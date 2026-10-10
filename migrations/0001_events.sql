-- First-party telemetry: aggregate daily counts only. No identifiers, no
-- per-visit rows, no cookies, no localStorage. `event_counts` holds one row
-- per (day, event name) with a running total; `day` is a UTC `YYYY-MM-DD`
-- string. A count of this shape identifies no one, so it has no retention
-- limit and is kept indefinitely. `feedback` stays free text + page + a
-- timestamp, with no identifiers, and rows older than 90 days are deleted in
-- bounded batches: before every feedback insert, and on each client event's
-- first count of a day (up to twice the feedback day ceiling, so the purge
-- keeps up), plus by the `scheduled` handler in worker/src/index.ts if a cron
-- trigger is ever wired up for this product.

CREATE TABLE IF NOT EXISTS event_counts (
  day TEXT NOT NULL,
  name TEXT NOT NULL,
  count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, name)
);

CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY,
  text TEXT NOT NULL,
  page TEXT,
  ts INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_feedback_ts ON feedback (ts);
