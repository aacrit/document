"""A46 the automatic black floor (founder ruling 4, cinematography ticket #11).

    python -m studio.engine.levels --check <film dir> [--json <file>]

The founder, 2026-10-17: "Black floor: AUTOMATED ... Apply the linear
black-floor automatically to every still over the threshold (p2 > 24). White,
gamma and hue stay untouched. Log each applied floor in the ledger as
non-material. A still whose fade is the artifact can opt out per still with
`levels: none` and a stated reason. `grade-jump` stays guidance."

The measure. Luma is Rec.709 on the 8-bit code values, in integers so it is
exact and the same on every machine: ``Y = (54 R + 183 G + 19 B + 128) >> 8``
(the weights sum to 256, so a grey pixel's luma is its own value). A
percentile is the nearest rank on a 256-bin histogram: ``p_q`` is the
smallest level whose cumulative count reaches ``ceil(q / 100 * N)``. The
threshold reads luma p2; the black point reads ``min0_5``, the 0.5th
percentile of each pixel's darkest channel ``min(R, G, B)``, so at most about
0.5% of pixels reach 0 in any channel (a black point from luma would clip a
sepia shadow's blue channel and turn its hue).

The map. One affine map on the code values, the same for R, G and B::

    out = 10 + (c - black_in) * k,   k = 245 / (255 - black_in)

rounded half up and clipped to 0..255, applied as one 256-entry table. It
sends ``black_in`` to 10/255 and 255 to 255 (the white point stays) and is one
straight line (no gamma bend). What it does to colour, exactly: the three
channels share the offset and the gain, so the differences between them are
all multiplied by ``k``. Contrast and colour strength (chroma, saturation) rise
by that factor; the hue angle of a pixel no channel clips is kept up to the
8-bit rounding, so a sepia stays a sepia. ``k`` is at most ``LEVELS_MAX_GAIN``
(1.35, so ``black_in`` at most 73): a paler scan would be stretched, not
floored, a grade rather than a level, and is shown as held and journaled
("pale scan, left as held"; founder ruling, 2026-10-17). A map on luma alone with the chroma
kept moves a pixel off the line through its own colour in RGB and can leave
gamut in the darks; per-channel black points would neutralise a cast, which is
a grade, not a floor.

Who gets it. An archive still (``kind: archive_still``) marked ARCHIVE or
RECONSTRUCTED: a RECONSTRUCTED still is still a scan of a real photograph, its
named alteration (an upscale, say) is apart from its black level, and a flat
level is not material under GRAMMAR 4.2, so it adds no alteration and is
logged like an ARCHIVE one. Never a clip, a card, a map or picture the studio
drew (DRAWN), an AI-GENERATED picture, or the series titles. A still whose
ledger item says ``levels: "none"`` (with ``levels_reason``) is shown as held.
A still with luma p2 at or under 24 is untouched; one whose ``min0_5`` is
already at or under 10 is untouched too (the floor never lifts a black), and so
is a pale scan whose gain would pass ``LEVELS_MAX_GAIN``.

Where. Once, in the source-still prep (``render.Pictures.still``), on the
full-resolution scan before the Lanczos pre-scale and ``fit_still``; the A7
pixel check applies it to its reference the same way. The plan carries the
parameters on the shot (``_levels``), so the segment cache key (which hashes
the shot and ``VERSION``) changes with them.

The record. Every archive still the film shows is written to the ledger's
overlay ``<ledger stem>.levels.json`` beside the ledger (film data, never in
git; the human ledger is never rewritten): its sha256, measurements, the floor
applied or why none, and the materiality. It is also the measurement cache,
keyed by (sha256, ``VERSION``): the first machine's decode of the file is
what gets cached (a JPEG decode can differ by a level between library builds),
and the same numbers are reused after it. The overlay is written atomically.
Stills never floored (DRAWN, or otherwise not eligible) are measured and cached
there too, for ``grade-jump``. Each applied floor is journaled as a decision
and printed in sources.json's ``levels`` for the shot (the Sources page states
it).

``grade-jump`` (guidance): at a cut or dissolve between two stills, a luma p2
delta over 20 after the floors is a warning, so a jump from a milky scan to a
deep one is seen before it is shipped.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import uuid
from pathlib import Path

import numpy as np
from PIL import Image

VERSION = 2                 # bump when the measure, the map or the rules change: old segments are not reused
P2_MAX = 24                 # a still whose luma p2 is above this (8-bit) is floored
BLACK_OUT = 10              # the black point (min-channel p0.5) goes here (10/255)
LEVELS_MAX_GAIN = 1.35      # founder ruling 2026-10-17: past this gain a floor is a grade; the scan is left as held
WHITE = 255                 # the white point stays
GRADE_JUMP = 20             # grade-jump: a p2 delta across a cut above this warns
ELIGIBLE_KIND = "archive_still"
ELIGIBLE_MARKS = ("ARCHIVE", "RECONSTRUCTED")
MATERIALITY = "non-material (GRAMMAR 4.2: a level adjustment, one straight line the same on every channel; A46)"
WHAT = ("black level set: the scan's grey floor taken down to near black by one straight-line level, the same on "
        "every colour, which raises contrast and colour strength by the same small factor; the white point kept")
PALE_WHY = "pale scan, left as held"     # founder ruling 2026-10-17: past the cap a floor would be a grade
RECONSTRUCTED_WHY = ("a RECONSTRUCTED still is still a scan of a real photograph; its named alteration is apart from "
                     "its black level, and a flat level adds no alteration (GRAMMAR 4.2)")
SIDECAR_SUFFIX = ".levels.json"


# --------------------------------------------------------------------------
# Pure: measure, map, decide
# --------------------------------------------------------------------------


def luma_u8(arr: np.ndarray) -> np.ndarray:
    """Rec.709 luma of an RGB uint8 array, exact in integers (weights 54, 183, 19 of 256)."""
    a = arr.astype(np.uint32)
    return ((54 * a[..., 0] + 183 * a[..., 1] + 19 * a[..., 2] + 128) >> 8).astype(np.uint8)


def percentile(hist: np.ndarray, q: float) -> int:
    """Nearest-rank percentile of a 256-bin histogram: the smallest level whose cumulative count reaches q%."""
    n = int(hist.sum())
    rank = max(1, math.ceil(q / 100.0 * n))
    return int(np.searchsorted(np.cumsum(hist), rank))


def measure(img: Image.Image) -> dict:
    """The still's luma p0.5, p2, p50 and p98, and ``min0_5``, the 0.5th percentile of min(R, G, B) (8-bit)."""
    arr = np.asarray(img.convert("RGB"))
    hist = np.bincount(luma_u8(arr).ravel(), minlength=256)
    mins = np.bincount(arr.min(axis=-1).ravel(), minlength=256)
    return {"p0_5": percentile(hist, 0.5), "p2": percentile(hist, 2), "p50": percentile(hist, 50),
            "p98": percentile(hist, 98), "min0_5": percentile(mins, 0.5)}


