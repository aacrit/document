"""Title v6 (The Run with the instruments), day 1: the scan gate, the museum scales, the baked transforms and the
convex decompositions the ball collides with (numpy, trimesh, coacd, scipy; the D: venv).

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/scans_v6.py [--no-lock]

Spec: Agentique reports/briefs/title-v6/v6-spec.md section 10 day 1 (Fable, 2026-10-26).

The gate (house rule: real scans only, no AI pixels; an unknown capture method is a refusal) is `gate()`: a CC0 licence,
a capture method that is a real capture, evidence quoted from the institution or digitiser that names that method, no
AI, and every pinned file's sha256 unchanged on disk. It reproduces every verdict already in run-scan-ledger.json.

The scales are the museum records' (`MUSEUM`), read on 2026-10-26 from the institutions' own APIs:
- the globe (Jagiellonian University Museum 4119; 119/V): "wysokość 43,0 cm, szerokość 51,0 cm, głębokość 51,0 cm,
  średnica 32,0 cm (kuli)". Scaled by its ball (a sphere fitted to the scan), its horizon comes to 0.510 x 0.513 m
  (the record's 0.51) and its height to 0.454 m (the record's 0.43, 5.6 percent: the record's height is the lesser
  measure, the two widths and the ball agree). Neither 0.24 (v5d) nor 0.30 m (bench) is the object. It stands on four
  turned wooden feet (the record: "wsparty na czterech toczonych nogach"); the foot the ball glances is wood, not iron.
- the nested weights (Museum of Pharmacy, KGZ 3918): "wysokość 6,2 cm". The scan's cylinder axis is its file's -z
  (captured on its side, as still_v5.upright_scan turns it); scaled to 62 mm tall its body is 65.8 mm across and 74 mm
  over the hasp. bench.WEIGHTS' 70 x 45 mm had the height wrong.
- the jeton (Archaeological Museum in Kraków, MAK/K/887/8, "Liczman FLO"): a square brass plaque, "wysokość 2,4 cm,
  szerokość 1,5 cm, długość 2,6 cm, waga 7,73 kg". The scan is in millimetres (its principal extents are 25.8 x 23.7 x
  2.6); its "depth" of 12.6 is the plaque standing tilted in the file's frame, not a thickness. The record's 1,5 cm
  and 7,73 kg are unit slips (7.73 g of brass over 26 x 24 mm is 1.5 mm thick). It is not a 28 mm disc.
- the coins keep the ledger's diameters (29 and 34 mm), scaled by their largest extent as before.

Each scan is oriented (glTF y-up to the table's z-up, then the object's own upright), scaled, set down with its lowest
point at z = 0 and centred on its footprint; that transform is written per scan (transforms.json) so the scene bakes
the same matrix the physics used. The ball (30 mm) can only touch a scan's lowest BAND_TOP: that band is clipped,
capped, decimated for collision only and decomposed with CoACD; every part is a static convex geom. The decomposition
is accepted when, on the band, no part bulges more than GAP_MAX out of the visual mesh (the ball would hit air) and no
visual surface lies more than GAP_MAX outside the parts (the ball would pass into the object).

Writes D:/document-media/title-sequence/v6/scans/ (transforms.json, <id>-collider.npz, gate.json, report.json).
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
LEDGER = HERE.parents[1] / "run-scan-ledger.json"
ASSETS = Path("D:/document-media/title-sequence/run/assets")
OUT = Path("D:/document-media/title-sequence/v6/scans")
KEY_ID = "SI-morse-vail-key-nmah-1096762"

# ------------------------------------------------------------------------------------------------ the gate

REAL_CAPTURE = {"structured-light", "photogrammetry", "3d-scan", "photo-scan", "laser-scan", "ct-scan"}
# words by which a capture note names a capture method (English, French, Polish, as the institutions write them)
METHOD_WORDS = ("scan", "skan", "photo", "artec", "chmur", "point cloud", "lidar", "tomograph", "structured light")
UNNAMED = ("not named", "not stated on the page", "unknown")


def gate(item: dict, disk: dict | None = None) -> tuple[str, list[str]]:
    """'pass' or 'refuse' for one ledger row, with the reasons for a refusal. disk maps a pinned file's path to its
    sha256 as read now; None skips the file check (the row's own claims only)."""
    why = []
    if item.get("licence") != "CC0":
        why.append(f"licence {item.get('licence')!r} is not CC0")
    method = item.get("capture_method", "")
    if method not in REAL_CAPTURE:
        why.append(f"capture method {method!r} is not a named real capture")
    ev = (item.get("capture_evidence") or "").lower()
    if not ev or any(u in ev for u in UNNAMED) or not any(w in ev for w in METHOD_WORDS):
        why.append("the institution's capture note does not name the method")
    if item.get("ai") is not False:
        why.append("AI or a generative step is not ruled out")
    if not item.get("sha256") and method in REAL_CAPTURE:
        why.append("no pinned archive hash")
    if disk is not None:
        for f in item.get("files", []):
            got = disk.get(f["path"])
            if got is None:
                why.append(f"pinned file missing: {f['path']}")
            elif got != f["sha256"]:
                why.append(f"pinned file changed: {f['path']}")
    return ("refuse" if why else "pass"), why


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ------------------------------------------------------------------------------------------------ the museum records

MUSEUM = {
    "globe": {"source": "https://api.muzea.malopolska.pl/api/object/2727",
              "record": "wysokość 43,0 cm, szerokość 51,0 cm, głębokość 51,0 cm, średnica 32,0 cm (kuli)",
              "height_m": 0.43, "width_m": 0.51, "depth_m": 0.51, "ball_d_m": 0.32,
              "materials": ["papier-mâché", "mosiądz", "gips"], "feet": "four turned wooden legs (wood)"},
    "weights": {"source": "https://api.muzea.malopolska.pl/api/object/1955", "record": "wysokość 6,2 cm",
                "height_m": 0.062, "materials": ["mosiądz"]},
    "jeton": {"source": "https://api.muzea.malopolska.pl/api/object/1558",
              "record": "wysokość 2,4 cm, szerokość 1,5 cm, długość 2,6 cm, waga 7,73 kg",
              "size_m": (0.026, 0.024), "mass_kg": 0.00773, "materials": ["mosiądz"],
              "note": "a square plaque; 1,5 cm and 7,73 kg are unit slips (1.5 mm, 7.73 g)"},
    "FS-coin-dupondius-octavian": {"source": "run-scan-ledger.json", "d_m": 0.029, "mass_kg": 0.01893},
    "FS-coin-sesterce-trajan": {"source": "run-scan-ledger.json", "d_m": 0.034, "mass_kg": 0.02635},
}


def fit_scale(native, real) -> tuple[float, list[float]]:
    """The one factor k that best maps native extents onto real ones in log space, and each residual k*n/r - 1."""
    native, real = np.asarray(native, float), np.asarray(real, float)
    k = float(np.exp(np.mean(np.log(real / native))))
    return k, [float(k * n / r - 1) for n, r in zip(native, real)]


def axis_scale(native_extent: float, real_extent: float) -> float:
    return real_extent / native_extent


def globe_scale(ball_native: float) -> float:
    """The globe is scaled by its ball: the record's 32 cm over the diameter of the sphere fitted to the scan."""
    return MUSEUM["globe"]["ball_d_m"] / ball_native


def zup(v):
    """glTF (y up) to the table's frame (z up): (x, y, z) -> (x, -z, y), as Blender's importer does."""
    v = np.asarray(v, float)
    return np.stack([v[:, 0], -v[:, 2], v[:, 1]], 1)


def rot_x(deg):
    a = math.radians(deg)
    return np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])


