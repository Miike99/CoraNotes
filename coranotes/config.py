"""Configuración de arranque de CoraNotes: rutas de datos, puerto, modelo y clave (solo backend)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PORT = 8765
DEFAULT_MODEL = "gemini-3.8-flash"
HOST = "127.0.0.1"  # nunca se escucha en otra interfaz
APP_NAME = "CoraNotes"
PET_NAME = "Cora"
DB_NAME = "coranotes.sqlite3"


def load_dotenv(path: Path) -> None:
    """Lee KEY=VALOR de un .env sin pisar variables ya definidas en el entorno."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass
class Paths:
    home: Path

    @property
    def db_dir(self) -> Path:
        return self.home / "datos"

    @property
    def db(self) -> Path:
        return self.db_dir / DB_NAME

    @property
    def logs(self) -> Path:
        return self.home / "logs"

    @property
    def adjuntos(self) -> Path:
        return self.home / "adjuntos"

    @property
    def historial(self) -> Path:
        return self.home / "historial"

    @property
    def copias(self) -> Path:
        return self.home / "copias"

    @property
    def run(self) -> Path:
        return self.home / "run"

    def ensure(self) -> None:
        for p in (self.db_dir, self.logs, self.adjuntos, self.historial, self.copias, self.run):
            p.mkdir(parents=True, exist_ok=True)


@dataclass
class AppConfig:
    paths: Paths
    port: int = DEFAULT_PORT
    gemini_model: str = DEFAULT_MODEL
    demo: bool = False
    tick_seconds: float = 20.0
    gemini_api_key: str | None = field(default=None, repr=False)

    @property
    def base_url(self) -> str:
        return f"http://{HOST}:{self.port}"


def env(name: str, default: str = "") -> str:
    """Lee la variable de entorno CORANOTES_<name>."""
    return os.environ.get(f"CORANOTES_{name}", "").strip() or default


def default_home(demo: bool) -> Path:
    r"""%LOCALAPPDATA%\CoraNotes (o CoraNotes-demo para la demostración)."""
    base = Path(os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local"))
    return base / (f"{APP_NAME}-demo" if demo else APP_NAME)


def load_config() -> AppConfig:
    load_dotenv(PROJECT_DIR / ".env")
    demo = env("DEMO") in ("1", "true", "si", "sí")
    home_env = env("HOME_DEMO" if demo else "HOME")
    home = Path(home_env).expanduser() if home_env else default_home(demo)
    try:
        port = int(env("PORT", str(DEFAULT_PORT)))
    except ValueError:
        port = DEFAULT_PORT
    if not 1024 <= port <= 65535:
        port = DEFAULT_PORT
    key = os.environ.get("GEMINI_API_KEY", "").strip() or None
    model = os.environ.get("GEMINI_MODEL", "").strip() or DEFAULT_MODEL
    return AppConfig(paths=Paths(home.resolve()), port=port, gemini_model=model, demo=demo,
                     gemini_api_key=None if demo else key)
