"""Founder rulings for "Real World" (11 September 2001): CC BY-SA allowed for that film only, scoped by the
screenplay's ``share_alike`` declaration (its DECISIONS entry); the narrator Zoe lowered 2 semitones (2026-10-16);
and Tara lowered 1 semitone (2026-10-18, after a narrator audition), each held to a stored profile entry of her own."""

import json
import math

import numpy as np
import pytest
import soundfile as sf

from conftest import make_film
from studio.engine import journal as J
from studio.engine import render as R

ZOE = {"engine": "orpheus", "voice": "zoe", "pitch_shift_st": -2}
TARA_1ST = {"engine": "orpheus", "voice": "tara", "pitch_shift_st": -1}
DECISION = "docs/DECISIONS.md 2026-10-17: CC BY-SA for Real World only"


def _by_sa_film(tmp_path, share_alike):
    film = make_film(tmp_path / "film")
    led = json.loads((film / "stills-ledger.json").read_text(encoding="utf-8"))
    led["items"][0]["licence"] = "CC BY-SA 2.0"
    (film / "stills-ledger.json").write_text(json.dumps(led), encoding="utf-8")
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    if share_alike is not None:
        play["share_alike"] = share_alike
    return film, play


# --------------------------------------------------------------------------
# CC BY-SA, per film
# --------------------------------------------------------------------------


@pytest.mark.parametrize("lic", ["CC BY-SA 2.0", "cc-by-sa-4.0", "CC BY-SA 3.0", "CC BY-SA"])
def test_share_alike_is_allowed_only_where_the_film_declares_it(lic):
    assert R.licence_allowed(lic) == (False, True)
    assert R.licence_allowed(lic, {"share_alike": {"decision": DECISION}}) == (True, True)
    assert R.licence_allowed(lic, {"share_alike": {"decision": "the founder said so"}}) == (False, True)
    assert R.licence_allowed(lic, {"share_alike": True}) == (False, True)


def test_the_house_allowlist_is_unchanged():
    for lic in ("public domain", "CC0", "CC BY 2.0", "CC BY 4.0"):
        assert R.licence_allowed(lic) == (True, False)
    for lic in ("CC BY-NC 2.0", "CC BY-ND 4.0", "CC BY-NC-SA 2.0", "all rights reserved", ""):
        assert R.licence_allowed(lic, {"share_alike": {"decision": DECISION}})[0] is False


def test_a_by_sa_still_is_refused_without_the_declaration(tmp_path):
    film, play = _by_sa_film(tmp_path, None)
    with pytest.raises(R.Refused, match="licence-allowlist"):
        R.build_plan(film, W=640, H=360, burn_subtitles=False, journal=J.Journal(film="sa-none"), play=play)


def test_a_bad_declaration_is_refused_and_does_not_allow_the_still(tmp_path):
    film, play = _by_sa_film(tmp_path, {"decision": "yes"})
    with pytest.raises(R.Refused, match="share-alike-declared"):
        R.build_plan(film, W=640, H=360, burn_subtitles=False, journal=J.Journal(film="sa-bad"), play=play)


def test_a_declared_film_plans_its_by_sa_still_and_journals_the_decision(tmp_path):
    film, play = _by_sa_film(tmp_path, {"decision": DECISION})
    j = J.Journal(film="sa-ok")
    R.build_plan(film, W=640, H=360, burn_subtitles=False, journal=j, play=play)
    evs = J.read(j.path)
    lic = [e for e in evs if e["kind"] == "lint" and e.get("rule") == "licence-allowlist"]
    assert lic and all(e["status"] == "pass" for e in lic)
    assert any(e["evidence"].get("share_alike") == DECISION for e in lic)
    assert [e for e in evs if e["kind"] == "decision" and "CC BY-SA allowed for this film only" in json.dumps(e)]


# --------------------------------------------------------------------------
# Zoe, lowered 2 semitones
# --------------------------------------------------------------------------


