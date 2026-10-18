"""The Run v4: plan the camera from the bake and measure it (runs in the D: venv).

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/plan_camera.py [--films ...]

Writes D:/document-media/title-sequence/run/sim/v4/camera-prefix.json (shared by every film) and camera-<record>.json
(the prefix rows unchanged up to f935, then the tail), each with ticket 5's measures: the pan guide per beat at 24 and
at 30000/1001 (the frame's centre, which the limiter holds, and a 3 x 3 ground grid), the lead marble's in-frame share
on beats 2-3, the brass disc's through its settle, the whole table in the f935 frame with its margins, and in each tail
whether the record fills the close's last frame with no felt in it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bench as B  # noqa: E402
import camera_run as CR  # noqa: E402

SIM = Path("D:/document-media/title-sequence/run/sim/v4")


def in_frame_share(rows, track, f0, f1, margin=0.0):
    n = k = 0
    for f in range(f0, f1 + 1):
        t = f / 24
        if not track or t < track[0][0] or t > track[-1][0]:
            continue
        p = CR.interp_track(track, t)
        n += 1
        k += CR.in_frame(CR.at(rows, t), p, -margin)
    return round(k / n, 3) if n else None


def table_margins(rows, f):
    """The table's four corners in the frame at frame f, as fractions of the frame inside each side (positive inside)."""
    r = CR.at(rows, f / 24)
    W, H = B.TABLE["size"]
    pts = [CR.project(r, (x, y, 0.0)) for x, y in ((0, 0), (W, 0), (W, H), (0, H))]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return {"left": round(min(xs) / 1920, 3), "right": round(1 - max(xs) / 1920, 3), "top": round(min(ys) / 1080, 3),
            "bottom": round(1 - max(ys) / 1080, 3)}


def record_fills(rows, f, rec):
    """At frame f: the four frame corners land on the record (no felt in the frame)."""
    r = CR.at(rows, f / 24)
    ok = True
    for px, py in ((0, 0), (1920, 0), (0, 1080), (1920, 1080)):
        g = CR.ray_to_bench(r, px, py, z=rec["z"])
        ok &= g is not None and rec["x0"] <= g[0] <= rec["x0"] + rec["W"] and abs(g[1] - rec["y"]) <= rec["H"] / 2
    return bool(ok)


def pan_report(rows, f_end, extra=()):
    out = {}
    for fps, key in ((24.0, "24"), (30000 / 1001, "2997")):
        m = CR.beat_maxima(rows, f_end, fps=fps, extra=extra)
        out[key] = m
    return out


