// Aggregate day-counter helpers. A count identifies no one: one row per
// (UTC day, event name) with a running total.

// A UTC calendar day as `YYYY-MM-DD`. This is the only "when" a count
// carries; there is no per-visit timestamp to correlate with anything.
export function utcDay(now: number): string {
  return new Date(now).toISOString().slice(0, 10);
}

// One statement, atomic on D1: insert the day's first count, or add one to
// it only while it is still under `ceiling`. The `WHERE` on the DO UPDATE
// makes the write itself conditional, so once the count reaches the ceiling
// nothing is written at all and `RETURNING` yields no row. A counter
// therefore never passes its ceiling, and a request past it costs a D1 read
// but no row write. (Reading the count first and upserting after, as the
// template once did, lets concurrent requests pass the ceiling; incrementing
// first and comparing after, as Rollbook once did, writes on every request
// past it.)
export const COUNT_UNDER_CEILING_SQL =
  "INSERT INTO event_counts (day, name, count) VALUES (?, ?, 1) ON CONFLICT(day, name) DO UPDATE SET count = count + 1 WHERE event_counts.count < ? RETURNING count";

/** Counts one `name` for `day` if today's count is under `ceiling`. Returns the new count, or null when the ceiling was already reached (nothing written). */
export async function incrementUnderCeiling(db: D1Database, day: string, name: string, ceiling: number): Promise<number | null> {
  const row = await db.prepare(COUNT_UNDER_CEILING_SQL).bind(day, name, ceiling).first<{ count: number }>();
  return row ? row.count : null;
}
