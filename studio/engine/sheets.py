"""Contact-sheet overlays (cinematography ticket #3): a PIL preview tool, no
render, no ffmpeg. It plans a film in memory (``render.build_plan``) and, for
every STILL shot (``archive_still``, ``drawn``), draws its first frame, each
resolved tour stop, and its last frame as 16:9 cells, cropped from the source
exactly as the camera window (``motion.still_view`` / ``motion.fit_still``,
through the same public camera resolver the renderer uses,
``overlays.framing_at``). Each cell carries the grid guides (thirds, phi),
the action- and graphics-safe borders, the house zones (``motion.LT``,
``motion.SUB``, ``motion.MARK_ZONE``, ``motion.MARK_GLYPH_ZONE``,
``motion.WM``, the single source for all of them), the plan's own ROI boxes
(colour-coded by ``source``: auto or human, A43), the stop's time, zoom and
``scale`` (whole, field or detail, derived from the window's share of the
picture), and a composition verdict (golden, centred or off; subject in
frame; under the lower third or the subtitle band).

Founder ruling (2026-10-17): the primary target is a 1080p screen (laptop or
TV); a phone is a sanity check only. Sheets are phone-viewable for
convenience (a page stays under PAGE_MAX_W), but framing is judged at full
frame, so every cell shows the true 16:9 window at a legible size.

One PNG per chapter (a screenplay part), a header (film, chapter, shot ids,
the plan's sha256) and one row per still; a chapter whose rows would not fit
one page (MAX_ROWS_PER_PAGE) splits into numbered pages. Nothing is written
into the film folder: the default output is ``D:/document-media/<slug>-sheets``.
Deterministic: fixed fonts, no timestamps drawn or embedded, so the same plan
gives byte-identical PNGs.

This is a preview tool, not a lint: it blocks nothing (GRAMMAR unchanged).

    python -m studio.engine.sheets <film dir> [--out <dir>] [--chapter <id>] [--skip-sound-lints]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from studio.engine import journal as J
from studio.engine import motion as M
from studio.engine import overlays as OV
from studio.engine import render as R
from studio.engine import tour as T

__all__ = ["build_sheets", "main"]

# --------------------------------------------------------------------------
# Layout (this tool's own numbers; not GRAMMAR).
# --------------------------------------------------------------------------

CELL_SIZES = [(640, 360), (480, 270), (384, 216), (320, 180)]   # tried largest first; "tight" falls back
PAGE_MAX_W = 2560
MAX_ROWS_PER_PAGE = 8
MARGIN = 28
GUTTER = 14
LABEL_H = 78                 # the caption strip under each cell: t/z, scale, verdict
HEADER_H = 108
ROW_LABEL_W = 220            # left column: shot id, class, mark, flags
BG = M.PALETTE["black"]
FG = M.PALETTE["bone"]

# House numbers this tool overlays (EBU R95 / SMPTE ST 2046-1, and the
# groundwork brief's thirds/phi/placement bands); none of these block.
THIRDS = (1 / 3, 2 / 3)
PHI = (0.382, 0.618)
ACTION_SAFE = 0.035
GRAPHICS_SAFE = 0.05
FRAMED_SHARE = M.CINE["framed_share"]        # 0.5: a box this much inside the window counts as framed
UNDER_TEXT_SHARE = 0.10                      # groundwork `subject-under-text` guide
WHOLE_SHARE, DETAIL_SHARE = 0.8, 0.4         # groundwork doctrine 2.2: WHOLE >= 0.8, DETAIL <= 0.4 of the picture


def _lt_zone_frac() -> tuple[float, float, float, float]:
    """An approximate lower-third box (fractions of the frame), from
    ``motion.LT``'s own row heights and gaps: the single source, no new
    numbers. A guide, not the exact text layout (``motion.lower_third_layout``
    draws that)."""
    LT = M.LT
    h = (LT["gap_flag"] + LT["name"] * LT["lh_name"] + LT["gap_role"] + LT["role"] * LT["lh_role"]
         + LT["gap_rule"] + LT["rule_h"] + LT["source"] * LT["lh_source"]) / 100.0
    y1 = LT["bottom"] / 100.0
    x0 = LT["x"] / 100.0
    return (x0, max(0.0, y1 - h), x0 + LT["max_w"] / 100.0, y1)


def _sub_zone_frac() -> tuple[float, float, float, float]:
    """The subtitle band (fractions of the frame), from ``motion.SUB``: up to
    2 lines (GRAMMAR 10), centred, ``max_w`` wide."""
    SUB = M.SUB
    h = 2 * SUB["size"] * SUB["lh"] / 100.0
    y1 = SUB["bottom"] / 100.0
    w = SUB["max_w"] / 100.0
    return ((1 - w) / 2.0, max(0.0, y1 - h), (1 + w) / 2.0, y1)


def _wm_zone_frac() -> tuple[float, float, float, float]:
    """The watermark box (fractions of the frame), from ``motion.WM``: a
    square ``box`` % of H, inset ``right`` % of W and ``top`` % of H; every
    delivery is 16:9 (A41), so its width share is its height share * 9/16."""
    WM = M.WM
    box_h = WM["box"] / 100.0
    box_w = box_h * 9.0 / 16.0
    x1 = 1.0 - WM["right"] / 100.0
    y0 = WM["top"] / 100.0
    return (x1 - box_w, y0, x1, y0 + box_h)


ZONES = {
    "LT": _lt_zone_frac(), "SUB": _sub_zone_frac(), "WM": _wm_zone_frac(),
    "MARK": tuple(M.MARK_ZONE), "GLYPH": tuple(M.MARK_GLYPH_ZONE),
}

# --------------------------------------------------------------------------
# Geometry: the plan's camera window, projected to frame space.
# --------------------------------------------------------------------------


def _area(b: tuple[float, float, float, float]) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _overlap_share(box, win) -> float:
    """The share of ``box``'s own area that lies inside ``win``."""
    a = _area(box)
    if a <= 0:
        return 0.0
    i = (max(box[0], win[0]), max(box[1], win[1]), min(box[2], win[2]), min(box[3], win[3]))
    return _area(i) / a