def upright_weights_R():
    """The weights were captured on their side, lid to -y: turned -90 degrees about x (still_v5.upright_scan)."""
    return rot_x(-90.0)


def flat_R(points):
    """A rotation that lays a flat object down: its thinnest principal axis to +z, its longest to +x."""
    P = np.asarray(points, float)
    w, V = np.linalg.eigh(np.cov((P - P.mean(0)).T))
    e3, e1 = V[:, 0], V[:, 2]
    e2 = np.cross(e3, e1)
    return np.stack([e1, e2, e3])


def fit_sphere(p):
    A = np.c_[2 * p, np.ones(len(p))]
    b = (p ** 2).sum(1)
    x, *_ = np.linalg.lstsq(A, b, rcond=None)
    c = x[:3]
    return c, float(np.sqrt(x[3] + c @ c))


# ------------------------------------------------------------------------------------------------ the colliders

# The contact band: a 30 mm ball on the sheets (up to 1.5 mm of plates) meets a standing object with its side, the
# contact normal within about 53 degrees of horizontal: between 3 and 27 mm above the object's base. Above that only
# the ball's crown could touch, which needs an overhang the feet and the weights do not have.
BAND_TOP = 0.027
CLIP_TOP = 0.030          # the band is cut here and capped; the decomposition sees nothing above
GAP_MAX = 0.001
COLLIDE = {"globe": {"threshold": 0.02, "faces": 8000}, "weights": {"threshold": 0.02, "faces": 20000}}


