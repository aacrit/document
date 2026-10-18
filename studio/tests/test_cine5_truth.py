"""A43 (cinematography ticket #5): truth lints for authored and automatic
framing, live in every preflight. Founder ruling 2 (2026-10-17): subject
finding is automatic and deterministic, a human optional; the lints degrade,
never block on missing human input. Each lint has a failing and a passing
fixture: pure functions on tiny synthetic sizes first, then the plan on the
fixture film (no frame is rendered)."""

import json
import shutil

import pytest

from studio.engine import journal as J
from studio.engine import motion as M
from studio.engine import render as R
from studio.engine import tour as T
from conftest import make_film

W, H = 640, 360
A = W / H
LANDSCAPE43 = (1600, 1200)
FACE = {"name": "face-1", "kind": "face", "x": 0.45, "y": 0.2, "w": 0.1, "h": 0.12, "source": "auto", "confidence": 0.9}
SIGN = {"name": "text-1", "kind": "text", "x": 0.75, "y": 0.75, "w": 0.15, "h": 0.1}


def lints(evs, rule):
    return [e for e in evs if e["kind"] == "lint" and e.get("rule") == rule]


def cam_for(shot, size=LANDSCAPE43, item=None, **kw):
    shot = dict({"id": "X", "kind": "archive_still", "_dur": 8.0, "_item": item or {"people": False}}, **shot)
    return R.still_camera(shot, size, W, H, **kw)


def face_bad(cam):
    return T.face_cap_check(cam["tour"], cam["cine"]["persons"])


# --------------------------------------------------------------------------
# face-cap-live (B): z 1.3 derives from the ledger's face and person boxes
# --------------------------------------------------------------------------

def test_face_cap_fires_on_a_face_roi_without_the_face_flag():
    item = {"people": False, "roi": [FACE]}
    # an authored depth on the face: refused as written (never capped quietly), with no `face` flag on the shot
    cam = cam_for({"camera": [{"t": 0}, {"t": 3, "roi": "face-1", "z": 2.0}]}, item=item)
    assert "face" not in cam and cam["tour"]["stops"][1]["z"] == pytest.approx(2.0)
    bad = face_bad(cam)
    assert bad and bad[0]["people"] == ["face-1"] and bad[0]["z"] > M.CINE["face_zmax"]
    # an x, y, z stop that frames the face is the same push
    cam = cam_for({"camera": [{"t": 0}, {"t": 3, "x": 0.5, "y": 0.26, "z": 1.8}]}, item=item)
    assert face_bad(cam)


def test_face_cap_passes_when_the_engine_places_the_stop_and_creep_never_passes_it():
    item = {"people": False, "roi": [FACE]}
    cam = cam_for({"camera": [{"t": 0}, {"t": 2, "roi": "face-1"}]}, item=item)   # the region alone would go to ~2.6
    st = cam["tour"]["stops"][1]
    assert st["z"] == pytest.approx(M.CINE["face_zmax"]) and st["capped"] == "face" and st["face_cap"]
    assert not face_bad(cam)
    assert cam["tour"]["z_max"] <= M.CINE["face_zmax"] + 1e-9                     # a 6 s hold creeps under the cap
    # a located person in `people` caps the same way
    cam = cam_for({"camera": [{"t": 0}, {"t": 2, "roi": "Ana"}]},
                  item={"people": [{"name": "Ana", "x": 0.1, "y": 0.3, "w": 0.1, "h": 0.3}]})
    assert cam["tour"]["stops"][1]["z"] <= M.CINE["face_zmax"] + 1e-9 and not face_bad(cam)


def test_a_deep_stop_away_from_the_people_is_not_capped():
    item = {"people": False, "roi": [FACE, SIGN]}
    cam = cam_for({"camera": [{"t": 0}, {"t": 3, "roi": "text-1", "z": 2.2}]}, item=item)
    assert cam["tour"]["stops"][1]["z"] == pytest.approx(2.2) and "face_cap" not in cam["tour"]["stops"][1]
    assert not face_bad(cam)


def test_the_dormant_face_flag_is_still_honoured():
    cam = cam_for({"preset": "DETAIL", "face": True, "region": {"x": 0.5, "y": 0.5}}, item={"people": False})
    assert cam["tour"]["z_max"] <= 1.3 + 1e-9


# --------------------------------------------------------------------------
# anchor-identity (B): timing on measured and estimated words, and the binding
# --------------------------------------------------------------------------

LINE = {"id": "N1", "kind": "narration", "start": 10.0, "dur": 4.0,
        "text": "At the school that morning the children read to Booker and the teachers."}
BOOKER = {"name": "Booker", "x": 0.4, "y": 0.2, "w": 0.15, "h": 0.4}
ITEM = {"title": "Booker at the school, test fixture", "people": [BOOKER]}


def estimated():
    return T.shot_words([LINE], 9.0, 17.0)


def measured():
    toks = LINE["text"].split()
    return T.shot_words([dict(LINE, words=[{"w": w, "t": 10.0 + 0.3 * i} for i, w in enumerate(toks)])], 9.0, 17.0)


