"""GRAMMAR A52: rulebook 10 (quoted text is must_show; two things named, the
event leads; a monument as vantage) and the subject pass's opening searched
as ``whole_pose`` searches. Hermetic: Real World's own VL answers and human
regions are copied here as data (no film, no picture, no model is read)."""

import json

import pytest

from studio.engine import journal as J
from studio.engine import motion as M
from studio.engine import render as R
from studio.engine import rulebook as RB
from studio.engine import tour as T

W, H = 1920, 1080
A = 16 / 9
FPS = 30000 / 1001
VLM = "vl:test"
NOBODY = {"people": [], "faces": [], "saliency": {"x": 0.3, "y": 0.3, "w": 0.4, "h": 0.4, "concentration": 0.1}}


def _meas(size):
    return dict(NOBODY, size=list(size))


# --------------------------------------------------------------------------
# Real World 5.7 (S11-LOC-0129): the cached VL answer, and WG-3's human region as the ground truth
# --------------------------------------------------------------------------

LOC_0129 = {"id": "S11-LOC-0129", "title": "\"Courtesy, Professionalism, Respect\": a police car in the debris",
            "seen": "A crushed, dust-covered NYPD car, its motto lettered on the door; rubble, a burned-out car and "
                    "the smoke beyond.",
            "people": "none visible inside or near the car (checked at master scan)", "no_zoom": False}
LOC_0129_VL = {"regions": [
    {"h": 0.53, "kind": "object", "label": "building", "w": 0.65, "x": 0.335, "y": 0.0},
    {"h": 0.415, "kind": "object", "label": "smoke", "w": 0.625, "x": 0.02, "y": 0.025},
    {"h": 0.78, "kind": "object", "label": "van", "w": 0.645, "x": 0.345, "y": 0.205},
    {"h": 0.455, "kind": "object", "label": "debris", "w": 0.535, "x": 0.015, "y": 0.53},
    {"h": 0.125, "kind": "object", "label": "smashed car", "w": 0.15, "x": 0.095, "y": 0.63},
    {"h": 0.04, "kind": "text", "label": "text", "w": 0.18, "x": 0.215, "y": 0.485},
    {"h": 0.255, "kind": "text", "label": "text", "w": 0.275, "x": 0.705, "y": 0.73}]}
LETTERING = {"name": "lettering", "kind": "text", "x": 0.655, "y": 0.735, "w": 0.32, "h": 0.235, "source": "human",
             "must_show": True}

# Real World 5.9 (S11-NPS-LIBERTY)
LIBERTY = {"id": "S11-NPS-LIBERTY", "title": "The Statue of Liberty and the smoke over Lower Manhattan",
           "seen": "The statue on its pedestal at left; a grey-brown smoke cloud over Lower Manhattan across the "
                   "harbour; no towers.", "people": "none", "no_zoom": False}
LIBERTY_VL = {"regions": [
    {"h": 0.51, "kind": "object", "label": "statue of liberty", "w": 0.12, "x": 0.06, "y": 0.03},
    {"h": 0.79, "kind": "object", "label": "smoke", "w": 0.78, "x": 0.22, "y": 0.07},
    {"h": 0.29, "kind": "object", "label": "base of statue", "w": 0.195, "x": 0.025, "y": 0.535},
    {"h": 0.25, "kind": "object", "label": "buildings", "w": 0.625, "x": 0.36, "y": 0.74},
    {"h": 0.18, "kind": "object", "label": "fortress wall", "w": 0.6, "x": 0.0, "y": 0.82},
    {"h": 0.83, "kind": "place", "label": "clear sky", "w": 1.0, "x": 0.0, "y": 0.0}]}
LIBERTY_HUMAN = {"name": "subject", "kind": "place", "x": 0.28, "y": 0.48, "w": 0.46, "h": 0.42, "source": "human"}


def _fields(item, vl, size=(3000, 2033), cues=()):
    return RB.fields(json.loads(json.dumps(item)), _meas(size), "mp:test", vl=vl, cues=cues, vl_model=VLM)


