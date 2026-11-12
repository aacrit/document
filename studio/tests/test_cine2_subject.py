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
from studio.engine import tourlint as TL

W, H = 640, 360
A = W / H
L43, L32, PORTRAIT, WIDE = (1600, 1200), (1800, 1200), (1200, 1600), (3200, 1000)
CINE = M.CINE
LO, HI = CINE["golden_band"]


def subject(x, y, w, h, kind="place", **kw):
    return dict({"name": "subject", "x": x, "y": y, "w": w, "h": h, "kind": kind, "source": "auto",
                 "confidence": 0.9}, **kw)


def cam_for(item, size, dur=8.0, words=None, cover=False, fps=None, **shot):
    s = dict({"id": "X", "kind": "archive_still", "_dur": dur, "start_s": 0.0, "_item": item}, **shot)
    cam = R.still_camera(s, size, W, H, words=words or [], cover=cover, fps=fps)
    return cam, s


def engine(item, size, dur=8.0, words=None, fps=24.0, **shot):
    cam, s = cam_for(item, size, dur, words, fps=fps, **shot)
    return R.engine_cover(s, cam, size, W, H, words or [], None, fps=fps), s


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


NEAR = (1920, 1150)                                          # the fill shows 94% of it: a whole still holds


def test_whole_is_an_upper_weighted_hold_with_one_drift_breath():
    cam, _ = cam_for({"people": False, "class": "place"}, NEAR, dur=8.0)
    assert cam["subject"]["src"] == "whole" and cam["subject"]["whole_mode"] == "hold"
    tl = cam["tour"]
    assert [g["kind"] for g in tl["segments"]] == ["creep"] and len(tl["stops"]) == 1
    fh = T.fill_window(NEAR, A)[1]
    want_y = (CINE["whole_weight"] * (NEAR[1] - fh) + fh / 2) / NEAR[1]
    st = tl["stops"][0]
    assert st["z"] == 1.0 and st["x"] == 0.5 and st["y"] == pytest.approx(want_y)
    fs = all_frames(cam, 8.0)
    assert all(f["z"] == pytest.approx(1.0) for f in fs)                 # the breath never pushes: a drift
    dy = [b["y"] - a["y"] for a, b in zip(fs, fs[1:])]
    assert all(d >= -1e-12 for d in dy) or all(d <= 1e-12 for d in dy)   # one direction
    drift_px = abs(fs[-1]["y"] - fs[0]["y"]) * NEAR[1]
    assert 0 < drift_px <= (M.TOUR["whole_creep_max"] - 1.0) * fh + 1e-6
    assert cam["subject"]["last"]["shown"] == pytest.approx(T.fill_window(NEAR, A)[1] / NEAR[1], abs=1e-3)
    rec, _ = cam_for({"people": False, "class": "document", "compose": "centred:document"}, NEAR)
    assert rec["tour"]["stops"][0]["y"] == pytest.approx(0.5)                               # a record: centred


def test_a_long_whole_hold_breathes_a_few_per_cent_at_most():
    cam, _ = cam_for({"people": False}, NEAR, dur=48.0)
    fs = all_frames(cam, 48.0, 4.0)
    fh = T.fill_window(NEAR, A)[1]
    total = abs(fs[-1]["y"] - fs[0]["y"]) * NEAR[1] / fh
    assert all(f["z"] == pytest.approx(1.0) for f in fs) and 0 < total <= M.TOUR["whole_creep_max"] - 1.0 + 1e-9
    assert total / 48.0 <= 0.0015                                       # 0.1 to 0.15% a second over a long hold
    # a picture of the frame's own shape has no room to drift: it breathes in, at most 1.06
    cam, _ = cam_for({"people": False}, (1920, 1080), dur=48.0)
    assert T.at(cam["tour"], 48.0)["z"] == pytest.approx(M.TOUR["whole_creep_max"])


def test_goes8_s_caption_stays_in_frame_on_its_whole_hold():
    # Real World 3.7 (GOES-8, 1287x748, a map): the burned caption's date line is rows 662 to 729. The whole hold
    # never pushes, so every frame keeps the full width and those rows
    size = (1287, 748)
    cam, _ = cam_for({"people": "none", "class": "map", "compose": "centred:map"}, size, dur=8.0)
    assert cam["subject"]["whole_mode"] == "hold"
    for f in all_frames(cam, 8.0, 30000 / 1001):
        x0, y0, x1, y1 = T.window(size, A, f["z"], f["x"], f["y"])
        assert f["z"] == pytest.approx(1.0) and x0 <= 0.5 and x1 >= size[0] - 0.5
        assert y0 <= 662 and y1 >= 729


@pytest.mark.parametrize("cls,size,axis,rising", [("place", L43, 1, True), ("person", PORTRAIT, 1, True),
                                                  ("document", L43, 1, False), ("map", PORTRAIT, 1, False),
                                                  ("place", WIDE, 0, False)])
