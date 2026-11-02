"""--stems (loom Phase 2a, reports/briefs/modular-engine/architecture.md section 8 Phase 2):
flag off, the render is unchanged; flag on, the four buses, the duck curve and every
voice line are written under <out>/stems. The buses sum, sample for sample, to work/mix.wav;
the lines placed at their start samples sum to voice.wav (from the pass that made the mix,
after any voice-ceiling pass); and mix-norm.wav follows from them by one gain only when the
master limiter did not run (stems.json says which)."""

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
from test_render import _e14_plan, _wav

BUSES = ("voice", "clips", "music_preduck", "music_ducked", "amb", "duck")
# 0.1 dB of level error, as a residual: |10^(0.1/20) - 1| of the signal, about -38.7 dB under it
RESIDUAL_DB = 20 * math.log10(10 ** (0.1 / 20) - 1)


def _read(p: Path) -> np.ndarray:
    x, sr = sf.read(str(p), dtype="float32")
    assert sr == R.AUDIO_RATE
    return x


def _stems(run_dir: Path) -> tuple[dict, dict, list]:
    stems = run_dir / "stems"
    manifest = json.loads((stems / "stems.json").read_text(encoding="utf-8"))
    index = json.loads((stems / "lines" / "index.json").read_text(encoding="utf-8"))
    return manifest, {k: _read(stems / f"{k}.wav") for k in BUSES}, index


def _lines_sum(run_dir: Path, index: list, n: int) -> np.ndarray:
    total = np.zeros(n, np.float32)
    for row in index:
        x = _read(run_dir / "stems" / row["file"])
        i = row["start_sample"]
        total[i:i + len(x)] += x[: n - i]
    return total


def _dbfs(x: np.ndarray) -> float:
    m = float(np.max(np.abs(x))) if len(x) else 0.0
    return 20 * math.log10(m) if m > 0 else float("-inf")


def _assert_lines_are_voice(run_dir: Path, index: list, voice: np.ndarray) -> None:
    """The lines placed back sum to voice.wav (float tolerance), and a line no
    other line overlaps is its own slice of voice.wav, sample for sample."""
    total = _lines_sum(run_dir, index, len(voice))
    assert float(np.max(np.abs(total - voice))) <= 1e-6, f"lines vs voice {_dbfs(total - voice):.1f} dBFS"
    spans = [(r["start_sample"], r["start_sample"] + len(_read(run_dir / "stems" / r["file"]))) for r in index]
    for row, (a, b) in zip(index, spans):
        assert row["start_sample"] == int(round(row["start_s"] * R.AUDIO_RATE))
        if any(c < b and a < d for (c, d) in spans if (c, d) != (a, b)):
            continue
        x = _read(run_dir / "stems" / row["file"])
        assert np.array_equal(x, voice[a:b]), row["id"]


def _assert_buses_are_the_mix(run_dir: Path, manifest: dict, bus: dict) -> None:
    mix = _read(run_dir / "work" / "mix.wav")
    assert manifest["mix"]["sha256"] == J.sha256_file(run_dir / "work" / "mix.wav")
    recon = (bus["voice"] + bus["clips"] + bus["music_ducked"] + bus["amb"]).astype(np.float32)
    assert np.array_equal(recon, mix)                                     # the mix, sample for sample
    assert np.array_equal((bus["music_preduck"] * bus["duck"]).astype(np.float32), bus["music_ducked"])


def _assert_mix_norm(run_dir: Path, manifest: dict, bus: dict) -> np.ndarray:
    """mix-norm.wav from the stems with stems.json's post gain, judged sample by
    sample: the residual sits 0.1 dB's worth under the signal. Returns the residual."""
    mix_norm = _read(run_dir / "work" / "mix-norm.wav")
    n = min(len(bus["voice"]), len(mix_norm))
    recon = ((bus["voice"] + bus["clips"] + bus["music_ducked"] + bus["amb"])[:n]
             * manifest["post_gain_linear"]).astype(np.float64)
    ref = mix_norm[:n].astype(np.float64)
    resid = recon - ref
    rms_ref = math.sqrt(float(np.mean(ref ** 2)))
    assert rms_ref > 0
    rel = 20 * math.log10(max(math.sqrt(float(np.mean(resid ** 2))), 1e-30) / rms_ref)
    assert rel <= RESIDUAL_DB, f"residual {rel:.1f} dB under the signal (want <= {RESIDUAL_DB:.1f})"
    return resid


