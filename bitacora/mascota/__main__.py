"""Arranque de Cora: `python -m bitacora.mascota` (lo inicia scripts\\iniciar.ps1)."""
from __future__ import annotations

import json
import logging
import sys
import urllib.request
from logging.handlers import RotatingFileHandler


def _ask_existing_to_show(config) -> None:
    """Cora ya está abierta: se le pide al backend que la muestre (no se abre un segundo proceso)."""
    try:
        token = (config.paths.run / "mascota.token").read_text(encoding="ascii").strip()
        req = urllib.request.Request(f"{config.base_url}/api/mascota/mostrar", data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json", "X-Bitacora-Mascota": token})
        urllib.request.urlopen(req, timeout=3).read()  # noqa: S310 - 127.0.0.1
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    from ..config import load_config
    from ..instance import AlreadyRunning, InstanceLock
    from ..secrets_guard import RedactingFilter

    config = load_config()
    config.paths.ensure()
    handler = RotatingFileHandler(config.paths.logs / "cora.log", maxBytes=500_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())
    logging.getLogger().handlers[:] = [handler]
    logging.getLogger().setLevel(logging.INFO)
    log = logging.getLogger("bitacora.mascota")

    lock = InstanceLock(config.paths.run, nombre="mascota")
    try:
        lock.acquire()
    except AlreadyRunning:
        _ask_existing_to_show(config)
        return 0
    try:
        (config.paths.run / "mascota.salir").unlink(missing_ok=True)
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            msg = "Falta PySide6. Ejecutá scripts\\iniciar.ps1 para instalar las dependencias."
            log.error(msg)
            if sys.stdout:
                print(msg)
            return 2
        from .app import PetController
        app = QApplication(sys.argv[:1])
        app.setApplicationName("Cora · CoraNotes")
        app.setQuitOnLastWindowClosed(False)  # ocultar la ventana no cierra el proceso (queda la bandeja)
        ctrl = PetController(app, config)
        ctrl.start()
        log.info("Cora iniciada (backend %s)", config.base_url)
        code = app.exec()
        log.info("Cora cerrada")
        return code
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
