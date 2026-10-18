"""Ticket preflight-voice: the take-only sound lints run at plan time.

WG-3 found that a full plan of Real World passed with 0 blocking, then the
render refused in the mix on A14 (N:5-8 f0 1.52 semitones under the
baseline, limit 1.5 for an unmarked line), after HEAVY.lock was taken. Every
sound lint whose inputs are the takes and the screenplay now runs in
build_plan (render.take_lints) at the mix's severity, cached by take sha, and
the render's mix does not journal it again. The parity tests hold
render.SOUND_LINTS to the code."""

import ast
import inspect
import json
from pathlib import Path

import numpy as np
import pytest

from studio.engine import journal as J
from studio.engine import render as R
from studio.engine import sheets as SH
from conftest import make_film

RATE = 48000


def lints(evs, rule=None):
    return [e for e in evs if e["kind"] == "lint" and (rule is None or e.get("rule") == rule)]


# --------------------------------------------------------------------------
# Parity: every lint the sound path journals is classified, and every
# take-only one is judged at plan time
# --------------------------------------------------------------------------

# What render() runs on the sound, from the mix to the loudness pass (the roots of the sound path).
SOUND_ROOTS = ("build_mix", "sound_lints", "score_lints", "fill_cards", "card_fill_lints", "still_hold_lints",
               "loudness_lints")
# Rules the sound path names through a variable, not a literal first argument (sound_lints' floors) or from
# score.score_checks (score_lints journals c["rule"]): the table lists them by name or as one group.
DYNAMIC = {"voiceless-floor": "sound_lints", "readings-floor": "sound_lints", "women-floor": "sound_lints",
           "score-standard checks": "score_lints"}


def _module_functions():
    tree = ast.parse(Path(R.__file__).read_text(encoding="utf-8"))
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}


def _called(fn: ast.FunctionDef, names: set[str]) -> set[str]:
    out = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in names:
            out.add(n.func.id)
    return out


def _closure(roots, funcs) -> set[str]:
    seen, todo = set(), list(roots)
    while todo:
        f = todo.pop()
        if f in seen or f not in funcs:
            continue
        seen.add(f)
        todo += sorted(_called(funcs[f], set(funcs)) - seen)
    return seen


def _rules(fn: ast.FunctionDef) -> set[str]:
    """The literal rule names a function journals: journal.lint("x", ...) or lint("x", ...), pacing_review(j, "x"),
    and card_lints' rule_fits / rule_drawn."""
    out = set()
    for n in ast.walk(fn):
        if not isinstance(n, ast.Call):
            continue
        name = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", None)
        if name == "lint" and n.args and isinstance(n.args[0], ast.Constant):
            out.add(n.args[0].value)
        elif name == "pacing_review" and len(n.args) > 1 and isinstance(n.args[1], ast.Constant):
            out.add(n.args[1].value)
        for k in n.keywords:
            if k.arg in ("rule_fits", "rule_drawn") and isinstance(k.value, ast.Constant):
                out.add(k.value.value)
    return out


def _sound_path_rules() -> dict[str, set[str]]:
    funcs = _module_functions()
    reach = _closure(SOUND_ROOTS, funcs)
    by_rule: dict[str, set[str]] = {}
    for f in reach:
        for r in _rules(funcs[f]):
            by_rule.setdefault(r, set()).add(f)
    return by_rule


def test_every_lint_on_the_sound_path_is_classified():
    found = _sound_path_rules()
    table = R.SOUND_LINTS
    assert set(found) - set(table) == set(), "a sound-path lint missing from render.SOUND_LINTS"
    assert set(table) - set(found) == set(DYNAMIC), "render.SOUND_LINTS lists a lint the sound path does not journal"
    for rule, where in DYNAMIC.items():
        src = inspect.getsource(getattr(R, where))
        assert ("SC.score_checks(" in src) if rule == "score-standard checks" else (f'"{rule}"' in src), rule
    for rule, row in table.items():
        assert row["class"] in ("take-only", "needs full mix") and row["why"], rule
        assert ("plan" in row) == (row["class"] == "take-only"), rule


