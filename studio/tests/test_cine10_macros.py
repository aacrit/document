"""A54 (cinematography ticket #10 and the smart camera): READ, PORTRAIT and SURVEY; the move chooser and its
variety rule; classic coverage (CUT-IN); entering mid-move; and the face cap's founder ruling (2026-10-18).
Pure geometry on small synthetic sizes; nothing is rendered and no film is read."""

import math

import pytest

from studio.engine import motion as M
from studio.engine import moves as MV
from studio.engine import render as R
from studio.engine import tour as T
from studio.engine import tourlint as TL

W, H = 640, 360
A = W / H
BIG = (4000, 3000)           # room under the 3x softness cap for a real DETAIL
SMALL = (900, 675)           # a small scan: the softness cap stops short of DETAIL


def person(x, y, w, h, name="person-1", **kw):
    return dict({"name": name, "x": x, "y": y, "w": w, "h": h, "source": "human"}, **kw)


def region(name, x, y, w, h, kind="place", **kw):
    return dict({"name": name, "x": x, "y": y, "w": w, "h": h, "kind": kind, "source": "human"}, **kw)


def shot_of(item, dur=8.0, **kw):
    return dict({"id": "X", "kind": "archive_still", "_dur": dur, "start_s": 0.0, "_item": item}, **kw)


def cam_with(item, size, move, dur=8.0, words=None, variant=None, **kw):
    m = {"move": move, "variant": variant or MV.DEFAULT_VARIANT.get(move), "why": "test", "flips": [],
         "end": MV.END.get((move, variant or MV.DEFAULT_VARIANT.get(move)), "whole")}
    s = shot_of(item, dur, _move=m, **kw)
    return R.still_camera(s, size, W, H, words=words or [], fps=24.0), s


def frames(cam, dur, hz=24.0):
    return [T.at(cam["tour"], k / hz) for k in range(int(dur * hz) + 1)]


def share(size, z):
    fw, fh = T.fill_window(size, A)
    return fw * fh / (size[0] * size[1]) / (z * z)


FIREFIGHTER = {"title": "A firefighter rests on the rubble", "people": [person(0.4, 0.2, 0.15, 0.5)]}
NEUTRAL = {"title": "A man rests on the rubble", "people": [person(0.4, 0.2, 0.15, 0.5)]}


# --------------------------------------------------------------------------
# The face cap (founder ruling 2026-10-18; "public role" only from the item's own text)
# --------------------------------------------------------------------------

def test_a_firefighter_named_in_the_caption_may_go_to_detail():
    persons, info = T.lift_face_caps(FIREFIGHTER, T.person_regions(FIREFIGHTER), BIG, A, 3.0)
    assert info["lifted"] and "firefighter" in info["lifted"]
    assert persons[0]["cap"] > M.CINE["face_zmax"]
    assert share(BIG, persons[0]["cap"]) == pytest.approx(M.CINE["face_detail_share"], rel=1e-6)


def test_the_same_picture_with_a_neutral_caption_keeps_1_3():
    persons, info = T.lift_face_caps(NEUTRAL, T.person_regions(NEUTRAL), BIG, A, 3.0)
    assert persons[0]["cap"] == M.CINE["face_zmax"] and info["lifted"] is None


@pytest.mark.parametrize("item, kw, why", [
    (dict(FIREFIGHTER, people=[person(0.1, 0.2, 0.1, 0.4), person(0.6, 0.2, 0.1, 0.4, name="person-2")]), {},
     "crowd"),
    (dict(FIREFIGHTER, dignity=True), {}, "dignity"),
    (dict(FIREFIGHTER, minor=True), {}, "minor"),
    (dict(FIREFIGHTER, people=[person(0.4, 0.2, 0.15, 0.5, age=12)]), {}, "minor"),
    (FIREFIGHTER, {"no_zoom": True}, "no_zoom"),
    (FIREFIGHTER, {"mode": "strict"}, "strict"),
])
def test_the_cap_stays_1_3_for_crowds_dignity_minors_no_zoom_and_strict(item, kw, why):
    persons, info = T.lift_face_caps(item, T.person_regions(item), BIG, A, 3.0, **kw)
    assert all(q["cap"] == M.CINE["face_zmax"] for q in persons)
    assert why in info["why"]


def test_a_caption_that_binds_one_name_lifts_the_cap():
    item = {"caption": "Rudolph Giuliani at the scene", "caption_names": ["Rudolph Giuliani"],
            "people": [person(0.4, 0.2, 0.15, 0.5, name="Rudolph Giuliani")]}
    _, info = T.lift_face_caps(item, T.person_regions(item), BIG, A, 3.0)
    assert info["lifted"].startswith("bound to")


