"""The Run v4: one heightmap per sheet, and the table they make together (numpy, scipy and PIL; runs in the D: venv).

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/relief.py

A sheet is a displaced surface with real thickness. Its own relief, in metres at 2 mm a texel, has three layers
(design section 3): (a) the scan's own fold relief, a band-pass of the pinned scan's luminance (6 to 40 mm: folds,
creases and cockle shading, not ink) at 0.2 to 0.5 mm; (b) cockle, laid as parallel troughs along the leg the sheet
carries (bench.SHEETS[...]["cockle"]); (c) the named edge curls and lifts (circular arcs: crest over run) and corner
lifts, plus every free edge 0.6 mm proud over its last 15 mm (paper never lies dead flat to its edge). Special
reliefs: the Atlas's hinge valley (the vellum dips 1.5 mm into the hinge over 25 mm each side), Ino's crease valley
(a 3 mm channel between tented panels), the papyrus's cross fold. No pixel is made: the scan is only read.

The sheets are then set down in their layer order (newest first, bench.SHEETS[...]["layer"]) on a world grid: each
sheet's underside is the higher of its own lie and what lies beneath (smoothed 3 mm: paper bridges small gaps), its
top that plus its thickness; the Atlas's boards are rigid, share one base and press the papers beneath them flat. The same composed
surface is MuJoCo's collision heightfield (sim_run.py) and Blender's displaced mesh (run_take.py), so what turns the
marble is what the camera sees.

Writes D:/document-media/title-sequence/run/relief/<sheet>.exr (channels R: the sheet's own relief, G: its composed top,
B: its composed underside, A: its footprint mask; image rows from the scan's top, +v) and <sheet>.json (extents, texel,
centre, psi, size, the relief's statistics), and world.npz (the table's composed top, the topmost surface's id per
cell, the grid's origin and texel).
"""

from __future__ import annotations

import json
import math
import struct
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bench as B  # noqa: E402

OUT = Path("D:/document-media/title-sequence/run/relief")
TEX = Path("D:/document-media/title-sequence/tex")
TEXEL = 0.002
EDGE_PROUD = (0.0006, 0.015)
DRAPE = 0.006                               # paper bridges what lies beneath over about 6 mm (sigma)
BOARD_BASE = 0.0002                         # the papers pressed flat under the Atlas's boards                # every free edge stands 0.6 mm proud over its last 15 mm
FOLD_AMP = {"papyrus": 0.0003, "piri": 0.0004, "leaf": 0.0002, "ino": 0.0003, "page": 0.0002, "chart": 0.0002}
WORLD = {"x0": -0.10, "y0": -0.10, "x1": 2.32, "y1": 1.34}
SURFACE_IDS = ["oak"] + list(B.SHEETS)


# ------------------------------------------------------------------------------------------------ EXR (uncompressed)


def _attr(name: str, typ: str, data: bytes) -> bytes:
    return name.encode() + b"\0" + typ.encode() + b"\0" + struct.pack("<i", len(data)) + data


def write_exr(path, channels: dict[str, np.ndarray]) -> Path:
    """A scanline OpenEXR, NO_COMPRESSION, 32-bit float channels (any of R, G, B, A), row 0 at the top."""
    names = sorted(channels)
    h, w = next(iter(channels.values())).shape
    chl = b"".join(n.encode() + b"\0" + struct.pack("<iB3xii", 2, 0, 1, 1) for n in names) + b"\0"
    box = struct.pack("<iiii", 0, 0, w - 1, h - 1)
    hdr = (_attr("channels", "chlist", chl) + _attr("compression", "compression", b"\0") +
           _attr("dataWindow", "box2i", box) + _attr("displayWindow", "box2i", box) +
           _attr("lineOrder", "lineOrder", b"\0") + _attr("pixelAspectRatio", "float", struct.pack("<f", 1.0)) +
           _attr("screenWindowCenter", "v2f", struct.pack("<ff", 0.0, 0.0)) +
           _attr("screenWindowWidth", "float", struct.pack("<f", 1.0)) + b"\0")
    head = struct.pack("<ii", 20000630, 2) + hdr
    line = 4 * w * len(names)
    start = len(head) + 8 * h
    offs = struct.pack(f"<{h}Q", *[start + y * (8 + line) for y in range(h)])
    rows = []
    data = [np.ascontiguousarray(channels[n], dtype="<f4") for n in names]
    for y in range(h):
        rows.append(struct.pack("<ii", y, line) + b"".join(d[y].tobytes() for d in data))
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(head + offs + b"".join(rows))
    return p