# --------------------------------------------------------------------------
# The fixture film, rendered with and without --stems
# --------------------------------------------------------------------------


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
    assert "limiter" in manifest and "mix_norm_from_stems" in manifest
    for rel, want in manifest["files"].items():
        assert J.sha256_file(stems / rel) == want, rel


def test_stems_lines_index_matches_files_and_kinds(stemmed):
    stems = Path(stemmed["out"]) / "stems"
    index = json.loads((stems / "lines" / "index.json").read_text(encoding="utf-8"))
    ids = {row["id"] for row in index}
    assert {"L1", "L2"} <= ids          # the fixture's two voice lines
    for row in index:
        assert row["kind"] in ("narration", "reading", "archival")
        assert isinstance(row["start_sample"], int)
        x = _read(stems / row["file"])
        assert len(x) > 0


def test_stems_buses_are_full_length_float32_from_sample_zero(stemmed):
    stems = Path(stemmed["out"]) / "stems"
    voice = _read(stems / "voice.wav")
    duck = _read(stems / "duck.wav")
    assert voice.dtype == np.float32
    assert len(voice) == len(duck)
    mix_norm = _read(Path(stemmed["out"]) / "work" / "mix-norm.wav")
    assert abs(len(voice) - len(mix_norm)) <= 1    # frame-aligned to the master


def test_stems_reconstruct_the_mix(stemmed):
    """Acceptance test (architecture.md section 8, Phase 2): the stems summed with the duck
    reproduce work/mix.wav, sample for sample; the lines sum to the voice bus; and, when the
    master limiter did not run (stems.json ``limiter`` null), the post gain takes them to
    mix-norm.wav, judged sample by sample."""
    run_dir = Path(stemmed["out"])
    manifest, bus, index = _stems(run_dir)
    _assert_buses_are_the_mix(run_dir, manifest, bus)
    _assert_lines_are_voice(run_dir, index, bus["voice"])
    if manifest["limiter"] is None:
        assert manifest["mix_norm_from_stems"].startswith("valid")
        resid = _assert_mix_norm(run_dir, manifest, bus)
        assert _dbfs(resid) <= -60.0, f"peak diff {_dbfs(resid):.1f} dBFS"
    else:
        assert manifest["mix_norm_from_stems"].startswith("not valid")


def test_stems_journaled(stemmed):
    evs = J.read(stemmed["journal"])
    arts = [e for e in evs if e["kind"] == "artifact" and (e.get("role") or "").startswith("stems/")]
    assert {e["role"] for e in arts} >= {"stems/voice.wav", "stems/stems.json", "stems/lines/index.json"}
    assert any(e["kind"] == "decision" and e.get("unit") == "stems" for e in evs)


# --------------------------------------------------------------------------
# E14's plans: a second voice-ceiling pass, and the master limiter catching peaks
# --------------------------------------------------------------------------


