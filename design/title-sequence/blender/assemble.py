"""Assemble the title's 57 s from Blender's machine frames (0..1151) and the engine's own pieces: the provenance
mark and watermark (studio/engine/motion.py), the ARCHIVE hold of the film's record at the HOLD fit, the 0.75 s dip
and the CARD lockup. This is the engine-side picture of BLENDER-PLAN.md's delivery, for proofs and the animatic;
the engine's title_sequence slot replaces it when that ticket lands.

    python design/title-sequence/blender/assemble.py --frames <dir of 0000.png..1151.png> --record S-130 \
        --size 640x360 --mp4 <out.mp4>                     # the whole 57 s
    python design/title-sequence/blender/assemble.py --frames <dir> --record S-130 --size 1920x1080 \
        --still 36,432,852,1176,1308 --out <dir>           # single frames, marks burned in
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))
from studio.engine import motion as M  # noqa: E402

CFG = json.loads((HERE / "title.json").read_text(encoding="utf-8"))
MAN = json.loads((Path(CFG["paths"]["media"]) / "tex-manifest.json").read_text(encoding="utf-8"))
CORE = None
FPS, LAST, CUT = CFG["fps"], CFG["machine_last_frame"], CFG["cut_frame"]
T_CUT, T_DIP, DIP = CUT / FPS, 52.0, 0.75
T_END = CFG["frames"] / FPS


def hold_fit(img: Image.Image, W: int, H: int) -> Image.Image:
    """HOLD (GRAMMAR 7.2, A7): the whole picture, contained, pillarboxed or letterboxed on film black."""
    k = min(W / img.width, H / img.height)
    w, h = round(img.width * k), round(img.height * k)
    out = Image.new("RGB", (W, H), M.PALETTE["black"])
    out.paste(img.convert("RGB").resize((w, h), Image.LANCZOS), ((W - w) // 2, (H - h) // 2))
    return out


def lockup(W: int, H: int, t: float, fonts: M.Fonts) -> Image.Image:
    """`void document · As It Was` with the logomark, centred, 5.6% of frame height (60 px at 1080p)."""
    L = M.Layout(W, H)
    base = Image.new("RGBA", (W, H), M.PALETTE["black"] + (255,))
    px = L.px(5.6)
    f_v, f_d, f_i = M._font(fonts.data, px), M._font(fonts.display, px), M._font(fonts.display_italic, px)
    sp = 0.45 * px
    dot_w = f_d.getlength("·")
    ring_d = 2 * M.LOGOMARK_RING[1] / 24.0 * px            # one ring diameter of clear space
    words = [("void", f_v), ("document", f_d), ("·", f_d), ("As It Was", f_i)]
    widths = [f.getlength(s) for s, f in words]
    total = px + ring_d + sum(widths) + 3 * sp
    x0 = (W - total) / 2
    baseline = H / 2 + 0.33 * px
    t_in = T_DIP + DIP / 2                                  # 0:52.375, frame 1257
    k_out = 1.0 - M.ease_in_quad((t - (T_END - 16 / FPS)) / (16 / FPS)) if t > T_END - 16 / FPS else 1.0
    p = M.DRIFT.progress(t - t_in) if t >= t_in else 0.0
    if p > 0:
        box = round(px * 24 / 17)                            # the corners span 17 of the mark's 24 units: they match the type's height
        mark = M.draw_logomark(box, spread=0.08 * (1 - M.clamp01(p)), ember_alpha=M.clamp01((p - 0.9) / 0.1))
        mark = M._scale_alpha(mark, M.clamp01(p) * k_out)
        base.alpha_composite(mark, (round(x0 - (box - px) / 2), round(baseline - 0.33 * px - box / 2)))
    wp = M.SETTLE.progress(t - t_in - 0.4) if t >= t_in + 0.4 else 0.0
    if wp > 0:
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        x = x0 + px + ring_d
        for (s, f), w in zip(words, widths):
            d.text((x, baseline), s, font=f, fill=M._rgba(M.PALETTE["bone"], M.clamp01(wp) * k_out), anchor="ls")
            x += w + sp
        base.alpha_composite(M._shift(layer, (1 - M.clamp01(wp)) * L.h(0.6)))
    return base


def record_still(record: str, W: int, H: int) -> Image.Image:
    rec = CFG["records"][record]
    src = MAN[rec["tex"]]["tex"]["file"]
    return hold_fit(Image.open(src), W, H)


def frame(f: int, frames_dir: Path, record: str, W: int, H: int, fonts: M.Fonts, rec_img: Image.Image) -> Image.Image:
    t = f / FPS
    rec = CFG["records"][record]
    if f <= LAST:
        src = frames_dir / f"{f:04d}.png"
        if not src.exists() and CORE is not None:
            src = CORE / f"{f:04d}.png"          # the shared core (beats 1 to 10), rendered once for every film
        pic = Image.open(src).convert("RGB")
        if pic.size != (W, H):
            pic = pic.resize((W, H), Image.LANCZOS)
    elif t < T_DIP:
        pic = rec_img.copy()
    else:
        pic = lockup(W, H, t, fonts).convert("RGB")
    # the dip ARCHIVE -> CARD, 0.75 s centred on 0:52.00
    if T_DIP - DIP / 2 <= t < T_DIP + DIP / 2:
        lvl = M.dip_level(t - (T_DIP - DIP / 2), DIP)
        pic = Image.blend(Image.new("RGB", (W, H), (0, 0, 0)), pic, lvl)
    shots = [{"start": 0.0, "cls": "DRAWN", "label": "Drawn · from period records"},
             {"start": T_CUT, "cls": rec["cls"], "label": rec["label"]},
             {"start": T_DIP, "cls": "CARD", "label": ""}]
    out = M.watermark(pic, t, start=0.0, card_spans=[(T_DIP, T_END + 1)], fonts=fonts)
    out = M.mark_frame(out, t, shots, fonts)
    return out.convert("RGB")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", required=True)
    ap.add_argument("--record", default="S-130")
    ap.add_argument("--size", default="640x360")
    ap.add_argument("--mp4")
    ap.add_argument("--still")
    ap.add_argument("--out")
    ap.add_argument("--core", help="dir of the shared core frames (used where --frames lacks a frame)")
    ap.add_argument("--master", help="write the lossless intermediate (.mkv, FFV1 RGB) and a ProRes 422 HQ copy (.mov) at this stem")
    a = ap.parse_args()
    global CORE
    CORE = Path(a.core) if a.core else None
    W, H = (int(x) for x in a.size.split("x"))
    fonts = M.Fonts()
    rec_img = record_still(a.record, W, H)
    fd = Path(a.frames)
    if a.still:
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        for f in (int(x) for x in a.still.split(",")):
            frame(f, fd, a.record, W, H, fonts, rec_img).save(out / f"{a.record}_{f:04d}.png")
            print(f"still {f}")
        return
    tmp = fd.parent / f"{fd.name}-comp-{a.record}"
    tmp.mkdir(parents=True, exist_ok=True)
    for f in range(CFG["frames"]):
        frame(f, fd, a.record, W, H, fonts, rec_img).save(tmp / f"{f:04d}.png", compress_level=1)
    if a.mp4:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-framerate", str(FPS), "-i", str(tmp / "%04d.png"),
                        "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", "-movflags", "+faststart", a.mp4], check=True)
        print(f"animatic: {a.mp4}")
    if a.master:
        # lossless intermediate: FFV1 level 3, RGB (no chroma subsampling), the assembled frames bit for bit
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-framerate", str(FPS), "-i", str(tmp / "%04d.png"),
                        "-c:v", "ffv1", "-level", "3", "-g", "1", "-slicecrc", "1", "-pix_fmt", "bgr0",
                        "-color_primaries", "bt709", "-color_trc", "iec61966-2-1", "-colorspace", "rgb", a.master + ".mkv"], check=True)
        # ProRes 422 HQ, 10-bit 4:2:2, BT.709
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-framerate", str(FPS), "-i", str(tmp / "%04d.png"),
                        "-c:v", "prores_ks", "-profile:v", "3", "-vendor", "apl0", "-pix_fmt", "yuv422p10le",
                        "-vf", "scale=out_color_matrix=bt709:out_range=tv",
                        "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", a.master + ".mov"], check=True)
        print(f"master: {a.master}.mkv, {a.master}.mov")


if __name__ == "__main__":
    main()
