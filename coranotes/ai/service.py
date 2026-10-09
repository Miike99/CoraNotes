"""Cola persistida de trabajos de IA: un trabajo a la vez, agrupación de cambios y control de consumo."""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from ..calendar_logic import Period, period_for
from ..db import get_meta, rows, set_meta
from ..util import parse_utc, utc_iso
from .prompt_builder import build_prompt
from .providers import AIError, GeminiProvider, SimulatedProvider, TemplateProvider
from .schema import InvalidAIResponse, validate_summary
from .sources import collect_sources, data_hash, input_hash

log = logging.getLogger("coranotes.ia")

BACKOFF = [30, 120, 300, 600, 900]
GEMINI_RESET_TZ = ZoneInfo("America/Los_Angeles")  # las cuotas diarias se reinician a medianoche del Pacífico


class AIService:
    def __init__(self, db, clock, settings, config, prompts, provider_factory=None):
        self.db = db
        self.clock = clock
        self.settings = settings
        self.config = config
        self.prompts = prompts
        self.closing = None
        self.provider_factory = provider_factory

    # ---------- modo y disponibilidad ----------
    def mode_info(self) -> tuple[str, str, str]:
        modo = self.settings.get("ia").modo
        if self.config.demo and modo == "gemini":
            modo = "demo"
        if modo == "gemini":
            return modo, f"Gemini ({self.config.gemini_model})", self.config.gemini_model
        if modo == "demo":
            return modo, SimulatedProvider.etiqueta, "simulado"
        return "plantilla", TemplateProvider.etiqueta, "plantilla"

    def provider(self, modo: str):
        if self.provider_factory:
            return self.provider_factory(modo)
        if modo == "gemini":
            return GeminiProvider(self.config.gemini_api_key, self.config.gemini_model)
        if modo == "demo":
            return SimulatedProvider()
        return TemplateProvider()

    def gemini_ready(self) -> tuple[bool, str]:
        icfg = self.settings.get("ia")
        if self.config.demo:
            return False, "En modo demostración no se usa Gemini."
        if not icfg.consentimiento:
            return False, "Falta tu consentimiento para enviar texto a Gemini (Configuración > IA)."
        if icfg.pausada:
            return False, "La IA está pausada en Configuración."
        if not self.config.gemini_api_key:
            return False, "Falta GEMINI_API_KEY en el archivo .env."
        return True, ""

    def blocked_until(self, conn) -> datetime | None:
        until = parse_utc(get_meta(conn, "gemini_bloqueado_hasta_utc"))
        return until if until and until > self.clock.now() else None

    def _tz(self) -> ZoneInfo:
        return ZoneInfo(self.settings.get("recordatorio").zona)

    def today(self) -> date:
        return self.clock.now().astimezone(self._tz()).date()

    def current_period(self, ref: date | None = None) -> Period:
        return period_for(self.settings.get("presentacion"), ref or self.today(), self._tz())

    def calls_today(self, conn) -> int:
        return conn.execute("SELECT count(*) FROM llamadas_ia WHERE fecha_local = ?",
                            (self.today().isoformat(),)).fetchone()[0]

    # ---------- cola ----------
    def enqueue(self, period: Period, motivo: str, cierre_id: str | None = None, force: bool = False) -> dict:
        pcfg = self.settings.get("presentacion")
        modo, _, modelo = self.mode_info()
        if modo == "gemini" and not motivo.startswith("cierre"):
            ok, why = self.gemini_ready()
            if not ok:
                return {"estado": "no_disponible", "mensaje": why}
        now = utc_iso(self.clock.now())
        with self.db.tx() as c:
            sources = collect_sources(c, period, pcfg)
            if not sources["registros"]:
                return {"estado": "sin_contenido",
                        "mensaje": "No hay registros válidos en el período: no hay nada para resumir."}
            hi = input_hash(data_hash(sources, pcfg), modo, modelo)
            if not force and self.prompts.latest(c, period.clave, "auto", hi):
                return {"estado": "sin_cambios", "mensaje": "Sin cambios: el borrador ya está actualizado."}
            existing = c.execute("SELECT id FROM trabajos_ia WHERE periodo_clave = ? AND estado = 'en_cola' "
                                 "ORDER BY id LIMIT 1", (period.clave,)).fetchone()
            if existing:
                c.execute("UPDATE trabajos_ia SET cierre_id = COALESCE(?, cierre_id), motivo = ?, "
                          "proximo_intento_utc = NULL, actualizado_utc = ? WHERE id = ?",
                          (cierre_id, motivo, now, existing["id"]))
                job_id = existing["id"]
            else:
                cur = c.execute("INSERT INTO trabajos_ia(periodo_clave, motivo, estado, cierre_id, creado_utc, "
                                "actualizado_utc) VALUES (?,?,?,?,?,?)",
                                (period.clave, motivo, "en_cola", cierre_id, now, now))
                job_id = cur.lastrowid
        return {"estado": "encolado", "trabajo_id": job_id, "mensaje": "Actualización en cola."}

    def auto_tick(self) -> dict | None:
        """Agrupa cambios: encola recién cuando pasaron `espera_segundos` sin nuevas modificaciones."""
        icfg = self.settings.get("ia")
        modo, _, _ = self.mode_info()
        if modo == "gemini":
            ok, _ = self.gemini_ready()
            if not ok:
                return None
        now = self.clock.now()
        with self.db.read() as c:
            changed = parse_utc(get_meta(c, "datos_cambiados_utc"))
            last = parse_utc(get_meta(c, "auto_encolado_utc"))
            if modo == "gemini" and self.blocked_until(c):
                return None
        if not changed or (last and last >= changed):
            return None
        if (now - changed).total_seconds() < icfg.espera_segundos:
            return None
        res = self.enqueue(self.current_period(), "auto")
        with self.db.tx() as c:
            set_meta(c, "auto_encolado_utc", utc_iso(now))
        return res

    def recover_interrupted(self) -> None:
        with self.db.tx() as c:
            c.execute("UPDATE trabajos_ia SET estado='en_cola', actualizado_utc=? WHERE estado='procesando'",
                      (utc_iso(self.clock.now()),))

    def _claim(self, job_id: int | None) -> dict | None:
        now = utc_iso(self.clock.now())
        with self.db.tx() as c:
            if job_id is None:
                row = c.execute("SELECT * FROM trabajos_ia WHERE estado='en_cola' AND (proximo_intento_utc IS NULL "
                                "OR proximo_intento_utc <= ?) ORDER BY id LIMIT 1", (now,)).fetchone()
            else:
                row = c.execute("SELECT * FROM trabajos_ia WHERE id=? AND estado='en_cola'", (job_id,)).fetchone()
            if not row:
                return None
            c.execute("UPDATE trabajos_ia SET estado='procesando', intentos=intentos+1, actualizado_utc=? WHERE id=?",
                      (now, row["id"]))
        job = dict(row)
        job["intentos"] += 1
        return job

    def process_next(self) -> bool:
        job = self._claim(None)
        if not job:
            return False
        self._safe_run(job)
        return True

    def run_job(self, job_id: int) -> None:
        job = self._claim(job_id)
        if job:
            self._safe_run(job)

    def _safe_run(self, job: dict) -> None:
        try:
            self._run(job)
        except Exception:  # noqa: BLE001
            log.exception("Error interno procesando un trabajo de IA")
            self._fail(job, AIError("interno", "Error interno al preparar el prompt (ver logs)."))

    def _set_job(self, job_id: int, **fields) -> None:
        fields["actualizado_utc"] = utc_iso(self.clock.now())
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self.db.tx() as c:
            c.execute(f"UPDATE trabajos_ia SET {cols} WHERE id = ?", (*fields.values(), job_id))

    def _record_call(self, modelo: str, resultado: str, t_in=None, t_out=None) -> None:
        with self.db.tx() as c:
            c.execute("INSERT INTO llamadas_ia(fecha_local, modelo, resultado, tokens_entrada, tokens_salida, "
                      "creado_utc) VALUES (?,?,?,?,?,?)", (self.today().isoformat(), modelo, resultado, t_in, t_out,
                                                          utc_iso(self.clock.now())))

    def _fail(self, job: dict, err: AIError) -> None:
        icfg = self.settings.get("ia")
        if err.transitorio and job["intentos"] <= icfg.reintentos_transitorios:
            delay = err.retry_after if err.retry_after else BACKOFF[min(job["intentos"] - 1, len(BACKOFF) - 1)]
            delay = max(5.0, min(float(delay), 3600.0))
            nxt = self.clock.now() + timedelta(seconds=delay)
            self._set_job(job["id"], estado="en_cola", proximo_intento_utc=utc_iso(nxt), error_tipo=err.tipo,
                          error_mensaje=f"{err.mensaje} Reintento automático {job['intentos']}/"
                                        f"{icfg.reintentos_transitorios}.")
            return
        self._set_job(job["id"], estado="error", error_tipo=err.tipo, error_mensaje=err.mensaje)
        if err.tipo == "cuota_diaria":
            tomorrow = datetime.combine(self.clock.now().astimezone(GEMINI_RESET_TZ).date() + timedelta(days=1),
                                        time(0, 5), tzinfo=GEMINI_RESET_TZ)
            with self.db.tx() as c:
                set_meta(c, "gemini_bloqueado_hasta_utc", utc_iso(tomorrow))
        if job.get("cierre_id") and self.closing:
            self.closing.mark_pending(job["cierre_id"], err.mensaje)

    def _run(self, job: dict) -> None:
        period = Period.from_clave(job["periodo_clave"])
        pcfg = self.settings.get("presentacion")
        icfg = self.settings.get("ia")
        modo, etiqueta, modelo = self.mode_info()
        with self.db.read() as c:
            sources = collect_sources(c, period, pcfg)
            blocked = self.blocked_until(c) if modo == "gemini" else None
            calls = self.calls_today(c)
        if not sources["registros"]:
            self._set_job(job["id"], estado="sin_contenido", error_mensaje="No hay registros válidos en el período.")
            return
        hd = data_hash(sources, pcfg)
        hi = input_hash(hd, modo, modelo)
        if modo == "gemini":
            ok, why = self.gemini_ready()
            if not ok:
                return self._fail(job, AIError("no_disponible", why))
            if blocked and job["motivo"] in ("auto", "cierre"):
                return self._fail(job, AIError("cuota_diaria", "La cuota diaria de Gemini está agotada; se "
                                                               "reintentará mañana o cuando lo pidas."))
            if calls >= icfg.max_intentos_diarios:
                return self._fail(job, AIError("limite_local", f"Se alcanzó el límite local de "
                                                               f"{icfg.max_intentos_diarios} llamadas diarias a Gemini."))
        provider = self.provider(modo)
        try:
            result = provider.generate(sources, icfg)
        except AIError as err:
            if modo == "gemini":
                self._record_call(modelo, err.tipo)
            return self._fail(job, err)
        if modo == "gemini":
            self._record_call(modelo, "ok", result.tokens_entrada, result.tokens_salida)
        try:
            resumen, warnings = validate_summary(result.data, sources)
        except InvalidAIResponse as exc:
            return self._fail(job, AIError("invalida", str(exc)))
        contenido = build_prompt(resumen, sources, pcfg, etiqueta, self.prompts.local_now_str(), warnings)

        version = None
        with self.db.tx() as c:
            fresh = collect_sources(c, period, pcfg)
            modo_now, _, modelo_now = self.mode_info()
            if data_hash(fresh, pcfg) != hd or (modo_now, modelo_now) != (modo, modelo):
                # Los datos cambiaron mientras la IA respondía: esta respuesta no se publica como vigente.
                now = utc_iso(self.clock.now())
                c.execute("UPDATE trabajos_ia SET estado='obsoleto', hash_entrada=?, error_mensaje=?, actualizado_utc=? "
                          "WHERE id=?", (hi, "Los registros cambiaron durante la generación; se procesa la versión nueva.",
                                         now, job["id"]))
                c.execute("INSERT INTO trabajos_ia(periodo_clave, motivo, estado, cierre_id, creado_utc, actualizado_utc) "
                          "VALUES (?,?,?,?,?,?)", (period.clave, job["motivo"], "en_cola", job.get("cierre_id"), now, now))
                return
            version = self.prompts.create_version(
                c, period, "auto", etiqueta, hi, hd,
                [{"id": r["id"], "revision": r["revision"]} for r in sources["registros"]],
                resumen.model_dump(), warnings, contenido)
            c.execute("UPDATE trabajos_ia SET estado='ok', hash_entrada=?, version_id=?, error_tipo=NULL, "
                      "error_mensaje=NULL, actualizado_utc=? WHERE id=?",
                      (hi, version["id"], utc_iso(self.clock.now()), job["id"]))
            set_meta(c, "ultima_actualizacion_utc", utc_iso(self.clock.now()))
        if job.get("cierre_id") and self.closing:
            self.closing.finalize(job["cierre_id"], version)

    # ---------- estado ----------
    def gemini_status(self) -> dict:
        icfg = self.settings.get("ia")
        with self.db.read() as c:
            last = c.execute("SELECT resultado, creado_utc FROM llamadas_ia ORDER BY id DESC LIMIT 1").fetchone()
            blocked = self.blocked_until(c)
            calls = self.calls_today(c)
        ok, why = self.gemini_ready()
        return {"clave_configurada": bool(self.config.gemini_api_key), "modelo": self.config.gemini_model,
                "consentimiento": icfg.consentimiento, "pausada": icfg.pausada, "lista": ok, "motivo": why,
                "bloqueado_hasta_utc": utc_iso(blocked) if blocked else None,
                "ultima_llamada": dict(last) if last else None, "llamadas_hoy": calls,
                "max_llamadas_diarias": icfg.max_intentos_diarios}

    def status(self, period: Period) -> dict:
        pcfg = self.settings.get("presentacion")
        modo, etiqueta, modelo = self.mode_info()
        with self.db.read() as c:
            sources = collect_sources(c, period, pcfg)
            hd = data_hash(sources, pcfg)
            hi = input_hash(hd, modo, modelo)
            draft = self.prompts.latest(c, period.clave, "auto")
            active = c.execute("SELECT count(*) FROM trabajos_ia WHERE periodo_clave=? AND estado IN "
                               "('en_cola','procesando')", (period.clave,)).fetchone()[0]
            last_job = c.execute("SELECT * FROM trabajos_ia WHERE periodo_clave=? AND estado NOT IN ('obsoleto') "
                                 "ORDER BY id DESC LIMIT 1", (period.clave,)).fetchone()
            last_update = get_meta(c, "ultima_actualizacion_utc")
            jobs = rows(c.execute("SELECT id, motivo, estado, intentos, proximo_intento_utc, error_tipo, error_mensaje, "
                                  "creado_utc, actualizado_utc FROM trabajos_ia WHERE periodo_clave=? ORDER BY id DESC "
                                  "LIMIT 8", (period.clave,)))
        if not sources["registros"]:
            estado, msg = "sin_contenido", "No hay registros válidos en el período."
        elif active:
            estado, msg = "actualizando", "Actualizando el borrador…"
            if last_job and last_job["error_mensaje"] and last_job["estado"] == "en_cola":
                msg = last_job["error_mensaje"]
        elif draft and draft["hash_entrada"] == hi:
            estado, msg = "actualizado", "El borrador refleja los registros vigentes."
        elif last_job and last_job["estado"] == "error":
            estado, msg = "error", last_job["error_mensaje"] or "Error al actualizar."
        else:
            estado, msg = "cambios_pendientes", "Hay cambios que todavía no están en el borrador."
        return {
            "periodo": {"clave": period.clave, "inicio": period.inicio.isoformat(), "fin": period.fin.isoformat(),
                        "etiqueta": period.etiqueta,
                        "cierre_local": period.cierre.isoformat() if period.cierre else None},
            "estado": estado, "mensaje": msg, "modo": modo, "modo_etiqueta": etiqueta,
            "registros": len(sources["registros"]), "excluidos": sources["excluidos"],
            "evidencias": len(sources["evidencias"]),
            "ultima_actualizacion_utc": last_update, "trabajos": jobs, "hash_datos": hd,
        }

    def preview_payload(self, period: Period) -> dict:
        """Lo que se enviaría a Gemini (sin la clave): para revisar antes de consentir."""
        from .providers import SYSTEM_INSTRUCTION, build_user_text
        pcfg = self.settings.get("presentacion")
        icfg = self.settings.get("ia")
        with self.db.read() as c:
            sources = collect_sources(c, period, pcfg)
        try:
            text = build_user_text(sources, icfg.max_caracteres_entrada)
        except AIError as err:
            text = f"[{err.mensaje}]"
        return {"instrucciones": SYSTEM_INSTRUCTION, "texto": text, "registros": len(sources["registros"]),
                "excluidos": sources["excluidos"], "adjuntos_enviados": 0,
                "nota": "Solo se envía este texto. Nunca se envían adjuntos, imágenes, carpetas ni la clave."}


__all__ = ["AIService", "timezone"]
