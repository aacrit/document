"""The map engine (studio/engine/maps.py): DRAWN frames from a spec, in the
house style, deterministically, with their sources on the frame."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pytest

from studio.engine import maps

FIX = Path(__file__).resolve().parent / "fixture" / "maps"
GEO: Path = FIX  # replaced by the generated geodata folder before any test runs


@pytest.fixture(scope="module", autouse=True)
def _geodata(tmp_path_factory):
    """R-08: the fixture's GeoJSON is written at test time, never tracked."""
    import sys
    sys.path.insert(0, str(FIX))
    import make_geodata
    global GEO
    GEO = make_geodata.write(tmp_path_factory.mktemp("geodata"))
    yield


def spec() -> dict:
    return json.loads((FIX / "spec.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rendered(_geodata):
    return maps.render_map(spec(), GEO)


def test_a_map_is_a_1920x1080_rgb_frame(rendered):
    img, info = rendered
    assert img.size == (1920, 1080) and img.mode == "RGB"
    assert info["size"] == [1920, 1080]


def test_a_map_renders_the_same_bytes_twice(rendered):
    img, _ = rendered
    again, _ = maps.render_map(spec(), GEO)
    a, b = maps.png_bytes(img), maps.png_bytes(again)
    assert hashlib.sha256(a).hexdigest() == hashlib.sha256(b).hexdigest()


def test_the_frame_carries_its_source_line(rendered):
    img, info = rendered
    assert info["source_line"] == "Data: Natural Earth; fixture-src:p1"
    assert info["source_line"] == maps.ledger_fields(spec())["source_line"]
    box = [b for b in info["boxes"] if b["kind"] == "source"]
    assert len(box) == 1 and box[0]["text"] == info["source_line"]
    x0, y0, x1, y1 = (int(round(v)) for v in box[0]["box"])
    assert y1 <= 1080 and y0 > 0.93 * 1080, "below the subtitles and lower thirds"
    region = np.asarray(img)[y0:y1, x0:x1].astype(int)
    assert region.max() - region.min() > 60, "the source line's glyphs are on the frame"


def test_the_geodata_used_is_recorded_with_its_hash(rendered):
    _, info = rendered
    assert set(info["geodata"]) == {"land.geojson", "river.geojson"}
    assert all(re.fullmatch(r"[0-9a-f]{64}", h) for h in info["geodata"].values())


@pytest.mark.parametrize("sources", [
    [],
    [{"id": "Natural Earth", "licence": "public domain"}],
    [{"id": "fixture-src:p1", "licence": "CC0"}, {"id": "Natural Earth", "licence": "public domain"}],
    [{"id": "Natural Earth", "licence": "public domain"}, {"id": "fixture-src:p1"}],
])
def test_a_spec_without_natural_earth_and_a_licensed_cited_source_is_refused(sources):
    s = spec()
    s["sources"] = sources
    with pytest.raises(maps.MapRefused):
        maps.render_map(s, GEO)


def test_the_palette_reads_tokens_css():
    tokens = maps.read_tokens()
    pal = maps.palette()
    hexes = {k: tuple(int(tokens[k][i:i + 2], 16) for i in (1, 3, 5)) for k in ("--doc-cold", "--doc-bone")}
    assert pal["cold"][:3] == hexes["--doc-cold"]          # --mark-generated: var(--doc-cold)
    assert pal["text"][:3] == hexes["--doc-bone"]          # --color-cream: var(--doc-bone)
    assert pal["muted"][3] == round(255 * 0.66)            # cream-muted: bone at 0.66
    assert pal["line"][:3] == (255, 246, 227)              # --mark-text, as motion.py has it


def test_changing_a_token_changes_the_map(tmp_path):
    src = maps.TOKENS.read_text(encoding="utf-8")
    alt = tmp_path / "tokens.css"
    alt.write_text(src.replace("--doc-cold: #2f5fa8;", "--doc-cold: #3a6ab0;"), encoding="utf-8")
    assert maps.palette(alt)["cold"][:3] == (0x3A, 0x6A, 0xB0)
    a, _ = maps.render_map(spec(), GEO)
    b, _ = maps.render_map(spec(), GEO, tokens=alt)
    assert maps.png_bytes(a) != maps.png_bytes(b)


def test_oklch_round_trips_the_primaries():
    tokens = maps.read_tokens()
    for k in ("--doc-black", "--doc-bone", "--doc-safelight", "--doc-cold"):
        rgb = maps.resolve(k, tokens)[:3]
        assert maps.oklch_to_rgb(*maps.rgb_to_oklch(rgb)) == rgb


def test_no_colour_literal_outside_the_token_file():
    """maps.py names roles and tokens only: no hex, no rgb(), no RGB tuple."""
    text = (Path(maps.__file__)).read_text(encoding="utf-8")
    code = "\n".join(ln.split("#", 1)[0] if not ln.lstrip().startswith(("r\"", "\"")) else ln
                     for ln in text.splitlines())
    assert not re.search(r"#[0-9a-fA-F]{6}\b", text), "hex colour in maps.py"
    assert not re.search(r"\b(?:rgb|rgba|hsl)\(", code), "css colour function in maps.py"
    assert not re.search(r"\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*(?:,\s*\d{1,3}\s*)?\)", code), \
        "an RGB tuple literal in maps.py"


def test_every_pixel_comes_from_the_palette_family(rendered):
    """Only black, bone and cold blue touch a map (BRAND-KIT 7): no amber, no other hue."""
    img, _ = rendered
    arr = np.asarray(img).reshape(-1, 3).astype(int)
    r, g, b = arr[:, 0], arr[:, 1], arr[:, 2]
    warm = (r - b > 40) & (r > 120)            # anything amber-like is far warmer than bone (r-b 30)
    assert not warm.any()


@pytest.mark.parametrize("key,value", [("fill", "cold"), ("colour", "blue")])
def test_a_spec_never_carries_a_colour(key, value):
    s = spec()
    s["layers"][0][key] = value
    with pytest.raises(maps.MapRefused, match="colour"):
        maps.render_map(s, GEO)


def test_a_colour_literal_in_spec_text_is_refused():
    s = spec()
    s["notes"] = ["drawn in #2f5fa8"]
    with pytest.raises(maps.MapRefused):
        maps.render_map(s, GEO)


def test_an_em_dash_in_on_screen_copy_is_refused():
    s = spec()
    s["title"] = "A map — of nothing"
    with pytest.raises(maps.MapRefused, match="em dash"):
        maps.render_map(s, GEO)


def test_an_unknown_style_is_refused():
    s = spec()
    s["layers"][0]["style"] = "glow"
    with pytest.raises(maps.MapRefused, match="style"):
        maps.render_map(s, GEO)


def _bottom_right_spec(text):
    s = copy.deepcopy(spec())
    for k in ("legend", "notes"):
        s.pop(k)
    s["show_title"] = False
    s["frame"] = [0.04, 0.08, 0.98, 0.99]
    s["labels"].append({"text": text, "style": "note", "lon": 14.8, "lat": 10.0, "align": "l"})
    return s


def test_text_never_enters_the_mark_glyph_zone():
    """A31: the class glyph sits bottom right on every frame; map text that
    would lie under it is refused (the label beside it only warns)."""
    with pytest.raises(maps.MapRefused, match="mark zone"):
        maps.render_map(_bottom_right_spec("Under the class glyph in the corner"), GEO)
    _, info = maps.render_map(_bottom_right_spec("Under the class glyph"), GEO)
    assert "'Under the class glyph' sits in the label zone" in info["warnings"]


def test_the_g2_mark_corner_is_free_for_map_text():
    s = spec()
    s["labels"].append({"text": "Where the plate was", "style": "note", "lon": 9.6, "lat": 14.1})
    maps.render_map(s, GEO)                                         # A31: the mark left the top left


def test_text_never_enters_the_watermark_zone():
    s = copy.deepcopy(spec())
    for k in ("legend", "notes"):
        s.pop(k)
    s["show_title"] = False
    s["extent"] = [12.0, 12.0, 14.8, 14.2]
    s["frame"] = [0.5, 0.02, 0.98, 0.5]
    s["labels"].append({"text": "Under the watermark", "style": "note", "lon": 14.7, "lat": 14.15, "align": "r"})
    with pytest.raises(maps.MapRefused, match="watermark zone"):
        maps.render_map(s, GEO)


def test_a_layer_that_matches_nothing_is_refused():
    s = spec()
    s["layers"][2]["where"] = {"name": "No such river"}
    with pytest.raises(maps.MapRefused, match="matched nothing"):
        maps.render_map(s, GEO)


def test_a_clipped_line_keeps_only_the_part_inside_the_box():
    parts = maps.clip_line([[0.0, 0.0], [2.0, 0.0], [2.0, 2.0]], [1.0, -1.0, 3.0, 1.0])
    assert parts == [[(1.0, 0.0), (2.0, 0.0), (2.0, 1.0)]]


def test_two_views_render_side_by_side():
    s = spec()
    view = {k: s.pop(k) for k in ("extent", "layers", "places", "labels")}
    view["labels"] = []
    s["views"] = [{**view, "name": "a", "frame": [0.04, 0.25, 0.35, 0.9]},
                  {**view, "name": "b", "frame": [0.36, 0.25, 0.68, 0.9]}]
    img, info = maps.render_map(s, GEO)
    assert img.size == (1920, 1080)
    assert sum(1 for b in info["boxes"] if b["text"] == "Alpha") == 2


def test_the_ledger_fields_come_from_the_spec_alone():
    led = maps.ledger_fields(spec())
    assert led["title"] == "A fixture map"
    assert led["data_source"] == "Natural Earth; fixture-src:p1"
    assert led["credit"] == "void document studio, drawn from Natural Earth; fixture-src:p1"
    assert led["source_short"] == "Fixture source, page 1" and led["licence"] == "CC0"


def test_geonames_places_need_geonames_credited_and_make_the_frame_cc_by():
    s = spec()
    s["places"][0]["geonameid"] = 1
    with pytest.raises(maps.MapRefused, match="GeoNames"):
        maps.render_map(s, GEO)
    s["sources"].append({"id": maps.GEONAMES, "licence": "CC BY 4.0"})
    _, info = maps.render_map(s, GEO)
    assert info["source_line"].endswith("GeoNames (CC BY 4.0)")
    assert maps.ledger_fields(s)["licence"] == "CC-BY-4.0"
    assert maps.ledger_fields(s)["licence_note"] == "contains GeoNames data (CC BY 4.0); Natural Earth public domain"


@pytest.mark.parametrize("short,ok", [("x" * 40, True), ("x" * 41, False)])
def test_source_short_fits_the_plate(short, ok):
    s = spec()
    s["source_short"] = short
    if ok:
        maps.check_spec(s)
    else:
        with pytest.raises(maps.MapRefused, match="source_short"):
            maps.check_spec(s)


def test_overlapping_labels_are_refused():
    s = spec()
    s["labels"].append({"text": "Fixture river", "style": "river", "lon": 12.62, "lat": 11.01})
    s["labels"][-1]["text"] = "Another label"
    with pytest.raises(maps.MapRefused, match="overlap"):
        maps.render_map(s, GEO)


def test_an_arrow_whose_last_points_coincide_is_refused():
    s = spec()
    s["paths"] = [{"points": [[11.0, 11.0], [12.0, 12.0], [12.0, 12.0]], "style": "line_dashed", "arrow": True}]
    with pytest.raises(maps.MapRefused, match="same place"):
        maps.render_map(s, GEO)


def test_text_clipped_by_a_view_frame_is_refused():
    s = spec()
    view = {k: s.pop(k) for k in ("extent", "layers", "places", "labels")}
    view["labels"].append({"text": "Off the edge of this view", "style": "region", "lon": 14.6, "lat": 12.0})
    s["views"] = [{**view, "name": "a", "frame": [0.04, 0.25, 0.35, 0.9]}]
    with pytest.raises(maps.MapRefused, match="clipped"):
        maps.render_map(s, GEO)


def test_two_sides_share_one_weight_and_differ_by_hatch(tmp_path):
    a, b = maps.POLY["side_a"], maps.POLY["side_b"]
    assert a[:4] == b[:4] and a[4] == -b[4] != 0
    s = spec()
    s["layers"].insert(1, {"file": "land.geojson", "style": "side_a", "where": {"ADM0_A3": "FIX"}})
    s["layers"].insert(2, {"file": "land.geojson", "style": "side_b", "where": {"ADM0_A3": "FXE"}})
    img, _ = maps.render_map(s, GEO)
    arr = np.asarray(img).astype(float)
    proj = maps.Projection(s["extent"], maps.DEFAULT_FRAME, (1920, 1080))

    def patch(lon, lat):
        x, y = (int(v) for v in proj(lon, lat))
        return arr[y - 30:y + 30, x - 30:x + 30].mean()
    assert abs(patch(10.6, 10.9) - patch(13.3, 11.0)) < 6, "equal weight on both sides"


def test_the_plate_prints_the_short_source():
    from studio.engine.render import mark_detail
    item = {"data_source": "Natural Earth; a very long list of cited sources, items and pages", "source_short": "Short"}
    assert mark_detail({"mark": "DRAWN"}, item) == "from Short"
    assert mark_detail({"mark": "DRAWN"}, {"data_source": "Long"}) == "from Long"


def test_every_ledger_licence_is_on_the_render_allowlist_exactly():
    """The plancheck's licence-allowlist lint must pass every drawn ledger item the
    engine can produce: with and without GeoNames."""
    from studio.engine.render import LICENCE_OK
    plain = spec()
    geo = spec()
    geo["places"][0]["geonameid"] = 1
    geo["sources"].append({"id": maps.GEONAMES, "licence": "CC BY 4.0"})
    for s in (plain, geo):
        lic = maps.ledger_fields(s)["licence"]
        assert LICENCE_OK.fullmatch(lic), lic
        assert lic == lic.strip() and lic in ("CC0", "CC-BY-4.0")


def _with_award(s, note=True):
    s["layers"][3]["award"] = True
    s["notes"] = (["Line approximate, from the award's description."] if note else ["Another note."])
    return s


def test_the_method_is_read_from_the_spec():
    m = maps.method(spec())
    assert m == {**m, "award_line": False, "geonames_positions": False}
    assert "award" not in m["text"] and "GeoNames" not in m["text"]
    s = _with_award(spec())
    s["places"][0]["geonameid"] = 1
    s["sources"].append({"id": maps.GEONAMES, "licence": "CC BY 4.0"})
    m = maps.method(s)
    assert m["award_line"] and m["approximate_note"] and m["geonames_positions"]
    assert "award line" in m["text"] and "approximate" in m["text"] and "GeoNames" in m["text"]
    assert maps.ledger_fields(s)["method"] == m


def test_an_award_line_without_the_approximate_note_is_refused():
    with pytest.raises(maps.MapRefused, match="Line approximate"):
        maps.render_map(_with_award(spec(), note=False), GEO)


def test_a_span_keeps_the_stretch_between_the_nearest_vertices():
    line = [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [3.0, 0.0], [4.0, 0.0]]
    assert maps.span_line(line, {"from": [3.1, 0.05], "to": [1.0, 0.0]}) == line[1:4]
    assert maps.span_line(line, {"from": [9.0, 9.0], "to": [1.0, 0.0]}) is None


def test_a_spans_geonameid_needs_geonames_credited():
    s = spec()
    s["layers"][3]["span"] = {"from": [12.0, 10.1], "to": [11.8, 13.0], "basis": {"geonameid": 1}}
    with pytest.raises(maps.MapRefused, match="GeoNames"):
        maps.render_map(s, GEO)


def test_a_solid_bengal_award_line_is_refused():
    s = spec()
    s["layers"].append({"file": "river.geojson", "style": "line",
                        "where": {"FEATURECLA": "International boundary (verify)", "ADM0_A3_L": "BGD", "ADM0_A3_R": "IND"}})
    with pytest.raises(maps.MapRefused, match="Bengal award"):
        maps.check_spec(s)
    s["layers"][-1]["style"] = "border_today"
    maps.check_spec(s)


def test_check_specs_reports_every_violation_and_exits_non_zero(tmp_path):
    good = spec()
    bad = spec()
    bad["layers"].append({"file": "river.geojson", "style": "line",
                          "where": {"ADM0_A3_L": "BGD", "ADM0_A3_R": "IND"}})
    (tmp_path / "D1.json").write_text(json.dumps(good), encoding="utf-8")
    assert maps.check_specs(tmp_path) == []
    assert maps.main(["check-specs", str(tmp_path)]) == 0
    (tmp_path / "D2.json").write_text(json.dumps(bad), encoding="utf-8")
    problems = maps.check_specs(tmp_path)
    assert len(problems) == 1 and problems[0].startswith("D2.json") and "Bengal award" in problems[0]
    assert maps.main(["check-specs", str(tmp_path)]) == 1
    assert maps.main(["check-specs", str(tmp_path / "empty")]) == 1


def test_the_source_line_zone_carries_no_map_strokes():
    """Lines and outlines stop short of the source line: the zone is identical with
    and without every stroked layer."""
    base = spec()
    base["frame"] = [0.04, 0.35, 0.68, 1.12]   # push the land down under the source line
    base["labels"], base["places"] = [], []
    fills_only = copy.deepcopy(base)
    fills_only["layers"] = [ly for ly in base["layers"] if ly["style"] in maps.POLY]
    a, info = maps.render_map(base, GEO)
    b, _ = maps.render_map(fills_only, GEO)
    x0, y0, x1, y1 = (int(round(v)) for v in [b_ for b_ in info["boxes"] if b_["kind"] == "source"][0]["box"])
    za, zb = np.asarray(a)[y0 - 6:1080, max(0, x0 - 6):x1 + 6], np.asarray(b)[y0 - 6:1080, max(0, x0 - 6):x1 + 6]
    assert np.array_equal(za, zb)
    # and the strokes are really there, outside the zone
    assert not np.array_equal(np.asarray(a), np.asarray(b))


@pytest.mark.parametrize("where", [
    None,                                                        # no filter at all
    {"ADM0_A3_L": "BGD"},                                         # one side named
    {"FEATURECLA": "International boundary (verify)"},            # class only
    {"name": ["Fixture border", "Fixture east border"]},          # a list that includes it
])
def test_a_solid_layer_matching_a_bengal_feature_is_refused_at_render(where):
    s = spec()
    ly = {"file": "river.geojson", "style": "line"}
    if where is not None:
        ly["where"] = where
    s["layers"].append(ly)
    with pytest.raises(maps.MapRefused, match="Bengal award"):
        maps.render_map(s, GEO)
    ly["style"] = "border_today"   # the same features, dashed, are allowed
    maps.render_map(s, GEO)


@pytest.mark.parametrize("left,right,refused", [
    (["BGD", "PAK"], ["IND"], True),
    ("IND", ["BGD", "NPL"], True),
    (["PAK"], ["IND", "NPL"], False),
])
def test_list_values_in_where_are_read_statically(left, right, refused):
    s = spec()
    s["layers"].append({"file": "river.geojson", "style": "line", "where": {"ADM0_A3_L": left, "ADM0_A3_R": right}})
    if refused:
        with pytest.raises(maps.MapRefused, match="Bengal award"):
            maps.check_spec(s)
    else:
        maps.check_spec(s)


def test_check_specs_reports_a_malformed_spec_instead_of_crashing(tmp_path):
    (tmp_path / "D1.json").write_text("{not json", encoding="utf-8")
    bad = spec()
    bad["layers"] = "not a list"
    (tmp_path / "D2.json").write_text(json.dumps(bad), encoding="utf-8")
    problems = maps.check_specs(tmp_path)
    assert [p_.split(":")[0] for p_ in problems] == ["D1.json", "D2.json"]
    assert maps.main(["check-specs", str(tmp_path)]) == 1


def test_a_haloed_line_lies_on_a_dark_band():
    s = spec()
    s["layers"].append({"file": "river.geojson", "style": "working", "where": {"name": "Fixture river"}})
    with_halo, _ = maps.render_map(s, GEO)
    old = maps.HALOED
    try:
        maps.HALOED = set()
        without, _ = maps.render_map(s, GEO)
    finally:
        maps.HALOED = old
    assert np.asarray(with_halo).astype(int).sum() < np.asarray(without).astype(int).sum()


@pytest.mark.parametrize("style", ["border", "coast", "river", "working", "road", "line", "line_dashed"])
def test_only_border_today_may_draw_on_an_unplaced_pair(style):
    """Statically (both sides named) and at render (the feature's own pair)."""
    s = spec()
    s["layers"].append({"file": "river.geojson", "style": style, "where": {"ADM0_A3_L": "BGD", "ADM0_A3_R": "IND"}})
    with pytest.raises(maps.MapRefused, match="Bengal award"):
        maps.check_spec(s)
    s["layers"][-1]["where"] = {"FEATURECLA": "International boundary (verify)"}
    with pytest.raises(maps.MapRefused, match="Bengal award"):
        maps.render_map(s, GEO)
    s["layers"][-1]["style"] = "border_today"
    maps.render_map(s, GEO)


def test_a_mapping_in_where_is_refused():
    s = spec()
    s["layers"].append({"file": "river.geojson", "style": "border_today", "where": {"ADM0_A3_L": {"in": ["BGD"]}}})
    with pytest.raises(maps.MapRefused, match="mapping"):
        maps.check_spec(s)
    with pytest.raises(maps.MapRefused, match="mapping"):
        maps.render_map(s, GEO)
    with pytest.raises(maps.MapRefused, match="mapping"):
        maps._as_set({"in": ["BGD"]})


def test_a_hand_drawn_path_along_an_unplaced_line_is_refused():
    s = spec()
    along = [[13.0, 10.3], [13.4, 12.0], [13.9, 12.9]]           # the fixture's BGD-IND feature, traced by hand
    s["paths"] = [{"style": "line", "points": along}]
    with pytest.raises(maps.MapRefused, match="hand-drawn 'line' path runs along the Bengal award"):
        maps.render_map(s, GEO)
    s["paths"] = [{"style": "border_today", "points": along}]
    maps.render_map(s, GEO)
    s["paths"] = [{"style": "line", "points": [[12.4, 11.6], [14.2, 11.0]], "arrow": True}]   # crossing it is a route
    maps.render_map(s, GEO)
