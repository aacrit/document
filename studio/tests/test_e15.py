"""E15 (brand audit of film 2, "Nought"): cards never cut their text, dips hold
black for at least 2 frames, lower thirds stay up long enough to read, the
credits print a year once, a source line takes no comma after "?" or "!", the
kit's watermark and logomark are the engine's, and a map frame never names the
studio's own files."""

from __future__ import annotations

import ast
import importlib.util
import json
import re
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from conftest import ROOT, make_film
from studio.engine import journal as J
from studio.engine import maps as MP
from studio.engine import motion as M
from studio.engine import render as R

FONTS = M.Fonts()
L1080 = M.Layout(1920, 1080)
L720 = M.Layout(1280, 720)

CARD_D = [
    "The record holds no open-licence words of anyone who had smallpox, or of any vaccinator, searcher or official of "
    "India, Bangladesh, Ethiopia, Somalia, West Africa or the Soviet Union.",
    "Searched: CDC Public Health Image Library, National Library of Medicine, Internet Archive, Wikimedia Commons, "
    "Hansard; the CDC Museum oral histories are held until their status is confirmed.",
    "The readings and recordings in this film are about 14 percent of its running time, under a fifth the grammar asks, "
    "and only 18 percent of them is a woman's voice. The film says so rather than invent.",
]
QUOTE = ("As of April 14, 1978, no cases of smallpox have been reported to the World Health Organization (WHO) from anywhere "
         "in the world since the last case had onset of rash on October 26, 1977, in Merka town, Somalia.")


def lints(j, rule):
    return [e for e in J.read(j.path) if e["kind"] == "lint" and e.get("rule") == rule]


def _edit(film: Path, fn, name="screenplay.json"):
    data = json.loads((film / name).read_text(encoding="utf-8"))
    fn(data)
    (film / name).write_text(json.dumps(data), encoding="utf-8")


def _shot(play, sid):
    return next(s for p in play["parts"] for s in p["shots"] if s["id"] == sid)


def _plan(film, name="e15"):
    j = J.Journal(film=name)
    return R.build_plan(film, W=640, H=360, burn_subtitles=False, journal=j), j


# --------------------------------------------------------------------------
# 1. No silent truncation
# --------------------------------------------------------------------------


def test_wrap_keeps_every_word_and_refuses_past_its_limit():
    f = M._font(FONTS.display, L1080.px(M.SILENT["size"]))
    lines = M._wrap(QUOTE, f, None, L1080.w(M.SILENT["max_w"]))
    assert len(lines) == 3 and " ".join(lines) == QUOTE                     # the G2 wrap kept 2 of these 3 lines
    with pytest.raises(M.TextOverflow, match="wraps to 3 lines; at most 2"):
        M._wrap(QUOTE, f, None, L1080.w(M.SILENT["max_w"]), max_lines=2)


@pytest.mark.parametrize("L", [L1080, L720], ids=["1080p", "720p"])
def test_card_d_draws_all_three_elements_word_for_word(L):
    lay = M.card_layout(L, CARD_D, FONTS)
    assert [e["index"] for e in lay["elements"]] == [0, 1, 2]
    assert M.card_drawn_text(lay) == [" ".join(x.split()) for x in CARD_D]
    assert M.card_text_problems(CARD_D, lay) == []
    assert lay["top"] >= L.h(M.SILENT["safe_top"]) and lay["bottom"] <= L.h(M.SILENT["safe_bottom"])
    for e in lay["elements"]:
        for ln in e["lines"]:
            assert ln["w"] <= L.w(M.SILENT["max_w"]) + 0.5


