"""Cinematography ticket #9 (GRAMMAR A53, doctrine 2.9's "three joints"):
``dissolve: true`` is honoured with the existing dissolve machinery
(``motion.dissolve_weight``, ``render.compose``'s blend), the incoming
shot's subject matches the outgoing shot's last subject screen position
the same way a cut's ``match: "prev"`` already did (A47), and the guidance
lint ``dissolve-rule`` says when a dissolve does not keep one subject.
Pure geometry and the tiny fixture film; nothing is rendered and no real
film is read."""

import math

import pytest

from studio.engine import journal as J
from studio.engine import motion as M
from studio.engine import render as R
from studio.engine import tourlint as TL
from conftest import make_film
from test_cine2_subject import cam_for, subject, L43, W, H
from test_render import _edit_play, _plan, _shot

CINE = M.CINE


# --------------------------------------------------------------------------
# `dissolve: true` shorthand: transition_in and match, filled or respected
# --------------------------------------------------------------------------


def test_dissolve_true_fills_transition_in_and_implies_match(tmp_path):
    film = make_film(tmp_path / "film")

    def edit(play):
        s8 = _shot(play, "S8")
        s8.pop("transition_in", None)                             # no stale type to conflict with the shorthand
        s8["dissolve"] = True
        s8["start_s"] -= CINE["dissolve_default_s"]              # the overlap shortens the timeline (7.3)
        _shot(play, "S9")["start_s"] -= CINE["dissolve_default_s"]

    _edit_play(film, edit)
    plan, _ = _plan(film, "dissolve-shorthand")
    s8 = next(s for s in plan["shots"] if s["id"] == "S8")
    assert s8["transition_in"] == {"type": "dissolve", "s": CINE["dissolve_default_s"]}
    assert s8["transition_in"]["s"] == pytest.approx(0.9)
    assert 0.75 <= s8["transition_in"]["s"] <= 1.0                # doctrine 2.9's house range
    assert s8["match"] == "prev"


def test_dissolve_true_respects_an_existing_duration_and_match(tmp_path):
    film = make_film(tmp_path / "film")

    def edit(play):
        s8 = _shot(play, "S8")
        s8["dissolve"] = True
        s8["transition_in"] = {"s": 0.8}                          # no type: the shorthand fills it in
        s8["match"] = "prev"                                      # already asked: the shorthand never overrides it
        s8["start_s"] -= 0.8
        _shot(play, "S9")["start_s"] -= 0.8

    _edit_play(film, edit)
    plan, _ = _plan(film, "dissolve-shorthand-s")
    s8 = next(s for s in plan["shots"] if s["id"] == "S8")
    assert s8["transition_in"] == {"type": "dissolve", "s": 0.8}
    assert s8["match"] == "prev"


def test_dissolve_true_conflicts_with_a_different_transition_type(tmp_path):
    film = make_film(tmp_path / "film")

    def edit(play):
        s8 = _shot(play, "S8")
        s8["dissolve"] = True
        s8["transition_in"] = {"type": "dip", "s": 0.5}           # a contradiction: refused, never silently picked

    _edit_play(film, edit)
    with pytest.raises(R.Refused, match=r"dissolve-flag-conflict"):
        _plan(film, "dissolve-conflict")


# --------------------------------------------------------------------------
# Position match across a dissolve (A47, A53): the incoming shot's subject
# opens where the outgoing shot left its own on the screen
# --------------------------------------------------------------------------


