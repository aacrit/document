# CLAUDE.md

Product law for **Document** (`document`). The Agentique plugin (installed via
`.claude/settings.json`) runs this product's org. This file holds law only,
capped at 150 lines, no history.

## What this is

Document is a single-purpose web product served at `https://document.voidvision.org`.
See `CHARTER.md` for its surfaces and kill dates, and `contract.yaml` for what
"serving correctly" means in a script.

## Founding principle: show as was, not as is, and never tell (A0)

`films/GRAMMAR.md` A0 outranks every other rule, in the films and on the site.
- **Show as was:** the period's own footage, photographs, maps, documents,
  recordings, place names (Dacca, Bombay, Ceylon) and terms, quoted, never modernised.
- **Not as is:** each screenplay declares `as_of`, its story's horizon. Nothing
  said, shown or heard postdates it: no present-day facts, footage, maps, names or
  "would later"/"today". Ledger items are dated (`date`; a studio-made one
  `content_date` with `content_basis`); facts carry `facts: [<id>]` with
  `known_by` and `known_by_basis` in the film's `facts_ledger`.
- **Never tell:** the narrator gives no opinion, verdict or editorial adjective;
  the thesis lives in selection and order. Period quotes may judge (`quote: true`
  on a card, double quotes in narration). The film ends on one question asked from
  inside the time.
- Enforced by `studio/engine/aswas.py` at plan time and by the site's copy lint
  (`scripts/lib/show-as-was.mjs`), both reading `studio/show-as-was.json`.

## Fixed constraints

- **$0 running cost.** Everything fits the free tiers declared in `budget.yaml`.
- **No SSR.** Static frontend (`web/`, built to a generated dist directory)
  served by Workers Static Assets, plus one Worker (`worker/src/index.ts`)
  for `/e`, `/feedback`, `/healthz` and API routes. Only those routes run the
  Worker (`assets.run_worker_first` in `wrangler.jsonc`): a static asset must
  never cost an invocation. A new Worker route is added to that list.
- **Free quotas are account-wide.** Every D1 write path sits behind a day
  ceiling that writes nothing once reached (`worker/src/events.ts`), and the
  ceilings' worst case stays within the share `budget.yaml` states
  (`tests/hardening.test.ts` recomputes it from `wrangler.jsonc`). A new
  write path adds its ceiling and a line in `worker/src/config.ts`'s
  worstCaseDailyWrites. Every Worker request passes the per-client rate
  limit in `worker/src/guard.ts` (IPv6 per /64, never stored).
- **Web baseline.** Every response carries the security headers and CSP from
  `scripts/lib/csp.mjs` (static files through the build's `_headers`, the
  Worker through `worker/src/headers.ts`). POSTs are same-origin JSON only.
- **Data:** D1 only, schema in `migrations/0001_events.sql`. No R2, no KV
  writes, unless a charter amendment adds a surface that needs them.
- **Telemetry is aggregate counts only.** `/e` bumps a same-day, same-name
  counter in `event_counts`; there is no per-visit row, no anonymous id, and
  no cookie or local storage. No third-party analytics script (including
  Cloudflare Web Analytics) is added by default; adding one needs a charter
  amendment and a V3 check.
- **Success event.** `contract.yaml`'s success_event is the product's core
  action completing, sent from where it completes, and the one count
  `CHARTER.md`'s kill criteria name. Never page views or feedback.
  `scripts/lint-events.mjs` fails the gate otherwise.
- **Nothing loads from another origin.** Fonts are self-hosted
  (`design/fonts.css`); the CSP allows this origin only. Invocation logs are
  off. `web/privacy.html` says only what the code does: every claim is
  paired with its code in `tests/privacy-page.test.ts`, changed together.
- **No LLM feature** by default. One needs a charter amendment and the
  plugin's LLM add-on (free providers under a daily cap), never the Claude
  subscription.
- **Design:** `design/tokens.css` is the only file that may define a color.
  Ink & Momentum grammar is law; see the plugin's `ink-and-momentum` skill.
