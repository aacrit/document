"""The Run: build, render, sound and encode the two proofs under the machine governor.

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/render_run.py --proofs latch,galley
    ... --still latch:110,121,150 [--calib]          # a few frames (calib: 640x360, 48 samples)
    ... --proofs latch --only-encode                 # re-sound and re-encode from existing frames

Before each render: D: must not be dirty and must have 20 GB free; both C:/Users/aacri/document-work/HEAVY.lock and
.heavy.lock are checked and any other Blender, film render, pytest or Orpheus is waited out (polled every 3 min);
then HEAVY.lock names this job (WG-4, the Blender PID) and is deleted the moment the render ends, failure included.
Every Cycles render runs gpu.py (OptiX only). One render at a time. Outputs, all on D:, under
D:/document-media/title-sequence/run/: frames/<proof>/####.png, proofs/<name>.mp4 (H.264 yuv420p CRF 18, 24 fps,
AAC from foley.py), proofs/<name>-contact.jpg, render-log.jsonl (per-frame seconds from Blender's own lines).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
BL = "D:/document-media/tools/blender-4.4.3-windows-x64/blender.exe"
VPY = "D:/document-media/tools/run-venv/Scripts/python.exe"
MEDIA = Path("D:/document-media/title-sequence/run")
LOCKS = [Path("C:/Users/aacri/document-work/HEAVY.lock"), Path("C:/Users/aacri/document-work/.heavy.lock")]
MY_LOCK = LOCKS[0]
LOG = MEDIA / "render-log.jsonl"
NAMES = {"latch": "latch", "galley": "galley"}
FRAMES = {"latch": (96, 167), "galley": (456, 527)}


def log(**kw):
    kw["at"] = dt.datetime.now().isoformat(timespec="seconds")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(kw) + "\n")
    print(json.dumps(kw), flush=True)


TMP = Path("D:/document-media/title-sequence/run/tmp")
C_MIN_GB = 6.0


def d_env() -> dict:
    """The environment for Blender and helpers: temp files on D:, never C: (C: is nearly full)."""
    TMP.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    for k in ("TEMP", "TMP", "TMPDIR"):
        env[k] = str(TMP)
    return env


RAM_MIN_GB = 6.0


def c_free_ok() -> bool:
    return shutil.disk_usage("C:/").free / 1e9 >= C_MIN_GB


def ram_free_gb() -> float:
    o = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory"], capture_output=True, text=True).stdout
    return int(o.strip() or 0) / 1024 / 1024


def machine_ok() -> tuple[bool, str]:
    """The coordinator's gate before every heavy step: C: at least 6 GB free and at least 6 GB of RAM free."""
    c = shutil.disk_usage("C:/").free / 1e9
    r = ram_free_gb()
    return (c >= C_MIN_GB and r >= RAM_MIN_GB), f"C: {c:.1f} GB free, RAM {r:.1f} GB free"


def heavy(cmd: list[str], label: str, cwd=None) -> int:
    """Run one heavy job (a MuJoCo bake, a Blender build or render) under HEAVY.lock: blockers waited out, C: and RAM
    checked (waits while short), the lock named for the job and removed the moment it ends."""
    while True:
        wait_clear()
        ok, why = machine_ok()
        if ok:
            break
        print(f"{dt.datetime.now():%H:%M:%S} waiting on the machine: {why}", flush=True)
        time.sleep(180)
    proc = subprocess.Popen(cmd, cwd=cwd, env=d_env())
    MY_LOCK.write_text(json.dumps({"group": "WG-4", "job": f"The Run ({label})", "pid": proc.pid,
                                   "started": dt.datetime.now().isoformat(timespec="seconds")}), encoding="utf-8")
    try:
        rc = proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
        MY_LOCK.unlink(missing_ok=True)
    log(event="heavy", label=label, rc=rc, machine=machine_ok()[1])
    return rc


def d_dirty() -> bool:
    return "NOT Dirty" not in subprocess.run(["fsutil", "dirty", "query", "D:"], capture_output=True, text=True).stdout


def _alive(pid: int) -> bool:
    return str(pid) in subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout


