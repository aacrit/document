# void document: brand kit

The channel's identity on film and on YouTube, and how it sits in the void family. `design/BRAND.md` stays the product brand (site, hues, house); this kit adds the wordmark and logomark rules, the channel watermark, the lower thirds and the on-film motion system. `films/GRAMMAR.md` is binding wherever the two touch (sections 4, 7 and 9). `motion.py` beside this file implements every number below, frame-exact, and `preview.html` shows it.

## 1. The family

void is the parent. Its products are "void" plus a product word, and the parent's mark is a hollow ring: the lens you look through, the void. void news fills the O of VOID with its Sigil (ring, level beam, foot); void history does the same in umber. void document keeps the ring and loses the beam: it measures provenance, not lean.

| | void news | void history | void document |
|---|---|---|---|
| Accent | terracotta `#B26F52` | umber `#5C4033` | safelight amber `--doc-safelight` |
| Accent means | the flagship's voice | the long view | "this is real, and here is where it came from" |
| Second hue | bias spectrum (data only) | bias spectrum | cold blue `--doc-cold`: AI-GENERATED and DRAWN only |
| Mark | Sigil-O: ring, beam, foot | Sigil-O | a void in the camera's window: ring in four crop corners, one ember |
| Wordmark | VOID NEWS, Playfair 700 | VOID HISTORY | `void document`, lowercase: `void` in JetBrains Mono, `document` in Fraunces 300 |
| Ground | walnut Evening Edition `#1C1A17` | walnut | the theatre `--doc-black`, darker: the film is the light |

**Shared, and not negotiable:** the hollow ring and what it means; the "void + word" naming with "void" set as a technical word; one accent per surface and an accent only where its meaning applies; Inter as the structural face and a mono face on every numeral; the voice rules (show, don't tell; arrive late, leave early; no em dashes); the footer line "void document is part of void, with void news and void history".

**Its own, and why:** lowercase, because a channel's name is a title card, not a masthead. Fraunces instead of Playfair, because Playfair's hairlines alias at 2 to 4% of frame height on video and flicker at 24 fps; Fraunces 300 holds its weight at those sizes. JetBrains Mono instead of Plex Mono and no Barlow Condensed, because the grammar is Ink & Momentum's three voices. Safelight amber instead of a fourth family accent, because it already carries one meaning across the whole product. No Sigil beam, ever: a document film does not measure lean.

**Beside its siblings:** when the three appear together (a family strip, a channel description, the footer), the marks sit on one baseline with their rings the same diameter. The document ring is 35% of its box and the Sigil ring is 60% of its box, so the document logomark box is 1.71 times the Sigil icon box. Match the rings, not the boxes. void document never redraws the Sigil and never borrows its beam sweep.

## 2. Wordmark and logomark

**Logomark: a void in the camera's window.** The ring at the centre of a 24-unit grid (centre 12,12, radius 4.2), four crop corners (3.5 to 20.5 on both axes, each arm 3.5 units), stroke 1.6 with round caps and joins, and one filled ember (18.6,17.6, radius 1.25) in the corner where a credit sits. Source: `logomark.svg`.

**Wordmark:** logomark, then `void` in JetBrains Mono 500 and `document` in Fraunces 300 at the same size on one baseline, gap 0.45 em, always lowercase. Source: `wordmark.svg`. The favicon is the logomark alone. In page bars the wordmark runs 17 to 19 px; on the title card the words run 2.6% of frame height beneath the film title.

**Clear space:** the ring's diameter on every side of the mark or the lockup (the family's rule). Nothing enters it: no type, no image edge, no other mark.

**Minimum sizes:** logomark 16 px; below 24 px the ember is omitted and the mark is strokes only. Wordmark 120 px wide. Watermark box never below 32 px (43 px at 720p is the smallest delivery).

**Treatments:** bone strokes and a safelight ember on dark (default). Ink strokes on bone when the house lights are up, with the ember darkened as `tokens.css` does for the light theme. One colour (no ember) for print and embossing. The burned-in watermark is the only treatment with a halo (section 3).

**Never:** fill the ring; move or tilt the corners except in the watermark's open settle; colour the strokes amber; add a shadow or gradient on the site; set the words in any other faces or in capitals; pair the mark with the Sigil's beam.

## 3. The channel watermark

**In the film.** The logomark, top right. It stays out of every other zone: the mark plate is top left, lower thirds bottom left, subtitles bottom centre, dates and counts bottom right, chapter cards centre.

