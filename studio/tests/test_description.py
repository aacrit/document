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


# ---- attribution survives the cap (CC BY: title, author, source, licence; the licence by its URI) ---------------------

GEONAMES_MAP = {
    "id": "6.14", "ledger_id": "D-EUR", "mark": {"class": "DRAWN"}, "title": "Western Europe, with Brussels (drawn map)",
    "archive": "void document studio", "creator": "void document studio", "licence": "CC-BY-4.0",
    "licence_note": "contains GeoNames data (CC BY 4.0); Natural Earth public domain",
    "source_line": "Data: Natural Earth; GeoNames (CC BY 4.0)",
    "data_sources": [{"id": "Natural Earth", "licence": "public domain", "url": "https://www.naturalearthdata.com/"},
                     {"id": "GeoNames (CC BY 4.0)", "licence": "CC BY 4.0", "url": "https://www.geonames.org/"}]}


def _long_film(n=73, at=47, voices=40):
    """Real World's shape: a long voices list, and n sources with the CC BY map late among them."""
    shots = [{"id": f"S{i}", "ledger_id": f"ST-{i}", "mark": {"class": "ARCHIVE"},
              "title": f"Public domain still {i} " + "x" * 60, "archive": "National Archives", "licence": "public domain",
              "item_url": f"https://catalog.archives.gov/id/{i}"} for i in range(n)]
    shots[at] = GEONAMES_MAP
    readings = [{"id": f"A{i}", "name": f"Recorded speaker number {i}", "mark": "ARCHIVE", "clip": f"RLR-{i:03d}",
                 "source": f"RLR-{i:03d}", "start_s": i} for i in range(voices)]
    return dict(SRC, shots=shots, readings=readings, unnamed_speakers=[])


def test_a_late_cc_by_map_keeps_its_full_attribution_under_the_cap():
    src = _long_film()
    assert len("\n".join(D.notes(src)["sources"])) > D.MAX_CHARS            # the fixture does overflow the cap
    t = D.description_text(src, FILM)
    assert len(t) <= D.MAX_CHARS
    assert "The full list is on the sources page." in t
    block = t[t.index("\nSources\n"):t.index("The full list is on the sources page.")]
    line = next(ln for ln in block.splitlines() if ln.startswith("Western Europe, with Brussels"))
    for must in ("CC-BY-4.0", "https://www.geonames.org/", "https://www.naturalearthdata.com/",
                 "https://creativecommons.org/licenses/by/4.0/", "contains GeoNames data"):
        assert must in line
    assert "Public domain still 72" not in t                                   # plain entries are what is dropped
    assert "Public domain still 0 " in t                                       # ... and still fill the room, in order
    assert block.index("Public domain still 0 ") < block.index("Western Europe")
    assert "D-EUR" not in t


def test_every_cc_by_photograph_keeps_its_author_licence_uri_and_link():
    src = _long_film()
    src["shots"][60] = {"id": "S60", "ledger_id": "CB-1", "mark": {"class": "ARCHIVE"}, "title": "Both towers burning",
                        "archive": "Wikimedia Commons", "creator": "newandrew (Flickr)", "licence": "CC BY 2.0",
                        "item_url": "https://commons.wikimedia.org/wiki/File:From_brooklyn.jpg"}
    src["shots"][65] = {"id": "S65", "ledger_id": "CB-2", "mark": {"class": "ARCHIVE"}, "title": "Hoboken",
                        "archive": "Wikimedia Commons", "creator": "Luigi Novi", "licence": "CC BY-SA 3.0",
                        "credit": "Luigi Novi / Wikimedia Commons", "item_url": "https://commons.wikimedia.org/wiki/File:H.jpg"}
    t = D.description_text(src, FILM)
    a = next(ln for ln in t.splitlines() if ln.startswith("Both towers burning"))
    assert "By newandrew (Flickr)" in a and "https://creativecommons.org/licenses/by/2.0/" in a
    assert "https://commons.wikimedia.org/wiki/File:From_brooklyn.jpg" in a
    b = next(ln for ln in t.splitlines() if ln.startswith("Hoboken"))
    assert "Attribution: Luigi Novi / Wikimedia Commons" in b and "https://creativecommons.org/licenses/by-sa/3.0/" in b
    assert "By Luigi Novi" not in b                                             # the credit is the attribution, once


def test_cc0_and_public_domain_carry_no_obligation():
    assert not D.obligated({"licence": "CC0"}) and not D.obligated({"licence": "public domain"})
    assert D.obligated({"licence": "CC BY 2.0"}) and D.obligated({"licence": "CC-BY-SA-4.0"})
    assert D.obligated({"licence": "public domain", "data_sources": [{"id": "X", "url": "https://x.org/"}]})
    assert D.licence_uri("CC-BY-SA-4.0") == "https://creativecommons.org/licenses/by-sa/4.0/"


