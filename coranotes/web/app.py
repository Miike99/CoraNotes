"""API local (FastAPI) y archivos estáticos de la interfaz."""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import Body, FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .. import __version__
from ..backup import create_backup, list_backups
from ..calendar_logic import Period, close_warning, next_runs
from ..db import get_meta
from ..evidence import IMAGE_MIMES
from ..importer import validate_inbox_folder
from ..records import AppError, mark_data_changed, parse_registro
from ..secrets_guard import redact
from ..settings import SettingsError
from ..util import safe_filename, utc_iso
from .security import COOKIE, SecurityMiddleware, SessionStore

log = logging.getLogger("coranotes.web")
STATIC = Path(__file__).parent / "static"


class FechaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fecha: date
    nota: str = Field("", max_length=500)


class ClasificarIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fecha: date
    proyecto: str = Field(min_length=1, max_length=120)
    tarea_titulo: str = Field("", max_length=200)


class ManualIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    periodo: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}$")
    contenido: str = Field(max_length=200_000)
    base_version_id: str | None = Field(None, pattern=r"^VER-[0-9A-F]{8}$")


class PeriodoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: date | None = None
    forzar: bool = False


class PresentacionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version_usada_id: str | None = Field(None, pattern=r"^VER-[0-9A-F]{8}$")
    referencia: str = Field("", max_length=500)
    evidencia_id: str | None = Field(None, pattern=r"^EVI-[0-9A-F]{8}$")


class ConsentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    acepto: bool


class IncluirIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    incluir: bool


class SincronizarIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    visible: bool = True


class RecompensaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fecha: date


class SilencioIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    activar: bool


class VincularIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    registro_id: str | None = Field(None, pattern=r"^REG-[0-9A-F]{8}$")


