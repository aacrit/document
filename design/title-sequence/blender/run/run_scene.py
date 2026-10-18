"""The Run: build the two proof scenes in Blender from the MuJoCo bakes. Nobody hand-edits the .blend.

    blender -b --factory-startup --python design/title-sequence/blender/run/run_scene.py -- --proof latch
    blender -b --factory-startup --python design/title-sequence/blender/run/run_scene.py -- --proof galley

Every moving body is keyed from its simulation at 240 Hz (tenth-frame keys, linear), so the 180-degree shutter
blurs between true poses. Real scale in metres; 50 mm on a 36 mm sensor, depth of field true. One bone lamp on the
camera arm (4300 K, white-balanced at 5200 K as in Chart) with a 60 cm bounce card; a dark grey environment for
lighting only (camera rays see black); no HDRI. Images come only from the pinned manifests: v1's tex-manifest
(T-01 Umma register, T-02a Turin papyrus, T-06 Gutenberg leaf, T-08 Ino) and Chart's (C-02 oak planks). The bronze
disc, brass, type metal and clay are procedural shaders. The bench's 0.8 degree fall lives in the simulation's
gravity; the bench is drawn level (the fall is invisible at this scale).
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
TS = HERE.parents[1]
sys.path.insert(0, str(HERE))
import moffatt as MF  # noqa: E402

TITLE = json.loads((HERE.parent / "title.json").read_text(encoding="utf-8"))
SIM = Path("D:/document-media/title-sequence/run/sim")
MAN_V1 = json.loads(Path("D:/document-media/title-sequence/tex-manifest.json").read_text(encoding="utf-8"))
MAN_C = json.loads(Path("D:/document-media/title-sequence/chart/tex-manifest.json").read_text(encoding="utf-8"))
LEDGER_V1 = json.loads((TS / "assets-ledger.json").read_text(encoding="utf-8"))
LEDGER_C = json.loads((TS / "chart-assets-ledger.json").read_text(encoding="utf-8"))
FPS = 24
FRAMES = {"latch": (96, 167), "galley": (456, 527)}


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    a = {"proof": "latch", "profile": "proof", "out": "", "calib": ""}
    for i, k in enumerate(argv):
        if k.startswith("--") and i + 1 < len(argv):
            a[k[2:]] = argv[i + 1]
    return a


ARGS = _args()
PROFILE = TITLE["render"][ARGS["profile"]]


def _load_motion():
    tree = ast.parse((REPO / "studio/engine/motion.py").read_text(encoding="utf-8"))
    body = ast.parse("import math\n").body
    body += [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {"clamp01", "smoothstep", "rostrum"}]
    ns: dict = {}
    exec(compile(ast.Module(body=body, type_ignores=[]), "studio/engine/motion.py (closed forms)", "exec"), ns)
    return ns


MO = _load_motion()
rostrum = MO["rostrum"]

# ------------------------------------------------------------------------------------------------ images

IMAGES: dict[str, str] = {}


def tex(name: str, noncolor: bool = False):
    man = MAN_C if name in MAN_C else MAN_V1
    if name not in man:
        raise SystemExit(f"refused: image {name!r} is in neither manifest")
    e = man[name]["tex"]
    p = Path(e["file"])
    if hashlib.sha256(p.read_bytes()).hexdigest() != e["sha256"]:
        raise SystemExit(f"refused: {name} bytes differ from its manifest")
    img = bpy.data.images.load(str(p), check_existing=True)
    img.name = name
    img.colorspace_settings.name = "Non-Color" if noncolor else "sRGB"
    IMAGES[name] = str(p)
    return img


def check_provenance():
    ok = {i["id"] for i in LEDGER_V1["items"] if i.get("sha256") and not i.get("ai")}
    ok |= {i["id"] for i in LEDGER_C["items"] if i.get("sha256") and not i.get("ai")}
    # the films' records: each is an item of its film's own ledger, pinned by sha256 in the title's ledger
    ok |= {k for k, r in LEDGER_V1.get("records", {}).items() if r.get("sha256")}
    bad = [n for n in IMAGES if (MAN_C.get(n) or MAN_V1.get(n) or {}).get("from") not in ok]
    if bad:
        raise SystemExit(f"provenance check failed: {bad}")
    print(f"provenance: {len(IMAGES)} images, each from a ledger item; none ai")


# ------------------------------------------------------------------------------------------------ materials


def _n(nt, kind, **inputs):
    n = nt.nodes.new(kind)
    for k, v in inputs.items():
        n.inputs[k].default_value = v
    return n


def _mat(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    return m, m.node_tree, m.node_tree.nodes["Principled BSDF"]


def m_image(name, image, rough=0.7, alpha=False, sheen=0.1, bump=0.0):
    m, nt, b = _mat(name)
    t = _n(nt, "ShaderNodeTexImage")
    t.image = tex(image)
    t.interpolation = "Cubic"
    nt.links.new(t.outputs["Color"], b.inputs["Base Color"])
    if alpha:
        nt.links.new(t.outputs["Alpha"], b.inputs["Alpha"])
    b.inputs["Roughness"].default_value = rough
    b.inputs["Specular IOR Level"].default_value = 0.3
    b.inputs["Sheen Weight"].default_value = sheen
    if bump:
        bw = _n(nt, "ShaderNodeRGBToBW")
        nt.links.new(t.outputs["Color"], bw.inputs["Color"])
        bp = _n(nt, "ShaderNodeBump", Strength=bump, Distance=0.0002)
        nt.links.new(bw.outputs["Val"], bp.inputs["Height"])
        nt.links.new(bp.outputs["Normal"], b.inputs["Normal"])
    return m


def m_oak():
    m, nt, b = _mat("oak planks")
    co = _n(nt, "ShaderNodeTexCoord")
    mp = _n(nt, "ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (1 / 1.2, 1 / 1.2, 1)
    nt.links.new(co.outputs["Object"], mp.inputs["Vector"])
    for k, nc in (("diff", False), ("rough", True), ("nor_gl", True)):
        t = _n(nt, "ShaderNodeTexImage")
        t.image = tex(f"C-02_{k}", nc)
        nt.links.new(mp.outputs["Vector"], t.inputs["Vector"])
        if k == "diff":
            nt.links.new(t.outputs["Color"], b.inputs["Base Color"])
        elif k == "rough":
            mr = _n(nt, "ShaderNodeMapRange")
            mr.inputs["To Min"].default_value, mr.inputs["To Max"].default_value = 0.35, 0.75
            nt.links.new(t.outputs["Color"], mr.inputs["Value"])
            nt.links.new(mr.outputs["Result"], b.inputs["Roughness"])
        else:
            nm = _n(nt, "ShaderNodeNormalMap", Strength=0.6)
            nt.links.new(t.outputs["Color"], nm.inputs["Color"])
            nt.links.new(nm.outputs["Normal"], b.inputs["Normal"])
    return m


def m_metal(name, col, rough, rough_var=0.08, scale=900.0, radial=False, patina=None):
    """Procedural metal: base colour, a fine noise in roughness (handling), optional lathe rings (radial tangent and
    anisotropy, for a turned disc) and an optional patina mixed in by a low-frequency noise."""
    m, nt, b = _mat(name)
    b.inputs["Metallic"].default_value = 1.0
    co = _n(nt, "ShaderNodeTexCoord")
    nz = _n(nt, "ShaderNodeTexNoise", Scale=scale, Detail=6.0, Roughness=0.6)
    nt.links.new(co.outputs["Object"], nz.inputs["Vector"])
    mr = _n(nt, "ShaderNodeMapRange")
    mr.inputs["To Min"].default_value, mr.inputs["To Max"].default_value = rough - rough_var, rough + rough_var
    nt.links.new(nz.outputs["Fac"], mr.inputs["Value"])
    nt.links.new(mr.outputs["Result"], b.inputs["Roughness"])
    base = _n(nt, "ShaderNodeRGB")
    base.outputs[0].default_value = col + (1.0,)
    colsock = base.outputs[0]
    if patina:
        nz2 = _n(nt, "ShaderNodeTexNoise", Scale=60.0, Detail=4.0, Roughness=0.55)
        nt.links.new(co.outputs["Object"], nz2.inputs["Vector"])
        ramp = _n(nt, "ShaderNodeMapRange")
        ramp.inputs["From Min"].default_value, ramp.inputs["From Max"].default_value = 0.55, 0.75
        ramp.inputs["To Max"].default_value = patina[1]
        nt.links.new(nz2.outputs["Fac"], ramp.inputs["Value"])
        mix = _n(nt, "ShaderNodeMix")
        mix.data_type = "RGBA"
        nt.links.new(ramp.outputs["Result"], mix.inputs[0])
        nt.links.new(base.outputs[0], mix.inputs[6])
        mix.inputs[7].default_value = patina[0] + (1.0,)
        colsock = mix.outputs[2]
    nt.links.new(colsock, b.inputs["Base Color"])
    if radial:
        tg = _n(nt, "ShaderNodeTangent")
        tg.direction_type = "RADIAL"
        tg.axis = "Z"
        nt.links.new(tg.outputs["Tangent"], b.inputs["Tangent"])
        b.inputs["Anisotropic"].default_value = 0.55
        wv = _n(nt, "ShaderNodeTexWave", Scale=420.0, Distortion=0.6, Detail=2.0)
        wv.wave_type = "RINGS"
        nt.links.new(co.outputs["Object"], wv.inputs["Vector"])
        bp = _n(nt, "ShaderNodeBump", Strength=0.05, Distance=0.00002)
        nt.links.new(wv.outputs["Fac"], bp.inputs["Height"])
        nt.links.new(bp.outputs["Normal"], b.inputs["Normal"])
    return m


CLAY = (0.283, 0.168, 0.087)    # T-01's clay: the median of all six of its scan crops (sRGB 145, 114, 83), linear


def m_clay():
    """Clay marble: the tablet's own colour, mottled, matte, with a faint burnish."""
    m, nt, b = _mat("clay marble")
    co = _n(nt, "ShaderNodeTexCoord")
    nz = _n(nt, "ShaderNodeTexNoise", Scale=180.0, Detail=8.0, Roughness=0.6)
    nt.links.new(co.outputs["Object"], nz.inputs["Vector"])
    ramp = _n(nt, "ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = tuple(c * 0.78 for c in CLAY) + (1,)
    ramp.color_ramp.elements[1].color = tuple(min(1, c * 1.18) for c in CLAY) + (1,)
    nt.links.new(nz.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.74
    b.inputs["Specular IOR Level"].default_value = 0.25
    bp = _n(nt, "ShaderNodeBump", Strength=0.35, Distance=0.00008)
    nz2 = _n(nt, "ShaderNodeTexNoise", Scale=900.0, Detail=4.0)
    nt.links.new(co.outputs["Object"], nz2.inputs["Vector"])
    nt.links.new(nz2.outputs["Fac"], bp.inputs["Height"])
    nt.links.new(bp.outputs["Normal"], b.inputs["Normal"])
    return m


# ------------------------------------------------------------------------------------------------ scene


def reset(f0, f1):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.fps = FPS
    sc.frame_start, sc.frame_end = f0, f1
    w = bpy.data.worlds.new("dark grey (lighting only)")
    w.use_nodes = True
    nt = w.node_tree
    bg = nt.nodes["Background"]
    bg.inputs[0].default_value = (0.03, 0.03, 0.03, 1)
    black = nt.nodes.new("ShaderNodeBackground")
    black.inputs[0].default_value = (0, 0, 0, 1)
    lp = nt.nodes.new("ShaderNodeLightPath")
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(lp.outputs["Is Camera Ray"], mix.inputs[0])
    nt.links.new(bg.outputs[0], mix.inputs[1])
    nt.links.new(black.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], nt.nodes["World Output"].inputs["Surface"])
    sc.world = w
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "None"
    return sc


def box(name, size, loc, mat, bevel=0.0):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=loc)
    ob = bpy.context.active_object
    ob.name = name
    ob.scale = size
    bpy.ops.object.transform_apply(scale=True)
    if bevel:
        bv = ob.modifiers.new("bevel", "BEVEL")
        bv.width, bv.segments, bv.limit_method = bevel, 3, "NONE"
    ob.data.materials.append(mat)
    return ob


