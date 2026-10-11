"""E8: count cards and the per-country, per-year data layer (studio/engine/counts.py
and the data layer in maps.py). Every number on a frame is a cited cell; a mismatch,
an unmatched country, a year outside the data or an interpolated value is refused."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from studio.engine import counts, maps

SRC = "Fixture table (CC BY 4.0)"
TXT = "Fixture history (public domain)"
CSV_TEXT = ("entity,code,year,cases\n"
            "Alpha,AAA,1970,1500\n"
            "Alpha,AAA,1971,0\n"
            "Beta,BBB,1970,0\n"
            "Beta,BBB,1971,0\n"
            "World,OWID_WRL,1970,1500\n"
            "World,OWID_WRL,1971,0\n"
            "Somewhere Region,,1970,1500\n")
HISTORY = "Front matter.\nIn May 1972, 7 cases were found in Gamma.\nThe end.\n"


def square(x0, y0, x1, y1):
    return {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


def country(adm, iso, box):
    return {"type": "Feature", "geometry": square(*box),
            "properties": {"ADM0_A3": adm, "ISO_A3": iso, "ISO_A3_EH": iso, "NAME": adm.title(),
                           "LABEL_X": (box[0] + box[2]) / 2, "LABEL_Y": (box[1] + box[3]) / 2}}


COUNTRIES = {"type": "FeatureCollection", "features": [
    country("AAA", "AAA", (10, 10, 12, 12)), country("BBB", "BBB", (12, 10, 14, 12)),
    country("CCC", "CCC", (10, 12, 12, 14)), country("TTT", "-99", (12, 12, 14, 14))]}


@pytest.fixture(scope="module")
def root(tmp_path_factory) -> Path:
    """R-08: the fixture's data and geodata are written at test time, never tracked."""
    r = tmp_path_factory.mktemp("counts")
    (r / "data").mkdir()
    (r / "data" / "table.csv").write_text(CSV_TEXT, encoding="utf-8", newline="")
    (r / "data" / "history.txt").write_text(HISTORY, encoding="utf-8")
    (r / "naturalearth").mkdir()
    (r / "naturalearth" / "ne_10m_admin_0_countries.geojson").write_text(json.dumps(COUNTRIES), encoding="utf-8")
    (r / "land.geojson").write_text(json.dumps(COUNTRIES), encoding="utf-8")
    return r


def sha(root, rel):
    return hashlib.sha256((root / rel).read_bytes()).hexdigest()


def cell(root, entity, year, **kw):
    return {"csv": "data/table.csv", "sha256": sha(root, "data/table.csv"), "licence": "CC BY 4.0", "source": SRC,
            "column": "cases", "row": {"entity": entity, "year": str(year)}, **kw}


def card(root, **kw):
    c = {"id": "C1", "kind": "count_card", "year": "1970", "numeral": "1,500", "caption": "cases reported, world",
         "cite": cell(root, "World", 1970, line=6), "source_short": "Fixture table",
         "sources": [{"id": SRC, "licence": "CC BY 4.0"}]}
    c.update(kw)
    return c


def data_layer(root, year=1970, **kw):
    d = {"csv": "data/table.csv", "sha256": sha(root, "data/table.csv"), "licence": "CC BY 4.0", "source": SRC,
         "columns": {"entity": "entity", "code": "code", "year": "year", "value": "cases"}, "year": year,
         "not_countries": {"World": {"aggregate": True, "why": "the total"},
                           "Somewhere Region": {"aggregate": True, "why": "a region"}}}
    d.update(kw)
    return d


def world_map(root, year=1970, **kw):
    s = {"id": "M1", "title": f"Fixture countries, {year}", "source_short": "Fixture table",
         "extent": [9.5, 9.5, 14.5, 14.5], "unplaced": [],
         "sources": [{"id": "Natural Earth", "licence": "public domain"}, {"id": SRC, "licence": "CC BY 4.0"}],
         "layers": [{"file": "land.geojson", "style": "land"}, {"file": "land.geojson", "style": "coast"}],
         "data": data_layer(root, year),
         "legend": [{"style": "cases", "text": "Cases reported"}, {"style": "zero", "text": "No cases reported"},
                    {"style": "nodata", "text": "No figure"}]}
    s.update(kw)
    return s


# ---------------------------------------------------------------- the CSV lint

