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
    "bed_lowmid_hz": 400.0,             # a bed's shaping passes over this (24 dB an octave) and keeps the sub-bass under
                                        # SUB_BASS_HZ: the voice-competing low-mids between are cut (A29 refined)
    "bed_lowmid_max_share": 0.10,       # a bed's (or regional cue's) share of its energy over 100 Hz in LOW_MID_HZ, shaped
    "music_treble_max_share": 0.02,     # any scored cue's share of its energy over 100 Hz above TREBLE_HZ
    "bed_breath_db": 6.0,               # a bed's 100 ms level spread (p90 minus p10) at least this: a drone breathes
    "transition_over_bed_max_db": 0.0,  # a transition's or sting's loudest 400 ms never above the bed it leads into
    "entry_fade_min_s": 1.5,            # an underscore cue that enters from no music fades in at least this long
    "music_hole_max_s": 1.5,            # a stretch with no music between the first and last cue, undeclared, at most this
    "duck_hold_s": 1.2,                 # the duck holds through a voice gap shorter than this (and every pause in a line)
}
BOUNDS = {                              # what A29 lets a film set: (lowest, highest)
    "bed_under_dialogue_db": (12.0, 20.0),      # quieter, never louder
    "bed_lowmid_hz": (400.0, 500.0),
    "bed_lowmid_max_share": (0.0, 0.10),
    "music_treble_max_share": (0.0, 0.02),
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
# A37 (R12; founder: "before Tara is about to speak, the music drops too sharply"): the duck's attack is a pre-roll
# that eases in, in dB, on the house sine in-out (BRAND-KIT 6, the dissolve's curve) over DUCK_ATTACK_S before the
# voice's onset and is at full depth on the onset. Its steepest drop is DUCK_DB * pi / 2 per DUCK_ATTACK_S
# (1.41 dB per 100 ms at 1.0 s); the old 250 ms centred linear ramp fell about 5 dB in its steepest 100 ms (4.75 on
# the 10 ms grid) and reached only half depth at the onset. duck-slope refuses an attack steeper than DUCK_ATTACK_MAX_DB per 100 ms.
DUCK_ATTACK_S = 1.0
DUCK_ATTACK_MAX_DB = 2.0            # per 100 ms: a 0.7 s sine pre-roll (2.0 dB) is the steepest that passes

ROLES = ("bed", "transition", "sting", "outro", "regional", "motif", "brand_pulse", "palette", "main_title")
UNDERSCORE = ("bed", "transition", "sting", "outro", "regional")   # levelled to the bed target; under the score standard
TRANSITIONS = ("transition", "sting", "outro")            # linted against the bed they lead into (or follow)
SHAPED = ("bed", "regional")                              # band-shaped (bed_shape) before they are levelled
FILM_LAYER = ("bed", "transition", "sting", "outro")      # the film's own score: never another film's (bed-reuse)
BRAND = ("motif", "brand_pulse", "main_title")            # the house's signature: recurs by design (score-repetition);
                                                          # A40: the main-title theme plays in every film's series titles
TREBLE_LIMITED = UNDERSCORE + BRAND                       # music-treble: every scored cue (a palette recording is a source)
FEATURED = ("motif", "brand_pulse", "palette", "main_title")   # heard for itself, levelled to FEATURE_LUFS
MUSIC_ROLES = ("underscore", "house_motif", "brand_pulse", "palette", "main_title")   # a music cue's `role`; absent is underscore
RULES = ("bed-under-voice", "bed-low-end", "music-treble", "bed-breathing", "underscore-level", "ambience-level",
         "ambience-low-end", "transition-ceiling", "regional-density", "brand-pulse-place", "bed-reuse",
         "score-repetition", "phone-check", "music-entry", "music-exit", "music-holes", "duck-pumping", "duck-slope")
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

# A29 refined (founder, 2026-10-11: the brand "a lot more bass heavy, a lot less treble"; the film's own score "calm,
# almost classical"; regional "sparsely"). The bands, measured in ENGINE-LOG 2026-10-11 R10.
SUB_BASS_HZ = 100.0                 # under this: sub-bass, allowed (the brand pulse's fundamental, a bed's floor); a phone
                                    # speaker plays none of it and it does not cover the voice's words
VOICE_BAND_HZ = (150.0, 4000.0)     # where the words are (a narrator's fundamental to the consonants): kept clear
LOW_MID_HZ = (150.0, 400.0)         # the voice-competing low-mids: a bed's measured share (bed-low-end)
TREBLE_HZ = 5000.0                  # over this: the treble, limited (music-treble) and shelved on a bed
SHAPE_ORDER = 4                     # the bed shaping's two branches, 24 dB an octave
TREBLE_SHELF_DB = 6.0               # a bed's gentle treble shelf: half of it at TREBLE_HZ, all of it an octave or two up
PHONE_HP_HZ = 150.0                 # the small-speaker simulation (phone-check)
PHONE_LP_HZ = 8000.0
PHONE_WINDOW_S = 1.0                # the voice's margin is judged on 1 s windows, every 0.5 s, inside each spoken line
PHONE_WINDOW_HOP_S = 0.5
PHONE_SPEECH_DB = 10.0              # a window counts as speech when the line's band level is within 10 dB of its mean
PHONE_VOICE_MARGIN_DB = 15.0        # on the phone, the voice's band level at least this over the score's, every window
PULSE_PHONE_UNDER_DIALOGUE_DB = 24.0    # the brand pulse on the phone at most this under the dialogue target (-44 LUFS)
REGIONAL_MAX_SHARE = 0.05           # regional seconds at most 5% of the runtime
REGIONAL_MAX_S = 8.0                # no regional cue over 8 s ("a couple of blocks of the tanpura")
REGIONAL_MIN_GAP_S = 60.0           # at least 60 s from one regional cue's end to the next one's start
PULSE_AROUND_S = 3.0                # a brand pulse is on or around a title or chapter card: within 3 s of one
# score-repetition (founder, 2026-10-11: "patterns are repeating and it's jarring"), calibrated in ENGINE-LOG R10
REP_HOP_S = 0.1                     # the feature grid
REP_NFFT = 8192                     # 171 ms windows: a semitone apart at 110 Hz
REP_SEG_S = 4.0                     # a recurring segment is 4 s or more
REP_LOOP_COUNT = 3                  # heard three times back to back is a tiled loop (twice is a restatement)
REP_MIN_CROSS_S = 1.5               # two cues are compared on 4 s, or on the shorter one when it is at least this long
REP_CHROMA_MIN = 0.97               # near-identical: the same notes,
REP_ENV_MIN = 0.95                  # the same spectrum (register, orchestration),
REP_ONSET_MIN = 0.90                # and the same rhythm, all three at once
REP_ONSET_FLAT = 25.0               # an onset envelope with a variance under this (std 5; a note's attack is 100s, a
                                    # held chord's beating 1 to 3) has no rhythm to compare


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
    any other is a bed (the strictest reading). `role: brand_pulse` is the
    brand pulse (A29 refined); a regional cue is only ever stated
    (``score_role: regional``), never read from a name. Ambience is not
    music. role_problem says what build_plan refuses."""
    if c.get("kind", "music") != "music":
        return "ambience"
    if c.get("role") == "house_motif":
        return "motif"
    if c.get("role") == "palette":
        return "palette"
    if c.get("role") == "brand_pulse":
        return "brand_pulse"
    if c.get("role") == "main_title":          # A40: the series titles' theme, developed from the house motif
        return "main_title"
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
    cue may state bed, transition, sting, outro or regional; motif only with
    `role: house_motif`, palette only with `role: palette`, brand_pulse only
    with `role: brand_pulse`); a regional cue without its ``marks_moment``
    (a non-empty string), and a ``marks_moment`` on any other cue."""
    if c.get("kind", "music") != "music":
        return "marks_moment is for a regional music cue only" if "marks_moment" in c else None
    role = c.get("role")
    if role is not None and (not isinstance(role, str) or role not in MUSIC_ROLES):
        return f"role {role!r} is not one of {', '.join(MUSIC_ROLES)}"
    if "score_role" in c:
        sr = c["score_role"]
        allowed = {"house_motif": ("motif",), "palette": ("palette",), "brand_pulse": ("brand_pulse",),
                   "main_title": ("main_title",)}.get(role, UNDERSCORE)
        if not isinstance(sr, str) or sr not in allowed:
            return f"score_role {sr!r} with role {role or 'underscore'!r}: it may be {', '.join(allowed)}"
    regional = cue_role(c) == "regional"
    mm = c.get("marks_moment")
    if regional and not (isinstance(mm, str) and mm.strip()):
        return ("a regional cue states marks_moment: the critical moment it lands on, in words (A29 refined: "
                "regional music is punctuation, where critical things happen)")
    if not regional and "marks_moment" in c:
        return "marks_moment is for a regional cue only (score_role: regional)"
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
    """A second-order high-pass at ``hz`` (12 dB an octave). Before A29
    refined it was the bed filter; a bed is now band-shaped (bed_shape)."""
    return _filtered(x, lambda f: highpass_mag(f, hz))


def butter_mag(f: np.ndarray, hz: float, order: int, kind: str) -> np.ndarray:
    """A Butterworth magnitude of ``order`` (6 dB an octave each): -3 dB at hz."""
    r = (np.asarray(f, np.float64) / float(hz)) ** order
    return r / np.sqrt(1.0 + r * r) if kind == "high" else 1.0 / np.sqrt(1.0 + r * r)


def shelf_mag(f: np.ndarray, hz: float, cut_db: float) -> np.ndarray:
    """A first-order high shelf: unity well under ``hz``, ``cut_db`` down well
    over it, half the cut (in dB) at ``hz``."""
    g = 10 ** (-float(cut_db) / 20)
    r = (np.asarray(f, np.float64) / (float(hz) * math.sqrt(g))) ** 2      # centred so the midpoint (in dB) lands on hz
    return np.sqrt((1.0 + g * g * r) / (1.0 + r))


def bed_shape_mag(f: np.ndarray, lowmid_hz: float) -> np.ndarray:
    """A29 refined: a bed's band-shaping. Two branches added in magnitude
    (zero phase, so they sum without cancelling): the sub-bass kept (a
    4th-order low-pass at SUB_BASS_HZ) and everything over the low-mids
    (a 4th-order high-pass at ``lowmid_hz``), so the voice-competing
    150 to 400 Hz is cut (-13 dB at 150 Hz, -18 dB at 200 Hz, -10 dB at
    300 Hz with the default 400 Hz) and the sub-bass passes (-0.3 dB at
    60 Hz); then a gentle treble shelf (TREBLE_SHELF_DB at TREBLE_HZ)."""
    return np.minimum(1.0, butter_mag(f, SUB_BASS_HZ, SHAPE_ORDER, "low") + butter_mag(f, lowmid_hz, SHAPE_ORDER, "high")) \
        * shelf_mag(f, TREBLE_HZ, TREBLE_SHELF_DB)


def bed_shape(x: np.ndarray, lowmid_hz: float) -> np.ndarray:
    """A29 refined: a bed or a regional cue through bed_shape_mag."""
    return _filtered(x, lambda f: bed_shape_mag(f, lowmid_hz))


def phone_mag(f: np.ndarray) -> np.ndarray:
    """A29 refined: a small speaker, simulated: a 4th-order high-pass at
    PHONE_HP_HZ (a micro speaker falls 12 dB an octave under its resonance and
    the phone's protection filter adds 12 more) and a first-order roll-off at
    PHONE_LP_HZ."""
    return butter_mag(f, PHONE_HP_HZ, 4, "high") * butter_mag(f, PHONE_LP_HZ, 1, "low")


def band_shares(x: np.ndarray) -> dict:
    """Where a cue's energy sits: its shares of the energy over SUB_BASS_HZ
    (the audible band on any speaker) in the low-mids (LOW_MID_HZ) and in the
    treble (over TREBLE_HZ), and the sub-bass's share of all of it. Measured
    against the energy over 100 Hz so a loud sub-bass never dilutes them."""
    seg = np.asarray(x, np.float64)
    if len(seg) < 2:
        return {"lowmid_share": 0.0, "treble_share": 0.0, "sub_share": 0.0}
    P = np.abs(np.fft.rfft(seg)) ** 2
    f = np.fft.rfftfreq(len(seg), 1.0 / RATE)
    P, f = P[1:], f[1:]
    tot, over = float(P.sum()), float(P[f >= SUB_BASS_HZ].sum())
    lm = float(P[(f >= LOW_MID_HZ[0]) & (f < LOW_MID_HZ[1])].sum())
    tr = float(P[f >= TREBLE_HZ].sum())
    return {"lowmid_share": round(lm / over, 4) if over > 0 else 0.0, "treble_share": round(tr / over, 4) if over > 0 else 0.0,
            "sub_share": round(max(0.0, 1.0 - over / tot), 4) if tot > 0 else 0.0}


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


def integrated_lufs(x: np.ndarray) -> float | None:
    """BS.1770 integrated loudness of ``x`` (K-weighted 400 ms blocks every
    100 ms, gated), as analyse_cue measures a cue."""
    y = k_weight(np.asarray(x, np.float32)).astype(np.float64)
    b, h = int(0.4 * RATE), int(0.1 * RATE)
    if len(y) < b:
        y = np.concatenate([y, np.zeros(b - len(y))])
    c = np.concatenate(([0.0], np.cumsum(y * y)))
    starts = np.arange(0, len(y) - b + 1, h)
    return gated_loudness((c[starts + b] - c[starts]) / b)


# --------------------------------------------------------------------------
# A38 (R12; founder: "Tara's voice sounds a little too much treble; can't we have some bass to supplement?"): the
# house narrator voicing EQ, applied at the mix to the narrator's lines only, zero-phase, then re-levelled so the line
# stays at the dialogue target. Chosen from Tara's long-term spectrum over the pilot's 81 narration takes against
# ANSI S3.5's speech spectrum (normalised at 500 Hz to 1 kHz): 6.3 kHz +6.3 dB and 8 kHz +14.5 dB over it (the
# treble the founder hears); 160 to 200 Hz already +8 to +9 dB (her fundamental, median 176 Hz), 250 Hz +4.6;
# 2.5 to 4 kHz 2 to 4 dB under it (her presence, which must not lose more). So the cut is a high shelf of the top
# of the founder's range, -2.5 dB with its half-gain point at 6 kHz: -1.4 at 6.3 kHz, -2.0 at 8 kHz, -2.3 at 10 kHz,
# and only -0.4 at 4 kHz. The warmth is a bell, not a shelf (Tara has nothing under 125 Hz for a shelf to lift):
# +2.5 dB at 200 Hz, Q 1.2 (+1.7 at 150, +1.9 at 250, +1.25 at 300 Hz), so it gives the chest just over her
# fundamental and leaves the low-mids that muddy speech nearly alone (+0.6 at 400 Hz, +0.3 at 500); most of it sits
# above a phone's 150 Hz cut, where it adds to the voice band rather than to what the phone throws away.
# --------------------------------------------------------------------------

NARRATOR_EQ_HOUSE = {"low": {"type": "bell", "hz": 200.0, "gain_db": 2.5, "q": 1.2},
                     "high": {"type": "high_shelf", "hz": 6000.0, "gain_db": -2.5, "slope": 1.0}}
NARRATOR_EQ_BOUNDS = {"low": {"type": ("bell",), "hz": (100.0, 300.0), "gain_db": (0.0, 3.0), "q": (0.5, 2.0)},
                      "high": {"type": ("high_shelf",), "hz": (5000.0, 9000.0), "gain_db": (-3.0, 0.0), "slope": (0.5, 1.0)}}
NARRATOR_EQ_TOL_DB = 0.5             # narrator-eq: the response measured on each line within this of the declared one
NARRATOR_EQ_MIN_SHARE = 1e-3         # ... in a band holding at least this share of the line's energy (else inconclusive:
                                     # a test tone has nothing at 9 kHz but the filter's own ringing at its edges)


def _biquad_mag(f: np.ndarray, b, a) -> np.ndarray:
    z = np.exp(-2j * np.pi * np.asarray(f, np.float64) / RATE)
    return np.abs((b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z))


def _band_coeffs(band: dict):
    """RBJ cookbook coefficients at RATE for a bell or a high shelf."""
    A = 10 ** (float(band["gain_db"]) / 40)
    w0 = 2 * math.pi * float(band["hz"]) / RATE
    cw, sw = math.cos(w0), math.sin(w0)
    if band["type"] == "bell":
        al = sw / (2 * float(band["q"]))
        return (1 + al * A, -2 * cw, 1 - al * A), (1 + al / A, -2 * cw, 1 - al / A)
    al = sw / 2 * math.sqrt((A + 1 / A) * (1 / float(band["slope"]) - 1) + 2)
    sa = 2 * math.sqrt(A) * al
    b = (A * ((A + 1) + (A - 1) * cw + sa), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - sa))
    a = ((A + 1) - (A - 1) * cw + sa, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - sa)
    return b, a


