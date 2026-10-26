"""A56 / BRAND-KIT 12b: a map draws no data credit and no notes (brand audit 2026-10-26, H1).

Real World's shot 6.14 printed "Data: Natural Earth; GeoNames (CC BY 4.0)" because its PNG was drawn on
2026-10-18 by an engine from before A56, and the film render took the PNG as it found it. These tests hold
three things: the engine's frame never carries the credit (by pixels); a map's on-screen text that reads as
a credit or a licence is refused; and the render refuses a map PNG the current engine did not draw, or whose
ledger item does not carry the engine's off-screen credit (so the CC BY attribution reaches sources.json and
description.txt).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from studio.engine import maps

FIX = Path(__file__).resolve().parent / "fixture" / "maps"
GEO: Path = FIX


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


XSS = '"><img src=x onerror=alert(1)>'
CREDITS = [
    "Data: Natural Earth; GeoNames (CC BY 4.0)",
    "Data: Natural Earth",
    "data : GeoNames",
    "Natural Earth; GeoNames (CC BY 4.0)",
    "Natural Earth; GeoNames",
    "GeoNames, CC-BY 4.0",
    "CC0",
    "Natural Earth (CC0 1.0)",
    "© OpenStreetMap contributors",
    "Source: Natural Earth",
    "Courtesy of the Library of Congress",
]


def _with_text(where: str, text: str) -> dict:
    s = spec()
    if where == "title":
        s["title"] = text
    elif where == "legend":
        s["legend"] = [{"style": "land", "text": text}]
    elif where == "figures":
        s["figures"] = [text]
    elif where == "label":
        s["labels"] = list(s.get("labels", [])) + [{"text": text, "style": "region", "at": [12.0, 12.0]}]
    elif where == "place":
        s["places"] = list(s["places"]) + [{"name": "Gamma", "label": text, "lon": 12.0, "lat": 12.0, "style": "town"}]
    return s


@pytest.mark.parametrize("where", ["title", "legend", "figures", "label", "place"])
@pytest.mark.parametrize("text", CREDITS)
def test_a_credit_or_licence_in_a_maps_on_screen_text_is_refused(where, text):
    with pytest.raises(maps.MapRefused, match="meta-text"):
        maps.check_spec(_with_text(where, text))


@pytest.mark.parametrize("text", ["Brussels", "Datia", "Database Street", "Cádiz", "Sources of the Indus",
                                  "Library of Congress"])
def test_a_place_name_that_only_resembles_a_credit_passes(text):
    maps.check_spec(_with_text("place", text))


def test_source_short_is_not_required_to_draw_a_map():
    """The frame no longer prints a source line, so a spec need not carry one; the ledger still gets the
    plate's short form, from the source ids without their licence parentheses."""
    s = spec()
    s.pop("source_short")
    s["sources"][1]["id"] = "GeoNames (CC BY 4.0)"
    maps.check_spec(s)
    led = maps.ledger_fields(s)
    assert led["source_short"] == "Natural Earth; GeoNames"
    assert led["source_line"] == "Data: Natural Earth; GeoNames (CC BY 4.0)"
    assert led["licence"] == "CC-BY-4.0" and "GeoNames data (CC BY 4.0)" in led["licence_note"]


def test_a_stated_source_short_still_fits_the_plate():
    s = spec()
    s["source_short"] = "x" * (maps.SOURCE_SHORT_MAX + 1)
    with pytest.raises(maps.MapRefused, match="source_short"):
        maps.check_spec(s)


def test_a_long_derived_source_short_is_cut_to_the_plate():
    s = spec()
    s.pop("source_short")
    s["sources"] += [{"id": f"src-a-long-citation:item{i}", "licence": "CC0"} for i in range(4)]
    short = maps.ledger_fields(s)["source_short"]
    assert len(short) <= maps.SOURCE_SHORT_MAX and short.startswith("Natural Earth")
    ids = [x["id"] for x in s["sources"]]
    assert all(part in ids for part in short.removesuffix(" and others").split("; "))   # cut at a source only
    s["sources"].insert(1, {"id": "x" * 60, "licence": "CC0"})                           # never inside a name
    assert maps.ledger_fields(s)["source_short"] == "Natural Earth and others"
    one = {"id": "M", "sources": [{"id": "N" * 90, "licence": "CC0"}]}                     # one source alone too long
    assert maps.source_short(one) == "N" * maps.SOURCE_SHORT_MAX


