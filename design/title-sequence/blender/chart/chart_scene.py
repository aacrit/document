"""Title B "Chart": build the proof scenes in Blender from code. Nobody hand-edits the .blend.

    blender -b --factory-startup --python design/title-sequence/blender/chart/chart_scene.py -- \
        --proof p2 --out D:/document-media/title-sequence/chart/blend/chart-p2.blend
    blender -b --factory-startup --python .../chart_scene.py -- --proof p1 --record S-16928 --out <blend>

P2 v2 (beats 3-4, title frames 300-371): C-01 (Moll 1719) unrolls toward camera, rolled about its long side so its
north margin is the far edge. 50 mm on a 36 mm sensor, about 0.55 m from the roll's end, low and to its right; the
camera rises on the house `rostrum` curve across beats 3-4 and, from f324, racks focus over 48 frames (f/2.8 to f/4)
from the roll to the coastline ink of the Bay of Nankin on the laid sheet.
P1 v2 (beats 8-9, title frames 888-959): the film's record slides onto the laid chart from the near edge and stops
(contact shadow, a 0.4 mm sheet edge). Over the last 12 frames of the slide the light closes onto the record: the
lamp travels over it, its pool narrows to the record's footprint (area-lamp spread 180 to 1 degree), the grey fill
falls to zero, so the chart goes to black; the record blends from lit diffuse to pure emission of the scan at 1.0.
The camera arrives exactly top-down with the record filling the frame height, centred: the A40 lint's HOLD fit.

Shared setup (design 2.1): real scale in metres (motion is analytic, nothing simulated, so no x10 scale or 0.1
parent; DOF is true as built), the Poly Haven oak planks running out of frame, an 18% grey fill seen by lighting
only (camera rays see black, so there is never a backdrop), one 4300 K area lamp white-balanced at 5200 K, and the
Standard view transform so emission 1.0 writes the scan's own pixel values. Every animated value is baked one
linear key per frame (the sheet as one shape key per frame, so Cycles blurs its deformation). Images come only
from the Chart texture manifest. The sheet's relief follows C-01's own fold lines, measured on the scan.
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
from mathutils import Euler, Vector

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(HERE))
import kinematics as K  # noqa: E402

TITLE = json.loads((HERE.parent / "title.json").read_text(encoding="utf-8"))
LEDGER = json.loads((HERE.parents[1] / "chart-assets-ledger.json").read_text(encoding="utf-8"))
MEDIA = Path(LEDGER["media_root"])
MAN = json.loads((MEDIA / "tex-manifest.json").read_text(encoding="utf-8"))
FPS = K.FPS


def _args() -> dict:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    a = {"proof": "p2", "record": "S-16928", "profile": "proof", "out": "", "calib": "", "lamp": "", "lamp_end": ""}
    for i, k in enumerate(argv):
        if k.startswith("--") and i + 1 < len(argv):
            a[k[2:]] = argv[i + 1]
    return a


ARGS = _args()
PROFILE = TITLE["render"][ARGS["profile"]]
P2_FRAMES = (300, 371)                                  # 72 frames from the middle of beats 3-4 (f144-479)
P1_FRAMES = (K.SLIDE_F0, K.SLIDE_F0 + 71)              # 888..959
BEATS34 = (144, 479)                                    # the camera's rise spans beats 3-4
RACK = (324, 371)                                       # beat 4's 48-frame focus rack
LAMP_W = 11.0                                           # P1 key (W): lit paper just under the scan's level
LAMP_P2_W = 3.0                                         # P2 key (W), with the dimmer fill
LAMP_END_W = 0.33                                       # P1 at the hold: the pool's power once it is collimated
WHITE_BALANCE_K = 5200.0
GREY = 0.18                                             # the studio fill's colour (18% grey), lighting only
P2_FILL = 0.30                                          # its strength in P2, so the table falls off beyond the pool
INK = (0.869, 0.46)                                     # C-01 (u, v from the top): the Bay of Nankin coastline

# C-01's fold lines, measured on the scan's paper tone with the ink removed (max filter, high-pass), as fractions
# of the cropped sheet: u from the west margin, v from the north margin. Heights in metres at the crease; the
# sheet relaxes linearly between creases (mountain up, valley down to the table), as a folded sheet lies.
FOLDS_U = [(0.2709, 0.0), (0.4975, 0.0024), (0.7175, 0.0)]
FOLDS_V = [(0.2758, 0.0016), (0.8163, 0.0)]
EDGE_LIFT = 0.0006


def _load_motion() -> dict:
    """The closed-form house curves from studio/engine/motion.py (it imports PIL, which Blender lacks)."""
    tree = ast.parse((REPO / "studio/engine/motion.py").read_text(encoding="utf-8"))
    body = ast.parse("import math\n").body
    body += [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {"clamp01", "smoothstep", "rostrum"}]
    ns: dict = {}
    exec(compile(ast.Module(body=body, type_ignores=[]), "studio/engine/motion.py (closed forms)", "exec"), ns)
    return ns


MO = _load_motion()
rostrum, smoothstep = MO["rostrum"], MO["smoothstep"]


# ------------------------------------------------------------------------------------------------ baking


def _fcurves(action):
    if hasattr(action, "fcurves") and len(action.fcurves):
        return list(action.fcurves)
    out = []
    for layer in getattr(action, "layers", []):
        for strip in layer.strips:
            for cb in strip.channelbags:
                out += list(cb.fcurves)
    return out


def _linear(owner):
    ad = getattr(owner, "animation_data", None) or getattr(getattr(owner, "id_data", None), "animation_data", None)
    if ad and ad.action:
        for fc in _fcurves(ad.action):
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"


def bake(owner, path: str, frames, values):
    for f, v in zip(frames, values):
        setattr(owner, path, v)
        owner.keyframe_insert(path, frame=f)
    _linear(owner)


def bake_ob(ob, frames, locs, quats):
    ob.rotation_mode = "QUATERNION"
    for i in range(1, len(quats)):                                       # no flips between frames
        if sum(a * b for a, b in zip(quats[i], quats[i - 1])) < 0:
            quats[i] = [-x for x in quats[i]]
    for f, l, q in zip(frames, locs, quats):
        ob.location = l
        ob.rotation_quaternion = q
        ob.keyframe_insert("location", frame=f)
        ob.keyframe_insert("rotation_quaternion", frame=f)
    _linear(ob)


# ------------------------------------------------------------------------------------------------ scene, world, lamp


def reset_scene(f0: int, f1: int, fill: float):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.name = "chart"
    sc.render.fps = FPS
    sc.frame_start, sc.frame_end = f0, f1
    sc.unit_settings.system = "METRIC"
    w = bpy.data.worlds.new("GREY 18 (lighting only)")
    w.use_nodes = True
    nt = w.node_tree
    bg = nt.nodes["Background"]
    bg.inputs[0].default_value = (GREY, GREY, GREY, 1.0)
    bg.inputs[1].default_value = fill
    black = nt.nodes.new("ShaderNodeBackground")
    black.inputs[0].default_value = (0, 0, 0, 1)
    lp = nt.nodes.new("ShaderNodeLightPath")
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(lp.outputs["Is Camera Ray"], mix.inputs[0])
    nt.links.new(bg.outputs[0], mix.inputs[1])
    nt.links.new(black.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], nt.nodes["World Output"].inputs["Surface"])
    sc.world = w
    sc.view_settings.view_transform = "Standard"                # emission 1.0 = the scan's own pixel values
    sc.view_settings.look = "None"
    sc.view_settings.exposure = 0.0
    sc.view_settings.gamma = 1.0
    return sc, bg


def lamp(loc, aim, power: float, size=(0.35, 0.25), spread_deg=180.0):
    d = bpy.data.lights.new("LAMP 4300K", "AREA")
    d.shape = "RECTANGLE"
    d.size, d.size_y = size
    d.energy = power
    d.spread = math.radians(spread_deg)
    d.use_nodes = True
    nt = d.node_tree
    em = nt.nodes["Emission"]
    bb = nt.nodes.new("ShaderNodeBlackbody")
    bb.inputs[0].default_value = 4300.0
    wb = nt.nodes.new("ShaderNodeBlackbody")                    # the camera's white balance: 5200 K, so the
    wb.inputs[0].default_value = WHITE_BALANCE_K                # 4300 K lamp reads bone, not orange
    dv = nt.nodes.new("ShaderNodeVectorMath")
    dv.operation = "DIVIDE"
    nt.links.new(bb.outputs[0], dv.inputs[0])
    nt.links.new(wb.outputs[0], dv.inputs[1])
    nt.links.new(dv.outputs[0], em.inputs["Color"])
    ob = bpy.data.objects.new("LAMP", d)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = loc
    ob.rotation_mode = "QUATERNION"
    ob.rotation_quaternion = (Vector(aim) - Vector(loc)).to_track_quat("-Z", "Y")
    return ob


# ------------------------------------------------------------------------------------------------ images and materials

IMAGES: dict[str, str] = {}


def tex(name: str, noncolor: bool = False) -> bpy.types.Image:
    """A texture by its Chart manifest name (bytes checked against the pinned sha256). Nothing else may enter."""
    if name not in MAN:
        raise SystemExit(f"refused: image {name!r} is not in the Chart tex-manifest.json")
    e = MAN[name]["tex"]
    p = Path(e["file"])
    if hashlib.sha256(p.read_bytes()).hexdigest() != e["sha256"]:
        raise SystemExit(f"refused: {name} bytes differ from the manifest")
    img = bpy.data.images.load(str(p), check_existing=True)
    img.name = name
    img.colorspace_settings.name = "Non-Color" if noncolor else "sRGB"
    IMAGES[name] = str(p)
    return img


def _n(nt, kind, loc=(0, 0), **inputs):
    n = nt.nodes.new(kind)
    n.location = loc
    for k, v in inputs.items():
        n.inputs[k].default_value = v
    return n


def m_table() -> bpy.types.Material:
    """C-02 oak planks (CC0), 1.2 m per tile: diffuse, roughness and GL normal, varnish kept soft."""
    m = bpy.data.materials.new("table oak planks")
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    uv = _n(nt, "ShaderNodeTexCoord", (-900, 0))
    mp = _n(nt, "ShaderNodeMapping", (-700, 0))
    mp.inputs["Scale"].default_value = (1 / 1.2, 1 / 1.2, 1.0)
    nt.links.new(uv.outputs["Object"], mp.inputs["Vector"])
    for i, (k, nc) in enumerate((("diff", False), ("rough", True), ("nor_gl", True))):
        t = _n(nt, "ShaderNodeTexImage", (-450, 250 - 280 * i))
        t.image = tex(f"C-02_{k}", nc)
        nt.links.new(mp.outputs["Vector"], t.inputs["Vector"])
        if k == "diff":
            nt.links.new(t.outputs["Color"], bsdf.inputs["Base Color"])
        elif k == "rough":
            mr = _n(nt, "ShaderNodeMapRange", (-200, 0))
            mr.inputs["To Min"].default_value, mr.inputs["To Max"].default_value = 0.35, 0.75
            nt.links.new(t.outputs["Color"], mr.inputs["Value"])
            nt.links.new(mr.outputs["Result"], bsdf.inputs["Roughness"])
        else:
            nm = _n(nt, "ShaderNodeNormalMap", (-200, -300), Strength=0.6)
            nt.links.new(t.outputs["Color"], nm.inputs["Color"])
            nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    bsdf.inputs["Specular IOR Level"].default_value = 0.35
    return m


PAPER = (0.73, 0.66, 0.55, 1.0)            # C-01's margin paper (sRGB ~222, 212, 196), linear


def _paper_bump(nt, scan_lum=None):
    """Fibre relief in the sheet's own UV metres (so it stays on the paper as it rolls), plus the C-01 scan's ink as
    height (intaglio ink stands slightly proud)."""
    co = _n(nt, "ShaderNodeTexCoord", (-1500, -500))
    mp = _n(nt, "ShaderNodeMapping", (-1300, -500))
    mp.inputs["Scale"].default_value = (K.W * 2400.0, K.L * 900.0, 1.0)
    nt.links.new(co.outputs["UV"], mp.inputs["Vector"])
    nz = _n(nt, "ShaderNodeTexNoise", (-1100, -500), Detail=9.0, Roughness=0.62)
    nt.links.new(mp.outputs["Vector"], nz.inputs["Vector"])
    b1 = _n(nt, "ShaderNodeBump", (-850, -500), Strength=0.22, Distance=0.00012)
    nt.links.new(nz.outputs["Fac"], b1.inputs["Height"])
    if scan_lum is None:
        return b1
    inv = _n(nt, "ShaderNodeMath", (-1100, -750))
    inv.operation = "SUBTRACT"
    inv.inputs[0].default_value = 1.0
    nt.links.new(scan_lum, inv.inputs[1])
    b2 = _n(nt, "ShaderNodeBump", (-650, -600), Strength=0.10, Distance=0.00008)
    nt.links.new(inv.outputs[0], b2.inputs["Height"])
    nt.links.new(b1.outputs["Normal"], b2.inputs["Normal"])
    return b2


def m_paper(name: str, image: str, side: str) -> bpy.types.Material:
    """Laid paper, a matte Principled layer mixed with a translucent layer. 'face' is the scan. 'back' is the paper
    tone darkened by the scan's own ink, desaturated and at low contrast: the print showing through a thin sheet
    (the back shell carries the face's UVs, so seen from behind it is mirrored, as show-through is). 'edge' is
    paper tone."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    out = nt.nodes["Material Output"]
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.location = (-200, 200)
    t = _n(nt, "ShaderNodeTexImage", (-1300, 200))
    t.image = tex(image)
    t.interpolation = "Cubic"
    t.extension = "EXTEND"
    bw = _n(nt, "ShaderNodeRGBToBW", (-1100, -750))
    nt.links.new(t.outputs["Color"], bw.inputs["Color"])
    lum = bw.outputs["Val"]
    if side == "face":
        col = t.outputs["Color"]
    else:
        # show-through: PAPER * (1 - k * (1 - lum)), k = 0.32 on the back, 0 on the edge
        one_minus = _n(nt, "ShaderNodeMath", (-900, 300))
        one_minus.operation = "SUBTRACT"
        one_minus.inputs[0].default_value = 1.0
        nt.links.new(lum, one_minus.inputs[1])
        k = _n(nt, "ShaderNodeMath", (-750, 300))
        k.operation = "MULTIPLY_ADD"
        k.inputs[1].default_value = -(0.32 if side == "back" else 0.0)
        k.inputs[2].default_value = 1.0
        nt.links.new(one_minus.outputs[0], k.inputs[0])
        mix = _n(nt, "ShaderNodeMix", (-550, 300))
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        mix.inputs[0].default_value = 1.0
        mix.inputs[6].default_value = PAPER
        nt.links.new(k.outputs[0], mix.inputs[7])
        col = mix.outputs[2]
    nt.links.new(col, bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.66
    bsdf.inputs["Specular IOR Level"].default_value = 0.30
    bsdf.inputs["Sheen Weight"].default_value = 0.20
    bsdf.inputs["Sheen Roughness"].default_value = 0.6
    tr = _n(nt, "ShaderNodeBsdfTranslucent", (-200, -200))
    nt.links.new(col, tr.inputs["Color"])
    bump = _paper_bump(nt, lum if side == "face" else None)
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    nt.links.new(bump.outputs["Normal"], tr.inputs["Normal"])
    ms = _n(nt, "ShaderNodeMixShader", (150, 100))
    ms.inputs[0].default_value = 0.16
    nt.links.new(bsdf.outputs[0], ms.inputs[1])
    nt.links.new(tr.outputs[0], ms.inputs[2])
    nt.links.new(ms.outputs[0], out.inputs["Surface"])
    return m


def m_record(image: str, frames) -> tuple[bpy.types.Material, list[float]]:
    """The flat-hold shader: lit diffuse paper mixed toward pure emission of the scan at strength 1.0; the mix
    weight is baked per frame from kinematics.hold_mix (0 until 12 frames before the stop, 1 from the stop)."""
    m = bpy.data.materials.new(f"record {image} flat-hold")
    m.use_nodes = True
    nt = m.node_tree
    out = nt.nodes["Material Output"]
    bsdf = nt.nodes["Principled BSDF"]
    t = _n(nt, "ShaderNodeTexImage", (-900, 200))
    t.image = tex(image)
    t.interpolation = "Linear"
    t.extension = "EXTEND"
    nt.links.new(t.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.72
    bsdf.inputs["Specular IOR Level"].default_value = 0.25
    em = _n(nt, "ShaderNodeEmission", (-200, -200), Strength=1.0)
    nt.links.new(t.outputs["Color"], em.inputs["Color"])
    val = _n(nt, "ShaderNodeValue", (-200, 400))
    val.name = val.label = "flat_hold"
    ms = _n(nt, "ShaderNodeMixShader", (150, 100))
    nt.links.new(val.outputs[0], ms.inputs[0])
    nt.links.new(bsdf.outputs[0], ms.inputs[1])
    nt.links.new(em.outputs[0], ms.inputs[2])
    nt.links.new(ms.outputs[0], out.inputs["Surface"])
    vals = [0.0 if ARGS["calib"] else K.hold_mix(f) for f in frames]
    bake(val.outputs[0], "default_value", frames, vals)
    return m, vals


# ------------------------------------------------------------------------------------------------ geometry

Z0 = 0.00025                       # the chart's face sits 0.25 mm up: its back shell (0.13 mm) clears the table
PAPER_T = 0.00013
Y0 = K.L / 2                       # the chart's far edge (its north margin); it lays toward -y (camera)


def _cols() -> np.ndarray:
    """x samples across the sheet: 9 mm apart, 1.5 mm near each fold and each edge (creases stay sharp)."""
    xs = list(np.linspace(-K.W / 2, K.W / 2, 108))
    for u, _ in FOLDS_U:
        xf = u * K.W - K.W / 2
        xs += list(xf + np.linspace(-0.009, 0.009, 13))
    for e in (-K.W / 2, K.W / 2):
        xs += list(e + np.sign(-e) * np.linspace(0.0, 0.012, 9))
    xs = np.unique(np.round(np.clip(xs, -K.W / 2, K.W / 2), 6))
    return xs


def grid_mesh(name: str, sig: np.ndarray, xs: np.ndarray):
    """A sheet strip: rows along sigma (0 = north margin, far .. L), columns across x (west to east); UVs map C-01
    face up and unmirrored with north to +y; faces wound so the printed face's normal is +z when laid."""
    nv, nu = len(sig), len(xs)
    co = np.zeros((nv, nu, 3), np.float32)
    co[..., 0] = xs[None, :]
    co[..., 1] = (Y0 - sig)[:, None]
    me = bpy.data.meshes.new(name)
    idx = np.arange(nv * nu).reshape(nv, nu)
    quads = np.stack([idx[:-1, :-1], idx[1:, :-1], idx[1:, 1:], idx[:-1, 1:]], axis=-1).reshape(-1, 4)
    me.vertices.add(nv * nu)
    me.vertices.foreach_set("co", co.ravel())
    me.loops.add(quads.size)
    me.loops.foreach_set("vertex_index", quads.ravel())
    me.polygons.add(len(quads))
    me.polygons.foreach_set("loop_start", np.arange(0, quads.size, 4))
    me.polygons.foreach_set("loop_total", np.full(len(quads), 4))
    uvl = me.uv_layers.new(name="UVMap")
    u = ((xs + K.W / 2) / K.W)[None, :].repeat(nv, 0)
    v = (1.0 - sig / K.L)[:, None].repeat(nu, 1)
    uv = np.stack([u, v], -1).reshape(-1, 2)
    uvl.data.foreach_set("uv", uv[quads.ravel()].ravel())
    me.update()
    me.validate()
    me.shade_smooth()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def _crease(p: np.ndarray, length: float, folds, edge: float) -> np.ndarray:
    """Heights along one axis: linear between the creases (and the edges), with the crease kept sharp."""
    knots = [0.0] + [f * length for f, _ in folds] + [length]
    vals = [edge] + [h for _, h in folds] + [edge]
    return np.interp(p, knots, vals)


def fold_relief(S, X, scale: float = 1.0) -> np.ndarray:
    """Fold memory along C-01's real folds, a far-edge curl that never quite flattens and lifted side edges."""
    zf = _crease(X + K.W / 2, K.W, FOLDS_U, EDGE_LIFT) + _crease(S, K.L, FOLDS_V, EDGE_LIFT)
    z = scale * zf
    z += 0.0022 * np.exp(-S / 0.020)
    z += 0.0005 * np.exp(-(K.W / 2 - np.abs(X)) / 0.015)
    return z + Z0


def unroll_coords(f: float, sig, xs, relief, laid_t) -> np.ndarray:
    """Exact sheet positions at title frame f: laid behind the contact line (the fold memory returning and the
    residual curl decaying with the time since laydown), wound on the coned, eccentric spiral ahead of it."""
    st = K.roll_state(f)
    s, r, th = st["s"], st["r"], st["theta"]
    nv, nu = len(sig), len(xs)
    co = np.zeros((nv, nu, 3))
    co[..., 0] = xs[None, :]
    cone = 1.0 + xs * math.tan(math.radians(K.CONE_DEG / 2)) / r            # radius scale along the axis
    ecc = min(K.ECC, 0.5 * (r - K.R_CORE))                                    # never closes a layer gap
    lam_all = K.L - s
    for i, sg in enumerate(sig):
        if sg <= s:
            age = st["t"] - laid_t[i]
            back = 1.0 - math.exp(-max(0.0, age) / 0.6)                       # the folds come back as it relaxes
            co[i, :, 1] = Y0 - sg
            co[i, :, 2] = Z0 + (relief[i] - Z0) * back + K.curl(age)
        else:
            lam = sg - s
            phi, rho = K.spiral(lam, r)
            dy, dz = -rho * math.sin(phi), r - rho * math.cos(phi)
            w = min(1.0, lam / max(1e-6, lam_all))                             # the core's offset grows inward
            dy += ecc * w * math.sin(th)
            dz += ecc * w * (1.0 - math.cos(th)) * 0.5
            co[i, :, 1] = Y0 - s + dy * cone
            co[i, :, 2] = Z0 + dz * cone
    return co.reshape(-1, 3)


def bake_shape_keys(ob, frames, coords_of):
    """One shape key per frame, keyed 1 on its frame and 0 on its neighbours (linear), so the mesh is exact on
    every frame and Cycles' deformation blur interpolates between consecutive solved frames."""
    first = coords_of(frames[0])
    ob.data.vertices.foreach_set("co", first.ravel().astype(np.float32))
    ob.shape_key_add(name="Basis", from_mix=False)
    keys = ob.data.shape_keys
    keys.use_relative = True
    for f in frames:
        kb = ob.shape_key_add(name=f"F{f:04d}", from_mix=False)
        kb.data.foreach_set("co", coords_of(f).ravel().astype(np.float32))
        for ff, v in ((f - 1, 0.0), (f, 1.0), (f + 1, 0.0)):
            kb.value = v
            kb.keyframe_insert("value", frame=ff)
        kb.value = 0.0
    _linear(keys)


def solidify(ob, mats):
    for m in mats:
        ob.data.materials.append(m)
    mod = ob.modifiers.new("paper", "SOLIDIFY")
    mod.thickness = PAPER_T
    mod.offset = -1.0
    mod.use_even_offset = True
    mod.material_offset = 1
    mod.material_offset_rim = 2
    return mod


def chart_mats():
    return [m_paper("C-01 face", "C-01_chart", "face"), m_paper("C-01 back", "C-01_chart", "back"),
            m_paper("C-01 edge", "C-01_chart", "edge")]


def table():
    """A long planked top that always runs out of frame."""
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(0, 2.0, 0))
    ob = bpy.context.active_object
    ob.name = "table top"
    ob.scale = (3.0, 8.0, 1.0)
    bpy.ops.object.transform_apply(scale=True)
    ob.data.materials.append(m_table())
    return ob


def camera(lens=50.0):
    d = bpy.data.cameras.new("CAM")
    d.lens = lens
    d.sensor_fit = "HORIZONTAL"
    d.sensor_width = 36.0
    d.clip_start = 0.005
    d.clip_end = 30.0
    d.dof.use_dof = True
    ob = bpy.data.objects.new("CAM", d)
    bpy.context.scene.collection.objects.link(ob)
    bpy.context.scene.camera = ob
    return ob


# ------------------------------------------------------------------------------------------------ the proofs


def build_p2(sc, world_bg):
    frames = list(range(P2_FRAMES[0] - 1, P2_FRAMES[1] + 2))            # one solved frame either side for the blur
    table()
    sig = np.linspace(0.0, K.L, 820)                                      # 0.7 mm: 85 segments a turn at r = 9.5 mm
    xs = _cols()
    ob = grid_mesh("C-01 chart (unrolling)", sig, xs)
    S, X = np.meshgrid(sig, xs, indexing="ij")
    relief = fold_relief(S, X)
    laid_t = [K.laid_time(sg) for sg in sig]
    bake_shape_keys(ob, frames, lambda f: unroll_coords(f, sig, xs, relief, laid_t))
    solidify(ob, chart_mats())
    # camera: low and to the right of the roll's +x end; rises on one rostrum move across beats 3-4; from f324 the
    # focus racks over 48 frames (rostrum) from the roll to the Bay of Nankin's coastline, f/2.8 to f/4
    xr, yaw, dh = 0.465, math.radians(48.0), 0.47
    h0, h1 = 0.05, 0.21

    def axis(f):
        st = K.roll_state(f)
        return Vector((xr, Y0 - st["s"], Z0 + st["r"]))
    ink_s = INK[1] * K.L
    ink = Vector((INK[0] * K.W - K.W / 2, Y0 - ink_s, float(np.interp(INK[0] * K.W - K.W / 2, xs, relief[np.searchsorted(sig, ink_s)]))))
    b0, b1 = axis(BEATS34[0]), axis(BEATS34[1])
    cam = camera()
    locs, quats, focus, fstops = [], [], [], []
    for f in frames:
        p = rostrum((f - BEATS34[0]) / FPS, (BEATS34[1] - BEATS34[0]) / FPS)
        base = b0.lerp(b1, p)
        eye = base + Vector((math.sin(yaw) * dh, -math.cos(yaw) * dh, 0.0))
        eye.z = h0 + (h1 - h0) * p
        q = rostrum((f - RACK[0]) / FPS, (RACK[1] - RACK[0]) / FPS) if f >= RACK[0] else 0.0
        roll = axis(f)
        tgt = roll.lerp(ink, q)
        locs.append(eye)
        quats.append(list((tgt - eye).to_track_quat("-Z", "Y")))
        focus.append((roll - eye).length + ((ink - eye).length - (roll - eye).length) * q)
        fstops.append(2.8 + 1.2 * q)
    bake_ob(cam, frames, locs, quats)
    bake(cam.data.dof, "focus_distance", frames, focus)
    bake(cam.data.dof, "aperture_fstop", frames, fstops)
    mid = axis(sum(P2_FRAMES) / 2)
    lamp((0.05, mid.y + 0.30, 0.85), (mid.x - 0.05, mid.y - 0.02, 0.0), float(ARGS["lamp"] or LAMP_P2_W),
         size=(0.35, 0.25), spread_deg=75.0)
    return {"frames": P2_FRAMES, "ink": [round(c, 4) for c in ink], "camera": {
        "lens_mm": 50, "horizontal_m": dh, "height_m": [round(locs[1].z, 3), round(locs[-2].z, 3)],
        "focus_m": [round(focus[1], 3), round(focus[-2], 3)], "fstop": [2.8, 4.0], "yaw_deg": 48, "rack": RACK}}


def build_p1(sc, world_bg):
    frames = list(range(P1_FRAMES[0] - 1, P1_FRAMES[1] + 2))
    rec = TITLE["records"][ARGS["record"]]
    name = rec["tex"]
    w_px, h_px = MAN[name]["tex"]["size"]
    table()
    sig = np.linspace(0.0, K.L, 400)
    xs = _cols()
    ob = grid_mesh("C-01 chart (laid)", sig, xs)
    S, X = np.meshgrid(sig, xs, indexing="ij")
    relief = fold_relief(S, X, scale=0.35)                                # it has lain flat for beat 7
    co = np.zeros((len(sig), len(xs), 3))
    co[..., 0], co[..., 1], co[..., 2] = X, Y0 - S, relief
    ob.data.vertices.foreach_set("co", co.ravel().astype(np.float32))
    ob.data.update()
    solidify(ob, chart_mats())
    # the record: 92% of a 0.7 m top-down frame (0.4446 x 0.2608 m), 0.4 mm thick; it ends filling the frame height
    frame_h_07 = 0.70 * (36.0 / 50.0) * 9 / 16
    sh = 0.92 * frame_h_07
    sw = sh * w_px / h_px
    thick = 0.0004
    under = (np.abs(X) <= sw / 2) & (np.abs(Y0 - S) <= sh / 2)
    z_rest = float(relief[under].max()) + 0.00005                         # resting on the highest crease under it
    z_wood = 0.00005
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    sheet = bpy.context.active_object
    sheet.name = f"record {ARGS['record']}"
    sheet.scale = (sw, sh, thick)
    bpy.ops.object.transform_apply(scale=True)
    bev = sheet.modifiers.new("edge", "BEVEL")
    bev.width = 0.00012
    bev.segments = 2
    bev.limit_method = "NONE"
    me = sheet.data
    uvl = me.uv_layers.active
    mat, mixes = m_record(name, frames)
    me.materials.append(mat)
    me.materials.append(m_paper("record edge", "C-01_chart", "edge"))
    for poly in me.polygons:                                             # top face takes the scan, whole; others paper
        top = poly.normal.z > 0.9
        poly.material_index = 0 if top else 1
        for li in poly.loop_indices:
            v = me.vertices[me.loops[li].vertex_index].co
            uvl.data[li].uv = ((v.x / sw + 0.5), (v.y / sh + 0.5)) if top else (0.5, 0.5)
    chart_near = Y0 - K.L                                                 # the chart's near (south) edge
    locs, quats = [], []
    for f in frames:
        st = K.slide_state(f)
        lead = st["offset"] + sh / 2                                      # the record's leading edge
        k = smoothstep((lead - chart_near) / 0.015)                       # it rides up onto the chart's edge
        z = z_wood + (z_rest - z_wood) * k + thick / 2
        locs.append(Vector((0.0, st["offset"], z)))
        quats.append(list(Euler((0.0, 0.0, st["yaw"])).to_quaternion()))
    bake_ob(sheet, frames, locs, quats)
    z_top = z_rest + thick
    # camera: 0.9 m at 70 degrees down (beat 7's end) to exactly top-down on rostrum over the slide, ending where
    # the record fills the frame height (the A40 HOLD fit: the whole scan, contained, centred)
    d_end = sh / ((36.0 / 50.0) * 9 / 16)
    cam = camera()
    locs, quats, focus = [], [], []
    for f in frames:
        p = rostrum((f - K.SLIDE_F0) / FPS, K.SLIDE_T)
        pitch = math.radians(70.0 + 20.0 * p)
        d = 0.90 + (d_end - 0.90) * p
        if p >= 1.0:
            locs.append(Vector((0.0, 0.0, z_top + d_end)))
            quats.append([1.0, 0.0, 0.0, 0.0])
        else:
            locs.append(Vector((0.0, -d * math.cos(pitch), z_top + d * math.sin(pitch))))
            quats.append(list(Euler((math.pi / 2 - pitch, 0.0, 0.0)).to_quaternion()))
        focus.append(d)
    bake_ob(cam, frames, locs, quats)
    cam.data.dof.aperture_fstop = 8.0
    bake(cam.data.dof, "focus_distance", frames, focus)
    # the light closes onto the record: over the 12-frame blend the lamp travels from above-left to over the record,
    # its pool narrows to the record's footprint (inset 1 cm, spread 180 to 1 degree, so nothing spills onto the
    # chart; power follows the pool's area so the record's irradiance holds), and the grey fill falls to zero; the chart goes to black around the only lit thing
    p0, a0 = Vector((-0.40, 0.18, 0.95)), Vector((0.0, 0.0, 0.0))
    p1 = Vector((0.0, 0.0, 1.0))
    lw, lh = sw - 0.02, sh - 0.02                                         # the pool's final footprint, inset 1 cm
    e_end = float(ARGS["lamp_end"] or LAMP_END_W)
    irr = e_end / (lw * lh)                                               # irradiance of the collimated pool (W/m^2)
    L = lamp(p0, a0, float(ARGS["lamp"] or LAMP_W), size=(lw, lh), spread_deg=180.0)
    locs, quats, spreads, energy, fills, sx, sy = [], [], [], [], [], [], []
    q_down = Vector((0, 0, -1)).to_track_quat("-Z", "Y")
    q0 = (a0 - p0).to_track_quat("-Z", "Y")
    w0 = float(ARGS["lamp"] or LAMP_W)
    for f in frames:
        u = K.hold_mix(f)
        pos = p0.lerp(p1, u)
        locs.append(pos)
        quats.append(list(q0.slerp(q_down, u)))
        spread = math.radians(180.0 * (1.0 / 180.0) ** u)                 # geometric: 180, ..., 1 degree
        spreads.append(spread)
        # constant irradiance on the record while the pool narrows: power over the pool's area at the record
        h = pos.z
        grow = 2.0 * h * math.tan(min(spread, math.radians(170.0)) / 2.0)
        area = min(math.pi * h * h, (lw + grow) * (lh + grow))
        energy.append(w0 if u <= 0.0 else min(w0, irr * area) if u < 1.0 else e_end)
        fills.append(1.0 - u)
        sx.append(0.12 + (lw - 0.12) * u)                                 # a small key for a crisp contact
        sy.append(0.09 + (lh - 0.09) * u)                                 # shadow, growing into the pool
    bake_ob(L, frames, locs, quats)
    for path, vals in (("spread", spreads), ("energy", energy), ("size", sx), ("size_y", sy)):
        bake(L.data, path, frames, vals)
    bake(world_bg.inputs[1], "default_value", frames, fills)
    return {"frames": P1_FRAMES, "record": ARGS["record"], "sheet_m": [round(sw, 5), round(sh, 5)],
            "camera_end_m": round(d_end, 4), "sheet_px": [round(1080 * w_px / h_px, 1), 1080.0],
            "hold_mix": {f: round(v, 4) for f, v in zip(frames, mixes) if 0 < v < 1 or f in (K.SLIDE_STOP, frames[-1])},
            "lamp_w": [w0, e_end], "camera": {"lens_mm": 50, "fstop": 8.0, "pitch_deg_end": 90}}


def render_settings(sc):
    p = PROFILE
    calib = bool(ARGS["calib"])
    sc.render.resolution_x, sc.render.resolution_y = (480, 270) if calib else tuple(p["res"])
    sc.render.resolution_percentage = 100
    sc.render.use_motion_blur = p["motion_blur"]
    sc.render.motion_blur_shutter = 0.5                                 # 180 degrees, a 24 fps camera
    sc.render.film_transparent = False
    sc.render.engine = "CYCLES"
    cy = sc.cycles
    cy.device = "GPU"
    cy.samples = 32 if calib else p["samples"]
    cy.use_adaptive_sampling = True
    cy.adaptive_threshold = p["noise_threshold"]
    cy.adaptive_min_samples = min(p["min_samples"], cy.samples)
    cy.use_denoising = True
    cy.denoiser = "OPENIMAGEDENOISE"
    cy.denoising_input_passes = "RGB_ALBEDO_NORMAL"
    cy.denoising_prefilter = "ACCURATE"
    cy.denoising_use_gpu = True
    cy.max_bounces, cy.diffuse_bounces, cy.glossy_bounces = 6, 3, 3
    cy.transmission_bounces, cy.transparent_max_bounces = 4, 8
    cy.caustics_reflective = cy.caustics_refractive = False
    cy.sample_clamp_indirect = 5.0
    cy.use_animated_seed = True
    cy.texture_limit_render = "8192"
    sc.render.use_persistent_data = True
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGB"
    sc.render.image_settings.color_depth = "8"
    sc.render.image_settings.compression = 15
    sc.render.use_overwrite = False
    sc.render.use_placeholder = True


def check_provenance():
    """Every image datablock is a Chart manifest texture whose source is a Chart ledger item or a film's record."""
    ok = {i["id"] for i in LEDGER["items"] if i.get("sha256") and not i.get("ai")} | set(LEDGER["records"])
    bad = []
    for img in bpy.data.images:
        if not img.filepath:
            continue
        src = MAN.get(img.name, {}).get("from")
        if src not in ok:
            bad.append(f"{img.name} (from {src})")
    if bad:
        raise SystemExit("provenance check failed: " + ", ".join(bad))
    print(f"provenance: {len(IMAGES)} images, each from a Chart ledger item or a film record; none ai")


def main():
    import time
    t0 = time.time()
    proof = ARGS["proof"]
    f0, f1 = P1_FRAMES if proof == "p1" else P2_FRAMES
    sc, world_bg = reset_scene(f0, f1, 1.0 if proof == "p1" else P2_FILL)
    info = build_p1(sc, world_bg) if proof == "p1" else build_p2(sc, world_bg)
    render_settings(sc)
    check_provenance()
    sc.frame_set(f0)
    out = ARGS["out"] or str(MEDIA / "blend" / f"chart-{proof}.blend")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=out, compress=False)
    info.update(proof=proof, blend=out, images=sorted(IMAGES), build_s=round(time.time() - t0, 1))
    print("CHART-BUILD " + json.dumps(info))


if __name__ == "__main__":
    main()
