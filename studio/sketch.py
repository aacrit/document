"""Render a sketch film from a screenplay: Ken Burns moves on archival stills,
narration, one score cue, mixed and encoded to a web-ready MP4.

    python studio/sketch.py D:/document-media/maxwell-street

The film folder holds `dossier.json` (the ledger of licensed assets),
`screenplay.json` (written by Fable) and optionally `score.yaml` (note data in
void-history's score.py manifest format). Outputs land in `<film>/out/`:
`film.mp4`, `poster.jpg`, `sources.json`. Media never enters the repo (R-08).

Rules enforced here, before anything renders:
  - every shot cites an asset id that exists in the dossier, with a licence
    on the allowlist (public domain, CC0, CC-BY)
  (the narration ceiling it once enforced is lifted by GRAMMAR A17: narration
  is reported in sources.json as narration_share, never capped)

Moves are computed per frame with sub-pixel affine sampling (PIL), so there is
none of ffmpeg zoompan's integer-step jitter. A move is two framings,
`{"z": zoom, "x": cx, "y": cy}`: z = 1 is the largest 16:9 window that fits
the photograph, x and y the window centre in 0..1 image coordinates.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

W, H, FPS = 1280, 720, 30
AUDIO_RATE = 48000
LICENCES = {"public domain", "CC0", "CC-BY-2.0", "CC-BY-4.0"}  # CC BY requires the credit line, which sources.json carries
VOID_ROOT = Path(os.environ.get("VOID_ROOT", "C:/Users/aacri/claudeprojects/voidnews"))
# Every unit of work is timed into this ledger; the Director's Lens predicts
# from it (design/spec.md, "timing ledger"). Data, never committed.
TIMINGS = Path(os.environ.get("DOCUMENT_TIMINGS", Path.home() / "document-work" / "timings.jsonl"))


def machine() -> dict:
    """Conditions at the moment a unit finishes: GPU load, VRAM, temperature."""
    import platform
    m = {"cpu": platform.processor(), "cpus": os.cpu_count()}
    try:
        q = subprocess.run(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,temperature.gpu,clocks_throttle_reasons.active",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5).stdout.strip()
        name, util, mem, temp, thr = [x.strip() for x in q.split(",")]
        m.update(gpu=name, gpu_util=int(util), vram_mb=int(mem), gpu_temp_c=int(temp), throttle=thr)
    except Exception:
        pass
    return m


class Timer:
    """Appends one JSON record per unit of work to TIMINGS."""

    def __init__(self, film: Path):
        import time, uuid
        self.run = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        self.film = film.name
        TIMINGS.parent.mkdir(parents=True, exist_ok=True)

    def record(self, stage: str, unit: str, seconds: float, size: dict, **extra) -> None:
        import time
        rec = {"run": self.run, "film": self.film, "stage": stage, "unit": unit, "wall_s": round(seconds, 3),
               "size": size, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "renderer": "sketch.py", **machine(), **extra}
        with TIMINGS.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")


def fail(msg: str) -> None:
    raise SystemExit(f"sketch: {msg}")


def ffmpeg() -> str:
    exe = os.environ.get("DOCUMENT_FFMPEG") or shutil.which("ffmpeg")
    if not exe:
        base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Packages"
        hits = sorted(base.glob("Gyan.FFmpeg*/**/bin/ffmpeg.exe"))
        exe = str(hits[-1]) if hits else None
    if not exe:
        fail("ffmpeg not found (set DOCUMENT_FFMPEG)")
    return exe


def ease(t: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * min(1.0, max(0.0, t)))


def window(img_w: int, img_h: int, f: dict) -> tuple[float, float, float, float]:
    """The source rectangle (x0, y0, x1, y1) for framing f, clamped inside the image."""
    aspect = W / H
    bw, bh = (img_w, img_w / aspect) if img_w / img_h <= aspect else (img_h * aspect, img_h)
    z = max(1.0, float(f.get("z", 1.0)))
    ww, wh = bw / z, bh / z
    cx = min(max(float(f.get("x", 0.5)) * img_w, ww / 2), img_w - ww / 2)
    cy = min(max(float(f.get("y", 0.5)) * img_h, wh / 2), img_h - wh / 2)
    return cx - ww / 2, cy - wh / 2, cx + ww / 2, cy + wh / 2


def shot_frame(img: Image.Image, move: dict, t: float) -> np.ndarray:
    a = window(*img.size, move["from"])
    b = window(*img.size, move.get("to", move["from"]))
    e = ease(t)
    box = tuple(a[i] + (b[i] - a[i]) * e for i in range(4))
    out = img.transform((W, H), Image.Transform.EXTENT, box, resample=Image.Resampling.BICUBIC)
    return np.asarray(out, dtype=np.float32)


def load_still(path: Path) -> Image.Image:
    img = Image.open(path).convert("RGB")
    # Oversample small scans so a slow push never magnifies past ~1.3x.
    if img.width < W * 2:
        s = (W * 2) / img.width
        img = img.resize((round(img.width * s), round(img.height * s)), Image.Resampling.LANCZOS)
    return img


def timeline(shots: list[dict]) -> tuple[list[tuple[float, float]], float]:
    """Start and end of each shot. A dissolve overlaps the previous shot by its length."""
    spans, t = [], 0.0
    for i, s in enumerate(shots):
        overlap = float(s.get("dissolve", 0.0)) if i else 0.0
        start = max(0.0, t - overlap)
        end = start + float(s["dur"])
        spans.append((start, end))
        t = end
    return spans, t


def check(dossier: dict, play: dict) -> dict:
    assets = {a["id"]: a for a in dossier["assets"]}
    for s in play["shots"]:
        a = assets.get(s["asset"])
        if a is None:
            fail(f"shot {s['id']} cites {s['asset']}, which is not in the dossier")
        if a["licence"] not in LICENCES:
            fail(f"shot {s['id']}: asset {a['id']} licence {a['licence']!r} is not on the allowlist")
    return assets


def narrate(lines: list[dict], voice: str, speed: float, work: Path, timer: "Timer") -> list[tuple[float, np.ndarray]]:
    import time
    from kokoro_onnx import Kokoro
    kdir = Path.home() / ".cache/void-kokoro/model-files-v1.0"
    t0 = time.perf_counter()
    k = Kokoro(str(kdir / "kokoro-v1.0.int8.onnx"), str(kdir / "voices-v1.0.bin"))
    timer.record("narration", "model_load", time.perf_counter() - t0, {}, engine="kokoro-82m-int8-cpu")
    out = []
    for i, ln in enumerate(lines):
        t0 = time.perf_counter()
        samples, rate = k.create(ln["text"], voice=ln.get("voice", voice), speed=speed, lang="en-us")
        timer.record("narration", f"line:{i}", time.perf_counter() - t0,
                     {"words": len(ln["text"].split()), "audio_s": round(len(samples) / rate, 3)}, engine="kokoro-82m-int8-cpu")
        out.append((float(ln["at"]), resample(np.asarray(samples, dtype=np.float32), rate)))
    return out


def resample(x: np.ndarray, rate: int) -> np.ndarray:
    if rate == AUDIO_RATE:
        return x
    n = int(round(len(x) * AUDIO_RATE / rate))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def score_cue(film: Path, score: dict, work: Path) -> np.ndarray | None:
    manifest = film / "score.yaml"
    if not manifest.exists():
        return None
    py = VOID_ROOT / ".venv/Scripts/python.exe"
    wav = work / "score.wav"
    code = (
        "import sys, yaml; sys.path.insert(0, r'%s'); sys.path.insert(0, r'%s');"
        "import score as s; m = yaml.safe_load(open(r'%s', encoding='utf-8'));"
        "bad = s.validate_manifest(m); assert not bad, bad;"
        "s.write_wav(__import__('pathlib').Path(r'%s'), s.render_cue(m, %r, %r))"
    ) % (VOID_ROOT / "pipeline", VOID_ROOT / "pipeline/history", manifest, wav, score.get("cue", "theme"), score.get("era", "modern"))
    r = subprocess.run([str(py), "-c", code], capture_output=True, text=True)
    if r.returncode:
        fail(f"score render failed:\n{r.stderr[-2000:]}")
    import soundfile as sf
    x, rate = sf.read(str(wav), dtype="float32")
    if x.ndim > 1:
        x = x.mean(axis=1)
    return resample(x, rate)


def mix(total: float, voice: list[tuple[float, np.ndarray]], music: np.ndarray | None, score: dict) -> np.ndarray:
    n = int(math.ceil(total * AUDIO_RATE))
    v = np.zeros(n, np.float32)
    for at, x in voice:
        i = int(at * AUDIO_RATE)
        x = x[: max(0, n - i)]
        v[i : i + len(x)] += x
    out = v * 10 ** (-3 / 20)
    if music is not None:
        m = np.zeros(n, np.float32)
        i = int(float(score.get("at", 0)) * AUDIO_RATE)
        seg = music[: max(0, n - i)]
        m[i : i + len(seg)] = seg
        # Duck the score 9 dB under the voice, with 250 ms smoothing.
        env = (np.abs(v) > 1e-3).astype(np.float32)
        k = int(0.25 * AUDIO_RATE)
        env = np.convolve(env, np.ones(k, np.float32) / k, mode="same")
        env = np.clip(env * 4, 0, 1)
        gain = 10 ** (float(score.get("gain_db", -8)) / 20) * (1 - env * (1 - 10 ** (-9 / 20)))
        fade = int(2.5 * AUDIO_RATE)
        m[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
        out = out + m * gain
    peak = float(np.max(np.abs(out))) or 1.0
    return (out / max(1.0, peak / 0.89)).astype(np.float32)


def render(film: Path) -> None:
    import time
    timer = Timer(film)
    run_t0 = time.perf_counter()
    dossier = json.loads((film / "dossier.json").read_text(encoding="utf-8"))
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    assets = check(dossier, play)
    spans, total = timeline(play["shots"])
    total += float(play.get("tail_s", 0))
    out_dir = film / "out"
    out_dir.mkdir(exist_ok=True)

    with tempfile.TemporaryDirectory(dir=film) as tmp:
        work = Path(tmp)
        voice = narrate(play.get("narration", []), play.get("voice", "am_michael"), float(play.get("speed", 1.0)), work, timer)
        spoken = sum(len(x) for _, x in voice) / AUDIO_RATE
        t0 = time.perf_counter()
        cue = score_cue(film, play.get("score", {}), work)
        if cue is not None:
            timer.record("score", "cue", time.perf_counter() - t0, {"audio_s": round(len(cue) / AUDIO_RATE, 3)})
        t0 = time.perf_counter()
        audio = mix(total, voice, cue, play.get("score", {}))
        timer.record("mix", "film", time.perf_counter() - t0, {"audio_s": round(total, 3)})
        import soundfile as sf
        wav = work / "mix.wav"
        sf.write(str(wav), audio, AUDIO_RATE, subtype="PCM_16")

        t0 = time.perf_counter()
        stills = {s["asset"]: load_still(film / assets[s["asset"]]["file"]) for s in play["shots"]}
        timer.record("motion", "load_stills", time.perf_counter() - t0, {"stills": len(stills)})
        shot_s: dict[str, float] = {}
        shot_f: dict[str, int] = {}
        motion_t0 = time.perf_counter()
        enc = subprocess.Popen(
            [ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
             "-i", str(wav), "-c:v", "libx264", "-preset", "slow", "-crf", "21", "-pix_fmt", "yuv420p",
             # Web loudness: -16 LUFS integrated, -1.5 dBTP (EBU R128 single pass).
             "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", str(AUDIO_RATE),
             "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(out_dir / "film.mp4")],
            stdin=subprocess.PIPE)
        frames = int(round(total * FPS))
        fade_in, fade_out = float(play.get("fade_in_s", 1.5)), float(play.get("fade_out_s", 2.0))
        poster_at = float(play.get("poster_at", total * 0.3))
        for f in range(frames):
            ft0 = time.perf_counter()
            t = f / FPS
            active = [s["id"] for s, (a, b) in zip(play["shots"], spans) if a <= t < b]
            acc, wsum = np.zeros((H, W, 3), np.float32), 0.0
            for s, (a, b) in zip(play["shots"], spans):
                if a <= t < b:
                    d = float(s.get("dissolve", 0.0))
                    w = min(1.0, (t - a) / d) if d and a > 0 else 1.0
                    acc = acc * (1 - w) + shot_frame(stills[s["asset"]], s["move"], (t - a) / (b - a)) * w if wsum else shot_frame(stills[s["asset"]], s["move"], (t - a) / (b - a))
                    wsum = 1.0
            lvl = min(1.0, t / fade_in if fade_in else 1.0, (total - t) / fade_out if fade_out else 1.0)
            frame = np.clip(acc * max(0.0, lvl), 0, 255).astype(np.uint8)
            enc.stdin.write(frame.tobytes())
            dt = time.perf_counter() - ft0
            for sid in active or ["tail"]:
                shot_s[sid] = shot_s.get(sid, 0.0) + dt / max(1, len(active))
                shot_f[sid] = shot_f.get(sid, 0) + 1
            if abs(t - poster_at) < 0.5 / FPS:
                Image.fromarray(frame).save(out_dir / "poster.jpg", quality=88)
            if f % (FPS * 5) == 0:
                print(f"  frame {f}/{frames}", flush=True)
        enc.stdin.close()
        t0 = time.perf_counter()
        if enc.wait():
            fail("ffmpeg encode failed")
        for sid, secs in shot_s.items():
            timer.record("motion", f"shot:{sid}", secs, {"frames": shot_f[sid], "width": W, "height": H},
                         method="ken-burns-pil-bicubic+x264-pipe")
        timer.record("motion", "all_frames", time.perf_counter() - motion_t0, {"frames": frames, "width": W, "height": H})
        timer.record("assembly", "encode_tail", time.perf_counter() - t0, {"frames": frames})

    sources = {
        "place": dossier["place"], "title": play.get("title", dossier["place"]),
        "duration_s": round(total, 2), "narration_share": round(spoken / total, 3),
        "shots": [{"id": s["id"], "start_s": round(a, 2), "asset": s["asset"],
                   "title": assets[s["asset"]]["title"], "date": assets[s["asset"]].get("date"),
                   "creator": assets[s["asset"]].get("creator"), "credit": assets[s["asset"]]["credit"],
                   "licence": assets[s["asset"]]["licence"], "item_url": assets[s["asset"]]["item_url"],
                   "treatment": s.get("treatment", "Ken Burns move on the photograph")}
                  for s, (a, _) in zip(play["shots"], spans)],
        "narration": [{"at": ln["at"], "text": ln["text"]} for ln in play.get("narration", [])],
        "voice": f"Kokoro-82M, voice {play.get('voice', 'am_michael')} (synthetic)",
        "score_credit": play.get("score", {}).get("credit"),
    }
    (out_dir / "sources.json").write_text(json.dumps(sources, indent=2, ensure_ascii=False), encoding="utf-8")
    timer.record("run", "total", time.perf_counter() - run_t0, {"film_s": round(total, 3), "shots": len(play["shots"])})
    print(f"sketch: {total:.1f}s, narration {spoken / total:.0%} -> {out_dir / 'film.mp4'}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        fail("usage: python studio/sketch.py <film folder>")
    render(Path(sys.argv[1]))