def test_the_frames_pixels_do_not_depend_on_the_credit():
    """By pixels: changing every word of the data credit, and where a source line would sit, changes
    nothing in the frame. A drawn credit would move pixels in the lower-left band."""
    a, info = maps.render_map(spec(), GEO)
    other = spec()
    other["sources"][1]["id"] = "GeoNames (CC BY 4.0)"
    other["sources"].append({"id": "a much longer citation:page 412 to 419", "licence": "CC BY 4.0"})
    other["source_at"] = {"x": 0.05, "baseline": 0.94}
    b, info_b = maps.render_map(other, GEO)
    assert info["source_line"] != info_b["source_line"]
    assert np.array_equal(np.asarray(a), np.asarray(b))
    assert not [x for x in info["boxes"] + info_b["boxes"] if x["kind"] in ("source", "note")]
    assert not [x for x in info_b["boxes"] if "Data" in x["text"] or "CC" in x["text"]]


def _render_cli(tmp_path, s: dict) -> tuple[Path, dict]:
    (tmp_path / "specs").mkdir(exist_ok=True)
    sp = tmp_path / "specs" / f"{s['id']}.json"
    sp.write_text(json.dumps(s), encoding="utf-8")
    out = tmp_path / "drawn"
    assert maps.main([str(sp), "--geodata", str(GEO), "--out", str(out)]) == 0
    rec = next(r for r in json.loads((out / "maps-render.json").read_text(encoding="utf-8")) if r["id"] == s["id"])
    return out / f"{s['id']}.png", rec


def _item(png: Path, rec: dict, **over) -> dict:
    """A drawn-ledger item as make_drawn.py writes it: the engine's credit copied from the render record."""
    led = rec["ledger"]
    it = {"id": rec["id"], "file": png.name, "_path": str(png), "generator": "studio.engine.maps from specs",
          **{k: led[k] for k in maps.CREDIT_KEYS}}
    it.update(over)
    return it


def _problems(png: Path, rec: dict, record: dict, **over) -> list[str]:
    return maps.drawn_map_problems(_item(png, rec, **over), record, maps.pixels_sha256(Image.open(png)),
                                   maps.spec_sha256(maps.record_spec(_item(png, rec), rec)))


def test_the_cli_records_the_text_it_drew_its_spec_and_no_credit(tmp_path):
    png, rec = _render_cli(tmp_path, spec())
    assert rec["kind"] == "map"
    assert {"kind": "place", "text": "Alpha"} in [{"kind": d["kind"], "text": d["text"]} for d in rec["drawn_text"]]
    assert not [d for d in rec["drawn_text"] if d["kind"] in ("source", "note") or d["text"].startswith("Data")]
    assert not Path(rec["spec"]).is_absolute()                 # relative to the record's folder: a film moves whole
    assert rec["spec_sha256"] == maps.spec_sha256(maps.record_spec(_item(png, rec), rec))
    assert maps.drawn_check(_item(png, rec)) == []


def test_the_cli_merges_records_by_id(tmp_path):
    a = spec()
    b = spec()
    b["id"] = "FX2"
    _render_cli(tmp_path, a)
    _render_cli(tmp_path, b)
    _render_cli(tmp_path, a)                                    # rendering one spec again keeps the other's record
    rows = json.loads((tmp_path / "drawn" / "maps-render.json").read_text(encoding="utf-8"))
    assert sorted(r["id"] for r in rows) == ["FX1", "FX2"]


def test_a_map_png_from_before_a56_is_refused(tmp_path):
    """Real World's D-EUR: a record with no drawn_text is an engine that drew the credit in the frame."""
    png, rec = _render_cli(tmp_path, spec())
    probs = _problems(png, rec, {k: v for k, v in rec.items() if k != "drawn_text"})
    assert len(probs) == 1 and "before A56" in probs[0]


@pytest.mark.parametrize("drawn_text", [{"a": 1}, "Brussels", None])
def test_a_malformed_drawn_text_reads_as_before_a56(tmp_path, drawn_text):
    png, rec = _render_cli(tmp_path, spec())
    assert any("before A56" in p for p in _problems(png, rec, dict(rec, drawn_text=drawn_text)))


