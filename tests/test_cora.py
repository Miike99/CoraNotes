"""Cora (mascota de escritorio): estado real del día, recompensa única, canal de aviso y lógica visual."""
from __future__ import annotations

import os
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from coranotes.mascota.logic import PetBrain, clamp_to_area
from coranotes.pet import MENSAJES
from coranotes.records import RegistroIn
from coranotes.web.app import create_app

from conftest import FAKE_KEY, HOY, enable_gemini, local, registro

AYER = HOY - timedelta(days=1)


def toasts(ctx):
    """Notificaciones de Windows de recordatorio (los avisos de cierre semanal se prueban aparte)."""
    return [n for n in ctx.notices.notifier.enviados if "cierre" not in n["titulo"] and "prompt" not in n["titulo"]]


def avisos(ctx, tipo="recordatorio"):
    return [a for a in ctx.notices.list() if a["tipo"] == tipo]


def pet_visible(ctx, visible=True):
    ctx.pet.heartbeat(visible)


# --- hambre / sin aviso ------------------------------------------------------
def test_hambre_cuando_falta_el_registro(ctx, clock):
    assert ctx.pet.state()["estado"] == "tranquilo"  # antes del horario: tranquilo
    clock.set(local(18, 1))
    pet_visible(ctx)
    ctx.scheduler.tick()
    st = ctx.pet.state()
    assert st["estado"] == "hambriento"
    assert st["mensaje"] == ("¡Hora de mi comida! ¿Qué hiciste hoy? Contame tus avances, problemas y soluciones")
    assert st["url_registro"].endswith("#/registro?fecha=2026-10-09")
    assert toasts(ctx) == []                                  # Cora es el canal: sin notificación duplicada
    assert len(avisos(ctx)) == 1 and avisos(ctx)[0]["entrega"] == "solo_app"


def test_sin_aviso_si_ya_hay_registro(ctx, clock):
    ctx.records.create(registro())
    clock.set(local(18, 1))
    pet_visible(ctx)
    ctx.scheduler.tick()
    st = ctx.pet.state()
    assert st["estado"] in ("comiendo", "alimentado")
    assert toasts(ctx) == [] and avisos(ctx) == []


def test_hambre_aunque_el_backend_arranque_tarde(ctx, clock, make_ctx):
    clock.set(local(19, 30))           # el aviso de las 18:00 quedó «perdido» (fuera de la ventana de gracia)
    ctx.scheduler.tick()
    assert ctx.pet.state()["estado"] == "hambriento"


# --- comer: recompensa al guardar, sin esperar a Gemini --------------------
def test_animacion_tras_guardar_sin_esperar_a_gemini(ctx, clock, fake_gemini):
    enable_gemini(ctx)

    def lento(sources, cfg):
        raise AssertionError("Cora no debe depender de Gemini")
    fake_gemini.behavior = lento
    clock.set(local(18, 1))
    pet_visible(ctx)
    ctx.scheduler.tick()
    assert ctx.pet.state()["estado"] == "hambriento"
    ctx.records.create(registro())                    # guardado local: ninguna llamada a la IA en el camino
    st = ctx.pet.state()
    assert st["estado"] == "comiendo" and st["recompensa_pendiente"] is True
    assert fake_gemini.calls == 0


def test_funciona_sin_gemini_ni_clave(make_ctx, clock):
    ctx = make_ctx()
    ctx.config.gemini_api_key = None
    assert ctx.settings.get("ia").modo == "plantilla"
    clock.set(local(18, 1))
    ctx.scheduler.tick()
    assert ctx.pet.state()["estado"] == "hambriento"
    ctx.records.create(registro())
    assert ctx.pet.state()["estado"] == "comiendo"


