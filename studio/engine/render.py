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
- stills that fill 16:9 on every frame (A41, TOUR): the camera tours the
  picture along a path of stops (``camera``), a preset's path (HOLD, PUSH,
  PULL, DRIFT, TILT, DETAIL, FILL) or the default tour, on the rostrum curve,
  never below the fill and never past the film's ``fill_max_upscale``; a
  still too small to fill under it states ``fill_exception`` and is held whole
  (A7);
- FILL (A34): an archive still or clip narrower than 16:9 opens whole for
  2.5 s, then moves over up to 6 s to the largest 16:9 window inside it about
  its ``focus`` and holds there (the default for such a picture over 6 s that
  declares no preset), never magnifying the source past the film's
  ``fill_max_upscale``;
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

from studio.engine import aswas as AW
from studio.engine import clips as CL
from studio.engine import maps as MP
from studio.engine import motion as M
from studio.engine import overlays as OV
from studio.engine import policy as POL
from studio.engine import score as SC
from studio.engine import titles as TS
from studio.engine import tour as T
from studio.engine import voicing as VO
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
# A15 refined (E14): when the pass-1 mix's master limiter would do more than catch peaks (limiter-peak-only), pass 2
# peak-controls every synthetic line to the master limiter's own ceiling (TARGET_TP - LIMIT_MARGIN_DB) minus the measured
# mix-to-master lift minus this safety margin, clamped between the floor (a near-silent film cannot crush its voices) and
# VOICE_TP (a film that passes never changes). Pass 2's own lift re-estimates the ceiling at most once more (pass 3).
VOICE_CEILING_SAFETY_DB = 0.3
VOICE_TP_FLOOR = -7.0
VOICE_CEILING_PASSES = 3            # pass 1 at VOICE_TP, then at most two re-peak-controls; then the master's lint judges
VOICE_CEILING_TOL_DB = 0.05         # a re-estimate this close to the ceiling used is not worth another pass
LEVEL_MIN_S = 0.4                  # loudnorm's gating block: a shorter line is measured looped to this length
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
MUSIC_LUFS = -26.0                  # a featured music cue (the motif, a palette recording), 6 dB under the dialogue; its
                                    # gain_db is an offset from it. A29 (R1): an underscore cue (bed, transition, sting,
                                    # outro) is levelled to the score standard's bed target instead, -32 LUFS by default
                                    # (studio/engine/score.py holds the standard's numbers, settable per film in bounds)
DUCK_DB = 9.0                       # GRAMMAR 8.5: music under voice
DUCK_SMOOTH_S = 0.250               # GRAMMAR 8.5: 250 ms smoothing, a centred ramp (it starts 125 ms before the voice)
DUCK_BRIDGE_S = 1.2                 # voice gaps shorter than this stay ducked (between words and between lines 0.8 s apart),
                                    # so a long bed never pumps; across a 1.5 s scene breath (A10) it comes back up.
                                    # A29: the film's score_standard duck_hold_s (1.2 to 3 s); every pause inside a line holds
assert (MUSIC_LUFS, DUCK_DB, DIALOGUE_LUFS, DUCK_BRIDGE_S) == (SC.FEATURE_LUFS, SC.DUCK_DB, SC.DIALOGUE_LUFS, SC.STANDARD["duck_hold_s"])
DUCK_VOICE_THRESHOLD = 1e-3         # a voice sample over -60 dBFS counts as voice for ducking
SILENCE_DBFS = -120.0               # A19: a mix sample at or under this is true digital silence
SILENCE_WARN_S = 4.0                # digital-silence: a run longer than this outside an intended silence is a warning
VOICELESS_FLOOR = 0.10              # GRAMMAR 6.1, A18: at least 10% of the runtime carries no voice
READINGS_FLOOR = 0.20               # GRAMMAR 6.1 as amended (founder, 2026-10-10): readings (read-by and archival
                                    # testimony) carry at least 20% of the runtime (was 30%)
# A25 (E9): these floors are the defaults of a film's `settings` (studio/engine/policy.py), Partition's values
assert (VOICELESS_FLOOR, READINGS_FLOOR) == (POL.DEFAULT_SETTINGS["voiceless_floor"], POL.DEFAULT_SETTINGS["readings_floor"])
# A25 (E9): the readings share counts first-person words, read by a computer voice or heard in their own recording
READINGS_SHARE_COUNTS = ("reading", "archival")
# A26 (E11): an archival line that plays a span of a source's own soundtrack
ARCHIVAL_DIALOGUE_LUFS = -20.0      # one static gain brings the span to the dialogue level (8.5); no compression, no limiter
ARCHIVAL_FADE_S = 0.020             # raised-cosine fades at its in and out points, so a cut never clicks
LONG_REEL_BYTES = 512 * 1024 * 1024  # a source over this is trimmed to a cached span before conform, never read whole
SPAN_PAD_S = 1.0                    # a cached video span keeps this much of the reel either side of the shot
SPAN_VERSION = 1                    # bump when the span extraction changes, so old cached spans are not reused
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
    TS.KIND: {"DRAWN"},             # A40: the series titles, drawn by the studio; their own marks are burned in
}
ALTERATIONS = {"colourised", "upscaled", "stabilised", "interpolated", "re-timed", "inpainted", "motion added", "tinted",
               "audio synthesised", "colour cast removed"}   # the last by GRAMMAR A14
LICENCE_OK = re.compile(r"^(public domain|cc0( 1\.0)?|cc[- ]?by([- ][1-4]\.0)?)$", re.I)
# CC BY-SA (founder ruling 2026-10-16, "Real World"): never on the house allowlist; allowed only in a film whose
# screenplay declares ``share_alike: {decision: "<its docs/DECISIONS.md entry>"}``, so the licence is scoped per film,
# and the film's sources page carries the ShareAlike attribution. Every such asset is journaled as a decision.
LICENCE_SHARE_ALIKE = re.compile(r"^cc[- ]?by[- ]?sa([- ][1-4]\.0)?$", re.I)


def share_alike_declared(play: dict | None) -> tuple[bool, list[str]]:
    """Whether the film allows CC BY-SA (``share_alike`` with a ``decision``
    naming its DECISIONS entry), and what is wrong with the declaration."""
    d = (play or {}).get("share_alike")
    if d is None:
        return False, []
    if not isinstance(d, dict):
        return False, ["share_alike must be an object: {decision: \"docs/DECISIONS.md <date>: <title>\"}"]
    dec = d.get("decision")
    if not (isinstance(dec, str) and "DECISIONS" in dec and dec.strip()):
        return False, ["share_alike.decision must name the film's docs/DECISIONS.md entry"]
    return True, []


def licence_allowed(lic: str, play: dict | None = None) -> tuple[bool, bool]:
    """(allowed, share_alike): the house allowlist, or CC BY-SA in a film that declares it (share_alike_declared)."""
    lic = str(lic or "").strip()
    if LICENCE_OK.match(lic):
        return True, False
    if LICENCE_SHARE_ALIKE.match(lic):
        return share_alike_declared(play)[0], True
    return False, False
PRESETS = {                         # GRAMMAR 7.2, zoom relative to the largest 16:9 window
    "HOLD": ({"z": 1.0}, {"z": 1.0}),
    "PUSH": ({"z": 1.0}, {"z": 1.12}),
    "PULL": ({"z": 1.12}, {"z": 1.0}),
    "DRIFT": ({"z": 1.15, "x": 1 / 3}, {"z": 1.15, "x": 2 / 3}),
    "TILT": ({"z": 1.2, "y": 0.0}, {"z": 1.2, "y": 1.0}),
    "DETAIL": ({"z": 1.3}, {"z": 1.3}),
}
PRESET_ZMAX = {"HOLD": 1.0, "PUSH": 1.12, "PULL": 1.12, "DRIFT": 1.15, "TILT": 1.2, "DETAIL": 1.3, "FILL": 1.0}
# A34 (R12): FILL ends on the largest 16:9 window inside the picture, which is 7.2's z = 1 (so its relative zoom is
# at most 1.0); its timing is motion.FILL. It never magnifies the source more than FILL_MAX_UPSCALE output pixels per
# source pixel (the founder's figure; a film may set fill_max_upscale, 1.0 to 3.0): at 1.6 a 4:3 source of 1200 px
# or more across fills 1080p; a 640x480 reel, already 2.25x in its plain fit (A5), stays whole and is journaled.
FILL = "FILL"
TOUR = "TOUR"                       # A41: a still's camera is a path of stops (studio/engine/tour.py)
COVERABLE = ("HOLD", "PUSH", "PULL", "DRIFT", "TILT", "DETAIL", "FILL", "DEFAULT")   # A41: not authored paths
FILL_MAX_UPSCALE = 1.6
FILL_ASPECT_TOL = 0.01              # narrower than 16:9 by more than 1% (a 1.77 transfer is 16:9)
FILL_SAFE = (0.04, 0.05, 0.96, 0.75)   # the focus at the end framing: inside the marks' insets, above the lower thirds
VIDEO_PRESETS = (FILL, "HOLD")      # a clip either plays as it is (HOLD, or no preset) or FILLs (A34)
assert FILL_MAX_UPSCALE == POL.DEFAULT_SETTINGS["fill_max_upscale"]
# A41 (founder, 2026-10-17: "fill the frame, soft is acceptable up to 3x"): a still's softness cap on the 1080p
# master when the film states no fill_max_upscale; a clip's FILL keeps FILL_MAX_UPSCALE
STILL_MAX_UPSCALE = M.TOUR["still_max_upscale"]
assert STILL_MAX_UPSCALE <= POL.SETTING_BOUNDS["fill_max_upscale"][1]
# 7.2, max 1.3. FIND (A32, a georeferenced sheet between extents) is not here: its limit is the
# scan's own resolution, per shot and per delivery resolution (OV.scan_zmax, A32 refined, CoS 2026-10-11).
SILENT_RE = re.compile(r"^The record holds no .+\.$")
FLAG_RE = re.compile(r"^Account of .+, \d{4}$")
CARD_TEXT_KINDS = {"chapter_card", "title_card", "silent_record"}
CHAPTER_RE = re.compile(r"^(\d+)\s+(.+)$")
LT_SUFFIXES = ("  ·  read by a computer voice", "  ·  original recording")
EM_DASH = "—"

_HERE = Path(__file__).resolve().parent
ENGINE_HASH = hashlib.sha256(b"".join((_HERE / f).read_bytes() for f in ("render.py", "motion.py", "score.py", "overlays.py", "georef.py", "clips.py", "voicing.py", "titles.py", "tour.py"))).hexdigest()[:12]
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
            if s.get("kind") not in ("archive_video", "archive_still", "drawn", TS.KIND) or not s.get("asset"):
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
            elif s["kind"] in ("archive_video", TS.KIND):
                why = decodes_a_frame(path)
            else:
                why = opens_as_image(path)
            if why:
                problems.append({"unit": s["id"], "asset": s["asset"], "file": path, "why": why})
        for ln in part.get("lines", []):
            if ln.get("kind") not in VOICE_KINDS:
                continue
            if archival_span(ln):                         # A26: the line plays its clip's own soundtrack
                checked += 1
                item = assets.get(ln["clip"])
                path = (item or {}).get("_path")
                why = ("clip not in any ledger" if item is None else "ledger item names no file" if not path else
                       "missing" if not Path(path).exists() else None)
                if why:
                    problems.append({"unit": ln["id"], "asset": ln["clip"], "file": path, "why": why})
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
            it["_ledger_file"] = str(path)
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
    if shot.get("marks"):                     # A32: an archive sheet with marks drawn over it says so
        return M.mark_label(cls, OV.label_year(item), ", ".join(x for x in (extra, OV.MARKS_DRAWN) if x))
    return M.mark_label(cls, year_of(item or {}), extra)


def mark_year(shot: dict) -> str | None:
    """A31: the year the label states, which with the class decides when it
    surfaces: an ARCHIVE or RECONSTRUCTED shot's item year, else none."""
    if shot["mark"] not in ("ARCHIVE", "RECONSTRUCTED"):
        return None
    y = year_of(shot.get("_item") or {})
    return str(y) if y else None


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


def ai_label_lint(lint, shots) -> None:
    """ai-label (A31): an AI-GENERATED shot's label is never empty, since it
    is a truth label, up for the whole shot (A16 refined). Blocking."""
    for s in shots:
        if s["mark"] == "AI-GENERATED":
            lint("ai-label", bool((s.get("label") or "").strip()), unit=s["id"], grammar="A16 refined, A31",
                 evidence={"label": s.get("label"), "fix": "an AI-GENERATED shot carries its label (mark_label)"})


def card_text_check(shot: dict, W: int, H: int, fonts: M.Fonts | None = None, key_classes=None) -> dict:
    """E15: what a card shot draws of its ``text[]``, from the same layout the
    drawer uses. Returns ``fits`` (False with ``why`` when the text cannot be
    laid out in the card's safe area at a readable size), ``missing`` (the
    elements not drawn word for word: index, intended, drawn) and, for a
    statement card, its ``scale`` and ``lines``. Never OCR: the layout
    records are what is drawn."""
    fonts = fonts or M.Fonts()
    L = M.Layout(W, H)
    texts = [str(x) for x in (shot.get("text") or [])]
    ck = shot.get("_card") or card_kind(shot)
    out = {"card": ck, "fits": True, "why": None, "missing": []}

    def norm(x):
        return " ".join(str(x).split())

    def drawn_as(drawn: list):
        return [{"index": i, "intended": norm(tx), "drawn": drawn[i] if i < len(drawn) else None}
                for i, tx in enumerate(texts) if (drawn[i] if i < len(drawn) else None) != norm(tx)]

    if ck in ("black", "credits"):          # neither draws the shot's text (the credits draw the plan's blocks)
        out["missing"] = drawn_as([])
        return out
    if ck == "mark_key":                    # A31: the key draws the class table; a text[] would be words not drawn
        try:
            M.mark_key_layout(L, fonts, key_classes)
        except M.TextOverflow as e:
            out.update(fits=False, why=str(e))
        out["missing"] = drawn_as([])
        return out
    if ck in ("title", "chapter"):
        try:
            if ck == "title":
                lay = M.title_card_layout(L, texts[0] if texts else "", fonts)
                recs = lay["lines"][:1] + lay["lines"][1:] * (len(texts) > 1)     # the wordmark stands for text[1]
            else:
                # drawn as Pictures.card draws it: the number and title from text[0], the dates from text[1]
                m = CHAPTER_RE.match(texts[0]) if texts else None
                lay = M.chapter_card_layout(L, int(m.group(1)) if m else 0, m.group(2) if m else (texts[0] if texts else ""),
                                            texts[1] if len(texts) > 1 else "", fonts)
                recs = lay["lines"][:1] + lay["lines"][1:] * (len(texts) > 1)
        except M.TextOverflow as e:
            out.update(fits=False, why=str(e), missing=drawn_as([]))
            return out
        out["missing"] = drawn_as([norm(r["text"]) for r in recs])
        return out
    try:
        lay = M.card_layout(L, texts, fonts, what=f"card {shot.get('id')}")
    except M.TextOverflow as e:
        out.update(fits=False, why=str(e), missing=drawn_as([]))
        return out
    out["missing"] = M.card_text_problems(texts, lay)
    out["scale"] = lay["scale"]
    out["lines"] = [len(e["lines"]) for e in lay["elements"]]
    return out


def card_lints(lint, shots: list[dict], W: int, H: int, *, rule_fits: str = "card-fits", rule_drawn: str = "card-drawn",
               stage: str = "scout", only=None) -> None:
    """E15: every card's text fits its safe area at a readable size, and every
    element of its ``text[]`` is drawn word for word (from the layout records).
    At plan time a shortfall card is checked with its placeholders as written,
    which are longer than any fill; after the fill it is checked again."""
    fonts = M.Fonts()
    used = M.key_classes(shots)                   # A31: the mark key shows the classes the film's shots use
    for s in shots:
        if s.get("kind") not in ("card", "black") or (only is not None and s["id"] not in only):
            continue
        c = card_text_check(s, W, H, fonts, used)
        lint(rule_fits, c["fits"], unit=s["id"], stage=stage, grammar="9, BRAND-KIT 6 and 11c",
             evidence={"card": c["card"], "why": c["why"], "scale": c.get("scale"), "lines": c.get("lines"),
                       "fix": None if c["fits"] else "shorten the text or split the card; the engine never cuts text"})
        lint(rule_drawn, not c["missing"], unit=s["id"], stage=stage, grammar="9, BRAND-KIT 11c",
             evidence={"card": c["card"], "missing": c["missing"],
                       "fix": None if not c["missing"] else "every element of text[] must be drawn; this card kind draws "
                                                            "only what its form allows (GRAMMAR 9)"})


def whole_camera(shot: dict, img_size, W: int, H: int, *, preset: str = "HOLD") -> dict:
    """A7's camera for a still under ``fill_exception`` (A41): the whole
    photograph at native aspect on the field on its first frame, then a gentle
    push inside its own shape (pillarboxed) at ``TOUR['creep_scale_per_s']``,
    never past ``TOUR['whole_creep_max']`` of the whole, so it is never frozen
    (founder, 2026-10-17)."""
    iw, ih = img_size
    s = min(W / iw, H / ih)
    dur = float(shot["_dur"])
    z_end = min(M.TOUR["whole_creep_max"], 1.0 + M.TOUR["creep_scale_per_s"] * dur)
    path = [{"z": 1.0, "x": 0.5, "y": 0.5}] + ([{"z": z_end, "x": 0.5, "y": 0.5}] if z_end > 1.0 + 1e-9 else [])
    return {"path": path, "clamp": "native", "fill_ok": False, "preset": preset, "open_s": 0.0, "move_s": dur,
            "z_max": z_end, "fit_scale": s, "z_rel_max": 1.0, "creep_z": z_end, "opens_whole": True}


def still_camera(shot: dict, img_size: tuple[int, int], W: int, H: int, *, words=None, cover: bool = False,
                 cap: float | None = None) -> dict:
    """The still's camera (A41, TOUR): a path of stops in picture coordinates
    (studio/engine/tour.py) that fills 16:9 on every frame, drawn by
    ``overlays.framing_at``. The path is the shot's ``camera`` (a list of
    stops, ``"tour"`` or ``{"tour": [names]}``: the ledger's regions visited
    as the narration names them), else its preset as a macro, else the
    default tour. ``cover`` swaps a preset or the default for a pass that
    shows the whole picture (a FILL then settles on its focus, a DETAIL on its
    region): the plan asks for it when the path would leave part of the
    picture, or a person, unseen. A still the
    softness cap cannot fill states ``fill_exception`` and is held whole (A7).
    FIND (A32) keeps its own camera, held at the fill. ``words`` are the
    narration's words over the shot (tour.shot_words), for ``at`` anchors."""
    iw, ih = img_size
    s = min(W / iw, H / ih)
    fw, fh = iw * s, ih * s
    cap = float(cap if cap is not None else shot.get("_fill_max_upscale") or STILL_MAX_UPSCALE)
    aspect = W / H
    # the softness cap is judged on the 1080p master, so a 720p delivery frames exactly as the master does
    zcap = T.z_cap(img_size, *RESOLUTIONS[1080], cap)
    item = shot.get("_item") or {}
    exc = shot.get("fill_exception")
    preset = shot_preset(shot, iw / ih, still=True)
    if exc is not None:
        if preset == OV.FIND:
            return dict(OV.find_camera(shot, img_size, W, H, open_s=OPEN_S), opens_whole=True, fill_exception=exc)
        return dict(whole_camera(shot, img_size, W, H), fill_exception=exc, declared_preset=preset)
    if preset == OV.FIND:                     # A32 under A41: the sheet's own moves, at the fill on every frame
        cam = OV.find_camera(dict(shot, fill_ok=True), img_size, W, H, open_s=OPEN_S)
        zf = max(W / fw, H / fh)
        pts = [dict(p, z=max(p["z"], zf)) for p in cam["path"]]
        pts[0] = {"z": max(pts[0]["z"], zf), "x": 0.5, "y": 0.5}
        path = [pts[0]]
        for p in pts[1:]:
            if any(abs(p[k] - path[-1][k]) > 1e-9 for k in ("z", "x", "y")):
                path.append(p)
        return dict(cam, path=path, clamp="image", fill_ok=True, z_max=max(p["z"] for p in path), opens_whole=False,
                    a41="FIND held at the fill: its whole-sheet opening is the fill (A41)")
    dur = float(shot["_dur"])
    t0 = float(shot.get("start_s") or 0.0)
    # A43 (founder ruling 2): human wins over auto for the same name; a machine box under the confidence floor is
    # ignored for framing (the person it marks counts as unlocated, so the still degrades toward the whole)
    eff = T.effective_regions(item)
    roi = eff["roi"]
    persons = T.person_regions(item)
    roi_by_name = {p["name"]: dict(p["entry"], kind="person") for p in persons
                   if p["src"] == "people" and p["name"] is not None}
    roi_by_name.update({r.get("name"): r for r in roi})
    zmax = max(1.0, zcap)
    if shot.get("face"):
        zmax = min(zmax, 1.3)                 # 7.2: a face is never pushed past z 1.3, creep included
    problems: list[str] = []
    camera = shot.get("camera")
    macro = None
    covering = False
    if camera is not None and shot.get("preset") is not None:
        problems.append("a shot takes a camera path or a preset, not both")
    if camera is not None:
        if camera == "tour" or (isinstance(camera, dict) and "tour" in camera):
            only = camera.get("tour") if isinstance(camera, dict) else None
            stops = T.tour_stops(roi, words or [], t0, dur, img_size, aspect, zmax, only=only)
            macro = "TOUR"
            if stops is None:
                stops, macro = T.default_stops(img_size, aspect, dur, str(shot.get("direction", "")).lower(),
                                               zmax=zmax), "DEFAULT"
        else:
            stops, probs = T.parse_path(camera, dur, words or [], t0, roi_by_name, img_size, aspect, zmax)
            problems += probs
            macro = "PATH"
            if not stops:
                stops = T.default_stops(img_size, aspect, dur, zmax=zmax)
    elif preset in T.MACROS:
        macro = preset
        stops = T.macro_stops(preset, shot, dur)
        clamped = [st for st in stops if st["z"] > zmax + 1e-9]
        for st in clamped:                    # a preset stops at the softness cap, as FILL did (A34): never softer
            st["z"], st["capped"] = zmax, True
    elif preset == TOUR:
        macro = "DEFAULT"
        stops = T.default_stops(img_size, aspect, dur, str(shot.get("direction", "")).lower(), zmax=zmax)
    else:
        raise Refused(f"shot {shot['id']}: unknown preset {preset!r} (GRAMMAR 7.2, A41)")
    asked = stops                             # still-zoom-limit judges the preset as written, before any cover
    if cover and (macro in COVERABLE or macro == "TOUR"):
        region = shot.get("region") or {}
        focus = (shot.get("focus") if macro == "FILL" else
                 [float(region.get("x", 0.5)), float(region.get("y", 0.5))] if macro == "DETAIL" else None)
        stops = T.covering_stops(img_size, aspect, dur, focus, zmax=zmax)
        covering = True
    # A43 face-cap-live: a stop that frames a face or a person never goes past z 1.3, creep included
    no_zoom = shot.get("no_zoom") is True
    stops = T.cap_faces(stops, persons, img_size, aspect)
    # A43 (founder ruling 2): the engine's own output is never refused. A stop it placed on a person that may not
    # bind the name it is timed to is re-framed to the group or the whole; a move it made across a face past the
    # cap is pulled back to it. A path a person wrote is left as written, for the lints.
    stops, reframed = T.degrade_bindings(stops, dur, item, roi_by_name, persons, img_size, aspect, zmax,
                                         no_zoom=no_zoom)
    stops = T.cap_faces(stops, persons, img_size, aspect)
    stops, pulled = T.enforce_face_cap(stops, persons, dur, img_size, aspect, zmax, no_zoom=no_zoom)
    if shot.get("match") == "prev" and stops:
        stops[0] = dict(stops[0], match="prev")   # the schema: a shot's match is its first stop's (#9 draws it)
    tl = T.build(stops, dur, img_size, aspect, zmax, no_zoom=no_zoom)
    frame_path = [T.to_frame(st, img_size, W, H) for st in tl["stops"]]
    zf = max(W / fw, H / fh)
    return {"path": frame_path, "clamp": "image", "fill_ok": True, "preset": TOUR, "macro": macro, "open_s": 0.0,
            "z_max": zf * tl["z_max"], "fit_scale": s, "z_rel_max": max(max(1.0, float(st["z"])) for st in asked),
            "tour": tl, "W": W, "H": H, "opens_whole": False, "problems": problems, "zcap": zcap, "cap": cap,
            "covering": covering, "capped": any(st.get("capped") for st in stops),
            "cine": {"persons": persons, "regions": roi_by_name, "ignored": eff["ignored"], "reframed": reframed,
                     "pulled": pulled}}


def engine_cover(s: dict, cam: dict, size, W: int, H: int, words, journal: Journal | None) -> dict:
    """A41 and A43: a path the engine made (a preset, the default, or the
    ``tour`` resolver's visits, re-framed or not) can never fail tour-people.
    Its windows are checked against every person in the picture (A7 over the
    path); one that misses anyone becomes a covering pass of the whole
    picture, journaled. A preset or the default that leaves part of the
    picture unseen is covered too, unless the ledger names what the picture
    is about (roi, must_show): then the path is the author's, and a reviewer
    item. A path a person wrote (``camera`` stops) is never changed here."""
    if cam.get("preset") != TOUR or not (cam.get("macro") in COVERABLE or cam.get("macro") == "TOUR"):
        return cam
    item = s["_item"]
    people = T.people_of(item, kind=s["kind"])
    wins = [w for _, w in still_windows(cam, s, size, W, H)]
    pc = T.people_check(wins, people, size)
    authored = bool(item.get("roi") or item.get("must_show")) or cam["macro"] == "TOUR"
    why = ("a person would go unseen" if not pc["ok"] else
           None if pc["whole_shown"] or authored else
           f"it shows {100 * T.coverage(wins, size):.0f}% of the picture")
    if not why:
        return cam
    macro = cam["macro"]
    cam = still_camera(s, size, W, H, words=words, cover=True)
    if journal is not None:
        journal.decision("motion", f"{s['id']}: {macro} made a covering pass of the whole picture",
                         f"A41 and A7: as written {why}; full visibility comes from touring the whole surface",
                         unit=s["id"], evidence={"people": people, "kind": s["kind"], "missed": pc["missed"]})
    return cam


def narrower_than_frame(aspect: float, W: int = 1920, H: int = 1080) -> bool:
    """A34: a picture narrower than 16:9 (4:3, square, portrait) by more than rounding."""
    return aspect < (W / H) * (1.0 - FILL_ASPECT_TOL)


def burned_names_in_shot(shot: dict, item: dict | None) -> list:
    """A26 refined: the speakers' names the source burns into the picture
    (``speakers_on_screen`` on the clip's ledger item) inside this shot's
    clip span. A crop could cut them off, so A34 never fills such a shot."""
    out = []
    a, b = float(shot.get("in_s", 0.0) or 0.0), float(shot.get("out_s", 0.0) or 0.0)
    for e in (item or {}).get("speakers_on_screen") or []:
        if isinstance(e, dict) and float(e.get("in_s", 0)) < b and float(e.get("out_s", 0)) > a:
            out.append(e)
    return out


def shot_preset(shot: dict, aspect: float, *, still: bool) -> str:
    """The camera preset a picture shot uses. A declared ``preset`` wins. A34:
    with none declared, an archive picture narrower than 16:9 that runs longer
    than FILL's default_min_s FILLs (unless it says ``fill_ok: false``, or its
    source burns names into the frame); else a still HOLDs and a clip plays
    as it is (``None``). A41: a still with no preset tours (TOUR), and so does
    any shot with a ``camera`` path. The choice is recorded on the shot
    (``_preset_from``)."""
    declared = shot.get("preset")
    if declared is not None:
        shot["_preset_from"] = "declared"
        return str(declared).upper()
    if still or shot.get("camera") is not None:
        # A41: a still with no preset tours (its ``camera`` path, or the default tour); on a clip a path is a TOUR
        # the clip lints refuse (a path on video is a later ticket)
        shot["_preset_from"] = "camera path" if shot.get("camera") is not None else "default tour (A41)"
        return TOUR
    dur = float(shot.get("_dur") or 0.0)
    why = None
    if not shot.get("kind", "").startswith("archive_"):
        why = "not an archive picture"
    elif not narrower_than_frame(aspect):
        why = "not narrower than 16:9"
    elif dur <= M.FILL["default_min_s"]:
        why = f"{dur:g} s, not over {M.FILL['default_min_s']:g} s"
    elif shot.get("fill_ok") is False:
        why = "the shot says fill_ok: false"
    elif burned_names_in_shot(shot, shot.get("_item")):
        why = "the source burns speakers' names into this span (A26 refined); a crop could cut them off"
    shot["_preset_from"] = "default" if why is None else f"no default fill: {why}"
    if why is None:
        return FILL
    return "HOLD" if still else None


def fill_camera(shot: dict, size: tuple[float, float], W: int, H: int, *, max_upscale: float | None = None) -> dict:
    """A34 (FILL): the camera that opens on the whole picture (A7) and then
    moves, on the rostrum curve, to the largest 16:9 window inside it about
    ``focus`` ([x, y], 0 to 1 in the picture; the centre by default), and
    holds there. ``size`` is the picture in source pixels (a clip's display
    width, its stored height). The end window never leaves the picture
    (still_view's ``image`` clamp). The move stops short of a full fill
    where filling would magnify the source more than ``max_upscale`` output
    pixels per source pixel (FILL_MAX_UPSCALE, or the film's
    ``fill_max_upscale``); a source whose plain fit already magnifies it that
    much (A5) does not move at all. Returns the camera, with its ``fill``
    record: the numbers the journal and sources.json carry."""
    iw, ih = float(size[0]), float(size[1])
    s = min(W / iw, H / ih)
    fw, fh = iw * s, ih * s
    ox, oy = (W - fw) / 2.0, (H - fh) / 2.0
    cap = float(max_upscale if max_upscale is not None else shot.get("_fill_max_upscale") or FILL_MAX_UPSCALE)
    z_fill = max(W / fw, H / fh)
    z_cap = max(1.0, cap / s)
    z_end = min(z_fill, z_cap)
    focus = shot.get("focus")
    if focus is None:
        fx, fy, focus_from = 0.5, 0.5, "centre (default)"
    else:
        ok = (isinstance(focus, (list, tuple)) and len(focus) == 2
              and all(isinstance(v, (int, float)) and not isinstance(v, bool) and 0.0 <= float(v) <= 1.0 for v in focus))
        if not ok:
            raise Refused(f"shot {shot['id']}: focus must be [x, y], each 0 to 1 in the picture, not {focus!r} (A34)")
        fx, fy, focus_from = float(focus[0]), float(focus[1]), "declared"
    end = {"z": z_end, "x": (ox + fx * fw) / W, "y": (oy + fy * fh) / H}
    whole = {"z": 1.0, "x": 0.5, "y": 0.5}
    path = [whole] if z_end <= 1.0 + 1e-9 else [whole, end]
    src, _ = M.still_view((iw, ih), M.Layout(W, H), z=z_end, cx=end["x"], cy=end["y"], clamp="image")
    sw, sh = src[2] - src[0], src[3] - src[1]
    at = ((fx * iw - src[0]) / sw, (fy * ih - src[1]) / sh) if sw > 0 and sh > 0 else (0.5, 0.5)
    # each axis either crops inside the picture or (a fill stopped short) shows all of it on the field: never a pixel
    # sampled from beyond the picture's own edge on an axis it crops
    inside = all((lo >= -0.5 and hi <= n + 0.5) or (lo <= 0.5 and hi >= n - 0.5)
                 for lo, hi, n in ((src[0], src[2], iw), (src[1], src[3], ih)))
    dur = float(shot["_dur"])
    open_s = M.FILL["open_s"] if dur >= M.FILL["open_s"] + M.FILL["move_min_s"] else 0.4 * dur
    move_s = min(M.FILL["move_s"], dur - open_s)
    fill = {"z_fill": round(z_fill, 4), "z_end": round(z_end, 4), "full": z_end >= z_fill - 1e-6,
            "fit_upscale": round(s, 4), "end_upscale": round(s * z_end, 4), "full_fill_upscale": round(s * z_fill, 4),
            "max_upscale": cap, "focus": [fx, fy], "focus_from": focus_from,
            "focus_in_frame": [round(at[0], 4), round(at[1], 4)], "end_window_px": [round(v, 2) for v in src],
            "end_inside_picture": inside, "picture": [round(iw, 2), round(ih, 2)], "open_s": round(open_s, 3),
            "move_s": round(move_s, 3), "from": shot.get("_preset_from", "declared")}
    return {"path": path, "clamp": "image", "fill_ok": True, "preset": FILL, "open_s": open_s, "move_s": move_s,
            "z_max": max(p["z"] for p in path), "fit_scale": s, "z_rel_max": z_end / z_fill, "fill": fill}


TOUR_WPS = 2.6                      # words a second, to place a line with no take yet (the pilot narrator's pace)
ML_UPSCALERS_OFF = (None, False, "", "none", "lanczos", "bicubic", "bilinear", "plain")


def tour_lines(play: dict, film: Path) -> list[dict]:
    """Every voiced line with its time on the film, for A41's ``at`` anchors:
    a take's measured length (voice_lines), else ``dur_s``, else its subtitle
    cue, else its words at TOUR_WPS."""
    have = {v["id"]: v for v in voice_lines(play, film)}
    subs = {c.get("ref"): c for c in play.get("subtitle_source") or [] if isinstance(c, dict)}
    out = []
    for part in play["parts"]:
        for ln in part.get("lines", []):
            if ln.get("kind") not in VOICE_KINDS or not ln.get("text"):
                continue
            if ln["id"] in have:
                dur = have[ln["id"]]["dur"]
            elif ln.get("dur_s"):
                dur = float(ln["dur_s"])
            elif ln["id"] in subs and subs[ln["id"]].get("end_s") is not None:
                dur = float(subs[ln["id"]]["end_s"]) - float(subs[ln["id"]]["start_s"])
            else:
                dur = len(str(ln["text"]).split()) / TOUR_WPS
            out.append({"id": ln["id"], "kind": ln["kind"], "start": float(ln["start_s"]), "dur": max(dur, 0.1),
                        "text": ln["text"], "words": ln.get("words")})
    return out


