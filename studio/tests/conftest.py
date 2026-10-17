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


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    """Each worktree's suite gets its own temp root, and pytest keeps its
    numbered, pruned sessions inside it. Under the shared root
    ``pytest-of-<user>``, pytest keeps only the 3 newest sessions, so with
    builders testing in parallel worktrees one session pruned another's live
    folder mid-run (ENGINE-LOG 2026-10-11: test_a_synthetic_still_cannot_be_marked_archive
    lost its stills, FileNotFoundError). PYTEST_DEBUG_TEMPROOT set by the
    caller, or a ``--basetemp``, still wins."""
    if not os.environ.get("PYTEST_DEBUG_TEMPROOT"):
        import hashlib
        import tempfile
        key = hashlib.sha256(str(ROOT).lower().encode()).hexdigest()[:10]
        root = Path(tempfile.gettempdir()) / f"document-studio-tests-{key}"
        prune_orphan_roots(root.parent, keep=root)
        root.mkdir(parents=True, exist_ok=True)
        tmp = root / f"{ROOT_MARKER}.{os.getpid()}"
        tmp.write_text(str(ROOT), encoding="utf-8")
        os.replace(tmp, root / ROOT_MARKER)   # atomic: a crash never leaves a truncated path
        os.environ["PYTEST_DEBUG_TEMPROOT"] = str(root)


ROOT_MARKER = "worktree.txt"
UNMARKED_MAX_AGE_S = 24 * 3600


def prune_orphan_roots(parent: Path, keep: Path, now: float | None = None) -> list[Path]:
    """Remove the temp roots of worktrees that no longer exist. Every worktree
    gets its own root (above) and each holds a rendered fixture film, so roots
    outlived their removed worktrees and filled C: (backlog 2026-10-17). A root
    names its worktree in ``worktree.txt``; it goes when that path is gone. A
    root from before the marker goes once it is a day unused (any live
    worktree writes its marker on its next run). Use is read from the newest
    mtime of the root, its ``pytest-of-*`` folders and their sessions, since
    pytest makes a new numbered session folder on every run (old code
    included); the root's own mtime alone never moves once it exists.
    Passing sessions inside a live root are removed by pytest itself
    (``tmp_path_retention_policy = failed`` in the repo's pytest.ini)."""
    import time
    now = time.time() if now is None else now
    gone = []
    for r in parent.glob("document-studio-tests-*"):
        if r == keep or not r.is_dir():
            continue
        marker = r / ROOT_MARKER
        try:
            if marker.is_file():
                orphan = not Path(marker.read_text(encoding="utf-8").strip()).exists()
            else:
                orphan = now - last_used(r) > UNMARKED_MAX_AGE_S
        except OSError:
            continue
        if orphan:
            shutil.rmtree(r, ignore_errors=True)
            gone.append(r)
    return gone


def last_used(root: Path) -> float:
    """The newest mtime among a temp root, its ``pytest-of-*`` folders and the
    numbered sessions inside them."""
    times = [root.stat().st_mtime]
    for user in root.glob("pytest-of-*"):
        times.append(user.stat().st_mtime)
        times += [s.stat().st_mtime for s in user.iterdir()]
    return max(times)


@pytest.fixture(scope="session", autouse=True)
def _isolated_logs(tmp_path_factory):
    logs = tmp_path_factory.mktemp("logs")
    old = {k: os.environ.get(k) for k in ("DOCUMENT_JOURNAL_DIR", "DOCUMENT_TIMINGS", "DOCUMENT_FILMS")}
    os.environ["DOCUMENT_JOURNAL_DIR"] = str(logs / "journal")
    os.environ["DOCUMENT_TIMINGS"] = str(logs / "timings.jsonl")
    # bed-reuse (A29 refined) reads the other films; a test names its own, never the working films in films.json
    os.environ["DOCUMENT_FILMS"] = ""
    yield logs
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def tone(path: Path, seconds: float, hz: float = 440.0) -> Path:
    """A test tone standing in for a voice WAV, shaped like a take: 0.25 s of
    silence at each end (inside ``seconds``) and a 0.2 s pause between two
    "words" in the middle, so A19's cleanup can measure a floor inside the
    take's live span (padding at the ends is never the floor, T1f) and the
    line passes voice-clean as a clean take does."""
    import soundfile as sf
    path.parent.mkdir(parents=True, exist_ok=True)
    t = np.arange(int(48000 * seconds)) / 48000
    x = 0.2 * np.sin(2 * np.pi * hz * t)
    x[(t < 0.25) | (t >= seconds - 0.25) | (np.abs(t - seconds / 2) < 0.1)] = 0.0
    sf.write(str(path), x.astype("float32"), 48000)
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
