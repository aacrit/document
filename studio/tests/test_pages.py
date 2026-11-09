"""The house typeset page (studio.engine.pages): a document's passage verbatim on the house paper, with the page's own
title and source lines (GRAMMAR 2026-11-08, A8 never-list refined: a statement's typeset page names its author in its
own title and source lines; they are the page's content, not A56 meta-text). Deterministic, every numeral in the data
face, nothing cut to fit, and the record beside the PNG makes it a page for maps.drawn_kind."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from studio.engine import maps as MP
from studio.engine import motion as M
from studio.engine import pages as PG

SMALL = (960, 540)


def page(**over):
    p = {"id": "D-PAGE-TEST", "title": ["Dr. Herran to Mr. Hay.", "Legation of Colombia, November 7, 1903."],
         "body": ["Your excellency will undoubtedly receive the reply, but I am lodging a solemn protest against "
                  "article 35 of the treaty of 1846–1848."],
         "source": "Papers Relating to the Foreign Relations of the United States, 1903, p. 244",
         "reads": ["I am lodging a solemn protest"]}
    p.update(over)
    return p


# ---- the spec ------------------------------------------------------------------------------------------------------

def test_a_good_page_has_no_problems():
    assert PG.page_problems(page()) == []


@pytest.mark.parametrize("field", ["title", "body", "source"])
def test_a_page_without_its_title_body_or_source_is_refused(field):
    bad = page(**{field: [] if field != "source" else ""})
    assert any(field in p for p in PG.page_problems(bad))


def test_a_reading_the_page_does_not_hold_verbatim_is_refused():
    probs = PG.page_problems(page(reads=["I am lodging a formal protest"]))
    assert probs and "verbatim" in probs[0]


def test_a_reading_matches_across_curly_and_straight_apostrophes_and_line_breaks():
    p = page(body=["the injury of Colombia’s rights and in disaccord"], reads=["injury of Colombia's\nrights"])
    assert PG.page_problems(p) == []


def test_a_character_with_no_glyph_is_refused_never_drawn_as_a_box():
    probs = PG.page_problems(page(body=["a protest ☃ here"]), size=SMALL)
    assert any("glyph" in p for p in probs)


def test_ids_from_a_spec_are_untrusted_and_quoted_in_problems():
    xss = '"><img src=x onerror=alert(1)>'
    probs = PG.page_problems(page(id=xss, source=""))
    assert probs and repr(xss) in probs[0]


def test_an_id_that_is_not_a_plain_file_name_is_refused():
    assert any("id" in p for p in PG.page_problems(page(id="../D-PAGE")))


# ---- the layout ----------------------------------------------------------------------------------------------------

def test_every_numeral_on_the_page_is_set_in_the_data_face():
    lay = PG.layout(page(), size=SMALL)
    spans = [s for ln in lay["lines"] for s in ln["spans"]]
    assert any("1903" in s["text"] for s in spans) and any("1846" in s["text"] for s in spans)
    assert M.numerals_outside_mono(spans) == []


def test_the_title_comes_first_and_the_source_last():
    lay = PG.layout(page(), size=SMALL)
    kinds = [ln["kind"] for ln in lay["lines"]]
    assert kinds[0] == "title" and kinds[-1] == "source" and "body" in kinds
    ys = [ln["baseline"] for ln in lay["lines"]]
    assert ys == sorted(ys)
    assert lay["drawn_text"][0] == {"kind": "title", "text": "Dr. Herran to Mr. Hay."}
    assert lay["drawn_text"][-1]["kind"] == "source"


def test_no_title_line_is_set_in_the_italic_whose_alternates_misread_names():
    lay = PG.layout(page(), size=SMALL)
    faces = {s["font"].path for ln in lay["lines"] if ln["kind"] == "title" for s in ln["spans"]}
    assert not any("italic" in f for f in faces)


def test_every_word_is_kept_and_everything_sits_inside_the_page():
    long = page(body=["word " * 260])
    lay = PG.layout(long, size=SMALL)
    W, H = SMALL
    drawn = " ".join(t["text"] for t in lay["drawn_text"] if t["kind"] == "body")
    assert drawn.split() == ("word " * 260).split()
    for ln in lay["lines"]:
        assert 0 <= ln["x"] and ln["x"] + ln["width"] <= W
        assert 0 < ln["baseline"] < H


def test_a_passage_too_long_for_the_page_is_refused_never_cut():
    with pytest.raises(M.TextOverflow):
        PG.layout(page(body=["word " * 4000]), size=SMALL)


def test_the_page_draws_in_the_house_paper_and_ink():
    im = PG.render(page(), size=SMALL)
    a = np.asarray(im).reshape(-1, 3).astype(int)
    paper = np.array(M.PALETTE["bone"])
    assert np.abs(np.median(a, axis=0) - paper).max() <= 3          # the ground is the house paper, grained
    assert (np.abs(a - np.array(M.PALETTE["ink"])).sum(axis=1) < 30).sum() > 200     # and the type is the house ink


def test_the_page_is_deterministic():
    a = PG.render(page(), size=SMALL).tobytes()
    b = PG.render(page(), size=SMALL).tobytes()
    assert a == b
    assert PG.render(page(id="D-PAGE-OTHER"), size=SMALL).tobytes() != a     # the grain is seeded per page


# ---- the CLI and its record ----------------------------------------------------------------------------------------

def _spec(tmp_path, pages):
    p = tmp_path / "pages.json"
    p.write_text(json.dumps({"film": "test", "pages": pages}), encoding="utf-8")
    return p


def test_the_cli_writes_each_png_and_a_record_that_makes_it_a_page(tmp_path):
    spec = _spec(tmp_path, [page()])
    out = tmp_path / "out"
    PG.main([str(spec), "--out", str(out), "--width", str(SMALL[0]), "--height", str(SMALL[1])])
    png = out / "D-PAGE-TEST.png"
    rec = json.loads((out / PG.RECORD).read_text(encoding="utf-8"))["D-PAGE-TEST"]
    assert rec["sha256"] == hashlib.sha256(png.read_bytes()).hexdigest()
    assert rec["pixels_sha256"] == hashlib.sha256(Image.open(png).convert("RGB").tobytes()).hexdigest()
    assert rec["spec_sha256"] == PG.spec_sha256(spec.read_bytes())
    assert rec["title"] == page()["title"] and rec["source"] == page()["source"]
    assert [d["kind"] for d in rec["drawn_text"]][0] == "title"
    assert (rec["width"], rec["height"]) == SMALL
    assert MP.drawn_kind({"id": "D-PAGE-TEST", "_path": str(png)}) == ("page", None)
    assert PG.RECORD.endswith("-pages.json")      # maps.PAGE_RECORDS finds it


def test_the_cli_keeps_other_pages_records_and_refuses_a_bad_spec_whole(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / PG.RECORD).write_text(json.dumps({"D-OLD": {"file": "D-OLD.png"}}), encoding="utf-8")
    good = _spec(tmp_path, [page()])
    PG.main([str(good), "--out", str(out), "--width", str(SMALL[0]), "--height", str(SMALL[1])])
    rec = json.loads((out / PG.RECORD).read_text(encoding="utf-8"))
    assert set(rec) == {"D-OLD", "D-PAGE-TEST"}
    bad = _spec(tmp_path, [page(id="D-PAGE-B"), page(id="D-PAGE-C", reads=["not on the page"])])
    with pytest.raises(SystemExit):
        PG.main([str(bad), "--out", str(out), "--width", str(SMALL[0]), "--height", str(SMALL[1])])
    assert not (out / "D-PAGE-B.png").exists()            # nothing is written when any page is refused


def test_the_cli_refuses_duplicate_ids(tmp_path):
    spec = _spec(tmp_path, [page(), page()])
    with pytest.raises(SystemExit):
        PG.main([str(spec), "--out", str(tmp_path / "o"), "--width", str(SMALL[0]), "--height", str(SMALL[1])])


# ---- fix round of PR #105: dashes, the spec's hash, unbreakable words -----------------------------------------------

EM = "—"


def test_a_verbatim_record_dash_is_kept_in_the_body_and_a_verbatim_title_line():
    """Founder ruling 2026-11-09 (DECISIONS; GRAMMAR 9 amendment): a typeset page sets its record's dashes verbatim."""
    p = page(title=[{"text": f"The Independence of the Isthmus of Panama{EM}Its History.", "verbatim": True}],
             body=[f"captured no fort{EM}contenting themselves; I am lodging a solemn protest"])
    assert PG.page_problems(p) == []
    lay = PG.layout(p, size=SMALL)
    assert lay["drawn_text"][0] == {"kind": "title", "text": f"The Independence of the Isthmus of Panama{EM}Its "
                                                             f"History.", "verbatim": True}


