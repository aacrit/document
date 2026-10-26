"""GRAMMAR A51: a human subject leads under HOLD, and faces are kept clear
of live text. Pure geometry on synthetic sizes (Real World's own picture
sizes and regions, no picture read) through the engine's own builders
(``render.still_camera``, ``render.engine_cover``, ``tour.subject_plan``,
``tour.end_pose``), so nothing here reads a film or renders a frame."""

import json
import random

import pytest

from studio.engine import journal as J
from studio.engine import motion as M
from studio.engine import render as R
from studio.engine import rulebook as RB
from studio.engine import tour as T
from studio.engine import tourlint as TL

W, H = 1920, 1080
A = 16 / 9
FPS = 30000 / 1001                        # Real World's master rate (A44)
SUB, LT = M.ZONES["SUB"], M.ZONES["LT"]


def _shot(item, *, dur, preset="HOLD", sid="X", **kw):
    return dict({"id": sid, "kind": "archive_still", "_dur": dur, "start_s": 0.0, "_item": item, "preset": preset},
                **kw)


def _spans(dur, *zones):
    return [{"zone": z, "id": f"{z}-1", "box": M.ZONES[z], "t0": 0.0, "t1": dur} for z in zones]


def _plan(s, size, *, zones=(), journal=None):
    """build_plan's own steps for one still: the avoid list (must_show boxes and, A51, every located face against
    every zone up over the shot), still_camera, then engine_cover."""
    item = s["_item"]
    boxes = [M.ZONES[z] for z in zones]
    avoid = ([(T.roi_box(r), zb) for r in T.must_show_regions(item) for zb in boxes]
             + T.face_avoid(item, boxes)) or None
    spans = _spans(float(s["_dur"]), *zones) if zones else None
    cam = R.still_camera(s, size, W, H, words=[], fps=FPS, avoid=avoid)
    return R.engine_cover(s, cam, size, W, H, [], journal, fps=FPS, avoid=avoid, text_spans=spans)


def _events(j):
    return [json.loads(x) for x in j.path.read_text(encoding="utf-8").splitlines()] if j.path.exists() else []


@pytest.fixture
def jr(tmp_path):
    return J.Journal(film="a51", kind="test", out_dir=tmp_path, directory=tmp_path, timings=tmp_path / "t.jsonl")


# --------------------------------------------------------------------------
# 1. A human subject leads under HOLD (Real World's own geometry)
# --------------------------------------------------------------------------

LIBERTY_SIZE = (1540, 1260)                       # S11-NPS-LIBERTY
LIBERTY = {"id": "S11-NPS-LIBERTY", "people": "none", "compose": "golden", "class": "place",
           "roi": [{"name": "subject", "kind": "place", "x": 0.42, "y": 0.50, "w": 0.53, "h": 0.47,
                    "source": "human", "must_show": True}]}
STATUE = (0.06, 0.03, 0.18, 0.54)                 # the VL's "statue of liberty" box (x0, y0, x1, y1)


def test_5_9_a_human_subject_under_hold_takes_the_subject_pass(jr):
    s = _shot(json.loads(json.dumps(LIBERTY)), dur=6.0)
    cam = _plan(s, LIBERTY_SIZE, journal=jr)
    sub = cam["subject"]
    assert cam["macro"] == "HOLD" and cam["cover"] == "subject" and sub["src"] == "subject"
    stops = cam["tour"]["stops"]
    first, last = stops[0], stops[-1]
    # ends low-right on the smoke, golden: the subject's centre on the band on both axes, the subject whole
    assert last["x"] > 0.5 and last["y"] > 0.6
    assert sub["stop"]["verdict"] == "golden" and sub["stop"]["inside"] and sub["stop"]["shown"] == 1.0
    # no rise: the window only ever travels down (or holds) on the way to the smoke
    ys = [st["y"] for st in stops]
    assert all(b >= a - 1e-9 for a, b in zip(ys, ys[1:])) and first["y"] < last["y"]
    # the depth the doctrine's golden placement allows for a box 0.47 of the picture high (A47: the subject's centre
    # on phi on each axis with the box whole): about tour z 1.06, frame z 1.54; the statue leaves by the top, not left
    assert last["z"] == pytest.approx(1.059, abs=0.002)
    lw = T.window(LIBERTY_SIZE, A, last["z"], last["x"], last["y"])
    assert lw[0] < STATUE[2] * LIBERTY_SIZE[0]
    assert any(e["kind"] == "decision" and "made the subject pass" in e["what"] for e in _events(jr))