def tablet_faces(ob):
    """T-01's faces from its own scans: obverse up, reverse down, the four edge crops on the sides, each face's UVs
    the whole image (the cube's default cross layout would crop them)."""
    me = ob.data
    mats = {"top": 0}
    for name, img in (("bottom", "T-01_reverse"), ("+x", "T-01_edge_right"), ("-x", "T-01_edge_left"),
                      ("+y", "T-01_edge_top"), ("-y", "T-01_edge_bottom")):
        me.materials.append(m_image(f"T-01 {name}", img, 0.85, bump=0.12))
        mats[name] = len(me.materials) - 1
    uv = me.uv_layers.active
    for poly in me.polygons:
        n = poly.normal
        key = "top" if n.z > 0.9 else "bottom" if n.z < -0.9 else ("+x" if n.x > 0.9 else "-x" if n.x < -0.9 else "+y" if n.y > 0.9 else "-y")
        poly.material_index = mats[key]
        for li, c in zip(poly.loop_indices, ((0, 0), (1, 0), (1, 1), (0, 1))):
            uv.data[li].uv = c


def plane_image(name, x0, x1, y0, y1, z, mat, u_axis="y", flip=False):
    """A sheet lying on the bench with its image mapped whole. u_axis: the bench axis the image's width runs along."""
    me = bpy.data.meshes.new(name)
    co = [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)]
    me.from_pydata(co, [], [(0, 1, 2, 3)])
    uv = me.uv_layers.new()
    for li, vi in enumerate(me.polygons[0].vertices):
        x, y, _ = co[vi]
        if u_axis == "y":                                     # width along +y, image up towards -x (far)
            u, v = (y - y0) / (y1 - y0), (x1 - x) / (x1 - x0)
        else:                                                 # width along +x, image up towards +y
            u, v = (x - x0) / (x1 - x0), (y - y0) / (y1 - y0)
        uv.data[li].uv = (u, v)
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    me.materials.append(mat)
    sol = ob.modifiers.new("t", "SOLIDIFY")
    sol.thickness, sol.offset = 0.00015, -1
    return ob


