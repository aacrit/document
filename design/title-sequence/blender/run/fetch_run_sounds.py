"""The Run: fetch, pin and decode the Foley recordings (Freesound CC0 HQ previews; house precedent: pin the mp3's
sha256, decode once to 48 kHz mono WAV). Writes design/title-sequence/run-sound-ledger.json.

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/fetch_run_sounds.py

Each sound page is read and saved as licence evidence; a recording whose page does not carry the CC0 deed
(creativecommons.org/publicdomain/zero/1.0) is refused. Media go to D:/document-media/title-sequence/run/sfx/.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
LEDGER = HERE.parents[1] / "run-sound-ledger.json"
SFX = Path("D:/document-media/title-sequence/run/sfx")
EVID = Path("D:/document-media/title-sequence/run/evidence")
UA = {"User-Agent": "void-document-title/0.1 (aacrit@gmail.com)"}
CHECKED = "2026-10-18"

# id, preview path, use in the proofs
WANT = [
    ("197214", "197/197214_770707", "coin spin-down: the bronze disc's whir, its stop placed on the slap (latch)"),
    ("628997", "628/628997_13875907", "marbles knocking: clay rim taps, the papyrus edge, clay on type, clay on clay (low-passed, pitched down)"),
    ("458136", "458/458136_7254624", "a marble dropped onto a table and rolling: drops off the lip and edges; the rolling loop"),
    ("259553", "259/259553_2316086", "small metal object falling: the type falling on brass (pitched up 1.5x), the end stop"),
    # v4 (design section 7): a small bearing's spin-down for the two reels, in place of the pitched coin stand-in
    ("509902", None, "a spinning reel: the register reel's and the Lumiere reel's whir and settle (v4)"),
    ("376517", None, "a spinning bearing: the second take for the reels' whir (v4)"),
]


def get(url: str) -> bytes:
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read()


def main():
    SFX.mkdir(parents=True, exist_ok=True)
    EVID.mkdir(parents=True, exist_ok=True)
    rows = []
    for sid, prev, use in WANT:
        page = EVID / f"fs-{sid}.html"
        if not page.exists():
            page.write_bytes(get(f"https://freesound.org/s/{sid}/"))
        html = page.read_text(encoding="utf-8", errors="ignore")
        lic = sorted(set(re.findall(r"creativecommons\.org/[a-z/.0-9]+", html)))
        if lic != ["creativecommons.org/publicdomain/zero/1.0/"]:
            sys.exit(f"{sid}: licence on the page is {lic}, not CC0")
        title = re.search(r"<title>Freesound - (.*?) by (.*?)</title>", html)
        name, uploader = (title.group(1).strip(), title.group(2).strip()) if title else ("?", "?")
        page_url = re.search(r'<link rel="canonical" href="([^"]+)"', html)
        if prev is None:
            # the preview's path is read from the sound's own page (it carries the uploader's id)
            m = re.search(r"https://cdn\.freesound\.org/previews/(\d+/\d+_\d+)-hq\.mp3", html)
            if not m:
                sys.exit(f"{sid}: no HQ preview on its page")
            prev = m.group(1)
        mp3 = SFX / f"{Path(prev).name}-hq.mp3"
        url = f"https://cdn.freesound.org/previews/{prev}-hq.mp3"
        if not mp3.exists():
            mp3.write_bytes(get(url))
        wav = mp3.with_suffix(".wav")
        if not wav.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(mp3), "-ar", "48000", "-ac", "1", str(wav)], check=True)
        rows.append({"id": f"FS{sid}", "title": name, "uploader": uploader,
                     "source_page": page_url.group(1) if page_url else f"https://freesound.org/s/{sid}/",
                     "file_pinned": url, "file": mp3.name, "decoded": wav.name,
                     "mp3_sha256": hashlib.sha256(mp3.read_bytes()).hexdigest(),
                     "licence": f"CC0 1.0 (the sound page's licence line, read {CHECKED})",
                     "licence_evidence": str(page).replace("\\", "/"), "credit_line": f"{uploader} on Freesound (CC0)",
                     "kind": "recording", "claims_period": False, "ai": False, "use": use})
    LEDGER.write_text(json.dumps({
        "ledger": "The Run: Foley recordings (proofs)", "checked": CHECKED,
        "precedent": "the original WAVs need a Freesound login; the HQ preview MP3 is pinned and decoded once (house room tone 329569)",
        "ir": {"file": "D:/document-media/house-room/AIR_1_4/air_binaural_lecture_1_1_2.mat", "var": "h_air", "sr": 48000,
               "what": "Aachen Impulse Response database, lecture room (the house IR)"},
        "room_tone": "D:/document-media/house-room/roomtone/house-roomtone-329569.json (Freesound 329569, leonelmail, CC0)",
        "recordings": rows}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for r in rows:
        print(r["id"], r["uploader"], r["mp3_sha256"][:16], r["title"])


if __name__ == "__main__":
    main()
