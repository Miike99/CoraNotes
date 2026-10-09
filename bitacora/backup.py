"""Copia de seguridad local (zip) y restauración con la app detenida."""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from .config import DB_NAME, LEGACY_DB_NAME
from .records import AppError

LEEME = """Copia de seguridad de CoraNotes
=================================
Contiene: base de datos (datos/), adjuntos/ e historial/.
NO contiene: el archivo .env ni la clave de Gemini.
Los archivos NO están cifrados: guardá esta copia en un lugar protegido.

Para restaurar (con la app detenida):
  .\\scripts\\restaurar_copia.ps1 -Archivo "ruta\\a\\esta\\copia.zip"
"""
INCLUDED = ("datos", "adjuntos", "historial")


def create_backup(paths, now: datetime) -> Path:
    paths.copias.mkdir(parents=True, exist_ok=True)
    target = paths.copias / f"coranotes-copia-{now.strftime('%Y%m%d-%H%M%S')}.zip"
    with tempfile.TemporaryDirectory(dir=paths.copias) as tmp:
        db_copy = Path(tmp) / DB_NAME
        src = sqlite3.connect(paths.db)
        dst = sqlite3.connect(db_copy)
        try:
            src.backup(dst)  # copia consistente aunque la app esté en uso
        finally:
            dst.close()
            src.close()
        partial = target.with_suffix(".zip.part")
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("LEEME.txt", LEEME)
            zf.write(db_copy, f"datos/{DB_NAME}")
            for folder in ("adjuntos", "historial"):
                base = paths.home / folder
                if not base.exists():
                    continue
                for f in base.rglob("*"):
                    if f.is_file() and not f.is_symlink() and not f.name.startswith(".tmp-"):
                        zf.write(f, f"{folder}/{f.relative_to(base).as_posix()}")
        partial.replace(target)
    return target


def list_backups(paths) -> list[dict]:
    if not paths.copias.exists():
        return []
    out = []
    for f in sorted([*paths.copias.glob("coranotes-copia-*.zip"), *paths.copias.glob("bitacora-copia-*.zip")],
                    key=lambda f: f.name.split("-copia-")[-1], reverse=True):
        out.append({"nombre": f.name, "tamano": f.stat().st_size, "ruta": str(f)})
    return out


def restore_backup(paths, archive: Path) -> Path:
    """Restaura una copia. Mueve los datos actuales a una carpeta de resguardo (no los borra)."""
    archive = Path(archive).resolve()
    if not archive.is_file():
        raise AppError("No existe el archivo de copia")
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        if f"datos/{DB_NAME}" not in names and f"datos/{LEGACY_DB_NAME}" not in names:
            raise AppError("El zip no parece una copia de CoraNotes")
        for n in names:
            p = PurePosixPath(n)
            if p.is_absolute() or ".." in p.parts or ":" in n or (p.parts and p.parts[0] not in (*INCLUDED, "LEEME.txt")):
                raise AppError(f"Entrada no permitida en la copia: {n}")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        resguardo = paths.home / f"resguardo-antes-de-restaurar-{stamp}"
        resguardo.mkdir(parents=True)
        for folder in INCLUDED:
            cur = paths.home / folder
            if cur.exists():
                shutil.move(str(cur), str(resguardo / folder))
        for n in names:
            if n.endswith("/") or n == "LEEME.txt":
                continue
            dest = (paths.home / n).resolve()
            if not dest.is_relative_to(paths.home.resolve()):
                raise AppError("Ruta inválida en la copia")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(n) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
    return resguardo