def gain(black_in: int) -> float:
    """The map's slope k for a black point."""
    return (WHITE - BLACK_OUT) / (WHITE - black_in)


def why_not(m: dict) -> str | None:
    """Why a measurement gets no floor, or None when it gets one."""
    if m["p2"] <= P2_MAX:
        return f"p2 {m['p2']} is at or under {P2_MAX}"
    if m["min0_5"] <= BLACK_OUT:
        return f"the darkest channel's p0.5 {m['min0_5']} is already at or under {BLACK_OUT}"
    if m["min0_5"] >= WHITE or gain(m["min0_5"]) > LEVELS_MAX_GAIN:
        return f"{PALE_WHY} (black point {m['min0_5']}, gain over {LEVELS_MAX_GAIN})"
    return None


def floor_params(m: dict) -> dict | None:
    """The floor a measurement asks for, or None (see ``why_not``)."""
    if why_not(m) is not None:
        return None
    return {"black_in": m["min0_5"], "black_out": BLACK_OUT, "white": WHITE, "gain": round(gain(m["min0_5"]), 4)}


def lut(params: dict) -> list[int]:
    """The 256-entry table: black_in -> black_out, white -> white, a straight line between, rounded half up."""
    b, o, w = params["black_in"], params["black_out"], params["white"]
    c = np.arange(256, dtype=np.float64)
    v = np.floor(o + (c - b) * (w - o) / (w - b) + 0.5)
    return [int(x) for x in np.clip(v, 0, 255)]


