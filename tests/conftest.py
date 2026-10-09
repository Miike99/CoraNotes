"""Fixtures: reloj, notificador y Gemini simulados. Ninguna prueba usa la red ni la API real."""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bitacora.ai.providers import ProviderResult, SimulatedProvider, TemplateProvider  # noqa: E402
from bitacora.ai.template_summary import build_template_summary  # noqa: E402
from bitacora.clock import FakeClock  # noqa: E402
from bitacora.config import AppConfig, Paths  # noqa: E402
from bitacora.context import AppContext  # noqa: E402
from bitacora.notifier import RecordingNotifier  # noqa: E402
from bitacora.records import RegistroIn  # noqa: E402

TZ = ZoneInfo("America/Argentina/Buenos_Aires")
HOY = date(2026, 10, 9)  # viernes
FAKE_KEY = "AIzaFAKE-clave-de-prueba-0123456789abcdefXYZ"


def local(h: int, m: int = 0, day: date = HOY) -> datetime:
    return datetime(day.year, day.month, day.day, h, m, tzinfo=TZ)


class FakeGemini:
    """Simula Gemini: por defecto devuelve el resumen de plantilla; `behavior` permite fallos o trampas."""
    nombre = "gemini"
    etiqueta = "Gemini (simulado en pruebas)"

    def __init__(self):
        self.calls = 0
        self.behavior = None
        self.last_sources = None

    def generate(self, sources, cfg):
        self.calls += 1
        self.last_sources = sources
        if self.behavior:
            return self.behavior(sources, cfg)
        return ProviderResult(build_template_summary(sources).model_dump(), "fake")


@pytest.fixture
def clock():
    return FakeClock(local(12, 0))


@pytest.fixture
def fake_gemini():
    return FakeGemini()


@pytest.fixture
def make_ctx(tmp_path, clock, fake_gemini):
    home = tmp_path / "datos_app"

    def factory(notifier=None):
        cfg = AppConfig(paths=Paths(home), port=8765, gemini_model="gemini-prueba",
                        gemini_api_key=FAKE_KEY, tick_seconds=1)

        def provider(modo):
            return {"gemini": fake_gemini, "demo": SimulatedProvider()}.get(modo, TemplateProvider())
        return AppContext(cfg, clock=clock, notifier=notifier or RecordingNotifier(), provider_factory=provider)
    return factory


@pytest.fixture
def ctx(make_ctx):
    return make_ctx()


def registro(fecha=HOY, **kw) -> RegistroIn:
    base = {"proyecto": "VR Planta", "actividad": "Trabajé en la escena", "estado": "guardado"}
    base.update(kw)
    return RegistroIn(fecha=fecha, **base)


def enable_gemini(ctx):
    ctx.settings.update("ia", {"consentimiento": True, "modo": "gemini"})


def drain(ctx, max_jobs=10):
    n = 0
    while n < max_jobs and ctx.ai.process_next():
        n += 1
    return n