def test_card_d_frame_shows_its_third_element():
    img = M.silent_card_frame(Image.new("RGB", (1280, 720)), 8.0, start=0.0, end=16.0, texts=CARD_D, fonts=FONTS)
    lay = M.card_layout(L720, CARD_D, FONTS)
    third = lay["elements"][2]["lines"]
    arr = np.asarray(img.convert("RGB"), dtype=int)
    top = int(third[0]["baseline"] - third[0]["w"] * 0 - lay["elements"][2]["px"])
    bottom = int(third[-1]["baseline"] + 4)
    assert arr[top:bottom].max() > 100                                       # the shortfall sentence is on the frame
    assert arr[bottom + 8:].max() == 0                                       # and nothing below it


def test_the_layout_records_catch_a_card_that_drops_an_element():
    lay = M.card_layout(L1080, CARD_D, FONTS)
    cut = dict(lay, elements=lay["elements"][:2])                           # what the G2 card drew of card D
    probs = M.card_text_problems(CARD_D, cut)
    assert [p["index"] for p in probs] == [2] and probs[0]["drawn"] is None
    trimmed = dict(lay, elements=[dict(lay["elements"][0], lines=lay["elements"][0]["lines"][:2])] + lay["elements"][1:])
    assert [p["index"] for p in M.card_text_problems(CARD_D, trimmed)] == [0]   # a quote that lost its end


def test_a_card_too_long_for_the_safe_band_steps_down_then_refuses():
    long = " ".join([QUOTE] * 6)
    lay = M.card_layout(L1080, [long, "Source, 1978"], FONTS)
    assert M.SILENT["min_scale"] <= lay["scale"] < 1.0                       # smaller type, every word kept
    assert M.card_text_problems([long, "Source, 1978"], lay) == []
    assert L720.px(M.SILENT["size"] * M.SILENT["min_scale"]) >= 21            # the floor stays readable at 720p
    assert L720.px(M.SILENT["searched"] * M.SILENT["min_scale"]) >= 14
    with pytest.raises(M.TextOverflow, match="do not fit the card at the smallest readable size"):
        M.card_layout(L1080, [" ".join([QUOTE] * 10)], FONTS)


def test_a_card_that_always_fitted_keeps_the_g2_arithmetic():
    """At scale 1 the layout is the G2 card's formula, so Partition's cards keep their pixels."""
    texts = ["Those who stayed", "1947 to today"]
    lay = M.card_layout(L1080, texts, FONTS)
    f1 = M._font(FONTS.display, L1080.px(M.SILENT["size"]))
    f2 = M._font(FONTS.structure, L1080.px(M.SILENT["searched"]))
    h1, h2 = f1.size * M.SILENT["lh"], f2.size * 1.4 + L1080.h(1.2)
    y = (L1080.H - h1 - h2) / 2.0
    assert lay["scale"] == 1.0
    assert lay["elements"][0]["lines"][0]["baseline"] == y + f1.size * (0.78 + (M.SILENT["lh"] - 1) / 2)
    assert lay["elements"][1]["lines"][0]["baseline"] == y + h1 + L1080.h(1.2) + f2.size * (0.78 + 0.2)
    a = M.silent_card_frame(Image.new("RGB", (1920, 1080)), 2.0, start=0.0, end=4.0, statement=texts[0],
                            searched=texts[1], fonts=FONTS)
    b = M.silent_card_frame(Image.new("RGB", (1920, 1080)), 2.0, start=0.0, end=4.0, texts=texts, fonts=FONTS)
    assert np.array_equal(np.asarray(a), np.asarray(b))


def test_the_plan_refuses_an_overflowing_card_and_an_undrawn_element(tmp_path):
    film = make_film(tmp_path / "film")
    _edit(film, lambda p: _shot(p, "S7").update(text=["The record holds no " + " ".join([QUOTE] * 10) + "."]))
    with pytest.raises(R.Refused, match=r"card-fits \(S7\)"):
        _plan(film, "e15-overflow")
    _edit(film, lambda p: _shot(p, "S7").update(text=["The record holds no open-licence film of this fixture."]))
    _edit(film, lambda p: _shot(p, "S2").update(text=["1  The fixture", "1946 to 1950", "A third line no chapter card draws"]))
    with pytest.raises(R.Refused, match=r"card-drawn \(S2\)"):
        _plan(film, "e15-undrawn")