def test_the_mix_journals_the_takes_through_the_same_helpers_the_plan_does():
    funcs = _module_functions()
    mix = _closure(("build_mix",), funcs)
    plan = _closure(("take_lints",), funcs)
    shared = {"process_take", "journal_take", "narrator_consistency_lints", "narrator_eq_lints", "reader_eq_lints",
              "take_refusal"}
    assert shared <= mix and shared <= plan
    assert "take_lints" in _closure(("build_plan",), funcs)


def test_every_take_only_lint_is_judged_at_plan_time():
    funcs = _module_functions()
    at_plan: set[str] = set()
    for f in _closure(("take_lints", "build_plan", "preflight_sources"), funcs):
        at_plan |= _rules(funcs[f])
    take_only = {r: row for r, row in R.SOUND_LINTS.items() if row["class"] == "take-only"}
    assert {"narrator-consistency", "narrator-drift", "voice-clean", "voice-chop", "voice-peak-control",
            "narrator-eq", "reader-eq"} <= set(take_only)
    for rule, row in take_only.items():
        assert set(row["plan"]) <= at_plan, (rule, set(row["plan"]) - at_plan)


# The sound-stage lints of WG-3's Real World --audio-only journal (r-20261018-013310-224ee218, on 5105fd8): each
# take-only, so each is judged at plan time.
REAL_WORLD_SOUND_STAGE = ("narrator-consistency", "narrator-drift", "narrator-eq", "reader-eq", "voice-beside",
                          "voice-chop", "voice-clean", "voice-peak-control")


def test_the_real_world_sound_stage_lints_are_all_take_only():
    assert all(R.SOUND_LINTS[r]["class"] == "take-only" for r in REAL_WORLD_SOUND_STAGE)


# --------------------------------------------------------------------------
# A fixture film with narration takes: a narrator at about 180 Hz and one
# unmarked line 1.52 semitones under her
# --------------------------------------------------------------------------