def project_box(box_frac, size, src, dst, L: "M.Layout") -> tuple[float, float, float, float]:
    """A picture-fraction box (``tour.roi_box``) through the same window
    (``src``, image pixels) and placement (``dst``, frame pixels) that
    ``motion.fit_still`` drew, to frame fractions. Outside [0, 1] when the
    region is outside the window."""
    iw, ih = size
    bx0, by0, bx1, by1 = box_frac
    px0, py0, px1, py1 = bx0 * iw, by0 * ih, bx1 * iw, by1 * ih
    sx0, sy0, sx1, sy1 = src
    sw, sh = (sx1 - sx0) or 1e-9, (sy1 - sy0) or 1e-9
    dx0, dy0, dx1, dy1 = dst
    dw, dh = dx1 - dx0, dy1 - dy0
    fx0 = dx0 + (px0 - sx0) / sw * dw
    fx1 = dx0 + (px1 - sx0) / sw * dw
    fy0 = dy0 + (py0 - sy0) / sh * dh
    fy1 = dy0 + (py1 - sy0) / sh * dh
    return (fx0 / L.W, fy0 / L.H, fx1 / L.W, fy1 / L.H)


def window_share(size, src) -> float:
    """The window's share of the whole picture (``tour`` doctrine 2.2:
    WHOLE >= 0.8, FIELD 0.4-0.8, DETAIL <= 0.4)."""
    iw, ih = size
    x0, y0, x1, y1 = src
    ix0, iy0 = max(0.0, x0), max(0.0, y0)
    ix1, iy1 = min(float(iw), x1), min(float(ih), y1)
    return max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0) / (iw * ih)


def scale_class(share: float) -> str:
    if share >= WHOLE_SHARE:
        return "whole"
    if share <= DETAIL_SHARE:
        return "detail"
    return "field"


