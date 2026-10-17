# void document · As It Was: the title sequence

Studio designer, 2026-10-16. For the founder's storyboard approval (G2 style) before any build. Read with `STORYBOARD.md`, `ASSETS.md`, `BLENDER-PLAN.md` and the style frames in `frames/` (open `index.html`).

## The idea

**The archive machine: the world, made only of its records, turning.** One continuous camera travels through a clockwork built from the instruments people used to record their world, in the order they made them: a Sumerian clay labour register from Umma, set as the hub of the first wheel; the Turin papyrus map and the Catalan Atlas unfolding on their boards into painted ranges; an Inka khipu hanging from a turning drum above the Piri Reis coast; a common press stamping the first page of the Gutenberg Bible; Ino Tadataka's survey of Japan, its traverse line becoming a telegraph wire; Morse's own tape of 24 May 1844; the dials of Hollerith's 1890 census tabulator; the Lumière cinématographe running Promio's Grand Canal; an Underwood No. 5; and a Marshallese rebbelib held over the Admiralty chart of the same atolls. One lamp moves through it all, like a reader. Then the machine settles, the lamp comes to rest on this film's own record, and the model gives way to the record itself: a hard cut to the real scan. The safelight surfaces for the first time, in the mark. Dip to black. `void document · As It Was`.

**The hero is the cut.** Everything before it is ours, a studio model and labelled as one. The record after it is real. The series' whole claim is that cut, made once, in about a second, with no words.

## Why it is "as it was"

- **The ground is only what the maps knew.** All the terrain is period sheets. Relief rises only where a sheet prints it: the scribe's painted hills on the Turin papyrus, the Atlas's painted ranges, Ino's pictorial mountains. There is no modern elevation data, no modern coastline and no present-day map (A0). Where a map's makers knew nothing, the ground ends. The camera leaves the Catalan Atlas over its blank western margin and finds, a level below, the Piri Reis sheet of 1513, with a coast the Atlas never drew.
- **The machine holds nothing the time did not have.** Every module is dated by its latest material and runs forward in time. Nothing in the shared machine is later than the 1931 edition of Admiralty chart 983, so every current film's horizon is safe: *Not a Free Agent* (as_of 1950-04-08), *The Next Village* (1980-05-08) and the September 11 film (2001-09-11).
- **Objects shown as objects, and no people.** No event is depicted. No person, crowd, hand or shadow of a person is modelled. Painted figures on a sheet (the Atlas's rulers, Promio's gondoliers) are never framed as subjects and stay below legibility.
- **No invented marks.** Every legible sign on screen is a real scan: wedge, ink, knot, type, embossing, print. Nothing is typeset to look old. Where a texture is missing, the surface stays blank, never filled. The khipu's knots, the rebbelib's sticks and the census card follow their sources. The card stays blank, because a punched pattern would be a fabricated census return. The dials advance but never show a figure.
- **Never tell.** No narration and no word on screen except the title and the marks. Any view lives in the order: clay to film, the record lengthening; the edge of the Atlas; a stick chart and a printed chart of the same sea, one casting its shadow on the other.
- **Honest about itself.** The machine is studio-made, so it carries DRAWN's cold-blue square and the label `Drawn · from period records`. The record is ARCHIVE, so its amber dot and `Archive · 1947` (or the film's own year) surface at the cut. Safelight means "this is real" and is earned exactly there, and once more in the logomark's ember.
- **No AI pixels.** The founder allowed AI for textures and atmosphere, but the design needs none. Textures are real scans. Dust, haze and the lamp's beam are Blender volumetrics and procedural shaders. Section 5 matters here: one AI pixel makes the whole title AI-GENERATED. Its label would then stay up for all 48 seconds of picture in every episode, and every film's mark key would lose the line "No picture in this film is AI-generated." (Open question 1.)
- **A silent machine.** GRAMMAR 8.3 rules out Foley and synthesised ambience. No gear, platen or key is heard. The score carries the machine, developed from the house motif (8.1: one sustained instrument, a rising figure of four to six notes, no percussion). Its struck strings land on the machine's stamps.
- **The light is bone, never amber or blue.** It is one neutral lamp. Materials keep their printed colour, because 7.4 says drawn shots are in colour. No sepia, grain or "old film" look is applied, so the model can never pass for archive (5.3).