def test_a_whole_its_fill_cannot_show_sweeps_once_end_to_end(cls, size, axis, rising):
    item = {"people": False, "class": cls}
    if cls in ("document", "map"):
        item["compose"] = f"centred:{cls}"
    cam, s = cam_for(item, size, dur=10.0)
    assert cam["subject"]["whole_mode"] == "sweep"
    tl = cam["tour"]
    assert not T.reversals(tl)
    key = "xy"[axis]
    a, b = tl["stops"][0][key], tl["stops"][-1][key]
    assert (a > b) if rising else (a < b)                    # rising for people and places; reading order or l to r
    wins = [w for _, w in R.still_windows(cam, s, size, W, H)]
    assert T.covered(wins, T.whole_box(size, A), size)
    fs = all_frames(cam, 10.0)
    assert all(f["z"] == pytest.approx(1.0) for f in fs)     # then a drift-only breath


def test_whole_hold_min_shown_switches_hold_and_sweep(monkeypatch):
    monkeypatch.setitem(M.CINE, "whole_hold_min_shown", 0.0)
    assert cam_for({"people": False}, L43)[0]["subject"]["whole_mode"] == "hold"
    monkeypatch.setitem(M.CINE, "whole_hold_min_shown", 1.01)
    assert cam_for({"people": False}, NEAR)[0]["subject"]["whole_mode"] == "sweep"
    assert M.CINE["whole_hold_min_shown"] != M.WHOLE_HOLD_MIN_SHOWN


def test_the_default_value_is_the_founder_s_option_c():
    assert M.WHOLE_HOLD_MIN_SHOWN == 0.90 and M.CINE["whole_hold_min_shown"] == M.WHOLE_HOLD_MIN_SHOWN


def test_a_whole_sweep_ends_toward_the_next_shot_s_matched_subject():
    for toward, low_end in (([0.7, 0.8], True), ([0.7, 0.2], False)):
        cam, _ = cam_for({"people": False, "class": "place"}, L43, _end_toward=toward)
        end = cam["tour"]["stops"][-1]["y"]
        bottom = T.settle({"z": 1, "x": .5, "y": 1.0}, L43, A)["y"]
        assert (end == pytest.approx(bottom)) == low_end
        assert cam["subject"]["point"] == toward              # the match carries that point's screen position
    nxt = {"id": "N", "kind": "archive_still", "match": "prev", "transition_in": {"type": "cut"},
           "_item": {"people": False, "roi": [subject(0.6, 0.6, 0.2, 0.2)]}}
    assert R.next_subject(nxt) == pytest.approx([0.7, 0.7])
    assert R.next_subject(dict(nxt, transition_in={"type": "dissolve"})) == pytest.approx([0.7, 0.7])  # A53
    assert R.next_subject(dict(nxt, transition_in={"type": "dip"})) is None
    assert R.next_subject(dict(nxt, match=None)) is None


def test_a_declared_whole_beats_an_old_focus_and_warns(tmp_path):
    cam, s = cam_for({"people": False, "whole": True}, L43, focus=[0.5, 0.9])
    assert cam["subject"]["src"] == "whole" and cam["subject"]["focus_ignored"]
    j = J.Journal(film="x", kind="test", out_dir=tmp_path, directory=tmp_path)
    R.subject_lints(j, s, cam, T.people_of(s["_item"]))
    assert [e["rule"] for e in J.read(j.path) if e["kind"] == "lint"] == ["cine-whole-focus"]
    # the rulebook's whole (its fallback, A45) is no declaration: the shot's focus is the subject
    cam, _ = cam_for({"people": False, "whole": True}, L43, focus=[0.5, 0.9],
                     _vision={"from_rulebook": ["whole"]})
    assert cam["subject"]["src"] == "focus"


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
# A54 (entering mid-move) replaced A49's opening settle: the pass leaves the cut already moving
# --------------------------------------------------------------------------

def test_the_pass_enters_already_moving_at_the_creep():
    cam, _ = cam_for({"people": False, "roi": [subject(0.1, 0.1, 0.1, 0.1)]}, L43, dur=20.0)
    tl = cam["tour"]
    g0 = tl["segments"][0]
    assert g0["kind"] == "move" and g0["t0"] <= 1e-9 and g0["v0"] > 0.0
    a, b = T.at(tl, 0.0), T.at(tl, 1 / 24)
    assert any(abs(a[k] - b[k]) > 1e-9 for k in ("x", "y", "z"))
    # it leaves at the creep, never a dead stop at the cut
    assert tl["segments"][-1]["v1"] > 0.0


def test_a_matched_opening_is_never_held_artificially():
    # a move already running across the cut (match: "prev"): A49's hold is never inserted
    cam, _ = cam_for({"people": False, "roi": [subject(0.1, 0.1, 0.1, 0.1)]}, L43, dur=20.0,
                     _match_screen=[0.9, 0.9])
    tl = cam["tour"]
    assert tl["segments"][0]["t0"] <= 1e-6


