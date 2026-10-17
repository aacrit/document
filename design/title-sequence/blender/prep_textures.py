"""Prepare the title sequence's textures from the ledger's originals. Deterministic; no generative model.

    python design/title-sequence/blender/prep_textures.py          # full set (long edge <= 8192) and lite set (<= 2048)

Every output is a crop, a resize, an alpha key of a plain photographic background, or a studio-drawn map
derived from what the sheet itself prints (relief from a sheet's painted hills, the glint path along Ino's
printed red line, the typed page's reveal order). Each output is written to tex/ (full) and tex-lite/ (lite)
under D:/document-media/title-sequence/, and listed in tex-manifest.json with the ledger id it comes from,
the operation, and its sha256. build_scene.py refuses any image that is not in this manifest.
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

Image.MAX_IMAGE_PIXELS = None
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LEDGER = json.loads((HERE.parent / "assets-ledger.json").read_text(encoding="utf-8"))
ORIG = {i["id"]: Path(i["original"]) for i in LEDGER["items"] if i.get("original")}
MEDIA = Path(LEDGER["media_root"])
FULL, LITE = MEDIA / "tex", MEDIA / "tex-lite"
FULL_MAX, LITE_MAX = 8192, 2048
MANIFEST: dict[str, dict] = {}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(name: str, img: Image.Image, src: str, op: str, cls: str = "archive", full_max: int = FULL_MAX,
         lite_max: int = LITE_MAX, fmt: str | None = None) -> None:
    """Write the full and lite versions (never upscaled) and record them."""
    fmt = fmt or ("png" if img.mode in ("RGBA", "LA", "I;16", "L") else "jpg")
    for root, cap in ((FULL, full_max), (LITE, lite_max)):
        root.mkdir(parents=True, exist_ok=True)
        im = img
        if max(im.size) > cap:
            k = cap / max(im.size)
            im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
        p = root / f"{name}.{fmt}"
        if fmt == "jpg":
            im.convert("RGB").save(p, quality=93, subsampling=0)
        else:
            im.save(p, optimize=False)
        MANIFEST.setdefault(name, {"from": src, "op": op, "class": cls})[root.name] = {
            "file": str(p).replace("\\", "/"), "size": list(im.size), "sha256": sha(p)}
    print(f"  {name}: {img.size} <- {src} ({op})", flush=True)


def load(tid: str, max_px: int | None = None) -> Image.Image:
    im = Image.open(ORIG[tid])
    if max_px and max(im.size) > max_px:
        im.draft("RGB", (max_px, max_px))
    return im.convert("RGB")


def key_background(rgb: np.ndarray, bg: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Alpha from colour distance to a plain photographic background (a key, not a paint-over)."""
    d = np.sqrt(((rgb.astype(np.float32) - bg) ** 2).sum(-1))
    return np.clip((d - lo) / (hi - lo), 0, 1)


def soft(mask: np.ndarray, radius: float) -> np.ndarray:
    im = Image.fromarray((np.clip(mask, 0, 1) * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius))
    return np.asarray(im, np.float32) / 255.0


def height16(h: np.ndarray) -> Image.Image:
    return Image.fromarray((np.clip(h, 0, 1) * 65535).astype(np.uint16), "I;16")


# ---------------------------------------------------------------------------------------------------------


def clay() -> None:
    im = load("T-01")   # the Walters composite: obverse with four edges around it, reverse below (1066 x 1800)
    for name, box in {"T-01_obverse": (172, 172, 860, 876), "T-01_reverse": (207, 1052, 833, 1783),
                      "T-01_edge_top": (167, 32, 873, 143), "T-01_edge_bottom": (167, 902, 873, 1010),
                      "T-01_edge_left": (37, 172, 148, 883), "T-01_edge_right": (887, 167, 998, 878)}.items():
        save(name, im.crop(box), "T-01", f"crop {box}")


