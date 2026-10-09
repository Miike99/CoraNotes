"""Genera las imágenes de Cora para el README (herramienta de desarrollo, sin pantalla).

Uso: .venv\\Scripts\\python.exe scripts\\capturas_cora.py
Salida: docs/img/cora-estados.png
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from coranotes.mascota.drawing import GATO_H, GATO_W, GLOBO_H, GLOBO_W, paint_bubble, paint_cat  # noqa: E402
from coranotes.mascota.logic import Visual  # noqa: E402
from coranotes.pet import MENSAJES  # noqa: E402

ESTADOS = [
    ("Pide comida", Visual(modo="hambriento", ojos="abiertos", plato="vacio", boca_abierta=True, inclinacion=-5,
                           cola=0.5, globo=MENSAJES["hambriento"], globo_clic=True)),
    ("Come al registrar", Visual(modo="comiendo", ojos="felices", plato="lleno", comida=0.7, inclinacion=12,
                                 cabeza_y=10, globo="¡Ñam! Gracias por contarme tu día.")),
    ("Contenta (caricia)", Visual(modo="alimentado", ojos="felices", plato="ninguno", corazones=0.4, inclinacion=6)),
    ("En calma", Visual(modo="tranquilo", ojos="abiertos", plato="ninguno", cola=0.3, inclinacion=2)),
    ("Duerme arriba de una ventana", Visual(modo="descanso", ojos="dormidos", plato="ninguno", zzz=True, pose="ventana")),
    ("Duerme sobre la barra de tareas", Visual(modo="descanso", ojos="dormidos", plato="ninguno", zzz=True, pose="panza")),
]


def main() -> None:
    app = QApplication.instance() or QApplication([])  # noqa: F841
    escala = 2.0  # alta resolución para el README
    cw, ch = GLOBO_W, GLOBO_H + GATO_H
    cols, rows = 3, 2
    img = QImage(int(cw * cols * escala), int((ch + 26) * rows * escala), QImage.Format.Format_ARGB32)
    img.fill(QColor("#FFFFFF"))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.scale(escala, escala)
    for i, (titulo, v) in enumerate(ESTADOS):
        x0, y0 = (i % cols) * cw, (i // cols) * (ch + 26)
        p.save()
        p.translate(x0, y0)
        p.setPen(QColor("#5A3A28"))
        p.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        p.drawText(QRectF(0, 2, cw, 20), Qt.AlignmentFlag.AlignCenter, titulo)
        p.translate(0, 24)
        if v.pose == "ventana":  # borde de una ventana debajo
            p.fillRect(QRectF(0, GLOBO_H + 150, cw, ch - GLOBO_H - 150), QColor("#C9D6E6"))
            p.fillRect(QRectF(0, GLOBO_H + 150, cw, 8), QColor("#9FB3CC"))
        if v.pose == "panza":  # barra de tareas debajo
            p.fillRect(QRectF(0, GLOBO_H + 198, cw, ch - GLOBO_H - 198), QColor("#2B3440"))
        p.save()
        p.translate(0, GLOBO_H)
        paint_cat(p, v, 1.0)
        p.restore()
        paint_bubble(p, v, 96)
        p.restore()
    p.end()
    out = ROOT / "docs" / "img" / "cora-estados.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out))
    print(f"[capturas] {out}")


if __name__ == "__main__":
    main()
