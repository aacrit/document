"""The Run v5: one lit still of the desk (Cycles, no denoiser), at the design's mid-run moment or from the top-down wide.

    blender -b --factory-startup --python design/title-sequence/blender/run/still_v5.py -- \
        --view mid|top --res 2560x1440 --samples 2048 --threshold 0.004 --exposure 0.0 --out <png> [--blend <blend>]

The scene is desk_v5's layout, nothing else: the oak desk (C-02 scan) with its boards and breadboard ends in a plain
plaster room, the spread being compared as v4.1 tuned it (each sheet the displaced mesh of its relief EXR, real
thickness), the late papers re-laid squared, folded as such papers are stored, the gated scans (globe, nested weights,
two Roman coins and the jeton), the galley of blank sorts with the glass pair at its lip, the khipu cord, the felt pad
and the film's record. One emitter: the wall-arm lamp (desk_v5.LAMP); the room's plaster, ceiling and floor give the
fill by bouncing it. The world is black. Exposure is the camera's (metered outside Blender from a low-sample pass of the
same view, meter_v5.py); the white balance is the lamp's colour against desk_v5.LAMP["white_balance_k"].

The moment (--t, v4.1 roll-out seconds; default 14.4 s): the lead is placed where the v4.1 roll-out has it, just past
the weights' glance and heading along the back of the desk toward the coin row. The galley strike and the coin row are
not baked yet, so the sorts, the glass pair and the coins stand where they start. Moving bodies are placed
statically at that moment (a still), so no motion blur.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bench as B  # noqa: E402
import desk_v5 as D  # noqa: E402
import run_scene as RS  # noqa: E402
import run_take as RT  # noqa: E402

RELIEF = Path("D:/document-media/title-sequence/run/relief")
SIM = Path("D:/document-media/title-sequence/run/sim/v4")


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    a = {"view": "mid", "res": "2560x1440", "samples": "2048", "threshold": "0.004", "exposure": "0.0", "out": "",
         "blend": "", "min_samples": "128", "t": "14.4"}
    for i, k in enumerate(argv):
        if k.startswith("--") and i + 1 < len(argv):
            a[k[2:]] = argv[i + 1]
    return a


A = _args()
T_MOMENT = float(A["t"])

# ------------------------------------------------------------------------------------------------ heights

_W = np.load(RELIEF / "world.npz")
_TOP, _X0, _Y0, _TX = _W["top"], float(_W["x0"]), float(_W["y0"]), float(_W["texel"])


def z_at(x, y):
    """The composed top of the tuned spread (relief.py's world grid) at a desk point."""
    j = int(round((y - _Y0) / _TX))
    i = int(round((x - _X0) / _TX))
    j = min(max(j, 0), _TOP.shape[0] - 1)
    i = min(max(i, 0), _TOP.shape[1] - 1)
    return float(_TOP[j, i])


# ------------------------------------------------------------------------------------------------ materials


def m_plaster(name, albedo):
    m, nt, b = RS._mat(name)
    b.inputs["Base Color"].default_value = (albedo, albedo * 0.93, albedo * 0.84, 1.0)
    b.inputs["Roughness"].default_value = 0.95
    b.inputs["Specular IOR Level"].default_value = 0.2
    return m


def m_glass():
    m, nt, b = RS._mat("clear glass (the pair)")
    b.inputs["Base Color"].default_value = (0.92, 0.95, 0.93, 1.0)
    b.inputs["Roughness"].default_value = 0.02
    b.inputs["Transmission Weight"].default_value = 1.0
    b.inputs["IOR"].default_value = 1.52
    return m


# ------------------------------------------------------------------------------------------------ the room and the lamp


def room():
    W, H = D.DESK["size"]
    hgt = D.DESK["height"]
    plaster = m_plaster("plaster (room)", D.ROOM["plaster_albedo"])
    floor = RT.m_plain("floor boards (dark, matte)", (D.ROOM["floor_albedo"],) * 3, 0.8)
    cz = D.ROOM["ceiling_z"]
    x0, x1 = D.ROOM["side_x"]
    wy = D.ROOM["wall_y"]
    parts = [
        ("floor", (x1 - x0, 8.0, 0.02), ((x0 + x1) / 2, wy - 4.0, -hgt - 0.01), floor),
        ("ceiling", (x1 - x0, 8.0, 0.02), ((x0 + x1) / 2, wy - 4.0, cz + 0.01), plaster),
        ("back wall", (x1 - x0, 0.02, cz + hgt), ((x0 + x1) / 2, wy + 0.01, (cz - hgt) / 2), plaster),
        ("left wall", (0.02, 8.0, cz + hgt), (x0 - 0.01, wy - 4.0, (cz - hgt) / 2), plaster),
        ("right wall", (0.02, 8.0, cz + hgt), (x1 + 0.01, wy - 4.0, (cz - hgt) / 2), plaster),
        ("wall behind the camera", (x1 - x0, 0.02, cz + hgt), ((x0 + x1) / 2, wy - 8.0, (cz - hgt) / 2), plaster),
    ]
    for name, size, loc, mat in parts:
        RS.box(name, size, loc, mat)


def the_lamp():
    L = D.LAMP
    d = bpy.data.lights.new("the wall-arm lamp", "AREA")
    d.shape = "DISK"
    d.size = L["shade_d"]
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
    ob.location = L["pos"]
    ob.rotation_mode = "QUATERNION"
    ob.rotation_quaternion = (Vector(L["aim"]) - Vector(L["pos"])).to_track_quat("-Z", "Y")
    ob.visible_camera = False                      # its body is not modelled (no scan); it stays out of frame
    return ob


# ------------------------------------------------------------------------------------------------ paper off the spread


def _on_top(name, x, y):
    """What lies beneath a re-laid paper at (x, y): the oak, or the tops of the papers it was dealt onto."""
    z = 0.0
    for other in ("ino", "tape", "strip", "card", "page"):
        if other == name:
            break
        it = D.ITEMS[other]
        u, v = _local(it, x, y)
        if abs(u) <= it["size"][0] / 2 and abs(v) <= it["size"][1] / 2:
            z = max(z, _support(other) + it["h"] + 0.00015)
    return z


_SUP: dict = {}


def _support(name):
    if name not in _SUP:
        it = D.ITEMS[name]
        _SUP[name] = _on_top(name, *it["centre"]) if name != "ino" else 0.0
    return _SUP[name]


def _local(it, x, y):
    p = math.radians(it["psi"])
    dx, dy = x - it["centre"][0], y - it["centre"][1]
    return dx * math.cos(p) + dy * math.sin(p), -dx * math.sin(p) + dy * math.cos(p)


def paper(name, tex, top_mat, side_mat, relief, texel=0.002, crop=None):
    """A re-laid sheet: a grid at 2 mm with its own relief (folds tented, cockle, a lifted corner) set on what lies
    beneath it, with real thickness (solidify) and the scan's own margin colour on its edges."""
    it = D.ITEMS[name]
    W, H = it["size"]
    nu, nv = max(2, int(round(W / texel)) + 1), max(2, int(round(H / texel)) + 1)
    u = np.linspace(-W / 2, W / 2, nu)
    v = np.linspace(-H / 2, H / 2, nv)
    U, V = np.meshgrid(u, v)
    p = math.radians(it["psi"])
    X = it["centre"][0] + U * math.cos(p) - V * math.sin(p)
    Y = it["centre"][1] + U * math.sin(p) + V * math.cos(p)
    Z = relief(U, V, W, H) + it["h"]
    Zb = np.vectorize(lambda x, y: _on_top(name, x, y))(X, Y)
    # paper bridges what is beneath it: the support smoothed over 6 mm
    from_scipy = None
    try:
        from scipy.ndimage import uniform_filter as from_scipy
    except Exception:
        pass
    if from_scipy is not None:
        Zb = from_scipy(Zb, size=3, mode="nearest")
    Z = Z + Zb
    verts = np.stack([X.ravel(), Y.ravel(), Z.ravel()], 1)
    idx = np.arange(nu * nv).reshape(nv, nu)
    faces = np.stack([idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel(), idx[1:, 1:].ravel(), idx[1:, :-1].ravel()], 1)
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(verts))
    me.vertices.foreach_set("co", verts.astype(np.float32).ravel())
    me.loops.add(faces.size)
    me.loops.foreach_set("vertex_index", faces.astype(np.int32).ravel())
    me.polygons.add(len(faces))
    me.polygons.foreach_set("loop_start", (np.arange(len(faces)) * 4).astype(np.int32))
    me.update(calc_edges=True)
    uvv = np.stack([(U.ravel() + W / 2) / W, (V.ravel() + H / 2) / H], 1)
    uv = me.uv_layers.new()
    uv.data.foreach_set("uv", uvv[faces.ravel()].astype(np.float32).ravel())
    me.polygons.foreach_set("use_smooth", np.ones(len(faces), bool))
    ob = bpy.data.objects.new(f"{name} ({tex})", me)
    bpy.context.scene.collection.objects.link(ob)
    me.materials.append(top_mat)
    me.materials.append(side_mat)
    so = ob.modifiers.new("thickness", "SOLIDIFY")
    so.thickness, so.offset, so.material_offset_rim = max(it["h"], 0.00008), -1, 1
    so.material_offset = 0
    return ob