def test_every_card_of_the_fixture_passes_and_is_journaled(tmp_path):
    film = make_film(tmp_path / "film")
    plan, j = _plan(film, "e15-cards")
    units = {e["unit"]: e["status"] for e in lints(j, "card-drawn")}
    assert units == {"S1": "pass", "S2": "pass", "S7": "pass", "S8": "pass", "S9": "pass"}
    assert all(e["status"] == "pass" for e in lints(j, "card-fits"))


# --------------------------------------------------------------------------
# 2. Dips hold black for at least 2 frames
# --------------------------------------------------------------------------


@pytest.mark.parametrize("dur", [0.5, 0.6, 0.75, 1.0])
def test_a_dip_holds_black_for_at_least_two_frames(dur):
    assert M.dip_black_frames(dur, 24) >= M.DIP_HOLD_MIN_FRAMES == 2
    assert M.dip_level(0.0, dur) == 1.0 and M.dip_level(dur, dur) == pytest.approx(1.0)


def test_a_one_second_dip_is_unchanged():
    old_a = 0.5 * (1.0 - 0.10)
    for t in np.linspace(0, 1.0, 97):
        u = t / 1.0
        want = 1.0 - (u / old_a) ** 2 if u < old_a else 0.0 if u <= 1 - old_a else 1 - (1 - (u - (1 - old_a)) / old_a) ** 2
        assert M.dip_level(t, 1.0) == pytest.approx(want, abs=1e-9)


def test_the_renderer_draws_the_dip_hold_black(plan):
    s = next(x for x in plan["shots"] if x["transition_in"].get("type") == "dip" and float(x["transition_in"]["s"]) == 0.5)
    i = plan["shots"].index(s)
    black = [f for f in range(s["f0"] - 6, s["f0"] + 6)
             if R.picture_level(plan, f, i if f >= s["f0"] else i - 1) <= 0.0]
    assert len(black) >= 2


def test_dip_black_hold_is_linted(tmp_path):
    film = make_film(tmp_path / "film")
    _, j = _plan(film, "e15-dip")
    found = lints(j, "dip-black-hold")
    assert found and all(e["status"] == "pass" and e["evidence"]["black_frames"] >= 2 for e in found)


# --------------------------------------------------------------------------
# 3. Lower thirds long enough to read
# --------------------------------------------------------------------------


def _lt(kind, start, end):
    lines = ["Patna, Bihar", "May 1974"] if kind == "place" else \
        ["John Neff", "Assistant Professor of Pediatrics, 1969", "Smallpox vaccination, NLM  ·  original recording"]
    s, e = M.lower_third_span(start, end)
    return {"id": f"LT-{kind}-{end - start:g}", "kind": kind, "lines": lines, "flag": None, "start": s, "end": e}


@pytest.mark.parametrize("kind, dur, ok", [
    ("place", 1.2, False), ("place", 2.5, False), ("place", 3.7, False), ("place", 3.9, True), ("place", 5.0, True),
    ("speaker", 3.5, False), ("speaker", 4.0, True), ("speaker", 5.0, True), ("speaker", 9.0, True),   # 9 s is drawn 5.46 s
])
def test_a_lower_third_is_up_long_enough_to_read(kind, dur, ok):
    plan = {"W": 1280, "H": 720, "lower_thirds": [_lt(kind, 10.0, 10.0 + dur)]}
    j = J.Journal(film="e15-lt")
    out = R.lower_third_time_lints(j, plan)
    assert (out == []) is ok
    e = lints(j, "lower-third-time")[0]
    assert e["severity"] == "block" and (e["status"] == "pass") is ok
    jd = J.Journal(film="e15-lt-draft")
    assert R.lower_third_time_lints(jd, plan, draft=True) == []                     # a warning under --draft
    assert lints(jd, "lower-third-time")[0]["severity"] == "warn"


