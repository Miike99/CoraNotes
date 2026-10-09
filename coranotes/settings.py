"""Ajustes persistidos en SQLite y validados con Pydantic."""
from __future__ import annotations

import json
from datetime import date
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .util import clean_text, new_id, utc_iso

HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class Puntual(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: new_id("PUN"), pattern=r"^PUN-[0-9A-F]{8}$")
    fecha: date
    hora: str = Field(pattern=HHMM)


class RecordatorioCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dias: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    hora: str = Field("18:00", pattern=HHMM)
    zona: str = "America/Argentina/Buenos_Aires"
    pausado: bool = False
    pausa_hasta: date | None = None
    excepciones: list[date] = Field(default_factory=list, max_length=500)
    puntuales: list[Puntual] = Field(default_factory=list, max_length=100)
    posponer_minutos: int = Field(15, ge=5, le=120)

    @field_validator("dias")
    @classmethod
    def _dias(cls, v: list[int]) -> list[int]:
        if any(d < 0 or d > 6 for d in v):
            raise ValueError("Los días deben ir de 0 (lunes) a 6 (domingo)")
        return sorted(set(v))

    @field_validator("zona")
    @classmethod
    def _zona(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Zona horaria desconocida: {v}") from exc
        return v

    @field_validator("excepciones")
    @classmethod
    def _exc(cls, v: list[date]) -> list[date]:
        return sorted(set(v))


class PresentacionCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    periodo: Literal["semana_laboral", "semana_completa", "personalizado"] = "semana_laboral"
    inicio: date | None = None
    fin: date | None = None
    dia_cierre: int = Field(4, ge=0, le=6)
    hora_cierre: str = Field("18:30", pattern=HHMM)
    fecha_cierre: date | None = None
    cierre_activo: bool = True
    proyectos: list[str] = Field(default_factory=list, max_length=50)
    audiencia: str = Field("Equipo del proyecto y responsables", max_length=200)
    max_diapositivas: int = Field(6, ge=1, le=20)

    @field_validator("proyectos")
    @classmethod
    def _proyectos(cls, v: list[str]) -> list[str]:
        out = []
        for p in v:
            p = clean_text(p, 120)
            if p and p.lower() not in [x.lower() for x in out]:
                out.append(p)
        return out

    @field_validator("audiencia")
    @classmethod
    def _aud(cls, v: str) -> str:
        return clean_text(v, 200)

    @model_validator(mode="after")
    def _personalizado(self):
        if self.periodo == "personalizado":
            if not self.inicio or not self.fin:
                raise ValueError("El período personalizado necesita fecha de inicio y de fin")
            if self.inicio > self.fin:
                raise ValueError("La fecha de inicio debe ser anterior o igual a la de fin")
            if (self.fin - self.inicio).days > 62:
                raise ValueError("El período personalizado no puede superar 62 días")
            if self.fecha_cierre and self.fecha_cierre < self.inicio:
                raise ValueError("La fecha de cierre no puede ser anterior al inicio del período")
        return self


class IACfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    modo: Literal["plantilla", "gemini", "demo"] = "plantilla"
    consentimiento: bool = False
    consentimiento_utc: str | None = None
    pausada: bool = False
    espera_segundos: int = Field(60, ge=10, le=3600)
    max_intentos_diarios: int = Field(20, ge=1, le=500)
    timeout_segundos: int = Field(60, ge=10, le=300)
    max_caracteres_entrada: int = Field(40000, ge=2000, le=400000)
    max_tokens_salida: int = Field(4096, ge=512, le=32768)
    reintentos_transitorios: int = Field(3, ge=0, le=5)


class EntradaCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    carpeta: str | None = Field(None, max_length=400)
    activa: bool = False


class LimitesCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    texto_mb: float = Field(2, gt=0, le=20)
    documento_mb: float = Field(10, gt=0, le=50)
    pdf_paginas: int = Field(50, ge=1, le=500)
    max_caracteres_extraidos: int = Field(100_000, ge=1000, le=2_000_000)
    docx_descomprimido_mb: float = Field(30, gt=0, le=200)

    @property
    def texto_bytes(self) -> int:
        return int(self.texto_mb * 1024 * 1024)

    @property
    def documento_bytes(self) -> int:
        return int(self.documento_mb * 1024 * 1024)

    @property
    def docx_bytes(self) -> int:
        return int(self.docx_descomprimido_mb * 1024 * 1024)


class MascotaCfg(BaseModel):
    """Cora, la mascota de escritorio: canal principal de recordatorio."""
    model_config = ConfigDict(extra="forbid")
    habilitada: bool = True
    tamano: Literal["chico", "mediano", "grande"] = "mediano"
    siempre_visible: bool = True
    sonidos: bool = True   # maullidos y sonidos de gato (se pueden apagar)
    reducir_animaciones: bool = False
    lugar_dormir: Literal["escritorio", "ventanas", "barra_tareas"] = "escritorio"
    notificacion_respaldo: bool = True  # notificación de Windows si Cora está oculta o cerrada
    posicion_x: int | None = Field(None, ge=-100_000, le=100_000)
    posicion_y: int | None = Field(None, ge=-100_000, le=100_000)


SECTIONS: dict[str, type[BaseModel]] = {
    "recordatorio": RecordatorioCfg,
    "presentacion": PresentacionCfg,
    "ia": IACfg,
    "entrada": EntradaCfg,
    "limites": LimitesCfg,
    "mascota": MascotaCfg,
}


class SettingsError(ValueError):
    pass


def format_validation_error(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err.get("loc", ()) if x != "__root__")
        msg = str(err.get("msg", "valor inválido")).replace("Value error, ", "")
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts) or "Datos inválidos"


class SettingsStore:
    def __init__(self, db, clock):
        self.db = db
        self.clock = clock

    def get(self, section: str, conn=None):
        model = SECTIONS[section]
        if conn is None:
            with self.db.read() as c:
                row = c.execute("SELECT valor FROM ajustes WHERE clave = ?", (section,)).fetchone()
        else:
            row = conn.execute("SELECT valor FROM ajustes WHERE clave = ?", (section,)).fetchone()
        if row:
            try:
                return model.model_validate(json.loads(row["valor"]))
            except (ValidationError, json.JSONDecodeError):
                pass
        return model()

    def all(self) -> dict[str, BaseModel]:
        with self.db.read() as conn:
            return {name: self.get(name, conn) for name in SECTIONS}

    def set(self, section: str, data, conn=None):
        model = SECTIONS.get(section)
        if model is None:
            raise SettingsError("Sección de configuración desconocida")
        try:
            value = data if isinstance(data, model) else model.model_validate(data)
        except ValidationError as exc:
            raise SettingsError(format_validation_error(exc)) from exc
        payload = value.model_dump_json()
        with self.db.tx_or(conn) as c:
            c.execute(
                "INSERT INTO ajustes(clave, valor, actualizado_utc) VALUES (?, ?, ?) "
                "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor, actualizado_utc = excluded.actualizado_utc",
                (section, payload, utc_iso(self.clock.now())),
            )
        return value

    def update(self, section: str, changes: dict, conn=None):
        current = self.get(section, conn).model_dump(mode="json")
        current.update(changes)
        return self.set(section, current, conn)
