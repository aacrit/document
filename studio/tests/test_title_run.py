"""The Run (design/title-sequence/blender/run): the bronze disc's analytic Moffatt settle and the contact event-list
writer. Pure maths and a temp file; no Blender, no MuJoCo."""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import pytest

_D = Path(__file__).resolve().parents[2] / "design/title-sequence/blender/run"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"run_{name}", _D / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


M = _load("moffatt")
E = _load("eventlog")


def test_the_tilt_follows_moffatts_one_third_law_and_is_flat_at_the_slap():
    t0 = M.T_SLAP
    for d in (1.0, 0.3, 0.1, 0.01):
        assert M.alpha(t0 - d) / M.alpha(t0 - 1.0) == pytest.approx(d ** (1 / 3), rel=1e-9)
    assert M.alpha(t0) == 0.0 and M.alpha(t0 + 0.5) == 0.0
    al = [M.alpha(t0 - 2.0 + i * 0.01) for i in range(200)]
    assert all(b < a for a, b in zip(al, al[1:]))


def test_the_precession_quickens_and_obeys_the_rolling_disc_relation():
    t0 = M.T_SLAP
    for d in (1.5, 0.5, 0.05):
        t = t0 - d
        assert M.omega(t) ** 2 * M.A * M.alpha(t) == pytest.approx(4 * M.G, rel=1e-12)
    assert M.rate_hz(t0 - 1.0) == pytest.approx(M.C_HZ)
    r = [M.rate_hz(t0 - 2.0 + i * 0.01) for i in range(200)]
    assert all(b > a for a, b in zip(r, r[1:]))


def test_the_phase_is_the_integral_of_the_precession_rate():
    t0 = M.T_SLAP
    assert M.phase(t0) == pytest.approx(M.PHI_SLAP)
    for t in (t0 - 1.2, t0 - 0.4, t0 - 0.02):
        h = 1e-6
        assert (M.phase(t + h) - M.phase(t - h)) / (2 * h) == pytest.approx(M.omega(t), rel=1e-5)


def test_the_rim_touches_the_bench_while_it_rolls_and_the_face_lies_on_it_after():
    for d in (1.0, 0.4, 0.1, 0.02):
        assert M.lowest_point_z(M.T_SLAP - d) == pytest.approx(0.0, abs=2e-7)
    assert M.lowest_point_z(M.T_SLAP + 0.3) == pytest.approx(0.0, abs=1e-12)
    p = M.pose(M.T_SLAP + 0.3)
    assert p["centre"][2] == pytest.approx(M.T / 2) and p["normal"] == pytest.approx((0, 0, 1))


def test_the_skitter_stops_after_its_distance_and_runs_along_the_last_tangent():
    assert M.skitter(M.T_SLAP) == 0.0
    assert M.skitter(M.T_SLAP + 1.0) == pytest.approx(M.SKITTER, rel=1e-9)
    d = [M.skitter(M.T_SLAP + i * 0.005) for i in range(60)]
    assert all(b >= a for a, b in zip(d, d[1:]))
    p0, p1 = M.pose(M.T_SLAP), M.pose(M.T_SLAP + 1.0)
    dx, dy = p1["centre"][0] - p0["centre"][0], p1["centre"][1] - p0["centre"][1]
    assert math.hypot(dx, dy) == pytest.approx(M.SKITTER, rel=1e-9)
    assert (dx, dy) == pytest.approx((-M.SKITTER * math.sin(M.PHI_SLAP), M.SKITTER * math.cos(M.PHI_SLAP)), abs=1e-12)


def _s(t, pair, v, f):
    return {"t_s": t, "pair": pair, "v_n": v, "f_n": f}


def test_events_are_onsets_with_their_first_milliseconds_of_impulse():
    log = [_s(0.010, "a|b", 0.30, 2.0), _s(0.011, "a|b", 0.10, 3.0), _s(0.012, "a|b", 0.0, 1.0),
           _s(0.020, "c|d", 0.20, 4.0),
           _s(0.031, "a|b", 0.25, 5.0)]                          # a|b separated at 0.013 and struck again
    ev = E.events(log, impulse_ms=5)
    assert [(e["t_s"], e["pair"]) for e in ev] == [(0.010, "a|b"), (0.020, "c|d"), (0.031, "a|b")]
    assert ev[0]["impulse"] == pytest.approx((2.0 + 3.0 + 1.0) * 0.001)
    assert ev[1]["impulse"] == pytest.approx(0.004) and ev[2]["v_n"] == 0.25
    assert ev[0]["frame"] == pytest.approx(0.24)


def test_slow_contacts_are_not_events_and_impulse_stops_at_its_window():
    log = [_s(0.001 * k, "m|floor", 0.001, 1.0) for k in range(1, 50)]
    log += [_s(0.100 + 0.001 * k, "m|q1", 0.4, 10.0) for k in range(20)]
    ev = E.events(log, impulse_ms=5)
    assert [e["pair"] for e in ev] == ["m|q1"]
    assert ev[0]["impulse"] == pytest.approx(0.05)


def test_the_event_list_is_jsonl_round_trip(tmp_path):
    rows = E.events([_s(0.5, "x|y", 1.0, 2.0)])
    p = E.write_jsonl(rows, tmp_path / "events.jsonl")
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and set(json.loads(lines[0])) == {"t_s", "frame", "pair", "v_n", "impulse"}
    assert E.read_jsonl(p) == rows
