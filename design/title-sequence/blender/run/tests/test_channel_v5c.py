"""The Run v5c: the carved channel is one continuous groove that fits the table, falls only downhill, keeps the marble
visible, puts leather only on straights clear of the banks, has nothing lying in it, passes the records in time order,
and (in the design's 1D clock) lands the run inside 34-40 s with the marble stopped on the felt clear of the record."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import channel_v5c as C  # noqa: E402


def _stations(n=4000):
    ss = np.linspace(0, C.LENGTH, n)
    return ss, np.array([C.point(s) for s in ss])


def test_the_groove_is_one_continuous_curve():
    ss, P = _stations()
    step = np.hypot(np.diff(P[:, 0]), np.diff(P[:, 1]))
    assert np.allclose(step, ss[1] - ss[0], rtol=0.01)
    dh = np.diff(np.unwrap(P[:, 2]))
    assert np.abs(dh).max() < 0.01                       # no kink in the heading anywhere
    assert 7.9 < C.LENGTH < 8.1


def test_the_run_fits_the_table_with_turns_a_maker_would_cut():
    W, H = C.TABLE["size"]
    _, P = _stations()
    hw = 0.017
    assert P[:, 0].min() - hw > 0 and P[:, 0].max() + hw <= W - C.TURN_EDGE + hw + 1e-9
    assert P[:, 1].min() - hw > 0.09 and P[:, 1].max() + hw < H - 0.09
    assert abs(C.TURN1_C[0] + C.R_TURN - (W - C.TURN_EDGE)) < 1e-9 and abs(C.TURN2_C[0] - C.R_TURN - C.TURN_EDGE) < 1e-9
    for y in C.REACH_Y:                                  # every reach on a heightfield grid line
        assert abs(y / C.CELL - round(y / C.CELL)) < 1e-6


def test_the_floor_only_falls_and_the_marble_stays_visible():
    ss = np.arange(0, C.LENGTH, 0.0005)
    z = C.floor_z(ss)
    assert (np.diff(z) <= 1e-12).all()                   # nothing climbs: the fall is the only drive
    after = ss > C.launch_len()
    depth = -z[after]
    assert depth.min() >= 0.0079 and depth.max() <= C.DEPTH_MAX
    assert C.slope_deg(ss).max() <= C.LAUNCH["deg"] + 1e-9
    assert 0.005 < C.BLOCK["h"] < 0.015                  # a low release block, not a tower


def test_the_two_steps_drop_three_millimetres_at_fifteen_degrees():
    for st in C.STEPS:
        a, b = st["s"] - 0.02, st["s"] + 0.02
        base = math.tan(math.radians(C.SLOPE_DEG[C.seg_at(st["s"])["name"]])) * 0.04
        drop = float(C.floor_z(a) - C.floor_z(b)) - base
        assert abs(drop - C.STEP_DROP) < 0.0002, (st, drop)
        assert C.slope_deg(np.linspace(a, b, 400)).max() <= C.STEP_DEG + 1e-9


def test_leather_lies_on_the_straights_clear_of_the_banks_and_steps():
    lines = [g for g in C.SEGMENTS if g["kind"] == "line"]
    for lz in C.LEATHER:
        sg = [g for g in lines if g["name"] == lz["reach"]][0]
        s0, s1 = lz["s"]
        assert sg["s0"] + C.launch_len() <= s0 and s1 <= sg["s0"] + sg["len"] + 1e-9, lz["name"]
        prev_turn_end = max([g["s0"] + g["len"] for g in C.SEGMENTS if g["kind"] == "arc" and g["s0"] < s0], default=-9)
        assert s0 - prev_turn_end >= 0.20 - 1e-9, lz["name"]       # a straight after each bank (plan, risk 3)
        for st in C.STEPS:
            assert not (s0 - 0.03 <= st["s"] <= s1 + 0.03), (lz["name"], st["name"])
    assert C.LEATHER[-1]["s"][1] >= C.LENGTH - 1e-6 and C.LEATHER[-1]["s"][1] - C.LEATHER[-1]["s"][0] >= 0.40 - 1e-9


def test_nothing_lies_in_the_groove():
    for name in C.ITEMS:
        if name in ("block", "felt", "record"):
            continue
        x0, x1, y0, y1 = C.rect_of(name)
        X, Y = np.meshgrid(np.linspace(x0, x1, 60), np.linspace(y0, y1, 60))
        s, u, k = C.project(X, Y)
        near = np.isfinite(u)
        hw = C.groove_half_width(s[near].ravel()[::97]).max() if near.any() else 0.0
        assert (~near | (np.abs(u) > hw + 0.008)).all(), name


def test_everything_lies_on_the_table_and_every_overlap_is_named():
    W, H = C.TABLE["size"]
    names = list(C.ITEMS)
    for n in names:
        x0, x1, y0, y1 = C.rect_of(n)
        assert 0 <= x0 < x1 <= W and 0 <= y0 < y1 <= H, n
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            ra, rb = C.rect_of(a), C.rect_of(b)
            if ra[0] < rb[1] and rb[0] < ra[1] and ra[2] < rb[3] and rb[2] < ra[3]:
                assert (a, b) in C.PLANNED_OVERLAPS or (b, a) in C.PLANNED_OVERLAPS, (a, b)


def test_the_marble_passes_the_records_in_time_order():
    rows = []
    for n, it in C.ITEMS.items():
        if it["kind"] != "record" or "beside" not in it:
            continue
        sg = [g for g in C.SEGMENTS if g["name"] == it["beside"]][0]
        x0, x1, y0, y1 = C.rect_of(n)
        s = sg["s0"] + abs((x0 + x1) / 2 - sg["p0"][0])
        rows.append((it["date"], s, n))
    rows.sort()
    assert [r[1] for r in rows] == sorted(r[1] for r in rows), rows


def test_the_design_clock_lands_inside_the_window_with_margin():
    r = C.roll_1d()
    total = C.T_RELEASE + r["t_rest"] + C.RUNTIME["arrive"]
    assert C.RUNTIME["min"] <= total <= C.RUNTIME["max"], total
    into = r["s_rest"] - C.LENGTH
    assert 0.03 <= into and C.LIP_X + into + C.R + 0.10 <= C.ITEMS["record"]["rect"][0]
    run = (r["s"] < C.LENGTH) & (r["t"] > 1.0)
    assert r["v"][run].min() >= 0.15
    # robustness: 15% more leather drag still reaches the felt
    hard = C.roll_1d(crr=dict(C.CRR, leather=C.CRR["leather"] * 1.15))
    assert hard["s_rest"] > C.LENGTH


def test_the_opening_wide_holds_the_whole_run_from_one_point_six_metres():
    eye, tgt = C.opening_eye()
    assert abs(eye[2] - 1.60) < 1e-9 and eye[0] < 0 and eye[1] < 0
    assert C.marble_px(C.FOLLOW["D"]) > 80 and C.marble_px(C.CLOSE["D"]) > 250


def test_one_lamp_and_its_spread_along_the_run():
    ss = np.linspace(0, C.LENGTH, 300)
    st = [C.lamp_falloff_stops(*C.point(s)[:2]) for s in ss]
    assert max(st) - min(st) <= 3.0                      # carried by the camera's auto-exposure (plan section 5)
    assert C.LAMP["kelvin"] == 3400.0 and C.LAMP["white_balance_k"] == 4300.0