def test_a_record_listing_a_drawn_credit_is_refused(tmp_path):
    png, rec = _render_cli(tmp_path, spec())
    bad = copy.deepcopy(rec)
    bad["drawn_text"] += [{"kind": "source", "text": "Data: Natural Earth; GeoNames (CC BY 4.0)"},
                          {"kind": "figure", "text": "Natural Earth 1:10m"}, None]
    probs = _problems(png, rec, bad)
    assert any("Data: Natural Earth" in p for p in probs) and any("1:10m" in p for p in probs)


def test_a_png_that_is_not_the_recorded_render_is_refused(tmp_path):
    png, rec = _render_cli(tmp_path, spec())
    im = Image.open(png).convert("RGB")
    im.putpixel((100, 1055), (237, 226, 207))          # one pixel of credit-coloured text in the old source band
    im.save(png)
    assert any("pixels" in p for p in maps.drawn_check(_item(png, rec)))


def test_a_spec_edited_since_the_render_is_refused(tmp_path):
    png, rec = _render_cli(tmp_path, spec())
    sp = maps.record_spec(_item(png, rec), rec)
    edited = json.loads(sp.read_text(encoding="utf-8"))
    edited["places"][0]["name"] = "Alpha East"
    sp.write_text(json.dumps(edited), encoding="utf-8")
    assert any("not the one this PNG was drawn from" in p for p in maps.drawn_check(_item(png, rec)))
    old = {k: v for k, v in rec.items() if k != "spec_sha256"}
    assert any("no spec_sha256" in p for p in _problems(png, rec, old))


@pytest.mark.parametrize("key,value", [("licence", "CC0"), ("licence_note", None), ("source_line", None),
                                       ("credit", None), ("data_sources", None)])
def test_a_ledger_item_without_the_engines_credit_is_refused(tmp_path, key, value):
    """Real World's D-EUR ledger said CC0 with no licence note or source line, so the GeoNames CC BY 4.0
    attribution reached neither sources.json nor description.txt."""
    s = spec()
    s["sources"][1] = {"id": "GeoNames (CC BY 4.0)", "licence": "CC BY 4.0", "url": "https://www.geonames.org/"}
    png, rec = _render_cli(tmp_path, s)
    assert rec["ledger"]["licence"] == "CC-BY-4.0"
    assert any(key in p for p in maps.drawn_check(_item(png, rec, **{key: value})))


def test_a_map_item_with_no_render_record_is_refused(tmp_path):
    png, rec = _render_cli(tmp_path, spec())
    (png.parent / "maps-render.json").unlink()
    probs = maps.drawn_check(_item(png, rec))
    assert probs and "maps-render.json" in probs[0]


# ---- what a drawn picture is: fail closed (review of PR #80, blocker 2) --------------------------------------------

def _png(tmp_path, name="D-X.png") -> Path:
    png = tmp_path / name
    Image.new("RGB", (64, 36), (10, 20, 30)).save(png)
    return png


def test_a_drawn_picture_nothing_identifies_is_refused(tmp_path):
    """A stale map renamed, with a hand-written generator and no record, must not pass as 'not a map'."""
    png = _png(tmp_path)
    item = {"id": "D-X", "_path": str(png), "generator": "void document studio map of the Punjab"}
    assert maps.drawn_kind(item) == (None, None)
    probs = maps.drawn_check(item)
    assert probs and "nothing says what this drawn picture is" in probs[0]
    assert maps.drawn_check(item, shot_kind="archive_still") == []      # an archive still is read only as a map


def test_a_page_is_known_by_its_page_record_or_its_declaration(tmp_path):
    png = _png(tmp_path, "D-METAR.png")
    item = {"id": "D-METAR", "_path": str(png), "generator": "metar_pages.py"}
    (tmp_path / "metar-pages.json").write_text(json.dumps({"D-METAR": {"file": "D-METAR.png"}}), encoding="utf-8")
    assert maps.drawn_kind(item)[0] == "page" and maps.drawn_check(item) == []
    (tmp_path / "metar-pages.json").write_text(json.dumps({"D-OTHER": {}}), encoding="utf-8")
    assert maps.drawn_check(item)                                        # a record for another id says nothing
    assert maps.drawn_check(dict(item, drawn_kind="page")) == []


