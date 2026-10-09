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


def perch_position(target: Rect, area: Rect, win_w: int, win_h: int, ground_px: int,
                   prefer_x: int | None = None) -> tuple[int, int] | None:
    """Posición de la ventana de Cora para que se apoye sobre el borde superior de `target`.

    `ground_px` es la distancia (en píxeles) desde el borde superior de la ventana de Cora hasta la
    línea de apoyo del dibujo. Devuelve None si no hay lugar arriba (por ejemplo, ventana maximizada).
    """
    if target.width < win_w * 0.6:
        return None
    if target.top - area.top < ground_px * 0.5:  # no entra arriba (p. ej. ventana pegada al borde superior)
        return None
    y = target.top - ground_px  # puede quedar parte transparente (zona del globo) fuera de la pantalla
    x = prefer_x if prefer_x is not None else target.right - win_w - 30
    x = _clamp(x, target.left - win_w // 5, target.right - (win_w * 4) // 5)
    x = _clamp(x, area.left, area.right - win_w)
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


def candidate_windows(min_width: int = 220) -> list[Rect]:
    """Ventanas visibles de otras aplicaciones, la activa primero y luego en orden de apilado.

    Coordenadas físicas de pantalla. Lista vacía fuera de Windows.
    """
    if sys.platform != "win32":
        return []
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    dwm = ctypes.windll.dwmapi
    own_pid = os.getpid()
    GWL_EXSTYLE, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = -20, 0x80, 0x08000000
    DWMWA_EXTENDED_FRAME_BOUNDS, DWMWA_CLOAKED = 9, 14
    found: list[tuple[int, Rect]] = []

    def visible_rect(hwnd) -> Rect | None:
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd) or user32.IsZoomed(hwnd):
            return None
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == own_pid:
            return None
        ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if ex & (WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE):
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

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):
        rect = visible_rect(hwnd)
        if rect is not None:
            found.append((hwnd, rect))
        return True

    user32.EnumWindows(callback, 0)
    fg = user32.GetForegroundWindow()
    found.sort(key=lambda item: 0 if item[0] == fg else 1)  # sort estable: el resto queda en orden Z
    return [rect for _, rect in found]
