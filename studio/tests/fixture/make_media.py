"""Make the fixture film's media at test time; nothing here is committed (R-08).

    python studio/tests/fixture/make_media.py <fixture dir>

- ``stills(dir)``: three test images drawn with PIL at the sizes of the
  ledger stills they stand in for (500x350, 395x316, 300x420), so the
  geometry tests keep landscape, near-4:3 and portrait shapes. They are
  marked DRAWN, never ARCHIVE.
- ``testsrc(path)``: 4 s of ffmpeg's testsrc at 640x480 and 29.97 fps (true
  progressive, so the engine conforms it by frame drop).
- ``telecined``, ``ntsc_dv`` and ``slow`` make the conform tests' clips.
All are test patterns, never archival material.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from studio.engine.render import ffmpeg  # noqa: E402


def _run(args: list[str]) -> None:
    r = subprocess.run([ffmpeg(), "-v", "error", "-y", *args], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"ffmpeg failed: {r.stderr[-500:]}")


def testsrc(dest: Path, seconds: float = 4.0) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(["-f", "lavfi", "-i", f"testsrc=size=640x480:rate=30000/1001:duration={seconds}",
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", str(dest)])
    return dest


MOVING = "testsrc2=size=640x480:rate=24000/1001:duration={s},scroll=horizontal=0.02"


def telecined(dest: Path, seconds: float = 2.0) -> Path:
    """A moving 23.976 fps pattern (``MOVING``) put through 3:2 pulldown to
    29.97 fps, encoded interlaced top field first. The motion makes any
    mixed-field (combed) frame stand out."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(["-f", "lavfi", "-i", MOVING.format(s=seconds),
          "-vf", "telecine=first_field=top:pattern=23", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
          "-flags", "+ildct+ilme", "-pix_fmt", "yuv420p", str(dest)])
    return dest


def ntsc_dv(dest: Path, seconds: float = 4.0) -> Path:
    """720x480 NTSC storage with non-square pixels (SAR 8:9, so DAR 4:3),
    a 23.976 fps pattern pulled down to 29.97 and encoded interlaced top field
    first: the shape of a DV or DVD newsreel transfer."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(["-f", "lavfi", "-i", f"testsrc=size=720x480:rate=24000/1001:duration={seconds}",
          "-vf", "telecine=first_field=top:pattern=23,setsar=8/9", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
          "-flags", "+ildct+ilme", "-pix_fmt", "yuv420p", str(dest)])
    return dest


def slow(dest: Path, seconds: float = 4.0, fps: int = 10) -> Path:
    """A true low-rate source (10 fps progressive, square pixels, 4:3)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(["-f", "lavfi", "-i", f"testsrc=size=640x480:rate={fps}:duration={seconds}",
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", str(dest)])
    return dest


def reel(dest: Path, seconds: float = 8.0) -> Path:
    """A small stand-in for a long reel with its own soundtrack (A26): a moving
    24 fps pattern and a steady 440 Hz tone (about -27 dBFS peak) as its "narration",
    so a span cut from it can be measured and compared frame for frame. The
    narration speaks in phrases (A33: a quote is cut on its speech edges):
    1.15 to 2.25 s, so the fixture's archival span 1.0 to 2.5 s has its 0.15 s
    lead and 0.25 s tail, and 3.2 to 4.0 s; silence between."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    words = "gte(t,1.15)*lt(t,2.25)+gte(t,3.2)*lt(t,4.0)"
    _run(["-f", "lavfi", "-i", f"testsrc2=size=320x240:rate=24:duration={seconds}",
          "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}",
          "-af", f"volume=-9dB,volume=0:enable='not({words})'", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-g", "48", "-pix_fmt", "yuv420p",
          "-c:a", "aac", "-b:a", "128k", "-shortest", str(dest)])
    return dest


def talker(dest: Path, seconds: float = 12.0, cuts=(4.0, 7.0), words=((1.0, 1.8), (4.6, 5.4), (7.5, 8.3), (9.2, 10.0)),
           size: str = "320x240") -> Path:
    """A33 clip-integrity stand-in: a moving 24 fps pattern that changes
    look at each of ``cuts`` (inverted, then grey, alternately: hard cuts
    scdet finds on the frame), and a soundtrack of noise "words" (bursts at
    about -9 dBFS RMS, digital silence between) over ``words`` (start, end),
    so its cuts and speech edges are known to the frame. Lossless video and
    PCM in Matroska."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    edges = [0.0, *cuts, seconds + 1]
    neg = "+".join(f"gte(t,{edges[k]})*lt(t,{edges[k + 1]})" for k in range(1, len(edges) - 1, 2)) or "0"
    grey = "+".join(f"gte(t,{edges[k]})*lt(t,{edges[k + 1]})" for k in range(2, len(edges) - 1, 2)) or "0"
    gate = "+".join(f"gte(t,{a})*lt(t,{b})" for a, b in words) or "0"
    _run(["-f", "lavfi", "-i", f"testsrc2=size={size}:rate=24:duration={seconds}",
          "-f", "lavfi", "-i", f"aevalsrc='0.5*(random(0)*2-1)*({gate})':s=48000:d={seconds}",
          "-vf", f"negate=enable='{neg}',hue=s=0:enable='{grey}'", "-c:v", "libx264", "-qp", "0", "-preset", "ultrafast",
          "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", "-shortest", str(dest)])
    return dest


def magenta(dest: Path, seconds: float = 4.0) -> Path:
    """A moving 24 fps pattern with a magenta cast (green cut to 55%), the
    shape of the 1946 newsreel's transfer cast, for the A14 neutralise test."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(["-f", "lavfi", "-i", f"testsrc2=size=640x480:rate=24:duration={seconds}",
          "-vf", "colorchannelmixer=gg=0.55", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", str(dest)])
    return dest


STILLS = {"FX-STILL-A": (500, 350), "FX-STILL-B": (395, 316), "FX-STILL-C": (300, 420)}


def stills(dest: Path) -> list[Path]:
    """Deterministic test images: a warm gradient (never near the letterbox
    black, so geometry tests can find the picture's edges), a few shapes and
    the image's own label."""
    from PIL import Image, ImageDraw
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for k, (sid, (w, h)) in enumerate(STILLS.items()):
        img = Image.new("RGB", (w, h))
        px = img.load()
        for y in range(h):
            for x in range(w):
                px[x, y] = (70 + (140 * x) // w, 60 + (120 * y) // h, 90 + 40 * k)
        d = ImageDraw.Draw(img)
        d.ellipse([w * 0.2, h * 0.2, w * 0.55, h * 0.75], outline=(240, 230, 210), width=4)
        d.rectangle([w * 0.6, h * 0.3, w * 0.85, h * 0.8], fill=(180, 120 + 30 * k, 80))
        d.line([(0, h - 1), (w - 1, 0)], fill=(230, 220, 200), width=3)
        d.text((10, 10), f"{sid} {w}x{h} test image", fill=(250, 245, 235))
        path = dest / f"{sid}.png"
        img.save(path)
        out.append(path)
    return out


def film(dest: Path) -> Path:
    """Everything the fixture film needs beside its JSON."""
    stills(dest / "stills")
    testsrc(dest / "footage" / "fx-testsrc.mp4")
    return dest


if __name__ == "__main__":
    print(film(Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent)))
