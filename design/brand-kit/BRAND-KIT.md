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
| Chapter card | dip to black (12 fr or more) first; number and title rise 0.6% of height on `arrive`; the centred rule (6% of width) grows from its middle on `drift` from +0.10 s; the dates on `settle` from +0.25 s | 10 fr (0.4 s) ease-in-quad fade, then a cut |
| Record-is-silent card | no movement: line 1 fades in over 18 fr (0.75 s, ease-out-sine); the Searched line follows 8 fr later | both fade over 18 fr, ease-in-sine; at least 4 s on screen |
| Title card | the title on `arrive` (rise 0.6% of height); `void document` on `settle` 0.4 s later | 16 fr (0.67 s) ease-in-quad; 5 s on screen |
| Credits | fade in over 1.0 s (ease-out-quad), then a constant roll at 5.2% of frame height per second (56 px/s at 1080p); no easing, a projector does not ease; headings in the data face, uppercase, safelight (credits are where things came from) | holds its last block through the final 6 voiceless seconds |
| Watermark | once, at the first imagery frame: corners close from 8% spread on `drift`, strokes fade with the progress, ember in the last tenth | 12-fr linear fade into and out of every CARD span; otherwise static |
| Dissolve (same class only) | 0.5 to 1.5 s, incoming weight on sine in-out; the label swaps on the first frame | |
| Dip to black | 0.5 to 1.0 s: fade out over 45% (ease-in-quad), black for 10% (never under 2 frames), fade in over 45% (ease-out-quad); at 0.5 s and 24 fps: 5.4 + 1.2 + 5.4 frames | |
| Ken Burns | the rostrum curve replaces `sketch.py`'s cosine ease: for an 8 s DRIFT, sine in-out never cruises and peaks at 1.57 times the mean speed; the rostrum ramps for 0.9 s, cruises at 1.13 times the mean for 6.2 s, and stops the same way, which is what a motion-control camera does | |

Type sizes on cards: chapter title Fraunces 300 at 5.6% of height (60 / 40 px) with the number in the data face at 80% opacity, baseline at 47% of height, rule 0.19% of height thick 1.6% below, dates in the data face at 2.6% (28 / 19 px) at 80% opacity; record-is-silent statement Fraunces 300 at 4.0% (43 / 29 px) on 1.35, at most 76% of width, Searched line Inter at 2.6%; film title Fraunces 300 at 7% (76 / 50 px) with the wordmark at 2.6% 2.2% of height beneath; credits Inter at 2.4% on 1.5 in a 70% column, headings in the data face at 1.85%.

**Reduced motion.** The film is a film and has no media query. On the site, every CSS mirror of these presets collapses to its end state under `prefers-reduced-motion` (`tokens.css` already does this); the burned-in motion is unaffected.

## 7. Colour, type and voice on film

- Colour on film: bone and near-white text, the theatre's black, safelight on the ARCHIVE bar and in the credits' headings, cold blue on the AI-GENERATED and DRAWN bars. No other hue touches a frame. Numerals and class words are always `--mark-text`, never a hue (A1).
- Type on film: Fraunces 300 for names, titles and the record-is-silent statement (300 italic for a place); Inter 400 for roles, sources and captions; JetBrains Mono for every numeral, the mark plate, flags, credits' headings and `void` in the wordmark. Nothing bold: hierarchy is size and air.
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
