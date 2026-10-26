"""A41 (TOUR): the still camera as a path of stops, in pure functions.

The founder, 2026-10-17: "move left right, top and down if we need to cover
different aspects of the picture, zoom in where needed, zoom out and move in
space. Make it dynamic, take the user through the artifact as needed, but use
the full resolution of the screen. Same with even the paintings."

Picture coordinates: ``x`` and ``y`` are the window's centre as fractions of
the picture (0 to 1), ``z`` is the zoom relative to the fill window, the
largest window of the frame's aspect inside the picture (z = 1, GRAMMAR 7.2's
own z = 1). ``z`` never goes below 1, so a still fills the frame on every
frame. A window is always clamped inside the picture's own pixels.

A path is a list of stops ``{t, x, y, z}`` (``t`` in shot seconds), or
anchored to the narration with ``at`` (a word index, or a cue the narration
speaks: ``parse_path`` resolves it with ``anchor_time``), or to a ledger region
with ``roi``. Between stops
the camera moves on the rostrum curve (BRAND-KIT 6). A stop held longer than
``motion.TOUR['hold_creep_after_s']`` keeps creeping (scale, or a slow drift)
so no frame is frozen.

The presets (HOLD, PUSH, PULL, DRIFT, TILT, DETAIL, FILL) are macros that
expand to paths (``macro_stops``); a shot with neither gets ``default_stops``.
Nothing here reads a file or keeps state: ``render.still_camera`` calls it and
the guards (``people_check``, ``speed_report``, ...) read what it returns.
"""

from __future__ import annotations

import math
import re

from studio.engine import motion as M

TOUR = M.TOUR
# Cinematography ticket #10 (A54): three more presets, engine-drawn from the ledger rather than a fixed framing
# (``rich_macro_stops``): READ (a document or page, tilted or panned at reading pace), PORTRAIT (a person, face
# first, then the fill) and SURVEY (a painting's several ROIs, then the widest fill). They carry every A41/A43/A47
# guarantee a preset already has (``render.COVERABLE``: never refused, steered, covered), and fall back to the
# A47 subject pass, journaled, when the still has none of what they need.
RICH_MACROS = ("READ", "PORTRAIT", "SURVEY")
MACROS = ("HOLD", "PUSH", "PULL", "DRIFT", "TILT", "DETAIL", "FILL") + RICH_MACROS
# The old presets' framings (GRAMMAR 7.2), now in picture coordinates relative to the fill (A41)
MACRO_ENDS = {
    "HOLD": ({"z": 1.0}, {"z": 1.0}),
    "PUSH": ({"z": 1.0}, {"z": 1.12}),
    "PULL": ({"z": 1.12}, {"z": 1.0}),
    "DRIFT": ({"z": 1.15, "x": 1 / 3}, {"z": 1.15, "x": 2 / 3}),
    "TILT": ({"z": 1.2, "y": 0.0}, {"z": 1.2, "y": 1.0}),
    "DETAIL": ({"z": 1.3}, {"z": 1.3}),
}
EPS = 1e-9
# A strip of the picture the fill hides that is under this share of its side (a scan a few pixels off 16:9) counts as
# shown: a pass over it would barely move, and it would replace the creep (1920x1078 travels 3.6 px in 8 s)
SHOWN_STRIP = 0.005
WHOLE = (0.0, 0.0, 1.0, 1.0)
FRAME_ASPECT = 16 / 9                      # every delivery is 16:9 (render.RESOLUTIONS)
# A54 (entering mid-move, founder 2026-10-18) retired A49's opening settle (MIN_OPEN_HOLD_S): every still leaves
# its cut frame already moving at the creep's speed (``build``, ``motion.enter_moving``)


class TourError(ValueError):
    """A path that cannot be drawn as written (the lint names it)."""


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------


def fill_window(size, aspect: float) -> tuple[float, float]:
    """The largest window of the frame's ``aspect`` inside the picture, in
    picture pixels (7.2's z = 1)."""
    iw, ih = float(size[0]), float(size[1])
    if iw / ih >= aspect:
        return ih * aspect, ih
    return iw, iw / aspect


def window(size, aspect: float, z: float, x: float, y: float) -> tuple[float, float, float, float]:
    """The window (x0, y0, x1, y1) in picture pixels at zoom ``z`` about the
    centre (x, y), clamped inside the picture (``still_view``'s image clamp)."""
    iw, ih = float(size[0]), float(size[1])
    fw, fh = fill_window(size, aspect)
    w, h = fw / max(1.0, z), fh / max(1.0, z)
    cx = min(max(x * iw, w / 2.0), iw - w / 2.0)
    cy = min(max(y * ih, h / 2.0), ih - h / 2.0)
    return cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0


def settle(p: dict, size, aspect: float) -> dict:
    """The stop as the camera can frame it: z at least 1, the centre moved in
    so the window stays inside the picture."""
    z = max(1.0, float(p["z"]))
    x0, y0, x1, y1 = window(size, aspect, z, float(p.get("x", 0.5)), float(p.get("y", 0.5)))
    return dict(p, z=z, x=(x0 + x1) / 2.0 / float(size[0]), y=(y0 + y1) / 2.0 / float(size[1]))


def z_cap(size, W: int, H: int, cap: float) -> float:
    """The deepest picture z the softness cap allows: ``cap`` output pixels per
    source pixel. Under 1 when even the fill would pass it."""
    fw, _ = fill_window(size, W / H)
    return cap * fw / W


def upscale(size, W: int, H: int, z: float) -> float:
    """Output pixels per source pixel at picture zoom z."""
    fw, _ = fill_window(size, W / H)
    return z * W / fw


def to_frame(f: dict, size, W: int, H: int) -> dict:
    """A picture-space framing as ``motion.still_view`` takes it (frame space,
    z = 1 the whole picture fitted, clamp ``image``)."""
    iw, ih = float(size[0]), float(size[1])
    s = min(W / iw, H / ih)
    fw, fh = iw * s, ih * s
    ox, oy = (W - fw) / 2.0, (H - fh) / 2.0
    zf = max(W / fw, H / fh)
    return {"z": zf * f["z"], "x": (ox + f["x"] * fw) / W, "y": (oy + f["y"] * fh) / H}


def project_box(size, window: tuple[float, float, float, float],
                box_frac: tuple[float, float, float, float]) -> tuple[float, float, float, float] | None:
    """A picture-fraction box (``roi_box``) projected through ``window``
    (picture pixels, as this module's own ``window()`` returns it) into
    frame fractions [0, 1], clipped to what is on screen during a TOUR
    (every frame fills the output, so the window maps onto the whole
    frame). None when none of the box is visible at this window.
    Cinematography ticket #4: the single projection ``end_pose``'s steering
    and ``tourlint.subject_under_text`` both read (the contact-sheet tool's
    own, more general ``sheets.project_box`` handles an arbitrary cell
    layout and stays separate)."""
    iw, ih = float(size[0]), float(size[1])
    x0, y0, x1, y1 = window
    ww, wh = x1 - x0, y1 - y0
    if ww <= 0 or wh <= 0:
        return None
    bx0, by0, bx1, by1 = box_frac[0] * iw, box_frac[1] * ih, box_frac[2] * iw, box_frac[3] * ih
    fx0, fy0 = max(0.0, (bx0 - x0) / ww), max(0.0, (by0 - y0) / wh)
    fx1, fy1 = min(1.0, (bx1 - x0) / ww), min(1.0, (by1 - y0) / wh)
    if fx1 <= fx0 or fy1 <= fy0:
        return None
    return fx0, fy0, fx1, fy1


def box_overlap_share(frame_box: tuple[float, float, float, float],
                      zone_box: tuple[float, float, float, float]) -> float:
    """The share of ``frame_box``'s own area that lies inside ``zone_box``
    (both frame fractions). 0 when ``frame_box`` has no area."""
    ax0, ay0, ax1, ay1 = frame_box
    zx0, zy0, zx1, zy1 = zone_box
    iw = max(0.0, min(ax1, zx1) - max(ax0, zx0))
    ih = max(0.0, min(ay1, zy1) - max(ay0, zy0))
    full = (ax1 - ax0) * (ay1 - ay0)
    return (iw * ih) / full if full > 0 else 0.0


# --------------------------------------------------------------------------
# Narration words (the anchors)
# --------------------------------------------------------------------------

_TOKEN = re.compile(r"[^\w']+", re.UNICODE)


def norm_word(w: str) -> str:
    return _TOKEN.sub("", str(w).lower()).strip("'")


def word_times(text: str, start: float, dur: float) -> list[dict]:
    """Each word of a line with the time it is spoken: the line's time shared
    by characters, as the captions share a cue's time (captions._timed). A
    line that carries measured ``words`` [{w, t}] is used as measured."""
    toks = [t for t in str(text or "").split() if t.strip()]
    if not toks:
        return []
    chars = [max(1, len(norm_word(t)) or 1) for t in toks]
    total = float(sum(chars)) + 0.5 * (len(toks) - 1)      # a space counts half a character
    out, acc = [], 0.0
    for i, (tok, c) in enumerate(zip(toks, chars)):
        out.append({"w": tok, "n": norm_word(tok), "i": i, "t": start + dur * acc / total})
        acc += c + 0.5
    return out


def shot_words(lines: list[dict], t0: float, t1: float) -> list[dict]:
    """The words of every voiced line that overlaps the shot [t0, t1), in time
    order, each with its line id and absolute time. ``lines`` are
    {id, kind, start, dur, text[, words]}."""
    out = []
    for ln in sorted(lines, key=lambda v: (v["start"], v["id"])):
        a, b = float(ln["start"]), float(ln["start"]) + float(ln["dur"])
        if b <= t0 or a >= t1:
            continue
        measured = bool(ln.get("words"))
        if measured:
            ws = [{"w": w["w"], "n": norm_word(w["w"]), "i": i, "t": float(w["t"])} for i, w in enumerate(ln["words"])]
        else:
            ws = word_times(ln.get("text", ""), a, float(ln["dur"]))
        for k, w in enumerate(ws):
            # a word ends where the next one starts, the last where the line ends (A43: "holds through the name")
            end = ws[k + 1]["t"] if k + 1 < len(ws) else max(b, w["t"])
            out.append(dict(w, line=ln["id"], kind=ln.get("kind"), e=end, m=measured))
    return out


def anchor_span(at, words: list[dict], *, line: str | None = None, t0: float = 0.0) -> dict | None:
    """The words a stop's ``at`` names: an integer (or a string of digits) is
    a word index in ``line`` (or in the first line heard in the shot), any
    other string a cue (one word or a phrase, "7 World Trade Center" too) the
    narration speaks, the first time the shot hears it. Returns {t (onset),
    end (the end of its last word), measured (every word measured), words}, or
    None when the narration in the shot does not hold it."""
    if not words:
        return None
    if isinstance(at, bool):
        return None
    if isinstance(at, (int, float)) or (isinstance(at, str) and re.fullmatch(r"\d+", at.strip())):
        k = int(at)
        lid = line or words[0]["line"]
        ws = [w for w in words if w["line"] == lid]
        if not 0 <= k < len(ws):
            return None
        hit = [ws[k]]
    else:
        cue = [norm_word(t) for t in str(at).split() if norm_word(t)]
        if not cue:
            return None
        # a cue is the first time it is spoken in the shot (a line that began before the cut may say it earlier)
        ws = [w for w in words if (line is None or w["line"] == line) and w["t"] >= t0 - 0.05]
        hit = None
        for i in range(len(ws) - len(cue) + 1):
            if all(ws[i + j]["n"] == cue[j] for j in range(len(cue))) and all(
                    ws[i + j]["line"] == ws[i]["line"] for j in range(len(cue))):
                hit = ws[i:i + len(cue)]
                break
        if hit is None:
            return None
    return {"t": hit[0]["t"], "end": hit[-1].get("e", hit[-1]["t"]), "measured": all(w.get("m") for w in hit),
            "words": hit}


def anchor_time(at, words: list[dict], *, line: str | None = None, t0: float = 0.0) -> float | None:
    """The absolute time of the word a stop's ``at`` names (``anchor_span``'s
    onset). None when the narration in the shot does not hold it."""
    sp = anchor_span(at, words, line=line, t0=t0)
    return None if sp is None else sp["t"]


def _anchor_fields(sp: dict, t0: float) -> dict:
    """What a stop anchored to the narration carries for the A43 lints: the
    name's onset and end in shot seconds, whether its timing is measured, and
    the words as spoken."""
    return {"onset": sp["t"] - t0, "name_end": sp["end"] - t0, "measured": sp["measured"],
            "spoken": [w["w"] for w in sp["words"]], "spoken_line": sp["words"][0]["line"],
            "spoken_i": [w["i"] for w in sp["words"]]}


# --------------------------------------------------------------------------
# Regions of interest and the stops that visit them
# --------------------------------------------------------------------------


def roi_box(r: dict) -> tuple[float, float, float, float] | None:
    """(x0, y0, x1, y1) in picture fractions from {x, y, w, h} (x, y the top
    left corner), or None when the region is not located."""
    try:
        x, y, w, h = (float(r[k]) for k in ("x", "y", "w", "h"))
    except (KeyError, TypeError, ValueError):
        return None
    return x, y, x + w, y + h


def roi_stop(r: dict, size, aspect: float, zmax: float, margin: float = 1.25) -> dict:
    """The stop that frames a region whole, with a margin around it: centred on
    it, as deep as the region allows and never past ``zmax``."""
    x0, y0, x1, y1 = roi_box(r)
    iw, ih = float(size[0]), float(size[1])
    fw, fh = fill_window(size, aspect)
    rw, rh = max((x1 - x0) * iw * margin, 1.0), max((y1 - y0) * ih * margin, 1.0)
    z = max(1.0, min(fw / rw, fh / rh, max(1.0, zmax)))
    return {"z": z, "x": (x0 + x1) / 2.0, "y": (y0 + y1) / 2.0}


def cue_of(r: dict) -> list[str]:
    """What the narration says when it names a region: its ``cue`` (a string
    or a list), else its ``name``."""
    c = r.get("cue")
    if c is None:
        c = r.get("name")
    return [c] if isinstance(c, str) else [x for x in (c or []) if isinstance(x, str)]


def tour_stops(roi: list[dict], words: list[dict], t0: float, dur: float, size, aspect: float, zmax: float,
               only=None) -> list[dict] | None:
    """The ``tour`` resolver: an opening stop at the fill (centred), then one
    stop on each region at the moment the narration names it (its cue, else
    its name), in the order spoken. ``only`` limits it to those region names.
    None when no region is named in the shot (the caller takes the default
    tour). Times are shot seconds."""
    picks = []
    for r in roi or []:
        if only is not None and r.get("name") not in only:
            continue
        if roi_box(r) is None:
            continue
        for c in cue_of(r):
            sp = anchor_span(c, words, t0=t0)
            if sp is not None and t0 - EPS <= sp["t"] <= t0 + dur + EPS:
                picks.append((sp["t"] - t0, r, c, sp))
                break
    if not picks:
        return None
    picks.sort(key=lambda p: p[0])
    stops = [{"t": 0.0, "z": 1.0, "x": 0.5, "y": 0.5, "from": "tour: the fill", "placed": "engine"}]
    for t, r, c, sp in picks:
        st = roi_stop(r, size, aspect, zmax)
        st.update(t=max(0.0, min(dur, t)), roi=r.get("name"), at=c, placed="engine", **_anchor_fields(sp, t0),
                  **{"from": f"tour: {r.get('name')}"})
        if is_person_region(r):
            # A43: a person is reached before their name (0.5 s on measured words, 1.0 s on estimated ones) and
            # held until the name has been said, so the picture never names the wrong face
            lead = CINE["anchor_lead_s"] if st["measured"] else CINE["anchor_estimated_lead_s"]
            st["t"] = max(0.0, min(dur, t - lead))
            st["hold"] = max(0.0, st["name_end"] - st["t"])
        prev = stops[-1]
        if st["t"] < prev["t"] + prev.get("hold", 0.0) - EPS:
            st["t"] = prev["t"] + prev.get("hold", 0.0) + 0.5   # never cut short the person held before
        elif st["t"] <= prev["t"] + EPS:
            st["t"] = prev["t"] + 0.5          # never two stops at one moment (tour.mjs does the same)
        if st["t"] > dur + EPS:
            continue                           # named too late to reach in this shot (tour.mjs drops it too)
        stops.append(st)
    return stops


# --------------------------------------------------------------------------
# Macros and the default tour
# --------------------------------------------------------------------------


def long_axis(size, aspect: float) -> str | None:
    """Which way the fill window can travel: ``y`` for a picture narrower than
    the frame (a portrait tilts), ``x`` for a wider one (a wide map pans), None
    when the fill shows the whole picture but for a strip under
    ``SHOWN_STRIP`` of its side (counted as shown; the shot creeps)."""
    iw, ih = float(size[0]), float(size[1])
    fw, fh = fill_window(size, aspect)
    if iw - fw > SHOWN_STRIP * iw:
        return "x"
    if ih - fh > SHOWN_STRIP * ih:
        return "y"
    return None


def whole_box(size, aspect: float) -> tuple[float, float, float, float]:
    """The part of the picture that must be shown for it to count as shown
    whole: all of it, less a centred strip under ``SHOWN_STRIP`` the fill
    hides on a picture of the frame's own shape (``long_axis`` None)."""
    if long_axis(size, aspect) is not None:
        return WHOLE
    iw, ih = float(size[0]), float(size[1])
    fw, fh = fill_window(size, aspect)
    mx, my = (iw - fw) / 2.0 / iw, (ih - fh) / 2.0 / ih
    return (mx, my, 1.0 - mx, 1.0 - my)


def default_stops(size, aspect: float, dur: float, direction: str = "", zmax: float | None = None, *,
                  no_zoom: bool = False) -> list[dict]:
    """A41's geometric pass: open at the fill on one end of the long axis
    and make one slow pass to the other over the shot (top to bottom, left to
    right; ``direction`` up or rl reverses it). A picture of the frame's own
    shape holds at the fill, creeping. A47 retired it as the default (the
    default now ends on the subject, ``subject_stops``); it stays for the
    callers that ask for a plain pass. ``no_zoom`` (burning and collapse
    stills, founder ruling): the pass never layers a push; it is a drift."""
    ax = long_axis(size, aspect)
    if ax is None:
        return [{"t": 0.0, "z": 1.0, "x": 0.5, "y": 0.5, "from": "default tour: the fill"}]
    a, b = 0.0, 1.0
    if direction in ("up", "bottom-to-top", "rl", "right-to-left", "left"):
        a, b = b, a
    first = {"t": 0.0, "z": 1.0, "x": 0.5, "y": 0.5, "from": "default tour: open"}
    last = {"t": dur, "z": 1.0, "x": 0.5, "y": 0.5, "from": "default tour: pass"}
    first[ax], last[ax] = a, b
    mid = None if no_zoom else _layer_creep(first, last, size, aspect, dur, ax, zmax)
    return [first, mid, last] if mid else [first, last]


def _layer_creep(first: dict, last: dict, size, aspect: float, dur: float, ax: str, zmax: float | None):
    """A pass slower than the creep (a short travel over a long shot) also
    breathes at the creep's rate, so it never reads as frozen: it pushes in to
    the middle of the shot and back out to the fill at the far end, so both
    ends (and their corners) are still shown at the fill. Never past ``zmax``.
    Returns the middle stop, or None when the pass is fast enough."""
    iw, ih = float(size[0]), float(size[1])
    fw, fh = fill_window(size, aspect)
    travel = (iw - fw) / fw if ax == "x" else (ih - fh) / fh       # in windows
    c = TOUR["creep_scale_per_s"]
    if dur <= EPS or travel / dur >= c:
        return None
    z = 1.0 + c * dur / 2.0
    if zmax is not None:
        z = min(z, zmax)
    if z <= 1.0 + 1e-6:
        return None
    mid = {"t": dur / 2.0, "z": z, "x": 0.5, "y": 0.5, "from": "default tour: pass, creeping"}
    mid[ax] = (first[ax] + last[ax]) / 2.0
    return mid


def covering_stops(size, aspect: float, dur: float, focus=None, zmax: float | None = None, *,
                   no_zoom: bool = False) -> list[dict]:
    """A pass that shows the whole picture: the default tour, and with a
    ``focus`` it starts at the end farther from the focus, passes to the other
    end and comes back to settle on the focus. The shot's time is shared by
    how far each leg travels, so the camera keeps one even speed (the rostrum
    cruise) instead of rushing the settle."""
    ax = long_axis(size, aspect)
    if ax is None or focus is None:
        return default_stops(size, aspect, dur, zmax=zmax, no_zoom=no_zoom)
    fx, fy = float(focus[0]), float(focus[1])
    f = fx if ax == "x" else fy
    a, b = (0.0, 1.0) if f >= 0.5 else (1.0, 0.0)          # from the far end, through the near one
    s0 = {"t": 0.0, "z": 1.0, "x": 0.5, "y": 0.5, "from": "covering pass: open"}
    s1 = {"t": 0.0, "z": 1.0, "x": 0.5, "y": 0.5, "from": "covering pass: the near end"}
    s0[ax], s1[ax] = a, b
    s2 = {"t": dur, "z": 1.0, "x": fx, "y": fy, "from": "covering pass: settle on the focus"}
    p0, p1, p2 = (settle(st, size, aspect)[ax] for st in (s0, s1, s2))
    sweep, back = abs(p1 - p0), abs(p2 - p1)
    if back <= 1e-3 or sweep + back <= 1e-9:
        s1["t"] = dur
        return [s0, s1]
    s1["t"] = dur * sweep / (sweep + back)
    return [s0, s1, s2]