def read_exr(path) -> dict[str, np.ndarray]:
    """Reads what write_exr writes (uncompressed float scanlines)."""
    b = Path(path).read_bytes()
    assert struct.unpack("<i", b[:4])[0] == 20000630
    i = 8
    attrs = {}
    while b[i] != 0:
        j = b.index(b"\0", i)
        name = b[i:j].decode()
        k = b.index(b"\0", j + 1)
        n = struct.unpack("<i", b[k + 1:k + 5])[0]
        attrs[name] = b[k + 5:k + 5 + n]
        i = k + 5 + n
    i += 1
    chl, names = attrs["channels"], []
    c = 0
    while chl[c] != 0:
        j = chl.index(b"\0", c)
        names.append(chl[c:j].decode())
        c = j + 1 + 16
    assert attrs["compression"] == b"\0"
    x0, y0, x1, y1 = struct.unpack("<iiii", attrs["dataWindow"])
    w, h = x1 - x0 + 1, y1 - y0 + 1
    i += 8 * h
    out = {n: np.zeros((h, w), np.float32) for n in names}
    for _ in range(h):
        y, size = struct.unpack("<ii", b[i:i + 8])
        i += 8
        for ci, n in enumerate(names):
            out[n][y - y0] = np.frombuffer(b, "<f4", w, i + ci * 4 * w)
        i += size
    return out


# ------------------------------------------------------------------------------------------------ one sheet


def sheet_grid(name):
    """Texel centres of a sheet: local (u, v) and table (x, y), row 0 at +v (the scan's top)."""
    s = B.SHEETS[name]
    W, H = s["size"]
    nu, nv = max(2, round(W / TEXEL)), max(2, round(H / TEXEL))
    u = -W / 2 + (np.arange(nu) + 0.5) * W / nu
    v = H / 2 - (np.arange(nv) + 0.5) * H / nv
    U, V = np.meshgrid(u, v)
    p = math.radians(s["psi"])
    X = s["centre"][0] + U * math.cos(p) - V * math.sin(p)
    Y = s["centre"][1] + U * math.sin(p) + V * math.cos(p)
    return U, V, X, Y


def _scan(name, shape):
    """The pinned scan's luminance and alpha, resampled to the sheet's texels (row 0 at the image's top)."""
    from PIL import Image
    s = B.SHEETS[name]
    ext = ".png" if s.get("alpha") else ".jpg"
    im = Image.open(TEX / f"{s['tex']}{ext}")
    im.draft("RGB", (shape[1] * 2, shape[0] * 2)) if ext == ".jpg" else None
    rgba = im.convert("RGBA").resize((shape[1], shape[0]), Image.BOX)
    a = np.asarray(rgba, np.float32) / 255.0
    lum = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
    return lum, a[..., 3]


def arc(s, crest, run):
    """A circular-arc curl: height at distance s (m) in from its foot toward the edge, crest at the edge."""
    r = (run * run + crest * crest) / (2 * crest)
    s = np.clip(s, 0.0, run)
    return r - np.sqrt(np.maximum(r * r - s * s, 0.0))


def smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def own_relief(name):
    """The sheet's own relief (m) on its texels, its footprint mask, and the parts, by layer, for the report."""
    from scipy.ndimage import gaussian_filter
    s = B.SHEETS[name]
    W, H = s["size"]
    U, V, X, Y = sheet_grid(name)
    parts = {}
    # the footprint: keyed scans by their alpha, the others whole
    lum, alpha = _scan(name, U.shape)
    mask = (alpha > 0.5) if s.get("alpha") and not s.get("backing") else np.ones_like(U, bool)
    # (a) the scan's own fold relief: luminance band-passed 6 to 40 mm, dark is low
    amp = FOLD_AMP.get(name, 0.0)
    if amp:
        L = np.where(mask, lum, np.nan)
        fill = np.nanmean(L)
        L = np.where(mask, lum, fill)
        bp = gaussian_filter(L, 0.006 / TEXEL) - gaussian_filter(L, 0.040 / TEXEL)
        k = np.percentile(np.abs(bp[mask]), 99) + 1e-9
        parts["fold"] = np.clip(bp / k, -1, 1) * amp
    # (b) cockle: parallel troughs along the leg, the trough floor through the named point
    ck = s.get("cockle")
    if ck:
        a = math.radians(ck["deg"])
        d = (X - ck["through"][0]) * (-math.sin(a)) + (Y - ck["through"][1]) * math.cos(a)
        parts["cockle"] = ck["amp"] / 2 * (1 - np.cos(2 * math.pi * d / ck["lam"]))
    # (c) edges: named curls and lifts, and corner lifts, measured in from the sheet's real edge: for a keyed scan the
    # fragment's own outline (per line, smoothed over 20 mm), else the rectangle; the outermost texel carries the edge
    h = TEXEL / 2
    dist = {"-u": U + W / 2 - h, "+u": W / 2 - U - h, "-v": V + H / 2 - h, "+v": H / 2 - V - h}
    if s.get("alpha") and not s.get("backing"):
        from scipy.ndimage import gaussian_filter1d
        nv, nu = mask.shape
        rows, cols = np.arange(nv)[:, None], np.arange(nu)[None, :]
        big = 10 ** 6
        first_r = np.where(mask.any(0), np.argmax(mask, 0), big)              # per column: the first opaque row (+v side)
        last_r = np.where(mask.any(0), nv - 1 - np.argmax(mask[::-1], 0), -big)
        first_c = np.where(mask.any(1), np.argmax(mask, 1), big)
        last_c = np.where(mask.any(1), nu - 1 - np.argmax(mask[:, ::-1], 1), -big)
        sm = lambda a, fill: gaussian_filter1d(np.where(np.abs(a) >= big, fill, a).astype(float), 0.02 / TEXEL)  # noqa: E731
        dist["+v"] = (rows - sm(first_r, 0)[None, :]) * TEXEL
        dist["-v"] = (sm(last_r, nv - 1)[None, :] - rows) * TEXEL
        dist["-u"] = (cols - sm(first_c, 0)[:, None]) * TEXEL
        dist["+u"] = (sm(last_c, nu - 1)[:, None] - cols) * TEXEL
        # a named edge is the fragment's edge only where that lies within 6 cm of the rectangle's side; elsewhere the
        # outline is a side or a cut of the fragment, and the curl does not run there
        lim = 0.06 / TEXEL
        far = 10.0
        dist["+v"] = np.where((sm(first_r, 0) < lim)[None, :], dist["+v"], far)
        dist["-v"] = np.where((sm(last_r, nv - 1) > nv - 1 - lim)[None, :], dist["-v"], far)
        dist["-u"] = np.where((sm(first_c, 0) < lim)[:, None], dist["-u"], far)
        dist["+u"] = np.where((sm(last_c, nu - 1) > nu - 1 - lim)[:, None], dist["+u"], far)
        dist = {k: np.maximum(v, 0.0) for k, v in dist.items()}
    edge = np.zeros_like(U)
    taper = np.ones_like(U)
    for e in s.get("edges", []):
        dd = dist[e["edge"]]
        if "taper" in e:
            # the crest varies along the edge: taper = (crest at the edge's -tangent end, crest at its +tangent end)
            tng = (V + H / 2) / H if e["edge"][1] == "u" else (U + W / 2) / W
            cr = e["taper"][0] + (e["taper"][1] - e["taper"][0]) * tng
            edge = np.maximum(edge, arc(e["run"] - dd, e["crest"], e["run"]) * cr / e["crest"])
        else:
            edge = np.maximum(edge, arc(e["run"] - dd, e["crest"], e["run"]))
        taper = np.minimum(taper, smoothstep((dd - e["run"]) / 0.04))     # the cockle dies into a curl
    for c, lift in s.get("corners", {}).items():
        du = dist[c[:2]]
        dv = dist[c[2:]]
        r = np.hypot(np.minimum(du, 0.08), np.minimum(dv, 0.08))
        edge = np.maximum(edge, lift * np.clip(1 - np.hypot(du, dv) / 0.08, 0, 1) ** 2)
        _ = r
    if s.get("alpha") and not s.get("backing"):
        from scipy.ndimage import binary_fill_holes, distance_transform_edt
        nearest = distance_transform_edt(binary_fill_holes(mask)) * TEXEL      # the outline, not every hole's rim
    else:
        nearest = np.minimum.reduce([dist[k] for k in dist])
    proud = EDGE_PROUD[0] * np.clip(1 - nearest / EDGE_PROUD[1], 0, 1) ** 2
    parts["edges"] = edge if s.get("board") else np.maximum(edge, proud)
    if "cockle" in parts:
        parts["cockle"] *= taper
        # the galley presses the paper flat under it
        (gx0, gy0), (gx1, gy1) = B.GALLEY["from"], B.GALLEY["to"]
        gL = math.hypot(gx1 - gx0, gy1 - gy0)
        ga = ((X - gx0) * (gx1 - gx0) + (Y - gy0) * (gy1 - gy0)) / gL
        gc = np.abs(-(X - gx0) * (gy1 - gy0) + (Y - gy0) * (gx1 - gx0)) / gL
        out_ = np.maximum(np.maximum(-ga, ga - gL), 0.0)
        press = (1 - smoothstep((gc - B.GALLEY["press_half_w"]) / 0.03)) * (1 - smoothstep(out_ / 0.03))
        parts["cockle"] *= 1 - press
        if s.get("cockle_clear_hinge"):
            # the parchment lies flat into the Atlas's hinge dip: no cockle within this distance of the hinge line
            lo, hi = B.HINGE["lo"], B.HINGE["hi"]
            L = math.hypot(lo[0] - hi[0], lo[1] - hi[1])
            dh = np.abs(-(X - hi[0]) * (lo[1] - hi[1]) / L + (Y - hi[1]) * (lo[0] - hi[0]) / L)
            parts["cockle"] *= smoothstep((dh - s["cockle_clear_hinge"] / 2) / (s["cockle_clear_hinge"] / 2))
    # specials
    if name in ("atlas1", "atlas2"):
        # the hinge valley: the vellum dips into the hinge, 1.5 mm at the gap, over 25 mm
        dh = dist["+u"] if name == "atlas1" else dist["-u"]
        parts["hinge"] = -B.HINGE["depth"] * (1 - np.clip(dh / B.HINGE["half_w"], 0, 1)) ** 2
    if "crease" in s:
        c = s["crease"]
        (x0, y0), (x1, y1) = c["from"], c["to"]
        L = math.hypot(x1 - x0, y1 - y0)
        tx, ty = (x1 - x0) / L, (y1 - y0) / L
        along = (X - x0) * tx + (Y - y0) * ty
        across = np.abs(-(X - x0) * ty + (Y - y0) * tx)
        ends = smoothstep(along / 0.06) * smoothstep((L - along) / 0.06)
        hw = c["half_w"]
        tent = c["depth"] * smoothstep(across / hw) * (1 - smoothstep((across - hw) / hw))
        parts["crease"] = tent * ends
    if name == "papyrus":
        # its cross fold, 0.3 mm, a third of the way along (the clock's f196)
        u0 = -W / 2 + 0.35 * W
        parts["fold_x"] = 0.0003 * np.exp(-0.5 * ((U - u0) / 0.004) ** 2)
    rel = sum(parts.values())
    return rel.astype(np.float32), mask, parts