def test_rulebook_version_is_10():
    assert RB.RULEBOOK_VERSION == "10"


def test_quoted_reads_double_curly_and_single_quotes_but_never_an_apostrophe():
    assert RB.quoted({"title": "\"All crossings to New York closed\""}) == ["All crossings to New York closed"]
    assert RB.quoted({"caption": "the sign “Ground Zero”, and 'Never Forget' below"}) == ["Ground Zero",
                                                                                        "Never Forget"]
    assert RB.quoted({"title": "The President's car, the driver's door"}) == []
    assert RB.quoted({"why": ["it reads \"EXIT\"", "it reads \"EXIT\""]}) == ["EXIT"]


def test_5_7_the_quoted_motto_is_must_show_and_covers_the_human_lettering():
    # WG-3's human region is removed in memory: the rule alone must find it
    res = _fields(LOC_0129, LOC_0129_VL)
    texts = [r for r in res["fields"]["roi"] if r["name"] != "subject"]
    assert len(texts) == 1
    t = texts[0]
    assert t["name"] == "text-1" and t["kind"] == "text" and t["must_show"] is True and t["source"] == "auto"
    assert t["model"] == VLM
    # the VL's two text regions are both labelled "text": the one on the police car (the VL's "van") is the motto
    assert "the one text region on the 'van' the item's words name" in res["why"]["quoted"]
    # the human box lies wholly inside the rule's region; IoU 0.669 (the VL's own box, unpadded: 0.775)
    assert RB._inside(LETTERING, t) == pytest.approx(1.0)
    assert RB.iou(LETTERING, t) == pytest.approx(0.669, abs=0.002)
    assert RB.iou(LETTERING, LOC_0129_VL["regions"][6]) == pytest.approx(0.775, abs=0.002)
    # the subject is still the car, never the lettering alone
    sub = next(r for r in res["fields"]["roi"] if r["name"] == "subject")
    assert (sub["x"], sub["y"], sub["w"], sub["h"]) == (0.345, 0.205, 0.645, 0.78)


def test_5_7_with_the_human_region_kept_the_rule_adds_no_second_must_show():
    res = _fields(LOC_0129, LOC_0129_VL)
    item = dict(LOC_0129, roi=[dict(LETTERING)])
    merged, used = RB.overlay(item, res["fields"])
    assert [r["name"] for r in merged["roi"]] == ["lettering"] and "roi" not in used
    # a human region elsewhere leaves the rule's must_show in place
    other = dict(LOC_0129, roi=[{"name": "wheel", "kind": "object", "x": 0.1, "y": 0.1, "w": 0.1, "h": 0.1,
                                 "source": "human"}])
    merged2, _ = RB.overlay(other, res["fields"])
    assert [r["name"] for r in merged2["roi"]] == ["wheel", "text-1"]
    assert [r["name"] for r in T.must_show_regions(merged2)] == ["text-1"]


def test_a_label_that_holds_the_quote_wins_over_a_generic_one():
    vl = {"regions": [{"kind": "text", "label": "text", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.05},
                      {"kind": "text", "label": "courtesy professionalism", "x": 0.6, "y": 0.7, "w": 0.3,
                       "h": 0.1}]}
    regs, why = RB.quoted_must_show(vl, LOC_0129)
    assert len(regs) == 1 and regs[0]["label"] == "courtesy professionalism" and "67%" in why
    # under the share: one word of three is no match, and two generic regions with none on a named thing tie
    vl2 = {"regions": [{"kind": "text", "label": "respect", "x": 0.6, "y": 0.7, "w": 0.3, "h": 0.1},
                       {"kind": "text", "label": "sign", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.05},
                       {"kind": "text", "label": "lettering", "x": 0.4, "y": 0.1, "w": 0.2, "h": 0.05}]}
    regs2, why2 = RB.quoted_must_show(vl2, LOC_0129)
    assert regs2 == [] and "no text region holds it" in why2


