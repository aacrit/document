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
    "numeral": "--mark-text",            # a count card's numeral (BRAND-KIT 7: numerals are --mark-text)
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
    # E8, a per-country, per-year data layer: three states, each visibly distinct. A country with
    # cases is lit in DRAWN's hue; a reported zero is dark but raised and outlined, a country the
    # table really counted; a country with no figure for the year is the plain land, hatched faint,
    # so "no data" can never be read as zero.
    "cases": ("cold", 0.72, "cold_text", 1.2, None),
    "zero": ("focus", 1.0, "faint", 1.0, None),
    "nodata": ("land", 1.0, None, 0, 45),
}
HATCH = dict(role="cold_text", alpha=0.5, px=1.6, gap=14)
# a style whose hatch is not DRAWN's blue: (role, alpha). No data is hatched in a rule colour, never a data hue.
HATCH_ROLE = {"nodata": ("faint", 0.45)}
DATA_STATES = ("cases", "zero", "nodata")
# lines: (role, alpha, px, dash px or None)
LINE = {
    "coast": ("faint", 0.6, 1.4, None),
    "border": ("faint", 1.0, 2.0, None),
    "border_fine": ("faint", 0.8, 1.0, None),   # a world or regional extent's country borders
    "border_today": ("muted", 0.9, 2.4, (10, 7)),
    "working": ("muted", 1.0, 2.2, (3, 5)),
    "river": ("cold_text", 0.85, 2.2, None),
    "road": ("muted", 1.0, 2.6, (6, 6)),
    "line": ("line", 1.0, 5.0, None),
    "line_dashed": ("line", 1.0, 4.0, (14, 9)),
}
# line styles laid on a solid dark band, so a dotted line reads over a shaded area's outline
HALOED = {"working"}
HALO_PX = 4.0
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
             note=1.55, source=1.5, figure_sub=2.3)   # figure_sub: a data figure's numeral, 1.3x a sub-line
# Zones (fractions of the frame) no map text may enter: the mark plate and the watermark.
FORBIDDEN = {"mark": (0.0, 0.0, 0.30, 0.20), "watermark": (0.88, 0.0, 1.0, 0.12)}
# Zones the film's own text may cover for a few seconds: labels there are warned.
COVERED = {"lower_third": (0.04, 0.75, 0.60, 0.93), "overlay": (0.60, 0.84, 0.96, 0.93),
           "subtitle": (0.08, 0.80, 0.92, 0.93)}
PANEL = dict(x=0.715, w=0.245, top=0.15, bottom=0.80, wash_from=0.64, wash_full=0.70, wash_alpha=0.82)
SOURCE_LINE = dict(x=0.04, baseline=0.972)   # film 1's frames; a spec may set `source_at` (film 2: 0.05, 0.94)


def source_at(spec: dict) -> dict:
    at = spec.get("source_at")
    if at is None:
        return SOURCE_LINE
    if not (isinstance(at, dict) and 0.03 <= at.get("x", -1) <= 0.10 and 0.90 <= at.get("baseline", -1) <= 0.972):
        raise MapRefused(f"{spec.get('id', '')}: source_at is {{x: 0.03 to 0.10, baseline: 0.90 to 0.972}}")
    return at
DEFAULT_FRAME = (0.04, 0.12, 0.68, 0.92)  # where the extent is fitted when a panel is shown
FULL_FRAME = (0.04, 0.08, 0.96, 0.92)     # when there is no panel


# --------------------------------------------------------------------------
# Spec checks
# --------------------------------------------------------------------------

GEONAMES = "GeoNames (CC BY 4.0)"
# Lines no open dataset places, which no spec may draw solid: (pair of ADM0_A3 codes, why).
UNPLACED = [({"BGD", "IND"}, "the Bengal award's line: no open dataset places it, so it is drawn only as "
                             "today's border, dashed")]
# On an unplaced pair only today's border, dashed, may be drawn: every other line style reads as a placed line.
ON_UNPLACED_OK = ("border_today",)


def unplaced_list(spec: dict) -> list:
    """The pairs a spec may not draw solid (E8: a per-film list). A spec that states
    `unplaced` (a list of {"pair": [A, B], "why": ...}, possibly empty) uses its own list;
    a spec that does not keeps the engine's default, the Partition film's Bengal award line,
    so film 1's specs read as they always did."""
    if "unplaced" not in spec:
        return UNPLACED
    out = []
    for u in spec["unplaced"] or []:
        pair = u.get("pair") if isinstance(u, dict) else None
        if not pair or len(pair) != 2 or not u.get("why"):
            raise MapRefused(f"{spec.get('id', '')}: each unplaced entry is a pair of two ADM0_A3 codes and a why")
        out.append((set(pair), u["why"]))
    return out


def _refused_on_unplaced(style) -> bool:
    return style in LINE and style not in ON_UNPLACED_OK


def _as_set(v) -> set | None:
    """A `where` value as the set of values it accepts; None when the key is not filtered."""
    if v is None:
        return None
    if isinstance(v, dict):
        raise MapRefused(f"a where value is a value or a list of values, never a mapping ({v})")
    return set(v) if isinstance(v, (list, tuple, set)) else {v}


def _unplaced_pair_possible(where: dict, unplaced=None) -> str | None:
    """Static check: a filter that names both sides and can match an unplaced pair.
    One-sided and unfiltered layers are checked on the features they match at render."""
    left, right = _as_set(where.get("ADM0_A3_L")), _as_set(where.get("ADM0_A3_R"))
    if left is None or right is None:
        return None
    for codes, why in (UNPLACED if unplaced is None else unplaced):
        a, b = sorted(codes)
        if (a in left and b in right) or (b in left and a in right):
            return f"on {[a, b]} is refused: {why}"
    return None


def unplaced_feature(props: dict, unplaced=None) -> str | None:
    """The reason a feature may not be drawn solid, from its own ADM0_A3_L/R pair."""
    pair = {props.get("ADM0_A3_L"), props.get("ADM0_A3_R")}
    for codes, why in (UNPLACED if unplaced is None else unplaced):
        if pair == codes:
            return why
    return None
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
        bad_where = [k for k, val in where.items() if isinstance(val, dict)]
        if bad_where:
            raise MapRefused(f"{spec['id']}: layer {ly.get('file')} where {bad_where[0]!r} is a mapping; "
                             "a where value is a value or a list of values")
        if _refused_on_unplaced(ly.get("style")):
            why = _unplaced_pair_possible(where, unplaced_list(spec))
            if why:
                raise MapRefused(f"{spec['id']}: a {ly.get('style')!r} layer {why}")
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
    for v in views:
        if "data" not in v:
            continue
        data = v["data"]
        check_data_block(spec["id"], data, [x["id"] for x in src])
        if data.get("territories") and data.get("territories_note") not in spec.get("notes", []):
            raise MapRefused(f"{spec['id']}: a territory drawn with another country's figure needs its "
                             "territories_note among the frame's notes, saying which and why")
        for yr in re.findall(r"\b(1[5-9]\d\d|20\d\d)\b", spec.get("title", "")):
            if int(yr) != data["year"]:
                raise MapRefused(f"{spec['id']}: the title names {yr}; the data layer draws {data['year']}")
        for fg in data.get("figures") or []:
            if not ISO3.match(str(fg.get("code", ""))):
                raise MapRefused(f"{spec['id']}: a data figure names a country by its ISO3 code")
    if any("data" in v for v in views):
        _lint_data_text(spec, views)