def _speech(f0, seconds=1.6, amp=0.1, seed=0):
    """A voiced take (as test_render's): harmonics to 4 kHz with a slow wobble, cut into syllables, padded with
    silence at the ends."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(RATE * seconds)) / RATE
    inst = f0 * (1 + 0.03 * np.sin(2 * np.pi * 1.3 * t + rng.uniform(0, 6)))
    ph = 2 * np.pi * np.cumsum(inst) / RATE
    x = sum((1.0 / k) * np.sin(k * ph) for k in range(1, int(4000 // f0) + 1))
    gate = (np.sin(2 * np.pi * 2.0 * t) > -0.7).astype(float)
    x = amp * x * gate / np.max(np.abs(x))
    x[(t < 0.2) | (t >= seconds - 0.2)] = 0.0
    return x.astype(np.float32)


def _wav(path, x):
    import soundfile as sf
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.asarray(x, dtype="float32"), RATE, subtype="FLOAT")
    return path


BASE = {"L1": 180.0, "NA": 181.0, "NB": 179.0, "NC": 180.5}
TEXT = "one two three four five"


def _f0(x, words=5):
    _, _, rec = R.process_take(x, {"kind": "narration", "text": TEXT}, None, None)
    return rec["profile"]["f0_hz"]


def _low_take(st=-1.52):
    """A take whose measured f0 sits ``st`` semitones from the baseline the BASE takes measure (one correction
    of the generator's pitch, so the measured offset is the one asked for)."""
    base = float(np.median([_f0(_speech(f, seed=k)) for k, f in enumerate(BASE.values())]))
    want = base * 2 ** (st / 12)
    f = want
    for _ in range(3):
        got = _f0(_speech(f, seed=9))
        f *= want / got
    return _speech(f, seed=9)


@pytest.fixture(scope="module")
def low_take():
    return _low_take()


def _narration_film(tmp_path, low, *, low_mood=None):
    """The fixture film with five narration lines in chapter 1: L1 and three more measured lines at about
    180 Hz (the baseline), and NLOW, unmarked, from ``low``."""
    film = make_film(tmp_path / "film")
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    ch = next(p for p in play["parts"] if p["id"] == "ch-1")
    l1 = next(ln for ln in ch["lines"] if ln["id"] == "L1")
    l1.update(text=TEXT, delivery={"mood": "measured"})
    starts = {"NA": 7.5, "NB": 10.0, "NC": 12.5, "NLOW": 15.0}
    for lid, at in starts.items():
        ch["lines"].append({"id": lid, "kind": "narration", "start_s": at, "text": TEXT, "sources": [],
                            **({"delivery": {"mood": "measured"}} if lid != "NLOW" else
                               {"delivery": {"mood": low_mood}} if low_mood else {})})
    (film / "screenplay.json").write_text(json.dumps(play), encoding="utf-8")
    for k, (lid, f0) in enumerate(BASE.items()):
        _wav(film / "audio" / f"{lid}.wav", _speech(f0, seed=k))
    _wav(film / "audio" / "NLOW.wav", low)
    return film


def _plan(film, journal, **kw):
    return R.build_plan(film, W=640, H=360, burn_subtitles=False, journal=journal, **kw)


@pytest.fixture
def takes_cache(tmp_path, monkeypatch):
    d = tmp_path / "takes-cache"
    monkeypatch.setenv("DOCUMENT_TAKES_CACHE", str(d))
    return d


def test_a_take_1_52_semitones_under_the_narrator_is_refused_at_plan_time(tmp_path, takes_cache, low_take):
    film = _narration_film(tmp_path, low_take)
    j = J.Journal(film="preflight-voice")
    with pytest.raises(R.Refused, match=r"^narrator-consistency and narrator-drift \(A14\): not the narrator's voice: "
                                        r"NLOW \(f0 -1\.5\d semitones \(more than 1\.5 below for a unmarked line\)\)$"):
        _plan(film, j)
    evs = J.read(j.path)
    per = {e["unit"]: e for e in lints(evs, "narrator-consistency") if e["unit"] in {*BASE, "NLOW"}}
    low = per.pop("NLOW")
    assert low["status"] == "fail" and low["severity"] == "block" and low["phase"] == "preflight"
    assert low["evidence"]["f0_st"] == pytest.approx(-1.52, abs=0.015) and low["evidence"]["mood"] is None
    assert low["evidence"]["result"] == "refused: re-render the line"
    assert {e["status"] for e in per.values()} == {"pass"} and len(per) == 4
    # the plan refused before the stills' pre-flight and any frame: nothing but the plan ran
    assert not [e for e in evs if e["kind"] == "stage" and e["stage"] == "assembly"]
    # every take's own lints are journaled at plan time too, at the mix's severity
    for rule in ("voice-clean", "voice-chop", "voice-beside"):
        assert {e["unit"] for e in lints(evs, rule)} >= {*BASE, "NLOW"}, rule
    assert [e for e in lints(evs, "narrator-eq")][0]["severity"] == "block"


def test_a_lower_mood_may_drop_it_and_a_draft_plan_warns(tmp_path, takes_cache, low_take):
    film = _narration_film(tmp_path, low_take, low_mood="grave")
    j = J.Journal(film="preflight-voice-grave")
    plan = _plan(film, j)                                          # grave may sit 3 semitones under
    assert plan["_takes"]["refusal"] is None
    film2 = _narration_film(tmp_path / "d", low_take)
    jd = J.Journal(film="preflight-voice-draft")
    plan = _plan(film2, jd, draft=True)
    low = [e for e in lints(J.read(jd.path), "narrator-consistency") if e["unit"] == "NLOW"][0]
    assert low["status"] == "fail" and low["severity"] == "warn" and plan["_takes"]["draft"] is True


def _verdicts(evs, units):
    keep = ("rule", "unit", "status", "severity", "grammar", "evidence")
    rows = [{k: e.get(k) for k in keep} for e in lints(evs) if e.get("unit") in units or e.get("unit") in
            ("narrator", "narrator-f0", "narrator-centroid", "readers")]
    return sorted(json.dumps(r, sort_keys=True) for r in rows if r["rule"] in R.SOUND_LINTS)


def test_the_plan_and_the_mix_give_the_same_verdicts(tmp_path, takes_cache, low_take):
    film = _narration_film(tmp_path, low_take)
    jp = J.Journal(film="pv-plan")
    plan = _plan(film, jp, draft=True)
    jm = J.Journal(film="pv-mix")                                  # another journal: the mix journals its own copies
    R.build_mix(plan, film, jm, draft=True)
    units = {*BASE, "NLOW", "L2"}
    assert _verdicts(J.read(jp.path), units) == _verdicts(J.read(jm.path), units)
    assert {"narrator-consistency", "voice-clean", "voice-chop", "narrator-eq"} <= {
        json.loads(r)["rule"] for r in _verdicts(J.read(jp.path), units)}


def test_a_render_journals_the_take_lints_once(tmp_path, takes_cache, low_take):
    film = _narration_film(tmp_path, low_take)
    j = J.Journal(film="pv-once")
    plan = _plan(film, j, draft=True)
    n_plan = len(lints(J.read(j.path)))
    R.build_mix(plan, film, j, draft=True)                         # the same journal, as render() runs them
    evs = J.read(j.path)
    for rule in ("voice-clean", "voice-chop", "voice-beside", "narrator-consistency", "narrator-eq"):
        units = [e["unit"] for e in lints(evs, rule)]
        assert len(units) == len(set(units)), (rule, units)
    assert len([e for e in evs if e.get("lens") == "narrator-profile"]) == 1
    assert len(lints(evs)) > n_plan                                # the mix's own lints (the edges, the ceiling) still run


def test_a_changed_take_is_judged_again_by_the_mix(tmp_path, takes_cache, low_take):
    film = _narration_film(tmp_path, low_take)
    j = J.Journal(film="pv-changed")
    plan = _plan(film, j, draft=True)
    _wav(film / "audio" / "NA.wav", _speech(181.0, seed=5))       # re-rendered after the plan
    R.build_mix(plan, film, j, draft=True)
    na = [e for e in lints(J.read(j.path), "voice-clean") if e["unit"] == "NA"]
    assert len(na) == 2                                            # the plan's, and the mix's for the new take
    assert len([e for e in J.read(j.path) if e.get("lens") == "narrator-profile"]) == 2


def test_the_cache_is_keyed_by_take_sha_and_a_warm_plan_measures_nothing(tmp_path, takes_cache, low_take, monkeypatch):
    film = _narration_film(tmp_path, low_take)
    j1 = J.Journal(film="pv-cold")
    p1 = _plan(film, j1, draft=True)
    assert p1["_takes"]["measured"] == 6 and p1["_takes"]["cached"] == 0      # L1, L2 and the four N lines
    assert len(list(takes_cache.glob("*.json"))) == 6 and not (film / "cache" / "takes").exists()
    calls = []
    real = R.process_take
    monkeypatch.setattr(R, "process_take", lambda *a, **k: calls.append(1) or real(*a, **k))
    j2 = J.Journal(film="pv-warm")
    p2 = _plan(film, j2, draft=True)
    assert p2["_takes"]["measured"] == 0 and p2["_takes"]["cached"] == 6 and not calls
    units = {*BASE, "NLOW", "L2"}
    assert _verdicts(J.read(j1.path), units) == _verdicts(J.read(j2.path), units)
    _wav(film / "audio" / "NB.wav", _speech(179.0, seed=7))        # a new take: a new sha, measured again
    p3 = _plan(film, J.Journal(film="pv-new"), draft=True)
    assert p3["_takes"]["measured"] == 1 and p3["_takes"]["cached"] == 5 and len(calls) == 1


def test_the_cache_defaults_to_the_films_cache_folder(tmp_path, monkeypatch):
    monkeypatch.delenv("DOCUMENT_TAKES_CACHE", raising=False)
    assert R.takes_cache_dir(tmp_path) == tmp_path / "cache" / "takes"
    monkeypatch.setenv("DOCUMENT_TAKES_CACHE", str(tmp_path / "elsewhere"))
    assert R.takes_cache_dir(tmp_path) == tmp_path / "elsewhere"


def test_a_preview_plan_runs_no_take_lints_and_writes_no_cache(tmp_path, takes_cache, low_take):
    film = _narration_film(tmp_path, low_take)
    j = J.Journal(film="pv-sheets")
    plan = SH.plan_stills(film, j)                                 # contact sheets and tourlint plan through here
    evs = J.read(j.path)
    assert plan["_takes"] is None and not lints(evs, "narrator-consistency") and not lints(evs, "voice-clean")
    assert [e for e in evs if e["kind"] == "decision" and e.get("unit") == "takes"][0]["what"].startswith(
        "take lints not run")
    assert not takes_cache.exists() and not (film / "cache" / "takes").exists()
    with pytest.raises(ValueError, match="take lints mode"):
        _plan(film, J.Journal(film="pv-bad-mode"), voice_lints="cached")
