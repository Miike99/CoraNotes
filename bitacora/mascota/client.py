"""Comunicación con el backend local (127.0.0.1) en un hilo aparte: la interfaz nunca se bloquea.

Se autentica con el token local `run\\mascota.token` que escribe el backend. No conoce ni pide
la clave de Gemini.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import urllib.error
import urllib.request
from pathlib import Path

from PySide6.QtCore import QObject, Signal

log = logging.getLogger("bitacora.mascota")
SYNC_SECONDS = 3.0
SYNC_SECONDS_OFFLINE = 5.0


class Backend(QObject):
    estado = Signal(dict)
    desconectado = Signal(str)
    resultado = Signal(str, bool, str)   # accion, ok, mensaje
    salir = Signal()

    def __init__(self, base_url: str, run_dir: Path):
        super().__init__()
        self.base = base_url.rstrip("/")
        self.run_dir = run_dir
        self.visible = True
        self._q: queue.Queue = queue.Queue()
        self._acks: list[str] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="mascota-backend", daemon=True)
        self.online = False

    # ---------- API pública (hilo de la interfaz) ----------
    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._q.put(("nada",))

    def sync_now(self) -> None:
        self._q.put(("sync",))

    def ack(self, fecha: str) -> None:
        self._q.put(("ack", fecha))

    def command(self, accion: str, body: dict | None = None) -> None:
        self._q.put(("cmd", accion, body or {}))

    def final_sync_hidden(self) -> None:
        """Al cerrar a Cora: avisa enseguida que ya no está visible (activa la notificación de respaldo)."""
        try:
            self._request("POST", "/api/mascota/sincronizar", {"visible": False}, timeout=1.5)
        except Exception:  # noqa: BLE001
            pass

    # ---------- internos ----------
    def _token(self, name: str) -> str:
        try:
            return (self.run_dir / name).read_text(encoding="ascii").strip()
        except OSError:
            return ""

    def _request(self, method: str, path: str, body: dict | None = None, timeout: float = 4.0,
                 stop_token: bool = False) -> dict:
        data = json.dumps(body or {}).encode("utf-8") if method == "POST" else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if stop_token:
            req.add_header("X-Bitacora-Detener", self._token("detener.token"))
        else:
            req.add_header("X-Bitacora-Mascota", self._token("mascota.token"))
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - siempre 127.0.0.1
            return json.loads(resp.read().decode("utf-8") or "{}")

    def _detail(self, exc: Exception) -> str:
        if isinstance(exc, urllib.error.HTTPError):
            try:
                return json.loads(exc.read().decode("utf-8")).get("detalle", f"Error {exc.code}")
            except Exception:  # noqa: BLE001
                return f"Error {exc.code}"
        return "Sin conexión con CoraNotes"

    def _handle(self, item: tuple) -> None:
        kind = item[0]
        if kind == "ack":
            if item[1] not in self._acks:
                self._acks.append(item[1])
        elif kind == "cmd":
            accion, body = item[1], item[2]
            rutas = {"posponer": "/api/mascota/posponer", "silenciar": "/api/mascota/silenciar",
                     "config": "/api/mascota/config"}
            try:
                if accion == "detener":
                    self._request("POST", "/api/sistema/detener", {}, stop_token=True)
                    self.resultado.emit(accion, True, "CoraNotes se está deteniendo.")
                    return
                self._request("POST", rutas[accion], body)
                self.resultado.emit(accion, True, "")
            except Exception as exc:  # noqa: BLE001
                self.resultado.emit(accion, False, self._detail(exc))

    def _sync(self) -> None:
        for fecha in list(self._acks):
            try:
                self._request("POST", "/api/mascota/recompensa", {"fecha": fecha})
                self._acks.remove(fecha)
            except Exception:  # noqa: BLE001
                break  # se reintenta en el próximo ciclo
        st = self._request("POST", "/api/mascota/sincronizar", {"visible": self.visible})
        self.online = True
        self.estado.emit(st)

    def _loop(self) -> None:
        while not self._stop.is_set():
            if (self.run_dir / "mascota.salir").exists():
                try:
                    (self.run_dir / "mascota.salir").unlink()
                except OSError:
                    pass
                self.salir.emit()
                return
            try:
                self._sync()
            except Exception as exc:  # noqa: BLE001
                if self.online:
                    log.info("Se perdió la conexión con el backend")
                self.online = False
                self.desconectado.emit(self._detail(exc))
            espera = SYNC_SECONDS if self.online else SYNC_SECONDS_OFFLINE
            try:
                item = self._q.get(timeout=espera)
                self._handle(item)
                while True:  # vacía comandos acumulados sin esperar
                    self._handle(self._q.get_nowait())
            except queue.Empty:
                pass
