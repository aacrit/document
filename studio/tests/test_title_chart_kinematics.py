"""Title B "Chart" (design/title-sequence/blender/chart/kinematics.py): the analytic unroll conserves the sheet's
area and rolls without slip, the roll slows while its turn rate rises, and the record slide stops at its solved pose.
Pure maths, no Blender, no files."""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

_P = Path(__file__).resolve().parents[2] / "design/title-sequence/blender/chart/kinematics.py"
_spec = importlib.util.spec_from_file_location("chart_kinematics", _P)
K = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(K)

FRAMES = [K.F_ZERO + 0.25 * i for i in range(int((K.F_LAST - K.F_ZERO) / 0.25) + 1)]


def test_roll_radius_and_laid_length_conserve_the_sheet_area():
    for f in FRAMES[::7]:
        st = K.roll_state(f)
        rolled_area = math.pi * (st["r"] ** 2 - K.R_CORE ** 2)
        assert rolled_area == pytest.approx(K.H * (K.L - st["s"]), rel=1e-9, abs=1e-12)
        assert 0.0 <= st["s"] <= K.L
    assert K.roll_state(K.F_ZERO)["s"] == pytest.approx(0.0, abs=1e-9)
    assert K.roll_state(K.F_LAST)["s"] == pytest.approx(K.L, abs=1e-9)
    assert K.roll_state(K.F_LAST)["r"] == pytest.approx(K.R_CORE)


def test_the_spiral_holds_exactly_the_unlaid_paper():
    for f in (60, 300, 540, 620):
        st = K.roll_state(f)
        phi, rho = K.spiral(K.L - st["s"], st["r"])
        assert rho == pytest.approx(K.R_CORE, rel=1e-6)
        assert phi == pytest.approx(K.THETA_END - st["theta"], rel=1e-6, abs=1e-6)
        # arc length of the spiral, integrated numerically, is the unlaid length
        n, arc = 4000, 0.0
        for i in range(n):
            a, b = phi * i / n, phi * (i + 1) / n
            ra, rb = st["r"] - K.H * a / (2 * math.pi), st["r"] - K.H * b / (2 * math.pi)
            arc += math.hypot(rb * math.cos(b) - ra * math.cos(a), rb * math.sin(b) - ra * math.sin(a))
        assert arc == pytest.approx(K.L - st["s"], rel=2e-3)


def test_rolls_without_slip_including_the_lope():
    """ds = r dtheta at every step: the contact point does not slide on the table."""
    for f in FRAMES[:-1:5]:
        a, b = K.roll_state(f), K.roll_state(f + 0.01)
        ds, dth = b["s"] - a["s"], b["theta"] - a["theta"]
        assert dth > 0 and ds > 0
        assert ds == pytest.approx(0.5 * (a["r"] + b["r"]) * dth, rel=1e-4)


def test_the_roll_slows_while_its_turns_per_second_rise():
    states = [K.roll_state(f) for f in FRAMES]
    v = [s["v_mean"] for s in states]
    n = [s["turns_per_s_mean"] for s in states]
    assert all(b < a for a, b in zip(v, v[1:-1]))
    assert all(b > a for a, b in zip(n, n[1:-1]))
    # per whole turn, the loped motion slows too: time per metre laid grows turn by turn
    marks, k = [], 1
    for s in states:
        if s["theta"] >= 2 * math.pi * k:
            marks.append((s["t"], s["s"]))
            k += 1
    speeds = [(s1 - s0) / (t1 - t0) for (t0, s0), (t1, s1) in zip(marks, marks[1:])]
    assert len(speeds) >= 6 and all(b < a for a, b in zip(speeds, speeds[1:]))
    rates = [1.0 / (t1 - t0) for (t0, _), (t1, _) in zip(marks, marks[1:])]
    assert all(b > a for a, b in zip(rates, rates[1:]))


def test_the_rotation_is_monotone_and_the_lope_is_small():
    th = [K.roll_state(f)["theta"] for f in FRAMES]
    assert all(b >= a for a, b in zip(th, th[1:]))
    assert K.LOPE < 0.1
    for x in (0.1, 3.0, 40.0, 90.0):
        assert K.unlope(K.lope(x)) == pytest.approx(x, abs=1e-9)


def test_the_residual_curl_starts_flat_and_is_gone_a_second_after_laydown():
    assert K.curl(0.0) == 0.0
    peak = max(K.curl(i / 1000) for i in range(1, 1000))
    assert peak == pytest.approx(K.CURL, rel=1e-3)
    assert K.curl(1.0) < 0.05 * K.CURL
    ages = [i / 100 for i in range(30, 200)]
    vals = [K.curl(a) for a in ages]
    assert all(b < a for a, b in zip(vals, vals[1:]))
    # a material point is laid exactly when the contact line reaches it
    for f in (100, 400, 560):
        st = K.roll_state(f)
        assert K.laid_time(st["s"]) == pytest.approx(st["t"], abs=1e-6)


def test_the_slide_decelerates_constantly_and_stops_at_the_solved_pose():
    st0, st_end = K.slide_state(K.SLIDE_F0), K.slide_state(K.SLIDE_STOP)
    assert st0["offset"] == pytest.approx(-K.SLIDE_D)
    assert st_end["offset"] == 0.0 and st_end["v"] == 0.0 and st_end["yaw"] == 0.0 and st_end["stopped"]
    for f in range(K.SLIDE_STOP, K.SLIDE_STOP + 30):
        assert K.slide_state(f) == st_end
    ys = [K.slide_state(K.SLIDE_F0 + i)["offset"] for i in range(K.SLIDE_STOP - K.SLIDE_F0 + 1)]
    assert all(b > a for a, b in zip(ys, ys[1:]))                     # never overshoots, never backs up
    acc = [ys[i + 1] - 2 * ys[i] + ys[i - 1] for i in range(1, len(ys) - 1)]
    assert max(acc) == pytest.approx(min(acc), rel=1e-6)              # constant deceleration
    assert acc[0] * K.FPS ** 2 == pytest.approx(-K.SLIDE_A, rel=1e-6)
    v = [K.slide_state(K.SLIDE_F0 + i)["v"] for i in range(K.SLIDE_STOP - K.SLIDE_F0 + 1)]
    assert all(b < a for a, b in zip(v, v[1:]))


def test_the_flat_hold_blends_over_the_last_twelve_frames_of_the_slide():
    assert K.hold_mix(K.SLIDE_STOP - 12) == 0.0
    assert K.hold_mix(K.SLIDE_STOP) == 1.0
    assert 0.0 < K.hold_mix(K.SLIDE_STOP - 6) < 1.0
    assert K.hold_mix(K.SLIDE_STOP + 11) == 1.0