def table():
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(0, 0.3, 0))
    ob = bpy.context.active_object
    ob.name = "oak bench"
    ob.scale = (3.0, 3.0, 1)
    bpy.ops.object.transform_apply(scale=True)
    ob.data.materials.append(m_oak())
    return ob


def lamp(loc, aim, power, size=(0.25, 0.18)):
    d = bpy.data.lights.new("bone lamp", "AREA")
    d.shape = "RECTANGLE"
    d.size, d.size_y = size
    d.energy = power
    d.spread = math.radians(110)
    d.use_nodes = True
    nt = d.node_tree
    bb = nt.nodes.new("ShaderNodeBlackbody")
    bb.inputs[0].default_value = 4300.0
    wb = nt.nodes.new("ShaderNodeBlackbody")
    wb.inputs[0].default_value = 5200.0
    dv = nt.nodes.new("ShaderNodeVectorMath")
    dv.operation = "DIVIDE"
    nt.links.new(bb.outputs[0], dv.inputs[0])
    nt.links.new(wb.outputs[0], dv.inputs[1])
    nt.links.new(dv.outputs[0], nt.nodes["Emission"].inputs["Color"])
    ob = bpy.data.objects.new("lamp", d)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = loc
    ob.rotation_mode = "QUATERNION"
    ob.rotation_quaternion = (Vector(aim) - Vector(loc)).to_track_quat("-Z", "Y")
    return ob


