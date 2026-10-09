"""Lógica de Cora sin dependencias gráficas (se prueba sin Qt).

El backend dice el estado del día; acá se decide qué dibujar y cuándo reproducir la recompensa.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

EAT_SECONDS = 4.0
EAT_SECONDS_REDUCED = 1.5
PET_SECONDS = 1.6
THANKS_SECONDS = 6.0
SLEEP_AFTER_SECONDS = 300.0
CONNECTING_TEXT = "Conectando con CoraNotes…"


@dataclass
class Visual:
    modo: str              # hambriento | comiendo | alimentado | descanso | tranquilo | silenciado
    ojos: str              # abiertos | parpadeo | felices | dormidos
    plato: str             # vacio | lleno | ninguno
    comida: float = 0.0    # 0..1 cantidad de comida en el plato
    globo: str | None = None
    globo_clic: bool = False   # el globo abre el formulario
    cola: float = 0.0      # ángulo de la cola (radianes)
    cabeza_y: float = 0.0  # desplazamiento de la cabeza (comer)
    corazones: float = 0.0 # 0..1 progreso de la reacción a la caricia
    zzz: bool = False
    desconectado: bool = False
    gris: bool = False
    pose: str = "sentada"  # sentada | ventana (arriba de una ventana) | panza (sobre la barra de tareas)
    boca_abierta: bool = False
    inclinacion: float = 0.0  # grados de la cabeza
    reducido: bool = False


@dataclass
class PetBrain:
    reducido: bool = False
    lugar_dormir: str | None = None  # «ventana» o «panza» mientras duerme fuera de su lugar
    rng: random.Random = field(default_factory=random.Random)
    estado: dict | None = None
    conectado: bool = False
    recompensas_vistas: set = field(default_factory=set)
    comiendo_hasta: float = 0.0
    comiendo_desde: float = 0.0
    gracias_hasta: float = 0.0
    caricia_desde: float = -100.0
    ultima_interaccion: float = 0.0
    parpadeo_hasta: float = 0.0
    proximo_parpadeo: float = 2.0

    def on_server_state(self, st: dict, t: float) -> list[tuple]:
        """Devuelve eventos: ('ack', fecha), ('sonido', tipo), ('hambre',)."""
        eventos: list[tuple] = []
        previo = (self.estado or {}).get("estado") if self.conectado else None
        self.estado = st
        self.conectado = True
        fecha = st.get("fecha")
        if st.get("recompensa_pendiente") and fecha not in self.recompensas_vistas:
            # Una sola vez por día: se recuerda localmente y el backend lo persiste con el 'ack'.
            self.recompensas_vistas.add(fecha)
            dur = EAT_SECONDS_REDUCED if self.reducido else EAT_SECONDS
            self.comiendo_desde = t
            self.comiendo_hasta = t + dur
            self.gracias_hasta = t + dur + THANKS_SECONDS
            self.ultima_interaccion = t
            eventos += [("ack", fecha), ("sonido", "comer")]
        elif st.get("estado") == "alimentado" and fecha:
            self.recompensas_vistas.add(fecha)  # ya se mostró (por ejemplo, antes de reiniciar)
        if st.get("estado") == "hambriento" and previo != "hambriento":
            self.ultima_interaccion = t
            eventos.append(("sonido", "hambre"))
        return eventos

    def on_disconnected(self) -> None:
        self.conectado = False

    def pet(self, t: float) -> list[tuple]:
        self.caricia_desde = t
        self.ultima_interaccion = t
        return [("sonido", "ronroneo")]

    @property
    def modo(self) -> str:
        return (self.estado or {}).get("estado", "tranquilo")

    def quiere_dormir(self, t: float) -> bool:
        """¿Cora debería estar durmiendo? (sin contar la reacción momentánea a una caricia)"""
        modo = (self.estado or {}).get("estado", "tranquilo")
        if not self.conectado or t < self.comiendo_hasta or modo in ("hambriento", "comiendo"):
            return False
        if modo in ("descanso", "silenciado"):
            return True
        return modo in ("tranquilo", "alimentado") and t - self.ultima_interaccion > SLEEP_AFTER_SECONDS

    def is_animating(self, t: float) -> bool:
        return t < self.comiendo_hasta or t - self.caricia_desde < PET_SECONDS

    def visual(self, t: float) -> Visual:
        st = self.estado or {}
        modo = st.get("estado", "tranquilo")
        comiendo = t < self.comiendo_hasta
        acariciando = t - self.caricia_desde < PET_SECONDS
        if comiendo:
            modo = "comiendo"
        elif modo == "comiendo":  # el backend aún no registró el ack: ya se vio la animación
            modo = "alimentado"

        # Parpadeo ocasional (no en modo reducido).
        if not self.reducido and t >= self.proximo_parpadeo:
            self.parpadeo_hasta = t + 0.15
            self.proximo_parpadeo = t + self.rng.uniform(3.0, 6.5)
        parpadea = t < self.parpadeo_hasta

        dormido = (modo in ("descanso", "silenciado")
                   or (modo in ("tranquilo", "alimentado") and t - self.ultima_interaccion > SLEEP_AFTER_SECONDS))
        if acariciando or modo == "hambriento":
            dormido = False

        v = Visual(modo=modo, ojos="abiertos", plato="ninguno", reducido=self.reducido)
        if not self.reducido:
            v.inclinacion = 2.5 * math.sin(t * 0.6)
        if dormido:
            v.ojos, v.zzz = "dormidos", True
        elif acariciando or (modo == "alimentado" and t < self.gracias_hasta):
            v.ojos = "felices"
        elif parpadea:
            v.ojos = "parpadeo"

        if modo == "hambriento":
            v.plato = "vacio"
            v.globo = st.get("mensaje") or "¡Hora de mi comida!"
            v.globo_clic = True
            v.inclinacion = -5 + (2 * math.sin(t * 2.0) if not self.reducido else 0)
            v.boca_abierta = (t % 1.8) < 0.45 and not self.reducido  # maullido
        elif modo == "comiendo":
            dur = max(0.01, self.comiendo_hasta - self.comiendo_desde)
            avance = min(1.0, max(0.0, (t - self.comiendo_desde) / dur))
            v.plato, v.comida = "lleno", 1.0 - 0.75 * avance
            v.ojos = "felices"
            v.globo = "¡Ñam! Gracias por contarme tu día."
            v.inclinacion = 12
            v.cabeza_y = 8.0 + (5.0 * abs(math.sin(t * 9.0)) if not self.reducido else 0)
        elif modo == "alimentado" and t < self.gracias_hasta:
            v.plato, v.comida = "lleno", 0.25
            v.globo = st.get("mensaje") or "¡Gracias por la comida!"

        if not self.reducido and not dormido:
            velocidad = 6.0 if acariciando or modo == "hambriento" else 2.2
            v.cola = 0.35 * math.sin(t * velocidad)
        elif not self.reducido:
            v.cola = 0.08 * math.sin(t * 0.8)
        if acariciando:
            v.corazones = min(1.0, (t - self.caricia_desde) / PET_SECONDS)
            v.inclinacion = 8 * math.sin(t * 6) if not self.reducido else 6
        if dormido:
            v.inclinacion = 6
        if self.lugar_dormir in ("ventana", "panza") and self.conectado:
            v.pose = self.lugar_dormir  # acostada arriba de una ventana o sobre la barra de tareas
            v.zzz = not acariciando
            v.ojos = "felices" if acariciando else "dormidos"
        if not self.conectado:
            v.desconectado = True
            v.gris = self.estado is None
            if self.estado is None:
                v.globo, v.globo_clic, v.plato = CONNECTING_TEXT, False, "ninguno"
        return v


def clamp_to_area(x: int, y: int, w: int, h: int, area: tuple[int, int, int, int]) -> tuple[int, int]:
    """Mantiene la ventana (x, y, w, h) completamente dentro de area=(ax, ay, aw, ah)."""
    ax, ay, aw, ah = area
    nx = min(max(x, ax), ax + max(0, aw - w))
    ny = min(max(y, ay), ay + max(0, ah - h))
    return nx, ny
