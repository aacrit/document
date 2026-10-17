"""void document: the on-film motion system, frame-exact in pure Python.

Everything here is a function of time. Nothing keeps state, nothing writes a
file (except the demo under ``__main__``), and every curve has a closed form,
so the studio renders the same pixel for the same ``t`` on every run.

    python design/brand-kit/motion.py            # 6 s demo strip -> design/brand-kit/demo/
    python design/brand-kit/motion.py --table    # preset table (settle times)

It lives in the studio engine (``studio/engine/motion.py``), which renders
films with it; ``design/brand-kit/motion.py`` re-exports it so the kit's CLI
and preview keep working from the kit folder.

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
# Palette. Every tuple cites a custom property in design/tokens.css, except
# the film's black: on film, black is black with every pixel off (founder ruling
# 2026-10-10 from the teaser), so card grounds, black under a voice, pillarbox
# and letterbox fields and a dip's black hold are RGB 0,0,0. The site's theatre
# black (--doc-black) stays as tokens.css has it.
# --------------------------------------------------------------------------

PALETTE = {
    "black": (0, 0, 0),             # film black, all pixels off (founder ruling; the site uses --doc-black)
    "letterbox": (0, 0, 0),         # pillarbox and letterbox fields: the same black
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
# A16 (founder revamp, 2026-10-10): on-screen information is subtle. The provenance label and the lower
# third's lines arrive on `whisper`: a quiet, near-critical spring that settles in 9 frames with no visible
# travel, so the words seem to surface rather than land.
WHISPER = Spring("whisper", 380, 38, 1.0, says="a provenance label or a lower third's line surfaces, then is let go")
# A32 (R5b, BRAND-KIT 13): a line drawn on over an archive map arrives along its length on `trace`, slow
# enough for the eye to follow it across the frame (zeta 0.88, settles in 1.56 s; its 0.31% overshoot is
# clamped, so a line never draws past its cited end). `drift` is too quick for that and `rostrum` is a camera curve.
TRACE = Spring("trace", 14, 7.5, 1.3, says="a line is drawn on over an archive map, along its length")
PRESETS = (STAMP, SETTLE, ARRIVE, DRIFT, WHISPER, TRACE)

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


DIP_HOLD_MIN_FRAMES = 2            # E15: a dip's black hold is never shorter than 2 frames (BRAND-KIT 6, 11c)
_DIP_EPS = 1e-9                    # frame times are floats: a frame on the hold's edge is in the hold


def dip_hold_s(dur: float, hold: float = 0.10, fps: float = 24.0) -> float:
    """Seconds of black at the bottom of a dip of ``dur`` seconds: ``hold`` of
    the duration, and never under DIP_HOLD_MIN_FRAMES frames (E15: at 0.5 s
    the 10% hold was 1.2 frames, so a frame-sampled dip showed one black frame)."""
    return max(hold * dur, DIP_HOLD_MIN_FRAMES / fps)


def dip_level(t: float, dur: float, hold: float = 0.10, fps: float = 24.0) -> float:
    """Picture level 0..1 through a dip to black of ``dur`` seconds: fade out
    (ease-in, the picture is released), black for ``dip_hold_s`` centred on
    the cut, fade in (ease-out, the next picture arrives). The fades share
    what the hold leaves: 45% each when the hold is 10% of the dip."""
    if dur <= 0:
        return 1.0
    u = t / dur
    a = 0.5 * (1.0 - min(1.0, dip_hold_s(dur, hold, fps) / dur))
    if u < a - _DIP_EPS:
        return 1.0 - ease_in_quad(u / a) if a > 0 else 0.0
    if u <= 1.0 - a + _DIP_EPS:
        return 0.0
    return ease_out_quad((u - (1.0 - a)) / a)


def dip_black_frames(dur: float, fps: float = 24.0) -> int:
    """How many frames of a dip of ``dur`` seconds, its cut on a frame, are
    entirely black when the dip is sampled at ``fps`` (the renderer samples
    frame k after the cut at ``dur / 2 + k / fps``)."""
    n = int(math.ceil(dur * fps)) + 1
    return sum(1 for k in range(-n, n + 1) if 0.0 <= dur / 2 + k / fps <= dur and dip_level(dur / 2 + k / fps, dur, fps=fps) <= 0.0)


def fade_out(t: float, end: float, dur: float) -> float:
    """1 until end - dur, then an ease-in fade to 0 at ``end``."""
    if t <= end - dur:
        return 1.0
    return 1.0 - ease_in_quad((t - (end - dur)) / dur)


def fade_in(t: float, start: float, dur: float, ease=ease_out_sine) -> float:
    if t <= start:
        return 0.0
    return ease((t - start) / dur)


def let_go(t: float, end: float, dur: float) -> float:
    """A16's departure ("ease out"): 1 until end - dur, then a sine in-out fade
    to 0 at ``end``. Gentler than ``fade_out``'s ease-in: a quiet element is
    let go, not released, so its last frames thin out instead of dropping."""
    if t <= end - dur:
        return 1.0
    if t >= end:
        return 0.0
    return 1.0 - sine_inout((t - (end - dur)) / dur)


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


LT = dict(                 # lower third (A16: quieter than the G2 kit in size, weight and opacity; it comes and goes)
    x=4.0,                 # % of W, left edge (aligned with the provenance glyph)
    bottom=92.0,           # % of H, bottom edge of the last line's box
    max_w=56.0,            # % of W
    rule_len=5.0,          # % of W (was 7.5)
    rule_h=0.14,           # % of H (1.5 px at 1080p; was 0.19)
    flag=2.0, name=3.3, role=2.1, source=1.8,        # font sizes, % of H (were 4.4, 2.8, 2.3)
    lh_flag=1.4, lh_name=1.1, lh_role=1.3, lh_source=1.3,
    gap_flag=0.5, gap_rule=0.6, gap_name=0.5, gap_role=0.4,   # % of H
    # Flagged (partisan-source) form: the flag stays the first and largest line, set in
    # Fraunces 300 italic above the rule; the name steps down under it, so the viewer
    # learns whose account this is before who speaks. The source must fit one line.
    flag_f=2.9, name_f=2.7, lh_flag_f=1.1, gap_flag_f=0.4, gap_rule_f=0.5, gap_role_f=0.35,
    rise=0.35,             # % of H, the vertical travel of an arriving line (was 0.8)
    stagger=4 / 24,        # s between arrivals (4 frames at 24 fps)
    exit=0.6,              # s, the departure (let_go, sine in-out; was a 0.5 s ease-in)
    hold=4.0,              # s the block holds after its last line settles, then it goes (A16)
    wash=0.36,             # peak alpha of the wash (was 0.5)
    wash_w=52.0,           # % of W the wash reaches (was 62)
    wash_feather=4.0,      # % of H above the block
    a_flag=0.94, a_name=0.88, a_role=0.74, a_source=0.62, a_rule=0.55,   # text opacity per line (was 1.0; rule 0.85)
)
# A16's lower third is on screen for at most its arrival, LT.hold and its departure, whatever the screenplay's end.
LT_MAX_S = 3 * LT["stagger"] + WHISPER.settle_time() + LT["hold"] + LT["exit"]
# A16: the provenance label and the class glyph. The label ("Archive · 1947") surfaces on `whisper`, holds and is
# let go; the glyph (a small mark in the class hue) stays on every frame. A31 (R2, founder 2026-10-11): bottom right,
# smaller and fainter, and the label surfaces only when the class or the year changes (BRAND-KIT 12).
LABEL = dict(
    right=4.0,             # % of W from the frame's right edge to the glyph box's right edge (the watermark's right inset)
    bottom=5.0,            # % of H from the frame's bottom edge to the glyph box's bottom edge (the watermark's top inset)
    glyph=0.85,            # % of H, the glyph's diameter (9 px at 1080p, 6 at 720p), never under 4 px
    glyph_min_px=4,
    size=1.6,              # % of H, the label's text (17 px at 1080p, 12 at 720p; A16 was 1.85, the G2 plate 3.1)
    gap=0.55,              # em of the label's size between the text and the glyph
    alpha=0.6,             # the label text's opacity (A16 was 0.72; the G2 plate's text was opaque on a 60% scrim)
    drift=0.25,            # em: the text surfaces this far toward the glyph (to the right of its rest) as it arrives
    shadow=0.42,           # alpha of the soft black shadow under the text and around the glyph (no box)
    blur=0.11,             # % of H, the shadow's blur radius
    halo=0.12,             # % of H, the dark contact ring around the glyph (at least 1 px)
    hold=2.0,              # s the label holds after it has surfaced (A16 was 3.0)
    exit=0.75,             # s, its departure (let_go)
    fade=4 / 24,           # s, the glyph's linear crossfade when the class changes (GRAMMAR 4.1, 4 frames)
)
LABEL_MAX_S = WHISPER.settle_time() + LABEL["hold"] + LABEL["exit"]
# A31 (CoS 2026-10-11): the AI-GENERATED label is a truth label, up for the whole shot; it keeps A16's size and
# opacity so it stays readable at the new, smaller corner.
LABEL_AI = dict(size=1.85, alpha=0.72,
                # a heavier shadow (CoS 2026-10-11): darker, wider and denser than the others', so the words hold on a
                # bright, busy ground at 720p; the other classes keep LABEL.shadow, LABEL.blur and a gain of 1.8
                shadow=0.78, blur=0.16, gain=2.8)
LABEL_SHADOW_GAIN = 1.8


def label_shadow(cls: str | None) -> tuple[float, float, float]:
    """The label's shadow for a class: alpha, blur (% of H) and gain on the blurred coverage."""
    if cls == "AI-GENERATED":
        return LABEL_AI["shadow"], LABEL_AI["blur"], LABEL_AI["gain"]
    return LABEL["shadow"], LABEL["blur"], LABEL_SHADOW_GAIN


