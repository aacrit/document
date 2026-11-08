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
RUNTIME = {"kokoro-onnx": "0.6.1", "onnxruntime": "1.31.1", "espeak-ng": "1.52.0"}


def probe(python=None):
    return dict(RUNTIME)
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
    kw = dict(runner=runner, folder=folder, lock=lock, prober=probe)
    res = NR.voice_lines(lines, cache=tmp_path / "c", **kw)
    assert res["synthesised"] == 2 and calls == [["af_aoede", "af_aoede"]]
    again = NR.voice_lines(lines, cache=tmp_path / "c", **kw)
    assert again["synthesised"] == 0 and all(v["cached"] for v in again["lines"].values()) and len(calls) == 1
    other = NR.voice_lines(lines, dict(AOEDE, speed=1.0), cache=tmp_path / "c", **kw)
    assert other["synthesised"] == 2                                              # another speed: new takes


# --------------------------------------------------------------------------
# The lock
# --------------------------------------------------------------------------


def test_the_lock_pins_kokoro_v1_and_quotes_its_licence():
    lock = NR.load_lock()
    assert lock["model"] == "hexgrad/Kokoro-82M" and lock["license"] == "Apache-2.0" and lock["voice"] == "af_aoede"
    assert "apache-2.0" in lock["license_quote"] and "af_aoede" in lock["license_quote"]
    assert "tools, not source inputs" in lock["_note"] and "licence allowlist" in lock["_note"]
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
        NR.voice_lines([{"id": "N1", "text": "One."}], cache=tmp_path / "c", runner=runner, folder=tmp_path,
                       prober=probe)


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


# --------------------------------------------------------------------------
# Review round 1 (PR #97): the manifest, a voice with no engine, the voice bank, aoede's own EQ, fetch, runtime
# --------------------------------------------------------------------------

import hashlib                                      # noqa: E402
from pathlib import Path                            # noqa: E402

from conftest import make_film                      # noqa: E402
from studio.engine import journal as J              # noqa: E402
from studio.engine import score as SC               # noqa: E402


def _edit(film, fn):
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    fn(play)
    (film / "screenplay.json").write_text(json.dumps(play), encoding="utf-8")


def _house(p):
    v = next(v for v in p["cast"]["voices"] if v["id"] == "v-narrator")
    v.pop("engine")
    v.pop("voice")


def _no_engine(p):
    next(v for v in p["cast"]["voices"] if v["id"] == "v-narrator").pop("engine")


def _aoede_film(tmp_path):
    """The fixture film with its narrator made the house narrator (engine and voice left out)."""
    film = make_film(tmp_path / "film")
    _edit(film, _house)
    return film


def _manifest(film, voice=AOEDE, text_of=None, sha_of=None):
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    lines = {ln["id"]: ln for p in play["parts"] for ln in p.get("lines", []) if ln.get("kind") == "narration"}
    doc = {"v": 1, "identity": NR.identity(voice), "model": "m", "runtime": RUNTIME, "lines": {}}
    for lid, ln in lines.items():
        wav = film / (ln.get("wav") or f"audio/{lid}.wav")
        doc["lines"][lid] = {"text_sha256": NR.sha256_text((text_of or {}).get(lid, ln["text"])), "key": "k",
                             "wav": wav.as_posix(), "sha256": (sha_of or {}).get(lid) or NR.sha256_path(wav)}
    (film / NR.MANIFEST).write_text(json.dumps(doc), encoding="utf-8")


def _plan(film, **kw):
    return R.build_plan(film, W=640, H=360, burn_subtitles=False, journal=J.Journal(film="aoede"), **kw)


def test_a_stale_take_is_refused_for_a_kokoro_narrator(tmp_path):
    film = _aoede_film(tmp_path)
    with pytest.raises(R.Refused, match=r"narrator-takes-voiced \(narrator\).*no voicing manifest"):
        _plan(film)                                                   # a WAV made elsewhere (a Tara take left in place)
    _manifest(film, sha_of={"L1": "0" * 64})
    with pytest.raises(R.Refused, match=r"L1: L1.wav is not the take voiced as kokoro:af_aoede"):
        _plan(film)
    _manifest(film, voice=dict(AOEDE, speed=1.0))
    with pytest.raises(R.Refused, match=r"narrator-takes-voiced.*re-voice it"):
        _plan(film)
    _manifest(film, text_of={"L1": "Another sentence."})
    with pytest.raises(R.Refused, match=r"L1: its text changed since it was voiced"):
        _plan(film)
    _manifest(film)
    with pytest.raises(R.Refused, match=r"narrator-drift"):            # the take passes; the tone is then judged as her
        _plan(film)
    plan = _plan(film, draft=True)                                    # the recorded take, as voiced: planned
    assert plan["narrator_voice"]["voice"] == "af_aoede" and plan["narrator_eq"]["low"]["hz"] == 195.0


def test_an_orpheus_film_needs_no_manifest():
    assert NR.manifest_problems(Path("nowhere"), [{"id": "N1", "kind": "narration"}], TARA) == ([], {"exempt": "orpheus"})
    assert NR.manifest_problems(Path("nowhere"), [{"id": "N1", "kind": "narration"}], {"engine": "test-tone"})[0] == []