def test_the_one_generic_text_region_holds_the_quote():
    vl = {"regions": [{"kind": "text", "label": "sign", "x": 0.4, "y": 0.4, "w": 0.2, "h": 0.1},
                      {"kind": "object", "label": "bridge", "x": 0.0, "y": 0.5, "w": 1.0, "h": 0.3}]}
    regs, why = RB.quoted_must_show(vl, {"title": "A sign reading \"All crossings to New York closed\""})
    assert len(regs) == 1 and "the one text region" in why
    r = regs[0]                                       # padded by a fifth of its size each side
    assert (r["x"], r["y"], r["w"], r["h"]) == (0.36, 0.38, 0.28, 0.14)


def test_nothing_quoted_or_no_vl_adds_nothing():
    res = _fields(dict(LOC_0129, title="A police car in the debris"), LOC_0129_VL)
    assert [r["name"] for r in res["fields"]["roi"]] == ["subject"] and "quoted" not in res["why"]
    res2 = RB.fields(dict(LOC_0129), _meas((3000, 2033)), "mp:test")
    assert all(r["name"] == "subject" for r in res2["fields"].get("roi") or [])


def test_a_quote_on_a_whole_still_is_must_show_beside_whole():
    vl = {"regions": [{"kind": "text", "label": "sign", "x": 0.4, "y": 0.4, "w": 0.2, "h": 0.1}]}
    item = {"title": "\"Closed\"", "seen": "A shop door, a hand-painted sign reading Closed in the window.", "people": "none"}
    res = _fields(item, vl)
    f = res["fields"]
    assert f["whole"] is True and [r["name"] for r in f["roi"]] == ["text-1"]
    merged, used = RB.overlay(item, f)
    assert merged["whole"] is True and "roi" in used and "whole" in used


# Review, 2026-10-18: quoted speech is never lettering in the picture (A0)
SIGN = {"regions": [{"kind": "text", "label": "sign", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.05}]}


@pytest.mark.parametrize("title", [
    'The President said "We will find those who did this" at the site',
    'A firefighter shouts "get back" near the barrier',
    "The Mayor's words, 'New York is open for business', on the steps",
])
def test_quoted_speech_never_makes_a_sign_must_show(title):
    regs, why = RB.quoted_must_show(SIGN, {"title": title})
    assert regs == [] and "quoted speech" in why
    f = _fields({"title": title, "people": "none"}, SIGN)["fields"]
    assert not [r for r in f.get("roi") or [] if r.get("must_show")]
    assert RB.quote_marks({"title": title})[0][1] == "speech"


def test_quoted_speech_still_binds_a_label_that_holds_its_words():
    vl = {"regions": [{"kind": "text", "label": "we will find those who did", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.05}]}
    regs, _ = RB.quoted_must_show(vl, {"title": 'The President said "We will find those who did this"'})
    assert len(regs) == 1


@pytest.mark.parametrize("item, mark", [
    ({"title": 'A banner "We Will Never Forget" over the street'}, "lettering"),
    ({"title": 'A storefront, the words "God Bless America"'}, "lettering"),
    ({"title": '"Ground Zero" on the barrier'}, "lettering"),
    ({"title": '"Ground Zero", the barrier'}, "unmarked"),
])
def test_quote_marks_read_lettering_beside_the_quote(item, mark):
    assert RB.quote_marks(item)[0][1] == mark
    regs, _ = RB.quoted_must_show(SIGN, item)
    assert bool(regs) == (mark == "lettering")


