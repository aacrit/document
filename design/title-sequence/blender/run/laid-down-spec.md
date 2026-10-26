# Laid Down: build spec for the series title (Fable, 2026-10-26)

Founder ruling 2026-10-26: "Try Laid Down first." v5d is on hold; its final does not render. This spec is written for the builder working in `D:/document-worktrees/run-v5d` (branch `t/run-v5d`) and reuses that pipeline: the oak desk, the one wall-arm lamp and the plaster room (`run/desk_v5.py`, `run/still_v5.py`), the prepared scans and relief maps (`run/bench.py` SHEETS, `/d/document-media/title-sequence/tex`), the record windows (`run/channel_v5c.record_window`), the flat-hold shader (`chart/chart_scene.py`), the Foley and room chain (`run/foley_v5c.py`, `run/fetch_run_sounds.py`), the A7 measurement (`run/tail_v5c.a7_master`) and the no-denoiser test. Machine-readable beats: `laid-down-beats.json` beside this file. Frame rate 30000/1001 only (founder, 2026-10-25). Nothing here is rendered yet.

## 0. The one idea

Records are what was set down. Under one lamp, on one oak table, the records of six ages are laid down one on another, oldest first, each sliding in and coming to rest by friction. The gaps shorten. After the last, a stillness. Then this film's own record slides onto the pile and stops, and the camera, fixed until that moment, descends onto it until the page is the frame. Hard cut to the lockup. No marble, no groove, no machine: one lamp, paper, physics, and the record as the last thing laid.

## 1. The sheets, in date order

Rule for inclusion: a real scan already gated in the title ledger (`design/title-sequence/assets-ledger.json`) and already prepared as a texture with its relief in the Run pipeline, flat enough to be laid as a sheet, big enough to read from 1.40 m. Six sheets plus the film's record. Seven landings is the count at which the quickening is still legible and every sheet still rests at least 2.2 s before the next enters; nine (adding the typed page and the Morse tape) pushed the last three under a second each and read as a shuffle; five lost the acceleration.

| # | Ledger | Texture (tex/) | Date | Real size (m) | Thickness | Why it is in |
|---|---|---|---|---|---|---|
| S1 | T-02a Turin papyrus map, on its linen mount | `T-02a_keyed.png` (alpha) | c. 1150 BCE | 0.62 x 0.13 (mount) | 0.25 mm + backing | the oldest map we hold; a strip on bare oak is the only time the oak is seen as ground |
| S2 | T-03 Catalan Atlas, boards 1 and 2 open on their hinge | `T-03_board1.jpg`, `T-03_board2.jpg` | 1375 | 1.00 x 0.69 (two boards, 1.5 mm gap) | 1.2 mm boards | the first sheet that fills the frame; painted vellum under the lamp |
| S3 | T-06 Gutenberg leaf, Genesis 1 | `T-06_leaf.jpg` | c. 1455 | 0.30 x 0.42 | 0.15 mm | the one printed thing; small on the Atlas, which is the point |
| S4 | T-04 Piri Reis fragment | `T-04_keyed.png` (alpha) | 1513 | 0.65 x 0.87 (portrait) | 0.3 mm | parchment, the cut edge; overflows the frame top and bottom |
| S5 | T-08 Ino Tadataka, sheet 6 | `T-08_sheet.jpg` | 1821 | 1.00 x 0.58 | 0.08 mm | washi, the red survey line; fills the frame |
| S6 | T-20 Admiralty chart 983 | `T-20_chart.jpg` | 1931 | 1.00 x 0.675 | 0.12 mm | the last dated thing before any horizon (v3 section 5) |
| R | the film's record | `R-S-130.jpg` 0.30 x 0.465; `R-S-16928.jpg` 0.42 x 0.246; `R-C20-METAR-0851.jpg` 0.20 x 0.1125 | 1947, 1976, 2001 | as `bench.FILMS` | per film, the last thing laid |

Left out: T-01 tablet (an object, not a sheet; it may lie off-frame on the near edge, never seen), T-09 tape, T-16 strip, T-18 page, the Hollerith card and T-19 stick chart (small or raised; they made the pile a shuffle), the coins, weights, globe and jeton (the pile is paper only). The 1.5 mm gap between the Atlas boards is kept: it is the hinge and it reads as two boards. Licences: all PD or CC0; T-03 carries BnF's commercial-reuse caveat, which the non-commercial channel satisfies; record it in the master's provenance as before. No AI pixels anywhere; no denoiser (`tests/test_no_denoise.py` stays).

