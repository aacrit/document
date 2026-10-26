"""The move chooser (A54, founder 2026-10-18: "Camera work is too similar on all pictures ... make the camera
movement smart based on the info").

For every still the screenplay leaves to the engine (no ``camera`` path, and no preset or HOLD, which only says
"stay", A51), the planner chooses the move from the still's own sidecar and ledger, deterministically:

| still has                                   | move                                         | end    |
|---------------------------------------------|----------------------------------------------|--------|
| a declared ``whole``, or no subject at all   | WHOLE: the A47 (c) hold or sweep             | whole  |
| ``no_zoom`` (a burning, a collapse)          | PAN: a pan or tilt to the subject at one     | const  |
|                                             | scale, FIELD where the softness cap allows   |        |
| one located person                          | PORTRAIT: the face, then the whole (reveal), | whole  |
|                                             | or the whole, then the face (explain)        | detail |
| two or more located people                  | SURVEY: each person or group (at most 3) in  | whole  |
|                                             | reading order, then the whole                |        |
| text that must show (a document's, or lines)| READ: a reading-pace tilt through it         | detail |
| text that must show on anything else         | EXPLAIN onto the text                        | detail |
| a place or an object with a subject          | EXPLAIN (whole to DETAIL) or REVEAL (DETAIL  | detail |
|                                             | to whole), by the variety rule               | whole  |

Variety, by rule and never at random, film-wide in shot order: every chapter ends at least one still WHOLE and
one in DETAIL; no more than two stills in a row take the same move or the same dominant direction (the third
flips EXPLAIN and REVEAL, a portrait's way round, a survey's order or a pan's end, where the still allows it).
A pan prefers to continue the direction the still before it left in. ``move: "<NAME>"`` on a shot is the
screenplay's own choice and is never changed. Every choice is journaled with its reason.

Pure: no I/O. ``render.build_plan`` calls ``choose_film`` once, before any camera is drawn, and
``render.still_camera`` draws each choice (``tour``'s own stops), falling back, journaled, to the A47 pass
where the still lacks what the move needs."""

from __future__ import annotations

from studio.engine import tour as T

MOVES = T.MOVE_NAMES
# the end each move plans for (doctrine 2.2's scale bands; the drawn path is measured, never promised)
END = {("WHOLE", None): "whole", ("PAN", "far"): "const", ("PAN", "near"): "const",
       ("PORTRAIT", "reveal"): "whole", ("PORTRAIT", "explain"): "detail",
       ("SURVEY", "forward"): "whole", ("SURVEY", "reverse"): "whole", ("READ", None): "detail",
       ("EXPLAIN", None): "detail", ("REVEAL", None): "whole", ("CUTIN", None): "detail"}
DEFAULT_VARIANT = {"PAN": "far", "PORTRAIT": "reveal", "SURVEY": "forward"}
PAGE = "page (whole)"           # READ's whole-page region, for a document that names none
MAX_RUN = 2                       # no more than this many stills in a row with one move, or one direction
CHOOSABLE_PRESETS = (None, "HOLD")


def eligible(shot: dict) -> bool:
    """A still the engine chooses for: no ``camera`` path, no preset or HOLD (A51: HOLD only says "stay"), and
    not a ``fill_exception`` (A50's bracket draws those)."""
    p = shot.get("preset")
    return (shot.get("camera") is None and (p is None or str(p).upper() in ("HOLD",))
            and shot.get("fill_exception") is None)


def _axis_dir(axis: str, sign: float) -> str:
    return ("right" if sign > 0 else "left") if axis == "x" else ("down" if sign > 0 else "up")


def direction(m: dict) -> str | None:
    """The dominant direction a choice plans: ``in``/``out`` for a move that changes scale, the pan's way for a
    PAN or a SURVEY, None for a WHOLE (its breath) and a READ (the page's own order)."""
    mv, var = m["move"], m.get("variant")
    if mv in ("EXPLAIN",) or (mv == "PORTRAIT" and var == "explain"):
        return "in"
    if mv == "REVEAL" or (mv == "PORTRAIT" and var == "reveal"):
        return "out"
    if mv == "SURVEY":
        return "right" if var == "forward" else "left"
    if mv == "PAN" and m.get("axis"):
        far = m.get("far_sign", 1.0)
        return _axis_dir(m["axis"], far if var == "far" else -far)
    return None


