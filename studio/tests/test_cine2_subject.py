"""A47 (cinematography ticket #2): the camera ends on the subject. The
default pass opens at the end of the picture furthest from the subject (the
ledger's ``subject``, else the shot's ``focus``, else ``whole``), sweeps once
and settles on it, composed by class, before the cut. Pure geometry on small
synthetic sizes; nothing is rendered and no film is read."""

import math
import random

import pytest

from studio.engine import journal as J
from studio.engine import motion as M
from studio.engine import overlays as OV
from studio.engine import render as R
from studio.engine import tour as T

W, H = 640, 360
A = W / H
L43, L32, PORTRAIT, WIDE = (1600, 1200), (1800, 1200), (1200, 1600), (3200, 1000)
CINE = M.CINE
LO, HI = CINE["golden_band"]


def subject(x, y, w, h, kind="place", **kw):
    return dict({"name": "subject", "x": x, "y": y, "w": w, "h": h, "kind": kind, "source": "auto",
                 "confidence": 0.9}, **kw)


def cam_for(item, size, dur=8.0, words=None, cover=False, **shot):
    s = dict({"id": "X", "kind": "archive_still", "_dur": dur, "start_s": 0.0, "_item": item}, **shot)
    cam = R.still_camera(s, size, W, H, words=words or [], cover=cover)
    return cam, s


def engine(item, size, dur=8.0, words=None, **shot):
    cam, s = cam_for(item, size, dur, words, **shot)
    return R.engine_cover(s, cam, size, W, H, words or [], None), s


def last_window(cam, size):
    tl = cam["tour"]
    f = T.at(tl, tl["dur"])
    a0, b0, a1, b1 = T.window(size, A, f["z"], f["x"], f["y"])
    return a0 / size[0], b0 / size[1], a1 / size[0], b1 / size[1]


def in_band(v):
    return LO - 1e-6 <= v <= HI + 1e-6 or 1 - HI - 1e-6 <= v <= 1 - LO + 1e-6


def all_frames(cam, dur, hz=24.0):
    return [T.at(cam["tour"], k / hz) for k in range(int(dur * hz) + 1)]


# --------------------------------------------------------------------------
# The default ends on the subject
# --------------------------------------------------------------------------

def test_the_default_ends_on_the_subject_and_starts_at_the_far_end():
    box = (0.2, 0.05, 0.3, 0.3)                              # a place high in a 4:3 picture
    cam, _ = cam_for({"people": False, "class": "place", "compose": "golden", "roi": [subject(*box)]}, L43)
    assert cam["macro"] == "DEFAULT" and cam["subject"]["src"] == "subject"
    st = cam["tour"]["stops"]
    assert st[0]["z"] == 1.0 and st[0]["y"] == pytest.approx(T.settle({"z": 1, "x": .5, "y": 1.0}, L43, A)["y"])
    x0, y0, x1, y1 = last_window(cam, L43)                   # the last frame holds the subject, composed
    assert x0 <= box[0] and y0 <= box[1] and x1 >= box[0] + box[2] and y1 >= box[1] + box[3]
    v = cam["subject"]["stop"]
    assert v["verdict"] == "golden" and v["inside"]
    assert in_band(v["subject_x"]) and in_band(v["subject_y"])
    assert not cam["subject"]["last"]["edge_not_subject"]
    # retired: the old default ran to the bottom edge, away from a subject at the top
    assert T.at(cam["tour"], 8.0)["y"] < 0.5


def test_whole_is_an_upper_weighted_hold_with_one_breath():
    cam, _ = cam_for({"people": False, "class": "place"}, L43, dur=8.0)
    assert cam["subject"]["src"] == "whole"
    tl = cam["tour"]
    assert [g["kind"] for g in tl["segments"]] == ["creep"] and len(tl["stops"]) == 1
    fh = T.fill_window(L43, A)[1]
    want_y = (CINE["whole_weight"] * (L43[1] - fh) + fh / 2) / L43[1]
    st = tl["stops"][0]
    assert st["z"] == 1.0 and st["x"] == 0.5 and st["y"] == pytest.approx(want_y)
    fs = all_frames(cam, 8.0)
    assert all(f["x"] == pytest.approx(0.5) and f["y"] == pytest.approx(want_y) for f in fs)   # no move but the creep
    assert fs[-1]["z"] == pytest.approx(M.TOUR["whole_creep_max"])                           # one breath, capped
    assert all(b["z"] >= a["z"] for a, b in zip(fs, fs[1:]))                                 # one direction
    rec, _ = cam_for({"people": False, "class": "document", "compose": "centred:document"}, L43)
    assert rec["tour"]["stops"][0]["y"] == pytest.approx(0.5)                               # a record: centred


