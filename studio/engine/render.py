"""Render a screenplay v2 into a 1080p24 master film.

    python -m studio.engine.render <film dir> [--out <dir>] [--res 1080|720]
                                   [--from SHOT] [--workers N] [--burn-subtitles]

Reads ``<film dir>/screenplay.json`` (films/GRAMMAR.md section 12) and the
ledgers it cites (top-level ``ledgers``: name -> path, or {"path", "media"};
``dossier.json`` when it names none). Writes ``<out>/master.mp4`` (H.264,
1920x1080 or 1280x720, 24 fps, Rec.709, AAC at -18 LUFS (A15)) and
``<out>/sources.json`` (the timeline: every shot's start and end, mark,
ledger id, credit and licence). Default ``<out>`` is ``<film dir>/out``.

What it draws (binding specs: films/GRAMMAR.md 4, 7, 9 and amendments A5 to
A9; design/brand-kit/BRAND-KIT.md; every graphic comes from motion.py):

- archive video at native aspect, pillarboxed on the near-black field, plain
  Lanczos resampling (A5); telecined sources restored by fieldmatch and
  decimate, true 25 or 30 fps sources conformed by frame drop or repeat (A6);
  a clip flagged ``neutralise_cast`` (ledger item or shot) loses its colour
  cast to neutral grey with its luma kept, and must be marked RECONSTRUCTED
  ``colour cast removed`` (A14);
- stills that open whole at native aspect for about 1.5 s (A7), then make
  their named move on the rostrum curve; a still fills 16:9 only when the shot
  says ``fill_ok: true``, otherwise the camera moves inside the photograph's
  own shape;
- cards: title, chapter, record-is-silent, perspective, credits (generated
  from the timeline), and black under a voice;
- on every frame the mark plate, the watermark (off on cards) and the lower
  thirds; English subtitles burned in only with ``--burn-subtitles``;
- cut, dissolve (same mark class only; any other dissolve is refused) and dip
  to black on the kit's curves.

Frames render in N worker processes (default 8, at most 12: this laptop
crashes under parallel load), one shot per unit, each to a cached segment
keyed by a content hash; the master is encoded last. ``--from SHOT``
re-renders from that shot and takes every earlier shot from the cache.

Every unit of work is journaled (studio/engine/journal.py). Media never
enters the repo (R-08); outputs land outside it unless ``--out`` says so.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import queue as queue_mod
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path

import numpy as np
from PIL import Image

from studio.engine import motion as M
from studio.engine.journal import Journal, sha256_file

ENGINE_VERSION = "0.1.0"
FPS = 24
AUDIO_RATE = 48000
RESOLUTIONS = {1080: (1920, 1080), 720: (1280, 720)}
DEFAULT_WORKERS, MAX_WORKERS = 8, 12
MIN_FREE_GB = 10.0
MAX_HOLD_S = 2.0                    # GRAMMAR 7.1: a longer freeze is RECONSTRUCTED re-timed
TAIL_S = 1.0                        # a hold's frame is read from the clip's last second (VideoReader.tail_frame)
OPEN_S = 1.5                        # A7: the whole photograph, before any move
A7_FULL_LIMIT, A7_BAND_LIMIT = 6.0, 3.5   # A7 pixel check: low-pass mean difference, whole picture and outer band
A7_BAND = 0.05                      # the outer band: 5% of the photograph's content on each side
A7_MOUNT_STD = 6.0                  # a border row or column whose luminance varies less than this is a mount, trimmed
A7_DETAIL_FLOOR = 5.0               # band detail under this cannot show a 1% crop (band score >= 0.76 x detail at z 1.01): inconclusive
TARGET_LUFS, TARGET_TP = -18.0, -1.5           # GRAMMAR 8.5 and A15 (the programme at -18 LUFS, not -16)
TARGET_LRA, LRA_MAX = 11.0, 50.0    # loudnorm's LRA target: at least 11, raised above the mix's own range (8.5 sets no limit)
LIMIT_MARGIN_DB = 0.5               # the true-peak limiter's ceiling sits this far under TARGET_TP
LIMIT_OVERSAMPLE = 4                # alimiter runs at 4x 48 kHz, so it holds inter-sample peaks
LIMITER_ATTACK_MS, LIMITER_RELEASE_MS = 5, 50
LIMIT_ATTEMPTS = 3
LIMIT_MAX_DB, LIMIT_OVER_1DB_S, LIMIT_LRA_DROP = 3.0, 0.050, 0.3   # past these the limiter compresses: refused
LIMIT_ACTED_LOGGED = 200            # the limiter's largest actions journaled with their timestamps
# GRAMMAR A13 (within 8.5's -18 to -20 LUFS dialogue range): each synthetic voice line is levelled to this integrated
# loudness by a measured linear gain before mixing; narration's mood offset (A14) is applied after it.
DIALOGUE_LUFS = -20.0
VOICE_TP_MARGIN = 1.3               # A15: room for the mix-to-master gain
# A13 and A15: a synthetic voice line's true peak after levelling is at most the dialogue level plus the programme's
# headroom (TARGET_TP - TARGET_LUFS, 16.5 dB) less the margin: -4.8 dBTP
VOICE_TP = DIALOGUE_LUFS + (TARGET_TP - TARGET_LUFS) - VOICE_TP_MARGIN
LEVEL_MIN_S = 0.4                   # loudnorm's gating block: a shorter line is measured looped to this length
# A14: narration delivery moves only the level, after the -20 LUFS levelling (voices are rendered upstream)
MOOD_OFFSET_DB = {"plain": 0.0, "measured": 0.0, "warm": 0.0, "grave": -0.5, "hushed": -2.0, "close": -1.0}   # warm: A14 list (CoS, 2026-10-10)
MOOD_OFFSET_MAX_DB = 2.0            # an offset under -2 dB is refused, and so is any positive one (a mood never lifts)
# narrator-consistency (A14): one narrator, one voice. Per line: median f0 and its p10-p90 range over voiced 40 ms
# frames (normalised autocorrelation), spectral centroid over active frames, words per second over the speech span.
PROFILE_FRAME_S, PROFILE_HOP_S, PROFILE_MIN_RMS = 0.040, 0.010, 0.01
F0_MIN_HZ, F0_MAX_HZ, VOICED_CORR = 60.0, 500.0, 0.5
# narrator-consistency bounds are perceptual (CoS ruling, A14 refined): semitones and percent from the narrator's own
# baseline, the median of the film's plain and measured lines. A z-score over a few dozen lines was unstable.
NARRATOR_MIN_LINES = 4              # fewer narration lines make no baseline: journaled as inconclusive
BASELINE_MOODS = {"plain", "measured"}       # the narrator's baseline comes from her unmarked register
MOOD_MAY_BE_LOWER = {"grave", "hushed", "close"}   # these may sit lower; no mood may be higher or brighter
NARRATOR_F0_UP_ST = 1.5             # f0 above the baseline by more than this: out of character, any mood
NARRATOR_F0_DOWN_ST = 1.5           # below by more than this: out of character for plain and measured (and unmarked) lines
NARRATOR_F0_DOWN_LOWER_ST = 3.0     # below by more than this: out of character for hushed, grave and close
NARRATOR_CENTROID_UP = 0.25         # centroid above the baseline by more than 25%: out of character, any mood
NARRATOR_CENTROID_DOWN = 0.25       # below by more than 25%: out of character for plain and measured lines
NARRATOR_CENTROID_DOWN_LOWER = 0.40  # lower moods may go 40% below
NARRATOR_SPREAD_MAX_ST = 1.0        # the baseline lines' robust f0 spread past this is two voices sharing the part
NARRATOR_GROUP_DOWN_ST = 1.5        # a lower-mood group's median f0 may sit at most this far under the baseline
NARRATOR_GROUP_MIN = 2              # a group of one is a single line, which may drop NARRATOR_F0_DOWN_LOWER_ST
# narrator-drift, the film's baseline against the stored audition profile: warn past the first, block past the second
NARRATOR_DRIFT_WARN_ST, NARRATOR_DRIFT_BLOCK_ST = 1.0, 2.0
NARRATOR_DRIFT_WARN_CENTROID, NARRATOR_DRIFT_BLOCK_CENTROID = 0.15, 0.25
NARRATOR_PROFILE = Path(__file__).resolve().parents[1] / "narrator-profile.json"   # optional anchor: the approved audition
NEUTRALISE = "colour cast removed"  # A14: the alteration a neutralised colour cast is marked with
NEUTRALISE_FILTER = "hue=s=0"       # chroma to neutral, luma kept, before scaling and pillarboxing
VOICE_LIMIT_MARGIN_DB = 0.3         # the per-line limiter's ceiling sits this far under VOICE_TP
# A13 bad take (refused, re-render it): over 8 dB for more than 20 ms in total, over 1 dB for more than 20% of the
# line, or over 3 dB for more than 5% of it. A click cut deep for a few ms is peak control; sustained cuts are compression.
VOICE_OVER_8DB_MAX_S, VOICE_OVER_1DB_MAX_SHARE, VOICE_OVER_3DB_MAX_SHARE = 0.020, 0.20, 0.05
MUSIC_LUFS = -26.0                  # a music cue's bed level, 6 dB under the dialogue (its gain_db is an offset from it)
DUCK_DB = 9.0                       # GRAMMAR 8.5: music under voice
DUCK_SMOOTH_S = 0.250               # GRAMMAR 8.5: 250 ms smoothing, a centred ramp (it starts 125 ms before the voice)
DUCK_BRIDGE_S = 1.2                 # voice gaps shorter than this stay ducked (between words and between lines 0.8 s apart),
                                    # so a long bed never pumps; across a 1.5 s scene breath (A10) it comes back up
DUCK_VOICE_THRESHOLD = 1e-3         # a voice sample over -60 dBFS counts as voice for ducking
SILENCE_DBFS = -120.0               # A19: a mix sample at or under this is true digital silence
SILENCE_WARN_S = 4.0                # digital-silence: a run longer than this outside an intended silence is a warning
VOICELESS_FLOOR = 0.10              # GRAMMAR 6.1, A18: at least 10% of the runtime carries no voice
READINGS_FLOOR = 0.20               # GRAMMAR 6.1 as amended (founder, 2026-10-10): readings (read-by and archival
                                    # testimony) carry at least 20% of the runtime (was 30%)
# GRAMMAR 7.2, A9 and A20(a): how long an archive still may hold, by what is spoken over it
STILL_MAX_S = 10.0                  # nothing spoken over the shot (7.2, A9)
STILL_UNDER_NARRATION_MAX_S = 20.0  # narration speaking over it (A20(a), founder 2026-10-10)
STILL_UNDER_READING_MAX_S = 30.0    # a reading (testimony) speaking over it (A9)
STILL_DETAIL_MAX_S = 5.0            # a DETAIL move on a still (7.2: 3 to 5 s; the upper bound is linted)
EVENT_FILM_MIN_S = 600.0            # the shares bind unless both the film and its runtime target are under 10 min
                                    # (teaser, trailer, the test fixture), which journal them as warnings
MASTER_CRF = 18
MASTER_THREADS = 4

CLASSES = ("ARCHIVE", "RECONSTRUCTED", "AI-GENERATED", "DRAWN", "CARD")
KIND_CLASSES = {
    "archive_video": {"ARCHIVE", "RECONSTRUCTED"},
    "archive_still": {"ARCHIVE", "RECONSTRUCTED"},
    "drawn": {"DRAWN"},
    "generated": {"AI-GENERATED"},
    "card": {"CARD"},
    "black": {"CARD"},
}
ALTERATIONS = {"colourised", "upscaled", "stabilised", "interpolated", "re-timed", "inpainted", "motion added", "tinted",
               "audio synthesised", "colour cast removed"}   # the last by GRAMMAR A14
LICENCE_OK = re.compile(r"^(public domain|cc0( 1\.0)?|cc[- ]?by([- ][1-4]\.0)?)$", re.I)
PRESETS = {                         # GRAMMAR 7.2, zoom relative to the largest 16:9 window
    "HOLD": ({"z": 1.0}, {"z": 1.0}),
    "PUSH": ({"z": 1.0}, {"z": 1.12}),
    "PULL": ({"z": 1.12}, {"z": 1.0}),
    "DRIFT": ({"z": 1.15, "x": 1 / 3}, {"z": 1.15, "x": 2 / 3}),
    "TILT": ({"z": 1.2, "y": 0.0}, {"z": 1.2, "y": 1.0}),
    "DETAIL": ({"z": 1.3}, {"z": 1.3}),
}
PRESET_ZMAX = {"HOLD": 1.0, "PUSH": 1.12, "PULL": 1.12, "DRIFT": 1.15, "TILT": 1.2, "DETAIL": 1.3}   # 7.2, max 1.3
SILENT_RE = re.compile(r"^The record holds no .+\.$")
FLAG_RE = re.compile(r"^Account of .+, \d{4}$")
CARD_TEXT_KINDS = {"chapter_card", "title_card", "silent_record"}
CHAPTER_RE = re.compile(r"^(\d+)\s+(.+)$")
LT_SUFFIXES = ("  ·  read by a computer voice", "  ·  original recording")
EM_DASH = "—"

_HERE = Path(__file__).resolve().parent
ENGINE_HASH = hashlib.sha256(b"".join((_HERE / f).read_bytes() for f in ("render.py", "motion.py"))).hexdigest()[:12]
ENGINE_MODEL = {"name": "studio.engine.render", "version": f"{ENGINE_VERSION}+{ENGINE_HASH}"}


class Refused(Exception):
    """The render will not start or go on: a lint failed or a pre-flight check did."""


class EncodeError(Exception):
    """ffmpeg failed while encoding or decoding a unit (retryable once)."""


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------


def ffmpeg() -> str:
    exe = os.environ.get("DOCUMENT_FFMPEG") or shutil.which("ffmpeg")
    if not exe:
        base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Packages"
        hits = sorted(base.glob("Gyan.FFmpeg*/**/bin/ffmpeg.exe"))
        exe = str(hits[-1]) if hits else None
    if not exe:
        raise Refused("ffmpeg not found (set DOCUMENT_FFMPEG)")
    return exe


def ffprobe() -> str:
    ff = Path(ffmpeg())
    sib = ff.with_name(ff.name.replace("ffmpeg", "ffprobe"))
    if sib.exists():
        return str(sib)
    exe = shutil.which("ffprobe")
    if not exe:
        raise Refused("ffprobe not found beside ffmpeg or on PATH")
    return exe


def count_frames(path: Path) -> int:
    """Video packets in a file (one per frame for our H.264 encodes)."""
    r = subprocess.run([ffprobe(), "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                        "stream=nb_read_packets", "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=600)
    try:
        return int(r.stdout.strip().split(",")[0])
    except ValueError:
        return -1


def ffmpeg_version() -> str:
    try:
        return subprocess.run([ffmpeg(), "-version"], capture_output=True, text=True, timeout=10).stdout.splitlines()[0]
    except Exception:
        return "unknown"


def probe_video(path: Path) -> dict:
    r = subprocess.run([ffprobe(), "-v", "error", "-show_entries",
                        "stream=codec_type,width,height,sample_aspect_ratio,r_frame_rate,avg_frame_rate,field_order,duration"
                        ":format=duration",
                        "-of", "json", str(path)], capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise Refused(f"ffprobe could not read {path}: {r.stderr.strip()[-300:]}")
    data = json.loads(r.stdout)
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if v is None:
        raise Refused(f"{path} has no video stream")

    def ratio(x, default=1.0):
        try:
            a, b = str(x).split(":") if ":" in str(x) else str(x).split("/")
            return float(a) / float(b) if float(b) else default
        except Exception:
            return default

    sar = ratio(v.get("sample_aspect_ratio", "1:1")) or 1.0
    if sar <= 0:
        sar = 1.0
    w, h = int(v["width"]), int(v["height"])
    # avg_frame_rate is the rate frames actually arrive at; r_frame_rate is a timebase guess (doubles for
    # field-coded streams). The video stream's own duration, not the container's (audio can run longer).
    fps = ratio(v.get("avg_frame_rate"), 0.0) or ratio(v.get("r_frame_rate"), 0.0)
    try:
        vdur = float(v.get("duration"))
        dur_from = "video stream"
    except (TypeError, ValueError):
        vdur = float(data.get("format", {}).get("duration") or 0.0)
        dur_from = "container (the stream states none)"
    return {"width": w, "height": h, "sar": sar, "dar": w * sar / h, "fps": fps, "r_frame_rate": v.get("r_frame_rate"),
            "field_order": v.get("field_order"), "duration_s": vdur, "duration_from": dur_from,
            "container_duration_s": float(data.get("format", {}).get("duration") or 0.0),
            "has_audio": any(s.get("codec_type") == "audio" for s in data.get("streams", []))}


def even(x: float) -> int:
    return max(2, int(round(x / 2.0)) * 2)


def frame_size(height: int) -> tuple[int, int]:
    if height in RESOLUTIONS:
        return RESOLUTIONS[height]
    return even(height * 16 / 9), even(height)


# --------------------------------------------------------------------------
# Pre-flight
# --------------------------------------------------------------------------


def _existing(p: Path) -> Path:
    p = Path(p).resolve()
    while not p.exists() and p != p.parent:
        p = p.parent
    return p


_HEALTH = {0: "Healthy", 1: "Warning", 2: "Unhealthy", 5: "Unknown"}
_OPSTATUS = {2: "OK", 0: "Unknown", 53264: "Online"}


def volume_health(letter: str) -> dict | None:
    """``Get-Volume`` health of a drive letter, read without elevation (fsutil's
    dirty query needs an elevated shell). None when it cannot be read."""
    cmd = f"Get-Volume -DriveLetter {letter} | Select-Object HealthStatus,OperationalStatus | ConvertTo-Json -Compress"
    for exe in ("powershell.exe", "pwsh"):
        if not shutil.which(exe):
            continue
        try:
            r = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True, text=True, timeout=30)
            data = json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None
        except Exception:
            data = None
        if isinstance(data, dict):
            hs, op = data.get("HealthStatus"), data.get("OperationalStatus")
            hs = _HEALTH.get(hs, hs) if isinstance(hs, int) else hs
            if isinstance(op, list):
                op = op[0] if op else None
            op = _OPSTATUS.get(op, op) if isinstance(op, int) else op
            return {"health": str(hs), "operational": str(op), "via": exe}
    return None


def preflight(out: Path, journal: Journal, *, min_free_gb: float = MIN_FREE_GB, disk_usage=shutil.disk_usage,
              health=volume_health, drive: str | None = None, allow_unverified: bool | None = None) -> dict:
    """Refuse a render that would fill the output drive, or that writes to a D:
    whose volume is not Healthy and OK. An unreadable D: is refused too unless
    DOCUMENT_ALLOW_UNVERIFIED_DISK=1 (journaled as a human override)."""
    root = _existing(out)
    drive = drive or root.anchor
    free_gb = disk_usage(root).free / 1024 ** 3
    ok = free_gb >= min_free_gb
    journal.lint("preflight-free-disk", ok, stage="scout", unit="preflight", phase="preflight",
                 evidence={"drive": drive, "free_gb": round(free_gb, 2), "min_free_gb": min_free_gb})
    if not ok:
        raise Refused(f"output drive {drive} has {free_gb:.1f} GB free, under the {min_free_gb:g} GB floor")
    if min_free_gb < MIN_FREE_GB:
        journal.human("scout", f"free-disk floor lowered to {min_free_gb:g} GB from {MIN_FREE_GB:g} GB", unit="preflight",
                      override="min_free_gb")
    result = {"drive": drive, "free_gb": round(free_gb, 2), "volume": None}
    if drive.upper().startswith("D:"):
        if allow_unverified is None:
            allow_unverified = os.environ.get("DOCUMENT_ALLOW_UNVERIFIED_DISK") == "1"
        v = health("D")
        result["volume"] = v
        healthy = bool(v) and v["health"] == "Healthy" and v["operational"] == "OK"
        if v is None and allow_unverified:
            journal.lint("preflight-d-health", False, stage="scout", unit="preflight", severity="warn", phase="preflight",
                         evidence={"volume": None, "override": "DOCUMENT_ALLOW_UNVERIFIED_DISK=1"})
            journal.human("scout", "rendered to D: with its volume health unverified", unit="preflight",
                          override="DOCUMENT_ALLOW_UNVERIFIED_DISK=1")
            return result
        journal.lint("preflight-d-health", healthy, stage="scout", unit="preflight", evidence={"volume": v}, phase="preflight")
        if v is None:
            raise Refused("D: volume health could not be read (Get-Volume); set DOCUMENT_ALLOW_UNVERIFIED_DISK=1 to "
                          "render anyway, or run chkdsk D: first")
        if not healthy:
            raise Refused(f"D: is {v['health']} / {v['operational']}; run chkdsk D: /f before rendering to it")
    return result


def decodes_a_frame(path: Path | str) -> str | None:
    """None when ffmpeg decodes at least one video frame from the file, else why not."""
    try:
        r = subprocess.run([ffmpeg(), "-v", "error", "-threads", "1", "-i", str(path), "-map", "0:v:0", "-frames:v", "1",
                            "-vf", "scale=16:16", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                           capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return "ffmpeg timed out reading its first frame"
    if len(r.stdout) >= 256:
        return None
    err = r.stderr.decode(errors="replace").strip()
    return f"no frame decoded{': ' + err[-200:] if err else ''}"


def reads_as_wav(path: Path | str) -> str | None:
    """None when soundfile reads the WAV's header and it holds at least one frame, else why not."""
    import soundfile as sf
    try:
        info = sf.info(str(path))
    except Exception as e:
        return f"not a readable WAV: {type(e).__name__}: {e}"
    return None if info.frames > 0 else "an empty WAV (0 frames)"


def opens_as_image(path: Path | str) -> str | None:
    """None when PIL decodes every pixel of the image file, else why not. verify() alone
    reads only the structure and passes a truncated JPEG, so the file is opened again and
    loaded."""
    try:
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            im.load()
        return None
    except Exception as e:
        return f"not a readable image: {type(e).__name__}: {e}"


def preflight_sources(film: Path, play: dict, journal: Journal, *, draft: bool = False) -> list[dict]:
    """Every file the screenplay references, checked before any frame: each clip, still and drawn
    frame exists and opens (a clip decodes at least one frame), and each voice WAV exists (a draft
    places silence instead, and build_mix journals it). A missing music or ambience cue stays a
    warning (silence). Journals one lint per file checked and returns every blocking problem, so
    one refusal lists them all."""
    assets = load_ledgers(film, play)
    problems: list[dict] = []
    seen: set[str] = set()
    checked = 0
    for part in play.get("parts", []):
        for s in part.get("shots", []):
            if s.get("kind") not in ("archive_video", "archive_still", "drawn") or not s.get("asset"):
                continue
            item = assets.get(s["asset"])
            if item is None:                              # build_plan's ledger-cited lint names it
                continue
            path = item.get("_path")
            if not path:
                problems.append({"unit": s["id"], "file": None, "why": f"ledger item {s['asset']} names no file"})
                continue
            if path in seen:
                continue
            seen.add(path)
            checked += 1
            if not Path(path).exists():
                why = "missing"
            elif s["kind"] == "archive_video":
                why = decodes_a_frame(path)
            else:
                why = opens_as_image(path)
            if why:
                problems.append({"unit": s["id"], "asset": s["asset"], "file": path, "why": why})
        for ln in part.get("lines", []):
            if ln.get("kind") not in VOICE_KINDS:
                continue
            wav = voice_wav(film, ln)
            checked += 1
            if not wav.exists():
                if not draft:
                    problems.append({"unit": ln["id"], "file": str(wav), "why": "voice WAV missing"})
                continue
            why = reads_as_wav(wav)
            if why:                                       # present but unreadable: refused even in a draft
                problems.append({"unit": ln["id"], "file": str(wav), "why": why})
    journal.lint("sources-readable", not problems, stage="scout", unit="sources", phase="preflight",
                 evidence={"files_checked": checked, "problems": problems, "draft": draft,
                           "checks": "clips decode a frame, stills and drawn frames open, voice WAVs exist"})
    return problems


# --------------------------------------------------------------------------
# Plan: screenplay + ledgers -> a picklable dict every worker renders from
# --------------------------------------------------------------------------


