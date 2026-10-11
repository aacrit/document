"""GRAMMAR A0, the founding principle: show as was, not as is, and never tell
(studio/engine/aswas.py). Every lint is tested both ways: what it must refuse
and what it must let pass. The text cases are shared with the site's suite
(tests/fixtures/a0-cases.json, run by tests/show-as-was.test.ts)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from studio.engine import aswas as AW
from studio.engine import journal as J
from studio.engine import render as R

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads((ROOT / "tests" / "fixtures" / "a0-cases.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# The shared text cases (the site runs the same file)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES["hindsight"], ids=lambda c: c["text"][:40])
def test_hindsight_phrases(case):
    assert [h["phrase"] for h in AW.phrase_hits(case["text"], AW.lexicon()["hindsight"])] == case["expect"]


@pytest.mark.parametrize("case", CASES["never_tell"], ids=lambda c: c["text"][:40])
def test_never_tell_phrases(case):
    assert [h["phrase"] for h in AW.phrase_hits(case["text"], AW.lexicon()["never_tell"])] == case["expect"]


@pytest.mark.parametrize("case", CASES["modern_names"], ids=lambda c: c["text"][:40])
def test_modern_names(case):
    horizon = AW.parse_date(case["as_of"])
    assert [h["modern"] for h in AW.modern_name_hits(case["text"], horizon, AW.name_entries())] == case["expect"]


@pytest.mark.parametrize("case", CASES["years"], ids=lambda c: c["text"][:40])
def test_years(case):
    assert AW.years_in(case["text"]) == case["expect"]


@pytest.mark.parametrize("case", CASES["dates"], ids=lambda c: str(c["value"])[:40])
def test_dates(case):
    got = AW.parse_date(case["value"])
    assert (None if got is None else [got[0].isoformat().rjust(10, "0"), got[1].isoformat()]) == case["expect"]


def test_the_lexicon_is_one_file_with_every_list():
    lex = AW.lexicon()
    assert {g["id"] for g in lex["hindsight"]} == {"future-in-past", "elapsed-time", "present-day", "knowledge-now", "persistence"}
    assert {g["id"] for g in lex["never_tell"]} == {"first-person-opinion", "prescriptive", "editorial-adjectives",
                                                    "verdict-adverbs", "mind-reading"}
    for e in lex["period_names"]:
        assert e["modern"] and e["period"] and AW.parse_date(e["until"]) is not None, e
    # every phrase is lowercase words, so case never decides a match
    for g in lex["hindsight"] + lex["never_tell"]:
        assert all(p == p.lower() and p.strip() == p for p in g["phrases"]), g["id"]


# --------------------------------------------------------------------------
# A screenplay, built small: the checks are pure functions of it and its ledgers
# --------------------------------------------------------------------------


def play(**over) -> dict:
    p = {
        "title": "A0 test", "slug": "a0-test", "as_of": "1951", "runtime_target_s": 30,
        "parts": [
            {"id": "ch-1", "kind": "chapter", "number": 1, "title": "The line", "dates": "1946 to 1951",
             "shots": [
                 {"id": "S1", "kind": "card", "start_s": 0, "dur_s": 3, "text": ["1  The line", "1946 to 1951"], "mark": "CARD"},
                 {"id": "S2", "kind": "archive_still", "asset": "A-1947", "start_s": 3, "dur_s": 8, "mark": "ARCHIVE"},
                 {"id": "S3", "kind": "card", "start_s": 11, "dur_s": 6, "mark": "CARD",
                  "text": ["The Governor wrote of twelve districts.", "The Transfer of Power vol. XII, 1947"]},
             ],
             "lines": [
                 {"id": "N1", "kind": "narration", "start_s": 4, "text": "In August nineteen forty-seven the Governor wrote to the Viceroy."},
                 {"id": "T1", "kind": "testimony", "start_s": 12, "year": 1947, "speaker": "sp-a",
                  "text": "We do not stand today for domination; it was a tragic hour."},
             ],
             "text": [
                 {"id": "LT1", "kind": "lower_third", "start_s": 12, "end_s": 16,
                  "lines": ["Sir Evan Jenkins", "Governor of the Punjab, 1947",
                            "Collected Papers 1947 to 1970, Dhaka University  ·  read by a computer voice"]},
             ],
             "cues": []},
            {"id": "credits", "kind": "credits", "shots": [
                {"id": "E1", "kind": "card", "start_s": 17, "dur_s": 4, "card": "attribution", "mark": "CARD",
                 "text": ["Archives: Wikimedia Commons, 2026", "Every shot, its source and licence: document.voidvision.org today"]},
                {"id": "E2", "kind": "card", "start_s": 21, "dur_s": 4, "card": "mark_key", "mark": "CARD", "text": []},
            ], "lines": [], "text": [], "cues": []},
        ],
    }
    p.update(over)
    return p


ASSETS = {"A-1947": {"id": "A-1947", "date": "1947-08-15", "archive": "Wikimedia Commons"}}


def failing(res, rule=None, severity="block"):
    return [c for c in res if not c["ok"] and c["severity"] == severity and (rule is None or c["rule"] == rule)]


def units(res, rule, severity="block"):
    return sorted(c["unit"] for c in failing(res, rule, severity))


def part(p, pid="ch-1"):
    return next(x for x in p["parts"] if x["id"] == pid)


def test_a_sound_screenplay_passes_every_a0_lint():
    res = AW.checks(play(), ASSETS)
    assert failing(res) == []
    # metadata is exempt: the attribution card says "today" and 2026, the lower third's attribution line a modern name
    assert {c["rule"] for c in res if c["ok"]} >= {"as-of-declared", "as-of", "hindsight-language", "modern-names", "never-tell",
                                                   "ending-question"}


# as-of ----------------------------------------------------------------------


def test_as_of_must_be_declared():
    p = play()
    del p["as_of"]
    res = AW.checks(p, ASSETS)
    assert units(res, "as-of-declared") == ["as_of"]
    assert not any(c["rule"] == "as-of" for c in res)                # nothing can be dated without a horizon
    assert units(AW.checks(play(as_of="sometime"), ASSETS), "as-of-declared") == ["as_of"]
    assert units(AW.checks(play(as_of="1951-06"), ASSETS), "as-of-declared") == []


def test_an_era_past_the_horizon_is_refused():
    assert units(AW.checks(play(era={"from": 1946, "to": 1960}), ASSETS), "as-of") == ["era"]
    assert units(AW.checks(play(era={"from": 1946, "to": 1951}), ASSETS), "as-of") == []


@pytest.mark.parametrize("item,ok", [
    ({"date": "1947-08-15"}, True),
    ({"date": "1951"}, True),
    ({"year": 1950}, True),
    ({"date": "before 1948"}, True),
    ({"date": "1959 (compiled 1954 from Survey of India sheets of 1917 to 1943)"}, False),     # printed after the horizon
    ({"date": "1950s"}, False),                                       # may postdate: imprecise across the horizon
    ({"date": "10 April 2026"}, False),
    ({}, False),                                                      # undated
    ({"date": "2026", "generator": "studio/engine/maps.py"}, False),  # studio-made, dated by the making
    ({"date": "2026", "generator": "maps.py", "content_date": "1947", "content_basis": "the 1941 census table"}, True),
    ({"date": "2026", "generator": "maps.py", "content_date": "2020", "content_basis": "Natural Earth 5.1 borders"}, False),
    ({"date": "2026", "generator": "maps.py", "content_date": "1947"}, False),          # no basis
    ({"date": "2026", "synthetic": True, "test_fixture": True}, True),                 # an engine test stand-in
])
def test_every_shot_is_dated_on_or_before_the_horizon(item, ok):
    res = AW.checks(play(), {"A-1947": dict(item, id="A-1947")})
    assert (units(res, "as-of") == []) is ok, failing(res, "as-of")


def test_a_later_printing_dated_by_its_content_is_a_review_item():
    item = {"id": "A-1947", "date": "1959 (compiled 1954)", "content_date": "1943", "content_basis": "compiled from Survey of India sheets of 1917 to 1943"}
    res = AW.checks(play(), {"A-1947": item})
    assert units(res, "as-of") == []
    assert [c["unit"] for c in res if c["rule"] == "as-of" and c["severity"] == "review"] == ["S2"]


def test_a_card_source_is_dated():
    p = play()
    part(p)["shots"][2]["text"][-1] = "CDC and the Smallpox Crusade (1987), on 1970"
    assert units(AW.checks(p, ASSETS), "as-of") == ["S3"]
    p = play()
    part(p)["shots"][2]["source_date"] = "1987"                          # stated wins over the line
    assert units(AW.checks(p, ASSETS), "as-of") == ["S3"]
    p = play()
    part(p)["shots"][2].update(text=["The Governor wrote of twelve districts.", "The Governor's telegram"], quote=True)
    assert units(AW.checks(p, ASSETS), "as-of") == ["S3"]                 # a quoted card names its source's date
    part(p)["shots"][2]["source_date"] = "1947-08-08"
    assert units(AW.checks(p, ASSETS), "as-of") == []
    # the chapter card's dates line is not a source; the credits part, attribution card and mark key are metadata
    p = play()
    part(p)["shots"][0]["text"][1] = "1946 to 1951"
    assert units(AW.checks(p, ASSETS), "as-of") == []


def test_a_reading_and_an_archival_recording_are_dated():
    p = play()
    part(p)["lines"][1]["year"] = 1997                                  # a memoir decades later
    assert units(AW.checks(p, ASSETS), "as-of") == ["T1"]
    p = play()
    del part(p)["lines"][1]["year"]
    assert units(AW.checks(p, ASSETS), "as-of") == ["T1"]
    p = play()
    part(p)["lines"][1].update(archival_audio=True, clip="REEL")
    assets = dict(ASSETS, REEL={"id": "REEL", "date": "1965"})
    assert units(AW.checks(p, assets), "as-of") == ["T1"]
    assets["REEL"]["date"] = "1947"
    assert units(AW.checks(p, assets), "as-of") == []


def test_a_mark_on_a_sheet_claims_nothing_after_the_horizon():
    p = play()
    part(p)["shots"][1]["marks"] = [{"id": "K1", "feature_year": 1947, "geometry_year": 2020}]
    assert units(AW.checks(p, ASSETS), "as-of") == ["S2/K1"]
    part(p)["shots"][1]["marks"][0]["geometry_year"] = 1947
    assert units(AW.checks(p, ASSETS), "as-of") == []


def test_ambience_recorded_after_the_horizon_is_a_warning():
    p = play()
    part(p)["cues"] = [{"id": "C1", "kind": "ambience", "source": "AMB", "start_s": 0, "end_s": 5}]
    res = AW.checks(p, dict(ASSETS, AMB={"id": "AMB", "date": "2019"}))
    assert units(res, "as-of") == [] and units(res, "as-of", "warn") == ["C1"]


# known-by -------------------------------------------------------------------


def facts_film(tmp_path, facts) -> Path:
    (tmp_path / "facts.json").write_text(json.dumps({"facts": facts}), encoding="utf-8")
    return tmp_path


def test_known_by_warns_when_no_fact_carries_an_id():
    res = AW.checks(play(), ASSETS)
    assert units(res, "known-by", "warn") == [None] and units(res, "known-by") == []


def test_known_by_reads_each_fact_against_the_horizon(tmp_path):
    p = play(facts_ledger="facts.json")
    part(p)["lines"][0]["facts"] = ["F1"]
    ok = {"id": "F1", "known_by": "1947-08-08", "known_by_basis": "the Governor's telegram of 8 August 1947",
          "sources": ["a book of 1990 that prints it"]}
    assert units(AW.checks(p, ASSETS, film=facts_film(tmp_path, [ok])), "known-by") == []
    late = dict(ok, known_by="1972", known_by_basis="a later census")
    assert units(AW.checks(p, ASSETS, film=facts_film(tmp_path, [late])), "known-by") == ["N1"]
    nobasis = {k: v for k, v in ok.items() if k != "known_by_basis"}
    assert units(AW.checks(p, ASSETS, film=facts_film(tmp_path, [nobasis])), "known-by") == ["N1"]
    assert units(AW.checks(p, ASSETS, film=facts_film(tmp_path, [dict(ok, id="F2")])), "known-by") == ["N1"]    # unresolved
    p2 = play()
    part(p2)["lines"][0]["facts"] = ["F1"]
    assert units(AW.checks(p2, ASSETS, film=tmp_path), "known-by") == ["facts_ledger"]                       # no ledger named


# the language lints ---------------------------------------------------------------


def test_hindsight_language_on_narration_cards_lower_thirds_and_parts():
    p = play()
    part(p)["lines"][0]["text"] = "The line would later be called a scar."
    part(p)["shots"][2]["text"][0] = "Decades later, the enclaves were exchanged."
    part(p)["text"][0]["lines"][1] = "Governor of the Punjab, today a province of Pakistan"
    part(p)["dates"] = "1947 to today"
    assert units(AW.checks(p, ASSETS), "hindsight-language") == ["LT1", "N1", "S3", "part ch-1"]


def test_a_year_after_the_horizon_is_hindsight_and_a_quote_is_not():
    p = play()
    part(p)["lines"][0]["text"] = "The enclaves were exchanged on the thirty-first of July, two thousand and fifteen."
    assert units(AW.checks(p, ASSETS), "hindsight-language") == ["N1"]
    part(p)["lines"][0]["text"] = "He wrote, “by 1990 the line will be forgotten”, and signed."
    assert units(AW.checks(p, ASSETS), "hindsight-language") == []


def test_quoted_period_speech_is_exempt():
    p = play()                                     # the testimony says "today" and "tragic": a period voice may judge
    part(p)["shots"][2].update(text=["Today the line is drawn; a tragic day.", "The Statesman, 18 August 1947"], quote=True)
    part(p)["text"][0]["quote"] = True
    part(p)["text"][0]["lines"][0] = "Today in Dhaka"
    res = AW.checks(p, ASSETS)
    assert failing(res) == []


def test_modern_names_against_the_horizon_and_the_films_own_map():
    p = play()
    part(p)["lines"][0]["text"] = "In Dhaka, in March nineteen forty-eight, she spoke."
    assert units(AW.checks(p, ASSETS), "modern-names") == ["N1"]
    part(p)["lines"][0]["text"] = "In Dacca, in March nineteen forty-eight, she spoke."
    assert units(AW.checks(p, ASSETS), "modern-names") == []
    assert units(AW.checks(dict(p, as_of="1990"), ASSETS), "modern-names") == []
    part(p)["lines"][0]["text"] = "In Shimla, in May nineteen forty-seven."
    assert units(AW.checks(p, ASSETS), "modern-names") == []
    p2 = dict(p, period_names=[{"modern": "Shimla", "period": "Simla", "until": "1972"}])
    assert units(AW.checks(p2, ASSETS), "modern-names") == ["N1"]


def test_never_tell_refuses_tara_and_lets_the_period_judge():
    p = play()
    part(p)["lines"][0]["text"] = "We believe it was a tragic hour, and we must remember it."
    hits = failing(AW.checks(p, ASSETS), "never-tell")
    assert [c["unit"] for c in hits] == ["N1"]
    assert [h["phrase"] for h in hits[0]["evidence"]["hits"]] == ["we believe", "we must", "tragic"]
    part(p)["lines"][0]["text"] = "In August the award said the line should follow the canal."
    assert units(AW.checks(p, ASSETS), "never-tell") == []


# the ending -----------------------------------------------------------------------


def event_play(last: dict, after: dict | None = None) -> dict:
    p = play(runtime_target_s=1200)
    lines = part(p)["lines"]
    lines.append(dict(last, start_s=15))
    if after:
        lines.append(dict(after, start_s=16))
    return p


Q = {"id": "NQ", "kind": "narration", "text": "Who decides where a river runs?"}


def test_the_ending_is_one_question_with_nothing_voiced_after_it():
    assert units(AW.checks(event_play(Q), ASSETS), "ending-question") == []
    statement = dict(Q, text="A river can be named in an award. It cannot be told which side to run on.")
    assert units(AW.checks(event_play(statement), ASSETS), "ending-question") == ["NQ"]
    reading = {"id": "TZ", "kind": "testimony", "year": 1947, "speaker": "sp-a", "text": "I believe it will not last."}
    assert units(AW.checks(event_play(Q, reading), ASSETS), "ending-question") == ["TZ"]
    quoted = dict(Q, text="She asked, “of whom are they frightened?”")
    assert units(AW.checks(event_play(quoted), ASSETS), "ending-question") == []
    # a short piece (the fixture, a trailer) needs no ending
    assert units(AW.checks(play(), ASSETS), "ending-question") == []


def test_a_closing_question_naming_a_year_after_the_horizon_is_a_warning():
    res = AW.checks(event_play(dict(Q, text="What will the river be in nineteen seventy-one?")), ASSETS)
    assert units(res, "ending-question") == [] and units(res, "ending-question-year", "warn") == ["NQ"]


# through the engine: build_plan journals A0 and refuses on it ----------------------


def test_build_plan_journals_a0_and_refuses_hindsight(film, tmp_path):
    f = tmp_path / "fixture"
    shutil.copytree(film, f, ignore=shutil.ignore_patterns("cache", "out"))
    j = J.Journal(film="a0-pass")
    R.build_plan(f, W=640, H=360, burn_subtitles=False, journal=j)
    a0 = [e for e in J.read(j.path) if e["kind"] == "lint" and e.get("grammar") == "A0"]
    assert {e["rule"] for e in a0} >= {"as-of-declared", "as-of", "hindsight-language", "modern-names", "never-tell", "ending-question"}
    assert all(e["status"] != "fail" or e["severity"] != "block" for e in a0)
    sp = json.loads((f / "screenplay.json").read_text(encoding="utf-8"))
    sp["parts"][1]["lines"][0]["text"] = "A test tone that would later stand in for the narrator."
    (f / "screenplay.json").write_text(json.dumps(sp), encoding="utf-8")
    with pytest.raises(R.Refused, match="hindsight-language"):
        R.build_plan(f, W=640, H=360, burn_subtitles=False, journal=J.Journal(film="a0-refuse"))
    del sp["as_of"]
    sp["parts"][1]["lines"][0]["text"] = "A test tone stands in for the narrator."
    (f / "screenplay.json").write_text(json.dumps(sp), encoding="utf-8")
    with pytest.raises(R.Refused, match="as-of-declared"):
        R.build_plan(f, W=640, H=360, burn_subtitles=False, journal=J.Journal(film="a0-undeclared"))
