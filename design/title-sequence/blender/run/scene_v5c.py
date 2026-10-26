"""The Run v5c: the whole shot in Blender (Cycles, no denoiser). Built from channel_v5c (geometry), the MuJoCo bake
(sim_v5c) and shot_v5c (marble and camera, frame by frame).

    blender -b --factory-startup --python design/title-sequence/blender/run/scene_v5c.py -- \
        --fps 30000/1001 --res 2560x1440 --samples 1024 --threshold 0.01 --min_samples 64 \
        --frames 0:1090 [--step 1] --out <dir> [--expo <json>] [--blur 1] [--blend <path>] [--record S-130]

The scene: a 3.0 x 1.7 m oak refectory top (7 glued boards, the C-02 scan) with the channel carved in it (the cove, the
banks, the two steps, the low release block, the felt well), flush leather in the floor, the seven placements beside the
groove (real scans and archive images only: run-scan-ledger.json and the tex manifests), the film's record on the felt,
the stick chart on the wall, one wall-arm lamp in its shade (3400 K against a 4300 K white balance) and the plaster room
as the only fill. The exposure is the camera's own, metered outside Blender (final_v5c.py) and keyed per frame.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import channel_v5c as C  # noqa: E402
import run_scene as RS  # noqa: E402
import run_take as RT  # noqa: E402
import shot_v5c as SH  # noqa: E402

SIM = Path("D:/document-media/title-sequence/run/sim/v5c")
RELIEF = Path("D:/document-media/title-sequence/run/relief")


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    a = {"fps": "30000/1001", "res": "2560x1440", "samples": "1024", "threshold": "0.01", "min_samples": "64",
         "frames": "0:0", "step": "1", "out": "", "expo": "", "blur": "1", "blend": "", "exposure": "0.0",
         "record": "C20-METAR-0851", "rec_spec": "0.0", "exr": "", "vs": ""}
    for i, k in enumerate(argv):
        if k.startswith("--") and i + 1 < len(argv):
            a[k[2:]] = argv[i + 1]
    return a


A = _args()
FPSV = (30000, 1001) if A["fps"] in ("30000/1001", "29.97") else (int(A["fps"]), 1)
FPS = FPSV[0] / FPSV[1]


# ------------------------------------------------------------------------------------------------ the carved top


def _axis(lo, hi, coarse, fine_ranges, breaks):
    v = [np.arange(lo, hi + 1e-9, coarse)]
    for a, b, d in fine_ranges:
        v.append(np.arange(max(a, lo), min(b, hi) + 1e-9, d))
    for e in breaks:
        v.append(np.array([e - 0.00005, e + 0.00005]))
    v = np.unique(np.round(np.concatenate(v), 6))
    keep = [v[0]]
    for x in v[1:]:
        if x - keep[-1] > 0.00004:
            keep.append(x)
    return np.clip(np.array(keep), lo, hi)


def carved_top(oak_mats, leather_mat):
    W, H = C.TABLE["size"]
    t1x, t2x = C.TURN1_C[0], C.TURN2_C[0]
    xs = _axis(0.0, W, 0.002, [(t2x - C.R_TURN - 0.03, t2x + 0.04, 0.0006), (t1x - 0.04, t1x + C.R_TURN + 0.03, 0.0006),
                               (C.BLOCK["x"][0] - 0.01, C.BLOCK["x"][1] + 0.02, 0.0005)],
               [C.WELL["x"][0], C.WELL["x"][1], C.BLOCK["x"][0], C.BLOCK["x"][1]])
    yf = [(y - 0.018, y + 0.018, 0.0005) for y in C.REACH_Y]
    ys = _axis(0.0, H, 0.002, yf, [C.WELL["y"][0], C.WELL["y"][1], C.BLOCK["y"][0], C.BLOCK["y"][1]])
    nx, ny = len(xs), len(ys)
    Z = np.zeros((ny, nx))
    for r0 in range(0, ny, 64):
        Y, X = np.meshgrid(ys[r0:r0 + 64], xs, indexing="ij")
        Z[r0:r0 + 64] = C.height(X, Y)
    Y, X = np.meshgrid(ys, xs, indexing="ij")
    verts = np.stack([X.ravel(), Y.ravel(), Z.ravel()], 1).astype(np.float32)
    idx = np.arange(nx * ny).reshape(ny, nx)
    faces = np.stack([idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel(), idx[1:, 1:].ravel(), idx[1:, :-1].ravel()], 1)
    me = bpy.data.meshes.new("oak top (carved)")
    me.vertices.add(len(verts))
    me.vertices.foreach_set("co", verts.ravel())
    me.loops.add(faces.size)
    me.loops.foreach_set("vertex_index", faces.astype(np.int32).ravel())
    me.polygons.add(len(faces))
    me.polygons.foreach_set("loop_start", (np.arange(len(faces)) * 4).astype(np.int32))
    me.update(calc_edges=True)
    # materials: the board each face lies on, leather where the floor is let in
    xc = (X[:-1, :-1] + X[1:, 1:]).ravel() / 2
    yc = (Y[:-1, :-1] + Y[1:, 1:]).ravel() / 2
    board = np.clip((yc / (H / C.TABLE["boards"])).astype(int), 0, C.TABLE["boards"] - 1)
    s, u, k = C.project(xc, yc)
    leather = C.on_leather(s, u) & np.isfinite(u)
    mi = np.where(leather, C.TABLE["boards"], board).astype(np.int32)
    for m in oak_mats:
        me.materials.append(m)
    me.materials.append(leather_mat)
    me.polygons.foreach_set("material_index", mi)
    me.polygons.foreach_set("use_smooth", np.ones(len(faces), bool))
    ob = bpy.data.objects.new("oak top (carved)", me)
    bpy.context.scene.collection.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    try:
        bpy.ops.object.shade_smooth_by_angle(angle=math.radians(35.0))
    except Exception:
        pass
    print(f"carved top: {nx} x {ny} = {nx * ny} vertices")
    return ob


def slab_and_trestles(oak_side, oak_leg):
    W, H = C.TABLE["size"]
    t = C.TABLE["top"]
    e = 0.010
    for nm, size, loc in (("slab edge near", (W, e, t), (W / 2, e / 2, -t / 2)),
                          ("slab edge far", (W, e, t), (W / 2, H - e / 2, -t / 2)),
                          ("slab edge left", (e, H, t), (e / 2, H / 2, -t / 2)),
                          ("slab edge right", (e, H, t), (W - e / 2, H / 2, -t / 2)),
                          ("slab underside", (W - 0.004, H - 0.004, 0.040), (W / 2, H / 2, -t + 0.020))):
        b = RS.box(nm, size, loc, oak_side, bevel=0.002 if "edge" in nm else 0.0)
        b.location.z -= 0.0003
    hgt = C.TABLE["height"]
    for x in (C.TABLE["trestle_inset"], W - C.TABLE["trestle_inset"]):
        RS.box("trestle post", (0.09, 0.14, hgt - t - 0.10), (x, H / 2, -t - (hgt - t - 0.10) / 2 - 0.05), oak_leg, 0.004)
        RS.box("trestle foot", (0.09, H - 0.30, 0.09), (x, H / 2, -hgt + 0.045), oak_leg, 0.004)
        RS.box("trestle head", (0.09, H - 0.36, 0.05), (x, H / 2, -t - 0.025), oak_leg, 0.004)
    RS.box("stretcher", (W - 2 * C.TABLE["trestle_inset"], 0.06, 0.08), (W / 2, H / 2, -hgt + 0.30), oak_leg, 0.004)


# ------------------------------------------------------------------------------------------------ sheets


def _mesh_from_grid(name, P, UV, mat, side_mat=None, thick=0.0002):
    nv, nu = P.shape[:2]
    verts = P.reshape(-1, 3).astype(np.float32)
    idx = np.arange(nu * nv).reshape(nv, nu)
    faces = np.stack([idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel(), idx[1:, 1:].ravel(), idx[1:, :-1].ravel()], 1)
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(verts))
    me.vertices.foreach_set("co", verts.ravel())
    me.loops.add(faces.size)
    me.loops.foreach_set("vertex_index", faces.astype(np.int32).ravel())
    me.polygons.add(len(faces))
    me.polygons.foreach_set("loop_start", (np.arange(len(faces)) * 4).astype(np.int32))
    me.update(calc_edges=True)
    uv = me.uv_layers.new()
    uv.data.foreach_set("uv", UV.reshape(-1, 2)[faces.ravel()].astype(np.float32).ravel())
    me.polygons.foreach_set("use_smooth", np.ones(len(faces), bool))
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    me.materials.append(mat)
    if side_mat is not None:
        me.materials.append(side_mat)
    so = ob.modifiers.new("thickness", "SOLIDIFY")
    so.thickness, so.offset = thick, -1
    so.material_offset_rim = 1 if side_mat is not None else 0
    return ob


def flat_sheet(name, rect, z, mat, side_mat=None, thick=0.0002, turn=False, lift=0.0015, n=(120, 120)):
    """A sheet lying on the oak (or on what is under it) at its real size, with a slight cockle and one free corner
    lifted a little; turn=True lays the image turned a quarter (its width along y)."""
    x0, x1, y0, y1 = rect
    U, V = np.meshgrid(np.linspace(0, 1, n[0]), np.linspace(0, 1, n[1]))
    X = x0 + U * (x1 - x0)
    Y = y0 + V * (y1 - y0)
    r = np.hypot(np.clip(U - 0.8, 0, None), np.clip(V - 0.8, 0, None)) / 0.2
    Zs = z + thick + 0.0001 + 0.0003 * (0.5 + 0.5 * np.sin(U * 9.1) * np.sin(V * 7.3)) + lift * np.clip(r, 0, 1) ** 2
    P = np.stack([X, Y, Zs], -1)
    UV = np.stack([V, 1 - U], -1) if turn else np.stack([U, V], -1)
    return _mesh_from_grid(name, P, UV, mat, side_mat, thick)


def rolled_sheet(name, it, full_len, mat, side_mat=None, thick=0.0003):
    """A large sheet kept partly rolled (plan section 3): flat over its open length from the open edge, then rolled up
    on the oak, the roll's turns spiralling in. The image runs from the open edge into the roll; the visible part is
    the open length. it['roll'] = {axis: the roll's axis ('x' or 'y'), at: where the flat part ends, r: outer radius}."""
    x0, x1, y0, y1 = it["rect"]
    ro = it["roll"]
    R0 = ro["r"]
    open_len = it["open"]
    rest = full_len - open_len
    n_len = 400
    n_w = 60
    ell = np.linspace(0, full_len, n_len)
    w = np.linspace(0, 1, n_w)
    # along the length: flat then a spiral (pitch 1.2 mm a turn) sitting on the oak
    pitch = 0.0012
    phi_max = rest / R0 * 1.15
    flat = ell <= open_len
    ph = np.clip((ell - open_len) / R0, 0, None)
    rad = np.maximum(R0 - pitch * ph / (2 * math.pi), R0 * 0.35)
    a = np.where(flat, 0.0, ph)
    along = np.where(flat, ell, open_len + rad * np.sin(a))
    up = np.where(flat, 0.0, R0 - rad * np.cos(a))
    _ = phi_max
    L, Wd = np.meshgrid(along, w)
    Zu, _w = np.meshgrid(up, w)
    if ro["axis"] == "x":                     # the length runs along +y from the open edge y0 to the roll at y1
        X = x0 + Wd * (x1 - x0)
        Y = y0 + L
        UV = np.stack([Wd, np.meshgrid(ell / full_len, w)[0]], -1)
    else:                                     # along +x from the open edge x0 to the roll at x1
        X = x0 + L
        Y = y0 + Wd * (y1 - y0)
        UV = np.stack([np.meshgrid(ell / full_len, w)[0], Wd], -1)
    Z = Zu + thick + 0.0001 + 0.00025 * (0.5 + 0.5 * np.sin(X * 31.0) * np.sin(Y * 23.0))
    P = np.stack([X, Y, Z], -1)
    return _mesh_from_grid(name, P, UV, mat, side_mat, thick)


def margin(nm):
    p = RELIEF / f"{nm}.json"
    if p.exists():
        return tuple(json.loads(p.read_text(encoding="utf-8"))["margin_rgb_linear"])
    return (0.55, 0.47, 0.36)


# ------------------------------------------------------------------------------------------------ scans


def _bake_world(ob):
    bpy.context.view_layer.update()
    me = ob.data
    me.transform(ob.matrix_world)
    ob.matrix_world = Matrix.Identity(4)
    return np.array([v.co[:] for v in me.vertices])


def scan_flat(sid, dia, x, y, z, spin_deg=0.0, flip=False):
    """A gated coin scan lying flat: its thinnest principal axis turned to vertical, its lowest point on z."""
    ob = RT.import_scan(sid, dia, (0.0, 0.0, 0.0))
    co = _bake_world(ob)
    c = co.mean(0)
    w_, V = np.linalg.eigh(np.cov((co - c).T))
    e3 = V[:, 0] / np.linalg.norm(V[:, 0])
    e1 = V[:, 2] - e3 * float(V[:, 2] @ e3)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(e3, e1)
    R0 = Matrix((tuple(e1), tuple(e2), tuple(e3)))
    M = Matrix.Rotation(math.radians(spin_deg), 3, "Z") @ (Matrix.Rotation(math.pi, 3, "X") if flip else
                                                           Matrix.Identity(3)) @ R0
    ob.data.transform(M.to_4x4() @ Matrix.Translation(Vector(-c)))
    co = np.array([v.co[:] for v in ob.data.vertices])
    ob.location = (x, y, z - co[:, 2].min())
    ob.name = f"{sid} (real scan)"
    return ob


def upright_scan(sid, size, loc, rx_deg, yaw_deg=0.0):
    ob = RT.import_scan(sid, size, (0.0, 0.0, 0.0))
    co = _bake_world(ob)
    mid = (co.max(0) + co.min(0)) / 2
    ob.data.transform(Matrix.Translation(Vector((-mid[0], -mid[1], -mid[2]))))
    ob.data.transform(Matrix.Rotation(math.radians(yaw_deg), 4, "Z") @ Matrix.Rotation(math.radians(rx_deg), 4, "X"))
    co = np.array([v.co[:] for v in ob.data.vertices])
    ob.location = (loc[0], loc[1], loc[2] - co[:, 2].min())
    ob.name = f"{sid} (real scan)"
    return ob


# ------------------------------------------------------------------------------------------------ room and lamp


def m_plaster(name, albedo):
    m, nt, b = RS._mat(name)
    b.inputs["Base Color"].default_value = (albedo, albedo * 0.93, albedo * 0.84, 1.0)
    b.inputs["Roughness"].default_value = 0.95
    b.inputs["Specular IOR Level"].default_value = 0.2
    return m


def room():
    R_ = C.ROOM
    hgt = C.TABLE["height"]
    plaster = m_plaster("plaster (room)", R_["plaster_albedo"])
    floor = RT.m_plain("floor boards (dark, matte)", (R_["floor_albedo"],) * 3, 0.8)
    cz = R_["ceiling_z"]
    x0, x1 = R_["side_x"]
    wy, ny = R_["wall_y"], R_["near_y"]
    L = wy - ny
    for name, size, loc, mat in (
            ("floor", (x1 - x0, L, 0.02), ((x0 + x1) / 2, (wy + ny) / 2, -hgt - 0.01), floor),
            ("ceiling", (x1 - x0, L, 0.02), ((x0 + x1) / 2, (wy + ny) / 2, cz + 0.01), plaster),
            ("far wall", (x1 - x0, 0.02, cz + hgt), ((x0 + x1) / 2, wy + 0.01, (cz - hgt) / 2), plaster),
            ("left wall", (0.02, L, cz + hgt), (x0 - 0.01, (wy + ny) / 2, (cz - hgt) / 2), plaster),
            ("right wall", (0.02, L, cz + hgt), (x1 + 0.01, (wy + ny) / 2, (cz - hgt) / 2), plaster),
            ("near wall", (x1 - x0, 0.02, cz + hgt), ((x0 + x1) / 2, ny - 0.01, (cz - hgt) / 2), plaster)):
        RS.box(name, size, loc, mat)


def the_lamp(brass):
    L = C.LAMP
    pos, aim = Vector(L["pos"]), Vector(L["aim"])
    d = bpy.data.lights.new("the wall-arm lamp", "AREA")
    d.shape = "DISK"
    d.size = L["shade_d"] * 0.86
    d.energy = L["power_w"]
    d.spread = math.radians(L["spread_deg"])
    d.use_nodes = True
    nt = d.node_tree
    bb = nt.nodes.new("ShaderNodeBlackbody")
    bb.inputs[0].default_value = L["kelvin"]
    wb = nt.nodes.new("ShaderNodeBlackbody")
    wb.inputs[0].default_value = L["white_balance_k"]
    dv = nt.nodes.new("ShaderNodeVectorMath")
    dv.operation = "DIVIDE"
    nt.links.new(bb.outputs[0], dv.inputs[0])
    nt.links.new(wb.outputs[0], dv.inputs[1])
    nt.links.new(dv.outputs[0], nt.nodes["Emission"].inputs["Color"])
    ob = bpy.data.objects.new("the wall-arm lamp", d)
    bpy.context.scene.collection.objects.link(ob)
    q = (aim - pos).to_track_quat("-Z", "Y")
    ob.rotation_mode = "QUATERNION"
    ob.rotation_quaternion = q
    ob.location = pos
    ob.visible_camera = False
    # the spun-metal shade around it: an open cone, dark outside, white enamel inside, its mouth 2 cm past the emitter
    shade_out = RT.m_worn("spun steel shade (dark)", (0.05, 0.05, 0.05), 0.45, (0.03, 0.03, 0.03), scratch=0.2)
    bpy.ops.mesh.primitive_cone_add(vertices=96, radius1=L["shade_d"] / 2, radius2=0.045, depth=0.20, end_fill_type="NOTHING")
    sh = bpy.context.active_object
    sh.name = "lamp shade (spun steel)"
    so = sh.modifiers.new("t", "SOLIDIFY")
    so.thickness = 0.0012
    sh.data.materials.append(shade_out)
    sh.rotation_mode = "QUATERNION"
    sh.rotation_quaternion = (pos - aim).to_track_quat("Z", "Y")
    sh.location = pos - (pos - aim).normalized() * (-0.08)
    # the arm to the wall
    top = pos + (pos - aim).normalized() * 0.2
    wall = Vector((top.x, C.ROOM["wall_y"], top.z + 0.15))
    mid = (top + wall) / 2
    bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=0.008, depth=(wall - top).length, location=mid)
    arm = bpy.context.active_object
    arm.name = "lamp arm (brass)"
    arm.rotation_mode = "QUATERNION"
    arm.rotation_quaternion = (wall - top).to_track_quat("Z", "Y")
    arm.data.materials.append(brass)
    return ob