def macro_stops(preset: str, shot: dict, dur: float) -> list[dict]:
    """A preset as a path (A41): its old framings (7.2) as the first and last
    stop, now relative to the fill, so HOLD and FILL fill rather than
    pillarbox. DETAIL sits on ``region``; DRIFT and TILT take ``direction``;
    ``from`` and ``to`` still override; FILL is the fill about its ``focus``."""
    preset = preset.upper()
    if preset == "FILL":
        focus = shot.get("focus") or [0.5, 0.5]
        p = {"z": 1.0, "x": float(focus[0]), "y": float(focus[1])}
        return [dict(p, t=0.0, **{"from": "FILL"}), dict(p, t=dur, **{"from": "FILL"})]
    frm, to = (dict(k) for k in MACRO_ENDS[preset])
    if preset == "DETAIL":
        region = shot.get("region") or {}
        for k in (frm, to):
            k["x"], k["y"] = float(region.get("x", 0.5)), float(region.get("y", 0.5))
    direction = str(shot.get("direction", "")).lower()
    if preset == "DRIFT" and direction in ("rl", "right-to-left", "left"):
        frm["x"], to["x"] = to["x"], frm["x"]
    if preset == "TILT" and direction in ("up", "bottom-to-top"):
        frm["y"], to["y"] = to["y"], frm["y"]
    frm.update(shot.get("from") or {})
    to.update(shot.get("to") or {})
    out = []
    for k, t in ((frm, 0.0), (to, dur)):
        out.append({"t": t, "z": float(k.get("z", 1.0)), "x": float(k.get("x", 0.5)), "y": float(k.get("y", 0.5)),
                    "from": preset})
    return out


# --------------------------------------------------------------------------
# Cinematography ticket #10 (A54): READ, PORTRAIT and SURVEY
#
# Three more presets a screenplay may name, built from the ledger rather than
# a fixed framing: READ tilts or pans through a document or page's text at
# reading pace; PORTRAIT opens on a person's face, then pulls to the fill;
# SURVEY visits a painting's regions of interest in order, then pulls to the
# widest fill. Each is called from ``render.still_camera`` exactly where the
# old macros are (``preset in MACROS``), so it carries every A41/A43/A47
# guarantee a preset already has: the face cap, the people and must_show
# guards, A49's text-zone steering and ``render.engine_cover``'s covering
# pass. ``rich_macro_stops`` never raises for a still that lacks what the
# macro needs (no text region, no located person, fewer than two regions of
# interest, or no time for the pacing with its settles): it returns
# ``(None, why)`` and the caller falls back to the A47 subject pass, which
# ``render.tour_lints`` journals from ``why`` (ticket #10: "never refuse").
# --------------------------------------------------------------------------

READ_LINE_S = M.BRACKET["read_line_s"]                 # A50's reading pace, 1.0 to 1.5 s a line (doctrine 2.9)
READ_PASS_S = M.BRACKET["cross_s"]                     # the 7-second rule's own floor (A49 pan-speed-px)
READ_XHEIGHT_MIN_PX = 14.0                              # A41/A49's phone-legibility floor, on the 1080p master
READ_LINE_HEIGHT_XH = 2.4                               # a line's own height (leading included), x-heights
READ_MASTER = (1920, 1080)                              # the softness cap is judged on the 1080p master (A41)
SURVEY_MAX_STOPS = 3                                    # doctrine 2.2: one to three stops per still
SURVEY_ROW_TOL = 0.12                                   # a share of the picture's height: one reading "row"


def _read_region(shot: dict, roi: list[dict]) -> dict | None:
    """READ's text region, in this order: the shot's own ``region`` (as
    DETAIL takes it), else the ``roi`` name the shot gives, else the
    ledger's ``subject`` when it is text, else the first ``kind: text``
    region. None when the still names no text to read (the caller falls
    back to the A47 subject pass)."""
    region = shot.get("region")
    if isinstance(region, dict) and roi_box(region) is not None:
        return region
    named = shot.get("roi")
    if isinstance(named, str):
        hit = next((r for r in roi if r.get("name") == named), None)
        if hit is not None and roi_box(hit) is not None:
            return hit
    subj = next((r for r in roi if r.get("name") == "subject"), None)
    if subj is not None and subj.get("kind") == "text" and roi_box(subj) is not None:
        return subj
    return next((r for r in roi if r.get("kind") == "text" and roi_box(r) is not None), None)


def _read_frame(region: dict, size, aspect: float, zmax: float) -> tuple[str, float, float, float, float]:
    """The zoom READ reads at and the axis it travels. A region wider than
    it is tall (a banner, a caption line) is fit by its height and panned
    across (``x``); a page or a paragraph (taller, or square) is fit by its
    width and tilted down through it (``y``), so every line it shows is
    whole, edge to edge, at the deepest legible zoom the cap allows.
    Returns (axis, z, a, b, c): the window travels from ``a`` to ``b`` on
    ``axis`` (picture fractions), held at ``c`` on the other axis."""
    x0, y0, x1, y1 = roi_box(region)
    iw, ih = float(size[0]), float(size[1])
    fw, fh = fill_window(size, aspect)
    wide = (x1 - x0) * iw >= (y1 - y0) * ih
    zc = max(1.0, zmax)
    if wide:
        rh = max((y1 - y0) * ih, 1.0)
        z = max(1.0, min(fh / rh, zc))
        half = (fw / z) / 2.0 / iw
        c, span = (y0 + y1) / 2.0, x1 - x0
        a, b = (x0 + x1) / 2.0, (x0 + x1) / 2.0
        if span > 2 * half + EPS:
            a, b = x0 + half, x1 - half
        return "x", z, a, b, c
    rw = max((x1 - x0) * iw, 1.0)
    z = max(1.0, min(fw / rw, zc))
    half = (fh / z) / 2.0 / ih
    c, span = (x0 + x1) / 2.0, y1 - y0
    a, b = (y0 + y1) / 2.0, (y0 + y1) / 2.0
    if span > 2 * half + EPS:
        a, b = y0 + half, y1 - half
    return "y", z, a, b, c


def read_line_count(region: dict, size, z: float) -> int:
    """The region's own ``lines`` (A50's field), else estimated from its
    height in source pixels and a nominal line height at ``z`` (READ's own
    deepest legible zoom, ``_read_frame``): a line reads at
    ``READ_XHEIGHT_MIN_PX`` x-height or more on the 1080p master, and a
    line's own height, leading included, runs about
    ``READ_LINE_HEIGHT_XH`` times its x-height for body text, so one line
    needs about that many output pixels; dividing the region's own height
    in output pixels at z by it gives the line count a legible pass would
    show. No OCR and no glyph metrics: this is geometry, never a read of
    the picture's pixels."""
    n = region.get("lines")
    if isinstance(n, int) and not isinstance(n, bool) and n > 0:
        return n
    box = roi_box(region)
    if box is None:
        return 1
    bh_src = (box[3] - box[1]) * float(size[1])
    out_per_src = upscale(size, READ_MASTER[0], READ_MASTER[1], z)
    line_h_out = READ_XHEIGHT_MIN_PX * READ_LINE_HEIGHT_XH
    return max(1, round(bh_src * out_per_src / line_h_out))


def _read_stops(shot: dict, roi: list[dict], words: list[dict], dur: float, size, aspect: float,
                zmax: float) -> tuple[list[dict] | None, str | None]:
    """READ (doctrine 3.9, A54): a tilt (or pan) through the text in
    reading order at reading pace when the narration reads it (a
    ``kind: testimony`` word over the shot: GRAMMAR's "a reading"), else a
    7-second pass; ends with the last line held at least the text settle
    (1.5 s). A region too short to travel keeps the single legible hold
    (``a == b``)."""
    region = _read_region(shot, roi)
    if region is None:
        return None, "no text region: the ledger names no document or page text to read"
    axis, z, a, b, c = _read_frame(region, size, aspect, zmax)
    reads = any(w.get("kind") == "testimony" for w in words)
    n = read_line_count(region, size, z)
    travel_s = n * READ_LINE_S if reads else READ_PASS_S
    settle_s = M.CINE["settle_read_s"]
    if dur < travel_s + settle_s - EPS:
        pace = f"reading pace, {n} line{'s' if n != 1 else ''}" if reads else "the 7-second pass"
        return None, (f"too short: {pace} needs {travel_s + settle_s:.1f} s with the settle, the shot has "
                      f"{dur:.1f} s")
    cross = "y" if axis == "x" else "x"
    s0 = {"t": 0.0, "z": z, axis: a, cross: c, "from": "READ: the text, start"}
    if abs(a - b) <= EPS:
        return [s0], None                          # the region fits one screen: a hold at reading pace, no travel
    s1 = {"t": round(travel_s, 3), "z": z, axis: b, cross: c, "from": "READ: the text, last line"}
    return [s0, s1], None


def _portrait_subject(persons: list[dict], item: dict) -> dict | None:
    """PORTRAIT's face (doctrine 3.9, A54): the ledger's ``subject`` when it
    is a person or a face, else the one located face, else the largest of
    several (A47's own tie-break, ``subject_facing``). None when the
    ledger locates nobody (the fallback)."""
    faces = face_boxes(item)
    if not faces:
        return None
    named = next((f for f in faces if f.get("name") == "subject"), None)
    if named is not None:
        return named
    if len(faces) == 1:
        return faces[0]
    return max(faces, key=lambda f: _area(f["box"]))


def _portrait_facing(face: dict, persons: list[dict]) -> str | None:
    """The way PORTRAIT's subject faces: the located person's own
    ``facing`` (never inferred from the face, A43), else the largest
    located person over the face's box (``subject_facing``)."""
    for p in persons:
        if p.get("name") is not None and p.get("name") == face.get("name"):
            f = (p.get("entry") or {}).get("facing")
            if f in FACINGS:
                return f
    return subject_facing({"box": face["box"], "kind": "face"}, persons)


def _portrait_stops(item: dict, persons: list[dict], dur: float, size, aspect: float,
                    zmax: float, variant: str | None = None) -> tuple[list[dict] | None, str | None]:
    """PORTRAIT (doctrine 3.9, A54): open on the face (A43's z 1.3 cap,
    golden placement with lead room by facing, ``end_pose``), hold at
    least the face settle (1.5 s), then pull to the fill (z 1, the house's
    "whole" moment), landing at least the plain settle (1.0 s) before the
    cut. Identity is never read from the face (A43): this macro places a
    located person's geometry, and binds no name to it."""
    face = _portrait_subject(persons, item)
    if face is None:
        return None, "no located person: the ledger locates nobody to open on"
    facing = _portrait_facing(face, persons)
    zlim = min(max(1.0, zmax), face_cap_of(persons))
    open_pose = end_pose({"box": face["box"], "kind": "face"}, size, aspect, zlim, record=False, facing=facing)
    open_hold, fill_settle = M.CINE["settle_read_s"], M.CINE["settle_s"]
    pull_t = dur - fill_settle
    if pull_t < open_hold + EPS:
        return None, (f"too short: the open ({open_hold:g} s) and the pull with its settle ({fill_settle:g} s) "
                      f"need more than the shot's {dur:.1f} s")
    if variant == "explain":
        # A54: the reverse (explain), the whole first and in onto the face, landing the face settle before the cut
        push_t = dur - open_hold
        s0 = {"t": 0.0, "z": 1.0, "x": 0.5, "y": 0.5, "from": "PORTRAIT: the fill"}
        s1 = dict(open_pose, t=round(push_t, 3), keep=(tuple(face["box"]),), keep_strict=True,
                  **{"from": "PORTRAIT: in onto the face"})
        if push_t < fill_settle + leg_min_s(s0, s1, size, aspect) - EPS:
            return None, f"too short: the push onto the face and its settle need more than the shot's {dur:.1f} s"
        return [s0, s1], None
    s0 = dict(open_pose, t=0.0, hold=open_hold, **{"from": "PORTRAIT: the face"})
    s1 = {"t": round(pull_t, 3), "z": 1.0, "x": 0.5, "y": 0.5, "from": "PORTRAIT: pull to the fill"}
    return [s0, s1], None


def _survey_candidates(roi: list[dict]) -> list[dict]:
    return [r for r in roi if isinstance(r, dict) and roi_box(r) is not None]


def _survey_order(cands: list[dict]) -> list[dict]:
    """SURVEY's visiting order (doctrine 3.9, A54): the painter's own order
    when any region states one (``order``, A54), else reading order: rows
    top to bottom (centres within ``SURVEY_ROW_TOL`` of the picture's
    height count as one row), left to right inside a row."""
    def has_order(r):
        o = r.get("order")
        return isinstance(o, (int, float)) and not isinstance(o, bool)
    if any(has_order(r) for r in cands):
        return sorted(cands, key=lambda r: (r.get("order") if has_order(r) else math.inf, r.get("name") or ""))

    def key(r):
        x0, y0, x1, y1 = roi_box(r)
        return (round((y0 + y1) / 2.0 / SURVEY_ROW_TOL), (x0 + x1) / 2.0)
    return sorted(cands, key=key)


def _survey_stops(item: dict, roi: list[dict], dur: float, size, aspect: float,
                  zmax: float, variant: str | None = None,
                  persons: list[dict] | None = None) -> tuple[list[dict] | None, str | None]:
    """SURVEY (doctrine 3.9, A54): visits up to ``SURVEY_MAX_STOPS`` regions
    of interest in reading order (``_survey_order``), each framed whole
    with a margin (``roi_stop``) and held its own settle (A47's
    ``settle_for``: 1.5 s for a face, a person or text, else 1.0 s), then
    pulls to the widest fill, landing at least the plain settle before the
    cut. A picture with fewer than two regions of interest has nothing to
    survey (the fallback)."""
    cands = survey_picks(roi, persons, variant)
    if len(cands) < 2:
        return None, f"too few regions of interest: SURVEY visits at least 2, this picture names {len(cands)}"
    picked = cands[:SURVEY_MAX_STOPS]
    holds = [settle_for({"kind": r.get("kind")}) for r in picked]
    fill_settle = M.CINE["settle_s"]
    need = sum(holds) + fill_settle
    if dur < need - EPS:
        return None, (f"too short: {len(picked)} stops and the fill need at least {need:.1f} s, the shot has "
                      f"{dur:.1f} s")
    slack = (dur - need) / len(picked)
    stops, t = [], 0.0
    for r, h in zip(picked, holds):
        st = roi_stop(r, size, aspect, zmax)
        st.update(t=round(t, 3), hold=round(h, 3), roi=r.get("name"), **{"from": f"SURVEY: {r.get('name') or 'roi'}"})
        stops.append(st)
        t += h + slack
    stops.append({"t": round(dur - fill_settle, 3), "z": 1.0, "x": 0.5, "y": 0.5,
                 "from": "SURVEY: pull to the widest fill"})
    return stops, None


def survey_picks(roi: list[dict], persons: list[dict] | None, variant: str | None = None) -> list[dict]:
    """SURVEY's regions in visiting order: the ledger's regions of interest, else (A54) a crowd's located
    people (a face inside its figure is one person); ``reverse`` runs the other way."""
    cands = _survey_order(_survey_candidates(roi))
    if len(cands) < 2 and persons:
        # A54: a crowd's located people stand in for regions of interest (a face inside its figure is one person)
        boxes = sorted((q["box"] for q in persons), key=_area, reverse=True)
        kept: list = []
        for b in boxes:
            if not any(_inside_share(b, k) >= CINE["nest_share"] for k in kept):
                kept.append(b)
        cands = _survey_order([{"name": f"person-{k + 1}", "kind": "person", "x": b[0], "y": b[1],
                                "w": b[2] - b[0], "h": b[3] - b[1]} for k, b in enumerate(kept)])
    if variant == "reverse":
        cands = list(reversed(cands))                  # A54's variety: the survey runs the other way
    return cands


def rich_macro_stops(preset: str, shot: dict, item: dict, roi: list[dict], persons: list[dict], words: list[dict],
                     dur: float, size, aspect: float, zmax: float,
                     variant: str | None = None) -> tuple[list[dict] | None, str | None]:
    """READ, PORTRAIT and SURVEY (cinematography ticket #10, A54): the
    dispatcher ``render.still_camera`` calls for a preset in
    ``RICH_MACROS``. Returns (stops, why): ``stops`` is None exactly when
    the still has none of what the macro needs, or no time for its pacing
    with the settles, and ``why`` names which; the caller falls back to
    the A47 subject pass, journaled (never refused)."""
    if preset == "READ":
        return _read_stops(shot, roi, words, dur, size, aspect, zmax)
    if preset == "PORTRAIT":
        return _portrait_stops(item, persons, dur, size, aspect, zmax, variant=variant)
    if preset == "SURVEY":
        return _survey_stops(item, roi, dur, size, aspect, zmax, variant=variant, persons=persons)
    raise ValueError(f"not a rich macro: {preset!r}")


# A54 addendum (classic coverage, founder 2026-10-18): a still may be shown as hard cuts between WIDE, MEDIUM and
# CLOSE framings of the same picture inside its one shot (``cut: true`` on a stop: ``build`` draws no move to it)
CUT_SCALE_MIN = 1.6            # no jump cut: the scale changes by at least this between framings of one subject
CUT_FRAMING_MIN_S = 1.5        # each framing is on screen about this long at least (guidance)
CUT_MAX_FRAMINGS = 3           # at most this many framings in one showing


def path_need_s(stops: list[dict], size, aspect: float) -> float:
    """The least time a path of stops needs: every leg at the speed guides (``leg_min_s``) plus every hold."""
    return (sum(leg_min_s(a, b, size, aspect) for a, b in zip(stops, stops[1:]))
            + sum(float(st.get("hold", 0.0)) for st in stops))


def _screen_point(pose: dict, point, size, aspect: float) -> tuple[float, float]:
    iw, ih = float(size[0]), float(size[1])
    a0, b0, a1, b1 = window(size, aspect, pose["z"], pose["x"], pose["y"])
    return ((point[0] * iw - a0) / (a1 - a0), (point[1] * ih - b0) / (b1 - b0))


def cut_in_stops(subj: dict, size, aspect: float, dur: float, zlim: float, *, record: bool, order: str = "in",
                 facing: str | None = None, cut_at: float | None = None,
                 avoid=None, hz: float | None = 24.0) -> tuple[list[dict] | None, str | None]:
    """A54 CUT-IN on one subject: the WIDE (``whole_pose``) and the CLOSE
    (a DETAIL on the subject, ``zlim`` the softness and face caps), joined by
    a hard cut at ``cut_at`` (the narration's beat, else the middle), WIDE
    first (``order="in"``) or CLOSE first (``"out"``). The second framing is
    a match cut: it puts the subject where the first left it on the screen,
    when the subject stays whole there. Refused (None, why) for a jump cut
    (the scale changes less than ``CUT_SCALE_MIN``) or a shot too short for
    two framings of ``CUT_FRAMING_MIN_S``."""
    if subj.get("box") is None:
        return None, "no subject to cut in on"
    if dur < 2 * CUT_FRAMING_MIN_S - EPS:
        return None, f"too short for two framings of {CUT_FRAMING_MIN_S:g} s"
    close = end_pose(subj, size, aspect, zlim, record=record, facing=facing, avoid=avoid,
                     z_min=min(zlim, detail_z(size, aspect)))
    wide = whole_pose(size, aspect, record, avoid=avoid)
    for f in (close, wide):
        f.pop("avoid_clear", None)
    if close["z"] / wide["z"] < CUT_SCALE_MIN - EPS:
        return None, (f"a jump cut: the close is only {close['z'] / wide['z']:.2f}x the wide (the caps allow no "
                      f"more), under {CUT_SCALE_MIN:g}x")
    tc = _cut_time(min(max(dur / 2.0 if cut_at is None else cut_at, CUT_FRAMING_MIN_S),
                       dur - CUT_FRAMING_MIN_S), hz)
    b = subj["box"]
    point = ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)
    # the WIDE shows the whole picture: where its fill cannot (a 4:3 scan in 16:9), it sweeps end to end (A7:
    # people and must_show are seen on the cut-in itself), ending on the subject's side before a cut in and
    # starting on it after a cut out, so the cut matches as near as the fill allows
    ax = long_axis(size, aspect)
    sweep = whole_sweep(size, aspect, record, toward=point if order == "in" else (1.0 - point[0], 1.0 - point[1]))
    if sweep:
        # the sweep keeps the speed guides: the wide gets the time it needs, moved off the beat only when the
        # narration does not set the cut; else the cut-in is refused and the move stands
        span = _wide_span(sweep, size, aspect, hz)
        lo, hi = CUT_FRAMING_MIN_S, dur - CUT_FRAMING_MIN_S
        if order == "in" and tc < span - EPS and cut_at is None and span <= hi + EPS:
            tc = _cut_time(span, hz) + 1.0 / hz if hz else span
        elif order == "out" and dur - tc < span - EPS and dur - span >= lo - EPS:
            tc = _cut_time(dur - span, hz)
        if (tc if order == "in" else dur - tc) < span - 1e-3:
            return None, (f"the wide's sweep needs {span:.1f} s at the speed guides; the "
                          f"{'beat leaves' if cut_at is not None else 'shot leaves'} it "
                          f"{(tc if order == 'in' else dur - tc):.1f} s")
    iw, ih = float(size[0]), float(size[1])
    if order == "in":
        wide_end = sweep[1] if sweep else wide
        m, _err = match_start(point, _screen_point(wide_end, point, size, aspect), size, aspect, zs=(close["z"],))
        a0, b0, a1, b1 = window(size, aspect, m["z"], m["x"], m["y"])
        matched = _inside_share(b, (a0 / iw, b0 / ih, a1 / iw, b1 / ih)) >= 1.0 - 1e-6
        if matched:
            close = dict(close, x=m["x"], y=m["y"])
        lead = (_wide_sweep(sweep, 0.0, tc, hz) if sweep else
                [dict(wide, t=0.0, hold=tc, placed="engine", **{"from": "CUT-IN: the wide"})])
        s1 = dict(close, t=tc, cut=True, placed="engine", breath=True, match_cut=matched, keep=(tuple(b),),
                  **{"from": "CUT-IN: the close"})
        return lead + [s1], None
    m, _err = match_start(point, _screen_point(close, point, size, aspect), size, aspect, zs=(wide["z"],))
    s0 = dict(close, t=0.0, hold=tc, placed="engine", keep=(tuple(b),), **{"from": "CUT-IN: the close"})
    if sweep:
        tail = _wide_sweep(sweep, tc, dur, hz)
        tail[0].update(cut=True, match_cut=abs(float(m[ax]) - float(sweep[0][ax])) <= 0.02)
    else:
        tail = [dict(wide, x=m["x"], y=m["y"], t=tc, hold=0.0, cut=True, placed="engine", breath=True,
                     match_cut=True, **{"from": "CUT-IN: the wide"})]
    return [s0] + tail, None


CUT_PAD_S = 1e-4               # a cut sits this far before a frame, so that frame is the new framing's first
CUT_WIDE_SETTLE_S = 0.4        # a swept WIDE reaches its far end about this long before its framing ends


def _frame(t: float, hz: float | None) -> float:
    return math.floor(t * hz + 0.5) / hz if hz else t