def test_a_voice_with_no_engine_is_not_turned_into_kokoro(tmp_path):
    play = {"cast": {"voices": [{"id": "v-narrator", "voice": "tara", "credit": "x"}]}, "parts": []}
    assert R.narrator_voice(play) == {"id": "v-narrator", "voice": "tara", "credit": "x"}     # not kokoro:tara
    (p,) = NR.narrator_problems(R.narrator_voice(play))
    assert "names no engine" in p
    film = make_film(tmp_path / "film")
    _edit(film, _no_engine)
    with pytest.raises(R.Refused, match=r"narrator-voice-declared \(narrator\).*names no engine"):
        _plan(film)


def test_a_kokoro_voice_outside_the_pinned_bank_is_refused():
    (p,) = NR.narrator_problems(dict(AOEDE, voice="af_nobody"))
    assert "not a voice in the pinned voice bank" in p
    assert "af_aoede" in NR.kokoro_voices() and len(NR.kokoro_voices()) == 54


def test_aoede_takes_her_own_measured_eq_and_a_tara_eq_is_refused():
    eq, how, problems = R.narrator_eq_resolve({}, AOEDE)
    assert not problems and eq == {"low": {"type": "bell", "hz": 195.0, "gain_db": 3.0, "q": 1.2},
                                   "high": {"type": "high_shelf", "hz": 6000.0, "gain_db": 0.0, "slope": 1.0}}
    assert "kokoro:af_aoede" in how and not SC.narrator_eq_setting({"narrator_eq": eq})[2]   # inside A38's bounds
    tara_eq = {"low": {"type": "bell", "hz": 170, "gain_db": 3, "q": 0.9},
               "high": {"type": "high_shelf", "hz": 5000, "gain_db": -3, "slope": 0.8}}
    none, _, problems = R.narrator_eq_resolve({"narrator_eq": tara_eq}, AOEDE)
    assert none is None and "tuned to Tara" in problems[0]
    assert R.narrator_eq_resolve({"narrator_eq": "off"}, AOEDE)[:2] == (None, "off")
    assert R.narrator_eq_resolve({"narrator_eq": tara_eq}, TARA)[0] == tara_eq           # Orpheus keeps the film's
    assert R.narrator_eq_resolve({}, dict(AOEDE, speed=1.0))[2]                           # no stored EQ: refused


def test_a_film_with_a_tara_eq_and_a_kokoro_narrator_is_refused_at_plan_time(tmp_path):
    film = _aoede_film(tmp_path)
    _manifest(film)
    _edit(film, lambda p: p.update(narrator_eq={"low": {"type": "bell", "hz": 170, "gain_db": 3, "q": 0.9},
                                                "high": {"type": "high_shelf", "hz": 5000, "gain_db": -3,
                                                         "slope": 0.8}}))
    with pytest.raises(R.Refused, match=r"narrator-eq-declared \(narrator_eq\).*tuned to Tara"):
        _plan(film)


def test_the_stored_eq_is_derived_from_the_stored_takes_by_the_house_method():
    prof = json.loads(R.NARRATOR_PROFILE.read_text(encoding="utf-8"))
    ev = prof["eq_evidence"]
    assert ev["takes"] == 5 and "voicing.derive" in prof["eq_method"]
    assert prof["eq"]["low"]["hz"] == round(ev["f0_hz"] * 200.0 / 179.4 / 5) * 5      # the bell sits above her f0


def test_fetch_checks_a_download_before_it_takes_the_name(tmp_path):
    lock = NR.load_lock()
    entry = dict(lock["files"][0], size=4)

    def bad(url, dest):
        dest.write_bytes(b"evil")

    with pytest.raises(NR.LockMismatch):
        NR.fetch(tmp_path, dict(lock, files=[entry]), download=bad)
    name = entry["name"]
    assert not (tmp_path / name).exists() and (tmp_path / f"{name}.rejected").read_bytes() == b"evil"

    def ok(url, dest):
        dest.write_bytes(b"good")

    good = dict(entry, sha256=hashlib.sha256(b"good").hexdigest())
    assert NR.fetch(tmp_path / "ok", dict(lock, files=[good]), download=ok)["model"].read_bytes() == b"good"


def test_the_runtime_versions_are_in_the_key_and_a_changed_runtime_refuses(tmp_path):
    assert NR.take_key("x", AOEDE, runtime=RUNTIME) != NR.take_key("x", AOEDE, runtime=dict(RUNTIME, onnxruntime="1.32"))
    lock = NR.load_lock()
    folder = tmp_path / "models"
    folder.mkdir()
    for f in lock["files"]:
        (folder / f["name"]).write_bytes(f["name"].encode())
    lock = dict(lock, files=[dict(f, size=len(f["name"]), sha256=NR.sha256_path(folder / f["name"]))
                             for f in lock["files"]])

    def runner(jobs, files, out, **kw):
        for j in jobs:
            (out / f"{j['id']}.wav").write_bytes(b"RIFF")
        return {"ok": [j["id"] for j in jobs], "failed": {}, "runtime": dict(RUNTIME, numpy="9")}

    with pytest.raises(NR.NarratorError, match="the worker ran on"):
        NR.voice_lines([{"id": "N1", "text": "x"}], cache=tmp_path / "c", runner=runner, folder=folder, lock=lock,
                       prober=probe)


