"""SQLite: esquema, conexiones y transacciones. Todas las consultas usan parámetros."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  clave TEXT PRIMARY KEY,
  valor TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ajustes (
  clave TEXT PRIMARY KEY,
  valor TEXT NOT NULL,
  actualizado_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tareas (
  id TEXT PRIMARY KEY,
  proyecto TEXT NOT NULL,
  titulo TEXT NOT NULL,
  titulo_norm TEXT NOT NULL,
  creado_utc TEXT NOT NULL,
  UNIQUE (proyecto, titulo_norm)
);
CREATE TABLE IF NOT EXISTS registros (
  id TEXT PRIMARY KEY,
  fecha TEXT NOT NULL,
  proyecto TEXT NOT NULL DEFAULT '',
  tarea_id TEXT REFERENCES tareas(id),
  actividad TEXT NOT NULL DEFAULT '',
  avance TEXT NOT NULL DEFAULT '',
  tipo_avance TEXT NOT NULL DEFAULT 'en_curso',
  problemas TEXT NOT NULL DEFAULT '',
  solucion TEXT NOT NULL DEFAULT '',
  estado_problema TEXT NOT NULL DEFAULT 'sin_problema',
  proximos_pasos TEXT NOT NULL DEFAULT '',
  estado TEXT NOT NULL,
  archivado INTEGER NOT NULL DEFAULT 0,
  archivado_utc TEXT,
  incluir_ia INTEGER NOT NULL DEFAULT 1,
  origen TEXT NOT NULL DEFAULT 'manual',
  documento_id TEXT,
  revision INTEGER NOT NULL DEFAULT 1,
  creado_utc TEXT NOT NULL,
  actualizado_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_registros_fecha ON registros(fecha);
CREATE TABLE IF NOT EXISTS registro_revisiones (
  registro_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  datos TEXT NOT NULL,
  motivo TEXT NOT NULL,
  creado_utc TEXT NOT NULL,
  PRIMARY KEY (registro_id, revision)
);
CREATE TABLE IF NOT EXISTS dias_sin_actividad (
  fecha TEXT PRIMARY KEY,
  nota TEXT NOT NULL DEFAULT '',
  creado_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidencias (
  id TEXT PRIMARY KEY,
  registro_id TEXT,
  nombre TEXT NOT NULL,
  archivo TEXT NOT NULL,
  mime TEXT NOT NULL,
  tamano INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  origen TEXT NOT NULL,
  documento_id TEXT,
  archivado INTEGER NOT NULL DEFAULT 0,
  creado_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documentos (
  id TEXT PRIMARY KEY,
  ruta_relativa TEXT NOT NULL UNIQUE,
  nombre TEXT NOT NULL,
  extension TEXT NOT NULL,
  estado TEXT NOT NULL,
  motivo TEXT NOT NULL DEFAULT '',
  sha256 TEXT,
  tamano INTEGER,
  version INTEGER NOT NULL DEFAULT 0,
  registro_id TEXT,
  evidencia_id TEXT,
  duplicado_de TEXT,
  metadatos TEXT NOT NULL DEFAULT '{}',
  texto TEXT NOT NULL DEFAULT '',
  origen_presente INTEGER NOT NULL DEFAULT 1,
  creado_utc TEXT NOT NULL,
  actualizado_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documento_versiones (
  documento_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  tamano INTEGER NOT NULL,
  detectado_utc TEXT NOT NULL,
  PRIMARY KEY (documento_id, version)
);
CREATE TABLE IF NOT EXISTS ejecuciones (
  clave TEXT PRIMARY KEY,
  tipo TEXT NOT NULL,
  fecha TEXT NOT NULL,
  programado_utc TEXT NOT NULL,
  estado TEXT NOT NULL,
  avisos INTEGER NOT NULL DEFAULT 0,
  pospuesto_hasta_utc TEXT,
  detalle TEXT NOT NULL DEFAULT '',
  creado_utc TEXT NOT NULL,
  actualizado_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ejecuciones_fecha ON ejecuciones(fecha);
CREATE TABLE IF NOT EXISTS avisos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tipo TEXT NOT NULL,
  titulo TEXT NOT NULL,
  mensaje TEXT NOT NULL,
  enlace TEXT NOT NULL DEFAULT '',
  clave_ejecucion TEXT,
  entrega TEXT NOT NULL DEFAULT 'pendiente',
  entrega_detalle TEXT NOT NULL DEFAULT '',
  leido INTEGER NOT NULL DEFAULT 0,
  creado_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trabajos_ia (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  periodo_clave TEXT NOT NULL,
  motivo TEXT NOT NULL,
  estado TEXT NOT NULL,
  intentos INTEGER NOT NULL DEFAULT 0,
  proximo_intento_utc TEXT,
  hash_entrada TEXT,
  error_tipo TEXT,
  error_mensaje TEXT,
  cierre_id TEXT,
  version_id TEXT,
  creado_utc TEXT NOT NULL,
  actualizado_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS llamadas_ia (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fecha_local TEXT NOT NULL,
  modelo TEXT NOT NULL,
  resultado TEXT NOT NULL,
  tokens_entrada INTEGER,
  tokens_salida INTEGER,
  creado_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS versiones_prompt (
  id TEXT PRIMARY KEY,
  periodo_clave TEXT NOT NULL,
  periodo_inicio TEXT NOT NULL,
  periodo_fin TEXT NOT NULL,
  tipo TEXT NOT NULL,
  modo TEXT NOT NULL,
  es_respaldo INTEGER NOT NULL DEFAULT 0,
  hash_entrada TEXT NOT NULL,
  hash_datos TEXT NOT NULL,
  hash_contenido TEXT NOT NULL,
  fuentes TEXT NOT NULL,
  resumen TEXT,
  advertencias TEXT NOT NULL DEFAULT '[]',
  contenido TEXT NOT NULL,
  base_version_id TEXT,
  nota TEXT NOT NULL DEFAULT '',
  creado_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_versiones_periodo ON versiones_prompt(periodo_clave, creado_utc);
CREATE TABLE IF NOT EXISTS mascota_dias (
  fecha TEXT PRIMARY KEY,
  recompensa TEXT NOT NULL,
  creado_utc TEXT NOT NULL,
  mostrada_utc TEXT
);
CREATE TABLE IF NOT EXISTS cierres (
  id TEXT PRIMARY KEY,
  periodo_clave TEXT NOT NULL,
  periodo_inicio TEXT NOT NULL,
  periodo_fin TEXT NOT NULL,
  disparo TEXT NOT NULL,
  estado TEXT NOT NULL,
  mensaje TEXT NOT NULL DEFAULT '',
  version_id TEXT,
  hash_datos TEXT,
  version_usada_id TEXT,
  presentacion_ref TEXT NOT NULL DEFAULT '',
  presentacion_evidencia_id TEXT,
  creado_utc TEXT NOT NULL,
  actualizado_utc TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = self.connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            conn.execute(
                "INSERT OR IGNORE INTO meta(clave, valor) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
        finally:
            conn.close()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        return conn

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """Transacción de escritura: todo o nada."""
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def tx_or(self, conn: sqlite3.Connection | None) -> Iterator[sqlite3.Connection]:
        """Reutiliza la transacción del llamador o abre una nueva."""
        if conn is not None:
            yield conn
        else:
            with self.tx() as new_conn:
                yield new_conn


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT valor FROM meta WHERE clave = ?", (key,)).fetchone()
    return row["valor"] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(clave, valor) VALUES (?, ?) ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
        (key, value),
    )


def rows(cursor) -> list[dict]:
    return [dict(r) for r in cursor.fetchall()]