# ------------------------------------------------------------------------------------------------ the table


def world_grid():
    nx = round((WORLD["x1"] - WORLD["x0"]) / TEXEL)
    ny = round((WORLD["y1"] - WORLD["y0"]) / TEXEL)
    xs = WORLD["x0"] + (np.arange(nx) + 0.5) * TEXEL
    ys = WORLD["y0"] + (np.arange(ny) + 0.5) * TEXEL
    return xs, ys


def _to_sheet_index(name, X, Y, shape):
    s = B.SHEETS[name]
    W, H = s["size"]
    p = math.radians(s["psi"])
    dx, dy = X - s["centre"][0], Y - s["centre"][1]
    u = dx * math.cos(p) + dy * math.sin(p)
    v = -dx * math.sin(p) + dy * math.cos(p)
    fi = (u + W / 2) / W * shape[1] - 0.5
    fj = (H / 2 - v) / H * shape[0] - 0.5
    inside = (u >= -W / 2) & (u <= W / 2) & (v >= -H / 2) & (v <= H / 2)
    return fi, fj, inside


def _bilinear(a, fi, fj):
    h, w = a.shape
    i0 = np.clip(np.floor(fi).astype(int), 0, w - 2)
    j0 = np.clip(np.floor(fj).astype(int), 0, h - 2)
    ti = np.clip(fi - i0, 0, 1)
    tj = np.clip(fj - j0, 0, 1)
    return (a[j0, i0] * (1 - ti) * (1 - tj) + a[j0, i0 + 1] * ti * (1 - tj) +
            a[j0 + 1, i0] * (1 - ti) * tj + a[j0 + 1, i0 + 1] * ti * tj)


