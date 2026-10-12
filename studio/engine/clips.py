"""Clip integrity (GRAMMAR A33, engine ticket R11): an archival clip is shown
whole where it has a natural boundary, its words are heard whole, and its
sound stays on its picture.

    python -m studio.engine.clips bounds <film> <clip> [--from A] [--to B]
    python -m studio.engine.clips natural-out <film> <clip> <t> [--talking-head]
    python -m studio.engine.clips breathe <film> <clip> <t>
    python -m studio.engine.clips snap-in <film> <clip> <t>
    python -m studio.engine.clips plan <film> <requests.json>
    python -m studio.engine.clips check <film> [--json <file>]
    python -m studio.engine.clips lipsync <film> <clip> --at A --dur D --face x0,y0,x1,y1 --mouth x0,y0,x1,y1 [--write]

What it knows of a source clip (``ClipBounds``), measured once and cached in
a sidecar keyed by the source's content (its size and the sha256 of its
first and last MiB, the span cache's key, so a reel is never hashed whole):

- its shot cuts, from ffmpeg ``scdet`` (threshold 8) on a 160 px copy, plus
  any the ledger item declares in ``extra_cuts`` (a dissolve scdet misses);
- its speech, from a 10 ms RMS envelope of its own soundtrack: a frame is
  speech when it stands 12 dB over the 10th-percentile floor of the 4 s
  around it (and over -50 dBFS); runs closer than 80 ms merge, runs under 50 ms
  are dropped.

Both are analysed in 30 s blocks aligned to the clip's own time, only where a
shot or line needs them (ffmpeg seeks to the block; nothing reads a reel
whole). The sidecar lives in ``<film>/cache/bounds/`` unless
``DOCUMENT_BOUNDS_CACHE`` names another folder.

The plan-time rules (``plan_lints``, called from render.build_plan) and the
render's own re-measurement (``rendered_sync_lints``) are A33's enforcers;
``natural_out``, ``breathe_out`` and ``snap_in`` are what a film's builder
calls to choose in and out points that pass them.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

# --------------------------------------------------------------------------
# Numbers (GRAMMAR A33)
# --------------------------------------------------------------------------

BOUNDS_VERSION = 1
BLOCK_S = 30.0                      # analysis blocks, aligned to the clip's own time
PREROLL_S = 0.5                     # scdet needs a frame before the block's first
SCDET_THRESHOLD = 8.0
ANALYSIS_WIDTH = 160                # scdet scores at 160 px match the source's own within 0.3 (debate 1969, Tonga 1965)
ENV_HOP_S = 0.010                   # speech envelope: 10 ms RMS
ENV_RATE = 16000
SPEECH_OVER_FLOOR_DB = 12.0
SPEECH_ABS_MIN_DBFS = -50.0
SPEECH_FLOOR_PCT = 10.0
SPEECH_FLOOR_WIN_S = 4.0            # ... of a sliding 4 s window (the room or bed under the words, here and now)
SPEECH_MERGE_S = 0.08               # gaps shorter than this are inside a word (a stop consonant)
SPEECH_MIN_RUN_S = 0.05             # shorter runs are clicks

SYNC_TOL_S = 1.0 / 24               # A33(1): a line's offset into its shot equals its offset into the source, within a frame
FLASH_S = 0.75                      # A33(2a): no shot starts or ends within 0.75 s of a source cut ...
ON_CUT_OUTSIDE_S = 0.5 / 24         # ... unless it is on it: never a frame of the other source shot ...
ON_CUT_INSIDE_S = 0.10              # ... and at most 0.1 s short of the cut on the side that only trims the shot
QUOTE_LEAD_S = 0.15                 # A33(2c): a quote's audio opens 0.15 s before its first word ...
QUOTE_TAIL_S = 0.25                 # ... and closes 0.25 s after its last
EDGE_SLACK_S = 0.25                 # either may run this much longer and still sit on the edge
EDGE_MIN_LEAD_S = 0.05              # a word's attack is clipped when the cut is closer than this
EDGE_MIN_TAIL_S = 0.10
EDGE_GUARD_S = 0.10                 # no speech in the 100 ms before the in point or after the out point
READING_HOLD_S = 1.5                # A10(2), A33(2d): the picture holds 1.5 s after a quote's last word
SILENT_TALK_MAX_S = 0.10            # A33(2e): a talking head's mouth may move unheard for at most this (a breath)
NATURAL_MIN_S = 1.5                 # natural_out: the first cut at or after the last word + 1.5 s ...
NATURAL_MAX_S = 6.0                 # ... up to 6 s after it
BREATHE_MAX_S = 8.0                 # A33(3): a narrated shot plays to its source shot's end unless that is over 8 s past
MID_ACTION_S = 1.0                  # A33(3): clip-cut-mid-action warns past this much of the source shot left unplayed
TH_RESUME_GUARD_S = 0.12            # a talking head ends this far before the speaker's next word

AV_LEAD_MAX_MS = 45.0               # A33(1b), ITU-R BT.1359: audio leading by more than this is detectable ...
AV_LAG_MAX_MS = 120.0               # ... and audio lagging by more than this (the house threshold, under BT.1359's 125)
LIPS_NATURAL_LAG_MS = 80.0          # the envelope trails visible articulation in a source known in sync (debate 1969: 66 to 104)
AV_OFFSET_ABS_MAX_MS = 2000.0
RENDER_SYNC_TOL_MS = 45.0           # A33(1c): the master's measured offset within 45 ms of the correction applied
RENDER_SYNC_MIN_S = 1.5             # a line needs this much of its own picture to be measured
ANALYSIS_PAD_BEFORE_S = 8.0         # the plan analyses each shot's clip from 8 s before its in point ...
ANALYSIS_PAD_AFTER_S = 25.0         # ... to 25 s past its out point (natural ends, the speaker's next word)


# --------------------------------------------------------------------------
# ffmpeg helpers
# --------------------------------------------------------------------------


def _ffmpeg() -> str:
    from studio.engine.render import ffmpeg
    return ffmpeg()


def _ffprobe() -> str:
    from studio.engine.render import ffprobe
    return ffprobe()


def probe_media(path: Path) -> dict:
    """Duration, start time and which streams a file has (ffprobe, the header only)."""
    r = subprocess.run([_ffprobe(), "-v", "error", "-show_entries", "format=duration,start_time:stream=codec_type,avg_frame_rate",
                        "-of", "json", str(path)], capture_output=True, text=True, timeout=60)
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        d = {}
    fmt = d.get("format") or {}
    kinds = [s.get("codec_type") for s in d.get("streams") or []]
    fps = None
    for s in d.get("streams") or []:
        if s.get("codec_type") == "video" and s.get("avg_frame_rate") not in (None, "0/0"):
            a, _, b = str(s["avg_frame_rate"]).partition("/")
            try:
                fps = float(a) / float(b or 1)
            except (ValueError, ZeroDivisionError):
                fps = None
    def num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None
    return {"duration_s": num(fmt.get("duration")), "start_time": num(fmt.get("start_time")) or 0.0,
            "has_video": "video" in kinds, "has_audio": "audio" in kinds, "fps": fps}


def read_pcm(path: Path | str, a: float, d: float, sr: int = ENV_RATE) -> np.ndarray:
    """Mono float PCM of [a, a + d] seconds of a file (an input seek: nothing before a is read)."""
    r = subprocess.run([_ffmpeg(), "-v", "error", "-ss", f"{max(0.0, a):.4f}", "-t", f"{max(0.0, d):.4f}", "-i", str(path),
                        "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"], capture_output=True)
    return np.frombuffer(r.stdout, np.float32).astype(np.float64)


def read_frames(path: Path | str, a: float, d: float, *, size: tuple[int, int], crop: str | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Grey frames of [a, a + d] at ``size`` (w, h), with each frame's own
    presentation time in the file (showinfo, timestamps copied), so a match
    is exact to the frame, never to a guessed frame rate."""
    w, h = size
    vf = (f"crop={crop}," if crop else "") + f"scale={w}:{h},format=gray,showinfo"
    r = subprocess.run([_ffmpeg(), "-hide_banner", "-copyts", "-ss", f"{max(0.0, a):.4f}", "-t", f"{max(0.0, d):.4f}", "-i", str(path),
                        "-an", "-vf", vf, "-f", "rawvideo", "-"], capture_output=True)
    x = np.frombuffer(r.stdout, np.uint8)
    n = len(x) // (w * h)
    frames = x[: n * w * h].reshape(n, h, w).astype(np.float32)
    times = [float(t) for t in re.findall(rb"pts_time:\s*([-\d.]+)", r.stderr)]
    k = min(n, len(times))
    return np.array(times[:k]), frames[:k]


