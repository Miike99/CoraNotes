"""Estado de Cora (mascota de escritorio), calculado desde el registro real del día.

- Hambre: pasó un horario de recordatorio de hoy y no hay registro (ni «sin actividad»).
- Comida: hay al menos una actividad válida con fecha de hoy (zona horaria configurada).
- La recompensa (animación de comer) se guarda en `mascota_dias`: una vez por día, aunque se
  agreguen más actividades, se edite, se importen duplicados o se reinicie la app.
"""
from __future__ import annotations

import threading
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from .calendar_logic import is_paused, reminder_occurrences
from .db import get_meta, set_meta
from .records import Conflict
from .util import utc_iso

PRESENCIA_TTL = timedelta(seconds=45)
MENSAJES = {
    "hambriento": "¡Hora de mi comida! ¿Qué hiciste hoy? Contame tus avances, problemas y soluciones",
    "comiendo": "¡Ñam! Gracias por contarme tu día.",
    "alimentado": "¡Gracias por la comida! Hoy ya está registrado.",
    "descanso": "Hoy descansamos.",
    "silenciado": "Recordatorios en silencio hasta mañana.",
    "tranquilo": "",
}
SIN_HAMBRE = ("pospuesto", "descartado", "silenciado", "registrado")


class PetService:
    def __init__(self, db, clock, settings, base_url: str):
        self.db = db
        self.clock = clock
        self.settings = settings
        self.base_url = base_url
        self._lock = threading.Lock()
        self._presence: dict = {"ultimo": None, "visible": False}
        self._mostrar_pedido = 0  # contador: el proceso de Cora se muestra al verlo cambiar

    # ---------- presencia del proceso de escritorio ----------
    def heartbeat(self, visible: bool) -> None:
        with self._lock:
            self._presence = {"ultimo": self.clock.now(), "visible": bool(visible)}

    def presence(self) -> dict:
        with self._lock:
            ultimo, visible = self._presence["ultimo"], self._presence["visible"]
        conectada = ultimo is not None and self.clock.now() - ultimo <= PRESENCIA_TTL
        return {"conectada": conectada, "visible": conectada and visible,
                "ultimo_utc": utc_iso(ultimo) if ultimo else None}

    def is_reminder_channel(self) -> bool:
        """Cora avisa si está activada, conectado y visible (no oculto en la bandeja)."""
        return self.settings.get("mascota").habilitada and self.presence()["visible"]

    def request_show(self) -> None:
        with self._lock:
            self._mostrar_pedido += 1

    # ---------- fechas ----------
    def _tz(self) -> ZoneInfo:
        return ZoneInfo(self.settings.get("recordatorio").zona)

    def today(self) -> date:
        return self.clock.now().astimezone(self._tz()).date()

    def silenced_today(self, conn) -> bool:
        return get_meta(conn, "mascota_silencio_fecha") == self.today().isoformat()

    def set_silence(self, activar: bool) -> None:
        with self.db.tx() as c:
            set_meta(c, "mascota_silencio_fecha", self.today().isoformat() if activar else "")
            if activar:  # el recordatorio activo de hoy deja de pedir atención
                c.execute("UPDATE ejecuciones SET estado='silenciado', pospuesto_hasta_utc=NULL, actualizado_utc=? "
                          "WHERE fecha=? AND tipo IN ('recordatorio','puntual') AND estado IN ('avisado','pospuesto')",
                          (utc_iso(self.clock.now()), self.today().isoformat()))

    # ---------- estado ----------
    def _passed_occurrences(self, today: date) -> list:
        rcfg = self.settings.get("recordatorio")
        now = self.clock.now()
        return [o for o in reminder_occurrences(rcfg, today) if o.utc <= now]

    def state(self) -> dict:
        today = self.today()
        f = today.isoformat()
        rcfg = self.settings.get("recordatorio")
        mcfg = self.settings.get("mascota")
        passed = self._passed_occurrences(today)
        with self.db.tx() as c:
            validos = c.execute("SELECT count(*) FROM registros WHERE fecha=? AND estado='guardado' AND archivado=0 "
                                "AND trim(actividad) <> ''", (f,)).fetchone()[0]
            declarado = c.execute("SELECT 1 FROM dias_sin_actividad WHERE fecha=?", (f,)).fetchone() is not None
            recompensa = c.execute("SELECT recompensa FROM mascota_dias WHERE fecha=?", (f,)).fetchone()
            if validos and recompensa is None:
                c.execute("INSERT OR IGNORE INTO mascota_dias(fecha, recompensa, creado_utc) VALUES (?,?,?)",
                          (f, "pendiente", utc_iso(self.clock.now())))
                recompensa = ("pendiente",)
            silenciado = self.silenced_today(c)
            filas = {r["clave"]: r for r in c.execute(
                "SELECT clave, estado, pospuesto_hasta_utc FROM ejecuciones WHERE fecha=? AND tipo IN "
                "('recordatorio','puntual')", (f,)).fetchall()}
        pendientes = [o for o in passed if filas.get(o.clave) is None or filas[o.clave]["estado"] not in SIN_HAMBRE]
        pospuesto = [filas[o.clave]["pospuesto_hasta_utc"] for o in passed
                     if filas.get(o.clave) is not None and filas[o.clave]["estado"] == "pospuesto"]
        dia_con_recordatorio = bool(reminder_occurrences(rcfg, today))
        recompensa_pendiente = bool(validos) and recompensa is not None and recompensa[0] == "pendiente"
        if validos:
            estado = "comiendo" if recompensa_pendiente else "alimentado"
        elif declarado:
            estado = "descanso"
        elif silenciado:
            estado = "silenciado"
        elif pendientes:
            estado = "hambriento"
        elif not dia_con_recordatorio or is_paused(rcfg, today):
            estado = "descanso"  # día excluido, no configurado o en pausa: sin hambre
        else:
            estado = "tranquilo"
        with self._lock:
            mostrar = self._mostrar_pedido
        return {
            "fecha": f,
            "estado": estado,
            "mensaje": MENSAJES[estado],
            "recompensa_pendiente": recompensa_pendiente,
            "pospuesto_hasta_utc": max(pospuesto) if pospuesto else None,
            "url_registro": f"{self.base_url}/#/registro?fecha={f}",
            "url_app": f"{self.base_url}/#/inicio",
            "config": mcfg.model_dump(mode="json"),
            "mostrar_pedido": mostrar,
            "presencia": self.presence(),
        }

    def ack_reward(self, fecha: str) -> bool:
        with self.db.tx() as c:
            cur = c.execute("UPDATE mascota_dias SET recompensa='mostrada', mostrada_utc=? WHERE fecha=? "
                            "AND recompensa='pendiente'", (utc_iso(self.clock.now()), fecha))
            return cur.rowcount > 0

    def snooze(self) -> dict:
        """Pospone el pedido de comida de hoy (mismo efecto que posponer el recordatorio)."""
        today = self.today()
        f = today.isoformat()
        minutos = self.settings.get("recordatorio").posponer_minutos
        now = self.clock.now()
        hasta = now + timedelta(minutes=minutos)
        cambiados = 0
        with self.db.tx() as c:
            for occ in self._passed_occurrences(today):
                row = c.execute("SELECT estado FROM ejecuciones WHERE clave=?", (occ.clave,)).fetchone()
                if row is None:
                    c.execute("INSERT INTO ejecuciones(clave, tipo, fecha, programado_utc, estado, avisos, "
                              "pospuesto_hasta_utc, creado_utc, actualizado_utc) VALUES (?,?,?,?,?,0,?,?,?)",
                              (occ.clave, occ.tipo, f, utc_iso(occ.utc), "pospuesto", utc_iso(hasta),
                               utc_iso(now), utc_iso(now)))
                    cambiados += 1
                elif row["estado"] in ("avisado", "perdido", "pospuesto"):
                    c.execute("UPDATE ejecuciones SET estado='pospuesto', pospuesto_hasta_utc=?, actualizado_utc=? "
                              "WHERE clave=?", (utc_iso(hasta), utc_iso(now), occ.clave))
                    cambiados += 1
        if not cambiados:
            raise Conflict("No hay un recordatorio activo para posponer")
        return {"pospuesto_hasta_utc": utc_iso(hasta), "minutos": minutos}

    def update_config(self, cambios: dict) -> dict:
        permitidos = {"tamano", "siempre_visible", "sonidos", "reducir_animaciones", "posicion_x", "posicion_y",
                      "habilitada", "notificacion_respaldo", "lugar_dormir"}
        cambios = {k: v for k, v in cambios.items() if k in permitidos}
        return self.settings.update("mascota", cambios).model_dump(mode="json")