def load_native(sid):
    import trimesh
    s = trimesh.load(str(ASSETS / sid / "scene.gltf"), force="scene", skip_materials=True)
    m = s.dump(concatenate=True)
    return trimesh.Trimesh(np.asarray(m.vertices, float), np.asarray(m.faces), process=True)


def world_transform(sid, v_native):
    """(4x4 matrix from the glTF file's own frame to the table at the origin, its footprint centred and its lowest
    point at z = 0; the scale and how it was found)."""
    v = zup(v_native)
    Rz = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float)          # zup() as a matrix
    if sid == "globe":
        z0 = v[:, 2].min()
        H = v[:, 2].max() - z0
        c, R = fit_sphere(v[v[:, 2] > z0 + 0.75 * H])
        for _ in range(8):
            keep = np.abs(np.linalg.norm(v - c, axis=1) - R) < 0.015 * R
            c, R = fit_sphere(v[keep])
        k = globe_scale(2 * R)
        how = {"by": "ball", "ball_native": 2 * R, "ball_inliers": int(keep.sum())}
        Ro = np.eye(3)
    elif sid == "weights":
        Ro = upright_weights_R()
        u = v @ Ro.T
        k = axis_scale(float(u[:, 2].max() - u[:, 2].min()), MUSEUM["weights"]["height_m"])
        how = {"by": "height", "height_native": float(u[:, 2].max() - u[:, 2].min())}
    elif sid == "jeton":
        Ro = flat_R(v)
        u = (v - v.mean(0)) @ Ro.T
        ext = u.max(0) - u.min(0)
        k, res = fit_scale(ext[:2], MUSEUM["jeton"]["size_m"])
        k = 0.001 if abs(k - 0.001) < 2e-5 else k                       # the file is in millimetres
        how = {"by": "plaque", "extents_native": ext.tolist(), "fit_residuals": res}
    else:
        Ro = flat_R(v)
        u = (v - v.mean(0)) @ Ro.T
        ext = u.max(0) - u.min(0)
        k = MUSEUM[sid]["d_m"] / float(ext[:2].max())
        how = {"by": "diameter", "extents_native": ext.tolist()}
    M = np.eye(4)
    M[:3, :3] = k * Ro @ Rz
    w = v_native @ M[:3, :3].T
    lo, hi = w.min(0), w.max(0)
    M[:3, 3] = [-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]]
    return M, k, how


def apply(M, v):
    return np.asarray(v, float) @ M[:3, :3].T + M[:3, 3]


def band_mesh(mesh, top):
    """The mesh below z = top, cut and capped (watertight, so CoACD and the signed distances see a solid)."""
    import trimesh.intersections as TI
    return TI.slice_mesh_plane(mesh, plane_normal=[0, 0, -1.0], plane_origin=[0, 0, top], cap=True)


