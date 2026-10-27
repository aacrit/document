"""Laid Down (the series title, spec rev 3, 2026-10-26): the beats file and the closed-form slides it is solved from.

Every sheet slides to rest under Coulomb friction: speed falls linearly to zero, the turn stops at the same instant,
nothing eases after the stop; releases lie on the table and off the frame; entry intervals fall to S6 and the stillness
outlasts the last hold by 1.4 times; the record is never in frame before its entry."""

from __future__ import annotations

import math
import sys
from pathlib import Path

RUN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUN))
import laid_down as L  # noqa: E402


def _t(f):
    return f * 1001 / 30000


def test_the_beats_file_is_the_spec_frame_list():
    assert L.BEATS["fps"] == "30000/1001" and L.BEATS["frames"] == 1032
    assert L.BEATS["version"] == "spec v3 2026-10-26"
    assert [s["id"] for s in L.SHEETS] == ["S2", "S3", "S4", "S5", "S6"]          # the papyrus is out
    assert [(s["enter_frame"], s["stop_frame"]) for s in L.SHEETS] == [(27, 57), (237, 260), (404, 439), (552, 585),
                                                                       (669, 708)]
    assert L.BEATS["stillness"]["frames"] == [708, 827]
    for r in L.BEATS["records"].values():
        assert r["enter_frame"] == 828 and r["record_pose"]["from_frame"] == 978


def test_the_closed_form_reproduces_the_solved_table():
    for s in L.SHEETS + list(L.RECORDS.values()):
        a = s["mu_eff"] * L.G
        assert abs(a - s.get("decel_m_s2", a)) < 2e-3
        # the release point is the stop pose moved back along the slide by v^2 / 2a
        x, y = L.centre_at(s, s["stop_s"] - L.t_release_to_stop(s))
        assert math.dist((x, y), s["release_centre_m"]) < 0.012, s["id"] if "id" in s else s["tex"]
        # the leading edge reaches the frame's edge at "enter" (to within a frame)
        f = L.first_frame_in_frame(s)
        assert abs(f - s["enter_frame"]) <= 1, (s.get("id", s["tex"]), f, s["enter_frame"])


def test_every_stop_is_a_friction_stop():
    for s in L.SHEETS + list(L.RECORDS.values()):
        t0, t1 = s["stop_s"] - L.t_release_to_stop(s), s["stop_s"]
        ts = [t0 + (t1 - t0) * k / 40 for k in range(41)]
        v = [L.speed_at(s, t) for t in ts]
        # v(t) is linear to zero: constant deceleration mu g, and exactly zero at the stop
        dv = [(v[k + 1] - v[k]) / (ts[k + 1] - ts[k]) for k in range(40)]
        assert all(abs(d + s["mu_eff"] * L.G) < 1e-6 for d in dv)
        assert v[-1] == 0.0
        # nothing moves after the stop: not the centre, not the turn
        for dt in (0.0, 0.01, 0.5, 5.0):
            assert L.centre_at(s, t1 + dt) == tuple(s["land_centre_m"])
            assert L.psi_at(s, t1 + dt) == s["land_psi_deg"]
        # the turn stops with the translation (the same quadratic in the time to the stop)
        eps = 1e-4
        w = (L.psi_at(s, t1) - L.psi_at(s, t1 - eps)) / eps
        assert abs(w) < 1e-2


def test_the_turn_lands_on_its_psi_from_psi_minus_delta_at_entry():
    for s in L.SHEETS:
        p = L.psi_at(s, s["stop_s"] - s["t_visible_s"])
        assert abs(p - (s["land_psi_deg"] - s["turn_delta_deg"])) < 1e-9


def test_releases_lie_on_the_table_and_off_the_frame():
    fw, fh = L.FRAME_M[0] / 2, L.FRAME_M[1] / 2
    W, H = L.TABLE["size"]
    for s in L.SHEETS + list(L.RECORDS.values()):
        cs = L.footprint(s, s["stop_s"] - L.t_release_to_stop(s))
        for x, y in cs:
            X, Y = x + L.P[0], y + L.P[1]
            assert 0.0 <= X <= W and 0.0 <= Y <= H, (s.get("id"), X, Y)
        assert not L.poly_hits_frame(cs), s.get("id")


def test_entry_intervals_fall_and_the_stillness_outlasts_the_last_hold():
    t = [s["enter_s"] for s in L.SHEETS] + [L.RECORDS["C20-METAR-0851"]["enter_s"]]
    iv = [round(b - a, 2) for a, b in zip(t, t[1:])]
    assert iv == L.BEATS["entry_intervals_s"]
    n = len(L.SHEETS) - 1                                # the intervals between sheets strictly shorten
    assert all(b < a for a, b in zip(iv[:n], iv[1:n]))
    still = L.BEATS["stillness"]["dur_s"]
    assert still >= 1.4 * L.SHEETS[-2]["hold_s"]


