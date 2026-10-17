"""The readers' voicing EQ (GRAMMAR A38 refined, ticket R13): the same house
warmth as the narrator's, measured per voice.

Founder, 2026-10-12: "Readers get the same house warmth as Tara." A38 (R12)
gave the narrator one EQ, a bell under her chest and a high shelf over her
treble, chosen from her long-term spectrum against ANSI S3.5's speech
spectrum. The Kokoro readers differ from her and from each other (some are
brighter than she is, some darker), so one EQ cannot serve them: each reader
voice gets its own bell and shelf, derived from its long-term spectrum
against the same reference so that, after its EQ, it sits where Tara sits
after hers: the same chest (the 160 to 315 Hz bands) and the same treble (the
5 to 8 kHz bands), within READER_EQ_BOUNDS. The bell is placed just above the
voice's median f0, as Tara's is (179 Hz measured so, bell at 200 Hz). Archival audio is
never EQ'd: it is a real recording and keeps its own sound.

The derived values are the house table (``studio/reader-eq.json``), pooled
over every film's takes of a voice, so a voice sounds the same in every film;
``python -m studio.engine.voicing measure <film>... [--write]`` rebuilds it.
A voice not yet in the table is measured on the film's own takes when the
plan is built (a reviewer item says so). A film may declare ``reader_eq``:
``"house"`` (the default), ``"off"``, or per voice ``"house"``, ``"off"`` or
its own ``{low, high}`` inside the bounds.

Every function here but ``measure_takes`` (which reads WAVs) is pure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path

import numpy as np

from studio.engine import score as SC

RATE = SC.RATE
TABLE = Path(__file__).resolve().parents[1] / "reader-eq.json"

# ANSI S3.5-1997 (R2017), Table 3: the standard speech spectrum level at normal vocal effort, dB per Hz, in the
# one-third octave bands 160 Hz to 8 kHz (the Speech Intelligibility Index's reference spectrum).
S35_NORMAL = {160: 32.41, 200: 34.48, 250: 34.75, 315: 33.98, 400: 34.59, 500: 34.27, 630: 32.06, 800: 28.30,
              1000: 25.01, 1250: 23.00, 1600: 20.15, 2000: 17.32, 2500: 13.18, 3150: 11.55, 4000: 9.33, 5000: 5.31,
              6300: 2.59, 8000: 1.13}
NORM_BANDS = (500, 630, 800, 1000)        # a spectrum is compared with the reference after matching it over these
LOW_BANDS = (160, 200, 250, 315)          # the chest: the warmth is judged as their mean
TREBLE_BANDS = (5000, 6300, 8000)         # the treble: judged band by band

LTAS_NFFT, LTAS_HOP = 4096, 2048          # Hann, 50% overlap, at 48 kHz (11.7 Hz bins: 160 Hz's band holds 3)
LTAS_MIN_RMS = 0.01                       # frames of a take levelled to the dialogue target, as voice_profile's
DIALOGUE_LUFS = -20.0

# Tara over the pilot's 81 narration takes (The Next Village), measured by ``measure_takes`` as a reader is: dB over
# S3.5 per band, matched over NORM_BANDS, and her median f0 (the median of each take's). R12's log gives the same
# chest (160 Hz +9.2, 200 Hz +7.7, 250 Hz +4.6) and 8 kHz +14.5, 6.3 kHz +6.3 by a method it did not record; this
# measure, the one the readers are held to, reads her treble at +11.0 and +4.2.
NARRATOR_EXCESS = {160: 9.6, 200: 7.7, 250: 4.6, 315: 3.7, 400: 1.2, 500: 0.2, 630: -0.9, 800: 0.4, 1000: 0.3,
                   1250: 1.2, 1600: 0.0, 2000: -0.8, 2500: -2.6, 3150: -4.4, 4000: -2.9, 5000: 1.4, 6300: 4.2,
                   8000: 11.0}
NARRATOR_F0_HZ = 179.4
WARMTH_ABOVE_F0 = 200.0 / NARRATOR_F0_HZ  # the house bell sits this far above the voice's median f0 (Tara: 200 Hz)

READER_BELL_Q = 1.2                       # Tara's
READER_SHELF_SLOPE = 1.0
READER_SHELF_HOUSE_HZ = 6000.0            # the corner when the shelf cuts nothing (gain 0)
READER_EQ_BOUNDS = {"low": {"type": ("bell",), "hz": (100.0, 300.0), "gain_db": (0.0, 3.0), "q": (0.5, 2.0)},
                    "high": {"type": ("high_shelf",), "hz": (5000.0, 9000.0), "gain_db": (-6.0, 0.0), "slope": (0.5, 1.0)}}
# The shelf may cut twice the narrator's 3 dB: the brightest readers sit 4 to 5 dB over Tara at 6.3 to 8 kHz.
# It never boosts: a reader darker than Tara keeps its own treble.


def voice_key(voice: dict | None) -> str | None:
    """A cast voice's house name: ``blend:<name>`` for a blend, else
    ``<engine>:<voice>`` (``kokoro-blend`` is ``kokoro``), as cast.json writes
    them."""
    if not isinstance(voice, dict) or not voice.get("voice"):
        return None
    v = str(voice["voice"])
    if v.startswith("blend:"):
        return v
    eng = str(voice.get("engine") or "kokoro").replace("-blend", "")
    return f"{eng}:{v}"


# --------------------------------------------------------------------------
# Measuring a voice
# --------------------------------------------------------------------------

def levelled(x: np.ndarray) -> np.ndarray:
    """A take at the dialogue target (integrated loudness), as the mix levels it."""
    m = SC.integrated_lufs(x)
    return np.asarray(x, np.float32) if m is None else (np.asarray(x, np.float64) * 10 ** ((DIALOGUE_LUFS - m) / 20)).astype(np.float32)


def band_power(xs) -> tuple[dict[int, float], int]:
    """The long-term spectrum of levelled takes: the mean power density of
    every frame over LTAS_MIN_RMS, pooled over the takes (a long take weighs
    more), in each one-third octave band of S35_NORMAL. Returns the band
    levels (dB, arbitrary reference) and the frames counted."""
    w = np.hanning(LTAS_NFFT)
    acc = np.zeros(LTAS_NFFT // 2 + 1)
    frames = 0
    for x in xs:
        x = np.asarray(x, np.float64)
        for i in range(0, len(x) - LTAS_NFFT + 1, LTAS_HOP):
            f = x[i: i + LTAS_NFFT]
            if math.sqrt(float((f * f).mean())) < LTAS_MIN_RMS:
                continue
            acc += np.abs(np.fft.rfft(f * w)) ** 2
            frames += 1
    if not frames:
        return {}, 0
    fr = np.fft.rfftfreq(LTAS_NFFT, 1.0 / RATE)
    out = {}
    for c in S35_NORMAL:
        m = (fr >= c / 2 ** (1 / 6)) & (fr < c * 2 ** (1 / 6))
        out[c] = 10 * math.log10(max(float(acc[m].mean()), 1e-30))
    return out, frames


def excess(levels: dict[int, float]) -> dict[int, float]:
    """Band levels over S3.5, matched over NORM_BANDS (dB, one decimal)."""
    d = {c: levels[c] - S35_NORMAL[c] for c in S35_NORMAL}
    ref = sum(d[c] for c in NORM_BANDS) / len(NORM_BANDS)
    return {c: round(d[c] - ref, 1) for c in S35_NORMAL}


def after_eq(ex: dict[int, float], eq: dict | None) -> dict[int, float]:
    """A spectrum's excess once ``eq`` is applied, matched again over NORM_BANDS
    (the bell lifts the 500 Hz band a little)."""
    if not eq:
        return dict(ex)
    db = {c: float(20 * np.log10(SC.eq_mag(np.array([float(c)]), eq)[0])) for c in S35_NORMAL}
    ref = sum(db[c] for c in NORM_BANDS) / len(NORM_BANDS)
    return {c: ex[c] + db[c] - ref for c in S35_NORMAL}


def warmth(ex: dict[int, float]) -> float:
    return sum(ex[c] for c in LOW_BANDS) / len(LOW_BANDS)


# The readers' target is pinned (founder ruling 2026-10-16, deeper Tara): it is Tara as synthesised, unshifted
# (NARRATOR_EXCESS, her measured spectrum over the pilot's 81 takes), after the house narrator EQ as R13 derived it
# from. A film's own narrator_eq, a narrator lowered by PSOLA (pitch_shift_st) or a later change to
# SC.NARRATOR_EQ_HOUSE never moves a reader: `voicing measure --write` re-derives every reader against this pin.
READER_TARGET_NARRATOR_EQ = {"low": {"type": "bell", "hz": 200.0, "gain_db": 2.5, "q": 1.2},
                             "high": {"type": "high_shelf", "hz": 6000.0, "gain_db": -2.5, "slope": 1.0}}
READER_TARGET = {"warmth_db": 8.08, "treble_db": {5000: 0.44, 6300: 2.63, 8000: 8.84}}   # a test re-derives it


def derived_targets() -> dict:
    """The pin re-derived: NARRATOR_EXCESS after READER_TARGET_NARRATOR_EQ (a test holds it equal to READER_TARGET)."""
    t = after_eq(NARRATOR_EXCESS, READER_TARGET_NARRATOR_EQ)
    return {"warmth_db": round(warmth(t), 2), "treble_db": {c: round(t[c], 2) for c in TREBLE_BANDS}}


def targets() -> dict:
    """Where the old Tara reference sits after its EQ: the readers' targets (pinned, READER_TARGET)."""
    return {"warmth_db": READER_TARGET["warmth_db"], "treble_db": dict(READER_TARGET["treble_db"])}


