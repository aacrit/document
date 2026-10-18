"""GRAMMAR A44, the master frame rate per film (cinematography ticket #6; founder ruling 1 (c), 2026-10-17:
"Per film, the native rate of the majority of clip runtime. Real World masters at 30000/1001.").

A film masters at 24 (the house rate, film-era stories) or at 30000/1001 (NTSC video). ``settings.master_fps`` states
it (24, "24", "30000/1001" or "29.97"; kept exactly as a rational); a film that states nothing masters at the rate of
the majority of its clip runtime, and at 24 when it has no clips or the runtime ties. A clip at the master's rate
plays 1:1 (no frame dropped or repeated); any other clip is conformed by frame drop or repeat with no speed change
(A6), and the conform is declared: in the plan, the journal, sources.json and the ``cadence`` reviewer item.

Pure functions, no I/O: render.py probes the clips and journals what these return.
"""

from __future__ import annotations

import math
from fractions import Fraction

HOUSE = Fraction(24)                    # film-era stories and every film with no clips
NTSC = Fraction(30000, 1001)            # video: 29.97 frames a second
FILM = Fraction(24000, 1001)            # film under 3:2 pulldown, after inverse telecine (23.976)
MASTERS = (HOUSE, NTSC)
NAMES = {HOUSE: "24", NTSC: "30000/1001"}
ALIASES = {"24": HOUSE, "24/1": HOUSE, "30000/1001": NTSC, "29.97": NTSC}
FAMILY_TOL = 0.002                      # a clip within 0.2% of a master's rate (23.976 for 24, 30 for 29.97) counts for it
SAME_TOL = 0.01                         # frames a second: a clip this close to the master plays 1:1 (render.conform_plan)


class RateError(ValueError):
    pass


def parse_rate(v) -> Fraction:
    """A stated master rate as an exact rational: 24, "24", 24.0, "30000/1001", "29.97" or 29.97. Anything else
    (another rate, a bool, a malformed string) raises RateError naming what is allowed."""
    if isinstance(v, bool) or v is None:
        raise RateError(f"master_fps must be 24 or 30000/1001, not {v!r}")
    if isinstance(v, (int, float)):
        if math.isfinite(float(v)):
            if float(v) == 24.0:
                return HOUSE
            if abs(float(v) - 29.97) < 1e-9:
                return NTSC
        raise RateError(f"master_fps must be 24 or 30000/1001, not {v!r}")
    if isinstance(v, str) and v.strip() in ALIASES:
        return ALIASES[v.strip()]
    raise RateError(f"master_fps must be 24 or 30000/1001 (\"24\", \"30000/1001\" or \"29.97\"), not {v!r}")


def rate_str(r: Fraction) -> str:
    """"24" or "30000/1001": how a rate is written in sources.json, the journal and an ffmpeg argument."""
    r = Fraction(r)
    return str(r.numerator) if r.denominator == 1 else f"{r.numerator}/{r.denominator}"


def probe_rate(s: str | None) -> Fraction | None:
    """ffprobe's ``avg_frame_rate`` (or ``r_frame_rate``), "30000/1001", as a rational; None when unknown (0/0)."""
    try:
        a, b = str(s).split("/") if "/" in str(s) else (str(s), "1")
        r = Fraction(int(a), int(b))
        return r if r > 0 else None
    except (ValueError, ZeroDivisionError):
        return None


def timescale(r: Fraction) -> int:
    """The mp4 track timescale for a master rate: a whole number of ticks per frame (24 -> 24000, 1000 a frame;
    30000/1001 -> 30000, 1001 a frame), so every frame's time is exact and the master is constant frame rate."""
    r = Fraction(r)
    return r.numerator * 1000 if r.denominator == 1 else r.numerator


def native_master(rate: Fraction | float | None, telecined=None) -> Fraction | None:
    """The master a clip plays 1:1 (or nearly: within FAMILY_TOL) against: telecined video is film under 3:2
    pulldown, restored to 24 by inverse telecine; else the master within 0.2% of its rate; else None (10, 25, 59.94
    fps: no master plays it 1:1, and it does not count toward the majority)."""
    if telecined is True:
        return HOUSE
    if rate is None or float(rate) <= 0:
        return None
    for m in MASTERS:
        if abs(float(rate) - float(m)) <= FAMILY_TOL * float(m):
            return m
    return None


