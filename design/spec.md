# void document: design spec (Blueprint round 2, for G2)

## Two products, one look

**document.voidvision.org is for viewers.** Four surfaces (Screening room, Film, Sources, Corrections), minimal and cinematic, with the film first. Nothing on them is technical: no render stats, no studio words ("cut", "shot", "render", "pipeline", zoom values, model names), and no link to `/studio` or mention of it.

**The Director's Lens is for the founder only.** It is a private, dense, keyboard-driven working tool that shows every stat the studio measures. It runs on `127.0.0.1` during a run, and at `/studio` behind a single admin sign-in (section 5d), fed by snapshots the laptop pushes. **Bookmark `/studio` on the phone:** it is where to watch a running render, and the Board only hears when one ends.

They share the type voices, the safelight meaning and the mark hues, and nothing else.

Binding inputs: `docs/DECISIONS.md` (from "Pivot to void document"), `films/GRAMMAR.md` (sections 4, 9 and 10 especially), and the round-2 brief. Files: `design/tokens.css` (the only color literals), `design/BRAND.md`, `design/mocks/` (`index.html` lists them).

**Mock content.** The mocks use only real Partition material:
- **Footage:** cleared items from `footage-scout.json` (public domain or CC0 only; licence-unclear items left out).
- **Stills:** items from `stills-ledger.json` with their real titles, creators, dates and licences. The four Photo Division stills re-dated to 1947 carry 1947 in the mark, with `date_catalogued` (1954-02) shown in Sources.
- **Readings:** verbatim spans of `testimony-ledger.json` (15 items with `side` and `gender`), cut only where an ellipsis shows; the generator checks every span against the excerpt.

Chapter titles, planned times and the numbers come from `films/partition-of-india/TREATMENT.md`; the cut replaces planned times. Lens timings are illustrative values of what the timing ledger records. No image shows bodies or violence. Screenshots are in `agentique/reports/g2/document/`; the narrow widths are side-by-side composites.

## Shared rules (public)

- Every public surface is dark (`data-theme="dark"`). The light roles serve `/privacy.html` and print only.
- Safelight marks credits, source links and the ARCHIVE mark only. Every timecode that navigates (Sources entries, chapters, transcript, the player clock) and typed input are bone. Cold blue marks AI-GENERATED and DRAWN only.
- Footer: "void document is part of void, with void news and void history." · "Films are free to watch and licensed CC BY 4.0." · "Privacy".
- Copy for this film is sober and plain. Never "tragic", "horrific", "bloodiest", and never a toll as a headline. Each page says what the film shows and does not show.
- Keyboard: every control is a real button or link with a bone focus ring, and touch targets are 44 px or more. Telemetry: `page_view`, `film_completed` at `ended`, `source_opened` on item links, and `correction_submitted` server-side.

## The in-picture mark (GRAMMAR 4), as rendered

| Class | Rule hue (token) | Text (`--mark-text`, mono) | Size |
|---|---|---|---|
| ARCHIVE | `--mark-archive` (amber) | `ARCHIVE  <archive> <year>` | 3.1% of frame height |
| RECONSTRUCTED | `--mark-reconstructed` (bone) | `RECONSTRUCTED  <archive> <year>  <alteration>` | 3.1% |
| AI-GENERATED | `--mark-generated` (cold blue) | `AI-GENERATED  context` | 3.1% |
| DRAWN | `--mark-generated` (cold blue) | `DRAWN  from <data source>` | 3.1% |
| CARD | `--mark-reconstructed` (bone) | `VOID DOCUMENT` | 2.4% (small) |

