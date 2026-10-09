"""Versiones del prompt (borrador automático, versión editada, instantáneas) y cierres."""
from __future__ import annotations

import difflib
import json
import logging
from zoneinfo import ZoneInfo

from .ai.prompt_builder import build_prompt
from .ai.schema import Resumen
from .ai.sources import collect_sources, data_hash, input_hash
from .ai.template_summary import build_template_summary
from .calendar_logic import Period, fmt_fecha
from .db import rows
from .records import AppError, Conflict, NotFound
from .secrets_guard import redact
from .util import atomic_write_text, clean_text, new_id, sha256_text, utc_iso

log = logging.getLogger("coranotes.prompts")

TIPOS = {"auto": "Borrador automático", "manual": "Mi versión editada", "cierre": "Instantánea de cierre"}
MAX_PROMPT = 200_000


class PromptService:
    def __init__(self, db, clock, settings, paths):
        self.db = db
        self.clock = clock
        self.settings = settings
        self.paths = paths

    def local_now_str(self) -> str:
        tz = ZoneInfo(self.settings.get("recordatorio").zona)
        return self.clock.now().astimezone(tz).strftime("%d/%m/%Y %H:%M")

    def create_version(self, conn, period: Period, tipo: str, modo: str, hash_entrada: str, hash_datos: str,
                       fuentes: list, resumen: dict | None, advertencias: list[str], contenido: str,
                       es_respaldo: bool = False, base_version_id: str | None = None, nota: str = "") -> dict:
        contenido = redact(contenido)
        vid = new_id("VER")
        conn.execute(
            "INSERT INTO versiones_prompt(id, periodo_clave, periodo_inicio, periodo_fin, tipo, modo, es_respaldo, "
            "hash_entrada, hash_datos, hash_contenido, fuentes, resumen, advertencias, contenido, base_version_id, "
            "nota, creado_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (vid, period.clave, period.inicio.isoformat(), period.fin.isoformat(), tipo, modo, int(es_respaldo),
             hash_entrada, hash_datos, sha256_text(contenido), json.dumps(fuentes, ensure_ascii=False),
             json.dumps(resumen, ensure_ascii=False) if resumen is not None else None,
             json.dumps(advertencias, ensure_ascii=False), contenido, base_version_id, nota,
             utc_iso(self.clock.now())))
        version = self._get(conn, vid)
        try:
            atomic_write_text(self.paths.historial / "prompts" / period.clave / f"{version['creado_utc'][:10]}_{vid}.md",
                              contenido)
        except OSError:
            log.warning("No se pudo escribir la copia en historial de una versión")
        return version

    @staticmethod
    def _decode(row) -> dict:
        v = dict(row)
        v["fuentes"] = json.loads(v["fuentes"])
        v["resumen"] = json.loads(v["resumen"]) if v.get("resumen") else None
        v["advertencias"] = json.loads(v["advertencias"] or "[]")
        v["es_respaldo"] = bool(v["es_respaldo"])
        v["tipo_texto"] = TIPOS.get(v["tipo"], v["tipo"])
        return v

    def _get(self, conn, vid: str) -> dict:
        row = conn.execute("SELECT * FROM versiones_prompt WHERE id = ?", (vid,)).fetchone()
        if not row:
            raise NotFound("No existe esa versión")
        return self._decode(row)

    def get(self, vid: str) -> dict:
        with self.db.read() as c:
            return self._get(c, vid)

    def latest(self, conn, clave: str, tipo: str, hash_entrada: str | None = None) -> dict | None:
        sql = "SELECT * FROM versiones_prompt WHERE periodo_clave = ? AND tipo = ?"
        params = [clave, tipo]
        if hash_entrada:
            sql += " AND hash_entrada = ?"
            params.append(hash_entrada)
        row = conn.execute(sql + " ORDER BY creado_utc DESC, rowid DESC LIMIT 1", params).fetchone()
        return self._decode(row) if row else None

    def list_versions(self, clave: str | None = None, limite: int = 100) -> list[dict]:
        sql = ("SELECT id, periodo_clave, periodo_inicio, periodo_fin, tipo, modo, es_respaldo, hash_entrada, "
               "hash_datos, hash_contenido, base_version_id, nota, creado_utc, fuentes FROM versiones_prompt")
        params: list = []
        if clave:
            sql += " WHERE periodo_clave = ?"
            params.append(clave)
        sql += " ORDER BY creado_utc DESC, rowid DESC LIMIT ?"
        params.append(limite)
        with self.db.read() as c:
            out = rows(c.execute(sql, params))
        for v in out:
            v["fuentes"] = json.loads(v["fuentes"])
            v["es_respaldo"] = bool(v["es_respaldo"])
            v["tipo_texto"] = TIPOS.get(v["tipo"], v["tipo"])
        return out

    def diff(self, a: str, b: str) -> str:
        va, vb = self.get(a), self.get(b)
        lines = difflib.unified_diff(va["contenido"].splitlines(), vb["contenido"].splitlines(),
                                     fromfile=f"{va['id']} ({va['tipo_texto']})",
                                     tofile=f"{vb['id']} ({vb['tipo_texto']})", lineterm="", n=2)
        return "\n".join(lines) or "(sin diferencias)"

    def save_manual(self, clave: str, contenido: str, base_version_id: str | None, nota: str = "") -> dict:
        contenido = clean_text(contenido)
        if not contenido:
            raise AppError("El prompt editado está vacío")
        if len(contenido) > MAX_PROMPT:
            raise AppError("El prompt editado es demasiado largo")
        period = Period.from_clave(clave)
        with self.db.tx() as c:
            base = self._get(c, base_version_id) if base_version_id else self.latest(c, clave, "auto")
            if base is None:
                raise Conflict("Todavía no hay un borrador para este período. Usá «Actualizar prompt» primero.")
            if base["periodo_clave"] != clave:
                raise Conflict("La versión base corresponde a otro período")
            return self.create_version(c, period, "manual", base["modo"], base["hash_entrada"], base["hash_datos"],
                                       base["fuentes"], base["resumen"], base["advertencias"], contenido,
                                       base["es_respaldo"], base["id"], nota or f"Editada a partir de {base['id']}")

    def recover(self, vid: str) -> dict:
        v = self.get(vid)
        return self.save_manual(v["periodo_clave"], v["contenido"], vid, nota=f"Recuperada como copia de {vid}")