def apply(img: Image.Image, levels: dict | None) -> Image.Image:
    """The floor on an RGB image (the same table on R, G and B), or the image itself when none is applied."""
    if not levels or not levels.get("applied"):
        return img
    t = lut(levels)
    return img.convert("RGB").point(t * 3)


def eligible(shot: dict, item: dict | None) -> tuple[bool, str]:
    """Whether a shot's picture may be floored at all, and why not."""
    kind, mark = shot.get("kind"), shot.get("mark")
    if kind != ELIGIBLE_KIND:
        what = {"archive_video": "a clip", "card": "a card", "black": "black", "drawn": "drawn by the studio",
                "title_sequence": "the series titles", "generated": "AI-GENERATED"}.get(kind, f"a {kind} shot")
        return False, f"never floored: {what}"
    if mark not in ELIGIBLE_MARKS:
        return False, f"never floored: marked {mark}"
    if not item or not item.get("_path"):
        return False, "no picture file"
    return True, RECONSTRUCTED_WHY if mark == "RECONSTRUCTED" else "an archive still"


def decide(shot: dict, item: dict, m: dict, after: dict | None) -> dict:
    """The shot's ``_levels`` record from its item and measurement (``after``: the floored still's measurement)."""
    base = {"version": VERSION, "p0_5": m["p0_5"], "p2": m["p2"], "min0_5": m["min0_5"]}
    if item.get("levels") == "none":
        return {**base, "applied": False, "opt_out": True, "reason": item.get("levels_reason")}
    fp = floor_params(m)
    if fp is None:
        why = why_not(m)
        return {**base, "applied": False, "why": why, **({"pale": True} if why.startswith(PALE_WHY) else {})}
    rec = {**base, "applied": True, **fp, "p2_after": (after or {}).get("p2"), "what": WHAT, "materiality": MATERIALITY}
    if shot.get("mark") == "RECONSTRUCTED":
        rec["why_reconstructed"] = RECONSTRUCTED_WHY
    return rec


def p2_shown(shot: dict, m: dict | None) -> int | None:
    """The p2 the viewer sees: after the floor when one is applied."""
    lv = shot.get("_levels") or {}
    if lv.get("applied"):
        return lv.get("p2_after")
    return lv.get("p2") if lv else (m or {}).get("p2")


def grade_jumps(shots: list[dict], p2_of: dict) -> list[dict]:
    """grade-jump: each cut or dissolve between two measured stills, with the p2 on each side (after floors)."""
    out = []
    for a, b in zip(shots, shots[1:]):
        if (b.get("transition_in") or {}).get("type", "cut") not in ("cut", "dissolve"):
            continue
        pa, pb = p2_of.get(a["id"]), p2_of.get(b["id"])
        if pa is None or pb is None:
            continue
        out.append({"from": a["id"], "to": b["id"], "p2_from": pa, "p2_to": pb, "delta": abs(pa - pb),
                    "warn": abs(pa - pb) > GRADE_JUMP})
    return out


# --------------------------------------------------------------------------
# I/O at the edges: the overlay (cache and record), the plan, the check
# --------------------------------------------------------------------------


def sidecar_path(ledger_file: str | Path) -> Path:
    p = Path(ledger_file)
    return p.with_name(p.stem + SIDECAR_SUFFIX)


