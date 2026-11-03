"""The release step's web packet: what goes to R2 for one film, with the facts
the site prints about it recorded beside them.

From a render folder (``master.mp4``, ``sources.json`` with ``master_sha256``,
and the screenplay the render used), the web encode of the master and the
poster still, it writes to ``--out``:

- ``sources.json``: the render's file plus ``web`` (the web encode's file
  name, sha256 and measured duration) and ``poster`` (the still's ledger id,
  title, creator, date, archive, licence, item link, description and
  sha256), so the site prints only what is tied to the bytes it serves;
  with ``--trailer``, also ``trailer`` (file, sha256, measured duration and
  the edge hashes the contract compares); without it, no trailer is declared
  and the site shows none;
- ``captions-en.vtt`` (studio/engine/captions.py).

It refuses when the web encode's duration differs from the film's by more
than one frame, when ``sources.json`` does not record the master's hash, or
when the master's bytes no longer match it. The film, poster and trailer
are not copied: the printed upload list names them with their hashes.
scripts/release-film.mjs runs this step and the upload.

    python -m studio.engine.publish <render dir> --film <web encode.mp4> --poster <poster.jpg>
        --poster-id S-020 --stills-ledger <stills-ledger.json> --out <packet dir> [--screenplay <file or dir>]
        [--trailer <trailer web encode.mp4>] [--poster-crop WxH+X+Y]

With ``--poster-crop`` (the crop release-film.mjs applied to the still before
its scale, 16:9 within 1%), the poster record carries ``crop`` ({w, h, x, y,
aspect: "16:9"}) and its description stays the ledger's own words (the crop is stated in `crop`)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from studio.engine import captions as C
from studio.engine import policy as POL
from studio.engine.journal import sha256_file
from studio.engine.render import Refused, probe_video

UPLOAD = ("film.mp4", "poster.jpg", "trailer.mp4", "sources.json", "captions-en.vtt")   # trailer.mp4 only when declared


def _creator(text: str | None) -> str | None:
    """The stills ledger sometimes doubles a creator ("Unknown authorUnknown author")."""
    if not text:
        return None
    m = re.fullmatch(r"(.+?)\1", text.strip())
    return m.group(1) if m else text.strip()


EDGE_BYTES = 1 << 20      # contract.yaml's max_bytes for film.mp4


def edge_hashes(path: Path, key: str, n: int = EDGE_BYTES) -> dict:
    """Size and the sha256 of the first and last n bytes, so a scheduled check can compare a large file by two
    byte ranges instead of downloading it (scripts/contract.mjs sha256_matches with max_bytes)."""
    import hashlib
    size = Path(path).stat().st_size
    with open(path, "rb") as fh:
        head = hashlib.sha256(fh.read(n)).hexdigest()
        fh.seek(max(0, size - n))
        tail = hashlib.sha256(fh.read(n)).hexdigest()
    return {f"{key}_size": size, f"{key}_head": head, f"{key}_tail": tail}


CROP_RE = re.compile(r"^(\d+)x(\d+)\+(\d+)\+(\d+)$")
CROP_ASPECT = 16 / 9
CROP_TOLERANCE = 0.01          # a crop within 1% of 16:9


def parse_crop(spec: str) -> dict:
    """``WxH+X+Y`` (scripts/release-film.mjs --poster-crop, applied before the scale) as {w, h, x, y}; refused unless
    it is well formed, non-empty and 16:9 within 1%. Whether it lies inside the still is checked where the still's
    size is known (release-film.mjs, before ffmpeg runs)."""
    m = CROP_RE.match(str(spec or ""))
    if not m:
        raise Refused(f"poster crop {spec!r} is not WxH+X+Y (for example 3200x1800+100+120)")
    w, h, x, y = (int(g) for g in m.groups())
    if w == 0 or h == 0:
        raise Refused(f"poster crop {spec!r} is empty")
    if abs((w / h) / CROP_ASPECT - 1) > CROP_TOLERANCE:
        raise Refused(f"poster crop {spec!r} is {w / h:.4f}:1, not 16:9 within 1%")
    return {"w": w, "h": h, "x": x, "y": y}


def poster_record(ledger: Path, poster_id: str, poster: Path, rule: dict | None = None, *, crop: dict | None = None) -> dict:
    """The poster's record. GRAMMAR A21 (E3): the still must pass the film's
    imagery rule on the same content flags as a shot (``rule``, as the
    render's sources.json states it); with no rule, the default, which is
    the Partition poster rule: shows_bodies (or the older
    shows_violence_or_bodies) stated false, so a still nobody has checked is
    never a poster. With ``crop`` (parse_crop), the record states it and the
    still's description says the poster is cropped to 16:9."""
    data = json.loads(ledger.read_text(encoding="utf-8"))
    items = data.get("items", data) if isinstance(data, dict) else data
    item = next((x for x in items if isinstance(x, dict) and x.get("id") == poster_id), None)
    if item is None:
        raise Refused(f"{poster_id} is not in {ledger}")
    rule = {**POL.DEFAULT_IMAGERY_RULE, "declared": False, **(rule or {})}
    problem = POL.poster_problem(item, rule)
    if problem:
        raise Refused(f"{poster_id} {problem}")
    if not item.get("licence"):
        raise Refused(f"{poster_id} has no licence in the ledger")
    seen = item.get("seen")    # the ledger's own words: the home page's alt text; the crop is stated in `crop`, not here
    return {
        "ledger_id": poster_id,
        "title": item.get("title"),
        "creator": _creator(item.get("creator")),
        "date": item.get("date"),
        "archive": item.get("archive"),
        "licence": item.get("licence"),
        "item_url": item.get("item_url"),
        "description": seen,
        **({"crop": {**{k: crop[k] for k in ("w", "h", "x", "y")}, "aspect": "16:9"}} if crop else {}),
        "file": "poster.jpg",
        "sha256": sha256_file(poster),
    }


def poster_rule(doc: dict, screenplay: Path | None) -> dict | None:
    """The film's imagery rule for the poster: the one the render stated in
    sources.json, else the screenplay's, else None (the default)."""
    if isinstance(doc.get("imagery_rule"), dict):
        return doc["imagery_rule"]
    if screenplay is not None:
        try:
            play = json.loads(C.find_screenplay(Path(screenplay)).read_text(encoding="utf-8"))
        except (C.CaptionError, OSError, ValueError):
            return None
        rule, _ = POL.imagery_rule(play)
        return rule
    return None


def packet(render_dir: Path, *, film: Path, poster: Path, poster_id: str, stills_ledger: Path, out: Path,
           screenplay: Path | None = None, trailer: Path | None = None, poster_crop: dict | None = None) -> dict:
    render_dir, out = Path(render_dir), Path(out)
    doc = json.loads((render_dir / "sources.json").read_text(encoding="utf-8"))
    if not doc.get("master_sha256"):
        raise Refused("sources.json records no master_sha256: run python -m studio.engine.render <film> --out <render dir> --sources-only")
    master = render_dir / str(doc.get("master") or "master.mp4")
    if not master.exists():
        raise Refused(f"no {master.name} in {render_dir}: the packet is checked against the master it describes")
    if sha256_file(master) != doc["master_sha256"]:
        raise Refused(f"{master.name} is not the master this sources.json describes: run --sources-only again")
    fps = float(doc.get("fps") or 24)
    pr = probe_video(film)
    # A browser reports the container's duration; the picture's own is checked too.
    web_dur = float(pr["container_duration_s"] or pr["duration_s"])
    for what, d in (("container", web_dur), ("picture", float(pr["duration_s"]))):
        if abs(d - float(doc["duration_s"])) > 1.0 / fps + 1e-6:
            raise Refused(f"the web encode's {what} runs {d:.3f} s and the film {doc['duration_s']} s: more than one frame apart")
    doc["web"] = {"film": "film.mp4", "film_sha256": sha256_file(film), "film_duration_s": round(web_dur, 4),
                  **edge_hashes(film, "film_sha256")}
    doc["poster"] = poster_record(stills_ledger, poster_id, poster, poster_rule(doc, screenplay), crop=poster_crop)
    doc.pop("trailer", None)
    if trailer is not None:
        tp = probe_video(trailer)
        doc["trailer"] = {"file": "trailer.mp4", "sha256": sha256_file(trailer),
                          "duration_s": round(float(tp["container_duration_s"] or tp["duration_s"]), 4), **edge_hashes(trailer, "sha256")}
    out.mkdir(parents=True, exist_ok=True)
    (out / "sources.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    vtt = C.captions(Path(screenplay) if screenplay else render_dir, fills=(doc.get("card_fills") or {}).get("values"))
    (out / "captions-en.vtt").write_text(vtt, encoding="utf-8", newline="\n")
    return {"sources": out / "sources.json", "captions": out / "captions-en.vtt", "web": doc["web"], "poster": doc["poster"],
            "trailer": doc.get("trailer")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m studio.engine.publish", description=__doc__.split("\n\n")[0])
    ap.add_argument("render_dir", type=Path)
    ap.add_argument("--film", type=Path, required=True, help="the 720p web encode of master.mp4")
    ap.add_argument("--poster", type=Path, required=True, help="the poster still as served (poster.jpg)")
    ap.add_argument("--poster-id", required=True, help="the poster's stills-ledger id, e.g. S-020")
    ap.add_argument("--stills-ledger", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True, help="where sources.json and captions-en.vtt are written")
    ap.add_argument("--trailer", type=Path, default=None, help="the trailer's web encode; omitted, sources.json declares no trailer")
    ap.add_argument("--screenplay", type=Path, default=None, help="the screenplay the render used (default: the render folder's fitted one)")
    ap.add_argument("--poster-crop", default=None, metavar="WxH+X+Y",
                    help="the crop release-film.mjs applied to the still before the scale; recorded in the poster's record")
    a = ap.parse_args(argv)
    try:
        crop = parse_crop(a.poster_crop) if a.poster_crop is not None else None
        r = packet(a.render_dir, film=a.film, poster=a.poster, poster_id=a.poster_id, stills_ledger=a.stills_ledger,
                   out=a.out, screenplay=a.screenplay, trailer=a.trailer, poster_crop=crop)
    except (Refused, C.CaptionError, OSError, KeyError, ValueError) as e:
        print(f"publish: refused: {e}", file=sys.stderr)
        return 2
    print(f"publish: wrote {r['sources']} and {r['captions']}")
    files = [f for f in UPLOAD if f != "trailer.mp4" or r["trailer"]]
    print(f"publish: upload to R2 under <slug>/: {', '.join(files)}")
    print(f"publish: film.mp4 sha256 {r['web']['film_sha256']} ({r['web']['film_duration_s']} s); poster.jpg sha256 {r['poster']['sha256']}")
    print(f"publish: trailer.mp4 sha256 {r['trailer']['sha256']}" if r["trailer"] else "publish: no trailer declared")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
