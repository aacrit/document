"""void document: the on-film motion system, frame-exact in pure Python.

Everything here is a function of time. Nothing keeps state, nothing writes a
file (except the demo under ``__main__``), and every curve has a closed form,
so the studio renders the same pixel for the same ``t`` on every run.

    python design/brand-kit/motion.py            # 6 s demo strip -> demo/
    python design/brand-kit/motion.py --table    # preset table (settle times)

Grammar: design/brand-kit/BRAND-KIT.md (the spec this implements),
films/GRAMMAR.md 4, 7 and 9 (the rules it obeys). Colours cite
design/tokens.css; there is no other colour source.

Frame coordinates are fractions of the frame, so 1920x1080 and 1280x720 render
the same picture. Springs are Hooke's law with viscous damping, solved in
closed form (no integrator, no dt drift). Exits never spring: an arrival is a
spring, a departure is a fade.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, features

# --------------------------------------------------------------------------
# Palette. Every tuple cites a custom property in design/tokens.css.
# --------------------------------------------------------------------------

PALETTE = {
    "black": (15, 12, 10),          # --doc-black  #0f0c0a  the theatre
    "letterbox": (5, 4, 3),         # --color-letterbox (black, l - 0.05)
    "bone": (237, 226, 207),        # --doc-bone   #ede2cf  text and controls
    "safelight": (237, 162, 60),    # --doc-safelight #eda23c  "this is real"
    "cold": (47, 95, 168),          # --doc-cold   #2f5fa8  AI-GENERATED, DRAWN
    "mark_text": (255, 246, 227),   # --mark-text  oklch(from bone l+0.06)
}
MARK_SCRIM_ALPHA = 0.60             # --mark-scrim: black at 60%
MARK_HUE = {                        # GRAMMAR 4, amendment A1: hue is a bar, never text
    "ARCHIVE": PALETTE["safelight"],
    "RECONSTRUCTED": PALETTE["bone"],
    "AI-GENERATED": PALETTE["cold"],
    "DRAWN": PALETTE["cold"],
    "CARD": PALETTE["bone"],
}

# --------------------------------------------------------------------------
# Fonts: paths only. Defaults resolve to the self-hosted @fontsource files the
# site already loads (design/fonts.css). FreeType reads the .woff directly.
# --------------------------------------------------------------------------

_FONTSOURCE = Path(__file__).resolve().parents[2] / "node_modules" / "@fontsource"


@dataclass(frozen=True)
class Fonts:
    display: str = str(_FONTSOURCE / "fraunces/files/fraunces-latin-300-normal.woff")
    display_italic: str = str(_FONTSOURCE / "fraunces/files/fraunces-latin-300-italic.woff")
    display_regular: str = str(_FONTSOURCE / "fraunces/files/fraunces-latin-400-normal.woff")
    structure: str = str(_FONTSOURCE / "inter/files/inter-latin-400-normal.woff")
    structure_medium: str = str(_FONTSOURCE / "inter/files/inter-latin-500-normal.woff")
    data: str = str(_FONTSOURCE / "jetbrains-mono/files/jetbrains-mono-latin-500-normal.woff")
    data_semibold: str = str(_FONTSOURCE / "jetbrains-mono/files/jetbrains-mono-latin-600-normal.woff")


@lru_cache(maxsize=256)
def _font(path: str, px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, max(1, px))


# --------------------------------------------------------------------------
# Springs: closed-form damped harmonic motion.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Spring:
    """x(t): displacement from rest, starting at x0 = 1 with v0 = 0.
    progress(t) = 1 - x(t). ``eps`` is the settle threshold on |x|."""

    name: str
    k: float      # stiffness, N/m
    c: float      # damping, N s/m
    m: float      # mass, kg
    eps: float = 0.005
    says: str = ""

    @property
    def omega0(self) -> float:
        return math.sqrt(self.k / self.m)

    @property
    def zeta(self) -> float:
        return self.c / (2.0 * math.sqrt(self.k * self.m))

    def x(self, t: float, x0: float = 1.0, v0: float = 0.0) -> float:
        if t <= 0.0:
            return x0
        w0, z = self.omega0, self.zeta
        if z < 1.0:                                   # underdamped
            wd = w0 * math.sqrt(1.0 - z * z)
            a = (v0 + z * w0 * x0) / wd
            return math.exp(-z * w0 * t) * (x0 * math.cos(wd * t) + a * math.sin(wd * t))
        if abs(z - 1.0) < 1e-9:                       # critically damped
            return (x0 + (v0 + w0 * x0) * t) * math.exp(-w0 * t)
        s = w0 * math.sqrt(z * z - 1.0)               # overdamped
        r1, r2 = -z * w0 + s, -z * w0 - s
        b = (v0 - r1 * x0) / (r2 - r1)
        a = x0 - b
        return a * math.exp(r1 * t) + b * math.exp(r2 * t)

    def progress(self, t: float) -> float:
        return 1.0 - self.x(t)

    def overshoot(self) -> float:
        """Peak of progress above 1, as a fraction (0 for zeta >= 1)."""
        z = self.zeta
        if z >= 1.0:
            return 0.0
        return math.exp(-math.pi * z / math.sqrt(1.0 - z * z))

    def settle_time(self, dt: float = 0.001, horizon: float = 6.0) -> float:
        """First t after which |x| stays below eps (scanned at 1 ms)."""
        n = int(horizon / dt)
        last = 0
        for i in range(n):
            if abs(self.x(i * dt)) >= self.eps:
                last = i
        return (last + 1) * dt

    def frames(self, fps: float) -> int:
        return math.ceil(self.settle_time() * fps)

    def css_linear(self, n: int = 20) -> str:
        """A CSS linear() easing sampled over the settle time, for previews."""
        T = self.settle_time()
        pts = []
        for i in range(n + 1):
            u = i / n
            p = self.progress(u * T)
            pts.append(f"{p:.4f} {u * 100:.1f}%")
        pts[-1] = "1 100%"
        return "linear(" + ", ".join(pts) + ")"


# The four arrivals. Damping sits at or just under critical: the eye feels the
# exponential settle (a spring, not a bezier) and never sees a bounce.
STAMP = Spring("stamp", 420, 40, 1.0, says="a rule is drawn; the watermark's corners close")
SETTLE = Spring("settle", 170, 24, 1.0, says="a line of a lower third or a card takes its place")
ARRIVE = Spring("arrive", 110, 20, 1.1, says="a title, the largest thing on the frame, arrives")
DRIFT = Spring("drift", 48, 14, 1.2, says="the watermark settles at the open; the chapter rule grows")
PRESETS = (STAMP, SETTLE, ARRIVE, DRIFT)

# --------------------------------------------------------------------------
# Eases (closed form) for fades, dissolves, dips and the rostrum move.
# --------------------------------------------------------------------------


def clamp01(u: float) -> float:
    return 0.0 if u < 0.0 else 1.0 if u > 1.0 else u


def ease_in_quad(u: float) -> float:
    u = clamp01(u)
    return u * u


def ease_out_quad(u: float) -> float:
    u = clamp01(u)
    return 1.0 - (1.0 - u) * (1.0 - u)


def ease_in_sine(u: float) -> float:
    return 1.0 - math.cos(0.5 * math.pi * clamp01(u))


def ease_out_sine(u: float) -> float:
    return math.sin(0.5 * math.pi * clamp01(u))


def sine_inout(u: float) -> float:
    """sketch.py's ease: symmetric, breathes at both ends. Kept for HOLD-less
    very short moves (under 2 s); the rostrum curve replaces it elsewhere."""
    return 0.5 - 0.5 * math.cos(math.pi * clamp01(u))


def smoothstep(u: float) -> float:
    u = clamp01(u)
    return u * u * (3.0 - 2.0 * u)


def rostrum(t: float, dur: float, ramp: float = 0.9) -> float:
    """Position 0..1 of a motion-control rostrum camera: velocity ramps up with
    a smoothstep over ``ramp`` seconds, holds constant, ramps down. The move
    spends most of the shot at one speed, which is what a documentary Ken Burns
    should feel like. Closed form (the integral of the smoothstep ramp is
    r * (u^3 - u^4 / 2)). ramp is clipped to 30% of the duration."""
    if dur <= 0.0:
        return 1.0
    r = min(ramp, 0.3 * dur)
    t = min(max(t, 0.0), dur)
    vmax = 1.0 / (dur - r)
    if t < r:
        u = t / r
        return vmax * r * (u ** 3 - 0.5 * u ** 4)
    if t <= dur - r:
        return vmax * (0.5 * r + (t - r))
    u = (dur - t) / r
    return 1.0 - vmax * r * (u ** 3 - 0.5 * u ** 4)


def dissolve_weight(t: float, dur: float) -> float:
    """Weight of the incoming shot during a dissolve (GRAMMAR 7.3: 0.5 to 1.5 s,
    same mark class only). Sine in-out: both pictures are held a beat longer at
    the ends than a linear mix gives, and the mid-point is at exactly 0.5."""
    return sine_inout(t / dur) if dur > 0 else 1.0


def dip_level(t: float, dur: float, hold: float = 0.10) -> float:
    """Picture level 0..1 through a dip to black of ``dur`` seconds: fade out
    over 45% (ease-in, the picture is released), black for ``hold`` of the
    duration, fade in over 45% (ease-out, the next picture arrives)."""
    if dur <= 0:
        return 1.0
    u = t / dur
    a = 0.5 * (1.0 - hold)
    if u < a:
        return 1.0 - ease_in_quad(u / a)
    if u <= 1.0 - a:
        return 0.0
    return ease_out_quad((u - (1.0 - a)) / a)


def fade_out(t: float, end: float, dur: float) -> float:
    """1 until end - dur, then an ease-in fade to 0 at ``end``."""
    if t <= end - dur:
        return 1.0
    return 1.0 - ease_in_quad((t - (end - dur)) / dur)


def fade_in(t: float, start: float, dur: float, ease=ease_out_sine) -> float:
    if t <= start:
        return 0.0
    return ease((t - start) / dur)


# --------------------------------------------------------------------------
# Layout in fractions of the frame. BRAND-KIT.md section 3 and 4 are the spec;
# these numbers are that spec.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Layout:
    W: int
    H: int

    def w(self, pct: float) -> float:
        return pct / 100.0 * self.W

    def h(self, pct: float) -> float:
        return pct / 100.0 * self.H

    def px(self, pct_h: float) -> int:
        return max(1, round(pct_h / 100.0 * self.H))


LT = dict(                 # lower third
    x=4.0,                 # % of W, left edge (aligned with the mark plate)
    bottom=92.0,           # % of H, bottom edge of the last line's box
    max_w=56.0,            # % of W
    rule_len=7.5,          # % of W
    rule_h=0.19,           # % of H (2 px at 1080p)
    flag=2.0, name=4.4, role=2.8, source=2.3,        # font sizes, % of H
    lh_flag=1.4, lh_name=1.1, lh_role=1.3, lh_source=1.3,
    gap_flag=0.5, gap_rule=0.7, gap_name=0.7, gap_role=0.5,   # % of H
    # Flagged (partisan-source) form: the flag is the first and largest line, set in
    # Fraunces 300 italic at the name's size; the name steps down to match it, gaps
    # tighten and the source must fit one line, so the block top stays at 75.06% of H.
    flag_f=3.6, name_f=3.6, lh_flag_f=1.1, gap_flag_f=0.5, gap_rule_f=0.6, gap_role_f=0.4,
    # block top: 78.4% of H plain, 75.06% with a flag (GRAMMAR 4.1: never above 75%)
    rise=0.8,              # % of H, the vertical travel of an arriving line
    stagger=4 / 24,        # s between arrivals (4 frames at 24 fps)
    exit=0.5,              # s, the fade out
    wash=0.5,              # peak alpha of the wash
    wash_w=62.0,           # % of W the wash reaches
    wash_feather=4.0,      # % of H above the block
)
MARK = dict(x=4.0, y=5.0, size=3.1, size_card=2.4, pad=0.6, radius=0.55, bar_px_1080=3, fade=4 / 24)
WM = dict(box=6.0, right=4.0, top=5.0, opacity=0.6, spread=0.08, halo=0.35, fade=0.5)
SUB = dict(size=3.9, bottom=93.0, max_w=84.0, gap=1.2, lh=1.45, lh_nastaliq=1.9)
CHAPTER = dict(title=5.6, dates=2.6, rule_len=6.0, rule_h=0.19, baseline=47.0, rise=0.6, exit=0.4)
SILENT = dict(size=4.0, lh=1.35, searched=2.6, max_w=76.0, fade=0.75, stagger=0.33)
TITLE = dict(size=7.0, wordmark=2.6, rise=0.6, exit=0.67, gap=2.2)
CREDITS = dict(size=2.4, lh=1.5, heading=1.85, speed=5.2, fade_in=1.0, col_w=70.0)

# --------------------------------------------------------------------------
# Drawing helpers (private). All return or mutate RGBA layers; composition is
# always alpha_composite onto a copy of the input frame.
# --------------------------------------------------------------------------

_NUM = re.compile(r"(\d[\d,.:]*\d|\d)")


def _rgba(rgb, a: float):
    return (rgb[0], rgb[1], rgb[2], int(round(255 * clamp01(a))))


def _runs(text: str):
    """Split text into (fragment, is_numeral) runs so numerals ride the data face."""
    out = []
    for i, part in enumerate(_NUM.split(text)):
        if part:
            out.append((part, i % 2 == 1))
    return out


def _measure(text: str, font: ImageFont.FreeTypeFont, data_font: ImageFont.FreeTypeFont | None) -> float:
    if data_font is None:
        return font.getlength(text)
    return sum((data_font if num else font).getlength(frag) for frag, num in _runs(text))


def _draw_mixed(d: ImageDraw.ImageDraw, xy, text: str, font, data_font, fill):
    """Draw text at baseline xy; numeral runs use data_font (tabular by nature)."""
    x, y = xy
    if data_font is None:
        d.text((x, y), text, font=font, fill=fill, anchor="ls")
        return
    for frag, num in _runs(text):
        f = data_font if num else font
        d.text((x, y), frag, font=f, fill=fill, anchor="ls")
        x += f.getlength(frag)


def _draw_tracked(d: ImageDraw.ImageDraw, xy, text: str, font, fill, track_em: float):
    x, y = xy
    px = font.size
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill, anchor="ls")
        x += font.getlength(ch) + track_em * px
    return x


def _tracked_width(text: str, font, track_em: float) -> float:
    return sum(font.getlength(ch) for ch in text) + track_em * font.size * max(0, len(text) - 1)


def _wrap(text: str, font, data_font, max_w: float) -> list[str]:
    words = text.split(" ")
    lines, cur = [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if cur and _measure(cand, font, data_font) > max_w:
            lines.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines[:2] if len(lines) > 2 else lines


def _scale_alpha(layer: Image.Image, k: float) -> Image.Image:
    if k >= 1.0:
        return layer
    a = np.asarray(layer.getchannel("A"), dtype=np.float32) * clamp01(k)
    layer.putalpha(Image.fromarray(a.astype(np.uint8)))
    return layer


def _shift(layer: Image.Image, dy: float) -> Image.Image:
    """Translate a layer vertically by a (rounded) pixel amount."""
    n = int(round(dy))
    if n == 0:
        return layer
    out = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    out.paste(layer, (0, n))
    return out


def _as_rgba(img: Image.Image) -> Image.Image:
    return img.convert("RGBA") if img.mode != "RGBA" else img.copy()


# --------------------------------------------------------------------------
# The logomark ("a void in the camera's window") and the watermark.
# --------------------------------------------------------------------------

LOGOMARK_CORNERS = [  # 24-grid, from design/BRAND.md; each is a 3-point polyline
    [(3.5, 8.0), (3.5, 4.5), (7.0, 4.5)],
    [(17.0, 4.5), (20.5, 4.5), (20.5, 8.0)],
    [(20.5, 16.0), (20.5, 19.5), (17.0, 19.5)],
    [(7.0, 19.5), (3.5, 19.5), (3.5, 16.0)],
]
LOGOMARK_RING = ((12.0, 12.0), 4.2)
LOGOMARK_EMBER = ((18.6, 17.6), 1.25)
LOGOMARK_STROKE = 1.6


def draw_logomark(box_px: int, *, stroke_rgb=PALETTE["bone"], ember_rgb=PALETTE["safelight"],
                  spread: float = 0.0, ember_alpha: float = 1.0, halo: float = 0.0,
                  ss: int = 4) -> Image.Image:
    """RGBA image of the logomark in a square of ``box_px``. ``spread`` moves
    the four corners outward by that fraction of the box (the watermark's open
    settle). ``halo`` > 0 draws the same strokes in black beneath, 2 px wider
    at 1080p scale, so the mark holds on a white sky."""
    big = box_px * ss
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = big / 24.0
    sw = LOGOMARK_STROKE * s
    cx = cy = 12.0

    def P(p, k=1.0):
        return ((cx + (p[0] - cx) * k) * s, (cy + (p[1] - cy) * k) * s)

    def strokes(color, width):
        r = width / 2.0
        k = 1.0 + spread * 24.0 / 17.0  # corners sit on a 17-unit square; spread is of the box
        for poly in LOGOMARK_CORNERS:
            pts = [P(p, k) for p in poly]
            d.line(pts, fill=color, width=max(1, int(round(width))), joint="curve")
            for (x, y) in (pts[0], pts[-1]):
                d.ellipse([x - r, y - r, x + r, y + r], fill=color)
        (rx, ry), rr = LOGOMARK_RING
        rx, ry, rr = rx * s, ry * s, rr * s
        d.ellipse([rx - rr - r, ry - rr - r, rx + rr + r, ry + rr + r], outline=color, width=max(1, int(round(width))))

    if halo > 0:
        strokes((0, 0, 0, int(255 * halo)), sw + 2.0 * s * (24.0 / 65.0))
    strokes(stroke_rgb + (255,), sw)
    if ember_alpha > 0:
        (ex, ey), er = LOGOMARK_EMBER
        ex, ey, er = ex * s, ey * s, er * s
        d.ellipse([ex - er, ey - er, ex + er, ey + er], fill=ember_rgb + (int(255 * clamp01(ember_alpha)),))
    return img.resize((box_px, box_px), Image.LANCZOS)


def watermark_level(t: float, card_spans=(), fade: float = WM["fade"]) -> float:
    """1 over imagery, 0 inside a CARD span, with a linear fade of ``fade``
    seconds on each side of every span. Cards carry the VOID DOCUMENT mark
    already; the watermark leaves them alone."""
    lvl = 1.0
    for s, e in card_spans:
        if s <= t < e:
            return 0.0
        if s - fade < t < s:
            lvl = min(lvl, (s - t) / fade)
        if e <= t < e + fade:
            lvl = min(lvl, (t - e) / fade)
    return lvl


def watermark(img: Image.Image, t: float, *, start: float = 0.0, card_spans=(), settle: bool = True,
              opacity: float = WM["opacity"], fonts: Fonts | None = None) -> Image.Image:
    """The in-film watermark: the logomark, top right, bone at 60% with a black
    halo, 6% of frame height. At ``start`` it settles once (corners close from
    an 8% spread with DRIFT; the ember appears in the last tenth); afterwards
    it is static. Hidden over CARD spans with a 12-frame fade."""
    base = _as_rgba(img)
    if t < start:
        return base
    lvl = watermark_level(t, card_spans)
    if lvl <= 0.0:
        return base
    L = Layout(*base.size)
    p = DRIFT.progress(t - start) if settle else 1.0
    box = L.px(WM["box"])
    spread = WM["spread"] * (1.0 - clamp01(p))
    ember = clamp01((p - 0.9) / 0.1)
    mark = draw_logomark(box, spread=spread, ember_alpha=ember, halo=WM["halo"])
    mark = _scale_alpha(mark, opacity * clamp01(p) * lvl)
    x = int(round(L.W - L.w(WM["right"]) - box))
    y = int(round(L.h(WM["top"])))
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    layer.paste(mark, (x, y))
    return Image.alpha_composite(base, layer)


# --------------------------------------------------------------------------
# The provenance mark plate (GRAMMAR 4). Stamp, not graphic.
# --------------------------------------------------------------------------


def _mark_plate(L: Layout, cls: str, detail: str, fonts: Fonts) -> Image.Image:
    small = cls == "CARD"
    px = L.px(MARK["size_card"] if small else MARK["size"])
    f_cls = _font(fonts.data_semibold, px)
    f_det = _font(fonts.data, px)
    word = "VOID DOCUMENT" if small else cls
    track = 0.06
    w_cls = _tracked_width(word, f_cls, track)
    gap = 0.9 * px if detail else 0.0
    w_det = f_det.getlength(detail) if detail else 0.0
    pad = MARK["pad"] * px
    bar = max(2, round(MARK["bar_px_1080"] * L.H / 1080))
    w = int(round(bar + 0.7 * px + w_cls + gap + w_det + 0.75 * px))
    h = int(round(px + 2 * pad))
    plate = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(plate)
    r = L.px(MARK["radius"])
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=r, fill=(0, 0, 0, int(255 * MARK_SCRIM_ALPHA)))
    d.rectangle([0, 0, bar - 1, h - 1], fill=MARK_HUE[cls] + (255,))
    base_y = pad + 0.78 * px
    x = bar + 0.7 * px
    x = _draw_tracked(d, (x, base_y), word, f_cls, PALETTE["mark_text"] + (255,), track)
    if detail:
        d.text((x + gap - track * px, base_y), detail, font=f_det, fill=PALETTE["mark_text"] + (255,), anchor="ls")
    return plate


def mark_plate_frame(img: Image.Image, t: float, shots, fonts: Fonts) -> Image.Image:
    """Draw the current shot's mark. ``shots`` is a list of dicts with
    ``start`` (s), ``cls`` and ``detail``. The label changes on the cut frame.
    When the class changes, the outgoing and incoming plates crossfade over
    4 frames (GRAMMAR 4.1); within a class the swap is hard. The first shot's
    mark is full from its first frame: no frame goes unmarked."""
    base = _as_rgba(img)
    L = Layout(*base.size)
    cur = prev = None
    for s in sorted(shots, key=lambda s: s["start"]):
        if s["start"] <= t:
            prev, cur = cur, s
    if cur is None:
        return base
    x, y = int(round(L.w(MARK["x"]))), int(round(L.h(MARK["y"])))
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    u = (t - cur["start"]) / MARK["fade"]
    if prev is not None and prev["cls"] != cur["cls"] and u < 1.0:
        out = _scale_alpha(_mark_plate(L, prev["cls"], prev.get("detail", ""), fonts), 1.0 - u)
        layer.paste(out, (x, y))
        inc = _scale_alpha(_mark_plate(L, cur["cls"], cur.get("detail", ""), fonts), u)
        layer.alpha_composite(inc, (x, y))
    else:
        layer.paste(_mark_plate(L, cur["cls"], cur.get("detail", ""), fonts), (x, y))
    return Image.alpha_composite(base, layer)


# --------------------------------------------------------------------------
# Lower thirds (BRAND-KIT.md section 3). Three formats, one grammar: a flag
# eyebrow (optional), a short rule, then lines that arrive one after another.
# --------------------------------------------------------------------------


def lower_third_layout(L: Layout, lines, fonts: Fonts, kind: str = "speaker", flag: str | None = None):
    """Compute the block: returns (elements, top_y, block_w). Each element is a
    dict with kind, text, font, data_font, baseline, size, order."""
    px = L.px
    max_w = L.w(LT["max_w"])
    els = []
    if kind == "place":
        f_place = _font(fonts.display_italic, px(LT["name"]))
        f_date = _font(fonts.data, px(LT["role"]))
        rows = [("name", lines[0], f_place, None, LT["name"], LT["lh_name"]),
                ("role", lines[1], f_date, f_date, LT["role"], LT["lh_role"])]
    else:
        name_sz = LT["name_f"] if flag else LT["name"]
        f_name = _font(fonts.display, px(name_sz))
        f_role = _font(fonts.structure, px(LT["role"]))
        f_role_n = _font(fonts.data, round(px(LT["role"]) * 0.94))
        f_src = _font(fonts.structure, px(LT["source"]))
        f_src_n = _font(fonts.data, round(px(LT["source"]) * 0.94))
        rows = [("name", lines[0], f_name, None, name_sz, LT["lh_name"]),
                ("role", lines[1], f_role, f_role_n, LT["role"], LT["lh_role"])]
        if len(lines) > 2 and flag and len(_wrap(lines[2], f_src, f_src_n, max_w)) > 1:
            raise ValueError("a flagged lower third's source line must fit on one line")
        if len(lines) > 2:
            for i, wrapped in enumerate(_wrap(lines[2], f_src, f_src_n, max_w)):
                rows.append(("source" if i == 0 else "source2", wrapped, f_src, f_src_n, LT["source"], LT["lh_source"]))
    # Stack from the bottom up so the last line's box bottom sits at LT.bottom.
    y = L.h(LT["bottom"])
    order = 0
    stacked = []
    gaps = {"name": LT["gap_name"], "role": LT["gap_role_f"] if flag else LT["gap_role"], "source": 0.0, "source2": 0.0}
    for i, (rk, text, font, dfont, size, lh) in enumerate(reversed(rows)):
        box_h = L.h(size) * lh
        top = y - box_h
        baseline = top + L.h(size) * (0.78 + (lh - 1.0) / 2.0)
        stacked.append(dict(kind=rk, text=text, font=font, data_font=dfont, baseline=baseline, top=top, size=L.h(size)))
        nxt = rows[len(rows) - 2 - i][0] if i + 1 < len(rows) else None
        y = top - (L.h(gaps[nxt]) if nxt else 0.0)
    stacked.reverse()
    rule_top = y - L.h(LT["gap_rule_f"] if flag else LT["gap_rule"]) - L.h(LT["rule_h"])
    rule = dict(kind="rule", top=rule_top, h=max(1, round(L.h(LT["rule_h"]))), len=L.w(LT["rule_len"]))
    els = [rule] + stacked
    top = rule_top
    if flag:
        f_flag = _font(fonts.display_italic, px(LT["flag_f"]))
        box_h = L.h(LT["flag_f"]) * LT["lh_flag_f"]
        ftop = rule_top - L.h(LT["gap_flag_f"]) - box_h
        baseline = ftop + L.h(LT["flag_f"]) * (0.78 + (LT["lh_flag_f"] - 1.0) / 2.0)
        els = [dict(kind="flag", text=flag, font=f_flag, data_font=None, baseline=baseline, top=ftop, size=L.h(LT["flag_f"]))] + els
        top = ftop
    # arrival order: flag and rule together, then each line in turn
    for e in els:
        e["order"] = 0 if e["kind"] in ("flag", "rule") else order + 1
        if e["kind"] not in ("flag", "rule"):
            order += 1
    return els, top


def _wash(L: Layout, top: float, alpha: float) -> Image.Image:
    """A feathered dark gradient behind the lower third, from the left edge to
    LT.wash_w, from LT.wash_feather above the block to the bottom of the frame."""
    xs = np.linspace(0.0, 1.0, L.W, dtype=np.float32)
    hx = 1.0 - np.clip(xs / (LT["wash_w"] / 100.0), 0.0, 1.0)
    hx = hx * hx * (3.0 - 2.0 * hx)
    ys = np.arange(L.H, dtype=np.float32)
    f = L.h(LT["wash_feather"])
    vy = np.clip((ys - (top - f)) / f, 0.0, 1.0)
    vy = vy * vy * (3.0 - 2.0 * vy)
    a = (vy[:, None] * hx[None, :]) * (255.0 * LT["wash"] * clamp01(alpha))
    rgba = np.zeros((L.H, L.W, 4), np.uint8)
    rgba[..., 3] = a.astype(np.uint8)
    return Image.fromarray(rgba)


def lower_third_frame(img: Image.Image, t: float, *, start: float, end: float, lines, fonts: Fonts,
                      kind: str = "speaker", flag: str | None = None) -> Image.Image:
    """Draw a lower third at time t. ``lines`` are GRAMMAR 9's lines: for a
    speaker [name, "role, year", "source, archive  ·  read by a computer voice"];
    for a place [place, date]. ``flag`` is the partisan-source eyebrow
    ("Account of the Government of West Punjab, 1948").

    In: the flag and the rule arrive first (STAMP draws the rule from the left),
    then each line 4 frames after the last, rising 0.8% of frame height on
    SETTLE while fading in. Out: everything fades together over 0.5 s with an
    ease-in; the rule shrinks back to its anchor. Nothing leaves by moving."""
    base = _as_rgba(img)
    if t < start or t >= end:
        return base
    L = Layout(*base.size)
    els, top = lower_third_layout(L, lines, fonts, kind, flag)
    x0 = L.w(LT["x"])
    exit_k = fade_out(t, end, LT["exit"])
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    rule_p = STAMP.progress(t - start)
    out = Image.alpha_composite(base, _wash(L, top, clamp01(rule_p) * exit_k))
    d = ImageDraw.Draw(layer)
    for e in els:
        t0 = start + e["order"] * LT["stagger"]
        if e["kind"] == "rule":
            p = clamp01(rule_p) * exit_k
            w = e["len"] * p
            if w >= 1:
                d.rectangle([x0, e["top"], x0 + w, e["top"] + e["h"]], fill=_rgba(PALETTE["bone"], 0.85))
            continue
        p = SETTLE.progress(t - t0) if t >= t0 else 0.0
        if p <= 0.0:
            continue
        a = clamp01(p) * exit_k
        dy = (1.0 - clamp01(p)) * L.h(LT["rise"])
        sub = Image.new("RGBA", base.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(sub)
        col = PALETTE["mark_text"]
        if e["kind"] == "flag":
            sd.text((x0, e["baseline"]), e["text"], font=e["font"], fill=_rgba(col, a), anchor="ls")
        elif e["kind"].startswith("source") and "  ·  " in e["text"]:
            main, suffix = e["text"].split("  ·  ", 1)
            _draw_mixed(sd, (x0, e["baseline"]), main, e["font"], e["data_font"], _rgba(col, a))
            xx = x0 + _measure(main, e["font"], e["data_font"])
            sd.text((xx, e["baseline"]), "  ·  ", font=e["font"], fill=_rgba(col, a * 0.7), anchor="ls")
            xx += e["font"].getlength("  ·  ")
            _draw_mixed(sd, (xx, e["baseline"]), suffix, e["font"], e["data_font"], _rgba(col, a * 0.7))
        else:
            _draw_mixed(sd, (x0, e["baseline"]), e["text"], e["font"], e["data_font"], _rgba(col, a))
        layer.alpha_composite(_shift(sub, dy))
    return Image.alpha_composite(out, layer)


def lower_third_top(L: Layout, lines, fonts: Fonts, kind="speaker", flag=None) -> float:
    """Top edge (px) of a lower third's block, for raising a subtitle above it."""
    return lower_third_layout(L, lines, fonts, kind, flag)[1]


