"""GRAMMAR A56: the dot is the only provenance in the picture; disclosures live in the sources data."""
import json
from pathlib import Path

import pytest

from studio.engine import disclosure as DS
from studio.engine import journal as J
from studio.engine import render as R

from conftest import make_film


# Each versioned pattern, a string it must refuse and a near miss it must pass (META_TEXT_VERSION 2)
REFUSE = [
    ("source-gap", "card", "The record holds no open-licence film of this fixture."),
    ("source-gap", "card", "No photograph of the crew survives."),
    ("source-gap", "card", "The meeting was never filmed."),
    ("source-gap", "overlay", "No open-licence footage of the tower exists"),
    ("descriptor", "lower_third", "A woman's voice"),
    ("descriptor", "lower_third", "a voice on the NEADS floor"),
    ("descriptor", "lower_third", "An unidentified controller"),
    ("descriptor", "lower_third", "A pilot"),                                  # v2: role-noun forms
    ("descriptor", "lower_third", "An air traffic controller"),
    ("descriptor", "lower_third", "a controller at Boston Center"),
    ("descriptor", "lower_third", "A reporter, name not given"),
    ("descriptor", "subtitle", "[A flight attendant]"),
    ("computer-voice", "lower_third", "Fixture source  ·  read by a computer voice"),
    ("computer-voice", "card", "Read by a computer voice. No recording of him was used."),
    ("original-recording", "overlay", "original recording"),
    ("provenance", "lower_third", "National Archives, FAA tapes"),
    ("provenance", "map", "Data: Natural Earth; GeoNames"),
    ("provenance", "overlay", "Courtesy of the Library of Congress"),
    ("provenance", "card", "Archives: FAA and NORAD recordings"),              # v2: a card's source line is provenance
    ("provenance", "card", "National Archives, RG 237"),
    ("provenance", "overlay", "Footage held by the National Archives"),
    ("mark-key", "card", "What the marks mean"),
    ("mark-key", "card", "No picture in this film is AI-generated."),
    ("shortfall", "card", "A woman's voice carries only {women_share:pct} of them."),
    ("shortfall", "card", "The film says so rather than invent."),
]
PASS = [
    ("card", "0835E: ... Pilot keyed mike while threat was being made in the cockpit."),
    ("card", "FAA headquarters, chronology ADA-30, 11 September 2001"),          # a quoted document's own citation
    ("lower_third", "American 11 and Boston Center"),
    ("lower_third", "Foxy, NEADS"),
    ("lower_third", "George W. Bush"),
    ("overlay", "29.97 fps, 4 s"),
    ("map", "Lower Manhattan"),
    ("lower_third", "Major Nasypany, NEADS"),
    ("lower_third", "The Reverend Gerard Creedon"),
    ("lower_third", "A pilot and New York Center"),                            # a call between posts, not a descriptor
    ("subtitle", "A pilot reported smoke in the cabin."),                      # words, not a speaker line
    ("map", "Library of Congress"),                                            # v2: a place on a map is map content
    ("map", "National Archives"),
    ("overlay", "Walking past the Library of Congress"),                       # v2: named in passing, not credited
    ("card", "The archives of the Library of Congress hold the letters."),
]


@pytest.mark.parametrize("pattern, role, text", REFUSE)
def test_each_pattern_refuses_its_fixture(pattern, role, text):
    hits = DS.meta_text_problems(text, role)
    assert pattern in [h["pattern"] for h in hits], (text, hits)


@pytest.mark.parametrize("role, text", PASS)
def test_names_roles_and_quoted_documents_pass(role, text):
    assert DS.meta_text_problems(text, role) == [], text


def test_the_patterns_are_versioned_and_named():
    assert DS.META_TEXT_VERSION == 2
    assert set(DS.META_TEXT_NAMES) == {"source-gap", "descriptor", "computer-voice", "original-recording", "provenance",
                                       "mark-key", "shortfall"}
    assert {p for p, _, _ in REFUSE} == set(DS.META_TEXT_NAMES)               # a fixture per pattern


def test_a_hostile_string_is_read_as_text_and_reported_verbatim():
    evil = '"><img src=x onerror=alert(1)> read by a computer voice'
    hits = DS.meta_text_problems(evil, "lower_third")
    assert [h["pattern"] for h in hits] == ["computer-voice"]
    assert DS.meta_text_problems('"><img src=x onerror=alert(1)>', "card") == []