- **Placement.** The plate (`--mark-scrim`, black at 60%) sits at 4% from the left and 5% from the top, with radius 0.55% of height and padding 0.6 em. The class word is uppercase at weight 600, and the year is tabular.
- **Hue as a rule, not as text.** The class hue is a 3 px rule on the plate's left edge, and the text is always near-white. Amber or blue text cannot reach 4.5:1 on a 60% scrim over a bright frame, while `--mark-text` holds 5.34 there (tokens.css lists the checked pairs).
- **Hue separation.** Cold blue is 189 degrees from amber and 31.7 L* below it, so the two classes read apart in greyscale (GRAMMAR asks for 120 degrees and 30%).
- **Brand kit.** Film graphics follow `design/brand-kit/BRAND-KIT.md`: the watermark top right (6% of height, 0.6 opacity, off on CARD), BBC-style lower thirds with no box (rule, name, role, source, wash) and the partisan flag above the rule, the chapter card and the record-is-silent card. The kit wins over this spec on film graphics.
- **A7.** Every still opens whole at its native aspect on the near-black field for about 1.5 s, then moves in; the film mock's frame shows S-038 in that opening.
- **Zones.** Lower thirds sit bottom left (three lines, GRAMMAR 9). Subtitles sit bottom centre and move up above a lower third. Text over footage goes bottom right, and chapter cards centre. The player never puts chrome in the mark zone (top-left 30% × 20%), the watermark zone (top-right 12% × 12%), the lower-third zone or the subtitle line. The paused credit sits **top right, from 15% of frame height**.
- **Burned in.** Marks and lower thirds are in the video, so they scale with the picture: at phone width they are small, and that's what was burned. Player-drawn subtitle cues keep a 14 px minimum.

## 1. Screening room `/`

**Job:** put the current film on the marquee. **Hero:** a real still, the lantern slide captioned "Dawn of Independence: At Red Fort", full bleed in greyscale, with the title card set as an opening credit.

| String | Copy |
|---|---|
| eyebrow | Now showing |
| title | The Partition of India |
| place | 1946 to 1948, told with the public record |
| note | This film tells of killing, abduction and flight through the words of people who were there. Every reading is word for word from its source, sometimes in part (marked ...). Voices are read by a computer; no recording is imitated. This film shows no bodies or killing. Every second carries a mark that says what it is. |
| actions | Watch (runtime added once cut) · Sources |
| credits | Film and photographs from the National Archives, the Internet Archive and Wikimedia Commons. Words from Hansard and the Punjab Boundary Commission papers. |
| poster credit | Indian Independence Day at the Red Fort. Unknown author, 1947. Wikimedia Commons, public domain. |
| before release | The first void document is being made. / The Partition of India, 1946 to 1948. |

## 2. Film `/f/<slug>`

**Job:** play the film to its last frame, and keep what you are seeing honest. **Hero:** the film, with its mark in the corner.

**Layout.**
- **Landscape, 760 px and wider:** the screen is `100svh` with the frame contained.
- **Portrait and phones:** the top bar, the frame, the paused credit and the controls stack, so there is no black above the image.
- **Top bar:** wordmark, Sources, Correct something.
- **Controls:** scrubber (with chapter ticks once chapters exist), play, time, **Subtitles**, **Marks**, **Chapters**, volume, full screen.
- **Below the screen:** title card, a note on whose accounts are present and absent, Sources and Correct rows, the Chapters drill, and the Transcript drill (in all three languages).

| Control | Copy and behaviour |
|---|---|
| Subtitles menu (`role="menu"`, radio items) | Subtitles: Off · English captions · हिन्दी (`lang="hi"`) · اردو (`lang="ur"`, `dir="rtl"`). The choice is remembered per browser (try/catch). C cycles. |
| Marks legend (dialog) | "The mark in the corner says what you see", then one row per class, each with the mark itself and one line: ARCHIVE "Real film or photograph from the archive, unaltered beyond trims, crops and slow moves." RECONSTRUCTED "Archive material changed in a way that matters. The change is named." AI-GENERATED "Made by a computer model: places, weather, objects. Never people, never a recorded event." DRAWN "A map or diagram drawn by us from named data." CARD "Text on black: titles, chapter cards, and where the record is silent." Link: "Every shot and its mark". Opened with M. |
| Chapters | From the treatment, planned times: 0:00 Cold open · 1:13 1 The count (1946 to 3 June 1947) · 5:08 2 The line (30 June to 17 August 1947) · 8:05 3 The midnight (11 to 15 August 1947) · 11:00 4 The roads (August to December 1947) · 14:18 5 After the line (October 1947 to 1949) · 18:14 Close: the border today · 20:33 Credits. Ticks on the scrubber; each row seeks; `[` and `]` step. |
| paused credit (top right) | `<item title>` / `<archive>, <year>. Licence <licence>.` (safelight) / See the source |
| note | Accounts from Britain, India, Pakistan and the Sikh community, read word for word. The record we could clear holds no first-person account from Bangladesh and none by a woman; the film says so where it matters. (Generated from the balance data, never typed.) |