def test_an_engine_generator_is_a_map_whatever_the_record_says(tmp_path):
    png = _png(tmp_path)
    px = maps.pixels_sha256(Image.open(png))
    for kind in ("locator", "count_card", "page"):
        (tmp_path / "maps-render.json").write_text(json.dumps([{"id": "D-X", "kind": kind, "pixels_sha256": px}]),
                                                   encoding="utf-8")
        item = {"id": "D-X", "_path": str(png), "generator": "studio.engine.maps from specs/D-X.json"}
        assert maps.drawn_kind(item)[0] == "map"
        assert any("before A56" in p for p in maps.drawn_check(item))


def test_only_a_count_card_record_is_exempt(tmp_path):
    png = _png(tmp_path)
    item = {"id": "D-X", "_path": str(png), "generator": "studio/engine/counts.py from specs/D-X.json"}
    (tmp_path / "maps-render.json").write_text(json.dumps([{"id": "D-X", "kind": "count_card"}]), encoding="utf-8")
    assert maps.drawn_kind(item)[0] == "count_card" and maps.drawn_check(item) == []
    (tmp_path / "maps-render.json").write_text(json.dumps([{"id": "D-X", "kind": "locator"}]), encoding="utf-8")
    assert maps.drawn_kind(item)[0] == "map" and maps.drawn_check(item)


@pytest.mark.parametrize("generator,is_map", [
    ("studio.engine.maps from x", True), ("python -m studio.engine.maps", True), ("studio/engine/maps.py", True),
    ("studio\\engine\\maps.py", True), ("drawn/road-maps.py", False), ("drawn/metar_pages.py", False),
    ("engine.maps_v2", False), ("the house maps CLI", False)])
def test_the_engine_generator_pattern(generator, is_map):
    assert bool(maps.MAP_GENERATOR.search(generator)) is is_map


def test_untrusted_ids_and_text_are_reported_as_data(tmp_path):
    """Problems are journal strings, never markup: an id or drawn text from a file is quoted with repr."""
    png, rec = _render_cli(tmp_path, spec())
    bad = copy.deepcopy(rec)
    bad["drawn_text"].append({"kind": "label", "text": XSS + " CC0"})
    assert any(repr(XSS + " CC0") in p for p in _problems(png, rec, bad, id=XSS))
    assert repr(XSS) in maps.drawn_check({"id": XSS, "_path": str(_png(tmp_path))})[0]


# ---- the plate and the description (M5, CC BY 4.0) ------------------------------------------------------------------

def test_a_maps_plate_names_no_dataset(tmp_path):
    from studio.engine import disclosure as DS
    from studio.engine import render as R
    png, rec = _render_cli(tmp_path, spec())
    item = _item(png, rec, source_short="Natural Earth; GeoNames")
    shot = {"mark": "DRAWN", "data_source": "Natural Earth; GeoNames"}
    label = R.mark_label(shot, item)
    assert label.endswith("from map data") and "Natural" not in label and "GeoNames" not in label
    assert R.mark_detail(shot, item) == "from map data"
    assert DS.meta_text_problems(label, "map") == []
    assert DS.meta_text_problems("Drawn · from Natural Earth; GeoNames", "map")     # the old plate is refused
    page = {"id": "D-METAR", "source_short": "NWS observations, 2001"}               # pages wait for the M5 sweep
    assert R.mark_detail(shot | {"data_source": None}, page) == "from NWS observations, 2001"


def test_the_description_attributes_a_cc_by_map_by_uri_and_url_never_by_id():
    from studio.engine import description as D
    src = {"title": "F", "slug": "f", "readings": [], "shots": [{
        "id": "6.14", "ledger_id": "D-EUR", "mark": {"class": "DRAWN"}, "title": None, "archive": "void document studio",
        "licence": "CC-BY-4.0", "licence_note": "contains GeoNames data (CC BY 4.0); Natural Earth public domain",
        "source_line": "Data: Natural Earth; GeoNames (CC BY 4.0)",
        "data_sources": [{"id": "Natural Earth", "licence": "public domain", "url": "https://www.naturalearthdata.com/"},
                         {"id": "GeoNames (CC BY 4.0)", "licence": "CC BY 4.0", "url": "https://www.geonames.org/"}]}]}
    t = D.description_text(src)
    line = next(ln for ln in t.splitlines() if "GeoNames, https://www.geonames.org/" in ln)
    assert "https://creativecommons.org/licenses/by/4.0/" in line and line.startswith("A drawn map")
    assert "D-EUR" not in t
    assert D.licence_uri("CC BY-SA 4.0") == "https://creativecommons.org/licenses/by-sa/4.0/"
    assert D.licence_uri("public domain") is None


