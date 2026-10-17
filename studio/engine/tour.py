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
MACROS = ("HOLD", "PUSH", "PULL", "DRIFT", "TILT", "DETAIL", "FILL")
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


def default_stops(size, aspect: float, dur: float, direction: str = "", zmax: float | None = None) -> list[dict]:
    """The default tour (A41): open at the fill on one end of the long axis
    and make one slow pass to the other over the shot (top to bottom, left to
    right; ``direction`` up or rl reverses it). A picture of the frame's own
    shape holds at the fill, creeping."""
    ax = long_axis(size, aspect)
    if ax is None:
        return [{"t": 0.0, "z": 1.0, "x": 0.5, "y": 0.5, "from": "default tour: the fill"}]
    a, b = 0.0, 1.0
    if direction in ("up", "bottom-to-top", "rl", "right-to-left", "left"):
        a, b = b, a
    first = {"t": 0.0, "z": 1.0, "x": 0.5, "y": 0.5, "from": "default tour: open"}
    last = {"t": dur, "z": 1.0, "x": 0.5, "y": 0.5, "from": "default tour: pass"}
    first[ax], last[ax] = a, b
    mid = _layer_creep(first, last, size, aspect, dur, ax, zmax)
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


def covering_stops(size, aspect: float, dur: float, focus=None, zmax: float | None = None) -> list[dict]:
    """A pass that shows the whole picture: the default tour, and with a
    ``focus`` it starts at the end farther from the focus, passes to the other
    end and comes back to settle on the focus. The shot's time is shared by
    how far each leg travels, so the camera keeps one even speed (the rostrum
    cruise) instead of rushing the settle."""
    ax = long_axis(size, aspect)
    if ax is None or focus is None:
        return default_stops(size, aspect, dur, zmax=zmax)
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


def creep(p: dict, h: float, size, aspect: float, zmax: float, *, prefer=None, no_zoom: bool = False) -> tuple[dict, str]:
    """Where a stop held ``h`` seconds has crept to, and how: a push of
    ``creep_scale_per_s`` while under the cap, else a pull while above the
    fill, else a slow drift along the axis with room (``prefer`` is the last
    move's direction, (dx, dy)). ``no_zoom`` (a shot that must not be zoomed)
    drifts only. ``held`` when nothing can move (a 16:9 picture at the cap)."""
    c = TOUR["creep_scale_per_s"] * h
    if not no_zoom and p["z"] * (1.0 + c) <= zmax + EPS:
        return dict(p, z=p["z"] * (1.0 + c)), "push"
    if not no_zoom and p["z"] / (1.0 + c) >= 1.0 - EPS:
        return dict(p, z=p["z"] / (1.0 + c)), "pull"
    iw, ih = float(size[0]), float(size[1])
    x0, y0, x1, y1 = window(size, aspect, p["z"], p["x"], p["y"])
    room = {"x": (x0, iw - x1), "y": (y0, ih - y1)}             # room before and after, picture px
    d = {"x": TOUR["creep_drift_per_s"] * h * (x1 - x0), "y": TOUR["creep_drift_per_s"] * h * (y1 - y0)}
    order = sorted(("x", "y"), key=lambda a: -max(room[a]))
    if prefer is not None:
        px, py = prefer
        order = sorted(("x", "y"), key=lambda a: -abs(px if a == "x" else py)) if (abs(px) + abs(py)) > EPS else order
    for ax in order:
        lo, hi = room[ax]
        if max(lo, hi) < 0.5:
            continue
        sign = 1.0 if hi >= lo else -1.0
        if prefer is not None:
            v = prefer[0] if ax == "x" else prefer[1]
            if abs(v) > EPS and (hi if v > 0 else lo) >= 0.5:
                sign = 1.0 if v > 0 else -1.0
        step = min(d[ax], hi if sign > 0 else lo)
        n = iw if ax == "x" else ih
        return dict(p, **{ax: p[ax] + sign * step / n}), "drift"
    return dict(p), "held"


