"""Synthesise the template game's sounds into MixarLink/Resources/Sounds.

    python3 scripts/make_sounds.py

Everything is made here from sine, noise and simple filters (no samples, so
nothing to license): a pickup chime, a hurt hit, a stone door grinding open,
a win fanfare, a checkpoint chime, a wind loop and a calm music loop. The two
loops end where they start, so they repeat without a click. Mono 16-bit WAV;
the template game imports them into /Game/Mixar/Game/Audio.
"""

import os
import wave

import numpy as np

RATE = 32000
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "MixarLink", "Resources",
                   "Sounds")
rng = np.random.default_rng(7)


def t_axis(seconds: float) -> np.ndarray:
    return np.arange(int(seconds * RATE)) / RATE


def note(freq: float) -> float:
    return freq


def hz(name: str) -> float:
    """'A4' style note names."""
    names = {"C": -9, "D": -7, "E": -5, "F": -4, "G": -2, "A": 0, "B": 2}
    semis = names[name[0]] + (1 if "#" in name else 0) + 12 * (int(name[-1]) - 4)
    return 440.0 * 2 ** (semis / 12)


def bell(freq: float, seconds: float, decay: float = 0.4, bright: float = 1.0) -> np.ndarray:
    """A struck bell: inharmonic partials, each fading faster the higher it is."""
    t = t_axis(seconds)
    out = np.zeros_like(t)
    for ratio, amp in ((1.0, 1.0), (2.0, 0.45 * bright), (2.76, 0.25 * bright), (5.4, 0.12 * bright),
                       (8.93, 0.05 * bright)):
        out += amp * np.sin(2 * np.pi * freq * ratio * t) * np.exp(-t / (decay / ratio ** 0.6))
    attack = np.minimum(1.0, t / 0.003)
    return out * attack


def lowpass(x: np.ndarray, cutoff) -> np.ndarray:
    """One-pole low-pass; ``cutoff`` in Hz, a number or one per sample."""
    cutoff = np.broadcast_to(np.asarray(cutoff, dtype=float), x.shape)
    alpha = 1.0 - np.exp(-2 * np.pi * cutoff / RATE)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc += alpha[i] * (x[i] - acc)
        y[i] = acc
    return y


def place(buf: np.ndarray, sound: np.ndarray, at: float) -> None:
    i = int(at * RATE)
    n = min(len(sound), len(buf) - i)
    buf[i:i + n] += sound[:n]


def norm(x: np.ndarray, peak: float = 0.89) -> np.ndarray:
    return x * (peak / max(1e-9, np.max(np.abs(x))))


def fade(x: np.ndarray, start: float = 0.005, end: float = 0.05) -> np.ndarray:
    n0, n1 = int(start * RATE), int(end * RATE)
    x = x.copy()
    if n0:
        x[:n0] *= np.linspace(0, 1, n0)
    if n1:
        x[-n1:] *= np.linspace(1, 0, n1)
    return x


def loop_seam(x: np.ndarray, overlap_s: float) -> np.ndarray:
    """Fold the tail over the head with an equal-power crossfade, so the
    sound loops seamlessly; the result is shorter by ``overlap_s``."""
    n = int(overlap_s * RATE)
    head, body, tail = x[:n], x[n:-n] if n else x, x[-n:]
    w = np.linspace(0, np.pi / 2, n)
    start = head * np.sin(w) + tail * np.cos(w)
    return np.concatenate([start, body])


def pickup() -> np.ndarray:
    buf = np.zeros(int(1.1 * RATE))
    place(buf, bell(hz("E6"), 1.0, 0.35), 0.0)
    place(buf, bell(hz("B6"), 0.95, 0.4), 0.07)
    place(buf, 0.5 * bell(hz("E7"), 0.8, 0.3, 0.5), 0.14)
    return fade(norm(buf, 0.8), 0.0, 0.1)


def checkpoint() -> np.ndarray:
    buf = np.zeros(int(1.2 * RATE))
    place(buf, bell(hz("G5"), 1.0, 0.45), 0.0)
    place(buf, bell(hz("D6"), 1.0, 0.5), 0.12)
    return fade(norm(buf, 0.7), 0.0, 0.15)


def hurt() -> np.ndarray:
    t = t_axis(0.55)
    sweep = 330 * np.exp(-t * 4.5) + 70
    phase = 2 * np.pi * np.cumsum(sweep) / RATE
    tone = (np.sin(phase) + 0.35 * np.sin(3 * phase) + 0.15 * np.sin(5 * phase)) * np.exp(-t * 6)
    thump = lowpass(rng.standard_normal(len(t)), 300) * np.exp(-t * 18) * 3
    return fade(norm(tone + thump, 0.85), 0.002, 0.08)


