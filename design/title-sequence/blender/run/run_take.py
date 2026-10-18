"""The Run, the full take: build the Blender scene from the one simulation, its layout and the camera plan. Nobody
hand-edits the .blend.

    blender -b --factory-startup --python design/title-sequence/blender/run/run_take.py -- \
        --window prefix|tail --record C20-METAR-0851 --fps 24|30000/1001 [--calib 1] --out <blend>

Every moving body is keyed from the simulation's 240 Hz poses at their own times (frame = t * fps), so the 180-degree
shutter blurs between true poses at either rate. The camera and the lamp are keyed per frame from the camera plan,
which is a function of seconds. Real scale, metres. Every sheet is its pinned scan at real size, turned and placed
as the simulation laid it; the galley, the knots and cord, the film strip, the platen and the felt are the simulation's
own collision geometry, drawn. The brass and bronze are worn (scratches, fingerprints, edge patina); the clay is
mottled; the type is blank (no invented marks). The lamp is one bone spot on the camera arm with a bounce card; in
the tail its iris (a rectangular gobo in the light's own node tree) closes to the record, 5 mm inside its edge.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Quaternion, Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bench as B  # noqa: E402
import camera_run as CR  # noqa: E402
import run_scene as RS  # noqa: E402
import sheetfit as SF  # noqa: E402

SIM = Path("D:/document-media/title-sequence/run/sim")


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    a = {"window": "prefix", "record": "C20-METAR-0851", "fps": "24", "calib": "", "out": "", "samples": ""}
    for i, k in enumerate(argv):
        if k.startswith("--") and i + 1 < len(argv):
            a[k[2:]] = argv[i + 1]
    return a


A = _args()
FPSV = (30000, 1001) if A["fps"] in ("30000/1001", "29.97") else (int(A["fps"]), 1)
FPS = FPSV[0] / FPSV[1]
RS.FPS = FPS                                  # run_scene's bake_track keys at frame = t * FPS


def frame_of(t):
    return t * FPS


# ------------------------------------------------------------------------------------------------ materials


def m_worn(name, col, rough, patina_col, scratch=0.5):
    """Worn brass or bronze: lathe-free handling wear. Fine directional scratches (stretched noise) raise the
    roughness in thin lines, fingerprints (soft blobs of a low noise) smear it, and the edges darken to patina by the
    geometry's pointiness; never a uniform gold."""
    m, nt, b = RS._mat(name)
    b.inputs["Metallic"].default_value = 1.0
    co = RS._n(nt, "ShaderNodeTexCoord")
    # scratches: noise stretched along one axis, thresholded into thin bright lines
    mp = RS._n(nt, "ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (2600.0, 60.0, 60.0)
    mp.inputs["Rotation"].default_value = (0.0, 0.0, 0.6)
    nt.links.new(co.outputs["Object"], mp.inputs["Vector"])
    sn = RS._n(nt, "ShaderNodeTexNoise", Scale=1.0, Detail=2.0, Roughness=0.5)
    nt.links.new(mp.outputs["Vector"], sn.inputs["Vector"])
    sr = RS._n(nt, "ShaderNodeMapRange")
    sr.inputs["From Min"].default_value, sr.inputs["From Max"].default_value = 0.62, 0.70
    sr.inputs["To Min"].default_value, sr.inputs["To Max"].default_value = 0.0, scratch
    nt.links.new(sn.outputs["Fac"], sr.inputs["Value"])
    # fingerprints: soft low-frequency blobs
    fp = RS._n(nt, "ShaderNodeTexNoise", Scale=90.0, Detail=1.0, Roughness=0.4)
    nt.links.new(co.outputs["Object"], fp.inputs["Vector"])
    fr_ = RS._n(nt, "ShaderNodeMapRange")
    fr_.inputs["From Min"].default_value, fr_.inputs["From Max"].default_value = 0.55, 0.75
    fr_.inputs["To Min"].default_value, fr_.inputs["To Max"].default_value = 0.0, 0.18
    nt.links.new(fp.outputs["Fac"], fr_.inputs["Value"])
    add = RS._n(nt, "ShaderNodeMath")
    add.operation = "ADD"
    nt.links.new(sr.outputs["Result"], add.inputs[0])
    nt.links.new(fr_.outputs["Result"], add.inputs[1])
    add2 = RS._n(nt, "ShaderNodeMath")
    add2.operation = "ADD"
    add2.use_clamp = True
    add2.inputs[1].default_value = rough
    nt.links.new(add.outputs[0], add2.inputs[0])
    nt.links.new(add2.outputs[0], b.inputs["Roughness"])
    # colour: base, mottled tarnish, edge patina by pointiness
    base = RS._n(nt, "ShaderNodeRGB")
    base.outputs[0].default_value = col + (1.0,)
    tn = RS._n(nt, "ShaderNodeTexNoise", Scale=35.0, Detail=5.0, Roughness=0.6)
    nt.links.new(co.outputs["Object"], tn.inputs["Vector"])
    tr = RS._n(nt, "ShaderNodeMapRange")
    tr.inputs["From Min"].default_value, tr.inputs["From Max"].default_value = 0.45, 0.8
    tr.inputs["To Max"].default_value = 0.45
    nt.links.new(tn.outputs["Fac"], tr.inputs["Value"])
    geo = RS._n(nt, "ShaderNodeNewGeometry")
    pr = RS._n(nt, "ShaderNodeMapRange")
    pr.inputs["From Min"].default_value, pr.inputs["From Max"].default_value = 0.52, 0.62
    pr.inputs["To Max"].default_value = 0.8
    nt.links.new(geo.outputs["Pointiness"], pr.inputs["Value"])
    mx = RS._n(nt, "ShaderNodeMath")
    mx.operation = "MAXIMUM"
    nt.links.new(tr.outputs["Result"], mx.inputs[0])
    nt.links.new(pr.outputs["Result"], mx.inputs[1])
    mix = RS._n(nt, "ShaderNodeMix")
    mix.data_type = "RGBA"
    nt.links.new(mx.outputs[0], mix.inputs[0])
    nt.links.new(base.outputs[0], mix.inputs[6])
    mix.inputs[7].default_value = patina_col + (1.0,)
    nt.links.new(mix.outputs[2], b.inputs["Base Color"])
    return m


def m_clay_mottled():
    """The clay marbles: T-01's own colour, mottled at two scales with darker specks of grog, matte, a faint burnish."""
    m, nt, b = RS._mat("clay marble (mottled)")
    co = RS._n(nt, "ShaderNodeTexCoord")
    n1 = RS._n(nt, "ShaderNodeTexNoise", Scale=140.0, Detail=6.0, Roughness=0.65)
    n2 = RS._n(nt, "ShaderNodeTexNoise", Scale=900.0, Detail=3.0, Roughness=0.5)
    vo = RS._n(nt, "ShaderNodeTexVoronoi", Scale=1400.0)
    for n in (n1, n2, vo):
        nt.links.new(co.outputs["Object"], n.inputs["Vector"])
    ramp = RS._n(nt, "ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = tuple(c * 0.70 for c in RS.CLAY) + (1,)
    ramp.color_ramp.elements[1].color = tuple(min(1, c * 1.22) for c in RS.CLAY) + (1,)
    mixf = RS._n(nt, "ShaderNodeMix")
    mixf.data_type = "FLOAT"
    mixf.inputs[0].default_value = 0.35
    nt.links.new(n1.outputs["Fac"], mixf.inputs[2])
    nt.links.new(n2.outputs["Fac"], mixf.inputs[3])
    nt.links.new(mixf.outputs[0], ramp.inputs["Fac"])
    speck = RS._n(nt, "ShaderNodeMapRange")
    speck.inputs["From Min"].default_value, speck.inputs["From Max"].default_value = 0.0, 0.08
    speck.inputs["To Min"].default_value, speck.inputs["To Max"].default_value = 0.55, 1.0
    nt.links.new(vo.outputs["Distance"], speck.inputs["Value"])
    mul = RS._n(nt, "ShaderNodeMix")
    mul.data_type = "RGBA"
    mul.blend_type = "MULTIPLY"
    mul.inputs[0].default_value = 1.0
    nt.links.new(ramp.outputs["Color"], mul.inputs[6])
    cm = RS._n(nt, "ShaderNodeCombineColor")
    for k in ("Red", "Green", "Blue"):
        nt.links.new(speck.outputs["Result"], cm.inputs[k])
    nt.links.new(cm.outputs[0], mul.inputs[7])
    nt.links.new(mul.outputs[2], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.72
    b.inputs["Specular IOR Level"].default_value = 0.25
    bp = RS._n(nt, "ShaderNodeBump", Strength=0.4, Distance=0.00008)
    nt.links.new(n2.outputs["Fac"], bp.inputs["Height"])
    nt.links.new(bp.outputs["Normal"], b.inputs["Normal"])
    return m


def m_plain(name, col, rough, sheen=0.0, metal=0.0):
    m, nt, b = RS._mat(name)
    b.inputs["Base Color"].default_value = col + (1.0,)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    b.inputs["Sheen Weight"].default_value = sheen
    return m


def m_felt():
    m, nt, b = RS._mat("black conservator's felt")
    co = RS._n(nt, "ShaderNodeTexCoord")
    nz = RS._n(nt, "ShaderNodeTexNoise", Scale=3000.0, Detail=4.0)
    nt.links.new(co.outputs["Object"], nz.inputs["Vector"])
    ramp = RS._n(nt, "ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.006, 0.006, 0.006, 1)
    ramp.color_ramp.elements[1].color = (0.016, 0.015, 0.014, 1)
    nt.links.new(nz.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 1.0
    b.inputs["Specular IOR Level"].default_value = 0.1
    b.inputs["Sheen Weight"].default_value = 0.6
    b.inputs["Sheen Roughness"].default_value = 0.4
    return m


def m_image_crop(name, image, u=(0.0, 1.0), v=(0.0, 1.0), rough=0.7, alpha=False, sheen=0.1, bump=0.0):
    m = RS.m_image(name, image, rough, alpha=alpha, sheen=sheen, bump=bump)
    nt = m.node_tree
    t = [n for n in nt.nodes if n.type == "TEX_IMAGE"][0]
    if u != (0.0, 1.0) or v != (0.0, 1.0):
        uv = RS._n(nt, "ShaderNodeUVMap")
        mp = RS._n(nt, "ShaderNodeMapping")
        mp.inputs["Location"].default_value = (u[0], v[0], 0)
        mp.inputs["Scale"].default_value = (u[1] - u[0], v[1] - v[0], 1)
        nt.links.new(uv.outputs["UV"], mp.inputs["Vector"])
        nt.links.new(mp.outputs["Vector"], t.inputs["Vector"])
    if alpha:
        m.blend_method = "HASHED" if hasattr(m, "blend_method") else None
    return m


# ------------------------------------------------------------------------------------------------ geometry


def sheet(name, s, mat, z, u_range=None):
    """A sheet lying on the bench at real size: its image's width along local u (turned psi from +x), its top along
    +v; drawn with its top surface at z."""
    W, H, psi = s["W"], s["H"], s["psi"]
    co = SF.corners(s["cx"], s["cy"], W, H, psi)
    me = bpy.data.meshes.new(name)
    me.from_pydata([(x, y, z) for x, y in co], [], [(0, 1, 2, 3)])
    uv = me.uv_layers.new()
    for li, c in zip(me.polygons[0].loop_indices, ((0, 0), (1, 0), (1, 1), (0, 1))):
        uv.data[li].uv = c
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    me.materials.append(mat)
    sol = ob.modifiers.new("t", "SOLIDIFY")
    sol.thickness, sol.offset = 0.0001, -1
    return ob


def geom_obj(name, g, mat):
    t = g["type"]
    pos = Vector(g["pos"])
    q = Quaternion(g["quat"])
    sz = g["size"]
    if t == "box":
        bpy.ops.mesh.primitive_cube_add(size=1.0)
        ob = bpy.context.active_object
        ob.scale = (2 * sz[0], 2 * sz[1], 2 * sz[2])
    elif t == "sphere":
        bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=sz[0])
        ob = bpy.context.active_object
        bpy.ops.object.shade_smooth()
    elif t == "cylinder":
        bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=sz[0], depth=2 * sz[1])
        ob = bpy.context.active_object
        bpy.ops.object.shade_smooth()
    elif t == "capsule":
        bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=sz[0], depth=2 * sz[1])
        ob = bpy.context.active_object
        for zz in (-sz[1], sz[1]):
            bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=sz[0], location=(0, 0, zz))
        bpy.ops.object.select_all(action="DESELECT")
        parts = [o for o in bpy.context.scene.objects if o.name.startswith(("Cylinder", "Sphere")) and o.data.users == 1]
        for o in parts:
            o.select_set(True)
        bpy.context.view_layer.objects.active = ob
        bpy.ops.object.join()
        bpy.ops.object.shade_smooth()
    else:
        return None
    ob.name = name
    ob.rotation_mode = "QUATERNION"
    ob.rotation_quaternion = q
    ob.location = pos
    if mat is not None:
        ob.data.materials.append(mat)
    return ob


def marble(name, rows, f0, f1, mat):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32, radius=B.R)
    ob = bpy.context.active_object
    ob.name = name
    bpy.ops.object.shade_smooth()
    ob.data.materials.append(mat)
    RS.bake_track(ob, rows, f0, f1)
    return ob