# --- recompensa única y persistente ----------------------------------------
def test_recompensa_una_vez_y_persistente(ctx, clock, make_ctx, tmp_path):
    rec, _ = ctx.records.create(registro())
    assert ctx.pet.state()["recompensa_pendiente"] is True
    assert ctx.pet.ack_reward(HOY.isoformat()) is True
    assert ctx.pet.ack_reward(HOY.isoformat()) is False   # idempotente

    # Más actividades, ediciones e importaciones duplicadas no repiten la recompensa.
    ctx.records.create(registro(actividad="Otra"))
    ctx.records.update(rec["id"], RegistroIn(fecha=HOY, proyecto="VR Planta", actividad="Editada", estado="guardado"))
    inbox = tmp_path / "entrada"
    inbox.mkdir()
    ctx.settings.update("entrada", {"carpeta": str(inbox), "activa": True})
    contenido = "Fecha: 2026-10-09\nProyecto: VR Planta\n\n## Actividad\nImportada\n"
    (inbox / "a.md").write_text(contenido, encoding="utf-8")
    (inbox / "b.md").write_text(contenido, encoding="utf-8")
    ctx.importer.scan()
    st = ctx.pet.state()
    assert st["estado"] == "alimentado" and st["recompensa_pendiente"] is False

    reiniciado = make_ctx()                                  # reinicio: mismo directorio de datos
    st = reiniciado.pet.state()
    assert st["estado"] == "alimentado" and st["recompensa_pendiente"] is False


def test_recompensa_pendiente_sobrevive_reinicio_y_se_muestra_una_vez(ctx, make_ctx):
    ctx.records.create(registro())
    ctx.pet.state()                                          # se generó la recompensa, pero Cora estaba cerrada
    otro = make_ctx()
    assert otro.pet.state()["recompensa_pendiente"] is True
    otro.pet.ack_reward(HOY.isoformat())
    assert otro.pet.state()["recompensa_pendiente"] is False


# --- lo que NO alimenta ------------------------------------------------------
def test_borradores_archivos_y_dias_anteriores_no_alimentan(ctx, clock, tmp_path):
    inbox = tmp_path / "entrada"
    inbox.mkdir()
    ctx.settings.update("entrada", {"carpeta": str(inbox), "activa": True})
    (inbox / "vacio.txt").write_text("", encoding="utf-8")
    (inbox / "pendiente.txt").write_text("Algo sin fecha ni proyecto", encoding="utf-8")
    (inbox / "ayer.md").write_text("Fecha: 2026-10-08\nProyecto: P\n\n## Actividad\nAyer\n", encoding="utf-8")
    from coranotes.demo import tiny_png
    (inbox / "captura.png").write_bytes(tiny_png())
    ctx.importer.scan()
    ctx.records.create(registro(estado="borrador", actividad=""))
    ctx.records.create(registro(fecha=AYER))
    clock.set(local(18, 1))
    ctx.scheduler.tick()
    st = ctx.pet.state()
    assert st["estado"] == "hambriento" and st["recompensa_pendiente"] is False


def test_importacion_valida_de_hoy_alimenta(ctx, clock, tmp_path):
    inbox = tmp_path / "entrada"
    inbox.mkdir()
    ctx.settings.update("entrada", {"carpeta": str(inbox), "activa": True})
    clock.set(local(18, 1))
    ctx.scheduler.tick()
    assert ctx.pet.state()["estado"] == "hambriento"
    (inbox / "hoy.md").write_text("Fecha: 09/10/2026\nProyecto: VR\n\n## Actividad\nHoy\n", encoding="utf-8")
    ctx.importer.scan()
    assert ctx.pet.state()["estado"] == "comiendo"