def test_a_count_card_whose_numeral_is_its_cited_cell_renders_at_1080p_twice_the_same(root):
    img, info = maps.render_map(card(root), root, data_root=root)
    assert img.size == (1920, 1080) and img.mode == "RGB"
    again, _ = maps.render_map(card(root), root, data_root=root)
    assert hashlib.sha256(maps.png_bytes(img)).hexdigest() == hashlib.sha256(maps.png_bytes(again)).hexdigest()
    assert info["cites"]["numeral"]["line"] == 6 and info["cites"]["numeral"]["value"] == 1500
    nb = [b for b in info["boxes"] if b["kind"] == "numeral"][0]["box"]
    region = np.asarray(img)[int(nb[1]):int(nb[3]), int(nb[0]):int(nb[2])].astype(int)
    assert region.max() - region.min() > 150, "the numeral is on the frame"
    assert info["source_line"] == f"Data: {SRC}"


@pytest.mark.parametrize("numeral", ["1,501", "1500", "15,00", "0"])
def test_a_count_card_whose_numeral_differs_from_its_cell_is_refused(root, numeral):
    with pytest.raises(maps.MapRefused):
        counts.check_card(card(root, numeral=numeral), root)


def test_a_citation_whose_sha256_or_line_is_wrong_is_refused(root):
    with pytest.raises(maps.MapRefused, match="sha256"):
        counts.check_card(card(root, cite=cell(root, "World", 1970, sha256="0" * 64)), root)
    with pytest.raises(maps.MapRefused, match="line 6"):
        counts.check_card(card(root, cite=cell(root, "World", 1970, line=7)), root)


def test_a_card_for_a_year_outside_the_data_is_refused(root):
    c = card(root, year="1972", numeral="0", cite=cell(root, "World", 1972))
    with pytest.raises(maps.MapRefused, match="no row.*runs 1970 to 1971"):
        counts.check_card(c, root)


def test_a_year_outside_the_data_passes_only_when_another_source_is_cited_the_same_way(root):
    q = {"text": "data/history.txt", "sha256": sha(root, "data/history.txt"), "licence": "public domain",
         "source": TXT, "line": 2, "quote": "In May 1972, 7 cases were found"}
    c = card(root, year="May 1972", numeral="7", caption="cases found, Gamma", cite=q,
             sources=[{"id": TXT, "licence": "public domain"}])
    assert counts.check_card(c, root)["numeral"]["kind"] == "quote"
    with pytest.raises(maps.MapRefused, match="not in the cited lines"):
        counts.check_card({**c, "cite": {**q, "line": 1}}, root)
    with pytest.raises(maps.MapRefused, match="the card says 8"):
        counts.check_card({**c, "numeral": "8"}, root)


def test_an_empty_cell_is_no_figure_and_never_zero(root, tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "table.csv").write_text("entity,code,year,cases\nWorld,OWID_WRL,1966,\n", encoding="utf-8")
    c = card(tmp_path, year="1966", numeral="0", cite=cell(tmp_path, "World", 1966))
    with pytest.raises(maps.MapRefused, match="empty: no figure, which is not zero"):
        counts.check_card(c, tmp_path)


def test_every_number_on_a_card_is_cited(root):
    with pytest.raises(maps.MapRefused, match="caption"):
        counts.check_card(card(root, caption="cases reported in 2 regions"), root)
    good = {"text": "{n} countries reporting cases", "numeral": "1",
            "cite": {"csv": "data/table.csv", "sha256": sha(root, "data/table.csv"), "licence": "CC BY 4.0",
                     "source": SRC, "count": True, "column": "cases", "where": {"year": "1970"}}}
    assert counts.check_card(card(root, lines=[good]), root)["lines"][0]["value"] == 1, \
        "aggregates (OWID_ and empty codes) are never counted as countries"
    with pytest.raises(maps.MapRefused):
        counts.check_card(card(root, lines=[{**good, "numeral": "2"}]), root)
    with pytest.raises(maps.MapRefused, match="nothing on the card cites"):
        counts.check_card(card(root, sources=[{"id": SRC, "licence": "CC BY 4.0"},
                                               {"id": TXT, "licence": "public domain"}]), root)


# ---------------------------------------------------------------- the animated count

