"""Provenance check for a built title .blend (BLENDER-PLAN.md, principle 4). The reviewer runs it:

    blender -b D:/document-media/title-sequence/blend/title-S-130-proof.blend --python design/title-sequence/blender/check_title.py

Fails (exit 1) when any image datablock is not a manifest texture, when a texture's bytes differ from the manifest's
sha256, when its source is not an item in assets-ledger.json (or a film's record), or when that item is marked ai.
"""

import hashlib
import json
import sys
from pathlib import Path

import bpy

HERE = Path(__file__).resolve().parent
LEDGER = json.loads((HERE.parent / "assets-ledger.json").read_text(encoding="utf-8"))
MAN = json.loads((Path(LEDGER["media_root"]) / "tex-manifest.json").read_text(encoding="utf-8"))
items = {i["id"]: i for i in LEDGER["items"]}
ok_sources = {k for k, v in items.items() if v.get("sha256")} | set(LEDGER["records"])

bad, seen = [], 0
for img in bpy.data.images:
    if not img.filepath:
        continue
    seen += 1
    entry = MAN.get(img.name)
    if entry is None:
        bad.append(f"{img.name}: not in tex-manifest.json")
        continue
    path = Path(bpy.path.abspath(img.filepath)).resolve()
    rec = next((v for k, v in entry.items() if isinstance(v, dict) and Path(v.get("file", "")).resolve() == path), None)
    if rec is None:
        bad.append(f"{img.name}: {path} is not the manifest's file")
        continue
    if hashlib.sha256(path.read_bytes()).hexdigest() != rec["sha256"]:
        bad.append(f"{img.name}: bytes differ from the manifest")
    src = entry.get("from")
    if src not in ok_sources:
        bad.append(f"{img.name}: source {src!r} is not a ledger item")
    if items.get(src, {}).get("ai"):
        bad.append(f"{img.name}: source {src} is marked ai")

if bad:
    print("check_title: FAIL\n  " + "\n  ".join(bad))
    sys.exit(1)
print(f"check_title: ok ({seen} images, each a manifest texture from a ledger item; none ai)")