# --- descanso, días excluidos, pausa, silencio y posponer --------------------
def test_sin_actividad_y_dias_excluidos_no_dan_hambre(ctx, clock):
    ctx.records.declare_no_activity(HOY)
    clock.set(local(18, 1))
    pet_visible(ctx)
    ctx.scheduler.tick()
    st = ctx.pet.state()
    assert st["estado"] == "descanso" and st["mensaje"] == MENSAJES["descanso"]
    assert toasts(ctx) == [] and avisos(ctx) == []
    sabado = HOY + timedelta(days=1)
    clock.set(local(18, 5, sabado))
    assert ctx.pet.state()["estado"] == "descanso"            # día no configurado
    lunes = HOY + timedelta(days=3)
    ctx.settings.update("recordatorio", {"excepciones": [lunes.isoformat()]})
    clock.set(local(18, 5, lunes))
    assert ctx.pet.state()["estado"] == "descanso"            # excepción
    martes = lunes + timedelta(days=1)
    ctx.settings.update("recordatorio", {"pausado": True})
    clock.set(local(18, 5, martes))
    ctx.scheduler.tick()
    assert ctx.pet.state()["estado"] == "descanso" and toasts(ctx) == []
    for texto in MENSAJES.values():                           # sin culpas, enfermedad ni muerte
        assert not any(p in texto.lower() for p in ("muer", "enferm", "culpa", "triste", "abandon"))


def test_posponer_y_silenciar_desde_cora(ctx, clock):
    clock.set(local(18, 1))
    pet_visible(ctx)
    ctx.scheduler.tick()
    ctx.pet.snooze()
    assert ctx.pet.state()["estado"] == "tranquilo"
    clock.set(local(18, 17))
    pet_visible(ctx)                                          # latido periódico de Cora (cada 3 s)
    ctx.scheduler.tick()
    assert ctx.pet.state()["estado"] == "hambriento"
    assert toasts(ctx) == [] and len(avisos(ctx)) == 2        # un aviso por disparo, solo en la app

    ctx.pet.set_silence(True)
    assert ctx.pet.state()["estado"] == "silenciado"
    ctx.settings.update("recordatorio", {"puntuales": [{"fecha": HOY.isoformat(), "hora": "19:00"}]})
    clock.set(local(19, 1))
    ctx.scheduler.tick()                                      # silenciado: ni Cora ni Windows
    assert ctx.pet.state()["estado"] == "silenciado" and len(avisos(ctx)) == 2 and toasts(ctx) == []
    clock.set(local(9, 0, HOY + timedelta(days=3)))          # al día siguiente hábil el silencio ya no aplica
    assert ctx.pet.state()["estado"] == "tranquilo"


# --- canal: Cora o notificación de Windows, nunca ambos -------------------
def test_respaldo_con_notificacion_si_cora_esta_oculta_o_cerrada(ctx, clock, make_ctx):
    pet_visible(ctx, visible=False)                          # oculto en la bandeja
    clock.set(local(18, 1))
    ctx.scheduler.tick()
    assert len(toasts(ctx)) == 1                             # respaldo: notificación de Windows

    lunes = HOY + timedelta(days=3)
    pet_visible(ctx, visible=True)
    clock.set(local(18, 1, lunes))                           # el último latido venció (> 45 s): Cora cerrada
    ctx.scheduler.tick()
    assert len(toasts(ctx)) == 2

    ctx.settings.update("mascota", {"notificacion_respaldo": False})
    clock.set(local(18, 1, lunes + timedelta(days=1)))
    ctx.scheduler.tick()
    assert len(toasts(ctx)) == 2                              # respaldo desactivado: solo aviso en la app
    assert avisos(ctx)[0]["entrega"] == "solo_app"


# --- zona horaria -------------------------------------------------------------
def test_dia_segun_zona_horaria_configurada(ctx, clock):
    clock.set(local(23, 30))                                  # 02:30 UTC del día siguiente
    assert ctx.pet.state()["fecha"] == "2026-10-09"
    ctx.records.create(registro(fecha=HOY))
    assert ctx.pet.state()["estado"] == "comiendo"
    ctx.settings.update("recordatorio", {"zona": "UTC"})
    assert ctx.pet.state()["fecha"] == "2026-10-10"


