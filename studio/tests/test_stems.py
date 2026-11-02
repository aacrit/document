"""--stems (loom Phase 2a, reports/briefs/modular-engine/architecture.md section 8 Phase 2):
flag off, the render is unchanged; flag on, the four buses, the duck curve and every
narration/reading line are written under <out>/stems, and summing them with the
programme's post gain reproduces mix-norm.wav within the acceptance tolerance."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from studio.engine import journal as J
from studio.engine import render as R
from conftest import HEIGHT, WORKERS


@pytest.fixture(scope="module")
def stemmed(film_safe, tmp_path_factory) -> dict:
    out = tmp_path_factory.mktemp("stems-out")
    summary = R.render(film_safe, out, height=HEIGHT, workers=WORKERS, min_free_gb=1, encode_preset="veryfast",
                       write_stems=True)
    summary["out"] = out
    return summary


def test_stems_off_is_unchanged(rendered, stemmed):
    """The acceptance test's first half: with the flag off (the shared ``rendered`` fixture,
    the same film_safe, same settings) the master is byte-identical to a render with the flag
    on. ``--stems`` adds a folder; it changes no frame, no sample and no journal decision about
    the mix itself."""
    a = Path(rendered["master"]).read_bytes()
    b = Path(stemmed["master"]).read_bytes()
    assert a == b
    assert not (Path(rendered["out"]) / "stems").exists()
    assert (Path(stemmed["out"]) / "stems").exists()


def test_stems_folder_has_every_file(stemmed):
    stems = Path(stemmed["out"]) / "stems"
    for name in ("voice.wav", "clips.wav", "music_preduck.wav", "music_ducked.wav", "amb.wav", "duck.wav",
                 "stems.json"):
        assert (stems / name).is_file(), name
    assert (stems / "lines" / "index.json").is_file()


def test_stems_manifest_hashes_match_the_files(stemmed):
    stems = Path(stemmed["out"]) / "stems"
    manifest = json.loads((stems / "stems.json").read_text(encoding="utf-8"))
    assert manifest["sample_rate"] == R.AUDIO_RATE
    assert manifest["length_samples"] > 0
    assert isinstance(manifest["post_gain_db"], float)
    for rel, want in manifest["files"].items():
        assert J.sha256_file(stems / rel) == want, rel


def test_stems_lines_index_matches_files_and_narration_kind(stemmed):
    stems = Path(stemmed["out"]) / "stems"
    index = json.loads((stems / "lines" / "index.json").read_text(encoding="utf-8"))
    ids = {row["id"] for row in index}
    assert {"L1", "L2"} <= ids          # the fixture's two voice lines
    for row in index:
        assert row["kind"] in ("narration", "reading")
        assert (stems / row["file"]).is_file()
        x, sr = sf.read(str(stems / row["file"]), dtype="float32")
        assert sr == R.AUDIO_RATE
        assert len(x) > 0


def test_stems_buses_are_full_length_float32_from_sample_zero(stemmed):
    stems = Path(stemmed["out"]) / "stems"
    voice, sr = sf.read(str(stems / "voice.wav"), dtype="float32")
    duck, _ = sf.read(str(stems / "duck.wav"), dtype="float32")
    assert sr == R.AUDIO_RATE
    assert voice.dtype == np.float32
    assert len(voice) == len(duck)
    mix_norm, _ = sf.read(str(Path(stemmed["out"]) / "work" / "mix-norm.wav"), dtype="float32")
    assert abs(len(voice) - len(mix_norm)) <= 1    # frame-aligned to the master


def test_stems_reconstruct_mix_within_tolerance(stemmed):
    """Acceptance test: voice + clips + music_ducked + amb, summed and with the same
    post gain applied, reproduces mix-norm.wav within 0.1 dB RMS and a peak difference
    at or below -60 dBFS."""
    stems = Path(stemmed["out"]) / "stems"
    manifest = json.loads((stems / "stems.json").read_text(encoding="utf-8"))
    voice, _ = sf.read(str(stems / "voice.wav"), dtype="float32")
    clips, _ = sf.read(str(stems / "clips.wav"), dtype="float32")
    music_ducked, _ = sf.read(str(stems / "music_ducked.wav"), dtype="float32")
    amb, _ = sf.read(str(stems / "amb.wav"), dtype="float32")
    mix_norm, _ = sf.read(str(Path(stemmed["out"]) / "work" / "mix-norm.wav"), dtype="float32")
    n = min(len(voice), len(mix_norm))
    recon = ((voice[:n] + clips[:n] + music_ducked[:n] + amb[:n]) * manifest["post_gain_linear"]).astype(np.float32)
    mix_norm = mix_norm[:n]
    rms_recon = math.sqrt(float(np.mean(recon.astype(np.float64) ** 2)))
    rms_mix = math.sqrt(float(np.mean(mix_norm.astype(np.float64) ** 2)))
    assert rms_mix > 0
    rms_db_diff = 20 * math.log10(rms_recon / rms_mix)
    assert abs(rms_db_diff) <= 0.1, f"RMS diff {rms_db_diff:+.4f} dB"
    peak_diff = float(np.max(np.abs(recon - mix_norm)))
    peak_dbfs = 20 * math.log10(peak_diff) if peak_diff > 0 else float("-inf")
    assert peak_dbfs <= -60.0, f"peak diff {peak_dbfs:.1f} dBFS"


def test_stems_journaled(stemmed):
    evs = J.read(stemmed["journal"])
    arts = [e for e in evs if e["kind"] == "artifact" and (e.get("role") or "").startswith("stems/")]
    assert {e["role"] for e in arts} >= {"stems/voice.wav", "stems/stems.json", "stems/lines/index.json"}
    assert any(e["kind"] == "decision" and e.get("unit") == "stems" for e in evs)


def test_write_stem_files_sanitises_untrusted_line_ids(tmp_path):
    """Line ids come from the screenplay JSON (untrusted input, A26/A33): a colon
    (Windows-illegal), a path separator or a traversal attempt must never leave
    stems/lines, and never collide into one file silently."""
    bus = {
        "voice": np.zeros(480, np.float32), "clips": np.zeros(480, np.float32),
        "music_preduck": np.zeros(480, np.float32), "music_ducked": np.zeros(480, np.float32),
        "amb": np.zeros(480, np.float32), "duck": np.ones(480, np.float32),
        "lines": [
            {"id": "N:1", "start_s": 0.0, "kind": "narration", "gain_db": 0.0, "audio": np.zeros(10, np.float32)},
            {"id": "../../evil", "start_s": 1.0, "kind": "reading", "gain_db": 0.0, "audio": np.zeros(10, np.float32)},
            {"id": "..", "start_s": 2.0, "kind": "reading", "gain_db": 0.0, "audio": np.zeros(10, np.float32)},
            {"id": "a/b\\c", "start_s": 3.0, "kind": "reading", "gain_db": 0.0, "audio": np.zeros(10, np.float32)},
            {"id": "a:b", "start_s": 4.0, "kind": "reading", "gain_db": 0.0, "audio": np.zeros(10, np.float32)},
            {"id": "a!b", "start_s": 5.0, "kind": "reading", "gain_db": 0.0, "audio": np.zeros(10, np.float32)},
        ],
    }
    j = J.Journal(film="stems-sanitise-test", out_dir=tmp_path)
    loud = {"gain_db": 0.0}
    manifest_path = R.write_stem_files(tmp_path, bus, loud, j)
    lines_dir = tmp_path / "stems" / "lines"
    for p in lines_dir.glob("*.wav"):
        assert p.resolve().parent == lines_dir.resolve(), p   # never escaped stems/lines
    index = json.loads((lines_dir / "index.json").read_text(encoding="utf-8"))
    assert len(index) == 6
    files = [row["file"] for row in index]
    assert len(files) == len(set(files))                      # "a:b" and "a!b" both sanitise to "a_b"; the second
                                                                # gets its own file instead of overwriting the first
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for rel in files:
        assert J.sha256_file(tmp_path / "stems" / rel) == manifest["files"][rel]
