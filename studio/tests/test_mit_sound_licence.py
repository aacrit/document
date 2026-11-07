"""Founder ruling (7 November 2026): MIT is allowed for a sound or other non-picture input, credited the same way
as CC BY (description.py). A picture input under MIT is still refused. Prompted by the RWTH Aachen room impulse
response (AIR database, MIT), used in the title Foley mix: the v11 provenance ledger lists it in its ``sound``
section (D:/document-media/title-sequence/v11/provenance-v11.json), flagged "MIT is outside the engine's media
licence allowlist" until this ruling. See docs/DECISIONS.md."""

from __future__ import annotations

from studio.engine import description as D
from studio.engine import render as R
from studio.engine import titles as TS

# --------------------------------------------------------------------------
# The house allowlist (render.licence_allowed): MIT for sound/non-picture only
# --------------------------------------------------------------------------


def test_mit_is_allowed_only_for_a_sound_or_non_picture_input():
    assert R.licence_allowed("MIT", kind="sound") == (True, False)
    assert R.licence_allowed("MIT", kind="non_picture") == (True, False)
    assert R.licence_allowed("mit", kind="sound") == (True, False)           # case-insensitive, like the rest


def test_a_picture_input_under_mit_is_still_refused():
    assert R.licence_allowed("MIT") == (False, False)                       # kind defaults to "picture"
    assert R.licence_allowed("MIT", kind="picture") == (False, False)
    assert R.licence_allowed("MIT", {"share_alike": {"decision": "docs/DECISIONS.md x"}}) == (False, False)


def test_the_house_allowlist_is_otherwise_unchanged():
    for lic in ("public domain", "CC0", "CC BY 2.0", "CC BY 4.0"):
        assert R.licence_allowed(lic, kind="sound") == (True, False)
        assert R.licence_allowed(lic) == (True, False)
    for lic in ("MIT License", "Expat", "all rights reserved", ""):
        assert R.licence_allowed(lic, kind="sound")[0] is False             # only the bare "MIT" id is read


# --------------------------------------------------------------------------
# The title's provenance (titles.py): picture items hold the house allowlist; sound items also allow MIT
# --------------------------------------------------------------------------

PICTURE_OK = {"id": "T-01", "title": "A clay tablet", "licence": "CC0", "ai": False,
              "source_page": "https://example.org/t01", "licence_evidence": "read 2026-10-16", "sha256": "0" * 64}
SOUND_MIT_OK = {"id": "AIR-1.4-lecture", "title": "Aachen Impulse Response database, lecture room", "licence": "MIT",
                "ai": False, "source_page": "https://www.iks.rwth-aachen.de/air", "licence_evidence": "the house's credit",
                "sha256": "4" * 64}


def test_provenance_sound_items_reads_the_ledgers_sound_list():
    assert TS.provenance_sound_items(None) == []
    assert TS.provenance_sound_items({"items": [PICTURE_OK]}) == []
    assert TS.provenance_sound_items({"sound": [SOUND_MIT_OK]}) == [SOUND_MIT_OK]


def test_an_mit_sound_input_passes_provenance():
    assert TS._provenance_problems(SOUND_MIT_OK, kind="sound", play=None) == []


def test_an_mit_picture_input_is_refused():
    picture_mit = dict(PICTURE_OK, id="T-99", licence="MIT")
    problems = TS._provenance_problems(picture_mit, kind="picture", play=None)
    assert any("not allowed" in p for p in problems)


def test_mit_ranks_beside_cc_by_for_attribution():
    assert TS.licence_rank("MIT") == TS.licence_rank("CC BY 2.0") == 2
    assert TS.licence_rank("MIT") > TS.licence_rank("CC0")


# --------------------------------------------------------------------------
# Credit: description.txt (A56) and the Sources page's credit list (description.compose/description_text)
# --------------------------------------------------------------------------

FILM = {"slug": "fixture", "title": "Fixture film", "dates": "11 September 2001", "logline": "the day, as the record keeps it"}
AIR_SHOT = {
    "id": "S-AIR", "ledger_id": "AIR-1.4-lecture", "mark": {"class": "ARCHIVE"},
    "title": "Aachen Impulse Response Database, lecture room (the house IR)",
    "creator": "RWTH Aachen, Institute of Communication Systems", "licence": "MIT",
    "item_url": "https://www.iks.rwth-aachen.de/air",
}
SRC = {"title": "Fixture film", "slug": "fixture", "shots": [AIR_SHOT]}


def test_mit_carries_the_same_obligation_as_cc_by():
    assert D.obligated({"licence": "MIT", "creator": "A holder"})
    assert not D.obligated({"licence": "CC0"})                               # unchanged: CC0 asks for nothing


def test_mit_has_no_4_0_style_exception_and_is_always_credited_in_full():
    assert D.tier(AIR_SHOT) == "full"


def test_the_credit_line_appears_in_the_description_and_names_the_holder_and_mit_licence():
    t = D.description_text(SRC, FILM)
    line = next(ln for ln in t.splitlines() if ln.startswith("Aachen Impulse Response Database"))
    assert line == ("Aachen Impulse Response Database, lecture room (the house IR). "
                     "By RWTH Aachen, Institute of Communication Systems. MIT licence. "
                     "https://www.iks.rwth-aachen.de/air")
    # the same entries feed the Sources page's credit list (description.notes)
    assert any(e["line"] == line for e in D.notes(SRC)["source_entries"])


def test_studio_owned_mit_work_owes_no_attribution():
    title = {"ledger_id": "TS-v11", "licence": "MIT", "creator": "void document studio", "credit": "void document studio"}
    assert not D.obligated(title)
