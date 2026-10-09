"""Evidencias locales (imágenes, PDF, presentaciones). Se sirven solo por ID interno."""
from __future__ import annotations

from pathlib import Path

from .db import rows
from .records import AppError, NotFound
from .util import atomic_write_bytes, clean_text, new_id, sha256_bytes, utc_iso

ALLOWED = {
    ".png": ("image/png", [b"\x89PNG\r\n\x1a\n"]),
    ".jpg": ("image/jpeg", [b"\xff\xd8\xff"]),
    ".jpeg": ("image/jpeg", [b"\xff\xd8\xff"]),
    ".pdf": ("application/pdf", [b"%PDF-"]),
    ".pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", [b"PK\x03\x04"]),
}
IMAGE_MIMES = {"image/png", "image/jpeg"}


def check_content(ext: str, data: bytes) -> str:
    ext = ext.lower()
    if ext not in ALLOWED:
        raise AppError("Tipo de archivo no permitido. Se aceptan PNG, JPEG, PDF y PPTX.")
    mime, magics = ALLOWED[ext]
    if not any(data.startswith(m) for m in magics):
        raise AppError("El contenido del archivo no coincide con su extensión.")
    return mime


class EvidenceService:
    def __init__(self, db, clock, paths, settings):
        self.db = db
        self.clock = clock
        self.paths = paths
        self.settings = settings

    def add(self, nombre: str, data: bytes, registro_id: str | None = None, origen: str = "subida",
            documento_id: str | None = None, conn=None) -> dict:
        limit = self.settings.get("limites").documento_bytes
        if len(data) == 0:
            raise AppError("El archivo está vacío")
        if len(data) > limit:
            raise AppError(f"El archivo supera el límite de {limit // (1024 * 1024)} MB")
        nombre = clean_text(Path(nombre).name, 150) or "archivo"
        ext = Path(nombre).suffix.lower()
        mime = check_content(ext, data)
        digest = sha256_bytes(data)
        eid = new_id("EVI")
        stored = f"{eid}{ext}"
        atomic_write_bytes(self.paths.adjuntos / stored, data)
        try:
            with self.db.tx_or(conn) as c:
                if registro_id and not c.execute("SELECT 1 FROM registros WHERE id=?", (registro_id,)).fetchone():
                    raise NotFound("No existe el registro indicado")
                c.execute("INSERT INTO evidencias(id, registro_id, nombre, archivo, mime, tamano, sha256, origen, "
                          "documento_id, creado_utc) VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (eid, registro_id, nombre, stored, mime, len(data), digest, origen, documento_id,
                           utc_iso(self.clock.now())))
        except Exception:
            (self.paths.adjuntos / stored).unlink(missing_ok=True)
            raise
        return self.get(eid, conn)

    def get(self, eid: str, conn=None) -> dict:
        if conn is not None:
            row = conn.execute("SELECT * FROM evidencias WHERE id = ?", (eid,)).fetchone()
        else:
            with self.db.read() as c:
                row = c.execute("SELECT * FROM evidencias WHERE id = ?", (eid,)).fetchone()
        if not row:
            raise NotFound("No existe esa evidencia")
        return dict(row)

    def list(self, registro_id: str | None = None, sin_registro: bool = False) -> list[dict]:
        sql = "SELECT id, registro_id, nombre, mime, tamano, origen, documento_id, creado_utc FROM evidencias " \
              "WHERE archivado = 0"
        params: list = []
        if registro_id:
            sql += " AND registro_id = ?"
            params.append(registro_id)
        elif sin_registro:
            sql += " AND registro_id IS NULL"
        with self.db.read() as c:
            return rows(c.execute(sql + " ORDER BY creado_utc DESC LIMIT 300", params))

    def link(self, eid: str, registro_id: str | None) -> dict:
        with self.db.tx() as c:
            self.get(eid, c)
            if registro_id and not c.execute("SELECT 1 FROM registros WHERE id=?", (registro_id,)).fetchone():
                raise NotFound("No existe el registro indicado")
            c.execute("UPDATE evidencias SET registro_id = ? WHERE id = ?", (registro_id, eid))
            c.execute("INSERT INTO meta(clave, valor) VALUES ('datos_cambiados_utc', ?) "
                      "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor", (utc_iso(self.clock.now()),))
        return self.get(eid)

    def file_path(self, eid: str) -> tuple[Path, dict]:
        ev = self.get(eid)
        path = (self.paths.adjuntos / ev["archivo"]).resolve()
        if path.parent != self.paths.adjuntos.resolve() or not path.is_file():
            raise NotFound("El archivo de la evidencia no está disponible")
        return path, ev
