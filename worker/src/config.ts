// Mirrors contract.yaml's `events.allowed` and `events.server_only`.
// tests/contract-events.test.ts parses contract.yaml and asserts both lists
// stay in sync with these, so the Worker never parses YAML at request time.
//
// "film_completed" is the success event: a viewer reaches the final frame
// of a film. It is the one thing the kill criteria count (contract.yaml,
// CHARTER.md, web/src/main.ts). scripts/lint-events.mjs checks it is sent.
export const ALLOWED_EVENTS = [
  "page_view",
  "film_completed",
  // A viewer opens an archive's item link on a film's Sources page: the
  // Sources surface's justifying event (CHARTER.md).
  "source_opened",
  // Server-only (see SERVER_ONLY_EVENTS): each is counted only by the
  // Worker code that does the thing being counted.
  "feedback_received",
  "rate_limiter_error",
] as const;

export type AllowedEvent = (typeof ALLOWED_EVENTS)[number];

// Event names /e rejects with 400 even though they are allowed names: a
// client posting one directly could inflate the count, and exhaust the
// matching daily ceiling, without doing the thing it counts.
export const SERVER_ONLY_EVENTS = ["feedback_received", "rate_limiter_error"] as const;

/** The event names a client may send through /e: the allowed list minus the server-only ones. */
export const CLIENT_EVENTS = ALLOWED_EVENTS.filter((n) => !(SERVER_ONLY_EVENTS as readonly string[]).includes(n));

// Every daily ceiling below is enforced by one conditional upsert
// (events.ts's incrementUnderCeiling): a counter under its ceiling is
// incremented, and one at its ceiling is left alone, so nothing is written
// past a ceiling. All are aggregate and account-wide; none tracks a person.

// Per-day, per-client-event-name ceiling on `event_counts` increments (env
// EVENT_DAILY_CEILING overrides it). Past it, /e writes nothing and answers
// 204. Every client event name has its own ceiling, so together they must
// fit this product's share of the account's D1 writes (see
// worstCaseDailyWrites below). 3,000 is ~3 page views per visitor at the
// 1,000-visitors-a-day estimate (screening room, film, sources), and far
// above any day's film_completed or source_opened. It was 4,000 with two
// client events; source_opened made three, and 3 x 4,000 would take the
// worst case past budget.yaml's 15% share.
export const DEFAULT_EVENT_DAILY_CEILING = 3_000;

// Per-day ceiling on accepted feedback messages (env FEEDBACK_DAILY_CEILING
// overrides it), counted as the server-only `feedback_received`. Past it,
// /feedback answers 429 and stores nothing. With the byte cap and 90-day
// retention it bounds the feedback table: 100 x 90 = 9,000 rows of at most
// ~4.3 KB, about 39 MB (budget.yaml's d1_storage_mb row).
export const DEFAULT_FEEDBACK_DAILY_CEILING = 100;

// A rate-limit binding that throws fails open and is counted as the
// aggregate `rate_limiter_error`, up to this many a day.
export const RATE_LIMITER_ERROR_DAILY_CEILING = 100;

// Feedback text is capped in UTF-8 bytes, which is what D1 stores, not in
// UTF-16 code units (JavaScript's .length).
export const MAX_FEEDBACK_TEXT_BYTES = 4_000;
export const MAX_FEEDBACK_PAGE_CHARS = 256;

// Raw body caps, checked before JSON.parse (worker/src/http.ts). `/e`'s
// body is only `{"name":"<event>"}`.
export const MAX_EVENT_BODY_BYTES = 256;
export const MAX_FEEDBACK_BODY_BYTES = 16 * 1024;

// Feedback retention deletes in bounded batches, so a purge never writes
// more than its batch: up to FEEDBACK_PURGE_ON_INSERT rows before every
// accepted message, and FEEDBACK_PURGE_DAILY_MULTIPLE times the feedback
// day ceiling on each client event's first count of a day. That keeps up by
// construction: rows expire at most FEEDBACK_DAILY_CEILING a day (no more
// were stored on any day), and any day the site is used purges at least
// twice that. With daily visits nothing is older than RETENTION_DAYS plus
// under a day; after unvisited days (nothing runs then) a backlog forms and
// each visited day shrinks it by at least a ceiling until it is gone.
// tests/hardening.test.ts simulates both.
export const FEEDBACK_PURGE_ON_INSERT = 10;
export const FEEDBACK_PURGE_DAILY_MULTIPLE = 2;
export const RETENTION_DAYS = 90;

// --- This product's share of the account's D1 writes ---
//
// D1's free tier allows 100,000 rows written a day across the whole
// Cloudflare account, shared by every product on it. Each line below is a
// counter's ceiling times the most rows one counted request can write,
// index entries included (D1 counts a write to an indexed column's index as
// another row). Past a ceiling nothing is written, so the total is the worst
// case a day of abuse can reach. budget.yaml's d1_rows_written_per_day row
// states it and the share of the account it may use; tests/hardening.test.ts
// recomputes it from wrangler.jsonc's vars and checks both.
export const ACCOUNT_D1_WRITES_PER_DAY = 100_000;

export interface Ceilings {
  event: number;
  feedback: number;
}

export function worstCaseDailyWrites(c: Ceilings): { lines: { what: string; rows: number }[]; total: number } {
  // A counter's first count of a day inserts its row (row + primary-key
  // index = 2); every later count updates `count`, which no index covers (1).
  const counter = (ceiling: number) => ceiling + 1;
  const lines = [
    // Client events: the counter, plus one feedback purge of up to
    // FEEDBACK_PURGE_DAILY_MULTIPLE x the feedback ceiling on each name's
    // first count of the day (2 rows each: the row and its ts index entry).
    { what: "/e client events", rows: CLIENT_EVENTS.length * (counter(c.event) + c.feedback * FEEDBACK_PURGE_DAILY_MULTIPLE * 2) },
    // Feedback: counter, purge batch (2 each), insert (row + ts index).
    { what: "POST /feedback", rows: counter(c.feedback) + c.feedback * (FEEDBACK_PURGE_ON_INSERT * 2 + 2) },
    { what: "rate_limiter_error", rows: counter(RATE_LIMITER_ERROR_DAILY_CEILING) },
  ];
  return { lines, total: lines.reduce((sum, l) => sum + l.rows, 0) };
}
