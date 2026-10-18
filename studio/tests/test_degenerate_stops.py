"""A49 refined: degenerate stops. Two consecutive stops closer than the settle minimum (1.0 s) whose windows
are near-equal (centres within 0.5% of the frame, depths within 1%) read as a hitch or a micro-settle (Real
World 5.9ba: the near end stopped on twice, 0.1 s apart). The engine merges its own pairs where every truth
guarantee holds (people seen, the whole shown, must_show seen); a written ``camera`` pair is never merged,
and ``degenerate-stops`` (guidance) names any pair left on a path."""

import json
import shutil

import pytest

from studio.engine import journal as J
from studio.engine import render as R
from studio.engine import tour as T
from studio.engine import tourlint as TL
from conftest import make_film

SIZE = (1200.0, 1800.0)        # a tall picture: the A47 pass sweeps its long axis (y)
ASPECT = 16 / 9
DUR = 18.0
FAR = T.settle({"z": 1.0, "x": 0.5, "y": 0.0}, SIZE, ASPECT)["y"]       # the window at the top of the picture
NEAR = T.settle({"z": 1.0, "x": 0.5, "y": 1.0}, SIZE, ASPECT)["y"]      # and at its bottom
WIN_H = 1200.0 / ASPECT / 1800.0                                       # the fill window's height, picture fractions


def eng(t, y, z=1.0, x=0.5, frm="A47: the near end", **kw):
    return {"t": t, "z": z, "x": x, "y": y, "from": frm, "placed": "engine", **kw}


def hocking(gap=0.1):
    """5.9ba as planned: the far end (held 1 s), the near end at 4.508 and again ``gap`` later, the subject."""
    return [eng(0.0, FAR, frm="A47: the far end", hold=1.0), eng(4.508, NEAR), eng(4.508 + gap, NEAR),
            eng(6.233, 0.6, z=1.0442, x=0.5212, frm="A47: the subject (subject)")]


# --------------------------------------------------------------------------
# The lint: a failing and a passing fixture
# --------------------------------------------------------------------------


def test_degenerate_stops_flags_the_hocking_pair():
    tl = T.build(hocking(), DUR, SIZE, ASPECT, 2.0)
    r = TL.degenerate_stops(tl)
    assert not r["ok"] and len(r["pairs"]) == 1
    p = r["pairs"][0]
    assert p["t"] == [4.508, 4.608] and p["dt"] == 0.1 and p["authored"] is False


@pytest.mark.parametrize("stops", [
    hocking(gap=1.2),                                                   # a settle apart: two stops, read as such
    [eng(0.0, 0.375, hold=1.0), eng(4.5, 0.625), eng(4.6, 0.64)],       # 0.1 s apart, but a new window (1.5% of the frame)
    [eng(0.0, 0.375, hold=1.0), eng(4.5, 0.625), eng(4.6, 0.625, z=1.03)],   # a 3% push: a new depth
])
def test_degenerate_stops_passes_distinct_or_settled_stops(stops):
    assert TL.degenerate_stops(T.build(stops, DUR, SIZE, ASPECT, 2.0))["ok"]


def test_near_equal_reads_the_frame_not_the_picture():
    a = eng(0.0, 0.5)
    assert T.near_equal(a, dict(a, y=0.5 + 0.004 * WIN_H), SIZE, ASPECT)    # 0.4% of the frame's height
    assert not T.near_equal(a, dict(a, y=0.5 + 0.006 * WIN_H), SIZE, ASPECT)
    assert T.near_equal(a, dict(a, z=1.009), SIZE, ASPECT) and not T.near_equal(a, dict(a, z=1.02), SIZE, ASPECT)


def test_check_still_names_the_lint():
    tl = T.build(hocking(), DUR, SIZE, ASPECT, 2.0)
    row = TL.check_still({"id": "5.9ba"}, {"tour": tl}, SIZE, fps=30000 / 1001)
    assert "degenerate-stops" in row["warnings"] and row["blocks"] == []


# --------------------------------------------------------------------------
# The merge
# --------------------------------------------------------------------------


def test_the_engine_pair_merges_to_the_earlier_stop_with_no_micro_hold():
    out, merged = T.merge_degenerate(hocking(), SIZE, ASPECT)
    assert [s["t"] for s in out] == [0.0, 4.508, 6.233]
    assert merged == [{"t": [4.508, 4.608], "kept": 4.508, "dropped": "A47: the near end", "why": "the earlier"}]
    tl = T.build(out, DUR, SIZE, ASPECT, 2.0)
    # no 0.1 s hold between legs; A54: the opening creeps along the first leg (never from rest)
    assert [g["kind"] for g in tl["segments"]][:3] == ["creep", "move", "move"]
    assert TL.degenerate_stops(tl)["ok"]


