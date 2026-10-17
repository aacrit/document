"""void document · As It Was: build the title machine in Blender from code. Nobody hand-edits the .blend.

    blender -b --factory-startup --python design/title-sequence/blender/build_scene.py -- \
        --record S-130 --profile animatic            # writes D:/document-media/title-sequence/blend/title-S-130-animatic.blend

Options: --record S-130 | S-16928 | C20-METAR-0851 (beat 11's swappable module), --profile animatic | proof | final,
--drop M05,M06 (the horizon rule: drop modules; the chain closes at the anchors), --out <path>.

Reads title.json (beats, frames), the texture manifest written by prep_textures.py (every image must be in it; the
build refuses any other) and the house motion system (studio/engine/motion.py: Spring.progress for arrive, settle,
stamp, drift, trace; rostrum for the camera), lifted out by its source so the springs are the film's own numbers.
Every animated value is baked as one linear key per frame. No Blender easing, no handles, no generative model.
"""

from __future__ import annotations

import ast
import json
import math
import random
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
CFG = json.loads((HERE / "title.json").read_text(encoding="utf-8"))
FPS = CFG["fps"]
MEDIA = Path(CFG["paths"]["media"])
MAN = json.loads((MEDIA / "tex-manifest.json").read_text(encoding="utf-8"))
LAST = CFG["machine_last_frame"]                 # 1151: Blender renders 0..1151; the engine makes the rest


def _args() -> dict:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    a = {"record": "S-130", "profile": "animatic", "drop": "", "out": "", "png": ""}
    for i, k in enumerate(argv):
        if k.startswith("--") and i + 1 < len(argv):
            a[k[2:]] = argv[i + 1]
    return a


ARGS = _args()
PROFILE = CFG["render"][ARGS["profile"]]
TEXSET = "tex-lite" if PROFILE["tex"] == "lite" else "tex"


# ------------------------------------------------------------------------------------------------ house motion


def _load_motion() -> dict:
    """Exec only the closed-form pieces of studio/engine/motion.py (it imports PIL, which Blender lacks)."""
    tree = ast.parse((REPO / "studio/engine/motion.py").read_text(encoding="utf-8"))
    funcs = {"clamp01", "smoothstep", "rostrum", "ease_in_quad", "ease_out_quad", "ease_in_sine", "ease_out_sine", "sine_inout"}
    names = {"STAMP", "SETTLE", "ARRIVE", "DRIFT", "WHISPER", "TRACE"}
    body = ast.parse("import math\nfrom dataclasses import dataclass\nfrom functools import lru_cache\n").body
    for n in tree.body:
        if (isinstance(n, ast.FunctionDef) and n.name in funcs) or (isinstance(n, ast.ClassDef) and n.name == "Spring") or \
           (isinstance(n, ast.Assign) and any(getattr(t, "id", None) in names for t in n.targets)):
            body.append(n)
    ns: dict = {}
    exec(compile(ast.Module(body=body, type_ignores=[]), "studio/engine/motion.py (closed forms)", "exec"), ns)
    return ns


MO = _load_motion()
STAMP, SETTLE, ARRIVE, DRIFT, TRACE = MO["STAMP"], MO["SETTLE"], MO["ARRIVE"], MO["DRIFT"], MO["TRACE"]
smoothstep, clamp01 = MO["smoothstep"], MO["clamp01"]


def sp(spring, f: float, f0: float) -> float:
    """A house spring's progress at frame f for a move that starts at frame f0 (0 before it starts)."""
    return 0.0 if f < f0 else spring.progress((f - f0) / FPS)


def sp_frames(spring) -> int:
    return spring.frames(FPS)


FRAMES = np.arange(0, LAST + 1)


# ------------------------------------------------------------------------------------------------ scene basics


def reset_scene() -> bpy.types.Scene:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.name = "title"
    sc.render.fps = FPS
    sc.frame_start, sc.frame_end = 0, LAST
    sc.unit_settings.system = "METRIC"
    w = bpy.data.worlds.new("WORLD")
    w.use_nodes = True
    bg = w.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (1.0, 1.0, 1.0, 1.0)
    bg.inputs[1].default_value = 0.002                 # near-black: shadow lift only, no HDRI
    sc.world = w
    try:
        sc.view_settings.view_transform = "Khronos PBR Neutral"
    except TypeError:
        sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.view_settings.exposure = 0.0
    return sc


IMAGES: dict[str, str] = {}


def tex(name: str, noncolor: bool = False) -> bpy.types.Image:
    """Load a prepared texture by its manifest name. Nothing else may enter the .blend as an image."""
    if name not in MAN or TEXSET not in MAN[name]:
        raise SystemExit(f"refused: image {name!r} is not in tex-manifest.json")
    f = MAN[name][TEXSET]["file"]
    img = bpy.data.images.load(f, check_existing=True)
    img.name = name
    if noncolor:
        img.colorspace_settings.name = "Non-Color"
    IMAGES[name] = f
    return img


def coll(name: str) -> bpy.types.Collection:
    c = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(c)
    return c


def link(obj, c, parent=None):
    c.objects.link(obj)
    if parent is not None:
        obj.parent = parent
    return obj


def mesh_obj(name: str, bm: bmesh.types.BMesh, mat=None, smooth=False) -> bpy.types.Object:
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    if smooth:
        me.shade_smooth()
    ob = bpy.data.objects.new(name, me)
    if mat is not None:
        if isinstance(mat, (list, tuple)):
            for m in mat:
                me.materials.append(m)
        else:
            me.materials.append(mat)
    return ob


def bevel(ob, width=0.003, segs=2):
    m = ob.modifiers.new("bevel", "BEVEL")
    m.width, m.segments, m.limit_method = width, segs, "ANGLE"
    m.harden_normals = False
    return ob


# ------------------------------------------------------------------------------------------------ geometry


def grid(name, w, h, nx=1, ny=1, mat=None) -> bpy.types.Object:
    """A w x h plane in XY, centred, UV 0..1 with v up along +Y (an image reads upright from above)."""
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")
    verts = [[bm.verts.new(((i / nx - 0.5) * w, (j / ny - 0.5) * h, 0.0)) for i in range(nx + 1)] for j in range(ny + 1)]
    for j in range(ny):
        for i in range(nx):
            f = bm.faces.new((verts[j][i], verts[j][i + 1], verts[j + 1][i + 1], verts[j + 1][i]))
            for loop in f.loops:
                x, y, _ = loop.vert.co
                loop[uv].uv = (x / w + 0.5, y / h + 0.5)
    return mesh_obj(name, bm, mat)


def box(name, sx, sy, sz, mat=None, origin=(0, 0, 0)) -> bpy.types.Object:
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * sx, v.co.y * sy, v.co.z * sz)) - Vector(origin)
    bm.loops.layers.uv.new("UVMap")
    return mesh_obj(name, bm, mat)


def cylinder(name, r, depth, segs=48, mat=None, axis="Z") -> bpy.types.Object:
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=segs, radius1=r, radius2=r, depth=depth)
    if axis == "X":
        bmesh.ops.rotate(bm, verts=bm.verts, matrix=Matrix.Rotation(math.pi / 2, 3, "Y"))
    elif axis == "Y":
        bmesh.ops.rotate(bm, verts=bm.verts, matrix=Matrix.Rotation(math.pi / 2, 3, "X"))
    bm.loops.layers.uv.new("UVMap")
    return mesh_obj(name, bm, mat, smooth=True)


def torus(name, R, r, seg=64, ring=12, mat=None) -> bpy.types.Object:
    bm = bmesh.new()
    rows = []
    for i in range(seg):
        a = 2 * math.pi * i / seg
        row = []
        for j in range(ring):
            b = 2 * math.pi * j / ring
            row.append(bm.verts.new(((R + r * math.cos(b)) * math.cos(a), (R + r * math.cos(b)) * math.sin(a), r * math.sin(b))))
        rows.append(row)
    for i in range(seg):
        for j in range(ring):
            bm.faces.new((rows[i][j], rows[(i + 1) % seg][j], rows[(i + 1) % seg][(j + 1) % ring], rows[i][(j + 1) % ring]))
    return mesh_obj(name, bm, mat, smooth=True)


def gear(name, teeth, r_root, r_tip, thick, mat=None, hole=0.0, steps=6) -> bpy.types.Object:
    """A spur gear (trapezoid teeth) as a fan-triangulated prism, so a concave outline stays correct."""
    pts = []
    for k in range(teeth):
        a0 = 2 * math.pi * k / teeth
        da = 2 * math.pi / teeth
        for (fa, rr) in ((0.0, r_root), (0.18, r_root), (0.30, r_tip), (0.70, r_tip), (0.82, r_root)):
            a = a0 + fa * da
            pts.append((rr * math.cos(a), rr * math.sin(a)))
    bm = bmesh.new()
    top = [bm.verts.new((x, y, thick / 2)) for x, y in pts]
    bot = [bm.verts.new((x, y, -thick / 2)) for x, y in pts]
    n = len(pts)
    if hole > 0:
        ht = [bm.verts.new((hole * math.cos(2 * math.pi * i / n), hole * math.sin(2 * math.pi * i / n), thick / 2)) for i in range(n)]
        hb = [bm.verts.new((hole * math.cos(2 * math.pi * i / n), hole * math.sin(2 * math.pi * i / n), -thick / 2)) for i in range(n)]
        for i in range(n):
            j = (i + 1) % n
            bm.faces.new((ht[i], top[i], top[j], ht[j]))
            bm.faces.new((hb[j], bot[j], bot[i], hb[i]))
            bm.faces.new((hb[i], ht[i], ht[j], hb[j]))
    else:
        ct, cb = bm.verts.new((0, 0, thick / 2)), bm.verts.new((0, 0, -thick / 2))
        for i in range(n):
            j = (i + 1) % n
            bm.faces.new((ct, top[i], top[j]))
            bm.faces.new((cb, bot[j], bot[i]))
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((top[i], bot[i], bot[j], top[j]))
    bm.normal_update()
    bm.loops.layers.uv.new("UVMap")
    return mesh_obj(name, bm, mat)


def curve_obj(name, pts, radius, mat=None, tilt=None, bevel_obj=None, res=2) -> bpy.types.Object:
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.resolution_u = res
    s = cu.splines.new("POLY")
    s.points.add(len(pts) - 1)
    for i, p in enumerate(pts):
        s.points[i].co = (p[0], p[1], p[2], 1.0)
        if tilt is not None:
            s.points[i].tilt = tilt[i]
    if bevel_obj is not None:
        cu.bevel_mode = "OBJECT"
        cu.bevel_object = bevel_obj
    else:
        cu.bevel_depth = radius
        cu.bevel_resolution = 3
    cu.use_fill_caps = True
    ob = bpy.data.objects.new(name, cu)
    if mat is not None:
        cu.materials.append(mat)
    return ob