def test_seen_naming_lettering_allows_only_the_region_on_a_named_thing():
    item = {"title": '"Ground Zero", the barrier'}
    assert RB.quoted_must_show(SIGN, item)[0] == []
    # seen names lettering somewhere: the lone generic region is not enough, it must lie on a thing named
    seen = dict(item, seen="A barrier with a painted sign.")
    assert RB.quote_visible(seen, "Ground Zero", "unmarked") == "bearer"
    assert RB.quoted_must_show(SIGN, seen)[0] == []
    on = {"regions": SIGN["regions"] + [{"kind": "object", "label": "barrier", "x": 0.05, "y": 0.05, "w": 0.4,
                                          "h": 0.2}]}
    assert len(RB.quoted_must_show(on, seen)[0]) == 1
    # seen that holds the quote's own words: the lone generic region binds
    words = dict(item, seen="A barrier, Ground Zero painted across it.")
    assert RB.quote_visible(words, "Ground Zero", "unmarked") == "all"
    assert len(RB.quoted_must_show(SIGN, words)[0]) == 1
    # 5.7: the bearer route (the motto on the car the title names)
    assert RB.quote_marks(LOC_0129)[0][1] == "unmarked"
    assert RB.quote_visible(LOC_0129, RB.quoted(LOC_0129)[0], "unmarked") == "bearer"


@pytest.mark.parametrize("title, seen", [
    ('Rescuers named it "the pile"', "graffiti lettered on a wall"),
    ('They knew it as "Ground Zero" by nightfall', "a street sign at right"),
])
def test_a_naming_quote_never_binds_a_sign(title, seen):
    item = {"title": title, "seen": seen, "people": "none"}
    assert RB.quote_marks(item)[0][1] == "speech"
    assert RB.quoted_must_show(SIGN, item)[0] == []
    f = _fields(item, SIGN)["fields"]
    assert not [r for r in f.get("roi") or [] if r.get("must_show")]


def test_a_seen_only_quote_with_no_naming_verb_takes_no_lone_region():
    for title, seen in (('"the pile", the site', "graffiti lettered on a wall"),
                        ('"Ground Zero" by nightfall', "a street sign at right")):
        assert RB.quoted_must_show(SIGN, {"title": title, "seen": seen})[0] == []


def test_a_marker_in_the_clause_before_a_colon_is_lettering():
    item = {"title": 'The headline the next day: "We Will Rebuild"'}
    assert RB.quote_marks(item)[0][1] == "lettering"
    assert len(RB.quoted_must_show(SIGN, item)[0]) == 1
    assert RB.quote_marks({"title": 'The day after, he said: "We Will Rebuild"'})[0][1] == "speech"


def test_a_crowd_is_never_an_event_people_stay_mediapipe_s():
    assert "crowd" not in RB.EVENT_WORDS
    assert RB.event_clause({"title": "The station and the crowd outside"}) == set()


# --------------------------------------------------------------------------
# Two things named: the event leads (Real World 5.9)
# --------------------------------------------------------------------------

def test_5_9_two_things_named_the_smoke_not_the_statue():
    # WG-3's human subject removed in memory: rulebook 9 took the statue (the first named); 10 takes the smoke
    res = _fields(LIBERTY, LIBERTY_VL, size=(1540, 1260))
    sub = next(r for r in res["fields"]["roi"] if r["name"] == "subject")
    assert (sub["x"], sub["y"], sub["w"], sub["h"]) == (0.22, 0.07, 0.78, 0.79)
    assert "smoke" in res["why"]["subject"] and "the event" in res["why"]["subject"]
    # the human's subject (the plume over the skyline) lies 90% inside it; IoU 0.275
    assert RB._inside(LIBERTY_HUMAN, sub) == pytest.approx(0.905, abs=0.002)
    assert RB.iou(LIBERTY_HUMAN, sub) == pytest.approx(0.275, abs=0.002)


def test_event_clause_forms():
    assert RB.event_clause({"title": "The Statue of Liberty and the smoke over Lower Manhattan"}) == {"plume"}
    assert RB.event_clause({"title": "The skyline with the smoke, from uptown"}) == {"plume"}
    assert RB.event_clause({"caption": "The bridge with fire behind"}) == {"fire"}
    assert RB.event_clause({"title": "The President and the staff watch"}) == set()
    assert RB.event_clause({"title": "Both towers burning, from a Brooklyn rooftop"}) == set()


