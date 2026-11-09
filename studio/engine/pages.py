"""The house typeset page: a document's passage, verbatim, as a DRAWN page (GRAMMAR 113: a document the studio typeset
is DRAWN with the source id; A8 rule 5 and its never-list: a partisan government's statement is read over a DRAWN
typeset title page, never a photograph).

The look is the house's drawn pages (tools/doc_pages.py, the Real World METAR plates): the words on the flat house
paper (--doc-bone) in the house ink (--doc-ink) with a fixed-seed grain, 3840x2160 so a READ tour stays sharp. What
this adds is the page's own title and source lines (GRAMMAR 2026-11-08, A8 never-list refined): the title names whose
document it is, as the document heads itself, and the source line names the record it is set from. They are the
page's content, not A56 meta-text, so no meta-text pattern reads them.

The passage and the title are set in Fraunces 300 (the title's later lines smaller), the source line in Inter; every
numeral rides the data face (BRAND-KIT 7, motion.text_spans). Nothing is cut to fit: the body steps down in size until
the page holds it, and a passage too long for the page is refused (motion.TextOverflow). A character with no glyph is
refused, never drawn as an empty box. A page's ``reads`` (the words the film reads over it) must stand in its body
verbatim (only the apostrophe and quote marks' curl and the line breaks are not compared).

Deterministic: the same spec gives the same pixels. The CLI writes ``<id>.png`` and merges each page's record into
``doc-pages.json`` beside them (the record ``maps.drawn_kind`` reads: ``*-pages.json`` keyed by id).

    python -m studio.engine.pages <spec.json> --out <dir> [--width 3840 --height 2160]

A spec is ``{"film": ..., "pages": [{"id", "title": [line, ...], "body": [paragraph, ...], "source": line,
"reads": [text, ...]}, ...]}``; any other fields (where each passage was read, its page) are kept for review only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from studio.engine import motion as M

RECORD = "doc-pages.json"
GENERATOR = "studio.engine.pages"
SIZE = (3840, 2160)
PAPER, INK = M.PALETTE["bone"], M.PALETTE["ink"]
GRAIN = 3.0                          # the house grain's sigma, one fixed seed per page (tools/doc_pages.py)

# shares of the page's height (sizes) and width (measures); the body steps down from BODY_MAX to BODY_MIN
LAYOUT = dict(title=0.040, title_after=0.62, body_max=0.044, body_min=0.018, source=0.020, leading=1.45,
              title_leading=1.30, para_gap=0.55, block_gap=1.10, body_w=0.62, line_w=0.70, fill=0.86)
STRUCTURE_NUMERALS = 0.94            # BRAND-KIT 11: the structure face's numerals are mono 500 at 94%
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_CURL = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'})


def _norm(text: str) -> str:
    return " ".join(str(text or "").translate(_CURL).split())


def _faces(fonts: M.Fonts, H: int, body_px: int) -> dict:
    t = max(1, round(H * LAYOUT["title"]))
    t2 = max(1, round(t * LAYOUT["title_after"]))
    s = max(1, round(H * LAYOUT["source"]))
    return {
        "title": (M._font(fonts.display, t), M.display_data_font(fonts, t)),
        # upright: the self-hosted Fraunces 300 italic draws its wonky alternates (a hooked l, a looped h), which read
        # on a document's page as misprints of its proper names
        "title_after": (M._font(fonts.display, t2), M.display_data_font(fonts, t2)),
        "body": (M._font(fonts.display, body_px), M.display_data_font(fonts, body_px)),
        "source": (M._font(fonts.structure, s), M._font(fonts.data, max(1, round(s * STRUCTURE_NUMERALS)))),
    }


def page_problems(page: dict, size: tuple[int, int] | None = None, fonts: M.Fonts | None = None) -> list[str]:
    """Why a spec page may not be typeset, or []. With ``size`` the page is also laid out, so a passage too long for
    the page is named here. Pure (the fonts are files the engine already reads)."""
    pid = page.get("id")
    probs = []
    if not isinstance(pid, str) or not SAFE_ID.match(pid):
        return [f"page id {pid!r} is not a plain file name"]
    title, body, source = page.get("title"), page.get("body"), page.get("source")
    if not (isinstance(title, list) and title and all(isinstance(t, str) and t.strip() for t in title)):
        probs.append(f"{pid!r}: no title: a typeset page names whose document it is in its own title lines "
                     f"(GRAMMAR 2026-11-08)")
    if not (isinstance(body, list) and body and all(isinstance(b, str) and b.strip() for b in body)):
        probs.append(f"{pid!r}: no body: the page sets the document's passage")
    if not (isinstance(source, str) and source.strip()):
        probs.append(f"{pid!r}: no source line: a typeset page names its record in its own source line "
                     f"(GRAMMAR 2026-11-08)")
    if probs:
        return probs
    held = _norm(" ".join(body))
    for r in page.get("reads") or []:
        if _norm(r) not in held:
            probs.append(f"{pid!r}: the reading {r!r} is not on the page verbatim")
    fonts = fonts or M.Fonts()
    faces = _faces(fonts, 1080, 40)
    for kind, texts in (("title", title[:1]), ("title_after", title[1:]), ("body", body), ("source", [source])):
        for t in texts:
            miss = M.missing_glyphs(" ".join(t.split()), *faces[kind])
            if miss:
                probs.append(f"{pid!r}: no glyph for {''.join(miss)!r} in the {kind} face: {t!r}")
    if not probs and size is not None:
        try:
            layout(page, size=size, fonts=fonts)
        except M.TextOverflow as e:
            probs.append(f"{pid!r}: {e}")
    return probs


def _block(kind: str, texts: list[str], font, data_font, max_w: float, leading: float, gap: float) -> list[dict]:
    rows = []
    for i, t in enumerate(texts):
        for j, ln in enumerate(M._wrap(" ".join(t.split()), font, data_font, max_w, what=kind)):
            rows.append({"kind": kind, "text": ln, "font": font, "data_font": data_font,
                         "h": font.size * leading, "gap": gap if (j == 0 and i > 0) else 0.0,
                         "w": M._measure(ln, font, data_font)})
    return rows


def layout(page: dict, size: tuple[int, int] = SIZE, fonts: M.Fonts | None = None) -> dict:
    """The page's lines, top to bottom: ``{"lines": [{kind, x, baseline, width, spans}], "drawn_text": [{kind,
    text}], "body_px"}``. The title and source lines are centred; the body is one ragged-right block, centred on its
    widest line. The body steps down a pixel at a time until everything fits ``LAYOUT['fill']`` of the height;
    past ``body_min`` it raises motion.TextOverflow. Pure."""
    W, H = size
    fonts = fonts or M.Fonts()
    title, body, source = page["title"], page["body"], page["source"]
    line_w, body_w = W * LAYOUT["line_w"], W * LAYOUT["body_w"]
    hi, lo = max(1, round(H * LAYOUT["body_max"])), max(1, round(H * LAYOUT["body_min"]))
    for px in range(hi, lo - 1, -1):
        f = _faces(fonts, H, px)
        head = _block("title", title[:1], *f["title"], line_w, LAYOUT["title_leading"], 0.0)
        head += _block("title", title[1:], *f["title_after"], line_w, LAYOUT["title_leading"], 0.0)
        text = _block("body", body, *f["body"], body_w, LAYOUT["leading"], px * LAYOUT["para_gap"])
        foot = _block("source", [source], *f["source"], line_w, LAYOUT["title_leading"], 0.0)
        gap = f["title"][0].size * LAYOUT["block_gap"]
        total = sum(r["h"] + r["gap"] for r in head + text + foot) + 2 * gap
        if total <= H * LAYOUT["fill"]:
            break
    else:
        raise M.TextOverflow(f"{page.get('id')!r}: the passage does not fit the page at {lo} px; set a shorter "
                             f"passage (nothing is cut to fit)")
    y = (H - total) / 2
    body_x = (W - max(r["w"] for r in text)) / 2
    lines = []
    for group, after in ((head, gap), (text, gap), (foot, 0.0)):
        for r in group:
            y += r["gap"]
            x = body_x if r["kind"] == "body" else (W - r["w"]) / 2
            base = y + r["h"] * 0.72
            lines.append({"kind": r["kind"], "x": x, "baseline": base, "width": r["w"],
                          "spans": M.text_spans(x, r["text"], r["font"], r["data_font"])})
            y += r["h"]
        y += after
    drawn = [{"kind": "title", "text": " ".join(t.split())} for t in title]
    drawn += [{"kind": "body", "text": " ".join(b.split())} for b in body]
    drawn += [{"kind": "source", "text": " ".join(source.split())}]
    return {"lines": lines, "drawn_text": drawn, "body_px": px, "size": [W, H]}


def render(page: dict, size: tuple[int, int] = SIZE, fonts: M.Fonts | None = None) -> Image.Image:
    """The page as an RGB image: the house paper, its grain seeded by the page's id, and the laid-out lines in the
    house ink. A digit outside the data face is refused (motion.NumeralsOutsideMono), never drawn."""
    W, H = size
    lay = layout(page, size=size, fonts=fonts)
    rng = np.random.default_rng(int(hashlib.sha256(str(page["id"]).encode()).hexdigest()[:8], 16))
    base = np.empty((H, W, 3), np.float32)
    base[:] = PAPER
    base += rng.normal(0, GRAIN, (H, W, 1)).astype(np.float32)
    im = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(im)
    for ln in lay["lines"]:
        bad = M.numerals_outside_mono(ln["spans"])
        if bad:
            raise M.NumeralsOutsideMono(f"{page['id']!r} would set {bad[0]['text']!r} in {bad[0]['face']}")
        for s in ln["spans"]:
            d.text((s["x"], ln["baseline"]), s["text"], font=s["font"], fill=INK, anchor="ls")
    return im


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m studio.engine.pages", description=__doc__.split("\n\n")[0])
    ap.add_argument("spec")
    ap.add_argument("--out", required=True)
    ap.add_argument("--width", type=int, default=SIZE[0])
    ap.add_argument("--height", type=int, default=SIZE[1])
    a = ap.parse_args(argv)
    spec_path = Path(a.spec)
    spec_bytes = spec_path.read_bytes()
    pages = json.loads(spec_bytes.decode("utf-8")).get("pages") or []
    size = (a.width, a.height)
    probs, seen = [], set()
    for p in pages:
        if p.get("id") in seen:
            probs.append(f"page id {p.get('id')!r} is set twice")
        seen.add(p.get("id"))
        probs += page_problems(p, size=size)
    if not pages:
        probs.append("the spec sets no pages")
    if probs:
        for p in probs:
            print("refused:", p, file=sys.stderr)
        raise SystemExit(1)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rec_path = out / RECORD
    try:
        records = json.loads(rec_path.read_text(encoding="utf-8"))
        records = records if isinstance(records, dict) else {}
    except (OSError, ValueError):
        records = {}
    for p in pages:
        im = render(p, size=size)
        png = out / f"{p['id']}.png"
        im.save(png, optimize=False)
        lay = layout(p, size=size)
        records[p["id"]] = {
            "file": png.name, "generator": GENERATOR, "kind": "page",
            "sha256": _sha(png.read_bytes()), "pixels_sha256": _sha(im.tobytes()),
            "spec": spec_path.name, "spec_sha256": _sha(spec_bytes),
            "width": size[0], "height": size[1], "body_px": lay["body_px"],
            "lines": sum(1 for ln in lay["lines"] if ln["kind"] == "body"),
            "title": p["title"], "source": p["source"], "drawn_text": lay["drawn_text"],
        }
        print(p["id"], lay["body_px"], "px", records[p["id"]]["sha256"])
    rec_path.write_text(json.dumps(records, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
