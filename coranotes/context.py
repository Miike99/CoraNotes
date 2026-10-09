"""Arma todos los servicios y los hilos de fondo de un único proceso backend."""
from __future__ import annotations

import logging
import threading

from .ai.service import AIService
from .clock import Clock
from .config import PROJECT_DIR, AppConfig
from .db import Database, get_meta, set_meta
from .evidence import EvidenceService
from .importer import Importer
from .notifier import NoticeService, default_notifier
from .pet import PetService
from .prompts import ClosingService, PromptService
from .records import RecordService
from .scheduler import Scheduler
from .secrets_guard import register_secret
from .settings import SettingsStore
from .util import utc_iso
from .watcher import InboxWatcher

log = logging.getLogger("coranotes")


class AppContext:
    def __init__(self, config: AppConfig, clock: Clock | None = None, notifier=None, provider_factory=None):
        self.config = config
        config.paths.ensure()
        register_secret(config.gemini_api_key)
        self.clock = clock or Clock()
        self.db = Database(config.paths.db)
        with self.db.tx() as c:
            if not get_meta(c, "instalado_utc"):
                set_meta(c, "instalado_utc", utc_iso(self.clock.now()))
        self.settings = SettingsStore(self.db, self.clock)
        if config.demo and self.settings.get("ia").modo == "gemini":
            self.settings.update("ia", {"modo": "demo"})
        self.notices = NoticeService(self.db, self.clock, notifier or default_notifier(), config.base_url)
        self.notices.sound_dir = config.paths.run
        self.records = RecordService(self.db, self.clock, config.paths)
        self.evidence = EvidenceService(self.db, self.clock, config.paths, self.settings)
        self.prompts = PromptService(self.db, self.clock, self.settings, config.paths)
        self.closing = ClosingService(self.db, self.clock, self.settings, self.prompts, self.notices)
        self.ai = AIService(self.db, self.clock, self.settings, config, self.prompts, provider_factory)
        self.ai.closing = self.closing
        self.closing.ai = self.ai
        self.pet = PetService(self.db, self.clock, self.settings, config.base_url)
        self.scheduler = Scheduler(self.db, self.clock, self.settings, self.notices, self.closing, self.pet)
        forbidden = [PROJECT_DIR, config.paths.home]
        self.importer = Importer(self.db, self.clock, self.settings, self.records, self.evidence, self.notices,
                                 forbidden)
        self.watcher = InboxWatcher(self.importer)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self.started_utc = utc_iso(self.clock.now())
        self.thread_status: dict[str, str] = {}

    # ---------- hilos de fondo ----------
    def _loop(self, name: str, interval: float, fn) -> None:
        self.thread_status[name] = "activo"
        while not self._stop.is_set():
            try:
                fn()
                self.thread_status[name] = "activo"
            except Exception:  # noqa: BLE001
                log.exception("Error en el ciclo %s", name)
                self.thread_status[name] = "con errores (ver logs)"
            self._stop.wait(interval)
        self.thread_status[name] = "detenido"

    def _ai_step(self) -> None:
        self.ai.auto_tick()
        while not self._stop.is_set() and self.ai.process_next():
            pass

    def start_background(self) -> None:
        self.ai.recover_interrupted()
        for name, interval, fn in (("programador", self.config.tick_seconds, self.scheduler.tick),
                                   ("ia", 3.0, self._ai_step),
                                   ("carpeta", 1.0, self.watcher.step)):
            t = threading.Thread(target=self._loop, args=(name, interval, fn), name=f"coranotes-{name}", daemon=True)
            t.start()
            self._threads.append(t)

    def stop_background(self) -> None:
        self._stop.set()
        self.watcher.stop()
        for t in self._threads:
            t.join(timeout=10)
