"""The Run v4.1: fetch and pin the real-scan objects of the collector's desk (CC0 photogrammetry on Sketchfab).

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/fetch_run_models.py

Sketchfab serves CC0 downloads only to a signed-in account. The token is read from the SKETCHFAB_TOKEN environment
variable in the download request alone; it is never printed, logged, written, committed or put in a command line, and
any error text is scrubbed of it. Each model's licence is read from Sketchfab's own model record (must be CC0) and saved
as evidence; the glTF archive is pinned by its URL page, licence and sha256 in design/title-sequence/run-model-ledger.json.
Media go to D:/document-media/title-sequence/run/models/.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bench as B  # noqa: E402

LEDGER = HERE.parents[1] / "run-model-ledger.json"
OUT = Path("D:/document-media/title-sequence/run/assets")
UA = "void-document-title/0.1 (aacrit@gmail.com)"
CHECKED = "2026-10-18"


def _token() -> str:
    """The token, read fresh from the Windows user environment (a newly set user variable is not in this process's
    environment) or from this process's. Never printed, logged or written."""
    tok = os.environ.get("SKETCHFAB_TOKEN") or ""
    if not tok and sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                tok = winreg.QueryValueEx(k, "SKETCHFAB_TOKEN")[0] or ""
        except OSError:
            tok = ""
    return tok


def _scrub(text: str) -> str:
    tok = _token()
    return text.replace(tok, "[token]") if tok else text


def _get(url: str, auth: bool = False) -> bytes:
    h = {"User-Agent": UA}
    if auth:
        h["Authorization"] = "Token " + _token()
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=180).read()
    except Exception as e:  # noqa: BLE001
        raise SystemExit(_scrub(f"{type(e).__name__} for {url}: {e}")) from None


def wanted():
    out = [("globe", B.GLOBE["uid"]), ("scale", B.SCALE["uid"]), ("weights", B.WEIGHTS["uid"]), ("jeton", B.JETON["uid"])]
    out += [(c["id"], c["uid"]) for c in B.COINS]
    return out


def main():
    if not _token():
        sys.exit("SKETCHFAB_TOKEN is in neither this environment nor the user environment: not fetching")
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, uid in wanted():
        rec = json.loads(_get(f"https://api.sketchfab.com/v3/models/{uid}"))
        lic = (rec.get("license") or {}).get("label", "")
        if "CC0" not in lic:
            sys.exit(f"{name}: licence on the model record is {lic!r}, not CC0")
        (OUT / f"{name}.record.json").write_text(json.dumps({k: rec.get(k) for k in ("uid", "name", "license", "user",
                                                                                       "description", "viewerUrl")},
                                                            indent=1, ensure_ascii=False), encoding="utf-8")
        dl = json.loads(_get(f"https://api.sketchfab.com/v3/models/{uid}/download", auth=True))
        src = (dl.get("gltf") or dl.get("glb") or {}).get("url")
        if not src:
            sys.exit(f"{name}: no glTF download offered")
        data = _get(src)                         # a signed, expiring link: the token is not in it
        ext = ".glb" if "glb" in (dl.get("glb") or {}) else ".zip"
        p = OUT / f"{name}{ext}"
        p.write_bytes(data)
        extracted = []
        if ext == ".zip":
            import zipfile
            xdir = OUT / name
            with zipfile.ZipFile(p) as z:
                z.extractall(xdir)
            for f in sorted(xdir.rglob("*")):
                if f.is_file():
                    extracted.append({"file": str(f).replace("\\", "/"), "bytes": f.stat().st_size,
                                      "sha256": hashlib.sha256(f.read_bytes()).hexdigest()})
        rows.append({"id": name, "uid": uid, "title": rec.get("name"), "holder_or_author": (rec.get("user") or {}).get("username"),
                     "source_page": f"https://sketchfab.com/3d-models/{uid}", "licence": lic,
                     "licence_evidence": str(OUT / f"{name}.record.json").replace("\\", "/"), "file": str(p).replace("\\", "/"),
                     "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "kind": "photogrammetry",
                     "extracted": extracted, "gate": "pending (capture method to verify before use)", "checked": CHECKED})
        print(name, rows[-1]["sha256"][:16], len(data))
    LEDGER.write_text(json.dumps({"ledger": "The Run v4.1: real-scan objects", "checked": CHECKED, "models": rows},
                                 indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
