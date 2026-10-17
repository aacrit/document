# void document · As It Was: Blender build plan

For the builder (Blender and ML), after the founder approves the storyboard. Blender 4.4, Cycles on the RTX 4090 Laptop (16 GB), 1920 x 1080 at 24 fps. Nothing here may run while another heavy job owns the GPU.

## Principles

1. **One script builds the scene.** `build_title.py` reads `title.yaml` (the beats, frames, station poses and ledger ids) and writes `title.blend`. Nobody hand-edits the `.blend`, so a module can be dropped by the horizon rule, or a record swapped, by re-running the script.
2. **The house motion, frame-exact.** Every arrival, stamp and settle is keyed per frame from `design/brand-kit/motion.py` (`Spring.progress` for `arrive`, `settle`, `stamp`, `drift`, `trace`; `rostrum_move` for the camera), baked as linear keys on every frame. No Blender easing and no F-curve handles. The film's springs and the title's springs are then the same numbers.
3. **Clean picture, marks by the engine.** Blender renders the machine only. The glyph, labels and watermark are burned by the engine at assembly, as for every shot. No grain, no grade, no look.
4. **Provenance is checked, not trusted.** `check_title.py` lists every image datablock in the `.blend` and fails when a file has no item in `title-ledger.json`. It also refuses any file whose ledger item says `ai`. The reviewer runs it.

## Layout on disk

| What | Where |
|---|---|
| Scripts (`build_title.py`, `check_title.py`, `title.yaml`, `title-ledger.json`) | the document repo, `studio/title/` (tracked; no media) |
| Source scans, H relief maps, `khipu-knots.csv`, `rebbelib-curves.json` | `C:/Users/aacri/document-work/title-sequence/sources/` (untracked) |
| `.blend` and renders | `C:/Users/aacri/document-work/title-sequence/` on C: (NTFS). Never on D:, which is exFAT and caused the 2026-10-10 crash |

## Scene structure

```
title.blend
├─ CAM            one camera; path = chained per-module Bezier segments; speed keyed on the rostrum curve
├─ LAMP           one light, "the reader" (area 0.15 m, or spot for beats 6 and 8); light-linked per module
├─ WORLD          near-black, strength 0.002 (shadow lift only); no HDRI
├─ M01_clay       entry/exit empties at station poses; tablet, ring, second ring, dust volume
├─ M02_atlas      papyrus sheet, table, 6 Atlas boards with hinges
├─ M03_khipu      Piri Reis sheet (one level below the table), drum, cords, knots
├─ M04_press      press, screw, platen, bed, Genesis leaf
├─ M05_survey     Ino sheet with relief, glint path, wire
├─ M06_wire       key, register train, rollers, tape ribbon
├─ M07_count      counter bank (4 x 10), press, pin box, blank card
├─ M08_reel       cinématographe, spool, strip, gate, beam volume
├─ M09_type       typebar basket, platen, carriage, typed page
├─ M10_swell      Admiralty chart, rebbelib, lashings, shells, strips
└─ M11_record     record plate (swapped per film), the last wheel's frame
```

**Station poses.** Every module has an `entry` and an `exit` empty. At both the camera looks straight down at 1.2 m above a sheet, with a 50 mm lens, at the module's cruise speed. The script chains module N+1 by moving its whole collection so its `entry` sits on module N's `exit`. Dropping a module therefore closes the chain with no new camera work. Module coordinates are local; nothing references world space.

**Scale.** Real object scale in metres: the tablet at its catalogue size, Atlas boards about 0.65 x 0.5 m, the press about 2 m tall. Depth of field comes from the real lens and distance (f/4 at macro distances), not from a fake blur.

## Procedural modelling, by module

