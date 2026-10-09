"""Punto de entrada: `python -m bitacora` (servidor) o `python -m bitacora restaurar <zip>`."""
from __future__ import annotations

import logging
import socket
import sys
from logging.handlers import RotatingFileHandler


def setup_logging(paths) -> None:
    from .secrets_guard import RedactingFilter
    paths.logs.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(paths.logs / "coranotes.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    for noisy in ("httpx", "httpcore", "google_genai", "watchdog", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def main(argv: list[str]) -> int:
    from .config import HOST, load_config
    config = load_config()
    config.paths.ensure()
    setup_logging(config.paths)
    log = logging.getLogger("bitacora")

    if argv and argv[0] == "restaurar":
        from .backup import restore_backup
        from .instance import AlreadyRunning, InstanceLock
        if len(argv) < 2:
            print("Uso: python -m bitacora restaurar <archivo.zip>")
            return 2
        lock = InstanceLock(config.paths.run)
        try:
            lock.acquire()
        except AlreadyRunning:
            print("Detené CoraNotes antes de restaurar (scripts\\detener.ps1).")
            return 3
        try:
            resguardo = restore_backup(config.paths, argv[1])
        finally:
            lock.release()
        print(f"Copia restaurada. Los datos anteriores quedaron en: {resguardo}")
        return 0

    import uvicorn

    from .context import AppContext
    from .instance import AlreadyRunning, InstanceLock
    from .web.app import create_app

    lock = InstanceLock(config.paths.run)
    try:
        lock.acquire()
    except AlreadyRunning:
        print(f"CoraNotes ya está en ejecución: abrí {config.base_url}")
        return 3
    if port_in_use(config.port):
        print(f"El puerto {config.port} está ocupado por otro programa. Cambiá CORANOTES_PORT en .env.")
        lock.release()
        return 4
    try:
        ctx = AppContext(config)
        server_holder: dict = {}

        def stop():
            srv = server_holder.get("server")
            if srv:
                srv.should_exit = True

        app = create_app(ctx, stop_callback=stop, stop_token_getter=lambda: lock.stop_token,
                         pet_token_getter=lambda: lock.pet_token)
        uv_config = uvicorn.Config(app, host=HOST, port=config.port, reload=False, workers=1,
                                   log_config=None, access_log=False, server_header=False, proxy_headers=False)
        server = uvicorn.Server(uv_config)
        server_holder["server"] = server
        ctx.start_background()
        log.info("CoraNotes iniciada en %s (demo=%s)", config.base_url, config.demo)
        if sys.stdout:
            print(f"CoraNotes en {config.base_url} — datos en {config.paths.home}")
        server.run()
        ctx.stop_background()
        log.info("CoraNotes detenida")
    finally:
        lock.release()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