def test_5_9_a_deliberate_move_preset_stays_the_author_s():
    for preset in ("PUSH", "PULL", "DRIFT", "TILT"):
        s = _shot(json.loads(json.dumps(LIBERTY)), dur=6.0, preset=preset)
        cam = _plan(s, LIBERTY_SIZE)
        assert cam["macro"] == preset and cam.get("cover") is None and cam["subject"] is None, preset


def test_a_written_camera_path_with_a_subject_is_never_changed():
    s = _shot(json.loads(json.dumps(LIBERTY)), dur=6.0, preset=None,
              camera=[{"t": 0.0, "z": 1.0, "x": 0.5, "y": 0.5, "hold": 6.0}])
    cam = _plan(s, LIBERTY_SIZE)
    assert cam["macro"] == "PATH" and [(st["x"], st["y"], st["z"]) for st in cam["tour"]["stops"]][0] == (0.5, 0.5, 1.0)


def test_hold_with_no_subject_region_keeps_today_s_path():
    # a human region that is not the subject (and no must_show) under HOLD is still the author's path
    item = {"people": "none", "roi": [{"name": "sign", "kind": "text", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.1}]}
    cam = _plan(_shot(item, dur=6.0), LIBERTY_SIZE)
    assert cam["macro"] == "HOLD" and cam.get("cover") is None


LETTERING_SIZE = (3000, 2033)                     # S11-LOC-0129, the police car
LETTERING = {"id": "S11-LOC-0129", "people": "none visible inside or near the car (checked at master scan)",
             "class": "object", "compose": "centred:object",                 # the rulebook's, under the human ledger
             "roi": [{"name": "lettering", "kind": "text", "x": 0.655, "y": 0.735, "w": 0.32, "h": 0.235,
                      "source": "human", "must_show": True}]}


def test_5_7_still_ends_with_its_lettering_whole():
    # the rulebook's police car is kept out by the human region (rulebook.overlay), so 5.7 has no subject region:
    # HOLD, the lettering under the subtitle band, steered to the whole sweep that ends at the bottom (as on main)
    s = _shot(json.loads(json.dumps(LETTERING)), dur=7.0)
    cam = _plan(s, LETTERING_SIZE, zones=("SUB",))
    last = cam["tour"]["stops"][-1]
    assert (round(last["x"], 4), round(last["y"], 4), round(last["z"], 4)) == (0.5, 0.585, 1.0)
    lw = T.window(LETTERING_SIZE, A, last["z"], last["x"], last["y"])
    box = T.roi_box(LETTERING["roi"][0])
    assert lw[1] <= box[1] * LETTERING_SIZE[1] and lw[3] >= box[3] * LETTERING_SIZE[1] - 0.5


GOES_SIZE = (1287, 748)                           # S11-NASA-GOES8-ERIN
GOES = {"id": "S11-NASA-GOES8-ERIN", "people": "none", "class": "document", "whole": True,
        "compose": "centred:a satellite record with its own caption and inset, shown as composed",
        "roi": [{"name": "caption", "kind": "text", "x": 0.12, "y": 0.882, "w": 0.73, "h": 0.096, "source": "human",
                 "must_show": True},
                {"name": "ny-inset", "kind": "place", "x": 0, "y": 0, "w": 0.21, "h": 0.31, "source": "human",
                 "must_show": True}]}


def test_3_7_keeps_its_aimed_breath():
    cam = _plan(_shot(json.loads(json.dumps(GOES)), dur=8.0), GOES_SIZE)
    got = [(round(st["x"], 4), round(st["y"], 4), round(st["z"], 4)) for st in cam["tour"]["stops"]]
    assert got == [(0.5, 0.4839, 1.0), (0.5, 0.4954, 1.0)]
    assert cam["subject"]["src"] == "whole" and cam["subject"]["whole_mode"] == "hold"


# --------------------------------------------------------------------------
# 2. Faces: where they are
# --------------------------------------------------------------------------