def _bell(hz: float, g: float) -> dict:
    return {"type": "bell", "hz": float(hz), "gain_db": round(float(g), 1), "q": READER_BELL_Q}


def _shelf(hz: float, g: float) -> dict:
    return {"type": "high_shelf", "hz": float(hz), "gain_db": round(float(g), 1), "slope": READER_SHELF_SLOPE}


def derive(ex: dict[int, float], f0_hz: float | None) -> tuple[dict, dict]:
    """A reader voice's EQ from its measured excess and median f0. The bell
    sits at f0 times WARMTH_ABOVE_F0 (to 5 Hz, inside the bounds) and its gain
    (0 to +3 dB, 0.1 dB steps) brings the voice's chest to the narrator's
    after hers; the shelf's corner (5 to 9 kHz, 250 Hz steps) and cut (0 to -6
    dB, 0.1 dB steps) bring its treble bands nearest hers (least squares),
    ties to the smaller cut and then to the corner nearest 6 kHz. No f0 (an
    unvoiced take), no bell. Returns the EQ and the evidence."""
    tgt = targets()
    lo_b, hi_b = READER_EQ_BOUNDS["low"], READER_EQ_BOUNDS["high"]
    bell_hz = None
    if f0_hz:
        bell_hz = min(max(round(f0_hz * WARMTH_ABOVE_F0 / 5) * 5, lo_b["hz"][0]), lo_b["hz"][1])
    shelf = _shelf(READER_SHELF_HOUSE_HZ, 0.0)

    def fit_bell(sh):
        if bell_hz is None:
            return None
        best = None
        for k in range(int(lo_b["gain_db"][0] * 10), int(lo_b["gain_db"][1] * 10) + 1):
            eq = {"low": _bell(bell_hz, k / 10), "high": sh}
            err = round(abs(warmth(after_eq(ex, eq)) - tgt["warmth_db"]), 6)
            if best is None or (err, k) < best[0]:
                best = ((err, k), eq["low"])
        return best[1]

    def fit_shelf(bl):
        best = None
        for hz in np.arange(hi_b["hz"][0], hi_b["hz"][1] + 1, 250.0):
            for k in range(int(hi_b["gain_db"][0] * 10), int(hi_b["gain_db"][1] * 10) + 1):
                eq = {"high": _shelf(hz, k / 10)} | ({"low": bl} if bl else {})
                a = after_eq(ex, eq)
                err = round(sum((a[c] - tgt["treble_db"][c]) ** 2 for c in TREBLE_BANDS), 6)
                key = (err, -k, abs(hz - READER_SHELF_HOUSE_HZ))
                if best is None or key < best[0]:
                    best = (key, eq["high"])
        return best[1]

    bell = fit_bell(shelf)
    shelf = fit_shelf(bell)
    bell = fit_bell(shelf)
    if shelf["gain_db"] == 0.0:
        shelf = _shelf(READER_SHELF_HOUSE_HZ, 0.0)
    eq = ({"low": bell} if bell else {}) | {"high": shelf}
    a = after_eq(ex, eq)
    ev = {"f0_hz": f0_hz, "excess_db": {str(c): ex[c] for c in S35_NORMAL},
          "warmth_db": round(warmth(ex), 2), "warmth_after_db": round(warmth(a), 2),
          "treble_db": {str(c): ex[c] for c in TREBLE_BANDS},
          "treble_after_db": {str(c): round(a[c], 2) for c in TREBLE_BANDS},
          "target": {"warmth_db": tgt["warmth_db"], "treble_db": {str(c): v for c, v in tgt["treble_db"].items()}},
          "bell_hz_from_f0": None if f0_hz is None else round(f0_hz * WARMTH_ABOVE_F0, 1)}
    return eq, ev


