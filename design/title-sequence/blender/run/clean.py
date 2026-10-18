"""The Run: the clean rule for the title's sound (founder, 2026-10-17: no audible noise; any texture extremely subtle).

Three pieces, numpy and scipy only:

* `room_bed(n, slug)`: the score's own room tone, exactly as score-tools/whole.py makes it (the same recording,
  looped with the same 4 s equal-power crossfades from a slug-seeded offset, high-cut at 3 kHz and low-cut at 60 Hz
  by the same second-order curves, set to the same RMS). The constants are read from whole.py itself, never
  re-typed, so the title-to-film handover is the same room at the same level.
* `denoise(x)`: a gentle broadband spectral gate for a Foley *source sample* (never the mix): the noise profile is
  each frequency bin's 10th-percentile magnitude over the recording; bins near it are reduced by at most 18 dB with
  a soft knee, gains smoothed across time and frequency so transients keep their shape.
* `load_ir()`: the house IR as whole.py loads it (the direct sound at unity, the pre-delay cut), its tail cut where
  its envelope meets its own noise floor (about -85 dB) and faded, so the convolution adds no noise tail.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import numpy as np
from scipy.signal import istft, stft

WHOLE = Path("C:/Users/aacri/document-work/score-tools/whole.py")
ROOM = Path("D:/document-media/house-room/roomtone/house-roomtone-329569.wav")
IR = Path("D:/document-media/house-room/AIR_1_4/air_binaural_lecture_1_1_2.mat")
SR = 48000


def whole_constants() -> dict:
    tree = ast.parse(WHOLE.read_text(encoding="utf-8"))
    want = {"ROOM_TONE_DBFS", "ROOM_TONE_HICUT_HZ", "ROOM_TONE_LOCUT_HZ", "RATE"}
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and getattr(node.targets[0], "id", None) in want:
            out[node.targets[0].id] = ast.literal_eval(node.value)
    assert set(out) == want, out
    return out


C = whole_constants()


def _read_room():
    import warnings
    from scipy.io import wavfile
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sr, x = wavfile.read(ROOM)
    x = x.astype(np.float64)
    if x.dtype.kind != "f":
        pass
    if np.abs(x).max() > 2:
        x = x / 32768.0
    if x.ndim > 1:
        x = x.mean(axis=1)
    assert sr == C["RATE"]
    return x - np.mean(x)


def room_bed(n: int, slug: str = "the-run") -> np.ndarray:
    """whole.py's room bed, n samples at 48 kHz (its lines from `tone = tone - np.mean(tone)` to the RMS set)."""
    RATE = C["RATE"]
    tone = _read_room()
    xf = 4 * RATE
    offset = int(hashlib.sha256(slug.encode()).hexdigest(), 16) % max(1, len(tone) - xf)
    loop = [tone]
    total = len(tone)
    while total < n + offset:
        prev = loop[-1]
        r = np.arange(xf) / xf
        head_ = tone[:xf] * np.sin(0.5 * np.pi * r) + prev[-xf:] * np.cos(0.5 * np.pi * r)
        loop[-1] = prev[:-xf]
        loop.append(np.concatenate([head_, tone[xf:]]))
        total += len(tone) - xf
    bed = np.concatenate(loop)[offset: offset + n]
    B = np.fft.rfft(bed)
    f = np.fft.rfftfreq(len(bed), 1.0 / RATE)
    B *= 1.0 / (1.0 + (f / C["ROOM_TONE_HICUT_HZ"]) ** 4) ** 0.5
    B *= 1.0 / (1.0 + (C["ROOM_TONE_LOCUT_HZ"] / np.maximum(f, 1e-6)) ** 4) ** 0.5
    bed = np.fft.irfft(B, len(bed))
    bed *= 10 ** ((C["ROOM_TONE_DBFS"] - 20 * np.log10(np.sqrt(np.mean(bed ** 2)) + 1e-20)) / 20)
    return bed


def denoise(x: np.ndarray, max_db: float = 18.0, nper: int = 2048) -> np.ndarray:
    f, t, Z = stft(x, fs=SR, nperseg=nper, noverlap=nper * 3 // 4)
    mag = np.abs(Z)
    noise = np.percentile(mag, 10, axis=1, keepdims=True) + 1e-12
    snr = mag / noise
    floor = 10 ** (-max_db / 20)
    # soft knee: no reduction from 4x the noise up, full reduction at the noise
    g = np.clip((snr - 1.0) / 3.0, 0.0, 1.0)
    g = floor + (1 - floor) * g
    # smooth the gain over 3 bins and 3 frames
    from scipy.ndimage import uniform_filter
    g = uniform_filter(g, size=(3, 3), mode="nearest")
    _, y = istft(Z * g, fs=SR, nperseg=nper, noverlap=nper * 3 // 4)
    return y[:len(x)] if len(y) >= len(x) else np.pad(y, (0, len(x) - len(y)))


def floor_db(x: np.ndarray, hop: int = SR // 100, pct: float = 10.0) -> float:
    e = np.array([np.sqrt((x[i:i + hop] ** 2).mean()) for i in range(0, len(x) - hop, hop)])
    return float(np.percentile(20 * np.log10(e + 1e-12), pct))


def load_ir() -> tuple[np.ndarray, dict]:
    import sys
    sys.path.insert(0, "D:/document-media/house-room/tools")
    import mat5
    h = mat5.load(str(IR))["h_air"].ravel().astype(np.float64)
    pk = int(np.argmax(np.abs(h)))
    h = h[max(0, pk - 48):]
    h = h / np.max(np.abs(h))
    # the tail's own floor: the envelope (10 ms RMS) in the last fifth
    hop = SR // 100
    env = np.array([np.sqrt((h[i:i + hop] ** 2).mean()) for i in range(0, len(h) - hop, hop)])
    edb = 20 * np.log10(env + 1e-20)
    fl = float(np.median(edb[int(len(edb) * 0.8):]))
    # cut where the envelope first stays within 6 dB of the floor, with a 50 ms fade
    above = np.nonzero(edb > fl + 6)[0]
    cut = (above[-1] + 1) * hop if len(above) else len(h)
    fade = min(int(0.05 * SR), cut)
    h = h[:cut].copy()
    h[-fade:] *= np.cos(0.5 * np.pi * np.arange(fade) / fade) ** 2
    return h, {"floor_db": round(fl, 1), "cut_s": round(cut / SR, 3)}