def test_a_count_changes_on_screen_only_by_cutting_between_cited_values(root):
    cards = {"C70": card(root, id="C70"),
             "C71": card(root, id="C71", year="1971", numeral="0", cite=cell(root, "World", 1971))}
    assert counts.check_sequence({"id": "S", "steps": ["C70", "C71"]}, cards, root) == ["C70", "C71"]
    mid = {"year": "1970", "numeral": "750", "caption": "cases reported, world", "interpolated": True,
           "source_short": "Fixture table", "sources": [{"id": SRC, "licence": "CC BY 4.0"}]}
    with pytest.raises(counts.SequenceRefused, match="no citation"):
        counts.check_sequence({"id": "S", "steps": ["C70", mid, "C71"]}, cards, root)
    with pytest.raises(counts.SequenceRefused, match="cutting between cited values"):
        counts.check_sequence({"id": "S", "mode": "count_up", "steps": ["C70", "C71"]}, cards, root)


# ---------------------------------------------------------------- the data layer

def test_every_csv_entity_must_match_natural_earth_by_iso3_or_say_why_not(root, tmp_path):
    for rel in ("naturalearth/ne_10m_admin_0_countries.geojson", "land.geojson"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes((root / rel).read_bytes())
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "table.csv").write_text(CSV_TEXT + "Zeta,ZZZ,1970,4\nNocode,,1970,3\n", encoding="utf-8")
    d = data_layer(tmp_path)
    with pytest.raises(maps.MapRefused, match=r"2 CSV entities match no Natural Earth country.*'Nocode'.*'Zeta'"):
        maps.data_state("M", d, tmp_path, tmp_path)
    d["not_countries"] = {**d["not_countries"], "Zeta": {"why": "a state of its time"},
                          "Nocode": {"why": "a group"}}
    with pytest.raises(maps.MapRefused, match="never left off the map"):
        maps.data_state("M", d, tmp_path, tmp_path)
    d["codes"] = {"Nocode": "CCC"}
    d["not_countries"] = {k: v for k, v in d["not_countries"].items() if k != "Nocode"}
    d["not_countries"]["Zeta"] = {"why": "folded into another row", "aggregate": True}
    st = maps.data_state("M", d, tmp_path, tmp_path)
    assert st["values"]["CCC"] == 3
    d["not_countries"]["Alpha"] = {"why": "no", "aggregate": True}
    with pytest.raises(maps.MapRefused, match="cannot be listed as not a country"):
        maps.data_state("M", d, tmp_path, tmp_path)


def test_no_data_is_drawn_distinct_from_zero(root):
    st = maps.data_state("M", data_layer(root), root, root)
    assert st["states"]["AAA"][0] == "cases" and st["states"]["BBB"][0] == "zero"
    assert st["states"]["CCC"][0] == "nodata" and st["states"]["TTT"][0] == "nodata"
    img, info = maps.render_map(world_map(root), root, data_root=root)
    rec = info["data"][0]
    assert rec["lit_in_view"] == ["AAA"] and rec["zero_in_view"] == ["BBB"]
    assert set(rec["nodata_in_view"]) == {"CCC", "TTT"}
    proj = maps.Projection([9.5, 9.5, 14.5, 14.5], maps.DEFAULT_FRAME, (1920, 1080))
    a = np.asarray(img).astype(int)

    def patch(lon, lat):
        x, y = (int(round(v)) for v in proj(lon, lat))
        return a[y - 20:y + 20, x - 20:x + 20].reshape(-1, 3)
    zero, nodata, lit = patch(13.0, 10.6), patch(10.6, 13.4), patch(10.6, 10.6)
    assert zero.std(axis=0).max() < 2, "zero is a flat fill"
    assert nodata.std(axis=0).max() > 4, "no data is hatched"
    assert abs(zero.mean(axis=0) - nodata.mean(axis=0)).max() > 1 or nodata.std(axis=0).max() > 4
    assert lit.mean(axis=0)[2] > zero.mean(axis=0)[2] + 30, "a country with cases is lit in DRAWN's blue"
    again, _ = maps.render_map(world_map(root), root, data_root=root)
    assert maps.png_bytes(img) == maps.png_bytes(again)


def test_a_country_lit_in_a_year_its_row_says_zero_fails(root):
    s = world_map(root, 1971)
    s["data"]["expect_lit"] = ["AAA"]
    with pytest.raises(maps.MapRefused, match="AAA reports 0 in 1971"):
        maps.render_map(s, root, data_root=root)
    s["data"]["expect_lit"] = []
    maps.render_map(s, root, data_root=root)


def test_a_map_of_a_year_outside_the_data_is_refused(root):
    with pytest.raises(maps.MapRefused, match="no row for any entity in 1972"):
        maps.render_map(world_map(root, 1972), root, data_root=root)


