"""Numerals on cards are set in JetBrains Mono (brand audit 2026-11-02, high; BRAND-KIT 7 and 7a, GRAMMAR A28(g)).

Market Street's title card set "1906" in Fraunces, and its chapter 3 title "5:12" too: the card renderer drew a title
as one Fraunces run. Every card now lays its lines out as spans (a fragment and its face), the drawer draws those
spans and nothing else, and the `card-numerals-mono` lint reads the same spans: a digit outside the mono face is
refused before any frame. Beside Fraunces 300 the numerals are JetBrains Mono 300 at DISPLAY_NUMERALS' scale, so
their stems and figure height match the display face (mono 500 read bold there)."""

from __future__ import annotations

import json

import numpy as np
import pytest
from PIL import Image, ImageDraw

from conftest import make_film
from studio.engine import journal as J
from studio.engine import motion as M
from studio.engine import render as R

FONTS = M.Fonts()
L1080 = M.Layout(1920, 1080)
XSS = '"><img src=x onerror=alert(1)>'


def _digit_spans(lines):
    return [s for ln in lines for s in ln["spans"] if any(ch.isdigit() for ch in s["text"])]


def _foot(path: str, px: int, s: str = "1") -> int:
    """The bottom row of ``s``'s ink drawn on one baseline (a flat-footed 1 has no overshoot). Opened through
    ``motion._font`` (BASIC layout, pinned), the same call the card renderer itself makes, so this measures the
    production layout and not whatever layout engine ``ImageFont.truetype`` would otherwise default to."""
    f = M._font(path, px)
    im = Image.new("L", (px * 3, 400))
    ImageDraw.Draw(im).text((10, 300), s, font=f, fill=255, anchor="ls")
    return int(np.where((np.asarray(im) > 127).any(1))[0].max())