def compose(write=True):
    """Set the sheets down in layer order; returns (world top, surface id grid, per-sheet {top, bottom, mask, rel})."""
    from scipy.ndimage import gaussian_filter
    xs, ys = world_grid()
    XW, YW = np.meshgrid(xs, ys)                       # rows along y (row 0 at the world's y0), columns along x
    top = np.zeros_like(XW, np.float32)
    sid = np.zeros(XW.shape, np.int16)
    sheets = {}
    for name in sorted(B.SHEETS, key=lambda n: B.SHEETS[n]["layer"]):
        s = B.SHEETS[name]
        rel, mask, parts = own_relief(name)
        U, V, X, Y = sheet_grid(name)
        # what lies beneath, at the sheet's texels: the world top sampled there (smoothed: paper bridges 3 mm)
        under_w = gaussian_filter(top, s.get("drape", DRAPE) / TEXEL)
        fi = (X - WORLD["x0"]) / TEXEL - 0.5
        fj = (Y - WORLD["y0"]) / TEXEL - 0.5
        under = _bilinear(under_w, fi, fj)
        under_raw = _bilinear(top, fi, fj)
        t = s["t"]
        if s.get("board"):
            # rigid: its weight presses the papers beneath it flat; both boards share one base, so the hinge is level
            bottom = np.full_like(rel, BOARD_BASE)
            topl = bottom + t + np.minimum(rel, 0.0)       # the vellum's hinge dip below the board's top
        else:
            # paper keeps its own lie on whatever it rests on (it drapes over what lies beneath, 6 mm smoothed)
            # never below what it lies on: the drape only bridges outward from a step (and nothing pokes through)
            bottom = np.maximum(under, under_raw) + np.maximum(rel, 0.0)
            topl = bottom + t
        sheets[name] = {"rel": rel, "top": topl.astype(np.float32), "bottom": bottom.astype(np.float32), "mask": mask,
                        "parts": {k: (float(v.min()), float(v.max())) for k, v in parts.items()}}
        # into the world: the cells under this sheet's footprint take its top
        wi, wj, inside = _to_sheet_index(name, XW, YW, rel.shape)
        m_s = _bilinear(mask.astype(np.float32), wi, wj) > 0.5
        hit = inside & m_s
        tw = _bilinear(topl, wi, wj)
        top = np.where(hit, tw, top).astype(np.float32)
        sid = np.where(hit, SURFACE_IDS.index(name), sid).astype(np.int16)
        if name == "atlas2":
            # the hinge: the Atlas's vellum runs on across the 1.5 mm gap between its boards, at the valley's floor
            lo, hi = B.HINGE["lo"], B.HINGE["hi"]
            L = math.hypot(lo[0] - hi[0], lo[1] - hi[1])
            tx, ty = (lo[0] - hi[0]) / L, (lo[1] - hi[1]) / L
            along = (XW - hi[0]) * tx + (YW - hi[1]) * ty
            across = np.abs(-(XW - hi[0]) * ty + (YW - hi[1]) * tx)
            gap = (along >= 0) & (along <= L) & (across <= B.HINGE["gap"] / 2 + TEXEL)
            top = np.where(gap, BOARD_BASE + s["t"] - B.HINGE["depth"], top).astype(np.float32)
            sid = np.where(gap, SURFACE_IDS.index(name), sid).astype(np.int16)
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        for name, d in sheets.items():
            s = B.SHEETS[name]
            write_exr(OUT / f"{name}.exr", {"R": d["rel"], "G": d["top"], "B": d["bottom"], "A": d["mask"].astype(np.float32)})
            W, H = s["size"]
            (OUT / f"{name}.json").write_text(json.dumps({
                "sheet": name, "ledger": s["ledger"], "tex": s["tex"], "size": [W, H], "centre": list(s["centre"]),
                "psi": s["psi"], "texel": TEXEL, "shape": list(d["rel"].shape), "rows": "row 0 at +v (the scan's top)",
                "extents": [list(c) for c in B.corners(s["centre"][0], s["centre"][1], W, H, s["psi"])],
                "thickness": s["t"], "layer": s["layer"], "margin_rgb_linear": margin_colour(name),
                "relief_min": float(d["rel"].min()),
                "relief_max": float(d["rel"].max()), "parts": d["parts"], "top_max": float(d["top"].max()),
                "units": "metres"}, indent=1), encoding="utf-8")
        np.savez_compressed(OUT / "world.npz", top=top, sid=sid, x0=WORLD["x0"], y0=WORLD["y0"], texel=TEXEL,
                            surfaces=np.array(SURFACE_IDS))
    return top, sid, sheets


