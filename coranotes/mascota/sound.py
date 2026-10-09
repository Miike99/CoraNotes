"""Sonidos suaves generados en código (desactivados por defecto). Solo reproduce, nunca graba."""
from __future__ import annotations

import math
import struct
import sys
import wave
from pathlib import Path

SR = 22050
TONOS = {  # (frecuencia inicial, final, duración en s)
    "hambre": [(520, 760, 0.12), (760, 600, 0.16)],
    "comer": [(660, 880, 0.08), (880, 990, 0.08), (990, 1180, 0.10)],
    "ronroneo": [(140, 150, 0.35)],
}


def _write_wav(path: Path, partes) -> None:
    frames = bytearray()
    for f0, f1, dur in partes:
        n = int(SR * dur)
        fase = 0.0
        for i in range(n):
            f = f0 + (f1 - f0) * i / n
            fase += 2 * math.pi * f / SR
            env = math.sin(math.pi * i / n)  # sin clics al empezar/terminar
            frames += struct.pack("<h", int(0.18 * 32767 * env * math.sin(fase)))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(bytes(frames))


class SoundPlayer:
    def __init__(self, run_dir: Path):
        self.dir = run_dir

    def play(self, tipo: str) -> None:
        if sys.platform != "win32" or tipo not in TONOS:
            return
        path = self.dir / f"mascota_{tipo}.wav"
        try:
            if not path.exists():
                _write_wav(path, TONOS[tipo])
            import winsound
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        except Exception:  # noqa: BLE001 - un sonido nunca debe romper la mascota
            pass
