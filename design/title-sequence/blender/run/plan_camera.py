"""The Run: plan the camera from the bake and measure it against the pan guide (runs in the D: venv).

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/plan_camera.py [--films ...]

Writes D:/document-media/title-sequence/run/sim/camera-prefix.json (shared by every film) and camera-<record>.json
(the prefix rows unchanged up to f935, then the tail), each with the measured pan-speed maxima per beat at 24 fps and,
for the record, at 30000/1001; and whether the leading marble is in frame, per beat.
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

SIM = Path("D:/document-media/title-sequence/run/sim")


def in_frame_share(rows, poses, f0, f1):
    names = ["lead", "pair1", "pair2"]
    n = k = 0
    for f in range(f0, f1 + 1):
        t = f / 24
        fr = CR.front_track(poses, names, [t])[0]
        if fr is None:
            continue
        n += 1
        k += CR.in_frame(CR.at(rows, t), fr)
    return round(k / n, 3) if n else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--films", default="C20-METAR-0851,S-130,S-16928")
    a = ap.parse_args()
    bake = json.loads((SIM / "run-bake.json").read_text(encoding="utf-8"))
    lay = json.loads((SIM / "run-layout.json").read_text(encoding="utf-8"))
    P = bake["poses"]
    t_pre = B.PREFIX_FRAMES / B.FPS
    pre = CR.plan(P, lay, t_end=t_pre + 0.5)
    pan = CR.beat_maxima(pre, 935)
    pan_ntsc = CR.beat_maxima(pre, 935, fps=30000 / 1001)
    share = {b[0]: in_frame_share(pre, P, max(b[1], 121), b[2]) for b in CR.BEATS[2:]}
    (SIM / "camera-prefix.json").write_text(json.dumps({"rows": pre, "pan_24": pan, "pan_2997": pan_ntsc,
                                                        "front_in_frame": share}), encoding="utf-8")
    print("prefix pan (24p px/frame):")
    for r in pan:
        print("  ", r)
    print("front marble in frame:", share)
    for rec in [r for r in a.films.split(",") if r]:
        p = SIM / f"run-tail-{rec}-bake.json"
        if not p.exists():
            continue
        tb = json.loads(p.read_text(encoding="utf-8"))
        F = B.FILMS[rec]
        t_end = (B.PREFIX_FRAMES + F["tail"][0] + F["tail"][1]) / B.FPS + 0.5
        rows = CR.plan(P, lay, tail={"poses": tb["poses"], "record": tb["meta"]["record"], "windows": F["tail"]},
                       t_end=t_end)
        # the prefix is shared: up to f935 the rows are the prefix's own; after it the tail's, eased onto them
        ts = np.array([r["t"] for r in rows])
        j = int(np.searchsorted(ts, t_pre))
        p_end = CR.at(pre, t_pre)
        d_eye = np.array(p_end["eye"]) - np.array(rows[j]["eye"])
        d_tgt = np.array(p_end["target"]) - np.array(rows[j]["target"])
        out = [r for r in pre if r["t"] < t_pre]
        for r in rows[j:]:
            u = CR.smoothstep((r["t"] - t_pre) / 1.5)
            r = dict(r)
            r["eye"] = (np.array(r["eye"]) + d_eye * (1 - u)).tolist()
            r["target"] = (np.array(r["target"]) + d_tgt * (1 - u)).tolist()
            out.append(r)
        a_, c_ = F["tail"][0], F["tail"][1]
        extra = [("13 approach", 936, 936 + a_ - 1), ("14 close", 936 + a_, 936 + a_ + c_ - 1)]
        tpan = CR.beat_maxima(out, 936 + a_ + c_ - 1, extra=extra)[-2:]
        tpan_n = CR.beat_maxima(out, 936 + a_ + c_ - 1, fps=30000 / 1001, extra=extra)[-2:]
        Pt = {n: P[n] + [r for r in tb["poses"].get(n, []) if r[0] > P[n][-1][0]] for n in ("lead", "pair1", "pair2")}
        (SIM / f"camera-{rec}.json").write_text(json.dumps({"rows": out, "pan_24": pan + tpan, "pan_2997": pan_ntsc + tpan_n,
                                                            "front_in_frame_approach": in_frame_share(out, Pt, 936, 936 + a_ - 1)}),
                                                encoding="utf-8")
        print(rec, "tail pan:", tpan)


if __name__ == "__main__":
    main()