def ident(path, words, item=ITEM, dur=8.0):
    cam = cam_for({"camera": path, "_dur": dur, "start_s": 9.0}, item=item, words=words)
    assert not cam["problems"], cam["problems"]
    return T.anchor_identity_check(cam["tour"], item, cam["cine"]["regions"], cam["cine"]["persons"])


def test_on_estimated_timings_a_name_needs_a_one_second_lead_and_a_hold_through_it():
    ws = estimated()
    bad = ident([{"t": 0}, {"roi": "Booker", "at": "Booker"}], ws)              # arrives on the name
    assert bad and "estimated" in bad[0]["why"][0] and not bad[0]["measured"]
    assert not ident([{"t": 0}, {"roi": "Booker", "at": "Booker", "lead_s": 1.2}], ws)
    # leaving for another framing before the name has ended is refused
    on = next(w for w in ws if w["n"] == "booker")
    bad = ident([{"t": 0}, {"roi": "Booker", "at": "Booker", "lead_s": 1.2},
                 {"t": on["t"] - 9.0 + 0.05, "x": 0.9, "y": 0.9, "z": 1.0}], ws)
    assert bad and any("hold through" in w for w in bad[0]["why"])
    assert not ident([{"t": 0}, {"roi": "Booker", "at": "Booker", "lead_s": 1.2, "hold": 2.0},
                      {"t": on["e"] - 9.0 + 0.9, "x": 0.9, "y": 0.9, "z": 1.0}], ws)


def test_on_measured_timings_a_name_lands_inside_its_window():
    ws = measured()
    assert all(w["m"] for w in ws)
    assert not ident([{"t": 0}, {"roi": "Booker", "at": "Booker", "lead_s": 0.5}], ws)
    assert not ident([{"t": 0}, {"roi": "Booker", "at": "Booker"}], ws)            # on the onset: inside
    bad = ident([{"t": 0}, {"roi": "Booker", "at": "Booker", "lead_s": 1.0}], ws)   # -1.0 s: too early to read as one
    assert bad and bad[0]["measured"] and "measured" in bad[0]["why"][0]
    # late: a stop that reaches the face after the name has been heard (built directly: `at` never lands late)
    size = LANDSCAPE43
    on = next(w for w in ws if w["n"] == "booker")
    st = dict(T.roi_stop(BOOKER, size, A, 1.3), t=on["t"] - 9.0 + 0.4, roi="Booker", onset=on["t"] - 9.0,
              name_end=on["e"] - 9.0, measured=True, spoken=["Booker"], spoken_line="N1", spoken_i=[on["i"]])
    tl = T.build([{"t": 0.0, "z": 1.0, "x": 0.5, "y": 0.5}, st], 8.0, size, A, 1.3)
    persons = T.person_regions(ITEM)
    bad = T.anchor_identity_check(tl, ITEM, {"Booker": dict(BOOKER, kind="person")}, persons)
    assert bad and "+0.40" in bad[0]["why"][0]


def test_the_binding_rule_refuses_a_name_on_a_face_the_caption_does_not_settle():
    ws = measured()
    path = [{"t": 0}, {"roi": "Booker", "at": "Booker"}]
    assert not ident(path, ws)
    two = dict(ITEM, people=[BOOKER, {"name": "person-2", "x": 0.7, "y": 0.2, "w": 0.1, "h": 0.4}])
    assert any("2 located" in w for w in ident(path, ws, item=two)[0]["why"])
    crowd = dict(ITEM, people=[BOOKER, {"name": "a teacher"}])                    # someone the ledger cannot place
    assert any("1 unlocated" in w for w in ident(path, ws, item=crowd)[0]["why"])
    uncaptioned = dict(ITEM, title="A classroom, test fixture")
    assert any("does not name" in w for w in ident(path, ws, item=uncaptioned)[0]["why"])
    # a face inside the same figure is one person, not two
    nested = dict(ITEM, roi=[{"name": "face-1", "kind": "face", "x": 0.45, "y": 0.22, "w": 0.05, "h": 0.08}])
    assert not ident(path, ws, item=nested)


def test_a_capital_alone_is_never_a_name():
    ws = measured()
    item = {"title": "the children, test fixture", "people": [dict(BOOKER, name="subject")]}
    assert not ident([{"t": 0}, {"roi": "subject", "at": "children"}], ws, item=item)
    persons = T.person_regions(ITEM)
    assert T.names_a_person(["Booker"], ITEM, persons)                         # the person's own recorded name
    for place in (["New", "York"], ["Pentagon"], ["At"]):
        assert not T.names_a_person(place, ITEM, persons)
    sub = {"people": [dict(BOOKER, name="subject")]}
    assert not T.names_a_person(["Booker"], sub, T.person_regions(sub))
    assert T.names_a_person(["Bush"], {"caption_names": ["President Bush"]}, [])


CROWD = [{"name": f"person-{k}", "x": 0.1 + 0.16 * k, "y": 0.4, "w": 0.1, "h": 0.3, "source": "auto",
          "confidence": 0.9} for k in range(5)]
PLACES = {"id": "N2", "kind": "narration", "start": 10.0, "dur": 4.0,
          "text": "They walked north out of New York toward the Pentagon road."}