def build(stops: list[dict], dur: float, size, aspect: float, zmax: float, *, no_zoom: bool = False) -> dict:
    """The stops as a timeline of segments {t0, t1, a, b, kind}: ``move``
    between stops on the rostrum curve, ``creep`` on a hold longer than
    ``hold_creep_after_s`` (before the first stop, after a stop's ``hold``, or
    to the shot's end), ``hold`` for a short one. Each stop is settled inside
    the picture first."""
    if not stops:
        raise TourError("a path needs at least one stop")
    pts = [dict(settle(s, size, aspect), t=float(s["t"]), hold=float(s.get("hold", 0.0))) for s in stops]
    after = TOUR["hold_creep_after_s"]
    segs: list[dict] = []
    held: list[dict] = []

    def hold(t0, t1, p, *, into: bool = False, prefer=None):
        """A hold from t0 to t1 at p (or, ``into``, a hold that must end on p)."""
        if t1 - t0 <= EPS:
            return p
        if t1 - t0 <= after + EPS:
            segs.append({"t0": t0, "t1": t1, "a": p, "b": p, "kind": "hold"})
            return p
        # A43: a stop that frames a face or a person creeps under the face cap, not only the softness cap
        zm = min(zmax, float(p.get("face_cap", math.inf)))
        if p["z"] > zm + EPS:
            zm = p["z"]                       # an authored depth past the cap: the lint refuses it; never pushed further
        q, how = creep(p, t1 - t0, size, aspect, zm, prefer=prefer, no_zoom=no_zoom)
        if how == "held":
            held.append({"t0": round(t0, 3), "t1": round(t1, 3)})
        q = settle(q, size, aspect)
        a, b = (q, p) if into else (p, q)
        segs.append({"t0": t0, "t1": t1, "a": a, "b": b, "kind": "creep" if how != "held" else "hold", "how": how})
        return b

    hold(0.0, pts[0]["t"], pts[0], into=True)
    last_dir = None
    for i, p in enumerate(pts):
        nxt = pts[i + 1] if i + 1 < len(pts) else None
        leave = min(p["t"] + p["hold"], nxt["t"] if nxt else dur)
        pos = hold(p["t"], leave, p, prefer=last_dir) if leave > p["t"] + EPS else p
        if nxt is None:
            if dur - leave > EPS:
                hold(leave, dur, pos, prefer=last_dir)
            break
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
    zs = [s["a"]["z"] for s in segs] + [s["b"]["z"] for s in segs]
    return {"segments": segs, "stops": pts, "dur": dur, "size": [float(size[0]), float(size[1])], "aspect": aspect,
            "z_max": max(zs), "z_min": min(zs), "held": held, "zmax_allowed": zmax}


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
    e = M.rostrum(t - g["t0"], g["t1"] - g["t0"]) if g["t1"] > g["t0"] else 1.0
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
PEOPLE_KEYS = set(BOX) | {"name", "facing", "source", "confidence", "model"}
ROI_KEYS = set(BOX) | {"name", "kind", "facing", "source", "confidence", "model", "cue", "must_show", "person"}
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
    cap = CINE["face_zmax"]
    out = []
    for st in stops:
        st = dict(st)
        hit = framed_persons(settle(st, size, aspect), persons, size, aspect) if persons else []
        if hit:
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
    cap = CINE["face_zmax"]
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
        if hit and key not in seen_:
            seen_.add(key)
            bad.append({"t": round(t, 3), "z": round(p["z"], 4), "people": [q["name"] for q in hit],
                        "stops": _stops_around(tl, t)})
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
                     no_zoom: bool = False) -> tuple[list[dict], list[dict]]:
    """The engine's side of ``face-cap-live``: build the path, and where any
    framing of it (a move included) frames a face past the cap, pull the
    engine-placed stops around it back to ``CINE['face_zmax']`` and build
    again. A depth a person wrote is left as written, for the lint. Returns
    (stops, what was pulled back)."""
    cap = CINE["face_zmax"]
    pulled = []
    for _ in range(len(stops) + 2):
        tl = build(stops, dur, size, aspect, zmax, no_zoom=no_zoom)
        bad = face_cap_check(tl, persons)
        idx = sorted({i for v in bad for i in v["stops"]
                      if tl["stops"][i]["z"] > cap + EPS and not tl["stops"][i].get("z_authored")})
        if not idx:
            break
        stops = [dict(st) for st in stops]
        for i in idx:
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
    person-1, ...), or an entry of the item's ``caption_names``. A capital
    letter alone never makes a name ("New York", "Pentagon")."""
    cue = [norm_word(w) for w in spoken if norm_word(w)]
    if not cue:
        return False
    for q in persons:
        e = q.get("entry") or {}
        for c in [e.get("name")] + (cue_of(e) if e.get("cue") is not None else []):
            if isinstance(c, str) and not GENERIC_NAME.match(c) and _same_name(_norm_words(c), cue):
                return True
    return any(_same_name(_norm_words(n), cue) for n in item.get("caption_names") or [] if isinstance(n, str))


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
    return why


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


def group_stop(persons: list[dict], size, aspect: float) -> dict:
    """Where a person stop that may not bind a name goes instead (ruling 2):
    the group, every located person framed with a margin and never past the
    face cap, or, with one person, the fill about them (the whole picture's
    framing, never a single face)."""
    bs = [q["box"] for q in persons]
    box = {"x": min(b[0] for b in bs), "y": min(b[1] for b in bs)}
    box.update(w=max(b[2] for b in bs) - box["x"], h=max(b[3] for b in bs) - box["y"])
    if located_persons(persons) <= 1:
        return {"z": 1.0, "x": box["x"] + box["w"] / 2.0, "y": box["y"] + box["h"] / 2.0}
    return roi_stop(box, size, aspect, CINE["face_zmax"])


def degrade_bindings(stops: list[dict], dur: float, item: dict, regions: dict, persons: list[dict], size,
                     aspect: float, zmax: float, *, no_zoom: bool = False) -> tuple[list[dict], list[dict]]:
    """The engine's side of ``anchor-identity`` (founder ruling 2: degrade,
    never block): an engine-placed stop that lands on a person and fails the
    timing or the binding is re-framed to the group or the whole, keeping its
    time, and no longer binds the name. A stop a person wrote is left for the
    lint. Returns (stops, what was re-framed)."""
    if not persons:
        return stops, []
    tl = build(stops, dur, size, aspect, zmax, no_zoom=no_zoom)
    fails = [f for f in anchor_identity_check(tl, item, regions, persons) if not f["authored"]]
    if not fails:
        return stops, []
    stops = [dict(st) for st in stops]
    now = "group" if located_persons(persons) > 1 else "whole"
    done = []
    for f in fails:
        st = stops[f["i"]]               # build keeps one stop per input stop, in order
        for key in ("roi", "at", "onset", "name_end", "measured", "spoken", "spoken_line", "spoken_i", "z_authored"):
            st.pop(key, None)
        st.update(group_stop(persons, size, aspect), reframed=f["person"],
                  **{"from": f"{st.get('from')}: re-framed to the {now}"})
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
    if roi:
        if not isinstance(e.get("name"), str) or not e["name"].strip():
            probs.append(f"{where}: a region needs a name (the rulebook's subject, person-1, ...; or the author's)")
        if e.get("kind") is not None and e["kind"] not in KINDS:
            probs.append(f"{where}: kind is one of {', '.join(KINDS)}, not {e['kind']!r}")
        cue = e.get("cue")
        if cue is not None and not (isinstance(cue, str) or (isinstance(cue, list) and all(isinstance(x, str) for x in cue))):
            probs.append(f"{where}: cue is a string or a list of strings")
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
    if "whole" in item and item["whole"] is not True:
        bad.append(f"whole is true or absent, not {item['whole']!r}")
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


def must_show(windows, item: dict, size) -> list[str]:
    """The ledger's ``must_show`` regions (a caption, a sign, a second figure:
    a region with ``must_show: true``, or a name in the item's ``must_show``
    list) that the path never shows whole."""
    names = item.get("must_show") if isinstance(item.get("must_show"), list) else []
    out = []
    for r in item.get("roi") or []:
        if not isinstance(r, dict) or roi_box(r) is None:
            continue
        if r.get("must_show") is True or r.get("name") in names:
            if not seen(windows, roi_box(r), size):
                out.append(r.get("name"))
    return out


def speed_report(wins: list[tuple[float, tuple]]) -> dict:
    """The fastest pan (the window's centre, in its own widths or heights per
    second) and zoom (scale change per second) over windows sampled in time
    order [(t, (x0, y0, x1, y1))], against the guides (A41: warnings)."""
    pan, zoom, pan_at, zoom_at = 0.0, 0.0, 0.0, 0.0
    for (ta, a), (tb, b) in zip(wins, wins[1:]):
        dt = tb - ta
        if dt <= EPS:
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