def test_the_hold_never_steals_time_from_a_tight_arrival():
    # a shot too short for both the leg's own minimum time and a 0.5 s hold: no hold is forced, and the pass
    # still keeps to the speed guides (A47's own priority, reach the subject in time, wins, as it always has)
    cam, s = cam_for({"people": False, "roi": [subject(0.1, 0.1, 0.1, 0.1)]}, L43, dur=0.6)
    tl = cam["tour"]
    assert tl["stops"][0].get("hold", 0.0) <= 1e-9
    wins = R.still_windows(cam, s, L43, W, H)
    assert T.speed_report(wins)["ok"]


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
    # A53: a dissolve matches the same way as a cut; a dip, or a clip before, gives no position: warnings
    s2 = dict(s, transition_in={"type": "dissolve", "s": 0.75})
    R.match_prev(j, s2, ps)
    assert s2["_match_screen"] == screen
    s2b = dict(s, transition_in={"type": "dip", "s": 0.75})
    R.match_prev(j, s2b, ps)
    s3 = dict(s)
    R.match_prev(j, s3, {"id": "C", "kind": "archive_video"})
    assert "_match_screen" not in s2b and "_match_screen" not in s3
    warn = [e for e in J.read(j.path) if e["kind"] == "lint" and e.get("rule") == "cine-match"]
    assert [e["status"] for e in warn] == ["pass", "pass", "fail", "fail"]


# --------------------------------------------------------------------------
# must_show, the covering pass's holds, no_zoom presets, people kept in the drift
# --------------------------------------------------------------------------

NTSC = 30000 / 1001


def test_the_default_never_leaves_a_must_show_region_unseen():
    sign = {"name": "sign", "x": 0.4, "y": 0.0, "w": 0.2, "h": 0.06, "must_show": True}
    for item in ({"people": False, "roi": [subject(0.3, 0.3, 0.3, 0.3), sign]},          # far end is the bottom
                 {"people": False, "roi": [sign]},                                        # whole, swept or held
                 {"people": False, "roi": [subject(0.3, 0.3, 0.3, 0.3), dict(sign, must_show=None)],
                  "must_show": ["sign"]}):
        cam, s = engine(item, L43, fps=NTSC)
        wins = [w for _, w in R.still_windows(cam, s, L43, W, H, hz=NTSC)]
        assert not T.must_show(wins, item, L43)
        assert not T.reversals(cam["tour"]) or cam["subject"]["need_whole"]


def test_a_person_the_sweep_passes_between_frames_is_held_whole():
    # seed 844's geometry: a 561 px figure in a 562.5 px window, swept at 29.97, never whole in any one frame
    size = (1000, 750)
    assert T.fill_window(size, A)[1] == pytest.approx(562.5)
    fig = {"name": "person-1", "x": 0.45, "y": 0.1, "w": 0.1, "h": 561 / 750, "source": "auto", "confidence": 0.9}
    item = {"people": [fig], "roi": [subject(0.0, 0.0, 1.0, 0.05)]}
    cam, s = engine(item, size, dur=3.0, fps=NTSC)
    wins = [w for _, w in R.still_windows(cam, s, size, W, H, hz=NTSC)]
    assert T.people_check(wins, T.people_of(item), size)["ok"]


@pytest.mark.parametrize("preset", ["PUSH", "PULL", "DRIFT", "TILT", "DETAIL"])
def test_no_zoom_turns_a_zooming_preset_into_a_drift(preset):
    item = {"people": "none", "roi": [{"name": "the shapes", "x": 0.2, "y": 0.2, "w": 0.5, "h": 0.5}]}
    cam, s = engine(item, L43, preset=preset, no_zoom=True, region={"x": 0.4, "y": 0.4})
    assert all(f["z"] == pytest.approx(1.0) for f in all_frames(cam, 8.0))


def test_the_closing_drift_keeps_every_located_person_in_frame():
    a = {"name": "person-1", "x": 0.40, "y": 0.3, "w": 0.08, "h": 0.4, "source": "auto", "confidence": 0.9}
    b = {"name": "person-2", "x": 0.52, "y": 0.3, "w": 0.08, "h": 0.4, "source": "auto", "confidence": 0.9}
    item = {"people": [a, b], "class": "crowd", "roi": [subject(0.40, 0.3, 0.2, 0.4, kind="group")]}
    cam, _ = engine(item, L43, dur=20.0, no_zoom=True)
    last = last_window(cam, L43)
    for p in (a, b):
        assert last[0] <= p["x"] + 1e-6 and last[2] >= p["x"] + p["w"] - 1e-6
        assert last[1] <= p["y"] + 1e-6 and last[3] >= p["y"] + p["h"] - 1e-6


def test_a_reversal_for_unlocated_people_only_is_journaled(tmp_path):
    j = J.Journal(film="x", kind="test", out_dir=tmp_path, directory=tmp_path)
    tl = T.build([{"t": 0, "z": 1, "x": .5, "y": 0.0}, {"t": 3, "z": 1, "x": .5, "y": 1.0},
                  {"t": 6, "z": 1, "x": .5, "y": 0.5}], 8.0, L43, A, 3.0)
    R.subject_lints(j, {"id": "S9"}, {"tour": tl, "subject": None}, {"boxes": [], "unlocated": 2, "known": True})
    evs = J.read(j.path)
    assert any(e["kind"] == "decision" and e.get("unit") == "S9" for e in evs)
    assert not [e for e in evs if e["kind"] == "lint"]


# --------------------------------------------------------------------------
# Rulebook 6: a cue and a VL label match through a short synonym table
# --------------------------------------------------------------------------

