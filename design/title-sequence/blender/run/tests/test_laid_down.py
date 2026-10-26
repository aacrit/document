"""Laid Down (the series title, spec 2026-10-26): the beats file and the closed-form slides it is solved from.

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
    assert L.BEATS["fps"] == "30000/1001" and L.BEATS["frames"] == 1080
    assert [s["id"] for s in L.SHEETS] == ["S1", "S2", "S3", "S4", "S5", "S6"]
    assert [(s["enter_frame"], s["stop_frame"]) for s in L.SHEETS] == [(12, 37), (204, 237), (375, 391), (502, 529),
                                                                       (616, 651), (717, 751)]
    assert L.BEATS["stillness"]["frames"] == [751, 868]
    for r in L.BEATS["records"].values():
        assert r["enter_frame"] == 869 and r["record_pose"]["from_frame"] == 1019


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
    t = [s["enter_s"] for s in L.SHEETS] + [29.0]
    iv = [round(b - a, 2) for a, b in zip(t, t[1:])]
    assert iv == L.BEATS["entry_intervals_s"]
    assert all(b < a for a, b in zip(iv[:5], iv[1:5]))
    still = L.BEATS["stillness"]["dur_s"]
    assert still >= 1.4 * L.SHEETS[4]["hold_s"]


def test_the_record_is_never_in_frame_before_its_entry():
    for r in L.RECORDS.values():
        for f in range(0, 869):
            assert not L.poly_hits_frame(L.footprint(r, _t(f))) or not L.visible_at(r, _t(f))


def test_the_trailing_corner_is_held_then_settles_in_a_quarter_second():
    s = L.SHEETS[0]
    assert L.lift_at(s, s["stop_s"] - 0.3) == L.LIFT_MAX
    assert L.lift_at(s, s["stop_s"]) == L.LIFT_MAX
    assert 0 < L.lift_at(s, s["stop_s"] + 0.125) < L.LIFT_MAX
    assert L.lift_at(s, s["stop_s"] + 0.25) == 0.0
    assert L.lift_at(s, s["stop_s"] + 2.0) == 0.0
    a = L.SHEETS[1]                                     # the Atlas boards: a 1 mm trailing edge, down in 0.1 s
    assert L.lift_at(a, a["stop_s"]) == 0.001 and L.lift_at(a, a["stop_s"] + 0.1) == 0.0


def test_the_camera_is_fixed_until_the_record_enters():
    for f in (0, 22, 400, 751, 868):
        eye, roll = L.camera_at("C20-METAR-0851", f)
        assert eye == (L.P[0], L.P[1], 1.30) and roll == 0.0
    eye, roll = L.camera_at("C20-METAR-0851", 1019)
    assert abs(eye[2] - 0.278) < 1e-3 and abs(roll - 1.5) < 1e-9
    assert L.camera_at("C20-METAR-0851", 1079) == L.camera_at("C20-METAR-0851", 1019)


def test_the_flat_hold_ramps_over_the_twelve_frames_before_the_pose():
    assert L.hold_mix(1006) == 0.0 and L.hold_mix(1007) == 0.0
    assert 0 < L.hold_mix(1013) < 1 and L.hold_mix(1019) == 1.0 and L.hold_mix(1079) == 1.0


def test_the_frame_on_the_table_is_the_lens_at_one_point_three_metres():
    assert abs(L.FRAME_M[0] - 0.936) < 1e-3 and abs(L.FRAME_M[1] - 0.527) < 1e-3
