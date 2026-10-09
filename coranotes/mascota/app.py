"""Ventana de Cora, menú, icono de bandeja y sincronización con el backend.

No captura pantalla, teclado global, cámara ni micrófono. No toma el foco: la ventana es una
herramienta sin marco que no acepta foco y se muestra sin activarse.
"""
from __future__ import annotations

import logging
import time

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QGuiApplication, QIcon, QPainter
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon, QWidget

from .client import Backend
from .drawing import BASE_H, BASE_W, ESCALAS, GATO_RECT, GLOBO_RECT, PLATO_RECT, paint_pet, tray_pixmap
from .logic import PetBrain, clamp_to_area
from .sound import SoundPlayer

log = logging.getLogger("coranotes.mascota")
DRAG_THRESHOLD = 6
FAST_MS, IDLE_MS, REDUCED_MS = 50, 140, 500


class PetWindow(QWidget):
    def __init__(self, ctrl: "PetController"):
        super().__init__(None)
        self.ctrl = ctrl
        self.escala = 1.0
        self._press: QPoint | None = None
        self._offset = QPoint()
        self._dragging = False
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWindowTitle("Cora · CoraNotes")
        self.apply_flags(True)
        self.set_scale("mediano")

    def apply_flags(self, on_top: bool) -> None:
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus
                 | Qt.WindowType.NoDropShadowWindowHint)
        if on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        visible = self.isVisible()
        self.setWindowFlags(flags)
        if visible:
            self.show()

    def set_scale(self, tamano: str) -> None:
        self.escala = ESCALAS.get(tamano, 1.0)
        self.setFixedSize(int(BASE_W * self.escala), int(BASE_H * self.escala))
        self.update()

    def _logical(self, pos) -> tuple[float, float]:
        return pos.x() / self.escala, pos.y() / self.escala

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.scale(self.escala, self.escala)
        paint_pet(p, self.ctrl.current_visual, self.ctrl.now())
        p.end()

    # ----- ratón: arrastrar, acariciar, abrir formulario -----
    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.globalPosition().toPoint()
            self._offset = self._press - self.frameGeometry().topLeft()
            self._dragging = False

    def mouseMoveEvent(self, e) -> None:
        if self._press is None:
            return
        gp = e.globalPosition().toPoint()
        if not self._dragging and (gp - self._press).manhattanLength() > DRAG_THRESHOLD:
            self._dragging = True
        if self._dragging:
            self.move(gp - self._offset)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton or self._press is None:
            return
        was_drag = self._dragging
        self._press, self._dragging = None, False
        if was_drag:
            self.ctrl.ensure_visible(save=True)
            return
        x, y = self._logical(e.position())
        v = self.ctrl.current_visual
        globo = QRectF(GLOBO_RECT)
        if v.globo and v.globo_clic and globo.contains(x, y):
            self.ctrl.open_form()
        elif PLATO_RECT.contains(x, y):
            self.ctrl.open_form()
        elif GATO_RECT.contains(x, y):
            self.ctrl.pet()

    def contextMenuEvent(self, e) -> None:
        self.ctrl.refresh_menu()
        self.ctrl.menu.popup(e.globalPos())