def test_cue_and_label_synonyms_and_the_recorded_answers():
    from studio.engine import rulebook as RB
    assert RB.RULEBOOK_VERSION == "11"                # 10: quoted text, two things, a vantage (A52); 11: box clamp (A53)
    smoke = {"regions": [{"kind": "object", "label": "smoke", "x": 0.55, "y": 0.3, "w": 0.3, "h": 0.25}]}
    sub, why = RB.vl_subject("place", smoke, {"title": "From orbit", "people": "none"}, ["plume"])
    assert sub is not None and "plume" in why
    # recorded VL answers (Real World, the pinned qwen2.5vl key, cached in the stills ledger's sidecar):
    # 1.4 (Fisch): "south tower" in the title finds the VL's "building" on the left
    fisch = {"regions": [{"h": 0.86, "kind": "object", "label": "smoke", "w": 0.79, "x": 0.0, "y": 0.14},
                         {"h": 0.29, "kind": "object", "label": "fire", "w": 0.215, "x": 0.38, "y": 0.675},
                         {"h": 1.0, "kind": "place", "label": "sky", "w": 1.0, "x": 0.0, "y": 0.0},
                         {"h": 0.68, "kind": "place", "label": "building", "w": 0.385, "x": 0.0, "y": 0.32}]}
    sub, _ = RB.vl_subject("place", fisch, {"title": "United Airlines 175 strikes the south tower, seen from "
                                                     "Greenwich Village"}, [])
    assert sub["label"] == "building" and sub["x"] == 0.0
    # C0 (ISS003-E-5388), prompt v1: the VL answered one region, "urban landscape"; no synonym makes a plume of
    # it, so it stays whole (the correction was a new measurement, prompt v2, never a hand-drawn box: #2b below)
    iss = {"regions": [{"h": 1.0, "kind": "place", "label": "urban landscape", "w": 1.0, "x": 0.0, "y": 0.0}]}
    assert RB.vl_subject("place", iss, {"title": "New York from the International Space Station"}, ["plume"])[0] is None


# --------------------------------------------------------------------------
# The people guard still holds (property)
# --------------------------------------------------------------------------

LINE_P = {"id": "NP", "kind": "narration", "start": 0.5, "dur": 4.0,
          "text": "Across the harbour the plume rose over the tower and the boat."}


@pytest.mark.parametrize("seed", list(range(60)) + [844])
def test_property_the_subject_pass_never_leaves_a_person_or_must_show_unseen(seed):
    rng = random.Random(seed)
    size = rng.choice([L43, L32, PORTRAIT, WIDE, (1920, 1080), (2089, 1186), (1000, 750), NEAR])
    hz = rng.choice([24.0, NTSC])
    people = []
    for k in range(rng.randint(0, 5)):
        w, h = rng.uniform(0.01, 0.2), rng.uniform(0.02, 0.75)
        people.append({"name": f"person-{k + 1}", "x": rng.uniform(0, 1 - w), "y": rng.uniform(0, 1 - h), "w": w,
                       "h": h, "source": "auto", "confidence": rng.uniform(0.3, 1.0),
                       **({"facing": rng.choice(["left", "right", "camera"])} if rng.random() < 0.5 else {})})
    item = {"people": people or rng.choice([False, "none visible", "a crowd"]),
            "class": rng.choice(["person", "crowd", "place", "document", "map"])}
    roi = []
    if rng.random() < 0.7:
        w, h = rng.uniform(0.02, 0.9), rng.uniform(0.02, 0.9)
        roi.append(subject(rng.uniform(0, 1 - w), rng.uniform(0, 1 - h), w, h,
                           kind=rng.choice(["person", "group", "place", "object", "text", "face"])))
    if rng.random() < 0.4:
        w, h = rng.uniform(0.02, 0.3), rng.uniform(0.02, 0.3)
        roi.append({"name": "sign", "x": rng.uniform(0, 1 - w), "y": rng.uniform(0, 1 - h), "w": w, "h": h,
                    "must_show": True})
    if roi:
        item["roi"] = roi
    if rng.random() < 0.15:
        item["whole"] = True
    shot = {}
    if rng.random() < 0.3:
        shot["no_zoom"] = True
    if rng.random() < 0.3:
        shot["preset"] = rng.choice(["HOLD", "PUSH", "TILT", "DETAIL", "FILL"])
        shot["region"] = {"x": rng.random(), "y": rng.random()}
    if rng.random() < 0.3:
        shot["focus"] = [rng.random(), rng.random()]
    if rng.random() < 0.3:
        shot["subject_at"] = rng.choice(["plume", "tower", "boat", "harbour"])
    if rng.random() < 0.3:
        shot["_match_screen"] = [rng.random(), rng.random()]
        shot["match"] = "prev"
    dur = rng.uniform(2.5, 30.0)
    words = T.shot_words([LINE_P], 0.0, dur)
    cam, s = cam_for(item, size, dur, words, **shot)
    cam = R.engine_cover(s, cam, size, W, H, words, None, fps=hz)
    wins = [w for _, w in R.still_windows(cam, s, size, W, H, hz=hz)]
    assert T.people_check(wins, T.people_of(item), size)["ok"]
    if cam.get("subject") is not None:                      # the engine's own pass: must_show seen, ends on subject
        assert not T.must_show(wins, item, size)
        v = cam["subject"]["last"]
        assert v["centre_in_frame"] and not v["edge_not_subject"]
    assert not T.face_cap_check(cam["tour"], cam["cine"]["persons"])
    if shot.get("no_zoom"):
        assert all(f["z"] == pytest.approx(1.0) for f in all_frames(cam, dur, 8.0))
    assert all(f["z"] >= 1.0 - 1e-9 for f in all_frames(cam, dur, 8.0))