def measure_takes(wavs, words=None) -> dict | None:
    """One voice's takes (paths) measured: their pooled band levels, excess
    and median f0 (the median of each take's, render.voice_profile on the
    levelled take). None when no take has a frame to measure."""
    from studio.engine import render as R
    xs, f0s = [], []
    for k, p in enumerate(wavs):
        x = levelled(R._read_wav(Path(p)))
        xs.append(x)
        prof = R.voice_profile(x, int((words or [1] * len(wavs))[k] or 1))
        if prof["f0_hz"]:
            f0s.append(prof["f0_hz"])
    levels, frames = band_power(xs)
    if not frames:
        return None
    return {"takes": len(xs), "frames": frames, "excess": excess(levels),
            "f0_hz": round(float(np.median(f0s)), 1) if f0s else None}


# --------------------------------------------------------------------------
# The declaration
# --------------------------------------------------------------------------

def load_table(path: Path = TABLE) -> tuple[dict, str | None]:
    """The house table's voices (key -> record with ``eq``) and its sha256."""
    try:
        raw = path.read_bytes()
    except OSError:
        return {}, None
    return (json.loads(raw.decode("utf-8")).get("voices") or {}), hashlib.sha256(raw).hexdigest()[:12]


def eq_problems(name: str, v) -> list[str]:
    """``v`` is a {low, high} EQ inside READER_EQ_BOUNDS (``high`` required)."""
    if not isinstance(v, dict) or not v or set(v) - {"low", "high"}:
        return [f"{name} must be \"house\", \"off\" or {{low, high}}, not {v!r}"]
    out = []
    for k, band in v.items():
        bounds = READER_EQ_BOUNDS[k]
        if not isinstance(band, dict) or set(band) != set(bounds):
            out.append(f"{name}.{k} needs exactly {sorted(bounds)}")
            continue
        if band["type"] not in bounds["type"]:
            out.append(f"{name}.{k}.type must be {bounds['type'][0]}")
            continue
        for p, (lo, hi) in ((p, r) for p, r in bounds.items() if p != "type"):
            x = band[p]
            if isinstance(x, bool) or not isinstance(x, (int, float)) or not lo <= float(x) <= hi:
                out.append(f"{name}.{k}.{p} {x!r} is outside {lo:g} to {hi:g}")
    return out