def test_a_lower_third_is_name_and_role_only():
    assert DS.lower_third_problems(["George W. Bush", "President, 9:30 a.m."]) == []
    assert "provenance line" in DS.lower_third_problems(["A", "B", "Source, archive  ·  original recording"])[0]
    assert DS.lower_third_problems(["Only a name"])


def test_the_label_is_the_class_word_and_one_qualifier():
    assert DS.label_problems("Archive · photographed Apr 2001") == []
    assert DS.label_problems("Archive · 1947 · stabilised")
    assert DS.label_problems("Archive · National Archives", forbidden=["National Archives"])
    assert DS.label_problems("Archive · photographed on a long afternoon in April")


# ---- the plan --------------------------------------------------------------------------------------------------------

@pytest.fixture
def film(tmp_path):
    return make_film(tmp_path / "fixture")


def _edit(film: Path, fn):
    p = film / "screenplay.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    fn(d)
    p.write_text(json.dumps(d), encoding="utf-8")


def _plan(film, name):
    j = J.Journal(film=name)
    plan = R.build_plan(film, W=640, H=360, burn_subtitles=False, journal=j)
    return plan, j


def _s7(p):
    return next(s for s in p["parts"][1]["shots"] if s["id"] == "S7")


def test_the_fixture_film_plans_with_no_meta_text(film):
    _, j = _plan(film, "a56-clean")
    evs = [e for e in J.read(j.path) if e.get("rule") == "meta-text"]
    assert [e["status"] for e in evs] == ["pass"]


@pytest.mark.parametrize("change, unit", [
    (lambda p: _s7(p).update(silent_record=True, text=["The record holds no open-licence film of this fixture."]), "S7"),
    (lambda p: _s7(p).update(card="mark_key", text=[]), "S7"),
    (lambda p: _s7(p).update(text=["No photograph of the fixture survives."]), r"S7\.text\[0\]"),
    (lambda p: p["parts"][1]["text"].append({"id": "T9", "kind": "overlay", "start_s": 9.0, "end_s": 10.0,
                                             "lines": ["Courtesy of the Library of Congress"]}), "T9"),
    (lambda p: p["parts"][1]["text"].append({"id": "T9", "kind": "lower_third", "start_s": 9.0, "end_s": 10.0,
                                             "lines": ["A woman's voice", "11 September 2001"]}), r"T9\.lines\[0\]"),
])
def test_meta_text_refuses_in_the_frame(film, change, unit):
    _edit(film, change)
    with pytest.raises(R.Refused, match=rf"meta-text \({unit}\)"):
        _plan(film, "a56-refused")


def test_a_period_quote_card_is_the_periods_own_words(film):
    _edit(film, lambda p: _s7(p).update(quote=True, source_date="1947", text=["\"No photograph was taken of the signing.\""]))
    _plan(film, "a56-quote")


def test_a_quote_cards_source_line_is_ours_and_is_read(film):
    words = "\"No photograph was taken of the signing.\""
    _edit(film, lambda p: _s7(p).update(quote=True, source_date="1947", text=[words, "Fixture Gazette, 1947"]))
    _plan(film, "a56-quote-src")
    _edit(film, lambda p: _s7(p).update(quote=True, source_date="1947", text=[words, "Courtesy of the National Archives"]))
    with pytest.raises(R.Refused, match=r"meta-text \(S7\.text\[1\]\)"):
        _plan(film, "a56-quote-prov")


def test_a_statement_cards_provenance_line_is_refused(film):
    _edit(film, lambda p: _s7(p).update(text=["Archives: FAA and NORAD recordings"]))
    with pytest.raises(R.Refused, match=r"meta-text \(S7\.text\[0\]\)"):
        _plan(film, "a56-card-prov")


def test_an_original_recordings_burned_cues_are_its_own_words():
    from types import SimpleNamespace
    found = []
    play = {"parts": [{"lines": [{"id": "A1", "archival_audio": True, "clip": "FX"}, {"id": "L1"}]}],
            "subtitle_source": [{"ref": "A1-1", "en": "[A pilot]"}, {"ref": "L1", "en": "[A pilot]"}]}
    R.meta_text_lints(lambda *a, **k: found.append((a, k)), play, [], [], [], burn_subtitles=True)
    units = [k.get("unit") for a, k in found if a[1] is False]
    assert units == ["subtitle:L1"]                     # the tape's verbatim cue is exempt; our own cue is read


# ---- gaps: what the record lacks is stated in the sources data -------------------------------------------------------

