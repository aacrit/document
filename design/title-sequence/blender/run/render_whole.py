"""The Run v4.1: the whole shot as one 480p calib animatic, no denoiser (founder rulings 2026-10-18).

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/render_whole.py --tag <tag>
        [--record C20-METAR-0851] [--res 854x480]

One physics run (sim_run.py's bake: the prefix and the film's tail), one camera over the whole shot (plan_camera.py
--whole), the constant lamp and the camera's own exposure (meter_expose.py), rendered in chunks under HEAVY.lock with
the machine checked before each heavy step; then the Foley and room (-72 dBFS), the assembly ending on the record's pose,
and A7 on the last frame against the record's scan at the pose.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[3]))
import bench as B  # noqa: E402
import camera_run as CR  # noqa: E402
import render_run as RR  # noqa: E402
import render_take as RT  # noqa: E402


def a7(frame_png: Path, rec: str) -> dict:
    """record_difference (studio.engine.titles, A7) of the last frame against the record's scan at the A7 window."""
    import numpy as np
    from PIL import Image
    from studio.engine import titles as TT
    tb = json.loads((RR.MEDIA / "sim" / "v4" / f"run-tail-{rec}-bake.json").read_text(encoding="utf-8"))
    rmeta = tb["meta"]["record"]
    _, frac = CR.a7_window(rmeta)
    man = json.loads(Path("D:/document-media/title-sequence/chart/tex-manifest.json").read_text(encoding="utf-8"))
    path = man[B.FILMS[rec]["tex"]]["tex"]["file"]
    arr = np.asarray(Image.open(frame_png).convert("RGB").resize((1920, 1080), Image.LANCZOS))
    win = [frac[0], frac[1], frac[2], frac[3]]
    return {"a7": round(float(TT.record_difference(arr, path, win)), 3),
            "edge_strips": round(float(TT.pose_edge_difference(arr, path, win)), 3), "window": win}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--record", default="C20-METAR-0851")
    ap.add_argument("--res", default="854x480")
    a = ap.parse_args()
    rec, tag = a.record, a.tag
    F = B.FILMS[rec]
    last = B.PREFIX_FRAMES - 1 + F["tail"][0] + F["tail"][1] + F["tail"][2]
    blend_dir = RR.MEDIA / "blend" / tag
    blend_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    dirs = {}
    for window in ("prefix", "tail"):
        bp = blend_dir / f"{window}-24.blend"
        info = RT.build(window, rec, "24", True, bp, a.res)
        f0, f1 = info["frames"]
        ok, why = RR.machine_ok()
        if not ok:
            sys.exit(f"machine short before the meter: {why}")
        out[f"exposure_{window}"] = RT.expose(bp, f0, f1, f"{tag}-{window}")
        d = RR.MEDIA / "frames" / tag / window
        out[f"render_{window}"] = RT.render_chunks(bp, d, f0, f1, f"{tag}-{window}")
        dirs[window] = d
        out[f"renderer_{window}"] = info.get("renderer")
    snd = RR.MEDIA / "masters" / tag
    r = subprocess.run([RR.VPY, str(HERE / "foley_take.py"), "--record", rec, "--out-dir", str(snd), "--end-frame", str(last)],
                       capture_output=True, text=True, cwd=RR.REPO, env=RR.d_env())
    out["foley"] = (r.stdout.strip().splitlines() or [""])[-1][:1500]
    if r.returncode:
        sys.exit("foley failed: " + r.stderr[-2000:])
    mp4 = snd / f"the-run-{tag}-{rec}-24.mp4"
    r = subprocess.run([RR.VPY, str(HERE / "assemble_take.py"), "--record", rec, "--fps", "24", "--size", a.res,
                        "--prefix", str(dirs["prefix"]), "--tail", str(dirs["tail"]), "--audio", str(snd / "title.review-mix.wav"),
                        "--mp4", str(mp4), "--keep", str(RR.MEDIA / "frames" / tag / "comp"), "--end-frame", str(last),
                        "--renderer", out.get("renderer_tail") or ""],
                       capture_output=True, text=True, cwd=RR.REPO, env=RR.d_env())
    if r.returncode:
        sys.exit("assemble failed: " + r.stderr[-2000:])
    out["a7"] = a7(dirs["tail"] / f"{last:04d}.png", rec)
    out["mp4"] = str(mp4)
    out["runtime_s"] = round((last + 1) / 24, 2)
    (snd / "whole-report.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print("WHOLE " + json.dumps({k: out[k] for k in ("mp4", "runtime_s", "a7")}))


if __name__ == "__main__":
    main()
