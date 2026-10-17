"""The suite's temp roots do not outlive their worktrees (backlog 2026-10-17:
the test temp-dir leak filled C:)."""

import configparser
import os
import time
from pathlib import Path

from conftest import ROOT_MARKER, UNMARKED_MAX_AGE_S, prune_orphan_roots


def _root(parent: Path, name: str, worktree: Path | None = None, age_s: float = 0) -> Path:
    r = parent / f"document-studio-tests-{name}"
    (r / "pytest-of-me" / "pytest-1").mkdir(parents=True)
    if worktree is not None:
        (r / ROOT_MARKER).write_text(str(worktree), encoding="utf-8")
    t = time.time() - age_s
    os.utime(r, (t, t))
    return r


def test_a_root_whose_worktree_is_gone_is_removed(tmp_path):
    live_tree = tmp_path / "live-tree"; live_tree.mkdir()
    live = _root(tmp_path, "live", live_tree)
    orphan = _root(tmp_path, "orphan", tmp_path / "removed-tree")
    gone = prune_orphan_roots(tmp_path, keep=tmp_path / "document-studio-tests-mine")
    assert gone == [orphan] and not orphan.exists() and live.exists()


def test_an_unmarked_root_goes_only_once_a_day_old(tmp_path):
    fresh = _root(tmp_path, "fresh", age_s=60)
    stale = _root(tmp_path, "stale", age_s=UNMARKED_MAX_AGE_S + 60)
    prune_orphan_roots(tmp_path, keep=tmp_path / "x")
    assert fresh.exists() and not stale.exists()


def test_the_running_root_and_other_folders_are_never_touched(tmp_path):
    mine = _root(tmp_path, "mine", tmp_path / "removed-tree")
    other = tmp_path / "something-else"; other.mkdir()
    assert prune_orphan_roots(tmp_path, keep=mine) == []
    assert mine.exists() and other.exists()


def test_this_session_runs_in_a_marked_root():
    root = Path(os.environ["PYTEST_DEBUG_TEMPROOT"])
    if root.name.startswith("document-studio-tests-"):
        assert Path((root / ROOT_MARKER).read_text(encoding="utf-8")) == Path(__file__).resolve().parents[2]


def test_passing_sessions_leave_no_temp_folder():
    ini = configparser.ConfigParser()
    ini.read(Path(__file__).with_name("pytest.ini"), encoding="utf-8")
    assert ini["pytest"]["tmp_path_retention_policy"] == "failed"
