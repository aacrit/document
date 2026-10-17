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
        if ln.get("words"):
            ws = [{"w": w["w"], "n": norm_word(w["w"]), "i": i, "t": float(w["t"])} for i, w in enumerate(ln["words"])]
        else:
            ws = word_times(ln.get("text", ""), a, float(ln["dur"]))
        for w in ws:
            out.append(dict(w, line=ln["id"], kind=ln.get("kind")))
    return out


def anchor_time(at, words: list[dict], *, line: str | None = None, t0: float = 0.0) -> float | None:
    """The absolute time of the word a stop's ``at`` names: an integer is a
    word index in ``line`` (or in the first line heard in the shot), a string
    a cue (one word or a phrase) the narration speaks, its first word's time.
    None when the narration in the shot does not hold it."""
    if not words:
        return None
    if isinstance(at, bool):
        return None
    if isinstance(at, (int, float)) or (isinstance(at, str) and re.fullmatch(r"\d+", at.strip())):
        k = int(at)
        lid = line or words[0]["line"]
        ws = [w for w in words if w["line"] == lid]
        return ws[k]["t"] if 0 <= k < len(ws) else None
    cue = [norm_word(t) for t in str(at).split() if norm_word(t)]
    if not cue:
        return None
    # a cue is the first time it is spoken in the shot (a line that began before the cut may say it earlier)
    ws = [w for w in words if (line is None or w["line"] == line) and w["t"] >= t0 - 0.05]
    for i in range(len(ws) - len(cue) + 1):
        if all(ws[i + j]["n"] == cue[j] for j in range(len(cue))) and all(
                ws[i + j]["line"] == ws[i]["line"] for j in range(len(cue))):
            return ws[i]["t"]
    return None


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
            at = anchor_time(c, words, t0=t0)
            if at is not None and t0 - EPS <= at <= t0 + dur + EPS:
                picks.append((at - t0, r))
                break
    if not picks:
        return None
    picks.sort(key=lambda p: p[0])
    stops = [{"t": 0.0, "z": 1.0, "x": 0.5, "y": 0.5, "from": "tour: the fill"}]
    for t, r in picks:
        st = roi_stop(r, size, aspect, zmax)
        st.update(t=max(0.0, min(dur, t)), roi=r.get("name"), **{"from": f"tour: {r.get('name')}"})
        if st["t"] <= stops[-1]["t"] + EPS:
            st["t"] = stops[-1]["t"] + 0.5     # never two stops at one moment (tour.mjs does the same)
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
    for one of the frame's own shape."""
    iw, ih = float(size[0]), float(size[1])
    a = iw / ih
    if abs(a - aspect) <= 0.01 * aspect:
        return None
    return "y" if a < aspect else "x"


def default_stops(size, aspect: float, dur: float, direction: str = "") -> list[dict]:
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
    return [first, last]


def covering_stops(size, aspect: float, dur: float, focus=None) -> list[dict]:
    """A pass that shows the whole picture: the default tour, and with a
    ``focus`` it starts at the end farther from the focus, passes to the other
    end and settles on the focus (``TOUR['default_settle']`` of the shot in)."""
    ax = long_axis(size, aspect)
    if ax is None or focus is None:
        return default_stops(size, aspect, dur)
    fx, fy = float(focus[0]), float(focus[1])
    f = fx if ax == "x" else fy
    a, b = (1.0, 0.0) if f >= 0.5 else (0.0, 1.0)
    t_mid = TOUR["default_settle"] * dur
    s0 = {"t": 0.0, "z": 1.0, "x": 0.5, "y": 0.5, "from": "covering pass: open"}
    s1 = {"t": t_mid, "z": 1.0, "x": 0.5, "y": 0.5, "from": "covering pass: the far end"}
    s0[ax], s1[ax] = a, b
    s2 = {"t": dur, "z": 1.0, "x": fx, "y": fy, "from": "covering pass: settle on the focus"}
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
        st = {"from": f"stop {k}"}
        if raw.get("roi") is not None:
            r = roi_by_name.get(raw["roi"])
            if r is None or roi_box(r) is None:
                probs.append(f"stop {k}: roi {raw['roi']!r} is not a located region of the ledger item")
                continue
            st.update(roi_stop(r, size, aspect, zmax), roi=raw["roi"])
        for key in ("x", "y", "z"):
            if key in raw:
                v = raw[key]
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    probs.append(f"stop {k}: {key} must be a number")
                    continue
                st[key] = float(v)
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
            at = anchor_time(raw["at"], words, line=raw.get("line"), t0=t0)
            if at is None:
                probs.append(f"anchor: stop {k}: at {raw['at']!r} is not spoken in this shot's narration")
                continue
            st["t"], st["at"] = at - t0, raw["at"]
            if not (-EPS <= st["t"] <= dur + EPS):
                probs.append(f"anchor: stop {k}: at {raw['at']!r} is spoken at {st['t']:.2f} s, outside the shot")
                continue
        elif "t" in raw:
            if not isinstance(raw["t"], (int, float)) or isinstance(raw["t"], bool):
                probs.append(f"stop {k}: t must be a number")
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
        if not isinstance(h, (int, float)) or isinstance(h, bool) or h < 0:
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
        q, how = creep(p, t1 - t0, size, aspect, zmax, prefer=prefer, no_zoom=no_zoom)
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
    boxes, unlocated, known = [], 0, True
    pe = item.get("people", None)
    if pe is None:
        known = False
        unlocated = 0 if kind == "drawn" else 1
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
        if isinstance(r, dict) and r.get("person") is True and roi_box(r) is not None:
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
    whole = covered(windows, (0.0, 0.0, 1.0, 1.0), size)
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
