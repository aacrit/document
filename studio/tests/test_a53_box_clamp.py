"""GRAMMAR A53: every box the rulebook emits (a located person, its face, and
each ``roi`` entry) is clamped to the picture [0, 1] before it ever reaches a
sidecar or the cine-schema check in studio/engine/tour.py. A measurer, or a
union of its boxes, can land a box a hair past the edge; the fix is a
deterministic clamp, never a hand-drawn correction (founder ruling 2).

Not a Free Agent (partition-of-india) hit this at shot 1.8 (S-006): the
pose detector's person-1 box had y + h == 1.0020000000000002, and the
union-of-people "subject" roi inherited the same overflow. Those exact
numbers are reproduced here as a regression fixture."""

import math

import pytest

from studio.engine import rulebook as RB


# --------------------------------------------------------------------------
# clamp_box: the pure primitive
# --------------------------------------------------------------------------

def test_an_in_range_box_comes_back_unchanged_identity():
    b = {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4, "name": "person-1"}
    assert RB.clamp_box(b) is b                     # no copy, no rounding noise, when nothing moves


def test_a_box_exactly_on_the_edge_is_unchanged():
    b = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
    assert RB.clamp_box(b) is b


def test_the_s_006_person_box_that_failed_preflight_is_clamped_onto_the_picture():
    # person-1 in partition-of-india shot 1.8 (S-006): y + h == 1.0020000000000002
    person = {"name": "person-1", "x": 0.3715, "y": 0.3646, "w": 0.2731, "h": 0.6374, "source": "auto"}
    assert person["y"] + person["h"] > 1.0
    cb = RB.clamp_box(person)
    assert cb["x"] == 0.3715 and cb["y"] == 0.3646           # x, y untouched: only the overflow is pulled back
    assert cb["h"] == pytest.approx(1.0 - 0.3646, abs=1e-9)
    assert cb["x"] + cb["w"] <= 1.0 and cb["y"] + cb["h"] <= 1.0
    assert cb["name"] == "person-1" and cb["source"] == "auto"  # every other field passes through


def test_the_s_006_subject_roi_union_box_is_clamped_too():
    # roi[0] ("subject", kind group): the union of the three people, same overflow (y + h == 1.002)
    roi = {"name": "subject", "kind": "group", "x": 0.0085, "y": 0.0709, "w": 0.9707, "h": 0.9311, "source": "auto"}
    assert roi["y"] + roi["h"] > 1.0
    cb = RB.clamp_box(roi)
    assert cb["y"] + cb["h"] == pytest.approx(1.0, abs=1e-9)
    assert cb["x"] + cb["w"] <= 1.0


@pytest.mark.parametrize("box, exp", [
    ({"x": -0.1, "y": 0.2, "w": 0.3, "h": 0.4}, {"x": 0.0, "y": 0.2, "w": 0.3, "h": 0.4}),
    ({"x": 0.9, "y": 0.2, "w": 0.3, "h": 0.4}, {"x": 0.9, "y": 0.2, "w": 0.1, "h": 0.4}),
    ({"x": 0.2, "y": 0.9, "w": 0.3, "h": 0.3}, {"x": 0.2, "y": 0.9, "w": 0.3, "h": 0.1}),
    ({"x": 1.2, "y": 0.2, "w": 0.3, "h": 0.4}, {"x": 1.0, "y": 0.2, "w": 0.0, "h": 0.4}),
])
def test_clamp_box_pulls_each_edge_back_onto_the_picture(box, exp):
    cb = RB.clamp_box(dict(box))
    assert (cb["x"], cb["y"], cb["w"], cb["h"]) == (exp["x"], exp["y"], exp["w"], exp["h"])
    assert 0.0 <= cb["x"] <= 1.0 and 0.0 <= cb["y"] <= 1.0
    assert cb["x"] + cb["w"] <= 1.0 + 1e-9 and cb["y"] + cb["h"] <= 1.0 + 1e-9


def test_clamp_box_is_idempotent_and_finite():
    box = {"x": 1.3, "y": -0.2, "w": 0.5, "h": 0.5}
    once = RB.clamp_box(dict(box))
    twice = RB.clamp_box(dict(once))
    assert once == twice
    assert all(math.isfinite(once[k]) for k in ("x", "y", "w", "h"))


# --------------------------------------------------------------------------
# fields(): the clamp is applied to every emitted people[] and roi[] box
# --------------------------------------------------------------------------

def _meas_two_people_one_overflowing(size=(499, 316)):
    # person-1 mirrors the real S-006 measurement: y + h slightly over 1
    return {
        "size": list(size),
        "faces": [],
        "people": [
            {"x": 0.3715, "y": 0.3646, "w": 0.2731, "h": 0.6374, "score": 0.96, "pose": None},
            {"x": 0.0085, "y": 0.0709, "w": 0.3769, "h": 0.9181, "score": 0.92, "pose": None},
        ],
        "saliency": {"x": 0.0938, "y": 0.321, "w": 0.8125, "h": 0.6173, "concentration": 0.5},
    }


def test_fields_clamps_every_located_person_box():
    item = {"id": "S-006", "people": True}            # True: "the ledger does not give an exact count"
    res = RB.fields(item, _meas_two_people_one_overflowing(), "mp:test")
    people = res["fields"]["people"]
    assert people, "the rulebook must have located and emitted people"
    for p in people:
        if not all(k in p for k in ("x", "y", "w", "h")):
            continue
        assert p["x"] + p["w"] <= 1.0 + 1e-9
        assert p["y"] + p["h"] <= 1.0 + 1e-9
        assert 0.0 <= p["x"] <= 1.0 and 0.0 <= p["y"] <= 1.0


def test_fields_clamps_the_roi_subject_box():
    item = {"id": "S-006", "people": True}
    res = RB.fields(item, _meas_two_people_one_overflowing(), "mp:test")
    roi = res["fields"].get("roi") or []
    assert roi, "a subject region must have been chosen"
    for r in roi:
        assert r["x"] + r["w"] <= 1.0 + 1e-9
        assert r["y"] + r["h"] <= 1.0 + 1e-9
        assert 0.0 <= r["x"] <= 1.0 and 0.0 <= r["y"] <= 1.0


def test_fields_leaves_an_in_range_rulebook_run_bit_for_bit_unchanged():
    # a still with no overflowing measurement: clamping must be a true no-op
    item = {"id": "S-999", "people": "none"}
    meas = {"size": [1000, 1000], "faces": [], "people": [],
            "saliency": {"x": 0.3, "y": 0.3, "w": 0.4, "h": 0.4, "concentration": 0.6}}
    res = RB.fields(item, meas, "mp:test")
    roi = res["fields"].get("roi") or []
    assert roi and (roi[0]["x"], roi[0]["y"], roi[0]["w"], roi[0]["h"]) == (0.3, 0.3, 0.4, 0.4)