def test_the_committed_profile_holds_zoe_lowered_two_semitones():
    prof = json.loads(R.NARRATOR_PROFILE.read_text(encoding="utf-8"))
    assert prof["voice"] == {"engine": "orpheus", "voice": "tara"}          # the stock entry is still Tara
    (zoe,) = [v for v in prof["variants"] if v["voice"].get("voice") == "zoe"]
    assert zoe["voice"] == ZOE and len(zoe["takes"]) >= 5
    assert 140 < zoe["baseline"]["f0_hz"] < 200 and zoe["baseline"]["centroid_hz"] > 0
    f0s = sorted(t["f0_hz"] for t in zoe["takes"].values())
    assert math.isclose(zoe["baseline"]["f0_hz"], f0s[len(f0s) // 2], rel_tol=0.02)   # the median of the takes


def test_zoe_is_chosen_by_voice_and_shift():
    zoe, why = R.load_narrator_profile(ZOE)
    assert zoe["voice"] == ZOE and "orpheus:zoe shifted -2 st" in why
    none, why = R.load_narrator_profile({"engine": "orpheus", "voice": "zoe"})        # unshifted zoe is not stored
    assert none is None and "none has that shift" in why
    other, why = R.load_narrator_profile({"engine": "orpheus", "voice": "leah", "pitch_shift_st": -2})
    assert other is None and "the film's narrator is orpheus:leah" in why
    tara, _ = R.load_narrator_profile({"engine": "orpheus", "voice": "tara", "pitch_shift_st": -2})
    assert tara["voice"]["voice"] == "tara"                                            # Tara's films are unchanged


# --------------------------------------------------------------------------
# Tara, lowered 1 semitone (supersedes Zoe for this film)
# --------------------------------------------------------------------------


def test_the_committed_profile_holds_tara_lowered_one_semitone():
    prof = json.loads(R.NARRATOR_PROFILE.read_text(encoding="utf-8"))
    assert prof["voice"] == {"engine": "orpheus", "voice": "tara"}          # the stock entry is still unshifted Tara
    (t1,) = [v for v in prof["variants"] if v["voice"] == TARA_1ST]
    assert t1["voice"] == TARA_1ST and len(t1["takes"]) == 4
    assert 140 < t1["baseline"]["f0_hz"] < 200 and t1["baseline"]["centroid_hz"] > 0
    f0s = sorted(t["f0_hz"] for t in t1["takes"].values())
    assert math.isclose(t1["baseline"]["f0_hz"], f0s[len(f0s) // 2], rel_tol=0.02)   # the median of the takes
    # every take carries its provenance: a (truncated) sha256 of the exact source file
    for name, take in t1["takes"].items():
        assert len(take["sha256"]) == 16
    assert "rw-narrator-audition/takes/tara-1st__P1.wav" in t1["_note"]   # pre-chain: shift only, no warm EQ baked in
    assert "2026-10-18" in t1["_note"]


def test_tara_1st_is_chosen_by_voice_and_shift():
    t1, why = R.load_narrator_profile(TARA_1ST)
    assert t1["voice"] == TARA_1ST and "orpheus:tara shifted -1 st" in why
    none, why = R.load_narrator_profile({"engine": "orpheus", "voice": "tara"})   # unshifted tara keeps its own entry
    assert none is not None and none["voice"] == {"engine": "orpheus", "voice": "tara"}
    tara_2st, _ = R.load_narrator_profile({"engine": "orpheus", "voice": "tara", "pitch_shift_st": -2})
    assert tara_2st["voice"]["pitch_shift_st"] == -2                              # the -2 st entry is unaffected
    zoe, _ = R.load_narrator_profile(ZOE)
    assert zoe["voice"]["voice"] == "zoe"                                         # Zoe's own entry is unaffected
    missing, why = R.load_narrator_profile({"engine": "orpheus", "voice": "tara", "pitch_shift_st": -1.5})
    assert missing is None and "none has that shift" in why


def test_narrator_profile_from_takes_is_hermetic_and_keyed_by_voice(tmp_path):
    """A tiny synthetic take (a steady 170 Hz tone, well inside the voiced-pitch band) run through the engine's own
    ``narrator_profile_from_takes``, exactly as the committed Tara -1 st entry was made, with no network, no model
    and no checked-in media."""
    rate = R.AUDIO_RATE
    t = np.arange(int(2.0 * rate)) / rate
    tone = (0.2 * np.sin(2 * np.pi * 170.0 * t)).astype(np.float32)
    wav = tmp_path / "synthetic-take.wav"
    sf.write(str(wav), tone, rate)

    voice = {"engine": "orpheus", "voice": "tara", "pitch_shift_st": -1}
    prof = R.narrator_profile_from_takes([(wav, "a short synthetic line for the test")], voice)

    assert prof["voice"] == voice
    (take,) = prof["takes"].values()
    assert take["words"] == 7
    assert 165 < take["f0_hz"] < 175                                 # the tone's own pitch, within measurement noise
    assert take["sha256"] == R.sha256_file(wav)[:16]                 # provenance matches the exact source bytes
    assert math.isclose(prof["baseline"]["f0_hz"], take["f0_hz"])    # a single take: baseline is that take
