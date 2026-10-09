"""Maullidos y sonidos de gato sintetizados por código (sin grabaciones ni descargas).

- maullido: síntesis aditiva (armónicos de una fuente tipo glotis) con formantes que pasan por
  «m-i-a-u», un tono que sube y baja, vibrato y un poco de aire.
- trino («mrrp»): tono ascendente con modulación rápida de amplitud (la «r» rodada).
- ronroneo: ruido grave pulsado a ~25 Hz con ciclos de inspiración y espiración.

Solo reproduce (winsound); nunca graba. Los WAV se generan una vez, en segundo plano, y se reutilizan.
"""
from __future__ import annotations

import math
import random
import struct
import sys
import threading
import wave
from pathlib import Path

SR = 22050
VERSION = 4  # cambiar si se modifica la síntesis (regenera los archivos)


def _lerp(points, x):
    """Interpolación lineal en una lista [(x, y), ...] ordenada."""
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


# Formantes (Hz) a lo largo del maullido: m -> i -> a -> u
_F = [(0.00, (260, 1150, 2600)), (0.15, (380, 2300, 3200)), (0.45, (880, 1650, 2900)),
      (0.80, (500, 950, 2500)), (1.00, (380, 800, 2400))]


def _formants(x):
    i = 0
    while i < len(_F) - 2 and x > _F[i + 1][0]:
        i += 1
    (x0, a), (x1, b) = _F[i], _F[i + 1]
    k = min(1.0, max(0.0, (x - x0) / (x1 - x0)))
    return [a[j] + (b[j] - a[j]) * k for j in range(3)]


def meow(dur=0.72, f0_start=520, f0_peak=760, f0_end=470, rng=None) -> list[float]:
    rng = rng or random.Random(3)
    n = int(SR * dur)
    out = [0.0] * n
    phase = 0.0
    bw = (110.0, 160.0, 220.0)
    gains = (1.0, 0.75, 0.35)
    for i in range(n):
        x = i / n
        f0 = _lerp([(0, f0_start), (0.35, f0_peak), (1.0, f0_end)], x)
        f0 *= 1 + 0.012 * math.sin(2 * math.pi * 6.0 * i / SR) + 0.004 * (rng.random() - 0.5)
        phase += 2 * math.pi * f0 / SR
        fs = _formants(x)
        s = 0.0
        k = 1
        while k * f0 < 7000:
            fk = k * f0
            amp = 0.0
            for F, B, g in zip(fs, bw, gains):
                amp += g / (1 + ((fk - F) / B) ** 2)
            s += amp * math.sin(k * phase) / (k ** 0.6)
            k += 1
        k_m = min(1.0, x / 0.14)
        nasal = 0.45 + 0.55 * k_m * k_m * (3 - 2 * k_m)  # la «m» inicial, más apagada, sin cortes
        env = min(1.0, x / 0.07) * (1 - x) ** 0.6 * nasal
        breath = (rng.random() - 0.5) * 0.018 * env
        out[i] = s * env + breath
    return out


def trill(dur=0.42, rng=None) -> list[float]:
    rng = rng or random.Random(5)
    n = int(SR * dur)
    out = []
    phase = 0.0
    for i in range(n):
        x = i / n
        f0 = 380 + 300 * x ** 0.7
        phase += 2 * math.pi * f0 / SR
        roll = 0.55 + 0.45 * math.sin(2 * math.pi * 30 * i / SR)  # «r» rodada
        s = math.sin(phase) + 0.45 * math.sin(2 * phase) + 0.2 * math.sin(3 * phase)
        env = min(1.0, x / 0.08) * (1 - x) ** 0.8
        out.append(s * roll * env + (rng.random() - 0.5) * 0.01 * env)
    return out


def purr(dur=1.5, rng=None) -> list[float]:
    rng = rng or random.Random(9)
    n = int(SR * dur)
    out = []
    lp = lp2 = 0.0
    for i in range(n):
        x = i / n
        noise = rng.random() - 0.5
        lp += (noise - lp) * 0.03          # dos etapas de pasabajos: ruido bien grave
        lp2 += (lp - lp2) * 0.03
        pulse = max(0.0, math.sin(2 * math.pi * 25 * i / SR)) ** 3
        cycle = 0.55 + 0.45 * math.sin(2 * math.pi * x * 1.5 - 1.2)  # inspira / espira
        env = min(1.0, x / 0.1) * min(1.0, (1 - x) / 0.15)
        out.append((lp2 * 30 * pulse + 0.3 * math.sin(2 * math.pi * 50 * i / SR) * pulse) * cycle * env)
    return out


def _normalize(sig, peak=0.38):
    m = max(1e-9, max(abs(v) for v in sig))
    return [v * peak / m for v in sig]


def _silence(sec):
    return [0.0] * int(SR * sec)


def build(tipo: str) -> list[float]:
    if tipo == "hambre":  # dos maullidos: uno corto y uno más largo y suplicante
        return _normalize(meow(0.48, 560, 740, 560) + _silence(0.18) + meow(0.85, 500, 800, 430, random.Random(4)))
    if tipo == "comer":
        return _normalize(trill() + _silence(0.06) + trill(0.30, random.Random(6)), 0.32)
    if tipo == "ronroneo":
        return _normalize(purr(), 0.30)
    if tipo == "saludo":
        return _normalize(meow(0.40, 600, 820, 640), 0.30)
    raise ValueError(tipo)


TIPOS = ("hambre", "comer", "ronroneo", "saludo")


def write_wav(path: Path, sig) -> None:
    frames = b"".join(struct.pack("<h", int(max(-1.0, min(1.0, v)) * 32767)) for v in sig)
    tmp = path.with_suffix(".tmp")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(frames)
    tmp.replace(path)


def wav_path(run_dir: Path, tipo: str) -> Path:
    return run_dir / f"cora_{tipo}_v{VERSION}.wav"


def ensure_wav(run_dir: Path, tipo: str) -> Path:
    path = wav_path(run_dir, tipo)
    if not path.exists():
        run_dir.mkdir(parents=True, exist_ok=True)
        write_wav(path, build(tipo))
    return path


def play_file(path: Path) -> None:
    if sys.platform != "win32":
        return
    try:
        import winsound
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except Exception:  # noqa: BLE001 - un sonido nunca debe romper la app
        pass


class SoundPlayer:
    """Prepara los sonidos en segundo plano y los reproduce sin bloquear la interfaz."""

    def __init__(self, run_dir: Path):
        self.dir = run_dir
        self._lock = threading.Lock()
        threading.Thread(target=self._prepare_all, name="cora-sonidos", daemon=True).start()

    def _prepare_all(self) -> None:
        for tipo in TIPOS:
            try:
                with self._lock:
                    ensure_wav(self.dir, tipo)
            except Exception:  # noqa: BLE001
                pass

    def play(self, tipo: str) -> None:
        if tipo not in TIPOS:
            return

        def run():
            try:
                with self._lock:
                    path = ensure_wav(self.dir, tipo)
                play_file(path)
            except Exception:  # noqa: BLE001
                pass
        threading.Thread(target=run, daemon=True).start()