def test_the_lock_records_the_conversion():
    c = NR.load_lock()["conversion"]
    assert c["repo"] == "thewh1teagle/kokoro-onnx" and c["release"].startswith("model-files-v1.0")
    assert c["model"]["what"] == "int8 ONNX export of hexgrad/Kokoro-82M v1.0"
    assert "MIT License" in c["repo_licence_quote"] and "6e742170" in c["model"]["checked"]
    assert "af_aoede.pt" in c["voices"]["af_aoede"] and "c03bd1a4" in c["voices"]["af_aoede"]


def test_the_requirements_are_pinned_with_hashes():
    req = (Path(NR.__file__).resolve().parents[1] / "requirements-tts.txt").read_text(encoding="utf-8")
    pins = [ln for ln in req.splitlines() if "==" in ln]
    assert any(ln.startswith("kokoro-onnx==0.6.1") for ln in pins) and "--require-hashes" in req
    reqs = [ln for ln in pins if not ln.startswith("#")]
    body = [ln for ln in req.splitlines() if not ln.startswith("#")]
    blocks = " ".join(body).split("==")[1:]
    assert len(reqs) == len(blocks) == 13 and all("--hash=sha256:" in b for b in blocks)


# --------------------------------------------------------------------------
# Readers follow narrator (founder ruling 2026-11-08, A38 amended)
# --------------------------------------------------------------------------

from studio.engine import voicing as VO             # noqa: E402


def test_switching_the_narrator_identity_switches_the_readers_reference(tmp_path, monkeypatch):
    tara, how, problems = VO.reference(TARA)
    assert tara == VO.targets() and "pinned Tara" in how and not problems          # Orpheus keeps the Tara pin
    aoede, how, problems = VO.reference(AOEDE)
    ev = json.loads(R.NARRATOR_PROFILE.read_text(encoding="utf-8"))["eq_evidence"]
    assert not problems and "kokoro:af_aoede" in how
    assert aoede == {"warmth_db": ev["warmth_after_db"], "treble_db": {c: ev["treble_after_db"][str(c)]
                                                                        for c in VO.TREBLE_BANDS}}
    assert aoede != tara
    # a later narrator (the founder's own voice) with a stored after-EQ spectrum is followed with no re-pin
    prof = json.loads(R.NARRATOR_PROFILE.read_text(encoding="utf-8"))
    founder = {"engine": "kokoro", "voice": "af_heart", "speed": 0.88}
    prof["variants"].append({"voice": founder, "baseline": prof["baseline"],
                             "eq_evidence": {"warmth_after_db": 5.0, "treble_after_db": {"5000": 1.0, "6300": 2.0,
                                                                                         "8000": 3.0}}})
    f = tmp_path / "narrator-profile.json"
    f.write_text(json.dumps(prof), encoding="utf-8")
    monkeypatch.setattr(R, "NARRATOR_PROFILE", f)
    nxt, how, _ = VO.reference(founder)
    assert nxt == {"warmth_db": 5.0, "treble_db": {5000: 1.0, 6300: 2.0, 8000: 3.0}} and "af_heart" in how
    none, _, problems = VO.reference(dict(AOEDE, speed=1.0))                      # a Kokoro narrator with none
    assert problems and "no stored after-EQ spectrum" in problems[0]


def test_a_kokoro_films_readers_derive_against_aoede():
    table, _ = VO.load_table()
    play = {"cast": {"voices": [dict(AOEDE, id="v-narrator"), {"id": "v-r", "engine": "kokoro", "voice": "am_eric"}]},
            "parts": [{"lines": [{"id": "N1", "kind": "narration", "read_by": "v-narrator", "text": "x"},
                                 {"id": "R1", "kind": "testimony", "read_by": "v-r", "text": "y"}]}]}
    target, name, _ = VO.reference(R.narrator_voice(play))
    per, _, problems = VO.setting(play, table, target, name)
    rec = table["kokoro:am_eric"]
    want, _ = VO.derive({int(c): v for c, v in rec["excess_db"].items()}, rec["f0_hz"], target)
    assert not problems and per["kokoro:am_eric"]["eq"] == want != rec["eq"]
    assert "re-derived against the narrator kokoro:af_aoede" in per["kokoro:am_eric"]["how"]
    for k, r in table.items():                                                   # every reader inside A38's bounds
        eq, _ = VO.derive({int(c): v for c, v in r["excess_db"].items()}, r["f0_hz"], target)
        assert not VO.eq_problems(k, eq)
    tara_play = json.loads(json.dumps(play))
    tara_play["cast"]["voices"][0] = dict(TARA, id="v-narrator")
    t, n, _ = VO.reference(R.narrator_voice(tara_play))
    assert VO.setting(tara_play, table, t, n)[0]["kokoro:am_eric"] == {"eq": rec["eq"], "how": "house table"}
