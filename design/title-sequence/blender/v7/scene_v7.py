"""Title v7 "The Record Stands" in Blender (Cycles, no denoiser), from the driver's per-frame plan (plan.json).

    blender -b -noaudio --factory-startup --python design/title-sequence/blender/v7/scene_v7.py -- \
        --plan <plan.json> --frames 0,1,2 --outdir <dir> --res 854x480 --samples 512 --min_samples 64 \
        --threshold 0.02 --exposure <ev> [--meter 170] [--blend <path>] [--still <png>]

The scene (v7-concept.md sections 6-7, with the day-1 measurements): the gated Doppelmayr scan's sphere and meridian
ring only (stand, horizon ring, legs and mat removed), registered and scaled to D, alone in black; one spot lamp
parented to the camera (right 0.9, up 1.2, back 0.3 m; 3400 K against a 4300 K balance; constant), aimed at the
camera's target; a thin homogeneous haze; 400 dust motes drifting around the camera (seed 7, no motion blur); the
records on hinged boards (dark matte card, 2 mm, the scan on the face, a luminance bump), each on a brass rod with two
feet; the film's record carries the flat-hold (lit card mixed toward emission of the scan at 2^-EV). Everything is
keyed every frame from plan.json; nothing is simulated.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import globe_v7 as G  # noqa: E402   (numpy only; the Caster's scipy import is lazy)

TEX_MANIFEST = Path("D:/document-media/title-sequence/tex-manifest.json")


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    a = {"plan": "", "frames": "", "outdir": "", "res": "854x480", "samples": "512", "min_samples": "64",
         "threshold": "0.02", "exposure": "0.0", "meter": "", "meter_res": "427x240", "meter_samples": "64",
         "blend": "", "still": "", "blur": "1", "haze": "", "lamp_w": ""}
    for i, k in enumerate(argv):
        if k.startswith("--") and i + 1 < len(argv):
            a[k[2:]] = argv[i + 1]
    return a


A = _args()
PLAN = json.loads(Path(A["plan"]).read_text(encoding="utf-8"))
K = PLAN["consts"]
IMAGES: dict = {}


# ------------------------------------------------------------------------------------------------ helpers


def _n(nt, kind, **inputs):
    n = nt.nodes.new(kind)
    for k, v in inputs.items():
        n.inputs[k].default_value = v
    return n


def _mat(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    return m, m.node_tree, m.node_tree.nodes["Principled BSDF"]


def image(path, noncolor=False, sha=None):
    p = Path(path)
    if sha is not None and hashlib.sha256(p.read_bytes()).hexdigest() != sha:
        raise SystemExit(f"refused: {p.name} bytes differ from its pin")
    img = bpy.data.images.load(str(p), check_existing=True)
    img.colorspace_settings.name = "Non-Color" if noncolor else "sRGB"
    IMAGES[p.name] = str(p)
    return img


def record_image(name):
    man = json.loads(TEX_MANIFEST.read_text(encoding="utf-8"))
    e = man[name]["tex"]
    return image(e["file"], sha=e["sha256"])


def interp_constant_at(idb, frames):
    ad = idb.animation_data
    if not (ad and ad.action):
        return
    act = ad.action
    if hasattr(act, "fcurves") and len(act.fcurves):
        fcs = list(act.fcurves)
    else:                                  # Blender 4.4 slotted actions
        fcs = [fc for layer in getattr(act, "layers", []) for strip in layer.strips
               for cb in strip.channelbags for fc in cb.fcurves]
    for fc in fcs:
        for kp in fc.keyframe_points:
            kp.interpolation = "CONSTANT" if (int(round(kp.co[0])) in frames or fc.data_path in
                                             ("hide_render", "hide_viewport")) else "LINEAR"


# ------------------------------------------------------------------------------------------------ the scene


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.frame_start, sc.frame_end = 0, K["frames"] - 1
    sc.render.fps, sc.render.fps_base = K["fps_num"], K["fps_den"]
    w = bpy.data.worlds.new("black")
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0, 0, 0, 1)
    w.node_tree.nodes["Background"].inputs[1].default_value = 0.0
    sc.world = w
    return sc


def scan_material(name, base, mr, coat):
    """The scan's own baseColor and metallicRoughness (glTF: G roughness, B metallic); `coat` a thin varnish whose
    roughness follows the scan's (the travelling highlight)."""
    m, nt, b = _mat(name)
    tb = _n(nt, "ShaderNodeTexImage")
    tb.image = base
    tb.interpolation = "Cubic"
    tm = _n(nt, "ShaderNodeTexImage")
    tm.image = mr
    sep = _n(nt, "ShaderNodeSeparateColor")
    nt.links.new(tm.outputs["Color"], sep.inputs[0])
    nt.links.new(tb.outputs["Color"], b.inputs["Base Color"])
    nt.links.new(sep.outputs["Green"], b.inputs["Roughness"])
    nt.links.new(sep.outputs["Blue"], b.inputs["Metallic"])
    gm = K.get("globe_material", {})
    b.inputs["Specular IOR Level"].default_value = gm.get("specular", 0.5)
    if coat > 0:
        b.inputs["Coat Weight"].default_value = coat
        mul = _n(nt, "ShaderNodeMath")
        mul.operation = "MULTIPLY"
        nt.links.new(sep.outputs["Green"], mul.inputs[0])
        mul.inputs[1].default_value = gm.get("coat_rough_factor", 0.45)
        nt.links.new(mul.outputs[0], b.inputs["Coat Roughness"])
    return m