def label_type(cls: str | None) -> tuple[float, float]:
    """The label's size (% of H) and opacity for a class."""
    if cls == "AI-GENERATED":
        return LABEL_AI["size"], LABEL_AI["alpha"]
    return LABEL["size"], LABEL["alpha"]
# The class glyph's shape, so classes that share a hue still differ (DRAWN and AI-GENERATED are both cold blue).
# Every shape but the ring is solid at its centre; only the square is solid at its top-left corner; only the ring is
# hollow at its centre (A31, CoS 2026-10-11: CARD gets a ring, so a card's bone mark no longer reads as RECONSTRUCTED's
# bone dot). The mark-coverage lint compares the centre and the corner with what the shot's own class composes there
# over the picture before the mark, so every shape is told apart from every other at the same hue. At 4 to 9 px a dot
# and a diamond read alike, so an AI-GENERATED shot also keeps its label up for the whole shot (A16 refined).
GLYPH_SHAPE = {"ARCHIVE": "dot", "RECONSTRUCTED": "dot", "CARD": "ring", "DRAWN": "square", "AI-GENERATED": "diamond"}
RING_STROKE = 0.25                 # the ring's stroke, a share of the glyph's diameter (at least 1 px): hollow at the centre
CLASS_WORD = {"ARCHIVE": "Archive", "RECONSTRUCTED": "Reconstructed", "AI-GENERATED": "AI-generated", "DRAWN": "Drawn",
              "CARD": "void document"}
WM = dict(box=6.0, right=4.0, top=5.0, opacity=0.36, spread=0.08, halo=0.22, fade=0.5)   # A16: was 0.6 and 0.35
SUB = dict(size=3.9, bottom=93.0, max_w=84.0, gap=1.2, lh=1.45, lh_nastaliq=1.9)
CHAPTER = dict(title=5.6, dates=2.6, rule_len=6.0, rule_h=0.19, baseline=47.0, rise=0.6, exit=0.4)
SILENT = dict(size=4.0, lh=1.35, searched=2.6, max_w=76.0, fade=0.75, stagger=0.33,
              # E15: every element of a statement card is drawn; the block sits in the safe band (% of H) and
              # steps down in size (never under min_scale) rather than lose a word
              gap=1.2, safe_top=10.0, safe_bottom=90.0, min_scale=0.75, scale_step=0.05)
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


class TextOverflow(ValueError):
    """Text that does not fit where it is drawn. The engine never cuts text to
    fit (E15: a card lost its third element and three quotes lost their ends
    to a silent ``lines[:2]``); it refuses and says what does not fit."""


def _wrap(text: str, font, data_font, max_w: float, max_lines: int | None = None, what: str = "text") -> list[str]:
    """Greedy word wrap at ``max_w`` px. Every word is kept: past ``max_lines``
    lines this raises TextOverflow, it never drops a line."""
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
    if max_lines is not None and len(lines) > max_lines:
        raise TextOverflow(f"{what} wraps to {len(lines)} lines; at most {max_lines} fit: {text!r}")
    return lines


def _ws_words(text: str) -> str:
    return " ".join(str(text or "").split())


class TextUndrawable(TextOverflow):
    """A character with no glyph in the font that would draw it: FreeType
    would draw the font's empty box (.notdef) in its place, which is a word
    cut as surely as a dropped line (E15)."""


SAFE_W = 90.0                      # % of W: a one-line text (a card's title, a chapter line, its dates) stays inside


@lru_cache(maxsize=32)
def font_cmap(path: str) -> frozenset:
    """The code points the font file maps to a glyph: its best Unicode cmap,
    read by fontTools from the .woff or .ttf itself. Whether a character can
    be drawn is a fact of the file, not of how a FreeType build renders a
    missing one (the empty-box comparison this replaces differed between
    Windows and Linux CI)."""
    from fontTools.ttLib import TTFont
    with TTFont(path, lazy=True) as f:
        return frozenset((f.getBestCmap() or {}).keys())


def _has_glyph(path: str, size: int, ch: str) -> bool:
    # only the plain space and a line break are never drawn; every other character, every other space (U+00A0,
    # U+2007, U+2009, U+202F, U+205F, U+3000 ...) and every combining mark must be in the face's cmap (E15 review)
    if ch in (" ", "\n"):
        return True
    return ord(ch) in font_cmap(path)


def missing_glyphs(text: str, font, data_font=None) -> list[str]:
    """The characters of ``text`` that its font has no glyph for (numeral runs
    are read in ``data_font`` when one is given, as they are drawn)."""
    out = set()
    runs = _runs(str(text or "")) if data_font is not None else [(str(text or ""), False)]
    for frag, num in runs:
        f = data_font if num else font
        out |= {ch for ch in frag if not _has_glyph(f.path, f.size, ch)}
    return sorted(out)


def check_text(text: str, font, data_font=None, *, max_w: float | None = None, what: str = "text") -> float:
    """Every character has a glyph, and the one line fits ``max_w`` px; returns
    its width. Raises TextUndrawable or TextOverflow: nothing is cut."""
    miss = missing_glyphs(text, font, data_font)
    if miss:
        raise TextUndrawable(f"{what}: no glyph for {''.join(miss)!r} in {Path(font.path).name}: {text!r}")
    w = _measure(str(text or ""), font, data_font)
    if max_w is not None and w > max_w + 0.5:
        raise TextOverflow(f"{what} is {w:.0f} px wide; at most {max_w:.0f} px fit on one line: {text!r}")
    return w


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
    """The in-film watermark: the logomark, top right, bone at 36% (A16; the G2
    kit had 60%) with a faint black halo, 6% of frame height. At ``start`` it settles once (corners close from
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
# The provenance mark (GRAMMAR 4, amendment A16): a quiet label at each shot
# change that is let go after about 3 s, and a small class glyph in the corner
# that stays on every frame. Together they replace the G2 plate (A1).
# --------------------------------------------------------------------------


LABEL_MIN_X = 60.0                  # % of W: a provenance label starts right of the lower third's measure (A31; E15 ended it by 50%)
# A31: the zone the mark may occupy (fractions of the frame: x0, y0, x1, y1): the longest label from LABEL_MIN_X to the
# glyph, from the top of its words to the title-safe line. Clear of the subtitle cue (bottom at SUB.bottom, 93%), the
# overlay (bottom at 92%), the lower third (its measure ends at 60% of width) and the watermark (top right).
MARK_ZONE = (LABEL_MIN_X / 100.0, 0.93, 1.0 - LABEL["right"] / 100.0, 0.965)
# The glyph's own box with its contact disc and a margin (fractions of the frame): on every frame, so nothing else
# (a map's text, a count card's source line) may enter it. At 1080p the glyph is x 1834 to 1842, y 1017 to 1025.
MARK_GLYPH_ZONE = (0.950, 0.935, 0.966, 0.956)


def label_check(L: Layout, text: str, fonts: Fonts, cls: str | None = None) -> float:
    """A provenance label is one line, every glyph present, from at least
    LABEL_MIN_X of the width to the glyph, or TextOverflow (E15, A31). An
    AI-GENERATED label is checked at its own, larger size."""
    px = L.px(label_type(cls)[0])
    w = check_text(text, _font(fonts.structure, px), _font(fonts.data, max(1, round(px * 0.94))), what="a provenance label")
    left = label_right(L, cls) - w
    if left < L.w(LABEL_MIN_X) - 0.5:
        raise TextOverflow(f"a provenance label starts at {100 * left / L.W:.1f}% of the width; it starts right of "
                           f"{LABEL_MIN_X:g}% (the lower third's measure): {text!r}")
    return w


def mark_label(cls: str, year: str | None = None, extra: str = "") -> str:
    """The label's words, sentence case: ``Archive · 1947``,
    ``Reconstructed · 1946 · colour cast removed``, ``Drawn · from Natural
    Earth``. A CARD carries the glyph alone (``label_starts`` gives it no
    label): the card's own words say what it is."""
    parts = [CLASS_WORD[cls]] + [p for p in (year, extra) if p]
    return " · ".join(parts)


def glyph_px(L: Layout) -> int:
    return max(LABEL["glyph_min_px"], L.px(LABEL["glyph"]))