def folded(nu_, nv_, ridge=0.0012, cockle=0.0005, lam=0.12, lift=(0.0, 0.0)):
    """A sheet stored folded nu x nv: each fold tents up a ridge (a mountain fold, the paper's memory), a low cockle,
    and an optional lifted corner (+u, -v) of lift[0] over lift[1]."""
    def f(U, V, W, H):
        z = np.zeros_like(U)
        for k in range(1, nu_):
            d = np.abs(U - (-W / 2 + k * W / nu_))
            z += ridge * np.clip(1 - d / 0.035, 0, 1) ** 1.5
        for k in range(1, nv_):
            d = np.abs(V - (-H / 2 + k * H / nv_))
            z += 0.6 * ridge * np.clip(1 - d / 0.03, 0, 1) ** 1.5
        z += cockle * 0.5 * (1 + np.sin(2 * math.pi * (U * 0.8 + V * 0.6) / lam) * np.cos(2 * math.pi * V / (lam * 1.3)))
        if lift[0]:
            r = np.hypot(np.clip(U - (W / 2 - lift[1]), 0, None), np.clip(-(V + H / 2 - lift[1]), 0, None))
            z += lift[0] * (r / lift[1]) ** 2
        # every free edge 0.6 mm proud over its last 15 mm
        e = np.minimum.reduce([U + W / 2, W / 2 - U, V + H / 2, H / 2 - V])
        z += 0.0006 * np.clip(1 - e / 0.015, 0, 1) ** 2
        return z
    return f