# --------------------------------------------------------------------------
# Re-review: a matched whole sweep never comes back; holds fit the time; times only go forward
# --------------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(48))
def test_a_whole_sweep_opened_by_a_match_never_comes_back(seed):
    rng = random.Random(seed)
    size = rng.choice([L43, L32, PORTRAIT, WIDE, (1000, 750)])
    item = {"people": rng.choice([False, "none visible"]), "class": rng.choice(["place", "crowd", "document"])}
    cam, s = cam_for(item, size, rng.uniform(2.5, 20.0), _match_screen=[rng.random(), rng.random()], match="prev",
                     fps=NTSC, no_zoom=rng.random() < 0.5)
    assert cam["subject"]["src"] == "whole" and cam["subject"]["whole_mode"] == "sweep"
    assert not T.reversals(cam["tour"])
    assert cam["tour"]["stops"][0].get("match") == "prev"


def test_a_whole_sweep_that_a7_needs_drops_a_match_that_cannot_show_it_all():
    cam, s = engine({"people": "a crowd", "class": "crowd"}, L43, dur=8.0, fps=NTSC,
                    _match_screen=[0.5, 0.5], match="prev")
    assert not T.reversals(cam["tour"])
    wins = [w for _, w in R.still_windows(cam, s, L43, W, H, hz=NTSC)]
    assert T.people_check(wins, T.people_of(s["_item"]), L43)["ok"]


@pytest.mark.parametrize("size,dur", [((1200, 1600), 2.5), ((1200, 1600), 1.2), ((1000, 750), 1.2)])
def test_holds_on_people_fit_the_time_and_stop_times_only_go_forward(size, dur):
    boxes = [(0.1 + 0.2 * k, 0.05 + 0.18 * k, 0.15 + 0.2 * k, 0.2 + 0.18 * k) for k in range(4)]
    pose = {"z": 1.0, "x": 0.5, "y": 0.5}
    wps = [dict(T.settle({"z": 1.0, "x": (b[0] + b[2]) / 2, "y": (b[1] + b[3]) / 2}, size, A), _hold=0.3)
           for b in boxes]
    stops, timing = T.subject_stops(size, A, dur, pose, arrive=dur, settle_s=1.0, need_whole=True,
                                    waypoints=wps, hz=NTSC)
    ts = [st["t"] for st in stops]
    assert all(b >= a - 1e-9 for a, b in zip(ts, ts[1:])) and ts[-1] <= dur + 1e-9
    moves = [(a, b) for a, b in zip(stops, stops[1:]) if not T._same(a, b)]
    assert all(b["t"] > a["t"] for a, b in moves)            # every move takes time
    T.build(stops, dur, size, A, 3.0)


def test_build_refuses_engine_stop_times_that_go_back():
    with pytest.raises(T.TourError, match="go back"):
        T.build([{"t": 0.0, "z": 1, "x": .5, "y": .5}, {"t": 1.0, "z": 1, "x": .5, "y": .2},
                 {"t": 0.5, "z": 1, "x": .5, "y": .8}], 2.0, L43, A, 3.0)


# --------------------------------------------------------------------------
# #2b: prompt v2 regions, Real World C0's plume, and rulebook 7 (seen from above)
# --------------------------------------------------------------------------

def _recorded(shot):
    import json
    from pathlib import Path
    fx = json.loads((Path(__file__).resolve().parent / "fixture" / "vision-vl.json").read_text(encoding="utf-8"))
    return fx["stills"][shot]


C0_SIZE = (3000, 1992)                                       # ISS003-E-5388 as saved
C0_LINE = {"id": "N:C-1", "kind": "narration", "start": 12.0, "dur": 4.0,
           "text": "the crew of the International Space Station had photographed the plume"}


def _c0_item():
    from studio.engine import rulebook as RB
    rec = _recorded("C0")
    out = RB.fields(rec["item"], rec["measure"], rec["measure"]["model"], vl=rec["vl"], cues=rec["cues"],
                    vl_model=rec["vl"]["model"])
    return RB.overlay(rec["item"], out["fields"])[0], out


def test_c0_s_recorded_v2_answer_finds_the_plume_where_the_picture_has_it():
    # checked against the picture: the pale plume runs from the tip of Manhattan, at about the frame's centre and
    # 47% down, to the right edge, between about 28% and 48% down. The VL's "smoke trail" box (normalized v2)
    # starts 2% right of the plume's source and holds the rest of it, a third of the height down.
    item, out = _c0_item()
    sub = item["roi"][0]
    assert (sub["x"], sub["y"], sub["w"], sub["h"]) == (0.52, 0.26, 0.48, 0.23)
    assert sub["name"] == "subject" and sub["kind"] == "object" and sub["source"] == "auto"
    assert "smoke trail" in out["why"]["vl"] and "plume" in out["why"]["vl"] and "cue" in out["why"]["vl"]
    assert 0.45 <= sub["x"] <= 0.55 and sub["x"] + sub["w"] == pytest.approx(1.0)      # centre to the right edge
    assert 0.3 <= sub["y"] + sub["h"] / 2 <= 0.42                                          # about a third down
    assert "whole" not in item and item["aerial"] is True and item["class"] == "place"
    # the cloud the VL also boxed there shares no word with the cue; the whole-picture regions are never subjects
    assert any(g["label"] == "cloud" for g in _recorded("C0")["vl"]["regions"])