def test_new_york_and_pentagon_over_a_crowd_bind_no_one():
    ws = T.shot_words([PLACES], 9.0, 17.0)
    item = {"title": "People walking north out of New York", "people": CROWD}
    # a centre in one crowd member's box frames the group; a rulebook name is not a person's name
    assert not ident([{"t": 0}, {"at": "New York", "x": 0.15, "y": 0.5, "z": 1.2}], ws, item=item)
    assert not ident([{"t": 0}, {"at": "Pentagon", "roi": "person-2"}], ws, item=item)
    assert T.stop_person({"x": 0.15, "y": 0.5}, {}, T.person_regions(item)) is None


BUSH = {"id": "N3", "kind": "narration", "start": 10.0, "dur": 4.0,
        "text": "At the barrier that morning the motorcade brought Bush past the school."}


def test_ruling_2_probe_a_machine_subject_named_in_the_caption_binds_with_a_lead():
    # the probe: an auto person region (the rulebook's subject, cue Bush, confidence 0.9), caption
    # "President Bush at the school", camera: tour, estimated timings: it must not be refused
    ws = T.shot_words([BUSH], 9.0, 17.0)
    # A45 (schema owner, 2026-10-17): a machine box binds only when the ledger's own people words name the person;
    # the planner keeps them as _people_words when the rulebook replaces people
    item = {"title": "President Bush at the school", "people": [], "_people_words": "President Bush",
            "roi": [{"name": "subject", "kind": "person", "cue": "Bush", "x": 0.4, "y": 0.2, "w": 0.15, "h": 0.4,
                     "source": "auto", "confidence": 0.9}]}
    unnamed = dict(item, _people_words="a policeman")
    cam = cam_for({"camera": "tour", "_dur": 8.0, "start_s": 9.0}, item=unnamed, words=ws)
    assert cam["cine"]["reframed"]                                 # the words do not name him: degrade, never bind
    cam = cam_for({"camera": "tour", "_dur": 8.0, "start_s": 9.0}, item=item, words=ws)
    st = cam["tour"]["stops"][1]
    assert st["roi"] == "subject" and st["t"] == pytest.approx(st["onset"] - M.CINE["anchor_estimated_lead_s"])
    assert T.leave_time(cam["tour"], 1) >= st["name_end"] - 1e-9 and not cam["cine"]["reframed"]
    assert not T.anchor_identity_check(cam["tour"], item, cam["cine"]["regions"], cam["cine"]["persons"])
    # on measured words it arrives half a second early
    toks = BUSH["text"].split()
    wm = T.shot_words([dict(BUSH, words=[{"w": w, "t": 10.0 + 0.3 * i} for i, w in enumerate(toks)])], 9.0, 17.0)
    st = cam_for({"camera": "tour", "_dur": 8.0, "start_s": 9.0}, item=item, words=wm)["tour"]["stops"][1]
    assert st["t"] == pytest.approx(st["onset"] - M.CINE["anchor_lead_s"])


def test_an_engine_stop_that_may_not_bind_is_reframed_never_refused():
    ws = T.shot_words([BUSH], 9.0, 17.0)
    region = {"name": "person-1", "kind": "person", "cue": "Bush", "x": 0.4, "y": 0.2, "w": 0.15, "h": 0.4,
              "source": "auto", "confidence": 0.9}
    # the schema owner's ruling: a machine box binds only as the rulebook's primary subject
    item = {"title": "The motorcade of President Bush passes a policeman", "caption_names": ["President Bush"],
            "people": [], "roi": [region]}
    assert any("primary subject" in w for w in T.binding_check(item, ["Bush"], region, T.person_regions(item)))
    cam = cam_for({"camera": "tour", "_dur": 8.0, "start_s": 9.0}, item=item, words=ws)
    st = cam["tour"]["stops"][1]
    assert cam["cine"]["reframed"] and st.get("reframed") == "person-1" and "roi" not in st and st["z"] == 1.0
    assert not T.anchor_identity_check(cam["tour"], item, cam["cine"]["regions"], cam["cine"]["persons"])
    # a person writing the same binding is refused
    bad = ident([{"t": 0}, {"roi": "person-1", "at": "Bush", "lead_s": 1.2, "hold": 2.0}], ws, item=item)
    assert bad and bad[0]["authored"]


def test_the_caption_must_name_exactly_one_person():
    ws = T.shot_words([BUSH], 9.0, 17.0)
    one = {"name": "Bush", "x": 0.4, "y": 0.2, "w": 0.15, "h": 0.4}
    item = {"title": "Bush and Card pass a policeman at the barrier", "people": [one]}
    persons = T.person_regions(item)
    assert any("Card" in w for w in T.binding_check(item, ["Bush"], one, persons))
    # the tour resolver degrades; the same binding written by hand is refused
    cam = cam_for({"camera": "tour", "_dur": 8.0, "start_s": 9.0},
                  item=dict(item, people=[], roi=[dict(one, kind="person")]), words=ws)
    assert cam["cine"]["reframed"]
    assert ident([{"t": 0}, {"roi": "Bush", "at": "Bush", "lead_s": 1.2, "hold": 2.0}], ws, item=item)
    # caption_names settles it: exactly one name, the spoken one
    assert not T.binding_check(dict(item, caption_names=["Bush"]), ["Bush"], one, persons)
    assert T.binding_check(dict(item, caption_names=["Bush", "Card"]), ["Bush"], one, persons)
    assert T.binding_check(dict(item, caption_names=["Card"]), ["Bush"], one, persons)
    assert not T.binding_check({"title": "President Bush at the school", "people": [one]}, ["Bush"], one, persons)


