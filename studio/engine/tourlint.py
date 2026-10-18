"""Cinematography ticket #4: the tour lint module (GRAMMAR A49, BRAND-KIT
14d). Pure functions over a still's tour path (``cam["tour"]``, the ``tl``
dict ``studio/engine/tour.py`` builds) and its end-pose composition
(``cam["subject"]``), plus the per-film groupings (scale variety, direction
monotony) the founder-approved spec's section 4 lists as guidance.

Every check here is GUIDANCE (warn and reviewer item: pacing and framing
choice are the founder's to judge, A39, ``pacing-is-guidance``), with the one
exception the spec states: ``subject_under_text`` BLOCKS when a ``must_show``
region is covered while a text zone is up (truth, not pacing: a burned
caption or a must-show region a viewer cannot read is a false "show as
was"). Nothing here refuses a render on its own; ``check_film`` below is a
read-only, in-memory report (the CLI), not wired into ``render.build_plan``'s
own preflight.

Reuse, not reimplementation (house rule): ``end_pose_composition`` reads
``tour.compose_verdict``'s own numbers (A47, ticket #2) and only adds the
borderline flag; ``lead_room_check`` reads the same verdict's ``lead_room``
and ``lead_ok``; ``phone_legibility_report`` calls ``motion.phone_legibility``
(ticket #8) rather than a second threshold. The pan and zoom speed checks are
new, tighter guides beside (not instead of) the existing outer-ceiling
warnings already in ``render.tour_lints`` (``tour-speed``, a third of the
frame a second and 15% a second): both may warn independently, so this module
never re-implements that ceiling.

The end-pose composition's borderline logic (``_BORDERLINE_BIN``,
``_borderline``) is ported from Ratio's rulebook, ``PROPORTION_BIN`` and
``borderlineIn`` (ratio/web/src/engine/rules.ts:36-51, 148-154, 250): a
measurement is binned before any rule reads it, and a value within half a
bin of a band edge is reported "borderline", never silently flipped to the
other side of the edge. The band edges here are ``motion.CINE``'s own
``golden_band`` (0.30, 0.44) and its mirror (0.56, 0.70), the same numbers
A47's ``compose_verdict`` already classifies against.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Sequence

from studio.engine import motion as M
from studio.engine import tour as T

SEVEN_SECOND_RULE_S = 7.0          # doctrine 8: a point crosses the frame no faster than this
ZOOM_CRUISE_GUIDE = 0.05           # 5%/s cruise (today's 15%/s stays the outer tour-speed ceiling)
SETTLE_MIN_S = M.CINE["settle_s"]          # 1.0 s
SETTLE_READ_MIN_S = M.CINE["settle_read_s"]  # 1.5 s for text, a face or a person
MIN_MOVE_AFTER_CUT_S = 0.5
DIRECTION_MONOTONY_MAX_RUN = 4
# `motion.CINE` is the single source for these (cinematography ticket #4; ticket #3's sheets.py reads the
# same keys, moved there out of its own module): under_text_share (the warn overlap), whole_share and
# detail_share (doctrine 2.2's scale bands).
SUBJECT_UNDER_TEXT_WARN_SHARE = M.CINE["under_text_share"]
SUBJECT_UNDER_TEXT_BLOCK_SHARE = 0.90       # "covered": a must_show region effectively hidden (this module's own)
SCALE_VARIETY_MIN_STILLS = 5
DOMINANT_VECTOR_MIN_FRAC = 0.02             # below this share of the window, a move reads as noise
# Ratio rules.ts:37 PROPORTION_BIN = 0.02; borderlineIn's tolerance is half of it
_BORDERLINE_BIN = 0.02


# --------------------------------------------------------------------------
# pan-speed-px, zoom-speed: the 7-second rule, derived from the plan's fps
# --------------------------------------------------------------------------


def _frame_windows(tl: dict, fps: float) -> list[tuple[float, tuple]]:
    """The tour's picture-pixel windows at every rendered frame (``T.window``
    sampled through ``T.samples(tl, hz=fps)``): the same per-frame sampling
    ``render.tour_lints`` uses for ``tour-fills`` and ``tour-speed``."""
    size, aspect = tl["size"], tl["aspect"]
    return [(t, T.window(size, aspect, f["z"], f["x"], f["y"])) for t, f in T.samples(tl, hz=fps)]


def pan_speed_px(tl: dict, fps: float, *, W: int = 1920, H: int = 1080) -> dict:
    """``pan-speed-px`` (guidance, GRAMMAR A49, doctrine 8): the 7-second
    rule, "a point takes at least 7 s to cross the frame", measured on
    rendered frames at the plan's own fps. The guide is the output frame's
    span divided by ``SEVEN_SECOND_RULE_S * fps`` on each axis (about 11.4
    and 6.4 px/frame at 24p, 9.1 and 5.1 at 29.97): since every TOUR frame
    fills the output (``tour-fills``), a window-centre travel of a share
    ``f`` of the window's own width in one frame is a screen travel of
    ``f * W`` px on that frame. Returns {ok, max_h_px, max_v_px, guide_h_px,
    guide_v_px, at_h_s, at_v_s}."""
    guide_h = W / (SEVEN_SECOND_RULE_S * fps)
    guide_v = H / (SEVEN_SECOND_RULE_S * fps)
    wins = _frame_windows(tl, fps)
    max_h = max_v = 0.0
    at_h = at_v = 0.0
    for (ta, a), (tb, b) in zip(wins, wins[1:]):
        ww, wh = a[2] - a[0], a[3] - a[1]
        dh = abs((b[0] + b[2]) - (a[0] + a[2])) / 2.0 / ww * W if ww > 0 else 0.0
        dv = abs((b[1] + b[3]) - (a[1] + a[3])) / 2.0 / wh * H if wh > 0 else 0.0
        if dh > max_h:
            max_h, at_h = dh, tb
        if dv > max_v:
            max_v, at_v = dv, tb
    ok = max_h <= guide_h + 1e-6 and max_v <= guide_v + 1e-6
    return {"ok": ok, "max_h_px": round(max_h, 3), "max_v_px": round(max_v, 3),
            "guide_h_px": round(guide_h, 3), "guide_v_px": round(guide_v, 3),
            "at_h_s": round(at_h, 3), "at_v_s": round(at_v, 3), "fps": fps}


def zoom_speed_cruise(tl: dict, fps: float, *, guide: float = ZOOM_CRUISE_GUIDE) -> dict:
    """``zoom-speed`` (guidance, GRAMMAR A49): a cruise of 5%/s or less
    (today's 15%/s stays the outer ``tour-speed`` ceiling in
    ``render.tour_lints``). Peak scale-change rate between consecutive
    rendered frames, as ``tour.speed_report`` measures it, against the
    tighter guide."""
    wins = _frame_windows(tl, fps)
    peak = 0.0
    at = 0.0
    for (ta, a), (tb, b) in zip(wins, wins[1:]):
        dt = tb - ta
        if dt <= T.EPS:
            continue
        vz = abs(math.log((a[2] - a[0]) / max(b[2] - b[0], T.EPS))) / dt
        if vz > peak:
            peak, at = vz, tb
    pct = math.exp(peak) - 1.0
    return {"ok": pct <= guide + 1e-6, "zoom_per_s": round(pct, 4), "guide": guide, "at_s": round(at, 3)}


# --------------------------------------------------------------------------
# settle-before-move, min-move-after-cut
# --------------------------------------------------------------------------


def settle_before_move(tl: dict, *, kinds: dict | None = None) -> list[dict]:
    """``settle-before-move`` (guidance, A47 principle 5): a stop settles at
    least 1.0 s (1.5 s for text, a face or a person, ``tour.settle_for``'s
    own numbers) before the next leg starts. ``kinds`` maps a hold segment's
    start time (``round(t0, 3)``) to the stop's picture-class kind
    (``"face"``, ``"person"``, ``"text"``, ...), when the caller knows it;
    unmapped stops get the plain 1.0 s floor. Only a "move" segment's own
    settle (the run of "hold"/"creep" segments immediately before it) is
    checked: the still's very first stop settles into the shot's own start,
    and the last stop settles into the cut, which A47's own ``settle_s``
    already enforces. Returns violations [{t, settle_s, required_s, kind}]."""
    kinds = kinds or {}
    segs = tl["segments"]
    out = []
    for i, g in enumerate(segs):
        if g["kind"] != "move":
            continue
        settle_s, j = 0.0, i - 1
        while j >= 0 and segs[j]["kind"] in ("hold", "creep"):
            settle_s += segs[j]["t1"] - segs[j]["t0"]
            j -= 1
        if j < 0 and i == 0:
            continue  # nothing precedes the shot's own first stop
        kind = kinds.get(round(segs[j + 1]["t0"], 3)) if j + 1 <= i - 1 else None
        required = SETTLE_READ_MIN_S if kind in T.READ_KINDS else SETTLE_MIN_S
        if settle_s < required - 1e-6:
            out.append({"t": round(g["t0"], 3), "settle_s": round(settle_s, 3), "required_s": required,
                        "kind": kind})
    return out


def min_move_after_cut(tl: dict, *, min_s: float = MIN_MOVE_AFTER_CUT_S, continues_across_cut: bool = False) -> dict:
    """``min-move-after-cut`` (guidance, section 6): a move starting within
    ``min_s`` of the shot's own cut-in (``t = 0``) warns, unless it continues
    a move already running across the cut (the caller's own knowledge: a
    ``match: prev`` shot, or a dissolve, carries continuity this function
    cannot see from one shot's ``tl`` alone)."""
    first_move = next((g for g in tl["segments"] if g["kind"] == "move"), None)
    if first_move is None or continues_across_cut:
        return {"ok": True, "move_t0": None, "min_s": min_s}
    ok = first_move["t0"] >= min_s - 1e-6
    return {"ok": ok, "move_t0": round(first_move["t0"], 3), "min_s": min_s}


# --------------------------------------------------------------------------
# end-pose-composition (Ratio's band table and borderline logic), lead-room
# --------------------------------------------------------------------------


def _composition_band_edges() -> tuple[float, float, float, float]:
    lo, hi = M.CINE["golden_band"]
    return (lo, hi, 1.0 - hi, 1.0 - lo)


def _borderline(v: float, *, bin_size: float = _BORDERLINE_BIN) -> bool:
    """Ratio ``borderlineIn`` (rules.ts:152-154): within half a bin of a band
    edge. ``golden_band``'s own edges (0.30, 0.44, 0.56, 0.70) are Ratio's
    ``PROPORTION_BANDS`` edges exactly (golden covers 0.30-0.44, halves
    0.44-0.56, golden-long 0.56-0.70)."""
    half = bin_size / 2.0
    return any(abs(v - e) < half for e in _composition_band_edges())


def end_pose_composition(verdict: dict) -> dict:
    """``end-pose-composition`` (guidance, A47 principle 6, GRAMMAR A49):
    reuses ``tour.compose_verdict``'s own numbers unchanged (``verdict`` is
    that dict, or ``cam["subject"]["last"]``/``["stop"]``, A47 already
    computes one per stop) and adds a borderline flag per axis that has
    room: a subject centre (``subject_x``/``subject_y``) within half a bin
    (0.01) of a band edge is reported borderline, never flipped to another
    verdict (Ratio's law 2). Returns ``verdict`` plus ``borderline`` and
    ``borderline_axes``."""
    axes = []
    for axis, room_key, val_key in (("x", "room_x", "subject_x"), ("y", "room_y", "subject_y")):
        if verdict.get(room_key) and val_key in verdict and _borderline(verdict[val_key]):
            axes.append(axis)
    return dict(verdict, borderline=bool(axes), borderline_axes=axes)


def lead_room_check(verdict: dict) -> dict:
    """``lead-room`` (guidance, A47 principle 6): room ahead on the facing
    axis at least the room behind. Surfaces ``compose_verdict``'s own
    ``lead_room``/``room_behind``/``lead_ok`` (computed only when the
    subject faces left or right) as a named lint, rather than a second
    measurement."""
    if "lead_ok" not in verdict:
        return {"ok": True, "applies": False}
    behind = verdict.get("room_behind")
    ratio = (verdict["lead_room"] / behind) if behind else None
    return {"ok": bool(verdict["lead_ok"]), "applies": True, "lead_room": verdict.get("lead_room"),
            "room_behind": behind, "ratio": ratio}


# --------------------------------------------------------------------------
# subject-under-text: BLOCK only for a covered must_show region
# --------------------------------------------------------------------------


def _frame_box_at(window: tuple, size, box: tuple) -> tuple | None:
    """``box`` (picture fractions) projected through ``window`` (picture
    pixels) into frame fractions [0, 1], clipped to what is on screen; None
    when none of it is visible at this window."""
    iw, ih = float(size[0]), float(size[1])
    x0, y0, x1, y1 = window
    ww, wh = x1 - x0, y1 - y0
    if ww <= 0 or wh <= 0:
        return None
    bx0, by0, bx1, by1 = box[0] * iw, box[1] * ih, box[2] * iw, box[3] * ih
    fx0, fy0 = max(0.0, (bx0 - x0) / ww), max(0.0, (by0 - y0) / wh)
    fx1, fy1 = min(1.0, (bx1 - x0) / ww), min(1.0, (by1 - y0) / wh)
    if fx1 <= fx0 or fy1 <= fy0:
        return None
    return fx0, fy0, fx1, fy1


def _overlap_share(frame_box: tuple, zone_box: tuple) -> float:
    ax0, ay0, ax1, ay1 = frame_box
    zx0, zy0, zx1, zy1 = zone_box
    iw = max(0.0, min(ax1, zx1) - max(ax0, zx0))
    ih = max(0.0, min(ay1, zy1) - max(ay0, zy0))
    full = (ax1 - ax0) * (ay1 - ay0)
    return (iw * ih) / full if full > 0 else 0.0


def subject_under_text(wins: Sequence[tuple], subject_box: tuple, size, *, text_spans: Sequence[dict],
                        is_face: bool = False, must_show: bool = False,
                        warn_share: float = SUBJECT_UNDER_TEXT_WARN_SHARE,
                        block_share: float = SUBJECT_UNDER_TEXT_BLOCK_SHARE) -> dict:
    """``subject-under-text`` (section 4): overlap of a subject or
    ``must_show`` box (picture fractions) with the LT, subtitle, overlay or
    mark zone while that zone is on screen (``text_spans``:
    ``[{"zone", "box" (frame fractions), "t0", "t1"}]``). A face is never
    checked (A43: the house's own text is not shrunk for a face, but a face
    is also never the thing this lint is protecting). GUIDANCE at
    ``warn_share`` (10% overlap); BLOCK only when ``must_show`` is true and
    the overlap reaches ``block_share`` (effectively covered: a burned
    caption or a must-show region a viewer cannot read, A0's truth guard,
    not a pacing choice)."""
    if is_face:
        return {"ok": True, "block": False, "max_overlap": 0.0, "at_s": None, "zone": None}
    worst, worst_at, worst_zone = 0.0, None, None
    for t, win in wins:
        active = [sp for sp in text_spans if sp["t0"] - 1e-9 <= t <= sp["t1"] + 1e-9]
        if not active:
            continue
        fb = _frame_box_at(win, size, subject_box)
        if fb is None:
            continue
        for sp in active:
            share = _overlap_share(fb, sp["box"])
            if share > worst:
                worst, worst_at, worst_zone = share, t, sp.get("zone")
    block = must_show and worst >= block_share - 1e-9
    ok = worst < warn_share - 1e-9
    return {"ok": ok, "block": block, "max_overlap": round(worst, 4), "at_s": worst_at, "zone": worst_zone}


# --------------------------------------------------------------------------
# direction-monotony
# --------------------------------------------------------------------------


def dominant_vector(tl: dict, *, min_frac: float = DOMINANT_VECTOR_MIN_FRAC) -> str | None:
    """The still's net move direction (A47 principle 7: "direction is where
    the subject is"), from its first stop to its last, on whichever axis
    travelled more of the window; ``None`` for a hold, a creep-only pass, or
    a net move under ``min_frac`` of the window (noise, not a direction)."""
    size, aspect = tl["size"], tl["aspect"]
    stops = tl["stops"]
    if len(stops) < 2:
        return None
    a, b = stops[0], stops[-1]
    wa = T.window(size, aspect, a["z"], a["x"], a["y"])
    wb = T.window(size, aspect, b["z"], b["x"], b["y"])
    ww, wh = wa[2] - wa[0], wa[3] - wa[1]
    fx = ((wb[0] + wb[2]) - (wa[0] + wa[2])) / 2.0 / ww if ww > 0 else 0.0
    fy = ((wb[1] + wb[3]) - (wa[1] + wa[3])) / 2.0 / wh if wh > 0 else 0.0
    if max(abs(fx), abs(fy)) < min_frac:
        return None
    return ("right" if fx > 0 else "left") if abs(fx) >= abs(fy) else ("down" if fy > 0 else "up")


def direction_monotony(vectors: Sequence[str | None], *, max_run: int = DIRECTION_MONOTONY_MAX_RUN) -> list[dict]:
    """``direction-monotony`` (guidance, A47 principle 7): more than
    ``max_run`` consecutive stills (skipping the ``None`` of a hold) with the
    same dominant vector warns, so no meaning arrives by accident. Returns
    [{start, len, direction}] for each run over the limit."""
    out, i, n = [], 0, len(vectors)
    while i < n:
        v = vectors[i]
        j = i
        while j < n and vectors[j] == v:
            j += 1
        if v is not None and j - i > max_run:
            out.append({"start": i, "len": j - i, "direction": v})
        i = j
    return out


# --------------------------------------------------------------------------
# scale-variety, wide-before-detail (doctrine 2 and 3: window share derives scale)
# --------------------------------------------------------------------------


def scale_of_share(share: float) -> str:
    """Doctrine 2.2 (``motion.CINE["whole_share"]``/``["detail_share"]``):
    WHOLE shows 0.8 or more of the picture, FIELD 0.4 to 0.8, DETAIL 0.4 or
    less. Derived from the end pose's shown share (``compose_verdict``'s
    ``shown``), so an authored ``scale`` field (A43's schema) can be checked
    against this rather than trusted blind."""
    if share >= M.CINE["whole_share"] - 1e-9:
        return "whole"
    if share <= M.CINE["detail_share"] + 1e-9:
        return "detail"
    return "field"


def scale_variety(chapters: dict, *, min_stills: int = SCALE_VARIETY_MIN_STILLS) -> list[dict]:
    """``scale-variety`` (guidance, doctrine 2): every chapter of
    ``min_stills`` or more stills carries at least one WHOLE and one DETAIL.
    ``chapters`` maps a chapter id to its ordered list of still scales
    (``None`` where a still has no tour). Returns the chapters that miss
    either."""
    out = []
    for cid, scales in chapters.items():
        scales = [s for s in scales if s]
        if len(scales) < min_stills:
            continue
        has_whole, has_detail = "whole" in scales, "detail" in scales
        if not (has_whole and has_detail):
            out.append({"chapter": cid, "count": len(scales), "has_whole": has_whole, "has_detail": has_detail})
    return out


def wide_before_detail(scales: Sequence[str | None], *, declared_reveal: Sequence[bool] | None = None) -> list[dict]:
    """``wide-before-detail`` (guidance, doctrine 3): no DETAIL on a picture
    not already seen wider (WHOLE or FIELD) earlier in the same showing
    (``scales``, one picture's stills in viewing order), unless that still
    declares a reveal. Returns [{index}] for each violation."""
    declared_reveal = declared_reveal or [False] * len(scales)
    out, seen_wide = [], False
    for i, sc in enumerate(scales):
        if sc == "detail" and not seen_wide and not declared_reveal[i]:
            out.append({"index": i})
        if sc in ("whole", "field"):
            seen_wide = True
    return out


# --------------------------------------------------------------------------
# phone-legibility: reused, not reimplemented (ticket #8, motion.phone_legibility)
# --------------------------------------------------------------------------


def phone_legibility_report(width: int = 1920, height: int = 1080, *, extra: dict | None = None) -> dict:
    """``phone-legibility`` (guidance only; founder ruling, 2026-10-17: the
    primary target is 1080p, and phone legibility never drives framing or
    size). This module adds no new threshold: it calls
    ``motion.phone_legibility`` (ticket #8's 693 px landscape measure,
    already journaled by ``render.phone_legibility_lint``) so the CLI's
    per-run report can show it beside the tour lints."""
    rows = M.phone_legibility(width, height, extra=extra)
    small = [r for r in rows if not r["ok"]]
    return {"ok": not small, "rows": rows, "under": small, "phone_width_px": M.PHONE["width_px"],
            "min_px": M.PHONE["min_px"]}


# --------------------------------------------------------------------------
# Per-still and per-film wiring (the CLI)
# --------------------------------------------------------------------------


def check_still(s: dict, cam: dict, size, *, fps: float, text_spans: Sequence[dict] | None = None,
                 must_show_boxes: Sequence[dict] | None = None, settle_kinds: dict | None = None) -> dict:
    """Every GUIDANCE tour lint, plus ``subject-under-text``'s one BLOCK
    case, for one TOUR still. Returns a per-still dict with ``warnings`` and
    ``blocks`` naming which lints fired."""
    out = {"id": s.get("id")}
    tl = cam.get("tour")
    if not tl:
        return out
    warnings: list[str] = []
    blocks: list[str] = []

    out["pan"] = pan_speed_px(tl, fps)
    if not out["pan"]["ok"]:
        warnings.append("pan-speed-px")
    out["zoom"] = zoom_speed_cruise(tl, fps)
    if not out["zoom"]["ok"]:
        warnings.append("zoom-speed")
    out["settle"] = settle_before_move(tl, kinds=settle_kinds)
    if out["settle"]:
        warnings.append("settle-before-move")
    out["min_move"] = min_move_after_cut(tl, continues_across_cut=bool(s.get("_continues_move")))
    if not out["min_move"]["ok"]:
        warnings.append("min-move-after-cut")

    sub = cam.get("subject") or {}
    verdict = sub.get("last")
    share = None
    if verdict is not None:
        out["composition"] = end_pose_composition(verdict)
        if out["composition"]["borderline"]:
            warnings.append("end-pose-composition:borderline")
        out["lead_room"] = lead_room_check(verdict)
        if out["lead_room"]["applies"] and not out["lead_room"]["ok"]:
            warnings.append("lead-room")
        share = verdict.get("shown")
    out["scale"] = scale_of_share(share) if share is not None else None
    out["direction"] = dominant_vector(tl)

    box, is_face = sub.get("box"), sub.get("kind") == "face"
    spans = list(text_spans or [])
    if box is not None and spans:
        r = subject_under_text([(t, w) for t, w in _frame_windows(tl, fps)], box, size, text_spans=spans,
                                is_face=is_face, must_show=False)
        out["subject_under_text"] = r
        if not r["ok"]:
            warnings.append("subject-under-text")
    if must_show_boxes and spans:
        rows = []
        for ms in must_show_boxes:
            r = subject_under_text([(t, w) for t, w in _frame_windows(tl, fps)], ms["box"], size, text_spans=spans,
                                    is_face=ms.get("kind") == "face", must_show=True)
            r["name"] = ms.get("name")
            rows.append(r)
            if r["block"]:
                blocks.append(f"subject-under-text:{ms.get('name')}")
            elif not r["ok"]:
                warnings.append(f"subject-under-text:{ms.get('name')}")
        out["must_show_under_text"] = rows

    out["warnings"], out["blocks"] = warnings, blocks
    return out


def check_film(film: Path, *, W: int = 1920, H: int = 1080, skip_sound_lints: bool = False) -> dict:
    """The tour lints over a whole film's screenplay, planned in memory
    (``sheets.plan_stills``, ticket #3: ``write_overlays=False``, the clip
    caches redirected away from the film folder, so this read-only report
    writes nothing into it; ``--skip-sound-lints`` drops music cues in
    memory the same way the contact-sheet tool does, so this CLI runs before
    a score is settled). Groups stills by chapter (``s["_part"]``, the
    screenplay's own part id) for ``scale-variety`` and runs
    ``direction-monotony`` over the stills in viewing order. Every text zone
    that is on screen for a still's whole duration today (the class glyph,
    A31/A42: it never goes off) is checked for ``subject-under-text``; a
    shot's own lower third or subtitle timing is left to a follow-up (Real
    World's archive stills carry neither today)."""
    from PIL import Image

    from studio.engine import journal as J
    from studio.engine import sheets as SH

    journal = J.Journal(film=f"tourlint-{Path(film).name}")
    plan = SH.plan_stills(Path(film), journal, skip_sound_lints=skip_sound_lints)
    fps = float(plan["fps"])

    stills = [s for s in plan["shots"] if s["kind"] in ("archive_still", "drawn")
              and s.get("_item", {}).get("_path") and s.get("_cam", {}).get("tour")]
    per_still, chapters, vectors = [], {}, []
    for s in stills:
        cam = s["_cam"]
        with Image.open(s["_item"]["_path"]) as im:
            size = im.size
        text_spans = [{"zone": "mark-glyph", "box": M.MARK_GLYPH_ZONE, "t0": 0.0, "t1": float(s["_dur"])}]
        must_show = [{"name": r.get("name"), "box": T.roi_box(r), "kind": r.get("kind")}
                     for r in (s.get("_item", {}).get("roi") or [])
                     if isinstance(r, dict) and r.get("must_show") is True and T.roi_box(r) is not None]
        row = check_still(s, cam, size, fps=fps, text_spans=text_spans, must_show_boxes=must_show)
        per_still.append(row)
        chapters.setdefault(s.get("_part"), []).append(row.get("scale"))
        vectors.append(row.get("direction"))

    return {"film": str(film), "fps": fps, "still_count": len(per_still), "stills": per_still,
            "scale_variety": scale_variety(chapters), "direction_monotony": direction_monotony(vectors),
            "phone_legibility": phone_legibility_report(W, H),
            "blocks": [b for row in per_still for b in row["blocks"]]}


def _print_report(report: dict) -> None:
    print(f"tourlint: {report['film']} ({report['still_count']} toured stills, fps {report['fps']:.3f})")
    for row in report["stills"]:
        tag = " ".join(row.get("warnings") or [])
        blk = " ".join(f"BLOCK:{b}" for b in row.get("blocks") or [])
        print(f"  {row['id']:>6}  scale={row.get('scale')!s:<7} dir={row.get('direction')!s:<6} {tag} {blk}".rstrip())
    if report["scale_variety"]:
        for row in report["scale_variety"]:
            print(f"  scale-variety: chapter {row['chapter']} ({row['count']} stills) "
                  f"whole={row['has_whole']} detail={row['has_detail']}")
    for row in report["direction_monotony"]:
        print(f"  direction-monotony: {row['len']} stills {row['direction']} from #{row['start']}")
    if not report["phone_legibility"]["ok"]:
        for r in report["phone_legibility"]["under"]:
            print(f"  phone-legibility: {r['element']} {r['px']:.1f}px < {report['phone_legibility']['min_px']}px")
    if report["blocks"]:
        print(f"BLOCK: {len(report['blocks'])} finding(s): {report['blocks']}")
    else:
        print("no BLOCK findings")


def main(argv: Sequence[str] | None = None) -> int:
    import argparse
    import json as json_mod

    ap = argparse.ArgumentParser(description="Cinematography ticket #4: tour lints, read-only, no render.")
    ap.add_argument("--check", required=True, type=Path, metavar="FILM_DIR", help="a film's folder")
    ap.add_argument("--json", type=Path, help="also write the full report as JSON")
    ap.add_argument("--skip-sound-lints", action="store_true",
                    help="drop the music cues in memory (never written), as the contact-sheet tool does, so this "
                         "runs before a score is settled")
    args = ap.parse_args(argv)

    report = check_film(args.check, skip_sound_lints=args.skip_sound_lints)
    _print_report(report)
    if args.json:
        args.json.write_text(json_mod.dumps(report, indent=2, default=str), encoding="utf-8")
    return 1 if report["blocks"] else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