def decompose(sid, world):
    """CoACD on the decimated, clipped band, component by component (the globe's four feet are separate solids)."""
    import coacd
    import trimesh
    cfg = COLLIDE[sid]
    band = band_mesh(world, CLIP_TOP)
    parts = []
    comps = band.split(only_watertight=False)
    total = sum(len(c.faces) for c in comps)
    for comp in comps:
        if comp.extents.max() < 0.004:                                  # a crumb of the scan, no contact surface
            continue
        target = max(400, int(cfg["faces"] * len(comp.faces) / total))
        if len(comp.faces) > target:
            comp = comp.simplify_quadric_decimation(face_count=target)
        cm = coacd.Mesh(np.asarray(comp.vertices, float), np.asarray(comp.faces, np.int64))
        for pv, pf in coacd.run_coacd(cm, threshold=cfg["threshold"], max_convex_hull=-1, preprocess_mode="auto",
                                      resolution=2000, mcts_iterations=150, seed=1):
            hull = trimesh.Trimesh(np.asarray(pv), np.asarray(pf)).convex_hull
            parts.append(hull)
    return band, parts


def planes(hull):
    """A convex hull's face planes (unit normals out, offsets): inside iff n . p - d <= 0 for every face."""
    n = np.asarray(hull.face_normals, float)
    d = np.einsum("ij,ij->i", n, np.asarray(hull.vertices)[hull.faces[:, 0]])
    return n, d


def depth_inside(pl, P):
    """max over faces of (n . p - d): negative inside the convex part (exactly minus the depth), positive outside (a
    lower bound on the distance, exact where the nearest feature is a face). Batched under machine_v6.batch_rows."""
    import machine_v6 as MV
    n, d = pl
    out = np.empty(len(P))
    rows = MV.batch_rows(8 * min(len(n), 256) * 2)
    for i in range(0, len(P), rows):
        Q = P[i:i + rows]
        o = np.full(len(Q), -np.inf)
        for k in range(0, len(n), 256):
            o = np.maximum(o, (Q @ n[k:k + 256].T - d[k:k + 256]).max(1))
        out[i:i + rows] = o
    return out


VIS_SPACING = 0.00025      # the visual band's sample spacing (0.25 mm) for the gap check
VIS_MAX = 400_000          # and its cap (about 10 MB of points)


def visual_samples(band_visual, seed=1):
    """Oriented points on the visual band (surface sample, outward face normals), and a KD-tree over them. No ray test:
    the bluescreen of 2026-10-26 came from trimesh's ray-based inside test asking for 13 GiB."""
    import trimesh
    from scipy.spatial import cKDTree
    m = band_visual
    zc = m.triangles_center[:, 2]
    keep = (zc > 0.0) & (zc < BAND_TOP + 0.002)
    sub = m.submesh([np.nonzero(keep)[0]], append=True)
    n = int(min(VIS_MAX, max(20_000, sub.area / VIS_SPACING ** 2)))
    pts, fi = trimesh.sample.sample_surface(sub, n, seed=seed)
    return pts, sub.face_normals[fi], cKDTree(pts)


def visual_signed(vis, P, k=4):
    """Signed distance of points to the visual surface (positive outside), from the nearest oriented samples: the
    offset along the normal of the nearest of the k nearest samples. Its error is about the spacing squared over the
    local radius of curvature (under 0.01 mm at 0.25 mm spacing and 3 mm radii). Batched."""
    import machine_v6 as MV
    pts, nrm, tree = vis
    out = np.empty(len(P))
    rows = MV.batch_rows(8 * (3 + 2 * k) * 4)
    for i in range(0, len(P), rows):
        Q = P[i:i + rows]
        dd, ii = tree.query(Q, k=k)
        j = ii[np.arange(len(Q)), np.argmin(dd, axis=1)]
        out[i:i + rows] = np.einsum("ij,ij->i", Q - pts[j], nrm[j])
    return out