# --------------------------------------------------------------------------
# Speech runs and cuts, per 30 s block
# --------------------------------------------------------------------------


def envelope_db(x: np.ndarray, sr: int = ENV_RATE, hop_s: float = ENV_HOP_S) -> np.ndarray:
    n = max(1, int(round(sr * hop_s)))
    k = len(x) // n
    if k == 0:
        return np.zeros(0)
    return 10.0 * np.log10(np.mean(x[: k * n].reshape(k, n) ** 2, axis=1) + 1e-12)


def merge_runs(runs: list[tuple[float, float]], gap: float = SPEECH_MERGE_S) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for a, b in sorted(runs):
        if out and a - out[-1][1] < gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(round(float(a), 3), round(float(b), 3)) for a, b in out]


def local_floor(e: np.ndarray, win_s: float = SPEECH_FLOOR_WIN_S, step: int = 25) -> np.ndarray:
    """The envelope's 10th percentile over a sliding window (every ``step``
    frames, interpolated): the room or bed the speech stands over, here and
    now. A reel's silent tail or a loud title never sets the floor of a
    quiet scene beside it, and a music bed lifts the floor under it."""
    half = max(1, int(win_s / 2 / ENV_HOP_S))
    at = np.arange(0, len(e), step)
    vals = np.array([np.percentile(e[max(0, k - half): k + half + 1], SPEECH_FLOOR_PCT) for k in at])
    return np.interp(np.arange(len(e)), at, vals)


def speech_runs(x: np.ndarray, t0: float, sr: int = ENV_RATE) -> tuple[list[tuple[float, float]], float]:
    """Speech runs (start, end) in seconds from t0, and the median floor."""
    e = envelope_db(x, sr)
    if not len(e):
        return [], -120.0
    floor = local_floor(e)
    on = e > np.maximum(floor + SPEECH_OVER_FLOOR_DB, SPEECH_ABS_MIN_DBFS)
    runs = []
    idx = np.flatnonzero(np.diff(np.concatenate([[0], on.astype(np.int8), [0]])))
    for a, b in zip(idx[::2], idx[1::2]):
        runs.append((t0 + a * ENV_HOP_S, t0 + b * ENV_HOP_S))
    runs = [r for r in merge_runs(runs) if r[1] - r[0] >= SPEECH_MIN_RUN_S]
    return runs, round(float(np.median(floor)), 2)


def scdet_cuts(path: Path | str, a: float, d: float, start_time: float = 0.0) -> list[tuple[float, float]]:
    """(time, score) of every scene cut ffmpeg's scdet finds in [a, a + d], in the clip's own time."""
    r = subprocess.run([_ffmpeg(), "-hide_banner", "-nostats", "-copyts", "-ss", f"{max(0.0, a):.4f}", "-t", f"{d:.4f}", "-i", str(path),
                        "-an", "-vf", f"scale={ANALYSIS_WIDTH}:-2,scdet=threshold={SCDET_THRESHOLD:g}:sc_pass=0", "-f", "null", "-"],
                       capture_output=True, text=True, errors="replace")
    found = re.findall(r"lavfi\.scd\.score:\s*([\d.]+).*?lavfi\.scd\.time:\s*([-\d.]+)", r.stderr)
    return [(round(float(t) - start_time, 3), round(float(s), 2)) for s, t in found]


def default_cache_dir(film: Path) -> Path:
    env = os.environ.get("DOCUMENT_BOUNDS_CACHE")
    return Path(env) if env else Path(film) / "cache" / "bounds"


PARAMS = {"block_s": BLOCK_S, "scdet": SCDET_THRESHOLD, "width": ANALYSIS_WIDTH, "hop_s": ENV_HOP_S,
          "over_floor_db": SPEECH_OVER_FLOOR_DB, "abs_min_dbfs": SPEECH_ABS_MIN_DBFS, "floor_pct": SPEECH_FLOOR_PCT,
          "floor_win_s": SPEECH_FLOOR_WIN_S,
          "merge_s": SPEECH_MERGE_S, "min_run_s": SPEECH_MIN_RUN_S}