def create_app(ctx, allowed_hosts: set[str] | None = None, stop_callback=None, stop_token_getter=None,
               pet_token_getter=None) -> FastAPI:
    app = FastAPI(title="CoraNotes", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    port = ctx.config.port
    hosts = allowed_hosts or {f"127.0.0.1:{port}", f"localhost:{port}"}
    sessions = SessionStore()
    app.add_middleware(SecurityMiddleware, allowed_hosts=hosts, sessions=sessions,
                       stop_token_getter=stop_token_getter or (lambda: None),
                       pet_token_getter=pet_token_getter or (lambda: None))

    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        return JSONResponse({"detalle": redact(exc.message)}, status_code=exc.status)

    @app.exception_handler(SettingsError)
    async def _settings_error(request: Request, exc: SettingsError):
        return JSONResponse({"detalle": str(exc)}, status_code=422)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        parts = []
        for e in exc.errors()[:5]:
            loc = ".".join(str(x) for x in e.get("loc", ()) if x not in ("body", "query", "path"))
            parts.append(f"{loc}: {str(e.get('msg', '')).replace('Value error, ', '')}")
        return JSONResponse({"detalle": "Datos inválidos — " + "; ".join(parts)}, status_code=422)

    def tz() -> ZoneInfo:
        return ZoneInfo(ctx.settings.get("recordatorio").zona)

    def today() -> date:
        return ctx.clock.now().astimezone(tz()).date()

    def _demo_loaded() -> bool:
        with ctx.db.read() as c:
            return bool(get_meta(c, "demo_cargada_utc"))

    def period_from(ref: date | None) -> Period:
        return ctx.ai.current_period(ref)

    # ---------- interfaz ----------
    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html", media_type="text/html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/api/sesion")
    def sesion(request: Request):
        sid, token = sessions.get_or_create(request.cookies.get(COOKIE))
        resp = JSONResponse({"csrf": token, "demo": ctx.config.demo, "version": __version__,
                             "zona": ctx.settings.get("recordatorio").zona})
        # Sin "Secure": el servidor local usa http://127.0.0.1. HttpOnly + SameSite=Strict.
        resp.set_cookie(COOKIE, sid, httponly=True, samesite="strict", path="/")
        return resp

    # ---------- estado general ----------
    @app.get("/api/estado")
    def estado():
        now = ctx.clock.now()
        rcfg = ctx.settings.get("recordatorio")
        pcfg = ctx.settings.get("presentacion")
        hoy = today()
        period = period_from(None)
        return {
            "ahora_local": now.astimezone(tz()).isoformat(),
            "hoy": ctx.records.day_status(hoy),
            "demo": ctx.config.demo,
            "demo_cargada": _demo_loaded(),
            "proceso": {"iniciado_utc": ctx.started_utc, "hilos": ctx.thread_status,
                        "ultimo_ciclo": ctx.scheduler.last_tick_result,
                        "carpeta": {"estado": ctx.watcher.estado, "detalle": ctx.watcher.detalle}},
            "recordatorios": {"pausado": rcfg.pausado, "pausa_hasta": rcfg.pausa_hasta, "dias": rcfg.dias,
                              "hora": rcfg.hora, "zona": rcfg.zona, "activos": ctx.scheduler.active_reminders()},
            "proximas": next_runs(rcfg, pcfg, now),
            "advertencia_cierre": close_warning(rcfg, pcfg, hoy),
            "gemini": ctx.ai.gemini_status(),
            "prompt": ctx.ai.status(period),
            "avisos_no_leidos": len(ctx.notices.list(solo_no_leidos=True)),
            "mascota": {**ctx.pet.presence(), "habilitada": ctx.settings.get("mascota").habilitada,
                        "canal_recordatorio": ctx.scheduler.reminder_channel()},
        }

    # ---------- registros ----------
    @app.get("/api/registros")
    def registros(desde: date | None = None, hasta: date | None = None, proyecto: str | None = None,
                  archivados: Literal["no", "si", "solo"] = "no"):
        return ctx.records.list(desde.isoformat() if desde else None, hasta.isoformat() if hasta else None,
                                proyecto, archivados)

    @app.post("/api/registros")
    def crear_registro(data: dict = Body(...)):
        rec, efectos = ctx.records.create(parse_registro(data))
        return {"registro": rec, "efectos": efectos}

    @app.get("/api/registros/{rec_id}")
    def ver_registro(rec_id: str):
        return ctx.records.get(rec_id)

    @app.put("/api/registros/{rec_id}")
    def editar_registro(rec_id: str, data: dict = Body(...)):
        rec, efectos = ctx.records.update(rec_id, parse_registro(data))
        return {"registro": rec, "efectos": efectos}

    @app.post("/api/registros/{rec_id}/archivar")
    def archivar(rec_id: str):
        return ctx.records.archive(rec_id)

    @app.post("/api/registros/{rec_id}/restaurar")
    def restaurar(rec_id: str):
        rec, efectos = ctx.records.restore(rec_id)
        return {"registro": rec, "efectos": efectos}

    @app.post("/api/registros/{rec_id}/eliminar-definitivo")
    def purgar(rec_id: str):
        ctx.records.purge(rec_id)
        return {"ok": True, "nota": "Eliminado de esta computadora. No borra datos ya enviados a un proveedor externo."}

    @app.post("/api/registros/{rec_id}/incluir-ia")
    def incluir_ia(rec_id: str, data: IncluirIn):
        return ctx.records.set_include(rec_id, data.incluir)

    @app.get("/api/registros/{rec_id}/revisiones")
    def revisiones(rec_id: str):
        return ctx.records.revisions(rec_id)

    @app.get("/api/registros/{rec_id}/markdown")
    def markdown(rec_id: str):
        rec = ctx.records.get(rec_id)
        return Response(ctx.records.markdown_text(rec), media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{rec["fecha"]}_{rec["id"]}.md"'})

    @app.get("/api/proyectos")
    def proyectos():
        return {"proyectos": ctx.records.projects(), "tareas": ctx.records.tasks()}

    # ---------- días ----------
    @app.get("/api/dias")
    def dias(desde: date, hasta: date):
        if (hasta - desde).days > 120:
            raise AppError("Rango demasiado amplio")
        return ctx.records.days_status(desde, hasta)

    @app.post("/api/dias/sin-actividad")
    def sin_actividad(data: FechaIn):
        return {"efectos": ctx.records.declare_no_activity(data.fecha, data.nota),
                "dia": ctx.records.day_status(data.fecha)}

    @app.post("/api/dias/quitar-sin-actividad")
    def quitar_sin_actividad(data: FechaIn):
        ctx.records.remove_declaration(data.fecha)
        return {"dia": ctx.records.day_status(data.fecha)}

    # ---------- recordatorios y avisos ----------
    @app.post("/api/recordatorios/posponer")
    def posponer(clave: str = Body(..., embed=True, max_length=120)):
        return ctx.scheduler.snooze(clave)

    @app.post("/api/recordatorios/descartar")
    def descartar(clave: str = Body(..., embed=True, max_length=120)):
        return ctx.scheduler.dismiss(clave)

    @app.get("/api/avisos")
    def avisos():
        return ctx.notices.list()

    @app.post("/api/avisos/leidos")
    def avisos_leidos(aviso_id: int | None = Body(None, embed=True)):
        ctx.notices.mark_read(aviso_id)
        return {"ok": True}

    @app.post("/api/notificaciones/probar")
    def probar_notificacion():
        aviso = ctx.notices.add("prueba", "CoraNotes: prueba",
                                "Esta es una notificación de prueba. Si la ves, las notificaciones funcionan.",
                                "#/inicio")
        return {"entrega": aviso.get("entrega"), "detalle": aviso.get("entrega_detalle")}

    # ---------- evidencias ----------
    @app.get("/api/evidencias")
    def evidencias(registro_id: str | None = None, sin_registro: bool = False):
        return ctx.evidence.list(registro_id, sin_registro)

    @app.post("/api/evidencias")
    async def subir_evidencia(archivo: UploadFile = File(...), registro_id: str | None = Form(None)):
        limit = ctx.settings.get("limites").documento_bytes
        data = await archivo.read(limit + 1)
        if len(data) > limit:
            raise AppError("El archivo supera el límite configurado")
        return ctx.evidence.add(archivo.filename or "archivo", data, registro_id or None)

    @app.post("/api/evidencias/{eid}/vincular")
    def vincular(eid: str, data: VincularIn):
        return ctx.evidence.link(eid, data.registro_id)

    @app.get("/api/evidencias/{eid}/archivo")
    def archivo_evidencia(eid: str, descargar: bool = False):
        path, ev = ctx.evidence.file_path(eid)
        inline = ev["mime"] in IMAGE_MIMES and not descargar
        name = safe_filename(ev["nombre"])
        return FileResponse(path, media_type=ev["mime"], headers={
            "Content-Disposition": f'{"inline" if inline else "attachment"}; filename="{name}"',
            "Content-Security-Policy": "default-src 'none'; img-src 'self'; sandbox"})

    # ---------- documentos ----------
    @app.get("/api/documentos")
    def documentos(estado: str | None = None):
        return ctx.importer.list(estado)

    @app.post("/api/documentos/{doc_id}/clasificar")
    def clasificar(doc_id: str, data: ClasificarIn):
        return ctx.importer.classify(doc_id, data.fecha, data.proyecto, data.tarea_titulo)

    @app.post("/api/documentos/{doc_id}/ignorar")
    def ignorar(doc_id: str):
        ctx.importer.ignore(doc_id)
        return {"ok": True}

    @app.post("/api/documentos/{doc_id}/archivar-registro")
    def archivar_registro_doc(doc_id: str):
        return ctx.importer.archive_linked_record(doc_id)

    @app.post("/api/documentos/reescanear")
    def reescanear():
        return ctx.importer.scan()

    # ---------- configuración ----------
    @app.get("/api/config")
    def get_config():
        data = {k: v.model_dump(mode="json") for k, v in ctx.settings.all().items()}
        data["_info"] = {"modelo": ctx.config.gemini_model, "clave_configurada": bool(ctx.config.gemini_api_key),
                         "demo": ctx.config.demo, "carpeta_datos": str(ctx.config.paths.home),
                         "carpeta_sugerida": str(Path.home() / "Documents" / "CoraNotes - Entrada"),
                         "advertencia_cierre": close_warning(ctx.settings.get("recordatorio"),
                                                             ctx.settings.get("presentacion"), today())}
        return data

    @app.put("/api/config/{seccion}")
    def put_config(seccion: str, data: dict = Body(...)):
        if seccion == "ia":
            current = ctx.settings.get("ia")
            data["consentimiento"] = current.consentimiento  # solo cambia por /api/ia/consentimiento
            data["consentimiento_utc"] = current.consentimiento_utc
            if data.get("modo") == "gemini":
                if ctx.config.demo:
                    raise AppError("En modo demostración no se usa Gemini.")
                if not current.consentimiento:
                    raise AppError("Primero tenés que aceptar el envío de texto a Gemini.")
        if seccion == "entrada" and data.get("carpeta"):
            data["carpeta"] = str(validate_inbox_folder(data["carpeta"], ctx.importer.forbidden))
        if seccion == "mascota":  # cambios parciales: no pisar la posición que guarda Cora al arrastrarla
            value = ctx.settings.update("mascota", data)
        else:
            value = ctx.settings.set(seccion, data)
        if seccion in ("presentacion", "ia"):
            with ctx.db.tx() as c:
                mark_data_changed(c, ctx.clock)
        resp = value.model_dump(mode="json")
        if seccion in ("recordatorio", "presentacion"):
            resp["_advertencia_cierre"] = close_warning(ctx.settings.get("recordatorio"),
                                                        ctx.settings.get("presentacion"), today())
        return resp

    @app.post("/api/config/carpeta-sugerida")
    def carpeta_sugerida():
        target = Path.home() / "Documents" / "CoraNotes - Entrada"
        target.mkdir(parents=True, exist_ok=True)
        real = validate_inbox_folder(str(target), ctx.importer.forbidden)
        ctx.settings.update("entrada", {"carpeta": str(real), "activa": True})
        return {"carpeta": str(real)}

    @app.post("/api/ia/consentimiento")
    def consentimiento(data: ConsentIn):
        if data.acepto:
            if ctx.config.demo:
                raise AppError("En modo demostración no se usa Gemini.")
            ctx.settings.update("ia", {"consentimiento": True, "consentimiento_utc": utc_iso(ctx.clock.now())})
        else:
            ctx.settings.update("ia", {"consentimiento": False, "consentimiento_utc": None, "modo": "plantilla"})
        return ctx.settings.get("ia").model_dump(mode="json")

    @app.get("/api/ia/vista-previa")
    def vista_previa(ref: date | None = None):
        return ctx.ai.preview_payload(period_from(ref))

    # ---------- prompt y versiones ----------
    @app.get("/api/prompt")
    def prompt(ref: date | None = None):
        period = period_from(ref)
        status = ctx.ai.status(period)
        with ctx.db.read() as c:
            draft = ctx.prompts.latest(c, period.clave, "auto")
            manual = ctx.prompts.latest(c, period.clave, "manual")
        return {"estado": status, "borrador": draft, "mi_version": manual,
                "mi_version_desactualizada": bool(manual and draft and manual["hash_datos"] != draft["hash_datos"]),
                "cierres": ctx.closing.list(period.clave)}

    @app.post("/api/prompt/actualizar")
    def actualizar(data: PeriodoIn):
        period = period_from(data.ref)
        res = ctx.ai.enqueue(period, "manual", force=data.forzar)
        if res.get("trabajo_id") and ctx.ai.mode_info()[0] != "gemini":
            ctx.ai.run_job(res["trabajo_id"])
            res["estado"] = "actualizado"
            res["mensaje"] = "Borrador actualizado."
        return res

    @app.get("/api/prompt/versiones")
    def versiones(periodo: str | None = None):
        return ctx.prompts.list_versions(periodo)

    @app.get("/api/prompt/versiones/{vid}")
    def version(vid: str):
        return ctx.prompts.get(vid)

    @app.get("/api/prompt/diferencias")
    def diferencias(a: str, b: str):
        return {"diff": ctx.prompts.diff(a, b)}

    @app.post("/api/prompt/manual")
    def guardar_manual(data: ManualIn):
        return ctx.prompts.save_manual(data.periodo, data.contenido, data.base_version_id)

    @app.post("/api/prompt/versiones/{vid}/recuperar")
    def recuperar(vid: str):
        return ctx.prompts.recover(vid)

    @app.get("/api/prompt/versiones/{vid}/descargar")
    def descargar(vid: str, formato: Literal["md", "txt"] = "md"):
        v = ctx.prompts.get(vid)
        name = f"coranotes-prompt-{v['periodo_clave']}-{v['id']}.{formato}"
        media = "text/markdown" if formato == "md" else "text/plain"
        return Response(redact(v["contenido"]), media_type=f"{media}; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.post("/api/preparar")
    def preparar(data: PeriodoIn):
        return ctx.closing.prepare(period_from(data.ref), disparo="manual")

    @app.get("/api/cierres")
    def cierres():
        return ctx.closing.list()

    @app.post("/api/cierres/{cid}/reintentar")
    def reintentar(cid: str):
        return ctx.closing.retry(cid)

    @app.post("/api/cierres/{cid}/respaldo")
    def respaldo(cid: str):
        return ctx.closing.fallback(cid)

    @app.post("/api/cierres/{cid}/presentacion")
    def registrar_presentacion(cid: str, data: PresentacionIn):
        return ctx.closing.register_presentation(cid, data.version_usada_id, data.referencia, data.evidencia_id)

    # ---------- Cora (mascota de escritorio) ----------
    # Las escrituras del proceso de Cora usan el token local de run\mascota.token;
    # las de la interfaz web usan el token CSRF de sesión. Nunca se expone la clave de Gemini.
    @app.get("/api/mascota/estado")
    def mascota_estado():
        return ctx.pet.state()

    @app.post("/api/mascota/sincronizar")
    def mascota_sincronizar(data: SincronizarIn):
        ctx.pet.heartbeat(data.visible)
        return ctx.pet.state()

    @app.post("/api/mascota/recompensa")
    def mascota_recompensa(data: RecompensaIn):
        return {"registrada": ctx.pet.ack_reward(data.fecha.isoformat())}

    @app.post("/api/mascota/posponer")
    def mascota_posponer():
        return ctx.pet.snooze()

    @app.post("/api/mascota/silenciar")
    def mascota_silenciar(data: SilencioIn):
        ctx.pet.set_silence(data.activar)
        return ctx.pet.state()

    @app.post("/api/mascota/config")
    def mascota_config(data: dict = Body(...)):
        return ctx.pet.update_config(data)

    @app.post("/api/mascota/mostrar")
    def mascota_mostrar():
        ctx.pet.request_show()
        return {"ok": True}

    @app.post("/api/mascota/abrir")
    def mascota_abrir():
        from ..pet_launcher import spawn_pet
        if not ctx.settings.get("mascota").habilitada:
            ctx.settings.update("mascota", {"habilitada": True})
        if ctx.pet.presence()["conectada"]:
            ctx.pet.request_show()
            return {"ok": True, "mensaje": "Cora ya está abierta: se va a mostrar."}
        ok, msg = spawn_pet()
        if not ok:
            raise AppError(msg)
        return {"ok": True, "mensaje": msg}

    # ---------- copias, demo y sistema ----------
    @app.get("/api/copias")
    def copias():
        return list_backups(ctx.config.paths)

    @app.post("/api/copias")
    def crear_copia():
        path = create_backup(ctx.config.paths, ctx.clock.now().astimezone(tz()))
        return {"archivo": str(path), "nota": "La copia no está cifrada y no incluye la clave de Gemini."}

    @app.post("/api/demo/cargar")
    def cargar_demo():
        if not ctx.config.demo:
            raise AppError("Los datos ficticios solo se cargan en modo demostración (demo.ps1).")
        from ..demo import load_demo
        return load_demo(ctx)

    @app.post("/api/sistema/detener")
    def detener():
        if stop_callback:
            stop_callback()
        return {"ok": True}

    return app
