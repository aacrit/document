"""void document: the studio's map engine. A map spec (JSON) becomes one
1920x1080 DRAWN frame in the house style, deterministically.

    python -m studio.engine.maps SPEC.json [SPEC.json ...] --geodata DIR --out DIR [--sheet PNG]

Grammar: films/GRAMMAR.md 4.3 (a drawn map is DRAWN and names its data
source), 5.3 and 7.4 (drawn shots are in clean colour, never an imitation of
period imagery), A2 (DRAWN maps from cited data are not generated imagery).
design/brand-kit/BRAND-KIT.md 3 and 7 (the reserved zones; bone, black and cold
blue only on a frame; Fraunces for names, Inter for captions, the data face for
every numeral).

Colour: every colour is a custom property of design/tokens.css, read from that
file and resolved here (hex, var() and oklch(from var() ...) relative colour).
A spec never carries a colour; it names a style, and a style names a token.

Truth: a spec places only what its sources state. Base geography is Natural
Earth (public domain); every other fact is a label the spec writes from a cited
extract. The frame carries a source line naming every source, and the spec's
`sources` list carries each source's licence for the ledger. The engine
refuses a spec without Natural Earth and at least one cited source.

Determinism: no clock, no randomness, no environment. The picture is drawn at
2x and reduced with a Lanczos filter; the same spec, data and fonts give the
same bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw

from . import motion as M

ROOT = Path(__file__).resolve().parents[2]
TOKENS = ROOT / "design" / "tokens.css"
W, H = 1920, 1080
SS = 2  # supersampling factor


class MapRefused(Exception):
    """A spec that would put an unsourced, unsafe or off-grammar frame on film."""


# --------------------------------------------------------------------------
# Tokens: design/tokens.css is the only colour source.
# --------------------------------------------------------------------------

_DECL = re.compile(r"(--[\w-]+)\s*:\s*([^;]+);")
_REL = re.compile(r"oklch\(\s*from\s+var\((--[\w-]+)\)\s+(.*?)\s*(?:/\s*([\d.]+)\s*)?\)$")


def read_tokens(path: Path | str = TOKENS) -> dict[str, str]:
    """The declarations of the first :root block (the dark theatre, the default)."""
    text = re.sub(r"/\*.*?\*/", "", Path(path).read_text(encoding="utf-8"), flags=re.S)
    start = text.index(":root {")
    end = text.index("\n}", start)
    return {k: v.strip() for k, v in _DECL.findall(text[start:end])}


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c: float) -> float:
    c = min(1.0, max(0.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def rgb_to_oklch(rgb) -> tuple[float, float, float]:
    r, g, b = (_srgb_to_linear(v / 255.0) for v in rgb)
    l_ = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m_ = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s_ = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    bb = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    return L, math.hypot(a, bb), math.degrees(math.atan2(bb, a)) % 360.0


def oklch_to_rgb(L: float, C: float, h: float) -> tuple[int, int, int]:
    a, b = C * math.cos(math.radians(h)), C * math.sin(math.radians(h))
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    r = 4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_
    g = -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_
    bl = -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_
    return tuple(int(round(255 * _linear_to_srgb(v))) for v in (r, g, bl))


def _component(expr: str, base: float) -> float:
    expr = expr.strip()
    if expr in ("l", "c", "h"):
        return base
    m = re.fullmatch(r"calc\(\s*[lch]\s*([+-])\s*([\d.]+)\s*\)", expr)
    if m:
        return base + float(m.group(2)) * (1 if m.group(1) == "+" else -1)
    return float(expr)


def resolve(name: str, tokens: dict[str, str]) -> tuple[int, int, int, float]:
    """A token's sRGB colour and alpha: a hex literal, var(), or oklch(from var() L C H / A)."""
    if name not in tokens:
        raise MapRefused(f"token {name} is not in tokens.css")
    v = tokens[name]
    if re.fullmatch(r"#[0-9a-fA-F]{6}", v):
        return int(v[1:3], 16), int(v[3:5], 16), int(v[5:7], 16), 1.0
    m = re.fullmatch(r"var\((--[\w-]+)\)", v)
    if m:
        return resolve(m.group(1), tokens)
    m = _REL.fullmatch(v)
    if m:
        r, g, b, alpha = resolve(m.group(1), tokens)
        L, C, h = rgb_to_oklch((r, g, b))
        parts = re.findall(r"calc\([^)]*\)|\S+", m.group(2))
        if len(parts) != 3:
            raise MapRefused(f"token {name}: cannot read {v}")
        L2, C2, h2 = _component(parts[0], L), _component(parts[1], C), _component(parts[2], h)
        out = oklch_to_rgb(L2, C2, h2)
        return out[0], out[1], out[2], float(m.group(3)) if m.group(3) else alpha
    raise MapRefused(f"token {name}: unsupported value {v}")


# Every role a map uses, and the one token it reads. Nothing else colours a map.
ROLES = {
    "sea": "--color-letterbox",          # water and the ground beyond the land
    "land": "--color-surface",           # land outside the subject
    "focus": "--color-surface-raised",   # the subject's land
    "rule": "--color-border",            # quiet rules (panel divider)
    "faint": "--color-cream-faint",      # coasts and other borders: rules, never text
    "text": "--color-cream",             # labels
    "muted": "--color-cream-muted",      # secondary labels, notes, the source line
    "line": "--mark-text",               # the line the film is about
    "cold": "--mark-generated",          # DRAWN's hue: data the spec highlights
    "cold_text": "--color-generated-text",  # rivers, and cold-blue text
    "halo": "--scrim-strong",            # the dark contact edge under a label
}


def palette(tokens_path: Path | str = TOKENS) -> dict[str, tuple[int, int, int, int]]:
    tokens = read_tokens(tokens_path)
    out = {}
    for role, tok in ROLES.items():
        r, g, b, a = resolve(tok, tokens)
        out[role] = (r, g, b, int(round(255 * a)))
    return out


def _with_alpha(c, a: float):
    return (c[0], c[1], c[2], int(round(c[3] * a)))