def glyph_origin(L: Layout) -> tuple[int, int]:
    """Top-left pixel of the glyph's box (A31): its right edge LABEL.right of
    the width in from the frame's right edge and its bottom edge LABEL.bottom
    of the height up from the frame's bottom, the watermark's insets mirrored
    into the opposite corner."""
    d = glyph_px(L)
    return int(round(L.W - L.w(LABEL["right"]))) - d, int(round(L.H - L.h(LABEL["bottom"]))) - d


def label_baseline(L: Layout, cls: str | None = None) -> float:
    """The label's baseline (px): the glyph sits at the middle of its x-height."""
    _, gy = glyph_origin(L)
    return gy + glyph_px(L) / 2.0 + 0.36 * L.px(label_type(cls)[0])


def label_right(L: Layout, cls: str | None = None) -> float:
    """Where the label's words end (px), at rest: LABEL.gap em left of the
    glyph box. The words are set flush right against the glyph, so the glyph
    never moves and the label grows leftward from it."""
    gx, _ = glyph_origin(L)
    return gx - LABEL["gap"] * L.px(label_type(cls)[0])


def glyph_corner(L: Layout) -> tuple[int, int]:
    """The glyph box's top-left pixel: solid only in the square (DRAWN)."""
    return glyph_origin(L)


def glyph_shape_probes(L: Layout) -> list[tuple[int, int]]:
    """Where the mark-coverage lint reads the shape: the glyph box's top-left
    pixel, the one right of it, and the glyph's centre (A31). The corner pair
    is solid in the square; in the dot, the diamond and the ring it lies under
    the glyph's edge and its contact disc. The centre is solid in the dot,
    the square and the diamond and hollow in the ring, where the contact disc
    shows. At every engine resolution, for every pair of classes that share a
    hue and differ in shape (DRAWN and AI-GENERATED; RECONSTRUCTED and CARD),
    some probe has a channel where no picture value 0 to 255 brings the wrong
    shape's composite within 1 of the right one's
    (test_a16_the_shape_check_cannot_be_reached_by_any_picture_at_the_film_resolutions)."""
    x, y = glyph_origin(L)
    return [(x, y), (x + 1, y), glyph_centre(L)]


def glyph_centre(L: Layout) -> tuple[int, int]:
    """The pixel at the glyph's centre: solid in the dot, the square and the
    diamond, hollow in the ring (A31). The mark-coverage lint reads it as a
    shape probe and, in a class change's crossfade, as the hue."""
    x, y = glyph_origin(L)
    d = glyph_px(L)
    return x + d // 2, y + d // 2


def _glyph(cls: str, d: int, ss: int = 4) -> Image.Image:
    """The class glyph, d x d px: the hue in every pixel and the shape in the
    alpha only, so a fully covered pixel is exactly the class hue. Drawn 4x
    and box-filtered down, which keeps the centre opaque at any size."""
    big = d * ss
    mask = Image.new("L", (big, big), 0)
    dm = ImageDraw.Draw(mask)
    shape = GLYPH_SHAPE[cls]
    if shape == "square":
        dm.rectangle([0, 0, big - 1, big - 1], fill=255)   # the whole box: its corner pixel is solid, which no other shape's is
    elif shape == "ring":
        w = max(1.0, RING_STROKE * d) * ss
        dm.ellipse([0, 0, big - 1, big - 1], fill=255)
        dm.ellipse([w, w, big - 1 - w, big - 1 - w], fill=0)
    elif shape == "diamond":
        c = (big - 1) / 2.0
        dm.polygon([(c, 0), (big - 1, c), (c, big - 1), (0, c)], fill=255)
    else:
        dm.ellipse([0, 0, big - 1, big - 1], fill=255)
    img = Image.new("RGBA", (d, d), MARK_HUE[cls] + (0,))
    img.putalpha(mask.resize((d, d), Image.BOX))
    return img


@lru_cache(maxsize=32)
def glyph_tile(W: int, H: int, cls: str) -> tuple[Image.Image, tuple[int, int]]:
    """The glyph over its dark contact disc, as a small tile and the frame
    pixel its top-left lands on. The disc is round for every shape, 0.12% of
    height (at least 1 px) wider than the glyph on each side, black at
    LABEL.shadow alpha, antialiased; a square's corners overhang it."""
    L = Layout(W, H)
    d = glyph_px(L)
    x, y = glyph_origin(L)
    ring = max(1, L.px(LABEL["halo"]))
    size = d + 2 * ring
    big = size * 4
    halo = Image.new("L", (big, big), 0)
    ImageDraw.Draw(halo).ellipse([0, 0, big - 1, big - 1], fill=int(round(255 * LABEL["shadow"])))
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    tile.putalpha(halo.resize((size, size), Image.BOX))
    tile.alpha_composite(_glyph(cls, d), (ring, ring))
    return tile, (x - ring, y - ring)


def _glyph_layer(W: int, H: int, cls: str) -> Image.Image:
    """The glyph tile on a full-frame transparent layer (for tests and the kit)."""
    tile, at = glyph_tile(W, H, cls)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    layer.alpha_composite(tile, at)
    return layer


LABEL_STAYS = {"AI-GENERATED"}       # A16 refined (CoS, T1e review): this label never fades; it stays the whole shot


def label_alpha(t: float, start: float, cls: str | None = None) -> float:
    """The label's opacity factor (0..1) at ``t`` for a label that surfaced at
    ``start``: up on `whisper`, held LABEL.hold s, let go over LABEL.exit s;
    0 from LABEL_MAX_S on. An AI-GENERATED label is at full opacity from
    the cut frame and never goes (a dissolve joins two shots of one class
    (GRAMMAR 4.4), so it stays up through one too)."""
    if t < start:
        return 0.0
    u = t - start
    if cls in LABEL_STAYS:
        return 1.0                       # the class is never hidden: full from the cut frame, no arrival
    if u >= LABEL_MAX_S:
        return 0.0
    return clamp01(WHISPER.progress(u)) * let_go(u, LABEL_MAX_S, LABEL["exit"])


_YEAR = re.compile(r"(?<!\d)(\d{4})(?!\d)")


def mark_key(shot: dict) -> tuple[str, str | None]:
    """What a label says that the glyph does not (A31): the class and the
    year. The year is the shot's ``year`` when it states one (the engine's
    plan does), else the first four-digit year in its label's words."""
    if "year" in shot:
        y = shot["year"]
    else:
        m = _YEAR.search(shot.get("label") or "")
        y = m.group(1) if m else None
    return shot["cls"], (str(y) if y not in (None, "") else None)


def label_plan(shots) -> list[dict]:
    """Per shot (``shots`` sorted by start): ``start``, when the label it
    shows surfaced (None: glyph only), and ``surfaces``, whether it surfaces
    at this shot's cut (A31, founder 2026-10-11). A label surfaces at the
    film's first picture shot and wherever the class or the year differs from
    the previous picture shot's (cards are not compared: a card carries the
    glyph alone). At a direct cut into a shot with the same class and year
    the label already up runs on, its words swapped on the cut frame (within
    a class the swap is hard, BRAND-KIT 5), and lets go on its own time. An
    AI-GENERATED shot is labelled for the whole shot, from its cut frame,
    whatever came before (A16 refined: the class is never hidden)."""
    out: list[dict] = []
    prev_key = None
    for k, s in enumerate(shots):
        if s["cls"] == "CARD" or not s.get("label"):
            out.append({"start": None, "surfaces": False})
            continue
        key = mark_key(s)
        surfaces = prev_key is None or key != prev_key
        start = None
        if s["cls"] in LABEL_STAYS or surfaces:
            start = s["start"]
        elif k > 0 and out[k - 1]["start"] is not None and shots[k - 1]["cls"] != "CARD" and shots[k - 1].get("label"):
            start = out[k - 1]["start"]          # the same class and year across a cut: the label runs on
        out.append({"start": start, "surfaces": surfaces})
        prev_key = key
    return out


def label_starts(shots) -> list[float | None]:
    """When the label each shot shows surfaced (``shots`` sorted by start), or
    None for the glyph alone (A31: only on a change of class or year; see
    ``label_plan``). A CARD has no label (the card's own words say what it is)."""
    return [e["start"] for e in label_plan(shots)]


def label_surfacings(shots) -> list[float]:
    """The times a label surfaces in the film (A31), for the label-rate lint."""
    ss = sorted(shots, key=lambda s: s["start"])
    return [s["start"] for s, e in zip(ss, label_plan(ss)) if e["surfaces"]]


def mark_state(t: float, shots) -> dict | None:
    """What the mark shows at ``t``. ``shots`` are dicts with ``start``,
    ``cls`` and ``label``. Returns the class, the outgoing class and the
    glyph's crossfade weight, and the label with its opacity factor."""
    ss = sorted(shots, key=lambda s: s["start"])
    starts = label_starts(ss)
    cur = prev = None
    for k, s in enumerate(ss):
        if s["start"] <= t:
            prev, cur = cur, k
    if cur is None:
        return None
    s = ss[cur]
    p = ss[prev] if prev is not None else None
    u = (t - s["start"]) / LABEL["fade"]
    mix = clamp01(u) if (p is not None and p["cls"] != s["cls"] and u < 1.0) else 1.0
    la = label_alpha(t, starts[cur], s["cls"]) if starts[cur] is not None else 0.0
    return {"cls": s["cls"], "prev_cls": p["cls"] if p is not None else None, "mix": mix,
            "label": s.get("label") or "", "label_alpha": la, "label_start": starts[cur]}



