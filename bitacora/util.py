"""Utilidades compartidas: IDs, hashes, escritura atómica y limpieza de texto."""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("Se esperaba una fecha con zona horaria")
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def new_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(4).upper()}"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def clean_text(value: str | None, max_len: int | None = None) -> str:
    """Normaliza saltos de línea, quita caracteres de control y recorta espacios."""
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_RE.sub("", text).strip()
    if max_len is not None and len(text) > max_len:
        text = text[:max_len]
    return text


def one_line(value: str, max_len: int = 600) -> str:
    text = " ".join(clean_text(value).split())
    if len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return text


def normalize_key(value: str) -> str:
    """Minúsculas sin acentos ni espacios extremos: 'Próximos pasos' -> 'proximos pasos'."""
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.lower().replace("_", " ").split())


def safe_filename(name: str, max_len: int = 80) -> str:
    base = unicodedata.normalize("NFKD", name)
    base = "".join(c for c in base if not unicodedata.combining(c))
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    return (base or "archivo")[:max_len]


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))
