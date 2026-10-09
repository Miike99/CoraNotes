"""Reloj inyectable: real en la app y simulado en las pruebas."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone


class Clock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FakeClock(Clock):
    def __init__(self, start: datetime):
        if start.tzinfo is None:
            raise ValueError("FakeClock necesita una fecha con zona horaria")
        self._now = start.astimezone(timezone.utc)
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def set(self, value: datetime) -> None:
        with self._lock:
            self._now = value.astimezone(timezone.utc)

    def advance(self, **kwargs) -> datetime:
        with self._lock:
            self._now = self._now + timedelta(**kwargs)
            return self._now