def _label_tile(L: Layout, text: str, alpha: float, dx: float, fonts: Fonts,
                cls: str | None = None) -> tuple[Image.Image, tuple[int, int]]:
    """The label's words left of the glyph, set flush right against it (A31),
    near-white at LABEL.alpha over a soft black shadow (no box), numerals in
    the data face, drawn and blurred on a crop around the words only, and the
    frame pixel the crop lands on. The crop stops short of the glyph's tile,
    so the label never touches a pixel the mark-coverage lint reads."""
    from PIL import ImageFilter
    size, opacity = label_type(cls)
    px = L.px(size)
    f_txt = _font(fonts.structure, px)
    f_num = _font(fonts.data, max(1, round(px * 0.94)))
    gx, _ = glyph_origin(L)
    x = label_right(L, cls) - _measure(text, f_txt, f_num) + dx
    baseline = label_baseline(L, cls)
    sh_alpha, sh_blur, sh_gain = label_shadow(cls)
    radius = max(1.0, L.h(sh_blur))
    margin = int(math.ceil(3 * radius)) + 2
    x0, y0 = max(0, int(math.floor(x)) - margin), max(0, int(math.floor(baseline - 1.1 * px)) - margin)
    x1 = max(x0, min(gx - max(1, L.px(LABEL["halo"])), int(math.ceil(x + _measure(text, f_txt, f_num))) + margin + 1))
    y1 = min(L.H, int(math.ceil(baseline + 0.4 * px)) + margin + 1)
    words = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
    _draw_mixed(ImageDraw.Draw(words), (x - x0, baseline - y0), text, f_txt, f_num,
                _rgba(PALETTE["mark_text"], opacity * alpha))
    # the shadow: the words' own coverage, blurred, in black at LABEL.shadow (scaled with the label's opacity)
    cover = np.asarray(words.getchannel("A"), dtype=np.float32) / max(opacity * alpha, 1e-6)
    blurred = Image.fromarray(np.clip(cover, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius))
    sh = np.clip(np.asarray(blurred, dtype=np.float32) * sh_gain, 0, 255) * (sh_alpha * alpha)
    out = Image.new("RGBA", words.size, (0, 0, 0, 0))
    out.putalpha(Image.fromarray(sh.astype(np.uint8)))
    out.alpha_composite(words)
    return out, (x0, y0)


def mark_frame(img: Image.Image, t: float, shots, fonts: Fonts) -> Image.Image:
    """Draw the provenance mark at ``t`` (A16, A31: bottom right). ``shots``
    holds dicts with ``start`` (s), ``cls``, ``label`` and optionally
    ``year``. The glyph is on every frame: a hard swap within a class, a
    4-frame linear crossfade when the class changes (both glyphs are opaque
    at the centre, so the pixel there is exactly the mix of the two hues).
    The label surfaces only when the class or the year changes, drifting a
    quarter em from the glyph to its rest, and is let go after about 2 s;
    an AI-GENERATED label is full from the cut frame and stays. Only small
    tiles are drawn and composited, never full-frame layers."""
    out = _as_rgba(img)
    st = mark_state(t, shots)
    if st is None:
        return out
    L = Layout(*out.size)
    tile, at = glyph_tile(L.W, L.H, st["cls"])
    if st["mix"] < 1.0:
        tile = Image.blend(glyph_tile(L.W, L.H, st["prev_cls"])[0], tile, st["mix"])
    out.alpha_composite(tile, at)
    if st["label_alpha"] > 0.0 and st["label"]:
        u = t - st["label_start"]
        arriving = st["cls"] not in LABEL_STAYS
        dx = (1.0 - clamp01(WHISPER.progress(u))) * LABEL["drift"] * L.px(LABEL["size"]) if arriving else 0.0
        words, wat = _label_tile(L, st["label"], st["label_alpha"], dx, fonts, st["cls"])
        if words.width > 0:
            out.alpha_composite(words, wat)
    return out


mark_plate_frame = mark_frame        # the G2 name, kept so the kit's callers still resolve


# --------------------------------------------------------------------------
# Lower thirds (BRAND-KIT.md section 3). Three formats, one grammar: a flag
# eyebrow (optional), a short rule, then lines that arrive one after another.
# --------------------------------------------------------------------------


def source_line_text(text: str) -> str:
    """A lower third's source line as drawn: ``<source title>, <archive>``,
    except that a title ending in ``?`` or ``!`` takes no comma after it
    (E15: "should our policy be changed?, National Library of Medicine")."""
    return re.sub(r"([?!]),(?=\s)", r"\1", text)


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
        if len(lines) > 2:
            # BRAND-KIT 4: the source wraps to at most 2 lines, 1 under a flag; past that it is refused, never cut (E15)
            src = source_line_text(lines[2])
            try:
                wrapped_src = _wrap(src, f_src, f_src_n, max_w, max_lines=1 if flag else 2, what="a lower third's source line")
            except TextOverflow as e:
                raise TextOverflow(("a flagged lower third's source line must fit on one line: " if flag else "") + str(e)) from None
            for i, wrapped in enumerate(wrapped_src):
                rows.append(("source" if i == 0 else "source2", wrapped, f_src, f_src_n, LT["source"], LT["lh_source"]))
    # E15: a name or a role is never wrapped (BRAND-KIT 8) and never cut: it fits LT.max_w or is refused
    for rk, text, font, dfont, _, _ in rows:
        check_text(text, font, dfont, max_w=max_w, what=f"a lower third's {rk} line")
    if flag:
        check_text(flag, _font(fonts.display_italic, px(LT["flag_f"])), None, max_w=max_w, what="a lower third's flag")
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


def lower_third_span(start: float, end: float) -> tuple[float, float]:
    """A16: a lower third comes and goes. It is on screen from ``start`` for
    at most LT_MAX_S (arrival, a 4 s hold, departure), or until ``end`` when
    the screenplay ends it sooner."""
    return start, min(end, start + LT_MAX_S)


def lower_third_frame(img: Image.Image, t: float, *, start: float, end: float, lines, fonts: Fonts,
                      kind: str = "speaker", flag: str | None = None) -> Image.Image:
    """Draw a lower third at time t. ``lines`` are GRAMMAR 9's lines: for a
    speaker [name, "role, year", "source, archive  ·  read by a computer voice"];
    for a place [place, date]. ``flag`` is the partisan-source eyebrow
    ("Account of the Government of West Punjab, 1948").

    A16, quieter than the G2 kit: smaller type, each line at its own opacity
    (LT.a_*), a lighter wash and a shorter, fainter rule. In: the flag and the
    rule first (the rule draws from its left anchor on `stamp`), then each line
    4 frames after the last, surfacing on `whisper` with a 0.35% of height
    rise. It holds LT.hold s and is let go over LT.exit s (sine in-out), all
    together; nothing leaves by moving. ``end`` is clipped by
    ``lower_third_span``, so a long screenplay span still comes and goes."""
    base = _as_rgba(img)
    start, end = lower_third_span(start, end)
    if t < start or t >= end:
        return base
    L = Layout(*base.size)
    els, top = lower_third_layout(L, lines, fonts, kind, flag)
    x0 = L.w(LT["x"])
    exit_k = let_go(t, end, LT["exit"])
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    rule_p = STAMP.progress(t - start)
    out = Image.alpha_composite(base, _wash(L, top, clamp01(WHISPER.progress(t - start)) * exit_k))
    d = ImageDraw.Draw(layer)
    for e in els:
        t0 = start + e["order"] * LT["stagger"]
        if e["kind"] == "rule":
            p = clamp01(rule_p) * exit_k
            w = e["len"] * p
            if w >= 1:
                d.rectangle([x0, e["top"], x0 + w, e["top"] + e["h"]], fill=_rgba(PALETTE["bone"], LT["a_rule"] * exit_k))
            continue
        p = WHISPER.progress(t - t0) if t >= t0 else 0.0
        if p <= 0.0:
            continue
        line_a = LT["a_flag"] if e["kind"] == "flag" else LT["a_name"] if e["kind"] == "name" else             LT["a_role"] if e["kind"] == "role" else LT["a_source"]
        a = clamp01(p) * exit_k * line_a
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


OVERLAY = dict(right=4.0, bottom=92.0, size=2.8, wash=0.5, wash_w=40.0, feather=4.0, rise=0.8, exit=0.5,
               max_w=56.0)          # E15: the lower third's measure, mirrored


