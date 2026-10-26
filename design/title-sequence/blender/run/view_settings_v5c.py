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
    dv = document_view(doc)
    (Path(sound_master).parent / view_sidecar_name(sound_master)).write_text(json.dumps(dv, indent=1), encoding="utf-8")
    return p, doc


def view_sidecar_name(master):
    """The engine's sidecar beside the master (studio.engine.viewxf, document.view/1): <master stem>.view.json."""
    return Path(master).stem + ".view.json"


DISPLAY_KEYS = ("display_device", "gamma", "use_curve_mapping")
DEFAULTS_BASIS = ("scene_v5c.py runs Blender 4.4.3 with --factory-startup and never sets the display device, gamma or "
                  "curve mapping, so each is Blender's factory default (display_device sRGB, gamma 1.0, "
                  "use_curve_mapping off); not every render that made this master's frames read them back, so they "
                  "are stated as assumed defaults, not as measured")


def display_of(dump_docs, covers_every_frame):
    """The display device, gamma and curve mapping as Blender read them back, when every render that made the
    master's frames recorded them (covers_every_frame) and they agree; else None (the sidecar then lists them as
    defaults_assumed). A read-back that is not Blender's default is returned as it is (the engine then refuses it)."""
    if not covers_every_frame or not dump_docs or any(any(k not in d for k in DISPLAY_KEYS) for d in dump_docs):
        return None
    vals = {tuple(d[k] for k in DISPLAY_KEYS) for d in dump_docs}
    if len(vals) != 1:
        raise ValueError(f"the renders read back different display settings: {sorted(vals)}")
    (v,) = vals
    return dict(zip(DISPLAY_KEYS, v))


def document_view(doc, display=None):
    """view-settings.json in the engine's schema (document.view/1). The transform and look are one value for every
    frame or this refuses. display_device, gamma and curve mapping: the values Blender read back (``display``, from
    display_of) when every frame's render recorded them; otherwise listed in defaults_assumed with a defaults_basis
    (the engine accepts Blender's defaults only that way; it refuses a sidecar that neither records nor lists them)."""
    tl = {(f["view_transform"], f["look"]) for f in doc["frames"]}
    if len(tl) != 1:
        raise ValueError(f"more than one view transform or look across the master: {sorted(tl)}")
    (vt, look), = tl
    shown = ({k: display[k] for k in DISPLAY_KEYS} if display is not None else
             {"defaults_assumed": list(DISPLAY_KEYS), "defaults_basis": DEFAULTS_BASIS})
    return {"schema": "document.view/1", "renderer": "Blender 4.4.3", "master": doc["master"],
            "master_sha256": doc["master_sha256"], "view_transform": vt, "look": look,
            "exposure": [f["exposure"] for f in doc["frames"]], **shown,
            "recorded": {"exposure": "per frame, see view-settings.json: "
                         f"{sum(1 for f in doc['frames'] if f['recorded'] == 'blender')} read back from Blender, "
                         f"{sum(1 for f in doc['frames'] if f['recorded'] == 'keyed')} as keyed from the render's "
                         "--expo file", "view_transform_look": "read back from Blender on the frames view-settings.json marks "
                         "'blender'; on 'keyed' frames, what scene_v5c.py settings() sets (AgX, None), not logged",
                         "display": ("read back from Blender by every render that made the master's frames"
                                     if display is not None else "not read back by every render: defaults_assumed")}}


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