def test_a_place_lower_third_needs_two_and_a_half_seconds_fully_visible():
    tm = R.lower_third_times(_lt("place", 0.0, 3.9), 1280, 720)
    assert tm["fully_visible_s"] >= R.LT_PLACE_FULL_MIN_S
    assert tm["on_screen_s"] - tm["fully_visible_s"] == pytest.approx(2 * M.LT["stagger"] + M.WHISPER.settle_time()
                                                                      + M.LT["exit"], abs=1e-3)


# --------------------------------------------------------------------------
# 4 and 5. Credits print a year once; a source line takes no comma after ? or !
# --------------------------------------------------------------------------


@pytest.mark.parametrize("title, year, want", [
    ("Smallpox Eradication and Measles Control Program, Niger, 1969", "1969", ""),
    ("D. A. Henderson, J. D. Millar and colleagues, 1966", "1966", ""),
    ("Bihar, 1974", "2026", "2026"),
    ("Miracle in Tonga", "1965", "1965"),
    ("Report of 11969", "1969", "1969"),
    ("Census (1951).", "1951", ""),
    ("Anything", None, ""),
])
def test_the_credits_print_a_year_once(title, year, want):
    assert R.credit_year(title, year) == want


def test_a_source_title_ending_in_a_question_takes_no_comma():
    src = "Smallpox vaccination: should our policy be changed?, National Library of Medicine  ·  original recording"
    assert M.source_line_text(src) == ("Smallpox vaccination: should our policy be changed? National Library of Medicine"
                                       "  ·  original recording")
    assert M.source_line_text("Hold on!, Pathé  ·  original recording").startswith("Hold on! Pathé")
    assert M.source_line_text("Hansard, House of Commons") == "Hansard, House of Commons"
    els, _ = M.lower_third_layout(L1080, ["John Neff", "Professor, 1969", src], FONTS)
    drawn = " ".join(e["text"] for e in els if e["kind"].startswith("source"))
    assert "changed?," not in drawn and "changed? National" in drawn


def test_a_lower_third_source_that_wraps_past_two_lines_is_refused_not_cut():
    long = ", ".join(["A very long source title of the archive"] * 6) + "  ·  original recording"
    with pytest.raises(M.TextOverflow, match="source line"):
        M.lower_third_layout(L1080, ["Name", "Role, 1969", long], FONTS)


# --------------------------------------------------------------------------
# 6. The kit's watermark and logomark are the engine's
# --------------------------------------------------------------------------