def blockers() -> list[str]:
    found = []
    for lk in LOCKS:
        if lk.exists():
            txt = lk.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r'"pid"\s*:\s*(\d+)', txt) or re.search(r"pid (\d+)", txt)
            if m is None or _alive(int(m.group(1))):
                found.append(f"{lk.name}: {txt.strip()[:120]}")
    ps = subprocess.run(["powershell", "-NoProfile", "-Command",
                         "Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId)`t$($_.Name)`t$($_.CommandLine)\" }"],
                        capture_output=True, text=True).stdout
    for line in ps.splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 3 or not parts[0].isdigit() or int(parts[0]) == os.getpid():
            continue
        pid, name, cmd = parts
        c, n = cmd.lower(), name.lower()
        if n == "blender.exe":
            found.append(f"blender {pid}")
        elif n.startswith("python") and ("pytest" in c or "studio.engine.render" in c or "render_final.py" in c):
            found.append(f"{name} {pid}: {cmd[:100]}")
        elif "orpheus" in c:
            found.append(f"orpheus {pid}")
    try:
        o = subprocess.run(["wsl", "-e", "ps", "-eo", "args"], capture_output=True, text=True, timeout=20).stdout
        if any("orpheus" in ln.lower() for ln in o.splitlines()):
            found.append("orpheus (WSL)")
    except Exception:  # noqa: BLE001
        pass
    return found


def wait_clear():
    t0 = time.time()
    while True:
        b = blockers()
        if not b:
            if time.time() - t0 > 5:
                log(event="clear", waited_s=round(time.time() - t0))
            return
        print(f"{dt.datetime.now():%H:%M:%S} waiting: {b}", flush=True)
        time.sleep(180)


def build(proof: str, extra: list[str]) -> tuple[Path, dict]:
    blend = MEDIA / "blend" / f"run-{proof}{'-calib' if '--calib' in extra else ''}.blend"
    r = subprocess.run([BL, "--background", "--factory-startup", "--python", str(HERE / "run_scene.py"), "--",
                        "--proof", proof, "--out", str(blend).replace("\\", "/")] + extra,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=REPO)
    m = re.search(r"^RUN-BUILD (.*)$", r.stdout, re.M)
    if r.returncode != 0 or not m:
        sys.exit(f"build {proof} failed:\n{r.stdout[-3000:]}\n{r.stderr[-2000:]}")
    info = json.loads(m.group(1))
    log(event="built", proof=proof, blend=str(blend), mb=round(blend.stat().st_size / 1e6, 1), info=info)
    return blend, info


def render(blend: Path, out_dir: Path, frames: list[int], label: str) -> list[float]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if d_dirty():
        sys.exit("D: is dirty: not rendering")
    if shutil.disk_usage("D:/").free < 20e9:
        sys.exit("D: has under 20 GB free: not rendering")
    if not c_free_ok():
        sys.exit(f"C: has under {C_MIN_GB} GB free: not rendering (report to the coordinator)")
    while True:
        wait_clear()
        ok, why = machine_ok()
        if ok:
            break
        print(f"{dt.datetime.now():%H:%M:%S} waiting on the machine: {why}", flush=True)
        time.sleep(180)
    args = [BL, "--background", str(blend), "--python", str(REPO / "design/title-sequence/blender/gpu.py"),
            "-o", str(out_dir / "####"), "-F", "PNG"]
    if len(frames) > 1 and frames == list(range(frames[0], frames[-1] + 1)):
        args += ["-s", str(frames[0]), "-e", str(frames[-1]), "-a"]
    else:
        args += ["-f", ",".join(map(str, frames))]
    t0 = time.time()
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                            env=d_env())
    MY_LOCK.write_text(json.dumps({"group": "WG-4", "job": f"The Run ({label})", "pid": proc.pid,
                                   "started": dt.datetime.now().isoformat(timespec="seconds")}), encoding="utf-8")
    lines = []
    try:
        for ln in proc.stdout:
            lines.append(ln)
            if ln.startswith(("Saved:", "gpu.py", "Error", "EXCEPTION")):
                print("   " + ln.rstrip(), flush=True)
        rc = proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
        MY_LOCK.unlink(missing_ok=True)
    text = "".join(lines)
    (out_dir.parent / f"blender-{label}.log").write_text(text[-200000:], encoding="utf-8")
    if "gpu.py: rendering on" not in text:
        sys.exit(f"{label}: no OptiX confirmation; refusing a CPU render")
    times = [float(m.group(1)) * 60 + float(m.group(2)) for m in re.finditer(r"^\s*Time: (\d+):(\d+\.\d+) \(Saving", text, re.M)]
    log(event="render", label=label, frames=f"{frames[0]}-{frames[-1]}", n=len(frames), rc=rc,
        seconds=round(time.time() - t0, 1), per_frame_s=[round(t, 2) for t in times],
        mean_s_per_frame=round(sum(times) / len(times), 2) if times else None)
    if rc != 0:
        sys.exit(f"{label}: blender exited {rc}")
    return times


