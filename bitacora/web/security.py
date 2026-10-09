"""Protecciones del servidor local: Host/Origin, CSRF por sesión y cabeceras seguras.

Escuchar en 127.0.0.1 reduce la exposición, pero no es una garantía absoluta: cualquier
programa de esta computadora o una página web maliciosa podría intentar hablar con el
servidor. Por eso se validan Host y Origin y toda escritura exige un token CSRF.
"""
from __future__ import annotations

import hmac
import secrets
import threading
from collections import OrderedDict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
COOKIE = "bitacora_sesion"
CSRF_HEADER = "x-csrf-token"
STOP_PATH = "/api/sistema/detener"
STOP_HEADER = "x-bitacora-detener"
PET_HEADER = "x-bitacora-mascota"
PET_PREFIX = "/api/mascota/"

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
       "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


class SessionStore:
    def __init__(self, max_sessions: int = 64):
        self._s: OrderedDict[str, str] = OrderedDict()
        self._lock = threading.Lock()
        self.max = max_sessions

    def get_or_create(self, sid: str | None) -> tuple[str, str]:
        with self._lock:
            if sid and sid in self._s:
                self._s.move_to_end(sid)
                return sid, self._s[sid]
            sid = secrets.token_urlsafe(24)
            token = secrets.token_urlsafe(24)
            self._s[sid] = token
            while len(self._s) > self.max:
                self._s.popitem(last=False)
            return sid, token

    def check(self, sid: str | None, token: str | None) -> bool:
        if not sid or not token:
            return False
        with self._lock:
            expected = self._s.get(sid)
        return expected is not None and hmac.compare_digest(expected, token)


class SecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, allowed_hosts: set[str], sessions: SessionStore, stop_token_getter,
                 pet_token_getter=None):
        super().__init__(app)
        self.pet_token_getter = pet_token_getter or (lambda: None)
        self.allowed_hosts = allowed_hosts
        self.allowed_origins = {f"http://{h}" for h in allowed_hosts}
        self.sessions = sessions
        self.stop_token_getter = stop_token_getter

    def _pet_ok(self, request) -> bool:
        expected = self.pet_token_getter() or ""
        got = request.headers.get(PET_HEADER, "")
        return bool(expected) and bool(got) and hmac.compare_digest(expected, got)

    async def dispatch(self, request, call_next):
        host = request.headers.get("host", "")
        if host not in self.allowed_hosts:
            return JSONResponse({"detalle": "Host no permitido"}, status_code=400)
        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin is not None and origin not in self.allowed_origins:
                return JSONResponse({"detalle": "Origen no permitido"}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detalle": "Solicitud entre sitios rechazada"}, status_code=403)
            if request.url.path == STOP_PATH:
                expected = self.stop_token_getter() or ""
                got = request.headers.get(STOP_HEADER, "")
                if not expected or not hmac.compare_digest(expected, got):
                    return JSONResponse({"detalle": "Token de detención inválido"}, status_code=403)
            elif request.url.path.startswith(PET_PREFIX) and self._pet_ok(request):
                pass  # proceso de Cora: token local leído de la carpeta run (no es un navegador)
            elif not self.sessions.check(request.cookies.get(COOKIE), request.headers.get(CSRF_HEADER)):
                return JSONResponse({"detalle": "Sesión vencida o token CSRF inválido. Recargá la página.",
                                     "codigo": "csrf"}, status_code=403)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        elif request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"  # siempre revalida tras actualizar la app
        return response