def bounce_card(loc, aim):
    bpy.ops.mesh.primitive_plane_add(size=0.6, location=loc)
    ob = bpy.context.active_object
    ob.name = "bounce card"
    ob.rotation_mode = "QUATERNION"
    ob.rotation_quaternion = (Vector(aim) - Vector(loc)).to_track_quat("Z", "Y")
    m, nt, b = _mat("bounce card")
    b.inputs["Base Color"].default_value = (0.8, 0.8, 0.78, 1)
    b.inputs["Roughness"].default_value = 0.95
    ob.data.materials.append(m)
    ob.visible_camera = False
    return ob


def camera(lens=50.0):
    d = bpy.data.cameras.new("CAM")
    d.lens, d.sensor_fit, d.sensor_width = lens, "HORIZONTAL", 36.0
    d.clip_start, d.clip_end = 0.005, 20.0
    d.dof.use_dof = True
    ob = bpy.data.objects.new("CAM", d)
    bpy.context.scene.collection.objects.link(ob)
    bpy.context.scene.camera = ob
    return ob


def _fcurves(action):
    if hasattr(action, "fcurves") and len(action.fcurves):
        return list(action.fcurves)
    out = []
    for layer in getattr(action, "layers", []):
        for strip in layer.strips:
            for cb in strip.channelbags:
                out += list(cb.fcurves)
    return out


