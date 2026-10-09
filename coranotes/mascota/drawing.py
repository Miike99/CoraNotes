"""Cora en 2D, dibujada por código con QPainter (estilo ilustración: contorno marrón suave,
pelaje naranja atigrado con degradés, mechones esponjosos, ojos verdes grandes y collar con pescadito).

Coordenadas: el gato se dibuja en un lienzo lógico de GATO_W x GATO_H que se escala según el tamaño
elegido; el globo de diálogo se dibuja aparte, en píxeles, para que el texto siempre se lea bien.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient)

from .logic import Visual

# ---------------------------------------------------------------- medidas
GATO_W, GATO_H = 236.0, 206.0          # lienzo lógico del gato (incluye el plato)
GLOBO_W, GLOBO_H = 236, 80             # globo en píxeles (no se escala)
ESCALAS = {"chico": 0.6, "mediano": 0.8, "grande": 1.0}
SUELO = {"sentada": 200.0, "ventana": 150.0, "panza": 198.0}   # línea de apoyo de cada pose (lógica)
GATO_RECT = QRectF(28, 16, 150, 186)   # zona para acariciar (lógica, pose sentada)
PLATO_RECT = QRectF(166, 160, 70, 46)  # zona del plato (lógica)

# ---------------------------------------------------------------- paleta (de la ilustración de referencia)
LINEA = QColor("#7E4524")
PELO = QColor("#F3A55B")
PELO_CLARO = QColor("#F8BF7C")
PELO_OSCURO = QColor("#DD8240")
RAYA = QColor(200, 104, 44, 200)
BLANCO = QColor("#FFF8EE")
BLANCO_SOMBRA = QColor("#F0DCC6")
ROSA = QColor("#F2A2A3")
NARIZ = QColor("#E9878F")
IRIS_CLARO = QColor("#A9D66B")
IRIS = QColor("#6EAE45")
IRIS_OSCURO = QColor("#3F7A2A")
PUPILA = QColor("#1E140F")
BORDE_OJO = QColor("#3A2215")
COLLAR = QColor("#71C7C4")
COLLAR_OSCURO = QColor("#4C9F9C")
ORO = QColor("#F2C14E")
ORO_OSCURO = QColor("#C8922A")
CERAMICA = QColor("#8DBDE6")
CERAMICA_OSCURA = QColor("#5E8FC2")
CROQUETA = QColor("#9B5A31")
GRIS = QColor("#BDBDBD")
GRIS_OSCURO = QColor("#8C8C8C")


def _pen(color=LINEA, w=2.0):
    p = QPen(color, w)
    p.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return p


class Paleta:
    """Colores efectivos: en gris cuando la mascota espera la conexión."""

    def __init__(self, gris: bool):
        self.gris = gris

    def c(self, color: QColor) -> QColor:
        if not self.gris:
            return color
        v = int(0.3 * color.red() + 0.59 * color.green() + 0.11 * color.blue())
        return QColor(v, v, v, color.alpha())


def fluffy(cx, cy, rx, ry, tufts=(), n=40, base_bump=0.0) -> QPainterPath:
    """Elipse «peluda»: en los rangos de ángulo de `tufts` [(desde°, hasta°, profundidad)] salen mechones."""
    path = QPainterPath()

    def pt(a, f=1.0):
        return QPointF(cx + rx * f * math.cos(a), cy + ry * f * math.sin(a))

    def depth(deg):
        deg %= 360
        for a, b, d in tufts:
            a %= 360
            b %= 360
            if (a <= b and a <= deg <= b) or (a > b and (deg >= a or deg <= b)):
                return d
        return base_bump

    path.moveTo(pt(0))
    for k in range(n):
        a0 = 2 * math.pi * k / n
        a1 = 2 * math.pi * (k + 1) / n
        am = (a0 + a1) / 2
        d = depth(math.degrees(am))
        if d > base_bump:
            d *= 1.0 if k % 2 == 0 else 0.35  # mechones de distinto largo
            path.quadTo(pt(am, 1 + d), pt(a1))
        else:  # tramo liso: curva que sigue la elipse
            path.quadTo(pt(am, 1 / math.cos(math.pi / n) + base_bump), pt(a1))
    path.closeSubpath()
    return path


def tube(points, widths) -> QPainterPath:
    """Tubo suave (cola, patas) a partir de una línea central y su ancho en cada punto."""
    left, right = [], []
    for i, (x, y) in enumerate(points):
        x0, y0 = points[max(i - 1, 0)]
        x1, y1 = points[min(i + 1, len(points) - 1)]
        dx, dy = x1 - x0, y1 - y0
        ln = math.hypot(dx, dy) or 1
        nx, ny = -dy / ln, dx / ln
        w = widths[i] / 2
        left.append(QPointF(x + nx * w, y + ny * w))
        right.append(QPointF(x - nx * w, y - ny * w))
    path = QPainterPath(left[0])
    for p in left[1:]:
        path.lineTo(p)
    # punta redondeada: se prolonga en la dirección final
    (xa, ya), (xb, yb) = points[-2], points[-1]
    ln = math.hypot(xb - xa, yb - ya) or 1
    reach = widths[-1] * 0.9
    path.quadTo(QPointF(xb + (xb - xa) / ln * reach, yb + (yb - ya) / ln * reach), right[-1])
    for p in reversed(right[:-1]):
        path.lineTo(p)
    path.closeSubpath()
    return path


def bezier(p0, p1, p2, p3, n=18):
    out = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        out.append((u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                    u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))
    return out


def fur_brush(pal: Paleta, x0, y0, x1, y1):
    g = QLinearGradient(x0, y0, x1, y1)
    g.setColorAt(0.0, pal.c(PELO_CLARO))
    g.setColorAt(0.55, pal.c(PELO))
    g.setColorAt(1.0, pal.c(PELO_OSCURO))
    return QBrush(g)


def white_brush(pal: Paleta, cx, cy, r):
    g = QRadialGradient(cx - r * 0.3, cy - r * 0.4, r * 1.4)
    g.setColorAt(0.0, pal.c(BLANCO))
    g.setColorAt(0.7, pal.c(BLANCO))
    g.setColorAt(1.0, pal.c(BLANCO_SOMBRA))
    return QBrush(g)


def fill_outline(p: QPainter, path: QPainterPath, brush, pal: Paleta, w=2.0, outline=True):
    p.setPen(_pen(pal.c(LINEA), w) if outline else Qt.PenStyle.NoPen)
    p.setBrush(brush)
    p.drawPath(path)


def stripe(p: QPainter, pal: Paleta, pts, w=4.0, color=RAYA):
    path = QPainterPath(QPointF(*pts[0]))
    if len(pts) == 3:
        path.quadTo(QPointF(*pts[1]), QPointF(*pts[2]))
    else:
        path.lineTo(QPointF(*pts[1]))
    p.setPen(_pen(pal.c(color), w))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)


# ---------------------------------------------------------------- partes
def draw_tail(p, pal, pts, w0=22.0, w1=15.0, tip=0.22):
    n = len(pts)
    widths = [w0 + (w1 - w0) * i / (n - 1) for i in range(n)]
    path = tube(pts, widths)
    fill_outline(p, path, fur_brush(pal, pts[0][0], pts[0][1], pts[-1][0], pts[-1][1]), pal)
    k = max(2, int(n * (1 - tip)))
    tip_path = tube(pts[k - 1:], widths[k - 1:])
    p.save()
    p.setClipPath(path)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(white_brush(pal, *pts[-1], 14))
    p.drawPath(tip_path)
    for i in range(2, k - 2, 4):  # rayas de la cola
        x, y = pts[i]
        x2, y2 = pts[i + 1]
        dx, dy = x2 - x, y2 - y
        ln = math.hypot(dx, dy) or 1
        nx, ny = -dy / ln * widths[i] / 2, dx / ln * widths[i] / 2
        stripe(p, pal, [(x + nx, y + ny), (x - nx * 0.2 + dx, y - ny * 0.2 + dy), (x - nx, y - ny)], 3.5)
    p.restore()
    p.setPen(_pen(pal.c(LINEA)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)


def draw_ear(p, pal, base_l, base_r, apex, twitch=0.0, side=1):
    p.save()
    cx, cy = (base_l[0] + base_r[0]) / 2, (base_l[1] + base_r[1]) / 2
    p.translate(cx, cy)
    p.rotate(twitch * side)
    p.translate(-cx, -cy)
    ear = QPainterPath(QPointF(*base_l))
    ear.quadTo(QPointF(base_l[0] + (apex[0] - base_l[0]) * 0.3 - 4 * side, apex[1] + 12), QPointF(*apex))
    ear.quadTo(QPointF(apex[0] + (base_r[0] - apex[0]) * 0.6, apex[1] + 8), QPointF(*base_r))
    ear.closeSubpath()
    fill_outline(p, ear, fur_brush(pal, *apex, *base_r), pal)
    # interior rosado con mechones blancos
    ix = [base_l[0] + (apex[0] - base_l[0]) * 0.18 + (base_r[0] - base_l[0]) * 0.18, base_l[1] - 3]
    jx = [base_r[0] - (base_r[0] - base_l[0]) * 0.22, base_r[1] - 2]
    ap = [apex[0] + (base_l[0] + base_r[0] - 2 * apex[0]) * 0.18, apex[1] + 9]
    inner = QPainterPath(QPointF(*ix))
    inner.quadTo(QPointF((ix[0] + ap[0]) / 2, (ix[1] + ap[1]) / 2 + 2), QPointF(*ap))
    inner.quadTo(QPointF((jx[0] + ap[0]) / 2, (jx[1] + ap[1]) / 2 + 2), QPointF(*jx))
    inner.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(pal.c(ROSA))
    p.drawPath(inner)
    p.setPen(_pen(pal.c(BLANCO), 1.6))
    for k in range(3):
        sx = ix[0] + (jx[0] - ix[0]) * (0.25 + 0.25 * k)
        p.drawLine(QPointF(sx, ix[1] + 1), QPointF(sx + (ap[0] - sx) * 0.45, ix[1] - (ix[1] - ap[1]) * 0.5))
    p.restore()


def draw_eye(p, pal, cx, cy, kind, blink=0.0):
    """kind: abiertos | felices | dormidos. blink 0..1 cierra el párpado."""
    if kind == "felices":
        path = QPainterPath(QPointF(cx - 11, cy + 4))
        path.quadTo(QPointF(cx, cy - 10), QPointF(cx + 11, cy + 4))
        p.setPen(_pen(pal.c(BORDE_OJO), 3.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        return
    if kind == "dormidos" or blink >= 0.95:
        path = QPainterPath(QPointF(cx - 12, cy))
        path.quadTo(QPointF(cx, cy + 9), QPointF(cx + 12, cy))
        p.setPen(_pen(pal.c(BORDE_OJO), 3.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        return
    outer = QRectF(cx - 15, cy - 16.5, 30, 33)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(pal.c(BORDE_OJO))
    p.drawEllipse(outer)
    p.setBrush(pal.c(QColor("#E3EFA8")))
    p.drawEllipse(outer.adjusted(1.8, 1.8, -1.8, -1.8))
    g = QRadialGradient(cx, cy + 6, 15)
    g.setColorAt(0.0, pal.c(IRIS_CLARO))
    g.setColorAt(0.55, pal.c(IRIS))
    g.setColorAt(1.0, pal.c(IRIS_OSCURO))
    p.setBrush(QBrush(g))
    p.drawEllipse(outer.adjusted(3.2, 3.2, -3.2, -3.2))
    p.setBrush(pal.c(PUPILA))
    p.drawEllipse(QRectF(cx - 8.5, cy - 11, 17, 20))
    p.setBrush(QColor(255, 255, 255, 245))
    p.drawEllipse(QPointF(cx + 4.5, cy - 5.5), 4.6, 4.8)
    p.drawEllipse(QPointF(cx - 4.2, cy + 5.2), 2.0, 2.0)
    if blink > 0.02:  # párpado que baja
        p.save()
        clip = QPainterPath()
        clip.addEllipse(outer.adjusted(-0.5, -0.5, 0.5, 0.5))
        p.setClipPath(clip)
        h = outer.height() * blink
        p.setBrush(fur_brush(pal, cx, cy - 16, cx, cy + 16))
        p.drawRect(QRectF(outer.left() - 1, outer.top() - 1, outer.width() + 2, h + 1))
        p.restore()
        p.setPen(_pen(pal.c(BORDE_OJO), 2.4))
        y = outer.top() + h
        p.drawLine(QPointF(cx - 13 * math.sqrt(max(0.0, 1 - ((y - cy) / 16.5) ** 2)), y),
                   QPointF(cx + 13 * math.sqrt(max(0.0, 1 - ((y - cy) / 16.5) ** 2)), y))


def draw_head(p, pal, v: Visual, t: float, cx=96.0, cy=70.0):
    twitch = 9 * max(0.0, math.sin(t * 1.3 + 1.0)) ** 30 if not v.reducido else 0.0
    draw_ear(p, pal, (cx - 54, cy - 8), (cx - 14, cy - 37), (cx - 52, cy - 62), twitch, side=-1)
    draw_ear(p, pal, (cx + 54, cy - 8), (cx + 14, cy - 37), (cx + 52, cy - 62), twitch * 0.6, side=1)
    head = fluffy(cx, cy, 61, 47, tufts=((140, 212, 0.22), (-32, 40, 0.22)), n=44)
    fill_outline(p, head, fur_brush(pal, cx - 50, cy - 50, cx + 40, cy + 50), pal)
    p.save()
    p.setClipPath(head)
    # rayas de la frente y de las mejillas
    for dx, top, bot in ((-13, cy - 44, cy - 28), (0, cy - 47, cy - 26), (13, cy - 44, cy - 28)):
        stripe(p, pal, [(cx + dx * 1.05, top), (cx + dx * 0.9, (top + bot) / 2), (cx + dx * 0.8, bot)], 4.2)
    for sx in (-1, 1):
        for k, dy in enumerate((0, 8)):
            stripe(p, pal, [(cx + sx * 62, cy + dy), (cx + sx * 55, cy + dy + 1), (cx + sx * 49, cy + dy + 3)], 3.0)
    # cachetes blancos y hocico
    p.setPen(Qt.PenStyle.NoPen)
    for sx in (-1, 1):
        p.setBrush(white_brush(pal, cx + sx * 30, cy + 26, 22))
        p.drawEllipse(QPointF(cx + sx * 28, cy + 27), 24, 16)
    p.setBrush(white_brush(pal, cx, cy + 22, 20))
    p.drawEllipse(QPointF(cx - 10, cy + 20), 14, 12)
    p.drawEllipse(QPointF(cx + 10, cy + 20), 14, 12)
    p.drawEllipse(QPointF(cx, cy + 30), 13, 8)
    p.restore()
    # rubor
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(242, 140, 140, 70 if not pal.gris else 30))
    p.drawEllipse(QPointF(cx - 36, cy + 14), 9, 5)
    p.drawEllipse(QPointF(cx + 36, cy + 14), 9, 5)
    # ojos
    blink = 1.0 if v.ojos == "parpadeo" else 0.0
    kind = {"felices": "felices", "dormidos": "dormidos"}.get(v.ojos, "abiertos")
    draw_eye(p, pal, cx - 21, cy - 2, kind, blink)
    draw_eye(p, pal, cx + 21, cy - 2, kind, blink)
    # nariz
    nose = QPainterPath(QPointF(cx - 5.5, cy + 12))
    nose.quadTo(QPointF(cx, cy + 9.5), QPointF(cx + 5.5, cy + 12))
    nose.quadTo(QPointF(cx + 3, cy + 17.5), QPointF(cx, cy + 18))
    nose.quadTo(QPointF(cx - 3, cy + 17.5), QPointF(cx - 5.5, cy + 12))
    p.setPen(_pen(pal.c(LINEA), 1.2))
    p.setBrush(pal.c(NARIZ))
    p.drawPath(nose)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 170))
    p.drawEllipse(QPointF(cx - 1.5, cy + 12.2), 1.6, 0.9)
    # boca
    if v.boca_abierta:
        mouth = QPainterPath(QPointF(cx - 7, cy + 22))
        mouth.quadTo(QPointF(cx, cy + 20), QPointF(cx + 7, cy + 22))
        mouth.quadTo(QPointF(cx + 6, cy + 35), QPointF(cx, cy + 35))
        mouth.quadTo(QPointF(cx - 6, cy + 35), QPointF(cx - 7, cy + 22))
        p.setPen(_pen(pal.c(LINEA), 1.8))
        p.setBrush(pal.c(QColor("#7A2A2A")))
        p.drawPath(mouth)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(pal.c(ROSA))
        p.drawEllipse(QPointF(cx, cy + 31.5), 4.5, 3)
    else:
        m = QPainterPath(QPointF(cx, cy + 18))
        m.lineTo(QPointF(cx, cy + 22))
        m.quadTo(QPointF(cx - 4, cy + 27), QPointF(cx - 10, cy + 23))
        m.moveTo(QPointF(cx, cy + 22))
        m.quadTo(QPointF(cx + 4, cy + 27), QPointF(cx + 10, cy + 23))
        p.setPen(_pen(pal.c(LINEA), 1.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(m)
    # bigotes (blancos, con una sombra suave para verse sobre fondos claros)
    for sx in (-1, 1):
        for k, (dy, ey) in enumerate(((17, 10), (23, 24))):
            w = QPainterPath(QPointF(cx + sx * 28, cy + dy))
            w.quadTo(QPointF(cx + sx * 48, cy + dy - 3 + k), QPointF(cx + sx * 66, cy + ey - 6 + k * 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(_pen(QColor(120, 70, 40, 60), 2.2))
            p.drawPath(w)
            p.setPen(_pen(QColor(255, 253, 248, 235), 1.2))
            p.drawPath(w)


def draw_collar(p, pal, cx, cy, ancho=40):
    band = QPainterPath(QPointF(cx - ancho, cy - 6))
    band.quadTo(QPointF(cx, cy + 9), QPointF(cx + ancho, cy - 6))
    band.lineTo(QPointF(cx + ancho - 1, cy + 1))
    band.quadTo(QPointF(cx, cy + 16), QPointF(cx - ancho + 1, cy + 1))
    band.closeSubpath()
    g = QLinearGradient(cx, cy - 6, cx, cy + 16)
    g.setColorAt(0, pal.c(COLLAR))
    g.setColorAt(1, pal.c(COLLAR_OSCURO))
    fill_outline(p, band, QBrush(g), pal, 1.6)
    # pescadito dorado
    fy = cy + 19
    p.setPen(_pen(pal.c(ORO_OSCURO), 1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(cx, cy + 10.5), 2.4, 2.4)
    fish = QPainterPath()
    fish.addEllipse(QPointF(cx - 1.5, fy + 2), 8.5, 5)
    tail = QPainterPath(QPointF(cx + 6, fy + 2))
    tail.lineTo(QPointF(cx + 12, fy - 3))
    tail.lineTo(QPointF(cx + 12, fy + 7))
    tail.closeSubpath()
    g2 = QLinearGradient(cx - 8, fy - 3, cx + 8, fy + 7)
    g2.setColorAt(0, pal.c(QColor("#FFE08A")))
    g2.setColorAt(1, pal.c(ORO))
    fill_outline(p, fish.united(tail), QBrush(g2), pal, 1.2)
    p.setPen(_pen(pal.c(ORO_OSCURO), 1.0))
    p.drawLine(QPointF(cx + 1, fy - 1), QPointF(cx + 1, fy + 5))
    p.drawLine(QPointF(cx + 3.5, fy - 1.5), QPointF(cx + 3.5, fy + 5.5))
    p.setBrush(pal.c(PUPILA))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(cx - 6, fy + 1), 1.0, 1.0)


def draw_paw(p, pal, cx, cy, rx=13, ry=8, toes=True):
    paw = QPainterPath()
    paw.addEllipse(QPointF(cx, cy), rx, ry)
    fill_outline(p, paw, white_brush(pal, cx, cy, rx), pal)
    if toes:
        p.setPen(_pen(pal.c(LINEA), 1.3))
        for dx in (-rx * 0.33, rx * 0.33):
            p.drawLine(QPointF(cx + dx, cy + ry * 0.2), QPointF(cx + dx, cy + ry * 0.85))


def draw_bowl(p, pal, comida: float, wiggle: float = 0.0):
    cx, top = 201 + wiggle, 180.0
    body = QPainterPath(QPointF(cx - 31, top))
    body.quadTo(QPointF(cx - 29, top + 22), QPointF(cx - 18, top + 24))
    body.lineTo(QPointF(cx + 18, top + 24))
    body.quadTo(QPointF(cx + 29, top + 22), QPointF(cx + 31, top))
    body.closeSubpath()
    g = QLinearGradient(cx - 30, top, cx + 30, top + 24)
    g.setColorAt(0, pal.c(CERAMICA))
    g.setColorAt(1, pal.c(CERAMICA_OSCURA))
    fill_outline(p, body, QBrush(g), pal, 1.8)
    p.setPen(_pen(pal.c(BLANCO), 2.2))
    p.drawLine(QPointF(cx - 22, top + 12), QPointF(cx + 22, top + 12))
    rim = QPainterPath()
    rim.addEllipse(QPointF(cx, top), 31, 7.5)
    fill_outline(p, rim, QBrush(pal.c(QColor("#F7FBFF"))), pal, 1.8)
    inner = QPainterPath()
    inner.addEllipse(QPointF(cx, top + 0.5), 26, 5.2)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(pal.c(QColor("#C9DDEF")))
    p.drawPath(inner)
    if comida > 0:
        p.save()
        clip = QPainterPath()
        clip.addRect(QRectF(cx - 40, top - 30, 80, 30.5))
        clip = clip.united(inner)
        p.setClipPath(clip)
        h = 3 + 9 * comida
        for i, (dx, dy) in enumerate(((-14, 1), (-5, -1), (5, 0), (14, 1), (-9, -3), (0, -4), (9, -3), (-2, -6))):
            if i >= 3 + int(comida * 6):
                break
            p.setPen(_pen(pal.c(QColor("#6E3A1D")), 1.0))
            p.setBrush(pal.c(CROQUETA))
            p.drawEllipse(QPointF(cx + dx, top + dy - h * 0.45), 5.2, 3.6)
        p.restore()


# ---------------------------------------------------------------- poses
def pose_sentada(p, pal, v: Visual, t: float):
    breath = 1 + (0.012 * math.sin(t * 2.2) if not v.reducido else 0)
    sway = v.cola
    # cola (detrás)
    tip_x = 196 + 18 * math.sin(sway)
    tip_y = 104 + 6 * math.cos(sway)
    draw_tail(p, pal, bezier((128, 186), (182, 194), (206, 150), (tip_x, tip_y)))
    # ancas y cuerpo
    for sx in (-1, 1):
        haunch = fluffy(96 + sx * 44, 172, 28, 26, tufts=((0, 360, 0.06),), n=24)
        fill_outline(p, haunch, fur_brush(pal, 70, 150, 120, 200), pal)
    p.save()
    p.translate(96, 200)
    p.scale(1, breath)
    p.translate(-96, -200)
    body = fluffy(96, 150, 50, 50, tufts=((160, 200, 0.12), (-20, 20, 0.12)), n=34)
    fill_outline(p, body, fur_brush(pal, 60, 100, 140, 200), pal)
    p.save()
    p.setClipPath(body)
    for sx in (-1, 1):
        for k in range(2):
            y = 140 + k * 18
            stripe(p, pal, [(96 + sx * 50, y), (96 + sx * 40, y + 5), (96 + sx * 33, y + 13)], 3.6)
    p.restore()
    bib = fluffy(96, 146, 33, 42, tufts=((45, 135, 0.18), (200, 340, 0.12)), n=30)
    fill_outline(p, bib, white_brush(pal, 96, 135, 34), pal, 1.6)
    p.restore()
    # patas delanteras
    for x in (80, 112):
        leg = QPainterPath()
        leg.addRoundedRect(QRectF(x - 11, 164, 22, 32), 10, 10)
        fill_outline(p, leg, fur_brush(pal, x - 10, 150, x + 10, 196), pal)
        draw_paw(p, pal, x, 196, 13.5, 8.5)
    for sx in (-1, 1):
        draw_paw(p, pal, 96 + sx * 58, 198, 14, 7, toes=False)
    # collar y cabeza
    p.save()
    hx, hy = 96, 108
    p.translate(hx, hy + v.cabeza_y)
    p.rotate(v.inclinacion)
    p.translate(-hx, -hy)
    draw_collar(p, pal, 96, 114, 36)
    draw_head(p, pal, v, t, cy=66)
    p.restore()


def pose_ventana(p, pal, v: Visual, t: float):
    """Echada arriba de una ventana: el borde está en y = SUELO['ventana']; patitas y cola cuelgan."""
    ground = SUELO["ventana"]
    sway = 0.25 * math.sin(t * 0.9) if not v.reducido else 0
    # cola colgando por el borde
    draw_tail(p, pal, bezier((168, ground - 6), (190, ground + 4), (186 + 14 * sway, ground + 30),
                             (190 + 22 * sway, ground + 52)), 18, 13)
    breath = 1 + (0.02 * math.sin(t * 1.4) if not v.reducido else 0)
    p.save()
    p.translate(130, ground)
    p.scale(1, breath)
    p.translate(-130, -ground)
    body = fluffy(136, ground - 22, 70, 26, tufts=((200, 340, 0.08),), n=36)
    fill_outline(p, body, fur_brush(pal, 70, ground - 50, 190, ground), pal)
    p.save()
    p.setClipPath(body)
    for k in range(4):
        x = 120 + k * 18
        stripe(p, pal, [(x, ground - 48), (x + 5, ground - 34), (x + 2, ground - 20)], 4.5)
    p.restore()
    p.restore()
    # patitas delanteras colgando
    for x, dx in ((62, -2), (88, 2)):
        leg = tube([(x, ground - 6), (x + dx * 0.5, ground + 10), (x + dx, ground + 22)], [18, 17, 16])
        fill_outline(p, leg, fur_brush(pal, x - 8, ground, x + 8, ground + 24), pal)
        draw_paw(p, pal, x + dx, ground + 26, 11.5, 8)
    # cabeza apoyada (más chica y ladeada)
    p.save()
    p.translate(74, ground - 30)
    p.rotate(-8 + (1.5 * math.sin(t * 1.4) if not v.reducido else 0))
    p.scale(0.72, 0.72)
    p.translate(-96, -70)
    draw_head(p, pal, v, t)
    p.restore()


def pose_panza(p, pal, v: Visual, t: float):
    """Panza arriba sobre la barra de tareas: apoyo en y = SUELO['panza']."""
    ground = SUELO["panza"]
    wig = math.sin(t * 3.0) * 3 if not v.reducido else 0
    draw_tail(p, pal, bezier((186, ground - 14), (214, ground - 4), (234, ground - 20), (226, ground - 46)), 17, 12)
    # patas traseras arriba
    for x, ang in ((160, 12), (180, 24)):
        leg = tube([(x, ground - 30), (x + ang * 0.3, ground - 52), (x + ang * 0.5 + wig * 0.3, ground - 70)], [24, 20, 17])
        fill_outline(p, leg, fur_brush(pal, x, ground - 70, x + 20, ground - 30), pal)
        draw_paw(p, pal, x + ang * 0.5 + wig * 0.3, ground - 74, 11, 8)
    breath = 1 + (0.025 * math.sin(t * 1.4) if not v.reducido else 0)
    p.save()
    p.translate(136, ground)
    p.scale(1, breath)
    p.translate(-136, -ground)
    body = fluffy(138, ground - 28, 62, 28, tufts=((20, 160, 0.08),), n=36)
    fill_outline(p, body, fur_brush(pal, 80, ground - 60, 200, ground), pal)
    belly = fluffy(132, ground - 36, 40, 17, tufts=((0, 360, 0.12),), n=26)
    fill_outline(p, belly, white_brush(pal, 132, ground - 40, 38), pal, 1.6)
    p.save()
    p.setClipPath(body)
    for k in range(3):
        x = 168 + k * 11
        stripe(p, pal, [(x, ground - 8), (x + 4, ground - 26), (x + 2, ground - 50)], 4.2)
    p.restore()
    p.restore()
    # patas delanteras arriba (dobladitas)
    for x, ang in ((104, -8), (122, 6)):
        leg = tube([(x, ground - 46), (x + ang * 0.4, ground - 66), (x + ang - wig * 0.4, ground - 78)], [20, 18, 16])
        fill_outline(p, leg, fur_brush(pal, x, ground - 80, x + 10, ground - 46), pal)
        draw_paw(p, pal, x + ang - wig * 0.4, ground - 82, 10.5, 7.5)
    # cabeza recostada a la izquierda, mirando hacia arriba
    p.save()
    p.translate(50, ground - 42)
    p.rotate(-20)
    p.scale(0.72, 0.72)
    p.translate(-96, -70)
    draw_head(p, pal, v, t)
    p.restore()


def paint_cat(p: QPainter, v: Visual, t: float) -> None:
    """Dibuja el gato (y el plato) en coordenadas lógicas GATO_W x GATO_H."""
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pal = Paleta(v.gris)
    if v.pose == "sentada" and v.plato != "ninguno":
        wig = 2.0 * math.sin(t * 7.0) if v.modo == "hambriento" and not v.reducido else 0.0
        draw_bowl(p, pal, v.comida if v.plato == "lleno" else 0.0, wig)
    {"ventana": pose_ventana, "panza": pose_panza}.get(v.pose, pose_sentada)(p, pal, v, t)
    # corazones (caricia) y zzz (dormir)
    if v.corazones > 0:
        k = v.corazones
        for i, dx in enumerate((-28, 0, 26)):
            _heart(p, 96 + dx, 30 - 30 * k - i * 4, 6 + 2 * i, QColor(232, 84, 110, int(255 * (1 - k))))
    if v.zzz:
        base_x, base_y = {"ventana": (110, 78), "panza": (40, 100)}.get(v.pose, (140, 30))
        p.setPen(QPen(pal.c(QColor("#5B6B8C")), 1))
        for i, size in enumerate((9, 12, 15)):
            dy = 0 if v.reducido else 3 * math.sin(t * 1.5 + i)
            p.setFont(QFont("Segoe UI", size, QFont.Weight.Bold))
            p.drawText(QPointF(base_x + i * 11, base_y - i * 13 + dy), "z")


def _heart(p: QPainter, cx: float, cy: float, s: float, color: QColor) -> None:
    path = QPainterPath()
    path.moveTo(cx, cy + s * 0.35)
    path.cubicTo(cx - s, cy - s * 0.4, cx - s * 0.45, cy - s * 1.05, cx, cy - s * 0.45)
    path.cubicTo(cx + s * 0.45, cy - s * 1.05, cx + s, cy - s * 0.4, cx, cy + s * 0.35)
    p.setPen(Qt.PenStyle.NoPen)
    p.fillPath(path, color)


# ---------------------------------------------------------------- globo (en píxeles)
def bubble_rect(v: Visual) -> QRectF:
    if v.globo_clic:
        return QRectF(2, 2, GLOBO_W - 4, GLOBO_H - 14)
    return QRectF(2, 22, GLOBO_W - 4, GLOBO_H - 34)


def paint_bubble(p: QPainter, v: Visual, punta_x: float) -> None:
    if not v.globo:
        if v.desconectado:
            p.setFont(QFont("Segoe UI", 8))
            p.setPen(QColor("#666666"))
            p.drawText(QRectF(0, GLOBO_H - 18, GLOBO_W, 14), Qt.AlignmentFlag.AlignCenter, "sin conexión · reintentando")
        return
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    rect = bubble_rect(v)
    p.setPen(_pen(QColor("#7E4524"), 1.6))
    p.setBrush(QColor("#FFFDF8") if not v.desconectado else QColor("#F1F1F1"))
    path = QPainterPath()
    path.addRoundedRect(rect, 14, 14)
    tip = QPainterPath(QPointF(punta_x - 9, rect.bottom() - 1))
    tip.lineTo(QPointF(punta_x + 2, GLOBO_H - 2))
    tip.lineTo(QPointF(punta_x + 9, rect.bottom() - 1))
    tip.closeSubpath()
    p.drawPath(path.united(tip))
    p.setPen(QColor("#3A2A20"))
    p.setFont(QFont("Segoe UI", 9))
    texto = rect.adjusted(10, 5, -10, -15 if v.globo_clic else -5)
    p.drawText(texto, int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap), v.globo)
    if v.globo_clic:
        p.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        p.setPen(QColor("#1F5FBF"))
        p.drawText(QRectF(rect.x(), rect.bottom() - 16, rect.width(), 13), Qt.AlignmentFlag.AlignCenter,
                   "Tocá el globo o el plato para registrar")


def tray_pixmap(size: int = 64) -> QPixmap:
    """Icono de bandeja: la cara de Cora."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    s = size / 130.0
    p.scale(s, s)
    p.translate(-31, -6)
    v = Visual(modo="tranquilo", ojos="abiertos", plato="ninguno", reducido=True)
    draw_head(p, Paleta(False), v, 0.0)
    p.end()
    return pm