def _stem_e14(root: Path, **kw) -> dict:
    """build_mix on an E14 plan with the bus captured, then the render's own order:
    work/mix.wav, the loudness pass to work/mix-norm.wav, write_stem_files."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(R, "clean_voice", lambda x: (x, None))     # E14's shaped tones must peak where the plan puts them
        plan, film = _e14_plan(root, **kw)
        j = J.Journal(film="stems-e14", out_dir=root)
        bus: dict = {}
        mix, placed = R.build_mix(plan, film, j, work=root / "work", bus_capture=bus)
    run_dir = root / "run"
    (run_dir / "work").mkdir(parents=True)
    _wav(run_dir / "work" / "mix.wav", mix)
    loud = R.loudnorm(run_dir / "work" / "mix.wav", run_dir / "work" / "mix-norm.wav")
    dec = [e for e in J.read(j.path) if e["kind"] == "decision" and e.get("unit") == "voice-ceiling"][0]
    R.write_stem_files(run_dir, bus, loud, j, min_free_gb=0)
    return {"run_dir": run_dir, "loud": loud, "passes": dec["evidence"]["passes"], "dec": dec, "mix": mix}


@pytest.fixture(scope="module")
def pass2(tmp_path_factory) -> dict:
    return _stem_e14(tmp_path_factory.mktemp("stems-pass2"), amb_amp=0.08, pulse_tp=-4.9)


@pytest.fixture(scope="module")
def peak_only(tmp_path_factory) -> dict:
    return _stem_e14(tmp_path_factory.mktemp("stems-peak-only"), amb_amp=0.08, lines=4, pulse_tp=-5.6)


def test_stems_after_a_second_voice_ceiling_pass_come_from_the_final_pass(pass2):
    """Review block 1: when voice_ceiling_pass re-places every line at a lower ceiling,
    the line files are that last pass's audio, not pass 1's: placed back, they sum to
    voice.wav, and their peak is the voice bus's peak (pass 1's lines peak about 2 dB higher)."""
    assert pass2["passes"] >= 2 and pass2["dec"]["evidence"]["lines_changed"] == 4
    run_dir = pass2["run_dir"]
    manifest, bus, index = _stems(run_dir)
    assert {r["id"] for r in index} == {"L0", "L1", "L2", "L3"}
    _assert_buses_are_the_mix(run_dir, manifest, bus)
    _assert_lines_are_voice(run_dir, index, bus["voice"])
    total = _lines_sum(run_dir, index, len(bus["voice"]))
    assert _dbfs(total) == pytest.approx(_dbfs(bus["voice"]), abs=1e-3)
    final = pass2["dec"]["evidence"]["final_ceiling_dbtp"]
    assert _dbfs(bus["voice"]) <= final                                  # sample peak under the final ceiling


def test_stems_when_the_master_limiter_runs_say_mix_norm_is_not_their_sum(peak_only):
    """Review block 2: the limiter-peak-only plan (one pass, the master limiter catches
    peaks). stems.json carries the limiter (its ceiling, the gain before it, the gain
    after it, its file), the total gain is the two gains' sum, and it says reconstructing
    mix-norm.wav from the stems is not valid; work/mix.wav still is, sample for sample."""
    assert peak_only["passes"] == 1
    loud = peak_only["loud"]
    assert loud["limiter"]
    run_dir = peak_only["run_dir"]
    manifest, bus, index = _stems(run_dir)
    lim = manifest["limiter"]
    assert lim["applied"] is True and lim["file"] == loud["limiter"]["file"]
    assert lim["ceiling_dbtp"] == loud["limiter"]["ceiling_dbtp"]
    assert lim["pre_gain_db"] == pytest.approx(loud["limiter"]["pre_gain_db"], abs=1e-4)
    want_post = R.TARGET_LUFS - loud["limiter"]["attempts"][-1]["measured"]["input_i"]
    assert lim["post_gain_db"] == pytest.approx(want_post, abs=1e-4)
    assert manifest["post_gain_db"] == pytest.approx(lim["pre_gain_db"] + lim["post_gain_db"], abs=1e-3)
    assert manifest["post_gain_linear"] == pytest.approx(10 ** (manifest["post_gain_db"] / 20), rel=1e-6)
    assert manifest["mix_norm_from_stems"].startswith("not valid")
    _assert_buses_are_the_mix(run_dir, manifest, bus)
    _assert_lines_are_voice(run_dir, index, bus["voice"])
    # The total gain is the programme's own: away from the places the limiter acted (each padded by its release),
    # the stems at post_gain_linear are mix-norm sample by sample; the gain before the limiter alone (the reviewed
    # bug) is not. Where it acted they differ, which is why mix_norm_from_stems says "not valid".
    acted = loud["limiter"]["acted"]
    assert acted and loud["limiter"]["acted_total"] == len(acted) <= R.LIMIT_ACTED_LOGGED   # every place is logged
    mix = _read(run_dir / "work" / "mix.wav").astype(np.float64)
    mix_norm = _read(run_dir / "work" / "mix-norm.wav").astype(np.float64)
    n = min(len(mix), len(mix_norm))
    keep = np.ones(n, bool)
    pad = R.LIMITER_RELEASE_MS / 1000
    for a in acted:
        keep[max(0, int((a["at_s"] - pad) * R.AUDIO_RATE)): int((a["at_s"] + a["dur_s"] + pad) * R.AUDIO_RATE)] = False
    assert keep.mean() > 0.5
    ref = mix_norm[:n][keep]
    rms_ref = math.sqrt(float(np.mean(ref ** 2)))

    def residual_db(gain_db: float) -> float:
        r = mix[:n][keep] * 10 ** (gain_db / 20) - ref
        return 20 * math.log10(math.sqrt(float(np.mean(r ** 2))) / rms_ref)

    total, pre_only = residual_db(manifest["post_gain_db"]), residual_db(lim["pre_gain_db"])
    assert total <= -70.0, f"residual {total:.1f} dB under the signal away from the limiter"   # measured: about -82
    assert total < pre_only - 20.0, (total, pre_only)                     # the gain before the limiter is not the gain
    whole = _read(run_dir / "work" / "mix-norm.wav")
    resid_all = (bus["voice"] + bus["clips"] + bus["music_ducked"] + bus["amb"])[:n] * manifest["post_gain_linear"] - whole[:n]
    assert _dbfs(resid_all) > -60.0                                       # where it acted, the stems are not mix-norm


def test_stems_without_the_limiter_reconstruct_mix_norm(tmp_path):
    """No limiter (the lift's gain leaves the true peak under the ceiling): mix-norm.wav
    is the stems' sum times post_gain_linear, sample by sample."""
    r = _stem_e14(tmp_path, amb_amp=0.0, lines=12, film_s=40.0, pulse_tp=-6.0)
    assert not r["loud"]["limiter"]
    manifest, bus, index = _stems(r["run_dir"])
    assert manifest["limiter"] is None and manifest["mix_norm_from_stems"].startswith("valid")
    assert manifest["post_gain_db"] == pytest.approx(R.TARGET_LUFS - r["loud"]["input_i"], abs=1e-4)
    _assert_buses_are_the_mix(r["run_dir"], manifest, bus)
    resid = _assert_mix_norm(r["run_dir"], manifest, bus)
    assert _dbfs(resid) <= -60.0, f"peak diff {_dbfs(resid):.1f} dBFS"


def test_stems_carry_archival_lines(plan, film, tmp_path, monkeypatch):
    """An archival file line (and, the same way, an archival span) is a line too, ``kind:
    archival``, at the static gain the final pass held it to, so the lines sum to voice.wav."""
    arch = json.loads(json.dumps(plan))
    k = next(n for n, ln in enumerate(arch["lines"]) if ln.get("kind") == "testimony")
    arch["lines"][k].update(archival_audio=True, gain_db=20.0)
    lid = arch["lines"][k]["id"]
    monkeypatch.setattr(R, "_master_overreach", lambda mix, tp, work: (["forced by the test"], None))
    monkeypatch.setattr(R, "derived_voice_ceiling", lambda lift: (-6.5, -6.5, None))
    bus: dict = {}
    mix, placed = R.build_mix(arch, film, J.Journal(film="stems-arch", out_dir=tmp_path), bus_capture=bus)
    row = next(ln for ln in bus["lines"] if ln["id"] == lid)
    assert row["kind"] == "archival"
    assert row["gain_db"] == pytest.approx(next(ln for ln in placed["lines"] if ln["id"] == lid)["static_gain_db"], abs=0.01)
    total = np.zeros(len(mix), np.float32)
    for ln in bus["lines"]:
        i = ln["start_sample"]
        total[i:i + len(ln["audio"])] += ln["audio"]
    assert float(np.max(np.abs(total - bus["voice"]))) <= 1e-6
    assert np.array_equal((bus["voice"] + bus["clips"] + bus["music_ducked"] + bus["amb"]).astype(np.float32), mix)


# --------------------------------------------------------------------------
# write_stem_files on its own: names, stale stems, the disk floor
# --------------------------------------------------------------------------


def _bus(lines: list[dict]) -> dict:
    b = {k: np.zeros(480, np.float32) for k in BUSES}
    b["lines"] = [dict({"start_sample": int(round(ln["start_s"] * R.AUDIO_RATE)), "kind": "reading", "gain_db": 0.0,
                        "audio": np.zeros(10, np.float32)}, **ln) for ln in lines]
    return b


def test_write_stem_files_sanitises_untrusted_line_ids(tmp_path):
    """Line ids come from the screenplay JSON (untrusted input, A26/A33): a colon
    (Windows-illegal), a path separator or a traversal attempt must never leave
    stems/lines, and never collide into one file silently."""
    bus = _bus([{"id": i, "start_s": float(s)} for s, i in
                enumerate(["N:1", "../../evil", "..", "a/b\\c", "a:b", "a!b"])])
    j = J.Journal(film="stems-sanitise-test", out_dir=tmp_path)
    manifest_path = R.write_stem_files(tmp_path, bus, {"gain_db": 0.0}, j, min_free_gb=0)
    lines_dir = tmp_path / "stems" / "lines"
    for p in lines_dir.glob("*.wav"):
        assert p.resolve().parent == lines_dir.resolve(), p   # never escaped stems/lines
    index = json.loads((lines_dir / "index.json").read_text(encoding="utf-8"))
    assert len(index) == 6
    files = [row["file"] for row in index]
    assert len(files) == len(set(files))                      # "a:b" and "a!b" both sanitise to "a_b"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for rel in files:
        assert J.sha256_file(tmp_path / "stems" / rel) == manifest["files"][rel]


def test_write_stem_files_names_are_unique_without_case_and_never_a_device(tmp_path):
    """NTFS is case-insensitive (N1 and n1 are one file), CON, NUL, COM1 and the rest
    open devices whatever their extension, and a name has a length cap."""
    ids = ["N1", "n1", "NUL", "con.x", "COM1", "lpt9", "x" * 300, "X" * 300]
    bus = _bus([{"id": i, "start_s": float(s), "audio": np.full(5 + s, s + 1, np.float32)} for s, i in enumerate(ids)])
    R.write_stem_files(tmp_path, bus, {"gain_db": 0.0}, J.Journal(film="stems-case", out_dir=tmp_path), min_free_gb=0)
    index = json.loads((tmp_path / "stems" / "lines" / "index.json").read_text(encoding="utf-8"))
    names = [Path(r["file"]).stem for r in index]
    assert len({n.casefold() for n in names}) == len(ids)
    for n in names:
        assert n.split(".")[0].upper() not in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                                               *(f"LPT{i}" for i in range(1, 10))}, n
        assert len(n) <= R.STEM_NAME_MAX
    on_disk = sorted(p.name for p in (tmp_path / "stems" / "lines").glob("*.wav"))
    assert len(on_disk) == len(ids)                            # nothing overwrote anything
    for s, row in enumerate(index):                             # each file holds its own line
        assert np.array_equal(_read(tmp_path / "stems" / row["file"]), np.full(5 + s, s + 1, np.float32)), row["id"]