# ---- the film render's plan ------------------------------------------------------------------------------------------

def _film_with_map(tmp_path, *, stale: bool = False, shot_kind: str = "drawn", **item_over) -> Path:
    """The fixture film with S5 as a drawn map: the fixture spec rendered by the CLI into the film's stills folder,
    its ledger item written as make_drawn.py writes one (the engine's credit copied from the render record)."""
    from conftest import make_film
    film = make_film(tmp_path / "fixture")
    s = spec()
    s["id"] = "D-FX1"
    sp = tmp_path / "D-FX1.json"
    sp.write_text(json.dumps(s), encoding="utf-8")
    assert maps.main([str(sp), "--geodata", str(GEO), "--out", str(film / "stills")]) == 0
    report = film / "stills" / "maps-render.json"
    rec = json.loads(report.read_text(encoding="utf-8"))[0]
    if stale:                                           # as Real World's D-EUR record: no list of the drawn text
        report.write_text(json.dumps([{k: v for k, v in rec.items() if k != "drawn_text"}]), encoding="utf-8")
    led_path = film / "stills-ledger.json"
    led = json.loads(led_path.read_text(encoding="utf-8"))
    item = {"id": "D-FX1", "file": "D-FX1.png", "title": "A fixture map (drawn map)", "date": "2026",
            "creator": "void document studio", "archive": "void document studio", "item_url": None,
            "generator": "studio.engine.maps from D-FX1.json", "synthetic": True, "test_fixture": True,
            "content_date": "1947", "content_basis": "the fixture's own geography", "people": False,
            "shows_bodies": False, "basis": "studio-made map", **{k: rec["ledger"][k] for k in maps.CREDIT_KEYS}}
    item.update(item_over)
    led["items"].append(item)
    led_path.write_text(json.dumps(led), encoding="utf-8")
    play_path = film / "screenplay.json"
    play = json.loads(play_path.read_text(encoding="utf-8"))
    s5 = next(x for p in play["parts"] for x in p["shots"] if x["id"] == "S5")
    s5.update(kind=shot_kind, asset="D-FX1", fill_ok=True, mark="DRAWN")
    s5.pop("fill_exception", None)
    play_path.write_text(json.dumps(play), encoding="utf-8")
    return film


def _map_lint(film, name):
    from studio.engine import journal as J
    from studio.engine import render as R
    j = J.Journal(film=name)
    err = None
    try:
        R.build_plan(film, W=640, H=360, burn_subtitles=False, journal=j)
    except R.Refused as e:
        err = str(e)
    return [e for e in J.read(j.path) if e.get("rule") == "drawn-map-current"], err


def test_the_render_takes_a_map_the_engine_drew(tmp_path):
    evs, err = _map_lint(_film_with_map(tmp_path), "a56-map-ok")
    assert [(e["unit"], e["status"]) for e in evs] == [("S5", "pass")]
    assert err is None or "drawn-map-current" not in err


def test_the_render_refuses_a_map_drawn_before_a56(tmp_path):
    """Real World 6.14 (D-EUR): the PNG of 2026-10-18 printed the credit; the plan now refuses it."""
    evs, err = _map_lint(_film_with_map(tmp_path, stale=True), "a56-map-stale")
    assert [(e["unit"], e["status"]) for e in evs] == [("S5", "fail")]
    assert err and "drawn-map-current (S5)" in err


def test_the_render_refuses_a_map_whose_ledger_drops_the_cc_by_credit(tmp_path):
    evs, err = _map_lint(_film_with_map(tmp_path, licence="CC-BY-4.0", licence_note=None), "a56-map-credit")
    assert [(e["unit"], e["status"]) for e in evs] == [("S5", "fail")]
    assert err and "drawn-map-current (S5)" in err


def test_the_render_refuses_a_stale_map_cited_as_an_archive_still(tmp_path):
    """Review of PR #80, blocker 1: a map cited by an archive_still shot marked DRAWN is still a map."""
    evs, err = _map_lint(_film_with_map(tmp_path, stale=True, shot_kind="archive_still"), "a56-map-still")
    assert [(e["unit"], e["status"]) for e in evs] == [("S5", "fail")]
    assert err and "drawn-map-current (S5)" in err