def flat(bow=0.0):
    def f(U, V, W, H):
        return bow * (1 - (2 * U / W) ** 2) if bow else np.zeros_like(U)
    return f


def panel_crop(fold, panel):
    nu_, nv_ = fold
    iu, iv = panel
    return (iu / nu_, (iu + 1) / nu_), (1 - (iv + 1) / nv_, 1 - iv / nv_)


# ------------------------------------------------------------------------------------------------ objects


def _bake_world(ob):
    """The scan's vertices in world space, its transform baked into the mesh (the glTF importer leaves the object in
    quaternion mode, so rotation_euler alone would be ignored)."""
    bpy.context.view_layer.update()                  # matrix_world is stale until the depsgraph updates
    me = ob.data
    me.transform(ob.matrix_world)
    ob.matrix_world = Matrix.Identity(4)
    return np.array([v.co[:] for v in me.vertices])


def scan_standing_coin(sid, dia, x, y, z, spin_deg, turned):
    """A gated coin scan standing on its edge in the groove, its faces across the row (normal along +x): the thin
    axis found by the scan's own principal axes, then turned about it (spin) and over (turned: the other face to +x)."""
    ob = RT.import_scan(sid, dia, (0.0, 0.0, 0.0))
    co = _bake_world(ob)
    c = co.mean(0)
    w_, V = np.linalg.eigh(np.cov((co - c).T))
    e1 = V[:, 0] / np.linalg.norm(V[:, 0])
    e2 = V[:, 1] - e1 * float(V[:, 1] @ e1)
    e2 /= np.linalg.norm(e2)
    e3 = np.cross(e1, e2)
    R0 = Matrix((tuple(e1), tuple(e2), tuple(e3)))          # world to (thin, in-face, in-face)
    M = Matrix.Rotation(math.radians(spin_deg), 3, "X") @ (Matrix.Rotation(math.pi, 3, "Z") if turned else
                                                           Matrix.Identity(3)) @ R0
    ob.data.transform(M.to_4x4() @ Matrix.Translation(Vector(-c)))
    co = np.array([v.co[:] for v in ob.data.vertices])
    ob.location = (x, y, z - co[:, 2].min())
    ob.name = f"{sid} (real scan, standing)"
    return ob