def test_match_prev_matches_across_a_dissolve_the_same_as_a_cut(tmp_path):
    prev_item = {"people": False, "roi": [subject(0.1, 0.1, 0.2, 0.2)]}
    prev, ps = cam_for(prev_item, L43, id="P")
    ps["_cam"] = prev
    screen = prev["subject"]["screen"]
    j = J.Journal(film="x", kind="test", out_dir=tmp_path, directory=tmp_path)
    s = {"id": "X", "kind": "archive_still", "_dur": 8.0, "start_s": 0.0, "match": "prev",
         "transition_in": {"type": "dissolve", "s": 0.9}, "_item": {"people": False, "roi": [subject(0.5, 0.4, 0.2, 0.2)]}}
    R.match_prev(j, s, ps)
    assert s["_match_screen"] == screen
    cam = R.still_camera(s, L43, W, H, words=[])
    tl = cam["tour"]
    got = T_screen(tl, screen_point=(0.6, 0.5))
    assert math.hypot(got[0] - screen[0], got[1] - screen[1]) == pytest.approx(cam["subject"]["match_error"], abs=1e-3)
    assert cam["subject"]["match_error"] < 0.05                  # matched within doctrine 2.9's ~5%
    assert tl["stops"][0].get("match") == "prev"                 # during the overlap the two subjects share a place
    warn = [e for e in J.read(j.path) if e["kind"] == "lint" and e.get("rule") == "cine-match"]
    assert [e["status"] for e in warn] == ["pass"]


def T_screen(tl, *, screen_point):
    from studio.engine import tour as T
    return T.screen_of(tl, screen_point, t=0.0)


def test_min_move_after_cut_is_waived_across_a_dissolve():
    cam = {"tour": {"stops": [{"match": None}]}}
    s_cut = {"transition_in": {"type": "cut"}}
    s_dis = {"transition_in": {"type": "dissolve", "s": 0.9}}
    assert TL.continues_across_cut(cam, s_cut) is False
    assert TL.continues_across_cut(cam, s_dis) is True            # #4/#61's own exemption recognises A53's joint


# --------------------------------------------------------------------------
# dissolve-rule (guidance): same subject, same mark class, one continuous
# reading, matched position; and the film-level budget
# --------------------------------------------------------------------------


def _pair(**over):
    # the outgoing shot ends at 8.0, the incoming starts at 7.1: the dissolve's own 0.9 s overlap (doctrine 2.9),
    # so a check against the join window [7.1, 8.0] has a real span to test, not a single point
    prev = dict({"id": "P", "mark": "ARCHIVE", "start_s": 0.0, "end_s": 8.0,
                 "_item": {"class": "place"}, "_cam": {"subject": {"kind": "place", "box": None}}})
    s = dict({"id": "S", "mark": "ARCHIVE", "start_s": 7.1, "end_s": 13.1,
              "_item": {"class": "place"}, "_cam": {"subject": {"kind": "place", "box": None}}})
    prev.update(over.pop("prev", {}))
    s.update(over.pop("s", {}))
    return prev, s


SPANNING_LINE = [{"start": 6.0, "dur": 4.0}]          # 6.0 to 10.0 covers the pair's join window, [7.1, 8.0]


def test_dissolve_join_passes_a_clean_same_subject_dissolve():
    prev, s = _pair()
    assert TL.dissolve_join(prev, s, SPANNING_LINE) == {"ok": True, "reasons": []}


def test_dissolve_join_warns_on_a_mark_class_mismatch():
    prev, s = _pair(s={"mark": "RECONSTRUCTED"})
    r = TL.dissolve_join(prev, s, SPANNING_LINE)
    assert not r["ok"] and any("mark class differs" in x for x in r["reasons"])


def test_dissolve_join_warns_on_a_picture_class_mismatch():
    prev, s = _pair(s={"_item": {"class": "document"}, "_cam": {"subject": {"kind": "document", "box": None}}})
    r = TL.dissolve_join(prev, s, SPANNING_LINE)
    assert not r["ok"] and any("picture class differs" in x for x in r["reasons"])