# --- API local -----------------------------------------------------------------
def test_api_mascota_token_local_y_sin_secretos(ctx):
    app = create_app(ctx, pet_token_getter=lambda: "token-mascota-prueba")
    c = TestClient(app, base_url="http://127.0.0.1:8765")
    assert c.post("/api/mascota/sincronizar", json={"visible": True}).status_code == 403
    assert c.post("/api/mascota/sincronizar", json={"visible": True},
                  headers={"X-CoraNotes-Mascota": "otro"}).status_code == 403
    r = c.post("/api/mascota/sincronizar", json={"visible": True}, headers={"X-CoraNotes-Mascota": "token-mascota-prueba"})
    assert r.status_code == 200 and FAKE_KEY not in r.text and "api_key" not in r.text.lower()
    assert ctx.pet.presence()["visible"] is True
    r = c.post("/api/mascota/config", json={"tamano": "grande", "posicion_x": 10, "posicion_y": 20, "otra": 1},
               headers={"X-CoraNotes-Mascota": "token-mascota-prueba"})
    assert r.json()["tamano"] == "grande" and "otra" not in r.json()
    assert c.post("/api/mascota/config", json={"tamano": "gigante"},
                  headers={"X-CoraNotes-Mascota": "token-mascota-prueba"}).status_code == 422
    # El token de Cora no sirve fuera de /api/mascota/.
    assert c.post("/api/registros", json={}, headers={"X-CoraNotes-Mascota": "token-mascota-prueba"}).status_code == 403
    # La web guarda cambios parciales sin pisar la posición.
    token = c.get("/api/sesion").json()["csrf"]
    c.put("/api/config/mascota", json={"sonidos": True}, headers={"X-CSRF-Token": token})
    cfg = ctx.settings.get("mascota")
    assert cfg.sonidos is True and cfg.posicion_x == 10 and cfg.sonidos is True


# --- lógica visual (sin Qt) -----------------------------------------------------
def test_logica_recompensa_una_vez_y_conexion_pendiente():
    b = PetBrain()
    v = b.visual(0.0)
    assert v.desconectado and v.globo.startswith("Conectando")
    st = {"fecha": "2026-10-09", "estado": "comiendo", "recompensa_pendiente": True, "mensaje": ""}
    ev = b.on_server_state(st, 1.0)
    assert ("ack", "2026-10-09") in ev
    assert b.visual(2.0).modo == "comiendo" and b.visual(2.0).plato == "lleno"
    assert ("ack", "2026-10-09") not in b.on_server_state(st, 3.0)   # el backend aún no procesó el ack
    assert b.visual(20.0).modo == "alimentado"
    b.on_disconnected()
    v = b.visual(21.0)
    assert v.desconectado and not v.gris and v.modo == "alimentado"   # conserva el último estado conocido
    hambre = {"fecha": "2026-10-10", "estado": "hambriento", "recompensa_pendiente": False,
              "mensaje": MENSAJES["hambriento"]}
    b.on_server_state(hambre, 30.0)
    v = b.visual(30.5)
    assert v.globo == MENSAJES["hambriento"] and v.globo_clic and v.plato == "vacio" and not v.desconectado


def test_logica_animaciones_reducidas_y_caricias():
    b = PetBrain(reducido=True)
    b.on_server_state({"fecha": "f", "estado": "tranquilo", "recompensa_pendiente": False}, 0.0)
    assert b.visual(1.0).cola == 0.0
    b.pet(2.0)
    assert b.visual(2.5).corazones > 0 and b.visual(2.5).ojos == "felices"
    b2 = PetBrain()
    b2.on_server_state({"fecha": "f", "estado": "descanso", "recompensa_pendiente": False}, 0.0)
    assert b2.visual(1.0).zzz is True


def test_mantener_dentro_del_area_visible():
    area = (0, 0, 1920, 1040)
    assert clamp_to_area(-500, 300, 250, 260, area) == (0, 300)
    assert clamp_to_area(1800, 1000, 250, 260, area) == (1670, 780)
    assert clamp_to_area(3000, -50, 250, 260, (1920, 0, 1280, 984)) == (2950, 0)


