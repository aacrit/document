"""The Run v5c: view-settings.json beside a film's master, the camera every one of its frames was rendered through.

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/view_settings_v5c.py \
        --record S-130

A40 like for like binds a title's declared view_transform to the render. A master is spliced from two renders: the
shared prefix (final-v5c/frames-2560, final_v5c.py, keyed from final-v5c/exposure.json) and the film's own tail
(<record>/tail-2560, tail_v5c.py, keyed from <record>/exposure.json). Each frame's entry says where its values come
from, and nothing is reconstructed:

- "blender": read back from the scene as Blender evaluated it at that frame (scene_v5c.py --vs, from 2026-10-26).
- "keyed": the exposure is the value the render keyed at that frame (the --expo file it was given, still on disk);
  the view transform and look are what scene_v5c.py's settings() sets (AgX, None, the same at every commit of the
  file); Blender did not log them at render time.

Schema (provisional until the engine names it): {master, master_sha256, frames: [{frame, view_transform, look,
exposure, recorded}], recorded: {legend}, sources: {...}}.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

SCENE_VIEW = {"view_transform": "AgX", "look": "None"}     # scene_v5c.settings(), unchanged since 1957e83
LEGEND = {"blender": "read back from the scene as Blender evaluated it at that frame (scene_v5c.py --vs)",
          "keyed": "exposure: the value the render keyed at that frame (its --expo file); view transform and look: "
                   "scene_v5c.py settings() (AgX, None), not logged by Blender at render time"}


def frames(n, redo, tail_ev, base_ev, dumps):
    """One entry per master frame. redo: the frames from the film's tail; dumps: {frame: Blender's read-back} for tail
    frames rendered with --vs. A read-back that disagrees with the keyed exposure is an error, not a choice."""
    out = []
    for f in range(n):
        d = dumps.get(f) if f in redo else None
        if d is not None and not d.get("skipped_existing"):
            if abs(d["exposure"] - tail_ev[f]) > 1e-5:
                raise ValueError(f"frame {f}: Blender read back exposure {d['exposure']} against the keyed {tail_ev[f]}")
            out.append({"frame": f, "view_transform": d["view_transform"], "look": d["look"],
                        "exposure": d["exposure"], "recorded": "blender"})
        else:
            ev = tail_ev[f] if f in redo else base_ev[f]
            out.append({"frame": f, **SCENE_VIEW, "exposure": round(float(ev), 6), "recorded": "keyed"})
    return out


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def load_dumps(rec_dir):
    out = {}
    for p in sorted(Path(rec_dir).glob("view-settings-*.blender.json")):
        for d in json.loads(p.read_text(encoding="utf-8"))["frames"]:
            out[d["frame"]] = d
    return out


def write(rec, redo, n, rec_dir, base_dir, sound_master):
    tail_ev = json.loads((Path(rec_dir) / "exposure.json").read_text(encoding="utf-8"))["ev"]
    base_ev = json.loads((Path(base_dir) / "exposure.json").read_text(encoding="utf-8"))["ev"]
    fr = frames(n, set(redo), tail_ev, base_ev, load_dumps(rec_dir))
    doc = {"record": rec, "master": Path(sound_master).name, "master_sha256": sha256(sound_master), "frames": fr,
           "recorded": LEGEND,
           "sources": {"prefix": str(Path(base_dir) / "exposure.json"), "tail": str(Path(rec_dir) / "exposure.json"),
                       "tail_frames": len(redo), "blender_read_back": sum(1 for f in fr if f["recorded"] == "blender")}}
    p = Path(rec_dir) / "view-settings.json"
    p.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return p, doc


def main(argv=None):
    import tail_v5c as T
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", required=True)
    a = ap.parse_args(argv)
    rec = a.record
    rec_dir = T.BASE / rec
    T.LOG = rec_dir / "tail.log"
    rep_sim = json.loads((T.MEDIA / "sim" / "v5c" / "run-timing.json").read_text(encoding="utf-8"))
    bake = json.loads((T.MEDIA / "sim" / "v5c" / "run-bake.json").read_text(encoding="utf-8"))
    meter = json.loads((T.BASE / "exposure.json").read_text(encoding="utf-8"))["ev"]
    P = T.plan(rec, bake, rep_sim["rest_sim_s"], meter)
    keyed = json.loads((rec_dir / "exposure.json").read_text(encoding="utf-8"))["ev"]
    if max(abs(a - b) for a, b in zip(keyed, P["ev"])) > 1e-9 or len(keyed) != P["n"]:
        raise SystemExit(f"{rec}/exposure.json is not this plan's exposure: the tail was keyed from something else")
    p, doc = write(rec, P["redo"], P["n"], rec_dir, T.BASE, rec_dir / f"the-run-v5c-{rec}-2997-sound.mov")
    k = P["k_from"]
    print(json.dumps({"wrote": str(p), "master_sha256": doc["master_sha256"], "pose": doc["frames"][k],
                      "last": doc["frames"][-1], "blender_read_back": doc["sources"]["blender_read_back"]}))


if __name__ == "__main__":
    main()