def _lint_data_text(spec: dict, views: list) -> None:
    """A data map's numbers come from its data. Every on-frame string is linted for digits and
    number words: the title may name the data year, a panel figure template its {n} and the data
    year; nothing else may carry a number, which would be uncited."""
    years = {str(v["data"]["year"]) for v in views if "data" in v}
    title = spec.get("title", "")
    for y in years:
        title = re.sub(r"(?<!\d)" + y + r"(?!\d)", "", title)
    texts = [("title", title)]
    texts += [(f"legend[{i}]", e.get("text", "")) for i, e in enumerate(spec.get("legend", []))]
    texts += [(f"notes[{i}]", n) for i, n in enumerate(spec.get("notes", []))]
    texts += [(f"figures[{i}]", f) for i, f in enumerate(spec.get("figures", []))]
    for v in views:
        texts += [("label", lb.get("text", "")) for lb in v.get("labels", [])]
        texts += [("place", f"{pl.get('label') or pl.get('name', '')} {pl.get('sub', '')}") for pl in v.get("places", [])]
        d = v.get("data") or {}
        texts += [("data figure label", f.get("label", "")) for f in d.get("figures") or []]
        for pf in d.get("panel_figures") or []:
            t = pf.get("text", "").replace("{n}", "", 1)
            for y in years:
                t = t.replace(y, "")
            texts.append(("panel figure", t))
    for where, t in texts:
        bad = uncited_numbers(t)
        if bad:
            raise MapRefused(f"{spec['id']}.{where}: {t!r} carries {bad} with no citation; a data map's numbers "
                             "come from its data")


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
        "data_layer": [{"csv": v["data"]["csv"], "sha256": v["data"]["sha256"], "column": v["data"]["columns"]["value"],
                        "year": v["data"]["year"], "match": "ISO3 against Natural Earth (ISO_A3, else ISO_A3_EH)",
                        "territories": v["data"].get("territories") or {}}
                       for v in views if "data" in v],
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
    for d in claims["data_layer"]:
        text.append(f"each country's state in {d['year']} from {d['csv']} column {d['column']} (sha256 {d['sha256'][:12]}), "
                    "matched by ISO3: cases reported (over 0), zero reported, or no figure in the table; "
                    "no year interpolated" + ("; territories drawn with a country's figure as the frame notes"
                                              if d["territories"] else ""))
    if claims["data_layer"]:
        text.append("plate carree projection")
    claims["text"] = "; ".join(text)
    return claims


# A frame the studio's engine draws (a map, a count card) shows no photographed person: its content
# flags are false by construction, stated by the generator itself so every film's ledger carries them
# (GRAMMAR A21's content schema; policy.asset_checks refuses an unstated flag).
DRAWN_CONTENT = {"graphic_medical": False, "named_patient": False, "shows_violence": False, "shows_bodies": False,
                 "people": []}


def ledger_fields(spec: dict) -> dict:
    """What the drawn ledger says about a map, from the spec alone, so the mark
    plate, the ledger and the frame's source line always agree."""
    ds = data_source(spec)
    geo = GEONAMES in [s["id"] for s in spec["sources"]]
    by = [s["id"] for s in spec["sources"] if s["id"] != GEONAMES and re.match(r"(?i)cc[- ]?by\b", s["licence"])]
    note = "Natural Earth public domain"
    if geo:
        note = "contains GeoNames data (CC BY 4.0); " + note
    if by:
        note = f"contains data under CC BY 4.0 ({'; '.join(by)}); " + note
    return {"title": spec["title"], "data_source": ds, "source_short": spec["source_short"],
            "credit": "void document studio, drawn from " + ds,
            # a canonical id the render engine's licence allowlist recognises; the why goes in licence_note
            "licence": "CC-BY-4.0" if (geo or by) else "CC0",
            "licence_note": note,
            "data_sources": spec["sources"], "source_line": source_line(spec), "method": method(spec),
            **DRAWN_CONTENT}


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


def file_sha256(path: str) -> str:
    """A file's sha256, cached on its path, size and mtime, so a file rewritten in place is hashed again."""
    st = Path(path).stat()
    return _file_sha256(str(path), st.st_size, st.st_mtime_ns)


@lru_cache(maxsize=64)
def _file_sha256(path: str, size: int, mtime_ns: int) -> str:
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
        if isinstance(vals, dict):
            raise MapRefused(f"where {k!r} is a mapping; a where value is a value or a list of values")
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
# Cited data (E8): a CSV or a text file named by path and sha256, read only
# through a citation, so a number on a frame is always a cell of a file whose
# bytes the spec states. Nothing is interpolated: a year with no row is "no
# data", never a value between its neighbours.
# --------------------------------------------------------------------------

ISO3 = re.compile(r"^[A-Z]{3}$")
NE_COUNTRIES = "naturalearth/ne_10m_admin_0_countries.geojson"
NUMBER_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
                "eleven", "twelve")
# every English number word a frame could carry; none may stand in on-frame text outside a cited {n}
NUMBER_WORD_RE = re.compile(
    r"(?i)\b(zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
    r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|"
    r"thousand|million|billion|dozen|dozens|hundreds|thousands|millions|billions|lakh|lakhs|crore|crores|"
    r"nought|naught|nil|none|single|half|once|twice|handful)\b")
# a quoted numeral's declared span: what may not follow it, stand before it, or negate it
# A text citation for a numeral is one or more whole sentences holding exactly one number and one year.
SENTENCE_END = re.compile(r"[.!?][\"\u201d\u2019)\]]*$")
SENTENCE_GAP = re.compile(r"[.!?][\"\u201d\u2019)\]]*\s+$")
DIGIT_TOKEN = re.compile(r"[0-9]+(?:[,.\u00b7][0-9]+)*")
NEGATORS = re.compile(r"(?i)\b(no|not|never|nor|without|none|nobody)\b|n't\b")
QUALIFIERS = re.compile(r"(?i)\b(more than|less than|fewer than|at least|at most|over|under|about|around|nearly|"
                        r"almost|roughly|up to|some|approximately|estimated)\b")
RELATIVE_YEAR = re.compile(r"(?i)\b(next|following|previous|same|that|this|last) year\b|\ba year (later|earlier|before|after)\b")
YEAR_RANGE = re.compile(r"[0-9]{4}\s*[-\u2010-\u2015/]\s*[0-9]{2,4}")
PERCENT_AFTER = re.compile(r"(?i)^\s*(%|per ?cent\b)")


def uncited_numbers(text: str) -> list:
    """Digits and number words in on-frame text (the caller removes {n} and any allowed year)."""
    return re.findall(r"\d+", text) + [m.group(0) for m in NUMBER_WORD_RE.finditer(text)]


def _cited_path(cite: dict, key: str, data_root) -> Path:
    for k in (key, "sha256", "licence", "source"):
        if not cite.get(k):
            raise MapRefused(f"a citation needs {key}, sha256, licence and source (lacks {k}): {cite}")
    if data_root is None:
        raise MapRefused(f"{cite[key]}: cited data needs a data root (--data)")
    path = Path(data_root) / cite[key]
    if not path.exists():
        raise MapRefused(f"{cite[key]}: not found under {data_root}")
    sha = file_sha256(str(path))
    if sha != cite["sha256"]:
        raise MapRefused(f"{cite[key]}: its sha256 is {sha}; the citation says {cite['sha256']} "
                         "(the file changed, or the citation names another copy)")
    return path


@lru_cache(maxsize=16)
def _csv_rows(path: str, sha: str) -> tuple:
    import csv
    with open(path, encoding="utf-8", newline="") as fh:
        rd = csv.DictReader(fh)
        # the line a row sits on in the file (the header is line 1), so a citation can name it
        return tuple((i + 2, dict(r)) for i, r in enumerate(rd))


