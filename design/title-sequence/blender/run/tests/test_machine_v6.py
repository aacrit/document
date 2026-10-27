"""Title v6: the lock text round-trips, the dirty query is read strictly, a dead pid is seen dead."""

from __future__ import annotations

import os
import sys
from pathlib import Path

RUN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUN))
import machine_v6 as MV  # noqa: E402


def test_lock_text_round_trips_in_both_house_forms():
    d = MV.parse_lock(MV.lock_text("v6 bake", 4242))
    assert d["purpose"] == "v6 bake" and d["pid"] == "4242" and d["started"]
    assert MV.parse_lock('{"pid": 17, "job": "x"}') == {"pid": 17, "job": "x"}


def test_only_not_dirty_is_clean():
    assert MV.dirty_says_clean("Volume - D: is NOT Dirty\n")
    assert not MV.dirty_says_clean("Volume - D: is Dirty\n")
    assert not MV.dirty_says_clean("Error:  Access is denied.")


def test_this_process_is_alive_and_an_unused_pid_is_not():
    assert MV.pid_alive(os.getpid())
    assert not MV.pid_alive(4_000_000)