def margin_colour(name):
    """The median colour (linear) of the scan's opaque pixels within 3% of its outline (or its border band): the
    plain fibre colour of the sheet's thickness faces and backing, the method run_scene.CLAY uses."""
    from PIL import Image
    from scipy.ndimage import binary_erosion
    s = B.SHEETS[name]
    alpha = bool(s.get("alpha"))
    im = Image.open(TEX / f"{s['tex']}{'.png' if alpha else '.jpg'}").convert("RGBA")
    im.thumbnail((600, 600))
    a = np.asarray(im, np.float32) / 255.0
    k = max(2, int(0.03 * max(a.shape[:2])))
    if alpha:
        m = a[..., 3] > 0.5
        ring = m & ~binary_erosion(m, iterations=k)
    else:
        ring = np.zeros(a.shape[:2], bool)
        ring[:k, :] = ring[-k:, :] = ring[:, :k] = ring[:, -k:] = True
    rgb = np.median(a[..., :3][ring], axis=0)
    return [float(((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92) for c in rgb]


def main():
    top, sid, sheets = compose()
    for n, d in sheets.items():
        print(f"{n:8s} relief {d['rel'].min() * 1e3:+6.2f}..{d['rel'].max() * 1e3:5.2f} mm  top max {d['top'].max() * 1e3:5.2f} mm  "
              + " ".join(f"{k} {a * 1e3:+.2f}..{b * 1e3:.2f}" for k, (a, b) in d["parts"].items()))
    print("world", top.shape, f"max {top.max() * 1e3:.2f} mm", "nan" if np.isnan(top).any() else "no nan")


if __name__ == "__main__":
    main()