def test_c0_s_subject_pass_arrives_before_plume_and_ends_on_it():
    item, _ = _c0_item()
    ws = T.shot_words([C0_LINE], 0.0, 20.0)
    onset = T.anchor_time("plume", ws)
    cam, s = engine(item, C0_SIZE, dur=20.0, words=ws, fps=NTSC, subject_at="plume")
    st = cam["tour"]["stops"]
    assert cam["subject"]["src"] == "subject" and st[-1].get("roi") == "subject"
    assert st[-1]["t"] == pytest.approx(onset - CINE["anchor_lead_s"]) and st[-1]["t"] < onset
    assert not T.reversals(cam["tour"])
    x0, y0, x1, y1 = last_window(cam, C0_SIZE)
    b = item["roi"][0]
    assert x0 <= b["x"] + 1e-6 and y0 <= b["y"] + 1e-6 and x1 >= b["x"] + b["w"] - 1e-6 and y1 >= b["y"] + b["h"] - 1e-6
    assert cam["subject"]["last"]["shown"] == pytest.approx(1.0)


def test_seen_from_above_reads_the_ledger_s_own_words():
    from studio.engine import rulebook as RB
    for text, word in (("From orbit: New York harbour", "orbit"), ("an orbital photograph", "orbital"),
                       ("New York from the International Space Station", "international space station"),
                       ("ISS003-E-5388", "ISS"), ("Photographed by the ISS crew", "ISS"),
                       ("A black-and-white satellite view", "satellite"), ("GOES-8, 14:39 UTC", "GOES"),
                       ("An aerial photograph of the site", "aerial"), ("Lower Manhattan from the air", "from the air"),
                       ("the pile seen from overhead", "from overhead")):
        assert RB.seen_from_above({"title": text}) == word, text
    # words that also describe the ground: never a point of view from above
    for text in ("A plain door with red signs, a wall phone, pipes overhead.",      # Real World's PEOC door (6.10)
                 "Firefighters raise the aerial ladder", "the plume goes south-east", "his mission", "Orbits Cafe",
                 "planes overhead"):
        assert RB.seen_from_above({"seen": text}) is None, text
    door = {"title": "The door to the Presidential Emergency Operations Center", "people": "none",
            "seen": "A plain door with red signs, a wall phone, pipes overhead."}
    m = {"model": "mp:test", "people": [], "faces": [], "size": [1000, 1500], "saliency": None}
    assert "aerial" not in RB.fields(door, m, "mp:test")["fields"]
    goes = _recorded("3.7")
    f = RB.fields(goes["item"], goes["measure"], goes["measure"]["model"])
    assert f["fields"]["aerial"] is True and "satellite" in f["why"]["aerial"]


def test_an_aerial_whole_never_sweeps_rising():
    from studio.engine import rulebook as RB
    for size in (L43, L32, PORTRAIT):                         # the fill travels up and down: top to bottom
        place = {"people": False, "class": "place"}
        rising, _ = cam_for(place, size, dur=10.0)
        aerial, _ = cam_for(dict(place, aerial=True), size, dur=10.0)
        assert rising["subject"]["whole_mode"] == aerial["subject"]["whole_mode"] == "sweep"
        r0, r1 = rising["tour"]["stops"][0]["y"], rising["tour"]["stops"][-1]["y"]
        a0, a1 = aerial["tour"]["stops"][0]["y"], aerial["tour"]["stops"][-1]["y"]
        assert r0 > r1 and a0 < a1 and not T.reversals(aerial["tour"])
    wide, _ = cam_for({"people": False, "class": "place", "aerial": True}, WIDE, dur=10.0)
    assert wide["tour"]["stops"][0]["x"] < wide["tour"]["stops"][-1]["x"]             # left to right
    # toward the subject: the next shot's matched subject at the top still ends the sweep at the top
    up, _ = cam_for({"people": False, "class": "place", "aerial": True}, L43, dur=10.0, _end_toward=[0.5, 0.1])
    assert up["tour"]["stops"][-1]["y"] < up["tour"]["stops"][0]["y"]
    # the rulebook supplies it under the human's word; a human aerial: false wins; anything but a bool is malformed
    assert RB.overlay({"people": False}, {"aerial": True})[0]["aerial"] is True
    assert RB.overlay({"people": False, "aerial": False}, {"aerial": True})[0]["aerial"] is False
    assert T.item_schema({"aerial": "yes"})[0] and not T.item_schema({"aerial": True})[0]