def reader_voices(play: dict) -> dict[str, str | None]:
    """Each synthetic reading's voice: line id -> house voice name (None when
    its ``read_by`` names no cast voice). Archival audio and narration are
    not readers."""
    voices = {v.get("id"): v for v in (play.get("cast") or {}).get("voices", [])}
    out = {}
    for part in play.get("parts", []):
        for ln in part.get("lines", []):
            if ln.get("kind") == "narration" or ln.get("archival_audio") or ln.get("clip") or not ln.get("read_by"):
                continue
            out[ln["id"]] = voice_key(voices.get(ln["read_by"]))
    return out


def setting(play: dict, table: dict) -> tuple[dict, str, list[str]]:
    """A38 refined: the film's ``reader_eq`` resolved per reader voice. Absent
    or ``"house"``: every voice the house's (its table entry, or ``None`` to be
    measured on the film's takes); ``"off"``: none; an object: per voice name
    ``"house"``, ``"off"`` or its own {low, high} (a voice not named is the
    house's). Returns ({voice: spec}, how it was declared, problems), where a
    spec is {"eq": eq or None, "how": ...}."""
    v = play.get("reader_eq", "house") if isinstance(play, dict) else "house"
    voices = sorted({k for k in reader_voices(play).values() if k})
    problems, per = [], {}

    def house(k):
        rec = table.get(k)
        if rec:
            p = eq_problems(f"reader-eq.json {k}", rec.get("eq"))
            problems.extend(p)
            return {"eq": None if p else rec["eq"], "how": "house table"}
        return {"eq": None, "how": "house, measured on this film's takes"}

    if v is None or v == "house":
        return {k: house(k) for k in voices}, ("house (default)" if "reader_eq" not in play else "house"), problems
    if v is False or v == "off":
        return {k: {"eq": None, "how": "off"} for k in voices}, "off", []
    if not isinstance(v, dict):
        return {}, "invalid", [f"reader_eq must be \"house\", \"off\" or an object by voice, not {v!r}"]
    for k in v:
        if k not in voices:
            problems.append(f"reader_eq names {k!r}, which reads no line of this film (voices: {', '.join(voices)})")
    for k in voices:
        d = v.get(k, "house")
        if d == "house":
            per[k] = house(k)
        elif d == "off" or d is False:
            per[k] = {"eq": None, "how": "off"}
        else:
            p = eq_problems(f"reader_eq.{k}", d)
            problems.extend(p)
            per[k] = {"eq": None if p else {b: dict(x) for b, x in d.items()}, "how": "film"}
    return per, "film", problems


