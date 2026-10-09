"""Ventana de Cora, menú, icono de bandeja, lugares para dormir y sincronización con el backend.

No captura pantalla, teclado global, cámara ni micrófono. No toma el foco: la ventana es una
herramienta sin marco que no acepta foco y se muestra sin activarse. Para dormir arriba de una
ventana solo se leen posiciones y tamaños de ventanas.
"""
from __future__ import annotations

import logging
import time

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRectF, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QGuiApplication, QIcon, QPainter
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon, QWidget

from . import lugares
from .client import Backend
from .drawing import (ESCALAS, GATO_H, GATO_RECT, GATO_W, GLOBO_H, GLOBO_W, PLATO_RECT, SUELO, bubble_rect,
                      paint_bubble, paint_cat, tray_pixmap)
from .logic import PetBrain, clamp_to_area
from .sound import SoundPlayer

log = logging.getLogger("coranotes.mascota")
DRAG_THRESHOLD = 6
FAST_MS, IDLE_MS, REDUCED_MS = 50, 120, 500


class PetWindow(QWidget):
    def __init__(self, ctrl: "PetController"):
        super().__init__(None)
        self.ctrl = ctrl
        self.escala = ESCALAS["mediano"]
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

    # ----- geometría: globo arriba (en píxeles) y gato debajo (escalado) -----
    def set_scale(self, tamano: str) -> None:
        self.escala = ESCALAS.get(tamano, ESCALAS["mediano"])
        cat_w = GATO_W * self.escala
        self.cat_x0 = max(0.0, (GLOBO_W - cat_w) / 2)
        self.setFixedSize(int(max(cat_w, GLOBO_W)), int(GLOBO_H + GATO_H * self.escala))
        self.update()

    def ground_px(self, pose: str) -> int:
        """Distancia desde el borde superior de la ventana hasta la línea de apoyo de la pose."""
        return int(GLOBO_H + SUELO[pose] * self.escala)

    def to_cat(self, pos) -> tuple[float, float]:
        return (pos.x() - self.cat_x0) / self.escala, (pos.y() - GLOBO_H) / self.escala

    def paintEvent(self, _event) -> None:
        v = self.ctrl.current_visual
        p = QPainter(self)
        p.save()
        p.translate(self.cat_x0, GLOBO_H)
        p.scale(self.escala, self.escala)
        paint_cat(p, v, self.ctrl.now())
        p.restore()
        paint_bubble(p, v, self.cat_x0 + 96 * self.escala)
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
            self.ctrl.drag_started()
        if self._dragging:
            self.move(gp - self._offset)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton or self._press is None:
            return
        was_drag = self._dragging
        self._press, self._dragging = None, False
        if was_drag:
            self.ctrl.drag_finished()
            return
        v = self.ctrl.current_visual
        if v.globo and v.globo_clic and bubble_rect(v).contains(e.position()):
            self.ctrl.open_form()
            return
        x, y = self.to_cat(e.position())
        if v.pose == "sentada" and PLATO_RECT.contains(x, y):
            self.ctrl.open_form()
        elif (GATO_RECT if v.pose == "sentada" else QRectF(0, 60, GATO_W, GATO_H - 60)).contains(x, y):
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
        self.home = QPoint()          # lugar elegido por la persona (despierta)
        self.lugar_actual: str | None = None   # «ventana» / «panza» mientras duerme fuera de casa
        self._ultimo_chequeo = 0.0
        self._anim: QPropertyAnimation | None = None
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

    # ---------- arranque y posición ----------
    def start(self) -> None:
        self._default_position()
        self.window.show()
        self.timer.start(IDLE_MS)
        self.backend.start()

    def _default_position(self) -> None:
        area = QGuiApplication.primaryScreen().availableGeometry()
        self.window.move(area.right() - self.window.width() - 24, area.bottom() - self.window.height() - 12)
        self.home = self.window.pos()

    def _screen_added(self, screen) -> None:
        screen.availableGeometryChanged.connect(lambda *_: self.ensure_visible())

    def _screen_for(self, point: QPoint):
        return QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()

    def ensure_visible(self, save: bool = False) -> None:
        """Mantiene la ventana dentro del área visible del monitor donde está (o del principal)."""
        if self.lugar_actual:  # durmiendo fuera de casa: se recalcula el lugar
            self._ultimo_chequeo = 0.0
            return
        geo = self.window.frameGeometry()
        a = self._screen_for(geo.center()).availableGeometry()
        x, y = clamp_to_area(geo.x(), geo.y(), geo.width(), geo.height(), (a.x(), a.y(), a.width(), a.height()))
        if (x, y) != (geo.x(), geo.y()):
            self.window.move(x, y)
        self.home = QPoint(x, y)
        if save:
            self.backend.command("config", {"posicion_x": x, "posicion_y": y})

    def drag_started(self) -> None:
        if self._anim:
            self._anim.stop()
        if self.lugar_actual:  # al arrastrarla, se despierta y vuelve a la pose sentada
            self.lugar_actual = None
            self.brain.lugar_dormir = None
            self.brain.pet(self.now())

    def drag_finished(self) -> None:
        self.ensure_visible(save=True)

    def _glide(self, target: QPoint) -> None:
        if self._anim:
            self._anim.stop()
        if self.brain.reducido or (self.window.pos() - target).manhattanLength() < 4:
            self.window.move(target)
            return
        self._anim = QPropertyAnimation(self.window, b"pos")
        self._anim.setDuration(650)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._anim.setEndValue(target)
        self._anim.start()

    # ---------- dormir arriba de una ventana o sobre la barra de tareas ----------
    def _sleep_target(self) -> tuple[str, QPoint] | None:
        lugar = self.cfg.get("lugar_dormir", "escritorio")
        if lugar == "escritorio":
            return None
        w = self.window
        home_center = QPoint(self.home.x() + w.width() // 2, self.home.y() + w.height() // 2)
        screen = self._screen_for(home_center)
        avail, geo = screen.availableGeometry(), screen.geometry()
        area = lugares.Rect(avail.left(), avail.top(), avail.right() + 1, avail.bottom() + 1)
        if lugar == "ventanas":
            dpr = screen.devicePixelRatio() or 1.0
            ground = w.ground_px("ventana")
            for r in lugares.candidate_windows():
                rect = lugares.Rect(int(r.left / dpr), int(r.top / dpr), int(r.right / dpr), int(r.bottom / dpr))
                pos = lugares.perch_position(rect, area, w.width(), w.height(), ground, prefer_x=self.home.x())
                if pos is not None:
                    return "ventana", QPoint(*pos)
            # sin ventanas con lugar arriba: sobre la barra de tareas
        full = lugares.Rect(geo.left(), geo.top(), geo.right() + 1, geo.bottom() + 1)
        x, y = lugares.taskbar_position(area, full, w.width(), w.ground_px("panza"), prefer_x=self.home.x())
        return "panza", QPoint(x, y)

    def _update_sleep_place(self, t: float) -> None:
        quiere = self.brain.quiere_dormir(t) and self.window.isVisible() and self._press_free()
        if not quiere or self.cfg.get("lugar_dormir", "escritorio") == "escritorio":
            if self.lugar_actual:
                self.lugar_actual = None
                self.brain.lugar_dormir = None
                self._glide(self.home)
            return
        if self.lugar_actual and t - self._ultimo_chequeo < 1.5:
            return
        self._ultimo_chequeo = t
        destino = self._sleep_target()
        if destino is None:
            return
        pose, pos = destino
        if pose != self.lugar_actual or (pos - self.window.pos()).manhattanLength() > 3:
            if self._anim is None or self._anim.state() != QPropertyAnimation.State.Running or pose != self.lugar_actual:
                self.lugar_actual = pose
                self.brain.lugar_dormir = pose
                self._glide(pos)

    def _press_free(self) -> bool:
        return self.window._press is None

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
            bottom = self.window.y() + self.window.height()
            self.window.set_scale(cfg.get("tamano", "mediano"))
            if old:  # mantiene a Cora apoyada en el mismo lugar al cambiar de tamaño
                self.window.move(self.window.x(), bottom - self.window.height())
            self.ensure_visible()
            self._ultimo_chequeo = 0.0
        if cfg.get("siempre_visible") != old.get("siempre_visible"):
            self.window.apply_flags(bool(cfg.get("siempre_visible", True)))
        self.brain.reducido = bool(cfg.get("reducir_animaciones"))
        if not self._pos_aplicada:
            self._pos_aplicada = True
            if cfg.get("posicion_x") is not None and cfg.get("posicion_y") is not None:
                self.window.move(int(cfg["posicion_x"]), int(cfg["posicion_y"]))
                self.ensure_visible()
        if cfg.get("lugar_dormir") != old.get("lugar_dormir"):
            self._ultimo_chequeo = 0.0
        if cfg.get("habilitada") is False:
            log.info("Cora está desactivada en la configuración: se cierra")
            self.quit()

    # ---------- animación ----------
    def tick(self) -> None:
        t = self.now()
        self._update_sleep_place(t)
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
            interval = 2000  # oculta: casi sin consumo
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

    def _set_cfg(self, clave: str, valor) -> None:
        cfg = dict(self.cfg)
        cfg[clave] = valor
        self.apply_config(cfg)
        self.backend.command("config", {clave: valor})

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
    def _radio_menu(self, parent: QMenu, titulo: str, clave: str, opciones) -> dict:
        sub = parent.addMenu(titulo)
        grupo = QActionGroup(sub)
        acciones = {}
        for valor, texto in opciones:
            a = QAction(texto, sub, checkable=True)
            a.triggered.connect(lambda _=False, v=valor: self._set_cfg(clave, v))
            grupo.addAction(a)
            sub.addAction(a)
            acciones[valor] = a
        return acciones

    def _build_menu(self) -> None:
        m = self.menu
        self.a_mostrar = m.addAction("Mostrar a Cora", self.show_pet)
        self.a_registrar = m.addAction("Registrar actividades de hoy", self.open_form)
        m.addAction("Abrir CoraNotes", self.open_app)
        self.a_posponer = m.addAction("Posponer recordatorio", lambda: self.backend.command("posponer"))
        self.a_ocultar = m.addAction("Ocultar a Cora (queda en la bandeja)", self.hide_pet)
        self.a_silenciar = m.addAction("Silenciar recordatorios hasta mañana", self._silence)
        m.addSeparator()
        self.a_tam = self._radio_menu(m, "Tamaño", "tamano",
                                      (("chico", "Chico"), ("mediano", "Mediano"), ("grande", "Grande")))
        self.a_lugar = self._radio_menu(m, "Dónde duerme", "lugar_dormir",
                                        (("escritorio", "En su lugar del escritorio"),
                                         ("ventanas", "Arriba de la ventana activa"),
                                         ("barra_tareas", "Panza arriba sobre la barra de tareas")))
        opciones = m.addMenu("Opciones")
        self.a_encima = opciones.addAction("Mantener sobre otras ventanas")
        self.a_encima.setCheckable(True)
        self.a_encima.triggered.connect(lambda v: self._set_cfg("siempre_visible", v))
        self.a_reducir = opciones.addAction("Reducir animaciones")
        self.a_reducir.setCheckable(True)
        self.a_reducir.triggered.connect(lambda v: self._set_cfg("reducir_animaciones", v))
        self.a_sonidos = opciones.addAction("Maullidos y sonidos")
        self.a_sonidos.setCheckable(True)
        self.a_sonidos.triggered.connect(lambda v: self._set_cfg("sonidos", v))
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
        for valor, a in self.a_tam.items():
            a.setChecked(valor == self.cfg.get("tamano", "mediano"))
        for valor, a in self.a_lugar.items():
            a.setChecked(valor == self.cfg.get("lugar_dormir", "escritorio"))

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
