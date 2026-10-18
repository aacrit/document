"""The Run, the full take: the Foley from the simulation's own event list, and the house room tone as its own stem.

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/foley_take.py \
        --record C20-METAR-0851 --out-dir <dir>

Writes <dir>/title.foley.wav (the Foley, wet with the house IR, no room tone) and <dir>/title.room.wav (the house
room tone alone), 48 kHz stereo, the title's full length (prefix + tail + lockup) in title seconds, so the same
stems serve the 24 fps and the 30000/1001 masters. Every sound is a real CC0 recording from the run's sound ledger
(foley.py's rules: sliced at its own onsets, chosen by velocity layer, gain from the contact's logged speed). Where
the ledger has no recording of the exact material yet, the nearest ledgered one stands in, low-passed and pitched,
and the report names it: the reels' whirs and the palm ribs. The bronze and brass whirs are the coin recording,
its stop placed on each disc's slap (the brass one pitched for 50 mm). The felt hushes: rolling there is low-passed
and quiet. The event list is exported for the composer beside the stems (title.events.jsonl, title seconds).
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import fftconvolve

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, "D:/document-media/house-room/tools")
import bench as B  # noqa: E402
import eventlog as E  # noqa: E402
import foley as FO  # noqa: E402
import mat5  # noqa: E402

SR = FO.SR
SIM = Path("D:/document-media/title-sequence/run/sim")


def classify(pair: str) -> str | None:
    a, b = pair.split("|")[0], pair.split("|")[-1]
    names = {a, b}
    marbles = names & {"lead", "pair1", "pair2"}
    other = (names - marbles) or names
    o = sorted(other)[0]
    if len(marbles) == 2:
        return "clay-clay"
    if not marbles:
        if any(n.startswith("quad") for n in names) or "stop" in names:
            return "type"
        return None
    if o == "disc":
        return "rim"
    if o.startswith(("knot", "cord")):
        return "cord"
    if o.startswith("quad") or o == "stop":
        return "clay-type"
    if o in ("galley", "galley_ramp", "rail", "rail2", "step", "shelf"):
        return "clay-brass-galley"
    if o.startswith("reel"):
        return "reel:" + o
    if o == "ribs":
        return "rib"
    if o == "brass":
        return "brass-hit"
    if o == "felt":
        return "felt"
    if o == "record":
        return "record"
    if o in ("oak",):
        return "oak"
    if o == "platen":
        return "rubber"
    if o == "tablet":
        return None
    return "paper"


def build(rec: str):
    F = B.FILMS[rec]
    dur = B.total_frames(rec) / B.FPS
    bus = FO.Bus(dur + 2.0)
    ev = E.read_jsonl(SIM / "run-events.jsonl") + E.read_jsonl(SIM / f"run-tail-{rec}-events.jsonl")
    ev = FO.dedupe(sorted([e for e in ev if e["v_n"] >= 0.010], key=lambda e: e["t_s"]))
    bake = json.loads((SIM / "run-bake.json").read_text(encoding="utf-8"))
    tail = json.loads((SIM / f"run-tail-{rec}-bake.json").read_text(encoding="utf-8"))
    lay = json.loads((SIM / "run-layout.json").read_text(encoding="utf-8"))
    t_pre = B.PREFIX_FRAMES / B.FPS
    poses = {n: bake["poses"][n] + [r for r in tail["poses"].get(n, []) if r[0] > t_pre] for n in ("lead", "pair1", "pair2")}
    clay = FO.slices(FO.load("FS628997"), 0.22)
    drop = FO.slices(FO.load("FS458136"), 0.30, floor_db=-55)
    rolling = FO.load("FS458136")
    metal = FO.slices(FO.load("FS259553"), 0.18, min_gap_s=0.05, rise_db=9, floor_db=-50)
    coin = FO.load("FS197214")
    rr = [0]
    stand_in = []
    groups: dict[str, list] = {}
    for e in ev:
        c = classify(e["pair"])
        if c:
            groups.setdefault(c, []).append(e)
    P = lambda k: groups.get(k, [])  # noqa: E731
    FO.place_hits(bus, P("rim"), 0.0, clay, 0.15, "rim tap", rr, extra_db=-14, lp=3500, ratio=0.8)
    FO.place_hits(bus, P("paper"), 0.0, clay, 0.05, "clay on paper", rr, extra_db=-7, lp=2500, ratio=0.75)
    FO.place_hits(bus, P("oak"), 0.0, clay, 0.06, "clay on oak", rr, extra_db=-9, lp=2200, ratio=0.7)
    FO.place_hits(bus, P("cord"), 0.0, clay, 0.06, "clay on cotton cord", rr, extra_db=-10, lp=1400, ratio=0.7)
    FO.place_hits(bus, P("type"), 0.0, metal, 0.45, "type on brass", rr, extra_db=-4, ratio=1.5)
    FO.place_hits(bus, P("clay-type"), 0.0, clay, 0.2, "clay on type", rr, extra_db=-8, lp=4000, ratio=0.8)
    FO.place_hits(bus, P("clay-brass-galley"), 0.0, drop, 0.12, "clay on brass", rr, extra_db=-10, lp=3000)
    FO.place_hits(bus, P("clay-clay"), 0.0, clay, 0.05, "clay on clay", rr, extra_db=-8, lp=4000, ratio=0.8)
    FO.place_hits(bus, P("rib"), 0.0, clay, 0.05, "clay on palm rib (stand-in: marbles, low-passed)", rr, extra_db=-8,
                  lp=2600, ratio=0.9)
    FO.place_hits(bus, P("brass-hit"), 0.0, metal, 0.3, "clay on brass disc", rr, extra_db=-6, ratio=0.9)
    FO.place_hits(bus, P("record"), 0.0, clay, 0.02, "clay on the record's edge", rr, extra_db=-14, lp=2500, ratio=0.75)
    FO.place_hits(bus, P("felt"), 0.0, drop, 0.05, "felt hush", rr, extra_db=-30, lp=700)
    if P("rib"):
        stand_in.append("palm ribs: the marbles recording low-passed (no palm-rib recording in the ledger yet)")
    # the reels: a clip, then the coin recording's steady rolling stretch pitched up as a small bearing's whir, its
    # length the reel's logged spin-down
    for key in [k for k in groups if k.startswith("reel:")]:
        hits = groups[key]
        FO.place_hits(bus, hits, 0.0, metal, 0.1, f"clay on {key[5:]} rim", rr, extra_db=-10, ratio=1.2)
        rows = (bake["poses"].get(key[5:]) or [])
        t_hit = hits[0]["t_s"]
        spin = 1.6
        if rows:
            a = np.array(rows)
            ang = np.unwrap(2 * np.arctan2(a[:, 7], a[:, 4]))
            w = np.abs(np.gradient(ang, a[:, 0]))
            moving = a[(a[:, 0] > t_hit) & (w > 0.15), 0]
            spin = float(moving[-1] - t_hit) if len(moving) else 1.0
        seg = coin[int(8.0 * SR):int((8.0 + spin + 0.3) * SR)].copy()
        seg = FO.pitch(seg, 1.7 if "reg" in key else 1.35)
        n = len(seg)
        seg *= np.linspace(1, 0, n) ** 1.5
        bus.add(seg / (np.abs(seg).max() + 1e-9) * 0.25, t_hit, -16.0, f"{key[5:]} whir {spin:.2f} s (stand-in: coin recording pitched up)")
        stand_in.append(f"{key[5:]} whir: the coin recording pitched up (no bearing recording in the ledger yet)")
    # the bronze disc: the coin recording itself, its stop on the slap at f120, the whir rising from f12
    stop_rec, slap_t = 19.93, 120 / 24
    a0 = int((stop_rec - (slap_t - 0.5)) * SR)
    seg = coin[a0:a0 + int((slap_t - 0.5 + 0.8) * SR)].copy()
    k = int(0.6 * SR)
    seg[:k] *= np.linspace(0, 1, k)
    bus.add(seg / (np.abs(seg).max() + 1e-9) * 0.6, 0.5, 0.0, "FS197214 coin spin-down: bronze disc, stop on the slap f120")
    # the brass disc: pitched for 50 mm, its stop on the analytic slap
    br = lay["stations"].get("brass", {})
    if br.get("t_slap"):
        ts_ = br["t_slap"]
        whir = ts_ - br["t_land"] + 0.3
        a0 = int((stop_rec - whir) * SR)
        seg = coin[a0:int((stop_rec + 0.8) * SR)].copy()
        seg = FO.pitch(seg, 22.5 / 25.0)
        k = int(0.25 * SR)
        seg[:k] *= np.linspace(0, 1, k)
        bus.add(seg / (np.abs(seg).max() + 1e-9) * 0.7, ts_ - whir / (22.5 / 25.0), 0.0,
                "FS197214 coin spin-down pitched for the 50 mm brass disc, stop on its slap")
    # rolling: a loop per marble, gain by speed; quieter and darker on the felt
    felt_x = tail["meta"].get("felt_x", 1e9)
    loop = rolling[int(4.0 * SR):int(9.5 * SR)]
    for nm, rows in poses.items():
        if not rows:
            continue
        a = np.array(rows)
        on_felt = a[:, 1] > felt_x

        def frozen(mask):
            # positions held where the mask is false, so the loop's speed (and gain) is zero there
            b = a.copy()
            for i in range(1, len(b)):
                if not mask[i]:
                    b[i, 1:4] = b[i - 1, 1:4]
            return b.tolist()
        FO.roll(bus, frozen(~on_felt), 0.0, dur, loop, 0.12, -24, f"{nm} rolling", lp=2800)
        if on_felt.any():
            FO.roll(bus, frozen(on_felt), 0.0, dur, loop, 0.12, -40, f"{nm} on felt (hush)", lp=600)
    h = mat5.load(str(FO.IR))["h_air"].ravel()
    h = h / np.abs(h).max()
    n = int(round(dur * SR))
    wet = fftconvolve(bus.x, h)[:n]
    wet = wet / (np.abs(wet).max() + 1e-9) * 10 ** (-4 / 20)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _, room = wavfile.read(FO.ROOM)
    room = room.astype(np.float64)
    if room.ndim > 1:
        room = room.mean(1)
    reps = int(np.ceil(n / len(room)))
    room = np.tile(room, reps)[:n]
    room = room / (np.sqrt((room ** 2).mean()) + 1e-12) * 10 ** (-48 / 20)
    fade = int(0.02 * SR)
    wet[-fade:] *= np.linspace(1, 0, fade)
    rep = {"record": rec, "events": len(ev), "placed": len(bus.placed), "groups": {k: len(v) for k, v in groups.items()},
           "duration_s": round(n / SR, 3), "stand_in": sorted(set(stand_in)), "ir": FO.IR.name, "room": FO.ROOM.name}
    return wet, room, ev, rep


def write(path, x):
    st = np.stack([x, x], 1)
    wavfile.write(path, SR, (np.clip(st, -1, 1) * 32767).astype(np.int16))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", default="C20-METAR-0851")
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    wet, room, ev, rep = build(a.record)
    write(out / "title.foley.wav", wet)
    write(out / "title.room.wav", room)
    write(out / "title.review-mix.wav", wet + room)
    E.write_jsonl(ev, out / "title.events.jsonl")
    (out / "title.foley-report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps(rep))


if __name__ == "__main__":
    main()
