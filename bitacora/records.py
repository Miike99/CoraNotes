"""Registros diarios: alta, edición con revisiones, papelera y estado de cada día."""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .db import get_meta, rows, set_meta
from .settings import format_validation_error
from .util import atomic_write_text, canonical_json, clean_text, new_id, normalize_key, utc_iso

TEXT_FIELDS = ("actividad", "avance", "problemas", "solucion", "proximos_pasos")
TIPOS_AVANCE = ("exploracion", "en_curso", "validado")
ESTADOS_PROBLEMA = ("sin_problema", "abierto", "en_curso", "resuelto")
SNAPSHOT_FIELDS = ("fecha", "proyecto", "tarea_id", *TEXT_FIELDS, "tipo_avance", "estado_problema",
                   "estado", "archivado", "incluir_ia")


class AppError(Exception):
    status = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFound(AppError):
    status = 404


class Conflict(AppError):
    status = 409


class InvalidData(AppError):
    status = 422


class RegistroIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fecha: date
    proyecto: str = Field("", max_length=120)
    tarea_id: str | None = Field(None, pattern=r"^TAR-[0-9A-F]{8}$")
    tarea_titulo: str = Field("", max_length=200)
    actividad: str = Field("", max_length=10_000)
    avance: str = Field("", max_length=10_000)
    problemas: str = Field("", max_length=10_000)
    solucion: str = Field("", max_length=10_000)
    proximos_pasos: str = Field("", max_length=10_000)
    tipo_avance: Literal["exploracion", "en_curso", "validado"] = "en_curso"
    estado_problema: Literal["sin_problema", "abierto", "en_curso", "resuelto"] = "sin_problema"
    incluir_ia: bool = True
    estado: Literal["borrador", "guardado"] = "guardado"
    revision_base: int | None = None

    @field_validator("proyecto", "tarea_titulo", *TEXT_FIELDS)
    @classmethod
    def _clean(cls, v: str) -> str:
        return clean_text(v)

    @model_validator(mode="after")
    def _check(self):
        if self.estado == "guardado" and (not self.proyecto or not self.actividad):
            raise ValueError("Para guardar el registro completá «proyecto» y «actividad realizada». "
                             "Si todavía no está listo, guardalo como borrador.")
        if abs((self.fecha - date.today()).days) > 3660:
            raise ValueError("La fecha de actividad está fuera de rango")
        return self


def parse_registro(data: dict) -> RegistroIn:
    try:
        return RegistroIn.model_validate(data)
    except ValidationError as exc:
        raise InvalidData(format_validation_error(exc)) from exc


def is_valid_record(rec: dict) -> bool:
    return rec["estado"] == "guardado" and not rec["archivado"] and bool(rec["actividad"].strip())


def is_day_registered(conn, fecha: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM registros WHERE fecha = ? AND estado = 'guardado' AND archivado = 0 "
        "AND trim(actividad) <> '' LIMIT 1", (fecha,)).fetchone()
    if row:
        return True
    return conn.execute("SELECT 1 FROM dias_sin_actividad WHERE fecha = ?", (fecha,)).fetchone() is not None


def mark_data_changed(conn, clock) -> None:
    set_meta(conn, "datos_cambiados_utc", utc_iso(clock.now()))