def overlay_frame(img: Image.Image, t: float, *, start: float, end: float, text: str, fonts: Fonts) -> Image.Image:
    """Text over footage (GRAMMAR 9): dates and counts only, one line, bottom
    right, every numeral in the data face (tabular). It mirrors the lower
    third: flush right at 4% of width, its box bottom at 92% of height, held
    by a feathered wash from the right edge, never a box. In: SETTLE with a
    0.8% rise; out: the last 0.5 s, ease-in, nothing moves."""
    base = _as_rgba(img)
    if t < start or t >= end:
        return base
    L = Layout(*base.size)
    px = L.px(OVERLAY["size"])
    f_txt = _font(fonts.structure, px)
    f_num = _font(fonts.data, round(px * 0.94))
    exit_k = fade_out(t, end, OVERLAY["exit"])
    p = clamp01(SETTLE.progress(t - start))
    w = _measure(text, f_txt, f_num)
    x = L.W - L.w(OVERLAY["right"]) - w
    bottom = L.h(OVERLAY["bottom"])
    baseline = bottom - px * 0.3
    top = bottom - px * 1.3
    # the wash, mirrored from the lower third's: dark at the right edge, gone by wash_w
    xs = np.linspace(0.0, 1.0, L.W, dtype=np.float32)[::-1]
    hx = 1.0 - np.clip(xs / (OVERLAY["wash_w"] / 100.0), 0.0, 1.0)
    hx = hx * hx * (3.0 - 2.0 * hx)
    ys = np.arange(L.H, dtype=np.float32)
    fth = L.h(OVERLAY["feather"])
    vy = np.clip((ys - (top - fth)) / fth, 0.0, 1.0)
    vy = vy * vy * (3.0 - 2.0 * vy)
    rgba = np.zeros((L.H, L.W, 4), np.uint8)
    rgba[..., 3] = ((vy[:, None] * hx[None, :]) * (255.0 * OVERLAY["wash"] * p * exit_k)).astype(np.uint8)
    out = Image.alpha_composite(base, Image.fromarray(rgba))
    sub = Image.new("RGBA", base.size, (0, 0, 0, 0))
    _draw_mixed(ImageDraw.Draw(sub), (x, baseline), text, f_txt, f_num, _rgba(PALETTE["mark_text"], p * exit_k))
    return Image.alpha_composite(out, _shift(sub, (1.0 - p) * L.h(OVERLAY["rise"])))


def overlay_check(L: Layout, text: str, fonts: Fonts) -> float:
    """An overlay is one line, flush right at 4% of width: it fits OVERLAY.max_w
    with every glyph, or TextOverflow (E15). Returns its width."""
    px = L.px(OVERLAY["size"])
    return check_text(text, _font(fonts.structure, px), _font(fonts.data, round(px * 0.94)),
                      max_w=L.w(OVERLAY["max_w"]), what="an overlay")


def lower_third_top(L: Layout, lines, fonts: Fonts, kind="speaker", flag=None) -> float:
    """Top edge (px) of a lower third's block, for raising a subtitle above it."""
    return lower_third_layout(L, lines, fonts, kind, flag)[1]


# --------------------------------------------------------------------------
# Subtitles (layout only: the film ships subtitles as tracks, never burned in).
# --------------------------------------------------------------------------


def subtitle_check(L: Layout, text: str, font_path: str, *, nastaliq: bool = False) -> list[float]:
    """A burned cue's lines as written (one per ``\\n``): each fits SUB.max_w of
    the width with every glyph, or TextOverflow (E15). Returns the widths."""
    f = _font(font_path, L.px(SUB["size"]))
    return [check_text(ln, f, max_w=L.w(SUB["max_w"]), what="a burned subtitle line") for ln in str(text).split("\n")]


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
# Cards over black: chapter, record-is-silent, title. All are CARD (the
# mark's glyph is drawn separately by mark_frame so no card forgets it).
# --------------------------------------------------------------------------


def _black(size) -> Image.Image:
    return Image.new("RGBA", size, PALETTE["black"] + (255,))


def chapter_card_layout(L: Layout, number: int, title: str, dates: str, fonts: Fonts) -> dict:
    """The chapter card's two lines as drawn (E15): ``<number>  <title>`` and
    the dates, each one line inside SAFE_W of the width, every glyph present,
    or TextOverflow. ``chapter_card_frame`` draws these records."""
    f_t = _font(fonts.display, L.px(CHAPTER["title"]))
    f_n = _font(fonts.data, L.px(CHAPTER["title"]))
    f_d = _font(fonts.data, L.px(CHAPTER["dates"]))
    num = f"{number}"
    gap = 0.55 * f_t.size
    check_text(num, f_n, what="the chapter number")
    check_text(title, f_t, what="the chapter title")
    w = f_n.getlength(num) + gap + f_t.getlength(title)
    if w > L.w(SAFE_W) + 0.5:
        raise TextOverflow(f"the chapter line is {100 * w / L.W:.1f}% of the width; at most {SAFE_W:g}% fit on one line: "
                           f"{num}  {title!r}")
    dw = check_text(dates, f_d, max_w=L.w(SAFE_W), what="the chapter dates") if dates else 0.0
    return {"fonts": (f_t, f_n, f_d), "gap": gap,
            "lines": [{"role": "title", "text": f"{num} {title}", "num": num, "title": title, "x": (L.W - w) / 2.0, "w": w},
                      {"role": "dates", "text": dates, "x": (L.W - dw) / 2.0, "w": dw}]}


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
    lay = chapter_card_layout(L, number, title, dates, fonts)
    f_t, f_n, f_d = lay["fonts"]
    head, dl = lay["lines"]
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    num, title, gap, x = head["num"], head["title"], lay["gap"], head["x"]
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
        sd.text((dl["x"], ry + L.h(1.2) + f_d.size), dl["text"], font=f_d, fill=_rgba(PALETTE["bone"], clamp01(dp) * 0.8 * exit_k), anchor="ls")
        layer.alpha_composite(_shift(sub, (1.0 - clamp01(dp)) * L.h(CHAPTER["rise"])))
    return Image.alpha_composite(base, layer)


def card_layout(L: Layout, texts, fonts: Fonts, what: str = "card") -> dict:
    """Where every element of a statement card's ``text[]`` is drawn (E15).

    Element 0 is the statement, Fraunces 300 at SILENT.size on SILENT.lh;
    every later element (the Searched line, a source, a filled shortfall
    sentence) is Inter at SILENT.searched on 1.4, SILENT.gap of height above
    it. Each wraps at SILENT.max_w of the width with no line limit, and the
    block is centred. When it is taller than the safe band (SILENT.safe_top
    to SILENT.safe_bottom of the height) every size steps down together by
    SILENT.scale_step, never under SILENT.min_scale (the floor that stays
    readable at 720p: the statement 3.0% of height, 22 px; the rest 1.95%,
    14 px). A card that does not fit at the floor raises TextOverflow: text
    is never cut or dropped.

    Returns ``{"scale", "top", "bottom", "elements": [{"index", "role",
    "text", "px", "lines": [{"text", "x", "baseline", "w"}]}]}``. The drawer
    draws these records and nothing else, so the card-drawn lint compares
    them with the intended text. At scale 1 the arithmetic is the G2 card's,
    so a card that always fitted keeps its pixels."""
    texts = [str(x) for x in (texts or [])]
    for i, tx in enumerate(texts):
        px = L.px(SILENT["size"] if i == 0 else SILENT["searched"])
        check_text(tx, _font(fonts.display if i == 0 else fonts.structure, px), _font(fonts.data, round(px * 0.94)),
                   what=f"{what}, element {i}")
    max_w = L.w(SILENT["max_w"])
    safe_top, safe_bottom = L.h(SILENT["safe_top"]), L.h(SILENT["safe_bottom"])
    steps = int(round((1.0 - SILENT["min_scale"]) / SILENT["scale_step"]))
    tried = []
    for k in range(steps + 1):
        scale = round(1.0 - k * SILENT["scale_step"], 6)
        px1 = L.px(SILENT["size"] * scale)
        px2 = L.px(SILENT["searched"] * scale)
        f1, f1n = _font(fonts.display, px1), _font(fonts.data, round(px1 * 0.94))
        f2, f2n = _font(fonts.structure, px2), _font(fonts.data, round(px2 * 0.94))
        gap = L.h(SILENT["gap"] * scale)
        wrapped = []
        for i, tx in enumerate(texts):
            f, fn = (f1, f1n) if i == 0 else (f2, f2n)
            wrapped.append((i, tx, f, fn, _wrap(tx, f, fn, max_w)))
        too_wide = [ln for (_, _, f, fn, lines) in wrapped for ln in lines if _measure(ln, f, fn) > max_w + 0.5]
        h1 = len(wrapped[0][4]) * f1.size * SILENT["lh"] if wrapped else 0
        h2 = 0
        for (i, _, _, _, lines) in wrapped[1:]:
            h2 += len(lines) * f2.size * 1.4 + (gap if lines else 0)
        y = (L.H - h1 - h2) / 2.0
        top, bottom = y, y + h1 + h2
        tried.append({"scale": scale, "height_pct": round(100.0 * (h1 + h2) / L.H, 2), "too_wide": too_wide})
        if too_wide or (texts and (top < safe_top - 0.5 or bottom > safe_bottom + 0.5)):
            continue
        elements = []
        for (i, tx, f, fn, lines) in wrapped:
            if i == 0:
                recs = []
                for ln in lines:
                    w = _measure(ln, f, fn)
                    recs.append({"text": ln, "x": (L.W - w) / 2.0, "baseline": y + f.size * (0.78 + (SILENT["lh"] - 1) / 2), "w": w})
                    y += f.size * SILENT["lh"]
            else:
                if lines:
                    y += gap
                recs = []
                for ln in lines:
                    w = _measure(ln, f, fn)
                    recs.append({"text": ln, "x": (L.W - w) / 2.0, "baseline": y + f.size * (0.78 + 0.2), "w": w})
                    y += f.size * 1.4
            elements.append({"index": i, "role": "statement" if i == 0 else "line", "text": tx, "px": f.size,
                             "font": f, "data_font": fn, "lines": recs})
        return {"scale": scale, "top": top, "bottom": bottom, "elements": elements}
    last = tried[-1] if tried else {}
    raise TextOverflow(
        f"{what}: its {len(texts)} text elements do not fit the card at the smallest readable size "
        f"({SILENT['size'] * SILENT['min_scale']:.2f}% and {SILENT['searched'] * SILENT['min_scale']:.2f}% of height): "
        + (f"a word is wider than {SILENT['max_w']:g}% of the width ({last['too_wide'][0]!r})" if last.get("too_wide") else
           f"the block is {last.get('height_pct')}% of the height and the safe band is "
           f"{SILENT['safe_bottom'] - SILENT['safe_top']:g}% ({SILENT['safe_top']:g}% to {SILENT['safe_bottom']:g}%)")
        + "; shorten the text or split the card, nothing is cut")