def test_a_long_whole_hold_breathes_at_a_tenth_of_a_percent():
    cam, _ = cam_for({"people": False}, L43, dur=48.0)
    z = T.at(cam["tour"], 48.0)["z"]
    rate = (z - 1.0) / 48.0
    assert z == pytest.approx(M.TOUR["whole_creep_max"]) and 0.001 <= rate <= 0.0015


def test_the_focus_is_the_subject_when_the_ledger_names_none():
    cam, _ = cam_for({"people": False}, PORTRAIT, focus=[0.5, 0.8])
    sub = cam["subject"]
    assert sub["src"] == "focus"
    x0, y0, x1, y1 = last_window(cam, PORTRAIT)
    assert y0 <= 0.8 <= y1 and x0 <= 0.5 <= x1
    assert cam["tour"]["stops"][0]["y"] < cam["tour"]["stops"][-1]["y"]   # from the far end (the top) down to it


def test_the_subject_region_wins_over_the_focus():
    cam, _ = cam_for({"people": False, "roi": [subject(0.1, 0.05, 0.2, 0.2)]}, PORTRAIT, focus=[0.5, 0.9])
    assert cam["subject"]["src"] == "subject"


# --------------------------------------------------------------------------
# Composition
# --------------------------------------------------------------------------

@pytest.mark.parametrize("facing,band", [("right", (LO, HI)), ("left", (1 - HI, 1 - LO))])
def test_golden_band_and_lead_room_by_facing(facing, band):
    person = subject(0.45, 0.3, 0.1, 0.3, kind="person", facing=facing)
    cam, _ = cam_for({"people": [], "class": "person", "compose": "golden", "roi": [person]}, WIDE)
    v = cam["subject"]["stop"]
    assert band[0] - 1e-6 <= v["subject_x"] <= band[1] + 1e-6
    assert v["lead_ok"] and v["lead_room"] >= v["room_behind"]
    assert v["inside"] and cam["tour"]["stops"][-1]["z"] <= CINE["face_zmax"] + 1e-9
    assert abs(v["eyes_y"] - 1 / 3) < abs(v["subject_y"] - 1 / 3) + 0.2


def test_records_are_centred():
    page = subject(0.3, 0.3, 0.3, 0.25, kind="text")
    cam, _ = cam_for({"people": False, "class": "document", "compose": "centred:document", "roi": [page]}, L43)
    v = cam["subject"]["stop"]
    assert v["verdict"] == "centred"
    assert abs(v["subject_x"] - 0.5) <= CINE["centred_band"] and abs(v["subject_y"] - 0.5) <= CINE["centred_band"]


def test_the_end_pose_stays_inside_and_under_the_softness_cap():
    tiny = subject(0.9, 0.9, 0.02, 0.02, kind="object")
    item = {"people": False, "class": "object", "compose": "centred:object", "roi": [tiny]}
    cam, _ = cam_for(item, L43)
    st = cam["tour"]["stops"][-1]
    assert st["z"] <= cam["tour"]["zmax_allowed"] + 1e-9
    x0, y0, x1, y1 = T.window(L43, A, st["z"], st["x"], st["y"])
    assert x0 >= -0.5 and y0 >= -0.5 and x1 <= L43[0] + 0.5 and y1 <= L43[1] + 0.5
    assert cam["subject"]["stop"]["inside"]


# --------------------------------------------------------------------------
# Timing: subject_at, the lead, the settle
# --------------------------------------------------------------------------

LINE = {"id": "N1", "kind": "narration", "start": 1.0, "dur": 5.0,
        "text": "Across the square the President stood at the lectern before the pupils."}


def words(measured):
    ln = dict(LINE)
    if measured:
        toks = ln["text"].split()
        ln["words"] = [{"w": t, "t": ln["start"] + ln["dur"] * i / len(toks)} for i, t in enumerate(toks)]
    return T.shot_words([ln], 0.0, 10.0)