def test_an_event_clause_with_no_event_region_holds_the_picture_whole():
    # the first-named thing is never taken in the event's place (Real World 3.7, the GOES-8 frame, shape)
    vl = {"regions": [{"kind": "object", "label": "hurricane erin", "x": 0.34, "y": 0.0, "w": 0.66, "h": 0.9}]}
    sub, why = RB.vl_subject("place", vl, {"title": "Hurricane Erin and the plume over New York"}, ())
    assert sub is None and "the event: plume" in why
    # a cue still names the subject first
    sub2, _ = RB.vl_subject("place", vl, {"title": "Hurricane Erin and the plume over New York"}, ("Erin",))
    assert sub2 is not None and sub2["label"] == "hurricane erin"


# --------------------------------------------------------------------------
# A monument as vantage
# --------------------------------------------------------------------------

def test_a_monument_the_photographer_stood_at_is_never_the_subject():
    vl = {"regions": [{"kind": "object", "label": "statue of liberty", "x": 0.0, "y": 0.1, "w": 0.15, "h": 0.6},
                      {"kind": "place", "label": "lower manhattan skyline", "x": 0.3, "y": 0.4, "w": 0.6, "h": 0.3}]}
    for title in ("Lower Manhattan from the Statue of Liberty", "Lower Manhattan, seen from the Statue of Liberty",
                  "The harbour beside the statue", "Liberty Island at the foot of the statue, Lower Manhattan"):
        sub, why = RB.vl_subject("place", vl, {"title": title}, ())
        assert sub is None or sub["label"] != "statue of liberty", title
        assert "the vantage set aside: statue of liberty" in why, title
    sub, _ = RB.vl_subject("place", vl, {"title": "Lower Manhattan from the Statue of Liberty"}, ())
    assert sub["label"] == "lower manhattan skyline"
    # a place that is no monument is never a vantage: the smoke from the Pentagon is about the Pentagon
    assert RB.vantage_words({"title": "Smoke from the Pentagon seen from Naval Support Facility Anacostia"}) == set()
    assert RB.vantage_words({"title": "The Statue of Liberty and the smoke over Lower Manhattan"}) == set()


def test_a_vantage_monument_can_still_be_must_show_when_quoted():
    item = {"title": "The harbour from the Statue of Liberty, its tablet reading \"July IV MDCCLXXVI\"",
            "people": "none"}
    vl = {"regions": [{"kind": "object", "label": "statue of liberty", "x": 0.0, "y": 0.1, "w": 0.15, "h": 0.6},
                      {"kind": "text", "label": "inscription", "x": 0.05, "y": 0.3, "w": 0.05, "h": 0.05},
                      {"kind": "place", "label": "harbour", "x": 0.3, "y": 0.5, "w": 0.6, "h": 0.3}]}
    f = _fields(item, vl, size=(2000, 1500))["fields"]
    sub = next(r for r in f["roi"] if r["name"] == "subject")
    assert (sub["x"], sub["w"]) == (0.3, 0.6)                    # the harbour, never the statue
    assert [r["name"] for r in f["roi"] if r.get("must_show")] == ["text-1"]


# --------------------------------------------------------------------------
# The opening searched as whole_pose searches (A51 review; synthetic, as WG-3 dropped 5.9's must_show)
# --------------------------------------------------------------------------

SIZE = (1540, 1260)
MUST = {"name": "subject", "kind": "place", "x": 0.42, "y": 0.50, "w": 0.53, "h": 0.47, "source": "human",
        "must_show": True}


def _item():
    return {"id": "X", "people": "none", "compose": "golden", "class": "place", "roi": [dict(MUST)]}


def _avoid(item, zones):
    boxes = [M.ZONES[z] for z in zones]
    return [(T.roi_box(r), zb) for r in T.must_show_regions(item) for zb in boxes] + T.face_avoid(item, boxes)


