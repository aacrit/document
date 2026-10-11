"""The engine journal: one JSON line per thing that happens in a studio run.

    ~/document-work/journal/<run>.jsonl      (DOCUMENT_JOURNAL_DIR overrides the folder)
    ~/document-work/timings.jsonl            (DOCUMENT_TIMINGS overrides the file)

Never committed. Decision "Capture every log" (docs/DECISIONS.md) is the
spec; design/spec.md 5a (Lens events) and 5e (timing ledger) are the contracts.

Every event carries:
    v, run, seq, kind, stage, unit, mono_s (monotonic seconds since the run
    started), wall (ISO time with offset)
and, where it applies, the payload fields ``size`` (in the stage's cost
driver), ``model`` (name and version), ``settings``, ``machine`` (GPU from
nvidia-smi, CPU, free disk on the output drive) and ``outcome``.

``kind`` is one of KINDS. Events the Director's Lens consumes also carry
``lens``: the Lens event type (``run.start``, ``stage``, ``unit.start``,
``unit.done``, ``frame``, ``marks``, ``error``, ``run.end``), so the Lens
can replay a journal as its SSE stream.

Every finished unit also appends one record to ``timings.jsonl`` (spec 5e,
plus the flat fields ``studio/sketch.py`` writes), so the predictor keeps one
input whichever renderer ran.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import threading
import time
import traceback
import uuid
from contextlib import contextmanager
from pathlib import Path

SCHEMA_V = 1
KINDS = ("stage", "unit", "timing", "lint", "retry", "error", "decision", "human", "artifact")


def journal_dir() -> Path:
    return Path(os.environ.get("DOCUMENT_JOURNAL_DIR") or Path.home() / "document-work" / "journal")


def timings_path() -> Path:
    return Path(os.environ.get("DOCUMENT_TIMINGS") or Path.home() / "document-work" / "timings.jsonl")


def _iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def new_run_id() -> str:
    return "r-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]


# --------------------------------------------------------------------------
# Machine conditions
# --------------------------------------------------------------------------

_GPU_CACHE: dict = {"at": -1e9, "value": None}
_GPU_TTL_S = 5.0


def gpu() -> dict | None:
    """nvidia-smi as studio/sketch.py's machine() reads it; cached for 5 s so a
    busy run does not spawn nvidia-smi for every event. None without a GPU."""
    now = time.monotonic()
    if now - _GPU_CACHE["at"] < _GPU_TTL_S:
        return _GPU_CACHE["value"]
    value = None
    try:
        q = subprocess.run(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,"
                            "clocks_throttle_reasons.active", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=5).stdout.strip().splitlines()[0]
        name, util, mem, total, temp, thr = [x.strip() for x in q.split(",")]
        value = {"name": name, "util": int(util), "vram_used_mb": int(mem), "vram_total_mb": int(total),
                 "temp_c": int(temp), "throttle": thr}
    except Exception:
        value = None
    _GPU_CACHE.update(at=now, value=value)
    return value


def machine(out_dir: Path | str | None = None) -> dict:
    """Conditions now: GPU, CPU, load and free disk on the output drive."""
    m: dict = {"host": platform.node(), "os": platform.platform(terse=True), "cpu": platform.processor() or platform.machine(),
               "cpus": os.cpu_count(), "gpu": gpu()}
    try:
        m["load_avg_1m"] = round(os.getloadavg()[0], 2)
    except (AttributeError, OSError):
        m["load_avg_1m"] = None
    if out_dir is not None:
        p = Path(out_dir)
        while not p.exists() and p != p.parent:
            p = p.parent
        try:
            du = shutil.disk_usage(p)
            m["disk"] = {"drive": Path(p).resolve().anchor, "free_gb": round(du.free / 1024 ** 3, 2),
                         "total_gb": round(du.total / 1024 ** 3, 2)}
        except OSError:
            m["disk"] = None
    return m


def sha256_file(path: Path | str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


# --------------------------------------------------------------------------
# The journal
# --------------------------------------------------------------------------


class Unit:
    """Handle yielded by ``Journal.unit``. Set ``size``, ``outcome``,
    ``wall_s`` (to report a time measured elsewhere, such as in a worker
    process) or add fields to ``extra`` before the block ends."""

    def __init__(self, stage: str, unit_id: str, size: dict | None, model: dict | None, settings: dict | None):
        self.stage, self.unit_id = stage, unit_id
        self.size = dict(size or {})
        self.model, self.settings = model, settings
        self.outcome = "ok"
        self.wall_s: float | None = None
        self.extra: dict = {}


class Journal:
    """Append-only JSONL writer for one run. Single writer: worker processes
    send their events to the parent, which writes them here."""

    def __init__(self, run: str | None = None, *, film: str = "", kind: str = "render", out_dir: Path | str | None = None,
                 directory: Path | str | None = None, timings: Path | str | None = None, renderer: str = "studio.engine"):
        self.run = run or new_run_id()
        self.film, self.kind, self.renderer = film, kind, renderer
        self.out_dir = Path(out_dir) if out_dir else None
        self.dir = Path(directory) if directory else journal_dir()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / f"{self.run}.jsonl"
        self.timings = Path(timings) if timings else timings_path()
        self.timings.parent.mkdir(parents=True, exist_ok=True)
        self._t0 = time.monotonic()
        self._seq = 0
        self._lock = threading.Lock()
        self.counts: dict[str, int] = {}

    # -- core ---------------------------------------------------------------

    def event(self, kind: str, stage: str, unit: str | None = None, *, lens: str | None = None, **payload) -> dict:
        if kind not in KINDS:
            raise ValueError(f"journal: unknown event kind {kind!r}")
        with self._lock:
            self._seq += 1
            ev = {"v": SCHEMA_V, "run": self.run, "seq": self._seq, "kind": kind, "stage": stage, "unit": unit,
                  "mono_s": round(time.monotonic() - self._t0, 4), "wall": _iso()}
            if lens:
                ev["lens"] = lens
            ev.update(payload)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")
            self.counts[kind] = self.counts.get(kind, 0) + 1
        return ev

    def machine(self) -> dict:
        return machine(self.out_dir)

    # -- helpers per kind ---------------------------------------------------

    def stage(self, stage: str, status: str, *, lens: str = "stage", **payload) -> dict:
        """status: start, done, skip or fail (design/spec.md 5a)."""
        return self.event("stage", stage, None, lens=lens, status=status, machine=self.machine(), **payload)

    def lint(self, rule: str, passed: bool, *, stage: str = "marks", unit: str | None = None, severity: str = "block",
             evidence=None, grammar: str | None = None, phase: str | None = None, status: str | None = None) -> dict:
        """severity: block (fails the render), warn (journaled, render goes on)
        or review (a reviewer-check item: the engine cannot judge it). phase:
        preflight (decided from the plan before any frame is rendered) or
        post-render (a second confirmation on the rendered pixels). status
        overrides the result: ``inconclusive`` when the check could not
        measure (it does not block; another check stays authoritative)."""
        status = status or ("review" if severity == "review" else ("pass" if passed else "fail"))
        extra = {"phase": phase} if phase else {}
        return self.event("lint", stage, unit, rule=rule, status=status, severity=severity, grammar=grammar,
                          evidence=evidence, **extra)

    def decision(self, stage: str, what: str, why: str, *, who: str = "engine", unit: str | None = None, **payload) -> dict:
        return self.event("decision", stage, unit, who=who, what=what, why=why, **payload)

    def human(self, stage: str, what: str, *, unit: str | None = None, **payload) -> dict:
        return self.event("human", stage, unit, what=what, **payload)

    def retry(self, stage: str, unit: str | None, attempt: int, error: str, *, fix: str | None = None, **payload) -> dict:
        return self.event("retry", stage, unit, attempt=attempt, error=error, fix=fix, **payload)

    def error(self, stage: str, unit: str | None, exc: BaseException | str, *, fix: str | None = None,
              resume: str | None = None, tb: str | None = None) -> dict:
        if isinstance(exc, BaseException):
            message = f"{type(exc).__name__}: {exc}"
            tb = tb or "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        else:
            message = str(exc)
        return self.event("error", stage, unit, lens="error", message=message, traceback=tb, fix=fix,
                          resume={"command": resume} if resume else None, machine=self.machine())

    def artifact(self, stage: str, path: Path | str, *, unit: str | None = None, role: str = "", hash_it: bool = True) -> dict:
        p = Path(path)
        return self.event("artifact", stage, unit, path=str(p), role=role, bytes=p.stat().st_size if p.exists() else None,
                          sha256=sha256_file(p) if (hash_it and p.exists()) else None)

    def timing(self, stage: str, unit_id: str, wall_s: float, *, size: dict | None = None, model: dict | None = None,
               settings: dict | None = None, outcome: str = "ok", started_at: str | None = None, unit_kind: str = "unit",
               **extra) -> dict:
        """A finished unit's timing: a journal ``timing`` event and one record
        in timings.jsonl (design/spec.md 5e)."""
        m = self.machine()
        ev = self.event("timing", stage, unit_id, wall_s=round(wall_s, 4), size=size or {}, model=model,
                        settings=settings, outcome=outcome, machine=m, **extra)
        g = m.get("gpu") or {}
        rec = {
            "v": SCHEMA_V, "run": self.run, "kind": self.kind, "stage": stage, "unit": unit_kind,
            "unit_id": unit_id, "size": size or {}, "wall_s": round(wall_s, 4),
            "started_at": started_at or ev["wall"],
            "machine": {"gpu": g.get("name"), "vram_total_mb": g.get("vram_total_mb"), "cpu": m.get("cpu"), "cpus": m.get("cpus")},
            "model": model, "settings": settings,
            "conditions": {"vram_used_mb": g.get("vram_used_mb"), "temp_c": g.get("temp_c"), "throttle": g.get("throttle"),
                           "cpu_load_avg": m.get("load_avg_1m"), "disk_free_gb": (m.get("disk") or {}).get("free_gb")},
            "outcome": outcome,
            # The flat fields studio/sketch.py writes, so one reader serves both.
            "film": self.film, "at": ev["wall"], "renderer": self.renderer, "journal": str(self.path),
        }
        with self._lock, self.timings.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        return ev

    @contextmanager
    def unit(self, stage: str, unit_id: str, *, size: dict | None = None, model: dict | None = None,
             settings: dict | None = None, start_event: bool = True, resume: str | None = None, unit_kind: str = "unit"):
        """One unit of work. Emits ``unit.start`` (unless the caller already
        did, e.g. from a worker), then ``unit.done`` plus its timing. On an
        exception it records an ``error`` event with the traceback and a
        ``failed`` timing, then re-raises."""
        u = Unit(stage, unit_id, size, model, settings)
        started = _iso()
        t0 = time.perf_counter()
        if start_event:
            self.event("unit", stage, unit_id, lens="unit.start", status="start", size=u.size, model=model, settings=settings)
        try:
            yield u
        except BaseException as exc:
            wall = u.wall_s if u.wall_s is not None else time.perf_counter() - t0
            if not getattr(exc, "_journaled", False):
                self.error(stage, unit_id, exc, resume=resume)
                try:
                    exc._journaled = True
                except Exception:
                    pass
            self.timing(stage, unit_id, wall, size=u.size, model=model, settings=settings, outcome="failed",
                        started_at=started, unit_kind=unit_kind)
            raise
        wall = u.wall_s if u.wall_s is not None else time.perf_counter() - t0
        value = (u.size or {}).get("value")
        self.event("unit", stage, unit_id, lens="unit.done", status="done", size=u.size, wall_s=round(wall, 4),
                   rate=round(wall / value, 6) if value else None, outcome=u.outcome, model=model, settings=settings,
                   machine=self.machine(), **u.extra)
        self.timing(stage, unit_id, wall, size=u.size, model=model, settings=settings, outcome=u.outcome, started_at=started,
                    unit_kind=unit_kind)


def read(path: Path | str) -> list[dict]:
    """All events of a journal file, in order."""
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]
