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
    return write_doubts(r)


def sha(root, rel):
    return hashlib.sha256((root / rel).read_bytes()).hexdigest()


def write_doubts(r: Path) -> Path:
    """The table's doubts file, pinned to its CSV (empty: the fixture table has none)."""
    (r / "data" / "table.doubts.json").write_text(json.dumps(
        {"csv": "table.csv", "csv_sha256": sha(r, "data/table.csv"), "conflicts": [], "zero_suspect": []}),
        encoding="utf-8")
    return r


def cell(root, entity, year, **kw):
    return {"csv": "data/table.csv", "sha256": sha(root, "data/table.csv"),
            "doubts_sha256": sha(root, "data/table.doubts.json"), "licence": "CC BY 4.0", "source": SRC,
            "column": "cases", "row": {"entity": entity, "year": str(year)}, **kw}


def card(root, **kw):
    c = {"id": "C1", "kind": "count_card", "year": "1970", "numeral": "1,500", "caption": "cases reported, world",
         "cite": cell(root, "World", 1970, line=6), "source_short": "Fixture table",
         "sources": [{"id": SRC, "licence": "CC BY 4.0"}]}
    c.update(kw)
    return c


def data_layer(root, year=1970, **kw):
    d = {"csv": "data/table.csv", "sha256": sha(root, "data/table.csv"),
         "doubts_sha256": sha(root, "data/table.doubts.json"), "licence": "CC BY 4.0", "source": SRC,
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




def test_an_empty_cell_is_no_figure_and_never_zero(root, tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "table.csv").write_text("entity,code,year,cases\nWorld,OWID_WRL,1966,\n", encoding="utf-8")
    write_doubts(tmp_path)
    c = card(tmp_path, year="1966", numeral="0", cite=cell(tmp_path, "World", 1966))
    with pytest.raises(maps.MapRefused, match="empty: no figure, which is not zero"):
        counts.check_card(c, tmp_path)


def test_every_number_on_a_card_is_cited(root):
    with pytest.raises(maps.MapRefused, match="caption"):
        counts.check_card(card(root, caption="cases reported in 2 regions"), root)
    good = {"text": "{n} countries reporting cases", "numeral": "1",
            "cite": {"csv": "data/table.csv", "sha256": sha(root, "data/table.csv"), "licence": "CC BY 4.0",
                     "doubts_sha256": sha(root, "data/table.doubts.json"), "source": SRC, "count": True, "column": "cases", "where": {"year": "1970"}}}
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
    write_doubts(tmp_path)
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
    write_doubts(tmp_path)
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
                          "doubts_sha256": sha(root, "data/table.doubts.json"),
                          "source": SRC, "count": True, "column": "cases", "where": {"year": "1970"}}, root)
    assert "today's ISO3 codes" in got["rule"]


# ---------------------------------------------------------------- re-review of 58aea22: declared spans (N1 to N10)





def test_probe_b_a_cells_year_is_its_own_rows_year(root):
    c = card(root, year="1971")
    with pytest.raises(maps.MapRefused, match="is cited for 1970; the card says 1971"):
        counts.check_card(c, root)
    with pytest.raises(maps.MapRefused, match="year_cites"):
        counts.check_card({**c, "year_cites": [cell(root, "World", 1971)]}, root)


def test_probe_k_every_lines_year_is_the_cards_year(root):
    ln = {"text": "Alpha, {n}", "numeral": "0", "cite": cell(root, "Alpha", 1971)}
    with pytest.raises(maps.MapRefused, match=r"lines\[0\] is cited for 1971; the card says 1970"):
        counts.check_card(card(root, lines=[ln]), root)
    ok = {"text": "Alpha, {n}", "numeral": "1,500", "cite": cell(root, "Alpha", 1970)}
    assert counts.check_card(card(root, lines=[ok]), root)






@pytest.mark.parametrize("caption", ["nought cases", "none reported", "a single case", "a half of the cases",
                                     "cases twice over", "a handful of cases", "nil cases"])
def test_probe_n8_more_number_words_in_a_caption_are_refused(root, caption):
    with pytest.raises(maps.MapRefused, match="no citation"):
        counts.check_card(card(root, caption=caption), root)
    assert counts.check_card(card(root, caption="the last cases reported"), root)


def test_probe_n9_a_data_maps_title_may_name_only_its_data_year(root):
    with pytest.raises(maps.MapRefused, match="the title names 1971"):
        maps.check_spec(world_map(root, 1970, title="Fixture countries, 1971"))
    with pytest.raises(maps.MapRefused, match="no citation"):
        maps._lint_data_text({**world_map(root, 1970), "title": "Fixture, 1970 and 1971"}, [world_map(root, 1970)])


