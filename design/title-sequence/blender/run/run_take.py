"""The Run v4, the full take: build the Blender scene from the one simulation, its layout, the relief and the camera
plan. Nobody hand-edits the .blend. v4 (design sections 2, 3, 6): a real oak table with its boards, chamfer, breadboard
ends, legs and floor; every sheet a displaced mesh with real thickness from relief.py's EXR (the same heightmap the
simulation rolls on); reels on hubs with their coils' layers; the lamp's 48 degree cone with the dimmer ride, its
rectangular iris keyed per beat and the dark past x 1.92 in the prefix. What follows is M1's description, which stands
where v4 does not change it.

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

SIM = Path("D:/document-media/title-sequence/run/sim/v4")
# the lamp: a bone spot (4300 K) on a stand at the table's near side, raking the sheets from the near left at about
# 50 degrees so their edges throw contact shadows; its cone covers the table to the record with a soft falloff
LAMP = {"pos": (0.95, -0.85, 1.55), "aim": (1.15, 0.50, 0.0), "energy": 170.0, "cone_deg": 80.0, "blend": 0.45,
        "soft": 0.04}
RELIEF = Path("D:/document-media/title-sequence/run/relief")


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    a = {"window": "prefix", "record": "C20-METAR-0851", "fps": "24", "calib": "", "out": "", "samples": "", "res": "",
         "end": ""}
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
        hi.inputs[1].default_value = 1.35          # a soft iris: the pool falls off like a reading lamp's
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


def m_oak_v4(name="oak (table)", seed=0.0, across=False):
    """The table's oak: the pinned CC0 photo-scan (C-02, Poly Haven Oak Wood Planks: diffuse, roughness, normal; founder
    note 2026-10-18), each board taking its own stretch of the scan (offset by its seed), the breadboard ends with the
    grain turned across; satin oil (roughness 0.3 to 0.5)."""
    m, nt, b = RS._mat(name)
    co = RS._n(nt, "ShaderNodeTexCoord")
    mp = RS._n(nt, "ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (1 / 1.2, 1 / 1.2, 1)
    mp.inputs["Location"].default_value = (seed * 0.41, seed * 0.73, 0.0)
    mp.inputs["Rotation"].default_value = (0.0, 0.0, math.pi / 2 if across else 0.0)
    nt.links.new(co.outputs["Object"], mp.inputs["Vector"])
    for k, nc in (("diff", False), ("rough", True), ("nor_gl", True)):
        t = RS._n(nt, "ShaderNodeTexImage")
        t.image = RS.tex(f"C-02_{k}", nc)
        nt.links.new(mp.outputs["Vector"], t.inputs["Vector"])
        if k == "diff":
            nt.links.new(t.outputs["Color"], b.inputs["Base Color"])
        elif k == "rough":
            mr = RS._n(nt, "ShaderNodeMapRange")
            mr.inputs["To Min"].default_value, mr.inputs["To Max"].default_value = 0.30, 0.50
            nt.links.new(t.outputs["Color"], mr.inputs["Value"])
            nt.links.new(mr.outputs["Result"], b.inputs["Roughness"])
        else:
            nm = RS._n(nt, "ShaderNodeNormalMap", Strength=0.6)
            nt.links.new(t.outputs["Color"], nm.inputs["Color"])
            nt.links.new(nm.outputs["Normal"], b.inputs["Normal"])
    return m


def table_model():
    """The 2.2 x 1.0 m oak table: four boards 0.25 m wide with visible joints along its length, breadboard ends, a 40
    mm top with a 3 mm chamfer, four legs, and the dark grey floor 0.75 m below, out of the lamp."""
    W, H = B.TABLE["size"]
    top, bb, cham = B.TABLE["top"], B.TABLE["breadboard"], B.TABLE["chamfer"]
    joint = 0.0008
    parts = []
    for k in range(B.TABLE["boards"]):
        y0 = k * B.TABLE["board_w"]
        ob = RS.box(f"oak board {k + 1}", (W - 2 * bb - joint, B.TABLE["board_w"] - joint, top),
                    (W / 2, y0 + B.TABLE["board_w"] / 2, -top / 2), m_oak_v4(f"oak board {k + 1}", seed=k * 0.37), bevel=cham)
        parts.append(ob)
    for side, x in (("left", bb / 2), ("right", W - bb / 2)):
        parts.append(RS.box(f"breadboard {side}", (bb - joint, H, top), (x, H / 2, -top / 2),
                            m_oak_v4(f"breadboard {side}", seed=2.1 + x, across=True), bevel=cham))
    leg = m_oak_v4("oak legs", seed=5.0)
    for x in (0.08, W - 0.08):
        for y in (0.08, H - 0.08):
            RS.box("leg", (0.07, 0.07, B.TABLE["height"] - top), (x, y, -top - (B.TABLE["height"] - top) / 2), leg, 0.003)
    bpy.ops.mesh.primitive_plane_add(size=12.0, location=(W / 2, H / 2, -B.TABLE["height"]))
    fl = bpy.context.active_object
    fl.name = "floor"
    fl.data.materials.append(m_plain("floor (dark grey)", (0.035, 0.034, 0.033), 0.85))
    return parts


ASSETS = Path("D:/document-media/title-sequence/run/assets")
SCAN_LEDGER = HERE.parents[1] / "run-scan-ledger.json"


def import_scan(name, size_m, loc, yaw_deg=0.0, lie_flat=False):
    """A gated real scan (run-scan-ledger.json, gate "pass") imported from its glTF, joined, scaled by its bounding box
    so its largest extent is the object's real size, turned and set down with its lowest point on the surface at loc.
    Classical steps only (scale, place); no retopology, no upscaling."""
    led = {i["id"]: i for i in json.loads(SCAN_LEDGER.read_text(encoding="utf-8"))["items"]}
    if led.get(name, {}).get("gate") != "pass":
        raise SystemExit(f"scan {name} has not passed the gate")
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(ASSETS / name / "scene.gltf"))
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH"]
    new_names = [o.name for o in new]
    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    ob = bpy.context.active_object
    ob.parent = None
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    keep = ob.name
    for nm_ in [n_ for n_ in new_names if n_ != keep]:
        o = bpy.data.objects.get(nm_)
        if o is not None and o.type != "MESH":
            bpy.data.objects.remove(o, do_unlink=True)
    ob = bpy.data.objects[keep]
    import numpy as np_
    co = np_.array([v.co[:] for v in ob.data.vertices])
    ext = co.max(0) - co.min(0)
    k = size_m / float(ext.max())
    ob.scale = (k, k, k)
    if lie_flat and ext[2] > ext.min():
        # a coin's thin axis to vertical
        thin = int(np_.argmin(ext))
        if thin == 0:
            ob.rotation_euler = (0.0, math.pi / 2, 0.0)
        elif thin == 1:
            ob.rotation_euler = (math.pi / 2, 0.0, 0.0)
    bpy.ops.object.transform_apply(rotation=True, scale=True)
    co = np_.array([v.co[:] for v in ob.data.vertices])
    mid = (co.max(0) + co.min(0)) / 2
    ob.location = (loc[0] - mid[0], loc[1] - mid[1], loc[2] - co.min(0)[2])
    ob.rotation_euler = (0.0, 0.0, math.radians(yaw_deg))
    ob.name = f"{name} (real scan)"
    return ob


def fibre(name, rgb):
    return m_plain(f"{name} (fibre, the scan's own margin colour)", rgb, 0.85, sheen=0.3)


def scan_margin_colour(image, alpha):
    """The median colour of the scan's opaque pixels within 3% of its outline: the method run_scene.CLAY uses."""
    from PIL import Image as PI
    from scipy.ndimage import binary_erosion
    man = RS.MAN_C if image in RS.MAN_C else RS.MAN_V1
    im = PI.open(man[image]["tex"]["file"]).convert("RGBA")
    im.thumbnail((600, 600))
    a = np.asarray(im, np.float32) / 255.0
    m = a[..., 3] > 0.5 if alpha else np.ones(a.shape[:2], bool)
    k = max(2, int(0.03 * max(m.shape)))
    if alpha:
        ring = m & ~binary_erosion(m, iterations=k)
    else:
        ring = np.zeros_like(m)
        ring[:k, :] = ring[-k:, :] = ring[:, :k] = ring[:, -k:] = True
    rgb = np.median(a[..., :3][ring], axis=0)
    return tuple(float(((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92) for c in rgb)


def sheet_mesh(name, top_mat, side_mat):
    """A sheet from its relief EXR (relief.py): the top surface at its composed top (G), the underside at its composed
    underside (B), and the walls between along its footprint's outline (A), so it has real thickness and lifts."""
    s = B.SHEETS[name]
    img = bpy.data.images.load(str(RELIEF / f"{name}.exr"), check_existing=False)
    w_, h_ = img.size
    px = np.array(img.pixels[:], dtype=np.float32).reshape(h_, w_, 4)[::-1]       # row 0 at +v
    bpy.data.images.remove(img)
    topz, botz, mask = px[..., 1], px[..., 2], px[..., 3] > 0.5
    W, H = s["size"]
    nv, nu = topz.shape
    u = -W / 2 + (np.arange(nu) + 0.5) * W / nu
    v = H / 2 - (np.arange(nv) + 0.5) * H / nv
    U, V = np.meshgrid(u, v)
    p = math.radians(s["psi"])
    X = s["centre"][0] + U * math.cos(p) - V * math.sin(p)
    Y = s["centre"][1] + U * math.sin(p) + V * math.cos(p)
    idx = np.arange(nv * nu).reshape(nv, nu)
    keep = mask[:-1, :-1] & mask[1:, :-1] & mask[:-1, 1:] & mask[1:, 1:]
    jj, ii = np.nonzero(keep)
    a_, b_, c_, d_ = idx[jj, ii], idx[jj, ii + 1], idx[jj + 1, ii + 1], idx[jj + 1, ii]
    n = nv * nu
    verts = np.concatenate([np.stack([X.ravel(), Y.ravel(), topz.ravel()], 1),
                            np.stack([X.ravel(), Y.ravel(), botz.ravel()], 1)])
    faces = [np.stack([a_, d_, c_, b_], 1), np.stack([a_ + n, b_ + n, c_ + n, d_ + n], 1)]
    mats = [np.zeros(len(a_), np.int32), np.ones(len(a_), np.int32)]
    # walls along the outline: an edge of a kept face whose neighbour across it is not kept
    K = np.zeros((nv + 1, nu + 1), bool)
    K[1:-1, 1:-1] = keep
    for (dj, di), (e0, e1) in (((-1, 0), (lambda j, i: idx[j, i], lambda j, i: idx[j, i + 1])),
                               ((1, 0), (lambda j, i: idx[j + 1, i + 1], lambda j, i: idx[j + 1, i])),
                               ((0, -1), (lambda j, i: idx[j + 1, i], lambda j, i: idx[j, i])),
                               ((0, 1), (lambda j, i: idx[j, i + 1], lambda j, i: idx[j + 1, i + 1]))):
        edge = keep & ~K[1 + dj:nv + dj, 1 + di:nu + di]
        ej, ei = np.nonzero(edge)
        p0, p1 = e0(ej, ei), e1(ej, ei)
        faces.append(np.stack([p0, p1, p1 + n, p0 + n], 1))
        mats.append(np.ones(len(p0), np.int32))
    faces = np.concatenate(faces)
    mats = np.concatenate(mats)
    used = np.unique(faces)
    remap = np.full(2 * n, -1, np.int64)
    remap[used] = np.arange(len(used))
    faces = remap[faces]
    verts = verts[used]
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(verts))
    me.vertices.foreach_set("co", verts.astype(np.float32).ravel())
    me.loops.add(faces.size)
    me.loops.foreach_set("vertex_index", faces.astype(np.int32).ravel())
    me.polygons.add(len(faces))
    me.polygons.foreach_set("loop_start", (np.arange(len(faces)) * 4).astype(np.int32))
    me.polygons.foreach_set("material_index", mats)
    me.update(calc_edges=True)
    # UVs: the scan's own coordinates (u across, v up) for every vertex, top and bottom alike
    uvv = np.concatenate([np.stack([(np.arange(nu)[None, :].repeat(nv, 0) + 0.5) / nu,
                                    1 - (np.arange(nv)[:, None].repeat(nu, 1) + 0.5) / nv], -1).reshape(-1, 2)] * 2)[used]
    uv = me.uv_layers.new()
    uv.data.foreach_set("uv", uvv[faces.ravel()].astype(np.float32).ravel())
    me.polygons.foreach_set("use_smooth", np.ones(len(faces), bool))
    ob = bpy.data.objects.new(f"{name} ({s['tex']})", me)
    bpy.context.scene.collection.objects.link(ob)
    me.materials.append(top_mat)
    me.materials.append(side_mat)
    return ob


def m_scan_on_backing(name, image, backing_rgb):
    """The keyed papyrus over its plain backing: the scan where its alpha is, the backing's plain colour elsewhere."""
    m, nt, b = RS._mat(name)
    t = RS._n(nt, "ShaderNodeTexImage")
    t.image = RS.tex(image)
    t.interpolation = "Cubic"
    # the backing: linen, the pinned CC0 photo-scan (C-03) at its real size (0.27 m)
    co = RS._n(nt, "ShaderNodeTexCoord")
    mp = RS._n(nt, "ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (1 / 0.27, 1 / 0.27, 1)
    nt.links.new(co.outputs["Object"], mp.inputs["Vector"])
    lin = RS._n(nt, "ShaderNodeTexImage")
    lin.image = RS.tex("C-03_diff")
    nt.links.new(mp.outputs["Vector"], lin.inputs["Vector"])
    mix = RS._n(nt, "ShaderNodeMix")
    mix.data_type = "RGBA"
    nt.links.new(t.outputs["Alpha"], mix.inputs[0])
    nt.links.new(lin.outputs["Color"], mix.inputs[6])
    nt.links.new(t.outputs["Color"], mix.inputs[7])
    _ = backing_rgb
    nt.links.new(mix.outputs[2], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.75
    b.inputs["Sheen Weight"].default_value = 0.2
    return m


def reel_v4(name, info, rows, f0, f1, kind):
    """A reel on its hub: the hub stands on the paper, the flange and the coil above it, the coil's layers as fine
    rings, so it reads as a cylinder from above."""
    r, h, hub_r = info["r"], info["h"], info["hub_r"]
    parts = []
    bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=hub_r, depth=0.012, location=(0, 0, 0.006))
    hub = bpy.context.active_object
    hub.data.materials.append(BRASS_M)
    parts.append(hub)
    z0 = 0.0005
    if kind == "reg":
        bpy.ops.mesh.primitive_cylinder_add(vertices=128, radius=r * 0.92, depth=h * 0.8, location=(0, 0, z0 + h / 2))
        coil = bpy.context.active_object
        coil.data.materials.append(m_coil("register tape (wound)", (0.62, 0.55, 0.42), r))
        parts.append(coil)
        for zz in (z0 + 0.0004, z0 + h - 0.0004):
            bpy.ops.mesh.primitive_cylinder_add(vertices=128, radius=r, depth=0.0008, location=(0, 0, zz))
            fl = bpy.context.active_object
            fl.data.materials.append(BRASS_M)
            parts.append(fl)
    else:
        bpy.ops.mesh.primitive_cylinder_add(vertices=128, radius=r, depth=0.0012, location=(0, 0, z0 + 0.0006))
        disc = bpy.context.active_object
        disc.data.materials.append(STEEL_M)
        for k in range(3):
            a = 2 * math.pi * k / 3
            bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=r * 0.22, depth=0.01,
                                                location=(r * 0.68 * math.cos(a), r * 0.68 * math.sin(a), z0))
            cut = bpy.context.active_object
            cut.hide_render = cut.hide_viewport = True
            bo = disc.modifiers.new(f"cut{k}", "BOOLEAN")
            bo.object, bo.operation = cut, "DIFFERENCE"
        parts.append(disc)
        bpy.ops.mesh.primitive_cylinder_add(vertices=128, radius=r * 0.48, depth=h - 0.0012, location=(0, 0, z0 + 0.0012 + (h - 0.0012) / 2))
        coil = bpy.context.active_object
        coil.data.materials.append(m_coil("35 mm film (wound)", (0.06, 0.045, 0.03), r))
        parts.append(coil)
    bpy.ops.object.select_all(action="DESELECT")
    for p_ in parts:
        p_.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.object.join()
    ob = bpy.context.active_object
    ob.name = name
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(40))
    RS.bake_track(ob, rows, f0, f1)
    return ob


