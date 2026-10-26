"""Cinematography ticket #4: the tour lint module (GRAMMAR A49). Pure
geometry on small synthetic sizes and hand-built ``tl``/verdict fixtures;
nothing is rendered and no film is read. One integration test per the
engine's own ``cam``/``tl`` builders (the pattern ``test_cine2_subject.py``
uses), so the module is proven against the real shapes ``render.py``
passes it, not only against hand-built dicts."""

import json
import math
import shutil

import pytest

from studio.engine import journal as J
from studio.engine import motion as M
from studio.engine import render as R
from studio.engine import tour as T
from studio.engine import tourlint as TL
from conftest import make_film

W, H = 1920, 1080
# a wide picture (2:1): at z = 1 the fill window already has horizontal room to pan (unlike a square or 16:9
# picture, where z = 1's fill window spans the whole width and panning needs a push first)
SIZE = (2000.0, 1000.0)
ASPECT = 16 / 9


def make_tl(segments, *, size=SIZE, aspect=ASPECT, stops=None, dur=None):
    stops = stops if stops is not None else ([dict(t=segments[0]["t0"], **segments[0]["a"])] +
                                              [dict(t=g["t1"], **g["b"]) for g in segments])
    dur = dur if dur is not None else segments[-1]["t1"]
    return {"segments": segments, "stops": stops, "dur": dur, "size": list(size), "aspect": aspect,
            "z_max": max(g["a"]["z"] for g in segments), "z_min": min(g["a"]["z"] for g in segments),
            "held": [], "zmax_allowed": 3.0}


# --------------------------------------------------------------------------
# pan-speed-px
# --------------------------------------------------------------------------


def test_pan_speed_px_passes_a_slow_pan():
    # a whole-shot pan, left to right, over 20 s: well under the 7-second rule at 24p
    seg = {"t0": 0.0, "t1": 20.0, "kind": "move", "a": {"z": 1.0, "x": 0.1, "y": 0.5},
           "b": {"z": 1.0, "x": 0.9, "y": 0.5}}
    tl = make_tl([seg])
    r = TL.pan_speed_px(tl, 24.0, W=W, H=H)
    assert r["ok"] and r["max_h_px"] <= r["guide_h_px"]


def test_pan_speed_px_fails_a_fast_pan():
    # the same travel in 1 s: far faster than a 7 s crossing
    seg = {"t0": 0.0, "t1": 1.0, "kind": "move", "a": {"z": 1.0, "x": 0.1, "y": 0.5},
           "b": {"z": 1.0, "x": 0.9, "y": 0.5}}
    tl = make_tl([seg])
    r = TL.pan_speed_px(tl, 24.0, W=W, H=H)
    assert not r["ok"] and r["max_h_px"] > r["guide_h_px"]


def test_pan_speed_px_guide_derives_from_fps():
    # at 29.97 the guide is 9/5, not 11/6 (derived from the plan's own fps, doctrine 8)
    seg = {"t0": 0.0, "t1": 20.0, "kind": "move", "a": {"z": 1.0, "x": 0.1, "y": 0.5},
           "b": {"z": 1.0, "x": 0.9, "y": 0.5}}
    tl = make_tl([seg])
    r24 = TL.pan_speed_px(tl, 24.0, W=W, H=H)
    r2997 = TL.pan_speed_px(tl, 30000 / 1001, W=W, H=H)
    assert r2997["guide_h_px"] < r24["guide_h_px"]
    assert r24["guide_h_px"] == pytest.approx(W / (7.0 * 24.0), rel=1e-3)
    assert r2997["guide_h_px"] == pytest.approx(W / (7.0 * 30000 / 1001), rel=1e-3)


# --------------------------------------------------------------------------
# zoom-speed
# --------------------------------------------------------------------------


def test_zoom_speed_cruise_passes_a_slow_push():
    seg = {"t0": 0.0, "t1": 20.0, "kind": "move", "a": {"z": 1.0, "x": 0.5, "y": 0.5},
           "b": {"z": 1.5, "x": 0.5, "y": 0.5}}
    tl = make_tl([seg])
    r = TL.zoom_speed_cruise(tl, 24.0)
    assert r["ok"]


def test_zoom_speed_cruise_fails_a_fast_push():
    seg = {"t0": 0.0, "t1": 1.0, "kind": "move", "a": {"z": 1.0, "x": 0.5, "y": 0.5},
           "b": {"z": 1.5, "x": 0.5, "y": 0.5}}
    tl = make_tl([seg])
    r = TL.zoom_speed_cruise(tl, 24.0)
    assert not r["ok"] and r["zoom_per_s"] > r["guide"]


