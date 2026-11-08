"""The narrator engine (founder ruling 2026-11-07, docs/DECISIONS.md; GRAMMAR A57): void document's narrator is
Kokoro-82M (hexgrad, Apache-2.0), the voice af_aoede at speed 0.88, on the laptop CPU with no WSL, the stand-in
until the founder's own recordings replace her (18 November). Orpheus stays available behind config: a film whose
narrator cast voice says ``engine: "orpheus"`` keeps its takes made outside the engine, as before.

What this module holds:
- the house narrator (HOUSE_NARRATOR), filled in when a film's narrator voice names neither engine nor voice;
- A57's checks on a narrator voice (narrator_problems): an engine named, a Kokoro voice that is in the pinned voice
  bank, a speed in range, natural pitch (the PSOLA shifts tuned to Tara are refused on a Kokoro narrator);
- the model files' lock (studio/kokoro.lock.json): each file's size and sha256 are checked before any use, and a
  mismatch refuses (LockMismatch), never loads; ``fetch`` checks a download before it takes the file's name;
- the take cache: a take is a WAV named by the hash of everything that makes it (the text, the engine, the voice,
  the speed, the shift, the language, the pinned model files and the runtime versions the worker reports), so a take
  of one voice can never stand in for another's (a Tara take is never an aoede one);
- the film's voicing manifest (``<film>/audio/voice.json``, written by ``voice <film>``): line id to its take key,
  the WAV it was written to and that WAV's sha256, under the narrator identity that voiced it. A render's plan
  refuses a Kokoro narration WAV the manifest does not record under the film's current narrator (manifest_problems,
  the narrator-takes-voiced lint), so a stale take (a Tara WAV left in place) never plays credited as aoede;
- the entry point a script calls (``voice_lines``) and the command line:

    python -m studio.engine.narrator verify                 the model files against the lock
    python -m studio.engine.narrator fetch                  download what is missing, check it, then verify
    python -m studio.engine.narrator voice <film dir> [--out <dir>] [--cache <dir>]
    python -m studio.engine.narrator voice <lines.json> --out <dir> [--cache <dir>]
    python -m studio.engine.narrator audition <lines> --out <dir> [--cache <dir>] [--profile]

``voice <film dir>`` voices the screenplay's narration lines as its narrator voice, writes each take to
``--out`` (default ``<film>/audio/narration``) as ``<line id>.wav`` and the manifest to ``<film>/audio/voice.json``;
the screenplay's lines then point their ``wav`` at those files. ``audition`` voices the lines, then runs each
through the voicing chain exactly as a render places a narration line (render.process_take with the narrator's EQ
as render.narrator_eq_resolve gives it: A19's cleanup, levelling to the dialogue target, A14's profile, A38's EQ,
A13's peak control) and reports the real-time factor, the loudness and the profile; ``--profile`` also prints the
stored-profile entry render.narrator_profile_from_takes makes from the raw takes.

Synthesis runs in its own interpreter (studio/requirements-tts.txt; DOCUMENT_KOKORO_PYTHON) through
studio/engine/kokoro_worker.py: one process, OMP and ONNX threads capped (default 2), stopped past a working set cap
(default 6000 MB).

Ported from aacrit/void--news at 775cc33481f72a955e7f6fa6c29b03a17bc7fe39: pipeline/briefing/kokoro_assets.py
(the lock, the sha256 check), pipeline/briefing/onair_producer.py lines 70-84 (af_aoede, speed 0.88) and
pipeline/briefing/tts_engines.py (KokoroEngine's worker protocol and its RTF). Kept: the pinned release and its
hashes, the worker file protocol, RTF as synthesis over audio seconds. Tweaked: a mismatch refuses without deleting
the file, the model folder is document's, takes are cached by input hash. Left behind: edge-tts fallback, pydub,
multi-worker fan-out, voice blends. Net-new: the cache key, the manifest, A57's checks, the D: dirty-bit refusal,
the memory cap, the runtime probe, the audition.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

LOCK_PATH = Path(__file__).resolve().parents[1] / "kokoro.lock.json"
WORKER = Path(__file__).resolve().parent / "kokoro_worker.py"
DEFAULT_MODEL_DIR = Path("D:/document-media/models/kokoro")
MANIFEST = Path("audio") / "voice.json"
WORKER_VERSION = 1                  # bump when the worker's output for the same input changes
# void on air's pace: void--news pipeline/briefing/onair_producer.py at 775cc33 says "0.95 from 2026-09-19 to rev 5;
# 0.88 since CEO 2026-11-08" (dated there by its own commits, UTC). Taken up here by the founder ruling of 2026-11-07.
HOUSE_SPEED = 0.88
CREDIT = "Narrated by a computer voice"
HOUSE_NARRATOR = {"id": "v-narrator", "engine": "kokoro", "voice": "af_aoede", "speed": HOUSE_SPEED, "credit": CREDIT}
# What the printed surfaces say of an engine (the Sources page's notes, description.txt): only what is checked.
ENGINES = {
    "kokoro": {"model": "Kokoro-82M (hexgrad)", "licence": "Apache-2.0", "made_here": True},
    "orpheus": {"model": None, "licence": None, "made_here": False},     # takes made outside the engine (WSL)
}
THREADS = 2
MAX_RSS_MB = 6000.0
SPEED_RANGE = (0.5, 2.0)


class LockMismatch(RuntimeError):
    """A model file is missing, or its size or sha256 is not the pinned one: it is never loaded."""


class NarratorError(RuntimeError):
    """The narrator cannot be voiced as declared."""


# --------------------------------------------------------------------------
# A cast voice's identity, and A57's checks
# --------------------------------------------------------------------------

def _num(v, default: float) -> float:
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return float("nan")
    return float(v)


def identity(voice: dict | None) -> dict:
    """What makes a narrator's take: engine, voice, speed (absent is the engine's own 1.0) and pitch_shift_st
    (absent is 0). Two voices with the same identity make the same takes."""
    v = voice or {}
    return {"engine": v.get("engine"), "voice": v.get("voice"), "speed": _num(v.get("speed"), 1.0),
            "pitch_shift_st": _num(v.get("pitch_shift_st"), 0.0)}


def kokoro_voices(lock: dict | None = None) -> set[str]:
    """The voice names in the pinned voice bank (voices-v1.0.bin), as the lock records them."""
    lock = lock or load_lock()
    return set(((lock.get("conversion") or {}).get("voices") or {}).get("names") or [])


def narrator_problems(voice: dict | None, lock: dict | None = None) -> list[str]:
    """What A57 refuses in a narrator cast voice. A voice that names no engine is refused (the house narrator is
    filled in only when neither engine nor voice is named). A Kokoro voice must be in the pinned voice bank and
    plays at her natural pitch: the PSOLA shifts were tuned to Tara (DECISIONS 2026-10-18, Real World's +0.76 st)
    and are never applied to her. Only the Kokoro and Orpheus engines are judged further: any other engine (a test
    tone) passes untouched."""
    if not voice:
        return []
    eng = voice.get("engine")
    if not eng:
        return [f"the narrator voice {voice.get('voice')!r} names no engine: say engine \"kokoro\" or \"orpheus\" "
                "(the house narrator is filled in only when neither engine nor voice is named)"]
    if eng not in ENGINES:
        return []
    out = []
    ident = identity(voice)
    if ident["speed"] != ident["speed"] or not SPEED_RANGE[0] <= ident["speed"] <= SPEED_RANGE[1]:
        out.append(f"narrator speed {voice.get('speed')!r} is not a number from {SPEED_RANGE[0]:g} to {SPEED_RANGE[1]:g}")
    if eng == "kokoro":
        if voice.get("voice") not in kokoro_voices(lock):
            out.append(f"{voice.get('voice')!r} is not a voice in the pinned voice bank (voices-v1.0.bin, "
                       "studio/kokoro.lock.json conversion.voices.names)")
        if ident["pitch_shift_st"] != 0:
            out.append(f"a Kokoro narrator plays at her natural pitch: pitch_shift_st {voice.get('pitch_shift_st')!r} "
                       "was tuned to Tara; remove it")
    elif "speed" in voice:
        out.append(f"speed is a Kokoro setting; the {eng} narrator's takes are made outside the engine")
    return out


def lang_of(voice: str) -> str:
    """Kokoro's language for a voice: British voices (b*) en-gb, every other English reading en-us."""
    return "en-gb" if str(voice or "").startswith("b") else "en-us"


def printed(voice: dict | None) -> dict:
    """What a printed surface may say of the narrator's engine: its model name and licence, when checked."""
    e = ENGINES.get((voice or {}).get("engine")) or {}
    return {k: e[k] for k in ("model", "licence") if e.get(k)}


# --------------------------------------------------------------------------
# The lock
# --------------------------------------------------------------------------

def load_lock(path: Path | None = None) -> dict:
    return json.loads(Path(path or LOCK_PATH).read_text(encoding="utf-8"))


def model_dir() -> Path:
    env = os.environ.get("DOCUMENT_KOKORO_DIR", "").strip()
    return Path(env).expanduser() if env else DEFAULT_MODEL_DIR


def sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


_VERIFIED: dict[tuple, str] = {}


def check_file(p: Path, entry: dict) -> None:
    """One file against its lock entry: size, then sha256. Raises LockMismatch."""
    st = p.stat()
    if int(entry.get("size") or st.st_size) != st.st_size:
        raise LockMismatch(f"{entry['name']} is {st.st_size} bytes, the lock pins {entry['size']}: refused")
    memo = (str(p.resolve()), st.st_size, st.st_mtime_ns)
    digest = _VERIFIED.get(memo) or sha256_path(p)
    if digest != entry["sha256"]:
        raise LockMismatch(f"{entry['name']} sha256 {digest[:12]} is not the pinned {entry['sha256'][:12]}: refused")
    _VERIFIED[memo] = digest


def verify_files(folder: Path | None = None, lock: dict | None = None) -> dict[str, Path]:
    """{role: path} for the lock's files in ``folder``, each checked (size, then sha256) before use. A missing
    file or any mismatch raises LockMismatch; the file is left where it is for a person to look at."""
    lock = lock or load_lock()
    folder = Path(folder or model_dir())
    out = {}
    for f in lock["files"]:
        p = folder / f["name"]
        if not p.exists():
            raise LockMismatch(f"{f['name']} is missing from {folder} (python -m studio.engine.narrator fetch)")
        check_file(p, f)
        out[f["role"]] = p
    return out


def lock_digest(lock: dict | None = None) -> str:
    lock = lock or load_lock()
    return hashlib.sha256("".join(f"{f['name']}:{f['sha256']};" for f in lock["files"]).encode()).hexdigest()[:16]


# --------------------------------------------------------------------------
# Disk safety: never write to a volume whose dirty bit is set (the exFAT D: of 2026-10-10)
# --------------------------------------------------------------------------

def dirty_refusal(path: Path) -> str | None:
    """Why writing under ``path`` is refused (None: it is not). On Windows, a volume other than the system drive is
    queried with ``fsutil dirty query``; a dirty volume, or a query that fails, refuses."""
    if os.name != "nt":
        return None
    drive = Path(path).resolve().drive.upper()
    system = (os.environ.get("SystemDrive") or "C:").upper()
    if not drive or drive == system:
        return None
    try:
        r = subprocess.run(["fsutil", "dirty", "query", drive], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        return f"fsutil dirty query {drive} failed ({e}): not writing to {drive}"
    text = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0 or "NOT Dirty" not in text:
        return f"{drive} is dirty or could not be queried ({text.strip()[:120]}): not writing to it"
    return None


def _download(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url, timeout=120) as r, dest.open("wb") as w:
        shutil.copyfileobj(r, w, 1 << 20)


def fetch(folder: Path | None = None, lock: dict | None = None, download=_download) -> dict[str, Path]:
    """Download the lock's files that are missing into ``folder``: each lands as ``<name>.part``, is checked
    against the lock, and only then takes its name. A download that fails the check is kept as
    ``<name>.rejected`` for a person to look at, and refuses (LockMismatch). Then every file is verified."""
    lock = lock or load_lock()
    folder = Path(folder or model_dir())
    for f in lock["files"]:
        p = folder / f["name"]
        if p.exists():
            continue
        why = dirty_refusal(folder)
        if why:
            raise NarratorError(why)
        folder.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".part")
        download(f["url"], tmp)
        try:
            check_file(tmp, f)
        except LockMismatch:
            os.replace(tmp, p.with_name(p.name + ".rejected"))
            raise
        os.replace(tmp, p)
    return verify_files(folder, lock)


# --------------------------------------------------------------------------
# The runtime, and the take cache
# --------------------------------------------------------------------------

def tts_python() -> str:
    return os.environ.get("DOCUMENT_KOKORO_PYTHON", "").strip() or sys.executable


def probe_runtime(python: str | None = None) -> dict:
    """The runtime versions as the worker reports them (kokoro-onnx, onnxruntime, numpy, phonemizer, the espeak-ng
    library, the interpreter): ``kokoro_worker.py --probe``, which loads no model."""
    with tempfile.TemporaryDirectory(prefix="kokoro-probe-") as d:
        r = subprocess.run([python or tts_python(), str(WORKER), "--probe", "--out", d],
                           capture_output=True, text=True, timeout=300)
        f = Path(d) / "result.json"
        if not f.exists():
            raise NarratorError(f"the Kokoro worker's probe wrote no result (exit {r.returncode}): "
                                f"{(r.stderr or '').strip()[-300:]}")
        rt = json.loads(f.read_text(encoding="utf-8")).get("runtime") or {}
    if not rt.get("kokoro-onnx") or not rt.get("onnxruntime"):
        raise NarratorError(f"the TTS interpreter has no kokoro-onnx or onnxruntime ({rt}): "
                            "install studio/requirements-tts.txt and set DOCUMENT_KOKORO_PYTHON")
    return rt


def take_key(text: str, voice: dict, lock: dict | None = None, runtime: dict | None = None) -> str:
    """The take's cache key: the hash of its text and everything that voices it, the runtime versions included."""
    ident = identity(voice)
    doc = {"text": str(text), "engine": ident["engine"], "voice": ident["voice"], "speed": ident["speed"],
           "pitch_shift_st": ident["pitch_shift_st"], "lang": lang_of(ident["voice"]),
           "model": lock_digest(lock), "runtime": runtime or {}, "worker": WORKER_VERSION}
    return hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()


def cache_dir(film: Path | None = None) -> Path:
    """Where takes are kept: DOCUMENT_VOICE_CACHE, else <film>/cache/voice."""
    env = os.environ.get("DOCUMENT_VOICE_CACHE", "").strip()
    if env:
        return Path(env)
    if film is None:
        raise NarratorError("no take cache: pass --cache or set DOCUMENT_VOICE_CACHE")
    return Path(film) / "cache" / "voice"


def run_worker(jobs: list[dict], files: dict[str, Path], out: Path, *, threads: int, max_rss_mb: float,
               python: str | None = None) -> dict:
    """Run kokoro_worker.py on ``jobs`` in the TTS interpreter; returns its result.json."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "jobs.json").write_text(json.dumps(jobs), encoding="utf-8")
    env = dict(os.environ, OMP_NUM_THREADS=str(threads), MKL_NUM_THREADS=str(threads))
    cmd = [python or tts_python(), str(WORKER), "--jobs", str(out / "jobs.json"), "--out", str(out),
           "--model", str(files["model"]), "--voices", str(files["voices"]), "--threads", str(threads),
           "--max-rss-mb", str(max_rss_mb)]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=3600)
    res = out / "result.json"
    if not res.exists():
        raise NarratorError(f"the Kokoro worker wrote no result (exit {r.returncode}): {(r.stderr or '').strip()[-300:]}")
    return json.loads(res.read_text(encoding="utf-8"))


def voice_lines(lines: list[dict], voice: dict | None = None, cache: Path | None = None, *, film: Path | None = None,
                threads: int = THREADS, max_rss_mb: float = MAX_RSS_MB, python: str | None = None,
                folder: Path | None = None, runner=run_worker, prober=probe_runtime, lock: dict | None = None) -> dict:
    """Voice narration lines ({id, text}) as ``voice`` (the house narrator by default). The runtime is probed
    first, so its versions are in every key. A take already in the cache under its key is reused; the rest are
    synthesised in one worker run and stored under their keys; a worker run whose reported runtime is not the probed
    one refuses. Returns {"lines": {id: {key, wav, cached}}, "timing", "peak_rss_mb", "runtime", ...}. Refuses an
    engine other than Kokoro and Orpheus, an Orpheus narrator (its takes are made outside the engine), a voice A57
    refuses, and a model file off the lock."""
    voice = dict(voice or HOUSE_NARRATOR)
    if voice.get("engine") not in ENGINES:
        raise NarratorError(f"narrator engine {voice.get('engine')!r} is not one of {sorted(ENGINES)}")
    lock = lock or load_lock()
    problems = narrator_problems(voice, lock)
    if problems:
        raise NarratorError("; ".join(problems))
    if not ENGINES[voice["engine"]]["made_here"]:
        raise NarratorError(f"the {voice['engine']} narrator's takes are made outside the engine; "
                            "only a Kokoro narrator is voiced here")
    cache = Path(cache) if cache else cache_dir(film)
    ident = identity(voice)
    runtime = prober(python)
    out, jobs = {}, []
    for ln in lines:
        key = take_key(ln["text"], voice, lock, runtime)
        wav = cache / f"{key}.wav"
        out[ln["id"]] = {"key": key, "wav": str(wav), "cached": wav.exists()}
        if not wav.exists() and not any(j["id"] == key for j in jobs):
            jobs.append({"id": key, "text": ln["text"], "voice": ident["voice"], "speed": ident["speed"],
                         "lang": lang_of(ident["voice"])})
    timing, peak = {"synth_s": 0.0, "audio_s": 0.0, "rtf": None, "load_s": 0.0}, None
    if jobs:
        why = dirty_refusal(cache)
        if why:
            raise NarratorError(why)
        files = verify_files(folder, lock)              # before any use: a model off the lock is never loaded
        cache.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="kokoro-", dir=cache))
        try:
            t0 = time.perf_counter()
            res = runner(jobs, files, work, threads=threads, max_rss_mb=max_rss_mb, python=python)
            wall = time.perf_counter() - t0
            if res.get("failed"):
                raise NarratorError(f"Kokoro failed ({res.get('status')}): "
                                    + "; ".join(f"{k[:12]}: {v}" for k, v in res["failed"].items()))
            if res.get("runtime") and res["runtime"] != runtime:
                raise NarratorError(f"the worker ran on {res['runtime']}, the keys were made for {runtime}")
            for j in jobs:
                os.replace(work / f"{j['id']}.wav", cache / f"{j['id']}.wav")
            timing = dict(res.get("timing") or {}, wall_s=round(wall, 2))
            if timing.get("audio_s"):
                timing["rtf_wall"] = round(wall / timing["audio_s"], 3)
            peak = res.get("peak_rss_mb")
        finally:
            shutil.rmtree(work, ignore_errors=True)
    return {"voice": voice, "identity": ident, "lines": out, "synthesised": len(jobs), "timing": timing,
            "peak_rss_mb": peak, "threads": threads, "model": lock_digest(lock), "runtime": runtime}


# --------------------------------------------------------------------------
# The film's voicing manifest
# --------------------------------------------------------------------------

def manifest_doc(lines: list[dict], res: dict, wavs: dict[str, Path]) -> dict:
    """The manifest for takes just written: per line, its text's sha256, its take key, the WAV and its sha256."""
    return {"v": 1, "identity": res["identity"], "model": res["model"], "runtime": res["runtime"],
            "lines": {ln["id"]: {"text_sha256": sha256_text(ln["text"]), "key": res["lines"][ln["id"]]["key"],
                                 "wav": Path(wavs[ln["id"]]).as_posix(), "sha256": sha256_path(wavs[ln["id"]])}
                      for ln in lines}}


def manifest_problems(film: Path, lines: list[dict], voice: dict | None, read_sha=sha256_path) -> tuple[list[str], dict]:
    """A57 narrator-takes-voiced: every narration line's WAV, for a Kokoro narrator, must be a take the film's
    manifest (<film>/audio/voice.json) records under the narrator's current identity, for that line's current
    text. Orpheus and other engines are exempt (their takes are made outside the engine). A line whose WAV is
    missing is left to sources-readable. Returns (problems, evidence)."""
    if (voice or {}).get("engine") != "kokoro":
        return [], {"exempt": (voice or {}).get("engine")}
    film = Path(film)
    f = film / MANIFEST
    narr = [ln for ln in lines if ln.get("kind") == "narration" and not ln.get("archival_audio")]
    if not narr:
        return [], {"lines": 0}
    if not f.exists():
        return [f"no voicing manifest at {MANIFEST.as_posix()}: voice the narration with "
                f"python -m studio.engine.narrator voice <film> (a take made elsewhere is not credited as "
                f"{voice.get('voice')})"], {"manifest": None}
    try:
        man = json.loads(f.read_text(encoding="utf-8"))
    except ValueError as e:
        return [f"{MANIFEST.as_posix()} is not JSON ({e})"], {"manifest": str(f)}
    want = identity(voice)
    have = man.get("identity") or {}
    if {k: have.get(k) for k in want} != want:
        return [f"{MANIFEST.as_posix()} was voiced as {have}, the film's narrator is {want}: re-voice it"], \
            {"manifest": str(f), "identity": have}
    out, checked = [], 0
    for ln in narr:
        wav = film / (ln.get("wav") or f"audio/{ln['id']}.wav")
        if not wav.exists():
            continue
        rec = (man.get("lines") or {}).get(ln["id"])
        if not rec:
            out.append(f"{ln['id']}: not in the voicing manifest")
            continue
        if rec.get("text_sha256") != sha256_text(ln.get("text") or ""):
            out.append(f"{ln['id']}: its text changed since it was voiced")
            continue
        if read_sha(wav) != rec.get("sha256"):
            out.append(f"{ln['id']}: {wav.name} is not the take voiced as {want['engine']}:{want['voice']}")
            continue
        checked += 1
    return out, {"manifest": str(f), "identity": have, "checked": checked, "lines": len(narr)}


# --------------------------------------------------------------------------
# The command line
# --------------------------------------------------------------------------

def read_lines(src: str) -> tuple[list[dict], Path | None, dict | None]:
    """{id, text} lines and the narrator voice from a film folder's screenplay (its narration lines), or the lines
    of a JSON list (the house narrator)."""
    p = Path(src)
    if p.is_dir():
        from studio.engine import render as R
        play = json.loads((p / "screenplay.json").read_text(encoding="utf-8"))
        return ([{"id": ln["id"], "text": ln["text"]} for part in play.get("parts", []) for ln in part.get("lines", [])
                 if ln.get("kind") == "narration" and ln.get("text")], p, R.narrator_voice(play))
    data = json.loads(p.read_text(encoding="utf-8"))
    return [{"id": str(x["id"]), "text": str(x["text"])} for x in data], None, None


def safe_name(lid: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", lid)


def audition(lines: list[dict], res: dict, out: Path, *, with_profile: bool = False) -> dict:
    """Each voiced line through the voicing chain as a render places it, with the narrator's own EQ."""
    import soundfile as sf
    from studio.engine import render as R
    from studio.engine import score as SC
    eq, how, problems = R.narrator_eq_resolve({}, res["voice"])
    if problems:
        raise NarratorError("; ".join(problems))
    (out / "chain").mkdir(parents=True, exist_ok=True)
    rows = {}
    for ln in lines:
        raw = Path(res["lines"][ln["id"]]["wav"])
        x = R._read_wav(raw)
        placed, _, rec = R.process_take(x, {"id": ln["id"], "kind": "narration", "text": ln["text"]}, eq, None)
        f = out / "chain" / f"{safe_name(ln['id'])}.wav"
        sf.write(str(f), placed, R.AUDIO_RATE, subtype="FLOAT")
        rows[ln["id"]] = {"raw": str(raw), "chain": str(f), "audio_s": round(len(x) / R.AUDIO_RATE, 2),
                          "lufs_raw": _r(SC.integrated_lufs(x)), "lufs_chain": _r(SC.integrated_lufs(placed)),
                          "level_db": _r(rec["level"]), "profile": rec["profile"],
                          "eq_relevel_db": (rec["eq"] or {}).get("relevel_db"), "eq_applied": rec["eq"] is not None,
                          "peak_reduction_db": (rec["peak"] or {}).get("max_reduction_db"),
                          "bad_take": (rec["peak"] or {}).get("bad_take") or []}
    report = {"voice": res["voice"], "timing": res["timing"], "peak_rss_mb": res["peak_rss_mb"],
              "threads": res["threads"], "runtime": res["runtime"], "lines": rows, "eq": eq, "eq_how": how}
    if with_profile:
        report["profile"] = R.narrator_profile_from_takes(
            [(out / f"{safe_name(ln['id'])}.wav", ln["text"]) for ln in lines],
            {k: res["voice"][k] for k in ("engine", "voice", "speed")})
    (out / "audition.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    return report


def _r(v):
    return None if v is None else round(float(v), 2)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m studio.engine.narrator", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verify")
    sub.add_parser("fetch")
    for name in ("voice", "audition"):
        p = sub.add_parser(name)
        p.add_argument("lines")
        p.add_argument("--out", required=name == "audition")
        p.add_argument("--cache")
        p.add_argument("--threads", type=int, default=THREADS)
        p.add_argument("--max-rss-mb", type=float, default=MAX_RSS_MB)
        if name == "audition":
            p.add_argument("--profile", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.cmd in ("verify", "fetch"):
            files = verify_files() if a.cmd == "verify" else fetch()
            for role, p in files.items():
                print(f"{role}: {p} (sha256 ok)")
            return 0
        lines, film, voice = read_lines(a.lines)
        if a.out:
            out = Path(a.out)
        elif film is not None:
            out = film / "audio" / "narration"
        else:
            raise NarratorError("--out is required for a list of lines")
        for d in (out, film):
            why = dirty_refusal(d) if d is not None else None
            if why:
                raise NarratorError(why)
        res = voice_lines(lines, voice, cache=Path(a.cache) if a.cache else None, film=film, threads=a.threads,
                          max_rss_mb=a.max_rss_mb)
        out.mkdir(parents=True, exist_ok=True)
        wavs = {}
        for ln in lines:
            wavs[ln["id"]] = out / f"{safe_name(ln['id'])}.wav"
            shutil.copyfile(res["lines"][ln["id"]]["wav"], wavs[ln["id"]])
        if a.cmd == "audition":
            res = audition(lines, res, out, with_profile=a.profile)
        else:
            doc = manifest_doc(lines, res, wavs)
            target = (film / MANIFEST) if film is not None else (out / "voice.json")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(doc, indent=1), encoding="utf-8")
            print(f"manifest: {target}")
        print(json.dumps({k: res[k] for k in ("timing", "peak_rss_mb")}, indent=1))
        return 0
    except (LockMismatch, NarratorError) as e:
        print(f"narrator: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