def _axis_band(v: float) -> str:
    """Ratio's golden-band table (``rules.ts:36-51``, the groundwork brief's
    lift): golden 0.30-0.44 or 0.56-0.70, centred (halves) 0.44-0.56, else
    off (short or long)."""
    if 0.30 <= v < 0.44 or 0.56 <= v < 0.70:
        return "golden"
    if 0.44 <= v < 0.56:
        return "centred"
    return "off"


def compose_verdict(subject_frame_box) -> str:
    """golden, centred, off, or n/a (no subject: a whole hold makes no
    composition claim)."""
    if subject_frame_box is None:
        return "n/a"
    cx = (subject_frame_box[0] + subject_frame_box[2]) / 2.0
    cy = (subject_frame_box[1] + subject_frame_box[3]) / 2.0
    bx, by = _axis_band(cx), _axis_band(cy)
    if bx == "off" or by == "off":
        return "off"
    if bx == "golden" and by == "golden":
        return "golden"
    return "centred"


def subject_in_frame(subject_frame_box) -> bool | None:
    if subject_frame_box is None:
        return None
    return _overlap_share(subject_frame_box, (0.0, 0.0, 1.0, 1.0)) >= FRAMED_SHARE


def subject_under_text(subject_frame_box) -> bool | None:
    if subject_frame_box is None:
        return None
    return (_overlap_share(subject_frame_box, ZONES["LT"]) >= UNDER_TEXT_SHARE
            or _overlap_share(subject_frame_box, ZONES["SUB"]) >= UNDER_TEXT_SHARE)


def subject_box(cam: dict) -> tuple[tuple[float, float, float, float] | None, str | None, str | None]:
    """The still's subject (picture fractions), its source and its name:
    the ``roi`` named ``subject`` (A45), else every located person together,
    else None (the still is ``whole``, or a FIND or a fill-exception shot:
    neither carries ``cine``, since neither runs the TOUR preset)."""
    cine = cam.get("cine")
    if cine is None:
        return None, None, None
    sub = cine["regions"].get("subject")
    if sub is not None:
        box = T.roi_box(sub)
        if box is not None:
            return box, T.source_of(sub), "subject"
    persons = cine["persons"]
    boxes = [p["box"] for p in persons if p.get("box") is not None]
    if boxes:
        x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
        x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
        srcs = {T.source_of(p["entry"]) for p in persons}
        return (x0, y0, x1, y1), ("auto" if srcs == {"auto"} else "human"), "people"
    return None, None, None


def roi_boxes(cam: dict) -> list[tuple[tuple[float, float, float, float], str, str, str]]:
    """Every box the plan places the camera from: ``(box, source, name,
    kind)``, picture fractions. Persons first (named or not), then every
    other named region not already drawn as a person. Empty for a cam with
    no ``cine`` (FIND, or held whole under a fill exception)."""
    cine = cam.get("cine")
    if cine is None:
        return []
    out = []
    drawn = set()
    for p in cine["persons"]:
        box = p.get("box")
        if box is None:
            continue
        name = p.get("name")
        drawn.add(name)
        out.append((box, T.source_of(p["entry"]), name or "person", "person"))
    for name, r in cine["regions"].items():
        if name in drawn:
            continue
        box = T.roi_box(r)
        if box is None:
            continue
        out.append((box, T.source_of(r), name, r.get("kind") or "roi"))
    return out


def stop_times(cam: dict, dur: float) -> list[float]:
    """First frame, each resolved stop, last frame (shot-local seconds). A
    cam with no ``tour`` (FIND, or held whole under a fill exception) has no
    authored stops: its own path's ends stand in for "stop"."""
    tl = cam.get("tour")
    if tl is not None:
        ts = {0.0, round(float(dur), 6)} | {round(float(p["t"]), 6) for p in tl["stops"]}
    else:
        open_s = float(cam.get("open_s") or 0.0)
        move = cam.get("move_s") or max(dur - open_s, 0.0)
        ts = {0.0, round(open_s, 6), round(min(open_s + move, dur), 6), round(float(dur), 6)}
    return sorted(t for t in ts if -1e-6 <= t <= dur + 1e-6)


