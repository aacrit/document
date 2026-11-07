"""Founder ruling (7 November 2026): MIT is allowed for a sound or other non-picture input, credited the same way
as CC BY (description.py). A picture input under MIT is still refused. Prompted by the RWTH Aachen room impulse
response (AIR database, MIT), used in the title Foley mix: the v11 provenance ledger lists it in its ``sound``
section (D:/document-media/title-sequence/v11/provenance-v11.json); the holder's own licence file is
AIR_1_4/license.txt in the AIR 1.4 archive ("MIT License"). See docs/DECISIONS.md."""

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


def test_one_mit_pattern_is_shared():
    assert R.LICENCE_MIT is D.MIT
    assert TS.licence_rank("MIT") == 2 and D.names_mit("MIT") and not D.names_mit("MIT License")


# --------------------------------------------------------------------------
# The title's provenance (titles.py): picture items hold the house allowlist; sound items also allow MIT
# --------------------------------------------------------------------------

PICTURE_OK = {"id": "T-01", "title": "A clay tablet", "licence": "CC0", "ai": False,
              "source_page": "https://example.org/t01", "licence_evidence": "read 2026-10-16", "sha256": "0" * 64}
# Shaped like the real v11 entry: a holder, no creator, the .mat file the mix reads, the holder's licence file
AIR = {"id": "AIR-1.4-lecture", "holder": "Institute of Communication Systems and Data Processing (IND), RWTH Aachen University",
       "title": "Aachen Impulse Response database, lecture room (the house IR)",
       "file": "D:/document-media/house-room/AIR_1_4/air_binaural_lecture_1_1_2.mat", "sha256": "4" * 64,
       "source_page": "https://www.iks.rwth-aachen.de/en/research/tools-downloads/databases/aachen-impulse-response-database/",
       "licence": "MIT", "licence_evidence": "D:/document-media/house-room/AIR_1_4/license.txt (sha256 576e14bf...)",
       "ai": False, "used": "the Foley's room (the house IR, foley_fall)"}
# The studio's own theme stems in the same shared ledger: CC BY 4.0, composed here, no holder
THEME = {"id": "THEME-v11-RW", "title": "the Fall theme conformed notes-only to the RW title's events",
         "file": "D:\\document-media\\title-sequence\\theme-v11\\the-fall-theme-v11-RW.wav", "sha256": "d" * 64,
         "licence": "CC BY 4.0", "ai": False, "basis": "composed by the studio's music director",
         "source_page": "compose_v8.py"}
FOLEY = {"id": "FS382654", "title": "Paper Fluttering.wav", "uploader": "bbrocer", "licence": "CC0", "ai": False,
         "source_page": "https://freesound.org/s/382654/", "licence_evidence": "x.html", "sha256": "0" * 64}


def test_provenance_sound_items_reads_the_ledgers_sound_list():
    assert TS.provenance_sound_items(None) == []
    assert TS.provenance_sound_items({"items": [PICTURE_OK]}) == []
    assert TS.provenance_sound_items({"sound": [AIR]}) == [AIR]


def test_an_mit_sound_input_passes_provenance():
    assert TS._provenance_problems(AIR, kind="sound", play=None) == []
    assert TS._provenance_problems(dict(AIR, file=None, media="audio"), kind="sound", play=None) == []


def test_an_mit_image_filed_under_sound_is_refused():
    for f in ("D:/media/texture.png", "x.jpg", None):
        problems = TS._provenance_problems(dict(AIR, id="TEX", file=f), kind="sound", play=None)
        assert any("only for sound" in p for p in problems), (f, problems)
    assert TS._provenance_problems(dict(AIR, file="t.png", media="image"), kind="sound", play=None)


def test_an_mit_picture_input_is_refused():
    picture_mit = dict(PICTURE_OK, id="T-99", licence="MIT")
    problems = TS._provenance_problems(picture_mit, kind="picture", play=None)
    assert any("not allowed" in p for p in problems)


def test_mit_ranks_beside_cc_by_for_attribution():
    assert TS.licence_rank("MIT") == TS.licence_rank("CC BY 2.0") == 2
    assert TS.licence_rank("MIT") > TS.licence_rank("CC0")


def test_only_third_party_attribution_sound_is_credited_never_the_studios_own_themes():
    prov = {"sound": [FOLEY, AIR, THEME, dict(THEME, id="THEME-v11-NFA"), dict(THEME, id="THEME-v11-NV"),
                      dict(THEME, id="THEME-x", holder="void document studio")]}
    assert [x["id"] for x in TS.credited_sound_items(prov)] == ["AIR-1.4-lecture"]
    cc_by_other = dict(FOLEY, id="FS-BY", licence="CC BY 4.0")             # another holder's CC BY is credited
    assert [x["id"] for x in TS.credited_sound_items({"sound": [cc_by_other]})] == ["FS-BY"]


# --------------------------------------------------------------------------
# Credit: description.txt (A56) and the Sources page's credit list, from sources.json's title_sequence.sound
# --------------------------------------------------------------------------

FILM = {"slug": "fixture", "title": "Fixture film", "dates": "11 September 2001", "logline": "the day, as the record keeps it"}
EXPORTED = {"id": AIR["id"], "title": AIR["title"], "holder": AIR["holder"], "creator": None, "licence": "MIT",
            "source_page": AIR["source_page"], "credit": ""}
TITLE_SHOT = {"id": "TS1", "kind": "title_sequence", "ledger_id": "TS-v11", "mark": {"class": "DRAWN"},
              "title": "void document, series titles", "creator": "void document studio", "licence": "CC BY 4.0",
              "title_sequence": {"provenance": [], "sound": [EXPORTED]}}
SRC = {"title": "Fixture film", "slug": "fixture", "shots": [TITLE_SHOT]}
LINE = ("Aachen Impulse Response database, lecture room (the house IR). "
        "By Institute of Communication Systems and Data Processing (IND), RWTH Aachen University. MIT licence. " + AIR["source_page"])


def test_mit_carries_the_same_obligation_as_cc_by():
    assert D.obligated({"licence": "MIT", "creator": "A holder"})
    assert D.obligated(D.title_sound_items(TITLE_SHOT)[0])                  # by its holder, no creator
    assert not D.obligated({"licence": "CC0"})                               # unchanged: CC0 asks for nothing


def test_mit_has_no_4_0_style_exception_and_is_always_credited_in_full():
    assert D.tier(D.title_sound_items(TITLE_SHOT)[0]) == "full"


def test_the_credit_line_appears_in_the_description_and_names_the_holder_and_mit_licence():
    t = D.description_text(SRC, FILM)
    assert LINE in t.splitlines()
    # the same entries feed the Sources page's credit list (description.notes)
    assert any(e["line"] == LINE for e in D.notes(SRC)["source_entries"])


def test_studio_owned_mit_work_owes_no_attribution():
    title = {"ledger_id": "TS-v11", "licence": "MIT", "creator": "void document studio", "credit": "void document studio"}
    assert not D.obligated(title)
