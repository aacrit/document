"""A45 (cinematography ticket #2a): automatic, deterministic subject finding
(founder ruling 2). The rulebook is pure and tested on synthetic measurements;
the sidecar cache and the planner's overlay on the fixture film; the known hard
detections of Real World (schema file) as synthetic fixtures: a miss must
degrade to a plan that still shows them, never crop them out. The suite is
hermetic: it never runs MediaPipe (CI does not install it); recorded
measurements of five Real World stills drive the rulebook, and the live
determinism proof is the CLI's --check."""

import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from studio.engine import journal as J
from studio.engine import motion as M
from studio.engine import render as R
from studio.engine import rulebook as RB
from studio.engine import tour as T
from studio.engine import vision as V
from conftest import make_film

W, H = 640, 360
MODEL = "mp:test"
LANDSCAPE43 = (1600, 1200)
LANDSCAPE32 = (3000, 2000)


def meas(people=(), faces=(), sal=None, size=LANDSCAPE43):
    return {"size": list(size), "model": MODEL, "people": [dict(p) for p in people], "faces": [dict(f) for f in faces],
            "saliency": sal or {"x": 0.3, "y": 0.3, "w": 0.4, "h": 0.4, "concentration": 0.1}}


def person(x, y, w, h, score=0.9, pose=None):
    return {"x": x, "y": y, "w": w, "h": h, "score": score, "pose": pose}


# --------------------------------------------------------------------------
# caption_names
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text, names", [
    # the ticket's three cases. Chosen: a title stays with the name it precedes, so "President Bush" (the narration's
    # "Bush" or "President Bush" both match it: tour._same_name)
    ("President Bush at the school", ["President Bush"]),
    ("Bush and Card pass a policeman", ["Bush", "Card"]),
    ("New York skyline", []),
    # a one-holder office used with "the" names its holder
    ("The President drafts his statement, Emma E. Booker Elementary School", ["President"]),
    ("The President speaks from the school, the pupils and teachers standing behind him", ["President"]),
    # a route: what follows "<listed place> to" is a place
    ("The President in his office aboard Air Force One, Sarasota to Barksdale", ["President"]),
    # quoted words are text in the picture, not the caption naming anyone
    ("\"Courtesy, Professionalism, Respect\": a police car in the debris", []),
    ("\"All crossings to New York closed\"", []),
    # acronyms and words with digits are not names; place, institution and thing words drop their run
    ("GOES-8, 14:39 UTC: Hurricane Erin and the plume over New York", []),
    ("The remarks, wide, the NONFICTION sign above", []),
    ("The Statue of Liberty and the smoke over Lower Manhattan", []),
    ("Patrol Boat Hocking heads toward Lower Manhattan", []),
    ("Coast Guard crew on the harbour after the collapse", []),
    ("Onlookers in Doric Park, Union City", []),
    ("Smoke from the Pentagon seen from Naval Support Facility Anacostia", []),
    # initials stay with the name
    ("D. A. Henderson, J. D. Millar and colleagues, 1966", ["D. A. Henderson", "J. D. Millar"]),
    ("Dr. Michael Schwartz at the bazaar", ["Dr Michael Schwartz"]),
    # the chosen direction of error: a surname-like place stays a name (one name too many only stops a binding)
    ("A view from the window of Air Force One approaching Andrews", ["Andrews"]),
    ("", []),
    # a run is a place only by its first word (or an institution's last word): surnames that are also place words stay
    # names (reviewer's probes)
    ("Mayor Giuliani with Frank Church at the barrier", ["Mayor Giuliani", "Frank Church"]),
    ("General White briefs Secretary Rumsfeld", ["General White", "Secretary Rumsfeld"]),
    ("Barbara Hall and Rudolph Giuliani", ["Barbara Hall", "Rudolph Giuliani"]),
    ("Edward Park, a rescuer, at Ground Zero", ["Edward Park"]),
    ("Sergeant John West, NYPD", ["Sergeant John West"]),
])
def test_caption_names(text, names):
    assert RB.caption_names(text) == names


@pytest.mark.parametrize("text, names", [
    # a title with the name after it resolves to the titled person
    ("Mayor Giuliani at the command post", ["Mayor Giuliani"]),
    ("Mr. Card and Mrs. Bush", ["Mr Card", "Mrs Bush"]),
    # a bare title or honorific is kept as one name, the title itself: it errs toward a checked binding (A43 binds
    # it to a face only when it is the caption's only name, the ledger counts one person and one is located)
    ("The President in his office", ["President"]),
    ("the Mayor at the scene", ["Mayor"]),
    ("A Senator arrives", ["Senator"]),
    ("Captain on the bridge", ["Captain"]),
    ("The President and Card", ["President", "Card"]),
])
def test_a_bare_title_is_one_name_and_a_titled_name_is_the_person(text, names):
    assert RB.caption_names(text) == names