def test_subject_at_arrives_by_the_lead():
    place = subject(0.6, 0.2, 0.2, 0.2)
    item = {"people": False, "roi": [place]}
    for measured in (True, False):
        ws = words(measured)
        onset = T.anchor_time("lectern", ws)
        cam, _ = cam_for(item, L43, dur=10.0, words=ws, subject_at="lectern")
        assert cam["tour"]["stops"][-1]["t"] == pytest.approx(onset - CINE["anchor_lead_s"])


def test_a_named_person_on_estimated_words_arrives_a_second_early_and_holds_through_the_name():
    person = subject(0.45, 0.2, 0.15, 0.4, kind="person")
    figure = {k: person[k] for k in ("x", "y", "w", "h", "source", "confidence")}
    item = {"people": [dict(figure, name="person-1")], "_people_words": "the President",
            "caption_names": ["President"], "caption": "The President at the lectern", "roi": [person]}
    ws = words(False)
    sp = T.anchor_span("President", ws)
    cam, _ = cam_for(item, L43, dur=10.0, words=ws, subject_at="President")
    st = cam["tour"]["stops"][-1]
    assert st["t"] == pytest.approx(sp["t"] - CINE["anchor_estimated_lead_s"])
    assert not cam["cine"]["reframed"]                     # the binding stands: one person, named by the caption
    assert not T.anchor_identity_check(cam["tour"], item, cam["cine"]["regions"], cam["cine"]["persons"])
    ws = words(True)                                       # measured: the 0.5 s lead
    sp = T.anchor_span("President", ws)
    cam, _ = cam_for(item, L43, dur=10.0, words=ws, subject_at="President")
    assert cam["tour"]["stops"][-1]["t"] == pytest.approx(sp["t"] - CINE["anchor_lead_s"])


@pytest.mark.parametrize("kind,settle", [("place", 1.0), ("object", 1.0), ("text", 1.5), ("person", 1.5),
                                         ("face", 1.5)])
def test_the_subject_settles_before_the_cut(kind, settle):
    assert T.settle_for({"kind": kind}) == settle
    reg = subject(0.6, 0.6, 0.15, 0.2, kind=kind)
    late = dict(LINE, start=0.5, dur=7.4, text="And the last word here is lectern")
    ws = T.shot_words([late], 0.0, 8.0)
    for sa in (None, "lectern"):                           # the cue falls 0.4 s before the cut: still settled
        extra = {"subject_at": sa} if sa else {}
        cam, _ = cam_for({"people": False, "roi": [reg]}, L43, dur=8.0, words=ws, **extra)
        tl = cam["tour"]
        arrive = tl["stops"][-1]["t"]
        assert arrive <= 8.0 - settle + 1e-9
        assert not [g for g in tl["segments"] if g["kind"] == "move" and g["t1"] > arrive + 1e-9]


def test_without_subject_at_it_lands_before_the_last_line_ends():
    ws = T.shot_words([dict(LINE, start=0.5, dur=4.0)], 0.0, 10.0)
    cam, _ = cam_for({"people": False, "roi": [subject(0.6, 0.6, 0.15, 0.2)]}, L43, dur=10.0, words=ws)
    assert cam["tour"]["stops"][-1]["t"] == pytest.approx(4.5 - CINE["settle_s"])
    cam, _ = cam_for({"people": False, "roi": [subject(0.6, 0.6, 0.15, 0.2)]}, L43, dur=10.0)
    assert cam["tour"]["stops"][-1]["t"] == pytest.approx(10.0 - CINE["settle_s"])   # no narration: before the cut


def test_no_leg_outruns_the_speed_guides():
    for dur in (2.5, 4.0, 8.0, 20.0):
        cam, s = cam_for({"people": False, "roi": [subject(0.4, 0.85, 0.2, 0.1)]}, PORTRAIT, dur=dur)
        wins = R.still_windows(cam, s, PORTRAIT, W, H)
        assert T.speed_report(wins)["ok"], dur


# --------------------------------------------------------------------------
# No in-shot reversal where the people are located
# --------------------------------------------------------------------------