def _earlier_stems(run_dir: Path) -> Path:
    """A stems folder as an earlier --stems render leaves it: stems.json and a line."""
    R.write_stem_files(run_dir, _bus([{"id": "OLD", "start_s": 0.0}]), {"gain_db": 0.0},
                       J.Journal(film="stems-earlier", out_dir=run_dir), min_free_gb=0)
    stale = run_dir / "stems" / "lines" / "OLD.wav"
    assert stale.is_file() and (run_dir / "stems" / "stems.json").is_file()
    return stale


def test_write_stem_files_clears_stale_stems(tmp_path):
    stale = _earlier_stems(tmp_path)
    R.write_stem_files(tmp_path, _bus([{"id": "L1", "start_s": 0.0}]), {"gain_db": 0.0},
                       J.Journal(film="stems-stale", out_dir=tmp_path), min_free_gb=0)
    assert not stale.exists()
    assert sorted(p.name for p in (tmp_path / "stems" / "lines").iterdir()) == ["L1.wav", "index.json"]


def test_write_stem_files_refuses_a_stems_folder_without_a_manifest(tmp_path):
    """<out>/stems without stems.json is not an earlier render's stems: refused, and nothing in it is deleted."""
    mine = tmp_path / "stems" / "notes.txt"
    mine.parent.mkdir(parents=True)
    mine.write_text("not stems", encoding="utf-8")
    with pytest.raises(R.Refused, match=r"holds no stems\.json.*left untouched"):
        R.write_stem_files(tmp_path, _bus([{"id": "L1", "start_s": 0.0}]), {"gain_db": 0.0},
                           J.Journal(film="stems-foreign", out_dir=tmp_path), min_free_gb=0)
    assert mine.read_text(encoding="utf-8") == "not stems"
    assert sorted(p.name for p in (tmp_path / "stems").iterdir()) == ["notes.txt"]