def stop_label(i: int, n: int) -> str:
    if n == 1:
        return "only"
    if i == 0:
        return "first"
    if i == n - 1:
        return "last"
    return f"stop {i}"


# --------------------------------------------------------------------------
# Drawing.
# --------------------------------------------------------------------------


@lru_cache(maxsize=64)
def _font(path: str, px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, max(1, int(px)))


def _rgba(rgb, a: float) -> tuple[int, int, int, int]:
    return (rgb[0], rgb[1], rgb[2], max(0, min(255, int(round(a * 255)))))


def _rect_px(frac, W: int, H: int) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = frac
    return (x0 * W, y0 * H, x1 * W, y1 * H)


def _dashed_line(d: ImageDraw.ImageDraw, p0, p1, fill, width: int = 1, dash: float = 6.0, gap: float = 4.0) -> None:
    x0, y0 = p0
    x1, y1 = p1
    length = math.hypot(x1 - x0, y1 - y0)
    if length <= 0:
        return
    ux, uy = (x1 - x0) / length, (y1 - y0) / length
    s = 0.0
    while s < length:
        e = min(s + dash, length)
        d.line([(x0 + ux * s, y0 + uy * s), (x0 + ux * e, y0 + uy * e)], fill=fill, width=width)
        s += dash + gap


def _dashed_rect(d: ImageDraw.ImageDraw, box, fill, width: int = 1, dash: float = 6.0, gap: float = 4.0) -> None:
    x0, y0, x1, y1 = box
    _dashed_line(d, (x0, y0), (x1, y0), fill, width, dash, gap)
    _dashed_line(d, (x1, y0), (x1, y1), fill, width, dash, gap)
    _dashed_line(d, (x1, y1), (x0, y1), fill, width, dash, gap)
    _dashed_line(d, (x0, y1), (x0, y0), fill, width, dash, gap)


def draw_grid(d: ImageDraw.ImageDraw, W: float, H: float) -> None:
    thirds, phi = _rgba(M.PALETTE["bone"], 0.26), _rgba(M.PALETTE["bone"], 0.42)
    for f in THIRDS:
        d.line([(f * W, 0), (f * W, H)], fill=thirds, width=1)
        d.line([(0, f * H), (W, f * H)], fill=thirds, width=1)
    for f in PHI:
        _dashed_line(d, (f * W, 0), (f * W, H), phi)
        _dashed_line(d, (0, f * H), (W, f * H), phi)
    action = _rgba(M.PALETTE["safelight"], 0.55)
    graphics = _rgba(M.PALETTE["cold"], 0.55)
    _dashed_rect(d, (ACTION_SAFE * W, ACTION_SAFE * H, (1 - ACTION_SAFE) * W, (1 - ACTION_SAFE) * H), action)
    _dashed_rect(d, (GRAPHICS_SAFE * W, GRAPHICS_SAFE * H, (1 - GRAPHICS_SAFE) * W, (1 - GRAPHICS_SAFE) * H), graphics)


def draw_zones(d: ImageDraw.ImageDraw, W: float, H: float, fonts_px: int) -> None:
    colour = _rgba(M.PALETTE["mark_text"], 0.55)
    f = _font(M.Fonts().data, max(1, fonts_px))
    for name, frac in ZONES.items():
        box = _rect_px(frac, W, H)
        _dashed_rect(d, box, colour, dash=4.0, gap=3.0)
        d.text((box[0] + 2, max(0.0, box[1] - fonts_px - 1)), name, font=f, fill=colour)


def draw_roi(d: ImageDraw.ImageDraw, box, colour, label: str, fonts_px: int) -> None:
    x0, y0, x1, y1 = box
    d.rectangle([(x0, y0), (x1, y1)], outline=colour, width=2)
    if label:
        f = _font(M.Fonts().structure, max(1, fonts_px))
        ly = y0 - fonts_px - 2 if y0 - fonts_px - 2 >= 0 else y1 + 2
        d.text((max(0.0, x0) + 2, ly), label, font=f, fill=colour)