# --- ventana Qt en modo offscreen (sin pantalla real) ----------------------------
def test_ventana_qt_offscreen(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from coranotes.config import AppConfig, Paths
    from coranotes.mascota.app import PetController
    app = QApplication.instance() or QApplication([])
    cfg = AppConfig(paths=Paths(tmp_path / "home"), port=1)  # puerto sin servidor: conexión pendiente
    cfg.paths.ensure()
    ctrl = PetController(app, cfg)
    ctrl.start()
    from PySide6.QtCore import Qt
    flags = ctrl.window.windowFlags()
    assert flags & Qt.WindowType.WindowDoesNotAcceptFocus and flags & Qt.WindowType.Tool
    assert ctrl.window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    ctrl.on_state({"fecha": "2026-10-09", "estado": "hambriento", "recompensa_pendiente": False,
                   "mensaje": MENSAJES["hambriento"], "config": {"tamano": "grande", "siempre_visible": False,
                                                                 "reducir_animaciones": False, "sonidos": False,
                                                                 "posicion_x": -9999, "posicion_y": 50,
                                                                 "habilitada": True},
                   "mostrar_pedido": 0, "url_registro": "http://127.0.0.1:1/#/registro?fecha=2026-10-09"})
    assert ctrl.current_visual.modo == "hambriento"
    assert ctrl.window.width() == 236 and ctrl.window.height() == 80 + 206  # tamaño grande aplicado
    assert ctrl.window.x() >= 0                                # posición guardada fuera de pantalla: se corrige
    assert not ctrl.window.grab().isNull()
    ctrl.hide_pet()
    assert not ctrl.window.isVisible() and ctrl.backend.visible is False
    from PySide6.QtWidgets import QSystemTrayIcon
    ctrl.on_tray(QSystemTrayIcon.ActivationReason.Trigger)    # recuperar desde la bandeja
    assert ctrl.window.isVisible() and ctrl.backend.visible is True
    ctrl.refresh_menu()
    assert ctrl.a_posponer.isEnabled()
    ctrl.backend.stop()
    ctrl.window.close()


# --- dónde duerme Cora (cálculo puro, sin pantalla) ------------------------------------
def test_posicion_arriba_de_una_ventana_y_sobre_la_barra():
    from coranotes.mascota.lugares import Rect, perch_position, taskbar_position
    area = Rect(0, 0, 1920, 1040)
    ventana = Rect(300, 400, 1300, 900)
    contenido = (26, 214)                           # dónde está dibujada la gata dentro de su ventana
    x, y = perch_position(ventana, area, 236, 286, 230, prefer_x=5000, content=contenido)
    assert y + 230 == ventana.top                  # la línea de apoyo queda sobre el borde de la ventana
    assert x + 214 <= ventana.right - 150          # entera sobre la ventana y lejos de minimizar/maximizar/cerrar
    x, _ = perch_position(ventana, area, 236, 286, 230, prefer_x=-500, content=contenido)
    assert x + 26 >= ventana.left                   # no se sale por la izquierda
    assert perch_position(Rect(0, 0, 1920, 1040), area, 236, 286, 230) is None   # pegada arriba: no entra
    assert perch_position(Rect(300, 400, 400, 900), area, 236, 286, 230, content=contenido) is None  # muy angosta
    screen = Rect(0, 0, 1920, 1080)
    x, y = taskbar_position(area, screen, 236, 278, prefer_x=5000)
    assert y + 278 == 1040 and x == 1920 - 236     # sobre la barra de tareas y dentro de la pantalla
    x, y = taskbar_position(screen, screen, 236, 278)  # barra oculta: apoyo en el borde inferior
    assert y + 278 == 1080


def test_logica_dormir_fuera_de_casa():
    b = PetBrain()
    b.on_server_state({"fecha": "f", "estado": "descanso", "recompensa_pendiente": False}, 0.0)
    assert b.quiere_dormir(1.0)
    b.lugar_dormir = "panza"
    v = b.visual(1.0)
    assert v.pose == "panza" and v.zzz and v.ojos == "dormidos"
    b.pet(2.0)
    v = b.visual(2.3)
    assert v.pose == "panza" and v.ojos == "felices" and v.corazones > 0   # mimo sin despertarla de golpe
    b.on_server_state({"fecha": "f", "estado": "hambriento", "recompensa_pendiente": False, "mensaje": "x"}, 3.0)
    assert not b.quiere_dormir(3.0)                 # con hambre se despierta y pide comida


def test_sonidos_sintetizados(tmp_path):
    import wave
    from coranotes.mascota import sound
    for tipo in sound.TIPOS:
        sig = sound.build(tipo)
        assert 0.3 < len(sig) / sound.SR < 2.0 and 0.25 <= max(abs(v) for v in sig) <= 0.4
        path = sound.ensure_wav(tmp_path, tipo)
        with wave.open(str(path)) as w:
            assert w.getframerate() == sound.SR and w.getnframes() == len(sig)


def test_notificacion_de_respaldo_con_maullido_sin_doble_sonido(ctx, clock):
    from coranotes.notifier import build_toast_xml
    assert '<audio silent="true"/>' in build_toast_xml("t", "m", "http://x", None, silencioso=True)
    assert "<audio" not in build_toast_xml("t", "m", "http://x", None)
    reproducidos = []
    ctx.notices._play = lambda tipo: reproducidos.append(tipo)
    clock.set(local(18, 1))                          # Cora cerrada: avisa Windows
    ctx.scheduler.tick()
    enviados = [n for n in ctx.notices.notifier.enviados if n["titulo"] == "CoraNotes"]
    assert enviados and enviados[0]["silencioso"] is True   # la notificación va sin su sonido propio…
    ctx.settings.update("mascota", {"sonidos": False})
    clock.set(local(18, 1, HOY + timedelta(days=3)))
    ctx.scheduler.tick()
    enviados = [n for n in ctx.notices.notifier.enviados if n["titulo"] == "CoraNotes"]
    assert enviados[-1]["silencioso"] is False       # sin maullidos: sonido normal de Windows


def test_ventana_qt_duerme_en_la_barra_y_vuelve(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    from coranotes.config import AppConfig, Paths
    from coranotes.mascota.app import PetController
    app = QApplication.instance() or QApplication([])
    cfg = AppConfig(paths=Paths(tmp_path / "home"), port=1)
    cfg.paths.ensure()
    ctrl = PetController(app, cfg)
    ctrl.start()
    base = {"fecha": "2026-10-09", "recompensa_pendiente": False, "mostrar_pedido": 0,
            "config": {"tamano": "chico", "siempre_visible": True, "reducir_animaciones": True, "sonidos": False,
                       "posicion_x": None, "posicion_y": None, "habilitada": True, "lugar_dormir": "barra_tareas"}}
    ctrl.on_state({**base, "estado": "descanso", "mensaje": ""})
    assert ctrl.lugar_actual == "panza" and ctrl.current_visual.pose == "panza"
    screen = QGuiApplication.primaryScreen()
    suelo = ctrl.window.y() + ctrl.window.ground_px("panza")
    assert suelo == screen.availableGeometry().bottom() + 1   # apoyada en el borde inferior / barra de tareas
    ctrl.on_state({**base, "estado": "hambriento", "mensaje": MENSAJES["hambriento"]})
    assert ctrl.lugar_actual is None and ctrl.window.pos() == ctrl.home   # vuelve a su lugar a pedir comida
    assert ctrl.current_visual.pose == "sentada" and ctrl.current_visual.globo_clic
    ctrl.backend.stop()
    ctrl.window.close()


def test_menu_probar_sonidos(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from coranotes.config import AppConfig, Paths
    from coranotes.mascota.app import PetController
    app = QApplication.instance() or QApplication([])
    cfg = AppConfig(paths=Paths(tmp_path / "home"), port=1)
    cfg.paths.ensure()
    ctrl = PetController(app, cfg)
    tocados = []
    ctrl.sound.play = tocados.append
    opciones = next(a.menu() for a in ctrl.menu.actions() if a.text() == "Opciones")
    prueba = next(a.menu() for a in opciones.actions() if a.text() == "Probar sonidos")
    for accion in prueba.actions():
        accion.trigger()
    assert tocados == ["hambre", "comer", "ronroneo", "saludo"]
    ctrl.backend.stop()
    ctrl.window.close()