def _hex(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _path_points(d):
    """Polyline points of an SVG path that uses M, L, H, V (absolute or relative) only."""
    toks = re.findall(r"[MLHVmlhv]|-?\d*\.?\d+", d)
    pts, x, y, cmd, i = [], 0.0, 0.0, None, 0
    while i < len(toks):
        if re.match(r"[A-Za-z]", toks[i]):
            cmd = toks[i]
            i += 1
            continue
        if cmd in "MLml":
            nx, ny = float(toks[i]), float(toks[i + 1])
            i += 2
            x, y = (x + nx, y + ny) if cmd.islower() else (nx, ny)
        elif cmd in "Hh":
            x = x + float(toks[i]) if cmd == "h" else float(toks[i])
            i += 1
        elif cmd in "Vv":
            y = y + float(toks[i]) if cmd == "v" else float(toks[i])
            i += 1
        pts.append((x, y))
    return pts


def rasterise_svg(path: Path, px: int, ss: int = 8) -> Image.Image:
    """A small rasteriser for the kit's mark files (paths of straight segments
    with round caps and joins, circles, group and stroke opacity): it reads
    the geometry and paint from the SVG itself, independent of motion.py."""
    import xml.etree.ElementTree as ET
    # the kit's comments cite tokens ("--doc-bone"), which XML forbids inside a comment: drop them before parsing
    root = ET.fromstring(re.sub(r"<!--.*?-->", "", path.read_text(encoding="utf-8"), flags=re.S))
    vb = [float(v) for v in root.get("viewBox").split()]
    s = px * ss / vb[2]
    out = Image.new("RGBA", (px * ss, px * ss), (0, 0, 0, 0))

    def layer(rgb, alpha, draw_fn):
        mask = Image.new("L", out.size, 0)
        draw_fn(ImageDraw.Draw(mask))
        a = np.asarray(mask, dtype=np.float32) * alpha
        lay = Image.new("RGBA", out.size, rgb + (0,))
        lay.putalpha(Image.fromarray(a.astype(np.uint8)))
        return lay

    def walk(el, opacity, style):
        tag = el.tag.split("}")[-1]
        style = dict(style, **{k: v for k, v in el.attrib.items() if k in ("fill", "stroke", "stroke-width", "stroke-opacity")})
        if tag == "g":
            group = Image.new("RGBA", out.size, (0, 0, 0, 0))
            for ch in el:
                for lay in walk(ch, 1.0, style):
                    group.alpha_composite(lay)
            if "opacity" in el.attrib:
                a = np.asarray(group.getchannel("A"), dtype=np.float32) * float(el.get("opacity"))
                group.putalpha(Image.fromarray(a.astype(np.uint8)))
            return [group]
        stroke, fill = style.get("stroke", "none"), style.get("fill", "black")
        sw = float(style.get("stroke-width", 1)) * s
        so = float(style.get("stroke-opacity", 1))
        r = sw / 2
        out_layers = []
        if tag == "path" and stroke != "none":
            pts = [(x * s, y * s) for x, y in _path_points(el.get("d"))]

            def draw(dm):
                dm.line(pts, fill=255, width=max(1, int(round(sw))))
                for x, y in pts:
                    dm.ellipse([x - r, y - r, x + r, y + r], fill=255)
            out_layers.append(layer(_hex(stroke), so, draw))
        elif tag == "circle":
            cx, cy, cr = (float(el.get(k)) * s for k in ("cx", "cy", "r"))
            if fill not in ("none",):
                out_layers.append(layer(_hex(fill), 1.0, lambda dm: dm.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], fill=255)))
            if stroke != "none":
                def ring(dm):
                    dm.ellipse([cx - cr - r, cy - cr - r, cx + cr + r, cy + cr + r], fill=255)
                    dm.ellipse([cx - cr + r, cy - cr + r, cx + cr - r, cy + cr - r], fill=0)
                out_layers.append(layer(_hex(stroke), so, ring))
        return out_layers

    for ch in root:
        for lay in walk(ch, 1.0, {}):
            out.alpha_composite(lay)
    return out.resize((px, px), Image.BOX)


def _over(img: Image.Image, grey: int) -> np.ndarray:
    ground = Image.new("RGBA", img.size, (grey, grey, grey, 255))
    ground.alpha_composite(img)
    return np.asarray(ground.convert("RGB"), dtype=int)


@pytest.mark.parametrize("grey", [0, 128, 245])
def test_the_kit_watermark_svg_is_the_engines_watermark(grey):
    """watermark.svg rasterised and the engine's watermark(), settled, over black, grey and a white sky."""
    W, H = 1920, 1080
    L = M.Layout(W, H)
    box = L.px(M.WM["box"])
    frame = M.watermark(Image.new("RGB", (W, H), (grey,) * 3), 60.0, start=0.0)
    x, y = int(round(L.W - L.w(M.WM["right"]) - box)), int(round(L.h(M.WM["top"])))
    engine = np.asarray(frame.convert("RGB"), dtype=int)[y:y + box, x:x + box]
    kit = _over(rasterise_svg(ROOT / "design" / "brand-kit" / "watermark.svg", box), grey)
    diff = np.abs(engine - kit)
    assert diff.mean() < 1.5 and np.percentile(diff, 99) <= 24, (diff.mean(), np.percentile(diff, 99), diff.max())
    # the tolerance is antialiasing only: the G2 values (opacity 0.6, halo 0.35) fail it
    g2 = M.watermark(Image.new("RGB", (W, H), (grey,) * 3), 60.0, start=0.0, opacity=0.6)
    if grey != 245:
        assert np.abs(np.asarray(g2.convert("RGB"), dtype=int)[y:y + box, x:x + box] - kit).mean() > 1.5
    else:
        assert diff.mean() < 1.0 and abs((engine - kit).mean()) < 0.75          # on a white sky the halo is what shows


