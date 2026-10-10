import json

import pytest

from studio.engine import journal as J


def test_events_carry_the_required_fields(tmp_path):
    j = J.Journal(film="t", directory=tmp_path / "j", timings=tmp_path / "timings.jsonl")
    for kind in J.KINDS:
        j.event(kind, "scout", "u1", note=kind)
    events = J.read(j.path)
    assert [e["kind"] for e in events] == list(J.KINDS)
    for e in events:
        for field in ("v", "run", "seq", "kind", "stage", "unit", "mono_s", "wall"):
            assert field in e, field
        assert e["run"] == j.run
    assert [e["seq"] for e in events] == list(range(1, len(J.KINDS) + 1))
    assert all(a["mono_s"] <= b["mono_s"] for a, b in zip(events, events[1:]))
    with pytest.raises(ValueError):
        j.event("gossip", "scout")


def test_env_var_sets_the_journal_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCUMENT_JOURNAL_DIR", str(tmp_path / "elsewhere"))
    monkeypatch.setenv("DOCUMENT_TIMINGS", str(tmp_path / "t.jsonl"))
    j = J.Journal(film="t")
    assert j.path.parent == tmp_path / "elsewhere"
    assert j.path.name == f"{j.run}.jsonl"
    assert j.timings == tmp_path / "t.jsonl"


def test_unit_writes_start_done_timing_and_the_timing_ledger(tmp_path):
    j = J.Journal(film="t", directory=tmp_path, timings=tmp_path / "timings.jsonl", out_dir=tmp_path)
    with j.unit("motion", "S1", size={"driver": "frames", "value": 48}, model={"name": "m", "version": "1"},
                settings={"preset": "PUSH"}, unit_kind="shot") as u:
        u.extra["note"] = "hello"
    ev = J.read(j.path)
    assert [(e["kind"], e.get("lens")) for e in ev] == [("unit", "unit.start"), ("unit", "unit.done"), ("timing", None)]
    done = ev[1]
    assert done["size"] == {"driver": "frames", "value": 48}
    assert done["model"] == {"name": "m", "version": "1"} and done["settings"] == {"preset": "PUSH"}
    assert done["outcome"] == "ok" and done["note"] == "hello"
    assert "cpus" in done["machine"] and "gpu" in done["machine"] and done["machine"]["disk"]["free_gb"] > 0
    rec = json.loads((tmp_path / "timings.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    for field in ("v", "run", "kind", "stage", "unit", "unit_id", "size", "wall_s", "started_at", "machine", "model",
                  "conditions", "outcome", "film", "at", "renderer"):
        assert field in rec, field
    assert rec["unit"] == "shot" and rec["unit_id"] == "S1" and rec["run"] == j.run


def test_unit_records_the_error_with_its_traceback_then_reraises(tmp_path):
    j = J.Journal(film="t", directory=tmp_path, timings=tmp_path / "timings.jsonl")

    def boom():
        raise RuntimeError("segment encoder died")

    with pytest.raises(RuntimeError, match="segment encoder died"):
        with j.unit("motion", "S4", size={"driver": "frames", "value": 10}, resume="python -m studio.engine.render x --from S4"):
            boom()
    ev = J.read(j.path)
    err = [e for e in ev if e["kind"] == "error"]
    assert len(err) == 1
    assert err[0]["unit"] == "S4" and err[0]["lens"] == "error"
    assert "RuntimeError: segment encoder died" in err[0]["message"]
    assert "boom" in err[0]["traceback"] and "raise RuntimeError" in err[0]["traceback"]
    assert err[0]["resume"] == {"command": "python -m studio.engine.render x --from S4"}
    timing = [e for e in ev if e["kind"] == "timing"]
    assert timing[-1]["outcome"] == "failed"
    rec = json.loads((tmp_path / "timings.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert rec["outcome"] == "failed"
    assert not [e for e in ev if e.get("lens") == "unit.done"]


def test_an_error_is_journaled_once_through_nested_units(tmp_path):
    j = J.Journal(film="t", directory=tmp_path, timings=tmp_path / "timings.jsonl")
    with pytest.raises(KeyError):
        with j.unit("scout", "outer"):
            with j.unit("scout", "inner"):
                raise KeyError("x")
    assert sum(1 for e in J.read(j.path) if e["kind"] == "error") == 1


def test_lint_artifact_decision_and_retry_helpers(tmp_path):
    j = J.Journal(film="t", directory=tmp_path, timings=tmp_path / "timings.jsonl")
    f = tmp_path / "a.bin"
    f.write_bytes(b"abc")
    j.lint("mark-coverage", True, evidence={"frames": 3})
    j.lint("telecine-declared", False, severity="warn")
    j.lint("fill-ok", True, severity="review")
    j.artifact("assembly", f, role="master")
    j.decision("conform", "treated as 30 fps", "ledger silent")
    j.retry("motion", "S2", 1, "EncodeError: x", fix="re-render")
    ev = J.read(j.path)
    assert [e["status"] for e in ev[:3]] == ["pass", "fail", "review"]
    assert ev[3]["sha256"] == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad" and ev[3]["bytes"] == 3
    assert ev[4]["who"] == "engine" and ev[5]["attempt"] == 1