def eq_mag(f: np.ndarray, eq: dict) -> np.ndarray:
    """The EQ's magnitude: the product of its bands' (low, high)."""
    m = np.ones(len(np.atleast_1d(f)))
    for k in ("low", "high"):
        if eq.get(k):
            m = m * _biquad_mag(f, *_band_coeffs(eq[k]))
    return m


def eq_db_at(hz: float, eq: dict) -> float:
    return round(float(20 * np.log10(eq_mag(np.array([float(hz)]), eq)[0])), 3)


def narrator_eq_setting(play: dict) -> tuple[dict | None, str, list[str]]:
    """A38: the film's ``narrator_eq``: absent or ``"house"`` is the house EQ
    (on by default), ``false`` or ``"off"`` none, an object {low, high} the
    film's own inside NARRATOR_EQ_BOUNDS. Returns (eq or None, how it was
    declared, problems)."""
    v = play.get("narrator_eq", "house") if isinstance(play, dict) else "house"
    if v is None or v == "house":
        return {k: dict(b) for k, b in NARRATOR_EQ_HOUSE.items()}, ("house (default)" if "narrator_eq" not in play else "house"), []
    if v is False or v == "off":
        return None, "off", []
    if not isinstance(v, dict) or set(v) - {"low", "high"} or not v:
        return None, "invalid", [f"narrator_eq must be \"house\", \"off\" or {{low, high}}, not {v!r}"]
    problems, eq = [], {}
    for k, band in v.items():
        bounds = NARRATOR_EQ_BOUNDS[k]
        if not isinstance(band, dict) or set(band) != set(bounds):
            problems.append(f"narrator_eq.{k} needs exactly {sorted(bounds)}")
            continue
        if band["type"] not in bounds["type"]:
            problems.append(f"narrator_eq.{k}.type must be {bounds['type'][0]}")
            continue
        for p, (lo, hi) in ((p, r) for p, r in bounds.items() if p != "type"):
            x = band[p]
            if isinstance(x, bool) or not isinstance(x, (int, float)) or not lo <= float(x) <= hi:
                problems.append(f"narrator_eq.{k}.{p} {x!r} is outside {lo:g} to {hi:g}")
        eq[k] = dict(band)
    return (None if problems else eq), "film", problems