# --------------------------------------------------------------------------
# The ledger's own people count, and the merge with the detector's boxes
# --------------------------------------------------------------------------

@pytest.mark.parametrize("people, n", [
    ("two distant, unidentifiable living onlookers on a rooftop (about 8 px tall); no figure at any window", 2),
    ("one rescuer by an ambulance, seen from the side, small; no injured, no remains", 1),
    ("a car with a driver, unidentifiable", 1),
    ("crew on deck, tiny", None),
    ("the President, partly in shadow", 1),
    ("the President; about 30 identifiable children (minors) and teachers at a public event", None),
    ("a crowd of living people, small; faces not resolvable at frame scale", None),
    ("two tiny figures on distant rooftops; unidentifiable", 2),
    ("one firefighter from behind; no name legible", 1),
    ("the President and named White House staff (NARA note); officials, not at risk", None),
    ("none visible", 0), ("none resolvable", 0), (False, 0), ([], 0), (None, None), (True, None),
    ([{"name": "Rahima Banu"}], 1),
    ("President Bush", 1), ("Bush and Card", 2),      # words that are only names: one person per name
])
def test_count_people(people, n):
    assert RB.count_people(people) == n


AUTO2 = [{"name": "person-1", "x": 0.1, "y": 0.1, "w": 0.1, "h": 0.3, "source": "auto", "confidence": 0.9},
         {"name": "person-2", "x": 0.5, "y": 0.1, "w": 0.1, "h": 0.3, "source": "auto", "confidence": 0.8}]


def test_merge_people_never_counts_fewer_than_the_ledger_says():
    v, extra, _ = RB.merge_people("four men on a cart", AUTO2)
    assert extra == 2 and [p for p in v if "x" not in p] == [{"name": "unlocated-1"}, {"name": "unlocated-2"}]
    v, extra, _ = RB.merge_people("crew on deck, tiny", AUTO2)          # no exact count: one more keeps the whole
    assert extra == 1 and len(v) == 3
    v, extra, _ = RB.merge_people(None, [])                              # absent: a detector cannot prove it empty
    assert extra == 1 and T.people_of({"people": v})["unlocated"] == 1


def test_merge_people_a_persons_word_wins():
    for nobody in ("none visible", False, []):
        v, extra, why = RB.merge_people(nobody, AUTO2)
        assert v == nobody and extra == 0 and "set aside" in why
    located = [{"name": "Card", "x": 0.2, "y": 0.2, "w": 0.1, "h": 0.3}]
    assert RB.merge_people(located, AUTO2)[0] is located
    named = [{"name": "Rahima Banu"}]                                    # named, not located: kept, stays unlocated
    v, _, _ = RB.merge_people(named, AUTO2)
    assert v[0] == named[0] and T.people_of({"people": v})["unlocated"] == 1


# --------------------------------------------------------------------------
# Facing, class, subject, composition
# --------------------------------------------------------------------------

def pose(nose_x, nose_vis=0.9, l=0.6, r=0.4):
    return {"nose": [nose_x, 0.0, nose_vis], "l_sh": [l, 0.0, 0.9], "r_sh": [r, 0.0, 0.9],
            "l_ear": [0.55, 0, 0.5], "r_ear": [0.45, 0, 0.5]}


def test_facing_from_the_pose():
    assert RB.facing_of(pose(0.5)) == "camera"
    assert RB.facing_of(pose(0.62)) == "right"
    assert RB.facing_of(pose(0.38)) == "left"
    assert RB.facing_of(pose(0.5, nose_vis=0.1)) == "away"
    assert RB.facing_of(None) is None
    assert RB.facing_of(dict(pose(0.5), l_sh=[0.6, 0, 0.2])) is None       # a weak shoulder says nothing


def test_facing_from_a_face_when_the_pose_is_silent():
    face = {"x": 0.4, "y": 0.1, "w": 0.05, "h": 0.05, "score": 0.9,
            "kp": [[0.41, 0.12], [0.43, 0.12], [0.44, 0.13], [0.42, 0.14], [0.40, 0.12], [0.44, 0.12]]}
    out = RB.fields({"people": "one man"}, meas([person(0.35, 0.05, 0.2, 0.6)], [face]), MODEL)["fields"]
    assert out["people"][0]["facing"] == "right"


def test_a_face_outside_any_figure_is_set_aside():
    tower_face = {"x": 0.4, "y": 0.1, "w": 0.2, "h": 0.2, "score": 0.6, "kp": []}
    res = RB.fields({"people": "none visible"}, meas(faces=[tower_face]), MODEL)
    assert "1 outside any figure set aside" in res["why"]["faces"] and "people" not in res["fields"]