# --------------------------------------------------------------------------
# Subtitles (layout only: the film ships subtitles as tracks, never burned in).
# --------------------------------------------------------------------------


def subtitle_frame(img: Image.Image, text: str, font_path: str, *, rtl: bool = False, nastaliq: bool = False,
                   raise_above: float | None = None, alpha: float = 1.0) -> Image.Image:
    """A cue at bottom centre on a per-line scrim, 3.9% of frame height, raised
    above a lower third when ``raise_above`` (that block's top, px) is given.
    Complex scripts need Pillow built with libraqm for shaping; without it this
    draws glyphs unshaped, which is fine for layout checks only."""
    base = _as_rgba(img)
    L = Layout(*base.size)
    px = L.px(SUB["size"])
    f = _font(font_path, px)
    lh = SUB["lh_nastaliq"] if nastaliq else SUB["lh"]
    lines = text.split("\n")
    box_h = px * lh
    bottom = (raise_above - L.h(SUB["gap"])) if raise_above is not None else L.h(SUB["bottom"])
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    kw = {"direction": "rtl"} if (rtl and features.check("raqm")) else {}
    for i, line in enumerate(reversed(lines)):
        top = bottom - (i + 1) * box_h
        baseline = top + px * (0.78 + (lh - 1.0) / 2.0)
        w = f.getlength(line)
        x = (L.W - w) / 2.0
        pad = 0.45 * px
        d.rounded_rectangle([x - pad, top, x + w + pad, top + box_h], radius=3, fill=(0, 0, 0, int(255 * MARK_SCRIM_ALPHA * alpha)))
        d.text((x, baseline), line, font=f, fill=_rgba(PALETTE["mark_text"], alpha), anchor="ls", **kw)
    return Image.alpha_composite(base, layer)