# --------------------------------------------------------------------------
# The house table, rebuilt from the films' takes
# --------------------------------------------------------------------------

def film_takes(film: Path) -> dict[str, list[tuple[Path, int]]]:
    """A film's reader takes by voice: voice -> [(wav, words)], as the
    screenplay places them (a relative wav is the film's)."""
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    who = reader_voices(play)
    out: dict[str, list] = {}
    for part in play.get("parts", []):
        for ln in part.get("lines", []):
            k = who.get(ln.get("id"))
            if not k:
                continue
            wav = Path(os.path.normpath(film / (ln.get("wav") or f"audio/{ln['id']}.wav")))
            if wav.exists():
                out.setdefault(k, []).append((wav, len(str(ln.get("text") or "").split())))
    return out


def build_table(films) -> dict:
    pooled: dict[str, list] = {}
    seen: dict[str, set] = {}
    for film in films:
        for k, takes in film_takes(Path(film)).items():
            have = {t[0] for t in pooled.get(k, [])}
            pooled.setdefault(k, []).extend(t for t in takes if t[0] not in have)
            seen.setdefault(k, set()).add(Path(film).name)
    voices = {}
    for k in sorted(pooled):
        m = measure_takes([t[0] for t in pooled[k]], [t[1] for t in pooled[k]])
        if m is None:
            continue
        eq, ev = derive(m["excess"], m["f0_hz"])
        voices[k] = {"eq": eq, "takes": m["takes"], "films": sorted(seen[k]), "f0_hz": m["f0_hz"],
                     **{x: y for x, y in ev.items() if x not in ("f0_hz", "target", "treble_db")}}
    return {"_note": "GRAMMAR A38 refined (R13): each reader voice's house EQ, measured on its takes in the films named "
                     "against ANSI S3.5 (normal effort), matched over 500 Hz to 1 kHz. Rebuilt by `python -m "
                     "studio.engine.voicing measure <film>... --write`; never edited by hand (a test re-derives every eq "
                     "from its excess and f0).",
            "target": {"warmth_db": targets()["warmth_db"], "treble_db": {str(c): v for c, v in targets()["treble_db"].items()},
                       "from": "the narrator (Tara, 81 pilot takes) after the house narrator EQ"},
            "bounds": READER_EQ_BOUNDS, "voices": voices}


