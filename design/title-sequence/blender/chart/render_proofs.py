"""Title B "Chart": build and render proofs P1 and P2 under the machine governor, then encode, sheet and measure.

    python design/title-sequence/blender/chart/render_proofs.py --proofs p2,p1      # the proof profile, both
    python design/title-sequence/blender/chart/render_proofs.py --proofs p1 --only-measure
    python design/title-sequence/blender/chart/render_proofs.py --still p1:959 --calib --lamp 70   # one small frame

Rules (WG-4): one render at a time; before each, both C:/Users/aacri/document-work/HEAVY.lock and .heavy.lock are
checked and any other Blender, film render, pytest or Orpheus is waited out (polled every 3 minutes); then HEAVY.lock
names this job and is deleted the moment the render ends, failure included. Every Cycles render runs gpu.py (OptiX
only). D: must not be dirty. Frames, mp4s, sheets and logs go to D:/document-media/title-sequence/chart/.

P1's A7 test reuses studio.engine.titles.record_difference (the A40 lint's own measure: 96 x 54 box low-pass, mean
absolute difference, marks masked) on the hold frame twice: on the whole frame against the scan held whole
(GRAMMAR 7.2 HOLD fit, film black around it) as the lint reads a master, and on the record's own rectangle in the
frame against the scan.
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
MEDIA = Path("D:/document-media/title-sequence/chart")
LOCKS = [Path("C:/Users/aacri/document-work/HEAVY.lock"), Path("C:/Users/aacri/document-work/.heavy.lock")]
MY_LOCK = LOCKS[0]
LOG = MEDIA / "render-log.jsonl"
NAMES = {"p1": "p1-record-hold-v2", "p2": "p2-unroll-v2"}

sys.path.insert(0, str(HERE))
import kinematics as K  # noqa: E402


def log(**kw):
    kw["at"] = dt.datetime.now().isoformat(timespec="seconds")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(kw) + "\n")
    print(json.dumps(kw), flush=True)


def d_dirty() -> bool:
    out = subprocess.run(["fsutil", "dirty", "query", "D:"], capture_output=True, text=True).stdout
    return "NOT Dirty" not in out


def _pid_alive(pid: int) -> bool:
    r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in r


def blockers() -> list[str]:
    found = []
    for lk in LOCKS:
        if lk.exists():
            txt = lk.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r'"pid"\s*:\s*(\d+)', txt) or re.search(r"pid (\d+)", txt)
            if m is None or _pid_alive(int(m.group(1))):
                found.append(f"{lk.name}: {txt.strip()[:120]}")
    ps = subprocess.run(["powershell", "-NoProfile", "-Command",
                         "Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId)`t$($_.Name)`t$($_.CommandLine)\" }"],
                        capture_output=True, text=True).stdout
    me = os.getpid()
    for line in ps.splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 3 or not parts[0].isdigit() or int(parts[0]) == me:
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
    except Exception:  # noqa: BLE001  WSL not running
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


def render(blend: Path, out_dir: Path, frames: list[int], label: str) -> list[float]:
    """One Blender render under HEAVY.lock; returns per-frame seconds parsed from Blender's own 'Time:' lines."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if d_dirty():
        sys.exit("D: is dirty: not rendering")
    if shutil.disk_usage("D:/").free < 20e9:
        sys.exit("D: has under 20 GB free: not rendering")
    wait_clear()
    args = [BL, "--background", str(blend), "--python", str(REPO / "design/title-sequence/blender/gpu.py"),
            "-o", str(out_dir / "####"), "-F", "PNG"]
    if frames == list(range(frames[0], frames[-1] + 1)) and len(frames) > 1:
        args += ["-s", str(frames[0]), "-e", str(frames[-1]), "-a"]
    else:
        args += ["-f", ",".join(map(str, frames))]
    t0 = time.time()
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    MY_LOCK.write_text(json.dumps({"group": "WG-4", "job": f"chart proofs P1+P2 ({label})", "pid": proc.pid,
                                   "started": dt.datetime.now().isoformat(timespec="seconds")}), encoding="utf-8")
    lines = []
    try:
        for ln in proc.stdout:
            lines.append(ln)
            if ln.startswith(("Saved:", "gpu.py", "Error", "EXCEPTION")) or "Time:" in ln[:12]:
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
    times = [float(m.group(1)) * 60 + float(m.group(2))
             for m in re.finditer(r"^\s*Time: (\d+):(\d+\.\d+) \(Saving", text, re.M)]
    log(event="render", label=label, frames=f"{frames[0]}-{frames[-1]}", n=len(frames), rc=rc,
        seconds=round(time.time() - t0, 1), per_frame_s=[round(t, 2) for t in times],
        mean_s_per_frame=round(sum(times) / len(times), 2) if times else None)
    if rc != 0:
        sys.exit(f"{label}: blender exited {rc}")
    return times