def test_a_data_figure_comes_from_the_table_and_never_stands_for_no_data(root):
    s = world_map(root)
    s["data"]["figures"] = [{"code": "AAA", "label": "Alpha"}]
    _, info = maps.render_map(s, root, data_root=root)
    assert info["data"][0]["figures"] == [{"code": "AAA", "value": 1500, "line": 2}]
    s["data"]["figures"] = [{"code": "CCC", "label": "Gamma"}]
    with pytest.raises(maps.MapRefused, match="the table has none"):
        maps.render_map(s, root, data_root=root)


def test_a_data_map_needs_a_legend_entry_for_every_state_it_draws(root):
    s = world_map(root)
    s["legend"] = [e for e in s["legend"] if e["style"] != "nodata"]
    with pytest.raises(maps.MapRefused, match="tell no figure from zero"):
        maps.render_map(s, root, data_root=root)


def test_a_territory_takes_a_countrys_figure_only_with_a_note(root):
    s = world_map(root)
    s["data"]["territories"] = {"AAA": ["TTT"]}
    with pytest.raises(maps.MapRefused, match="territories_note"):
        maps.check_spec(s)
    s["data"]["territories_note"] = "Tee is drawn with Alpha, as it was then."
    s["notes"] = [s["data"]["territories_note"]]
    st = maps.data_state("M", s["data"], root, root)
    assert st["states"]["TTT"] == ("cases", "AAA")


def test_the_unplaced_pair_is_a_per_film_list(root):
    s = {"id": "U", "layers": [{"file": "b.geojson", "style": "border",
                                "where": {"ADM0_A3_L": "BGD", "ADM0_A3_R": "IND"}}]}
    assert maps._unplaced_pair_possible(s["layers"][0]["where"], maps.unplaced_list(s)), "film 1's default holds"
    assert maps._unplaced_pair_possible(s["layers"][0]["where"], maps.unplaced_list({**s, "unplaced": []})) is None
    with pytest.raises(maps.MapRefused, match="pair of two"):
        maps.unplaced_list({"id": "U", "unplaced": [{"pair": ["BGD"]}]})


# ---------------------------------------------------------------- the ledger flow

def test_a_count_card_ledger_item_is_marked_drawn_by_the_engine(root):
    from studio.engine import render
    img, info = maps.render_map(card(root), root, data_root=root)
    fields = maps.ledger_for(card(root), info)
    item = {"id": "C1", "generator": "studio/engine/counts.py from specs/C1.json", **fields}
    assert render.is_synthetic(item)
    assert render.LICENCE_OK.match(item["licence"])
    assert render.mark_label({"mark": "DRAWN"}, item) == "Drawn · from Fixture table"
    assert "line 6, column cases = 1500" in item["method"]["text"]


def test_check_specs_checks_count_cards_against_their_data(root, tmp_path):
    (tmp_path / "C1.json").write_text(json.dumps(card(root)), encoding="utf-8")
    assert maps.check_specs(tmp_path, root) == []
    assert maps.check_specs(tmp_path) and "data root" in maps.check_specs(tmp_path)[0]
    (tmp_path / "C2.json").write_text(json.dumps(card(root, id="C2", numeral="9")), encoding="utf-8")
    problems = maps.check_specs(tmp_path, root)
    assert len(problems) == 1 and problems[0].startswith("C2.json")
    (tmp_path / "M1.json").write_text(json.dumps(world_map(root, 1972)), encoding="utf-8")
    assert any("1972" in p for p in maps.check_specs(tmp_path, root, root))


# ---------------------------------------------------------------- review of d05870c (probes A to K)

HISTORY2 = ("about 1.5 million died in 1975\n"
            "there was no one left in 1975\n"
            "In 1975 one outbreak was found.\n"
            "only one appearance since then\n"
            "Hansard, 8 December 1975\n")


@pytest.fixture()
def hroot(root, tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "h.txt").write_text(HISTORY2, encoding="utf-8")
    return tmp_path


def hq(hroot, line, quote, lines=1):
    return {"text": "data/h.txt", "sha256": sha(hroot, "data/h.txt"), "licence": "public domain", "source": TXT,
            "line": line, "lines": lines, "quote": quote}


def qcard(hroot, numeral, cite, **kw):
    return {"id": "Q", "kind": "count_card", "year": "1975", "numeral": numeral, "caption": "outbreaks",
            "cite": cite, "source_short": "Fixture history", "sources": [{"id": TXT, "licence": "public domain"}], **kw}