def majority(clips: list[dict]) -> tuple[Fraction, dict]:
    """The master rate by the majority of clip runtime: ``clips`` are {rate, runtime_s, telecined?}. Each clip's
    runtime counts for the master it plays 1:1 against (native_master); the larger total wins, a tie goes to 24 (the
    house rate), and a film with no clip that counts masters at 24. Returns (rate, tally in seconds by rate name)."""
    tally = {m: 0.0 for m in MASTERS}
    for c in clips:
        m = native_master(c.get("rate"), c.get("telecined"))
        if m is not None:
            tally[m] += max(0.0, float(c.get("runtime_s") or 0.0))
    best = max(tally.values())
    rate = NTSC if best > 0 and tally[NTSC] > tally[HOUSE] + 1e-9 else HOUSE
    return rate, {NAMES[m]: round(v, 3) for m, v in tally.items()}


def resolve(declared, clips: list[dict]) -> dict:
    """The film's master rate: the declared ``settings.master_fps`` when it parses, else the majority rule.
    {rate, name, fps (float), from: "settings" | "majority" | "house", tally, problem}."""
    rate, tally = majority(clips)
    how = "majority" if any(v > 0 for v in tally.values()) else "house"
    problem = None
    if declared is not None:
        try:
            rate, how = parse_rate(declared), "settings"
        except RateError as e:
            problem = str(e)
    return {"rate": rate, "name": rate_str(rate), "fps": float(rate), "from": how, "tally": tally, "problem": problem}


def source_index(k: int, src: Fraction | float, master: Fraction | float, n: int | None = None) -> int:
    """The source frame on output frame k of ffmpeg's fps filter, both clocks starting at 0: source frame i lands on
    output slot round(i x master / src) (to nearest, halves up), and slot k shows the latest frame that landed on or
    before it (a later one landing on the same slot replaces it: a drop; a slot nothing lands on shows the last one
    again: a repeat). round(i x r) <= k holds exactly when i < (k + 1/2) / r, so i is the largest such integer. With
    ``n``, the source's frame count, a slot past its last frame holds the last (frame n - 1)."""
    src, master = Fraction(src).limit_denominator(100000), Fraction(master).limit_denominator(100000)
    i = k if src == master else math.ceil((k + Fraction(1, 2)) * src / master) - 1
    return i if n is None or n <= 0 else min(i, n - 1)


def output_slot(i: int, src: Fraction | float, master: Fraction | float) -> int:
    """The output frame source frame i lands on (ffmpeg's fps filter, to nearest, halves up)."""
    src, master = Fraction(src).limit_denominator(100000), Fraction(master).limit_denominator(100000)
    return i if src == master else math.floor(i * master / src + Fraction(1, 2))


def source_indices(src: Fraction | float, master: Fraction | float, n_out: int, n: int | None = None) -> list[int]:
    """source_index for output frames 0 to n_out - 1 (clamped to a source of ``n`` frames)."""
    return [source_index(k, src, master, n) for k in range(n_out)]


def pattern(src: Fraction | float, master: Fraction | float, n_out: int, n: int | None = None) -> dict:
    """What a drop or repeat conform does over ``n_out`` output frames: the source frames it spans, how many it never
    shows (dropped) and how many output frames repeat the one before (repeated). A clip at the master's rate drops
    and repeats nothing."""
    if n_out <= 0:
        return {"out_frames": 0, "source_frames": 0, "dropped": 0, "repeated": 0}
    idx = source_indices(src, master, n_out, n)    # a source of n frames: never a frame past its last
    shown = len(set(idx))
    span = idx[-1] - idx[0] + 1
    return {"out_frames": n_out, "source_frames": span, "dropped": span - shown, "repeated": n_out - shown}


def frame_floor(seconds: float, master: Fraction | float) -> int:
    """Frames of the master a span of ``seconds`` covers, rounded (a 0.5 s cross-class dip is 12 frames at 24 and
    15 at 29.97: the rule is in seconds and follows the master)."""
    return int(round(seconds * float(master)))


