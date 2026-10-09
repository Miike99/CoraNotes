"""Notificaciones nativas de Windows y avisos persistentes dentro de la app.

La notificación nativa se entrega al sistema mediante PowerShell + WinRT (sin dependencias extra).
Windows puede ocultarla (No molestar / Asistente de concentración) sin informarlo: por eso se
registra como «entregada al sistema», nunca como «vista».
"""
from __future__ import annotations

import base64
import logging
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from xml.sax.saxutils import escape, quoteattr

from .db import rows
from .util import utc_iso

log = logging.getLogger("coranotes.avisos")

POWERSHELL_AUMID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"


@dataclass
class Delivery:
    estado: str  # entregada_al_sistema | desactivada | no_disponible | error
    detalle: str = ""


class NullNotifier:
    def notify(self, titulo: str, mensaje: str, enlace: str, acciones=None) -> Delivery:
        return Delivery("no_disponible", "Las notificaciones nativas no están disponibles en este sistema.")


@dataclass
class RecordingNotifier:
    """Para pruebas: guarda lo que se habría mostrado (no es una notificación real)."""
    enviados: list = field(default_factory=list)

    def notify(self, titulo, mensaje, enlace, acciones=None) -> Delivery:
        self.enviados.append({"titulo": titulo, "mensaje": mensaje, "enlace": enlace})
        return Delivery("simulada", "Notificación simulada (prueba automática)")


def build_toast_xml(titulo: str, mensaje: str, enlace: str, acciones: list[tuple[str, str]] | None) -> str:
    acts = "".join(
        f"<action content={quoteattr(label)} activationType=\"protocol\" arguments={quoteattr(url)}/>"
        for label, url in (acciones or [])[:3])
    return (f"<toast activationType=\"protocol\" launch={quoteattr(enlace)}>"
            f"<visual><binding template=\"ToastGeneric\"><text>{escape(titulo)}</text>"
            f"<text>{escape(mensaje)}</text></binding></visual>"
            + (f"<actions>{acts}</actions>" if acts else "") + "</toast>")


class WindowsToastNotifier:
    def __init__(self):
        self._lock = threading.Lock()

    def notify(self, titulo: str, mensaje: str, enlace: str, acciones=None) -> Delivery:
        xml = build_toast_xml(titulo, mensaje, enlace, acciones)
        xml_b64 = base64.b64encode(xml.encode("utf-8")).decode("ascii")
        script = (
            "$ErrorActionPreference = 'Stop'\n"
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null\n"
            "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null\n"
            f"$n = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{POWERSHELL_AUMID}')\n"
            "$s = ''\n"
            "try { $s = [string]$n.Setting } catch { $s = '' }\n"
            "if ($s -like 'Disabled*') { Write-Output ('SETTING:' + $s); exit 0 }\n"
            "$x = New-Object Windows.Data.Xml.Dom.XmlDocument\n"
            f"$x.LoadXml([System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{xml_b64}')))\n"
            "$n.Show([Windows.UI.Notifications.ToastNotification]::new($x))\n"
            "if ($s -eq 'Enabled') { Write-Output 'OK' } else { Write-Output 'OK_SIN_ESTADO' }\n")
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with self._lock:
            try:
                proc = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                     "-EncodedCommand", encoded],
                    capture_output=True, text=True, timeout=25, creationflags=flags)
            except (OSError, subprocess.TimeoutExpired) as exc:
                log.warning("No se pudo invocar PowerShell para notificar: %s", type(exc).__name__)
                return Delivery("error", "No se pudo invocar el sistema de notificaciones de Windows.")
        out = (proc.stdout or "").strip()
        lines = out.splitlines()
        if "OK" in lines:
            return Delivery("entregada_al_sistema",
                            "Entregada a Windows. Si «No molestar» está activo, puede quedar solo en el centro de notificaciones.")
        if "OK_SIN_ESTADO" in lines:
            return Delivery("entregada_al_sistema",
                            "Entregada a Windows, pero Windows no informó si las notificaciones están habilitadas: "
                            "confirmá vos si la viste.")
        if out.startswith("SETTING:"):
            return Delivery("desactivada", f"Windows tiene las notificaciones desactivadas para esta app ({out[8:]}).")
        log.warning("Notificación no entregada (código %s)", proc.returncode)
        return Delivery("error", "Windows rechazó la notificación. Revisá Configuración > Sistema > Notificaciones.")


def default_notifier():
    return WindowsToastNotifier() if sys.platform == "win32" else NullNotifier()


class NoticeService:
    """Avisos persistentes (siempre) + notificación nativa (cuando se pide y es posible)."""

    def __init__(self, db, clock, notifier, base_url: str):
        self.db = db
        self.clock = clock
        self.notifier = notifier
        self.base_url = base_url

    def add(self, tipo: str, titulo: str, mensaje: str, ruta: str = "#/inicio", nativo: bool = True,
            clave: str | None = None, acciones: list[tuple[str, str]] | None = None) -> dict:
        with self.db.tx() as c:
            cur = c.execute("INSERT INTO avisos(tipo, titulo, mensaje, enlace, clave_ejecucion, entrega, creado_utc) "
                            "VALUES (?,?,?,?,?,?,?)", (tipo, titulo, mensaje, ruta, clave,
                                                       "pendiente" if nativo else "solo_app",
                                                       utc_iso(self.clock.now())))
            aviso_id = cur.lastrowid
        if nativo:
            url = f"{self.base_url}/{ruta}"
            acts = [(label, f"{self.base_url}/{r}") for label, r in (acciones or [])]
            try:
                d = self.notifier.notify(titulo, mensaje, url, acts)
            except Exception:  # noqa: BLE001
                log.exception("Fallo inesperado al notificar")
                d = Delivery("error", "Fallo inesperado al notificar")
            with self.db.tx() as c:
                c.execute("UPDATE avisos SET entrega=?, entrega_detalle=? WHERE id=?", (d.estado, d.detalle, aviso_id))
        return self.get(aviso_id)

    def get(self, aviso_id: int) -> dict:
        with self.db.read() as c:
            row = c.execute("SELECT * FROM avisos WHERE id = ?", (aviso_id,)).fetchone()
            return dict(row) if row else {}

    def list(self, solo_no_leidos: bool = False, limite: int = 50) -> list[dict]:
        sql = "SELECT * FROM avisos"
        if solo_no_leidos:
            sql += " WHERE leido = 0"
        sql += " ORDER BY id DESC LIMIT ?"
        with self.db.read() as c:
            return rows(c.execute(sql, (limite,)))

    def mark_read(self, aviso_id: int | None = None) -> None:
        with self.db.tx() as c:
            if aviso_id is None:
                c.execute("UPDATE avisos SET leido = 1")
            else:
                c.execute("UPDATE avisos SET leido = 1 WHERE id = ?", (aviso_id,))
