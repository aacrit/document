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


def spec() -> dict:
    return json.loads((FIX / "spec.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rendered():
    return maps.render_map(spec(), FIX)


def test_a_map_is_a_1920x1080_rgb_frame(rendered):
    img, info = rendered
    assert img.size == (1920, 1080) and img.mode == "RGB"
    assert info["size"] == [1920, 1080]


def test_a_map_renders_the_same_bytes_twice(rendered):
    img, _ = rendered
    again, _ = maps.render_map(spec(), FIX)
    a, b = maps.png_bytes(img), maps.png_bytes(again)
    assert hashlib.sha256(a).hexdigest() == hashlib.sha256(b).hexdigest()


def test_the_frame_carries_its_source_line(rendered):
    img, info = rendered
    assert info["source_line"] == "Data: Natural Earth; fixture-src:p1"
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
        maps.render_map(s, FIX)


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
    a, _ = maps.render_map(spec(), FIX)
    b, _ = maps.render_map(spec(), FIX, tokens=alt)
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
        maps.render_map(s, FIX)


def test_a_colour_literal_in_spec_text_is_refused():
    s = spec()
    s["notes"] = ["drawn in #2f5fa8"]
    with pytest.raises(maps.MapRefused):
        maps.render_map(s, FIX)


def test_an_em_dash_in_on_screen_copy_is_refused():
    s = spec()
    s["title"] = "A map — of nothing"
    with pytest.raises(maps.MapRefused, match="em dash"):
        maps.render_map(s, FIX)


def test_an_unknown_style_is_refused():
    s = spec()
    s["layers"][0]["style"] = "glow"
    with pytest.raises(maps.MapRefused, match="style"):
        maps.render_map(s, FIX)


def test_text_never_enters_the_mark_plate_zone():
    s = spec()
    s["labels"].append({"text": "In the mark zone", "style": "note", "lon": 9.6, "lat": 14.1})
    with pytest.raises(maps.MapRefused, match="mark zone"):
        maps.render_map(s, FIX)


def test_text_never_enters_the_watermark_zone():
    s = copy.deepcopy(spec())
    for k in ("title", "legend", "notes"):
        s.pop(k)
    s["extent"] = [12.0, 12.0, 14.8, 14.2]
    s["frame"] = [0.5, 0.02, 0.98, 0.5]
    s["labels"].append({"text": "Under the watermark", "style": "note", "lon": 14.7, "lat": 14.15, "align": "r"})
    with pytest.raises(maps.MapRefused, match="watermark zone"):
        maps.render_map(s, FIX)


def test_a_layer_that_matches_nothing_is_refused():
    s = spec()
    s["layers"][2]["where"] = {"name": "No such river"}
    with pytest.raises(maps.MapRefused, match="matched nothing"):
        maps.render_map(s, FIX)


def test_a_clipped_line_keeps_only_the_part_inside_the_box():
    parts = maps.clip_line([[0.0, 0.0], [2.0, 0.0], [2.0, 2.0]], [1.0, -1.0, 3.0, 1.0])
    assert parts == [[(1.0, 0.0), (2.0, 0.0), (2.0, 1.0)]]


def test_two_views_render_side_by_side():
    s = spec()
    view = {k: s.pop(k) for k in ("extent", "layers", "places", "labels")}
    s["views"] = [{**view, "name": "a", "frame": [0.04, 0.25, 0.35, 0.9]},
                  {**view, "name": "b", "frame": [0.36, 0.25, 0.68, 0.9]}]
    img, info = maps.render_map(s, FIX)
    assert img.size == (1920, 1080)
    assert sum(1 for b in info["boxes"] if b["text"] == "Alpha") == 2