def test_the_role_word_list_is_versioned_and_read_from_text_only():
    assert T.PUBLIC_ROLE_WORDS_VERSION == 1 and "firefighter" in T.PUBLIC_ROLE_WORDS
    assert T.public_role({"title": "A woman on the stairs"}) is None
    assert T.public_role({"people": "a police officer"}) == "officer" or T.public_role({"people": "a police officer"})


def test_portrait_goes_past_1_3_only_for_the_lifted_face_and_never_past_its_cap():
    cam, _ = cam_with(FIREFIGHTER, BIG, "PORTRAIT", dur=10.0)
    assert cam["tour"]["z_max"] > M.CINE["face_zmax"] + 1e-6
    assert not T.face_cap_check(cam["tour"], cam["cine"]["persons"], 24.0)
    cam2, _ = cam_with(NEUTRAL, BIG, "PORTRAIT", dur=10.0)
    assert cam2["tour"]["z_max"] <= M.CINE["face_zmax"] + 1e-9


# --------------------------------------------------------------------------
# The chooser: the grammar table, then the variety rule (deterministic)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("item, shot, move", [
    ({"whole": True}, {}, "WHOLE"),
    ({"roi": [region("subject", 0.6, 0.3, 0.2, 0.2)]}, {"no_zoom": True}, "PAN"),
    ({"people": [person(0.4, 0.2, 0.15, 0.5)]}, {}, "PORTRAIT"),
    ({"people": [person(0.1, 0.2, 0.1, 0.4), person(0.6, 0.2, 0.1, 0.4, name="b")]}, {}, "SURVEY"),
    ({"class": "document", "roi": [region("page", 0.1, 0.1, 0.8, 0.8, kind="text", must_show=True)]}, {}, "READ"),
    ({"class": "object", "roi": [region("motto", 0.2, 0.6, 0.3, 0.1, kind="text", must_show=True)]}, {},
     "EXPLAIN"),
    ({"class": "place", "roi": [region("subject", 0.6, 0.3, 0.2, 0.2)]}, {}, "EXPLAIN"),
    ({}, {}, "WHOLE"),
])
def test_the_grammar_table(item, shot, move):
    assert MV.base_choice(shot_of(item, **shot), item, BIG)["move"] == move


def _film(n, item=None, chapter="1"):
    item = item or {"class": "place", "roi": [region("subject", 0.6, 0.3, 0.2, 0.2)]}
    return [{"id": f"{chapter}.{k}", "chapter": chapter, "shot": shot_of(item), "item": item, "size": BIG}
            for k in range(n)]


def test_variety_no_three_in_a_row_and_every_chapter_whole_and_detail():
    rows = _film(6) + _film(4, chapter="2")
    ms = MV.choose_film(rows)
    moves = [m["move"] for m in ms]
    dirs = [m["direction"] for m in ms]
    for k in range(len(ms) - 2):
        assert len(set(moves[k:k + 3])) > 1 and len(set(dirs[k:k + 3])) > 1
    for ch in ("1", "2"):
        ends = {m["end"] for r, m in zip(rows, ms) if r["chapter"] == ch}
        assert {"whole", "detail"} <= ends
    assert MV.choose_film(_film(6) + _film(4, chapter="2")) == ms             # same input, same film
    assert any(m.get("variety") for m in ms)                                  # flips are journaled with a reason


def test_crowds_alternate_survey_and_reveal():
    crowd = {"people": [person(0.1, 0.2, 0.1, 0.4), person(0.6, 0.2, 0.1, 0.4, name="b")]}
    ms = MV.choose_film(_film(5, crowd))
    moves = [m["move"] for m in ms]
    assert "REVEAL" in moves and all(len(set(moves[k:k + 3])) > 1 for k in range(3))


def test_an_authored_move_wins_and_a_deliberate_preset_is_left_alone():
    rows = _film(3)
    rows[0]["shot"] = shot_of(rows[0]["item"], move="REVEAL")
    rows[1]["shot"] = shot_of(rows[1]["item"], preset="PUSH")
    rows[2]["shot"] = shot_of(rows[2]["item"], preset="HOLD")
    ms = MV.choose_film(rows)
    assert ms[0]["move"] == "REVEAL" and ms[0]["authored"]
    assert ms[1] is None and ms[2]["move"] in ("EXPLAIN", "REVEAL")