def bake_track(ob, rows, f0, f1):
    """Key an object from simulation rows [t, x, y, z, qw, qx, qy, qz] at their own times (frame = 24 t)."""
    a = np.array(rows)
    fr = a[:, 0] * FPS
    keep = (fr >= f0 - 1.5) & (fr <= f1 + 1.5)
    a, fr = a[keep], fr[keep]
    q = a[:, 4:8].copy()
    for i in range(1, len(q)):
        if np.dot(q[i], q[i - 1]) < 0:
            q[i] = -q[i]
    ob.rotation_mode = "QUATERNION"
    ob.location = a[0, 1:4]
    ob.rotation_quaternion = q[0]
    ob.keyframe_insert("location", frame=float(fr[0]))
    ob.keyframe_insert("rotation_quaternion", frame=float(fr[0]))
    curves = {(fc.data_path, fc.array_index): fc for fc in _fcurves(ob.animation_data.action)}
    for path, idx, vals in [("location", i, a[:, 1 + i]) for i in range(3)] + \
                           [("rotation_quaternion", i, q[:, i]) for i in range(4)]:
        fc = curves[(path, idx)]
        fc.keyframe_points.clear()
        fc.keyframe_points.add(len(fr))
        fc.keyframe_points.foreach_set("co", np.stack([fr, vals], 1).ravel().astype(np.float32))
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"
        fc.update()


def key_cam(cam, frames, eyes, tgts, focus, fstop):
    cam.rotation_mode = "QUATERNION"
    prev = None
    for f, e, t, fd in zip(frames, eyes, tgts, focus):
        q = (Vector(t) - Vector(e)).to_track_quat("-Z", "Y")
        if prev is not None and q.dot(prev) < 0:
            q.negate()
        prev = q
        cam.location = e
        cam.rotation_quaternion = q
        cam.keyframe_insert("location", frame=f)
        cam.keyframe_insert("rotation_quaternion", frame=f)
        cam.data.dof.focus_distance = fd
        cam.data.dof.keyframe_insert("focus_distance", frame=f)
    for ob in (cam, cam.data):
        for fc in _fcurves(ob.animation_data.action):
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"
    cam.data.dof.aperture_fstop = fstop


# ------------------------------------------------------------------------------------------------ proofs