## How it scales across episodes

Game of Thrones changes its map for each episode. This sequence changes its record.

1. **A shared core, built once.** Beats 1 to 10 are modules joined at *station poses*: between modules the camera passes over a sheet looking straight down, at one height and one speed. Any module can be lifted out and its neighbours still join. They are rendered once and reused in every film.
2. **The film's own record (beat 11).** Each film names one record from its own ledger. The CG plate in the machine is textured with that scan and re-rendered, about 2 seconds of picture. The ARCHIVE hold after the cut is an ordinary engine still shot (HOLD, the whole sheet, pillarboxed on black). The label carries the record's own year. Proposals:

   | Film | as_of | Record | Ledger | Label |
   |---|---|---|---|---|
   | Not a Free Agent (Partition) | 1950-04-08 | The Gazette of India Extraordinary, Sunday 17 August 1947, page 1 | `partition/stills-ledger.json` S-130 | Archive · 1947 |
   | The Next Village (smallpox) | 1980-05-08 | World-wide smallpox endemic areas, 1976 (WHO map) | `smallpox/stills-ledger.json` S-16928 | Archive · 1976 |
   | September 11 | 2001-09-11 | GOES-8, 11 September 2001, 14:39 UTC | `sept11/stills-ledger.json` S11-NASA-GOES8-ERIN | Archive · 2001 |

3. **The horizon rule.** A module whose latest material is later than the film's `as_of` is dropped, and the rest close up at their station poses. A film set before 1931 loses the later modules. For early horizons, reserve modules can be sourced and added to the library (leads in `ASSETS.md`): Shang oracle bones, the Tabula Peutingeriana, the Kangnido, a Maya codex. If a horizon still leaves under 45 seconds, the sequence runs shorter rather than padding with decoration (open question 3).
4. **Rules the engine needs** (the engine builder's ticket; proposed amendment text):
   - A `title_sequence` slot after the cold open, holding three shots: DRAWN (the machine, a rendered clip), ARCHIVE (the record, a still from the film's ledger) and CARD (the lockup). Their transitions are lawful: a cut DRAWN to ARCHIVE, then a 0.75 s dip ARCHIVE to CARD.
   - DRAWN's definition widens from "maps and diagrams" to "maps, diagrams and models made by the studio from named sources". The label is `Drawn · from period records`, and the sources are listed in the credits from `title-ledger.json`.
   - The watermark stays on over the machine and the record, and goes off on the lockup (a CARD), as now. Because the title uses DRAWN, every film's mark key shows the Drawn row.
   - **A35:** the record shown in the title counts as a showing. If the film shows it again, that shot states a `repeat_reason` ("the title's record returns where the story reaches it"), or the film picks a record it does not otherwise show (open question 2).
5. **Length:** 57.0 s (1,368 frames at 24 fps) in every film: 48.0 s of machine, 4.0 s of record, 5.0 s of lockup.

## Open questions for G2

1. **AI pixels.** Zero AI pixels, with the title marked DRAWN, is recommended. Or should AI atmosphere be allowed? The cost would be an AI-GENERATED label on screen for the whole machine in every episode, and the loss of "No picture in this film is AI-generated." in every film's key.
2. **The records.** Confirm S-130, S-16928 and S11-NASA-GOES8-ERIN as the three films' final records, accepting that a second showing in the film needs a `repeat_reason` under A35. The GOES-8 frame shows the smoke plume from orbit. It is calm, but it shows the attack, so it may want a quieter record.
3. **Early horizons.** For a future film set before about 1500, should the sequence run shorter than 45 s, or should reserve modules be sourced to keep it at length?