def test_probe_a_the_year_must_stand_in_the_numerals_own_quote(hroot):
    assert counts.check_card(qcard(hroot, "1", hq(hroot, 3, "In 1975 one outbreak was found")), hroot)
    c = qcard(hroot, "1", hq(hroot, 4, "only one appearance"))
    with pytest.raises(maps.MapRefused, match="quoted span does not print it"):
        counts.check_card(c, hroot)
    with pytest.raises(maps.MapRefused, match="year_cites are not accepted"):
        counts.check_card({**c, "year_cites": [hq(hroot, 5, "8 December 1975")]}, hroot)


def test_probe_b_a_cells_year_is_its_own_rows_year(root):
    c = card(root, year="1971")
    with pytest.raises(maps.MapRefused, match="cited row is 1970"):
        counts.check_card(c, root)
    with pytest.raises(maps.MapRefused, match="year_cites"):
        counts.check_card({**c, "year_cites": [cell(root, "World", 1971)]}, root)


def test_probe_k_every_lines_year_is_the_cards_year(root):
    ln = {"text": "Alpha, {n}", "numeral": "0", "cite": cell(root, "Alpha", 1971)}
    with pytest.raises(maps.MapRefused, match=r"lines\[0\] is cited for 1971; the card is 1970"):
        counts.check_card(card(root, lines=[ln]), root)
    ok = {"text": "Alpha, {n}", "numeral": "1,500", "cite": cell(root, "Alpha", 1970)}
    assert counts.check_card(card(root, lines=[ok]), root)


@pytest.mark.parametrize("caption", ["cases, in thirty countries", "one week of cases", "a hundred cases",
                                     "cases in 2 regions", "cases by the million"])
def test_probe_c_number_words_and_digits_in_a_caption_are_refused(root, caption):
    with pytest.raises(maps.MapRefused, match="no citation"):
        counts.check_card(card(root, caption=caption), root)


def test_probe_d_number_words_or_a_second_n_in_a_line_are_refused(root):
    base = {"numeral": "1,500", "cite": cell(root, "Alpha", 1970)}
    with pytest.raises(maps.MapRefused, match="million"):
        counts.check_card(card(root, lines=[{**base, "text": "Alpha, {n} of a million"}]), root)
    with pytest.raises(maps.MapRefused, match="exactly one"):
        counts.check_card(card(root, lines=[{**base, "text": "Alpha, {n} and {n}"}]), root)


def test_probe_e_a_numeral_is_never_part_of_a_longer_number(hroot):
    with pytest.raises(maps.MapRefused, match="the card says 1;"):
        counts.check_card(qcard(hroot, "1", hq(hroot, 1, "about 1.5 million died in 1975")), hroot)
    with pytest.raises(maps.MapRefused, match="the card says 5;"):
        counts.check_card(qcard(hroot, "5", hq(hroot, 1, "about 1.5 million died in 1975")), hroot)


def test_probe_g_a_negated_number_word_is_never_a_count(hroot):
    with pytest.raises(maps.MapRefused, match="the card says 1;"):
        counts.check_card(qcard(hroot, "1", hq(hroot, 2, "there was no one left in 1975")), hroot)


def test_probe_i_a_data_maps_text_carries_no_uncited_number(root):
    for bad in ({"notes": ["36 countries still reported cases."]},
                {"notes": ["Drawn as each was from 1967 to 1977."]},
                {"legend": world_map(root)["legend"] + [{"style": "zero", "text": "No cases in twelve months"}]}):
        with pytest.raises(maps.MapRefused, match="no citation"):
            maps.check_spec(world_map(root, **bad))
    s = world_map(root)
    s["data"]["figures"] = [{"code": "AAA", "label": "Alpha, 1,500"}]
    with pytest.raises(maps.MapRefused, match="no citation"):
        maps.check_spec(s)
    maps.check_spec(world_map(root))   # the title's data year is allowed


def conflict(root):
    return [{"cell": {"csv": "data/table.csv", "column": "cases", "row": {"entity": "Alpha", "year": "1971"}},
             "text": {"text": "data/history.txt", "sha256": sha(root, "data/history.txt"), "licence": "public domain",
                      "source": TXT, "line": 2, "quote": "7 cases were found in Gamma"},
             "why": "a fixture conflict"}]