def _ink(path: str, px: int, s: str):
    """The figure height and the median horizontal stem of ``s`` drawn at ``px``, in pixels. Opened through
    ``motion._font`` (BASIC layout, pinned), the same call the card renderer itself makes."""
    f = M._font(path, px)
    im = Image.new("L", (px * len(s) * 2, px * 3))
    ImageDraw.Draw(im).text((10, 2 * px), s, font=f, fill=255, anchor="ls")
    a = np.asarray(im) > 127
    ys = np.where(a.any(1))[0]
    h = ys.max() - ys.min() + 1
    runs = []
    for y in range(ys.min() + h // 4, ys.max() - h // 4):
        e = np.diff(np.concatenate([[0], a[y].astype(int), [0]]))
        runs += list(np.where(e == -1)[0] - np.where(e == 1)[0])
    return int(h), float(np.median(runs))


def _probe(frame: Image.Image, span: dict, baseline: float, alpha: float = 1.0):
    """The frame's pixels over one span's box, beside the same span drawn alone in its own face and in Fraunces 300."""
    f = span["font"]
    x0, x1 = int(span["x"]) - 2, int(span["x"] + f.getlength(span["text"])) + 3
    y0, y1 = int(baseline - f.size), int(baseline + 0.3 * f.size)
    got = np.asarray(frame.convert("L"), dtype=np.float32)[y0:y1, x0:x1]

    def alone(font):
        im = Image.new("RGBA", frame.size, (0, 0, 0, 255))
        ImageDraw.Draw(im).text((span["x"], baseline), span["text"], font=font, fill=M._rgba(M.PALETTE["bone"], alpha),
                                anchor="ls")
        return np.asarray(im.convert("L"), dtype=np.float32)[y0:y1, x0:x1]

    display = M._font(FONTS.display, round(f.size / M.DISPLAY_NUMERALS["scale"]))
    return got, alone(f), alone(display)


# --------------------------------------------------------------------------
# The optical match: mono 300 at DISPLAY_NUMERALS' scale sits with Fraunces 300
# --------------------------------------------------------------------------

@pytest.mark.parametrize("pct", [M.TITLE["size"], M.CHAPTER["title"], M.SILENT["size"]])
def test_display_numerals_match_fraunces_300_in_height_and_stem(pct):
    px = L1080.px(pct)
    mono = M.display_data_font(FONTS, px)
    fh, fs = _ink(FONTS.display, px, "1906")
    mh, ms = _ink(mono.path, mono.size, "1906")
    # the figures stand as tall as Fraunces' own: within 2 px, the step FreeType's hinting takes between two sizes
    # (mono 300 is 53 px tall at 73 px and 57 at 74; Fraunces 300 steps the same way)
    assert abs(mh - fh) <= 2, (pct, fh, mh)
    assert abs(ms - fs) <= 1, (pct, fs, ms)          # and their stems are as thick
    assert abs(_foot(mono.path, mono.size) - _foot(FONTS.display, px)) <= 1     # on the Fraunces baseline
    _, bold = _ink(FONTS.data, round(px * 0.94), "1906")
    assert bold >= 1.15 * fs                         # mono 500 at 94%, the old inline face, read bold beside it


def test_the_matched_face_is_jetbrains_mono_300():
    f = M.display_data_font(FONTS, 76)
    assert M.is_data_face(f.path) and "300" in f.path
    assert not M.is_data_face(FONTS.display) and not M.is_data_face(FONTS.structure)


# --------------------------------------------------------------------------
# Title and chapter cards: "1906" and "5:12" render in mono
# --------------------------------------------------------------------------

def test_a_title_card_with_1906_sets_the_year_in_mono():
    title = "Market Street · San Francisco, spring 1906"
    lay = M.title_card_layout(L1080, title, FONTS)
    spans = _digit_spans(lay["lines"][:1])
    assert [s["text"] for s in spans] == ["1906"]
    assert all(M.is_data_face(s["font"].path) for s in spans)
    assert "".join(s["text"] for s in lay["lines"][0]["spans"]) == title
    assert M.card_numeral_problems(lay) == []
    frame = M.title_card_frame(Image.new("RGB", (1920, 1080)), 3.0, start=0.0, end=5.0, title=title, fonts=FONTS)
    got, mono, fraunces = _probe(frame, spans[0], L1080.h(50.0))
    assert np.abs(got - mono).mean() < 2.0               # the pixels are the mono span's
    assert np.abs(got - fraunces).mean() > 8.0           # and not Fraunces' 1906


def test_a_chapter_card_titled_5_12_sets_the_time_and_the_number_in_mono():
    lay = M.chapter_card_layout(L1080, 3, "5:12", "Wednesday 18 April 1906", FONTS)
    head, dates = lay["lines"]
    spans = _digit_spans([head])
    assert [s["text"] for s in spans] == ["3", "5:12"]
    assert all(M.is_data_face(s["font"].path) for s in spans)
    assert all(M.is_data_face(s["font"].path) for s in dates["spans"])
    assert M.card_numeral_problems(lay) == []
    frame = M.chapter_card_frame(Image.new("RGB", (1920, 1080)), 3.0, start=0.0, end=5.0, number=3, title="5:12",
                                 dates="Wednesday 18 April 1906", fonts=FONTS)
    got, mono, fraunces = _probe(frame, spans[1], L1080.h(M.CHAPTER["baseline"]))
    assert np.abs(got - mono).mean() < 2.0
    assert np.abs(got - fraunces).mean() > 8.0


def test_a_digit_inside_a_chapter_title_is_mono_beside_fraunces_words():
    lay = M.chapter_card_layout(L1080, 2, "Tuesday night, 17 April", "", FONTS)
    faces = [(s["text"], M.is_data_face(s["font"].path)) for s in lay["lines"][0]["spans"]]
    assert ("17", True) in faces and ("Tuesday night, ", False) in faces


# --------------------------------------------------------------------------
# Statement, quote and credits cards
# --------------------------------------------------------------------------

def test_statement_and_quote_cards_set_every_digit_in_mono():
    texts = ['"All 211 contacts were traced."', "Morbidity and Mortality Weekly Report, 6 January 1978"]
    lay = M.card_layout(L1080, texts, FONTS)
    assert M.card_numeral_problems(lay) == []
    first = lay["elements"][0]["lines"][0]["spans"]
    assert [s["text"] for s in first if s["text"].isdigit()] == ["211"]
    assert all(M.is_data_face(s["font"].path) and "300" in s["font"].path for s in first if s["text"].isdigit())
    # the structure face keeps BRAND-KIT 11's numerals (JetBrains Mono at 94%), unchanged
    second = lay["elements"][1]["lines"][0]["spans"]
    assert all(s["font"].path == FONTS.data for s in second if any(c.isdigit() for c in s["text"]))
    assert M.card_drawn_text(lay) == [" ".join(t.split()) for t in texts]


def test_credits_set_every_digit_in_mono():
    blocks = [("Archives", ["Prelinger Archives (A Trip Down Market Street, 4K scan 2018)"]),
              ("Recordings", ["Enrico Caruso, The Theatre, July 1906"])]
    lay = M.credits_layout(L1080, blocks, FONTS)
    assert M.card_numeral_problems(lay) == []
    assert {s["text"] for s in _digit_spans(lay["lines"])} == {"4", "2018", "1906"}


def test_the_drawer_draws_the_layout_spans_and_nothing_else():
    texts = ["Bihar, one week in May 1974: 11 707 cases.", "WHO, Weekly Epidemiological Record, 14 June 1974"]
    a = M.silent_card_frame(Image.new("RGB", (1920, 1080)), 2.0, start=0.0, end=4.0, texts=texts, fonts=FONTS)
    lay = M.card_layout(L1080, texts, FONTS)
    ref = Image.new("RGBA", (1920, 1080), M.PALETTE["black"] + (255,))
    layer = Image.new("RGBA", ref.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for e in lay["elements"]:
        al = M.fade_in(2.0, e["index"] * M.SILENT["stagger"], M.SILENT["fade"]) * (0.8 if e["index"] else 1.0)
        for ln in e["lines"]:
            for s in ln["spans"]:
                d.text((s["x"], ln["baseline"]), s["text"], font=s["font"], fill=M._rgba(M.PALETTE["mark_text"], al),
                       anchor="ls")
    assert np.array_equal(np.asarray(a), np.asarray(Image.alpha_composite(ref, layer)))


def test_a_hostile_title_is_laid_out_as_text_and_its_spans_keep_every_character():
    lay = M.title_card_layout(L1080, "Fixture 1906 " + XSS, FONTS)
    assert "".join(s["text"] for s in lay["lines"][0]["spans"]) == "Fixture 1906 " + XSS
    assert M.card_numeral_problems(lay) == []


# --------------------------------------------------------------------------
# The lint catches the old behaviour
# --------------------------------------------------------------------------

def _old_title_layout(L, title, fonts):
    """The renderer before this ticket: the whole title one Fraunces run."""
    f_t = M._font(fonts.display, L.px(M.TITLE["size"]))
    w = f_t.getlength(title)
    x = (L.W - w) / 2.0
    return {"font": f_t, "lines": [{"role": "title", "text": title, "x": x, "w": w,
                                    "spans": [{"text": title, "x": x, "font": f_t, "alpha": 1.0}]},
                                   {"role": "wordmark", "text": "void document", "spans": []}]}


def test_the_lint_names_a_digit_run_set_in_fraunces():
    old = _old_title_layout(L1080, "Market Street · San Francisco, spring 1906", FONTS)
    found = M.card_numeral_problems(old)
    assert len(found) == 1 and found[0]["digits"] == ["1906"] and "Fraunces" in found[0]["face"]
    f_t = M._font(FONTS.display, 60)
    chapter_old = {"lines": [{"role": "title", "spans": [{"text": "3", "x": 0, "font": M._font(FONTS.data, 60)},
                                                         {"text": "5:12", "x": 60, "font": f_t}]}]}
    assert [p["digits"] for p in M.card_numeral_problems(chapter_old)] == [["5:12"]]


def test_the_drawer_refuses_a_digit_outside_mono():
    old = _old_title_layout(L1080, "Market Street 1906", FONTS)
    d = ImageDraw.Draw(Image.new("RGBA", (1920, 1080)))
    with pytest.raises(M.NumeralsOutsideMono, match="1906"):
        M._draw_spans(d, 540, old["lines"][0]["spans"], M.PALETTE["bone"], 1.0)


def _edit(film, fn):
    data = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    fn(data)
    (film / "screenplay.json").write_text(json.dumps(data), encoding="utf-8")


def _shot(play, sid):
    return next(s for p in play["parts"] for s in p["shots"] if s["id"] == sid)


def _lints(j, rule):
    return [e for e in J.read(j.path) if e["kind"] == "lint" and e.get("rule") == rule]


def test_the_plan_journals_card_numerals_mono_and_refuses_the_old_title(tmp_path, monkeypatch):
    film = make_film(tmp_path / "film")
    _edit(film, lambda p: _shot(p, "S1").update(text=["Fixture film · 1906"]))
    j = J.Journal(film="numerals-pass")
    R.build_plan(film, W=640, H=360, burn_subtitles=False, journal=j)
    units = {e["unit"]: e["status"] for e in _lints(j, "card-numerals-mono")}
    assert units == {"S1": "pass", "S2": "pass", "S7": "pass", "S8": "pass", "S9": "pass", "credits": "pass"}
    monkeypatch.setattr(M, "title_card_layout", _old_title_layout)
    with pytest.raises(R.Refused, match=r"card-numerals-mono \(S1\)"):
        R.build_plan(film, W=640, H=360, burn_subtitles=False, journal=J.Journal(film="numerals-old"))


@pytest.mark.parametrize("text", ["An area of 1 000 km\u00b2 searched", "Footnote\u00b9 in 1974", "x\u00b3 and 10\u00b2"])
# Latin-1 superscripts only: a glyph neither face carries (U+2074) is refused as undrawable, which is right
def test_superscript_digits_are_routed_to_mono_and_the_lint_agrees(text):
    """Review of #89: str.isdigit() counts superscripts, \d does not. The router (_NUM) and the lint must share one
    predicate, or a card with "km\u00b2" refuses with no way to fix it but rewording."""
    lay = M.card_layout(L1080, [text], FONTS)
    assert M.card_numeral_problems(lay) == []
    spans = lay["elements"][0]["lines"][0]["spans"]
    for s in spans:
        if any(ch.isdigit() for ch in s["text"]):
            assert M.is_data_face(s["font"].path), (s["text"], s["font"].path)
    assert M.card_drawn_text(lay) == [" ".join(text.split())]
