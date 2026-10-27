"""The web packet: sources.json readings carry their length and whose words
they are, --sources-only rewrites sources.json beside an existing master,
and studio/engine/publish.py ties the web encode and the poster to it."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import tone
from studio.engine import publish as P
from studio.engine import render as R
from studio.engine.journal import Journal, sha256_file


def _plan(film: Path, lines: list[dict]) -> dict:
    return {"film": str(film), "title": "T", "slug": "t", "W": 640, "H": 360, "frames": 240, "shots": [], "lines": lines,
            "speakers": {"sp-a": {"name": "A", "side": "india", "gender": "f"}, "sp-b": {"name": "B", "side": "britain", "gender": "m"}},
            "lower_thirds": [], "cues": [], "credits": []}


def test_reading_lengths_come_from_the_wav_and_are_null_without_one(tmp_path):
    tone(tmp_path / "audio" / "R1.wav", 1.5)
    tone(tmp_path / "recordings" / "nehru.wav", 2.25)
    lines = [
        {"id": "R1", "kind": "testimony", "speaker": "sp-a", "start_s": 1.0, "text": "a", "read_by": "v-01"},
        {"id": "R2", "kind": "testimony", "speaker": "sp-b", "start_s": 4.0, "text": "b", "read_by": "v-02"},
        {"id": "R3", "kind": "testimony", "speaker": "sp-b", "start_s": 6.0, "text": "c", "archival_audio": True,
         "wav": "recordings/nehru.wav"},
        {"id": "N1", "kind": "narration", "start_s": 0.0, "text": "n"},
    ]
    doc = R.sources_doc(_plan(tmp_path, lines), Journal(film="dur"), {})
    by = {r["id"]: r for r in doc["readings"]}
    assert set(by) == {"R1", "R2", "R3"}
    assert by["R1"]["dur_s"] == pytest.approx(1.5, abs=0.01) and by["R1"]["gender"] == "f"
    assert by["R2"]["dur_s"] is None and by["R2"]["gender"] == "m"          # no WAV: no length is claimed
    assert by["R3"]["dur_s"] == pytest.approx(2.25, abs=0.01)                # an archival recording: its own file's length
    assert by["R3"]["credit"] == "original recording"


def _copy_render(rendered: dict, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("master.mp4", "sources.json"):
        shutil.copy(Path(rendered["out"]) / name, dest / name)
    return dest


def test_a_full_render_records_the_master_hash(rendered):
    doc = json.loads((Path(rendered["out"]) / "sources.json").read_text(encoding="utf-8"))
    assert doc["master_sha256"] == sha256_file(Path(rendered["out"]) / "master.mp4")


def test_sources_only_rewrites_sources_json_without_rendering(film, rendered, tmp_path):
    out = _copy_render(rendered, tmp_path / "out")
    before = json.loads((out / "sources.json").read_text(encoding="utf-8"))
    r = R.sources_only(film, out)
    after = json.loads((out / "sources.json").read_text(encoding="utf-8"))
    assert after["master_sha256"] == sha256_file(out / "master.mp4") == r["master_sha256"]
    for key in ("shots", "marks", "share", "lower_thirds", "duration_s", "frames", "loudness"):
        assert after[key] == before[key], key
    assert [x["id"] for x in after["readings"]] == [x["id"] for x in before["readings"]]
    assert after["readings"][0]["dur_s"] == pytest.approx(1.2, abs=0.01)
    assert not (out / "segments").exists() and not (out / "work").exists()


def test_sources_only_refuses_without_a_master_or_with_a_stale_one(film, rendered, tmp_path):
    with pytest.raises(R.Refused, match="no master.mp4"):
        R.sources_only(film, tmp_path / "empty")
    out = _copy_render(rendered, tmp_path / "stale")
    short = tmp_path / "short.mp4"
    subprocess.run([R.ffmpeg(), "-v", "error", "-y", "-i", str(out / "master.mp4"), "-t", "2", "-c", "copy", str(short)], check=True)
    shutil.copy(short, out / "master.mp4")
    with pytest.raises(R.Refused, match="stale"):
        R.sources_only(film, out)


def test_sources_only_refuses_a_description_it_cannot_publish_before_writing_either_file(film, rendered, tmp_path,
                                                                                          monkeypatch):
    from studio.engine import description as DSC
    out = _copy_render(rendered, tmp_path / "unpublishable")
    before = (out / "sources.json").read_bytes()
    monkeypatch.setattr(DSC, "release_problem", lambda doc, film: "fixture is not in films.json")
    with pytest.raises(R.Refused, match="description: fixture is not in films.json"):
        R.sources_only(film, out)
    assert (out / "sources.json").read_bytes() == before and not (out / "description.txt").exists()


def test_the_pre_flight_reads_the_description_from_the_plans_own_sources_data(monkeypatch):
    crowded = {"slug": "fixture", "title": "F", "readings": [], "shots": [
        {"id": f"S{i}", "ledger_id": f"CB-{i}", "mark": {"class": "ARCHIVE"}, "title": "y" * 200, "licence": "CC BY 2.0",
         "creator": f"P{i}", "item_url": f"https://c.org/{i}"} for i in range(40)]}
    monkeypatch.setattr(R, "sources_doc", lambda plan, journal, extra: crowded)
    why = R.description_overflow({}, Journal(film="pre"))
    assert why and "CB-0" in why and "before 4.0" in why
    monkeypatch.setattr(R, "sources_doc", lambda plan, journal, extra: dict(crowded, shots=crowded["shots"][:2]))
    assert R.description_overflow({}, Journal(film="pre")) is None


def test_a_draft_that_cannot_write_its_description_retires_the_old_one(tmp_path):
    old = tmp_path / "description.txt"
    old.write_text("an earlier render's description\n", encoding="utf-8")
    stale = R.retire_description(old)
    assert stale == tmp_path / "description.stale.txt" and not old.exists()
    assert stale.read_text(encoding="utf-8") == "an earlier render's description\n"
    assert R.retire_description(old) is None                    # nothing to retire


def test_cli_sources_only(film, rendered, tmp_path):
    out = _copy_render(rendered, tmp_path / "cli")
    assert R.main([str(film), "--out", str(out), "--sources-only"]) == 0
    assert json.loads((out / "sources.json").read_text(encoding="utf-8"))["master_sha256"]


def _ledger(tmp_path: Path) -> Path:
    p = tmp_path / "stills-ledger.json"
    p.write_text(json.dumps({"items": [
        {"id": "S-020", "title": "Indian Independence Day at the Red Fort", "date": "1947", "creator": "Unknown authorUnknown author",
         "archive": "Wikimedia Commons", "item_url": "https://commons.wikimedia.org/wiki/File:Indian_Independence_Day_at_the_Red_Fort.jpg",
         "licence": "Public domain", "seen": "A crowd before the Red Fort.", "shows_violence_or_bodies": False},
        {"id": "S-099", "title": "x", "licence": "Public domain", "shows_violence_or_bodies": True},
        {"id": "S-100", "title": "y", "licence": "Public domain", "shows_bodies": True, "shows_violence_or_bodies": False},
        {"id": "S-101", "title": "z", "licence": "Public domain"},
        {"id": "S-102", "title": "w", "licence": "Public domain", "shows_bodies": False},
    ]}), encoding="utf-8")
    return p


def test_publish_ties_the_web_encode_and_the_poster_to_sources_json(film, rendered, tmp_path):
    out = _copy_render(rendered, tmp_path / "render")
    R.sources_only(film, out)
    poster = tmp_path / "poster.jpg"
    poster.write_bytes(b"\xff\xd8not really a jpeg")
    (out / "screenplay.fitted.json").write_text((Path(film) / "screenplay.json").read_text(encoding="utf-8"), encoding="utf-8")
    r = P.packet(out, film=out / "master.mp4", poster=poster, poster_id="S-020", stills_ledger=_ledger(tmp_path), out=tmp_path / "packet")
    doc = json.loads((tmp_path / "packet" / "sources.json").read_text(encoding="utf-8"))
    assert doc["web"]["film_sha256"] == sha256_file(out / "master.mp4")
    data = (out / "master.mp4").read_bytes()
    import hashlib
    assert doc["web"]["film_sha256_size"] == len(data)
    assert doc["web"]["film_sha256_head"] == hashlib.sha256(data[: P.EDGE_BYTES]).hexdigest()
    assert doc["web"]["film_sha256_tail"] == hashlib.sha256(data[-P.EDGE_BYTES:]).hexdigest()
    assert abs(doc["web"]["film_duration_s"] - doc["duration_s"]) <= 1 / 24
    assert doc["poster"] == r["poster"]
    assert doc["poster"]["ledger_id"] == "S-020" and doc["poster"]["sha256"] == sha256_file(poster)
    assert doc["poster"]["creator"] == "Unknown author" and doc["poster"]["licence"] == "Public domain"
    assert (tmp_path / "packet" / "captions-en.vtt").read_text(encoding="utf-8").startswith("WEBVTT")
    assert "trailer" not in doc and r["trailer"] is None          # no --trailer: no trailer declared, the site shows none
    # With a trailer, sources.json declares its bytes (the contract checks them only when declared).
    r2 = P.packet(out, film=out / "master.mp4", poster=poster, poster_id="S-020", stills_ledger=_ledger(tmp_path),
                  out=tmp_path / "packet2", trailer=out / "master.mp4")
    doc2 = json.loads((tmp_path / "packet2" / "sources.json").read_text(encoding="utf-8"))
    assert doc2["trailer"] == r2["trailer"]
    assert doc2["trailer"]["file"] == "trailer.mp4" and doc2["trailer"]["sha256"] == sha256_file(out / "master.mp4")
    assert doc2["trailer"]["sha256_size"] == len(data) and doc2["trailer"]["duration_s"] > 0


def test_publish_refuses_a_mismatched_encode_an_unhashed_render_and_a_violent_poster(film, rendered, tmp_path):
    out = _copy_render(rendered, tmp_path / "render")
    poster = tmp_path / "poster.jpg"
    poster.write_bytes(b"x")
    ledger = _ledger(tmp_path)
    doc = json.loads((out / "sources.json").read_text(encoding="utf-8"))
    doc.pop("master_sha256", None)                  # a render from before the engine recorded it
    (out / "sources.json").write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(R.Refused, match="master_sha256"):
        P.packet(out, film=out / "master.mp4", poster=poster, poster_id="S-020", stills_ledger=ledger, out=tmp_path / "p0")
    R.sources_only(film, out)
    short = tmp_path / "short.mp4"
    subprocess.run([R.ffmpeg(), "-v", "error", "-y", "-i", str(out / "master.mp4"), "-t", "2", "-c", "copy", str(short)], check=True)
    with pytest.raises(R.Refused, match="more than one frame apart"):
        P.packet(out, film=short, poster=poster, poster_id="S-020", stills_ledger=ledger, out=tmp_path / "p1")
    with pytest.raises(R.Refused, match="never a poster"):
        P.packet(out, film=out / "master.mp4", poster=poster, poster_id="S-099", stills_ledger=ledger, out=tmp_path / "p2")
    # shows_bodies is the ledger's field and wins over the older one; a still with neither field is refused.
    with pytest.raises(R.Refused, match="shows_bodies: True"):
        P.packet(out, film=out / "master.mp4", poster=poster, poster_id="S-100", stills_ledger=ledger, out=tmp_path / "p4")
    with pytest.raises(R.Refused, match="shows_bodies: None"):
        P.packet(out, film=out / "master.mp4", poster=poster, poster_id="S-101", stills_ledger=ledger, out=tmp_path / "p5")
    assert P.poster_record(ledger, "S-102", poster)["ledger_id"] == "S-102"
    with pytest.raises(R.Refused, match="not in"):
        P.packet(out, film=out / "master.mp4", poster=poster, poster_id="S-404", stills_ledger=ledger, out=tmp_path / "p3")
    # No master beside sources.json: refused.
    (out / "master.mp4").rename(out / "moved.mp4")
    with pytest.raises(R.Refused, match="no master.mp4"):
        P.packet(out, film=out / "moved.mp4", poster=poster, poster_id="S-020", stills_ledger=ledger, out=tmp_path / "p6")


def test_the_narration_and_the_narrators_credit_are_recorded_for_the_site(tmp_path):
    lines = [
        {"id": "N1", "kind": "narration", "start_s": 0.5, "text": "In the summer of 1947.", "read_by": "v-narrator"},
        {"id": "R1", "kind": "testimony", "speaker": "sp-a", "start_s": 4.0, "text": "a", "read_by": "v-01"},
        {"id": "N2", "kind": "narration", "start_s": 9.0, "text": ""},
    ]
    plan = {**_plan(tmp_path, lines), "narrator_voice": {"id": "v-narrator", "engine": "orpheus", "voice": "tara",
                                                         "credit": "Narrated by a computer voice"}}
    doc = R.sources_doc(plan, Journal(film="narr"), {})
    assert doc["narration"] == [{"id": "N1", "start_s": 0.5, "text": "In the summer of 1947."}]   # an empty line is not a word spoken
    assert doc["narrator"] == {"credit": "Narrated by a computer voice", "engine": "orpheus", "voice": "tara"}
    no_narr = R.sources_doc(_plan(tmp_path, lines[1:2]), Journal(film="none"), {})
    assert no_narr["narration"] == [] and no_narr["narrator"] is None                            # no narration: no narrator credited