def apply_voice_eq(x: np.ndarray, eq: dict) -> tuple[np.ndarray, dict]:
    """A38: the EQ on one narration line, zero-phase, then one static gain so
    the line's integrated loudness is what it was (it stays at the dialogue
    target). Returns the line and its record: the gain, and the response
    measured on this line (output over input energy) in the bands either side
    of each declared corner against the declared response there."""
    y = _filtered(x, lambda f: eq_mag(f, eq))
    before, after = integrated_lufs(x), integrated_lufs(y)
    g = 0.0 if before is None or after is None else before - after
    y = (y * np.float32(10 ** (g / 20))).astype(np.float32)
    n = _fast_len(len(x) + RATE // 2)
    fx = np.fft.rfftfreq(n, 1.0 / RATE)
    X = np.abs(np.fft.rfft(np.asarray(x, np.float64), n)) ** 2
    Y = np.abs(np.fft.rfft(np.asarray(y, np.float64) * 10 ** (-g / 20), n)) ** 2
    checks = []
    total = float(X.sum())
    for k, band in eq.items():
        hz = float(band["hz"]) if band["type"] == "bell" else float(band["hz"]) * 1.5
        m = (fx >= hz / 2 ** (1 / 6)) & (fx < hz * 2 ** (1 / 6))
        if X[m].sum() <= NARRATOR_EQ_MIN_SHARE * total or total <= 0:
            checks.append({"band": k, "at_hz": round(hz, 1), "measured_db": None, "declared_db": None,
                           "error_db": None, "why": "too little of the line here to measure: inconclusive"})
            continue
        meas = 10 * math.log10(Y[m].sum() / X[m].sum())
        want = 10 * math.log10(float((X[m] * eq_mag(fx[m], eq) ** 2).sum() / X[m].sum()))
        checks.append({"band": k, "at_hz": round(hz, 1), "measured_db": round(meas, 3), "declared_db": round(want, 3),
                       "error_db": round(abs(meas - want), 3)})
    return y, {"eq": eq, "relevel_db": round(g, 3), "lufs_before": before, "lufs_after_eq": after, "response": checks}


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
                unfaded: np.ndarray | None = None, features: bool = True) -> dict:
    """What the standard reads of one cue as the mix places it (levelled,
    faded, gained): per 100 ms window its RMS (dBFS) and K-weighted power,
    its momentary loudness (400 ms) and their maximum, its integrated
    loudness, over its full-level part (between its fades) where its energy
    sits (band_shares: the low-mids, the treble, the sub-bass), for the
    brand pulse its loudness through the small-speaker simulation
    (``phone_lufs``), for any music but the brand's its repetition features
    (rep_features, of ``unfaded`` when given; ``features`` false skips
    them), and its breathing: the level spread (p90
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
    shares = band_shares(y[full.start * hop: full.stop * hop])
    src = unfaded if unfaded is not None else y
    tonal = tonal_low_share(src) if role == "ambience" else None
    phone = None
    if role == "brand_pulse" and len(y):
        pk = np.mean(_windows(_filtered(y, lambda f: k_mag(f) * phone_mag(f)), hop) ** 2, axis=1)
        phone = gated_loudness(np.convolve(pk, np.ones(4) / 4, mode="valid") if len(pk) >= 4 else pk)
    feat = rep_features(src) if features and role not in BRAND + ("ambience",) else None
    return {"role": role, "n": len(y), "ms": ms.astype(np.float32), "kp": kp.astype(np.float32), "tonal_low_share": tonal,
            "mom_max_lufs": round(float(-0.691 + _db(mom).max()), 2) if len(mom) else None,
            "integrated_lufs": gated_loudness(mom) if len(mom) else None,
            "integrated_unfaded_lufs": integrated_unfaded,
            "full": [full.start, full.stop],
            "breath_db": round(spread, 2), "breath_judged": judged, **shares, "phone_lufs": phone, "feat": feat}


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


def duck_attack(gain: np.ndarray, closed: np.ndarray, rate: float, *, attack_s: float = DUCK_ATTACK_S,
                smooth_s: float = 0.25, duck_db: float = DUCK_DB) -> np.ndarray:
    """A37: the duck's pre-roll. ``gain`` is the duck as the centred ramp
    builds it (its release is kept); ``closed`` the ducked stretches (voice
    with its held gaps), on a grid of ``rate`` samples a second. Before each
    stretch's onset the gain falls over ``attack_s`` on the sine in-out in dB,
    reaching -duck_db on the onset and holding it through the half-ramp after
    it (where the centred ramp was still at half depth). The deeper of the two
    gains wins, so the release is unchanged. Returns the new gain (a copy)."""
    g = np.asarray(gain, np.float32).copy()
    c = np.asarray(closed) > 0.5
    if not c.any():
        return g
    n = max(1, int(round(attack_s * rate)))
    half = max(1, int(round(smooth_s / 2 * rate)))
    u = (np.arange(n) + 1.0) / n
    curve = (10 ** (-duck_db * (0.5 - 0.5 * np.cos(np.pi * u)) / 20)).astype(np.float32)   # ends at full depth
    floor = np.float32(10 ** (-duck_db / 20))
    edges = np.diff(np.concatenate(([0], c.astype(np.int8), [0])))
    for a, b in zip(np.flatnonzero(edges == 1).tolist(), np.flatnonzero(edges == -1).tolist()):
        lo = max(0, a - n)
        if a > lo:
            g[lo:a] = np.minimum(g[lo:a], curve[n - (a - lo):][: a - lo])
        e = min(b, a + half)
        g[a:e] = np.minimum(g[a:e], floor)
    return g


def duck_slopes(duck: np.ndarray, grid_s: float = DUCK_GRID_S) -> dict:
    """A37, duck-slope: the duck gain's steepest fall and rise over any 100 ms
    on its grid, in dB, and where."""
    db = 20 * np.log10(np.maximum(np.asarray(duck, np.float64), 1e-6))
    k = max(1, int(round(0.1 / grid_s)))
    if len(db) <= k:
        return {"attack_db_per_100ms": 0.0, "release_db_per_100ms": 0.0, "attack_at_s": None, "release_at_s": None}
    d = db[k:] - db[:-k]
    i, j = int(np.argmin(d)), int(np.argmax(d))
    return {"attack_db_per_100ms": round(float(max(0.0, -d[i])), 2), "attack_at_s": round(i * grid_s, 2),
            "release_db_per_100ms": round(float(max(0.0, d[j])), 2), "release_at_s": round(j * grid_s, 2)}


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
# Repetition (A29 refined, founder 2026-10-11: "We need variance in music...
# right now patterns are repeating and it's jarring")
# --------------------------------------------------------------------------

def rep_features(y: np.ndarray) -> dict:
    """What score-repetition compares, per REP_HOP_S frame (REP_NFFT Hann
    windows): ``chroma`` (12 pitch classes, 55 Hz to 5 kHz, unit length: the
    notes), ``env`` (log energy in third-octave bands, 50 Hz to 6.4 kHz,
    z-scored per frame: register and orchestration), ``onset`` (spectral flux
    on the log magnitude over 100 Hz, relative to the cue's own loudest bin:
    the rhythm) and ``live`` (a frame within 60 dB of the cue's loudest).
    Level-free: a gain, a duck or a slow swell changes none of them."""
    x = np.asarray(y, np.float64)
    edges = _REP_BANDS
    hop = int(round(REP_HOP_S * RATE))
    n = int(math.ceil(len(x) / hop)) if len(x) else 0
    if n == 0:
        z = np.zeros((0, 12), np.float32)
        return {"chroma": z, "env": np.zeros((0, len(edges) - 1), np.float32), "onset": np.zeros(0, np.float32),
                "live": np.zeros(0, bool)}
    pad = np.concatenate([np.zeros(REP_NFFT // 2), x, np.zeros(REP_NFFT)])
    f = np.fft.rfftfreq(REP_NFFT, 1.0 / RATE)
    keep = f < 8000.0
    win = np.hanning(REP_NFFT)
    mags = np.empty((n, int(keep.sum())), np.float32)
    for a in range(0, n, 256):                                       # 256 frames at a time: bounded memory
        idx = np.arange(a, min(n, a + 256))[:, None] * hop + np.arange(REP_NFFT)[None, :]
        mags[a: a + len(idx)] = np.abs(np.fft.rfft(pad[idx] * win, axis=1))[:, keep]
    f = f[keep]
    peak = float(mags.max()) if mags.size else 0.0
    if peak <= 0:
        return {"chroma": np.zeros((n, 12), np.float32), "env": np.zeros((n, len(edges) - 1), np.float32),
                "onset": np.zeros(n, np.float32), "live": np.zeros(n, bool)}
    m = mags / peak
    power = (m.astype(np.float64) ** 2).sum(axis=1)
    live = power > power.max() * 1e-6
    cb = (f >= 55.0) & (f < 5000.0)
    pc = np.mod(np.round(12 * np.log2(f[cb] / 440.0)).astype(int), 12)
    chroma = np.zeros((n, 12))
    for k in range(12):
        chroma[:, k] = m[:, cb][:, pc == k].sum(axis=1)
    chroma /= np.maximum(np.linalg.norm(chroma, axis=1, keepdims=True), 1e-12)
    band = np.digitize(f, edges) - 1
    env = np.stack([(m[:, band == k].astype(np.float64) ** 2).sum(axis=1) for k in range(len(edges) - 1)], axis=1)
    env = np.log10(env + 1e-10)
    env = (env - env.mean(axis=1, keepdims=True)) / np.maximum(env.std(axis=1, keepdims=True), 1e-9)
    lg = np.log1p(1000.0 * m[:, f >= 100.0].astype(np.float64))
    onset = np.concatenate([lg[:1].sum(axis=1), np.maximum(0.0, np.diff(lg, axis=0)).sum(axis=1)])   # frame 0: from silence
    chroma[~live] = 0.0
    env[~live] = 0.0
    return {"chroma": chroma.astype(np.float32), "env": env.astype(np.float32), "onset": onset.astype(np.float32), "live": live}


_REP_BANDS = 50.0 * 2.0 ** (np.arange(0, 22) / 3.0)                # third-octave edges, 50 Hz to 6.4 kHz (21 bands)


def _win_sum(v: np.ndarray, w: int) -> np.ndarray:
    c = np.concatenate([[0.0], np.cumsum(np.asarray(v, np.float64))])
    return c[w:] - c[:-w]


def _pearson(sa, sb, sab, saa, sbb, w: int):
    """Pearson's r from window sums; None where either side is flat (no rhythm to compare)."""
    va, vb = saa - sa * sa / w, sbb - sb * sb / w
    flat = (va <= REP_ONSET_FLAT * w) | (vb <= REP_ONSET_FLAT * w)
    r = (sab - sa * sb / w) / np.sqrt(np.maximum(va * vb, 1e-30))
    return np.where(flat, np.nan, r)


def _near(c, e, o) -> np.ndarray:
    """Near-identical: the notes, the spectrum and the rhythm all match (a flat rhythm never does: a drone is
    judged by bed-breathing, not here)."""
    return (c >= REP_CHROMA_MIN) & (e >= REP_ENV_MIN) & (np.nan_to_num(o, nan=-1.0) >= REP_ONSET_MIN)


def _score(c, e, o) -> np.ndarray:
    """One number per comparison for the journal: the weakest of the three similarities, each over its threshold
    as a ratio (1.0 or more on all three is near-identical)."""
    return np.minimum(np.minimum(c / REP_CHROMA_MIN, e / REP_ENV_MIN), np.nan_to_num(o, nan=0.0) / REP_ONSET_MIN)


def self_repetition(feat: dict) -> dict:
    """score-repetition within a cue: the strongest back-to-back recurrence.
    For every period P of at least REP_SEG_S (and at most a third of the
    cue), a segment of length P at t is compared with the one at t + P and
    that one with the one at t + 2P (frame by frame: chroma cosine, band
    correlation; over the window: the onsets' Pearson r). A tiled loop is
    a segment heard three times in a row (twice is a restatement), each
    pair near-identical. Returns the loop (if any) and the best match."""
    C, E, O = feat["chroma"].astype(np.float64), feat["env"].astype(np.float64), feat["onset"].astype(np.float64)
    n, d = len(O), max(1, E.shape[1] if E.ndim == 2 else 1)
    best = {"score": None, "period_s": None, "at_s": None, "chroma": None, "env": None, "onset": None}
    loop = None
    w0 = int(round(REP_SEG_S / REP_HOP_S))
    for p in range(w0, n // REP_LOOP_COUNT + 1):
        sc = _win_sum((C[:-p] * C[p:]).sum(axis=1), p) / p
        se = _win_sum((E[:-p] * E[p:]).sum(axis=1) / d, p) / p
        sa = _win_sum(O, p)
        sq = _win_sum(O * O, p)
        so = _pearson(sa[:-p], sa[p:], _win_sum(O[:-p] * O[p:], p), sq[:-p], sq[p:], p)
        k = len(sc) - p                                          # windows t with a third copy at t + 2P
        if k <= 0:
            continue
        s = _score(sc, se, so)
        both = np.minimum(s[:k], s[p:p + k])
        i = int(np.argmax(both))
        if best["score"] is None or both[i] > best["score"]:
            j = i if s[i] <= s[i + p] else i + p
            best = {"score": round(float(both[i]), 3), "period_s": round(p * REP_HOP_S, 1), "at_s": round(i * REP_HOP_S, 1),
                    "chroma": round(float(sc[j]), 3), "env": round(float(se[j]), 3),
                    "onset": None if np.isnan(so[j]) else round(float(so[j]), 3)}
        nr = _near(sc, se, so)
        hit = np.flatnonzero(nr[:k] & nr[p:p + k])
        if len(hit) and loop is None:
            loop = {"period_s": round(p * REP_HOP_S, 1), "at_s": round(int(hit[0]) * REP_HOP_S, 1),
                    "copies": REP_LOOP_COUNT}
    return {"loop": loop, "best": best}


def _diag_window_sums(M: np.ndarray, w: int) -> np.ndarray:
    """Out[i, j] = sum of M[i + k, j + k] for k < w (w consecutive frames of A against w of B, in step)."""
    na, nb = M.shape
    C = np.zeros((na + 1, nb + 1), np.float64)
    for i in range(na):
        C[i + 1, 1:] = M[i] + C[i, :-1]
    return C[w:, w:] - C[: na + 1 - w, : nb + 1 - w]


def cross_repetition(fa: dict, fb: dict) -> dict:
    """score-repetition across two cues: the best match of any window of
    REP_SEG_S (or the shorter cue, at least REP_MIN_CROSS_S) of one against
    the other at any offset. Near-identical on all three measures is a
    duplicate."""
    na, nb = len(fa["onset"]), len(fb["onset"])
    w = min(int(round(REP_SEG_S / REP_HOP_S)), na, nb)
    out = {"duplicate": False, "score": None, "window_s": round(w * REP_HOP_S, 1), "a_at_s": None, "b_at_s": None,
           "chroma": None, "env": None, "onset": None}
    if w * REP_HOP_S < REP_MIN_CROSS_S - 1e-9:
        out["judged"] = False
        return out
    d = max(1, fa["env"].shape[1])
    sc = _diag_window_sums(fa["chroma"].astype(np.float64) @ fb["chroma"].astype(np.float64).T, w) / w
    se = _diag_window_sums(fa["env"].astype(np.float64) @ fb["env"].astype(np.float64).T / d, w) / w
    oa, ob = fa["onset"].astype(np.float64), fb["onset"].astype(np.float64)
    sab = _diag_window_sums(np.outer(oa, ob), w)
    sa, sb = _win_sum(oa, w)[:, None], _win_sum(ob, w)[None, :]
    saa, sbb = _win_sum(oa * oa, w)[:, None], _win_sum(ob * ob, w)[None, :]
    so = _pearson(sa, sb, sab, saa, sbb, w)
    s = _score(sc, se, so)
    i, j = np.unravel_index(int(np.argmax(s)), s.shape)
    out.update(judged=True, duplicate=bool(_near(sc, se, so).any()), score=round(float(s[i, j]), 3),
               a_at_s=round(i * REP_HOP_S, 1), b_at_s=round(j * REP_HOP_S, 1), chroma=round(float(sc[i, j]), 3),
               env=round(float(se[i, j]), 3), onset=None if np.isnan(so[i, j]) else round(float(so[i, j]), 3))
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


def _span(c: dict) -> tuple[float, float]:
    return c["start_s"], c["start_s"] + c["an"]["n"] / RATE


def regional_checks(cues: list[dict], duration_s: float) -> list[dict]:
    """regional-density (A29 refined): regional music is punctuation. Each
    regional cue at most REGIONAL_MAX_S long and at least REGIONAL_MIN_GAP_S
    after the one before it ends; all of them together at most
    REGIONAL_MAX_SHARE of the runtime. Nothing when the film has none."""
    regs = sorted((c for c in cues if c["role"] == "regional"), key=lambda c: c["start_s"])
    out, prev = [], None
    for c in regs:
        a, b = _span(c)
        gap = None if prev is None else round(a - _span(prev)[1], 2)
        ok = b - a <= REGIONAL_MAX_S + 1e-9 and (gap is None or gap >= REGIONAL_MIN_GAP_S - 1e-9)
        out.append({"rule": "regional-density", "ok": ok, "unit": c["id"], "evidence": {
            "dur_s": round(b - a, 2), "max_s": REGIONAL_MAX_S, "after": None if prev is None else prev["id"], "gap_s": gap,
            "min_gap_s": REGIONAL_MIN_GAP_S, "marks_moment": c.get("marks_moment"),
            "fix": None if ok else f"a regional cue is a block of at most {REGIONAL_MAX_S:g} s, at least "
                                   f"{REGIONAL_MIN_GAP_S:g} s from the last: keep the one on the most critical moment"}})
        prev = c
    if regs:
        total = sum(_span(c)[1] - _span(c)[0] for c in regs)
        share = total / duration_s if duration_s > 0 else 1.0
        ok = share <= REGIONAL_MAX_SHARE + 1e-9
        out.append({"rule": "regional-density", "ok": ok, "unit": "regional", "evidence": {
            "count": len(regs), "total_s": round(total, 2), "runtime_s": round(duration_s, 2), "share": round(share, 4),
            "max_share": REGIONAL_MAX_SHARE,
            "fix": None if ok else f"regional music at most {REGIONAL_MAX_SHARE:.0%} of the runtime: sparsely, where critical "
                                   "things happen"}})
    return out


def pulse_floor_lufs() -> float:
    """The brand pulse's floor through the small-speaker simulation: PULSE_PHONE_UNDER_DIALOGUE_DB under the dialogue."""
    return DIALOGUE_LUFS - PULSE_PHONE_UNDER_DIALOGUE_DB


def pulse_checks(cues: list[dict], cards, voice100: np.ndarray | None) -> list[dict]:
    """brand-pulse-place: a brand pulse plays on or around a title or
    chapter card (within PULSE_AROUND_S of one) or where no voice speaks
    (``voice100``; offline without voices, only a card can place it). And
    phone-check for the pulse: its loudness through the small-speaker
    simulation at least pulse_floor_lufs, so its soft upper harmonic carries
    it where a phone plays no sub-bass."""
    out = []
    floor = pulse_floor_lufs()
    for c in (c for c in cues if c["role"] == "brand_pulse"):
        a, b = _span(c)
        card = next(((x, y) for x, y in cards if a >= x - PULSE_AROUND_S - 1e-6 and b <= y + PULSE_AROUND_S + 1e-6), None)
        voiced = None
        if voice100 is not None:
            v = np.asarray(voice100, bool)
            voiced = round(float(v[max(0, int(math.floor(a / HOP_S))): max(0, int(math.ceil(b / HOP_S)))].sum()) * HOP_S, 1)
        ok = card is not None or voiced == 0.0
        out.append({"rule": "brand-pulse-place", "ok": ok, "unit": c["id"], "evidence": {
            "from_s": round(a, 2), "to_s": round(b, 2), "card": None if card is None else [round(card[0], 2), round(card[1], 2)],
            "around_s": PULSE_AROUND_S, "voice_s": voiced, "voice_measured": voice100 is not None,
            "fix": None if ok else "the brand pulse is the house's signature at the title and chapter cards and in "
                                   "voiceless stretches, not under the narration: move it to a card or a stretch with no voice"}})
        pl = c["an"].get("phone_lufs")
        ok = pl is not None and pl >= floor - 1e-9
        out.append({"rule": "phone-check", "ok": ok, "unit": c["id"], "evidence": {
            "what": "the brand pulse, perceptible on a small speaker", "phone_lufs": pl, "floor_lufs": floor,
            "full_band_lufs": c["an"].get("integrated_unfaded_lufs") or c["an"].get("integrated_lufs"),
            "sub_share": c["an"].get("sub_share"),
            "simulation": f"mono, {PHONE_HP_HZ:g} Hz high-pass (24 dB an octave), {PHONE_LP_HZ:g} Hz roll-off (6 dB an octave)",
            "fix": None if ok else f"give the pulse a soft upper harmonic (an octave or a twelfth over its fundamental, over "
                                   f"{PHONE_HP_HZ:g} Hz): a phone plays nothing of a sub-bass alone"}})
    return out


def repetition_checks(cues: list[dict]) -> list[dict]:
    """score-repetition (founder, 2026-10-11: "We need variance in music...
    right now patterns are repeating and it's jarring"): within each music
    cue but the brand's, no segment of REP_SEG_S or more heard
    REP_LOOP_COUNT times back to back near-identically (self_repetition: a
    tiled loop); across the film, no two music cues near-duplicates
    (cross_repetition), the brand's motif and pulse exempt (they recur by
    design). Near-identical is the notes, the spectrum and the rhythm all
    matching at once, so a theme restated in another key, register,
    orchestration or rhythm passes. The largest similarities are journaled."""
    out = []
    mus = [c for c in cues if c["role"] not in BRAND + ("ambience",) and c["an"].get("feat") is not None]
    for c in mus:
        r = self_repetition(c["an"]["feat"])
        ok = r["loop"] is None
        out.append({"rule": "score-repetition", "ok": ok, "unit": c["id"], "evidence": {
            "within": True, "loop": r["loop"], "max_self_similarity": r["best"], "min_segment_s": REP_SEG_S,
            "thresholds": {"chroma": REP_CHROMA_MIN, "env": REP_ENV_MIN, "onset": REP_ONSET_MIN},
            "fix": None if ok else f"a {r['loop']['period_s']:g} s segment is heard {REP_LOOP_COUNT} times back to back: "
                                   "write the bed through (vary the voicing, the register, the rhythm), never tile it"}})
    dups, best = [], None
    for i, a in enumerate(mus):
        for b in mus[i + 1:]:
            r = cross_repetition(a["an"]["feat"], b["an"]["feat"])
            if not r.get("judged"):
                continue
            rec = {"a": a["id"], "b": b["id"], **{k: r[k] for k in ("score", "chroma", "env", "onset", "window_s", "a_at_s",
                                                                    "b_at_s")}}
            if best is None or r["score"] > best["score"]:
                best = rec
            if r["duplicate"]:
                dups.append(rec)
    if len(mus) > 1:
        out.append({"rule": "score-repetition", "ok": not dups, "unit": "music", "evidence": {
            "within": False, "duplicates": dups[:30], "count": len(dups), "max_cross_similarity": best,
            "exempt": list(BRAND), "thresholds": {"chroma": REP_CHROMA_MIN, "env": REP_ENV_MIN, "onset": REP_ONSET_MIN},
            "fix": None if not dups else "two cues play the same music: write the second one new, or restate the theme "
                                         "transformed (another key, register, orchestration or rhythm)"}})
    return out


def phone_check(voice: np.ndarray, background: np.ndarray, spans) -> dict:
    """phone-check for the dialogue: the mix as a small speaker plays it
    (phone_mag, mono), in the voice band (VOICE_BAND_HZ). Inside each spoken
    line, on PHONE_WINDOW_S windows every PHONE_WINDOW_HOP_S that hold speech
    (within PHONE_SPEECH_DB of the line's mean band level), the voice's band
    level is at least PHONE_VOICE_MARGIN_DB over the score's (``background``:
    the music as ducked, and the ambience). Returns the margins and the check."""
    lo, hi = VOICE_BAND_HZ
    win, hop = int(PHONE_WINDOW_S * RATE), int(PHONE_WINDOW_HOP_S * RATE)
    margins, worst, lines = [], [], 0
    for a, b in spans or []:
        i0, i1 = max(0, int(round(a * RATE))), min(len(voice), int(round(b * RATE)))
        if i1 - i0 < RATE // 10:
            continue
        p0, p1 = max(0, i0 - RATE // 4), min(len(voice), i1 + RATE // 4)
        band = lambda f: phone_mag(f) * ((f >= lo) & (f <= hi))      # noqa: E731
        v = _filtered(voice[p0:p1], band)[i0 - p0: i1 - p0].astype(np.float64)
        m = _filtered(background[p0:p1], band)[i0 - p0: i1 - p0].astype(np.float64)
        starts = list(range(0, max(1, len(v) - win + 1), hop)) if len(v) >= win else [0]
        pv = np.array([np.mean(v[s: s + win] ** 2) for s in starts])
        pm = np.array([np.mean(m[s: s + win] ** 2) for s in starts])
        if not len(pv) or pv.max() <= 0:
            continue
        lines += 1
        speech = pv >= np.mean(pv) * 10 ** (-PHONE_SPEECH_DB / 10)
        mg = 10 * np.log10(np.maximum(pv[speech], 1e-20) / np.maximum(pm[speech], 1e-20))
        mg = np.minimum(mg, 99.0)
        margins += mg.tolist()
        worst += [(round(float(x), 1), round(a + s / RATE, 1)) for x, s in zip(mg, np.array(starts)[speech])]
    worst.sort()
    bad = [w for w in worst if w[0] < PHONE_VOICE_MARGIN_DB - 1e-9]
    ev = {"what": "the dialogue, intelligible on a small speaker", "lines": lines, "windows": len(margins),
          "min_margin_db": worst[0][0] if worst else None,
          "p10_margin_db": round(float(np.percentile(margins, 10)), 1) if margins else None,
          "median_margin_db": round(float(np.median(margins)), 1) if margins else None,
          "min_margin_required_db": PHONE_VOICE_MARGIN_DB, "under": len(bad),
          "worst": [{"margin_db": m, "at_s": t} for m, t in worst[:10]], "band_hz": list(VOICE_BAND_HZ),
          "simulation": f"mono, {PHONE_HP_HZ:g} Hz high-pass (24 dB an octave), {PHONE_LP_HZ:g} Hz roll-off (6 dB an octave)",
          "fix": None if not bad else "the score covers the words on a phone: lower or thin what plays under these "
                                      "windows in the voice band (150 Hz to 4 kHz)"}
    return {"margins": margins, "checks": [{"rule": "phone-check", "ok": not bad, "unit": "voice", "evidence": ev}]}


# --------------------------------------------------------------------------
# bed-reuse: a film's own score is its own (founder, 2026-10-11)
# --------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
HEAD_S = 5.0                        # bed-reuse also matches the first 5 s of sound (a fold or a cut of the same WAV)
_HASHES: dict = {}


def audio_hashes(path: Path) -> tuple[str, str | None]:
    """A WAV's content hashes: sha256 of its decoded samples (float32, with
    its rate and channels), so a copy re-wrapped or re-encoded losslessly
    still matches; and of its first HEAD_S of sound (after any leading
    digital silence), so a fold or a cut of it matches too (None when it
    holds under HEAD_S of sound)."""
    import hashlib
    import soundfile as sf
    st = path.stat()
    key = (str(path.resolve()), st.st_mtime_ns, st.st_size)
    if key not in _HASHES:
        x, rate = sf.read(str(path), dtype="float32", always_2d=True)
        x = np.ascontiguousarray(x)
        tag = f"{rate}:{x.shape[1]}:".encode()
        whole = hashlib.sha256(tag + x.tobytes()).hexdigest()
        on = np.flatnonzero(np.abs(x).max(axis=1) > 1e-6)
        k = int(HEAD_S * rate)
        head = None
        if len(on) and len(x) - on[0] >= k:
            head = hashlib.sha256(tag + np.ascontiguousarray(x[on[0]: on[0] + k]).tobytes()).hexdigest()
        _HASHES[key] = (whole, head)
    return _HASHES[key]


def film_registry(root: Path = REPO_ROOT) -> list[dict]:
    """The other films bed-reuse reads: DOCUMENT_FILMS when it is set (film
    folders or screenplay.json paths, separated by os.pathsep; set and empty
    means none), else films.json's ``screenplay_path`` per film (``~`` is the
    home folder; a relative path is from the repo root). A film with no path
    is listed as not located."""
    import os
    env = os.environ.get("DOCUMENT_FILMS")
    out = []
    if env is not None:
        for p in (x.strip() for x in env.split(os.pathsep)):
            if p:
                q = Path(p).expanduser()
                out.append({"slug": None, "screenplay": q if q.suffix == ".json" else q / "screenplay.json",
                            "from": "DOCUMENT_FILMS"})
        return out
    reg = root / "films.json"
    if not reg.exists():
        return out
    for f in json.loads(reg.read_text(encoding="utf-8")).get("films", []):
        sp = f.get("screenplay_path")
        q = None
        if isinstance(sp, str) and sp.strip():
            q = Path(sp).expanduser()
            q = q if q.is_absolute() else root / q
        out.append({"slug": f.get("slug"), "screenplay": q, "from": "films.json"})
    return out


def _film_layer_wavs(film: Path, play: dict) -> list[tuple[str, Path]]:
    return [(c["id"], film / (c.get("wav") or f"audio/{c['id']}.wav")) for c in film_cues(play)
            if c.get("kind") == "music" and cue_role(c) in FILM_LAYER and c.get("silence") != "intended"]


def reuse_check(film: Path, play: dict, registry: list[dict] | None = None,
                mine: list[tuple[str, Path]] | None = None) -> dict:
    """bed-reuse: no cue of this film's own score (FILM_LAYER: a bed, a
    transition, a sting, the outro) plays a WAV another registered film's
    own score already plays, by content (audio_hashes: the whole of it, or
    its first HEAD_S of sound). The brand's motif and pulse are shared by
    design; a palette or regional recording may recur. A registered film
    whose screenplay is declared and not found is refused (its reuse cannot
    be checked); one with no path is listed as not located. ``mine`` gives
    this film's (cue id, WAV) when they are not the screenplay's own (the
    offline checker's --wavs)."""
    registry = film_registry() if registry is None else registry
    me = (film / "screenplay.json").resolve()
    slug = play.get("slug")
    theirs: dict = {}
    checked, unlocated, problems = [], [], []
    for r in registry:
        sp = r["screenplay"]
        if sp is None:
            if r.get("slug") != slug:
                unlocated.append(r.get("slug"))
            continue
        if not sp.exists():
            problems.append({"film": r.get("slug"), "screenplay": str(sp), "from": r["from"]})
            continue
        if sp.resolve() == me:
            continue
        other = json.loads(sp.read_text(encoding="utf-8"))
        if other.get("slug") == slug:
            continue
        checked.append(other.get("slug"))
        for cid, p in _film_layer_wavs(sp.parent, other):
            if p.exists():
                w, h = audio_hashes(p)
                theirs.setdefault(w, []).append({"film": other.get("slug"), "cue": cid, "wav": p.name, "match": "whole"})
                if h:
                    theirs.setdefault("head:" + h, []).append({"film": other.get("slug"), "cue": cid, "wav": p.name,
                                                               "match": "first 5 s"})
    out = []
    for cid, p in (_film_layer_wavs(film, play) if mine is None else mine):
        if not p.exists():
            continue
        w, h = audio_hashes(p)
        hit = theirs.get(w) or (theirs.get("head:" + h) if h else None)
        out.append({"rule": "bed-reuse", "ok": not hit, "unit": cid, "evidence": {
            "wav": p.name, "sha256": w[:16], "used_by": (hit or [])[:5], "films_checked": checked,
            "fix": None if not hit else "another film's score already plays this: write this film its own (the founder: "
                                        "no bed reused across films)"}})
    out.append({"rule": "bed-reuse", "ok": not problems, "unit": "registry", "evidence": {
        "films_checked": checked, "not_located": unlocated, "not_found": problems,
        "fix": None if not problems else "a registered film's screenplay_path is not there: fix films.json's "
                                         "screenplay_path or set DOCUMENT_FILMS to the film folders"}})
    return {"checks": out}


def card_spans_from_play(play: dict) -> list[tuple[float, float]]:
    """Offline: the title and chapter cards (render.card_kind's reading of a
    card shot: its explicit ``card``, else a title part's cards, else a
    chapter part's first shot), as (start, end) from start_s and dur_s."""
    out = []
    for part in play["parts"]:
        for k, s in enumerate(part.get("shots", [])):
            if s.get("kind") != "card" or s.get("dur_s") is None:
                continue
            ck = s.get("card") or ("silent" if s.get("silent_record") else
                                   part.get("kind") if part.get("kind") in ("title", "credits") else
                                   "chapter" if part.get("kind") == "chapter" and k == 0 else "statement")
            if ck in ("title", "chapter"):
                out.append((float(s["start_s"]), float(s["start_s"]) + float(s["dur_s"])))
    return out


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
                 grid_s: float = DUCK_GRID_S, voice100: np.ndarray | None = None, cards=(),
                 phone: dict | None = None, reuse: dict | None = None) -> list[dict]:
    """Every A29 check on the placed cues, as lint results: {rule, ok, unit,
    evidence}. ``cues`` are {id, role, start_s, fade_in_s, fade_out_s,
    gain_db, an (analyse_cue)}. ``duck100`` is the duck gain on the 100 ms
    grid (bed-under-voice measures the gaps with it); ``voice_grid`` and
    ``duck_grid`` (voice activity and duck gain on ``grid_s``) and the lines'
    spoken ``spans`` feed duck-pumping, which is skipped without them;
    ``voice100`` (voice activity on the 100 ms grid) lets music-holes count a
    stretch with voice as no hole, and brand-pulse-place find a voiceless
    stretch. ``cards`` are the title and chapter cards' (start, end);
    ``phone`` is phone_check's result (phone-check is skipped without it)
    and ``reuse`` is reuse_check's (bed-reuse is skipped without it)."""
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
        judged = c["an"].get("breath_judged", True)
        ok = judged and c["an"]["breath_db"] >= std["bed_breath_db"] - 1e-9
        out.append({"rule": "bed-breathing", "ok": ok, "unit": c["id"], "evidence": {
            "spread_db": c["an"]["breath_db"] if judged else None, "judged": judged, "min_db": std["bed_breath_db"],
            "window_s": HOP_S, "measure": "p90 - p10 of 100 ms RMS, levelled, before the fades",
            "fix": None if ok else ("let the drone breathe: rests (two beats in eight), one regional pluck a bar, not one a beat"
                                    if judged else f"not judged: under {BREATH_MIN_S:g} s of bed; a cue this short is a "
                                                   "transition or a sting (say so with score_role), or lengthen the bed")}})
    for c in cues:
        if c["role"] in SHAPED:
            ok = c["an"]["lowmid_share"] <= std["bed_lowmid_max_share"] + 1e-9
            out.append({"rule": "bed-low-end", "ok": ok, "unit": c["id"], "evidence": {
                "role": c["role"], "band_hz": list(LOW_MID_HZ), "share": c["an"]["lowmid_share"],
                "max_share": std["bed_lowmid_max_share"], "of": f"the energy over {SUB_BASS_HZ:g} Hz, shaped",
                "sub_share": c["an"]["sub_share"], "shaping": c.get("shaping"),
                "fix": None if ok else (f"take the notes out of {LOW_MID_HZ[0]:g} to {LOW_MID_HZ[1]:g} Hz (the voice's own "
                                        f"range): voice the bass under {SUB_BASS_HZ:g} Hz and the rest over "
                                        f"{LOW_MID_HZ[1]:g} Hz; the shaping only thins them")}})
        if c["role"] in TREBLE_LIMITED:
            ok = c["an"]["treble_share"] <= std["music_treble_max_share"] + 1e-9
            out.append({"rule": "music-treble", "ok": ok, "unit": c["id"], "evidence": {
                "role": c["role"], "over_hz": TREBLE_HZ, "share": c["an"]["treble_share"],
                "max_share": std["music_treble_max_share"], "of": f"the energy over {SUB_BASS_HZ:g} Hz"
                + (", shaped" if c["role"] in SHAPED else ""),
                "fix": None if ok else f"darken it: less over {TREBLE_HZ:g} Hz (no bright attacks, no air or shimmer layer; "
                                       "the founder: a lot less treble)"}})
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
    out += regional_checks(cues, duration_s)
    out += pulse_checks(cues, cards, voice100)
    out += repetition_checks(cues)
    if phone is not None:
        out += phone["checks"]
    if reuse is not None:
        out += reuse["checks"]
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
    if duck_grid is not None:
        sl = duck_slopes(duck_grid, grid_s)
        ok = sl["attack_db_per_100ms"] <= DUCK_ATTACK_MAX_DB + 1e-6
        out.append({"rule": "duck-slope", "ok": ok, "unit": "music", "evidence": dict(
            sl, max_attack_db_per_100ms=DUCK_ATTACK_MAX_DB, attack_s=DUCK_ATTACK_S, curve="sine in-out in dB, ending on the onset",
            fix=None if ok else "the music drops too fast before a voice: the duck's pre-roll eases in over about 1 s")})
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
    """One cue processed as build_mix does (a bed's or regional cue's
    band-shaping, levelling to its target over the part that plays, fades,
    gain_db), offline: the level is measured here by BS.1770 (the engine
    measures with ffmpeg's loudnorm, the same standard). Returns the placed
    record with its analysis."""
    role = cue_role(c)
    span = int(round((float(c["end_s"]) - float(c["start_s"])) * RATE))
    x = np.asarray(x[: max(0, span)], np.float32)
    shaping = None
    if role in SHAPED:
        shaping = shaping_record(std)
        x = bed_shape(x, std["bed_lowmid_hz"])
    target = bed_lufs(std) if role in UNDERSCORE else FEATURE_LUFS if role in FEATURED else None
    lvl = None
    if target is not None and len(x):
        kp = np.mean(_windows(k_weight(x), int(HOP_S * RATE)) ** 2, axis=1)
        m = gated_loudness(np.convolve(kp, np.ones(4) / 4, mode="valid") if len(kp) >= 4 else kp)
        lvl = None if m is None else target - m
    fi, fo = float(c.get("fade_in_s", 0) or 0), float(c.get("fade_out_s", 0) or 0)
    gain = np.float32(10 ** (((lvl or 0.0) + float(c.get("gain_db", 0.0) or 0.0)) / 20))
    y = fades(x, span, fi, fo) * gain
    return {"id": c["id"], "role": role, "start_s": float(c["start_s"]), "fade_in_s": fi, "fade_out_s": fo,
            "gain_db": float(c.get("gain_db", 0.0) or 0.0), "shaping": shaping, "level_db": None if lvl is None else round(lvl, 2),
            "marks_moment": c.get("marks_moment"), "y": y, "an": analyse_cue(y, role, fi, fo, unfaded=x[:span] * gain)}


def shaping_record(std: dict) -> dict:
    """What a bed's band-shaping did, for the journal and the evidence."""
    return {"sub_bass_kept_under_hz": SUB_BASS_HZ, "passes_over_hz": std["bed_lowmid_hz"], "order": SHAPE_ORDER,
            "treble_shelf_db": TREBLE_SHELF_DB, "treble_shelf_hz": TREBLE_HZ,
            "cut_db_at": {str(int(f)): round(float(20 * np.log10(bed_shape_mag(np.array([f]), std["bed_lowmid_hz"])[0])), 1)
                          for f in (60.0, 150.0, 200.0, 300.0, 1000.0, 8000.0)}}


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


def offline(film: Path, *, wav_dir: Path | None = None, voices: bool = True, registry: list[dict] | None = None) -> dict:
    """The A29 checks on a film's score as its screenplay places it, read
    from the cue WAVs (``wav_dir`` replaces each cue's WAV with
    ``<wav_dir>/<stem>.wav`` when present, so a re-scored set can be checked
    against the same placements). With ``voices``, the voice takes are placed
    raw (no cleanup) for duck-pumping, judged on the duck the engine now
    builds and on the duck it built before A29, and each levelled to the
    dialogue target (BS.1770 here; no mood offset) for phone-check, against
    the music as ducked plus the ambience. bed-reuse reads the other films
    from ``registry`` (film_registry when None)."""
    play = json.loads((film / "screenplay.json").read_text(encoding="utf-8"))
    std, stated, problems = standard(play)
    placed, swapped, missing, kinds, mine = [], [], [], [], []
    for c in film_cues(play):
        if c.get("kind") not in CUE_KINDS:
            kinds.append({"rule": "cue-kind", "ok": False, "unit": c.get("id"), "evidence": {
                "kind": c.get("kind"), "kinds": list(CUE_KINDS), "fix": "state kind: music or kind: ambience"}})
            continue
        why = role_problem(c)
        if why is not None:
            kinds.append({"rule": "score-role", "ok": False, "unit": c.get("id"), "evidence": {
                "role": c.get("role"), "score_role": c.get("score_role"), "problem": why, "fix": why}})
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
        if c.get("kind") == "music" and cue_role(c) in FILM_LAYER:
            mine.append((c["id"], p))
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
    phone = None
    n = int(math.ceil(end * RATE)) + 1
    if voices:
        bg = np.zeros(n, np.float32)
        duck = np.ones(n, np.float32)
        dg = np.repeat(duck_grid, int(round(DUCK_GRID_S * RATE)))[:n]
        duck[: len(dg)] = dg
        for c in placed:
            i0 = int(round(c["start_s"] * RATE))
            y = c["y"][: max(0, n - i0)]
            bg[i0: i0 + len(y)] += y if c["role"] == "ambience" else y * duck[i0: i0 + len(y)]     # ambience is not ducked
        del duck, dg
        phone = phone_check(levelled_voice(film, play, n), bg, spans)
        del bg
    for c in placed:
        c.pop("y", None)
    reuse = reuse_check(film, play, registry, mine=mine)
    checks = kinds + score_checks(placed, std, duration_s=end, silences=sil, own_sound=own, duck100=duck100,
                                  voice_grid=voice_grid, duck_grid=duck_grid, spans=spans, voice100=voice100,
                                  cards=card_spans_from_play(play), phone=phone, reuse=reuse)
    return dict(report, film=str(film), standard=std, stated=stated, problems=problems, swapped=swapped, missing=missing,
                cues=[{k: v for k, v in c.items() if k != "an"} | {kk: c["an"][kk] for kk in
                      ("mom_max_lufs", "integrated_lufs", "breath_db", "lowmid_share", "treble_share", "sub_share",
                       "phone_lufs")} for c in placed],
                checks=checks)


def levelled_voice(film: Path, play: dict, n: int) -> np.ndarray:
    """Offline: every synthetic voice take placed at the dialogue target (BS.1770 gated; the engine levels with
    loudnorm, the same standard, and then applies a mood offset of 0 to -3 dB, not applied here). An archival
    line's audio is not read offline."""
    voice = np.zeros(n, np.float32)
    hop = int(HOP_S * RATE)
    for part in play["parts"]:
        for ln in part.get("lines", []):
            if ln.get("kind") not in ("narration", "testimony") or (ln.get("archival_audio") and ln.get("clip")):
                continue
            p = film / (ln.get("wav") or f"audio/{ln['id']}.wav")
            if not p.exists():
                continue
            x = _read(p)
            kp = np.mean(_windows(k_weight(x), hop) ** 2, axis=1)
            m = gated_loudness(np.convolve(kp, np.ones(4) / 4, mode="valid") if len(kp) >= 4 else kp)
            if m is None:
                continue
            i0 = int(round(float(ln["start_s"]) * RATE))
            y = (x * np.float32(10 ** ((DIALOGUE_LUFS - m) / 20)))[: max(0, n - i0)]
            voice[i0: i0 + len(y)] += y
    return voice


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
    g = (1.0 - env * (1.0 - 10 ** (-duck_db / 20))).astype(np.float32)
    return duck_attack(g, a > 0, 1.0 / grid_s, smooth_s=smooth_s, duck_db=duck_db)     # A37: the eased pre-roll


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
