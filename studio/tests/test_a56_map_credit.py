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
    rec = json.loads((out / "maps-render.json").read_text(encoding="utf-8"))[0]
    return out / f"{s['id']}.png", rec


def _item(png: Path, rec: dict, **over) -> dict:
    """A drawn-ledger item as make_drawn.py writes it: the engine's credit copied from the render record."""
    led = rec["ledger"]
    it = {"id": rec["id"], "file": png.name, "_path": str(png), "generator": "studio.engine.maps from specs",
          **{k: led[k] for k in maps.CREDIT_KEYS}}
    it.update(over)
    return it


def test_the_cli_records_the_text_it_drew_and_no_credit(tmp_path):
    png, rec = _render_cli(tmp_path, spec())
    assert rec["kind"] == "map"
    assert {"kind": "place", "text": "Alpha"} in [{"kind": d["kind"], "text": d["text"]} for d in rec["drawn_text"]]
    assert not [d for d in rec["drawn_text"] if d["kind"] in ("source", "note") or d["text"].startswith("Data")]
    assert maps.drawn_map_check(_item(png, rec)) == []


def test_a_map_png_from_before_a56_is_refused(tmp_path):
    """Real World's D-EUR: a record with no drawn_text is an engine that drew the credit in the frame."""
    png, rec = _render_cli(tmp_path, spec())
    old = {k: v for k, v in rec.items() if k != "drawn_text"}
    probs = maps.drawn_map_problems(_item(png, rec), old, maps.pixels_sha256(Image.open(png)))
    assert probs and "before A56" in probs[0]


def test_a_record_listing_a_drawn_credit_is_refused(tmp_path):
    png, rec = _render_cli(tmp_path, spec())
    bad = copy.deepcopy(rec)
    bad["drawn_text"].append({"kind": "source", "text": "Data: Natural Earth; GeoNames (CC BY 4.0)"})
    probs = maps.drawn_map_problems(_item(png, rec), bad, maps.pixels_sha256(Image.open(png)))
    assert any("Data: Natural Earth" in p for p in probs)


def test_a_png_that_is_not_the_recorded_render_is_refused(tmp_path):
    png, rec = _render_cli(tmp_path, spec())
    im = Image.open(png).convert("RGB")
    im.putpixel((100, 1055), (237, 226, 207))          # one pixel of credit-coloured text in the old source band
    im.save(png)
    probs = maps.drawn_map_check(_item(png, rec))
    assert any("pixels" in p for p in probs)


@pytest.mark.parametrize("key,value", [("licence", "CC0"), ("licence_note", None), ("source_line", None)])
def test_a_ledger_item_without_the_engines_credit_is_refused(tmp_path, key, value):
    """Real World's D-EUR ledger said CC0 with no licence note or source line, so the GeoNames CC BY 4.0
    attribution reached neither sources.json nor description.txt."""
    s = spec()
    s["sources"][1] = {"id": "GeoNames (CC BY 4.0)", "licence": "CC BY 4.0"}
    png, rec = _render_cli(tmp_path, s)
    assert rec["ledger"]["licence"] == "CC-BY-4.0"
    probs = maps.drawn_map_check(_item(png, rec, **{key: value}))
    assert any(key in p for p in probs)


def test_a_map_item_with_no_render_record_is_refused(tmp_path):
    png, rec = _render_cli(tmp_path, spec())
    (png.parent / "maps-render.json").unlink()
    probs = maps.drawn_map_check(_item(png, rec))
    assert probs and "maps-render.json" in probs[0]


def test_a_drawn_page_that_is_not_a_map_is_not_checked(tmp_path):
    """A METAR or cable page the film draws by its own script has no map record and is not a map."""
    png = tmp_path / "D-METAR.png"
    Image.new("RGB", (1920, 1080)).save(png)
    assert maps.drawn_map_check({"id": "D-METAR", "_path": str(png), "generator": "metar_pages.py"}) == []


def test_untrusted_ids_and_text_are_reported_as_data(tmp_path):
    """Problems are journal strings, never markup: an id or drawn text from a file is quoted with repr."""
    png, rec = _render_cli(tmp_path, spec())
    bad = copy.deepcopy(rec)
    bad["drawn_text"].append({"kind": "label", "text": XSS + " CC0"})
    probs = maps.drawn_map_problems(_item(png, rec, id=XSS), bad, maps.pixels_sha256(Image.open(png)))
    assert any(repr(XSS + " CC0") in p for p in probs)


# ---- the film render's plan ------------------------------------------------------------------------------------------

def _film_with_map(tmp_path, *, stale: bool = False, **item_over) -> Path:
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
    s5.update(kind="drawn", asset="D-FX1", fill_ok=True)
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
