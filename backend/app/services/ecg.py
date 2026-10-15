"""Synthetic ECG (lead II-like) waveform generator.

A sum-of-Gaussians beat model (P, Q, R, S, T) with mild heart-rate variability, baseline wander
and noise. Leads-off produces a flat, noisy trace; artifact adds motion noise.
"""

import math
import random

# (amplitude mV, offset from R peak in s, width s)
_WAVES = (
    (0.12, -0.20, 0.025),   # P
    (-0.10, -0.045, 0.010),  # Q
    (1.05, 0.0, 0.011),     # R
    (-0.25, 0.040, 0.011),  # S
    (0.32, 0.28, 0.045),    # T
)


def synth_ecg(heart_rate: float | None, seconds: float = 6.0, fs: int = 125, seed: int = 0,
              leads_off: bool = False, artifact: bool = False) -> list[float]:
    rng = random.Random(seed)
    n = int(seconds * fs)
    if leads_off or heart_rate is None:
        return [round(rng.gauss(0, 0.008), 3) for _ in range(n)]

    rr = 60.0 / max(25.0, min(240.0, heart_rate))
    beats: list[float] = []
    t = rng.uniform(0.1, rr)
    while t < seconds + 0.5:
        beats.append(t)
        t += rr * (1 + rng.gauss(0, 0.025))

    out: list[float] = []
    for i in range(n):
        ts = i / fs
        v = 0.0
        for b in beats:
            dt = ts - b
            if -0.35 < dt < 0.5:
                for amp, off, width in _WAVES:
                    v += amp * math.exp(-((dt - off) ** 2) / (2 * width ** 2))
        v += 0.04 * math.sin(2 * math.pi * 0.25 * ts)
        v += rng.gauss(0, 0.012)
        if artifact:
            v += 0.25 * math.sin(2 * math.pi * 3.1 * ts) * rng.random()
        out.append(round(v, 3))
    return out
