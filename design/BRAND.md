# void document: brand

void document sits beside void news and void history: same family, its own say. The grammar (three type voices, earned accents, motion tiers, copy voice) is Ink & Momentum's. The film rules are `films/GRAMMAR.md`. This file covers what void document decides for itself.

## Name and family

- The name is always lowercase: **void document**. Never "Void Document", never "Document" alone in product copy.
- Family device: the void family sets "void" as a technical word (void news writes it beside a command-line flag, with a hollow O). void document keeps that: "void" is set in the data face (JetBrains Mono), and "document" in the display face (Fraunces). The pairing reads as a terminal word meeting a film title.
- Every footer says: "void document is part of void, with void news and void history." Cross-links to the siblings come later, per the pivot decision.

## Logomark

**A void in the camera's window.** The family's hollow circle sits inside four crop corners (the camera's window on a photograph), with one safelight ember in the corner where a credit sits. 24 px grid, 1.6 px stroke, round caps, one filled ember.

<svg viewBox="0 0 24 24" width="96" height="96" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-label="void document logomark"><path d="M3.5 8V4.5H7M17 4.5h3.5V8M20.5 16v3.5H17M7 19.5H3.5V16"/><circle cx="12" cy="12" r="4.2"/><circle cx="18.6" cy="17.6" r="1.25" fill="var(--color-safelight)" stroke="none"/></svg>

The favicon is the mark alone. The wordmark is the mark plus "void document" as above, at 17 to 19 px in page bars.

## The house

A cinema house: a dark theatre where the film fills the screen and the chrome steps aside. Title cards are set like opening credits; the sources read like end credits. The site shows and does not explain. For a contested mass atrocity the voice is sober: say what the film shows and does not show, never sell it.

## Safelight (amber) and cold blue

- **Safelight amber** (`--doc-safelight`, the `ARCHIVE` mark hue) means one thing: **this is real, and here is where it came from.** It marks credits, source and ledger links, the ARCHIVE mark's rule, and a timecode only where it points to a source. It never marks a button, focus ring, progress bar, status, heading, hover, typed input, player clock, transcript time, the Lens film clock or playhead.
- **Cold blue** (`--doc-cold`, the `mark.generated` hue) marks AI-GENERATED and DRAWN, and nothing else. It sits 189 degrees from amber, and 31.7 L* below it, so the two never read alike, even in greyscale. On the site it appears as the mark rule and as `--color-generated-text` in Sources.
- Bone carries RECONSTRUCTED and CARD marks, and every control.
- One allowed exception: the ember in the logomark, because the mark states the rule.

## The in-picture mark (GRAMMAR 4)

The mark is burned into every second of the film at assembly. Rendering decisions:
- Plate: the mark scrim (black at 60%), corner radius 0.55% of frame height (6 px at 1080p), padding 0.6 em, top left at 4% of width and 5% of height.
- Text: JetBrains Mono, class word uppercase at weight 600, then the detail in sentence case at weight 500, years with `tabular-nums`, ligatures off. Size 3.1% of frame height (cap height 2.2%, 24 px at 1080p).
- Text colour is always `--mark-text` (near-white): coloured text cannot reach 4.5:1 on a 60% scrim over a bright frame (amber gets 2.69). The class hue rides as a 3 px rule on the plate's left edge.
- No glow, no pulse. A 4-frame fade only when the class changes.

## Texture: film grain

One texture: a fine monochrome grain in the dark **behind** content on the site. It never lies over a photograph or film, because the picture is evidence. The Lens has no grain.

## Film graphics: the brand kit wins

`design/brand-kit/BRAND-KIT.md` is binding for everything on film: the watermark (top right, 6% of height, 0.6 opacity, halo, off on every CARD), lower thirds (no box: a rule, Fraunces 300 name, Inter role and source, a feathered wash; the partisan flag `Account of <publisher or side>, <year>` sits above the rule, before the name), the chapter card, the record-is-silent card, the title card and the credits. Where this file and the kit differ on film graphics, the kit wins. The mocks render them with the kit's CSS (`design/mocks/house.css`, section r3).

## Motion presets

Site motion uses the film's four springs, from `motion.py` as CSS `linear()` in `tokens.css`: `--spring-stamp` (341 ms; a rule drawn, a button pressed), `--spring-settle` (450 ms; a line takes its place, the paused credit), `--spring-arrive` (565 ms; a title arrives), `--spring-drift` (934 ms; a chapter rule grows). Departures are fades (`--ease-in-quad`), never moves. The Ink & Momentum springs stay in `tokens.css` for the Lens only.

| Name | What it says | Spec |
|---|---|---|
| `house-lights` | the film is playing | chrome fades out over 520 ms `--ease-cinematic` after 2.5 s without pointer movement |
| `rack-to-source` | you stopped on a frame: here is where it came from | paused credit, top right below the watermark zone (from 13% of frame height): `settle` spring, rising 0.8% of height |
| `credit-roll` | the film is over | sources rise at a constant 42 px/s; pauses on hover or focus |
| `develop` | a new frame arrived (Lens) | 160 ms opacity 0.6 to 1 |
| `slate` | a new unit started (Lens) | the id chip flashes bone, then settles over 600 ms |

With `prefers-reduced-motion`, every preset renders its end state at once. The burned-in mark's 4-frame fade lives in the video and is unaffected.

## Type

| Voice | Face | Use |
|---|---|---|
| Display | Fraunces (300 titles, 300 italic place lines, 400 names) | title cards, credit names, readings quoted in Sources |
| Structure | Inter 400/500/600 | body, labels, controls, English captions, lower thirds |
| Data | JetBrains Mono 400/600, `tabular-nums`, ligatures off | every numeral, timecodes, ledger ids, the in-picture mark, "void" in the wordmark, command text |
| Subtitles | Noto Sans Devanagari (Hindi), Noto Nastaliq Urdu (Urdu, `dir="rtl"`, taller line) | subtitle tracks and the subtitle menu only |

All faces are self-hosted from `@fontsource` packages (`design/fonts.css`). The two subtitle faces still have to be added: `@fontsource/noto-sans-devanagari` and `@fontsource/noto-nastaliq-urdu`, both OFL. No font CDN.

## Player on phones (2026-10-11)

- **Full screen letterbox is true black.** In full screen only, the ground around the picture is `--color-fullscreen` (pure black, so the letterbox disappears into the glass); everywhere else, including the theatre's backdrop, the theatre stays `--doc-black` and `--color-letterbox`.
- **Icon-only controls at 520 px and below** (and in landscape full screen): Play, Subtitles, Marks, Chapters, Sound and Full screen show their icons without the word under them, each keeping its `aria-label` and a 44 px target. Marks stays icon-only too (CoS decision): its menu's first line explains the marks ("What the marks mean", then "The mark in the corner says what you see."), and the menu is reachable in full screen.

## The mark, calmer (2026-10-11, founder; GRAMMAR A31, BRAND-KIT 12)

The burned-in mark moved bottom right (the glyph 4% and 5% in, the watermark's insets mirrored), its label smaller and fainter (Inter 1.6% of height at 0.6), surfacing for about 2 s only when the class or the year changes. A key card, "What the marks mean", teaches the glyphs the film uses (and says so when none of its pictures is AI-generated) after the title and again before the attribution card. The kit's section 12 holds every number; the "in-picture mark" rules above are the G2 plate's and are superseded where they differ. The site player's overlay (A4) still draws the G2 plate top left and follows in its own ticket.