def doubts_path(csv_path: Path) -> Path:
    return csv_path.with_name(csv_path.stem + ".doubts.json")


@lru_cache(maxsize=16)
def _sidecar(path: str, sha: str, csv_rel: str, csv_sha: str, data_root: str) -> tuple:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if d.get("csv_sha256") != csv_sha:
        raise MapRefused(f"{Path(path).name}: pins {csv_rel} at sha256 {d.get('csv_sha256')}; the file is {csv_sha}. "
                         "The doubts belong to one copy of the table: re-read them against this one")
    out = []
    for c in d.get("conflicts") or []:
        if not c.get("row") or not c.get("text") or not c.get("why"):
            raise MapRefused(f"{Path(path).name}: a conflict names its row, the text that contradicts it, and why")
        q = text_quote(c["text"], data_root)
        out.append(("conflict", csv_rel, c["row"], f"{csv_rel} {c['row']} against {q['text']} line {q['line']}: "
                                                   f"\"{q['quote']}\" ({c['why']})"))
    for z in d.get("zero_suspect") or []:
        if not z.get("row") or not z.get("why"):
            raise MapRefused(f"{Path(path).name}: a zero_suspect entry names its row and why")
        out.append(("zero_suspect", csv_rel, z["row"], f"{csv_rel} {z['row']} ({z['why']})"))
    return tuple(out)


def table_doubts(cite: dict, data_root) -> list:
    """The doubts that travel with a cited CSV: `<name>.doubts.json` beside it, pinned to the CSV's
    sha256, and itself pinned by every citation of the CSV (`doubts_sha256`, beside `sha256`). A
    missing sidecar, or one whose sha256 differs from the pin, refuses: no spec can opt out of the
    table's doubts or swap them; a spec may only add its own."""
    path = Path(data_root) / cite["csv"]
    side = doubts_path(path)
    pin = cite.get("doubts_sha256")
    if not pin:
        raise MapRefused(f"{cite['csv']}: a citation of a table pins its doubts too (doubts_sha256 of {side.name})")
    if not side.exists():
        raise MapRefused(f"{cite['csv']}: its doubts file {side.name} is missing; the citation pins {pin}")
    got = file_sha256(str(side))
    if got != pin:
        raise MapRefused(f"{side.name}: its sha256 is {got}; the citation pins {pin} (the table's doubts changed, "
                         "or this is another copy)")
    return list(_sidecar(str(side), got, cite["csv"], file_sha256(str(path)), str(data_root)))


def cited_csv(cite: dict, data_root) -> tuple:
    """The rows of a cited CSV as (line, row), after its sha256 is checked."""
    path = _cited_path(cite, "csv", data_root)
    return _csv_rows(str(path), cite["sha256"])


def _int_cell(raw: str, where: str) -> int | None:
    raw = (raw or "").strip()
    if raw == "":
        return None
    if not re.fullmatch(r"-?\d+", raw):
        raise MapRefused(f"{where}: the cell {raw!r} is not a whole count")
    return int(raw)


def _years(rows, ycol: str) -> tuple[int, int]:
    ys = [int(r[ycol]) for _, r in rows if (r.get(ycol) or "").strip().lstrip("-").isdigit()]
    return (min(ys), max(ys)) if ys else (0, 0)


def csv_cell(cite: dict, data_root, extra=()) -> dict:
    """One cell: the row whose columns equal `row` (e.g. entity and year), the `column`
    named. Refused when no row or several rows match, when the cell is empty (no figure is
    not zero), when the citation's `line` is not the line the row sits on, or when the table's
    doubts (its sidecar) or the spec's added doubts name the cell."""
    rows = cited_csv(cite, data_root)
    col, key = cite.get("column"), cite.get("row") or {}
    if not col or not key:
        raise MapRefused(f"{cite['csv']}: a cell citation names a column and a row (its key columns)")
    hit = [(ln, r) for ln, r in rows if all(str(r.get(k, "")) == str(v) for k, v in key.items())]
    if not hit:
        ycol = cite.get("year_column", "year")
        span = _years(rows, ycol) if rows and ycol in rows[0][1] else None
        rng = f"; the table's {ycol} runs {span[0]} to {span[1]}" if span else ""
        raise MapRefused(f"{cite['csv']}: no row where {key}{rng}. A figure the table does not hold is "
                         "never drawn from it: cite the source that does")
    if len(hit) > 1:
        raise MapRefused(f"{cite['csv']}: {len(hit)} rows where {key}; a cell citation must name one row")
    ln, r = hit[0]
    if col not in r:
        raise MapRefused(f"{cite['csv']}: no column {col!r}")
    if cite.get("line") is not None and int(cite["line"]) != ln:
        raise MapRefused(f"{cite['csv']}: the row where {key} is on line {ln}; the citation says line {cite['line']}")
    v = _int_cell(r[col], f"{cite['csv']} line {ln}")
    if v is None:
        raise MapRefused(f"{cite['csv']} line {ln}: the cell {col} is empty: no figure, which is not zero")
    why = doubt_on(table_doubts(cite, data_root) + list(extra), cite["csv"], key, v)
    if why:
        raise MapRefused(f"{cite['csv']} line {ln}: {why}")
    return {"kind": "cell", "csv": cite["csv"], "sha256": cite["sha256"], "doubts_sha256": cite["doubts_sha256"],
            "line": ln, "column": col, "row": key, "value": v}


def csv_count(cite: dict, data_root, extra=()) -> dict:
    """A derived count: the rows matching `where` whose `column` is over zero and whose
    `code_column` holds an ISO 3166 alpha-3 code (so regions and aggregates, whose codes are
    empty or OWID_*, are never counted as countries)."""
    rows = cited_csv(cite, data_root)
    col, where = cite.get("column"), cite.get("where") or {}
    ccol = cite.get("code_column", "code")
    if not col or not where:
        raise MapRefused(f"{cite['csv']}: a count citation names a column and a where")
    hit = [(ln, r) for ln, r in rows if all(str(r.get(k, "")) == str(v) for k, v in where.items())]
    if not hit:
        raise MapRefused(f"{cite['csv']}: no row where {where}")
    for kind, csv_, drow, msg in table_doubts(cite, data_root) + list(extra):
        if (csv_ is None or csv_ == cite["csv"]) and all(str(drow.get(k)) == str(v) for k, v in where.items()
                                                        if k in drow):
            raise MapRefused(f"{cite['csv']}: a count where {where} takes in a doubted row ({kind}: {msg}); "
                             "a count over a doubted cell is not drawn")
    lines = [ln for ln, r in hit if ISO3.match(r.get(ccol) or "") and (_int_cell(r[col], cite["csv"]) or 0) > 0]
    return {"kind": "count", "csv": cite["csv"], "sha256": cite["sha256"], "doubts_sha256": cite["doubts_sha256"],
            "column": col, "where": where,
            "rule": (f"rows with an ISO3 {ccol} and {col} over 0: countries as the table codes them, by today's "
                     "ISO3 codes, so a state of the time since divided counts as its parts"),
            "lines": lines, "value": len(lines)}


