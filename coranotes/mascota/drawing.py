"""Dibujo de Cora con QPainter (gráficos generados en código, sin imágenes externas)."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap

from .logic import Visual

BASE_W, BASE_H = 250.0, 262.0  # lienzo lógico; se escala según el tamaño elegido
CAT_DY = 22.0                  # el gato y el plato se dibujan debajo del globo
ESCALAS = {"chico": 0.72, "mediano": 1.0, "grande": 1.35}

PIEL = QColor("#F4A259")
PIEL_OSCURA = QColor("#B8682E")
PANZA = QColor("#FCE3C2")
OREJA = QColor("#F6B3B3")
OJO = QColor("#2B2B2B")
NARIZ = QColor("#E07A7A")
GRIS = QColor("#B9B9B9")
GRIS_OSCURO = QColor("#7D7D7D")

GLOBO_RECT = QRectF(8, 4, 234, 74)
PLATO_RECT = QRectF(150, 178 + CAT_DY, 82, 46)
GATO_RECT = QRectF(36, 70 + CAT_DY, 120, 160)


def _heart(p: QPainter, cx: float, cy: float, s: float, color: QColor) -> None:
    path = QPainterPath()
    path.moveTo(cx, cy + s * 0.35)
    path.cubicTo(cx - s, cy - s * 0.4, cx - s * 0.45, cy - s * 1.05, cx, cy - s * 0.45)
    path.cubicTo(cx + s * 0.45, cy - s * 1.05, cx + s, cy - s * 0.4, cx, cy + s * 0.35)
    p.fillPath(path, color)


def paint_pet(p: QPainter, v: Visual, t: float) -> None:
    """Dibuja en coordenadas lógicas (BASE_W x BASE_H). El llamador aplica la escala."""
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    piel = GRIS if v.gris else PIEL
    borde = GRIS_OSCURO if v.gris else PIEL_OSCURA
    contorno = QPen(borde, 2.2)
    p.save()
    p.translate(0, CAT_DY)

    # Plato (detrás del globo, delante del fondo)
    if v.plato != "ninguno":
        oscila = 2.0 * math.sin(t * 7.0) if v.modo == "hambriento" else 0.0
        bowl = QRectF(PLATO_RECT.x() + 6 + oscila, 194, 70, 26)  # coordenadas antes de CAT_DY
        if v.plato == "lleno" and v.comida > 0:
            alto = 16 * v.comida
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#8D5A3B"))
            for i, dx in enumerate((14, 28, 42, 56)):
                p.drawEllipse(QPointF(bowl.x() + dx, bowl.y() + 4 - alto * (0.5 + 0.15 * (i % 2))), 9, 3 + alto * 0.45)
        p.setPen(QPen(QColor("#3F6E9E"), 2))
        p.setBrush(QColor("#6FA8DC"))
        path = QPainterPath()
        path.moveTo(bowl.x(), bowl.y())
        path.lineTo(bowl.right(), bowl.y())
        path.lineTo(bowl.right() - 9, bowl.bottom())
        path.lineTo(bowl.x() + 9, bowl.bottom())
        path.closeSubpath()
        p.drawPath(path)
        p.setBrush(QColor("#9CC3E8"))
        p.drawEllipse(QRectF(bowl.x(), bowl.y() - 5, bowl.width(), 10))
        if v.plato == "vacio":
            p.setPen(QPen(QColor("#3F6E9E"), 1))
            p.setFont(QFont("Segoe UI", 7))
            p.drawText(QRectF(bowl.x(), bowl.bottom() + 1, bowl.width(), 14), Qt.AlignmentFlag.AlignCenter, "plato vacío")

    # Cola
    base = QPointF(128, 206)
    ang = -0.9 + v.cola
    tip = QPointF(base.x() + 52 * math.cos(ang), base.y() + 52 * math.sin(ang))
    ctrl = QPointF(base.x() + 42, base.y() + 8)
    cola = QPainterPath(base)
    cola.quadTo(ctrl, tip)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(borde, 15, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawPath(cola)
    p.setPen(QPen(piel, 11, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawPath(cola)

    # Cuerpo
    p.setPen(contorno)
    p.setBrush(piel)
    p.drawEllipse(QPointF(92, 182), 47, 40)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(PANZA if not v.gris else QColor("#E3E3E3"))
    p.drawEllipse(QPointF(92, 190), 26, 27)
    # Patitas
    p.setPen(contorno)
    p.setBrush(piel)
    for x in (72, 112):
        p.drawEllipse(QPointF(x, 219), 13, 8)

    # Cabeza (baja al comer)
    hy = 122 + v.cabeza_y
    hx = 92 + (4 if v.cabeza_y else 0)
    for sx in (-1, 1):  # orejas
        ear = QPainterPath()
        ear.moveTo(hx + sx * 34, hy - 12)
        ear.lineTo(hx + sx * 30, hy - 50)
        ear.lineTo(hx + sx * 8, hy - 32)
        ear.closeSubpath()
        p.setPen(contorno)
        p.setBrush(piel)
        p.drawPath(ear)
        inner = QPainterPath()
        inner.moveTo(hx + sx * 29, hy - 18)
        inner.lineTo(hx + sx * 27, hy - 41)
        inner.lineTo(hx + sx * 13, hy - 30)
        inner.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(OREJA if not v.gris else QColor("#D8D8D8"))
        p.drawPath(inner)
    p.setPen(contorno)
    p.setBrush(piel)
    p.drawEllipse(QPointF(hx, hy), 40, 35)
    # Rayitas
    p.setPen(QPen(borde, 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for dx in (-8, 0, 8):
        p.drawLine(QPointF(hx + dx, hy - 33), QPointF(hx + dx, hy - 24))

    # Ojos
    p.setPen(QPen(OJO, 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for ex in (hx - 15, hx + 15):
        ey = hy - 3
        if v.ojos == "abiertos":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(OJO)
            p.drawEllipse(QPointF(ex, ey), 5.5, 7)
            p.setBrush(QColor("white"))
            p.drawEllipse(QPointF(ex + 1.8, ey - 2.5), 1.8, 1.8)
            p.setPen(QPen(OJO, 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        elif v.ojos == "parpadeo":
            p.drawLine(QPointF(ex - 5, ey), QPointF(ex + 5, ey))
        elif v.ojos == "felices":
            arc = QPainterPath(QPointF(ex - 6, ey + 2))
            arc.quadTo(QPointF(ex, ey - 7), QPointF(ex + 6, ey + 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(arc)
        else:  # dormidos
            arc = QPainterPath(QPointF(ex - 6, ey - 1))
            arc.quadTo(QPointF(ex, ey + 5), QPointF(ex + 6, ey - 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(arc)
    # Nariz, boca y bigotes
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(NARIZ)
    nose = QPainterPath()
    nose.moveTo(hx - 4, hy + 7)
    nose.lineTo(hx + 4, hy + 7)
    nose.lineTo(hx, hy + 11)
    nose.closeSubpath()
    p.drawPath(nose)
    p.setPen(QPen(OJO, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    boca = QPainterPath(QPointF(hx - 7, hy + 13))
    boca.quadTo(QPointF(hx - 3, hy + 17), QPointF(hx, hy + 12))
    boca.quadTo(QPointF(hx + 3, hy + 17), QPointF(hx + 7, hy + 13))
    p.drawPath(boca)
    p.setPen(QPen(GRIS_OSCURO, 1.2))
    for sx in (-1, 1):
        for dy in (-2, 4):
            p.drawLine(QPointF(hx + sx * 16, hy + 9 + dy / 2), QPointF(hx + sx * 42, hy + 5 + dy))

    # Corazones (caricia) y zzz (descanso)
    if v.corazones > 0:
        k = v.corazones
        for i, dx in enumerate((-30, 0, 30)):
            alpha = int(255 * (1 - k))
            _heart(p, hx + dx, hy - 50 - 30 * k - i * 4, 7 + 2 * i, QColor(232, 84, 110, alpha))
    if v.zzz:
        p.setPen(QPen(QColor("#5B6B8C"), 1))
        for i, size in enumerate((9, 12, 15)):
            dy = 0 if v.cola == 0 else 3 * math.sin(t * 1.5 + i)
            p.setFont(QFont("Segoe UI", size, QFont.Weight.Bold))
            p.drawText(QPointF(hx + 34 + i * 10, hy - 40 - i * 12 + dy), "z")
    p.restore()
    hy += CAT_DY

    # Globo
    if v.globo:
        p.setFont(QFont("Segoe UI", 9))
        rect = QRectF(GLOBO_RECT)
        if not v.globo_clic:
            rect = QRectF(GLOBO_RECT.x(), GLOBO_RECT.y() + 18, GLOBO_RECT.width(), GLOBO_RECT.height() - 18)
        p.setPen(QPen(QColor("#4A4A4A"), 1.6))
        p.setBrush(QColor("#FFFFFF") if not v.desconectado else QColor("#F1F1F1"))
        p.drawRoundedRect(rect, 12, 12)
        punta = QPainterPath()
        punta.moveTo(hx - 8, rect.bottom() - 1)
        punta.lineTo(hx + 4, rect.bottom() + 14)
        punta.lineTo(hx + 10, rect.bottom() - 1)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(punta)
        p.setPen(QPen(QColor("#4A4A4A"), 1.6))
        p.drawLine(QPointF(hx - 8, rect.bottom()), QPointF(hx + 4, rect.bottom() + 14))
        p.drawLine(QPointF(hx + 4, rect.bottom() + 14), QPointF(hx + 10, rect.bottom()))
        p.setPen(QColor("#222222"))
        texto = rect.adjusted(10, 6, -10, -16 if v.globo_clic else -6)
        p.drawText(texto, int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap), v.globo)
        if v.globo_clic:
            p.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
            p.setPen(QColor("#1F5FBF"))
            p.drawText(QRectF(rect.x(), rect.bottom() - 17, rect.width(), 14), Qt.AlignmentFlag.AlignCenter,
                       "Tocá el globo o el plato para registrar")
    elif v.desconectado:
        p.setFont(QFont("Segoe UI", 7))
        p.setPen(QColor("#666666"))
        p.drawText(QRectF(0, 70, 200, 14), Qt.AlignmentFlag.AlignCenter, "sin conexión · reintentando")


def tray_pixmap(size: int = 64) -> QPixmap:
    """Icono de bandeja: carita de gato dibujada en código."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    s = size / 64.0
    p.scale(s, s)
    p.setPen(QPen(PIEL_OSCURA, 3))
    p.setBrush(QBrush(PIEL))
    for sx in (-1, 1):
        ear = QPainterPath()
        ear.moveTo(32 + sx * 26, 30)
        ear.lineTo(32 + sx * 24, 4)
        ear.lineTo(32 + sx * 6, 16)
        ear.closeSubpath()
        p.drawPath(ear)
    p.drawEllipse(QPointF(32, 36), 27, 24)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(OJO)
    p.drawEllipse(QPointF(22, 34), 4, 5)
    p.drawEllipse(QPointF(42, 34), 4, 5)
    p.setBrush(NARIZ)
    p.drawEllipse(QPointF(32, 43), 3, 2)
    p.end()
    return pm