def upright_scan(sid, size, loc, rx_deg, yaw_deg=0.0):
    """A gated scan turned upright about x (the nested weights were captured lying on their side, lid to -y), turned
    yaw about the vertical, and set down with its lowest point on loc, its bounds centred on loc."""
    ob = RT.import_scan(sid, size, (0.0, 0.0, 0.0))
    co = _bake_world(ob)
    mid = (co.max(0) + co.min(0)) / 2
    ob.data.transform(Matrix.Translation(Vector((-mid[0], -mid[1], -mid[2]))))
    ob.data.transform(Matrix.Rotation(math.radians(yaw_deg), 4, "Z") @ Matrix.Rotation(math.radians(rx_deg), 4, "X"))
    co = np.array([v.co[:] for v in ob.data.vertices])
    ob.location = (loc[0], loc[1], loc[2] - co[:, 2].min())
    return ob


def tray(brass_free_oak):
    """The oak coin tray: a near rail, a divider and a far rail along x with a floor under the far compartment only;
    the groove between the near rail and the divider is open at both ends and its floor is the desk."""
    it = D.ITEMS["tray"]
    gx0, gx1 = it["groove"]["x"]
    L, cx = gx1 - gx0, (gx0 + gx1) / 2
    gw, h = it["groove"]["w"], it["h"]
    ly = D.LINE_Y
    rail_t = 0.008
    y_near = ly - gw / 2 - rail_t / 2
    y_div = ly + gw / 2 + rail_t / 2
    y_far = it["centre"][1] + it["size"][1] / 2 - rail_t / 2
    for nm, y in (("near rail", y_near), ("divider", y_div), ("far rail", y_far)):
        RS.box(f"coin tray {nm}", (L, rail_t, h), (cx, y, h / 2), brass_free_oak, bevel=0.0012)
    comp_y0, comp_y1 = y_div + rail_t / 2, y_far - rail_t / 2
    RS.box("coin tray floor", (L, comp_y1 - comp_y0, 0.004), (cx, (comp_y0 + comp_y1) / 2, 0.002), brass_free_oak)
    for x in (gx0 + rail_t / 2, gx1 - rail_t / 2):
        RS.box("coin tray end", (rail_t, comp_y1 - comp_y0 + 2 * rail_t, h), (x, (comp_y0 + comp_y1) / 2, h / 2),
               brass_free_oak, bevel=0.0012)