def test_a_vl_region_that_is_a_band_or_the_whole_picture_is_never_the_subject():
    from studio.engine import rulebook as RB
    vl = {"regions": [{"kind": "place", "label": "water", "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
                      {"kind": "object", "label": "smoke trail", "x": 0.0, "y": 0.0, "w": 0.95, "h": 0.92},
                      # Real World 3.5's "cloud": the sky band across the picture, 0.75 of it (rulebook 8)
                      {"kind": "object", "label": "smoke cloud", "x": 0.0, "y": 0.028, "w": 1.0, "h": 0.75}]}
    assert RB.VL_MAX_AREA == 0.70
    assert RB.vl_subject("place", vl, {"title": "Smoke over the water"}, ["plume"])[0] is None
    vl["regions"].append({"kind": "object", "label": "smoke", "x": 0.0, "y": 0.0, "w": 1.0, "h": 0.69})
    assert RB.vl_subject("place", vl, {"title": "x"}, ["plume"])[0]["h"] == 0.69      # wide, under the area


def test_car_van_and_vehicle_are_one_word():
    from studio.engine import rulebook as RB
    rec = _recorded("5.7")                     # Real World 5.7: "a police car in the debris"; the VL's "van" is it
    sub, why = RB.vl_subject("object", rec["vl"], rec["item"], rec["cues"])
    assert sub["label"] == "van" and "car" in why
    assert RB.match_words("a smashed car") == RB.match_words("smashed vehicle")


# --------------------------------------------------------------------------
# A48: a whole hold's breath aimed at what must be seen (Real World 3.7, GOES-8)
# --------------------------------------------------------------------------

GOES = (1287, 748)                                           # the 16:9 window is 1287 x 724: rows 0 to 731 never fit
GOES_ITEM = {"people": "none", "class": "document", "whole": True,
             "compose": "centred:a satellite record with its own caption and inset, shown as composed",
             "roi": [{"name": "caption", "kind": "text", "x": 0.12, "y": 0.882, "w": 0.73, "h": 0.096,
                      "source": "human", "must_show": True},
                     {"name": "ny-inset", "kind": "place", "x": 0, "y": 0, "w": 0.21, "h": 0.31,
                      "source": "human", "must_show": True}]}


@pytest.mark.parametrize("preset", [None, "HOLD", "PUSH"])
def test_a_whole_hold_aims_its_breath_so_each_must_show_region_is_whole_at_some_point(preset):
    shot = {"preset": preset} if preset else {}
    cam, s = engine(GOES_ITEM, GOES, dur=8.0, fps=NTSC, **shot)
    assert cam["subject"]["src"] == "whole" and cam["subject"]["whole_mode"] == "hold"
    wins = [w for _, w in R.still_windows(cam, s, GOES, W, H, hz=NTSC)]
    assert T.must_show(wins, GOES_ITEM, GOES) == []                         # each whole at some frame
    fs = all_frames(cam, 8.0, NTSC)
    assert all(f["z"] == pytest.approx(1.0) for f in fs) and not T.reversals(cam["tour"])
    ys = [f["y"] for f in fs]
    assert ys == sorted(ys) and ys[-1] > ys[0]                              # top to bottom: the inset read first
    def whole_in(box, f):
        a0, b0, a1, b1 = T.window(GOES, A, f["z"], f["x"], f["y"])
        return b0 <= box[1] * GOES[1] + 1e-6 and b1 >= (box[1] + box[3]) * GOES[1] - 1e-6
    inset, caption = (0, 0, 0.21, 0.31), (0.12, 0.882, 0.73, 0.096)
    assert whole_in(inset, fs[0]) and whole_in(caption, fs[-1])
    # one breath at most: the drift is under whole_creep_max of the window
    assert (ys[-1] - ys[0]) * GOES[1] <= (M.TOUR["whole_creep_max"] - 1) * T.fill_window(GOES, A)[1] + 1e-6


def test_the_aimed_breath_keeps_the_plain_breath_or_gives_way_to_the_sweep():
    # one window holds them all: the plain breath (one stop, a drift)
    near = dict(GOES_ITEM, roi=[dict(GOES_ITEM["roi"][1], y=0.2)])
    cam, _ = cam_for(near, GOES, dur=8.0)
    assert len(cam["tour"]["stops"]) == 1 and cam["subject"]["whole_mode"] == "hold"
    # regions farther apart than one breath: the hold becomes the (c) sweep end to end
    assert T.aimed_breath(NEAR, A, [(0, 0, 0.2, 0.1), (0, 0.9, 0.2, 1.0)], True) is None
    far = {"people": "none", "class": "place", "whole": True,
           "roi": [{"name": "a", "x": 0, "y": 0, "w": 0.2, "h": 0.1, "source": "human", "must_show": True},
                   {"name": "b", "x": 0, "y": 0.9, "w": 0.2, "h": 0.1, "source": "human", "must_show": True}]}
    cam, _ = cam_for(far, NEAR, dur=8.0)
    assert cam["subject"]["whole_mode"] == "sweep"
    assert T.aimed_breath(GOES, A, [(0, 0, 0.2, 0.99)], True) is None      # a region taller than the window


# --------------------------------------------------------------------------
# A49 (cinematography ticket #4, reviewer's re-review): the engine never
# refuses itself for subject-under-text, and a steer that only ducks a
# refusal while still warning has moved the wrong way: it must minimise the
# overlap, taking a pose under the lint's own warn share when one exists.
# The reviewer's own probe: a "caption" must_show box (x 0.05, y 0.758,
# w 0.336, h 0.071) on FX-STILL-A (1500 x 1050), under a lower third widened
# to cover the whole shot. A written path is the one case that still blocks
# (render.a49_tour_lints); every engine path (HOLD, PUSH, declared
# whole: true, the plain default) must plan without a Refused, keep the
# region whole in frame (A7/A41, never traded for clearing it of text), and
# read under 10% overlap on every frame the text is up (this geometry has
# room: the fill window can travel about 0.40 of the picture vertically).
# --------------------------------------------------------------------------

CAPTION_SIZE = (1500, 1050)                             # make_media.STILLS["FX-STILL-A"]
CAPTION_BOX = {"x": 0.05, "y": 0.758, "w": 0.336, "h": 0.071, "name": "caption", "must_show": True, "kind": "place"}
LT_OVER_WHOLE_SHOT = {"zone": "LT", "id": "T-fixture", "box": M.ZONES["LT"], "t0": 0.0, "t1": 4.0}


def _engine_text_cam(item, size, dur, preset):
    s = dict({"id": "X", "kind": "archive_still", "_dur": dur, "start_s": 0.0, "_item": item, "preset": preset})
    must_show = T.must_show_regions(item)
    avoid = [(T.roi_box(r), LT_OVER_WHOLE_SHOT["box"]) for r in must_show]
    cam = R.still_camera(s, size, W, H, words=[], fps=24.0, avoid=avoid)
    cam = R.engine_cover(s, cam, size, W, H, [], None, fps=24.0, avoid=avoid, text_spans=[LT_OVER_WHOLE_SHOT])
    return cam, s, must_show


def _caption_overlap(cam, s, size, must_show):
    """(whole_in_frame, max_overlap) for the first must_show region, or
    (False, 1.0) when there is no tour at all to measure."""
    tl = cam.get("tour")
    if not tl or not must_show:
        return False, 1.0
    wins = TL.frame_windows(tl, 24.0)
    box = T.roi_box(must_show[0])
    whole = not T.must_show([w for _, w in wins], s["_item"], size)
    res = TL.subject_under_text(wins, box, size, text_spans=[LT_OVER_WHOLE_SHOT], must_show=True)
    return whole, res["max_overlap"]


@pytest.mark.parametrize("label,preset,declare_whole", [
    ("HOLD", "HOLD", False), ("PUSH", "PUSH", False), ("whole-true", "HOLD", True), ("default", None, False),
])
def test_an_engine_path_is_never_refused_for_a_must_show_box_under_a_lower_third(label, preset, declare_whole):
    item = {"people": False, "class": "place", "roi": [dict(CAPTION_BOX)]}
    if declare_whole:
        item["whole"] = True
    cam, s, must_show = _engine_text_cam(item, CAPTION_SIZE, 4.0, preset)
    assert cam.get("tour") is not None                   # the engine always has somewhere to go (ruling 2)
    whole, overlap = _caption_overlap(cam, s, CAPTION_SIZE, must_show)
    assert whole                                          # A7/A41: never traded away for clearing the text
    assert overlap < M.CINE["under_text_share"]           # a clear pose exists here: the steer must find it


@pytest.mark.parametrize("seed", range(40))
def test_property_an_engine_path_with_a_must_show_box_under_text_is_never_refused(seed):
    rng = random.Random(seed)
    size = rng.choice([GOES, L43, L32, NEAR, (1920, 1080), (1000, 750)])
    w, h = rng.uniform(0.03, 0.4), rng.uniform(0.02, 0.25)
    must_show = {"name": "caption", "x": rng.uniform(0, 1 - w), "y": rng.uniform(0, 1 - h), "w": w, "h": h,
                "must_show": True, "kind": rng.choice(["place", "text", "object"]), "source": "human"}
    item = {"people": "none", "class": rng.choice(["document", "place", "object"]), "roi": [must_show]}
    if rng.random() < 0.3:
        item["whole"] = True
    preset = rng.choice([None, "HOLD", "PUSH", "PULL", "DRIFT", "TILT", "FILL"])
    dur = rng.uniform(2.5, 20.0)
    zone_name, zone_box = rng.choice([("LT", M.ZONES["LT"]), ("SUB", M.ZONES["SUB"])])
    span = {"zone": zone_name, "id": "cue-1", "box": zone_box, "t0": 0.0, "t1": dur}   # up for the whole shot: worst case
    s = dict({"id": "X", "kind": "archive_still", "_dur": dur, "start_s": 0.0, "_item": item, "preset": preset})
    avoid = [(T.roi_box(must_show), zone_box)]
    cam = R.still_camera(s, size, W, H, words=[], fps=24.0, avoid=avoid)           # must not raise
    cam = R.engine_cover(s, cam, size, W, H, [], None, fps=24.0, avoid=avoid, text_spans=[span])  # never refuses
    sub = cam.get("subject") or {}
    if sub.get("avoid_clear") is True:
        # the engine's own signal that it cleared the box at the warn share: the measured overlap must agree
        tl = cam.get("tour")
        if tl is not None:
            wins = TL.frame_windows(tl, 24.0)
            r = TL.subject_under_text(wins, T.roi_box(must_show), size, text_spans=[span], must_show=True)
            assert r["max_overlap"] < M.CINE["under_text_share"]