def build(proof: str, extra: list[str]) -> tuple[Path, dict]:
    blend = MEDIA / "blend" / f"chart-{proof}{'-calib' if '--calib' in extra else ''}.blend"
    r = subprocess.run([BL, "--background", "--factory-startup", "--python", str(HERE / "chart_scene.py"), "--",
                        "--proof", proof, "--out", str(blend).replace("\\", "/")] + extra,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=REPO)
    m = re.search(r"^CHART-BUILD (.*)$", r.stdout, re.M)
    if r.returncode != 0 or not m:
        sys.exit(f"build {proof} failed:\n{r.stdout[-3000:]}\n{r.stderr[-2000:]}")
    info = json.loads(m.group(1))
    log(event="built", proof=proof, blend=str(blend), mb=round(blend.stat().st_size / 1e6, 1), info=info)
    return blend, info


def encode(frames_dir: Path, f0: int, mp4: Path):
    mp4.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-v", "error", "-framerate", "24", "-start_number", str(f0), "-i", str(frames_dir / "%04d.png"),
           "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", "-profile:v", "high",
           "-movflags", "+faststart", "-r", "24", str(mp4)]
    subprocess.run(cmd, check=True)
    pr = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries",
                         "stream=width,height,pix_fmt,r_frame_rate,nb_read_frames,codec_name", "-of", "json", str(mp4)],
                        capture_output=True, text=True).stdout
    log(event="encoded", mp4=str(mp4), mb=round(mp4.stat().st_size / 1e6, 2), probe=json.loads(pr)["streams"][0])


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
        x, y = 12 + (i % 3) * (tw + 12), 40 + 12 + (i // 3) * (th + 12)
        sheet.paste(im, (x, y))
        d.rectangle((x, y, x + 150, y + 30), fill=(18, 18, 18))
        d.text((x + 8, y + 5), f"f{f} ({f / 24:.2f} s)", fill=(237, 226, 207), font=font)
    sheet.save(out, quality=90)
    log(event="contact-sheet", file=str(out), frames=pick)


def measure_p1(frames_dir: Path, info: dict) -> dict:
    """A7 on the hold: the A40 lint's own measure, whole frame and on the record's rectangle."""
    import numpy as np
    from PIL import Image
    sys.path.insert(0, str(REPO))
    from studio.engine import titles as T
    rec = json.loads((HERE.parent / "title.json").read_text(encoding="utf-8"))["records"][info["record"]]
    man = json.loads((MEDIA / "tex-manifest.json").read_text(encoding="utf-8"))
    scan = man[rec["tex"]]["tex"]["file"]
    out = {"record": info["record"], "scan": scan, "limit": T.RECORD_LIMIT, "by_frame": {}}
    for f in (K.SLIDE_STOP, K.SLIDE_STOP + 5, info["frames"][1]):
        arr = np.asarray(Image.open(frames_dir / f"{f:04d}.png").convert("RGB"))
        H, W = arr.shape[:2]
        w, h = info["sheet_px"]
        x0, y0 = (W - w) / 2, (H - h) / 2
        crop = arr[round(y0):round(y0 + h), round(x0):round(x0 + w)]
        out["by_frame"][f] = {"whole_frame_vs_hold_fit": round(T.record_difference(arr, scan), 3),
                              "record_rect_vs_scan": round(T.record_difference(crop, scan), 3),
                              "rect_px": [round(x0, 1), round(y0, 1), round(w, 1), round(h, 1)]}
    log(event="a7", **out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proofs", default="p2,p1")
    ap.add_argument("--only-measure", action="store_true")
    ap.add_argument("--still", default="")            # p1:959 or p2:544,560
    ap.add_argument("--calib", action="store_true")
    ap.add_argument("--lamp", default="")
    ap.add_argument("--lamp-end", default="")
    a = ap.parse_args()
    extra = (["--calib", "1"] if a.calib else []) + (["--lamp", a.lamp] if a.lamp else [])         + (["--lamp_end", a.lamp_end] if a.lamp_end else [])
    if a.still:
        proof, fr = a.still.split(":")
        blend, info = build(proof, extra)
        frames = [int(x) for x in fr.split(",")]
        d = MEDIA / "frames" / f"still-{proof}{'-calib' if a.calib else ''}{'-' + a.lamp if a.lamp else ''}{'-e' + a.lamp_end if a.lamp_end else ''}"
        for f in frames:
            (d / f"{f:04d}.png").unlink(missing_ok=True)
        render(blend, d, frames, f"still-{proof}")
        if proof == "p1" and not a.calib:
            measure_p1(d, info) if all((d / f"{f:04d}.png").exists() for f in (K.SLIDE_STOP, K.SLIDE_STOP + 5, info["frames"][1])) else None
        return
    for proof in a.proofs.split(","):
        blend, info = build(proof, extra)
        f0, f1 = info["frames"]
        frames = list(range(f0, f1 + 1))
        d = MEDIA / "frames" / f"{proof}-v2"
        if not a.only_measure:
            render(blend, d, frames, proof)
        name = NAMES[proof]
        encode(d, f0, MEDIA / "proofs" / f"{name}.mp4")
        contact_sheet(d, frames, MEDIA / "proofs" / f"{name}-contact.jpg",
                      f"Chart proof {proof.upper()}: {name}, title frames {f0}-{f1}, Cycles proof profile")
        if proof == "p1":
            measure_p1(d, info)


if __name__ == "__main__":
    try:
        main()
    finally:
        if MY_LOCK.exists() and '"WG-4"' in MY_LOCK.read_text(encoding="utf-8", errors="ignore"):
            MY_LOCK.unlink(missing_ok=True)