def text_quote(cite: dict, data_root) -> dict:
    """A quotation: `quote` must stand verbatim in lines `line` to `line + lines - 1` of the
    cited text file, the lines joined by one space."""
    path = _cited_path(cite, "text", data_root)
    if not cite.get("line") or not cite.get("quote"):
        raise MapRefused(f"{cite['text']}: a text citation names a line and a quote")
    lines = Path(path).read_text(encoding="utf-8").split("\n")
    a = int(cite["line"])
    n = int(cite.get("lines", 1))
    if a < 1 or a + n - 1 > len(lines):
        raise MapRefused(f"{cite['text']}: line {a} is outside the file ({len(lines)} lines)")
    span = " ".join(x.strip() for x in lines[a - 1:a - 1 + n])
    if cite["quote"] not in span:
        raise MapRefused(f"{cite['text']} line {a}: {cite['quote']!r} is not in the cited lines ({span!r})")
    out = {"kind": "quote", "text": cite["text"], "sha256": cite["sha256"], "line": a, "lines": n,
           "quote": cite["quote"], "_span": span}
    if cite.get("attested"):
        out["attested"] = cite["attested"]
    return out


def resolve_cite(cite: dict, data_root, extra=()) -> dict:
    if "text" in cite:
        return text_quote(cite, data_root)
    if "csv" in cite and cite.get("count"):
        return csv_count(cite, data_root, extra)
    if "csv" in cite:
        return csv_cell(cite, data_root, extra)
    raise MapRefused(f"a citation is a csv cell, a csv count or a text quote: {cite}")


def digits(s: str) -> str:
    return re.sub(r"[,\s]", "", s)


def numeral_supported(numeral: str, got: dict) -> bool:
    """A cell or count supports a numeral when it equals the value. A quote never does by
    itself: check_numeral_sentence judges a quoted count."""
    if got["kind"] in ("cell", "count"):
        n = digits(numeral)
        return n.lstrip("-").isdigit() and int(n) == got["value"]
    return False


def _declared(cite: dict, key: str) -> tuple:
    sp = cite.get(key)
    if not (isinstance(sp, list) and len(sp) == 2 and all(isinstance(x, int) and not isinstance(x, bool) for x in sp)):
        raise MapRefused(f"{cite.get('text')} line {cite.get('line')}: a text citation declares {key}: [start, end], "
                         "character offsets into its quote")
    s_, e_ = sp
    if not 0 <= s_ < e_ <= len(cite["quote"]):
        raise MapRefused(f"{cite.get('text')}: {key} {sp} is outside the quote ({len(cite['quote'])} characters)")
    return s_, e_


def sentence_tokens(q: str) -> tuple:
    """Every number token in a quote: digit runs (with their , . and middle-dot groups, so 1,500
    and 1.5 are one token each) and number words; a bare four-digit run is a year."""
    nums, years = [], []
    for m in DIGIT_TOKEN.finditer(q):
        (years if re.fullmatch(r"[0-9]{4}", m.group(0)) else nums).append((m.start(), m.end(), m.group(0)))
    for m in NUMBER_WORD_RE.finditer(q):
        nums.append((m.start(), m.end(), m.group(0)))
    return sorted(nums), years


def check_numeral_sentence(cite: dict, got: dict, numeral: str, year: str) -> None:
    """A text citation for a count, so strict nothing is left to interpret (CoS ruling on PR #16):
    the quote is one or more whole sentences of the cited lines; it holds exactly one number token
    and exactly one four-digit year (no other number of any kind, no two-digit year, no year range,
    no relative year); no negator and no qualifier anywhere in it; the declared spans `numeral_at`
    and `year_at` are exactly those two tokens; the number equals the card's and the year the card's;
    and a person has attested that the sentence means this count for this year (`attested`)."""
    q, span = cite["quote"], got["_span"]
    where = f"{cite.get('text')} line {cite.get('line')}"
    att = cite.get("attested")
    if not (isinstance(att, dict) and all(str(att.get(k) or "").strip() for k in ("by", "date", "note"))):
        raise MapRefused(f"{where}: a count from a text needs `attested: {{by, date, note}}`: a person's statement that "
                         "the sentence means this count for this year")
    starts = [i for i in range(len(span)) if span.startswith(q, i)
              and (i == 0 or SENTENCE_GAP.search(span[:i])) and (i + len(q) == len(span) or span[i + len(q)].isspace())]
    if not starts or not SENTENCE_END.search(q):
        raise MapRefused(f"{where}: the quote is not one or more whole sentences of the cited lines; a count is "
                         "quoted whole, never trimmed")
    if any(ch.isdigit() and not ("0" <= ch <= "9") for ch in q):
        raise MapRefused(f"{where}: the quote holds digits of another script; a count is read from ASCII digits only")
    for rx, what in ((NEGATORS, "a negator"), (QUALIFIERS, "a qualifier"), (RELATIVE_YEAR, "a relative year"),
                     (YEAR_RANGE, "a year range")):
        m = rx.search(q)
        if m:
            raise MapRefused(f"{where}: the sentence holds {what} ({m.group(0)!r}); it does not state one count")
    nums, years = sentence_tokens(q)
    if len(nums) != 1:
        raise MapRefused(f"{where}: the sentence holds {len(nums)} numbers ({[t[2] for t in nums]}); a count is "
                         "cited from a sentence with exactly one")
    if len(years) != 1:
        raise MapRefused(f"{where}: the sentence holds {len(years)} years ({[t[2] for t in years]}); exactly one")
    (ns, ne, ntext), (ys, ye, ytext) = nums[0], years[0]
    if [ns, ne] != list(_declared(cite, "numeral_at")):
        raise MapRefused(f"{where}: numeral_at {cite['numeral_at']} is not the sentence's number {ntext!r} at {[ns, ne]}")
    if [ys, ye] != list(_declared(cite, "year_at")):
        raise MapRefused(f"{where}: year_at {cite['year_at']} is not the sentence's year {ytext!r} at {[ys, ye]}")
    if PERCENT_AFTER.match(q[ne:]):
        raise MapRefused(f"{where}: {ntext!r} is a percentage, not a count")
    if re.fullmatch(r"[0-9]{1,3}(,[0-9]{3})+|[0-9]+", ntext):
        val = int(ntext.replace(",", ""))
    elif ntext.lower() in NUMBER_WORDS:
        val = NUMBER_WORDS.index(ntext.lower())
    else:
        raise MapRefused(f"{where}: {ntext!r} is not a whole count (digits, or one word zero to twelve)")
    n = digits(numeral)
    if not n.isdigit() or int(n) != val:
        raise MapRefused(f"{where}: the card says {numeral}; the sentence's number is {ntext!r} ({val})")
    if ytext != year:
        raise MapRefused(f"{where}: the card says {year}; the sentence's year is {ytext}")


# ---- doubts a film states about its own table

def _row_match(a: dict, b: dict) -> bool:
    return {str(k): str(v) for k, v in a.items()} == {str(k): str(v) for k, v in b.items()}


def check_doubts(spec: dict, data_root) -> list:
    """A spec's `conflicts` (a cell a cited text contradicts) and `zero_suspect` (a zero the film
    does not take as a report of no cases), resolved: each conflict's text quote must stand in its
    file. Returns the list of doubts as (kind, csv, row, message)."""
    out = []
    sid = spec.get("id", "")
    for c in spec.get("conflicts") or []:
        if not c.get("why") or not c.get("cell") or not c.get("text"):
            raise MapRefused(f"{sid}: a conflict names its cell, the text that contradicts it, and why")
        cell_ = c["cell"]
        q = text_quote(c["text"], data_root)
        cited = (f"{cell_['csv']} {cell_.get('row')} column {cell_.get('column')} against {q['text']} line "
                 f"{q['line']}: \"{q['quote']}\" ({c['why']})")
        out.append(("conflict", cell_["csv"], cell_.get("row") or {}, cited))
    for z in spec.get("zero_suspect") or []:
        if not z.get("why") or not z.get("row"):
            raise MapRefused(f"{sid}: a zero_suspect entry names its row and why")
        out.append(("zero_suspect", z.get("csv"), z["row"], f"{z['row']} ({z['why']})"))
    return out


