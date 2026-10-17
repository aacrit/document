"""The Run: a rough Foley pass for a proof, placed from the simulation's own event list.

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/foley.py --proof latch --out <wav>

Every sound is a real recording: Freesound CC0 HQ previews, pinned by sha256 in design/title-sequence/run-sound-ledger.json
and decoded once to 48 kHz mono WAV on D:. One-shots are sliced at the recordings' own onsets and chosen by velocity
layer (the louder the contact, the louder the slice), round-robin, with a small pitch spread (+-3%); each is placed at
its contact's logged time with gain 20 log10(v_n / v_ref) (clipped to -40..+6 dB). Rolling is a loop whose gain follows
the body's speed from the bake. Everything is convolved with the house IR (Aachen lecture room, AIR h_air, 48 kHz) and
the house room tone (Freesound 329569, CC0, processed) sits under it. No synthesis, no generative model. The bronze
disc's whir is the coin recording itself, placed so its stop lands on the slap at f120.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, fftconvolve, resample_poly, sosfiltfilt

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, "D:/document-media/house-room/tools")
import eventlog as E  # noqa: E402
import mat5  # noqa: E402

SR = 48000
LEDGER = HERE.parents[1] / "run-sound-ledger.json"
SFX = Path("D:/document-media/title-sequence/run/sfx")
SIM = Path("D:/document-media/title-sequence/run/sim")
IR = Path("D:/document-media/house-room/AIR_1_4/air_binaural_lecture_1_1_2.mat")
ROOM = Path("D:/document-media/house-room/roomtone/house-roomtone-329569.wav")
FRAMES = {"latch": (96, 167), "galley": (456, 527)}
RNG = np.random.default_rng(20261017)


def load(sid: str) -> np.ndarray:
    led = {r["id"]: r for r in json.loads(LEDGER.read_text(encoding="utf-8"))["recordings"]}[sid]
    mp3 = SFX / led["file"]
    if hashlib.sha256(mp3.read_bytes()).hexdigest() != led["mp3_sha256"]:
        sys.exit(f"{sid}: mp3 bytes differ from the ledger")
    sr, x = wavfile.read(SFX / led["decoded"])
    x = x.astype(np.float64) / (32768.0 if x.dtype == np.int16 else 1.0)
    assert sr == SR
    return x


def onsets(x: np.ndarray, min_gap_s=0.08, rise_db=12.0, floor_db=-45.0) -> list[int]:
    hop = SR // 200
    e = np.array([np.sqrt((x[i:i + hop] ** 2).mean()) for i in range(0, len(x) - hop, hop)])
    db = 20 * np.log10(e + 1e-9)
    out = []
    for i in range(3, len(db)):
        if db[i] - db[i - 3] > rise_db and db[i] > floor_db and (not out or (i - out[-1]) * hop > min_gap_s * SR):
            out.append(i)
    return [max(0, i * hop - int(0.004 * SR)) for i in out]


def slices(x, length_s=0.25, **kw) -> list[np.ndarray]:
    n = int(length_s * SR)
    fade = np.ones(n)
    k = int(0.06 * SR)
    fade[-k:] = np.linspace(1, 0, k) ** 2
    out = [x[o:o + n] * fade[:len(x[o:o + n])] for o in onsets(x, **kw)]
    out = [s for s in out if len(s) == n]
    return sorted(out, key=lambda s: np.abs(s).max())                  # velocity layers, softest first


def lowpass(x, hz):
    return sosfiltfilt(butter(4, hz, "low", fs=SR, output="sos"), x)


def pitch(x, ratio):
    up, down = int(round(1000 / ratio)), 1000
    return resample_poly(x, up, down)


class Bus:
    def __init__(self, seconds):
        self.x = np.zeros(int(seconds * SR) + SR)
        self.placed = []

    def add(self, s, t, gain_db, label):
        i = int(round(t * SR))
        if i < 0:
            s, i = s[-i:], 0
        n = min(len(s), len(self.x) - i)
        if n <= 0:
            return
        self.x[i:i + n] += s[:n] * 10 ** (gain_db / 20)
        self.placed.append({"t": round(t, 4), "gain_db": round(gain_db, 1), "what": label})


def place_hits(bus, events, t0, pool, v_ref, label, rr, extra_db=0.0, lp=None, ratio=1.0):
    for e in events:
        v = e["v_n"]
        g = float(np.clip(20 * np.log10(v / v_ref), -40, 6)) + extra_db
        layer = int(np.clip(round((g + 40) / 46 * (len(pool) - 1)), 0, len(pool) - 1))
        cands = pool[max(0, layer - 1):layer + 2]
        s = cands[rr[0] % len(cands)]
        rr[0] += 1
        s = pitch(s, ratio * (1 + RNG.uniform(-0.03, 0.03)))
        if lp:
            s = lowpass(s, lp)
        bus.add(s / (np.abs(s).max() + 1e-9) * 0.5, e["t_s"] - t0, g, f"{label} {e['pair']} v={v:.3f}")


def roll(bus, poses, t0, t1, loop, v_ref, gain_db, label, lp=None):
    """A rolling loop whose gain follows the body's speed (from the bake), 10 ms blocks."""
    a = np.array(poses)
    t = a[:, 0]
    v = np.r_[0, np.linalg.norm(np.diff(a[:, 1:4], axis=0), axis=1) / np.diff(t)]
    if lp:
        loop = lowpass(loop, lp)
    loop = loop / (np.sqrt((loop ** 2).mean()) + 1e-9) * 0.05
    n = int((t1 - t0) * SR)
    reps = int(np.ceil(n / len(loop))) + 1
    start = RNG.integers(0, len(loop))
    sig = np.tile(loop, reps)[start:start + n]
    tt = t0 + np.arange(n) / SR
    vv = np.interp(tt, t, v)
    g = np.clip(vv / v_ref, 0, 2.0) * 10 ** (gain_db / 20)
    bus.x[:n] += sig * g
    bus.placed.append({"t": 0.0, "what": f"{label} roll loop, gain follows speed (v_ref {v_ref} m/s)"})


