"""Title B "Chart": fetch its two scans, pin them, prepare the textures and write the Chart ledger.

    python design/title-sequence/blender/chart/fetch_chart_assets.py            # fetch what is missing, prep, ledger
    python design/title-sequence/blender/chart/fetch_chart_assets.py --verify   # re-hash originals and textures

C-01 Herman Moll, A New and Correct Map of the Whole World, 1719 (NYPL Map Division, image 1630430, CC0), at the
largest size NYPL serves (its "g" derivative, 8523 x 5083; the Commons copy of the same NYPL file is 8525 x 5069).
C-02 Poly Haven "Oak Wood Planks" (CC0), 4k diffuse, GL normal and roughness: the plain planked table top.

Originals, evidence and textures go to D:/document-media/title-sequence/chart/ (C: is under its floor). The tracked
outputs are design/title-sequence/chart-assets-ledger.json (same item shape as assets-ledger.json) and the texture
manifest on D:, chart/tex-manifest.json. No generative model touches any file. The film's record (R-S-16928 etc.)
is not re-fetched: it is read from the machine title's tex-manifest.json with its pinned sha256.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

Image.MAX_IMAGE_PIXELS = None

HERE = Path(__file__).resolve().parent
TS = HERE.parents[1]                                   # design/title-sequence
LEDGER = TS / "chart-assets-ledger.json"
MACHINE_LEDGER = TS / "assets-ledger.json"
MEDIA = Path("D:/document-media/title-sequence/chart")
ORIG, EVID, TEX = MEDIA / "originals", MEDIA / "evidence", MEDIA / "tex"
MANIFEST = MEDIA / "tex-manifest.json"
UA = {"User-Agent": "void-document-title/0.1 (aacrit@gmail.com)"}
CHECKED = "2026-10-17"
TEX_MAX = 8192                                         # Cycles texture_limit_render in the house setup

MOLL_COMMONS = ("A_new_and_correct_map_of_the_whole_world,_shewing_ye_situation_of_its_principal_parts._..."
                "_according_to_the_newest_and_most_exact_observations_-_by_Herman_Moll,_geographer,_1719._NYPL1630430.jpg")
MOLL_CROP = (72, 72, 8512, 5024)                       # inside the sheet: the scan's blue-grey ground cut off
PH = "https://dl.polyhaven.org/file/ph-assets/Textures/jpg/4k/oak_wood_planks/oak_wood_planks_{map}_4k.jpg"

ITEMS = [
    {"id": "C-01", "use": "texture", "beats": [2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
     "title": "Herman Moll, A New and Correct Map of the Whole World (Mercator projection)",
     "date": "1719 (engraved date on the cartouche)", "content_date": "1719", "module_date": "1719",
     "holder": "The New York Public Library, Lionel Pincus and Princess Firyal Map Division (image ID 1630430)",
     "basis_object": "the object itself: the 1719 sheet as NYPL scanned it, byte for byte; the studio only crops off the scan's ground",
     "class": "archive", "licence": "CC0",
     "basis": "NYPL Digital Collections public-domain release; the same NYPL file on Wikimedia Commons carries "
              "'Creative Commons CC0 1.0 Universal Public Domain Dedication' (LicenseShortName CC0)",
     "credit": "Herman Moll, 1719. The New York Public Library, Lionel Pincus and Princess Firyal Map Division",
     "source_url": "https://images.nypl.org/index.php?id=1630430&t=g",
     "source_page": "http://digitalgallery.nypl.org/nypldigital/dgkeysearchdetail.cfm?imageID=1630430",
     "commons_page": "https://commons.wikimedia.org/wiki/File:" + MOLL_COMMONS,
     "ext": ".jpg", "people_on_screen": False,
     "note": "The design's Arrowsmith 1790 chart is replaced by this map (founder ruling 7.2, 2026-10-17). "
             "The cartouche figures are engraved allegories, not photographs of people."},
    {"id": "C-02", "use": "texture", "beats": [2, 3, 4, 5, 6, 7, 8],
     "title": "Poly Haven, Oak Wood Planks (varnished planks, 1.2 m x 1.2 m), by Dimitrios Savva",
     "date": "scanned surface (modern photograph of a plain planked top)", "content_date": "form",
     "module_date": "form", "holder": "Poly Haven",
     "basis_object": "form: a plain planked wooden top with no modern hardware in frame (design 2.1)",
     "class": "texture", "licence": "CC0",
     "basis": "Poly Haven licence page: every asset is CC0; api.polyhaven.com/info/oak_wood_planks read 2026-10-17",
     "credit": "Dimitrios Savva, Poly Haven (CC0)",
     "source_url": PH.format(map="diff"), "source_page": "https://polyhaven.com/a/oak_wood_planks",
     "maps": {"diff": PH.format(map="diff"), "nor_gl": PH.format(map="nor_gl"), "rough": PH.format(map="rough")},
     "md5": {"diff": "afdebae04b31a4f77ca878d9c8292daa", "nor_gl": "6afff3c8f29ac342026db49f12e1c1fe",
             "rough": "e9a7285184bc6d77d4715756bdb9c542"},
     "ext": ".jpg", "people_on_screen": False, "size_m": [1.2, 1.2]},
]


def get(url: str, timeout: int = 300) -> bytes:
    for attempt in range(4):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
        except Exception as e:  # noqa: BLE001
            if attempt == 3:
                raise
            print(f"   retry {attempt + 1}: {e}")
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("unreachable")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url: str, dest: Path, md5: str | None = None) -> Path:
    if not dest.exists():
        data = get(url)
        if md5 and hashlib.md5(data).hexdigest() != md5:
            sys.exit(f"{dest.name}: md5 differs from the publisher's ({md5})")
        dest.write_bytes(data)
        print(f"  fetched {dest.name}: {len(data)} bytes")
    return dest


def man_entry(name: str, src: str, op: str, p: Path, cls: str, extra: dict | None = None) -> dict:
    with Image.open(p) as im:
        size = list(im.size)
    e = {"from": src, "op": op, "class": cls, "tex": {"file": str(p).replace("\\", "/"), "size": size, "sha256": sha256(p)}}
    e.update(extra or {})
    return e


def main() -> None:
    for d in (ORIG, EVID, TEX):
        d.mkdir(parents=True, exist_ok=True)
    verify = "--verify" in sys.argv
    old = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {}
    old_items = {i["id"]: i for i in old.get("items", [])}
    items, man = [], {}

    # C-01 Moll 1719
    moll = dict(ITEMS[0])
    o = fetch(moll["source_url"], ORIG / "C-01.jpg")
    ev = EVID / "C-01.commons.json"
    if not ev.exists():
        q = {"action": "query", "format": "json", "prop": "imageinfo|revisions", "rvprop": "content", "rvslots": "main",
             "iiprop": "url|size|sha1|extmetadata", "titles": "File:" + MOLL_COMMONS}
        ev.write_bytes(get("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(q)))
    page = next(iter(json.loads(ev.read_text(encoding="utf-8"))["query"]["pages"].values()))
    ii = page["imageinfo"][0]
    lic = ii["extmetadata"]["LicenseShortName"]["value"]
    if lic != "CC0":
        sys.exit(f"C-01: the Commons record reads {lic!r}, not CC0")
    with Image.open(o) as im:
        w, h = im.size
    moll.update(original=str(o).replace("\\", "/"), bytes=o.stat().st_size, sha256=sha256(o), width=w, height=h, ai=False,
                commons_size=[ii["width"], ii["height"]], commons_sha1=ii["sha1"],
                licence_evidence=f"{moll['commons_page']} read {CHECKED}; API response saved as {ev}")
    if verify and old_items.get("C-01", {}).get("sha256") not in (None, moll["sha256"]):
        sys.exit("C-01: original bytes differ from the ledger")
    t = TEX / "C-01_chart.jpg"
    if not t.exists():
        with Image.open(o) as im:
            c = im.convert("RGB").crop(MOLL_CROP)
            k = TEX_MAX / max(c.size)
            if k < 1:
                c = c.resize((round(c.width * k), round(c.height * k)), Image.LANCZOS)
            c.save(t, quality=95, subsampling=0)
    man["C-01_chart"] = man_entry("C-01_chart", "C-01", f"crop {MOLL_CROP}, Lanczos to {TEX_MAX} px on the long side",
                                  t, "archive", {"sheet_m": [0.97, round(0.97 * 4952 / 8440, 4)]})
    items.append(moll)

    # C-02 Poly Haven oak planks
    oak = dict(ITEMS[1])
    info = EVID / "C-02.polyhaven-info.json"
    if not info.exists():
        info.write_bytes(get("https://api.polyhaven.com/info/oak_wood_planks"))
    files = {}
    for k, url in oak["maps"].items():
        p = fetch(url, ORIG / f"C-02_{k}.jpg", oak["md5"][k])
        files[k] = {"original": str(p).replace("\\", "/"), "bytes": p.stat().st_size, "sha256": sha256(p)}
        man[f"C-02_{k}"] = man_entry(f"C-02_{k}", "C-02", "as published (4k jpg)", p, "texture",
                                     {"noncolor": k != "diff", "size_m": oak["size_m"]})
    oak.update(original=files["diff"]["original"], bytes=files["diff"]["bytes"], sha256=files["diff"]["sha256"],
               files=files, width=4096, height=4096, ai=False,
               licence_evidence=f"{info} (api.polyhaven.com/info/oak_wood_planks, read {CHECKED}); https://polyhaven.com/license")
    if verify:
        for k, f in files.items():
            prev = old_items.get("C-02", {}).get("files", {}).get(k, {}).get("sha256")
            if prev not in (None, f["sha256"]):
                sys.exit(f"C-02 {k}: bytes differ from the ledger")
    items.append(oak)

    # the film's records: used as the machine title pins them (never re-licensed here)
    machine = json.loads(MACHINE_LEDGER.read_text(encoding="utf-8"))
    mman = json.loads(Path("D:/document-media/title-sequence/tex-manifest.json").read_text(encoding="utf-8"))
    for rid in machine["records"]:
        name = f"R-{rid}"
        if name in mman:
            e = mman[name]
            if sha256(Path(e["tex"]["file"])) != e["tex"]["sha256"]:
                sys.exit(f"{name}: bytes differ from the machine title's manifest")
            man[name] = {"from": rid, "op": e["op"], "class": e["class"], "tex": e["tex"]}

    MANIFEST.write_text(json.dumps(man, indent=1) + "\n", encoding="utf-8")
    LEDGER.write_text(json.dumps({
        "ledger": "title-sequence assets: Title B, Chart", "checked": CHECKED,
        "design": "reports/briefs/document-title-and-score-design.md (agentique) 2.1, 2.3, 7",
        "records": machine["records"], "records_from": "design/title-sequence/assets-ledger.json (same files, same sha256)",
        "media_root": str(MEDIA).replace("\\", "/"), "studio": {
            "world": "uniform 18% grey, no HDRI (procedural)", "lamp": "one area lamp, 4300 K, above and left (procedural)",
            "paper_fibre": "bump from the C-01 scan's own paper (high-passed luminance in the shader) plus a procedural "
                           "fibre noise; no fibre image beyond C-01"},
        "rule": "no AI pixels; every image datablock in the Chart .blend names an item here or a film's record",
        "items": items}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"ledger: {LEDGER} ({len(items)} items); manifest: {MANIFEST} ({len(man)} textures)")
    for k, v in man.items():
        print(f"  {k}: {v['tex']['size']} sha256 {v['tex']['sha256'][:16]}")


if __name__ == "__main__":
    main()