def test_the_kit_watermark_halo_is_the_engines_halo(monkeypatch):
    """On a white sky only the halo darkens the frame: the G2 halo (0.35) is caught on its own."""
    W, H, grey = 1920, 1080, 245
    L = M.Layout(W, H)
    box = L.px(M.WM["box"])
    x, y = int(round(L.W - L.w(M.WM["right"]) - box)), int(round(L.h(M.WM["top"])))
    kit = _over(rasterise_svg(ROOT / "design" / "brand-kit" / "watermark.svg", box), grey)

    def engine():
        f = M.watermark(Image.new("RGB", (W, H), (grey,) * 3), 60.0, start=0.0)
        return np.asarray(f.convert("RGB"), dtype=int)[y:y + box, x:x + box]

    right = engine()
    monkeypatch.setitem(M.WM, "halo", 0.35)
    halo_g2 = engine()
    assert abs((halo_g2 - kit).mean() - (right - kit).mean()) > 0.8               # the halo's darkening, signed
    assert np.abs(halo_g2 - kit).mean() > np.abs(right - kit).mean() + 0.4


def test_the_kit_logomark_svg_is_the_engines_logomark():
    # compared large, where the two antialiasing filters (Lanczos in the engine, a box here) differ least
    for px in (192, 384):
        engine = _over(M.draw_logomark(px, halo=0.0), 0)
        kit = _over(rasterise_svg(ROOT / "design" / "brand-kit" / "logomark.svg", px), 0)
        diff = np.abs(engine - kit)
        assert diff.mean() < 1.5, (px, diff.mean(), np.percentile(diff, 99))
        moved = _over(M.draw_logomark(px, halo=0.0, spread=0.01), 0)          # corners 1% of the box out of place are caught
        assert np.abs(moved - kit).mean() > 2.5


def test_the_kit_motion_is_a_pure_reexport_of_the_engine():
    spec = importlib.util.spec_from_file_location("kit_motion_e15", ROOT / "design" / "brand-kit" / "motion.py")
    kit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kit)
    for name in ("WM", "LT", "LABEL", "SILENT", "LOGOMARK_CORNERS", "LOGOMARK_RING", "LOGOMARK_EMBER", "LOGOMARK_STROKE",
                 "draw_logomark", "watermark", "dip_level", "card_layout", "lower_third_layout", "PRESETS"):
        assert getattr(kit, name) is getattr(M, name), name
    # the kit file defines nothing of its own: imports, its root path and the CLI guard only
    tree = ast.parse((ROOT / "design" / "brand-kit" / "motion.py").read_text(encoding="utf-8"))
    own = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))]
    assigned = [t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)]
    assert not own and assigned == ["_ROOT"]


# --------------------------------------------------------------------------
# 7. A map frame speaks of the open record, never of the studio's files
# --------------------------------------------------------------------------


def test_a_map_note_naming_the_studios_geodata_is_refused():
    base = json.loads((ROOT / "studio" / "tests" / "fixture" / "maps" / sorted(
        p.name for p in (ROOT / "studio" / "tests" / "fixture" / "maps").glob("*.json"))[0]).read_text(encoding="utf-8"))
    bad = dict(base, notes=["Bihar's state and district boundaries are not drawn: none are in the studio's geodata."])
    with pytest.raises(MP.MapRefused, match="no open source gives them"):
        MP.check_spec(bad)
    good = dict(base, notes=["Bihar's state and district boundaries are not drawn: " + MP.NOT_IN_OPEN_SOURCES + "."])
    MP.check_spec(good)


