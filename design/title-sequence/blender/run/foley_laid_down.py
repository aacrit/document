"""Laid Down: the Foley (spec rev 3, section 6), from the closed-form slides in laid_down.py (CPU only; no lock).

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/foley_laid_down.py \
        --record C20-METAR-0851 --out <wav> [--lockup-s 6.0]

Three events per sheet, all from real CC0 recordings pinned in run-sound-ledger.json (fetch_run_sounds.py; no
synthesis), and all placed from laid_down's own clock (nothing simulated here):

* the slide: a loop of the material pair's recording (its active gestures joined, high-passed at 120 Hz against
  handling rumble), read at a rate within 3 percent of its own (faster as the sheet is faster), its level following the
  speed (20 log10(v / v_ref)) and its brightness falling with it (a crossfade between three low-passed reads). The
  speed is laid_down.audio_speed: up under the unseen push from 0.2 s before the sheet is seen, then Coulomb's linear
  fall to zero, so every sheet is heard before it is seen and its sound ends exactly at its stop;
* the edge: one flick (a short tap slice, high-passed) at laid_down.edge_crossing_s, where the leading edge first rides
  onto the pile, its level by the speed there; the Atlas, sliding on bare oak, has none;
* the settle: one soft tap at laid_down.settle_tap_s (0.25 s after the stop; the Atlas boards' 1 mm drop lands in 0.1 s,
  a hard object laid on wood).

Material pairs (rev 3 has six; the spec's "seven" counted the papyrus): the Atlas boards on oak, the leaf on vellum,
parchment on vellum, washi on parchment, the chart on washi, the record on the chart. The dry bus is convolved with the
house IR (clean.load_ir), normalised to a peak of PEAK_DBFS, and the house room tone (clean.room_bed: -72 dBFS RMS,
60 Hz to 3 kHz) runs under the whole title and on under the lockup; nothing else is under the lockup.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, fftconvolve, sosfiltfilt

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import clean as CL  # noqa: E402
import foley as FO  # noqa: E402
import laid_down as L  # noqa: E402

SR = FO.SR
V_REF = 1.6                                  # m/s: a mid entry speed (entries 1.5-2.3)
PEAK_DBFS = -10.0                            # the wet Foley's peak: headroom for the theme on top
LP_BANDS = (1200.0, 3200.0, 9000.0)          # the slide's brightness, slow to fast
HP_HZ = 120.0
PITCH_SPAN = 0.03                            # the read rate stays within 3 percent of the recording's own

# per pair: the recording, the stretch of it used (s), gain (dB) and a brightness ceiling (Hz)
PAIRS = {
    "S2": {"pair": "Atlas boards on oak", "src": "FS451411", "span": (0.0, 40.0), "gain_db": 0.0, "ceil": 3000.0},
    "S3": {"pair": "leaf on vellum", "src": "FS46631", "span": (0.0, 19.4), "gain_db": -3.0, "ceil": 9000.0},
    "S4": {"pair": "parchment on vellum", "src": "FS451411", "span": (40.0, 92.0), "gain_db": -1.0, "ceil": 5000.0},
    "S5": {"pair": "washi on parchment", "src": "FS464302", "span": (0.0, 1.6), "gain_db": -5.0, "ceil": 9000.0},
    "S6": {"pair": "chart on washi", "src": "FS46631", "span": (0.0, 19.4), "gain_db": -1.0, "ceil": 6500.0},
    "R": {"pair": "record on chart", "src": "FS730078", "span": (0.0, 0.8), "gain_db": -4.0, "ceil": 6500.0},
}
# one-shots are normalised to a 0.5 peak; the slide loop to RMS 1 (its peaks near +12 dB). The edge comes as the slide
# is loudest (just after entry), so the flick is set at the slide's peak level to cut through it; the settle tap is
# soft but clear of the slide's reverb tail (measured in the report)
FLICK = {"src": "FS834340", "gain_db": 15.0, "hp": 1500.0}
TAP = {"src": "FS834340", "gain_db": 0.0, "lp": 3000.0}
BOARD_TAP = {"src": "FS552615", "gain_db": 2.0, "lp": 2000.0}


def hp(x, hz):
    return sosfiltfilt(butter(4, hz, "high", fs=SR, output="sos"), x)


def lp(x, hz):
    return sosfiltfilt(butter(4, min(hz, SR / 2 * 0.95), "low", fs=SR, output="sos"), x)


def active_loop(x, floor_db=-50.0, fade_s=0.02):
    """The recording's active gestures (20 ms envelope over floor_db), joined end to end with short crossfades, as a
    loop: the silences and the room between gestures are left out, so the loop is all slide."""
    hop = int(0.02 * SR)
    n = len(x) // hop
    e = 20 * np.log10(np.sqrt(np.mean(x[:n * hop].reshape(n, hop) ** 2, axis=1)) + 1e-12)
    on = e > floor_db
    segs, i = [], 0
    while i < n:
        if on[i]:
            j = i
            while j < n and on[j]:
                j += 1
            if j - i >= 5:                       # at least 0.1 s
                segs.append(x[i * hop:j * hop])
            i = j
        else:
            i += 1
    k = int(fade_s * SR)
    out = segs[0].copy()
    for s in segs[1:]:
        if len(s) <= 2 * k or len(out) <= 2 * k:
            continue
        w = np.linspace(0, 1, k)
        out[-k:] = out[-k:] * (1 - w) + s[:k] * w
        out = np.concatenate([out, s[k:]])
    out = hp(out, HP_HZ)
    return out / (np.sqrt(np.mean(out ** 2)) + 1e-12)


def read_at(loop, rate, offset):
    """Read the loop at a time-varying rate (samples of source per output sample), wrapping."""
    pos = offset + np.cumsum(rate)
    idx = pos % len(loop)
    i0 = np.floor(idx).astype(np.int64)
    i1 = (i0 + 1) % len(loop)
    f = idx - i0
    return loop[i0] * (1 - f) + loop[i1] * f


def slide(s, pid, n, rng):
    """One sheet's slide over the whole timeline (zero outside its push and slide)."""
    P = PAIRS[pid]
    x = FO.load(P["src"])
    a, b = (int(P["span"][0] * SR), int(min(P["span"][1] * SR, len(x))))
    loop = active_loop(x[a:b])
    t = np.arange(n) / SR
    t0, t1 = L.push_start_s(s), s["stop_s"]
    i0, i1 = max(0, int(t0 * SR) - 1), min(n, int(math.ceil(t1 * SR)) + 1)
    v = np.array([L.audio_speed(s, tt) for tt in t[i0:i1]])
    vmax = max(s["v_release_m_s"], 1e-6)
    rate = 1.0 + PITCH_SPAN * np.clip(2 * v / vmax - 1, -1, 1)
    raw = read_at(loop, rate, rng.integers(0, len(loop)))
    bands = [lp(raw, min(f, P["ceil"])) for f in LP_BANDS]
    u = np.clip(v / vmax, 0, 1) * (len(bands) - 1)
    k = np.clip(np.floor(u).astype(int), 0, len(bands) - 2)
    w = u - k
    stack = np.stack(bands)
    bright = stack[k, np.arange(len(u))] * (1 - w) + stack[k + 1, np.arange(len(u))] * w
    gain = np.clip(v / V_REF, 0, 1.4) * 10 ** (P["gain_db"] / 20)
    out = np.zeros(n)
    out[i0:i1] = bright * gain
    return out, {"pair": P["pair"], "src": P["src"], "heard_s": round(t0, 3), "seen_s": s["enter_s"],
                 "lead_s": round(s["enter_s"] - t0, 3), "stop_s": s["stop_s"]}


