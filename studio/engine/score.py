"""The house score standard (GRAMMAR A29, ticket R1): what the music of every
film must do under the voice, measured on the cues as the mix places them.

Founder, 2026-10-11, on the Partition master: "the tanpura is a little too
loud in the background, and there's that constant sound coming... the vibe
we're going for with background music is not loud. It is dramatic when
needed, silent when it deserves... make sure the transitions are
consistent." The measurements behind each number are in
``episode-v2/FOUNDER-FEEDBACK-1.md`` (section 1).

The numbers are one block, ``STANDARD``. A film may set any of them in its
screenplay's ``score_standard``, only inside ``BOUNDS`` (what GRAMMAR A29
allows): never louder, never laxer than the house allows.

Every function here is pure (numpy in, numbers out); ``render.build_mix``
calls ``highpass`` and ``analyse_cue`` while it places the cues, and
``score_checks`` judges them; ``python -m studio.engine.score <film>``
runs the same checks offline on a film's cue WAVs (no voices cleaned, no
mix rendered), so a writer can check a score before any render.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

RATE = 48000
DIALOGUE_LUFS = -20.0               # render.DIALOGUE_LUFS (A13): every synthetic line is levelled to this
FEATURE_LUFS = -26.0                # the motif and a palette cue (a recording heard for itself): render.MUSIC_LUFS
DUCK_DB = 9.0                       # GRAMMAR 8.5 (render.DUCK_DB)

# --------------------------------------------------------------------------
# The house score standard: one block (A29). A film may set a value in its
# screenplay's `score_standard`, inside BOUNDS only.
# --------------------------------------------------------------------------

STANDARD = {
    "bed_under_dialogue_db": 12.0,      # a bed in the voice's gaps sits this far under the -20 LUFS dialogue: -32 LUFS
    "bed_highpass_hz": 300.0,           # 12 dB an octave on every bed, so nothing of the bed sits under the voice
    "bed_low_end_max_share": 0.10,      # a bed's energy under LOW_END_HZ, after its high-pass, at most this share
    "bed_breath_db": 6.0,               # a bed's 100 ms level spread (p90 minus p10) at least this: a drone breathes
    "transition_over_bed_max_db": 0.0,  # a transition's or sting's loudest 400 ms never above the bed it leads into
    "entry_fade_min_s": 1.5,            # an underscore cue that enters from no music fades in at least this long
    "music_hole_max_s": 1.5,            # a stretch with no music between the first and last cue, undeclared, at most this
    "duck_hold_s": 1.2,                 # the duck holds through a voice gap shorter than this (and every pause in a line)
}
BOUNDS = {                              # what A29 lets a film set: (lowest, highest)
    "bed_under_dialogue_db": (12.0, 20.0),      # quieter, never louder
    "bed_highpass_hz": (300.0, 400.0),
    "bed_low_end_max_share": (0.0, 0.10),
    "bed_breath_db": (6.0, 12.0),
    "transition_over_bed_max_db": (-6.0, 0.0),
    "entry_fade_min_s": (1.5, 4.0),
    "music_hole_max_s": (0.5, 1.5),
    "duck_hold_s": (1.2, 3.0),                  # up to a 3 s written pause between lines
}
LOW_END_HZ = 230.0                  # where a plucked tanpura and a harp's bass octave read as "loud" (the voice has nothing there)
TOL_DB = 1.0                        # a bed's measured level in the gaps may sit this far over its target (its own phrasing)
CEILING_TOL_DB = 0.5                # a transition's loudest 400 ms may sit this far over the bed's (measurement grain)
PRESENT_DBFS = -70.0                # 100 ms of music at or under this is no music (a hole)
ENTRY_LOOKBACK_S = 0.5              # a cue enters from no music when nothing else sounds in the 0.5 s before it
LEADS_INTO_S = 10.0                 # the bed a transition leads into starts within 10 s of its end (else the bed before it)
DUCK_HELD_TOL_DB = 1.0              # a held duck stays within 1 dB of its floor
GAP_MIN_S = 4.0                     # a bed is measured in the voice's gaps when they total this much, else over its whole span
BREATH_MIN_S = 4.0                  # a bed's breathing is judged on at least this much of it, unfaded; shorter is not judged
ORPHAN_HEADROOM_DB = 4.0            # a transition with no bed in the film is held to the bed target plus this (a bed's
                                    # loudest 400 ms sits 3 to 4 dB over its integrated level: Partition, Nought)
HOP_S = 0.1                         # the analysis grid: 100 ms windows (momentary loudness is 4 of them, 400 ms)
DUCK_GRID_S = 0.01                  # duck-pumping is judged on a 10 ms grid

ROLES = ("bed", "transition", "sting", "outro", "motif", "palette")
UNDERSCORE = ("bed", "transition", "sting", "outro")     # levelled to the bed target; under the score standard
TRANSITIONS = ("transition", "sting", "outro")            # linted against the bed they lead into (or follow)
MUSIC_ROLES = ("underscore", "house_motif", "palette")    # a music cue's `role`; absent is underscore
RULES = ("bed-under-voice", "bed-low-end", "bed-breathing", "underscore-level", "ambience-level", "ambience-low-end",
         "transition-ceiling",
         "music-entry", "music-exit", "music-holes", "duck-pumping")
CUE_KINDS = ("music", "ambience")                          # a cue's `kind`, stated on every cue; nothing else is placed
# Ambience under the voice (A29(1)): at most this share of its energy may be tonal and under LOW_END_HZ (spectral
# lines standing 10x over their neighbourhood on a 1 Hz Welch spectrum, 20 to 230 Hz). Calibrated (R1 review): two real
# room tones measure 0.0 (34% and 42% of their energy under 230 Hz, all of it broadband), pink noise (crowd) 0.0, brown
# noise (wind, 100% under 230 Hz) 0.0, brown noise with a strong 50 Hz mains hum 0.10; a 55 and 110 Hz drone 1.0, a
# cello G2 over noise 0.93, the E14 tests' two-tone bed 0.5. A plain low-end share could not tell wind (100%) from a
# drone (100%); the tonal share can.
AMB_TONAL_LOW_MAX_SHARE = 0.15
TONAL_PEAK_X = 10.0                                         # a line stands this many times over its neighbours' median
TONAL_HALF_HZ = 12                                          # the neighbours: up to 12 Hz either side (2 Hz guard)


def standard(play: dict) -> tuple[dict, dict, list[str]]:
    """The film's score standard (STANDARD with the screenplay's
    ``score_standard`` applied), what it stated, and what is wrong with it
    (an unknown key, not a number, outside BOUNDS)."""
    out = dict(STANDARD)
    stated: dict = {}
    problems: list[str] = []
    declared = play.get("score_standard")
    if declared is None:
        return out, stated, problems
    if not isinstance(declared, dict):
        return out, stated, [f"score_standard must be an object, not {type(declared).__name__}"]
    for k, v in declared.items():
        if k not in BOUNDS:
            problems.append(f"unknown score_standard key {k!r} (known: {', '.join(sorted(BOUNDS))})")
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
            problems.append(f"{k} must be a number, not {v!r}")
            continue
        lo, hi = BOUNDS[k]
        if not lo - 1e-9 <= float(v) <= hi + 1e-9:
            problems.append(f"{k} {v:g} is outside GRAMMAR A29's bounds ({lo:g} to {hi:g})")
            continue
        out[k] = float(v)
        stated[k] = float(v)
    return out, stated, problems


def bed_lufs(std: dict) -> float:
    return DIALOGUE_LUFS - float(std["bed_under_dialogue_db"])


def cue_role(c: dict) -> str:
    """A music cue's place in the score. Only the cue's `role` makes it heard
    for itself: `house_motif` is the motif, `palette` a palette recording.
    Every other music cue is underscore: its ``score_role`` when it states
    one of bed, transition, sting or outro, else read from the score's own
    names (the WAV stem or the `tradition` after "underscore:"): transition
    and rupture cues are transitions, stings stings, the outro the outro, and
    any other is a bed (the strictest reading). Ambience is not music.
    role_problem says what build_plan refuses."""
    if c.get("kind", "music") != "music":
        return "ambience"
    if c.get("role") == "house_motif":
        return "motif"
    if c.get("role") == "palette":
        return "palette"
    sr = c.get("score_role")
    if isinstance(sr, str) and sr in UNDERSCORE:
        return sr
    stem = Path(str(c.get("wav") or c.get("id") or "")).stem.lower()
    trad = str(c.get("tradition") or "").lower()
    trad = trad.split(":", 1)[1].strip() if trad.startswith("underscore:") else trad
    for name, role in (("transition", "transition"), ("rupture", "transition"), ("sting", "sting"), ("outro", "outro")):
        if stem.startswith(name) or trad.startswith(name):
            return role
    return "bed"


def role_problem(c: dict) -> str | None:
    """What A29 refuses in a music cue's roles: a `role` outside MUSIC_ROLES,
    or a ``score_role`` that is not a string or contradicts it (an underscore
    cue may state bed, transition, sting or outro; motif only with `role:
    house_motif`, palette only with `role: palette`)."""
    if c.get("kind", "music") != "music":
        return None
    role = c.get("role")
    if role is not None and (not isinstance(role, str) or role not in MUSIC_ROLES):
        return f"role {role!r} is not one of {', '.join(MUSIC_ROLES)}"
    if "score_role" not in c:
        return None
    sr = c["score_role"]
    allowed = {"house_motif": ("motif",), "palette": ("palette",)}.get(role, UNDERSCORE)
    if not isinstance(sr, str) or sr not in allowed:
        return f"score_role {sr!r} with role {role or 'underscore'!r}: it may be {', '.join(allowed)}"
    return None


# --------------------------------------------------------------------------
# Filters (zero-phase, by FFT: numpy only, no scipy)
# --------------------------------------------------------------------------

def _fast_len(n: int) -> int:
    best = 1 << max(0, (n - 1).bit_length())
    for f in (3, 5, 9, 15, 25, 27, 45, 75):
        k = f
        while k < n:
            k *= 2
        best = min(best, k)
    return best


def _filtered(x: np.ndarray, mag) -> np.ndarray:
    """x through a zero-phase filter of magnitude ``mag(f)``; 0.5 s of padding
    takes the filter's ringing, so nothing wraps around into the cue."""
    if len(x) == 0:
        return np.zeros(0, np.float32)
    n = _fast_len(len(x) + RATE // 2)
    X = np.fft.rfft(np.asarray(x, np.float64), n)
    X *= mag(np.fft.rfftfreq(n, 1.0 / RATE))
    return np.fft.irfft(X, n)[: len(x)].astype(np.float32)


def highpass_mag(f: np.ndarray, hz: float) -> np.ndarray:
    """A second-order Butterworth high-pass (12 dB an octave): -3 dB at hz."""
    r = (np.asarray(f, np.float64) / float(hz)) ** 2
    return r / np.sqrt(1.0 + r * r)


def highpass(x: np.ndarray, hz: float) -> np.ndarray:
    """A29: the bed high-pass, 12 dB an octave at ``hz`` (300 Hz by default)."""
    return _filtered(x, lambda f: highpass_mag(f, hz))


# ITU-R BS.1770-4 K-weighting at 48 kHz: the pre-filter (high shelf) and the RLB high-pass
_K = (([1.53512485958697, -2.69169618940638, 1.19839281085285], [1.0, -1.69065929318241, 0.73248077421585]),
      ([1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621]))


def k_mag(f: np.ndarray) -> np.ndarray:
    z = np.exp(-2j * np.pi * np.asarray(f, np.float64) / RATE)
    h = np.ones_like(z)
    for b, a in _K:
        h *= (b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z)
    return np.abs(h)


def k_weight(x: np.ndarray) -> np.ndarray:
    return _filtered(x, k_mag)


# --------------------------------------------------------------------------
# Measurements on one cue as placed
# --------------------------------------------------------------------------

def _windows(x: np.ndarray, hop: int) -> np.ndarray:
    n = math.ceil(len(x) / hop) * hop
    y = np.zeros(n, np.float64)
    y[: len(x)] = x
    return y.reshape(-1, hop)


def _db(p, floor: float = -200.0):
    return np.maximum(10 * np.log10(np.maximum(np.asarray(p, np.float64), 1e-30)), floor)


def gated_loudness(power: np.ndarray) -> float | None:
    """BS.1770 integrated loudness of K-weighted 400 ms block powers: the
    absolute gate at -70 LUFS, then the relative gate 10 LU under the mean.
    None when every block is gated out."""
    p = np.asarray(power, np.float64)
    lufs = -0.691 + _db(p)
    keep = lufs > -70.0
    if not keep.any():
        return None
    rel = -0.691 + 10 * math.log10(float(p[keep].mean())) - 10.0
    keep &= lufs > rel
    return round(-0.691 + 10 * math.log10(float(p[keep].mean())), 2) if keep.any() else None


def analyse_cue(y: np.ndarray, role: str, fade_in_s: float = 0.0, fade_out_s: float = 0.0, *,
                low_end_hz: float = LOW_END_HZ, unfaded: np.ndarray | None = None) -> dict:
    """What the standard reads of one cue as the mix places it (levelled,
    faded, gained): per 100 ms window its RMS (dBFS) and K-weighted power,
    its momentary loudness (400 ms) and their maximum, its integrated
    loudness, over its full-level part (between its fades) the share of its
    energy under ``low_end_hz``, and its breathing: the level spread (p90
    minus p10 of the 100 ms RMS) of ``unfaded`` (the same cue levelled and
    gained, before its fades, so a fade never passes for a breath), or of the
    full-level part when that is not given. Under BREATH_MIN_S of it, the
    breathing is not judged (``breath_judged`` false)."""
    hop = int(HOP_S * RATE)
    y = np.asarray(y, np.float32)
    w = _windows(y, hop)
    ms = np.mean(w * w, axis=1)
    kw = _windows(k_weight(y), hop)
    kp = np.mean(kw * kw, axis=1)
    mom = np.convolve(kp, np.ones(4) / 4, mode="full")[3: len(kp)] if len(kp) >= 4 else np.array([kp.mean()]) if len(kp) else kp
    a = min(len(ms), int(math.ceil(fade_in_s / HOP_S)))
    b = max(a, len(ms) - int(math.ceil(fade_out_s / HOP_S)))
    full = slice(a, b) if b - a >= 10 else slice(0, len(ms))
    integrated_unfaded = None
    if unfaded is not None:
        u = np.asarray(unfaded, np.float32)
        whole = len(u) // hop * hop                       # whole 100 ms windows only
        uw = u[:whole].reshape(-1, hop).astype(np.float64)
        ums = np.mean(uw * uw, axis=1)
        rms_db = _db(ums, -80.0)
        live = np.flatnonzero(_db(ums) > PRESENT_DBFS)     # digital silence built into the WAV is not a breath
        rms_db = rms_db[live[0]: live[-1] + 1] if len(live) else rms_db[:0]
        ukw = _windows(k_weight(u), hop)
        ukp = np.mean(ukw * ukw, axis=1)
        umom = np.convolve(ukp, np.ones(4) / 4, mode="valid") if len(ukp) >= 4 else ukp
        integrated_unfaded = gated_loudness(umom) if len(umom) else None
    else:
        rms_db = _db(ms[full], -80.0) if b - a >= 10 else _db(ms[:0])
    judged = len(rms_db) * HOP_S >= BREATH_MIN_S - 1e-9
    spread = float(np.percentile(rms_db, 90) - np.percentile(rms_db, 10)) if judged else 0.0
    seg = y[full.start * hop: full.stop * hop].astype(np.float64)
    if len(seg):
        P = np.abs(np.fft.rfft(seg)) ** 2
        f = np.fft.rfftfreq(len(seg), 1.0 / RATE)
        tot = float(P[1:].sum())
        low = float(P[1:][f[1:] < low_end_hz].sum())
        low_share = low / tot if tot > 0 else 0.0
    else:
        low_share = 0.0
    tonal = tonal_low_share(unfaded if unfaded is not None else y) if role == "ambience" else None
    return {"role": role, "n": len(y), "ms": ms.astype(np.float32), "kp": kp.astype(np.float32), "tonal_low_share": tonal,
            "mom_max_lufs": round(float(-0.691 + _db(mom).max()), 2) if len(mom) else None,
            "integrated_lufs": gated_loudness(mom) if len(mom) else None,
            "integrated_unfaded_lufs": integrated_unfaded,
            "full": [full.start, full.stop],
            "breath_db": round(spread, 2), "breath_judged": judged, "low_share": round(low_share, 4)}


# --------------------------------------------------------------------------
# The ducking (A29 with GRAMMAR 8.5): which voice gaps the duck must hold
# --------------------------------------------------------------------------

def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    d = np.diff(np.concatenate(([0], mask.astype(np.int8), [0])))
    return list(zip(np.flatnonzero(d == 1).tolist(), np.flatnonzero(d == -1).tolist()))


def held_gaps(active: np.ndarray, spans: list[tuple[float, float]], hold_s: float, grid_s: float) -> list[tuple[int, int, str]]:
    """The voice gaps the duck must hold through, on a grid of ``grid_s``:
    every gap between two voiced stretches that is shorter than ``hold_s``,
    and every pause inside one line's spoken span whatever its length (a
    written pause is the line's own). (start, end, why) in grid steps."""
    act = np.asarray(active, bool)
    out = []
    v = _runs(act)
    inside = np.zeros(len(act), bool)
    for a, b in spans:
        inside[max(0, int(round(a / grid_s))): max(0, int(round(b / grid_s)))] = True
    for (_, e0), (s1, _) in zip(v, v[1:]):
        if e0 >= s1:
            continue
        if (s1 - e0) * grid_s < hold_s - 1e-9:
            out.append((e0, s1, "shorter than the hold"))
        elif inside[e0:s1].all():
            out.append((e0, s1, "a pause inside a line"))
    return out


def duck_pumps(active: np.ndarray, duck: np.ndarray, spans: list[tuple[float, float]], hold_s: float,
               grid_s: float = DUCK_GRID_S, duck_db: float = DUCK_DB, smooth_s: float = 0.25) -> list[dict]:
    """duck-pumping: each held gap (held_gaps) where the music's duck gain
    rises more than DUCK_HELD_TOL_DB over its floor: the bed coming back up in
    a breath, which is what makes the music "come and go"."""
    floor = 10 ** (-duck_db / 20)
    lim = floor * 10 ** (DUCK_HELD_TOL_DB / 20)
    out = []
    gaps = held_gaps(active, spans, hold_s, grid_s)
    # The held stretch is the voice plus its held gaps; its last half-ramp before a real release (a gap the duck may
    # come up in) is the ramp starting early, not a pump, so only the inside of each held stretch is judged.
    held = np.asarray(active, bool).copy()
    for a, b, _ in gaps:
        held[a:b] = True
    edge = int(math.ceil(smooth_s / 2 / grid_s))
    inner = np.zeros(len(held), bool)
    for a, b in _runs(held):
        inner[a + edge: b - edge] = True
    for a, b, why in gaps:
        d = duck[a:b][inner[a:b]] if b > a else duck[:0]
        peak = float(np.max(d)) if len(d) else floor
        if peak > lim:
            out.append({"from_s": round(a * grid_s, 2), "to_s": round(b * grid_s, 2), "gap_s": round((b - a) * grid_s, 2),
                        "why_held": why, "rises_db": round(20 * math.log10(peak / floor), 1)})
    return out


# --------------------------------------------------------------------------
# The checks
# --------------------------------------------------------------------------

def _grid(cues: list[dict], duration_s: float) -> np.ndarray:
    """The music's power on the 100 ms grid over the film: the sum of every
    placed music cue's window powers (cues are independent, so powers add).
    Ambience is not music (A29(7)), as in _sounds_before and _sounds_after."""
    g = np.zeros(int(math.ceil(duration_s / HOP_S)) + 1, np.float64)
    for c in cues:
        if c["role"] == "ambience":
            continue
        i0 = int(round(c["start_s"] / HOP_S))
        ms = c["an"]["ms"]
        i1 = min(len(g), i0 + len(ms))
        if i1 > i0 >= 0:
            g[i0:i1] += ms[: i1 - i0]
    return g


def _covered(spans, a: float, b: float) -> bool:
    return any(x <= a + 1e-6 and y >= b - 1e-6 for x, y in spans)


def music_holes(cues: list[dict], duration_s: float, silences, own_sound, max_s: float,
                voice100: np.ndarray | None = None) -> list[dict]:
    """music-holes: stretches, between the first music cue's start and the
    last one's end, with neither voice (``voice100``, voice activity on the
    100 ms grid) nor music (every 100 ms window at or under PRESENT_DBFS;
    ambience is not music) for longer than ``max_s``, outside the declared
    silences (shots, parts, cues and moments marked ``silence: intended``)
    and outside a source's own sound (an archival clip or an archival line)."""
    music = [c for c in cues if c["role"] != "ambience"]
    if not music:
        return []
    g = _grid(cues, duration_s)
    quiet = _db(g) <= PRESENT_DBFS
    lo = int(round(min(c["start_s"] for c in music) / HOP_S))
    hi = int(round(max(c["start_s"] + c["an"]["n"] / RATE for c in music) / HOP_S))
    keep = np.zeros(len(quiet), bool)
    keep[lo:hi] = True
    for a, b in list(silences) + list(own_sound):
        keep[max(0, int(math.floor(a / HOP_S + 1e-6))): max(0, int(math.ceil(b / HOP_S - 1e-6)))] = False
    if voice100 is not None:
        v = np.asarray(voice100, bool)[: len(keep)]
        keep[: len(v)] &= ~v
    out = []
    for a, b in _runs(quiet & keep):
        if (b - a) * HOP_S > max_s + 1e-9:
            before = [c["id"] for c in music if c["start_s"] < a * HOP_S]
            after = [c["id"] for c in music if c["start_s"] >= a * HOP_S]
            out.append({"from_s": round(a * HOP_S, 1), "to_s": round(b * HOP_S, 1), "dur_s": round((b - a) * HOP_S, 1),
                        "after_cue": before[-1] if before else None, "before_cue": after[0] if after else None})
    return out


def tonal_low_share(x: np.ndarray, hz: float = LOW_END_HZ) -> float:
    """The share of x's energy in tonal lines between 20 Hz and ``hz``: on a
    1 Hz Welch spectrum (1 s Hann windows), each bin over TONAL_PEAK_X times
    the larger of its left and right neighbourhood medians (TONAL_HALF_HZ
    either side, a 2 Hz guard), so a drone's partials count and the steep
    slope of wind or room rumble does not."""
    x = np.asarray(x, np.float64)
    if len(x) == 0:
        return 0.0
    n = min(RATE, len(x))
    k = max(1, len(x) // n)
    w = np.hanning(n)
    P = np.mean([np.abs(np.fft.rfft(x[i * n:(i + 1) * n] * w)) ** 2 for i in range(k)], axis=0)
    f = np.fft.rfftfreq(n, 1.0 / RATE)
    tot = float(P[1:].sum())
    if tot <= 0:
        return 0.0
    tonal = 0.0
    for i in np.flatnonzero((f >= 20.0) & (f < hz)):
        lo, hi = P[max(1, i - TONAL_HALF_HZ): max(1, i - 2)], P[i + 3: i + TONAL_HALF_HZ + 1]
        ref = max(float(np.median(lo)) if len(lo) else 0.0, float(np.median(hi)) if len(hi) else 0.0)
        if P[i] > TONAL_PEAK_X * ref:
            tonal += float(P[i])
    return round(tonal / tot, 4)


def _sounds_before(c: dict, cues: list[dict]) -> bool:
    """Some other cue sounds (over PRESENT_DBFS) in the ENTRY_LOOKBACK_S before c starts: other music for a music
    cue (ambience is not music), any other cue for an ambience (a crossfade)."""
    a, b = c["start_s"] - ENTRY_LOOKBACK_S, c["start_s"]
    for o in cues:
        if o is c or (o["role"] == "ambience" and c["role"] != "ambience"):
            continue
        i0 = int(math.floor((a - o["start_s"]) / HOP_S))
        i1 = int(math.ceil((b - o["start_s"]) / HOP_S))
        ms = o["an"]["ms"][max(0, i0): max(0, min(len(o["an"]["ms"]), i1))]
        if len(ms) and _db(ms.max()) > PRESENT_DBFS:
            return True
    return False


def _sounds_after(c: dict, cues: list[dict]) -> bool:
    """Some other cue sounds (over PRESENT_DBFS) in the ENTRY_LOOKBACK_S after c ends (as _sounds_before)."""
    a = c["start_s"] + c["an"]["n"] / RATE
    b = a + ENTRY_LOOKBACK_S
    for o in cues:
        if o is c or (o["role"] == "ambience" and c["role"] != "ambience"):
            continue
        i0 = int(math.floor((a - o["start_s"]) / HOP_S))
        i1 = int(math.ceil((b - o["start_s"]) / HOP_S))
        ms = o["an"]["ms"][max(0, i0): max(0, min(len(o["an"]["ms"]), i1))]
        if len(ms) and _db(ms.max()) > PRESENT_DBFS:
            return True
    return False


def _leads_into(t: dict, beds: list[dict]) -> tuple[dict | None, str]:
    end = t["start_s"] + t["an"]["n"] / RATE
    nxt = [b for b in beds if t["start_s"] - 1e-6 <= b["start_s"] <= end + LEADS_INTO_S]
    if nxt:
        return min(nxt, key=lambda b: b["start_s"]), "the bed it leads into"
    prev = [b for b in beds if b["start_s"] < t["start_s"] and b["start_s"] + b["an"]["n"] / RATE >= t["start_s"] - LEADS_INTO_S]
    if prev:
        return max(prev, key=lambda b: b["start_s"]), "the bed before it (no bed follows within 10 s)"
    return None, "fallback: no bed within 10 s"


def _gap_level(c: dict, duck: np.ndarray | None) -> tuple[float | None, int, str]:
    """A bed's integrated loudness over its full-level windows where no voice
    ducks it (duck gain at least 0.99): the bed as heard in the gaps. Gaps
    under GAP_MIN_S in all measure one phrase of a breathing bed, not its
    level, so the whole full-level span is measured instead."""
    kp = c["an"]["kp"]
    a, b = c["an"]["full"]
    idx = np.arange(a, b)
    on = "the bed's full-level span (no voice measured)"
    if duck is not None:
        g = duck[np.clip(int(round(c["start_s"] / HOP_S)) + idx, 0, len(duck) - 1)]
        free = idx[g >= 0.99]
        if len(free) * HOP_S >= GAP_MIN_S - 1e-9:
            idx, on = free, "the voice's gaps (no duck)"
    p = kp[idx]
    blocks = np.convolve(p, np.ones(4) / 4, mode="valid") if len(p) >= 4 else p
    return gated_loudness(blocks) if len(blocks) else None, len(idx), on


def score_checks(cues: list[dict], std: dict, *, duration_s: float, silences=(), own_sound=(),
                 duck100: np.ndarray | None = None, voice_grid: np.ndarray | None = None,
                 duck_grid: np.ndarray | None = None, spans: list[tuple[float, float]] | None = None,
                 grid_s: float = DUCK_GRID_S, voice100: np.ndarray | None = None) -> list[dict]:
    """Every A29 check on the placed cues, as lint results: {rule, ok, unit,
    evidence}. ``cues`` are {id, role, start_s, fade_in_s, fade_out_s,
    gain_db, an (analyse_cue)}. ``duck100`` is the duck gain on the 100 ms
    grid (bed-under-voice measures the gaps with it); ``voice_grid`` and
    ``duck_grid`` (voice activity and duck gain on ``grid_s``) and the lines'
    spoken ``spans`` feed duck-pumping, which is skipped without them;
    ``voice100`` (voice activity on the 100 ms grid) lets music-holes count a
    stretch with voice as no hole."""
    out = []
    target = bed_lufs(std)
    beds = [c for c in cues if c["role"] == "bed"]
    for c in beds:
        lvl, n, on = _gap_level(c, duck100)
        ceiling = target + TOL_DB
        ok = lvl is None or lvl <= ceiling + 1e-9
        out.append({"rule": "bed-under-voice", "ok": ok, "unit": c["id"], "evidence": {
            "measured_lufs": lvl, "measured_on": on, "windows": n, "target_lufs": target, "max_lufs": ceiling,
            "under_dialogue_db": None if lvl is None else round(DIALOGUE_LUFS - lvl, 2), "min_under_db": std["bed_under_dialogue_db"],
            "gain_db": c.get("gain_db"),
            "fix": None if ok else "lower the cue's gain_db (a bed's gain_db is an offset from the bed target and may not lift it)"}})
        ok = c["an"]["low_share"] <= std["bed_low_end_max_share"] + 1e-9
        out.append({"rule": "bed-low-end", "ok": ok, "unit": c["id"], "evidence": {
            "share_under_hz": LOW_END_HZ, "share": c["an"]["low_share"], "max_share": std["bed_low_end_max_share"],
            "highpass_hz": c.get("highpass_hz"),
            "fix": None if ok else f"take the bed's low notes out of the score (nothing under {LOW_END_HZ:g} Hz: no bass "
                                   "octave, no low tanpura); the high-pass only thins them"}})
        judged = c["an"].get("breath_judged", True)
        ok = judged and c["an"]["breath_db"] >= std["bed_breath_db"] - 1e-9
        out.append({"rule": "bed-breathing", "ok": ok, "unit": c["id"], "evidence": {
            "spread_db": c["an"]["breath_db"] if judged else None, "judged": judged, "min_db": std["bed_breath_db"],
            "window_s": HOP_S, "measure": "p90 - p10 of 100 ms RMS, levelled, before the fades",
            "fix": None if ok else ("let the drone breathe: rests (two beats in eight), one regional pluck a bar, not one a beat"
                                    if judged else f"not judged: under {BREATH_MIN_S:g} s of bed; a cue this short is a "
                                                   "transition or a sting (say so with score_role), or lengthen the bed")}})
    loudest_bed = max((b["an"]["mom_max_lufs"] for b in beds if b["an"]["mom_max_lufs"] is not None), default=None)
    fallback = target + ORPHAN_HEADROOM_DB if loudest_bed is None else min(target + ORPHAN_HEADROOM_DB, loudest_bed)
    for c in cues:
        if (c["role"] in UNDERSCORE and c["role"] != "bed") or c["role"] == "ambience":
            # every underscore cue and every ambience is under the bed target (beds: bed-under-voice), whatever is near
            # it, measured levelled and before its fades (a fade never lowers what the cue is)
            lvl = c["an"].get("integrated_unfaded_lufs")
            if lvl is None:
                lvl = c["an"]["integrated_lufs"]
            amb = c["role"] == "ambience"
            mx = c["an"]["mom_max_lufs"]
            ok = (lvl is None or lvl <= target + TOL_DB + 1e-9) and (
                not amb or mx is None or mx <= target + ORPHAN_HEADROOM_DB + CEILING_TOL_DB + 1e-9)
            out.append({"rule": "ambience-level" if amb else "underscore-level", "ok": ok, "unit": c["id"], "evidence": {
                "role": c["role"], "integrated_lufs": lvl, "measured_on": "levelled, before the fades",
                "target_lufs": target, "max_lufs": target + TOL_DB, "gain_db": c.get("gain_db"),
                **({"max_momentary_lufs": mx, "max_momentary_allowed_lufs": target + ORPHAN_HEADROOM_DB + CEILING_TOL_DB}
                   if amb else {}),
                "fix": None if ok else ("hold the ambience under the bed target: lower its gain_db (GRAMMAR 8.5: 12 to 18 dB "
                                        "under the dialogue)" if amb else
                                        "lower its gain_db: an underscore cue's gain_db is an offset from the bed target, "
                                        "at most 0")}})
        if c["role"] in TRANSITIONS:
            bed, why = _leads_into(c, beds)
            ref = bed["an"]["mom_max_lufs"] if bed else None
            if ref is None:
                ref = fallback
                why = (f"fallback: no bed within 10 s, so the lower of the bed target plus {ORPHAN_HEADROOM_DB:g} dB and the "
                       "film's loudest bed")
            lim = ref + std["transition_over_bed_max_db"] + CEILING_TOL_DB
            mx = c["an"]["mom_max_lufs"]
            ok = lim is None or mx is None or mx <= lim + 1e-9
            out.append({"rule": "transition-ceiling", "ok": ok, "unit": c["id"], "evidence": {
                "role": c["role"], "max_momentary_lufs": mx, "bed": bed["id"] if bed else None, "bed_max_momentary_lufs": ref,
                "compared_with": why, "max_lufs": lim, "over_db": None if mx is None else round(mx - ref, 2),
                "fix": None if ok else "lower its gain_db (or the swell in the score) until its loudest 400 ms is under the bed's"}})
        amb = c["role"] == "ambience"
        if amb and voice100 is not None:
            i0 = int(round(c["start_s"] / HOP_S))
            under = bool(np.asarray(voice100, bool)[max(0, i0): max(0, i0 + len(c["an"]["ms"]))].any())
        else:
            under = amb                          # offline with no voice measured: judged as if under the voice
        if amb and under:
            ts = c["an"].get("tonal_low_share") or 0.0
            ok = ts <= AMB_TONAL_LOW_MAX_SHARE + 1e-9
            out.append({"rule": "ambience-low-end", "ok": ok, "unit": c["id"], "evidence": {
                "tonal_low_share": ts, "max_share": AMB_TONAL_LOW_MAX_SHARE, "under_hz": LOW_END_HZ,
                "under_voice": voice100 is not None,
                "fix": None if ok else "this is music, not room tone: take its low lines out, or file it as a bed (A29)"}})
        if (c["role"] in UNDERSCORE or amb) and not _sounds_before(c, cues):
            fi = float(c.get("fade_in_s") or 0.0)
            ok = fi >= std["entry_fade_min_s"] - 1e-9
            out.append({"rule": "music-entry", "ok": ok, "unit": c["id"], "evidence": {
                "role": c["role"], "enters_from": "no other cue" if amb else "no music", "fade_in_s": fi,
                "min_fade_in_s": std["entry_fade_min_s"],
                "fix": None if ok else f"fade it in over at least {std['entry_fade_min_s']:g} s, or carry the bed before it into it"}})
        if (c["role"] in UNDERSCORE or amb) and (c["role"] == "bed" or not _sounds_after(c, cues)):
            fo = float(c.get("fade_out_s") or 0.0)
            ok = fo >= std["entry_fade_min_s"] - 1e-9
            out.append({"rule": "music-exit", "ok": ok, "unit": c["id"], "evidence": {
                "role": c["role"], "leaves": "a bed always fades out" if c["role"] == "bed" else
                "no other cue after it" if amb else "no music after it",
                "fade_out_s": fo, "min_fade_out_s": std["entry_fade_min_s"],
                "fix": None if ok else f"fade it out over at least {std['entry_fade_min_s']:g} s"}})
    holes = music_holes(cues, duration_s, silences, own_sound, std["music_hole_max_s"], voice100)
    out.append({"rule": "music-holes", "ok": not holes, "unit": "music", "evidence": {
        "holes": holes, "count": len(holes), "max_s": std["music_hole_max_s"], "present_dbfs": PRESENT_DBFS,
        "declared": [list(map(lambda v: round(v, 2), s)) for s in silences],
        "voice_measured": voice100 is not None,
        "fix": None if not holes else "carry a bed through it, or declare it: a moment with silence: intended and its why"}})
    if voice_grid is not None and duck_grid is not None:
        pumps = duck_pumps(voice_grid, duck_grid, spans or [], std["duck_hold_s"], grid_s)
        out.append({"rule": "duck-pumping", "ok": not pumps, "unit": "music", "evidence": {
            "pumps": pumps[:30], "count": len(pumps), "hold_s": std["duck_hold_s"], "tol_db": DUCK_HELD_TOL_DB,
            "fix": None if not pumps else "the duck must hold: through every pause inside a line and every gap under the hold"}})
    return out


# --------------------------------------------------------------------------
# Offline: a film's score checked from its cue WAVs, with no mix rendered
# --------------------------------------------------------------------------

def _read(path: Path) -> np.ndarray:
    import soundfile as sf
    x, rate = sf.read(str(path), dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    if rate != RATE:
        n = int(round(len(x) * RATE / rate))
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
    return x


def fades(x: np.ndarray, n: int, fi_s: float, fo_s: float) -> np.ndarray:
    """render.cue_fades: raised-cosine fades at the start and at the end of what plays."""
    y = np.asarray(x[:n], np.float32).copy()
    n = len(y)
    fi, fo = min(n, int(round(fi_s * RATE))), min(n, int(round(fo_s * RATE)))
    if fi > 0:
        y[:fi] *= (0.5 - 0.5 * np.cos(np.pi * (np.arange(fi) + 0.5) / fi)).astype(np.float32)
    if fo > 0:
        y[n - fo:] *= (0.5 + 0.5 * np.cos(np.pi * (np.arange(fo) + 0.5) / fo)).astype(np.float32)
    return y


def place_cue(c: dict, x: np.ndarray, std: dict) -> dict:
    """One cue processed as build_mix does (the bed high-pass, levelling to
    its target over the part that plays, fades, gain_db), offline: the level
    is measured here by BS.1770 (the engine measures with ffmpeg's loudnorm,
    the same standard). Returns the placed record with its analysis."""
    role = cue_role(c)
    span = int(round((float(c["end_s"]) - float(c["start_s"])) * RATE))
    x = np.asarray(x[: max(0, span)], np.float32)
    hp = None
    if role == "bed":
        hp = std["bed_highpass_hz"]
        x = highpass(x, hp)
    target = bed_lufs(std) if role in UNDERSCORE else FEATURE_LUFS if role in ("motif", "palette") else None
    lvl = None
    if target is not None and len(x):
        kp = np.mean(_windows(k_weight(x), int(HOP_S * RATE)) ** 2, axis=1)
        m = gated_loudness(np.convolve(kp, np.ones(4) / 4, mode="valid") if len(kp) >= 4 else kp)
        lvl = None if m is None else target - m
    fi, fo = float(c.get("fade_in_s", 0) or 0), float(c.get("fade_out_s", 0) or 0)
    gain = np.float32(10 ** (((lvl or 0.0) + float(c.get("gain_db", 0.0) or 0.0)) / 20))
    y = fades(x, span, fi, fo) * gain
    return {"id": c["id"], "role": role, "start_s": float(c["start_s"]), "fade_in_s": fi, "fade_out_s": fo,
            "gain_db": float(c.get("gain_db", 0.0) or 0.0), "highpass_hz": hp, "level_db": None if lvl is None else round(lvl, 2),
            "an": analyse_cue(y, role, fi, fo, unfaded=x[:span] * gain)}


def film_cues(play: dict) -> list[dict]:
    cues = [dict(x) for part in play["parts"] for x in part.get("cues", [])]
    cues += [dict(x) for x in play.get("music", [])]       # A29(0): a missing kind is refused here as in a part
    return sorted(cues, key=lambda c: float(c["start_s"]))


def declared_silences(play: dict) -> list[tuple[float, float]]:
    """The moments and cues marked ``silence: intended`` (render.build_plan
    also reads shots and parts; offline, shot times come from start_s and
    dur_s)."""
    out = [(float(x["start_s"]), float(x["end_s"])) for x in film_cues(play) + list(play.get("moments", []))
           if x.get("silence") == "intended"]
    for part in play["parts"]:
        sh = part.get("shots", [])
        for s in sh:
            if s.get("silence") == "intended" and s.get("dur_s") is not None:
                out.append((float(s["start_s"]), float(s["start_s"]) + float(s["dur_s"])))
        if part.get("silence") == "intended" and sh and sh[-1].get("dur_s") is not None:
            out.append((float(sh[0]["start_s"]), float(sh[-1]["start_s"]) + float(sh[-1]["dur_s"])))
    return sorted(out)


def offline(film: Path, *, wav_dir: Path | None = None, voices: bool = True) -> dict:
    """The A29 checks on a film's score as its screenplay places it, read
    from the cue WAVs (``wav_dir`` replaces each cue's WAV with
    ``<wav_dir>/<stem>.wav`` when present, so a re-scored set can be checked
    against the same placements). With ``voices``, the voice takes are placed
    raw (no cleanup, no levelling: activity only) for duck-pumping, judged on
    the duck the engine now builds and on the duck it built before A29."""
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    std, stated, problems = standard(play)
    placed, swapped, missing, kinds = [], [], [], []
    for c in film_cues(play):
        if c.get("kind") not in CUE_KINDS:
            kinds.append({"rule": "cue-kind", "ok": False, "unit": c.get("id"), "evidence": {
                "kind": c.get("kind"), "kinds": list(CUE_KINDS), "fix": "state kind: music or kind: ambience"}})
            continue
        if c.get("silence") == "intended":
            continue
        rel = c.get("wav") or f"audio/{c['id']}.wav"
        p = film / rel
        if wav_dir is not None:
            stem = Path(rel).stem
            for cand in (stem, stem.split("-x")[0]):
                if (wav_dir / f"{cand}.wav").exists():
                    p = wav_dir / f"{cand}.wav"
                    swapped.append(c["id"])
                    break
        if not p.exists():
            missing.append(c["id"])
            continue
        placed.append(place_cue(c, _read(p), std))
    end = max([float(s["start_s"]) + float(s.get("dur_s") or 0) for part in play["parts"] for s in part.get("shots", [])]
              + [c["start_s"] + c["an"]["n"] / RATE for c in placed] + [0.0])
    sil = declared_silences(play)
    duck100 = voice_grid = duck_grid = voice100 = None
    spans: list[tuple[float, float]] = []
    report: dict = {}
    if voices:
        voice_grid, spans = voice_activity(film, play, end)
        duck_grid = duck_from_activity(voice_grid, spans, std["duck_hold_s"])
        old = duck_from_activity(voice_grid, [], 1.2)
        report["duck_before_a29"] = {"pumps": duck_pumps(voice_grid, old, spans, std["duck_hold_s"])}
        k = int(round(HOP_S / DUCK_GRID_S))
        n100 = len(duck_grid) // k
        duck100 = duck_grid[: n100 * k].reshape(n100, k).mean(axis=1)
        voice100 = voice_grid[: n100 * k].reshape(n100, k).any(axis=1)
    # a source's own sound: the archival lines' spans (A26). A clip playing its own soundtrack is not known offline
    # (that needs its probe), so a hole under one is reported here and not by the engine.
    own = [(float(ln["start_s"]), float(ln["start_s"]) + float(ln["out_s"]) - float(ln["in_s"]))
           for part in play["parts"] for ln in part.get("lines", []) if ln.get("archival_audio") and ln.get("clip")]
    checks = kinds + score_checks(placed, std, duration_s=end, silences=sil, own_sound=own, duck100=duck100,
                          voice_grid=voice_grid, duck_grid=duck_grid, spans=spans, voice100=voice100)
    return dict(report, film=str(film), standard=std, stated=stated, problems=problems, swapped=swapped, missing=missing,
                cues=[{k: v for k, v in c.items() if k != "an"} | {kk: c["an"][kk] for kk in
                      ("mom_max_lufs", "integrated_lufs", "breath_db", "low_share")} for c in placed],
                checks=checks)


def voice_activity(film: Path, play: dict, duration_s: float, threshold: float = 1e-3) -> tuple[np.ndarray, list]:
    """Offline: every voice line's take placed raw on the duck grid (a step is
    voiced when a sample passes -60 dBFS, render.DUCK_VOICE_THRESHOLD), and
    each line's spoken span."""
    hop = int(DUCK_GRID_S * RATE)
    act = np.zeros(int(math.ceil(duration_s / DUCK_GRID_S)) + 1, bool)
    spans = []
    for part in play["parts"]:
        for ln in part.get("lines", []):
            if ln.get("kind") not in ("narration", "testimony"):
                continue
            if ln.get("archival_audio") and ln.get("clip"):
                # A26: a span of a source's own soundtrack; offline its audio is not read, so the span counts as voiced
                a = float(ln["start_s"])
                b = a + float(ln["out_s"]) - float(ln["in_s"])
                spans.append((a, b))
                act[max(0, int(round(a / DUCK_GRID_S))): max(0, int(round(b / DUCK_GRID_S)))] = True
                continue
            p = film / (ln.get("wav") or f"audio/{ln['id']}.wav")
            if not p.exists():
                continue
            x = _read(p)
            on = np.flatnonzero(np.abs(x) > threshold)
            if not len(on):
                continue
            a = float(ln["start_s"])
            spans.append((a + on[0] / RATE, a + (on[-1] + 1) / RATE))
            w = np.abs(_windows(x, hop)).max(axis=1) > threshold
            i0 = int(round(a / DUCK_GRID_S))
            i1 = min(len(act), i0 + len(w))
            act[i0:i1] |= w[: i1 - i0]
    return act, spans


def duck_from_activity(active: np.ndarray, spans, hold_s: float, grid_s: float = DUCK_GRID_S,
                       smooth_s: float = 0.25, duck_db: float = DUCK_DB) -> np.ndarray:
    """render.duck_gain on a coarse grid (offline only): voiced steps, every
    line's spoken span filled, gaps under ``hold_s`` closed, a centred ramp."""
    a = np.asarray(active, np.float64).copy()
    for s, e in spans:
        a[max(0, int(round(s / grid_s))): max(0, int(round(e / grid_s)))] = 1.0
    runs = _runs(a > 0)
    for (_, e0), (s1, _) in zip(runs, runs[1:]):
        if (s1 - e0) * grid_s < hold_s:
            a[e0:s1] = 1.0
    k = max(1, int(round(smooth_s / grid_s)))
    env = np.clip(np.convolve(a, np.ones(k) / k, mode="same"), 0.0, 1.0)
    return (1.0 - env * (1.0 - 10 ** (-duck_db / 20))).astype(np.float32)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="GRAMMAR A29: check a film's score offline from its cue WAVs (no mix rendered)")
    ap.add_argument("film", type=Path)
    ap.add_argument("--wavs", type=Path, help="a folder of re-scored cue WAVs (<stem>.wav) to check in the same placements")
    ap.add_argument("--no-voices", action="store_true", help="skip duck-pumping (it reads every voice take)")
    ap.add_argument("--json", type=Path, help="write the full report here")
    a = ap.parse_args(argv)
    rep = offline(a.film.resolve(), wav_dir=a.wavs.resolve() if a.wavs else None, voices=not a.no_voices)
    if a.json:
        a.json.write_text(json.dumps(rep, indent=2, default=float), encoding="utf-8")
    fails = [c for c in rep["checks"] if not c["ok"]]
    for c in rep["checks"]:
        print(("PASS " if c["ok"] else "FAIL ") + f"{c['rule']:<20} {c['unit']:<8} " +
              json.dumps({k: v for k, v in c["evidence"].items() if k not in ("fix", "declared")}, default=float)[:240])
    print(f"{len(fails)} of {len(rep['checks'])} checks fail; standard {rep['standard']}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