def test_the_move_and_dignity_schema():
    assert T.shot_schema({"move": "SWOOP"})[0] and not T.shot_schema({"move": "reveal"})[0]
    assert T.shot_schema({"move_variant": "sideways"})[0]
    assert T.item_schema({"dignity": False})[0] and not T.item_schema({"dignity": True})[0]
    assert not T.item_schema({"people": [person(0.1, 0.1, 0.1, 0.1, minor=True)]})[1]


# --------------------------------------------------------------------------
# Drawing the moves: real DETAIL, constant scale under no_zoom, every still enters moving
# --------------------------------------------------------------------------

def test_explain_ends_in_a_real_detail_where_the_softness_cap_allows():
    item = {"class": "place", "roi": [region("subject", 0.6, 0.3, 0.1, 0.1)]}
    cam, _ = cam_with(item, BIG, "EXPLAIN", dur=12.0)
    end = cam["tour"]["stops"][-1]
    assert share(BIG, end["z"]) <= M.CINE["detail_share"] + 1e-6
    assert T.upscale(BIG, 1920, 1080, cam["tour"]["z_max"]) <= 3.0 + 1e-6


def test_explain_on_a_small_scan_stops_at_the_softness_cap():
    item = {"class": "place", "roi": [region("subject", 0.6, 0.3, 0.1, 0.1)]}
    cam, _ = cam_with(item, SMALL, "EXPLAIN", dur=12.0)
    assert T.upscale(SMALL, 1920, 1080, cam["tour"]["z_max"]) <= 3.0 + 1e-6


def test_reveal_opens_on_the_detail_and_ends_whole():
    item = {"class": "object", "roi": [region("subject", 0.5, 0.3, 0.3, 0.3, kind="object")]}
    cam, _ = cam_with(item, BIG, "REVEAL", dur=10.0)
    st = cam["tour"]["stops"]
    assert cam["macro"] == "REVEAL" and st[0]["z"] > st[-1]["z"] and st[-1]["z"] <= 1.0 + 1e-6


def test_no_zoom_pans_at_one_scale():
    item = {"roi": [region("subject", 0.8, 0.4, 0.1, 0.1)]}
    cam, _ = cam_with(item, BIG, "PAN", dur=10.0, no_zoom=True)
    zs = [f["z"] for f in frames(cam, 10.0)]
    assert max(zs) - min(zs) <= 1e-9 and cam["macro"] == "PAN"
    fs = frames(cam, 10.0)
    assert max(abs(fs[-1][k] - fs[0][k]) for k in ("x", "y")) > 0.05            # it pans (or tilts)


@pytest.mark.parametrize("move, item", [
    ("EXPLAIN", {"class": "place", "roi": [region("subject", 0.6, 0.3, 0.1, 0.1)]}),
    ("REVEAL", {"class": "place", "roi": [region("subject", 0.6, 0.3, 0.1, 0.1)]}),
    ("PORTRAIT", FIREFIGHTER),
    ("SURVEY", {"people": [person(0.1, 0.2, 0.1, 0.4), person(0.6, 0.2, 0.1, 0.4, name="b")]}),
    ("WHOLE", {}),
])
def test_every_move_enters_moving_and_never_ends_on_a_dead_stop(move, item):
    cam, _ = cam_with(item, BIG, move, dur=10.0)
    tl = cam["tour"]
    assert TL.min_move_after_cut(tl, hz=24.0)["ok"]
    a, b = T.at(tl, 10.0 - 1 / 24), T.at(tl, 10.0)
    assert any(abs(a[k] - b[k]) > 1e-12 for k in ("x", "y", "z"))


# --------------------------------------------------------------------------
# The macros (ticket #10)
# --------------------------------------------------------------------------

def test_read_tilts_a_page_at_reading_pace_when_the_narration_reads_it():
    page = region("page", 0.2, 0.05, 0.6, 0.9, kind="text", lines=6)
    words = [{"w": "reads", "t": 0.5, "e": 0.8, "i": 0, "line": "L", "kind": "testimony"}]
    st, why = T.rich_macro_stops("READ", shot_of({}), {}, [page], [], words, 12.0, BIG, A, 3.0)
    assert why is None and st[0]["y"] < st[-1]["y"]
    assert st[-1]["t"] == pytest.approx(6 * M.BRACKET["read_line_s"])


