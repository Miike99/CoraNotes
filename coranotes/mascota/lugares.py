"""Dónde duerme Cora: arriba de una ventana o sobre la barra de tareas.

Solo se leen posiciones y tamaños de ventanas (nunca títulos, contenido ni capturas de pantalla).
El cálculo de la posición es puro (se prueba sin Windows); la enumeración usa la API de Win32.
"""
from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass

LUGARES = ("escritorio", "ventanas", "barra_tareas")


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(v, max(lo, hi)))


BOTONES_PX = 150  # esquina derecha de la barra de título (minimizar, maximizar, cerrar): no se tapa


def perch_position(target: Rect, area: Rect, win_w: int, win_h: int, ground_px: int,
                   prefer_x: int | None = None, content: tuple[int, int] | None = None) -> tuple[int, int] | None:
    """Posición de la ventana de Cora para que se apoye sobre el borde superior de `target`.

    `ground_px`: distancia (px) desde el borde superior de la ventana de Cora hasta la línea de apoyo.
    `content`: desde dónde hasta dónde (px, medidos desde el borde izquierdo de la ventana de Cora) está
    dibujada la gata; así queda entera sobre la ventana y lejos de los botones de la barra de título.
    Devuelve None si no hay lugar arriba (por ejemplo, ventana maximizada) o si la ventana es muy angosta.
    """
    c_left, c_right = content if content else (0, win_w)
    if target.top - area.top < ground_px * 0.5:  # no entra arriba (p. ej. ventana pegada al borde superior)
        return None
    y = target.top - ground_px  # puede quedar parte transparente (zona del globo) fuera de la pantalla
    lo = target.left + 12 - c_left
    hi = target.right - BOTONES_PX - c_right
    if hi < lo:  # ventana angosta: se permite llegar hasta el borde derecho
        hi = target.right - 8 - c_right
    if hi < lo:
        return None
    x = prefer_x if prefer_x is not None else hi
    x = _clamp(x, lo, hi)
    x = _clamp(x, area.left - c_left, area.right - c_right)
    return x, y


def taskbar_position(available: Rect, screen: Rect, win_w: int, ground_px: int,
                     prefer_x: int | None = None) -> tuple[int, int]:
    """Cora acostada justo encima de la barra de tareas (o del borde inferior si la barra está oculta)."""
    ground = available.bottom if available.bottom < screen.bottom else screen.bottom
    x = prefer_x if prefer_x is not None else available.right - win_w - 60
    return _clamp(x, available.left, available.right - win_w), ground - ground_px


# ---------------------------------------------------------------- Win32
_EXCLUIR = {"Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman", "WorkerW", "NotifyIconOverflowWindow",
            "Windows.UI.Core.CoreWindow", "TopLevelWindowForOverflowXamlIsland", "XamlExplorerHostIslandWindow"}


def active_window(min_width: int = 220) -> Rect | None:
    """Rectángulo de la ventana activa (la que está adelante), o None si no sirve para acostarse arriba.

    Solo se usa la ventana activa: las de atrás pueden estar tapadas y Cora quedaría «flotando».
    No sirve si está maximizada, minimizada, oculta, es de esta app o es parte del escritorio/barra.
    Coordenadas físicas de pantalla (las de la ventana visible, sin la sombra). None fuera de Windows.
    """
    if sys.platform != "win32":
        return None
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    dwm = ctypes.windll.dwmapi
    user32.GetForegroundWindow.restype = wintypes.HWND
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    GWL_EXSTYLE, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = -20, 0x80, 0x08000000
    DWMWA_EXTENDED_FRAME_BOUNDS, DWMWA_CLOAKED = 9, 14
    if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd) or user32.IsZoomed(hwnd):
        return None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == os.getpid():
        return None
    if user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & (WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE):
        return None
    cloaked = ctypes.c_int(0)
    dwm.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
    if cloaked.value:
        return None
    cls = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(hwnd, cls, 128)
    if cls.value in _EXCLUIR:
        return None
    r = wintypes.RECT()
    if dwm.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        user32.GetWindowRect(hwnd, ctypes.byref(r))
    rect = Rect(r.left, r.top, r.right, r.bottom)
    return rect if rect.width >= min_width and rect.height >= 120 else None