def test_class_records_win_then_people_then_place():
    m = meas([person(0.4, 0.2, 0.2, 0.6)])
    assert RB.fields({"title": "A map of the district"}, m, MODEL)["fields"]["class"] == "map"
    assert RB.fields({"title": "GOES-8 satellite image"}, m, MODEL)["fields"]["class"] == "map"
    assert RB.fields({"title": "A man at the door", "people": "a man"}, m, MODEL)["fields"]["class"] == "person"
    assert RB.fields({"title": "The door", "people": "none"}, meas(), MODEL)["fields"]["class"] == "object"
    crowd = [person(0.05 + 0.1 * k, 0.4, 0.06, 0.25) for k in range(6)]
    assert RB.fields({"people": "a crowd"}, meas(crowd), MODEL)["fields"]["class"] == "crowd"
    tiny = [person(0.5, 0.5, 0.02, 0.05)]
    assert RB.fields({"people": "crew on deck"}, meas(tiny), MODEL)["fields"]["class"] == "place"
    # one figure dominating others behind them is a person picture (5.5, the man in the mask)
    lead = [person(0.5, 0.2, 0.34, 0.77)] + [person(0.1 + 0.05 * k, 0.4, 0.02, 0.06) for k in range(4)]
    f = RB.fields({"people": "one identifiable living man, close"}, meas(lead), MODEL)["fields"]
    assert f["class"] == "person" and f["roi"][0]["kind"] == "person" and f["compose"] == "golden"


def test_subject_one_person_group_and_whole():
    f = RB.fields({"people": "the President"}, meas([person(0.42, 0.18, 0.12, 0.37, pose=pose(0.5))]), MODEL)["fields"]
    sub = f["roi"][0]
    assert sub["name"] == "subject" and sub["kind"] == "person" and sub["source"] == "auto"
    assert sub["facing"] == "camera" and sub["confidence"] == 0.9 and "whole" not in f
    two = [person(0.2, 0.2, 0.2, 0.5), person(0.6, 0.2, 0.2, 0.5, 0.8)]
    f = RB.fields({"people": "two men"}, meas(two), MODEL)["fields"]
    assert f["roi"][0]["kind"] == "group" and f["roi"][0]["x"] == 0.2 and f["roi"][0]["w"] == pytest.approx(0.6)
    # nothing over the floor: held whole (a place with spread saliency)
    f = RB.fields({"people": "none visible"}, meas(), MODEL)["fields"]
    assert f["whole"] is True and "roi" not in f and f["class"] == "place" and f["compose"] == "golden"
    # a detection under the floor is not a person the camera may frame
    f = RB.fields({"people": "one man"}, meas([person(0.4, 0.2, 0.2, 0.6, score=0.3)]), MODEL)["fields"]
    assert f["whole"] is True and T.people_of(f)["unlocated"] == 1


def test_a_concentrated_saliency_gives_a_place_subject_and_records_are_centred():
    sal = {"x": 0.1, "y": 0.5, "w": 0.3, "h": 0.2, "concentration": 0.7}
    f = RB.fields({"people": "none"}, meas(sal=sal), MODEL)["fields"]
    assert f["roi"][0]["kind"] == "place" and f["roi"][0]["confidence"] == 0.7
    f = RB.fields({"title": "A page of the newspaper", "people": "none"}, meas(sal=sal), MODEL)["fields"]
    assert f["class"] == "document" and f["compose"] == "centred:document" and f["roi"][0]["kind"] == "text"


def test_no_zoom_means_drift_only():
    m = meas([person(0.45, 0.3, 0.08, 0.25)], size=LANDSCAPE32)
    f = RB.fields({"people": "a man", "no_zoom": True}, m, MODEL)["fields"]
    sub = f["roi"][0]
    assert sub["w"] == pytest.approx(1.0) and sub["h"] == pytest.approx(0.8438, abs=1e-3)   # the z 1 window of 3:2
    st = T.roi_stop(sub, LANDSCAPE32, 16 / 9, 3.0)
    assert st["z"] == pytest.approx(1.0)
    # without no_zoom the same figure is a push
    f = RB.fields({"people": "a man"}, m, MODEL)["fields"]
    assert T.roi_stop(f["roi"][0], LANDSCAPE32, 16 / 9, 3.0)["z"] > 1.5


def test_the_rulebook_is_deterministic_and_writes_no_framing():
    item = {"title": "President Bush at the school", "people": "the President"}
    m = meas([person(0.42, 0.18, 0.12, 0.37, pose=pose(0.6))])
    a, b = RB.fields(item, m, MODEL), RB.fields(json.loads(json.dumps(item)), json.loads(json.dumps(m)), MODEL)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert set(a["fields"]) <= {"class", "people", "roi", "caption_names", "whole", "compose"}
    assert not T.item_schema(RB.overlay(item, a["fields"])[0])[0]          # schema-clean (A43)


def test_nothing_measured_gives_no_fields():
    item = {"title": "Bush at the school", "people": "the President"}
    res = RB.fields(item, None, MODEL)
    assert res["fields"] == {}
    merged, used = RB.overlay(item, res["fields"])
    assert merged == item and used == []