def test_face_boxes_reads_faces_figures_and_heads():
    item = {"people": [{"name": "a", "x": 0.1, "y": 0.2, "w": 0.2, "h": 0.5,
                        "face": {"x": 0.15, "y": 0.22, "w": 0.05, "h": 0.06}},
                       {"name": "b", "x": 0.5, "y": 0.3, "w": 0.1, "h": 0.5},
                       {"name": "c", "x": 0.7, "y": 0.1, "w": 0.2, "h": 0.6}],
            "roi": [{"name": "c-face", "kind": "face", "x": 0.75, "y": 0.12, "w": 0.05, "h": 0.06},
                    {"name": "subject", "kind": "person", "x": 0.5, "y": 0.3, "w": 0.1, "h": 0.5, "source": "auto",
                     "confidence": 0.9}]}
    got = {f["name"]: (f["src"], tuple(round(v, 4) for v in f["box"])) for f in T.face_boxes(item)}
    assert got["c-face"][0] == "roi"
    assert got["a"] == ("face", (0.15, 0.22, 0.2, 0.28))                         # MediaPipe's face in the figure
    assert got["b"] == ("head", (0.5, 0.3, 0.6, round(0.3 + 0.5 * 0.22, 4)))    # the top 22% of the box
    assert "c" not in got                          # its face region is already counted
    assert "subject" not in got                    # the same box as b, listed once
    assert T.face_boxes({"people": "none", "roi": []}) == []


def test_face_boxes_drop_a_machine_figure_under_the_floor():
    item = {"people": [{"name": "p", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.5, "source": "auto", "confidence": 0.2}]}
    assert T.face_boxes(item) == []


def test_the_rulebook_hands_on_the_face_inside_a_figure():
    assert RB.RULEBOOK_VERSION == "11"               # 9 brought the face; 10 (A52) and 11 (A53) keep it
    face = {"x": 0.4, "y": 0.1, "w": 0.05, "h": 0.05, "score": 0.9, "kp": []}
    stray = {"x": 0.9, "y": 0.9, "w": 0.05, "h": 0.05, "score": 0.9, "kp": []}
    m = {"size": [1600, 1200], "model": "mp:test", "faces": [face, stray],
         "people": [{"x": 0.35, "y": 0.05, "w": 0.2, "h": 0.6, "score": 0.9, "pose": None},
                    {"x": 0.05, "y": 0.3, "w": 0.1, "h": 0.4, "score": 0.9, "pose": None}],
         "saliency": {"x": 0.3, "y": 0.3, "w": 0.4, "h": 0.4, "concentration": 0.1}}
    people = RB.fields({"people": "two men"}, m, "mp:test")["fields"]["people"]
    by_x = {p["x"]: p for p in people}
    assert by_x[0.35]["face"] == {"x": 0.4, "y": 0.1, "w": 0.05, "h": 0.05}
    assert "face" not in by_x[0.05]                 # no face inside it: its head is the top of its box


def test_the_schema_knows_a_figure_s_face():
    good = {"people": [{"name": "p", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.5, "face": {"x": 0.12, "y": 0.12,
                                                                                      "w": 0.05, "h": 0.05}}]}
    bad, unknown = T.item_schema(good)
    assert bad == [] and unknown == []
    bad, _ = T.item_schema({"people": [{"name": "p", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.5, "face": [1, 2]}]})
    assert any("face is a box" in b for b in bad)
    bad, _ = T.item_schema({"people": [{"name": "p", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.5,
                                        "face": {"x": 0.9, "y": 0.1, "w": 0.5, "h": 0.1}}]})
    assert any("past the picture's edge" in b for b in bad)


# --------------------------------------------------------------------------
# 2. Faces: under live text
# --------------------------------------------------------------------------

FULL = (0.0, 0.0, 1000.0, 1000.0)
SQ = (1000.0, 1000.0)


def test_a_face_reads_under_live_text_at_any_overlap():
    span = [{"zone": "LT", "box": (0.0, 0.85, 0.5, 1.0), "t0": 0.0, "t1": 5.0}]
    box = (0.1, 0.80, 0.2, 0.855)                  # an eleventh of the face under the lower third: under the 10% guide
    assert TL.subject_under_text([(1.0, FULL)], box, SQ, text_spans=span)["ok"]
    r = TL.subject_under_text([(1.0, FULL)], box, SQ, text_spans=span, is_face=True)
    assert not r["ok"] and not r["block"] and r["zone"] == "LT"
    assert TL.subject_under_text([(1.0, FULL)], box, SQ, text_spans=span, is_face=True, must_show=True)["block"]
    # the class glyph is not live text: a face under it is not this lint's
    glyph = [{"zone": "glyph", "box": (0.0, 0.85, 0.5, 1.0), "t0": 0.0, "t1": 5.0}]
    assert TL.subject_under_text([(1.0, FULL)], box, SQ, text_spans=glyph, is_face=True)["ok"]
    # nor once the text is gone
    assert TL.subject_under_text([(9.0, FULL)], box, SQ, text_spans=span, is_face=True)["ok"]


