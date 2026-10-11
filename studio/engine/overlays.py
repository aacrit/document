"""void document: marks drawn over a georeferenced archive sheet (R5b).

Grammar: films/GRAMMAR.md A32 (an ARCHIVE frame may carry DRAWN marks when
its sheet is georeferenced and each mark is cited and no more precise than
its source; the label names it; no fill hides the paper; the credits list
every mark). Look and motion: design/brand-kit/BRAND-KIT.md section 13.

A shot of a period map sheet (``archive_still``, mark ARCHIVE or
RECONSTRUCTED) may carry ``marks[]``, and may move its camera between
geographic extents with the ``FIND`` preset. Every mark:

    {"id": "K1", "kind": "line" | "halo" | "outline",
     "name": "the award line, schedule items 1 and 2",    # a halo: the place as the sheet prints it
     "spelling": "sheet" | "record",                       # a halo's name: the sheet's spelling or the record's
     "geometry": {"sheet_px": [[x, y], ...]} | {"lonlat": [[lon, lat], ...]},   # a halo: one point
     "traced": {"on": "<this sheet's ledger id>", "what": "...", "error_px": 3},   # read off the sheet itself
     "geometry_year": 2020,                                # a lonlat geometry: the dataset's vintage
     "source": {"id": "src-...:item1, item2", "licence": "...", "used_for": "...", "year": 1947,
                "precision_m": 0, "runs": {"ends": [[lon, lat], ...], "tol_m": 1500}},
     "feature_year": 1947,                                 # the year of what the mark claims
     "precision_m": 400,                                   # the precision the mark claims, in metres
     "style": {"opacity": 0.55},
     "enter": {"preset": "trace", "at_s": 3.0, "order": 0},
     "exit": {"ease": "let_go", "at_s": 9.0}}

Arrivals are the house springs (``motion.PRESETS``, named, never an inline
easing); departures are ``let_go``. A line is drawn on along its length on
``trace``; a halo surfaces on ``whisper`` and settles in scale on ``settle``;
an outline fades in on ``settle``. Nothing else moves.

Truth: a mark is never more precise than its source. Its claimed precision
covers the georef's error, the sheet's own drawing and the tracing, and the
mark is drawn at least that wide at the shot's closest zoom. A line runs only
where its cited source says it runs. A sheet without a georef is shown plain.

Pure functions of their inputs, so the same frame renders the same pixels.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from . import georef as GR
from . import motion as M

GRAMMAR = "A32"
MARKS_DRAWN = "marks drawn"
KINDS = ("line", "halo", "outline")
BASE_CLASSES = ("ARCHIVE", "RECONSTRUCTED")
FIND = "FIND"
SS = 2                               # marks are drawn at 2x and reduced, so a 1.4 px line is smooth
# A32 refined (CoS 2026-10-11): on a georeferenced archive sheet, FIND's push may go as deep as the
# scan's own resolution (no output pixel samples more than one source pixel), computed per sheet and
# per delivery resolution by scan_zmax(); this replaces the flat 1.3 still cap for FIND only. Other
# presets (HOLD, PUSH, PULL, DRIFT, TILT, DETAIL) keep their existing caps in render.PRESET_ZMAX.
HALO_LABEL_CLEAR_PX = 60             # A32 refined: sheet px a halo ring keeps from the printed place
                                      # name by default, when the name's own box is not known (configurable)
HALO_MIN_RADIUS_PX = 8               # a ring never shrinks to invisible while clearing a label

# BRAND-KIT 13. Sizes are % of frame height, so 720p and 1080p draw the same picture.
# Every mark is drawn as the provenance label is: --mark-text over a soft black contact band, so it holds on a
# paper sheet and on a dark print alike. A halo is a ring around the place, never a disc over it: the kit's first
# design (bone at 0.18, a soft disc) moved a paper sheet's pixels by under 2% and could not be seen (R5b frames).
STYLE = {
    "line": dict(opacity=0.55, width=0.19, band=0.30, band_alpha=0.30),
    "outline": dict(opacity=0.40, width=0.14, band=0.30, band_alpha=0.24),
    "halo": dict(opacity=0.50, radius=2.4, width=0.19, band=0.30, band_alpha=0.30, scale_from=1.06),
}
OPACITY = {"line": (0.40, 0.60), "outline": (0.30, 0.50), "halo": (0.30, 0.55)}
FILL_MAX = 0.10                      # no fill may hide the paper
BAND_MAX = 1.20                      # % of H: a line whose honest width is wider than this is not drawn at this zoom
STYLE_KEYS = {"line": {"opacity", "band"}, "outline": {"opacity", "band", "fill"}, "halo": {"opacity"}}
ENTER_PRESETS = {"line": ("trace",), "outline": ("settle", "whisper"), "halo": ("whisper", "settle")}
ENTER_KEYS = {"preset", "at_s", "order"}
EXIT_KEYS = {"ease", "at_s"}
EXIT_S = M.LT["exit"]                # 0.6 s, the lower third's departure
SPELLINGS = ("sheet", "record")


def preset(name: str) -> M.Spring:
    """The named house spring. Only names in ``motion.PRESETS`` exist."""
    for s in M.PRESETS:
        if s.name == name:
            return s
    raise KeyError(f"no motion preset named {name!r}; one of {[s.name for s in M.PRESETS]}")


def preset_names() -> tuple[str, ...]:
    return tuple(s.name for s in M.PRESETS)


# --------------------------------------------------------------------------
# The sheet
# --------------------------------------------------------------------------


def sheet_fit(item: dict | None):
    """(fit, problems): the item's georef fitted, or None with the reasons."""
    g = (item or {}).get("georef")
    probs = GR.problems(g)
    if probs:
        return None, probs
    return GR.fit(g), []