def _crowded(src=None):
    """Half the film CC BY photographs with long titles: the attributed entries alone overflow the cap."""
    src = src or _long_film()
    for i in range(0, 73, 2):
        if i == 47:
            continue                                                            # the map stays where it is
        src["shots"][i] = {"id": f"S{i}", "ledger_id": f"CB-{i}", "mark": {"class": "ARCHIVE"},
                           "title": f"Licensed photograph {i} " + "y" * 90, "archive": "Wikimedia Commons",
                           "creator": f"Photographer {i}", "licence": "CC BY 2.0", "item_url": f"https://c.org/{i}"}
    return src


def test_the_map_note_is_printed_only_when_the_maps_own_entry_is_not():
    t = D.description_text(_long_film(), FILM)                                  # the map's full entry is printed
    assert t.count("https://www.geonames.org/") == 1
    assert "Notes on the maps\nWestern Europe" not in t
    t = D.description_text(_crowded(), FILM)                                    # the map's entry does not fit
    assert not any(ln.startswith("Western Europe, with Brussels (drawn map). ") for ln in t.splitlines())
    notes = t[t.index("Notes on the maps"):]
    line = next(ln for ln in notes.splitlines() if ln.startswith("Western Europe"))
    assert "https://www.geonames.org/" in line and "https://creativecommons.org/licenses/by/4.0/" in line


def test_attributions_that_cannot_all_fit_point_to_the_sources_page_within_the_cap():
    t = D.description_text(_crowded(), FILM)
    assert len(t) <= D.MAX_CHARS
    link = "Full sources, credits and licences for every shot: https://document.voidvision.org/f/fixture/sources/"
    assert link in t.splitlines()                                               # whole, on its own line
    assert "The full list is on the sources page." not in t
    kept = [ln for ln in t.splitlines() if ln.startswith("Licensed photograph ")]
    assert kept and kept[0].startswith("Licensed photograph 0 ")                # whole entries, in film order
    assert all("https://creativecommons.org/licenses/by/2.0/" in ln and "By Photographer" in ln for ln in kept)
    assert "Public domain still" not in t                                       # plain entries go first
    sources = t[t.index("\nSources\n"):t.index(link)]
    assert sources.rstrip().splitlines()[-1] == kept[-1]


def test_the_sources_page_link_uses_the_slug_from_films_json():
    src = dict(_crowded(), slug="fixture-render")
    t = D.description_text(src, dict(FILM, slug="the-listed-film"))
    assert "every shot: https://document.voidvision.org/f/the-listed-film/sources/" in t


def test_with_no_slug_in_films_json_an_overflow_is_a_hard_error_naming_them():
    try:
        D.description_text(_crowded(), None)
    except D.AttributionOverflow as e:
        msg = str(e)
    else:
        raise AssertionError("an attribution was dropped with no sources page to point to")
    assert "CB-0" in msg and "Licensed photograph 0" in msg and str(D.MAX_CHARS) in msg and "films.json" in msg


def test_when_even_the_sources_page_line_cannot_fit_it_is_a_hard_error():
    src = dict(_crowded(), gaps=[{"says": "z" * 6000}])
    try:
        D.description_text(src, FILM)
    except D.AttributionOverflow as e:
        assert "sources-page line" in str(e)
    else:
        raise AssertionError("the sources-page line was cut")


def test_the_studios_own_cc_by_works_owe_no_attribution():
    title = {"ledger_id": "TS-v5c", "licence": "CC BY 4.0", "creator": "void document studio",
             "credit": "void document studio", "archive": "void document studio"}
    assert not D.obligated(title)
    assert not D.obligated(dict(title, creator=None, archive=None))             # by its credit alone
    assert D.obligated(dict(title, data_sources=[{"id": "GeoNames", "url": "https://www.geonames.org/"}]))
    assert D.obligated({"licence": "CC BY 4.0", "creator": "Jane Roe", "archive": "Wikimedia Commons"})
    assert D.obligated({"licence": "CC BY 4.0", "creator": "Someone citing void document", "archive": "Commons"})


def test_the_cli_refuses_rather_than_write_a_short_attribution_for_an_unlisted_film(tmp_path):
    src = _long_film()
    for i in range(0, 73, 2):
        src["shots"][i] = {"id": f"S{i}", "ledger_id": f"CB-{i}", "mark": {"class": "ARCHIVE"}, "title": "y" * 120,
                           "archive": "Wikimedia Commons", "licence": "CC BY 2.0", "item_url": f"https://c.org/{i}"}
    (tmp_path / "sources.json").write_text(json.dumps(src), encoding="utf-8")
    try:
        D.main([str(tmp_path / "sources.json"), "--films", str(tmp_path / "none.json")])
    except D.AttributionOverflow:
        pass
    else:
        raise AssertionError("the CLI wrote a description that drops attributions")
    assert not (tmp_path / "description.txt").exists()
