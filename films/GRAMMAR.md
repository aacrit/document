# void document: Film Grammar

The rulebook every void document screenplay is written from. It carries principles, never content. Each rule is written so a lint or a reviewer can say pass or fail. "Lint" means `studio/lint.py` run on `screenplay.json` plus the ledger; "reviewer" means a human or the Gatehouse reviewer reading the cut. The Partition of India pilot is the first film written from it. Binding decisions: `docs/DECISIONS.md`, entries "Pivot to void document" and "G1 round 2 approved".

## 1. What a void document film is

A void document film tells one event of history with the record itself: every real moving image the public domain holds, public-domain photographs given motion, first-person words read word for word, and narration, sound and music that strengthen the record without replacing it. Where the record runs out, the film says so, and generated context (never people) fills only what context can honestly fill. Every second of the picture carries an in-picture mark that says what it is. Many named people speak, from every side of the event, and none of them is handed the last word. The film is a public good: free, sourced to the shot, and open to correction.

Non-negotiables. Each names its check.

1. Truth. No claim without a source id; no estimate shown as a count; no source quoted beyond what its text says. [lint: every numeral in narration carries `source`; reviewer: spot-check 10 lines against extracts]
2. Licences. Every asset, text and recording is public domain, CC0 or CC BY (1.0 to 4.0). The allowlist lives in `studio/licences.json`; adding to it needs a `docs/DECISIONS.md` entry. A ledger entry with `rights: null` or `licence: unclear` cannot be cited. [lint]
3. Marks on every second. Every frame from first to last, credits included, carries exactly one mark class. [lint on the rendered mark track; verifier samples 1 frame per second of the output and finds the mark in every sample]
4. No generated people, faces, crowds, bodies, hands, silhouettes or violence. [lint: every generated shot carries `asserts.no_people: true` and a forbidden-term scan of the prompt; reviewer: watches every generated shot at full size]
5. No recreation of a specific recorded event. A generated shot may show a kind of place or weather, never "the Wagah crossing on 15 August 1947". [lint: generated prompts contain no date, no named person and no event name from `events/*.yaml`; reviewer]
6. No footage or photograph of bodies, killing, wounds or corpses. [ledger field `shows_bodies: false` required on every cited asset; reviewer]
7. Many named accounts, none given the last word. [lint: section 6 balance check; the final spoken line of the film is not testimony]
8. Violence is told through testimony, aftermath and silence. [reviewer: every violent passage is carried by a read account, a document, an aftermath image or a silent frame, never by music swell or narrated adjectives]

## 2. Building the story from the record

The method, in order. A screenplay that skipped a step fails review.