# --------------------------------------------------------------------------
# settle-before-move
# --------------------------------------------------------------------------


def test_settle_before_move_passes_a_full_second():
    segs = [{"t0": 0.0, "t1": 1.0, "kind": "hold", "a": {"z": 1.0, "x": 0.3, "y": 0.5},
             "b": {"z": 1.0, "x": 0.3, "y": 0.5}},
            {"t0": 1.0, "t1": 3.0, "kind": "move", "a": {"z": 1.0, "x": 0.3, "y": 0.5},
             "b": {"z": 1.0, "x": 0.7, "y": 0.5}}]
    tl = make_tl(segs)
    assert TL.settle_before_move(tl) == []


def test_settle_before_move_fails_a_short_stop():
    segs = [{"t0": 0.0, "t1": 0.4, "kind": "hold", "a": {"z": 1.0, "x": 0.3, "y": 0.5},
             "b": {"z": 1.0, "x": 0.3, "y": 0.5}},
            {"t0": 0.4, "t1": 2.0, "kind": "move", "a": {"z": 1.0, "x": 0.3, "y": 0.5},
             "b": {"z": 1.0, "x": 0.7, "y": 0.5}}]
    tl = make_tl(segs)
    bad = TL.settle_before_move(tl)
    assert len(bad) == 1 and bad[0]["settle_s"] == pytest.approx(0.4) and bad[0]["required_s"] == 1.0


def test_settle_before_move_requires_1_5s_for_a_face():
    segs = [{"t0": 0.0, "t1": 1.2, "kind": "hold", "a": {"z": 1.2, "x": 0.3, "y": 0.4},
             "b": {"z": 1.2, "x": 0.3, "y": 0.4}},
            {"t0": 1.2, "t1": 3.0, "kind": "move", "a": {"z": 1.2, "x": 0.3, "y": 0.4},
             "b": {"z": 1.0, "x": 0.7, "y": 0.5}}]
    tl = make_tl(segs)
    bad = TL.settle_before_move(tl, kinds={0.0: "face"})
    assert len(bad) == 1 and bad[0]["required_s"] == 1.5 and bad[0]["kind"] == "face"
    ok = TL.settle_before_move(tl, kinds={})            # unknown kind: the plain 1.0 s floor passes at 1.2 s
    assert ok == []


# --------------------------------------------------------------------------
# min-move-after-cut
# --------------------------------------------------------------------------


def test_never_from_rest_warns_on_a_dead_opening_hold():
    # A54: min-move-after-cut is now "never from rest": an opening that sits still warns
    segs = [{"t0": 0.0, "t1": 0.6, "kind": "hold", "a": {"z": 1.0, "x": 0.1, "y": 0.5},
             "b": {"z": 1.0, "x": 0.1, "y": 0.5}},
            {"t0": 0.6, "t1": 4.0, "kind": "move", "a": {"z": 1.0, "x": 0.1, "y": 0.5},
             "b": {"z": 1.0, "x": 0.9, "y": 0.5}}]
    r = TL.min_move_after_cut(make_tl(segs))
    assert not r["ok"] and r["from_rest"] and r["rule"] == "never from rest"


def test_never_from_rest_warns_on_a_move_eased_from_zero():
    segs = [{"t0": 0.0, "t1": 4.0, "kind": "move", "a": {"z": 1.0, "x": 0.1, "y": 0.5},
             "b": {"z": 1.0, "x": 0.9, "y": 0.5}}]
    assert not TL.min_move_after_cut(make_tl(segs))["ok"]          # no v0: the rostrum's own ease from rest


def test_never_from_rest_passes_a_move_entered_at_the_creep():
    segs = [{"t0": 0.0, "t1": 4.0, "kind": "move", "a": {"z": 1.0, "x": 0.1, "y": 0.5},
             "b": {"z": 1.0, "x": 0.9, "y": 0.5}}]
    M.enter_moving(segs, lambda a, b: (abs(b["x"] - a["x"]), 0.0))
    r = TL.min_move_after_cut(make_tl(segs))
    assert r["ok"] and segs[0]["v0"] > 0


def test_min_move_after_cut_waived_when_the_move_continues():
    segs = [{"t0": 0.0, "t1": 4.0, "kind": "move", "a": {"z": 1.0, "x": 0.1, "y": 0.5},
             "b": {"z": 1.0, "x": 0.9, "y": 0.5}}]
    tl = make_tl(segs)
    assert TL.min_move_after_cut(tl, continues_across_cut=True)["ok"]