def build_latch():
    f0, f1 = FRAMES["latch"]
    bake = json.loads((SIM / "latch-bake.json").read_text(encoding="utf-8"))
    meta, P = bake["meta"], bake["poses"]
    table()
    # T-01 the Umma register, Ur III, lying flat behind the disc (31 x 30.5 x 5 cm, ledger); obverse up
    tab = box("T-01 Umma register", (0.31, 0.305, 0.05), (-0.16, 0.215, 0.025), m_image("T-01 obverse", "T-01_obverse", 0.85, bump=0.12), bevel=0.006)
    tablet_faces(tab)
    # T-02a the Turin papyrus: its solid left end (alpha > 0.95 from 1.2% in, rows 14 to 86% down) under the entry
    L, Hh = 0.60, 0.60 * 1481 / 8192
    px = meta["papyrus_x"] - 0.012 * L
    y_top = -0.026 + 0.030
    plane_image("T-02a Turin papyrus", px, px + L, y_top - Hh, y_top, 0.00025,
                m_image("T-02a papyrus", "T-02a_keyed", 0.75, alpha=True, sheen=0.2, bump=0.3), u_axis="x")
    # the bronze disc and the clay marble, from the bake
    bpy.ops.mesh.primitive_cylinder_add(vertices=128, radius=MF.A, depth=MF.T)
    disc = bpy.context.active_object
    disc.name = "bronze disc"
    bv = disc.modifiers.new("edge", "BEVEL")
    bv.width, bv.segments, bv.limit_method = 0.0004, 3, "ANGLE"
    bpy.ops.object.shade_smooth()
    disc.data.materials.append(m_metal("bronze", (0.50, 0.30, 0.15), 0.34, radial=True, patina=((0.16, 0.20, 0.13), 0.35)))
    bake_track(disc, P["disc"], f0, f1)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=96, ring_count=48, radius=0.008)
    mar = bpy.context.active_object
    mar.name = "clay marble"
    bpy.ops.object.shade_smooth()
    mar.data.materials.append(m_clay())
    bake_track(mar, P["marble"], f0, f1)
    # camera: 25 degrees down, 0.23 m from the disc, f/2.8; holds on the settle, cruises with the marble from f130
    mp = np.array(P["marble"])
    def marble_at(f):
        return np.array([np.interp(f / FPS, mp[:, 0], mp[:, k]) for k in (1, 2, 3)])
    a0 = Vector((0.0, 0.0, 0.010))
    m167 = marble_at(f1)
    # the camera follows the release only a little and lets the marble run out of frame (the 7-second guide: the
    # pan stays under 11 px a frame); the marble's own speed carries the release
    a1 = Vector((float(m167[0]) * 0.15, float(m167[1]) * 0.15, 0.009))
    frames = list(range(f0 - 1, f1 + 2))
    eyes, tgts, focus = [], [], []
    for f in frames:
        p = rostrum((f - 130) / FPS, (f1 + 12 - 130) / FPS) if f >= 130 else 0.0
        t = a0.lerp(a1, p)
        # re-proof (founder via the coordinator, 2026-10-17): about 25 degrees down and tighter, so the disc and the
        # marble read as a DETAIL (about a third of the frame) on the golden band, the tablet filling the top
        e = t + Vector((0.035, -0.205, 0.096))
        subj = Vector((0, 0, MF.T)) if f < 121 else Vector(marble_at(f))
        k = MO["smoothstep"]((f - 118) / 14.0)
        sd = (Vector((0, 0, MF.T)) - e).length * (1 - k) + (Vector(marble_at(f)) - e).length * k
        eyes.append(e)
        # aim right of and above the subject: it sits at about 0.38 of the width (lead room on the marble's side)
        # and 0.6 of the height
        tgts.append(t + Vector((0.019, 0.0, 0.006)))
        focus.append(sd)
    cam = camera()
    key_cam(cam, frames, eyes, tgts, focus, 2.8)
    lamp((-0.22, -0.30, 0.42), (0.0, 0.0, 0.0), float(ARGS.get("lamp") or 2.5))
    bounce_card((0.32, -0.12, 0.10), (0.0, 0.0, 0.01))
    return {"papyrus_x": meta["papyrus_x"], "camera": {"lens_mm": 50, "fstop": 2.8, "distance_m": round((eyes[1] - Vector((0, 0, 0.0015))).length, 3)}}