def papyrus() -> None:
    im = load("T-02a")
    a = np.asarray(im)
    corners = np.concatenate([a[:40, :40].reshape(-1, 3), a[-40:, -40:].reshape(-1, 3), a[:40, -40:].reshape(-1, 3)])
    bg = np.median(corners, 0)
    alpha = key_background(a, bg, 14, 34)
    alpha = soft(alpha, 1.2)
    alpha = np.clip((alpha - 0.35) / 0.3, 0, 1)        # a firm edge: no half-transparent grey to dither
    rgba = np.dstack([a, (alpha * 255).astype(np.uint8)])
    save("T-02a_keyed", Image.fromarray(rgba, "RGBA"), "T-02a", f"alpha key of the grey photographic background {bg.round().tolist()}")
    # H-02: the scribe's painted hills are pink-red washes; height = that pigment's strength, softened. Drawn from T-02a.
    small = np.asarray(im.resize((im.width // 4, im.height // 4), Image.LANCZOS), np.float32)
    r, g, b = small[..., 0], small[..., 1], small[..., 2]
    # the hills are painted pink, about (200, 139, 110): red stands about 60 above green; the bare papyrus is
    # about 30 above, and its dark patches are darker than the paint (mean under 140)
    pink = np.clip(((r - g) - 42) / 14, 0, 1) * np.clip((s.mean(-1) - 138) / 12, 0, 1) if False else         np.clip(((r - g) - 42) / 14, 0, 1) * np.clip((small.mean(-1) - 138) / 12, 0, 1)
    pink *= soft(key_background(small.astype(np.uint8), bg, 14, 34), 1)
    h = soft(pink, 6) * 0.7 + soft(pink, 2) * 0.3
    save("H-02", height16(h / max(h.max(), 1e-6)), "T-02a", "relief drawn from the painted pink hills (pigment strength, blurred)",
         cls="drawn", full_max=4096, lite_max=1024)


def atlas() -> None:
    im = load("T-03")
    a = np.asarray(im.convert("L"), np.float32)
    rows = a.mean(1)
    body = np.where(rows < 226)[0]
    y0, y1 = int(body[0]), int(body[-1])
    # four map leaves, each folded at its middle; board seams measured on the master (column darkness)
    for k, (x0, x1) in enumerate([(131, 2859), (3091, 5851), (5939, 8811), (8983, 11595)]):
        save(f"T-03_board{k}", im.crop((x0, y0, x1, y1)), "T-03", f"crop board {k}: x {x0}..{x1}, y {y0}..{y1}",
             full_max=4096, lite_max=1024)


def piri() -> None:
    im = load("T-04")
    a = np.asarray(im)
    alpha = soft(key_background(a, np.array([255, 255, 255], np.float32), 10, 30), 1.0)
    alpha = np.clip((alpha - 0.35) / 0.3, 0, 1)
    save("T-04_keyed", Image.fromarray(np.dstack([a, (alpha * 255).astype(np.uint8)]), "RGBA"), "T-04",
         "alpha key of the white photographic background")


def khipu_palette() -> None:
    """Cord colours sampled from T-05 (the cords are dark on a beige mount): median of the darkest pixels."""
    im = load("T-05", 1500)
    a = np.asarray(im, np.float32).reshape(-1, 3)
    lum = a.mean(1)
    mount = np.median(lum)
    cords = a[(lum < mount - 35) & (lum > mount - 120)]          # fibre, not the beige mount and not its deepest shadow
    cols = np.percentile(cords, [25, 50, 75], axis=0).round().astype(int).tolist()
    MANIFEST["T-05_palette"] = {"from": "T-05", "op": "cord colour quartiles (sRGB) of pixels 35 to 120 levels darker than the mount's median",
                                "class": "archive", "values": cols}
    print(f"  T-05_palette: {cols}")


def press() -> None:
    save("T-06_leaf", load("T-06"), "T-06", "whole leaf")


def ino() -> None:
    im = load("T-08")
    save("T-08_sheet", im, "T-08", "whole sheet")
    small = im.resize((im.width // 8, im.height // 8), Image.LANCZOS)
    s = np.asarray(small, np.float32)
    r, g, b = s[..., 0], s[..., 1], s[..., 2]
    # H-08: Ino's pictorial mountains are blue-green washes beside the coast; height = that wash's strength.
    wash = np.clip(((g + b) / 2 - r + 6) / 22, 0, 1) * np.clip((230 - s.mean(-1)) / 50, 0, 1)
    h = soft(wash, 5) * 0.6 + soft(wash, 1.5) * 0.4
    save("H-08", height16(h / max(h.max(), 1e-6)), "T-08", "relief drawn from the blue-green pictorial mountains (wash strength, blurred)",
         cls="drawn", full_max=2048, lite_max=1024)
    # The glint path: the printed red traverse line, as the longest geodesic path through its largest connected run.
    red = (r - (g + b) / 2 > 28) & (r > 120)
    path = longest_path(red)
    # Ino's sheet also prints straight red bearing lines to distant peaks; the glint walks the traverse, which bends
    # with the coast: keep the longest run of the path that is not straight over 30 px (chord / arc < 0.985).
    P = np.array(path, np.float32)
    k = 15
    curvy = np.zeros(len(P), bool)
    for i in range(k, len(P) - k):
        arc = np.linalg.norm(np.diff(P[i - k:i + k + 1], axis=0), axis=1).sum()
        curvy[i] = np.linalg.norm(P[i + k] - P[i - k]) / max(arc, 1e-6) < 0.985
    runs, start = [], None
    for i, c in enumerate(list(curvy) + [False]):
        if c and start is None:
            start = i
        elif not c and start is not None:
            runs.append((start, i)); start = None
    # join runs separated by short straight bits (a coast has short straight reaches)
    merged = []
    for a, b in runs:
        if merged and a - merged[-1][1] < 25:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    a, b = max(merged, key=lambda r: r[1] - r[0])
    seg = path[a:b]
    W, H = small.size
    pts = [[round(x / W, 5), round(y / H, 5)] for (y, x) in seg[:: max(1, len(seg) // 300)]]
    MANIFEST["T-08_redline"] = {"from": "T-08", "class": "drawn",
                                "op": f"red pixels (r - (g+b)/2 > 28) at 1/8 scale; largest 8-connected run; longest geodesic path; "
                                      f"its longest bending run (the coastal traverse, not the straight bearing lines): {len(pts)} points (uv, y down)",
                                "points": pts}
    print(f"  T-08_redline: {len(path)} px, {len(pts)} points")


def longest_path(mask: np.ndarray) -> list[tuple[int, int]]:
    H, W = mask.shape
    lab = -np.ones(mask.shape, np.int32)
    comps = []
    nb = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    for y, x in zip(*np.nonzero(mask)):
        if lab[y, x] >= 0:
            continue
        q = deque([(y, x)]); lab[y, x] = len(comps); members = []
        while q:
            cy, cx = q.popleft(); members.append((cy, cx))
            for dy, dx in nb:
                ny, nx = cy + dy, cx + dx
                if 0 <= ny < H and 0 <= nx < W and mask[ny, nx] and lab[ny, nx] < 0:
                    lab[ny, nx] = len(comps); q.append((ny, nx))
        comps.append(members)
    comp = max(comps, key=len)
    cid = lab[comp[0]]

    def bfs(start):
        dist = {start: 0}; par = {start: None}; q = deque([start]); last = start
        while q:
            c = q.popleft(); last = c
            for dy, dx in nb:
                n = (c[0] + dy, c[1] + dx)
                if 0 <= n[0] < H and 0 <= n[1] < W and lab[n] == cid and n not in dist:
                    dist[n] = dist[c] + 1; par[n] = c; q.append(n)
        return last, par
    a, _ = bfs(comp[0])
    b, par = bfs(a)
    out = []; c = b
    while c is not None:
        out.append(c); c = par[c]
    return out


def tape() -> None:
    im = Image.open(ORIG["T-09"]).convert("RGB")
    band = im.crop((0, 704, im.width, 1600))
    g = np.asarray(band.convert("L").resize((band.width // 8, band.height // 8)), np.float32)
    # the tape is darker than its white mount and lighter than the frame: the longest run of tape-tone columns
    mid = g[int(g.shape[0] * 0.25):int(g.shape[0] * 0.75)]
    tone = (mid.mean(0) > 150) & (mid.mean(0) < 208)
    best, run, start = (0, 0), 0, 0
    for i, v in enumerate(list(tone) + [False]):
        if v and run == 0:
            start = i
        run = run + 1 if v else 0
        if run > best[1] - best[0]:
            best = (start, i + 1)
    x0, x1 = best[0] * 8, best[1] * 8
    rows = g[:, best[0]:best[1]].mean(1)
    on = np.where(rows < 208)[0]
    y0, y1 = 704 + int(on[0]) * 8, 704 + int(on[-1]) * 8 + 8
    box = (x0, y0, x1, y1)
    save("T-09_tape", im.crop(box), "T-09", f"crop of the tape (and Morse's line above it) out of its mount: {box}")


def promio() -> None:
    """96 consecutive distinct frames of Promio's film, in order, on a 4 x 24 atlas (cells 384 x 288)."""
    tmp = MEDIA / "work" / "promio"
    tmp.mkdir(parents=True, exist_ok=True)
    for f in tmp.glob("*.png"):
        f.unlink()
    subprocess.run(["ffmpeg", "-v", "error", "-ss", "4", "-i", str(ORIG["T-16"]), "-vf", "mpdecimate,setpts=N/TB,scale=384:288",
                    "-fps_mode", "vfr", "-frames:v", "96", str(tmp / "f%03d.png")], check=True)
    frames = sorted(tmp.glob("f*.png"))
    atlas = Image.new("RGB", (4 * 384, 24 * 288))
    for k, f in enumerate(frames[:96]):
        atlas.paste(Image.open(f).convert("RGB"), ((k % 4) * 384, (k // 4) * 288))
    save("T-16_atlas", atlas, "T-16", f"{len(frames)} consecutive distinct frames from 4 s (ffmpeg mpdecimate), 384 x 288 each, row-major 4 x 24",
         full_max=8192, lite_max=8192)


def typed_page() -> None:
    im = load("T-18")
    gray = np.asarray(im.convert("L"), np.float32)
    paper_level = np.percentile(gray, 70)
    ink = gray < paper_level - 45
    # the paper without its ink: ink pixels replaced by the local paper, then a wide median
    small = Image.fromarray(np.where(ink, paper_level, gray).astype(np.uint8)).filter(ImageFilter.MedianFilter(9))
    rgb = np.asarray(im, np.float32)
    ratio = rgb / np.maximum(gray[..., None], 1)
    paper = np.clip(np.asarray(small, np.float32)[..., None] * ratio.mean((0, 1)), 0, 255).astype(np.uint8)
    paper = Image.fromarray(np.where(ink[..., None], paper, rgb.astype(np.uint8)))
    paper = paper.filter(ImageFilter.MedianFilter(5))
    save("T-18_page", im, "T-18", "whole page")
    save("T-18_paper", paper, "T-18", "the page with its ink replaced by the surrounding paper (median), for the reveal")
    # reveal order: lines by row projection, characters by the typewriter's fixed pitch within each line
    rows = ink.mean(1)
    lines, inside = [], False
    for y, v in enumerate(rows > 0.004):
        if v and not inside:
            start, inside = y, True
        elif not v and inside:
            if y - start > 12:
                lines.append((start, y))
            inside = False
    order = np.zeros(gray.shape, np.float32)
    n_chars = 0
    spans = []
    for (y0, y1) in lines:
        cols = ink[y0:y1].any(0)
        xs = np.nonzero(cols)[0]
        if len(xs) == 0:
            continue
        spans.append((y0, y1, int(xs[0]), int(xs[-1])))
    pitch = 25.0 * im.width / 3104      # elite/pica pitch measured on the scan (about 25 px a character at 3104 px)
    for (y0, y1, x0, x1) in spans:
        n = int(np.ceil((x1 - x0 + 1) / pitch))
        idx = np.clip(((np.arange(gray.shape[1]) - x0) / pitch).astype(int), 0, n - 1)
        seg = ink[max(0, y0 - 6):y1 + 6]
        o = (n_chars + idx + 1).astype(np.float32)
        order[max(0, y0 - 6):y1 + 6] = np.where(seg, o[None, :], 0)
        n_chars += n
    MANIFEST["T-18_lines"] = {"from": "T-18", "class": "drawn", "op": "line spans (y0, y1, x0, x1) and character pitch",
                              "lines": spans, "pitch_px": pitch, "chars": n_chars, "size": list(im.size)}
    dil = Image.fromarray((order / n_chars * 65535).astype(np.uint16), "I;16")
    save("M-18_order", dil, "T-18", f"reveal order: each ink pixel holds (its character's index) / {n_chars}, in reading order",
         cls="drawn", full_max=4096, lite_max=2048)


def rebbelib() -> None:
    im = load("T-19")
    a = np.asarray(im)
    corners = np.concatenate([a[:60, :60].reshape(-1, 3), a[-60:, :60].reshape(-1, 3), a[:60, -60:].reshape(-1, 3)])
    bg = np.median(corners, 0)
    alpha = soft(key_background(a, bg, 55, 95), 1.5)
    alpha = np.clip((alpha - 0.35) / 0.3, 0, 1)
    save("T-19_keyed", Image.fromarray(np.dstack([a, (alpha * 255).astype(np.uint8)]), "RGBA"), "T-19",
         f"alpha key of the dark blue photographic background {bg.round().tolist()}")


def chart() -> None:
    save("T-20_chart", load("T-20"), "T-20", "whole sheet")


def records() -> None:
    for rid, rec in LEDGER["records"].items():
        if rid.startswith("C20"):
            plate = metar_plate(rec)
            save(f"R-{rid}", plate, rid, "typeset DRAWN plate: the four 08:51 METAR rows, verbatim, in the house data face", cls="drawn",
                 full_max=4096, lite_max=2048)
        else:
            assert sha(Path(rec["file"])) == rec["sha256"], f"{rid}: the file differs from the ledger's sha256"
            im = Image.open(rec["file"]).convert("RGB")
            save(f"R-{rid}", im, rid, "the record as its film's ledger holds it (sha256 checked against the ledger)", full_max=8192, lite_max=2048)


def metar_plate(rec: dict) -> Image.Image:
    rows = {}
    with open(rec["file"], newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            key = f"{r['station']},{r['valid']}"
            if key in rec["rows"]:
                rows[key] = r["metar"]
    lines = [rows[k] for k in rec["rows"]]
    font = ImageFont.truetype(str(REPO / "node_modules/@fontsource/jetbrains-mono/files/jetbrains-mono-latin-500-normal.woff"), 64)
    W, H = 3840, 2160
    img = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    pitch = 120
    widths = [d.textlength(t, font=font) for t in lines]
    scale = min(1.0, (W * 0.86) / max(widths))
    if scale < 1.0:
        font = ImageFont.truetype(font.path, int(64 * scale)); pitch = int(pitch * scale)
    y = H / 2 - pitch * (len(lines) - 1) / 2
    x = (W - max(d.textlength(t, font=font) for t in lines)) / 2
    for t in lines:
        d.text((x, y), t, font=font, fill=(237, 226, 207), anchor="lm")
        y += pitch
    return img


def main() -> None:
    steps = [clay, papyrus, atlas, piri, khipu_palette, press, ino, tape, promio, typed_page, rebbelib, chart, records]
    only = sys.argv[1:]
    man_path = MEDIA / "tex-manifest.json"
    if only and man_path.exists():
        MANIFEST.update(json.loads(man_path.read_text(encoding="utf-8")))
    for s in steps:
        if not only or s.__name__ in only:
            print(s.__name__, flush=True)
            s()
    man_path.write_text(json.dumps(MANIFEST, indent=1), encoding="utf-8")
    print(f"manifest: {man_path} ({len(MANIFEST)} entries)")


if __name__ == "__main__":
    main()