def test_the_render_refuses_a_drawn_picture_nothing_identifies(tmp_path):
    """Review of PR #80, blocker 2: no record, a hand-written generator: refused, not waved through."""
    film = _film_with_map(tmp_path, generator="void document studio map of the fixture")
    (film / "stills" / "maps-render.json").unlink()
    evs, err = _map_lint(film, "a56-map-unknown")
    assert [(e["unit"], e["status"]) for e in evs] == [("S5", "fail")]
    assert err and "nothing says what this drawn picture is" in err


def test_the_plan_labels_a_map_from_map_data(tmp_path):
    from studio.engine import journal as J
    from studio.engine import render as R
    plan = R.build_plan(_film_with_map(tmp_path), W=640, H=360, burn_subtitles=False, journal=J.Journal(film="a56-lbl"))
    s5 = next(s for s in plan["shots"] if s["id"] == "S5")
    assert s5["label"].endswith("from map data") and s5["detail"] == "from map data"


def test_a_records_spec_falls_back_to_the_ledgers_source_file(tmp_path):
    png, rec = _render_cli(tmp_path, spec())
    sp = maps.record_spec(_item(png, rec), rec)
    no_spec = {k: v for k, v in rec.items() if k != "spec"}
    assert maps.record_spec(_item(png, rec, source_file=str(sp)), no_spec) == sp
    assert maps.record_spec(_item(png, rec), no_spec) is None


@pytest.mark.parametrize("shot_kind,mark,synthetic,refused", [
    ("drawn", None, False, True),
    ("archive_still", "DRAWN", False, True),          # review round 2, r3: a DRAWN still is a drawn picture
    ("archive_still", "ARCHIVE", True, True),         # a program-made item is drawn whatever its mark says
    ("archive_still", "ARCHIVE", False, False),       # a photograph from an archive is not read
])
def test_an_unidentified_picture_is_refused_when_anything_says_it_is_drawn(tmp_path, shot_kind, mark, synthetic, refused):
    item = {"id": "D-X", "_path": str(_png(tmp_path)), "generator": "void document studio map"}
    probs = maps.drawn_check(item, shot_kind=shot_kind, mark=mark, synthetic=synthetic)
    assert bool(probs) is refused


@pytest.mark.parametrize("over", [{"generator": "void document studio map"}, {"generator": "studio maps by hand"},
                                  {"file": "D-europe-map.png"}])
@pytest.mark.parametrize("declared", ["page", "image"])
def test_a_declared_page_or_image_that_says_map_is_refused(tmp_path, over, declared):
    """Review round 2, r4: `drawn_kind: "page"` is no way round the map check."""
    name = over.get("file", "D-X.png")
    item = {"id": "D-X", "_path": str(_png(tmp_path, name)), "drawn_kind": declared,
            "generator": over.get("generator", "tools/doc_pages.py")}
    probs = maps.drawn_check(item, shot_kind="drawn", mark="DRAWN")
    assert probs and "says it is a map" in probs[0]


def test_a_declared_image_or_page_otherwise_passes(tmp_path):
    for declared in ("page", "image"):
        item = {"id": "D-X", "_path": str(_png(tmp_path)), "drawn_kind": declared, "generator": "make_media.py stills()"}
        assert maps.drawn_check(item, shot_kind="drawn", mark="DRAWN", synthetic=True) == []


def test_the_render_refuses_an_unrecorded_map_cited_as_a_drawn_archive_still(tmp_path):
    """Review round 2, r3: no record, a hand-written generator, an archive_still marked DRAWN: refused."""
    film = _film_with_map(tmp_path, shot_kind="archive_still", generator="void document studio map")
    (film / "stills" / "maps-render.json").unlink()
    evs, err = _map_lint(film, "a56-map-r3")
    assert [(e["unit"], e["status"]) for e in evs] == [("S5", "fail")]
    assert err and "nothing says what this drawn picture is" in err


def test_the_fixture_films_own_stills_pass_as_declared_images(tmp_path):
    film = _film_with_map(tmp_path)
    evs, err = _map_lint(film, "a56-fixture-images")
    assert [(e["unit"], e["status"]) for e in evs] == [("S5", "pass")]          # S3, S4 are images: not journaled