def test_no_in_shot_reversal_when_the_people_are_located():
    people = [{"name": "person-1", "x": 0.2, "y": 0.1, "w": 0.1, "h": 0.3, "source": "auto", "confidence": 0.9},
              {"name": "person-2", "x": 0.6, "y": 0.15, "w": 0.1, "h": 0.3, "source": "auto", "confidence": 0.9}]
    item = {"people": people, "class": "crowd", "roi": [subject(0.2, 0.1, 0.5, 0.35, kind="group")]}
    cam, s = engine(item, L43)
    assert not T.reversals(cam["tour"])
    wins = [w for _, w in R.still_windows(cam, s, L43, W, H)]
    assert T.people_check(wins, T.people_of(item), L43)["ok"]
    assert not cam["subject"]["need_whole"]


def test_the_near_end_opens_when_the_far_end_would_miss_a_located_person():
    # the subject sits a little above the middle; a person stands at the very top: the far end is the bottom,
    # whose sweep never shows her, so the pass opens at the top (the near end) and still ends on the subject
    people = [{"name": "top", "x": 0.45, "y": 0.0, "w": 0.06, "h": 0.06, "source": "auto", "confidence": 0.9}]
    item = {"people": people, "roi": [subject(0.3, 0.3, 0.3, 0.3)]}
    cam, s = engine(item, L43)
    assert cam["subject"]["timing"].get("opens", "").startswith("the near end")
    assert not T.reversals(cam["tour"])
    wins = [w for _, w in R.still_windows(cam, s, L43, W, H)]
    assert T.people_check(wins, T.people_of(item), L43)["ok"]


def test_an_unlocated_person_sweeps_both_ends_then_settles_on_the_subject():
    item = {"people": "two onlookers on a roof", "roi": [subject(0.3, 0.3, 0.3, 0.3)]}
    cam, s = engine(item, L43)
    assert cam["subject"]["need_whole"]
    wins = [w for _, w in R.still_windows(cam, s, L43, W, H)]
    assert T.people_check(wins, T.people_of(item), L43)["ok"]            # the whole picture is shown (A7)
    v = cam["subject"]["last"]
    assert v["inside"]                                                    # and it still ends on the subject


def test_in_shot_reversal_warns_only_where_every_person_is_located(tmp_path):
    j = J.Journal(film="x", kind="test", out_dir=tmp_path, directory=tmp_path)
    tl = T.build([{"t": 0, "z": 1, "x": .5, "y": 0.0}, {"t": 3, "z": 1, "x": .5, "y": 1.0},
                  {"t": 6, "z": 1, "x": .5, "y": 0.5}], 8.0, L43, A, 3.0)
    assert [r["axis"] for r in T.reversals(tl)] == ["y"]
    cam = {"tour": tl, "macro": "PATH", "subject": None}
    located = {"boxes": [{"name": "a", "box": (0.1, 0.1, 0.2, 0.2)}], "unlocated": 0, "known": True}
    R.subject_lints(j, {"id": "S1"}, cam, located)
    R.subject_lints(j, {"id": "S2"}, cam, dict(located, unlocated=1))
    R.subject_lints(j, {"id": "S3"}, cam, {"boxes": [], "unlocated": 0, "known": True})
    evs = J.read(j.path)
    warn = [e for e in evs if e["kind"] == "lint" and e.get("rule") == "in-shot-reversal"]
    assert [(e["unit"], e["status"], e["severity"]) for e in warn] == [("S1", "fail", "warn")]
    assert any(e["kind"] == "decision" and e.get("unit") == "S2" for e in evs)


# --------------------------------------------------------------------------
# no_zoom: drift only
# --------------------------------------------------------------------------

def test_no_zoom_never_pushes():
    big = (2089, 1186)                                       # a slow pass: A41 layered a push on it (Real World 3.6, 5.1)
    assert max(st["z"] for st in T.default_stops(big, A, 16.0, zmax=3.0)) > 1.1        # the bug, as it was
    for st in (T.default_stops(big, A, 16.0, zmax=3.0, no_zoom=True),
               T.covering_stops(big, A, 16.0, zmax=3.0, no_zoom=True)):
        tl = T.build(st, 16.0, big, A, 3.0, no_zoom=True)
        assert all(f["z"] == 1.0 for _, f in T.samples(tl, 24.0))
    for item, size in (({"people": False, "roi": [subject(0.3, 0.3, 0.1, 0.1)]}, L43),
                       ({"people": False}, L43), ({"people": "smoke and two figures"}, L32)):
        cam, s = engine(item, size, dur=16.0, no_zoom=True)
        assert all(f["z"] == pytest.approx(1.0) for f in all_frames(cam, 16.0))
        assert cam["subject"]["no_zoom"]


