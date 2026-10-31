"""Title v7: the Foley and the room (v7-beats.json foley; CPU only, no lock), from plan_v7's own clock.

Every sound is a real CC0 recording pinned by sha256 in run-sound-ledger.json (foley.load checks nothing new is
fetched; no synthesis). The spec asks for three new recordings (brass hinge, card on brass, brass sweep); none was
fetched in this build, so the nearest pinned ones stand in (a departure, logged):

* hinge  (rise start + 0.15 s): a short slice of the spinning bearing (FS376517: a metal pivot turning), low-passed,
  over a soft small-metal tick (FS259553, pitched down) at its start; level by board width;
* settle (rise end, start + 46 frames): one soft tap of card on brass: the hard-object lay-down (FS552615) low-passed,
  with a quiet paper touch (FS834340);
* the Atlas opening (f106-134): the hard folder's slide (FS388393) under the boards' swing, and its settle tap;
* the ring (f301, the meridian ring passing under the camera): the bearing's whir, very low, a 0.35 s fade in (no
  attack), 1.0 s;
* the cut (719): room tone only; the pose (1019-1079): room tone only.

The dry bus goes through the house IR (clean.load_ir) at a fixed gain, the house room tone (clean.room_bed, -72 dBFS)
runs under everything to the end of the lockup, nothing else sounds under the lockup. Every attack is checked >= 80 ms
from any music attack: before the theme exists, against the 6/8 eighth grid (1/3 s); after, against its onsets
(assemble_v7.foley_guard).
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
from scipy.signal import butter, fftconvolve, sosfiltfilt

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "run"))
import clean as CL  # noqa: E402
import foley as FO  # noqa: E402
import plan_v7 as P  # noqa: E402

SR = FO.SR
GUARD_S = 0.080
EIGHTH_S = 1.0 / 3.0
WET_GAIN_DB = -14.0
SRC = {"hinge": "FS376517", "tick": "FS259553", "settle": "FS552615", "touch": "FS834340", "open": "FS388393",
       "ring": "FS376517"}


def lp(x, hz):
    return sosfiltfilt(butter(4, min(hz, SR / 2 * 0.95), "low", fs=SR, output="sos"), x)


def hp(x, hz):
    return sosfiltfilt(butter(2, hz, "high", fs=SR, output="sos"), x)


def env(n, a_s, r_s):
    a, r = max(1, int(a_s * SR)), max(1, int(r_s * SR))
    e = np.ones(n)
    e[:min(a, n)] = 0.5 - 0.5 * np.cos(np.pi * np.arange(min(a, n)) / a)
    e[-min(r, n):] *= np.cos(0.5 * np.pi * np.arange(min(r, n)) / r) ** 2
    return e


def seg(sid, start_s, dur_s):
    x = FO.load(sid)
    a = int(start_s * SR) % max(1, len(x) - int(dur_s * SR))
    return x[a:a + int(dur_s * SR)].copy()


def loudest(sid, dur_s):
    """The loudest dur_s stretch of a recording (its active gesture)."""
    x = FO.load(sid)
    w = int(dur_s * SR)
    c = np.concatenate(([0.0], np.cumsum(x * x)))
    e = c[w:] - c[:-w]
    i = int(np.argmax(e))
    return x[i:i + w].copy()


def norm(x, peak=0.5):
    return x / (np.abs(x).max() + 1e-12) * peak


def place(bus, s, t, gain_db):
    i = int(round(t * SR))
    m = min(len(s), len(bus) - i)
    if m > 0 and i >= 0:
        bus[i:i + m] += s[:m] * 10 ** (gain_db / 20)


def guard_from_grid(t, grid=EIGHTH_S, guard=GUARD_S):
    """The distance (s) from t to the nearest eighth of the 6/8 grid."""
    k = round(t / grid)
    return abs(t - k * grid)


def events():
    """Foley attacks (s): hinge and settle per board, the Atlas opening and its settle, the ring."""
    ev = []
    for b in P.BOARDS:
        s = b["rise"] / P.FPS
        w = P.RECORDS[b["id"]]["size"][0]
        ev.append({"t": round(s + 0.15, 4), "kind": "hinge", "board": b["id"], "gain_db": -3.0 + 6 * (w - 0.5)})
        ev.append({"t": round(s + P.RISE_FRAMES / P.FPS, 4), "kind": "settle", "board": b["id"], "gain_db": -6.0})
    a, z = P.board("T-03")["open"]
    ev.append({"t": round(a / P.FPS - 0.02, 4), "kind": "open", "board": "T-03", "gain_db": -10.0})
    ev.append({"t": round(z / P.FPS, 4), "kind": "open settle", "board": "T-03", "gain_db": -9.0})
    ev.append({"t": round(9.79, 4), "kind": "ring", "board": None, "gain_db": -24.0,
               "note": "the meridian ring passes under the camera at f301 (10.04 s); a swell, no attack"})
    for e in ev:
        e["grid_guard_ms"] = round(1000 * guard_from_grid(e["t"]), 1)
    return sorted(ev, key=lambda e: e["t"])


def build(lockup_s=P.LOCKUP_S, room_tone=True):
    rng = np.random.default_rng(20261031)
    shot_s = P.FRAMES / P.FPS
    n_shot = int(round(shot_s * SR))
    n = n_shot + int(round(lockup_s * SR))
    bus = np.zeros(n)
    hinge = lp(loudest(SRC["hinge"], 0.45), 2500.0)
    tick = lp(FO.pitch(loudest(SRC["tick"], 0.08), 0.7), 4000.0)
    settle = lp(loudest(SRC["settle"], 0.30), 2000.0)
    touch = lp(loudest(SRC["touch"], 0.15), 3500.0)
    opening = lp(hp(loudest(SRC["open"], 0.95), 150.0), 3000.0)
    ring = lp(seg(SRC["ring"], 1.3, 1.0), 1800.0)
    evs = events()
    for e in evs:
        g = e["gain_db"]
        if e["kind"] == "hinge":
            place(bus, norm(hinge * env(len(hinge), 0.01, 0.15)), e["t"], g)
            place(bus, norm(tick * env(len(tick), 0.002, 0.03)), e["t"], g - 8.0)
        elif e["kind"] == "settle":
            place(bus, norm(settle * env(len(settle), 0.002, 0.12)), e["t"], g)
            place(bus, norm(touch * env(len(touch), 0.002, 0.06)), e["t"] + 0.01, g - 10.0)
        elif e["kind"] == "open":
            place(bus, norm(opening * env(len(opening), 0.08, 0.25)), e["t"], g)
        elif e["kind"] == "open settle":
            place(bus, norm(settle * env(len(settle), 0.002, 0.10)), e["t"], g)
        elif e["kind"] == "ring":
            place(bus, norm(ring * env(len(ring), 0.35, 0.45)), e["t"], g)
    bus[n_shot:] = 0.0
    h, ir = CL.load_ir()
    wet = fftconvolve(bus, h)[:n]
    wet[n_shot:] = 0.0                                  # the IR's tail is cut at the lockup's cut, as the picture is
    wet *= 10 ** (WET_GAIN_DB / 20)
    room = CL.room_bed(n, "the-record-stands") if room_tone else np.zeros(n)
    mix = wet + room
    fade = int(0.05 * SR)
    mix[-fade:] *= np.linspace(1, 0, fade)
    rep = {"sr": SR, "shot_s": round(shot_s, 4), "lockup_s": lockup_s, "events": evs,
           "sources": SRC, "ir": {"file": str(CL.IR), **ir}, "room_dbfs": CL.C["ROOM_TONE_DBFS"],
           "wet_gain_db": WET_GAIN_DB, "wet_peak_dbfs": round(20 * math.log10(np.abs(wet).max() + 1e-20), 2),
           "min_grid_guard_ms": min(e["grid_guard_ms"] for e in evs if e["kind"] != "ring"),
           "departure": "no new brass recordings fetched: pinned CC0 stand-ins (bearing for the hinge and ring, "
                        "small-metal fall for the brass tick, hard-object lay-down for card on brass)"}
    return mix, wet, room, rep


def write_stereo(path, x):
    from scipy.io import wavfile
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(path, SR, (np.clip(np.stack([x, x], 1), -1, 1) * 32767).astype(np.int16))


def write_events(path):
    """The Foley attacks for the music director's guard check (compose_v7.py --foley-events)."""
    ev = events()
    doc = {"fps": "30000/1001", "guard_ms": GUARD_S * 1000, "source": "foley_v7.events (t/title-v7)",
           "events": [{"t_s": e["t"], "frame": round(e["t"] * P.FPS, 2), "kind": e["kind"], "board": e["board"],
                       "attack": e["kind"] != "ring"} for e in ev]}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return doc


if __name__ == "__main__":
    if "--events" in sys.argv:
        print(json.dumps(write_events(sys.argv[sys.argv.index("--events") + 1]), indent=1))
        sys.exit(0)
    mix, wet, room, rep = build()
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("D:/document-media/title-sequence/v7/work/foley.wav")
    write_stereo(out, mix)
    out.with_suffix(".json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("wet_peak_dbfs", "min_grid_guard_ms")}),
          [(e["kind"], e["t"], e["grid_guard_ms"]) for e in rep["events"]])
