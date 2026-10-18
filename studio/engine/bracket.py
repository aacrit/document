"""A detail inside the whole (GRAMMAR A50, cinematography ticket #12).

Founder ruling 3 (2026-10-17): "Detail stop in a fill_exception shot: (b).
One DETAIL stop within 3x, bracketed by the whole picture at both ends."

A still too small to fill 16:9 under the softness cap states
``fill_exception`` and is shown whole at its own shape, pillarboxed (A41).
This module draws the one move such a shot may make beyond its breath: the
whole, read; a push in to one detail inside the picture's own shape; a hold
(reading pace when the detail is text); a pull back out to the whole, settled
before the cut. When there is no detail to go to, or no time to go there and
back with the settles, ``plan`` says why and the shot keeps A41's whole +
creep (``render.whole_camera``).

Pure: no I/O. Framings are in the frame space the exception already moves in
(``motion.still_view``'s ``clamp="native"``): z is the zoom of the whole
(z 1 is the whole picture at its native aspect on the field) and x, y the
frame-space centre, so ``overlays.framing_at`` draws them as it draws the
creep. The numbers are ``motion.BRACKET``.
"""

from __future__ import annotations

import math

from studio.engine import motion as M
from studio.engine import tour as T

B = M.BRACKET
EPS = 1e-9
MASTER = (1920, 1080)          # the softness cap is judged on the 1080p master (A41)


# --------------------------------------------------------------------------
# Geometry: picture fractions <-> the native frame space
# --------------------------------------------------------------------------


def geom(size, W: int, H: int) -> tuple[float, float, float, float, float]:
    """(scale, fitted width, fitted height, left, top) of the whole picture on the field."""
    iw, ih = float(size[0]), float(size[1])
    s = min(W / iw, H / ih)
    fw, fh = iw * s, ih * s
    return s, fw, fh, (W - fw) / 2.0, (H - fh) / 2.0


def master_scale(size) -> float:
    """Output pixels per source pixel of the whole on the 1080p master."""
    return min(MASTER[0] / float(size[0]), MASTER[1] / float(size[1]))


def zcap(size, cap: float) -> float:
    """The deepest zoom of the whole the softness cap allows on the master (may be under 1: no room)."""
    return cap / master_scale(size)


def clamp_centre(u: float, v: float, z: float) -> tuple[float, float]:
    """A window centre (picture fractions) moved just enough to keep a 1/z window inside the picture."""
    h = 0.5 / max(1.0, z)
    return min(max(u, h), 1.0 - h), min(max(v, h), 1.0 - h)


def framing(u: float, v: float, z: float, size, W: int, H: int) -> dict:
    """The frame-space framing {z, x, y} whose window is centred on (u, v) in the picture."""
    z = max(1.0, float(z))
    u, v = clamp_centre(u, v, z)
    _, fw, fh, ox, oy = geom(size, W, H)
    return {"z": z, "x": (ox + u * fw) / W, "y": (oy + v * fh) / H}


def window(f: dict, size, W: int, H: int) -> tuple[float, float, float, float]:
    """The picture window (fractions) a framing shows: ``motion.still_view`` itself, so it is what is drawn."""
    src, _ = M.still_view(size, M.Layout(W, H), z=f["z"], cx=f["x"], cy=f["y"], clamp="native")
    iw, ih = float(size[0]), float(size[1])
    return src[0] / iw, src[1] / ih, src[2] / iw, src[3] / ih


def project(box, win, size, W: int, H: int) -> tuple[float, float, float, float] | None:
    """A picture box seen through a native window, in frame fractions (the window fills the pillarboxed shape)."""
    _, fw, fh, ox, oy = geom(size, W, H)
    ww, wh = win[2] - win[0], win[3] - win[1]
    if ww <= 0 or wh <= 0:
        return None
    x0, y0 = max(0.0, (box[0] - win[0]) / ww), max(0.0, (box[1] - win[1]) / wh)
    x1, y1 = min(1.0, (box[2] - win[0]) / ww), min(1.0, (box[3] - win[1]) / wh)
    if x1 <= x0 or y1 <= y0:
        return None
    return ((ox + x0 * fw) / W, (oy + y0 * fh) / H, (ox + x1 * fw) / W, (oy + y1 * fh) / H)


def overlap(win, avoid, size, W: int, H: int) -> float:
    """A49's measure in this frame space: the worst share of an ``avoid`` box under its own text zone."""
    worst = 0.0
    for box, zone in avoid or []:
        fb = project(box, win, size, W, H)
        if fb is not None:
            worst = max(worst, T.box_overlap_share(fb, zone))
    return worst