def globe():
    """Sphere and ring from the scan's own buffers, native -> world: s * R^T (p - c)."""
    parts = G.load()
    c = np.array(K["ball_centre_native"])
    s = K["R"] / K["ball_radius_native"]
    Rg = np.array(K["R_geo_to_native"])
    tex = {"sphere": (G.SPHERE_TEX, G.SPHERE_RM, K.get("globe_material", {}).get("coat", 0.35)),
           "ring": (G.RING_TEX, G.RING_RM, 0.0)}
    obs = []
    for name in ("sphere", "ring"):
        P = parts[name]["P"]
        UV = parts[name]["UV"]
        T = parts[name]["T"]
        W = (s * (P - c)) @ Rg            # rows: (R^T (p - c))^T = (p - c)^T R
        me = bpy.data.meshes.new(f"globe {name}")
        me.from_pydata(W.tolist(), [], T.tolist())
        uvl = me.uv_layers.new()
        uv = np.stack([UV[:, 0], 1.0 - UV[:, 1]], 1)
        uvl.data.foreach_set("uv", uv[T.ravel()].astype(np.float32).ravel())
        me.polygons.foreach_set("use_smooth", np.ones(len(T), bool))
        me.update()
        ob = bpy.data.objects.new(f"Doppelmayr globe 1728, {name} (gated scan)", me)
        bpy.context.scene.collection.objects.link(ob)
        bt, mt, coat = tex[name]
        me.materials.append(scan_material(f"{name} (scan)", image(bt), image(mt, noncolor=True), coat))
        obs.append(ob)
    return obs


def card_material():
    m, nt, b = _mat("board card (dark matte, DRAWN)")
    b.inputs["Base Color"].default_value = (0.025, 0.021, 0.018, 1)
    b.inputs["Roughness"].default_value = 0.85
    b.inputs["Specular IOR Level"].default_value = 0.25
    return m


def brass_material():
    m, nt, b = _mat("brass (hinge, feet; DRAWN)")
    b.inputs["Base Color"].default_value = (0.62, 0.45, 0.20, 1)
    b.inputs["Metallic"].default_value = 1.0
    b.inputs["Roughness"].default_value = 0.38
    return m


