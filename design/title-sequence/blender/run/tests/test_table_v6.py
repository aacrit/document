"""Title v6, days 2-3: the layout on the table, the fall and its two sags, the roof-tiling, the event classes and the
preview-1 acceptance checks (pure functions; the bake is checked by them, not by eye)."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

RUN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUN))
import table_v6 as T  # noqa: E402


def test_the_ball_is_the_spec_ball():
    assert T.R == 0.015 and abs(T.MASS - 0.027) < 0.0005


def test_the_sheets_lie_in_date_order_older_over_newer():
    order = [s["name"] for s in T.SHEETS]                     # top of the pile first
    assert order == ["atlas1", "atlas2", "leaf", "piri", "ino", "chart"]
    dates = [s["date"] for s in T.SHEETS]
    assert dates == sorted(dates)
    assert T.SHEETS[0]["layer"] > T.SHEETS[-1]["layer"]
    for a, b in zip(T.SHEETS, T.SHEETS[1:]):                  # each next sheet starts before the last one ends
        sa, sb = T.path_span(a["name"]), T.path_span(b["name"])
        if a["name"] == "atlas1":
            assert math.isclose(sb[0] - sa[1], T.HINGE_GAP, abs_tol=0.0011)
        else:
            assert sb[0] < sa[1], (a["name"], b["name"], sa, sb)
    assert math.isclose(T.path_span("chart")[1], T.S_LIP, abs_tol=0.001)        # the chart's edge is the lip


def test_the_warp_is_under_8_mm_and_falls_only_downhill_along_the_path():
    ss = np.linspace(-0.05, T.S_LIP - 1e-4, 4000)
    x, y = T.point(ss)
    z = T.warp(x, y)
    assert z.max() - min(z.min(), 0.0) < 0.008
    assert np.all(np.diff(z) <= 1e-12)                         # no rise along the path: the sags only steepen it
    assert abs(float(T.warp(np.array([2.6]), np.array([1.4]))[0])) < 1e-12     # the well and the record keep v5d's level


def test_the_sags_steepen_the_fall_where_the_spec_puts_them():
    def slope_at(s):
        x0, y0 = T.point(np.array([s - 0.001]))
        x1, y1 = T.point(np.array([s + 0.001]))
        dz = float(T.warp(x1, y1)[0] - T.warp(x0, y0)[0])
        return T.FALL_DEG + math.degrees(math.atan(-dz / 0.002))
    assert slope_at(0.06) == pytest.approx(T.SAGS[0]["deg"], abs=0.02)
    s_mid = T.S_LIP - 0.15
    # the chart sag runs across the lip line, not across the path: along the path it is the spec's 1.5 degrees
    assert slope_at(s_mid) == pytest.approx(T.SAGS[1]["deg"], abs=0.03)
    assert slope_at(1.2) == pytest.approx(T.FALL_DEG, abs=1e-6)


def test_the_path_meets_the_well_inside_its_mouth_and_the_rest_is_on_the_record_line():
    x, y = T.point(np.array([T.S_LIP]))
    assert math.isclose(float(x[0]), T.LIP_X, abs_tol=1e-9)
    assert T.WELL["y"][0] + 0.05 < float(y[0]) < T.WELL["y"][1] - 0.05
    rx, ry = T.REST_TARGET
    assert math.isclose(T.RECORD_RECT[0] - (rx + T.R), 0.007, abs_tol=1e-9)
    assert math.isclose(ry, (T.RECORD_RECT[2] + T.RECORD_RECT[3]) / 2, abs_tol=1e-9)


def test_stack_heights_give_only_down_steps_along_the_path():
    prof = T.ground_profile(np.linspace(0.0, T.S_LIP - 0.002, 6000))
    # the ball rides the envelope of its centre (it bridges the 1.5 mm hinge gap); the drape over a lower sheet's edge
    # is a gentle rise of at most that sheet's thickness, never a step
    rises = T.rises(prof["s"], prof["zc"] - prof["warp"])
    assert all(r["h"] <= 0.00075 and r["len"] >= 0.01 for r in rises), rises
    steps = [d for d in T.down_steps(prof["s"], prof["z"] - prof["warp"]) if "oak" not in (d["onto"], d["from"])]
    assert [d["onto"] for d in steps] == ["leaf", "piri", "ino", "chart"]
    assert all(d["dz"] < 0 for d in steps), steps
    oak = [d for d in T.down_steps(prof["s"], prof["z"]) if d["onto"] == "oak"]
    assert len(oak) == 1 and abs(oak[0]["s"] - T.path_span("atlas1")[1]) < 0.002       # only the hinge gap


def test_roll_1d_holds_speed_at_equilibrium_and_stops_below_it():
    mu = 0.006
    th = math.degrees(math.atan(mu))
    out = T.roll_1d(th, lambda s: mu, v0=0.15, s_end=1.0, slope=lambda s: 0.0)
    assert out["v"][-1] == pytest.approx(0.15, abs=1e-3)
    out = T.roll_1d(th - 0.1, lambda s: mu, v0=0.15, s_end=5.0, slope=lambda s: 0.0)
    assert out["stopped"]


def test_v_stall_is_the_up_step_threshold():
    assert T.v_stall(0.0012) == pytest.approx(math.sqrt(10 / 7 * 9.81 * 0.0012))
    assert T.v_stall(0.0) == 0.0


def test_contact_classes_name_the_seven_designed_contacts_and_flag_the_rest():
    c = T.contact_class
    assert c("ball|latch cup") == 1 and c("ball|latch ramp 3") == 1
    assert c("atlas2|ball") == 2 and c("ball|chart") == 2
    assert c("ball|sort1") == 3
    assert c("ball|weights 4") == 4 and c("ball|globe 11") == 5
    assert c("ball|felt") == 7
    for stray in ("ball|sort2", "ball|galley floor", "ball|galley rail", "ball|oak", "ball|record",
                  "ball|coin dupondius", "ball|jeton", "ball|well wall far"):
        assert c(stray) is None, stray
    assert c("sort3|sort4") == "row" and c("galley floor|sort5") == "row"


def test_heading_change_is_signed_left_positive():
    assert T.turn_deg((1.0, 0.0), (math.cos(0.4), math.sin(0.4))) == pytest.approx(math.degrees(0.4))
    assert T.turn_deg((1.0, 0.0), (math.cos(-0.3), math.sin(-0.3))) == pytest.approx(-math.degrees(0.3))


def test_acceptance_reads_the_spec_numbers():
    A = T.ACCEPT
    assert A["rest_mm"] == (7.0, 5.0) and A["roll_s"] == (20.0, 24.0) and A["v_min"] == 0.10
    assert A["margin"] == 0.15 and A["sorts"] == 12 and A["speed_kept"] == 0.90
    assert A["turn_weights_deg"] == (20.0, 30.0) and A["turn_globe_deg"] == (-25.0, -15.0) and A["gap_m"] == 0.001
    ok = T.check_rest((T.RECORD_RECT[0] - T.R - 0.007, T.REST_TARGET[1]))
    assert ok["pass"] and ok["short_mm"] == pytest.approx(7.0)
    assert not T.check_rest((T.RECORD_RECT[0] - T.R - 0.0125, T.REST_TARGET[1]))["pass"]
    assert not T.check_rest((T.RECORD_RECT[0] - T.R - 0.007, T.REST_TARGET[1] + 0.02))["pass"]
    assert T.check_budget(t_rest=24.0)["pass"] and not T.check_budget(t_rest=31.5)["pass"]
