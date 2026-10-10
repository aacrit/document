"""Shared fixtures: the fixture film copied to a temp folder, its synthetic
clip and test tone made there, and one small render (640x360) that most
tests read. Journals and timings go to the temp folder, never ~/document-work."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).resolve().parent / "fixture"
for p in (ROOT, FIXTURE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

HEIGHT = 360          # "render the fixture small"
WORKERS = 2


@pytest.fixture(scope="session", autouse=True)
def _isolated_logs(tmp_path_factory):
    logs = tmp_path_factory.mktemp("logs")
    old = {k: os.environ.get(k) for k in ("DOCUMENT_JOURNAL_DIR", "DOCUMENT_TIMINGS")}
    os.environ["DOCUMENT_JOURNAL_DIR"] = str(logs / "journal")
    os.environ["DOCUMENT_TIMINGS"] = str(logs / "timings.jsonl")
    yield logs
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def tone(path: Path, seconds: float, hz: float = 440.0) -> Path:
    """A test tone standing in for a voice WAV."""
    import soundfile as sf
    path.parent.mkdir(parents=True, exist_ok=True)
    t = np.arange(int(48000 * seconds)) / 48000
    sf.write(str(path), (0.2 * np.sin(2 * np.pi * hz * t)).astype("float32"), 48000)
    return path


def make_film(dest: Path) -> Path:
    """A working copy of the fixture film with its generated media: the test
    stills, the testsrc clip and a tone for each voice line (the ambience cue
    C1 stays missing, a warning)."""
    import make_media
    shutil.copytree(FIXTURE, dest, ignore=shutil.ignore_patterns("__pycache__", "stills", "footage", "audio", "out"))
    make_media.film(dest)
    tone(dest / "audio" / "L1.wav", 2.0)
    tone(dest / "audio" / "L2.wav", 1.2, 330.0)
    return dest


@pytest.fixture(scope="session")
def film(tmp_path_factory) -> Path:
    return make_film(tmp_path_factory.mktemp("film") / "fixture")


@pytest.fixture(scope="session")
def rendered(film, tmp_path_factory) -> dict:
    from studio.engine.render import render
    out = tmp_path_factory.mktemp("out")
    summary = render(film, out, height=HEIGHT, workers=WORKERS, min_free_gb=1, encode_preset="veryfast")
    summary["out"] = out
    return summary


@pytest.fixture(scope="session")
def plan(film):
    from studio.engine.journal import Journal
    from studio.engine.render import build_plan, frame_size
    W, H = frame_size(HEIGHT)
    j = Journal(film="fixture-plan")
    return build_plan(film, W=W, H=H, burn_subtitles=False, journal=j)