def reel(name, info, rows, f0, f1, kind):
    r, h = info["r"], info["h"]
    if kind == "reg":
        # the register's paper reel: tape wound on a hub between two thin brass flanges
        bpy.ops.mesh.primitive_cylinder_add(vertices=96, radius=r * 0.92, depth=h * 0.8)
        core = bpy.context.active_object
        core.data.materials.append(m_plain("register tape (wound)", (0.62, 0.55, 0.42), 0.8, sheen=0.2))
        parts = [core]
        for zz in (-h / 2 + 0.0004, h / 2 - 0.0004):
            bpy.ops.mesh.primitive_cylinder_add(vertices=96, radius=r, depth=0.0008, location=(0, 0, zz))
            fl = bpy.context.active_object
            fl.data.materials.append(BRASS_M)
            parts.append(fl)
        hole_r = r * 0.22
    else:
        # the film spool: a steel disc with three cut-outs between its spokes, film wound at its hub
        bpy.ops.mesh.primitive_cylinder_add(vertices=128, radius=r, depth=h)
        core = bpy.context.active_object
        core.data.materials.append(STEEL_M)
        for k in range(3):
            a = 2 * math.pi * k / 3
            bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=r * 0.30, depth=h * 3,
                                                location=(r * 0.56 * math.cos(a), r * 0.56 * math.sin(a), 0))
            cut = bpy.context.active_object
            cut.hide_render = True
            cut.hide_viewport = True
            bo = core.modifiers.new(f"cut{k}", "BOOLEAN")
            bo.object, bo.operation = cut, "DIFFERENCE"
        parts = [core]
        hole_r = r * 0.12
    bpy.ops.object.select_all(action="DESELECT")
    for p in parts:
        p.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    if len(parts) > 1:
        bpy.ops.object.join()
    ob = bpy.context.active_object
    ob.name = name
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(40))
    RS.bake_track(ob, rows, f0, f1)
    _ = hole_r
    return ob