def test_the_record_is_never_in_frame_before_its_entry():
    for r in L.RECORDS.values():
        for f in range(0, 828):
            assert not L.poly_hits_frame(L.footprint(r, _t(f))) or not L.visible_at(r, _t(f))


def test_the_trailing_corner_is_held_then_settles_in_a_quarter_second():
    s = L.BY_ID["S5"]                                   # released at 1.62 m/s: min(4 mm, 3.2 mm)
    held = min(L.LIFT_MAX, L.LIFT_PER_V * s["v_release_m_s"])
    assert L.lift_at(s, s["stop_s"] - 0.3) == held
    assert L.lift_at(s, s["stop_s"]) == held
    assert 0 < L.lift_at(s, s["stop_s"] + 0.125) < held
    assert L.lift_at(s, s["stop_s"] + 0.25) == 0.0
    assert L.lift_at(s, s["stop_s"] + 2.0) == 0.0
    assert max(L.lift_at(x, x["stop_s"]) for x in L.SHEETS) <= 0.004
    a = L.BY_ID["S2"]                                   # the Atlas boards: a 1 mm trailing edge, down in 0.25 s
    assert L.lift_at(a, a["stop_s"]) == 0.001 and L.lift_at(a, a["stop_s"] + 0.1) > 0.0
    assert L.lift_at(a, a["stop_s"] + 0.25) == 0.0


def test_a_sheet_lies_down_onto_the_pile_as_its_corner_settles():
    s = L.BY_ID["S6"]
    assert L.lie_at(s, s["stop_s"] - 0.1) == 0.0 and L.lie_at(s, s["stop_s"]) == 0.0
    assert 0 < L.lie_at(s, s["stop_s"] + 0.1) < 1
    assert L.lie_at(s, s["stop_s"] + 0.25) == 1.0 and L.lie_at(s, 40.0) == 1.0
    assert all(L.lie_at(L.BY_ID["S2"], t) == 0.0 for t in (7.0, 8.0, 30.0))      # the boards stay rigid


def test_the_camera_is_fixed_until_the_record_enters():
    for f in (0, 54, 400, 708, 827):
        eye, roll = L.camera_at("C20-METAR-0851", f)
        assert eye == (L.P[0], L.P[1], 2.00) and roll == 0.0
    eye, roll = L.camera_at("C20-METAR-0851", 978)
    assert abs(eye[2] - 0.278) < 1e-3 and abs(roll - 1.5) < 1e-9
    assert L.camera_at("C20-METAR-0851", 1031) == L.camera_at("C20-METAR-0851", 978)


def test_the_pose_height_is_over_the_record_where_it_lies_on_the_pile():
    eye, _ = L.camera_at("C20-METAR-0851", 978, record_z=0.0068)
    assert abs(eye[2] - (0.0068 + 0.2 / 0.72)) < 1e-9          # the window's width / 0.72, exactly
    assert abs(L.camera_at("C20-METAR-0851", 978)[0][2] - L.RECORDS["C20-METAR-0851"]["pose_eye_height_m"]) < 5e-4
    assert L.camera_at("C20-METAR-0851", 100, record_z=0.0068)[0][2] == 2.00     # the fixed camera is not moved


def test_the_flat_hold_ramps_over_the_twelve_frames_before_the_pose():
    assert L.hold_mix(965) == 0.0 and L.hold_mix(966) == 0.0
    assert 0 < L.hold_mix(972) < 1 and L.hold_mix(978) == 1.0 and L.hold_mix(1031) == 1.0


def test_the_frame_on_the_table_is_the_lens_at_two_metres():
    assert abs(L.FRAME_M[0] - 1.44) < 1e-9 and abs(L.FRAME_M[1] - 0.81) < 1e-9
    assert L.P == (2.0, 1.0) and L.TABLE["size"] == (4.0, 2.0)


def test_every_stop_keeps_the_earlier_sheets_showing():
    # the spec's floors (checks), measured on its 1440 x 810 raster
    rows = L.cover_floors()
    bad = [r for r in rows if not r[5]]
    assert not bad, bad
    assert len(rows) == len(L.SHEETS) * (len(L.SHEETS) - 1) // 2 + 1