def _cut_time(t: float, hz: float | None) -> float:
    """A cut padded onto the master's frame grid: just before the nearest frame, so the frame before it is
    the last of the old framing and the frame at it the first of the new (``at`` gives a boundary to the
    segment that ends there). The new framing's opening pose is on screen."""
    return _frame(t, hz) - CUT_PAD_S if hz else t


def _wide_span(sweep: tuple[dict, dict], size, aspect: float, hz: float | None) -> float:
    """The least time a swept WIDE framing needs: the sweep at the speed guides, its settle, and a frame."""
    return leg_min_s(sweep[0], sweep[1], size, aspect) + CUT_WIDE_SETTLE_S + (1.0 / hz if hz else 0.0)


def _wide_sweep(sweep: tuple[dict, dict], t0: float, t1: float, hz: float | None) -> list[dict]:
    """A54's swept WIDE over [t0, t1): from one end to the other, arriving on a frame at least one frame
    before ``t1`` (``CUT_WIDE_SETTLE_S`` before it), then a drift to the cut or the end, so both ends of the
    picture are on screen."""
    one = 1.0 / hz if hz else 0.0
    arrive = min(_frame(t1 - CUT_WIDE_SETTLE_S, hz), _frame(t1, hz) - one)
    return [dict(sweep[0], t=t0, hold=0.0, placed="engine", **{"from": "CUT-IN: the wide"}),
            dict(sweep[1], t=arrive, hold=max(0.0, t1 - arrive), placed="engine", breath=True,
                 **{"from": "CUT-IN: the wide, swept end to end"})]


def survey_cut_stops(picks: list[dict], size, aspect: float, dur: float,
                     zmax: float, hz: float | None = 24.0) -> tuple[list[dict] | None, str | None]:
    """A54 CUT-IN for a SURVEY: up to two of its regions (each a new subject, so never a jump cut) and then
    the WIDE, each framing an equal share of the shot, joined by hard cuts padded onto the frame grid; the
    WIDE sweeps end to end where its fill cannot show the whole picture (A7, as in ``cut_in_stops``)."""
    picked = picks[:CUT_MAX_FRAMINGS - 1]
    if len(picked) < 2:
        return None, "fewer than two regions to cut between"
    n = len(picked) + 1
    if dur < n * CUT_FRAMING_MIN_S - EPS:
        return None, f"too short for {n} framings of {CUT_FRAMING_MIN_S:g} s"
    sweep = whole_sweep(size, aspect, record=False)
    wspan = max(dur / n, _wide_span(sweep, size, aspect, hz)) if sweep else dur / n
    rest = dur - wspan                        # the regions share what the WIDE (its sweep at the guides) leaves
    if rest < (n - 1) * CUT_FRAMING_MIN_S - EPS:
        return None, f"the wide's sweep needs {wspan:.1f} s; {n - 1} framings of {CUT_FRAMING_MIN_S:g} s do not fit"
    starts = [0.0] + [_cut_time(k * rest / (n - 1), hz) for k in range(1, n)] + [dur]
    stops = []
    for k, r in enumerate(picked):
        st = roi_stop(r, size, aspect, zmax)
        st.update(t=starts[k], hold=starts[k + 1] - starts[k], roi=r.get("name"), placed="engine",
                  **{"from": f"CUT-IN: {r.get('name') or 'roi'}"})
        if k:
            st["cut"] = True
        stops.append(st)
    if sweep:
        wide = _wide_sweep(sweep, starts[n - 1], dur, hz)
        wide[0]["cut"] = True
        stops += wide
    else:
        stops.append({"t": starts[n - 1], "z": 1.0, "x": 0.5, "y": 0.5, "cut": True, "placed": "engine",
                      "breath": True, "from": "CUT-IN: the wide"})
    return stops, None


def field_const_z(size, aspect: float, zcap: float) -> float:
    """A54: the one scale a ``no_zoom`` PAN keeps, the window showing
    ``CINE['field_const_share']`` (0.6, FIELD) of the picture where the
    softness cap allows, else as near as it does (z 1 at the least)."""
    fw, fh = fill_window(size, aspect)
    z = math.sqrt(fw * fh / (float(size[0]) * float(size[1])) / CINE["field_const_share"])
    return max(1.0, min(z, max(1.0, zcap)))


def reveal_stops(subj: dict, size, aspect: float, dur: float, zlim: float, *, record: bool,
                 facing: str | None = None, avoid=None) -> tuple[list[dict] | None, str | None]:
    """A54 REVEAL: open on the subject at DETAIL (a window showing at most
    ``CINE['detail_share']`` of the picture where ``zlim``, the softness and
    face caps, allows), held its settle, then pull to the whole
    (``whole_pose``), landing at least the plain settle before the cut."""
    if subj.get("box") is None:
        return None, "no subject to open on"
    pose = end_pose(subj, size, aspect, zlim, record=record, facing=facing, avoid=avoid,
                    z_min=min(zlim, detail_z(size, aspect)))
    whole = whole_pose(size, aspect, record, avoid=avoid)
    hold, land = settle_for(subj), CINE["settle_s"]
    s0 = dict(pose, t=0.0, hold=hold, placed="engine", **{"from": "REVEAL: the detail"})
    s0.pop("avoid_clear", None)
    s1 = dict(whole, t=round(dur - land, 3), placed="engine", breath=True, **{"from": "REVEAL: the whole"})
    s1.pop("avoid_clear", None)
    if dur - land - hold < leg_min_s(s0, s1, size, aspect) - EPS:
        return None, f"too short: the detail, the pull and the settle need more than the shot's {dur:.1f} s"
    return [s0, s1], None


def pan_stops(subj: dict, size, aspect: float, dur: float, z: float, *, record: bool, near: bool = False,
              facing: str | None = None, arrive: float | None = None) -> tuple[list[dict] | None, str | None]:
    """A54 PAN (``no_zoom``): a pan or tilt at one scale ``z`` from the far
    end of the travel (``near``: the near end) to the subject, landing the
    settle before the cut (or at ``arrive``, the narration's cue), then
    drifting; the scale never changes (no_zoom's truth)."""
    if subj.get("box") is None:
        return None, "no subject to pan to"
    pose = end_pose(subj, size, aspect, z, record=record, facing=facing, z_min=z)
    pose = settle(dict(pose, z=z), size, aspect)
    iw, ih = float(size[0]), float(size[1])
    x0, y0, x1, y1 = window(size, aspect, z, 0.5, 0.5)
    room = {"x": iw - (x1 - x0), "y": ih - (y1 - y0)}
    ax = "x" if room["x"] >= room["y"] else "y"
    if room[ax] < 0.5:
        return None, "no room to pan at this scale"
    ends = [settle(dict(pose, **{ax: v}), size, aspect) for v in (0.0, 1.0)]
    far = max(ends, key=lambda e: abs(e[ax] - pose[ax]))
    nearest = min(ends, key=lambda e: abs(e[ax] - pose[ax]))
    start = nearest if near else far
    if _same(start, pose):
        return None, "the subject sits at that end: nothing to pan"
    settle_s = settle_for(subj)
    latest = dur - settle_s
    t1 = latest if arrive is None else min(max(arrive, 0.0), latest)
    s0 = dict(start, t=0.0, placed="engine", **{"from": f"PAN: the {'near' if near else 'far'} end"})
    s1 = dict(pose, t=round(t1, 3), placed="engine", breath=True, keep=(tuple(subj["box"]),),
              **{"from": "PAN: the subject"})
    if t1 < leg_min_s(s0, s1, size, aspect) - EPS:
        t1 = min(latest, leg_min_s(s0, s1, size, aspect))
        s1["t"] = round(t1, 3)
        if t1 < leg_min_s(s0, s1, size, aspect) - EPS:
            return None, f"too short to pan at the speed guides in {dur:.1f} s"
    return [s0, s1], None


# --------------------------------------------------------------------------
# A47: the camera ends on the subject (cinematography ticket #2)
# --------------------------------------------------------------------------

RECORD_CLASSES = ("document", "map", "painting", "object")
READ_KINDS = ("text", "face", "person")          # settled 1.5 s: read, then cut


def _focus_point(focus) -> tuple[float, float] | None:
    if (isinstance(focus, (list, tuple)) and len(focus) == 2 and all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and 0.0 <= v <= 1.0
            for v in focus)):
        return float(focus[0]), float(focus[1])
    return None


def is_record(item: dict) -> bool:
    """A record (a document, map, painting or object, or a still the ledger
    composes ``centred:``): composed centred, never upper-weighted."""
    comp = item.get("compose")
    if isinstance(comp, str):
        return comp.startswith("centred:")
    return item.get("class") in RECORD_CLASSES


def resolve_subject(roi: list[dict], focus=None, *, declared_whole: bool = False) -> dict:
    """What the still is about, in A47's order: the ledger's ``subject``
    region (a person's or the rulebook's, as ``effective_regions`` keeps it),
    else the shot's ``focus`` (a point), else ``whole`` (the whole picture is
    the subject). A ledger's own ``whole: true`` (``declared_whole``: a
    declaration, doctrine 1, not the rulebook's fallback) beats the shot's
    ``focus``. Returns {src, box (picture fractions x0, y0, x1, y1; None for
    whole), kind, facing, name}."""
    for r in roi or []:
        if isinstance(r, dict) and r.get("name") == "subject" and roi_box(r) is not None:
            return {"src": "subject", "box": roi_box(r), "kind": r.get("kind"), "facing": r.get("facing"),
                    "name": "subject"}
    pt = None if declared_whole else _focus_point(focus)
    if pt is not None:
        return {"src": "focus", "box": (pt[0], pt[1], pt[0], pt[1]), "kind": "focus", "facing": None, "name": None}
    return {"src": "whole", "box": None, "kind": "whole", "facing": None, "name": None}


