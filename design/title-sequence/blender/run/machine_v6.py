"""Title v6: the machine rules for every long job (house rule 13, the D: incident of 2026-10-10, and the bluescreen of
2026-10-26 21:38 under this ticket's gap check, a trimesh ray test that asked for 13 GiB).

`heavy(purpose)` is a context manager: it refuses when D: is dirty (`fsutil dirty query D:`), when C: or D: has
10 GB or less free, or when free RAM is under 6 GB; it caps this process's committed memory with a Windows job object
(MEM_CAP_GB, so an oversized allocation raises MemoryError in this process and the job fails cleanly instead of
starving the machine); it waits while HEAVY.lock names a live pid, clears a lock whose pid is dead, takes the lock
atomically with this process's real Windows pid, and releases it in a finally (only if the lock is still ours).
`batch_rows(bytes_per_row)` sizes every batch so no array passes 1 GiB (or an eighth of free RAM, if less).
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
MIN_FREE_RAM_GB = 6.0
MEM_CAP_GB = 8.0
MAX_ARRAY_BYTES = 1 << 30


class _MEMSTAT(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def free_ram_gb() -> float:
    st = _MEMSTAT()
    st.dwLength = ctypes.sizeof(_MEMSTAT)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
        raise OSError("GlobalMemoryStatusEx failed")
    return st.ullAvailPhys / 2 ** 30


def batch_rows(bytes_per_row: int, free_gb: float | None = None, max_bytes: int = MAX_ARRAY_BYTES) -> int:
    """Rows per batch so a batch's array stays under max_bytes and under an eighth of free RAM."""
    free = (free_ram_gb() if free_gb is None else free_gb) * 2 ** 30
    return max(1, int(min(max_bytes, free / 8) // max(1, bytes_per_row)))


class _BASIC(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", ctypes.c_ulong), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_ulong),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_ulong), ("SchedulingClass", ctypes.c_ulong)]


class _IO(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in ("R", "W", "O", "RB", "WB", "OB")]


class _EXT(ctypes.Structure):
    _fields_ = [("Basic", _BASIC), ("Io", _IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


_JOB = None


def cap_memory(gb: float = MEM_CAP_GB) -> dict:
    """Put this process in a job object whose per-process committed-memory limit is `gb`: past it, allocations fail
    (numpy raises MemoryError) and only this process is affected. Once per process; the limit cannot be raised."""
    global _JOB
    if _JOB is not None:
        return {"cap_gb": _JOB[1], "already": True}
    k = ctypes.windll.kernel32
    k.CreateJobObjectW.restype = ctypes.c_void_p
    k.GetCurrentProcess.restype = ctypes.c_void_p
    job = k.CreateJobObjectW(None, None)
    if not job:
        raise OSError("CreateJobObjectW failed")
    info = _EXT()
    info.Basic.LimitFlags = 0x00000100                         # JOB_OBJECT_LIMIT_PROCESS_MEMORY
    info.ProcessMemoryLimit = int(gb * 2 ** 30)
    if not k.SetInformationJobObject(ctypes.c_void_p(job), 9, ctypes.byref(info), ctypes.sizeof(info)):
        raise OSError(f"SetInformationJobObject failed ({k.GetLastError()})")
    if not k.AssignProcessToJobObject(ctypes.c_void_p(job), ctypes.c_void_p(k.GetCurrentProcess())):
        raise OSError(f"AssignProcessToJobObject failed ({k.GetLastError()})")
    _JOB = (job, gb)
    return {"cap_gb": gb, "already": False}


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
    ram = free_ram_gb()
    if ram < MIN_FREE_RAM_GB:
        raise SystemExit(f"refused: free RAM {ram:.1f} GB (at least {MIN_FREE_RAM_GB} needed)")
    disks["free_ram_gb"] = round(ram, 1)
    disks["mem_cap"] = cap_memory()
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
    print(f"HEAVY.lock taken: {purpose} (pid {os.getpid()}); disks {disks['free_gb']} GB free, RAM "
          f"{disks['free_ram_gb']} GB free, process capped at {disks['mem_cap']['cap_gb']} GB", flush=True)
    try:
        yield {"lock": True, **disks}
    finally:
        try:
            if LOCK.exists() and str(parse_lock(LOCK.read_text(encoding="utf-8")).get("pid")) == str(os.getpid()):
                LOCK.unlink()
                print("HEAVY.lock released", flush=True)
        except OSError as e:
            print(f"HEAVY.lock release failed: {e}", flush=True)