def inside(box, win, tol: float = 1e-6) -> bool:
    return (box[0] >= win[0] - tol and box[1] >= win[1] - tol and box[2] <= win[2] + tol
            and box[3] <= win[3] + tol)


# --------------------------------------------------------------------------
# The timeline: segments on the rostrum curve, z geometric
# --------------------------------------------------------------------------


def at(segs: list[dict], t: float) -> dict:
    """The framing at shot time t (the same easing as ``tour.at``)."""
    if t <= segs[0]["t0"]:
        g = segs[0]
        t = g["t0"]
    elif t >= segs[-1]["t1"]:
        g = segs[-1]
        t = g["t1"]
    else:
        g = next((s for s in segs if s["t0"] - EPS <= t <= s["t1"] + EPS), segs[-1])
    a, b = g["a"], g["b"]
    e = M.rostrum(t - g["t0"], g["t1"] - g["t0"]) if g["t1"] > g["t0"] else 1.0
    return {"z": a["z"] * (b["z"] / a["z"]) ** e, "x": a["x"] + (b["x"] - a["x"]) * e,
            "y": a["y"] + (b["y"] - a["y"]) * e}


def leg_s(za: float, zb: float, du: float, dv: float, zdeep: float) -> float:
    """The shortest leg on the rostrum curve inside the house guides (A49): a point crosses the frame in no
    less than ``cross_s`` (7 s) and the zoom cruises at ``zoom_cruise`` (5%/s) or less. The pan is counted
    in the deepest window's own widths and heights, where it reads fastest."""
    pan = max(abs(du), abs(dv)) * zdeep
    need = max(abs(math.log(zb / za)) / math.log(1.0 + B["zoom_cruise"]), pan * B["cross_s"])
    if need <= EPS:
        return 0.0
    # the cruise runs over T minus one ramp, the ramp min(0.9 s, 30% of T) (motion.rostrum)
    return need / 0.7 if need / 0.7 <= 3.0 else need + 0.9


def hold_min(region: dict | None, kind: str | None) -> float:
    """How long the detail holds at least: text at reading pace (one line per ``read_line_s`` when the region
    states its ``lines``, else ``read_default_s``), anything else ``hold_s`` (1.5 s)."""
    if kind == "text":
        n = (region or {}).get("lines")
        if isinstance(n, int) and not isinstance(n, bool) and n > 0:
            return max(B["hold_s"], n * B["read_line_s"])
        return max(B["hold_s"], B["read_default_s"])
    return B["hold_s"]


# --------------------------------------------------------------------------
# What the detail is
# --------------------------------------------------------------------------


def _cue_words(at_) -> list[str]:
    return [T.norm_word(w) for w in str(at_).split() if T.norm_word(w)]