def test_the_opening_is_steered_down_the_travel_under_a_subtitle_already_up():
    item = _item()
    av = _avoid(item, ("SUB",))
    roi, persons = T.effective_regions(item)["roi"], T.person_regions(item)
    shot = {"id": "X", "kind": "archive_still"}
    st, info = T.subject_plan(shot, item, roi, persons, [], SIZE, A, 6.0, 0.0, 3.0, need_whole=False, avoid=av)
    plain, _ = T.subject_stops(SIZE, A, 6.0, dict(st[-1]), arrive=info["timing"]["arrive_s"], settle_s=1.0,
                               breath=True)
    w_plain = T.window(SIZE, A, plain[0]["z"], plain[0]["x"], plain[0]["y"])
    w_new = T.window(SIZE, A, st[0]["z"], st[0]["x"], st[0]["y"])
    before, after = T.avoid_overlap(SIZE, w_plain, av), T.avoid_overlap(SIZE, w_new, av)
    assert before == pytest.approx(0.391, abs=0.005)            # the far (top) end: 39% under the subtitle
    assert after == pytest.approx(0.156, abs=0.005)             # the lower whole: about 16%
    assert st[0]["z"] == 1.0 and st[0]["y"] > plain[0]["y"]
    assert info["timing"]["open_steered"]["overlap_to"] == pytest.approx(after, abs=1e-3)
    # the whole shot is no worse than its first frame, and the subject's stop is unchanged
    worst = max(T.avoid_overlap(SIZE, w, av) for w in T.windows_of(T.build(st, 6.0, SIZE, A, 3.0), 24.0))
    assert worst <= after + 1e-3
    assert (st[-1]["x"], st[-1]["y"], st[-1]["z"]) == (plain[-1]["x"], plain[-1]["y"], plain[-1]["z"])


def test_an_opening_already_clear_is_never_moved():
    item = _item()
    av = _avoid(item, ("LT",))
    roi, persons = T.effective_regions(item)["roi"], T.person_regions(item)
    st, info = T.subject_plan({"id": "X"}, item, roi, persons, [], SIZE, A, 6.0, 0.0, 3.0, need_whole=False)
    # no avoid: today's far-end opening, no steer
    assert "open_steered" not in info["timing"] and st[0]["y"] < 0.4
    # a zone the far end does not touch: the end is clear and stays
    far = {"z": 1.0, "x": 0.5, "y": st[0]["y"]}
    q = T.travel_search(SIZE, A, 0.0, [((0.0, 0.0, 0.1, 0.05), M.ZONES["SUB"])], span=(0.0, 1.0))
    assert q["avoid_clear"] is True and abs(q["y"] - far["y"]) < 1e-9
    assert av                                            # (LT is a real avoid list for the 5.9 shape)


def test_whole_pose_keeps_its_search_through_the_shared_helper():
    av = [((0.3, 0.2, 0.7, 0.4), M.ZONES["SUB"])]
    p = T.whole_pose((1000, 1400), A, False, avoid=av)
    q = T.travel_search((1000, 1400), A, M.CINE["whole_weight"], av)
    assert p == q


# --------------------------------------------------------------------------
# One report for a subject that is also must_show
# --------------------------------------------------------------------------

def test_a_must_show_subject_under_text_is_reported_once(tmp_path):
    jr = J.Journal(film="a52", kind="test", out_dir=tmp_path, directory=tmp_path, timings=tmp_path / "t.jsonl")
    item = _item()
    s = {"id": "X", "kind": "archive_still", "_dur": 6.0, "start_s": 0.0, "_item": item, "preset": "HOLD"}
    av = _avoid(item, ("SUB",))
    spans = [{"zone": "SUB", "id": "SUB-1", "box": M.ZONES["SUB"], "t0": 0.0, "t1": 6.0}]
    cam = R.still_camera(s, SIZE, W, H, words=[], fps=FPS, avoid=av)
    R.a49_tour_lints(lambda *a, **k: None, jr, s, cam, SIZE, FPS, None, spans, T.must_show_regions(item))
    ev = [json.loads(x) for x in jr.path.read_text(encoding="utf-8").splitlines()] if jr.path.exists() else []
    sut = [e for e in ev if e["kind"] == "lint" and e["rule"] == "subject-under-text"]
    assert len(sut) == 1 and sut[0]["evidence"]["must_show"] == "subject"