def still_windows(cam: dict, s: dict, size, W: int, H: int, hz: float = FPS) -> list[tuple[float, tuple]]:
    """The picture window the renderer shows at each frame of a still (from
    ``overlays.framing_at`` and ``motion.still_view``, what Pictures draws),
    [(t, (x0, y0, x1, y1))]."""
    dur = float(s["_dur"])
    out = []
    L = M.Layout(W, H)
    for k in range(int(math.floor(dur * hz)) + 1):
        t = min(k / hz, dur)
        f = OV.framing_at(cam, t, dur)
        src, dst = M.still_view(size, L, z=f["z"], cx=f["x"], cy=f["y"], clamp=cam["clamp"])
        out.append((t, src))
    return out


def tour_lints(lint, journal: Journal, s: dict, cam: dict, size, W: int, H: int) -> None:
    """A41 at plan time, for a still that tours (or a FIND held at the fill).
    Blocking: the path as written (tour-path), its narration anchors
    (tour-anchor), every frame filled inside the picture (tour-fills), the
    softness cap at the deepest framing (tour-softness), 7.2's zoom limits
    (still-zoom-limit: a preset's own depth, a face at 1.3), and
    every person in the picture in frame at some point in the shot (tour-people:
    A7 over the path; a person the ledger does not locate needs the whole
    picture shown). Warnings (pacing is guidance, A39): a pan or zoom past
    the speed guides (tour-speed), a hold that cannot creep (tour-held).
    Reviewer items: a ``must_show`` region never shown (tour-must-show), a
    path that never shows the whole picture (tour-partial)."""
    dur = float(s["_dur"])
    probs = cam.get("problems") or []
    anchor = [p for p in probs if p.startswith("anchor:")]
    other = [p for p in probs if not p.startswith("anchor:")]
    lint("tour-path", not other, unit=s["id"], stage="motion", grammar="A41",
         evidence={"problems": other, "camera": s.get("camera"), "macro": cam.get("macro"),
                   "fix": None if not other else "stops are {t | at, x, y, z} with x, y 0 to 1 in the picture and z >= 1"})
    lint("tour-anchor", not anchor, unit=s["id"], stage="motion", grammar="A41",
         evidence={"problems": anchor, "fix": None if not anchor else
                   "anchor to a word the narration over this shot speaks (a word index or a cue), or give t"})
    if cam.get("tour") and cam.get("cine") is not None:
        cine_lints(lint, journal, s, cam)
    L = M.Layout(W, H)
    wins, bad, z_min = [], [], math.inf
    for k in range(int(math.floor(dur * FPS)) + 1):
        t = min(k / FPS, dur)
        f = OV.framing_at(cam, t, dur)
        src, dst = M.still_view(size, L, z=f["z"], cx=f["x"], cy=f["y"], clamp=cam["clamp"])
        inside = src[0] >= -0.5 and src[1] >= -0.5 and src[2] <= size[0] + 0.5 and src[3] <= size[1] + 0.5
        full = dst == (0.0, 0.0, float(W), float(H))
        z_rel = (src[2] - src[0]) and T.fill_window(size, W / H)[0] / (src[2] - src[0])
        z_min = min(z_min, z_rel)
        if not (inside and full) and len(bad) < 5:
            bad.append({"t": round(t, 3), "src": [round(v, 2) for v in src], "dst": [round(v, 2) for v in dst]})
        wins.append((t, src))
    lint("tour-fills", not bad, unit=s["id"], stage="motion", grammar="A41",
         evidence={"frames": len(wins), "z_min": round(z_min, 4), "not_filled": bad})
    mw, mh = RESOLUTIONS[1080]                # judged on the 1080p master: every delivery frames the same
    up = min(mw / size[0], mh / size[1]) * cam["z_max"]
    cap = float(s.get("_fill_max_upscale") or STILL_MAX_UPSCALE)
    fill_up = T.upscale(size, mw, mh, 1.0)
    ok = up <= cap + 1e-6
    lint("tour-softness", ok, unit=s["id"], stage="motion", grammar="A5, A34, A41",
         evidence={"deepest_upscale": round(up, 4), "fill_upscale": round(fill_up, 4), "max_upscale": cap, "at": "1080p",
                   "capped": cam.get("capped", False), "fix": None if ok else (
                       f"the fill alone magnifies this picture {fill_up:.2f}x, over {cap:g}x: state fill_exception: "
                       "\"<reason>\" (it is then held whole) or raise the film's fill_max_upscale"
                       if fill_up > cap + 1e-6 else
                       f"pull the deepest stop back to z <= {cam.get('zcap', 1.0):.3f} (or raise fill_max_upscale)")})
    if cam["preset"] == TOUR:
        macro = cam.get("macro")
        z_stops = cam["z_rel_max"]
        limit = PRESET_ZMAX.get(macro) if macro in PRESET_ZMAX and macro != FILL else None
        face_ok = not s.get("face") or cam["tour"]["z_max"] <= 1.3 + 1e-9
        zok = (limit is None or z_stops <= limit + 1e-9) and face_ok
        lint("still-zoom-limit", zok, unit=s["id"], stage="motion", grammar="7.2, A41",
             evidence={"preset": TOUR, "macro": macro, "z_max": round(z_stops, 4), "limit": limit,
                       "face": bool(s.get("face")), "deepest_with_creep": round(cam["tour"]["z_max"], 4)})
        sp = T.speed_report(wins)
        journal.lint("tour-speed", sp["ok"], stage="motion", unit=s["id"], severity="warn", grammar="A39, A41",
                     phase="preflight", evidence=dict(sp, fix=None if sp["ok"] else
                                                      "give the move more time, or fewer stops (a guide, never a block)"))
        held = cam["tour"]["held"]
        journal.lint("tour-held", not held, stage="motion", unit=s["id"], severity="warn", grammar="A41",
                     phase="preflight", evidence={"held": held, "fix": None if not held else
                                                  "nothing can creep here (a 16:9 picture at the cap): add a move"})
        journal.decision("motion", f"{s['id']}: TOUR ({macro}{', covering pass' if cam.get('covering') else ''}), "
                         f"{len(cam['tour']['stops'])} stops, z {cam['tour']['z_min']:.3f} to {cam['tour']['z_max']:.3f}",
                         "A41: the still fills 16:9 on every frame and the camera tours it on the rostrum curve",
                         unit=s["id"], evidence={"stops": [{k: (round(v, 4) if isinstance(v, float) else v)
                                                           for k, v in st.items()} for st in cam["tour"]["stops"]],
                                                 "segments": [g["kind"] for g in cam["tour"]["segments"]],
                                                 "speed": sp})
    item = s.get("_item") or {}
    win = [w for _, w in wins]
    people = T.people_of(item, kind=s.get("kind", "archive_still"))
    r = T.people_check(win, people, size)
    lint("tour-people", r["ok"], unit=s["id"], stage="motion", grammar="A7, A41",
         evidence=dict(r, fix=None if r["ok"] else (
             "a path that passes over every person (locate them in the ledger: people [{name, x, y, w, h}]), "
             "or a pass that shows the whole picture")))
    missed = T.must_show(win, item, size)
    if missed:
        journal.lint("tour-must-show", True, stage="motion", unit=s["id"], severity="review", grammar="A41",
                     phase="preflight", evidence={"never_shown": missed,
                                                  "check": "a crop never removes what changes the reading"})
    if not r["whole_shown"]:
        journal.lint("tour-partial", True, stage="motion", unit=s["id"], severity="review", grammar="A41",
                     phase="preflight", evidence={"macro": cam.get("macro"), "shown": round(T.coverage(win, size), 4),
                                                  "check": "the path never shows the whole picture: what it leaves "
                                                           "out is the author's choice (A41: full visibility comes "
                                                           "from touring the whole surface)"})


def cine_lints(lint, journal: Journal, s: dict, cam: dict) -> None:
    """A43 at plan time, inside every preflight (founder ruling 2: automatic,
    deterministic framing, a human optional; degrade, never block on missing
    human input). Blocking: ``face-cap-live`` (a stop that frames a face or a
    person, from the ledger's ``kind: face|person`` regions or its located
    people, stays at or under z 1.3, creep included, with or without the
    shot's ``face`` flag) and ``anchor-identity`` (a stop that lands on a
    person and is anchored to a name arrives within [-0.8, +0.25] s of the
    name on measured word timings, or at least 1.0 s early and holding
    through it on estimated ones; and binds only when the item's own caption
    names that one person and exactly one person is located). Both refuse
    only what a person wrote: the engine's own stops were re-framed or pulled
    back already in ``still_camera`` and are journaled here. Never blocking:
    a machine box ignored for framing (``source: auto`` under the confidence
    floor, or overridden by a human entry of the same name) is journaled."""
    cine, tl = cam["cine"], cam["tour"]
    bad = T.face_cap_check(tl, cine["persons"])
    lint("face-cap-live", not bad, unit=s["id"], stage="motion", grammar="7.2, A43",
         evidence={"face_zmax": M.CINE["face_zmax"], "people": [p["name"] for p in cine["persons"]],
                   "over": bad[:5], "fix": None if not bad else
                   "a face or a person is never pushed past z 1.3: pull the stop back (leave z out and the engine "
                   "caps it), or frame what is beside them"})
    ident = T.anchor_identity_check(tl, s.get("_item") or {}, cine["regions"], cine["persons"])
    lint("anchor-identity", not ident, unit=s["id"], stage="motion", grammar="A41, A43",
         evidence={"stops": ident, "fix": None if not ident else (
             "on estimated timings arrive at least 1.0 s before the name (lead_s) and hold through it, or measure "
             "the words (words: [{w, t}] on the line); a name binds to one face only when the item's own caption "
             "names that person and exactly one person is located: otherwise frame the group or the whole")})
    if cine["reframed"]:
        journal.decision("motion", f"{s['id']}: {len(cine['reframed'])} person stop(s) re-framed to the group or the "
                         "whole", "A43 (founder ruling 2): identity is never inferred from a face; a stop the engine "
                         "placed that may not bind the name it is timed to frames the group or the whole picture, "
                         "never a single face", unit=s["id"], evidence={"reframed": cine["reframed"]})
    if cine["pulled"]:
        journal.decision("motion", f"{s['id']}: {len(cine['pulled'])} stop(s) pulled back to the face cap",
                         "A43: a face is never pushed past z 1.3, a move across one included", unit=s["id"],
                         evidence={"pulled": cine["pulled"], "face_zmax": M.CINE["face_zmax"]})
    if cine["ignored"]:
        journal.decision("motion", f"{s['id']}: {len(cine['ignored'])} machine box(es) not used for framing",
                         "A43 (founder ruling 2): a human entry wins over auto; under the confidence floor the "
                         "box is ignored and the person it marks counts as unlocated, so the still degrades toward "
                         "the whole", unit=s["id"], evidence={"ignored": cine["ignored"],
                                                              "floor": M.CINE["auto_confidence_floor"]})


def cine_schema_lints(lint, journal: Journal, shots: list[dict], words_for) -> None:
    """A43: the cinematography fields of every still and its ledger item
    against the schema, before any camera is drawn. Malformed values refuse
    (the engine would misbehave on them); unknown keys on a person, a region,
    a stop or ``subject_at`` warn; a ``subject_at`` the narration over the
    shot never speaks warns (the rulebook then lands the subject at the end
    of the shot's last line)."""
    seen_items: set = set()
    for s in shots:
        item = s.get("_item") or {}
        bad, unknown = T.shot_schema(s)
        if item.get("id") not in seen_items:
            seen_items.add(item.get("id"))
            ib, iu = T.item_schema(item)
            bad += [f"ledger {item.get('id')}: {b}" for b in ib]
            unknown += [f"ledger {item.get('id')}: {u}" for u in iu]
        lint("cine-schema", not bad, unit=s["id"], stage="motion", grammar="A43",
             evidence={"malformed": bad, "fix": None if not bad else
                       "boxes are {x, y, w, h} in 0 to 1 inside the picture; class, kind, facing and source take "
                       "their closed lists; compose is golden or centred:<reason>; levels: none states levels_reason"})
        if unknown:
            journal.lint("cine-schema-keys", False, stage="motion", unit=s["id"], severity="warn", grammar="A43",
                         phase="preflight", evidence={"unknown": unknown, "fix": "a misspelt key is read as absent"})
        sa = s.get("subject_at")
        if sa is not None and not bad:
            at, line = (sa.get("at"), sa.get("line")) if isinstance(sa, dict) else (sa, None)
            sp = T.anchor_span(at, words_for(s), line=line, t0=float(s["start_s"]))
            ok = sp is not None and float(s["start_s"]) - 1e-9 <= sp["t"] <= float(s["end_s"]) + 1e-9
            journal.lint("cine-subject-at", ok, stage="motion", unit=s["id"], severity="warn", grammar="A43",
                         phase="preflight", evidence={"subject_at": sa, "onset_s": None if sp is None else
                                                      round(sp["t"] - float(s["start_s"]), 3),
                                                      "measured": None if sp is None else sp["measured"],
                                                      "fix": None if ok else "a cue the narration over this shot "
                                                      "speaks (digits alone are a word index)"})


def ml_upscale_lint(lint, s: dict) -> None:
    """A5 (and A41): a picture made with a learned upscaler is RECONSTRUCTED
    ``upscaled``, whatever its camera: a still that tours, one held whole, a
    clip."""
    item = s.get("_item") or {}
    ml = item.get("ml_upscaled") is True or item.get("upscaler") not in ML_UPSCALERS_OFF or "upscaled" in (
        item.get("alterations") or [])
    if ml:
        okm = s.get("mark") == "RECONSTRUCTED" and "upscaled" in (s.get("alterations") or [])
        lint("tour-ml-upscale", okm, unit=s["id"], stage="motion", grammar="A5, A41",
             evidence={"upscaler": item.get("upscaler"), "ml_upscaled": item.get("ml_upscaled"), "mark": s.get("mark"),
                       "fix": None if okm else "a learned upscale is RECONSTRUCTED 'upscaled', on any camera"})


def fill_exception_lints(lint, journal: Journal, s: dict, cam: dict, size, W: int, H: int) -> None:
    """A41: ``fill_exception`` holds a still whole only where the fill would
    pass the softness cap on the 1080p master (the house master decides, so a
    film renders the same way at every delivery), and it states why.
    Journaled and a reviewer item."""
    exc = s.get("fill_exception")
    cap = float(s.get("_fill_max_upscale") or STILL_MAX_UPSCALE)
    mw, mh = RESOLUTIONS[1080]
    fill_up = T.upscale(size, mw, mh, 1.0)
    needed = fill_up > cap + 1e-6
    stated = isinstance(exc, str) and len(exc.split()) >= 2
    lint("tour-fill-exception", needed and stated, unit=s["id"], stage="motion", grammar="A41",
         evidence={"fill_exception": exc, "master_fill_upscale": round(fill_up, 4), "max_upscale": cap,
                   "delivery_fill_upscale": round(T.upscale(size, W, H, 1.0), 4),
                   "fix": None if needed and stated else (
                       "state the reason, a sentence" if needed else
                       f"this picture fills the 1080p master at {fill_up:.2f}x, within {cap:g}x: every still fills "
                       "(A41); drop fill_exception")})
    journal.decision("motion", f"{s['id']}: fill_exception, held whole ({exc})",
                     f"A41: the fill would magnify the source {fill_up:.2f}x on the 1080p master, over {cap:g}x; "
                     "held whole (A7)", unit=s["id"], evidence={"master_fill_upscale": round(fill_up, 4), "max_upscale": cap})
    journal.lint("tour-exception-review", True, stage="motion", unit=s["id"], severity="review", grammar="A41",
                 phase="preflight", evidence={"check": "the still is held whole, pillarboxed, under its stated exception",
                                              "fill_exception": exc})


def continuity_lints(journal: Journal, shots: list[dict], W: int, H: int) -> None:
    """A41 (a warning): at a cut or a dissolve between two touring stills, the
    next shot's first move does not run against the last one's, unless one
    side lands on a stop."""
    for a, b in zip(shots, shots[1:]):
        ca, cb = a.get("_cam") or {}, b.get("_cam") or {}
        if ca.get("preset") != TOUR or cb.get("preset") != TOUR:
            continue
        if (b.get("transition_in") or {}).get("type", "cut") not in ("cut", "dissolve"):
            continue
        va = T.edge_motion(ca["tour"], end=True)
        vb = T.edge_motion(cb["tour"], end=False)
        rev = T.reversal(va, vb)
        journal.lint("tour-continuity", not rev, stage="motion", unit=b["id"], severity="warn", grammar="A41",
                     phase="preflight", evidence={"from": a["id"], "reversed": rev,
                                                  "out_velocity": [round(v, 4) for v in va],
                                                  "in_velocity": [round(v, 4) for v in vb],
                                                  "fix": None if not rev else "continue the last move's direction, or "
                                                  "land the cut on a stop"})


def fill_safe(fill: dict) -> bool:
    """A34: the focus lands where nothing is drawn over it at the end framing:
    above the lower thirds and subtitles (75% of the height, GRAMMAR 4.1) and
    inside the marks' insets (4% of the width, 5% of the height)."""
    x, y = fill["focus_in_frame"]
    return FILL_SAFE[0] <= x <= FILL_SAFE[2] and FILL_SAFE[1] <= y <= FILL_SAFE[3]


def fill_lints(lint, journal: Journal, s: dict, cam: dict | None) -> None:
    """A34 at plan time, for a still or a clip. A FILL refuses: ``fill_ok:
    false`` beside it (fill-declared), a first framing that is not the whole
    picture or an opening under 2 s on a shot long enough for one
    (fill-opens-whole), an end window outside the picture (fill-inside-picture),
    a clip whose source burns names into the span (fill-burned-names). It
    warns, as a reviewer item, where it stops short of a full fill
    (fill-upscale) and where the focus ends under a lower third or a mark
    (fill-focus-safe). Every FILL, and every default that did not fill a
    picture narrower than 16:9, is journaled as a decision."""
    why = str(s.get("_preset_from") or "")
    if cam is None or cam.get("preset") != FILL:
        if why.startswith("no default fill") and "not narrower" not in why and "not an archive" not in why:
            journal.decision("motion", f"{s['id']}: no FILL ({why[len('no default fill: '):]})",
                             "A34: FILL is the default only for an archive picture narrower than 16:9 over "
                             f"{M.FILL['default_min_s']:g} s that does not say otherwise", unit=s["id"])
        return
    f = cam["fill"]
    dur = float(s["_dur"])
    lint("fill-declared", s.get("fill_ok") is not False, unit=s["id"], stage="motion", grammar="A7, A34",
         evidence={"preset": FILL, "fill_ok": s.get("fill_ok"),
                   "fix": None if s.get("fill_ok") is not False else "a FILL fills: drop fill_ok: false or the preset"})
    first = cam["path"][0]
    opens = (abs(first["z"] - 1.0) < 1e-9 and abs(first["x"] - 0.5) < 1e-9 and abs(first["y"] - 0.5) < 1e-9
             and cam["open_s"] >= min(2.0, 0.4 * dur) - 1e-9)
    lint("fill-opens-whole", opens, unit=s["id"], stage="motion", grammar="A7, A34",
         evidence={"first": first, "open_s": round(cam["open_s"], 3), "dur_s": round(dur, 3)})
    lint("fill-inside-picture", f["end_inside_picture"], unit=s["id"], stage="motion", grammar="4.2, A7, A34",
         evidence={"end_window_px": f["end_window_px"], "picture": f["picture"]})
    if s.get("kind") == "archive_video":         # A7 for a moving picture: the reviewer sees every person through the move
        journal.lint("fill-ok", True, stage="motion", unit=s["id"], severity="review", grammar="A7, A34", phase="preflight",
                     evidence={"fill_ok": True, "preset": FILL,
                               "check": "Every person the clip is about is inside the frame through the move, or seen "
                                        "whole in the opening, and no person who is the subject is cropped out."})
    names = burned_names_in_shot(s, s.get("_item")) if s.get("kind") == "archive_video" else []
    lint("fill-burned-names", not names, unit=s["id"], stage="motion", grammar="A26 refined, A34",
         evidence={"speakers_on_screen": names, "fix": None if not names else
                   "the source names its speakers in the frame; a crop could cut the names off: play it whole"})
    journal.lint("fill-upscale", f["full"], stage="motion", unit=s["id"], severity="warn", grammar="A5, A34",
                 phase="preflight", evidence=dict(f, why=None if f["full"] else (
                     f"a full fill would magnify the source {f['full_fill_upscale']:g}x, over {f['max_upscale']:g}x; "
                     f"the move stops at z {f['z_end']:g} of {f['z_fill']:g}" if f["z_end"] > 1.0 + 1e-9 else
                     f"the plain fit already magnifies the source {f['fit_upscale']:g}x, over {f['max_upscale']:g}x: "
                     "the picture stays whole"), reviewer="the founder rules whether the softer fill is wanted "
                                                         "(the film's fill_max_upscale, up to 3.0)"))
    journal.lint("fill-focus-safe", fill_safe(f), stage="motion", unit=s["id"], severity="warn", grammar="4.1, A34",
                 phase="preflight", evidence={"focus": f["focus"], "focus_in_frame": f["focus_in_frame"], "safe": FILL_SAFE,
                                              "fix": None if fill_safe(f) else "the focus ends under a lower third or a "
                                                     "mark: move focus, or keep the shot whole"})
    if not fill_safe(f) or not f["full"]:
        journal.lint("fill-review", True, stage="motion", unit=s["id"], severity="review", grammar="A34", phase="preflight",
                     evidence={"check": "the fill as framed: " + ("stops short of the frame; " if not f["full"] else "")
                                        + ("the focus ends under a drawn area" if not fill_safe(f) else ""), "fill": f})
    journal.decision("motion", f"{s['id']}: FILL ({f['from']}), whole for {f['open_s']:g} s, then a {f['move_s']:g} s "
                     f"rostrum move to z {f['z_end']:g} about {f['focus']} ({f['focus_from']})",
                     "A34: the whole original first (A7), then a crop inside the picture that fills 16:9; a crop is not a "
                     "material alteration (4.2) and plain resampling never is (A5), so the mark and label are unchanged",
                     unit=s["id"], evidence=f)


IMAGE_KINDS = ("archive_still", "drawn", "generated")   # A35: an image is a still picture; a clip's shots are A33's
IMAGE_MAX_PER_FILM, IMAGE_MAX_PER_PART = 2, 1


def image_appearances(shots: list[dict]) -> list[dict]:
    """A35: each showing of an image (a still asset), in film order. Shots of
    one asset in a row, joined by a cut or a dissolve, are one showing (a
    still split for a move, a FILL or a DETAIL on another region of it); a
    dip, or any other shot between, starts a new one. Each carries its
    number in the film and in its part, and the first shot's
    ``repeat_reason``."""
    out: list[dict] = []
    prev = None
    for s in shots:
        a = s.get("asset")
        if TS.is_title(s) and (s.get("_item") or {}).get("record"):
            # A40: the series titles show the film's record whole: a showing of that image
            out.append({"asset": s["_item"]["record"], "part": s.get("_part"), "shots": [s["id"]],
                        "reason": s.get("repeat_reason")})
            prev = None
            continue
        if s.get("kind") not in IMAGE_KINDS or not a:
            prev = None
            continue
        tr = (s.get("transition_in") or {}).get("type", "cut")
        if prev is not None and prev.get("asset") == a and tr in ("cut", "dissolve"):
            out[-1]["shots"].append(s["id"])
        else:
            out.append({"asset": a, "part": s.get("_part"), "shots": [s["id"]], "reason": s.get("repeat_reason")})
        prev = s
    film_n: dict = {}
    part_n: dict = {}
    for ap in out:
        film_n[ap["asset"]] = film_n.get(ap["asset"], 0) + 1
        part_n[(ap["asset"], ap["part"])] = part_n.get((ap["asset"], ap["part"]), 0) + 1
        ap["n_film"], ap["n_part"] = film_n[ap["asset"]], part_n[(ap["asset"], ap["part"])]
        ap["needs_reason"] = ap["n_film"] > IMAGE_MAX_PER_FILM or ap["n_part"] > IMAGE_MAX_PER_PART
    return out


def image_repeat_lints(lint, journal: Journal, shots: list[dict]) -> None:
    """A35 (R12; founder: "we are reusing lots of images, why? Only show if it
    makes sense"): an image may be shown at most twice in a film and at most
    once in a part. A further showing needs ``repeat_reason`` on its first
    shot, a return the story intends; each declared reason is journaled as a
    decision and a reviewer item. Blocking, at plan time."""
    for ap in image_appearances(shots):
        if not ap["needs_reason"]:
            continue
        why = (f"showing {ap['n_film']} of {ap['asset']} in the film" if ap["n_film"] > IMAGE_MAX_PER_FILM else
               f"showing {ap['n_part']} of {ap['asset']} in {ap['part']}")
        reason = ap["reason"]
        ok = isinstance(reason, str) and len(reason.split()) >= 3
        ev = {"asset": ap["asset"], "part": ap["part"], "shots": ap["shots"], "in_film": ap["n_film"], "in_part": ap["n_part"],
              "max_per_film": IMAGE_MAX_PER_FILM, "max_per_part": IMAGE_MAX_PER_PART, "repeat_reason": reason, "why": why}
        lint("image-repeat", ok, unit=ap["shots"][0], stage="scout", grammar="A35",
             evidence=dict(ev, fix=None if ok else "show another picture, or state repeat_reason on the shot (a return the "
                                                   "story intends, in a sentence)"))
        if ok:
            journal.lint("image-repeat", True, stage="scout", unit=ap["shots"][0], severity="review", grammar="A35",
                         phase="preflight", evidence=dict(ev, check="the return is one the story intends"))
            journal.decision("scout", f"{ap['shots'][0]}: {ap['asset']} shown again ({why})", f"A35: {reason}",
                             unit=ap["shots"][0], evidence=ev)


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


def reader_eq_plan(lint, journal: Journal, film: Path, play: dict) -> tuple[dict, str, str | None]:
    """A38 refined (R13; founder: readers get the same house warmth as Tara):
    each reader voice's EQ as the film declares it (``VO.setting``). A voice
    the house table does not hold is measured on this film's takes and its
    EQ derived as the table's are (``VO.derive``), journaled as a decision
    and a reviewer item (``reader-eq-measured``); a voice with no take to
    measure is not EQ'd (a warning). A reading whose ``read_by`` names no
    cast voice cannot have a declared EQ. reader-eq-declared is blocking.
    Returns ({voice: EQ or None}, how it was declared, the table's sha)."""
    table, sha = VO.load_table()
    per, how, problems = VO.setting(play, table)
    who = VO.reader_voices(play)
    if how != "off":
        problems += [f"{lid}: read_by names no cast voice, so its reader EQ cannot be declared"
                     for lid, k in who.items() if k is None]
    lines = {ln["id"]: ln for part in play.get("parts", []) for ln in part.get("lines", []) if ln.get("id") in who}
    for k, spec in per.items():
        if spec["how"] != "house, measured on this film's takes":
            continue
        takes = [(film / (ln.get("wav") or f"audio/{lid}.wav"), len(str(ln.get("text") or "").split()))
                 for lid, ln in lines.items() if who[lid] == k]
        takes = [t for t in takes if t[0].exists()]
        m = VO.measure_takes([t[0] for t in takes], [t[1] for t in takes]) if takes else None
        if m is None:
            spec["how"] = "house, no take to measure: not EQ'd"
            lint("reader-eq-measured", False, unit=k, severity="warn", grammar="A38 refined",
                 evidence={"voice": k, "takes": len(takes), "result": "not EQ'd: no take of this voice has a frame to measure"})
            continue
        spec["eq"], ev = VO.derive(m["excess"], m["f0_hz"])
        journal.decision("scout", f"reader voice {k} measured on {m['takes']} takes of this film: EQ {spec['eq']}",
                         "A38 refined: a voice the house table does not hold is measured as the table's voices are",
                         unit=k, evidence=dict(ev, takes=m["takes"], frames=m["frames"]))
        lint("reader-eq-measured", True, unit=k, severity="review", grammar="A38 refined",
             evidence={"voice": k, "eq": spec["eq"], "takes": m["takes"], "f0_hz": m["f0_hz"],
                       "check": "a voice outside the house table: hear it, and add it to the table "
                                "(python -m studio.engine.voicing measure <films> --write)"})
    eqs = {k: spec["eq"] for k, spec in per.items()}
    lint("reader-eq-declared", not problems, unit="reader_eq", grammar="A38 refined",
         evidence={"declared": how, "voices": {k: dict(spec) for k, spec in per.items()}, "table_sha": sha,
                   "bounds": VO.READER_EQ_BOUNDS, "problems": problems,
                   "archival": "never EQ'd: a real recording keeps its own sound"})
    return eqs, how, sha


def narrator_voice(play: dict) -> dict | None:
    """The cast voice the narration is read by (a narration line's
    ``read_by``, else the voice ``v-narrator``)."""
    voices = {v.get("id"): v for v in (play.get("cast") or {}).get("voices", [])}
    for part in play.get("parts", []):
        for ln in part.get("lines", []):
            if ln.get("kind") == "narration" and ln.get("read_by") in voices:
                return voices[ln["read_by"]]
    return voices.get("v-narrator")


def credit_year(title: str, year: str | None) -> str:
    """The year a credit line prints after the title: none when the title
    already ends with it (E15: "Niger, 1969, 1969")."""
    if not year:
        return ""
    return "" if re.search(r"(?<!\d)" + re.escape(str(year)) + r"[\s.,;:)\]]*$", title or "") else str(year)