def gaps(band_visual, parts, n=60000, seed=0):
    """(air, missing, info) in metres on the contact band (0.5 mm to BAND_TOP): air, how far any part's outer surface
    lies outside the visual solid (the ball would strike air); missing, how far any visual surface lies outside every
    part (the ball would pass into the object). Per part: its worst air and where. Sampled, never ray-cast."""
    import trimesh
    rng = np.random.default_rng(seed)
    pls = [planes(p) for p in parts]
    area = sum(q.area for q in parts)
    vis = visual_samples(band_visual)
    per_part = []
    air_all, pts_all = [], []
    for j, p in enumerate(parts):
        k = max(200, int(n * p.area / area))
        s, _ = trimesh.sample.sample_surface(p, k, seed=int(rng.integers(1 << 30)))
        s = s[(s[:, 2] > 0.0005) & (s[:, 2] < BAND_TOP)]
        if not len(s):
            continue
        buried = np.zeros(len(s), bool)
        for i, pl in enumerate(pls):               # a face buried in another part is not a contact surface
            if i != j:
                buried |= depth_inside(pl, s) < -1e-5
        s = s[~buried]
        if not len(s):
            continue
        a = visual_signed(vis, s)
        air_all.append(a)
        pts_all.append(s)
        w = int(np.argmax(a))
        per_part.append({"part": j, "air_max_m": float(max(0.0, a[w])), "at": s[w].round(4).tolist()})
    air_v = np.concatenate(air_all) if air_all else np.zeros(1)
    V = vis[0][::max(1, len(vis[0]) // n)]
    V = V[(V[:, 2] > 0.0005) & (V[:, 2] < BAND_TOP)]
    depth = np.full(len(V), np.inf)
    for pl in pls:
        depth = np.minimum(depth, depth_inside(pl, V))
    outside = depth > 1e-6
    out_pts = V[outside]
    miss = depth[outside]
    missing = float(miss.max()) if len(miss) else 0.0
    # by side: the worst air and missing in each 30 degree sector about the footprint centre (the origin), so the
    # side the ball can reach can be judged on its own and the object turned to present it
    P = np.concatenate(pts_all) if pts_all else np.zeros((0, 3))
    sec = {}
    for q in range(12):
        lo_, hi_ = -180 + 30 * q, -150 + 30 * q
        aP = np.degrees(np.arctan2(P[:, 1], P[:, 0]))
        aM = np.degrees(np.arctan2(out_pts[:, 1], out_pts[:, 0])) if len(out_pts) else np.zeros(0)
        mA, mM = (aP >= lo_) & (aP < hi_), (aM >= lo_) & (aM < hi_)
        sec[f"{lo_}..{hi_}"] = {"air_m": float(max(0.0, air_v[mA].max())) if mA.any() else 0.0,
                                "missing_m": float(miss[mM].max()) if mM.any() else 0.0}
    Vb = band_visual.vertices
    mid = Vb[(Vb[:, 2] > 0.004) & (Vb[:, 2] < 0.012)]
    far = mid[int(np.argmax(np.hypot(mid[:, 0], mid[:, 1])))] if len(mid) else np.zeros(3)
    return float(max(0.0, air_v.max())), missing, {
        "method": f"sampled: visual band {len(vis[0])} oriented points at {VIS_SPACING * 1000:.2f} mm (KD-tree), parts "
                  "by their face planes; no ray tests",
        "sectors": sec, "protrusion_deg": float(np.degrees(np.arctan2(far[1], far[0]))),
        "protrusion_r_m": float(np.hypot(far[0], far[1])),
        "n_visual_pts": int(len(V)), "n_visual_outside_parts": int(len(out_pts)),
        "air_p99_m": float(np.percentile(np.maximum(air_v, 0), 99)),
        "missing_p99_m": float(np.percentile(miss, 99)) if len(miss) else 0.0,
        "worst_parts": sorted(per_part, key=lambda r: -r["air_max_m"])[:6]}


def gate_all():
    """Every scan v6 uses (and the key), gated against the ledger and the files on disk now."""
    items = {i["id"]: i for i in json.loads(LEDGER.read_text(encoding="utf-8"))["items"]}
    out = {}
    for sid in ("globe", "weights", "jeton", "FS-coin-dupondius-octavian", "FS-coin-sesterce-trajan", KEY_ID):
        it = items[sid]
        disk = {f["path"]: sha256(Path(f["path"])) for f in it.get("files", []) if Path(f["path"]).exists()}
        verdict, why = gate(it, disk)
        out[sid] = {"gate": verdict, "reasons": why, "ledger_gate": it["gate"], "files_checked": len(disk),
                    "capture_method": it.get("capture_method"), "capture_evidence": it.get("capture_evidence")}
    return out


def main():
    use_lock = "--no-lock" not in sys.argv
    import machine_v6 as MV
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    g = gate_all()
    (OUT / "gate.json").write_text(json.dumps(g, indent=1, ensure_ascii=False), encoding="utf-8")
    for sid, r in g.items():
        print(f"gate {sid}: {r['gate']}" + (f" ({'; '.join(r['reasons'])})" if r["reasons"] else ""))
    only = sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv else None
    if "--threshold" in sys.argv:
        th = float(sys.argv[sys.argv.index("--threshold") + 1])
        for sid in only or COLLIDE:
            COLLIDE[sid]["threshold"] = th
    if "--faces" in sys.argv:
        nf = int(sys.argv[sys.argv.index("--faces") + 1])
        for sid in only or COLLIDE:
            COLLIDE[sid]["faces"] = nf
    transforms, report = {}, {"gate": {k: v["gate"] for k, v in g.items()}, "museum": MUSEUM, "scans": {}}
    if only and (OUT / "report.json").exists():               # one scan redone: keep the others' results
        report["scans"] = json.loads((OUT / "report.json").read_text(encoding="utf-8")).get("scans", {})
        transforms = json.loads((OUT / "transforms.json").read_text(encoding="utf-8"))
    with MV.heavy("v6 scans: CoACD decompositions (CPU)", enabled=use_lock):
        for sid in ("globe", "weights", "jeton", "FS-coin-dupondius-octavian", "FS-coin-sesterce-trajan"):
            if g[sid]["gate"] != "pass" or (only and sid not in only):
                continue
            mesh = load_native(sid)
            M, k, how = world_transform(sid, mesh.vertices)
            world = mesh.copy()
            world.vertices = apply(M, mesh.vertices)
            ext = world.extents
            transforms[sid] = {"matrix_gltf_to_table": M.tolist(), "scale": k, "how": how, "extents_m": ext.tolist()}
            rep = {"faces": int(len(mesh.faces)), "watertight": bool(mesh.is_watertight), "scale": k, "how": how,
                   "extents_m": [round(float(e), 5) for e in ext]}
            if sid in COLLIDE:
                band, parts = decompose(sid, world)
                air, missing, info = gaps(band_mesh(world, CLIP_TOP), parts)
                rep.update({"parts": len(parts), "air_m": air, "missing_m": missing, "gap_ok": max(air, missing) <=
                            GAP_MAX, **info, "threshold": COLLIDE[sid]["threshold"],
                            "decimated_faces": COLLIDE[sid]["faces"]})
                np.savez_compressed(OUT / f"{sid}-collider.npz",
                                    **{f"v{i}": p.vertices.astype(np.float64) for i, p in enumerate(parts)},
                                    **{f"f{i}": p.faces.astype(np.int32) for i, p in enumerate(parts)})
                # the band's outline per part height, for the plot and the placement (footprint at the ball's equator)
                print(f"{sid}: {len(parts)} parts, air {air * 1000:.2f} mm, missing {missing * 1000:.2f} mm; "
                      f"worst {info['worst_parts'][:3]}", flush=True)
            else:
                # visual only: a convex hull for the close-pass check (the ball never touches them by design)
                np.savez_compressed(OUT / f"{sid}-collider.npz", v0=world.convex_hull.vertices,
                                    f0=world.convex_hull.faces.astype(np.int32))
            report["scans"][sid] = rep
    report["wall_s"] = round(time.time() - t0, 1)
    (OUT / "transforms.json").write_text(json.dumps(transforms, indent=1), encoding="utf-8")
    (OUT / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report["scans"], indent=1))


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    main()
