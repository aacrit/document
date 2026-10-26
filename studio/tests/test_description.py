"""A56: the per-film description block is generated from sources.json (the data the picture no longer shows)."""
import json

from studio.engine import description as D

SRC = {
    "title": "Fixture film", "slug": "fixture",
    "narrator": {"credit": "Narrated by a computer voice", "engine": "orpheus", "voice": "tara", "pitch_shift_st": 0.76},
    "readings": [
        {"id": "L2", "speaker": "sp-a", "name": "Ari Fleischer", "reader": "kokoro:am_eric", "source": "Press briefing",
         "start_s": 20.3},
        {"id": "L3", "speaker": "sp-a", "name": "Ari Fleischer", "reader": "kokoro:am_eric", "source": "Press briefing",
         "start_s": 40.0},
        {"id": "A1", "speaker": "sp-floor", "name": "A voice on the NEADS floor", "mark": "ARCHIVE", "clip": "FX-TAPE",
         "source": "NEADS tape, channel 2", "reader": None, "start_s": 75.5},
    ],
    "unnamed_speakers": [{"speaker": "sp-floor", "name": "A voice on the NEADS floor", "basis": None,
                          "lines": [{"id": "A1", "start_s": 75.5}]}],
    "shots": [
        {"id": "S1", "ledger_id": "ST-1", "mark": {"class": "ARCHIVE"}, "title": "The tower, 2001", "archive": "Commons",
         "licence": "CC BY-SA 4.0", "credit": "Photo by Jane Roe, CC BY-SA 4.0", "item_url": "https://example.org/1"},
        {"id": "S2", "ledger_id": "ST-1", "mark": {"class": "ARCHIVE"}, "title": "The tower, 2001"},
        {"id": "S3", "ledger_id": "MAP-1", "mark": {"class": "DRAWN"}, "title": "Lower Manhattan", "licence": "CC-BY-4.0",
         "licence_note": "contains GeoNames data (CC BY 4.0); Natural Earth public domain",
         "source_line": "Data: Natural Earth; GeoNames", "notes": ["Streets after 2001 are not drawn."]},
        {"id": "S4", "mark": {"class": "CARD"}, "text": ["1  Morning"]},
    ],
    "gaps": [{"says": "The record holds no open-licence film of the fixture.", "searched": "Searched: Commons, NARA."}],
    "shortfalls": [{"what": "women", "statement": "Women's words are {women_share:pct} of the readings.",
                    "filled": "Women's words are 4.0% of the readings."},
                   {"what": "readings", "statement": "Readings are {readings_share:pct}."}],      # unfilled: never printed
}
FILM = {"slug": "fixture", "title": "Fixture film", "dates": "11 September 2001", "logline": "the day, as the record keeps it"}


def test_the_block_has_the_sections_in_order_from_the_sources_data():
    t = D.description_text(SRC, FILM)
    heads = ["Fixture film (11 September 2001)", "How to read the marks", "Voices", "Speakers not named on screen",
             "Sources", "Notes on the maps", "Gaps in the record", "Every shot, reading and licence:"]
    at = [t.index(h) for h in heads]
    assert at == sorted(at)
    assert "The day, as the record keeps it." in t
    assert "Narration: a computer voice, Orpheus 'tara', pitched +0.76 semitones." in t
    assert "Read by computer voices: Ari Fleischer (Kokoro 'am_eric')." in t           # once per reader
    assert "Original recordings: A voice on the NEADS floor, NEADS tape, channel 2." in t
    assert "A voice on the NEADS floor: A1 (1:16)" in t
    assert t.count("The tower, 2001") == 1 and "Attribution: Photo by Jane Roe, CC BY-SA 4.0" in t
    assert "Lower Manhattan: Streets after 2001 are not drawn." in t and "Lower Manhattan: Data: Natural Earth" in t
    assert "The record holds no open-licence film of the fixture. Searched: Commons, NARA." in t
    assert "Women's words are 4.0% of the readings." in t
    assert "{" not in t and "Readings are" not in t                                  # an unfilled statement is not printed
    assert "https://document.voidvision.org/f/fixture/sources/" in t and "/f/fixture/correct/" in t
    assert "<" not in t and "**" not in t                                             # plain text, no markup


def test_each_mark_class_has_one_line():
    t = D.description_text(SRC, FILM)
    for word in ("Amber dot, Archive:", "Bone dot, Reconstructed:", "Blue diamond, AI-generated:", "Blue square, Drawn:",
                 "Bone ring, void document:"):
        assert t.count(word) == 1


def test_a_film_with_nothing_to_disclose_prints_no_empty_sections():
    t = D.description_text({"title": "Bare", "slug": "bare", "shots": [], "readings": []})
    for h in ("Voices", "Speakers not named on screen", "Gaps in the record", "Notes on the maps", "\nSources\n"):
        assert h not in t


def test_the_block_stays_under_the_cap_and_cuts_the_sources_list_first():
    many = dict(SRC, shots=[{"id": f"S{i}", "ledger_id": f"ST-{i}", "mark": {"class": "ARCHIVE"},
                             "title": f"Still {i} " + "x" * 80, "archive": "Commons", "licence": "CC0"} for i in range(200)])
    t = D.description_text(many, FILM)
    assert len(t) <= D.MAX_CHARS
    assert "The full list is on the sources page." in t
    assert "Gaps in the record" in t and t.rstrip().endswith("/f/fixture/correct/")


def test_a_hostile_string_is_printed_as_plain_text():
    evil = '"><img src=x onerror=alert(1)>'
    src = dict(SRC, gaps=[{"says": "The record holds no " + evil + ".", "searched": "Searched: " + evil}])
    t = D.description_text(src, FILM)
    assert ("The record holds no " + evil + ".") in t                                # verbatim, never interpreted


def test_the_cli_writes_description_txt_beside_sources_json(tmp_path):
    (tmp_path / "sources.json").write_text(json.dumps(SRC), encoding="utf-8")
    reg = tmp_path / "films.json"
    reg.write_text(json.dumps({"films": [FILM]}), encoding="utf-8")
    assert D.main([str(tmp_path / "sources.json"), "--films", str(reg)]) == 0
    out = (tmp_path / "description.txt").read_text(encoding="utf-8")
    assert out.startswith("Fixture film (11 September 2001)\n")