def dedupe(evs, gap=0.015):
    out, last = [], {}
    for e in evs:
        if e["pair"] in last and e["t_s"] - last[e["pair"]] < gap:
            continue
        last[e["pair"]] = e["t_s"]
        out.append(e)
    return out


def build(proof: str) -> tuple[np.ndarray, dict]:
    f0, f1 = FRAMES[proof]
    t0, dur = f0 / 24, (f1 - f0 + 1) / 24
    bus = Bus(dur + 1.5)
    evs = [e for e in E.read_jsonl(SIM / f"{proof}-events.jsonl") if t0 - 0.05 <= e["t_s"] <= t0 + dur]
    evs = dedupe([e for e in evs if e["v_n"] >= 0.012])
    poses = json.loads((SIM / f"{proof}-bake.json").read_text(encoding="utf-8"))["poses"]
    clay = slices(load("FS628997"), 0.22)                   # marbles knocking (clay stand-in: glass/stone, low-passed)
    drop = slices(load("FS458136"), 0.30, floor_db=-55)     # a marble dropped onto a table
    rolling = load("FS458136")
    rr = [0]
    if proof == "latch":
        coin = load("FS197214")
        stop_rec, slap_t = 19.93, 120 / 24                   # the recording's stop, placed on the slap (f120)
        a = int((stop_rec - (slap_t - t0)) * SR)
        seg = coin[a:a + int((dur + 0.6) * SR)].copy()
        k = int(0.05 * SR)
        seg[:k] *= np.linspace(0, 1, k)
        bus.add(seg / (np.abs(seg).max() + 1e-9) * 0.6, 0.0, 0.0, "FS197214 coin spin-down, stop on the slap f120")
        taps = [e for e in evs if e["pair"] == "disc|marble"]
        place_hits(bus, taps, t0, clay, 0.15, "rim tap", rr, extra_db=-14, lp=3500, ratio=0.8)
        tick = [e for e in evs if "papyrus" in e["pair"]]
        place_hits(bus, tick, t0, clay, 0.05, "papyrus edge", rr, extra_db=-6, lp=2500, ratio=0.75)
        roll(bus, poses["marble"], t0, t0 + dur, rolling[int(4.0 * SR):int(9.5 * SR)], 0.06, -24, "marble on oak", lp=3000)
    else:
        metal = slices(load("FS259553"), 0.18, min_gap_s=0.05, rise_db=9, floor_db=-50)
        type_ev = [e for e in evs if ("quad" in e["pair"] and ("galley" in e["pair"] or "quad" in e["pair"].split("|")[1]))
                   or e["pair"] in ("quad12|step",)]
        place_hits(bus, type_ev, t0, metal, 0.45, "type on brass", rr, extra_db=-4, ratio=1.5)
        stop_ev = [e for e in evs if "stop" in e["pair"] and ("galley" in e["pair"] or "leaf" in e["pair"] or "quad12" in e["pair"])]
        place_hits(bus, stop_ev, t0, metal, 0.6, "end stop", rr, extra_db=-2, ratio=1.1)
        hit = [e for e in evs if e["pair"].startswith("lead|quad") or ("pair" in e["pair"] and "stop" in e["pair"])]
        place_hits(bus, hit, t0, clay, 0.2, "clay on type", rr, extra_db=-8, lp=4000, ratio=0.8)
        drops = [e for e in evs if any(b in e["pair"] for b in ("lead", "pair1", "pair2")) and
                 any(g in e["pair"] for g in ("galley", "leaf", "ino", "shelf"))]
        place_hits(bus, drops, t0, drop, 0.12, "clay on brass and paper", rr, extra_db=-10, lp=3000)
        meet = [e for e in evs if e["pair"] == "pair1|pair2"]
        place_hits(bus, meet, t0, clay, 0.05, "clay on clay", rr, extra_db=-8, lp=4000, ratio=0.8)
        for b in ("lead", "pair1", "pair2"):
            roll(bus, poses[b], t0, t0 + dur, rolling[int(4.0 * SR):int(9.5 * SR)], 0.12, -22, f"{b} rolling", lp=2800)
    h = mat5.load(str(IR))["h_air"].ravel()
    h = h / np.abs(h).max()
    n = int(dur * SR)
    wet = fftconvolve(bus.x, h)[:n]
    wet = wet / (np.abs(wet).max() + 1e-9) * 10 ** (-4 / 20)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sr, room = wavfile.read(ROOM)
    room = room.astype(np.float64)
    if room.ndim > 1:
        room = room.mean(1)
    room = room[: len(wet)] / (np.sqrt((room ** 2).mean()) + 1e-12) * 10 ** (-48 / 20)
    out = wet.copy()
    out[: len(room)] += room
    fade = int(0.02 * SR)
    out[-fade:] *= np.linspace(1, 0, fade)
    rep = {"proof": proof, "events_used": len(evs), "placed": len(bus.placed), "peak_dbfs": round(20 * np.log10(np.abs(out).max()), 1),
           "ir": IR.name, "room": ROOM.name, "duration_s": round(n / SR, 3)}
    return out, rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proof", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    x, rep = build(a.proof)
    st = np.stack([x, x], 1)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(a.out, SR, (np.clip(st, -1, 1) * 32767).astype(np.int16))
    print(json.dumps(rep))


if __name__ == "__main__":
    main()