def _year(v) -> int | None:
    try:
        return int(str(v)[:4])
    except (TypeError, ValueError):
        return None


def sheet_year(item: dict | None) -> int | None:
    it = item or {}
    return _year(it.get("year")) or _year(it.get("date"))


def label_year(item: dict | None) -> str | None:
    """The label's year for a sheet with marks: ``1959 map``."""
    y = sheet_year(item)
    return f"{y} map" if y else "map"


def has_overlay(shot: dict) -> bool:
    return bool(shot.get("marks")) or str(shot.get("preset", "")).upper() == FIND


# --------------------------------------------------------------------------
# Camera: FIND between geographic extents, on the rostrum curve
# --------------------------------------------------------------------------


def _extent_rect(fit, ext, s: float, ox: float, oy: float) -> tuple[float, float, float, float]:
    lon0, lat0, lon1, lat1 = (float(v) for v in ext)
    xs, ys = [], []
    for u in (0.0, 0.5, 1.0):
        for v in (0.0, 0.5, 1.0):
            x, y = fit.to_px(lon0 + (lon1 - lon0) * u, lat0 + (lat1 - lat0) * v)
            xs.append(ox + x * s)
            ys.append(oy + y * s)
    return min(xs), min(ys), max(xs), max(ys)


def extent_framing(fit, ext, size, W: int, H: int, *, fill: bool) -> dict:
    """The framing {"z", "x", "y"} (frame space, z = 1 the whole sheet at
    native aspect) that holds a geographic extent [lon0, lat0, lon1, lat1]."""
    iw, ih = size
    s = min(W / iw, H / ih)
    fw, fh = iw * s, ih * s
    ox, oy = (W - fw) / 2.0, (H - fh) / 2.0
    x0, y0, x1, y1 = _extent_rect(fit, ext, s, ox, oy)
    rw, rh = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    z = min(W / rw, H / rh) if fill else min(fw / rw, fh / rh)
    return {"z": max(1.0, z), "x": (x0 + x1) / 2.0 / W, "y": (y0 + y1) / 2.0 / H}


def scan_zmax(size, W: int, H: int) -> float:
    """A32 refined (CoS 2026-10-11): the deepest zoom (frame space, z = 1 is
    the whole sheet at native aspect) a georeferenced sheet's own scan
    supports at this delivery frame, so no output pixel ever samples less
    than one source pixel (no enlargement past the scan). Computed from the
    scan's own pixel size against the output frame, so it differs at 720p
    and 1080p. Never under 1.0 (a sheet already too small for the frame is
    held whole)."""
    iw, ih = size
    fit_scale = min(W / iw, H / ih)
    return max(1.0, 1.0 / fit_scale)


def find_camera(shot: dict, size, W: int, H: int, *, open_s: float) -> dict:
    """The still camera of a FIND: whole sheet (A7), then through the ``via``
    extents to the ``to`` extent on the rostrum curve. The same dict
    ``render.still_camera`` returns, so the renderer moves it as any still.

    A32 refined (CoS 2026-10-11): each requested framing is clamped to
    ``scan_zmax`` (the scan's own resolution at this delivery frame), so a
    push never enlarges past the scan; ``requested_z_max`` keeps the
    unclamped request, so ``lints`` can refuse one tighter than the scan
    supports (overlay-zoom) rather than deliver it softened."""
    item = shot.get("_item") or {}
    fit, _ = sheet_fit(item)
    iw, ih = size
    s = min(W / iw, H / ih)
    fw, fh = iw * s, ih * s
    fill = shot.get("fill_ok") is True
    base = max(W / fw, H / fh) if fill else 1.0
    find = shot.get("find") or {}
    whole = {"z": 1.0, "x": 0.5, "y": 0.5}
    zmax = scan_zmax(size, W, H)

    def raw_framing(k):
        if fit is None:                  # no georef: the sheet is held whole, and overlay-georef refuses the shot
            return dict(whole)
        if k in (None, "whole") or (isinstance(k, dict) and k.get("whole")):
            return dict(whole)
        return extent_framing(fit, k["extent"], size, W, H, fill=fill)

    raw_path = [whole] + [raw_framing(v) for v in (find.get("via") or [])] + [raw_framing(find.get("to"))]
    requested_z_max = max(p["z"] for p in raw_path)
    path = [dict(p, z=min(p["z"], zmax)) for p in raw_path]
    out = [path[0]]
    for p in path[1:]:
        if any(abs(p[k] - out[-1][k]) > 1e-9 for k in ("z", "x", "y")):
            out.append(p)
    dur = float(shot["_dur"])
    z_max = max(p["z"] for p in out)
    return {"path": out, "clamp": "image" if fill else "native", "fill_ok": fill, "preset": FIND,
            "open_s": min(open_s, 0.4 * dur), "z_max": z_max, "fit_scale": s,
            "z_rel_max": max(1.0, z_max / base), "scan_zmax": zmax, "requested_z_max": requested_z_max}