def ribbon(name, pts, width, mat, side=(0, 1, 0), n=120):
    """A flat strip of paper along a smooth path (Catmull-Rom through pts), u along its length 0..1."""
    P = [Vector(p) for p in pts]
    samples = []
    for i in range(len(P) - 1):
        for k in range(n // (len(P) - 1)):
            u = k / (n // (len(P) - 1))
            samples.append(catmull(P[max(0, i - 1)], P[i], P[i + 1], P[min(len(P) - 1, i + 2)], u))
    samples.append(P[-1])
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")
    sv = Vector(side).normalized()
    rows = []
    for q in samples:
        rows.append((bm.verts.new(q - sv * width / 2), bm.verts.new(q + sv * width / 2)))
    m = len(rows) - 1
    for i in range(m):
        f = bm.faces.new((rows[i][0], rows[i + 1][0], rows[i + 1][1], rows[i][1]))
        for loop, (uu, vv) in zip(f.loops, ((i / m, 0), ((i + 1) / m, 0), ((i + 1) / m, 1), (i / m, 1))):
            loop[uv].uv = (uu, vv)
    return mesh_obj(name, bm, mat, smooth=True)


# ------------------------------------------------------------------------------------------------ materials


def _nodes(mat):
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs[0], out.inputs[0])
    return nt, bsdf, out


def lin(rgb):
    """sRGB (as authored, 0..1) to linear."""
    return tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb)