def load_ledgers(film: Path, play: dict) -> dict:
    refs = play.get("ledgers") or ({"dossier": "dossier.json"} if (film / "dossier.json").exists() else {})
    assets: dict[str, dict] = {}
    for name, ref in refs.items():
        path = film / (ref if isinstance(ref, str) else ref["path"])
        media = (film / ref["media"]) if isinstance(ref, dict) and ref.get("media") else path.parent
        if not path.exists():
            raise Refused(f"ledger {name!r} not found at {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else (data.get("items") or data.get("assets") or [])
        for it in items:
            it = dict(it)
            it["_private_keys"] = private_keys(it)       # refused in build_plan: "_" keys belong to the engine
            it["_ledger"] = name
            it["_path"] = str((media / it["file"]).resolve()) if it.get("file") else None
            assets[it["id"]] = it
    return assets


def private_keys(x, path: str = "") -> list[str]:
    """Every key starting with ``_`` anywhere inside a screenplay element or
    ledger item. Those names are the engine's own working state (``_item``,
    ``_neutralise``, ``_video``...): set by hand they could switch on a
    behaviour the mark does not declare, so they are refused."""
    out = []
    if isinstance(x, dict):
        for k, v in x.items():
            if str(k).startswith("_"):
                out.append(f"{path}{k}")
            out += private_keys(v, f"{path}{k}.")
    elif isinstance(x, list):
        for k, v in enumerate(x):
            out += private_keys(v, f"{path}{k}.")
    return out


def year_of(item: dict) -> str | None:
    if item.get("year"):
        return str(item["year"])
    m = re.match(r"^(\d{4})", str(item.get("date") or ""))
    return m.group(1) if m else None


def mark_detail(shot: dict, item: dict | None) -> str:
    cls = shot["mark"]
    if cls == "CARD":
        return ""
    if cls == "AI-GENERATED":
        return "context"
    if cls == "DRAWN":
        # the plate prints the ledger's short form (at most 40 characters, so it fits the frame);
        # the full data source goes to the credits and the Sources page
        src = (shot.get("data_source") or (item or {}).get("source_short") or (item or {}).get("data_source")
               or (item or {}).get("mark_detail_source") or "")
        return f"from {src}".strip()
    archive = (item or {}).get("archive_short") or (item or {}).get("archive") or ""
    detail = f"{archive} {year_of(item or {}) or ''}".strip()
    if cls == "RECONSTRUCTED":
        detail += "  " + ", ".join(shot.get("alterations") or [])
    return detail


def mark_label(shot: dict, item: dict | None) -> str:
    """A16: the quiet provenance label, class and year in sentence case
    ("Archive · 1947"); a RECONSTRUCTED shot names its alterations, a DRAWN
    one its data source. The archive's name stays in the credits, the
    Sources page and sources.json. A CARD has none (it carries the glyph)."""
    cls = shot["mark"]
    if cls == "CARD":
        return ""
    if cls == "AI-GENERATED":
        return M.mark_label(cls, None, "context")
    if cls == "DRAWN":
        src = (shot.get("data_source") or (item or {}).get("source_short") or (item or {}).get("data_source")
               or (item or {}).get("mark_detail_source") or "")
        return M.mark_label(cls, None, f"from {src}" if src else "")
    extra = ", ".join(shot.get("alterations") or []) if cls == "RECONSTRUCTED" else ""
    return M.mark_label(cls, year_of(item or {}), extra)


def is_synthetic(item: dict | None) -> bool:
    """A ledger item a program made (a test pattern or fixture image) rather
    than an archive: it may only ever be marked DRAWN."""
    return bool(item) and bool(item.get("synthetic") or item.get("test_fixture") or item.get("generator"))


def neutralise_cast(shot: dict, item: dict | None) -> bool:
    """A14: the shot's ``neutralise_cast`` when it states one, else its
    ledger item's (a whole derivative carries a transfer cast)."""
    if "neutralise_cast" in shot:
        return shot["neutralise_cast"] is True
    return bool(item) and item.get("neutralise_cast") is True


def card_kind(shot: dict) -> str:
    if shot["kind"] == "black":
        return "black"
    explicit = shot.get("card")
    if explicit:
        return explicit
    if shot.get("silent_record"):
        return "silent"
    if shot["_part_kind"] in ("title", "credits"):
        return shot["_part_kind"]
    if shot["_part_kind"] == "chapter" and shot["_first_in_part"]:
        return "chapter"
    return "statement"


def still_camera(shot: dict, img_size: tuple[int, int], W: int, H: int) -> dict:
    """The still's camera: a path of framings in frame space (z = 1 is the
    whole photograph at native aspect) and the clamp mode. The path always
    starts whole (A7); a fill needs ``fill_ok: true``."""
    iw, ih = img_size
    s = min(W / iw, H / ih)
    fw, fh = iw * s, ih * s
    ox, oy = (W - fw) / 2.0, (H - fh) / 2.0
    fill = shot.get("fill_ok") is True
    base = max(W / fw, H / fh) if fill else 1.0
    preset = str(shot.get("preset", "HOLD")).upper()
    if preset not in PRESETS:
        raise Refused(f"shot {shot['id']}: unknown preset {preset!r} (GRAMMAR 7.2)")
    frm, to = (dict(k) for k in PRESETS[preset])
    if preset == "DETAIL":
        region = shot.get("region") or {}
        for k in (frm, to):
            k["x"], k["y"] = float(region.get("x", 0.5)), float(region.get("y", 0.5))
    direction = str(shot.get("direction", "")).lower()
    if preset == "DRIFT" and direction in ("rl", "right-to-left", "left"):
        frm["x"], to["x"] = to["x"], frm["x"]
    if preset == "TILT" and direction in ("up", "bottom-to-top"):
        frm["y"], to["y"] = to["y"], frm["y"]
    frm.update(shot.get("from") or {})
    to.update(shot.get("to") or {})

    def F(k):
        return {"z": base * float(k["z"]), "x": (ox + float(k.get("x", 0.5)) * fw) / W, "y": (oy + float(k.get("y", 0.5)) * fh) / H}

    whole = {"z": 1.0, "x": 0.5, "y": 0.5}
    pts = [whole] + ([F(to)] if preset == "PULL" else [F(frm), F(to)])
    path = [pts[0]]
    for p in pts[1:]:
        if any(abs(p[k] - path[-1][k]) > 1e-9 for k in ("z", "x", "y")):
            path.append(p)
    dur = float(shot["_dur"])
    return {"path": path, "clamp": "image" if fill else "native", "fill_ok": fill, "preset": preset,
            "open_s": min(OPEN_S, 0.4 * dur), "z_max": max(p["z"] for p in path), "fit_scale": s,
            "z_rel_max": max(float(frm["z"]), float(to["z"]))}


def still_is_whole(size, src, dst, W: int, H: int) -> bool:
    """A7 geometry: the window holds the entire photograph, drawn at the
    scale that fits it in the frame, with its aspect unchanged."""
    iw, ih = size
    sw, sh = src[2] - src[0], src[3] - src[1]
    dw, dh = dst[2] - dst[0], dst[3] - dst[1]
    contains = src[0] <= 0.5 and src[1] <= 0.5 and src[2] >= iw - 0.5 and src[3] >= ih - 0.5
    sx, sy = dw / sw, dh / sh
    fit = min(W / iw, H / ih)
    return contains and abs(sx - sy) <= 1e-3 * fit and abs(sx - fit) <= 1e-3 * fit


def conform_plan(item: dict, probe: dict) -> dict:
    """A6: how a clip reaches 24 fps with no speed change."""
    fps = probe["fps"]
    telecined = item.get("telecined")
    if telecined is True:
        # fieldmatch's automatic field order mis-matches decoded H.264 (ENGINE-LOG 2026-10-10): name it.
        fo = str(item.get("field_order") or probe.get("field_order") or "").lower()
        order = {"tt": "tff", "tb": "tff", "tff": "tff", "bb": "bff", "bt": "bff", "bff": "bff"}.get(fo, "auto")
        return {"method": "ivtc", "filter": f"fieldmatch=order={order}:combmatch=full,decimate,fps=24",
                "field_order": order, "in_fps": round(fps, 3), "out_fps": FPS,
                "note": "inverse telecine restores the film frames (23.976), then fps=24 repeats 1 frame in 1000 to keep time"}
    if abs(fps - FPS) < 0.01:
        return {"method": "none", "filter": "", "in_fps": round(fps, 3), "out_fps": FPS}
    method = "drop" if fps > FPS else "repeat"
    return {"method": method, "filter": "fps=24", "in_fps": round(fps, 3), "out_fps": FPS,
            "note": f"frame {method} to 24 with no speed change",
            "telecine_declared": telecined is not None}


def parse_aspect(x) -> float:
    """``4:3``, ``4/3``, ``1.3333`` or a number."""
    t = str(x).strip()
    for sep in (":", "/"):
        if sep in t:
            a, b = t.split(sep, 1)
            return float(a) / float(b)
    return float(t)


def fit_video(dar: float, W: int, H: int) -> tuple[int, int]:
    if dar >= W / H:
        return W, min(H, even(W / dar))
    return min(W, even(H * dar)), H


def _wrap_chars(text: str, n: int = 90) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > n:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    return lines + ([cur] if cur else [])


def narrator_voice(play: dict) -> dict | None:
    """The cast voice the narration is read by (a narration line's
    ``read_by``, else the voice ``v-narrator``)."""
    voices = {v.get("id"): v for v in (play.get("cast") or {}).get("voices", [])}
    for part in play.get("parts", []):
        for ln in part.get("lines", []):
            if ln.get("kind") == "narration" and ln.get("read_by") in voices:
                return voices[ln["read_by"]]
    return voices.get("v-narrator")


def credits_blocks(plan: dict) -> list:
    shots, readings, sound = [], [], []
    for s in plan["shots"]:
        if s["mark"] == "CARD":
            continue
        it = plan["assets"].get(s.get("asset") or "", {})
        alt = ", ".join(s.get("alterations") or [])
        parts = [s["id"], it.get("archive_short") or it.get("archive") or "", (it.get("title") or "").strip(),
                 year_of(it) or "", it.get("licence") or ""] + ([alt] if alt else [])
        shots += _wrap_chars("  ".join(p for p in parts[:1]) + "  " + ", ".join(p for p in parts[1:] if p))
    seen = set()
    for ln in plan["lines"]:
        if ln.get("kind") == "testimony" and ln.get("read_by") and ln.get("speaker") not in seen:
            seen.add(ln.get("speaker"))
            name = plan["speakers"].get(ln.get("speaker"), {}).get("name", ln.get("speaker"))
            readings.append(f"Read by a computer voice. No recording of {name} was used.")
    for c in plan["cues"]:
        bits = [c.get("source", ""), c.get("tradition", ""), c.get("performer", ""), c.get("licence", "")]
        sound += _wrap_chars(", ".join(b for b in bits if b))
    blocks = [("Shots", shots)]
    if readings:
        blocks.append(("Readings", readings))
    if sound:
        blocks.append(("Sound", sound))
    blocks.append(("Studio", [f"void document studio engine {ENGINE_VERSION} ({ENGINE_HASH})"]))
    return [(h, [ln.replace(EM_DASH, ", ") for ln in lines]) for h, lines in blocks]


VOICE_KINDS = ("narration", "testimony")
VOICE_GAP_S = 0.8                   # founder ruling 2026-10-10: voices never overlap, 0.8 s between lines


def voice_wav(film: Path, ln: dict) -> Path:
    return film / (ln.get("wav") or f"audio/{ln['id']}.wav")


def wav_seconds(path: Path) -> float:
    import soundfile as sf
    info = sf.info(str(path))
    return info.frames / float(info.samplerate)


def voice_lines(play: dict, film: Path) -> list[dict]:
    """Every narration and testimony line whose WAV exists, with its measured
    length, in time order. Lines without a WAV are left out (a missing WAV is
    refused on its own unless --draft)."""
    out = []
    for part in play["parts"]:
        for ln in part.get("lines", []):
            if ln.get("kind") in VOICE_KINDS and voice_wav(film, ln).exists():
                out.append({"id": ln["id"], "kind": ln["kind"], "start": float(ln["start_s"]),
                            "dur": wav_seconds(voice_wav(film, ln)), "ref": ln})
    return sorted(out, key=lambda v: (v["start"], v["id"]))


def voice_collisions(lines: list[dict], gap: float = VOICE_GAP_S) -> list[dict]:
    """Each place where a voice line starts before the previous voice has
    ended plus ``gap``: the two ids, how many seconds they overlap (0 when they
    only sit too close) and the gap they leave."""
    out = []
    prev = None
    for v in lines:
        if prev is not None:
            prev_end = prev["start"] + prev["dur"]
            g = v["start"] - prev_end
            if g < gap - 1e-9:
                out.append({"a": prev["id"], "b": v["id"], "overlap_s": round(max(0.0, -g), 3), "gap_s": round(g, 3),
                            "short_by_s": round(gap - g, 3)})
        if prev is None or v["start"] + v["dur"] > prev["start"] + prev["dur"]:
            prev = v
    return out


def fit_voices(play: dict, film: Path, journal: Journal, gap: float = VOICE_GAP_S) -> dict:
    """--fit-voices: move each voice line to max(its start, the previous
    voice's end + gap). Time is inserted at the line's start: the shot the line
    sits in grows by that much and everything that starts at or after that
    point moves later by the same amount. Audio is never shortened or sped up.

    What moves, and by how much (``shift(t)`` is the time inserted at or
    before the original time t):
    - voice lines, text elements and audio cues by ``shift(start)``. Text keeps
      its length. An audio cue spanning an insertion point plays on through it
      (its end moves by the time inserted before its end), since ambience
      under a longer shot should keep playing;
    - each ``subtitle_source`` cue by exactly the shift of the element its
      ``ref`` names, never stretched, so a caption stays with its words even
      when it starts a few frames before them;
    - shots: the one holding an insertion point grows, later ones move.
    Every move is journaled as a decision."""
    import copy
    play = copy.deepcopy(play)
    shots = [sh for part in play["parts"] for sh in part.get("shots", [])]
    # 1. Where time is inserted, on the original timeline.
    points: list[tuple[float, float, dict]] = []          # (original start, seconds inserted, line)
    acc, prev_end = 0.0, None
    for v in voice_lines(play, film):
        start = v["start"] + acc
        if prev_end is not None and start < prev_end + gap - 1e-9:
            delta = round(prev_end + gap - start, 4)
            points.append((v["start"], delta, v["ref"]))
            acc += delta
            start += delta
        prev_end = max(prev_end or 0.0, start + v["dur"])
    if not points:
        return play

    def shift(t: float, strict: bool = False) -> float:
        return sum(d for p, d, _ in points if (p < t - 1e-9 if strict else p <= t + 1e-9))

    # 2. Shots: the owner of each point grows; a shot starting after a point moves.
    assets = None
    for p, d, ln in points:
        owner = max((sh for sh in shots if float(sh["start_s"]) <= p + 1e-9), key=lambda sh: float(sh["start_s"]))
        if owner["kind"] == "archive_video":
            if "out_s" not in owner:                  # derive the out point the way build_plan does
                if assets is None:
                    assets = load_ledgers(film, play)
                item = assets.get(owner.get("asset"), {})
                in_s = float(owner.get("in_s", item.get("in_s", 0.0)))
                owner["in_s"] = in_s
                owner["out_s"] = float(item.get("out_s", in_s + float(owner.get("dur_s", 0.0))))
            owner["out_s"] = round(float(owner["out_s"]) + d, 4)
        else:
            owner["dur_s"] = round(float(owner["dur_s"]) + d, 4)
    for sh in shots:
        sh["start_s"] = round(float(sh["start_s"]) + shift(float(sh["start_s"]), strict=True), 4)
    # 3. Lines, text and audio cues.
    moved: dict[str, float] = {}
    for part in play["parts"]:
        for x in part.get("lines", []) + part.get("text", []):
            if "start_s" not in x:
                continue
            k = shift(float(x["start_s"]))
            moved[x["id"]] = k
            if k:
                x["start_s"] = round(float(x["start_s"]) + k, 4)
                if "end_s" in x:
                    x["end_s"] = round(float(x["end_s"]) + k, 4)
        for c in part.get("cues", []):
            k0, k1 = shift(float(c["start_s"])), shift(float(c["end_s"]), strict=True)
            c["start_s"], c["end_s"] = round(float(c["start_s"]) + k0, 4), round(float(c["end_s"]) + k1, 4)
    # 4. Subtitle cues follow their ref, exactly, and never stretch.
    for c in play.get("subtitle_source", []):
        k = moved[c["ref"]] if c.get("ref") in moved else shift(float(c["start_s"]))
        if k:
            c["start_s"], c["end_s"] = round(float(c["start_s"]) + k, 4), round(float(c["end_s"]) + k, 4)
    for p, d, ln in points:
        owner = max((sh for sh in shots if float(sh["start_s"]) <= p + shift(p, strict=True) + 1e-9),
                    key=lambda sh: float(sh["start_s"]))
        journal.decision("scout", f"moved {ln['id']} later by {d:.3f} s (from {p + shift(p, strict=True):.3f} s) and lengthened "
                         f"{owner['id']} by {d:.3f} s; everything from that point on moved {d:.3f} s later",
                         f"voice-overlap: {ln['id']} started {d:.3f} s before the previous voice's end plus {gap:g} s "
                         f"(--fit-voices)", unit=ln["id"], moved_from=round(p + shift(p, strict=True), 4),
                         moved_to=round(p + shift(p), 4), shot=owner["id"], lengthened_s=d)
    return play


def build_plan(film: Path, *, W: int, H: int, burn_subtitles: bool, journal: Journal, play: dict | None = None) -> dict:
    play = play if play is not None else json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    if "parts" not in play:
        raise Refused("screenplay.json has no parts: it is not format v2 (GRAMMAR 12); studio/sketch.py renders v1")
    assets = load_ledgers(film, play)
    lint_fail: list[str] = []

    def lint(rule, ok, *, unit=None, severity="block", evidence=None, grammar=None, stage="scout"):
        journal.lint(rule, ok, stage=stage, unit=unit, severity=severity, evidence=evidence, grammar=grammar, phase="preflight")
        if severity == "block" and not ok:
            lint_fail.append(f"{rule}" + (f" ({unit})" if unit else "") + (f": {evidence}" if evidence else ""))

    # Engine-private keys: nothing in a screenplay part (or what it holds), its cast, its subtitles or a ledger item
    # may start with "_". The documents' own top-level "_note" comments are not read into any element.
    private = {}
    for part in play["parts"]:
        for coll in ("shots", "lines", "cues", "text"):
            for x in part.get(coll, []):
                if private_keys(x):
                    private[f"{part.get('id')}/{x.get('id')}"] = private_keys(x)
        own = private_keys({k: v for k, v in part.items() if k not in ("shots", "lines", "cues", "text")})
        if own:
            private[f"part {part.get('id')}"] = own
    for where, x in (("cast", play.get("cast")), ("subtitle_source", play.get("subtitle_source"))):
        if private_keys(x):
            private[where] = private_keys(x)
    for aid, it in assets.items():
        if it.get("_private_keys"):
            private[f"ledger {it['_ledger']}/{aid}"] = it["_private_keys"]
    for where, keys in private.items():
        lint("private-key", False, unit=where, evidence={"keys": keys, "fix": "remove them: keys starting with _ are the engine's"})
    if lint_fail:
        raise Refused("lint failed: " + "; ".join(lint_fail))

    shots, lines, cues, texts = [], [], [], []
    for part in play["parts"]:
        for k, s in enumerate(part.get("shots", [])):
            s = dict(s)
            s["_part"], s["_part_kind"], s["_first_in_part"] = part["id"], part.get("kind", ""), k == 0
            shots.append(s)
        lines += [dict(x, _part=part["id"]) for x in part.get("lines", [])]
        cues += [dict(x, _part=part["id"]) for x in part.get("cues", [])]
        texts += [dict(x, _part=part["id"]) for x in part.get("text", [])]
    # A19: underscore. Top-level `music` cues may span scenes and parts; a cue anywhere may fade in and out.
    cues += [dict(x, _part=None, kind=x.get("kind", "music")) for x in play.get("music", [])]
    if not shots:
        raise Refused("the screenplay has no shots")
    ids = [s["id"] for s in shots]
    if len(set(ids)) != len(ids):
        raise Refused("shot ids are not unique")

    # Durations, ledger checks, marks.
    for s in shots:
        item = assets.get(s.get("asset")) if s.get("asset") else None
        kind = s["kind"]
        if kind in ("generated",):
            lint("kind-supported", False, unit=s["id"], evidence="generated shots are not rendered by T1 (AI-GENERATED share is 0)")
            continue
        if kind == "drawn" and not s.get("asset"):
            lint("kind-supported", False, unit=s["id"], evidence="a drawn shot needs a pre-rendered image cited as its asset in T1")
            continue
        if kind in ("archive_video", "archive_still", "drawn"):
            ok = item is not None
            lint("ledger-cited", ok, unit=s["id"], evidence={"asset": s.get("asset")}, grammar="11.1")
            if not ok:
                continue
            lic = str(item.get("licence") or "")
            lint("licence-allowlist", bool(LICENCE_OK.match(lic.strip())), unit=s["id"], evidence={"licence": lic}, grammar="1.2")
            bodies = item.get("shows_bodies", item.get("shows_violence_or_bodies"))
            lint("no-bodies", bodies is False, unit=s["id"], evidence={"shows_bodies": bodies}, grammar="1.6")
            if not item.get("_path") or not Path(item["_path"]).exists():
                lint("asset-file", False, unit=s["id"], evidence={"file": item.get("_path")})
                continue
        allowed = set(KIND_CLASSES.get(kind, set()))
        if is_synthetic(item):
            allowed = {"DRAWN"}            # made by a program (a test pattern, a fixture image): never ARCHIVE
        lint("mark-class-valid", s.get("mark") in allowed, unit=s["id"], evidence={"kind": kind, "mark": s.get("mark"),
             "allowed": sorted(allowed)}, grammar="4")
        if s.get("mark") == "RECONSTRUCTED":
            alts = s.get("alterations") or []
            lint("alterations-closed", bool(alts) and set(alts) <= ALTERATIONS, unit=s["id"], evidence=alts, grammar="4.2, A14")
        s["_neutralise"] = False                 # only the A14 check below may turn it on
        neutral = neutralise_cast(s, item)
        named = NEUTRALISE in (s.get("alterations") or [])
        if neutral or named:
            # A14: the flag and the mark go together. A neutralised shot is RECONSTRUCTED "colour cast removed", never
            # ARCHIVE; a mark that names the alteration with nothing performing it is a false mark.
            ok = kind == "archive_video" and neutral and named and s.get("mark") == "RECONSTRUCTED"
            lint("colour-cast-marked", ok, unit=s["id"], grammar="A14",
                 evidence={"kind": kind, "neutralise_cast": neutral, "mark": s.get("mark"), "alterations": s.get("alterations") or [],
                           "fix": None if ok else (
                               "neutralise_cast applies to archive_video only" if kind != "archive_video" else
                               f"mark the shot RECONSTRUCTED with the alteration '{NEUTRALISE}'" if neutral else
                               f"set neutralise_cast: true on the ledger item or the shot, or drop '{NEUTRALISE}'")})
            s["_neutralise"] = bool(ok)
        if kind == "archive_video":
            in_s = float(s.get("in_s", (item or {}).get("in_s", 0.0)))
            out_s = float(s.get("out_s", (item or {}).get("out_s", in_s + float(s.get("dur_s", 0)))))
            s["in_s"], s["out_s"] = in_s, out_s
            s["_dur"] = out_s - in_s
        else:
            s["_dur"] = float(s.get("dur_s", 0.0))
        if s["_dur"] <= 0:
            lint("duration", False, unit=s["id"], evidence={"dur_s": s["_dur"]})
        s["_item"] = {k: v for k, v in (item or {}).items()}
        s["detail"] = mark_detail(s, item)
        s["label"] = mark_label(s, item)
        if s["mark"] in ("ARCHIVE", "RECONSTRUCTED") and item and not year_of(item):
            lint("mark-year", False, unit=s["id"], severity="warn", evidence={"date": item.get("date")}, grammar="4")
        if kind in ("card", "black"):
            s["_card"] = card_kind(s)
    if lint_fail:
        raise Refused("lint failed: " + "; ".join(lint_fail))

    # Timeline: start, end, tiling; frame ranges by owner (the latest shot started).
    for i, s in enumerate(shots):
        s["start_s"] = float(s["start_s"])
        s["end_s"] = s["start_s"] + s["_dur"]
        tr = s.get("transition_in") or {"type": "cut"}
        s["transition_in"] = tr
        if i:
            prev = shots[i - 1]
            overlap = float(tr.get("s", 0)) if tr.get("type") == "dissolve" else 0.0
            expect = prev["end_s"] - overlap
            lint("tiling", abs(s["start_s"] - expect) <= 0.5 / FPS, unit=s["id"],
                 evidence={"start_s": s["start_s"], "expected": round(expect, 4)}, grammar="12")
        if tr.get("type") == "dissolve":
            prev_cls = shots[i - 1]["mark"] if i else None
            ok = i > 0 and prev_cls == s["mark"]
            lint("dissolve-same-class", ok, unit=s["id"], evidence={"from": prev_cls, "to": s["mark"]}, grammar="4.4")
            if not ok:
                journal.decision("scout", f"refused a dissolve from {prev_cls} into {s['mark']} at {s['id']}",
                                 "GRAMMAR 4.4 and 7.3: a dissolve is allowed only within one mark class", unit=s["id"])
            ds = float(tr.get("s", 0))
            lint("dissolve-length", 0.5 <= ds <= 1.5 and ds < s["_dur"], unit=s["id"], severity="warn",
                 evidence={"s": ds}, grammar="7.3")
        elif tr.get("type") == "dip":
            ds = float(tr.get("s", 0))
            # over GRAMMAR's 1.0 s a dip is a long black that hides the mark (A11): refused; short of 0.5 s, a warning
            lint("dip-length", 0.5 <= ds <= 1.0, unit=s["id"], severity="block" if ds > 1.0 else "warn",
                 evidence={"s": ds, "min_s": 0.5, "max_s": 1.0}, grammar="7.3, A11")
            if i and shots[i - 1]["mark"] != s["mark"]:
                lint("cross-class-dip", round(ds * FPS) >= 12, unit=s["id"], grammar="4.4",
                     evidence={"from": shots[i - 1]["mark"], "to": s["mark"], "frames": round(ds * FPS), "min_frames": 12})
        elif tr.get("type") != "cut":
            lint("transition-known", False, unit=s["id"], evidence=tr, grammar="7.3")
    if lint_fail:
        raise Refused("lint failed: " + "; ".join(lint_fail))
    for i, s in enumerate(shots):
        s["f0"] = int(round(s["start_s"] * FPS))
    total_frames = int(round(shots[-1]["end_s"] * FPS))
    for i, s in enumerate(shots):
        s["f1"] = shots[i + 1]["f0"] if i + 1 < len(shots) else total_frames
        if s["f1"] <= s["f0"]:
            raise Refused(f"shot {s['id']} owns no frames")

    # AI-GENERATED share (decision "No AI-generated imagery in the Partition pilot").
    gen = sum(s["f1"] - s["f0"] for s in shots if s["mark"] == "AI-GENERATED")
    lint("ai-generated-share-zero", gen == 0, evidence={"generated_frames": gen, "frames": total_frames},
         grammar="decision 2026-10-10", stage="marks")

    # Stills: the camera, the whole first frame (A7), the resampler (A5), fill_ok for the reviewer.
    for s in shots:
        if s["kind"] in ("archive_still", "drawn") and s.get("_item", {}).get("_path"):
            if s["kind"] == "drawn":
                s.setdefault("preset", "HOLD")
            with Image.open(s["_item"]["_path"]) as im:
                size = im.size
            cam = still_camera(s, size, W, H)
            s["_cam"] = cam
            limit = PRESET_ZMAX[cam["preset"]]
            lint("still-zoom-limit", cam["z_rel_max"] <= limit + 1e-9 and cam["z_rel_max"] <= 1.3 + 1e-9, unit=s["id"],
                 stage="motion", grammar="7.2", evidence={"preset": cam["preset"], "z_max": round(cam["z_rel_max"], 4),
                                                          "limit": limit, "face": bool(s.get("face"))})
            src, dst = M.still_view(size, M.Layout(W, H), z=cam["path"][0]["z"], cx=cam["path"][0]["x"],
                                    cy=cam["path"][0]["y"], clamp=cam["clamp"])
            whole = still_is_whole(size, src, dst, W, H)
            lint("still-first-frame-whole", whole, unit=s["id"], stage="motion",
                 evidence={"src": [round(v, 2) for v in src], "dst": [round(v, 2) for v in dst], "image": list(size)}, grammar="A7")
            scale_max = cam["fit_scale"] * cam["z_max"]
            s["_resampler"] = {"method": "lanczos prescale + bicubic affine (PIL)", "ml_upscaler": False,
                               "scale_max": round(scale_max, 4), "image": list(size)}
            lint("resampler-plain", True, unit=s["id"], stage="motion", evidence=s["_resampler"], grammar="A5")
            if s["kind"] == "archive_still":
                journal.lint("fill-ok", True, stage="motion", unit=s["id"], severity="review", grammar="A7", phase="preflight",
                             evidence={"fill_ok": cam["fill_ok"], "preset": cam["preset"],
                                       "check": ("Every person in the photograph is inside the frame at some point in this shot."
                                                 if cam["fill_ok"] else "No fill: the move stays inside the photograph's own shape.")})
    if lint_fail:
        raise Refused("lint failed: " + "; ".join(lint_fail))

    # Clips: probe, conform (A6), fit at native aspect (A5, 7.5).
    for s in shots:
        if s["kind"] != "archive_video":
            continue
        item = s["_item"]
        with journal.unit("conform", s["id"], size={"driver": "seconds", "value": round(s["_dur"], 3)}, model=ENGINE_MODEL,
                          unit_kind="clip") as u:
            pr = probe_video(Path(item["_path"]))
            conf = conform_plan(item, pr)
            ntsc = any(abs(pr["fps"] - r) < 0.02 for r in (29.97, 59.94))
            if ntsc:
                lint("telecine-declared", item.get("telecined") in (True, False), unit=s["id"], stage="conform", grammar="A6",
                     evidence={"fps": round(pr["fps"], 3), "telecined": item.get("telecined"),
                               "fix": "state telecined: true|false in the ledger"})
            if conf["method"] == "ivtc":
                lint("field-order-known", conf.get("field_order") in ("tff", "bff"), unit=s["id"], stage="conform", grammar="A6",
                     evidence={"probe": pr.get("field_order"), "ledger": item.get("field_order"),
                               "fix": "state field_order: tff|bff in the ledger"})
            dar, dar_from = pr["dar"], "probe (width x SAR / height)"
            if item.get("display_aspect"):
                dar, dar_from = parse_aspect(item["display_aspect"]), "ledger display_aspect"
                if abs(dar - pr["dar"]) > 0.01 * dar:
                    journal.decision("conform", f"display aspect {dar:.4f} from the ledger, not {pr['dar']:.4f} from the file",
                                     "the ledger's display_aspect overrides the file's SAR", unit=s["id"])
            pr["dar_used"], pr["dar_from"] = dar, dar_from
            if conf["method"] == "repeat":
                journal.decision("conform", f"{pr['fps']:.3f} fps conformed to 24 by frame repeat",
                                 "A6 and GRAMMAR 7.5: no speed change; each source frame is shown 2 or 3 times", unit=s["id"])
            vw, vh = fit_video(dar, W, H)
            neutral = {"filter": NEUTRALISE_FILTER, "alteration": NEUTRALISE} if s.get("_neutralise") else None
            s["_video"] = {"probe": pr, "conform": conf, "fit": [vw, vh], "neutralise_cast": neutral,
                           "resampler": {"method": "lanczos (ffmpeg scale)", "ml_upscaler": False,
                                         "scale": round(vh / pr["height"], 4)}}
            s["_resampler"] = s["_video"]["resampler"]
            u.settings = {"conform": conf, "resampler": s["_resampler"], "neutralise_cast": neutral}
            u.extra.update(conform=conf, resampler=s["_resampler"], fit=[vw, vh], neutralise_cast=neutral)
            if neutral:
                journal.decision("conform", f"colour cast neutralised to grey ({NEUTRALISE_FILTER}, luma kept) before pillarboxing",
                                 f"neutralise_cast is set; GRAMMAR A14 marks it RECONSTRUCTED '{NEUTRALISE}'", unit=s["id"],
                                 evidence={"asset": s.get("asset"), "filter": NEUTRALISE_FILTER, "mark": s["mark"],
                                           "alterations": s.get("alterations")})
            ok_aspect = abs(vw / vh - dar) <= dar * (2.0 / vw + 2.0 / vh)
            lint("clip-aspect", ok_aspect, unit=s["id"], stage="conform",
                 evidence={"source_dar": round(dar, 4), "dar_from": dar_from, "sar": round(pr["sar"], 4),
                           "storage": [pr["width"], pr["height"]], "fit": [vw, vh], "fit_ar": round(vw / vh, 4)}, grammar="7.5")
            lint("conform-logged", True, unit=s["id"], stage="conform", evidence=conf, grammar="A6")
            lint("resampler-plain", True, unit=s["id"], stage="conform", evidence=s["_resampler"], grammar="A5")
            in_range = 0 <= s["in_s"] < pr["duration_s"]
            lint("clip-in-out", in_range, unit=s["id"], stage="conform",
                 evidence={"in_s": s["in_s"], "out_s": s["out_s"], "duration_s": pr["duration_s"],
                           "duration_from": pr["duration_from"]}, grammar="7.1")
            hold = max(0.0, s["out_s"] - pr["duration_s"])
            s["_video"]["hold_s"] = round(hold, 4)
            if hold > 1.0 / FPS:
                retimed = s["mark"] == "RECONSTRUCTED" and "re-timed" in (s.get("alterations") or [])
                lint("clip-hold", hold <= MAX_HOLD_S or retimed, unit=s["id"], stage="conform", grammar="7.1",
                     severity="block" if hold > MAX_HOLD_S else "warn",
                     evidence={"hold_s": round(hold, 3), "max_s": MAX_HOLD_S, "retimed": retimed,
                               "why": "the out point is past the end of the video stream; its last frame would be held"})
            if s.get("sound", {}).get("mode", "own") == "own" and not pr["has_audio"]:
                lint("clip-sound", False, unit=s["id"], stage="conform", severity="warn",
                     evidence="sound is own but the file has no audio stream: silence")
    if lint_fail:
        raise Refused("lint failed: " + "; ".join(lint_fail))

    # On-screen text: cards, lower thirds, subtitles.
    for s in shots:
        if s.get("_card") in ("silent",):
            first = (s.get("text") or [""])[0]
            lint("silent-card-form", bool(SILENT_RE.match(first)), unit=s["id"], evidence=first, grammar="9")
        if s.get("_card") == "chapter":
            first = (s.get("text") or [""])[0]
            lint("chapter-card-form", bool(CHAPTER_RE.match(first)), unit=s["id"], evidence=first, grammar="9")
    lower_thirds, subs, overlays = [], [], []
    for t in texts:
        if t["kind"] == "lower_third":
            ln = list(t.get("lines") or [])
            kind = "place" if len(ln) == 2 else "speaker"
            ok = (kind == "place") or (len(ln) == 3 and ln[2].endswith(LT_SUFFIXES))
            if t.get("flag"):
                ok = ok and bool(FLAG_RE.match(t["flag"]))
            lint("lower-third-format", ok, unit=t["id"], evidence={"lines": ln, "flag": t.get("flag")}, grammar="9")
            # A16: a lower third comes and goes; it is drawn for at most M.LT_MAX_S whatever the screenplay's end_s
            shown = M.lower_third_span(float(t["start_s"]), float(t["end_s"]))
            lower_thirds.append({"id": t["id"], "start": shown[0], "end": shown[1], "end_s": float(t["end_s"]), "lines": ln,
                                 "kind": kind, "flag": t.get("flag")})
        elif t["kind"] == "overlay":
            ln = list(t.get("lines") or [])
            start, end = float(t["start_s"]), float(t["end_s"])
            over_card = any(a < end and b > start for a, b in
                            ((x["start_s"], x["start_s"] + x["_dur"]) for x in shots if x["mark"] == "CARD"))
            over_lt = any(float(o["start_s"]) < end and float(o["end_s"]) > start for o in texts if o["kind"] == "lower_third")
            lint("overlay-format", len(ln) == 1 and bool(ln[0].strip()) and not over_card and not over_lt, unit=t["id"],
                 grammar="9", evidence={"lines": ln, "over_card": over_card, "over_lower_third": over_lt})
            overlays.append({"id": t["id"], "start": start, "end": end, "text": ln[0] if ln else ""})
        elif t["kind"] in CARD_TEXT_KINDS:
            pass                    # the card shot draws these words; the element feeds the subtitles
        else:
            lint("kind-supported", False, unit=t["id"], grammar="12",
                 evidence={"kind": t["kind"], "drawn": ["lower_third", "overlay", *sorted(CARD_TEXT_KINDS)]})
    lt_drawn_end = {lt["id"]: lt["end"] for lt in lower_thirds}
    if burn_subtitles:
        for c in play.get("subtitle_source", []):
            if c.get("en"):
                # A16: a lower third's bracketed cue ends when the drawn lower third does
                end = min(float(c["end_s"]), lt_drawn_end.get(c.get("ref"), float("inf")))
                if c.get("ref") in lt_drawn_end:
                    lint("subtitle-lower-third-span", end > float(c["start_s"]), unit=c.get("ref"), grammar="10, A16",
                         evidence={"cue_start_s": float(c["start_s"]), "cue_end_s": float(c["end_s"]), "drawn_end_s": round(end, 4),
                                   "fix": "start the lower third's cue while the lower third is drawn (A16 clips it to "
                                          f"{M.LT_MAX_S:.2f} s)"})
                subs.append({"ref": c.get("ref"), "start": float(c["start_s"]), "end": end, "text": c["en"]})
    screen_text = [x for s in shots for x in (s.get("text") or [])] + [x for lt in lower_thirds for x in lt["lines"] + [lt["flag"] or ""]]
    screen_text += [o["text"] for o in overlays]
    screen_text += [s["detail"] for s in shots] + [s["label"] for s in shots] + [c["text"] for c in subs]
    dashes = [x for x in screen_text if EM_DASH in x]
    lint("no-em-dash", not dashes, evidence=dashes[:5], grammar="9")
    subcues = sorted(((float(c["start_s"]), float(c["end_s"]), c.get("ref")) for c in play.get("subtitle_source", [])))
    clash = [{"a": a[2], "b": b[2], "overlap_s": round(a[1] - b[0], 3)} for a, b in zip(subcues, subcues[1:]) if b[0] < a[1] - 1e-9]
    # burned in, two cues would draw over each other; as tracks, a player shows them stacked
    lint("subtitle-overlap", not clash, severity="block" if burn_subtitles else "warn", grammar="10",
         evidence={"overlaps": clash, "burned": burn_subtitles})
    for c in cues:
        start, end = float(c.get("start_s", 0)), float(c.get("end_s", 0))
        fi, fo = float(c.get("fade_in_s", 0) or 0), float(c.get("fade_out_s", 0) or 0)
        ok = end > start and fi >= 0 and fo >= 0 and fi + fo <= (end - start) + 1e-9
        lint("cue-span", ok, unit=c.get("id"), grammar="12, A19",
             evidence={"start_s": start, "end_s": end, "fade_in_s": fi, "fade_out_s": fo,
                       "fix": None if ok else "end_s after start_s, fades of 0 or more that fit inside the cue"})
    vl = voice_lines(play, film)
    collisions = voice_collisions(vl)
    lint("voice-overlap", not collisions, stage="scout", grammar="founder ruling 2026-10-10",
         evidence={"collisions": collisions, "gap_s": VOICE_GAP_S, "lines": len(vl),
                   "fix": "move the lines, or render with --fit-voices" if collisions else None})
    for ln in lines:
        if ln.get("kind") not in VOICE_KINDS or ln.get("archival_audio"):
            continue
        if "gain_db" in ln:
            # A13 levels every synthetic line to the dialogue target; the mood offset (A14) is the only level change after it
            lint("voice-gain-db", False, unit=ln["id"], grammar="A13, A14",
                 evidence={"gain_db": ln["gain_db"], "fix": "drop gain_db; a narration line's level moves only by its delivery mood"})
        if "delivery" in ln:
            d = ln["delivery"] if isinstance(ln["delivery"], dict) else {}
            mood = d.get("mood")
            off = MOOD_OFFSET_DB.get(mood)
            ok = ln.get("kind") == "narration" and off is not None and -MOOD_OFFSET_MAX_DB - 1e-9 <= off <= 0.0
            lint("narrator-delivery", ok, unit=ln["id"], grammar="A14",
                 evidence={"kind": ln.get("kind"), "mood": mood, "offset_db": off, "max_abs_db": MOOD_OFFSET_MAX_DB,
                           "moods": MOOD_OFFSET_DB,
                           "fix": None if ok else ("delivery is for narration lines only" if ln.get("kind") != "narration" else
                                                   f"mood must be one of {sorted(MOOD_OFFSET_DB)}" if off is None else
                                                   f"offset {off:+g} dB is outside -{MOOD_OFFSET_MAX_DB:g} to 0 dB")})
    if lint_fail:
        raise Refused("lint failed: " + "; ".join(lint_fail))

    speakers = {sp["id"]: sp for sp in (play.get("cast") or {}).get("speakers", [])}
    # A19: where digital silence is meant (a shot, a part, a cue or a top-level moment marked silence: intended)
    silences = []
    for s in shots:
        if s.get("silence") == "intended":
            silences.append((s["f0"] / FPS, s["f1"] / FPS))
    for part in play["parts"]:
        own = [s for s in shots if s["_part"] == part["id"]]
        if part.get("silence") == "intended" and own:
            silences.append((own[0]["f0"] / FPS, own[-1]["f1"] / FPS))
    for x in list(cues) + list(play.get("moments", [])):
        if x.get("silence") == "intended":
            silences.append((float(x["start_s"]), float(x["end_s"])))
    card_spans = [(s["f0"] / FPS, s["f1"] / FPS) for s in shots if s["mark"] == "CARD"]
    imagery = [s for s in shots if s["mark"] != "CARD"]
    plan = {
        "film": str(film), "title": play.get("title", film.name), "slug": play.get("slug", film.name),
        "W": W, "H": H, "fps": FPS, "frames": total_frames, "duration_s": total_frames / FPS,
        "shots": shots, "assets": {k: {kk: vv for kk, vv in v.items()} for k, v in assets.items()},
        "lines": lines, "cues": cues, "speakers": speakers, "narrator_voice": narrator_voice(play), "silences": sorted(silences),
        "runtime_target_s": play.get("runtime_target_s"),
        "lower_thirds": lower_thirds, "overlays": overlays, "subtitles": subs, "burn_subtitles": burn_subtitles,
        "marks": [{"start": s["f0"] / FPS, "cls": s["mark"], "detail": s["detail"], "label": s["label"]} for s in shots],
        "card_spans": card_spans, "wm_start": (imagery[0]["f0"] / FPS) if imagery else None,
    }
    plan["credits"] = credits_blocks(plan)
    return plan


def trim_plan(plan: dict, until_s: float) -> dict:
    """The plan cut after the last shot that starts before ``until_s`` (a check render): that
    shot ends where it ends, and what lies past it (shots, lines, cues, text) is dropped."""
    if until_s <= 0:
        raise Refused(f"--until {until_s:g}: must be after the film's start")
    shots = [s for s in plan["shots"] if s["f0"] < until_s * FPS]
    if len(shots) == len(plan["shots"]):
        return plan
    end = shots[-1]["f1"]
    end_s = end / FPS
    out = dict(plan, shots=shots, frames=end, duration_s=end_s, marks=plan["marks"][:len(shots)])
    out["lines"] = [x for x in plan["lines"] if float(x["start_s"]) < end_s]
    out["cues"] = [x for x in plan["cues"] if float(x["start_s"]) < end_s]
    for k in ("lower_thirds", "overlays", "subtitles"):
        out[k] = [x for x in plan[k] if x["start"] < end_s]
    out["card_spans"] = [(a, b) for a, b in plan["card_spans"] if a < end_s]
    out["until_s"] = until_s
    return out


# --------------------------------------------------------------------------
# Pictures (worker side)
# --------------------------------------------------------------------------


class VideoReader:
    """Decodes one clip, conformed and fitted, from a local start time onward;
    frames are asked for in increasing time."""

    def __init__(self, shot: dict, start_local: float):
        self.shot_id = shot["id"]
        v = shot["_video"]
        self.vw, self.vh = v["fit"]
        self.nbytes = self.vw * self.vh * 3
        self.t0 = start_local
        conform = v["conform"]["filter"]
        neutral = (v.get("neutralise_cast") or {}).get("filter")
        vf = "".join(f + "," for f in (conform, neutral) if f) + f"scale={self.vw}:{self.vh}:flags=lanczos,setsar=1,format=rgb24"
        ss = shot["in_s"] + start_local
        dur = shot["_dur"] - start_local + 2.0 / FPS
        self.err = tempfile.TemporaryFile()
        self.src, self.vf, self.in_s = shot["_item"]["_path"], vf, float(shot["in_s"])
        self.src_dur = float((v.get("probe") or {}).get("duration_s") or 0.0)
        self.src_fps = float((v.get("probe") or {}).get("fps") or 0.0) or float(FPS)
        self.proc = subprocess.Popen([ffmpeg(), "-v", "error", "-filter_threads", "1", "-threads", "1",
                                      "-ss", f"{ss:.4f}", "-t", f"{dur:.4f}", "-i", self.src,
                                      "-an", "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                     stdout=subprocess.PIPE, stderr=self.err, stdin=subprocess.DEVNULL)
        self.idx, self.last, self.held = -1, None, 0

    def _decode_last(self, ss: float) -> bytes | None:
        """The last whole frame decoded from ``ss`` to the end of the stream, or None."""
        proc = subprocess.Popen([ffmpeg(), "-v", "error", "-filter_threads", "1", "-threads", "1",
                                 "-ss", f"{max(0.0, ss):.4f}", "-i", self.src,
                                 "-an", "-vf", self.vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        last = None
        try:
            while True:
                buf = proc.stdout.read(self.nbytes)
                if len(buf) < self.nbytes:
                    break
                last = buf
        finally:
            proc.stdout.close()
            proc.wait()
        return last

    def starts_in_hold(self) -> bool:
        """The reader's seek point is at or past the source's last frame (one output frame of slack
        for the conform's rounding). An empty decode from anywhere earlier is a real decode error
        and raises with ffmpeg's own message."""
        return self.src_dur > 0 and self.in_s + self.t0 >= self.src_dur - 1.0 / self.src_fps - 1.0 / FPS

    def tail_frame(self) -> bytes | None:
        """The clip's last decodable frame, conformed and fitted as every other frame is: the
        frame a hold shows. A reader that starts at or past it (the next shot dissolving out of a
        held clip, in its own segment) decodes nothing from its seek point, so the frame is read
        from the stream's last TAIL_S seconds, or failing that from the in point."""
        last = self._decode_last(max(self.in_s, self.src_dur - TAIL_S)) if self.src_dur else None
        return last if last is not None else self._decode_last(self.in_s)

    def frame(self, t_local: float) -> Image.Image:
        want = int(round((t_local - self.t0) * FPS))
        while self.idx < want:
            buf = self.proc.stdout.read(self.nbytes)
            if len(buf) < self.nbytes:
                self.held += 1          # an output frame past the stream's last: the hold (GRAMMAR 7.1)
                if self.last is None and self.starts_in_hold():
                    self.last = self.tail_frame()
                break
            self.last, self.idx = buf, self.idx + 1
        if self.last is None:
            self.err.seek(0)
            raise EncodeError(f"no frames decoded for {self.shot_id}: {self.err.read().decode(errors='replace')[-500:]}")
        return Image.frombytes("RGB", (self.vw, self.vh), self.last)

    def close(self):
        try:
            self.proc.stdout.close()
        except Exception:
            pass
        try:
            self.proc.kill()
            self.proc.wait(timeout=5)
        except Exception:
            pass
        self.err.close()


class Pictures:
    """Each shot's own picture at a local time, before transitions and overlays."""

    def __init__(self, plan: dict):
        self.plan = plan
        self.L = M.Layout(plan["W"], plan["H"])
        self.fonts = M.Fonts()
        self.stills: dict[str, Image.Image] = {}
        self.readers: dict[str, VideoReader] = {}
        self._held: dict[str, int] = {}          # held frames of readers already closed, by the clip's shot id

    def still(self, s: dict) -> Image.Image:
        key = s["id"]
        if key not in self.stills:
            img = Image.open(s["_item"]["_path"]).convert("RGB")
            need = s["_cam"]["fit_scale"] * s["_cam"]["z_max"]
            if need < 1.0:                       # pre-scale big scans with Lanczos (A5)
                img = img.resize((max(2, math.ceil(img.width * need)), max(2, math.ceil(img.height * need))), Image.Resampling.LANCZOS)
            self.stills[key] = img
        return self.stills[key]

    def video(self, s: dict, t_local: float) -> Image.Image:
        r = self.readers.get(s["id"])
        if r is None or t_local < r.t0 - 1e-9:
            if r:
                self._retire(r)
            r = self.readers[s["id"]] = VideoReader(s, max(0.0, t_local))
        fr = r.frame(t_local)
        out = Image.new("RGB", (self.plan["W"], self.plan["H"]), M.PALETTE["letterbox"])
        out.paste(fr, ((self.plan["W"] - r.vw) // 2, (self.plan["H"] - r.vh) // 2))
        return out

    def card(self, s: dict, t: float) -> Image.Image:
        L, f, dur = self.L, self.fonts, s["_dur"]
        blank = Image.new("RGB", (L.W, L.H), M.PALETTE["black"])
        text = list(s.get("text") or [])
        ck = s["_card"]
        if ck == "black":
            return blank
        if ck == "title":
            img = M.title_card_frame(blank, t, start=0.0, end=dur, title=text[0] if text else "", fonts=f)
        elif ck == "chapter":
            m = CHAPTER_RE.match(text[0]) if text else None
            img = M.chapter_card_frame(blank, t, start=0.0, end=dur, number=int(m.group(1)) if m else 0,
                                       title=m.group(2) if m else (text[0] if text else ""),
                                       dates=text[1] if len(text) > 1 else "", fonts=f)
        elif ck == "credits":
            img = M.credits_frame(blank, t, start=0.0, blocks=self.plan["credits"], fonts=f)
        else:                                    # silent, perspective, statement
            img = M.silent_card_frame(blank, t, start=0.0, end=dur, statement=text[0] if text else "",
                                      searched=text[1] if len(text) > 1 else None, fonts=f)
        return img.convert("RGB")

    def shot(self, i: int, t_local: float) -> Image.Image:
        s = self.plan["shots"][i]
        if s["kind"] in ("card", "black"):
            return self.card(s, t_local)
        if s["kind"] == "archive_video":
            return self.video(s, t_local)
        cam = s["_cam"]
        img = self.still(s)
        p = cam["path"]
        if len(p) == 1 or t_local < cam["open_s"]:
            return M.fit_still(img, self.L, z=p[0]["z"], cx=p[0]["x"], cy=p[0]["y"], clamp=cam["clamp"])
        return M.rostrum_move(img, self.L, t_local - cam["open_s"], s["_dur"] - cam["open_s"], p[0], p[-1],
                              via=p[1:-1], clamp=cam["clamp"])

    def _retire(self, r: VideoReader) -> None:
        self._held[r.shot_id] = self._held.get(r.shot_id, 0) + r.held
        r.close()

    def held(self) -> dict[str, int]:
        """Frames that showed a clip's held last frame, by the clip's shot id: a dissolve's
        outgoing clip counts under its own id, not the segment's."""
        out = dict(self._held)
        for r in self.readers.values():
            out[r.shot_id] = out.get(r.shot_id, 0) + r.held
        return {k: v for k, v in out.items() if v}

    def close(self):
        for r in self.readers.values():
            self._retire(r)
        self.readers.clear()


def picture_level(plan: dict, f: int, i: int) -> float:
    """Picture level 0..1 at frame f (owned by shot i) through a dip to black:
    the incoming shot's own dip, or the next shot's dip in this one's tail.
    0 is the dip's black hold."""
    shots = plan["shots"]
    t = f / FPS
    tl = t - shots[i]["f0"] / FPS
    tr = shots[i]["transition_in"]
    level = 1.0
    if tr.get("type") == "dip" and tl < float(tr["s"]) / 2:
        level = M.dip_level(tl + float(tr["s"]) / 2, float(tr["s"]))
    if i + 1 < len(shots):
        ntr = shots[i + 1]["transition_in"]
        if ntr.get("type") == "dip":
            ds = float(ntr["s"])
            dt = shots[i + 1]["f0"] / FPS - t
            if 0 < dt <= ds / 2:
                level = min(level, M.dip_level(ds / 2 - dt, ds))
    return level


def compose(plan: dict, pics: Pictures, f: int, i: int, probe: dict | None = None) -> Image.Image:
    """Frame f (owned by shot i): picture with its transition, then the lower
    thirds, burned subtitles, watermark and the provenance mark (A16)."""
    shots = plan["shots"]
    t = f / FPS
    s = shots[i]
    tl = t - s["f0"] / FPS
    img = pics.shot(i, tl)
    tr = s["transition_in"]
    if tr.get("type") == "dissolve" and i > 0 and tl < float(tr["s"]):
        prev = shots[i - 1]
        a = pics.shot(i - 1, t - prev["f0"] / FPS)
        img = Image.blend(a, img, M.dissolve_weight(tl, float(tr["s"])))
    level = picture_level(plan, f, i)
    if level <= 0.0:
        # a dip's black hold: every pixel off, overlays included (founder ruling 2026-10-10)
        return Image.new("RGB", (plan["W"], plan["H"]), (0, 0, 0))
    if level < 1.0:
        arr = np.asarray(img, dtype=np.float32) * level
        img = Image.fromarray(arr.astype(np.uint8))
    rgba = img.convert("RGBA")
    lt_top = None
    for lt in plan["lower_thirds"]:
        if lt["start"] <= t < lt["end"]:
            rgba = M.lower_third_frame(rgba, t, start=lt["start"], end=lt["end"], lines=lt["lines"], fonts=pics.fonts,
                                       kind=lt["kind"], flag=lt["flag"])
            lt_top = M.lower_third_top(pics.L, lt["lines"], pics.fonts, kind=lt["kind"], flag=lt["flag"])
    for o in plan["overlays"]:
        if o["start"] <= t < o["end"]:
            rgba = M.overlay_frame(rgba, t, start=o["start"], end=o["end"], text=o["text"], fonts=pics.fonts)
    for c in plan["subtitles"]:
        if c["start"] <= t < c["end"]:
            rgba = M.subtitle_frame(rgba, c["text"], pics.fonts.structure_medium, raise_above=lt_top)
    if plan["wm_start"] is not None:
        rgba = M.watermark(rgba, t, start=plan["wm_start"], card_spans=plan["card_spans"])
    if probe is not None:                # the shape probes before the mark, so the shape check never reads the picture
        probe["bare_corner"] = [rgba.getpixel(at)[:3] for at in M.glyph_shape_probes(pics.L)]
    rgba = M.mark_frame(rgba, t, plan["marks"], pics.fonts)
    return rgba.convert("RGB")


def mark_probe(plan: dict) -> tuple[int, int]:
    """The pixel at the centre of the class glyph (A16, BRAND-KIT 11), solid in
    every glyph shape: the glyph is the mark on every frame, label or not."""
    return M.glyph_centre(M.Layout(plan["W"], plan["H"]))


def between_hues(px, a, b, tol: float = 3.0) -> bool:
    """True when px lies on the segment from hue a to hue b (within tol)."""
    p, a, b = (np.asarray(v, dtype=float) for v in (px, a, b))
    d = b - a
    u = float(np.clip(np.dot(p - a, d) / max(float(np.dot(d, d)), 1e-9), 0.0, 1.0))
    return float(np.max(np.abs(p - (a + u * d)))) <= tol


def expected_probe(plan: dict, cls: str, at: tuple[int, int], bare) -> np.ndarray:
    """A shape-probe pixel as ``cls``'s glyph tile composes it over ``bare``,
    the same pixel of the frame before the mark was drawn. Composed by PIL,
    as mark_frame composes it."""
    L = M.Layout(plan["W"], plan["H"])
    tile, (ox, oy) = M.glyph_tile(L.W, L.H, cls)
    x, y = at
    px = Image.new("RGBA", (1, 1), tuple(int(v) for v in bare[:3]) + (255,))
    px.alpha_composite(tile.crop((x - ox, y - oy, x - ox + 1, y - oy + 1)))
    return np.array(px.getpixel((0, 0))[:3], dtype=int)


def glyph_shape_ok(plan: dict, arr: np.ndarray, cls: str, bare) -> bool:
    """The glyph's shape per class (A16 refined), independent of the picture:
    each shape-probe pixel must be what ``cls``'s own glyph composes there
    over the bare frame's pixel (``bare``: one RGB per probe, or one RGB for
    all). The square leaves its hue at both probes; the dot and the diamond
    leave the picture under the glyph's edge and its contact disc. At every
    engine resolution some probe channel of a wrong shape at the same hue
    stays more than 1 away whatever the bare value (0 to 255), so a wrong
    shape fails over any picture."""
    probes = M.glyph_shape_probes(M.Layout(plan["W"], plan["H"]))
    bares = list(bare) if bare and isinstance(bare[0], (tuple, list, np.ndarray)) else [bare] * len(probes)
    for (x, y), b in zip(probes, bares):
        if int(np.max(np.abs(arr[y, x, :3].astype(int) - expected_probe(plan, cls, (x, y), b)))) > 1:
            return False
    return True


def check_mark(plan: dict, arr: np.ndarray, f: int, i: int, bare=None) -> str:
    """'ok' when the glyph's centre shows the owning shot's class hue and its
    corner the class's shape (A16 refined); 'fade' inside the 4-frame class
    crossfade when the centre shows a mix of the outgoing and incoming hues;
    'dip' on a dip's black hold (all pixels off, A11, checked as all zero);
    'shape' when the hue is right and the shape wrong; else 'fail'. ``bare``
    is the shape-probe pixels before the mark was drawn (``compose(...,
    probe=)``); without them the shape cannot be judged and the frame fails."""
    x, y = mark_probe(plan)
    s = plan["shots"][i]
    if picture_level(plan, f, i) <= 0.0:
        return "dip" if not arr.any() else "fail"
    px = arr[y, x, :3].astype(int)
    if i > 0 and plan["shots"][i - 1]["mark"] != s["mark"] and f - s["f0"] < round(M.LABEL["fade"] * FPS):
        return "fade" if between_hues(px, M.MARK_HUE[plan["shots"][i - 1]["mark"]], M.MARK_HUE[s["mark"]]) else "fail"
    if np.max(np.abs(px - np.array(M.MARK_HUE[s["mark"]]))) > 2:
        return "fail"
    if bare is None:
        return "fail"
    return "ok" if glyph_shape_ok(plan, arr, s["mark"], bare) else "shape"


def render_frame(plan: dict, f: int, pics: Pictures | None = None, probe: dict | None = None) -> np.ndarray:
    """One finished frame as an HxWx3 uint8 array (for tests and previews);
    ``probe`` receives the bare glyph corner, as compose gives it."""
    own = pics is None
    pics = pics or Pictures(plan)
    try:
        i = max(k for k, s in enumerate(plan["shots"]) if s["f0"] <= f)
        return np.asarray(compose(plan, pics, f, i, probe))
    finally:
        if own:
            pics.close()


def encoder_cmd(plan: dict, out: Path) -> list[str]:
    return [ffmpeg(), "-v", "error", "-y", "-filter_threads", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{plan['W']}x{plan['H']}",
            "-r", str(FPS), "-i", "-", "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv444p,"
            "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-threads", "1",
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-video_track_timescale", str(FPS * 1000), "-f", "mp4", str(out)]


def _unlink_quietly(path: Path, tries: int = 5) -> None:
    """Remove a partial file; Windows may hold it a moment after its writer dies
    (WinError 32). A leftover .part is overwritten by the next attempt."""
    for k in range(tries):
        try:
            path.unlink(missing_ok=True)
            return
        except OSError:
            time.sleep(0.2 * (k + 1))


def render_segment(plan: dict, i: int, seg: str, sink=None) -> dict:
    """Worker: render shot i's frames to a cached segment. Returns stats."""
    t_start = time.perf_counter()
    s = plan["shots"][i]
    seg = Path(seg)
    part = seg.with_name(seg.name + ".part")
    frames = s["f1"] - s["f0"]
    if sink is not None:
        sink.put({"lens": "unit.start", "stage": "motion", "unit": s["id"], "size": {"driver": "frames", "value": frames}})
    pics = Pictures(plan)
    err = tempfile.TemporaryFile()
    enc = subprocess.Popen(encoder_cmd(plan, part), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=err)
    stats = {"ok": 0, "fade": 0, "dip": 0, "fail": 0, "shape": 0, "fail_frames": [], "label": 0, "glyph_only": 0}
    first_whole, first_detail = None, None
    ms = []
    try:
        for f in range(s["f0"], s["f1"]):
            ft = time.perf_counter()
            probe: dict = {}
            arr = np.asarray(compose(plan, pics, f, i, probe))
            res = check_mark(plan, arr, f, i, probe.get("bare_corner"))
            stats[res] += 1
            if res in ("ok", "fade"):           # A16: which of the two carried the provenance on this frame
                st = M.mark_state(f / FPS, plan["marks"])
                stats["label" if st and st["label_alpha"] > 0 else "glyph_only"] += 1
            if res in ("fail", "shape") and len(stats["fail_frames"]) < 10:
                stats["fail_frames"].append(f)
            if f == s["f0"] and s["kind"] == "archive_still":
                first_detail = {}
                first_whole = still_first_frame_whole(plan, pics, i, first_detail)
            try:
                enc.stdin.write(arr.tobytes())
            except (BrokenPipeError, OSError) as exc:
                err.seek(0)
                raise EncodeError(f"segment encoder for {s['id']} stopped: {err.read().decode(errors='replace')[-500:]}") from exc
            ms.append((time.perf_counter() - ft) * 1000)
            k = f - s["f0"]
            if sink is not None and (k % FPS == 0 or f == s["f1"] - 1):
                sink.put({"lens": "frame", "stage": "motion", "unit": s["id"], "frame": f, "frames": plan["frames"],
                          "tc_s": round(f / FPS, 3), "ms": round(ms[-1], 1),
                          "mark": {"class": s["mark"], "detail": s["detail"], "label": s["label"]}, "preview": None})
        held_by = pics.held()                                  # before close() clears the readers
        enc.stdin.close()
        if enc.wait():
            err.seek(0)
            raise EncodeError(f"segment encoder for {s['id']} exited {enc.returncode}: {err.read().decode(errors='replace')[-500:]}")
        got = count_frames(part)
        if got != frames:
            raise EncodeError(f"segment {s['id']} holds {got} frames, expected {frames}")
        os.replace(part, seg)
    except BaseException:
        try:
            enc.kill()
            enc.wait(timeout=10)
        except Exception:
            pass
        _unlink_quietly(part)
        raise
    finally:
        pics.close()
        err.close()
    result = {"shot": s["id"], "frames": frames, "wall_s": time.perf_counter() - t_start,
              "ms_mean": round(sum(ms) / len(ms), 2) if ms else None, "mark": stats, "first_frame_whole": first_whole,
              "first_frame_detail": first_detail, "held_frames": held_by.get(s["id"], 0), "held_by_shot": held_by}
    seg.with_name(seg.name + ".json").write_text(json.dumps(result), encoding="utf-8")
    return result


def held_totals(results: dict[int, dict], ids: list[str]) -> dict[str, int]:
    """Held frames per clip over the whole film, summed over every segment that shows it: the
    clip's own and the next shot's, where a dissolve carries it out. GRAMMAR 7.1's 2 s is per clip,
    never per segment. A segment cached before held_by_shot existed counts under its own shot."""
    out: dict[str, int] = {}
    for i, r in results.items():
        by = r.get("held_by_shot")
        if by is None:
            by = {ids[i]: r.get("held_frames", 0)}
        for sid, k in by.items():
            if k:
                out[sid] = out.get(sid, 0) + int(k)
    return out


def still_first_frame_whole(plan: dict, pics: Pictures, i: int, detail: dict | None = None) -> bool:
    """Pixel evidence for A7, on the still's own layer at its first frame
    (before any dissolve, dip or overlay is composited): outside the
    photograph's fitted rectangle every pixel is the black field, and inside
    it the picture matches the whole photograph.

    The reference is independent of the camera: the original file, Lanczos-
    resized to the whole-image fit and centred. The two are compared after a
    box downsample (8x at 1080p), because a dense photograph resampled two
    ways (the renderer's bicubic affine after a Lanczos prescale, and a plain
    Lanczos resize) differs pixel by pixel while agreeing once box-averaged.

    Two scores, both on the box-downsampled pair: the mean over the whole
    picture (under A7_FULL_LIMIT), and the mean over its outer band, the
    outer 5% of the fitted rectangle on each side (under A7_BAND_LIMIT). A
    zoom about the centre shifts content most at the edges, and the whole-
    picture mean dilutes that: a 1% crop of two of the trailer's stills
    scored 3.8 and 5.0 there, under 6. On the trailer's 10 real stills at
    1080p the band scores 0.5 to 1.6 whole and 8.5 to 24.5 at z 1.01
    (2026-10-10)."""
    s = plan["shots"][i]
    raw = np.asarray(pics.shot(i, 0.0)).astype(np.float32)
    W, H = plan["W"], plan["H"]
    with Image.open(s["_item"]["_path"]) as im:
        orig = im.convert("RGB")
    k = min(W / orig.width, H / orig.height)
    fx0, fy0 = (W - orig.width * k) / 2.0, (H - orig.height * k) / 2.0
    fx1, fy1 = W - fx0, H - fy0
    outside = np.ones(raw.shape[:2], bool)
    outside[max(0, math.floor(fy0) - 1):math.ceil(fy1) + 1, max(0, math.floor(fx0) - 1):math.ceil(fx1) + 1] = False
    field = np.array(M.PALETTE["letterbox"], dtype=np.float32)
    outside_max = float(np.max(np.abs(raw[outside] - field))) if outside.any() else 0.0
    ref = np.zeros_like(raw)
    rw, rh = max(1, round(orig.width * k)), max(1, round(orig.height * k))
    x0, y0 = round(fx0), round(fy0)
    ref[y0:y0 + rh, x0:x0 + rw] = np.asarray(orig.resize((rw, rh), Image.Resampling.LANCZOS), dtype=np.float32)[: H - y0, : W - x0]
    f = max(2, round(H / 135))
    hh, ww = (H // f) * f, (W // f) * f

    def low(a):
        return a[:hh, :ww].reshape(hh // f, f, ww // f, f, 3).mean(axis=(1, 3))

    d = np.abs(low(raw) - low(ref)).mean(axis=2)
    diff = float(d.mean())
    # The band sits on the photograph's content: a uniform mount or border is trimmed first, because a zoom moves
    # nothing visible inside it and the band would compare blank against blank.
    cl, ct, cr, cb = content_box(orig)
    gx0, gy0 = (fx0 + cl * k) / f, (fy0 + ct * k) / f
    gx1, gy1 = (fx0 + (orig.width - cr) * k) / f, (fy0 + (orig.height - cb) * k) / f
    bw, bh = A7_BAND * (gx1 - gx0), A7_BAND * (gy1 - gy0)
    yy, xx = np.mgrid[0:d.shape[0], 0:d.shape[1]] + 0.5          # cell centres, in low-res cells
    inside = (xx >= gx0 + 1) & (xx <= gx1 - 1) & (yy >= gy0 + 1) & (yy <= gy1 - 1)   # off the photograph's edge cells
    core = (xx > gx0 + bw) & (xx < gx1 - bw) & (yy > gy0 + bh) & (yy < gy1 - bh)
    band = inside & ~core
    band_diff = float(d[band].mean()) if band.any() else diff
    g = low(ref).mean(axis=2)                                     # the reference's own detail in the band: what a shift would change
    dx, dy = np.abs(np.diff(g, axis=1)), np.abs(np.diff(g, axis=0))
    band_detail = float((dx[band[:, 1:] & band[:, :-1]].mean() + dy[band[1:, :] & band[:-1, :]].mean()) / 2) if band.any() else 0.0
    whole = outside_max <= 2.0 and diff < A7_FULL_LIMIT and band_diff < A7_BAND_LIMIT
    verdict = "not whole" if not whole else ("inconclusive" if band_detail < A7_DETAIL_FLOOR else "whole")
    if detail is not None:
        detail.update(outside_max=round(outside_max, 2), low_pass_mean_diff=round(diff, 3), band_mean_diff=round(band_diff, 3),
                      band_detail=round(band_detail, 3), mount_trim_px={"left": cl, "top": ct, "right": cr, "bottom": cb},
                      limits={"outside": 2.0, "full": A7_FULL_LIMIT, "band": A7_BAND_LIMIT, "detail_floor": A7_DETAIL_FLOOR},
                      box=f, verdict=verdict)
    return whole


def content_box(img: Image.Image) -> tuple[int, int, int, int]:
    """How many pixels of uniform border (a mount, a scanner's margin) each
    side of the photograph carries: rows or columns, from the edge in, whose
    luminance varies by less than A7_MOUNT_STD and stays near the edge's tone.
    At most 40% per side. Returns (left, top, right, bottom)."""
    a = np.asarray(img.convert("L"), dtype=np.float32)

    def run(lines: np.ndarray) -> int:
        std, mean = lines.std(axis=1), lines.mean(axis=1)
        cap = int(0.4 * len(lines))
        ok = (std[:cap] < A7_MOUNT_STD) & (np.abs(mean[:cap] - mean[0]) < 2 * A7_MOUNT_STD)
        return int(np.argmin(ok)) if not ok.all() else cap

    return run(a.T), run(a), run(a.T[::-1]), run(a[::-1])


def preflight_stills(plan: dict, journal: Journal) -> list[str]:
    """A7's pixel check for every still, run before any frame is rendered: one
    frame per still, its own layer. Returns the shots that are not whole."""
    pics = Pictures(plan)
    bad = []
    try:
        for i, s in enumerate(plan["shots"]):
            if s["kind"] == "archive_still" and s.get("_cam"):
                ev: dict = {}
                ok = still_first_frame_whole(plan, pics, i, ev)
                journal.lint("still-first-frame-whole-pixels", ok, stage="scout", unit=s["id"], grammar="A7",
                             phase="preflight", evidence=dict(ev, enters_by=s["transition_in"].get("type")),
                             status="inconclusive" if ev.get("verdict") == "inconclusive" else None)
                if not ok:
                    bad.append(s["id"])
    finally:
        pics.close()
    return bad


# --------------------------------------------------------------------------
# Audio
# --------------------------------------------------------------------------


def _read_wav(path: Path) -> np.ndarray:
    import soundfile as sf
    x, rate = sf.read(str(path), dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    if rate != AUDIO_RATE:
        n = int(round(len(x) * AUDIO_RATE / rate))
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
    return x


def speech_active(x: np.ndarray, gain_db: float = 0.0) -> np.ndarray:
    """The samples of a voice line that count as speech once it is placed:
    over -60 dBFS (DUCK_VOICE_THRESHOLD) after the placement gain (a mood
    offset or an archival line's gain_db), so the span is measured on what
    the mix hears, not on the take before its offset (T1e review)."""
    return np.flatnonzero(np.abs(x) * np.float32(10 ** (gain_db / 20)) > DUCK_VOICE_THRESHOLD)


def _place(buf: np.ndarray, x: np.ndarray, at_s: float, gain_db: float = 0.0, end_s: float | None = None):
    i = int(round(at_s * AUDIO_RATE))
    if i >= len(buf):
        return 0
    if end_s is not None:
        x = x[: max(0, int(round((end_s - at_s) * AUDIO_RATE)))]
    x = x[: len(buf) - i] * (10 ** (gain_db / 20))
    buf[i: i + len(x)] += x
    return len(x)


def clip_audio(s: dict) -> np.ndarray | None:
    r = subprocess.run([ffmpeg(), "-v", "error", "-filter_threads", "1", "-threads", "1",
                        "-ss", f"{s['in_s']:.4f}", "-t", f"{s['_dur']:.4f}", "-i", s["_item"]["_path"],
                        "-vn", "-ac", "1", "-ar", str(AUDIO_RATE), "-f", "f32le", "-"], capture_output=True)
    if r.returncode or not r.stdout:
        return None
    return np.frombuffer(r.stdout, dtype=np.float32).copy()


def moving_average(x: np.ndarray, k: int) -> np.ndarray:
    """Centred moving average of window k, same length as x, by cumulative
    sum (O(n); a full-film np.convolve is O(n k))."""
    if k <= 1 or len(x) == 0:
        return x.astype(np.float32)
    c = np.concatenate(([0.0], np.cumsum(x, dtype=np.float64)))
    i = np.arange(len(x))
    lo = np.clip(i - k // 2, 0, len(x))
    hi = np.clip(i - k // 2 + k, 0, len(x))
    return ((c[hi] - c[lo]) / k).astype(np.float32)


# --------------------------------------------------------------------------
# A19: synthetic voice cleanup, before levelling. A synthetic take carries a
# faint broadband hiss (Tara's Orpheus takes about -66 dBFS, Kokoro's bm_fable
# about -49) that levelling lifts and digital silence around it exposes. Each
# line gets a gentle spectral denoise against its own measured noise, then a
# downward gate between words with lookahead, hold and release so word tails
# are kept. Archival audio is never cleaned.
# --------------------------------------------------------------------------

CLEAN_FRAME_S = 0.020               # floor and speech are measured over 20 ms frames
CLEAN_NOISE_PCT = 10.0              # the floor frames: the quietest 10% of frames; the floor is their median power
CLEAN_SPEECH_ABOVE_DB = 20.0        # speech frames: at least this far above the floor
CLEAN_PAUSE_BELOW_DB = 30.0         # pause frames: 30 dB or more under the take's speech level ...
CLEAN_PAUSE_MIN_SHARE = 0.05        # ... at least 5% of the take, or its floor is quiet speech, not noise (voice-chop refuses)
CLEAN_FLOOR_SPREAD_MAX_DB = 6.0     # the floor frames' p90 at most this over their median, or the noise is not steady
CLEAN_NFFT, CLEAN_HOP = 2048, 512   # denoise STFT (43 ms Hann, 75% overlap)
CLEAN_OVERSUB = 2.0                 # spectral subtraction factor on the noise power
CLEAN_MAX_REDUCTION_DB = 18.0       # "gentle": no bin is cut by more than this
CLEAN_GATE_WIN_S = 0.010            # expander detector: RMS over 10 ms
CLEAN_EXP_OPEN_DB = 3.0             # full gain above the raw take's floor + 3 dB (under voice-chop's 6 dB line) ...
CLEAN_EXP_SPEECH_DB = 60.0          # ... or 60 dB under the speech level, whichever is higher
CLEAN_EXP_RATIO = 4.0               # under the threshold the gain falls 3 dB per dB (1:4 downward expansion)
CLEAN_RANGE_DB = 26.0               # and never by more than 26 dB: a breath is turned down, not cut out (CoS: 20 to 30)
CLEAN_LOOKAHEAD_S = 0.050           # the gain opens 50 ms before a word (CoS: 50 to 80 ms)
CLEAN_HOLD_S = 0.040                # and holds 40 ms after it
CLEAN_RELEASE_S = 0.050             # then recovers its depth with a 50 ms time constant, so a tail fades, never clicks
CLEAN_CHOP_ABOVE_DB = 6.0           # voice-chop: frames this far over the raw floor (breaths, word tails, speech) ...
CLEAN_CHOP_CUT_DB = 3.0             # ... that the cleanup cut by more than this are chopped
CLEAN_CHOP_MAX_SHARE = 0.02         # at most 2% of them may be
CLEAN_FLOOR_MAX_DBFS = -80.0        # voice-clean (blocking): the median power of the raw take's quietest 10% of frames,
                                    # cleaned and levelled, under this; their p90 is journaled, not limited
CLEAN_SPEECH_TOL_DB = 0.5           # and its speech energy must stay within this
CLEAN_NEAR_SPEECH_DB = 30.0         # T1f review (CoS): frames within 30 dB of the take's speech level are speech for the
                                    # speech-referenced chop and, with a guard, never true pauses
CLEAN_TRUE_PAUSE_GUARD_S = 0.100    # a true pause is a live frame at least 100 ms from any such frame ...
CLEAN_TRUE_PAUSE_MIN = 5            # ... and with fewer than 5 of them the floor frames' p90 stands in
CLEAN_NOISE_FLATNESS = 0.4          # a frame this spectrally flat (white noise reads about 0.56, voiced speech under 0.05)
                                    # is noise, not speech, so it never guards a true pause (T1f: a hiss 25 dB under the
                                    # speech would otherwise count as speech and hide every pause it fills)
CLEAN_PAUSE_GATE_DB = 40.0          # T1f (CoS): the pause gate's fixed depth; a true pause is turned down this far, never up
CLEAN_PAUSE_RAMP_S = 0.040          # its raised-cosine ramps, each inside the region; a region without at least one 20 ms
                                    # frame at full depth between its ramps (under 100 ms) is left as it is
CLEAN_SILENT_DBFS = -120.0          # a take's live span runs from its first to its last 20 ms frame over this; digital
                                    # silence padding a take's ends is outside it and never counts as floor or pause


def _db(p: float) -> float:
    return 10.0 * math.log10(max(float(p), 1e-30))


def live_span(x: np.ndarray) -> tuple[int, int] | None:
    """The take's live span in samples: from the start of its first 20 ms
    frame over CLEAN_SILENT_DBFS to the end of its last. Digital silence
    padding the take's ends lies outside it (T1e review: a zero-padded noisy
    take made its quietest 10% digital zero, and voice-clean passed it).
    Digital silence between words stays inside, so a take that is truly
    silent in its pauses still measures a silent floor."""
    n = int(round(CLEAN_FRAME_S * AUDIO_RATE))
    k = len(x) // n
    if k == 0:
        return None
    p = (x[: k * n].astype(np.float64).reshape(k, n) ** 2).mean(axis=1)
    live = np.flatnonzero(p > 10 ** (CLEAN_SILENT_DBFS / 10))
    return None if not len(live) else (int(live[0]) * n, (int(live[-1]) + 1) * n)


def _live_frames(k: int, span: tuple[int, int] | None) -> np.ndarray:
    """The 20 ms frames inside ``span`` (all of them when it holds under 4)."""
    n = int(round(CLEAN_FRAME_S * AUDIO_RATE))
    m = np.zeros(k, bool)
    if span is not None:
        m[span[0] // n: span[1] // n] = True
    return m if m.sum() >= 4 else np.ones(k, bool)


def voice_floor(x: np.ndarray, gaps: np.ndarray | None = None, speech: np.ndarray | None = None,
                ref: np.ndarray | None = None) -> dict:
    """Measure a voice line over 20 ms frames: the noise floor (dBFS, the
    median power of the quietest 10% of the frames inside the take's live
    span (``live_span``), or of ``gaps`` frames when given;
    ``floor_p90_dbfs`` is their 90th percentile),
    the speech level (dBFS, the mean power of frames 20 dB or more above that
    floor, or of ``speech`` frames when given) and their difference, the SNR.
    Passing the frame sets measured on the raw take measures a cleaned take on
    the same frames, so before and after compare like with like."""
    n = int(round(CLEAN_FRAME_S * AUDIO_RATE))
    k = len(x) // n
    if k < 4:
        return {"frames": k, "floor_dbfs": None, "speech_dbfs": None, "snr_db": None}
    p = (x[: k * n].astype(np.float64).reshape(k, n) ** 2).mean(axis=1)
    if gaps is None:
        cand = np.flatnonzero(_live_frames(k, live_span(x)))
        q = max(1, int(round(len(cand) * CLEAN_NOISE_PCT / 100.0)))
        gaps = np.zeros(k, bool)
        gaps[cand[np.argsort(p[cand], kind="stable")[:q]]] = True
    floor = _db(float(np.median(p[gaps]))) if gaps.any() else None
    p90 = _db(float(np.percentile(p[gaps], 90))) if gaps.any() else None
    pr = p if ref is None else (ref[: k * n].astype(np.float64).reshape(k, n) ** 2).mean(axis=1)
    heard = gaps & (pr > 10 ** (CLEAN_SILENT_DBFS / 10))      # floor frames that are not digital silence (in ``ref``, the raw take)
    floor_heard = _db(float(np.median(p[heard]))) if heard.any() else None
    if speech is None:
        speech = p > (10 ** ((floor if floor is not None else -300) / 10)) * 10 ** (CLEAN_SPEECH_ABOVE_DB / 10)
    sp = _db(p[speech].mean()) if speech.any() else None
    return {"frames": k, "floor_dbfs": None if floor is None else round(floor, 2),
            "floor_p90_dbfs": None if p90 is None else round(p90, 2),
            "floor_heard_dbfs": None if floor_heard is None else round(floor_heard, 2),
            "speech_dbfs": None if sp is None else round(sp, 2),
            "snr_db": None if floor is None or sp is None else round(sp - floor, 2),
            "_gaps": gaps, "_speech": speech}


def _stft(x: np.ndarray, n: int, hop: int) -> tuple[np.ndarray, int]:
    pad = np.concatenate([np.zeros(n, np.float64), x.astype(np.float64), np.zeros(n + hop, np.float64)])
    k = 1 + (len(pad) - n) // hop
    w = np.hanning(n + 1)[:n]
    frames = pad[np.arange(n)[None, :] + hop * np.arange(k)[:, None]] * w
    return np.fft.rfft(frames, axis=1), len(pad)


def _istft(X: np.ndarray, n: int, hop: int, length: int, out_len: int) -> np.ndarray:
    w = np.hanning(n + 1)[:n]
    frames = np.fft.irfft(X, n=n, axis=1) * w
    y = np.zeros(length, np.float64)
    norm = np.zeros(length, np.float64)
    for i in range(frames.shape[0]):
        y[i * hop: i * hop + n] += frames[i]
        norm[i * hop: i * hop + n] += w * w
    y = y / np.maximum(norm, 1e-12)
    return y[n: n + out_len]


def spectral_denoise(x: np.ndarray, noise_frames: np.ndarray | None = None) -> tuple[np.ndarray, dict]:
    """A gentle spectral subtraction against the take's own noise: the noise
    power per bin is the mean over the quietest 10% of the STFT frames centred
    inside the take's live span (digital silence padding its ends is not its
    noise), each bin's
    gain is sqrt(1 - 2 N / P), floored at -18 dB and smoothed over 3 frames so
    the residue never warbles. Returns the cleaned line and what was done."""
    X, length = _stft(x, CLEAN_NFFT, CLEAN_HOP)
    P = np.abs(X) ** 2
    e = P.sum(axis=1)
    span = live_span(x)
    centre = np.arange(len(e)) * CLEAN_HOP - CLEAN_NFFT // 2          # each frame's centre, in the take's samples
    cand = np.flatnonzero((centre >= span[0]) & (centre < span[1])) if span else np.arange(len(e))
    if len(cand) < 4:
        cand = np.arange(len(e))
    q = max(1, int(round(len(cand) * CLEAN_NOISE_PCT / 100.0)))
    quiet = cand[np.argsort(e[cand], kind="stable")[:q]]
    N = P[quiet].mean(axis=0)
    gmin = 10 ** (-CLEAN_MAX_REDUCTION_DB / 20)
    g = np.sqrt(np.clip(1.0 - CLEAN_OVERSUB * N[None, :] / np.maximum(P, 1e-30), gmin * gmin, 1.0))
    if g.shape[0] >= 3:                                   # 3-frame moving average in time
        gp = np.pad(g, ((1, 1), (0, 0)), mode="edge")
        g = (gp[:-2] + gp[1:-1] + gp[2:]) / 3.0
    y = _istft(X * g, CLEAN_NFFT, CLEAN_HOP, length, len(x))
    return y.astype(np.float32), {"method": "spectral subtraction (numpy STFT)", "nfft": CLEAN_NFFT, "hop": CLEAN_HOP,
                                  "oversubtraction": CLEAN_OVERSUB, "max_reduction_db": CLEAN_MAX_REDUCTION_DB,
                                  "noise_frames": int(q), "time_smoothing_frames": 3}


def word_expander(x: np.ndarray, floor_dbfs: float, speech_dbfs: float) -> tuple[np.ndarray, dict]:
    """A downward expander between words (A19). The detector is the RMS over
    10 ms. Below the threshold, max(denoised floor + CLEAN_EXP_OPEN_DB,
    speech - CLEAN_EXP_SPEECH_DB), the gain falls CLEAN_EXP_RATIO - 1 dB per
    dB, never past -CLEAN_RANGE_DB, so a breath is turned down, not cut out.
    The gain looks ahead CLEAN_LOOKAHEAD_S (a word's onset is never clipped)
    and holds CLEAN_HOLD_S after it (nor its tail), then recovers its depth
    with a CLEAN_RELEASE_S time constant. Worked on 1 ms blocks, then
    smoothed over 5 ms and interpolated to the samples."""
    n = len(x)
    thr = max(floor_dbfs + CLEAN_EXP_OPEN_DB, speech_dbfs - CLEAN_EXP_SPEECH_DB)
    win = max(1, int(round(CLEAN_GATE_WIN_S * AUDIO_RATE)))
    rms = np.sqrt(np.maximum(moving_average((x.astype(np.float64) ** 2).astype(np.float32), win), 0.0))
    blk = AUDIO_RATE // 1000
    nb = max(1, -(-n // blk))
    pad = np.concatenate([rms, np.zeros(nb * blk - n, np.float32)]).reshape(nb, blk).max(axis=1)
    level = 20 * np.log10(np.maximum(pad.astype(np.float64), 1e-12))
    g = np.clip((level - thr) * (CLEAN_EXP_RATIO - 1.0), -CLEAN_RANGE_DB, 0.0)        # the static curve, dB
    ahead, hold = int(round(CLEAN_LOOKAHEAD_S * 1000)), int(round(CLEAN_HOLD_S * 1000))
    gp = np.concatenate([np.full(hold, -CLEAN_RANGE_DB), g, np.full(ahead, -CLEAN_RANGE_DB)])
    g = np.lib.stride_tricks.sliding_window_view(gp, hold + ahead + 1).max(axis=1)     # open early, stay open
    a = math.exp(-1.0 / max(CLEAN_RELEASE_S * 1000, 1e-9))                              # per-block release coefficient
    out = np.empty_like(g)
    cur = g[0]
    for i, v in enumerate(g):                                                           # opens at once, closes slowly
        cur = v if v >= cur else v + (cur - v) * a
        out[i] = cur
    out = moving_average(out.astype(np.float32), 5)
    gain = 10 ** (np.interp(np.arange(n) / blk, np.arange(nb) + 0.5, out) / 20)
    y = (x * gain).astype(np.float32)
    return y, {"kind": "downward expander", "threshold_dbfs": round(thr, 2), "ratio": CLEAN_EXP_RATIO,
               "range_db": CLEAN_RANGE_DB, "detector_ms": CLEAN_GATE_WIN_S * 1000,
               "lookahead_ms": CLEAN_LOOKAHEAD_S * 1000, "hold_ms": CLEAN_HOLD_S * 1000, "release_ms": CLEAN_RELEASE_S * 1000,
               "at_full_depth_share": round(float(np.mean(out <= -CLEAN_RANGE_DB + 0.5)), 4)}


def _cut_stats(x: np.ndarray, y: np.ndarray, before: dict) -> dict:
    """What a cleanup did to the raw take's 20 ms frames: speech frames and
    audible frames (6 dB or more over the raw floor: breaths, tails, speech)
    cut by more than 3 dB, and the frames from the floor to 6 dB over it."""
    n = int(round(CLEAN_FRAME_S * AUDIO_RATE))
    k = before["frames"]
    px = (x[: k * n].astype(np.float64).reshape(k, n) ** 2).mean(axis=1)
    py = (y[: k * n].astype(np.float64).reshape(k, n) ** 2).mean(axis=1)
    sp = before["_speech"]
    audible = px >= 10 ** ((before["floor_dbfs"] + CLEAN_CHOP_ABOVE_DB) / 10)
    cut = px > py * 10 ** (CLEAN_CHOP_CUT_DB / 10)
    near = (px >= 10 ** (before["floor_dbfs"] / 10)) & ~audible
    return {"speech_frames": int(sp.sum()), "chopped_frames": int(np.sum(cut & sp)),
            "near_floor_frames": int(near.sum()), "near_floor_cut": int(np.sum(cut & near)),
            "audible_frames": int(audible.sum()), "chopped_audible": int(np.sum(cut & audible)),
            "chopped_audible_share": round(float(np.sum(cut & audible)) / max(int(audible.sum()), 1), 4), "_px": px}


def true_pause_mask(x: np.ndarray, before: dict, live: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """T1f review (CoS): the raw take's near-speech frames (within
    CLEAN_NEAR_SPEECH_DB of its speech level), the voiced ones among them (a
    frame as flat as noise, CLEAN_NOISE_FLATNESS, is noise and guards
    nothing) and the true pauses: live frames at least
    CLEAN_TRUE_PAUSE_GUARD_S from any voiced frame. Returns (true pauses,
    near speech, voiced), one bool per 20 ms frame."""
    n = int(round(CLEAN_FRAME_S * AUDIO_RATE))
    k = before["frames"]
    px = (x[: k * n].astype(np.float64).reshape(k, n) ** 2).mean(axis=1)
    near = px >= 10 ** ((before["speech_dbfs"] - CLEAN_NEAR_SPEECH_DB) / 10)
    F = np.abs(np.fft.rfft(x[: k * n].astype(np.float64).reshape(k, n) * np.hanning(n), axis=1)[:, 2:]) ** 2 + 1e-30
    flatness = np.exp(np.mean(np.log(F), axis=1)) / np.mean(F, axis=1)       # Wiener entropy, above 100 Hz
    voiced = near & (flatness < CLEAN_NOISE_FLATNESS)
    g = int(round(CLEAN_TRUE_PAUSE_GUARD_S / CLEAN_FRAME_S))
    guard = np.convolve(voiced.astype(np.int32), np.ones(2 * g + 1, np.int32), mode="same") > 0
    return live & ~guard, near, voiced


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    d = np.diff(np.concatenate(([0], mask.astype(np.int8), [0])))
    return list(zip(np.flatnonzero(d == 1).tolist(), np.flatnonzero(d == -1).tolist()))


def _ramp_frames() -> int:
    return int(math.ceil(CLEAN_PAUSE_RAMP_S / CLEAN_FRAME_S - 1e-9))


def pause_regions(tp: np.ndarray) -> list[tuple[int, int]]:
    """The true-pause runs (frame index ranges) long enough for the gate:
    two ramps (CLEAN_PAUSE_RAMP_S each) and at least one 20 ms frame at full
    depth between them. Shorter ones are left as they are."""
    m = 2 * _ramp_frames() + 1
    return [(a, b) for a, b in _runs(tp) if b - a >= m]


def pause_gate(y: np.ndarray, regions: list[tuple[int, int]]) -> tuple[np.ndarray, dict]:
    """T1f (CoS): turn each true-pause region down by CLEAN_PAUSE_GATE_DB,
    with raised-cosine ramps of CLEAN_PAUSE_RAMP_S placed entirely inside
    the region, so no sample outside it (none within 100 ms of voiced
    speech) changes. Never a boost."""
    n = int(round(CLEAN_FRAME_S * AUDIO_RATE))
    r = int(round(CLEAN_PAUSE_RAMP_S * AUDIO_RATE))
    depth = 10 ** (-CLEAN_PAUSE_GATE_DB / 20)
    gain = np.ones(len(y), np.float64)
    ramp = 0.5 + 0.5 * np.cos(np.pi * (np.arange(r) + 0.5) / r)              # 1 -> 0 inside the ramp
    for a, b in regions:
        s0, s1 = a * n, min(b * n, len(y))
        seg = np.full(s1 - s0, depth)
        seg[:r] = depth + (1 - depth) * ramp
        seg[-r:] = depth + (1 - depth) * ramp[::-1]
        gain[s0:s1] = seg
    out = (y * gain).astype(np.float32)
    return out, {"regions_s": [[round(a * CLEAN_FRAME_S, 3), round(b * CLEAN_FRAME_S, 3)] for a, b in regions],
                 "regions": len(regions), "gated_s": round(sum(b - a for a, b in regions) * CLEAN_FRAME_S, 3),
                 "depth_db": CLEAN_PAUSE_GATE_DB, "ramp_ms": CLEAN_PAUSE_RAMP_S * 1000,
                 "min_region_ms": round((2 * _ramp_frames() + 1) * CLEAN_FRAME_S * 1000), "boost": False}


def true_pauses(x: np.ndarray, y: np.ndarray, before: dict, live: np.ndarray, gated: np.ndarray | None = None) -> dict:
    """T1f review (CoS): what is heard between words, on the take as used:
    the median power of the true pauses (``true_pause_mask``; frames that
    are digital silence in the raw take left out), and the loudest true
    pause, the highest median over the regions long enough to gate
    (``pause_regions``). The speech-referenced chop is the share of
    near-speech frames outside the gated regions that the cleanup cut by
    more than CLEAN_CHOP_CUT_DB."""
    n = int(round(CLEAN_FRAME_S * AUDIO_RATE))
    k = before["frames"]
    px = (x[: k * n].astype(np.float64).reshape(k, n) ** 2).mean(axis=1)
    py = (y[: k * n].astype(np.float64).reshape(k, n) ** 2).mean(axis=1)
    tp, near, voiced = true_pause_mask(x, before, live)
    heard = tp & (px > 10 ** (CLEAN_SILENT_DBFS / 10))
    cut = px > py * 10 ** (CLEAN_CHOP_CUT_DB / 10)
    judged = near & ~(gated if gated is not None else np.zeros(k, bool))
    r = _ramp_frames()                       # the loudest pause is judged where the gate is at full depth
    loud = [(_db(float(np.median(py[a + r:b - r]))), a, b) for a, b in pause_regions(tp)
            if (px[a + r:b - r] > 10 ** (CLEAN_SILENT_DBFS / 10)).any()]
    top = max(loud) if loud else None
    short = [(_db(float(np.median(py[a:b]))), a, b) for a, b in _runs(tp) if b - a < 2 * r + 1
             and (px[a:b] > 10 ** (CLEAN_SILENT_DBFS / 10)).any()]
    stop = max(short) if short else None
    return {"true_pause_frames": int(tp.sum()), "true_pause_heard_frames": int(heard.sum()),
            "near_speech_flat_frames": int(np.sum(near & ~voiced)),
            "true_pause_dbfs": round(_db(float(np.median(py[heard]))), 2) if heard.any() else None,
            "true_pause_p90_dbfs": round(_db(float(np.percentile(py[heard], 90))), 2) if heard.any() else None,
            "loudest_pause_dbfs": None if top is None else round(top[0], 2),
            "loudest_pause_at_s": None if top is None else [round(top[1] * CLEAN_FRAME_S, 3), round(top[2] * CLEAN_FRAME_S, 3)],
            "loudest_short_pause_dbfs": None if stop is None else round(stop[0], 2),
            "loudest_short_pause_at_s": None if stop is None else [round(stop[1] * CLEAN_FRAME_S, 3), round(stop[2] * CLEAN_FRAME_S, 3)],
            "near_speech_frames": int(judged.sum()), "near_speech_cut": int(np.sum(cut & judged)),
            "speech_chop_share": round(float(np.sum(cut & judged)) / max(int(judged.sum()), 1), 4)}


def clean_voice(x: np.ndarray) -> tuple[np.ndarray, dict]:
    """A19: clean one synthetic voice line before levelling: measure its floor
    and speech, denoise, gate between words, and measure again on the same
    frames. Returns the cleaned line and the report the journal carries. A
    take too short to measure, or with no frame 20 dB over its quietest, is
    returned untouched, and the report says why. The report also says
    whether the floor can be trusted: pause frames (30 dB or more under the
    speech) at least 5% of the take, and the floor frames' p90 within 6 dB
    of their median.

    T1f (CoS): when the floor is not steady (spread over 6 dB) or the first
    pass cut more than 2% of the audible frames by over 3 dB, the expander's
    one-floor model does not hold (Kokoro's quiet frames are vocoder
    residue, not steady hiss), so the take is cleaned again by the denoise
    alone (``path`` "denoise-only"; ``first_pass`` keeps both numbers). The
    take used is the one measured: nothing is expanded, so the expander's
    chop share is 0 and the denoise's own cuts are reported, not limited."""
    before = voice_floor(x)
    rep = {"before": {k: v for k, v in before.items() if not k.startswith("_")}}
    if before["snr_db"] is None:
        rep.update(cleaned=False, why=("too short to measure" if before["frames"] < 4 else
                                       "no frame stands 20 dB over the quietest: no pause to learn the noise from"))
        return x, rep
    y_dn, den = spectral_denoise(x)
    mid = voice_floor(y_dn, before["_gaps"], before["_speech"])
    y, gate = word_expander(y_dn, before["floor_dbfs"], mid["speech_dbfs"])
    st = _cut_stats(x, y, before)
    px = st.pop("_px")
    k = before["frames"]
    live = _live_frames(k, live_span(x))         # padding at the ends is not a pause either
    pause_share = float(np.mean(px[live] < 10 ** ((before["speech_dbfs"] - CLEAN_PAUSE_BELOW_DB) / 10)))
    spread = before["floor_p90_dbfs"] - before["floor_dbfs"]
    pause_why, spread_why = [], []
    if pause_share < CLEAN_PAUSE_MIN_SHARE:
        pause_why.append(f"the take's floor is within {CLEAN_PAUSE_BELOW_DB:g} dB of its speech: no pause quiet enough to measure "
                   f"(frames {CLEAN_PAUSE_BELOW_DB:g} dB under the speech are {100 * pause_share:.1f}% of the take; at least "
                   f"{100 * CLEAN_PAUSE_MIN_SHARE:g}% needed)")
    if spread > CLEAN_FLOOR_SPREAD_MAX_DB:
        spread_why.append(f"the floor frames spread {spread:.1f} dB (p90 over median; at most {CLEAN_FLOOR_SPREAD_MAX_DB:g}): the noise "
                   "is not steady, so one floor does not describe it")
    path, first = "expander", None
    if spread_why or st["chopped_audible_share"] > CLEAN_CHOP_MAX_SHARE:
        first = {"floor_spread_db": round(spread, 2), "chopped_audible_share": st["chopped_audible_share"],
                 "chopped_audible": st["chopped_audible"], "audible_frames": st["audible_frames"],
                 "max_floor_spread_db": CLEAN_FLOOR_SPREAD_MAX_DB, "max_chop_share": CLEAN_CHOP_MAX_SHARE,
                 "why": " and ".join(w for w in (
                     f"the floor spreads {spread:.1f} dB (over {CLEAN_FLOOR_SPREAD_MAX_DB:g}): not one steady floor" if spread_why else "",
                     f"the first pass cut {100 * st['chopped_audible_share']:.1f}% of audible frames by over {CLEAN_CHOP_CUT_DB:g} dB "
                     f"(at most {100 * CLEAN_CHOP_MAX_SHARE:g}%)" if st["chopped_audible_share"] > CLEAN_CHOP_MAX_SHARE else "") if w)}
        path, y, gate = "denoise-only", y_dn, None
        dn = _cut_stats(x, y, before)
        dn.pop("_px")
        st = dict(dn, denoise_chopped_audible=dn["chopped_audible"], denoise_chopped_audible_share=dn["chopped_audible_share"],
                  chopped_audible=0, chopped_audible_share=0.0)      # nothing is expanded on this path
    # T1f (CoS): the pause gate, on the take as cleaned: true pauses turned down, nothing near speech touched
    tp_mask, _, _ = true_pause_mask(x, before, live)
    regions = pause_regions(tp_mask)
    pre = true_pauses(x, y, before, live)
    y, pg = pause_gate(y, regions)
    gated = np.zeros(k, bool)
    for a_, b_ in regions:
        gated[a_:b_] = True
    pg.update(true_pause_before_dbfs=pre["true_pause_dbfs"], loudest_pause_before_dbfs=pre["loudest_pause_dbfs"])
    after = voice_floor(y, before["_gaps"], before["_speech"], ref=x)
    tp = true_pauses(x, y, before, live, gated)
    rep.update(cleaned=True, path=path, first_pass=first, denoise=den, gate=gate, pause_gate=pg, **st, **tp,
               pause_share=round(pause_share, 4), floor_spread_db=round(spread, 2),
               measure_ok=not (pause_why or spread_why), measure_why=pause_why + spread_why,
               pause_why=pause_why, spread_why=spread_why,
               after_denoise={k: v for k, v in mid.items() if not k.startswith("_")},
               after={k: v for k, v in after.items() if not k.startswith("_")},
               floor_drop_db=round(before["floor_dbfs"] - after["floor_dbfs"], 2),
               speech_change_db=round(after["speech_dbfs"] - before["speech_dbfs"], 3))
    return y, rep


def _level(journal: Journal, unit: str, x: np.ndarray, target: float, what: str) -> float | None:
    """Level one synthetic voice line or music cue to its target by a measured
    linear gain (never archival audio, which keeps its own level and
    dynamics), and journal the gain as a decision."""
    g, m = level_gain(x, target)
    if g is None:
        journal.decision("assembly", f"{unit} not levelled", "empty or too quiet to measure (gated out)", unit=unit,
                         evidence={"measured_i": m.get("input_i"), "dur_s": round(len(x) / AUDIO_RATE, 3)})
        # a line or cue that cannot be levelled (and so is not peak-controlled) is said, not silently passed
        journal.lint("level-measured", False, stage="assembly", phase="preflight", unit=unit, severity="warn", grammar="A13",
                     evidence={"what": what, "dur_s": round(len(x) / AUDIO_RATE, 3), "measured_i": m.get("input_i"),
                               "result": "placed at its own level, with no peak control"})
        return None
    looped = m.get("looped", 1)
    journal.decision("assembly", f"{unit} levelled to {target:g} LUFS ({what}) by {g:+.2f} dB",
                     f"measured {m['input_i']:.2f} LUFS integrated, true peak {m['input_tp']:.2f} dBTP; linear gain only"
                     + (f"; the line is {len(x) / AUDIO_RATE:.3f} s, under one {LEVEL_MIN_S:g} s gating block, so it was "
                        f"measured looped {looped} times" if looped > 1 else ""),
                     unit=unit, evidence={"measured_i": m["input_i"], "measured_tp": m["input_tp"], "target": target, "gain_db": round(g, 2),
                                          "measured_looped": looped})
    return g


def _journal_clean(journal: Journal, unit: str, rep: dict, level: float | None, draft: bool = False) -> list[str]:
    """A19: a line's cleanup as a decision (the floor and SNR before and after,
    and after levelling) and two lints, blocking on a final render and warnings
    under --draft (CoS, T1e review). voice-clean: the inter-word floor after
    levelling is under -80 dBFS and the speech energy within 0.5 dB; a take
    that could not be cleaned fails it. voice-chop: always refuses a take
    with too few pauses to measure its floor; on the expander path it also
    refuses a floor that spreads over 6 dB or more than 2% of the frames
    6 dB or more over the raw floor (breaths, tails, speech) cut by more than
    3 dB, which clean_voice never hands it (such a take goes the denoise-only
    way; the inaudible-floor waiver this replaced is gone). A take cleaned by the denoise alone (``path``
    "denoise-only", T1f) is journaled as that decision with its first-pass
    numbers; voice-chop then refuses only too few pauses (nothing was
    expanded; the spread and the denoise's cuts are journaled). On either
    path voice-clean also needs the median of the floor frames that are not
    digital silence under -80 as levelled, so a hiss that drops to digital
    zero inside a pause cannot pass on a median of zeros. Returns the
    reasons to refuse."""
    lift = level or 0.0
    sev = "warn" if draft else "block"
    b = rep["before"]
    if not rep["cleaned"]:
        journal.decision("assembly", f"{unit} not cleaned: {rep['why']}", "GRAMMAR A19 cleans synthetic voice lines before levelling",
                         unit=unit, evidence=rep)
        journal.lint("voice-clean", False, stage="assembly", phase="preflight", unit=unit, severity=sev, grammar="A19",
                     evidence={"cleaned": False, "why": rep["why"], "before": b, "fix": "re-render the take"})
        return [] if draft else [f"{unit} (voice-clean: {rep['why']})"]
    a = rep["after"]
    floor_levelled = None if a["floor_dbfs"] is None else round(a["floor_dbfs"] + lift, 2)
    journal.decision("assembly", f"{unit} cleaned: floor {b['floor_dbfs']:.1f} to {a['floor_dbfs']:.1f} dBFS, SNR {b['snr_db']:.1f} to "
                     f"{a['snr_db']:.1f} dB, speech {rep['speech_change_db']:+.2f} dB",
                     "GRAMMAR A19: gentle spectral denoise, then a downward expander between words (lookahead, hold, release), "
                     "before levelling; measured on the same 20 ms frames before and after", unit=unit,
                     evidence=dict(rep, level_gain_db=None if level is None else round(level, 2), floor_after_level_dbfs=floor_levelled,
                                   floor_raw_after_level_dbfs=None if b["floor_dbfs"] is None else round(b["floor_dbfs"] + lift, 2)))
    denoise_only = rep.get("path") == "denoise-only"
    if denoise_only:
        fp = rep["first_pass"]
        journal.decision("assembly", f"{unit} re-cleaned by the denoise alone, without the expander: {fp['why']}",
                         "GRAMMAR A19 refined (T1f): the expander assumes one steady floor; a take whose quiet frames are not "
                         "steady (vocoder residue) or that the first pass chopped is cleaned by the denoise only, and judged as used",
                         unit=unit, evidence={"first_pass": fp, "denoise_chopped_audible": rep.get("denoise_chopped_audible"),
                                              "denoise_chopped_audible_share": rep.get("denoise_chopped_audible_share"),
                                              "floor_after_level_dbfs": floor_levelled})
    heard = None if a.get("floor_heard_dbfs") is None else round(a["floor_heard_dbfs"] + lift, 2)
    p90_levelled = None if a.get("floor_p90_dbfs") is None else round(a["floor_p90_dbfs"] + lift, 2)
    # T1f review (CoS): the true pauses, what a listener hears in the silences, on both paths; with too few of them
    # the floor frames' p90 stands in
    fallback = rep.get("true_pause_frames", 0) < CLEAN_TRUE_PAUSE_MIN
    if fallback:
        pause_lvl = p90_levelled
    else:
        pause_lvl = None if rep.get("true_pause_dbfs") is None else round(rep["true_pause_dbfs"] + lift, 2)
    pause_ok = pause_lvl is None or pause_lvl < CLEAN_FLOOR_MAX_DBFS
    # T1f (CoS): the loudest true pause long enough to gate, at the gate's full depth, as levelled
    loudest = None if rep.get("loudest_pause_dbfs") is None else round(rep["loudest_pause_dbfs"] + lift, 2)
    loudest_ok = loudest is None or loudest < CLEAN_FLOOR_MAX_DBFS
    pg = rep.get("pause_gate") or {}
    journal.decision("assembly", f"{unit} pause gate: {pg.get('regions', 0)} true pauses, {pg.get('gated_s', 0):g} s, "
                     f"turned down {pg.get('depth_db', CLEAN_PAUSE_GATE_DB):g} dB",
                     "GRAMMAR A19 refined, pause gate (T1f): true pauses (100 ms or more from voiced speech) are turned down "
                     "with raised-cosine ramps inside them; nothing near speech changes", unit=unit,
                     evidence=dict(pg, loudest_pause_after_level_dbfs=loudest,
                                   loudest_short_pause_after_level_dbfs=None if rep.get("loudest_short_pause_dbfs") is None
                                   else round(rep["loudest_short_pause_dbfs"] + lift, 2),
                                   short_note="true pauses under 100 ms are left as they are and journaled, not judged"))
    out = []
    ok = (floor_levelled is not None and floor_levelled < CLEAN_FLOOR_MAX_DBFS and abs(rep["speech_change_db"]) <= CLEAN_SPEECH_TOL_DB
          and (heard is None or heard < CLEAN_FLOOR_MAX_DBFS) and pause_ok and loudest_ok)
    journal.lint("voice-clean", ok, stage="assembly", phase="preflight", unit=unit, severity=sev, grammar="A19, T1f",
                 evidence={"measure": "median power of the raw take's quietest 10% of 20 ms frames, on the cleaned and "
                                      "levelled line, and of its true pauses (live frames 100 ms or more from any frame within "
                                      "30 dB of the speech; the floor p90 when there are under 5)",
                           "floor_after_level_dbfs": floor_levelled, "max_dbfs": CLEAN_FLOOR_MAX_DBFS,
                           "floor_p90_after_level_dbfs": p90_levelled, "path": rep.get("path", "expander"),
                           "floor_heard_after_level_dbfs": heard,
                           "true_pause_after_level_dbfs": pause_lvl, "true_pause_frames": rep.get("true_pause_frames"),
                           "true_pause_fallback_p90": fallback,
                           "loudest_pause_after_level_dbfs": loudest, "loudest_pause_at_s": rep.get("loudest_pause_at_s"),
                           "true_pause_p90_after_level_dbfs": None if rep.get("true_pause_p90_dbfs") is None else
                           round(rep["true_pause_p90_dbfs"] + lift, 2),
                           "speech_change_db": rep["speech_change_db"], "tolerance_db": CLEAN_SPEECH_TOL_DB,
                           "snr_before_db": b["snr_db"], "snr_after_db": a["snr_db"], "fix": None if ok else "re-render the take"})
    if not ok:
        out.append(f"{unit} (voice-clean: floor {floor_levelled} dBFS after levelling"
                   + (f", {heard} dBFS where not digital silence" if heard is not None and heard != floor_levelled else "")
                   + (f", true pauses {pause_lvl} dBFS" + (" (floor p90, too few true pauses)" if fallback else "")
                      if not pause_ok else "")
                   + (f", loudest true pause {loudest} dBFS at {rep.get('loudest_pause_at_s')} s" if not loudest_ok else "")
                   + f", speech {rep['speech_change_db']:+.2f} dB{', denoise only' if denoise_only else ''})")
    pause_why = rep.get("pause_why", [])
    sc = rep.get("speech_chop_share", 0.0)
    chop_bad = sc > CLEAN_CHOP_MAX_SHARE
    chop_ok = not pause_why and not chop_bad
    journal.lint("voice-chop", chop_ok, stage="assembly", phase="preflight", unit=unit, severity=sev, grammar="A19, T1f",
                 evidence={"path": rep.get("path", "expander"),
                           "measure": "frames within 30 dB of the take's speech level cut by more than 3 dB, at most 2%",
                           "speech_chop_share": sc, "near_speech_frames": rep.get("near_speech_frames"),
                           "near_speech_cut": rep.get("near_speech_cut"), "max_share": CLEAN_CHOP_MAX_SHARE,
                           "floor_referenced": {"note": "frames 6 dB or more over the raw floor cut by over 3 dB; journaled, not limited",
                                                "chopped": rep["chopped_audible"], "frames": rep["audible_frames"],
                                                "share": rep["chopped_audible_share"],
                                                "denoise_chopped_audible_share": rep.get("denoise_chopped_audible_share")},
                           "speech_frames_chopped": rep["chopped_frames"],
                           "near_floor_frames": rep["near_floor_frames"], "near_floor_cut": rep["near_floor_cut"],
                           "pause_share": rep["pause_share"], "min_pause_share": CLEAN_PAUSE_MIN_SHARE,
                           "floor_spread_db": rep["floor_spread_db"], "max_floor_spread_db": CLEAN_FLOOR_SPREAD_MAX_DB,
                           "first_pass": rep.get("first_pass"),
                           "expander_threshold_after_level_dbfs": None if not rep.get("gate") else
                           round(rep["gate"]["threshold_dbfs"] + lift, 2),
                           "why": pause_why or None})
    if chop_bad:
        out.append(f"{unit} (voice-chop: {rep.get('near_speech_cut')} of {rep.get('near_speech_frames')} frames within "
                   f"{CLEAN_NEAR_SPEECH_DB:g} dB of the speech cut over {CLEAN_CHOP_CUT_DB:g} dB)")
    for w in pause_why:
        out.append(f"{unit} (voice-chop: {w})")
    return out if not draft else []


def _journal_peak(journal: Journal, unit: str, peak: dict, draft: bool) -> None:
    """A13: a line's peak reduction as a decision, and the bad-take lint (blocking; a warning under --draft)."""
    journal.decision("assembly", f"{unit} peak-controlled to {peak['ceiling_dbtp']:g} dBTP: at most {peak['max_reduction_db']:.2f} dB; "
                     f"over 8 dB {peak['over_8db_s']:.3f} s, over 3 dB {peak['over_3db_s']:.3f} s, over 1 dB {peak['over_1db_s']:.3f} s "
                     f"of {peak['dur_s']:.3f} s",
                     f"its true peak after levelling was {peak['tp_before']:.2f} dBTP, past the voice ceiling {VOICE_TP:g} dBTP "
                     f"(GRAMMAR A13, A15: {DIALOGUE_LUFS:g} LUFS + {TARGET_TP - TARGET_LUFS:g} dB headroom - {VOICE_TP_MARGIN:g} dB)", unit=unit,
                     evidence=dict({k: v for k, v in peak.items() if k != "acted"}, acted=peak["acted"][:20]))
    journal.lint("voice-peak-control", not peak["bad_take"], stage="assembly", phase="preflight", unit=unit,
                 severity="warn" if draft else "block", grammar="A13",
                 evidence={"max_reduction_db": peak["max_reduction_db"], "max_at_s": peak["max_at_s"], "dur_s": peak["dur_s"],
                           "over_8db_s": peak["over_8db_s"], "over_3db_s": peak["over_3db_s"], "over_1db_s": peak["over_1db_s"],
                           "over_3db_share": peak["over_3db_share"], "over_1db_share": peak["over_1db_share"], "bad_take": peak["bad_take"],
                           "limits": {"over_8db_s": VOICE_OVER_8DB_MAX_S, "over_1db_share": VOICE_OVER_1DB_MAX_SHARE,
                                      "over_3db_share": VOICE_OVER_3DB_MAX_SHARE},
                           "result": None if not peak["bad_take"] else ("kept (draft)" if draft else "refused: re-render the take")})


WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*")


def mood_offset(journal: Journal, ln: dict) -> float:
    """A14: a narration line's level offset for its delivery mood, applied
    after the -20 LUFS levelling and peak control, journaled as a decision.
    Delivery moves only the level; pace and pauses were rendered upstream.
    An offset past MOOD_OFFSET_MAX_DB is refused (build_plan's
    narrator-delivery lint refuses it first)."""
    d = ln.get("delivery")
    if not isinstance(d, dict) or ln.get("kind") != "narration":
        return 0.0
    mood = d.get("mood")
    off = MOOD_OFFSET_DB.get(mood)
    if off is None or not -MOOD_OFFSET_MAX_DB - 1e-9 <= off <= 0.0:
        raise Refused(f"narrator-delivery (A14): {ln['id']} mood {mood!r} gives offset {off}; moods {MOOD_OFFSET_DB}, "
                      f"each from -{MOOD_OFFSET_MAX_DB:g} to 0 dB")
    journal.decision("assembly", f"{ln['id']} delivery {mood}: {off:+.1f} dB after levelling to {DIALOGUE_LUFS:g} LUFS",
                     "GRAMMAR A14: a narration line's mood sets a small level offset (plain 0, measured 0, warm 0, grave -0.5, "
                     "hushed -2.0, close -1.0 dB); the voice itself was rendered upstream", unit=ln["id"],
                     evidence={"mood": mood, "offset_db": off, "intensity": d.get("intensity"), "pace": d.get("pace"),
                               "pause_after_s": d.get("pause_after_s"), "applies_to": "level only"})
    return off


def _frames(x: np.ndarray, n: int, hop: int) -> np.ndarray:
    if len(x) < n:
        return np.zeros((0, n), dtype=x.dtype)
    k = 1 + (len(x) - n) // hop
    return x[np.arange(n)[None, :] + hop * np.arange(k)[:, None]]


def voice_profile(x: np.ndarray, words: int) -> dict:
    """A levelled voice line's profile for narrator-consistency, over 40 ms
    frames every 10 ms. Active frames have an RMS of at least 0.01. On each
    active frame, pitch comes from the normalised autocorrelation of the
    line box-filtered to 16 kHz: a frame is voiced when its best lag in 60 to
    500 Hz correlates at least 0.5, and the pitch is the first lag within 90%
    of that best (so a subharmonic never wins), refined parabolically.
    Returns the median f0 and its p10 to p90 range over voiced frames, the
    median spectral centroid over active frames (Hann window, full band),
    and words per second over the speech span (first to last active frame)."""
    x = np.asarray(x, dtype=np.float64)
    n, hop = int(PROFILE_FRAME_S * AUDIO_RATE), int(PROFILE_HOP_S * AUDIO_RATE)
    fr = _frames(x, n, hop)
    active = np.sqrt((fr ** 2).mean(axis=1)) >= PROFILE_MIN_RMS if len(fr) else np.zeros(0, bool)
    ds = 3
    rd, nd, hd = AUDIO_RATE // ds, n // ds, hop // ds
    xd = x[: len(x) // ds * ds].reshape(-1, ds).mean(axis=1)
    fd = _frames(xd, nd, hd)[: len(fr)]
    lo, hi = int(rd / F0_MAX_HZ), int(math.ceil(rd / F0_MIN_HZ))
    tau = np.arange(nd)
    f0s = []
    for f in fd[active[: len(fd)]]:
        f = f - f.mean()
        ac = np.fft.irfft(np.abs(np.fft.rfft(f, 2 * nd)) ** 2)[:nd]
        c = np.concatenate(([0.0], np.cumsum(f ** 2)))
        r = ac / np.sqrt(np.maximum(c[nd - tau] * (c[nd] - c[tau]), 1e-12))
        seg = r[lo:hi + 1]
        best = float(seg.max())
        if best < VOICED_CORR:
            continue
        j = int(np.flatnonzero(seg >= 0.9 * best)[0])
        while j + 1 < len(seg) and seg[j + 1] > seg[j]:
            j += 1
        t = float(lo + j)
        if 0 < lo + j < nd - 1:
            a, b, cc = r[lo + j - 1], r[lo + j], r[lo + j + 1]
            den = a - 2 * b + cc
            t += 0.5 * (a - cc) / den if den else 0.0
        f0s.append(rd / t)
    cen = np.zeros(0)
    if active.any():
        mag = np.abs(np.fft.rfft(fr[active] * np.hanning(n), axis=1))
        freqs = np.fft.rfftfreq(n, 1.0 / AUDIO_RATE)
        cen = (mag * freqs).sum(axis=1) / np.maximum(mag.sum(axis=1), 1e-12)
    idx = np.flatnonzero(active)
    span = ((idx[-1] - idx[0]) * hop + n) / AUDIO_RATE if len(idx) else 0.0
    f0 = np.asarray(f0s)
    r2 = (lambda v: None if v is None else round(float(v), 2))
    return {"f0_hz": r2(np.median(f0)) if len(f0) else None,
            "f0_p10_hz": r2(np.percentile(f0, 10)) if len(f0) else None,
            "f0_p90_hz": r2(np.percentile(f0, 90)) if len(f0) else None,
            "f0_range_hz": r2(np.percentile(f0, 90) - np.percentile(f0, 10)) if len(f0) else None,
            "centroid_hz": r2(np.median(cen)) if len(cen) else None,
            "words": int(words), "speech_s": round(span, 3), "wps": r2(words / span) if span else None,
            "voiced_frames": int(len(f0)), "active_frames": int(active.sum())}


def _st(f: float, ref: float) -> float:
    """Semitones from ref to f."""
    return 12 * math.log2(f / ref)


def narrator_consistency(profiles: dict[str, dict]) -> dict:
    """A14 narrator-consistency (refined: perceptual bounds) over every
    narration line's profile (with its ``mood``).

    The baseline is the median f0 and centroid of the plain and measured
    lines (all lines when fewer than NARRATOR_MIN_LINES of those). A line is
    out of character when its f0 is more than 1.5 semitones above the
    baseline (any mood), or below it by more than 1.5 semitones (plain,
    measured or no mood) or 3 semitones (hushed, grave, close); or when its
    centroid is more than 25% above (any mood), or below by more than 25%
    (plain, measured or no mood) or 40% (the lower moods). Words per second
    is profiled, never refused. The baseline lines' robust f0 spread (1.4826
    x the median absolute deviation, in semitones) past 1 semitone means two
    voices share the part (``spread_ok`` False). Fewer than
    NARRATOR_MIN_LINES measured lines make no baseline: all inconclusive."""
    measured = {k: p for k, p in profiles.items() if p.get("f0_hz") is not None and p.get("centroid_hz") is not None}
    unmarked = {k: p for k, p in measured.items() if p.get("mood") in BASELINE_MOODS}
    pool = unmarked if len(unmarked) >= NARRATOR_MIN_LINES else measured
    enough = len(measured) >= NARRATOR_MIN_LINES
    base: dict = {}
    spread_st = None
    if pool:
        for k in ("f0_hz", "f0_range_hz", "centroid_hz", "wps"):
            v = [p[k] for p in pool.values() if p.get(k) is not None]
            if v:
                base[k] = round(float(np.median(v)), 2)
        st = np.array([_st(p["f0_hz"], base["f0_hz"]) for p in pool.values()])
        spread_st = round(1.4826 * float(np.median(np.abs(st - np.median(st)))), 3)
    lines = {}
    for lid, p in profiles.items():
        mood = p.get("mood")
        lower = mood in MOOD_MAY_BE_LOWER
        d_st = round(_st(p["f0_hz"], base["f0_hz"]), 2) if p.get("f0_hz") and base.get("f0_hz") else None
        d_cen = round(p["centroid_hz"] / base["centroid_hz"] - 1, 4) if p.get("centroid_hz") and base.get("centroid_hz") else None
        down_st = NARRATOR_F0_DOWN_LOWER_ST if lower else NARRATOR_F0_DOWN_ST
        down_cen = NARRATOR_CENTROID_DOWN_LOWER if lower else NARRATOR_CENTROID_DOWN
        off, allowed = [], []
        if d_st is not None:
            if d_st > NARRATOR_F0_UP_ST:
                off.append(f"f0 {d_st:+.2f} semitones (more than {NARRATOR_F0_UP_ST:g} above; no mood may be higher)")
            elif d_st < -down_st:
                off.append(f"f0 {d_st:+.2f} semitones (more than {down_st:g} below for a {mood or 'unmarked'} line)")
            elif d_st < -NARRATOR_F0_DOWN_ST:
                allowed.append(f"f0 {d_st:+.2f} semitones, within the {down_st:g} a {mood} line may drop")
        if d_cen is not None:
            if d_cen > NARRATOR_CENTROID_UP:
                off.append(f"centroid {d_cen:+.1%} (more than {NARRATOR_CENTROID_UP:.0%} above; no mood may be brighter)")
            elif d_cen < -down_cen:
                off.append(f"centroid {d_cen:+.1%} (more than {down_cen:.0%} below for a {mood or 'unmarked'} line)")
            elif d_cen < -NARRATOR_CENTROID_DOWN:
                allowed.append(f"centroid {d_cen:+.1%}, within the {down_cen:.0%} a {mood} line may drop")
        verdict = "inconclusive" if not enough or d_st is None or d_cen is None else ("off" if off else "consistent")
        lines[lid] = {"profile": {k: v for k, v in p.items() if k != "mood"}, "mood": mood, "f0_st": d_st,
                      "centroid_pct": None if d_cen is None else round(100 * d_cen, 2), "off": off, "allowed": allowed,
                      "verdict": verdict}
    # A single lower-mood line may drop 3 semitones, but a whole mood may not: otherwise a second voice could take
    # the plain lines and leave the narrator only the lower ones. Each lower mood with at least NARRATOR_GROUP_MIN lines,
    # and the lower moods pooled, keep their median f0 within NARRATOR_GROUP_DOWN_ST of the baseline.
    groups = {}
    if base.get("f0_hz") and enough:
        sets = {m: [p["f0_hz"] for p in measured.values() if p.get("mood") == m] for m in sorted(MOOD_MAY_BE_LOWER)}
        sets["lower moods pooled"] = [p["f0_hz"] for p in measured.values() if p.get("mood") in MOOD_MAY_BE_LOWER]
        for m, v in sets.items():
            if len(v) < NARRATOR_GROUP_MIN:
                continue
            d = round(_st(float(np.median(v)), base["f0_hz"]), 2)
            groups[m] = {"lines": len(v), "median_f0_hz": round(float(np.median(v)), 2), "f0_st": d,
                         "ok": d >= -NARRATOR_GROUP_DOWN_ST}
    group_off = [f"{m}: median f0 {g['f0_st']:+.2f} semitones over {g['lines']} lines (a mood may sit at most "
                 f"{NARRATOR_GROUP_DOWN_ST:g} below the baseline)" for m, g in groups.items() if not g["ok"]]
    return {"baseline": base, "lines": lines, "enough": enough, "min_lines": NARRATOR_MIN_LINES,
            "groups": groups, "group_off": group_off, "baseline_lines": sorted(pool),
            "baseline_from": ("plain and measured lines" if pool is unmarked
                              else f"all lines (fewer than {NARRATOR_MIN_LINES} plain or measured)"),
            "bounds": {"f0_up_st": NARRATOR_F0_UP_ST, "f0_down_st": NARRATOR_F0_DOWN_ST,
                       "f0_down_lower_moods_st": NARRATOR_F0_DOWN_LOWER_ST, "centroid_up": NARRATOR_CENTROID_UP,
                       "centroid_down": NARRATOR_CENTROID_DOWN, "centroid_down_lower_moods": NARRATOR_CENTROID_DOWN_LOWER},
            "spread_st": spread_st, "spread_ok": spread_st is None or not enough or spread_st <= NARRATOR_SPREAD_MAX_ST}


def load_narrator_profile(narrator_voice: dict | None, path: Path | None = None) -> tuple[dict | None, str]:
    """The stored narrator profile (the approved audition's median f0 and
    centroid) when it exists and is the film's narrator voice, else None;
    and why. It is a drift reference only: it never sets the baseline."""
    path = NARRATOR_PROFILE if path is None else path
    if not path or not Path(path).exists():
        return None, f"no stored profile at {path}"
    prof = json.loads(Path(path).read_text(encoding="utf-8"))
    want = {k: (narrator_voice or {}).get(k) for k in ("engine", "voice")}
    have = {k: (prof.get("voice") or {}).get(k) for k in ("engine", "voice")}
    if want != have:
        return None, f"the stored profile is {have['engine']}:{have['voice']}, the film's narrator is {want['engine']}:{want['voice']}"
    return prof, f"drift reference {Path(path).name} ({have['engine']}:{have['voice']})"


def narrator_profile_from_takes(takes: list[tuple[Path, str]], voice: dict) -> dict:
    """A stored narrator profile from approved takes (WAV, spoken text): each
    take levelled to DIALOGUE_LUFS and profiled as narration lines are, then
    the median f0 and centroid (the drift check's reference)."""
    per = {}
    for path, text in takes:
        x = _read_wav(Path(path))
        g, _ = level_gain(x, DIALOGUE_LUFS)
        per[Path(path).name] = dict(voice_profile(x * 10 ** (g / 20), len(WORD_RE.findall(text))),
                                    sha256=sha256_file(path)[:16])
    base = {k: round(float(np.median([p[k] for p in per.values()])), 2) for k in ("f0_hz", "centroid_hz")}
    return {"voice": voice, "baseline": base, "takes": per,
            "method": "studio.engine.render.voice_profile on each take levelled to -20 LUFS; median over the takes"}


def narrator_drift(baseline: dict, stored: dict | None) -> dict:
    """The film's narrator baseline against the stored audition profile:
    f0 in semitones, centroid as a fraction. Each is ``ok``, ``warn``
    (past NARRATOR_DRIFT_WARN_*) or ``block`` (past NARRATOR_DRIFT_BLOCK_*)."""
    if not stored or not baseline.get("f0_hz") or not baseline.get("centroid_hz"):
        return {}
    f0 = round(_st(baseline["f0_hz"], float(stored["baseline"]["f0_hz"])), 2)
    cen = round(baseline["centroid_hz"] / float(stored["baseline"]["centroid_hz"]) - 1, 4)

    def grade(v, warn, block):
        return "block" if abs(v) > block else ("warn" if abs(v) > warn else "ok")

    return {"f0": {"value": f0, "unit": "semitones", "warn": NARRATOR_DRIFT_WARN_ST, "block": NARRATOR_DRIFT_BLOCK_ST,
                   "grade": grade(f0, NARRATOR_DRIFT_WARN_ST, NARRATOR_DRIFT_BLOCK_ST)},
            "centroid": {"value": cen, "unit": "fraction", "warn": NARRATOR_DRIFT_WARN_CENTROID,
                         "block": NARRATOR_DRIFT_BLOCK_CENTROID,
                         "grade": grade(cen, NARRATOR_DRIFT_WARN_CENTROID, NARRATOR_DRIFT_BLOCK_CENTROID)}}


def narrator_consistency_lints(journal: Journal, profiles: dict[str, dict], draft: bool,
                               narrator_voice: dict | None = None) -> list[str]:
    """Journal the narrator's baseline and every line's profile, and lint:
    narrator-consistency per line, for the part's spread and for each
    lower-mood group (blocking, a warning under --draft); narrator-drift
    against the stored audition profile for f0 and centroid (a warning past
    the first bound, blocking past the second, a warning under --draft), or
    a review item "no reference profile" when the narrator voice has none.
    Returns what is refused, with why."""
    res = narrator_consistency(profiles)
    stored, why = load_narrator_profile(narrator_voice)
    drift = narrator_drift(res["baseline"], stored)
    journal.event("unit", "assembly", "narrator", lens="narrator-profile", status="info", grammar="A14",
                  baseline=res["baseline"], baseline_from=res["baseline_from"], baseline_lines=res["baseline_lines"],
                  bounds=res["bounds"], spread_st=res["spread_st"], groups=res["groups"], drift=drift, reference=why,
                  lines={k: v["profile"] | {"mood": v["mood"]} for k, v in res["lines"].items()}, enough=res["enough"])
    sev = "warn" if draft else "block"
    off = []
    if not stored:
        journal.lint("narrator-drift", True, stage="assembly", phase="preflight", unit="narrator", severity="review",
                     grammar="A14", evidence={"check": "no reference profile", "why": why, "narrator_voice": narrator_voice,
                                              "film_baseline": res["baseline"]})
    elif not drift:
        # a stored profile, but no narration line measured both f0 and centroid: the drift could not be measured
        journal.lint("narrator-drift", True, stage="assembly", phase="preflight", unit="narrator", severity=sev,
                     grammar="A14", status="inconclusive",
                     evidence={"check": "no line has both f0 and centroid", "why": why, "film_baseline": res["baseline"],
                               "reference": stored.get("baseline"), "lines": len(profiles)})
    else:
        for k, d in drift.items():
            blocks = d["grade"] == "block"
            # the blocking bound applies outside --draft, so the lint carries block severity unless only the warning bound failed
            journal.lint("narrator-drift", d["grade"] == "ok", stage="assembly", phase="preflight", unit=f"narrator-{k}",
                         severity="warn" if d["grade"] == "warn" else sev, grammar="A14",
                         evidence=dict(d, film_baseline=res["baseline"], reference=stored["baseline"], why=why,
                                       result=None if not blocks else ("kept (draft)" if draft else "refused: not the narrator's voice")))
            if blocks:
                v = f"{d['value']:+.2f} semitones" if k == "f0" else f"{d['value']:+.1%}"
                off.append(f"narrator-drift {k} {v} from the stored profile (block past {d['block']:g}"
                           + (" semitones)" if k == "f0" else ")"))
    journal.lint("narrator-consistency", res["spread_ok"], stage="assembly", phase="preflight", unit="narrator",
                 severity=sev, grammar="A14", status=None if res["enough"] else "inconclusive",
                 evidence={"spread_st": res["spread_st"], "limit_st": NARRATOR_SPREAD_MAX_ST, "baseline": res["baseline"],
                           "baseline_from": res["baseline_from"], "result": None if res["spread_ok"] else
                           ("kept (draft)" if draft else "refused: two voices share the narrator")})
    if not res["spread_ok"]:
        off.append(f"narrator (the baseline lines' pitch spreads {res['spread_st']:.2f} semitones, "
                   f"limit {NARRATOR_SPREAD_MAX_ST:g}: two voices share the part)")
    for m, g in res["groups"].items():
        journal.lint("narrator-consistency", g["ok"], stage="assembly", phase="preflight", unit=f"narrator:{m}", severity=sev,
                     grammar="A14", evidence=dict(g, baseline=res["baseline"], limit_st=NARRATOR_GROUP_DOWN_ST,
                                                  result=None if g["ok"] else ("kept (draft)" if draft else "refused")))
    off += res["group_off"]
    for lid, r in res["lines"].items():
        bad = r["verdict"] == "off"
        journal.lint("narrator-consistency", not bad, stage="assembly", phase="preflight", unit=lid,
                     severity=sev, grammar="A14",
                     status="inconclusive" if r["verdict"] == "inconclusive" else None,
                     evidence={"profile": r["profile"], "mood": r["mood"], "f0_st": r["f0_st"], "centroid_pct": r["centroid_pct"],
                               "off": r["off"], "allowed": r["allowed"], "baseline": res["baseline"], "bounds": res["bounds"],
                               "verdict": r["verdict"], "lines": len(res["lines"]),
                               "result": None if not bad else ("kept (draft)" if draft else "refused: re-render the line")})
        if bad:
            off.append(f"{lid} ({'; '.join(r['off'])})")
    return off


def build_mix(plan: dict, film: Path, journal: Journal, *, draft: bool = False) -> tuple[np.ndarray, dict]:
    n = int(round(plan["frames"] / FPS * AUDIO_RATE))
    voice, music, amb, clips = (np.zeros(n, np.float32) for _ in range(4))
    placed = {"lines": [], "cues": [], "clips": [], "missing": []}
    missing_voice, bad_takes, unclean = [], [], []
    narr: dict[str, dict] = {}                   # narration line id -> its voice profile, for narrator-consistency
    for ln in plan["lines"]:
        wav = film / (ln.get("wav") or f"audio/{ln['id']}.wav")
        if not wav.exists():
            # a narration or testimony line is the film's words: missing, it blocks unless this is a draft
            journal.lint("audio-present", False, stage="assembly", phase="preflight", unit=ln["id"], severity="warn" if draft else "block",
                         evidence={"wav": str(wav), "kind": ln.get("kind"), "result": "silence (draft)" if draft else "refused"})
            placed["missing"].append(ln["id"])
            missing_voice.append(ln["id"])
            continue
        x = _read_wav(wav)
        synthetic = not ln.get("archival_audio")
        if synthetic and "gain_db" in ln:        # build_plan refuses it (voice-gain-db); a hand-made plan is refused here too
            raise Refused(f"voice-gain-db (A13, A14): {ln['id']} carries gain_db; a synthetic line's level is set by the engine")
        cleaned = None
        if synthetic:                            # A19: cleaned before levelling; archival audio never is
            x, cleaned = clean_voice(x)
        level = _level(journal, ln["id"], x, DIALOGUE_LUFS, "dialogue") if synthetic else None
        if cleaned is not None:
            unclean += _journal_clean(journal, ln["id"], cleaned, level, draft)
        peak = None
        if level is not None:                    # A13: peak control on a synthetic line, after its levelling
            x = x * np.float32(10 ** (level / 20))
            if ln.get("kind") == "narration":
                words = len(WORD_RE.findall(str(ln.get("text") or "")))
                narr[ln["id"]] = dict(voice_profile(x, words), mood=(ln.get("delivery") or {}).get("mood"))
            x, peak = voice_peak_control(x)
            if peak:
                _journal_peak(journal, ln["id"], peak, draft)
                if peak["bad_take"]:
                    bad_takes.append(f"{ln['id']} ({'; '.join(peak['bad_take'])})")
        offset = mood_offset(journal, ln) if synthetic else 0.0
        place_db = offset if synthetic else float(ln.get("gain_db", 0.0))
        k = _place(voice, x, float(ln["start_s"]), place_db)                # levelling is in x
        act = speech_active(x[:k], place_db)                                 # the speech-active span, as placed
        sp = plan["speakers"].get(ln.get("speaker"), {})
        placed["lines"].append({"id": ln["id"], "speaker": ln.get("speaker"), "side": sp.get("side"),
                                "kind": "narration" if ln.get("kind") == "narration" else ("archival" if ln.get("archival_audio") else "reading"),
                                "at_s": float(ln["start_s"]), "dur_s": round(k / AUDIO_RATE, 3), "line_kind": ln.get("kind"),
                                "speech_from_s": None if not len(act) else round(float(ln["start_s"]) + act[0] / AUDIO_RATE, 3),
                                "speech_to_s": None if not len(act) else round(float(ln["start_s"]) + (act[-1] + 1) / AUDIO_RATE, 3),
                                "level_db": None if level is None else round(level, 2),
                                "mood_offset_db": offset if synthetic else None,
                                "cleaned": None if cleaned is None else cleaned["cleaned"],
                                "floor_before_dbfs": None if cleaned is None else cleaned["before"]["floor_dbfs"],
                                "floor_after_dbfs": None if not (cleaned and cleaned["cleaned"]) else cleaned["after"]["floor_dbfs"],
                                "peak_reduction_db": peak["max_reduction_db"] if peak else None})
    narrator_off = narrator_consistency_lints(journal, narr, draft, plan.get("narrator_voice")) if narr else []
    for c in plan["cues"]:
        wav = film / (c.get("wav") or f"audio/{c['id']}.wav")
        if not wav.exists():
            journal.lint("audio-present", False, stage="assembly", phase="preflight", unit=c["id"], severity="warn",
                         evidence={"wav": str(wav), "kind": c.get("kind"), "result": "silence"})
            placed["missing"].append(c["id"])
            continue
        target = music if c.get("kind") == "music" else amb
        x = _read_wav(wav)
        level = None
        if c.get("kind") == "music":            # levelled over the part that plays
            span = x[: max(0, int(round((float(c["end_s"]) - float(c["start_s"])) * AUDIO_RATE)))]
            level = _level(journal, c["id"], span, MUSIC_LUFS, "music bed")
        x = cue_fades(x, float(c["end_s"]) - float(c["start_s"]), float(c.get("fade_in_s", 0) or 0),
                      float(c.get("fade_out_s", 0) or 0))
        k = _place(target, x, float(c["start_s"]), (level or 0.0) + float(c.get("gain_db", 0.0)), float(c["end_s"]))
        placed["cues"].append({"id": c["id"], "kind": c.get("kind"), "at_s": float(c["start_s"]), "dur_s": round(k / AUDIO_RATE, 3),
                               "level_db": None if level is None else round(level, 2), "part": c.get("_part"),
                               "fade_in_s": float(c.get("fade_in_s", 0) or 0), "fade_out_s": float(c.get("fade_out_s", 0) or 0)})
    for s in plan["shots"]:
        if s["kind"] == "archive_video" and (s.get("sound") or {}).get("mode", "own") == "own" and s["_video"]["probe"]["has_audio"]:
            x = clip_audio(s)
            if x is None:
                journal.lint("audio-present", False, stage="assembly", phase="preflight", unit=s["id"], severity="warn", evidence="clip audio unreadable")
                continue
            _place(clips, x, s["f0"] / FPS, end_s=s["f1"] / FPS)
            placed["clips"].append(s["id"])
    if missing_voice and not draft:
        raise Refused(f"voice WAVs missing for {', '.join(missing_voice)} (render with --draft to place silence)")
    if bad_takes and not draft:
        raise Refused(f"voice-peak-control (A13): bad takes, re-render them instead of crushing them: {'; '.join(bad_takes)}")
    if unclean:
        raise Refused(f"voice-clean and voice-chop (A19): re-render these takes (or render with --draft): {'; '.join(unclean)}")
    if narrator_off and not draft:
        raise Refused(f"narrator-consistency and narrator-drift (A14): not the narrator's voice: {'; '.join(narrator_off)}")
    mix = voice + clips + music * duck_gain(voice) + amb
    return mix.astype(np.float32), placed


def cue_fades(x: np.ndarray, span_s: float, fade_in_s: float, fade_out_s: float) -> np.ndarray:
    """A19: a cue's fade in at its start and fade out at the end of what plays
    (its end_s, or the WAV's end if sooner), each a raised cosine. The cue is
    levelled before (over the part that plays), so a fade never moves the bed."""
    n = min(len(x), max(0, int(round(span_s * AUDIO_RATE))))
    y = x[:n].astype(np.float32).copy()
    fi, fo = min(n, int(round(fade_in_s * AUDIO_RATE))), min(n, int(round(fade_out_s * AUDIO_RATE)))
    if fi > 0:
        y[:fi] *= (0.5 - 0.5 * np.cos(np.pi * (np.arange(fi) + 0.5) / fi)).astype(np.float32)
    if fo > 0:
        y[n - fo:] *= (0.5 + 0.5 * np.cos(np.pi * (np.arange(fo) + 0.5) / fo)).astype(np.float32)
    return y


def duck_gain(voice: np.ndarray) -> np.ndarray:
    """Music gain under voice (GRAMMAR 8.5): -9 dB wherever a voice speaks,
    with gaps shorter than DUCK_BRIDGE_S closed (a morphological closing of
    the voice activity), so the bed holds still between words and between
    lines instead of pumping, and a 250 ms centred ramp in and out."""
    active = (np.abs(voice) > DUCK_VOICE_THRESHOLD).astype(np.float32)
    k = int(round(DUCK_BRIDGE_S * AUDIO_RATE)) | 1
    grown = (moving_average(active, k) > 1e-6).astype(np.float32)          # dilate by half the bridge on each side
    closed = (moving_average(grown, k) > 1 - 1e-6).astype(np.float32)       # erode back: only the short gaps stay filled
    closed = np.maximum(closed, active)
    env = np.clip(moving_average(closed, int(round(DUCK_SMOOTH_S * AUDIO_RATE))), 0.0, 1.0)
    return (1.0 - env * (1.0 - 10 ** (-DUCK_DB / 20))).astype(np.float32)


def digital_silence(mix: np.ndarray, intended: list, min_s: float = SILENCE_WARN_S) -> list[dict]:
    """A19: runs of true digital silence (|x| at or under -120 dBFS) longer
    than ``min_s`` once the intended silences are taken out."""
    quiet = np.abs(mix) <= 10 ** (SILENCE_DBFS / 20)
    for a, b in intended:
        quiet[int(round(a * AUDIO_RATE)): int(round(b * AUDIO_RATE))] = False
    if not quiet.any():
        return []
    d = np.diff(np.concatenate(([0], quiet.astype(np.int8), [0])))
    starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    n = int(round(min_s * AUDIO_RATE))
    return [{"from_s": round(a / AUDIO_RATE, 3), "to_s": round(b / AUDIO_RATE, 3), "dur_s": round((b - a) / AUDIO_RATE, 3)}
            for a, b in zip(starts, ends) if b - a > n]


def voice_shares(plan: dict, placed: dict) -> dict:
    """Shares of the runtime carried by narration, by readings (testimony,
    read by a voice or archival) and by no voice at all, from the placed
    lines of the VOICE_KINDS only, each over its speech-active span (its
    first to its last sample over -60 dBFS), not the WAV's silent ends."""
    n = max(1, int(round(plan["duration_s"] * 100)))
    any_voice = np.zeros(n, bool)
    by = {"narration": np.zeros(n, bool), "testimony": np.zeros(n, bool)}
    for ln in placed["lines"]:
        kind = ln.get("line_kind", "narration" if ln["kind"] == "narration" else "testimony")
        if kind not in VOICE_KINDS:
            continue
        a_s, b_s = ln.get("speech_from_s", ln["at_s"]), ln.get("speech_to_s", ln["at_s"] + ln["dur_s"])
        if a_s is None:
            continue
        a, b = int(round(a_s * 100)), int(round(b_s * 100))
        any_voice[a:b] = True
        by[kind][a:b] = True
    return {"narration": round(by["narration"].sum() / n, 4), "readings": round(by["testimony"].sum() / n, 4),
            "voiceless": round(1.0 - any_voice.sum() / n, 4)}


def _merge_spans(spans: list[tuple[float, float]], a: float, b: float) -> list[list[float]]:
    """Spans clipped to [a, b], sorted and merged where they touch or overlap."""
    out: list[list[float]] = []
    for f, t in sorted((max(f, a), min(t, b)) for f, t in spans if f < b and t > a):
        if out and f <= out[-1][1]:
            out[-1][1] = max(out[-1][1], t)
        else:
            out.append([f, t])
    return out


def _longest_gap(merged: list[list[float]], a: float, b: float) -> tuple[float, float]:
    """The longest stretch of [a, b] outside the merged spans."""
    edges = [a] + [v for m in merged for v in m] + [b]
    return max(((edges[i], edges[i + 1]) for i in range(0, len(edges), 2)), key=lambda x: x[1] - x[0])


def still_holds(plan: dict, placed: dict) -> list[dict]:
    """Each archive still's hold against what is spoken over it (GRAMMAR
    7.2, A9, A20(a) refined in the T1f review). Consecutive archive_still
    shots of one asset joined by a cut or a dissolve are one hold; holds of
    one asset joined by a dip are linked for the silence check. Inside each
    hold, with the speech-active spans of the lines that overlap it merged:
    the whole hold is at most 30 s; the longest stretch not under a reading
    is at most 20 s; and across the linked holds the longest stretch with no
    voice is at most 10 s. A DETAIL shot is at most 5 s. Read from the
    placed lines (as the mix hears them), never from estimates."""
    voice, reading = [], []
    for ln in placed["lines"]:
        kind = ln.get("line_kind", "narration" if ln.get("kind") == "narration" else "testimony")
        if kind not in VOICE_KINDS:
            continue
        f, t = ln.get("speech_from_s", ln["at_s"]), ln.get("speech_to_s", ln["at_s"] + ln["dur_s"])
        if f is not None and t > f:
            voice.append((float(f), float(t)))
            if kind == "testimony":
                reading.append((float(f), float(t)))
    chains: list[list[list[dict]]] = []          # chains of holds (joined by dips) of holds (shots joined by cut or dissolve)
    prev = None
    for s in plan["shots"]:
        if s.get("kind") != "archive_still":
            prev = None
            continue
        tr = (s.get("transition_in") or {}).get("type", "cut")
        same = prev is not None and s.get("asset") and s.get("asset") == prev.get("asset")
        if same and tr in ("cut", "dissolve"):
            chains[-1][-1].append(s)
        elif same and tr == "dip":
            chains[-1].append([s])
        else:
            chains.append([[s]])
        prev = s
    tol = 0.5 / FPS
    out = []
    for chain in chains:
        ca, cb = float(chain[0][0]["start_s"]), float(chain[-1][-1]["end_s"])
        silent = _longest_gap(_merge_spans(voice, ca, cb), ca, cb)
        silent_s = round(silent[1] - silent[0], 3)
        why, holds = [], []
        if silent_s > STILL_MAX_S + tol:
            why.append(f"{silent_s:g} s with no voice ({silent[0]:.2f} to {silent[1]:.2f} s), at most {STILL_MAX_S:g}")
        for g in chain:
            a, b = float(g[0]["start_s"]), float(g[-1]["end_s"])
            dur = round(b - a, 3)
            unread = _longest_gap(_merge_spans(reading, a, b), a, b)
            unread_s = round(unread[1] - unread[0], 3)
            narrated = bool(_merge_spans(voice, a, b))
            holds.append({"shots": [s["id"] for s in g], "dur_s": dur, "longest_not_under_reading_s": unread_s})
            if dur > STILL_UNDER_READING_MAX_S + tol:
                why.append(f"{g[0]['id']}: hold {dur:g} s, at most {STILL_UNDER_READING_MAX_S:g}")
            if unread_s > STILL_UNDER_NARRATION_MAX_S + tol:
                why.append(f"{g[0]['id']}: {unread_s:g} s not under a reading ({unread[0]:.2f} to {unread[1]:.2f} s), "
                           f"at most {STILL_UNDER_NARRATION_MAX_S:g}" + ("" if narrated else " (and no voice at all)"))
            for s in g:
                if str(s.get("preset") or "").upper() == "DETAIL":
                    d = round(float(s["end_s"]) - float(s["start_s"]), 3)
                    if d > STILL_DETAIL_MAX_S + tol:
                        why.append(f"DETAIL {s['id']} {d:g} s, at most {STILL_DETAIL_MAX_S:g}")
        shots = [s for g in chain for s in g]
        out.append({"id": shots[0]["id"], "shots": [s["id"] for s in shots], "asset": shots[0].get("asset"),
                    "dur_s": round(cb - ca, 3), "holds": holds, "longest_voiceless_s": silent_s,
                    "limits": {"voiceless_s": STILL_MAX_S, "not_under_reading_s": STILL_UNDER_NARRATION_MAX_S,
                               "hold_s": STILL_UNDER_READING_MAX_S, "detail_s": STILL_DETAIL_MAX_S},
                    "ok": not why, "why": why})
    return out


def still_hold_lints(journal: Journal, plan: dict, placed: dict, *, draft: bool = False) -> list[str]:
    """still-hold (GRAMMAR 7.2, A9, A20(a)), one lint per archive still:
    blocking on a final render, a warning under --draft or a check render
    (--until, which may not place every line over its last shot). Returns
    the reasons to refuse."""
    binding = not draft and not plan.get("until_s")
    out = []
    for h in still_holds(plan, placed):
        journal.lint("still-hold", h["ok"], stage="assembly", phase="preflight", unit=h["id"],
                     severity="block" if binding else "warn", grammar="7.2, A9, A20(a)",
                     evidence=dict(h, rule="at most 10 s with no voice (holds of one photograph linked across a dip); at most "
                                                "20 s not under a reading; a hold at most 30 s; a DETAIL at most 5 s",
                                   fix=None if h["ok"] else "shorten the still, or cut to another picture"))
        if not h["ok"] and binding:
            out.append(f"still-hold ({h['id']}: {'; '.join(h['why'])})")
    return out


def sound_lints(journal: Journal, plan: dict, mix: np.ndarray, placed: dict, *, draft: bool = False) -> list[str]:
    """A17, A18 and A19 on the mix. digital-silence (a warning): true digital
    silence over 4 s outside an intended silence. voiceless-floor and
    readings-floor (GRAMMAR 6.1): at least 10% of the runtime has no voice
    and readings carry at least 20% (founder, 2026-10-10; was 30%); blocking on a full, final render of an
    event film, a warning on a draft, a check render (--until) or a short
    piece. The narration ceiling is lifted (A17): narration is reported, never
    capped. Returns the reasons to refuse."""
    runs = digital_silence(mix, plan.get("silences", []))
    journal.lint("digital-silence", not runs, stage="assembly", phase="preflight", severity="warn", grammar="8.4, A19",
                 evidence={"runs": runs[:20], "count": len(runs), "max_s": SILENCE_WARN_S, "threshold_dbfs": SILENCE_DBFS,
                           "intended": plan.get("silences", []),
                           "fix": "carry underscore (a music cue) through it, or mark the moment silence: intended" if runs else None})
    sh = voice_shares(plan, placed)
    # CoS ruling (T1e review): the longer of the target and the film itself, so neither can be shrunk to dodge the floors
    length = max(float(plan.get("runtime_target_s") or 0.0), float(plan["duration_s"]))
    binding = not draft and not plan.get("until_s") and length >= EVENT_FILM_MIN_S
    sev = "block" if binding else "warn"
    why = None if binding else ("draft" if draft else "check render (--until)" if plan.get("until_s") else
                                f"the film and its runtime target are both under {EVENT_FILM_MIN_S:g} s (a short piece)")
    out = []
    for rule, ok, ev in (("voiceless-floor", sh["voiceless"] >= VOICELESS_FLOOR, {"voiceless": sh["voiceless"], "min": VOICELESS_FLOOR}),
                         ("readings-floor", sh["readings"] >= READINGS_FLOOR, {"readings": sh["readings"], "min": READINGS_FLOOR})):
        journal.lint(rule, ok, stage="assembly", phase="preflight", severity=sev, grammar="6.1, A17, A18",
                     evidence=dict(ev, shares=sh, binding=binding, warning_because=why))
        if not ok and binding:
            out.append(f"{rule}: {ev}")
    journal.event("unit", "assembly", "mix", lens="shares", status="info", shares=sh, narration_ceiling=None,
                  note="A17 lifts the 25% narration ceiling; narration is reported, not capped")
    return out


def loudness_lints(journal: Journal, loud: dict, *, draft: bool = False) -> list[str]:
    """Journal what the loudness pass did and why: every step it took (the
    LRA target raised above the programme's own range, the true-peak limiter
    with the values each attempt used) as a decision, the measured result
    against the -18 LUFS target, whether the gain was linear, and whether the limiter
    stayed peak control (GRAMMAR 8.5 keeps archival audio's own dynamics).
    A dynamic result or a limiter that compressed blocks a final master, and
    is only a warning under --draft. Returns the reasons the run must be
    refused (empty when it may go on)."""
    if not loud["normalised"]:
        journal.decision("assembly", "loudness not normalised", "the programme is silent (no voice, music or clip sound placed)")
        return []
    for step in loud.get("steps", []):
        journal.decision("assembly", step["what"], step["why"], unit="loudness", evidence=step.get("evidence"))
    journal.lint("loudness", phase="preflight", passed=abs(loud["output_i"] - TARGET_LUFS) <= 1.0 and loud["output_tp"] <= TARGET_TP + 0.5,
                 stage="assembly", severity="warn", evidence=loud, grammar="8.5")
    sev = "warn" if draft else "block"
    refusals = []
    blockers = "; ".join(loud.get("blockers") or ["cause unknown"])
    causes = {k: loud.get(k) for k in ("input_i", "input_tp", "input_lra", "gain_db", "predicted_tp", "lra_target")}
    causes["limiter"] = {k: v for k, v in (loud.get("limiter") or {}).items() if k != "acted"} or None
    journal.lint("loudnorm-linear", loud["linear"], stage="assembly", phase="preflight", severity=sev,
                 grammar="8.5", evidence=dict(causes, normalization_type=loud["normalization_type"],
                                              result=None if loud["linear"] else ("dynamic (draft)" if draft else "refused"),
                                              why=None if loud["linear"] else
                                              "loudnorm fell back to dynamic mode, which compresses the programme "
                                              f"(GRAMMAR 8.5 keeps archival dynamics): {blockers}"))
    if not loud["linear"]:
        journal.decision("assembly", "the mix was normalised in loudnorm's dynamic mode", blockers, unit="loudness")
        refusals.append(f"the mix could only reach {TARGET_LUFS:g} LUFS in loudnorm's dynamic mode: {blockers}")
    lim = loud.get("limiter")
    if lim:
        over = limiter_overreach(lim)
        journal.lint("limiter-peak-only", not over, stage="assembly", phase="preflight", severity=sev, grammar="8.5",
                     evidence={"max_reduction_db": lim["max_reduction_db"], "over_1db_s": lim["over_1db_s"],
                               "input_lra": loud["input_lra"], "lra_after": lim["lra_after"], "lra_drop": lim["lra_drop"],
                               "limits": {"max_db": LIMIT_MAX_DB, "over_1db_s": LIMIT_OVER_1DB_S, "lra_drop": LIMIT_LRA_DROP},
                               "acted": lim["acted"], "acted_total": lim["acted_total"], "over": over,
                               "result": None if not over else ("compressed (draft)" if draft else "refused")})
        if over:
            refusals.append("the true-peak limiter compressed the programme instead of only catching peaks: " + "; ".join(over))
    else:
        journal.lint("limiter-peak-only", True, stage="assembly", phase="preflight", severity=sev, grammar="8.5",
                     evidence={"limiter": "not needed", "max_reduction_db": 0.0, "over_1db_s": 0.0,
                               "predicted_tp": loud["predicted_tp"], "ceiling": TARGET_TP})
    return [] if draft else refusals


def limiter_overreach(lim: dict) -> list[str]:
    """How the limiter went past peak control, if it did: more than 1 dB of
    gain reduction for over 50 ms in total, more than 3 dB at any point, or
    the loudness range after limiting more than 0.3 LU under the mix's own."""
    over = []
    if lim["max_reduction_db"] > LIMIT_MAX_DB:
        over.append(f"{lim['max_reduction_db']:.2f} dB of gain reduction at {lim['max_at_s']:.3f} s (limit {LIMIT_MAX_DB:g} dB)")
    if lim["over_1db_s"] > LIMIT_OVER_1DB_S:
        over.append(f"more than 1 dB of gain reduction for {lim['over_1db_s']:.3f} s in total (limit {LIMIT_OVER_1DB_S:g} s)")
    if lim["lra_drop"] > LIMIT_LRA_DROP:
        over.append(f"the loudness range fell {lim['lra_drop']:.2f} LU (limit {LIMIT_LRA_DROP:g})")
    return over


def _loudnorm_json(stderr: str) -> dict:
    j = stderr[stderr.rfind("{"): stderr.rfind("}") + 1]
    return json.loads(j) if j else {}


def _measure(src: Path | np.ndarray) -> dict:
    """loudnorm's first pass on a file or a mono 48 kHz float array:
    integrated loudness, true peak, loudness range, gate threshold and target
    offset, as floats (silence measures input_i -inf). A failed or unreadable
    measurement raises EncodeError: it must never pass for silence."""
    cmd = [ffmpeg(), "-hide_banner", "-nostats"]
    if isinstance(src, np.ndarray):
        cmd += ["-f", "f32le", "-ar", str(AUDIO_RATE), "-ac", "1", "-i", "pipe:0"]
        data = np.ascontiguousarray(src, dtype=np.float32).tobytes()
    else:
        cmd += ["-i", str(src)]
        data = None
    cmd += ["-af", f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TP}:LRA={TARGET_LRA}:print_format=json", "-f", "null", "-"]
    r = subprocess.run(cmd, input=data, capture_output=True)
    err = r.stderr.decode(errors="replace")
    try:
        m = _loudnorm_json(err)
        out = {k: float(m[k]) for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")}
    except (KeyError, ValueError, json.JSONDecodeError):
        out = {}
    if r.returncode or not out:
        raise EncodeError(f"loudness measurement failed (exit {r.returncode}): {err[-300:]}")
    return out


def _measure_line(x: np.ndarray) -> dict:
    """_measure on a line, looped end to end to LEVEL_MIN_S when it is
    shorter (loudnorm needs one 400 ms gating block): a loop has the line's
    own mean-square loudness and true peak. ``looped`` says how often."""
    n = int(LEVEL_MIN_S * AUDIO_RATE)
    reps = 1 if len(x) >= n or len(x) == 0 else math.ceil(n / len(x))
    m = _measure(np.tile(x, reps) if reps > 1 else x)
    m["looped"] = reps
    return m


def level_gain(x: np.ndarray, target: float) -> tuple[float | None, dict]:
    """The linear gain that brings x's integrated loudness to target, and the
    measurement. A line under 0.4 s is measured looped (``looped`` > 1).
    None when x is empty or too quiet to measure (gated out)."""
    if len(x) == 0:
        return None, {}
    m = _measure_line(x)
    if not math.isfinite(m["input_i"]) or m["input_i"] < -70:
        return None, m
    return target - m["input_i"], m


def _limit(src: Path, dst: Path, gain_db: float, ceiling_db: float) -> None:
    """Linear gain, then a true-peak limiter: alimiter run 4x oversampled
    (192 kHz), so the peaks it holds under the ceiling include inter-sample
    peaks, with no auto level and its look-ahead delay compensated."""
    lim = 10 ** (ceiling_db / 20)
    af = (f"volume={gain_db:.3f}dB:precision=double,aresample={AUDIO_RATE * LIMIT_OVERSAMPLE},"
          f"alimiter=limit={lim:.6f}:attack={LIMITER_ATTACK_MS}:release={LIMITER_RELEASE_MS}:level=0:latency=1,"
          f"aresample={AUDIO_RATE}")
    r = subprocess.run([ffmpeg(), "-hide_banner", "-nostats", "-v", "error", "-y", "-i", str(src), "-af", af,
                        "-ar", str(AUDIO_RATE), "-c:a", "pcm_f32le", str(dst)], capture_output=True, text=True)
    if r.returncode:
        raise EncodeError(f"true-peak limiter failed: {r.stderr[-500:]}")


def _limit_array(x: np.ndarray, ceiling_db: float) -> np.ndarray:
    """The true-peak limiter of _limit (alimiter, 4x oversampled, delay
    compensated, no auto level) on a mono 48 kHz array, same length out."""
    lim = 10 ** (ceiling_db / 20)
    af = (f"aresample={AUDIO_RATE * LIMIT_OVERSAMPLE},alimiter=limit={lim:.6f}:attack={LIMITER_ATTACK_MS}:"
          f"release={LIMITER_RELEASE_MS}:level=0:latency=1,aresample={AUDIO_RATE}")
    r = subprocess.run([ffmpeg(), "-hide_banner", "-nostats", "-v", "error", "-f", "f32le", "-ar", str(AUDIO_RATE), "-ac", "1",
                        "-i", "pipe:0", "-af", af, "-f", "f32le", "-ar", str(AUDIO_RATE), "-ac", "1", "pipe:1"],
                       input=np.ascontiguousarray(x, dtype=np.float32).tobytes(), capture_output=True)
    if r.returncode:
        raise EncodeError(f"voice peak limiter failed: {r.stderr.decode(errors='replace')[-500:]}")
    y = np.frombuffer(r.stdout, dtype=np.float32).copy()
    return np.pad(y, (0, max(0, len(x) - len(y))))[: len(x)]


def voice_peak_control(x: np.ndarray, ceiling_db: float | None = None) -> tuple[np.ndarray, dict | None]:
    """GRAMMAR A13: a levelled synthetic voice line whose true peak passes
    the voice ceiling goes through the oversampled true-peak limiter, so its
    crest fits the master's 16.5 dB between -18 LUFS and -1.5 dBTP (A15). Returns
    the line and what the limiter did (None when it was not needed), with
    ``bad_take`` listing why when its cuts were compression, not peak
    control: over 8 dB for more than 20 ms in total, over 1 dB for more than
    20% of the line, or over 3 dB for more than 5% of it."""
    ceiling_db = VOICE_TP if ceiling_db is None else ceiling_db
    m = _measure_line(x)                         # a line under 0.4 s is measured looped, so it is peak-controlled too
    if not math.isfinite(m["input_tp"]) or m["input_tp"] <= ceiling_db:
        return x, None
    y = _limit_array(x, ceiling_db - VOICE_LIMIT_MARGIN_DB)
    gr = _gr_stats(x, y)
    dur = len(x) / AUDIO_RATE
    share1 = gr["over_1db_s"] / dur if dur else 0.0
    share3 = gr["over_3db_s"] / dur if dur else 0.0
    bad = []
    if gr["over_8db_s"] > VOICE_OVER_8DB_MAX_S:
        bad.append(f"over 8 dB for {gr['over_8db_s']:.3f} s in total (limit {VOICE_OVER_8DB_MAX_S:g} s; "
                   f"at most {gr['max_reduction_db']:.2f} dB at {gr['max_at_s']:.3f} s)")
    if share1 > VOICE_OVER_1DB_MAX_SHARE:
        bad.append(f"over 1 dB for {gr['over_1db_s']:.3f} s, {share1:.1%} of the line (limit {VOICE_OVER_1DB_MAX_SHARE:.0%})")
    if share3 > VOICE_OVER_3DB_MAX_SHARE:
        bad.append(f"over 3 dB for {gr['over_3db_s']:.3f} s, {share3:.1%} of the line (limit {VOICE_OVER_3DB_MAX_SHARE:.0%})")
    after = _measure_line(y)
    return y, dict(gr, ceiling_dbtp=round(ceiling_db - VOICE_LIMIT_MARGIN_DB, 2), tp_before=m["input_tp"], tp_after=after["input_tp"],
                   i_after=after["input_i"], dur_s=round(dur, 3), over_1db_share=round(share1, 4), over_3db_share=round(share3, 4),
                   measured_looped=m["looped"], bad_take=bad)


def gain_reduction(src: Path, limited: Path, gain_db: float, block_ms: float = 1.0) -> dict:
    """What the limiter did, measured: the input with its linear gain against
    the limiter's output, block by block (1 ms RMS ratio). Returns the largest
    reduction and where, the time spent over 1 dB, and the stretches where it
    acted (over 0.1 dB, merged across gaps under 10 ms)."""
    import soundfile as sf
    a, _ = sf.read(str(src), dtype="float64", always_2d=True)
    b, _ = sf.read(str(limited), dtype="float64", always_2d=True)
    return _gr_stats(a.mean(axis=1) * 10 ** (gain_db / 20), b.mean(axis=1), block_ms)


def _gr_stats(a: np.ndarray, b: np.ndarray, block_ms: float = 1.0) -> dict:
    """gain_reduction's measure on two aligned mono arrays: a before the limiter, b after it."""
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    n = min(len(a), len(b))
    k = max(1, int(round(AUDIO_RATE * block_ms / 1000)))
    m = n // k
    ra = np.sqrt(np.mean(a[: m * k].reshape(m, k) ** 2, axis=1))
    rb = np.sqrt(np.mean(b[: m * k].reshape(m, k) ** 2, axis=1))
    live = ra > 10 ** (-60 / 20)
    gr = np.zeros(m)
    gr[live] = np.clip(20 * np.log10(ra[live] / np.maximum(rb[live], 1e-12)), 0, None)
    block_s = k / AUDIO_RATE
    acted = []
    idx = np.flatnonzero(gr > 0.1)
    if len(idx):
        start = prev = idx[0]
        for j in list(idx[1:]) + [None]:
            if j is not None and (j - prev) * block_s < 0.010:
                prev = j
                continue
            seg = gr[start:prev + 1]
            acted.append({"at_s": round(start * block_s, 3), "dur_s": round((prev - start + 1) * block_s, 3),
                          "max_db": round(float(seg.max()), 2)})
            if j is not None:
                start = prev = j
    top = int(np.argmax(gr)) if m else 0
    return {"max_reduction_db": round(float(gr.max()) if m else 0.0, 2), "max_at_s": round(top * block_s, 3),
            "over_1db_s": round(float(np.count_nonzero(gr > 1.0)) * block_s, 3),
            "over_3db_s": round(float(np.count_nonzero(gr > 3.0)) * block_s, 3),
            "over_8db_s": round(float(np.count_nonzero(gr > 8.0)) * block_s, 3),
            "acted_s": round(float(np.count_nonzero(gr > 0.1)) * block_s, 3), "block_ms": block_ms,
            "acted_total": len(acted), "acted": sorted(acted, key=lambda e: -e["max_db"])[:LIMIT_ACTED_LOGGED]}


def loudnorm(src: Path, dst: Path) -> dict:
    """EBU R128 to -18 LUFS (A15) integrated, -1.5 dBTP, by linear gain only
    (GRAMMAR 8.5: archival audio keeps its own dynamics). The voices and
    music were already levelled line by line (build_mix), so the gain here
    is small.

    1. Measure the mix (loudnorm's first pass).
    2. If the gain to -18 LUFS would push the true peak past -1.5 dBTP, apply
       that gain and an oversampled true-peak limiter just under the ceiling
       (``<dst stem>-limited.wav``), measure again, and measure what the
       limiter did (``gain_reduction``). It may only catch peaks; how much it
       acted, and where, is returned for loudness_lints to judge.
    3. Set the LRA target above the measured range (8.5 sets no LRA limit;
       loudnorm stays linear only when the range fits its target).
    4. Apply loudnorm with ``linear=true`` and the measured values.

    Returns the measurements, every step taken (``steps``, journaled as
    decisions), and why a result is not linear (``blockers``)."""
    m1 = _measure(src)
    if not math.isfinite(m1["input_i"]) or m1["input_i"] < -70:
        shutil.copyfile(src, dst)
        return {"normalised": False, "input_i": m1["input_i"], "reason": "silent programme"}
    steps, blockers = [], []
    gain = TARGET_LUFS - m1["input_i"]
    predicted = m1["input_tp"] + gain
    res = {"normalised": True, "input_i": m1["input_i"], "input_tp": m1["input_tp"], "input_lra": m1["input_lra"],
           "gain_db": round(gain, 2), "predicted_tp": round(predicted, 2), "limiter": None}
    feed, m = src, m1
    if predicted > TARGET_TP:
        limited = dst.with_name(dst.stem + "-limited.wav")
        ceiling = TARGET_TP - LIMIT_MARGIN_DB
        attempts = []
        for attempt in range(1, LIMIT_ATTEMPTS + 1):
            _limit(src, limited, gain, ceiling)
            m = _measure(limited)
            after = m["input_tp"] + TARGET_LUFS - m["input_i"]
            attempts.append({"attempt": attempt, "pre_gain_db": round(gain, 2), "ceiling_dbtp": round(ceiling, 2),
                             "measured": {k: m[k] for k in ("input_i", "input_tp", "input_lra")},
                             "peak_after_final_gain_dbtp": round(after, 2)})
            if after <= TARGET_TP:
                break
            ceiling -= after - TARGET_TP + 0.1      # the final linear gain would lift the held peaks past the ceiling
        feed = limited
        gr = gain_reduction(src, limited, gain)
        res["limiter"] = dict(gr, ceiling_dbtp=round(ceiling, 2), pre_gain_db=round(gain, 2), oversample=LIMIT_OVERSAMPLE,
                              attack_ms=LIMITER_ATTACK_MS, release_ms=LIMITER_RELEASE_MS, attempts=attempts, file=str(limited),
                              lra_after=m["input_lra"], lra_drop=round(m1["input_lra"] - m["input_lra"], 2))
        steps.append({"what": f"true-peak limiter (alimiter, {LIMIT_OVERSAMPLE}x oversampled) at {ceiling:.2f} dBTP before the linear gain",
                      "why": f"the mix's true peak {m1['input_tp']:.2f} dBTP plus the {gain:.2f} dB gain to {TARGET_LUFS:g} LUFS "
                             f"would reach {predicted:.2f} dBTP, past {TARGET_TP:g}; it acted for {gr['acted_s']:.3f} s in "
                             f"{gr['acted_total']} places, at most {gr['max_reduction_db']:.2f} dB (at {gr['max_at_s']:.3f} s)",
                      "evidence": {k: v for k, v in res["limiter"].items() if k != "acted"}})
    lra_target = min(LRA_MAX, max(TARGET_LRA, float(math.ceil(m["input_lra"] + 1.0))))
    res["lra_target"] = lra_target
    if lra_target > TARGET_LRA:
        steps.append({"what": f"loudnorm LRA target raised from {TARGET_LRA:g} to {lra_target:g} LU",
                      "why": f"the mix's own loudness range is {m['input_lra']:.1f} LU; loudnorm compresses a range above "
                             "its target, and GRAMMAR 8.5 sets no range limit",
                      "evidence": {"input_lra": m["input_lra"], "lra_target": lra_target}})
    if m["input_lra"] > lra_target:
        blockers.append(f"input_lra {m['input_lra']:.1f} LU exceeds loudnorm's largest LRA target ({LRA_MAX:g})")
    if m["input_tp"] + TARGET_LUFS - m["input_i"] > TARGET_TP:
        blockers.append(f"true peak {m['input_tp']:.2f} dBTP plus {TARGET_LUFS - m['input_i']:.2f} dB gain passes {TARGET_TP:g} dBTP"
                        + (" after the limiter" if res["limiter"] else ""))
    measured_lra = max(m["input_lra"], 0.1)       # loudnorm never runs linear on a measured LRA of exactly 0 (a steady tone)
    af = (f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TP}:LRA={lra_target}:measured_I={m['input_i']}:measured_TP={m['input_tp']}"
          f":measured_LRA={measured_lra}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true:print_format=json")
    r2 = subprocess.run([ffmpeg(), "-hide_banner", "-nostats", "-y", "-i", str(feed), "-af", af, "-ar", str(AUDIO_RATE),
                         "-c:a", "pcm_s24le", str(dst)], capture_output=True, text=True)
    if r2.returncode:
        raise EncodeError(f"loudnorm pass 2 failed: {r2.stderr[-500:]}")
    m2 = _loudnorm_json(r2.stderr)
    nt = m2.get("normalization_type")
    if nt != "linear" and not blockers:
        blockers.append(f"loudnorm reported {nt!r}")
    res.update(output_i=float(m2.get("output_i", "nan")), output_tp=float(m2.get("output_tp", "nan")),
               output_lra=float(m2.get("output_lra", "nan")), normalization_type=nt, linear=nt == "linear",
               steps=steps, blockers=blockers)
    return res


# --------------------------------------------------------------------------
# Sources timeline
# --------------------------------------------------------------------------


def sources_doc(plan: dict, journal: Journal, extra: dict) -> dict:
    shots = []
    for s in plan["shots"]:
        it = s.get("_item") or {}
        shots.append({
            "id": s["id"], "part": s["_part"], "kind": s["kind"],
            "start_s": round(s["f0"] / FPS, 4), "end_s": round(s["f1"] / FPS, 4),
            "start_frame": s["f0"], "end_frame": s["f1"],
            "mark": {"class": s["mark"], "detail": s["detail"], "label": s.get("label", "")},
            "ledger": it.get("_ledger"), "ledger_id": s.get("asset"),
            "title": it.get("title"), "archive": it.get("archive"), "item_url": it.get("item_url"), "date": it.get("date"),
            "creator": it.get("creator"), "credit": it.get("credit"), "licence": it.get("licence"), "basis": it.get("basis"),
            "alterations": s.get("alterations") or [], "transition_in": s["transition_in"],
            "preset": (s.get("_cam") or {}).get("preset"), "fill_ok": (s.get("_cam") or {}).get("fill_ok"),
            "in_s": s.get("in_s"), "out_s": s.get("out_s"),
            "resampler": s.get("_resampler"), "conform": (s.get("_video") or {}).get("conform"),
            "neutralise_cast": (s.get("_video") or {}).get("neutralise_cast"),
            "test_fixture": is_synthetic(it),
            "text": s.get("text"),
        })
    track = []
    for s in shots:
        if track and track[-1]["class"] == s["mark"]["class"] and track[-1]["detail"] == s["mark"]["detail"]:
            track[-1]["to_s"] = s["end_s"]
        else:
            track.append({"from_s": s["start_s"], "to_s": s["end_s"], "class": s["mark"]["class"], "detail": s["mark"]["detail"],
                          "label": s["mark"]["label"]})
    total = plan["frames"]
    share = {c: round(sum(s["end_frame"] - s["start_frame"] for s in shots if s["mark"]["class"] == c) / total, 4) for c in CLASSES}
    readings = []
    for ln in plan["lines"]:
        if ln.get("kind") == "testimony":
            sp = plan["speakers"].get(ln.get("speaker"), {})
            # How long the reading is heard (its measured WAV) and whose words they are: the site's
            # "Whose words, and how long" balance is computed from these (web/src/film-data.ts).
            wav = voice_wav(Path(plan["film"]), ln)
            dur = round(wav_seconds(wav), 3) if wav.exists() else None
            readings.append({"id": ln["id"], "speaker": ln.get("speaker"), "name": sp.get("name"), "side": sp.get("side"),
                             "gender": sp.get("gender"), "dur_s": dur,
                             "year": ln.get("year"), "source": ln.get("source"), "locator": ln.get("locator"),
                             "start_s": ln.get("start_s"), "text": ln.get("text"),
                             "credit": (f"Read by a computer voice. No recording of {sp.get('name', ln.get('speaker'))} was used."
                                        if ln.get("read_by") else "original recording")})
    return {"v": 2, "title": plan["title"], "slug": plan["slug"], "run": journal.run,
            "engine": {"version": ENGINE_VERSION, "hash": ENGINE_HASH},
            "width": plan["W"], "height": plan["H"], "fps": FPS, "frames": total, "duration_s": round(total / FPS, 4),
            "shots": shots, "marks": track, "share": share,
            "lower_thirds": [{"id": lt["id"], "start_s": lt["start"], "end_s": lt["end"], "lines": lt["lines"], "flag": lt["flag"]}
                             for lt in plan["lower_thirds"]],
            "readings": readings,
            "cues": [{k: c.get(k) for k in ("id", "kind", "role", "source", "licence", "tradition", "performer", "start_s", "end_s")}
                     for c in plan["cues"]],
            "credits": [{"heading": h, "lines": ln} for h, ln in plan["credits"]], **extra}


# --------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if k not in ("_item",)}


def tools_key() -> dict:
    """What else changes a segment's pixels: the ffmpeg build and the font files."""
    f = M.Fonts()
    fonts = {}
    for name in ("display", "display_italic", "display_regular", "structure", "structure_medium", "data", "data_semibold"):
        path = Path(getattr(f, name))
        fonts[name] = sha256_file(path)[:16] if path.exists() else None
    return {"ffmpeg": ffmpeg_version(), "fonts": fonts}


def shot_key(plan: dict, i: int, asset_hash: dict, env_key: dict | None = None) -> str:
    s = plan["shots"][i]
    t0, t1 = s["f0"] / FPS, s["f1"] / FPS
    prev = plan["shots"][i - 1] if i else None
    nxt = plan["shots"][i + 1] if i + 1 < len(plan["shots"]) else None
    rec = {
        "engine": ENGINE_HASH, "W": plan["W"], "H": plan["H"], "fps": FPS, "shot": _clean(s),
        "asset": asset_hash.get(s.get("asset")), "prev": _clean(prev) if prev else None,
        "prev_asset": asset_hash.get(prev.get("asset")) if prev else None,
        "next_transition": nxt["transition_in"] if nxt else None, "next_f0": nxt["f0"] if nxt else None,
        "marks": plan["marks"][max(0, i - 1): i + 1],
        "lower_thirds": [lt for lt in plan["lower_thirds"] if lt["start"] < t1 and lt["end"] > t0],
        "overlays": [o for o in plan["overlays"] if o["start"] < t1 and o["end"] > t0],
        "tools": env_key,
        "subtitles": [c for c in plan["subtitles"] if c["start"] < t1 and c["end"] > t0],
        "wm": [plan["wm_start"], plan["card_spans"]],
        "credits": plan["credits"] if s.get("_card") == "credits" else None,
    }
    return hashlib.sha256(json.dumps(rec, sort_keys=True, default=str).encode()).hexdigest()[:16]


class _Direct:
    def __init__(self, fn):
        self.put = fn


def render(film: Path | str, out: Path | str | None = None, *, height: int = 1080, from_shot: str | None = None,
           workers: int = DEFAULT_WORKERS, burn_subtitles: bool = False, min_free_gb: float = MIN_FREE_GB,
           encode_preset: str = "slow", draft: bool = False, fit_voices_opt: bool = False, audio_only: bool = False,
           until_s: float | None = None, journal: Journal | None = None) -> dict:
    film = Path(film).resolve()
    out = Path(out).resolve() if out else film / "out"
    W, H = frame_size(height)
    journal = journal or Journal(film=film.name, out_dir=out)
    run_t0 = time.perf_counter()
    resume_cmd = f"python -m studio.engine.render {film} --out {out} --res {height}" + (
        f" --until {until_s:g}" if until_s is not None else "")
    # A check render (--until) keeps its segments, mix and outputs apart: it never touches, or passes as, the full render.
    check = f"check-{until_s:g}s" if until_s is not None else None
    run_dir = out / check if check else out
    settings = {"height": H, "width": W, "fps": FPS, "workers": workers, "from": from_shot, "burn_subtitles": burn_subtitles,
                "min_free_gb": min_free_gb, "encode_preset": encode_preset, "draft": draft, "fit_voices": fit_voices_opt,
                "audio_only": audio_only, "until_s": until_s}
    current = {"stage": "scout", "unit": None}
    n_req = int(workers)
    n = max(1, min(n_req, MAX_WORKERS, os.cpu_count() or 1))
    try:
        # run.start is always the journal's first event and run.end its last (design/spec.md 5a).
        journal.event("stage", "run", None, lens="run.start", status="start", film=film.name, run_kind=journal.kind,
                      stages=["scout", "conform", "assembly", "motion", "marks"], resumed_from=from_shot,
                      settings=dict(settings, workers=n, workers_requested=n_req), model=ENGINE_MODEL,
                      ffmpeg=ffmpeg_version(), out=str(out), predict={}, baselines_at=None, machine=journal.machine())
        # Pre-flight: every check the plan can decide runs here, before any frame is rendered: the drive,
        # licences, marks, transitions, dips, zoom limits, A7 framing, voice-overlap, then A7 on each
        # still's own first frame. The rendered pixels are checked again after motion (phase post-render).
        journal.stage("scout", "start", phase="preflight")
        if draft:
            journal.human("scout", "draft render: missing voice WAVs become silence; dynamic loudness, a compressing master limiter, A13 bad takes and narrator-consistency are warnings instead of refusing the run",
                          override="--draft")
        with journal.unit("scout", "preflight", size={"driver": "items", "value": 1}):
            pf = preflight(out, journal, min_free_gb=min_free_gb)
        fonts = M.Fonts()
        missing = [p for p in (fonts.display, fonts.structure, fonts.data) if not Path(p).exists()]
        if missing:
            raise Refused(f"fonts not found ({missing[0]}); run npm ci in the repo")
        play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
        if fit_voices_opt:
            journal.human("scout", "--fit-voices: voice lines may move later and their shots grow", override="--fit-voices")
            play = fit_voices(play, film, journal)
            out.mkdir(parents=True, exist_ok=True)
            fitted = out / "screenplay.fitted.json"
            fitted.write_text(json.dumps(play, indent=2, ensure_ascii=False), encoding="utf-8")
            journal.artifact("scout", fitted, role="screenplay-fitted")
        with journal.unit("scout", "sources", size={"driver": "items", "value": 0}) as u:
            bad_sources = preflight_sources(film, play, journal, draft=draft)
            u.extra.update(problems=len(bad_sources))
        if bad_sources:
            raise Refused("source files missing or unreadable (pre-flight): " + "; ".join(
                f"{b['unit']}: {b['file']} ({b['why']})" for b in bad_sources))
        with journal.unit("scout", "plan", size={"driver": "items", "value": 0}) as u:
            plan = build_plan(film, W=W, H=H, burn_subtitles=burn_subtitles, journal=journal, play=play)
            u.size = {"driver": "items", "value": len(plan["shots"])}
        if until_s is not None:
            journal.human("scout", f"--until {until_s:g}: only the shots that start before {until_s:g} s are rendered",
                          override="--until")
            plan = trim_plan(plan, until_s)
        stills = [s["id"] for s in plan["shots"] if s["kind"] == "archive_still" and s.get("_cam")]
        with journal.unit("scout", "preflight-stills", size={"driver": "items", "value": len(stills)}):
            not_whole = preflight_stills(plan, journal)
            if not_whole:
                raise Refused(f"A7 (pre-flight): the first frame of {', '.join(not_whole)} is not the whole photograph")
        journal.stage("scout", "done", phase="preflight", frames_rendered=0)

        if n != n_req:
            journal.decision("motion", f"workers clamped from {n_req} to {n}",
                             f"hard maximum {MAX_WORKERS} (this laptop crashes under parallel load) and {os.cpu_count()} CPUs")
        ids = [s["id"] for s in plan["shots"]]
        from_idx = None
        if from_shot is not None:
            if from_shot not in ids:
                raise Refused(f"--from {from_shot}: no such shot (shots: {', '.join(ids)})")
            from_idx = ids.index(from_shot)

        seg_dir = run_dir / "segments"
        seg_dir.mkdir(parents=True, exist_ok=True)
        asset_hash = {}
        for s in plan["shots"]:
            p = (s.get("_item") or {}).get("_path")
            if p and s.get("asset") not in asset_hash:
                asset_hash[s["asset"]] = sha256_file(p)
        env_key = tools_key()
        segs, todo, cached = {}, [], []
        for i, s in enumerate(plan["shots"]):
            key = shot_key(plan, i, asset_hash, env_key)
            seg = seg_dir / f"{s['id']}.{key}.mp4"
            segs[i] = seg
            for old in seg_dir.glob(f"{s['id']}.*.mp4"):
                if old != seg:
                    old.unlink(missing_ok=True)
                    Path(str(old) + ".json").unlink(missing_ok=True)
            have = seg.exists() and Path(str(seg) + ".json").exists()
            if from_idx is not None and i < from_idx:
                if not have:
                    raise Refused(f"--from {from_shot}: shot {s['id']} has no cached segment matching the screenplay; "
                                  "render without --from first")
                cached.append(i)
            elif from_idx is None and have:
                cached.append(i)
            else:
                todo.append(i)

        # What run.start cannot know until the screenplay is read: the units and the film's length.
        journal.event("stage", "run", None, lens="run.plan", status="planned", film=plan["slug"], title=plan["title"],
                      units=[{"id": s["id"], "stage": "motion", "size": {"driver": "frames", "value": s["f1"] - s["f0"]}}
                             for s in plan["shots"]],
                      duration_s=plan["duration_s"], frames=plan["frames"], todo=[ids[i] for i in todo],
                      cached=[ids[i] for i in cached], preflight=pf)

        # Audio first (cheap), so the marks event can carry the voice shares.
        current.update(stage="assembly", unit="mix")
        journal.stage("assembly", "start")
        work = run_dir / "work"
        work.mkdir(parents=True, exist_ok=True)
        with journal.unit("assembly", "mix", size={"driver": "seconds", "value": round(plan["duration_s"], 3)}) as u:
            mix, placed = build_mix(plan, film, journal, draft=draft)
            import soundfile as sf
            sf.write(str(work / "mix.wav"), mix, AUDIO_RATE, subtype="FLOAT")
            u.extra.update(placed=placed)
        journal.artifact("assembly", work / "mix.wav", unit="mix", role="mix")
        share_refusals = sound_lints(journal, plan, mix, placed, draft=draft)
        if share_refusals:
            raise Refused(f"voice shares (pre-flight): {'; '.join(share_refusals)} (GRAMMAR 6.1; render with --draft to accept it)")
        hold_refusals = still_hold_lints(journal, plan, placed, draft=draft)
        if hold_refusals:
            raise Refused(f"still holds (pre-flight): {'; '.join(hold_refusals)} (GRAMMAR 7.2, A9, A20(a); "
                          "render with --draft to accept it)")
        journal.event("unit", "assembly", "mix", lens="narration", status="info", lines=placed["lines"], peaks=None)
        with journal.unit("assembly", "loudness", size={"driver": "seconds", "value": round(plan["duration_s"], 3)},
                          settings={"I": TARGET_LUFS, "TP": TARGET_TP, "LRA_min": TARGET_LRA, "linear": True,
                                    "limiter": {"oversample": LIMIT_OVERSAMPLE, "margin_db": LIMIT_MARGIN_DB}}) as u:
            loud = loudnorm(work / "mix.wav", work / "mix-norm.wav")
            u.extra.update(loudness=loud)
        if loud.get("limiter"):
            journal.artifact("assembly", loud["limiter"]["file"], unit="loudness", role="mix-limited")
        journal.artifact("assembly", work / "mix-norm.wav", unit="loudness", role="mix-normalised")
        # Pre-flight, before any frame: a final master's loudness is linear, and its limiter only catches peaks (GRAMMAR 8.5).
        refusals = loudness_lints(journal, loud, draft=draft)
        if refusals:
            raise Refused(f"loudness (pre-flight): {'; '.join(refusals)} (GRAMMAR 8.5; render with --draft to accept it)")
        if audio_only:                       # --audio-only: the pre-flight and the sound, no frames and no master
            journal.stage("assembly", "done", detail={"audio_only": True})
            summary = {"run": journal.run, "journal": str(journal.path), "mix": str(work / "mix-norm.wav"), "loudness": loud,
                       "partial": bool(check), "until_s": until_s,
                       "frames": 0, "duration_s": plan["duration_s"], "wall_s": round(time.perf_counter() - run_t0, 2)}
            journal.event("stage", "run", None, lens="run.end", status="done", outcome="ok", audio_only=True,
                          **{k: v for k, v in summary.items() if k != "loudness"})
            return summary

        # Frames.
        current.update(stage="motion", unit=None)
        journal.stage("motion", "start", detail={"todo": [ids[i] for i in todo], "cached": [ids[i] for i in cached], "workers": n})
        for i in cached:
            journal.event("unit", "motion", ids[i], lens="unit.done", status="skip", outcome="cached",
                          segment=str(segs[i]), size={"driver": "frames", "value": plan["shots"][i]["f1"] - plan["shots"][i]["f0"]})
        results: dict[int, dict] = {i: json.loads(Path(str(segs[i]) + ".json").read_text(encoding="utf-8")) for i in cached}

        def on_msg(msg):
            lens = msg.pop("lens")
            stage, unit = msg.pop("stage"), msg.pop("unit")
            if lens == "unit.start":
                journal.event("unit", stage, unit, lens=lens, status="start", model=ENGINE_MODEL, **msg)
            else:
                journal.event("timing", stage, unit, lens=lens, **msg)

        def finish(i, res=None, exc=None):
            s = plan["shots"][i]
            set_ = {"segment_codec": "x264 crf 12 yuv444p veryfast mp4 (intermediate)", "resampler": s.get("_resampler"),
                    "conform": (s.get("_video") or {}).get("conform")}
            with journal.unit("motion", s["id"], size={"driver": "frames", "value": s["f1"] - s["f0"], "width": W, "height": H},
                              model=ENGINE_MODEL, settings=set_, start_event=False, unit_kind="shot",
                              resume=f"{resume_cmd} --from {s['id']}") as u:
                if exc is not None:
                    raise exc
                u.wall_s = res["wall_s"]
                u.extra.update(ms_mean=res["ms_mean"], mark=res["mark"], first_frame_whole=res["first_frame_whole"],
                               held_frames=res["held_frames"], held_by_shot=res.get("held_by_shot"),
                               segment=str(segs[i]))
            results[i] = res

        attempts = {i: 0 for i in todo}
        if todo and n == 1:
            sink = _Direct(on_msg)
            for i in todo:
                current["unit"] = ids[i]
                while True:
                    try:
                        res = render_segment(plan, i, str(segs[i]), sink)
                    except EncodeError as e:
                        if attempts[i] < 1:
                            attempts[i] += 1
                            journal.retry("motion", ids[i], attempts[i], str(e), fix="re-render the segment once")
                            continue
                        finish(i, exc=e)
                    except BaseException as e:
                        finish(i, exc=e)
                    break
                finish(i, res)
        elif todo:
            import multiprocessing as mp
            ctx = mp.get_context("spawn")
            with ctx.Manager() as manager:
                q = manager.Queue()

                def drain():
                    while True:
                        try:
                            on_msg(q.get_nowait())
                        except queue_mod.Empty:
                            return

                with ProcessPoolExecutor(max_workers=min(n, len(todo)), mp_context=ctx) as ex:
                    futs = {ex.submit(render_segment, plan, i, str(segs[i]), q): i for i in todo}
                    pending = set(futs)
                    try:
                        while pending:
                            done, pending = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
                            drain()
                            for fut in done:
                                i = futs[fut]
                                current["unit"] = ids[i]
                                try:
                                    res = fut.result()
                                except EncodeError as e:
                                    if attempts[i] < 1:
                                        attempts[i] += 1
                                        journal.retry("motion", ids[i], attempts[i], str(e), fix="re-render the segment once")
                                        nf = ex.submit(render_segment, plan, i, str(segs[i]), q)
                                        futs[nf] = i
                                        pending.add(nf)
                                        continue
                                    finish(i, exc=e)
                                except BaseException as e:
                                    finish(i, exc=e)
                                finish(i, res)
                        drain()
                    except BaseException:
                        ex.shutdown(wait=True, cancel_futures=True)
                        raise
        journal.stage("motion", "done")

        # Marks lint on what was rendered.
        current.update(stage="marks", unit=None)
        journal.stage("marks", "start")
        fails = {plan["shots"][i]["id"]: r["mark"]["fail_frames"] for i, r in results.items()
                 if r["mark"]["fail"] or r["mark"].get("shape", 0)}
        checked = sum(r["mark"]["ok"] + r["mark"]["fade"] + r["mark"].get("dip", 0) + r["mark"]["fail"] + r["mark"].get("shape", 0)
                      for r in results.values())
        journal.lint("mark-coverage", not fails and checked == plan["frames"], stage="marks", grammar="1.3, 4, A11", phase="post-render",
                     evidence={"frames": plan["frames"], "checked": checked, "ok": sum(r["mark"]["ok"] for r in results.values()),
                               "probe": "the class glyph's centre for the hue and its corner for the shape (A16 refined)",
                               "wrong_shape": sum(r["mark"].get("shape", 0) for r in results.values()),
                               "label_frames": sum(r["mark"].get("label", 0) for r in results.values()),
                               "glyph_only_frames": sum(r["mark"].get("glyph_only", 0) for r in results.values()),
                               "crossfade": sum(r["mark"]["fade"] for r in results.values()),
                               "dip_black": sum(r["mark"].get("dip", 0) for r in results.values()), "failed": fails})
        stills_bad = [plan["shots"][i]["id"] for i, r in results.items() if r.get("first_frame_whole") is False]
        for i in sorted(results):                # one lint per still, with its scores and verdict, as in pre-flight
            r = results[i]
            if r.get("first_frame_whole") is None:
                continue
            ev = dict(r.get("first_frame_detail") or {}, enters_by=plan["shots"][i]["transition_in"].get("type"))
            journal.lint("still-first-frame-whole-pixels", bool(r["first_frame_whole"]), stage="marks", unit=ids[i], grammar="A7",
                         phase="post-render", evidence=ev, status="inconclusive" if ev.get("verdict") == "inconclusive" else None)
        doc = sources_doc(plan, journal, {})
        voiced = {"narration": 0.0, "reading": 0.0, "archival": 0.0}
        for ln in placed["lines"]:
            voiced[ln["kind"]] = voiced.get(ln["kind"], 0.0) + ln["dur_s"]
        dur = plan["duration_s"]
        journal.event("lint", "marks", None, lens="marks", rule="marks-track", status="pass" if not fails else "fail",
                      severity="block", track=doc["marks"], share=doc["share"], generated_share=doc["share"]["AI-GENERATED"],
                      narration_share=round(voiced["narration"] / dur, 4), readings_share=round((voiced["reading"] + voiced["archival"]) / dur, 4),
                      violations=[{"shot": k, "frames": v} for k, v in fails.items()])
        if fails or checked != plan["frames"]:
            raise Refused(f"mark coverage failed on {fails or 'a frame count mismatch'}")
        held = held_totals(results, ids)
        held_bad = [sid for sid, k in held.items() if k / FPS > MAX_HOLD_S and not (
            plan["shots"][ids.index(sid)]["mark"] == "RECONSTRUCTED" and "re-timed" in (plan["shots"][ids.index(sid)].get("alterations") or []))]
        journal.lint("clip-hold-rendered", not held_bad, stage="marks", grammar="7.1", phase="post-render",
                     evidence={"held_frames": held, "max_s": MAX_HOLD_S, "over": held_bad})
        if held_bad:
            raise Refused(f"clips held their last frame over {MAX_HOLD_S:g} s: {', '.join(held_bad)} (GRAMMAR 7.1)")
        if stills_bad:
            raise Refused(f"A7: the first frame of {', '.join(stills_bad)} is not the whole photograph")
        journal.stage("marks", "done")

        # Encode last.
        current.update(stage="assembly", unit="encode")
        out.mkdir(parents=True, exist_ok=True)
        listing = work / "segments.txt"
        listing.write_text("".join(f"file '{segs[i].as_posix()}'\n" for i in range(len(plan["shots"]))), encoding="utf-8")
        master = out / (f"master.{check}.mp4" if check else "master.mp4")
        sources_path = out / (f"sources.{check}.json" if check else "sources.json")
        threads = MASTER_THREADS          # fixed, so the master's bytes never depend on --workers
        enc_settings = {"codec": "libx264", "preset": encode_preset, "crf": MASTER_CRF, "pix_fmt": "yuv420p", "fps": FPS,
                        "color": "bt709", "audio": "aac 192k 48 kHz", "threads": threads}
        with journal.unit("assembly", "encode", size={"driver": "seconds", "value": round(dur, 3)},
                          model={"name": "ffmpeg", "version": ffmpeg_version()}, settings=enc_settings,
                          resume=resume_cmd) as u:
            cmd = [ffmpeg(), "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-i", str(work / "mix-norm.wav"),
                   "-map", "0:v:0", "-map", "1:a:0",
                   "-vf", "scale=in_color_matrix=bt709:out_color_matrix=bt709:in_range=tv:out_range=tv,format=yuv420p,"
                          "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv",
                   "-c:v", "libx264", "-preset", encode_preset, "-crf", str(MASTER_CRF), "-r", str(FPS), "-threads", str(threads),
                   "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                   "-c:a", "aac", "-b:a", "192k", "-ar", str(AUDIO_RATE), "-t", f"{dur:.6f}", "-movflags", "+faststart", str(master)]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode:
                raise EncodeError(f"master encode failed: {r.stderr[-800:]}")
            pr = probe_video(master)
            pr["frames"] = count_frames(master)
            u.extra.update(master={"width": pr["width"], "height": pr["height"], "fps": pr["fps"], "duration_s": pr["duration_s"],
                                   "frames": pr["frames"]})
        ok_fmt = pr["width"] == W and pr["height"] == H and abs(pr["fps"] - FPS) < 0.01 and pr["frames"] == plan["frames"]
        journal.lint("master-format", ok_fmt, stage="assembly", grammar="7.5", phase="post-render",
                     evidence={"width": pr["width"], "height": pr["height"], "fps": pr["fps"], "frames": pr["frames"],
                               "expected_frames": plan["frames"], "duration_s": pr["duration_s"]})
        if not ok_fmt:
            raise Refused(f"the master is {pr['width']}x{pr['height']} at {pr['fps']} fps with {pr['frames']} frames; "
                          f"expected {W}x{H} at 24 with {plan['frames']}")
        # One write: a check render writes its own partial sources file and never the full one (T1d);
        # a full render also records the master's sha256, which ties sources.json to its film (T7).
        extra = {"loudness": loud, "master": master.name, "master_sha256": sha256_file(master)}
        if check:
            extra.update(partial=True, until_s=until_s)
        doc = sources_doc(plan, journal, extra)
        sources_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
        for i in range(len(plan["shots"])):
            journal.artifact("motion", segs[i], unit=ids[i], role="check-segment" if check else "segment")
        journal.artifact("assembly", master, role="check-master" if check else "master")
        journal.artifact("assembly", sources_path, role="check-sources" if check else "sources")
        journal.stage("assembly", "done")
        wall = time.perf_counter() - run_t0
        journal.timing("run", "total", wall, size={"driver": "seconds", "value": round(dur, 3), "frames": plan["frames"]},
                       model=ENGINE_MODEL, settings=dict(settings, workers=n))
        summary = {"run": journal.run, "journal": str(journal.path), "master": str(master), "sources": str(sources_path),
                   "frames": plan["frames"], "duration_s": dur, "wall_s": round(wall, 2), "rendered": [ids[i] for i in todo],
                   "cached": [ids[i] for i in cached], "workers": n, "partial": bool(check), "until_s": until_s}
        journal.event("stage", "run", None, lens="run.end", status="done", outcome="ok", **summary)
        return summary
    except BaseException as exc:
        unit = current.get("unit")
        resume = f"{resume_cmd} --from {unit}" if current["stage"] == "motion" and unit else resume_cmd
        if not getattr(exc, "_journaled", False):
            journal.error(current["stage"], unit, exc, resume=resume,
                          fix="fix the lint or pre-flight finding above" if isinstance(exc, Refused) else None)
        journal.event("stage", "run", None, lens="run.end", status="fail", outcome="refused" if isinstance(exc, Refused) else "failed",
                      stage_failed=current["stage"], message=f"{type(exc).__name__}: {exc}", resume={"command": resume})
        raise


def sources_only(film: Path | str, out: Path | str | None = None, *, journal: Journal | None = None) -> dict:
    """--sources-only: re-plan the film and rewrite ``<out>/sources.json`` beside an existing master, without
    rendering a frame. It uses the render's own fitted screenplay when there is one, takes the frame size
    from the master, refuses when the master's frame count differs from the plan's (the master is then
    stale: render again), keeps the previous file's loudness, and records the master's sha256."""
    film = Path(film).resolve()
    out = Path(out).resolve() if out else film / "out"
    master = out / "master.mp4"
    if not master.exists():
        raise Refused(f"no master.mp4 in {out}: render the film first")
    fitted = out / "screenplay.fitted.json"
    play = json.loads((fitted if fitted.exists() else film / "screenplay.json").read_text(encoding="utf-8"))
    journal = journal or Journal(film=film.name, out_dir=out)
    pr = probe_video(master)
    with journal.unit("scout", "sources-only", size={"driver": "items", "value": 0}) as u:
        plan = build_plan(film, W=pr["width"], H=pr["height"], burn_subtitles=False, journal=journal, play=play)
        u.size = {"driver": "items", "value": len(plan["shots"])}
    frames = count_frames(master)
    journal.lint("master-matches-plan", frames == plan["frames"], stage="assembly", phase="sources-only",
                 evidence={"master_frames": frames, "plan_frames": plan["frames"], "screenplay": "fitted" if fitted.exists() else "screenplay.json"})
    if frames != plan["frames"]:
        raise Refused(f"the master has {frames} frames and the plan {plan['frames']}: the master is stale, render again")
    extra: dict = {}
    path = out / "sources.json"
    if path.exists():
        prev = json.loads(path.read_text(encoding="utf-8"))
        extra.update({k: prev[k] for k in ("loudness",) if k in prev})
    extra.update(master="master.mp4", master_sha256=sha256_file(master))
    doc = sources_doc(plan, journal, extra)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    journal.artifact("assembly", path, role="sources")
    return {"sources": str(path), "frames": plan["frames"], "duration_s": plan["duration_s"], "master_sha256": extra["master_sha256"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m studio.engine.render", description=__doc__.split("\n\n")[0])
    ap.add_argument("film", type=Path, help="film folder with screenplay.json and its ledgers")
    ap.add_argument("--out", type=Path, default=None, help="output folder (default <film>/out)")
    ap.add_argument("--res", type=int, choices=sorted(RESOLUTIONS), default=1080)
    ap.add_argument("--from", dest="from_shot", default=None, help="re-render from this shot; earlier shots come from the cache")
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help=f"CPU worker processes (default {DEFAULT_WORKERS}, max {MAX_WORKERS})")
    ap.add_argument("--burn-subtitles", action="store_true", help="burn the English subtitles into the picture (off by default)")
    ap.add_argument("--draft", action="store_true", help="place silence for missing voice WAVs and accept dynamic loudness, a compressing limiter, a bad take or an "
                         "inconsistent narrator line instead of refusing (journaled)")
    ap.add_argument("--fit-voices", action="store_true",
                    help="move overlapping voice lines later (0.8 s apart) and lengthen their shots (journaled)")
    ap.add_argument("--until", dest="until_s", type=float, default=None,
                    help="a check render: only the shots that start before this many seconds (journaled)")
    ap.add_argument("--audio-only", action="store_true",
                    help="run the pre-flight and the sound (mix, levelling, loudness) only: no frames, no master")
    ap.add_argument("--sources-only", action="store_true",
                    help="rewrite sources.json beside an existing master.mp4 from the screenplay, without rendering frames")
    a = ap.parse_args(argv)
    if a.sources_only:
        try:
            r = sources_only(a.film, a.out)
        except Refused as e:
            print(f"render: refused: {e}", file=sys.stderr)
            return 2
        print(f"render: sources only, {r['frames']} frames -> {r['sources']} (master sha256 {r['master_sha256'][:16]})")
        return 0
    try:
        s = render(a.film, a.out, height=a.res, from_shot=a.from_shot, workers=a.workers, burn_subtitles=a.burn_subtitles,
                   draft=a.draft, fit_voices_opt=a.fit_voices, audio_only=a.audio_only, until_s=a.until_s)
    except Refused as e:
        print(f"render: refused: {e}", file=sys.stderr)
        return 2
    if a.audio_only:
        lo = s["loudness"]
        print(f"render: audio only, {s['duration_s']:.2f} s -> {s['mix']} "
              f"({lo.get('output_i')} LUFS, {lo.get('output_tp')} dBTP, LRA {lo.get('output_lra')})")
        print(f"render: journal {s['journal']}")
        return 0
    print(f"render: {s['frames']} frames, {s['duration_s']:.2f} s of film in {s['wall_s']} s -> {s['master']}")
    print(f"render: journal {s['journal']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