def framing_at(cam: dict, t: float, dur: float) -> dict:
    """The still's framing at local time t: the opening framing, then the
    rostrum move through the path (the renderer's own rule for every still)."""
    p = cam["path"]
    if len(p) == 1 or t < cam["open_s"]:
        return dict(p[0])
    return M.rostrum_framing(t - cam["open_s"], dur - cam["open_s"], p[0], p[-1], via=p[1:-1])


# --------------------------------------------------------------------------
# Lints (A32). Each runs on every shot that carries marks or a FIND.
# --------------------------------------------------------------------------


def _points(mark: dict) -> list:
    g = mark.get("geometry") or {}
    pts = g.get("sheet_px") if "sheet_px" in g else g.get("lonlat")
    if pts is None:
        return []
    if pts and isinstance(pts[0], (int, float)):
        return [list(pts)]
    return [list(p) for p in pts]


def sheet_points(mark: dict, fit) -> list[list[float]]:
    g = mark.get("geometry") or {}
    pts = _points(mark)
    if "sheet_px" in g:
        return [[float(x), float(y)] for x, y in pts]
    return [list(fit.to_px(float(lon), float(lat))) for lon, lat in pts]


def lonlat_points(mark: dict, fit) -> list[list[float]]:
    g = mark.get("geometry") or {}
    pts = _points(mark)
    if "lonlat" in g:
        return [[float(a), float(b)] for a, b in pts]
    return [list(fit.to_lonlat(float(x), float(y))) for x, y in pts]