# --------------------------------------------------------------------------
# match: prev
# --------------------------------------------------------------------------

def test_match_prev_opens_with_the_subject_where_the_last_shot_left_its_own(tmp_path):
    prev_item = {"people": False, "roi": [subject(0.1, 0.1, 0.2, 0.2)]}
    prev, ps = cam_for(prev_item, L43, id="P")
    ps["_cam"] = prev
    screen = prev["subject"]["screen"]
    j = J.Journal(film="x", kind="test", out_dir=tmp_path, directory=tmp_path)
    s = {"id": "X", "kind": "archive_still", "_dur": 8.0, "start_s": 0.0, "match": "prev",
         "transition_in": {"type": "cut"}, "_item": {"people": False, "roi": [subject(0.5, 0.4, 0.2, 0.2)]}}
    R.match_prev(j, s, ps)
    assert s["_match_screen"] == screen
    cam = R.still_camera(s, L43, W, H, words=[])
    tl = cam["tour"]
    got = T.screen_of(tl, (0.6, 0.5), t=0.0)
    assert math.hypot(got[0] - screen[0], got[1] - screen[1]) == pytest.approx(cam["subject"]["match_error"], abs=1e-3)
    assert cam["subject"]["match_error"] < 0.05
    assert tl["stops"][0].get("match") == "prev"
    assert cam["subject"]["last"]["inside"]                  # and it still ends on its own subject
    # a dissolve waits for #9; a clip before gives no position: warnings, and the default pass
    s2 = dict(s, transition_in={"type": "dissolve", "s": 0.75})
    R.match_prev(j, s2, ps)
    s3 = dict(s)
    R.match_prev(j, s3, {"id": "C", "kind": "archive_video"})
    assert "_match_screen" not in s2 and "_match_screen" not in s3
    warn = [e for e in J.read(j.path) if e["kind"] == "lint" and e.get("rule") == "cine-match"]
    assert [e["status"] for e in warn] == ["pass", "fail", "fail"]


# --------------------------------------------------------------------------
# The people guard still holds (property)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(40))
def test_property_the_subject_pass_never_leaves_a_person_unseen(seed):
    rng = random.Random(seed)
    size = rng.choice([L43, L32, PORTRAIT, WIDE, (1920, 1080), (2089, 1186)])
    people = []
    for k in range(rng.randint(0, 5)):
        w, h = rng.uniform(0.01, 0.2), rng.uniform(0.02, 0.6)
        people.append({"name": f"person-{k + 1}", "x": rng.uniform(0, 1 - w), "y": rng.uniform(0, 1 - h), "w": w,
                       "h": h, "source": "auto", "confidence": rng.uniform(0.3, 1.0),
                       **({"facing": rng.choice(["left", "right", "camera"])} if rng.random() < 0.5 else {})})
    item = {"people": people or rng.choice([False, "none visible", "a crowd"]),
            "class": rng.choice(["person", "crowd", "place", "document", "map"])}
    if rng.random() < 0.7:
        w, h = rng.uniform(0.02, 0.9), rng.uniform(0.02, 0.9)
        item["roi"] = [subject(rng.uniform(0, 1 - w), rng.uniform(0, 1 - h), w, h,
                               kind=rng.choice(["person", "group", "place", "object", "text", "face"]))]
    shot = {}
    if rng.random() < 0.3:
        shot["no_zoom"] = True
    if rng.random() < 0.3:
        shot["preset"] = rng.choice(["HOLD", "PUSH", "TILT"])
    dur = rng.uniform(2.5, 30.0)
    cam, s = engine(item, size, dur=dur, **shot)
    wins = [w for _, w in R.still_windows(cam, s, size, W, H)]
    assert T.people_check(wins, T.people_of(item), size)["ok"]
    assert not T.face_cap_check(cam["tour"], cam["cine"]["persons"])
    if cam.get("subject") is not None:                      # the engine's pass ends on its subject
        v = cam["subject"]["last"]
        assert v["centre_in_frame"] and not v["edge_not_subject"]
        if no_zoom := shot.get("no_zoom"):
            assert all(f["z"] == pytest.approx(1.0) for f in all_frames(cam, dur, 8.0)), no_zoom
    assert all(f["z"] >= 1.0 - 1e-9 for f in all_frames(cam, dur, 8.0))