def card_drawn_text(layout: dict) -> list[str]:
    """What a card layout draws, element by element, as one whitespace-normalised string each."""
    return [_ws_words(" ".join(ln["text"] for ln in e["lines"])) for e in layout["elements"]]


def card_text_problems(texts, layout: dict) -> list[dict]:
    """Every element of ``texts`` that the layout does not draw word for word
    (E15): the comparison is between the layout records the drawer draws and
    the intended text, never OCR."""
    drawn = card_drawn_text(layout)
    out = []
    for i, tx in enumerate(texts or []):
        want = _ws_words(tx)
        got = drawn[i] if i < len(drawn) else None
        if got != want:
            out.append({"index": i, "intended": want, "drawn": got})
    return out


def silent_card_frame(img: Image.Image, t: float, *, start: float, end: float, statement: str = "",
                      searched: str | None = None, fonts: Fonts, texts=None) -> Image.Image:
    """A statement card over black: the record-is-silent card, a perspective
    card, a quote with its source. No spring: the graphic is still. Every
    element of ``texts`` (or ``[statement, searched]``) is drawn, laid out by
    ``card_layout`` (E15). Element 0 fades in over 0.75 s (ease-out sine);
    each later element follows SILENT.stagger s after the one before; all
    fade out together over 0.75 s."""
    base = _black(img.size)
    if t < start or t >= end:
        return base
    L = Layout(*base.size)
    if texts is None:
        texts = [statement] + ([searched] if searched else [])
    lay = card_layout(L, texts, fonts)
    exit_k = 1.0 - ease_in_sine((t - (end - SILENT["fade"])) / SILENT["fade"]) if t > end - SILENT["fade"] else 1.0
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for e in lay["elements"]:
        a = fade_in(t, start + e["index"] * SILENT["stagger"], SILENT["fade"]) * exit_k
        if e["index"]:
            a *= 0.8
        for ln in e["lines"]:
            _draw_mixed(d, (ln["x"], ln["baseline"]), ln["text"], e["font"], e["data_font"], _rgba(PALETTE["mark_text"], a))
    return Image.alpha_composite(base, layer)


def wordmark_width(L: Layout, px: int, fonts: Fonts) -> float:
    f_v, f_d = _font(fonts.data, px), _font(fonts.display, px)
    return f_v.getlength("void") + 0.45 * px + f_d.getlength("document")


def draw_wordmark(d: ImageDraw.ImageDraw, x: float, baseline: float, px: int, fonts: Fonts, alpha: float = 1.0):
    """``void`` in the data face, ``document`` in the display face (BRAND.md)."""
    f_v, f_d = _font(fonts.data, px), _font(fonts.display, px)
    d.text((x, baseline), "void", font=f_v, fill=_rgba(PALETTE["bone"], alpha), anchor="ls")
    d.text((x + f_v.getlength("void") + 0.45 * px, baseline), "document", font=f_d, fill=_rgba(PALETTE["bone"], alpha), anchor="ls")


def title_card_layout(L: Layout, title: str, fonts: Fonts) -> dict:
    """The title card's line as drawn (E15): one line inside SAFE_W, every glyph
    present, or TextOverflow; the wordmark beneath is fixed."""
    f_t = _font(fonts.display, L.px(TITLE["size"]))
    w = check_text(title, f_t, max_w=L.w(SAFE_W), what="the film title")
    return {"font": f_t, "lines": [{"role": "title", "text": title, "x": (L.W - w) / 2.0, "w": w},
                                   {"role": "wordmark", "text": "void document"}]}


def title_card_frame(img: Image.Image, t: float, *, start: float, end: float, title: str, fonts: Fonts) -> Image.Image:
    """Film title on one line, ``void document`` beneath (GRAMMAR 9), 5 s, CARD.
    In: the title arrives on ARRIVE (rise 0.6% of H); the wordmark on SETTLE
    0.4 s later. Out: a 0.67 s ease-in fade."""
    base = _black(img.size)
    if t < start or t >= end:
        return base
    L = Layout(*base.size)
    exit_k = fade_out(t, end, TITLE["exit"])
    lay = title_card_layout(L, title, fonts)
    f_t = lay["font"]
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    p = ARRIVE.progress(t - start)
    sub = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(sub)
    by = L.h(50.0)
    sd.text((lay["lines"][0]["x"], by), title, font=f_t, fill=_rgba(PALETTE["bone"], clamp01(p) * exit_k), anchor="ls")
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


# --------------------------------------------------------------------------
# The mark key (A31, R2): "What the marks mean", each picture class's glyph
# with its word, drawn from the class table (GLYPH_SHAPE, MARK_HUE,
# CLASS_WORD), never from typed colours or words. After the title card and
# again in the end sequence, before the attribution card.
# --------------------------------------------------------------------------

KEY = dict(
    heading=4.0,           # % of H, Fraunces 300: the statement card's size (43 px at 1080p, 29 at 720p)
    word=2.6,              # % of H, Inter 400 in --mark-text: the statement card's second line (28 / 19 px)
    glyph=1.7,             # % of H, the glyph drawn large enough to read its shape (18 / 12 px)
    gap=0.6,               # em of the word's size between the glyph and its word
    pitch=5.2,             # % of H from one row's baseline to the next
    head_gap=4.8,          # % of H from the heading's baseline to the first row's cap height
    max_w=76.0,            # % of W: the statement card's measure
    rise=0.6,              # % of H, the heading's rise on `settle` (a card's line takes its place)
    row_rise=0.35,         # % of H, each row's rise on `whisper` (the label's own preset)
    row_delay=0.25,        # s after the heading before the first row (as a chapter card's dates)
    stagger=4 / 24,        # s between rows (a lower third's stagger)
    exit=0.75,             # s, everything is let go together (the label's departure)
    min_s=4.0,             # s on screen at least (5 s recommended), so every row can be read
    note_gap=1.4,          # pitches from the last row's baseline to the no-AI line's
)
KEY_HEADING = "What the marks mean"
# The classes in key order: amber, the two bones (the dot and the card's ring) side by side, then the two cold blues
# side by side, so each pair that shares a hue is compared by shape.
KEY_CLASSES = tuple(GLYPH_SHAPE)
KEY_WORD = dict(CLASS_WORD, CARD="Our own titles and cards")   # a card's own words say what it is; the key says whose
# CoS 2026-10-11: a key shows only the classes the film uses; a film with no AI-GENERATED picture says so in a line
# derived from the plan, because a key that showed the class could imply the film has it.
KEY_NO_AI = "No picture in this film is AI-generated."


def key_classes(marks) -> tuple[str, ...]:
    """The classes a film's shots use (``marks``: plan marks with ``cls`` or
    shots with ``mark``), in KEY_CLASSES order: what its key shows. CARD is
    among them whenever the film has a card (it always does: the key is one)."""
    used = {m.get("cls", m.get("mark")) for m in marks}
    return tuple(c for c in KEY_CLASSES if c in used)


