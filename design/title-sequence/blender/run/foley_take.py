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
import clean as CL  # noqa: E402
import eventlog as E  # noqa: E402
import foley as FO  # noqa: E402
import mat5  # noqa: E402

SR = FO.SR
SIM = Path("D:/document-media/title-sequence/run/sim/v4")


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
    if o in ("hf_atlas1", "hf_atlas2"):
        return "wood"                          # vellum on its board: the hinge's double tick, clay on wood
    if o == "hf_piri":
        return "parchment"
    if o == "hf_ino":
        return "washi"
    if o == "hf_chart":
        return "chart"
    if o == "hf_papyrus":
        return "papyrus"
    if o.startswith(("strip", "card")):
        return "card"
    if o == "platen":
        return "rubber"
    if o == "tablet":
        return None
    return "paper"


def build(rec: str, end_frame: int = 0):
    F = B.FILMS[rec]
    dur = (end_frame + 1) / B.FPS if end_frame else B.total_frames(rec) / B.FPS
    bus = FO.Bus(dur + 2.0)
    tail_ev = SIM / f"run-tail-{rec}-events.jsonl"
    ev = E.read_jsonl(SIM / "run-events.jsonl") + (E.read_jsonl(tail_ev) if tail_ev.exists() else [])
    ev = [e for e in ev if not end_frame or e["t_s"] * B.FPS <= end_frame]
    ev = FO.dedupe(sorted([e for e in ev if e["v_n"] >= 0.010], key=lambda e: e["t_s"]))
    bake = json.loads((SIM / "run-bake.json").read_text(encoding="utf-8"))
    tp = SIM / f"run-tail-{rec}-bake.json"
    tail = json.loads(tp.read_text(encoding="utf-8")) if tp.exists() else {"meta": {}, "poses": {}}
    lay = json.loads((SIM / "run-layout.json").read_text(encoding="utf-8"))
    t_pre = B.PREFIX_FRAMES / B.FPS
    poses = {n: bake["poses"][n] + [r for r in tail["poses"].get(n, []) if r[0] > t_pre] for n in ("lead", "pair1", "pair2")}
    clay = FO.slices(FO.load("FS628997"), 0.22)
    drop = FO.slices(FO.load("FS458136"), 0.30, floor_db=-55)
    rolling = FO.load("FS458136")
    metal = FO.slices(FO.load("FS259553"), 0.18, min_gap_s=0.05, rise_db=9, floor_db=-50)
    coin = FO.load("FS197214")
    reel_rec = FO.load("FS509902")
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
    # the new surfaces of the table (v4): each a filter of the same real recordings, never a made sound
    FO.place_hits(bus, P("wood"), 0.0, clay, 0.06, "clay on wood (the Atlas's boards)", rr, extra_db=-8, lp=2600, ratio=0.72)
    FO.place_hits(bus, P("parchment"), 0.0, clay, 0.05, "clay on parchment", rr, extra_db=-9, lp=2000, ratio=0.74)
    FO.place_hits(bus, P("washi"), 0.0, clay, 0.05, "clay on washi", rr, extra_db=-12, lp=1600, ratio=0.76)
    FO.place_hits(bus, P("chart"), 0.0, clay, 0.05, "clay on chart paper", rr, extra_db=-9, lp=2400, ratio=0.75)
    FO.place_hits(bus, P("papyrus"), 0.0, clay, 0.05, "clay on papyrus", rr, extra_db=-9, lp=2200, ratio=0.74)
    FO.place_hits(bus, P("card"), 0.0, clay, 0.05, "clay on card and film stock", rr, extra_db=-10, lp=3000, ratio=0.8)
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
    # the reels: a clip on the rim, then a real spinning reel's whir (FS509902), its
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
        # the reel's whir: the spinning-reel recording's own spin-down (FS509902, CC0), its stop on the reel's settle
        env = np.convolve(np.abs(reel_rec), np.ones(SR // 50) / (SR // 50), mode="same")
        end = int(np.nonzero(env > env.max() * 0.03)[0][-1])
        seg = reel_rec[max(0, end - int((spin + 0.3) * SR)):end].copy()
        seg = FO.pitch(seg, 1.25 if "reg" in key else 1.0)
        n = len(seg)
        seg *= np.linspace(1, 0, n) ** 1.2
        bus.add(seg / (np.abs(seg).max() + 1e-9) * 0.25, t_hit, -16.0, f"{key[5:]} whir {spin:.2f} s (FS509902 spinning reel)")
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
    # no rolling loop (founder, 2026-10-17, the clean rule): between contacts there is only the room and the last
    # contact's IR tail. A clay marble rolling on paper is near silent; M1's loop was the constant noise heard.
    # the house IR as the score loads it, its tail cut at its own noise floor (clean.load_ir): no noise tail
    h, _ir = CL.load_ir()
    n = int(round(dur * SR))
    wet = fftconvolve(bus.x, h)[:n]
    wet = wet / (np.abs(wet).max() + 1e-9) * 10 ** (-4 / 20)
    # the clean rule (design section 7): the score's own room, -72 dBFS RMS, 3 kHz high cut and 60 Hz low cut, the same
    # file, loop and filter as score-tools/whole.py (clean.room_bed). The review mix is Foley plus this, nothing else.
    room = CL.room_bed(n, "the-run")
    fade = int(0.02 * SR)
    wet[-fade:] *= np.linspace(1, 0, fade)
    rep = {"record": rec, "events": len(ev), "placed": len(bus.placed), "groups": {k: len(v) for k, v in groups.items()},
           "duration_s": round(n / SR, 3), "stand_in": sorted(set(stand_in)), "ir": FO.IR.name, "ir_cut": _ir,
           "room": FO.ROOM.name, "room_dbfs": CL.C["ROOM_TONE_DBFS"]}
    return wet, room, ev, rep


def gap_rms(mix, ev, sr=SR, after=1.2, min_len=0.4):
    """The review mix's RMS (dBFS) in the stretches between events: from 1.2 s after an event (the IR's tail has
    decayed: RT60 about 0.8 s) to the next, where at least 0.4 s long, excluding rolling (any marble moving)."""
    ts = sorted(e["t_s"] for e in ev)
    segs = []
    for a, b in zip(ts, ts[1:] + [len(mix) / sr]):
        if b - (a + after) >= min_len:
            segs.append(mix[int((a + after) * sr):int(b * sr)])
    if not segs:
        return None, 0.0
    x = np.concatenate(segs)
    return round(20 * np.log10(np.sqrt((x ** 2).mean()) + 1e-20), 2), round(len(x) / sr, 2)


def write(path, x):
    st = np.stack([x, x], 1)
    wavfile.write(path, SR, (np.clip(st, -1, 1) * 32767).astype(np.int16))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", default="C20-METAR-0851")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--end-frame", type=int, default=0, help="the working stretch only")
    a = ap.parse_args()
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    wet, room, ev, rep = build(a.record, a.end_frame)
    write(out / "title.foley.wav", wet)
    write(out / "title.room.wav", room)
    mix = wet + room
    write(out / "title.review-mix.wav", mix)
    rep["gap_rms_dbfs"], rep["gap_s"] = gap_rms(mix, ev)
    rep["room_rms_dbfs"] = round(20 * np.log10(np.sqrt((room ** 2).mean())), 2)
    E.write_jsonl(ev, out / "title.events.jsonl")
    (out / "title.foley-report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps(rep))


if __name__ == "__main__":
    main()
