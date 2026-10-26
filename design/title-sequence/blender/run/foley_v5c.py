"""The Run v5c: Foley for the carved-channel physics proof, wired to the v5c sim's own event list (CPU only).

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/foley_v5c.py \
        --record C20-METAR-0851 --out <wav>

The marble's sound is read off the MuJoCo bake and event lists sim_v5c.py already wrote (never re-simulated here):

* D:/document-media/title-sequence/run/sim/v5c/run-timing.json ("events": the named zone changes, the two carved
  steps, the rest) -- also mirrored at layout/v5c-physics.json, same content.
* .../run-bake.json ("track": [t_s, s_m, u_m, speed_mps, z_m] at 240 Hz) for the continuous roll.
* .../run-contact-events.jsonl (sim_v5c's own E.events() onsets: {t_s, pair, v_n, impulse}) for the facet-to-facet
  grain and the felt landing.

All three share one raw-sim clock where t = 0 is the latch opening (frame 0 of final_v5c.py's render); the two
JSON files additionally carry "title_t" from an earlier release offset (rep["release_title_s"]) that no longer
matches the current shot (channel_v5c.T_RELEASE is now 0.0), so this script always uses the raw "t" / "t_s" fields,
correcting run-contact-events.jsonl's t_s by subtracting the recorded release_title_s back out. This keeps the
Foley on the same clock as final_v5c.py's frames (frame f = t * fps) without re-running the sim.

A marble rolling in an oak groove: level and pitch both follow its instantaneous speed (a variable-speed read of the
real "ball in hole" recording, so the grain rate and the loop's own pitch rise and fall together, the way a rolling
object actually sounds faster or slower -- no synthesis). Oak is bright and loudest; the leather zones are the same
roll, low-passed and quieter; the felt is low-passed hard and quiet, and -- simply because speed drives the level --
is silent once the marble is actually at rest, never before. The two carved steps get a short, soft "tok" (the house
clay recording, pitched down slightly). The facet-to-facet contact onsets add a very quiet grain on top; the one
real felt-landing contact (v_n an order of magnitude above the rest) comes through as the marble's one audible settle.
Every recording is one of the ledger's CC0 pins (design/title-sequence/run-sound-ledger.json); no synthesis, no new
downloads. The room tone is exactly the score's own (clean.room_bed: -72 dBFS RMS, 3 kHz high cut, 60 Hz low cut,
the same recording and constants as score-tools/whole.py).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import fftconvolve

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, "D:/document-media/house-room/tools")
import clean as CL  # noqa: E402
import eventlog as E  # noqa: E402
import foley as FO  # noqa: E402

SR = FO.SR
SIM = Path("D:/document-media/title-sequence/run/sim/v5c")
LAYOUT = Path("D:/document-media/title-sequence/run/layout")
ARRIVE_S = 5.0                      # final_v5c.main(): n = ceil((rest_sim_s + ARRIVE_S) * fps)

# base gain (linear) and low-pass cutoff per surface, the continuous roll: oak loudest and brightest, leather duller
# and quieter, felt duller and quieter still. The actual level at any instant is this times the speed envelope below,
# so the felt is only ever "near-silent" once the marble is actually slow or at rest, not simply by being on felt.
ZONE = {"oak": (1.0, 3500.0), "leather": (10 ** (-9 / 20), 2200.0), "felt": (10 ** (-20 / 20), 700.0)}
V_REF = 0.28                        # a mid run speed (v_max 0.34, slowest-on-the-run 0.165): the level/pitch anchor


def load_timing(record: str, timing_dir: Path = SIM) -> dict:
    p = Path(timing_dir) / "run-timing.json"
    if not p.exists() and Path(timing_dir) == SIM:
        p = LAYOUT / "v5c-physics.json"
    return json.loads(p.read_text(encoding="utf-8"))


def zone_segments(events: list[dict]) -> list[tuple[float, str]]:
    """(t, zone) at each onto-a-surface transition, raw sim seconds, "oak" first (the release block is oak)."""
    out = [(0.0, "oak")]
    for e in events:
        name = e["event"]
        if name.startswith("onto "):
            # the surface is the word after "onto": "onto leather (L8 before the felt)" is leather, not felt
            word = name[5:].split(" ")[0]
            zone = word if word in ZONE else "oak"
        elif name == "over the lip onto the felt":
            zone = "felt"
        else:
            continue
        out.append((float(e["t"]), zone))
    # drop a zone echoing the one already in force (keeps the mix free of needless filter swaps)
    dedup = [out[0]]
    for t, z in out[1:]:
        if z != dedup[-1][1]:
            dedup.append((t, z))
    return dedup


def step_events(events: list[dict]) -> list[dict]:
    return [e for e in events if e["event"].startswith("step ")]


def fix_contact_times(contacts: list[dict], release_title_s: float) -> list[dict]:
    """run-contact-events.jsonl's t_s carries sim_v5c.py's t_offset (release_title_s at generation time): subtract
    it back out so these onsets sit on the same raw-sim clock as run-timing.json's "t" and the bake's "track"."""
    out = []
    for c in contacts:
        c = dict(c)
        c["t_s"] = round(c["t_s"] - release_title_s, 4)
        out.append(c)
    return [c for c in out if c["t_s"] >= 0.0]


def speed_driven_roll(loop: np.ndarray, speed: np.ndarray, v_ref: float, sr: int) -> np.ndarray:
    """A variable-speed read of `loop`: the read pointer advances by speed/v_ref source-seconds per output sample,
    so both the grain rate and the loop's own pitch rise and fall with the marble's speed, wrapping on the loop --
    the way a real rolling recording sounds faster or slower, not a separate pitch-shift bolted onto a fixed loop."""
    rate = np.clip(speed / v_ref, 0.0, 2.2)
    src_t = np.cumsum(rate) / sr               # seconds of source consumed, monotonic
    idx = (src_t * sr) % len(loop)
    i0 = np.floor(idx).astype(np.int64)
    i1 = (i0 + 1) % len(loop)
    frac = idx - i0
    return loop[i0] * (1 - frac) + loop[i1] * frac


def speed_envelope(speed: np.ndarray, v_ref: float) -> np.ndarray:
    return np.clip(speed / v_ref, 0.0, 1.3)


def rms_dbfs(x: np.ndarray) -> float:
    r = np.sqrt(np.mean(np.asarray(x, dtype=np.float64) ** 2)) if len(x) else 0.0
    return round(float(20 * np.log10(r + 1e-20)), 1)


def build(record: str = "C20-METAR-0851", timing_dir: Path = SIM) -> tuple[np.ndarray, dict]:
    """timing_dir: where run-timing.json and run-contact-events.jsonl are read (v5d: sim/v5d, timing_v5d.py's
    corrected events, release_title_s 0); the bake is always v5c's own (the physics is unchanged)."""
    rep_sim = load_timing(record, timing_dir)
    fps = 30000 / 1001
    n_frames = math.ceil((rep_sim["rest_sim_s"] + ARRIVE_S) * fps)
    dur_s = n_frames / fps
    release_title_s = rep_sim["release_title_s"]

    bake = json.loads((SIM / "run-bake.json").read_text(encoding="utf-8"))
    track = np.array(bake["track"])                      # [t, s, u, v, z]
    T, V = track[:, 0], track[:, 3]

    contacts = fix_contact_times(E.read_jsonl(Path(timing_dir) / "run-contact-events.jsonl"), release_title_s)
    zones = zone_segments(rep_sim["events"])
    steps = step_events(rep_sim["events"])

    out_t = np.arange(0.0, dur_s, 1.0 / SR)
    speed = np.interp(out_t, T, V, left=0.0, right=0.0)

    rolling_src = FO.load("FS458136")[int(4.0 * SR):int(9.5 * SR)]
    raw = speed_driven_roll(rolling_src, speed, V_REF, SR)
    raw = raw / (np.sqrt(np.mean(raw ** 2)) + 1e-12)

    filtered = {z: FO.lowpass(raw, lp) for z, (_, lp) in ZONE.items()}
    bed = np.zeros_like(raw)
    bounds = zones + [(dur_s, None)]
    zone_spans: dict[str, list[tuple[int, int]]] = {}
    fade = int(0.03 * SR)
    for (t0, zone), (t1, _) in zip(bounds[:-1], bounds[1:]):
        i0, i1 = int(t0 * SR), min(int(t1 * SR), len(bed))
        if i1 <= i0:
            continue
        g, _ = ZONE[zone]
        seg = filtered[zone][i0:i1] * g
        if i0 > 0:
            k = min(fade, len(seg))
            seg = seg.copy()
            seg[:k] *= np.linspace(0, 1, k)
        bed[i0:i1] += seg
        zone_spans.setdefault(zone, []).append((i0, i1))
    env = speed_envelope(speed, V_REF)
    overall = 10 ** (-22 / 20)
    bed = bed * env * overall
    # the floor each zone actually contributes to the mix: the same spans, after the speed envelope and overall gain
    stem_floor = {z: rms_dbfs(np.concatenate([bed[i0:i1] for i0, i1 in spans])) for z, spans in zone_spans.items()}

    bus = FO.Bus(dur_s + 1.0)
    bus.x[:len(bed)] += bed

    clay_contact = FO.slices(FO.load("FS628997"), 0.12)
    oak_hits = [c for c in contacts if "felt" not in c["pair"]]
    felt_hits = [c for c in contacts if "felt" in c["pair"]]
    rr = [0]
    FO.place_hits(bus, [{"t_s": c["t_s"], "v_n": c["v_n"], "pair": c["pair"]} for c in oak_hits],
                  0.0, clay_contact, 0.02, "run facet grain", rr, extra_db=-26, lp=3000, ratio=0.9)
    FO.place_hits(bus, [{"t_s": c["t_s"], "v_n": c["v_n"], "pair": c["pair"]} for c in felt_hits],
                  0.0, clay_contact, 0.02, "run felt settle", rr, extra_db=-20, lp=700, ratio=0.8)

    tok_pool = FO.slices(FO.load("FS628997"), 0.18)
    tok_events = [{"t_s": e["t"], "v_n": e.get("v", V_REF), "pair": e["event"]} for e in steps]
    FO.place_hits(bus, tok_events, 0.0, tok_pool, V_REF, "carved step tok", rr, extra_db=-14, lp=2000, ratio=0.85)

    h, ir_info = CL.load_ir()
    n = len(out_t)
    wet = fftconvolve(bus.x, h)[:n]
    peak = np.abs(wet).max() + 1e-9
    wet = wet / peak * 10 ** (-4 / 20)

    room = CL.room_bed(n, "the-run-v5c")

    rep = {
        "record": record, "timing": str(Path(timing_dir) / "run-timing.json"), "frames": n_frames, "fps": "30000/1001", "duration_s": round(dur_s, 3),
        "release_title_s_corrected_for": release_title_s, "zones": [(round(t, 3), z) for t, z in zones],
        "step_events": [e["event"] for e in steps], "contacts_used": len(contacts),
        "oak_contact_hits": len(oak_hits), "felt_contact_hits": len(felt_hits),
        "ir": FO.IR.name, "ir_cut_s": ir_info["cut_s"], "ir_floor_db": ir_info["floor_db"],
        "room": FO.ROOM.name, "room_dbfs": CL.C["ROOM_TONE_DBFS"],
        "stem_floors_dbfs": {
            "bed_oak": stem_floor.get("oak", -200.0),
            "bed_leather": stem_floor.get("leather", -200.0),
            "bed_felt": stem_floor.get("felt", -200.0),
            "facet_grain": rms_dbfs(bus.x[:n] - bed[:n]),
            "room_tone": rms_dbfs(room),
            "foley_wet_peak_dbfs": round(float(20 * np.log10(np.abs(wet).max() + 1e-20)), 1),
        },
    }
    mix = wet + room
    fadeout = int(0.05 * SR)
    mix[-fadeout:] *= np.linspace(1, 0, fadeout)
    return mix, rep


def write_stereo(path: Path, x: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    st = np.stack([x, x], 1)
    wavfile.write(path, SR, (np.clip(st, -1, 1) * 32767).astype(np.int16))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", default="C20-METAR-0851")
    ap.add_argument("--out", required=True)
    ap.add_argument("--timing", default=str(SIM), help="the run-timing.json / contact events directory (v5d: sim/v5d)")
    a = ap.parse_args()
    mix, rep = build(a.record, Path(a.timing))
    out = Path(a.out)
    write_stereo(out, mix)
    (out.with_suffix(".foley-report.json")).write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps(rep))


if __name__ == "__main__":
    main()