def test_a_cell_a_cited_text_contradicts_is_refused_with_both_citations(root):
    c = card(root, year="1971", numeral="0", cite=cell(root, "Alpha", 1971), conflicts=conflict(root))
    with pytest.raises(maps.MapRefused, match=r"contradicted by a cited text.*history.txt line 2"):
        counts.check_card(c, root)
    s = world_map(root, 1971, conflicts=conflict(root))
    with pytest.raises(maps.MapRefused, match="AAA in 1971 is drawn from line 3, but the cell is contradicted"):
        maps.render_map(s, root, data_root=root)
    bad = conflict(root)
    bad[0]["text"]["quote"] = "not in the file"
    with pytest.raises(maps.MapRefused, match="not in the cited lines"):
        counts.check_card(card(root, conflicts=bad), root)


def test_a_suspect_zero_is_refused_and_a_count_over_zero_is_not(root):
    z = [{"row": {"entity": "Alpha", "year": "1971"}, "why": "a war year"}]
    with pytest.raises(maps.MapRefused, match="the zero is suspect"):
        counts.check_card(card(root, year="1971", numeral="0", cite=cell(root, "Alpha", 1971), zero_suspect=z), root)
    with pytest.raises(maps.MapRefused, match="the zero is suspect"):
        maps.render_map(world_map(root, 1971, zero_suspect=z), root, data_root=root)
    z70 = [{"row": {"entity": "Alpha", "year": "1970"}, "why": "only zeros are suspect"}]
    assert counts.check_card(card(root, cite=cell(root, "Alpha", 1970), caption="cases reported, Alpha",
                                  zero_suspect=z70), root)


def test_a_lit_country_mostly_under_the_panel_scrim_is_refused(root, tmp_path):
    feats = copy.deepcopy(COUNTRIES)
    feats["features"].append(country("EEE", "EEE", (16.5, 10.5, 18.5, 12.5)))
    for rel in ("naturalearth/ne_10m_admin_0_countries.geojson", "land.geojson"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(json.dumps(feats), encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "table.csv").write_text(CSV_TEXT + "Echo,EEE,1970,3\n", encoding="utf-8")
    s = world_map(tmp_path)
    with pytest.raises(maps.MapRefused, match="EEE is lit in 1970 but 100% of it lies under the panel's scrim"):
        maps.render_map(s, tmp_path, data_root=tmp_path)
    framed = {k: v for k, v in s.items() if k not in ("extent", "layers", "data")}
    framed["views"] = [{"name": "v", "frame": [0.03, 0.10, 0.62, 0.92], "extent": s["extent"], "layers": s["layers"],
                        "data": s["data"]}]
    _, info = maps.render_map(framed, tmp_path, data_root=tmp_path)
    assert info["data"][0]["lit_in_view"] == ["AAA"], "a framed view stops before the panel"


def test_a_territories_note_is_printed_only_when_a_territory_takes_a_figure_in_view(root):
    note = "Tee is drawn with its neighbour, as it was then."

    def notes_drawn(owner):
        s = world_map(root, notes=[note])
        s["data"].update(territories={owner: ["TTT"]}, territories_note=note)
        _, info = maps.render_map(s, root, data_root=root)
        return [b["text"] for b in info["boxes"] if b["kind"] == "note"]
    assert notes_drawn("AAA"), "Alpha's figure is drawn on Tee"
    assert notes_drawn("CCC") == [], "Gamma has no figure, so Tee takes none"


def test_the_render_record_carries_a_pixel_hash(root, tmp_path):
    (tmp_path / "C1.json").write_text(json.dumps(card(root)), encoding="utf-8")
    assert maps.main([str(tmp_path / "C1.json"), "--geodata", str(root), "--data", str(root),
                      "--out", str(tmp_path / "out")]) == 0
    rec = json.loads((tmp_path / "out" / "maps-render.json").read_text(encoding="utf-8"))[0]
    img, _ = maps.render_map(card(root), root, data_root=root)
    assert rec["pixels_sha256"] == maps.pixels_sha256(img) == hashlib.sha256(img.tobytes()).hexdigest()


def test_a_sequence_compares_each_steps_own_year(root):
    cards = {"A": card(root, id="A"), "B": card(root, id="B")}
    with pytest.raises(counts.SequenceRefused, match="same value for the same year"):
        counts.check_sequence({"id": "S", "steps": ["A", "B"]}, cards, root)


def test_the_count_of_countries_says_it_counts_by_todays_codes(root):
    got = maps.csv_count({"csv": "data/table.csv", "sha256": sha(root, "data/table.csv"), "licence": "CC BY 4.0",
                          "source": SRC, "count": True, "column": "cases", "where": {"year": "1970"}}, root)
    assert "today's ISO3 codes" in got["rule"]