# --------------------------------------------------------------------------
# The check: a film's resolved rate, its conformed clips and its title, read-only (no plan, no render)
# --------------------------------------------------------------------------


def check_film(film) -> dict:
    """A44 on a film folder, read-only: the master rate it resolves to (stated, or the majority of its clip runtime),
    each clip's conform at that rate, and the series titles' master (the one at the film's rate, played 1:1, else the
    item's own, conformed). Reads the screenplay, its ledgers and the clips' headers; builds no plan, so other lints
    (a score's, a framing's) never hide the answer."""
    import json
    from pathlib import Path
    from studio.engine import render as R
    from studio.engine import titles as TS
    film = Path(film)
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    assets = R.load_ledgers(film, play)
    cad = R.master_rate(play, assets)
    rate, fps = cad["rate"], cad["fps"]
    clips, titles, probes = [], [], {}

    def owned(s, dur):           # the frames the shot owns at the master rate, as the plan counts them
        t0 = float(s.get("start_s", 0.0))
        return int(round((t0 + dur) * fps)) - int(round(t0 * fps))
    for part in play.get("parts") or []:
        for s in part.get("shots") or []:
            item = assets.get(s.get("asset")) or {}
            if s.get("kind") == "archive_video" and item.get("_path") and Path(item["_path"]).exists():
                p = item["_path"]
                pr = probes[p] = probes.get(p) or R.probe_video(Path(p))
                in_s = float(s.get("in_s", item.get("in_s", 0.0)))
                out_s = float(s.get("out_s", item.get("out_s", in_s + float(s.get("dur_s", 0)))))
                conf = R.conform_plan(item, pr, rate)
                row = {"shot": s.get("id"), "asset": s.get("asset"), "in_fps": conf["in_fps"], "method": conf["method"]}
                if conf["method"] != "none":
                    src = pr["fps"] if conf["method"] != "ivtc" else FILM
                    left = int(math.floor(max(0.0, pr["duration_s"] - in_s) * float(src) + 1e-6))
                    row.update(pattern(src, rate, owned(s, out_s - in_s), left or None))
                clips.append(row)
            elif TS.is_title(s) and item:
                chosen, how = TS.select_master(item, fps)
                r = TS.rate_of(chosen)
                row = {"shot": s.get("id"), "asset": s.get("asset"), "file": chosen.get("file"),
                       "fps": chosen.get("fps", TS.FPS), "how": how}
                if how == "conform" and r:
                    row.update(pattern(r, rate, owned(s, float(s.get("dur_s", 0))),
                                       int(chosen.get("frames") or 0) or None))
                titles.append(row)
    return {"film": str(film), "master_fps": cad["name"], "from": cad["from"], "tally_s": cad["tally"],
            "problem": cad["problem"], "clips": clips, "titles": titles,
            "conformed": [c for c in clips + titles if c.get("method", "none") != "none" or c.get("how") == "conform"]}


def main(argv=None) -> int:
    """``python -m studio.engine.cadence --check <film dir> [--expect 24|30000/1001]``: print the film's resolved
    master rate, every clip's conform and the title's master as JSON; exit 1 when the rate is not the expected one
    (or the stated master_fps is malformed), 2 when the film cannot be read."""
    import argparse
    import json
    ap = argparse.ArgumentParser(prog="python -m studio.engine.cadence")
    ap.add_argument("--check", required=True, metavar="FILM_DIR")
    ap.add_argument("--expect", help="the rate the film must resolve to: 24 or 30000/1001")
    a = ap.parse_args(argv)
    try:
        want = parse_rate(a.expect) if a.expect is not None else None
        rep = check_film(a.check)
    except (OSError, ValueError, KeyError) as e:
        print(f"cadence: {type(e).__name__}: {e}")
        return 2
    print(json.dumps(rep, indent=2, ensure_ascii=False))
    bad = []
    if rep["problem"]:
        bad.append(rep["problem"])
    if want is not None and rep["master_fps"] != rate_str(want):
        bad.append(f"resolves to {rep['master_fps']}, expected {rate_str(want)}")
    for b in bad:
        print(f"cadence: MISMATCH: {b}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