def credits_blocks(plan: dict) -> list:
    """The credits roll's blocks. Each credit is broken at 90 characters and,
    where a line is still wider than the column at the plan's size, again by
    its measured width (E15: ``M.credits_wrap``), so no line leaves the column."""
    L, fonts = M.Layout(plan.get("W", 1920), plan.get("H", 1080)), M.Fonts()

    def wrap(text):
        return M.credits_wrap(L, text, fonts)

    shots, readings, sound = [], [], []
    for s in plan["shots"]:
        if s["mark"] == "CARD":
            continue
        it = plan["assets"].get(s.get("asset") or "", {})
        alt = ", ".join(s.get("alterations") or [])
        title = (it.get("title") or "").strip()
        parts = [s["id"], it.get("archive_short") or it.get("archive") or "", title,
                 credit_year(title, year_of(it)), it.get("licence") or ""] + ([alt] if alt else [])
        shots += wrap("  ".join(p for p in parts[:1]) + "  " + ", ".join(p for p in parts[1:] if p))
    seen = set()
    for ln in plan["lines"]:
        if ln.get("kind") == "testimony" and ln.get("read_by") and ln.get("speaker") not in seen:
            seen.add(ln.get("speaker"))
            name = plan["speakers"].get(ln.get("speaker"), {}).get("name", ln.get("speaker"))
            readings.append(f"Read by a computer voice. No recording of {name} was used.")
    recordings, clips_seen = [], set()
    for ln in plan["lines"]:
        # one line per speaker heard from each clip (E15: a debate reel with two speakers credited only the first)
        if archival_span(ln) and (ln["clip"], ln.get("speaker")) not in clips_seen:
            clips_seen.add((ln["clip"], ln.get("speaker")))
            it = plan["assets"].get(ln["clip"], {})
            name = plan["speakers"].get(ln.get("speaker"), {}).get("name", ln.get("speaker"))
            title = (it.get("title") or "").strip()
            recordings += wrap(", ".join(b for b in [f"{name}: original recording", title,
                                                            it.get("archive") or "", credit_year(title, year_of(it)),
                                                            it.get("licence") or ""] if b))
    for c in plan["cues"]:
        bits = [c.get("source", ""), c.get("tradition", ""), c.get("performer", ""), c.get("licence", "")]
        sound += wrap(", ".join(b for b in bits if b))
        for k in ("room_tone", "room_ir"):  # A29 take: the room tone (8.3, a real recording) and the room it plays in
            m = ((c.get("_take") or {}).get("manifest") or {}).get(k)
            if isinstance(m, dict) and (m.get("credit_line") or m.get("recording") or m.get("source")):
                sound += wrap(str(m.get("credit_line") or ", ".join(str(b) for b in (m.get("recording") or m.get("source"),
                                                                                  m.get("licence")) if b)))
    blocks = [("Shots", shots)]
    titles = [s for s in plan["shots"] if TS.is_title(s)]
    if titles:                  # A40: the series titles, drawn from period records; every CC BY input is attributed
        prov, _, _ = TS.provenance(titles[0].get("_item") or {})
        items = TS.provenance_items(prov)
        series = wrap(f"{TS.SERIES}: drawn from {len(items)} period records, no AI; every record on the "
                      "sources page")
        for x in items:
            if (TS.licence_rank(x.get("licence")) or 0) >= 2:
                series += wrap(", ".join(b for b in [TS.plain(x.get("title")), TS.plain(x.get("credit") or x.get("holder")),
                                                     str(x.get("licence") or "")] if b))
        blocks.append(("Series titles", series))
    if readings:
        blocks.append(("Readings", readings))
    if recordings:
        blocks.append(("Recordings", recordings))
    if sound:
        blocks.append(("Sound", sound))
    drawn = [w for ln in OV.credit_lines(plan["shots"]) for w in wrap(ln)]     # A32: every mark and its source
    if drawn:
        blocks.append(("Marks drawn", drawn))
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
            if ln.get("kind") in VOICE_KINDS and archival_span(ln):
                # A26: an archival span's length is its out point minus its in point, the cut the mix places
                out.append({"id": ln["id"], "kind": ln["kind"], "start": float(ln["start_s"]),
                            "dur": max(0.0, float(ln.get("out_s", 0)) - float(ln.get("in_s", 0))), "ref": ln})
            elif ln.get("kind") in VOICE_KINDS and voice_wav(film, ln).exists():
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
    voice's end + gap). Time is inserted and everything after it moves later
    by the same amount. Audio is never shortened or sped up.

    Where the time goes in (A33(1): a line heard over its own clip's picture
    keeps its offset into the shot equal to its offset into the source):
    - by default at the line's start: the shot holding it grows (a clip's out
      point moves later, any other shot's dur_s grows);
    - when that shot is a clip with an archival line of its own at or after
      the insertion (growing it there would slide the line off its picture):
      at the shot's start, so the whole shot moves and the shot before it
      grows ("lengthens the previous shot"), when the voice it collides with
      starts before the shot; otherwise, with no archival line of the clip
      before the insertion, the shot's in point moves earlier by the inserted
      time ("shifts the in point") so the picture after it keeps its place.
      When neither is possible (two archival lines of one take inside one
      shot, or no source before the in point) the line is not moved and the
      voice-overlap lint refuses it: split the shot.

    What moves, and by how much (``shift(t)`` is the time inserted at or
    before the original time t):
    - voice lines, text elements and audio cues by ``shift(start)``. Text keeps
      its length. An audio cue spanning an insertion point plays on through it
      (its end moves by the time inserted before its end), since ambience
      under a longer shot should keep playing;
    - each ``subtitle_source`` cue by exactly the shift of the element its
      ``ref`` names, never stretched, so a caption stays with its words even
      when it starts a few frames before them;
    - shots: the grown one stays, later ones move (a shot-start insertion
      moves the shot it starts).
    Every move is journaled as a decision."""
    import copy
    play = copy.deepcopy(play)
    shots = [sh for part in play["parts"] for sh in part.get("shots", [])]
    assets: dict | None = None

    def inout(sh):                                      # derive a clip's in and out points the way build_plan does
        nonlocal assets
        if "in_s" not in sh or "out_s" not in sh:
            if assets is None:
                assets = load_ledgers(film, play)
            item = assets.get(sh.get("asset"), {})
            in_s = float(sh.get("in_s", item.get("in_s", 0.0)))
            sh["in_s"] = in_s
            sh["out_s"] = float(sh.get("out_s", item.get("out_s", in_s + float(sh.get("dur_s", 0.0)))))

    def grow(sh, d):
        if sh["kind"] == "archive_video":
            inout(sh)
            sh["out_s"] = round(float(sh["out_s"]) + d, 4)
        else:
            sh["dur_s"] = round(float(sh["dur_s"]) + d, 4)

    def owner_of(t):
        cands = [sh for sh in shots if float(sh["start_s"]) <= t + 1e-9]
        return max(cands, key=lambda sh: float(sh["start_s"])) if cands else None

    def shot_end(sh):
        if sh["kind"] == "archive_video":
            inout(sh)
            return float(sh["start_s"]) + float(sh["out_s"]) - float(sh["in_s"])
        return float(sh["start_s"]) + float(sh.get("dur_s", 0.0))

    vl = voice_lines(play, film)

    def mode_for(v, d, prev):
        """How time is inserted for line v delayed by d after voice prev (original timeline), or None."""
        p, owner = v["start"], owner_of(v["start"])
        if owner is None or owner["kind"] != "archive_video":
            return {"mode": "grow", "at": p, "owner": owner}
        S, end = float(owner["start_s"]), shot_end(owner)
        mine = [x for x in vl if archival_span(x["ref"]) and x["ref"]["clip"] == owner.get("asset") and S - 1e-9 <= x["start"] < end]
        if not any(x["start"] >= p - 1e-9 for x in mine):
            return {"mode": "grow", "at": p, "owner": owner}
        k = shots.index(owner)
        if prev["start"] < S - 1e-9 and k > 0:
            return {"mode": "shift", "at": S, "owner": owner, "grown": shots[k - 1]}
        inout(owner)
        if not any(x["start"] < p - 1e-9 for x in mine) and float(owner["in_s"]) >= d - 1e-9:
            return {"mode": "in", "at": p, "owner": owner}
        return None

    # 1. Where time is inserted, on the original timeline.
    points: list[dict] = []
    acc, prev_end, prev = 0.0, None, None
    for v in vl:
        start = v["start"] + acc
        if prev_end is not None and start < prev_end + gap - 1e-9:
            delta = round(prev_end + gap - start, 4)
            m = mode_for(v, delta, prev)
            if m is None:
                journal.decision("scout", f"did not move {v['id']}: no insertion keeps an archival line on its picture",
                                 "A33(1): two archival lines of one take in one shot, or no source before the in point; "
                                 "split the shot (the voice-overlap lint refuses the plan)", unit=v["id"], short_by_s=delta)
            else:
                points.append(dict(m, d=delta, ln=v["ref"], p=v["start"]))
                acc += delta
                start += delta
        if prev_end is None or start + v["dur"] > prev_end:
            prev_end, prev = start + v["dur"], v
    if not points:
        return play

    def shift(t: float, strict: bool = False, shot: bool = False) -> float:
        tot = 0.0
        for pt in points:
            if strict and not (shot and pt["mode"] == "shift"):
                hit = pt["at"] < t - 1e-9
            else:
                hit = pt["at"] <= t + 1e-9
            tot += pt["d"] if hit else 0.0
        return tot

    # 2. Shots: what grows, then everything after the insertion moves.
    for pt in points:
        if pt["mode"] == "grow" and pt["owner"] is not None:
            grow(pt["owner"], pt["d"])
        elif pt["mode"] == "shift":
            grow(pt["grown"], pt["d"])
        elif pt["mode"] == "in":
            pt["owner"]["in_s"] = round(float(pt["owner"]["in_s"]) - pt["d"], 4)
    for sh in shots:
        sh["start_s"] = round(float(sh["start_s"]) + shift(float(sh["start_s"]), strict=True, shot=True), 4)
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
    for pt in points:
        ln, d, p = pt["ln"], pt["d"], pt["p"]
        before = shift(p, strict=True)
        why = f"voice-overlap: {ln['id']} started {d:.3f} s before the previous voice's end plus {gap:g} s (--fit-voices)"
        keep = "; A33(1): the archival line keeps its place on its own picture"
        if pt["mode"] == "shift":
            journal.decision("scout", f"moved {ln['id']} and its shot {pt['owner']['id']} later by {d:.3f} s and lengthened "
                             f"{pt['grown']['id']} by {d:.3f} s; everything from {pt['owner']['id']} on moved {d:.3f} s later",
                             why + keep, unit=ln["id"], moved_from=round(p + before, 4), moved_to=round(p + shift(p), 4),
                             shot=pt["owner"]["id"], lengthened=pt["grown"]["id"], lengthened_s=d, mode="lengthen-previous")
        elif pt["mode"] == "in":
            journal.decision("scout", f"moved {ln['id']} later by {d:.3f} s and opened {pt['owner']['id']} {d:.3f} s earlier in its "
                             f"source (in_s {pt['owner']['in_s']:.3f}); everything after it moved {d:.3f} s later",
                             why + keep, unit=ln["id"], moved_from=round(p + before, 4), moved_to=round(p + shift(p), 4),
                             shot=pt["owner"]["id"], lengthened_s=d, mode="shift-in-point")
        else:
            oid = pt["owner"]["id"] if pt["owner"] is not None else None
            journal.decision("scout", f"moved {ln['id']} later by {d:.3f} s (from {p + before:.3f} s) and lengthened "
                             f"{oid} by {d:.3f} s; everything from that point on moved {d:.3f} s later", why, unit=ln["id"],
                             moved_from=round(p + before, 4), moved_to=round(p + shift(p), 4), shot=oid, lengthened_s=d)
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

    # A21 and A25 (E3, E9): the film's own imagery rule and policy settings; a screenplay that states neither gets the
    # Partition pilot's, which is what the engine enforced before they were per film (studio/engine/policy.py).
    rule, rule_problems = POL.imagery_rule(play)
    if rule["declared"]:
        lint("imagery-rule-declared", not rule_problems, unit="imagery_rule", grammar="A21",
             evidence={"rule": rule, "problems": rule_problems})
    if play.get("share_alike") is not None:
        sa_ok, sa_problems = share_alike_declared(play)
        lint("share-alike-declared", sa_ok, unit="share_alike", grammar="1.2",
             evidence={"share_alike": play.get("share_alike"), "problems": sa_problems})
    settings, settings_stated, settings_problems = POL.film_settings(play)
    if play.get("settings") is not None:
        lint("film-settings", not settings_problems, unit="settings", grammar="A25",
             evidence={"settings": settings, "stated": settings_stated, "bounds": POL.SETTING_BOUNDS, "problems": settings_problems})
    # A38 (R12): the narrator voicing EQ, the house's unless the film declares its own (or off), journaled
    narrator_eq, eq_how, eq_problems = SC.narrator_eq_setting(play)
    lint("narrator-eq-declared", not eq_problems, unit="narrator_eq", grammar="A38",
         evidence={"narrator_eq": narrator_eq, "declared": eq_how, "house": SC.NARRATOR_EQ_HOUSE,
                   "bounds": SC.NARRATOR_EQ_BOUNDS, "problems": eq_problems})
    # A38 refined (R13): each reader voice's EQ, the house table's (measured per voice), the film's own, or off
    reader_eq, reader_eq_how, reader_eq_table = reader_eq_plan(lint, journal, film, play)
    # A29 (R1): the house score standard, with what the film sets of it inside GRAMMAR's bounds
    score_std, score_stated, score_problems = SC.standard(play)
    if play.get("score_standard") is not None:
        lint("score-standard", not score_problems, unit="score_standard", grammar="A29",
             evidence={"standard": score_std, "stated": score_stated, "bounds": SC.BOUNDS, "problems": score_problems})
    # A0 (founder, 2026-10-11), the founding principle: show as was, not as is, and never tell (studio/engine/aswas.py)
    for c in AW.checks(play, assets, film=film):
        lint(c["rule"], c["ok"], unit=c["unit"], severity=c["severity"], evidence=c["evidence"], grammar=c["grammar"])
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
    cues += [dict(x, _part=None) for x in play.get("music", [])]     # A29(0): kind is stated, here as in a part
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
        if kind in ("archive_video", "archive_still", "drawn", TS.KIND):
            ok = item is not None
            lint("ledger-cited", ok, unit=s["id"], evidence={"asset": s.get("asset")}, grammar="11.1")
            if not ok:
                continue
            lic = str(item.get("licence") or "")
            lic_ok, sa = licence_allowed(lic, play)
            lint("licence-allowlist", lic_ok, unit=s["id"], grammar="1.2",
                 evidence={"licence": lic, **({"share_alike": (play.get("share_alike") or {}).get("decision") if lic_ok else
                                               "CC BY-SA needs the film's share_alike declaration (its DECISIONS entry)"}
                                              if sa else {})})
            if lic_ok and sa:
                journal.decision("scout", f"{s['id']}: {s['asset']} is {lic}", "CC BY-SA allowed for this film only: "
                                 + str(play["share_alike"]["decision"]), unit=s["id"],
                                 evidence={"asset": s["asset"], "licence": lic, "attribution": "ShareAlike, on the sources page"})
            # A21 (E3): the film's imagery rule on the asset's content flags. Under the default rule this is the
            # Partition lint exactly: no-bodies, shows_bodies (or the older shows_violence_or_bodies) stated false.
            for c in POL.asset_checks(item, rule):
                lint(c["rule"], c["ok"], unit=s["id"], severity=c["severity"], evidence=c["evidence"],
                     grammar="1.6" if c["rule"] == "no-bodies" and not rule["declared"] else "1.6, 11.1, A21")
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
            if ds > 0:
                black = M.dip_black_frames(ds, FPS)
                lint("dip-black-hold", black >= M.DIP_HOLD_MIN_FRAMES, unit=s["id"], grammar="7.3, A11, BRAND-KIT 11c",
                     evidence={"s": ds, "black_frames": black, "min_frames": M.DIP_HOLD_MIN_FRAMES})
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

    # AI-GENERATED share (decision "No AI-generated imagery in the Partition pilot"); A25: the film's
    # ai_generated_share_max, 0 unless it states otherwise, never over GRAMMAR 2.6's 15%.
    gen = sum(s["f1"] - s["f0"] for s in shots if s["mark"] == "AI-GENERATED")
    gen_max = settings["ai_generated_share_max"]
    if gen_max == 0:
        lint("ai-generated-share-zero", gen == 0, stage="marks",
             evidence={"generated_frames": gen, "frames": total_frames} if "ai_generated_share_max" not in settings_stated else
             {"generated_frames": gen, "frames": total_frames, "max": 0.0},
             grammar="decision 2026-10-10" if "ai_generated_share_max" not in settings_stated else "A25")
    else:
        lint("ai-generated-share-max", gen / total_frames <= gen_max + 1e-9, stage="marks", grammar="2.6, A2, A25",
             evidence={"generated_frames": gen, "frames": total_frames, "share": round(gen / total_frames, 4), "max": gen_max})

    image_repeat_lints(lint, journal, shots)     # A35 (R12): an image is shown at most twice, once per part

    # Stills: the camera (A41: a tour that fills, or whole under a fill exception), the people guard over each
    # shot, the resampler (A5), fill_ok for the reviewer.
    words_src = None
    stills = [s for s in shots if s["kind"] in ("archive_still", "drawn") and s.get("_item", {}).get("_path")]
    if any(x.get("camera") is not None or x.get("subject_at") is not None for x in stills):
        words_src = tour_lines(play, film)
    # A43: the cinematography fields against the schema first; a malformed box or list refuses before any camera
    cine_schema_lints(lint, journal, stills, lambda x: T.shot_words(words_src or [], x["start_s"], x["end_s"]))
    if lint_fail:
        raise Refused("lint failed: " + "; ".join(lint_fail))
    for s in shots:
        if s["kind"] in ("archive_still", "drawn") and s.get("_item", {}).get("_path"):
            if s["kind"] == "drawn" and s.get("camera") is None:
                s.setdefault("preset", "HOLD")
            with Image.open(s["_item"]["_path"]) as im:
                size = im.size
            # A41 (founder, 2026-10-17): a still may go to 3.0x unless the film states its own fill_max_upscale
            s["_fill_max_upscale"] = (settings["fill_max_upscale"] if "fill_max_upscale" in settings_stated
                                      else STILL_MAX_UPSCALE)
            words = T.shot_words(words_src or [], s["start_s"], s["end_s"])
            cam = still_camera(s, size, W, H, words=words)
            cam = engine_cover(s, cam, size, W, H, words, journal)
            s["_cam"] = cam
            fill_lints(lint, journal, s, cam)
            ml_upscale_lint(lint, s)
            if cam["preset"] == TOUR or cam.get("a41"):
                tour_lints(lint, journal, s, cam, size, W, H)
                if cam["preset"] == OV.FIND:
                    lint("still-zoom-limit", cam["z_rel_max"] <= cam["scan_zmax"] + 1e-9, unit=s["id"], stage="motion",
                         grammar="7.2, A32", evidence={"preset": OV.FIND, "z_max": round(cam["z_rel_max"], 4),
                                                       "limit": round(cam["scan_zmax"], 4), "face": bool(s.get("face"))})
            else:
                if cam.get("fill_exception") is not None:
                    fill_exception_lints(lint, journal, s, cam, size, W, H)
                if cam["preset"] == OV.FIND:
                    limit = cam["scan_zmax"]
                    ok = cam["z_rel_max"] <= limit + 1e-9
                else:
                    limit = PRESET_ZMAX.get(cam["preset"], 1.0)
                    ok = cam["z_rel_max"] <= limit + 1e-9 and cam["z_rel_max"] <= 1.3 + 1e-9
                    # A41: a still held whole creeps inside its own shape, at most whole_creep_max
                    ok = ok and cam.get("creep_z", 1.0) <= M.TOUR["whole_creep_max"] + 1e-9
                lint("still-zoom-limit", ok, unit=s["id"], stage="motion", grammar="7.2",
                     evidence={"preset": cam["preset"], "z_max": round(cam["z_rel_max"], 4),
                               "limit": round(limit, 4), "face": bool(s.get("face"))})
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
                journal.lint("fill-ok", True, stage="motion", unit=s["id"], severity="review", grammar="A7, A41", phase="preflight",
                             evidence={"fill_ok": cam["fill_ok"], "preset": cam["preset"], "macro": cam.get("macro"),
                                       "check": ("Every person in the photograph is inside the frame at some point in this shot."
                                                 if cam["fill_ok"] else "Held whole under a fill exception (A41).")})
            if s.get("fill_ok") is False and cam["preset"] == TOUR:
                journal.decision("motion", f"{s['id']}: fill_ok: false no longer holds a still whole",
                                 "A41: every still fills 16:9; a still kept whole states fill_exception (only when the "
                                 "softness cap cannot be met)", unit=s["id"])
    continuity_lints(journal, shots, W, H)
    OV.lints(lint, shots, W, H, play)                # A32: marks drawn over a georeferenced archive sheet
    if lint_fail:
        raise Refused("lint failed: " + "; ".join(lint_fail))

    # Clips: probe, conform (A6), fit at native aspect (A5, 7.5).
    for s in shots:
        if s["kind"] != "archive_video":
            continue
        item = s["_item"]
        with journal.unit("conform", s["id"], size={"driver": "seconds", "value": round(s["_dur"], 3)}, model=ENGINE_MODEL,
                          unit_kind="clip") as u:
            if is_long_reel(item):
                # A26 (E11): a long reel is cut to the shot's span (with SPAN_PAD_S either side) before anything reads it;
                # the probe, the conform and every frame read the cached span, in reel time through its offset.
                sp = cached_span(film, item["_path"], s["in_s"], s["out_s"], video=True, pad_s=SPAN_PAD_S)
                s["_span"] = sp
                pr = probe_video(Path(sp["file"]))
                pr["span_duration_s"] = pr["duration_s"]
                pr["duration_s"] = sp["offset_s"] + pr["duration_s"]
                pr["container_duration_s"] = sp["offset_s"] + pr["container_duration_s"]
                journal.decision("conform", f"read from a cached span of the reel, {sp['offset_s']:.3f} to "
                                 f"{pr['duration_s']:.3f} s", "A26: a source over "
                                 f"{LONG_REEL_BYTES // (1024 * 1024)} MB (or trim_span: true) is never read whole",
                                 unit=s["id"], evidence={"asset": s.get("asset"), "span": sp})
            else:
                pr = probe_video(Path(item["_path"]))
            conf = conform_plan(item, pr)
            ntsc = any(abs(pr["fps"] - r) < 0.02 for r in (29.97, 59.94))
            if ntsc:
                lint("telecine-declared", POL.flag(item.get("telecined")), unit=s["id"], stage="conform", grammar="A6",
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
            # A34: a clip narrower than 16:9 FILLs (declared, or by default over 6 s); it is decoded large enough
            # for its end framing, so the crop samples the source once (Lanczos), never an upsampled fit
            preset = shot_preset(s, dar, still=False)
            cam = None
            ml_upscale_lint(lint, s)
            if s.get("camera") is not None and preset != TOUR:
                lint("tour-video", False, unit=s["id"], stage="motion", grammar="A41",
                     evidence={"camera": s.get("camera"), "preset": preset,
                               "fix": "a clip takes no camera path (a later ticket): drop camera; the preset plays"})
            elif preset == TOUR:
                # A41: a crop could cut a burned caption off (A26 refined), and a path on video is a later ticket
                burned = burned_names_in_shot(s, item) or ([{"burned_captions": True}] if item.get("burned_captions") else [])
                lint("tour-burned-captions", not burned, unit=s["id"], stage="motion", grammar="A26 refined, A41",
                     evidence={"speakers_on_screen": burned, "fix": None if not burned else
                               "the source burns captions into the frame; a path could cut them off: play it whole"})
                if not burned:
                    lint("tour-video", False, unit=s["id"], stage="motion", grammar="A41",
                         evidence={"camera": s.get("camera"), "fix": "a path on a clip is a later ticket: play it as it "
                                   "is (HOLD) or FILL (A34)"})
            elif preset is not None and preset not in VIDEO_PRESETS:
                lint("video-preset", False, unit=s["id"], stage="motion", grammar="7.1, A34",
                     evidence={"preset": preset, "allowed": list(VIDEO_PRESETS),
                               "fix": "a clip plays as it is (HOLD) or FILLs; Ken Burns presets are for stills"})
            elif preset == FILL:
                s["_fill_max_upscale"] = settings["fill_max_upscale"]
                cam = fill_camera(s, (dar * pr["height"], pr["height"]), W, H)
                s["_cam"] = cam
                if len(cam["path"]) > 1:          # a FILL that cannot move (the upscale limit) plays as it is
                    z = cam["z_max"]
                    s["_video"]["decode"] = [even(vw * z), even(vh * z)]
                    s["_video"]["resampler"] = dict(s["_video"]["resampler"], scale=round(vh * z / pr["height"], 4),
                                                    camera="FILL: bicubic window of the decoded frame (PIL), at most 1:1")
            fill_lints(lint, journal, s, cam)
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
        if s.get("intent") is not None:          # A30: the closed list, on a black or card shot only
            it = s["intent"]
            known = isinstance(it, str) and it in BLACK_INTENTS
            ok = known and s["kind"] in BLACK_KINDS and (it not in BLACK_ONLY_INTENTS or s["kind"] == "black")
            lint("black-intent", ok, unit=s["id"], grammar="A30",
                 evidence={"kind": s["kind"], "intent": it, "intents": sorted(BLACK_INTENTS),
                           "fix": None if ok else ("intent is a string from the closed list" if not known else
                                                   f"{it} is for a black shot only" if it in BLACK_ONLY_INTENTS else
                                                   "intent is for a black or card shot")})
        if s.get("black_reason") is not None:    # A30 refined: a free-text reason, on a black shot only
            reason = s["black_reason"]
            is_black = s["kind"] == "black"
            is_str = isinstance(reason, str)
            ok = is_black and valid_black_reason(reason)
            fix = (None if ok else
                   "black_reason is for a black shot only" if not is_black else
                   "black_reason is a string" if not is_str else
                   f"black_reason is a sentence of its own words (at least {BLACK_REASON_MIN_WORDS}), "
                   "never a filler token padded to length")
            lint("black-reason", ok, unit=s["id"], grammar="A30 refined",
                 evidence={"kind": s["kind"], "black_reason": reason, "min_words": BLACK_REASON_MIN_WORDS, "fix": fix})
    card_lints(lint, shots, W, H)            # E15: laid out at plan time; overflow refuses, nothing is cut
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
    # E15: every renderer that lays out text draws all of it or refuses; these are laid out here, before any frame
    fonts_ = M.Fonts()
    L_ = M.Layout(W, H)

    def fits(rule, unit, fn, grammar):
        try:
            fn()
            lint(rule, True, unit=unit, grammar=grammar)
        except M.TextOverflow as e:
            lint(rule, False, unit=unit, grammar=grammar, evidence={"why": str(e), "fix": "shorten it; the engine never cuts text"})

    for lt in lower_thirds:
        fits("lower-third-fits", lt["id"], lambda lt=lt: M.lower_third_layout(L_, lt["lines"], fonts_, lt["kind"], lt["flag"]),
             "9, BRAND-KIT 4 and 11c")
    for o in overlays:
        fits("overlay-fits", o["id"], lambda o=o: M.overlay_check(L_, o["text"], fonts_), "9, BRAND-KIT 11c")
    ai_label_lint(lint, shots)
    for s in shots:
        if s.get("label"):
            # A31: at both delivery resolutions, so a check render's size (a sources-only pass reads a 64 px master) never decides
            fits("label-fits", s["id"], lambda s=s: [M.label_check(M.Layout(*wh), s["label"], fonts_, s["mark"])
                                                     for wh in RESOLUTIONS.values()],
                 "A16, A31, BRAND-KIT 11c and 12")
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
                fits("subtitle-fits", c.get("ref"), lambda c=c: M.subtitle_check(L_, c["en"], fonts_.structure_medium),
                     "10, BRAND-KIT 11c")
    screen_text = [x for s in shots for x in (s.get("text") or [])] + [x for lt in lower_thirds for x in lt["lines"] + [lt["flag"] or ""]]
    screen_text += [o["text"] for o in overlays]
    screen_text += [s["detail"] for s in shots] + [s["label"] for s in shots] + [c["text"] for c in subs]
    dashes = [x for x in screen_text if EM_DASH in x]
    lint("no-em-dash", not dashes, evidence=dashes[:5], grammar="9")
    def _cue_time(c):
        try:
            a, b = float(c["start_s"]), float(c["end_s"])
        except (KeyError, TypeError, ValueError):
            return None
        return (a, b) if math.isfinite(a) and math.isfinite(b) else None

    bad_times = [c.get("ref") for c in play.get("subtitle_source", []) if _cue_time(c) is None]
    if bad_times:
        lint("subtitle-times", False, grammar="10, 12", evidence={"refs": bad_times, "why": "start_s and end_s must be numbers"})
    subcues = sorted((*_cue_time(c), c.get("ref")) for c in play.get("subtitle_source", []) if _cue_time(c) is not None)
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
        kind_ok = c.get("kind") in SC.CUE_KINDS          # A29: a cue is music or ambience, spelled so; nothing else is placed
        lint("cue-kind", kind_ok, unit=c.get("id"), grammar="A29",
             evidence={"kind": c.get("kind"), "kinds": list(SC.CUE_KINDS)})
        why = SC.role_problem(c)                 # A29: a music cue's role and score_role, from the closed lists
        lint("score-role", why is None, unit=c.get("id"), grammar="A29",
             evidence={"role": c.get("role"), "score_role": c.get("score_role"), "roles": list(SC.MUSIC_ROLES),
                       "score_roles": list(SC.ROLES), "problem": why})
        if why is None and kind_ok and (c["kind"] == "ambience" or SC.cue_role(c) in SC.UNDERSCORE + ("brand_pulse",)):
            g = c.get("gain_db", 0.0)
            ok = isinstance(g, (int, float)) and not isinstance(g, bool) and math.isfinite(float(g)) and float(g) <= 0.0
            lint("underscore-gain", ok, unit=c.get("id"), grammar="A29, A29 refined",
                 evidence={"role": SC.cue_role(c), "gain_db": g,
                           "fix": None if ok else "an underscore, brand pulse or ambience cue's gain_db may only lower it: "
                                                  "0 or less"})
        if why is None and kind_ok and c["kind"] == "music" and SC.cue_role(c) == "take":
            # A29 take (S4): the film's whole score in one take, its spans, rests and manifest read here, once, for the
            # mix and the lints. What the take is (anchored at 0, to the film's end, gain_db 0, no fades, its files
            # whole) is its definition, not a judgement of its sound, so it blocks; the sound's lints are the canary's.
            tk, probs = SC.load_take(film, c)
            wav = film / (c.get("wav") or f"audio/{c['id']}.wav")
            wav_s = None
            if wav.exists():
                import soundfile as sf
                wav_s = sf.info(str(wav)).duration       # a stem shorter than the film is an old cut's (build_mix: missing)
            probs += SC.take_cue_problems(c, total_frames / FPS, wav_s)
            lint("take-cue", not probs, unit=c.get("id"), grammar="A29 take",
                 evidence={"problems": probs, "files": (tk or {}).get("paths"),
                           "spans": len((tk or {}).get("spans", [])), "rests": len((tk or {}).get("rests", [])),
                           "fix": "; ".join(probs) if probs else None})
            c["_take"] = tk
    takes = [c for c in cues if c.get("kind") == "music" and SC.cue_role(c) == "take"]
    if takes:
        # A29 take: one take at most, and beside it only the A40 main-title theme; the motif and the pulse are inside it
        others = [c.get("id") for c in cues if c.get("kind") == "music" and SC.cue_role(c) not in ("take", "main_title")]
        ok = len(takes) == 1 and not others
        lint("take-only", ok, unit=takes[0].get("id"), grammar="A29 take",
             evidence={"takes": [c.get("id") for c in takes], "other_music": others,
                       "fix": None if ok else "a film with a take has one take and, beside it, only the main-title theme: "
                                              "the motif and the brand pulse are moments inside the take"})
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
    # A21 (E3): the shot-level half of the film's imagery rule (patient shots only; inert for a film that shows none)
    speakers = {sp["id"]: sp for sp in (play.get("cast") or {}).get("speakers", [])}
    cast_names = [str(sp.get("name")) for sp in speakers.values() if sp.get("name")]
    for c in POL.patient_shot_checks(shots, assets, rule, lower_thirds, cast_names):
        lint(c["rule"], c["ok"], unit=c["unit"], severity=c["severity"], evidence=c["evidence"], grammar="A21", stage="motion")
    # A26 (E11): archival lines that play a span of a source's own soundtrack
    named_on_screen = archival_lints(lint, film, play, shots, lines, assets, lower_thirds, vl, speakers)
    # A33 (R11): clip integrity. The sound stays on its picture, quotes are cut on speech edges, shots end on natural
    # boundaries, no flash, no replay, no mouth moving unheard; clip-cut-mid-action is a warning for the report
    clip_integrity = CL.plan_lints(lint, journal, film, shots, lines, assets)
    # A25 (E9): every declared shortfall names a card that states it
    shortfalls = shortfall_lints(lint, play, shots, settings)
    if lint_fail:
        raise Refused("lint failed: " + "; ".join(lint_fail))

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
    # A40: the series titles, a pre-rendered master played as it is after the cold open (studio/engine/titles.py)
    titles = TS.plan_lints(lint, journal, play, shots, assets, lines=lines, texts=texts, cues=cues, vl=vl, silences=silences)
    if lint_fail:
        raise Refused("lint failed: " + "; ".join(lint_fail))
    card_spans = [(s["f0"] / FPS, s["f1"] / FPS) for s in shots if s["mark"] == "CARD"]
    for s in shots:
        if TS.is_title(s):                      # its lockup is a CARD: the film's watermark is off there and fades back
            s["_title"] = {"burned": titles[s["id"]]["burned"], "marks": TS.sub_marks(s["_item"], s["f0"] / FPS),
                           "classes": TS.classes(s["_item"]), "out_class": TS.out_class(s["_item"]),
                           "holds": TS.dip_hold_frames(s["_item"])}
            card_spans += TS.card_spans(s["_item"], s["f0"] / FPS, s["f1"] / FPS)
    card_spans.sort()
    imagery = [s for s in shots if s["mark"] != "CARD"]
    plan = {
        "film": str(film), "title": play.get("title", film.name), "slug": play.get("slug", film.name),
        "W": W, "H": H, "fps": FPS, "frames": total_frames, "duration_s": total_frames / FPS,
        "shots": shots, "assets": {k: {kk: vv for kk, vv in v.items()} for k, v in assets.items()},
        "lines": lines, "cues": cues, "speakers": speakers, "narrator_voice": narrator_voice(play), "silences": sorted(silences),
        "narrator_eq": narrator_eq, "narrator_eq_declared": eq_how,
        "reader_eq": reader_eq, "reader_eq_declared": reader_eq_how, "reader_eq_table": reader_eq_table,
        "reader_voices": VO.reader_voices(play),
        "runtime_target_s": play.get("runtime_target_s"),
        "lower_thirds": lower_thirds, "overlays": overlays, "subtitles": subs, "burn_subtitles": burn_subtitles,
        # A40: a title's entry is the class it ends on, with no label of ours (its own are in the master or drawn
        # from its timeline), so the next shot's glyph crossfades from what the screen shows
        "marks": [{"start": s["f0"] / FPS, "cls": s["_title"]["out_class"], "detail": s["detail"], "label": "", "year": None,
                   "title": True} if TS.is_title(s) else
                  {"start": s["f0"] / FPS, "end": s["f1"] / FPS, "cls": s["mark"], "detail": s["detail"],
                   "label": s["label"], "year": mark_year(s)}           # end: A42's repeats stay inside the shot
                  for s in shots],
        "card_spans": card_spans, "wm_start": (imagery[0]["f0"] / FPS) if imagery else None,
        # A31: the mark key's classes, from the whole film (kept by --until), the series titles' own classes with them (A40)
        "key_classes": list(M.key_classes(shots + [{"mark": c} for s in shots if TS.is_title(s) for c in s["_title"]["classes"]])),
        # A21, A25 and E2's sides: what the sources page states about the film's own rules
        "imagery_rule": rule, "settings": settings, "settings_stated": settings_stated, "shortfalls": shortfalls,
        "score_standard": score_std, "score_standard_stated": score_stated,
        "balance": play.get("balance"), "sides": film_sides(play),
        "clip_integrity": clip_integrity,
    }
    plan["dark_voice"] = dark_voice_runs(plan)          # A30: judged by black_dip_lints, printed in sources.json
    plan["dips"] = dip_list(plan)
    plan["credits"] = credits_blocks(plan)
    try:
        M.credits_layout(M.Layout(W, H), plan["credits"], M.Fonts())
        lint("credits-fits", True, unit="credits", grammar="9, BRAND-KIT 11c")
    except M.TextOverflow as e:
        lint("credits-fits", False, unit="credits", grammar="9, BRAND-KIT 11c", evidence={"why": str(e)})
    if lint_fail:
        raise Refused("lint failed: " + "; ".join(lint_fail))
    # A26 refined (E15): a speaker whose source names him on screen, and who has no lower third of ours, is still named
    # where the record names every voice: the readings on the sources page (sources.json) and the credits' Recordings
    if named_on_screen:
        readings = readings_doc(plan, durations=False)
        recorded = [ln for h, lns in plan["credits"] if h == "Recordings" for ln in lns]
        for x in named_on_screen:
            nm = _ws(x["name"]).lower()
            in_readings = any(r["id"] == x["id"] and _ws(r.get("name") or "").lower() == nm for r in readings)
            in_credits = any(_ws(ln).lower().startswith(nm + ": original recording") for ln in recorded)
            lint("archival-named-elsewhere", in_readings and in_credits, unit=x["id"], grammar="6.3, 11.5, A26 refined",
                 evidence={"speaker_name": x["name"], "clip": x["clip"], "in_readings": in_readings,
                           "in_credits_recordings": in_credits,
                           "fix": None if in_readings and in_credits else
                           "the line is a testimony line whose speaker has a cast name, so the readings and the credits' "
                           "Recordings name the speaker"})
            if in_readings and in_credits:
                journal.decision("scout", f"{x['id']}: no lower third; {x['clip']} names {x['name']} on screen",
                                 "A26 refined: the source's own on-screen name stands in for ours", unit=x["id"],
                                 evidence={"clip": x["clip"], "speaker": x["speaker"]})
        if lint_fail:
            raise Refused("lint failed: " + "; ".join(lint_fail))
    return plan


def film_sides(play: dict) -> list[str]:
    """The sides the film declares (``balance.sides``: ids, or objects with an
    ``id``), else the sides of its cast's speakers in the order they are
    listed. Never a fixed list: a film's sides are its own (GRAMMAR 6.4, E2)."""
    declared = (play.get("balance") or {}).get("sides") if isinstance(play.get("balance"), dict) else None
    if isinstance(declared, list) and declared:
        return [str(x.get("id") if isinstance(x, dict) else x) for x in declared]
    out: list[str] = []
    for sp in (play.get("cast") or {}).get("speakers", []):
        side = sp.get("side")
        if side and side != "narrator" and side not in out:
            out.append(str(side))
    return out


