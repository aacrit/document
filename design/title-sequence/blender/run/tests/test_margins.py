"""The Run: every hand-off keeps its headroom (coordinator, 2026-10-18: upstream changes must stop flipping turns).
Reads the latest bake's checks (sim_run.py writes run-checks.json) and fails if any margin is under MIN_MARGIN."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

CHECKS = Path("D:/document-media/title-sequence/run/sim/v4/run-checks.json")
MIN_MARGIN = 0.20

pytestmark = pytest.mark.skipif(not CHECKS.exists(), reason="no bake yet")


def test_every_hand_off_keeps_its_margin():
    m = json.loads(CHECKS.read_text(encoding="utf-8")).get("margins", {})
    assert m, "the bake carries no margins"
    low = {k: v["margin"] for k, v in m.items() if v["margin"] < MIN_MARGIN}
    assert not low, f"margins under {MIN_MARGIN:.0%}: {low}"