class ClosingService:
    def __init__(self, db, clock, settings, prompts: PromptService, notices):
        self.db = db
        self.clock = clock
        self.settings = settings
        self.prompts = prompts
        self.notices = notices
        self.ai = None  # se asigna después (dependencia circular)

    def _get(self, conn, cid: str) -> dict:
        row = conn.execute("SELECT * FROM cierres WHERE id = ?", (cid,)).fetchone()
        if not row:
            raise NotFound("No existe ese cierre")
        return dict(row)

    def get(self, cid: str) -> dict:
        with self.db.read() as c:
            return self._get(c, cid)

    def _update(self, cid: str, **fields) -> None:
        fields["actualizado_utc"] = utc_iso(self.clock.now())
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self.db.tx() as c:
            c.execute(f"UPDATE cierres SET {cols} WHERE id = ?", (*fields.values(), cid))

    def prepare(self, period: Period, disparo: str = "manual", tardio: bool = False) -> dict:
        pcfg = self.settings.get("presentacion")
        modo, _, modelo = self.ai.mode_info()
        now = utc_iso(self.clock.now())
        cid = new_id("CIE")
        with self.db.tx() as c:
            sources = collect_sources(c, period, pcfg)
            hd = data_hash(sources, pcfg)
            empty = not sources["registros"]
            estado = "sin_contenido" if empty else "preparando"
            mensaje = ("No hay registros válidos en el período: no se preparó ningún prompt ni presentación."
                       if empty else "Preparando el prompt…")
            c.execute("INSERT INTO cierres(id, periodo_clave, periodo_inicio, periodo_fin, disparo, estado, mensaje, "
                      "hash_datos, creado_utc, actualizado_utc) VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (cid, period.clave, period.inicio.isoformat(), period.fin.isoformat(), disparo, estado,
                       mensaje, hd, now, now))
        if empty:
            self.notices.add("cierre_sin_contenido", "CoraNotes: cierre sin contenido",
                             f"El período {period.etiqueta} no tiene registros válidos. No se preparó un prompt.",
                             "#/prompt", nativo=(disparo == "programado"))
            return self.get(cid)
        hi = input_hash(hd, modo, modelo)
        with self.db.read() as c:
            vigente = self.prompts.latest(c, period.clave, "auto", hi)
        if vigente:
            return self.finalize(cid, vigente, tardio)
        if modo == "gemini":
            ok, why = self.ai.gemini_ready()
            if not ok:
                return self.mark_pending(cid, why)
        res = self.ai.enqueue(period, "cierre", cierre_id=cid, force=True)
        if modo != "gemini" and res.get("trabajo_id"):
            self.ai.run_job(res["trabajo_id"])
        else:
            self._update(cid, mensaje="Esperando la respuesta de Gemini…")
        return self.get(cid)

    def finalize(self, cid: str, version: dict, tardio: bool = False) -> dict:
        period = Period.from_clave(version["periodo_clave"])
        with self.db.tx() as c:
            cierre = self._get(c, cid)
            manual = self.prompts.latest(c, period.clave, "manual")
            if manual:
                contenido = manual["contenido"]
                nota = f"Instantánea de tu versión editada {manual['id']}"
                if manual["hash_datos"] != version["hash_datos"]:
                    nota += (". Atención: tu versión editada se basa en datos anteriores; revisá el borrador "
                             f"{version['id']} y reemplazá tu versión si corresponde")
                base = manual
            else:
                contenido = version["contenido"]
                nota = f"Instantánea del borrador {version['id']}"
                base = version
            snap = self.prompts.create_version(
                c, period, "cierre", version["modo"], version["hash_entrada"], version["hash_datos"],
                version["fuentes"], version["resumen"], version["advertencias"], contenido,
                version["es_respaldo"], base["id"], nota)
            estado = "listo_respaldo" if version["es_respaldo"] else "listo"
            mensaje = ("Prompt listo para copiar en Claude (generado con plantilla sin IA como respaldo)."
                       if version["es_respaldo"] else "Prompt listo para copiar en Claude.")
            c.execute("UPDATE cierres SET estado=?, version_id=?, hash_datos=?, mensaje=?, actualizado_utc=? "
                      "WHERE id=?", (estado, snap["id"], version["hash_datos"], mensaje + " " + nota + ".",
                                     utc_iso(self.clock.now()), cid))
        extra = " Se usó la plantilla sin IA (respaldo)." if version["es_respaldo"] else ""
        tarde = " (se ejecutó al reanudar la app)" if tardio else ""
        self.notices.add("cierre_listo", "CoraNotes: prompt listo",
                         f"El prompt del período {period.etiqueta} está listo{tarde}. Copialo en Claude para "
                         f"generar la presentación; todavía no se generó ninguna presentación.{extra}",
                         "#/prompt", nativo=(cierre["disparo"] == "programado"))
        return self.get(cid)

    def mark_pending(self, cid: str, mensaje: str) -> dict:
        cierre = self.get(cid)
        self._update(cid, estado="pendiente",
                     mensaje=f"{mensaje} Podés reintentar o usar la plantilla sin IA (respaldo).")
        self.notices.add("cierre_pendiente", "CoraNotes: prompt pendiente",
                         "No se pudo preparar el prompt con Gemini. Abrí la app para reintentar o usar la "
                         "plantilla sin IA.", "#/prompt", nativo=(cierre["disparo"] == "programado"))
        return self.get(cid)

    def retry(self, cid: str) -> dict:
        cierre = self.get(cid)
        if cierre["estado"] not in ("pendiente", "error"):
            raise Conflict("Solo se puede reintentar un cierre pendiente")
        period = Period.from_clave(cierre["periodo_clave"])
        modo, _, _ = self.ai.mode_info()
        if modo == "gemini":
            ok, why = self.ai.gemini_ready()
            if not ok:
                raise Conflict(why)
        self._update(cid, estado="preparando", mensaje="Reintentando…")
        res = self.ai.enqueue(period, "cierre_manual", cierre_id=cid, force=True)
        if modo != "gemini" and res.get("trabajo_id"):
            self.ai.run_job(res["trabajo_id"])
        return self.get(cid)

    def fallback(self, cid: str) -> dict:
        cierre = self.get(cid)
        if cierre["estado"] not in ("pendiente", "error", "preparando"):
            raise Conflict("El respaldo sin IA solo se usa cuando el cierre quedó pendiente")
        period = Period.from_clave(cierre["periodo_clave"])
        pcfg = self.settings.get("presentacion")
        with self.db.tx() as c:
            sources = collect_sources(c, period, pcfg)
            if not sources["registros"]:
                raise Conflict("No hay registros válidos en el período")
            hd = data_hash(sources, pcfg)
            resumen: Resumen = build_template_summary(sources)
            contenido = build_prompt(resumen, sources, pcfg, "Plantilla sin IA (respaldo)",
                                     self.prompts.local_now_str(), respaldo=True)
            version = self.prompts.create_version(
                c, period, "auto", "plantilla (respaldo)", input_hash(hd, "plantilla", "plantilla"), hd,
                [{"id": r["id"], "revision": r["revision"]} for r in sources["registros"]],
                resumen.model_dump(), [], contenido, es_respaldo=True, nota="Respaldo sin IA elegido por el usuario")
            c.execute("UPDATE trabajos_ia SET estado='descartado', actualizado_utc=? WHERE cierre_id=? "
                      "AND estado IN ('en_cola')", (utc_iso(self.clock.now()), cid))
        return self.finalize(cid, version)

    def list(self, clave: str | None = None, limite: int = 30) -> list[dict]:
        pcfg = self.settings.get("presentacion")
        with self.db.read() as c:
            sql = "SELECT * FROM cierres"
            params: list = []
            if clave:
                sql += " WHERE periodo_clave = ?"
                params.append(clave)
            out = rows(c.execute(sql + " ORDER BY creado_utc DESC LIMIT ?", (*params, limite)))
            hashes: dict[str, str] = {}
            for ci in out:
                if ci["periodo_clave"] not in hashes:
                    period = Period.from_clave(ci["periodo_clave"])
                    hashes[ci["periodo_clave"]] = data_hash(collect_sources(c, period, pcfg), pcfg)
                ci["cambios_posteriores"] = (ci["estado"] in ("listo", "listo_respaldo")
                                             and ci["hash_datos"] != hashes[ci["periodo_clave"]])
                ci["etiqueta"] = f"{fmt_fecha(Period.from_clave(ci['periodo_clave']).inicio)} al " \
                                 f"{fmt_fecha(Period.from_clave(ci['periodo_clave']).fin)}"
        return out

    def register_presentation(self, cid: str, version_usada_id: str | None, referencia: str,
                              evidencia_id: str | None) -> dict:
        with self.db.tx() as c:
            self._get(c, cid)
            if version_usada_id and not c.execute("SELECT 1 FROM versiones_prompt WHERE id = ?",
                                                  (version_usada_id,)).fetchone():
                raise NotFound("No existe la versión indicada")
            if evidencia_id and not c.execute("SELECT 1 FROM evidencias WHERE id = ?", (evidencia_id,)).fetchone():
                raise NotFound("No existe el archivo indicado")
            c.execute("UPDATE cierres SET version_usada_id=?, presentacion_ref=?, presentacion_evidencia_id=?, "
                      "actualizado_utc=? WHERE id=?",
                      (version_usada_id, clean_text(referencia, 500), evidencia_id, utc_iso(self.clock.now()), cid))
        return self.get(cid)