def target(shot: dict, item: dict, roi: list[dict], persons: list[dict]) -> tuple[dict | None, str, list[str]]:
    """The one detail, in the schema's order: a person's written ``camera`` stop (an authored camera wins
    over the rulebook), else the ledger's ``subject`` region (a person's or the A45 rulebook's), else the
    region the shot's ``subject_at`` cue names (its ``cue``, else its name). Returns (target, why, problems):
    problems are a written path's, refused as written (A43); no target and no problems keeps whole + creep."""
    cam = shot.get("camera")
    by_name = {p["name"]: dict(p["entry"], kind=p.get("kind") or "person") for p in persons
               if p.get("name") is not None}
    by_name.update({r.get("name"): r for r in roi if isinstance(r, dict) and r.get("name") is not None})
    if isinstance(cam, list):
        stops = [st for st in cam if not (isinstance(st, dict) and st.get("roi") == "whole")]
        if len(stops) != 1 or not isinstance(stops[0], dict):
            return None, "a written path", [
                f"a fill_exception shot carries one DETAIL stop between the whole at both ends (A50); "
                f"this path has {len(stops)} besides the whole"]
        st = stops[0]
        out = {"src": "camera", "authored": True, "stop": st, "at": st.get("at"), "line": st.get("line"),
               "t": st.get("t"), "hold": st.get("hold"), "lead_s": st.get("lead_s")}
        if st.get("roi") is not None:
            r = by_name.get(st["roi"])
            if r is None or T.roi_box(r) is None:
                return None, "a written path", [f"stop roi {st['roi']!r} is not a located region of the item"]
            out.update(box=T.roi_box(r), kind=r.get("kind"), name=st["roi"], region=r, z_req=st.get("z"))
            return out, "the shot's written stop", []
        try:
            u, v = float(st["x"]), float(st["y"])
            z = float(st["z"])
        except (KeyError, TypeError, ValueError):
            return None, "a written path", ["a DETAIL stop is {roi} or {x, y, z} (x, y the centre in the picture, "
                                            "z the zoom of the whole)"]
        if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0 and math.isfinite(z) and z >= 1.0):
            return None, "a written path", [f"stop x, y are 0 to 1 and z at least 1 (got {u}, {v}, {z})"]
        out.update(box=None, point=(u, v), kind=None, name=None, region=None, z_req=z)
        return out, "the shot's written stop", []
    for r in roi:
        if isinstance(r, dict) and r.get("name") == "subject" and T.roi_box(r) is not None:
            sa = shot.get("subject_at")
            at_, line = (sa.get("at"), sa.get("line")) if isinstance(sa, dict) else (sa, None)
            return ({"src": "subject", "authored": False, "box": T.roi_box(r), "kind": r.get("kind"),
                     "name": "subject", "region": r, "at": at_, "line": line},
                    f"the ledger's subject ({T.source_of(r)})", [])
    sa = shot.get("subject_at")
    if sa is not None:
        at_, line = (sa.get("at"), sa.get("line")) if isinstance(sa, dict) else (sa, None)
        cue = _cue_words(at_)
        for r in roi:
            if not isinstance(r, dict) or T.roi_box(r) is None or T.is_person_region(r):
                continue
            if cue and any(_cue_words(c) == cue for c in T.cue_of(r)):
                return ({"src": "subject_at", "authored": False, "box": T.roi_box(r), "kind": r.get("kind"),
                         "name": r.get("name"), "region": r, "at": at_, "line": line},
                        f"the region subject_at names ({r.get('name')!r})", [])
    return None, "no subject: the ledger names no subject region and no subject_at cue names one", []


# --------------------------------------------------------------------------
# The plan
# --------------------------------------------------------------------------


def _no(why: str, problems: list[str] | None = None, **kw) -> dict:
    return dict({"ok": False, "why": why, "problems": problems or []}, **kw)


