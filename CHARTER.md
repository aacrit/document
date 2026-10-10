# Charter

At most 5 surfaces for v1. Any surface added later needs a charter amendment.

| Surface | Why | Justifying user event | Kill date |
|---|---|---|---|
| Screening room `/` | The current portrait, poster, trailer and past films. At Spark it serves the 60–90 s Maxwell Street sketch | `film_completed` | 2027-05-31 |
| Film `/f/<place>` | Our own HLS player (R2), chapters, captions, transcript; no YouTube embed, no cookies | `film_completed` | 2027-05-31 |
| Sources `/f/<place>/sources` | Every shot → archive, item, licence, credit, and what we did to it (pan, crop, animated) | `source_opened` | 2027-05-31 |
| Corrections `/f/<place>/correct` | People who know the place flag errors; fixes are listed in the credits | `correction_submitted` | 2027-05-31 |
| Studio (local CLI `doc`, `studio/`) + Director's Lens | Dossier → Fable screenplay → narration → score → motion → assembly → publish packet; the Director's Lens is a local live view that opens during every render (stage, GPU and VRAM, shots done of total, frames appearing as they render, narration waveform, ledger source per shot) | `film_published` | 2027-04-30 |
| `/privacy.html` | Disclosure for the aggregate-count telemetry, the feedback form and the rate limit; linked from the home page | `page_view` (same page load as home) | tied to the product's own kill date |

## Kill criteria

Aggregate counts in D1 (`/e`'s `event_counts`), plus YouTube view counts read daily from the YouTube Data API (`videos.list?part=statistics`) into D1; nothing per person. Dates assume the first public film ships by 2027-01-31 and are re-dated at G3.

- 2027-04-30: fewer than 4 `film_published` in total → archive (the studio can't hold the cadence).
- 2027-05-31: fewer than 300 `film_completed` in total **and** fewer than 5,000 YouTube views across all films → archive.

Reading the counts: every count is capped by its daily ceiling, and a browser-sent one can be inflated by anyone who posts to `/e`. So the G4 packet shows each count's day-level spikes (days at or near a ceiling, or far above the usual day) next to the totals, and a total carried by a spike is read as suspect, not as progress.

## Not in v1

- Generated people or reenactment scenes; cloned voices of real people. Image-to-video only for atmosphere on real photographs, labelled.
- Automatic public YouTube publishing (uploads stay private until the API audit passes).
- void news and void history strands (later, by founder decision).
- Money of any kind, Shorts, dubbing, comments, viewer place requests, accounts.
- Any product-side LLM call. Screenplays are written by Fable in a Claude Code session; the pipeline calls no LLM.
- Anything else the brief marked "Not in v1" (see `reports/briefs/document.md`, gitignored, on the Chief of Staff's side).

## Workflows: 3 (gate, verify-production, branch-prune)