1. The ledger comes first. Before a word of story, the footage and stills ledger (`dossier.json`) lists every cleared moving image and still with: id, archive, item URL, licence and its basis, date, duration or pixel size, `seen` (what is in the frame, in plain words), `people: true|false`, `shows_bodies: false`, `themes[]`. The research ledger (void-history's `ledger.yaml` or its equivalent) lists every text with the same rights fields. [lint: every field present]
2. The story is fitted to what exists. Write the theme list of the event, then mark each theme by what the ledger holds: `video`, `stills`, `text only`, `nothing`. The film's chapters are chosen from the themes with `video` or `stills` first; a theme with `text only` is told through readings and documents; a theme with `nothing` gets a record-is-silent statement (rule 5 below) or is cut. [reviewer: the theme table is attached to the screenplay as `coverage.md`]
3. Choosing the chapter spine. A chapter is a turn in the event that the record can carry, not a topic. Pick 4 to 6 chapters such that: each has at least one anchor shot of real moving image or a cleared still sequence; each contains at least one named account; together they cover the before, the decision, the day, the aftermath and the long tail; and the order is chronological unless a dated reason is given in `why`. [reviewer]
4. Weighting scarce real video. Real moving image of the event is the rarest thing the film owns. Rules: a clip's seconds are spent at a chapter's turning point, never as wallpaper under exposition; each clip appears at most once, except one clip the screenplay names as the visual refrain, which may return up to 3 times; at least half of all archival-video seconds play with no narration over them; no real video is used under a line that describes something other than the frame. [lint: clip reuse count; narration-over-video ratio. Reviewer: the rest]
5. When a moment has no image at all. The film does not invent one. The order of preference, and the rule for choosing:
   - If a cleared first-person account or primary document exists for the moment: a black frame with the reading, marked CARD, with the speaker's lower third. Black because it is the only frame that cannot lie.
   - If only a place or a route is known: a drawn map, marked DRAWN, with its data source named, and the reading or narration over it.
   - If the moment is known but no cleared words exist: a title stating the record is silent, in the exact form of section 9, for at least 4 seconds, with ambience or silence.
   - If nothing is known that the film can source: the moment is cut.
   A generated landscape is never the answer to a missing moment; it is context for a moment that already has words.
6. Shorten before padding. If the ledger carries less than the target runtime, the film gets shorter. A screenplay with more than 15% of runtime on generated shots fails. A film may ship at 15 minutes with every second earned. [lint: generated seconds / total seconds ≤ 0.15]

## 3. Structure for a 20 to 25 minute event film

Runtime 1200 to 1500 seconds. The parts and their typical durations:

| Part | Seconds | Rule |
|---|---|---|
| Cold open | 40 to 75 | Opens on one real image and its own sound, before any narration. No music until the house motif. The first spoken words are a date and a place. |
| House motif and title | 15 to 25 | The house motif plays once, whole, under the title card and the first chapter card. The motif opens and closes every film and plays nowhere else. |
| Chapters (4 to 6) | 150 to 240 each | Each opens with a chapter card (section 9), holds at least one anchor shot and one named account, and ends on a frame, not a line. |
| Close on the present | 90 to 180 | Returns to the place as it is now: CC0 or CC BY contemporary images, present-day public facts, the border today, the survivors' words. The last account is not from the group that spoke last in the previous chapter. |
| House motif and credits | 60 to 120 | The motif returns under the end credits. Credits list every shot's source (section 9). |

Checks: part durations within range [lint]; motif appears exactly twice [lint on music cues]; the film ends on a frame with no voice for at least its last 6 seconds [lint].

## 4. Provenance marks

Every frame carries exactly one mark. The mark is burned into the picture at assembly and is also written as a mark track in `sources.json`, so the player and the lint can check it.

Classes, hues, text:

| Class | Hue token | Label text | When |
|---|---|---|---|
| ARCHIVE | `mark.archive` (amber, the product accent) | `ARCHIVE  <archive> <year>` | Real moving image or still, unaltered beyond what section 4.2 allows |
| RECONSTRUCTED | `mark.reconstructed` (bone, neutral) | `RECONSTRUCTED  <archive> <year>  <alteration>` | Archival material materially altered |
| AI-GENERATED | `mark.generated` (cold blue) | `AI-GENERATED  context` | Any pixel produced by a generative model |
| DRAWN | `mark.generated` (cold blue) | `DRAWN  from <data source>` | Maps and diagrams made by the studio from named data |
| CARD | `mark.reconstructed` (bone, small) | `VOID DOCUMENT` | A plain field with text only, no imagery of any kind |

Hue rules: `mark.generated` is never amber and its hue angle differs from `mark.archive` by at least 120 degrees; the two are distinguishable in greyscale by a luminance difference of at least 30%. Values live in the design token file, never in the screenplay. [lint reads tokens]

4.1 Placement and size
- The mark sits in the top-left corner, inset 4% of frame width and 5% of frame height, on a scrim plate (black at 60% opacity, 6 px corner radius at 1080p) that extends 0.6 em around the text.
- Text: the product's mono or grotesk UI face, uppercase class word, then the detail in sentence case, `tabular-nums` on the year. Cap height is at least 2.2% of frame height (24 px at 1080p, 16 px at 720p). Contrast of text on the scrim is at least 4.5:1.
- The mark is never covered by subtitles (bottom centre), lower thirds (bottom left) or chapter cards (centre). Lower thirds and subtitles never rise above 75% of frame height; the mark never descends below 15%. [lint on layout boxes]
- The mark updates on the first frame of every new shot, so a new archive name and year appear exactly at the cut. [lint]
- The mark is never animated beyond a 4-frame fade when the class changes. It never scrolls, pulses or glows.

4.2 What counts as material alteration
- Not material (stays ARCHIVE): crop within the frame, Ken Burns move on a still, pillarboxing, trim, hold on a frame for up to 2 seconds, dust and scratch removal that changes under 2% of pixels per frame, flat level or gamma adjustment, audio cleaning, resampling to the master frame size without resizing content above 1.3x.
- Material (becomes RECONSTRUCTED, alteration named): colourise, upscale above 1.3x, stabilise, frame-interpolate, re-time (any speed change, including 25 to 24 fps slowdowns), inpaint, remove or add any object, image-to-video motion on a photograph, denoise above the 2% threshold, synthesise missing audio for the clip, tint for mood. The alteration label is one of: `colourised`, `upscaled`, `stabilised`, `interpolated`, `re-timed`, `inpainted`, `motion added`, `tinted`, `audio synthesised`; several are joined with commas. [lint: `alterations[]` non-empty on every RECONSTRUCTED shot, and vocabulary closed]
- Image-to-video motion on a photograph is allowed only when the dossier says `people: false`; a photograph with people gets Ken Burns moves only. [lint]

4.3 Title cards, maps and text over footage
- A title or chapter card on a plain field is CARD. A card over imagery keeps the imagery's mark; the text is just text.
- A drawn map is DRAWN, and the data source (a named census table, a gazetteer, a boundary schedule paragraph) is in the label. A map built from a generative model is AI-GENERATED, not DRAWN.
- Text over archival footage (a date, a count, a document line) does not change the mark. A document shown as an illustration (a letter, a page) that the studio typeset is DRAWN with the source id; a scan of the real document is ARCHIVE.
- The record-is-silent statement (section 9) is a CARD.

4.4 Behaviour at transitions
- A dissolve is allowed only between two shots of the same mark class. Between classes the transition is a cut or a dip to black of at least 12 frames, and the mark changes on the cut frame. [lint: transition type versus class pair]
- During a dissolve within a class whose detail changes (archive A into archive B), the incoming label replaces the outgoing on the first frame of the dissolve, so the label is never ahead of or behind the picture by more than the dissolve length.
- Credits and chapter cards over black are CARD; credits over imagery are not allowed.

## 5. Generated context

5.1 What may be generated
Maps and terrain, land, rivers, canals, fields, roads without travellers, railway track without trains, weather, sky, light, time of day, water, dust, smoke from no named fire, seasons, objects shown as objects (a lamp, a trunk, a ledger, a railway ticket, a well, a plough), documents typeset as illustrations, and text. Everything is context for words that are already in the film.

5.2 Forbidden subjects
People, faces, crowds, hands, silhouettes, shadows of people, bodies, blood, wounds, weapons, fire set to buildings, wrecked vehicles, trains with figures, animals being harmed, flags at a named ceremony, any named building at a named date, any named person, any dated event. The prompt scan rejects any of these terms and their common synonyms from `studio/forbidden-terms.json`; the reviewer watches every generated shot at full size. [lint plus reviewer]

5.3 Prompt rules
- Every generated shot carries its full prompt, negative prompt, model name, seed and the assertion `asserts.no_people: true`. [lint]
- The prompt names a kind of place, not a place at a date: "a canal through flat wheat country, monsoon sky" passes; "the Upper Bari Doab Canal at Madhopur, August 1947" fails. A region name alone ("Punjab plain") is allowed; a town plus a date is not. [lint: no 4-digit year, no month name with a year, no name from `events/*.yaml` key figures]
- Never imitate the archive. The prompt never asks for film grain, scratches, sepia, black and white, newsreel, 16 mm, 35 mm, vintage, period photograph, daguerreotype, hand tinted, or any decade. Generated shots are rendered in clean colour, present-day light, so they can never pass as archive. [lint: forbidden style terms]
- No generated shot is lit or framed to match the adjacent archival shot's angle; a generated shot that reads as a continuation of an archival shot fails review. [reviewer]

5.4 Durations and placement
- A generated shot lasts 3 to 8 seconds. Two generated shots never sit next to each other. A generated shot never opens or closes a chapter, the cold open or the close. [lint]
- Generated seconds are at most 15% of runtime (section 2, rule 6) and at most 20% of any one chapter. [lint]
- A generated shot sits beside archival shots by a cut or a dip to black, never a dissolve (section 4.4).

## 6. Voices

6.1 The narrator
- One voice, a computer voice credited as such, the same across all films.
- May say: dates, places, distances, counts with their source, who is about to speak and from where, what the record holds and what it does not, the words of a document's title. Every number it speaks carries a source id in the line. [lint]
- May not say: what the frame shows; what anyone felt or must have thought; any verdict on any side; adjectives of scale or feeling. Banned list in `studio/narration-banned.json`, starting with: tragic, horrific, unimaginable, heartbreaking, brutal, savage, must have, surely, of course, infamous, iconic. [lint]
- Ceiling: narration occupies at most 25% of runtime. Proposed and fixed for the pilot. Readings occupy at least 30%. At least 10% of runtime has no voice at all. [lint on the rendered timing of lines]
- The narrator never speaks over the first 3 seconds of a new archival clip and never over the record-is-silent card. [lint]

6.2 The read-by cast
- Verbatim only. The `text` of a testimony line is byte-equal, after whitespace normalisation, to a span of the cited extract file. [lint: substring match against `extracts/<source>.<locator>.txt`]
- Ellipsis: an omission inside a reading is marked `[...]` in the screenplay, is read as a half-second pause, and is shown as ` ... ` in the subtitle. An omission never joins two sentences into a claim neither made; the reviewer checks every `[...]` against the extract. No more than 2 omissions per reading. [lint counts; reviewer reads]
- One consistent voice per real speaker across the film and across films in the strand; a voice is never shared by two real speakers in one film. [lint: `read_by` to `speaker` map is one-to-one within a film]
- No imitated accents, no attempted likeness of a real voice, no gendered mismatch: a woman's words are read by a woman-presenting voice, a man's by a man-presenting voice, in a plain register in the language of the source text. Translation is read only when the extract is itself a translation, and the lower third says so.
- Credit wording, in the end credits and in the sources page, exactly: `Read by a computer voice. No recording of <name> was used.` once per speaker.
- A reading is never set to music that swells, and is never faded under narration.

6.3 Archival audio playing as itself
- A real recording (a speech, a radio bulletin, a newsreel's own narration) is used only when its licence is on the allowlist, plays at its own speed, and is marked `archival_audio` with its source id. It is never cut together with a read voice to form one sentence. Its words are subtitled from a transcript the ledger cites, not from listening. [lint: `archival_audio` lines carry `source` and `transcript_source`]
- A newsreel's own narration is a voice of its time: it is introduced by lower third as `<Newsreel name>, <year>, original narration` and is never used as the film's narrator.

6.4 Introducing and naming accounts
- The first time any voice speaks, a lower third names it (section 9 format). No voice is heard without a name; "a survivor" is not a name. An anonymised source may be named as the archive names it, with the archive's wording, and the lower third says `name withheld by <archive>`.
- The narrator introduces an account in at most one sentence of fact (who, where, when, from what document), never a characterisation.
- Each speaker carries `side` and `gender` in the cast list. `side` is one of `india`, `pakistan`, `bangladesh`, `britain`, `sikh`; a speaker belongs to one side as the research ledger records it. Sikh is its own side because the Punjab was partitioned through the Sikh community and neither state speaks for it.

6.5 Balance across accounts
Measured on testimony seconds (read-by plus archival audio, narration excluded). [lint]
- Every side present in the research ledger is present in the film, and each present side holds at least 10% of testimony seconds; no side holds more than 35%.
- At least 2 named speakers per side.
- Women's words are at least 30% of testimony seconds.
- The last testimony line of each chapter comes from a different side than the last testimony line of the previous chapter, and the last three testimony lines of the film come from three different sides.
- The final spoken line of the film is narration or silence, never testimony.
- If the ledger cannot meet a threshold, the film does not fake it: the shortfall is stated in the record-is-silent card at the end of the close ("No first-person Bengali account under an open licence was found"), and the shortfall is logged in `coverage.md` as a scout task.

## 7. Image vocabulary

7.1 Archival video
- Trims only at the shot level: in and out points in seconds on the ledger item. A shot is never trimmed to remove a person from frame when the person is the subject.
- Holds: a freeze on a frame is allowed for up to 2 seconds within ARCHIVE; longer freezes are RECONSTRUCTED `re-timed`.
- Speed: any speed change, in either direction and of any size, is RECONSTRUCTED `re-timed`. Silent-era reels shot at 16 or 18 fps are played at the frame rate the archive's digitisation set; the screenplay records that rate.
- The clip's own sound (optical track, newsreel narration) plays unless the screenplay says `mute` with a reason.
- No loops. A clip ends where its out point is; it is not played forward and back.

7.2 Stills: Ken Burns presets
Each still shot names one preset. Zoom factor is relative to the largest 16:9 window that fits the photograph (z = 1). Maximum z is 1.3. Motion is eased with the sine ease in `studio/sketch.py`.

| Preset | From | To | Use |
|---|---|---|---|
| HOLD | z 1.0 centre | same | documents, faces, anything that must be read |
| PUSH | z 1.0 | z 1.12, same centre | arriving at a subject |
| PULL | z 1.12 | z 1.0 | leaving a subject, end of a sequence |
| DRIFT | z 1.15, left or right third | same z, opposite third | crowds, roads, columns |
| TILT | z 1.2, top | same z, bottom (or reverse) | sky to ground, arriving on foot |
| DETAIL | z 1.3 on a named region | same | one object or face, 3 to 5 s, after a wider shot of the same still |

A still shot lasts 4 to 10 seconds; a DETAIL is 3 to 5. A face is never pushed past z 1.3. [lint]

7.3 Cut versus dissolve
- Cut by default. Dissolve (0.5 to 1.5 s) only within one mark class and within one continuous subject (the same place, the same column, the same document). A dip to black (0.5 to 1.0 s) marks a change of chapter, a change of mark class, or a passage into silence. [lint on class pairs; reviewer on subject]
- No wipes, pushes, zooms between shots or any transition effect besides these three.

7.4 Black and white versus colour
- Archival material plays in its own colour state. Nothing is colourised except as RECONSTRUCTED with a stated reason, and the pilot colourises nothing.
- Generated and drawn shots are in colour (section 5.3). Cards are bone text on near-black.
- The film's colour grade touches archival frames only by flat level or gamma (section 4.2); no looks.

7.5 Frame rates and aspect ratios
- Master: 1920 by 1080, 16:9, 24 fps, Rec.709. Delivery: HLS at 1080p and 720p.
- Newsreels and period stills are shown at their native aspect, pillarboxed or letterboxed on a plain near-black field. No blurred-edge fill, no stretch, no crop that removes a person who is in the source frame. A crop for a DETAIL move is allowed on stills only, and only within the rules of 7.2. [lint: shot aspect equals asset aspect for video]
- A source digitised at 25 or 30 fps is conformed to 24 by frame drop or repeat with no speed change; frame interpolation is RECONSTRUCTED `interpolated`.

## 8. Sound

8.1 The house motif (brief for the composer)
- Length 18 to 24 seconds, whole; it plays at the title and under the end credits and nowhere else.
- One sustained instrument of long decay (a bowed drone or a struck string left to ring), a single rising figure of four to six notes, no percussion, no reverb tail longer than the room it was recorded in. It should sound like a reading lamp turned on in an archive, not like a trailer.
- Written as note data in `score.yaml` on pinned CC0 or CC BY samples, so it renders the same on every film. Credit line in the ledger.

8.2 The subject's musical palette (Partition)
- Punjabi: the Heer of Waris Shah as a sung tradition (kafi and qissa singing), the tumbi and the algoza, the dhadd and sarangi of the dhadi tradition. Bengali: Baul song, the ektara and dotara, bhatiyali boat songs, Nazrul and Tagore only as public-domain compositions with cleared recordings.
- Only recordings or performances on the allowlist, and only compositions whose copyright has expired (India: 60 years after the author's death). A tradition is credited by name and the performer is credited by name. [lint: every music cue carries `source` and `licence`]
- Avoiding cliche: no sitar or tabla as a generic "India" signifier; no drone under a reading; no instrument from a tradition under words from a different side; no music under the record-is-silent card; no music under any account of violence; a palette cue plays at most once per chapter and never across a chapter card.

8.3 Real ambience only
- Field recordings on the allowlist, credited in the ledger with place and year of recording. Ambience is never synthesised, never Foley, never looped audibly (a loop point is at least 40 seconds apart and crossfaded). An ambience cue names what it is and where it was recorded in the lower third of the sources page, not on screen. [lint: `source` on every ambience cue]
- Ambience never pretends to be the period: a railway recorded in 2019 is credited as 2019.

8.4 Silence
- True silence (digital zero) is allowed for up to 6 seconds; room tone from a credited recording covers longer silences.
- At least three passages of 8 seconds or more with no voice and no music. [lint]

8.5 Levels
- Integrated loudness -16 LUFS, true peak -1.5 dBTP (EBU R128, measured on the full programme). Dialogue (narration and readings) sits at -18 to -20 LUFS short-term. Music under voice ducks 9 dB with 250 ms smoothing. Ambience under voice sits 12 to 18 dB below dialogue. Archival audio keeps its own dynamics within these ceilings. [lint on the render log]

## 9. On-screen text

- Title card: film title on one line, `void document` beneath it in the product face, on near-black. 5 seconds. CARD.
- Chapter cards: `<number>  <title>` on one line, with the dates the chapter covers beneath in `tabular-nums`. 3 to 4 seconds, over black, CARD. Chapter titles are at most 5 words and never a verdict.
- Speaker lower thirds, bottom left, shown for the first 4 to 6 seconds of a speaker's first line in the film and again the first time they speak in a later chapter. Exact format, three lines:
  - line 1: `<Name>` (as the source names them; `name withheld by <archive>` if withheld)
  - line 2: `<role or place>, <year of the words>`
  - line 3: `<source title>, <archive>  ·  read by a computer voice` or `  ·  original recording`
  Example: `Sir Evan Jenkins` / `Governor of the Punjab, 1947` / `Telegram to the Viceroy, The Transfer of Power vol. XII  ·  read by a computer voice`. [lint: three lines, line 3 ends in one of the two suffixes]
- Record-is-silent statements, centred, bone on black, at least 4 seconds, exact form: `The record holds no <what>.` optionally followed on a second line by `<what was searched>.` Example: `The record holds no open-licence film of the ceremonies of 14 and 15 August 1947.` / `Searched: National Archives, Internet Archive, Library of Congress, Wikimedia Commons.` [lint: first line matches `^The record holds no .+\.$`]
- Text over footage: dates and counts only, bottom right, `tabular-nums`, never more than one line, never over a lower third.
- Credits, over black, CARD: every shot in order with id, archive, item title, year, licence and alteration; every reading with the credit line of 6.2; every recording and music cue with performer, tradition and licence; the corrections list with dates; the plugin and studio versions. Credits are generated from `sources.json`, never typed. [lint: credits text equals the generator's output]
- No em dashes in any on-screen text or subtitle. [lint]

## 10. Subtitles

- Languages: Hindi (Devanagari) and Urdu (Nastaliq) for the pilot; English captions for the deaf and hard of hearing are also produced. Each is a WebVTT track built from `subtitle_source` in the screenplay.
- What gets subtitled: everything spoken (narration, readings, archival audio) and all on-screen text (cards, lower thirds, record-is-silent statements, text over footage). Lower thirds are subtitled as a bracketed line. [lint: every spoken line and every card has a cue in every track]
- Proper nouns: personal names are transliterated as the person wrote or was recorded writing them in that script where known, otherwise by the glossary `films/<slug>/glossary.yaml`, which lists every proper noun once with its Hindi and Urdu forms. A name not in the glossary fails the lint.
- Contested terms: a place whose name differs by side is given in the form the speaker used, with the other form in brackets on first use in each language, as the glossary records. Terms the sides contest ("riots", "massacre", "migration", "recovery") are subtitled with the word the source used, never softened or sharpened; the glossary records the chosen word per source.
- Numbers keep the source's own figures and units; lakh and crore are kept where the source used them.
- Timing: a cue is 1 to 7 seconds, at most 2 lines of 42 characters (Devanagari) or 38 (Nastaliq), bottom centre above the safe area, never overlapping a lower third (which moves the cue up).
- Human review is mandatory: each track is reviewed by a reader of that language before G3, the reviewer's name and date are recorded in `subtitles/review.yaml`, and the lint fails a publish with a track whose review record is missing or older than the track file. [lint]

## 11. Truth checks before render

The lint runs all of these and blocks the render on any failure; the reviewer signs the last four.

1. Every cited asset id exists in the dossier, with a licence on the allowlist and `shows_bodies: false`.
2. Every text source cited by a reading has `rights` on the allowlist; readings from `rights: null` entries are rejected.
3. Every reading's `text` is a substring of its extract file after whitespace normalisation; `[...]` count ≤ 2 per reading.
4. Every narration numeral carries a `source`; every narration line passes the banned list.
5. Narration ≤ 25%, readings ≥ 30%, voiceless ≥ 10%, generated ≤ 15% of runtime and ≤ 20% of any chapter.
6. Every frame carries exactly one mark class; marks change on cut frames; no dissolve crosses a class.
7. Every RECONSTRUCTED shot names its alterations from the closed vocabulary; every generated shot carries prompt, model, seed and `no_people: true`, and its prompt passes the forbidden-subject and forbidden-style scans.
8. No generated shot adjoins another; none opens or closes a part.
9. The balance thresholds of 6.5 hold, or the shortfall is stated in a record-is-silent card and in `coverage.md`.
10. Chapter count 4 to 6; part durations in range; the house motif plays exactly twice; the final 6 seconds are voiceless.
11. Every lower third matches the three-line format; every record-is-silent card matches its form; no em dashes anywhere.
12. Every spoken line and card has a cue in each subtitle track; every proper noun is in the glossary; each track has a current human review record.
13. Credits equal the generator's output from `sources.json`.
14. Reviewer: watched every generated shot at full size and found no person, face, crowd, body or violence.
15. Reviewer: read 10 random readings against their extracts and found them verbatim with honest omissions.
16. Reviewer: confirmed no archival shot shows bodies, wounds or killing, and no account of violence is carried by music or narrated adjectives.
17. Reviewer: confirmed every generated shot is context for words already present and could not be taken for the record.

## 12. Screenplay format v2

`films/<slug>/screenplay.json`. Times are seconds from the film's first frame; every element has an `id`. Shots cite `dossier.json` assets; readings cite the research ledger and its extracts. The lint schema is `studio/screenplay.schema.json`; this section is its human form.

Top level: `title`, `slug`, `languages`, `runtime_target_s`, `cast` (speakers and voices), `parts` (ordered: `cold_open`, `title`, `chapter` ×4 to 6, `close`, `credits`), and `subtitle_source`. Each part has `id`, `kind`, `title`, `dates`, `shots[]`, `lines[]`, `cues[]`, `text[]`.

Shot kinds and their required fields:
- `archive_video`: `asset`, `in_s`, `out_s`, `native_fps`, `sound` (`own` or `mute` with `reason`), `mark: ARCHIVE` or `RECONSTRUCTED` with `alterations[]`.
- `archive_still`: `asset`, `preset`, `dur_s`, optional `region` for DETAIL, `mark`.
- `generated`: `prompt`, `negative_prompt`, `model`, `seed`, `dur_s`, `asserts: {no_people: true, no_period_look: true}`, `mark: AI-GENERATED`.
- `drawn`: `data_source` (a ledger id or a named table), `dur_s`, `mark: DRAWN`.
- `card`: `text[]`, `dur_s`, `mark: CARD`; `silent_record: true` for a record-is-silent statement.
- `black`: `dur_s`, `mark: CARD`.
Every shot has `start_s`, `transition_in` (`cut`, `dissolve` with `s`, or `dip` with `s`) and `why` (one sentence for the reviewer).

Lines: `kind: narration | testimony`. Testimony has `speaker` (cast id), `year`, `source`, `locator`, `text` (verbatim), and either `read_by` (voice id) or `archival_audio` with `transcript_source`. Narration has `text` and `sources[]` when it carries a number.

Cues: `kind: ambience | music`, `source`, `licence`, `start_s`, `end_s`, `gain_db`; music adds `role: house_motif | palette`, `tradition`, `performer`.

Text: `kind: lower_third | chapter_card | title_card | silent_record | overlay`, with `lines[]` and `start_s`, `end_s`.

Example (abridged to one chapter):

```json
{
  "title": "The Line",
  "slug": "partition-of-india",
  "languages": {"spoken": "en", "subtitles": ["hi", "ur", "en"]},
  "runtime_target_s": 1380,
  "cast": {
    "speakers": [
      {"id": "sp-jenkins", "name": "Sir Evan Jenkins", "side": "britain", "gender": "m", "role": "Governor of the Punjab"},
      {"id": "sp-witness-a", "name": "name withheld by <archive>", "side": "pakistan", "gender": "f", "role": "from a village in Ludhiana district"}
    ],
    "voices": [
      {"id": "v-narrator", "engine": "kokoro", "voice": "am_michael", "credit": "Narrated by a computer voice"},
      {"id": "v-01", "engine": "kokoro", "voice": "bm_george", "for": "sp-jenkins"},
      {"id": "v-02", "engine": "kokoro", "voice": "af_heart", "for": "sp-witness-a"}
    ]
  },
  "parts": [
    {
      "id": "ch-4", "kind": "chapter", "number": 4, "title": "The roads", "dates": "August to November 1947",
      "shots": [
        {"id": "S41", "kind": "card", "start_s": 612.0, "dur_s": 3.5, "transition_in": {"type": "dip", "s": 0.75},
         "text": ["4  The roads", "August to November 1947"], "mark": "CARD", "why": "Chapter card."},
        {"id": "S42", "kind": "archive_video", "start_s": 615.5, "asset": "commons-refugees-train-roof", "in_s": 0.0, "out_s": 5.0,
         "native_fps": 24, "sound": {"mode": "mute", "reason": "the file carries no original track"}, "transition_in": {"type": "cut"},
         "mark": "ARCHIVE", "why": "The only moving image of a refugee train the record holds; it carries the chapter's turn, so it plays with nothing over it."},
        {"id": "S43", "kind": "archive_still", "start_s": 620.5, "asset": "A-014", "preset": "DRIFT", "dur_s": 8.0,
         "transition_in": {"type": "cut"}, "mark": "ARCHIVE", "why": "The column, wide, while the Governor's count is read."},
        {"id": "S44", "kind": "drawn", "start_s": 628.5, "dur_s": 6.0, "data_source": "src-top-xii:item382", "transition_in": {"type": "dip", "s": 0.5},
         "mark": "DRAWN", "why": "Twelve districts drawn from the telegram's own list, so the number has a shape."},
        {"id": "S45", "kind": "black", "start_s": 634.5, "dur_s": 14.0, "transition_in": {"type": "cut"}, "mark": "CARD",
         "why": "No image exists for the witness's road; black carries her words alone."},
        {"id": "S46", "kind": "generated", "start_s": 648.5, "dur_s": 5.0, "transition_in": {"type": "dip", "s": 0.5},
         "prompt": "a dirt road across flat wheat country after rain, empty, late afternoon light, clean colour photograph", 
         "negative_prompt": "people, figures, crowd, animals, carts, vehicles, film grain, sepia, black and white, vintage",
         "model": "wan-2.2", "seed": 4471, "asserts": {"no_people": true, "no_period_look": true}, "mark": "AI-GENERATED",
         "why": "Context for the road already named by the witness; no travellers, no date."}
      ],
      "lines": [
        {"id": "L41", "kind": "narration", "start_s": 621.0, "text": "On 8 August 1947 the Governor of the Punjab telegraphed the Viceroy.", "sources": ["src-top-xii:item382"]},
        {"id": "L42", "kind": "testimony", "speaker": "sp-jenkins", "year": 1947, "source": "src-top-xii", "locator": "item382", "start_s": 624.0,
         "text": "say 7500 effective rifles to control 12 districts with a population of no less than 12 million", "read_by": "v-01"},
        {"id": "L43", "kind": "testimony", "speaker": "sp-witness-a", "year": 1947, "source": "src-<ledger id>", "locator": "para8", "start_s": 635.5,
         "text": "<verbatim span of the extract file>", "read_by": "v-02"}
      ],
      "cues": [
        {"id": "C41", "kind": "ambience", "source": "amb-railway-2019", "licence": "CC0", "start_s": 615.5, "end_s": 628.5, "gain_db": -20},
        {"id": "C42", "kind": "music", "role": "palette", "tradition": "dhadi (Punjabi)", "performer": "<as the ledger names>", "source": "mus-dhadi-01", "licence": "CC-BY-4.0", "start_s": 648.5, "end_s": 653.5, "gain_db": -14}
      ],
      "text": [
        {"id": "T41", "kind": "lower_third", "start_s": 624.0, "end_s": 629.0,
         "lines": ["Sir Evan Jenkins", "Governor of the Punjab, 1947", "Telegram to the Viceroy, The Transfer of Power vol. XII  ·  read by a computer voice"]},
        {"id": "T42", "kind": "overlay", "start_s": 628.5, "end_s": 634.5, "lines": ["7,500 rifles, 12 districts"]}
      ]
    }
  ],
  "subtitle_source": [
    {"ref": "L41", "start_s": 621.0, "end_s": 624.0, "en": "On 8 August 1947 the Governor of the Punjab telegraphed the Viceroy."},
    {"ref": "T41", "start_s": 624.0, "end_s": 629.0, "en": "[Sir Evan Jenkins, Governor of the Punjab, 1947. Read by a computer voice.]"},
    {"ref": "L42", "start_s": 624.0, "end_s": 630.0, "en": "say 7500 effective rifles to control 12 districts with a population of no less than 12 million"}
  ]
}
```

Rules the schema enforces beyond the fields: ids are unique; shots within a part tile the part's time with no gap or overlap beyond the stated dissolve; `subtitle_source` has one entry per line and per text element, with `en` filled from the screenplay and `hi` and `ur` filled by the subtitle step and reviewed per section 10; every `source` resolves to a ledger entry and every `locator` to an extract file; `read_by` resolves to a voice whose `for` is the line's speaker.

## Amendments

**2026-10-10, Chief of Staff (from the G2 design round; every one is checkable):**
- A1 (section 4): the mark's text is always near-white on the scrim (4.5:1 or better over any frame), and the class colour is a 3 px bar on the plate's left edge (ARCHIVE amber, RECONSTRUCTED bone, AI-GENERATED and DRAWN cold blue). Coloured mark text is not allowed.
- A2 (section 2): the 15% generated cap counts AI-GENERATED seconds only. DRAWN maps and diagrams made from cited data are not generated imagery, but they are marked DRAWN and listed with their data source.
- A3 (section 6): every speaker in the testimony ledger carries explicit `side` and `gender` fields. The balance check reads those fields and never infers them.
- A4 (section 4): marks are burned in for YouTube and screenshots. On document.voidvision.org the player also draws the current shot's mark as a crisp overlay from the film's `sources.json` timeline, so it stays legible on phones.

**2026-10-10, Chief of Staff (aspect, scale and frame rate; founder decision on stills framing):**
- A5 (sections 4.2 and 7.5, scale): plain resampling (bicubic or Lanczos) to the master frame is not a material alteration at any scale and stays ARCHIVE. Only learned upscaling (super-resolution models, face restoration, AI deblur) is RECONSTRUCTED `upscaled`. This replaces the 1.3x threshold. [lint: the resampler used per shot is logged; any ML upscaler forces RECONSTRUCTED]
- A6 (section 7.5, frame rate): a telecined source (24 fps film transferred at 29.97 with 3:2 pulldown) is restored by inverse telecine (field matching and decimation) to its original frames, with no speed change, and stays ARCHIVE. Only a true 25 or 30 fps source is conformed by frame drop or repeat. [lint: the conform method is logged per clip]
- A7 (section 7.2, stills framing; founder, 2026-10-10): every still opens whole, at its native aspect on the near-black field, so the viewer sees the entire record. The camera may then move in until the image fills the 16:9 frame. A fill is allowed only if every person in the photograph is inside the frame at some point in that shot; otherwise the move stays within the native shape. DETAIL moves on a region are unchanged. [reviewer: every person in frame at some point; lint: first frame of every still shot is the whole image]

**2026-10-10, writer-director of void document (proposed from the Partition treatment, revision 2; written against the founder's note that black under readings must fall to 20% of runtime or less; binding on the pilot once the Chief of Staff accepts):**
- A8 (section 2 rule 5, section 6.2, a reading's picture): rule 5's first step, "a black frame with the reading", is replaced. A cleared reading is set over a picture that is truthfully related to the words, chosen in this order and the first that holds is used: (1) the speaker at the time of the words; (2) the speaker's own occasion, the same place in the same week with the speaker in frame; (3) the same place and period, or the same subject in the same period, where the narrator's one-sentence introduction gives the photograph's own place and date as its caption gives them; (4) the speaker's own portrait from another year, the mark carrying that year; (5) a DRAWN map or typeset page of the places or figures the reading names, with the reading's extract as data source; (6) black, only where the absence is the meaning (an author of whom no open-licence image exists, a count of the dead, a poem) and for a pending account that passes none of 1 to 5. Never: a photograph of a named person other than the speaker unless the words are about that person or event and the narrator says so; a column, camp or crowd whose caption names one community under a voice from another; any photograph under a partisan government's statement, which is read over a DRAWN typeset title page under its perspective card. The mark and the credit stay on screen for the whole reading. A pending slot that fails becomes a record-is-silent card, never a black hold. Rule 5's remaining steps (map, record-is-silent card, cut) are unchanged. [reviewer: every reading checked against the order and the never-list; lint: a `black` shot under a testimony line is at most 30 s; a narration line introducing a rule-3 photograph carries that asset id in `sources[]`]
- A9 (section 7.2, still duration under a reading): a still that carries a reading may run to the reading's length, at most 30 s, as HOLD or as one preset eased over the whole shot after the A7 whole-image opening; stills of one subject may dissolve into each other under one reading. A still that carries no reading keeps the 4 to 10 s rule; DETAIL stays 3 to 5 s. [lint: a still shot that overlaps a testimony line is at most 30 s, otherwise at most 10 s]

**2026-10-10, writer-director of void document (pacing, from the founder's note on the Trailer cut that it "feels like a collage"; binding on the pilot once the Chief of Staff accepts):**
- A10 (sections 3, 7 and 8, pacing): the film breathes between scenes and lingers where the record deserves it. (1) Breath: at least 1.5 s with no voice across every change of scene (a dip, a card or a held frame), at least 1.0 s between a cut and the first word spoken on the new shot, and at least 0.8 s between consecutive voice lines; a narrator's line and a reading never touch. (2) Hold: a real moving-image clip runs at least 5 s; a still whose subject is a face or a person is held at least 8 s; a frame that carried a reading stays at least 1.5 s after the last word before the next cut. (3) Rest: no stretch of the film runs longer than 60 s without a held moment, meaning at least 4 s on one frame with no voice. Timings are measured on the rendered voice files, never on estimates. [lint on line timings against shot boundaries; the renderer's plan reports every breach with the shot and line ids]

**2026-10-10, Chief of Staff (founder ruling on black):**
- A11 (sections 1, 4 and 7.3): black is RGB 0,0,0 wherever the film is black (cards, black under a voice, pillarbox and letterbox fields, the hold of a dip). The one exception to "a mark on every frame" is the black hold at the bottom of a dip to black: those frames are entirely black, with no mark, watermark or lower third. [lint: frames inside a dip's hold are all zero; every other frame carries a mark]
- A12 (section 6): voices never overlap. Timing comes from measured audio durations; consecutive voice lines are at least 0.8 s apart. [lint: voice-overlap, blocking]

**2026-10-10, Chief of Staff (sound; engine run r-20261010-134936-c606):**
- A13 (section 8.5): synthetic voice lines (narration and read-by testimony) are levelled per line to the dialogue target and may be peak-controlled per line by an oversampled true-peak limiter before mixing, so their crest factor fits the programme (measured: Kokoro and Orpheus lines peak 12 to 21 dB above their own loudness). Each line's gain and peak reduction are journaled. Archival audio (archival_audio, clip sound, ambience) is never levelled or limited; it keeps its own dynamics. The master limiter remains peak-control only and the engine refuses a final master when it does more (limiter-peak-only).
- A13 refined (2026-10-10, Chief of Staff, from runs on the trailer's R2 and R9): per-line peak control refuses a take only for sustained gain reduction, never for a click: more than 8 dB for over 20 ms in total, more than 1 dB for over 20% of the line, or more than 3 dB for over 5% of the line.

**2026-10-10, Chief of Staff (programme loudness):**
- A15 (section 8.5): the finished programme's integrated loudness is -18 LUFS (true peak at most -1.5 dBTP), not -16. This matches 8.5's dialogue level of -18 to -20 LUFS in the finished programme, keeps the calm the founder asked for, and gives synthetic voices the headroom natural speech needs: the per-line peak ceiling becomes about -4.8 dBTP (dialogue -20 LUFS plus the programme's 16.5 dB headroom, less a 1.3 dB margin for the mix-to-master gain). Measured on the episode's 29 reader takes: 6 failed per-line peak control at the old ceiling, 0 fail at the new one. YouTube does not raise quieter programmes, so the film plays slightly quieter than loudness-maximised videos, by design.

**2026-10-10, Chief of Staff (T1c: the founder's newsreel and narrator rulings; appended, so sections 4.2, 8.5 and 12 above keep their original text and are read with these; A14 sits after A15, which landed first):**
- A14 (section 4.2, alteration vocabulary): `colour cast removed` joins the closed alteration list. A clip whose transfer carries a colour cast (the 1946 United News reel's magenta) may be neutralised to grey, its luma kept, before it is fitted and pillarboxed; the shot is then RECONSTRUCTED `colour cast removed`, never ARCHIVE. A ledger item or a shot sets `neutralise_cast: true` (the shot's value wins). [lint: colour-cast-marked, blocking: the flag needs the RECONSTRUCTED mark with that alteration, and the alteration needs the flag; alterations-closed carries the new label]
- A14 (section 12 and 8.5, narrator delivery): a narration line may carry `delivery: {mood, intensity, pace, pause_after_s}`, with mood one of plain, measured, grave, hushed, close. Voices are rendered upstream; in the engine delivery moves only the level, by an offset applied after the line is levelled to -20 LUFS and peak-controlled (A13): plain 0, measured 0, grave -0.5, hushed -2.0, close -1.0 dB. An offset beyond 2 dB either way is refused, and so is `delivery` on a reading. A synthetic voice line (narration or read-by testimony) carries no `gain_db`; the mood offset is its only level change. Each offset is journaled as a decision. [lint: narrator-delivery and voice-gain-db, blocking]
- A14 (section 6, one narrator): every narration line must sound like the same narrator. Per line, the engine measures the median pitch (f0) and its 10th to 90th percentile range over voiced 40 ms frames (normalised autocorrelation, frames of RMS 0.01 or more after levelling), the spectral centroid and the words per second. The narrator's baseline is the median of each measure over all lines; a line more than 2.5 robust z (median and MAD) from it in pitch or centroid is refused, except in the direction its mood expects: hushed and grave may be lower and slower, close may be lower, and no mood may be brighter or higher. Every line's profile and the baseline are journaled. [lint: narrator-consistency, blocking; a warning under --draft]
- A14 (section 12, music cues): a music cue's `gain_db` is an offset from the -26 LUFS bed every music cue is first levelled to over the part that plays (6 dB under the dialogue), not an absolute gain; `gain_db: 0` is the bed. Ambience cues are not levelled and their `gain_db` stays a plain gain.
- A14 refined (2026-10-10, Chief of Staff, from the T1c review): a mood's level offset is 0 or less, never positive. A lower mood's allowance is bounded: its pitch may sit at most 3 semitones under the narrator's baseline and its centroid at most 5 robust z (twice the limit) under it; past either bound the line is another voice, whatever its mood. The baseline comes from the plain and measured lines (all lines when fewer than 4 of those), and is anchored, when `studio/narrator-profile.json` holds the film's narrator voice, on the f0 and centroid of the approved audition. The part is refused when the baseline lines' robust pitch scale is wider than 1 semitone (two voices sharing the narrator). [lint: narrator-delivery, narrator-consistency]
- A14 refined (2026-10-10, Chief of Staff ruling on calibration; replaces the robust-z bounds above): narrator-consistency judges a line against perceptual bounds from the narrator's baseline, the median f0 and centroid of the film's plain and measured narration lines. A line is out of character when its f0 is more than 1.5 semitones above the baseline (any mood), more than 1.5 semitones below it (plain, measured or unmarked) or more than 3 semitones below it (hushed, grave, close); or when its centroid is more than 25% above (any mood), more than 25% below (plain, measured or unmarked) or more than 40% below (the lower moods). The stored narrator profile (`studio/narrator-profile.json`, the approved audition) is a drift check only: the engine warns when the film's baseline f0 is more than 1 semitone from it, and it never sets the baseline or the bounds. The part is still refused when the baseline lines' robust pitch spread is wider than 1 semitone. [lint: narrator-consistency, blocking (a warning under --draft); narrator-drift, a warning]
- A14 superseded in part (2026-10-10, Chief of Staff, from the T1c re-review): in the "A14 (section 6, one narrator)" entry and the first "A14 refined" entry above, the robust-z bounds, the mood exemptions bounded in z, and the anchoring of the baseline on the stored profile are superseded by the second "A14 refined" entry (perceptual bounds) and by this one. Nothing above is deleted; read those passages as history.
- A14 refined (2026-10-10, Chief of Staff, from the T1c re-review: three ways a second voice could pass): (1) a whole lower mood may not sit low. Each of hushed, grave and close with at least 2 lines, and the lower moods pooled, keep their median f0 within 1.5 semitones of the baseline; a single line may still drop 3. This stops a second voice taking the plain lines while the narrator keeps only the lower ones. (2) Timbre: the film's baseline centroid is compared with the stored profile, with a warning past 15% either way and a refusal past 25%. (3) Pitch drift from the stored profile warns past 1 semitone and is refused past 2. Drift refusals are warnings under --draft. A narrator voice with no stored profile is journaled as a review item, "no reference profile", so it surfaces at G3. [lint: narrator-consistency (per line, per lower-mood group, the part's spread), narrator-drift (f0 and centroid; review when there is no profile)]

**2026-10-10, founder revamp (supersedes the rules named below where they conflict):**
- A16 (sections 4, 9): on-screen information is subtle. At each shot change a short, quiet provenance label (class and year, e.g. "Archive · 1947") shows for about 3 s, then fades to a small class glyph in the corner that stays for the rest of the shot, so every frame still carries its provenance. Lower thirds show name, role and year briefly, then go. Supersedes A1's always-on full plate.
- A17 (section 6.1): the narrator tells a story in literary prose, with imagery, rhythm and feeling, and may describe what the record shows people did and the weight of it. She never puts thoughts or words into a named person's head, and every fact remains sourced. The bans on adjectives of feeling and on "what anyone felt" are lifted for the prose; invention remains forbidden. The 25% narration ceiling is lifted; narration may carry most of the film.
- A18 (sections 2, 3): a film is built in this order: theme, perspectives, footage and content, revisit the theme, then prose. Footage serves the theme, not the reverse. Long voiceless stretches are the exception, kept for moments the theme asks for; the 10% voiceless floor stays.
- A19 (section 8): the film carries underscore through its scenes, not only the motif at its bookends; digital silence is used only where the theme asks for it. Synthetic voice lines are cleaned (gentle spectral denoise, then a downward expander between words) before levelling, journaled per line; archival audio is never cleaned.
- A16 refined (2026-10-10, Chief of Staff, from the T1e review): the provenance label shows at every cut, never suppressed for repeated wording; an AI-GENERATED label never fades and stays for the whole shot, because its glyph is not distinguishable from DRAWN at small sizes and the class must never be hidden.
- A16 refined, checks (2026-10-10, Chief of Staff, from the T1e re-review): an AI-GENERATED label is at full opacity from the cut frame and stays through a dissolve. The mark-coverage lint checks each frame's glyph for its class's shape as well as its hue, against what that class's glyph composes over the frame before the mark, so the picture under the mark can never fail a correct frame. A19's inter-word floor is the median power of the take's quietest 10% of 20 ms frames, cleaned and levelled, under -80 dBFS; their 90th percentile is journaled, not limited. voice-chop also refuses a take whose pauses (frames 30 dB under its speech) are under 5% of it, or whose floor frames spread more than 6 dB, because then its floor cannot be measured. [lint: mark-coverage, voice-clean, voice-chop, blocking (warnings under --draft for the voice lints)]

**2026-10-10, founder rulings on the revamp (in chat; recorded by the Chief of Staff, T1f; appended, so sections 6.1, 6.4, 6.5, 7.2, 11 and A8 above keep their text and are read with these):**
- 6.1 amended (readings floor): readings (read-by and archival testimony) occupy at least 20% of runtime, not 30%; the same in 11.5. The story leads; the readings stay. Voiceless stays at least 10% (A18). [lint: readings-floor, on the speech-active spans of the placed lines; blocking on a full, final render of an event film]
- A20(a) (sections 7.2 and A9, still duration): an archive still with narration speaking over it may hold up to 20 s; with a reading over it, A9's 30 s; with no voice over it, the 10 s cap. Within any hold, however long, no stretch with no voice runs over 10 s: the 10 s cap applies wherever nothing is spoken, so a reading's last words do not license 29 s of silence. "Speaking over it" is measured on the speech-active spans (first to last sample over -60 dBFS, as placed in the mix) of the narration and testimony lines that overlap the hold, merged. Consecutive shots of one photograph joined by a cut or a dissolve are one hold. A DETAIL shot is at most 5 s (7.2's lower bound of 3 s is not linted). [lint: still-hold, blocking on a final render, a warning under --draft and in a check render]
- A20(b) (sections 6.1 and A8 rule 3, the narrator and the screen): the narrator never reports the screen: she does not say who is in the picture, where or when it was taken, or what it shows. Who and where are carried by the provenance label (A16) and a lower third: for a speaker the three-line form of section 9; for a photograph's place, the two-line place form, `<place as the caption gives it>` / `<date as the caption gives it>`. This replaces A8 rule 3's narrator caption sentence (6.4's one-sentence introduction of an account may not describe the picture either); A8's lint that a narration line introducing a rule-3 photograph carry its asset id is withdrawn (the engine never had it). [lint: lower-third-format accepts the two-line place form; reviewer: no narration line describes the frame]
- Balance (6.5 and 11.9): a shortfall, including a side the ledger holds that has 0 testimony seconds and women's words under 30%, is allowed when the close's record-is-silent card (card D in the pilot) states it. The pilot ships with women's words at 18.5% and no Bangladeshi account, stated on card D; sourcing continues for v2. [reviewer; the engine does not lint 6.5, and the sources page shows each side and women's share against the band with "Short of the floor"]
- A14 refined (mood `warm`, Chief of Staff): `warm` joins the moods at 0 dB: plain, measured, warm, grave, hushed, close. It is judged like a plain line by narrator-consistency (not one of the lower moods) and is not part of the narrator's baseline. [lint: narrator-delivery]
- A19 refined, voice-chop (Chief of Staff, T1f): voice-chop always refuses a take with too few pauses to measure its floor (frames 30 dB under its speech under 5% of its live span). Its two other refusals, floor frames spreading more than 6 dB and more than 2% of audible frames cut by more than 3 dB, apply only when what the expander turns down could be heard: when the expander's threshold as levelled (its threshold on the raw take, at least the raw floor + 3 dB, plus the line's levelling gain), or the raw floor frames' p90 as levelled, is above voice-clean's -80 dBFS. Otherwise both numbers are journaled as an inaudible-floor pass, with the reason. The p90 guard keeps a floor whose median is a digital-zero dropout from hiding a loud hiss the expander never touches. [lint: voice-chop, blocking (a warning under --draft)]
- A19 refined, denoise-only path (Chief of Staff, T1f; supersedes the voice-chop line above where they differ): the expander assumes one steady floor. When a take's floor frames spread more than 6 dB, or the first pass cuts more than 2% of its audible frames by over 3 dB, the take is cleaned again by the gentle spectral denoise alone, without the expander, and that decision is journaled with its reason and both numbers. The take used is the one judged: voice-chop refuses it only for too few pauses (always refused, on either path), and journals its spread and the denoise's own cuts without limiting them; voice-clean holds its floor as levelled under -80 dBFS, and also the median of its floor frames that are not digital silence, so a hiss that drops to digital zero in a pause cannot pass on a median of zeros. A denoise-only take that fails voice-clean is audible hiss: re-render it. The inaudible-floor waiver above is withdrawn, since every take it could waive now goes this way. [lint: voice-clean, voice-chop, blocking (warnings under --draft)]
- A20(a) (refined, CoS, T1f review; replaces the A20(a) line's caps where they differ, which are not founder rulings): inside a hold the speech-active spans of the readings are merged as the voice spans are, and three limits apply: the longest stretch not under a reading is at most 20 s, the longest stretch with no voice at most 10 s, and the whole hold at most 30 s. A reading's last words therefore never lift a narrated still past 20 s. Holds of one photograph joined by a dip are linked for the 10 s silence check (the dip does not reset it). [lint: still-hold]
- A19 refined, true pauses and speech-referenced chop (CoS, T1f review; founder's intent: "every time Tara's voice comes, a noise is there in the otherwise silent background"): on both cleanup paths, voice-clean also holds the median of the take's true pauses, after cleaning and as levelled, under -80 dBFS. True pauses are live frames at least 100 ms from any frame within 30 dB of the take's speech level; a frame as spectrally flat as white noise (Wiener entropy 0.4 or more) is noise, not speech, and guards nothing. With fewer than 5 true-pause frames the floor frames' p90 stands in. voice-chop, on both paths, refuses a take where more than 2% of the frames within 30 dB of its speech level lost more than 3 dB; the floor-referenced chop share is journaled only. The pause-share refusal stays. [lint: voice-clean, voice-chop]