def test_the_cover_measure_agrees_with_the_spec_generator():
    for s in L.SHEETS:
        got = L.topmost_cover(s["stop_frame"])
        for k, v in s["cover_at_stop"].items():
            assert abs(got.get(k, 0.0) - v) < 0.003, (s["id"], k, got.get(k), v)


# ------------------------------------------------------------------------------------------------ the Foley's events


def test_every_sheet_is_heard_before_it_is_seen():
    for s in L.SHEETS + list(L.RECORDS.values()):
        lead = s["enter_s"] - L.push_start_s(s)
        assert 0.1 <= lead <= 0.3, (s["id"], lead)
        # the push is never seen: the sheet starts moving off frame and leaves the hand at its release speed
        assert L.audio_speed(s, L.push_start_s(s) - 0.01) == 0.0
        assert L.audio_speed(s, L.release_s(s)) == L.speed_at(s, L.release_s(s))


def test_the_push_speeds_the_sheet_up_and_the_slide_slows_it_to_zero():
    s = L.BY_ID["S4"]
    t0, tr = L.push_start_s(s), L.release_s(s)
    vs = [L.audio_speed(s, t0 + (tr - t0) * k / 10) for k in range(11)]
    assert all(b >= a for a, b in zip(vs, vs[1:])) and abs(vs[-1] - s["v_release_m_s"]) < 1e-9
    assert L.audio_speed(s, s["stop_s"]) == 0.0 and L.audio_speed(s, s["stop_s"] + 1) == 0.0


def test_an_edge_flick_at_each_edge_the_leading_edge_rides_onto():
    assert L.edge_crossings(L.BY_ID["S2"]) == []                      # the Atlas slides on bare oak
    for s in L.SHEETS[1:] + list(L.RECORDS.values()):
        cr = L.edge_crossings(s)
        under = [e for e in L.SHEETS if e["stop_s"] < L.release_s(s)]
        assert {u for u, _, _ in cr} <= {e["id"] for e in under}
        for uid, kind, t in cr:
            e = L.BY_ID[uid]

            def on(tt):
                return L._sat(L.footprint(s, tt), L.footprint(e, e["stop_s"]))
            assert on(t) and L.release_s(s) <= t < s["stop_s"], (s["id"], uid)
            if kind == "over at release":                 # already over it when it leaves the hand: no flick
                assert t == L.release_s(s)
            else:
                assert kind == "edge flick" and not on(t - 1 / 240)
    # the Ino crosses two edges as it slides: Piri Reis's, then the Atlas's
    assert [k for _, k, _ in L.edge_crossings(L.BY_ID["S5"])].count("edge flick") == 2


def test_the_settle_tap_is_a_quarter_second_after_each_stop():
    for s in L.SHEETS + list(L.RECORDS.values()):
        assert abs(L.settle_tap_s(s) - (s["stop_s"] + 0.25)) < 1e-9


def test_static_frames_are_rendered_once_and_repeated():
    plan = L.render_plan("C20-METAR-0851")
    src = plan["source_of"]
    assert len(src) == L.FRAMES and src[0] == 0
    unique = sorted(set(src))
    assert unique == plan["render"]
    # a repeated frame is identical to the one rendered: same poses at the shutter's open, middle and close
    for f, g in enumerate(src):
        assert L.frame_state(f, "C20-METAR-0851") == L.frame_state(g, "C20-METAR-0851")
    # holds collapse: the stillness (nothing moves) is one render, and so is the pose hold
    still = range(L.BEATS["stillness"]["frames"][0] + 9, L.RECORDS["C20-METAR-0851"]["enter_frame"] - 8)
    assert len({src[f] for f in still}) == 1
    hold = range(L.RECORDS["C20-METAR-0851"]["flat_hold"]["one_from_frame"] + 1, L.FRAMES)
    assert len({src[f] for f in hold}) == 1
    # every slide frame, settle and descent frame is its own render
    for s in L.SHEETS:
        for f in range(s["enter_frame"], s["stop_frame"]):
            assert src[f] == f
    for f in range(L.DESCENT[0] + 1, L.DESCENT[1]):
        assert src[f] == f
    assert len(unique) < 0.6 * L.FRAMES


def test_the_stillness_has_no_slide_in_it_until_the_record_is_heard():
    t0, t1 = L.t_of(L.BEATS["stillness"]["frames"][0]), L.t_of(L.BEATS["stillness"]["frames"][1] + 1)
    for s in L.SHEETS:
        assert all(L.audio_speed(s, t0 + (t1 - t0) * k / 50) == 0.0 for k in range(51))
    for r in L.RECORDS.values():                      # the record is heard only in the stillness's last 0.3 s
        assert L.push_start_s(r) >= t1 - 0.3
