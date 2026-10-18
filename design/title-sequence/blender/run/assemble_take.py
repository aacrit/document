"""The Run: assemble the title from the Blender frames, the record's scan and the engine's own pieces.

    python design/title-sequence/blender/run/assemble_take.py --record C20-METAR-0851 --fps 24 --size 640x360 \
        --prefix <dir> --tail <dir> --audio <review wav> --mp4 <out> [--keep <comp dir>]

Timeline (title seconds; the design's frame numbers are 24 fps and convert as t = f / 24): black until the lamp
comes up (f36); the shared prefix's frames; the film's tail frames (approach, the light closing); then the 24-frame
dissolve from the lit model's last frame to the flat ledger scan at the matching crop (the crop the camera's last
pose sees of the record); the A41 tour on `rostrum`, from that crop out to the largest 16:9 crop of the sheet,
centred (end-pose rule); the 0.75 s dip; the lockup (120 frames, v1's assembly: `void document · As It Was`, corners
on `drift`, ember). Marks burned in: DRAWN from the open, the record's class label as the tour comes to rest (the
first amber), CARD from the dip; the watermark as v1.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))
from studio.engine import motion as M  # noqa: E402
import bench as B  # noqa: E402
import camera_run as CR  # noqa: E402

SIM = Path("D:/document-media/title-sequence/run/sim/v4")
MAN = json.loads(Path("D:/document-media/title-sequence/chart/tex-manifest.json").read_text(encoding="utf-8"))
DIP = 0.75


def fps_of(s):
    return (30000, 1001) if s in ("30000/1001", "29.97") else (int(s), 1)


def crop_from_camera(rec, cam_rows, t, img_size):
    """The record-scan rectangle (px, left top right bottom) the camera sees at title second t (top-down)."""
    tb = json.loads((SIM / f"run-tail-{rec}-bake.json").read_text(encoding="utf-8"))
    r = tb["meta"]["record"]
    pose = CR.at(cam_rows, t)
    w, h = img_size
    pts = []
    for px, py in ((0, 0), (1920, 1080)):
        g = CR.ray_to_bench(pose, px, py, z=r["z"])
        if r.get("upright", True):
            u = (g[0] - r["x0"]) / r["W"]
            v_top = ((r["y"] + r["H"] / 2) - g[1]) / r["H"]
        else:
            # turned 90 degrees: the image's width along +y, its top toward -x
            u = (g[1] - (r["y"] - r["H"] / 2)) / r["H"]
            v_top = (g[0] - r["x0"]) / r["W"]
        pts.append((u * w, v_top * h))
    (x0, y0), (x1, y1) = pts
    c = [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]
    # A41: nothing but the scan inside the frame. If the camera's last pose saw past the sheet's edge, the matching
    # crop is moved (and if need be shrunk, keeping 16:9) to lie inside the scan; the shift is logged
    cw, ch = c[2] - c[0], c[3] - c[1]
    k = min(1.0, w / cw, h / ch)
    cw, ch = cw * k, ch * k
    cx, cy = (c[0] + c[2]) / 2, (c[1] + c[3]) / 2
    cx = min(max(cx, cw / 2), w - cw / 2)
    cy = min(max(cy, ch / 2), h - ch / 2)
    return [cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2]


def final_crop(w, h):
    """The largest 16:9 crop of the sheet, centred across; a sheet taller than 16:9 shows its full width and its top
    (the identifying region: masthead, title block), a wider one its full height, centred."""
    if w / h >= 16 / 9:
        cw = h * 16 / 9
        return [(w - cw) / 2, 0.0, (w + cw) / 2, float(h)]
    ch = w * 9 / 16
    return [0.0, 0.0, float(w), ch]


def lockup(W, H, t, t_dip, t_end, fonts):
    """v1's lockup (design/title-sequence/blender/assemble.py), in seconds from this title's own dip."""
    L = M.Layout(W, H)
    base = Image.new("RGBA", (W, H), M.PALETTE["black"] + (255,))
    px = L.px(5.6)
    f_v, f_d, f_i = M._font(fonts.data, px), M._font(fonts.display, px), M._font(fonts.display_italic, px)
    sp = 0.45 * px
    ring_d = 2 * M.LOGOMARK_RING[1] / 24.0 * px
    words = [("void", f_v), ("document", f_d), ("·", f_d), ("As It Was", f_i)]
    widths = [f.getlength(s) for s, f in words]
    total = px + ring_d + sum(widths) + 3 * sp
    x0 = (W - total) / 2
    baseline = H / 2 + 0.33 * px
    t_in = t_dip + DIP / 2
    k_out = 1.0 - M.ease_in_quad((t - (t_end - 16 / 24)) / (16 / 24)) if t > t_end - 16 / 24 else 1.0
    p = M.DRIFT.progress(t - t_in) if t >= t_in else 0.0
    if p > 0:
        box = round(px * 24 / 17)
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


def timeline(rec, fps):
    F = B.FILMS[rec]
    a, dsc, c, d, tour = F["tail"]                       # find, descend, close, dissolve, tour (v4)
    s = lambda f: f / 24.0  # noqa: E731
    P = B.PREFIX_FRAMES
    T = {"lamp": s(36), "tail0": s(P), "close0": s(P + a + dsc), "dis0": s(P + a + dsc + c),
         "tour0": s(P + a + dsc + c + d), "dip": s(P + a + dsc + c + d + tour), "end": s(B.total_frames(rec))}
    T["rest"] = T["dip"] - 0.6                            # the tour has come to rest: the class label surfaces
    n = B.frames_at(T["end"], fps)
    return T, n


def handover(audio, T, fps):
    """The clean rule's join (design section 7): the room stem is one continuous recording, never faded, and the film's
    take continues it at the sample where the title ends (a butt join, no crossfade). Asserted here: the room stem's
    level over the title's last second is -72 +- 1 dBFS, and nothing in the review mix from the lockup's first frame
    to the end exceeds -60 dBFS (the last decay is gone)."""
    from scipy.io import wavfile
    import clean as CL
    sr, x = wavfile.read(audio)
    x = (x.astype(np.float64) / 32768.0).mean(1) if x.ndim > 1 else x.astype(np.float64) / 32768.0
    room_p = Path(audio).with_name("title.room.wav")
    _, rm = wavfile.read(room_p)
    rm = (rm.astype(np.float64) / 32768.0).mean(1) if rm.ndim > 1 else rm.astype(np.float64) / 32768.0
    n_end = int(round(T["end"] * sr))
    last = rm[max(0, n_end - sr):n_end]
    room_db = 20 * np.log10(np.sqrt((last ** 2).mean()) + 1e-20)
    k0 = int(round((T["dip"] + 1.5) * sr))                   # the lockup's first full frame
    tail = x[k0:n_end]
    peak_db = 20 * np.log10(np.abs(tail).max() + 1e-20) if len(tail) else -200.0
    assert abs(room_db - CL.C["ROOM_TONE_DBFS"]) <= 1.0, f"room at the join is {room_db:.1f} dBFS, not -72 +- 1"
    assert peak_db <= -60.0, f"the review mix peaks at {peak_db:.1f} dBFS after the lockup's first frame"
    return {"room_dbfs_last_s": round(room_db, 2), "peak_after_lockup_dbfs": round(peak_db, 2), "join_sample": n_end,
            "room": "clean.room_bed(n, 'the-run'): the film's take continues it at join_sample, butt-joined"}


def assemble_stretch(a, fpsv, W, H):
    """The working stretch only (milestone A, reduced): black until the lamp comes up (f36), then the prefix's frames,
    the DRAWN mark with its own A42 label from the open, the watermark; encoded with the review mix."""
    fps = fpsv[0] / fpsv[1]
    fonts = M.Fonts()
    shots = [{"start": 0.0, "cls": "DRAWN", "label": "Drawn · from period records"}]
    pre = Path(a.prefix)
    out_dir = Path(a.keep) if a.keep else pre.parent / f"comp-stretch-{W}"
    out_dir.mkdir(parents=True, exist_ok=True)
    n = a.end_frame + 1
    for f in range(n):
        t = f / fps
        if True:                                   # one take from f0: no black open (founder, physics only)
            src_dir = pre if (not a.tail or f < B.PREFIX_FRAMES) else Path(a.tail)
            pic = Image.open(src_dir / f"{f:04d}.png").convert("RGB")
            if pic.size != (W, H):
                pic = pic.resize((W, H), Image.LANCZOS)
        img = M.watermark(pic, t, start=0.0, card_spans=[], fonts=fonts)
        img = M.mark_frame(img, t, shots, fonts)
        img.convert("RGB").save(out_dir / f"{f:04d}.png", compress_level=1)
    rate = f"{fpsv[0]}/{fpsv[1]}"
    cmd = ["ffmpeg", "-y", "-v", "error", "-framerate", rate, "-i", str(out_dir / "%04d.png")]
    if a.audio:
        cmd += ["-i", a.audio, "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-r", rate,
            a.mp4]
    subprocess.run(cmd, check=True)
    print("ASSEMBLED " + json.dumps({"frames": n, "fps": a.fps, "mp4": a.mp4, "marks": [{"frame": 0, "cls": "DRAWN"}],
                                     "denoise": False, "renderer": a.renderer}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", default="C20-METAR-0851")
    ap.add_argument("--fps", default="24")
    ap.add_argument("--size", default="640x360")
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--tail", default="")
    ap.add_argument("--audio")
    ap.add_argument("--mp4")
    ap.add_argument("--keep", help="write the composited PNGs here")
    ap.add_argument("--master", help="lossless FFV1 .mkv at this path")
    ap.add_argument("--end-frame", type=int, default=0, help="the working stretch only (no tail)")
    ap.add_argument("--renderer", default="", help="the build's renderer line (RUN-BUILD), for the master item")
    a = ap.parse_args()
    fpsv = fps_of(a.fps)
    if a.end_frame:
        W, H = (int(x) for x in a.size.split("x"))
        return assemble_stretch(a, fpsv, W, H)
    fps = fpsv[0] / fpsv[1]
    W, H = (int(x) for x in a.size.split("x"))
    rec = a.record
    F = B.FILMS[rec]
    T, n = timeline(rec, fps)
    cam = json.loads((SIM / f"camera-{rec}.json").read_text(encoding="utf-8"))["rows"]
    src = Image.open(MAN[F["tex"]]["tex"]["file"]).convert("RGB")
    c0 = crop_from_camera(rec, cam, T["dis0"] - 1e-3, src.size)
    c1 = final_crop(*src.size)
    fonts = M.Fonts()
    shots = [{"start": 0.0, "cls": "DRAWN", "label": "Drawn · from period records"},
             {"start": T["rest"], "cls": F["cls"], "label": F["label"]},
             {"start": T["dip"], "cls": "CARD", "label": ""}]
    pre, tail = Path(a.prefix), Path(a.tail)
    out_dir = Path(a.keep) if a.keep else pre.parent / f"comp-{rec}-{a.fps.replace('/', '_')}-{W}"
    out_dir.mkdir(parents=True, exist_ok=True)
    last3d = None
    f_dis0 = int(np.ceil(T["dis0"] * fps - 1e-6))
    info = {"denoise": False, "renderer": a.renderer,
            "crop_close_end": [round(v, 1) for v in c0], "crop_final": [round(v, 1) for v in c1], "frames": n,
            "fps": a.fps, "marks": [], "record_frames": None, "dip": None, "lockup_frame": None}
    for f in range(n):
        t = f / fps
        if t < T["lamp"] - 1e-9:
            pic = Image.new("RGB", (W, H), (0, 0, 0))
        elif t < T["dis0"] - 1e-9:
            d = pre if t < T["tail0"] - 1e-9 else tail
            p = d / f"{f:04d}.png"
            pic = Image.open(p).convert("RGB")
            if pic.size != (W, H):
                pic = pic.resize((W, H), Image.LANCZOS)
            last3d = pic
        elif t < T["dip"] + DIP / 2:
            if t < T["tour0"]:
                u = (t - T["dis0"]) / (T["tour0"] - T["dis0"])
                k = M.dissolve_weight(t - T["dis0"], T["tour0"] - T["dis0"]) if hasattr(M, "dissolve_weight") else u
                scan = src.crop(tuple(int(round(v)) for v in c0)).resize((W, H), Image.LANCZOS)
                base3d = last3d if last3d is not None else scan
                pic = Image.blend(base3d, scan, float(min(max(k, 0.0), 1.0)))
            else:
                p_ = M.rostrum(min(t - T["tour0"], T["dip"] - T["tour0"]), T["dip"] - T["tour0"])
                c = [c0[i] + (c1[i] - c0[i]) * p_ for i in range(4)]
                pic = src.crop(tuple(int(round(v)) for v in c)).resize((W, H), Image.LANCZOS)
        else:
            pic = lockup(W, H, t, T["dip"], T["end"], fonts).convert("RGB")
        if T["dip"] - DIP / 2 <= t < T["dip"] + DIP / 2:
            if t >= T["dip"]:
                pic = lockup(W, H, t, T["dip"], T["end"], fonts).convert("RGB")
            lvl = M.dip_level(t - (T["dip"] - DIP / 2), DIP, fps=fps)
            pic = Image.blend(Image.new("RGB", (W, H), (0, 0, 0)), pic, lvl)
        img = M.watermark(pic, t, start=0.0, card_spans=[(T["dip"], T["end"] + 1)], fonts=fonts)
        img = M.mark_frame(img, t, shots, fonts)
        img.convert("RGB").save(out_dir / f"{f:04d}.png", compress_level=1)
    info["marks"] = [{"frame": 0, "cls": "DRAWN", "label": shots[0]["label"]},
                     {"frame": int(np.ceil(T["rest"] * fps - 1e-6)), "cls": F["cls"], "label": F["label"]},
                     {"frame": int(np.ceil(T["dip"] * fps - 1e-6)), "cls": "CARD"}]
    info["record_frames"] = [f_dis0, int(np.ceil((T["dip"] - DIP / 2) * fps - 1e-6)) - 1]
    info["dip"] = {"centre_frame": int(round(T["dip"] * fps)), "s": DIP}
    info["lockup_frame"] = int(round((T["dip"] + 1.5) * fps))
    info["handover"] = handover(a.audio, T, fps) if a.audio else None
    (out_dir / "assembly.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    rate = f"{fpsv[0]}/{fpsv[1]}"
    if a.mp4:
        cmd = ["ffmpeg", "-y", "-v", "error", "-framerate", rate, "-i", str(out_dir / "%04d.png")]
        if a.audio:
            cmd += ["-i", a.audio, "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest"]
        cmd += ["-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", "-profile:v", "high",
                "-movflags", "+faststart", "-r", rate, a.mp4]
        subprocess.run(cmd, check=True)
    if a.master:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-framerate", rate, "-i", str(out_dir / "%04d.png"),
                        "-c:v", "ffv1", "-level", "3", "-g", "1", "-slicecrc", "1", "-pix_fmt", "bgr0",
                        "-color_primaries", "bt709", "-color_trc", "iec61966-2-1", "-colorspace", "rgb", a.master], check=True)
    print("ASSEMBLED " + json.dumps(info))


if __name__ == "__main__":
    main()