def test_read_falls_back_without_text_and_portrait_without_a_person():
    assert T.rich_macro_stops("READ", shot_of({}), {}, [], [], [], 12.0, BIG, A, 3.0)[0] is None
    assert T.rich_macro_stops("PORTRAIT", shot_of({}), {}, [], [], [], 12.0, BIG, A, 3.0)[0] is None
    assert T.rich_macro_stops("SURVEY", shot_of({}), {}, [], [], [], 12.0, BIG, A, 3.0)[0] is None


def test_survey_visits_people_in_reading_order_and_reverse_runs_back():
    persons = T.person_regions({"people": [person(0.6, 0.2, 0.1, 0.4, name="b"), person(0.1, 0.2, 0.1, 0.4)]})
    fwd, _ = T.rich_macro_stops("SURVEY", shot_of({}), {}, [], persons, [], 12.0, BIG, A, 3.0)
    rev, _ = T.rich_macro_stops("SURVEY", shot_of({}), {}, [], persons, [], 12.0, BIG, A, 3.0, variant="reverse")
    assert fwd[0]["x"] < fwd[1]["x"] and rev[0]["x"] > rev[1]["x"]
    assert fwd[-1]["z"] == 1.0


# --------------------------------------------------------------------------
# Classic coverage: CUT-IN (hard cuts between framings of one still, inside one shot)
# --------------------------------------------------------------------------

def _words(cue, t):
    return [dict(w, e=w["t"] + 0.4, line="L") for w in T.word_times(f"and then {cue}", t - 0.6, 1.2)]


def test_a_name_spoken_abruptly_cuts_in_on_the_beat():
    # a 16:9 scan: its fill shows the whole picture, so the wide needs no sweep and the beat sets the cut
    item = {"class": "place", "roi": [region("subject", 0.6, 0.3, 0.1, 0.1)]}
    big = (4800, 2700)
    cam, s = cam_with(item, big, "EXPLAIN", dur=10.0, words=_words("tower", 1.8), subject_at="tower")
    tl = cam["tour"]
    assert cam["macro"] == "CUTIN" and len(tl["cuts"]) == 1 and "abruptly" in cam["cut_in"]["reason"]
    tc = tl["cuts"][0]
    onset = next(w["t"] for w in _words("tower", 1.8) if w["w"] == "tower")
    # on the beat, padded onto the frame grid (the cut lands just before a frame)
    assert tc == pytest.approx(max(onset - M.CINE["anchor_lead_s"], T.CUT_FRAMING_MIN_S), abs=0.5 / 24 + 1e-3)
    za, zb = T.at(tl, tc)["z"], T.at(tl, tc + 1 / 24)["z"]
    assert zb / za >= T.CUT_SCALE_MIN - 1e-6                                 # no jump cut
    fs = frames(cam, 10.0)
    assert all(any(abs(a[k] - b[k]) > 1e-12 for k in "xyz") for a, b in zip(fs, fs[1:]))   # every framing drifts
    wins = [(k / 24, T.window(big, A, f["z"], f["x"], f["y"])) for k, f in enumerate(fs)]
    assert T.speed_report(wins, tl["cuts"])["ok"]                            # the cut is no motion
    # on a 4:3 scan the same beat leaves the wide too little time to sweep at the guides: the move stands
    cam, _ = cam_with(item, BIG, "EXPLAIN", dur=10.0, words=_words("tower", 1.8), subject_at="tower")
    assert cam["macro"] != "CUTIN"


def test_a_cut_in_that_would_be_a_jump_cut_keeps_the_move():
    item = {"class": "place", "roi": [region("subject", 0.6, 0.3, 0.1, 0.1)]}
    st, why = T.cut_in_stops(T.resolve_subject(item["roi"]), SMALL, A, 10.0, 1.3, record=False)
    assert st is None and "jump cut" in why


def test_no_zoom_never_cuts_in():
    item = {"roi": [region("subject", 0.6, 0.3, 0.1, 0.1)]}
    cam, _ = cam_with(item, BIG, "CUTIN", dur=10.0, no_zoom=True)
    assert cam["macro"] != "CUTIN"


def test_a_survey_cut_in_has_at_most_three_framings_of_at_least_1_5_s():
    picks = T.survey_picks([], T.person_regions({"people": [person(0.05, 0.2, 0.1, 0.4), person(0.45, 0.2, 0.1, 0.4,
                           name="b"), person(0.85, 0.2, 0.1, 0.4, name="c")]}))
    st, _ = T.survey_cut_stops(picks, BIG, A, 6.0, 3.0)
    starts = [x["t"] for k, x in enumerate(st) if k == 0 or x.get("cut")]   # each framing starts at a cut
    assert len(starts) <= T.CUT_MAX_FRAMINGS and all(b - a >= T.CUT_FRAMING_MIN_S - 1e-3
                                                     for a, b in zip(starts, starts[1:] + [6.0]))
    assert [bool(x.get("cut")) for x in st][:3] == [False, True, True] and not any(x.get("cut") for x in st[3:])
    tl = T.build(st, 6.0, BIG, A, 3.0)
    assert len(tl["cuts"]) == 2