GAP = {"says": "The record holds no open-licence film of this fixture.", "searched": "Searched: the fixture archive."}


def test_a_gap_is_stated_in_the_sources_data(film):
    _edit(film, lambda p: p.update(gaps=[GAP]))
    plan, j = _plan(film, "a56-gap")
    assert plan["gaps"] == [GAP]
    evs = [e for e in J.read(j.path) if e.get("rule") == "source-gap-stated"]
    assert [e["status"] for e in evs] == ["pass"]


@pytest.mark.parametrize("gap", [{"says": "No film.", "searched": "x"}, {"says": GAP["says"]},
                                 {"says": GAP["says"], "searched": "x", "where": "?"}, "a gap"])
def test_a_malformed_gap_is_refused(film, gap):
    _edit(film, lambda p: p.update(gaps=[gap]))
    with pytest.raises(R.Refused, match=r"source-gap-stated \(gaps\[0\]\)"):
        _plan(film, "a56-gap-bad")


def test_where_a_silent_card_stood_a_gap_must_say_it(film):
    card = lambda p: _s7(p).update(silent_record=True, text=[GAP["says"], GAP["searched"]])
    _edit(film, card)
    with pytest.raises(R.Refused, match=r"source-gap-stated \(S7\)"):
        _plan(film, "a56-silent-nogap")
    _edit(film, lambda p: p.update(gaps=[GAP]))
    with pytest.raises(R.Refused) as e:                  # the card itself is still refused, the gap is now stated
        _plan(film, "a56-silent-gap")
    assert "meta-text (S7)" in str(e.value) and "source-gap-stated (S7)" not in str(e.value)


# ---- map notes: not drawn, stated in the sources data ----------------------------------------------------------------

def test_a_maps_notes_reach_the_ledger_and_the_method_says_where():
    from studio.engine import maps
    spec = {"id": "m", "title": "A map", "source_short": "Fixture, p. 1",
            "sources": [{"id": "fixture-src:p1", "licence": "CC0"}],
            "notes": ["Line approximate, from the award's description.", "Boundaries after 1950 are not drawn."]}
    led = maps.ledger_fields(spec)
    assert led["notes"] == spec["notes"]
    assert "the sources data notes the line is approximate" in led["method"]["text"]
    assert "the sources data notes what is not drawn" in led["method"]["text"]
    assert "the frame" not in led["method"]["text"]


def test_the_mark_key_card_points_to_the_marks_legend(film):
    _edit(film, lambda p: _s7(p).update(card="mark_key", text=[]))
    with pytest.raises(R.Refused, match=r"player's Marks legend"):
        _plan(film, "a56-key")
    assert R.mark_key_lints(J.Journal(film="a56-nokey"), {"shots": []}) == []


def test_a_three_line_lower_third_is_refused(film):
    _edit(film, lambda p: p["parts"][1]["text"][0].update(
        lines=["Fixture speaker", "Test stand-in, 1947", "Fixture source, studio test folder  ·  read by a computer voice"]))
    with pytest.raises(R.Refused, match=r"lower-third-format \(T1\).*provenance line"):
        _plan(film, "a56-lt3")


def test_the_reading_disclosure_is_in_the_sources_data_and_not_in_the_credits(film):
    plan, j = _plan(film, "a56-readings")
    rd = R.readings_doc(plan, durations=False)
    assert next(r for r in rd if r["id"] == "L2")["credit"].startswith("Read by a computer voice.")
    heads = [h for h, _ in plan["credits"]]
    assert "Readings" not in heads
    assert not any("computer voice" in ln or "original recording" in ln for _, lines in plan["credits"] for ln in lines)


def test_an_attribution_card_in_the_credits_is_the_attribution_not_provenance(film):
    attribution = ["Archives: FAA and NORAD recordings", "Public domain and CC BY 2.0 unless marked."]
    _edit(film, lambda p: p["parts"][2]["shots"][0].update(card="statement", text=attribution))
    _, j = _plan(film, "a56-credits-attribution")
    assert [e["status"] for e in J.read(j.path) if e.get("rule") == "meta-text"] == ["pass"]
    # every other pattern is still read there
    _edit(film, lambda p: p["parts"][2]["shots"][0].update(text=["Read by a computer voice."]))
    with pytest.raises(R.Refused, match=r"meta-text \(S9\.text\[0\]\)"):
        _plan(film, "a56-credits-voice")