def galley(brass, type_metal, glass):
    """The approved galley (sim_galley's local frame: the row of blank sorts along +x from quad 1 at the origin, the end
    stop, the pair on the step at the lip), set on the leaf at desk_v5's place."""
    lay = json.loads((SIM / "run-layout.json").read_text(encoding="utf-8"))["stations"]["galley"]
    loc = dict(lay["local"])
    loc.update({k: v for k, v in lay.items() if k != "local"})
    it = D.ITEMS["galley"]
    a = math.radians(it["psi"])
    ox = it["mouth"][0] + (loc["ramp_l"]) * math.cos(a)
    oy = it["mouth"][1] + (loc["ramp_l"]) * math.sin(a)
    z0 = z_at(ox, oy) + 0.0002
    M = Matrix.Translation((ox, oy, z0)) @ Matrix.Rotation(a, 4, "Z")

    def put(ob, lx, ly, lz):
        ob.matrix_world = M @ Matrix.Translation((lx, ly, lz))
        return ob

    gx, gy = loc["galley"]["x"], loc["galley"]["y"]
    fl = loc["floor_t"]
    put(RS.box("galley floor (brass)", (gx[1] - gx[0], gy[1] - gy[0], fl), (0, 0, 0), brass, 0.0003),
        (gx[0] + gx[1]) / 2, (gy[0] + gy[1]) / 2, fl / 2)
    for side in (gy[0], gy[1]):
        put(RS.box("galley rail (brass)", (gx[1] - gx[0], 0.003, 0.008), (0, 0, 0), brass, 0.0006),
            (gx[0] + gx[1]) / 2, side, 0.004)
    put(RS.box("galley head (brass)", (0.003, gy[1] - gy[0], 0.008), (0, 0, 0), brass, 0.0006), gx[1], (gy[0] + gy[1]) / 2, 0.004)
    qh = loc["quad_half"]
    for k, qx in enumerate(loc["quad_x"]):
        put(RS.box(f"sort {k + 1} (blank)", (2 * qh[0], 2 * qh[1], 2 * qh[2]), (0, 0, 0), type_metal, 0.0002),
            qx, 0.0, fl + qh[2])
    sh = loc["stop_half"]
    put(RS.box("end stop (brass)", (2 * sh[0], 2 * sh[1], 2 * sh[2]), (0, 0, 0), brass, 0.0002), loc["stop_x"],
        loc["stop_y"], fl + sh[2])
    sb = loc["step_b"]
    put(RS.box("step (brass)", (sb["x"][1] - sb["x"][0], sb["y"][1] - sb["y"][0], loc["step_h"]), (0, 0, 0), brass, 0.0003),
        (sb["x"][0] + sb["x"][1]) / 2, (sb["y"][0] + sb["y"][1]) / 2, fl + loc["step_h"] / 2)
    for k, (px_, py_) in enumerate(loc["pair"]):
        bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32, radius=B.R)
        g = bpy.context.active_object
        g.name = f"glass marble {k + 1}"
        bpy.ops.object.shade_smooth()
        g.data.materials.append(glass)
        put(g, px_, py_, fl + loc["step_h"] + B.R)


def khipu(cotton):
    lay = json.loads((SIM / "run-layout.json").read_text(encoding="utf-8"))["stations"]["khipu"]
    cord = lay["cord"]
    pts = [Vector((x, y, z_at(x, y) + B.KHIPU["cord_r"])) for x, y in cord]
    cu = bpy.data.curves.new("khipu cord", "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = B.KHIPU["cord_r"]
    cu.bevel_resolution = 4
    sp = cu.splines.new("POLY")
    sp.points.add(len(pts) - 1)
    for p_, v in zip(sp.points, pts):
        p_.co = (v.x, v.y, v.z, 1.0)
    ob = bpy.data.objects.new("khipu cord (cotton)", cu)
    bpy.context.scene.collection.objects.link(ob)
    ob.data.materials.append(cotton)
    for k, (x, y, _z) in enumerate(lay["knots"]):
        bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=B.KHIPU["knot_r"],
                                             location=(x, y, z_at(x, y) + B.KHIPU["knot_r"] * 0.8))
        kn = bpy.context.active_object
        kn.scale = (1.0, 1.0, 0.75)
        kn.name = f"knot {k + 1}"
        bpy.ops.object.shade_smooth()
        kn.data.materials.append(cotton)