# --------------------------------------------------------------------------
# end-pose-composition (Ratio's borderline logic)
# --------------------------------------------------------------------------


def test_end_pose_composition_golden_is_not_borderline_at_the_middle_of_its_band():
    v = {"room_x": True, "room_y": False, "subject_x": 0.37, "verdict": "golden"}  # middle of 0.30-0.44
    out = TL.end_pose_composition(v)
    assert out["verdict"] == "golden" and not out["borderline"] and out["borderline_axes"] == []


def test_end_pose_composition_flags_borderline_near_a_band_edge_and_never_flips():
    # 0.445: just past the golden band's 0.44 edge (into "halves"), but within half a bin (0.01) of it
    v = {"room_x": True, "room_y": False, "subject_x": 0.445, "verdict": "centred (too large for phi)"}
    out = TL.end_pose_composition(v)
    assert out["borderline"] and out["borderline_axes"] == ["x"]
    assert out["verdict"] == "centred (too large for phi)"          # never flipped to "golden"


def test_end_pose_composition_ignores_an_axis_with_no_room():
    v = {"room_x": False, "room_y": True, "subject_x": 0.441, "subject_y": 0.5, "verdict": "whole"}
    out = TL.end_pose_composition(v)
    assert out["borderline_axes"] == []                             # x has no room: never checked


# --------------------------------------------------------------------------
# lead-room
# --------------------------------------------------------------------------


def test_lead_room_passes_when_ahead_covers_behind():
    v = {"lead_room": 0.6, "room_behind": 0.4, "lead_ok": True}
    r = TL.lead_room_check(v)
    assert r["applies"] and r["ok"] and r["ratio"] == pytest.approx(1.5)


def test_lead_room_fails_when_behind_is_larger():
    v = {"lead_room": 0.2, "room_behind": 0.5, "lead_ok": False}
    r = TL.lead_room_check(v)
    assert r["applies"] and not r["ok"]


def test_lead_room_does_not_apply_with_no_facing():
    assert TL.lead_room_check({"verdict": "whole"}) == {"ok": True, "applies": False}


# --------------------------------------------------------------------------
# subject-under-text
# --------------------------------------------------------------------------


FULL_WIN = (0.0, 0.0, 1000.0, 1000.0)
SPAN = [{"zone": "lt", "box": (0.0, 0.85, 0.5, 1.0), "t0": 0.0, "t1": 5.0}]


def test_subject_under_text_passes_a_subject_clear_of_the_zone():
    wins = [(1.0, FULL_WIN)]
    r = TL.subject_under_text(wins, (0.1, 0.1, 0.3, 0.3), SIZE, text_spans=SPAN)
    assert r["ok"] and not r["block"] and r["max_overlap"] == 0.0


def test_subject_under_text_warns_past_10_percent_overlap():
    # a subject box a third of it inside the lt zone
    wins = [(1.0, FULL_WIN)]
    box = (0.0, 0.8, 0.3, 0.9)                 # overlaps y 0.85-0.9 of its own 0.8-0.9 span: half the box
    r = TL.subject_under_text(wins, box, SIZE, text_spans=SPAN)
    assert not r["ok"] and not r["block"] and r["max_overlap"] >= 0.10


def test_subject_under_text_blocks_a_covered_must_show_region():
    wins = [(1.0, FULL_WIN)]
    box = (0.05, 0.9, 0.2, 0.98)                # wholly inside the lt zone while it is up
    r = TL.subject_under_text(wins, box, SIZE, text_spans=SPAN, must_show=True)
    assert r["block"] and r["max_overlap"] == pytest.approx(1.0)


def test_subject_under_text_checks_a_face_at_any_overlap():
    # A51 (faces never) replaces A49's "a face is never checked": a face under a live lower third reads at any
    # overlap, and a must_show face blocks there (test_cine_faces_subject.py has the rest)
    wins = [(1.0, FULL_WIN)]
    box = (0.05, 0.9, 0.2, 0.98)
    r = TL.subject_under_text(wins, box, SIZE, text_spans=SPAN, is_face=True)
    assert not r["ok"] and not r["block"]
    r = TL.subject_under_text(wins, box, SIZE, text_spans=SPAN, must_show=True, is_face=True)
    assert not r["ok"] and r["block"]


