"""Title v6: the machine rules for every long job (house rule 13 and the D: incident of 2026-10-10).

`heavy(purpose)` is a context manager: it refuses when D: is dirty (`fsutil dirty query D:`) or when C: or D: has
10 GB or less free; it waits while HEAVY.lock names a live pid, clears a lock whose pid is dead, takes the lock
atomically with this process's real Windows pid, and releases it in a finally (only if the lock is still ours).
"""

from __future__ import annotations

import contextlib
import ctypes
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

LOCK = Path("C:/Users/aacri/document-work/HEAVY.lock")
MIN_FREE_GB = 10.0


def parse_lock(text: str) -> dict:
    """HEAVY.lock in either form the house writes: JSON, or key=value lines (purpose, pid, started)."""
    try:
        d = json.loads(text)
        if isinstance(d, dict):
            return d
    except ValueError:
        pass
    out = {}
    for ln in text.splitlines():
        if "=" in ln:
            k, v = ln.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def lock_text(purpose: str, pid: int) -> str:
    return f"purpose={purpose}\npid={pid}\nstarted={dt.datetime.now().isoformat(timespec='seconds')}\n"


def pid_alive(pid: int) -> bool:
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))      # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = ctypes.c_ulong()
    ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(h)
    return bool(ok) and code.value == 259                               # STILL_ACTIVE


def dirty_says_clean(text: str) -> bool:
    """fsutil's answer: 'Volume - D: is NOT Dirty' is clean; anything else (dirty, an error) is not."""
    return "is NOT Dirty" in text


def check_disks() -> dict:
    p = subprocess.run(["fsutil", "dirty", "query", "D:"], capture_output=True, text=True)
    if p.returncode != 0 or not dirty_says_clean(p.stdout):
        raise SystemExit(f"refused: D: dirty query says {p.stdout.strip() or p.stderr.strip()!r}")
    free = {d: shutil.disk_usage(f"{d}:/").free / 2 ** 30 for d in ("C", "D")}
    low = {d: round(f, 1) for d, f in free.items() if f <= MIN_FREE_GB}
    if low:
        raise SystemExit(f"refused: free disk at or under {MIN_FREE_GB} GB: {low}")
    return {"d_clean": True, "free_gb": {d: round(f, 1) for d, f in free.items()}}


@contextlib.contextmanager
def heavy(purpose: str, enabled: bool = True, poll_s: float = 30.0):
    if not enabled:
        yield {"lock": False}
        return
    disks = check_disks()
    while True:
        if LOCK.exists():
            try:
                held = parse_lock(LOCK.read_text(encoding="utf-8"))
            except OSError:
                held = {}
            pid = held.get("pid")
            if pid is not None and str(pid).isdigit() and not pid_alive(int(pid)):
                print(f"HEAVY.lock names dead pid {pid}: stale, cleared", flush=True)
                LOCK.unlink(missing_ok=True)
            else:
                print(f"HEAVY.lock held by {held}; waiting", flush=True)
                time.sleep(poll_s)
            continue
        try:
            fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(lock_text(purpose, os.getpid()))
        break
    print(f"HEAVY.lock taken: {purpose} (pid {os.getpid()}); disks {disks['free_gb']}", flush=True)
    try:
        yield {"lock": True, **disks}
    finally:
        try:
            if LOCK.exists() and str(parse_lock(LOCK.read_text(encoding="utf-8")).get("pid")) == str(os.getpid()):
                LOCK.unlink()
                print("HEAVY.lock released", flush=True)
        except OSError as e:
            print(f"HEAVY.lock release failed: {e}", flush=True)