def test_overlay_human_fields_win_and_the_item_is_not_changed():
    item = {"title": "Bush", "people": "the President", "class": "place", "whole": True}
    auto = RB.fields(item, meas([person(0.42, 0.18, 0.12, 0.37)]), MODEL)["fields"]
    before = json.dumps(item, sort_keys=True)
    merged, used = RB.overlay(item, auto)
    assert json.dumps(item, sort_keys=True) == before
    assert merged["class"] == "place" and "roi" not in merged and merged["whole"] is True
    assert "class" not in used and "people" in used
    human_roi = {"name": "subject", "kind": "text", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.1}
    merged, _ = RB.overlay(dict(item, whole=None, roi=[human_roi]), auto)
    assert merged["roi"] == [human_roi]


# --------------------------------------------------------------------------
# Known hard detections (schema file): a miss degrades to a plan that shows them
# --------------------------------------------------------------------------

HARD = {
    # shot: (ledger people words, picture size, no_zoom, what the detector finds (often nothing at 8 px))
    "1.4 rooftop onlookers": ("two distant, unidentifiable living onlookers on a rooftop (about 8 px tall)",
                              (1515, 948), True, []),
    "3.5 rooftop figures": ("two tiny figures on distant rooftops; unidentifiable", (2048, 1536), True, []),
    "2.8 rescuer by the ambulance": ("one rescuer by an ambulance, seen from the side, small", (2000, 1312), True,
                                     [person(0.1, 0.7, 0.01, 0.03, score=0.3)]),
    "3.6 driver": ("a car with a driver, unidentifiable", (1188, 792), True, []),
    "5.9ba crew on the Hocking": ("crew on deck, tiny", (1024, 768), False,
                                  [person(0.7334, 0.4674, 0.0371, 0.1133, 0.79), person(0.6943, 0.4766, 0.0264, 0.1042, 0.65)]),
}


def _plan_still(item, size, preset="HOLD", camera=None, dur=8.0, sal=None, found=()):
    f = RB.fields(item, meas(list(found), sal=sal, size=size), MODEL)["fields"]
    merged, _ = RB.overlay(item, f)
    shot = {"id": "X", "kind": "archive_still", "_dur": dur, "start_s": 0.0, "_item": merged}
    if camera is not None:
        shot["camera"] = camera
    else:
        shot["preset"] = preset
    if item.get("no_zoom"):
        shot["no_zoom"] = True
    cam = R.still_camera(shot, size, W, H, words=[])
    cam = R.engine_cover(shot, cam, size, W, H, [], None)
    wins = [w for _, w in R.still_windows(cam, shot, size, W, H)]
    return merged, cam, wins


@pytest.mark.parametrize("case", sorted(HARD))
@pytest.mark.parametrize("preset", ["HOLD", "PUSH", "DRIFT", "TILT", "tour"])
def test_a_missed_person_is_still_shown(case, preset):
    words, size, no_zoom, found = HARD[case]
    item = {"title": case, "people": words, **({"no_zoom": True} if no_zoom else {})}
    # even when saliency would single out an empty corner, the guard over the whole path shows everyone
    corner = {"x": 0.0, "y": 0.0, "w": 0.2, "h": 0.2, "concentration": 0.9}
    for sal in (None, corner):
        merged, cam, wins = _plan_still(item, size, preset=preset if preset != "tour" else "HOLD",
                                        camera="tour" if preset == "tour" else None, sal=sal, found=found)
        people = T.people_of(merged)
        assert people["unlocated"] >= 1                         # the miss is an unlocated person, never "nobody"
        pc = T.people_check(wins, people, size)
        assert pc["ok"] and pc["whole_shown"], (case, preset, pc)
        assert not T.face_cap_check(cam["tour"], cam["cine"]["persons"])


MOTORCADE = {"title": "The motorcade of the President passes a policeman", "people": "a policeman"}
OFFICE = {"title": "The President in his office aboard Air Force One, Sarasota to Barksdale", "people": "the President"}
ONE = [person(0.42, 0.18, 0.12, 0.37)]


def _merged(item):
    f = RB.fields(item, meas(ONE, size=LANDSCAPE32), MODEL)["fields"]
    merged, _ = RB.overlay(item, f)
    merged["_people_words"] = item["people"]           # as vision.apply keeps them
    return merged


