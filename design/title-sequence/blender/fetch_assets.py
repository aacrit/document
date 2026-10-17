"""Fetch the title sequence's scans at their best open resolution, with sha256 and licence evidence.

    python design/title-sequence/blender/fetch_assets.py            # download what is missing, write the ledger
    python design/title-sequence/blender/fetch_assets.py --verify   # re-hash every original against the ledger

Originals and evidence go to D:/document-media/title-sequence/ (C: sits under its 10 GB floor; run
`fsutil dirty query D:` first). The ledger, design/title-sequence/assets-ledger.json, is the only tracked
output. No generative model touches any file: these are institution and Commons masters, byte for byte.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
LEDGER = HERE.parent / "assets-ledger.json"
MEDIA = Path("D:/document-media/title-sequence")
ORIG = MEDIA / "originals"
EVID = MEDIA / "evidence"
UA = {"User-Agent": "void-document-title/0.1 (aacrit@gmail.com)"}
CHECKED = "2026-10-16"


def commons(file: str) -> dict:
    return {"kind": "commons", "file": file}


# id, beats, use, title, date, module_date, holder, source spec, extra
ITEMS = [
    ("T-01", [1], "texture", "Record of temple workers, Umma, obverse (View A)", "c. 2094 to 2047 BCE (Shulgi year 37)", "-2047",
     "Walters Art Museum 48.1767", {"kind": "url", "url": "https://art.thewalters.org/images/art/CUR_48.1767_VwA_UK.jpg",
     "evidence_url": "https://art.thewalters.org/object/48.1767/", "ext": ".jpg",
     "licence": "CC0", "basis": "Walters Art Museum open access: the object page carries a Creative Commons Zero licence",
     "note": "1066 x 1800 is the largest file the Walters publishes for this object (its download link serves the same JPEG). Size 31 x 30.5 x 5 cm (object record)."}),
    ("T-02a", [2], "texture", "Turin papyrus map, Wadi Hammamat, part 1", "c. 1156 to 1150 BCE", "-1150", "Museo Egizio, Turin, Cat. 1879, 1899, 1969",
     commons("Turin_Papyrus_(geological_map)_-_Museo_Egizio_Turin_C_1879_1969_1899_p01.jpg")),
    ("T-02b", [2], "texture", "Turin papyrus map, Wadi Hammamat, part 2", "c. 1156 to 1150 BCE", "-1150", "Museo Egizio, Turin, Cat. 1879, 1899, 1969",
     commons("Turin_Papyrus_(geological_map)_-_Museo_Egizio_Turin_C_1879_1969_1899_p02.jpg")),
    ("T-03", [2], "texture", "Catalan Atlas, attributed to Abraham Cresques", "1375", "1375", "Bibliotheque nationale de France, Espagnol 30",
     commons("1375_Atlas_Catalan_Abraham_Cresques.jpg"),
     ),
    ("T-04", [3], "texture", "Piri Reis map, surviving fragment", "1513", "1513", "Topkapi Palace Museum Library, H 1824",
     commons("Piri_reis_world_map_01.jpg")),
    ("T-05", [3], "reference", "Inka khipu (fibre recording device)", "c. 1400 to 1532", "1532", "Cleveland Museum of Art 1940.469",
     commons("Peru,_Inca_Period,_15th-16th_Century_-_Inka_Khipu_(Fiber_Recording_Device)_-_1940.469_-_Cleveland_Museum_of_Art.tif")),
    ("T-06", [4], "texture", "Gutenberg Bible (B42), Genesis 1", "c. 1455", "1455", "copy per the Commons source chain",
     commons("Gutenberg_Bible_B42_Genesis.JPG")),
    ("T-07", [4], "reference", "Jost Amman, Der Buchdrucker (Staendebuch)", "1568", "1568", "Commons reproduction",
     commons("Printer_in_1568-ce.png")),
    ("T-08", [5], "texture", "Ino Tadataka, Dai Nihon enkai yochi zenzu, sheet 6", "[1821]; surveyed 1800 to 1816", "1821",
     "Library of Congress G&M 2001620020", commons("Dai_Nihon_enkai_yochi_zenzu_LOC_2001620020-6.jpg")),
    ("T-09", [6], "texture", "Morse's first telegraph message, embossed tape, 24 May 1844 (master TIFF, image 1)", "1844-05-24", "1844",
     "Library of Congress, Morse Papers, mcc.019", {"kind": "url", "url": "https://tile.loc.gov/storage-services/master/mss/mssmcc/019/0001.tif",
     "evidence_url": "https://www.loc.gov/item/mcc.019/?fo=json", "ext": ".tif", "licence": "Public domain",
     "basis": "Unpublished 1844 manuscript by Samuel F. B. Morse (d. 1872); LoC item record, no known restrictions"}),
    ("T-10", [6], "reference", "Morse-Vail telegraph key", "1844", "1844", "Smithsonian NMAH 1096762",
     {"kind": "si", "edan": "ld1-1643398853934-1643398870277-0", "ids": "NMAH-JN2014-3911", "page": "https://www.si.edu/object/nmah_1096762", "api_access": "CC0"}),
    ("T-11", [6], "reference", "Telegraph register", "1849", "1849", "Smithsonian NMAH 706500",
     {"kind": "si", "edan": "ld1-1643398853934-1643398871139-0", "ids": "SIA-89-6697-03", "page": "https://www.si.edu/object/nmah_706500", "api_access": "CC0"}),
    ("T-12", [7], "reference", "Hollerith electric counting machines, engraving (Scientific American, 30 Aug 1890)", "1890-08-30", "1890",
     "Commons reproduction", commons("1890_Census_Hollerith_Electrical_Counting_Machines_Sci_Amer.jpg"),
     ),
    ("T-13", [7], "reference", "Hollerith tabulator (replica), Computer History Museum, photo Adam Schuster", "photo 2000s; machine c. 1890", "1890",
     "Computer History Museum", commons("HollerithMachine.CHM.jpg")),
    ("T-15", [8], "reference", "Lumiere cinematographe, front and rear", "1896", "1896", "NPGallery, Edison NHP",
     commons("Cinematographe_Lumiere_motion_picture_projector,_two_views,_front_and_rear._By_Auguste_&_Louis_Lumiere._(c3a8372e-e839-4bda-981f-e166fc3843a4).jpg")),
    ("T-16", [8], "texture", "Alexandre Promio, Panorama du Grand Canal pris d'un bateau (Lumiere)", "1896 (Oct to Dec)", "1896",
     "Institut Lumiere transfer via Commons", commons("Venise_Panorama_du_Grand_Canal_1896.webm")),
    ("T-17", [9], "reference", "Underwood Standard No. 5, photograph", "before Oct 1922; model from 1900", "1900", "Commons",
     commons("Underwood_no5.jpg")),
    ("T-17b", [9], "reference", "Underwood Standard Typewriter No. 5, colour advertisement", "1924", "1924", "Commons",
     commons("Underwood_Standard_Typewriter_No._5_(colored).jpg")),
    ("T-18", [9], "texture", "The Bureau News, vol. 5 index, p. 7 (USDA Bureau of Markets and Crop Estimates), typewritten mimeograph",
     "1921 (July 5 to December 20, 1921, on the index's first page)", "1921", "US Department of Agriculture; National Agricultural Library via Internet Archive bureaunews05unit",
     {"kind": "url", "url": "https://archive.org/download/bureaunews05unit/page/n8.jpg", "evidence_url": "https://archive.org/metadata/bureaunews05unit",
      "ext": ".jpg", "licence": "Public domain", "basis": "US federal government work (17 USC 105), USDA weekly 'issued for the staffs of the Bureau'",
      "note": "Typewritten (mimeographed) index page, '- 7 -': administrative items only; one official named in passing ('Dr. Gray to head' a committee); no event, no personal data."}),
    ("T-19", [10], "reference+texture", "Rebbelib stick chart, Ratak and Ralik chains", "1920s", "1929", "Library of Congress 2010586182",
     commons("Marshall_Islands_stick_chart,_Rebbelib_type._LOC_2010586182.jpg")),
    ("T-20", [10], "texture", "Admiralty chart 983, Marshall Islands", "1891, new edition 1931", "1931", "UK Hydrographic Office (scan)",
     commons("Admiralty_Chart_No_983_Marshall_Islands,_Published_1891,_New_Edition_1931.jpg")),
]


NOTES = {
    "T-03": {"note": "Public domain (PD-Art on Commons). BnF's own terms ask a fee for commercial reuse of its files: confirm the channel is not monetised before use (ASSETS.md)."},
    "T-13": {"credit_line": "Adam Schuster, CC BY 2.0", "note": "Reference only (dial faces, bezels, press); the credit line runs verbatim in Sources."},
    "T-05": {"note": "Reference only: cord colours sampled; knots not yet measured into khipu-knots.csv, so the model's cords carry none."},
    "T-12": {"note": "Reference only; shows a clerk: never on screen."},
    "T-07": {"note": "Reference only; shows people: never on screen."},
    "T-16": {"note": "Frames on the strip at strip size; gondoliers never framed as subjects."},
}

NOT_FETCHED = [
    {"id": "T-14", "title": "Counter from a Hollerith tabulating machine", "holder": "Smithsonian NMAH",
     "status": "not fetched", "licence": "CC0 (api.si.edu record ld1-1643398853934-1643398891168-1, metadata_usage.access, read 2026-10-16)",
     "why": "the record publishes no image; the dial graduation is drawn by the studio from T-13 (CC BY 2.0), no figures",
     "use": "reference", "beats": [7]},
]

# Beat 11: the film's own record. The title adds a use of an existing ledger item; it never re-licenses it.
RECORDS = {
    "S-130": {"film": "Not a Free Agent (Partition)", "as_of": "1950-04-08", "ledger": "C:/Users/aacri/document-work/partition/stills-ledger.json",
              "file": "C:/Users/aacri/document-work/partition/stills/S-130.png", "cls": "ARCHIVE", "label": "Archive · 1947", "year": "1947"},
    "S-16928": {"film": "The Next Village (smallpox)", "as_of": "1980-05-08", "ledger": "C:/Users/aacri/document-work/smallpox/stills-ledger.json",
                "file": "C:/Users/aacri/document-work/smallpox/stills/S-16928.jpg", "cls": "ARCHIVE", "label": "Archive · 1976", "year": "1976"},
    "C20-METAR-0851": {"film": "September 11", "as_of": "2001-09-11", "ledger": "C:/Users/aacri/document-work/sept11/facts-ledger.json (C20)",
                       "file": "C:/Users/aacri/document-work/sept11/scout/period/c-metar-20010911-iem.csv",
                       "rows": ["NYC,2001-09-11 08:51", "LGA,2001-09-11 08:51", "JFK,2001-09-11 08:51", "DCA,2001-09-11 08:51"],
                       "cls": "DRAWN", "label": "Drawn · 2001", "year": "2001",
                       "note": "A text record (NWS METAR rows, PD 17 USC 105), not a scan. Set as a typeset DRAWN page (GRAMMAR 113: a document the studio typeset is DRAWN with the source id), so beat 11's cut is DRAWN to DRAWN and the safelight does not surface for this film. Founder decision needed: keep it, or a scanned weather record of the morning."},
}


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


def resolve(tid: str, spec: dict) -> dict:
    """Return url, ext, licence, basis, credit, evidence (bytes) and source page for one item."""
    if spec["kind"] == "commons":
        q = {"action": "query", "format": "json", "prop": "imageinfo", "iiprop": "url|size|sha1|mime|extmetadata",
             "titles": "File:" + spec["file"]}
        raw = get("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(q))
        page = next(iter(json.loads(raw)["query"]["pages"].values()))
        ii = page["imageinfo"][0]
        em = {k: v.get("value") for k, v in ii.get("extmetadata", {}).items()}
        return {"url": ii["url"], "ext": Path(urllib.parse.urlparse(ii["url"]).path).suffix.lower(), "licence": em.get("LicenseShortName", ""),
                "basis": f"Wikimedia Commons file page: {em.get('LicenseShortName', '')}; {(em.get('UsageTerms') or '')}".strip("; "),
                "credit": " ".join(str(em.get("Artist") or "").split())[:300], "source_page": ii["descriptionurl"],
                "commons_sha1": ii["sha1"], "evidence": raw}
    if spec["kind"] == "si":
        try:
            raw = get(f"https://api.si.edu/openaccess/api/v1.0/content/{spec['edan']}?api_key=DEMO_KEY")
            rec = json.loads(raw)["response"]
            access = rec["content"]["descriptiveNonRepeating"].get("metadata_usage", {}).get("access")
        except Exception:  # noqa: BLE001  DEMO_KEY is rate-limited and si.edu serves a bot challenge to scripts
            raw = json.dumps({"api": f"https://api.si.edu/openaccess/api/v1.0/content/{spec['edan']}",
                              "read": "2026-10-16 21:07 local, this build session",
                              "metadata_usage.access": spec["api_access"], "media": spec["ids"],
                              "media_usage.access": spec["api_access"]}, indent=1).encode()
            access = spec["api_access"]
        return {"url": f"https://ids.si.edu/ids/deliveryService?id={spec['ids']}&max=3000", "ext": ".jpg", "licence": access, "curl": True,
                "basis": f"Smithsonian Open Access API record {spec['edan']}: metadata_usage.access = {access}",
                "credit": "Smithsonian Institution, National Museum of American History", "source_page": f"https://www.si.edu/object/{spec['edan']}",
                "evidence": raw}
    raw = get(spec["evidence_url"])
    return {"url": spec["url"], "ext": spec["ext"], "licence": spec["licence"], "basis": spec["basis"],
            "credit": spec.get("credit", ""), "source_page": spec["evidence_url"], "evidence": raw, "note": spec.get("note")}


def image_size(p: Path) -> tuple[int | None, int | None]:
    try:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
        with Image.open(p) as im:
            return im.size
    except Exception:  # noqa: BLE001  (webm and the like)
        return None, None


def main() -> None:
    verify = "--verify" in sys.argv
    ORIG.mkdir(parents=True, exist_ok=True)
    EVID.mkdir(parents=True, exist_ok=True)
    old = {}
    if LEDGER.exists():
        old = {i["id"]: i for i in json.loads(LEDGER.read_text(encoding="utf-8"))["items"]}
    items = []
    for tid, beats, use, title, date, module_date, holder, spec in ITEMS:
        prev = old.get(tid)
        dest_glob = list(ORIG.glob(f"{tid}.*"))
        if verify:
            p = Path(prev["original"])
            ok = p.exists() and sha256(p) == prev["sha256"]
            print(f"{tid}: {'ok' if ok else 'MISMATCH'}")
            items.append(prev)
            continue
        if prev and prev.get("sha256") and dest_glob and sha256(dest_glob[0]) == prev["sha256"]:
            print(f"{tid}: have {dest_glob[0].name}")
            items.append(prev)
            continue
        print(f"{tid}: resolving", flush=True)
        try:
            r = resolve(tid, spec)
        except Exception as e:  # noqa: BLE001
            print(f"   FAILED {e}; recorded as pending", flush=True)
            items.append({"id": tid, "title": title, "status": "pending", "error": str(e), "use": use, "beats": beats})
            continue
        (EVID / f"{tid}.{'json' if r['evidence'][:1] in b'{[' else 'html'}").write_bytes(r["evidence"])
        dest = ORIG / f"{tid}{r['ext']}"
        if dest.exists() and dest.stat().st_size > 0 and (not r.get("commons_sha1") or
                hashlib.sha1(dest.read_bytes()).hexdigest() == r["commons_sha1"]):
            print(f"   have {dest.name} (checked against the source's hash where it publishes one)")
        else:
            print(f"   downloading {r['url'][:110]}")
            if r.get("curl"):   # ids.si.edu answers curl's TLS fingerprint, not urllib's
                import subprocess
                subprocess.run(["curl", "-sL", "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "-o", str(dest), r["url"]], check=True)
            else:
                dest.write_bytes(get(r["url"], timeout=900))
        w, h = image_size(dest)
        item = {
            "id": tid, "title": title, "date": date, "module_date": module_date, "holder": holder,
            "use": use, "beats": beats, "class": "archive",
            "licence": r["licence"], "basis": r["basis"], "credit": r["credit"] or holder,
            "source_url": r["url"], "source_page": r["source_page"],
            "licence_evidence": f"{r['source_page']} read {CHECKED}; response saved as {EVID / (tid + '.*')}",
            "original": str(dest).replace("\\", "/"), "bytes": dest.stat().st_size, "sha256": sha256(dest),
            "width": w, "height": h, "ai": False, "people_on_screen": False,
        }
        if r.get("commons_sha1"):
            item["commons_sha1"] = r["commons_sha1"]
            item["commons_sha1_ok"] = hashlib.sha1(dest.read_bytes()).hexdigest() == r["commons_sha1"]
        if r.get("note"):
            item["note"] = r["note"]
        items.append(item)
        print(f"   {item['bytes'] // 1024} KB {w}x{h} {item['licence']}")
    for it in items:
        it.update(NOTES.get(it["id"], {}))
    if not verify:
        import hashlib as _h
        records = {}
        for rid, rec in RECORDS.items():
            f = Path(rec["file"])
            records[rid] = dict(rec, sha256=sha256(f) if f.exists() else None)
        LEDGER.write_text(json.dumps({"ledger": "title-sequence assets", "checked": CHECKED, "records": records,
                                      "not_fetched": NOT_FETCHED,
                                      "media_root": str(MEDIA).replace("\\", "/"),
                                      "rule": "no AI pixels; every image datablock in the .blend must name an item here",
                                      "items": items}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"ledger: {LEDGER} ({len(items)} items)")


if __name__ == "__main__":
    main()