def _framing_windows(tl, size, dur, hz=24.0):
    """The rendered windows of each framing, split where ``at`` changes framing (the internal cuts)."""
    out, edges = [], list(tl["cuts"]) + [math.inf]
    for k in range(int(dur * hz) + 1):
        t = k / hz
        i = next(j for j, e in enumerate(edges) if t <= e)
        while len(out) <= i:
            out.append([])
        f = T.at(tl, t)
        out[i].append(T.window(size, A, f["z"], f["x"], f["y"]))
    return out


def test_a_wide_cut_in_shows_every_located_person_and_the_must_show_text_whole():
    # a 4:3 scan fills 16:9 showing 75% of its height: the WIDE sweeps end to end, arriving a frame before the
    # cut, so a person at the top edge and must_show text at the bottom are each whole on some rendered frame
    top, text = (0.05, 0.0, 0.2, 0.3), (0.6, 0.8, 1.0, 1.0)
    subj = {"src": "subject", "box": (0.4, 0.4, 0.5, 0.5), "kind": "place", "facing": None}
    for order in ("in", "out"):
        st, _ = T.cut_in_stops(subj, BIG, A, 6.0, 3.0, record=False, order=order, hz=24.0)
        tl = T.build(st, 6.0, BIG, A, 3.0)
        fr = _framing_windows(tl, BIG, 6.0)
        wide = fr[0] if order == "in" else fr[-1]
        assert len(fr) == 2 and len(tl["cuts"]) == 1
        assert any(T.covered([w], top, BIG) for w in wide) and any(T.covered([w], text, BIG) for w in wide)
        assert T.covered(wide, (0, 0, 1, 1), BIG)
        fs = [T.at(tl, k / 24) for k in range(6 * 24 + 1)]
        wins = [(k / 24, T.window(BIG, A, f["z"], f["x"], f["y"])) for k, f in enumerate(fs)]
        assert T.speed_report(wins, tl["cuts"])["ok"]                        # the sweep keeps the speed guides
    people = [person(0.05, 0.0, 0.1, 0.3), person(0.45, 0.4, 0.1, 0.3, name="b"), person(0.85, 0.7, 0.1, 0.3, name="c")]
    st, _ = T.survey_cut_stops(T.survey_picks([], T.person_regions({"people": people})), BIG, A, 7.0, 3.0, hz=24.0)
    wide = _framing_windows(T.build(st, 7.0, BIG, A, 3.0), BIG, 7.0)[-1]
    for p in people:
        box = (p["x"], p["y"], p["x"] + p["w"], p["y"] + p["h"])
        assert any(T.covered([w], box, BIG) for w in wide)                   # each person whole on one frame


def test_a_covering_pass_that_replaces_a_cut_in_does_not_claim_it():
    # the engine's covering re-draw (render.engine_cover) is one pass, not hard cuts: the record says so, and why
    item = {"class": "place", "roi": [region("subject", 0.6, 0.3, 0.1, 0.1)]}
    m = {"move": "CUTIN", "variant": None, "why": "test", "flips": [], "end": "detail"}
    s = shot_of(item, 10.0, _move=m)
    cam = R.still_camera(s, BIG, W, H, words=[], fps=24.0, cover="whole")
    assert cam["covering"] and cam["macro"] != "CUTIN" and cam["cut_in"] is None and not cam["tour"]["cuts"]
    assert "covering pass" in cam["move_why"]["reason"]


def test_a_typeset_page_with_no_regions_is_read_whole():
    item = {"class": "document", "title": "observations, 8:51 a.m. (typeset page)"}
    m = MV.base_choice(shot_of(item, kind="drawn"), item, (1600, 2000))
    assert m["move"] == "READ" and m["target"] == MV.PAGE
    s = shot_of(item, 12.0, kind="drawn", _move=dict(m, end="detail"))
    cam = R.still_camera(s, (1600, 2000), W, H, words=[], fps=24.0)
    assert cam["macro"] == "READ" and cam["tour"]["stops"][0]["y"] < cam["tour"]["stops"][-1]["y"]