# --------------------------------------------------------------------------
# Styles: the closed vocabulary a spec may name.
# --------------------------------------------------------------------------

# polygons: (fill role, fill alpha, outline role or None, outline px, hatch angle in degrees or None)
POLY = {
    "land": ("land", 1.0, None, 0, None),
    "focus": ("focus", 1.0, None, 0, None),
    "water": ("sea", 1.0, None, 0, None),
    "shade": ("cold", 0.62, "cold_text", 2, None),
    # two sides of one division at equal weight: the same fill, told apart by the hatch's direction
    "side_a": ("cold", 0.42, "cold_text", 2, 45),
    "side_b": ("cold", 0.42, "cold_text", 2, -45),
}
HATCH = dict(role="cold_text", alpha=0.5, px=1.6, gap=14)
# lines: (role, alpha, px, dash px or None)
LINE = {
    "coast": ("faint", 0.6, 1.4, None),
    "border": ("faint", 1.0, 2.0, None),
    "border_today": ("muted", 0.9, 2.4, (10, 7)),
    "working": ("muted", 1.0, 2.2, (3, 5)),
    "river": ("cold_text", 0.85, 2.2, None),
    "road": ("muted", 1.0, 2.6, (6, 6)),
    "line": ("line", 1.0, 5.0, None),
    "line_dashed": ("line", 1.0, 4.0, (14, 9)),
}
# points: (marker, radius px, label font, label role)
POINT = {
    "town": ("dot", 4.5, "structure", "muted"),
    "key": ("dot", 6.0, "display", "text"),
    "listed": ("disc", 8.0, "structure", "text"),
    "unlisted": ("ring", 7.0, "structure", "muted"),
    "hidden": (None, 0.0, "structure", "text"),
}
# free labels: (font, size % of H, role)
LABEL = {
    "region": ("display_italic", 3.0, "muted"),
    "sea": ("display_italic", 2.4, "cold_text"),
    "river": ("display_italic", 1.9, "cold_text"),
    "line": ("structure", 1.75, "text"),
    "note": ("structure", 1.6, "muted"),
    "figure": ("data", 2.4, "text"),
}
SIZES = dict(point_label=1.85, point_label_key=2.6, point_sub=1.75, title=2.9, legend=1.7,
             note=1.55, source=1.5)
# Zones (fractions of the frame) no map text may enter: the mark plate and the watermark.
FORBIDDEN = {"mark": (0.0, 0.0, 0.30, 0.20), "watermark": (0.88, 0.0, 1.0, 0.12)}
# Zones the film's own text may cover for a few seconds: labels there are warned.
COVERED = {"lower_third": (0.04, 0.75, 0.60, 0.93), "overlay": (0.60, 0.84, 0.96, 0.93),
           "subtitle": (0.08, 0.80, 0.92, 0.93)}
PANEL = dict(x=0.715, w=0.245, top=0.15, bottom=0.80, wash_from=0.64, wash_full=0.70, wash_alpha=0.82)
SOURCE_LINE = dict(x=0.04, baseline=0.972)
DEFAULT_FRAME = (0.04, 0.12, 0.68, 0.92)  # where the extent is fitted when a panel is shown
FULL_FRAME = (0.04, 0.08, 0.96, 0.92)     # when there is no panel


# --------------------------------------------------------------------------
# Spec checks
# --------------------------------------------------------------------------

GEONAMES = "GeoNames (CC BY 4.0)"
# Lines no open dataset places, which no spec may draw solid: (pair of ADM0_A3 codes, why).
UNPLACED = [({"BGD", "IND"}, "the Bengal award's line: no open dataset places it, so it is drawn only as "
                             "today's border, dashed")]