class RecordService:
    def __init__(self, db, clock, paths):
        self.db = db
        self.clock = clock
        self.paths = paths

    # ---------- lectura ----------
    _SELECT = ("SELECT r.*, t.titulo AS tarea_titulo FROM registros r "
               "LEFT JOIN tareas t ON t.id = r.tarea_id")

    def _fetch(self, conn, rec_id: str) -> dict:
        row = conn.execute(self._SELECT + " WHERE r.id = ?", (rec_id,)).fetchone()
        if not row:
            raise NotFound("No existe ese registro")
        rec = dict(row)
        rec["archivado"] = bool(rec["archivado"])
        rec["incluir_ia"] = bool(rec["incluir_ia"])
        rec["valido"] = is_valid_record(rec)
        rec["evidencias"] = rows(conn.execute(
            "SELECT id, nombre, mime, tamano FROM evidencias WHERE registro_id = ? AND archivado = 0", (rec_id,)))
        return rec

    def get(self, rec_id: str) -> dict:
        with self.db.read() as conn:
            return self._fetch(conn, rec_id)

    def list(self, desde: str | None = None, hasta: str | None = None, proyecto: str | None = None,
             archivados: Literal["no", "si", "solo"] = "no", limite: int = 500) -> list[dict]:
        sql = self._SELECT + " WHERE 1=1"
        params: list = []
        if desde:
            sql += " AND r.fecha >= ?"
            params.append(desde)
        if hasta:
            sql += " AND r.fecha <= ?"
            params.append(hasta)
        if proyecto:
            sql += " AND lower(r.proyecto) = lower(?)"
            params.append(proyecto)
        if archivados == "no":
            sql += " AND r.archivado = 0"
        elif archivados == "solo":
            sql += " AND r.archivado = 1"
        sql += " ORDER BY r.fecha DESC, r.creado_utc DESC LIMIT ?"
        params.append(max(1, min(limite, 2000)))
        with self.db.read() as conn:
            out = []
            for row in conn.execute(sql, params).fetchall():
                rec = dict(row)
                rec["archivado"] = bool(rec["archivado"])
                rec["incluir_ia"] = bool(rec["incluir_ia"])
                rec["valido"] = is_valid_record(rec)
                out.append(rec)
            return out

    def revisions(self, rec_id: str) -> list[dict]:
        with self.db.read() as conn:
            self._fetch(conn, rec_id)
            out = rows(conn.execute(
                "SELECT revision, datos, motivo, creado_utc FROM registro_revisiones WHERE registro_id = ? "
                "ORDER BY revision DESC", (rec_id,)))
        for r in out:
            r["datos"] = json.loads(r["datos"])
        return out

    def projects(self) -> list[str]:
        with self.db.read() as conn:
            return [r[0] for r in conn.execute(
                "SELECT DISTINCT proyecto FROM registros WHERE proyecto <> '' ORDER BY proyecto").fetchall()]

    def tasks(self, proyecto: str | None = None) -> list[dict]:
        with self.db.read() as conn:
            if proyecto:
                return rows(conn.execute("SELECT id, proyecto, titulo FROM tareas WHERE lower(proyecto) = lower(?) "
                                         "ORDER BY titulo", (proyecto,)))
            return rows(conn.execute("SELECT id, proyecto, titulo FROM tareas ORDER BY proyecto, titulo"))

    # ---------- escritura ----------
    def _resolve_task(self, conn, data: RegistroIn) -> str | None:
        if data.tarea_id:
            row = conn.execute("SELECT id FROM tareas WHERE id = ?", (data.tarea_id,)).fetchone()
            if not row:
                raise InvalidData("La tarea indicada no existe")
            return data.tarea_id
        if not data.tarea_titulo or not data.proyecto:
            return None
        norm = normalize_key(data.tarea_titulo)
        row = conn.execute("SELECT id FROM tareas WHERE proyecto = ? AND titulo_norm = ?",
                           (data.proyecto, norm)).fetchone()
        if row:
            return row["id"]
        tid = new_id("TAR")
        conn.execute("INSERT INTO tareas(id, proyecto, titulo, titulo_norm, creado_utc) VALUES (?,?,?,?,?)",
                     (tid, data.proyecto, data.tarea_titulo, norm, utc_iso(self.clock.now())))
        return tid

    def _snapshot(self, conn, rec_id: str, motivo: str) -> None:
        rec = conn.execute("SELECT * FROM registros WHERE id = ?", (rec_id,)).fetchone()
        datos = {k: rec[k] for k in SNAPSHOT_FIELDS}
        conn.execute("INSERT INTO registro_revisiones(registro_id, revision, datos, motivo, creado_utc) "
                     "VALUES (?,?,?,?,?)", (rec_id, rec["revision"], canonical_json(datos), motivo,
                                            utc_iso(self.clock.now())))

    def _after_save(self, conn, fecha: str, valid: bool) -> list[str]:
        efectos: list[str] = []
        mark_data_changed(conn, self.clock)
        if valid:
            cur = conn.execute("DELETE FROM dias_sin_actividad WHERE fecha = ?", (fecha,))
            if cur.rowcount:
                efectos.append("Se quitó la declaración «sin actividad» de ese día porque ahora tiene actividad.")
            cur = conn.execute(
                "UPDATE ejecuciones SET estado = 'registrado', pospuesto_hasta_utc = NULL, actualizado_utc = ? "
                "WHERE fecha = ? AND estado IN ('pospuesto', 'avisado')", (utc_iso(self.clock.now()), fecha))
            if cur.rowcount:
                efectos.append("Se cancelaron los recordatorios pendientes de ese día.")
        return efectos

    def create(self, data: RegistroIn, origen: str = "manual", documento_id: str | None = None,
               conn=None) -> tuple[dict, list[str]]:
        now = utc_iso(self.clock.now())
        with self.db.tx_or(conn) as c:
            rec_id = new_id("REG")
            while c.execute("SELECT 1 FROM registros WHERE id = ?", (rec_id,)).fetchone():
                rec_id = new_id("REG")
            tarea_id = self._resolve_task(c, data)
            c.execute(
                "INSERT INTO registros(id, fecha, proyecto, tarea_id, actividad, avance, tipo_avance, problemas, "
                "solucion, estado_problema, proximos_pasos, estado, incluir_ia, origen, documento_id, revision, "
                "creado_utc, actualizado_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)",
                (rec_id, data.fecha.isoformat(), data.proyecto, tarea_id, data.actividad, data.avance,
                 data.tipo_avance, data.problemas, data.solucion, data.estado_problema, data.proximos_pasos,
                 data.estado, int(data.incluir_ia), origen, documento_id, now, now))
            self._snapshot(c, rec_id, "creacion")
            rec = self._fetch(c, rec_id)
            efectos = self._after_save(c, rec["fecha"], rec["valido"])
        self.export_markdown(rec)
        return rec, efectos

    def update(self, rec_id: str, data: RegistroIn, motivo: str = "edicion", conn=None) -> tuple[dict, list[str]]:
        with self.db.tx_or(conn) as c:
            old = self._fetch(c, rec_id)
            if old["archivado"]:
                raise Conflict("El registro está en la papelera. Restauralo antes de editarlo.")
            if data.revision_base is not None and data.revision_base != old["revision"]:
                raise Conflict("El registro cambió en otra ventana o por una importación. Recargalo y volvé a "
                               "aplicar tus cambios (tu texto sigue en el formulario).")
            tarea_id = self._resolve_task(c, data)
            c.execute(
                "UPDATE registros SET fecha=?, proyecto=?, tarea_id=?, actividad=?, avance=?, tipo_avance=?, "
                "problemas=?, solucion=?, estado_problema=?, proximos_pasos=?, estado=?, incluir_ia=?, "
                "revision = revision + 1, actualizado_utc=? WHERE id=?",
                (data.fecha.isoformat(), data.proyecto, tarea_id, data.actividad, data.avance, data.tipo_avance,
                 data.problemas, data.solucion, data.estado_problema, data.proximos_pasos, data.estado,
                 int(data.incluir_ia), utc_iso(self.clock.now()), rec_id))
            self._snapshot(c, rec_id, motivo)
            rec = self._fetch(c, rec_id)
            efectos = self._after_save(c, rec["fecha"], rec["valido"])
        self.export_markdown(rec)
        return rec, efectos

    def set_include(self, rec_id: str, incluir: bool) -> dict:
        with self.db.tx() as c:
            old = self._fetch(c, rec_id)
            if old["incluir_ia"] == incluir:
                return old
            c.execute("UPDATE registros SET incluir_ia=?, revision = revision + 1, actualizado_utc=? WHERE id=?",
                      (int(incluir), utc_iso(self.clock.now()), rec_id))
            self._snapshot(c, rec_id, "incluir_ia" if incluir else "excluir_ia")
            mark_data_changed(c, self.clock)
            rec = self._fetch(c, rec_id)
        self.export_markdown(rec)
        return rec

    def archive(self, rec_id: str, motivo: str = "archivado", conn=None) -> dict:
        with self.db.tx_or(conn) as c:
            old = self._fetch(c, rec_id)
            if old["archivado"]:
                return old
            now = utc_iso(self.clock.now())
            c.execute("UPDATE registros SET archivado=1, archivado_utc=?, revision = revision + 1, actualizado_utc=? "
                      "WHERE id=?", (now, now, rec_id))
            self._snapshot(c, rec_id, motivo)
            mark_data_changed(c, self.clock)
            rec = self._fetch(c, rec_id)
        self.export_markdown(rec)
        return rec

    def restore(self, rec_id: str) -> tuple[dict, list[str]]:
        with self.db.tx() as c:
            old = self._fetch(c, rec_id)
            if not old["archivado"]:
                return old, []
            c.execute("UPDATE registros SET archivado=0, archivado_utc=NULL, revision = revision + 1, "
                      "actualizado_utc=? WHERE id=?", (utc_iso(self.clock.now()), rec_id))
            self._snapshot(c, rec_id, "restaurado")
            rec = self._fetch(c, rec_id)
            efectos = self._after_save(c, rec["fecha"], rec["valido"])
        self.export_markdown(rec)
        return rec, efectos

    def purge(self, rec_id: str) -> None:
        """Borrado definitivo, solo desde la papelera y por pedido explícito."""
        with self.db.tx() as c:
            rec = self._fetch(c, rec_id)
            if not rec["archivado"]:
                raise Conflict("Solo se pueden eliminar definitivamente registros que están en la papelera.")
            c.execute("DELETE FROM registro_revisiones WHERE registro_id = ?", (rec_id,))
            c.execute("UPDATE evidencias SET registro_id = NULL WHERE registro_id = ?", (rec_id,))
            c.execute("UPDATE documentos SET registro_id = NULL WHERE registro_id = ?", (rec_id,))
            c.execute("DELETE FROM registros WHERE id = ?", (rec_id,))
            mark_data_changed(c, self.clock)
        path = self.markdown_path(rec)
        if path.exists():
            path.unlink()

    # ---------- días ----------
    def declare_no_activity(self, fecha: date, nota: str = "") -> list[str]:
        f = fecha.isoformat()
        with self.db.tx() as c:
            valid = c.execute("SELECT count(*) FROM registros WHERE fecha = ? AND estado='guardado' AND archivado=0 "
                              "AND trim(actividad) <> ''", (f,)).fetchone()[0]
            if valid:
                raise Conflict("Ese día ya tiene actividad registrada. Si querés declarar que no hubo actividad, "
                               "primero mandá esos registros a la papelera.")
            c.execute("INSERT INTO dias_sin_actividad(fecha, nota, creado_utc) VALUES (?,?,?) "
                      "ON CONFLICT(fecha) DO UPDATE SET nota = excluded.nota",
                      (f, clean_text(nota, 500), utc_iso(self.clock.now())))
            c.execute("UPDATE ejecuciones SET estado='registrado', pospuesto_hasta_utc=NULL, actualizado_utc=? "
                      "WHERE fecha = ? AND estado IN ('pospuesto','avisado')", (utc_iso(self.clock.now()), f))
            mark_data_changed(c, self.clock)
        return ["Día marcado como «sin actividad para registrar». Podés corregirlo si después agregás actividad."]

    def remove_declaration(self, fecha: date) -> None:
        with self.db.tx() as c:
            c.execute("DELETE FROM dias_sin_actividad WHERE fecha = ?", (fecha.isoformat(),))
            mark_data_changed(c, self.clock)

    def day_status(self, fecha: date, conn=None) -> dict:
        f = fecha.isoformat()

        def _q(c):
            counts = c.execute(
                "SELECT sum(CASE WHEN estado='guardado' AND archivado=0 AND trim(actividad)<>'' THEN 1 ELSE 0 END), "
                "sum(CASE WHEN estado='borrador' AND archivado=0 THEN 1 ELSE 0 END) FROM registros WHERE fecha = ?",
                (f,)).fetchone()
            decl = c.execute("SELECT nota FROM dias_sin_actividad WHERE fecha = ?", (f,)).fetchone()
            validos = counts[0] or 0
            return {"fecha": f, "validos": validos, "borradores": counts[1] or 0,
                    "sin_actividad": decl is not None,
                    "registrado": bool(validos) or decl is not None,
                    "motivo": "actividad" if validos else ("sin_actividad" if decl else None)}
        if conn is not None:
            return _q(conn)
        with self.db.read() as c:
            return _q(c)

    def days_status(self, desde: date, hasta: date) -> list[dict]:
        out = []
        with self.db.read() as c:
            d = desde
            while d <= hasta and len(out) < 400:
                out.append(self.day_status(d, c))
                d += timedelta(days=1)
        return out

    # ---------- exportación Markdown ----------
    def markdown_path(self, rec: dict):
        y, m, _ = rec["fecha"].split("-")
        return self.paths.historial / "registros" / y / m / f"{rec['fecha']}_{rec['id']}.md"

    @staticmethod
    def markdown_text(rec: dict) -> str:
        meta = {
            "id": rec["id"], "fecha": rec["fecha"], "proyecto": rec["proyecto"],
            "tarea_id": rec.get("tarea_id"), "tarea": rec.get("tarea_titulo"), "estado": rec["estado"],
            "archivado": bool(rec["archivado"]), "tipo_avance": rec["tipo_avance"],
            "estado_problema": rec["estado_problema"], "incluir_ia": bool(rec["incluir_ia"]),
            "origen": rec["origen"], "documento_id": rec.get("documento_id"), "revision": rec["revision"],
            "actualizado_utc": rec["actualizado_utc"],
        }
        lines = ["---"]
        for k, v in meta.items():
            lines.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
        lines.append("---")
        titles = {"actividad": "Actividad realizada", "avance": "Avance o resultado", "problemas": "Problemas",
                  "solucion": "Solución o estado del problema", "proximos_pasos": "Próximos pasos"}
        for key, title in titles.items():
            lines += ["", f"## {title}", "", rec.get(key) or "_(sin completar)_"]
        if rec.get("evidencias"):
            lines += ["", "## Evidencias", ""]
            lines += [f"- {e['id']} · {e['nombre']}" for e in rec["evidencias"]]
        return "\n".join(lines) + "\n"

    def export_markdown(self, rec: dict) -> None:
        try:
            atomic_write_text(self.markdown_path(rec), self.markdown_text(rec))
        except OSError:
            # La copia legible es secundaria: SQLite ya tiene el dato.
            pass
