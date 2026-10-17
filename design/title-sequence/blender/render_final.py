"""The overnight final: the shared core once (frames 0..1085), then each film's record window (1086..1151),
in module chunks, resumable, under the machine governor. Then the engine-side assembly of each film's 57 s.

    python design/title-sequence/blender/render_final.py                    # everything still missing
    python design/title-sequence/blender/render_final.py --records S-130    # one film's window only

Outputs (D:, per founder ruling 2026-10-17; the .blend is copied to C: as well):
    D:/document-media/title-sequence/renders/final/core/{exr,png}/####.{exr,png}
    D:/document-media/title-sequence/renders/final/<record>/{exr,png}/####.{exr,png}
    D:/document-media/title-sequence/masters/title-v1-<record>.{mkv,mov}
Log: D:/document-media/title-sequence/renders/final/render-log.jsonl (one line per chunk, per re-render, per encode).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
CFG = json.loads((HERE / "title.json").read_text(encoding="utf-8"))
BL = "D:/document-media/tools/blender-4.4.3-windows-x64/blender.exe"
PY = "C:/Users/aacri/document-work/.venv/Scripts/python.exe"
MEDIA = Path(CFG["paths"]["media"])
FINAL = MEDIA / "renders" / "final"
MASTERS = MEDIA / "masters"
BLEND_C = Path("C:/Users/aacri/document-work/title-sequence/blend")
LOCK = Path("C:/Users/aacri/document-work/.heavy.lock")
LOG = FINAL / "render-log.jsonl"
RECORD_START = 1086                       # frames from here on can show the record plate: rendered per film
LAST = CFG["machine_last_frame"]


def log(**kw):
    kw["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(kw) + "\n")
    print(json.dumps(kw), flush=True)


def d_dirty() -> bool:
    out = subprocess.run(["fsutil", "dirty", "query", "D:"], capture_output=True, text=True).stdout
    return "NOT Dirty" not in out


def blockers() -> list[str]:
    """Jobs that may not overlap a render (rule 13): a pytest gate, a film render, Orpheus, another Blender."""
    ps = subprocess.run(["powershell", "-NoProfile", "-Command",
                         "Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId)`t$($_.Name)`t$($_.CommandLine)\" }"],
                        capture_output=True, text=True).stdout
    found = []
    for line in ps.splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 3:
            continue
        pid, name, cmd = parts
        if int(pid) == os.getpid():
            continue
        c = cmd.lower()
        if name.lower() == "python.exe" and ("-m pytest" in c or "studio.engine.render" in c):
            found.append(f"{name} {pid}: {cmd[:90]}")
        elif name.lower() == "blender.exe":
            found.append(f"{name} {pid}")
    wsl = subprocess.run(["wsl", "-l", "--running"], capture_output=True).stdout.decode("utf-16-le", "ignore")
    if "orpheus" in wsl.lower() or ("running" not in wsl.lower() and "ubuntu" in wsl.lower()):
        pass
    try:
        orph = subprocess.run(["wsl", "-e", "ps", "-eo", "args"], capture_output=True, text=True, timeout=20).stdout
        if any("orpheus" in l.lower() for l in orph.splitlines()):
            found.append("orpheus (WSL)")
    except Exception:  # noqa: BLE001  WSL not running: nothing in it
        pass
    return found


def wait_clear():
    t0 = time.time()
    while True:
        b = blockers()
        if not b:
            if time.time() - t0 > 1:
                log(event="clear", waited_s=round(time.time() - t0))
            return
        if LOCK.exists() and "title-sequence final" in LOCK.read_text(encoding="utf-8", errors="ignore"):
            LOCK.unlink()                 # release while we wait: we are not rendering
        print(f"waiting: {b}", flush=True)
        time.sleep(30)


def take_lock(what: str):
    if LOCK.exists():
        held = LOCK.read_text(encoding="utf-8", errors="ignore")
        if "title-sequence final" not in held:
            log(event="lock-held-by-other", holder=held.strip())
            while LOCK.exists():
                time.sleep(30)
    LOCK.write_text(f"title-sequence final {what} pid {os.getpid()} {time.strftime('%Y-%m-%dT%H:%M:%S')}\n", encoding="utf-8")


def build(record: str, png_dir: Path) -> Path:
    out = MEDIA / "blend" / f"title-{record}-final.blend"
    r = subprocess.run([BL, "--background", "--factory-startup", "--python", str(HERE / "build_scene.py"), "--",
                        "--record", record, "--profile", "final", "--out", str(out), "--png", str(png_dir).replace("\\", "/") + "/"],
                       capture_output=True, text=True, cwd=REPO)
    if r.returncode != 0 or "provenance:" not in r.stdout:
        sys.exit(f"build failed for {record}:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
    chk = subprocess.run([BL, "--background", str(out), "--python", str(HERE / "check_title.py")], capture_output=True, text=True)
    if "check_title: ok" not in chk.stdout:
        sys.exit(f"provenance check failed for {record}:\n{chk.stdout[-2000:]}")
    BLEND_C.mkdir(parents=True, exist_ok=True)
    shutil.copy2(out, BLEND_C / out.name)                  # founder ruling: a copy of the .blend on C:
    log(event="built", record=record, blend=str(out), blend_c=str(BLEND_C / out.name), mb=round(out.stat().st_size / 1e6, 1))
    return out


def chunks(lo: int, hi: int):
    """Module chunks inside [lo, hi]."""
    for m in CFG["modules"]:
        a, b = max(lo, m["start"]), min(hi, m["end"] - 1)
        if a <= b:
            yield m["id"], a, b


def missing(d: Path, a: int, b: int) -> list[int]:
    out = []
    for f in range(a, b + 1):
        e, p = d / "exr" / f"{f:04d}.exr", d / "png" / f"{f:04d}.png"
        if not (e.exists() and e.stat().st_size > 0 and p.exists() and p.stat().st_size > 0):
            out.append(f)
    return out


def render_range(blend: Path, d: Path, label: str, a: int, b: int):
    (d / "exr").mkdir(parents=True, exist_ok=True)
    (d / "png").mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        todo = missing(d, a, b)
        if not todo:
            return
        rerender = attempt > 0
        for f in todo:                                     # placeholders and half-written pairs go; the frame is redone
            for p in (d / "exr" / f"{f:04d}.exr", d / "png" / f"{f:04d}.png"):
                if p.exists():
                    p.unlink()
        if d_dirty():
            sys.exit("D: is dirty: stopping before writing (check the drive; do not render on it)")
        if shutil.disk_usage("D:/").free < 20e9:
            sys.exit("D: has under 20 GB free: stopping")
        wait_clear()
        take_lock(f"{label} {a}-{b}")
        t0 = time.time()
        args = [BL, "--background", str(blend), "--python", str(HERE / "gpu.py"), "-o", str(d / "exr" / "####"), "-F", "OPEN_EXR"]
        if rerender or len(todo) < (b - a + 1):
            args += ["-f", ",".join(str(f) for f in todo)]
        else:
            args += ["-s", str(a), "-e", str(b), "-a"]
        r = subprocess.run(args, capture_output=True, text=True)
        LOCK.unlink(missing_ok=True)
        secs = time.time() - t0
        times = [ln for ln in r.stdout.splitlines() if ln.startswith("Time:")]
        crashed = r.returncode != 0 or "EXCEPTION" in r.stdout
        if "gpu.py: rendering on" not in r.stdout:
            sys.exit(f"{label}: the render did not confirm an OptiX device; stopping rather than render on the CPU")
        log(event="rerender" if rerender else "chunk", label=label, frames=f"{a}-{b}", n=len(todo),
            redone=todo if rerender else None, rc=r.returncode, crashed=crashed, seconds=round(secs),
            s_per_frame=round(secs / max(1, len(todo)), 1), last_times=times[-2:])
        if crashed:
            (FINAL / f"crash-{label}-{a}.log").write_text(r.stdout[-20000:] + r.stderr[-5000:], encoding="utf-8")
    left = missing(d, a, b)
    if left:
        sys.exit(f"{label} {a}-{b}: frames still missing after 3 attempts: {left}")


def assemble(record: str):
    MASTERS.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    stem = MASTERS / f"title-v1-{record}"
    subprocess.run([PY, str(HERE / "assemble.py"), "--frames", str(FINAL / record / "png"), "--core", str(FINAL / "core" / "png"),
                    "--record", record, "--size", "1920x1080", "--master", str(stem)], check=True, cwd=REPO)
    log(event="assembled", record=record, mkv=f"{stem}.mkv", mov=f"{stem}.mov", seconds=round(time.time() - t0),
        mkv_mb=round(Path(f"{stem}.mkv").stat().st_size / 1e6), mov_mb=round(Path(f"{stem}.mov").stat().st_size / 1e6))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", default="S-130,S-16928,C20-METAR-0851")
    ap.add_argument("--skip-core", action="store_true")
    a = ap.parse_args()
    if d_dirty():
        sys.exit("D: is dirty before the run: not rendering")
    log(event="start", dirty_D=False, records=a.records)
    t_all = time.time()
    if not a.skip_core:
        blend = build("S-130", FINAL / "core" / "png")
        for mid, s, e in chunks(0, RECORD_START - 1):
            render_range(blend, FINAL / "core", f"core-{mid}", s, e)
    for rec in a.records.split(","):
        blend = build(rec, FINAL / rec / "png")
        render_range(blend, FINAL / rec, f"{rec}-M10M11", RECORD_START, LAST)
        assemble(rec)
    log(event="done", dirty_D=d_dirty(), hours=round((time.time() - t_all) / 3600, 2))


if __name__ == "__main__":
    main()