def plan(shot: dict, item: dict, size, W: int, H: int, *, words=(), t0: float = 0.0, dur: float, cap: float,
         avoid=None, declared_whole: bool = False) -> dict:
    """The bracket for a ``fill_exception`` still, or why it keeps whole + creep. Returns {ok, why, problems}
    and, when ok, {segments, path, detail, timing, z_max, z_open, z_limit}. ``avoid`` is A49's
    [(must_show box, text zone)] for the shot: the detail's placement is steered to the least overlap
    among those that keep its region whole (``tour.avoid_key``)."""
    eff = T.effective_regions(item)
    roi = eff["roi"]
    persons = T.person_regions(item)
    authored_cam = isinstance(shot.get("camera"), list)
    if shot.get("no_zoom") is True and not authored_cam:
        return _no("no_zoom: the still only drifts, never a push (A47)")
    if declared_whole and not authored_cam:
        return _no("the ledger declares the still whole: nothing to single out (doctrine 1)")
    tg, src_why, problems = target(shot, item, roi, persons)
    if problems:
        return _no(src_why, problems)
    if tg is None:
        return _no(src_why)
    authored = tg["authored"]
    zc = zcap(size, cap)
    people_kind = tg.get("kind") in T.PERSON_KINDS or tg.get("kind") == "group" or bool(shot.get("face"))
    face = M.CINE["face_zmax"]
    box = tg.get("box")
    m = B["margin"]
    if box is not None:
        bw, bh = max(box[2] - box[0], EPS), max(box[3] - box[1], EPS)
        z_fit = 1.0 / (max(bw, bh) * m)
        # deepest that keeps the region whole with the compose edge inside each side (A47's 2%)
        z_tight = 1.0 / (max(bw, bh) * (1.0 + 2.0 * M.CINE["compose_edge"]))
        u, v = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
    else:
        u, v = tg["point"]
        z_fit = z_tight = math.inf
    z_req = tg.get("z_req")
    if authored and z_req is not None:
        z_req = float(z_req)
        if z_req > zc + 1e-6:
            return _no("a written path", [
                f"stop z {z_req:g} passes the softness cap: {master_scale(size) * z_req:.2f}x on the 1080p master, "
                f"over {cap:g}x (deepest z {zc:.3f}); A41 refuses it, never softens it"])
        z_d = z_req
    else:
        z_d = min(z_fit, zc)
    if people_kind and not authored:
        z_d = min(z_d, face)

    def framed(z, uu, vv):
        win = window(framing(uu, vv, z, size, W, H), size, W, H)
        return [q for q in persons if T._inside_share(q["box"], win) >= M.CINE["framed_share"] - EPS]

    if z_d > face + EPS and framed(z_d, u, v):
        if authored:
            return _no("a written path", [f"stop z {z_d:g} frames a person past the face cap {face:g} (A43)"])
        z_d = face
    if z_d < B["min_detail_z"] - EPS:
        share = 1.0 / max(z_d, 1.0) ** 2
        why = (f"no room for a detail: the cap allows z {zc:.3f} of the whole ({master_scale(size):.2f}x on the "
               f"master already), so the deepest stop still shows {share:.0%} of the picture (a WHOLE)"
               if zc < z_fit else
               f"the region is nearly the whole picture: framing it shows {share:.0%} of it (a WHOLE)")
        if authored:
            return _no("a written path", [f"the stop is no detail: {why}"])
        return _no(why)
    # A49 steering: where the detail sits, among the placements that keep its region whole
    u, v = clamp_centre(u, v, z_d)
    if avoid and box is not None:
        h = 0.5 / z_d
        ulo, uhi = max(box[2] - h, h), min(box[0] + h, 1.0 - h)
        vlo, vhi = max(box[3] - h, h), min(box[1] + h, 1.0 - h)
        best = None
        n = 9
        for i in range(n):
            for j in range(n):
                cu = ulo + (uhi - ulo) * i / (n - 1) if uhi > ulo else u
                cv = vlo + (vhi - vlo) * j / (n - 1) if vhi > vlo else v
                win = window(framing(cu, cv, z_d, size, W, H), size, W, H)
                key = T.avoid_key(overlap(win, avoid, size, W, H), math.hypot(cu - u, cv - v), inside(box, win))
                if best is None or key < best[0]:
                    best = (key, cu, cv)
        if best is not None and not best[0][0]:
            u, v = best[1], best[2]
    det_win = window(framing(u, v, z_d, size, W, H), size, W, H)
    if box is not None and not inside(box, det_win, 1e-4):
        return _no("the region cannot be framed whole inside the picture at this depth")
    # how deep the hold's creep may go: the region whole, the cap, the face cap
    z_peak = min(zc, z_tight, z_d * M.TOUR["whole_creep_max"])
    if box is not None:
        reach = max(u - box[0], box[2] - u, v - box[1], box[3] - v, EPS)
        z_peak = min(z_peak, 0.5 / reach)
    if people_kind or framed(z_d, u, v):
        z_peak = min(z_peak, face)
    z_peak = max(z_peak, z_d)

    # timing
    kind = tg.get("kind")
    hmin = hold_min(tg.get("region"), kind)
    if authored and isinstance(tg.get("hold"), (int, float)) and not isinstance(tg.get("hold"), bool):
        hmin = max(hmin, float(tg["hold"]))
    du, dv = u - 0.5, v - 0.5
    p_min = leg_s(1.0, z_d, du, dv, z_peak)
    q_min = leg_s(z_peak, 1.0, du, dv, z_peak)
    o_min, e_min = B["open_s"], B["end_s"]
    arrive = until = None
    anchor = None
    if tg.get("at") is not None:
        sp = T.anchor_span(tg["at"], list(words or []), line=tg.get("line"), t0=t0)
        if sp is None or not (t0 - EPS <= sp["t"] <= t0 + dur + EPS):
            if authored:
                return _no("a written path", [f"anchor: the narration over this shot never speaks {tg['at']!r}"])
        else:
            spoken = [w["w"] for w in sp["words"]]
            person = kind in T.PERSON_KINDS and T.names_a_person(spoken, item, persons)
            if person:
                why = T.binding_check(item, spoken, tg.get("region"), persons)
                if why:
                    if authored:
                        return _no("a written path", [f"anchor-identity: {w}" for w in why])
                    return _no("the subject is a person the cue may not bind (A43): " + "; ".join(why))
            if authored and isinstance(tg.get("lead_s"), (int, float)):
                lead = float(tg["lead_s"])
            else:
                lead = (M.CINE["anchor_lead_s"] if sp["measured"] or not person
                        else M.CINE["anchor_estimated_lead_s"])
            arrive = sp["t"] - t0 - lead
            until = sp["end"] - t0
            anchor = {"at": tg["at"], "onset_s": round(sp["t"] - t0, 3), "lead_s": lead,
                      "measured": sp["measured"], "spoken": spoken}
    elif authored and isinstance(tg.get("t"), (int, float)) and not isinstance(tg.get("t"), bool):
        arrive = float(tg["t"])
    need = o_min + p_min + hmin + q_min + e_min
    if arrive is None:
        if dur < need - EPS:
            why = (f"too short: {dur:.1f} s, the whole + push + hold + pull with the settles needs {need:.1f} s")
            return _no("a written path", [why]) if authored else _no(why)
        slack = dur - need
        o, hd, p, q = o_min + slack / 3.0, hmin + slack / 3.0, p_min + slack / 6.0, q_min + slack / 6.0
        arrive = o + p
    else:
        hneed = max(hmin, (until - arrive) if until is not None else 0.0)
        o = arrive - p_min
        rest = dur - arrive - hneed - q_min - e_min
        if o < o_min - EPS or rest < -EPS:
            why = (f"no time around the cue: the detail must arrive at {arrive:.2f} s, after a {o_min:g} s whole and "
                   f"a {p_min:.1f} s push, and hold {hneed:.1f} s, pull {q_min:.1f} s and settle {e_min:g} s before "
                   f"the cut at {dur:.1f} s")
            return _no("a written path", [why]) if authored else _no(why)
        extra = (o - o_min) / 3.0            # a long opening lends a third of itself to a slower push
        o, p = o - extra, p_min + extra
        hd, q = hneed + rest / 2.0, q_min + rest / 2.0
    # the opening breathes in (one way, eased) and never takes more than a third of the push's own depth
    after = M.TOUR["hold_creep_after_s"]
    z_open = 1.0
    if o > after + EPS:
        z_open = min(1.0 + M.TOUR["creep_scale_per_s"] * o, M.TOUR["whole_creep_max"],
                     z_d ** B["open_creep_share"])
    z_hold = z_d
    if hd > after + EPS:
        z_hold = min(z_d * (1.0 + M.TOUR["creep_scale_per_s"] * hd), z_peak)
    whole0 = {"z": 1.0, "x": 0.5, "y": 0.5}
    f_open = dict(whole0, z=z_open)
    f_det = framing(u, v, z_d, size, W, H)
    f_hold = dict(f_det, z=z_hold)
    t1, t2, t3, t4 = o, o + p, o + p + hd, o + p + hd + q
    segs = [{"t0": 0.0, "t1": t1, "a": whole0, "b": f_open, "kind": "creep" if z_open > 1.0 else "hold"},
            {"t0": t1, "t1": t2, "a": f_open, "b": f_det, "kind": "push"},
            {"t0": t2, "t1": t3, "a": f_det, "b": f_hold, "kind": "creep" if z_hold > z_d + EPS else "hold"},
            {"t0": t3, "t1": t4, "a": f_hold, "b": dict(whole0), "kind": "pull"},
            {"t0": t4, "t1": dur, "a": dict(whole0), "b": dict(whole0), "kind": "hold"}]
    share = 1.0 / z_hold ** 2
    scale = "detail" if share <= M.CINE["detail_share"] + EPS else "field"
    limit = min(zc, face) if (people_kind or framed(z_d, u, v)) else zc
    detail = {"src": tg["src"], "name": tg.get("name"), "kind": kind, "authored": authored,
              "box": [round(b, 4) for b in box] if box is not None else None, "centre": [round(u, 4), round(v, 4)],
              "z": round(z_d, 4), "z_hold": round(z_hold, 4), "shows": round(share, 4), "scale": scale,
              "master_upscale": round(master_scale(size) * z_hold, 4), "cap": cap, "face_capped": limit < zc - EPS,
              "why": src_why}
    timing = {"open_s": round(t1, 3), "push_s": round(p, 3), "arrive_s": round(t2, 3), "hold_s": round(hd, 3),
              "pull_s": round(q, 3), "whole_again_s": round(t4, 3), "end_s": round(dur - t4, 3), "anchor": anchor}
    return {"ok": True, "why": src_why, "problems": [], "segments": segs, "path": [whole0, f_det, dict(whole0)],
            "detail": detail, "timing": timing, "z_max": z_hold, "z_open": z_open, "z_limit": limit}