def lead_at(t):
    rows = json.loads((SIM / "run-bake.json").read_text(encoding="utf-8"))["poses"]["lead"]
    r = min(rows, key=lambda r_: abs(r_[0] - t))
    return Vector(r[1:4]), r[4:8], rows


# ------------------------------------------------------------------------------------------------ build


def build():
    RS.FPS = 24                                  # run_take sets it to a float rate for its own keying
    sc = RS.reset(0, 0)
    sc.world.node_tree.nodes["Background"].inputs[0].default_value = (0.0, 0.0, 0.0, 1)
    RT.table_model()
    # the floor plane table_model adds is replaced by the room's floor
    fl = bpy.data.objects.get("floor")
    if fl is not None:
        bpy.data.objects.remove(fl, do_unlink=True)
    room()

    brass = RT.m_worn("brass (worn)", (0.62, 0.44, 0.18), 0.42, (0.24, 0.20, 0.10))
    RT.BRASS_M = brass
    bronze = RT.m_worn("bronze (worn)", (0.50, 0.30, 0.15), 0.32, (0.16, 0.20, 0.13), scratch=0.4)
    type_metal = RT.m_worn("type metal", (0.42, 0.42, 0.43), 0.38, (0.20, 0.20, 0.21), scratch=0.25)
    clay = RT.m_clay_mottled()
    glass = m_glass()
    cotton = RT.m_plain("khipu cotton", (0.36, 0.27, 0.17), 0.9, sheen=0.4)
    oak_tray = RT.m_oak_v4("coin tray oak (modelled, plain)", seed=3.3)

    # the tablet, squared at the near-left corner; its far-right corner on the Atlas board's overhang
    t = D.ITEMS["tablet"]
    tab = RS.box("T-01 Umma register", (t["size"][0], t["size"][1], t["h"]),
                 (t["centre"][0], t["centre"][1], t["h"] / 2 + 0.0011), RS.m_image("T-01 obverse", "T-01_obverse", 0.85,
                                                                                    bump=0.12), bevel=0.006)
    RS.tablet_faces(tab)
    tab.rotation_euler = (math.radians(-0.2), math.radians(0.2), 0.0)

    # the spread being compared: the tuned sheets from their relief EXRs (bench.SHEETS poses)
    for nm in ("papyrus", "atlas1", "atlas2", "piri", "leaf"):
        s = B.SHEETS[nm]
        rgb = tuple(json.loads((RELIEF / f"{nm}.json").read_text(encoding="utf-8"))["margin_rgb_linear"])
        side = RT.fibre(nm, rgb)
        if s.get("backing"):
            top = RT.m_scan_on_backing(nm, s["tex"], rgb)
        else:
            top = RT.m_image_crop(nm, s["tex"], rough=0.72, alpha=bool(s.get("alpha")), sheen=0.15, bump=0.15)
        RT.sheet_mesh(nm, top, side)

    # the late papers, re-laid squared, dealt by date
    def side_of(nm):
        return RT.fibre(nm, tuple(json.loads((RELIEF / f"{nm}.json").read_text(encoding="utf-8"))["margin_rgb_linear"]))

    u, v = panel_crop(D.ITEMS["ino"]["fold"], D.ITEMS["ino"]["panel"])
    paper("ino", "T-08_sheet", RT.m_image_crop("ino", "T-08_sheet", u=u, v=v, rough=0.75, sheen=0.2, bump=0.12),
          side_of("ino"), folded(2, 2, ridge=0.0010, cockle=0.0006))
    paper("tape", "T-09_tape", RT.m_image_crop("T-09 tape", "T-09_tape", rough=0.75), side_of("ino"), flat(0.0004))
    film_base = RT.m_plain("film base (35 mm, blank)", (0.10, 0.08, 0.06), 0.35)
    paper("strip", "35 mm", film_base, film_base, flat(0.0015))
    card = RT.m_plain("manila card (blank)", (0.66, 0.58, 0.42), 0.75, sheen=0.15)
    paper("card", "card", card, card, folded(1, 1, ridge=0.0, cockle=0.0002, lift=(0.003, 0.05)))
    paper("page", "T-18_page", RT.m_image_crop("page", "T-18_page", rough=0.75, sheen=0.15, bump=0.1), side_of("page"),
          folded(1, 1, ridge=0.0, cockle=0.0012, lam=0.15, lift=(0.004, 0.07)))
    u, v = panel_crop(D.ITEMS["chart"]["fold"], D.ITEMS["chart"]["panel"])
    paper("chart", "T-20_chart", RT.m_image_crop("chart", "T-20_chart", u=u, v=v, rough=0.75, sheen=0.15, bump=0.1),
          side_of("chart"), folded(3, 2, ridge=0.0014, cockle=0.0008))

    # the felt pad and the film's record on it
    f = D.ITEMS["felt"]
    RS.box("black felt pad", (f["size"][0], f["size"][1], f["h"]), (f["centre"][0], f["centre"][1], f["h"] / 2),
           RT.m_felt(), bevel=0.0004)
    r = D.ITEMS["record"]
    rec = {"cx": r["centre"][0], "cy": r["centre"][1], "W": r["size"][0], "H": r["size"][1], "psi": 0.0}
    RT.sheet("record C20-METAR-0851", rec, RT.m_image_crop("record", "R-C20-METAR-0851", rough=0.8, sheen=0.1),
             f["h"] + r["h"] + 0.00005)

    # the coin corner: the tray, the row standing in its groove, the weights on Piri's corner
    tray(oak_tray)
    for k, (sid, dia) in enumerate(D.COIN_ROW):
        scan_standing_coin(sid, dia, D.COIN_X0 + k * D.COIN_PITCH, D.LINE_Y, 0.0, spin_deg=37.0 * k, turned=k >= 3)
    w = D.ITEMS["weights"]
    zw = max(z_at(w["centre"][0] + dx, w["centre"][1] + dy) for dx in (-0.03, 0, 0.03) for dy in (-0.03, 0, 0.03))
    upright_scan("weights", w["size"][0], (w["centre"][0], w["centre"][1], zw), w["upright_rx_deg"], yaw_deg=20.0)

    # the globe on its stand (the scan is one piece: its spin belongs to the animatic, about the ball's own axis)
    g = D.ITEMS["globe"]
    upright_scan("globe", g["h"], (g["centre"][0], g["centre"][1], 0.0), 0.0, yaw_deg=-30.0)

    # the latch's disc at rest where it slapped down, the galley, the khipu
    bpy.ops.mesh.primitive_cylinder_add(vertices=128, radius=B.DISC["A"], depth=B.DISC["T"])
    disc = bpy.context.active_object
    disc.name = "bronze disc (latch)"
    bv = disc.modifiers.new("edge", "BEVEL")
    bv.width, bv.segments, bv.limit_method = 0.0004, 3, "ANGLE"
    bpy.ops.object.shade_smooth()
    disc.data.materials.append(bronze)
    disc.location = (B.LATCH["disc"][0] + 0.005, B.LATCH["disc"][1] + 0.006, B.DISC["T"] / 2)
    galley(brass, type_metal, glass)
    khipu(cotton)

    # the lead at the moment
    p, q, _rows = lead_at(T_MOMENT)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=96, ring_count=48, radius=B.R)
    lead = bpy.context.active_object
    lead.name = "the lead (clay)"
    bpy.ops.object.shade_smooth()
    lead.data.materials.append(clay)
    lead.location = (p.x, p.y, z_at(p.x, p.y) + B.R)
    lead.rotation_mode = "QUATERNION"
    lead.rotation_quaternion = q

    the_lamp()
    return sc, lead