def test_write_stem_files_refused_for_disk_keeps_the_earlier_stems(tmp_path):
    """The free-space check runs before anything is removed: a refused run leaves the earlier stems as they were."""
    stale = _earlier_stems(tmp_path)
    before = {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in (tmp_path / "stems").rglob("*") if p.is_file()}

    class Full:
        free = 0

    with pytest.raises(R.Refused, match=r"GB floor"):
        R.write_stem_files(tmp_path, _bus([{"id": "L1", "start_s": 0.0}]), {"gain_db": 0.0},
                           J.Journal(film="stems-full", out_dir=tmp_path), min_free_gb=10, disk_usage=lambda p: Full)
    assert stale.is_file()
    after = {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in (tmp_path / "stems").rglob("*") if p.is_file()}
    assert after == before


def test_write_stem_files_refuses_past_the_free_disk_floor(tmp_path):
    """The stems' size is estimated before any file is written; past the out drive's
    floor the render is refused with the size named, and no stems folder is left."""
    bus = _bus([{"id": "L1", "start_s": 0.0}])
    need = R.stem_bytes(bus)
    assert need >= 6 * 480 * 4 + 10 * 4

    class Usage:
        free = 10 * 1024 ** 3 + need - 1                       # one byte short of keeping 10 GB free

    with pytest.raises(R.Refused, match=r"--stems: the stems need 0\.00 GB.*10 GB floor"):
        R.write_stem_files(tmp_path, bus, {"gain_db": 0.0}, J.Journal(film="stems-disk", out_dir=tmp_path),
                           min_free_gb=10, disk_usage=lambda p: Usage)
    assert not (tmp_path / "stems").exists()

    class Roomy:
        free = 10 * 1024 ** 3 + need
    R.write_stem_files(tmp_path, bus, {"gain_db": 0.0}, J.Journal(film="stems-disk-ok", out_dir=tmp_path),
                       min_free_gb=10, disk_usage=lambda p: Roomy)
    assert (tmp_path / "stems" / "stems.json").is_file()


def test_write_stem_files_escapes_nothing_into_html_and_keeps_ids_verbatim(tmp_path):
    """An id is data: it is kept verbatim in index.json (JSON-escaped) and only its file name is sanitised."""
    evil = '"><img src=x onerror=alert(1)>'
    R.write_stem_files(tmp_path, _bus([{"id": evil, "start_s": 0.0}]), {"gain_db": 0.0},
                       J.Journal(film="stems-evil", out_dir=tmp_path), min_free_gb=0)
    index = json.loads((tmp_path / "stems" / "lines" / "index.json").read_text(encoding="utf-8"))
    assert index[0]["id"] == evil
    assert all(c.isalnum() or c in "_.-" for c in Path(index[0]["file"]).stem)