@pytest.mark.parametrize("item, binds", [(OFFICE, True), (MOTORCADE, False)])
def test_an_auto_binding_needs_the_ledger_s_people_words_to_name_them(item, binds):
    # schema owner's ruling (2026-10-17): the caption names one person and one figure is found, but the ledger's own
    # people words ("a policeman") do not name the President, so the machine box never binds him; 4.2's do
    merged = _merged(item)
    assert merged["caption_names"] == ["President"] and len(T.person_regions(merged)) >= 1
    sub = next(r for r in merged["roi"] if r["name"] == "subject")
    why = T.binding_check(merged, ["President"], sub, T.person_regions(merged))
    assert (not why) is binds
    if not binds:
        assert any("people words" in w for w in why)
    # the engine's own tour stop on him at "President": bound on 4.2, re-framed (degraded) on the motorcade
    line = {"id": "N1", "kind": "narration", "start": 0.0, "dur": 6.0, "text": "Aboard was the President with his staff."}
    tour_item = dict(merged, roi=[dict(sub, cue="President")])
    shot = {"id": "X", "kind": "archive_still", "_dur": 8.0, "start_s": 0.0, "camera": "tour", "_item": tour_item}
    cam = R.still_camera(shot, LANDSCAPE32, W, H, words=T.shot_words([line], 0.0, 8.0))
    assert bool(cam["cine"]["reframed"]) is (not binds)
    assert not T.anchor_identity_check(cam["tour"], tour_item, cam["cine"]["regions"], cam["cine"]["persons"])


def test_the_hocking_crew_found_are_each_in_frame():
    words, size, _, found = HARD["5.9ba crew on the Hocking"]
    merged, cam, wins = _plan_still({"title": "Patrol Boat Hocking", "people": words}, size, found=found)
    assert merged["class"] == "place" and merged.get("whole") is True
    assert T.people_check(wins, T.people_of(merged), size)["missed"] == []


# --------------------------------------------------------------------------
# Measurement helpers that need no model
# --------------------------------------------------------------------------

def test_saliency_finds_a_lone_object_and_not_a_flat_picture():
    rng = np.random.default_rng(7)
    a = (rng.random((300, 400)) * 30 + 100).astype(np.uint8)
    noise = V.saliency_box(Image.fromarray(a).convert("RGB"))
    a[200:240, 60:110] = 255
    box = V.saliency_box(Image.fromarray(a).convert("RGB"))
    cx, cy = box["x"] + box["w"] / 2, box["y"] + box["h"] / 2
    assert 0.1 < cx < 0.3 and 0.6 < cy < 0.85 and box["concentration"] > noise["concentration"]
    assert V.saliency_box(Image.fromarray(a).convert("RGB")) == box                      # deterministic
    flat = V.saliency_box(Image.new("RGB", (400, 300), (120, 120, 120)))
    assert flat["concentration"] < M.CINE["auto_confidence_floor"]


def test_nms_keeps_one_box_per_figure_and_is_order_free():
    dets = [(0.9, 100, 100, 50, 150), (0.7, 105, 110, 45, 60), (0.8, 400, 100, 50, 150), (0.6, 102, 98, 52, 148)]
    a, b = V.nms(dets), V.nms(list(reversed(dets)))
    assert a == b and [d["px"][0] for d in a] == [100, 400]


def test_the_sidecar_is_byte_identical_and_written_only_on_change(tmp_path):
    d = {"version": V.SIDECAR_VERSION, "measure": {"b|m": {"z": 1, "a": [1, 2]}}, "items": {"X": {"k": 1}}}
    p = tmp_path / "stills-ledger.vision.json"
    assert V.write_sidecar(p, d) is True
    first = p.read_bytes()
    assert V.write_sidecar(p, json.loads(json.dumps(d))) is False and p.read_bytes() == first
    assert b"\r\n" not in first and V.read_sidecar(p)["measure"] == d["measure"]
    assert V.sidecar_path(tmp_path / "stills-ledger.json") == p


def test_a_missing_model_degrades_never_raises(tmp_path, monkeypatch):
    def missing(*a, **k):
        raise V.MissingModel("not installed here")
    monkeypatch.setattr(V, "CPU", missing)
    m = V.Measurer(True)
    img = tmp_path / "x.png"
    Image.new("RGB", (64, 48)).save(img)
    assert m.get({"measure": {}}, "abc", img) is None and m.why == "not installed here"
    assert V.Measurer(False).get({"measure": {}}, "abc", img) is None


# Recorded MediaPipe measurements of five Real World stills (numbers, no pixels): the suite stays hermetic (CI never
# installs MediaPipe); the live determinism proof is `python -m studio.engine.vision <film> --check`
RECORDED = json.loads((Path(__file__).resolve().parent / "fixture" / "vision-measure.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("shot, cls, located, unlocated, subject, facing", [
    ("4.2", "person", 1, 0, "person", "camera"),        # the President in his office
    ("4.9", "person", 1, 0, "person", "right"),         # he faces right, into the window (WG-3's note)
    ("5.5", "person", 5, 0, "person", "camera"),        # the man in the mask dominates the figures behind him
    ("5.9ba", "place", 2, 1, None, None),               # the Hocking's crew: two found, "crew" gives no count
    ("1.4", "place", 0, 2, None, None),                 # the 8 px rooftop onlookers: missed, kept as two unlocated
])
def test_the_rulebook_on_recorded_real_world_measurements(shot, cls, located, unlocated, subject, facing):
    rec = RECORDED["stills"][shot]
    a = RB.fields(rec["item"], rec["measure"], rec["measure"]["model"])
    b = RB.fields(json.loads(json.dumps(rec["item"])), json.loads(json.dumps(rec["measure"])), rec["measure"]["model"])
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    merged, _ = RB.overlay(rec["item"], a["fields"])
    people = T.people_of(merged)
    assert merged["class"] == cls and T.located_persons(T.person_regions(merged)) == located
    assert people["unlocated"] == unlocated
    sub = next((r for r in merged.get("roi") or [] if r["name"] == "subject"), None)
    assert (sub and sub["kind"]) == subject and (sub or {}).get("facing") == facing
    assert merged.get("whole") is (None if subject else True)