def _metres(a, b) -> float:
    """Great-circle distance in metres between two lon, lat points (mean sphere)."""
    lon1, lat1, lon2, lat2 = (math.radians(v) for v in (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * GR.EARTH_R * math.asin(min(1.0, math.sqrt(h)))


def _to_neatline_m(p, nl) -> float:
    """Metres from a lon, lat point to the nearest edge of the neatline box."""
    lon, lat = p
    lon0, lat0, lon1, lat1 = nl
    cands = [(lon0, min(max(lat, lat0), lat1)), (lon1, min(max(lat, lat0), lat1)),
             (min(max(lon, lon0), lon1), lat0), (min(max(lon, lon0), lon1), lat1)]
    return min(_metres(p, c) for c in cands)


def needed_precision_m(mark: dict, fit, georef: dict) -> dict:
    """What a mark's claimed precision must cover, in metres: the georef's
    worst control-point residual, the sheet's own drawing (when the geometry
    is read off the sheet), the tracing, and the source's own precision."""
    mpp = fit.m_per_px
    parts = {"georef_m": fit.max_px * mpp}
    traced = mark.get("traced") or {}
    if "sheet_px" in (mark.get("geometry") or {}) or traced:
        parts["sheet_drawn_m"] = float(georef.get("drawn_precision_m") or 0.0)
        parts["trace_m"] = float(traced.get("error_px") or 0.0) * mpp
    src_p = (mark.get("source") or {}).get("precision_m")
    parts["source_m"] = float(src_p) if isinstance(src_p, (int, float)) else 0.0
    parts["total_m"] = sum(parts.values())
    return parts


def frame_m_per_px(fit, cam: dict, H: int) -> float:
    """Metres a frame pixel covers at the shot's closest framing."""
    return fit.m_per_px / (cam["fit_scale"] * cam["z_max"])


def drawn_radius_pct(mark: dict, band_pct: float | None = None) -> float:
    """The mark's drawn half-width, % of H: a line's or outline's band, a
    halo's radius. That is the precision the picture shows."""
    k = mark.get("kind")
    if k == "halo":
        return STYLE["halo"]["radius"]
    return float(band_pct if band_pct is not None else STYLE[k]["band"])


def era_to(play: dict | None) -> int | None:
    e = (play or {}).get("era")
    if isinstance(e, dict):
        return _year(e.get("to"))
    return None


def mark_problems(shot: dict, mark: dict, fit, georef: dict, cam: dict | None, W: int, H: int,
                  play: dict | None) -> dict[str, list]:
    """Every A32 rule's problems for one mark (empty lists pass)."""
    out = {r: [] for r in ("overlay-cited", "overlay-presets", "overlay-no-fill", "overlay-precision",
                           "overlay-era", "overlay-names", "overlay-timing")}
    kind = mark.get("kind")
    item = shot.get("_item") or {}
    if kind not in KINDS:
        out["overlay-presets"].append(f"kind {kind!r} is not one of {KINDS}")
        return out
    # cited: every mark names its source as a drawn map does
    src = mark.get("source") or {}
    for k in ("id", "licence", "used_for"):
        if not str(src.get(k) or "").strip():
            out["overlay-cited"].append(f"source.{k} is missing")
    traced = mark.get("traced")
    g = mark.get("geometry") or {}
    if ("sheet_px" in g) == ("lonlat" in g):
        out["overlay-cited"].append("geometry is sheet_px (read off this sheet) or lonlat (cited coordinates), one of them")
    if "sheet_px" in g and not traced:
        out["overlay-cited"].append("a geometry read off the sheet says so: traced {on, what, error_px}")
    if traced and traced.get("on") != shot.get("asset"):
        out["overlay-cited"].append(f"traced on {traced.get('on')!r}, not this shot's sheet {shot.get('asset')!r}")
    if traced and not isinstance(traced.get("error_px"), (int, float)):
        out["overlay-cited"].append("traced.error_px (how far the tracing may stray, in sheet pixels) is missing")
    pts = _points(mark)
    if kind == "halo" and len(pts) != 1:
        out["overlay-cited"].append("a halo has one point")
    if kind in ("line", "outline") and len(pts) < 2:
        out["overlay-cited"].append("a line or outline has at least two points")
    # presets: only named house springs; the departure is let_go; no inline easing or duration
    enter, ex = mark.get("enter") or {}, mark.get("exit") or {}
    names = preset_names()
    if enter.get("preset") not in names:
        out["overlay-presets"].append(f"enter.preset {enter.get('preset')!r} is not a motion preset ({', '.join(names)})")
    elif enter.get("preset") not in ENTER_PRESETS[kind]:
        out["overlay-presets"].append(f"a {kind} enters on {' or '.join(ENTER_PRESETS[kind])}, not {enter.get('preset')!r}")
    if set(enter) - ENTER_KEYS:
        out["overlay-presets"].append(f"enter carries {sorted(set(enter) - ENTER_KEYS)}: the spring sets the timing")
    if ex and ex.get("ease") != "let_go":
        out["overlay-presets"].append(f"exit.ease {ex.get('ease')!r}: a mark is let go (let_go)")
    if set(ex) - EXIT_KEYS:
        out["overlay-presets"].append(f"exit carries {sorted(set(ex) - EXIT_KEYS)}")
    # no fill; opacity inside the kind's band
    style = mark.get("style") or {}
    for k, v in style.items():
        if k not in STYLE_KEYS[kind]:
            out["overlay-no-fill"].append(f"style.{k} is not a {kind}'s style ({sorted(STYLE_KEYS[kind])})")
    if "fill" in style or "fill" in mark:
        f = style.get("fill", mark.get("fill"))
        if not isinstance(f, (int, float)) or f > FILL_MAX:
            out["overlay-no-fill"].append(f"fill {f!r} over {FILL_MAX}: no fill may hide the paper")
    op = style.get("opacity", STYLE[kind]["opacity"])
    lo, hi = OPACITY[kind]
    if not isinstance(op, (int, float)) or not lo <= op <= hi:
        out["overlay-no-fill"].append(f"opacity {op!r}; a {kind} is {lo} to {hi}")
    # timing inside the shot
    dur = float(shot.get("_dur") or 0.0)
    at = enter.get("at_s")
    end = ex.get("at_s", dur)
    if not isinstance(at, (int, float)) or not 0.0 <= at < dur:
        out["overlay-timing"].append(f"enter.at_s {at!r} is not inside the shot (0 to {dur:g} s)")
    elif not isinstance(end, (int, float)) or not at < end <= dur + 1e-9:
        out["overlay-timing"].append(f"exit.at_s {end!r} is not after the arrival and inside the shot")
    # era: nothing the mark claims is dated after the film's era; no younger dataset on a period sheet
    eto = era_to(play)
    fy = _year(mark.get("feature_year"))
    if eto is None:
        out["overlay-era"].append("the screenplay declares no era {from, to}: a mark's date cannot be checked")
    if fy is None:
        out["overlay-era"].append("feature_year (the year of what the mark claims) is missing")
    elif eto is not None and fy > eto:
        out["overlay-era"].append(f"the mark claims a feature of {fy}, after the film's era (to {eto})")
    if "lonlat" in g and kind in ("line", "outline"):
        gy, sy = _year(mark.get("geometry_year")), sheet_year(item)
        if gy is None:
            out["overlay-era"].append("a lonlat line names its dataset's vintage (geometry_year)")
        elif sy is not None and gy > sy:
            out["overlay-era"].append(f"its geometry is from {gy}, younger than the {sy} sheet: refused on a period sheet")
    # names: a halo names the place as the sheet prints it, or as the record spells it
    if kind == "halo":
        if not str(mark.get("name") or "").strip():
            out["overlay-names"].append("a halo names its place")
        if mark.get("spelling") not in SPELLINGS:
            out["overlay-names"].append(f"spelling {mark.get('spelling')!r}: the sheet's printed form or the record's")
        if mark.get("spelling") == "record" and not str(mark.get("name_source") or "").strip():
            out["overlay-names"].append("a record spelling cites the record (name_source)")
    # precision: the claim covers its errors, the picture is as wide as the claim, the line runs where the source runs
    if fit is None:
        return out
    need = needed_precision_m(mark, fit, georef)
    claim = mark.get("precision_m")
    if not isinstance(claim, (int, float)):
        out["overlay-precision"].append(f"precision_m is missing; at least {need['total_m']:.0f} m")
    elif claim + 1e-9 < need["total_m"]:
        out["overlay-precision"].append(f"claims {claim:g} m, finer than its sources allow ({need['total_m']:.0f} m: "
                                        + ", ".join(f"{k} {v:.0f}" for k, v in need.items() if k != "total_m") + ")")
    if cam is not None and isinstance(claim, (int, float)):
        req_px = claim / frame_m_per_px(fit, cam, H)
        req_pct = 100.0 * req_px / H
        band = style.get("band")
        if kind in ("line", "outline") and band not in (None, "auto") and not isinstance(band, (int, float)):
            out["overlay-precision"].append(f"style.band {band!r} is a number (% of height) or auto")
        elif kind in ("line", "outline") and isinstance(band, (int, float)) and band + 1e-9 < req_pct:
            out["overlay-precision"].append(f"band {band:g}% of height is narrower than the claim at the closest zoom "
                                            f"({req_pct:.2f}%): a mark is never drawn finer than its precision")
        if kind in ("line", "outline") and max(req_pct, STYLE[kind]["band"]) > BAND_MAX + 1e-9:
            out["overlay-precision"].append(f"its honest width at the closest zoom is {req_pct:.2f}% of height, over "
                                            f"{BAND_MAX}%: the sheet is too coarse for a line at this zoom")
        if kind == "halo" and STYLE["halo"]["radius"] + 1e-9 < req_pct:
            out["overlay-precision"].append(f"a halo of {STYLE['halo']['radius']}% of height is finer than its claim "
                                            f"({req_pct:.2f}%) at the closest zoom")
    nl = georef.get("neatline")
    ll = lonlat_points(mark, fit)
    if nl:
        tol_m = fit.max_px * fit.m_per_px            # a point on the edge may fall outside by the fit's own error
        off = [p for p in ll if not (nl[0] <= p[0] <= nl[2] and nl[1] <= p[1] <= nl[3]) and _to_neatline_m(p, nl) > tol_m]
        if off:
            out["overlay-precision"].append(f"{len(off)} point(s) lie off the sheet's map face {nl}")
    if kind == "line":
        runs = src.get("runs")
        if not isinstance(runs, dict) or not runs.get("ends"):
            out["overlay-precision"].append("a line is drawn only where its cited source runs: source.runs {ends, tol_m}")
        elif ll:
            tol_m = float(runs.get("tol_m") or 0.0)
            for end_name, p in (("first", ll[0]), ("last", ll[-1])):
                at_end = min(_metres(p, e) for e in runs["ends"]) <= tol_m
                at_edge = bool(nl) and _to_neatline_m(p, nl) <= tol_m
                if not (at_end or at_edge):
                    out["overlay-precision"].append(f"its {end_name} point is neither an end the source names nor the "
                                                    f"sheet's edge (within {tol_m:g} m): the line runs past its source")
            bb = runs.get("bbox")
            if bb:
                out_bb = [p for p in ll if not (bb[0] <= p[0] <= bb[2] and bb[1] <= p[1] <= bb[3])]
                if out_bb:
                    out["overlay-precision"].append(f"{len(out_bb)} point(s) outside where the source runs {bb}")
    return out


def lints(lint, shots: list[dict], W: int, H: int, play: dict | None) -> None:
    """A32's lints over a plan's shots, through build_plan's ``lint``; a shot
    that passes gets ``_overlay``, what the renderer draws."""
    for s in shots:
        if not has_overlay(s):
            continue
        item = s.get("_item") or {}
        georef = item.get("georef") or {}
        fit, probs = sheet_fit(item)
        base_ok = s.get("kind") == "archive_still" and s.get("mark") in BASE_CLASSES
        if not base_ok:
            probs = [f"marks go on an archive_still marked {' or '.join(BASE_CLASSES)} (this is {s.get('kind')}, "
                     f"{s.get('mark')})"] + probs
        lint("overlay-georef", not probs, unit=s["id"], grammar=GRAMMAR, stage="marks",
             evidence={"sheet": s.get("asset"), "problems": probs,
                       "fit": None if fit is None else {"fit": fit.fit, "rmse_px": round(fit.rmse_px, 3),
                                                        "max_px": round(fit.max_px, 3), "m_per_px": round(fit.m_per_px, 2),
                                                        "control_points": len(georef.get("control") or [])}})
        cam = s.get("_cam")
        if cam is not None and cam.get("preset") == FIND and "scan_zmax" in cam:
            # A32 refined (CoS 2026-10-11): the camera already clamps to the scan's own resolution
            # (find_camera), so a request tighter than the scan supports is refused outright here,
            # rather than quietly delivered softer than asked.
            lint("overlay-zoom", cam["requested_z_max"] <= cam["scan_zmax"] + 1e-6, unit=s["id"], grammar=GRAMMAR,
                 stage="marks", evidence={"requested_z": round(cam["requested_z_max"], 4),
                                          "scan_zmax": round(cam["scan_zmax"], 4),
                                          "why": "a requested extent tighter than the scan's own resolution supports"})
        marks = s.get("marks") or []
        ids = [m.get("id") for m in marks]
        if len(set(ids)) != len(ids) or None in ids:
            lint("overlay-cited", False, unit=s["id"], grammar=GRAMMAR, stage="marks",
                 evidence={"why": "every mark has a unique id", "ids": ids})
        resolved = []
        for m in marks:
            probs_m = mark_problems(s, m, fit, georef, cam, W, H, play)
            for rule, p in probs_m.items():
                lint(rule, not p, unit=f"{s['id']}/{m.get('id')}", grammar=GRAMMAR, stage="marks",
                     evidence={"problems": p} if p else {"kind": m.get("kind")})
            if fit is not None and not any(probs_m.values()):
                resolved.append(resolve(s, m, fit, cam, H))
        if marks:
            label = s.get("label") or ""
            lint("overlay-label", MARKS_DRAWN in label, unit=s["id"], grammar=GRAMMAR, stage="marks",
                 evidence={"label": label, "needs": MARKS_DRAWN})
        if fit is not None and not probs and item.get("_path"):
            with Image.open(item["_path"]) as im:
                size = list(im.size)
            s["_overlay"] = {"marks": resolved, "size": size, "m_per_px": round(fit.m_per_px, 3)}


def halo_ring_geometry(mark: dict, point: list[float]) -> tuple[list[float], float]:
    """A halo's ring centre and its safe reach, both in sheet px, kept clear
    of the printed place name: sized (and, if the point sits inside it,
    offset away from) the mark's own ``label_box``
    (``{"sheet_px": [x0, y0, x1, y1]}``) when it is known, else held inside
    a configurable default clearance (``HALO_LABEL_CLEAR_PX``).

    A32 refined (CoS 2026-10-11), a low finding from the R5b proof: the
    ring is drawn at a fixed % of frame height for the whole shot (BRAND-KIT
    13), but a printed name is a fixed size on the *sheet*; as a FIND push
    goes deeper, the name's own frame-pixel size grows while the ring's
    does not, so a ring sized only for a shallow push can end up crossing
    the name once the push (now allowed past 1.3) makes it legible."""
    cx, cy = point
    box = (mark.get("label_box") or {}).get("sheet_px")
    if not box or len(box) != 4:
        return [cx, cy], float(HALO_LABEL_CLEAR_PX)
    x0, y0, x1, y1 = (float(v) for v in box)
    dx = max(x0 - cx, 0.0, cx - x1)
    dy = max(y0 - cy, 0.0, cy - y1)
    gap = math.hypot(dx, dy)
    if gap >= HALO_MIN_RADIUS_PX:
        return [cx, cy], gap * 0.9           # a known box is a real boundary: size exactly to clear it
    bx, by = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    vx, vy = cx - bx, cy - by
    d = math.hypot(vx, vy) or 1.0
    push = (HALO_MIN_RADIUS_PX - gap) + HALO_MIN_RADIUS_PX
    return [cx + vx / d * push, cy + vy / d * push], float(HALO_MIN_RADIUS_PX)


def resolve(shot: dict, mark: dict, fit, cam: dict | None, H: int) -> dict:
    """What the renderer needs to draw a mark: sheet-pixel points, the style
    with an honest band, the arrival and the departure."""
    kind = mark["kind"]
    style = dict(STYLE[kind])
    style.update({k: v for k, v in (mark.get("style") or {}).items() if k in ("opacity", "fill")})
    pts = sheet_points(mark, fit)
    if kind in ("line", "outline") and cam is not None:
        req_pct = 100.0 * float(mark["precision_m"]) / frame_m_per_px(fit, cam, H) / H
        band = (mark.get("style") or {}).get("band", "auto")
        style["band"] = max(STYLE[kind]["band"], req_pct) if band in (None, "auto") else float(band)
    elif kind == "halo" and cam is not None:
        centre, safe_px = halo_ring_geometry(mark, pts[0])
        pts = [centre]
        scale = cam["fit_scale"] * cam["z_max"]
        if (mark.get("label_box") or {}).get("sheet_px"):
            # a known label_box is a real boundary: the drawn ring also carries a soft contact
            # band around its bare circle (BRAND-KIT 13), a fixed % of frame height, so keep the
            # whole painted ring, not just its radius, clear of it (generously, past its blur).
            # The unknown-box default clearance is a guess, not a detected edge, so it is spared
            # this extra margin (A32 refined, CoS 2026-10-11).
            margin_sheet_px = (3.0 * style["band"] / 100.0 * H) / scale if scale else 0.0
            safe_px = max(1.0, safe_px - margin_sheet_px)
        safe_pct = 100.0 * safe_px * scale / H
        # A32(e) still binds: a halo is a ring, never a disc, over the place; clearing a very close
        # label never shrinks it below a size that keeps its centre visibly open.
        style["radius"] = max(min(STYLE["halo"]["radius"], safe_pct), STYLE["halo"]["width"] * 1.2)
    enter = mark.get("enter") or {}
    start = float(enter["at_s"]) + int(enter.get("order") or 0) * M.LT["stagger"]
    end = float((mark.get("exit") or {}).get("at_s", shot["_dur"]))
    return {"id": mark["id"], "kind": kind, "pts": [[round(x, 3), round(y, 3)] for x, y in pts],
            "style": style, "preset": enter["preset"], "start": start, "end": end,
            "calm": str(shot.get("motion", "")).lower() == "calm"}


# --------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------


def _cut(pts: list, p: float) -> list:
    """The polyline from its start to fraction p of its length (p clamped to
    0..1, so a spring's overshoot never draws past the cited end)."""
    p = M.clamp01(p)
    if p >= 1.0 or len(pts) < 2:
        return list(pts)
    seg = [math.dist(a, b) for a, b in zip(pts, pts[1:])]
    goal = p * sum(seg)
    out = [pts[0]]
    for (a, b), d in zip(zip(pts, pts[1:]), seg):
        if goal <= d:
            u = goal / d if d > 0 else 0.0
            out.append((a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u))
            return out
        out.append(b)
        goal -= d
    return out


def mark_alpha(m: dict, t: float) -> tuple[float, float, float]:
    """(opacity factor, draw-on progress, scale) of a resolved mark at local t."""
    u = t - m["start"]
    if u < 0 or t >= m["end"]:
        return 0.0, 0.0, 1.0
    leave = M.let_go(t, m["end"], min(EXIT_S, m["end"] - m["start"]))
    if m["calm"]:                               # BRAND-KIT 13: the calm tier, no travel, no scale
        return M.clamp01(M.SETTLE.progress(u)) * leave, 1.0, 1.0
    if m["kind"] == "line":
        return leave, M.clamp01(preset(m["preset"]).progress(u)), 1.0
    if m["kind"] == "halo":
        sf = STYLE["halo"]["scale_from"]
        return M.clamp01(preset(m["preset"]).progress(u)) * leave, 1.0, sf + (1.0 - sf) * M.clamp01(M.SETTLE.progress(u))
    return M.clamp01(preset(m["preset"]).progress(u)) * leave, 1.0, 1.0


def _layer_box(pts, pad: float, W: int, H: int):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0, y0 = max(0, int(math.floor(min(xs) - pad))), max(0, int(math.floor(min(ys) - pad)))
    x1, y1 = min(W, int(math.ceil(max(xs) + pad)) + 1), min(H, int(math.ceil(max(ys) + pad)) + 1)
    return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None


def _stroke_mask(pts, box, width: float, closed: bool) -> Image.Image:
    x0, y0, x1, y1 = box
    big = Image.new("L", ((x1 - x0) * SS, (y1 - y0) * SS), 0)
    d = ImageDraw.Draw(big)
    q = [((x - x0) * SS, (y - y0) * SS) for x, y in pts]
    if closed and len(q) > 2:
        q = q + [q[0]]
    w = max(1, int(round(width * SS)))
    if len(q) >= 2:
        d.line(q, fill=255, width=w, joint="curve")
    r = width * SS / 2.0
    for x, y in ([q[0], q[-1]] if not closed else []):      # round caps
        d.ellipse([x - r, y - r, x + r, y + r], fill=255)
    return big


def _down(big: Image.Image, box) -> Image.Image:
    x0, y0, x1, y1 = box
    return big.resize((x1 - x0, y1 - y0), Image.Resampling.BOX)


def _paint(out: Image.Image, mask: Image.Image, box, rgb, alpha: float) -> None:
    a = np.asarray(mask, dtype=np.float32) * alpha
    tile = Image.new("RGBA", mask.size, tuple(rgb) + (0,))
    tile.putalpha(Image.fromarray(np.clip(np.rint(a), 0, 255).astype(np.uint8)))
    out.alpha_composite(tile, (box[0], box[1]))


def draw(img: Image.Image, shot: dict, t: float, framing: dict, L: M.Layout, shown_size) -> Image.Image:
    """The shot's marks over its picture at local time t. ``framing`` is the
    still's framing at t and ``shown_size`` the size of the image the
    renderer framed (a big sheet is pre-scaled), so the marks sit on the
    sheet's own pixels as the camera moves."""
    ov = shot.get("_overlay") or {}
    if not ov.get("marks"):
        return img
    iw, ih = ov["size"]
    kx, ky = shown_size[0] / iw, shown_size[1] / ih
    src, dst = M.still_view(shown_size, L, z=framing["z"], cx=framing["x"], cy=framing["y"],
                            clamp=shot["_cam"]["clamp"])
    sx = (dst[2] - dst[0]) / (src[2] - src[0])
    sy = (dst[3] - dst[1]) / (src[3] - src[1])

    def to_frame(p):
        return (dst[0] + (p[0] * kx - src[0]) * sx, dst[1] + (p[1] * ky - src[1]) * sy)

    out = img.convert("RGBA")
    for m in ov["marks"]:
        a, prog, scale = mark_alpha(m, t)
        if a <= 0.0:
            continue
        st = m["style"]
        pts = [to_frame(p) for p in m["pts"]]
        if m["kind"] == "halo":                  # a ring around the place, drawn as a closed line
            r = L.h(st["radius"]) * scale
            n = max(24, int(2 * math.pi * r / 2))
            pts = [(pts[0][0] + r * math.cos(2 * math.pi * k / n), pts[0][1] + r * math.sin(2 * math.pi * k / n))
                   for k in range(n)]
        closed = m["kind"] in ("outline", "halo")
        pts = pts if closed else _cut(pts, prog)
        if len(pts) < 2:
            continue
        band = L.h(st["band"])
        box = _layer_box(pts, band * 2 + 3, L.W, L.H)
        if box is None:
            continue
        if closed and st.get("fill"):             # an outline's wash: black, at most FILL_MAX, never hiding the paper
            x0, y0 = box[0], box[1]
            big = Image.new("L", ((box[2] - x0) * SS, (box[3] - y0) * SS), 0)
            ImageDraw.Draw(big).polygon([((x - x0) * SS, (y - y0) * SS) for x, y in pts], fill=255)
            _paint(out, _down(big, box), box, (0, 0, 0), min(float(st["fill"]), FILL_MAX) * a)
        # the contact band: as wide as the mark's claimed precision, dark, soft; then the bone line on it
        halo = _stroke_mask(pts, box, 2 * band, closed).filter(ImageFilter.GaussianBlur(band * SS * 0.6))
        _paint(out, _down(halo, box), box, (0, 0, 0), st["band_alpha"] * a)
        core = _stroke_mask(pts, box, max(1.0, L.h(st["width"])), closed)
        _paint(out, _down(core, box), box, M.PALETTE["mark_text"], st["opacity"] * a)
    return out.convert("RGB")


# --------------------------------------------------------------------------
# Provenance: the credits and sources.json
# --------------------------------------------------------------------------


def credit_lines(shots: list[dict]) -> list[str]:
    """One credit line per mark: the shot, what the mark is and its source."""
    out = []
    for s in shots:
        for m in s.get("marks") or []:
            src = m.get("source") or {}
            how = "traced on the sheet's own printing" if m.get("traced") else "from cited coordinates"
            out.append(f"{s['id']}  {m.get('name') or m.get('kind')}: {src.get('id', '')}, {src.get('licence', '')}; {how}")
    return out


def sources_fields(shot: dict) -> dict:
    """The shot's ``marks`` and ``georef`` for sources.json (the Sources page
    and the credits list every mark with its source)."""
    if not has_overlay(shot):
        return {}
    item = shot.get("_item") or {}
    g = item.get("georef") or {}
    marks = []
    for m in shot.get("marks") or []:
        marks.append({k: m.get(k) for k in ("id", "kind", "name", "spelling", "source", "traced", "feature_year",
                                            "precision_m", "enter", "exit") if m.get(k) is not None})
    return {"marks": marks,
            "georef": {k: g.get(k) for k in ("fit", "projection", "stated", "rmse_px", "max_px", "m_per_px", "neatline",
                                              "drawn_precision_m", "verified_by")} | {"control_points": len(g.get("control") or [])}}
