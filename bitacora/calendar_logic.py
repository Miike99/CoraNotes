"""Cálculo de recordatorios y períodos en la zona horaria elegida."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .settings import PresentacionCfg, RecordatorioCfg

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def parse_hhmm(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def local_dt(day: date, hhmm: str, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, parse_hhmm(hhmm), tzinfo=tz)


def fmt_fecha(day: date) -> str:
    return day.strftime("%d/%m/%Y")


@dataclass(frozen=True)
class Occurrence:
    clave: str
    tipo: str  # recordatorio | puntual
    fecha: date
    local: datetime

    @property
    def utc(self) -> datetime:
        return self.local.astimezone(timezone.utc)


def is_paused(cfg: RecordatorioCfg, day: date) -> bool:
    if not cfg.pausado:
        return False
    return cfg.pausa_hasta is None or day <= cfg.pausa_hasta


def reminder_occurrences(cfg: RecordatorioCfg, day: date) -> list[Occurrence]:
    tz = ZoneInfo(cfg.zona)
    if is_paused(cfg, day):
        return []
    out: list[Occurrence] = []
    if day.weekday() in cfg.dias and day not in cfg.excepciones:
        out.append(Occurrence(f"rec:{day.isoformat()}:{cfg.hora}", "recordatorio", day, local_dt(day, cfg.hora, tz)))
    for p in cfg.puntuales:
        if p.fecha == day:
            out.append(Occurrence(f"pun:{p.id}:{day.isoformat()}:{p.hora}", "puntual", day, local_dt(day, p.hora, tz)))
    return sorted(out, key=lambda o: o.local)


@dataclass(frozen=True)
class Period:
    inicio: date
    fin: date
    cierre: datetime | None  # hora local de cierre

    @property
    def clave(self) -> str:
        return f"{self.inicio.isoformat()}_{self.fin.isoformat()}"

    @property
    def etiqueta(self) -> str:
        return f"{fmt_fecha(self.inicio)} al {fmt_fecha(self.fin)}"

    def contains(self, day: date) -> bool:
        return self.inicio <= day <= self.fin

    @staticmethod
    def from_clave(clave: str) -> "Period":
        a, b = clave.split("_")
        return Period(date.fromisoformat(a), date.fromisoformat(b), None)


def period_for(pcfg: PresentacionCfg, ref: date, tz: ZoneInfo) -> Period:
    if pcfg.periodo == "personalizado" and pcfg.inicio and pcfg.fin:
        cierre_dia = pcfg.fecha_cierre or pcfg.fin
        return Period(pcfg.inicio, pcfg.fin, local_dt(cierre_dia, pcfg.hora_cierre, tz))
    monday = ref - timedelta(days=ref.weekday())
    fin = monday + timedelta(days=4 if pcfg.periodo == "semana_laboral" else 6)
    cierre = local_dt(monday + timedelta(days=pcfg.dia_cierre), pcfg.hora_cierre, tz)
    return Period(monday, fin, cierre)


def close_candidates(pcfg: PresentacionCfg, today: date, tz: ZoneInfo) -> list[Period]:
    """Período actual y el anterior (por si el cierre se perdió con la PC apagada)."""
    if not pcfg.cierre_activo:
        return []
    if pcfg.periodo == "personalizado":
        return [period_for(pcfg, today, tz)]
    return [period_for(pcfg, today - timedelta(days=7), tz), period_for(pcfg, today, tz)]


def close_key(period: Period) -> str:
    return f"cie:{period.clave}:{period.cierre.isoformat() if period.cierre else ''}"


def next_runs(rcfg: RecordatorioCfg, pcfg: PresentacionCfg, now: datetime, limit: int = 6) -> list[dict]:
    tz = ZoneInfo(rcfg.zona)
    today = now.astimezone(tz).date()
    items: list[dict] = []
    for i in range(0, 21):
        d = today + timedelta(days=i)
        for occ in reminder_occurrences(rcfg, d):
            if occ.utc > now:
                items.append({"tipo": occ.tipo, "fecha": d.isoformat(), "local": occ.local.isoformat(),
                              "descripcion": f"Recordatorio {DIAS[d.weekday()]} {fmt_fecha(d)} {occ.local:%H:%M}"})
    seen = set()
    for i in range(0, 21, 7):
        if not pcfg.cierre_activo:
            break
        p = period_for(pcfg, today + timedelta(days=i), tz)
        if p.cierre and p.cierre.astimezone(timezone.utc) > now and p.clave not in seen:
            seen.add(p.clave)
            items.append({"tipo": "cierre", "fecha": p.cierre.date().isoformat(), "local": p.cierre.isoformat(),
                          "descripcion": f"Cierre del período {p.etiqueta}: {DIAS[p.cierre.weekday()]} {p.cierre:%H:%M}"})
    items.sort(key=lambda x: x["local"])
    return items[:limit]


def close_warning(rcfg: RecordatorioCfg, pcfg: PresentacionCfg, today: date) -> str | None:
    """Avisa si el cierre ocurre antes del último recordatorio del período."""
    tz = ZoneInfo(rcfg.zona)
    p = period_for(pcfg, today, tz)
    if not p.cierre or not pcfg.cierre_activo:
        return None
    later = []
    d = p.inicio
    while d <= p.fin:
        for occ in reminder_occurrences(rcfg, d):
            if occ.local > p.cierre:
                later.append(occ)
        d += timedelta(days=1)
    if not later:
        return None
    last = later[-1]
    return (f"El cierre ({DIAS[p.cierre.weekday()]} {p.cierre:%H:%M}) ocurre antes del último recordatorio del "
            f"período ({DIAS[last.fecha.weekday()]} {last.local:%H:%M}). Lo que registres después del cierre "
            f"aparecerá como «cambios posteriores al cierre» y podrás preparar otra versión.")
