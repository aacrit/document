"""Title v6 (The Run with the instruments), day 1: the scan gate, the museum scales and the scan orientations.

The gate reproduces every verdict already in run-scan-ledger.json (the regression), refuses a scan whose capture method
the institution's records do not name, and refuses a file whose hash has moved. The scales come from the museum
records, not from earlier guesses (the globe was 0.24 or 0.30 m in two modules; its record says 0.51 m wide)."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

RUN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUN))
import scans_v6 as SV  # noqa: E402

LEDGER = RUN.parents[1] / "run-scan-ledger.json"


def _items():
    return json.loads(LEDGER.read_text(encoding="utf-8"))["items"]


def test_the_gate_reproduces_every_verdict_in_the_ledger():
    for it in _items():
        if it["id"] == SV.KEY_ID:
            continue
        verdict, reasons = SV.gate(it)
        assert verdict == it["gate"], (it["id"], reasons)


def test_an_unnamed_capture_method_is_refused():
    base = {"id": "x", "licence": "CC0", "capture_method": "photogrammetry", "ai": False, "sha256": "ab" * 32,
            "capture_evidence": "Numérisation 3D par un prestataire (method not named on the page)"}
    assert SV.gate(base)[0] == "refuse"
    base["capture_evidence"] = "3D digitisation was done by two named people"            # names people, not a method
    assert SV.gate(base)[0] == "refuse"
    base["capture_evidence"] = "skanowanie 3D obiektu, efektem którego jest uzyskanie chmur punktów"
    assert SV.gate(base)[0] == "pass"
    base["capture_method"] = "unknown"
    assert SV.gate(base)[0] == "refuse"


def test_the_gate_refuses_ai_a_non_cc0_licence_and_a_moved_hash():
    ok = {"id": "x", "licence": "CC0", "capture_method": "structured-light", "ai": False, "sha256": "ab" * 32,
          "capture_evidence": "scanner 3D Artec EVA", "files": [{"path": "a/b.bin", "sha256": "11" * 32}]}
    assert SV.gate(ok, disk={"a/b.bin": "11" * 32})[0] == "pass"
    assert SV.gate(ok, disk={"a/b.bin": "22" * 32})[0] == "refuse"
    assert SV.gate(ok, disk={})[0] == "refuse"                                             # the file is missing
    assert SV.gate(dict(ok, ai=True))[0] == "refuse"
    assert SV.gate(dict(ok, licence="CC BY"))[0] == "refuse"


def test_the_key_is_in_the_ledger_and_refused_on_its_records():
    key = {i["id"]: i for i in _items()}[SV.KEY_ID]
    assert key["gate"] == "refuse" and key["capture_method"] == "unknown"
    assert SV.gate(key)[0] == "refuse"
    assert "nmah_1096762" in key["capture_evidence_url"] or "ed99f44d" in key["capture_evidence_url"]


def test_the_globe_scale_comes_from_its_ball_and_agrees_with_the_record_width():
    rec = SV.MUSEUM["globe"]
    assert rec["ball_d_m"] == 0.32 and rec["width_m"] == 0.51 and rec["height_m"] == 0.43
    # the scan's fitted ball diameter and its horizon width in native units (measured day 1)
    k = SV.globe_scale(ball_native=0.5922)
    assert abs(k * 0.9498 - 0.51) / 0.51 < 0.01                         # the width agrees within 1 percent
    assert not (0.235 < k * 0.9498 < 0.245) and not (0.295 < k * 0.9498 < 0.305)   # neither earlier guess


def test_the_weights_scale_is_their_recorded_height():
    assert SV.MUSEUM["weights"]["height_m"] == 0.062
    assert math.isclose(SV.axis_scale(0.2325, SV.MUSEUM["weights"]["height_m"]), 0.062 / 0.2325)


def test_the_jeton_is_a_square_plaque_in_millimetres():
    j = SV.MUSEUM["jeton"]
    assert j["size_m"] == (0.026, 0.024)
    k, res = SV.fit_scale((25.84, 23.68), j["size_m"])
    assert abs(k - 0.001) < 1.5e-5 and max(abs(r) for r in res) < 0.015


def test_fit_scale_is_the_log_least_squares_factor():
    k, res = SV.fit_scale((1.0, 2.0), (2.0, 4.0))
    assert math.isclose(k, 2.0) and all(abs(r) < 1e-12 for r in res)
    k, res = SV.fit_scale((1.0, 1.0), (1.0, 4.0))
    assert math.isclose(k, 2.0) and math.isclose(res[0], 1.0) and math.isclose(res[1], -0.5)


def test_orientations_are_proper_rotations():
    v = np.array([[1.0, 2.0, 3.0]])
    assert np.allclose(SV.zup(v), [[1.0, -3.0, 2.0]])                   # glTF y-up to table z-up
    for R in (SV.upright_weights_R(), SV.flat_R(np.random.default_rng(1).normal(size=(500, 3)) * [5, 4, 0.3])):
        assert np.allclose(R @ R.T, np.eye(3), atol=1e-9) and math.isclose(np.linalg.det(R), 1.0)


def test_the_ball_stops_at_a_cylinder_one_radius_out_and_does_not_feel_a_narrow_groove():
    rng = np.random.default_rng(3)
    a = 0.03
    th = rng.uniform(-np.pi, np.pi, 200_000)
    z = rng.uniform(0.0, 0.03, 200_000)
    cyl = np.stack([a * np.cos(th), a * np.sin(th), z], 1)
    _, r = SV.touch_radius(cyl, 0.015)
    assert np.allclose(r, a + SV.BALL_R, atol=2e-4)
    # a groove 1.2 mm deep and 3 mm tall cut round the cylinder: the ball cannot reach into it
    groove = cyl.copy()
    g = (z > 0.0135) & (z < 0.0165)
    groove[g, :2] *= (a - 0.0012) / a
    gap = SV.swept_gap(groove, cyl)
    assert gap["air_m"] < 1e-4 and gap["missing_m"] < 1e-4


def test_flat_R_puts_the_thin_axis_up():
    rng = np.random.default_rng(2)
    P = rng.normal(size=(4000, 3)) * [12.0, 13.0, 1.0]
    a = math.radians(35.0)
    tilt = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
    Q = P @ tilt.T
    F = (Q - Q.mean(0)) @ SV.flat_R(Q).T
    ext = F.max(0) - F.min(0)
    assert ext[2] < 0.3 * min(ext[0], ext[1])