def one_shot(pool, level, rng):
    s = pool[int(np.clip(round(level * (len(pool) - 1)), 0, len(pool) - 1))]
    s = FO.pitch(s, 1 + rng.uniform(-0.03, 0.03))
    return s / (np.abs(s).max() + 1e-9) * 0.5


def place(bus, s, t, gain_db):
    i = int(round(t * SR))
    m = min(len(s), len(bus) - i)
    if m > 0 and i >= 0:
        bus[i:i + m] += s[:m] * 10 ** (gain_db / 20)


def build(record="C20-METAR-0851", lockup_s=6.0, room_tone=True):
    rng = np.random.default_rng(20261026)
    shot_s = L.FRAMES / L.FPS
    n_shot = int(round(shot_s * SR))
    n = n_shot + int(round(lockup_s * SR))
    bus = np.zeros(n)
    taps = FO.slices(FO.load(TAP["src"]), 0.12)
    flicks = [hp(s, FLICK["hp"]) for s in FO.slices(FO.load(FLICK["src"]), 0.06)]
    board = FO.slices(FO.load(BOARD_TAP["src"]), 0.3, floor_db=-60.0) or [FO.load(BOARD_TAP["src"])[:int(0.3 * SR)]]
    events = []
    sheets = [(s["id"], s) for s in L.SHEETS] + [("R", L.RECORDS[record])]
    for pid, s in sheets:
        sl, info = slide(s, pid, n_shot, rng)
        bus[:n_shot] += sl
        ev = {"sheet": s["id"] if pid != "R" else f"R {record}", **info}
        te = L.edge_crossing_s(s)
        if te is not None:
            v = L.audio_speed(s, te)
            g = FLICK["gain_db"] + float(np.clip(20 * np.log10(v / V_REF + 1e-9), -12, 3))
            place(bus, one_shot(flicks, 0.75, rng), te, g)      # one firm layer; its level is the speed's
            ev["edge_s"], ev["edge_speed_m_s"] = round(te, 3), round(v, 3)
        tt = L.settle_tap_s(s)
        if L.is_board(s):
            place(bus, lp(one_shot(board, 0.3, rng), BOARD_TAP["lp"]), tt, BOARD_TAP["gain_db"])
        else:
            place(bus, lp(one_shot(taps, 0.2, rng), TAP["lp"]), tt, TAP["gain_db"])
        ev["settle_tap_s"] = round(tt, 3)
        events.append(ev)
    bus[n_shot:] = 0.0                              # nothing under the lockup
    h, ir = CL.load_ir()
    wet = fftconvolve(bus, h)[:n]
    wet[n_shot:] = 0.0                              # the IR's tail is cut at the cut, as the picture is
    peak = np.abs(wet).max() + 1e-12
    wet *= 10 ** (PEAK_DBFS / 20) / peak
    room = CL.room_bed(n, "laid-down") if room_tone else np.zeros(n)
    mix = wet + room
    # what is heard when: the wet slide's onset per sheet against its entry (20 ms frames, 6 dB over the room)
    rep = {"record": record, "shot_s": round(shot_s, 3), "lockup_s": lockup_s, "sr": SR, "events": events,
           "peak_dbfs": PEAK_DBFS, "room_dbfs": CL.C["ROOM_TONE_DBFS"], "ir": str(CL.IR), "ir_cut_s": ir.get("cut_s"),
           "pairs": {k: {kk: vv for kk, vv in v.items() if kk != "span"} | {"span_s": list(v["span"])}
                     for k, v in PAIRS.items()},
           "stillness_wet_peak_dbfs": None}
    a, b = (int(L.t_of(f) * SR) for f in L.BEATS["stillness"]["frames"])
    quiet_from = int((events[-2]["settle_tap_s"] + 0.6) * SR)
    seg = wet[max(a, quiet_from):int(events[-1]["heard_s"] * SR)]
    rep["stillness_wet_peak_dbfs"] = round(float(20 * np.log10(np.abs(seg).max() + 1e-20)), 1) if len(seg) else None
    fade = int(0.05 * SR)
    mix[-fade:] *= np.linspace(1, 0, fade)
    return mix, rep


def write_stereo(path, x):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(path, SR, (np.clip(np.stack([x, x], 1), -1, 1) * 32767).astype(np.int16))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", default="C20-METAR-0851")
    ap.add_argument("--out", required=True)
    ap.add_argument("--lockup-s", type=float, default=6.0)
    a = ap.parse_args()
    mix, rep = build(a.record, a.lockup_s)
    write_stereo(a.out, mix)
    Path(a.out).with_suffix(".foley-report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("shot_s", "stillness_wet_peak_dbfs")}),
          *[f"\n{e['sheet']}: heard {e['heard_s']} seen {e['seen_s']} lead {e['lead_s']} edge {e.get('edge_s')} "
            f"stop {e['stop_s']} tap {e['settle_tap_s']}" for e in rep["events"]])


if __name__ == "__main__":
    main()