def doubt_on(doubts: list, csv_path: str, row: dict, value) -> str | None:
    """The refusal for a cell the film doubts, or None."""
    for kind, csv_, drow, msg in doubts:
        if (csv_ is None or csv_ == csv_path) and _row_match(drow, row):
            if kind == "conflict":
                return f"the cell is contradicted by a cited text: {msg}"
            if kind == "zero_suspect" and value == 0:
                return f"the zero is suspect: {msg}"
    return None


# ---- the per-country, per-year layer ---------------------------------------

def ne_code(props: dict) -> str | None:
    """A Natural Earth country's ISO 3166 alpha-3: ISO_A3, or ISO_A3_EH where ISO_A3 is -99
    (France and Norway); None where neither is a code (Somaliland, Kosovo, the bases)."""
    for k in ("ISO_A3", "ISO_A3_EH"):
        v = props.get(k)
        if v and ISO3.match(v):
            return v
    return None


DATA_KEYS = ("csv", "sha256", "doubts_sha256", "licence", "source", "columns", "year")


def check_data_block(spec_id: str, data: dict, source_ids: list) -> None:
    for k in DATA_KEYS:
        if k not in data:
            raise MapRefused(f"{spec_id}: a data layer needs {', '.join(DATA_KEYS)} (lacks {k})")
    if data["source"] not in source_ids:
        raise MapRefused(f"{spec_id}: the data layer's source {data['source']!r} is not in the spec's sources")
    cols = data["columns"]
    for k in ("entity", "code", "year", "value"):
        if k not in cols:
            raise MapRefused(f"{spec_id}: data columns name entity, code, year and value (lacks {k})")
    if not isinstance(data["year"], int) or isinstance(data["year"], bool):
        raise MapRefused(f"{spec_id}: the data year is one whole year (no range, no interpolation)")
    for ent, why in (data.get("not_countries") or {}).items():
        if not isinstance(why, dict) or not why.get("why"):
            raise MapRefused(f"{spec_id}: not_countries[{ent!r}] states why it is not drawn")
    for iso, extra in (data.get("territories") or {}).items():
        if not isinstance(extra, list) or not extra:
            raise MapRefused(f"{spec_id}: territories[{iso!r}] is a list of Natural Earth ADM0_A3 codes")


def data_state(spec_id: str, data: dict, data_root, geodata: Path) -> dict:
    """Every Natural Earth country's state for the data year, from the cited CSV.

    Matching is by ISO3 against Natural Earth (`ne_code`). Every entity in the CSV is
    accounted for: it matches a Natural Earth country, or `codes` gives it one (an entity
    whose code is empty), or `not_countries` says why it is not drawn. Anything else is
    refused, never dropped. An entity not drawn may hold a count over zero in the data year
    only when it is marked an aggregate (a region whose countries are drawn on their own
    rows); a country that had cases and cannot be drawn is refused.
    State: `cases` (over 0), `zero` (0), `nodata` (no row, or an empty cell). No year is
    ever filled from its neighbours."""
    rows = cited_csv(data, data_root)
    cols = data["columns"]
    ecol, ccol, ycol, vcol = cols["entity"], cols["code"], cols["year"], cols["value"]
    if rows and any(c not in rows[0][1] for c in (ecol, ccol, ycol, vcol)):
        raise MapRefused(f"{spec_id}: {data['csv']} lacks a named column ({[ecol, ccol, ycol, vcol]})")
    year = str(data["year"])
    doubts = table_doubts(data, data_root)
    lo, hi = _years(rows, ycol)
    if not any(r[ycol] == year for _, r in rows):
        raise MapRefused(f"{spec_id}: {data['csv']} has no row for any entity in {year}; its {ycol} runs {lo} to {hi}. "
                         "A year outside the table is not drawn from it")
    cpath = geodata / data.get("countries_file", NE_COUNTRIES)
    if not cpath.exists():
        raise MapRefused(f"{spec_id}: geodata {data.get('countries_file', NE_COUNTRIES)} not found under {geodata}")
    feats = _load(str(cpath))
    ne_iso = {ne_code(p) for p, _, _ in feats} - {None}
    ne_adm = {p.get("ADM0_A3") for p, _, _ in feats}
    codes = data.get("codes") or {}
    not_c = data.get("not_countries") or {}
    terr = data.get("territories") or {}
    owner_of_adm = {}
    for iso, extra in terr.items():
        if iso not in ne_iso:
            raise MapRefused(f"{spec_id}: territories names {iso}, which is not a Natural Earth country")
        for adm in extra:
            if adm not in ne_adm:
                raise MapRefused(f"{spec_id}: territories[{iso}] names {adm}, which Natural Earth does not have")
            owner_of_adm[adm] = iso
    values: dict = {}
    unmatched, line_of, row_of = [], {}, {}
    by_entity: dict = {}
    for ln, r in rows:
        by_entity.setdefault((r[ecol], r[ccol]), []).append((ln, r))
    for (ent, code), rs in sorted(by_entity.items()):
        if ent in codes and code:
            raise MapRefused(f"{spec_id}: codes gives {ent!r} a code, but the CSV already codes it {code}")
        iso = codes.get(ent) or code
        if ent in not_c:
            if iso in ne_iso:
                raise MapRefused(f"{spec_id}: {ent!r} ({iso}) matches a Natural Earth country; it cannot be listed "
                                 "as not a country")
            for ln, r in rs:
                v = _int_cell(r[vcol], f"{data['csv']} line {ln}") if r[ycol] == year else None
                if v and not not_c[ent].get("aggregate"):
                    raise MapRefused(f"{spec_id}: {ent!r} reports {v} in {year} (line {ln}) and has no polygon to draw; "
                                     "a country with cases is never left off the map")
            continue
        if iso not in ne_iso:
            unmatched.append(f"{ent!r} ({code or 'no code'})")
            continue
        for ln, r in rs:
            if r[ycol] != year:
                continue
            if iso in values:
                raise MapRefused(f"{spec_id}: two rows for {iso} in {year} (lines {line_of[iso]} and {ln})")
            values[iso] = _int_cell(r[vcol], f"{data['csv']} line {ln}")
            line_of[iso] = ln
            row_of[iso] = {ecol: ent, ycol: year}
    if unmatched:
        raise MapRefused(f"{spec_id}: {len(unmatched)} CSV entities match no Natural Earth country by ISO3 and are "
                         f"not accounted for: {', '.join(unmatched[:8])}{' ...' if len(unmatched) > 8 else ''}. "
                         "Give each a code (codes) or say why it is not drawn (not_countries); none is dropped")
    for adm, iso in owner_of_adm.items():
        own = {ne_code(p) for p, _, _ in feats if p.get("ADM0_A3") == adm} - {None}
        if own & set(values):
            raise MapRefused(f"{spec_id}: territory {adm} has its own row in {year}; it cannot take {iso}'s figure")
    states = {}
    for p, _, _ in feats:
        adm = p.get("ADM0_A3")
        iso = owner_of_adm.get(adm) or ne_code(p)
        v = values.get(iso) if iso else None
        states[adm] = ("nodata" if v is None else "zero" if v == 0 else "cases", iso)
    return {"year": int(year), "values": values, "lines": line_of, "rows": row_of, "states": states,
            "owner_of_adm": owner_of_adm, "doubts": doubts,
            "lit": sorted(k for k, v in values.items() if v), "zero": sorted(k for k, v in values.items() if v == 0),
            "csv": data["csv"], "sha256": data["sha256"], "column": vcol, "countries_file": str(cpath)}