def test_a_subject_arrival_keeps_its_own_time():
    stops = [eng(0.0, 0.375, hold=1.0), eng(5.0, 0.625), eng(5.4, 0.626, frm="A47: the subject (subject)")]
    out, merged = T.merge_degenerate(stops, SIZE, ASPECT)
    assert [s["t"] for s in out] == [0.0, 5.4] and out[-1]["from"] == "A47: the subject (subject)"
    assert merged[0]["why"] == "the subject's arrival"


def test_a_real_hold_on_the_dropped_stop_is_kept():
    stops = [eng(0.0, 0.375, hold=1.0), eng(4.0, 0.625), eng(4.5, 0.625, hold=2.0), eng(9.0, 0.4)]
    out, _ = T.merge_degenerate(stops, SIZE, ASPECT)
    assert [s["t"] for s in out] == [0.0, 4.0, 9.0] and out[1]["hold"] == pytest.approx(2.5)


def test_a_written_pair_is_never_merged_only_linted():
    stops = [dict(s, placed="author") for s in hocking()]
    out, merged = T.merge_degenerate(stops, SIZE, ASPECT)
    assert out == stops and merged == []
    assert TL.degenerate_stops(T.build(stops, DUR, SIZE, ASPECT, 2.0))["pairs"][0]["authored"] is True


def test_a_merge_that_would_lose_a_truth_guarantee_is_refused():
    """5.3's shape: the near end twice, then the subject 0.055 s later and a hair off the near end. The first
    pair merges; folding the near end into the subject would leave a strip of the picture never shown (A7),
    so that pair stays, for the lint."""
    stops = [eng(0.0, FAR, frm="A47: the far end", hold=1.0), eng(6.845, NEAR), eng(6.945, NEAR),
             eng(7.0, NEAR - 0.001, z=1.0018, x=0.5009, frm="A47: the subject (subject)")]
    shot = {"id": "5.3", "kind": "archive_still"}
    out, merged = R.degenerate_merge(stops, shot, {}, 8.0, SIZE, ASPECT, 2.0, no_zoom=False, hz=30000 / 1001)
    assert [s["t"] for s in out] == [0.0, 6.845, 7.0] and len(merged) == 1
    w = T.windows_of(T.build(out, 8.0, SIZE, ASPECT, 2.0), 30000 / 1001)
    assert T.people_check(w, T.people_of({}), SIZE)["whole_shown"]
    left = TL.degenerate_stops(T.build(out, 8.0, SIZE, ASPECT, 2.0))
    assert not left["ok"] and left["pairs"][0]["t"] == [6.845, 7.0]


def test_the_hocking_merge_keeps_the_whole_shown():
    shot = {"id": "5.9ba", "kind": "archive_still"}
    out, merged = R.degenerate_merge(hocking(), shot, {}, DUR, SIZE, ASPECT, 2.0, no_zoom=False, hz=30000 / 1001)
    assert [s["t"] for s in out] == [0.0, 4.508, 6.233] and len(merged) == 1
    w = T.windows_of(T.build(out, DUR, SIZE, ASPECT, 2.0), 30000 / 1001)
    assert T.people_check(w, T.people_of({}), SIZE)["whole_shown"]


# --------------------------------------------------------------------------
# Live in build_plan: a written pair warns, the plan goes on
# --------------------------------------------------------------------------


def _shot(play, sid):
    return next(s for p in play["parts"] for s in p["shots"] if s["id"] == sid)


def test_plan_warns_a_written_degenerate_pair(tmp_path):
    film = make_film(tmp_path / "fixture")
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    _shot(play, "S3").update(preset=None, camera=[{"t": 0.0, "z": 1.0, "x": 0.5, "y": 0.5, "hold": 1.0},
                                                  {"t": 2.0, "z": 1.05, "x": 0.5, "y": 0.5},
                                                  {"t": 2.3, "z": 1.05, "x": 0.5, "y": 0.5}])
    (film / "screenplay.json").write_text(json.dumps(play), encoding="utf-8")
    j = J.Journal(film="degenerate-written")
    R.build_plan(film, W=640, H=360, burn_subtitles=False, journal=j)
    lint = [e for e in J.read(j.path) if e["kind"] == "lint" and e.get("rule") == "degenerate-stops"]
    assert len(lint) == 1 and lint[0]["unit"] == "S3" and lint[0]["severity"] == "warn"
    assert lint[0]["evidence"]["pairs"][0]["authored"] is True