def test_subject_under_text_ignores_the_zone_once_it_is_gone():
    wins = [(10.0, FULL_WIN)]                  # past the span's t1 = 5.0
    box = (0.05, 0.9, 0.2, 0.98)
    r = TL.subject_under_text(wins, box, SIZE, text_spans=SPAN, must_show=True)
    assert r["ok"] and not r["block"]


# --------------------------------------------------------------------------
# direction-monotony
# --------------------------------------------------------------------------


def test_dominant_vector_reads_the_net_travel():
    tl = make_tl([{"t0": 0.0, "t1": 4.0, "kind": "move", "a": {"z": 1.0, "x": 0.1, "y": 0.5},
                    "b": {"z": 1.0, "x": 0.9, "y": 0.5}}])
    assert TL.dominant_vector(tl) == "right"


def test_dominant_vector_none_for_a_hold():
    tl = make_tl([{"t0": 0.0, "t1": 4.0, "kind": "hold", "a": {"z": 1.0, "x": 0.5, "y": 0.5},
                    "b": {"z": 1.0, "x": 0.5, "y": 0.5}}])
    assert TL.dominant_vector(tl) is None


def test_direction_monotony_passes_four_in_a_row():
    assert TL.direction_monotony(["down"] * 4) == []


def test_direction_monotony_warns_past_four_in_a_row():
    out = TL.direction_monotony(["down"] * 5 + ["up"])
    assert out == [{"start": 0, "len": 5, "direction": "down"}]


def test_direction_monotony_a_hold_breaks_the_run():
    out = TL.direction_monotony(["down", "down", None, "down", "down", "down", "down", "down"])
    assert out == [{"start": 3, "len": 5, "direction": "down"}]


# --------------------------------------------------------------------------
# scale-of-share, scale-variety, wide-before-detail
# --------------------------------------------------------------------------


def test_scale_of_share_bands():
    assert TL.scale_of_share(0.9) == "whole"
    assert TL.scale_of_share(0.6) == "field"
    assert TL.scale_of_share(0.2) == "detail"


def test_scale_variety_passes_a_chapter_with_both():
    chapters = {"c1": ["whole", "field", "field", "detail", "field"]}
    assert TL.scale_variety(chapters) == []


def test_scale_variety_warns_a_chapter_missing_detail():
    chapters = {"c1": ["whole", "field", "field", "field", "field"]}
    out = TL.scale_variety(chapters)
    assert out == [{"chapter": "c1", "count": 5, "has_whole": True, "has_detail": False}]


def test_scale_variety_skips_a_short_chapter():
    chapters = {"c1": ["whole", "field"]}
    assert TL.scale_variety(chapters) == []


def test_wide_before_detail_passes_after_a_wide_showing():
    assert TL.wide_before_detail(["whole", "detail"]) == []


def test_wide_before_detail_warns_a_detail_first():
    assert TL.wide_before_detail(["detail", "whole"]) == [{"index": 0}]


def test_wide_before_detail_declared_reveal_waives_it():
    assert TL.wide_before_detail(["detail", "whole"], declared_reveal=[True, False]) == []


# --------------------------------------------------------------------------
# phone-legibility (reused, not reimplemented)
# --------------------------------------------------------------------------


def test_phone_legibility_report_reuses_motion_phone_legibility():
    r = TL.phone_legibility_report(1920, 1080)
    assert r["ok"] and r["phone_width_px"] == M.PHONE["width_px"]
    small = TL.phone_legibility_report(1920, 1080, extra={"tiny": 1.0})
    assert not small["ok"] and any(x["element"] == "tiny" for x in small["under"])


# --------------------------------------------------------------------------
# Integration: a real cam/tl from render.still_camera + engine_cover
# --------------------------------------------------------------------------


EW, EH = 640, 360


def test_check_still_runs_against_a_real_engine_cam():
    item = {"people": False, "class": "place", "compose": "golden",
            "roi": [{"name": "subject", "x": 0.2, "y": 0.05, "w": 0.3, "h": 0.3, "kind": "place",
                     "source": "auto", "confidence": 0.9}]}
    size = (1600, 1200)
    s = {"id": "X", "kind": "archive_still", "_dur": 8.0, "start_s": 0.0, "_item": item}
    cam = R.still_camera(s, size, EW, EH, words=[], fps=24.0)
    cam = R.engine_cover(s, cam, size, EW, EH, [], None, fps=24.0)
    row = TL.check_still(s, cam, size, fps=24.0)
    assert row["id"] == "X"
    assert row["min_move"]["ok"]      # A54: the default pass leaves the cut already moving (never from rest)
    assert row["scale"] in ("whole", "field", "detail")
    assert row["blocks"] == []                              # no must_show region: nothing here can block