def test_dissolve_join_warns_when_the_named_subject_differs():
    box_a, box_b = (0.1, 0.1, 0.3, 0.3), (0.5, 0.5, 0.7, 0.7)
    prev, s = _pair(
        prev={"_item": {"class": "person", "roi": [{"name": "Nurse Reed", "x": box_a[0], "y": box_a[1],
                                                     "w": 0.2, "h": 0.2}]},
              "_cam": {"subject": {"kind": "person", "box": box_a}}},
        s={"_item": {"class": "person", "roi": [{"name": "Dr. Alam", "x": box_b[0], "y": box_b[1],
                                                 "w": 0.2, "h": 0.2}]},
           "_cam": {"subject": {"kind": "person", "box": box_b}}})
    r = TL.dissolve_join(prev, s, SPANNING_LINE)
    assert not r["ok"] and any("subject differs" in x for x in r["reasons"])


def test_dissolve_join_warns_when_no_line_spans_the_join():
    prev, s = _pair()
    lines_missing = [{"start": 0.0, "dur": 2.0}]                  # ends long before the join window [7.1, 8.0]
    assert not TL.dissolve_join(prev, s, lines_missing)["ok"]
    assert TL.dissolve_join(prev, s, SPANNING_LINE)["ok"]


def test_dissolve_join_warns_on_a_position_mismatch_past_the_tolerance():
    prev, s = _pair(s={"_cam": {"subject": {"kind": "place", "box": None, "match_error": 0.2}}})
    r = TL.dissolve_join(prev, s, SPANNING_LINE)
    assert not r["ok"] and any("subject position differs" in x for x in r["reasons"])
    prev2, s2 = _pair(s={"_cam": {"subject": {"kind": "place", "box": None, "match_error": 0.01}}})
    assert TL.dissolve_join(prev2, s2, SPANNING_LINE)["ok"]


def test_dissolve_budget_warns_past_about_one_per_three_minutes():
    def shots_with(n, total_s):
        out = [{"end_s": total_s, "transition_in": {"type": "dissolve"}} for _ in range(n)]
        out[-1] = dict(out[-1])
        return out

    ok = shots_with(1, 200.0)                                     # 1 in 200 s, budget ceil(200/180) = 2
    assert TL.dissolve_budget(ok)["ok"]
    over = shots_with(3, 200.0)                                   # 3 in 200 s, budget 2: over
    bud = TL.dissolve_budget(over)
    assert not bud["ok"] and bud["count"] == 3 and bud["budget"] == 2
    assert TL.dissolve_budget([])["ok"]                           # no shots, no dissolves: trivially fine


def test_dissolve_rule_lints_journals_a_warning_with_reasons_and_the_film_budget(tmp_path):
    prev, s = _pair(s={"mark": "RECONSTRUCTED", "transition_in": {"type": "dissolve", "s": 0.9}})
    j = J.Journal(film="x", kind="test", out_dir=tmp_path, directory=tmp_path)
    R.dissolve_rule_lints(j, [prev, s], [])
    evs = J.read(j.path)
    pair = [e for e in evs if e["rule"] == "dissolve-rule" and e["unit"] == "S"]
    assert len(pair) == 1 and pair[0]["status"] == "fail" and pair[0]["severity"] == "warn"
    assert any("mark class differs" in r for r in pair[0]["evidence"]["reasons"])
    film_row = [e for e in evs if e["rule"] == "dissolve-rule" and e["unit"] == "film"]
    assert len(film_row) == 1 and film_row[0]["status"] == "pass"       # one dissolve in 13 s: well inside budget


def test_dissolve_rule_lints_journals_a_pass_for_a_clean_join(tmp_path):
    prev, s = _pair(s={"transition_in": {"type": "dissolve", "s": 0.9}})
    j = J.Journal(film="x", kind="test", out_dir=tmp_path, directory=tmp_path)
    R.dissolve_rule_lints(j, [prev, s], SPANNING_LINE)
    pair = [e for e in J.read(j.path) if e["rule"] == "dissolve-rule" and e["unit"] == "S"]
    assert len(pair) == 1 and pair[0]["status"] == "pass"