def test_face_cap_samples_moves_a_pan_across_a_face_is_capped_or_refused():
    persons = T.person_regions({"roi": [dict(FACE, x=0.45, y=0.45, w=0.1, h=0.1)]})
    a = {"t": 0.0, "z": 2.5, "x": 0.1, "y": 0.5}
    b = {"t": 6.0, "z": 2.5, "x": 0.9, "y": 0.5}
    tl = T.build([a, b], 6.0, LANDSCAPE43, A, 3.0)
    bad = T.face_cap_check(tl, persons)
    assert bad and all(0.0 < v["t"] < 6.0 for v in bad)                       # only the move crosses it
    stops, pulled = T.enforce_face_cap([a, b], persons, 6.0, LANDSCAPE43, A, 3.0)
    assert pulled and not T.face_cap_check(T.build(stops, 6.0, LANDSCAPE43, A, 3.0), persons)
    written = [dict(a, z_authored=True, placed="author"), dict(b, z_authored=True, placed="author")]
    stops, pulled = T.enforce_face_cap(written, persons, 6.0, LANDSCAPE43, A, 3.0)
    assert not pulled and T.face_cap_check(T.build(stops, 6.0, LANDSCAPE43, A, 3.0), persons)
    # a face less than half in frame is not capped (framed_share 0.5, deliberate)
    win = T.window(LANDSCAPE43, A, 2.5, 0.3, 0.5)
    edge_x = (win[2] / LANDSCAPE43[0]) - 0.04                                  # 40% of the 0.1-wide face inside
    edge = {"t": 0.0, "z": 2.5, "x": 0.3, "y": 0.5}
    near = T.person_regions({"roi": [dict(FACE, x=edge_x, y=0.45, w=0.1, h=0.1)]})
    assert not T.face_cap_check(T.build([edge], 1.0, LANDSCAPE43, A, 2.5), near)


def test_the_tour_resolver_leads_a_person_and_holds_through_the_name():
    ws = estimated()
    item = dict(ITEM, roi=[dict(BOOKER, kind="person")], people=[])
    cam = cam_for({"camera": "tour", "_dur": 8.0, "start_s": 9.0}, item=item, words=ws)
    st = cam["tour"]["stops"][1]
    assert st["at"] == "Booker" and st["t"] == pytest.approx(st["onset"] - 1.0)
    assert not T.anchor_identity_check(cam["tour"], item, cam["cine"]["regions"], cam["cine"]["persons"])


def test_digits_alone_are_a_word_index_and_a_phrase_with_digits_is_a_cue():
    line = {"id": "N9", "kind": "narration", "start": 0.0, "dur": 4.0,
            "text": "At five twenty the 7 World Trade Center building fell."}
    ws = T.shot_words([line], 0.0, 5.0)
    cue = T.anchor_span("7 World Trade Center", ws)
    assert [w["w"] for w in cue["words"]] == ["7", "World", "Trade", "Center"] and not cue["measured"]
    idx = T.anchor_span("7", ws)
    assert [w["w"] for w in idx["words"]] == ["Center"]             # word index 7 (from 0), not the spoken "7"
    assert T.anchor_span(7, ws)["t"] == idx["t"]
    assert cue["end"] == pytest.approx(next(w["t"] for w in ws if w["n"] == "building"))


# --------------------------------------------------------------------------
# unconfirmed-roi is gone (ruling 2): source auto|human, confidence, the floor
# --------------------------------------------------------------------------

def test_human_wins_over_auto_and_no_source_is_human():
    item = {"roi": [dict(FACE, name="subject", x=0.1), {"name": "subject", "kind": "face", "x": 0.6, "y": 0.2,
                                                        "w": 0.1, "h": 0.1, "source": "human"}],
            "people": [{"name": "Ana", "x": 0.0, "y": 0.0, "w": 0.1, "h": 0.1}]}
    eff = T.effective_regions(item)
    assert [r["x"] for r in eff["roi"]] == [0.6] and eff["ignored"][0]["why"].startswith("a human")
    assert eff["people"] == item["people"] and eff["unlocated"] == 0             # legacy A41 authoring: human
    assert T.source_of({}) == "human" and T.source_of({"source": "auto"}) == "auto"