SOLID = ("line", "line_dashed")
SOURCE_SHORT_MAX = 40
_COLOUR_VALUE = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgb|rgba|hsl|hsla|oklch)\(")
_COLOUR_KEYS = {"color", "colour", "fill", "stroke", "rgb", "hex"}


def _strings(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from _strings(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _strings(v, f"{path}[{i}]")
    elif isinstance(o, str):
        yield path, o


def _keys(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from _keys(v)
    elif isinstance(o, list):
        for v in o:
            yield from _keys(v)


def check_spec(spec: dict) -> None:
    for k in ("id", "title", "source_short", "sources"):
        if k not in spec:
            raise MapRefused(f"spec lacks {k}")
    if len(spec["source_short"]) > SOURCE_SHORT_MAX:
        raise MapRefused(f"{spec['id']}: source_short is {len(spec['source_short'])} characters; "
                         f"the plate holds {SOURCE_SHORT_MAX}")
    bad = sorted(set(k.lower() for k in _keys(spec)) & _COLOUR_KEYS)
    if bad:
        raise MapRefused(f"{spec['id']}: a spec never carries a colour ({bad[0]}); name a style")
    for path, s in _strings(spec):
        if _COLOUR_VALUE.search(s):
            raise MapRefused(f"{spec['id']}{path}: colour literal in a spec")
        if "—" in s:
            raise MapRefused(f"{spec['id']}{path}: em dash in on-screen copy")
    src = spec["sources"]
    if not src or any(not s.get("id") or not s.get("licence") for s in src):
        raise MapRefused(f"{spec['id']}: every source needs an id and a licence")
    if src[0]["id"] != "Natural Earth" or len(src) < 2:
        raise MapRefused(f"{spec['id']}: sources are Natural Earth first, then at least one cited source")
    views = spec.get("views") or [spec]
    if uses_geonames(spec) and GEONAMES not in [x["id"] for x in src]:
        raise MapRefused(f"{spec['id']}: positions from GeoNames need the source {GEONAMES!r} on the frame")
    if any(ly.get("award") for v in views for ly in v.get("layers", [])) and not has_approximate_note(spec):
        raise MapRefused(f"{spec['id']}: an award line drawn on today's border needs the note "
                         f"{APPROX_NOTE!r} on the frame")
    for v in views:
        if "extent" not in v:
            raise MapRefused(f"{spec['id']}: every view needs an extent")
        if v is not spec and "frame" not in v:
            raise MapRefused(f"{spec['id']}: every view of several needs a frame")
        for pth in v.get("paths", []):
            if pth.get("style") not in LINE or len(pth.get("points", [])) < 2:
                raise MapRefused(f"{spec['id']}: a path needs a line style and two points")
    for ly in [ly for v in views for ly in v.get("layers", [])]:
        where = ly.get("where") or {}
        pair = {where.get("ADM0_A3_L"), where.get("ADM0_A3_R")}
        for codes, why in UNPLACED:
            if ly.get("style") in SOLID and pair == codes:
                raise MapRefused(f"{spec['id']}: a solid line on {sorted(codes)} is refused: {why}")
        st = ly.get("style")
        if st not in POLY and st not in LINE:
            raise MapRefused(f"{spec['id']}: unknown layer style {st}")
    for p in [p for v in views for p in v.get("places", [])]:
        if p.get("style", "town") not in POINT:
            raise MapRefused(f"{spec['id']}: unknown place style {p.get('style')}")
    for lb in [lb for v in views for lb in v.get("labels", [])]:
        if lb.get("style") not in LABEL:
            raise MapRefused(f"{spec['id']}: unknown label style {lb.get('style')}")
    for e in spec.get("legend", []):
        if e.get("style") not in POLY and e.get("style") not in LINE and e.get("style") not in POINT:
            raise MapRefused(f"{spec['id']}: unknown legend style {e.get('style')}")


def data_source(spec: dict) -> str:
    return "; ".join(s["id"] for s in spec["sources"])


def source_line(spec: dict) -> str:
    return "Data: " + data_source(spec)


APPROX_NOTE = "Line approximate, from the award"


def uses_geonames(spec: dict) -> bool:
    return any(k == "geonameid" for k in _keys(spec))


def has_approximate_note(spec: dict) -> bool:
    return any(n.startswith(APPROX_NOTE) for n in spec.get("notes", []))


def method(spec: dict) -> dict:
    """What a map claims about how it was drawn, read from its spec: the ledger's
    `method` is this, never hand-written."""
    views = spec.get("views") or [spec]
    layers = [ly for v in views for ly in v.get("layers", [])]
    claims = {
        "award_line": any(ly.get("award") for ly in layers),
        "approximate_note": has_approximate_note(spec),
        "geonames_positions": uses_geonames(spec),
        "boundaries_not_drawn_note": any("not drawn" in n for n in spec.get("notes", [])),
    }
    text = ["base geography from Natural Earth"]
    if claims["award_line"]:
        text.append("the award line drawn on today's border (Natural Earth) only where the cited schedule runs")
    if claims["approximate_note"]:
        text.append("the frame notes the line is approximate")
    if claims["geonames_positions"]:
        text.append("named places positioned from GeoNames")
    if claims["boundaries_not_drawn_note"]:
        text.append("the frame states what is not drawn and why")
    claims["text"] = "; ".join(text)
    return claims


def ledger_fields(spec: dict) -> dict:
    """What the drawn ledger says about a map, from the spec alone, so the mark
    plate, the ledger and the frame's source line always agree."""
    ds = data_source(spec)
    geo = GEONAMES in [s["id"] for s in spec["sources"]]
    return {"title": spec["title"], "data_source": ds, "source_short": spec["source_short"],
            "credit": "void document studio, drawn from " + ds,
            # a canonical id the render engine's licence allowlist recognises; the why goes in licence_note
            "licence": "CC-BY-4.0" if geo else "CC0",
            "licence_note": ("contains GeoNames data (CC BY 4.0); Natural Earth public domain" if geo
                             else "Natural Earth public domain"),
            "data_sources": spec["sources"], "source_line": source_line(spec), "method": method(spec)}


# --------------------------------------------------------------------------
# Geodata
# --------------------------------------------------------------------------

@lru_cache(maxsize=32)
def _load(path: str) -> tuple:
    gj = json.loads(Path(path).read_text(encoding="utf-8"))
    feats = []
    for f in gj["features"]:
        g = f.get("geometry")
        if not g or not g.get("coordinates"):
            continue
        feats.append((f.get("properties") or {}, g, _bbox(g["coordinates"])))
    return tuple(feats)


@lru_cache(maxsize=32)
def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _bbox(c) -> tuple[float, float, float, float]:
    xs, ys = [], []

    def walk(a):
        if a and isinstance(a[0], (int, float)):
            xs.append(a[0])
            ys.append(a[1])
        else:
            for b in a:
                walk(b)
    walk(c)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else (0.0, 0.0, 0.0, 0.0)


def _overlaps(a, b) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def _matches(props: dict, where: dict | None) -> bool:
    if not where:
        return True
    for k, vals in where.items():
        v = props.get(k)
        if isinstance(vals, list):
            if v not in vals:
                return False
        elif v != vals:
            return False
    return True


def _lines_of(g) -> list:
    t = g["type"]
    if t == "LineString":
        return [g["coordinates"]]
    if t == "MultiLineString":
        return g["coordinates"]
    if t == "Polygon":
        return list(g["coordinates"])
    if t == "MultiPolygon":
        return [ring for poly in g["coordinates"] for ring in poly]
    return []


def _polys_of(g) -> list:
    if g["type"] == "Polygon":
        return [g["coordinates"]]
    if g["type"] == "MultiPolygon":
        return g["coordinates"]
    return []


def _merge_touching(lines: list) -> list:
    """Chain parts whose ends meet (in any order), so a dash pattern runs on across a
    multi-part line instead of restarting at every short part. Deterministic: parts
    are taken in their file order."""
    rest = [list(ln) for ln in lines if ln]
    out = []
    while rest:
        cur = rest.pop(0)
        grew = True
        while grew:
            grew = False
            for i, ln in enumerate(rest):
                if _near(cur[-1], ln[0], 1e-6):
                    cur = cur + ln[1:]
                elif _near(ln[-1], cur[0], 1e-6):
                    cur = ln + cur[1:]
                else:
                    continue
                rest.pop(i)
                grew = True
                break
        out.append(cur)
    return out


def _near(a, b, tol: float) -> bool:
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def _touches(lines: list, ends: list, tol: float) -> bool:
    """A feature whose line endpoints include every point named (a road between two towns)."""
    tips = [p for ln in lines for p in (ln[0], ln[-1])]
    return all(any(_near(t, e, tol) for t in tips) for e in ends)


def _clip_segment(p, q, box):
    """Liang-Barsky: the part of segment pq inside box (lon0, lat0, lon1, lat1), or None."""
    x0, y0, x1, y1 = box
    dx, dy = q[0] - p[0], q[1] - p[1]
    u0, u1 = 0.0, 1.0
    for pk, qk in ((-dx, p[0] - x0), (dx, x1 - p[0]), (-dy, p[1] - y0), (dy, y1 - p[1])):
        if pk == 0:
            if qk < 0:
                return None
            continue
        r = qk / pk
        if pk < 0:
            u0 = max(u0, r)
        else:
            u1 = min(u1, r)
        if u0 > u1:
            return None
    return (p[0] + u0 * dx, p[1] + u0 * dy), (p[0] + u1 * dx, p[1] + u1 * dy)


SPAN_TOL = 0.25  # degrees: a span's end must lie this close to a vertex of the line


def span_line(line, span: dict):
    """The stretch of `line` between the vertices nearest span["from"] and span["to"]
    (each [lon, lat]), or None when either point is not on this line. Used where a
    source describes a line by its ends (a schedule's junctions) on a longer border."""
    def nearest(pt):
        best = min(range(len(line)), key=lambda i: (line[i][0] - pt[0]) ** 2 + (line[i][1] - pt[1]) ** 2)
        d = math.hypot(line[best][0] - pt[0], line[best][1] - pt[1])
        return best if d <= SPAN_TOL else None
    i, j = nearest(span["from"]), nearest(span["to"])
    if i is None or j is None or i == j:
        return None
    a, b = sorted((i, j))
    return line[a:b + 1]


def clip_line(line, box) -> list[list]:
    out, cur = [], []
    for p, q in zip(line, line[1:]):
        seg = _clip_segment(p, q, box)
        if seg is None:
            if len(cur) > 1:
                out.append(cur)
            cur = []
            continue
        a, b = seg
        if cur and _near(cur[-1], a, 1e-9):
            cur.append(b)
        else:
            if len(cur) > 1:
                out.append(cur)
            cur = [a, b]
    if len(cur) > 1:
        out.append(cur)
    return out


# --------------------------------------------------------------------------
# Projection: a local plate carree, true to scale at the extent's centre latitude.
# --------------------------------------------------------------------------

class Projection:
    def __init__(self, extent, frame, size):
        lon0, lat0, lon1, lat1 = extent
        if not (lon1 > lon0 and lat1 > lat0):
            raise MapRefused("extent must be [lon0, lat0, lon1, lat1] with lon1 > lon0, lat1 > lat0")
        Wp, Hp = size
        fx0, fy0, fx1, fy1 = frame
        self.k = math.cos(math.radians((lat0 + lat1) / 2))
        bw, bh = (fx1 - fx0) * Wp, (fy1 - fy0) * Hp
        self.s = min(bw / ((lon1 - lon0) * self.k), bh / (lat1 - lat0))
        self.cx, self.cy = (fx0 + fx1) / 2 * Wp, (fy0 + fy1) / 2 * Hp
        self.clon, self.clat = (lon0 + lon1) / 2, (lat0 + lat1) / 2
        self.size = size

    def __call__(self, lon: float, lat: float) -> tuple[float, float]:
        return (self.cx + (lon - self.clon) * self.k * self.s, self.cy - (lat - self.clat) * self.s)

    def view(self) -> tuple[float, float, float, float]:
        """The lon/lat box the whole frame shows."""
        Wp, Hp = self.size
        lon_a = self.clon + (0 - self.cx) / (self.k * self.s)
        lon_b = self.clon + (Wp - self.cx) / (self.k * self.s)
        lat_a = self.clat - (Hp - self.cy) / self.s
        lat_b = self.clat - (0 - self.cy) / self.s
        return lon_a, lat_a, lon_b, lat_b


# --------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------

def _font_path(fonts: M.Fonts, which: str) -> str:
    return {"display": fonts.display, "display_italic": fonts.display_italic,
            "structure": fonts.structure, "structure_medium": fonts.structure_medium,
            "data": fonts.data}[which]


class Canvas:
    """A 2x RGBA canvas; every text box is recorded at 1x for the zone checks."""

    def __init__(self, pal, fonts: M.Fonts):
        self.pal, self.fonts = pal, fonts
        self.img = Image.new("RGBA", (W * SS, H * SS), pal["sea"][:3] + (255,))
        self.d = ImageDraw.Draw(self.img, "RGBA")
        self.boxes: list[dict] = []
        self.keepout = None  # 2x rect kept clear of map strokes (the source line's zone)

    def font(self, which: str, pct_h: float):
        return M._font(_font_path(self.fonts, which), max(1, round(pct_h / 100.0 * H * SS)))

    def data_font(self, pct_h: float):
        return M._font(self.fonts.data, max(1, round(0.94 * pct_h / 100.0 * H * SS)))

    def measure(self, text: str, which: str, pct_h: float) -> float:
        f = self.font(which, pct_h)
        return M._measure(text, f, None if which == "data" else self.data_font(pct_h))

    def text(self, xy, text: str, which: str, pct_h: float, role: str, *, anchor="ls", halo=True,
             kind="label", alpha=1.0, group=None) -> tuple:
        """Draw at a baseline-left (ls) or other anchor; numerals ride the data face."""
        f = self.font(which, pct_h)
        df = None if which == "data" else self.data_font(pct_h)
        w = M._measure(text, f, df)
        asc, desc = f.getmetrics()
        x, y = xy
        if anchor[0] == "m":
            x -= w / 2
        elif anchor[0] == "r":
            x -= w
        if anchor[1] == "m":
            y += (asc - desc) / 2 * 0.86
        elif anchor[1] == "t":
            y += asc
        stroke = max(2, round(f.size * 0.07)) if halo else 0
        runs = [(text, False)] if df is None else M._runs(text)

        def glyphs(md, width):
            cx = x
            for frag, num in runs:
                ff = df if num else f
                md.text((cx, y), frag, font=ff, fill=255, anchor="ls", stroke_width=width, stroke_fill=255)
                cx += ff.getlength(frag)
        if stroke:
            self.shape("halo", 1.0, lambda md: glyphs(md, stroke))
        self.shape(role, alpha, lambda md: glyphs(md, 0))
        box = ((x - stroke) / SS, (y - asc - stroke) / SS, (x + w + stroke) / SS, (y + desc + stroke) / SS)
        self.boxes.append({"kind": kind, "text": text, "box": box,
                           "group": group if group is not None else len(self.boxes)})
        return box

    def mask(self) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        m = Image.new("L", self.img.size, 0)
        return m, ImageDraw.Draw(m)

    def composite(self, mask: Image.Image, role: str, alpha: float, *, stroke: bool = False) -> None:
        """Lay a role's colour through a coverage mask, once. Strokes are drawn opaque
        into the mask first, so a dense coastline's overlapping joints never stack
        their alpha into a brighter line than its style. A map stroke never enters the
        keep-out zone (the source line's)."""
        if stroke and self.keepout is not None:
            mask = mask.copy()
            ImageDraw.Draw(mask).rectangle(self.keepout, fill=0)
        bbox = mask.getbbox()
        if bbox is None:
            return
        c = self.pal[role]
        k = c[3] / 255.0 * alpha
        m = mask.crop(bbox)
        layer = Image.new("RGBA", m.size, (c[0], c[1], c[2], 0))
        layer.putalpha(m.point(lambda v: int(round(v * k))))
        self.img.alpha_composite(layer, dest=bbox[:2])
        self.d = ImageDraw.Draw(self.img, "RGBA")

    def shape(self, role: str, alpha: float, draw) -> None:
        """Any filled or stroked shape in a role's colour at its token alpha:
        drawn opaque into a mask, then laid on (ImageDraw replaces alpha, never blends)."""
        m, md = self.mask()
        draw(md)
        self.composite(m, role, alpha)


def _line_on(d: ImageDraw.ImageDraw, pts, fill, px: float, dash=None) -> None:
    wpx = max(1, round(px * SS))
    if dash is None:
        d.line(pts, fill=fill, width=wpx, joint="curve")
        return
    on, off = dash[0] * SS, dash[1] * SS
    drawing, left = True, on
    seg = [pts[0]]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        L = math.hypot(x1 - x0, y1 - y0)
        t = 0.0
        while L - t > 1e-9:
            step = min(left, L - t)
            t += step
            left -= step
            q = (x0 + (x1 - x0) * t / L, y0 + (y1 - y0) * t / L)
            if drawing:
                seg.append(q)
            if left <= 1e-9:
                if drawing and len(seg) > 1:
                    d.line(seg, fill=fill, width=wpx, joint="curve")
                drawing = not drawing
                left = on if drawing else off
                seg = [q]
    if drawing and len(seg) > 1:
        d.line(seg, fill=fill, width=wpx, joint="curve")


def _draw_layers(cv: Canvas, spec: dict, proj: Projection, geodata: Path, used: dict) -> None:
    view = proj.view()
    for ly in spec.get("layers", []):
        path = geodata / ly["file"]
        if not path.exists():
            raise MapRefused(f"{spec['id']}: geodata {ly['file']} not found under {geodata}")
        used[ly["file"]] = file_sha256(str(path))
        style = ly["style"]
        clip = ly.get("clip")
        n = 0
        omask = lmask = fmask = None
        for props, g, bb in _load(str(path)):
            if not _overlaps(bb, view) or not _matches(props, ly.get("where")):
                continue
            if clip and not _overlaps(bb, clip):
                continue
            if ly.get("geometry") and g["type"] != ly["geometry"]:
                continue
            if ly.get("endpoints") and not _touches(_lines_of(g), ly["endpoints"], ly.get("tol", 0.03)):
                continue
            n += 1
            if style in POLY:
                role, a, orole, opx, _ = POLY[style]
                if orole and omask is None:
                    omask, omd = cv.mask()
                if fmask is None:
                    fmask, fmd = cv.mask()
                for poly in _polys_of(g):
                    rings = [[proj(*p) for p in ring] for ring in poly]
                    rings = [[(x * SS, y * SS) for x, y in r] for r in rings]
                    if len(rings[0]) > 2:
                        fmd.polygon(rings[0], fill=255)
                    for hole in rings[1:]:
                        if len(hole) > 2:
                            fmd.polygon(hole, fill=0)
                    if orole:
                        for r in rings:
                            _line_on(omd, r, 255, opx)
            else:
                role, a, px, dash = LINE[style]
                if lmask is None:
                    lmask, lmd = cv.mask()
                for line in _merge_touching(_lines_of(g)):
                    if ly.get("span"):
                        line = span_line(line, ly["span"])
                        if line is None:
                            continue
                    parts = clip_line(line, clip) if clip else [line]
                    for part in parts:
                        pts = [proj(*p) for p in part]
                        _line_on(lmd, [(x * SS, y * SS) for x, y in pts], 255, px, dash)
        if fmask is not None:
            cv.composite(fmask, POLY[style][0], POLY[style][1])
            if POLY[style][4] is not None:
                cv.composite(ImageChops.multiply(fmask, _hatch(cv.img.size, POLY[style][4])), HATCH["role"], HATCH["alpha"],
                             stroke=True)
        if omask is not None:
            cv.composite(omask, POLY[style][2], 0.9, stroke=True)
        if lmask is not None:
            cv.composite(lmask, LINE[style][0], LINE[style][1], stroke=True)
        if n == 0:
            raise MapRefused(f"{spec['id']}: layer {ly['file']} {ly.get('where') or ''} matched nothing in view")


def _hatch(size, angle: float) -> Image.Image:
    """Parallel lines at `angle` degrees across the whole canvas (a coverage mask)."""
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    Wp, Hp = size
    gap = HATCH["gap"] * SS
    t = math.tan(math.radians(angle))
    span = int(abs(t) * Hp) + Wp
    for x0 in range(-span, span, gap):
        d.line([(x0, 0), (x0 + t * Hp, Hp)], fill=255, width=max(1, round(HATCH["px"] * SS)))
    return m


_OFF = {"e": (1, 0), "w": (-1, 0), "n": (0, -1), "s": (0, 1),
        "ne": (0.8, -0.8), "nw": (-0.8, -0.8), "se": (0.8, 0.8), "sw": (-0.8, 0.8)}


def _draw_marker(cv: Canvas, x: float, y: float, marker, r: float):
    R = r * SS
    halo = [x - R - 2 * SS, y - R - 2 * SS, x + R + 2 * SS, y + R + 2 * SS]
    disc = [x - R, y - R, x + R, y + R]
    if marker == "dot":
        cv.shape("halo", 1.0, lambda md: md.ellipse(halo, fill=255))
        cv.shape("text", 1.0, lambda md: md.ellipse(disc, fill=255))
    elif marker == "disc":
        cv.shape("halo", 1.0, lambda md: md.ellipse(halo, fill=255))
        cv.shape("cold", 1.0, lambda md: md.ellipse(disc, fill=255))
        cv.shape("cold_text", 1.0, lambda md: md.ellipse(disc, outline=255, width=2 * SS))
    elif marker == "ring":
        cv.shape("halo", 1.0, lambda md: md.ellipse(halo, fill=255))
        cv.shape("muted", 1.0, lambda md: md.ellipse(disc, outline=255, width=round(2.2 * SS)))


def _draw_places(cv: Canvas, spec: dict, proj: Projection) -> None:
    for p in spec.get("places", []):
        style = p.get("style", "town")
        marker, r, font, role = POINT[style]
        x, y = proj(p["lon"], p["lat"])
        x, y = x * SS, y * SS
        _draw_marker(cv, x, y, marker, r)
        if p.get("label") is False:
            continue
        name = p.get("label") or p["name"]
        size = SIZES["point_label_key"] if style == "key" or p.get("big") else SIZES["point_label"]
        ox, oy = _OFF[p.get("anchor", "e")]
        gap = (r + 7) * SS
        ax = "l" if ox > 0 else ("r" if ox < 0 else "m")
        lx, ly = x + ox * gap, y + oy * gap
        f = cv.font(font, size)
        asc, desc = f.getmetrics()
        lines = [(name, font, size, role)]
        if p.get("sub"):
            lines.append((p["sub"], "structure", SIZES["point_sub"],
                          "cold_text" if p.get("sub_role") == "cold" else "text"))
        total = sum(cv.font(fw, sz).getmetrics()[0] + cv.font(fw, sz).getmetrics()[1] * 0.6 for _, fw, sz, _ in lines)
        if oy < 0:
            top = ly - total
        elif oy > 0:
            top = ly
        else:
            top = ly - asc * 0.62
        for text, fw, sz, rl in lines:
            fa, fd = cv.font(fw, sz).getmetrics()
            base = top + fa
            cv.text((lx, base), text, fw, sz, rl, anchor=ax + "s", kind="place", group=("place", spec["id"], name))
            top = base + fd * 0.6


def _draw_labels(cv: Canvas, spec: dict, proj: Projection) -> None:
    for lb in spec.get("labels", []):
        font, size, role = LABEL[lb["style"]]
        x, y = proj(lb["lon"], lb["lat"])
        dx, dy = lb.get("offset", (0, 0))   # px at 1080p, to sit beside a line rather than on it
        x, y = x + dx, y + dy
        anchor = {"l": "lm", "c": "mm", "r": "rm"}[lb.get("align", "c")]
        lines = lb["text"].split("\n")
        f = cv.font(font, size)
        asc, desc = f.getmetrics()
        lh = (asc + desc) * 1.08
        y0 = y * SS - lh * (len(lines) - 1) / 2
        for i, t in enumerate(lines):
            cv.text((x * SS, y0 + i * lh), t, font, size, lb.get("role", role), anchor=anchor, kind="label",
                    group=("label", spec["id"], lb["text"]))


def _wrap(cv: Canvas, text: str, which: str, pct: float, max_w: float) -> list[str]:
    words, lines, cur = text.split(" "), [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if cur and cv.measure(cand, which, pct) > max_w:
            lines.append(cur)
            cur = w
        else:
            cur = cand
    return lines + ([cur] if cur else [])


def _swatch(cv: Canvas, style: str, x: float, y: float, w: float) -> None:
    """A legend key at x..x+w on the line's mid-height y (2x px)."""
    if style in LINE:
        role, a, px, dash = LINE[style]
        cv.shape(role, a, lambda md: _line_on(md, [(x, y), (x + w, y)], 255, px, dash))
    elif style in POLY:
        role, a, orole, _, hatch = POLY[style]
        h = 0.55 * w
        m, md = cv.mask()
        md.rectangle([x, y - h / 2, x + w, y + h / 2], fill=255)
        cv.composite(m, role, a)
        if hatch is not None:
            cv.composite(ImageChops.multiply(m, _hatch(cv.img.size, hatch)), HATCH["role"], HATCH["alpha"])
        m, md = cv.mask()
        md.rectangle([x, y - h / 2, x + w, y + h / 2], outline=255, width=SS)
        cv.composite(m, orole or "faint", 1.0)
    else:
        marker, r, _, _ = POINT[style]
        _draw_marker(cv, x + w / 2, y, marker, r)


def _draw_panel(cv: Canvas, spec: dict) -> None:
    x0, x1 = PANEL["x"] * W * SS, (PANEL["x"] + PANEL["w"]) * W * SS
    # the wash: theatre black, feathered in from the left so the map is never cut by an edge
    xs = np.arange(W * SS, dtype=np.float32) / (W * SS)
    u = np.clip((xs - PANEL["wash_from"]) / (PANEL["wash_full"] - PANEL["wash_from"]), 0.0, 1.0)
    u = u * u * (3.0 - 2.0 * u)
    halo = cv.pal["halo"]
    a = (u * PANEL["wash_alpha"] * 255).astype(np.uint8)
    wash = np.zeros((H * SS, W * SS, 4), np.uint8)
    wash[..., 0], wash[..., 1], wash[..., 2] = halo[0], halo[1], halo[2]
    wash[..., 3] = a[None, :]
    cv.img.alpha_composite(Image.fromarray(wash))
    cv.d = ImageDraw.Draw(cv.img, "RGBA")
    y = PANEL["top"] * H * SS
    maxw = x1 - x0
    if spec.get("title") and spec.get("show_title", True):
        f = cv.font("display", SIZES["title"])
        asc, desc = f.getmetrics()
        for ln in _wrap(cv, spec["title"], "display", SIZES["title"], maxw):
            y += asc
            cv.text((x0, y), ln, "display", SIZES["title"], "text", halo=False, kind="title")
            y += desc + asc * 0.18
        y += 0.018 * H * SS
        cv.shape("muted", 1.0, lambda md, y=y: md.line([(x0, y), (x0 + 0.06 * W * SS, y)], fill=255, width=SS * 2))
        y += 0.022 * H * SS
    sw = 0.032 * W * SS
    for e in spec.get("legend", []):
        f = cv.font("structure", SIZES["legend"])
        asc, desc = f.getmetrics()
        lines = _wrap(cv, e["text"], "structure", SIZES["legend"], maxw - sw - 14 * SS)
        y += asc
        _swatch(cv, e["style"], x0, y - asc * 0.36, sw)
        for ln in lines:
            cv.text((x0 + sw + 14 * SS, y), ln, "structure", SIZES["legend"], "text", halo=False, kind="legend")
            y += (asc + desc) * 1.02
        y += 0.008 * H * SS - desc
    for fig in spec.get("figures", []):
        f = cv.font("data", LABEL["figure"][1])
        asc, desc = f.getmetrics()
        for ln in _wrap(cv, fig, "structure", LABEL["figure"][1], maxw):
            y += asc
            cv.text((x0, y), ln, "structure", LABEL["figure"][1], "text", halo=False, kind="figure")
            y += desc * 1.3
        y += 0.010 * H * SS
    if spec.get("notes"):
        y += 0.012 * H * SS
    for note in spec.get("notes", []):
        f = cv.font("structure", SIZES["note"])
        asc, desc = f.getmetrics()
        for ln in _wrap(cv, note, "structure", SIZES["note"], maxw):
            y += asc
            cv.text((x0, y), ln, "structure", SIZES["note"], "muted", halo=False, kind="note")
            y += desc * 1.25
        y += 0.010 * H * SS
    if y / SS > PANEL["bottom"] * H:
        raise MapRefused(f"{spec['id']}: the panel runs to {y / SS / H:.2f} of the frame height; at most {PANEL['bottom']}")


def _draw_paths(cv: Canvas, spec: dict, proj: Projection) -> None:
    """Lines the spec states point by point (a route a letter names between two
    towns): straight segments between the named places, never a course."""
    for pth in spec.get("paths", []):
        role, a, px, dash = LINE[pth["style"]]
        pts = [proj(*p) for p in pth["points"]]
        if pth.get("arrow"):  # stop short of the last town's marker
            (x0, y0), (x1, y1) = pts[-2], pts[-1]
            L = math.hypot(x1 - x0, y1 - y0)
            if L < 1.0:
                raise MapRefused(f"{spec['id']}: an arrow's last two points are the same place")
            back = min(14.0, L / 3)
            pts[-1] = (x1 - (x1 - x0) * back / L, y1 - (y1 - y0) * back / L)
        m, md = cv.mask()
        _line_on(md, [(x * SS, y * SS) for x, y in pts], 255, px, dash)
        cv.composite(m, role, a, stroke=True)
        if pth.get("arrow"):
            (x0, y0), (x1, y1) = pts[-2], pts[-1]
            ang = math.atan2(y1 - y0, x1 - x0)
            L = 13 * SS
            tip = (x1 * SS, y1 * SS)
            wing = [(tip[0] - L * math.cos(ang - s * 0.45), tip[1] - L * math.sin(ang - s * 0.45)) for s in (1, -1)]
            cv.shape(role, a, lambda md: md.polygon([tip, wing[0], wing[1]], fill=255))


def _draw_view(cv: Canvas, view: dict, proj: Projection, geodata: Path, used: dict) -> None:
    _draw_layers(cv, view, proj, geodata, used)
    _draw_paths(cv, view, proj)
    _draw_labels(cv, view, proj)
    _draw_places(cv, view, proj)


KEEPOUT_PAD = 14  # px at 1080p around the source line


def _source_keepout(cv: Canvas, src: str) -> list:
    """The 2x rectangle around the source line that no map stroke may cross."""
    f = cv.font("structure", SIZES["source"])
    asc, _ = f.getmetrics()
    x = SOURCE_LINE["x"] * W * SS
    base = SOURCE_LINE["baseline"] * H * SS
    w = cv.measure(src, "structure", SIZES["source"])
    pad = KEEPOUT_PAD * SS
    return [x - pad, base - asc - pad, x + w + pad, H * SS]


def _intersects(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _shrink(b, d: float) -> tuple:
    return b[0] + d, b[1] + d, b[2] - d, b[3] - d


def _zone(z) -> tuple:
    return z[0] * W, z[1] * H, z[2] * W, z[3] * H


def render_map(spec: dict, geodata: Path | str, *, fonts: M.Fonts | None = None,
               tokens: Path | str = TOKENS) -> tuple[Image.Image, dict]:
    """Render one spec. Returns the 1920x1080 RGB frame and what it drew (text
    boxes, geodata files with their sha256, warnings, the source line)."""
    check_spec(spec)
    fonts = fonts or M.Fonts()
    pal = palette(tokens)
    cv = Canvas(pal, fonts)
    show_title = spec.get("show_title", True)
    panel = bool((show_title and spec.get("title")) or spec.get("legend") or spec.get("notes") or spec.get("figures"))
    frame = tuple(spec.get("frame") or (DEFAULT_FRAME if panel else FULL_FRAME))
    used: dict[str, str] = {}
    src = source_line(spec)
    cv.keepout = _source_keepout(cv, src)
    views = spec.get("views")
    if not views:
        proj = Projection(spec["extent"], frame, (W, H))
        _draw_view(cv, spec, proj, Path(geodata), used)
    else:
        for v in views:
            vf = tuple(v["frame"])
            sub = Canvas(pal, fonts)
            sub.boxes = cv.boxes
            sub.keepout = cv.keepout
            before = len(cv.boxes)
            _draw_view(sub, {**v, "id": f"{spec['id']}/{v.get('name', '')}"}, Projection(v["extent"], vf, (W, H)),
                       Path(geodata), used)
            fx0, fy0, fx1, fy1 = vf[0] * W, vf[1] * H, vf[2] * W, vf[3] * H
            for b in cv.boxes[before:]:
                bx = b["box"]
                if bx[0] < fx0 or bx[1] < fy0 or bx[2] > fx1 or bx[3] > fy1:
                    raise MapRefused(f"{spec['id']}: text {b['text']!r} is clipped by its view's frame")
            mask = Image.new("L", cv.img.size, 0)
            ImageDraw.Draw(mask).rectangle([vf[0] * W * SS, vf[1] * H * SS, vf[2] * W * SS, vf[3] * H * SS], fill=255)
            cv.img.paste(sub.img, (0, 0), mask)
            cv.d = ImageDraw.Draw(cv.img, "RGBA")
            rect = [vf[0] * W * SS, vf[1] * H * SS, vf[2] * W * SS, vf[3] * H * SS]
            cv.shape("faint", 1.0, lambda md, rect=rect: md.rectangle(rect, outline=255, width=SS))
    if panel:
        _draw_panel(cv, spec)
    cv.text((SOURCE_LINE["x"] * W * SS, SOURCE_LINE["baseline"] * H * SS), src, "structure", SIZES["source"],
            "muted", halo=True, kind="source")
    if cv.boxes[-1]["box"][2] > 0.96 * W:
        raise MapRefused(f"{spec['id']}: the source line is wider than the frame's safe width")
    warnings = []
    for b in cv.boxes:
        bx = b["box"]
        if bx[0] < 0 or bx[1] < 0 or bx[2] > W or bx[3] > H:
            raise MapRefused(f"{spec['id']}: text {b['text']!r} leaves the frame")
        for name, z in FORBIDDEN.items():
            if _intersects(bx, _zone(z)):
                raise MapRefused(f"{spec['id']}: text {b['text']!r} enters the {name} zone")
        if b["kind"] in ("place", "label"):
            for name, z in COVERED.items():
                if _intersects(bx, _zone(z)):
                    warnings.append(f"{b['text']!r} sits in the {name} zone")
    labels = [b for b in cv.boxes if b["kind"] in ("place", "label")]
    for i, a in enumerate(labels):
        for b in labels[i + 1:]:
            if a["group"] != b["group"] and _intersects(_shrink(a["box"], 2), _shrink(b["box"], 2)):
                raise MapRefused(f"{spec['id']}: labels {a['text']!r} and {b['text']!r} overlap")
    img = cv.img.resize((W, H), Image.LANCZOS).convert("RGB")
    info = {"id": spec["id"], "source_line": src, "boxes": cv.boxes, "geodata": used, "warnings": warnings,
            "size": [W, H]}
    return img, info


def png_bytes(img: Image.Image) -> bytes:
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False, compress_level=6)
    return buf.getvalue()


def contact_sheet(paths: list[Path], out: Path, cols: int = 3, thumb_w: int = 640) -> None:
    thumbs = []
    for p in paths:
        with Image.open(p) as im:
            thumbs.append(im.convert("RGB").resize((thumb_w, round(thumb_w * im.height / im.width)), Image.LANCZOS))
    th = thumbs[0].height
    rows = math.ceil(len(thumbs) / cols)
    gap = 12
    pal = palette()
    sheet = Image.new("RGB", (cols * thumb_w + (cols + 1) * gap, rows * th + (rows + 1) * gap), pal["sea"][:3])
    for i, t in enumerate(thumbs):
        r, c = divmod(i, cols)
        sheet.paste(t, (gap + c * (thumb_w + gap), gap + r * (th + gap)))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Render map specs to 1920x1080 DRAWN frames.")
    ap.add_argument("specs", nargs="+")
    ap.add_argument("--geodata", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sheet")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    written, report, failed = [], [], 0
    for sp in a.specs:
        spec = json.loads(Path(sp).read_text(encoding="utf-8"))
        try:
            img, info = render_map(spec, a.geodata)
        except MapRefused as e:
            print(f"REFUSED {sp}: {e}")
            failed += 1
            continue
        data = png_bytes(img)
        dst = out / f"{spec['id']}.png"
        dst.write_bytes(data)
        written.append(dst)
        report.append({"id": spec["id"], "file": str(dst), "sha256": hashlib.sha256(data).hexdigest(),
                       "geodata": info["geodata"], "warnings": info["warnings"], "ledger": ledger_fields(spec)})
        print(f"{spec['id']}: {dst} sha256 {report[-1]['sha256'][:16]}"
              + (f"  warnings: {'; '.join(info['warnings'])}" if info["warnings"] else ""))
    (out / "maps-render.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    if a.sheet:
        contact_sheet(written, Path(a.sheet))
        print("sheet:", a.sheet)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