def test_the_recorded_measurements_carry_the_pinned_model_key():
    assert {r["measure"]["model"] for r in RECORDED["stills"].values()} == {V.cpu_model_key()}


# --------------------------------------------------------------------------
# The planner: cached fields applied under the human's, a miss degrades
# --------------------------------------------------------------------------

def _edit(film, fn, name="screenplay.json"):
    data = json.loads((film / name).read_text(encoding="utf-8"))
    fn(data)
    (film / name).write_text(json.dumps(data), encoding="utf-8")


def _item(film, aid, fn):
    _edit(film, lambda d: fn(next(i for i in d["items"] if i["id"] == aid)), name="stills-ledger.json")


def _plan(film):
    j = J.Journal(film="a45")
    return R.build_plan(film, W=W, H=H, burn_subtitles=False, journal=j), j


def _seed(film, aid, m):
    path = film / "stills" / f"{aid}.png"
    sc = V.read_sidecar(V.sidecar_path(film / "stills-ledger.json"))
    sc["measure"][f"{V.sha256_file(path)}|{V.cpu_model_key()}"] = m
    V.write_sidecar(V.sidecar_path(film / "stills-ledger.json"), sc)


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    return make_film(tmp_path_factory.mktemp("a45") / "fixture")


@pytest.fixture
def film(base, tmp_path):
    dest = tmp_path / "fixture"
    shutil.copytree(base, dest, ignore=shutil.ignore_patterns("cache", "out"))
    return dest


def _shot(plan, sid):
    return next(s for s in plan["shots"] if s["id"] == sid)


def test_plan_applies_cached_fields_and_is_identical_twice(film):
    _item(film, "FX-STILL-A", lambda i: i.update(people="one man, close", title="A man at the window"))
    _seed(film, "FX-STILL-A", meas([person(0.42, 0.2, 0.16, 0.6, pose=pose(0.62))], size=(1500, 1050)))
    plan, j = _plan(film)
    s = _shot(plan, "S3")
    it = s["_item"]
    assert it["class"] == "person" and it["roi"][0]["name"] == "subject" and it["roi"][0]["facing"] == "right"
    assert it["_path"] and s["_vision"]["measured"] and s["_vision"]["people_located"] == 1
    ev = [e for e in J.read(j.path) if e["kind"] == "decision" and e["what"].startswith("A45:")]
    assert ev and ev[0]["evidence"]["stills"][0]["id"] == "FX-STILL-A"
    # the face cap derives from the machine's box (A43): no frame of the PUSH frames him past 1.3
    assert not T.face_cap_check(s["_cam"]["tour"], s["_cam"]["cine"]["persons"])
    plan2, _ = _plan(film)
    s2 = _shot(plan2, "S3")
    assert json.dumps(s2["_item"], sort_keys=True, default=str) == json.dumps(it, sort_keys=True, default=str)
    assert s2["_cam"]["tour"]["stops"] == s["_cam"]["tour"]["stops"]
    # the human ledger itself is never rewritten
    led = json.loads((film / "stills-ledger.json").read_text(encoding="utf-8"))
    assert "roi" not in next(i for i in led["items"] if i["id"] == "FX-STILL-A")


def test_plan_a_miss_in_the_cache_degrades_never_infers_and_writes_nothing(film, monkeypatch):
    def never(*a, **k):
        raise AssertionError("a plan must never build the detectors")
    monkeypatch.setattr(V, "CPU", never)
    had_mp = "mediapipe" in sys.modules
    _item(film, "FX-STILL-A", lambda i: i.update(people="two distant onlookers on a rooftop"))
    plan, j = _plan(film)
    s = _shot(plan, "S3")
    assert "roi" not in s["_item"] and s["_item"]["people"] == "two distant onlookers on a rooftop"
    evs = J.read(j.path)
    ev = [e for e in evs if e["kind"] == "decision" and "not measured" in e["what"]]
    assert ev and "FX-STILL-A" in ev[0]["evidence"]["stills"]
    rv = [e for e in evs if e["kind"] == "lint" and e.get("rule") == "vision-cache"]
    assert rv and rv[0]["severity"] == "review" and "--write first" in rv[0]["evidence"]["fix"]
    assert not list(film.glob("*.vision.json*")) and not list(film.glob("**/*.vision.json*"))
    assert had_mp or "mediapipe" not in sys.modules


