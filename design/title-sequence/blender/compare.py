"""Side-by-side: the approved style frame (left) against the built proof (right), one sheet per beat.

    python design/title-sequence/blender/compare.py --proofs <dir> --record S-130 --out <dir>
"""

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
SHOTS = HERE.parent / "frames" / "shots"
BEATS = {1: ("01-clay.png", 36), 4: ("04-press.png", 432), 8: ("08-reel.png", 852),
         11: ("11-record.png", 1176), 12: ("12-lockup.png", 1308)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proofs", required=True)
    ap.add_argument("--record", default="S-130")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    font = ImageFont.load_default(size=22)
    for beat, (shot, f) in BEATS.items():
        left = Image.open(SHOTS / shot).convert("RGB").resize((960, 540), Image.LANCZOS)
        p = Path(a.proofs) / f"{a.record}_{f:04d}.png"
        if not p.exists():
            continue
        right = Image.open(p).convert("RGB").resize((960, 540), Image.LANCZOS)
        sheet = Image.new("RGB", (1940, 590), (24, 24, 24))
        sheet.paste(left, (0, 50))
        sheet.paste(right, (980, 50))
        d = ImageDraw.Draw(sheet)
        d.text((10, 14), f"beat {beat}: approved style frame ({shot})", fill=(237, 226, 207), font=font)
        d.text((990, 14), f"built proof, frame {f} ({f / 24:.2f} s), {a.record}", fill=(237, 226, 207), font=font)
        sheet.save(out / f"compare-beat{beat:02d}-{a.record}.png")
        print(out / f"compare-beat{beat:02d}-{a.record}.png")


if __name__ == "__main__":
    main()