| | % of frame | 1920 x 1080 | 1280 x 720 |
|---|---|---|---|
| Box (square) | 6% of height | 65 px | 43 px |
| Inset from right | 4% of width (mirrors the mark plate's left inset) | 77 px | 51 px |
| Inset from top | 5% of height (the mark plate's top inset) | 54 px | 36 px |
| Stroke | 1.6/24 of the box | 4.3 px | 2.9 px |
| Opacity | 0.6, the whole mark including the ember | | |
| Halo | the same strokes in `--doc-black` at 0.35 alpha, 2 px wider at 1080p (1.3 px at 720p), beneath the bone strokes | | |
| Reserved zone | top right, 12% of width by 12% of height: no player chrome, no text | | |

The halo is a contact edge so the mark holds on a white sky; it exists in the burned-in watermark only. Source: `watermark.svg`.

**Behaviour.** Always on over imagery: ARCHIVE, RECONSTRUCTED, DRAWN and AI-GENERATED shots, through dissolves and dips alike (the mark does not dip with the picture). Off on every CARD: the title card, chapter cards, record-is-silent cards, black under a reading, and the credits. Those frames already carry the VOID DOCUMENT mark plate, and a black frame holding a witness's words carries nothing else. It leaves and returns with a linear 12-frame fade (0.5 s) either side of each CARD span. At the film's first imagery frame it settles once: the four corners close from 8% outside their rest position on `drift` while the strokes fade in with the same progress, and the ember appears in the last tenth of the settle (23 frames at 24 fps). After that it is still.

**On YouTube.** `watermark-youtube.svg`, exported by `motion.py` as `watermark-youtube-150.png` (150 x 150, transparent, under 1 MB; PNGs are build outputs and gitignored). Bone strokes and the ember, no halo and no opacity, because YouTube draws the branding watermark at its own low opacity in the player's bottom right. Set it to show for the entire video. The two watermarks never share a corner: ours is burned top right, YouTube's is drawn bottom right.

## 4. Lower thirds

The look, after the BBC documentary school: no box. A short rule, a name in a light serif, the role beneath it in a quiet sans, the source beneath that, generous air, text set flush left at the same edge as the mark plate. Legibility comes from a wash, not a plate: a feathered dark gradient that fades to nothing before it reaches the middle of the frame, so the picture is never cut by a straight edge.

### Three formats

1. **Speaker or reader** (GRAMMAR 9, three lines): `<Name>` / `<role or place>, <year>` / `<source title>, <archive>  ·  read by a computer voice` (or `  ·  original recording`). The suffix after the dot sits at 70% opacity. Example: `Sir Stanley Reed` / `Member of Parliament, former editor of the Times of India, 1947` / `Clause 4 (The Punjab), HC Deb 14 July 1947  ·  read by a computer voice`.
2. **Place and date** (two lines): the place in Fraunces 300 italic, the date beneath in the data face. Example: `A refugee train near the new border, Punjab` / `September 1947`. Used for a shot that needs a where and a when; never over a lower third of a speaker.
3. **Partisan-source flag**: the flag is the first and most prominent line, above the rule, in Fraunces 300 italic at the same size as the name, so the account cannot read as plain testimony. The name steps down to the flag's size beneath the rule. The flag arrives with the rule, before the name: the viewer learns whose account this is before they learn who speaks. Exact form: `Account of <publisher or side>, <year>`. Example: `Account of the Government of West Punjab, 1948` / `Darshan Singh` / `Statement recorded by officials, 1947` / `Note on the Sikh Plan, Government of West Punjab, Lahore  ·  read by a computer voice`. The source must fit one line.

### Exact layout

Everything is a fraction of the frame, so 1080p and 720p are the same picture.

| Element | Face, weight | Size | Line | 1080p | 720p |
|---|---|---|---|---|---|
| Left edge | | 4% of width | | 77 px | 51 px |
| Block bottom (last line's box) | | 92% of height | | 994 px | 662 px |
| Max width | | 56% of width | | 1075 px | 717 px |
| Rule | bone at 85% | 7.5% of width long, 0.19% of height thick | | 144 x 2 px | 96 x 1 px |
| Flag (flagged form only) | Fraunces 300 italic, sentence case, no tracking; first line, above the rule | 3.6% of height | 1.1 | 39 px | 26 px |
| Name, flagged form | Fraunces 300, the flag's size | 3.6% of height | 1.1 | 39 px | 26 px |
| Name | Fraunces 300 (place: 300 italic) | 4.4% of height | 1.1 | 48 px | 32 px |
| Role, year | Inter 400; numerals JetBrains Mono at 94% of the size, tabular | 2.8% of height | 1.3 | 30 px | 20 px |
| Source | Inter 400; wraps to at most 2 lines | 2.3% of height | 1.3 | 25 px | 17 px |
| Gaps | plain: rule to name 0.7%, name to role 0.7%, role to source 0.5%. Flagged: flag to rule 0.5%, rule to name 0.6%, name to role 0.7%, role to source 0.4% | | | | |
| Text colour | `--mark-text` (near-white; the mark plate's text colour) | | | | |
| Wash | `--doc-black`, alpha 0.5 at the left edge, smoothstep to 0 at 62% of width; vertically a 4% of height smoothstep feather above the block, full to the frame's bottom | | | | |
| Block top | plain: 78.4% of height; flagged: 75.06% (one source line) | | | 847 / 811 px | 565 / 541 px |

GRAMMAR 4.1 keeps lower thirds below 75% of frame height and the mark above 15%: both hold, with a flag at the limit. Safe areas: 4% of width is inside action safe (3.5%) and 1% proud of graphics safe (5%); accepted because the film is delivered to screens that do not overscan, and because the mark plate is at 4% by GRAMMAR, and the two edges must align.

**Timing.** On screen for 4 to 6 seconds (GRAMMAR 9). In: the flag and the rule at frame 0 (the rule draws from its left anchor on `stamp`); the name at +4 frames, the role at +8, the source at +12 (each on `settle`, rising 0.8% of frame height while it fades in); everything has settled by frame 23 at 24 fps. Out: the last 12 frames (0.5 s), every element fading together on an ease-in, the rule shrinking back to its anchor on the same curve, the wash with them. Nothing leaves by moving.

### With subtitles

Subtitles are tracks (WebVTT: Hindi, Urdu, English captions), never burned in. Their layout, in the player and in the kit:

| | Value |
|---|---|
| Size | 3.9% of height (42 px at 1080p, 28 px at 720p); the player keeps a 14 px floor |
| Position alone | bottom centre, cue bottom at 93% of height, max width 84% of width |
| Scrim | per line, `--mark-scrim` (black at 60%), padding 0.1 em 0.45 em, radius 3 px |
| Line | 1.45; Nastaliq 1.9 |
| Hindi | Noto Sans Devanagari, 2 lines of 42 characters at most |
| Urdu | Noto Nastaliq Urdu, `dir="rtl"`, 2 lines of 38, numerals isolated with `<bdi>` so a year never reorders |
| Raised over a lower third | cue bottom = block top minus 1.2% of height. A 2-line cue's top then sits at 65.9% of height (62.6% with a flag). The VTT cue carries `line:62%` so YouTube's desktop player raises it too; on mobile YouTube ignores it, which is accepted. |

The lower third is itself subtitled as a bracketed line (GRAMMAR 10), so during its 4 to 6 seconds the raised cue reads the name while the lower third shows it. The mark zone (top left 30% by 20%) and the watermark zone (top right 12% by 12%) are never entered by a cue.

## 5. The mark plate on a cut

The plate is a stamp, not a graphic, and `design/BRAND.md` already fixes it: top left at 4% of width and 5% of height, `--mark-scrim`, radius 0.55% of height, padding 0.6 em, JetBrains Mono at 3.1% of height (CARD at 2.4%), class word at 600 tracked 0.06 em, detail at 500, `tabular-nums`, text `--mark-text`, class hue as a 3 px bar on the left edge (2 px at 720p).

On a cut, nothing moves. The label and the plate's width change on the cut frame. When the class changes (ARCHIVE to RECONSTRUCTED, anything to CARD), the outgoing and incoming plates crossfade over 4 frames, linear: 4 frames cannot carry a curve and GRAMMAR allows exactly that fade. Within a class the swap is hard, including on the first frame of a dissolve, where the incoming label replaces the outgoing at once. The first frame of the film carries its plate at full: no frame is unmarked.

## 6. The motion system

Three principles. Motion says one thing: something is arriving. Arrivals are springs and departures are fades, so the eye is never asked to follow something leaving. Overshoot is below 0.2% in every preset, which at these sizes is under a tenth of a pixel: the spring is felt in the exponential settle, never seen as a bounce.

### Springs

Hooke's law with viscous damping, solved in closed form, so every frame is a function of `t` and nothing drifts: with omega0 = sqrt(k/m) and zeta = c / (2 sqrt(k m)), displacement from rest starting at x = 1 is `x(t) = e^(-zeta omega0 t) (cos(wd t) + (zeta omega0 / wd) sin(wd t))`, `wd = omega0 sqrt(1 - zeta^2)`; progress is `1 - x(t)`. Settle is the first time after which |x| stays under 0.005. (`motion.py`: `Spring.x`, `Spring.progress`, `Spring.settle_time`; `Spring.css_linear` emits the CSS `linear()` mirror used in `preview.html`.)

| preset | k | c | m | zeta | overshoot | settle (s) | 24 fps | 25 fps | 30 fps | says |
|---|---|---|---|---|---|---|---|---|---|---|
| `stamp` | 420 | 40 | 1 | 0.976 | 0.00% | 0.341 | 9 | 9 | 11 | a rule is drawn; the watermark's corners close |
| `settle` | 170 | 24 | 1 | 0.920 | 0.06% | 0.450 | 11 | 12 | 14 | a line of a lower third or a card takes its place |
| `arrive` | 110 | 20 | 1.1 | 0.909 | 0.11% | 0.565 | 14 | 15 | 17 | a title, the largest thing on the frame, arrives |
| `drift` | 48 | 14 | 1.2 | 0.922 | 0.06% | 0.934 | 23 | 24 | 29 | the watermark settles at the open; the chapter rule grows |

### Eases (closed form)

| name | formula | used for |
|---|---|---|
| ease-in-quad | u^2 | every exit fade; the first half of a dip |
| ease-out-quad | 1 - (1 - u)^2 | the credits' fade in; the second half of a dip |
| ease-out-sine | sin(pi u / 2) | the record-is-silent card's fade in |
| ease-in-sine | 1 - cos(pi u / 2) | the record-is-silent card's fade out |
| sine in-out | 0.5 - 0.5 cos(pi u) | dissolves |
| rostrum | velocity ramps on a smoothstep over r = min(0.9 s, 0.3 dur), constant between; position `vmax r (u^3 - u^4/2)` on the ramps with `vmax = 1/(dur - r)` | Ken Burns moves |

### Choreography

| Element | In | Out |
|---|---|---|
| Lower third | flag and rule at 0 (`stamp`); name +4 fr, role +8, source +12 (`settle`, rise 0.8% of height); settled by frame 23 | last 12 fr, ease-in-quad, all together; rule shrinks to its anchor |
| Mark plate | hard swap on the cut frame; class change: 4-frame linear crossfade | with the cut |
| Provenance label (A42, section 12a) | grows leftward out of the glyph on `whisper` (a reveal, the opacity rising with it); holds 2.0 s | folds back into the glyph over 0.75 s on `let_go`; grows again 40 s later within a long shot |
| Chapter card | dip to black (12 fr or more) first; number and title rise 0.6% of height on `arrive`; the centred rule (6% of width) grows from its middle on `drift` from +0.10 s; the dates on `settle` from +0.25 s | 10 fr (0.4 s) ease-in-quad fade, then a cut |
| Record-is-silent card | no movement: line 1 fades in over 18 fr (0.75 s, ease-out-sine); the Searched line follows 8 fr later | both fade over 18 fr, ease-in-sine; at least 4 s on screen |
| Title card | the title on `arrive` (rise 0.6% of height); `void document` on `settle` 0.4 s later | 16 fr (0.67 s) ease-in-quad; 5 s on screen |
| Credits | fade in over 1.0 s (ease-out-quad), then a constant roll at 5.2% of frame height per second (56 px/s at 1080p); no easing, a projector does not ease; headings in the data face, uppercase, safelight (credits are where things came from) | holds its last block through the final 6 voiceless seconds |
| Watermark | once, at the first imagery frame: corners close from 8% spread on `drift`, strokes fade with the progress, ember in the last tenth | 12-fr linear fade into and out of every CARD span; otherwise static |
| Dissolve (same class only) | 0.5 to 1.5 s, incoming weight on sine in-out; the label swaps on the first frame | |
| Dip to black | 0.5 to 1.0 s: fade out over 45% (ease-in-quad), black for 10% (never under 2 frames), fade in over 45% (ease-out-quad); at 0.5 s and 24 fps: 5.4 + 1.2 + 5.4 frames | |
| Ken Burns | the rostrum curve replaces `sketch.py`'s cosine ease: for an 8 s DRIFT, sine in-out never cruises and peaks at 1.57 times the mean speed; the rostrum ramps for 0.9 s, cruises at 1.13 times the mean for 6.2 s, and stops the same way, which is what a motion-control camera does | |
| FILL (A34, section 14) | a picture narrower than 16:9 holds whole for 2.5 s, then grows on the rostrum curve over up to 6 s to the largest 16:9 window inside it, and holds the fill | |
| TOUR (A41, section 14a) | a still fills 16:9 on every frame; the camera moves between stops on the rostrum curve, and a stop held over 1.5 s creeps at 1.5% scale a second; for stills it supersedes the FILL row's whole opening | |

Type sizes on cards: chapter title Fraunces 300 at 5.6% of height (60 / 40 px) with the number in the data face at 80% opacity, baseline at 47% of height, rule 0.19% of height thick 1.6% below, dates in the data face at 2.6% (28 / 19 px) at 80% opacity; record-is-silent statement Fraunces 300 at 4.0% (43 / 29 px) on 1.35, at most 76% of width, Searched line Inter at 2.6%; film title Fraunces 300 at 7% (76 / 50 px) with the wordmark at 2.6% 2.2% of height beneath; credits Inter at 2.4% on 1.5 in a 70% column, headings in the data face at 1.85%.

**Reduced motion.** The film is a film and has no media query. On the site, every CSS mirror of these presets collapses to its end state under `prefers-reduced-motion` (`tokens.css` already does this); the burned-in motion is unaffected.

## 7. Colour, type and voice on film

- Colour on film: bone and near-white text, the theatre's black, safelight on the ARCHIVE bar and in the credits' headings, cold blue on the AI-GENERATED and DRAWN bars. No other hue touches a frame. Numerals and class words are always `--mark-text`, never a hue (A1).
- Type on film: Fraunces 300 for names, titles and the record-is-silent statement (300 italic for a place); Inter 400 for roles, sources and captions; JetBrains Mono for every numeral, the mark plate, flags, credits' headings and `void` in the wordmark. Nothing bold: hierarchy is size and air.
- Voice on film, first (GRAMMAR A0, the founding principle; founder, 2026-10-11): **show as was, not as is, and never tell.** Every word on screen and in the voice is as the time saw, knew and said it: period place names and terms (Dacca, Bombay, Ceylon), never modernised; nothing after the film's horizon (`as_of`): no "today", no "would later", no "decades later", no present-day map, border, figure or name. The narrator and every card, lower third and title give no opinion, verdict or editorial adjective ("tragic", "heroic", "brutal", "remarkable", "we believe", "must remember"); the film's view is in what it selects and how it orders it. Period voices may judge, in quotes. The film ends on one question asked from inside the time, then the brand end. [lint: hindsight-language, modern-names, never-tell, ending-question (`studio/engine/aswas.py`, lists in `studio/show-as-was.json`); site copy: `tests/show-as-was.test.ts`]
- Voice on film: a lower third states, it never characterises ("Governor of the Punjab, 1947", never "the man who lost the Punjab"). Chapter titles are at most five words and never a verdict. No exclamation marks, no em dashes, sentence case except the mono eyebrows. Dates and counts over footage are one line, bottom right, tabular, sourced.

## 8. Do and don't

Do: align the lower third's left edge with the mark plate; let the picture breathe under a wash instead of a box; put the flag before the name; keep the watermark off every card; cut by default and dissolve only within a class; let a reading end on a frame, not on a graphic.

Don't: put a hue in text on film; animate the mark plate; bounce anything; slide anything out; put a watermark over a black frame under a reading; wrap a name; set a lower third over a place-and-date card; use the Sigil or its sweep; letter-space Fraunces; put the watermark bottom right where YouTube draws its own.

## 9. Files

| File | What |
|---|---|
| `BRAND-KIT.md` | this document |
| `logomark.svg`, `wordmark.svg` | the mark and the lockup (explicit fills citing `tokens.css`) |
| `watermark.svg` | the in-film watermark with its halo, at 65 px (1080p) |
| `watermark-youtube.svg` | the YouTube branding watermark source |
| `watermark-youtube-150.png` | the 150 x 150 export (build output, gitignored; `python design/brand-kit/motion.py` writes it) |
| `motion.py` | springs, eases, layout and `lower_third_frame`, `mark_plate_frame`, `chapter_card_frame`, `silent_card_frame`, `title_card_frame`, `credits_frame`, `subtitle_frame`, `watermark`, `rostrum_move`; `--table` prints the presets |
| `demo/` | 29 PNG frames (every 5th of 6 s at 24 fps, 720p) from the demo (build output, gitignored) |
| `preview.html` | the kit in a browser, with CSS `linear()` mirrors of the springs |
| `_media/` | copies of five ledger stills for the preview (gitignored) |

## 10. Amendments this kit needs

1. **GRAMMAR 9:** a `lower_third` text element gains an optional `flag` line, rendered as the eyebrow of section 4, matching `^Account of .+, \d{4}$`. The three-line lint is unchanged.
2. **GRAMMAR 4.1:** "lower thirds and subtitles never rise above 75% of frame height" needs a second clause for a cue raised over a lower third: its top never rises above 62% of frame height. Add the watermark zone (top right, 12% by 12%) to the layout boxes the lint checks, and the rule that the watermark is off on CARD frames.
3. **GRAMMAR 7.2:** "eased with the sine ease in `studio/sketch.py`" becomes "on the rostrum curve in `design/brand-kit/motion.py`".
4. **spec.md, Film page:** the paused credit (player chrome, top right) starts below the watermark zone: its top edge at 13% of frame height or lower.
5. **sketch.py:** master at 1920 x 1080 and 24 fps as GRAMMAR 7.5 says (it renders 1280 x 720 at 30 today); import the moves, plates and cards from `motion.py` instead of its own `ease`.
6. **Subtitle faces:** add `@fontsource/noto-sans-devanagari` and `@fontsource/noto-nastaliq-urdu` (already a build ticket). Pillow on this machine lacks libraqm, so `motion.py` lays out Devanagari and Nastaliq without shaping; it is for layout checks only, and subtitles ship as tracks.

## 11. Subtle on-screen information (2026-10-10, founder revamp; GRAMMAR A16)

Appended; sections 3 to 6 above keep their G2 text and are read with this. Where they conflict, this section wins: the always-on mark plate (section 5, A1) is replaced by a label and a glyph, and the lower third and watermark are quieter. The measure is void news's restraint: information is there when you look for it and gone when you don't. `motion.py` implements every number below (`LABEL`, `GLYPH_SHAPE`, `LT`, `WM`, `WHISPER`, `let_go`).

### The provenance label and the class glyph

At each shot change a short label surfaces top left, holds about 3 s and is let go, leaving a small glyph in the class hue that stays for the rest of the shot. Every frame carries its provenance: the label, the glyph, or both. The glyph is the mark the mark-coverage lint reads.

| | Value | 1080p | 720p |
|---|---|---|---|
| Glyph position | its box's top-left at 4% of width, 5% of height (the old plate's corner) | 77, 54 px | 51, 36 px |
| Glyph size | 0.85% of height, never under 4 px | 9 px | 6 px |
| Glyph shape | ARCHIVE, RECONSTRUCTED and CARD a dot; DRAWN a square (inset 9% of its box); AI-GENERATED a diamond. Classes that share a hue (DRAWN and AI-GENERATED are both cold blue) differ in shape. Every shape is solid at its centre. | | |
| Glyph colour | the class hue at full opacity (amber, bone, cold blue, as section 5), drawn 4x and box-filtered | | |
| Glyph contact disc | a round disc beneath the glyph, black at 0.42 alpha, its diameter the glyph box plus 0.12% of height on each side (at least 1 px), antialiased at its edge; it is round under every shape, so it shows as a thin dark rim around the dot and the diamond, and the square's corners overhang it | 11 px across | 8 px across |
| Label words | class and year, sentence case, joined by ` · `: `Archive · 1947`; RECONSTRUCTED adds its alterations (`Reconstructed · 1946 · colour cast removed`); DRAWN its data source (`Drawn · from Natural Earth`). The archive's name stays in the credits and on the Sources page. | | |
| Label type | Inter 400 at 1.85% of height, numerals JetBrains Mono at 94%, `--mark-text` at 0.72 opacity (the G2 plate was mono 600 at 3.1%, opaque on a 60% scrim) | 20 px | 13 px |
| Label position | 0.55 em right of the glyph; the glyph sits at the middle of the x-height | | |
| Label ground | no box: a soft shadow, the words' own shape blurred by 0.11% of height (at least 1 px) in black at 0.42 alpha | | |
| In | on `whisper` (below): opacity follows the spring while the words drift 0.25 em toward their rest | 9 frames | |
| Hold | 3.0 s after it has surfaced | | |
| Out | `let_go`: a 0.75 s sine in-out fade, nothing moves; the glyph stays | | |
| Whole label | 4.11 s from the cut to gone | | |
| Repeated words | a cut into a shot whose label is word for word the outgoing one (two stills of one class and year) does not bring the label up again: the same words again at a cut are noise, and the glyph carries them | | |
| CARD | the glyph alone (bone dot), never a label: a card's own words say what it is | | |
| Class change | the glyph crossfades linearly over 4 frames (GRAMMAR 4.1); within a class the swap is hard | | |
| Dip to black | the hold of a dip is all black, glyph and label included (A11) | | |

### Lower thirds, quieter

Same grammar as section 4 (no box, a short rule, flush left with the glyph, the flag first), smaller, softer and brief: a lower third comes and goes.

| | G2 kit | A16 | 1080p | 720p |
|---|---|---|---|---|
| Name | Fraunces 300, 4.4% of height, opaque | 3.3%, 0.88 opacity | 36 px | 24 px |
| Role, year | Inter 400, 2.8% | 2.1%, 0.74 | 23 px | 15 px |
| Source | Inter 400, 2.3% | 1.8%, 0.62 (the suffix after the dot at 70% of that) | 19 px | 13 px |
| Flag (flagged form) | Fraunces 300 italic, 3.6% | 2.9%, 0.94: still the first and the largest line, above the rule, and the most opaque | 31 px | 21 px |
| Name under a flag | 3.6% | 2.7% | 29 px | 19 px |
| Rule | 7.5% of width, 0.19% of height, bone 0.85 | 5% of width, 0.14% of height, bone 0.55 | 96 x 2 px | 64 x 1 px |
| Gaps (plain) | rule 0.7, name 0.7, role 0.5% | 0.6, 0.5, 0.4% | | |
| Gaps (flagged) | flag 0.5, rule 0.6, role 0.4% | 0.4, 0.5, 0.35% | | |
| Wash | black 0.5 at the left edge to 0 at 62% of width | 0.36 to 0 at 52% | | |
| Block top | 78.4% plain, 75.06% flagged | 81.7% plain, 78.9% flagged | | |
| In | flag and rule at 0 (rule on `stamp`), lines at +4, +8, +12 frames on `settle`, rising 0.8% of height | the same order and stagger on `whisper`, rising 0.35% | | |
| Hold | the screenplay's span (4 to 6 s) | 4.0 s after the last line has surfaced, then it goes, whatever the screenplay's `end_s` (an earlier `end_s` ends it sooner) | | |
| Out | last 0.5 s, ease-in | `let_go`, 0.6 s sine in-out, all together | | |
| On screen at most | | 5.46 s | | |

### Watermark, quieter

The logomark top right as section 3, at 0.36 opacity (was 0.6), with its halo at 0.22 alpha (was 0.35). Everything else, including the settle and the card fades, is unchanged.

### New motion preset and ease

| preset | k | c | m | zeta | overshoot | settle (s) | 24 fps | 25 fps | 30 fps | says |
|---|---|---|---|---|---|---|---|---|---|---|
| `whisper` | 380 | 38 | 1 | 0.975 | 0.00% | 0.357 | 9 | 9 | 11 | a provenance label or a lower third's line surfaces, then is let go |

| name | formula | used for |
|---|---|---|
| let go | 1 - (0.5 - 0.5 cos(pi u)) over the last `dur` seconds | the label's departure (0.75 s), the lower third's (0.6 s): a quiet element thins out instead of dropping |

Do: let the glyph do the work once the label has gone; keep the flag the strongest line of a partisan lower third. Don't: put a box behind the label; animate the glyph; bring the same label back at a cut; let a lower third stay past its hold.

### 11a. Refined after the T1e review (2026-10-10, Chief of Staff; GRAMMAR A16 refined)

These values replace section 11's where they differ.

| | Value |
|---|---|
| Label at a cut | it surfaces at every cut, even when its words repeat the outgoing shot's (section 11's "repeated words" row no longer applies) |
| AI-GENERATED label | never fades: it surfaces on `whisper` and stays up for the whole shot, because at 4 to 9 px the diamond and the square read alike |
| DRAWN glyph | a square filling its whole box (no inset), so its top-left pixel is solid; no other shape's is |
| Shape check | see 11b |
| Lower third's bracketed cue | a burned subtitle cue for a lower third ends when the drawn lower third does |

### 11b. Refined after the T1e re-review (2026-10-10, Chief of Staff)

| | Value |
|---|---|
| AI-GENERATED label | full opacity from the cut frame (no `whisper` arrival, no drift) and up for the whole shot, through a dissolve too (a dissolve joins two shots of one class) |
| Shape check | mark-coverage reads the hue at the glyph's centre and the shape at two pixels: the glyph box's top-left pixel and the one to its right. Each must equal what the shot's own class glyph composes there over the same pixels of the frame before the mark was drawn. The square leaves its hue at both; the dot and the diamond leave the picture under the glyph's edge and its dark contact disc. A correct frame passes over any picture. The guarantee, tested at every engine resolution (1080p and 720p) for every bare value 0 to 255: between the square and the diamond (the classes that share the cold blue) some probe has a channel (blue, at the second probe) where no picture value brings the wrong shape's composite within 1 of the right one's, so a wrong shape fails over any picture, flat or not (T1f). |
| Drawing | the glyph and the label are drawn on small tiles (the label and its shadow on a crop around the words) and composited in place, never as full-frame layers: about 2 ms a frame at 1080p, down from 41 ms, with identical pixels |

### 11c. Corrected after the brand audit of film 2 (2026-10-11, E15; GRAMMAR A28)

Appended; section 6's choreography table keeps its G2 text and is read with this. These values replace it where they differ.

| | Value |
|---|---|
| Dip to black | the hold is 10% of the dip and never under 2 frames, centred on the cut. Section 6's example ("at 0.5 s and 24 fps: 5.4 + 1.2 + 5.4 frames") broke its own floor: at 0.5 s the hold is 2 frames (0.083 s) and each fade 0.208 s, so the cut frame and its two neighbours are black, 3 frames, where the G2 dip showed 1. At 0.75 s and 1.0 s the hold is 10% (0.075 s is under 2 frames, so 0.083 s; 0.1 s) and 3 frames are black, as before. `dip_hold_s`, `dip_black_frames` |
| Statement cards | every element of `text[]` is drawn: the statement in Fraunces 300 at 4.0%, each later element (the Searched line, a source, a filled shortfall sentence) in Inter at 2.6% on 1.4, 1.2% of height apart, wrapped at 76% of width with no line limit, the block centred in a safe band from 10% to 90% of height. A block taller than the band steps all its type down by 5% at a time to 75% (3.0% and 1.95%: 32 and 21 px at 1080p, 22 and 14 px at 720p); past that the card is refused, never cut. A card that always fitted is drawn exactly as before. `card_layout`, `SILENT` |
| Statement card timing | element `k` fades in `k` x 0.33 s after the first, all fade out together |
| Lower third source | wraps to at most 2 lines (1 under a flag) and is refused past that, never cut; no comma after a title ending in `?` or `!` |
| Lower third on screen | a speaker's 4 to 6 s (section 4); a place-and-date one fully visible at least 2.5 s, so on screen at least 3.79 s |
| Credits | a year once: none after a title that ends with it |
| Watermark source | `watermark.svg` carries A16's values (group opacity 0.36, halo film black at 0.22); a test rasterises it and `logomark.svg` and holds them to the engine's `watermark()` and `draw_logomark()` within antialiasing, and `motion.py` here is a pure re-export of the engine's |

Correction to 11c (2026-10-11, E15 review of 5a9ee29; append-only): in the dip row, "as before" applies to the 1.0 s dips only. A 0.75 s dip's hold was 0.075 s (1 black frame) and is now 0.083 s (3 black frames); only at 1.0 s are the hold (0.1 s) and its 3 black frames unchanged.

| | Value (E15 review) |
|---|---|
| One-line texts | a card's title, a chapter line and its dates, a lower third's name, role and flag, an overlay (56% of width), a burned subtitle line (84%), a credit line (the 70% column; a credit broken at 90 characters is broken again by its measured width where it is still wider), a credits heading and a provenance label (ending by 50% of width) each fit their measure with every glyph present, or the plan refuses. The engine never cuts text: no renderer drops a word, a line or a glyph |
| Missing glyphs | a character the face has no glyph for (FreeType would draw an empty box) is refused wherever text is drawn, maps and count cards included |
| Credits roll | the roll's constant speed is unchanged; the credits shot lasts until the last line has been fully on screen 2 s, or the render refuses |

## 12. The mark, calmer (2026-10-11, founder; R2, GRAMMAR A31)

Appended; sections 5 and 11 to 11c keep their text and are read with this. Where they conflict, this section wins. The founder: the label "takes too much attention ... shouldn't be jarring"; it moves down, comes only when it says something new, and a key teaches the colours once. `motion.py` implements every number below (`LABEL`, `LABEL_AI`, `LABEL_MIN_X`, `MARK_ZONE`, `MARK_GLYPH_ZONE`, `GLYPH_SHAPE`, `RING_STROKE`, `label_plan`, `KEY`, `KEY_WORD`, `mark_key_frame`).

### Position: bottom right

| | Value | 1080p | 720p |
|---|---|---|---|
| Glyph box | its right edge 4% of width in from the right, its bottom edge 5% of height up from the bottom: the watermark's insets (section 3) mirrored into the opposite corner | x 1834 to 1842, y 1017 to 1025 | x 1223 to 1228, y 678 to 683 |
| Glyph size, shape, colour, contact disc | unchanged (sections 11, 11a): 0.85% of height; except CARD's (below) | 9 px | 6 px |
| CARD glyph | a ring, an outline in bone, its stroke 25% of its diameter (at least 1 px), hollow at the centre where the contact disc shows; it was a dot, which read as RECONSTRUCTED's bone dot (CoS 2026-10-11). The two bones now differ by shape as the two blues do; mark-coverage reads the centre as a shape probe beside the corner pair | stroke 2.25 px | stroke 1.5 px |
| Label | set flush right against the glyph, 0.55 em left of it, the glyph at the middle of its x-height; it grows leftward and the glyph never moves | | |
| Label type | Inter 400 at 1.6% of height (was 1.85%), numerals JetBrains Mono at 94%, `--mark-text` at 0.6 opacity (was 0.72); the soft shadow as section 11 | 17 px | 12 px |
| AI-GENERATED label | keeps section 11's 1.85% at 0.72 (`LABEL_AI`): it is a truth label, up for the whole shot, and must stay readable at the smaller corner; its shadow is heavier than the other classes' (black at 0.78, blurred 0.16% of height, gain 2.8; theirs 0.42, 0.11%, 1.8) so the words hold on a bright, busy ground at 720p; it sits in the same zone | 20 px | 13 px |
| Label measure | starts right of 60% of width (the lower third's measure, 4% + 56%); a longer label is refused, never cut (E15). Was "ends by 50%" | | |
| Mark zone | x 60% to 96%, y 93% to 96.5% of the frame; the glyph's own zone x 95.0% to 96.6%, y 93.5% to 95.6% | | |

Why this corner and these numbers. Every other corner is taken: the watermark is top right, lower thirds are bottom left (their measure ends at 60% of width, their wash at 52%), subtitles are bottom centre with their scrim's bottom at 93% of height, and a date or count overlay (section 7) is bottom right with its box bottom at 92%. The mark sits under all of them: its highest pixel, the label's shadow included, is below 93% at 1080p and 720p, so it never meets a subtitle cue, an overlay or a lower third, and a long label stops at 60% of width. The overlay and the glyph share the 96% right edge, so a date over footage and the mark beneath it read as one column. The glyph is inside title safe (5%); the label's descenders and shadow reach 96.5% of height, inside action safe (3.5%), accepted for the reason section 4 gives for the 4% left edge (the film goes to screens that do not overscan). `studio/tests/test_r2_marks.py` holds every bound at 1080p and 720p.

The YouTube branding watermark (section 3, "On YouTube") is withdrawn: YouTube draws it bottom right, over the glyph. The burned watermark top right already carries the channel's mark. YouTube's own player bar covers the bottom of the picture only while the viewer hovers or pauses, which is accepted; on document.voidvision.org the player draws the mark from `sources.json` (A4). YouTube end screens use the layout with the elements in the left and centre (video and subscribe left, nothing in the bottom-right quarter), so the last frames keep the corner clear. A pillarboxed picture (a 4:3 clip or a portrait still) puts the glyph and most of the label on the black bar, not on the picture; that is accepted: the mark is in the same place on every frame, and on black it is at its calmest.

### Behaviour: only when it says something new

| | Value |
|---|---|
| When the label surfaces | at the film's first picture shot, and at a cut where the class or the year differs from the previous picture shot's (cards are not compared: a card carries the glyph alone). Never at a cut that repeats them; section 11a's "at every cut" no longer applies |
| A cut that repeats class and year | the label already up runs on and lets go on its own time; its words swap on the cut frame (within a class the swap is hard, section 5). A label that has gone does not come back |
| What counts as the year | an ARCHIVE or RECONSTRUCTED shot's item year; DRAWN and AI-GENERATED have none, so a new data source alone does not bring the label up (the glyph and the Sources page carry it) |
| In | `whisper`, as section 11, the words drifting 0.25 em from beside the glyph to their rest (section 11's drift, mirrored) |
| Hold | 2.0 s after it has surfaced (was 3.0) |
| Out | `let_go`, 0.75 s, as section 11; the glyph stays |
| Whole label | 3.11 s from the cut to gone |
| AI-GENERATED | unchanged (11a, 11b): full from the cut frame and up for the whole shot, whatever came before; counted once per change for the rate |
| Rate | at most one surfacing per 15 s of film, over the film (n at most the duration over 15 s, rounded up), and at most 4 in any 60 s; a guide, not a rule (GRAMMAR A39 refined): the `label-rate` lint counts them, reports them per minute and the busiest minute, and past either cap journals a warning and a reviewer item; it never refuses |
| Empty AI label | refused at plan time (`ai-label`) |

### 12a. The dot speaks (2026-10-17, founder; GRAMMAR A42)

The founder: "the dot (class glyph, bottom right) is the only source indicator. Its label grows out of the dot, lingers, then folds back into it. On a long clip it animates again after an interval." What now wins over section 12's In and Out rows and its "A label that has gone does not come back": the label is part of the dot. It grows leftward out of the glyph (a reveal anchored at the glyph, its opacity rising with it), holds, and folds back into the glyph, the mirror of the grow; the glyph never moves. Within one shot that keeps its class and year, the label grows again 40 s after it last did, but only when its whole grow, hold and fold ends at least 1 s before the shot's cut. When it first surfaces (section 12's Behaviour rows), the AI-GENERATED label (full and up for the whole shot, never folding), the CARD ring (no label), the glyph's crossfade on a class change, its size, position, shadow and opacity are unchanged. The site's player draws no tag of its own over the film (release/2026.10.17-2): the dot is the only source indicator in the picture. `motion.LABEL` holds the numbers; `motion.label_reveal` and `label_repeats` draw them.

| | Value |
|---|---|
| Grow | out of the glyph, leftward, on `whisper` (section 6): 0.357 s; the reveal's soft edge is 0.35 em; never wider than the words |
| Linger | 2.0 s (`LABEL.hold`) |
| Fold | back into the glyph over 0.75 s on `let_go` (`LABEL.exit`), the reveal and the opacity together |
| Whole label | 3.11 s from the start of the grow to the end of the fold |
| Repeat | 40 s after the last surfacing (`LABEL.repeat_s`), within one shot of one class and year, if the whole label ends 1 s (`LABEL.repeat_tail`) before the cut; counted by the `label-rate` guide (40 s keeps within one per 15 s and 4 in any 60 s) |

Do: let a long clip or a held still remind the viewer where it came from, once every 40 s. Don't: move the glyph; let the label slide in from elsewhere; bring the label up at a cut that repeats class and year; fold the AI-GENERATED label.

### The key card: "What the marks mean"

A card (`card: mark_key`, CARD, true black, `text: []`) that teaches the glyphs once. The engine draws it from the plan and the class table, never from typed words or colours: the glyph (`GLYPH_SHAPE`, `MARK_HUE`) and words (`KEY_WORD`) of each class the film's shots use, and only those (`key_classes`, CoS 2026-10-11: a class shown in the key could imply the film has it), in the order Archive, Reconstructed, Our own titles and cards (the CARD ring, shown whenever the film has a card, which it always does), Drawn, AI-generated, so each pair that shares a hue (the two bones, the two blues) sits side by side and differs by shape. The ring's words say whose the frame is, not what it shows, because a card's own words already say that. The plan's key classes are required: a key with none is refused, never filled with a default. A film with no AI-GENERATED shot gets one more line beneath the rows, `No picture in this film is AI-generated.` (`KEY_NO_AI`), derived from the plan; adding an AI-GENERATED shot removes the line and adds the class.

| | Value | 1080p | 720p |
|---|---|---|---|
| Heading | `What the marks mean`, Fraunces 300 at 4.0% of height (the statement card's size), bone, centred | 43 px | 29 px |
| Rows | the glyph at 1.7% of height, 0.6 em, then the word in Inter 400 at 2.6% (the statement card's second size) in `--mark-text`; a column centred on the frame, rows 5.2% of height apart, the first 4.8% under the heading | 18 / 28 px | 12 / 19 px |
| No-AI line | Inter 400 at 2.6% in `--mark-text` at 0.8 (a statement card's later lines), centred, 1.4 row pitches under the last row; it arrives on `whisper` one stagger after the last row | 28 px | 19 px |
| Block | centred vertically, inside the statement card's safe band (10% to 90%) and measure (76%); every glyph present or the card is refused (E15) | | |
| In | the heading on `settle`, rising 0.6% of height; from +0.25 s each row on `whisper`, 4 frames apart, rising 0.35% | | |
| Out | everything let go together over 0.75 s; nothing moves | | |
| On screen | at least 4 s; 5 s recommended | | |
| Where | (1) after the title card, before the next picture shot; (2) in the end sequence, after the last picture shot and before the attribution card, found by its kind: the first statement card of the credits part, else its credits roll. The `mark-key` lint refuses a final render of an event film without either; a draft, a check render or a short piece gets a warning | | |
| Mark and watermark | the bone CARD ring bottom right, as on every card; no watermark (a CARD) | | |

Do: let the key teach the colours so the label can stay down; keep the overlay and the glyph on one right edge. Don't: draw a card's mark as a dot; bring a label up at a cut that repeats class and year; type a key's words or colours into a screenplay; let a label run past 60% of width; set YouTube's branding watermark.

## 13. Marks over archive maps (2026-10-11, R5b; GRAMMAR A32)

A period map sheet is shown as it was printed, and what the film points to is drawn over it, quietly. `studio/engine/overlays.py` implements every number here; `studio/engine/georef.py` holds the georeferencing.

**One drawing language.** Every mark is drawn as the provenance label is drawn: `--mark-text` over a soft black contact band. That holds on a paper sheet (most period maps are cream paper) and on a dark print alike. No saturated colour (the class hues are the glyph's), no arrows, no flashing, and no fill that hides the paper.

| Mark | Look (% of frame height; 1080p) | Enter | Exit |
|---|---|---|---|
| Line drawn on (a boundary where the cited record runs) | `--mark-text` at 0.55 (0.40 to 0.60), 0.19% wide (2 px), round caps, over a black band at 0.30 whose half-width is the mark's claimed precision at the shot's closest framing, never under 0.30% (3.2 px) and never over 1.2%; the sheet's printed line stays visible under it | along its length on `trace`; the draw-on is clamped at its end, so the spring's 0.31% overshoot never draws past the cited end | `let_go`, 0.6 s |
| Halo (a named place) | a ring around the place, never a disc over it: radius 2.4% (26 px; clear of a 1:250,000 sheet's town symbol at the 1.3 push, which the R5b brand audit found the first 1.6% ring touching), the line's 0.19% stroke in `--mark-text` at 0.50 (0.30 to 0.55) over a 0.30% black band at 0.30; the place's own symbol and name stay untouched | opacity on `whisper` (or `settle`), the ring closing from 1.06 to 1.0 of its radius on `settle` | `let_go`, 0.6 s |
| Outline (a boundary as the sheet prints it) | `--mark-text` at 0.40 (0.30 to 0.50), 0.14% wide, over a band at 0.24; an optional black wash inside, at most 0.10 | opacity on `settle` (or `whisper`); no travel | `let_go`, 0.6 s |
| Camera, `FIND` | the whole sheet first (A7), then on the rostrum curve through `via` extents to the `to` extent, all in longitude and latitude; at most 1.3 of the largest 16:9 window (7.2) | | |
| Stagger | marks entering together come in reading order (the record's order), `order` 0, 1, 2 and on, `LT["stagger"]` (4 frames) apart | | |
| Calm tier | a shot's `motion: calm`: every mark arrives by opacity on `settle`, with no draw-on and no scale | | |

**`trace`** (`motion.TRACE`, k 14, c 7.5, m 1.3): zeta 0.88, settles in 1.56 s (38 frames at 24 fps), overshoot 0.31%. It is the one slow arrival, for a line the eye should follow across the frame; `drift` (0.93 s) is too quick for that and `rostrum` is a camera curve. The R5 scout's note gave 2.6 s for these constants; measured, it is 1.56 s.

**Why a ring, not a glow.** The scout's halo (a bone disc at 0.18, blurred) moves a paper sheet's pixels by under 2% (bone over cream paper), so on the R5b proof frames it could not be seen. A ring in the label's language reads on paper and on a dark print, and leaves the place's own symbol and printed name untouched.

**The band is the truth.** A line is never drawn thinner than it is known. Its band is as wide as its claimed precision (the georef's worst residual, the sheet's own drawing, the tracing and the source's precision) at the closest zoom, so a coarser source draws a softer, wider line, and a line too coarse for the zoom is not drawn.

Do: draw a line only where the cited record runs, over the sheet's own printed line; ring places in the order the record names them; keep the sheet's printed names as they are. Don't: draw today's border on a period sheet; fill a district; draw a mark on a sheet without a georef; move a mark on anything but the house springs.

## 14. FILL: the whole record, then the screen (2026-10-11, R12; GRAMMAR A34)

The founder, on The Next Village pilot: "show the original, then slowly zoom in to what matters, but outward, meaning it should fill the screen, not zoom into the same 1:1." A picture narrower than 16:9 (4:3 footage, a square or portrait photograph) first shows all of itself, then grows to fill the frame on a crop inside its own pixels. `motion.FILL` holds the numbers; `render.fill_camera` draws it for a still and a clip alike.

| Beat | What the viewer sees | Numbers |
|---|---|---|
| Open | the whole original, pillarboxed on black (A7): the record as it is | 2.5 s (`open_s`); a shot under 5.5 s opens for 40% of itself |
| Move | the camera grows the picture until it fills 16:9, about its focus | the rostrum curve (section 6: velocity ramps on a smoothstep for 0.9 s, cruises, ramps down) over up to 6 s (`move_s`); at least 3 s where the shot allows |
| Hold | the fill, still, for the rest of the shot | the largest 16:9 window inside the picture (7.2's z = 1) |

**Focus.** A shot may say where the fill ends, `focus: [x, y]` in the picture (0 to 1); the centre otherwise. The focus must end inside the marks' insets and above the lower thirds (75% of the height), or the engine warns and a reviewer looks.

**Softness.** The fill never magnifies the source past 1.6 output pixels per source pixel (`settings.fill_max_upscale`, at most 3.0): a 1440x1080 reel fills 1080p at 1.33x; a square scan of 1000 px stops short at 1.6x, its full width still on screen; a 640x480 reel, already 2.25x in its plain fit, stays whole.

**Why the rostrum curve, not a spring.** A spring is an arrival of a graphic (section 6); a FILL is a camera, and the house camera is the rostrum: one even speed, eased in and out, the way a motion-control stand moves. A spring's exponential settle would read as the picture landing, which it does not do.

Do: let every 4:3 or square archive picture over 6 s open whole and fill; name the focus where the subject sits off-centre. Don't: fill a clip whose source burns its speakers' names into the frame (the crop could cut them off; the engine refuses it); fill a document that must be read whole (state `preset: HOLD`); push past the fill (DETAIL is the move for a region).

### 14a. TOUR: the full screen, toured (2026-10-17, founder; GRAMMAR A41)

The founder: "take the user through the artifact as needed, but use the full resolution of the screen. Same with even the paintings/other things that need full visibility." What now wins over section 14 for a still (a clip keeps section 14 as written): the still fills 16:9 from its first frame to its last, and the camera tours it. The open beat above (the whole original, pillarboxed) is dropped for stills; a still is held whole only under a stated `fill_exception`, where filling would pass the softness cap. `motion.TOUR` holds the numbers; `studio/engine/tour.py` draws it.

| Beat | What the viewer sees | Numbers |
|---|---|---|
| Stop | a framing of the picture: its centre (x, y, 0 to 1 in the picture) and zoom z, never under the fill (z = 1) | a stop is reached at its time `t`, or on the narration word it is anchored to (`at`) |
| Move | the camera travels to the next stop: pan, tilt, push and pull fall out of the stops | the rostrum curve (section 6), zoom geometric; guides: a third of the frame a second across, 15% scale a second (warnings) |
| Creep | a stop held over 1.5 s keeps moving, so no frame is frozen | 1.5% scale a second; a slow pull at the cap; a 1% drift where scale cannot change |
| Default | a still with no path and no preset opens at the fill on one end and passes to the other | a portrait or 4:3 picture tilts top to bottom; a wide map pans left to right |

**The presets are paths.** HOLD, PUSH, PULL, DRIFT, TILT and DETAIL keep 7.2's framings, now measured from the fill; FILL is the fill about its focus. A preset that never shows the whole picture becomes a covering pass of it (a FILL then settles on its focus, a DETAIL on its region), unless the ledger names the picture's regions; then, and for a written path, a part left unseen is a reviewer item.

**Softness.** Founder ruling, 2026-10-17: "fill the frame, soft is acceptable up to 3x." A still may be magnified up to 3.0 output pixels per source pixel on the 1080p master (a film may state a lower `fill_max_upscale`; a clip's FILL keeps section 14's 1.6), judged at the deepest framing, creep included. A preset stops at it; a written stop past it is refused. A still that would need more states `fill_exception`: whole on its first frame, then a gentle push inside its own pillarboxed shape (1.5% a second, at most 1.06), never frozen.

Do: write regions of interest once per image (`roi`) and let `tour` visit each as the narration names it; keep moves continuing across a cut, or land the cut on a stop. Don't: pillarbox a still because it is a document or a painting (tour it); push a face past z 1.3; state `fill_exception` on a picture that can fill.

## 15. The series titles: `void document · As It Was` (2026-10-17; GRAMMAR A40)

The founder: "a cinematic ... intro ... after the hook of each video like it's a documentary episode." The series titles are the archive machine (`design/title-sequence/`: 12 beats, 57.0 s, G2 approved 2026-10-16), rendered once per film with that film's own record, and played by the engine as they are.

| | Value |
|---|---|
| Place | after the cold open's last shot (the hook), before the film's title card and Part 1; cut in (the master opens from black), cut or dip out |
| Picture | the master, 1920x1080 at 24 fps, lossless; no grade, no camera, no re-drawing; scaled only for a 720p delivery |
| Marks | the master's own: DRAWN's cold-blue square and `Drawn · from period records` over the machine; at the cut to the record its class and year (`Archive · 1947`), the first safelight of the film; CARD's ring on the lockup. The engine draws nothing over a master that carries them, and reads the glyph on every frame against the master's declared timeline. One glyph, never two |
| Watermark | the master's own over the machine and the record, off on the lockup (a CARD), as section 3; the film's watermark resumes after |
| Lockup | `void document · As It Was`: `void` in JetBrains Mono 500, `document` in Fraunces 300, a middle dot, `As It Was` in Fraunces 300 italic, centred at 5.6% of the height with the logomark (its corners close on `drift`, the ember in the last tenth); the second and last safelight of the sequence |
| Motion | the house vocabulary only (sections 6, 11, 13 and 14): the camera is `rostrum`; arrivals `arrive` and `settle`; contacts `stamp`; travels `trace`; once engaged a wheel turns at constant speed |
| Sound | the main-title theme (`role: main_title`), developed from the house motif, from the first frame; nothing else under it. Until it exists: the house motif or silence, a reviewer item |
| AI | none: the master's provenance states `ai: false` for every input, so the film's mark key keeps "No picture in this film is AI-generated." One AI pixel would make the whole sequence AI-GENERATED, labelled for all its seconds in every film |

Do: keep the record the film's own (an item of its ledgers, held whole); state in the master's ledger item what it already carries. Don't: draw a second mark, label or watermark over a burned master; let narration, a lower third or a subtitle run over it; dissolve into or out of it; let the master's own dip show anything on its black hold.