def _yn(v: bool | None) -> str:
    return "n/a" if v is None else ("yes" if v else "no")


def draw_caption(d: ImageDraw.ImageDraw, x0: float, y0: float, t: float, z: float,
                 scale_cls: str, share: float, compose: str, in_frame: bool | None, under_text: bool | None) -> None:
    mono = _font(M.Fonts().data, 11)
    sans = _font(M.Fonts().structure, 11)
    fg = _rgba(FG, 0.92)
    d.text((x0, y0), f"t={t:05.2f}s  z={z:.2f}", font=mono, fill=fg)
    d.text((x0, y0 + 14), f"scale: {scale_cls} (share {share:.2f})", font=sans, fill=fg)
    d.text((x0, y0 + 28), f"compose: {compose}  subject in frame: {_yn(in_frame)}", font=sans, fill=fg)
    d.text((x0, y0 + 42), f"under LT/SUB: {_yn(under_text)}", font=sans, fill=fg)


def _clamp_box(box, w: float, h: float) -> tuple[float, float, float, float]:
    """A projected ROI box can land far outside the cell when the region is
    out of frame; PIL draws fine either way, but this keeps the coordinates
    sane (no inf or absurd floats from a degenerate window)."""
    lo_x, hi_x = -4.0 * w, 5.0 * w
    lo_y, hi_y = -4.0 * h, 5.0 * h
    x0, y0, x1, y1 = box
    return (min(max(x0, lo_x), hi_x), min(max(y0, lo_y), hi_y), min(max(x1, lo_x), hi_x), min(max(y1, lo_y), hi_y))


# --------------------------------------------------------------------------
# One still's row of cells.
# --------------------------------------------------------------------------


class _StillImage:
    """The still's source pixels, pre-scaled once to the deepest zoom any of
    its cells needs (the same ``fit_scale`` * ``z_max`` the renderer pre-scales
    to, ``render.Renderer.still``), reused for every cell of its row."""

    def __init__(self, path: str, cam: dict) -> None:
        img = Image.open(path).convert("RGB")
        self.size = img.size
        need = float(cam["fit_scale"]) * float(cam["z_max"])
        if need < 1.0:
            img = img.resize((max(2, math.ceil(img.width * need)), max(2, math.ceil(img.height * need))),
                             Image.Resampling.LANCZOS)
        self.img = img


def camera_crop(still: "_StillImage", cam: dict, t: float, dur: float, L: "M.Layout"):
    """The cell's picture, exactly as the renderer would draw it at shot
    time ``t``: the same public camera resolver (``overlays.framing_at``)
    and the same sampler (``motion.fit_still``, ``motion.still_view``) render
    frames with. Returns ``(pic, src, dst, framing)``; ``src`` and ``dst``
    are against ``still.size`` (the *original* image), for roi projection and
    the window share. ``still.img`` may be pre-scaled (resolution-independent:
    the same fractions, so the window matches)."""
    f = OV.framing_at(cam, t, dur)
    pic = M.fit_still(still.img, L, z=f["z"], cx=f["x"], cy=f["y"], clamp=cam["clamp"])
    src, dst = M.still_view(still.size, L, z=f["z"], cx=f["x"], cy=f["y"], clamp=cam["clamp"])
    return pic, src, dst, f