def add_voices(table: dict, built: dict) -> tuple[dict, list[str]]:
    """The house table with only the voices it does not hold yet taken from ``built`` (a ``build_table`` result):
    every voice already in the table keeps its entry exactly, so adding a film's new readers never moves another
    film's EQ. Returns (table, the voices added)."""
    out = json.loads(json.dumps(table))
    have = out.setdefault("voices", {})
    added = [k for k in sorted(built.get("voices", {})) if k not in have]
    for k in added:
        have[k] = built["voices"][k]
    out["voices"] = dict(sorted(have.items()))
    return out, added


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="GRAMMAR A38 refined: measure the reader voices and derive their house EQ")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("measure", help="measure every reader voice over the films' takes")
    m.add_argument("films", type=Path, nargs="+")
    m.add_argument("--write", action="store_true", help=f"write the house table ({TABLE.name})")
    m.add_argument("--add", action="store_true", help="only add voices the house table does not hold yet; every entry it "
                   "holds is kept exactly (with --write, writes the merged table)")
    a = ap.parse_args(argv)
    t = build_table([f.resolve() for f in a.films])
    if a.add:
        current = json.loads(TABLE.read_text(encoding="utf-8")) if TABLE.exists() else {"voices": {}}
        merged, added = add_voices(current, t)
        print(f"--add: {len(added)} new voice(s): {', '.join(added) or 'none'}; {len(current.get('voices', {}))} kept as they were")
        t = dict(merged, voices={k: merged["voices"][k] for k in merged["voices"]})
        shown = {k: t["voices"][k] for k in added}
    else:
        shown = t["voices"]
    print(f"target: warmth {t['target']['warmth_db']:+.2f} dB, treble {t['target']['treble_db']}")
    print(f"{'voice':<18} {'takes':>5} {'f0':>6}  {'bell':>16}  {'shelf':>17}  {'chest':>13}  {'5k / 6.3k / 8k before':>22}  after")
    for k, r in shown.items():
        lo, hi = r["eq"].get("low"), r["eq"]["high"]
        ta = r["treble_after_db"]
        tb = {c: r["excess_db"][c] for c in ta}
        print(f"{k:<18} {r['takes']:>5} {r['f0_hz'] or 0:>6.1f}  "
              + (f"{lo['gain_db']:+.1f} dB @ {lo['hz']:>3.0f} Hz" if lo else f"{'none':>16}")
              + f"  {hi['gain_db']:+.1f} dB @ {hi['hz'] / 1000:.2f} kHz"
              + f"  {r['warmth_db']:+5.1f} > {r['warmth_after_db']:+5.1f}"
              + "  " + " / ".join(f"{tb[c]:+5.1f}" for c in tb) + "   " + " / ".join(f"{ta[c]:+5.1f}" for c in ta))
    if a.write:
        TABLE.write_text(json.dumps(t, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {TABLE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
