# Laid Down: build spec for the series title, revision 2 (Fable, 2026-10-26)

Founder ruling 2026-10-26: "Try Laid Down first." v5d is on hold. This spec is for the builder on `t/laid-down` (`D:/document-worktrees/laid-down`, `run/laid_down.py` at eb1270f) and reuses the Run pipeline: the oak desk, the wall-arm lamp and the plaster room (`desk_v5.py`, `still_v5.py`), the prepared scans and relief maps (`bench.SHEETS`, `/d/document-media/title-sequence/tex`), `channel_v5c.record_window`, the chart scene's flat-hold shader, the Foley chain, `tail_v5c.a7_master` and the no-denoiser test. Machine-readable beats: `laid-down-beats.json` beside this file; every frame, pose, speed, release point and cover fraction below is computed there, and it is the source if the two differ. Frame rate 30000/1001 only. Nothing here is rendered.

## Revision 2: what changed and why

The first stills showed the fault: at 1.30 m the frame was 0.936 x 0.527 m, so the three metre-wide sheets each covered 99.6-100% of it and f751 was the Admiralty chart edge to edge, a slideshow of single documents. The papyrus sat on a cool linen mount that read as a blue band, and its entry blur smeared the fragments.

1. **The camera rises to 2.00 m**: the frame is 1.44 x 0.81 m, a metre-wide sheet is 69% of the width, and oak shows round the pile.
2. **The poses step**: a numerical search (`topmost_cover` on a 1440 x 810 raster, the same measure as the builder's) fixed the six landings so that at every later beat every earlier sheet keeps at least 8% of the frame visible (the leaf, 10.8% of the frame in total, keeps 65% of itself) and 4% of oak remains at the end. The chart ends at 52% of the frame with a stepped rim of five sheets round it.
3. **The table grows to 4.0 x 2.0 m** (its edges are never in frame; the C-02 oak tiles at 1.2 m). At a 1.44 m frame a metre-wide sheet could not start its slide off frame on a 3.0 m top; now every release sits on the table with its leading edge 3 cm outside the frame, computed per sheet rather than fixed.
4. **The papyrus keeps its own mount**: the Museo Egizio photograph (`originals/T-02a.jpg`) shows the fragments pinned on the museum's warm-grey mount board, so the un-keyed scan is the sheet and the mount is the scan's own. No linen, nothing keyed. The opening still moves to frame 40, where the strip is nearly at rest.
5. **The builder's five departures are accepted** (section 4), and the hold frames are rendered once and repeated, which brings the final back to about 3-3.5 h.

## 0. The one idea

Records are what was set down. Under one lamp, on one oak table, the records of six ages are laid down one on another, oldest first, each sliding in and coming to rest by friction, each leaving the edges of the ones before it showing. The gaps shorten. After the last, a stillness. Then this film's own record slides onto the pile and stops, and the camera, fixed until that moment, descends onto it until the page is the frame. Hard cut to the lockup.

## 1. The sheets, in date order

Six sheets plus the film's record, all gated in `assets-ledger.json` and prepared in the Run pipeline. Seven landings is where the quickening is legible and every sheet rests at least 2.2 s; nine read as a shuffle, five lost the acceleration.

| # | Ledger | Texture | Date | Size (m) | Thickness | Why it is in |
|---|---|---|---|---|---|---|
| S1 | T-02a Turin papyrus, part 1, on the museum's mount board | `originals/T-02a.jpg` whole: the fragments, pins and grey board as photographed; board edges in the board's colour | c. 1150 BCE | 1.45 x 0.262 (see the scale note) | 3 mm board | the oldest map we hold; a band along the top of the pile that stays visible to the end |
| S2 | T-03 Catalan Atlas, boards 1 and 2 open on the hinge | `T-03_board1.jpg`, `T-03_board2.jpg` | 1375 | 1.00 x 0.69, 1.5 mm gap | 1.2 mm boards | the first sheet that fills most of the frame; lands left and low, so its left margin is the pile's first step |
| S3 | T-06 Gutenberg leaf | `T-06_leaf.jpg` | c. 1455 | 0.30 x 0.42 | 0.15 mm | the one printed thing, small, at the Atlas's top-left corner where nothing later reaches |
| S4 | T-04 Piri Reis fragment | `T-04_keyed.png` | 1513 | 0.65 x 0.87 | 0.3 mm | parchment; lands high, overflowing the frame's top, its lower half later covered |
| S5 | T-08 Ino Tadataka, sheet 6 | `T-08_sheet.jpg` | 1821 | 1.00 x 0.58 | 0.08 mm | lands right and low; its right margin is the pile's last step |
| S6 | T-20 Admiralty chart 983 | `T-20_chart.jpg` | 1931 | 1.00 x 0.675 | 0.12 mm | the last dated thing; lands centred, the descent's target |
| R | the film's record | `R-S-130.jpg` 0.30 x 0.465; `R-S-16928.jpg` 0.42 x 0.246; `R-C20-METAR-0851.jpg` 0.20 x 0.1125 | 1947, 1976, 2001 | as `bench.FILMS` | per film, laid on the chart |

**Scale note on S1.** The Run used the papyrus at 0.60 m, under scale. The Museo Egizio gives the whole papyrus (Cat. 1879, 1899, 1969) as about 2.8 m long; part 1 is taken here as 1.45 m long at 0.262 m high (the scan's aspect). The builder confirms the length from the museum record before the still; if part 1 is over 1.6 m at true scale, it will not fit the frame as a band and the fallback is to drop S1 and open on the Atlas with five sheets, keeping every other frame.

Left out: T-01 tablet (an object), T-09, T-16, T-18, the card, T-19, the coins, weights, globe and jeton. Licences PD or CC0; T-03 carries BnF's commercial caveat, which the non-commercial channel satisfies. No AI pixels; no denoiser.

## 2. The beats

29.97 fps, 1080 frames (36.036 s), then the slot's 6 s lockup card on a hard cut. The master opens from black. "Enter" is the leading edge entering the frame, "stop" the full stop, "hold" stop to the next entry. Entry intervals fall 6.65, 5.62, 4.45, 4.06, 3.30 s; the stillness breaks the pattern at 4.52 s. Positions are metres from the pile centre P, +x to the frame's right, +y to the top; psi is the long side from +x.

| Beat | Frames | Seconds | What |
|---|---|---|---|
| black | 0-11 | 0.00-0.40 | room tone; the papyrus slide audible from f6 |
| S1 papyrus | enter 12, stop 43 | 0.40-1.45 | from the sitter's side (bottom), lands at (+0.02, +0.33), psi +3.5; a band along the frame's top; hold 5.6 s |
| S2 Atlas | enter 211, stop 242 | 7.05-8.08 | from the left, lands at (-0.41, -0.11), psi -4.0; hold 4.6 s |
| S3 leaf | enter 380, stop 402 | 12.68-13.41 | from the bottom, lands at (-0.53, +0.22), psi +4.0, on the Atlas's top-left; hold 3.7 s |
| S4 Piri Reis | enter 513, stop 548 | 17.12-18.28 | from the right, lands at (-0.14, +0.19), psi -0.2; hold 2.9 s |
| S5 Ino | enter 635, stop 668 | 21.19-22.29 | from the right, lands at (+0.39, -0.22), psi -1.6; hold 2.2 s |
| S6 chart | enter 734, stop 772 | 24.49-25.77 | from the left, lands at (0.00, -0.14), psi -4.0 |
| stillness | 772-868 | 25.77-29.00 | 3.2 s, 1.47 times the last hold; nothing moves; the pattern says a sheet is due at about 27.8 s and none comes |
| R record | enter 869, stop 883 (C20), 887 (S-130), 884 (S-16928) | 29.00-29.6 | from the bottom, lands at (+0.05, -0.17) on the chart, psi +1.5 |
| descent | 869-1019 | 29.00-34.00 | the only camera move: from 2.00 m onto the record's pose, smoothstep, 5.0 s, from the frame the record enters |
| pose hold | 1019-1079 | 34.00-36.04 | the record's window fills the frame; flat-hold at 1.0; `record_pose.from_frame` 1019 |
| cut | 1080 | | hard cut to the lockup card |

Cover at each stop, as a fraction of the frame (from the JSON): after S2, oak 34%, papyrus 22%, Atlas 45%. After S4: oak 31%, papyrus 9%, Atlas 18%, leaf 7%, Piri 36%. After S6: oak 4.4%, papyrus 8.6%, Atlas 8.7%, leaf 7.0%, Piri 11.1%, Ino 8.7%, chart 51.6%. The record at its stop covers 2% (METAR), 12% (S-130) or 9% (S-16928) of the frame, on the chart.

If the animatic shows the first hold (5.6 s on the strip and oak) is too long, take 1.2 s from it and give 0.4 s each to holds 3, 4 and 5; keep the stillness.

## 3. The camera

One 50 mm on a 36 mm sensor, f/8, 180 deg shutter, exactly top-down, frame +y toward the back wall. Fixed for frames 0-868 at 2.00 m over P = (2.0, 1.0), the centre of a 4.0 x 2.0 m oak top. Frame on the table 1.44 x 0.81 m; 1.33 px per mm at 1080p. A metre-wide sheet is 69% of the width, Piri 45%, the leaf 21%, the record 14-29% at its stop. The pile overflows the frame's top by design (the papyrus band and Piri's top edge) and never its sides; oak shows at the left, right and bottom until S5 and at the corners to the end.

Why 2.00 m and not 2.2: at 2.2 the search scattered the pile (the Atlas half out of frame) to keep its rims, and a 3 mm settle fell under 4 px. Why not lower: at 1.6 m a metre-wide sheet is 87% of the width and the rims cannot be kept. Why the table grew: a sheet must start its slide fully on the table and fully off frame; with a 1.44 m frame that needs 1.25 m of table beyond the frame's edge on each side.

The descent (869-1019): from (P, 2.00) to the pose, eye over the record's centre at z = window width / 0.72, rolled to the record's psi so the window exactly fills the frame: C20 0.278 m, S-130 0.417 m, S-16928 0.583 m (`record_window`). Smoothstep (`shot_v5c._smooth`), 5.0 s, no spring; focus pulled with it; the record is still sliding for the first 0.5 s and the camera aims at its pre-solved rest from the first frame.

## 4. The physics

Rigid thin plates with their real thickness and the existing relief heightmaps, released off frame by a push that is never seen, sliding to rest under Coulomb friction. All closed form, baked to keyframes; nothing simulated at render time.

**The slide.** Constant deceleration a = mu_eff g; v falls linearly to zero with no ease. The release point is the shortest distance that puts the leading edge 3 cm outside the frame (`back_of` in the generator; checked on the table). Visible slides run 0.75 s (the leaf) to 1.29 s (the chart); entry speeds 1.5-2.2 m/s. mu_eff per pair, tuned once on the animatic within 20%: papyrus board on oak 0.16; Atlas boards on the papyrus board and oak 0.16; leaf on vellum 0.30; parchment on vellum 0.18; washi on parchment 0.14; chart on washi 0.15; record on chart 0.28. Large sheets glide on an air film, which is why their values are low. Sides: S1, S3 and R from the sitter's side; S2 and S6 from the left; S4 and S5 from the right.

**The turn.** Spin and slide stop together under isotropic Coulomb friction (Farkas, Bartels, Unger and Wolf, 2003): each sheet enters psi_land minus 2-4 deg and turns onto psi_land with the same quadratic profile as its distance. Nothing eases after the stop.

**The lift, the lie, the settle (the builder's departures, all accepted).** The trailing corner's lift, min(4 mm, 2 mm per m/s of release speed), is held through the slide as the air film it stands for, then over 0.25 s after the stop the sheet lies down onto the pile point by point (as `still_v5.paper` lays dealt papers), so the pile never floats; the Atlas boards do not lift, their trailing edge rides 1 mm and drops in 0.1 s. Cockle is capped at 1.5 mm so edge gaps stay under 2.5 mm. At 1.33 px per mm a 4 mm settle is 5 px: visible at 1080p, and the contact shadows carry the rest. Sheets exist from their release frame, which is off frame by construction.

Evidence returned: the solved table (release, v_entry, t_visible, delta, stop) per sheet; a plot of v(t) with linear stops; `topmost_cover` at every stop frame against the floors in `checks`; the no-denoiser test green.

## 5. Light and exposure

One lamp, unchanged for 1080 frames: `desk_v5.LAMP` in kind (0.26 m shade, 90 W, 3400 K against a 4300 K white balance, the emitter inside the shade), at P + (0.45, 0.90, 1.40) = (2.45, 1.90, 1.40), aimed at P: elevation 54 deg over the pile from the back-right, so every edge, step and lifted corner shadows toward the frame's lower left. The wall is at y 2.4; the camera at 2.00 m is above the lamp head and 1.2 m from it; neither shade nor arm is in a top-down frame. Fill is the room's bounce only; the world black. Falloff across the 1.44 m frame is about 0.9 stop, read as a lamp.

Exposure fixed for the whole shot, set once on the chart's paper white at about 0.85; no meter, no ease. View transform Standard throughout (as the chart proofs). The flat-hold is the chart scene's material with the builder's emission at 2^-EV so the scan's values come out exact under the fixed exposure; mix 0 to 1 over frames 1007-1019, 1 to the end; `record_pose {window, from_frame 1019}`; A7 by construction, edges exact because the window fills the frame. Fallback: AgX with `tail_v5c.POSE_EV` and the measured route.

## 6. Foley

Three events per sheet: the slide (continuous, level and brightness by speed, 20 log10(v / v_ref), low-pass as v falls), the edge (a flick as the leading edge rides onto the sheet below, from the solved crossing frame), the settle (one soft tap 0.25 s after the stop). Seven material pairs as section 4. Each slide starts off frame and is heard 0.1-0.3 s before it is seen; the first under black. The stillness is room tone only. Sources: CC0 paper-on-wood and paper-on-paper recordings (the 62 catalogued in the title-and-score design), hash-pinned with `fetch_run_sounds.py`, sliced as `foley_v5c.py` does, house IR, room tone -72 dBFS RMS. No bed, nothing under the lockup.

## 7. Score

Keep the v5d theme (G Dorian, the six stems, the 6 s lockup phrase); re-spot, do not recompose. The settle figure (three quickening notes and a landing fifth) is the title's shape: landing notes on the stops, frames 43, 242, 402, 548, 668, 772, never within 80 ms of a slide's start or a settle tap; the stretto on S4-S6; the stillness (772-868) a bare restatement or silence that makes the missing landing felt; the long line over the record's arrival and the descent; the final fifth as the flat-hold completes (1019); the hold unscored. Length within 0.4 s of the v5d mix, so the lockup stem is reused. The film's score clock starts at zero where the title ends. If a theme written for a rolling body will not re-spot to seven landings, say so and write the new one to the same frames.

## 8. The stills, and the animatic's acceptance

Two stills, 2560 x 1440, 2048 spp, no denoiser:
1. **Frame 772, the pile complete.** The chart centred at 52% of the frame; round it, stepped and shadowed toward the lower left, the Ino's right margin, Piri's top, the Atlas's left margin with the leaf on its corner, the papyrus band along the top, and oak at the corners. This is the founder's judgement still: does a pile of real paper under one lamp carry the title.
2. **Frame 40, the opening.** The papyrus on its grey board nearly at rest on bare oak, blur under 8 px, its shadow toward the lower left. The entry blur (about 25 px at f22) is judged on the animatic, not on a still.
A third frame, 1040 for S-130, is a check: the Gazette filling the frame, A7 and edge strips from `a7_master`.

Animatic: 480 x 270, 24-32 spp, no denoiser, all 1080 frames with Foley and the re-spotted theme. Accept when all hold:
- `topmost_cover` at every stop frame meets the floors in the JSON (8% of frame per earlier sheet; 60% of its own area for the leaf); oak at least 4% at 772.
- Every stop is a friction stop (v linear to zero, the turn stopping with it); every sheet heard before seen; the settle tap 0.25 s after each stop.
- Entry intervals strictly decrease to S6 (6.65 to 3.30 s); the stillness at least 1.4 times the last hold.
- The lamp and exposure constant; the record never in frame before 869; from 1019 A7 under 6.0 and edges under 12 for all three films.
- `test_timing_v5d.py` replaced by a test of the beats file (frames, monotone intervals, releases on the table and off frame, the cover floors).

The beats that decide "shot, not slideshow": S2 (a metre of vellum gliding a second onto the papyrus band, its shadow leading, the band still showing above it); S5 then S6 (two metre-wide sheets 3.3 s apart, each leaving the other's margin); the stillness over a stepped pile; the small record and the one descent. If a landing reads as animation, the fix is friction and blur, never easing. If the title reads as slides, cut to five sheets (drop S1 and S3) and lengthen the slides; never add camera moves.

## 9. Cost and risk

**Rendered once.** The lamp, camera and pile are static between a settle and the next release, so every hold frame after its 0.25 s settle is identical: render one and repeat it (deterministic, no interpolation), likewise the stillness and the pose hold. What renders: six slides with their settles (244 frames), six hold frames, three descents (151 frames each) and three pose frames: about 710 frames against the 1,500 the builder measured at 5-6 h, with motion blur on the slides costing more per frame. Estimate 3-3.5 h at 512 spp adaptive, no denoiser; stills about 1 h; animatic about 0.7 h. Tokens about 0.8 M from here.

**Risks.** (1) Slideshow: still 1 decides it before anything else renders. (2) The papyrus scale (section 1 note) and its entry blur; fallback: open on the Atlas with five sheets. (3) The leaf enters fastest (2.2 m/s) and blurs most; it is small and the fix is a lower mu for it. (4) The pile overflows the frame's top from S1 on; intended, but the founder judges it on still 1. (5) Standard view transform on the desk scene: fallback stated. (6) Piri's low scan: 3 px per mm against 1.33 on screen, well inside the limit. (7) The unseen push holds only while no hand, no shadow of one and no second light ever enters.