def test_plan_the_hard_detection_degrades_to_the_whole_in_the_plan(film):
    _item(film, "FX-STILL-A", lambda i: i.update(people="two distant, unidentifiable living onlookers on a rooftop"))
    _seed(film, "FX-STILL-A", meas([], size=(1500, 1050), sal={"x": 0, "y": 0, "w": 0.2, "h": 0.2, "concentration": 0.9}))
    plan, j = _plan(film)
    s = _shot(plan, "S3")
    people = T.people_of(s["_item"])
    assert people["unlocated"] == 2
    wins = [w for _, w in R.still_windows(s["_cam"], s, (1500, 1050), W, H)]
    assert T.people_check(wins, people, (1500, 1050))["whole_shown"]
    assert not [e for e in J.read(j.path) if e["kind"] == "lint" and e.get("status") == "fail" and e.get("severity") == "block"]


def test_an_auto_region_does_not_make_the_default_the_authors_path():
    item = {"people": False, "roi": [{"name": "subject", "kind": "place", "x": 0.0, "y": 0.0, "w": 0.2, "h": 0.2,
                                      "source": "auto", "confidence": 0.9}]}
    shot = {"id": "X", "kind": "archive_still", "_dur": 8.0, "start_s": 0.0, "preset": "PUSH", "_item": item}
    cam = R.engine_cover(shot, R.still_camera(shot, LANDSCAPE43, W, H), LANDSCAPE43, W, H, [], None)
    assert cam["covering"]
    human = dict(item, roi=[dict(item["roi"][0], source="human")])
    shot = dict(shot, _item=human)
    cam = R.engine_cover(shot, R.still_camera(shot, LANDSCAPE43, W, H), LANDSCAPE43, W, H, [], None)
    assert not cam["covering"]


# --------------------------------------------------------------------------
# The VL: place and object regions only, normalized, cold, from the cache (founder ruling (b))
# --------------------------------------------------------------------------

RECORDED_VL = json.loads((Path(__file__).resolve().parent / "fixture" / "vision-vl.json").read_text(encoding="utf-8"))


def test_vl_normalization_snaps_sorts_and_is_canonical():
    raw = json.dumps({"class": "place", "regions": [
        {"label": " Smoke Plume ", "kind": "object", "box": [100, 50, 600, 300]},
        {"label": "city skyline", "kind": "place", "box": [0, 280, 1000, 400]},
        {"label": "a man", "kind": "person", "box": [10, 10, 20, 40]},
        {"label": "bad", "kind": "vehicle", "box": [0, 0, 5, 5]}]})
    n = V.vl_normalize(raw, 1000, 800)
    assert [r["kind"] for r in n["regions"]] == ["object", "person", "place"]        # kind, then y, x, label
    plume = n["regions"][0]
    assert plume == {"kind": "object", "label": "smoke plume", "x": 0.1, "y": 0.06, "w": 0.5, "h": 0.31}
    # half-even on the 0.005 grid: 0.0625 -> 0.06 (12.5 rounds to 12), 0.0675 -> 0.07 (13.5 rounds to 14)
    assert V._snap(0.0625) == 0.06 and V._snap(0.0675) == 0.07
    swapped = json.dumps({"class": "place", "regions": list(reversed(json.loads(raw)["regions"]))})
    assert V.vl_normalize(swapped, 1000, 800) == n
    assert V.vl_normalize("not json", 10, 10)["regions"] == []


def test_vl_regions_never_make_a_person_and_a_cue_beats_the_caption():
    vl = {"class": "place", "regions": [
        {"kind": "group", "label": "people on the tower", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2},
        {"kind": "object", "label": "smoke plume", "x": 0.3, "y": 0.1, "w": 0.3, "h": 0.3},
        {"kind": "place", "label": "south tower", "x": 0.6, "y": 0.2, "w": 0.1, "h": 0.4},
        {"kind": "place", "label": "thin line", "x": 0.0, "y": 0.9, "w": 1.0, "h": 0.0}]}
    item = {"title": "The plume over the tower", "people": "none"}
    sub, why = RB.vl_subject("place", vl, item, ["south tower"])
    assert sub["kind"] == "place" and sub["x"] == 0.6 and "cue" in why
    sub, why = RB.vl_subject("place", vl, item, [])
    assert sub["kind"] == "object" and "plume" in why                     # the caption names the plume
    assert RB.vl_subject("place", vl, {"title": "Sky", "people": "none"}, [])[0] is None
    assert RB.vl_subject("crowd", vl, item, ["south tower"])[0] is None     # people come from MediaPipe alone
    f = RB.fields(item, meas(), MODEL, vl=vl, cues=["south tower"], vl_model="vl:x")["fields"]
    assert f["roi"][0]["model"] == "vl:x" and f["roi"][0]["confidence"] == RB.VL_CONFIDENCE and "whole" not in f
    assert not T.item_schema(RB.overlay(item, f)[0])[0]


