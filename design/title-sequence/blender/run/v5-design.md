# The Run v5: the desk, the lamp, the camera

Founder verdict on v4.1 (2026-10-18): the lighting was all over the place, the camera did not follow the marble, the
desk looked randomly scattered, approved inputs were missing. v5 is a fresh look at those three things on the reused
v4.1 chain (coordinator, 2026-10-25): latch, papyrus, hinge, U1, khipu, leaf, weights' glance and the run into the felt
keep their tuned poses. Constants: `desk_v5.py` (tests: `tests/test_desk_v5.py`). Plan: `layout/v5-desk-plan.png`.

## 1. The desk: one person's work, not a scatter

A 2.2 x 1.0 m oak desk 0.40 m from a plaster wall; the sitter (and the camera) on the near side, a right-handed reader.
The rule that makes it read as a desk: **one spread is being compared; everything else is put away square**, each
thing where a person would have set it down, and the records run in date order left to right down the 0.95 degree fall.

| Zone | What lies there (real size) | Why it is there |
|---|---|---|
| Centre-left: the spread (fixed by the chain) | Catalan Atlas facsimile OPEN on its two boards (hinge at -66 deg); the Turin papyrus on its linen mount on the left board; Piri Reis over the right board; the Gutenberg leaf on Piri with the galley of blank sorts on it | two portolans compared side by side; the papyrus laid beside them; the galley weighs the leaf flat and its sorts are compared with the page |
| Near-left corner | Umma tablet, squared, 1 cm from both edges; its far corner rests on the Atlas board's overhang | the heaviest, oldest thing, put down within reach |
| Back-left | the latch's bronze disc on bare oak | the approved latch, unchanged |
| Back, under the lamp | the Krakow nested cup weights (upright) on Piri's cut corner; an oak coin tray squared to the back edge, its long groove on the lead's line (y 0.821), six coins standing on edge in it | a reader weights a creeping parchment; coins are weighed, so the weights sit by the tray; coins stand in a sorting groove to be photographed |
| Right of centre, near | the late papers dealt left to right by date on bare oak: Ino's sheet folded in quarters (1821) with a length of Morse tape (1844), a blank Hollerith card (1890), 35 mm film (1895); the typed page (1921) over the sheet's edge; Admiralty chart 983 folded in six (1931) over the page | the next things to read, newer over older, squared |
| Back-right | black felt pad under the lamp, the film's record on it (R-C20-METAR-0851 shown) | where a new document is laid to be read; the lead stops at its edge (x 1.976) |
| Near-right corner | the Doppelmayr table globe (1728) on its stand, already turning slowly (bearing friction) | the right hand's corner |
| The wall | T-19 stick chart hung above the back edge | 0.80 m across: it would cover a third of the desk |

Out of v5: both reels and the platen (no scans; v4.1 never touched them), the standing brass disc (a blank disc set on
edge is staged: the last coin falls off the groove's open end and spins down on the oak instead, the same whir and
slap from a real object), the gold (no real scan).

## 2. One lamp

- **The source:** one swing-arm reading lamp on the wall behind the back-right, its 0.26 m shade 1.40 m over the top at
  (1.60, 1.25), aimed across the desk; 3400 K tungsten against a 4300 K white balance (warm, not orange). Constant for
  the whole shot: never dimmed, moved, masked or irised.
- **The pool:** the felt, the record and the coin tray are its brightest (the record sits in the pool, as ruled). It
  falls off 1.05 stops to the latch and U1 and 1.7 stops to the near-left corner; over the whole path the spread is
  1.24 stops, inside the meter's clamp.
- **The off-axis key:** from behind and to the right at 46-73 degrees over the path, so every sheet edge, ball, coin
  and weight throws its contact shadow toward the near side, the side the camera works from.
- **The room fill:** no second emitter and a black world. The fill is the lamp's own light off the plaster wall, the
  4.3 m ceiling (an old study's; the crane's wide at 3.40 m fits under it) and the floor.
- **Exposure:** the camera's own. Metered from rendered low-sample frames outside Blender (centre-weighted, on the
  lead), eased over 0.8 s, clamped to +-1.5 stops. This replaces meter_expose.py's in-Blender loop, which crashed.

## 3. The camera

- **One body, one 50 mm lens, a real aperture.** No cut, fade or time remap.
- **The follow rig:** a critically damped spring (omega 3.2 rad/s, about 0.45 s of lag) on a point 9 cm ahead of the
  lead along its velocity. The eye sits 0.45 m out at 26 degrees elevation, 155 degrees from the heading, on the
  sitter's side, so the lead runs into the frame's depth and its shadow falls toward the lens. At f/4 the focus
  distance is the lead's.
- **The lead stays legible.** Checked per frame: in frame, inside the centre 60%, at least 28 px across at 1080p (the
  follow gives about 95 px), in focus, and the pan under 40 px a frame. Clay against glass is the material contrast: the
  pair are clear glass.
- **Close passes:** 0.16 m out, 16 degrees, f/2.8 (about 267 px), eased in and out of the follow. They come at the
  latch (approved framing), U1 (low at the near edge: the lead climbs the curl toward the lens and rolls back), the
  galley strike (square to the row: the sorts fall and the pair leaves the lip), the weights' glance, the coin row (low
  along the groove), and the record.
- **The end:** the lead at rest against the record. The crane rises to the top-down wide over the whole desk (3.40 m,
  3 s), holds 2 s, then descends 4.5 s onto the record into the A7 pose (A7 at most 6.0, held 1 s).

## 4. The path and its hand-offs (v4.1 roll-out seconds; the physics step re-bakes)

latch release 5.0 -> papyrus -> Atlas hinge valley 8.2 -> **U1, Piri's curl, 9.65** (the one U-turn) -> khipu knots
10.4-11.4 -> **galley strike 11.7**: the galley moves 12 cm onto the lead's line, mouth at (1.062, 0.430), axis 58
degrees; the sorts fall and the glass pair leaves the lip -> leaf -> **weights' glance 13.96** (turns the lead along the
back) -> **coin row 15.0-17.4**: into the groove's open end at x 1.47; six coins fall in turn; the last spins down on the
oak -> felt 18.6 -> record's edge 20.4, rest 22.2. Runtime: rest 22.2 + strike and coins about 2.1 + end 10.5 = 34.8 s.

Physics risks for the next step: the galley strike after the knots (the cord's last knot ends under the mouth); the
lead's speed into the groove after the weights (0.12-0.15 m/s; each coin costs about 0.25 s); the glass pair's line
after the lip (they must not reach the groove before the lead).

## 5. Decisions for the founder

1. **The coin row.** Only two Roman coin scans and the jeton passed the gate, so six coins use each scan twice, turned
   over (A, shown). B: three coins only (a short topple). C: source more gated coin scans first.
2. **The brass disc.** Out, replaced by the last coin's spin-down (recommended), or kept.
3. **The weights' reason.** They stand on Piri's cut corner beside the tray. Keep, or set them inside the tray's end.