def test_an_auto_box_under_the_floor_is_ignored_and_the_still_degrades_toward_the_whole():
    floor = M.CINE["auto_confidence_floor"]
    low = {"name": "person-1", "x": 0.0, "y": 0.0, "w": 0.05, "h": 0.1, "source": "auto", "confidence": floor - 0.01}
    ok = dict(low, confidence=floor)
    eff = T.effective_regions({"people": [low]})
    assert eff["people"] == [] and eff["unlocated"] == 1 and eff["ignored"][0]["confidence"] == floor - 0.01
    pe = T.people_of({"people": [low]})
    assert pe["boxes"] == [] and pe["unlocated"] == 1                            # whole picture needed: degrade
    pe = T.people_of({"people": [ok]})
    assert len(pe["boxes"]) == 1 and pe["unlocated"] == 0
    # an auto box with no confidence is under the floor; a low non-person region is dropped without a person
    eff = T.effective_regions({"roi": [dict(SIGN, source="auto")]})
    assert eff["roi"] == [] and eff["unlocated"] == 0
    eff = T.effective_regions({"roi": [dict(FACE, confidence=0.1)]})
    assert eff["roi"] == [] and eff["unlocated"] == 1
    # an ignored face box neither caps nor binds
    cam = cam_for({"camera": [{"t": 0}, {"t": 3, "x": 0.5, "y": 0.26, "z": 1.8}]},
                  item={"people": False, "roi": [dict(FACE, confidence=0.1)]})
    assert not face_bad(cam) and cam["cine"]["ignored"]


# --------------------------------------------------------------------------
# The schema (cheap): malformed refuses, unknown keys warn
# --------------------------------------------------------------------------

@pytest.mark.parametrize("item,msg", [
    ({"class": "portrait"}, "class is one of"),
    ({"people": [{"x": 0.1, "y": 0.1, "w": 0.2}]}, "x, y, w and h together"),
    ({"people": [{"x": 0.1, "y": 0.1, "w": 0.0, "h": 0.2}]}, "over 0"),
    ({"people": [{"x": 1.2, "y": 0.1, "w": 0.1, "h": 0.2}]}, "0 to 1"),
    ({"people": [{"x": 0.95, "y": 0.1, "w": 0.1, "h": 0.2}]}, "past the picture"),
    ({"people": [{"x": "a", "y": 0.1, "w": 0.1, "h": 0.2}]}, "must be a number"),
    ({"people": [{"x": 0.1, "y": 0.1, "w": 0.1, "h": 0.2, "facing": "up"}]}, "facing is one of"),
    ({"people": [{"x": 0.1, "y": 0.1, "w": 0.1, "h": 0.2, "source": "model"}]}, "source is auto or human"),
    ({"people": [{"x": 0.1, "y": 0.1, "w": 0.1, "h": 0.2, "confidence": 1.5}]}, "confidence is a number"),
    ({"roi": {"subject": {"x": 0.1, "y": 0.1, "w": 0.1, "h": 0.1}}}, "never a keyed object"),
    ({"roi": [{"x": 0.1, "y": 0.1, "w": 0.1, "h": 0.1}]}, "needs a name"),
    ({"roi": [dict(SIGN, kind="sign")]}, "kind is one of"),
    ({"roi": [SIGN, SIGN]}, "two human regions"),
    ({"whole": "yes"}, "whole is true"),
    ({"compose": "thirds"}, "compose is"),
    ({"compose": "centred:"}, "compose is"),
    ({"levels": "floor"}, "levels is"),
    ({"levels": "none"}, "levels_reason"),
])
def test_a_malformed_item_is_named(item, msg):
    bad, _ = T.item_schema(item)
    assert any(msg in b for b in bad), bad


def test_a_well_formed_item_passes_and_unknown_keys_only_warn():
    item = {"class": "person", "compose": "centred:a symmetric doorway", "whole": True, "levels": "none",
            "levels_reason": "the fade is the print", "people": [dict(BOOKER, facing="camera", source="auto",
                                                                      confidence=0.8, model="mp-0.10")],
            "roi": [FACE, dict(SIGN, cue=["the sign", "NONFICTION"], must_show=True), {"name": "old", "person": True,
                                                                                         "x": 0, "y": 0, "w": 1, "h": 1}]}
    assert T.item_schema(item) == ([], [])
    bad, unknown = T.item_schema({"compose": "golden", "roi": [dict(SIGN, colour="red")], "people": "none"})
    assert not bad and unknown == ["roi[0].colour"]


@pytest.mark.parametrize("shot,msg", [
    ({"subject_at": 3.5}, "subject_at is a cue"),
    ({"subject_at": ""}, "subject_at is a cue"),
    ({"subject_at": {"line": "N1"}}, "subject_at.at"),
    ({"match": "next"}, "match is"),
    ({"camera": [{"t": 0, "scale": "close"}]}, "scale is one of"),
    ({"camera": [{"t": 0, "match": "first"}]}, "match is"),
    ({"camera": [{"at": True}]}, "at is a cue"),
])
def test_a_malformed_shot_is_named(shot, msg):
    bad, _ = T.shot_schema(shot)
    assert any(msg in b for b in bad), bad


def test_a_well_formed_shot_passes():
    for shot in ({"subject_at": "7 World Trade Center"}, {"subject_at": {"at": 4, "line": "L2"}}, {"match": "prev"},
                 {"camera": [{"t": 0, "scale": "whole", "match": "prev"}, {"at": "Booker", "lead_s": 1.0, "hold": 2}]}):
        assert T.shot_schema(shot) == ([], []), shot
    assert T.shot_schema({"camera": [{"t": 0, "zoom": 2}]}) == ([], ["camera[0].zoom"])