class ClipBounds:
    """A source clip's shot cuts and speech runs, analysed per block on
    demand and kept in its sidecar (``<cache>/<stem>.<key>.json``, key = the
    source's edge digest)."""

    def __init__(self, path: Path | str, cache_dir: Path | str, extra_cuts=(), *, journal=None, unit=None):
        from studio.engine.render import edge_digest
        self.path = Path(path)
        self.cache_dir = Path(cache_dir)
        self.edges = edge_digest(self.path)
        self.sidecar = self.cache_dir / f"{self.path.stem}.{self.edges[:16]}.json"
        self.extra_cuts = sorted(float(c) for c in extra_cuts)
        self.journal, self.unit = journal, unit
        self.analysed_now: list[int] = []
        data = None
        if self.sidecar.exists():
            try:
                data = json.loads(self.sidecar.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = None
        if not data or data.get("version") != BOUNDS_VERSION or data.get("edges") != self.edges or data.get("params") != PARAMS:
            pr = probe_media(self.path)
            data = {"version": BOUNDS_VERSION, "src": str(self.path), "edges": self.edges, "bytes": self.path.stat().st_size,
                    "params": PARAMS, "duration_s": pr["duration_s"], "start_time": pr["start_time"], "fps": pr["fps"],
                    "has_video": pr["has_video"], "has_audio": pr["has_audio"], "blocks": {}}
        self.data = data

    @property
    def duration(self) -> float:
        return float(self.data.get("duration_s") or 0.0)

    @property
    def has_audio(self) -> bool:
        return bool(self.data.get("has_audio"))

    def _save(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.sidecar.with_name(self.sidecar.name + ".part")
        tmp.write_text(json.dumps(self.data), encoding="utf-8")
        os.replace(tmp, self.sidecar)

    def ensure(self, a: float, b: float) -> None:
        dur = self.duration
        a, b = max(0.0, a), min(dur, b) if dur else b
        if b <= a:
            return
        todo = [k for k in range(int(a // BLOCK_S), int(math.ceil(b / BLOCK_S))) if str(k) not in self.data["blocks"]]
        for k in todo:
            ba, bb = k * BLOCK_S, min(dur, (k + 1) * BLOCK_S) if dur else (k + 1) * BLOCK_S
            st = float(self.data.get("start_time") or 0.0)
            blk: dict = {"a": ba, "b": bb, "cuts": [], "speech": [], "floor_db": None}
            if self.data.get("has_video"):
                pre = min(PREROLL_S, ba)
                cuts = scdet_cuts(self.path, ba - pre, bb - ba + pre, st)
                blk["cuts"] = [[t, s] for t, s in cuts if ba <= t < bb and t > 1e-3]
            if self.data.get("has_audio"):
                pa = max(0.0, ba - 1.0)
                x = read_pcm(self.path, pa, (bb + 1.0) - pa)
                runs, floor = speech_runs(x, pa)
                blk["speech"] = [[max(ba, r0), min(bb, r1)] for r0, r1 in runs if r1 > ba and r0 < bb]
                blk["floor_db"] = floor
            self.data["blocks"][str(k)] = blk
            self.analysed_now.append(k)
        if todo:
            self._save()
            if self.journal is not None:
                self.journal.decision("scout", f"analysed {self.path.name} blocks {todo} for cuts and speech",
                                      "A33: natural boundaries are measured on the source, once, and kept in its sidecar",
                                      unit=self.unit, evidence={"sidecar": str(self.sidecar), "blocks": todo, "params": PARAMS})

    def cuts(self, a: float = 0.0, b: float = float("inf")) -> list[float]:
        self.ensure(a, b if math.isfinite(b) else self.duration)
        out = {round(float(c), 3) for blk in self.data["blocks"].values() for c, _ in blk["cuts"]}
        out |= {round(c, 3) for c in self.extra_cuts}
        return sorted(c for c in out if a <= c <= b)

    def speech(self, a: float, b: float) -> list[tuple[float, float]]:
        self.ensure(a, b)
        runs = [tuple(r) for blk in self.data["blocks"].values() for r in blk["speech"]]
        return [r for r in merge_runs(runs) if r[1] > a and r[0] < b]


class StaticBounds:
    """Bounds given as data (tests, and a builder that measured them itself)."""

    def __init__(self, cuts=(), speech=(), duration: float = 3600.0, has_audio: bool = True):
        self._cuts = sorted(float(c) for c in cuts)
        self._speech = merge_runs([tuple(map(float, r)) for r in speech])
        self.duration = float(duration)
        self.has_audio = has_audio

    def ensure(self, a, b):
        pass

    def cuts(self, a=0.0, b=float("inf")):
        return [c for c in self._cuts if a <= c <= b]

    def speech(self, a, b):
        return [r for r in self._speech if r[1] > a and r[0] < b]


def extra_cuts_of(item: dict | None) -> tuple[list[float], str | None]:
    x = (item or {}).get("extra_cuts")
    if x is None:
        return [], None
    if not isinstance(x, list) or not all(isinstance(c, (int, float)) and not isinstance(c, bool) and math.isfinite(c) and c > 0
                                          for c in x):
        return [], "extra_cuts is a list of source times in seconds, each over 0"
    return [float(c) for c in x], None


def bounds_for(film: Path, item: dict, cache_dir: Path | None = None, *, journal=None, unit=None, _memo: dict | None = None):
    path = item.get("_path")
    if not path or not Path(path).exists():
        return None
    key = str(path)
    if _memo is not None and key in _memo:
        return _memo[key]
    cuts, _ = extra_cuts_of(item)
    b = ClipBounds(path, cache_dir or default_cache_dir(film), cuts, journal=journal, unit=unit)
    if _memo is not None:
        _memo[key] = b
    return b


# --------------------------------------------------------------------------
# What a builder calls
# --------------------------------------------------------------------------


def next_onset(b, t: float, horizon: float = 30.0) -> float | None:
    """The speaker's next word after t (the first speech run starting after t + 50 ms)."""
    for r0, _ in b.speech(t, t + horizon):
        if r0 > t + 0.05:
            return r0
    return None


def natural_out(b, t: float, *, talking_head: bool = False) -> dict:
    """A33(2): where a quote's picture ends, t being its last word (source
    time). The first source cut (or the clip's end) at or after t + 1.5 s, up
    to t + 6 s; with none in reach, t + 1.5 s and a ``cut_reason`` to declare.
    Where the source itself cuts sooner than 1.5 s after the last word, the
    picture ends with the source's shot, on that cut. A talking head ends
    before the speaker's next word instead (a mouth never moves without
    sound); a reading-hold shorter than 1.5 s is then the speaker's own pause."""
    lo, hi = t + NATURAL_MIN_S, t + NATURAL_MAX_S
    own = b.cuts(t + 1e-3, lo - 1e-3)
    ends = b.cuts(lo, hi) + ([b.duration] if b.duration and lo <= b.duration <= hi else [])
    if own:
        out = {"out_s": round(own[0], 3), "on": "cut", "cut_reason": None,
               "note": f"the source cuts {own[0] - t:.2f} s after the last word; the picture ends with its shot"}
    elif ends:
        c = min(ends)
        out = {"out_s": round(c, 3), "on": "clip end" if b.duration and abs(c - b.duration) < 1e-3 else "cut", "cut_reason": None}
    else:
        out = {"out_s": round(lo, 3), "on": None,
               "cut_reason": f"no source cut within {NATURAL_MAX_S:g} s of the last word; the picture holds {NATURAL_MIN_S:g} s (A10(2))"}
    if talking_head:
        nxt = next_onset(b, t)
        if nxt is not None and nxt - TH_RESUME_GUARD_S < out["out_s"]:
            end = max(t + QUOTE_TAIL_S, nxt - TH_RESUME_GUARD_S)
            out = {"out_s": round(end, 3), "on": "speaker's pause",
                   "cut_reason": f"talking head: ends {TH_RESUME_GUARD_S:g} s before the speaker's next word at {nxt:.2f} s"}
    out["last_word_s"] = round(t, 3)
    return out


def breathe_out(b, t: float) -> dict:
    """A33(3), the default for a narrated (non-quote) shot: t is where its
    narration would let it end (source time). It plays on to its source
    shot's natural end (the next cut, or the clip's end) unless that is more
    than 8 s further; then it ends at t with a ``cut_reason``, or on the cut
    just before t when t would leave a flash."""
    after = [c for c in b.cuts(t - 1e-3, t + BREATHE_MAX_S)] + ([b.duration] if b.duration and t <= b.duration <= t + BREATHE_MAX_S else [])
    if after:
        c = min(after)
        return {"out_s": round(c, 3), "on": "clip end" if b.duration and abs(c - b.duration) < 1e-3 else "cut", "cut_reason": None,
                "breath_s": round(c - t, 3)}
    before = [c for c in b.cuts(t - FLASH_S, t)]
    if before:
        return {"out_s": round(max(before), 3), "on": "cut", "cut_reason": None, "breath_s": round(max(before) - t, 3)}
    return {"out_s": round(t, 3), "on": None, "breath_s": 0.0,
            "cut_reason": f"the source shot runs more than {BREATHE_MAX_S:g} s past the narration; cut mid-shot at {t:.2f} s"}


def snap_in(b, t: float) -> dict:
    """An in point that never opens on a flash: a cut within 0.75 s either side of t becomes the in point."""
    near = b.cuts(t - FLASH_S, t + FLASH_S)
    if not near:
        return {"in_s": round(t, 3), "on": None}
    c = min(near, key=lambda c: abs(c - t))
    return {"in_s": round(c, 3), "on": "cut"}


def quote_edges(b, onset: float, offset: float) -> dict:
    """The audio in and out points for words measured from onset to offset (A33(2c))."""
    runs = b.speech(onset - 3.0, offset + 3.0)
    prev = max((r1 for r0, r1 in runs if r1 <= onset - 1e-3), default=None)
    nxt = min((r0 for r0, r1 in runs if r0 >= offset + 1e-3), default=None)
    i = onset - QUOTE_LEAD_S if prev is None or prev < onset - QUOTE_LEAD_S - EDGE_GUARD_S else max(prev + EDGE_GUARD_S, onset - QUOTE_LEAD_S)
    o = offset + QUOTE_TAIL_S if nxt is None or nxt > offset + QUOTE_TAIL_S + EDGE_GUARD_S else min(nxt - EDGE_GUARD_S, offset + QUOTE_TAIL_S)
    return {"in_s": round(min(i, onset - EDGE_MIN_LEAD_S), 3), "out_s": round(max(o, offset + EDGE_MIN_TAIL_S), 3)}


# --------------------------------------------------------------------------
# A/V offset: the ledger's av_offset_ms and the correction it implies
# --------------------------------------------------------------------------


def av_offset_problem(item: dict | None) -> str | None:
    x = (item or {}).get("av_offset_ms")
    if x is None:
        return None
    if not isinstance(x, (int, float)) or isinstance(x, bool) or not math.isfinite(x) or abs(x) > AV_OFFSET_ABS_MAX_MS:
        return f"av_offset_ms is a number of milliseconds (positive: the sound is late), at most {AV_OFFSET_ABS_MAX_MS:g} either way"
    return None


def av_correction_s(item: dict | None) -> float:
    """A33(1b): the seconds an archival line from this clip is placed EARLIER
    than its screenplay start to put its sound back on the picture (negative:
    later). Zero unless the ledger's lip-measured ``av_offset_ms`` lies
    outside -45 to +120 ms (BT.1359 detectability); then the measured offset
    less the envelope's natural lag behind the lips (80 ms)."""
    if av_offset_problem(item) is not None:
        return 0.0
    x = (item or {}).get("av_offset_ms")
    if x is None or -AV_LEAD_MAX_MS <= float(x) <= AV_LAG_MAX_MS:
        return 0.0
    return round((float(x) - LIPS_NATURAL_LAG_MS) / 1000.0, 4)


# --------------------------------------------------------------------------
# The plan-time rules (pure: shots, lines and bounds in, results out)
# --------------------------------------------------------------------------


def _flag(x) -> bool | None:
    return x if isinstance(x, bool) else None


def norm_shots(shots: list[dict], assets: dict) -> list[dict]:
    """Shots as the rules read them: film start and the next shot's start,
    and for clips the source in and out, sound mode, talking_head (the shot's,
    else its ledger item's) and cut_reason."""
    out = []
    for i, s in enumerate(shots):
        start = float(s["start_s"])
        dur = float(s["_dur"]) if "_dur" in s else (
            float(s["out_s"]) - float(s["in_s"]) if s.get("kind") == "archive_video" and "out_s" in s and "in_s" in s
            else float(s.get("dur_s", 0.0)))
        nxt = float(shots[i + 1]["start_s"]) if i + 1 < len(shots) else start + dur
        item = assets.get(s.get("asset")) or {}
        th = _flag(s.get("talking_head"))
        if th is None:
            th = _flag(item.get("talking_head"))
        out.append({"id": s["id"], "kind": s.get("kind"), "asset": s.get("asset"), "start": start, "end": start + dur, "next": nxt,
                    "in_s": float(s.get("in_s", 0.0) or 0.0), "out_s": float(s.get("out_s", 0.0) or 0.0),
                    "sound": (s.get("sound") or {}).get("mode", "own"), "talking_head": th,
                    "talking_head_stated": "talking_head" in s or "talking_head" in item, "cut_reason": s.get("cut_reason"),
                    "repeat_of": s.get("repeat_of"), "index": i})
    return out


def _r(x: float) -> float:
    return round(float(x), 3)


def check_clips(shots: list[dict], lines: list[dict], bounds: dict, items: dict | None = None) -> list[dict]:
    """Every A33 plan-time check, as {rule, ok, unit, severity, evidence}.
    ``shots`` come from ``norm_shots``; ``lines`` are the archival span
    lines (clip, in_s, out_s, start_s); ``bounds`` maps a clip id to its
    ClipBounds (or StaticBounds; None when the file is missing, which A26
    refuses on its own)."""
    items = items or {}
    res: list[dict] = []

    def add(rule, ok, unit, evidence, severity="block"):
        res.append({"rule": rule, "ok": bool(ok), "unit": unit, "severity": severity, "evidence": evidence, "grammar": "A33"})

    clips = [s for s in shots if s["kind"] == "archive_video"]
    arch = sorted(lines, key=lambda ln: float(ln["start_s"]))

    # (1) archival-sync and talking-head-declared, per line over its own clip's picture
    for ln in arch:
        ls, li, lo = float(ln["start_s"]), float(ln["in_s"]), float(ln["out_s"])
        over = [s for s in clips if s["asset"] == ln["clip"] and s["start"] < ls + (lo - li) - 1e-9 and s["next"] > ls + 1e-9]
        if not over:
            continue
        errs = []
        for s in over:
            err = (ls - s["start"]) - (li - s["in_s"])
            errs.append({"shot": s["id"], "error_ms": round(err * 1000), "film_offset_s": _r(ls - s["start"]),
                         "source_offset_s": _r(li - s["in_s"]), "ok": abs(err) <= SYNC_TOL_S + 1e-6,
                         "fix": None if abs(err) <= SYNC_TOL_S + 1e-6 else (
                             f"start {s['id']} at in_s {s['in_s'] - err:.3f} (picture {err * 1000:+.0f} ms) or lengthen the shot "
                             f"before it by {err:.3f} s and start {s['id']} that much later; never leave in_s fixed when a line moves")})
        add("archival-sync", all(e["ok"] for e in errs), ln["id"],
            {"line_start_s": ls, "in_s": li, "shots": errs, "tolerance_ms": round(SYNC_TOL_S * 1000, 1),
             "sign": "positive: the sound is heard after the picture shows it"})
        for s in over:
            add("talking-head-declared", s["talking_head_stated"] and s["talking_head"] is not None, s["id"],
                {"line": ln["id"], "talking_head": s["talking_head"],
                 "fix": None if s["talking_head"] is not None else
                 "state talking_head: true or false on the shot or its ledger item (is the speaker's mouth on screen?)"})

    # (2c) quote-edges, (2d) reading-hold
    for ln in arch:
        b = bounds.get(ln["clip"])
        if b is None or not b.has_audio:
            continue
        li, lo, ls = float(ln["in_s"]), float(ln["out_s"]), float(ln["start_s"])
        runs = b.speech(li - 3.0, lo + 3.0)
        inside = [r for r in runs if r[1] > li and r[0] < lo]
        problems, fix, last_off = [], {}, None
        if not inside:
            problems.append("no speech measured inside the span")
        else:
            cut_in = next((r for r in runs if r[0] < li - 1e-3 and r[1] > li + 1e-3), None)
            near_in = [r for r in runs if r[1] > li - EDGE_GUARD_S and r[0] < li]
            first = next((r for r in runs if r[0] >= li - 1e-3), None)
            if cut_in is not None:
                problems.append(f"the in point {li:.2f} cuts into speech that starts at {cut_in[0]:.2f} ({li - cut_in[0]:.2f} s clipped)")
                onset = cut_in[0]
            elif near_in:
                problems.append(f"speech ends {li - max(r[1] for r in near_in):.2f} s before the in point (under {EDGE_GUARD_S:g} s)")
                onset = first[0] if first else li
            else:
                onset = first[0] if first else li
                lead = onset - li
                if lead < EDGE_MIN_LEAD_S - 1e-6:
                    problems.append(f"the first word starts {lead:.2f} s after the in point: its attack is clipped")
                elif lead > QUOTE_LEAD_S + EDGE_SLACK_S + 1e-6:
                    problems.append(f"the in point is {lead:.2f} s before the first word, not on its edge ({QUOTE_LEAD_S:g} s)")
            cut_out = next((r for r in runs if r[0] < lo - 1e-3 and r[1] > lo + 1e-3), None)
            near_out = [r for r in runs if r[0] < lo + EDGE_GUARD_S and r[1] > lo]
            words = [r for r in inside if r[0] < lo - 1e-3]
            if cut_out is not None:
                prior = [r for r in words if r[1] <= cut_out[0] + 1e-3]
                leak = prior and lo - cut_out[0] <= 0.6 and cut_out[0] - prior[-1][1] >= 0.15
                problems.append(f"the out point {lo:.2f} cuts into speech running {cut_out[0]:.2f} to {cut_out[1]:.2f} "
                                + (f"(the next phrase: {lo - cut_out[0]:.2f} s of it is included)" if leak
                                   else f"({cut_out[1] - lo:.2f} s of the word clipped)"))
                offset = prior[-1][1] if leak else cut_out[1]
                last_off = prior[-1][1] if leak else lo              # a clipped last word ends where the audio does
            elif near_out:
                problems.append(f"speech starts {min(r[0] for r in near_out) - lo:.2f} s after the out point (under {EDGE_GUARD_S:g} s)")
                offset = last_off = max(r[1] for r in words) if words else lo
            else:
                offset = last_off = max(r[1] for r in words) if words else lo
                tail = lo - offset
                if tail < EDGE_MIN_TAIL_S - 1e-6:
                    problems.append(f"the out point is {tail:.2f} s after the last word: its tail is clipped")
                elif tail > QUOTE_TAIL_S + EDGE_SLACK_S + 1e-6:
                    problems.append(f"the out point is {tail:.2f} s after the last word, not on its edge ({QUOTE_TAIL_S:g} s)")
            fix = quote_edges(b, onset, offset)
        add("quote-edges", not problems, ln["id"],
            {"in_s": li, "out_s": lo, "speech": [list(r) for r in inside][:12], "problems": problems,
             "lead_s": QUOTE_LEAD_S, "tail_s": QUOTE_TAIL_S,
             "fix": None if not problems else dict(fix, why="audio in and out on speech edges, measured on the source, "
                                                              "never caption edges")})
        # reading-hold: the picture under the last word holds 1.5 s before the next cut the viewer sees (the film's, or
        # the source's own inside the shot); where the source itself cuts sooner, or a talking head starts again sooner,
        # the hold is that much (the picture ends with the source's shot, or before the mouth moves unheard)
        measured = last_off is not None
        if last_off is None:
            last_off = lo - QUOTE_TAIL_S
        lw = ls + (last_off - li)
        holder = next((s for s in shots if s["start"] <= lw + 1e-9 < s["next"]), shots[-1] if shots else None)
        if holder is None:
            continue
        seen_cut, need, why = holder["next"], READING_HOLD_S, "A10(2)"
        if holder["kind"] == "archive_video" and holder["asset"] == ln["clip"]:
            src_lw = holder["in_s"] + (lw - holder["start"])
            own = [c for c in b.cuts(src_lw + 1e-3, holder["out_s"])]
            src_cut = own[0] if own else None
            if src_cut is not None:
                seen_cut = min(seen_cut, holder["start"] + (src_cut - holder["in_s"]))
                if src_cut - src_lw < READING_HOLD_S:
                    need, why = src_cut - src_lw, f"the source cuts at {src_cut:.2f} s, {src_cut - src_lw:.2f} s after the last word"
            if holder["talking_head"]:
                nxt = next_onset(b, last_off)
                if nxt is not None and (src_cut is None or nxt < src_cut) and nxt - TH_RESUME_GUARD_S - last_off < need:
                    need = max(0.0, nxt - TH_RESUME_GUARD_S - last_off)
                    why = f"talking head: the speaker starts again at {nxt:.2f} s, so the hold is the speaker's own pause"
        hold = seen_cut - lw
        ok = hold >= need - 0.5 / 24
        add("reading-hold", ok, ln["id"],
            {"last_word_source_s": _r(last_off), "last_word_film_s": _r(lw), "measured": measured, "shot": holder["id"],
             "next_cut_s": _r(seen_cut), "hold_s": _r(hold), "need_s": _r(need), "why": why,
             "fix": None if ok else f"hold {holder['id']} {need - hold:.2f} s longer (natural_out), or end the line earlier; "
                                    "narration waits for the clip"})

    # (2a) clip-flash, (2b) clip-repeat, (2e) talking-head-silent, (3) clip-cut-mid-action
    by_clip: dict[str, list[dict]] = {}
    for s in clips:
        by_clip.setdefault(s["asset"], []).append(s)
        b = bounds.get(s["asset"])
        if b is None:
            continue
        ii, oo = s["in_s"], s["out_s"]
        cuts = [c for c in b.cuts(ii - FLASH_S, oo + FLASH_S) if 0 < c < (b.duration or float("inf")) - 1e-3]
        th_runs = b.speech(ii - FLASH_S, oo + FLASH_S) if s["talking_head"] and b.has_audio else []
        flashes = []
        # the in point: the nearest cut at or before it, and the first after it
        before = [c for c in cuts if c <= ii + ON_CUT_OUTSIDE_S]
        after = [c for c in cuts if c > ii + ON_CUT_OUTSIDE_S]
        if after and after[0] - ii < FLASH_S:
            flashes.append({"edge": "in", "cut_s": after[0], "what": f"opens on the last {after[0] - ii:.2f} s of the previous "
                            "source shot", "fix": f"in_s {after[0]:.3f}"})
        elif before and ON_CUT_INSIDE_S < ii - before[-1] < FLASH_S and \
                not any(before[-1] < r[1] and r[0] < ii for r in th_runs):
            flashes.append({"edge": "in", "cut_s": before[-1], "what": f"starts {ii - before[-1]:.2f} s after a source cut",
                            "fix": f"in_s {before[-1]:.3f} (on the cut)"})
        # the out point: the nearest cut at or after it, and the last before it
        before = [c for c in cuts if c < oo - ON_CUT_OUTSIDE_S]
        after = [c for c in cuts if c >= oo - ON_CUT_OUTSIDE_S]
        if before and oo - before[-1] < FLASH_S:
            flashes.append({"edge": "out", "cut_s": before[-1], "what": f"ends {oo - before[-1]:.2f} s into the next source shot",
                            "fix": f"out_s {before[-1]:.3f}"})
        elif after and ON_CUT_INSIDE_S < after[0] - oo < FLASH_S and \
                not any(oo < r[1] and r[0] < after[0] for r in th_runs):
            flashes.append({"edge": "out", "cut_s": after[0], "what": f"ends {after[0] - oo:.2f} s before a source cut",
                            "fix": f"out_s {after[0]:.3f} (on the cut)"})
        add("clip-flash", not flashes, s["id"], {"in_s": ii, "out_s": oo, "cuts_near": cuts, "flashes": flashes,
                                                 "within_s": FLASH_S})
        # clip-opens-on-a-tail (warning): the first source cut comes soon after the in point, past the flash window
        tail = [c for c in b.cuts(ii + FLASH_S, ii + NATURAL_MIN_S) if c < oo]
        add("clip-opens-on-a-tail", not tail or bool(s["cut_reason"]), s["id"],
            {"in_s": ii, "cut_s": tail[0] if tail else None, "cut_reason": s["cut_reason"],
             "fix": None if not tail else f"open on the cut (in_s {tail[0]:.3f}, snap_in), or declare cut_reason"}, severity="warn")
        # talking-head-silent
        if s["talking_head"] and b.has_audio and s["sound"] != "own":
            heard = [(float(ln["in_s"]), float(ln["out_s"])) for ln in arch if ln["clip"] == s["asset"]
                     and float(ln["start_s"]) < s["next"] and float(ln["start_s"]) + float(ln["out_s"]) - float(ln["in_s"]) > s["start"]]
            corr = av_correction_s(items.get(s["asset"]))
            lo_, hi_ = ii + corr, oo + corr                      # the mouth at picture p moves for the sound at p + offset
            pieces = []
            for r0, r1 in b.speech(lo_, hi_):
                segs = [(max(r0, lo_), min(r1, hi_))]
                for h0, h1 in heard:
                    segs = [x for a, z in segs for x in ((a, min(z, h0)), (max(a, h1), z)) if x[1] - x[0] > 1e-6]
                pieces += [p for p in segs if p[1] - p[0] > SILENT_TALK_MAX_S]
            add("talking-head-silent", not pieces, s["id"],
                {"in_s": ii, "out_s": oo, "unheard_speech_source_s": [[_r(a), _r(z)] for a, z in pieces][:12],
                 "unheard_s": _r(sum(z - a for a, z in pieces)), "heard": [list(h) for h in heard],
                 "fix": None if not pieces else "a talking head shows the speaker's mouth only while it is heard: end the shot "
                        "before the speaker starts again (natural_out(..., talking_head=True)), or open it after"})
        # clip-cut-mid-action (warning)
        nxt_shot = next((x for x in shots if x["start"] > s["start"] + 1e-9), None)
        continued = nxt_shot is not None and nxt_shot["kind"] == "archive_video" and nxt_shot["asset"] == s["asset"] \
            and abs(nxt_shot["in_s"] - oo) <= SYNC_TOL_S
        # the source shot's natural end: its next cut (one just before out is the flash lint's) or the clip's end, looked
        # for over the analysed 25 s past the out point; none there means more than 25 s of it is left unplayed
        horizon = oo + ANALYSIS_PAD_AFTER_S
        after = b.cuts(oo - FLASH_S, horizon) + ([b.duration] if b.duration and b.duration <= horizon else [])  # a held end too
        nat = min(after) if after else None
        left = (nat - oo) if nat is not None else ANALYSIS_PAD_AFTER_S
        ok = continued or left <= MID_ACTION_S + 1e-6 or bool(s["cut_reason"])
        add("clip-cut-mid-action", ok, s["id"],
            {"out_s": oo, "source_shot_ends_s": _r(nat) if nat is not None else f"over {ANALYSIS_PAD_AFTER_S:g} s on",
             "left_unplayed_s": _r(left) if nat is not None else f"over {ANALYSIS_PAD_AFTER_S:g}", "cut_reason": s["cut_reason"],
             "continued_by_next_shot": continued,
             "fix": None if ok else "let it play to its source shot's end (breathe_out), or declare cut_reason"}, severity="warn")
    for clip, ss in by_clip.items():
        for j, s in enumerate(ss):
            rep = [{"shot": t["id"], "overlap_s": _r(min(s["out_s"], t["out_s"]) - max(s["in_s"], t["in_s"])),
                    "adjacent": s["index"] - t["index"] == 1}
                   for t in ss[:j] if min(s["out_s"], t["out_s"]) - max(s["in_s"], t["in_s"]) > SYNC_TOL_S]
            # a refrain (the same image shown again, further on, on purpose) is declared: repeat_of names the earlier shot.
            # A shot never replays the one right before it: that is a backward jump, declared or not.
            refrain = s["repeat_of"] in {r["shot"] for r in rep if not r["adjacent"]}
            bad = [r for r in rep if r["adjacent"] or not refrain]
            add("clip-repeat", not bad, s["id"], {"clip": clip, "in_s": s["in_s"], "out_s": s["out_s"], "replays": rep,
                                                  "repeat_of": s["repeat_of"],
                                                  "fix": None if not bad else (
                                                      "a shot never replays the source of the shot right before it: start after "
                                                      "its out point, or merge them into one take" if any(r["adjacent"] for r in bad)
                                                      else "two shots of one clip share source time: a deliberate refrain names "
                                                           "the earlier shot in repeat_of")})
    # (1b) av-offset: stated on a talking-head clip whose words are heard on its picture
    th_clips = {s["asset"] for s in clips if s["talking_head"]} & {ln["clip"] for ln in arch}
    for clip in sorted({s["asset"] for s in clips} | {ln["clip"] for ln in arch}):
        item = items.get(clip) or {}
        why = av_offset_problem(item)
        if why:
            add("av-offset", False, clip, {"av_offset_ms": item.get("av_offset_ms"), "problem": why})
        elif clip in th_clips:
            stated = item.get("av_offset_ms") is not None
            add("av-offset", stated, clip, {"av_offset_ms": item.get("av_offset_ms"), "correction_s": av_correction_s(item),
                                            "window_ms": [-AV_LEAD_MAX_MS, AV_LAG_MAX_MS],
                                            "fix": None if stated else "measure it: python -m studio.engine.clips lipsync "
                                                                       "<film> <clip> --at A --dur D --face .. --mouth .. --write"},
                severity="block" if stated else "warn")
    return res


def span_lines(lines: list[dict]) -> list[dict]:
    """The archival lines A33 reads: a clip and a real span (A26 refuses the others on its own)."""
    out = []
    for ln in lines:
        if not (ln.get("archival_audio") and ln.get("clip")):
            continue
        try:
            a, b, st = float(ln["in_s"]), float(ln["out_s"]), float(ln["start_s"])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(a) and math.isfinite(b) and math.isfinite(st) and 0 <= a < b:
            out.append(ln)
    return out


def analysis_window(shots: list[dict], lines: list[dict], clip: str) -> tuple[float, float] | None:
    spans = [(s["in_s"] - ANALYSIS_PAD_BEFORE_S, s["out_s"] + ANALYSIS_PAD_AFTER_S) for s in shots
             if s["kind"] == "archive_video" and s["asset"] == clip]
    spans += [(float(ln["in_s"]) - 3.0, float(ln["out_s"]) + ANALYSIS_PAD_AFTER_S) for ln in lines if ln["clip"] == clip]
    if not spans:
        return None
    return max(0.0, min(a for a, _ in spans)), max(b for _, b in spans)


def gather_bounds(film: Path, shots: list[dict], lines: list[dict], assets: dict, *, cache_dir: Path | None = None,
                  journal=None) -> dict:
    out, memo = {}, {}
    for clip in sorted({s["asset"] for s in shots if s["kind"] == "archive_video"} | {ln["clip"] for ln in lines}):
        item = assets.get(clip)
        if not item:
            continue
        b = bounds_for(film, item, cache_dir, journal=journal, unit=clip, _memo=memo)
        if b is None:
            continue
        # only the windows the shots and lines need (a reel is analysed in 30 s blocks, never whole)
        for s in shots:
            if s["kind"] == "archive_video" and s["asset"] == clip:
                b.ensure(s["in_s"] - ANALYSIS_PAD_BEFORE_S, s["out_s"] + ANALYSIS_PAD_AFTER_S)
        for ln in lines:
            if ln["clip"] == clip:
                b.ensure(float(ln["in_s"]) - 3.0, float(ln["out_s"]) + ANALYSIS_PAD_AFTER_S)
        out[clip] = b
    return out


def plan_lints(lint, journal, film: Path, shots: list[dict], lines: list[dict], assets: dict) -> dict:
    """build_plan's call: every A33 check as a lint (blocking but for the
    clip-cut-mid-action warning and a missing av_offset_ms), and the
    warnings and extra_cuts problems returned for the report."""
    arch = span_lines(lines)
    for aid in sorted({s.get("asset") for s in shots if s.get("kind") == "archive_video"} | {ln["clip"] for ln in arch}):
        _, why = extra_cuts_of(assets.get(aid))
        if why:
            lint("extra-cuts", False, unit=aid, grammar="A33", evidence={"extra_cuts": (assets.get(aid) or {}).get("extra_cuts"),
                                                                        "problem": why})
    ns = norm_shots(shots, assets)
    bounds = gather_bounds(film, ns, arch, assets, journal=journal)
    results = check_clips(ns, arch, bounds, assets)
    for r in results:
        lint(r["rule"], r["ok"], unit=r["unit"], severity=r["severity"], evidence=r["evidence"], grammar="A33")
    warnings = [{"rule": r["rule"], "unit": r["unit"], **{k: v for k, v in r["evidence"].items() if k != "fix"}}
                for r in results if not r["ok"] and r["severity"] == "warn"]
    return {"warnings": warnings, "sidecars": {k: str(getattr(b, "sidecar", "")) for k, b in bounds.items()},
            "corrections": {aid: av_correction_s(assets.get(aid)) for aid in {ln["clip"] for ln in arch}
                            if av_correction_s(assets.get(aid))}}


# --------------------------------------------------------------------------
# Standalone check (read-only): the screenplay and its ledgers, no plan
# --------------------------------------------------------------------------


def screenplay_shots(play: dict, assets: dict) -> list[dict]:
    shots = []
    for part in play["parts"]:
        for s in part.get("shots", []):
            s = dict(s)
            if s.get("kind") == "archive_video":
                item = assets.get(s.get("asset")) or {}
                s["in_s"] = float(s.get("in_s", item.get("in_s", 0.0)))
                s["out_s"] = float(s.get("out_s", item.get("out_s", s["in_s"] + float(s.get("dur_s", 0)))))
                s["_dur"] = s["out_s"] - s["in_s"]
            else:
                s["_dur"] = float(s.get("dur_s", 0.0))
            shots.append(s)
    return shots


def check_film(film: Path, *, cache_dir: Path | None = None, play: dict | None = None) -> dict:
    """Every A33 plan-time check on a film's screenplay, read-only (the
    sidecars go to ``cache_dir``). Returns the results and a summary."""
    from studio.engine.render import load_ledgers
    film = Path(film)
    play = play if play is not None else json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    assets = load_ledgers(film, play)
    shots = screenplay_shots(play, assets)
    lines = span_lines([ln for part in play["parts"] for ln in part.get("lines", [])])
    ns = norm_shots(shots, assets)
    bounds = gather_bounds(film, ns, lines, assets, cache_dir=cache_dir)
    results = check_clips(ns, lines, bounds, assets)
    for aid in sorted({s["asset"] for s in ns if s["kind"] == "archive_video"} | {ln["clip"] for ln in lines}):
        _, why = extra_cuts_of(assets.get(aid))
        if why:
            results.append({"rule": "extra-cuts", "ok": False, "unit": aid, "severity": "block", "evidence": {"problem": why}})
    fails = [r for r in results if not r["ok"]]
    return {"film": str(film), "results": results,
            "blocking": [r for r in fails if r["severity"] == "block"], "warnings": [r for r in fails if r["severity"] == "warn"],
            "sidecars": {k: str(getattr(b, "sidecar", "")) for k, b in bounds.items()}}


# --------------------------------------------------------------------------
# Lip sync: the ledger's av_offset_ms, measured on the source
# --------------------------------------------------------------------------


def _ncc_argmax(S: np.ndarray, T: np.ndarray) -> tuple[int, int]:
    """Where template T (zero-mean) best matches inside S, by normalised cross-correlation (FFT)."""
    h, w = S.shape
    th, tw = T.shape
    F = np.fft.rfft2(S, s=(h, w))
    G = np.fft.rfft2(T[::-1, ::-1], s=(h, w))
    c = np.fft.irfft2(F * G, s=(h, w))[th - 1:, tw - 1:]
    ii = np.pad(np.cumsum(np.cumsum(S, 0), 1), ((1, 0), (1, 0)))
    i2 = np.pad(np.cumsum(np.cumsum(S * S, 0), 1), ((1, 0), (1, 0)))
    s1 = ii[th:, tw:] - ii[:-th, tw:] - ii[th:, :-tw] + ii[:-th, :-tw]
    s2 = i2[th:, tw:] - i2[:-th, tw:] - i2[th:, :-tw] + i2[:-th, :-tw]
    den = np.sqrt(np.maximum(s2 - s1 ** 2 / T.size, 1e-6))
    k = np.unravel_index(int(np.argmax(c / den)), c.shape)
    return int(k[0]), int(k[1])


def xcorr_lag(a: np.ndarray, b: np.ndarray, rate: float, max_lag_s: float = 0.6) -> tuple[float, float]:
    """The lag (s) at which b best follows a (positive: b is later), refined to a fraction of a sample, and its correlation."""
    a = (a - a.mean()) / (a.std() + 1e-9)
    b = (b - b.mean()) / (b.std() + 1e-9)
    L = int(max_lag_s * rate)
    res = []
    for l in range(-L, L + 1):
        res.append(float(np.mean(a[: len(a) - l] * b[l:])) if l >= 0 else float(np.mean(a[-l:] * b[: len(b) + l])))
    res = np.array(res)
    k = int(np.argmax(res))
    fr = 0.0
    if 0 < k < len(res) - 1:
        y0, y1, y2 = res[k - 1: k + 2]
        d = y0 - 2 * y1 + y2
        fr = 0.5 * (y0 - y2) / d if d else 0.0
    return (k - L + fr) / rate, float(res[k])


def lip_offset(path: Path | str, at: float, dur: float, face: tuple[int, int, int, int], mouth: tuple[int, int, int, int],
               *, search: int = 30) -> dict:
    """A33(1b): how late the sound runs behind the lips over [at, at + dur]
    of a talking-head clip (positive: late). The face box is tracked by
    template; the mouth box's openness (its share of pixels darker than 55%
    of its own 80th percentile: the open mouth's cavity) is cross-correlated
    with the audio envelope (25 ms RMS at each frame) over +-0.6 s. A source
    in sync reads about +80 ms: the envelope trails visible articulation."""
    pr = probe_media(Path(path))
    times, F = read_frames(path, at, dur, size=_native_size(path))
    if len(F) < 10:
        raise ValueError(f"no frames read from {path} at {at} s")
    fps = (len(times) - 1) / (times[-1] - times[0]) if len(times) > 1 and times[-1] > times[0] else (pr["fps"] or 25.0)
    H, W = F.shape[1:]
    x0, y0, x1, y1 = face
    T = F[0, y0:y1, x0:x1] - F[0, y0:y1, x0:x1].mean()
    th, tw = T.shape
    px, py = x0, y0
    pos = [(px, py)]
    for i in range(1, len(F)):
        ax, ay = max(0, px - search), max(0, py - search)
        bx, by = min(W, px + tw + search), min(H, py + th + search)
        dy, dx = _ncc_argmax(F[i, ay:by, ax:bx], T)
        py, px = ay + dy, ax + dx
        pos.append((px, py))
    mx0, my0, mx1, my1 = mouth[0] - x0, mouth[1] - y0, mouth[2] - x0, mouth[3] - y0
    M = np.array([F[i, p[1] + my0: p[1] + my1, p[0] + mx0: p[0] + mx1] for i, p in enumerate(pos)])
    ref = np.percentile(M, 80, axis=(1, 2))[:, None, None]
    openness = np.mean(M < ref * 0.55, axis=(1, 2))
    x = read_pcm(path, at, dur)
    sr = ENV_RATE
    t = times - at
    hw = int(sr * 0.025)
    env = np.array([np.sqrt(np.mean(x[max(0, int(tt * sr) - hw): int(tt * sr) + hw] ** 2) + 1e-12) if len(x) else 1e-6 for tt in t])
    env = 20 * np.log10(env)
    env = np.maximum(env, np.percentile(env, 20))
    lag, r = xcorr_lag(openness, env, fps)
    return {"av_offset_ms": int(round(lag * 1000)), "r": round(r, 3), "window_s": [round(at, 3), round(at + dur, 3)],
            "frames": int(len(F)), "fps": round(fps, 3), "face": list(face), "mouth": list(mouth),
            "head_travel_px": [int(v) for v in np.ptp(np.array(pos), axis=0)],
            "method": "mouth openness (dark share) x audio envelope, +-0.6 s (A33(1b))",
            "correction_s": av_correction_s({"av_offset_ms": int(round(lag * 1000))})}


def _native_size(path) -> tuple[int, int]:
    r = subprocess.run([_ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json",
                        str(path)], capture_output=True, text=True)
    st = json.loads(r.stdout)["streams"][0]
    return int(st["width"]), int(st["height"])


def write_av_offset(film: Path, play: dict, clip: str, measure: dict) -> Path:
    """Record a lipsync measurement on the clip's ledger item (av_offset_ms, av_offset_measure)."""
    refs = play.get("ledgers") or {}
    for name, ref in refs.items():
        path = Path(film) / (ref if isinstance(ref, str) else ref["path"])
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else (data.get("items") or data.get("assets") or [])
        for it in items:
            if it.get("id") == clip:
                it["av_offset_ms"] = measure["av_offset_ms"]
                it["av_offset_measure"] = {k: v for k, v in measure.items() if k != "av_offset_ms"} | {"measured": time.strftime("%Y-%m-%d")}
                path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
                return path
    raise KeyError(f"{clip} is in no ledger of {film}")


# --------------------------------------------------------------------------
# The render's own re-measurement (A33(1c))
# --------------------------------------------------------------------------


def measure_sync(master: Path | str, film_t: float, film_d: float, src: Path | str, src_base: float, in_s: float,
                 shot_start: float, crop: str | None, *, audio_t: float | None = None, src_crop: str | None = None) -> dict:
    """In the master over [film_t, film_t + film_d]: which source time the
    picture shows (each sampled frame matched to the source's own frames
    around the expected time) and which source time is heard (the master's
    audio cross-correlated with the source's), so ``audio_late_ms`` is how
    far the sound trails the picture (positive: late). ``src_base`` is the
    reel time the source file starts at (a cached span's offset).
    Inconclusive when the picture does not change enough to be matched (a
    still) or the sound does not correlate. ``crop`` takes the picture out
    of the master's frame; ``src_crop`` the same window out of the source's
    (a FILL's held end framing, A34)."""
    size = (160, 120)
    rt, RF = read_frames(master, film_t, film_d, size=size, crop=crop)
    exp = in_s + (film_t - shot_start)
    st, SF = read_frames(src, exp - src_base - 1.5, film_d + 3.0, size=size, crop=src_crop)
    st = st + src_base
    out = {"picture_src_minus_film": None, "audio_src_minus_film": None, "audio_late_ms": None, "conclusive": False}
    if len(RF) >= 6 and len(SF) >= 6:
        offs, sharp = [], []
        for i in range(0, len(RF), 3):
            e = np.mean((SF - RF[i]) ** 2, axis=(1, 2))
            k = int(np.argmin(e))
            offs.append(st[k] - rt[i])
            far = e[np.abs(st - st[k]) > 0.2]
            sharp.append(float(np.min(far) / max(e[k], 1e-6)) if len(far) else 1.0)
        offs = np.array(offs)
        pic = float(np.median(offs))
        spread = float(np.percentile(offs, 75) - np.percentile(offs, 25))
        out.update(picture_src_minus_film=round(pic, 4), picture_spread_s=round(spread, 4),
                   picture_sharpness=round(float(np.median(sharp)), 2))
        pic_ok = spread <= 0.06 and np.median(sharp) >= 1.5
    else:
        pic_ok = False
    a0 = film_t + 0.3 if audio_t is None else audio_t
    ra = read_pcm(master, a0, min(3.0, film_d - 0.3))
    sa = read_pcm(src, exp + (a0 - film_t) - src_base - 0.7, min(3.0, film_d - 0.3) + 1.4)
    aud_ok = False
    if len(ra) > ENV_RATE and len(sa) > len(ra):
        n = len(sa) + len(ra)
        nf = 1 << (n - 1).bit_length()
        c = np.fft.irfft(np.fft.rfft(sa, nf) * np.conj(np.fft.rfft(ra, nf)), nf)[: len(sa) - len(ra) + 1]
        k = int(np.argmax(c))
        win = sa[k: k + len(ra)]
        r = float(c[k] / (np.linalg.norm(win) * np.linalg.norm(ra) + 1e-12))
        aud = (exp + (a0 - film_t) - 0.7 + k / ENV_RATE) - a0
        out.update(audio_src_minus_film=round(aud, 4), audio_r=round(r, 3))
        aud_ok = r >= 0.3
    if out["picture_src_minus_film"] is not None and out["audio_src_minus_film"] is not None:
        out["audio_late_ms"] = int(round((out["picture_src_minus_film"] - out["audio_src_minus_film"]) * 1000))
    out["conclusive"] = bool(pic_ok and aud_ok)
    return out


def rendered_sync_lints(journal, plan: dict, master: Path, *, draft: bool = False) -> list[str]:
    """A33(1c): every archival line heard over its own clip's picture is
    measured in the master; its offset is journaled, and a conclusive one
    more than 45 ms from the correction applied refuses a final render."""
    from studio.engine.render import clip_file
    refusals = []
    W, H = plan["W"], plan["H"]
    for ln in span_lines(plan["lines"]):
        corr = av_correction_s(plan["assets"].get(ln["clip"]))
        ls = float(ln["start_s"]) - corr
        dur = float(ln["out_s"]) - float(ln["in_s"])
        holder = next((s for s in plan["shots"] if s["kind"] == "archive_video" and s.get("asset") == ln["clip"]
                       and s["f0"] / 24 <= ls + 0.3 < s["f1"] / 24), None)
        if holder is None:
            continue
        a, z = max(ls, holder["f0"] / 24), min(ls + dur, holder["f1"] / 24)
        if z - a < RENDER_SYNC_MIN_S:
            journal.lint("archival-sync-rendered", True, stage="assembly", unit=ln["id"], grammar="A33", phase="post-render",
                         status="inconclusive", severity="warn",
                         evidence={"why": f"under {RENDER_SYNC_MIN_S:g} s of the line on its own picture", "shot": holder["id"]})
            continue
        vw, vh = holder["_video"]["fit"]
        crop = f"{vw}:{vh}:{(W - vw) // 2}:{(H - vh) // 2}"
        src_crop = None
        cam = holder.get("_cam")
        if cam is not None and len(cam["path"]) > 1:
            # A34: a FILL clip is whole only in its opening and still only once the fill holds; it is measured in
            # whichever of the two holds enough of the line, never during the move
            f0 = holder["f0"] / 24
            opened, held = f0 + cam["open_s"], f0 + cam["open_s"] + cam["move_s"]
            if min(z, opened) - a >= RENDER_SYNC_MIN_S + 0.3:
                z = min(z, opened)
            elif z - max(a, held) >= RENDER_SYNC_MIN_S + 0.3:
                a = max(a, held)
                (x0, y0, x1, y1), (pw, ph) = cam["fill"]["end_window_px"], cam["fill"]["picture"]
                crop = None
                src_crop = (f"iw*{(x1 - x0) / pw:.6f}:ih*{(y1 - y0) / ph:.6f}:iw*{x0 / pw:.6f}:ih*{y0 / ph:.6f}")
            else:
                journal.lint("archival-sync-rendered", True, stage="assembly", unit=ln["id"], grammar="A33, A34",
                             phase="post-render", status="inconclusive", severity="warn",
                             evidence={"why": "the line sits on the FILL's move, where no frame is still to match",
                                       "shot": holder["id"]})
                continue
        src, base = clip_file(holder)
        m = measure_sync(master, a + 0.15, min(4.0, z - a - 0.3), src, base, holder["in_s"], holder["f0"] / 24, crop,
                         src_crop=src_crop)
        expected = -corr * 1000
        ok = (m["audio_late_ms"] is not None and abs(m["audio_late_ms"] - expected) <= RENDER_SYNC_TOL_MS)
        ev = dict(m, shot=holder["id"], expected_ms=round(expected), tolerance_ms=RENDER_SYNC_TOL_MS, correction_s=corr)
        if not m["conclusive"]:
            journal.lint("archival-sync-rendered", True, stage="assembly", unit=ln["id"], grammar="A33", phase="post-render",
                         status="inconclusive", severity="warn", evidence=ev)
            continue
        sev = "warn" if draft else "block"
        journal.lint("archival-sync-rendered", ok, stage="assembly", unit=ln["id"], grammar="A33", phase="post-render",
                     severity=sev, evidence=ev)
        if not ok and not draft:
            refusals.append(f"{ln['id']} is heard {m['audio_late_ms']:+d} ms against its picture (expected {expected:+.0f})")
    return refusals


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _clip_bounds(film: Path, clip: str, cache: str | None):
    from studio.engine.render import load_ledgers
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    assets = load_ledgers(film, play)
    if clip not in assets:
        raise SystemExit(f"{clip} is in no ledger of {film}")
    b = bounds_for(film, assets[clip], Path(cache) if cache else None)
    if b is None:
        raise SystemExit(f"{clip}: the file is missing")
    return b, assets[clip], play


def _box(s: str) -> tuple[int, int, int, int]:
    v = [int(x) for x in s.split(",")]
    if len(v) != 4:
        raise argparse.ArgumentTypeError("x0,y0,x1,y1")
    return v[0], v[1], v[2], v[3]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m studio.engine.clips", description=__doc__.split("\n\n")[0])
    ap.add_argument("--cache", help="sidecar folder (default <film>/cache/bounds, or DOCUMENT_BOUNDS_CACHE)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("bounds", help="a clip's cuts and speech runs")
    p.add_argument("film"); p.add_argument("clip")
    p.add_argument("--from", dest="a", type=float, default=0.0); p.add_argument("--to", dest="b", type=float, default=None)
    p = sub.add_parser("natural-out", help="where a quote's picture ends, t = its last word")
    p.add_argument("film"); p.add_argument("clip"); p.add_argument("t", type=float); p.add_argument("--talking-head", action="store_true")
    p = sub.add_parser("breathe", help="where a narrated shot ends, t = where its narration lets it")
    p.add_argument("film"); p.add_argument("clip"); p.add_argument("t", type=float)
    p = sub.add_parser("snap-in", help="an in point that never opens on a flash")
    p.add_argument("film"); p.add_argument("clip"); p.add_argument("t", type=float)
    p = sub.add_parser("plan", help="answer a JSON list of {op, clip, t, talking_head} requests in one call (builders)")
    p.add_argument("film"); p.add_argument("requests")
    p = sub.add_parser("check", help="every A33 plan-time check on a film, read-only")
    p.add_argument("film"); p.add_argument("--json", dest="json_out")
    p = sub.add_parser("lipsync", help="measure a talking-head clip's av_offset_ms")
    p.add_argument("film"); p.add_argument("clip"); p.add_argument("--at", type=float, required=True)
    p.add_argument("--dur", type=float, required=True); p.add_argument("--face", type=_box, required=True)
    p.add_argument("--mouth", type=_box, required=True); p.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    film = Path(a.film).resolve()
    if a.cmd == "check":
        rep = check_film(film, cache_dir=Path(a.cache) if a.cache else None)
        for r in rep["blocking"] + rep["warnings"]:
            ev = {k: v for k, v in r["evidence"].items() if v not in (None, [], {})}
            print(f"{r['severity'].upper():5} {r['rule']:24} {r['unit']:10} {json.dumps(ev, ensure_ascii=False)[:600]}")
        print(f"{len(rep['blocking'])} blocking, {len(rep['warnings'])} warnings, {len(rep['results'])} checks")
        if a.json_out:
            Path(a.json_out).write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
        return 1 if rep["blocking"] else 0
    if a.cmd == "plan":
        reqs = json.loads(Path(a.requests).read_text(encoding="utf-8"))
        answers, memo = [], {}
        for q in reqs:
            if q["clip"] not in memo:
                memo[q["clip"]] = _clip_bounds(film, q["clip"], a.cache)[0]
            b = memo[q["clip"]]
            fn = {"natural_out": lambda: natural_out(b, float(q["t"]), talking_head=bool(q.get("talking_head"))),
                  "breathe_out": lambda: breathe_out(b, float(q["t"])), "snap_in": lambda: snap_in(b, float(q["t"])),
                  "quote_edges": lambda: quote_edges(b, float(q["onset"]), float(q["offset"])),
                  "speech": lambda: {"speech": [list(r) for r in b.speech(float(q["from"]), float(q["to"]))]},
                  "cuts": lambda: {"cuts": b.cuts(float(q["from"]), float(q["to"]))}}[q["op"]]
            answers.append(dict(q, **fn()))
        print(json.dumps(answers, ensure_ascii=False))
        return 0
    b, item, play = _clip_bounds(film, a.clip, a.cache)
    if a.cmd == "bounds":
        to = a.b if a.b is not None else b.duration
        print(json.dumps({"clip": a.clip, "duration_s": b.duration, "cuts": b.cuts(a.a, to),
                          "speech": [list(r) for r in b.speech(a.a, to)], "sidecar": str(b.sidecar)}, ensure_ascii=False))
    elif a.cmd == "natural-out":
        print(json.dumps(natural_out(b, a.t, talking_head=a.talking_head)))
    elif a.cmd == "breathe":
        print(json.dumps(breathe_out(b, a.t)))
    elif a.cmd == "snap-in":
        print(json.dumps(snap_in(b, a.t)))
    elif a.cmd == "lipsync":
        m = lip_offset(item["_path"], a.at, a.dur, a.face, a.mouth)
        print(json.dumps(m))
        if a.write:
            print(f"written to {write_av_offset(film, play, a.clip, m)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