def render_cell(still: _StillImage, cam: dict, t: float, dur: float, cell_w: int, cell_h: int) -> Image.Image:
    """One 16:9 cell: the camera window at shot time ``t``, with every
    overlay drawn over it (thirds, phi, safe areas, the house zones, the
    plan's roi boxes), plus a caption strip below it (never on top of the
    picture, so every cell still shows the true full frame, per the
    founder's 2026-10-17 ruling)."""
    L = M.Layout(cell_w, cell_h)
    pic, src, dst, f = camera_crop(still, cam, t, dur, L)
    canvas = Image.new("RGBA", (cell_w, cell_h + LABEL_H), _rgba(BG, 1.0))
    canvas.paste(pic.convert("RGBA"), (0, 0))
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    draw_grid(d, cell_w, cell_h)
    draw_zones(d, cell_w, cell_h, max(8, cell_h // 36))
    sbox, _ssource, _sname = subject_box(cam)
    sframe = project_box(sbox, still.size, src, dst, L) if sbox is not None else None
    for box, source, name, kind in roi_boxes(cam):
        fbox = _clamp_box(_rect_px(project_box(box, still.size, src, dst, L), cell_w, cell_h), cell_w, cell_h)
        colour = _rgba(M.PALETTE["cold"], 0.9) if source == "auto" else _rgba(M.PALETTE["safelight"], 0.9)
        draw_roi(d, fbox, colour, f"{name} ({kind}, {source})", max(8, cell_h // 32))
    share = window_share(still.size, src)
    draw_caption(d, 6, cell_h + 4, t, f["z"], scale_class(share), share,
                compose_verdict(sframe), subject_in_frame(sframe), subject_under_text(sframe))
    return Image.alpha_composite(canvas, overlay)


# --------------------------------------------------------------------------
# One chapter's sheet (one or more numbered pages).
# --------------------------------------------------------------------------


def _cell_size_for(max_cells: int) -> tuple[int, int]:
    for w, h in CELL_SIZES:
        if ROW_LABEL_W + max_cells * (w + GUTTER) + MARGIN * 2 <= PAGE_MAX_W:
            return w, h
    return CELL_SIZES[-1]


def _row_label(s: dict) -> list[str]:
    item = s.get("_item") or {}
    bits = [s["id"], s.get("mark") or "", item.get("class") or ""]
    cam = s["_cam"]
    if cam.get("fill_exception") is not None:
        bits.append("fill_exception")
    if item.get("whole") is True:
        bits.append("whole")
    return [b for b in bits if b]


def build_chapter_pages(part_id: str, part_title: str, stills: list[dict], plan_sha: str, plan: dict,
                        images: dict[str, _StillImage]) -> list[tuple[Image.Image, list[str], tuple[int, int]]]:
    """One page per ``MAX_ROWS_PER_PAGE`` rows of this chapter. Returns
    ``[(page image, [shot id on this page, ...], (cell_w, cell_h)), ...]``."""
    rows = []
    for s in stills:
        cam = s["_cam"]
        dur = float(s["_dur"])
        ts = stop_times(cam, dur)
        rows.append((s, ts))
    max_cells = max((len(ts) for _, ts in rows), default=1)
    cell_w, cell_h = _cell_size_for(max_cells)
    row_h = cell_h + LABEL_H + GUTTER
    pages = [rows[i:i + MAX_ROWS_PER_PAGE] for i in range(0, len(rows), MAX_ROWS_PER_PAGE)] or [[]]
    out_pages = []
    for page_i, page_rows in enumerate(pages):
        width = ROW_LABEL_W + max_cells * (cell_w + GUTTER) + MARGIN * 2
        height = HEADER_H + len(page_rows) * row_h + MARGIN
        canvas = Image.new("RGB", (width, height), BG)
        d = ImageDraw.Draw(canvas)
        head_f = _font(M.Fonts().structure_medium, 18)
        mono_f = _font(M.Fonts().data, 13)
        shot_ids = ", ".join(s["id"] for s, _ in page_rows)
        d.text((MARGIN, 14), f"{plan['title']}  \u00b7  chapter {part_id}: {part_title}", font=head_f, fill=FG)
        d.text((MARGIN, 40), f"shots: {shot_ids}", font=mono_f, fill=_rgba(FG, 0.85))
        d.text((MARGIN, 58), f"plan sha {plan_sha}  \u00b7  page {page_i + 1}/{len(pages)}  \u00b7  cell {cell_w}x{cell_h}",
               font=mono_f, fill=_rgba(FG, 0.85))
        d.text((MARGIN, 76), "ROI: cold=auto, safelight=human  \u00b7  zones: mark_text  \u00b7  grid: bone  "
               "\u00b7  safe: safelight=action, cold=graphics", font=mono_f, fill=_rgba(FG, 0.6))
        y = HEADER_H
        for s, ts in page_rows:
            cam = s["_cam"]
            still = images[s["id"]]
            d.multiline_text((MARGIN, y + cell_h // 2 - 16), "\n".join(_row_label(s)), font=mono_f, fill=FG, spacing=3)
            x = MARGIN + ROW_LABEL_W
            n = len(ts)
            for i, t in enumerate(ts):
                cell = render_cell(still, cam, t, float(s["_dur"]), cell_w, cell_h)
                canvas.paste(cell.convert("RGB"), (x, y))
                lf = _font(M.Fonts().data, 11)
                d.text((x + 6, y + 2), stop_label(i, n), font=lf, fill=_rgba(FG, 0.9))
                x += cell_w + GUTTER
            y += row_h
        out_pages.append((canvas, [s["id"] for s, _ in page_rows], (cell_w, cell_h)))
    return out_pages


# --------------------------------------------------------------------------
# Planning: build_plan through its public contract, optionally with the
# music cues dropped in memory (never written) so a sheet can be made before
# a score is settled (ticket #3, WG-4's --skip-sound-lints).
# --------------------------------------------------------------------------


def _strip_music_cues(play: dict, journal: J.Journal | None) -> dict:
    play = json.loads(json.dumps(play))         # a deep copy; the original and the file on disk are never touched
    dropped: list[str] = []
    for part in play.get("parts", []):
        kept = []
        for c in part.get("cues", []):
            if c.get("kind") == "music":
                dropped.append(c.get("id"))
            else:
                kept.append(c)
        part["cues"] = kept
    if play.get("music"):
        dropped += [c.get("id") for c in play["music"]]
        play["music"] = []
    if dropped and journal is not None:
        journal.decision("scout", f"--skip-sound-lints: dropped {len(dropped)} music cue(s) in memory",
                         "cinematography ticket #3: a contact sheet is made before the score is settled; "
                         "the screenplay on disk is never changed", evidence={"dropped": dropped})
    return play


@contextmanager
def _redirect_film_caches(cache_dir: Path | None):
    """``build_plan`` caches a clip's natural-cut bounds (A33) and a long
    reel's trimmed span (A26) beside the film unless ``DOCUMENT_BOUNDS_CACHE``
    / ``DOCUMENT_SPANS_CACHE`` say otherwise (``clips.py``, ``render.py``).
    This tool never writes into the film folder, so it always says
    otherwise: a scratch folder beside the sheets, or (with no ``out_dir``,
    as in a bare ``plan_stills`` call) a process-local temp folder, restored
    on exit either way."""
    base = Path(cache_dir) if cache_dir else Path(tempfile.mkdtemp(prefix="document-sheets-cache-"))
    keys = ("DOCUMENT_BOUNDS_CACHE", "DOCUMENT_SPANS_CACHE")
    sub = {"DOCUMENT_BOUNDS_CACHE": "bounds", "DOCUMENT_SPANS_CACHE": "spans"}
    old = {k: os.environ.get(k) for k in keys}
    try:
        for k in keys:
            os.environ[k] = str(base / sub[k])
        yield base
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def plan_stills(film: Path, journal: J.Journal, *, skip_sound_lints: bool = False,
                cache_dir: Path | None = None) -> dict:
    W, H = R.RESOLUTIONS[1080]
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    if skip_sound_lints:
        play = _strip_music_cues(play, journal)
    with _redirect_film_caches(cache_dir):
        return R.build_plan(film, W=W, H=H, burn_subtitles=False, journal=journal, play=play)


def plan_sha(film: Path) -> str:
    return hashlib.sha256((film / "screenplay.json").read_bytes()).hexdigest()[:12]


def build_sheets(film: Path, *, out_dir: Path | None = None, chapter: str | None = None,
                 skip_sound_lints: bool = False, journal: J.Journal | None = None) -> dict:
    """Plan the film and write one PNG per chapter (part), plus
    ``index.json``. Never writes into ``film``. Returns {"out": Path,
    "plan_sha": str, "sheets": [...]}."""
    film = Path(film)
    own_journal = journal is None
    journal = journal or J.Journal(film=film.name, kind="sheets")
    cache_dir = (Path(out_dir) / ".cache") if out_dir else None   # never the film folder; plan_stills defaults to a temp one
    plan = plan_stills(film, journal, skip_sound_lints=skip_sound_lints, cache_dir=cache_dir)
    sha = plan_sha(film)
    slug = plan.get("slug") or film.name
    out = Path(out_dir) if out_dir else Path("D:/document-media") / f"{slug}-sheets"
    out.mkdir(parents=True, exist_ok=True)

    stills = [s for s in plan["shots"] if s.get("_cam") is not None]
    by_part: dict[str, list[dict]] = {}
    for s in stills:
        by_part.setdefault(s.get("_part"), []).append(s)
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    titles = {p["id"]: p.get("title", p["id"]) for p in play.get("parts", [])}
    order = [p["id"] for p in play.get("parts", []) if p["id"] in by_part]
    if chapter is not None:
        order = [pid for pid in order if pid == chapter]

    sheets_meta = []
    for part_id in order:
        part_stills = by_part[part_id]
        images: dict[str, _StillImage] = {}
        for s in part_stills:
            images[s["id"]] = _StillImage(s["_item"]["_path"], s["_cam"])
        pages = build_chapter_pages(part_id, titles.get(part_id, part_id), part_stills, sha, plan, images)
        for i, (page, page_shots, cell_size) in enumerate(pages):
            name = f"{part_id}.png" if len(pages) == 1 else f"{part_id}-page{i + 1}of{len(pages)}.png"
            path = out / name
            page.save(path, "PNG")
            sheets_meta.append({"chapter": part_id, "title": titles.get(part_id, part_id), "page": i + 1,
                                "pages": len(pages), "path": str(path), "width": page.width, "height": page.height,
                                "shots": page_shots, "cell": list(cell_size)})

    index = {"film": plan.get("title"), "slug": slug, "plan_sha": sha, "source": str(film),
            "skip_sound_lints": bool(skip_sound_lints), "sheets": sheets_meta}
    index_path = out / "index.json"
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    if own_journal:
        journal.decision("motion", f"sheets: {len(sheets_meta)} page(s) for {len(stills)} still(s) -> {out}",
                         "cinematography ticket #3: a grid-overlay contact sheet, no render", evidence={"out": str(out)})
    return {"out": out, "plan_sha": sha, "sheets": sheets_meta, "index": index_path}


# --------------------------------------------------------------------------
# CLI.
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m studio.engine.sheets", description=__doc__.split("\n\n")[0])
    ap.add_argument("film", type=Path, help="film folder with screenplay.json and its ledgers")
    ap.add_argument("--out", type=Path, default=None, help="output folder (default D:/document-media/<slug>-sheets)")
    ap.add_argument("--chapter", default=None, help="only this part id")
    ap.add_argument("--skip-sound-lints", action="store_true",
                    help="drop the music cues in memory (never written) so a sheet can be made before the score "
                         "is settled (WG-4)")
    a = ap.parse_args(argv)
    try:
        r = build_sheets(a.film, out_dir=a.out, chapter=a.chapter, skip_sound_lints=a.skip_sound_lints)
    except R.Refused as e:
        print(f"sheets: refused: {e}", file=sys.stderr)
        return 2
    sizes = ", ".join(f"{Path(m['path']).name} ({m['width']}x{m['height']})" for m in r["sheets"])
    print(f"sheets: {len(r['sheets'])} page(s) -> {r['out']}")
    if sizes:
        print(f"sheets: {sizes}")
    print(f"sheets: {r['index']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
