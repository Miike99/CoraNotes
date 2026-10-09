"""Programación persistida de recordatorios y cierres.

Cada ejecución tiene una clave única en la tabla `ejecuciones` (p. ej. "rec:2026-10-09:18:00").
La inserción ocurre dentro de una transacción, así que un reinicio o una segunda ventana del
navegador no pueden duplicar avisos. Los horarios se recalculan en cada ciclo desde la
configuración vigente, por eso los cambios afectan a las ejecuciones siguientes.
"""
from __future__ import annotations

import logging
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo

from .calendar_logic import (DIAS, close_candidates, close_key, fmt_fecha, reminder_occurrences)
from .db import get_meta, rows
from .records import AppError, Conflict, NotFound, is_day_registered
from .util import parse_utc, utc_iso

log = logging.getLogger("coranotes.programador")

GRACE = timedelta(minutes=30)   # si se detecta más tarde, se agrupa como "perdido"
LOOKBACK_DAYS = 7
REMINDER_TEXT = "¿Qué hiciste hoy? Registrá tus avances, resultados, problemas y soluciones"


class Scheduler:
    def __init__(self, db, clock, settings, notices, closing, pet=None):
        self.pet = pet
        self.db = db
        self.clock = clock
        self.settings = settings
        self.notices = notices
        self.closing = closing
        self.last_tick = None
        self.last_tick_result: dict = {}

    def tick(self) -> dict:
        now = self.clock.now()
        rcfg = self.settings.get("recordatorio")
        pcfg = self.settings.get("presentacion")
        tz = ZoneInfo(rcfg.zona)
        today = now.astimezone(tz).date()
        reanudado = self.last_tick is None or (now - self.last_tick) > timedelta(minutes=5)
        self.last_tick = now
        with self.db.read() as c:
            installed = parse_utc(get_meta(c, "instalado_utc")) or now
        start = max(today - timedelta(days=LOOKBACK_DAYS), installed.astimezone(tz).date())

        due, lost, closes = [], [], []
        nowiso = utc_iso(now)
        with self.db.tx() as c:
            silenciado = self.pet is not None and self.pet.silenced_today(c)
            d = start
            while d <= today:
                for occ in reminder_occurrences(rcfg, d):
                    if occ.utc > now or occ.utc < installed:
                        continue
                    row = c.execute("SELECT * FROM ejecuciones WHERE clave = ?", (occ.clave,)).fetchone()
                    registered = is_day_registered(c, d.isoformat())
                    if row is None:
                        if registered:
                            estado = "registrado"
                        elif d == today and silenciado:
                            estado = "silenciado"
                        elif d == today and now - occ.utc <= GRACE:
                            estado = "avisado"
                            due.append(occ)
                        else:
                            estado = "perdido"
                            lost.append(occ)
                        c.execute("INSERT INTO ejecuciones(clave, tipo, fecha, programado_utc, estado, avisos, "
                                  "creado_utc, actualizado_utc) VALUES (?,?,?,?,?,?,?,?)",
                                  (occ.clave, occ.tipo, d.isoformat(), utc_iso(occ.utc), estado,
                                   1 if estado == "avisado" else 0, nowiso, nowiso))
                    elif row["estado"] == "pospuesto" and parse_utc(row["pospuesto_hasta_utc"]) <= now:
                        if registered:
                            nuevo = "registrado"
                        elif d == today and silenciado:
                            nuevo = "silenciado"
                        elif d == today:
                            nuevo = "avisado"
                            due.append(occ)
                        else:
                            nuevo = "perdido"
                        c.execute("UPDATE ejecuciones SET estado=?, pospuesto_hasta_utc=NULL, "
                                  "avisos = avisos + ?, actualizado_utc=? WHERE clave=?",
                                  (nuevo, 1 if nuevo == "avisado" else 0, nowiso, occ.clave))
                d += timedelta(days=1)

            for period in close_candidates(pcfg, today, tz):
                if period.cierre is None:
                    continue
                cierre_utc = period.cierre.astimezone(timezone.utc)
                if cierre_utc > now or cierre_utc < installed:
                    continue
                key = close_key(period)
                if c.execute("SELECT 1 FROM ejecuciones WHERE clave = ?", (key,)).fetchone():
                    continue
                c.execute("INSERT INTO ejecuciones(clave, tipo, fecha, programado_utc, estado, creado_utc, "
                          "actualizado_utc) VALUES (?,?,?,?,?,?,?)",
                          (key, "cierre", period.cierre.date().isoformat(), utc_iso(cierre_utc), "en_proceso",
                           nowiso, nowiso))
                closes.append((period, key, now - cierre_utc > GRACE))

        self._notify_reminders(due, lost)
        cierres = []
        for period, key, late in closes:
            try:
                res = self.closing.prepare(period, disparo="programado", tardio=late)
                detalle, estado = res.get("estado", ""), "ejecutado"
                cierres.append(res)
            except Exception:  # noqa: BLE001
                log.exception("Fallo al ejecutar el cierre programado")
                detalle, estado = "error", "error"
            with self.db.tx() as c:
                c.execute("UPDATE ejecuciones SET estado=?, detalle=?, actualizado_utc=? WHERE clave=?",
                          (estado, detalle, utc_iso(self.clock.now()), key))
        self.last_tick_result = {
            "momento_utc": nowiso, "reanudado": reanudado,
            "avisados": sorted({o.fecha.isoformat() for o in due}),
            "perdidos": sorted({o.fecha.isoformat() for o in lost}),
            "cierres": [c.get("id") for c in cierres],
        }
        return self.last_tick_result

    def reminder_channel(self) -> str:
        """«mascota» si Cora está visible; si no, notificación de Windows (si está habilitada) o solo app."""
        if self.pet is not None and self.pet.is_reminder_channel():
            return "mascota"
        if self.pet is None or self.settings.get("mascota").notificacion_respaldo:
            return "windows"
        return "app"

    def _notify_reminders(self, due, lost) -> None:
        due_dates = sorted({o.fecha for o in due})
        lost_dates = sorted({o.fecha for o in lost} - set(due_dates))
        if not due_dates and not lost_dates:
            return
        canal = self.reminder_channel()
        nativo = canal == "windows"  # nunca Cora + notificación a la vez
        if lost_dates:
            fechas = ", ".join(fmt_fecha(d) for d in lost_dates[:7])
            extra = " Además, hoy todavía no registraste actividad." if due_dates else ""
            mensaje = (f"Mientras la app no estuvo activa quedaron {len(lost_dates)} día(s) sin registrar: "
                       f"{fechas}.{extra} Podés completarlos desde Historial.")
            ruta = f"#/registro?fecha={due_dates[0].isoformat()}" if due_dates else "#/historial"
            self.notices.add("recordatorio_agrupado", "CoraNotes: días pendientes", mensaje, ruta, nativo=nativo,
                             acciones=[("Abrir CoraNotes", ruta)])
            return
        d = due_dates[0]
        texto = REMINDER_TEXT if canal != "mascota" else "Cora pidió su comida: registrá el día."
        self.notices.add("recordatorio", "CoraNotes", texto, f"#/registro?fecha={d.isoformat()}",
                         clave=due[0].clave, nativo=nativo,
                         acciones=[("Abrir registro", f"#/registro?fecha={d.isoformat()}"),
                                   ("Posponer o descartar", "#/inicio")])

    # ---------- acciones del usuario ----------
    def active_reminders(self) -> list[dict]:
        rcfg = self.settings.get("recordatorio")
        today = self.clock.now().astimezone(ZoneInfo(rcfg.zona)).date().isoformat()
        with self.db.read() as c:
            return rows(c.execute("SELECT clave, fecha, estado, avisos, pospuesto_hasta_utc FROM ejecuciones "
                                  "WHERE fecha = ? AND tipo IN ('recordatorio','puntual') "
                                  "AND estado IN ('avisado','pospuesto') ORDER BY programado_utc", (today,)))

    def snooze(self, clave: str) -> dict:
        rcfg = self.settings.get("recordatorio")
        now = self.clock.now()
        hasta = now + timedelta(minutes=rcfg.posponer_minutos)
        with self.db.tx() as c:
            row = c.execute("SELECT * FROM ejecuciones WHERE clave = ?", (clave,)).fetchone()
            if not row or row["tipo"] not in ("recordatorio", "puntual"):
                raise NotFound("No existe ese recordatorio")
            if row["estado"] not in ("avisado", "pospuesto"):
                raise Conflict("Ese recordatorio ya no está activo")
            if is_day_registered(c, row["fecha"]):
                raise Conflict("Ese día ya está registrado; no hace falta posponer")
            c.execute("UPDATE ejecuciones SET estado='pospuesto', pospuesto_hasta_utc=?, actualizado_utc=? "
                      "WHERE clave=?", (utc_iso(hasta), utc_iso(now), clave))
        return {"clave": clave, "pospuesto_hasta_utc": utc_iso(hasta)}

    def dismiss(self, clave: str) -> dict:
        with self.db.tx() as c:
            row = c.execute("SELECT * FROM ejecuciones WHERE clave = ?", (clave,)).fetchone()
            if not row:
                raise NotFound("No existe ese recordatorio")
            if row["estado"] not in ("avisado", "pospuesto"):
                raise AppError("Ese recordatorio ya no está activo")
            c.execute("UPDATE ejecuciones SET estado='descartado', pospuesto_hasta_utc=NULL, actualizado_utc=? "
                      "WHERE clave=?", (utc_iso(self.clock.now()), clave))
        return {"clave": clave, "estado": "descartado",
                "nota": "Descartar el aviso no registra actividad: el día sigue pendiente."}


__all__ = ["Scheduler", "REMINDER_TEXT", "DIAS"]