def build_galley():
    f0, f1 = FRAMES["galley"]
    bake = json.loads((SIM / "galley-bake.json").read_text(encoding="utf-8"))
    meta, P = bake["meta"], bake["poses"]
    L = meta["layout"]
    table()
    le = meta["leaf_edge_x"]
    lt, it = meta["leaf_t"], meta["ino_t"]
    # T-06 the Gutenberg leaf (portrait, 0.30 x 0.42 m), its head towards the far end; T-08 Ino's sheet beyond
    plane_image("T-06 Gutenberg leaf", le - 0.42, le, -0.135, 0.165, it + lt, m_image("T-06 leaf", "T-06_leaf", 0.7, sheen=0.15, bump=0.2), u_axis="y")
    plane_image("T-08 Ino sheet", le - 0.02, le + 1.0, -0.30, 0.279, it, m_image("T-08 Ino", "T-08_sheet", 0.72, sheen=0.1, bump=0.2), u_axis="y")
    brass = m_metal("brass", (0.62, 0.44, 0.18), 0.30, patina=((0.32, 0.25, 0.12), 0.4))
    tm = m_metal("type metal", (0.42, 0.42, 0.43), 0.38, rough_var=0.12, scale=1400.0, patina=((0.20, 0.20, 0.21), 0.5))
    ft = L["floor_top"]
    gx, gy = L["galley"]["x"], L["galley"]["y"]
    fl = meta["floor_t"]
    z0 = it + lt
    box("galley floor", (gx[1] - gx[0], gy[1] - gy[0], fl), ((gx[0] + gx[1]) / 2, (gy[0] + gy[1]) / 2, z0 + fl / 2), brass, 0.0003)
    for nm, (ya, yb) in (("rail", (gy[0], gy[0] + 0.003)), ("rail2", (gy[1] - 0.003, gy[1]))):
        box(nm, (gx[1] - gx[0], yb - ya, 0.006), ((gx[0] + gx[1]) / 2, (ya + yb) / 2, ft + 0.003), brass, 0.0004)
    sh = meta["step_h"]
    for nm in ("step_a", "step_b"):
        sx, sy = L[nm]["x"], L[nm]["y"]
        box(nm, (sx[1] - sx[0], sy[1] - sy[0], sh), ((sx[0] + sx[1]) / 2, (sy[0] + sy[1]) / 2, ft + sh / 2), brass, 0.0003)
    qh = meta["quad"]["half_m"]
    for i in range(12):
        ob = box(f"type {i + 1}", (2 * qh[0], 2 * qh[1], 2 * qh[2]), (0, 0, 0), tm, 0.0002)
        bake_track(ob, P[f"quad{i + 1}"], f0, f1)
    sp = meta["stop"]["half_m"]
    ob = box("end stop", (2 * sp[0], 2 * sp[1], 2 * sp[2]), (0, 0, 0), brass, 0.0002)
    bake_track(ob, P["stop"], f0, f1)
    clay = m_clay()
    for n in ("lead", "pair1", "pair2"):
        bpy.ops.mesh.primitive_uv_sphere_add(segments=96, ring_count=48, radius=0.008)
        ob = bpy.context.active_object
        ob.name = f"clay marble {n}"
        bpy.ops.object.shade_smooth()
        ob.data.materials.append(clay)
        bake_track(ob, P[n], f0, f1)
    # camera: 0.3 m high, 40 degrees down, at the downhill end so the row falls towards it; cruises on rostrum
    frames = list(range(f0 - 1, f1 + 2))
    a0, a1 = Vector((0.05, 0.004, 0.006)), Vector((0.16, 0.008, 0.004))
    eyes, tgts, focus = [], [], []
    yaw, pitch, hz = math.radians(16.0), math.radians(40.0), 0.30
    dh = hz / math.tan(pitch)
    for f in frames:
        p = rostrum((f - f0) / FPS, (f1 - f0) / FPS)
        t = a0.lerp(a1, p)
        e = t + Vector((dh * math.cos(yaw), dh * math.sin(yaw), hz))
        eyes.append(e)
        tgts.append(t)
        focus.append((t - e).length)
    cam = camera()
    key_cam(cam, frames, eyes, tgts, focus, 4.0)
    mid = (eyes[len(eyes) // 2] + tgts[len(tgts) // 2]) / 2
    lamp((eyes[0].x + 0.05, eyes[0].y + 0.22, 0.52), (0.09, 0.0, 0.0), float(ARGS.get("lamp") or 4.0), size=(0.3, 0.2))
    bounce_card((eyes[0].x - 0.05, eyes[0].y - 0.35, 0.18), (0.09, 0.0, 0.0))
    return {"camera": {"lens_mm": 50, "fstop": 4.0, "height_m": hz, "pitch_deg": 40, "yaw_deg": 16}, "leaf_edge_x": le}


CALIB_SPP = 128


def renderer_line(sc) -> str:
    """The master item's `renderer` field (WG-2's no-denoise lint): engine, device, sampling, threshold, clamp, denoiser."""
    cy = sc.cycles
    return (f"Blender {bpy.app.version_string} Cycles (OptiX), adaptive sampling {cy.samples} spp, noise threshold "
            f"{cy.adaptive_threshold}, clamp direct {cy.sample_clamp_direct or 'off'} indirect {cy.sample_clamp_indirect}, "
            f"no denoiser")


def render_settings(sc):
    p = PROFILE
    calib = bool(ARGS["calib"])
    sc.render.resolution_x, sc.render.resolution_y = (640, 360) if calib else tuple(p["res"])
    sc.render.resolution_percentage = 100
    sc.render.use_motion_blur = p["motion_blur"]
    sc.render.motion_blur_shutter = 0.5
    sc.render.engine = "CYCLES"
    cy = sc.cycles
    cy.device = "GPU"
    # NO denoiser of any kind (founder, 2026-10-18: no AI pixels; OIDN and OptiX are machine-learned): adaptive sampling,
    # high samples and a light clamp instead; the viewport's denoise off as well. tests/test_no_denoise.py holds this.
    cy.samples = CALIB_SPP if calib else p["samples"]
    cy.use_adaptive_sampling = True
    cy.adaptive_threshold = 0.03 if calib else p["noise_threshold"]
    cy.adaptive_min_samples = min(p["min_samples"], cy.samples)
    cy.use_denoising = False
    cy.use_preview_denoising = False
    cy.sample_clamp_direct = 0.0
    sc.render.use_compositing = False
    cy.max_bounces, cy.diffuse_bounces, cy.glossy_bounces = 8, 3, 4
    cy.caustics_reflective = cy.caustics_refractive = False
    cy.sample_clamp_indirect = 5.0
    cy.use_animated_seed = True
    cy.texture_limit_render = "8192"
    sc.render.use_persistent_data = True
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGB"
    sc.render.image_settings.color_depth = "8"
    sc.render.use_overwrite = False
    sc.render.use_placeholder = True


def main():
    import time
    t0 = time.time()
    proof = ARGS["proof"]
    f0, f1 = FRAMES[proof]
    sc = reset(f0, f1)
    info = build_latch() if proof == "latch" else build_galley()
    render_settings(sc)
    check_provenance()
    sc.frame_set(f0)
    out = ARGS["out"] or f"D:/document-media/title-sequence/run/blend/run-{proof}.blend"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=out, compress=False)
    info.update(proof=proof, frames=[f0, f1], blend=out, images=sorted(IMAGES), build_s=round(time.time() - t0, 1))
    print("RUN-BUILD " + json.dumps(info))


if __name__ == "__main__":
    main()