| Module | Approach |
|---|---|
| Clay | Geometry Nodes: a rounded slab (cube, subdivision, smooth-min corners) at the tablet's measured size; its faces UV-mapped to T-01's views. Displacement from a high-pass of the raking-light photograph, at most 0.8 mm, for texture only. The ring is a GN gear generator: teeth = 24 (one per column), radius from the shot. Fired-clay shader from noise, no image. |
| Sheets (papyrus, Atlas, Piri Reis, Ino, chart) | Subdivided planes (2 mm grid where the camera is closest; adaptive elsewhere), a paper or vellum shader with sheen, thickness 0.2 mm. Atlas boards are rigid, on hinge empties whose angle is keyed from `trace`. Relief: a Displace modifier from an H map (16-bit) that the builder traces from what the sheet prints (painted hills, ranges, pictorial mountains), never from elevation data. Heights stay at a few millimetres: the land is only as high as the map draws it. |
| Khipu | GN: the primary cord is a curve around the drum's rim. Pendants are curves hanging under gravity with a small sway from a sine of the drum angle (no simulation, so it is deterministic). The cord profile is two circles twisted along the length (two-ply). Knots are three modelled meshes (single, long with n turns, figure-eight) instanced from `khipu-knots.csv` measured off T-05. |
| Press | Beveled timbers with a procedural wood shader. The screw is a GN spiral swept with a triangular thread profile, with its pitch matched to the khipu ply for the transition. Platen travel is keyed from `stamp`. |
| Survey | The glint is a small emissive-free highlight: the lamp's target moves along a curve traced on T-08's red line, on `trace`. The wire continues the same curve off the sheet's edge. |
| Wire | The key and register are GN gears (involute approximation, tooth counts from T-11), with brass and iron shaders. The tape is a curve-to-mesh ribbon whose UVs run along its length, textured with T-09 and fed at constant speed by offsetting UVs. |
| Count | The counter bank is a GN grid instance of one dial (bezel, paper face, two hands). The face graduation is drawn by the studio from T-14 (no figures). Hands advance one division on `settle` after the press `stamp`. The card is a blank manila plane with the 1890 cut corner. |
| Reel | The box, spool, gate and crank are modelled from T-15. The strip is a ribbon with one round perforation per side per frame (Lumière). Its frames are an image sequence of T-16 in order, advanced intermittently at 16 frames a second. The beam is a spot lamp through the gate into a bounded volume box, its density modulated by noise. |
| Type | GN basket: 42 bars on a semicircular segment, each a swept curve with a slug. The striking bar is keyed from `stamp`. The page reveals T-18 one character at a time through a mask built by detecting the glyphs on the scan, in reading order: the real page's own characters, no letter typeset by us. |
| Swell | Every stick of T-19 is traced as a curve in the photograph's plane, so the geometry is the object's own. Curve-to-mesh with a flattened profile, lashings as instanced tori at crossings, shells instanced at their photographed positions, name strips as small planes textured with crops of T-19. A hard area lamp casts the shadow onto T-20. |
| Record | A plane at the scan's exact aspect. The camera's last pose is solved so the plate fills the same rectangle as the engine's HOLD fit (the whole scan, pillarboxed in 1920 x 1080). The engine's first ARCHIVE frame and Blender's last frame then register to the pixel. Only this module and the frames after the machine stops are re-rendered per film. |

## Light, colour and look

- **One lamp, neutral.** Its colour is the bone white point (about 4500 K, graded to neutral). It is never amber and never blue: amber means real, and blue means AI-GENERATED or DRAWN in the marks. Light linking keeps each module's lamp off the others.
- **View transform: Khronos PBR Neutral** (Blender 4.2 and later), exposure set so a sheet's paper sits just under white. It keeps the scans' printed hues closer than AgX or Filmic do, so the Atlas's gilt and Ino's red stay as printed.
- **Volumes only where the storyboard asks:** the dust in beat 1 and the beam in beat 8. Each sits in a bounded box, never a world volume.
- **No look:** no grain, no vignette added in compositing, no colour grade. The vignette in the style frames is the lamp's fall-off, which the scene produces itself.