def door() -> np.ndarray:
    t = t_axis(2.6)
    env = np.clip(t / 0.25, 0, 1) * np.clip((2.6 - t) / 0.6, 0, 1)
    grind = lowpass(rng.standard_normal(len(t)), 180 + 120 * np.sin(2 * np.pi * 3.1 * t) ** 2)
    rasp = lowpass(rng.standard_normal(len(t)), 1400) * (0.5 + 0.5 * np.sin(2 * np.pi * 7.3 * t)) * 0.08
    hum = 0.25 * np.sin(2 * np.pi * 52 * t + 0.4 * np.sin(2 * np.pi * 0.9 * t))
    thud = np.zeros_like(t)
    tail = t_axis(0.6)
    place(thud, lowpass(rng.standard_normal(len(tail)), 120) * np.exp(-tail * 9) * 4, 2.0)
    return fade(norm((grind * 3 + rasp + hum) * env + thud, 0.85), 0.01, 0.2)


def win() -> np.ndarray:
    buf = np.zeros(int(3.2 * RATE))
    for i, name in enumerate(("C5", "E5", "G5", "C6")):
        place(buf, bell(hz(name), 1.6, 0.6), 0.13 * i)
    for name in ("C5", "E5", "G5", "C6", "E6"):  # the closing chord rings longer
        place(buf, 0.6 * bell(hz(name), 2.6, 1.1, 0.7), 0.6)
    t = t_axis(2.6)
    shimmer = sum(np.sin(2 * np.pi * hz(n) * 2 * t) for n in ("C6", "G6")) * 0.05 * np.exp(-t * 1.2)
    place(buf, shimmer * np.clip(t / 0.3, 0, 1), 0.6)
    return fade(norm(buf, 0.85), 0.0, 0.4)


def wind() -> np.ndarray:
    seconds = 14.0
    t = t_axis(seconds)
    white = rng.standard_normal(len(t))
    gust = 0.5 + 0.5 * np.sin(2 * np.pi * t / 7.0) * np.sin(2 * np.pi * t / 3.5 + 1.0)
    body = lowpass(white, 250 + 500 * gust)
    whistle = lowpass(white, 2200) - lowpass(white, 1500)
    out = body * (0.6 + 0.4 * gust) + 0.25 * whistle * gust ** 2
    return norm(loop_seam(out, 2.0), 0.6)


def saw(freq: float, t: np.ndarray) -> np.ndarray:
    """A band-limited saw (additive)."""
    out = np.zeros_like(t)
    k = 1
    while freq * k < 4000:
        out += np.sin(2 * np.pi * freq * k * t) / k
        k += 1
    return out


def music() -> np.ndarray:
    """A calm pad over Am - F - C - G, 6 s a chord, with a sparse bell line."""
    chord_s = 6.0
    chords = (("A3", "C4", "E4", "A2"), ("F3", "A3", "C4", "F2"), ("C4", "E4", "G4", "C3"),
              ("G3", "B3", "D4", "G2"))
    total = chord_s * len(chords)
    overlap = 2.0
    buf = np.zeros(int((total + overlap) * RATE))
    seg = t_axis(chord_s + overlap)
    env = np.clip(seg / 1.8, 0, 1) * np.clip((chord_s + overlap - seg) / 2.2, 0, 1)
    for i, chord in enumerate(chords):
        pad = np.zeros_like(seg)
        for name in chord:
            f = hz(name)
            for detune in (-0.004, 0.004):
                pad += saw(f * (1 + detune), seg) * (0.6 if name[-1] == "2" else 0.35)
        pad = lowpass(pad, 900)
        place(buf, pad * env, i * chord_s)
    melody = (("E5", 1.0), ("A5", 3.5), ("C6", 7.0), ("A5", 9.5), ("G5", 13.0), ("E5", 15.5), ("D5", 19.0),
              ("G5", 21.0))
    for name, at in melody:
        place(buf, 0.12 * bell(hz(name), 3.0, 1.2, 0.4), at)
    return norm(loop_seam(buf, overlap), 0.5)


def write(name: str, samples: np.ndarray) -> None:
    os.makedirs(OUT, exist_ok=True)
    data = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    with wave.open(os.path.join(OUT, name + ".wav"), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(RATE)
        fh.writeframes(data)
    print(f"{name}: {len(samples) / RATE:.1f} s")


if __name__ == "__main__":
    for fn in (pickup, checkpoint, hurt, door, win, wind, music):
        write("S_Mixar" + fn.__name__.capitalize(), fn())