def test_match_prev_on_the_shot_is_copied_onto_the_first_stop():
    cam = cam_for({"match": "prev", "camera": [{"t": 0}, {"t": 4, "z": 1.2}]})
    assert cam["tour"]["stops"][0]["match"] == "prev" and "match" not in cam["tour"]["stops"][1]


# --------------------------------------------------------------------------
# The plan: the lints run inside build_plan, so every preflight runs them
# --------------------------------------------------------------------------

def _edit(film, fn, name="screenplay.json"):
    data = json.loads((film / name).read_text(encoding="utf-8"))
    fn(data)
    (film / name).write_text(json.dumps(data), encoding="utf-8")


def _shot(play, sid):
    return next(s for p in play["parts"] for s in p["shots"] if s["id"] == sid)


def _line(play, lid):
    return next(x for p in play["parts"] for x in p.get("lines", []) if x["id"] == lid)


def _item(film, aid, fn):
    _edit(film, lambda d: fn(next(i for i in d["items"] if i["id"] == aid)), name="stills-ledger.json")


def _plan(film, name="cine5"):
    j = J.Journal(film=name)
    return R.build_plan(film, W=W, H=H, burn_subtitles=False, journal=j), j


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    return make_film(tmp_path_factory.mktemp("cine5") / "fixture")


@pytest.fixture
def film(base, tmp_path):
    dest = tmp_path / "fixture"
    shutil.copytree(base, dest, ignore=shutil.ignore_patterns("cache", "out"))
    return dest


def test_plan_face_cap_live_refuses_a_push_on_a_face_and_passes_the_capped_stop(film):
    _item(film, "FX-STILL-A", lambda i: i.update(roi=[FACE]))
    _edit(film, lambda p: _shot(p, "S3").update(preset=None, camera=[{"t": 0}, {"t": 1.5, "roi": "face-1", "z": 2.0}]))
    with pytest.raises(R.Refused, match=r"face-cap-live \(S3\)"):
        _plan(film, "cine5-face")
    _edit(film, lambda p: _shot(p, "S3").update(camera=[{"t": 0}, {"t": 1.5, "roi": "face-1"}]))
    plan, j = _plan(film, "cine5-face-ok")
    assert [e["status"] for e in lints(J.read(j.path), "face-cap-live") if e["unit"] == "S3"] == ["pass"]
    assert next(s for s in plan["shots"] if s["id"] == "S3")["_cam"]["tour"]["z_max"] <= 1.3 + 1e-9


def test_plan_anchor_identity_refuses_an_unled_name_and_passes_a_led_one(film):
    # L1 runs 5.0 to 7.0 over S3 (4.5 to 8.5), timed by character share: estimated
    _edit(film, lambda p: _line(p, "L1").update(text="A test tone stands in for Booker."))
    _item(film, "FX-STILL-A", lambda i: i.update(title="Booker, a test fixture",
                                                 people=[{"name": "Booker", "x": 0.4, "y": 0.2, "w": 0.15, "h": 0.4}]))
    _edit(film, lambda p: _shot(p, "S3").update(preset=None, camera=[{"t": 0}, {"roi": "Booker", "at": "Booker"}]))
    with pytest.raises(R.Refused, match=r"anchor-identity \(S3\)"):
        _plan(film, "cine5-ident")
    _edit(film, lambda p: _shot(p, "S3").update(camera=[{"t": 0}, {"roi": "Booker", "at": "Booker", "lead_s": 1.2}]))
    plan, j = _plan(film, "cine5-ident-ok")
    assert [e["status"] for e in lints(J.read(j.path), "anchor-identity") if e["unit"] == "S3"] == ["pass"]
    # the binding: a second located person and the same stop is refused, whatever the timing
    _item(film, "FX-STILL-A", lambda i: i["people"].append({"name": "person-2", "x": 0.7, "y": 0.2, "w": 0.1,
                                                            "h": 0.4, "source": "auto", "confidence": 0.9}))
    with pytest.raises(R.Refused, match=r"anchor-identity \(S3\)"):
        _plan(film, "cine5-bind")


def test_plan_auto_boxes_never_block_and_a_low_one_degrades_to_the_whole(film):
    _item(film, "FX-STILL-A", lambda i: i.update(people=[{"name": "person-1", "x": 0.0, "y": 0.0, "w": 0.04,
                                                          "h": 0.08, "source": "auto", "confidence": 0.2}]))
    _edit(film, lambda p: _shot(p, "S3").update(preset="HOLD"))
    plan, j = _plan(film, "cine5-auto")
    cam = next(s for s in plan["shots"] if s["id"] == "S3")["_cam"]
    assert cam["covering"]                                                     # the whole picture is toured
    evs = J.read(j.path)
    assert [e["status"] for e in lints(evs, "tour-people") if e["unit"] == "S3"] == ["pass"]
    assert any(e["kind"] == "decision" and e.get("unit") == "S3" and "machine box" in e.get("what", "") for e in evs)
    assert not [e for e in evs if e["kind"] == "lint" and e.get("status") == "fail" and e.get("severity") == "block"]