def m_plain(name, rgb, rough=0.6, metal=0.0, spec=0.5):
    mat = bpy.data.materials.new(name)
    nt, b, _ = _nodes(mat)
    b.inputs["Base Color"].default_value = (*lin(rgb), 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    b.inputs["Specular IOR Level"].default_value = spec
    return mat


def m_brass():
    return m_plain("brass", (0.62, 0.46, 0.22), rough=0.32, metal=1.0)


def m_iron():
    return m_plain("iron", (0.10, 0.10, 0.10), rough=0.45, metal=1.0)


def m_lacquer():
    return m_plain("black lacquer", (0.012, 0.012, 0.012), rough=0.25)


def _noise_ramp(nt, scale, detail, c0, c1, coord=None):
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = scale
    n.inputs["Detail"].default_value = detail
    if coord is not None:
        nt.links.new(coord, n.inputs["Vector"])
    r = nt.nodes.new("ShaderNodeValToRGB")
    r.color_ramp.elements[0].color = (*lin(c0), 1)
    r.color_ramp.elements[1].color = (*lin(c1), 1)
    nt.links.new(n.outputs["Fac"], r.inputs[0])
    return n, r


def m_wood(name="wood", dark=False):
    mat = bpy.data.materials.new(name)
    nt, b, _ = _nodes(mat)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (2.0, 2.0, 30.0)
    nt.links.new(tc.outputs["Object"], mp.inputs[0])
    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.inputs["Scale"].default_value = 22.0
    wave.inputs["Distortion"].default_value = 1.5
    wave.inputs["Detail"].default_value = 3.0
    nt.links.new(mp.outputs[0], wave.inputs["Vector"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    c0, c1 = ((0.10, 0.065, 0.045), (0.16, 0.105, 0.07)) if dark else ((0.24, 0.15, 0.09), (0.36, 0.23, 0.14))
    ramp.color_ramp.elements[0].color = (*lin(c0), 1)
    ramp.color_ramp.elements[1].color = (*lin(c1), 1)
    nt.links.new(wave.outputs["Fac"], ramp.inputs[0])
    nt.links.new(ramp.outputs[0], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.55
    return mat


def m_clay():
    """Fired clay from noise alone (no image)."""
    mat = bpy.data.materials.new("fired clay")
    nt, b, _ = _nodes(mat)
    n, r = _noise_ramp(nt, 9.0, 6.0, (0.36, 0.25, 0.18), (0.50, 0.36, 0.26))
    nt.links.new(r.outputs[0], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.9
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.25
    bump.inputs["Distance"].default_value = 0.002
    nt.links.new(n.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs[0], b.inputs["Normal"])
    return mat


def m_image(name, img_name, rough=0.72, alpha=False, bump=0.0, sheen=0.25, value_node=False):
    """A scan as the surface (paper, vellum, clay). Optional bump from the scan's own luminance (raking light)."""
    mat = bpy.data.materials.new(name)
    nt, b, _ = _nodes(mat)
    it = nt.nodes.new("ShaderNodeTexImage")
    it.image = tex(img_name)
    it.interpolation = "Smart"
    it.extension = "CLIP" if alpha else "EXTEND"
    nt.links.new(it.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = rough
    b.inputs["Sheen Weight"].default_value = sheen
    b.inputs["Sheen Roughness"].default_value = 0.6
    if alpha:
        nt.links.new(it.outputs["Alpha"], b.inputs["Alpha"])
        mat.surface_render_method = "DITHERED"
        mat.use_transparent_shadow = True
    if bump > 0:
        bp = nt.nodes.new("ShaderNodeBump")
        bp.inputs["Strength"].default_value = bump
        bp.inputs["Distance"].default_value = 0.0008
        nt.links.new(it.outputs["Color"], bp.inputs["Height"])
        nt.links.new(bp.outputs[0], b.inputs["Normal"])
    if value_node:   # a fade: alpha times a keyed value
        v = nt.nodes.new("ShaderNodeValue")
        v.name = "fade"
        v.outputs[0].default_value = 1.0
        mult = nt.nodes.new("ShaderNodeMath")
        mult.operation = "MULTIPLY"
        nt.links.new(it.outputs["Alpha"] if alpha else v.outputs[0], mult.inputs[0])
        nt.links.new(v.outputs[0], mult.inputs[1])
        nt.links.new(mult.outputs[0], b.inputs["Alpha"])
        mat.surface_render_method = "DITHERED"
    return mat


def m_fade(base: bpy.types.Material) -> bpy.types.Material:
    """Add a keyed 'fade' Value node to a material's alpha (for departures, which are fades)."""
    nt = base.node_tree
    b = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    v = nt.nodes.new("ShaderNodeValue")
    v.name = "fade"
    v.outputs[0].default_value = 1.0
    nt.links.new(v.outputs[0], b.inputs["Alpha"])
    base.surface_render_method = "DITHERED"
    base.use_transparent_shadow = True
    return base


def m_volume(name, density, noise_scale=3.0, color=(1, 1, 1)):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    vol = nt.nodes.new("ShaderNodeVolumePrincipled")
    vol.inputs["Color"].default_value = (*color, 1)
    vol.inputs["Anisotropy"].default_value = 0.35
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = noise_scale
    n.inputs["Detail"].default_value = 2.0
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    mul.inputs[1].default_value = density * 2.0
    nt.links.new(n.outputs["Fac"], mul.inputs[0])
    nt.links.new(mul.outputs[0], vol.inputs["Density"])
    nt.links.new(vol.outputs[0], out.inputs["Volume"])
    return mat


# ------------------------------------------------------------------------------------------------ baking


INTERP_LINEAR = 1


def fcurve(owner, path: str, index: int = 0):
    """The F-curve for owner.path[index]. Blender 4.4 keeps object data (a light, a camera) in its object's action
    under its own slot, so look in the slot's channelbag first."""
    ad = owner.animation_data
    act = ad.action
    try:
        from bpy_extras.anim_utils import action_get_channelbag_for_slot
        cb = action_get_channelbag_for_slot(act, ad.action_slot)
        if cb is not None:
            fc = cb.fcurves.find(path, index=index)
            if fc is not None:
                return fc
    except ImportError:
        pass
    return act.fcurves.find(path, index=index)


def bake(owner, path: str, frames, values, index: int = -1):
    """One linear key per frame on owner.path[index] (values a 1-D sequence)."""
    frames = list(frames)
    values = [float(v) for v in values]
    owner.keyframe_insert(data_path=path, index=index, frame=frames[0])
    fc = fcurve(owner, path, max(index, 0))
    fc.keyframe_points.clear()
    fc.keyframe_points.add(len(frames))
    co = np.empty(2 * len(frames), np.float64)
    co[0::2] = frames
    co[1::2] = values
    fc.keyframe_points.foreach_set("co", co)
    fc.keyframe_points.foreach_set("interpolation", [INTERP_LINEAR] * len(frames))
    fc.update()


def bake_vec(ob, path, frames, vecs, n=3):
    arr = np.asarray(vecs, np.float64)
    for i in range(n):
        bake(ob, path, frames, arr[:, i], index=i)


def key_visible(ob, f_on: int, f_off: int):
    """hide_render as constant keys: rendered on [f_on, f_off)."""
    seq = ([(0, False)] if f_on <= 0 else [(0, True), (f_on, False)]) + ([(f_off, True)] if f_off <= LAST else [])
    for path in ("hide_render",):           # hide_viewport is never animated: it rebuilds depsgraph relations and can crash
        for f, v in seq:
            setattr(ob, path, v)
            ob.keyframe_insert(path, frame=f)
        fc = fcurve(ob, path)
        for kp in fc.keyframe_points:
            kp.interpolation = "CONSTANT"


def node_value(mat, name="fade"):
    return mat.node_tree.nodes[name]


def bake_node(mat, node_name, frames, values):
    bake(mat.node_tree, f'nodes["{node_name}"].outputs[0].default_value', frames, values)


# ------------------------------------------------------------------------------------------------ poses and lights


def look(eye, target, up=(0, 0, 1)) -> Matrix:
    e, t, u = Vector(eye), Vector(target), Vector(up)
    f = (t - e).normalized()
    if abs(f.dot(u.normalized())) > 0.999:
        u = Vector((0, 1, 0))
    r = f.cross(u).normalized()
    uu = r.cross(f)
    m = Matrix.Identity(4)
    m.col[0][:3], m.col[1][:3], m.col[2][:3], m.col[3][:3] = r, uu, -f, e
    return m


def light(name, kind, c, parent, energy, color=(1.0, 0.95, 0.88), size=0.1, spot_deg=40, blend=0.35):
    """'The reader': one neutral lamp (bone white point, never amber or blue). One per module, never two lit at once."""
    ld = bpy.data.lights.new(name, kind)
    ld.energy = energy
    ld.color = color
    if kind == "SPOT":
        ld.spot_size = math.radians(spot_deg)
        ld.spot_blend = blend
        ld.shadow_soft_size = size
    elif kind == "AREA":
        ld.size = size
    else:
        ld.shadow_soft_size = size
    ob = bpy.data.objects.new(name, ld)
    link(ob, c, parent)
    return ob


def aim(ob, eye, target, up=(0, 0, 1)):
    ob.matrix_local = look(eye, target, up)


LAMP_SCALE = 0.3

STATION = ((0.0, 0.0, 1.2), (0.0, 0.0, 0.0), (0.0, 1.0, 0.0))   # straight down, 1.2 m above the sheet, image up = +Y


def anchor(loc, yaw_deg=0.0) -> Matrix:
    return Matrix.Translation(Vector(loc)) @ Matrix.Rotation(math.radians(yaw_deg), 4, "Z")


# ------------------------------------------------------------------------------------------------ modules


class Module:
    """A module builds its objects under a root empty in its own local space. It declares camera keys
    (frames relative to its start; key 0 is its entry pose), the anchor where the next module's origin
    sits, its lamp windows and its constant motions."""

    ov_in = 18      # frames visible before its start (a station pass shows the next sheet early)
    ov_out = 18

    def __init__(self, spec: dict):
        self.id, self.start, self.end = spec["id"], spec["start"], spec["end"]
        self.c = coll(f'{self.id}_{spec["name"].lower()}')
        self.root = bpy.data.objects.new(f"{self.id}_root", None)
        self.c.objects.link(self.root)
        self.cam: list = []              # (rel_frame, eye, target, up, lens)
        self.next_anchor = anchor((0, 0, 0))
        self.lamps: list = []            # (light object, energy)

    def add(self, ob, parent=None):
        return link(ob, self.c, parent or self.root)

    def f(self, rel):                   # global frame
        return self.start + rel

    def key(self, rel, eye, target, up=(0, 0, 1), lens=50.0):
        self.cam.append((self.start + rel, eye, target, up, lens))

    def build(self):
        raise NotImplementedError

    def lamp(self, ob, energy):
        self.lamps.append((ob, energy * LAMP_SCALE))
        return ob


# --- 1. Clay -------------------------------------------------------------------------------------


class Clay(Module):
    ov_in = 0

    def build(self):
        clay = m_clay()
        r_root, r_tip = 0.355, 0.395                          # 24 teeth, one per column
        ring = self.add(bevel(gear("M01_ring", 24, r_root, r_tip, 0.05, clay), 0.004))
        rim = self.add(torus("M01_ring_rim", 0.235, 0.012, mat=clay), ring)
        rim.location.z = 0.027
        seat = self.add(bevel(cylinder("M01_seat", 0.25, 0.012, 96, clay), 0.002), ring)
        seat.location.z = 0.03
        # the tablet, 30.5 x 31 x 5 cm (Walters record), each face its own scan
        mats = [m_image("T-01 obverse", "T-01_obverse", rough=0.85, bump=0.6, sheen=0.0),
                m_image("T-01 reverse", "T-01_reverse", rough=0.85, bump=0.4, sheen=0.0),
                m_image("T-01 edge top", "T-01_edge_top", rough=0.85, sheen=0.0),
                m_image("T-01 edge bottom", "T-01_edge_bottom", rough=0.85, sheen=0.0),
                m_image("T-01 edge left", "T-01_edge_left", rough=0.85, sheen=0.0),
                m_image("T-01 edge right", "T-01_edge_right", rough=0.85, sheen=0.0)]
        tab = self.add(self._tablet(0.305, 0.31, 0.05, mats), ring)
        tab.location.z = 0.036 + 0.025
        # the second ring meshes across the frame (20 teeth, same pitch)
        k = 20 / 24
        ring2 = self.add(bevel(gear("M01_ring2", 20, r_root * k + 0.04 * (1 - k) * 0, r_root * k + (r_tip - r_root), 0.05, clay), 0.004))
        d = r_root * (1 + k) + (r_tip - r_root) * 0.55
        ring2.location = (d * math.cos(math.radians(40)), d * math.sin(math.radians(40)), -0.004)
        rim2 = self.add(torus("M01_ring2_rim", 0.2, 0.012, mat=clay), ring2)
        rim2.location.z = 0.027
        # motion: still until frame 50, then engages on `settle` to 15 degrees a second (one column a second)
        w = math.radians(15.0) / FPS
        ang, a = [], 0.0
        for fr in FRAMES:
            a += w * sp(SETTLE, fr, 50)
            ang.append(a)
        bake(ring, "rotation_euler", FRAMES, ang, 2)
        bake(ring2, "rotation_euler", FRAMES, [-x / k + math.pi / 20 for x in ang], 2)
        # dust in the beam: a bounded volume and procedural motes (no image)
        vol = self.add(box("M01_dust", 1.6, 1.6, 0.7, m_volume("dust haze", 0.025, 4.0)))
        vol.location = (-0.2, 0.0, 0.4)
        self.add(self._motes("M01_motes", 500, (1.5, 1.5, 0.6), (-0.2, 0.0, 0.42)))
        # the lamp: one hard key grazing at 8 degrees from frame left; it sweeps from the tablet's left edge to its
        # centre on `drift` before anything moves
        L = self.lamp(light("LAMP_M01", "SPOT", self.c, self.root, 1.0, size=0.02, spot_deg=26, blend=0.25), 1800)
        dist = 1.7
        L.location = (-dist, -0.25, 0.061 + dist * math.tan(math.radians(8)))
        targets = []
        for fr in FRAMES:
            p = sp(DRIFT, fr, 12)
            x = -0.32 + (0.0 - -0.32) * p
            targets.append(look(L.location, (x, 0.0, 0.07)).to_quaternion())
        L.rotation_mode = "QUATERNION"
        bake_vec(L, "rotation_quaternion", FRAMES, [list(q) for q in targets], 4)
        # camera: hold 1.0 s, then a rostrum crane up and back (2.8 m to 3.4 m), on toward the papyrus's station
        self.key(0, (-0.55, -1.95, 1.85), (0.16, 0.12, 0.02))
        self.key(24, (-0.55, -1.95, 1.85), (0.16, 0.12, 0.02))
        self.key(84, (-0.40, -1.75, 2.75), (0.20, 0.55, 0.0))
        self.next_anchor = anchor((0.15, 1.65, -0.02))
        self.motes_drift()

    def _tablet(self, sx, sy, sz, mats):
        bm = bmesh.new()
        uv = bm.loops.layers.uv.new("UVMap")
        x, y, z = sx / 2, sy / 2, sz / 2
        V = {k: bm.verts.new(v) for k, v in {
            "a": (-x, -y, z), "b": (x, -y, z), "c": (x, y, z), "d": (-x, y, z),
            "e": (-x, -y, -z), "f": (x, -y, -z), "g": (x, y, -z), "h": (-x, y, -z)}.items()}
        faces = [("adcb"[::-1], 0), ("efgh"[::-1], 1), ("dhgc"[::-1], 2), ("abfe"[::-1], 3), ("aehd"[::-1], 4), ("bcgf"[::-1], 5)]
        quads = {0: "abcd", 1: "hgfe", 2: "cdhg", 3: "abfe", 4: "daeh", 5: "bcgf"}
        uvq = [(0, 0), (1, 0), (1, 1), (0, 1)]
        for mi, q in quads.items():
            fc = bm.faces.new([V[ch] for ch in q])
            fc.material_index = mi
            for loop, u in zip(fc.loops, uvq):
                loop[uv].uv = u
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        ob = mesh_obj("M01_tablet", bm, mats)
        bevel(ob, 0.009, 3)
        return ob

    def _motes(self, name, n, size, centre):
        rng = random.Random(1)
        bm = bmesh.new()
        for _ in range(n):
            bm.verts.new(((rng.random() - 0.5) * size[0], (rng.random() - 0.5) * size[1], (rng.random() - 0.5) * size[2]))
        ob = mesh_obj(name, bm)
        ob.location = centre
        gn_points_to_spheres(ob, 0.0009, m_plain("mote", (0.8, 0.78, 0.74), rough=0.9))
        self._mote_ob = ob
        return ob

    def motes_drift(self):
        ob = self._mote_ob
        base = Vector(ob.location)
        bake_vec(ob, "location", FRAMES, [base + Vector((0.004 * fr / FPS, 0.0, 0.006 * fr / FPS)) for fr in FRAMES])


def gn_points_to_spheres(ob, radius, mat):
    """Geometry Nodes: every vertex becomes a tiny sphere (procedural dust)."""
    ng = bpy.data.node_groups.new(f"{ob.name}_gn", "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    gi, go = ng.nodes.new("NodeGroupInput"), ng.nodes.new("NodeGroupOutput")
    ico = ng.nodes.new("GeometryNodeMeshIcoSphere")
    ico.inputs["Radius"].default_value = radius
    ico.inputs["Subdivisions"].default_value = 1
    inst = ng.nodes.new("GeometryNodeInstanceOnPoints")
    sm = ng.nodes.new("GeometryNodeSetMaterial")
    sm.inputs["Material"].default_value = mat
    ng.links.new(gi.outputs[0], inst.inputs["Points"])
    ng.links.new(ico.outputs["Mesh"], inst.inputs["Instance"])
    ng.links.new(inst.outputs[0], sm.inputs[0])
    ng.links.new(sm.outputs[0], go.inputs[0])
    mod = ob.modifiers.new("dust", "NODES")
    mod.node_group = ng


# --- 2. Atlas ------------------------------------------------------------------------------------


class Atlas(Module):
    def build(self):
        table = self.add(box("M02_table", 3.4, 2.1, 0.05, m_wood("table", dark=True)))
        table.location = (0.05, 0.4, -0.025)
        # the Turin papyrus, 2.4 m of its first part, its painted hills raised a few millimetres from H-02
        pap = self.add(grid("M02_papyrus", 2.4, 2.4 * 2712 / 15000, 480, 87, m_image("T-02a papyrus", "T-02a_keyed", alpha=True, rough=0.8)))
        pap.location.z = 0.001
        self.relief(pap, "H-02", 0.004)
        # the Catalan Atlas: four map leaves on boards (0.48 x 0.65 m), folded like a screen, opened on `trace`
        bw, bh, th = 0.48, 0.65, 0.012
        y0 = 0.80
        wood = m_wood("board edge")
        parent = self.root
        x_hinge = 0.85
        self.hinges = []
        for k in (3, 2, 1, 0):                                 # east to west: they unfold toward the camera's track
            h = bpy.data.objects.new(f"M02_hinge{k}", None)
            self.add(h, parent)
            h.location = (x_hinge, y0, th) if parent is self.root else (-bw, 0.0, th / 2)
            board = self.add(box(f"M02_board{k}", bw, bh, th, [m_image(f"T-03 board {k}", f"T-03_board{k}", rough=0.6, sheen=0.3), wood],
                                 origin=(bw / 2, 0, 0)), h)       # local x spans [-bw, 0]: the hinge is its east edge
            board.location = (0.0, 0.0, -th / 2)
            self._uv_top(board)
            parent = board
            self.hinges.append((k, h))
        # hinge angles: folded 180 degrees; each opens on `trace` (37 frames), landing on 177, 185, 193, 201
        for i, (k, h) in enumerate(self.hinges):
            f0 = 140 + 8 * i
            open_angle = math.radians(-5.0 if i % 2 else 5.0)   # world angles 5, 0, 5, 0: a screen's zigzag, never into the table
            vals = [math.pi + (open_angle - math.pi) * sp(TRACE, fr, f0) for fr in FRAMES]
            bake(h, "rotation_euler", FRAMES, vals, 1)
        L = self.lamp(light("LAMP_M02", "AREA", self.c, self.root, 1.0, size=0.6), 420)
        aim(L, (1.7, 1.9, 1.9), (-0.2, 0.6, 0.0))
        # camera: station over the papyrus, a pass along it, tilt to 50 degrees and track left along the boards,
        # then past the western margin and over the board's wooden edge
        self.key(0, *STATION)
        self.key(29, (-0.35, 0.02, 1.2), (-0.35, 0.02, 0.0), (0, 1, 0))
        self.key(62, (-0.20, -0.05, 0.95), (-0.30, 0.82, 0.04))
        self.key(100, (-0.80, 0.00, 0.92), (-0.85, 0.82, 0.04))
        self.key(128, (-1.35, 0.30, 0.95), (-1.85, 0.80, -0.30))
        self.next_anchor = anchor((-2.05, 0.80, -0.40))

    def _uv_top(self, board):
        """Map the board's top face to its leaf (the box's UVs are reset to planar from above)."""
        me = board.data
        uvl = me.uv_layers[0].data
        xs = [v.co.x for v in me.vertices]
        ys = [v.co.y for v in me.vertices]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        for poly in me.polygons:
            top = poly.normal.z > 0.9
            poly.material_index = 0 if top else 1
            for li in poly.loop_indices:
                v = me.vertices[me.loops[li].vertex_index].co
                uvl[li].uv = ((v.x - x0) / (x1 - x0), (v.y - y0) / (y1 - y0))

    def relief(self, ob, hname, strength):
        t = bpy.data.textures.new(hname, "IMAGE")
        t.image = tex(hname, noncolor=True)
        t.extension = "EXTEND"
        m = ob.modifiers.new("relief", "DISPLACE")
        m.texture, m.texture_coords, m.strength, m.mid_level = t, "UV", strength, 0.0
        return m


# --- 3. Khipu ------------------------------------------------------------------------------------


class Khipu(Module):
    def build(self):
        piri = self.add(grid("M03_piri", 0.65, 0.65 * 2619 / 1964, 1, 1, m_image("T-04 Piri Reis", "T-04_keyed", alpha=True, rough=0.75)))
        piri.location.z = 0.0
        drum = self.add(bevel(cylinder("M03_drum", 0.14, 0.08, 96, m_wood("drum", dark=True)), 0.004))
        drum.location = (0.0, 0.10, 0.78)
        q25, q50, q75 = MAN["T-05_palette"]["values"]
        cotton = [m_plain(f"cotton {i}", tuple(c / 255 for c in q), rough=0.95, spec=0.2) for i, q in enumerate((q25, q50, q75))]
        # two-ply profile: two circles, twisted along each cord by the curve's tilt
        prof = bpy.data.curves.new("ply", "CURVE")
        for dx in (-0.0009, 0.0009):
            s = prof.splines.new("POLY")
            s.points.add(11)
            for i in range(12):
                a = 2 * math.pi * i / 12
                s.points[i].co = (dx + 0.001 * math.cos(a), 0.001 * math.sin(a), 0, 1)
            s.use_cyclic_u = True
        ply = bpy.data.objects.new("M03_ply_profile", prof)
        self.add(ply)
        ply.hide_render = True
        ply.hide_viewport = True
        primary = []
        for i in range(97):
            a = 2 * math.pi * i / 96
            primary.append((0.142 * math.cos(a), 0.142 * math.sin(a), -0.02))
        self.add(curve_obj("M03_primary", primary, 0.003, cotton[0]), drum)
        # pendants: plain cords, no knots. Knots are records; until khipu-knots.csv is measured off T-05 per cord,
        # the cords stay blank rather than carry invented knots.
        rng = random.Random(1940469)
        self.pendants = []
        n = 64
        for i in range(n):
            a = 2 * math.pi * (i + 0.5) / n
            L = 0.26 + 0.18 * rng.random()
            top = Vector((0.142 * math.cos(a), 0.142 * math.sin(a), -0.02))
            pts, tilt = [], []
            m = 40
            for j in range(m + 1):
                s = j / m
                pts.append((top.x * (1 + 0.15 * s), top.y * (1 + 0.15 * s), top.z - L * s))
                tilt.append(s * L / 0.008 * 2 * math.pi)
            cord = self.add(curve_obj(f"M03_pendant{i:02d}", pts, 0.0012, cotton[i % 3], tilt, bevel_obj=ply), drum)
            self.pendants.append((cord, top, rng.random() * 6.28))
        # motion: the drum turns at constant speed; each pendant swings a little with the turn (no simulation)
        w = math.radians(12.0) / FPS
        bake(drum, "rotation_euler", FRAMES, [w * fr for fr in FRAMES], 2)
        for cord, top, ph in self.pendants:
            cord.location = (0, 0, 0)
            sw = [math.radians(2.2) * math.sin(2 * math.pi * fr / 46 + ph) for fr in FRAMES]
            cord.rotation_mode = "XYZ"
            bake(cord, "rotation_euler", FRAMES, sw, 0)
        L = self.lamp(light("LAMP_M03", "AREA", self.c, self.root, 1.0, size=0.5), 160)
        aim(L, (0.0, 0.85, 1.35), (0.0, 0.0, 0.55))        # backlight from above and behind: rim-lit cotton
        fill = self.lamp(light("LAMP_M03_sheet", "SPOT", self.c, self.root, 1.0, size=0.05, spot_deg=50), 90)
        aim(fill, (0.6, -0.4, 1.4), (0.0, 0.0, 0.0))
        self.key(0, *STATION)
        self.key(34, (0.05, -0.70, 0.62), (0.0, 0.10, 0.55))
        self.key(84, (0.04, -0.40, 0.66), (0.02, 0.06, 0.52))
        self.key(110, (0.02, -0.30, 0.60), (0.0, -0.12, 0.36))
        self.next_anchor = anchor((0.0, -0.40, -1.20))
        self.ov_out = 0


# --- 4. Press ------------------------------------------------------------------------------------


class Press(Module):
    ov_in = 0

    def build(self):
        wood = m_wood("press timber")
        for sx in (-0.45, 0.45):                             # cheeks, after Jost Amman 1568 (T-07, measured, never shown)
            ch = self.add(bevel(box(f"M04_cheek{sx:+.0f}", 0.12, 0.15, 2.0, wood), 0.006))
            ch.location = (sx, 0.0, 1.0)
        head = self.add(bevel(box("M04_head", 1.02, 0.18, 0.16, wood), 0.006))
        head.location = (0.0, 0.0, 1.82)
        winter = self.add(bevel(box("M04_winter", 1.02, 0.16, 0.10, wood), 0.006))
        winter.location = (0.0, 0.0, 0.70)
        bed = self.add(bevel(box("M04_bed", 0.62, 0.86, 0.05, wood), 0.004))
        bed.location = (0.0, -0.16, 0.775)                  # the carriage runs out under the platen
        leaf = self.add(grid("M04_leaf", 0.29, 0.29 * 9616 / 6843, 1, 1, m_image("T-06 Genesis", "T-06_leaf", rough=0.7, sheen=0.3)))
        leaf.location = (0.0, -0.225, 0.8015)                # its top line just in front of the platen, as in the style frame
        # the screw: a helix swept with a triangular thread, pitch matched to the khipu's ply direction
        screw = self.add(self._screw(0.04, 0.70, 0.045), None)
        screw.location = (0.0, 0.0, 1.43)
        platen_m = m_fade(m_wood("platen"))
        platen = self.add(bevel(box("M04_platen", 0.50, 0.20, 0.05, platen_m), 0.004))
        platen.location.y = 0.08                             # over the far half of the forme: the near half of the leaf stays in view
        bar = self.add(box("M04_bar", 0.55, 0.025, 0.025, m_iron(), origin=(-0.275, 0, 0)), screw)
        bar.location = (0.0, 0.0, 0.0)
        # the stamp: the platen lands on `stamp` at frame 432 and the bar pulls with it; after contact the platen and
        # its shadow fade (a departure is a fade, never a move)
        n_st = sp_frames(STAMP)
        f0 = 432 - n_st
        up_z, down_z = 1.02, 0.827
        z = [up_z + (down_z - up_z) * sp(STAMP, fr, f0) for fr in FRAMES]
        bake(platen, "location", FRAMES, z, 2)
        bake(screw, "location", FRAMES, [0.08] * len(FRAMES), 1)
        bake(screw, "rotation_euler", FRAMES, [math.radians(55) * sp(STAMP, fr, f0) for fr in FRAMES], 2)
        bake(screw, "location", FRAMES, [1.43 + (z_ - up_z) for z_ in z], 2)
        bake_node(platen_m, "fade", FRAMES, [1.0 - clamp01((fr - 440) / 18) for fr in FRAMES])
        L = self.lamp(light("LAMP_M04", "SPOT", self.c, self.root, 1.0, size=0.04, spot_deg=55), 900)
        aim(L, (1.15, -0.35, 1.30), (0.0, 0.05, 0.80))
        # camera: down the screw, then low across the leaf toward the platen; up and over to Ino's sheet
        self.key(0, (0.0, -0.30, 1.75), (0.0, 0.0, 1.45))
        self.key(38, (0.0, -0.85, 1.28), (0.0, 0.0, 0.95))
        self.key(48, (0.0, -0.80, 1.03), (0.0, -0.14, 0.85))
        self.key(66, (0.02, -0.70, 0.98), (0.0, -0.14, 0.82))
        self.key(92, (0.0, -0.40, 2.30), (0.0, 0.70, 1.30))
        self.next_anchor = anchor((0.0, 1.70, 0.80))

    def _screw(self, r, length, pitch):
        bm = bmesh.new()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=48, radius1=r * 0.82, radius2=r * 0.82, depth=length)
        core = mesh_obj("M04_screw", bm, m_wood("screw"))
        turns = length / pitch
        pts, n = [], int(turns * 48)
        for i in range(n + 1):
            a = 2 * math.pi * i / 48
            pts.append((r * 0.86 * math.cos(a), r * 0.86 * math.sin(a), -length / 2 + pitch * i / 48))
        thread = curve_obj("M04_thread", pts, 0.0, core.data.materials[0])
        prof = bpy.data.curves.new("thread_profile", "CURVE")
        s = prof.splines.new("POLY")
        s.points.add(2)
        for i, (x, y) in enumerate(((0, -0.008), (0.012, 0.0), (0, 0.008))):
            s.points[i].co = (x, y, 0, 1)
        s.use_cyclic_u = True
        po = bpy.data.objects.new("M04_thread_profile", prof)
        self.add(po)
        po.hide_render = po.hide_viewport = True
        thread.data.bevel_mode = "OBJECT"
        thread.data.bevel_object = po
        self.add(thread, core)
        return core


# --- 5. Survey -----------------------------------------------------------------------------------


class Survey(Module):
    W, H = 2.0, 2.0 * 5739 / 9918

    def build(self):
        sheet = self.add(grid("M05_ino", self.W, self.H, 600, 347, m_image("T-08 Ino", "T-08_sheet", rough=0.55, sheen=0.4)))
        Atlas.relief(self, sheet, "H-08", 0.006)
        under = self.add(box("M05_board", self.W + 0.1, self.H + 0.1, 0.03, m_wood("survey table", dark=True)))
        under.location.z = -0.016
        pts = [Vector(((u - 0.5) * self.W, (0.5 - v) * self.H, 0.0025)) for u, v in MAN["T-08_redline"]["points"]]
        if pts[0].x > pts[-1].x:
            pts.reverse()                                   # walk west to east
        cum = [0.0]
        for a, b in zip(pts, pts[1:]):
            cum.append(cum[-1] + (b - a).length)
        total = cum[-1]

        def at(d):
            d = max(0.0, min(total, d))
            for i in range(1, len(cum)):
                if cum[i] >= d:
                    t = (d - cum[i - 1]) / max(cum[i] - cum[i - 1], 1e-9)
                    return pts[i - 1].lerp(pts[i], t)
            return pts[-1]
        # the glint: the lamp's target travels along the printed red line on `trace`, never off it
        a_d, b_d = 0.10 * total, 0.85 * total
        f0 = self.f(16)
        glint_pos = [at(a_d + (b_d - a_d) * min(1.0, sp(TRACE, fr, f0))) for fr in FRAMES]
        g = self.lamp(light("LAMP_M05_glint", "SPOT", self.c, self.root, 1.0, size=0.002, spot_deg=1.1, blend=0.8), 45)
        g.rotation_mode = "QUATERNION"
        locs, rots = [], []
        for p in glint_pos:
            src = p + Vector((0.0, 0.55, 0.30))
            locs.append(src)
            rots.append(list(look(src, p).to_quaternion()))
        bake_vec(g, "location", FRAMES, locs)
        bake_vec(g, "rotation_quaternion", FRAMES, rots, 4)
        L = self.lamp(light("LAMP_M05", "AREA", self.c, self.root, 1.0, size=1.2), 380)
        aim(L, (0.3, 1.9, 0.55), (0.0, 0.0, 0.0))            # low and raking from beyond the sheet
        # the wire continues the line off the sheet's edge, to the key
        end = at(b_d)
        edge = Vector((self.W / 2 + 0.02, end.y, 0.004))
        nxt = Vector((self.W / 2 + 0.95, end.y, -0.10))
        wire = [edge.lerp(nxt, s / 20) + Vector((0, 0, -0.04 * math.sin(math.pi * s / 20))) for s in range(0, 21)]
        self.add(curve_obj("M05_wire", [tuple(p) for p in wire], 0.0012, m_iron()))
        # camera: low and fast along the glint (the sequence's highest cruise), then off the edge along the wire
        s0, s1 = at(a_d), at(b_d)
        dirv = (s1 - s0).normalized()
        side = Vector((-dirv.y, dirv.x, 0))
        self.key(0, *STATION)
        self.key(20, tuple(s0 - dirv * 0.40 - side * 0.12 + Vector((0, 0, 0.26))), tuple(s0 + dirv * 0.25))
        mid = at((a_d + b_d) / 2)
        self.key(40, tuple(mid - dirv * 0.40 - side * 0.12 + Vector((0, 0, 0.24))), tuple(mid + dirv * 0.25))
        self.key(62, tuple(s1 - dirv * 0.35 - side * 0.10 + Vector((0, 0, 0.22))), tuple(s1 + dirv * 0.25))
        self.key(95, tuple(edge + Vector((-0.30, -0.10, 0.18))), tuple(edge + Vector((0.4, 0.0, -0.05))))
        self.next_anchor = Matrix.Translation(nxt - Vector((-0.80, 0.0, 0.02)))


# --- 6. Wire -------------------------------------------------------------------------------------


class Wire(Module):
    def build(self):
        brass, iron, wood = m_brass(), m_iron(), m_wood("key base")
        base = self.add(bevel(box("M06_key_base", 0.17, 0.09, 0.02, wood), 0.003))
        base.location = (0.0, 0.0, 0.01)
        piv = bpy.data.objects.new("M06_key_pivot", None)
        self.add(piv)
        piv.location = (0.03, 0.0, 0.035)
        lever = self.add(box("M06_lever", 0.12, 0.012, 0.008, brass, origin=(0.06, 0, 0)), piv)
        knob = self.add(cylinder("M06_knob", 0.012, 0.012, 32, m_lacquer()), lever)
        knob.location = (-0.115, 0.0, 0.01)
        self.add(curve_obj("M06_wire_in", [(-0.80, 0.0, 0.02), (-0.4, 0.0, 0.0), (-0.08, 0.0, 0.02)], 0.0012, iron))
        # the key presses on `stamp` at frame 640 and holds
        f0 = 640 - sp_frames(STAMP)
        bake(piv, "rotation_euler", FRAMES, [math.radians(-5.0) * sp(STAMP, fr, f0) for fr in FRAMES], 1)
        # the register (NMAH 706500, measured): a plate, a train of two gears, the rollers and the stylus
        plate = self.add(bevel(box("M06_plate", 0.22, 0.012, 0.20, m_plain("register plate", (0.06, 0.05, 0.04), 0.4)), 0.003))
        plate.location = (0.40, 0.04, 0.12)
        big = self.add(gear("M06_gear72", 72, 0.066, 0.072, 0.006, brass))
        big.rotation_euler.x = math.radians(90)
        big.location = (0.36, 0.025, 0.12)
        small = self.add(gear("M06_gear24", 24, 0.020, 0.026, 0.006, brass))
        small.rotation_euler.x = math.radians(90)
        small.location = (0.36 + 0.093, 0.025, 0.12 + 0.03)
        r1 = self.add(cylinder("M06_roller1", 0.011, 0.06, 32, brass, axis="Y"))
        r1.location = (0.52, 0.0, 0.10)
        r2 = self.add(cylinder("M06_roller2", 0.011, 0.06, 32, brass, axis="Y"))
        r2.location = (0.52, 0.0, 0.078)
        # the train starts on `settle` after the stamp and runs at constant speed; the tape feeds at constant speed
        w = math.radians(30) / FPS
        ang, a = [], 0.0
        for fr in FRAMES:
            a += w * sp(SETTLE, fr, 640)
            ang.append(a)
        bake(big, "rotation_euler", FRAMES, ang, 1)
        bake(small, "rotation_euler", FRAMES, [-x * 3 for x in ang], 1)
        bake(r1, "rotation_euler", FRAMES, [x * 6 for x in ang], 1)
        bake(r2, "rotation_euler", FRAMES, [-x * 6 for x in ang], 1)
        # the tape: the real 1844 tape (T-09), a ribbon that runs out between the rollers and curls toward the camera.
        # Its embossing is the scan, not keyed by our key: no message of ours.
        tw = 0.035
        tl = tw * 20728 / 888
        tape_m = m_image("T-09 tape", "T-09_tape", rough=0.6, sheen=0.3)
        it = next(n for n in tape_m.node_tree.nodes if n.type == "TEX_IMAGE")
        mp = tape_m.node_tree.nodes.new("ShaderNodeMapping")
        mp.name = "feed"
        tc = tape_m.node_tree.nodes.new("ShaderNodeTexCoord")
        tape_m.node_tree.links.new(tc.outputs["UV"], mp.inputs[0])
        tape_m.node_tree.links.new(mp.outputs[0], it.inputs[0])
        vis = 0.50 / tl                                      # about 50 cm of tape visible: a window onto the strip
        mp.inputs["Scale"].default_value = (vis, 1.0, 1.0)
        self.add(ribbon("M06_tape", [(0.53, 0.0, 0.089), (0.62, 0.0, 0.085), (0.72, -0.03, 0.095), (0.82, -0.10, 0.13), (0.90, -0.20, 0.19)],
                        tw, tape_m, side=(0.0, 1.0, 0.0)))
        feed = 0.035 / tl / FPS                              # 3.5 cm a second, in UV units a frame
        off, x = [], 0.02
        for fr in FRAMES:
            x += feed * sp(SETTLE, fr, 640)
            off.append(x)
        bake(tape_m.node_tree, 'nodes["feed"].inputs[1].default_value', FRAMES, [-v for v in off], 0)
        L = self.lamp(light("LAMP_M06", "SPOT", self.c, self.root, 1.0, size=0.02, spot_deg=28, blend=0.5), 140)
        aim(L, (0.35, -0.45, 0.55), (0.45, 0.0, 0.09))      # a tight pin on the stylus and rollers
        self.key(0, (-0.55, -0.06, 0.13), (0.0, 0.0, 0.03))
        self.key(28, (-0.24, -0.16, 0.11), (0.03, 0.0, 0.03))
        self.key(52, (0.18, -0.48, 0.24), (0.45, 0.0, 0.11))
        self.key(78, (0.52, -0.62, 0.30), (0.78, -0.10, 0.13))
        self.next_anchor = anchor((1.40, 0.70, -0.80))


# --- 7. Count ------------------------------------------------------------------------------------


class Count(Module):
    ov_out = 0

    def build(self):
        brass, wood = m_brass(), m_wood("tabulator")
        bank = self.add(bevel(box("M07_bank", 1.56, 0.04, 0.80, wood), 0.006))
        bank.location = (0.0, 0.02, 1.28)
        face_m = self._dial_face()
        rng = random.Random(1890)
        self.dials = []
        for row in range(4):
            for col in range(10):
                c = Vector(((col - 4.5) * 0.145, -0.002, 1.04 + (3 - row) * 0.165))
                face = self.add(cylinder(f"M07_face{row}{col}", 0.055, 0.004, 64, face_m, axis="Y"))
                face.location = c
                bez = self.add(torus(f"M07_bezel{row}{col}", 0.057, 0.0045, 64, 10, brass))
                bez.rotation_euler.x = math.radians(90)
                bez.location = c
                hands = []
                for hi, (ln, wd) in enumerate(((0.045, 0.004), (0.030, 0.006))):
                    hp = bpy.data.objects.new(f"M07_hand{row}{col}_{hi}", None)
                    self.add(hp)
                    hp.location = c + Vector((0, -0.004 - 0.002 * hi, 0))
                    hand = self.add(box(f"M07_handbar{row}{col}_{hi}", wd, 0.0015, ln, m_lacquer(), origin=(0, 0, -ln / 2 + 0.006)), hp)
                    hp.rotation_euler.y = rng.random() * 2 * math.pi
                    hands.append(hp)
                self.dials.append((row, col, hands))
        # the press: a blank 1890 card (no punch: a punched pattern would be an invented return) and the pin box
        desk = self.add(bevel(box("M07_desk", 1.0, 0.6, 0.04, wood), 0.004))
        desk.location = (-0.1, -0.45, 0.80)
        card = self.add(self._card())
        card.location = (-0.30, -0.42, 0.8205)
        pinbox = self.add(bevel(box("M07_pinbox", 0.24, 0.13, 0.06, m_lacquer()), 0.003))
        f0 = 756 - sp_frames(STAMP)
        bake(pinbox, "location", FRAMES, [-0.30] * len(FRAMES), 0)
        bake(pinbox, "location", FRAMES, [-0.42] * len(FRAMES), 1)
        bake(pinbox, "location", FRAMES, [0.95 + (0.855 - 0.95) * sp(STAMP, fr, f0) for fr in FRAMES], 2)
        # the machine counts one: several dials advance one division on `settle` after the stamp; no figure is shown
        advance = set(rng.sample(range(40), 9))
        for i, (row, col, hands) in enumerate(self.dials):
            if i in advance:
                hp = hands[0]
                a0 = hp.rotation_euler.y
                bake(hp, "rotation_euler", FRAMES, [a0 + 2 * math.pi / 100 * sp(SETTLE, fr, 756) for fr in FRAMES], 1)
        L = self.lamp(light("LAMP_M07", "SPOT", self.c, self.root, 1.0, size=0.06, spot_deg=60), 1100)
        aim(L, (-1.1, -1.0, 2.1), (0.1, 0.0, 1.2))
        tgt = Vector(((6 - 4.5) * 0.145, -0.002, 1.04 + (3 - 1) * 0.165))
        self.key(0, (-0.10, -1.05, 1.02), (-0.20, -0.30, 0.86))
        self.key(30, (-0.30, -1.25, 1.30), (0.05, 0.0, 1.25))
        self.key(48, (-0.80, -0.82, 1.26), (0.25, 0.0, 1.27))
        self.key(76, tuple(tgt + Vector((-0.05, -0.42, 0.02))), tuple(tgt))
        self.key(95, tuple(tgt + Vector((0, -0.16, 0))), tuple(tgt))
        # the push into one dial rhymes with the spool's hub and spokes (matched centre and scale)
        self.next_anchor = self._spool_anchor(tgt)

    def _spool_anchor(self, dial_centre):
        # place the reel module so its spool centre sits behind the dial, at the distance that matches its size
        spool_c_local = Vector((-0.02, 0.0, 0.36))
        s = 0.10 / 0.055                                     # spool radius / dial radius
        cam = dial_centre + Vector((0, -0.16, 0))
        spool_world = cam + Vector((0, 0.16 * s, 0))
        return Matrix.Translation(spool_world - spool_c_local)

    def _dial_face(self):
        """Paper face with 100 graduations drawn by the studio from T-13 (CC BY 2.0); no figures."""
        mat = bpy.data.materials.new("dial face")
        nt, b, _ = _nodes(mat)
        tc = nt.nodes.new("ShaderNodeTexCoord")
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        nt.links.new(tc.outputs["Object"], sep.inputs[0])

        def M(op, a, bb=None, v=None):
            n = nt.nodes.new("ShaderNodeMath")
            n.operation = op
            for i, x in enumerate((a, bb)):
                if x is None:
                    continue
                if isinstance(x, (int, float)):
                    n.inputs[i].default_value = x
                else:
                    nt.links.new(x, n.inputs[i])
            return n.outputs[0]
        x, z = sep.outputs["X"], sep.outputs["Z"]
        r = M("SQRT", M("ADD", M("MULTIPLY", x, x), M("MULTIPLY", z, z)))
        ang = M("ARCTAN2", z, x)
        u = M("FRACT", M("MULTIPLY", M("ADD", M("DIVIDE", ang, 2 * math.pi), 1.0), 100.0))
        tick = M("LESS_THAN", M("ABSOLUTE", M("SUBTRACT", u, 0.5)), 0.13)
        band = M("MULTIPLY", M("GREATER_THAN", r, 0.044), M("LESS_THAN", r, 0.051))
        u10 = M("FRACT", M("MULTIPLY", M("ADD", M("DIVIDE", ang, 2 * math.pi), 1.0), 10.0))
        major = M("MULTIPLY", M("LESS_THAN", M("ABSOLUTE", M("SUBTRACT", u10, 0.5)), 0.018), M("MULTIPLY", M("GREATER_THAN", r, 0.040), M("LESS_THAN", r, 0.051)))
        ink = M("MAXIMUM", M("MULTIPLY", tick, band), major)
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.inputs["A"].default_value = (*lin((0.80, 0.72, 0.56)), 1)
        mix.inputs["B"].default_value = (*lin((0.06, 0.06, 0.06)), 1)
        nt.links.new(ink, mix.inputs["Factor"])
        nt.links.new(mix.outputs["Result"], b.inputs["Base Color"])
        b.inputs["Roughness"].default_value = 0.6
        return mat

    def _card(self):
        w, h, c = 0.168, 0.083, 0.012                       # 1890 card, 6 5/8 x 3 1/4 in, cut corner
        bm = bmesh.new()
        vs = [bm.verts.new(p) for p in ((-w / 2, -h / 2, 0), (w / 2, -h / 2, 0), (w / 2, h / 2, 0), (-w / 2 + c, h / 2, 0), (-w / 2, h / 2 - c, 0))]
        bm.faces.new(vs)
        bm.loops.layers.uv.new("UVMap")
        return mesh_obj("M07_card", bm, m_plain("manila", (0.62, 0.50, 0.33), 0.8))


# --- 8. Reel -------------------------------------------------------------------------------------


class Reel(Module):
    ov_in = 0

    def build(self):
        wood, brass = m_wood("cinematographe"), m_brass()
        bx = self.add(bevel(box("M08_box", 0.30, 0.18, 0.25, wood), 0.005))
        bx.location = (0.0, 0.0, 0.125)
        spool = self.add(self._spool(brass))
        spool.location = (-0.02, 0.0, 0.36)
        post = self.add(box("M08_post", 0.02, 0.02, 0.06, m_lacquer()))
        post.location = (-0.02, 0.0, 0.26)
        lens = self.add(cylinder("M08_lens", 0.032, 0.06, 48, brass, axis="X"))
        lens.location = (0.18, 0.0, 0.13)
        glass = self.add(cylinder("M08_glass", 0.026, 0.002, 48, m_plain("lens glass", (0.9, 0.9, 0.88), 0.05), axis="X"))
        glass.location = (0.211, 0.0, 0.13)
        # the strip: Promio's frames in order, one round perforation each side of each frame (Lumiere), advancing
        # intermittently through the gate at 16 a second, as the claw did
        strip_m = self._strip_material()
        strip = self.add(grid("M08_strip", 0.035, 0.34, 1, 1, strip_m))
        strip.rotation_euler.x = math.radians(90)
        strip.location = (-0.175, -0.02, 0.20)
        pitch = 0.019
        offs = []
        for fr in FRAMES:
            t = 16.0 * fr / FPS
            n, frac = math.floor(t), t - math.floor(t)
            offs.append(n + smoothstep(min(1.0, frac / 0.25)))
        bake(strip_m.node_tree, 'nodes["advance"].outputs[0].default_value', FRAMES, offs)
        bake(spool, "rotation_euler", FRAMES, [math.radians(40) * fr / FPS for fr in FRAMES], 1)
        # the beam is the lamp: outside the box as the Lumieres' lantern was, through the gate, into haze
        beam = self.lamp(light("LAMP_M08_beam", "SPOT", self.c, self.root, 1.0, size=0.01, spot_deg=30, blend=0.5), 420)
        aim(beam, (0.215, 0.0, 0.13), (2.0, 0.0, 0.13))
        haze = self.add(box("M08_haze", 2.2, 1.0, 0.8, m_volume("beam haze", 0.05, 2.5)))
        haze.location = (1.3, 0.0, 0.15)
        motes = Clay._motes(self, "M08_motes", 700, (2.0, 0.8, 0.6), (1.2, 0.0, 0.15))
        self.add(motes)
        Clay.motes_drift(self)
        leak = self.lamp(light("LAMP_M08_leak", "POINT", self.c, self.root, 1.0, size=0.03), 55)
        leak.location = (0.12, -0.24, 0.30)                  # the gate's leak, the only light on the box and spool
        self.key(0, (-0.02, -0.29, 0.36), (-0.02, 0.0, 0.36))
        self.key(22, (-0.24, -0.34, 0.27), (-0.17, 0.0, 0.22))
        self.key(42, (0.12, -1.42, 0.32), (0.19, 0.0, 0.20))
        self.key(56, (0.20, -1.36, 0.31), (0.26, 0.0, 0.20))
        self.key(78, (0.06, -0.24, 0.17), (1.20, 0.0, 0.14))
        self.next_anchor = anchor((1.30, -0.10, -0.30))
        self.ov_out = 0

    def _spool(self, brass):
        rim = torus("M08_spool", 0.095, 0.006, 64, 10, brass)
        rim.rotation_euler.x = math.radians(90)
        hub = cylinder("M08_hub", 0.014, 0.02, 32, brass)     # along the torus's own axis
        link(hub, self.c, rim)
        for k in range(5):
            a = 2 * math.pi * k / 5
            sp_ = box(f"M08_spoke{k}", 0.09, 0.006, 0.006, brass, origin=(-0.045, 0, 0))
            link(sp_, self.c, rim)
            sp_.rotation_euler = (0, 0, a)
        return rim

    def _strip_material(self):
        mat = bpy.data.materials.new("Promio strip")
        nt, b, _ = _nodes(mat)
        mat.surface_render_method = "DITHERED"
        mat.use_transparent_shadow = True
        tc = nt.nodes.new("ShaderNodeTexCoord")
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        nt.links.new(tc.outputs["UV"], sep.inputs[0])
        adv = nt.nodes.new("ShaderNodeValue")
        adv.name = "advance"

        def M(op, a, bb=None):
            n = nt.nodes.new("ShaderNodeMath")
            n.operation = op
            for i, x in enumerate((a, bb)):
                if x is None:
                    continue
                if isinstance(x, (int, float)):
                    n.inputs[i].default_value = x
                else:
                    nt.links.new(x, n.inputs[i])
            return n.outputs[0]
        u, v = sep.outputs["X"], sep.outputs["Y"]
        cells = 0.34 / 0.019                                 # frames visible on the strip
        pos = M("ADD", M("MULTIPLY", M("SUBTRACT", 1.0, v), cells), adv.outputs[0])
        idx = M("FLOOR", pos)
        fy = M("FRACT", pos)
        idx = M("SUBTRACT", idx, M("MULTIPLY", M("FLOOR", M("DIVIDE", idx, 96.0)), 96.0))
        col = M("SUBTRACT", idx, M("MULTIPLY", M("FLOOR", M("DIVIDE", idx, 4.0)), 4.0))
        row = M("FLOOR", M("DIVIDE", idx, 4.0))
        fx = M("DIVIDE", M("SUBTRACT", u, 0.14), 0.72)       # the image between the perforations
        fyy = M("DIVIDE", M("SUBTRACT", fy, 0.06), 0.88)
        au = M("DIVIDE", M("ADD", col, M("MINIMUM", M("MAXIMUM", fx, 0.0), 1.0)), 4.0)
        av = M("SUBTRACT", 1.0, M("DIVIDE", M("ADD", row, M("MINIMUM", M("MAXIMUM", fyy, 0.0), 1.0)), 24.0))
        comb = nt.nodes.new("ShaderNodeCombineXYZ")
        nt.links.new(au, comb.inputs[0])
        nt.links.new(av, comb.inputs[1])
        it = nt.nodes.new("ShaderNodeTexImage")
        it.image = tex("T-16_atlas")
        it.interpolation = "Linear"
        nt.links.new(comb.outputs[0], it.inputs[0])
        inside = M("MULTIPLY", M("MULTIPLY", M("GREATER_THAN", fx, 0.0), M("LESS_THAN", fx, 1.0)),
                   M("MULTIPLY", M("GREATER_THAN", fyy, 0.0), M("LESS_THAN", fyy, 1.0)))
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.inputs["A"].default_value = (0.012, 0.010, 0.009, 1)
        nt.links.new(inside, mix.inputs["Factor"])
        nt.links.new(it.outputs["Color"], mix.inputs["B"])
        nt.links.new(mix.outputs["Result"], b.inputs["Base Color"])
        # one round perforation on each side of each frame (u 0.07 and 0.93), radius 0.035 of the width
        dyp = M("MULTIPLY", M("SUBTRACT", fy, 0.5), 0.019 / 0.035)
        hole = None
        for cx in (0.07, 0.93):
            dx = M("SUBTRACT", u, cx)
            d = M("SQRT", M("ADD", M("MULTIPLY", dx, dx), M("MULTIPLY", dyp, dyp)))
            h = M("LESS_THAN", d, 0.035)
            hole = h if hole is None else M("MAXIMUM", hole, h)
        nt.links.new(M("SUBTRACT", 1.0, hole), b.inputs["Alpha"])
        b.inputs["Roughness"].default_value = 0.3
        return mat


# --- 9. Type -------------------------------------------------------------------------------------


class Type(Module):
    ov_in = 0

    def build(self):
        iron = m_plain("typebar steel", (0.42, 0.42, 0.42), rough=0.3, metal=1.0)
        platen = self.add(cylinder("M09_platen", 0.028, 0.42, 64, m_plain("platen rubber", (0.015, 0.015, 0.015), 0.5), axis="X"))
        platen.location = (0.0, 0.03, -0.028)
        # 42 typebars on a semicircular segment (Underwood No. 5, T-17, measured)
        C, R = Vector((0.0, -0.10, -0.075)), 0.115
        self.bars = []
        for k in range(42):
            a = math.radians(12 + 156 * k / 41)
            pivot = C + Vector((R * math.cos(a), -R * math.sin(a) * 0.55, -R * math.sin(a) * 0.35))
            hp = bpy.data.objects.new(f"M09_bar_pivot{k:02d}", None)
            self.add(hp)
            hp.location = pivot
            rest = (C + Vector((0, 0.02, 0.0)) - pivot)
            hp.matrix_basis = Matrix.Translation(pivot) @ rest.to_track_quat("Z", "Y").to_matrix().to_4x4()
            bar = self.add(box(f"M09_bar{k:02d}", 0.003, 0.0035, rest.length * 0.92, iron, origin=(0, 0, -rest.length * 0.46)), hp)
            slug = self.add(box(f"M09_slug{k:02d}", 0.006, 0.006, 0.008, iron), bar)
            slug.location = (0, 0, rest.length * 0.92)
            self.bars.append((hp, pivot, rest))
        # the striking bar rises out of the fan on `stamp` (frame 948) and falls back at once
        hp, pivot, rest = self.bars[20]
        strike = (Vector((0.0, 0.0, 0.0)) - pivot)
        axis = rest.cross(strike).normalized()
        ang = rest.angle(strike)
        f0 = 948 - sp_frames(STAMP)
        base = hp.matrix_basis.copy()
        mats = []
        for fr in FRAMES:
            p = sp(STAMP, fr, f0) if fr <= 950 else max(0.0, 1.0 - (fr - 950) / 3.0)
            mats.append(Matrix.Translation(pivot) @ Matrix.Rotation(ang * p, 4, axis) @ Matrix.Translation(-pivot) @ base)
        hp.rotation_mode = "QUATERNION"
        bake_vec(hp, "location", FRAMES, [m.to_translation() for m in mats])
        bake_vec(hp, "rotation_quaternion", FRAMES, [list(m.to_quaternion()) for m in mats], 4)
        # the page: the real typed page (T-18), revealed one character at a time along its own lines
        info = MAN["T-18_lines"]
        Wpx, Hpx = info["size"]
        lines = info["lines"]
        mid = range(len(lines) // 3, 2 * len(lines) // 3)
        Lc = max(mid, key=lambda i: lines[i][3] - lines[i][2])   # the longest line in the page's middle third
        pw = 0.216
        ph = pw * Hpx / Wpx
        y0, y1, x0, x1 = lines[Lc]
        v_cut = 1.0 - (y1 + 4) / Hpx                         # the page above the print line; below it wraps the platen
        page_m = self._page_material()
        page = self.add(grid("M09_page", pw, ph * (1 - v_cut), 1, 8, page_m))
        for loop_uv in page.data.uv_layers[0].data:
            loop_uv.uv.y = v_cut + loop_uv.uv.y * (1 - v_cut)
        page.rotation_euler.x = math.radians(90 - 12)
        k0 = int(math.ceil((x1 - x0 + 1) / info["pitch_px"]) * 0.45)   # the beat joins the line nearly halfway along
        cx = (x0 + (k0 + 0.5) * info["pitch_px"]) / Wpx     # the next character to be typed sits at the print point
        page_x = [(0.5 - cx) * pw - (0.0 if fr < 948 else info["pitch_px"] / Wpx * pw * sp(STAMP, fr, 946)) for fr in FRAMES]
        bake(page, "location", FRAMES, page_x, 0)
        page.location.y = 0.03 - 0.028 * math.sin(math.radians(12))
        page.location.z = (ph * (1 - v_cut)) / 2 * math.cos(math.radians(12)) + 0.002
        n_before = 0
        for (a, b, c, d) in lines[:Lc]:
            n_before += int(math.ceil((d - c + 1) / info["pitch_px"]))
        n_line = int(math.ceil((x1 - x0 + 1) / info["pitch_px"]))
        reveal = [(n_before + min(n_line, k0 + max(0, (fr - 900) / FPS * 4.5))) / info["chars"] for fr in FRAMES]
        bake_node(page_m, "reveal", FRAMES, reveal)
        L = self.lamp(light("LAMP_M09", "SPOT", self.c, self.root, 1.0, size=0.03, spot_deg=50), 220)
        aim(L, (0.55, -0.35, 0.10), (0.0, -0.02, 0.0))       # a low side key from frame right
        self.key(0, (0.0, -0.60, 0.05), (0.0, -0.02, -0.03))
        self.key(48, (0.0, -0.50, 0.04), (0.0, -0.02, -0.025))
        self.key(78, (0.0, -0.28, 0.20), (0.0, 0.02, 0.10))
        self.next_anchor = anchor((0.0, 0.9, -0.30))

    def _page_material(self):
        mat = bpy.data.materials.new("T-18 typed page")
        nt, b, _ = _nodes(mat)
        tc = nt.nodes.new("ShaderNodeTexCoord")
        ink = nt.nodes.new("ShaderNodeTexImage")
        ink.image = tex("T-18_page")
        paper = nt.nodes.new("ShaderNodeTexImage")
        paper.image = tex("T-18_paper")
        order = nt.nodes.new("ShaderNodeTexImage")
        order.image = tex("M-18_order", noncolor=True)
        order.interpolation = "Closest"
        for n in (ink, paper, order):
            nt.links.new(tc.outputs["UV"], n.inputs[0])
        rv = nt.nodes.new("ShaderNodeValue")
        rv.name = "reveal"
        gt0 = nt.nodes.new("ShaderNodeMath")
        gt0.operation = "GREATER_THAN"
        gt0.inputs[1].default_value = 0.0
        nt.links.new(order.outputs["Color"], gt0.inputs[0])
        le = nt.nodes.new("ShaderNodeMath")
        le.operation = "LESS_THAN"
        nt.links.new(order.outputs["Color"], le.inputs[0])
        nt.links.new(rv.outputs[0], le.inputs[1])
        hid = nt.nodes.new("ShaderNodeMath")
        hid.operation = "MULTIPLY"
        nt.links.new(gt0.outputs[0], hid.inputs[0])
        inv = nt.nodes.new("ShaderNodeMath")
        inv.operation = "SUBTRACT"
        inv.inputs[0].default_value = 1.0
        nt.links.new(le.outputs[0], inv.inputs[1])
        nt.links.new(inv.outputs[0], hid.inputs[1])
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        nt.links.new(hid.outputs[0], mix.inputs["Factor"])
        nt.links.new(ink.outputs["Color"], mix.inputs["A"])
        nt.links.new(paper.outputs["Color"], mix.inputs["B"])
        nt.links.new(mix.outputs["Result"], b.inputs["Base Color"])
        b.inputs["Roughness"].default_value = 0.75
        b.inputs["Sheen Weight"].default_value = 0.3
        return mat


# --- 10. Swell -----------------------------------------------------------------------------------


class Swell(Module):
    def build(self):
        table = self.add(box("M10_table", 1.6, 1.2, 0.04, m_wood("chart table", dark=True)))
        table.location.z = -0.021
        chart = self.add(grid("M10_chart", 1.0, 1.0 * 10955 / 16232, 1, 1, m_image("T-20 Admiralty 983", "T-20_chart", rough=0.6, sheen=0.3)))
        chart.location.z = 0.0005
        # the rebbelib (T-19), its sticks as photographed, rising above the chart on `arrive` and holding
        w = 0.62
        reb_m = m_image("T-19 rebbelib", "T-19_keyed", alpha=True, rough=0.7, sheen=0.0)
        reb = self.add(grid("M10_rebbelib", w, w * 10176 / 10966, 1, 1, reb_m))
        sol = reb.modifiers.new("thickness", "SOLIDIFY")
        sol.thickness = 0.006
        reb.location = (0.08, 0.02, 0.0)
        f0 = self.f(22)
        bake(reb, "location", FRAMES, [0.012 + 0.13 * sp(ARRIVE, fr, f0) for fr in FRAMES], 2)
        # a hard lamp high at top left, so the sticks' shadow is sharp on the printed atolls; its pool lets go at the end
        L = self.lamp(light("LAMP_M10", "SPOT", self.c, self.root, 1.0, size=0.004, spot_deg=60, blend=0.5), 560)
        aim(L, (-0.75, 0.70, 1.55), (0.05, -0.05, 0.0))
        self.key(0, *STATION)
        self.key(48, (0.10, -0.78, 1.02), (0.05, 0.02, 0.0))
        self.key(96, (0.12, -0.95, 1.38), (0.05, 0.10, 0.05))
        self.next_anchor = Matrix.Translation(Vector((0.0, 0.25, 1.90)))
        self.fade_last = 14


# --- 11. Record (swappable per film) -------------------------------------------------------------


class Record(Module):
    ov_out = 0

    def build(self):
        rec = CFG["records"][ARGS["record"]]
        w_px, h_px = MAN[rec["tex"]]["tex"]["size"]
        aspect = w_px / h_px
        H = 0.50
        W = H * aspect
        frame_aspect = 16 / 9
        plate = self.add(grid("M11_plate", W, H, 1, 1, m_image(f"record {ARGS['record']}", rec["tex"], rough=0.8, sheen=0.0)))
        plate.rotation_euler.x = math.radians(90)                        # faces -Y
        fr_m = m_wood("last wheel frame", dark=True)
        b = 0.022
        for nm, (sx, sz, x, z) in {"top": (W + 2 * b, b, 0, H / 2 + b / 2), "bottom": (W + 2 * b, b, 0, -H / 2 - b / 2),
                                   "left": (b, H, -W / 2 - b / 2, 0), "right": (b, H, W / 2 + b / 2, 0)}.items():
            o = self.add(bevel(box(f"M11_frame_{nm}", sx, 0.03, sz, fr_m), 0.003))
            o.location = (x, 0.012, z)
        # the final pose: the plate fills the same rectangle as the engine's HOLD fit (whole scan, pillarboxed in 16:9)
        sensor_w, lens = 36.0, 50.0
        half_h_sensor = sensor_w / frame_aspect / 2
        if aspect <= frame_aspect:
            d = (H / 2) * lens / half_h_sensor                            # height-fit
        else:
            d = (W / 2) * lens / (sensor_w / 2)                           # width-fit (letterboxed)
        self.final_distance = d
        L = self.lamp(light("LAMP_M11", "SPOT", self.c, self.root, 1.0, size=0.15, spot_deg=50, blend=0.5), 3600)
        L.rotation_mode = "QUATERNION"
        locs, rots = [], []
        for fr in FRAMES:
            p = sp(SETTLE, fr, self.f(14)) if fr >= self.f(14) else 0.0
            src = Vector((-1.4, -0.4, 0.25)).lerp(Vector((0.0, -1.7, 0.35)), clamp01(p))
            locs.append(src)
            rots.append(list(look(src, (0, 0, 0)).to_quaternion()))
        bake_vec(L, "location", FRAMES, locs)
        bake_vec(L, "rotation_quaternion", FRAMES, rots, 4)
        self.key(0, (0.30, -1.95, 0.75), (0.0, 0.0, 0.08))
        self.key(LAST - self.start, (0.0, -d, 0.0), (0.0, 0.0, 0.0))


MODULES = {"M01": Clay, "M02": Atlas, "M03": Khipu, "M04": Press, "M05": Survey, "M06": Wire,
           "M07": Count, "M08": Reel, "M09": Type, "M10": Swell, "M11": Record}


# ------------------------------------------------------------------------------------------------ the camera


def catmull(p0, p1, p2, p3, u):
    u2, u3 = u * u, u * u * u
    return 0.5 * ((2 * p1) + (-p0 + p2) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u2 + (-p0 + 3 * p1 - 3 * p2 + p3) * u3)


def solve_camera(keys):
    """One continuous rostrum camera through every key: constant cruise between keys, a smoothstep velocity
    ramp over min(0.9 s, 0.3 of the move) wherever the speed changes (centred on the key, one-sided from or to
    rest), so a cruise hands over through a ramp, never a stop. Each key is hit exactly at its frame."""
    keys = sorted(keys, key=lambda k: k[0])
    F = np.array([k[0] for k in keys], float)
    E = [Vector(k[1]) for k in keys]
    T = [Vector(k[2]) for k in keys]
    U = [Vector(k[3]) for k in keys]
    LENS = [k[4] for k in keys]
    n = len(keys)

    def P(arr, i):
        return arr[max(0, min(n - 1, i))]
    meas = []
    for i in range(n - 1):
        ev = sum((catmull(P(E, i - 1), E[i], E[i + 1], P(E, i + 2), (s + 1) / 40) - catmull(P(E, i - 1), E[i], E[i + 1], P(E, i + 2), s / 40)).length for s in range(40))
        tv = (T[i + 1] - T[i]).length
        meas.append(ev + 0.35 * tv)
    D = np.diff(F)
    c = np.array([m / d if m > 1e-5 else 0.0 for m, d in zip(meas, D)])
    sub = 8
    tt = np.arange(F[0], F[-1] + 1e-9, 1.0 / sub)
    v = np.zeros_like(tt)
    seg = np.clip(np.searchsorted(F, tt, side="right") - 1, 0, n - 2)
    v[:] = c[seg]
    for i in range(n):                                  # ramps at every key
        before = c[i - 1] if i > 0 else 0.0
        after = c[i] if i < n - 1 else 0.0
        if abs(after - before) < 1e-9:
            continue
        dl = D[i - 1] if i > 0 else 1e9
        dr = D[i] if i < n - 1 else 1e9
        r = min(0.9 * FPS, 0.3 * min(dl, dr))
        if before == 0.0:
            a0, a1 = F[i], F[i] + r
        elif after == 0.0:
            a0, a1 = F[i] - r, F[i]
        else:
            a0, a1 = F[i] - r / 2, F[i] + r / 2
        m = (tt >= a0) & (tt <= a1)
        v[m] = before + (after - before) * np.array([smoothstep((t - a0) / (a1 - a0)) for t in tt[m]])
    S = np.concatenate([[0.0], np.cumsum(v[:-1] / sub)])
    out = []
    for fr in FRAMES:
        if fr <= F[0]:
            i, u = 0, 0.0
        elif fr >= F[-1]:
            i, u = n - 2, 1.0
        else:
            i = int(np.searchsorted(F, fr, side="right") - 1)
            s_at = lambda f: np.interp(f, tt, S)
            s0, s1 = s_at(F[i]), s_at(F[i + 1])
            u = (s_at(fr) - s0) / (s1 - s0) if s1 - s0 > 1e-9 else (fr - F[i]) / D[i]
        eye = catmull(P(E, i - 1), E[i], E[i + 1], P(E, i + 2), u)
        tgt = catmull(P(T, i - 1), T[i], T[i + 1], P(T, i + 2), u)
        up = U[i].lerp(U[i + 1], u)
        lens = LENS[i] + (LENS[i + 1] - LENS[i]) * u
        out.append((eye, tgt, up, lens))
    return out


# ------------------------------------------------------------------------------------------------ build


def build() -> dict:
    sc = reset_scene()
    drop = {d for d in ARGS["drop"].split(",") if d}
    specs = [m for m in CFG["modules"] if m["id"] not in drop]
    mods = []
    world = Matrix.Identity(4)
    for spec in specs:
        m = MODULES[spec["id"]](spec)
        m.build()
        m.root.matrix_world = world
        world = world @ m.next_anchor
        mods.append(m)
    bpy.context.view_layer.update()
    # visibility windows and the lamp's windows: one module lit at a time, handed over with a short fade
    for i, m in enumerate(mods):
        prev, nxt = (mods[i - 1] if i > 0 else None), (mods[i + 1] if i + 1 < len(mods) else None)
        ov_in = 0 if (prev is None or m.ov_in == 0 or prev.ov_out == 0) else m.ov_in
        ov_out = 0 if (nxt is None or m.ov_out == 0 or nxt.ov_in == 0) else m.ov_out
        on = max(0, m.start - ov_in)
        off = LAST + 1 if nxt is None else m.end + ov_out
        for ob in m.c.objects:
            key_visible(ob, on, off)
        fade_last = getattr(m, "fade_last", 0)
        for lob, energy in m.lamps:
            vals = []
            for fr in FRAMES:
                k_in = clamp01((fr - (on - 1)) / 10.0) if on > 0 else 1.0
                k_out = clamp01((off - fr) / 10.0)
                if fade_last:
                    k_out = min(k_out, clamp01((m.end - fr) / fade_last))
                vals.append(energy * min(k_in, k_out) if on <= fr < off else 0.0)
            bake(lob.data, "energy", FRAMES, vals)
    # the camera
    cam_d = bpy.data.cameras.new("CAM")
    cam_d.lens = 50.0
    cam_d.sensor_fit = "HORIZONTAL"
    cam_d.sensor_width = 36.0
    cam_d.clip_start = 0.005
    cam_d.clip_end = 60.0
    cam = bpy.data.objects.new("CAM", cam_d)
    sc.collection.objects.link(cam)
    sc.camera = cam
    keys = []
    for m in mods:
        for (fr, eye, tgt, up, lens) in m.cam:
            Mw = m.root.matrix_world
            keys.append((fr, Mw @ Vector(eye), Mw @ Vector(tgt), (Mw.to_3x3() @ Vector(up)).normalized(), lens))
    poses = solve_camera(keys)
    cam.rotation_mode = "QUATERNION"
    locs, rots, lenses, focus = [], [], [], []
    for eye, tgt, up, lens in poses:
        mtx = look(eye, tgt, up)
        locs.append(eye)
        rots.append(list(mtx.to_quaternion()))
        lenses.append(lens)
        focus.append((tgt - eye).length)
    # quaternion continuity (no flips between frames)
    for i in range(1, len(rots)):
        if np.dot(rots[i], rots[i - 1]) < 0:
            rots[i] = [-x for x in rots[i]]
    bake_vec(cam, "location", FRAMES, locs)
    bake_vec(cam, "rotation_quaternion", FRAMES, rots, 4)
    bake(cam_d, "lens", FRAMES, lenses)
    cam_d.dof.use_dof = ARGS["profile"] != "animatic"
    cam_d.dof.aperture_fstop = 4.0
    bake(cam_d, "dof.focus_distance", FRAMES, focus)
    render_settings(sc)
    return {"modules": [m.id for m in mods], "images": IMAGES}


def render_settings(sc):
    p = PROFILE
    sc.render.resolution_x, sc.render.resolution_y = p["res"]
    sc.render.resolution_percentage = 100
    sc.render.use_motion_blur = p["motion_blur"]
    sc.render.motion_blur_shutter = 0.5                 # 180 degrees, as a 24 fps camera
    sc.render.film_transparent = False
    if p["engine"] == "EEVEE":
        sc.render.engine = "BLENDER_EEVEE_NEXT"
        sc.eevee.taa_render_samples = p["samples"]
        sc.eevee.use_shadows = True
        sc.eevee.volumetric_samples = 32
        sc.eevee.volumetric_tile_size = "8"
        sc.eevee.use_volumetric_shadows = True
        sc.render.image_settings.file_format = "PNG"
        sc.render.image_settings.color_depth = "8"
    else:
        sc.render.engine = "CYCLES"
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.compute_device_type = "OPTIX"
        prefs.get_devices()
        for d in prefs.devices:
            d.use = d.type == "OPTIX"                    # GPU only: the laptop stays responsive
        cy = sc.cycles
        cy.device = "GPU"
        cy.samples = p["samples"]
        cy.use_adaptive_sampling = True
        cy.adaptive_threshold = p["noise_threshold"]
        cy.adaptive_min_samples = p["min_samples"]
        cy.use_denoising = True
        cy.denoiser = "OPENIMAGEDENOISE"
        cy.denoising_input_passes = "RGB_ALBEDO_NORMAL"
        cy.denoising_prefilter = "ACCURATE"
        cy.denoising_use_gpu = True
        cy.max_bounces, cy.diffuse_bounces, cy.glossy_bounces = 6, 3, 3
        cy.transmission_bounces, cy.volume_bounces, cy.transparent_max_bounces = 4, 1, 8
        cy.caustics_reflective = cy.caustics_refractive = False
        cy.sample_clamp_indirect = 5.0
        cy.volume_step_rate = 2.0
        cy.volume_max_steps = 256
        cy.use_animated_seed = True
        cy.texture_limit_render = "8192"
        sc.render.use_persistent_data = True
        sc.render.image_settings.file_format = "OPEN_EXR"
        sc.render.image_settings.color_mode = "RGBA"
        sc.render.image_settings.color_depth = "16"
        sc.render.image_settings.exr_codec = "DWAA"
        # resumable: a frame whose file exists is skipped; a placeholder marks a frame in progress
        sc.render.use_overwrite = False
        sc.render.use_placeholder = True
        if ARGS.get("png"):
            # beside each scene-linear EXR, the display-referred frame (view transform applied, dithered 8-bit PNG)
            # for the engine's assembly
            sc.use_nodes = True
            nt = sc.node_tree
            for n in list(nt.nodes):
                nt.nodes.remove(n)
            rl = nt.nodes.new("CompositorNodeRLayers")
            comp = nt.nodes.new("CompositorNodeComposite")
            fo = nt.nodes.new("CompositorNodeOutputFile")
            fo.base_path = ARGS["png"]
            fo.format.file_format = "PNG"
            fo.format.color_mode = "RGB"
            fo.format.color_depth = "8"
            fo.format.compression = 15
            fo.file_slots[0].path = "####"
            nt.links.new(rl.outputs["Image"], comp.inputs["Image"])
            nt.links.new(rl.outputs["Image"], fo.inputs[0])
    sc.frame_set(0)


def check_provenance(images: dict):
    """Every image datablock in the .blend is a manifest texture whose source is a ledger item (or a drawn map
    derived from one) or a film's record; nothing is marked ai."""
    ledger = json.loads((HERE.parent / "assets-ledger.json").read_text(encoding="utf-8"))
    ids = {i["id"] for i in ledger["items"] if i.get("sha256")} | set(ledger["records"])
    bad = []
    for img in bpy.data.images:
        if img.source in ("VIEWER", "GENERATED") and not img.filepath:
            continue
        name = img.name
        src = MAN.get(name, {}).get("from")
        if src is None or src not in ids:
            bad.append(f"{name}: {img.filepath} (from {src})")
        if any(i.get("ai") for i in ledger["items"] if i["id"] == src):
            bad.append(f"{name}: source marked ai")
    if bad:
        raise SystemExit("provenance check failed:\n  " + "\n  ".join(bad))
    print(f"provenance: {len(bpy.data.images)} images, each from a ledger item; none ai")


def main():
    t0 = __import__("time").time()
    info = build()
    check_provenance(info["images"])
    out = ARGS["out"] or CFG["paths"]["blend"].format(record=ARGS["record"]).replace(".blend", f"-{ARGS['profile']}.blend")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=out, compress=False)
    print(f"built {info['modules']} record {ARGS['record']} profile {ARGS['profile']} -> {out} "
          f"in {__import__('time').time() - t0:.1f} s")


if __name__ == "__main__":
    main()
