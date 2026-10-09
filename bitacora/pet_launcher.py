"""Inicia el proceso de Cora, la mascota de escritorio (separado del backend, sin ventana de consola)."""
from __future__ import annotations

import importlib.util
import logging
import os
import subprocess
import sys
from pathlib import Path

from .config import PROJECT_DIR

log = logging.getLogger("bitacora.mascota")


def pyside_available() -> bool:
    return importlib.util.find_spec("PySide6") is not None


def spawn_pet() -> tuple[bool, str]:
    if not pyside_available():
        return False, "Falta PySide6: ejecutá scripts\\iniciar.ps1 para instalar las dependencias."
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    cmd = [str(pyw if pyw.exists() else exe), "-m", "bitacora.mascota"]
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen(cmd, cwd=str(PROJECT_DIR), env=os.environ.copy(), creationflags=flags, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        log.warning("No se pudo iniciar a Cora: %s", type(exc).__name__)
        return False, "No se pudo iniciar a Cora (ver logs)."
    return True, "Iniciando a Cora…"
