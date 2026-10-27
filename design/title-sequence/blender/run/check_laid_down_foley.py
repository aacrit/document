"""Laid Down: the flick-frame check. The builder's solved Foley events against the music director's, and the theme's
notes against the solved events (CPU only; no lock).

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/check_laid_down_foley.py

1. Writes the solved events (laid_down.solved_foley_events, the authority) to
   D:/document-media/title-sequence/laid-down/animatic/foley-events-solved.json, in the shape of the music director's
   theme-laid-down/foley-events-computed.json.
2. Lists every slide start (release), edge flick and settle tap that differs from theirs by more than one frame.
3. Runs the music director's own guard (series-title/compose_laid_down.py: no attack within 80 ms of a slide start,
   an edge flick with a frame of margin, or a settle tap) with its events swapped for the solved ones, without editing
   their files: their notes as written, checked against the solved times. Exit 1 if any note clashes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import laid_down as L  # noqa: E402

MD = Path("C:/Users/aacri/document-work/series-title")
THEIRS = Path("D:/document-media/title-sequence/theme-laid-down/foley-events-computed.json")
OUT = Path("D:/document-media/title-sequence/laid-down/animatic/foley-events-solved.json")
FRAME = 1 / L.FPS


def diffs(mine, theirs):
    rows = []
    for k, e in mine.items():
        t = theirs.get(k)
        if t is None:
            rows.append({"sheet": k, "what": "missing in theirs"})
            continue
        for key in ("release_s", "tap_s"):
            d = e[key] - t[key]
            rows.append({"sheet": k, "what": key, "solved": e[key], "theirs": t[key], "diff_frames": round(d / FRAME, 2)})
        mf = {u: tt for u, kind, tt in e["crossings"] if kind == "edge flick"}
        tf = {u: tt for u, kind, tt in t["crossings"] if kind == "edge flick"}
        for u in sorted(set(mf) | set(tf)):
            if u in mf and u in tf:
                rows.append({"sheet": k, "what": f"edge flick onto {u}", "solved": mf[u], "theirs": tf[u],
                             "diff_frames": round((mf[u] - tf[u]) / FRAME, 2)})
            else:
                rows.append({"sheet": k, "what": f"edge flick onto {u}", "solved": mf.get(u), "theirs": tf.get(u),
                             "diff_frames": None})
    for r in rows:
        r["over_one_frame"] = r.get("diff_frames") is None or abs(r["diff_frames"]) > 1.0
    return rows


def guard_check(events_path):
    sys.path.insert(0, str(MD))
    import compose_laid_down as CL  # their module, unchanged
    import notes as _n
    sys.modules["notes_util"] = _n
    CL.EVENTS = Path(events_path)        # their guard reads this; the solved events stand in for their own solve
    instruments = CL.V5.instruments()
    out = {}
    for rec in CL.RECORDS:
        bad, gap = CL.check_guard(CL.compose(rec), instruments, rec)
        out[rec] = {"closest_s": gap, "violations": bad}
    return out


def main():
    mine = L.solved_foley_events()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"what": "builder, laid_down.solved_foley_events (spec rev 3): Coulomb slides with the "
                                       "turn, footprints as turned rectangles, the authority", "events": mine},
                              indent=1), encoding="utf-8")
    theirs = json.loads(THEIRS.read_text(encoding="utf-8"))["events"]
    rows = diffs(mine, theirs)
    over = [r for r in rows if r["over_one_frame"]]
    rep = {"solved": str(OUT), "theirs": str(THEIRS), "over_one_frame": over, "all": rows}
    try:
        rep["guard"] = guard_check(OUT)
    except SystemExit as e:              # their compose refuses a figure note that breaks the guard
        rep["guard"] = {"refused": str(e)}
    (OUT.parent / "flick-frame-check.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    print(json.dumps({"over_one_frame": over, "guard": rep["guard"]}, indent=1, default=str))
    clash = "refused" in rep["guard"] or any(v["violations"] for v in rep["guard"].values())
    sys.exit(1 if clash else 0)


if __name__ == "__main__":
    main()