# --------------------------------------------------------------------------
# E15 review: every renderer that lays out text draws all of it or refuses
# --------------------------------------------------------------------------


def test_a_non_draft_audio_only_run_does_not_refuse_on_screen_time(tmp_path):
    """--audio-only draws no frame: a short place lower third is a warning there, and refuses a final render."""
    film = make_film(tmp_path / "film")
    _edit(film, lambda p: p["parts"][1]["text"].append(
        {"id": "T9", "kind": "lower_third", "start_s": 6.5, "end_s": 7.7, "lines": ["A fixture place", "1947"]}))
    j = J.Journal(film="e15-audio-only")
    s = R.render(film, tmp_path / "out", height=360, workers=1, min_free_gb=1, audio_only=True, journal=j)
    assert s["frames"] == 0
    lt = [e for e in lints(j, "lower-third-time") if e["unit"] == "T9"]
    assert lt and lt[0]["status"] == "fail" and lt[0]["severity"] == "warn"
    plan, _ = _plan(film, "e15-final")
    assert any(o.startswith("lower-third-time (T9") for o in R.lower_third_time_lints(J.Journal(film="e15-final-lt"), plan))


def test_a_chapter_dates_line_too_wide_is_refused_and_recorded_from_the_layout(tmp_path):
    film = make_film(tmp_path / "film")
    dates = "1946 to 1950, " + ", ".join(["and the years of the long aftermath in every district"] * 4)
    _edit(film, lambda p: _shot(p, "S2").update(text=["1  The fixture", dates]))
    with pytest.raises(R.Refused, match=r"card-fits \(S2\).*chapter dates"):
        _plan(film, "e15-dates")
    with pytest.raises(M.TextOverflow, match="chapter dates"):
        M.chapter_card_layout(L1080, 1, "The fixture", dates, FONTS)
    lay = M.chapter_card_layout(L1080, 1, "The fixture", "1946 to 1950", FONTS)
    assert [r["text"] for r in lay["lines"]] == ["1 The fixture", "1946 to 1950"]
    shot = {"id": "S2", "kind": "card", "_card": "chapter", "text": ["1  The fixture", "1946 to 1950"]}
    assert R.card_text_check(shot, 1920, 1080)["missing"] == []


@pytest.mark.parametrize("what", ["name", "overlay", "subtitle"])
def test_a_line_wider_than_its_measure_is_refused_at_plan_time(tmp_path, what):
    film = make_film(tmp_path / "film")
    long = "A name far too long to stand in one line of a lower third, which never wraps a name, at any size"
    if what == "name":
        _edit(film, lambda p: next(t for t in p["parts"][1]["text"] if t["id"] == "T1")["lines"].__setitem__(0, long))
        with pytest.raises(R.Refused, match=r"lower-third-fits \(T1\)"):
            _plan(film, "e15-name")
    elif what == "overlay":
        _edit(film, lambda p: p["parts"][1]["text"].append(
            {"id": "O9", "kind": "overlay", "start_s": 10.5, "end_s": 12.0, "lines": ["14 August 1947, " + long]}))
        with pytest.raises(R.Refused, match=r"overlay-fits \(O9\)"):
            _plan(film, "e15-overlay")
    else:
        _edit(film, lambda p: p["subtitle_source"][0].update(en=long + " " + long))
        ref = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))["subtitle_source"][0]["ref"]
        _plan(film, "e15-sub-tracks")                                             # as a track, the player wraps it
        with pytest.raises(R.Refused, match=rf"subtitle-fits \({re.escape(ref)}\)"):
            R.build_plan(film, W=640, H=360, burn_subtitles=True, journal=J.Journal(film="e15-sub-burned"))


FACES = ("display", "display_italic", "structure", "structure_medium", "data")