## Render settings (final)

| Setting | Value |
|---|---|
| Engine and device | Cycles, OptiX, GPU only (CPU off, so the laptop stays responsive) |
| Resolution and rate | 1920 x 1080, 100%, 24 fps |
| Frames | 0 to 1151 (beats 1 to 11 up to the cut; the record hold and the lockup are made by the engine) |
| Samples | adaptive, noise threshold 0.015, max 256, min 32 |
| Denoise | OpenImageDenoise on GPU, albedo and normal, prefilter accurate |
| Light paths | total 6, diffuse 3, glossy 3, transmission 4, volume 1, transparent 8; caustics off; indirect clamp 5 |
| Volumes | step rate 2 (render), max steps 256 |
| Motion blur | on, shutter 0.5 (180 degrees), as a 24 fps camera |
| Memory | persistent data on; texture limit 8192 px; scans prepared per shot at the size the shot needs (no texture larger than its biggest screen size times 1.6) |
| Seed | animated (fresh noise per frame, which the denoiser handles) |
| Output | OpenEXR, half float, DWAA, RGBA: about 4 MB a frame, about 5 GB for 1,152 frames |
| VRAM budget | about 3 GB of textures, under 1 GB of geometry, volumes small: well inside 16 GB |

**Animatic first.** An EEVEE (or Workbench) playblast of the whole chain at 1080p takes about 0.5 to 1.5 s a frame, under 30 minutes. The music director scores to it, and the founder sees motion before any Cycles frame is spent.

## Render time estimate (RTX 4090 Laptop, final settings)

| Beats | Frames | Seconds a frame (estimate) | Time |
|---|---|---|---|
| 1 (dust volume, macro depth of field) | 120 | 35 to 45 | 70 to 90 min |
| 8 (beam volume) | 96 | 30 to 40 | 48 to 64 min |
| 2 to 7, 9 to 11 (surfaces, depth of field, motion blur) | 936 | 10 to 18 | 156 to 281 min |
| **Total, shared core and one record** | **1,152** | | **about 4.5 to 7.5 hours** |

Allow a third more for thermal throttling on a laptop under sustained load: **one overnight run of about 6 to 10 hours.** After that, each further film re-renders only the record module and the settled frames before the cut (about 48 to 72 frames): **12 to 25 minutes per film.** These are estimates. The builder times 10 frames of each module first and corrects this table before the full run.

## Running it safely (machine governor, rule 13)

- **One heavy job at a time.** A render chunk, an Orpheus batch (WSL), a film render, an audio mix and the full test gate never overlap. The builder adds a lock file, `C:/Users/aacri/document-work/.heavy.lock`: written with the job name and PID before a chunk starts, removed after, and checked by the film render and Orpheus scripts. None exists yet; it is the builder's ticket, named in the brief.
- **Chunks by module:** `blender -b title.blend -s <first> -e <last> -a`, one module per chunk. A crash costs one module, and the next chunk starts only on the previous one's exit.
- **Before each chunk:** the lock is free; at least 10 GB of disk free on C: after the chunk's expected output; no dev servers or browsers left running.
- **The GPU's other owner:** no Blender process runs while another job holds the lock. This plan's own style frames used no GPU (headless Chromium with GPU off).

## Delivery

- **The master clip:** EXR frames, then the engine's assembly: DRAWN clip 0:00 to 0:48, ARCHIVE hold 0:48 to 0:52 (the record from the film's ledger), dip, CARD lockup 0:52 to 0:57. Versioned `title-v<N>` at 1080p24, with the music director's stems (score only; there is no effects stem, since 8.3 allows no Foley).
- **Placement:** the engine's `title_sequence` slot after the cold open, before the film's title card (`CONCEPT.md`, rules the engine needs).
- **Credits:** every T id used appears in the film's credits and Sources from `title-ledger.json`, with CC BY credit lines (T-13) verbatim.