@pytest.mark.parametrize("shot, cls, subject", [
    ("3.6", "place", ("object", "smoke plume")),     # the plume over Lower Manhattan (no_zoom: drift only)
    ("5.7", "object", ("object", "damaged car")),    # the police car in the debris
    ("5.9ba", "place", ("object", "boat")),          # the Hocking crossing; its crew still unlocated, so shown whole
    ("1.4", "place", None), ("2.8", "place", None), ("3.7", "map", None),
    ("4.2", "person", ("person", None)),             # people: MediaPipe alone, the VL is not read
])
def test_the_rulebook_on_recorded_vl_answers(shot, cls, subject):
    rec = RECORDED_VL["stills"][shot]
    run = lambda: RB.fields(rec["item"], rec["measure"], rec["measure"]["model"], vl=rec["vl"], cues=rec["cues"],
                            vl_model=rec["vl"]["model"])
    a, b = run(), run()
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    f = a["fields"]
    assert f["class"] == cls
    if subject is None:
        assert f.get("whole") is True and "roi" not in f
    else:
        sub = f["roi"][0]
        assert sub["kind"] == subject[0]
        if subject[1]:
            assert subject[1] in a["why"]["vl"] and sub["model"] == V.vl_model_key()
    if rec["item"].get("no_zoom") and "roi" in f:
        assert T.roi_stop(f["roi"][0], tuple(rec["measure"]["size"]), 16 / 9, 3.0)["z"] == pytest.approx(1.0)


def test_the_recorded_vl_answers_carry_the_pinned_key():
    assert {r["vl"]["model"] for r in RECORDED_VL["stills"].values()} == {V.vl_model_key()}


def test_plan_reads_a_cached_vl_answer_with_the_shot_s_cue_and_never_calls_the_vl(film, monkeypatch):
    def never(*a, **k):
        raise AssertionError("a plan must never call the VL")
    monkeypatch.setattr(V, "VL", never)
    monkeypatch.setattr(V, "CPU", never)
    _item(film, "FX-STILL-A", lambda i: i.update(people="none visible", title="A test picture"))
    _edit(film, lambda p: next(s for q in p["parts"] for s in q["shots"] if s["id"] == "S3").update(subject_at="tower"))
    _seed(film, "FX-STILL-A", meas([], size=(1500, 1050)))
    path = film / "stills" / "FX-STILL-A.png"
    sc = V.read_sidecar(V.sidecar_path(film / "stills-ledger.json"))
    sc["vl"][f"{V.sha256_file(path)}|{V.vl_model_key()}"] = {"class": "place", "model": V.vl_model_key(), "regions": [
        {"kind": "place", "label": "radio tower", "x": 0.6, "y": 0.1, "w": 0.1, "h": 0.5}]}
    V.write_sidecar(V.sidecar_path(film / "stills-ledger.json"), sc)
    plan, j = _plan(film)
    it = _shot(plan, "S3")["_item"]
    assert it["roi"][0]["name"] == "subject" and it["roi"][0]["x"] == 0.6 and it["roi"][0]["model"] == V.vl_model_key()


def test_the_vl_cli_refuses_when_another_job_holds_the_heavy_lock(tmp_path, monkeypatch):
    lock = tmp_path / "HEAVY.lock"
    lock.write_text('{"group": "WG-4", "pid": 1}', encoding="utf-8")
    monkeypatch.setenv("DOCUMENT_HEAVY_LOCK", str(lock))
    with pytest.raises(V.MissingModel):
        with V.HeavyLock("test"):
            pass
    lock.unlink()
    with V.HeavyLock("test"):
        assert json.loads(lock.read_text(encoding="utf-8"))["group"] == "WG-2"
    assert not lock.exists()


def test_two_acquirers_of_the_heavy_lock_in_one_process_the_second_fails(tmp_path, monkeypatch):
    lock = tmp_path / "HEAVY.lock"
    monkeypatch.setenv("DOCUMENT_HEAVY_LOCK", str(lock))
    first = V.HeavyLock("first").__enter__()
    with pytest.raises(V.MissingModel, match="held"):
        V.HeavyLock("second").__enter__()
    assert json.loads(lock.read_text(encoding="utf-8"))["job"] == "first"      # the loser never overwrote it
    first.__exit__(None, None, None)
    assert not lock.exists()
    # another job's lock (another pid) is never removed by our exit
    lock.write_text(json.dumps({"group": "WG-4", "pid": -1}), encoding="utf-8")
    V.HeavyLock("x").__exit__(None, None, None)
    assert lock.exists()