def test_plan_schema_refuses_malformed_and_warns_on_unknown_keys(film):
    _item(film, "FX-STILL-A", lambda i: i.update(roi=[{"name": "subject", "x": 0.9, "y": 0.1, "w": 0.3, "h": 0.1}]))
    with pytest.raises(R.Refused, match=r"cine-schema \(S3\).*past the picture"):
        _plan(film, "cine5-schema")
    _item(film, "FX-STILL-A", lambda i: i.update(roi=[{"name": "subject", "x": 0.5, "y": 0.1, "w": 0.3, "h": 0.1,
                                                       "kindd": "text"}]))
    plan, j = _plan(film, "cine5-schema-keys")
    w = [e for e in lints(J.read(j.path), "cine-schema-keys") if e["unit"] == "S3"]
    assert w and w[0]["severity"] == "warn" and w[0]["evidence"]["unknown"] == ["ledger FX-STILL-A: roi[0].kindd"]


def test_plan_subject_at_is_checked_against_the_narration_as_a_warning(film):
    _edit(film, lambda p: _shot(p, "S3").update(subject_at="narrator"))
    plan, j = _plan(film, "cine5-subject")
    ev = [e for e in lints(J.read(j.path), "cine-subject-at") if e["unit"] == "S3"]
    assert ev[0]["status"] == "pass" and 0.5 < ev[0]["evidence"]["onset_s"] < 4.0
    _edit(film, lambda p: _shot(p, "S3").update(subject_at="Calcutta"))
    plan, j = _plan(film, "cine5-subject-unspoken")                            # a warning: the plan is made
    ev = [e for e in lints(J.read(j.path), "cine-subject-at") if e["unit"] == "S3"]
    assert ev[0]["status"] == "fail" and ev[0]["severity"] == "warn"


def test_plan_ruling_2_probe_a_fully_automatic_tour_is_never_refused(film):
    # the reviewer's probe on the fixture film: an auto person region, cue Bush, conf 0.9, camera "tour", estimated
    _edit(film, lambda p: _line(p, "L1").update(text="A test tone stands in for Bush."))
    region = {"name": "subject", "kind": "person", "cue": "Bush", "x": 0.4, "y": 0.2, "w": 0.15, "h": 0.4,
              "source": "auto", "confidence": 0.9}
    # A45: the ledger's own people words name him (a located person of the same box), so the machine box may bind
    person = {"name": "President Bush", "x": 0.4, "y": 0.2, "w": 0.15, "h": 0.4}
    _item(film, "FX-STILL-A", lambda i: i.update(title="President Bush at the school", roi=[region], people=[person]))
    _edit(film, lambda p: _shot(p, "S3").update(preset=None, camera="tour"))
    plan, j = _plan(film, "cine5-probe")
    evs = J.read(j.path)
    assert [e["status"] for e in lints(evs, "anchor-identity") if e["unit"] == "S3"] == ["pass"]
    cam = next(s for s in plan["shots"] if s["id"] == "S3")["_cam"]
    assert cam["tour"]["stops"][1]["roi"] == "subject" and not cam["cine"]["reframed"]
    # not the primary subject, or a caption naming two people: re-framed and journaled, still never refused
    _item(film, "FX-STILL-A", lambda i: i.update(title="Bush and Card pass a policeman at the barrier",
                                                 roi=[dict(region, name="person-1")]))
    plan, j = _plan(film, "cine5-probe-degrade")
    evs = J.read(j.path)
    assert [e["status"] for e in lints(evs, "anchor-identity") if e["unit"] == "S3"] == ["pass"]
    assert any(e["kind"] == "decision" and e.get("unit") == "S3" and "re-framed" in e.get("what", "") for e in evs)


# --------------------------------------------------------------------------
# An engine path can never fail tour-people (re-review)
# --------------------------------------------------------------------------

PANORAMA = (4500, 1500)
TWO_ENDS = {"id": "N4", "kind": "narration", "start": 10.0, "dur": 6.0,
            "text": "On the left stood Ramos and far across the square waited Diaz for the word."}


def _engine_cam(item, size, words, dur=8.0):
    shot = {"id": "X", "kind": "archive_still", "_dur": dur, "start_s": 9.0, "camera": "tour", "_item": item}
    cam = R.still_camera(shot, size, W, H, words=words)
    return R.engine_cover(shot, cam, size, W, H, words, None), shot


def _never_refused(cam, shot, item, size):
    wins = [w for _, w in R.still_windows(cam, shot, size, W, H)]
    assert T.people_check(wins, T.people_of(item), size)["ok"]
    assert not T.face_cap_check(cam["tour"], cam["cine"]["persons"])
    assert not T.anchor_identity_check(cam["tour"], item, cam["cine"]["regions"], cam["cine"]["persons"])