**Subtitle rendering (GRAMMAR 10).**
- **Layout boxes:** cues come from the WebVTT tracks. The player places them using the mark track's layout boxes from `sources.json`: bottom centre, and lifted above a lower third while one is on screen.
- **Faces and RTL:** Hindi uses Noto Sans Devanagari. Urdu uses Noto Nastaliq Urdu with `dir="rtl"` and a 1.9 line height, with numerals wrapped in `<bdi>` so years never reorder.
- **Line limits:** at most 2 lines, 42 characters (Devanagari) or 38 (Nastaliq).
- **Lower thirds** become a bracketed line: `[क्लेमेंट एटली, प्रधानमंत्री, 1947]` / `[کلیمنٹ ایٹلی، وزیر اعظم، 1947]`. The mock cues are drafts until human review, which GRAMMAR requires before release.

**States:** ready (poster plus Play); playing (chrome hides); paused (credit top right); buffering; ended (`film_completed`, then `credit-roll` of every shot's source, with Watch again / All sources / Correct something); error ("The film could not load." / "Check your connection, then reload the page."); captions error; not found.

## 3. Sources `/f/<slug>/sources`

**Job:** show every shot's mark and source, and whose words the film holds. **Hero:** the ledger, filterable by mark, with the account balance beside it.

**Filters.** Toggle buttons (`aria-pressed`): All · ARCHIVE · RECONSTRUCTED · AI-GENERATED · DRAWN · CARD, each with its count and its hue rule. An empty filter says so: "No shot in this film is AI-generated."

**Entries.** Each entry shows:
- the mark exactly as on screen;
- the time (or the ledger id before a cut);
- the item title (Fraunces);
- kind and year, plus duration in the archive;
- archive, item link (safelight), licence;
- for RECONSTRUCTED, the alterations from GRAMMAR's closed list;
- for AI-GENERATED, the prompt, model, seed and the no-people check result;
- for DRAWN, the data source;
- for CARD, what was searched;
- "Correct this", which goes to Corrections with `?s=<id>`.

**Readings.** Each reading shows:
- the quote, verbatim, with `[...]` kept;
- Speaker (name and role, as the source gives them) and Side (Britain, India, Pakistan, Bangladesh or Sikh, as the research ledger records it);
- Year and Source (safelight link plus archive);
- Voice: "Read by a computer voice. No recording of <name> was used."

**Account balance, shown plainly** (numbers from TREATMENT section 5). Cleared testimony 396 s: Britain 136 s (34.3%), India 136 (34.3%), Pakistan 66 (16.7%), Sikh 58 (14.6%), Bangladesh 0. With every pending slot (616 s): 22.1 / 32.5 / 20.6 / 14.3 / 10.6%. Women 46 s, 11.6% (floor 30%; 23.4% with every slot). Seconds by mark: ARCHIVE film 137 (10.6%), ARCHIVE stills about 628 (48.6%), DRAWN about 308 (23.8%), CARD 220 (17.0%), AI-GENERATED 0.

**Balance panel layout.** "Whose words, and how long."
- One bar per side, giving testimony seconds and share of all testimony, with the GRAMMAR 6.5 band marked (10% to 35%). It also shows named speakers per side, and women's share against the 30% rule.
- Before a cut it shows cleared speakers per side and "Seconds appear when the film is cut".
- Shortfalls appear in the record-is-silent form. Today, true of the cleared ledger: "The record holds no first-person Bangladeshi account under an open licence." and "The record holds no first-person account by a woman under an open licence." / "Searched: the void history research ledger, 54 sources."

## 4. Corrections `/f/<slug>/correct`

The same design as round 1, retitled "Correct something in *The Partition of India*". The lede is "If the film gets something wrong, a name, a date, a place, a word in a subtitle, tell us what, and where."
- **Arrival:** from "Correct this" the moment shows that ledger item and its credit; from a paused frame the time is filled in.
- **Sending:** a send shows "Sent." in place, with no page jump.
- **Field 1** takes a time or a ledger id: "Use a time inside the film, like 12:40, a ledger id, or leave this empty."

## 5. Director's Lens (Studio): local and `/studio`

**Job:** see what the run is doing, and whether the film still obeys GRAMMAR, at a glance and in full. **Hero:** the live monitor, showing the frame with its mark preview where the mark will be burned.

**Stages (the pipeline rail):**
1. **Scout ledgers:** rights re-read, `shows_bodies: false`, licence allowlist.
1a. **Conform (A6):** telecined sources restored by inverse telecine (field match, decimate) with no speed change; true 25 or 30 fps sources conformed by frame drop or repeat; the method is logged per clip.
2. **Story fit:** the coverage table: theme, then video / stills / text only / nothing.
3. **Narration:** readings and narrator, with the whisper match.
4. **Score**
5. **Motion:** Ken Burns on the rostrum curve, after the A7 whole-image opening. The resampler (bicubic or Lanczos) and its scale are logged per shot (A5); any ML upscaler forces RECONSTRUCTED `upscaled`.
6. **Generation:** context clips, each followed by the **no-people check**. A failing clip is dropped and never shown.
7. **Marks lint:** one mark per second, changes on cuts, no dissolve across classes.
8. **Assembly**
9. **Subtitles:** three tracks, plus the review record.
10. **Publish**

**New panels.**
- **Marks on the film:** a strip of the whole runtime, coloured by class (ARCHIVE amber, RECONSTRUCTED and CARD bone, AI-GENERATED cold blue, DRAWN cold blue hatched), with the share of each class.
- **Two live gauges:**
  - generated share against the **15%** cap (AI-GENERATED seconds over runtime; DRAWN is not counted, see Conflicts);
  - narration against the **25%** ceiling, with readings shown against their 30% floor.
  - Over the cap, the gauge turns burgundy and the render blocks at marks lint.
- **Source card:** archive, year, licence, mark, and `people` (yes means Ken Burns only, never image-to-video).

**Health verdict** (top of the rail): Healthy / Watch / Problem, the worst of five checks.

| Check | Healthy | Watch | Problem |
|---|---|---|---|
| GPU temperature | under 80 °C | 80 to 86 °C | 87 °C or more |
| Throttle reasons | none | power cap or sync boost | thermal slowdown |
| Free space, target drive | 25 GB or more | under 25 GB | under 10 GB |
| Target drive dirty flag (read at run start) | clean | set | |
| VRAM free | 1.5 GB or more | under 1.5 GB | under 0.5 GB |

The Machine panel names the GPU use to expect per stage. "Ken Burns motion runs on the CPU; GPU idle is expected." covers motion and assembly. "GPU-bound stage: high use is expected." covers narration and generation.

**Mock state:** a `doc calibrate` run (`cal-0003`), because no Partition screenplay exists. Its fixtures are real:
- ledger still S-001 for motion;
- Attlee's reading for narration;
- GRAMMAR 5.3's own example prompt ("a canal through flat wheat country, monsoon sky") for generation;
- the Census of India 1941 table for a DRAWN map;
- the record-is-silent card for CARD.

The reel is over the 15% cap on purpose: it is a fixture, and the gauge says so.

### 5e. Timing ledger and predictor (founder requirement: measured, never guessed)

**Timing ledger.** The studio appends one record per unit of work to `studio/timings.jsonl` on the laptop, never in git. It is pushed in summary only.

```json
{"v":1,"run":"r-0001","kind":"render|calibrate","stage":"generation","unit":"clip","unit_id":"G-03",
 "size":{"driver":"px_frames","value":32348160,"frames":81,"width":832,"height":480},
 "wall_s":198.4,"started_at":"2026-10-10T03:15:02+05:30",
 "machine":{"gpu":"NVIDIA GeForce RTX 4090 Laptop GPU","vram_total_mb":16376,"cpu":"<model>","driver":"<version>"},
 "model":{"name":"Wan 2.2 TI2V 5B","version":"<hash>"},
 "conditions":{"vram_used_mb_avg":13900,"temp_c_max":84,"throttle":["power_cap"],"gpu_other_procs":0,"cpu_load_avg":0.41},
 "outcome":"ok|failed|rejected"}
```

The size driver per stage is the unit that drives cost:
- narration and score: seconds of audio;
- motion: frames out;
- generation: width × height × frames;
- marks lint and assembly: seconds of film;
- subtitles: cues;
- scout: items.

**Predictor.**
- **Rate:** for each stage, cost per unit = the median (and p90) of `wall_s / size` over past `ok` records on this machine and model.
- **Live blend:** once the current run has done 3 or more units of that stage, the rate blends with the live rate, weighted by the units done.
- **Range:** the stage prediction is a range, `remaining size × [median, p90]`. The whole-run ETA is the sum of ranges, shown as clock times: "Finishes 03:18:01 to 03:18:46", with "from n past samples".
- **Fewer than 3 samples:** "first run: no estimate yet" plus the live rate, and the header says "Finishes: no estimate until <stage> has 3 units". Never a fake number.

**Lens UI.**
- **Pipeline rail:** stages not yet started show "predicted m:ss–m:ss, n samples". Finished stages show "0:52, predicted 0:48–1:05". A running stage shows its time so far and its prediction.
- **"How this is predicted":** a drill under the pipeline listing per stage the unit, median, p90, sample count (n) and live rate.
- **Deviation flag:** when the live rate departs from the history median by more than 25%, a quiet bone-ruled flag sits under that stage with the likely reason, read from the record's conditions: thermal or power-cap throttling, other GPU processes, a CPU load above 0.8, or a model change. Example: "31% slower than history. GPU at 84 °C with the power cap active during this stage."
- **Pipeline header:** "baselines calibrated <date> (cal-xxxx)".

**`doc calibrate`.** Runs every stage on small fixed fixtures:
- 1 still and 120 frames of motion;
- one 10-second reading;
- 20 s of score;
- one generation clip of 81 frames at 832×480, with its no-people check;
- a 22-second reel for lint, assembly and 3 subtitle tracks.

It writes `kind: "calibrate"` records, which seed the predictor. Run it on a fresh machine, after a driver or model change, and whenever a stage has fewer than 3 samples. The Lens flags baselines older than 30 days or from another model version.

### 5a. Data contract (studio → Lens, local)

SSE at `127.0.0.1:8765/events`; `/state` for reload; frames at `/frame/<seq>.jpg`; POST `/control` with a per-run token. Every event carries `v`, `type`, `run`, `seq` and `t`.

| type | fields |
|---|---|
| `run.start` | `kind` (render or calibrate), `film`, `title`, `stages[]`, `units[]` = {`id`, `stage`, `size`}, `predict` = {stage: {`median`, `p90`, `n`, `unit`}}, `baselines_at`, `duration_s`, `resumed_from` |
| `stage` | `stage` (scout, story, narration, score, motion, generation, marks, assembly, subtitles, publish), `status` (`start`, `done`, `skip`, `fail`), `wall_s`, `predicted` [lo, hi], `detail` |
| `unit.start` / `unit.done` | `stage`, `unit_id`, `size`, `wall_s`, `rate`, `deviation` (fraction vs median) and `reason` when above 0.25 |
| `frame` | `unit_id`, `frame`, `frames`, `tc_s`, `ms`, `mark` {`class`, `detail`}, `preview` |
| `gen.check` | `unit_id`, `no_people` (`pass` or `fail`), `frames_flagged[]`, `prompt_scan` (`pass` or `fail`) |
| `marks` | `track[]` = {`from_s`, `to_s`, `class`}, `share` {class: fraction}, `generated_share`, `narration_share`, `readings_share`, `violations[]` |
| `narration` | `lines[]` = {`speaker`, `side`, `kind`: narration, reading or archival, `at_s`, `dur_s`}, `peaks` |
| `gpu` (every 2 s) / `host` (every 5 s) | util, VRAM, temperature, power, throttle; CPU, RAM, disk free and dirty flag |
| `lock`, `log`, `error` {`stage`, `unit_id`, `message`, `fix`, `resume.command`}, `run.paused`, `run.end` | as in round 1 |

### 5b. Hosted push (laptop → `/studio`)

- **Cadence:** every 5 s while a run is active, one multipart POST with `Authorization: Bearer <push token>` (Worker secret `STUDIO_PUSH_TOKEN`).
- **Payload:** `state` (folded Lens state, including the marks track and gauges, the predictor table and the last 20 log lines; at most 16 KB) and `frame` (JPEG 640×360, at most 48 KB, only when it changed).
- **Size cap:** the Worker answers 413 to anything over 64 KB.
- **Storage:** D1 only: `studio_live` (one upserted row), `studio_thumbs` and `studio_sessions`.
- **Ceilings in code:** 6,000 pushes and 6,000 hosted GETs a day; 50 sessions a day. The worst case is 6.3% of D1 writes and 12.3% of Worker requests.
- **Freshness:** stale from 30 s without a push, offline from 10 min. Polling only while the tab is visible, pausing after 30 min idle.
- **Not public:** `/studio` has `noindex`, `robots.txt` disallows it, and no public link points to it.

### 5d. Studio sign-in

- **Account:** one admin account. `STUDIO_ADMIN_USER` and `STUDIO_PASSWORD_HASH` are Worker secrets. The hash is PBKDF2-SHA256 with a salt, at the highest iteration count that fits the free-plan CPU limit (measured in the build ticket).
- **Session cookie:** `studio_session`; `Path=/studio`; `HttpOnly`; `Secure`; `SameSite=Strict`; 12 h.
- **Rate limit:** 5 failures in 10 min per client lock that client for 60 s; 20 failures an hour lock sign-in for 15 min.
- **Copy:** Username, Password, Sign in. Wrong: "That username and password don't match." Locked: "Too many tries. Wait a minute." with the seconds left. No reset page: rotate the secret.

### 5c. Board card

One card per run, when it finishes or fails.
- **Rendered:** title, outcome, film runtime, marks result (every second marked, generated share within the cap), and wall time against the prediction.
- **Failed:** where it stopped, why, the resume command, and "To watch a render while it runs, open /studio. It is worth bookmarking: the Board only hears when a render ends."
- **Link:** `/studio`, or the film once published.

## Anti-slop checklist, per surface

| Surface | Template look? | Accents earned? | Numerals mono + tabular? | Copy clean? | Motion means state? | Space? |
|---|---|---|---|---|---|---|
| Screening room | Pass: a real slide, a credit-set title, a content note | Pass: safelight on credits only | Pass | Pass: sober, no toll as a headline | Pass | Pass |
| Film | Pass | Pass: amber only on the ARCHIVE rule, the credit and source links | Pass, including the mark's year | Pass | Pass | Pass |
| Sources | Pass: filters by mark, balance shown plainly | Pass: mark rules and source links | Pass | Pass: shortfalls in the record's own form | Pass | Pass |
| Corrections | Pass | Pass | Pass | Pass | Pass | Pass |
| Lens | Pass: control room | Pass: amber on the source credit and the ARCHIVE rule; blue on generated; forest done; burgundy over-cap and failed | Pass | Pass | Pass | Dense by design |
| Studio sign-in, Board card | Pass | Pass | Pass | Pass | Pass | Pass |

## Conflicts and open items

1. **DRAWN and the 15% cap.** GRAMMAR 2.6 caps "generated shots" without saying whether DRAWN counts. The design counts AI-GENERATED only, and shows DRAWN in the strip. GRAMMAR should say which.
2. **Mark text colour.** GRAMMAR 4 gives each class a hue and asks for 4.5:1 text on a 60% scrim. Coloured text can't do both over a bright frame, so the hue is a rule and the text is near-white. Confirm that reading.
3. **Small screens.** Burned-in marks and lower thirds shrink with the picture. On phones the 2.2% cap height is about 4.6 px. GRAMMAR's minimum is per frame, not per screen, so this complies, but it is hard to read on a phone.
4. **Chapter 5 title.** The treatment names chapter 5 "After the line"; the round-3 instruction called it "The recovery". The mocks follow the treatment.
5. **Missing ledgers.** The stills ledger is not written yet, and the readings' `side` comes from the ledger's own wording ("nominated by the Congress" or "by the Muslim League"). The research ledger needs an explicit `side` and `gender` per speaker (GRAMMAR 6.4).
6. **Build tickets:**
   - the contract check moves to `/f/partition-of-india`;
   - the subtitle font packages are added;
   - `/feedback` gains `when`, `how` and `item`;
   - `/studio` needs a charter amendment and `budget.yaml` lines.

## Round 4 fixes (G2 dry run)

- **Wording (B2).** "Read in full" is gone everywhere. The standing line is: "Every reading is word for word from its source, sometimes in part (marked ...)." It appears on `/`, in the film intro and in the Sources header, with "This film shows no bodies or killing." and "Voices are read by a computer; no recording is imitated."
- **End of the film (B3).** The film's last 8 s are the close's record-is-silent card, in the treatment's words: "The record holds no first-person account under an open licence by a Bengali or Bangladeshi witness, and women's words are short of the film's rule." / "Searched: The 1947 Partition Archive, Citizens Archive of Pakistan, SOAS, ADST, FRUS, Hansard, Internet Archive, Wikisource, sansad.in, na.gov.pk." Then the credits roll over black, with amber headings, generated from the sources file. Then the end card: Watch again · Sources · Correct something. All three are mocked in the film page's states.
- **Provenance at the player.**
  - Every control has a visible text label: Play, Subtitles, Marks, Chapters, Sound, Full screen. At 520 px and below, the labelled buttons wrap to their own row.
  - The subtitle menu starts closed.
  - A line under the controls says "No AI-generated images in this film. Voices are read by a computer; no recording is imitated." and links to "What the marks mean".
  - The Marks legend opens with the same sentence. It is one column, so it fits at 375 px, and RECONSTRUCTED reads: "Archive film or photographs changed in a way that matters: colourised, re-timed, stabilised, or enlarged by a computer model. The mark names the change. This film has none."
- **Partisan flag (BRAND-KIT 4, `motion.py` LT).**
  - The flag "Account of <publisher or side>, <year>" is the first line, above the rule, in Fraunces 300 italic at 3.6% of height.
  - The name steps down to the same 3.6%. Gaps tighten, and the source fits one line, which `motion.py` raises an error on.
  - The block top is 75.06% of height, inside GRAMMAR 4.1.
  - The same form is used for every partisan or government account: Darshan Singh (Government of West Punjab), Talib (SGPC) and Khosla (Fact Finding Organisation, Government of India).
- **Readings (Sources).** All 26 readings counted in the balance are listed, by chapter, totalling 396 s. Each one shows:
  - Speaker, side (marked where they are a woman's words), year, length in seconds and source;
  - the verbatim text, cut from the extract or the testimony ledger excerpt, checked by the generator;
  - for flagged accounts, the flag and the perspective line first;
  - Baldev Singh's source exactly as the testimony ledger has it, rendered from the ledger.

  The header links to "Whose words, and how long" and "All 26 readings".
- **No studio words in public copy.** "Pending", "slot", "cleared", "ledger", "read-by", "refrain", "end frame" and ledger ids are banned. The generator sweeps page text for them.
  - **Licence wording:** the DRAWN map's field names its facts' source in plain words (the Governor's telegram of 8 August 1947, printed in The Transfer of Power, vol. XII, HMSO 1983) and the drawing's licence (CC BY 4.0).
  - **Item links** read "The photograph at Wikimedia Commons" or "The film at the Internet Archive".
- **Corrections.** "Where in the film" takes the time or the shot's title as Sources lists it. The example text is "For example: you wrote 7:12, I think you meant 17:12."