def mark_key_layout(L: Layout, fonts: Fonts, classes) -> dict:
    """Where the key draws its heading, its rows and, when ``classes`` holds
    no AI-GENERATED, the KEY_NO_AI line beneath them (E15: every glyph
    present, each line inside KEY.max_w, or TextOverflow; nothing is cut).
    ``classes`` are the film's picture classes (``key_classes``), drawn in
    KEY_CLASSES order. The rows are a column centred on the frame, each glyph
    centred on its word's x-height; the block is centred vertically. Returns
    ``{"heading", "rows": [{"cls", "text", "glyph": (x, y, d), "x",
    "baseline", "w"}], "note": {"text", "x", "baseline", "w"} or None, "top",
    "bottom"}``."""
    f_h = _font(fonts.display, L.px(KEY["heading"]))
    px = L.px(KEY["word"])
    f_w, f_n = _font(fonts.structure, px), _font(fonts.data, round(px * 0.94))
    max_w = L.w(KEY["max_w"])
    hw = check_text(KEY_HEADING, f_h, max_w=max_w, what="the mark key's heading")
    d = max(LABEL["glyph_min_px"], L.px(KEY["glyph"]))
    gap = KEY["gap"] * px
    if classes is None:
        raise TextOverflow("the mark key has no classes: they come from the plan (key_classes), never a default")
    want = set(classes)
    words = [(c, KEY_WORD[c]) for c in KEY_CLASSES if c in want]
    ww = [check_text(w, f_w, f_n, max_w=max_w - d - gap, what=f"the mark key's word for {c}") for c, w in words]
    note = None if "AI-GENERATED" in want else KEY_NO_AI
    nw = check_text(note, f_w, f_n, max_w=max_w, what="the mark key's line") if note else 0.0
    col_w = d + gap + max(ww, default=0.0)
    pitch = L.h(KEY["pitch"])
    head_gap = L.h(KEY["head_gap"])
    first = 0.73 * px                              # the first row's cap height under the heading's gap
    n_lines = len(words)
    last_off = (n_lines - 1) * pitch if words else 0.0
    if note:
        last_off = last_off + KEY["note_gap"] * pitch if words else 0.0
    height = f_h.size * 0.78 + head_gap + first + last_off + 0.25 * px
    top = (L.H - height) / 2.0
    h_base = top + f_h.size * 0.78
    x0 = (L.W - col_w) / 2.0
    rows = []
    for k, (c, w) in enumerate(words):
        base = h_base + head_gap + first + k * pitch
        cy = base - 0.36 * px
        rows.append({"cls": c, "text": w, "glyph": (int(round(x0)), int(round(cy - d / 2.0)), d),
                     "x": x0 + d + gap, "baseline": base, "w": ww[k]})
    note_rec = None
    if note:
        base = (rows[-1]["baseline"] + KEY["note_gap"] * pitch) if rows else h_base + head_gap + first
        note_rec = {"text": note, "x": (L.W - nw) / 2.0, "baseline": base, "w": nw}
    return {"heading": {"text": KEY_HEADING, "x": (L.W - hw) / 2.0, "baseline": h_base, "w": hw, "font": f_h},
            "rows": rows, "note": note_rec, "font": f_w, "data_font": f_n, "top": top, "bottom": top + height}


def mark_key_drawn_text(layout: dict) -> list[str]:
    """What the key draws: the heading, each row's word, then the line when there is one."""
    return [layout["heading"]["text"]] + [r["text"] for r in layout["rows"]] + (
        [layout["note"]["text"]] if layout.get("note") else [])


def mark_key_frame(img: Image.Image, t: float, *, start: float, end: float, fonts: Fonts,
                   classes) -> Image.Image:
    """The mark key over black (CARD) for the film's ``classes``. In: the
    heading on `settle`, rising KEY.rise; from KEY.row_delay the rows one by
    one, KEY.stagger apart, each glyph with its word on `whisper`, rising
    KEY.row_rise; the no-AI line (when drawn) one step after the last row, at
    0.8 opacity as a statement card's later lines. Out: all of it let go
    together over KEY.exit (nothing moves). The glyphs are the class glyphs
    themselves (``_glyph``), drawn at KEY.glyph of the height."""
    base = _black(img.size)
    if t < start or t >= end:
        return base
    L = Layout(*base.size)
    lay = mark_key_layout(L, fonts, classes)
    exit_k = let_go(t, end, KEY["exit"])
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    hp = clamp01(SETTLE.progress(t - start))
    sub = Image.new("RGBA", base.size, (0, 0, 0, 0))
    h = lay["heading"]
    ImageDraw.Draw(sub).text((h["x"], h["baseline"]), h["text"], font=h["font"],
                             fill=_rgba(PALETTE["bone"], hp * exit_k), anchor="ls")
    layer.alpha_composite(_shift(sub, (1.0 - hp) * L.h(KEY["rise"])))
    items = list(lay["rows"]) + ([dict(lay["note"], cls=None)] if lay["note"] else [])
    for k, r in enumerate(items):
        t0 = start + KEY["row_delay"] + k * KEY["stagger"]
        if t < t0:
            continue
        p = clamp01(WHISPER.progress(t - t0))
        a = p * exit_k
        sub = Image.new("RGBA", base.size, (0, 0, 0, 0))
        if r["cls"] is not None:
            gx, gy, d = r["glyph"]
            sub.alpha_composite(_scale_alpha(_glyph(r["cls"], d), a), (gx, gy))
        else:
            a *= 0.8
        _draw_mixed(ImageDraw.Draw(sub), (r["x"], r["baseline"]), r["text"], lay["font"], lay["data_font"],
                    _rgba(PALETTE["mark_text"], a))
        layer.alpha_composite(_shift(sub, (1.0 - p) * L.h(KEY["row_rise"])))
    return Image.alpha_composite(base, layer)


def credits_fonts(L: Layout, fonts: Fonts):
    return (_font(fonts.data, L.px(CREDITS["heading"])), _font(fonts.structure, L.px(CREDITS["size"])),
            _font(fonts.data, round(L.px(CREDITS["size"]) * 0.94)))


def credits_wrap(L: Layout, text: str, fonts: Fonts, chars: int = 90) -> list[str]:
    """A credit's lines: broken at ``chars`` characters (the G2 credits), and
    any line still wider than the column (CREDITS.col_w) broken again by its
    measured width, so every word is drawn inside the column (E15)."""
    _, f_l, f_n = credits_fonts(L, fonts)
    col = L.w(CREDITS["col_w"])
    out, cur = [], ""
    for w in str(text).split():
        if cur and len(cur) + 1 + len(w) > chars:
            out.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        out.append(cur)
    final = []
    for ln in out:
        final += _wrap(ln, f_l, f_n, col) if _measure(ln, f_l, f_n) > col else [ln]
    return final


def credits_layout(L: Layout, blocks, fonts: Fonts) -> dict:
    """Where each credit line sits on the roll, from the roll's top (px), and
    when it has fully entered the frame (s after the credits start). Every
    line fits the column with its glyphs, or TextOverflow (E15)."""
    f_h, f_l, f_n = credits_fonts(L, fonts)
    lh = f_l.size * CREDITS["lh"]
    col = L.w(CREDITS["col_w"])
    speed = L.h(CREDITS["speed"])
    y, lines = 0.0, []
    for heading, rows in blocks:
        check_text(heading.upper(), f_h, what="a credits heading")
        if _tracked_width(heading.upper(), f_h, 0.12) > col + 0.5:
            raise TextOverflow(f"a credits heading is wider than the column: {heading!r}")
        y += lh * 1.3
        for ln in rows:
            w = check_text(ln, f_l, f_n, max_w=col, what="a credit line")
            lines.append({"text": ln, "y": y, "w": w, "entered_s": (y + f_l.size * 0.9 + f_l.size * 0.3) / speed})
            y += lh
        y += lh * 0.8
    return {"lines": lines, "height": y, "speed": speed,
            "last_entered_s": lines[-1]["entered_s"] if lines else 0.0}


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


# A34 (R12, founder: "show the original, then slowly zoom in to what matters... it should fill the screen"): the
# FILL camera preset for a picture narrower than 16:9 (4:3 footage, a square or portrait photograph). It opens on
# the whole original for ``open_s`` (pillarboxed, A7), then moves on the rostrum curve (section 6's Ken Burns ease)
# over ``move_s`` to the largest 16:9 window inside the picture about its focus, and holds there. A shot shorter
# than open_s + move_min_s opens for 40% of itself and moves over the rest.
FILL = dict(open_s=2.5, move_s=6.0, move_min_s=3.0, curve="rostrum", default_min_s=6.0)