def test_face_under_text_names_each_face():
    span = [{"zone": "SUB", "id": "N:1", "box": (0.0, 0.85, 1.0, 1.0), "t0": 0.0, "t1": 5.0}]
    faces = [{"name": "low", "box": (0.1, 0.84, 0.2, 0.9), "src": "head", "must_show": False},
             {"name": "high", "box": (0.1, 0.1, 0.2, 0.2), "src": "face", "must_show": False}]
    rows = TL.face_under_text([(1.0, FULL)], faces, SQ, text_spans=span)
    assert [r["name"] for r in rows] == ["low"] and rows[0]["cue"] == "N:1" and rows[0]["src"] == "head"


def test_avoid_reads_a_face_at_any_overlap_and_never_needs_it_in_frame():
    size = (2000, 1000)
    win = T.window(size, A, 1.0, 0.5, 0.5)
    zone = (0.0, 0.8, 1.0, 1.0)
    graze = (0.5, 0.78, 0.52, 0.802)                # an eleventh of it under the zone
    assert T.avoid_overlap(size, win, [(graze, zone)]) < M.CINE["under_text_share"]
    assert T.avoid_overlap(size, win, [(graze, zone, "face")]) >= M.CINE["under_text_share"]
    outside = (0.99, 0.1, 1.0, 0.2)                 # out of this window: a must_show box must fit, a face need not
    left = T.window(size, A, 1.5, 0.3, 0.5)
    assert not T.avoid_fits(size, left, [(outside, zone)])
    assert T.avoid_fits(size, left, [(outside, zone, "face")])


def test_the_subject_stop_is_steered_off_a_face_under_the_subtitles():
    size = (2000, 1000)
    subj = {"box": (0.41, 0.45, 0.67, 0.82), "kind": "place", "facing": None}
    face = (0.66, 0.73, 0.72, 0.81)
    plain = T.end_pose(subj, size, A, 3.0, record=False)
    assert T.avoid_overlap(size, T.window(size, A, plain["z"], plain["x"], plain["y"]),
                           [(face, SUB, "face")]) >= M.CINE["under_text_share"]
    steered = T.end_pose(subj, size, A, 3.0, record=False, avoid=[(face, SUB, "face")])
    assert steered["avoid_clear"] is True and steered["z"] == plain["z"]
    sw = T.window(size, A, steered["z"], steered["x"], steered["y"])
    assert T.avoid_overlap(size, sw, [(face, SUB, "face")]) == 0.0
    # the smallest move: the same depth and row, only across, and the subject still whole in frame
    assert steered["y"] == plain["y"] and abs(steered["x"] - plain["x"]) < 0.05
    assert sw[0] <= subj["box"][0] * size[0] and sw[2] >= subj["box"][2] * size[0]


def test_the_pass_opens_at_the_near_end_when_the_far_end_carries_a_face_under_text():
    size = (1000, 1000)
    item = {"people": False, "class": "place",
            "roi": [{"name": "subject", "x": 0.16, "y": 0.48, "w": 0.19, "h": 0.23, "kind": "place",
                     "source": "human"},
                    {"name": "f", "kind": "face", "x": 0.38, "y": 0.56, "w": 0.05, "h": 0.07, "source": "human"}]}
    shot = {"id": "X", "kind": "archive_still"}
    roi, persons = T.effective_regions(item)["roi"], T.person_regions(item)
    av = T.face_avoid(item, [SUB])
    far, i0 = T.subject_plan(shot, item, roi, persons, [], size, A, 8.0, 0.0, 3.0, need_whole=False)
    near, i1 = T.subject_plan(shot, item, roi, persons, [], size, A, 8.0, 0.0, 3.0, need_whole=False, avoid=av)
    assert far[0]["y"] < 0.5 < near[0]["y"]                         # top end, then the bottom end
    assert "A51" in i1["timing"]["opens"] and i0["timing"].get("opens") is None
    assert (far[-1]["x"], far[-1]["y"], far[-1]["z"]) == (near[-1]["x"], near[-1]["y"], near[-1]["z"])

    def worst(st):
        return max(T.avoid_overlap(size, w, av) for w in T.windows_of(T.build(st, 8.0, size, A, 3.0), 24.0))
    assert worst(far) >= M.CINE["under_text_share"] and worst(near) == 0.0


