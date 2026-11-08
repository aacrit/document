"""Film-level dated notes (founder, 2026-11-02, Market Street's brand audit): the house's notes about a film,
outside its horizon, carried by the screenplay's top-level ``film_notes`` into sources.json, validated at plan time
(lint ``film-note``, blocking). First use: Market Street's later death counts, moved off its end card."""
import json
from pathlib import Path

import pytest

from studio.engine import journal as J
from studio.engine import render as R

from conftest import make_film

NOTE = {"text": "The dead were counted at 478 by the city in 1907 and 498 by the Army in 1906. Research since names "
                "more than 3,000.",
        "noted": "2026-11-02",
        "source": "498: the Army's report (1906), page 15. More than 3,000: Hansen and Condon, Denial of Disaster (1989)."}
EVIL = '"><img src=x onerror=alert(1)>'


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
    return R.build_plan(film, W=640, H=360, burn_subtitles=False, journal=j), j


def test_film_notes_reach_the_plan_and_sources_json(film):
    hostile = {"text": EVIL, "noted": "2026-11-02", "source": None}
    _edit(film, lambda p: p.update(film_notes=[NOTE, hostile]))
    plan, j = _plan(film, "film-notes")
    assert plan["film_notes"] == [NOTE, hostile]         # printed as written; the site escapes it
    assert R.sources_doc(plan, j, {})["film_notes"] == [NOTE, hostile]
    evs = [e for e in J.read(j.path) if e.get("rule") == "film-note"]
    assert [e["status"] for e in evs] == ["pass", "pass"]


def test_a_film_with_no_notes_states_an_empty_list(film):
    plan, j = _plan(film, "film-notes-none")
    assert plan["film_notes"] == [] and R.sources_doc(plan, j, {})["film_notes"] == []


def test_a_source_may_be_left_out_and_is_then_null(film):
    _edit(film, lambda p: p.update(film_notes=[{"text": "A note.", "noted": "2026-11-02"}]))
    plan, _ = _plan(film, "film-notes-nosource")
    assert plan["film_notes"] == [{"text": "A note.", "noted": "2026-11-02", "source": None}]


@pytest.mark.parametrize("note", [
    {"text": "", "noted": "2026-11-02", "source": None},                       # empty text
    {"text": "   ", "noted": "2026-11-02", "source": None},                    # blank text
    {"noted": "2026-11-02", "source": None},                                   # no text
    {"text": "A note.", "noted": "2 November 2026", "source": None},           # not an ISO date
    {"text": "A note.", "noted": "2026-11", "source": None},                   # not a full date
    {"text": "A note.", "noted": "2026-02-30", "source": None},                # not a real day
    {"text": "A note.", "source": None},                                       # undated
    {"text": "A note.", "noted": "2026-11-02", "source": 3},                   # source neither a string nor null
    {"text": "A note.", "noted": "2026-11-02", "source": "  "},                # a blank source says nothing
    {"text": "A note.", "noted": "2026-11-02", "source": None, "date": "1906"},  # unknown key
    {"text": "{readings_share} of it.", "noted": "2026-11-02", "source": None},  # a placeholder is never filled here
    "a note",
])
def test_a_malformed_film_note_is_refused(film, note):
    _edit(film, lambda p: p.update(film_notes=[note]))
    with pytest.raises(R.Refused, match=r"film-note \(film_notes\[0\]\)"):
        _plan(film, "film-notes-bad")


def test_film_notes_must_be_a_list(film):
    _edit(film, lambda p: p.update(film_notes={"text": "A note.", "noted": "2026-11-02"}))
    with pytest.raises(R.Refused, match=r"film-note \(film_notes\)"):
        _plan(film, "film-notes-notalist")
