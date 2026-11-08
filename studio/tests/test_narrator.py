"""The narrator engine (founder ruling 2026-11-07, GRAMMAR A57): Kokoro-82M af_aoede at speed 0.88 is the house
narrator; takes are cached by a key holding the engine, voice and speed; a model file off the lock refuses; a Kokoro
narrator plays at her natural pitch; the printed wording names the model, the voice and the licence."""

import json
import math

import pytest

from studio.engine import description as DSC
from studio.engine import narrator as NR
from studio.engine import render as R

AOEDE = {"engine": "kokoro", "voice": "af_aoede", "speed": 0.88}
TARA = {"engine": "orpheus", "voice": "tara"}


# --------------------------------------------------------------------------
# The cache key
# --------------------------------------------------------------------------


def test_the_take_key_holds_the_engine_voice_and_speed():
    k = NR.take_key("New Delhi.", AOEDE)
    assert k == NR.take_key("New Delhi.", dict(AOEDE))                            # the same input, the same key
    assert k != NR.take_key("New Delhi.", dict(AOEDE, speed=1.0))                 # speed
    assert k != NR.take_key("New Delhi.", dict(AOEDE, voice="af_heart"))          # voice
    assert k != NR.take_key("New Delhi.", dict(AOEDE, engine="orpheus"))          # engine
    assert k != NR.take_key("New Delhi.", TARA)                                   # a Tara take is never an aoede one
    assert k != NR.take_key("New Delhi", AOEDE)                                   # text


def test_the_take_key_holds_the_pinned_model():
    lock = NR.load_lock()
    other = json.loads(json.dumps(lock))
    other["files"][0]["sha256"] = "0" * 64
    assert NR.take_key("x", AOEDE, lock) != NR.take_key("x", AOEDE, other)


def test_a_take_record_key_holds_the_narrator_identity():
    ln = {"id": "N1", "kind": "narration", "text": "In the summer of 1947."}
    tools = {"engine": "e", "ffmpeg": "f", "numpy": "n"}
    a = R._take_key("sha", ln, None, tools, AOEDE)
    assert a != R._take_key("sha", ln, None, tools, TARA)                     # a byte-identical take, another narrator
    assert a != R._take_key("sha", ln, None, tools, dict(AOEDE, speed=1.0))
    rd = {"id": "R1", "kind": "testimony", "text": "x"}
    assert R._take_key("sha", rd, None, tools, AOEDE) == R._take_key("sha", rd, None, tools, TARA)   # readings unchanged


def test_a_cached_take_is_reused_and_a_new_voice_is_synthesised(tmp_path):
    calls = []

    def runner(jobs, files, out, **kw):
        calls.append([j["voice"] for j in jobs])
        for j in jobs:
            (out / f"{j['id']}.wav").write_bytes(b"RIFF")
        return {"ok": [j["id"] for j in jobs], "failed": {}, "timing": {"audio_s": 1.0, "synth_s": 0.3}}

    lines = [{"id": "N1", "text": "One."}, {"id": "N2", "text": "Two."}]
    lock = NR.load_lock()
    folder = tmp_path / "models"
    folder.mkdir()
    for f in lock["files"]:                                     # a lock pinned to files made here, so verify passes
        (folder / f["name"]).write_bytes(f["name"].encode())
    lock = dict(lock, files=[dict(f, size=len(f["name"]), sha256=NR.sha256_path(folder / f["name"]))
                             for f in lock["files"]])
    res = NR.voice_lines(lines, cache=tmp_path / "c", runner=runner, folder=folder, lock=lock)
    assert res["synthesised"] == 2 and calls == [["af_aoede", "af_aoede"]]
    again = NR.voice_lines(lines, cache=tmp_path / "c", runner=runner, folder=folder, lock=lock)
    assert again["synthesised"] == 0 and all(v["cached"] for v in again["lines"].values()) and len(calls) == 1
    other = NR.voice_lines(lines, dict(AOEDE, speed=1.0), cache=tmp_path / "c", runner=runner, folder=folder, lock=lock)
    assert other["synthesised"] == 2                                              # another speed: new takes


# --------------------------------------------------------------------------
# The lock
# --------------------------------------------------------------------------


def test_the_lock_pins_kokoro_v1_and_quotes_its_licence():
    lock = NR.load_lock()
    assert lock["model"] == "hexgrad/Kokoro-82M" and lock["license"] == "Apache-2.0" and lock["voice"] == "af_aoede"
    assert "apache-2.0" in lock["license_quote"] and "af_aoede" in lock["license_quote"]
    assert "a tool" in lock["_note"] and "licence allowlist" in lock["_note"]
    assert {f["role"] for f in lock["files"]} == {"model", "voices"}
    assert all(len(f["sha256"]) == 64 for f in lock["files"])


def test_a_sha256_mismatch_refuses(tmp_path):
    lock = NR.load_lock()
    for f in lock["files"]:
        (tmp_path / f["name"]).write_bytes(b"x" * 8)
    sized = dict(lock, files=[dict(f, size=8) for f in lock["files"]])
    with pytest.raises(NR.LockMismatch, match="sha256 .* is not the pinned"):
        NR.verify_files(tmp_path, sized)
    assert all((tmp_path / f["name"]).exists() for f in lock["files"])       # left for a person to look at