def test_an_engine_path_with_a_face_it_cannot_clear_is_a_reviewer_item_never_refused(jr):
    # a picture of the frame's own shape at the fill has nowhere to go: the face under the subtitle band stays,
    # journaled for a reviewer
    size = (1600, 900)
    item = {"people": [{"name": "p", "x": 0.4, "y": 0.80, "w": 0.1, "h": 0.2, "source": "human"}],
            "class": "place", "whole": True}
    cam = _plan(_shot(item, dur=6.0), size, zones=("SUB",), journal=jr)
    assert cam["tour"] is not None
    items = [e for e in _events(jr) if e["kind"] == "lint" and e["rule"] == "face-under-text"]
    assert len(items) == 1 and items[0]["severity"] == "review" and items[0]["status"] == "review"
    assert items[0]["evidence"]["faces"][0]["name"] == "p"


def _a49(s, cam, size, spans, jr):
    fails = []

    def lint(rule, ok, **kw):
        if not ok and kw.get("severity", "block") == "block":
            fails.append(rule)
    R.a49_tour_lints(lint, jr, s, cam, size, FPS, None, spans, T.must_show_regions(s["_item"]))
    return fails


def test_a_written_path_over_a_face_warns_and_blocks_only_a_must_show_face(jr):
    size = (1600, 900)
    face = {"name": "f", "kind": "face", "x": 0.4, "y": 0.84, "w": 0.06, "h": 0.08, "source": "human"}
    person = {"name": "p", "x": 0.38, "y": 0.80, "w": 0.1, "h": 0.2, "source": "human"}
    path = [{"t": 0.0, "z": 1.0, "x": 0.5, "y": 0.5, "hold": 6.0}]
    spans = _spans(6.0, "SUB")
    s = _shot({"people": [person], "class": "place"}, dur=6.0, preset=None, camera=path)
    cam = R.still_camera(s, size, W, H, words=[], fps=FPS)
    assert _a49(s, cam, size, spans, jr) == []
    warns = [e for e in _events(jr) if e["kind"] == "lint" and e["rule"] == "face-under-text"]
    assert len(warns) == 1 and warns[0]["severity"] == "warn"
    s2 = _shot({"people": False, "class": "place", "roi": [dict(face, must_show=True)]}, dur=6.0, preset=None,
               camera=path)
    cam2 = R.still_camera(s2, size, W, H, words=[], fps=FPS)
    assert _a49(s2, cam2, size, spans, jr) == ["subject-under-text"]


# --------------------------------------------------------------------------
# Property: random people under random live text are never refused, every
# person stays shown, and a face left under live text is a reviewer item
# --------------------------------------------------------------------------

def test_property_faces_are_steered_or_reported_never_refused(tmp_path):
    rng = random.Random(51)
    for k in range(60):
        size = rng.choice([(2000, 1000), (1600, 1200), (1200, 1600), (1600, 900)])
        people = []
        for n in range(rng.randint(1, 3)):
            w, h = rng.uniform(0.05, 0.25), rng.uniform(0.1, 0.5)
            x, y = rng.uniform(0.0, 1.0 - w), rng.uniform(0.0, 1.0 - h)
            e = {"name": f"p{n}", "x": round(x, 3), "y": round(y, 3), "w": round(w, 3), "h": round(h, 3),
                 "source": "human"}
            if rng.random() < 0.5:
                e["face"] = {"x": round(x + w * 0.3, 3), "y": round(y + h * 0.02, 3), "w": round(w * 0.4, 3),
                             "h": round(h * 0.15, 3)}
            people.append(e)
        item = {"people": people, "class": rng.choice(["person", "crowd", "place"])}
        if rng.random() < 0.6:
            b = people[0]
            item["roi"] = [{"name": "subject", "kind": "person", "source": "human",
                            **{q: b[q] for q in ("x", "y", "w", "h")}}]
        zones = rng.choice([("SUB",), ("LT",), ("LT", "SUB")])
        preset = rng.choice(["HOLD", "PUSH", None])
        j = J.Journal(film="prop", kind="test", directory=tmp_path, timings=tmp_path / "t.jsonl")
        s = _shot(item, dur=rng.uniform(4.0, 12.0), preset=preset, sid=f"P{k}")
        cam = _plan(s, size, zones=zones, journal=j)              # never raises: the engine never refuses itself
        wins = [w for _, w in R.still_windows(cam, s, size, W, H, hz=FPS)]
        assert T.people_check(wins, T.people_of(item), size)["ok"], k
        left = TL.face_under_text(R.still_windows(cam, s, size, W, H, hz=FPS), T.face_boxes(item), size,
                                  text_spans=_spans(float(s["_dur"]), *zones))
        items = [e for e in _events(j) if e["kind"] == "lint" and e["rule"] == "face-under-text"]
        assert bool(left) == bool(items), k
        if items:
            assert items[0]["severity"] == "review"
