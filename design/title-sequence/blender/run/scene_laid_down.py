"""Laid Down: the series title in Blender (Cycles, no denoiser), from laid_down (the beats) and the bake.

    blender -b --factory-startup --python design/title-sequence/blender/run/scene_laid_down.py -- \
        --frame 708 --res 1920x1080 --samples 1024 --min_samples 512 --threshold 0.005 --exposure 0.0 \
        --out <png> [--meter 1] [--view Standard] [--record C20-METAR-0851] [--blur 1] [--blend <path>]

The scene (spec rev 2, sections 0-5): the v5c table grown to 4.0 x 2.0 m (eight oak boards of the C-02 scan) with a
bare top, no groove; the plaster room under a 4.3 m ceiling as the only fill; one wall-arm lamp (desk_v5.LAMP: 0.26 m shade, 90 W,
3400 K against a 4300 K white balance, 110 degree spread, the emitter inside its shade) at the spec's place, aimed at
the pile centre; the world black. The six sheets and the film's record are the bake's plates (each its real scan, real
thickness and own relief), keyed every frame from the bake's closed-form poses: centre, turn, the pile's height, the
trailing corner (shape key "lift") and the lie onto the pile (shape key "lie"). The record carries the chart scene's
flat-hold (lit diffuse paper mixed toward emission of the scan; its strength set against the view exposure so the
pose writes the scan's own values). One camera: 50 mm, f/8, 180 degree shutter, exactly top-down at 2.00 m over the
pile, fixed until the record enters, then the one descent. View transform Standard (the spec); --view AgX is its
stated fallback.

--meter 1: before the still, a 480x270 pass at exposure 0 to a scene-linear EXR; the exposure is set so the brightest
paper (the 99.5th percentile of max(R, G, B): the chart nearest the lamp) sits at 0.85 of display white, and printed
(spec rev 3, section 5). Run it on frame 708, the pile complete; every other frame takes that exposure (fixed for the
shot).
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import channel_v5c as C  # noqa: E402
import laid_down as L  # noqa: E402
import run_scene as RS  # noqa: E402
import run_take as RT  # noqa: E402

BAKE = Path("D:/document-media/title-sequence/laid-down/bake")
RELIEF = Path("D:/document-media/title-sequence/run/relief")
TMP = Path("D:/document-media/title-sequence/laid-down/tmp")
LIFT_REF = 0.003                      # the "lift" shape key at 1.0 is a 3 mm corner (the Atlas pair's: 1 mm)
TABLE = {**C.TABLE, "size": L.TABLE["size"], "boards": 8}   # rev 2: the v5c oak top grown to 4.0 x 2.0 m (0.25 m boards)
ROOM = {"wall_y": TABLE["size"][1] + 0.40, "near_y": -3.0, "side_x": (-1.6, 5.6), "ceiling_z": 4.30 - TABLE["height"],
        "plaster_albedo": 0.42, "floor_albedo": 0.06}          # desk_v5.ROOM's study (4.3 m ceiling) around the v5c table
LAMP = {**L.BEATS["lamp"]}
PAPER_WHITE_DISPLAY = 0.85
METER_PCT = 99.5


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    a = {"frame": "708", "res": "1920x1080", "samples": "1024", "min_samples": "512", "threshold": "0.005",
         "exposure": "0.0", "out": "", "meter": "0", "meter_res": "480x270", "meter_samples": "64", "view": "Standard",
         "record": "C20-METAR-0851", "blur": "1", "blend": ""}
    for i, k in enumerate(argv):
        if k.startswith("--") and i + 1 < len(argv):
            a[k[2:]] = argv[i + 1]
    return a


A = _args()


# ------------------------------------------------------------------------------------------------ the table and the room


def table_and_room():
    W, H = TABLE["size"]
    t = TABLE["top"]
    n = TABLE["boards"]
    joint = 0.0008
    bw = H / n
    for k in range(n):
        RS.box(f"oak board {k + 1}", (W, bw - joint, t), (W / 2, (k + 0.5) * bw, -t / 2),
               RT.m_oak_v4(f"oak board {k + 1}", seed=k * 0.37), bevel=0.0015)
    leg = RT.m_oak_v4("oak (trestles)", seed=5.0)
    hgt = TABLE["height"]
    for x in (TABLE["trestle_inset"], W - TABLE["trestle_inset"]):
        RS.box("trestle post", (0.09, 0.14, hgt - t - 0.10), (x, H / 2, -t - (hgt - t - 0.10) / 2 - 0.05), leg, 0.004)
        RS.box("trestle foot", (0.09, H - 0.30, 0.09), (x, H / 2, -hgt + 0.045), leg, 0.004)
        RS.box("trestle head", (0.09, H - 0.36, 0.05), (x, H / 2, -t - 0.025), leg, 0.004)
    RS.box("stretcher", (W - 2 * TABLE["trestle_inset"], 0.06, 0.08), (W / 2, H / 2, -hgt + 0.30), leg, 0.004)
    m, nt, b = RS._mat("plaster (room)")
    al = ROOM["plaster_albedo"]
    b.inputs["Base Color"].default_value = (al, al * 0.93, al * 0.84, 1.0)
    b.inputs["Roughness"].default_value = 0.95
    b.inputs["Specular IOR Level"].default_value = 0.2
    floor = RT.m_plain("floor boards (dark, matte)", (ROOM["floor_albedo"],) * 3, 0.8)
    cz = ROOM["ceiling_z"]
    x0, x1 = ROOM["side_x"]
    wy, ny = ROOM["wall_y"], ROOM["near_y"]
    Ly = wy - ny
    for name, size, loc, mat in (
            ("floor", (x1 - x0, Ly, 0.02), ((x0 + x1) / 2, (wy + ny) / 2, -hgt - 0.01), floor),
            ("ceiling", (x1 - x0, Ly, 0.02), ((x0 + x1) / 2, (wy + ny) / 2, cz + 0.01), m),
            ("far wall", (x1 - x0, 0.02, cz + hgt), ((x0 + x1) / 2, wy + 0.01, (cz - hgt) / 2), m),
            ("left wall", (0.02, Ly, cz + hgt), (x0 - 0.01, (wy + ny) / 2, (cz - hgt) / 2), m),
            ("right wall", (0.02, Ly, cz + hgt), (x1 + 0.01, (wy + ny) / 2, (cz - hgt) / 2), m),
            ("near wall", (x1 - x0, 0.02, cz + hgt), ((x0 + x1) / 2, ny - 0.01, (cz - hgt) / 2), m)):
        RS.box(name, size, loc, mat)


def the_lamp():
    """desk_v5.LAMP moved with the pile (spec section 5); the emitter inside its spun-steel shade, the arm to the wall
    (scene_v5c.the_lamp's build). Nothing else emits."""
    pos, aim = Vector(LAMP["pos_m"]), Vector(LAMP["aim_m"])
    d = bpy.data.lights.new("the wall-arm lamp", "AREA")
    d.shape = "DISK"
    d.size = LAMP["shade_d_m"] * 0.86
    d.energy = LAMP["power_w"]
    d.spread = math.radians(LAMP["spread_deg"])
    d.use_nodes = True
    nt = d.node_tree
    bb = nt.nodes.new("ShaderNodeBlackbody")
    bb.inputs[0].default_value = LAMP["kelvin"]
    wb = nt.nodes.new("ShaderNodeBlackbody")
    wb.inputs[0].default_value = LAMP["white_balance_k"]
    dv = nt.nodes.new("ShaderNodeVectorMath")
    dv.operation = "DIVIDE"
    nt.links.new(bb.outputs[0], dv.inputs[0])
    nt.links.new(wb.outputs[0], dv.inputs[1])
    nt.links.new(dv.outputs[0], nt.nodes["Emission"].inputs["Color"])
    ob = bpy.data.objects.new("the wall-arm lamp", d)
    bpy.context.scene.collection.objects.link(ob)
    ob.rotation_mode = "QUATERNION"
    ob.rotation_quaternion = (aim - pos).to_track_quat("-Z", "Y")
    ob.location = pos
    ob.visible_camera = False
    shade = RT.m_worn("spun steel shade (dark)", (0.05, 0.05, 0.05), 0.45, (0.03, 0.03, 0.03), scratch=0.2)
    bpy.ops.mesh.primitive_cone_add(vertices=96, radius1=LAMP["shade_d_m"] / 2, radius2=0.045, depth=0.20,
                                    end_fill_type="NOTHING")
    sh = bpy.context.active_object
    sh.name = "lamp shade (spun steel)"
    sh.modifiers.new("t", "SOLIDIFY").thickness = 0.0012
    sh.data.materials.append(shade)
    sh.rotation_mode = "QUATERNION"
    sh.rotation_quaternion = (pos - aim).to_track_quat("Z", "Y")
    sh.location = pos + (pos - aim).normalized() * 0.08
    top = pos + (pos - aim).normalized() * 0.2
    wall = Vector((top.x, ROOM["wall_y"], top.z + 0.15))
    bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=0.008, depth=(wall - top).length, location=(top + wall) / 2)
    arm = bpy.context.active_object
    arm.name = "lamp arm (brass)"
    arm.rotation_mode = "QUATERNION"
    arm.rotation_quaternion = (wall - top).to_track_quat("Z", "Y")
    arm.data.materials.append(RT.m_worn("brass (worn)", (0.62, 0.44, 0.18), 0.42, (0.24, 0.20, 0.10)))
    return ob