def test_a_panorama_s_two_ends_are_each_still_visited_after_unbinding():
    ws = T.shot_words([TWO_ENDS], 9.0, 17.0)
    item = {"title": "Two men at the ends of the square", "people": [], "roi": [
        {"name": "subject", "kind": "person", "cue": "Ramos", "x": 0.02, "y": 0.3, "w": 0.04, "h": 0.4,
         "source": "auto", "confidence": 0.9},
        {"name": "person-1", "kind": "person", "cue": "Diaz", "x": 0.93, "y": 0.3, "w": 0.04, "h": 0.4,
         "source": "auto", "confidence": 0.9}]}
    cam, shot = _engine_cam(item, PANORAMA, ws)
    rf = cam["cine"]["reframed"]
    assert {r["person"] for r in rf} == {"subject", "person-1"} and all(r["now"] == "whole" for r in rf)
    st = [s for s in cam["tour"]["stops"] if s.get("reframed")]
    assert all(s["z"] == 1.0 for s in st) and st[0]["x"] < 0.5 < st[1]["x"]          # each end, at the fill
    _never_refused(cam, shot, item, PANORAMA)


def test_a_group_that_fits_one_window_is_framed_together():
    persons = T.person_regions({"people": [{"x": 0.3, "y": 0.3, "w": 0.05, "h": 0.2},
                                           {"x": 0.45, "y": 0.3, "w": 0.05, "h": 0.2}]})
    g, now = T.group_stop(persons, LANDSCAPE43, A)
    assert now == "group" and 1.0 <= g["z"] <= M.CINE["face_zmax"]


@pytest.mark.parametrize("seed", range(40))
def test_property_random_auto_people_with_a_tour_are_never_refused(seed):
    import random
    rng = random.Random(seed)
    size = rng.choice([PANORAMA, LANDSCAPE43, (1200, 1600), (3200, 1000), (1920, 1080)])
    names = ["Ramos", "Diaz", "Ortiz", "Silva", "Mendes"]
    n = rng.randint(1, 5)
    roi = []
    for k in range(n):
        w, h = rng.uniform(0.01, 0.2), rng.uniform(0.02, 0.5)
        roi.append({"name": "subject" if k == 0 else f"person-{k}", "kind": rng.choice(["person", "face"]),
                    "cue": names[k], "x": rng.uniform(0, 1 - w), "y": rng.uniform(0, 1 - h), "w": w, "h": h,
                    "source": "auto", "confidence": rng.uniform(0.3, 1.0)})
    title = rng.choice([f"{names[0]} in the square", f"{names[0]} and {names[1]} in the square", "The square"])
    item = {"title": title, "people": [], "roi": roi}
    if rng.random() < 0.3:
        item["caption_names"] = [names[0]]
    text = "In the square " + " then ".join(rng.sample(names[:n], n)) + " stood waiting for the word."
    line = {"id": "N5", "kind": "narration", "start": 9.0 + rng.uniform(0, 2), "dur": rng.uniform(2, 6), "text": text}
    if rng.random() < 0.5:
        toks = text.split()
        line["words"] = [{"w": t, "t": line["start"] + line["dur"] * i / len(toks)} for i, t in enumerate(toks)]
    ws = T.shot_words([line], 9.0, 17.0)
    cam, shot = _engine_cam(item, size, ws, dur=8.0)
    _never_refused(cam, shot, item, size)


def test_without_caption_names_a_capitalised_caption_cue_is_a_name():
    ws = T.shot_words([BUSH], 9.0, 17.0)
    one = {"name": "person-1", "x": 0.4, "y": 0.2, "w": 0.15, "h": 0.4}
    item = {"title": "Bush and Card pass a policeman at the barrier", "people": [one]}
    assert T.names_a_person(["Bush"], item, T.person_regions(item))
    bad = ident([{"t": 0}, {"roi": "person-1", "at": "Bush", "lead_s": 1.2, "hold": 2.0}], ws, item=item)
    assert bad and bad[0]["authored"] and any("Card" in w for w in bad[0]["why"])
    # crowd safety: a stop placed by x and y inside one of several people binds no one
    crowd = dict(item, people=[one, {"name": "person-2", "x": 0.7, "y": 0.2, "w": 0.1, "h": 0.4}])
    assert not ident([{"t": 0}, {"at": "Bush", "x": 0.47, "y": 0.4, "z": 1.2}], ws, item=crowd)
    assert not T.names_a_person(["barrier"], item, T.person_regions(item))     # lower case in the caption


def test_plan_panorama_tour_is_never_refused(film):
    from PIL import Image
    Image.new("RGB", PANORAMA, (90, 80, 70)).save(film / "stills" / "FX-STILL-A.png")
    _edit(film, lambda p: _line(p, "L1").update(text="Ramos stood left and Diaz right."))
    _item(film, "FX-STILL-A", lambda i: i.update(width=PANORAMA[0], height=PANORAMA[1], title="Two men", roi=[
        {"name": "subject", "kind": "person", "cue": "Ramos", "x": 0.02, "y": 0.3, "w": 0.04, "h": 0.4,
         "source": "auto", "confidence": 0.9},
        {"name": "person-1", "kind": "person", "cue": "Diaz", "x": 0.93, "y": 0.3, "w": 0.04, "h": 0.4,
         "source": "auto", "confidence": 0.9}]))
    _edit(film, lambda p: _shot(p, "S3").update(preset=None, camera="tour"))
    plan, j = _plan(film, "cine5-panorama")
    evs = J.read(j.path)
    for rule in ("tour-people", "anchor-identity", "face-cap-live"):
        assert [e["status"] for e in lints(evs, rule) if e["unit"] == "S3"] == ["pass"], rule
