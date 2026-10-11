"""English captions (GRAMMAR 10) as WebVTT, from a screenplay's
``subtitle_source`` at the times the engine resolved.

The input is the screenplay the render used: ``screenplay.fitted.json`` when
the render moved lines (``--fit-voices`` writes it beside the master), else
``screenplay.json``. Given a directory, the fitted file wins.

What it does to the cues:
- A lower third's cue never overlaps a reading: when a lower-third cue
  overlaps any other cue, it is folded into the first cue it overlaps, as
  the speaker's name in brackets (``[Arthur Henderson] Verified ...``); a
  place lower third (two lines) folds in whole. A lower third over silence
  stays its own bracketed cue.
- Every cue is cut to at most two lines of 42 characters and at most 7
  seconds, its time shared in proportion to its characters (GRAMMAR 10).
- No two cues overlap; an em dash is refused (GRAMMAR 9).

Each cue's identifier is its ``ref`` (``R1``, or ``R1-2`` for the second
part of a split), so a player can map a cue back to its reading.

    python -m studio.engine.captions <film dir | screenplay.json> [-o captions-en.vtt]
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path

LINE_CHARS = 42
MAX_LINES = 2
MAX_CUE_S = 7.0
MIN_CUE_S = 1.0
EM_DASH = "—"


class CaptionError(ValueError):
    """The screenplay cannot be captioned as GRAMMAR 10 asks."""


@dataclass
class Cue:
    ref: str
    start: float
    end: float
    text: str


def find_screenplay(path: Path) -> Path:
    """The fitted screenplay in a directory if there is one, else screenplay.json; a file is taken as given."""
    if path.is_file():
        return path
    for name in ("screenplay.fitted.json", "screenplay.json"):
        if (path / name).is_file():
            return path / name
    raise CaptionError(f"no screenplay.fitted.json or screenplay.json in {path}")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _text_elements(play: dict) -> dict[str, dict]:
    return {t["id"]: t for part in play.get("parts", []) for t in part.get("text", []) if "id" in t}


def source_cues(play: dict) -> list[Cue]:
    """The English cues as the screenplay states them, in time order."""
    cues = []
    for c in play.get("subtitle_source", []):
        text = _clean(c.get("en") or "")
        if not text:
            continue
        start, end = float(c["start_s"]), float(c["end_s"])
        if end <= start:
            raise CaptionError(f"cue {c.get('ref')} ends at {end} s, before it starts at {start} s")
        if EM_DASH in text:
            raise CaptionError(f"cue {c.get('ref')} has an em dash (GRAMMAR 9)")
        cues.append(Cue(str(c.get("ref") or f"c{len(cues) + 1}"), start, end, text))
    return sorted(cues, key=lambda c: (c.start, c.ref))


def _speaker(lt: dict | None, cue: Cue) -> str:
    """What a folded lower third contributes: the speaker's name, or a place lower third whole."""
    lines = list((lt or {}).get("lines") or [])
    if len(lines) == 3:
        return f"[{_clean(lines[0])}]"
    if len(lines) == 2:
        return f"[{_clean(lines[0])}, {_clean(lines[1])}]"
    inner = cue.text.strip("[]")
    return f"[{inner.split(',')[0].strip()}]"


def fold_lower_thirds(cues: list[Cue], play: dict) -> list[Cue]:
    """Folds every lower-third cue into the first other cue that overlaps it, or that overlaps the
    lower third's own time on screen (its text element). A screenplay may time the lower third's cue
    just before the reading it names (the episode's LT-5 sits 0.1 s before R1); it is still that
    reading's speaker, and a separate one-second cue would flash past."""
    texts = _text_elements(play)
    is_lt = {c.ref for c in cues if (texts.get(c.ref) or {}).get("kind") == "lower_third"}
    others = [c for c in cues if c.ref not in is_lt]
    out = list(others)
    for lt in (c for c in cues if c.ref in is_lt):
        el = texts.get(lt.ref) or {}
        spans = [(lt.start, lt.end)]
        if "start_s" in el and "end_s" in el:
            spans.append((float(el["start_s"]), float(el["end_s"])))
        hits = [c for c in others if any(c.start < b - 1e-9 and c.end > a + 1e-9 for a, b in spans)]
        if not hits:
            out.append(lt)
            continue
        # Prefer a cue under the lower third's own time on screen: a narration line that merely
        # brushes its cue (just before it) is not the speaker's words.
        if len(spans) > 1:
            a, b = spans[1]
            under = [c for c in hits if c.start < b - 1e-9 and c.end > a + 1e-9]
            hits = under or hits
        first = min(hits, key=lambda c: (c.start, c.ref))
        first.text = f"{_speaker(texts.get(lt.ref), lt)} {first.text}"
    return sorted(out, key=lambda c: (c.start, c.ref))


def wrap(text: str, width: int = LINE_CHARS) -> list[str]:
    """Words into lines of at most ``width`` characters; a longer word stands alone."""
    lines: list[str] = []
    line = ""
    for word in text.split(" "):
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}" if line else word
    if line:
        lines.append(line)
    return lines


def _deal(lines: list[str], n: int) -> list[list[str]]:
    """The lines dealt into n groups in order, as evenly as they go."""
    base, extra = divmod(len(lines), n)
    groups, i = [], 0
    for k in range(n):
        take = base + (1 if k < extra else 0)
        groups.append(lines[i : i + take])
        i += take
    return [g for g in groups if g]