def test_probe_n10_a_map_note_saying_nought_is_refused(root):
    with pytest.raises(maps.MapRefused, match="Nought"):
        maps.check_spec(world_map(root, notes=["Nought cases in Gamma."]))


# ---------------------------------------------------------------- doubts travel with the table (N11 to N15)

def with_sidecar(root, tmp_path, conflicts=(), zero_suspect=(), csv_sha=None):
    for rel in ("naturalearth/ne_10m_admin_0_countries.geojson", "land.geojson", "data/table.csv", "data/history.txt"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes((root / rel).read_bytes())
    side = {"csv": "table.csv", "csv_sha256": csv_sha or sha(tmp_path, "data/table.csv"),
            "conflicts": list(conflicts), "zero_suspect": list(zero_suspect)}
    (tmp_path / "data" / "table.doubts.json").write_text(json.dumps(side), encoding="utf-8")
    return tmp_path


def side_conflict(r):
    return {"row": {"entity": "Alpha", "year": "1971"},
            "text": {"text": "data/history.txt", "sha256": sha(r, "data/history.txt"), "licence": "public domain",
                     "source": TXT, "line": 2, "quote": "7 cases were found in Gamma"},
            "why": "a fixture conflict"}


def test_probe_n11_n12_a_map_of_a_doubted_cell_refuses_whatever_the_spec_says(root, tmp_path):
    r = with_sidecar(root, tmp_path)
    (r / "data" / "table.doubts.json").write_text(json.dumps(
        {"csv": "table.csv", "csv_sha256": sha(r, "data/table.csv"), "conflicts": [side_conflict(r)]}), encoding="utf-8")
    for spec_doubts in ({}, {"conflicts": []}):
        with pytest.raises(maps.MapRefused, match="AAA in 1971 is drawn from line 3, but the cell is contradicted"):
            maps.render_map(world_map(r, 1971, **spec_doubts), r, data_root=r)


def test_probe_n13_n14_a_card_of_a_doubted_cell_refuses_whatever_the_spec_says(root, tmp_path):
    r = with_sidecar(root, tmp_path, zero_suspect=[{"row": {"entity": "Beta", "year": "1971"}, "why": "a war year"}])
    (r / "data" / "table.doubts.json").write_text(json.dumps(
        {"csv": "table.csv", "csv_sha256": sha(r, "data/table.csv"), "conflicts": [side_conflict(r)],
         "zero_suspect": [{"row": {"entity": "Beta", "year": "1971"}, "why": "a war year"}]}), encoding="utf-8")
    with pytest.raises(maps.MapRefused, match="contradicted by a cited text.*history.txt line 2"):
        counts.check_card(card(r, year="1971", numeral="0", cite=cell(r, "Alpha", 1971)), r)
    with pytest.raises(maps.MapRefused, match="the zero is suspect"):
        counts.check_card(card(r, year="1971", numeral="0", caption="cases reported, Beta",
                               cite=cell(r, "Beta", 1971), zero_suspect=[]), r)


def test_probe_n15_a_count_over_a_doubted_row_refuses(root, tmp_path):
    r = with_sidecar(root, tmp_path)
    (r / "data" / "table.doubts.json").write_text(json.dumps(
        {"csv": "table.csv", "csv_sha256": sha(r, "data/table.csv"), "conflicts": [side_conflict(r)]}), encoding="utf-8")
    cnt = {"csv": "data/table.csv", "sha256": sha(r, "data/table.csv"), "licence": "CC BY 4.0", "source": SRC,
           "doubts_sha256": sha(r, "data/table.doubts.json"),
           "count": True, "column": "cases", "where": {"year": "1971"}}
    with pytest.raises(maps.MapRefused, match="takes in a doubted row"):
        maps.csv_count(cnt, r)
    assert maps.csv_count({**cnt, "where": {"year": "1970"}}, r)["value"] == 1


def test_a_stale_sidecar_refuses_and_a_spec_may_only_add_doubts(root, tmp_path):
    r = with_sidecar(root, tmp_path, csv_sha="0" * 64)
    with pytest.raises(maps.MapRefused, match="pins data/table.csv"):
        counts.check_card(card(r), r)
    r2 = with_sidecar(root, tmp_path / "b")
    z = [{"row": {"entity": "World", "year": "1971"}, "why": "added by the spec"}]
    with pytest.raises(maps.MapRefused, match="the zero is suspect"):
        counts.check_card(card(r2, year="1971", numeral="0", cite=cell(r2, "World", 1971), zero_suspect=z), r2)


# ---------------------------------------------------------------- advisories

def test_a_small_zero_country_past_the_full_wash_is_refused(root, tmp_path):
    feats = copy.deepcopy(COUNTRIES)
    feats["features"].append(country("EEE", "EEE", (17.6, 11.0, 17.9, 11.3)))
    for rel in ("naturalearth/ne_10m_admin_0_countries.geojson", "land.geojson"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(json.dumps(feats), encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "table.csv").write_text(CSV_TEXT + "Echo,EEE,1970,0\n", encoding="utf-8")
    write_doubts(tmp_path)
    with pytest.raises(maps.MapRefused, match="EEE is drawn as zero in 1970"):
        maps.render_map(world_map(tmp_path), tmp_path, data_root=tmp_path)


def test_a_spec_may_move_the_source_line_and_film_one_keeps_its_place(root):
    _, info = maps.render_map(world_map(root, source_at={"x": 0.05, "baseline": 0.94}), root, data_root=root)
    box = [b for b in info["boxes"] if b["kind"] == "source"][0]["box"]
    assert abs(box[0] - 0.05 * 1920) < 4 and box[3] < 0.955 * 1080
    _, info = maps.render_map(world_map(root), root, data_root=root)
    box = [b for b in info["boxes"] if b["kind"] == "source"][0]["box"]
    assert abs(box[0] - 0.04 * 1920) < 4, "a spec without source_at keeps film 1's position"
    with pytest.raises(maps.MapRefused, match="source_at"):
        maps.render_map(world_map(root, source_at={"x": 0.5, "baseline": 0.5}), root, data_root=root)


def test_an_in_map_figure_is_drawn_larger_than_a_sub_line(root):
    s = world_map(root)
    s["data"]["figures"] = [{"code": "AAA", "label": "Alpha"}]
    _, info = maps.render_map(s, root, data_root=root)
    fig = [b for b in info["boxes"] if b["text"] == "1,500"][0]["box"]
    assert fig[3] - fig[1] > 1.2 * (1.75 / 100 * 1080), "the figure's numeral is about 1.3x a sub-line"


# ---------------------------------------------------------------- PR #16: a quoted number is never a count (CoS 2026-10-11)

def qcard(r, numeral, cite, **kw):
    return {"id": "Q", "kind": "count_card", "year": "1975", "numeral": numeral, "caption": "outbreaks",
            "cite": cite, "source_short": "Fixture history", "sources": [{"id": TXT, "licence": "public domain"}], **kw}


# Every sentence of the reviewer's probe4 and probe5 (and their controls, which a sentence rule passed): none
# may supply a count, whatever its wording, spans or attestation.
PROBE5_LINES = [
    "About 1.5 million died in 1975.", "There were no cases in 1975.", "No one was left in 1975.", "Zero cases in 1975.",
    "5 million died in 1975.", "About 1·5 million in 1975.", "1 500 cases in 1975.", "Not even one case in 1975.",
    "In 1976 there were 3 cases, against 0 in 1975.", "1975: about 300 thousand cases.", "No one in 1975.",
    "In 1975 there were 12 cases; the next year, 3.", "12 cases among 19751 people.", "In 1975 smallpox ended.",
    "12% of cases in 1975.", "12–15 cases in 1975.", "More than 12 cases in 1975.", "12 cases in 1975, as in 1975.",
    "12 cases in 1975 (revised in 1976).", "There were 1,500 cases in 1975.", "١٢ cases in 1975.",
    "12 cases in 1975-76.", "Nought cases in 1975.", " 12 cases in 1975.", "In ’76 there were 3 cases; 1975 had 12.",
    "12 cases were reported in 1975.", "12m people died in 1975.", "Approx. 12 cases were reported in 1975.",
    "c. 12 cases were reported in 1975.", "12 cases were reported in the 1970s.", "Officials didn’t record 12 cases in 1975.",
    "12 or more cases were reported in 1975.", "12 cases had been reported since 1975.", "12+ cases were reported in 1975.",
    "12k cases were reported in 1975.", "The 12th case was reported in 1975.", "Twelve cases were reported in 1975.",
    "12 cases were reported by 1975.", "Upwards of 12 cases were reported in 1975.", "As many as 12 cases were reported in 1975.",
    "Was it true 12 cases were reported in 1975?", "It is false that 12 cases were reported in 1975.",
    "Cases rose 12-fold in 1975.", "12 times as many cases were seen in 1975.", "Perhaps 12 cases were reported in 1975.",
    "An estimated 12 cases were reported in 1975.", "12 cases a week were reported in 1975.",
    "Dr. Rao said 12 cases were reported in 1975.", "12 cases were reported in 1975 A.D.",
    "Est. 12 cases were reported in 1975.", "12 cases, give or take, were reported in 1975."]


def text_cite(r, line, quote, **kw):
    return {"text": "data/q.txt", "sha256": sha(r, "data/q.txt"), "licence": "public domain", "source": TXT,
            "line": line, "quote": quote, **kw}


@pytest.fixture()
def proot(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "q.txt").write_text("\n".join(PROBE5_LINES) + "\n", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("i", range(len(PROBE5_LINES)), ids=[f"probe5-{i + 1}" for i in range(len(PROBE5_LINES))])
def test_probe5_no_quoted_sentence_supplies_a_count(proot, i):
    q = PROBE5_LINES[i].strip()
    extra = {"numeral_at": [0, 2], "year_at": [0, 4], "attested": {"by": "x", "date": "y", "note": "z"}}
    with pytest.raises(maps.MapRefused, match=r"a quoted number is not accepted as a count \(CoS 2026-10-11\)"):
        counts.check_card(qcard(proot, "12", text_cite(proot, i + 1, q, **extra)), proot)


def test_a_quoted_number_is_refused_for_a_lines_n_too(root, proot):
    ln = {"text": "Gamma, {n}", "numeral": "12", "cite": text_cite(proot, 26, "12 cases were reported in 1975.")}
    c = card(root, lines=[ln], sources=[{"id": SRC, "licence": "CC BY 4.0"}, {"id": TXT, "licence": "public domain"}])
    for f in ("data/q.txt",):
        (root / f).parent.mkdir(parents=True, exist_ok=True)
        (root / f).write_bytes((proot / f).read_bytes())
    with pytest.raises(maps.MapRefused, match=r"lines\[0\].*a quoted number is not accepted as a count"):
        counts.check_card(c, root)


def test_a_year_outside_the_data_has_no_count_card(root):
    q = {"text": "data/history.txt", "sha256": sha(root, "data/history.txt"), "licence": "public domain",
         "source": TXT, "line": 2, "quote": "In May 1972, 7 cases were found in Gamma."}
    c = card(root, year="May 1972", numeral="7", caption="cases found, Gamma", cite=q,
             sources=[{"id": TXT, "licence": "public domain"}])
    with pytest.raises(maps.MapRefused, match="a quoted number is not accepted as a count"):
        counts.check_card(c, root)


def test_a_text_citation_still_supports_what_is_not_a_count(root):
    q = {"text": "data/history.txt", "sha256": sha(root, "data/history.txt"), "licence": "public domain",
         "source": TXT, "line": 2, "quote": "7 cases were found in Gamma"}
    c = card(root, also=[q], sources=[{"id": SRC, "licence": "CC BY 4.0"}, {"id": TXT, "licence": "public domain"}])
    got = counts.check_card(c, root)
    assert got["also"][0]["kind"] == "quote" and got["numeral"]["kind"] == "cell"
    with pytest.raises(maps.MapRefused, match="not in the cited lines"):
        counts.check_card({**c, "also": [{**q, "quote": "8 cases"}]}, root)


# ---------------------------------------------------------------- the sidecar is pinned (SC1 to SC4)

def test_a_csv_citation_pins_its_doubts(root):
    c = cell(root, "World", 1970, line=6)
    c.pop("doubts_sha256")
    with pytest.raises(maps.MapRefused, match="pins its doubts too"):
        counts.check_card(card(root, cite=c), root)
    with pytest.raises(maps.MapRefused, match="doubts_sha256"):
        maps.check_spec(world_map(root, data={k: v for k, v in data_layer(root).items() if k != "doubts_sha256"}))


def pinned_root(root, tmp_path):
    r = with_sidecar(root, tmp_path)
    (r / "data" / "table.doubts.json").write_text(json.dumps(
        {"csv": "table.csv", "csv_sha256": sha(r, "data/table.csv"), "conflicts": [side_conflict(r)],
         "zero_suspect": [{"row": {"entity": "Beta", "year": "1971"}, "why": "a war year"}]}), encoding="utf-8")
    return r


def test_probe_sc0_to_sc4_the_doubts_cannot_be_deleted_emptied_or_swapped(root, tmp_path):
    r = pinned_root(root, tmp_path)
    alpha = card(r, year="1971", numeral="0", cite=cell(r, "Alpha", 1971))   # pinned to the full sidecar
    beta = card(r, year="1971", numeral="0", caption="cases reported, Beta", cite=cell(r, "Beta", 1971))
    m71 = world_map(r, 1971)
    with pytest.raises(maps.MapRefused, match="contradicted"):
        counts.check_card(alpha, r)                                                     # SC0
    side = r / "data" / "table.doubts.json"
    full = side.read_bytes()
    side.write_text(json.dumps({"csv": "table.csv", "csv_sha256": sha(r, "data/table.csv"), "conflicts": [],
                                "zero_suspect": []}), encoding="utf-8")
    for spec, run in ((alpha, counts.check_card), (beta, counts.check_card)):        # SC2, SC3
        with pytest.raises(maps.MapRefused, match="the citation pins"):
            run(spec, r)
    with pytest.raises(maps.MapRefused, match="the citation pins"):                  # SC4
        maps.render_map(m71, r, data_root=r)
    side.unlink()
    with pytest.raises(maps.MapRefused, match="is missing"):                         # SC1
        counts.check_card(alpha, r)
    side.write_bytes(full)
    with pytest.raises(maps.MapRefused, match="contradicted"):
        counts.check_card(alpha, r)


def test_the_render_record_carries_the_doubts_pin(root, tmp_path):
    (tmp_path / "C1.json").write_text(json.dumps(card(root)), encoding="utf-8")
    assert maps.main([str(tmp_path / "C1.json"), "--geodata", str(root), "--data", str(root),
                      "--out", str(tmp_path / "out")]) == 0
    rec = json.loads((tmp_path / "out" / "maps-render.json").read_text(encoding="utf-8"))[0]
    assert rec["doubts_sha256"] == [sha(root, "data/table.doubts.json")]
    assert rec["ledger"]["method"]["cites"]["numeral"]["doubts_sha256"] == sha(root, "data/table.doubts.json")


def test_a_file_rewritten_in_place_is_hashed_again(tmp_path):
    """No cache: a same-size rewrite with its mtime put back is still hashed from its bytes (probe5)."""
    import os
    f = tmp_path / "f.txt"
    f.write_bytes(b"AAAA")
    first, st = maps.file_sha256(str(f)), os.stat(f)
    f.write_bytes(b"BBBB")
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert maps.file_sha256(str(f)) != first


def test_the_engine_states_a_drawn_frames_content_flags_for_every_film(root):
    """A count card's and a map's ledger fields carry graphic_medical, named_patient, shows_violence and
    shows_bodies false and no people: the studio drew them, so it says so. Under a film's declared imagery
    rule (film 2 shows disease) the content-flags check passes on them; with a flag left out it refuses."""
    from studio.engine import policy
    rule, problems = policy.imagery_rule({"imagery_rule": {"show_disease": True,
                                                           "statement": "This film shows the disease as the record holds it."}})
    assert not problems
    img, info = maps.render_map(card(root), root, data_root=root)
    for fields in (maps.ledger_for(card(root), info), maps.ledger_fields(world_map(root))):
        item = {"id": "X", "generator": "studio/engine", **fields}
        assert {k: item[k] for k in maps.DRAWN_CONTENT} == maps.DRAWN_CONTENT
        checks = {c["rule"]: c["ok"] for c in policy.asset_checks(item, rule)}
        assert checks["content-flags"] and checks["no-bodies"] and checks["imagery-rule"]
        bare = {k: v for k, v in item.items() if k != "named_patient"}
        assert not {c["rule"]: c["ok"] for c in policy.asset_checks(bare, rule)}["content-flags"]


# ---------------------------------------------------------------- A31: the mark's zones on a count card

def test_a_count_card_warns_for_text_in_a_zone_the_films_own_text_covers(root, monkeypatch):
    _, info = maps.render_map(card(root), root, data_root=root)
    assert info["warnings"] == []                                   # the card's own layout stays clear
    monkeypatch.setitem(maps.COVERED, "test", (0.30, 0.30, 0.70, 0.80))
    _, info = maps.render_map(card(root), root, data_root=root)
    assert any("sits in the test zone" in w for w in info["warnings"])


def test_a_source_line_under_the_provenance_label_is_refused():
    W, H = 1920, 1080
    y0, y1 = 0.929 * H, 0.944 * H                                   # film 2's source line at its 0.94 baseline
    maps.source_clear_of_label("D1", {"box": (0.05 * W, y0, 0.59 * W, y1)}, W, H)
    with pytest.raises(maps.MapRefused, match="provenance label's zone"):
        maps.source_clear_of_label("D1", {"box": (0.05 * W, y0, 0.62 * W, y1)}, W, H)