def encode(frames_dir: Path, f0: int, wav: Path | None, mp4: Path):
    mp4.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-v", "error", "-framerate", "24", "-start_number", str(f0), "-i", str(frames_dir / "%04d.png")]
    if wav:
        cmd += ["-i", str(wav), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest"]
    else:
        cmd += ["-an"]
    cmd += ["-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", "-profile:v", "high",
            "-movflags", "+faststart", "-r", "24", str(mp4)]
    subprocess.run(cmd, check=True)
    pr = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_entries",
                         "stream=codec_type,codec_name,width,height,pix_fmt,r_frame_rate,nb_read_frames,sample_rate,channels",
                         "-of", "json", str(mp4)], capture_output=True, text=True).stdout
    log(event="encoded", mp4=str(mp4), mb=round(mp4.stat().st_size / 1e6, 2), streams=json.loads(pr)["streams"])


def contact_sheet(frames_dir: Path, frames: list[int], out: Path, title: str):
    from PIL import Image, ImageDraw, ImageFont
    pick = [frames[round(i * (len(frames) - 1) / 5)] for i in range(6)]
    tw, th = 640, 360
    sheet = Image.new("RGB", (3 * tw + 4 * 12, 2 * th + 3 * 12 + 40), (18, 18, 18))
    d = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=20)
    d.text((12, 10), title, fill=(237, 226, 207), font=font)
    for i, f in enumerate(pick):
        im = Image.open(frames_dir / f"{f:04d}.png").convert("RGB").resize((tw, th), Image.LANCZOS)
        x, y = 12 + (i % 3) * (tw + 12), 52 + (i // 3) * (th + 12)
        sheet.paste(im, (x, y))
        d.rectangle((x, y, x + 150, y + 30), fill=(18, 18, 18))
        d.text((x + 8, y + 5), f"f{f} ({f / 24:.2f} s)", fill=(237, 226, 207), font=font)
    sheet.save(out, quality=90)
    log(event="contact-sheet", file=str(out), frames=pick)


def foley(proof: str) -> Path:
    out = MEDIA / "proofs" / f"{NAMES[proof]}-foley.wav"
    r = subprocess.run([VPY, str(HERE / "foley.py"), "--proof", proof, "--out", str(out)], capture_output=True, text=True, cwd=REPO)
    if r.returncode != 0:
        sys.exit(f"foley {proof} failed:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
    log(event="foley", proof=proof, wav=str(out), report=r.stdout.strip().splitlines()[-1][:600])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proofs", default="latch,galley")
    ap.add_argument("--still", default="")
    ap.add_argument("--calib", action="store_true")
    ap.add_argument("--only-encode", action="store_true")
    ap.add_argument("--lamp", default="")
    a = ap.parse_args()
    extra = (["--calib", "1"] if a.calib else []) + (["--lamp", a.lamp] if a.lamp else [])
    if a.still:
        proof, fr = a.still.split(":")
        blend, _ = build(proof, extra)
        frames = [int(x) for x in fr.split(",")]
        d = MEDIA / "frames" / f"still-{proof}{'-calib' if a.calib else ''}"
        for f in frames:
            (d / f"{f:04d}.png").unlink(missing_ok=True)
        render(blend, d, frames, f"still-{proof}")
        return
    for proof in a.proofs.split(","):
        f0, f1 = FRAMES[proof]
        frames = list(range(f0, f1 + 1))
        d = MEDIA / "frames" / proof
        if not a.only_encode:
            blend, _ = build(proof, extra)
            render(blend, d, frames, proof)
        wav = foley(proof)
        encode(d, f0, wav, MEDIA / "proofs" / f"{NAMES[proof]}.mp4")
        contact_sheet(d, frames, MEDIA / "proofs" / f"{NAMES[proof]}-contact.jpg",
                      f"The Run, proof '{NAMES[proof]}', title frames {f0}-{f1}, Cycles proof profile")


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--heavy":
        # render_run.py --heavy <label> -- <command...>: one heavy job under the lock
        lbl = sys.argv[2]
        sys.exit(heavy(sys.argv[sys.argv.index("--") + 1:], lbl))
    try:
        main()
    finally:
        if MY_LOCK.exists() and '"WG-4"' in MY_LOCK.read_text(encoding="utf-8", errors="ignore"):
            MY_LOCK.unlink(missing_ok=True)