def _timed(cue: Cue, groups: list[list[str]]) -> list[Cue]:
    """Each group's share of the cue's time follows its characters, but no part gets under 1 s when
    the cue can afford it: a part that would is held at 1 s and the others share what is left."""
    dur = cue.end - cue.start
    chars = [max(1, sum(len(line) for line in g)) for g in groups]
    floor = min(MIN_CUE_S, dur / len(groups))
    held: set[int] = set()
    while True:
        free = [i for i in range(len(groups)) if i not in held]
        left = dur - floor * len(held)
        share = {i: left * chars[i] / sum(chars[j] for j in free) for i in free}
        low = {i for i, d in share.items() if d < floor - 1e-9}
        if not low:
            break
        held |= low
    lengths = [floor if i in held else share[i] for i in range(len(groups))]
    out, t = [], cue.start
    for k, g in enumerate(groups):
        end = cue.end if k == len(groups) - 1 else round(t + lengths[k], 3)
        ref = cue.ref if len(groups) == 1 else f"{cue.ref}-{k + 1}"
        out.append(Cue(ref, round(t, 3), round(end, 3), "\n".join(g)))
        t = end
    return out


def split_cue(cue: Cue) -> list[Cue]:
    """One cue as parts of at most two lines and at most 7 s, times shared by characters.
    It takes the fewest parts that keep both limits; if even one line per part runs over
    7 s (few words over a long silence), each part ends at 7 s and the screen clears."""
    lines = wrap(cue.text)
    first = max(math.ceil(len(lines) / MAX_LINES), math.ceil((cue.end - cue.start) / MAX_CUE_S - 1e-9), 1)
    parts: list[Cue] = []
    for n in range(min(first, len(lines)), len(lines) + 1):
        parts = _timed(cue, _deal(lines, n))
        if all(p.end - p.start <= MAX_CUE_S + 1e-9 for p in parts):
            return parts
    for p in parts:
        p.end = round(min(p.end, p.start + MAX_CUE_S), 3)
    return parts


def no_overlaps(cues: list[Cue]) -> list[Cue]:
    """Ends a cue where the next begins, so two never share the screen."""
    cues = sorted(cues, key=lambda c: (c.start, c.ref))
    for a, b in zip(cues, cues[1:]):
        if a.end > b.start:
            a.end = b.start
    return [c for c in cues if c.end - c.start > 1e-6]


def build_cues(play: dict) -> list[Cue]:
    cues = fold_lower_thirds(source_cues(play), play)
    parts = [p for c in cues for p in split_cue(c)]
    return no_overlaps(parts)


def timestamp(s: float) -> str:
    ms = int(round(s * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    sec, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d}.{ms:03d}"


def to_vtt(cues: list[Cue]) -> str:
    blocks = ["WEBVTT", ""]
    for c in cues:
        blocks += [c.ref, f"{timestamp(c.start)} --> {timestamp(c.end)}", c.text, ""]
    return "\n".join(blocks)


def fill_play(play: dict, values: dict | None) -> dict:
    """GRAMMAR A25 refined: a shortfall card's subtitle carries placeholders
    (``{women_share:pct}``) that the render filled from its measurement; the
    captions take the same values (sources.json ``card_fills.values``). A
    placeholder left unfilled is refused, never published as written."""
    from studio.engine import policy as POL
    out = dict(play, subtitle_source=[dict(c) for c in play.get("subtitle_source", [])])
    for c in out["subtitle_source"]:
        if POL.has_placeholder(c.get("en")):
            if not values:
                raise CaptionError(f"cue {c.get('ref')} holds a placeholder and no filled values were given "
                                   "(the render's sources.json card_fills)")
            c["en"] = POL.fill_placeholders(c["en"], values)
            if POL.has_placeholder(c["en"]):
                raise CaptionError(f"cue {c.get('ref')} holds an unknown placeholder: {c['en']}")
    return out


def render_fills(path: Path) -> dict | None:
    """The filled values a render recorded beside its screenplay, if any,
    checked as --sources-only checks them: the sources.json describes the
    master beside it (its sha256), from a full render, and its card_fills is
    well formed. None when there is no sources.json or it holds no fills; a
    sources.json whose fills fail the check is refused."""
    folder = path if path.is_dir() else path.parent
    src = folder / "sources.json"
    if not src.is_file():
        return None
    prev = json.loads(src.read_text(encoding="utf-8"))
    if prev.get("card_fills") is None:
        return None
    from studio.engine.journal import sha256_file
    from studio.engine.render import fills_provenance
    master = folder / str(prev.get("master") or "master.mp4")
    why = fills_provenance(prev, sha256_file(master) if master.is_file() else None)
    if why:
        raise CaptionError(f"the captions take a shortfall card's numbers from the render's own measurement, and {why}")
    return prev["card_fills"]["values"]


def captions(path: Path, fills: dict | None = None) -> str:
    play = json.loads(find_screenplay(path).read_text(encoding="utf-8"))
    return to_vtt(build_cues(fill_play(play, fills if fills is not None else render_fills(path))))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="English captions (WebVTT) from a screenplay's subtitle_source.")
    ap.add_argument("source", type=Path, help="a render's output directory, a film directory, or a screenplay JSON")
    ap.add_argument("-o", "--out", type=Path, help="where to write the VTT (default: captions-en.vtt beside the screenplay)")
    args = ap.parse_args(argv)
    try:
        screenplay = find_screenplay(args.source)
        text = captions(screenplay)
    except (CaptionError, OSError, KeyError, json.JSONDecodeError) as e:
        print(f"captions: {e}", file=sys.stderr)
        return 1
    out = args.out or screenplay.parent / "captions-en.vtt"
    out.write_text(text, encoding="utf-8", newline="\n")
    print(f"captions: wrote {out} ({text.count(' --> ')} cues) from {screenplay.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