def _draw_data(cv, spec: dict, proj, geodata: Path, data_root, used: dict, record: dict) -> None:
    """Fill each country in view by its state, then check what the spec expects to be lit."""
    data = spec["data"]
    sid = spec.get("id", "")
    st = data_state(sid, data, data_root, geodata)
    used[data.get("countries_file", NE_COUNTRIES)] = file_sha256(st["countries_file"])
    clip = spec.get("_clip") or (0.0, 0.0, 1.0, 1.0)   # a view is clipped to its frame; a single view fills the frame
    view = proj.box(clip)
    doubts = st["doubts"] + check_doubts(spec, data_root)
    masks = {}
    in_view = {s: set() for s in DATA_STATES}
    terr_in_view = set()
    under = {}
    S8 = 8
    for props, g, bb in _load(st["countries_file"]):
        if not _overlaps(bb, view):
            continue
        state, iso = st["states"][props.get("ADM0_A3")]
        in_view[state].add(iso or props.get("ADM0_A3"))
        if props.get("ADM0_A3") in st["owner_of_adm"] and state != "nodata":
            terr_in_view.add(props.get("ADM0_A3"))
        if iso in st["rows"]:
            why = doubt_on(doubts, data["csv"], st["rows"][iso], st["values"][iso])
            if why:
                raise MapRefused(f"{sid}: {iso} in {st['year']} is drawn from line {st['lines'][iso]}, but {why}")
        if state in ("cases", "zero") and spec.get("_panel"):
            # how much of this country, inside the frame, lies under the panel's scrim
            xs = [proj(*pt)[0] for poly in _polys_of(g) for pt in poly[0]]
            ys = [proj(*pt)[1] for poly in _polys_of(g) for pt in poly[0]]
            small = (max(xs) - min(xs)) < 160 or (max(ys) - min(ys)) < 160
            sc = 1 if small else 4
            m8 = Image.new("L", (W // sc, H // sc), 0)
            d8 = ImageDraw.Draw(m8)
            for poly in _polys_of(g):
                ring = [(x / sc, y / sc) for x, y in (proj(*pt) for pt in poly[0])]
                if len(ring) > 2:
                    d8.polygon(ring, fill=255)
            a8 = np.asarray(m8) > 0
            x0, y0, x1, y1 = (int(round(c * n / sc)) for c, n in zip(clip, (W, H, W, H)))
            a8 = a8[y0:y1, x0:x1]
            tot = int(a8.sum())
            if tot:
                cut = max(0, int(round(PANEL["wash_from"] * W / sc)) - x0)
                full = max(0, int(round(PANEL["wash_full"] * W / sc)) - x0)
                k = under.setdefault((iso or props.get("ADM0_A3"), state), [0, 0, 0])
                k[0] += int(a8[:, cut:].sum())
                k[1] += tot
                k[2] += int(a8[:, full:].sum())
        if state not in masks:
            masks[state] = (cv.mask(), cv.mask())
        (fm, fmd), (om, omd) = masks[state]
        for poly in _polys_of(g):
            rings = [[(x * SS, y * SS) for x, y in (proj(*p) for p in ring)] for ring in poly]
            if len(rings[0]) > 2:
                fmd.polygon(rings[0], fill=255)
            for hole in rings[1:]:
                if len(hole) > 2:
                    fmd.polygon(hole, fill=0)
            if POLY[state][2]:
                for r in rings:
                    _line_on(omd, r, 255, POLY[state][3])
    for state in DATA_STATES:
        if state not in masks:
            continue
        (fm, _), (om, _) = masks[state]
        role, a, orole, _, hatch = POLY[state]
        cv.composite(fm, role, a)
        if hatch is not None:
            cv.composite(ImageChops.multiply(fm, _hatch(cv.img.size, hatch)), *_hatch_role(state), stroke=True)
        if orole:
            cv.composite(om, orole, 0.9, stroke=True)
    for (iso, state), (u, tot, past) in sorted(under.items()):
        what = "lit" if state == "cases" else "drawn as zero"
        if past or (tot and u / tot > 0.25):
            raise MapRefused(f"{sid}: {iso} is {what} in {st['year']} but {u / tot:.0%} of it lies under the panel's "
                             f"scrim ({past} px past its full wash); move the extent, or draw the map in a framed "
                             "view that stops before the panel")
    lit_in_view = sorted(in_view["cases"])
    exp = data.get("expect_lit")
    if exp is not None and sorted(exp) != lit_in_view:
        why = []
        for iso in sorted(set(exp) - set(lit_in_view)):
            got = "has no row" if iso not in st["values"] else f"reports {st['values'][iso]}"
            why.append(f"{iso} {got} in {st['year']}" + (f" (line {st['lines'][iso]})" if iso in st["lines"] else ""))
        for iso in sorted(set(lit_in_view) - set(exp)):
            why.append(f"{iso} reports {st['values'][iso]} in {st['year']} (line {st['lines'][iso]}) and is lit")
        raise MapRefused(f"{spec.get('id', '')}: the spec expects {sorted(exp)} lit in {st['year']}; the data lights "
                         f"{lit_in_view}: {'; '.join(why)}")
    record.update({"year": st["year"], "csv": st["csv"], "sha256": st["sha256"],
                   "doubts_sha256": data["doubts_sha256"], "column": st["column"],
                   "lit_in_view": lit_in_view, "zero_in_view": sorted(in_view["zero"]),
                   "nodata_in_view": sorted(in_view["nodata"]), "territories_in_view": sorted(terr_in_view),
                   "cells": {iso: {"line": st["lines"][iso], "value": st["values"][iso]}
                             for iso in sorted(set(lit_in_view) | set(in_view["zero"])) if iso in st["lines"]}})
    record["_values"], record["_lines"], record["_countries_file"] = st["values"], st["lines"], st["countries_file"]


def _data_figures(spec: dict, record: dict) -> list:
    """Figures the data layer prints beside a country (at Natural Earth's label point unless
    the spec moves it). Every number comes from the cited CSV; a figure the table does not
    hold is refused, never written as zero."""
    data = spec["data"]
    places = []
    for fg in data.get("figures") or []:
        iso = fg["code"]
        v = record["_values"].get(iso)
        if v is None:
            raise MapRefused(f"{spec.get('id', '')}: a figure for {iso} in {record['year']}: the table has none")
        feats = [p for p, _, _ in _load(record["_countries_file"]) if ne_code(p) == iso]
        if not feats:
            raise MapRefused(f"{spec.get('id', '')}: no Natural Earth country {iso} to place its figure")
        p = feats[0]
        lon, lat = fg.get("lon", p.get("LABEL_X")), fg.get("lat", p.get("LABEL_Y"))
        places.append({"name": fg.get("label") or p.get("NAME"), "lon": lon, "lat": lat, "style": "hidden",
                       "anchor": fg.get("anchor", "e"), "big": True, "sub": f"{v:,}",
                       "sub_size": SIZES["figure_sub"]})
        record.setdefault("figures", []).append({"code": iso, "value": v, "line": record["_lines"].get(iso)})
    return places


def panel_data_figures(spec: dict, data_root) -> list:
    """Panel lines from cited cells: each `panel_figures` entry is a template with {n} and an
    entity; the value is that entity's cell for the data year."""
    data = spec.get("data") or {}
    out = []
    for pf in data.get("panel_figures") or []:
        text = pf["text"]
        if "{n}" not in text or re.search(r"\d", text.replace("{n}", "").replace(str(data["year"]), "")):
            raise MapRefused(f"{spec.get('id', '')}: a panel figure is a template with {{n}} and no other number "
                             f"but the data year: {text!r}")
        cite = {k: data[k] for k in ("csv", "sha256", "doubts_sha256", "licence", "source")}
        cite.update(column=data["columns"]["value"],
                    row={data["columns"]["entity"]: pf["entity"], data["columns"]["year"]: str(data["year"])})
        try:
            got = csv_cell(cite, data_root, check_doubts(spec, data_root))
        except MapRefused as e:
            raise MapRefused(f"{spec.get('id', '')}: the panel figure for {pf['entity']}: {e}") from None
        out.append(text.replace("{n}", f"{got['value']:,}"))
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

    def box(self, frame) -> tuple[float, float, float, float]:
        """The lon/lat box a fraction-of-frame rectangle shows."""
        Wp, Hp = self.size
        x0, y0, x1, y1 = frame[0] * Wp, frame[1] * Hp, frame[2] * Wp, frame[3] * Hp
        return (self.clon + (x0 - self.cx) / (self.k * self.s), self.clat - (y1 - self.cy) / self.s,
                self.clon + (x1 - self.cx) / (self.k * self.s), self.clat - (y0 - self.cy) / self.s)

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


def _draw_layers(cv: Canvas, spec: dict, proj: Projection, geodata: Path, used: dict,
                 data_root=None, record: dict | None = None) -> None:
    """The layers in order; a view's data layer (E8) is filled after its polygon layers and
    before its first line layer, so borders and coasts lie over the data."""
    view = proj.view()
    unp = unplaced_list(spec)
    pending = "data" in spec
    record = record if record is not None else {}
    for ly in spec.get("layers", []):
        if pending and ly.get("style") in LINE:
            _draw_data(cv, spec, proj, geodata, data_root, used, record)
            pending = False
        path = geodata / ly["file"]
        if not path.exists():
            raise MapRefused(f"{spec['id']}: geodata {ly['file']} not found under {geodata}")
        used[ly["file"]] = file_sha256(str(path))
        style = ly["style"]
        clip = ly.get("clip")
        n = 0
        omask = lmask = fmask = hmask = None
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
            if _refused_on_unplaced(style):
                why = unplaced_feature(props, unp)
                if why:
                    raise MapRefused(f"{spec['id']}: layer {ly['file']} ({style}) matched a feature on "
                                     f"{sorted({props.get('ADM0_A3_L'), props.get('ADM0_A3_R')})}: {why}")
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
                    if style in HALOED:
                        hmask, hmd = cv.mask()
                for line in _merge_touching(_lines_of(g)):
                    if ly.get("span"):
                        line = span_line(line, ly["span"])
                        if line is None:
                            continue
                    parts = clip_line(line, clip) if clip else [line]
                    for part in parts:
                        pts = [proj(*p) for p in part]
                        _line_on(lmd, [(x * SS, y * SS) for x, y in pts], 255, px, dash)
                        if style in HALOED:
                            _line_on(hmd, [(x * SS, y * SS) for x, y in pts], 255, px + HALO_PX, None)
        if fmask is not None:
            cv.composite(fmask, POLY[style][0], POLY[style][1])
            if POLY[style][4] is not None:
                cv.composite(ImageChops.multiply(fmask, _hatch(cv.img.size, POLY[style][4])), *_hatch_role(style),
                             stroke=True)
        if omask is not None:
            cv.composite(omask, POLY[style][2], 0.9, stroke=True)
        if hmask is not None:
            cv.composite(hmask, "halo", 1.0, stroke=True)
        if lmask is not None:
            cv.composite(lmask, LINE[style][0], LINE[style][1], stroke=True)
        if n == 0:
            raise MapRefused(f"{spec['id']}: layer {ly['file']} {ly.get('where') or ''} matched nothing in view")
    if pending:
        _draw_data(cv, spec, proj, geodata, data_root, used, record)


def _hatch_role(style: str) -> tuple[str, float]:
    return HATCH_ROLE.get(style, (HATCH["role"], HATCH["alpha"]))


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
            lines.append((p["sub"], "structure", p.get("sub_size", SIZES["point_sub"]),
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
            cv.composite(ImageChops.multiply(m, _hatch(cv.img.size, hatch)), *_hatch_role(style))
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


# The boundary file every hand-drawn path is checked against, beside the spec's own layer files.
BOUNDARY_FILE = "naturalearth/ne_10m_admin_0_boundary_lines_land.geojson"
PATH_UNPLACED_TOL = 0.05      # degrees: a path sample this close to an unplaced feature lies on it
PATH_UNPLACED_SHARE = 0.5     # a path with at least this share of its length on an unplaced feature runs along it
PATH_SAMPLE_DEG = 0.02


def _seg_dist(p, a, b) -> float:
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def _samples(points: list) -> list:
    out = []
    for a, b in zip(points, points[1:]):
        n = max(1, int(math.ceil(math.hypot(b[0] - a[0], b[1] - a[1]) / PATH_SAMPLE_DEG)))
        out += [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(n)]
    return out + [tuple(points[-1])]


def path_on_unplaced(points: list, feats, unplaced=None) -> str | None:
    """Why a hand-drawn path may not be drawn in its style: at least PATH_UNPLACED_SHARE of it
    lies within PATH_UNPLACED_TOL of a feature whose ADM0_A3_L/R pair is unplaced. A path that
    only crosses the line (a route over the border) is not on it."""
    pts = _samples(points)
    bb = _bbox(points)
    pad = PATH_UNPLACED_TOL
    near_any = None
    for props, g, fbb in feats:
        why = unplaced_feature(props, unplaced)
        if not why or not _overlaps((bb[0] - pad, bb[1] - pad, bb[2] + pad, bb[3] + pad), fbb):
            continue
        segs = [(a, b) for line in _lines_of(g) for a, b in zip(line, line[1:])]
        on = sum(1 for q in pts if any(_seg_dist(q, a, b) <= pad for a, b in segs))
        if on >= 2 and on / len(pts) >= PATH_UNPLACED_SHARE:
            near_any = why
            break
    return near_any


def _check_paths(view: dict, spec_id: str, geodata: Path) -> None:
    files = {ly["file"] for ly in view.get("layers", [])} | {BOUNDARY_FILE}
    feats = [f for name in sorted(files) if (geodata / name).exists() for f in _load(str(geodata / name))]
    for pth in view.get("paths", []):
        if pth.get("style") in ON_UNPLACED_OK:
            continue
        why = path_on_unplaced(pth["points"], feats, unplaced_list(view))
        if why:
            raise MapRefused(f"{spec_id}: a hand-drawn {pth['style']!r} path runs along {why}")


def _draw_view(cv: Canvas, view: dict, proj: Projection, geodata: Path, used: dict,
               data_root=None, records: list | None = None, legend: list | None = None) -> None:
    record: dict = {}
    _draw_layers(cv, view, proj, geodata, used, data_root, record)
    _check_paths(view, view.get("id") or "", geodata)
    _draw_paths(cv, view, proj)
    _draw_labels(cv, view, proj)
    if "data" not in view:
        _draw_places(cv, view, proj)
        return
    drawn = {s for s, k in (("cases", "lit_in_view"), ("zero", "zero_in_view"), ("nodata", "nodata_in_view"))
             if record.get(k)}
    styles = {e.get("style") for e in (legend if legend is not None else view.get("legend", []))}
    missing = sorted(drawn - styles)
    if missing:
        raise MapRefused(f"{view.get('id') or ''}: the frame draws {missing} with no legend entry; a reader must "
                         "be able to tell no figure from zero")
    _draw_places(cv, {**view, "places": list(view.get("places", [])) + _data_figures(view, record)}, proj)
    if records is not None:
        records.append({k: v for k, v in record.items() if not k.startswith("_")})


KEEPOUT_PAD = 14  # px at 1080p around the source line


def _source_keepout(cv: Canvas, src: str, at: dict = SOURCE_LINE) -> list:
    """The 2x rectangle around the source line that no map stroke may cross."""
    f = cv.font("structure", SIZES["source"])
    asc, _ = f.getmetrics()
    x = at["x"] * W * SS
    base = at["baseline"] * H * SS
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
               tokens: Path | str = TOKENS, data_root: Path | str | None = None) -> tuple[Image.Image, dict]:
    """Render one spec. Returns the 1920x1080 RGB frame and what it drew (text
    boxes, geodata files with their sha256, warnings, the source line, and for a
    data layer the year, the CSV's sha256 and the cells each country was drawn from).
    A `count_card` spec is drawn by studio/engine/counts.py."""
    if spec.get("kind") == "count_card":
        from . import counts
        return counts.render_card(spec, data_root, fonts=fonts, tokens=tokens)
    check_spec(spec)
    records: list[dict] = []
    if spec.get("data"):
        spec = {**spec, "figures": list(spec.get("figures", [])) + panel_data_figures(spec, data_root)}
    fonts = fonts or M.Fonts()
    pal = palette(tokens)
    cv = Canvas(pal, fonts)
    show_title = spec.get("show_title", True)
    panel = bool((show_title and spec.get("title")) or spec.get("legend") or spec.get("notes") or spec.get("figures"))
    frame = tuple(spec.get("frame") or (DEFAULT_FRAME if panel else FULL_FRAME))
    used: dict[str, str] = {}
    src = source_line(spec)
    at = source_at(spec)
    cv.keepout = _source_keepout(cv, src, at)
    views = spec.get("views")
    if not views:
        proj = Projection(spec["extent"], frame, (W, H))
        _draw_view(cv, {**spec, "_panel": panel}, proj, Path(geodata), used, data_root, records)
    else:
        for v in views:
            vf = tuple(v["frame"])
            sub = Canvas(pal, fonts)
            sub.boxes = cv.boxes
            sub.keepout = cv.keepout
            before = len(cv.boxes)
            vv = {**v, "id": f"{spec['id']}/{v.get('name', '')}", "_panel": panel, "_clip": vf}
            for k in ("unplaced", "conflicts", "zero_suspect"):
                if k in spec and k not in v:
                    vv[k] = spec[k]
            _draw_view(sub, vv, Projection(v["extent"], vf, (W, H)),
                       Path(geodata), used, data_root, records, spec.get("legend", []))
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
    terr_notes = {v["data"].get("territories_note") for v in (views or [spec]) if "data" in v} - {None}
    if terr_notes and not any(r.get("territories_in_view") for r in records):
        # a territory note is printed only when a territory it names takes a figure in view
        spec = {**spec, "notes": [n for n in spec.get("notes", []) if n not in terr_notes]}
    if panel:
        _draw_panel(cv, spec)
    cv.text((at["x"] * W * SS, at["baseline"] * H * SS), src, "structure", SIZES["source"],
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
            "size": [W, H], "data": records}
    return img, info


def pixels_sha256(img: Image.Image) -> str:
    """The sha256 of the raw RGB pixels: stable where PNG bytes vary with the zlib build."""
    return hashlib.sha256(img.convert("RGB").tobytes()).hexdigest()


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


def check_any(spec: dict, data_root=None, geodata=None) -> None:
    """The checks a spec must pass, without drawing. A count card is checked against its
    cited files (it needs the data root). A map's static rules always; with a data root and
    geodata, its data layer too (the CSV's sha256, the ISO3 matching, the year's rows)."""
    if spec.get("kind") == "count_card":
        from . import counts
        counts.check_card(spec, data_root)
        return
    check_spec(spec)
    if data_root is not None and geodata is not None:
        for v in spec.get("views") or [spec]:
            if "data" in v:
                data_state(spec["id"], v["data"], data_root, Path(geodata))
        if spec.get("data"):
            panel_data_figures(spec, data_root)


def doubts_pins(spec) -> list:
    """Every table-doubts sha256 a spec pins (its CSV citations and data blocks)."""
    out = set()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "doubts_sha256" and isinstance(v, str):
                    out.add(v)
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(spec)
    return sorted(out)


def ledger_for(spec: dict, info: dict) -> dict:
    """The ledger fields of a rendered spec: a map's from its spec, a count card's with the
    citations its render resolved."""
    if spec.get("kind") == "count_card":
        from . import counts
        return counts.ledger_fields(spec, info.get("cites"))
    out = ledger_fields(spec)
    if info.get("data"):
        out["method"] = {**out["method"], "data_drawn": info["data"]}
    return out


def check_specs(folder: Path | str, data_root=None, geodata=None) -> list[str]:
    """Every rule check_spec enforces, over every *.json spec in a folder, without rendering:
    one line per violation (an empty list is a pass). Count cards are checked against their
    cited files when a data root is given, and refused without one."""
    problems = []
    files = sorted(f for f in Path(folder).glob("*.json") if not f.name.startswith("_"))
    if not files:
        return [f"{folder}: no specs found"]
    for f in files:
        try:
            check_any(json.loads(f.read_text(encoding="utf-8")), data_root, geodata)
        except MapRefused as e:
            problems.append(f"{f.name}: {e}")
        except Exception as e:  # a malformed spec is a violation to report, never a crash
            problems.append(f"{f.name}: {type(e).__name__}: {e}")
    return problems


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["check-specs"]:
        cp = argparse.ArgumentParser(prog="python -m studio.engine.maps check-specs")
        cp.add_argument("folder")
        cp.add_argument("--data", help="root the specs' cited CSV and text paths are relative to")
        cp.add_argument("--geodata", help="with --data, also check each map's data layer against Natural Earth")
        try:
            ca = cp.parse_args(argv[1:])
        except SystemExit:
            return 2
        problems = check_specs(ca.folder, ca.data, ca.geodata)
        for line in problems:
            print("VIOLATION", line)
        print(f"check-specs: {len(problems)} violation(s)")
        return 1 if problems else 0
    ap = argparse.ArgumentParser(description="Render map specs to 1920x1080 DRAWN frames.")
    ap.add_argument("specs", nargs="+")
    ap.add_argument("--geodata", required=True)
    ap.add_argument("--data", help="root the specs' cited CSV and text paths are relative to (E8)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--sheet")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    written, report, failed = [], [], 0
    for sp in a.specs:
        spec = json.loads(Path(sp).read_text(encoding="utf-8"))
        try:
            img, info = render_map(spec, a.geodata, data_root=a.data)
        except MapRefused as e:
            print(f"REFUSED {sp}: {e}")
            failed += 1
            continue
        data = png_bytes(img)
        dst = out / f"{spec['id']}.png"
        dst.write_bytes(data)
        written.append(dst)
        report.append({"id": spec["id"], "kind": spec.get("kind", "map"), "file": str(dst),
                       "sha256": hashlib.sha256(data).hexdigest(), "pixels_sha256": pixels_sha256(img),
                       "doubts_sha256": doubts_pins(spec),
                       "geodata": info["geodata"],
                       "warnings": info["warnings"], "ledger": ledger_for(spec, info)})
        print(f"{spec['id']}: {dst} sha256 {report[-1]['sha256'][:16]}"
              + (f"  warnings: {'; '.join(info['warnings'])}" if info["warnings"] else ""))
    (out / "maps-render.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    if a.sheet:
        contact_sheet(written, Path(a.sheet))
        print("sheet:", a.sheet)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
