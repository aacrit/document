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


def test_the_memory_cap_makes_an_oversized_allocation_fail_cleanly():
    """In a child process capped at 1 GB, a 2 GB array raises MemoryError and the child carries on and exits normally."""
    import subprocess
    code = ("import sys; sys.path.insert(0, %r); import machine_v6 as M; import numpy as np; M.cap_memory(1.0)\n"
            "try:\n    a = np.ones(256 * 2**20)\n    print('allocated')\nexcept MemoryError:\n    print('refused')\n"
            "b = np.ones(2**20); print('small ok', b.sum())" % str(RUN))
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    assert "refused" in p.stdout and "small ok" in p.stdout


def test_batches_stay_under_a_gib_and_an_eighth_of_free_ram():
    assert MV.batch_rows(24, free_gb=64.0) == (1 << 30) // 24
    assert MV.batch_rows(24, free_gb=2.0) == int((2 * 2 ** 30 / 8) // 24)
    assert MV.batch_rows(10 ** 12, free_gb=64.0) == 1
    assert MV.free_ram_gb() > 0


def test_this_process_is_alive_and_an_unused_pid_is_not():
    assert MV.pid_alive(os.getpid())
    assert not MV.pid_alive(4_000_000)