# --------------------------------------------------------------------------
# A49, live in build_plan: a must_show box under a lower third is refused
# (a written camera path) or steered clear of it (the engine's own pass).
# --------------------------------------------------------------------------

FW, FH = 640, 360          # the fixture film's own frame size (test_cine5_truth.py's convention)


def _edit(film, fn, name="screenplay.json"):
    data = json.loads((film / name).read_text(encoding="utf-8"))
    fn(data)
    (film / name).write_text(json.dumps(data), encoding="utf-8")


def _shot(play, sid):
    return next(s for p in play["parts"] for s in p["shots"] if s["id"] == sid)


def _text(play, tid):
    return next(x for p in play["parts"] for x in p.get("text", []) if x["id"] == tid)


def _item(film, aid, fn):
    _edit(film, lambda d: fn(next(i for i in d["items"] if i["id"] == aid)), name="stills-ledger.json")


def _plan(film, name="cine4-fixture"):
    j = J.Journal(film=name)
    return R.build_plan(film, W=FW, H=FH, burn_subtitles=False, journal=j), j


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    return make_film(tmp_path_factory.mktemp("cine4") / "fixture")


@pytest.fixture
def film(base, tmp_path):
    dest = tmp_path / "fixture"
    shutil.copytree(base, dest, ignore=shutil.ignore_patterns("cache", "out"))
    return dest


def _widen_lt_over_s3(film):
    # T1 (a lower third) already sits in S3's own chapter; widen it so it is fully up for S3's whole duration
    # (4.5 to 8.5 s), regardless of A16's own stagger and exit clipping
    _edit(film, lambda p: _text(p, "T1").update(start_s=4.5, end_s=10.0))


# FX-STILL-A is 1500x1050 (make_media.STILLS); this box (picture fractions) and this stop (z, x, y), solved from
# motion.ZONES["LT"] and tour.window's own geometry, together land the box exactly on the LT zone at FW x FH
# (640x360, 16:9): a human-written stop here is refused as written (A43's rule); the engine never writes it this
# way, but the same box as a must_show region lets A47's own pass try to steer clear of it instead
MUST_SHOW_BOX = {"x": 0.1, "y": 0.70, "w": 0.5, "h": 0.0779177295918367}
ON_LT_STOP = {"z": 1.12, "x": 0.5107142857142857, "y": 0.476578443877551}


def test_plan_refuses_a_written_stop_that_puts_a_must_show_box_under_the_lower_third(film):
    _widen_lt_over_s3(film)
    _item(film, "FX-STILL-A", lambda i: i.update(roi=[dict(MUST_SHOW_BOX, name="caption", must_show=True)]))
    _edit(film, lambda p: _shot(p, "S3").update(preset=None, camera=[dict(ON_LT_STOP, t=0.0, hold=4.0)]))
    with pytest.raises(R.Refused, match=r"subject-under-text \(S3\)"):
        _plan(film, "cine4-authored")


def test_plan_steers_the_engine_s_own_pass_clear_of_the_lower_third(film):
    from PIL import Image

    _widen_lt_over_s3(film)
    _item(film, "FX-STILL-A", lambda i: i.update(
        roi=[dict(MUST_SHOW_BOX, name="subject", must_show=True, kind="place", source="auto", confidence=0.9)]))
    _edit(film, lambda p: _shot(p, "S3").update(preset=None, camera=None))
    plan, j = _plan(film, "cine4-engine")                   # must not raise: the engine steers, or is never refused
    s3 = next(s for s in plan["shots"] if s["id"] == "S3")
    sub = s3["_cam"].get("subject") or {}
    assert sub.get("avoid_clear") is not None               # A47's end_pose ran with the must_show box to avoid
    tl = s3["_cam"]["tour"]
    wins = TL.frame_windows(tl, float(plan["fps"]))
    box = T.roi_box(next(r for r in s3["_item"]["roi"] if r.get("name") == "subject"))
    with Image.open(s3["_item"]["_path"]) as im:
        size = im.size
    span = [{"zone": "LT", "box": M.ZONES["LT"], "t0": 0.0, "t1": float(s3["_dur"])}]
    r = TL.subject_under_text(wins, box, size, text_spans=span, must_show=True)
    assert not r["block"]