@pytest.mark.parametrize("face", FACES)
def test_a_character_with_no_glyph_is_found_in_every_face(face):
    f = M._font(getattr(FONTS, face), 43)
    assert M.missing_glyphs("Smallpox 1977, the record", f) == []
    assert M.missing_glyphs("गाँव", f) == sorted(set("गाँव"))                  # Devanagari: in no latin face
    assert " " in M.missing_glyphs("1947 48", f)                    # a narrow no-break space is a glyph too
    assert M.missing_glyphs("a　b", f) == ["　"]
    assert M.missing_glyphs("a\tb", f) == ["\t"]                              # only U+0020 and a line break are skipped
    assert M.missing_glyphs("a b\nc", f) == []


def test_a_space_the_face_lacks_refuses_the_card():
    data = M._font(FONTS.data, 43)
    assert M.missing_glyphs("1947 48", data)
    with pytest.raises(M.TextUndrawable):
        M.card_layout(L1080, ["The record holds no account of 1947 48."], FONTS)
    with pytest.raises(M.TextUndrawable):
        M.card_layout(L1080, ["The record holds no account.", "Searched: the archive"], FONTS)


def test_a_character_with_no_glyph_is_refused_never_drawn_as_a_box():
    f = M._font(FONTS.display, 43)
    assert M.missing_glyphs("Smallpox 1977", f) == []
    assert M.missing_glyphs("गाँव", f)                                        # Devanagari: not in the latin face
    with pytest.raises(M.TextUndrawable):
        M.card_layout(L1080, ["The record holds no गाँव."], FONTS)
    with pytest.raises(M.TextUndrawable):
        M.lower_third_layout(L1080, ["गाँव", "Place, 1947"], FONTS, "place")
    with pytest.raises(M.TextUndrawable):
        M.label_check(L1080, "Archive · गाँव", FONTS)


def test_a_provenance_label_past_the_middle_is_refused():
    assert M.label_check(L1080, "Reconstructed · 1946 · colour cast removed", FONTS) > 0
    with pytest.raises(M.TextOverflow, match="provenance label"):
        M.label_check(L1080, "Reconstructed · 1946 · " + ", ".join(["colour cast removed"] * 6), FONTS)


def test_credits_wrap_by_their_measured_width():
    wide = "W" * 40 + " " + "W" * 40                                              # 81 characters, far wider than the column
    lines = M.credits_wrap(L1080, wide, FONTS)
    assert len(lines) == 2 and " ".join(lines) == wide
    _, f_l, f_n = M.credits_fonts(L1080, FONTS)
    assert all(M._measure(ln, f_l, f_n) <= L1080.w(M.CREDITS["col_w"]) for ln in lines)
    normal = "S3 test fixture, Test image A (landscape), test fixture, not archival, 2026, CC0"
    assert M.credits_wrap(L1080, normal, FONTS) == [normal]                       # what fitted keeps its G2 breaks


@pytest.mark.parametrize("dur, ok", [(3.0, False), (14.0, True)])
def test_the_credits_roll_finishes_inside_its_shot(plan, dur, ok):
    s = dict(next(x for x in plan["shots"] if x.get("_card") == "credits"), _dur=dur)
    p = dict(plan, shots=[s])
    j = J.Journal(film="e15-roll")
    assert (R.credits_roll_lints(j, p) == []) is ok
    e = lints(j, "credits-roll")[0]
    assert (e["status"] == "pass") is ok and e["severity"] == "block"
    assert R.credits_roll_lints(J.Journal(film="e15-roll-draft"), p, draft=True) == []


def test_a_map_or_count_text_with_no_glyph_is_refused():
    cv = MP.Canvas(MP.palette(MP.TOKENS), FONTS)
    cv.text((100, 100), "Patna", "structure", 2.0, "text")
    with pytest.raises(MP.MapRefused, match="no glyph"):
        cv.text((100, 200), "पटना", "structure", 2.0, "text")