## 2. The beats

29.97 fps. 1080 frames (36.036 s), then the slot's 6 s lockup card (TS1b) on a hard cut, as the film builders hold it. The master opens from its own black (A40). Times are the sheet's leading edge entering the frame ("enter") and its full stop ("stop"); "hold" is stop to the next entry. Entry intervals fall 6.42, 5.70, 4.24, 3.79, 3.37 s, then the stillness breaks the pattern at 5.08 s. Every frame below is computed in `laid-down-beats.json` from the poses and friction values of section 4; the JSON is the source if they ever differ.

| Beat | Frames | Seconds | What |
|---|---|---|---|
| black | 0-11 | 0.000-0.400 | room tone; the papyrus is already sliding, heard from f6 |
| S1 papyrus | enter 12, stop 37 | 0.40-1.22 | from the left, lands at (-0.05, +0.08), psi +4.0 deg; hold 5.6 s |
| S2 Atlas | enter 204, stop 237 | 6.82-7.92 | from the right, lands at (+0.02, -0.01), psi -2.5 deg; hold 4.6 s |
| S3 leaf | enter 375, stop 391 | 12.52-13.06 | from the sitter's side (bottom of frame), lands at (+0.12, -0.04), psi +3.0 deg; hold 3.7 s |
| S4 Piri Reis | enter 502, stop 529 | 16.76-17.65 | from the left, lands at (-0.10, +0.02), psi -3.5 deg; the leaf's right 4 cm stays visible; hold 2.9 s |
| S5 Ino | enter 616, stop 651 | 20.55-21.72 | from the right, lands at (+0.03, -0.02), psi +2.0 deg; hold 2.2 s |
| S6 chart | enter 717, stop 751 | 23.92-25.05 | from the left, lands at (-0.02, +0.03), psi -1.5 deg |
| stillness | 751-868 | 25.05-29.00 | 3.9 s. Nothing moves, nothing sounds but the room and the theme. The pattern says a sheet is due at about 27.3 s; none comes. This replaces the assessment's "beat of dark oak": from a fixed top-down the pile is the frame, so the years with nothing to show are shown as time, not as wood |
| R record | enter 869, stop 884 (C20), 887 (S-130), 885 (S-16928) | 29.00-29.6 | from the sitter's side, lands at (0, 0), psi +1.5 deg, on the chart |
| descent | 869-1019 | 29.00-34.00 | the only camera move: the rostrum descends from 1.30 m onto the record's pose, starting the frame the record enters; smoothstep, 5.0 s |
| pose hold | 1019-1079 | 34.00-36.04 | the record's window fills the frame; flat-hold at 1.0; A7 holds by construction; `record_pose.from_frame` 1019 |
| cut | 1080 | | hard cut to the lockup card (6 s, the slot's TS1b) |

Positions are metres from the pile centre P on the table (section 3), +x to the frame's right, +y to the frame's top; psi is the sheet's long side from +x. Shared prefix: frames 0-868, rendered once. Tails: 869-1079 per film (211 frames each).

If the animatic shows the first hold (5.6 s on a strip and bare oak) is too long, take 1.2 s from it and give 0.4 s each to holds 3, 4 and 5; keep the stillness.

## 3. The camera

One 50 mm on a 36 mm sensor (`desk_v5.LENS_MM`, `SENSOR_MM`), f/8 throughout, 180 deg shutter, focus on the pile's top surface, pulled with the descent. Exactly top-down (the lens axis along -z), frame +y toward the back wall, as `bench.record_size` assumes.

Fixed position for frames 0-868: over the pile centre P = (1.50, 0.85), the centre of the 3.0 x 1.7 m v5 desk, height 1.30 m above the top. The frame on the table is then 0.936 x 0.527 m. The pile sits at the table's centre and the camera this low for one physical reason: a 1.00 m sheet must start its slide fully outside the frame and fully on the table, and 3.0 m of table leaves a 3 cm window for that on each side (the JSON checks every release point for both). A 1.00 m sheet overflows the width by 3 cm a side, which is correct (the frame is paper edge to edge); the 0.69 and 0.675 m sheets overflow the height; Piri Reis overflows top and bottom; the leaf is 32% of the width, small on the Atlas by design; the record is 21-45% of the width when it stops, then the descent makes it the frame. Argument against 35 mm: the pile is read as surface, not as space, and a wider lens would show the table's edges and the lamp's arm. Argument against descending during the prefix: a fixed camera is what makes the one move at the end mean something.

The descent (869-1019): from (P, 1.30) to the pose: eye over the record's centre at z_pose = window width / 0.72, the frame rolled to the record's psi (+1.5 deg) so the window exactly fills the frame (the chart scene's "hold fit"): C20-METAR-0851 0.278 m; S-130 0.417 m (its window is the sheet's full width from the top, `record_window`); S-16928 0.583 m (full width from the top, 16:9 window 0.42 x 0.236). Smoothstep in time (`shot_v5c._smooth`), 5.0 s, no spring. The record is still sliding for the first 0.5 s of the descent; the camera aims at its pre-solved resting pose from the first frame, so the sheet slides into the frame's centre as the frame closes on it.

## 4. The physics

A sheet is a rigid thin plate with its scan, its real thickness and its relief heightmap (`relief.py`, the cockle and corner lifts already defined per sheet in `bench.SHEETS`; no curls, no rolled edges). It is released off-frame on the table by a push that is never seen and slides to rest under Coulomb friction. Everything is solved in closed form and baked to keyframes; nothing is simulated at render time.

The slide. Constant deceleration a = mu_eff * g; the stop is where v reaches zero, and v reaches zero linearly, with no ease. The resting pose is given (section 2); from it, mu_eff and the side of entry, the entry speed and the release point follow: with d the distance the leading edge travels from the frame's edge to the stop, t_vis = sqrt(2 d / a) and v_entry = a t_vis. mu_eff per pair, to be tuned once on the animatic within the stated range: papyrus mount on oak 0.22; Atlas boards on papyrus and oak 0.16; leaf on vellum 0.30; parchment on vellum 0.18; washi on parchment 0.14; chart on washi 0.15; the record on the chart 0.28. The low values for the large sheets are real: a big flat sheet slid fast rides an air film and glides further than a small one. The resulting visible slides are 0.54 s (the leaf) to 1.17 s (Ino); release points lie 0.56 to 0.97 m back along the table, on the table, outside the frame (checked in the JSON: `release_on_table`, `release_off_frame`). Large sheets enter from the left or right because only there is the table long enough for a sheet to start off-frame; small sheets (the leaf, the record) come from the sitter's side. The push that precedes release is never seen; for the metre-wide sheets it begins with the sheet overhanging the table's end, as a person feeds a large sheet on, and that too is off-frame.

The turn. A sliding plate turns as it slides, and with isotropic Coulomb friction its spin and its translation stop at the same instant (Farkas, Bartels, Unger and Wolf, 2003). So each sheet enters at psi_land minus 2 to 5 deg and turns onto its landing psi with the same quadratic profile as its distance: psi(t) = psi_land - delta (1 - t / t_vis)^2. Nothing eases after the stop. Delta per sheet is in the JSON.

The lift and the settle. A thin sheet sliding fast lifts its trailing corner a few millimetres on the air it drags; at the stop the air escapes and the corner comes down. Model: the trailing corner's lift = min(3 mm, 2 mm * v / 1 m/s) during the slide, decaying to the sheet's resting corner lift over 0.25 s after the stop (a shape key keyed to speed; the chart's `kinematics.py` lift is the pattern). At 1.30 m one millimetre is 2.05 px, so a 3 mm settle is 6 px and visible. The Atlas boards do not lift (they are boards); their settle is a 1 mm drop of the trailing edge over 0.1 s as the gap under them closes.

The pile. A sheet rests on whatever is under it: its z is the maximum of the heights it covers (`still_v5.under_at` does this for the dealt papers). A sheet crossing an edge of the sheet below rides over a step of 0.1 to 1.2 mm; the tilt is under 0.1 deg and is ignored, the contact shadow is not: the thickness, the step and the corner lifts are what the lamp draws.

Evidence the builder returns: the solved table (entry point, v_entry, t_vis, delta, stop frame) per sheet; a plot of v(t) for all seven showing linear stops; one MuJoCo run of a sliding plate on a flat plane, if wanted, to show the coupled stop; the no-denoiser test green.

## 5. Light and exposure

One lamp, unchanged for 1080 frames: the wall-arm reading lamp as `desk_v5.LAMP` (0.26 m shade, 90 W, 3400 K against a 4300 K white balance, 110 deg spread, the area emitter inside the shade geometry), moved with the pile: position (1.95, 1.75, 1.40) in table coordinates, aimed at P. From there its elevation over the pile centre is 54 deg and its azimuth is the back-right, so every edge, step and lifted corner throws its contact shadow toward the frame's lower left, the sitter's side. Fill is the room's own bounce (plaster, the 4.3 m ceiling, the dark floor; `still_v5.room`); the world is black; nothing else emits. Falloff across the 0.94 m frame is about 0.6 stop (`lamp_falloff_stops`), which the eye reads as a lamp. The camera at 1.30 m is below the lamp head and 1.0 m from it; neither the shade nor the arm is in a top-down frame. The lamp never moves, dims or warms.

Exposure is fixed for the whole shot: no meter, no ease. Set it once on the chart's paper white (S6) so it sits at about 0.85 of white, and keep it through the descent; the flat-hold takes over the record's pixels at the pose regardless of exposure. View transform: Standard for the whole title, as `chart_scene.py` ran its proofs, because emission 1.0 under Standard writes the scan's own values and the frame has no highlight that needs AgX. This is a change from v5c's AgX; the builder confirms on the still that paper and oak look right under Standard.

The flat-hold (A7 by construction). The record's material is the chart scene's "record flat-hold": lit diffuse paper mixed toward pure emission of the scan at strength 1.0, the mix baked per frame: 0 until frame 1007, rising over 12 frames to 1.0 at 1019 (the pose's first frame), 1.0 to the end. From 1019 the record's window fills the frame and the pixels are the scan's, so `record_difference` is resampling only (the chart proofs measured under 1.0) and `pose_edge_difference` passes because the window sits exactly on the frame. `record_pose: {window: record_window(rec), from_frame: 1019}` per film; the hold is 2.04 s, above A40's 0.5 s. Fallback if the Standard transform is refused: v5c's metered route (`tail_v5c.POSE_EV`, AgX, A7 measured with the engine's own `a7_master`).

## 6. Foley

Materials in order: papyrus mount on oak; vellum boards on papyrus and oak; paper on vellum; parchment on vellum; washi on parchment; chart paper on washi; the record's paper on the chart. Three events per sheet: the slide (a continuous hiss whose level and brightness follow speed, 20 log10(v / v_ref) with a gentle low-pass as v falls, pitch within 3 percent), the edge (a flick as the leading edge rides onto the sheet below, from the solved crossing frame), and the stop (near silence; then the settle: one soft tap as the lifted corner comes down, 0.25 s after the stop). The slide starts off-frame, so each sheet is heard 0.1-0.3 s before it is seen; the first is heard under black. The stillness has room tone only. Sources: CC0 recordings of paper slid on wood and on paper (the 62 candidates catalogued in the title-and-score design, section 2.2), fetched and pinned by hash with `fetch_run_sounds.py`, sliced to loops and one-shots with velocity layers as `foley_v5c.py` does, convolved with the house room IR; room tone at -72 dBFS RMS, 60 Hz to 3 kHz, the same room as the score. No bed, no pad, no Foley under the lockup.

## 7. Score

Keep the v5d theme: G Dorian, the house chamber group, its six stems (`/d/document-media/title-sequence/theme-v5d/stems`), its 6 s lockup phrase. It was spotted to the marble's event list; it is now re-spotted to the landing list in `laid-down-beats.json`, not recomposed. What to tell the music director:

- The settle figure (three quickening notes and a landing fifth) is now the whole title's shape: seven landings whose entries quicken from 6.4 to 3.4 s, then a stillness, then the last landing. Place the figure's landing notes on the stops (frames 37, 237, 391, 529, 651, 751), never within 80 ms of a slide's start or a settle tap. The stretto belongs to S4-S6.
- The stillness (751-868) is the theme's bare restatement or its silence; it must make the missing landing felt, not fill it.
- The record's arrival (869) and the descent get the long line; the final fifth lands as the flat-hold completes (1019), and the hold is held, not scored over.
- Length: 36.036 s plus the 6 s lockup, within 0.4 s of the v5d mix (36.403 + 6), so the lockup stem is reused as is.
- The take handover rule stands: the film's score clock starts at zero where the title ends (founder, 2026-10-26).

If the music director judges that a theme written for a rolling body cannot be re-spotted to seven landings, say so and write the new one to the same beats; the frame list does not change.

## 8. The still, and the animatic's acceptance

Two stills before any animatic, both 2560x1440, 2048 spp, no denoiser, from `render_still_v5.py`'s pattern:
1. Frame 751, the pile complete: the chart on top; the edges of Ino, Piri Reis, the leaf's corner and the Atlas's corner visible as a stepped rim toward the lower left; contact shadows under every edge; the oak at no more than the frame's corners. This is the founder's judgement still: texture, the lamp, and whether a pile of real paper is spectacle enough.
2. Frame 22, the opening: lit oak, the papyrus mid-slide with 180 deg motion blur, its shadow ahead of it. This is the "already in motion" still.
A third frame, 1040 for S-130, is a check, not a judgement: the Gazette filling the frame with its A7 and edge-strip numbers from `a7_master`.

Animatic: 480x270, 24-32 spp, no denoiser, all 1080 frames with Foley and the re-spotted theme, as `proof_v5d.py` did. Accept when all of these hold:
- Every stop is a friction stop: v(t) linear to zero, the turn stopping with it, no ease-out anywhere (check the baked curves, then watch S2 and S6 at 1080p).
- Every sheet is heard before it is seen; every stop is one event; the settle tap follows by 0.25 s.
- At every beat the previous sheet shows on at least one side of the new one, and the pile's rim is visible from S3 on.
- Entry intervals strictly decrease to S6 (6.42 to 3.37 s); the stillness (3.9 s) is at least 1.4 times the last hold (2.2 s).
- The lamp is constant: no frame-to-frame exposure change outside the descent's own framing.
- The record is never in frame before 869; from 1019 to 1079 A7 is under 6.0 and the edge strips under 12 for all three films.
- The marble checks are retired; `test_timing_v5d.py` is replaced by a test of the beats file (frames, monotone intervals, release points on the table).

The beats that decide "shot, not slideshow", in order of weight: S2 (a metre of painted vellum gliding 1.1 s across a papyrus with blur, its shadow line leading); the opening (the picture starts on a sheet already moving); S5 to S6 (two metre-wide sheets 3.4 s apart); the stillness; the record's small arrival and the one slow descent. If S2 reads as an animation, the fix is friction and blur (lower mu_eff, confirm the shutter), not more motion. If the title reads as slides, cut to five sheets (drop S1 and S3) and lengthen the slides, never add camera moves.

## 9. Cost and risk

GPU, one job at a time: two stills about 1 h; the animatic about 0.7 h; the final at 1920x1080, 512 spp adaptive (threshold 0.02), no denoiser, no depth of field to speak of and a fixed camera: about 1.5-2 h for the shared prefix and about 0.4 h per tail, roughly 3-3.5 h in all, against v5d's 3.9. Tokens: about 0.5 M for the scene and the slide solver with tests, 0.3 M for Foley and the re-spot, 0.3 M for the proofs and reviews.

Risks, honestly. (1) Slideshow: the whole bet; the stills and S2 in the animatic decide it before the final. (2) The first hold: 5.6 s on a strip and oak may be long; the redistribution in section 2 is ready. (3) The Standard view transform across the whole title is new to the desk scene; if oak or paper look wrong, fall back to AgX with the metered A7 route. (4) Piri Reis is a low scan (1964 x 2619): at 1.30 m it is 3 px per mm against 2.05 px per mm on screen, inside the 1.6x limit; the descent never magnifies it. (5) The stillness can read as a stall if the theme fills it; the brief to the music director is explicit. (6) The off-frame push is never seen and never explained; it is the same convention as the Run's latch and Rest's slide, and it holds as long as no hand, no shadow of a hand and no second light ever enters.