def stick_chart(st, z):
    W, H = st["W"], st["H"]
    me = bpy.data.meshes.new("T-19 stick chart")
    co = SF.corners(st["cx"], st["cy"], W, H, st["ang"])
    zz = z + B.STICK["raise"] + B.STICK["rib_h"] * 0.6
    me.from_pydata([(x, y, zz) for x, y in co], [], [(0, 1, 2, 3)])
    uv = me.uv_layers.new()
    for li, c in zip(me.polygons[0].loop_indices, ((0, 0), (1, 0), (1, 1), (0, 1))):
        uv.data[li].uv = c
    ob = bpy.data.objects.new("T-19 stick chart", me)
    bpy.context.scene.collection.objects.link(ob)
    ob.data.materials.append(m_image_crop("T-19 stick chart", "T-19_keyed", rough=0.7, alpha=True, sheen=0.1, bump=0.4))
    sol = ob.modifiers.new("t", "SOLIDIFY")
    sol.thickness, sol.offset = 0.004, -1
    return ob


# ------------------------------------------------------------------------------------------------ lamp with an iris


def iris_lamp():
    d = bpy.data.lights.new("bone lamp", "SPOT")
    d.spot_size = math.radians(19)
    d.spot_blend = 0.7
    d.shadow_soft_size = 0.06
    d.use_nodes = True
    nt = d.node_tree
    em = nt.nodes["Emission"]
    bb = nt.nodes.new("ShaderNodeBlackbody")
    bb.inputs[0].default_value = 4300.0
    wb = nt.nodes.new("ShaderNodeBlackbody")
    wb.inputs[0].default_value = 5200.0
    dv = nt.nodes.new("ShaderNodeVectorMath")
    dv.operation = "DIVIDE"
    nt.links.new(bb.outputs[0], dv.inputs[0])
    nt.links.new(wb.outputs[0], dv.inputs[1])
    # the iris: a rectangle in the light's own frame, |x/z| < a and |y/z| < b, soft by 2%
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Normal"], sep.inputs[0])
    az = nt.nodes.new("ShaderNodeMath")
    az.operation = "ABSOLUTE"
    nt.links.new(sep.outputs["Z"], az.inputs[0])
    masks = []
    vals = {}
    for axis in ("X", "Y"):
        ax = nt.nodes.new("ShaderNodeMath")
        ax.operation = "ABSOLUTE"
        nt.links.new(sep.outputs[axis], ax.inputs[0])
        ratio = nt.nodes.new("ShaderNodeMath")
        ratio.operation = "DIVIDE"
        nt.links.new(ax.outputs[0], ratio.inputs[0])
        nt.links.new(az.outputs[0], ratio.inputs[1])
        val = nt.nodes.new("ShaderNodeValue")
        val.name = f"iris_{axis.lower()}"
        val.outputs[0].default_value = 50.0
        vals[axis] = val
        hi = nt.nodes.new("ShaderNodeMath")
        hi.operation = "MULTIPLY"
        hi.inputs[1].default_value = 1.02
        nt.links.new(val.outputs[0], hi.inputs[0])
        mr = nt.nodes.new("ShaderNodeMapRange")
        mr.clamp = True
        nt.links.new(ratio.outputs[0], mr.inputs["Value"])
        nt.links.new(val.outputs[0], mr.inputs["From Min"])
        nt.links.new(hi.outputs[0], mr.inputs["From Max"])
        mr.inputs["To Min"].default_value, mr.inputs["To Max"].default_value = 1.0, 0.0
        masks.append(mr)
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    nt.links.new(masks[0].outputs["Result"], mul.inputs[0])
    nt.links.new(masks[1].outputs["Result"], mul.inputs[1])
    nt.links.new(dv.outputs[0], em.inputs["Color"])
    nt.links.new(mul.outputs[0], em.inputs["Strength"])
    ob = bpy.data.objects.new("lamp", d)
    bpy.context.scene.collection.objects.link(ob)
    ob.rotation_mode = "QUATERNION"
    return ob, vals