# --------------------------------------------------------------------------
# Cards over black: chapter, record-is-silent, title. All are CARD (the mark
# plate is drawn separately by mark_plate_frame so no card forgets it).
# --------------------------------------------------------------------------


def _black(size) -> Image.Image:
    return Image.new("RGBA", size, PALETTE["black"] + (255,))


def chapter_card_frame(img: Image.Image, t: float, *, start: float, end: float, number: int, title: str,
                       dates: str, fonts: Fonts) -> Image.Image:
    """``<number>  <title>`` on one line, the dates beneath in tabular figures
    (GRAMMAR 9). In: the title rises 0.6% of frame height on ARRIVE; a short
    centred rule grows from its middle on DRIFT (+0.1 s); the dates follow on
    SETTLE (+0.25 s). Out: a 0.4 s ease-in fade. The frame is black."""
    base = _black(img.size)
    if t < start or t >= end:
        return base
    L = Layout(*base.size)
    exit_k = fade_out(t, end, CHAPTER["exit"])
    f_t = _font(fonts.display, L.px(CHAPTER["title"]))
    f_n = _font(fonts.data, L.px(CHAPTER["title"]))
    f_d = _font(fonts.data, L.px(CHAPTER["dates"]))
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    num = f"{number}"
    gap = 0.55 * f_t.size
    w = f_n.getlength(num) + gap + f_t.getlength(title)
    x = (L.W - w) / 2.0
    by = L.h(CHAPTER["baseline"])
    p = ARRIVE.progress(t - start)
    a = clamp01(p) * exit_k
    dy = (1.0 - clamp01(p)) * L.h(CHAPTER["rise"])
    sub = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(sub)
    sd.text((x, by), num, font=f_n, fill=_rgba(PALETTE["bone"], a * 0.8), anchor="ls")
    sd.text((x + f_n.getlength(num) + gap, by), title, font=f_t, fill=_rgba(PALETTE["bone"], a), anchor="ls")
    layer.alpha_composite(_shift(sub, dy))
    rp = clamp01(DRIFT.progress(t - start - 0.10)) * exit_k
    rl = L.w(CHAPTER["rule_len"]) * rp
    ry = by + L.h(1.6)
    if rl >= 1:
        d.rectangle([L.W / 2 - rl / 2, ry, L.W / 2 + rl / 2, ry + max(1, round(L.h(CHAPTER["rule_h"])))],
                    fill=_rgba(PALETTE["bone"], 0.6 * exit_k))
    dp = SETTLE.progress(t - start - 0.25) if t >= start + 0.25 else 0.0
    if dp > 0:
        sub = Image.new("RGBA", base.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(sub)
        dw = f_d.getlength(dates)
        sd.text(((L.W - dw) / 2.0, ry + L.h(1.2) + f_d.size), dates, font=f_d, fill=_rgba(PALETTE["bone"], clamp01(dp) * 0.8 * exit_k), anchor="ls")
        layer.alpha_composite(_shift(sub, (1.0 - clamp01(dp)) * L.h(CHAPTER["rise"])))
    return Image.alpha_composite(base, layer)


def silent_card_frame(img: Image.Image, t: float, *, start: float, end: float, statement: str,
                      searched: str | None, fonts: Fonts) -> Image.Image:
    """The record-is-silent card. No spring: the record is silent, so the
    graphic is still. Line 1 fades in over 0.75 s (ease-out sine); the
    "Searched:" line follows 0.33 s later; both fade out together over 0.75 s."""
    base = _black(img.size)
    if t < start or t >= end:
        return base
    L = Layout(*base.size)
    f1 = _font(fonts.display, L.px(SILENT["size"]))
    f1n = _font(fonts.data, round(L.px(SILENT["size"]) * 0.94))
    f2 = _font(fonts.structure, L.px(SILENT["searched"]))
    f2n = _font(fonts.data, round(L.px(SILENT["searched"]) * 0.94))
    exit_k = 1.0 - ease_in_sine((t - (end - SILENT["fade"])) / SILENT["fade"]) if t > end - SILENT["fade"] else 1.0
    a1 = fade_in(t, start, SILENT["fade"]) * exit_k
    a2 = fade_in(t, start + SILENT["stagger"], SILENT["fade"]) * exit_k
    lines1 = _wrap(statement, f1, f1n, L.w(SILENT["max_w"]))
    lines2 = _wrap(searched, f2, f2n, L.w(SILENT["max_w"])) if searched else []
    h1 = len(lines1) * f1.size * SILENT["lh"]
    h2 = len(lines2) * f2.size * 1.4 + (L.h(1.2) if lines2 else 0)
    y = (L.H - h1 - h2) / 2.0
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for ln in lines1:
        w = _measure(ln, f1, f1n)
        _draw_mixed(d, ((L.W - w) / 2.0, y + f1.size * (0.78 + (SILENT["lh"] - 1) / 2)), ln, f1, f1n, _rgba(PALETTE["mark_text"], a1))
        y += f1.size * SILENT["lh"]
    y += L.h(1.2)
    for ln in lines2:
        w = _measure(ln, f2, f2n)
        _draw_mixed(d, ((L.W - w) / 2.0, y + f2.size * (0.78 + 0.2)), ln, f2, f2n, _rgba(PALETTE["mark_text"], a2 * 0.8))
        y += f2.size * 1.4
    return Image.alpha_composite(base, layer)


def wordmark_width(L: Layout, px: int, fonts: Fonts) -> float:
    f_v, f_d = _font(fonts.data, px), _font(fonts.display, px)
    return f_v.getlength("void") + 0.45 * px + f_d.getlength("document")


def draw_wordmark(d: ImageDraw.ImageDraw, x: float, baseline: float, px: int, fonts: Fonts, alpha: float = 1.0):
    """``void`` in the data face, ``document`` in the display face (BRAND.md)."""
    f_v, f_d = _font(fonts.data, px), _font(fonts.display, px)
    d.text((x, baseline), "void", font=f_v, fill=_rgba(PALETTE["bone"], alpha), anchor="ls")
    d.text((x + f_v.getlength("void") + 0.45 * px, baseline), "document", font=f_d, fill=_rgba(PALETTE["bone"], alpha), anchor="ls")


def title_card_frame(img: Image.Image, t: float, *, start: float, end: float, title: str, fonts: Fonts) -> Image.Image:
    """Film title on one line, ``void document`` beneath (GRAMMAR 9), 5 s, CARD.
    In: the title arrives on ARRIVE (rise 0.6% of H); the wordmark on SETTLE
    0.4 s later. Out: a 0.67 s ease-in fade."""
    base = _black(img.size)
    if t < start or t >= end:
        return base
    L = Layout(*base.size)
    exit_k = fade_out(t, end, TITLE["exit"])
    f_t = _font(fonts.display, L.px(TITLE["size"]))
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    p = ARRIVE.progress(t - start)
    sub = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(sub)
    w = f_t.getlength(title)
    by = L.h(50.0)
    sd.text(((L.W - w) / 2.0, by), title, font=f_t, fill=_rgba(PALETTE["bone"], clamp01(p) * exit_k), anchor="ls")
    layer.alpha_composite(_shift(sub, (1.0 - clamp01(p)) * L.h(TITLE["rise"])))
    wp = SETTLE.progress(t - start - 0.4) if t >= start + 0.4 else 0.0
    if wp > 0:
        px = L.px(TITLE["wordmark"])
        sub = Image.new("RGBA", base.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(sub)
        ww = wordmark_width(L, px, fonts)
        draw_wordmark(sd, (L.W - ww) / 2.0, by + L.h(TITLE["gap"]) + px, px, fonts, clamp01(wp) * exit_k)
        layer.alpha_composite(_shift(sub, (1.0 - clamp01(wp)) * L.h(CHAPTER["rise"])))
    return Image.alpha_composite(base, layer)


def credits_frame(img: Image.Image, t: float, *, start: float, blocks, fonts: Fonts) -> Image.Image:
    """End credits over black: a constant-speed roll at 5.2% of frame height
    per second (a projector does not ease), fading in over the first second.
    ``blocks`` is a list of (heading, [lines]). The text is the generator's
    output from sources.json (GRAMMAR 9), never typed here."""
    base = _black(img.size)
    if t < start:
        return base
    L = Layout(*base.size)
    f_h = _font(fonts.data, L.px(CREDITS["heading"]))
    f_l = _font(fonts.structure, L.px(CREDITS["size"]))
    f_n = _font(fonts.data, round(L.px(CREDITS["size"]) * 0.94))
    lh = f_l.size * CREDITS["lh"]
    y = L.H - (t - start) * L.h(CREDITS["speed"])
    a = fade_in(t, start, CREDITS["fade_in"], ease_out_quad)
    x = (L.W - L.w(CREDITS["col_w"])) / 2.0
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for heading, lines in blocks:
        if -lh < y < L.H + lh:
            _draw_tracked(d, (x, y + f_h.size), heading.upper(), f_h, _rgba(PALETTE["safelight"], 0.9 * a), 0.12)
        y += lh * 1.3
        for ln in lines:
            if -lh < y < L.H + lh:
                _draw_mixed(d, (x, y + f_l.size * 0.9), ln, f_l, f_n, _rgba(PALETTE["bone"], a))
            y += lh
        y += lh * 0.8
    return Image.alpha_composite(base, layer)


# --------------------------------------------------------------------------
# Stills: fit at native aspect (GRAMMAR 7.5) and a rostrum move.
# --------------------------------------------------------------------------


def fit_still(still: Image.Image, L: Layout, *, z: float = 1.0, cx: float = 0.5, cy: float = 0.5) -> Image.Image:
    """Letterbox or pillarbox the photograph on the letterbox field, then take
    the window (zoom z about centre cx, cy in 0..1) with bicubic sampling."""
    iw, ih = still.size
    s = min(L.W / iw, L.H / ih)
    fw, fh = iw * s, ih * s
    ox, oy = (L.W - fw) / 2.0, (L.H - fh) / 2.0
    ww, wh = L.W / z, L.H / z
    x0 = min(max(cx * L.W - ww / 2, 0), L.W - ww)
    y0 = min(max(cy * L.H - wh / 2, 0), L.H - wh)
    # map the frame-space window back into image pixels
    def to_img(x, y):
        return ((x - ox) / s, (y - oy) / s)
    a, b = to_img(x0, y0), to_img(x0 + ww, y0 + wh)
    field = Image.new("RGB", (iw, ih))
    out = still.convert("RGB").transform((L.W, L.H), Image.Transform.EXTENT, (a[0], a[1], b[0], b[1]),
                                         resample=Image.Resampling.BICUBIC, fillcolor=PALETTE["letterbox"])
    return out


def rostrum_move(still: Image.Image, L: Layout, t: float, dur: float, frm: dict, to: dict) -> Image.Image:
    """Ken Burns between two framings {"z", "x", "y"} on the rostrum curve."""
    e = rostrum(t, dur)
    z = frm["z"] + (to["z"] - frm["z"]) * e
    cx = frm.get("x", 0.5) + (to.get("x", 0.5) - frm.get("x", 0.5)) * e
    cy = frm.get("y", 0.5) + (to.get("y", 0.5) - frm.get("y", 0.5)) * e
    return fit_still(still, L, z=z, cx=cx, cy=cy)


# --------------------------------------------------------------------------
# Tables and the demo.
# --------------------------------------------------------------------------


def preset_table() -> str:
    rows = ["| preset | k | c | m | zeta | overshoot | settle (s) | 24 fps | 25 fps | 30 fps | says |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in PRESETS:
        rows.append(f"| `{s.name}` | {s.k:g} | {s.c:g} | {s.m:g} | {s.zeta:.3f} | {100 * s.overshoot():.2f}% | {s.settle_time():.3f} | {s.frames(24)} | {s.frames(25)} | {s.frames(30)} | {s.says} |")
    return "\n".join(rows)


def _demo(out_dir: Path, media: Path, fps: int = 24, seconds: float = 6.0, every: int = 5, size=(1280, 720)) -> None:
    """A 6 s strip: shot A (ARCHIVE, rostrum push) with the watermark settling
    and a flagged lower third; a cut to shot B (RECONSTRUCTED, 4-frame class
    fade); a dip to black; a chapter card. PNG every ``every`` frames."""
    fonts = Fonts()
    L = Layout(*size)
    out_dir.mkdir(parents=True, exist_ok=True)
    a = Image.open(media / "S-038.jpg").convert("RGB")
    b = Image.open(media / "S-036.jpg").convert("RGB")
    # Demo text is layout sample only: never attribute invented words to a real
    # person or document (GRAMMAR section 1). Dates are the year depicted.
    shots = [dict(start=0.0, cls="ARCHIVE", detail="Wikimedia Commons 1947"),
             dict(start=3.0, cls="ARCHIVE", detail="Wikimedia Commons 1947"),
             dict(start=5.0, cls="CARD", detail="")]
    lt_lines = ["Sample speaker", "Role, year (layout sample)",
                "Source title, archive  ·  read by a computer voice"]
    flag = "Account of a named government, year (layout sample)"
    cue = "Sample subtitle, line one of two,\nfor layout only."
    dip_start, dip = 4.5, 0.5
    n = int(round(seconds * fps))
    for f in range(0, n, every):
        t = f / fps
        if t < 3.0:
            frame = rostrum_move(a, L, t, 3.0, {"z": 1.0}, {"z": 1.12})
        elif t < 5.0:
            frame = rostrum_move(b, L, t - 3.0, 2.0, {"z": 1.15, "x": 0.35}, {"z": 1.15, "x": 0.65})
        else:
            frame = Image.new("RGB", size, PALETTE["black"])
        frame = frame.convert("RGBA")
        if t < 5.0:
            lvl = dip_level(t - dip_start, dip) if dip_start <= t < dip_start + dip else 1.0
            if lvl < 1.0:
                arr = np.asarray(frame, dtype=np.float32)
                arr[..., :3] *= lvl
                frame = Image.fromarray(arr.astype(np.uint8))
            frame = lower_third_frame(frame, t, start=0.4, end=4.4, lines=lt_lines, fonts=fonts, flag=flag)
            if 0.4 <= t < 4.4:
                top = lower_third_top(L, lt_lines, fonts, flag=flag)
                frame = subtitle_frame(frame, cue, fonts.structure_medium, raise_above=top,
                                       alpha=fade_out(t, 4.4, 0.5) * fade_in(t, 0.4, 0.2))
            frame = watermark(frame, t, start=0.0, card_spans=[(5.0, 6.5)])
        else:
            frame = chapter_card_frame(frame, t, start=5.0, end=9.0, number=4, title="The roads",
                                       dates="August to November 1947", fonts=fonts)
        frame = mark_plate_frame(frame, t, shots, fonts)
        frame.convert("RGB").save(out_dir / f"f{f:04d}.png")
    print(f"demo: {len(range(0, n, every))} frames -> {out_dir}")


def _youtube_watermark(path: Path) -> None:
    """150x150 transparent PNG for YouTube's branding watermark: the logomark in
    bone with its ember, no halo (YouTube draws it at its own low opacity)."""
    img = draw_logomark(150, halo=0.0)
    img.save(path)
    print(f"youtube watermark -> {path}")


if __name__ == "__main__":
    import sys
    here = Path(__file__).resolve().parent
    if "--table" in sys.argv:
        print(preset_table())
        for s in PRESETS:
            print(s.name, s.css_linear())
        sys.exit(0)
    _youtube_watermark(here / "watermark-youtube-150.png")
    _demo(here / "demo", here / "_media")