def end_of(m: dict) -> str:
    return END.get((m["move"], m.get("variant")), "whole")


def base_choice(shot: dict, item: dict, size) -> dict:
    """The move the grammar table gives one still, before variety: {move, variant, why, flips}. ``flips``
    lists the other (move, variant) pairs the still allows, for the variety rule."""
    w, h = float(size[0]), float(size[1])
    aspect = 16 / 9
    eff = T.effective_regions(item)
    roi = eff["roi"]
    persons = T.person_regions(item)
    n = T.located_persons(persons)
    subj = next((r for r in roi if r.get("name") == "subject" and T.roi_box(r) is not None), None)
    texts = [r for r in T.must_show_regions(item) if r.get("kind") == "text" and T.roi_box(r) is not None]
    cls = item.get("class")
    no_zoom = shot.get("no_zoom") is True or item.get("no_zoom") is True

    def out(move, why, variant=None, flips=(), **kw):
        return dict({"move": move, "variant": variant if variant is not None else DEFAULT_VARIANT.get(move),
                     "why": why, "flips": list(flips)}, **kw)

    if item.get("whole") is True:
        return out("WHOLE", "the ledger says whole: the A47 (c) hold or sweep")
    if no_zoom:
        tgt = subj or (texts[0] if texts else None) or (persons[0]["entry"] if n == 1 else None)
        if tgt is None:
            return out("WHOLE", "no_zoom and no subject: the (c) hold or sweep at the fill, no scale change")
        b = T.roi_box(tgt)
        cx, cy = (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0
        axis = T.long_axis(size, aspect) or ("x" if w >= h else "y")
        c = cx if axis == "x" else cy
        # the far end is the one away from the subject; the pan runs toward it
        far_sign = 1.0 if c >= 0.5 else -1.0
        return out("PAN", "no_zoom: a pan or tilt to the subject at one scale, never a zoom",
                   flips=[("PAN", "near")], axis=axis, far_sign=far_sign)
    if n == 1 and (cls in (None, "person") or (subj or {}).get("kind") in T.PERSON_KINDS or subj is None):
        return out("PORTRAIT", "one located person: the face, then the whole",
                   flips=[("PORTRAIT", "explain")])
    if n >= 2 and (cls in (None, "person", "crowd") or (subj or {}).get("kind") in (*T.PERSON_KINDS, "group")
                   or subj is None):
        return out("SURVEY", f"{n} located people: each person or group in reading order, then the whole",
                   flips=[("SURVEY", "reverse"), ("REVEAL", None)])
    if cls == "document" and not texts:
        # a page: its subject when the rulebook found text there, else the whole page is the text it reads
        if subj is not None and subj.get("kind") == "text":
            return out("READ", "a document: read its text at reading pace", target="subject")
        return out("READ", "a document with no text region: the whole page read at reading pace", target=PAGE)
    if texts:
        t0 = texts[0]
        if cls == "document" or isinstance(t0.get("lines"), int):
            return out("READ", f"must_show text {t0.get('name')!r}: read at reading pace",
                       target=t0.get("name"))
        return out("EXPLAIN", f"must_show text {t0.get('name')!r} on a {cls or 'picture'}: the whole, then in onto it",
                   target=t0.get("name"), flips=[("REVEAL", None)])
    if subj is not None:
        return out("EXPLAIN", f"a {cls or 'picture'} with a subject: the whole, then a DETAIL on it",
                   flips=[("REVEAL", None)])
    return out("WHOLE", "no subject: the whole, the A47 (c) hold or sweep")


def _apply(m: dict, move: str, variant, reason: str) -> None:
    m.setdefault("was", f"{m['move']}{'/' + m['variant'] if m.get('variant') else ''}")
    m["move"], m["variant"] = move, variant if variant is not None else DEFAULT_VARIANT.get(move)
    m["variety"] = reason
    # the flip is undone by flipping back: keep the alternatives the still allows
    alts = {("EXPLAIN", None): [("REVEAL", None)], ("REVEAL", None): [("EXPLAIN", None)],
            ("PORTRAIT", "reveal"): [("PORTRAIT", "explain")], ("PORTRAIT", "explain"): [("PORTRAIT", "reveal")],
            ("SURVEY", "forward"): [("SURVEY", "reverse"), ("REVEAL", None)],
            ("SURVEY", "reverse"): [("SURVEY", "forward"), ("REVEAL", None)],
            ("PAN", "far"): [("PAN", "near")], ("PAN", "near"): [("PAN", "far")]}
    m["flips"] = list(alts.get((m["move"], m["variant"]), []))


def _chapter_ok(ms: list[dict], idx: list[int]) -> tuple[bool, bool]:
    ends = [end_of(ms[i]) for i in idx]
    return "whole" in ends, "detail" in ends


def choose_film(stills: list[dict]) -> list[dict]:
    """The chooser over the film, in shot order. ``stills``: [{id, chapter, shot, item, size}]. Returns one
    choice per still, {id, move, variant, why, authored, variety?, was?}; a still the engine may not choose for
    (a ``camera`` path, a deliberate preset, a fill exception) gets None."""
    ms: list[dict | None] = []
    for st in stills:
        shot = st["shot"]
        if shot.get("move") is not None:
            mv = str(shot["move"]).upper()
            var = shot.get("move_variant")
            ms.append({"id": st["id"], "move": mv, "variant": var or DEFAULT_VARIANT.get(mv), "authored": True,
                       "why": f"the screenplay's own move: {mv}", "flips": []})
            continue
        if not eligible(shot):
            ms.append(None)
            continue
        m = base_choice(shot, st["item"], st["size"])
        m.update(id=st["id"], authored=False)
        ms.append(m)
    chapters: dict = {}
    for i, (st, m) in enumerate(zip(stills, ms)):
        if m is not None:
            chapters.setdefault(st.get("chapter"), []).append(i)

    # 1. every chapter ends at least one still WHOLE and one in DETAIL (flip the first still that allows it)
    for cid, idx in chapters.items():
        if len(idx) < 2:
            continue
        for want in ("whole", "detail"):
            has_w, has_d = _chapter_ok(ms, idx)
            if (has_w if want == "whole" else has_d):
                continue
            for i in idx:
                m = ms[i]
                if m["authored"]:
                    continue
                flip = next(((mv, var) for mv, var in m["flips"] if END.get((mv, var or DEFAULT_VARIANT.get(mv)))
                             == want), None)
                if flip is None:
                    continue
                keep = "detail" if want == "whole" else "whole"
                trial = dict(m, move=flip[0], variant=flip[1] or DEFAULT_VARIANT.get(flip[0]))
                rest = [end_of(ms[j]) for j in idx if j != i] + [end_of(trial)]
                if keep in [end_of(ms[j]) for j in idx] and keep not in rest:
                    continue                                   # never trade the chapter's only other end
                _apply(m, flip[0], flip[1], f"chapter {cid} had no {want.upper()} end")
                break

    # 2. no more than MAX_RUN in a row with one move or one direction; a pan continues the direction before it
    order = [i for i, m in enumerate(ms) if m is not None]
    for k, i in enumerate(order):
        m = ms[i]
        prev = [ms[j] for j in order[max(0, k - MAX_RUN):k]]
        if m["authored"]:
            continue
        if m["move"] == "PAN" and prev:
            pd = direction(prev[-1])
            alt = dict(m, variant="near" if m["variant"] == "far" else "far")
            if pd and direction(m) != pd and direction(alt) == pd:
                _apply(m, "PAN", alt["variant"], f"continues the {pd} the still before left in")
        cid = stills[i].get("chapter")
        idx = chapters.get(cid, [])
        for what in ("move", "direction"):
            key = (lambda x: x["move"]) if what == "move" else direction
            if len(prev) < MAX_RUN or key(m) is None or not all(key(p) == key(m) for p in prev):
                continue
            for mv, var in m["flips"]:
                trial = dict(m, move=mv, variant=var or DEFAULT_VARIANT.get(mv))
                if key(trial) == key(m):
                    continue
                if what == "direction" and all(p["move"] == trial["move"] for p in prev):
                    continue                                   # never trade a direction run for a move run
                before = _chapter_ok(ms, idx)
                saved = dict(m)
                _apply(m, mv, var, f"a third {what} in a row ({key(saved)})")
                after = _chapter_ok(ms, idx)
                if len(idx) >= 2 and ((before[0] and not after[0]) or (before[1] and not after[1])):
                    m.clear()
                    m.update(saved)                            # the chapter's WHOLE/DETAIL rule comes first
                    continue
                break
    for m in ms:
        if m is not None:
            m["end"] = end_of(m)
            m["direction"] = direction(m)
    return ms