# ------------------------------------------------------------------------------------------------ materials


def margin(pl):
    """The plate's fibre colour: the Run's relief record where the sheet has one, else the bake's (same method)."""
    p = RELIEF / f"{pl['name']}.json"
    if p.exists():
        return tuple(json.loads(p.read_text(encoding="utf-8"))["margin_rgb_linear"])
    return tuple(pl["margin_rgb_linear"])


def m_mount(pl):
    """The Turin papyrus on its linen mount: the keyed scan on its own place on the mount (CLIP outside it), the
    pinned linen photo-scan (C-03, at its real 0.27 m) wherever the scan's alpha is not (run_take.m_scan_on_backing)."""
    m, nt, b = RS._mat("papyrus on its linen mount")
    u0, v0, u1, v1 = pl["uv"]
    uvn = RS._n(nt, "ShaderNodeUVMap")
    mp = RS._n(nt, "ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (1 / (u1 - u0), 1 / (v1 - v0), 1)
    mp.inputs["Location"].default_value = (-u0 / (u1 - u0), -v0 / (v1 - v0), 0)
    nt.links.new(uvn.outputs["UV"], mp.inputs["Vector"])
    t = RS._n(nt, "ShaderNodeTexImage")
    t.image = RS.tex(pl["tex"])
    t.interpolation = "Cubic"
    t.extension = "CLIP"
    nt.links.new(mp.outputs["Vector"], t.inputs["Vector"])
    co = RS._n(nt, "ShaderNodeTexCoord")
    lm = RS._n(nt, "ShaderNodeMapping")
    lm.inputs["Scale"].default_value = (1 / 0.27, 1 / 0.27, 1)
    nt.links.new(co.outputs["Object"], lm.inputs["Vector"])
    lin = RS._n(nt, "ShaderNodeTexImage")
    lin.image = RS.tex("C-03_diff")
    nt.links.new(lm.outputs["Vector"], lin.inputs["Vector"])
    mix = RS._n(nt, "ShaderNodeMix")
    mix.data_type = "RGBA"
    nt.links.new(t.outputs["Alpha"], mix.inputs[0])
    nt.links.new(lin.outputs["Color"], mix.inputs[6])
    nt.links.new(t.outputs["Color"], mix.inputs[7])
    nt.links.new(mix.outputs[2], b.inputs["Base Color"])
    bw = RS._n(nt, "ShaderNodeRGBToBW")
    nt.links.new(mix.outputs[2], bw.inputs["Color"])
    bp = RS._n(nt, "ShaderNodeBump", Strength=0.15, Distance=0.0002)
    nt.links.new(bw.outputs["Val"], bp.inputs["Height"])
    nt.links.new(bp.outputs["Normal"], b.inputs["Normal"])
    b.inputs["Roughness"].default_value = 0.75
    b.inputs["Specular IOR Level"].default_value = 0.3
    b.inputs["Sheen Weight"].default_value = 0.2
    return m


def m_record_flat_hold(image, exposure_ev):
    """chart_scene.m_record (the flat-hold): lit diffuse paper (dead matte: no gloss, no sheen, the v5c A7 lesson)
    mixed toward pure emission of the scan; the mix is keyed per frame (laid_down.hold_mix). The emission's strength is
    2^-EV against the fixed view exposure, so at the pose the frame's pixels are the scan's own values."""
    m = bpy.data.materials.new(f"record {image} flat-hold")
    m.use_nodes = True
    nt = m.node_tree
    out = nt.nodes["Material Output"]
    bsdf = nt.nodes["Principled BSDF"]
    t = RS._n(nt, "ShaderNodeTexImage")
    t.image = RS.tex(image)
    t.interpolation = "Linear"
    t.extension = "EXTEND"
    nt.links.new(t.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 1.0
    bsdf.inputs["Specular IOR Level"].default_value = 0.0
    bsdf.inputs["Sheen Weight"].default_value = 0.0
    em = RS._n(nt, "ShaderNodeEmission", Strength=2.0 ** -exposure_ev)
    nt.links.new(t.outputs["Color"], em.inputs["Color"])
    val = nt.nodes.new("ShaderNodeValue")
    val.name = val.label = "flat_hold"
    ms = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(val.outputs[0], ms.inputs[0])
    nt.links.new(bsdf.outputs[0], ms.inputs[1])
    nt.links.new(em.outputs[0], ms.inputs[2])
    nt.links.new(ms.outputs[0], out.inputs["Surface"])
    return m, val


def plate_materials(pl, exposure_ev):
    nm, kind = pl["name"], pl["kind"]
    side_rgb = margin(pl)
    if nm.startswith("record "):
        top, val = m_record_flat_hold(pl["tex"], exposure_ev)
        return top, RT.fibre(nm, side_rgb), val
    if kind == "mount":
        top = m_mount(pl)
    elif kind == "board":
        top = RT.m_image_crop(nm, pl["tex"], rough=0.7, sheen=0.1, bump=0.1)
    elif kind == "keyed":
        top = RT.m_image_crop(nm, pl["tex"], rough=0.72, alpha=True, sheen=0.15, bump=0.15)
    else:
        rough, sheen, bump = {"leaf": (0.72, 0.15, 0.15), "ino": (0.75, 0.2, 0.12)}.get(nm, (0.75, 0.15, 0.1))
        top = RT.m_image_crop(nm, pl["tex"], rough=rough, sheen=sheen, bump=bump)
    return top, RT.fibre(nm, side_rgb), None


# ------------------------------------------------------------------------------------------------ the plates


def plate_mesh(name, pl, top, bot, mask, lift, lie, top_mat, side_mat):
    """A plate in its sheet's own frame (run_take.sheet_mesh's build from arrays): the face at its top, the underside
    at its bottom, walls along the footprint's outline; shape keys "lift" (the trailing corner at LIFT_REF) and "lie"
    (onto the pile at rest)."""
    W, H = pl["size"]
    nv, nu = top.shape
    u = -W / 2 + (np.arange(nu) + 0.5) * W / nu + pl["at"][0]
    v = H / 2 - (np.arange(nv) + 0.5) * H / nv + pl["at"][1]
    X, Y = np.meshgrid(u, v)
    idx = np.arange(nv * nu).reshape(nv, nu)
    keep = mask[:-1, :-1] & mask[1:, :-1] & mask[:-1, 1:] & mask[1:, 1:]
    jj, ii = np.nonzero(keep)
    a_, b_, c_, d_ = idx[jj, ii], idx[jj, ii + 1], idx[jj + 1, ii + 1], idx[jj + 1, ii]
    n = nv * nu
    verts = np.concatenate([np.stack([X.ravel(), Y.ravel(), top.ravel()], 1),
                            np.stack([X.ravel(), Y.ravel(), bot.ravel()], 1)])
    faces = [np.stack([a_, d_, c_, b_], 1), np.stack([a_ + n, b_ + n, c_ + n, d_ + n], 1)]
    mats = [np.zeros(len(a_), np.int32), np.ones(len(a_), np.int32)]
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
    uvv = np.concatenate([np.stack([(np.arange(nu)[None, :].repeat(nv, 0) + 0.5) / nu,
                                    1 - (np.arange(nv)[:, None].repeat(nu, 1) + 0.5) / nv], -1).reshape(-1, 2)] * 2)[used]
    uvl = me.uv_layers.new()
    uvl.data.foreach_set("uv", uvv[faces.ravel()].astype(np.float32).ravel())
    me.polygons.foreach_set("use_smooth", np.ones(len(faces), bool))
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    me.materials.append(top_mat)
    me.materials.append(side_mat)
    ob.shape_key_add(name="Basis", from_mix=False)
    ref = 0.001 if pl["kind"] == "board" else LIFT_REF
    for kname, dz in (("lift", lift * ref), ("lie", lie)):
        k = ob.shape_key_add(name=kname, from_mix=False)
        k.slider_min, k.slider_max = 0.0, 1.0
        d2 = np.concatenate([dz.ravel(), dz.ravel()])[used]
        co = verts.copy()
        co[:, 2] += d2
        k.data.foreach_set("co", co.astype(np.float32).ravel())
    return ob, ref



def _interp(idb, kind):
    ad = idb.animation_data
    if ad and ad.action:
        for fc in RS._fcurves(ad.action):
            for kp in fc.keyframe_points:
                kp.interpolation = "CONSTANT" if fc.data_path in ("hide_render", "hide_viewport") else kind


def key_sheet(obs, rows, ref, frames):
    """Keys every frame where the sheet moves or settles, and its first and last: centre, turn, z, the keys, the
    visibility (constant)."""
    for f in frames:
        r = rows[f]
        for ob in obs:
            ob.location = (L.P[0] + r["c"][0], L.P[1] + r["c"][1], r["z"])
            ob.rotation_euler = (0.0, 0.0, math.radians(r["psi"]))
            ob.hide_render = not r["vis"]
            ob.keyframe_insert("location", frame=f)
            ob.keyframe_insert("rotation_euler", frame=f)
            ob.keyframe_insert("hide_render", frame=f)
            kb = ob.data.shape_keys.key_blocks
            kb["lift"].value = r["lift"] / ref
            kb["lie"].value = r["lie"]
            kb["lift"].keyframe_insert("value", frame=f)
            kb["lie"].keyframe_insert("value", frame=f)
    for ob in obs:
        _interp(ob, "LINEAR")
        _interp(ob.data.shape_keys, "LINEAR")


def active_frames(rows):
    """The frames at which a sheet's pose changes, padded by two, plus the shot's first and last."""
    out = {0, len(rows) - 1}
    prev = None
    for r in rows:
        sig = (r["c"][0], r["c"][1], r["psi"], r["z"], r["lift"], r["lie"], r["vis"])
        if sig != prev:
            out |= {max(0, r["f"] - 2), max(0, r["f"] - 1), r["f"], min(len(rows) - 1, r["f"] + 1),
                    min(len(rows) - 1, r["f"] + 2)}
        prev = sig
    return sorted(out)


def build(exposure_ev):
    RS.FPS = 30
    sc = RS.reset(0, L.FRAMES - 1)
    sc.render.fps, sc.render.fps_base = L.FPS_NUM, L.FPS_DEN
    sc.world.node_tree.nodes["Background"].inputs[0].default_value = (0.0, 0.0, 0.0, 1)
    table_and_room()
    the_lamp()
    bake = json.loads((BAKE / "poses.json").read_text(encoding="utf-8"))
    arr = np.load(BAKE / "plates.npz")
    rec_key = f"R {A['record']}"
    flat = None
    for sid in [s["id"] for s in L.SHEETS] + [rec_key]:
        plates = [p for p in bake["plates"] if p["sheet"] == sid]
        obs, ref = [], LIFT_REF
        for pl in plates:
            top_m, side_m, val = plate_materials(pl, exposure_ev)
            flat = val or flat
            nm = pl["name"]
            ob, ref = plate_mesh(f"{sid} {nm} ({pl['tex']})", pl, arr[f"{nm}|top"], arr[f"{nm}|bottom"],
                                 arr[f"{nm}|mask"], arr[f"{nm}|lift"], arr[f"{nm}|lie"], top_m, side_m)
            obs.append(ob)
        rows = bake["poses"][sid]
        key_sheet(obs, rows, ref, active_frames(rows))
    if flat is not None:
        fh = L.RECORDS[A["record"]]["flat_hold"]
        a, b = fh["ramp_from_frame"], fh["one_from_frame"]
        for f in sorted({0, a - 1, L.FRAMES - 1} | set(range(a, b + 1))):
            flat.outputs[0].default_value = L.hold_mix(f)
            flat.outputs[0].keyframe_insert("default_value", frame=f)
    return sc


def camera(sc):
    cam = RS.camera(L.LENS_MM)
    sc.camera = cam
    cam.data.dof.use_dof = True
    cam.data.dof.aperture_fstop = L.CAM["fstop"]
    rep = json.loads((BAKE / "report.json").read_text(encoding="utf-8"))
    pile_top = max(v.get("pile_top_mm", 0.0) for v in rep["rest"].values()) / 1e3   # focus on the pile's surface
    for f in sorted({0, L.DESCENT[0]} | set(range(L.DESCENT[0], L.DESCENT[1] + 1)) | {L.FRAMES - 1}):
        eye, roll = L.camera_at(A["record"], f)
        cam.location = eye
        cam.rotation_euler = (0.0, 0.0, math.radians(roll))
        cam.data.dof.focus_distance = eye[2] - pile_top
        cam.keyframe_insert("location", frame=f)
        cam.keyframe_insert("rotation_euler", frame=f)
        cam.data.dof.keyframe_insert("focus_distance", frame=f)
    _interp(cam, "LINEAR")
    _interp(cam.data, "LINEAR")
    return cam


def settings(sc, res, samples, min_samples, threshold, fmt="PNG"):
    sc.render.engine = "CYCLES"
    cy = sc.cycles
    cy.device = "GPU"
    rx, ry = (int(v) for v in res.split("x"))
    sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = rx, ry, 100
    cy.samples = int(samples)
    cy.use_adaptive_sampling = True
    cy.adaptive_threshold = float(threshold)
    cy.adaptive_min_samples = min(int(min_samples), cy.samples)
    # NO denoiser of any kind (founder ruling: no AI pixels; tests/test_no_denoise.py)
    cy.use_denoising = False
    cy.use_preview_denoising = False
    cy.sample_clamp_direct = 0.0
    cy.sample_clamp_indirect = 5.0
    cy.max_bounces, cy.diffuse_bounces, cy.glossy_bounces, cy.transmission_bounces = 10, 4, 4, 8
    cy.transparent_max_bounces = 16                  # Piri Reis's keyed edge
    cy.caustics_reflective = cy.caustics_refractive = False
    cy.texture_limit_render = "8192"
    cy.seed = 0
    sc.render.use_motion_blur = A["blur"] == "1"
    sc.render.motion_blur_shutter = L.CAM["shutter_deg"] / 360.0
    sc.render.use_compositing = False
    sc.view_settings.view_transform = A["view"]
    sc.view_settings.look = "None"
    s = sc.render.image_settings
    if fmt == "EXR":
        s.file_format, s.color_mode, s.color_depth, s.exr_codec = "OPEN_EXR", "RGB", "32", "NONE"
    else:
        s.file_format, s.color_mode, s.color_depth = "PNG", "RGB", "16"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for kind in ("OPTIX", "CUDA"):
        try:
            prefs.compute_device_type = kind
            prefs.get_devices()
            if any(d.type == kind for d in prefs.devices):
                for d in prefs.devices:
                    d.use = d.type == kind
                break
        except TypeError:
            continue


def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def meter(sc):
    """Paper white at exposure 0 in scene-linear (the 95th percentile of luminance), from a small EXR pass."""
    settings(sc, A["meter_res"], A["meter_samples"], 16, 0.02, fmt="EXR")
    sc.view_settings.exposure = 0.0
    p = TMP / f"meter-f{int(A['frame']):04d}.exr"
    sc.render.filepath = str(p)
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(str(p), check_existing=False)
    w, h = img.size
    px = np.array(img.pixels[:], np.float32).reshape(h, w, 4)
    bpy.data.images.remove(img)
    # rev 3: the brightest channel, not luminance (under the 3400 K lamp red leads; rev 2's luminance meter clipped red)
    M = px[..., :3].max(-1)
    white = float(np.percentile(M, METER_PCT))
    ev = math.log2(srgb_to_linear(PAPER_WHITE_DISPLAY) / white)
    return {"paper_white_max_channel_linear": white, "percentile": METER_PCT, "p50": float(np.percentile(M, 50)),
            "max": float(M.max()), "ev": ev, "s": None}


def main():
    t0 = time.time()
    TMP.mkdir(parents=True, exist_ok=True)
    bpy.context.preferences.filepaths.temporary_directory = str(TMP) + "/"
    ev = float(A["exposure"])
    sc = build(ev)
    cam = camera(sc)
    RS.check_provenance()
    sc.frame_set(int(A["frame"]))
    info = {"frame": int(A["frame"]), "view": A["view"], "record": A["record"], "build_s": round(time.time() - t0, 1)}
    if A["meter"] == "1":
        tm = time.time()
        mt = meter(sc)
        mt["s"] = round(time.time() - tm, 1)
        ev = mt["ev"]
        info["meter"] = mt
        # the record's flat-hold emission follows the exposure the shot now has
        for m in bpy.data.materials:
            if m.name.endswith("flat-hold"):
                for nd in m.node_tree.nodes:
                    if nd.type == "EMISSION":
                        nd.inputs["Strength"].default_value = 2.0 ** -ev
        print("LD-METER " + json.dumps(mt), flush=True)
    settings(sc, A["res"], A["samples"], A["min_samples"], A["threshold"])
    sc.view_settings.exposure = ev
    if A["blend"]:
        bpy.ops.wm.save_as_mainfile(filepath=A["blend"], compress=False)
    sc.render.filepath = A["out"]
    tr = time.time()
    bpy.ops.render.render(write_still=True)
    assert not sc.cycles.use_denoising and not sc.cycles.use_preview_denoising, "no denoiser (founder ruling)"
    info.update({"out": A["out"], "res": A["res"], "samples": sc.cycles.samples, "min_samples": sc.cycles.adaptive_min_samples,
                 "threshold": sc.cycles.adaptive_threshold, "exposure": sc.view_settings.exposure,
                 "view_transform": sc.view_settings.view_transform, "motion_blur": sc.render.use_motion_blur,
                 "shutter": sc.render.motion_blur_shutter, "camera": list(cam.location),
                 "fstop": cam.data.dof.aperture_fstop, "focus": cam.data.dof.focus_distance,
                 "lights": [o.name for o in bpy.data.objects if o.type == "LIGHT"],
                 "emitters": [m.name for m in bpy.data.materials if m.node_tree and any(
                     n.type == "EMISSION" for n in m.node_tree.nodes)],
                 "images": sorted(RS.IMAGES), "denoise": False, "renderer": RS.renderer_line(sc),
                 "render_s": round(time.time() - tr, 1), "s": round(time.time() - t0, 1)})
    print("LD-STILL " + json.dumps(info), flush=True)


if __name__ == "__main__":
    main()