def camera_for(view, lead):
    cam = RS.camera(D.LENS_MM)
    if view == "top":
        W, H = D.DESK["size"]
        cam.location = (W / 2, H / 2 + 0.02, D.END["wide_height"])
        cam.rotation_euler = (0.0, 0.0, 0.0)
        cam.data.dof.use_dof = True
        cam.data.dof.focus_distance = D.END["wide_height"]
        cam.data.dof.aperture_fstop = 8.0
        return cam
    # the follow pose: the eye at (D, elevation, azimuth from the lead's heading), aimed 4 cm ahead of the lead
    rows = json.loads((SIM / "run-bake.json").read_text(encoding="utf-8"))["poses"]["lead"]
    r0 = min(rows, key=lambda r_: abs(r_[0] - (T_MOMENT - 0.25)))
    r1 = min(rows, key=lambda r_: abs(r_[0] - (T_MOMENT + 0.25)))
    hd = math.atan2(r1[2] - r0[2], r1[1] - r0[1])
    F = D.FOLLOW
    tgt = Vector((lead.location.x + F["lead_ahead"] * math.cos(hd), lead.location.y + F["lead_ahead"] * math.sin(hd),
                  lead.location.z - B.R * 0.5))
    # the eye trails the lead on the sitter's side of its heading (the side the key's shadows fall toward)
    az = max((hd + math.radians(F["az_from_heading"]), hd - math.radians(F["az_from_heading"])),
             key=lambda a_: -math.sin(a_))
    el = math.radians(F["elev"])
    eye = tgt + Vector((F["D"] * math.cos(el) * math.cos(az), F["D"] * math.cos(el) * math.sin(az), F["D"] * math.sin(el)))
    cam.location = eye
    cam.rotation_mode = "QUATERNION"
    cam.rotation_quaternion = (tgt - eye).to_track_quat("-Z", "Y")
    cam.data.dof.use_dof = True
    cam.data.dof.focus_distance = (lead.location - eye).length
    cam.data.dof.aperture_fstop = F["fstop"]
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
    # NO denoiser of any kind (founder ruling; tests/test_no_denoise.py): adaptive sampling and samples instead
    cy.use_denoising = False
    cy.use_preview_denoising = False
    cy.sample_clamp_direct = 0.0
    cy.sample_clamp_indirect = 5.0
    cy.max_bounces, cy.diffuse_bounces, cy.glossy_bounces, cy.transmission_bounces = 12, 4, 6, 10
    cy.caustics_reflective = cy.caustics_refractive = False
    cy.texture_limit_render = "8192"
    sc.render.use_motion_blur = False
    sc.render.use_compositing = False
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "None"
    sc.view_settings.exposure = float(A["exposure"])
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGB"
    sc.render.image_settings.color_depth = "16"
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
    Path("D:/document-media/title-sequence/run/tmp").mkdir(parents=True, exist_ok=True)
    bpy.context.preferences.filepaths.temporary_directory = "D:/document-media/title-sequence/run/tmp/"
    sc, lead = build()
    cam = camera_for(A["view"], lead)
    sc.camera = cam
    settings(sc)
    RS.check_provenance()
    if A["blend"]:
        bpy.ops.wm.save_as_mainfile(filepath=A["blend"], compress=False)
    sc.render.filepath = A["out"]
    bpy.ops.render.render(write_still=True)
    assert not sc.cycles.use_denoising and not sc.cycles.use_preview_denoising, "no denoiser (founder ruling)"
    print("V5-STILL " + json.dumps({"view": A["view"], "out": A["out"], "res": A["res"], "samples": sc.cycles.samples,
                                    "threshold": sc.cycles.adaptive_threshold, "exposure": sc.view_settings.exposure,
                                    "camera": {"loc": list(cam.location), "fstop": cam.data.dof.aperture_fstop,
                                               "focus": cam.data.dof.focus_distance},
                                    "lead": list(lead.location), "images": sorted(RS.IMAGES), "denoise": False,
                                    "renderer": RS.renderer_line(sc), "s": round(time.time() - t0, 1)}))


if __name__ == "__main__":
    main()