# ------------------------------------------------------------------------------------------------ build


def build():
    window, rec = A["window"], A["record"]
    bake = json.loads((SIM / "run-bake.json").read_text(encoding="utf-8"))
    lay = json.loads((SIM / "run-layout.json").read_text(encoding="utf-8"))
    P = bake["poses"]
    geoms = dict(lay["geoms"])
    tail = None
    t_prefix_end = B.PREFIX_FRAMES / B.FPS
    if window == "tail":
        tb = json.loads((SIM / f"run-tail-{rec}-bake.json").read_text(encoding="utf-8"))
        tail = tb
        for n, rows in tb["poses"].items():
            P[n] = [r for r in P.get(n, []) if r[0] <= t_prefix_end] + [r for r in rows if r[0] > t_prefix_end]
        geoms.update(tb["geoms"])
        F = B.FILMS[rec]
        t0 = t_prefix_end
        t1 = (B.PREFIX_FRAMES + F["tail"][0] + F["tail"][1]) / B.FPS
    else:
        t0, t1 = 36 / B.FPS, t_prefix_end
    f0 = int(math.ceil(frame_of(t0) - 1e-6))
    f1 = int(math.ceil(frame_of(t1) - 1e-6)) - 1
    RS.FPS = 24
    sc = RS.reset(f0, f1)
    # the room beyond the lamp: lighting only, and darker than the proofs' so the bench falls away into the dark
    sc.world.node_tree.nodes["Background"].inputs[0].default_value = (0.006, 0.006, 0.006, 1)
    RS.FPS = FPS
    sc.render.fps, sc.render.fps_base = FPSV
    cam_rows = json.loads((SIM / (f"camera-{rec}.json" if window == "tail" else "camera-prefix.json")).read_text(encoding="utf-8"))["rows"]

    # the bench: oak planks the length of the run
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(2.0, 0.0, 0.0))
    ob = bpy.context.active_object
    ob.name = "oak bench"
    ob.scale = (7.2, 1.6, 1)
    bpy.ops.object.transform_apply(scale=True)
    ob.data.materials.append(RS.m_oak())
    # T-01 the Umma register beside the bronze disc
    tab = RS.box("T-01 Umma register", (0.31, 0.305, 0.05), (-0.16, 0.215, 0.025),
                 RS.m_image("T-01 obverse", "T-01_obverse", 0.85, bump=0.12), bevel=0.006)
    RS.tablet_faces(tab)

    global BRASS_M, STEEL_M
    BRASS_M = m_worn("brass (worn)", (0.62, 0.44, 0.18), 0.28, (0.24, 0.20, 0.10))
    bronze = m_worn("bronze (worn)", (0.50, 0.30, 0.15), 0.32, (0.16, 0.20, 0.13), scratch=0.4)
    STEEL_M = m_worn("steel spool", (0.42, 0.42, 0.44), 0.35, (0.16, 0.15, 0.14), scratch=0.3)
    type_metal = m_worn("type metal", (0.42, 0.42, 0.43), 0.38, (0.20, 0.20, 0.21), scratch=0.25)
    clay = m_clay_mottled()

    # the sheets, each its scan at real size, older on top
    S = lay["sheets"]
    tex = {"papyrus": ("T-02a_keyed", True), "atlas1": ("T-03_board1", False), "atlas2": ("T-03_board2", False),
           "piri": ("T-04_keyed", True), "leaf": ("T-06_leaf", False), "ino": ("T-08_sheet", False),
           "page": ("T-18_page", False), "chart": ("T-20_chart", False)}
    for nm, s in S.items():
        if nm == "card":
            sheet("blank Hollerith card", s, m_plain("manila card", (0.66, 0.58, 0.42), 0.75, sheen=0.15), s["level"])
            continue
        img, alpha = tex[nm]
        sheet(f"{nm} ({img})", s, m_image_crop(nm, img, rough=0.72, alpha=alpha, sheen=0.15, bump=0.2), s["level"])

    # the simulation's own collision geometry, drawn
    cord_rgb = (0.36, 0.27, 0.17)
    film_base = m_plain("film base", (0.10, 0.08, 0.06), 0.35)
    st = lay["stations"]
    for n, g in geoms.items():
        if n in ("oak", "tablet") or n in S or n.startswith(("fold_", "atlas", "ribs")):
            continue
        if window != "tail" and n in ("felt", "record"):
            continue                      # the prefix is shared: no film's felt or record in it
        if n.startswith(("galley", "rail", "step", "shelf")):
            geom_obj(n, g, BRASS_M)
        elif n.startswith(("knot", "cord")):
            geom_obj(n, g, m_plain("khipu cotton", cord_rgb, 0.9, sheen=0.4) if n == "knot1" or n == "cord0" else
                     bpy.data.materials.get("khipu cotton"))
        elif n == "tape":
            x0 = g["pos"][0] - g["size"][0]
            x1 = g["pos"][0] + g["size"][0]
            frac = (x1 - x0) / B.TAPE["len"]
            s = {"cx": (x0 + x1) / 2, "cy": g["pos"][1], "W": x1 - x0, "H": B.TAPE["w"], "psi": 0.0}
            sheet("T-09 Morse tape", s, m_image_crop("T-09 tape", "T-09_tape", u=(0.0, min(frac, 1.0)), rough=0.75),
                  g["pos"][2] + g["size"][2])
        elif n == "strip_c":
            x0 = g["pos"][0] - g["size"][0]
            s = {"cx": g["pos"][0], "cy": g["pos"][1], "W": 2 * g["size"][1], "H": 2 * g["size"][0], "psi": 90.0}
            ln = 2 * g["size"][1]
            frames_v = ln / (2 * g["size"][0] * 288 / 384) / 24
            sheet("T-16 Grand Canal strip", s, m_image_crop("T-16 strip", "T-16_atlas", u=(0.0, 0.25),
                                                             v=(0.0, min(frames_v, 1.0)), rough=0.3),
                  g["pos"][2] + g["size"][2] + 0.00001)
        elif n.startswith("strip_p"):
            geom_obj(n, g, film_base)
        elif n == "platen":
            ob = geom_obj(n, g, m_plain("platen rubber", (0.018, 0.017, 0.016), 0.55))
            for sgn in (-1, 1):
                gg = dict(g)
                gg["size"] = (g["size"][0] * 0.55, 0.004)
                gg["pos"] = (g["pos"][0], g["pos"][1] + sgn * (g["size"][1] + 0.004), g["pos"][2])
                geom_obj(f"platen end {sgn}", gg, BRASS_M)
        elif n == "felt":
            geom_obj(n, g, m_felt())
        elif n == "record":
            F = B.FILMS[rec]
            s = {"cx": g["pos"][0], "cy": g["pos"][1], "W": 2 * g["size"][0], "H": 2 * g["size"][1], "psi": 0.0}
            sheet(f"record {rec}", s, m_image_crop("record", F["tex"], rough=0.8, sheen=0.1), g["pos"][2] + g["size"][2])
    if "stick" in st:
        stick_chart(st["stick"], st["stick"]["level"])

    # moving bodies
    bpy.ops.mesh.primitive_cylinder_add(vertices=128, radius=0.0225, depth=0.003)
    disc = bpy.context.active_object
    disc.name = "bronze disc"
    bv = disc.modifiers.new("edge", "BEVEL")
    bv.width, bv.segments, bv.limit_method = 0.0004, 3, "ANGLE"
    bpy.ops.object.shade_smooth()
    disc.data.materials.append(bronze)
    RS.bake_track(disc, P["disc"], f0, f1)
    for n in ("lead", "pair1", "pair2"):
        if P.get(n):
            marble(f"clay marble {n}", P[n], f0, f1, clay)
    gl = st.get("galley")
    if gl:
        qh = gl["quad_half"]
        sh = gl["stop_half"]
        for i in range(12):
            if P.get(f"quad{i + 1}"):
                ob = RS.box(f"type {i + 1} (blank)", (2 * qh[0], 2 * qh[1], 2 * qh[2]), (0, 0, 0), type_metal, 0.0002)
                RS.bake_track(ob, P[f"quad{i + 1}"], f0, f1)
        if P.get("stop"):
            ob = RS.box("end stop", (2 * sh[0], 2 * sh[1], 2 * sh[2]), (0, 0, 0), BRASS_M, 0.0002)
            RS.bake_track(ob, P["stop"], f0, f1)
    for n, kind in (("reel_reg", "reg"), ("reel_film", "film")):
        if P.get(n) and n in st:
            reel(n, st[n], P[n], f0, f1, kind)
    if P.get("brass"):
        A_, T_ = B.BRASS["A"], B.BRASS["T"]
        bpy.ops.mesh.primitive_cylinder_add(vertices=128, radius=A_, depth=2 * T_)
        bd = bpy.context.active_object
        bd.name = "brass disc"
        bv = bd.modifiers.new("edge", "BEVEL")
        bv.width, bv.segments, bv.limit_method = 0.0004, 3, "ANGLE"
        bpy.ops.object.shade_smooth()
        bd.data.materials.append(BRASS_M)
        RS.bake_track(bd, P["brass"], f0, f1)

    # camera and lamp, keyed per frame from the plan (seconds)
    cam = RS.camera()
    lamp, iris = iris_lamp()
    card = RS.bounce_card((0, 0, 0.1), (0, 0, 0))
    frames = list(range(f0 - 1, f1 + 2))
    eyes, tgts, focus, fst = [], [], [], []
    rec_g = geoms.get("record")
    F = B.FILMS.get(rec)
    for f in frames:
        r = CR.at(cam_rows, f / FPS)
        eyes.append(Vector(r["eye"]))
        tgts.append(Vector(r["target"]))
        focus.append(r["focus"])
        fst.append(r["fstop"])
        T = Vector(r["target"])
        Dd = r["D"]
        t = f / FPS
        # the lamp on the arm: above and behind the camera's left shoulder, scaled with the distance
        lp = T + Vector((-0.96, -1.31, 1.83)) * Dd
        aim = T
        if window == "tail" and rec_g is not None:
            # in the tail the lamp swings over the record so its iris can close square on it
            rc = Vector((rec_g["pos"][0], rec_g["pos"][1], 0.0))
            u = CR.smoothstep((t * B.FPS - 940) / 40.0)
            over = rc + Vector((0, 0, 0.9))
            lp = lp.lerp(over, u)
            aim = T.lerp(rc, u)
        lamp.location = lp
        lamp.rotation_quaternion = (aim - lp).to_track_quat("-Z", "Y")
        dist = (aim - lp).length
        energy = 9.0 * (dist / 0.55) ** 2
        k_up = CR.smoothstep((t * B.FPS - 36) / 12.0)
        lamp.data.energy = energy * k_up
        lamp.keyframe_insert("location", frame=f)
        lamp.keyframe_insert("rotation_quaternion", frame=f)
        lamp.data.keyframe_insert("energy", frame=f)
        a = b = 50.0
        if window == "tail" and rec_g is not None:
            fc0 = B.PREFIX_FRAMES + F["tail"][0]
            u = CR.smoothstep((t * B.FPS - fc0) / F["tail"][1])
            h = 0.9 - rec_g["pos"][2]
            a_end = (rec_g["size"][0] - 0.005) / h
            b_end = (rec_g["size"][1] - 0.005) / h
            a0 = math.tan(math.radians(40))
            a = a0 + (a_end - a0) * u if t * B.FPS >= fc0 else 50.0
            b = a0 + (b_end - a0) * u if t * B.FPS >= fc0 else 50.0
        iris["X"].outputs[0].default_value = a
        iris["Y"].outputs[0].default_value = b
        iris["X"].outputs[0].keyframe_insert("default_value", frame=f)
        iris["Y"].outputs[0].keyframe_insert("default_value", frame=f)
        card.location = T + Vector((0.55, -0.35, 0.30)) * Dd
        card.rotation_quaternion = (T - card.location).to_track_quat("Z", "Y")
        card.keyframe_insert("location", frame=f)
        card.keyframe_insert("rotation_quaternion", frame=f)
    RS.key_cam(cam, frames, eyes, tgts, focus, 4.0)
    for f, s_ in zip(frames, fst):
        cam.data.dof.aperture_fstop = s_
        cam.data.dof.keyframe_insert("aperture_fstop", frame=f)
    return sc, f0, f1


def main():
    import time
    t0 = time.time()
    RS.ARGS["calib"] = A["calib"]
    sc, f0, f1 = build()
    RS.render_settings(sc)
    if A["samples"]:
        sc.cycles.samples = int(A["samples"])
    sc.render.fps, sc.render.fps_base = FPSV
    RS.check_provenance()
    sc.frame_set(f0)
    out = A["out"] or f"D:/document-media/title-sequence/run/blend/take-{A['window']}.blend"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=out, compress=False)
    print("RUN-BUILD " + json.dumps({"window": A["window"], "record": A["record"], "fps": A["fps"], "frames": [f0, f1],
                                     "blend": out, "images": sorted(RS.IMAGES), "build_s": round(time.time() - t0, 1)}))


if __name__ == "__main__":
    main()
