"""Evita que la clave de Gemini aparezca en logs, respuestas o exportaciones."""
from __future__ import annotations

import logging
import re
import threading

_PATTERNS = [re.compile(r"AIza[0-9A-Za-z_\-]{30,}")]
_known: set[str] = set()
_lock = threading.Lock()
MASK = "[CLAVE OCULTA]"


def register_secret(value: str | None) -> None:
    if value and len(value) >= 8:
        with _lock:
            _known.add(value)


def redact(text: str) -> str:
    if not text:
        return text
    with _lock:
        known = list(_known)
    for secret in known:
        text = text.replace(secret, MASK)
    for pattern in _PATTERNS:
        text = pattern.sub(MASK, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - nunca romper el logging
            return True
        record.msg = redact(message)
        record.args = ()
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True