def guide_met(pan, exempt=("2-3 papyrus, hinge (exempt)",)):
    """The guide (11 px and 6 px a frame at 24p, 24p-equivalent at 29.97) on the frame's centre, every beat but the
    exemption."""
    bad = []
    for key, beats in pan.items():
        for b in beats:
            if b["beat"] in exempt or b["beat"].startswith("0 "):
                continue
            if b["centre_x"] > 11.0 or b["centre_y"] > 6.0:
                bad.append((key, b["beat"], b["centre_x"], b["centre_y"]))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--films", default="C20-METAR-0851,S-130,S-16928")
    ap.add_argument("--until-frame", type=int, default=0, help="the working stretch only (milestone A, reduced)")
    ap.add_argument("--whole", action="store_true", help="one film: plan the camera once over prefix and tail")
    a = ap.parse_args()
    f_end = a.until_frame or 935
    bake = json.loads((SIM / "run-bake.json").read_text(encoding="utf-8"))
    lay = json.loads((SIM / "run-layout.json").read_text(encoding="utf-8"))
    P = bake["poses"]
    t_pre = B.PREFIX_FRAMES / B.FPS
    pre = CR.plan(P, lay, t_end=(f_end + 12) / 24 if a.until_frame else t_pre + 0.5)
    f_end = min(f_end, B.PREFIX_FRAMES - 1)
    pan = pan_report(pre, f_end)
    ck = lay.get("checks", {})
    br = lay["stations"].get("brass", {})
    f_settle = (int(br.get("frame_land", 866)), min(int(br.get("frame_slap", 926)) + 6, 935))
    meas = {"pan": pan, "guide_violations": guide_met(pan),
            "lead_in_frame_beats_2_3": in_frame_share(pre, P["lead"], 180, 330),
            "lead_in_frame_note": "from f180: the approved latch lets the marble leave frame right at f167; the crane rises to catch it",
            "turns": ck.get("turns")}
    if not a.until_frame:
        meas["brass_in_frame_settle"] = in_frame_share(pre, P.get("brass", []), *f_settle)
        meas["table_margins_f935"] = table_margins(pre, B.PREFIX_FRAMES - 1)
        meas["wide_ok"] = all(v >= 0.05 for v in meas["table_margins_f935"].values())
    shares = {}
    for name, f0, f1 in CR.BEATS[2:]:
        if f0 <= f_end:
            shares[name] = in_frame_share(pre, P["lead"], max(f0, 121), min(f1, f_end))
    if a.until_frame:
        (SIM / "camera-prefix.json").write_text(json.dumps({"rows": pre, "measures": {**meas, "lead_in_frame_by_beat": shares}}),
                                                encoding="utf-8")
        print("WARP U1", (ck.get("turns") or [{}])[0].get("frame"), "quad1", lay["stations"].get("galley", {}).get("t_quad1"))
        print("STRETCH " + json.dumps({k: v for k, v in {**meas, "lead_in_frame_by_beat": shares}.items() if k != "pan"}))
        for b in pan["24"]:
            print("  24p", b)
        return
    meas["lead_in_frame_by_beat"] = shares
    (SIM / "camera-prefix.json").write_text(json.dumps({"rows": pre, "measures": meas}), encoding="utf-8")
    print("PREFIX " + json.dumps({k: v for k, v in meas.items() if k != "pan"}))
    for b in pan["24"]:
        print("  24p", b)
    for rec in [r for r in a.films.split(",") if r]:
        p = SIM / f"run-tail-{rec}-bake.json"
        if not p.exists():
            continue
        tb = json.loads(p.read_text(encoding="utf-8"))
        F = B.FILMS[rec]
        fa, fd, fc = F["tail"][0], F["tail"][1], F["tail"][2]
        t_end = (B.PREFIX_FRAMES + fa + fd + fc) / B.FPS + 0.5
        rows = CR.plan(P, lay, tail={"poses": tb["poses"], "record": tb["meta"]["record"], "windows": F["tail"]},
                       t_end=t_end)
        if a.whole:
            # one film, one camera over the whole shot (the animatic): no seam at the prefix's end
            out = rows
            (SIM / "camera-prefix.json").write_text(json.dumps({"rows": rows, "measures": meas}), encoding="utf-8")
        else:
            # the prefix is shared: up to its end the rows are the prefix's own
            out = [r for r in pre if r["t"] < t_pre] + [r for r in rows if r["t"] >= t_pre]
        P0 = B.PREFIX_FRAMES
        extra = [("13 find", P0, P0 - 1 + fa), ("14 descend", P0 + fa, P0 - 1 + fa + fd),
                 ("15 close", P0 + fa + fd, P0 - 1 + fa + fd + fc)]
        tpan = pan_report(out, P0 - 1 + fa + fd + fc, extra=extra)
        tpan = {k: [b for b in v if b["beat"][:2] in ("13", "14", "15")] for k, v in tpan.items()}
        last = P0 - 1 + fa + fd + fc
        tm = {"pan": tpan, "guide_violations": guide_met(tpan, exempt=("14 descend", "15 close")),
              "record_fills_close_end": record_fills(out, last, tb["meta"]["record"]),
              "marbles_in_frame_find": in_frame_share(out, P["lead"] + [r for r in tb["poses"]["lead"] if r[0] > t_pre],
                                                      P0, P0 - 1 + fa)}
        (SIM / f"camera-{rec}.json").write_text(json.dumps({"rows": out, "measures": tm}), encoding="utf-8")
        print("TAIL", rec, json.dumps({k: v for k, v in tm.items() if k != "pan"}), json.dumps(tpan["24"]))


if __name__ == "__main__":
    main()