- **Production deploys** only via the plugin's `/release` skill, only from a
  release/* tag. This repo has no deploy workflow.

## Non-negotiables

1. No merge to `main` without a green `gate` job (`.github/workflows/gate.yml`).
2. Every ticket maps to a `CHARTER.md` row (see the plugin's `/ship` skill).
3. Secrets are never tracked; see `.githooks/pre-commit`.
4. Reports go to a gitignored reports directory or the Board page, never the repo root.
5. `/e` accepts only the event names `contract.yaml` lists under events.allowed.

## Commands

- `npm run dev`: Vite dev server plus `wrangler dev`.
- `npm run build`: production build to dist/, build tag injected. It also writes the installable app: the manifest,
  icons from the logomark (`scripts/lib/pwa.mjs`) and the service worker (`scripts/lib/sw.mjs`: never caches films, captions,
  Range requests or sources.json).
- Films: `films.json` is the registry (slug, title, status live or coming, caption tracks with their review
  status). The build writes the home page and every live film's pages from `web/templates/` (generated,
  gitignored; `scripts/lib/films.mjs`), and `contract.yaml`'s `films` block is expanded once per film.
- `npm run gate`: the full gate (typecheck, build, tests, studio-test, lint-size,
  lint-workflows, lint-design, lint-docs, lint-events, gate-selftest). Must pass before
  any merge. studio-test runs pytest on `studio/tests` and needs Python 3.12 with
  numpy, pillow, soundfile, pytest and fonttools, plus ffmpeg (`DOCUMENT_PYTHON` picks the interpreter).
- `python -m studio.engine.render <film dir>`: render a screenplay v2 to a 1080p master at the film's rate (24, or 30000/1001: GRAMMAR A44);
  every run is journaled (`studio/engine/journal.py`), issues go to `docs/ENGINE-LOG.md`. Cut spans of long reels go to
  `<film>/cache/spans`, or to `DOCUMENT_SPANS_CACHE` when set (keep them off a near-full system disk). The plan judges the takes'
  own sound lints (`render.take_lints`) before any frame, their records cached in `<film>/cache/takes` or `DOCUMENT_TAKES_CACHE`.
- `python -m studio.engine.render <film dir> --shots <id>..<id> [--out <dir>]`: a check render of that span (whole film planned and linted, the full mix cut to it) to `<out>/master.shots-<a>-<b>.mp4`.
  Not read-only: it writes the same film-folder caches a full render does (bounds, spans, the A46 levels record).
- `python -m studio.engine.score <film dir> [--wavs <dir>]`: the house score standard (GRAMMAR A29) checked offline on the
  film's cue WAVs as its screenplay places them, with no mix rendered; `--wavs` swaps in a re-scored set of cues.
- `python -m studio.engine.levels --check <film dir> [--json <file>]`: GRAMMAR A46's automatic black floor read-only on a
  film's screenplay and ledgers, with no plan: which stills are floored, which opt out, and the grade-jump warnings.
- `python -m studio.engine.voicing measure <film dir>... [--write]`: each reader voice's EQ (GRAMMAR A38 refined), measured
  on its takes in those films; `--write` rebuilds the house table `studio/reader-eq.json` (never edited by hand).
- `python -m studio.engine.clips check <film dir>`: GRAMMAR A33 (clip integrity) read-only on a screenplay; `natural-out`,
  `breathe`, `snap-in` and `plan <film dir> <requests.json>` choose in and out points on a clip's measured cuts and words
  (sidecars in `<film>/cache/bounds/`), and `lipsync` measures a talking-head clip's `av_offset_ms` (`--write` records it).
- `python -m studio.engine.captions <render dir>`: write the English captions (captions-en.vtt) from the
  render's resolved screenplay (`studio/engine/captions.py`); they go to R2 with the film, poster and sources.json.
- `python -m studio.engine.description --check-external <render dir>/sources.json`: advisory, for an upload to an outside
  platform by hand (GRAMMAR A56); exits non-zero, saying what, while description.txt leaves anything out. It gates nothing.
- `python -m studio.engine.sheets <film dir> [--out <dir>] [--chapter <id>] [--skip-sound-lints]`: grid-overlay
  contact sheets (no render), one PNG per chapter with the camera's own window, zones and ROI boxes per stop.
- `node scripts/release-film.mjs <render dir>/master.mp4 [--trailer <file>] [--out <dir>] [--dry-run]`: the post-render
  release in order (--sources-only, 720p web encode, poster and publish packet, captions check, R2 upload with
  sources.json last, hashes); `--dry-run` prints every command and runs none. The trailer is optional (none declared,
  none shown). The packet defaults to D:/document-media/web-packet/<slug>; a dirty D: (`fsutil dirty query`) or a
  failed query refuses. Pages still change only through `/release`.
- `npm run contract -- --url <url>`: run `contract.yaml` against a live URL.
  Checks marked `requires: deployed` show SKIP on localhost and must PASS
  on the preview.
- `npm run scan-history`: scan full git history for leaked secrets.