def m_coil(name, rgb, r):
    """A wound coil: its layers as fine concentric rings on the top face (a wave texture, radial)."""
    m, nt, b = RS._mat(name)
    co = RS._n(nt, "ShaderNodeTexCoord")
    wave = RS._n(nt, "ShaderNodeTexWave")
    wave.wave_type, wave.rings_direction = "RINGS", "SPHERICAL"
    wave.inputs["Scale"].default_value = 0.25 / r * 2.0
    wave.inputs["Distortion"].default_value = 0.4
    nt.links.new(co.outputs["Object"], wave.inputs["Vector"])
    mr = RS._n(nt, "ShaderNodeMapRange")
    mr.inputs["To Min"].default_value, mr.inputs["To Max"].default_value = 0.8, 1.0
    nt.links.new(wave.outputs["Fac"], mr.inputs["Value"])
    mul = RS._n(nt, "ShaderNodeMix")
    mul.data_type, mul.blend_type = "RGBA", "MULTIPLY"
    mul.inputs[0].default_value = 1.0
    mul.inputs[6].default_value = rgb + (1.0,)
    cmb = RS._n(nt, "ShaderNodeCombineColor")
    for k in ("Red", "Green", "Blue"):
        nt.links.new(mr.outputs["Result"], cmb.inputs[k])
    nt.links.new(cmb.outputs[0], mul.inputs[7])
    nt.links.new(mul.outputs[2], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.6
    return m


def stick_chart_v4(st):
    """The lattice (T-19), its keyed photograph at real size raised on its shells, at the simulation's place."""
    W, H = st["W"], st["H"]
    me = bpy.data.meshes.new("T-19 stick chart")
    co = B.corners(st["cx"], st["cy"], W, H, st["psi"])
    zz = st["z"] + B.STICK["raise"] + B.STICK["rib_h"]
    me.from_pydata([(x, y, zz) for x, y in co], [], [(0, 1, 2, 3)])
    uv = me.uv_layers.new()
    for li, c in zip(me.polygons[0].loop_indices, ((0, 0), (1, 0), (1, 1), (0, 1))):
        uv.data[li].uv = c
    ob = bpy.data.objects.new("T-19 stick chart", me)
    bpy.context.scene.collection.objects.link(ob)
    ob.data.materials.append(m_image_crop("T-19 stick chart", "T-19_keyed", rough=0.7, alpha=True, sheen=0.1, bump=0.4))
    sol = ob.modifiers.new("t", "SOLIDIFY")
    sol.thickness, sol.offset = B.STICK["rib_h"], -1
    return ob


def iris_lamp_v4():
    """The bone lamp: a 48 degree spot with a rectangular iris in its own frame (half-angles iris_x, iris_y as
    tangents) and the dark mask: no light lands where the table's x is past dark_x (the years after 1931 are crossed
    in the dark). The lamp's position is keyed into its own node tree (lamp_x, lamp_y, lamp_z) so the mask is computed
    on the table in world space."""
    ob, vals = iris_lamp()
    d = ob.data
    d.spot_size = math.radians(48)
    d.spot_blend = 0.15
    d.shadow_soft_size = 0.05
    nt = d.node_tree
    em = nt.nodes["Emission"]
    strength_in = em.inputs["Strength"].links[0].from_socket
    tc = [n for n in nt.nodes if n.type == "TEX_COORD"][0]
    vt = nt.nodes.new("ShaderNodeVectorTransform")
    vt.vector_type, vt.convert_from, vt.convert_to = "VECTOR", "OBJECT", "WORLD"
    nt.links.new(tc.outputs["Normal"], vt.inputs["Vector"])
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(vt.outputs["Vector"], sep.inputs[0])
    for k in ("lamp_x", "lamp_z", "dark_x"):
        v = nt.nodes.new("ShaderNodeValue")
        v.name = k
        vals[k] = v
    vals["dark_x"].outputs[0].default_value = 99.0
    # x on the table: lamp_x + dx * lamp_z / -dz
    neg = nt.nodes.new("ShaderNodeMath")
    neg.operation = "MULTIPLY"
    neg.inputs[1].default_value = -1.0
    nt.links.new(sep.outputs["Z"], neg.inputs[0])
    mx = nt.nodes.new("ShaderNodeMath")
    mx.operation = "MAXIMUM"
    mx.inputs[1].default_value = 1e-4
    nt.links.new(neg.outputs[0], mx.inputs[0])
    dv = nt.nodes.new("ShaderNodeMath")
    dv.operation = "DIVIDE"
    nt.links.new(vals["lamp_z"].outputs[0], dv.inputs[0])
    nt.links.new(mx.outputs[0], dv.inputs[1])
    ml = nt.nodes.new("ShaderNodeMath")
    ml.operation = "MULTIPLY_ADD"
    nt.links.new(sep.outputs["X"], ml.inputs[0])
    nt.links.new(dv.outputs[0], ml.inputs[1])
    nt.links.new(vals["lamp_x"].outputs[0], ml.inputs[2])
    sub = nt.nodes.new("ShaderNodeMath")
    sub.operation = "SUBTRACT"
    nt.links.new(ml.outputs[0], sub.inputs[0])
    nt.links.new(vals["dark_x"].outputs[0], sub.inputs[1])
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.clamp = True
    nt.links.new(sub.outputs[0], mr.inputs["Value"])
    mr.inputs["From Min"].default_value, mr.inputs["From Max"].default_value = -0.004, 0.004
    mr.inputs["To Min"].default_value, mr.inputs["To Max"].default_value = 1.0, 0.0
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    nt.links.new(strength_in, mul.inputs[0])
    nt.links.new(mr.outputs["Result"], mul.inputs[1])
    nt.links.new(mul.outputs[0], em.inputs["Strength"])
    return ob, vals


# ------------------------------------------------------------------------------------------------ build


def build():
    window, rec = A["window"], A["record"]
    bake = json.loads((SIM / "run-bake.json").read_text(encoding="utf-8"))
    lay = json.loads((SIM / "run-layout.json").read_text(encoding="utf-8"))
    P = bake["poses"]
    geoms = dict(lay["geoms"])
    t_prefix_end = B.PREFIX_FRAMES / B.FPS
    tb = None
    F = B.FILMS[rec]
    if window == "tail":
        tb = json.loads((SIM / f"run-tail-{rec}-bake.json").read_text(encoding="utf-8"))
        for n, rows in tb["poses"].items():
            P[n] = [r for r in P.get(n, []) if r[0] <= t_prefix_end] + [r for r in rows if r[0] > t_prefix_end]
        geoms.update(tb["geoms"])
        t0 = t_prefix_end
        t1 = (B.PREFIX_FRAMES + sum(F["tail"][:3])) / B.FPS
    else:
        t0, t1 = 0.0, (int(A["end"]) + 1) / B.FPS if A["end"] else t_prefix_end
    f0 = int(math.ceil(frame_of(t0) - 1e-6))
    f1 = int(math.ceil(frame_of(t1) - 1e-6)) - 1
    RS.FPS = 24
    sc = RS.reset(f0, f1)
    sc.world.node_tree.nodes["Background"].inputs[0].default_value = (0.006, 0.006, 0.006, 1)
    RS.FPS = FPS
    sc.render.fps, sc.render.fps_base = FPSV
    cam_rows = json.loads((SIM / (f"camera-{rec}.json" if window == "tail" else "camera-prefix.json")).read_text(encoding="utf-8"))["rows"]

    table_model()
    t = B.TABLET
    tab = RS.box("T-01 Umma register", t["size"], (t["centre"][0], t["centre"][1], t["size"][2] / 2),
                 RS.m_image("T-01 obverse", "T-01_obverse", 0.85, bump=0.12), bevel=0.006)
    tab.rotation_euler = (0, 0, math.radians(t["psi"]))
    RS.tablet_faces(tab)

    global BRASS_M, STEEL_M
    BRASS_M = m_worn("brass (worn)", (0.62, 0.44, 0.18), 0.42, (0.24, 0.20, 0.10))
    bronze = m_worn("bronze (worn)", (0.50, 0.30, 0.15), 0.32, (0.16, 0.20, 0.13), scratch=0.4)
    STEEL_M = m_worn("steel spool", (0.42, 0.42, 0.44), 0.35, (0.16, 0.15, 0.14), scratch=0.3)
    type_metal = m_worn("type metal", (0.42, 0.42, 0.43), 0.38, (0.20, 0.20, 0.21), scratch=0.25)
    clay = m_clay_mottled()

    # the sheets: displaced meshes with thickness, from relief.py's EXRs; the scans only
    for nm, s in B.SHEETS.items():
        alpha = bool(s.get("alpha"))
        rgb = tuple(json.loads((RELIEF / f"{nm}.json").read_text(encoding="utf-8"))["margin_rgb_linear"])
        side = fibre(nm, rgb)
        if s.get("backing"):
            top = m_scan_on_backing(nm, s["tex"], rgb)
        else:
            top = m_image_crop(nm, s["tex"], rough=0.72, alpha=alpha, sheen=0.15, bump=0.15)
        sheet_mesh(nm, top, side)

    st = lay["stations"]
    film_base = m_plain("film base", (0.10, 0.08, 0.06), 0.35)
    cotton = m_plain("khipu cotton", (0.36, 0.27, 0.17), 0.9, sheen=0.4)
    for n, g in geoms.items():
        if g["type"] == "hfield" or n in ("oak", "tablet"):
            continue
        if window != "tail" and n in ("felt", "record"):
            continue                      # the prefix is shared: no film's felt or record in it
        if n.startswith(("galley", "rail", "step", "shelf")):
            geom_obj(n, g, BRASS_M)
        elif n.startswith(("knot", "cord")):
            geom_obj(n, g, cotton)
        elif n == "tape":
            s = {"cx": g["pos"][0], "cy": g["pos"][1], "W": 2 * g["size"][0], "H": 2 * g["size"][1],
                 "psi": 2 * math.degrees(math.atan2(g["quat"][3], g["quat"][0]))}
            sheet("T-09 Morse tape", s, m_image_crop("T-09 tape", "T-09_tape", rough=0.75), g["pos"][2] + g["size"][2] + 0.0001)
        elif n == "card":
            ob = geom_obj("blank Hollerith card", g, m_plain("manila card", (0.66, 0.58, 0.42), 0.75, sheen=0.15))
        elif n == "strip_c":
            ob = geom_obj("35 mm strip (picture band)", g, film_base)
        elif n.startswith("strip_p"):
            geom_obj(n, g, film_base)
        elif n == "platen":
            geom_obj(n, g, m_plain("platen rubber", (0.018, 0.017, 0.016), 0.55))
        elif n.startswith("tray_"):
            geom_obj(n, g, m_oak_v4(f"tray oak (modelled, plain)", seed=3.3))
        elif n == "weights":
            st_w = lay["stations"]["weights"]
            import_scan("weights", 2 * st_w["r"], (st_w["centre"][0], st_w["centre"][1], st_w["centre"][2]))
        elif n == "felt":
            geom_obj(n, g, m_felt())
        elif n == "record":
            s = {"cx": g["pos"][0], "cy": g["pos"][1], "W": 2 * g["size"][0], "H": 2 * g["size"][1], "psi": 0.0}
            rinfo = tb["meta"]["record"]
            if not rinfo.get("upright"):
                s = {"cx": s["cx"], "cy": s["cy"], "W": s["H"], "H": s["W"], "psi": 90.0}
            sheet(f"record {rec}", s, m_image_crop("record", F["tex"], rough=0.8, sheen=0.1), g["pos"][2] + g["size"][2])
    if "stick" in st and not B.STICK.get("standing"):
        stick_chart_v4(st["stick"])
    if B.V41:
        # the money tray's coins lying in it, and the globe in the near corner (all gated real scans)
        tr_ = st.get("tray")
        if tr_:
            c, a_ = tr_["centre"], math.radians(tr_["deg"])
            zf = tr_["z"] + B.TRAY["floor_t"]
            for k, (nm, dd) in enumerate((("FS-coin-dupondius-octavian", 0.029), ("FS-coin-sesterce-trajan", 0.034),
                                          ("jeton", 0.028))):
                off = (-0.10 + 0.045 * k, -0.04 + 0.02 * (k % 2))
                p = (c[0] + off[0] * math.cos(a_) - off[1] * math.sin(a_), c[1] + off[0] * math.sin(a_) + off[1] * math.cos(a_), zf)
                import_scan(nm, dd, p, yaw_deg=tr_["deg"] + 30 * k, lie_flat=True)
        import_scan("globe", B.GLOBE["d"] + 0.15, (2.03, 0.20, 0.0), yaw_deg=-30.0)

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
        qh, sh = gl["quad_half"], gl["stop_half"]
        for i in range(12):
            if P.get(f"quad{i + 1}"):
                ob = RS.box(f"type {i + 1} (blank)", (2 * qh[0], 2 * qh[1], 2 * qh[2]), (0, 0, 0), type_metal, 0.0002)
                RS.bake_track(ob, P[f"quad{i + 1}"], f0, f1)
        if P.get("stop"):
            ob = RS.box("end stop", (2 * sh[0], 2 * sh[1], 2 * sh[2]), (0, 0, 0), BRASS_M, 0.0002)
            RS.bake_track(ob, P["stop"], f0, f1)
    for n, kind in (("reel_reg", "reg"), ("reel_film", "film")):
        if P.get(n) and n in st:
            reel_v4(n, st[n], P[n], f0, f1, kind)
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
    lamp, iris = iris_lamp_v4()
    card = RS.bounce_card((0, 0, 0.1), (0, 0, 0))
    frames = list(range(f0 - 1, f1 + 2))
    eyes, tgts, focus, fst = [], [], [], []
    rec_g = geoms.get("record")
    a_, dsc, c_ = F["tail"][0], F["tail"][1], F["tail"][2]
    # one physical lamp, fixed over the table's near side, constant (founder, 2026-10-18: no lamp cues); exposure is the
    # camera's (expose.py meters each frame and keys the film exposure)
    lp, aim = Vector(LAMP["pos"]), Vector(LAMP["aim"])
    lamp.location = lp
    lamp.rotation_quaternion = (aim - lp).to_track_quat("-Z", "Y")
    lamp.data.energy = LAMP["energy"]
    lamp.data.spot_size = math.radians(LAMP["cone_deg"])
    lamp.data.spot_blend = LAMP["blend"]
    lamp.data.shadow_soft_size = LAMP["soft"]
    for key in ("X", "Y"):
        iris[key].outputs[0].default_value = 50.0
    iris["dark_x"].outputs[0].default_value = 99.0
    card.hide_render = True
    for f in frames:
        r = CR.at(cam_rows, f / FPS)
        eyes.append(Vector(r["eye"]))
        tgts.append(Vector(r["target"]))
        focus.append(r["focus"])
        fst.append(r["fstop"])
    RS.key_cam(cam, frames, eyes, tgts, focus, 4.0)
    for f, s_ in zip(frames, fst):
        cam.data.dof.aperture_fstop = s_
        cam.data.dof.keyframe_insert("aperture_fstop", frame=f)
    return sc, f0, f1


def main():
    import time
    t0 = time.time()
    Path("D:/document-media/title-sequence/run/tmp").mkdir(parents=True, exist_ok=True)
    bpy.context.preferences.filepaths.temporary_directory = "D:/document-media/title-sequence/run/tmp/"
    RS.ARGS["calib"] = A["calib"]
    sc, f0, f1 = build()
    RS.render_settings(sc)
    if A["calib"] and A.get("res"):
        sc.render.resolution_x, sc.render.resolution_y = (int(v) for v in A["res"].split("x"))
    if A["samples"]:
        sc.cycles.samples = int(A["samples"])
    sc.render.fps, sc.render.fps_base = FPSV
    RS.check_provenance()
    sc.frame_set(f0)
    out = A["out"] or f"D:/document-media/title-sequence/run/blend/take-{A['window']}.blend"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=out, compress=False)
    assert not sc.cycles.use_denoising and not sc.cycles.use_preview_denoising, "no denoiser (founder ruling)"
    print("RUN-BUILD " + json.dumps({"window": A["window"], "record": A["record"], "fps": A["fps"], "frames": [f0, f1],
                                     "blend": out, "images": sorted(RS.IMAGES), "build_s": round(time.time() - t0, 1),
                                     "denoise": bool(sc.cycles.use_denoising), "renderer": RS.renderer_line(sc)}))


if __name__ == "__main__":
    main()