def face_material(texname, ev, flat=False):
    """The record's face: matte paper (rough 0.75, a little sheen, a luminance bump). The film's record adds the
    flat-hold: mixed toward emission of the scan at 2^-EV by the keyed value `flat_hold`."""
    m, nt, b = _mat(f"{texname} face")
    t = _n(nt, "ShaderNodeTexImage")
    t.image = record_image(texname)
    t.interpolation = "Linear" if flat else "Cubic"
    t.extension = "EXTEND"
    nt.links.new(t.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 1.0 if flat else 0.75
    b.inputs["Specular IOR Level"].default_value = 0.0 if flat else 0.3
    b.inputs["Sheen Weight"].default_value = 0.0 if flat else 0.12
    if not flat:
        bw = _n(nt, "ShaderNodeRGBToBW")
        nt.links.new(t.outputs["Color"], bw.inputs["Color"])
        bp = _n(nt, "ShaderNodeBump", Strength=0.08, Distance=0.0003)
        nt.links.new(bw.outputs["Val"], bp.inputs["Height"])
        nt.links.new(bp.outputs["Normal"], b.inputs["Normal"])
        return m, None
    em = _n(nt, "ShaderNodeEmission", Strength=2.0 ** -ev)
    nt.links.new(t.outputs["Color"], em.inputs["Color"])
    val = nt.nodes.new("ShaderNodeValue")
    val.name = val.label = "flat_hold"
    ms = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(val.outputs[0], ms.inputs[0])
    nt.links.new(b.outputs[0], ms.inputs[1])
    nt.links.new(em.outputs[0], ms.inputs[2])
    nt.links.new(ms.outputs[0], nt.nodes["Material Output"].inputs["Surface"])
    return m, val


def panel_mesh(name, hw, hh, t, face_m, card_m):
    """A card: face at +z (uv over the whole scan, image left at -x), back and edges in card."""
    v = [(-hw, -hh, t / 2), (hw, -hh, t / 2), (hw, hh, t / 2), (-hw, hh, t / 2),
         (-hw, -hh, -t / 2), (hw, -hh, -t / 2), (hw, hh, -t / 2), (-hw, hh, -t / 2)]
    f = [(0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
    me = bpy.data.meshes.new(name)
    me.from_pydata(v, [], f)
    uvl = me.uv_layers.new()
    uvs = []
    for poly in me.polygons:
        for li in poly.loop_indices:
            x, y, _ = v[me.loops[li].vertex_index]
            uvs += [(x / hw + 1) / 2, (y / hh + 1) / 2]
    uvl.data.foreach_set("uv", uvs)
    me.materials.append(face_m)
    me.materials.append(card_m)
    me.polygons.foreach_set("material_index", [0, 1, 1, 1, 1, 1])
    me.update()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def cylinder(name, a, b, r, mat):
    a, b = Vector(a), Vector(b)
    bpy.ops.mesh.primitive_cylinder_add(vertices=20, radius=r, depth=(b - a).length, location=(a + b) / 2)
    ob = bpy.context.active_object
    ob.name = name
    ob.rotation_mode = "QUATERNION"
    ob.rotation_quaternion = (b - a).to_track_quat("Z", "Y")
    ob.data.materials.append(mat)
    return ob


def boards(ev):
    card, brass = card_material(), brass_material()
    flat_val = None
    objs = []
    for b in PLAN["boards"]:
        for k, pn in enumerate(b["panels"]):
            fm, val = face_material(pn["tex"], ev, flat=b.get("tail", False))
            flat_val = val or flat_val
            ob = panel_mesh(f"{b['id']} {pn['tex']} (record on a DRAWN board)", pn["hw"], pn["hh"], K["card_t"], fm, card)
            ob.rotation_mode = "QUATERNION"
            objs.append((b, k, ob))
        h = b["hinge"]
        cylinder(f"{b['id']} hinge rod (brass, DRAWN)", h["rod_a"], h["rod_b"], K["rod_r"], brass)
        for fa, fb in h["feet"]:
            cylinder(f"{b['id']} hinge foot (brass, DRAWN)", fa, fb, K["rod_r"] * 1.4, brass)
    return objs, flat_val


def key_boards(objs):
    for f, row in enumerate(PLAN["frames"]):
        for b, k, ob in objs:
            st = row["panels"][b["id"]][k]
            M = Matrix([st["x"], st["y"], st["z"]]).transposed()
            ob.location = st["c"]
            ob.rotation_quaternion = M.to_quaternion()
            ob.hide_render = not row["show"][b["id"]]
            ob.keyframe_insert("location", frame=f)
            ob.keyframe_insert("rotation_quaternion", frame=f)
            ob.keyframe_insert("hide_render", frame=f)
    for _, _, ob in objs:
        interp_constant_at(ob, set(K["constant_frames"]))
    # hinge parts follow their board's visibility
    for b in PLAN["boards"]:
        for ob in bpy.data.objects:
            if ob.name.startswith(f"{b['id']} hinge"):
                for f in (0, K["cut"] - 1, K["cut"], K["frames"] - 1):
                    ob.hide_render = not PLAN["frames"][f]["show"][b["id"]]
                    ob.keyframe_insert("hide_render", frame=f)
                interp_constant_at(ob, set())


def camera_and_lamp():
    cd = bpy.data.cameras.new("the reader's camera")
    cd.lens = K["lens_mm"]
    cd.sensor_fit = "HORIZONTAL"
    cd.sensor_width = K["sensor_mm"]
    cd.clip_start, cd.clip_end = 0.01, 50.0
    cd.dof.use_dof = True
    cam = bpy.data.objects.new("the reader's camera", cd)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    cam.rotation_mode = "QUATERNION"
    L = K["lamp"]
    ld = bpy.data.lights.new("the lamp (camera-parented)", "SPOT")
    ld.shadow_soft_size = L["shade_d_m"] / 2
    ld.spot_size = math.radians(L["spot_deg"])
    ld.spot_blend = L["spot_blend"]
    ld.energy = float(A["lamp_w"] or L["power_w"])
    ld.use_nodes = True
    nt = ld.node_tree
    bb = nt.nodes.new("ShaderNodeBlackbody")
    bb.inputs[0].default_value = L["kelvin"]
    wb = nt.nodes.new("ShaderNodeBlackbody")
    wb.inputs[0].default_value = L["white_balance_k"]
    dv = nt.nodes.new("ShaderNodeVectorMath")
    dv.operation = "DIVIDE"
    nt.links.new(bb.outputs[0], dv.inputs[0])
    nt.links.new(wb.outputs[0], dv.inputs[1])
    nt.links.new(dv.outputs[0], nt.nodes["Emission"].inputs["Color"])
    lamp = bpy.data.objects.new("the lamp (camera-parented)", ld)
    bpy.context.scene.collection.objects.link(lamp)
    lamp.parent = cam
    lamp.location = Vector(L["offset_cam"])
    lamp.rotation_mode = "QUATERNION"
    for f, row in enumerate(PLAN["frames"]):
        c = row["cam"]
        cam.location = c["E"]
        cam.rotation_quaternion = Matrix([c["x"], c["y"], c["z"]]).transposed().to_quaternion()
        cd.dof.focus_distance = c["focus"]
        cd.dof.aperture_fstop = c["fstop"]
        cam.keyframe_insert("location", frame=f)
        cam.keyframe_insert("rotation_quaternion", frame=f)
        cd.dof.keyframe_insert("focus_distance", frame=f)
        cd.dof.keyframe_insert("aperture_fstop", frame=f)
        aim = Vector((0.0, 0.0, -c["focus"])) - lamp.location
        lamp.rotation_quaternion = aim.to_track_quat("-Z", "Y")
        lamp.keyframe_insert("rotation_quaternion", frame=f)
    for idb in (cam, cd, lamp):
        interp_constant_at(idb, set(K["constant_frames"]))
    return cam, lamp


def haze():
    hz = K["haze"]
    bpy.ops.mesh.primitive_cube_add(size=hz["box_m"], location=(0, 0, 0))
    ob = bpy.context.active_object
    ob.name = "haze (DRAWN)"
    m = bpy.data.materials.new("haze")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.remove(nt.nodes["Principled BSDF"])
    vs = _n(nt, "ShaderNodeVolumeScatter")
    vs.inputs["Density"].default_value = float(A["haze"] or hz["density"])
    vs.inputs["Anisotropy"].default_value = hz["anisotropy"]
    vs.inputs["Color"].default_value = (1, 1, 1, 1)
    nt.links.new(vs.outputs[0], nt.nodes["Material Output"].inputs["Volume"])
    ob.data.materials.append(m)
    ob.visible_shadow = False
    # the haze clears through the close-in so nothing lit stands between the lens and the record at the pose (A7)
    base = vs.inputs["Density"].default_value
    prev = None
    for f, row in enumerate(PLAN["frames"]):
        k = row.get("haze", 1.0)
        if k != prev or f == K["frames"] - 1:
            vs.inputs["Density"].default_value = base * k
            vs.inputs["Density"].keyframe_insert("default_value", frame=f)
            prev = k
    return ob


DUST = {}


def dust():
    d = K["dust"]
    rng = np.random.default_rng(d["seed"])
    n = d["count"]
    box = d["box_m"]
    DUST["p0"] = rng.uniform(-box / 2, box / 2, (n, 3))
    v = rng.normal(size=(n, 3))
    DUST["v"] = v / np.linalg.norm(v, axis=1, keepdims=True) * d["drift_m_s"]
    me = bpy.data.meshes.new("dust points")
    me.vertices.add(n)
    me.update()
    pts = bpy.data.objects.new("dust (DRAWN)", me)
    bpy.context.scene.collection.objects.link(pts)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=d["radius_m"], location=(0, 0, -1000))
    mote = bpy.context.active_object
    mote.name = "dust mote"
    m, nt, b = _mat("dust (matte)")
    b.inputs["Base Color"].default_value = (0.75, 0.72, 0.66, 1)
    b.inputs["Roughness"].default_value = 0.9
    mote.data.materials.append(m)
    mote.parent = pts
    mote.location = (0, 0, 0)
    pts.instance_type = "VERTS"
    for ob in (pts, mote):
        ob.cycles.use_motion_blur = False
    DUST["pts"], DUST["mote"] = pts, mote
    bpy.app.handlers.frame_change_pre.append(dust_update)


def dust_update(scene, depsgraph=None):
    f = scene.frame_current
    row = PLAN["frames"][min(max(f, 0), K["frames"] - 1)]
    E = np.array(row["cam"]["E"])
    t = f / (K["fps_num"] / K["fps_den"])
    box = K["dust"]["box_m"]
    p = DUST["p0"] + DUST["v"] * t - E
    p = (p + box / 2) % box - box / 2
    near = np.linalg.norm(p, axis=1) < K["dust"]["min_dist_m"]
    p[near] = 1000.0                       # nothing within reach of the lens
    co = (p + E).astype(np.float32)
    co[near] = (0, 0, -1000)
    DUST["pts"].data.vertices.foreach_set("co", co.ravel())
    DUST["pts"].data.update()
    s = row["dust_scale"]
    DUST["mote"].scale = (s, s, s)
    DUST["mote"].hide_render = s <= 1e-4


def key_flat(val):
    if val is None:
        return
    for f, row in enumerate(PLAN["frames"]):
        val.outputs[0].default_value = row["hold_mix"]
        val.outputs[0].keyframe_insert("default_value", frame=f)


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
    cy.use_denoising = False                  # NO denoiser of any kind (founder ruling: no AI pixels)
    cy.use_preview_denoising = False
    cy.sample_clamp_direct = 0.0
    cy.sample_clamp_indirect = 5.0
    cy.max_bounces, cy.diffuse_bounces, cy.glossy_bounces, cy.transmission_bounces = 8, 3, 3, 4
    cy.volume_bounces = 0
    cy.volume_step_rate = 4.0
    cy.caustics_reflective = cy.caustics_refractive = False
    cy.texture_limit_render = "8192"
    cy.seed = 0
    sc.render.use_motion_blur = A["blur"] == "1"
    sc.render.motion_blur_shutter = K["shutter_deg"] / 360.0
    sc.render.motion_blur_position = "START"     # f samples f..f+0.5: frame 719 never blurs back across the cut
    sc.render.use_compositing = False
    sc.render.use_sequencer = False
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    s = sc.render.image_settings
    if fmt == "EXR":
        s.file_format, s.color_mode, s.color_depth, s.exr_codec = "OPEN_EXR", "RGB", "32", "NONE"
    else:
        s.file_format, s.color_mode, s.color_depth, s.compression = "PNG", "RGB", "8", 30
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


def meter(sc, frame):
    """The fixed exposure: max(R,G,B) at its 99.5th percentile over the frame (the Atlas vellum nearest the lamp at
    its read) set to 0.85 of display white (Standard: sRGB 0.85 -> linear 0.694)."""
    settings(sc, A["meter_res"], A["meter_samples"], 16, 0.02, fmt="EXR")
    sc.view_settings.exposure = 0.0
    sc.frame_set(frame)
    p = Path(A["outdir"]) / f"meter-f{frame:04d}.exr"
    sc.render.filepath = str(p)
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(str(p), check_existing=False)
    w, h = img.size
    px = np.array(img.pixels[:], np.float32).reshape(h, w, 4)
    bpy.data.images.remove(img)
    M = px[..., :3].max(-1)
    white = float(np.percentile(M, 99.5))
    target = ((0.85 + 0.055) / 1.055) ** 2.4
    return {"frame": frame, "p99_5_max_channel_linear": white, "ev": math.log2(target / white),
            "max": float(M.max()), "p50": float(np.percentile(M, 50))}


def main():
    t0 = time.time()
    ev = float(A["exposure"])
    sc = reset()
    globe()
    objs, flat_val = boards(ev)
    key_boards(objs)
    key_flat(flat_val)
    camera_and_lamp()
    haze()
    dust()
    info = {"build_s": round(time.time() - t0, 1), "images": sorted(IMAGES)}
    if A["meter"]:
        rows = [meter(sc, int(v)) for v in A["meter"].split(",")]
        mt = min(rows, key=lambda r: r["ev"])          # the brightest record sets the one fixed exposure
        mt = {**mt, "by_frame": rows}
        print("V7-METER " + json.dumps(mt), flush=True)
        ev = mt["ev"]
        for m in bpy.data.materials:
            for nd in (m.node_tree.nodes if m.node_tree else []):
                if nd.type == "EMISSION":
                    nd.inputs["Strength"].default_value = 2.0 ** -ev
        info["meter"] = mt
    settings(sc, A["res"], A["samples"], A["min_samples"], A["threshold"])
    sc.view_settings.exposure = ev
    if A["blend"]:
        bpy.ops.wm.save_as_mainfile(filepath=A["blend"], compress=True)
    done = []
    if A["frames"]:
        sc.render.use_persistent_data = True
        out = Path(A["outdir"])
        for f in (int(v) for v in A["frames"].split(",")):
            p = out / f"{f:05d}.png"
            if p.exists():
                continue
            sc.frame_set(f)
            sc.render.filepath = str(p)
            t1 = time.time()
            bpy.ops.render.render(write_still=True)
            done.append([f, round(time.time() - t1, 2)])
            print(f"V7-FRAME {f} {done[-1][1]}", flush=True)
    if A["still"]:
        f = int(A["frames"].split(",")[0]) if A["frames"] else 170
        sc.frame_set(f)
        sc.render.filepath = A["still"]
        t1 = time.time()
        bpy.ops.render.render(write_still=True)
        done.append([f, round(time.time() - t1, 2)])
    assert not sc.cycles.use_denoising and not sc.cycles.use_preview_denoising, "no denoiser (founder ruling)"
    lights = [o.name for o in bpy.data.objects if o.type == "LIGHT"]
    emit = [m.name for m in bpy.data.materials if m.node_tree and any(n.type == "EMISSION" for n in m.node_tree.nodes)]
    info.update({"frames_rendered": done, "exposure": ev, "samples": sc.cycles.samples, "res": A["res"],
                 "denoise": False, "lights": lights, "emitters": emit, "motion_blur": sc.render.use_motion_blur,
                 "view_transform": sc.view_settings.view_transform, "blender": bpy.app.version_string,
                 "s": round(time.time() - t0, 1)})
    print("V7-DONE " + json.dumps(info), flush=True)


if __name__ == "__main__":
    main()
