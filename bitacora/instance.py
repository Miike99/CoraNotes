"""Instancia única: un archivo bloqueado impide que dos backends ejecuten los mismos trabajos."""
from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path


class AlreadyRunning(Exception):
    pass


class InstanceLock:
    def __init__(self, run_dir: Path, nombre: str = "bitacora"):
        self.run_dir = run_dir
        self.nombre = nombre
        principal = nombre == "bitacora"
        self.lock_path = run_dir / ("instancia.lock" if principal else f"{nombre}.lock")
        self.pid_path = run_dir / f"{nombre}.pid"
        # Tokens locales (solo los escribe el backend): detener la app y autenticar a Cora.
        self.token_path = run_dir / "detener.token" if principal else None
        self.pet_token_path = run_dir / "mascota.token" if principal else None
        self._fh = None
        self.stop_token = ""
        self.pet_token = ""

    def acquire(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        fh = open(self.lock_path, "a+b")
        try:
            if sys.platform == "win32":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            fh.close()
            raise AlreadyRunning("CoraNotes ya está en ejecución") from exc
        self._fh = fh
        self.pid_path.write_text(str(os.getpid()), encoding="ascii")
        if self.token_path is not None:
            self.stop_token = secrets.token_urlsafe(24)
            self.pet_token = secrets.token_urlsafe(24)
            self.token_path.write_text(self.stop_token, encoding="ascii")
            self.pet_token_path.write_text(self.pet_token, encoding="ascii")

    def release(self) -> None:
        for p in (self.pid_path, self.token_path, self.pet_token_path):
            if p is None:
                continue
            try:
                p.unlink()
            except OSError:
                pass
        if self._fh is not None:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            self._fh.close()
            self._fh = None