TRANSCRIPT_CUE = re.compile(r"^\s*(\d[\d:.,]*)\s*-->\s*(\d[\d:.,]*)[^|]*\|?\s*(.*)$")
TRANSCRIPT_MARGIN_S = 1.0           # the transcript's cues that may hold an archival span: those within 1 s of it


def _clock(t: str) -> float:
    """``00:03:06.040``, ``00:03:06,040`` or ``03:06.040`` in seconds."""
    out = 0.0
    for part in t.replace(",", ".").split(":"):
        out = out * 60 + float(part)
    return out


def transcript_cues(path: Path) -> list[tuple[float, float, str]]:
    """The timed cues of a transcript file (WebVTT, SRT, or NLM's
    ``start --> end | text`` lines): each cue's start and end in seconds of
    the source, and its words with bracketed tags (``[Music]``,
    ``[Narrator:]``) dropped. An untimed file gives no cues."""
    cues: list[list] = []
    cur = None
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        t = raw.strip()
        m = TRANSCRIPT_CUE.match(t)
        if m:
            cur = [_clock(m.group(1)), _clock(m.group(2)), [m.group(3)]]
            cues.append(cur)
        elif not t:
            cur = None                              # a blank line ends a WebVTT or SRT cue
        elif cur is not None and t != "WEBVTT":
            cur[2].append(t)
    return [(a, b, _ws(re.sub(r"\[[^\]]*\]", " ", " ".join(words)))) for a, b, words in cues]


def transcript_window(cues: list[tuple[float, float, str]], in_s: float, out_s: float,
                      margin: float = TRANSCRIPT_MARGIN_S) -> str:
    """The words of the cues that overlap [in_s - margin, out_s + margin]: the
    only part of the transcript a span from in_s to out_s can be."""
    return _ws(" ".join(t for a, b, t in cues if a < out_s + margin and b > in_s - margin))


