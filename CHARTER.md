# Charter

Purpose: history shown as it was seen at the time, never as it is now, and never told what to think (founding principle A0, `films/GRAMMAR.md`; founder, 2026-10-11). Every surface below, film and page alike, follows it.

At most 5 surfaces for v1. Any surface added later needs a charter amendment.

| Surface | Why | Justifying user event | Kill date |
|---|---|---|---|
| Screening room `/` | The current film, poster, films in production and past films | `film_completed` | 2027-05-31 |
| Film `/f/<slug>` | Our own HLS player (R2), chapters, captions, transcript; no YouTube embed, no cookies | `film_completed` | 2027-05-31 |
| Sources `/f/<slug>/sources` | Every shot → archive, item, licence, credit, and what we did to it (pan, crop, animated) | `source_opened` | 2027-05-31 |
| Corrections `/f/<slug>/correct` | People who know the place flag errors; fixes are listed in the credits | `correction_submitted` | 2027-05-31 |
| Studio (local CLI `doc`, `studio/`) + Director's Lens | Dossier → Fable screenplay → narration → score → motion → assembly → publish packet; the Director's Lens is the founder's private render view: live on localhost, and at `/studio` behind a single admin login fed by ~5 s pushes from the laptop; never linked from the public site | `film_published` | 2027-04-30 |
| `/privacy.html` | Disclosure for the aggregate-count telemetry, the feedback form and the rate limit; linked from the home page | `page_view` (same page load as home) | tied to the product's own kill date |

Amended 2026-10-11: the screening room also lists the films in production, by title, dates and status, after the founder asked for the second film to go live end to end ("Lets finish the live version end to end for this as well.", in chat; docs/DECISIONS.md). It remains one surface.

## Kill criteria

Aggregate counts in D1 (`/e`'s `event_counts`), plus YouTube view counts read daily from the YouTube Data API (`videos.list?part=statistics`) into D1; nothing per person. Dates assume the Partition pilot is public by 2027-01-31 and are re-dated at G3.

- 2027-01-31: the Partition pilot has not passed G3 → archive (the studio cannot make the film).
- Pilot + 90 days: fewer than 500 `film_completed` in total **and** fewer than 10,000 YouTube views → archive.

Reading the counts: every count is capped by its daily ceiling, and a browser-sent one can be inflated by anyone who posts to `/e`. So the G4 packet shows each count's day-level spikes (days at or near a ceiling, or far above the usual day) next to the totals, and a total carried by a spike is read as suspect, not as progress.

## Not in v1

- Generated people or reenactment scenes; cloned voices of real people. Image-to-video only for atmosphere on real photographs, labelled.
- Automatic public YouTube publishing (uploads stay private until the API audit passes).
- void news and void history strands (later, by founder decision).
- Money of any kind, Shorts, dubbing, comments, viewer place requests, accounts.
- Any product-side LLM call. Screenplays are written by Fable in a Claude Code session; the pipeline calls no LLM.
- Anything else the brief marked "Not in v1" (see `reports/briefs/document.md`, gitignored, on the Chief of Staff's side).

## Workflows: 3 (gate, verify-production, branch-prune)