def test_a_size_mismatch_or_a_missing_file_refuses(tmp_path):
    lock = NR.load_lock()
    with pytest.raises(NR.LockMismatch, match="missing"):
        NR.verify_files(tmp_path, lock)
    for f in lock["files"]:
        (tmp_path / f["name"]).write_bytes(b"x")
    with pytest.raises(NR.LockMismatch, match="bytes, the lock pins"):
        NR.verify_files(tmp_path, lock)


def test_a_model_off_the_lock_is_never_handed_to_the_worker(tmp_path):
    def runner(*a, **k):
        raise AssertionError("the worker ran on an unverified model")

    with pytest.raises(NR.LockMismatch):
        NR.voice_lines([{"id": "N1", "text": "One."}], cache=tmp_path / "c", runner=runner, folder=tmp_path)


def test_the_model_folder_defaults_to_d_and_can_be_overridden(monkeypatch, tmp_path):
    monkeypatch.delenv("DOCUMENT_KOKORO_DIR", raising=False)
    assert NR.model_dir().as_posix() == "D:/document-media/models/kokoro"
    monkeypatch.setenv("DOCUMENT_KOKORO_DIR", str(tmp_path))
    assert NR.model_dir() == tmp_path


# --------------------------------------------------------------------------
# The default narrator and natural pitch
# --------------------------------------------------------------------------


def test_the_house_narrator_is_aoede_at_0_88():
    assert {k: NR.HOUSE_NARRATOR[k] for k in ("engine", "voice", "speed")} == AOEDE
    play = {"cast": {"voices": [{"id": "v-narrator", "credit": "Narrated by a computer voice"}]},
            "parts": [{"lines": [{"id": "N1", "kind": "narration", "read_by": "v-narrator", "text": "x"}]}]}
    nv = R.narrator_voice(play)
    assert {k: nv[k] for k in ("engine", "voice", "speed")} == AOEDE


def test_an_orpheus_narrator_is_kept_behind_config():
    play = {"cast": {"voices": [dict(TARA, id="v-narrator", pitch_shift_st=0.76)]}, "parts": []}
    assert R.narrator_voice(play) == dict(TARA, id="v-narrator", pitch_shift_st=0.76)
    assert NR.narrator_problems(R.narrator_voice(play)) == []
    with pytest.raises(NR.NarratorError, match="made outside the engine"):
        NR.voice_lines([{"id": "N1", "text": "x"}], TARA, cache="unused")


def test_a_kokoro_narrator_plays_at_her_natural_pitch():
    assert NR.narrator_problems(AOEDE) == []
    (p,) = NR.narrator_problems(dict(AOEDE, pitch_shift_st=0.76))
    assert "natural pitch" in p and "Tara" in p
    assert NR.narrator_problems(dict(AOEDE, speed="slow"))
    assert NR.narrator_problems(dict(TARA, speed=0.9))                       # speed is a Kokoro setting


def test_the_lint_judges_only_kokoro_and_orpheus():
    assert NR.narrator_problems({"engine": "test-tone", "voice": "none", "pitch_shift_st": 3}) == []


# --------------------------------------------------------------------------
# The re-baselined profile
# --------------------------------------------------------------------------


def test_the_rebaselined_profile_loads_for_aoede():
    prof, why = R.load_narrator_profile(dict(AOEDE, id="v-narrator", credit="x"))
    assert prof is not None and prof["voice"] == AOEDE and "kokoro:af_aoede at speed 0.88" in why
    assert len(prof["takes"]) == 5 and 150 < prof["baseline"]["f0_hz"] < 210
    assert 900 < prof["baseline"]["centroid_hz"] < 1700
    f0s = sorted(t["f0_hz"] for t in prof["takes"].values())
    assert math.isclose(prof["baseline"]["f0_hz"], f0s[2], rel_tol=0.001)        # the median of the five takes
    assert all(len(t["sha256"]) == 16 for t in prof["takes"].values())


def test_aoede_at_another_speed_has_no_reference():
    none, why = R.load_narrator_profile(dict(AOEDE, speed=1.0))
    assert none is None and "none has that shift and speed" in why


def test_tara_is_still_found_behind_config():
    tara, why = R.load_narrator_profile(TARA)
    assert tara["voice"] == TARA and len(tara["takes"]) == 5


# --------------------------------------------------------------------------
# The printed wording
# --------------------------------------------------------------------------


def test_sources_json_and_the_description_name_the_model_voice_and_licence():
    nv = dict(NR.HOUSE_NARRATOR, **NR.printed(NR.HOUSE_NARRATOR))
    assert NR.printed(NR.HOUSE_NARRATOR) == {"model": "Kokoro-82M (hexgrad)", "licence": "Apache-2.0"}
    assert NR.printed(TARA) == {}
    n = DSC.notes({"narrator": {k: nv[k] for k in ("credit", "engine", "voice", "speed", "model", "licence")},
                   "readings": [], "shots": []})
    assert n["narrator"] == "Narration: a computer voice, Kokoro-82M (hexgrad), the voice af_aoede, Apache-2.0."
    old = DSC.notes({"narrator": {"credit": "x", "engine": "orpheus", "voice": "tara", "pitch_shift_st": 0.76},
                     "readings": [], "shots": []})
    assert old["narrator"] == "Narration: a computer voice, Orpheus 'tara', pitched +0.76 semitones."