def subject_point(subj: dict, pose: dict) -> tuple[float, float]:
    """The picture point that stands for the subject: its box's centre, or
    for ``whole`` the centre of its held window."""
    b = subj.get("box")
    if b is None:
        return pose["x"], pose["y"]
    return (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0


def subject_facing(subj: dict, persons: list[dict]) -> str | None:
    """The way the subject faces: its own ``facing``, else that of the
    largest located person whose centre lies in the subject's box."""
    if subj.get("facing") in FACINGS:
        return subj["facing"]
    b = subj.get("box")
    if b is None:
        return None
    best = None
    for q in persons or []:
        e = q.get("entry") or {}
        if e.get("facing") not in FACINGS:
            continue
        qb = q["box"]
        cx, cy = (qb[0] + qb[2]) / 2.0, (qb[1] + qb[3]) / 2.0
        if b[0] - EPS <= cx <= b[2] + EPS and b[1] - EPS <= cy <= b[3] + EPS:
            if best is None or _area(qb) > _area(best[0]):
                best = (qb, e["facing"])
    return best[1] if best else None


def settle_for(subj: dict) -> float:
    """How long the subject stop is held, settled, before the cut: 1.5 s for
    text, a face or a person, else 1.0 s (``CINE``)."""
    return CINE["settle_read_s"] if subj.get("kind") in READ_KINDS else CINE["settle_s"]


def avoid_overlap(size, window_px: tuple, avoid: list[tuple]) -> float:
    """The worst overlap share (A49) any ``avoid`` box (picture fractions)
    reaches against its own text zone (frame fractions), projected through
    ``window_px`` (picture pixels, as this module's own ``window()``
    returns it). 0.0 when nothing in ``avoid`` is visible at this window.
    The one measurement ``end_pose``, ``whole_pose``, ``creep`` and
    ``aimed_breath`` all steer against, so "clear" means the same thing
    everywhere.

    A51 ("faces never"): an entry may carry a third element, ``"face"``
    (``face_avoid``): a located face, which reads as under the zone at any
    overlap past ``CINE["face_under_text_share"]``. Such an entry counts as
    the warn share plus its own share once it touches the zone, so every
    caller's "clear" (under the warn share) means clear of every face too,
    and among candidates that are not clear the least-covered face still
    ranks first."""
    best = 0.0
    for a in avoid:
        box, zone = a[0], a[1]
        fb = project_box(size, window_px, box)
        if fb is not None:
            share = box_overlap_share(fb, zone)
            if is_face_avoid(a) and share > CINE["face_under_text_share"] + 1e-9:
                share = CINE["under_text_share"] + share
            best = max(best, share)
    return best


def is_face_avoid(a: tuple) -> bool:
    """A51: an ``avoid`` entry that is a located face (``face_avoid``)."""
    return len(a) > 2 and a[2] == "face"


def avoid_fits(size, window_px: tuple, avoid: list[tuple]) -> bool:
    """Whether every ``avoid`` box is whole inside ``window_px`` (A7/A41's
    own truth: a must_show region shown somewhere is never traded for
    clearing it of text), not merely visible in part. Steering never
    chooses a window a box does not fit, whatever it clears. A face entry
    (A51) is never a fit requirement: a face is steered out from under the
    text, never forced into the window (the people guards keep each person
    shown, ``people_check``, and the subject stop keeps a framed person
    whole, ``keep_strict``)."""
    iw, ih = float(size[0]), float(size[1])
    x0, y0, x1, y1 = window_px
    tol = 0.5
    for a in avoid:
        if is_face_avoid(a):
            continue
        box = a[0]
        bx0, by0, bx1, by1 = box[0] * iw, box[1] * ih, box[2] * iw, box[3] * ih
        if bx0 < x0 - tol or by0 < y0 - tol or bx1 > x1 + tol or by1 > y1 + tol:
            return False
    return True


def avoid_key(overlap: float, distance: float, fits: bool = True) -> tuple:
    """A49: the sort key every avoid-aware search here orders its candidates
    by: first, whether every ``avoid`` box still fits whole in the window
    (``avoid_fits``: A7/A41's coverage truth always outranks clearing a
    text zone, never the reverse); then whether this candidate already
    reads clear at the lint's own warn share (``CINE["under_text_share"]``,
    not the block share: the reviewer's own ruling is that a steer that
    merely ducks a refusal while still warning has moved the wrong way);
    among the clear candidates, the one closest to the planned pose
    (``distance``, the search's own units, e.g. a weight or a seconds
    offset) wins, so the steer moves no more than it has to; failing that,
    the candidate with the least overlap wins, whatever its distance (the
    reviewer item that follows names how close it came)."""
    warn = CINE["under_text_share"]
    clear = overlap < warn - 1e-9
    return (not fits, not clear, distance if (fits and clear) else overlap)


def whole_pose(size, aspect: float, record: bool, avoid: list[tuple] | None = None) -> dict:
    """``whole``: the fill (z 1), upper-weighted along the axis its window can
    travel (``CINE['whole_weight']`` of the travel from the top), centred for
    a record. A wide picture is centred across (it has no upper weight); a
    picture of the frame's own shape is the fill (no travel at all).

    ``avoid`` (A49, ``subject-under-text`` steering): when the doctrine
    weight's window still reads an overlap at or past the lint's own warn
    share, this searches the whole travel (the only freedom a ``whole``
    still has, in 2.5% steps) for the point with the least overlap, taking
    the one closest to the doctrine weight among those that clear it
    (``avoid_key``), so the engine never refuses itself here (ruling 2): a
    still with no subject region still has somewhere to go, and the steer
    never moves further than it has to. Returns {z, x, y[, avoid_clear]};
    ``avoid_clear`` is only set when ``avoid`` is given and is False only
    when no point along the travel reads under the warn share (no room: the
    caller falls back further, journaled, never refused)."""
    ih = float(size[1])
    fh = fill_window(size, aspect)[1]
    wgt = CINE["whole_weight_record"] if record else CINE["whole_weight"]
    ax = long_axis(size, aspect)
    p = {"z": 1.0, "x": 0.5, "y": 0.5}
    if ax == "y":
        p["y"] = (wgt * (ih - fh) + fh / 2.0) / ih
    if ax is None or not avoid:
        return p
    return travel_search(size, aspect, wgt, avoid)


def _travel_at(size, aspect: float, w: float) -> dict:
    """The fill (z 1) at weight ``w`` of its travel along the long axis (0 the
    top or left end, 1 the bottom or right end)."""
    iw, ih = float(size[0]), float(size[1])
    fw, fh = fill_window(size, aspect)
    q = {"z": 1.0, "x": 0.5, "y": 0.5}
    if long_axis(size, aspect) == "y":
        q["y"] = (w * (ih - fh) + fh / 2.0) / ih
    else:
        q["x"] = (w * (iw - fw) + fw / 2.0) / iw
    return q


def travel_weight(size, aspect: float, p: dict) -> float:
    """``_travel_at``'s inverse: where a framing's centre sits along the fill's
    travel, clamped to [0, 1]."""
    ax = long_axis(size, aspect)
    if ax is None:
        return 0.5
    full = float(size[0] if ax == "x" else size[1])
    win = fill_window(size, aspect)[0 if ax == "x" else 1]
    if full - win <= 1e-9:
        return 0.5
    return min(1.0, max(0.0, (float(p[ax]) * full - win / 2.0) / (full - win)))


def travel_search(size, aspect: float, prefer: float, avoid: list[tuple], span=(0.0, 1.0)) -> dict:
    """A49's ``whole`` search (``whole_pose``), shared with the subject pass's
    opening (A52): the fill (z 1) along its travel, in 2.5% steps inside
    ``span`` (weights), ordered by ``avoid_key``: a window every ``avoid`` box
    fits first, then one that reads clear of the warn share, the closest to
    ``prefer`` among those; failing that, the least overlap. Returns {z, x,
    y, avoid_clear}."""
    lo, hi = min(span), max(span)
    cands = sorted({round(k / 40.0, 4) for k in range(41)} | {round(prefer, 4)}, key=lambda w: abs(w - prefer))
    cands = [w for w in cands if lo - 1e-9 <= w <= hi + 1e-9 or w == round(prefer, 4)]

    def win_of(w: float) -> tuple:
        q = _travel_at(size, aspect, w)
        return window(size, aspect, q["z"], q["x"], q["y"])

    best_w, best_overlap, best_key = prefer, avoid_overlap(size, win_of(prefer), avoid), None
    for w in cands:
        win = win_of(w)
        ov = avoid_overlap(size, win, avoid)
        key = avoid_key(ov, abs(w - prefer), fits=avoid_fits(size, win, avoid))
        if best_key is None or key < best_key:
            best_key, best_w, best_overlap = key, w, ov
    best_fits = avoid_fits(size, win_of(best_w), avoid)
    return dict(_travel_at(size, aspect, best_w),
                avoid_clear=best_fits and best_overlap < CINE["under_text_share"] - 1e-9)


def _place(c: float, s: float, win: float, full: float, t: float) -> tuple[float, float]:
    """One axis, picture px: the window (``win`` long inside ``full``) that
    puts a subject centred at ``c`` (``s`` long) at ``t`` of the window, the
    subject kept ``compose_edge`` inside it; then clamped inside the
    picture. Returns (the window's start, the subject centre's share of it)."""
    e = CINE["compose_edge"]
    frac = s / win if win > 0 else 0.0
    if frac >= 1.0 - 2 * e:
        t = 0.5
    else:
        t = min(max(t, frac / 2.0 + e), 1.0 - frac / 2.0 - e)
    a = min(max(c - t * win, 0.0), max(0.0, full - win))
    return a, ((c - a) / win if win > 0 else 0.5)


def _in_band(v: float) -> bool:
    lo, hi = CINE["golden_band"]
    return lo - 1e-6 <= v <= hi + 1e-6 or 1.0 - hi - 1e-6 <= v <= 1.0 - lo + 1e-6


def _eyes(subj: dict) -> float | None:
    """Where a person's eyes sit (picture fraction, from the top), or None."""
    if subj.get("kind") not in PERSON_KINDS or subj.get("box") is None:
        return None
    y0, y1 = subj["box"][1], subj["box"][3]
    return y0 + (y1 - y0) * (CINE["eye_face"] if subj["kind"] == "face" else CINE["eye_person"])


def end_pose(subj: dict, size, aspect: float, zlim: float, *, record: bool, facing: str | None = None,
             no_zoom: bool = False, avoid: list[tuple] | None = None, z_min: float | None = None) -> dict:
    """The subject stop (A47): as deep as the subject allows and never past
    ``zlim`` (the softness cap, and the face cap for people; z 1 under
    ``no_zoom``: drift only), the window inside the picture, composed by
    class. Golden: the subject's centre on phi (0.382 or 0.618 of the window)
    on each axis that has room, thirds the fallback, the subject whole in
    frame; a subject facing left or right sits on the side behind it, so the
    room ahead is the larger; a person's eyes sit nearest the upper third.
    Centred for a record. ``whole`` is the upper-weighted fill
    (``whole_pose``).

    ``avoid`` (A49, ``subject-under-text`` steering): ``[(box, zone), ...]``,
    each a ``must_show`` region (picture fractions) and a house text zone
    (frame fractions, ``motion.ZONES``) active while this still is shown.
    Among the placements this function already tries, the one that leaves
    every ``avoid`` box under ``CINE["under_text_block_share"]`` of its zone
    wins first, ahead of the usual golden-band and eye-line scoring; this
    never widens the search (no new placement is invented) and never moves
    a path a person wrote (``parse_path`` never calls this with ``avoid``).
    The chosen pose carries ``avoid_clear`` (bool) when ``avoid`` is given,
    so the caller knows whether steering actually cleared it or every
    candidate still covers something (A49: refuse only then, or when the
    camera is a human's own). Returns {z, x, y[, avoid_clear]}."""
    if subj["box"] is None:
        return whole_pose(size, aspect, record, avoid=avoid)
    iw, ih = float(size[0]), float(size[1])
    fw, fh = fill_window(size, aspect)
    x0, y0, x1, y1 = subj["box"]
    bw, bh = (x1 - x0) * iw, (y1 - y0) * ih
    cx, cy = (x0 + x1) / 2.0 * iw, (y0 + y1) / 2.0 * ih
    phi, e = CINE["phi"], CINE["compose_edge"]
    if record:
        tx, ty, share = [0.5], [0.5], 0.8      # roi_stop's margin: the region whole, with room round it
    else:
        if facing == "right":
            tx = [phi, 1 / 3]                  # left of centre: the room ahead is on the right
        elif facing == "left":
            tx = [1 - phi, 2 / 3]
        else:
            tx = [phi, 1 / 3] if cx <= iw / 2.0 else [1 - phi, 2 / 3]
        ty = ([phi, 1 - phi, 1 / 3, 2 / 3] if subj.get("kind") in PERSON_KINDS else
              [phi, 1 / 3] if cy <= ih / 2.0 else [1 - phi, 2 / 3])
        share = 2 * (phi - e)                  # the subject fits whole with its centre on phi
    z = 1.0
    if not no_zoom:
        zs = [max(1.0, zlim)]
        if bw > 0:
            zs.append(fw * share / bw)
        if bh > 0:
            zs.append(fh * share / bh)
        z = max(1.0, min(zs))
        if z_min is not None:
            z = max(z, min(z_min, max(1.0, zlim)))     # A54: a DETAIL end goes past the subject's own fit
    ww, wh = fw / z, fh / z
    eye = _eyes(subj)

    def win_at(ax_, ay_) -> tuple:
        return (ax_, ay_, ax_ + ww, ay_ + wh)

    best = None
    for t_y in ty:
        for t_x in tx:
            ax_, px = _place(cx, bw, ww, iw, t_x)
            ay_, py = _place(cy, bh, wh, ih, t_y)
            if record:
                miss = 0
            else:
                miss = int(not (_in_band(px) or ww >= iw - 0.5)) + int(not (_in_band(py) or wh >= ih - 0.5))
            eye_dist = round(abs((eye * ih - ay_) / wh - 1 / 3), 6) if eye is not None else 0.0
            win = win_at(ax_, ay_)
            ov = avoid_overlap(size, win, avoid) if avoid else 0.0
            fits = avoid_fits(size, win, avoid) if avoid else True
            clear = ov < CINE["under_text_share"] - 1e-9
            # A49: among the house's own golden-band/eye-line candidates, one that already reads clear of an
            # active text zone (and still fits every avoid box whole, A7/A41's coverage truth) wins first (by
            # the usual scoring, among those); only when none clears it does overlap itself decide (the
            # reviewer item that follows names how close it came)
            key = (not fits, not clear, miss if (fits and clear) else ov, eye_dist if (fits and clear) else 0.0)
            if best is None or key < best[0]:
                best = (key, ax_, ay_, ov, fits)
    _, ax_, ay_, best_overlap, best_fits = best
    pose = {"z": z, "x": (ax_ + ww / 2.0) / iw, "y": (ay_ + wh / 2.0) / ih}
    if avoid:
        pose["avoid_clear"] = best_fits and best_overlap < CINE["under_text_share"] - 1e-9
    return pose


def compose_verdict(p: dict, subj: dict, size, aspect: float, *, record: bool, facing: str | None = None) -> dict:
    """What a framing {z, x, y} does with the subject (A47; #4's
    ``end-pose-composition`` reads the same numbers): the subject's centre
    as a share of the window on each axis (None where the window spans the
    picture: no room to place it), whether its box is whole in frame, the
    room ahead and behind on the axis it faces, its eyes' height, and the
    verdict: golden, centred, whole, or what kept it off."""
    iw, ih = float(size[0]), float(size[1])
    a0, b0, a1, b1 = window(size, aspect, p["z"], p["x"], p["y"])
    ww, wh = a1 - a0, b1 - b0
    out = {"window": [round(a0 / iw, 4), round(b0 / ih, 4), round(a1 / iw, 4), round(b1 / ih, 4)]}
    if subj["box"] is None:
        out.update(verdict="whole", inside=True, centre_in_frame=True, flush=[], edge_not_subject=[],
                   shown=round((a1 - a0) * (b1 - b0) / (iw * ih), 4))
        return out
    x0, y0, x1, y1 = subj["box"]
    cx, cy = (x0 + x1) / 2.0 * iw, (y0 + y1) / 2.0 * ih
    # an axis has room to place the subject when the window travels more than a shown strip on it (long_axis)
    room_x, room_y = ww < iw * (1.0 - 2 * SHOWN_STRIP), wh < ih * (1.0 - 2 * SHOWN_STRIP)
    px, py = (cx - a0) / ww, (cy - b0) / wh
    tol = 0.5                                  # half a source pixel
    flush = [n for n, hit in (("left", room_x and a0 <= tol), ("right", room_x and a1 >= iw - tol),
                              ("top", room_y and b0 <= tol), ("bottom", room_y and b1 >= ih - tol)) if hit]
    # an edge the window rests on is the subject's unless the subject sits wholly in the third away from it
    near = {"left": x0 * iw <= a0 + 2 / 3 * ww, "right": x1 * iw >= a1 - 2 / 3 * ww,
            "top": y0 * ih <= b0 + 2 / 3 * wh, "bottom": y1 * ih >= b1 - 2 / 3 * wh}
    out.update(subject_x=round(px, 4), subject_y=round(py, 4), room_x=room_x, room_y=room_y,
               inside=(x0 * iw >= a0 - tol and y0 * ih >= b0 - tol and x1 * iw <= a1 + tol and y1 * ih <= b1 + tol),
               centre_in_frame=-1e-6 <= px <= 1.0 + 1e-6 and -1e-6 <= py <= 1.0 + 1e-6, flush=flush,
               shown=round(_inside_share(subj["box"], (a0 / iw, b0 / ih, a1 / iw, b1 / ih)), 4),
               edge_not_subject=[n for n in flush if not near[n]])
    eye = _eyes(subj)
    if eye is not None:
        out["eyes_y"] = round((eye * ih - b0) / wh, 4)
    if facing in ("left", "right"):
        behind = (x0 * iw - a0) if facing == "right" else (a1 - x1 * iw)
        ahead = (a1 - x1 * iw) if facing == "right" else (x0 * iw - a0)
        out.update(facing=facing, lead_room=round(ahead / ww, 4), room_behind=round(behind / ww, 4),
                   lead_ok=ahead >= behind - 0.5)
    cb = CINE["centred_band"]
    axes = [v for v, r in ((px, room_x), (py, room_y)) if r]
    if not axes:
        out["verdict"] = "no room (the window spans the picture)"
    elif record:
        out["verdict"] = ("centred" if all(abs(v - 0.5) <= cb + 1e-6 for v in axes) else
                          "off-centre (the subject sits at the picture's edge)" if flush else "off-centre")
    elif all(_in_band(v) for v in axes):
        out["verdict"] = "golden"
    elif all(abs(v - 0.5) <= cb + 1e-6 for v in axes):
        out["verdict"] = "centred (too large for phi)"
    else:
        out["verdict"] = "past the band (the subject sits at the picture's edge)" if flush else "off"
    return out


def _leg_dist(a: dict, b: dict, size, aspect: float) -> tuple[float, float]:
    """A leg's travel: (the larger of its pan and tilt in the smaller of its
    two windows' widths or heights, as ``speed_report`` judges it at the
    tight end; its zoom as a log ratio)."""
    wa = window(size, aspect, a["z"], a["x"], a["y"])
    wb = window(size, aspect, b["z"], b["x"], b["y"])
    ww, wh = min(wa[2] - wa[0], wb[2] - wb[0]), min(wa[3] - wa[1], wb[3] - wb[1])
    pan = max(abs((wb[0] + wb[2]) - (wa[0] + wa[2])) / 2.0 / ww, abs((wb[1] + wb[3]) - (wa[1] + wa[3])) / 2.0 / wh)
    return pan, abs(math.log(b["z"] / a["z"]))


def leg_min_s(a: dict, b: dict, size, aspect: float) -> float:
    """The shortest leg on the rostrum curve whose cruise stays inside the
    speed guides (A41: a third of the frame a second, 15% scale a second)."""
    pan, zl = _leg_dist(a, b, size, aspect)
    need = max(pan / TOUR["pan_guide_per_s"], zl / math.log(1.0 + TOUR["zoom_guide_per_s"]))
    if need <= EPS:
        return 0.0
    # the cruise covers 1 / (T - ramp) of the leg a second, the ramp min(0.9 s, 30% of T) (motion.rostrum)
    return need / 0.7 if need / 0.7 <= 3.0 else need + 0.9


def subject_stops(size, aspect: float, dur: float, pose: dict, *, arrive: float, settle_s: float,
                  need_whole: bool = False, start: dict | None = None, breath: bool = False,
                  from_near: bool = False, waypoints=(), hz: float = 24.0,
                  continues: bool = False, open_avoid: list[tuple] | None = None) -> tuple[list[dict], dict]:
    """A47's default pass, ending on the subject: it opens at the end of the
    picture's long axis furthest from the subject (or, ``start``, where a
    ``match: prev`` puts the subject), sweeps once and lands on ``pose`` at
    ``arrive`` (shot seconds), never later than ``settle_s`` before the cut,
    and holds there to the cut, creeping (one ``breath`` on a ``whole``
    still). It never comes back on itself unless ``need_whole``: the A7
    guard needs the whole picture shown (a person the ledger has not
    located), so it passes the far end, then the near end, then settles on
    the subject. ``from_near`` opens at the near end instead (a located
    person there that the far end's sweep would never show). No leg is
    faster than the speed guides allow: a pass that cannot reach the subject
    in time starts nearer it, or, when the whole picture is needed, arrives
    late (A7 first). ``waypoints`` (framings with ``_hold`` seconds, used
    with ``need_whole``) are visited in order along the sweep between the far
    and the near end, and held there: a person the sweep would pass between
    two frames is held whole in frame. The holds take at most half of the
    time before the arrival, each at least one frame at ``hz``; when even
    that does not fit, the arrival runs late, up to the cut (A7 first).
    ``open_avoid`` (A52, A51's opening refined): the opening end is searched
    as ``whole_pose`` searches the fill (``travel_search``), between that
    end and the subject, so a ``must_show`` box or a face under a lower
    third or subtitle already up is minimised from the first frame; the end
    itself wins whenever it is already clear, and the sweep's direction is
    never reversed. Returns (stops, timing), the stop times never going back."""
    ax = long_axis(size, aspect)
    pose = dict(pose, **settle(pose, size, aspect))
    pose.setdefault("from", "A47: the subject")
    if breath:
        pose["breath"] = True
    latest = max(0.0, dur - settle_s)
    want = min(max(0.0, arrive), latest)
    timing = {"asked_s": round(arrive, 3), "latest_s": round(latest, 3)}
    pts: list[dict] = []
    if start is not None:
        pts.append(dict(settle(start, size, aspect), **{"from": "A47: match prev"}))
    ends: list[dict] = []
    if ax is not None:
        a = settle({"z": 1.0, "x": 0.5, "y": 0.5, ax: 0.0}, size, aspect)
        b = settle({"z": 1.0, "x": 0.5, "y": 0.5, ax: 1.0}, size, aspect)
        far, near = (a, b) if abs(pose[ax] - a[ax]) >= abs(pose[ax] - b[ax]) else (b, a)
        ends = [dict(far, **{"from": "A47: the far end"}), dict(near, **{"from": "A47: the near end"})]
    if need_whole and ends:
        far_, near_ = ends
        sgn = 1.0 if near_[ax] >= far_[ax] else -1.0
        mid = sorted((dict(settle(w, size, aspect), _hold=w.get("_hold", 0.0), **{"from": "A47: held on a person"})
                      for w in waypoints), key=lambda w: sgn * w[ax])
        # each end is held a moment, so a frame at any master rate lands on it (the whole picture shown, A7)
        hold_end = CINE["end_hold_s"]
        pts += [dict(far_, _hold=hold_end), *mid, dict(near_, _hold=hold_end)]
    elif need_whole:
        # a picture of the frame's own shape: the fill shows it whole, so the pass passes the fill
        pts += [dict(settle(w, size, aspect), _hold=w.get("_hold", 0.0), **{"from": "A47: held on a person"})
                for w in waypoints]
        pts.append({"z": 1.0, "x": 0.5, "y": 0.5, "from": "A47: the fill"})
    elif start is None:
        opening = ends[1 if from_near else 0] if ends else {"z": 1.0, "x": 0.5, "y": 0.5, "from": "A47: the fill"}
        if open_avoid and ends:
            ew = travel_weight(size, aspect, opening)
            q = travel_search(size, aspect, ew, open_avoid, span=(ew, travel_weight(size, aspect, pose)))
            w0 = window(size, aspect, opening["z"], opening["x"], opening["y"])
            w1 = window(size, aspect, q["z"], q["x"], q["y"])
            if not _same(opening, q) and avoid_overlap(size, w1, open_avoid) < avoid_overlap(size, w0, open_avoid) - 1e-9:
                timing["open_steered"] = {"from": round(opening[ax], 4), "to": round(q[ax], 4),
                                          "overlap_from": round(avoid_overlap(size, w0, open_avoid), 4),
                                          "overlap_to": round(avoid_overlap(size, w1, open_avoid), 4)}
                opening = {"z": 1.0, "x": q["x"], "y": q["y"],
                           "from": "A52: the opening, steered clear of live text along the travel"}
        pts.append(opening)
    pts.append(pose)
    path = [pts[0]]
    for q in pts[1:]:
        if not _same(path[-1], q):
            path.append(q)
        elif q is pose:
            path[-1] = q                        # an end that is the subject's own framing is the subject's stop
    if len(path) == 1:
        timing.update(arrive_s=0.0, why="the shot opens on the subject: held from the cut")
        return [dict(path[0], t=0.0)], timing
    legs = list(zip(path, path[1:]))
    holds = sum(float(q.get("_hold", 0.0)) for q in path[1:])
    need = sum(leg_min_s(a, b, size, aspect) for a, b in legs) + holds
    if want + EPS < need:
        if need_whole or start is not None:
            want = min(need, latest)
            timing["why"] = ("A7: the whole picture is shown before the subject" if need_whole else
                             "the match opening keeps to the speed guides")
        elif want <= 0.5:
            timing.update(arrive_s=0.0, why="no time to sweep before the subject: held on it from the cut")
            return [dict(pose, t=0.0)], timing
        else:
            a0 = path[0]

            def out_at(k):
                return {"z": pose["z"] * (a0["z"] / pose["z"]) ** k, "x": pose["x"] + (a0["x"] - pose["x"]) * k,
                        "y": pose["y"] + (a0["y"] - pose["y"]) * k, "from": "A47: as far out as the time allows"}
            lo, hi = 0.0, 1.0                   # a shorter lead-in: as far out as the speed guides allow
            for _ in range(40):
                mid = (lo + hi) / 2.0
                if leg_min_s(out_at(mid), pose, size, aspect) <= want:
                    lo = mid
                else:
                    hi = mid
            st = out_at(lo)
            path, legs = [st, pose], [(st, pose)]
            timing["why"] = "a short lead-in: the sweep opens as far out as the speed guides allow"
    timing.setdefault("why", "subject_at" if arrive < latest - EPS else "settled before the cut")
    dist = [sum(_leg_dist(a, b, size, aspect)) for a, b in legs]
    frame = 1.0 / float(hz)
    hs = [float(b.get("_hold", 0.0)) for _, b in legs]
    if sum(hs) > 0.5 * want + EPS:
        nh = sum(1 for h in hs if h > 0)
        if nh * frame > 0.5 * want:
            want = min(dur, max(want, 2.0 * nh * frame))          # the arrival runs late (A7 first)
            timing["why"] = "A7: the holds on the whole picture need the time, so the subject is reached late"
        k = min(1.0, 0.5 * want / sum(hs))
        hs = [max(frame, h * k) if h > 0 else 0.0 for h in hs]
        if sum(hs) >= want:                                       # a shot too short for even one frame each
            hs = [0.0 for _ in hs]
    holds = sum(hs)
    total = sum(dist) or 1.0
    move = max(0.0, want - holds)
    out = [dict(path[0], t=0.0)]
    t = 0.0
    for (_, b), d, h in zip(legs, dist, hs):
        t += move * d / total
        out.append(dict(b, t=t))
        if h > 0.0:
            t += h
            out.append(dict(b, t=t))
    out[-1]["t"] = max(want, out[-2]["t"]) if len(out) > 1 else want
    for st in out:
        st.pop("_hold", None)
    # A54 (entering mid-move) replaces A49's opening settle: the pass leaves the cut frame already moving, at the
    # creep's speed in its first leg's direction (``build``, ``motion.enter_moving``), never from rest
    timing["arrive_s"] = round(want, 3)
    return out, timing


def reversals(tl: dict) -> list[dict]:
    """``in-shot-reversal`` (A47, guidance): a move that turns back on an
    axis the move before it travelled (a pass that sweeps and comes back).
    Creeps are not moves. Returns [{t, axis}]."""
    size, aspect = tl["size"], tl["aspect"]
    out, prev = [], None
    for g in tl["segments"]:
        if g["kind"] != "move":
            continue
        wa = window(size, aspect, g["a"]["z"], g["a"]["x"], g["a"]["y"])
        wb = window(size, aspect, g["b"]["z"], g["b"]["x"], g["b"]["y"])
        v = ((wb[0] + wb[2]) - (wa[0] + wa[2]), (wb[1] + wb[3]) - (wa[1] + wa[3]))
        if prev is not None:
            for k, name in enumerate(("x", "y")):
                if abs(prev[k]) > 1.0 and abs(v[k]) > 1.0 and (prev[k] > 0) != (v[k] > 0):
                    out.append({"t": round(g["t0"], 3), "axis": name})
        prev = v
    return out


def screen_of(tl: dict, point: tuple[float, float], t: float | None = None) -> tuple[float, float]:
    """Where a picture point (fractions) sits on the screen (frame
    fractions) at shot time ``t`` (the last frame by default): what ``match:
    prev`` carries across a cut."""
    size, aspect = tl["size"], tl["aspect"]
    f = at(tl, tl["dur"] if t is None else t)
    a0, b0, a1, b1 = window(size, aspect, f["z"], f["x"], f["y"])
    return (point[0] * float(size[0]) - a0) / (a1 - a0), (point[1] * float(size[1]) - b0) / (b1 - b0)


def match_start(point: tuple[float, float], screen, size, aspect: float, zs=(1.0,)) -> tuple[dict, float]:
    """``match: prev`` (A47, on a cut): the opening framing that puts the
    picture point ``point`` where the previous shot left its subject on the
    screen (``screen``, frame fractions), at the zoom of ``zs`` that comes
    nearest inside the picture. Returns (framing, the error left in frame
    fractions)."""
    iw, ih = float(size[0]), float(size[1])
    fw, fh = fill_window(size, aspect)
    best = None
    for z in zs:
        ww, wh = fw / z, fh / z
        c = settle({"z": z, "x": (point[0] * iw + (0.5 - screen[0]) * ww) / iw,
                    "y": (point[1] * ih + (0.5 - screen[1]) * wh) / ih}, size, aspect)
        a0, b0, a1, b1 = window(size, aspect, c["z"], c["x"], c["y"])
        err = math.hypot((point[0] * iw - a0) / (a1 - a0) - screen[0], (point[1] * ih - b0) / (b1 - b0) - screen[1])
        if best is None or err < best[1] - 1e-9:
            best = (c, err)
    return best


def fit_zmax(box, pose: dict, size, aspect: float) -> float:
    """The deepest zoom about the pose's own centre that keeps the subject's
    box whole in the window (the creep on the subject stop pushes no
    further, so the hold never cuts what it landed on)."""
    iw, ih = float(size[0]), float(size[1])
    fw, fh = fill_window(size, aspect)
    a0, b0, a1, b1 = window(size, aspect, pose["z"], pose["x"], pose["y"])
    cx, cy = (a0 + a1) / 2.0, (b0 + b1) / 2.0
    hx = max(cx - box[0] * iw, box[2] * iw - cx, EPS)
    hy = max(cy - box[1] * ih, box[3] * ih - cy, EPS)
    return max(1.0, min(fw / (2.0 * hx), fh / (2.0 * hy)))


def must_see(item: dict) -> dict:
    """What any pass the engine draws must show (A7 and A41): the located
    people and the ledger's ``must_show`` regions, as ``people_check`` boxes
    (the unlocated are the caller's ``need_whole``). Empty when there are
    none."""
    pe = people_of(item)
    names = item.get("must_show") if isinstance(item.get("must_show"), list) else []
    boxes = list(pe["boxes"])
    roi = item.get("roi") if isinstance(item.get("roi"), list) else []
    for r in roi:
        if isinstance(r, dict) and roi_box(r) is not None and (r.get("must_show") is True or r.get("name") in names):
            boxes.append({"name": r.get("name"), "box": roi_box(r)})
    return {"boxes": boxes, "unlocated": 0, "known": pe["known"]} if boxes else {}


def aimed_breath(size, aspect: float, boxes, record: bool, aerial: bool = False,
                 avoid: list[tuple] | None = None) -> tuple[dict, dict] | None:
    """A ``whole`` hold whose one window cannot hold every located person and
    ``must_show`` region together (``boxes``, picture fractions): its drift,
    at z 1 along the axis the fill travels, is aimed so each is whole at some
    point. The drift is the shortest one that reaches every box's span of
    window positions, opened on the one read first (``whole_sweep``'s order:
    top to bottom for a record or a picture seen from above, left to right
    on a wide picture, rising otherwise) and ended with the other, no longer
    than one breath (``whole_creep_max`` of the window). Returns (first, last)
    or None (a box larger than the window, or a drift longer than a breath:
    the hold becomes the sweep).

    ``avoid`` (A49): when an end still covers a must_show box with an active
    text zone, this extends that end outward, within the same breath-length
    budget, to the nearest point clear of it; coverage (every box whole at
    some point) is never traded away for this, so a `must_show`/people
    guarantee always wins when the two conflict, and a still-conflicted end
    is left as it was (the caller's own fallback, journaled, never refused)."""
    ax = long_axis(size, aspect)
    if ax is None or not boxes:
        return None
    k = 0 if ax == "x" else 1
    side = float(size[k])
    win = fill_window(size, aspect)[k]
    lo_c, hi_c = win / 2.0, side - win / 2.0
    spans = []
    for b in boxes:
        a0, a1 = float(b[k]) * side, float(b[k + 2]) * side
        if a1 - a0 > win + 1e-6:
            return None
        spans.append((max(lo_c, a1 - win / 2.0), min(hi_c, a0 + win / 2.0)))
    lo, hi = min(sp[1] for sp in spans), max(sp[0] for sp in spans)
    if hi <= lo + 1e-9:
        return None                               # one window holds them all: the plain breath
    budget = (TOUR["whole_creep_max"] - 1.0) * win
    if hi - lo > budget + 1e-9:
        return None
    lo, hi = max(lo_c, lo - 1.0), min(hi_c, hi + 1.0)     # a pixel past each tight end: whole on a frame, not a float
    a, b = (lo, hi) if (ax == "x" or record or aerial) else (hi, lo)

    def pose_at(v: float) -> dict:
        return settle({"z": 1.0, "x": 0.5, "y": 0.5, ax: v / side}, size, aspect)

    def win_at(v: float) -> tuple:
        q = pose_at(v)
        return window(size, aspect, q["z"], q["x"], q["y"])

    def clear(v: float) -> bool:
        if not avoid:
            return True
        win = win_at(v)
        return avoid_fits(size, win, avoid) and avoid_overlap(size, win, avoid) < CINE["under_text_share"] - 1e-9

    if avoid:
        spare = max(0.0, budget - (hi - lo))
        lo_v, hi_v = min(a, b), max(a, b)
        if spare > 1e-6:
            for edge, grow in ((lo_v, -1.0), (hi_v, 1.0)):
                if clear(edge):
                    continue
                # A49: step outward within the same breath budget for the least overlap, preferring the point
                # closest to the box's own tight edge among any that read clear of the lint's warn share
                win0 = win_at(edge)
                best_v = edge
                best_key = avoid_key(avoid_overlap(size, win0, avoid), 0.0, fits=avoid_fits(size, win0, avoid))
                step = spare / 40.0
                v = edge
                for k in range(1, 41):
                    v = max(lo_c, min(hi_c, edge + grow * step * k))
                    win = win_at(v)
                    key = avoid_key(avoid_overlap(size, win, avoid), abs(v - edge), fits=avoid_fits(size, win, avoid))
                    if key < best_key:
                        best_key, best_v = key, v
                if edge == lo_v:
                    lo_v = best_v
                else:
                    hi_v = best_v
            a, b = (lo_v, hi_v) if a <= b else (hi_v, lo_v)
    first = pose_at(a)
    last = pose_at(b)
    return first, last


def whole_sweep(size, aspect: float, record: bool, toward=None, aerial: bool = False) -> tuple[dict, dict] | None:
    """A ``whole`` still its fill cannot show (``whole_hold_min_shown``): one
    sweep end to end, never coming back. Rising (bottom to top) for a person,
    a crowd or a place, top to bottom for a record (reading order), left to
    right for a wide picture. ``aerial`` (rulebook 7: the still's own words
    say it was seen from above, where up in the picture is not the sky): never
    rising, left to right on a wide picture and top to bottom where the fill
    travels only up and down. ``toward`` (the next shot's subject, picture
    fractions, when it says ``match: "prev"``): the sweep ends on that side,
    so the match carries a real position. Returns (first, last) at the fill,
    or None when the fill cannot travel."""
    ax = long_axis(size, aspect)
    if ax is None:
        return None
    a, b = (0.0, 1.0) if (ax == "x" or record or aerial) else (1.0, 0.0)
    if toward is not None:
        b = 1.0 if float(toward[0 if ax == "x" else 1]) >= 0.5 else 0.0
        a = 1.0 - b
    first = settle({"z": 1.0, "x": 0.5, "y": 0.5, ax: a}, size, aspect)
    last = settle({"z": 1.0, "x": 0.5, "y": 0.5, ax: b}, size, aspect)
    return first, last


def subject_arrival(shot: dict, item: dict, subj: dict, persons: list[dict], words: list[dict], t0: float,
                    dur: float, settle_s: float) -> tuple[float, dict | None, str]:
    """When the subject stop arrives (shot seconds), the narration span it is
    anchored to, and why. With ``subject_at`` (a cue the narration speaks
    over the shot): before the cue's onset by the A43 lead, 0.5 s on
    measured words and on estimated ones, 1.0 s on estimated words when the
    subject is a person the cue names (the binding: arrive early, hold
    through the name). Without it: settled ``settle_s`` before the shot's
    last line ends, so the subject holds through the end of the line and the
    breath after it; a shot with no narration lands it ``settle_s`` before
    the cut."""
    sa = shot.get("subject_at")
    if sa is not None:
        at_, line = (sa.get("at"), sa.get("line")) if isinstance(sa, dict) else (sa, None)
        sp = anchor_span(at_, words, line=line, t0=t0)
        if sp is not None and t0 - EPS <= sp["t"] <= t0 + dur + EPS:
            spoken = [w["w"] for w in sp["words"]]
            person = subj.get("kind") in PERSON_KINDS and names_a_person(spoken, item, persons)
            lead = CINE["anchor_lead_s"] if sp["measured"] or not person else CINE["anchor_estimated_lead_s"]
            why = (f"subject_at {at_!r}: {lead:g} s before its onset"
                   f" ({'measured' if sp['measured'] else 'estimated'} words{', a person it names' if person else ''})")
            return sp["t"] - t0 - lead, sp, why
    ends = [w["e"] - t0 for w in words if t0 - EPS <= w["t"] <= t0 + dur + EPS]
    if ends:
        return min(dur, max(ends)) - settle_s, None, "settled before the shot's last line ends: held through it"
    return dur, None, "no narration over the shot: settled before the cut"


def subject_plan(shot: dict, item: dict, roi: list[dict], persons: list[dict], words: list[dict], size,
                 aspect: float, dur: float, t0: float, zmax: float, *, need_whole: bool, focus=None,
                 match_screen=None, declared_whole: bool = False, hold_on=(), hz: float = 24.0,
                 avoid: list[tuple] | None = None, detail: bool = False) -> tuple[list[dict], dict]:
    """A47's default for a still: the subject (``resolve_subject``), its end
    pose composed by class (``end_pose``), when it arrives
    (``subject_arrival``), and the pass that ends on it (``subject_stops``).
    The pass opens at the far end, else at the near end when only that sweep
    shows every located person and ``must_show`` region (judged at ``hz``,
    the master rate), else it sweeps both ends (``need_whole``, as for a
    person the ledger has not located). ``whole`` (founder ruling, option
    (c)): held on the upper-weighted fill when the fill shows at least
    ``whole_hold_min_shown`` of the picture and everyone and everything that
    must be seen; else one sweep end to end (``whole_sweep``); either way its
    breath is a drift inside the fill, never a push. ``hold_on`` (boxes)
    holds the covering pass on each of them. ``no_zoom`` keeps every stop at
    z 1 (drift only). ``avoid`` (A49): passed straight to ``end_pose``, to
    steer the subject's stop clear of an active text zone when it can.
    Returns (stops, info) for the journal and the lints."""
    fpt = shot.get("focus") if focus is None else focus
    subj = resolve_subject(roi, fpt, declared_whole=declared_whole)
    # A49: a dissolve carries the move across the cut, the same as a match: "prev" opening (``start``)
    continues = (shot.get("transition_in") or {}).get("type") == "dissolve"
    record = is_record(item)
    facing = subject_facing(subj, persons)
    no_zoom = shot.get("no_zoom") is True
    zlim = max(1.0, zmax)
    people_kind = subj.get("kind") in PERSON_KINDS or subj.get("kind") == "group"
    if people_kind:
        zlim = min(zlim, face_cap_of(persons))
    z_min = None
    if detail and not no_zoom and subj["box"] is not None:
        # A54 (EXPLAIN): the subject's stop is a real DETAIL, a window showing at most CINE detail_share of the
        # picture, as deep as the softness cap (and the face cap) allows; measured, never promised
        z_min = min(zlim, detail_z(size, aspect))
    pose = end_pose(subj, size, aspect, zlim, record=record, facing=facing, no_zoom=no_zoom, avoid=avoid, z_min=z_min)
    framed = framed_persons(pose, persons, size, aspect) if persons else []
    if framed and pose["z"] > face_cap_of(framed) + EPS:
        cap = face_cap_of(framed)
        pose = end_pose(subj, size, aspect, cap, record=record, facing=facing, no_zoom=no_zoom,
                        avoid=avoid, z_min=None if z_min is None else min(z_min, cap))
    whole = subj["src"] == "whole"
    settle_s = settle_for(subj)
    arrive, sp, why = subject_arrival(shot, item, subj, persons, words, t0, dur, settle_s)
    seeing = must_see(item)
    waypoints = [dict(settle({"z": 1.0, "x": (b[0] + b[2]) / 2.0, "y": (b[1] + b[3]) / 2.0}, size, aspect),
                      _hold=CINE["waypoint_hold_s"]) for b in hold_on]
    if waypoints:
        need_whole = True
    mode = None
    aimed = None
    if whole:
        iw, ih = float(size[0]), float(size[1])
        fw, fh = fill_window(size, aspect)
        mode = "hold"
        fill_share_low = fw * fh / (iw * ih) < CINE["whole_hold_min_shown"] - 1e-9
        if need_whole:
            mode = "sweep"
        elif fill_share_low:
            # A49 (ruling 2): clearing a must_show box of an active text zone outranks the fill-share doctrine
            # alone (never a truth requirement like need_whole above); `pose` is already end_pose's avoid-aware
            # whole_pose, so a static hold that already cleared it wins over the (unsteered) sweep
            mode = "sweep" if not (avoid and pose.get("avoid_clear")) else "hold"
        elif seeing:
            win = window(size, aspect, pose["z"], pose["x"], pose["y"])
            if not people_check([win], seeing, size)["ok"]:
                aimed = (None if match_screen is not None else
                         aimed_breath(size, aspect, [q["box"] for q in seeing["boxes"]], record,
                                      aerial=item.get("aerial") is True, avoid=avoid))
                mode = "sweep" if aimed is None else "hold"
        sw = (whole_sweep(size, aspect, record, toward=shot.get("_end_toward"), aerial=item.get("aerial") is True)
              if mode == "sweep" else None)
        if sw is not None:
            pose = dict(sw[1])
            arrive = dur                      # the sweep spends the shot, settled before the cut
        else:
            mode = "hold"
    pose.update(placed="engine", breath=True,
                **{"from": f"A47: the subject ({subj['src']}{', swept' if mode == 'sweep' else ''})"})
    if avoid:
        pose["avoid"] = avoid       # A49: the hold's own creep (build()) steers its breath clear of it too
    if subj["src"] == "subject":
        pose["roi"] = "subject"
    if whole:
        # the whole picture's breath is a drift inside the fill, never a push; only a picture of the frame's own
        # shape, where a drift has no room, breathes in, and never past what keeps everyone and must_show whole
        pose["fit_zmax"] = pose["z"]
        if long_axis(size, aspect) is None and not no_zoom:
            caps = [fit_zmax(q["box"], pose, size, aspect) for q in (seeing or {}).get("boxes", [])]
            pose["fit_zmax"] = max(pose["z"], min([TOUR["whole_creep_max"], *caps]))
    else:
        keep = [tuple(subj["box"])]
        if people_kind:
            a0, b0, a1, b1 = window(size, aspect, pose["z"], pose["x"], pose["y"])
            win = (a0 / size[0], b0 / size[1], a1 / size[0], b1 / size[1])
            keep += [tuple(q["box"]) for q in persons if _inside_share(q["box"], win) >= 1.0 - 1e-6]
            pose["keep_strict"] = True
        pose["keep"] = tuple(keep)
        if not no_zoom:
            pose["fit_zmax"] = max(pose["z"], fit_zmax(subj["box"], pose, size, aspect))
    if sp is not None:
        pose.update(_anchor_fields(sp, t0), at=sp["words"][0]["w"] if len(sp["words"]) == 1 else
                    " ".join(w["w"] for w in sp["words"]))
    start, match_err = None, None
    if match_screen is not None:
        start, match_err = match_start(subject_point(subj, pose), match_screen, size, aspect,
                                       zs=(1.0,) if no_zoom else (1.0, pose["z"]))
        start = dict(start, placed="engine", match="prev")
    opens = None
    if whole and aimed is not None and start is None and not waypoints:
        # A48: the breath aimed between must_show regions (or located people) no one window holds together: it
        # opens on the one read first and ends with the other, a drift at z 1 eased over the whole shot
        first = dict(pose, **aimed[0], t=0.0, breath=False)
        first["from"] = "A47: the subject (whole, the breath aimed at what must be seen)"
        last = dict(pose, **aimed[1], t=dur, breath=False)
        last["from"] = first["from"]
        stops, timing = [first, last], {"arrive_s": 0.0, "why": "whole: held from the cut, its one breath a drift "
                                        "aimed so every must_show region and located person is whole at some point"}
    elif whole and mode == "hold" and start is None and not waypoints:
        stops, timing = [dict(pose, t=0.0)], {"arrive_s": 0.0, "why": "whole: held from the cut, one breath (a "
                                              "drift) and no other move"}
    elif whole and mode == "sweep":
        sweep_whole = True
        if start is not None:
            # founder ruling (c): one sweep, never back. A match opens it, so it runs from the opening to the end
            # farther from it, the ruling's end when that is the farther one; that shows the whole picture only
            # when the opening is at the other end. When A7 needs the whole and it is not, the match gives way
            ax = long_axis(size, aspect)
            ends = [settle({"z": 1.0, "x": 0.5, "y": 0.5, ax: v}, size, aspect) for v in (0.0, 1.0)]
            s0 = settle(start, size, aspect)
            far = max(ends, key=lambda e: abs(e[ax] - s0[ax]))
            near = min(ends, key=lambda e: abs(e[ax] - s0[ax]))
            from_end = abs(s0[ax] - near[ax]) * (size[0] if ax == "x" else size[1]) <= 0.5 and s0["z"] <= 1.0 + EPS
            if need_whole and not from_end:
                start, match_err, opens = None, None, "the match gives way: A7 needs the whole picture swept"
            else:
                pose.update(x=far["x"], y=far["y"], z=far["z"])
                sweep_whole = False
        stops, timing = subject_stops(size, aspect, dur, pose, arrive=arrive, settle_s=settle_s,
                                      need_whole=sweep_whole, start=start, breath=True, waypoints=waypoints, hz=hz,
                                      continues=continues)
        timing["why"] = "whole: one sweep end to end, then a drift" if sweep_whole else (
            "whole: one sweep from the match opening to the farther end, then a drift")
    else:
        stops = timing = None
        # A51: a located face under a live text zone is steered like a must_show region; the opening is one more
        # freedom the pass already has (far end or near end), so a far-end sweep that carries a face under the
        # text while the near end's does not opens at the near end (the smaller move), never at the cost of a
        # person or a must_show region
        # A52: each opening is first searched along the travel as whole_pose searches it (``open_avoid``), so a
        # must_show box or a face under text already up is minimised from the first frame; the unsteered end
        # follows, so steering never costs a person or a must_show region
        face_av = [a for a in avoid or [] if is_face_avoid(a)]
        tries = (False, True) if not need_whole and start is None and (seeing or face_av) else (False,)
        steers = (True, False) if avoid and not need_whole and start is None else (False,)
        cands = []
        for near, steer in [(n, st) for n in tries for st in steers]:
            st_, tm_ = subject_stops(size, aspect, dur, pose, arrive=arrive, settle_s=settle_s,
                                     need_whole=need_whole, start=start, breath=True, from_near=near,
                                     waypoints=waypoints, hz=hz, continues=continues,
                                     open_avoid=avoid if steer else None)
            if not (seeing or face_av) or need_whole:
                cands.append((st_, tm_, near, True, True))
                break
            tl = build(st_, dur, size, aspect, zmax, no_zoom=no_zoom)
            wins = windows_of(tl, hz)
            cov = not seeing or people_check(wins, seeing, size)["ok"]
            clear = not face_av or all(avoid_overlap(size, w, face_av) < CINE["under_text_share"] - 1e-9
                                       for w in wins)
            cands.append((st_, tm_, near, cov, clear))
            if cov and clear:
                break
        pick = (next((c for c in cands if c[3] and c[4]), None) or next((c for c in cands if c[3]), None))
        if pick is not None:
            stops, timing, near = pick[0], pick[1], pick[2]
            if near:
                opens = ("the near end: the far end's sweep would leave a person or a must_show region unseen"
                         if not any(c[3] for c in cands if not c[2]) else
                         "the near end: the far end's sweep would carry a face under live text (A51)")
        else:
            # A47 and A7: no single sweep ending on the subject shows every located person and must_show region
            need_whole = True
            stops, timing = subject_stops(size, aspect, dur, pose, arrive=arrive, settle_s=settle_s,
                                          need_whole=True, start=start, breath=True, waypoints=waypoints, hz=hz,
                                          continues=continues)
            opens = "both ends: no single sweep ending on the subject shows every person and must_show region"
    if opens:
        timing["opens"] = opens
    timing.setdefault("anchor", why)
    for st in stops:
        st.setdefault("placed", "engine")
    info = {"src": subj["src"], "kind": subj["kind"], "box": None if subj["box"] is None else
            [round(v, 4) for v in subj["box"]], "compose": "centred" if record else "golden", "record": record,
            "facing": facing, "no_zoom": no_zoom, "settle_s": settle_s, "need_whole": need_whole,
            "whole_mode": mode, "timing": timing, "match_error": None if match_err is None else round(match_err, 4),
            # a whole still that sweeps toward the next shot's subject hands on that point's screen position
            "point": (tuple(shot["_end_toward"]) if whole and mode == "sweep" and shot.get("_end_toward") else
                      subject_point(subj, pose)), "subj": subj, "held_on": len(waypoints),
            "focus_ignored": bool(declared_whole and _focus_point(fpt) is not None),
            "avoid_clear": pose.get("avoid_clear")}
    return stops, info


# --------------------------------------------------------------------------
# Stops into a timeline
# --------------------------------------------------------------------------


def parse_path(path, dur: float, words: list[dict], t0: float, roi_by_name: dict, size, aspect: float,
               zmax: float) -> tuple[list[dict], list[str]]:
    """A screenplay's ``camera: [...]`` as stops in shot seconds, and the
    problems with it (the ``tour-path`` and ``tour-anchor`` lints). A stop is
    {t | at [, line], x, y, z [, hold]} or {t | at, roi}; ``z`` under 1 is
    refused (A41: never below the fill)."""
    probs: list[str] = []
    stops: list[dict] = []
    if not isinstance(path, list) or not path:
        return [], ["camera must be a list of stops, at least one"]
    for k, raw in enumerate(path):
        if not isinstance(raw, dict):
            probs.append(f"stop {k}: not an object")
            continue
        st = {"from": f"stop {k}", "placed": "author"}
        if raw.get("roi") is not None:
            r = roi_by_name.get(raw["roi"])
            if r is None or roi_box(r) is None:
                probs.append(f"stop {k}: roi {raw['roi']!r} is not a located region of the ledger item")
                continue
            st.update(roi_stop(r, size, aspect, zmax), roi=raw["roi"])
        for key in ("x", "y", "z"):
            if key in raw:
                v = raw[key]
                if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
                    probs.append(f"stop {k}: {key} must be a finite number")
                    continue
                st[key] = float(v)
                if key == "z":
                    st["z_authored"] = True       # A43: a written depth is judged as written, never capped quietly
        if raw.get("match") is not None:
            st["match"] = raw["match"]
        if raw.get("scale") is not None:
            st["scale"] = raw["scale"]
        st.setdefault("x", 0.5)
        st.setdefault("y", 0.5)
        st.setdefault("z", 1.0)
        if not (0.0 <= st["x"] <= 1.0 and 0.0 <= st["y"] <= 1.0):
            probs.append(f"stop {k}: x and y are 0 to 1 in the picture")
        if st["z"] < 1.0 - EPS:
            probs.append(f"stop {k}: z {st['z']:g} is below the fill (z >= 1, A41)")
            st["z"] = 1.0                     # drawn at the fill; the lint refuses the path as written
        if "t" in raw and "at" in raw:
            probs.append(f"stop {k}: t or at, not both")
        if "at" in raw:
            sp = anchor_span(raw["at"], words, line=raw.get("line"), t0=t0)
            if sp is None:
                probs.append(f"anchor: stop {k}: at {raw['at']!r} is not spoken in this shot's narration")
                continue
            st["t"], st["at"] = sp["t"] - t0, raw["at"]
            st.update(_anchor_fields(sp, t0))
            if not (-EPS <= st["t"] <= dur + EPS):
                probs.append(f"anchor: stop {k}: at {raw['at']!r} is spoken at {st['t']:.2f} s, outside the shot")
                continue
            lead = raw.get("lead_s", 0.0)
            if not isinstance(lead, (int, float)) or isinstance(lead, bool) or not math.isfinite(lead) or lead < 0:
                probs.append(f"stop {k}: lead_s is seconds before the word, 0 or more")
                lead = 0.0
            # A43: arrive lead_s before the word; a lead that reaches back past the cut arrives on the cut
            st["t"] = max(0.0, st["t"] - float(lead))
        elif "t" in raw:
            if not isinstance(raw["t"], (int, float)) or isinstance(raw["t"], bool) or not math.isfinite(raw["t"]):
                probs.append(f"stop {k}: t must be a finite number")
                continue
            st["t"] = float(raw["t"])
        elif k == 0:
            st["t"] = 0.0
        else:
            probs.append(f"stop {k}: needs t (shot seconds) or at (a narration word)")
            continue
        if not (-EPS <= st["t"] <= dur + EPS):
            probs.append(f"stop {k}: t {st['t']:g} is outside the shot (0 to {dur:g} s)")
        h = raw.get("hold", 0.0)
        if not isinstance(h, (int, float)) or isinstance(h, bool) or not math.isfinite(h) or h < 0:
            probs.append(f"stop {k}: hold is seconds, 0 or more")
            h = 0.0
        st["hold"] = float(h)
        st["t"] = min(max(st["t"], 0.0), dur)
        stops.append(st)
    for a, b in zip(stops, stops[1:]):
        if abs(b["t"] - a["t"]) <= EPS and not _same(a, b):
            probs.append(f"{b['from']}: at the same moment as the stop before ({b['t']:.2f} s): the camera would jump")
        elif b["t"] < a["t"] + a.get("hold", 0.0) - EPS:
            probs.append(f"{b['from']}: t {b['t']:.2f} comes before the previous stop has left ({a['t'] + a.get('hold', 0.0):.2f})")
    return stops, probs


def _same(a: dict, b: dict) -> bool:
    return abs(math.log(b["z"] / a["z"])) < 1e-6 and abs(a["x"] - b["x"]) < 1e-6 and abs(a["y"] - b["y"]) < 1e-6


def creep(p: dict, h: float, size, aspect: float, zmax: float, *, prefer=None, no_zoom: bool = False,
          breath: bool = False, keep=None, keep_strict: bool = False,
          avoid: list[tuple] | None = None) -> tuple[dict, str]:
    """Where a stop held ``h`` seconds has crept to, and how: a push of
    ``creep_scale_per_s`` while under the cap, else a pull while above the
    fill, else a slow drift along the axis with room (``prefer`` is the last
    move's direction, (dx, dy)). ``no_zoom`` (a shot that must not be zoomed)
    drifts only. ``held`` when nothing can move (a 16:9 picture at the cap).
    ``breath`` (A47, the hold on the subject): one breath over the hold,
    never more than ``whole_creep_max`` of the window in all (1.5% a second
    on a short hold, 0.1 to 0.15% a second on a 40 to 60 s one), a push or a
    drift and never a pull, so it runs one way. ``keep`` (boxes, picture
    fractions: the subject the stop landed on, and for a person or a group
    every located person it frames) is never drifted out of a window it fits
    inside: the drift takes the first direction that keeps them all. When
    none does, a ``keep_strict`` stop (people) holds; any other drifts a few
    per cent past its subject's edge rather than freeze (no dead holds).

    ``avoid`` (A49): a few other directions are tried too (still honouring
    ``keep``/``keep_strict``), plus staying put (no breath at all, for this
    hold); the one with the least overlap wins, preferring the default
    direction's own choice among those that already read clear of the lint's
    warn share (``avoid_key``: the reviewer's own ruling is that ducking a
    refusal while still warning has moved the wrong way), so the engine
    never refuses itself here (ruling 2) and never moves further than it
    has to."""
    base = _creep_step(p, h, size, aspect, zmax, prefer=prefer, no_zoom=no_zoom, breath=breath, keep=keep,
                       keep_strict=keep_strict)
    if not avoid:
        return base

    def win_of(q: dict) -> tuple:
        return window(size, aspect, q["z"], q["x"], q["y"])

    candidates = [(base, 0.0)]
    for alt in ((1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0)):
        q, how = _creep_step(p, h, size, aspect, zmax, prefer=alt, no_zoom=no_zoom, breath=breath, keep=keep,
                             keep_strict=keep_strict)
        candidates.append(((q, how), 1.0))
    candidates.append(((dict(p), "held"), 2.0))        # staying put: the furthest from the plan, tried last
    best, best_key = None, None
    for (q, how), distance in candidates:
        win = win_of(q)
        ov = avoid_overlap(size, win, avoid)
        key = avoid_key(ov, distance, fits=avoid_fits(size, win, avoid))
        if best_key is None or key < best_key:
            best, best_key = (q, how), key
    return best


def _creep_step(p: dict, h: float, size, aspect: float, zmax: float, *, prefer=None, no_zoom: bool = False,
                breath: bool = False, keep=None, keep_strict: bool = False) -> tuple[dict, str]:
    """``creep``'s own search, with no ``avoid`` (its default direction)."""
    c = TOUR["creep_scale_per_s"] * h
    cd = TOUR["creep_drift_per_s"] * h
    if breath:
        c, cd = min(c, TOUR["whole_creep_max"] - 1.0), min(cd, TOUR["whole_creep_max"] - 1.0)
    if not no_zoom and p["z"] * (1.0 + c) <= zmax + EPS:
        return dict(p, z=p["z"] * (1.0 + c)), "push"
    if not no_zoom and not breath and p["z"] / (1.0 + c) >= 1.0 - EPS:
        return dict(p, z=p["z"] / (1.0 + c)), "pull"
    iw, ih = float(size[0]), float(size[1])
    x0, y0, x1, y1 = window(size, aspect, p["z"], p["x"], p["y"])
    room = {"x": (x0, iw - x1), "y": (y0, ih - y1)}             # room before and after, picture px
    d = {"x": cd * (x1 - x0), "y": cd * (y1 - y0)}
    order = sorted(("x", "y"), key=lambda a: -max(room[a]))
    if prefer is not None:
        px, py = prefer
        order = sorted(("x", "y"), key=lambda a: -abs(px if a == "x" else py)) if (abs(px) + abs(py)) > EPS else order
    if isinstance(keep, tuple) and keep and not isinstance(keep[0], (tuple, list)):
        keep = [keep]
    for ax in order:
        lo, hi = room[ax]
        if max(lo, hi) < 0.5:
            continue
        sign = 1.0 if hi >= lo else -1.0
        if prefer is not None:
            v = prefer[0] if ax == "x" else prefer[1]
            if abs(v) > EPS and (hi if v > 0 else lo) >= 0.5:
                sign = 1.0 if v > 0 else -1.0
        n = iw if ax == "x" else ih
        for sg in ((sign, -sign) if keep else (sign,)):
            step = min(d[ax], hi if sg > 0 else lo)
            for kb in keep or []:
                k0, k1 = (kb[0] * n, kb[2] * n) if ax == "x" else (kb[1] * n, kb[3] * n)
                w0, w1 = (x0, x1) if ax == "x" else (y0, y1)
                if k1 - k0 < (w1 - w0) - 1.0 and k0 >= w0 - 0.5 and k1 <= w1 + 0.5:
                    step = min(step, (k0 - w0) if sg > 0 else (w1 - k1))
            if step >= 0.5:
                return dict(p, **{ax: p[ax] + sg * step / n}), "drift"
    if keep and not keep_strict:
        # a subject that fills its window leaves no room to drift inside it: a frozen frame is worse (no dead
        # holds, founder 2026-10-17), so the breath drifts and the subject's edge goes by a few per cent at most
        return _creep_step(p, h, size, aspect, zmax, prefer=prefer, no_zoom=no_zoom, breath=breath)
    return dict(p), "held"


def build(stops: list[dict], dur: float, size, aspect: float, zmax: float, *, no_zoom: bool = False) -> dict:
    """The stops as a timeline of segments {t0, t1, a, b, kind}: ``move``
    between stops on the rostrum curve, ``creep`` on a hold longer than
    ``hold_creep_after_s`` (before the first stop, after a stop's ``hold``, or
    to the shot's end), ``hold`` for a short one. Each stop is settled inside
    the picture first."""
    if not stops:
        raise TourError("a path needs at least one stop")
    for a, b in zip(stops, stops[1:]):
        if float(b["t"]) < float(a["t"]) - 1e-6 and not (authored(a) or authored(b)):
            # an engine bug, never a silent path (a written path out of order is tour-path's to refuse)
            raise TourError(f"stop times go back: {b.get('from')} at {float(b['t']):.3f} s after "
                            f"{a.get('from')} at {float(a['t']):.3f} s")
    pts = [dict(settle(s, size, aspect), t=float(s["t"]), hold=float(s.get("hold", 0.0))) for s in stops]
    after = TOUR["hold_creep_after_s"]
    segs: list[dict] = []
    held: list[dict] = []

    def hold(t0, t1, p, *, into: bool = False, prefer=None, force: bool = False):
        """A hold from t0 to t1 at p (or, ``into``, a hold that must end on p). A54: a hold that opens the
        still or runs into the cut always creeps, however short (never from rest, never a dead stop)."""
        if t1 - t0 <= EPS:
            return p
        edge = force or t0 <= EPS or t1 >= dur - EPS        # A54: a framing beside a hard cut drifts too
        if t1 - t0 <= after + EPS and not edge:
            segs.append({"t0": t0, "t1": t1, "a": p, "b": p, "kind": "hold"})
            return p
        # A43: a stop that frames a face or a person creeps under the face cap, not only the softness cap
        zm = min(zmax, float(p.get("face_cap", math.inf)), float(p.get("fit_zmax", math.inf)))
        if p["z"] > zm + EPS:
            zm = p["z"]                       # an authored depth past the cap: the lint refuses it; never pushed further
        q, how = creep(p, t1 - t0, size, aspect, zm, prefer=prefer, no_zoom=no_zoom, breath=bool(p.get("breath")),
                       keep=p.get("keep"), keep_strict=bool(p.get("keep_strict")), avoid=p.get("avoid"))
        if how == "held":
            held.append({"t0": round(t0, 3), "t1": round(t1, 3)})
        q = settle(q, size, aspect)
        a, b = (q, p) if into else (p, q)
        segs.append({"t0": t0, "t1": t1, "a": a, "b": b, "kind": "creep" if how != "held" else "hold", "how": how})
        return b

    hold(0.0, pts[0]["t"], pts[0], into=True)
    last_dir = None
    cuts: list[float] = []
    for i, p in enumerate(pts):
        nxt = pts[i + 1] if i + 1 < len(pts) else None
        leave = min(p["t"] + p["hold"], nxt["t"] if nxt else dur)
        by_cut = bool(p.get("cut") or (nxt is not None and nxt.get("cut")))
        if i == 0 and p["t"] <= EPS and nxt is not None and leave > EPS and not _same(p, nxt) and not by_cut:
            # A54: the still's opening hold leaves the cut already moving, at the creep's speed along its first
            # leg (so it never turns back, and a sweep the whole picture needs keeps its depth)
            k = min(0.5, M.creep_rate(*_leg_dist(p, nxt, size, aspect)) * leave)
            q = dict(p, z=p["z"] * (nxt["z"] / p["z"]) ** k, x=p["x"] + (nxt["x"] - p["x"]) * k,
                     y=p["y"] + (nxt["y"] - p["y"]) * k)
            segs.append({"t0": 0.0, "t1": leave, "a": p, "b": q, "kind": "creep", "how": "lead"})
            pos = q
        else:
            pos = hold(p["t"], leave, p, prefer=last_dir, force=by_cut) if leave > p["t"] + EPS else p
        if nxt is None:
            if dur - leave > EPS:
                hold(leave, dur, pos, prefer=last_dir)
            break
        if nxt.get("cut"):
            # A54 (classic coverage): a hard cut to the next framing of the same picture, inside the shot; the
            # framing before it drifts up to the cut, and the next enters drifting
            if nxt["t"] - leave > EPS:
                hold(leave, nxt["t"], pos, prefer=last_dir, force=True)
            cuts.append(round(float(nxt["t"]), 6))
            continue
        if nxt["t"] - leave <= EPS:
            continue
        if _same(pos, nxt) or _same(p, nxt):
            # the same framing again: one long hold (it creeps), and the next stop is where the creep has reached
            q = hold(leave, nxt["t"], pos, prefer=last_dir)
            pts[i + 1] = dict(nxt, z=q["z"], x=q["x"], y=q["y"])
        else:
            segs.append({"t0": leave, "t1": nxt["t"], "a": pos, "b": nxt, "kind": "move"})
            last_dir = (nxt["x"] - pos["x"], nxt["y"] - pos["y"])
    if not segs:
        segs.append({"t0": 0.0, "t1": max(dur, EPS), "a": pts[0], "b": pts[0], "kind": "hold"})
    # A54 (entering mid-move): the first segment enters at the creep's speed, the last leaves at it, and a leg
    # next to a creep slows to it rather than stopping
    M.enter_moving(segs, lambda a, b: _leg_dist(a, b, size, aspect))
    zs = [s["a"]["z"] for s in segs] + [s["b"]["z"] for s in segs]
    return {"segments": segs, "stops": pts, "dur": dur, "size": [float(size[0]), float(size[1])], "aspect": aspect,
            "z_max": max(zs), "z_min": min(zs), "held": held, "zmax_allowed": zmax, "cuts": cuts}


def at(tl: dict, t: float) -> dict:
    """The picture-space framing {z, x, y} at shot time t: the rostrum curve
    over each segment, z geometric so its speed reads even."""
    segs = tl["segments"]
    if t <= segs[0]["t0"]:
        g = segs[0]
    elif t >= segs[-1]["t1"]:
        g = segs[-1]
        t = g["t1"]
    else:
        g = next((s for s in segs if s["t0"] - EPS <= t <= s["t1"] + EPS), segs[-1])
    a, b = g["a"], g["b"]
    e = M.eased(g, t)
    return {"z": a["z"] * (b["z"] / a["z"]) ** e, "x": a["x"] + (b["x"] - a["x"]) * e,
            "y": a["y"] + (b["y"] - a["y"]) * e}


def samples(tl: dict, hz: float | None = None) -> list[tuple[float, dict]]:
    """The path sampled at ``hz`` (``TOUR['sample_hz']``) and at every segment's ends."""
    hz = hz or TOUR["sample_hz"]
    dur = tl["dur"]
    ts = {round(k / hz, 6) for k in range(int(math.floor(dur * hz)) + 1)}
    for g in tl["segments"]:
        ts.add(round(g["t0"], 6))
        ts.add(round(min(g["t1"], dur), 6))
    return [(t, at(tl, t)) for t in sorted(ts) if t <= dur + EPS]


# --------------------------------------------------------------------------
# A43: truth for authored and automatic framing (founder ruling 2, 2026-10-17)
# --------------------------------------------------------------------------

CINE = M.CINE
CLASSES = ("person", "crowd", "place", "document", "map", "painting", "object")
KINDS = ("face", "person", "group", "text", "object", "place")
PERSON_KINDS = ("face", "person")
FACINGS = ("left", "right", "camera", "away")
SOURCES = ("auto", "human")
SCALES = ("whole", "field", "detail")
BOX = ("x", "y", "w", "h")
PEOPLE_KEYS = set(BOX) | {"name", "facing", "source", "confidence", "model", "face",   # face: A51
               "minor", "age"}   # A54: the face cap keeps z 1.3 for a minor
ROI_KEYS = set(BOX) | {"name", "kind", "facing", "source", "confidence", "model", "cue", "must_show", "person",
                       "lines",     # A50, a text region's line count (its reading pace)
                       "order",     # A54, SURVEY's painter reading order (ticket #10)
                       "minor", "age"}   # A54: the face cap keeps z 1.3 for a minor
# A54: the chooser's moves (``moves.py``), which a screenplay may name itself (``move``, ``move_variant``)
MOVE_NAMES = ("WHOLE", "PAN", "PORTRAIT", "SURVEY", "READ", "EXPLAIN", "REVEAL", "CUTIN")
MOVE_VARIANTS = ("far", "near", "reveal", "explain", "forward", "reverse")
STOP_KEYS = {"t", "at", "line", "x", "y", "z", "hold", "roi", "scale", "lead_s", "match"}
# the rulebook's own names for what it finds (the schema): never a person's name
GENERIC_NAME = re.compile(r"(subject|(face|person|group|text|object|place)-\d+)$")


def source_of(e: dict) -> str:
    """``auto`` or ``human``. An entry with no ``source`` was written by a
    person (A41's hand authoring), so it is human."""
    return "auto" if e.get("source") == "auto" else "human"


def is_person_region(r: dict) -> bool:
    """A region of interest that marks a person: ``kind: face|person``, or
    A41's ``person: true``."""
    return r.get("kind") in PERSON_KINDS or r.get("person") is True


def effective_regions(item: dict) -> dict:
    """The ledger's people and regions as the camera may use them (founder
    ruling 2): ``source: human`` wins over ``source: auto`` for the same name,
    and a machine box under ``CINE['auto_confidence_floor']`` is ignored for
    framing. An ignored box that marks a person still counts as a person the
    ledger has not located (``unlocated``), so the guards ask for the whole
    picture: a miss degrades toward the whole, never crops anyone out.
    Returns {people, roi, unlocated, ignored}; ``people`` is the ledger's
    value unchanged unless it is a list."""
    floor = CINE["auto_confidence_floor"]
    pe = item.get("people", None)
    roi = [r for r in (item.get("roi") or []) if isinstance(r, dict)] if isinstance(item.get("roi"), list) else []
    plist = pe if isinstance(pe, list) else []
    human = {e.get("name") for e in [*roi, *[p for p in plist if isinstance(p, dict)]]
             if source_of(e) == "human" and e.get("name") is not None}
    ignored, unlocated = [], 0

    def keep(e: dict, where: str, person: bool) -> bool:
        nonlocal unlocated
        if source_of(e) == "human":
            return True
        if e.get("name") is not None and e.get("name") in human:
            ignored.append({"in": where, "name": e.get("name"), "why": "a human entry of the same name wins"})
            return False
        c = e.get("confidence")
        if not isinstance(c, (int, float)) or isinstance(c, bool) or not math.isfinite(c) or c < floor:
            ignored.append({"in": where, "name": e.get("name"), "confidence": c, "floor": floor,
                            "why": "below the confidence floor: ignored for framing"})
            if person:
                unlocated += 1
            return False
        return True

    out_people = pe
    if isinstance(pe, list):
        out_people = [p for p in pe if not isinstance(p, dict) or keep(p, "people", True)]
    out_roi = [r for r in roi if keep(r, "roi", is_person_region(r))]
    return {"people": out_people, "roi": out_roi, "unlocated": unlocated, "ignored": ignored}


def person_regions(item: dict) -> list[dict]:
    """Every located person the camera may frame: the effective ``people``
    boxes and the ``kind: face|person`` regions, {name, kind, box, src}."""
    eff = effective_regions(item)
    out = []
    for p in eff["people"] if isinstance(eff["people"], list) else []:
        if isinstance(p, dict) and roi_box(p) is not None:
            out.append({"name": p.get("name"), "kind": "person", "box": roi_box(p), "src": "people", "entry": p})
    for r in eff["roi"]:
        if is_person_region(r) and roi_box(r) is not None:
            out.append({"name": r.get("name"), "kind": r.get("kind") or "person", "box": roi_box(r), "src": "roi",
                        "entry": r})
    return out


def _area(b) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _inside_share(box, win) -> float:
    """The share of ``box``'s area inside ``win`` (both x0, y0, x1, y1)."""
    a = _area(box)
    if a <= 0:
        return 1.0 if win[0] <= box[0] <= win[2] and win[1] <= box[1] <= win[3] else 0.0
    i = (max(box[0], win[0]), max(box[1], win[1]), min(box[2], win[2]), min(box[3], win[3]))
    return _area(i) / a


def located_persons(persons: list[dict]) -> int:
    """How many people the boxes hold: a box mostly inside another (a face in
    its figure, ``CINE['nest_share']``) is the same person."""
    bs = sorted((p["box"] for p in persons), key=_area, reverse=True)
    kept: list = []
    for b in bs:
        if not any(_inside_share(b, k) >= CINE["nest_share"] for k in kept):
            kept.append(b)
    return len(kept)


# A54 (founder ruling 2026-10-18, the face cap): z 1.3 stays the cap for every face, except one person the
# caption binds (A43) or one located adult the item's own text names in a public role (this list, versioned:
# never inferred from the picture), who may go to the DETAIL limit (``detail_limit_z``) inside the softness cap
PUBLIC_ROLE_WORDS_VERSION = 1
PUBLIC_ROLE_WORDS = ("firefighter", "firefighters", "fireman", "firemen", "officer", "officers", "police",
                     "policeman", "policemen", "policewoman", "official", "officials", "president", "mayor",
                     "senator", "governor", "soldier", "soldiers", "crew", "guardsman", "guardsmen", "trooper",
                     "troopers", "paramedic", "paramedics", "rescuer", "rescuers")
PUBLIC_ROLE_FIELDS = ("caption", "title", "nara_title", "people", "_people_words", "seen")


def face_cap_of(persons: list[dict]) -> float:
    """The face cap over a set of located persons: the lowest of their own
    caps (``lift_face_caps`` sets ``cap``; z 1.3 for anyone it did not lift)."""
    return min([float(q.get("cap", CINE["face_zmax"])) for q in persons] or [CINE["face_zmax"]])


def detail_z(size, aspect: float) -> float:
    """The zoom at which the window shows ``CINE['detail_share']`` (0.4) of
    the picture: the DETAIL band's own edge (doctrine 2.2)."""
    fw, fh = fill_window(size, aspect)
    return max(1.0, math.sqrt(fw * fh / (float(size[0]) * float(size[1])) / CINE["detail_share"]))


def detail_limit_z(size, aspect: float, zcap: float) -> float:
    """A54's lifted face cap: the zoom at which the window still shows
    ``CINE['face_detail_share']`` (0.25) of the picture, inside the softness
    cap ``zcap``, and never under the plain face cap."""
    fw, fh = fill_window(size, aspect)
    z = math.sqrt(fw * fh / (float(size[0]) * float(size[1])) / CINE["face_detail_share"])
    return max(CINE["face_zmax"], min(z, max(1.0, zcap)))


def public_role(item: dict) -> str | None:
    """The public-role word the item's own text gives (``PUBLIC_ROLE_FIELDS``,
    whole words, any case), or None. Read from the ledger's words only,
    never from the picture (founder guard, 2026-10-18)."""
    have: set[str] = set()
    for f in PUBLIC_ROLE_FIELDS:
        v = item.get(f)
        if isinstance(v, list):
            v = " ".join(str(e.get("name") or "") if isinstance(e, dict) else str(e) for e in v)
        if isinstance(v, str):
            have |= set(_norm_words(v))
    return next((w for w in PUBLIC_ROLE_WORDS if w in have), None)


def _is_minor(item: dict, persons: list[dict]) -> bool:
    if item.get("minor") is True:
        return True
    for q in persons:
        e = q.get("entry") or {}
        age = e.get("age")
        if e.get("minor") is True or (isinstance(age, (int, float)) and not isinstance(age, bool) and age < 18):
            return True
    return False


def lift_face_caps(item: dict, persons: list[dict], size, aspect: float, zcap: float, *, no_zoom: bool = False,
                   mode: str | None = None) -> tuple[list[dict], dict]:
    """A54's face cap (founder ruling 2026-10-18; ``CINE['face_detail']``):
    under ``"proposal"`` (the ruling) the one located person of a still may
    go to the DETAIL limit (``detail_limit_z``) when (a) the caption binds
    them by A43's own rule (``binding_check``: exactly one person named and
    located), or (b) the item's own text names a public role
    (``public_role``). Kept at z 1.3: ``"strict"``, a crowd (two or more
    located people), a ``no_zoom`` still, a minor (``minor: true``, or an
    ``age`` under 18), and an item marked ``dignity: true`` (a human's flag,
    never the rulebook's). Returns (persons, each with ``cap``, and info)."""
    mode = mode or CINE["face_detail"]
    base = CINE["face_zmax"]
    out = [dict(q, cap=base) for q in persons]
    info = {"mode": mode, "cap": base, "lifted": None, "why": None}
    n = located_persons(persons)
    kept = ("strict: every face keeps z 1.3" if mode != "proposal" else
            "nobody located" if n == 0 else
            f"a crowd: {n} located people" if n > 1 else
            "no_zoom" if no_zoom else
            "dignity: true" if item.get("dignity") is True else
            "a minor" if _is_minor(item, persons) else None)
    if kept is None:
        bound = None
        names = item.get("caption_names")
        cands = [names[0]] if isinstance(names, list) and len(names) == 1 and isinstance(names[0], str) else []
        cands += [str(q["name"]) for q in persons if q.get("name") and not GENERIC_NAME.match(str(q["name"]))]
        region = next((q.get("entry") for q in persons if q.get("entry")), None)
        for nm in cands:
            if not binding_check(item, nm.split(), region, persons):
                bound = nm
                break
        role = public_role(item)
        if bound is not None or role is not None:
            cap = detail_limit_z(size, aspect, zcap)
            out = [dict(q, cap=cap) for q in out]
            info.update(cap=round(cap, 4), lifted=(f"bound to {bound!r} (A43)" if bound is not None else
                                                    f"a public role in the item's own text: {role!r}"))
            return out, info
        kept = "neither bound to a caption name nor named in a public role by the item's own text"
    info["why"] = kept
    return out, info


def framed_persons(p: dict, persons: list[dict], size, aspect: float) -> list[dict]:
    """The people a framing {z, x, y} frames: at least ``CINE['framed_share']``
    of the box inside its window."""
    iw, ih = float(size[0]), float(size[1])
    x0, y0, x1, y1 = window(size, aspect, p["z"], p["x"], p["y"])
    win = (x0 / iw, y0 / ih, x1 / iw, y1 / ih)
    return [q for q in persons if _inside_share(q["box"], win) >= CINE["framed_share"] - EPS]


def cap_faces(stops: list[dict], persons: list[dict], size, aspect: float) -> list[dict]:
    """``face-cap-live`` in the engine (7.2, A43): every stop whose window
    frames a face or a person creeps under ``CINE['face_zmax']``, and one the
    engine placed (a region's stop, a macro, the default) is pulled back to it.
    A depth the screenplay wrote (``z``) is left as written, for the lint to
    refuse. Returns the stops, each marked ``face_cap`` where it applies."""
    out = []
    for st in stops:
        st = dict(st)
        hit = framed_persons(settle(st, size, aspect), persons, size, aspect) if persons else []
        if hit:
            cap = face_cap_of(hit)
            st["face_cap"] = cap
            st["framed_people"] = [q["name"] for q in hit]
            if st["z"] > cap + EPS and not st.get("z_authored"):
                st["z"], st["capped"] = cap, "face"
                st["framed_people"] = [q["name"] for q in framed_persons(settle(st, size, aspect), persons, size,
                                                                         aspect)] or st["framed_people"]
        out.append(st)
    return out


def face_cap_check(tl: dict, persons: list[dict], hz: float | None = None) -> list[dict]:
    """``face-cap-live`` (A43, blocking): every framing of the path, the
    stops, the holds and creeps on them and the moves between them (sampled,
    ``samples``), that frames a face or a person stays at or under
    ``CINE['face_zmax']``. A face less than half in frame (``framed_share``)
    is not capped: the push is about what is beside it. Returns the framings
    that do not, each with the stops it lies between."""
    if not persons:
        return []
    cap = min(face_cap_of([q]) for q in persons)          # A54: a lifted cap is per person (``lift_face_caps``)
    size, aspect = tl["size"], tl["aspect"]
    pts = [(st["t"], st) for st in tl["stops"]] + list(samples(tl, hz))
    for g in tl["segments"]:
        pts += [(g["t0"], g["a"]), (g["t1"], g["b"])]
    bad, seen_ = [], set()
    for t, p in sorted(pts, key=lambda v: v[0]):
        if p["z"] <= cap + 1e-9:
            continue
        hit = framed_persons(p, persons, size, aspect)
        key = round(t, 3)
        if hit and p["z"] > face_cap_of(hit) + 1e-9 and key not in seen_:
            seen_.add(key)
            bad.append({"t": round(t, 3), "z": round(p["z"], 4), "people": [q["name"] for q in hit],
                        "cap": round(face_cap_of(hit), 4), "stops": _stops_around(tl, t)})
    return bad


def _stops_around(tl: dict, t: float) -> list[int]:
    """The indexes of the stops a moment of the path lies between (the stop
    it holds on, or the two a move joins)."""
    pts = tl["stops"]
    before = [i for i, st in enumerate(pts) if st["t"] <= t + EPS]
    after = [i for i, st in enumerate(pts) if st["t"] >= t - EPS]
    out = []
    if before:
        out.append(before[-1])
    if after and after[0] not in out:
        out.append(after[0])
    return out


def authored(st: dict) -> bool:
    """A stop a person wrote in the screenplay's ``camera`` list. Every other
    stop (the tour resolver's, a preset's, the default's, the rulebook's) was
    placed by the engine, and the engine's own output is never refused: it
    is re-framed (founder ruling 2)."""
    return st.get("placed") == "author"


def enforce_face_cap(stops: list[dict], persons: list[dict], dur: float, size, aspect: float, zmax: float, *,
                     no_zoom: bool = False, hz: float | None = None) -> tuple[list[dict], list[dict]]:
    """The engine's side of ``face-cap-live``: build the path, and where any
    framing of it (a move included) frames a face past the cap, pull the
    engine-placed stops around it back to ``CINE['face_zmax']`` and build
    again. A depth a person wrote is left as written, for the lint. Returns
    (stops, what was pulled back)."""
    pulled = []
    for _ in range(len(stops) + 2):
        tl = build(stops, dur, size, aspect, zmax, no_zoom=no_zoom)
        bad = face_cap_check(tl, persons, hz)        # hz: the film's master rate (A44); None: TOUR sample_hz
        caps: dict[int, float] = {}
        for v in bad:
            for i in v["stops"]:
                caps[i] = min(caps.get(i, math.inf), v["cap"])
        idx = sorted(i for i, c in caps.items()
                     if tl["stops"][i]["z"] > c + EPS and not tl["stops"][i].get("z_authored"))
        if not idx:
            break
        stops = [dict(st) for st in stops]
        for i in idx:
            cap = caps[i]
            stops[i].update(z=cap, face_cap=cap, capped="face")
            pulled.append({"stop": stops[i].get("from"), "t": round(stops[i]["t"], 3),
                           "why": f"a move or a hold on it frames a face or a person past z {cap:g}"})
    return stops, pulled


def _norm_words(text) -> list[str]:
    return [norm_word(t) for t in str(text or "").split() if norm_word(t)]


def _contains(hay: list[str], needle: list[str]) -> bool:
    return bool(needle) and any(hay[i:i + len(needle)] == needle for i in range(len(hay) - len(needle) + 1))


def _same_name(a: list[str], b: list[str]) -> bool:
    """One name holds the other ("Bush" and "President Bush")."""
    return bool(a) and bool(b) and (_contains(a, b) or _contains(b, a))


def names_a_person(spoken: list[str], item: dict, persons: list[dict]) -> bool:
    """Whether an anchor is a person's name: it matches the name or the cue of
    a person the ledger records (not the rulebook's own names: subject,
    person-1, ...), or an entry of the item's ``caption_names``, or, when the
    item states none, a cue its caption gives with a capital. A capital in
    the narration alone never makes a name ("New York", "Pentagon")."""
    cue = [norm_word(w) for w in spoken if norm_word(w)]
    if not cue:
        return False
    for q in persons:
        e = q.get("entry") or {}
        for c in [e.get("name")] + (cue_of(e) if e.get("cue") is not None else []):
            if isinstance(c, str) and not GENERIC_NAME.match(c) and _same_name(_norm_words(c), cue):
                return True
    names = item.get("caption_names")
    if isinstance(names, list):
        return any(_same_name(_norm_words(n), cue) for n in names if isinstance(n, str))
    # no caption_names: a cue the caption itself gives with a capital is taken as a name, so the binding rule (and
    # its check for other capitalised caption words) runs; a crowd still binds no one (stop_person)
    toks = [w.strip(_QUOTES) for w in str(item.get("caption") or item.get("title") or "").split()]
    toks = [w for w in toks if norm_word(w)]
    for i in range(len(toks) - len(cue) + 1):
        if [norm_word(w) for w in toks[i:i + len(cue)]] == cue and toks[i][:1].isupper():
            return True
    return False


_SENTENCE_END = (".", "!", "?", ":", ";")
_QUOTES = "\"'()[]“”‘’,"


def caption_other_names(caption: str, cue: list[str]) -> list[str]:
    """The approximate check, used only when the item states no
    ``caption_names``: the capitalised words of the caption that are not the
    cue and do not open it or a sentence. Any one of them may be another
    person, so the caption is not taken to name exactly one."""
    toks = str(caption or "").split()
    out = []
    for i, tok in enumerate(toks):
        w = tok.strip(_QUOTES)
        if not w or not w[0].isupper() or norm_word(w) in cue or w == "I":
            continue
        if i == 0 or toks[i - 1].rstrip(_QUOTES).endswith(_SENTENCE_END):
            continue
        out.append(w)
    return out


def binding_check(item: dict, spoken: list[str], region: dict | None, persons: list[dict]) -> list[str]:
    """Founder ruling 2's binding rule (A43): a person may be bound to a name
    the narration speaks only when the item's own caption names exactly that
    one person (its ``caption_names`` lists exactly one name and it is the
    spoken one; with no ``caption_names``, the caption, else the title, holds
    the name and no other capitalised word past a sentence's start), exactly
    one person is located and nobody else is in the picture unlocated, no
    second person's name is recorded for it, and, when the person's box is
    the machine's (``source: auto``), it is the rulebook's primary
    ``subject``. Returns what fails (empty when the binding stands)."""
    why = []
    n = located_persons(persons)
    unloc = people_of(item)["unlocated"]
    if n != 1 or unloc:
        why.append(f"the picture holds {n} located person(s) and {unloc} unlocated: a name binds to a face only "
                   "when exactly one person is located and nobody else is in it")
    cue = [norm_word(w) for w in spoken if norm_word(w)]
    names = item.get("caption_names")
    if isinstance(names, list):
        if len(names) != 1 or not _same_name(_norm_words(names[0]), cue):
            why.append(f"caption_names is {names!r}: it must name exactly one person, {' '.join(spoken)!r}")
    else:
        caption = item.get("caption") or item.get("title") or ""
        if not _contains(_norm_words(caption), cue):
            why.append(f"the item's own caption or title ({caption!r}) does not name {' '.join(spoken)!r}")
        others = caption_other_names(caption, cue)
        if others:
            why.append(f"the caption may name someone else too ({', '.join(others)}): state caption_names")
    recorded = {str(q["name"]) for q in persons if q.get("name") and not GENERIC_NAME.match(str(q["name"]))}
    if len(recorded) > 1:
        why.append(f"the ledger records more than one person's name here ({sorted(recorded)})")
    own = region.get("name") if region else None
    if own and not GENERIC_NAME.match(str(own)) and not _same_name(_norm_words(own), cue):
        why.append(f"the region is {own!r}, not {' '.join(spoken)!r}")
    if region is not None and source_of(region) == "auto" and own != "subject":
        why.append(f"a machine box binds a name only as the rulebook's primary subject, not {own!r}")
    if region is not None and source_of(region) == "auto" and not people_words_name(item, cue):
        why.append(f"a machine box binds {' '.join(spoken)!r} only when the ledger's own people words name them "
                   f"(A45; they say {item.get('_people_words')!r})")
    return why


def people_words_name(item: dict, cue: list[str]) -> bool:
    """A45 (schema owner's ruling, 2026-10-17): the ledger's own people
    words (the count the rulebook read, kept as ``_people_words`` when the
    rulebook replaced ``people``; else ``people`` itself) mention
    the name, by any of its words (a title or a surname), whole and
    case-insensitive. "the President" names "President"; "a policeman" does
    not, so a motorcade's caption never binds the President to the
    policeman the detector found."""
    pw = item.get("_people_words", item.get("people"))
    if isinstance(pw, list):
        pw = " ".join(str(p.get("name") or "") if isinstance(p, dict) else str(p) for p in pw)
    if not isinstance(pw, str):
        return False
    have = set(_norm_words(pw))
    return any(w in have for w in cue)


def leave_time(tl: dict, i: int) -> float:
    """When the camera leaves stop ``i`` (shot seconds): the start of the
    first move after it (a hold, a creep or the same framing again keeps it
    there), else the shot's end."""
    t = tl["stops"][i]["t"]
    for g in tl["segments"]:
        if g["kind"] == "move" and g["t0"] >= t - EPS:
            return g["t0"]
    return tl["dur"]


def stop_person(st: dict, regions: dict, persons: list[dict]) -> dict | None:
    """The person a stop lands on: the region its ``roi`` names when that is
    a person, else (a stop placed by x and y) the one person located, when
    the window's centre falls in their box. A centre in one member of a
    crowd frames the crowd: it binds no one. None when it lands on no one."""
    if st.get("roi") is not None:
        r = regions.get(st["roi"])
        if r is not None and is_person_region(r):
            return {"name": st["roi"], "region": r}
        return None
    if located_persons(persons) != 1:
        return None
    for q in persons:
        b = q["box"]
        if b[0] <= st["x"] <= b[2] and b[1] <= st["y"] <= b[3]:
            return {"name": q["name"], "region": q["entry"]}
    return None


def anchor_identity_check(tl: dict, item: dict, regions: dict, persons: list[dict]) -> list[dict]:
    """``anchor-identity`` (A43): a stop that lands on a person and is
    anchored to their name (``names_a_person``) arrives within
    [-``anchor_early_s``, +``anchor_late_s``] of the name's onset on measured
    word timings, or at least ``anchor_estimated_lead_s`` early and holds
    through the name on estimated ones; and the binding itself stands
    (``binding_check``). Returns the stops that fail, each with its index,
    whether a person wrote it, and why."""
    out = []
    for i, st in enumerate(tl["stops"]):
        if st.get("onset") is None:
            continue
        who = stop_person(st, regions, persons)
        if who is None or not names_a_person(st.get("spoken") or [], item, persons):
            continue
        why = []
        d = st["t"] - st["onset"]
        leave = leave_time(tl, i)
        if st.get("measured"):
            if not (-CINE["anchor_early_s"] - 1e-6 <= d <= CINE["anchor_late_s"] + 1e-6):
                why.append(f"arrives {d:+.2f} s from the name on measured timings, outside "
                           f"[-{CINE['anchor_early_s']:g}, +{CINE['anchor_late_s']:g}] s")
        else:
            if d > -CINE["anchor_estimated_lead_s"] + 1e-6:
                why.append(f"arrives {d:+.2f} s from the name on estimated timings: at least "
                           f"{CINE['anchor_estimated_lead_s']:g} s early (lead_s), or measure the words")
            if leave < st["name_end"] - 1e-6:
                why.append(f"leaves at {leave:.2f} s, before the name ends ({st['name_end']:.2f} s): hold through it")
        why += binding_check(item, st.get("spoken") or [], who["region"], persons)
        if why:
            out.append({"i": i, "stop": st.get("from"), "person": who["name"], "at": st.get("at"),
                        "authored": authored(st), "spoken": " ".join(st.get("spoken") or []),
                        "arrives_s": round(st["t"], 3), "onset_s": round(st["onset"], 3),
                        "measured": bool(st.get("measured")), "why": why})
    return out


def group_stop(persons: list[dict], size, aspect: float, who: dict | None = None) -> tuple[dict, str]:
    """Where a person stop that may not bind a name goes instead (ruling 2),
    and what it now frames: the group, every located person framed with a
    margin and never past the face cap, when the group fits one window; else
    (one person, or a group wider than any window, a panorama's two ends)
    the fill about the person the stop visited, z 1, the whole picture's
    framing and never a face push, so the visit still shows them."""
    bs = [q["box"] for q in persons]
    box = {"x": min(b[0] for b in bs), "y": min(b[1] for b in bs)}
    box.update(w=max(b[2] for b in bs) - box["x"], h=max(b[3] for b in bs) - box["y"])
    if located_persons(persons) > 1:
        fw, fh = fill_window(size, aspect)
        if box["w"] * float(size[0]) * 1.25 <= fw + EPS and box["h"] * float(size[1]) * 1.25 <= fh + EPS:
            return roi_stop(box, size, aspect, CINE["face_zmax"]), "group"
    b = who["box"] if who is not None else (box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"])
    return {"z": 1.0, "x": (b[0] + b[2]) / 2.0, "y": (b[1] + b[3]) / 2.0}, "whole"


def degrade_bindings(stops: list[dict], dur: float, item: dict, regions: dict, persons: list[dict], size,
                     aspect: float, zmax: float, *, no_zoom: bool = False) -> tuple[list[dict], list[dict]]:
    """The engine's side of ``anchor-identity`` (founder ruling 2: degrade,
    never block): an engine-placed stop that lands on a person and fails the
    timing or the binding is re-framed (``group_stop``), keeping its time, and
    no longer binds the name. A stop a person wrote is left for the lint.
    Returns (stops, what was re-framed)."""
    if not persons:
        return stops, []
    tl = build(stops, dur, size, aspect, zmax, no_zoom=no_zoom)
    fails = [f for f in anchor_identity_check(tl, item, regions, persons) if not f["authored"]]
    if not fails:
        return stops, []
    stops = [dict(st) for st in stops]
    done = []
    for f in fails:
        st = stops[f["i"]]               # build keeps one stop per input stop, in order
        r = regions.get(st.get("roi")) if st.get("roi") is not None else None
        who = {"box": roi_box(r)} if r is not None and roi_box(r) is not None else next(
            (q for q in persons if q["name"] == f["person"]), None)
        for key in ("roi", "at", "onset", "name_end", "measured", "spoken", "spoken_line", "spoken_i", "z_authored"):
            st.pop(key, None)
        g, now = group_stop(persons, size, aspect, who)
        st.update(g, reframed=f["person"], **{"from": f"{st.get('from')}: re-framed to the {now}"})
        done.append({"stop": f["stop"], "person": f["person"], "spoken": f["spoken"], "why": f["why"], "now": now})
    return stops, done


def _box_problems(e: dict, where: str) -> list[str]:
    have = [k for k in BOX if k in e]
    if not have:
        return []
    if len(have) < 4:
        return [f"{where}: a box is x, y, w and h together (it has {', '.join(have)})"]
    vals = {}
    for k in BOX:
        v = e[k]
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
            return [f"{where}: {k} must be a number 0 to 1 (picture fractions), not {v!r}"]
        vals[k] = float(v)
    probs = []
    if not all(0.0 <= vals[k] <= 1.0 for k in BOX):
        probs.append(f"{where}: x, y, w and h are picture fractions 0 to 1 ({vals})")
    if vals["w"] <= 0 or vals["h"] <= 0:
        probs.append(f"{where}: w and h must be over 0")
    if vals["x"] + vals["w"] > 1.0 + 1e-6 or vals["y"] + vals["h"] > 1.0 + 1e-6:
        probs.append(f"{where}: the box runs past the picture's edge (x + w and y + h are at most 1)")
    return probs


def _entry_problems(e: dict, where: str, *, roi: bool) -> list[str]:
    probs = _box_problems(e, where)
    if e.get("facing") is not None and e["facing"] not in FACINGS:
        probs.append(f"{where}: facing is one of {', '.join(FACINGS)}, not {e['facing']!r}")
    if e.get("source") is not None and e["source"] not in SOURCES:
        probs.append(f"{where}: source is auto or human, not {e['source']!r}")
    c = e.get("confidence")
    if c is not None and (not isinstance(c, (int, float)) or isinstance(c, bool) or not math.isfinite(c)
                          or not 0.0 <= c <= 1.0):
        probs.append(f"{where}: confidence is a number 0 to 1, not {c!r}")
    if e.get("name") is not None and not isinstance(e["name"], str):
        probs.append(f"{where}: name is a string")
    if not roi and "face" in e:
        # A51: the face found inside this figure ({x, y, w, h}, picture fractions; the rulebook's, or a person's)
        if not isinstance(e["face"], dict) or roi_box(e["face"]) is None:
            probs.append(f"{where}: face is a box {{x, y, w, h}} (the face inside this figure)")
        else:
            probs += _box_problems(e["face"], f"{where}.face")
    if roi:
        if not isinstance(e.get("name"), str) or not e["name"].strip():
            probs.append(f"{where}: a region needs a name (the rulebook's subject, person-1, ...; or the author's)")
        if e.get("kind") is not None and e["kind"] not in KINDS:
            probs.append(f"{where}: kind is one of {', '.join(KINDS)}, not {e['kind']!r}")
        cue = e.get("cue")
        if cue is not None and not (isinstance(cue, str) or (isinstance(cue, list) and all(isinstance(x, str) for x in cue))):
            probs.append(f"{where}: cue is a string or a list of strings")
        ln = e.get("lines")
        if ln is not None and not (isinstance(ln, int) and not isinstance(ln, bool) and ln >= 1):
            probs.append(f"{where}: lines is the number of lines of text the region holds (1 or more), not {ln!r}")
        od = e.get("order")
        if od is not None and not (isinstance(od, (int, float)) and not isinstance(od, bool) and math.isfinite(od)):
            probs.append(f"{where}: order is a number (the painter's reading order for SURVEY, A54), not {od!r}")
    return probs


def item_schema(item: dict) -> tuple[list[str], list[str]]:
    """The cinematography fields of a stills-ledger item against the schema
    (WG-2, A43). Returns (malformed, unknown): malformed values would make the
    engine misbehave and refuse; unknown keys on a person or a region warn."""
    bad, unknown = [], []
    cls = item.get("class")
    if cls is not None and cls not in CLASSES:
        bad.append(f"class is one of {', '.join(CLASSES)}, not {cls!r}")
    pe = item.get("people")
    if isinstance(pe, list):
        for k, p in enumerate(pe):
            if isinstance(p, dict):
                bad += _entry_problems(p, f"people[{k}]", roi=False)
                unknown += [f"people[{k}].{x}" for x in sorted(set(p) - PEOPLE_KEYS)]
    roi = item.get("roi")
    if roi is not None:
        if not isinstance(roi, list):
            bad.append("roi is a list of regions [{name, x, y, w, h, kind, ...}], never a keyed object")
        else:
            names: dict = {}
            for k, r in enumerate(roi):
                if not isinstance(r, dict):
                    bad.append(f"roi[{k}]: a region is an object")
                    continue
                bad += _entry_problems(r, f"roi[{k}]", roi=True)
                unknown += [f"roi[{k}].{x}" for x in sorted(set(r) - ROI_KEYS)]
                key = (r.get("name"), source_of(r))
                if r.get("name") is not None and key in names:
                    bad.append(f"roi[{k}]: two {key[1]} regions are named {r.get('name')!r} (roi[{names[key]}])")
                names.setdefault(key, k)
    cn = item.get("caption_names")
    if cn is not None and not (isinstance(cn, list) and all(isinstance(x, str) and x.strip() for x in cn)):
        bad.append(f"caption_names is a list of the names the caption gives, not {cn!r}")
    if "dignity" in item and item["dignity"] is not True:
        bad.append(f"dignity is true or absent (a human's mark: keep every face at z 1.3), not {item['dignity']!r}")
    if "whole" in item and item["whole"] is not True:
        bad.append(f"whole is true or absent, not {item['whole']!r}")
    if "aerial" in item and not isinstance(item["aerial"], bool):
        bad.append(f"aerial is true or false (seen from above: the whole sweep never rises), not {item['aerial']!r}")
    comp = item.get("compose")
    if comp is not None and not (comp == "golden" or (isinstance(comp, str) and comp.startswith("centred:")
                                                     and comp.split(":", 1)[1].strip())):
        bad.append(f"compose is \"golden\" or \"centred:<reason>\", not {comp!r}")
    lv = item.get("levels")
    if lv is not None:
        if lv != "none":
            bad.append(f"levels is \"none\" (the opt-out from the automatic black floor), not {lv!r}")
        elif not (isinstance(item.get("levels_reason"), str) and item["levels_reason"].strip()):
            bad.append("levels: none needs a levels_reason (why the fade is the artifact)")
    return bad, unknown


def _at_ok(v) -> bool:
    return (isinstance(v, str) and v.strip() != "") or (isinstance(v, int) and not isinstance(v, bool) and v >= 0)


def shot_schema(shot: dict) -> tuple[list[str], list[str]]:
    """A still shot's cinematography fields against the schema (A43):
    ``subject_at``, ``match``, and each ``camera`` stop's keys and values.
    Returns (malformed, unknown)."""
    bad, unknown = [], []
    sa = shot.get("subject_at")
    if sa is not None:
        if isinstance(sa, dict):
            if not _at_ok(sa.get("at")):
                bad.append(f"subject_at.at is a cue the narration speaks or a word index, not {sa.get('at')!r}")
            if sa.get("line") is not None and not isinstance(sa["line"], str):
                bad.append("subject_at.line is a line id")
            unknown += [f"subject_at.{x}" for x in sorted(set(sa) - {"at", "line"})]
        elif not (isinstance(sa, str) and sa.strip()):
            bad.append(f"subject_at is a cue (a string) or {{at, line?}}, not {sa!r}")
    if shot.get("match") is not None and shot["match"] != "prev":
        bad.append(f"match is \"prev\", not {shot['match']!r}")
    mv = shot.get("move")
    if mv is not None and (not isinstance(mv, str) or mv.upper() not in MOVE_NAMES):
        bad.append(f"move is one of {', '.join(MOVE_NAMES)} (A54), not {mv!r}")
    mvv = shot.get("move_variant")
    if mvv is not None and mvv not in MOVE_VARIANTS:
        bad.append(f"move_variant is one of {', '.join(MOVE_VARIANTS)}, not {mvv!r}")
    if mv is not None and shot.get("camera") is not None:
        bad.append("a shot takes a camera path or a move, not both")
    cam = shot.get("camera")
    if isinstance(cam, list):
        for k, st in enumerate(cam):
            if not isinstance(st, dict):
                continue                       # tour-path names it
            unknown += [f"camera[{k}].{x}" for x in sorted(set(st) - STOP_KEYS)]
            if st.get("scale") is not None and st["scale"] not in SCALES:
                bad.append(f"camera[{k}].scale is one of {', '.join(SCALES)}, not {st['scale']!r}")
            if st.get("match") is not None and st["match"] != "prev":
                bad.append(f"camera[{k}].match is \"prev\", not {st['match']!r}")
            if "at" in st and not _at_ok(st["at"]):
                bad.append(f"camera[{k}].at is a cue the narration speaks or a word index, not {st['at']!r}")
            if st.get("line") is not None and not isinstance(st["line"], str):
                bad.append(f"camera[{k}].line is a line id")
    return bad, unknown


# --------------------------------------------------------------------------
# Guards
# --------------------------------------------------------------------------

# exactly these mean nobody; any other words name someone, so they are unlocated people (a ledger that says
# "no one named; three refugees" holds three people)
NOBODY = ("none", "none visible", "none resolvable")


def people_of(item: dict, *, kind: str = "archive_still") -> dict:
    """Who is in the picture, from the ledger: ``{"boxes": [...], "unlocated":
    n, "known": bool}``. ``people`` false, empty, or exactly "none", "none
    visible" or "none resolvable" is nobody; any other string is someone; a list holds people, each located when it carries {x, y, w, h};
    a region of interest with ``person: true`` is a located person. Absent on
    an archive picture it is unknown (unlocated); a drawn picture is nobody
    unless it says so."""
    eff = effective_regions(item)
    item = dict(item, people=eff["people"], roi=eff["roi"])
    boxes, unlocated, known = [], eff["unlocated"], True
    pe = item.get("people", None)
    if pe is None:
        known = False
        unlocated += 0 if kind == "drawn" else 1
    elif pe is False or pe == [] or pe == 0:
        pass
    elif isinstance(pe, str):
        if pe.strip().lower().rstrip(".") not in NOBODY:
            unlocated = 1
    elif isinstance(pe, list):
        for p in pe:
            b = roi_box(p) if isinstance(p, dict) else None
            if b is None:
                unlocated += 1
            else:
                boxes.append({"name": p.get("name"), "box": b})
    else:
        unlocated = 1
    for r in item.get("roi") or []:
        if isinstance(r, dict) and is_person_region(r) and roi_box(r) is not None:
            boxes.append({"name": r.get("name"), "box": roi_box(r)})
    return {"boxes": boxes, "unlocated": unlocated, "known": known}


def covered(windows, box, size, hit=None, tol_px: float = 0.5) -> bool:
    """Every point of a box (picture fractions) is inside some window: exact,
    on the grid the windows' own edges cut (coordinate compression), so a
    thin box between any sample grid is judged as it is. ``hit`` is unused
    (kept for callers)."""
    import numpy as np
    iw, ih = float(size[0]), float(size[1])
    bx0, by0, bx1, by1 = box[0] * iw, box[1] * ih, box[2] * iw, box[3] * ih
    if bx1 - bx0 <= 0 or by1 - by0 <= 0:
        return True
    ws = [(a - tol_px, b - tol_px, c + tol_px, d + tol_px) for (a, b, c, d) in windows]
    xs = np.unique(np.clip(np.array([bx0, bx1] + [v for w in ws for v in (w[0], w[2])]), bx0, bx1))
    ys = np.unique(np.clip(np.array([by0, by1] + [v for w in ws for v in (w[1], w[3])]), by0, by1))
    if len(xs) < 2 or len(ys) < 2:
        return True
    hit = np.zeros((len(ys) - 1, len(xs) - 1), bool)
    for (a, b, c, d) in ws:
        i0, i1 = np.searchsorted(xs, a, "left"), np.searchsorted(xs, c, "right") - 1
        j0, j1 = np.searchsorted(ys, b, "left"), np.searchsorted(ys, d, "right") - 1
        if i1 > i0 and j1 > j0:
            hit[j0:j1, i0:i1] = True
    return bool(hit.all())


def coverage(windows, size) -> float:
    """The share of the picture's area some window shows (for the evidence)."""
    import numpy as np
    iw, ih = float(size[0]), float(size[1])
    xs = np.unique(np.clip(np.array([0.0, iw] + [v for w in windows for v in (w[0], w[2])]), 0, iw))
    ys = np.unique(np.clip(np.array([0.0, ih] + [v for w in windows for v in (w[1], w[3])]), 0, ih))
    hit = np.zeros((len(ys) - 1, len(xs) - 1), bool)
    for (a, b, c, d) in windows:
        i0, i1 = np.searchsorted(xs, a - 0.5, "left"), np.searchsorted(xs, c + 0.5, "right") - 1
        j0, j1 = np.searchsorted(ys, b - 0.5, "left"), np.searchsorted(ys, d + 0.5, "right") - 1
        if i1 > i0 and j1 > j0:
            hit[j0:j1, i0:i1] = True
    area = np.outer(np.diff(ys), np.diff(xs))
    return float((area * hit).sum() / (iw * ih))


def seen(windows, box, size, tol_px: float = 0.5) -> bool:
    """A box (picture fractions) is in frame at some point: whole inside one
    window (to half a source pixel), or, when it is larger than any window can
    hold, every part of it inside some window over the path (a full-length
    figure the camera tilts down), judged exactly (``covered``)."""
    iw, ih = float(size[0]), float(size[1])
    x0, y0, x1, y1 = box[0] * iw, box[1] * ih, box[2] * iw, box[3] * ih
    for (a, b, c, d) in windows:
        if a <= x0 + tol_px and b <= y0 + tol_px and c >= x1 - tol_px and d >= y1 - tol_px:
            return True
    if any(c - a >= x1 - x0 - tol_px and d - b >= y1 - y0 - tol_px for (a, b, c, d) in windows):
        return False
    return covered(windows, box, size)


def windows_of(tl: dict, hz: float | None = None) -> list[tuple[float, float, float, float]]:
    """The picture windows of a tour, sampled (``samples``)."""
    size, aspect = tl["size"], tl["aspect"]
    return [window(size, aspect, f["z"], f["x"], f["y"]) for _, f in samples(tl, hz)]


def people_check(windows, people: dict, size) -> dict:
    """A7 over the path (A41, blocking): every located person is in frame at
    some point; an unlocated person (or unknown people) needs the whole
    picture shown at some point. Returns {ok, missed, whole_shown}."""
    missed = [p["name"] or f"person {k}" for k, p in enumerate(people["boxes"]) if not seen(windows, p["box"], size)]
    whole = covered(windows, whole_box(size, FRAME_ASPECT), size)
    need_whole = people["unlocated"] > 0
    ok = not missed and (whole or not need_whole)
    return {"ok": ok, "missed": missed, "whole_shown": whole, "unlocated": people["unlocated"],
            "located": len(people["boxes"]), "known": people["known"]}


def must_show_regions(item: dict) -> list[dict]:
    """The ledger's ``must_show`` regions (a caption, a sign, a second
    figure): a region with ``must_show: true``, or named in the item's
    ``must_show`` list. Cinematography ticket #4: the single source for
    ``must_show`` (section 7.2, A41), read by this module's own
    ``must_show`` (coverage) and by ``render.build_plan``'s
    ``subject-under-text`` steering and block (A49)."""
    names = item.get("must_show") if isinstance(item.get("must_show"), list) else []
    return [r for r in item.get("roi") or [] if isinstance(r, dict) and roi_box(r) is not None
            and (r.get("must_show") is True or r.get("name") in names)]


def must_show(windows, item: dict, size) -> list[str]:
    """The ledger's ``must_show`` regions (``must_show_regions``) that the
    path never shows whole."""
    return [r.get("name") for r in must_show_regions(item) if not seen(windows, roi_box(r), size)]


def face_boxes(item: dict) -> list[dict]:
    """A51 (doctrine section 4, "faces never"): every located face in the
    picture, as the camera may use it (``effective_regions``): a ``kind:
    face`` region; else, for each located person (a ``people`` box, a
    ``kind: person`` region or A41's ``person: true``), the face MediaPipe
    found inside that figure (the rulebook's ``face`` on the entry), else
    its head: the top ``CINE["head_share"]`` of the person's box. A person
    whose box already holds a face region is not counted twice, nor is one
    box listed under two names (a ``people`` entry and the ``subject`` the
    rulebook made of it). Returns [{name, box (x0, y0, x1, y1), src: roi |
    face | head, must_show}]; ``must_show`` is the region's own (a face
    named in the ledger's ``must_show``)."""
    eff = effective_regions(item)
    names = item.get("must_show") if isinstance(item.get("must_show"), list) else []
    out: list[dict] = []
    seen_boxes: set = set()

    def add(name, box, src, must):
        key = tuple(round(v, 4) for v in box)
        if key in seen_boxes:
            return
        seen_boxes.add(key)
        out.append({"name": name, "box": box, "src": src, "must_show": must})

    faces = [r for r in eff["roi"] if r.get("kind") == "face" and roi_box(r) is not None]
    for r in faces:
        add(r.get("name"), roi_box(r), "roi", r.get("must_show") is True or r.get("name") in names)
    figures = [p for p in (eff["people"] if isinstance(eff["people"], list) else [])
               if isinstance(p, dict) and roi_box(p) is not None]
    figures += [r for r in eff["roi"] if is_person_region(r) and r.get("kind") != "face" and roi_box(r) is not None]
    done: set = set()
    for e in figures:
        pb = roi_box(e)
        key = tuple(round(v, 4) for v in pb)
        if key in done:
            continue
        done.add(key)
        if any(_inside_share(roi_box(f), pb) >= CINE["nest_share"] for f in faces):
            continue
        fb = roi_box(e["face"]) if isinstance(e.get("face"), dict) else None
        if fb is not None:
            add(e.get("name"), fb, "face", False)
        else:
            add(e.get("name"), (pb[0], pb[1], pb[2], pb[1] + (pb[3] - pb[1]) * CINE["head_share"]), "head", False)
    return out


def face_avoid(item: dict, zones) -> list[tuple]:
    """A51: the ``avoid`` entries (``end_pose``, ``whole_pose``, ``creep``,
    ``aimed_breath``) for every located face (``face_boxes``) against every
    live text zone (frame fractions: the lower thirds and subtitle cues up
    over the shot), each marked ``"face"`` so it reads at any overlap
    (``avoid_overlap``) and is never a fit requirement (``avoid_fits``)."""
    return [(f["box"], zone, "face") for f in face_boxes(item) for zone in zones]


def across_cut(ta: float, tb: float, cuts) -> bool:
    """A54: a pair of samples that straddles a hard cut inside the shot (``tl['cuts']``) is no motion."""
    return any(ta - 1e-6 <= c < tb - 1e-9 for c in cuts or ())


def speed_report(wins: list[tuple[float, tuple]], cuts=()) -> dict:
    """The fastest pan (the window's centre, in its own widths or heights per
    second) and zoom (scale change per second) over windows sampled in time
    order [(t, (x0, y0, x1, y1))], against the guides (A41: warnings)."""
    pan, zoom, pan_at, zoom_at = 0.0, 0.0, 0.0, 0.0
    for (ta, a), (tb, b) in zip(wins, wins[1:]):
        dt = tb - ta
        if dt <= EPS or across_cut(ta, tb, cuts):
            continue
        ww, wh = a[2] - a[0], a[3] - a[1]
        vx = abs((b[0] + b[2]) - (a[0] + a[2])) / 2.0 / ww / dt
        vy = abs((b[1] + b[3]) - (a[1] + a[3])) / 2.0 / wh / dt
        vz = abs(math.log(ww / max(b[2] - b[0], EPS))) / dt
        if max(vx, vy) > pan:
            pan, pan_at = max(vx, vy), tb
        if vz > zoom:
            zoom, zoom_at = vz, tb
    zoom_pct = math.exp(zoom) - 1.0
    return {"pan_per_s": round(pan, 4), "pan_at_s": round(pan_at, 3), "zoom_per_s": round(zoom_pct, 4),
            "zoom_at_s": round(zoom_at, 3), "pan_guide": round(TOUR["pan_guide_per_s"], 4),
            "zoom_guide": TOUR["zoom_guide_per_s"],
            "ok": pan <= TOUR["pan_guide_per_s"] + 1e-6 and zoom_pct <= TOUR["zoom_guide_per_s"] + 1e-6}


def edge_motion(tl: dict, end: bool, near: float = 0.25) -> tuple[float, float, float]:
    """The move the camera is making at a cut: at the shot's end (``end``) the
    last move when it arrives within ``near`` seconds of the cut, at its start
    the first move when it leaves within ``near`` seconds. Its mean velocity:
    (x, y) in window widths and heights per second, z in log scale per second
    (positive pushes in). Zero when the cut falls on a hold or a creep (the
    camera has landed on a stop)."""
    segs = tl["segments"]
    g = segs[-1] if end else segs[0]
    if g["kind"] != "move" or (end and tl["dur"] - g["t1"] > near) or (not end and g["t0"] > near):
        return 0.0, 0.0, 0.0
    d = g["t1"] - g["t0"]
    if d <= EPS:
        return 0.0, 0.0, 0.0
    size, aspect = tl["size"], tl["aspect"]
    wa = window(size, aspect, g["a"]["z"], g["a"]["x"], g["a"]["y"])
    wb = window(size, aspect, g["b"]["z"], g["b"]["x"], g["b"]["y"])
    ww, wh = wa[2] - wa[0], wa[3] - wa[1]
    return (((wb[0] + wb[2]) - (wa[0] + wa[2])) / 2.0 / ww / d, ((wb[1] + wb[3]) - (wa[1] + wa[3])) / 2.0 / wh / d,
            math.log(g["b"]["z"] / g["a"]["z"]) / d)


def reversal(out_v, in_v) -> list[str]:
    """The axes on which the next shot's first move runs against the last
    one's (both moving, opposite signs; ``edge_motion``). A side that has
    landed on a stop (slower than ``still_eps_per_s``) never reverses."""
    eps = TOUR["still_eps_per_s"]
    out = []
    for name, a, b in zip(("pan x", "tilt y", "zoom"), out_v, in_v):
        if abs(a) > eps and abs(b) > eps and (a > 0) != (b > 0):
            out.append(name)
    return out


# --------------------------------------------------------------------------
# A49 refined: degenerate stops (two framings the eye cannot tell apart, under a settle apart)
# --------------------------------------------------------------------------

DEGENERATE_GAP_S = CINE["settle_s"]        # closer than the settle minimum (1.0 s) ...
DEGENERATE_CENTRE = 0.005                  # ... with window centres within 0.5% of the frame ...
DEGENERATE_Z = 0.01                        # ... and depths within 1%: one framing, stopped on twice


def near_equal(a: dict, b: dict, size, aspect: float, *, centre: float = DEGENERATE_CENTRE,
               z: float = DEGENERATE_Z) -> bool:
    """Two stops frame the same window to the eye: centres within ``centre`` of the frame (the first window's
    width and height) and depths within ``z``."""
    wa = window(size, aspect, float(a["z"]), float(a["x"]), float(a["y"]))
    wb = window(size, aspect, float(b["z"]), float(b["x"]), float(b["y"]))
    fw, fh = wa[2] - wa[0], wa[3] - wa[1]
    dcx = abs((wb[0] + wb[2]) - (wa[0] + wa[2])) / 2.0
    dcy = abs((wb[1] + wb[3]) - (wa[1] + wa[3])) / 2.0
    return (abs(math.log(float(b["z"]) / float(a["z"]))) <= math.log1p(z) + EPS
            and dcx <= centre * fw + 1e-6 and dcy <= centre * fh + 1e-6)


def degenerate_pairs(stops: list[dict], size, aspect: float, *, gap_s: float = DEGENERATE_GAP_S) -> list[dict]:
    """``degenerate-stops`` (A49 refined): consecutive stops closer than ``gap_s`` whose windows are near-equal
    (``near_equal``): the path stops on one framing twice, which reads as a hitch or a micro-settle. Returns
    [{i, t, dt, z, authored, from}], ``i`` the first stop's index."""
    out = []
    for i, (a, b) in enumerate(zip(stops, stops[1:])):
        dt = float(b["t"]) - float(a["t"])
        if -EPS <= dt < gap_s - EPS and near_equal(a, b, size, aspect):
            out.append({"i": i, "t": [round(float(a["t"]), 3), round(float(b["t"]), 3)], "dt": round(dt, 3),
                        "z": [round(float(a["z"]), 4), round(float(b["z"]), 4)],
                        "authored": authored(a) or authored(b), "from": [a.get("from"), b.get("from")]})
    return out


def is_arrival(st: dict) -> bool:
    """The A47 subject stop (``subject_stops``' pose: its ``subject_at`` arrival, or its settle before the cut)."""
    return str(st.get("from") or "").startswith("A47: the subject")


def merge_pair(stops: list[dict], i: int) -> tuple[list[dict], dict]:
    """Stops ``i`` and ``i + 1`` as one: the later one's time is kept when it is the subject's arrival
    (``is_arrival``), else the earlier one's; the kept stop keeps its own hold, grown to cover a dropped stop's
    own hold where that runs longer (the micro-hold between the two is gone, a real hold is not). Returns
    (stops, what was merged)."""
    a, b = stops[i], stops[i + 1]
    later = is_arrival(b) and not is_arrival(a)
    keep, drop = (b, a) if later else (a, b)
    k = dict(keep)
    if float(drop.get("hold", 0.0)) > 0:
        end = float(drop["t"]) + float(drop["hold"])
        if end > float(k["t"]) + float(k.get("hold", 0.0)) + EPS:
            k["hold"] = end - float(k["t"])
    rec = {"t": [round(float(a["t"]), 3), round(float(b["t"]), 3)], "kept": round(float(k["t"]), 3),
           "dropped": drop.get("from"), "why": "the subject's arrival" if later else "the earlier"}
    return stops[:i] + [k] + stops[i + 2:], rec


def merge_degenerate(stops: list[dict], size, aspect: float, *, gap_s: float = DEGENERATE_GAP_S, accept=None
                     ) -> tuple[list[dict], list[dict]]:
    """The engine's side of ``degenerate-stops``: near-equal ENGINE stops under ``gap_s`` apart become one
    (``merge_pair``), one pair at a time, first to last, each kept only when ``accept(stops)`` (the caller's
    truth check; None accepts all). A stop a person wrote (``camera``) is never merged: ``degenerate_pairs``
    lints it. Returns (stops, merged: [{t, kept, dropped, why}])."""
    merged: list[dict] = []
    refused: set = set()
    while True:
        cand = [p for p in degenerate_pairs(stops, size, aspect, gap_s=gap_s)
                if not p["authored"] and (p["t"][0], p["t"][1]) not in refused]
        if not cand:
            return stops, merged
        p = cand[0]
        out, rec = merge_pair(stops, p["i"])
        if accept is None or accept(out):
            stops = out
            merged.append(rec)
        else:
            refused.add((p["t"][0], p["t"][1]))