# A41 (TOUR; founder, 2026-10-17: "take the user through the artifact as needed, but use the full resolution of the
# screen"): every still fills 16:9 on every frame (z = 1 is the largest 16:9 window inside the picture, and the camera
# never goes below it), and the shot is a path of stops the camera tours on the rostrum curve. These are its numbers
# (studio/engine/tour.py draws them):
#   hold_creep_after_s  a stop held longer than this keeps creeping, so no frame is frozen
#   creep_scale_per_s   the creep: the picture's scale grows 1.5% a second (the brief's 1 to 2%), or shrinks where the
#                       softness cap is reached, or ...
#   creep_drift_per_s   ... a slow drift of 1% of the frame a second where scale cannot change (at the fill and the cap)
#   pan_guide_per_s     a pan faster than a third of the frame per second is a warning (pacing is guidance, A39)
#   zoom_guide_per_s    a zoom changing scale faster than 15% a second is a warning
#   still_eps_per_s     slower than this (frame or log-scale per second) the camera is landed on a stop, for the
#                       continuity check across a cut (a creep is under it)
#   default_settle      the FILL macro's covering pass ends this share of the shot in, then settles on its focus
#   sample_hz           how often the guards sample the path (the people and fill checks)
#   still_max_upscale   the softness cap for a still on the 1080p master unless the film states fill_max_upscale
#                       (founder, 2026-10-17: "fill the frame, soft is acceptable up to 3x"); a clip keeps A34's 1.6
#   whole_creep_max     a still held whole under a fill_exception creeps inside its own shape (pillarboxed, never
#                       frozen) at creep_scale_per_s, to at most this zoom of the whole (founder, 2026-10-17)
TOUR = dict(hold_creep_after_s=1.5, creep_scale_per_s=0.015, creep_drift_per_s=0.01, pan_guide_per_s=1 / 3,
            zoom_guide_per_s=0.15, still_eps_per_s=0.03, default_settle=0.7, sample_hz=8.0, curve="rostrum",
            still_max_upscale=3.0, whole_creep_max=1.06)


def still_view(size, L: Layout, *, z: float = 1.0, cx: float = 0.5, cy: float = 0.5, clamp: str = "frame"):
    """Where a still lands for a camera at zoom z about the frame-space centre
    (cx, cy). z = 1 is the whole photograph fitted at its native aspect on the
    field (GRAMMAR 7.5, amendment A7). Returns ``(src, dst)``: ``src`` is the
    window in image pixels (x0, y0, x1, y1) and ``dst`` the frame rectangle it
    is drawn into; whatever of ``dst`` lies outside the photograph stays the
    letterbox field.

    ``clamp``:
      - ``"frame"``: the window stays inside the frame (the kit demo's move).
      - ``"image"``: the window stays inside the photograph on every axis where
        it fits, so a move can fill 16:9 without showing the field (a fill;
        the studio allows it only when the shot's ``fill_ok`` is true).
      - ``"native"``: the picture keeps the photograph's own shape and place on
        the field and the camera moves inside that shape (A7 without a fill).
    """
    iw, ih = size
    s = min(L.W / iw, L.H / ih)
    fw, fh = iw * s, ih * s
    ox, oy = (L.W - fw) / 2.0, (L.H - fh) / 2.0
    z = max(1.0, float(z))

    def to_img(x, y):
        return ((x - ox) / s, (y - oy) / s)

    if clamp == "native":
        ww, wh = fw / z, fh / z
        x0 = min(max(cx * L.W - ww / 2, ox), ox + fw - ww)
        y0 = min(max(cy * L.H - wh / 2, oy), oy + fh - wh)
        a, b = to_img(x0, y0), to_img(x0 + ww, y0 + wh)
        return (a[0], a[1], b[0], b[1]), (ox, oy, ox + fw, oy + fh)
    ww, wh = L.W / z, L.H / z
    if clamp == "image":
        def axis(c, w, lo, span):
            if w <= span:
                return min(max(c - w / 2, lo), lo + span - w)
            return lo + span / 2 - w / 2          # wider than the photograph: keep it centred
        x0 = axis(cx * L.W, ww, ox, fw)
        y0 = axis(cy * L.H, wh, oy, fh)
    else:
        x0 = min(max(cx * L.W - ww / 2, 0), L.W - ww)
        y0 = min(max(cy * L.H - wh / 2, 0), L.H - wh)
    a, b = to_img(x0, y0), to_img(x0 + ww, y0 + wh)
    return (a[0], a[1], b[0], b[1]), (0.0, 0.0, float(L.W), float(L.H))


def fit_still(still: Image.Image, L: Layout, *, z: float = 1.0, cx: float = 0.5, cy: float = 0.5,
              clamp: str = "frame") -> Image.Image:
    """Letterbox or pillarbox the photograph on the letterbox field, then take
    the window (zoom z about centre cx, cy in 0..1) with bicubic sampling.
    ``clamp`` is as ``still_view`` says."""
    src, dst = still_view(still.size, L, z=z, cx=cx, cy=cy, clamp=clamp)
    rgb = still if still.mode == "RGB" else still.convert("RGB")
    if dst == (0.0, 0.0, float(L.W), float(L.H)):
        return rgb.transform((L.W, L.H), Image.Transform.EXTENT, src,
                             resample=Image.Resampling.BICUBIC, fillcolor=PALETTE["letterbox"])
    x0, y0 = int(round(dst[0])), int(round(dst[1]))
    dw, dh = int(round(dst[2])) - x0, int(round(dst[3])) - y0
    out = Image.new("RGB", (L.W, L.H), PALETTE["letterbox"])
    out.paste(rgb.transform((dw, dh), Image.Transform.EXTENT, src, resample=Image.Resampling.BICUBIC,
                            fillcolor=PALETTE["letterbox"]), (x0, y0))
    return out


def _path_point(points, e: float) -> dict:
    """Position ``e`` (0..1) along a polyline of framings, each leg weighted by
    how far the camera travels on it (log zoom plus centre distance); zoom is
    geometric along a leg so its speed reads even."""
    legs = []
    for a, b in zip(points, points[1:]):
        d = abs(math.log(b["z"] / a["z"])) + abs(b.get("x", 0.5) - a.get("x", 0.5)) + abs(b.get("y", 0.5) - a.get("y", 0.5))
        legs.append(max(d, 1e-9))
    pos = clamp01(e) * sum(legs)
    for (a, b), d in zip(zip(points, points[1:]), legs):
        if pos <= d:
            u = pos / d
            return {"z": a["z"] * (b["z"] / a["z"]) ** u,
                    "x": a.get("x", 0.5) + (b.get("x", 0.5) - a.get("x", 0.5)) * u,
                    "y": a.get("y", 0.5) + (b.get("y", 0.5) - a.get("y", 0.5)) * u}
        pos -= d
    return {"z": points[-1]["z"], "x": points[-1].get("x", 0.5), "y": points[-1].get("y", 0.5)}


def rostrum_framing(t: float, dur: float, frm: dict, to: dict, via=()) -> dict:
    """The framing {"z", "x", "y"} at time t of a rostrum move. With no
    ``via`` it is the kit's straight move (z, x and y linear in the rostrum
    curve); with ``via`` it runs the polyline frm, *via, to."""
    e = rostrum(t, dur)
    if not via:
        return {"z": frm["z"] + (to["z"] - frm["z"]) * e,
                "x": frm.get("x", 0.5) + (to.get("x", 0.5) - frm.get("x", 0.5)) * e,
                "y": frm.get("y", 0.5) + (to.get("y", 0.5) - frm.get("y", 0.5)) * e}
    return _path_point([frm, *via, to], e)


def rostrum_move(still: Image.Image, L: Layout, t: float, dur: float, frm: dict, to: dict, *,
                 via=(), clamp: str = "frame") -> Image.Image:
    """Ken Burns between two framings {"z", "x", "y"} on the rostrum curve,
    optionally through ``via`` framings, clamped as ``still_view`` says."""
    f = rostrum_framing(t, dur, frm, to, via)
    return fit_still(still, L, z=f["z"], cx=f["x"], cy=f["y"], clamp=clamp)


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
    shots = [dict(start=0.0, cls="ARCHIVE", label=mark_label("ARCHIVE", "1947")),
             dict(start=3.0, cls="RECONSTRUCTED", label=mark_label("RECONSTRUCTED", "1947", "stabilised")),
             dict(start=5.0, cls="CARD", label="")]
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
        frame = mark_frame(frame, t, shots, fonts)
        frame.convert("RGB").save(out_dir / f"f{f:04d}.png")
    print(f"demo: {len(range(0, n, every))} frames -> {out_dir}")


def _youtube_watermark(path: Path) -> None:
    """150x150 transparent PNG for YouTube's branding watermark: the logomark in
    bone with its ember, no halo (YouTube draws it at its own low opacity)."""
    img = draw_logomark(150, halo=0.0)
    img.save(path)
    print(f"youtube watermark -> {path}")


KIT_DIR = Path(__file__).resolve().parents[2] / "design" / "brand-kit"


def main(here: Path | None = None, argv=None) -> None:
    """The kit CLI. ``--table`` prints the presets; otherwise it writes the
    YouTube watermark PNG and the demo strip into the brand-kit folder (build
    outputs, gitignored)."""
    import sys
    here = here or KIT_DIR
    argv = sys.argv[1:] if argv is None else argv
    if "--table" in argv:
        print(preset_table())
        for s in PRESETS:
            print(s.name, s.css_linear())
        return
    _youtube_watermark(here / "watermark-youtube-150.png")
    _demo(here / "demo", here / "_media")


if __name__ == "__main__":
    main()
