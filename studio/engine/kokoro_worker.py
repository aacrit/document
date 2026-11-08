"""Kokoro-82M synthesis worker: the only file that imports kokoro-onnx. It runs in the TTS interpreter
(studio/requirements-tts.txt, DOCUMENT_KOKORO_PYTHON), never the studio's, and talks to the engine
(studio/engine/narrator.py) through files:

    python kokoro_worker.py --jobs jobs.json --out DIR --model M --voices V [--threads N] [--max-rss-mb MB]
    python kokoro_worker.py --probe --out DIR          (the runtime's versions only; loads no model)

jobs.json: [{"id": "<cache key>", "text": "...", "voice": "af_aoede", "speed": 0.88, "lang": "en-us"}, ...]

Writes DIR/<id>.wav (24 kHz mono int16, peak at most -1 dBFS) per job and DIR/result.json:
    {"ok": [ids], "failed": {id: message}, "status": "ok" | "load-failed" | "memory" | "probe",
     "timing": {"load_s", "synth_s", "audio_s", "rtf"}, "peak_rss_mb": float | null, "sample_rate": 24000,
     "runtime": {"kokoro-onnx", "onnxruntime", "numpy", "phonemizer", "espeakng-loader", "espeak-ng", "python"}}

Machine safety (the 2026-10 WSL memory runaway and BSODs): one process, ONNX intra-op threads capped by --threads.
Before each job the worker reads its own peak working set; once that is past --max-rss-mb it synthesises nothing
more, and every job left is reported failed (status "memory"). A job already running is not interrupted.

Ported from aacrit/void--news pipeline/briefing/tts_kokoro_worker.py at 775cc33481f72a955e7f6fa6c29b03a17bc7fe39:
kept the file protocol, the int16 writer with -1 dBFS headroom, the session options and the per-job speed; left
behind the voice blends and the deadline; added the memory stop and the runtime report.
Nothing here imports from the studio package: it must stay importable with only numpy and kokoro-onnx.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import wave
from pathlib import Path

SAMPLE_RATE = 24000
PEAK_CEILING = 0.891          # -1 dBFS: Kokoro occasionally clips


def rss_mb() -> float | None:
    """This process's working set in MB (Windows: GetProcessMemoryInfo; elsewhere ru_maxrss), or None."""
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
            c = PMC()
            c.cb = ctypes.sizeof(PMC)
            k = ctypes.WinDLL("kernel32", use_last_error=True)
            k.GetCurrentProcess.restype = wintypes.HANDLE
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            if not psapi.GetProcessMemoryInfo(k.GetCurrentProcess(), ctypes.byref(c), c.cb):
                return None
            return round(c.PeakWorkingSetSize / 2**20, 1)
        import resource
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    except Exception:  # pragma: no cover - a platform without either
        return None


def write_wav(path: Path, samples) -> float:
    import numpy as np
    x = np.asarray(samples, dtype=np.float32)
    peak = float(np.abs(x).max()) if x.size else 0.0
    if peak > PEAK_CEILING:
        x = x * (PEAK_CEILING / peak)
    pcm = (np.clip(x, -1.0, 1.0) * 32767.0).astype(np.int16)
    tmp = path.with_name(path.name + ".part")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())
    os.replace(tmp, path)
    return len(pcm) / float(SAMPLE_RATE)


RUNTIME_PACKAGES = ("kokoro-onnx", "onnxruntime", "numpy", "phonemizer", "espeakng-loader")


def runtime_versions() -> dict:
    """The versions of everything between the text and the samples: each package's installed version, the
    espeak-ng library's own (the phonemiser kokoro-onnx loads), and the interpreter. None where one is absent."""
    from importlib import metadata
    out = {}
    for name in RUNTIME_PACKAGES:
        try:
            out[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            out[name] = None
    try:
        import espeakng_loader
        from phonemizer.backend.espeak.wrapper import EspeakWrapper
        EspeakWrapper.set_library(espeakng_loader.get_library_path())
        EspeakWrapper.set_data_path(espeakng_loader.get_data_path())   # as kokoro-onnx does, before any init
        out["espeak-ng"] = ".".join(str(v) for v in EspeakWrapper().version)
    except Exception:
        out["espeak-ng"] = None
    out["python"] = sys.version.split()[0]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--jobs")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model")
    ap.add_argument("--voices")
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--max-rss-mb", type=float, default=6000.0)
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    result = {"ok": [], "failed": {}, "status": "ok", "timing": {}, "peak_rss_mb": None, "sample_rate": SAMPLE_RATE,
              "runtime": runtime_versions()}
    if args.probe:
        result["status"] = "probe"
        (out / "result.json").write_text(json.dumps(result), encoding="utf-8")
        return 0
    if not (args.jobs and args.model and args.voices):
        ap.error("--jobs, --model and --voices are required unless --probe")
    jobs = json.loads(Path(args.jobs).read_text(encoding="utf-8"))
    t0 = time.time()
    try:
        import onnxruntime as ort
        from kokoro_onnx import Kokoro
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, args.threads)
        opts.inter_op_num_threads = 1
        session = ort.InferenceSession(args.model, sess_options=opts, providers=["CPUExecutionProvider"])
        kokoro = Kokoro.from_session(session, args.voices)
    except Exception as e:  # pragma: no cover - environment failure
        result["status"] = "load-failed"
        result["failed"]["__load__"] = f"{type(e).__name__}: {e}"
        (out / "result.json").write_text(json.dumps(result), encoding="utf-8")
        print(f"[kokoro-worker] load failed: {e}", file=sys.stderr)
        return 0
    load_s = time.time() - t0
    audio_s = 0.0
    t1 = time.time()
    for job in jobs:
        peak = rss_mb()
        if peak is not None and peak > args.max_rss_mb:
            result["status"] = "memory"
            result["failed"][job["id"]] = f"stopped: working set {peak:g} MB is over {args.max_rss_mb:g} MB"
            continue
        try:
            samples, rate = kokoro.create(job["text"], voice=job["voice"], speed=float(job["speed"]),
                                          lang=job.get("lang") or "en-us")
            if rate != SAMPLE_RATE:
                raise RuntimeError(f"sample rate {rate}, expected {SAMPLE_RATE}")
            audio_s += write_wav(out / f"{job['id']}.wav", samples)
            result["ok"].append(job["id"])
        except Exception as e:
            result["failed"][job["id"]] = f"{type(e).__name__}: {e}"
    synth_s = time.time() - t1
    result["timing"] = {"load_s": round(load_s, 2), "synth_s": round(synth_s, 2), "audio_s": round(audio_s, 2),
                        "rtf": round(synth_s / audio_s, 3) if audio_s else None}
    result["peak_rss_mb"] = rss_mb()
    (out / "result.json").write_text(json.dumps(result), encoding="utf-8")
    print(f"[kokoro-worker] {len(result['ok'])} ok, {len(result['failed'])} failed, rtf {result['timing']['rtf']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