def test_a_dash_in_the_studios_own_words_is_refused():
    in_source = PG.page_problems(page(source=f"Papers Relating to the Foreign Relations{EM}1903"))
    assert in_source and "em dash" in in_source[0] and "source" in in_source[0]
    in_title = PG.page_problems(page(title=[f"Herran to Hay{EM}a protest"]))           # a plain string: studio-written
    assert in_title and "em dash" in in_title[0]
    flagged = PG.page_problems(page(title=[{"text": f"Herran{EM}Hay", "verbatim": False}]))
    assert flagged and "em dash" in flagged[0]


def test_a_title_line_object_must_hold_text():
    assert any("title" in p for p in PG.page_problems(page(title=[{"verbatim": True}])))


def test_the_spec_hash_does_not_depend_on_the_checkouts_line_endings():
    lf = b'{\n "pages": []\n}\n'
    assert PG.spec_sha256(lf) == PG.spec_sha256(lf.replace(b"\n", b"\r\n"))
    assert PG.spec_sha256(lf) == hashlib.sha256(lf).hexdigest()


def test_a_word_wider_than_its_measure_is_refused_never_drawn_past_it():
    with pytest.raises(M.TextOverflow):
        PG.layout(page(body=["x" * 400]), size=SMALL)
    with pytest.raises(M.TextOverflow):
        PG.layout(page(source="y" * 400), size=SMALL)