# ------------------------------------------------------------------------------------------------ build


def m_leather():
    m, nt, b = RS._mat("vegetable-tanned leather (let into the floor)")
    co = RS._n(nt, "ShaderNodeTexCoord")
    nz = RS._n(nt, "ShaderNodeTexNoise", Scale=900.0, Detail=6.0)
    nt.links.new(co.outputs["Object"], nz.inputs["Vector"])
    ramp = RS._n(nt, "ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.16, 0.075, 0.032, 1)
    ramp.color_ramp.elements[1].color = (0.24, 0.12, 0.055, 1)
    nt.links.new(nz.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    bm = RS._n(nt, "ShaderNodeBump", Strength=0.15, Distance=0.0003)
    nt.links.new(nz.outputs["Fac"], bm.inputs["Height"])
    nt.links.new(bm.outputs["Normal"], b.inputs["Normal"])
    b.inputs["Roughness"].default_value = 0.62
    return m


def record_sheet(rec):
    x0, x1, y0, y1 = C.record_rect(rec)
    return {"cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2, "W": x1 - x0, "H": y1 - y0, "psi": 0.0}


def m_record(rec):
    """The film's record, printed on dead-matte stock: no gloss coat and no sheen, so a straight-down camera sees the
    print and not the lit room reflected off its surface (the measured cause of the v5c A7 failure: a 0.3 specular
    and 0.1 sheen lifted the plate's black ground from 3 to about 70 of 255)."""
    m = RT.m_image_crop("record", C.RECORDS[rec]["tex"], rough=1.0, sheen=0.0)
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Specular IOR Level"].default_value = RECORD_SPECULAR
    k = C.record_albedo(rec)
    if k != 1.0:
        # the page printed darker than its scan by a fixed factor (channel_v5c.RECORD_ALBEDO_EV): the paper's albedo
        # calibrated to the scan's white at the declared exposure, in the scene, not in the measurement
        t = next(n for n in nt.nodes if n.type == "TEX_IMAGE")
        sc_ = nt.nodes.new("ShaderNodeVectorMath")
        sc_.operation = "SCALE"
        sc_.inputs["Scale"].default_value = k
        nt.links.new(t.outputs["Color"], sc_.inputs[0])
        nt.links.new(sc_.outputs["Vector"], b.inputs["Base Color"])
        print(f"record {rec}: albedo x{k:.4f} ({math.log2(k):+.2f} stop)")
    return m


RECORD_SPECULAR = float(A["rec_spec"])         # 0: no gloss coat (the calibration may try a trace)


def galley(brass, type_metal):
    x0, x1, y0, y1 = C.ITEMS["galley"]["rect"]
    fl = 0.0015
    RS.box("galley floor (brass)", (x1 - x0, y1 - y0, fl), ((x0 + x1) / 2, (y0 + y1) / 2, fl / 2), brass, 0.0003)
    for nm, size, loc in (("galley rail left", (0.003, y1 - y0, 0.010), (x0 + 0.0015, (y0 + y1) / 2, 0.005)),
                          ("galley rail right", (0.003, y1 - y0, 0.010), (x1 - 0.0015, (y0 + y1) / 2, 0.005)),
                          ("galley head", (x1 - x0, 0.003, 0.010), ((x0 + x1) / 2, y1 - 0.0015, 0.005))):
        RS.box(nm, size, loc, brass, 0.0005)
    for k in range(14):                       # blank sorts set up against the head, feet down
        y = y1 - 0.003 - 0.0016 - k * 0.0034
        RS.box(f"sort {k + 1} (blank)", (x1 - x0 - 0.008, 0.0031, 0.0185), ((x0 + x1) / 2, y, fl + 0.00925), type_metal,
               0.0002)


def build():
    RS.FPS = 30                               # an int for reset(); the exact rate is set just below
    sc = RS.reset(0, 0)
    sc.render.fps, sc.render.fps_base = FPSV
    sc.world.node_tree.nodes["Background"].inputs[0].default_value = (0.0, 0.0, 0.0, 1)
    oak = [RT.m_oak_v4(f"oak board {k + 1}", seed=k * 0.37) for k in range(C.TABLE["boards"])]
    carved_top(oak, m_leather())
    slab_and_trestles(RT.m_oak_v4("oak (slab edges)", seed=4.2, across=True), RT.m_oak_v4("oak (trestles)", seed=5.0))
    room()
    brass = RT.m_worn("brass (worn)", (0.62, 0.44, 0.18), 0.42, (0.24, 0.20, 0.10))
    RT.BRASS_M = brass
    bronze = RT.m_worn("bronze (worn)", (0.50, 0.30, 0.15), 0.32, (0.16, 0.20, 0.13), scratch=0.4)
    type_metal = RT.m_worn("type metal", (0.42, 0.42, 0.43), 0.38, (0.20, 0.20, 0.21), scratch=0.25)
    I = C.ITEMS
    # the tablet at the launch corner
    x0, x1, y0, y1 = I["tablet"]["rect"]
    tab = RS.box("T-01 Umma register", (x1 - x0, y1 - y0, I["tablet"]["h"]),
                 ((x0 + x1) / 2, (y0 + y1) / 2, I["tablet"]["h"] / 2 + 0.0008),
                 RS.m_image("T-01 obverse", "T-01_obverse", 0.85, bump=0.12), bevel=0.006)
    RS.tablet_faces(tab)
    # the latch's bronze disc, lying beside the cup where it fell open
    bpy.ops.mesh.primitive_cylinder_add(vertices=128, radius=0.0225, depth=0.003,
                                        location=(C.BLOCK["x"][0] + 0.010, C.REACH_Y[0] - 0.060, 0.0015))
    disc = bpy.context.active_object
    disc.name = "bronze disc (the latch, open)"
    bpy.ops.object.shade_smooth()
    disc.data.materials.append(bronze)
    # the papyrus along reach 1 on its backing, the two Roman coins on its ends
    pap = RT.m_scan_on_backing("papyrus", "T-02a_keyed", margin("papyrus"))
    flat_sheet("T-02a Turin papyrus", I["papyrus"]["rect"], 0.0, pap, RT.fibre("papyrus", margin("papyrus")),
               thick=0.0004, lift=0.0008, n=(300, 60))
    for nm, spin in (("coin dupondius", 20.0), ("coin sestertius", -35.0)):
        it = I[nm]
        scan_flat(it["scan"], it["dia"], it["at"][0], it["at"][1], 0.0011, spin_deg=spin)
    # the Gutenberg leaf and the galley beside it
    flat_sheet("T-06 Gutenberg leaf", I["leaf"]["rect"], 0.0,
               RT.m_image_crop("leaf", "T-06_leaf", rough=0.72, sheen=0.15, bump=0.15), RT.fibre("leaf", margin("leaf")),
               thick=0.00015, lift=0.0012)
    galley(brass, type_metal)
    # the Catalan Atlas board on its closed folder
    x0, x1, y0, y1 = I["folder"]["rect"]
    RS.box("Atlas folder (closed, the second board inside)", (x1 - x0, y1 - y0, I["folder"]["h"]),
           ((x0 + x1) / 2, (y0 + y1) / 2, I["folder"]["h"] / 2), RT.m_plain("folder cloth (dark)", (0.05, 0.04, 0.035), 0.8,
                                                                         sheen=0.3), bevel=0.0015)
    flat_sheet("T-03 Catalan Atlas board", I["atlas"]["rect"], I["folder"]["h"],
               RT.m_image_crop("atlas1", "T-03_board1", rough=0.7, sheen=0.1, bump=0.1),
               RT.fibre("atlas1", margin("atlas1")), thick=0.0012, turn=True, lift=0.0)
    # the globe on its stand at turn 2
    g = I["globe"]
    upright_scan("globe", g["h"], (g["at"][0], g["at"][1], 0.0), 0.0, yaw_deg=-30.0)
    # Piri Reis, partly rolled, the nested weights on it; Ino's sheet and the Admiralty chart, partly rolled
    piri = I["piri"]
    rolled_sheet("T-04 Piri Reis (partly rolled)", piri, 0.8668,
                 RT.m_image_crop("piri", "T-04_keyed", rough=0.72, alpha=True, sheen=0.15, bump=0.15),
                 RT.fibre("piri", margin("piri")), thick=0.0003)
    w = I["weights"]
    upright_scan("weights", w["dia"], (w["at"][0], w["at"][1], 0.0009), w["upright_rx_deg"], yaw_deg=20.0)
    rolled_sheet("T-08 Ino's sheet (partly rolled)", I["ino"], 1.0,
                 RT.m_image_crop("ino", "T-08_sheet", rough=0.75, sheen=0.2, bump=0.12), RT.fibre("ino", margin("ino")),
                 thick=0.0001)
    rolled_sheet("T-20 Admiralty chart 983 (partly rolled)", I["admiralty"], 1.0,
                 RT.m_image_crop("chart", "T-20_chart", rough=0.75, sheen=0.15, bump=0.1),
                 RT.fibre("chart", margin("chart")), thick=0.00015)
    j = I["jeton"]
    scan_flat(j["scan"], j["dia"], j["at"][0], j["at"][1], 0.0009, spin_deg=10.0)
    # the felt in the well and the film's record on it
    wx, wy = C.WELL["x"], C.WELL["y"]
    RS.box("black felt (the well)", (wx[1] - wx[0] - 0.0004, wy[1] - wy[0] - 0.0004, C.WELL["felt_t"]),
           ((wx[0] + wx[1]) / 2, (wy[0] + wy[1]) / 2, C.felt_top() - C.WELL["felt_t"] / 2), RT.m_felt(), bevel=0.0003)
    RT.sheet(f"record {A['record']}", record_sheet(A["record"]), m_record(A["record"]),
             C.felt_top() + I["record"]["h"] + 0.00005)
    # the stick chart on the wall behind the far edge
    st = C.WALL_ITEMS["stick"]
    me = bpy.data.meshes.new("T-19 stick chart (on the wall)")
    yw = C.ROOM["wall_y"] - 0.012
    me.from_pydata([(st["x"][0], yw, st["z"][0]), (st["x"][1], yw, st["z"][0]), (st["x"][1], yw, st["z"][1]),
                    (st["x"][0], yw, st["z"][1])], [], [(0, 1, 2, 3)])
    uv = me.uv_layers.new()
    for li, c_ in zip(me.polygons[0].loop_indices, ((0, 0), (1, 0), (1, 1), (0, 1))):
        uv.data[li].uv = c_
    ob = bpy.data.objects.new("T-19 stick chart (on the wall)", me)
    bpy.context.scene.collection.objects.link(ob)
    ob.data.materials.append(RT.m_image_crop("T-19 stick chart", "T-19_keyed", rough=0.7, alpha=True, sheen=0.1, bump=0.4))
    so = ob.modifiers.new("t", "SOLIDIFY")
    so.thickness = 0.006
    the_lamp(brass)
    # the marble
    bpy.ops.mesh.primitive_uv_sphere_add(segments=96, ring_count=48, radius=C.R)
    m = bpy.context.active_object
    m.name = "the marble (clay)"
    bpy.ops.object.shade_smooth()
    m.data.materials.append(RT.m_clay_mottled())
    m.rotation_mode = "QUATERNION"
    return sc, m


def animate(sc, marble, frames, expo):
    cam = RS.camera(C.LENS_MM)
    sc.camera = cam
    cam.rotation_mode = "QUATERNION"
    cam.data.dof.use_dof = True
    for f, fr in enumerate(frames):
        marble.location = Vector(fr["p"])
        marble.rotation_quaternion = Quaternion(fr["q"])
        marble.keyframe_insert("location", frame=f)
        marble.keyframe_insert("rotation_quaternion", frame=f)
        eye, tgt, up = Vector(fr["eye"]), Vector(fr["tgt"]), Vector(fr["up"])
        fwd = (tgt - eye).normalized()
        right = fwd.cross(up).normalized()
        upv = right.cross(fwd)
        M = Matrix((right, upv, -fwd)).transposed()
        cam.location = eye
        cam.rotation_quaternion = M.to_quaternion()
        cam.keyframe_insert("location", frame=f)
        cam.keyframe_insert("rotation_quaternion", frame=f)
        cam.data.dof.focus_distance = fr["focus"]
        cam.data.dof.aperture_fstop = fr["fstop"]
        cam.data.dof.keyframe_insert("focus_distance", frame=f)
        cam.data.dof.keyframe_insert("aperture_fstop", frame=f)
        if expo is not None:
            sc.view_settings.exposure = float(expo[min(f, len(expo) - 1)])
            sc.view_settings.keyframe_insert("exposure", frame=f)
    for ob in (marble, cam):
        ad = ob.animation_data
        if ad and ad.action:
            for fc in RS._fcurves(ad.action):
                for kp in fc.keyframe_points:
                    kp.interpolation = "LINEAR"
    for idb in (cam.data, sc):
        ad = idb.animation_data
        if ad and ad.action:
            for fc in RS._fcurves(ad.action):
                for kp in fc.keyframe_points:
                    kp.interpolation = "LINEAR"
    return cam


def settings(sc):
    sc.render.engine = "CYCLES"
    cy = sc.cycles
    cy.device = "GPU"
    rx, ry = (int(v) for v in A["res"].split("x"))
    sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = rx, ry, 100
    cy.samples = int(A["samples"])
    cy.use_adaptive_sampling = True
    cy.adaptive_threshold = float(A["threshold"])
    cy.adaptive_min_samples = min(int(A["min_samples"]), cy.samples)
    # NO denoiser of any kind (founder ruling; tests/test_no_denoise.py and tests/test_final_v5c.py hold this)
    cy.use_denoising = False
    cy.use_preview_denoising = False
    cy.sample_clamp_direct = 0.0
    cy.sample_clamp_indirect = 5.0
    cy.max_bounces, cy.diffuse_bounces, cy.glossy_bounces, cy.transmission_bounces = 10, 4, 4, 8
    cy.caustics_reflective = cy.caustics_refractive = False
    cy.use_animated_seed = True
    cy.texture_limit_render = "8192"
    sc.render.use_persistent_data = True
    sc.render.use_motion_blur = A["blur"] == "1"
    sc.render.motion_blur_shutter = 0.5
    sc.render.use_compositing = False
    if A["exr"]:
        # the same frames also kept scene-linear (half-float EXR, before the view transform and the exposure): the
        # PNG is unchanged (the Composite node is the render layer as rendered)
        sc.use_nodes = True
        tree = sc.node_tree
        rl = next(n for n in tree.nodes if n.type == "R_LAYERS")
        fo = tree.nodes.new("CompositorNodeOutputFile")
        fo.base_path = A["exr"]
        fo.format.file_format = "OPEN_EXR"
        fo.format.color_depth = "16"
        fo.format.exr_codec = "ZIP"
        fo.file_slots[0].path = "#####"
        tree.links.new(rl.outputs["Image"], fo.inputs[0])
        sc.render.use_compositing = True
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "None"
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGB"
    sc.render.image_settings.color_depth = "8"
    sc.render.use_overwrite = False
    sc.render.use_placeholder = True
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


def main():
    import time
    t0 = time.time()
    bpy.context.preferences.filepaths.temporary_directory = "D:/document-media/title-sequence/run/tmp/"
    rep = json.loads((SIM / "run-timing.json").read_text(encoding="utf-8"))
    bake = json.loads((SIM / "run-bake.json").read_text(encoding="utf-8"))
    frames = SH.shot(bake, FPS, rep["rest_sim_s"], A["record"])
    expo = json.loads(Path(A["expo"]).read_text(encoding="utf-8"))["ev"] if A["expo"] else None
    sc, marble = build()
    animate(sc, marble, frames, expo)
    settings(sc)
    if expo is None:
        sc.view_settings.exposure = float(A["exposure"])
    RS.check_provenance()
    f0, f1 = (int(v) for v in A["frames"].split(":"))
    f1 = min(f1, len(frames) - 1)
    sc.frame_start, sc.frame_end, sc.frame_step = f0, f1, int(A["step"])
    if A["blend"]:
        bpy.ops.wm.save_as_mainfile(filepath=A["blend"], compress=False)
    sc.render.filepath = str(Path(A["out"]) / "#####")
    if A["vs"]:
        # the view settings each frame renders through, read back from the scene as evaluated at that frame (A40 like
        # for like binds a title's declared view_transform to these); a frame whose PNG is already on disk is not
        # rendered again (use_overwrite off) and is marked so
        vs = []
        for f in range(f0, f1 + 1, int(A["step"])):
            sc.frame_set(f)
            v = sc.view_settings
            vs.append({"frame": f, "view_transform": v.view_transform, "look": v.look,
                       "exposure": round(float(v.exposure), 6),
                       **({"skipped_existing": True} if (Path(A["out"]) / f"{f:05d}.png").exists() else {})})
        sc.frame_set(f0)
        try:                                  # a retry after a crash keeps the read-back of the frames it rendered
            old = {d["frame"]: d for d in json.loads(Path(A["vs"]).read_text(encoding="utf-8"))["frames"]}
        except (OSError, ValueError, KeyError):
            old = {}
        vs = [old[d["frame"]] if d.get("skipped_existing") and d["frame"] in old
              and not old[d["frame"]].get("skipped_existing") else d for d in vs]
        Path(A["vs"]).write_text(json.dumps({"blender": bpy.app.version_string, "frames": vs}), encoding="utf-8")
    print("V5C-BUILD " + json.dumps({"frames_total": len(frames), "range": [f0, f1, int(A["step"])],
                                     "build_s": round(time.time() - t0, 1), "renderer": RS.renderer_line(sc)}), flush=True)
    bpy.ops.render.render(animation=True)
    assert not sc.cycles.use_denoising and not sc.cycles.use_preview_denoising, "no denoiser (founder ruling)"
    print("V5C-DONE " + json.dumps({"s": round(time.time() - t0, 1), "images": sorted(RS.IMAGES), "denoise": False}),
          flush=True)


if __name__ == "__main__":
    main()