def _ws(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def transcript_holds(transcript: str, text: str) -> str | None:
    """How the line's text is found in the transcript: ``"verbatim"`` after
    whitespace normalisation, ``"verbatim without spaces"`` (caption files
    join words across their line breaks, as NLM's do), or None."""
    if _ws(text) and _ws(text) in transcript:
        return "verbatim"
    nospace = re.sub(r"\s+", "", str(text or ""))
    if nospace and nospace in re.sub(r"\s+", "", transcript):
        return "verbatim without spaces"
    return None


def media_duration(path: Path) -> float | None:
    """A media file's length from its container header (ffprobe; never a
    decode), for video and audio-only files alike. None when unknown."""
    r = subprocess.run([ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True, timeout=60)
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return None


LT_SOURCE_FORM = re.compile(r"^.+\S, \S.+$")   # line 3 before its suffix: "<source title>, <archive>" (BRAND-KIT 4)


def archival_lints(lint, film: Path, play: dict, shots: list[dict], lines: list[dict], assets: dict,
                   lower_thirds: list[dict], vl: list[dict], speakers: dict | None = None) -> None:
    """A26 (E11) on every archival span line: its clip resolves to a ledger
    item with a file and an allowed licence, the span lies inside the clip
    (video or audio alone); it carries ``transcript_source`` and a timed
    transcript whose cues around the span (within 1 s of in and out) hold its
    text word for word; its subtitles (``subtitle_source`` cues with its id as
    ``ref``) are that text; its mark is ARCHIVE; no shot plays the same clip's
    own sound over it; a speaker's first archival line has a lower third that
    names the speaker (line 1 is the cast's name) and whose line 3 is
    ``<source title>, <archive>  ·  original recording``, and no lower third
    over it says ``read by a computer voice`` or is malformed. A26 refined
    (E15): a source that names its speakers on screen (declared, and the
    ledger item lists the speaker) may omit that lower third; the lines that
    do are returned, and build_plan checks the speaker is still named in the
    readings and the credits."""
    speakers = speakers or {}
    durs = {v["id"]: v["dur"] for v in vl}
    seen: set = set()
    cues = play.get("subtitle_source", [])
    named_on_screen: list[dict] = []
    declared_naming = play.get("names_its_speakers")
    if declared_naming is not None:
        ok = isinstance(declared_naming, list) and all(isinstance(x, str) for x in declared_naming)
        unknown = [x for x in declared_naming if x not in assets] if ok else []
        lint("names-its-speakers", ok and not unknown, unit="names_its_speakers", grammar="A26 refined",
             evidence={"declared": declared_naming, "not_in_a_ledger": unknown,
                       "fix": None if ok and not unknown else "a list of clip ids from the film's ledgers"})
    declared_naming = set(declared_naming) if isinstance(declared_naming, list) else set()
    for ln in lines:
        if not archival_span(ln):
            continue
        uid = ln["id"]
        item = assets.get(ln["clip"])
        in_s, out_s = float(ln.get("in_s", -1)), float(ln.get("out_s", -1))
        clip_dur = None
        why = []
        path = (item or {}).get("_path")
        if item is None:
            why.append(f"clip {ln['clip']!r} is in no ledger")
        else:
            lic = str(item.get("licence") or "")
            if not licence_allowed(lic, play)[0]:
                why.append(f"licence {lic!r} is not on the allowlist")
            if not path or not Path(path).exists():
                why.append("the clip's file is missing")
        if not (0 <= in_s < out_s):
            why.append(f"in_s {in_s:g} and out_s {out_s:g} are not a span")
        elif path and Path(path).exists():
            dur = clip_dur = media_duration(Path(path))                      # the header, not the reel
            if dur is None:
                why.append("the clip's length cannot be read")
            elif out_s > dur + 1.0 / FPS:
                why.append(f"out_s {out_s:g} is past the clip's end ({dur:.3f} s)")
        if str(ln.get("mark", "ARCHIVE")) != "ARCHIVE":
            why.append(f"an original recording is marked ARCHIVE, not {ln.get('mark')!r}")
        lint("archival-span", not why, unit=uid, grammar="6.3, A26",
             evidence={"clip": ln.get("clip"), "in_s": in_s, "out_s": out_s, "problems": why})
        # the transcript the ledger cites holds the words, at the span's own time; the subtitles are those words
        tf = ln.get("transcript_file") or (item or {}).get("transcript_file")
        tpath = (film / tf) if tf and not Path(tf).is_absolute() else (Path(tf) if tf else None)
        tcues = transcript_cues(tpath) if tpath and tpath.exists() else []
        window = transcript_window(tcues, in_s, out_s)
        found = transcript_holds(window, ln.get("text") or "") if window else None
        ok = bool(ln.get("transcript_source")) and found is not None
        lint("archival-transcript", ok, unit=uid, grammar="6.3, A26",
             evidence={"transcript_source": ln.get("transcript_source"), "transcript_file": str(tpath) if tpath else None,
                       "timed_cues": len(tcues), "window_s": [round(in_s - TRANSCRIPT_MARGIN_S, 3), round(out_s + TRANSCRIPT_MARGIN_S, 3)],
                       "window": window[:400], "found": found,
                       "fix": None if ok else "cite transcript_source and give a timed transcript_file (the line's or its "
                                              "clip's) whose cues within 1 s of in_s and out_s hold the line word for word"})
        mine = [c for c in cues if c.get("ref") == uid or str(c.get("ref", "")).startswith(uid + "-")]
        said = _ws(" ".join(str(c.get("en") or "") for c in mine))
        ok = bool(mine) and said == _ws(ln.get("text") or "")
        lint("archival-subtitles", ok, unit=uid, grammar="6.3, 10, A26",
             evidence={"cues": [c.get("ref") for c in mine], "subtitles": said, "text": _ws(ln.get("text") or ""),
                       "fix": None if ok else "subtitle the line from its transcript: its cues' text is the line's text"})
        a = float(ln["start_s"])
        b = a + durs.get(uid, max(0.0, out_s - in_s))
        double = [s["id"] for s in shots if s["kind"] == "archive_video" and s.get("asset") == ln["clip"]
                  and (s.get("sound") or {}).get("mode", "own") == "own" and s["start_s"] < b and s["start_s"] + s["_dur"] > a]
        lint("archival-double-sound", not double, unit=uid, grammar="7.1, A26",
             evidence={"shots": double, "fix": None if not double else "mute the shot's own sound (sound: mute, with the reason "
                                                                       "that the archival line plays it)"})
        name = (speakers.get(ln.get("speaker")) or {}).get("name")
        over = [lt for lt in lower_thirds if lt["kind"] == "speaker" and len(lt["lines"]) == 3 and lt["start"] < b and lt["end"] > a]
        read_by = [lt["id"] for lt in over if lt["lines"][2].endswith(LT_SUFFIXES[0])]
        good, bad = [], []
        for lt in over:
            if not lt["lines"][2].endswith(LT_SUFFIXES[1]):
                continue
            form = bool(LT_SOURCE_FORM.match(lt["lines"][2][: -len(LT_SUFFIXES[1])]))
            names = bool(name) and _ws(lt["lines"][0]).lower() == _ws(name).lower()
            (good if form and names else bad).append({"id": lt["id"], "source_form": form, "names_the_speaker": names})
        first = ln.get("speaker") not in seen
        seen.add(ln.get("speaker"))
        # A26 refined (E15): a source that burns its speakers' names into the picture names them itself; our lower
        # third would sit on top of theirs. Declared by the screenplay (names_its_speakers: [clip ids]) or the ledger
        # item (names_its_speakers: true), and allowed only for a speaker the item lists in speakers_on_screen.
        on_screen = None
        if first and not good:
            declared = ln["clip"] in declared_naming or (item or {}).get("names_its_speakers") is True
            entries = (item or {}).get("speakers_on_screen") or []
            if declared:
                mine = [e for e in entries if isinstance(e, dict) and bool(name) and _ws(str(e.get("name", ""))).lower()
                        == _ws(name).lower()]
                # a span is clip time: 0 <= in_s < out_s <= the clip's length (read from its header)
                spans = [(float(e["in_s"]), float(e["out_s"])) for e in mine
                         if isinstance(e.get("in_s"), (int, float)) and isinstance(e.get("out_s"), (int, float))
                         and not isinstance(e.get("in_s"), bool) and not isinstance(e.get("out_s"), bool)
                         and 0 <= e["in_s"] < e["out_s"] and clip_dur is not None and e["out_s"] <= clip_dur + 1.0 / FPS]
                line_span = 0 <= in_s < out_s
                over = [sp for sp in spans if line_span and sp[0] < out_s and sp[1] > in_s]
                on_screen = bool(over)
                lint("archival-named-on-screen", on_screen, unit=uid, grammar="6.3, 9, A26 refined",
                     evidence={"clip": ln["clip"], "speaker_name": name, "line_span_s": [in_s, out_s] if line_span else None,
                               "clip_s": clip_dur, "valid_spans": spans,
                               "speakers_on_screen": entries, "overlapping": over,
                               "fix": None if on_screen else "the clip's ledger item lists each speaker its picture names, "
                                      "with the clip-time span the name is on screen ({name, in_s, out_s} in "
                                      f"speakers_on_screen), and a span for {name!r} overlaps the line's in_s to out_s"})
                if on_screen:
                    named_on_screen.append({"id": uid, "clip": ln["clip"], "speaker": ln.get("speaker"), "name": name})
        ok = not read_by and not bad and (bool(good) or not first or bool(on_screen))
        lint("archival-lower-third", ok, unit=uid, grammar="6.3, 6.4, 9, A26",
             evidence={"first_line_of_speaker": first, "speaker_name": name, "original_recording": good, "malformed": bad,
                       "read_by_a_computer_voice": read_by, "named_on_screen_by_the_source": bool(on_screen),
                       "fix": None if ok else (f"the speaker's first line carries a lower third: line 1 '{name}', line 3 "
                                               f"'<source title>, <archive>{LT_SUFFIXES[1]}'")})
    return named_on_screen


def shortfall_lints(lint, play: dict, shots: list[dict], settings: dict) -> list[dict]:
    """A25 refined (E9, CoS design reset): each declared shortfall is well
    formed (what, the film's own floor, a card to state it) and the card it
    names prints its numbers only through placeholders, ``{<what>_share}``
    and ``{<what>_floor}`` with a format (pct, words, fraction), which the
    engine fills from the film's measurement at the mix. The card, and the
    subtitles and text elements shown with it, may hold no other digit,
    number word, fraction or percent sign, and the card holds the
    ``{<what>_share}`` of every shortfall it states. A placeholder anywhere
    else is refused (it would be drawn as written). Every declared shortfall
    is judged; ``measured`` is advisory. Returns the shortfalls."""
    declared = play.get("shortfalls")
    declared = declared if declared is not None else []
    if not isinstance(declared, list):
        lint("shortfall-stated", False, unit="shortfalls", grammar="6.5, A25", evidence={"why": "shortfalls must be a list"})
        declared = []
    by_id = {s["id"]: s for s in shots}
    on_card: dict[str, set] = {}
    for sf in declared:
        if isinstance(sf, dict) and sf.get("stated_on") and sf.get("what") in POL.SHORTFALL_WHAT:
            on_card.setdefault(sf["stated_on"], set()).add(sf["what"])
    spans = {cid: (by_id[cid]["start_s"], by_id[cid]["start_s"] + by_id[cid]["_dur"]) for cid in on_card if cid in by_id}
    out = []
    for k, sf in enumerate(declared):
        probs = POL.shortfall_problems(sf, settings)
        if not isinstance(sf, dict):
            lint("shortfall-stated", False, unit=f"shortfalls[{k}]", grammar="6.5, A25", evidence={"problems": probs})
            continue
        card = by_id.get(sf.get("stated_on"))
        how: dict = {}
        if sf.get("stated_on") and card is None:
            probs.append(f"no shot {sf.get('stated_on')!r} in the film")
        elif card is not None and card["kind"] != "card":
            probs.append(f"{card['id']} is a {card['kind']} shot, not a card")
        elif card is not None:
            text = " ".join(card.get("text") or [])
            if sf.get("what") in POL.SHORTFALL_WHAT and not POL.states_shortfall(sf["what"], text):
                probs.append(f"{card['id']} does not print {{{sf['what']}_share}}"
                             + (" (or {women_speakers_f} with {women_speakers_unsigned})" if sf["what"] == "women" else ""))
            how = {"card_text": card.get("text")}
        lint("shortfall-stated", not probs, unit=f"shortfall:{sf.get('what')}", grammar="6.5, A25",
             evidence={"shortfall": sf, "found": how, "problems": probs})
        out.append(dict(sf, stated=not probs))
    # every surface that can print a number: the cards themselves, then text elements and subtitles shown with them.
    # A placeholder may stand only in a shortfall card's own text and in a subtitle cue shown with that card; a lower
    # third, an overlay or any other text element is drawn as written, so a placeholder there is refused.
    def span(x):
        try:
            a, b = float(x["start_s"]), float(x["end_s"])
        except (KeyError, TypeError, ValueError):
            return None
        return (a, b) if math.isfinite(a) and math.isfinite(b) else None

    surfaces = [("card", s["id"], " ".join(s.get("text") or []), (s["start_s"], s["start_s"] + s["_dur"]))
                for s in shots if s.get("text")]
    for part in play.get("parts", []):
        for t in part.get("text", []):
            surfaces.append(("text", t.get("id"), " ".join(str(x) for x in t.get("lines") or []), span(t)))
    for c in play.get("subtitle_source", []):
        surfaces.append(("subtitle", c.get("ref"), str(c.get("en") or ""), span(c)))
    for kind, sid, text, ab in surfaces:
        if ab is None:
            if on_card or POL.has_placeholder(text):
                lint("shortfall-card", False, unit=f"{kind}:{sid}", grammar="6.5, A25",
                     evidence={"text": text, "why": "start_s and end_s must be numbers, so the card it is shown with is known"})
            continue
        a, b = ab
        if kind == "card" and sid in on_card:
            whats, own = on_card[sid], True
        else:
            near = [cid for cid, (ca, cb) in spans.items() if a < cb and b > ca]
            whats, own = set().union(*(on_card[c] for c in near)) if near else set(), False
            if kind != "subtitle" and POL.has_placeholder(text):
                lint("shortfall-card", False, unit=f"{kind}:{sid}", grammar="6.5, A25",
                     evidence={"text": text, "why": "a placeholder may stand only in a shortfall card's own text and in its "
                                                    "subtitle cues; here it would be printed as written"})
                continue
            if not near:
                if POL.has_placeholder(text):
                    lint("shortfall-card", False, unit=f"{kind}:{sid}", grammar="6.5, A25",
                         evidence={"text": text, "why": "a subtitle placeholder outside a shortfall card's time would print "
                                                        "a number no card states"})
                continue
        probs, info = POL.template_problems(text, whats, needs_share=own)
        lint("shortfall-card", not probs, unit=f"{kind}:{sid}", grammar="6.5, A25",
             evidence=dict(info, text=text, states=sorted(whats), problems=probs))
    return out


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
        self.vw, self.vh = v.get("decode") or v["fit"]          # A34: a FILL clip is decoded at its end framing's size
        self.nbytes = self.vw * self.vh * 3
        self.t0 = start_local
        conform = v["conform"]["filter"]
        neutral = (v.get("neutralise_cast") or {}).get("filter")
        vf = "".join(f + "," for f in (conform, neutral) if f) + f"scale={self.vw}:{self.vh}:flags=lanczos,setsar=1,format=rgb24"
        src, base = clip_file(shot)                # a long reel is read from its cached span (A26), in the span's own time
        ss = shot["in_s"] - base + start_local
        dur = shot["_dur"] - start_local + 2.0 / FPS
        self.err = tempfile.TemporaryFile()
        self.src, self.vf, self.in_s = src, vf, float(shot["in_s"]) - base
        self.src_dur = max(0.0, float((v.get("probe") or {}).get("duration_s") or 0.0) - base)
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
        self.titles: dict[str, TS.Reader] = {}   # A40: the series titles' master, read in order
        self.title_native: np.ndarray | None = None   # the master's own frame last shown (its burned marks are checked on it)

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
        cam = s.get("_cam")
        if cam is not None and len(cam["path"]) > 1:   # A34: the whole frame first, then the rostrum move to the fill
            f = OV.framing_at(cam, t_local, s["_dur"])
            return M.fit_still(fr, self.L, z=f["z"], cx=f["x"], cy=f["y"], clamp=cam["clamp"])
        out = Image.new("RGB", (self.plan["W"], self.plan["H"]), M.PALETTE["letterbox"])
        out.paste(fr, ((self.plan["W"] - r.vw) // 2, (self.plan["H"] - r.vh) // 2))
        return out

    def title(self, s: dict, t_local: float) -> Image.Image:
        """A40: the master's frame, as it is (scaled only when the delivery is not the master's 1080p)."""
        k = min(int(round(t_local * FPS)), s["f1"] - s["f0"] - 1)
        r = self.titles.get(s["id"])
        if r is None or k < r.k - 1:
            if r:
                r.close()
            r = self.titles[s["id"]] = TS.Reader(ffmpeg(), s["_item"]["_path"], k)
        arr = r.frame(k)
        self.title_native = arr
        img = Image.fromarray(arr)
        if img.size != (self.plan["W"], self.plan["H"]):
            img = img.resize((self.plan["W"], self.plan["H"]), Image.Resampling.LANCZOS)
        return img

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
        elif ck == "mark_key":                   # A31: drawn from the class table, never from the shot's text
            if not self.plan.get("key_classes"):       # A31: from the plan, never a default
                raise Refused(f"shot {s['id']}: the mark key has no key_classes in the plan")
            img = M.mark_key_frame(blank, t, start=0.0, end=dur, fonts=f, classes=self.plan["key_classes"])
        else:                                    # silent, perspective, statement: every element of text[] (E15)
            img = M.silent_card_frame(blank, t, start=0.0, end=dur, texts=text, fonts=f)
        return img.convert("RGB")

    def shot(self, i: int, t_local: float) -> Image.Image:
        s = self.plan["shots"][i]
        if s["kind"] in ("card", "black"):
            return self.card(s, t_local)
        if s["kind"] == "archive_video":
            return self.video(s, t_local)
        if TS.is_title(s):
            return self.title(s, t_local)
        cam = s["_cam"]
        img = self.still(s)
        f = OV.framing_at(cam, t_local, s["_dur"])          # the opening framing, then the rostrum move
        pic = M.fit_still(img, self.L, z=f["z"], cx=f["x"], cy=f["y"], clamp=cam["clamp"])
        return OV.draw(pic, s, t_local, f, self.L, img.size) if s.get("_overlay") else pic   # A32: marks on the sheet

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
        for r in self.titles.values():
            r.close()
        self.titles.clear()


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
    title = s.get("_title")
    if title is not None and (title["burned"] or int(round(tl * FPS)) in title["holds"]):
        return img.convert("RGB")           # A40: the master carries its own marks, watermark and lockup: nothing over it
                                            # (and its own dip's black hold stays black, A11)
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
    if title is not None:                # A40: a master without its own marks is marked from its timeline
        return M.mark_frame(rgba, t, title["marks"], pics.fonts).convert("RGB")
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


def expected_probe(plan: dict, cls: str, at: tuple[int, int], bare, *, prev: str | None = None,
                   mix: float = 1.0) -> np.ndarray:
    """A shape-probe pixel as ``cls``'s glyph tile composes it over ``bare``,
    the same pixel of the frame before the mark was drawn. Composed by PIL,
    as mark_frame composes it."""
    L = M.Layout(plan["W"], plan["H"])
    tile, (ox, oy) = M.glyph_tile(L.W, L.H, cls)
    if prev is not None and mix < 1.0:           # inside a class change's crossfade, as mark_frame blends the two tiles
        tile = Image.blend(M.glyph_tile(L.W, L.H, prev)[0], tile, mix)
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
    """'ok' when every shape probe (the glyph box's corner pair and its
    centre, A31) shows what the owning shot's class glyph composes there over
    the bare frame (A16 refined); 'fade' inside the 4-frame class crossfade
    when the centre lies between what the outgoing and the incoming glyphs
    compose there; 'dip' on a dip's black hold (all pixels off, A11, checked
    as all zero); 'shape' when the frame carries another class of the same
    hue (a square for a diamond, a dot for a ring); else 'fail'. ``bare`` is
    the probe pixels before the mark was drawn (``compose(..., probe=)``);
    without them nothing can be judged and the frame fails."""
    s = plan["shots"][i]
    if picture_level(plan, f, i) <= 0.0:
        return "dip" if not arr.any() else "fail"
    if bare is None:
        return "fail"
    L = M.Layout(plan["W"], plan["H"])
    probes = M.glyph_shape_probes(L)
    bares = list(bare) if bare and isinstance(bare[0], (tuple, list, np.ndarray)) else [bare] * len(probes)
    x, y = M.glyph_centre(L)
    b_c = bares[probes.index((x, y))]
    px = arr[y, x, :3].astype(int)
    prev_cls = plan["marks"][i - 1]["cls"] if i > 0 else None     # A40: a title's entry is the class it ends on
    if i > 0 and prev_cls != s["mark"] and f - s["f0"] < round(M.LABEL["fade"] * FPS):
        prev = prev_cls
        mix = M.mark_state(f / FPS, plan["marks"])["mix"]
        want = expected_probe(plan, s["mark"], (x, y), b_c, prev=prev, mix=mix)
        return "fade" if int(np.max(np.abs(px - want))) <= 2 else "fail"
    if glyph_shape_ok(plan, arr, s["mark"], bares):
        return "ok"
    twins = [c for c in M.GLYPH_SHAPE if c != s["mark"] and M.MARK_HUE[c] == M.MARK_HUE[s["mark"]]]
    return "shape" if any(glyph_shape_ok(plan, arr, c, bares) for c in twins) else "fail"


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
    stats = {"ok": 0, "fade": 0, "dip": 0, "fail": 0, "shape": 0, "fail_frames": [], "label": 0, "glyph_only": 0,
             "burned": 0, "dip_glyph": 0}
    title = s.get("_title")
    first_whole, first_detail = None, None
    ms = []
    try:
        for f in range(s["f0"], s["f1"]):
            ft = time.perf_counter()
            probe: dict = {}
            arr = np.asarray(compose(plan, pics, f, i, probe))
            if title is not None:               # A40: the master's own marks (on its native frame), or ours from its timeline
                k = f - s["f0"]
                res = TS.check_frame(pics.title_native if title["burned"] else arr, s["_item"], k)
                if res == "fail" and picture_level(plan, f, i) < 1.0:
                    res = "dip" if not arr.any() else "fade"     # the next shot's own dip, laid over the master's black
            else:
                res = check_mark(plan, arr, f, i, probe.get("bare_corner"))
            stats[res] += 1
            if res in ("ok", "fade") and title is None:   # A16: which of the two carried the provenance on this frame
                st = M.mark_state(f / FPS, plan["marks"])
                stats["label" if st and st["label_alpha"] > 0 else "glyph_only"] += 1
            if res in ("fail", "shape") and len(stats["fail_frames"]) < 10:
                stats["fail_frames"].append(f)
            if f == s["f0"] and s["kind"] == "archive_still" and opens_whole(s):
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


def opens_whole(s: dict) -> bool:
    """A7's first frame is the whole photograph: a still held whole under a
    fill exception (A41). A TOUR still fills from its first frame."""
    return bool((s.get("_cam") or {}).get("opens_whole", True))


def preflight_stills(plan: dict, journal: Journal) -> list[str]:
    """A7's pixel check for every still, run before any frame is rendered: one
    frame per still, its own layer. Returns the shots that are not whole."""
    pics = Pictures(plan)
    bad = []
    try:
        for i, s in enumerate(plan["shots"]):
            if s["kind"] == "archive_still" and s.get("_cam") and opens_whole(s):
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


def archival_span(ln: dict) -> bool:
    """A26 (E11): a testimony line that plays a span (``clip``, ``in_s``,
    ``out_s``) of a source's own soundtrack, rather than a WAV of its own."""
    return bool(ln.get("archival_audio")) and bool(ln.get("clip"))


def is_long_reel(item: dict | None) -> bool:
    """A26 (E11): a source too large to read whole (or a ledger item that says
    ``trim_span: true``) is trimmed to a cached span before conform."""
    if not item:
        return False
    if item.get("trim_span") is True:
        return True
    p = item.get("_path")
    return bool(p) and Path(p).exists() and Path(p).stat().st_size > LONG_REEL_BYTES


def spans_cache_dir(film: Path) -> Path:
    """Where cut spans of long reels are kept: ``<film>/cache/spans`` unless
    ``DOCUMENT_SPANS_CACHE`` names another folder (a film on a near-full
    system disk can keep its spans on a data disk; a span's file name carries
    its source and cut, so one folder may serve several films)."""
    env = os.environ.get("DOCUMENT_SPANS_CACHE")
    return Path(env) if env else Path(film) / "cache" / "spans"


def cached_span(film: Path, src: str | Path, in_s: float, out_s: float, *, video: bool, pad_s: float = 0.0) -> dict:
    """A26 (E11): the span [in_s - pad, out_s + pad] of a source, cut once by an
    input seek (ffmpeg never reads the reel before the seek point, and stops at
    the span's end) into ``<film>/cache/spans/``, keyed by the source's size and
    mtime and the span, never by hashing the reel. Video is re-encoded lossless
    (x264 qp 0, so every decoded frame is the source's own) with the source's
    sound as float PCM; audio alone is mono 48 kHz float WAV, as the mix reads
    it. Returns the file, the reel time it starts at (``offset_s``), and its
    sha256 and length."""
    src = Path(src)
    st = src.stat()
    a = max(0.0, float(in_s) - pad_s)
    b = float(out_s) + pad_s
    rec = {"src": str(src.resolve()), "size": st.st_size, "mtime_ns": st.st_mtime_ns, "edges": edge_digest(src),
           "a": round(a, 4), "b": round(b, 4), "video": video, "v": SPAN_VERSION}
    key = hashlib.sha256(json.dumps(rec, sort_keys=True).encode()).hexdigest()[:16]
    d = spans_cache_dir(film)
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"{src.stem}.{key}.{'mkv' if video else 'wav'}"
    meta = out.with_name(out.name + ".json")
    if out.exists() and meta.exists():
        # D: is exFAT and has corrupted files before: a cached span is used only if its bytes still hash to what was cut
        try:
            info = json.loads(meta.read_text(encoding="utf-8"))
            if info.get("sha256") == sha256_file(out) and info.get("edges") == rec["edges"]:
                return info
        except (OSError, ValueError):
            pass
        _unlink_quietly(out)
    part = out.with_name(out.stem + ".part" + out.suffix)
    cmd = [ffmpeg(), "-v", "error", "-y", "-ss", f"{a:.4f}", "-t", f"{b - a:.4f}", "-i", str(src)]
    if video:
        cmd += ["-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-qp", "0", "-preset", "ultrafast",
                "-fps_mode", "passthrough", "-c:a", "pcm_f32le", "-threads", "2", str(part)]
    else:
        cmd += ["-vn", "-ac", "1", "-ar", str(AUDIO_RATE), "-c:a", "pcm_f32le", str(part)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode or not part.exists():
        _unlink_quietly(part)
        raise EncodeError(f"span {a:.3f} to {b:.3f} s of {src.name} could not be cut: {r.stderr[-400:]}")
    os.replace(part, out)
    info = {"file": str(out), "src": str(src), "offset_s": a, "requested": [round(float(in_s), 4), round(float(out_s), 4)],
            "pad_s": pad_s, "bytes": out.stat().st_size, "sha256": sha256_file(out), "key": key, "edges": rec["edges"]}
    meta.write_text(json.dumps(info), encoding="utf-8")
    return info


EDGE_BYTES = 1 << 20                # a source is identified by its size and the sha256 of its first and last MiB


def edge_digest(path: Path, n: int = EDGE_BYTES) -> str:
    """The source's content key for the span cache, without reading a reel
    whole: sha256 of its size and its first and last ``n`` bytes (the same
    two ranges publish.edge_hashes gives the contract)."""
    size = Path(path).stat().st_size
    h = hashlib.sha256(str(size).encode())
    with open(path, "rb") as fh:
        h.update(fh.read(n))
        fh.seek(max(0, size - n))
        h.update(fh.read(n))
    return h.hexdigest()


def clip_file(s: dict) -> tuple[str, float]:
    """The file a clip shot is read from and the reel time that file starts
    at: the cached span for a long reel (A26), else the ledger's own file."""
    sp = s.get("_span")
    if sp:
        return sp["file"], float(sp["offset_s"])
    return s["_item"]["_path"], 0.0


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
CLEAN_GUARD_AFTER_S = 0.060         # the speech extent: voiced speech and its consonants, then 60 ms of decay after ...
CLEAN_GUARD_BEFORE_S = 0.040        # ... and 40 ms of onset before (CoS final design, T1f)
CLEAN_HF_LO_HZ, CLEAN_HF_HI_HZ = 3000.0, 16000.0   # the consonant band: fricatives, plosive bursts, aspiration
CLEAN_HF_BIN_S = 0.010              # judged in 10 ms bins
CLEAN_HF_OVER_PAUSE_DB = 12.0       # a bin 12 dB or more over the take's pause level in that band extends a word
CLEAN_GATE_NEAR_VOICED_S = 0.150    # a consonant bin this close to voiced speech is in the extent; voice-chop refuses a gate cut there
CLEAN_HF_LOSS_DB = 3.0              # voice-chop: a consonant bin inside the extent may lose at most this to the cleanup
CLEAN_TRUE_PAUSE_MIN = 5            # ... and with fewer than 5 of them the floor frames' p90 stands in
CLEAN_NOISE_FLATNESS = 0.4          # a frame this spectrally flat (white noise reads about 0.56, voiced speech under 0.05)
                                    # is noise, not speech, so it never guards a true pause (T1f: a hiss 25 dB under the
                                    # speech would otherwise count as speech and hide every pause it fills)
CLEAN_PAUSE_GATE_DB = 40.0          # T1f (CoS): the pause gate's fixed depth; a true pause is turned down this far, never up
CLEAN_PAUSE_RAMP_S = 0.040          # its raised-cosine ramps, each inside the region; a region without at least one 20 ms
                                    # frame at full depth between its ramps (a run under 100 ms) is left as it is
# T1f final review (CoS): noise beside words, the floor frames the pause gate cannot reach (within about 100 to 140 ms
# of speech, where the word partly masks them; pre-masking is short, so the limit stays 40 dB under the -20 LUFS dialogue)
CLEAN_BESIDE_MAX_DBFS = -60.0       # their median, cleaned and levelled
CLEAN_BESIDE_P90_MAX_DBFS = -55.0   # and their p90
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


def frame_flatness(x: np.ndarray, k: int) -> np.ndarray:
    """Wiener entropy (spectral flatness) of each 20 ms frame above 100 Hz:
    about 0.56 for white noise, under 0.05 for voiced speech."""
    n = int(round(CLEAN_FRAME_S * AUDIO_RATE))
    F = np.abs(np.fft.rfft(x[: k * n].astype(np.float64).reshape(k, n) * np.hanning(n), axis=1)[:, 2:]) ** 2 + 1e-30
    return np.exp(np.mean(np.log(F), axis=1)) / np.mean(F, axis=1)


def hf_bins(x: np.ndarray) -> np.ndarray:
    """Power (dB) of ``x`` in the consonant band (CLEAN_HF_LO_HZ to
    CLEAN_HF_HI_HZ) per CLEAN_HF_BIN_S bin."""
    h = int(round(CLEAN_HF_BIN_S * AUDIO_RATE))
    X = np.fft.rfft(x.astype(np.float64))
    f = np.fft.rfftfreq(len(x), 1.0 / AUDIO_RATE)
    X[(f < CLEAN_HF_LO_HZ) | (f > CLEAN_HF_HI_HZ)] = 0
    z = np.fft.irfft(X, len(x))
    m = len(z) // h
    return 10.0 * np.log10(np.maximum((z[: m * h].reshape(m, h) ** 2).mean(axis=1), 1e-30))


def speech_extent(x: np.ndarray, before: dict) -> dict:
    """CoS final design (T1f): the one definition of where speech is, used by
    the pause gate, the true pauses, the beside-word set and voice-chop.
    Voiced frames (within CLEAN_NEAR_SPEECH_DB of the take's speech level
    and less flat than noise, CLEAN_NOISE_FLATNESS), extended on both sides
    by any contiguous run of 10 ms bins whose 3 to 16 kHz energy stays
    CLEAN_HF_OVER_PAUSE_DB or more over the take's pause level in that band
    (the median over the raw take's floor frames, digital silence left
    out): consonants, plosive
    bursts, aspiration. Then CLEAN_GUARD_AFTER_S of decay after and
    CLEAN_GUARD_BEFORE_S of onset before. Returns the extent per 10 ms bin
    and per 20 ms frame (a frame is in it when either of its bins is); a
    consonant run that reaches the extent through a guard joins it, to a
    fixpoint (T1f review); the
    consonant-band levels, the pause level in that band, and the near-speech
    and voiced frames."""
    n = int(round(CLEAN_FRAME_S * AUDIO_RATE))
    k = before["frames"]
    per = int(round(CLEAN_FRAME_S / CLEAN_HF_BIN_S))
    px = (x[: k * n].astype(np.float64).reshape(k, n) ** 2).mean(axis=1)
    near = px >= 10 ** ((before["speech_dbfs"] - CLEAN_NEAR_SPEECH_DB) / 10)
    voiced = near & (frame_flatness(x, k) < CLEAN_NOISE_FLATNESS)
    hx = hf_bins(x)
    nb = len(hx)
    vb = np.zeros(nb, bool)
    vb[: min(nb, k * per)] = np.repeat(voiced, per)[:nb]
    gb = np.zeros(nb, bool)
    gb[: min(nb, k * per)] = np.repeat(before["_gaps"], per)[:nb]
    gb &= hx > CLEAN_SILENT_DBFS                  # digital silence has no level: it is not the pause level
    pause_hf = float(np.median(hx[gb])) if gb.any() else float(np.median(hx[hx > CLEAN_SILENT_DBFS] if (hx > CLEAN_SILENT_DBFS).any() else hx))
    hot = hx >= pause_hf + CLEAN_HF_OVER_PAUSE_DB
    after = int(round(CLEAN_GUARD_AFTER_S / CLEAN_HF_BIN_S))
    bef = int(round(CLEAN_GUARD_BEFORE_S / CLEAN_HF_BIN_S))

    def guarded(core_: np.ndarray) -> np.ndarray:
        g = core_.copy()
        for sh in range(1, after + 1):
            g[sh:] |= core_[: nb - sh]
        for sh in range(1, bef + 1):
            g[: nb - sh] |= core_[sh:]
        return g

    # T1f review: to a fixpoint. A hot run that touches the guarded extent (inside it or next to it) joins the core,
    # the guards are applied again, and so on until nothing changes, so a consonant reached only through a guard
    # (T:R2's /k/ after the /s/ and its closure) is speech too
    hot_runs = _runs(hot)
    # a consonant bin within CLEAN_GATE_NEAR_VOICED_S of voiced speech is speech even across a dip (V:N10 5.04 s,
    # E:R09 7.48 s): the voice-chop gate check refuses a gate that cuts one, so the extent never lets it be gated
    w = int(round(CLEAN_GATE_NEAR_VOICED_S / CLEAN_HF_BIN_S))
    near_v = np.convolve(vb.astype(np.int32), np.ones(2 * w + 1, np.int32), mode="same") > 0
    core = vb | (hot & near_v)
    while True:
        ext = guarded(core)
        grown = core.copy()
        for a, b in hot_runs:
            if ext[a:b].any() or (a > 0 and ext[a - 1]) or (b < nb and ext[b]):
                grown[a:b] = True
        if np.array_equal(grown, core):
            break
        core = grown
    ef = np.zeros(k, bool)
    m = min(k, nb // per)
    ef[:m] = ext[: m * per].reshape(m, per).any(axis=1)
    return {"bins": ext, "frames": ef, "hf": hx, "pause_hf_db": pause_hf, "hot": hot, "near": near, "voiced": voiced}


def true_pause_mask(x: np.ndarray, before: dict, live: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """T1f (CoS final design): the true pauses are the live frames outside the
    speech extent (``speech_extent``). Returns (true pauses, near speech,
    voiced), one bool per 20 ms frame."""
    e = speech_extent(x, before)
    return live & ~e["frames"], e["near"], e["voiced"]


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
    the region, so no sample outside it (none inside the speech extent
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


def beside_words(x: np.ndarray, y: np.ndarray, before: dict, live: np.ndarray, gated: np.ndarray) -> dict:
    """T1f (CoS final design): the noise beside words. The beside-word frames
    are the live frames outside the speech extent (``speech_extent``) and
    outside the gated regions, above digital silence on the cleaned take:
    the runs between words too short to gate. They lie beside the words,
    which partly mask them; pre-masking is short, so the limit stays strict,
    40 dB under the -20 LUFS dialogue: their median, cleaned and levelled,
    under CLEAN_BESIDE_MAX_DBFS (-60) and their p90 under
    CLEAN_BESIDE_P90_MAX_DBFS (-55), judged on the frames themselves however
    few. With none, everything outside speech is gated, and that passes and
    is said. Also counts the near-speech frames inside a gated region, which
    the gate must never touch."""
    n = int(round(CLEAN_FRAME_S * AUDIO_RATE))
    k = before["frames"]
    px = (x[: k * n].astype(np.float64).reshape(k, n) ** 2).mean(axis=1)
    py = (y[: k * n].astype(np.float64).reshape(k, n) ** 2).mean(axis=1)
    e = speech_extent(x, before)
    sel = live & ~e["frames"] & ~gated & (py > 10 ** (CLEAN_SILENT_DBFS / 10))
    hit = np.flatnonzero(e["near"] & gated)
    med = round(_db(float(np.median(py[sel]))), 2) if sel.any() else None
    p90 = round(_db(float(np.percentile(py[sel], 90))), 2) if sel.any() else None
    return {"beside_frames": int(sel.sum()), "beside_dbfs": med, "beside_p90_dbfs": p90,
            "beside_at_s": [round(float(i) * CLEAN_FRAME_S, 3) for i in np.flatnonzero(sel)[:20]],
            "gated_near_speech_frames": int(len(hit)),
            "gated_near_speech_at_s": [round(float(i) * CLEAN_FRAME_S, 3) for i in hit[:20]]}


def hf_chop(x: np.ndarray, y_pre: np.ndarray, y: np.ndarray, before: dict) -> dict:
    """T1f, for voice-chop, two checks in 3 to 16 kHz. The gate (independent
    of the speech extent, T1f review): any raw consonant bin (the raw take's
    band energy CLEAN_HF_OVER_PAUSE_DB or more over its pause level) within
    CLEAN_GATE_NEAR_VOICED_S of a voiced frame that the pause gate cut by
    more than CLEAN_HF_LOSS_DB (``y_pre`` is the take before the gate, ``y``
    after it). The cleanup: any consonant bin inside the speech extent that
    the denoise and expander cut by more than CLEAN_HF_LOSS_DB."""
    e = speech_extent(x, before)
    nb = len(e["bins"])
    hp, hg = hf_bins(y_pre)[:nb], hf_bins(y)[:nb]
    m = min(nb, len(hp), len(hg))
    per = int(round(CLEAN_FRAME_S / CLEAN_HF_BIN_S))
    vb = np.zeros(nb, bool)
    vb[: min(nb, len(e["voiced"]) * per)] = np.repeat(e["voiced"], per)[:nb]
    w = int(round(CLEAN_GATE_NEAR_VOICED_S / CLEAN_HF_BIN_S))
    near_v = np.convolve(vb.astype(np.int32), np.ones(2 * w + 1, np.int32), mode="same") > 0
    gate_loss = np.zeros(nb)
    gate_loss[:m] = hp[:m] - hg[:m]
    gate_hit = np.flatnonzero(e["hot"] & near_v & (gate_loss > CLEAN_HF_LOSS_DB))
    loss = e["hf"] - hf_bins(y_pre)[:nb]
    cons = e["bins"] & e["hot"]
    lost = np.flatnonzero(cons & (loss > CLEAN_HF_LOSS_DB))
    return {"hf_pause_db": round(e["pause_hf_db"], 2), "hf_extent_bins": int(e["bins"].sum()),
            "hf_consonant_bins": int(cons.sum()), "hf_gate_cut_bins": int(len(gate_hit)),
            "hf_gate_cut_max_db": round(float(gate_loss[e["hot"] & near_v].max()), 2) if (e["hot"] & near_v).any() else None,
            "hf_gate_cut_at_s": [round(float(i) * CLEAN_HF_BIN_S, 3) for i in gate_hit[:20]],
            "hf_cleanup_loss_bins": int(len(lost)),
            "hf_cleanup_loss_max_db": round(float(loss[cons].max()), 2) if cons.any() else None,
            "hf_cleanup_loss_at_s": [round(float(i) * CLEAN_HF_BIN_S, 3) for i in lost[:20]]}


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
    gated = np.zeros(k, bool)
    for a_, b_ in regions:
        gated[a_:b_] = True

    def finish(yc: np.ndarray) -> tuple[np.ndarray, dict, dict, dict, dict, dict, dict]:
        pre_ = true_pauses(x, yc, before, live)
        yg, pg_ = pause_gate(yc, regions)
        pg_.update(true_pause_before_dbfs=pre_["true_pause_dbfs"], loudest_pause_before_dbfs=pre_["loudest_pause_dbfs"])
        after_ = voice_floor(yg, before["_gaps"], before["_speech"], ref=x)
        return (yg, pg_, after_, true_pauses(x, yg, before, live, gated), beside_words(x, yg, before, live, gated),
                hf_chop(x, yc, yg, before), {})

    y, pg, after, tp, beside, hfc, _ = finish(y)
    consonant_fallback = None
    if hfc["hf_cleanup_loss_bins"]:
        # T1f (CoS): the denoise cut consonants inside the speech extent by over 3 dB: clean the take again by the
        # pause gate alone (no denoise, no expander) and judge that take with the same lints
        consonant_fallback = {"why": f"the cleanup cut {hfc['hf_cleanup_loss_bins']} consonant bins inside the speech extent "
                                     f"by over {CLEAN_HF_LOSS_DB:g} dB in 3 to 16 kHz (up to {hfc['hf_cleanup_loss_max_db']} dB)",
                              "from_path": path, "hf_cleanup_loss_bins": hfc["hf_cleanup_loss_bins"],
                              "hf_cleanup_loss_max_db": hfc["hf_cleanup_loss_max_db"],
                              "hf_cleanup_loss_at_s": hfc["hf_cleanup_loss_at_s"]}
        path, gate = "gate-only", None
        st = dict(_cut_stats(x, x, before), denoise_chopped_audible=0, denoise_chopped_audible_share=0.0)
        st.pop("_px")
        y, pg, after, tp, beside, hfc, _ = finish(x.astype(np.float32))
    rep.update(cleaned=True, path=path, first_pass=first, denoise=den if path != "gate-only" else None, gate=gate,
               consonant_fallback=consonant_fallback, pause_gate=pg, **st, **tp, **beside, **hfc,
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
    if rep.get("consonant_fallback"):
        cf = rep["consonant_fallback"]
        journal.decision("assembly", f"{unit} cleaned again by the pause gate alone (no denoise, no expander): {cf['why']}",
                         "GRAMMAR A19 refined (CoS, T1f): consonants inside the speech extent are never cut by the cleanup; "
                         "a take whose denoise does is gated only, and judged by the same lints", unit=unit, evidence=cf)
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
    bes = None if rep.get("beside_dbfs") is None else round(rep["beside_dbfs"] + lift, 2)
    bes90 = None if rep.get("beside_p90_dbfs") is None else round(rep["beside_p90_dbfs"] + lift, 2)
    # CoS final design: judged on the frames themselves, however few; none means everything outside speech is gated
    nbes = rep.get("beside_frames", 0)
    beside_ok = nbes == 0 or (bes is not None and bes90 is not None and bes < CLEAN_BESIDE_MAX_DBFS
                              and bes90 < CLEAN_BESIDE_P90_MAX_DBFS)
    pg = rep.get("pause_gate") or {}
    journal.decision("assembly", f"{unit} pause gate: {pg.get('regions', 0)} true pauses, {pg.get('gated_s', 0):g} s, "
                     f"turned down {pg.get('depth_db', CLEAN_PAUSE_GATE_DB):g} dB",
                     "GRAMMAR A19 refined, pause gate (T1f): true pauses (live frames outside the speech extent: voiced speech "
                     "and its consonants, 60 ms of decay after, 40 ms of onset before) are turned down with raised-cosine ramps "
                     "inside them; no sample inside the speech extent changes", unit=unit,
                     evidence=dict(pg, loudest_pause_after_level_dbfs=loudest,
                                   loudest_short_pause_after_level_dbfs=None if rep.get("loudest_short_pause_dbfs") is None
                                   else round(rep["loudest_short_pause_dbfs"] + lift, 2),
                                   short_note="runs outside the speech extent under 100 ms are not gated; they are the "
                                              "beside-word frames, judged by the beside-word limit"))
    out = []
    ok = (floor_levelled is not None and floor_levelled < CLEAN_FLOOR_MAX_DBFS and abs(rep["speech_change_db"]) <= CLEAN_SPEECH_TOL_DB
          and pause_ok and loudest_ok)
    journal.lint("voice-clean", ok, stage="assembly", phase="preflight", unit=unit, severity=sev, grammar="A19, T1f",
                 evidence={"measure": "median power of the raw take's quietest 10% of 20 ms frames, on the cleaned and "
                                      "levelled line, and of its true pauses (live frames outside the speech extent; the floor "
                                      "p90 when there are under 5)",
                           "floor_after_level_dbfs": floor_levelled, "max_dbfs": CLEAN_FLOOR_MAX_DBFS,
                           "floor_p90_after_level_dbfs": p90_levelled, "path": rep.get("path", "expander"),
                           "floor_heard_after_level_dbfs": heard,
                           "true_pause_after_level_dbfs": pause_lvl, "true_pause_frames": rep.get("true_pause_frames"),
                           "true_pause_fallback_p90": fallback,
                           "loudest_pause_after_level_dbfs": loudest, "loudest_pause_at_s": rep.get("loudest_pause_at_s"),
                           "beside_after_level_dbfs": bes, "beside_p90_after_level_dbfs": bes90,
                           "beside_frames": rep.get("beside_frames"), "beside_max_dbfs": CLEAN_BESIDE_MAX_DBFS,
                           "beside_at_s": rep.get("beside_at_s"),
                           "beside_verdict": ("0 ungated frames beside words: everything outside speech is gated" if not nbes
                                              else None),
                           "beside_judged": "warn only (voice-beside), CoS 2026-10-10",
                           "beside_p90_max_dbfs": CLEAN_BESIDE_P90_MAX_DBFS,
                           "beside_note": "live frames outside the speech extent and outside the gated regions, above digital "
                                          "silence on the cleaned take (the runs between words too short to gate), judged on the "
                                          "frames themselves however few: partly masked by the words; 40 dB under the -20 LUFS "
                                          "dialogue",
                           "heard_note": "the floor frames that are not digital silence are judged by the beside-word limit",
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
    # CoS (2026-10-10): the beside-word limit warns, never refuses; the founder judges the residue by ear
    journal.lint("voice-beside", beside_ok, stage="assembly", phase="preflight", unit=unit, severity="warn", grammar="A19, CoS 2026-10-10",
                 evidence={"beside_frames": nbes, "beside_after_level_dbfs": bes, "beside_p90_after_level_dbfs": bes90,
                           "beside_max_dbfs": CLEAN_BESIDE_MAX_DBFS, "beside_p90_max_dbfs": CLEAN_BESIDE_P90_MAX_DBFS,
                           "beside_at_s": rep.get("beside_at_s"),
                           "verdict": ("0 ungated frames beside words: everything outside speech is gated" if not nbes else
                                       None if beside_ok else "over the warning thresholds: listen on the released film"),
                           "note": "residue within about 60 to 150 ms of words, partly masked by the word and the underscore; "
                                   "warn only (CoS 2026-10-10); the next remedy is a neural speech denoiser"})
    pause_why = rep.get("pause_why", [])
    sc = rep.get("speech_chop_share", 0.0)
    chop_bad = sc > CLEAN_CHOP_MAX_SHARE
    gated_near = rep.get("gated_near_speech_frames", 0)
    hf_gate, hf_loss = rep.get("hf_gate_cut_bins", 0), rep.get("hf_cleanup_loss_bins", 0)
    chop_ok = not pause_why and not chop_bad and not gated_near and not hf_gate and not hf_loss
    journal.lint("voice-chop", chop_ok, stage="assembly", phase="preflight", unit=unit, severity=sev, grammar="A19, T1f",
                 evidence={"path": rep.get("path", "expander"),
                           "measure": "frames within 30 dB of the take's speech level cut by more than 3 dB, at most 2%",
                           "speech_chop_share": sc, "near_speech_frames": rep.get("near_speech_frames"),
                           "gated_near_speech_frames": gated_near, "gated_near_speech_at_s": rep.get("gated_near_speech_at_s"),
                           "hf_gate_cut_bins": hf_gate, "hf_gate_cut_at_s": rep.get("hf_gate_cut_at_s"),
                           "hf_gate_cut_max_db": rep.get("hf_gate_cut_max_db"),
                           "hf_cleanup_loss_bins": hf_loss, "hf_cleanup_loss_at_s": rep.get("hf_cleanup_loss_at_s"),
                           "hf_cleanup_loss_max_db": rep.get("hf_cleanup_loss_max_db"), "hf_loss_max_db": CLEAN_HF_LOSS_DB,
                           "hf_pause_db": rep.get("hf_pause_db"), "hf_consonant_bins": rep.get("hf_consonant_bins"),
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
    if hf_gate:
        out.append(f"{unit} (voice-chop: the pause gate cut {hf_gate} consonant bins within "
                   f"{CLEAN_GATE_NEAR_VOICED_S * 1000:g} ms of voiced speech by over {CLEAN_HF_LOSS_DB:g} dB in 3 to 16 kHz, at "
                   f"{rep.get('hf_gate_cut_at_s')} s)")
    if hf_loss:
        out.append(f"{unit} (voice-chop: the cleanup cut {hf_loss} consonant bins inside the speech extent by over "
                   f"{CLEAN_HF_LOSS_DB:g} dB in 3 to 16 kHz (up to {rep.get('hf_cleanup_loss_max_db')} dB), at "
                   f"{rep.get('hf_cleanup_loss_at_s')} s)")
    if gated_near:
        out.append(f"{unit} (voice-chop: the pause gate reached {gated_near} frames within {CLEAN_NEAR_SPEECH_DB:g} dB of "
                   f"the speech, at {rep.get('gated_near_speech_at_s')} s)")
    for w in pause_why:
        out.append(f"{unit} (voice-chop: {w})")
    return out if not draft else []


def _journal_peak(journal: Journal, unit: str, peak: dict, draft: bool, ceiling: float | None = None) -> None:
    """A13: a line's peak reduction as a decision, and the bad-take lint (blocking; a warning under --draft).
    ``ceiling`` is the derived voice ceiling of pass 2 (A15 refined, E14); None is A15's fixed VOICE_TP."""
    why = (f"(GRAMMAR A13, A15: {DIALOGUE_LUFS:g} LUFS + {TARGET_TP - TARGET_LUFS:g} dB headroom - {VOICE_TP_MARGIN:g} dB)"
           if ceiling is None else
           f"(GRAMMAR A13, A15 refined: pass 2, {TARGET_TP:g} dBTP less the measured mix-to-master lift less "
           f"{VOICE_CEILING_SAFETY_DB:g} dB, clamped to {VOICE_TP_FLOOR:g} to {VOICE_TP:g})")
    journal.decision("assembly", f"{unit} peak-controlled to {peak['ceiling_dbtp']:g} dBTP: at most {peak['max_reduction_db']:.2f} dB; "
                     f"over 8 dB {peak['over_8db_s']:.3f} s, over 3 dB {peak['over_3db_s']:.3f} s, over 1 dB {peak['over_1db_s']:.3f} s "
                     f"of {peak['dur_s']:.3f} s",
                     f"its true peak after levelling was {peak['tp_before']:.2f} dBTP, past the voice ceiling "
                     f"{VOICE_TP if ceiling is None else ceiling:g} dBTP {why}", unit=unit,
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


def _voice_shift(voice: dict | None) -> float:
    """A cast voice's declared pitch shift in semitones (``pitch_shift_st``; absent is 0)."""
    v = (voice or {}).get("pitch_shift_st", 0) or 0
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else float("nan")


def _voice_name(voice: dict) -> str:
    s = _voice_shift(voice)
    return f"{voice.get('engine')}:{voice.get('voice')}" + (f" shifted {s:+g} st" if s else "")


def load_narrator_profile(narrator_voice: dict | None, path: Path | None = None) -> tuple[dict | None, str]:
    """The stored narrator profile (the approved audition's median f0 and
    centroid) when it exists and is the film's narrator voice, else None;
    and why. It is a drift reference only: it never sets the baseline.

    The file is global, so a voice processed after synthesis is declared per
    film: the narrator's cast voice names ``pitch_shift_st`` (founder ruling
    2026-10-16, Tara lowered 2 semitones by PSOLA), and the drift reference is
    the stored variant of that voice with the same shift (``variants``), made
    from the approved audition takes shifted the same way. A declared shift
    with no stored variant has no reference (a review item), never the
    unshifted profile; an undeclared voice is held to the unshifted one.
    A variant may also be another voice (a film's narrator chosen by the
    founder: Zoe for "Real World", 2026-10-16): the reference is the stored
    entry whose engine, voice and shift all match the film's narrator."""
    path = NARRATOR_PROFILE if path is None else path
    if not path or not Path(path).exists():
        return None, f"no stored profile at {path}"
    prof = json.loads(Path(path).read_text(encoding="utf-8"))
    cands = [prof] + list(prof.get("variants") or [])
    key = lambda v: {k: (v or {}).get(k) for k in ("engine", "voice")}
    want = key(narrator_voice)
    if not any(key(c.get("voice")) == want for c in cands):
        have = key(prof.get("voice"))
        stored = sorted({f"{key(c.get('voice'))['engine']}:{key(c.get('voice'))['voice']}" for c in cands})
        return None, (f"the stored profile is {have['engine']}:{have['voice']}, the film's narrator is "
                      f"{want['engine']}:{want['voice']} (stored voices: {', '.join(stored)})")
    shift = _voice_shift(narrator_voice)
    if shift != shift:                                       # NaN: not a number
        return None, f"the narrator's pitch_shift_st {(narrator_voice or {}).get('pitch_shift_st')!r} is not a number"
    for cand in cands:
        cv = cand.get("voice") or {}
        if key(cv) == want and _voice_shift(cv) == shift:
            return cand, f"drift reference {Path(path).name} ({_voice_name(cv)})"
    stored = ", ".join(_voice_name(c.get("voice") or {}) for c in cands)
    return None, (f"the film's narrator is {_voice_name(dict(want, pitch_shift_st=shift))}; the stored profiles are "
                  f"{stored}: none has that shift")


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


def build_mix(plan: dict, film: Path, journal: Journal, *, draft: bool = False,
              work: Path | None = None, stems: dict | None = None) -> tuple[np.ndarray, dict]:
    """The programme mix, in two passes (A15 refined, E14). Pass 1 levels,
    cleans and peak-controls every line at A15's fixed voice ceiling and
    mixes. If the master's true-peak limiter would then do more than catch
    peaks, pass 2 peak-controls the synthetic lines (and holds the archival
    spans' static gain) to a ceiling derived from the measured lift and mixes
    again (voice_ceiling_pass). ``work`` holds pass 1's trial master (a
    temporary folder when None).

    A29 refined (R10): a bed or a regional cue is band-shaped (score.bed_shape:
    the sub-bass kept, the voice-competing low-mids cut over the standard's
    bed_lowmid_hz, a gentle treble shelf) before it is levelled; every
    underscore cue (bed, transition, sting, outro, regional) is levelled to
    the standard's bed target, a featured cue (the motif, the brand pulse, a
    palette recording) to MUSIC_LUFS; the duck holds through every pause
    inside a line and every gap under the standard's duck_hold_s. ``stems``,
    when given, receives what score_lints reads: each music cue's analysis
    as placed, the voice activity and duck gain on score.py's grids, and the
    phone-check of the mix (the voice against the ducked music and the
    ambience, through the small-speaker simulation).

    A29 take (S4): a take cue is the film's whole score in one stem, placed
    whole at 0 with no shaping, levelling or fades (the duck still applies);
    ``stems`` then receives its reading by span (score.take_analysis)."""
    std = plan.get("score_standard") or dict(SC.STANDARD)
    n = int(round(plan["frames"] / FPS * AUDIO_RATE))
    voice, music, amb, clips = (np.zeros(n, np.float32) for _ in range(4))
    placed = {"lines": [], "cues": [], "clips": [], "missing": []}
    missing_voice, bad_takes, unclean = [], [], []
    narr: dict[str, dict] = {}                   # narration line id -> its voice profile, for narrator-consistency
    eq = plan.get("narrator_eq") if "narrator_eq" in plan else SC.narrator_eq_setting({})[0]
    eq_lines: dict[str, dict] = {}               # A38: narration line id -> its EQ record
    reader_eqs = plan.get("reader_eq") or {}     # A38 refined (R13): reader voice -> its declared EQ (None: not EQ'd)
    reader_of = plan.get("reader_voices") or {}  # reading line id -> its voice
    rd_lines: dict[str, dict] = {}               # reading line id -> its EQ record
    parts: list[dict] = []                       # E14: every voice placement in order, so pass 2 can place them again
    # A36 (R12): every archival segment's edges, planned together (a gap between two of one reel may be joined)
    segs = archival_segments(plan, film)
    plan_edges(segs, plan, film)
    by_seg = {g["id"]: g for g in segs}
    arch: list = []                              # the archival stem as placed: (start sample, sound, gain dB, segment)
    for ln in plan["lines"]:
        if archival_span(ln):
            # A26 (E11): the clip's own soundtrack, cut at in and out, one static gain; never cleaned or limited.
            # A36: its edges carry the reel's sound past the cut and fade it.
            k, act, gain = place_archival_span(voice, plan, film, journal, ln, stash=parts, seg=by_seg.get(ln["id"]),
                                               arch=arch)
            parts[-1]["i"] = len(placed["lines"])
            sp = plan["speakers"].get(ln.get("speaker"), {})
            # A33(1b): the start the span's words were placed at, after any re-sync (its head edge sits before it)
            at = parts[-1]["at_s"] + parts[-1]["core"][0] / AUDIO_RATE
            placed["lines"].append({"id": ln["id"], "speaker": ln.get("speaker"), "side": sp.get("side"), "kind": "archival",
                                    "at_s": at, "dur_s": round(k / AUDIO_RATE, 3), "line_kind": ln.get("kind"),
                                    "speech_from_s": None if not len(act) else round(at + act[0] / AUDIO_RATE, 3),
                                    "speech_to_s": None if not len(act) else round(at + (act[-1] + 1) / AUDIO_RATE, 3),
                                    "level_db": None, "mood_offset_db": None, "cleaned": None, "floor_before_dbfs": None,
                                    "floor_after_dbfs": None, "peak_reduction_db": None, "static_gain_db": gain,
                                    "span": {"clip": ln["clip"], "in_s": float(ln["in_s"]), "out_s": float(ln["out_s"])}})
            continue
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
                if eq is not None:               # A38: after the narrator's profile (A14 judges her own voice), before peaks
                    x, eq_lines[ln["id"]] = SC.apply_voice_eq(x, eq)
            elif reader_eqs.get(reader_of.get(ln["id"])) is not None:
                # A38 refined: a reading, through its own voice's EQ, at the same place (after levelling and A19's
                # cleaning, before peak control); archival audio never reaches here (it is not levelled)
                x, rec = SC.apply_voice_eq(x, reader_eqs[reader_of[ln["id"]]])
                rd_lines[ln["id"]] = dict(rec, voice=reader_of[ln["id"]])
            x0 = x                               # E14: pass 2 peak-controls the levelled line again, at its own ceiling
            x, peak = voice_peak_control(x)
            if peak:
                _journal_peak(journal, ln["id"], peak, draft)
                if peak["bad_take"]:
                    bad_takes.append(f"{ln['id']} ({'; '.join(peak['bad_take'])})")
        offset = mood_offset(journal, ln) if synthetic else 0.0
        place_db = offset if synthetic else float(ln.get("gain_db", 0.0))
        k = _place(voice, x, float(ln["start_s"]), place_db)                # levelling is in x
        act = speech_active(x[:k], place_db)                                 # the speech-active span, as placed
        parts.append({"kind": "synthetic", "id": ln["id"], "x0": x0, "x": x, "at_s": float(ln["start_s"]), "db": place_db,
                      "peak": peak, "i": len(placed["lines"])} if level is not None else
                     {"kind": "archival-file" if not synthetic else "fixed", "id": ln["id"], "x": x,
                      "at_s": float(ln["start_s"]), "db": place_db, "i": len(placed["lines"])})
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
    eq_off = narrator_eq_lints(journal, plan, eq, eq_lines, draft)
    eq_off += reader_eq_lints(journal, plan, rd_lines, placed, draft)
    for c in plan["cues"]:
        wav = film / (c.get("wav") or f"audio/{c['id']}.wav")
        if not wav.exists():
            # A29 take: a missing take is the film's whole score missing, so it blocks a final render (a draft: silence)
            whole = c.get("kind") == "music" and SC.cue_role(c) == "take"
            journal.lint("audio-present", False, stage="assembly", phase="preflight", unit=c["id"],
                         severity="block" if whole and not draft else "warn",
                         evidence={"wav": str(wav), "kind": c.get("kind"), "result": "refused" if whole and not draft
                                   else "silence", **({"why": "the take is the film's whole score (A29 take)"} if whole else {})})
            if whole and not draft:
                raise Refused(f"audio-present (A29 take): the take {c['id']} is missing: {wav} (render it with whole.py, "
                              "or render with --draft to place silence)")
            placed["missing"].append(c["id"])
            continue
        target = music if c.get("kind") == "music" else amb
        x = _read_wav(wav)
        level = None
        role = SC.cue_role(c)
        shaping = None
        if role == "take":
            # A29 take (S4): the whole score, placed whole at 0. No band-shaping (the stem is shaped per span at render),
            # no levelling (its one global gain is baked in), no fades (its entries are composed); only the A37 duck,
            # below, as for any music. build_plan refuses a take with a gain_db; a hand-made plan is refused here too.
            if float(c.get("gain_db", 0.0) or 0.0) != 0.0 or float(c.get("start_s", 0.0)) != 0.0:
                raise Refused(f"take-cue (A29 take): {c['id']} is placed at 0 with gain_db 0; its gain is in the stem")
            tk = c.get("_take") or SC.load_take(film, c)[0]     # build_plan reads it; a hand-made plan is read here
            if tk is None:
                raise Refused(f"take-cue (A29 take): {c['id']}: its spans, rests or manifest cannot be read")
            k = _place(target, x, 0.0, 0.0, float(c["end_s"]))
            placed["cues"].append({"id": c["id"], "kind": "music", "at_s": 0.0, "dur_s": round(k / AUDIO_RATE, 3),
                                   "level_db": None, "part": c.get("_part"), "fade_in_s": 0.0, "fade_out_s": 0.0,
                                   "role": role, "shaping": None, "spans": len(tk.get("spans", [])),
                                   "rests": len(tk.get("rests", []))})
            journal.decision("assembly", f"{c['id']}: the take placed whole at 0 ({k / AUDIO_RATE:.2f} s)",
                             "A29 take: one stem from the first frame to the last; no shaping, levelling or fades, "
                             "only the duck", unit=c["id"],
                             evidence={"spans": len(tk.get("spans", [])), "rests": len(tk.get("rests", [])),
                                       "wav": str(wav)})
            if stems is not None:
                titles = [(s["f0"] / FPS, s["f1"] / FPS) for s in plan["shots"] if TS.is_title(s)]
                stems["take"] = SC.take_analysis(x[:k], tk, titles=titles)
            continue
        if c.get("kind") == "music":            # levelled over the part that plays
            span = x[: max(0, int(round((float(c["end_s"]) - float(c["start_s"])) * AUDIO_RATE)))]
            if role in SC.SHAPED:               # A29 refined: the sub-bass kept, the voice's low-mids and the treble cut
                shaping = SC.shaping_record(std)
                x = span = SC.bed_shape(span, float(std["bed_lowmid_hz"]))
                journal.decision("assembly", f"{c['id']} band-shaped: sub-bass kept under {SC.SUB_BASS_HZ:g} Hz, passed over "
                                 f"{float(std['bed_lowmid_hz']):g} Hz, treble shelved {SC.TREBLE_SHELF_DB:g} dB",
                                 "A29 refined: every bed and regional cue is band-shaped before it is levelled", unit=c["id"],
                                 evidence={"role": role, "shaping": shaping})
            under = role in SC.UNDERSCORE
            level = _level(journal, c["id"], span, SC.bed_lufs(std) if under else MUSIC_LUFS,
                           f"music {role}, the score standard's bed target" if under else f"music {role}")
        fi, fo = float(c.get("fade_in_s", 0) or 0), float(c.get("fade_out_s", 0) or 0)
        span_n = max(0, int(round((float(c["end_s"]) - float(c["start_s"])) * AUDIO_RATE)))
        unfaded = x[:span_n] if stems is not None else None    # A29: breathing is judged before the fades
        x = cue_fades(x, float(c["end_s"]) - float(c["start_s"]), fi, fo)
        gain = (level or 0.0) + float(c.get("gain_db", 0.0))
        k = _place(target, x, float(c["start_s"]), gain, float(c["end_s"]))
        placed["cues"].append({"id": c["id"], "kind": c.get("kind"), "at_s": float(c["start_s"]), "dur_s": round(k / AUDIO_RATE, 3),
                               "level_db": None if level is None else round(level, 2), "part": c.get("_part"),
                               "fade_in_s": fi, "fade_out_s": fo, "role": role, "shaping": shaping})
        if stems is not None:
            y = x[:k] * np.float32(10 ** (gain / 20))
            stems.setdefault("cues", []).append({"id": c["id"], "role": role, "start_s": float(c["start_s"]), "fade_in_s": fi,
                                                 "fade_out_s": fo, "gain_db": float(c.get("gain_db", 0.0)), "shaping": shaping,
                                                 "marks_moment": c.get("marks_moment"),
                                                 "an": SC.analyse_cue(y, role, fi, fo,
                                                                      unfaded=unfaded[:k] * np.float32(10 ** (gain / 20)))})
    for s in plan["shots"]:
        if s["kind"] == "archive_video" and (s.get("sound") or {}).get("mode", "own") == "own" and s["_video"]["probe"]["has_audio"]:
            g = by_seg.get(s["id"])
            if g is None or not len(g["x"]):
                journal.lint("audio-present", False, stage="assembly", phase="preflight", unit=s["id"], severity="warn", evidence="clip audio unreadable")
                continue
            y, h, _ = segment_audio(g)           # A36: the clip's own sound, its edges carried past the cut and faded
            at0 = g["t_in"] - h / AUDIO_RATE
            _place(clips, y, at0)
            arch.append((int(round(at0 * AUDIO_RATE)), y, 0.0, s["id"]))
            journal.decision("assembly", f"{s['id']} plays its own sound with A36 edges",
                             "A36: a clip's own sound never starts or stops on a hard cut of its noise floor", unit=s["id"],
                             evidence={"head": g["head"], "tail": g["tail"]})
            placed["clips"].append(s["id"])
    if missing_voice and not draft:
        raise Refused(f"voice WAVs missing for {', '.join(missing_voice)} (render with --draft to place silence)")
    if bad_takes and not draft:
        raise Refused(f"voice-peak-control (A13): bad takes, re-render them instead of crushing them: {'; '.join(bad_takes)}")
    if unclean:
        raise Refused(f"voice-clean and voice-chop (A19): re-render these takes (or render with --draft): {'; '.join(unclean)}")
    if narrator_off and not draft:
        raise Refused(f"narrator-consistency and narrator-drift (A14): not the narrator's voice: {'; '.join(narrator_off)}")
    if eq_off and not draft:
        raise Refused(f"narrator-eq and reader-eq (A38): the EQ applied is not the one declared: {'; '.join(eq_off)}")
    edge_off = archival_edge_lints(journal, arch, segs, draft=draft)
    if edge_off:
        raise Refused(f"archival-sound-edge (A36): the reel's sound stops in one step: {'; '.join(edge_off)}")
    del arch, segs, by_seg
    spans = [(ln["speech_from_s"], ln["speech_to_s"]) for ln in placed["lines"] if ln.get("speech_from_s") is not None]
    duck = duck_gain(voice, spans=spans, hold_s=float(std["duck_hold_s"]))
    if stems is not None:
        g = int(round(SC.DUCK_GRID_S * AUDIO_RATE))
        m = len(voice) // g
        stems.update(voice_grid=np.abs(voice[: m * g]).reshape(m, g).max(axis=1) > DUCK_VOICE_THRESHOLD,
                     duck_grid=duck[: m * g].reshape(m, g).mean(axis=1), spans=spans,
                     own_sound=[(s["f0"] / FPS, s["f1"] / FPS) for s in plan["shots"] if s["id"] in placed["clips"]]
                     + [(ln["at_s"], ln["at_s"] + ln["dur_s"]) for ln in placed["lines"] if ln["kind"] == "archival"])
        k = int(round(SC.HOP_S / SC.DUCK_GRID_S))
        stems["duck100"] = stems["duck_grid"][: m // k * k].reshape(-1, k).mean(axis=1)
        stems["voice100"] = stems["voice_grid"][: m // k * k].reshape(-1, k).any(axis=1)
        # A29 refined: phone-check, on pass 1's voice (pass 2 only re-peaks the same lines) against the score as heard
        stems["phone"] = SC.phone_check(voice, music * duck + amb, spans)
    mix = (voice + clips + music * duck + amb).astype(np.float32)
    lifted = voice_ceiling_pass(mix, parts, clips, music, amb, placed, journal, draft=draft, work=work, duck=duck)
    return (mix if lifted is None else lifted), placed


def narrator_eq_lints(journal: Journal, plan: dict, eq: dict | None, eq_lines: dict, draft: bool) -> list[str]:
    """A38, narrator-eq: the voicing EQ applied to the narration is the one
    the film declares (the house's by default): each narration line was EQ'd
    with it, and the response measured on the line at each band (a bell at
    its centre, a shelf at 1.5 times its corner) is within
    NARRATOR_EQ_TOL_DB of the declared response there; journaled with
    the setting and each line's re-level. Off, it journals that it is off.
    Blocking on a final render. Returns the reasons to refuse."""
    how = plan.get("narrator_eq_declared", "house (default)")
    if eq is None:
        journal.lint("narrator-eq", True, stage="assembly", phase="preflight", unit="narrator", grammar="A38",
                     evidence={"narrator_eq": None, "declared": how, "lines": 0})
        return []
    bad, worst = [], 0.0
    for lid, rec in eq_lines.items():
        if rec.get("eq") != eq:
            bad.append(f"{lid} was EQ'd with {rec.get('eq')}, not the declared {eq}")
        for c in rec["response"]:
            if c.get("error_db") is None:
                continue
            worst = max(worst, c["error_db"])
            if c["error_db"] > SC.NARRATOR_EQ_TOL_DB:
                bad.append(f"{lid} {c['band']} {c['measured_db']:+.2f} dB, declared {c['declared_db']:+.2f}")
    ok = not bad
    journal.lint("narrator-eq", ok, stage="assembly", phase="preflight", unit="narrator", grammar="A38",
                 severity="warn" if draft else "block",
                 evidence={"narrator_eq": eq, "declared": how, "lines": len(eq_lines),
                           "at_hz": {k: {"declared_db": SC.eq_db_at(b["hz"], eq)} for k, b in eq.items()},
                           "worst_error_db": round(worst, 3), "tol_db": SC.NARRATOR_EQ_TOL_DB, "off_lines": bad[:20],
                           "relevel_db": {lid: r["relevel_db"] for lid, r in list(eq_lines.items())[:200]},
                           "readers": "their own voices' EQ (A38 refined, the reader-eq lint)"})
    return bad


def reader_eq_lints(journal: Journal, plan: dict, rd_lines: dict, placed: dict, draft: bool) -> list[str]:
    """A38 refined, reader-eq: every reading placed was EQ'd with exactly
    its voice's declared EQ (none when its voice's is off), the response
    measured on the line is within NARRATOR_EQ_TOL_DB of the declared one at
    each band, and no archival line was EQ'd. Journaled per voice with each
    line's re-level. Blocking on a final render. Returns the reasons to refuse."""
    declared = plan.get("reader_eq") or {}
    reader_of = plan.get("reader_voices") or {}
    bad, worst, voices = [], 0.0, {}
    for pl in placed["lines"]:
        lid = pl["id"]
        if pl["kind"] == "archival":
            if lid in rd_lines:
                bad.append(f"{lid} is archival audio and was EQ'd")
            continue
        if lid not in reader_of:
            continue
        k = reader_of[lid]
        want, rec = declared.get(k), rd_lines.get(lid)
        v = voices.setdefault(k, {"eq": want, "lines": 0, "relevel_db": {}})
        got = None if rec is None else rec.get("eq")
        if got != want:
            bad.append(f"{lid} ({k}) was EQ'd with {got}, not the declared {want}")
            continue
        if rec is None:
            continue
        v["lines"] += 1
        v["relevel_db"][lid] = rec["relevel_db"]
        for c in rec["response"]:
            if c.get("error_db") is None:
                continue
            worst = max(worst, c["error_db"])
            if c["error_db"] > SC.NARRATOR_EQ_TOL_DB:
                bad.append(f"{lid} ({k}) {c['band']} {c['measured_db']:+.2f} dB, declared {c['declared_db']:+.2f}")
    if not voices and not bad:
        return []
    journal.lint("reader-eq", not bad, stage="assembly", phase="preflight", unit="readers", grammar="A38 refined",
                 severity="warn" if draft else "block",
                 evidence={"declared": plan.get("reader_eq_declared"), "table_sha": plan.get("reader_eq_table"),
                           "voices": voices, "worst_error_db": round(worst, 3), "tol_db": SC.NARRATOR_EQ_TOL_DB,
                           "off_lines": bad[:20], "archival": "never EQ'd"})
    return bad


def derived_voice_ceiling(lift_db: float) -> tuple[float, float, str | None]:
    """A15 refined (E14): the voice ceiling for a programme whose mix needs
    ``lift_db`` to reach TARGET_LUFS: the master limiter's ceiling
    (TARGET_TP - LIMIT_MARGIN_DB, -2.0 dBTP) less the lift less
    VOICE_CEILING_SAFETY_DB, clamped to [VOICE_TP_FLOOR, VOICE_TP]. Returns the
    ceiling, the unclamped value and which bound held it ("upper", "floor" or None)."""
    raw = round(TARGET_TP - LIMIT_MARGIN_DB - lift_db - VOICE_CEILING_SAFETY_DB, 2)
    if raw >= VOICE_TP:
        return VOICE_TP, raw, "upper"
    if raw <= VOICE_TP_FLOOR:
        return VOICE_TP_FLOOR, raw, "floor"
    return raw, raw, None


def _trial_master(mix: np.ndarray, work: Path | None) -> dict:
    """E14 pass 1: the loudness pass (loudnorm, with its true-peak limiter)
    on a trial copy of the mix, in a temporary folder, so the voice ceiling
    is judged by the same limiter-peak-only rule as the master."""
    import soundfile as sf
    if work is not None:
        work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mix-pass1-", dir=None if work is None else str(work)) as td:
        src = Path(td) / "mix-pass1.wav"
        sf.write(str(src), mix, AUDIO_RATE, subtype="FLOAT")
        return loudnorm(src, Path(td) / "mix-pass1-norm.wav")


def _master_overreach(mix: np.ndarray, predicted_tp: float, work: Path | None) -> tuple[list[str], dict | None]:
    """E14: how the master's true-peak limiter would go past peak control on
    this mix (limiter_overreach on a trial loudness pass), and its numbers.
    No trial is run when the gain leaves the true peak under TARGET_TP."""
    if predicted_tp <= TARGET_TP:
        return [], None
    lim = _trial_master(mix, work).get("limiter")
    ev = None if not lim else {k: lim[k] for k in ("max_reduction_db", "max_at_s", "over_1db_s", "lra_drop",
                                                    "ceiling_dbtp", "acted_s", "acted_total")}
    return (limiter_overreach(lim) if lim else []), ev


def _held_gain(db: float, tp: float | None, ceiling: float) -> float:
    """A fixed gain held back so a true peak ``tp`` stays under ``ceiling``; never raised."""
    return db if tp is None or not math.isfinite(tp) or db <= ceiling - tp else ceiling - tp


def _mix_at(parts: list[dict], ceiling: float, n: int, clips: np.ndarray, music: np.ndarray,
            amb: np.ndarray, duck: np.ndarray | None = None) -> tuple[np.ndarray, dict]:
    """E14: place every voice part again under ``ceiling``: synthetic lines
    peak-controlled (A13) from their levelled take, archival spans and
    archival files at one static gain held to it (A26; never limited).
    Returns the mix and, per part, what was placed."""
    voice = np.zeros(n, np.float32)
    got = {}
    for k, p in enumerate(parts):
        if p["kind"] == "synthetic":
            y, peak = voice_peak_control(p["x0"], ceiling)
            got[k] = {"x": y, "db": p["db"], "peak": peak}
        elif p["kind"] == "archival":
            got[k] = {"x": p["x"], "db": _archival_total(p["gain"], p["m"], p["line_gain"], ceiling)}
        elif p["kind"] == "archival-file":
            if "tp" not in p:
                p["tp"] = _measure_line(p["x"])["input_tp"] if len(p["x"]) else None
            got[k] = {"x": p["x"], "db": _held_gain(p["db"], p["tp"], ceiling)}
        else:
            got[k] = {"x": p["x"], "db": p["db"]}
        _place(voice, got[k]["x"], p["at_s"], got[k]["db"])
    # A29: pass 1's duck (its lines' spans and the film's hold) when given; pass 2 only re-peaks the same lines
    return (voice + clips + music * (duck_gain(voice) if duck is None else duck) + amb).astype(np.float32), got


def voice_ceiling_pass(mix: np.ndarray, parts: list[dict], clips: np.ndarray, music: np.ndarray, amb: np.ndarray,
                       placed: dict, journal: Journal, *, draft: bool = False, work: Path | None = None,
                       duck: np.ndarray | None = None) -> np.ndarray | None:
    """A15 refined (E14): measure pass 1's mix (its integrated loudness, so
    the lift to TARGET_LUFS) and, when that gain would push its true peak past
    TARGET_TP, run the loudness pass on a trial copy. Only when that master's
    limiter would do more than catch peaks (limiter_overreach) is a second
    pass made: every synthetic line is peak-controlled again (A13) to the
    derived ceiling (derived_voice_ceiling), and every archival line's one
    static gain (A26: a span or its own file) is held to it, since nothing may
    limit it. If pass 2's measured lift lowers the ceiling by more than
    VOICE_CEILING_TOL_DB, a third pass places the voices once more at the
    re-estimate; never more (the master's limiter-peak-only lint then judges
    it). A mix that passes is returned as None (kept, sample for sample).
    Journals one ``voice-ceiling`` decision: the lift, each pass's ceiling,
    pass 1's limiter and each line's change. A bad take at the final ceiling
    (A13) is refused, a warning under --draft."""
    m = _measure(mix)
    if not math.isfinite(m["input_i"]) or m["input_i"] < -70:
        journal.decision("assembly", f"voice ceiling kept at {VOICE_TP:g} dBTP: silent programme",
                         "A15 refined (E14): the mix is too quiet to measure, so it has no lift to derive a ceiling from; one pass",
                         unit="voice-ceiling", evidence={"pass1": {"input_i": m["input_i"], "input_tp": m["input_tp"]},
                                                         "passes": 1, "reason": "silent programme"})
        return None
    lift = round(TARGET_LUFS - m["input_i"], 2)
    predicted = round(m["input_tp"] + lift, 2)
    ceiling, raw, bound = derived_voice_ceiling(lift)
    ev = {"pass1": {"input_i": m["input_i"], "input_tp": m["input_tp"], "input_lra": m["input_lra"]}, "lift_db": lift,
          "predicted_tp": predicted, "master_tp": TARGET_TP, "limiter_margin_db": LIMIT_MARGIN_DB,
          "safety_db": VOICE_CEILING_SAFETY_DB, "derived_ceiling_raw_dbtp": raw, "derived_ceiling_dbtp": ceiling,
          "bound": bound, "bounds": {"floor": VOICE_TP_FLOOR, "upper": VOICE_TP}}
    over, ev["pass1_limiter"] = _master_overreach(mix, predicted, work)
    ev["pass1_overreach"] = over
    adjustable = any(p["kind"] in ("synthetic", "archival", "archival-file") for p in parts)
    if not over or ceiling >= VOICE_TP or not adjustable:
        why = ("the gain to the target leaves the true peak under the master ceiling" if not ev["pass1_limiter"] else
               "the master limiter only catches peaks (limiter-peak-only)" if not over else
               f"the derived ceiling {raw:g} dBTP is held at the upper bound {VOICE_TP:g}, so the voices are not the cause"
               if ceiling >= VOICE_TP else "no synthetic or archival line to bring down")
        journal.decision("assembly", f"voice ceiling kept at {VOICE_TP:g} dBTP: the mix is {m['input_i']:.2f} LUFS, a "
                         f"{lift:+.2f} dB lift to {TARGET_LUFS:g}", f"A15 refined (E14): {why}; one pass",
                         unit="voice-ceiling", evidence=dict(ev, passes=1))
        return None
    passes = [{"pass": 1, "ceiling_dbtp": VOICE_TP, "input_i": m["input_i"], "lift_db": lift}]
    while True:
        out, got = _mix_at(parts, ceiling, len(mix), clips, music, amb, duck)
        mn = _measure(out)
        lift_n = round(TARGET_LUFS - mn["input_i"], 2)
        nxt, nraw, nbound = derived_voice_ceiling(lift_n)
        passes.append({"pass": len(passes) + 1, "ceiling_dbtp": ceiling, "bound": bound, "input_i": mn["input_i"],
                       "input_tp": mn["input_tp"], "input_lra": mn["input_lra"], "lift_db": lift_n,
                       "predicted_tp": round(mn["input_tp"] + lift_n, 2), "next_estimate_dbtp": nraw})
        if len(passes) >= VOICE_CEILING_PASSES or nxt >= ceiling - VOICE_CEILING_TOL_DB:
            break
        ceiling, raw, bound = nxt, nraw, nbound
    changes, bad = [], []
    for k, p in enumerate(parts):
        g, line = got[k], placed["lines"][p["i"]] if "i" in p else None
        if p["kind"] == "fixed":
            continue
        h, core = p.get("core") or (0, len(g["x"]))     # A36: an archival span's words are its core, not its edges
        at_core = p["at_s"] + h / AUDIO_RATE
        k_n = int(min(core, len(g["x"]) - h, max(0, len(mix) - int(round(at_core * AUDIO_RATE)))))
        act = speech_active(g["x"][h:h + k_n], g["db"])
        line.update(voice_ceiling_dbtp=ceiling,
                    speech_from_s=None if not len(act) else round(at_core + act[0] / AUDIO_RATE, 3),
                    speech_to_s=None if not len(act) else round(at_core + (act[-1] + 1) / AUDIO_RATE, 3))
        if p["kind"] == "synthetic":
            peak = g["peak"]
            if peak:
                _journal_peak(journal, p["id"], peak, draft, ceiling)
                if peak["bad_take"]:
                    bad.append(f"{p['id']} ({'; '.join(peak['bad_take'])})")
            p1 = p["peak"]["max_reduction_db"] if p["peak"] else None
            p2 = peak["max_reduction_db"] if peak else None
            line["peak_reduction_db"] = p2
            if p1 != p2:
                changes.append({"id": p["id"], "kind": "synthetic", "pass1_max_reduction_db": p1, "final_max_reduction_db": p2,
                                "pass1_over_1db_s": p["peak"]["over_1db_s"] if p["peak"] else 0.0,
                                "final_over_1db_s": peak["over_1db_s"] if peak else 0.0,
                                "tp_levelled_dbtp": (peak or p["peak"] or {}).get("tp_before")})
        else:
            before = p["total"] if p["kind"] == "archival" else p["db"]
            line["static_gain_db"] = round(g["db"], 2)
            if round(g["db"], 2) != round(before, 2):
                changes.append({"id": p["id"], "kind": p["kind"], "pass1_static_gain_db": round(before, 2),
                                "final_static_gain_db": round(g["db"], 2),
                                "measured_tp": p["m"].get("input_tp") if p["kind"] == "archival" else p.get("tp")})
    last = passes[-1]
    ev.update(passes=len(passes), pass_log=passes, final_ceiling_dbtp=ceiling, changes=changes, lines_changed=len(changes))
    journal.decision("assembly", f"voice ceiling derived at {ceiling:g} dBTP ({len(passes)} passes): the mix was "
                     f"{m['input_i']:.2f} LUFS, a {lift:+.2f} dB lift to {TARGET_LUFS:g}; {len(changes)} lines changed",
                     f"A15 refined (E14): on pass 1 the master limiter would have done more than catch peaks "
                     f"({'; '.join(over)}); the ceiling is {TARGET_TP:g} dBTP - {LIMIT_MARGIN_DB:g} dB (the master limiter's "
                     f"margin) - the lift - {VOICE_CEILING_SAFETY_DB:g} dB, clamped to {VOICE_TP_FLOOR:g} to {VOICE_TP:g}"
                     + (f" (held at the {bound} bound)" if bound else "")
                     + "; synthetic lines peak-controlled to it again (A13), archival lines' static gain held to it (A26, "
                     f"never limited); the final mix is {last['input_i']:.2f} LUFS, a {last['lift_db']:+.2f} dB lift",
                     unit="voice-ceiling", evidence=ev)
    if bad and not draft:
        raise Refused(f"voice-peak-control (A13, A15 refined): bad takes at the derived voice ceiling {ceiling:g} dBTP, "
                      f"re-render them instead of crushing them: {'; '.join(bad)}")
    return out


def _archival_total(gain: float | None, m: dict, line_gain: float, ceiling: float = VOICE_TP) -> float:
    """A26: an archival span's static gain plus its line's gain_db, held back so
    its true peak stays under the voice ceiling (A15's, or pass 2's derived one)."""
    total = (gain or 0.0) + line_gain
    tp = m.get("input_tp")
    if tp is not None and math.isfinite(tp) and total > ceiling - tp:      # nothing limits it, so the gain is held back
        total = ceiling - tp
    return total


def archival_gain(x: np.ndarray) -> tuple[float | None, dict]:
    """A26: the one static gain that brings an archival span to the dialogue
    level (ARCHIVAL_DIALOGUE_LUFS), held back so its true peak stays under the
    voice ceiling (VOICE_TP, A15), since nothing may limit it. None when the
    span is too quiet to measure. Dynamics are never touched."""
    g, m = level_gain(x, ARCHIVAL_DIALOGUE_LUFS)
    if g is None:
        return None, m
    held = math.isfinite(m.get("input_tp", float("nan"))) and m["input_tp"] + g > VOICE_TP
    gain = (VOICE_TP - m["input_tp"]) if held else g
    return gain, dict(m, target_gain_db=round(g, 2), held_by_peak=held)


# A36 (R12; founder: "in some places there is sudden silence after old footage (noise disappears abruptly)"): an
# archival segment (an archival line's span, or a clip shot playing its own sound) never starts or ends on a hard cut
# of its noise floor. Each edge carries the reel's own sound on past the cut, where the reel has no speech there and
# nothing else is placed, and fades it over EDGE_FADE_S (EDGE_LONG_S where silence follows or precedes), on the house
# sine in-out in dB down to EDGE_DEPTH_DB under its level, so the noise eases away at the rate a room decays rather
# than in one 20 ms step. Where the reel speaks too soon after the out point, the fade starts inside the span's own
# A33 tail (after the last word and its decay, EDGE_GUARD_AFTER_S, A19's speech extent), so it is at least EDGE_MIN_S
# long where there is room; the reel's next word (less EDGE_GUARD_BEFORE_S for its onset) is never carried. Two segments
# of one reel whose gap keeps their source timing, with no speech and no voice line in it, are joined: the reel's
# sound plays through the gap at its own level. archival-sound-edge refuses an edge whose noise floor still steps by
# more than EDGE_STEP_MAX_DB within 50 ms (edge_steps: the edit's own step, the reel's own changes and words set aside).
# Calibration (R12, The Next Village, r-20261011-204507): its 9 archival spans and 3 own-sound clips have 24 edges.
# As cut before R12 (A26's 20 ms fade, own sound cut hard), the 22 with a floor under them stepped 20.1 to 56.7 dB in
# 50 ms (the other 2 sat on the reel's own digital silence); on the master's mix their 50 ms steps were 30.7 to
# 71.6 dB. Planned by A36, the 21 edges with room step 3.6 to 13.5 dB; 3 are speech-bound (the reel speaks on both
# sides of the cut: 21.2 to 24.6 dB), a warning and a reviewer item. A sine-dB fade steps 7.9 dB at 0.6 s, 11.8 at 0.4.
EDGE_FADE_S = 0.6
EDGE_LONG_S = 1.5
EDGE_MIN_S = 0.4
EDGE_DEPTH_DB = 60.0
EDGE_GUARD_AFTER_S, EDGE_GUARD_BEFORE_S = 0.060, 0.040   # A19's speech extent: a word's decay, a word's onset
EDGE_PAD_S = 1.6                    # the reel read either side of a segment, so an edge can carry on past its cut
EDGE_JOIN_MAX_S = 3.0               # a gap this short between two segments of one reel in step may be joined
EDGE_STEP_MAX_DB = 15.0
EDGE_FLOOR_DBFS = -80.0
EDGE_WIN_S, EDGE_HOP_S = 0.050, 0.010


def edge_gain(n: int, *, rising: bool) -> np.ndarray:
    """A36: n samples of gain on the sine in-out in dB, from -EDGE_DEPTH_DB
    to 0 (rising) or from 0 to -EDGE_DEPTH_DB."""
    if n <= 0:
        return np.ones(0, np.float32)
    u = (np.arange(n) + 0.5) / n
    db = -EDGE_DEPTH_DB * (0.5 + 0.5 * np.cos(np.pi * u)) if rising else -EDGE_DEPTH_DB * (0.5 - 0.5 * np.cos(np.pi * u))
    return (10 ** (db / 20)).astype(np.float32)


def reel_audio(src, a: float, b: float) -> np.ndarray:
    """A reel's sound from a to b (its own time, a >= 0), mono 48 kHz float."""
    r = subprocess.run([ffmpeg(), "-v", "error", "-filter_threads", "1", "-threads", "1", "-ss", f"{max(0.0, a):.4f}",
                        "-t", f"{max(0.0, b - a):.4f}", "-i", str(src), "-vn", "-ac", "1", "-ar", str(AUDIO_RATE),
                        "-f", "f32le", "-"], capture_output=True)
    if r.returncode:
        return np.zeros(0, np.float32)
    return np.frombuffer(r.stdout, dtype=np.float32).copy()


def archival_segments(plan: dict, film: Path) -> list[dict]:
    """A36: every archival segment the mix places, in time order, with the
    reel's sound read EDGE_PAD_S either side and its speech runs: each
    archival line's span (at its A33(1b)-corrected start) and each clip shot
    that plays its own sound."""
    segs = []
    for ln in plan["lines"]:
        if not archival_span(ln):
            continue
        item = plan["assets"].get(ln["clip"]) or {}
        in_s, out_s = float(ln["in_s"]), float(ln["out_s"])
        sp = cached_span(film, item["_path"], in_s, out_s, video=False, pad_s=EDGE_PAD_S)
        t_in = float(ln["start_s"]) - CL.av_correction_s(item)
        segs.append({"id": ln["id"], "kind": "span", "asset": ln["clip"], "src_in": in_s, "src_out": out_s, "t_in": t_in,
                     "t_out": t_in + out_s - in_s, "x": _read_wav(Path(sp["file"])), "x0": float(sp["offset_s"]),
                     "span": sp, "ln": ln})
    for s in plan["shots"]:
        if not (s["kind"] == "archive_video" and (s.get("sound") or {}).get("mode", "own") == "own"
                and s["_video"]["probe"]["has_audio"]):
            continue
        src, base = clip_file(s)
        t_in, t_out = s["f0"] / FPS, s["f1"] / FPS
        src_in = float(s["in_s"])
        a = max(base, src_in - EDGE_PAD_S)
        x = reel_audio(src, a - base, src_in + (t_out - t_in) + EDGE_PAD_S - base)
        segs.append({"id": s["id"], "kind": "own", "asset": s.get("asset"), "src_in": src_in,
                     "src_out": src_in + (t_out - t_in), "t_in": t_in, "t_out": t_out, "x": x, "x0": a, "shot": s})
    for g in segs:
        g["runs"] = CL.speech_runs(g["x"], g["x0"], sr=AUDIO_RATE)[0] if len(g["x"]) else []
        g["x_end"] = g["x0"] + len(g["x"]) / AUDIO_RATE
        g["head"] = g["tail"] = None
    return sorted(segs, key=lambda g: (g["t_in"], g["id"]))


def _voice_intervals(plan: dict, film: Path) -> list[tuple[float, float, str]]:
    out = []
    for ln in plan["lines"]:
        if archival_span(ln) or ln.get("kind") not in VOICE_KINDS:
            continue
        w = voice_wav(film, ln)
        if w.exists():
            out.append((float(ln["start_s"]), float(ln["start_s"]) + wav_seconds(w), ln["id"]))
    return out


def plan_edges(segs: list[dict], plan: dict, film: Path) -> None:
    """A36: each segment's ``head`` and ``tail``: how far the reel's sound
    carries past the cut (``ext``), how long the fade is (``fade``, of which
    ``inside`` lies within the segment) and why, or ``joined`` to the
    neighbouring segment of the same reel."""
    voices = _voice_intervals(plan, film)
    music = []
    for c in plan.get("cues", []):
        tk = c.get("_take")              # A29 take: the take plays music only in its spans; its rests are the room
        music += [(s["start_s"], s["end_s"]) for s in tk["spans"]] if tk else [(float(c["start_s"]), float(c["end_s"]))]

    def others(g: dict) -> list[tuple[float, float]]:
        return [(v[0], v[1]) for v in voices] + [(h["t_in"], h["t_out"]) for h in segs if h is not g]

    def quiet(a: float, b: float, g: dict) -> bool:
        return not any(x0 < b and x1 > a for x0, x1 in others(g) + music)

    for i, g in enumerate(segs):
        nxt = segs[i + 1] if i + 1 < len(segs) else None
        gap = nxt["t_in"] - g["t_out"] if nxt else None
        if (nxt is not None and nxt["asset"] == g["asset"] and 0.0 <= gap <= EDGE_JOIN_MAX_S
                and abs(gap - (nxt["src_in"] - g["src_out"])) <= 1.0 / FPS
                and not any(a < nxt["src_in"] and b > g["src_out"] for a, b in g["runs"])
                and not any(v0 < nxt["t_in"] and v1 > g["t_out"] for v0, v1, _ in voices)
                and g["x_end"] >= nxt["src_in"] - 1e-3):
            g["tail"] = {"joined": nxt["id"], "ext": round(gap, 4), "fade": 0.0, "inside": 0.0}
            nxt["head"] = {"joined": g["id"], "ext": 0.0, "fade": 0.0, "inside": 0.0}
            continue
        g["tail"] = _edge(g, "tail", quiet(g["t_out"], g["t_out"] + EDGE_LONG_S, g), others(g))
    for g in segs:
        if g["head"] is None:
            g["head"] = _edge(g, "head", quiet(g["t_in"] - EDGE_LONG_S, g["t_in"], g), others(g))


def _edge(g: dict, side: str, silent: bool, others: list[tuple[float, float]]) -> dict:
    """A36: one edge's plan (see plan_edges)."""
    want = EDGE_LONG_S if silent else EDGE_FADE_S
    if side == "tail":
        nxt_speech = min([a for a, b in g["runs"] if a >= g["src_out"] - 1e-3] or [math.inf])
        avail_src = min(nxt_speech - EDGE_GUARD_BEFORE_S, g["x_end"]) - g["src_out"]
        avail_t = min([a for a, b in others if a >= g["t_out"] - 1e-6] or [math.inf]) - g["t_out"]
        last = max([b for a, b in g["runs"] if a < g["src_out"] - 1e-3] or [g["src_in"]])
        room_in = g["src_out"] - max(g["src_in"], min(g["src_out"], last + EDGE_GUARD_AFTER_S))
    else:
        prv_speech = max([b for a, b in g["runs"] if b <= g["src_in"] + 1e-3] or [-math.inf])
        avail_src = g["src_in"] - max(prv_speech + EDGE_GUARD_AFTER_S, g["x0"])
        avail_t = g["t_in"] - max([b for a, b in others if b <= g["t_in"] + 1e-6] or [-math.inf])
        first = min([a for a, b in g["runs"] if b > g["src_in"] + 1e-3] or [g["src_out"]])
        room_in = min(g["src_out"], max(g["src_in"], first - EDGE_GUARD_BEFORE_S)) - g["src_in"]
    room_in = max(0.0, room_in)
    ext = max(0.0, min(want, avail_src, avail_t))
    if ext >= EDGE_MIN_S - 1e-9:
        inside = 0.0
    else:
        inside = min(EDGE_MIN_S - ext, room_in)
        if ext + inside < 2 * ARCHIVAL_FADE_S:      # no room at all: A26's 20 ms fade, so the cut never clicks
            inside = min(ARCHIVAL_FADE_S, room_in)
    limit = ("wanted" if ext >= want - 1e-9 else "the reel speaks or ends" if avail_src <= min(want, avail_t) + 1e-9
             else "another sound is placed")
    return {"ext": round(ext, 4), "fade": round(ext + inside, 4), "inside": round(inside, 4), "wanted": want,
            "silence": silent, "limited_by": limit}


def segment_audio(g: dict) -> tuple[np.ndarray, int, int]:
    """A36: the segment's sound with its edges: the reel from in - head ext
    to out + tail ext, the head and tail fades on it. Returns it, the
    samples before the core (the head's ext) and the core's length."""
    lo, hi = g["src_in"] - g["head"]["ext"], g["src_out"] + g["tail"]["ext"]
    i0 = max(0, int(round((lo - g["x0"]) * AUDIO_RATE)))
    i1 = max(i0, int(round((hi - g["x0"]) * AUDIO_RATE)))
    y = np.zeros(i1 - i0, np.float32)
    got = g["x"][i0:i1]
    y[: len(got)] = got
    h = int(round(g["head"]["ext"] * AUDIO_RATE))
    core = int(round((g["src_out"] - g["src_in"]) * AUDIO_RATE))
    for side in ("head", "tail"):
        e = g[side]
        n = min(len(y), int(round(e["fade"] * AUDIO_RATE)))
        if e.get("joined") or n <= 0:
            continue
        if side == "head":
            y[:n] *= edge_gain(n, rising=True)
        else:
            y[len(y) - n:] *= edge_gain(n, rising=False)
    return y, h, core


def stem_window(parts, i0: int, i1: int, *, skip: str | None = None) -> np.ndarray:
    """The archival stem from sample i0 to i1, summed from its placed parts
    ((start sample, sound, gain dB, segment id)), without holding a
    film-long buffer; ``skip`` leaves one segment out."""
    out = np.zeros(max(0, i1 - i0), np.float64)
    for st, y, db, sid in parts:
        if sid == skip:
            continue
        a, b = max(i0, st), min(i1, st + len(y))
        if b > a:
            out[a - i0: b - i0] += y[a - st: b - st] * 10 ** (db / 20)
    return out


def _levels(x: np.ndarray) -> np.ndarray:
    w, hop = int(EDGE_WIN_S * AUDIO_RATE), int(EDGE_HOP_S * AUDIO_RATE)
    fr = np.lib.stride_tricks.sliding_window_view(x, w)[::hop]
    return np.maximum(10 * np.log10(np.mean(fr * fr, axis=1) + 1e-20), EDGE_FLOOR_DBFS)


def edge_steps(parts, segs: list[dict]) -> list[dict]:
    """A36, archival-sound-edge: the step the edit puts into the reel's sound
    at each edge that is not joined. Across the fade and 100 ms past it, on
    50 ms windows every 10 ms, the edited stem's level and the level the reel
    would have had playing on unedited (the same segment, the same gain, no
    fade, no cut), each floored at EDGE_FLOOR_DBFS. The step is the edited
    level's change within 50 ms in the fade's direction (a fall at a tail, a
    rise at a head) less the reel's own change that way, so a fall the reel
    makes by itself (its own silence) is not the edit's. Windows over the
    reel's speech are left out: a word the edit deliberately does not carry
    (the next speaker, the previous sentence) is not its noise floor.
    ``parts``: (start sample, sound, gain dB, segment id) for every placed
    archival segment."""
    out = []
    k = int(round(EDGE_WIN_S / EDGE_HOP_S))
    gains = {sid: db for _, _, db, sid in parts}
    for g in segs:
        for side in ("head", "tail"):
            e = g[side]
            if e is None or e.get("joined") or g["id"] not in gains:
                continue
            if side == "tail":
                end = g["t_out"] + e["ext"]
                a, b = end - e["fade"] - EDGE_WIN_S, end + 0.1
            else:
                start = g["t_in"] - e["ext"]
                a, b = start - 0.1, start + e["fade"] + EDGE_WIN_S
            i0, i1 = max(0, int(round(a * AUDIO_RATE))), int(round(b * AUDIO_RATE))
            if i1 - i0 < int(EDGE_WIN_S * AUDIO_RATE) + k * int(EDGE_HOP_S * AUDIO_RATE):
                continue
            edited = stem_window(parts, i0, i1)
            reel_at = int(round((g["t_in"] - (g["src_in"] - g["x0"])) * AUDIO_RATE))
            unedited = stem_window(parts, i0, i1, skip=g["id"]) + stem_window([(reel_at, g["x"], gains[g["id"]], g["id"])], i0, i1)
            le, lu = _levels(edited), _levels(unedited)
            t0 = i0 / AUDIO_RATE + np.arange(len(le)) * EDGE_HOP_S - g["t_in"] + g["src_in"]   # each window in reel time
            words = np.zeros(len(le), bool)
            for ra, rb in g["runs"]:
                words |= (t0 < rb) & (t0 + EDGE_WIN_S > ra)
            sign = 1.0 if side == "tail" else -1.0                    # a fall at a tail, a rise at a head
            de, du = sign * (le[:-k] - le[k:]), sign * (lu[:-k] - lu[k:])
            d = np.where(words[k:] | words[:-k], -np.inf, de - np.maximum(du, 0.0))
            if not np.isfinite(d).any():
                continue
            i = int(np.argmax(d))
            out.append({"segment": g["id"], "kind": g["kind"], "edge": side,
                        "at_s": round(g["t_out"] if side == "tail" else g["t_in"], 3), "step_db": round(float(d[i]), 1),
                        "step_at_s": round(a + i * EDGE_HOP_S, 3), "plan": e,
                        "reel_dbfs": round(float(np.percentile(_levels(unedited), 50)), 1),
                        "speech_bound": e.get("limited_by") == "the reel speaks or ends" and e["fade"] < EDGE_MIN_S - 1e-9})
    return out


def archival_edge_lints(journal: Journal, parts: list, segs: list[dict], *, draft: bool = False) -> list[str]:
    """A36: archival-sound-edge, one lint per segment edge, on the archival
    stem as placed (``parts``, as edge_steps reads them). A step over
    EDGE_STEP_MAX_DB is refused on a final render (a warning under --draft),
    except at a speech-bound edge (the reel speaks on both sides of the cut,
    so no speech-safe fade of EDGE_MIN_S fits): that is a warning and a
    reviewer item, since only a different cut can give it room. Returns the
    reasons to refuse."""
    out = []
    for st in edge_steps(parts, segs):
        ok = st["step_db"] <= EDGE_STEP_MAX_DB + 1e-9
        bound = not ok and st["speech_bound"]
        unit = f"{st['segment']}:{st['edge']}"
        journal.lint("archival-sound-edge", ok, stage="assembly", phase="preflight", unit=unit,
                     severity="warn" if draft or bound else "block", grammar="8.5, A26, A36",
                     evidence=dict(st, max_step_db=EDGE_STEP_MAX_DB, window_s=EDGE_WIN_S, floor_clip_dbfs=EDGE_FLOOR_DBFS,
                                   fix=None if ok else (
                                       "the reel speaks right at this cut, so no speech-safe fade fits: a cut in a "
                                       "longer pause gives it room" if bound else
                                       "the reel's sound stops in one step: give the edge room (move the next sound "
                                       "later, or cut in a pause)")))
        if bound:
            journal.lint("archival-sound-edge", True, stage="assembly", phase="preflight", unit=unit, severity="review",
                         grammar="A36", evidence={"check": "a speech-bound edge: hear whether the cut sounds abrupt",
                                                  "step_db": st["step_db"], "plan": st["plan"]})
        elif not ok and not draft:
            out.append(f"{st['segment']} {st['edge']} steps {st['step_db']:g} dB in 50 ms")
    joined = [{"from": g["id"], "to": g["tail"]["joined"], "gap_s": g["tail"]["ext"]} for g in segs
              if g["tail"] and g["tail"].get("joined")]
    if joined:
        journal.decision("assembly", f"{len(joined)} archival gaps joined: the reel plays through at its own level",
                         "A36: two segments of one reel in step, with no speech and no voice in the gap", unit="archival",
                         evidence={"joined": joined})
    return out


def place_archival_span(voice: np.ndarray, plan: dict, film: Path, journal: Journal, ln: dict,
                        stash: list | None = None, seg: dict | None = None,
                        arch: list | None = None) -> tuple[int, np.ndarray, float]:
    """A26 (E11): place an archival line from its clip's own soundtrack. The
    span is cut from the source once into the span cache (a long reel is
    never read whole), brought to the archival dialogue level by one static
    gain measured on the span itself (plus the line's own ``gain_db``, if
    any), and placed. A36: its edges carry the reel's sound past the cut and
    fade it (``seg``, from plan_edges; without one, A26's 20 ms fades). Never
    cleaned (A19), never peak controlled (A13), never judged as the narrator
    (A14). Returns the span's samples, its speech-active samples and the
    gain. ``stash`` keeps what pass 2 (A15 refined, E14) needs to place it
    again under a derived ceiling; ``arch`` receives it too (the archival
    stem archival-sound-edge reads)."""
    item = plan["assets"].get(ln["clip"]) or {}
    in_s, out_s = float(ln["in_s"]), float(ln["out_s"])
    if seg is None:
        sp = cached_span(film, item["_path"], in_s, out_s, video=False)
        core_x = _read_wav(Path(sp["file"]))[: int(round((out_s - in_s) * AUDIO_RATE))]
        x, h, core = cue_fades(core_x, out_s - in_s, ARCHIVAL_FADE_S, ARCHIVAL_FADE_S), 0, len(core_x)
    else:
        sp = seg["span"]
        x, h, core = segment_audio(seg)
    # the level is the span's own, measured as A26 cut it (20 ms fades), whatever its edges carry
    gain, m = archival_gain(cue_fades(x[h:h + core], out_s - in_s, ARCHIVAL_FADE_S, ARCHIVAL_FADE_S))
    line_gain = float(ln.get("gain_db", 0.0) or 0.0)
    total = _archival_total(gain, m, line_gain)
    journal.decision("assembly", f"{ln['id']} plays {ln['clip']} {in_s:.2f} to {out_s:.2f} s at its own dynamics, "
                     f"{total:+.2f} dB", "A26: an archival span is brought to "
                     f"{ARCHIVAL_DIALOGUE_LUFS:g} LUFS by one static gain (held back to the voice ceiling, never limited), "
                     "never cleaned; A36: its edges carry the reel's own sound past the cut and fade it", unit=ln["id"],
                     evidence={"span": sp, "measured": m, "static_gain_db": None if gain is None else round(gain, 2),
                               "line_gain_db": ln.get("gain_db"), "cleaned": False, "limited": False,
                               "edges": None if seg is None else {"head": seg["head"], "tail": seg["tail"]}})
    # A33(1b): a clip whose lip-measured offset lies outside BT.1359's window is put back on its picture by placing the
    # span earlier (sound late) or later (sound early); the words and their edges are the span's own, never re-cut
    corr = CL.av_correction_s(item)
    at = float(ln["start_s"]) - corr
    if corr:
        journal.decision("assembly", f"{ln['id']} placed {corr * 1000:+.0f} ms against its screenplay start ({at:.3f} s)",
                         f"A33(1b): {ln['clip']}'s av_offset_ms {item.get('av_offset_ms')} lies outside "
                         f"{-CL.AV_LEAD_MAX_MS:g} to +{CL.AV_LAG_MAX_MS:g} ms; corrected by the offset less the envelope's "
                         f"natural {CL.LIPS_NATURAL_LAG_MS:g} ms lag", unit=ln["id"],
                         evidence={"av_offset_ms": item.get("av_offset_ms"), "correction_s": corr,
                                   "measure": item.get("av_offset_measure")})
    start = at - h / AUDIO_RATE
    k = _place(voice, x, start, total)
    if arch is not None:
        arch.append((int(round(start * AUDIO_RATE)), x, total, ln["id"]))
    k_core = max(0, min(core, k - h))
    if stash is not None:
        stash.append({"kind": "archival", "id": ln["id"], "x": x, "at_s": start, "gain": gain, "m": m,
                      "line_gain": line_gain, "total": total, "core": (h, core)})
    return k_core, speech_active(x[h:h + k_core], total), round(total, 2)


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


def duck_gain(voice: np.ndarray, spans: list[tuple[float, float]] | None = None,
              hold_s: float = DUCK_BRIDGE_S) -> np.ndarray:
    """Music gain under voice (GRAMMAR 8.5): -9 dB wherever a voice speaks,
    with gaps shorter than ``hold_s`` closed (a morphological closing of
    the voice activity), so the bed holds still between words and between
    lines instead of pumping; it comes back up on a 250 ms centred ramp, and
    goes down on A37's pre-roll (about 1 s, eased in dB, full depth on the
    onset). A29: each
    of ``spans`` (a line's spoken span, first to last word) counts as voice
    throughout, so the duck holds through every pause written into a line."""
    active = (np.abs(voice) > DUCK_VOICE_THRESHOLD).astype(np.float32)
    for a, b in spans or []:
        active[max(0, int(round(a * AUDIO_RATE))): max(0, int(round(b * AUDIO_RATE)))] = 1.0
    k = int(round(hold_s * AUDIO_RATE)) | 1
    grown = (moving_average(active, k) > 1e-6).astype(np.float32)          # dilate by half the bridge on each side
    closed = (moving_average(grown, k) > 1 - 1e-6).astype(np.float32)       # erode back: only the short gaps stay filled
    closed = np.maximum(closed, active)
    env = np.clip(moving_average(closed, int(round(DUCK_SMOOTH_S * AUDIO_RATE))), 0.0, 1.0)
    g = (1.0 - env * (1.0 - 10 ** (-DUCK_DB / 20))).astype(np.float32)
    # A37 (R12): the attack is a pre-roll eased in dB over SC.DUCK_ATTACK_S, at full depth on the voice's onset
    return SC.duck_attack(g, closed, AUDIO_RATE, smooth_s=DUCK_SMOOTH_S)


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


def shortfall_values(plan: dict, placed: dict) -> dict:
    """The values a shortfall card's placeholders print: each share as the
    film measures it (voice_shares, women_share) and each floor as it sets it."""
    sh = voice_shares(plan, placed)
    women = women_share(plan, placed)
    settings = plan.get("settings") or POL.DEFAULT_SETTINGS
    return {"readings": {"share": sh["readings"], "floor": settings["readings_floor"]},
            "voiceless": {"share": sh["voiceless"], "floor": settings["voiceless_floor"]},
            "women": {"share": women["share"], "floor": settings["women_floor"], "unknown_s": women["by_gender_s"]["unknown"],
                      "unsigned_share": women["unsigned_share"], "speakers": women["speakers"]}}


def plan_has_placeholders(plan: dict) -> bool:
    """Any placeholder on a card or in a subtitle cue of the plan."""
    return (any(POL.has_placeholder(x) for sh in plan["shots"] for x in sh.get("text") or [])
            or any(POL.has_placeholder(c.get("text")) for c in plan.get("subtitles", [])))


def card_values_problems(values) -> list[str]:
    """What is wrong with a card_fills ``values`` block (from a previous sources.json)."""
    if not isinstance(values, dict):
        return [f"values must be an object, not {type(values).__name__}"]
    out = []
    for what in POL.SHORTFALL_WHAT:
        v = values.get(what)
        if not isinstance(v, dict):
            out.append(f"{what}: missing")
            continue
        for k in ("share", "floor"):
            x = v.get(k)
            if isinstance(x, bool) or not isinstance(x, (int, float)) or not 0 <= float(x) <= 1:
                out.append(f"{what}.{k} must be a share from 0 to 1, not {x!r}")
        if what == "women":                       # the seconds of unstated gender travel with women's share (A3)
            x = v.get("unknown_s")
            if isinstance(x, bool) or not isinstance(x, (int, float)) or not x >= 0:
                out.append(f"women.unknown_s must be seconds, 0 or more, not {x!r}")
            if "unsigned_share" in v:             # A3 refined: optional, a share when present
                x = v["unsigned_share"]
                if isinstance(x, bool) or not isinstance(x, (int, float)) or not 0 <= float(x) <= 1:
                    out.append(f"women.unsigned_share must be a share from 0 to 1, not {x!r}")
            if "speakers" in v:
                sp = v["speakers"]
                if not isinstance(sp, dict) or any(not isinstance(sp.get(k), int) or isinstance(sp.get(k), bool) or sp.get(k) < 0
                                                   for k in ("all", "f", "m", "unsigned")):
                    out.append(f"women.speakers must give whole counts for all, f, m and unsigned, not {sp!r}")
    return out


def fills_provenance(prev: dict, master_sha256: str | None) -> str | None:
    """Why a previous sources.json's card_fills may not fill this master's
    cards, or None: it holds none, it is malformed, it describes another
    master, or it is from a partial render (the one check for --sources-only
    and for the captions)."""
    fills = prev.get("card_fills")
    values = fills.get("values") if isinstance(fills, dict) else None
    if fills is None:
        return "the previous sources.json holds no card_fills"
    probs = card_values_problems(values)
    if probs:
        return "the previous sources.json's card_fills is malformed: " + "; ".join(probs)
    if not master_sha256 or prev.get("master_sha256") != master_sha256:
        return "the previous sources.json describes another master"
    if prev.get("partial") or prev.get("until_s"):
        return "the previous sources.json is from a partial render"
    return None


def fill_cards(plan: dict, values: dict, journal: Journal) -> list[str]:
    """A25 refined: fill every placeholder in the cards and the burned
    subtitles from ``values``, before any card is drawn, and journal each
    filled card. The filled text is what the frames, the credits and
    sources.json carry; ``card_fills`` is set only when something was filled
    (a film without placeholders keeps its sources.json as it was). A
    placeholder that cannot be filled truthfully (a share that would print as
    its floor, women's share with testimony of unstated gender) or that is
    left anywhere drawn (cards, subtitles, lower thirds, overlays) refuses
    the run. Returns the ids of the shots whose text changed."""
    if not plan_has_placeholders(plan):
        left = [x["id"] for x in plan.get("lower_thirds", []) + plan.get("overlays", [])
                if any(POL.has_placeholder(t) for t in (x.get("lines") or [x.get("text")]))]
        if left:
            raise Refused(f"placeholders on {', '.join(left)}, which are drawn as written (A25 refined)")
        return []
    changed, texts = [], {}
    try:
        for s in plan["shots"]:
            if any(POL.has_placeholder(x) for x in s.get("text") or []):
                s["text"] = [POL.fill_placeholders(x, values) for x in s["text"]]
                changed.append(s["id"])
                texts[s["id"]] = s["text"]
                journal.decision("assembly", f"{s['id']} filled from the cut: {' / '.join(s['text'])}",
                                 "A25 refined: a shortfall card prints the film's own measurement, never a typed number",
                                 unit=s["id"], evidence={"values": values, "text": s["text"]})
        for c in plan.get("subtitles", []):
            if POL.has_placeholder(c.get("text")):
                c["text"] = POL.fill_placeholders(c["text"], values)
    except (POL.FillError, KeyError, TypeError, ValueError) as e:
        journal.lint("shortfall-fill", False, stage="assembly", phase="preflight", grammar="6.5, A3, A25",
                     evidence={"values": values, "why": str(e)})
        raise Refused(f"shortfall-fill (A25 refined): {e}") from None
    journal.lint("shortfall-fill", True, stage="assembly", phase="preflight", grammar="6.5, A25",
                 evidence={"values": values, "cards": texts})
    for sf in plan.get("shortfalls") or []:
        if isinstance(sf, dict) and sf.get("what") in values:
            sf["measured_cut"] = values[sf["what"]]["share"]
            sf["filled"] = texts.get(sf.get("stated_on"))
    plan["card_fills"] = {"values": values, "texts": texts}
    left = [x["id"] for x in plan["shots"] if any(POL.has_placeholder(t) for t in x.get("text") or [])]
    left += [f"subtitle {c.get('ref')}" for c in plan.get("subtitles", []) if POL.has_placeholder(c.get("text"))]
    left += [x["id"] for x in plan.get("lower_thirds", []) + plan.get("overlays", [])
             if any(POL.has_placeholder(t) for t in (x.get("lines") or [x.get("text")]))]
    if left:
        raise Refused(f"placeholders left unfilled on {', '.join(left)}")
    return changed


def women_share(plan: dict, placed: dict) -> dict:
    """GRAMMAR 6.5: women's share of the testimony seconds (read-by and
    archival, A25), each line over its speech-active span, by the gender the
    cast states (A3; never inferred). Lines whose speaker states no gender are
    counted apart."""
    by = {"f": 0.0, "m": 0.0, "unknown": 0.0}
    heard: dict = {}
    for ln in placed["lines"]:
        kind = ln.get("line_kind", "narration" if ln.get("kind") == "narration" else "testimony")
        if kind != "testimony":
            continue
        f, t = ln.get("speech_from_s", ln.get("at_s")), ln.get("speech_to_s", (ln.get("at_s") or 0) + (ln.get("dur_s") or 0))
        if f is None or t is None or t <= f:
            continue
        g = (plan.get("speakers") or {}).get(ln.get("speaker"), {}).get("gender")
        g = g if g in ("f", "m") else "unknown"
        by[g] += float(t) - float(f)
        heard.setdefault(ln.get("speaker"), g)
    total = sum(by.values())
    return {"share": round(by["f"] / total, 4) if total else 0.0, "testimony_s": round(total, 3),
            "by_gender_s": {k: round(v, 3) for k, v in by.items()},
            # A3 refined: the unsigned apart, as a share of testimony seconds and as voices heard (each speaker once)
            "unsigned_share": round(by["unknown"] / total, 4) if total else 0.0,
            "speakers": {"all": len(heard), "f": sum(1 for g in heard.values() if g == "f"),
                         "m": sum(1 for g in heard.values() if g == "m"),
                         "unsigned": sum(1 for g in heard.values() if g == "unknown")}}


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


LT_SPEAKER_S = (4.0, 6.0)       # BRAND-KIT 4 (CoS, E15): a speaker's lower third is on screen 4 to 6 s
LT_PLACE_FULL_MIN_S = 2.5       # A20(b) (CoS, E15): a place-and-date lower third is fully visible at least 2.5 s


def lower_third_times(lt: dict, W: int, H: int, fonts: M.Fonts | None = None) -> dict:
    """How long a lower third is on screen (its drawn span, A16) and how long
    it is fully visible: from its last line's settle (the last arrival's
    stagger plus `whisper`'s settle) to the start of its let-go."""
    els, _ = M.lower_third_layout(M.Layout(W, H), lt["lines"], fonts or M.Fonts(), lt["kind"], lt.get("flag"))
    last = max(e["order"] for e in els)
    shown = lt["end"] - lt["start"]
    full = (lt["end"] - M.LT["exit"]) - (lt["start"] + last * M.LT["stagger"] + M.WHISPER.settle_time())
    return {"on_screen_s": round(shown, 4), "fully_visible_s": round(full, 4), "last_arrival": last}


def lower_third_time_lints(journal: Journal, plan: dict, *, draft: bool = False) -> list[str]:
    """lower-third-time (E15): a speaker's lower third is on screen 4 to 6 s;
    a place-and-date one is fully visible at least 2.5 s. Blocking on a final
    render, a warning under --draft. Returns the reasons to refuse."""
    fonts = M.Fonts()
    out = []
    for lt in plan["lower_thirds"]:
        tm = lower_third_times(lt, plan["W"], plan["H"], fonts)
        if lt["kind"] == "place":
            ok = tm["fully_visible_s"] >= LT_PLACE_FULL_MIN_S - 1e-6
            need = f"fully visible at least {LT_PLACE_FULL_MIN_S:g} s"
        else:
            ok = LT_SPEAKER_S[0] - 1e-6 <= tm["on_screen_s"] <= LT_SPEAKER_S[1] + 1e-6
            need = f"on screen {LT_SPEAKER_S[0]:g} to {LT_SPEAKER_S[1]:g} s"
        journal.lint("lower-third-time", ok, stage="scout", phase="preflight", unit=lt["id"],
                     severity="warn" if draft else "block", grammar="9, A16, A20(b), BRAND-KIT 4",
                     evidence=dict(tm, kind=lt["kind"], rule=need, start_s=lt["start"], end_s=lt["end"],
                                   fix=None if ok else "lengthen the lower third's span (end_s), or drop it"))
        if not ok and not draft:
            out.append(f"lower-third-time ({lt['id']}: {lt['kind']} {need}; on screen {tm['on_screen_s']:g} s, "
                       f"fully visible {tm['fully_visible_s']:g} s)")
    return out


CREDITS_LAST_LINE_S = 2.0       # E15: the last credit line has been fully on screen this long when the credits shot ends

# A30 (R4): no voice over empty black. A voice over a black or card picture (a run of them) for longer than
# BLACK_VOICE_MAX_S is refused unless each such shot declares why, from this closed list; every use is journaled and
# printed on the sources page. A reading over black also carries its lower third.
BLACK_VOICE_MAX_S = 4.0
BLACK_KINDS = ("black", "card")
BLACK_INTENTS = {
    "count-of-the-dead": "A count of the dead is read over bare black (GRAMMAR 8.2, A8 rule 6).",
    "poem": "A poem or a song's words, heard whole over black.",
    "no-open-image-of-the-author": "No image of the speaker exists under an open licence, and the absence is the point.",
    "the-film-speaks": "The film's own card, read aloud.",
}
BLACK_ONLY_INTENTS = ("count-of-the-dead",)    # bare black: never on a card (its why says so)
# A30 refined (founder, 2026-10-17: "Black with nothing could mean mourning. Silence even. I don't think we
# should be saying no black at all. It should be demanded by the story, the script, and how things are
# flowing."): alongside the closed BLACK_INTENTS list (unchanged), a `black` shot (never a `card`) may instead
# declare a free-text `black_reason`: a sentence, in the story's own words, for what its black demands (mourning,
# silence, the record falling silent). A shot with a valid reason passes black-under-voice as a declared intent
# does, journaled as a reviewer item that prints the reason, never a closed-list decision.
BLACK_REASON_MIN_WORDS = 4      # a non-trivial sentence, never a single filler token padded to length
_BLACK_REASON_WORD_RE = re.compile(r"[A-Za-z']+")


def valid_black_reason(text) -> bool:
    """A30 refined: ``black_reason`` is a string of at least BLACK_REASON_MIN_WORDS of its own words; a filler
    token repeated to pad the count (its distinct words number one) does not pass."""
    if not isinstance(text, str):
        return False
    words = _BLACK_REASON_WORD_RE.findall(text)
    return len(words) >= BLACK_REASON_MIN_WORDS and len({w.lower() for w in words}) > 1


# A30 (R4): the dip budget (FOUNDER-FEEDBACK-1 section 4: Partition's 56 dips, one every 21 s, made "a lot of black").
# Over each part, at most one dip per 40 s on average (rounded up, so a short part keeps its one dip); over the film,
# at most 12 s of dip per 10 minutes.
DIP_EVERY_S = 40.0
DIP_SECONDS_PER_10MIN_MAX = 12.0
# A30 refined (founder, 2026-10-16, Partition's ambassador's cables: 47 s and 82 s of black under a reading): a reading
# whose source is a document can show the document. More than this many seconds of black under one reading is an
# advisory warning (document-over-black) suggesting the typeset page; a count of the dead keeps its bare black.
DOC_BLACK_ADVISORY_S = 10.0


def dark_voice_runs(plan: dict) -> list[dict]:
    """A30: each run of consecutive black or card shots that a voice line
    speaks over, with the seconds of voice over it (the lines' WAV lengths,
    or an archival span's cut), the lines, each shot's declared intent and,
    for a reading, the lower thirds drawn while it speaks."""
    film = Path(plan["film"])
    voice = []
    for ln in plan["lines"]:
        if ln.get("kind") not in VOICE_KINDS:
            continue
        if archival_span(ln):
            d = max(0.0, float(ln.get("out_s", 0)) - float(ln.get("in_s", 0)))
        elif voice_wav(film, ln).exists():
            d = wav_seconds(voice_wav(film, ln))
        else:
            continue
        voice.append((float(ln["start_s"]), float(ln["start_s"]) + d, ln))
    runs, cur = [], []
    for s in plan["shots"]:
        if s["kind"] in BLACK_KINDS:
            cur.append(s)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    out = []
    for run in runs:
        a, b = run[0]["f0"] / FPS, run[-1]["f1"] / FPS
        over = [(max(a, x), min(b, y), ln) for x, y, ln in voice if x < b and y > a]
        if not over:
            continue
        merged = _merge_spans([(x, y) for x, y, _ in over], a, b)
        secs = sum(y - x for x, y in merged)
        shots = []
        for s in run:
            s0, s1 = s["f0"] / FPS, s["f1"] / FPS
            sv = sum(max(0.0, min(s1, y) - max(s0, x)) for x, y in merged)
            if sv > 0:
                shots.append({"id": s["id"], "kind": s["kind"], "voice_s": round(sv, 2), "intent": s.get("intent"),
                              "reason": s.get("black_reason")})
        readings = []
        for x, y, ln in over:
            if ln.get("kind") == "testimony":
                lt = [o["id"] for o in plan.get("lower_thirds", []) if o["start"] < y and o["end"] > x]
                readings.append({"id": ln["id"], "lower_thirds": lt})
        out.append({"from_s": round(a, 3), "to_s": round(b, 3), "voice_s": round(secs, 2), "shots": shots,
                    "lines": [ln["id"] for _, _, ln in over], "readings": readings, "part": run[0]["_part"]})
    return out


def document_over_black(plan: dict) -> list[dict]:
    """A30 refined: each reading read from a document (a testimony line read
    by a voice, with a ``source``; never an archival span) that has black
    under it, with the seconds of black under its take and the shots. Black
    declared for a count of the dead (BLACK_ONLY_INTENTS) is left out."""
    film = Path(plan["film"])
    blacks = [(s["f0"] / FPS, s["f1"] / FPS, s) for s in plan["shots"]
              if s.get("kind") == "black" and s.get("intent") not in BLACK_ONLY_INTENTS]
    out = []
    for ln in plan["lines"]:
        if ln.get("kind") != "testimony" or archival_span(ln) or not ln.get("read_by") or not ln.get("source"):
            continue
        wav = voice_wav(film, ln)
        if not wav.exists():
            continue
        a = float(ln["start_s"])
        b = a + wav_seconds(wav)
        under = [(s["id"], max(0.0, min(b, y) - max(a, x))) for x, y, s in blacks if x < b and y > a]
        under = [(i, d) for i, d in under if d > 0]
        if under:
            out.append({"line": ln["id"], "source": ln.get("source"), "locator": ln.get("locator"),
                        "black_s": round(sum(d for _, d in under), 2), "read_s": round(b - a, 2),
                        "shots": [{"id": i, "black_s": round(d, 2)} for i, d in under]})
    return out


def document_over_black_lints(journal: Journal, plan: dict) -> None:
    """A30 refined: document-over-black, advisory (a warning, never a
    refusal): more than DOC_BLACK_ADVISORY_S of black under one reading from a
    document suggests the document typeset on screen instead (a quote card:
    ``quote: true`` with ``source_date``, paged with the reading, or a DRAWN
    page)."""
    for r in document_over_black(plan):
        ok = r["black_s"] <= DOC_BLACK_ADVISORY_S + 1e-9
        journal.lint("document-over-black", ok, stage="scout", phase="preflight", unit=r["line"], severity="warn",
                     grammar="A30", evidence=dict(r, max_s=DOC_BLACK_ADVISORY_S, advisory=True,
                                                  fix=None if ok else "show the document: its words typeset on quote cards "
                                                  "(quote: true, source_date) paged with the reading, or a DRAWN page; "
                                                  "black for a breath at most"))


def dip_list(plan: dict) -> list[dict]:
    return [{"id": s["id"], "part": s["_part"], "s": float(s["transition_in"].get("s", 0))}
            for s in plan["shots"] if (s.get("transition_in") or {}).get("type") == "dip"]


def part_spans(plan: dict) -> dict:
    """Each part's length in seconds, from its shots' frames, in film order."""
    out: dict = {}
    for s in plan["shots"]:
        out[s["_part"]] = out.get(s["_part"], 0.0) + (s["f1"] - s["f0"]) / FPS
    return out


def black_dip_lints(journal: Journal, plan: dict, *, draft: bool = False) -> list[str]:
    """A30 (R4), refined (founder, 2026-10-17). black-under-voice: a voice over
    a run of black or card shots for more than BLACK_VOICE_MAX_S is refused
    unless every such shot declares an intent from BLACK_INTENTS (journaled as
    a decision, printed in sources.json) or, on a black shot only, a valid
    free-text black_reason (journaled as a reviewer item that prints the
    reason); and a reading over it has a lower third. dip-budget: over
    each part at most one dip per DIP_EVERY_S on average (rounded up, so a
    short part keeps one), and over the film at most DIP_SECONDS_PER_10MIN_MAX
    seconds of dip per 10 minutes, a pacing guide (A39): a warning and a
    reviewer item, never a refusal. black-under-voice is blocking on a final
    render; a warning under --draft, --audio-only and --until (``draft``).
    Returns the reasons to refuse."""
    out = []
    sev = "warn" if draft else "block"
    document_over_black_lints(journal, plan)            # advisory: never refuses
    runs = plan["dark_voice"] if "dark_voice" in plan else dark_voice_runs(plan)
    for r in runs:
        long_ = r["voice_s"] > BLACK_VOICE_MAX_S + 1e-9
        # A30 refined: a shot passes on its closed-list intent, as before, or (black only) a valid free-text
        # black_reason; `declared` names which, so the reviewer item and the decision print the right one.
        declared = {s["id"]: ("intent" if isinstance(s.get("intent"), str) and s["intent"] in BLACK_INTENTS else
                              "reason" if s["kind"] == "black" and valid_black_reason(s.get("reason")) else None)
                    for s in r["shots"]} if long_ else {}
        missing = [sid for sid, d in declared.items() if d is None] if long_ else []
        bare = [x["id"] for x in r["readings"] if not x["lower_thirds"]] if long_ else []
        ok = not missing and not bare
        unit = r["shots"][0]["id"] if r["shots"] else r["part"]
        journal.lint("black-under-voice", ok, stage="scout", phase="preflight", unit=unit, severity=sev, grammar="8.2, A8, A30",
                     evidence=dict(r, max_s=BLACK_VOICE_MAX_S, intents=sorted(BLACK_INTENTS), no_intent=missing,
                                   readings_without_lower_third=bare,
                                   fix=None if ok else (
                                       "give the words a picture (typeset the document as a DRAWN page, or a still), or "
                                       f"declare the shot's intent from {sorted(BLACK_INTENTS)}, or a black shot's own "
                                       "black_reason" if missing else
                                       "a reading over black carries its lower third")))
        if ok and long_:
            for s in r["shots"]:
                d = declared.get(s["id"])
                if d == "intent":
                    journal.decision("scout", f"{s['id']}: a voice over {s['kind']} for {s['voice_s']:g} s, intent {s['intent']}",
                                     f"A30: {BLACK_INTENTS[s['intent']]}", unit=s["id"],
                                     evidence={"intent": s["intent"], "lines": r["lines"], "run_voice_s": r["voice_s"]})
                elif d == "reason":
                    journal.lint("black-reason", True, stage="scout", phase="preflight", unit=s["id"], severity="review",
                                 grammar="A30 refined",
                                 evidence={"black_reason": s["reason"], "lines": r["lines"], "run_voice_s": r["voice_s"],
                                           "voice_s": s["voice_s"],
                                           "check": "the reason is a black the story, the script or its flow demands"})
        if not ok and not draft:
            out.append(f"black-under-voice ({unit}: {r['voice_s']:g} s of voice over {r['from_s']:g} to {r['to_s']:g} s; "
                       + (f"no intent on {', '.join(missing)}" if missing else f"no lower third for {', '.join(bare)}") + ")")
    dips = plan["dips"] if "dips" in plan else dip_list(plan)
    dur = float(plan["duration_s"])
    length = max(float(plan.get("runtime_target_s") or 0.0), dur)
    binding = not draft and length >= EVENT_FILM_MIN_S
    n, secs = len(dips), sum(d["s"] for d in dips)
    srate = secs * 600.0 / dur if dur else 0.0
    film_allowed = math.floor(dur / DIP_EVERY_S + 1e-9)        # and over the film, at most one per 40 s (15 per 10 min)
    spans = plan["part_s"] if "part_s" in plan else part_spans(plan)
    by_part = {}
    for p, ps in spans.items():
        ids = [d["id"] for d in dips if d["part"] == p]
        allowed = max(1, math.ceil(ps / DIP_EVERY_S - 1e-9))
        by_part[p] = {"dips": len(ids), "part_s": round(ps, 2), "allowed": allowed, "over": max(0, len(ids) - allowed)}
    over = {p: v for p, v in by_part.items() if v["over"]}
    secs_ok = srate <= DIP_SECONDS_PER_10MIN_MAX + 1e-9
    count_ok = n <= film_allowed
    ok = not over and secs_ok and count_ok
    pacing_review(journal, "dip-budget", ok, stage="scout", unit="dips", grammar="7.3, A10, A30",
                  evidence={"dips": n, "film_allowed_dips": film_allowed, "dip_s": round(secs, 2),
                           "dip_s_per_10min": round(srate, 2),
                           "one_dip_per_s": DIP_EVERY_S, "max_dip_s_per_10min": DIP_SECONDS_PER_10MIN_MAX,
                           "allowed_dip_s": round(DIP_SECONDS_PER_10MIN_MAX * dur / 600.0, 2),
                           "by_part": by_part, "parts_over": sorted(over), "binding": binding,
                           "warning_because": None if binding else ("draft or check render" if draft else
                                                                    f"under {EVENT_FILM_MIN_S:g} s (a short piece)"),
                           "fix": None if ok else (
                               "make cuts of " + ", ".join(f"{v['over']} dip(s) in {p}" for p, v in over.items()) if over else
                               f"make cuts of {n - film_allowed} dip(s) across the film" if not count_ok else
                               "shorten the dips") + " (a cut inside a scene; a breath between scenes is a held frame or 1.5 s "
                                                     "with no voice, A10)"})
    return out


def credits_roll_lints(journal: Journal, plan: dict, *, draft: bool = False) -> list[str]:
    """credits-roll (E15): the roll finishes inside the credits shot: at the
    roll's constant speed, its last line has fully entered the frame at least
    CREDITS_LAST_LINE_S before the shot ends. Blocking on a final render, a
    warning under --draft. Returns the reasons to refuse."""
    out = []
    for s in plan["shots"]:
        if s.get("_card") != "credits":
            continue
        lay = M.credits_layout(M.Layout(plan["W"], plan["H"]), plan["credits"], M.Fonts())
        need = lay["last_entered_s"] + CREDITS_LAST_LINE_S
        ok = need <= s["_dur"] + 1e-6
        journal.lint("credits-roll", ok, stage="scout", phase="preflight", unit=s["id"], severity="warn" if draft else "block",
                     grammar="9, BRAND-KIT 6 and 11c",
                     evidence={"lines": len(lay["lines"]), "last_line_entered_s": round(lay["last_entered_s"], 2),
                               "shot_s": s["_dur"], "needs_s": round(need, 2),
                               "fix": None if ok else f"lengthen the credits shot to {math.ceil(need)} s; the roll never speeds up"})
        if not ok and not draft:
            out.append(f"credits-roll ({s['id']}: the last line enters at {lay['last_entered_s']:.1f} s; the shot is "
                       f"{s['_dur']:g} s, it needs {need:.1f} s)")
    return out


LABEL_RATE_S = 15.0             # A31 (R2): at most one label surfacing per 15 s of film (4 a minute), over the film
LABEL_RATE_WINDOW_MAX = 4       # A31 (review): and at most 4 in any 60 s window
PICTURE_CLASSES = ("ARCHIVE", "RECONSTRUCTED", "DRAWN", "AI-GENERATED")


def phone_legibility_lint(journal: Journal, plan: dict) -> list[str]:
    """phone-legibility (cinematography pass, founder 2026-10-17): every must-read text the house draws (the motion
    module's and the map renderer's sizes) renders at M.PHONE.min_px or more on a landscape phone (the frame
    M.PHONE.width_px wide). Guidance: a warning and a reviewer item, never a refusal. Returns [] (nothing to refuse)."""
    extra = {f"map {k}": v[1] for k, v in MP.LABEL.items()}
    extra.update({f"map {k}": v for k, v in MP.SIZES.items()})
    rows = M.phone_legibility(int(plan.get("W", 1920)), int(plan.get("H", 1080)), extra=extra)
    small = [r for r in rows if not r["ok"]]
    journal.lint("phone-legibility", not small, stage="scout", phase="preflight", unit="text", severity="warn",
                 grammar="cinematography pass 6, BRAND-KIT 4 and 12",
                 evidence={"phone_width_px": M.PHONE["width_px"], "min_px": M.PHONE["min_px"], "under": small,
                           "smallest": min(rows, key=lambda r: r["px"]), "checked": len(rows),
                           "fix": None if not small else "raise these sizes (% of H) until each renders at "
                                                         f"{M.PHONE['min_px']:g} px on the landscape phone"})
    return []


def label_rate_lint(journal: Journal, plan: dict, *, draft: bool = False) -> list[str]:
    """label-rate (A31, and A39 refined: founder 2026-10-12, a pacing guide):
    the provenance label surfaces only on a change of class or year
    (``M.label_surfacings``), and the guide is at most once per LABEL_RATE_S
    of film: n <= ceil(duration / 15), and at most LABEL_RATE_WINDOW_MAX in
    any 60 s window. The evidence counts the surfacings per minute and the
    busiest minute. Journaled as a warning and, past either cap, a reviewer
    item (``pacing-guide``); never a refusal, on a draft or a final render.
    The mark itself (glyph, change-only label, key) is unchanged and its
    own lints still bind. Returns [] (nothing to refuse)."""
    times = M.label_surfacings(plan["marks"])
    dur = float(plan["duration_s"])
    allowed = max(1, math.ceil(dur / LABEL_RATE_S - 1e-9))
    busiest = max((sum(1 for u in times if t <= u < t + 60.0) for t in times), default=0)
    ok = len(times) <= allowed and busiest <= LABEL_RATE_WINDOW_MAX
    pacing_review(journal, "label-rate", ok, stage="scout", grammar="A16, A31, BRAND-KIT 12",
                  evidence={"surfacings": len(times), "allowed": allowed, "duration_s": round(dur, 3),
                            "per_minute": round(60.0 * len(times) / dur, 2) if dur > 0 else None,
                            "busiest_minute": busiest, "busiest_minute_max": LABEL_RATE_WINDOW_MAX,
                            "times_s": [round(t, 3) for t in times[:200]],
                            "rule": f"guide: at most one per {LABEL_RATE_S:g} s of film and {LABEL_RATE_WINDOW_MAX} in any "
                                    "60 s, only on a change of class or year",
                            "fix": None if ok else "the guide suggests fewer changes of class or year between neighbouring "
                                                   "picture shots: group the shots of one year, or cut to a card between eras"})
    return []


def attribution_card(shots) -> int | None:
    """The end sequence's attribution card (END-SEQUENCE-SPEC, card 2), found
    by its kind: the first statement (or ``attribution``) card in the part of
    kind credits; else that part's credits roll; else None."""
    credits = [i for i, s in enumerate(shots) if s.get("_part_kind") == "credits" and s["kind"] == "card"]
    for want in (("statement", "attribution"), ("credits",)):
        k = next((i for i in credits if shots[i].get("_card") in want), None)
        if k is not None:
            return k
    return None


def mark_key_lints(journal: Journal, plan: dict, *, draft: bool = False) -> list[str]:
    """mark-key (A31): a film with picture marks shows the key card
    (``card: mark_key``) after its title card and before the next picture
    shot ("head"), and again after its last picture shot and before the
    attribution card ("end"): the first statement card of the credits part
    (``attribution_card``), else its credits roll; each key card is
    on screen at least KEY.min_s. Blocking on a final render of an event film
    (EVENT_FILM_MIN_S or longer, as the floors), a warning on a draft, a check
    render (--until) or a short piece. Returns the reasons to refuse."""
    shots = plan["shots"]
    pics = [i for i, s in enumerate(shots) if s["mark"] in PICTURE_CLASSES]
    if not pics:
        return []
    length = max(float(plan.get("runtime_target_s") or 0.0), float(plan["duration_s"]))
    binding = not draft and not plan.get("until_s") and length >= EVENT_FILM_MIN_S
    keys = [i for i, s in enumerate(shots) if s.get("_card") == "mark_key"]
    title = next((i for i, s in enumerate(shots) if s.get("_card") == "title"), None)
    after = title if title is not None else -1
    nxt_pic = next((i for i in pics if i > after), None)
    head = next((k for k in keys if k > after and (nxt_pic is None or k < nxt_pic)), None)
    attr = attribution_card(shots)
    end = next((k for k in keys if k > pics[-1] and (attr is None or k < attr)), None)
    out = []
    for unit, k, where in (("mark-key:head", head, "after the title card, before the first picture shot after it"),
                           ("mark-key:end", end, "after the last picture shot, before the attribution card")):
        dur = float(shots[k]["_dur"]) if k is not None else None
        ok = k is not None and dur >= M.KEY["min_s"] - 1e-6
        journal.lint("mark-key", ok, stage="scout", phase="preflight", unit=unit, severity="block" if binding else "warn",
                     grammar="A31, BRAND-KIT 12",
                     evidence={"where": where, "shot": shots[k]["id"] if k is not None else None, "dur_s": dur,
                               "min_s": M.KEY["min_s"], "title": shots[title]["id"] if title is not None else None,
                               "key_cards": [shots[i]["id"] for i in keys], "binding": binding,
                               "fix": None if ok else (
                                   f"lengthen it to at least {M.KEY['min_s']:g} s" if k is not None else
                                   f"add a shot {{kind: card, card: mark_key, mark: CARD, text: []}} {where}, 5 s")})
        if not ok and binding:
            out.append(f"mark-key ({unit.split(':')[1]}: {where})")
    return out


def card_fill_lints(journal: Journal, plan: dict) -> list[str]:
    """card-fills-drawn (E15): after the fill, every filled card is laid out
    again from its filled text, which must fit and be drawn word for word.
    Returns the reasons to refuse."""
    fills = (plan.get("card_fills") or {}).get("texts") or {}
    out = []

    def lint(rule, ok, *, unit=None, severity="block", evidence=None, grammar=None, stage="assembly"):
        journal.lint(rule, ok, stage=stage, unit=unit, severity=severity, evidence=evidence, grammar=grammar, phase="preflight")
        if not ok:
            out.append(f"{rule} ({unit}): {evidence}")

    card_lints(lint, plan["shots"], plan["W"], plan["H"], rule_fits="card-fills-fit", rule_drawn="card-fills-drawn",
               stage="assembly", only=set(fills))
    return out


PACING_GUIDE = "A39: pacing is guidance; the founder judges rhythm (a warning and a reviewer item, never a refusal)"
PACING_ADVISORY = ("still-hold", "dip-budget", "voiceless-floor", "label-rate")   # A39: advisory (R12; label-rate R13)


def pacing_review(journal: Journal, rule: str, ok: bool, *, unit=None, stage: str = "assembly", grammar=None,
                  evidence=None) -> None:
    """A39 (founder, R12: "Max hold times etc should be guidance, not rule"): a
    pacing limit is journaled as a warning and, where it is not met, as a
    reviewer item (``pacing-guide``) naming the rule; it never refuses."""
    ev = dict(evidence or {}, advisory=PACING_GUIDE)
    journal.lint(rule, ok, stage=stage, phase="preflight", unit=unit, severity="warn", grammar=grammar, evidence=ev)
    if not ok:
        journal.lint("pacing-guide", True, stage=stage, phase="preflight", unit=unit, severity="review",
                     grammar=f"{grammar}, A39" if grammar else "A39",
                     evidence={"rule": rule, "check": "the founder judges this rhythm", "found": ev})


def still_hold_lints(journal: Journal, plan: dict, placed: dict, *, draft: bool = False) -> list[str]:
    """still-hold (GRAMMAR 7.2, A9, A20(a)), one lint per archive still: a
    pacing guide (A39, founder R12: "Max hold times etc should be guidance,
    not rule"), journaled as a warning and, where a hold runs over, a
    reviewer item. Never a refusal: returns []."""
    for h in still_holds(plan, placed):
        pacing_review(journal, "still-hold", h["ok"], unit=h["id"], grammar="7.2, A9, A20(a)",
                      evidence=dict(h, rule="at most 10 s with no voice (holds of one photograph linked across a dip); at "
                                             "most 20 s not under a reading; a hold at most 30 s; a DETAIL at most 5 s",
                                    fix=None if h["ok"] else "the guide suggests a shorter hold or another picture"))
    return []


def sound_lints(journal: Journal, plan: dict, mix: np.ndarray, placed: dict, *, draft: bool = False) -> list[str]:
    """A17, A18 and A19 on the mix. digital-silence (a warning): true digital
    silence over 4 s outside an intended silence. voiceless-floor and
    readings-floor (GRAMMAR 6.1): at least 10% of the runtime has no voice
    and readings carry at least 20% (founder, 2026-10-10; was 30%); readings-floor is blocking on a full, final
    render of an event film, a warning on a draft, a check render (--until) or a short piece; voiceless-floor
    judges the film's breath, a rhythm, and is a pacing guide (A39): a warning and a reviewer item. The narration ceiling is lifted (A17): narration is reported, never
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
    # A25 (E9): the floors are the film's settings (Partition's values unless it states its own); a share under its
    # floor passes as a review item only when the screenplay declares the shortfall and its card states it (6.5, T1f).
    # A25 refined: every declared shortfall is judged on the film's own measurement, which its card prints; a film
    # that meets the floor it declared short of is refused (the card would say short when it is not).
    settings = plan.get("settings") or POL.DEFAULT_SETTINGS
    stated = plan.get("settings_stated") or {}
    declared = {sf.get("what"): sf for sf in (plan.get("shortfalls") or []) if isinstance(sf, dict)}
    floors = [("voiceless-floor", "voiceless", sh["voiceless"], settings["voiceless_floor"], sev, "6.1, A17, A18"),
              ("readings-floor", "readings", sh["readings"], settings["readings_floor"], sev, "6.1, A17, A18")]
    women = women_share(plan, placed)
    if (women["testimony_s"] > 0 and "women_floor" in stated) or "women" in declared:
        # GRAMMAR 6.5: the T1f ruling left it unlinted for a film that states neither its women_floor nor a shortfall
        floors.append(("women-floor", "women", women["share"], settings["women_floor"],
                       sev if "women_floor" in stated else "review", "6.5, A25"))
    for rule, what, value, floor, severity, grammar in floors:
        ok = value >= floor
        ev = {what: value, "min": floor}
        extra = {"women": women} if what == "women" else {}
        sf = declared.get(what)
        if sf is None and rule in PACING_ADVISORY:
            # A39: the voiceless floor judges the film's breath, a rhythm: a warning and a reviewer item
            pacing_review(journal, rule, ok, grammar=grammar, evidence=dict(ev, shares=sh, binding=binding, warning_because=why))
            continue
        if sf is None:
            journal.lint(rule, ok, stage="assembly", phase="preflight", severity=severity, grammar=grammar,
                         evidence=dict(ev, shares=sh, binding=binding, warning_because=why, **extra))
            if not ok and binding and severity == "block":
                out.append(f"{rule}: {ev}")
            continue
        extra["shortfall"] = sf
        if ok:
            journal.lint(rule, True, stage="assembly", phase="preflight", severity=severity, grammar=grammar,
                         evidence=dict(ev, shares=sh, binding=binding, warning_because=why, **extra))
            journal.lint("shortfall-measured", False, stage="assembly", phase="preflight", unit=f"shortfall:{what}",
                         severity="block" if binding else "warn", grammar="6.5, A25",
                         evidence={"shortfall": sf, "measured": value, "floor": floor, "warning_because": why,
                                   "why": "declared short, but the film meets its floor: not short"})
            if binding:
                out.append(f"shortfall-measured ({what}): the film measures {value:g}, at or over its floor {floor:g}: "
                           f"not short, so {sf.get('stated_on')} may not say it is")
        elif sf.get("stated"):
            journal.lint(rule, False, stage="assembly", phase="preflight", severity="review", grammar=grammar,
                         evidence=dict(ev, shares=sh, binding=binding, **extra,
                                       result=f"short of the floor, stated on {sf['stated_on']} with the film's own "
                                              f"measurement: a review item for G3"))
        else:
            journal.lint(rule, False, stage="assembly", phase="preflight", severity=severity, grammar=grammar,
                         evidence=dict(ev, shares=sh, binding=binding, warning_because=why, **extra,
                                       why="the declared shortfall's card does not state it (shortfall-stated)"))
            if binding and severity == "block":
                out.append(f"{rule}: {ev} (its declared shortfall is not stated on a card)")
    journal.event("unit", "assembly", "mix", lens="shares", status="info", shares=sh, narration_ceiling=None,
                  note="A17 lifts the 25% narration ceiling; narration is reported, not capped")
    return out


def score_lints(journal: Journal, plan: dict, stems: dict, *, draft: bool = False,
                registry: list[dict] | None = None) -> list[str]:
    """A29 (R1) and A29 refined (R10), the house score standard on the music
    as the mix placed it (studio/engine/score.py): bed-under-voice (a bed in
    the voice's gaps at least the standard's 12 dB under the dialogue
    target), bed-low-end (a bed's or regional cue's share of 150 to 400 Hz
    after its band-shaping), music-treble (a scored cue's share over 5 kHz),
    regional-density, brand-pulse-place, score-repetition (no tiled loop in
    a cue, no two cues alike), bed-reuse (no cue of the film's own score
    another registered film plays; ``registry`` replaces
    score.film_registry), phone-check (the words clear and the brand pulse
    perceptible on a small speaker), bed-breathing (its 100 ms level
    spread), transition-ceiling (a transition's or sting's loudest 400 ms
    never above the bed it leads into), music-entry (an underscore cue that
    enters from no music fades in), music-holes (no undeclared stretch with
    no music between the first cue and the last) and duck-pumping (the duck
    holds through every pause in a line and every gap under the hold).
    Blocking on a final render; warnings under --draft, --audio-only and
    --until (``draft``). A film's take (A29 take) is judged by its spans and
    its rest map (score.take_checks), each of those checks a canary: a
    warning until score.TAKE_CANARY_UNTIL, then blocking. Returns the reasons
    to refuse."""
    std = plan.get("score_standard") or dict(SC.STANDARD)
    film = Path(plan["film"])
    mine = [(c["id"], film / (c.get("wav") or f"audio/{c['id']}.wav"), SC.cue_role(c) == "take") for c in plan["cues"]
            if c.get("kind") == "music" and SC.cue_role(c) in SC.FILM_LAYER and c.get("silence") != "intended"]
    cards = [(s["f0"] / FPS, s["f1"] / FPS) for s in plan["shots"]
             if s["kind"] == "card" and (s.get("_card") or card_kind(s)) in ("title", "chapter")]
    checks = SC.score_checks(stems.get("cues", []), std, duration_s=plan["duration_s"], silences=plan.get("silences", []),
                             own_sound=stems.get("own_sound", []), duck100=stems.get("duck100"),
                             voice_grid=stems.get("voice_grid"), duck_grid=stems.get("duck_grid"), spans=stems.get("spans"),
                             voice100=stems.get("voice100"), cards=cards, phone=stems.get("phone"),
                             reuse=SC.reuse_check(film, {"slug": plan["slug"]}, registry, mine=mine), take=stems.get("take"))
    out = []
    canary = SC.take_canary()
    for c in checks:
        # A29 take: a take's checks are a canary, log-only until SC.TAKE_CANARY_UNTIL, then blocking as the rest
        log_only = bool(c.get("canary")) and canary
        extra = {"canary": f"A29 take: log-only until {SC.TAKE_CANARY_UNTIL}" if log_only else
                 f"A29 take: blocking since {SC.TAKE_CANARY_UNTIL}"} if c.get("canary") else {}
        journal.lint(c["rule"], c["ok"], stage="assembly", phase="preflight", unit=c["unit"],
                     severity="warn" if draft or log_only else "block",
                     grammar="8.4 (revised), A29 take" if c.get("canary") else "8.5, A29, A29 refined",
                     evidence=dict(c["evidence"], standard_stated=plan.get("score_standard_stated") or {}, **extra))
        if not c["ok"] and not draft and not log_only:
            ev = {k: v for k, v in c["evidence"].items() if k not in ("fix", "declared", "pumps", "holes", "worst", "duplicates")}
            out.append(f"{c['rule']} ({c['unit']}: {ev}; {c['evidence'].get('fix')})")
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


def title_sources_fields(s: dict) -> dict:
    """A40: what the sources page says of the series titles: the master, its record, its marks and every period
    record it was drawn from, with its licence and source (the CC BY ones are attributed here and in the credits)."""
    if not TS.is_title(s):
        return {}
    it = s.get("_item") or {}
    prov, _, _ = TS.provenance(it)
    keep = ("id", "title", "date", "holder", "licence", "source_page", "use", "beats")
    return {"title_sequence": {
        "series": TS.SERIES, "master": it.get("id"), "version": it.get("version"), "record": it.get("record"),
        "burned_marks": it.get("burned") is True, "marks": TS.timeline(it), "ai": False,
        "made_with": it.get("generator"),
        "provenance": [dict({k: x.get(k) for k in keep}, credit=TS.plain(x.get("credit"))) for x in TS.provenance_items(prov)]}}


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
            "fill": (s.get("_cam") or {}).get("fill"),
            "in_s": s.get("in_s"), "out_s": s.get("out_s"),
            "resampler": s.get("_resampler"), "conform": (s.get("_video") or {}).get("conform"),
            "neutralise_cast": (s.get("_video") or {}).get("neutralise_cast"),
            "test_fixture": is_synthetic(it),
            **OV.sources_fields(s),
            **title_sources_fields(s),
            "text": s.get("text"),
        })
    # the mark track and the share by class, frame by frame: a series title (A40) by its own marks' spans
    pieces = []
    for s, d in zip(plan["shots"], shots):
        if TS.is_title(s):
            pieces += [(a, b, cls, "" if cls == "CARD" else (s["detail"] if cls == s["mark"] else ""), lab)
                       for a, b, cls, lab in TS.spans(s["_item"], s["f0"], s["f1"])]
        else:
            pieces.append((s["f0"], s["f1"], d["mark"]["class"], d["mark"]["detail"], d["mark"]["label"]))
    track = []
    for a, b, cls, detail, label in pieces:
        if track and track[-1]["class"] == cls and track[-1]["detail"] == detail:
            track[-1]["to_s"] = round(b / FPS, 4)
        else:
            track.append({"from_s": round(a / FPS, 4), "to_s": round(b / FPS, 4), "class": cls, "detail": detail, "label": label})
    total = plan["frames"]
    share = {c: round(sum(b - a for a, b, cls, _, _ in pieces if cls == c) / total, 4) for c in CLASSES}
    readings = readings_doc(plan)
    # The narrator's words, so the site's transcript holds everything spoken, and the narrator's voice credit, so
    # the site can say the narration is a computer voice from the film's own record (web/src/film-data.ts).
    narration = [{"id": ln["id"], "start_s": ln.get("start_s"), "text": ln.get("text")}
                 for ln in plan["lines"] if ln.get("kind") == "narration" and ln.get("text")]
    nv = plan.get("narrator_voice") or {}
    narrator = {"credit": nv.get("credit"), "engine": nv.get("engine"), "voice": nv.get("voice")} if narration and nv.get("credit") else None
    return {"v": 2, "title": plan["title"], "slug": plan["slug"], "run": journal.run,
            "engine": {"version": ENGINE_VERSION, "hash": ENGINE_HASH},
            "width": plan["W"], "height": plan["H"], "fps": FPS, "frames": total, "duration_s": round(total / FPS, 4),
            "shots": shots, "marks": track, "share": share,
            "lower_thirds": [{"id": lt["id"], "start_s": lt["start"], "end_s": lt["end"], "lines": lt["lines"], "flag": lt["flag"]}
                             for lt in plan["lower_thirds"]],
            "readings": readings, "narration": narration, "narrator": narrator,
            # A21, A25, E2: the film's own imagery rule, policy settings, stated shortfalls and sides, for the sources page
            **film_policy_doc(plan),
            # A29 refined: a regional cue prints the critical moment it lands on
            "cues": [{**{k: c.get(k) for k in ("id", "kind", "role", "source", "licence", "tradition", "performer", "start_s",
                                               "end_s")},
                      **({"score_role": "regional", "marks_moment": c["marks_moment"]} if SC.cue_role(c) == "regional" else {})}
                     for c in plan["cues"]],
            "credits": [{"heading": h, "lines": ln} for h, ln in plan["credits"]],
            # A30: every voice over black the film chose, and why, so the choice is visible; A29: the score standard used
            "black_under_voice": [{"shot": s["id"], "kind": s["kind"], "intent": s["intent"], "why": BLACK_INTENTS[s["intent"]],
                                   "voice_s": s["voice_s"], "lines": r["lines"]}
                                  for r in plan.get("dark_voice") or [] if r["voice_s"] > BLACK_VOICE_MAX_S
                                  for s in r["shots"] if isinstance(s.get("intent"), str) and s["intent"] in BLACK_INTENTS],
            "score_standard": plan.get("score_standard") or dict(SC.STANDARD), **extra}


def readings_doc(plan: dict, *, durations: bool = True) -> list[dict]:
    """sources.json's ``readings``: every testimony line, whose words they are
    and how long they are heard. ``durations=False`` skips reading the WAVs
    (the plan-time check that an on-screen-named speaker is still named here)."""
    readings = []
    for ln in plan["lines"]:
        if ln.get("kind") == "testimony":
            sp = plan["speakers"].get(ln.get("speaker"), {})
            # How long the reading is heard (its measured WAV) and whose words they are: the site's
            # "Whose words, and how long" balance is computed from these (web/src/film-data.ts).
            if archival_span(ln):                # A26: an original recording plays its span, marked ARCHIVE
                dur = round(float(ln["out_s"]) - float(ln["in_s"]), 3)
            elif not durations:
                dur = None
            else:
                wav = voice_wav(Path(plan["film"]), ln)
                dur = round(wav_seconds(wav), 3) if wav.exists() else None
            readings.append({"id": ln["id"], "speaker": ln.get("speaker"), "name": sp.get("name"), "side": sp.get("side"),
                             "gender": sp.get("gender"), "dur_s": dur,
                             "year": ln.get("year"), "source": ln.get("source"), "locator": ln.get("locator"),
                             "start_s": ln.get("start_s"), "text": ln.get("text"),
                             "credit": (f"Read by a computer voice. No recording of {sp.get('name', ln.get('speaker'))} was used."
                                        if ln.get("read_by") else "original recording")})
            if archival_span(ln):
                readings[-1].update(mark="ARCHIVE", clip=ln["clip"], in_s=float(ln["in_s"]), out_s=float(ln["out_s"]),
                                    source=ln.get("source") or ln["clip"], transcript_source=ln.get("transcript_source"))
                corr = CL.av_correction_s(plan["assets"].get(ln["clip"]))
                if corr:                         # A33(1b): a re-synced span says so on the sources page
                    readings[-1]["av_correction_ms"] = round(corr * 1000)
    return readings


# --------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------


def film_policy_doc(plan: dict) -> dict:
    """What sources.json states of the film's own rules (A21, A25, E2): its
    imagery rule in plain words, its policy settings, each stated shortfall
    and the card that states it, and the sides it declares. A plan made
    before these existed gets the Partition defaults."""
    rule = plan.get("imagery_rule") or dict(POL.DEFAULT_IMAGERY_RULE, declared=False)
    return {"imagery_rule": rule, "settings": plan.get("settings") or dict(POL.DEFAULT_SETTINGS),
            "readings_share_counts": list(READINGS_SHARE_COUNTS),
            "shortfalls": plan.get("shortfalls") or [], "sides": plan.get("sides") or sorted(
                {sp.get("side") for sp in (plan.get("speakers") or {}).values() if sp.get("side")}),
            **({"balance": plan["balance"]} if plan.get("balance") else {}),
            **({"card_fills": plan["card_fills"]} if plan.get("card_fills") else {})}


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
        "engine": ENGINE_HASH, "resample": M.RESAMPLE, "W": plan["W"], "H": plan["H"], "fps": FPS, "shot": _clean(s),
        "asset": asset_hash.get(s.get("asset")), "prev": _clean(prev) if prev else None,
        "prev_asset": asset_hash.get(prev.get("asset")) if prev else None,
        "next_transition": nxt["transition_in"] if nxt else None, "next_f0": nxt["f0"] if nxt else None,
        "marks": plan["marks"][max(0, i - 1): i + 1],
        "label_start": M.label_starts(plan["marks"])[i],        # A31: it may come from an earlier shot (a label runs on)
        "label_times": M.label_times(plan["marks"])[i],         # A42: and it grows again within a long shot
        "lower_thirds": [lt for lt in plan["lower_thirds"] if lt["start"] < t1 and lt["end"] > t0],
        "overlays": [o for o in plan["overlays"] if o["start"] < t1 and o["end"] > t0],
        "tools": env_key,
        "subtitles": [c for c in plan["subtitles"] if c["start"] < t1 and c["end"] > t0],
        "wm": [plan["wm_start"], plan["card_spans"]],
        "credits": plan["credits"] if s.get("_card") == "credits" else None,
        "key_classes": plan.get("key_classes") if s.get("_card") == "mark_key" else None,
    }
    if plan.get("card_fills"):                      # A25 refined: the filled numbers are part of what is drawn
        rec["card_fills"] = plan["card_fills"]["values"]
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
        # E15: binding on a run that renders the final frames; --draft, --audio-only (no frames) and --until (a check
        # render) journal them as warnings
        advisory = draft or audio_only or until_s is not None
        lt_refusals = (lower_third_time_lints(journal, plan, draft=advisory) + credits_roll_lints(journal, plan, draft=advisory)
                       + label_rate_lint(journal, plan, draft=advisory) + phone_legibility_lint(journal, plan) + mark_key_lints(journal, dict(plan, until_s=until_s), draft=advisory))
        lt_refusals += black_dip_lints(journal, plan, draft=advisory)
        if lt_refusals:
            raise Refused(f"on-screen time (pre-flight): {'; '.join(lt_refusals)} (BRAND-KIT 4 and 11c, A20(b), A30; "
                          "render with --draft to accept it)")
        if until_s is not None:
            journal.human("scout", f"--until {until_s:g}: only the shots that start before {until_s:g} s are rendered",
                          override="--until")
            plan = trim_plan(plan, until_s)
        stills = [s["id"] for s in plan["shots"] if s["kind"] == "archive_still" and s.get("_cam") and opens_whole(s)]
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
            if s.get("_span"):                   # A26: keyed by the span's own sha256 (in the shot), never the whole reel
                continue
            p = (s.get("_item") or {}).get("_path")
            if p and s.get("asset") not in asset_hash:
                asset_hash[s["asset"]] = sha256_file(p)
        env_key = tools_key()
        segs, todo, cached = {}, [], []

        def key_shot(i):
            s = plan["shots"][i]
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

        # A25 refined: a film with placeholders is keyed once the mix has filled them (a card's text is its pixels, and a
        # neighbour's key reads it through prev and the subtitles), so every shot of such a film waits for the fill
        pending = list(range(len(plan["shots"]))) if plan_has_placeholders(plan) else []
        for i in range(len(plan["shots"])):
            if i not in pending:
                key_shot(i)

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
            stems: dict = {}
            mix, placed = build_mix(plan, film, journal, draft=draft, work=work, stems=stems)
            import soundfile as sf
            sf.write(str(work / "mix.wav"), mix, AUDIO_RATE, subtype="FLOAT")
            u.extra.update(placed=placed)
        journal.artifact("assembly", work / "mix.wav", unit="mix", role="mix")
        share_refusals = sound_lints(journal, plan, mix, placed, draft=draft)
        if share_refusals:
            raise Refused(f"voice shares (pre-flight): {'; '.join(share_refusals)} (GRAMMAR 6.1; render with --draft to accept it)")
        score_refusals = score_lints(journal, plan, stems, draft=advisory)
        del stems
        if score_refusals:
            raise Refused(f"score standard (pre-flight): {'; '.join(score_refusals)} (GRAMMAR 8.5, A29; render with --draft "
                          "to accept it)")
        fill_cards(plan, shortfall_values(plan, placed), journal)
        fill_refusals = card_fill_lints(journal, plan)
        if fill_refusals:
            raise Refused(f"filled cards (pre-flight): {'; '.join(fill_refusals)} (E15: a card's text is drawn whole or refused)")
        for i in pending:
            key_shot(i)
        todo.sort()
        cached.sort()
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
                      + r["mark"].get("burned", 0) + r["mark"].get("dip_glyph", 0) for r in results.values())
        dip_glyph = {plan["shots"][i]["id"]: r["mark"]["dip_glyph"] for i, r in results.items() if r["mark"].get("dip_glyph")}
        if dip_glyph:                            # A40: a master's own dip that shows its mark on the black hold (a warning)
            journal.lint("title-dip-hold", False, stage="marks", grammar="A40, 7.3, A11", phase="post-render", severity="warn",
                         evidence={"frames": dip_glyph, "fix": "re-assemble the master with its dip's black hold all black"})
        journal.lint("mark-coverage", not fails and checked == plan["frames"], stage="marks", grammar="1.3, 4, A11", phase="post-render",
                     evidence={"frames": plan["frames"], "checked": checked, "ok": sum(r["mark"]["ok"] for r in results.values()),
                               "probe": "the class glyph's centre for the hue and its corner for the shape (A16 refined)",
                               "wrong_shape": sum(r["mark"].get("shape", 0) for r in results.values()),
                               "label_frames": sum(r["mark"].get("label", 0) for r in results.values()),
                               "glyph_only_frames": sum(r["mark"].get("glyph_only", 0) for r in results.values()),
                               "crossfade": sum(r["mark"]["fade"] for r in results.values()),
                               "dip_black": sum(r["mark"].get("dip", 0) for r in results.values()),
                               # A40: the series titles' frames, checked against the master's own declared marks
                               "title_burned": sum(r["mark"].get("burned", 0) for r in results.values()),
                               "title_dip_glyph": sum(r["mark"].get("dip_glyph", 0) for r in results.values()), "failed": fails})
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
        # A33(1c): every archival line heard over its own picture is measured in the master; a final render refuses a
        # conclusive offset more than 45 ms from the correction applied (a draft or check render journals it)
        with journal.unit("assembly", "sync-check", size={"driver": "items", "value": sum(
                1 for ln in plan["lines"] if ln.get("archival_audio") and ln.get("clip"))}):
            sync_refusals = CL.rendered_sync_lints(journal, plan, master, draft=draft or bool(check))
        if sync_refusals:
            raise Refused(f"archival sync (post-render): {'; '.join(sync_refusals)} (GRAMMAR A33)")
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
                   "cached": [ids[i] for i in cached], "workers": n, "partial": bool(check), "until_s": until_s,
                   "clip_warnings": plan.get("clip_integrity", {}).get("warnings", [])}     # A33(3): listed in the report
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
    prev = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    extra.update({k: prev[k] for k in ("loudness",) if k in prev})
    extra.update(master="master.mp4", master_sha256=sha256_file(master))
    if plan_has_placeholders(plan):
        fills = prev.get("card_fills")
        values = fills.get("values") if isinstance(fills, dict) else None
        why = fills_provenance(prev, extra["master_sha256"])
        journal.lint("shortfall-fill", why is None, stage="assembly", phase="sources-only", grammar="6.5, A25",
                     evidence={"why": why, "values": values})
        if why:
            raise Refused(f"a shortfall card's numbers come from the render's own measurement and {why}: render the film")
        fill_cards(plan, values, journal)
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
