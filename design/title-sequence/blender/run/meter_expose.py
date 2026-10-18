"""The Run v4: the camera's own auto-exposure (founder, 2026-10-18: one constant lamp, real camera exposure).

    blender -b <take.blend> --python design/title-sequence/blender/run/meter_expose.py -- <f0> <f1> <meter dir> <curve.json>

Renders a meter pass of every frame at 96 x 54 (8 samples, linear EXR), takes each frame's mean log luminance (the
camera's metering: the frame's middle 80%, scene-linear), and keys the film exposure (Colour Management exposure, in
stops) so the metered level holds at the latch's own (the reference: its frames f60-f110 at exposure 0, the approved
look). The meter responds as a real camera's does: a causal exponential with a 0.7 s time constant, clamped to
+-3 stops. Nothing else changes: the lamp is fixed and constant. Saves the take with the keys and writes the curve.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:]
F0, F1, MDIR, CURVE = int(argv[0]), int(argv[1]), Path(argv[2]), Path(argv[3])
TAU, CLAMP = 0.7, 3.0
REF = (60, 110)

sc = bpy.context.scene
fps = sc.render.fps / sc.render.fps_base
keep = (sc.render.resolution_x, sc.render.resolution_y, sc.cycles.samples, sc.render.image_settings.file_format,
        sc.render.image_settings.color_depth, sc.render.use_motion_blur, sc.cycles.use_denoising)
sc.render.resolution_x, sc.render.resolution_y = 96, 54
sc.cycles.samples = 8
sc.cycles.use_denoising = False
sc.cycles.use_preview_denoising = False
sc.render.use_motion_blur = False
sc.render.image_settings.file_format = "OPEN_EXR"
sc.render.image_settings.color_depth = "32"
sc.view_settings.exposure = 0.0
MDIR.mkdir(parents=True, exist_ok=True)
lum = {}
for f in range(F0, F1 + 1):
    sc.frame_set(f)
    p = MDIR / f"{f:04d}.exr"
    sc.render.filepath = str(p)
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(str(p), check_existing=False)
    w, h = img.size
    a = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)[..., :3]
    bpy.data.images.remove(img)
    y0, y1, x0, x1 = int(0.1 * h), int(0.9 * h), int(0.1 * w), int(0.9 * w)
    Y = 0.2126 * a[y0:y1, x0:x1, 0] + 0.7152 * a[y0:y1, x0:x1, 1] + 0.0722 * a[y0:y1, x0:x1, 2]
    lum[f] = float(np.exp(np.mean(np.log(np.maximum(Y, 1e-5)))))
ref = float(np.exp(np.mean([math.log(lum[f]) for f in range(max(F0, REF[0]), min(F1, REF[1]) + 1)])))
ev, curve, e = {}, [], None
for f in range(F0, F1 + 1):
    want = max(-CLAMP, min(CLAMP, math.log2(ref / max(lum[f], 1e-6))))
    e = want if e is None else e + (want - e) * (1 - math.exp(-1 / (fps * TAU)))
    ev[f] = e
    curve.append({"frame": f, "metered": lum[f], "exposure_ev": round(e, 3)})
(sc.render.resolution_x, sc.render.resolution_y, sc.cycles.samples, sc.render.image_settings.file_format,
 sc.render.image_settings.color_depth, sc.render.use_motion_blur, sc.cycles.use_denoising) = keep
for f, v in ev.items():
    sc.view_settings.exposure = v
    sc.view_settings.keyframe_insert("exposure", frame=f)
bpy.ops.wm.save_mainfile()
vals = list(ev.values())
CURVE.write_text(json.dumps({"tau_s": TAU, "clamp_ev": CLAMP, "reference_frames": REF, "ref_luminance": ref,
                             "range_ev": [round(min(vals), 3), round(max(vals), 3)], "curve": curve}), encoding="utf-8")
print("EXPOSURE " + json.dumps({"range_ev": [round(min(vals), 3), round(max(vals), 3)], "frames": len(vals)}))
