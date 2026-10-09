"""Supervisión de la carpeta de entrada (watchdog + reescaneo periódico de respaldo)."""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

log = logging.getLogger("bitacora.carpeta")

STABLE_SECONDS = 2.0      # el archivo no cambió de tamaño/fecha durante este tiempo
GIVE_UP_SECONDS = 180.0   # si sigue bloqueado (en uso) se informa como error
RESCAN_SECONDS = 120.0


class InboxWatcher:
    def __init__(self, importer):
        self.importer = importer
        self.pending: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.observer = None
        self.watching: Path | None = None
        self.estado = "inactiva"
        self.detalle = ""
        self._last_rescan = 0.0

    def notify_path(self, path: str) -> None:
        with self.lock:
            entry = self.pending.get(path)
            if entry is None:
                self.pending[path] = {"first": time.monotonic(), "sig": None, "since": time.monotonic()}

    def _start_observer(self, inbox: Path) -> None:
        self._stop_observer()
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            self.estado, self.detalle = "sondeo", "watchdog no disponible: se usa reescaneo periódico"
            self.watching = inbox
            return
        watcher = self

        class Handler(FileSystemEventHandler):
            def on_created(self, event):
                if not event.is_directory:
                    watcher.notify_path(event.src_path)

            def on_modified(self, event):
                if not event.is_directory:
                    watcher.notify_path(event.src_path)

            def on_moved(self, event):
                if not event.is_directory:
                    watcher.notify_path(event.dest_path)

            def on_deleted(self, event):
                watcher._last_rescan = 0.0  # fuerza un reescaneo para detectar quitados

        try:
            obs = Observer()
            obs.schedule(Handler(), str(inbox), recursive=True)
            obs.daemon = True
            obs.start()
            self.observer = obs
            self.estado, self.detalle = "activa", str(inbox)
        except OSError as exc:
            log.warning("No se pudo iniciar la supervisión: %s", type(exc).__name__)
            self.estado, self.detalle = "sondeo", "Supervisión en vivo no disponible: se usa reescaneo periódico"
        self.watching = inbox
        self._last_rescan = 0.0

    def _stop_observer(self) -> None:
        if self.observer is not None:
            try:
                self.observer.stop()
                self.observer.join(timeout=5)
            except Exception:  # noqa: BLE001
                pass
        self.observer = None

    def step(self) -> None:
        """Un ciclo: sincroniza la carpeta configurada, procesa archivos estables y reescanea."""
        inbox = self.importer.inbox()
        if inbox != self.watching:
            if inbox is None:
                self._stop_observer()
                self.watching = None
                self.estado, self.detalle = "inactiva", ""
            else:
                self._start_observer(inbox)
        if inbox is None:
            return
        now = time.monotonic()
        with self.lock:
            items = list(self.pending.items())
        for path, entry in items:
            try:
                st = os.stat(path)
            except FileNotFoundError:
                with self.lock:
                    self.pending.pop(path, None)
                continue
            except OSError:
                continue
            sig = (st.st_size, st.st_mtime_ns)
            if sig != entry["sig"]:
                entry["sig"], entry["since"] = sig, now
                continue
            if now - entry["since"] < STABLE_SECONDS:
                continue
            try:
                with open(path, "rb") as fh:
                    fh.read(1)
            except PermissionError:
                if now - entry["first"] > GIVE_UP_SECONDS:
                    with self.lock:
                        self.pending.pop(path, None)
                    try:
                        rel = Path(path).relative_to(inbox).as_posix()
                        self.importer.record_error(rel, "El archivo sigue en uso por otro programa")
                    except ValueError:
                        pass
                continue
            except OSError:
                continue
            with self.lock:
                self.pending.pop(path, None)
            try:
                self.importer.process_file(Path(path))
            except Exception:  # noqa: BLE001
                log.exception("Error procesando un archivo de entrada")
        if now - self._last_rescan > RESCAN_SECONDS:
            self._last_rescan = now
            try:
                self.importer.scan(process=lambda p: self.notify_path(str(p)))
            except Exception:  # noqa: BLE001
                log.exception("Error en el reescaneo de la carpeta de entrada")

    def stop(self) -> None:
        self._stop_observer()