def read_sidecar(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("version") != VERSION:
        return {}
    return data.get("items") or {}


def measured(item: dict, cache: dict, *, floor: bool = True) -> tuple[dict, dict | None, str]:
    """The item's measurement and the floored still's (None when no floor, or ``floor`` is false), from the
    cache keyed by (sha256, VERSION), else measured from the file."""
    from studio.engine.journal import sha256_file
    sha = sha256_file(item["_path"])
    hit = cache.get(item["id"])
    if hit and hit.get("sha256") == sha and hit.get("version") == VERSION and "measure" in hit:
        return hit["measure"], hit.get("measure_after"), sha
    with Image.open(item["_path"]) as im:
        img = im.convert("RGB")
    m = measure(img)
    fp = floor_params(m) if floor else None
    after = measure(apply(img, {"applied": True, **fp})) if fp else None
    return m, after, sha


def assess(shots: list[dict], item_of) -> tuple[dict, dict]:
    """Every shot's ``_levels`` (set on eligible shots) and the overlay entries by ledger file.
    ``item_of(shot)`` gives the shot's ledger item (with ``_path``, ``_ledger_file``)."""
    caches: dict[str, dict] = {}
    overlay: dict[str, dict] = {}
    p2_of: dict[str, int] = {}
    for s in shots:
        item = item_of(s)
        ok, why = eligible(s, item)
        if not ok and not (s.get("kind") in ("archive_still", "drawn") and item and item.get("_path")):
            continue
        lf = item.get("_ledger_file") or ""
        cache = caches.setdefault(lf, read_sidecar(sidecar_path(lf)) if lf else {})
        if not ok:                                          # measured as held, for grade-jump only, cached alike
            m, _, sha = measured(item, cache, floor=False)
            p2_of[s["id"]] = m["p2"]
            overlay.setdefault(lf, {})[item["id"]] = {"version": VERSION, "sha256": sha, "file": item.get("file"),
                                                      "measure": m, "measure_after": None, "applied": False,
                                                      "why": why}
            continue
        m, after, sha = measured(item, cache)
        rec = decide(s, item, m, after)
        s["_levels"] = rec
        p2_of[s["id"]] = rec["p2_after"] if rec["applied"] else rec["p2"]
        entry = {"version": VERSION, "sha256": sha, "file": item.get("file"), "measure": m, "measure_after": after,
                 **{k: rec[k] for k in ("applied", "black_in", "black_out", "white", "gain", "p2_after", "what",
                                        "materiality", "opt_out", "reason", "why", "pale", "why_reconstructed")
                    if k in rec}}
        overlay.setdefault(lf, {})[item["id"]] = entry
    return p2_of, overlay


def write_overlays(overlay: dict) -> list[str]:
    """Each ledger's overlay beside it, rewritten only when its content changes (deterministic, sorted)."""
    written = []
    for lf, items in overlay.items():
        if not lf:
            continue
        path = sidecar_path(lf)
        doc = {"version": VERSION, "ledger": Path(lf).name,
               "note": ("A46 automatic black floor: a ledger overlay written by studio.engine.levels; the human "
                        "ledger is never rewritten. Each applied floor is non-material (GRAMMAR 4.2)."),
               "items": dict(sorted(items.items()))}
        text = json.dumps(doc, indent=1, sort_keys=False, ensure_ascii=False) + "\n"
        tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            if path.exists() and path.read_text(encoding="utf-8") == text:
                continue
            tmp.write_text(text, encoding="utf-8", newline="")   # LF only: byte-identical across OSes (no CRLF translation)
            os.replace(tmp, path)                           # atomic: a reader never sees half an overlay
            written.append(str(path))
        except OSError:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            continue
    return written


def plan_levels(shots: list[dict], journal, *, write: bool = True) -> list[dict]:
    """build_plan's step: set each eligible still's ``_levels``, write the ledger overlays, journal each floor as a
    decision (non-material) and each grade jump as a warning. Returns the grade jumps."""
    p2_of, overlay = assess(shots, lambda s: s.get("_item"))
    if write:
        write_overlays(overlay)
    for s in shots:
        lv = s.get("_levels")
        if lv and lv.get("applied"):
            journal.decision("motion", f"{s['id']}: black floor {lv['black_in']} -> {lv['black_out']}, gain {lv['gain']} "
                             f"(p2 {lv['p2']} -> {lv['p2_after']})", f"A46 (founder ruling 4): {MATERIALITY}",
                             unit=s["id"], levels=lv)
        elif lv and lv.get("pale"):
            journal.decision("motion", f"{s['id']}: {PALE_WHY}", f"A46: {lv['why']}", unit=s["id"])
        elif lv and lv.get("opt_out"):
            journal.decision("motion", f"{s['id']}: shown as held (levels: none, p2 {lv['p2']})",
                             f"A46: {lv.get('reason')}", unit=s["id"])
    jumps = grade_jumps(shots, p2_of)
    for j in jumps:
        journal.lint("grade-jump", not j["warn"], stage="motion", unit=j["to"], severity="warn", grammar="A46",
                     phase="preflight", evidence={**j, "limit": GRADE_JUMP,
                                                  "fix": None if not j["warn"] else
                                                  "guidance: reorder, dip, or accept; the floor already ran"})
    return jumps


def check(film: Path | str) -> dict:
    """Read-only: what the floor does to a film, from its screenplay and ledgers, without planning it."""
    from studio.engine import render as R
    film = Path(film).resolve()
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    assets = R.load_ledgers(film, play)
    shots = [dict(sh) for part in play["parts"] for sh in part.get("shots", [])]
    p2_of, _ = assess(shots, lambda s: assets.get(s.get("asset")))
    floored, opt_out, untouched = [], [], []
    for s in shots:
        lv = s.get("_levels")
        if not lv:
            continue
        row = {"shot": s["id"], "id": s.get("asset"), "p0_5": lv["p0_5"], "min0_5": lv["min0_5"], "p2": lv["p2"]}
        if lv.get("applied"):
            floored.append({**row, "p2_after": lv["p2_after"], "black_in": lv["black_in"], "gain": lv["gain"]})
        elif lv.get("opt_out"):
            opt_out.append({**row, "reason": lv.get("reason")})
        else:
            untouched.append({**row, "why": lv.get("why")})
    jumps = grade_jumps(shots, p2_of)
    return {"film": str(film), "version": VERSION, "threshold_p2": P2_MAX, "max_gain": LEVELS_MAX_GAIN, "floored": floored, "opt_out": opt_out,
            "untouched": untouched, "grade_jumps": [j for j in jumps if j["warn"]], "cuts_measured": len(jumps)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m studio.engine.levels", description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", metavar="FILM", required=True, help="report the black floor on a film, read-only")
    ap.add_argument("--json", metavar="FILE", help="also write the report as JSON")
    a = ap.parse_args(argv)
    rep = check(a.check)
    if a.json:
        Path(a.json).write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(f"levels v{rep['version']} on {rep['film']} (floor when p2 > {rep['threshold_p2']}, gain at most "
          f"{rep['max_gain']})")
    print(f"floored ({len(rep['floored'])}):")
    for r in rep["floored"]:
        print(f"  {r['shot']:>6} {r['id']}: p0.5 {r['p0_5']}, black point (min-channel p0.5) {r['black_in']}, "
              f"gain {r['gain']}, p2 {r['p2']} -> {r['p2_after']}")
    print(f"opted out ({len(rep['opt_out'])}):")
    for r in rep["opt_out"]:
        print(f"  {r['shot']:>6} {r['id']}: p0.5 {r['p0_5']}, p2 {r['p2']} ({r['reason']})")
    print(f"untouched ({len(rep['untouched'])}):")
    for r in rep["untouched"]:
        print(f"  {r['shot']:>6} {r['id']}: p0.5 {r['p0_5']}, p2 {r['p2']} ({r['why']})")
    print(f"grade-jump warnings ({len(rep['grade_jumps'])} of {rep['cuts_measured']} still-to-still cuts):")
    for j in rep["grade_jumps"]:
        print(f"  {j['from']} -> {j['to']}: p2 {j['p2_from']} -> {j['p2_to']} (delta {j['delta']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