class PetController:
    def __init__(self, app: QApplication, config):
        self.app = app
        self.config = config
        self.t0 = time.monotonic()
        self.brain = PetBrain()
        self.current_visual = self.brain.visual(0.0)
        self.state: dict = {}
        self.cfg: dict = {}
        self._pos_aplicada = False
        self._mostrar_visto: int | None = None
        self.sound = SoundPlayer(config.paths.run)
        self.window = PetWindow(self)
        self.backend = Backend(config.base_url, config.paths.run)
        self.backend.estado.connect(self.on_state)
        self.backend.desconectado.connect(self.on_disconnected)
        self.backend.resultado.connect(self.on_result)
        self.backend.salir.connect(self.quit)
        self.menu = QMenu()
        self._build_menu()
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(QIcon(tray_pixmap()))
            self.tray.setToolTip("Cora · CoraNotes")
            self.tray.setContextMenu(self.menu)
            self.tray.activated.connect(self.on_tray)
            self.tray.show()
        self.timer = QTimer()
        self.timer.setTimerType(Qt.TimerType.CoarseTimer)
        self.timer.timeout.connect(self.tick)
        for screen in QGuiApplication.screens():
            screen.availableGeometryChanged.connect(lambda *_: self.ensure_visible())
        QGuiApplication.instance().screenAdded.connect(self._screen_added)
        QGuiApplication.instance().screenRemoved.connect(lambda *_: QTimer.singleShot(300, self.ensure_visible))
        app.aboutToQuit.connect(self._about_to_quit)

    def now(self) -> float:
        return time.monotonic() - self.t0

    # ---------- arranque ----------
    def start(self) -> None:
        self._default_position()
        self.window.show()
        self.timer.start(IDLE_MS)
        self.backend.start()

    def _default_position(self) -> None:
        screen = QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        self.window.move(area.right() - self.window.width() - 24, area.bottom() - self.window.height() - 24)

    def _screen_added(self, screen) -> None:
        screen.availableGeometryChanged.connect(lambda *_: self.ensure_visible())

    def ensure_visible(self, save: bool = False) -> None:
        """Mantiene la ventana dentro del área visible del monitor donde está (o del principal)."""
        geo = self.window.frameGeometry()
        screen = QGuiApplication.screenAt(geo.center()) or QGuiApplication.primaryScreen()
        a = screen.availableGeometry()
        x, y = clamp_to_area(geo.x(), geo.y(), geo.width(), geo.height(), (a.x(), a.y(), a.width(), a.height()))
        if (x, y) != (geo.x(), geo.y()):
            self.window.move(x, y)
        if save:
            self.backend.command("config", {"posicion_x": x, "posicion_y": y})

    # ---------- estado del backend ----------
    def on_state(self, st: dict) -> None:
        self.state = st
        self.apply_config(st.get("config", {}))
        for ev in self.brain.on_server_state(st, self.now()):
            if ev[0] == "ack":
                self.backend.ack(ev[1])
            elif ev[0] == "sonido" and self.cfg.get("sonidos"):
                self.sound.play(ev[1])
        pedido = st.get("mostrar_pedido", 0)
        if self._mostrar_visto is not None and pedido != self._mostrar_visto:
            self.show_pet()
        self._mostrar_visto = pedido
        self._update_tray()
        self.tick()

    def on_disconnected(self, _msg: str) -> None:
        self.brain.on_disconnected()
        self._update_tray()
        self.tick()

    def on_result(self, accion: str, ok: bool, msg: str) -> None:
        if accion == "detener" and ok:
            self.quit()
            return
        if not ok and self.tray is not None:
            self.tray.showMessage("CoraNotes", msg, QSystemTrayIcon.MessageIcon.Warning, 4000)
        self.backend.sync_now()

    def apply_config(self, cfg: dict) -> None:
        if not cfg:
            return
        old = self.cfg
        self.cfg = cfg
        if cfg.get("tamano") != old.get("tamano"):
            self.window.set_scale(cfg.get("tamano", "mediano"))
            self.ensure_visible()
        if cfg.get("siempre_visible") != old.get("siempre_visible"):
            self.window.apply_flags(bool(cfg.get("siempre_visible", True)))
        self.brain.reducido = bool(cfg.get("reducir_animaciones"))
        if not self._pos_aplicada:
            self._pos_aplicada = True
            if cfg.get("posicion_x") is not None and cfg.get("posicion_y") is not None:
                self.window.move(int(cfg["posicion_x"]), int(cfg["posicion_y"]))
                self.ensure_visible()
        if cfg.get("habilitada") is False:
            log.info("Cora está desactivada en la configuración: se cierra")
            self.quit()

    # ---------- animación ----------
    def tick(self) -> None:
        t = self.now()
        self.current_visual = self.brain.visual(t)
        if self.window.isVisible():
            self.window.update()
        if self.brain.reducido:
            interval = REDUCED_MS
        elif self.brain.is_animating(t) or self.current_visual.modo == "hambriento":
            interval = FAST_MS
        else:
            interval = IDLE_MS
        if not self.window.isVisible():
            interval = 2000  # oculto: casi sin consumo
        if self.timer.interval() != interval:
            self.timer.setInterval(interval)

    # ---------- acciones ----------
    def pet(self) -> None:
        for ev in self.brain.pet(self.now()):
            if ev[0] == "sonido" and self.cfg.get("sonidos"):
                self.sound.play(ev[1])
        self.tick()

    def open_form(self) -> None:
        fecha_url = self.state.get("url_registro") or f"{self.config.base_url}/#/registro"
        QDesktopServices.openUrl(QUrl(fecha_url))

    def open_app(self) -> None:
        QDesktopServices.openUrl(QUrl(self.state.get("url_app") or f"{self.config.base_url}/"))

    def show_pet(self) -> None:
        self.window.show()
        self.ensure_visible()
        self.backend.visible = True
        self.backend.sync_now()

    def hide_pet(self) -> None:
        self.window.hide()
        self.backend.visible = False  # el backend usa la notificación de Windows como respaldo
        self.backend.sync_now()

    def on_tray(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_pet()

    def _toggle(self, clave: str, valor: bool) -> None:
        self.cfg[clave] = valor
        self.apply_config(dict(self.cfg))
        self.backend.command("config", {clave: valor})

    def _set_size(self, tamano: str) -> None:
        self.backend.command("config", {"tamano": tamano})
        cfg = dict(self.cfg)
        cfg["tamano"] = tamano
        self.apply_config(cfg)

    def _silence(self) -> None:
        activar = self.state.get("estado") != "silenciado"
        self.backend.command("silenciar", {"activar": activar})

    def _stop_all(self) -> None:
        r = QMessageBox.question(None, "Detener CoraNotes",
                                 "¿Detener todo CoraNotes? Se apagan Cora, los recordatorios, la carpeta "
                                 "de entrada y la cola de IA. Tus datos quedan guardados.")
        if r == QMessageBox.StandardButton.Yes:
            self.backend.command("detener")

    def quit(self) -> None:
        self.app.quit()

    def _about_to_quit(self) -> None:
        self.timer.stop()
        self.backend.stop()
        self.backend.final_sync_hidden()
        if self.tray is not None:
            self.tray.hide()

    # ---------- menú ----------
    def _build_menu(self) -> None:
        m = self.menu
        self.a_mostrar = m.addAction("Mostrar a Cora", self.show_pet)
        self.a_registrar = m.addAction("Registrar actividades de hoy", self.open_form)
        m.addAction("Abrir CoraNotes", self.open_app)
        self.a_posponer = m.addAction("Posponer recordatorio", lambda: self.backend.command("posponer"))
        self.a_ocultar = m.addAction("Ocultar a Cora (queda en la bandeja)", self.hide_pet)
        self.a_silenciar = m.addAction("Silenciar recordatorios hasta mañana", self._silence)
        m.addSeparator()
        opciones = m.addMenu("Opciones")
        self.a_encima = opciones.addAction("Mantener sobre otras ventanas")
        self.a_encima.setCheckable(True)
        self.a_encima.triggered.connect(lambda v: self._toggle("siempre_visible", v))
        self.a_reducir = opciones.addAction("Reducir animaciones")
        self.a_reducir.setCheckable(True)
        self.a_reducir.triggered.connect(lambda v: self._toggle("reducir_animaciones", v))
        self.a_sonidos = opciones.addAction("Sonidos")
        self.a_sonidos.setCheckable(True)
        self.a_sonidos.triggered.connect(lambda v: self._toggle("sonidos", v))
        tam = opciones.addMenu("Tamaño")
        grupo = QActionGroup(tam)
        self.a_tam = {}
        for clave, texto in (("chico", "Chico"), ("mediano", "Mediano"), ("grande", "Grande")):
            a = QAction(texto, tam, checkable=True)
            a.triggered.connect(lambda _=False, c=clave: self._set_size(c))
            grupo.addAction(a)
            tam.addAction(a)
            self.a_tam[clave] = a
        m.addSeparator()
        m.addAction("Cerrar a Cora (CoraNotes sigue funcionando)", self.quit)
        m.addAction("Detener todo CoraNotes…", self._stop_all)
        m.aboutToShow.connect(self.refresh_menu)

    def refresh_menu(self) -> None:
        estado = self.state.get("estado")
        self.a_mostrar.setVisible(not self.window.isVisible())
        self.a_ocultar.setEnabled(self.tray is not None and self.window.isVisible())
        self.a_posponer.setEnabled(estado == "hambriento")
        self.a_silenciar.setText("Reactivar recordatorios de hoy" if estado == "silenciado"
                                 else "Silenciar recordatorios hasta mañana")
        self.a_encima.setChecked(bool(self.cfg.get("siempre_visible", True)))
        self.a_reducir.setChecked(bool(self.cfg.get("reducir_animaciones")))
        self.a_sonidos.setChecked(bool(self.cfg.get("sonidos")))
        tam = self.cfg.get("tamano", "mediano")
        for clave, a in self.a_tam.items():
            a.setChecked(clave == tam)

    def _update_tray(self) -> None:
        if self.tray is None:
            return
        textos = {"hambriento": "tiene hambre: falta registrar hoy", "comiendo": "está comiendo",
                  "alimentado": "ya comió: hoy está registrado", "descanso": "está descansando",
                  "silenciado": "recordatorios en silencio hasta mañana", "tranquilo": "está en calma"}
        if not self.brain.conectado:
            texto = "espera la conexión con CoraNotes"
        else:
            texto = textos.get(self.state.get("estado", ""), "")
        self.tray.setToolTip(f"Cora {texto} · CoraNotes".strip())
