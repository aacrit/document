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
             "Sources", "Full sources, credits and licences for every shot:", "Notes on the maps",
             "Gaps in the record", "Correct something:"]
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
    assert "Full sources, credits and licences for every shot: https://document.voidvision.org/f/fixture/sources/" in t
    assert "Every shot, reading and licence:" not in t                                # the same url, once
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
# Before 4.0 a CC licence asks for the credit itself, so a pre-4.0 work is always credited in full here. Only a 4.0 work
# may be left to the sources page (CC BY 4.0 3(a)(2): a URI to a resource that holds the attribution).

LINK = "Full sources, credits and licences for every shot: https://document.voidvision.org/f/fixture/sources/"

GEONAMES_MAP = {
    "id": "6.14", "ledger_id": "D-EUR", "mark": {"class": "DRAWN", "detail": "from map data"},
    "title": "Western Europe, with Brussels (drawn map)",
    "archive": "void document studio", "creator": "void document studio", "licence": "CC-BY-4.0",
    "credit": "void document studio, drawn from Natural Earth; GeoNames (CC BY 4.0)",
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


def _photo(i, licence, title=None):
    return {"id": f"S{i}", "ledger_id": f"CB-{i}", "mark": {"class": "ARCHIVE"},
            "title": title or f"Licensed photograph {i} " + "y" * 90, "archive": "Wikimedia Commons",
            "creator": f"Photographer {i}", "licence": licence, "credit": None,
            "item_url": f"https://commons.wikimedia.org/wiki/File:P{i}.jpg"}


def _crowded(licence="CC BY 4.0", every=2):
    """Many CC BY photographs with long titles: the attributed entries alone overflow the cap."""
    src = _long_film()
    for i in range(0, 73, every):
        if i != 47:                                                             # the map stays where it is
            src["shots"][i] = _photo(i, licence)
    return src


def test_a_late_cc_by_map_keeps_its_full_attribution_under_the_cap():
    src = _long_film()
    assert len("\n".join(D.notes(src)["sources"])) > D.MAX_CHARS            # the fixture does overflow the cap
    t = D.description_text(src, FILM)
    assert len(t) <= D.MAX_CHARS
    block = t[t.index("\nSources\n"):t.index(LINK)]
    line = next(ln for ln in block.splitlines() if ln.startswith("Western Europe, with Brussels"))
    for must in ("CC-BY-4.0", "https://www.geonames.org/", "https://www.naturalearthdata.com/",
                 "https://creativecommons.org/licenses/by/4.0/", "contains GeoNames data"):
        assert must in line
    assert "Public domain still 72" not in t                                   # plain entries are what is dropped
    assert "Public domain still 0 " in t                                       # ... and still fill the room, in order
    assert block.index("Public domain still 0 ") < block.index("Western Europe")
    assert "D-EUR" not in t


def test_every_cc_by_photograph_keeps_its_author_licence_uri_and_link_in_a_short_form():
    src = _long_film()
    src["shots"][60] = _photo(60, "CC BY 2.0", "Both towers burning")
    src["shots"][65] = dict(_photo(65, "CC BY-SA 3.0", "Hoboken"), credit="Luigi Novi / Wikimedia Commons")
    t = D.description_text(src, FILM)
    a = next(ln for ln in t.splitlines() if ln.startswith("Both towers burning"))
    assert a == ("Both towers burning. By Photographer 60. CC BY 2.0 https://creativecommons.org/licenses/by/2.0/. "
                 "https://commons.wikimedia.org/wiki/File:P60.jpg")             # no "Wikimedia Commons." beside its link
    b = next(ln for ln in t.splitlines() if ln.startswith("Hoboken"))
    assert "Attribution: Luigi Novi / Wikimedia Commons" in b and "https://creativecommons.org/licenses/by-sa/3.0/" in b
    assert "By Photographer" not in b                                           # the credit is the attribution, once
    other = dict(_photo(1, "CC BY 2.0", "Elsewhere"), item_url="https://www.flickr.com/photos/x/1")
    assert ". Wikimedia Commons. " in D.notes(dict(src, shots=[other]))["sources"][0]   # kept where the link is not Commons


def test_cc0_and_public_domain_carry_no_obligation():
    assert not D.obligated({"licence": "CC0"}) and not D.obligated({"licence": "public domain"})
    assert D.obligated({"licence": "CC BY 2.0"}) and D.obligated({"licence": "CC-BY-SA-4.0"})
    assert D.obligated({"licence": "public domain", "data_sources": [{"id": "X", "url": "https://x.org/"}]})
    assert D.obligated({"licence": "Creative Commons Attribution-ShareAlike 3.0 Unported"})


def test_the_licence_ids_the_house_reads():
    assert D.licence_uri("CC-BY-SA-4.0") == "https://creativecommons.org/licenses/by-sa/4.0/"
    assert D.licence_uri("CC BY-NC-SA 2.0") == "https://creativecommons.org/licenses/by-nc-sa/2.0/"
    assert D.licence_uri("CC BY-ND 4.0") == "https://creativecommons.org/licenses/by-nd/4.0/"
    assert D.licence_uri("CC BY 3.0 US") == "https://creativecommons.org/licenses/by/3.0/us/"       # a ported licence
    assert D.licence_uri("CC BY-SA 2.5 ES") == "https://creativecommons.org/licenses/by-sa/2.5/es/"
    assert D.licence_uri("CC BY 4.0 US") is None                                 # 4.0 was never ported
    assert D.licence_uri("CC BY 3.0 IGO") == "https://creativecommons.org/licenses/by/3.0/igo/"
    assert D.licence_uri("CC BY-SA 3.0 IGO") == "https://creativecommons.org/licenses/by-sa/3.0/igo/"
    assert D.licence_uri("CC BY 4.0 IGO") is None and D.licence_uri("CC BY 2.0 IGO") is None   # IGO only at 3.0
    assert D.licence_uri("CC BY 9.9") is None and D.licence_uri("CC BY-XX 4.0") is None
    assert D.licence_uri("CC BY 2.0 by newandrew") == "https://creativecommons.org/licenses/by/2.0/"
    assert D.licence_uri("CC0") == "https://creativecommons.org/publicdomain/zero/1.0/"
    assert D.licence_uri("Creative Commons Attribution-ShareAlike 3.0 Unported") == \
        "https://creativecommons.org/licenses/by-sa/3.0/"
    assert D.licence_uri("Creative Commons Attribution 4.0 International") == \
        "https://creativecommons.org/licenses/by/4.0/"
    assert D.licence_uri("Creative Commons Attribution-NonCommercial-NoDerivs 2.0 Generic") == \
        "https://creativecommons.org/licenses/by-nc-nd/2.0/"
    assert D.CC_TABLE["versions"] == ["1.0", "2.0", "2.5", "3.0", "4.0"]       # the list the site reads too


def test_the_tier_of_each_credit():
    assert D.tier(_photo(1, "CC BY 2.0")) == "full" and D.tier(_photo(1, "CC BY-SA 3.0")) == "full"
    assert D.tier(_photo(1, "CC BY 4.0")) == "uri" and D.tier(GEONAMES_MAP) == "uri"
    assert D.tier(_photo(1, "CC BY")) == "full"                                 # no version read: credited in full
    assert D.tier(_photo(1, "CC BY 4.0 US")) == "full"                          # not a licence CC published
    assert D.tier(_photo(1, "public domain")) == "plain"
    pre = dict(GEONAMES_MAP, data_sources=[{"id": "OSM", "licence": "CC BY-SA 2.0", "url": "https://osm.org/"}])
    assert D.tier(pre) == "full"                                                # a map's data under 2.0
    osm = dict(GEONAMES_MAP, data_sources=[{"id": "OpenStreetMap", "licence": "ODbL 1.0", "url": "https://osm.org/"}])
    assert D.tier(osm) == "full"                                                # a licence not CC: credited in full
    unstated = dict(GEONAMES_MAP, data_sources=[{"id": "Survey", "url": "https://x.org/"}])
    assert D.tier(unstated) == "full"                                           # no licence stated: in full
    pd = dict(GEONAMES_MAP, licence="public domain", licence_note=None, source_line="Data: Natural Earth",
              data_sources=[{"id": "Natural Earth", "licence": "public domain", "url": "https://www.naturalearthdata.com/"},
                            {"id": "Census", "licence": "CC0", "url": "https://x.org/"}])
    assert D.tier(pd) == "uri"                                                  # public domain and CC0 data owe nothing


def test_the_map_note_is_printed_only_when_the_maps_own_entry_is_not():
    t = D.description_text(_long_film(), FILM)                                  # the map's full entry is printed
    assert t.count("https://www.geonames.org/") == 1
    assert "Notes on the maps\nWestern Europe" not in t



def test_a_4_0_maps_data_note_is_printed_when_its_entry_is_left_out_and_there_is_room(monkeypatch):
    """Under a cap where the map's entry does not fit but its shorter data note does, the note carries the URIs;
    under a tighter cap it gives way (a 4.0 credit the sources page carries), never a pre-4.0 entry."""
    src = _long_film()
    entry = next(ln for ln in D.notes(src)["sources"] if ln.startswith("Western Europe"))
    seen = {"note": False, "neither": False}
    for cap in range(2600, 4200, 5):
        monkeypatch.setattr(D, "MAX_CHARS", cap)
        r = D.compose(src, FILM)
        assert not r["omitted"]                                                 # no pre-4.0 work in this film
        if r["incomplete"]:                                                     # a cap even the floor does not fit: cut
            assert len(r["text"]) <= cap and r["trimmed"] and not r["external_publish_ready"]
            continue
        t = r["text"]
        assert len(t) <= cap
        lines = t.splitlines()
        if entry in lines:
            assert "Notes on the maps" not in t                                 # never both
            continue
        note = next((ln for ln in lines if ln.startswith("Western Europe, with Brussels (drawn map): Data:")), None)
        if note:
            assert "https://www.geonames.org/" in note and "https://creativecommons.org/licenses/by/4.0/" in note
            seen["note"] = True
        else:
            seen["neither"] = True
    assert seen == {"note": True, "neither": True}


def test_4_0_attributions_that_cannot_all_fit_point_to_the_sources_page_within_the_cap():
    t = D.description_text(_crowded(), FILM)
    assert len(t) <= D.MAX_CHARS
    assert LINK in t.splitlines()                                               # whole, on its own line
    kept = [ln for ln in t.splitlines() if ln.startswith("Licensed photograph ")]
    assert kept and kept[0].startswith("Licensed photograph 0 ")                # whole entries, in film order
    assert len(kept) < 36
    assert all("https://creativecommons.org/licenses/by/4.0/" in ln and "By Photographer" in ln for ln in kept)
    assert "Public domain still" not in t                                       # plain entries only after every 4.0 one
    sources = t[t.index("\nSources\n"):t.index(LINK)]
    assert sources.rstrip().splitlines()[-1] == kept[-1]


def test_every_pre_4_0_credit_is_printed_in_full_before_any_4_0_one():
    src = _crowded()                                                            # 36 CC BY 4.0 photographs
    for i in (5, 33, 71):
        src["shots"][i] = _photo(i, "CC BY-SA 2.0", f"Old licence photograph {i}")
    t = D.description_text(src, FILM)
    assert len(t) <= D.MAX_CHARS and LINK in t
    for i in (5, 33, 71):                                                       # late in the film, still printed whole
        line = next(ln for ln in t.splitlines() if ln.startswith(f"Old licence photograph {i}."))
        assert f"By Photographer {i}" in line and "https://creativecommons.org/licenses/by-sa/2.0/" in line
        assert f"https://commons.wikimedia.org/wiki/File:P{i}.jpg" in line
    lines = t.splitlines()
    assert lines.index(next(ln for ln in lines if ln.startswith("Old licence photograph 5."))) < \
        lines.index(next(ln for ln in lines if ln.startswith("Old licence photograph 71.")))  # printed in film order


def _partition_scale(n=120):
    """Not a Free Agent's shape: so many pre-4.0 CC works that their credits alone run to tens of thousands of
    characters (32,860 there), with a 4.0 map and public domain stills among them."""
    src = _long_film(n=n, at=47)
    for i in range(n):
        if i != 47 and i % 4:
            src["shots"][i] = _photo(i, "CC BY-SA 3.0" if i % 2 else "CC BY 2.0")
    return src


def test_pre_4_0_credits_that_cannot_fit_write_the_best_description_that_fits():
    src = _partition_scale()
    full = [e for e in D.notes(src)["source_entries"] if e["tier"] == "full"]
    assert sum(len(e["line"]) + 1 for e in full) > 3 * D.MAX_CHARS            # the overflow is real, not marginal
    r = D.compose(src, FILM)                                                    # never raises: no render is gated
    t = r["text"]
    assert len(t) <= D.MAX_CHARS
    lines = t.splitlines()
    page = "https://document.voidvision.org/f/fixture/sources/"
    assert lines[2] == D.INCOMPLETE.format(url=page)                            # the header, after the title and logline
    assert "incomplete" in lines[2] and "Full credits and notes for every shot" in lines[2] and "\u2014" not in lines[2]
    assert LINK in lines                                                        # room kept for the sources-page line
    kept = [e for e in full if e["line"] in lines]
    assert kept and r["omitted"] and len(kept) + len(r["omitted"]) == len(full)  # every pre-4.0 credit kept or listed
    assert [e["line"] for e in kept] == [ln for ln in lines if ln.startswith("Licensed photograph ")]   # film order
    for e in kept:                                                              # what is printed is printed whole
        assert "By Photographer" in e["line"] and "https://creativecommons.org/licenses/" in e["line"]
    assert r["trimmed"].get("gaps") == 2                                       # the gaps gave their room first
    assert r["external_publish_ready"] is False
    assert r["problems"] and all(e["name"] in r["problems"][0] for e in r["omitted"]) and "before 4.0" in r["problems"][0]
    assert D.release_problem(src, FILM) is None                                 # the site release is never refused for it
    assert D.external_problems(src, FILM) == r["problems"]


def test_a_film_that_fits_has_no_header_and_is_ready_for_external_publication():
    for src in (SRC, _long_film(), _crowded()):                                 # Real World's shape, and 4.0 overflow
        r = D.compose(src, FILM)
        assert r["external_publish_ready"] is True and not r["omitted"] and not r["problems"]
        assert "This description is incomplete" not in r["text"]
    every_pre_4 = _crowded()
    for i in (5, 33, 71):
        every_pre_4["shots"][i] = _photo(i, "CC BY-SA 2.0", f"Old licence photograph {i}")
    assert D.compose(every_pre_4, FILM)["external_publish_ready"] is True       # every pre-4.0 credit fits


def test_the_sources_page_link_uses_the_slug_from_films_json():
    src = dict(_crowded(), slug="fixture-render")
    t = D.description_text(src, dict(FILM, slug="the-listed-film"))
    assert "every shot: https://document.voidvision.org/f/the-listed-film/sources/" in t
    assert "/f/fixture-render/" not in t


def test_a_film_not_in_films_json_is_written_with_its_own_slug_and_refused_at_release():
    src = _crowded()
    t = D.description_text(src, None)                                           # degrade, never block the render
    assert "every shot: https://document.voidvision.org/f/fixture/sources/" in t and len(t) <= D.MAX_CHARS
    why = D.release_problem(src, None)
    assert why and "not in films.json" in why and "CB-" in why
    assert D.release_problem(src, FILM) is None                                 # listed: the page is served
    assert D.release_problem(SRC, None) is None                                 # nothing left to the page


def test_the_studios_own_cc_by_works_owe_no_attribution():
    title = {"ledger_id": "TS-v5c", "licence": "CC BY 4.0", "creator": "void document studio",
             "credit": "void document studio", "archive": "void document studio"}
    assert not D.obligated(title)
    assert not D.obligated(dict(title, credit=None))
    assert D.obligated(dict(title, data_sources=[{"id": "GeoNames", "url": "https://www.geonames.org/"}]))
    assert D.obligated({"licence": "CC BY 4.0", "creator": "Jane Roe", "archive": "Wikimedia Commons"})


def test_the_reviewers_probes_are_not_the_studios_own():
    title = {"licence": "CC BY 4.0", "creator": "void document studio", "credit": "void document studio",
             "archive": "void document studio"}
    # 1. our creator, but the credit names another party
    assert D.obligated(dict(title, credit="void document studio, after a photograph by Jane Roe (CC BY 2.0)"))
    # 2. only the archive is ours: the creator is someone else (or not stated)
    assert D.obligated(dict(title, creator="Jane Roe", credit=None))
    assert D.obligated(dict(title, creator=None, credit="void document studio"))
    # 1b. a creator that starts with ours and names someone else (round 2 of the review)
    assert D.obligated(dict(title, creator="void document studio; Jane Doe", credit=None))
    assert D.obligated(dict(title, creator="void document studio after a photo by Jane Doe", credit=None))
    assert not D.obligated(dict(title, creator="void document", credit="void document studio."))
    # 3. a map of ours whose data is CC BY, stated only in its source line or licence note
    drawn = dict(title, mark={"class": "DRAWN", "detail": "from map data"}, licence="public domain")
    assert D.obligated(dict(drawn, source_line="Data: GeoNames (CC BY 4.0)"))
    assert D.obligated(dict(drawn, licence_note="contains GeoNames data (CC BY 4.0)"))
    assert not D.obligated(drawn)


def test_the_cli_writes_an_unlisted_film_with_its_own_slug(tmp_path):
    (tmp_path / "sources.json").write_text(json.dumps(_crowded()), encoding="utf-8")
    assert D.main([str(tmp_path / "sources.json"), "--films", str(tmp_path / "none.json")]) == 0
    assert "/f/fixture/sources/" in (tmp_path / "description.txt").read_text(encoding="utf-8")
    side = json.loads((tmp_path / D.SIDECAR).read_text(encoding="utf-8"))
    assert side["external_publish_ready"] is False and not side["listed"]       # its credits lean on an unserved page
    assert side["left_to_sources_page"] and not side["omitted"]


def _write(tmp_path, src):
    (tmp_path / "sources.json").write_text(json.dumps(src), encoding="utf-8")
    reg = tmp_path / "films.json"
    reg.write_text(json.dumps({"films": [FILM]}), encoding="utf-8")
    return tmp_path / "sources.json", reg


def test_a_pre_4_0_overflow_is_written_with_its_sidecar_and_check_external_refuses_it(tmp_path, capsys):
    sources, reg = _write(tmp_path, _partition_scale())
    assert D.main([str(sources), "--films", str(reg)]) == 0                     # written, never refused
    text = (tmp_path / "description.txt").read_text(encoding="utf-8")
    assert len(text.rstrip("\n")) <= D.MAX_CHARS and "This description is incomplete" in text
    side = json.loads((tmp_path / D.SIDECAR).read_text(encoding="utf-8"))
    assert side["external_publish_ready"] is False and side["listed"] is True
    assert side["chars"] == len(text.rstrip("\n")) and side["max_chars"] == D.MAX_CHARS
    assert side["omitted"] and all(o["tier"] == "full" and o["ledger_id"].startswith("CB-") for o in side["omitted"])
    assert all(o["line"] not in text for o in side["omitted"])                  # the sidecar lists what is not printed
    capsys.readouterr()
    assert D.main(["--check-external", str(sources), "--films", str(reg)]) == 1
    err = capsys.readouterr().err
    assert "outside platform: not ready (advisory" in err and "A56" in err
    for o in side["omitted"]:                                                   # names every omitted pre-4.0 entry
        assert o["name"] in err


def test_check_external_passes_a_film_that_fits_and_its_sidecar_says_ready(tmp_path, capsys):
    sources, reg = _write(tmp_path, _long_film())                               # Real World's shape: it fits
    assert D.main([str(sources), "--films", str(reg)]) == 0
    side = json.loads((tmp_path / D.SIDECAR).read_text(encoding="utf-8"))
    assert side["external_publish_ready"] is True and side["omitted"] == [] and side["problems"] == []
    assert D.main(["--check-external", str(sources), "--films", str(reg)]) == 0
    assert "outside platform: ready" in capsys.readouterr().out
    assert D.main(["--check-external", str(sources), "--films", str(tmp_path / "none.json")]) == 0   # nothing left out


# ---- over the cap for any reason: the header, then the trailing sections cut; the fixed lines always stay ------------

CORRECT = "Correct something: https://document.voidvision.org/f/fixture/correct/"


def _fixed_lines_kept(t):
    lines = t.splitlines()
    assert len(t) <= D.MAX_CHARS
    assert lines[2] == D.INCOMPLETE.format(url="https://document.voidvision.org/f/fixture/sources/")
    assert LINK in lines and lines[-1] == CORRECT
    return lines


def test_an_overflow_from_map_notes_is_cut_to_fit_with_the_header():
    src = dict(SRC, shots=SRC["shots"] + [
        {"id": "M1", "ledger_id": "MAP-N", "mark": {"class": "DRAWN"}, "title": "Map",
         "licence": "public domain", "notes": [f"Note {i} on this map, a sentence of some length to fill the cap."
                                               for i in range(200)]}])
    r = D.compose(src, FILM)
    lines = _fixed_lines_kept(r["text"])
    assert r["incomplete"] and r["trimmed"].get("map_notes") and not r["omitted"]
    assert r["trimmed"].get("gaps") == 2                                        # the gaps go first, then the notes
    assert "Gaps in the record" not in lines and "Map: Note 0 on this map" in r["text"]   # cut from the end
    assert r["external_publish_ready"] is False and "map note(s)" in r["problems"][0]


def test_an_overflow_from_voices_never_exceeds_the_cap_and_keeps_the_fixed_lines():
    src = dict(SRC, readings=[{"id": f"L{i}", "speaker": f"sp-{i}", "name": f"Speaker with a long name {i}",
                               "reader": f"kokoro:voice_{i}", "source": "x", "start_s": i} for i in range(400)],
               unnamed_speakers=[{"name": f"A voice {i}", "lines": [{"id": f"U{i}", "start_s": i}]} for i in range(200)])
    r = D.compose(src, FILM)
    lines = _fixed_lines_kept(r["text"])
    assert r["trimmed"].get("unnamed") or r["trimmed"].get("voices")
    assert not r["external_publish_ready"]


def test_a_title_longer_than_the_cap_is_itself_cut_and_the_fixed_lines_stay():
    r = D.compose(SRC, dict(FILM, title="T" * 6000))
    assert len(r["text"]) <= D.MAX_CHARS and r["incomplete"]
    lines = r["text"].splitlines()
    assert LINK in lines and lines[-1] == CORRECT and D.INCOMPLETE.split(":")[0] in r["text"]


def test_the_unserved_page_is_a_structured_flag():
    assert D.compose(_crowded(), None)["unserved_page"] is True
    assert D.compose(_crowded(), FILM)["unserved_page"] is False
    assert D.compose(SRC, None)["unserved_page"] is False                       # nothing left to the page
    assert D.release_problem(_partition_scale(), FILM) is None                  # the cap is never a release reason


def test_a_string_notes_in_sources_json_is_never_printed_letter_by_letter():
    src = dict(SRC, shots=[dict(SRC["shots"][0], notes="Crop above the caption bar.")])
    n = D.notes(src)
    assert n["map_notes"] == [] and "Crop above" not in D.description_text(src, FILM)


def _probe(n_pre, n_gaps, title=None, gap_len=200):
    """The reviewer's probes: a pre-4.0 overflow and a long gaps list together."""
    src = dict(SRC, shortfalls=[], shots=[_photo(i, "CC BY 2.0", title(i) if title else None) for i in range(n_pre)],
               gaps=[{"says": f"Gap {i}: " + "g" * gap_len, "searched": "Searched: Commons."} for i in range(n_gaps)])
    return src


def test_the_cut_order_is_honoured_60_pre_4_0_credits_and_30_gaps():
    src = _probe(60, 30)
    r = D.compose(src, FILM)
    alone = D.compose(dict(src, gaps=[]), FILM)                               # the same film with no gaps at all
    assert len(r["text"]) <= D.MAX_CHARS and r["incomplete"] and r["omitted"]
    assert len(r["omitted"]) == len(alone["omitted"])                          # the gaps took no credit's room
    assert r["trimmed"]["gaps"] == 30 and "Gaps in the record" not in r["text"]   # cut first, wholly


def test_the_cut_order_is_honoured_15_pre_4_0_credits_and_3_gaps():
    src = _probe(15, 3, title=lambda i: f"Photograph {i}", gap_len=1500)
    r = D.compose(src, FILM)
    assert len(r["text"]) <= D.MAX_CHARS and r["incomplete"]
    assert r["omitted"] == []                                                  # every credit kept: the gaps gave way
    assert all(f"Photograph {i}." in r["text"] for i in range(15))
    assert 0 < r["trimmed"]["gaps"] <= 3 and "Gap 0: " in r["text"]           # cut from the end, the first kept
    assert "map note(s)" not in r["problems"][0] and "gap line(s)" in r["problems"][0]
