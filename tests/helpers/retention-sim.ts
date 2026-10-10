// Simulates days of feedback retention on real SQLite (sqlite-d1.ts), with
// the Worker's own handlers and a fake clock. Shared by tests/hardening.test.ts
// and tests/privacy-page.test.ts, so the privacy page's retention claim is
// paired with this behavior rather than with a constant.
//
// Scenario: FEEDBACK_DAILY_CEILING is 100; days 0-4 each store a burst of
// 100 messages late in the day; on each day `visitOn` allows, one page_view
// arrives just after midnight (a client event's first count of the day,
// which runs the daily purge). Only page_view is sent: one client event
// name, one daily purge, is the slowest case.

import { vi } from "vitest";
import { handleEvent, handleFeedback, type Env } from "../../worker/src/index";
import { createSqliteD1 } from "./sqlite-d1";
import { createMockAssets } from "./mock-d1";

const DAY_MS = 86_400_000;
const START = Date.parse("2026-01-01T00:00:00Z");
const RETENTION_MS = 90 * DAY_MS;
const at = (day: number, hour: number) => START + day * DAY_MS + hour * 3_600_000;

export interface SimDay {
  day: number;
  visited: boolean;
  rows: number;
  /** Rows older than 90 days at the end of the day. */
  expired: number;
  /** Age in days of the oldest row at the end of the day (0 when empty). */
  oldestAgeDays: number;
}

function post(pathname: string, body: unknown): Request {
  return new Request(`https://product.example${pathname}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function simulateRetention(opts: { visitOn: (day: number) => boolean; lastDay: number; burstDays?: number; ceiling?: number }): Promise<SimDay[]> {
  const ceiling = opts.ceiling ?? 100;
  const burstDays = opts.burstDays ?? 5;
  const d1 = await createSqliteD1();
  const env: Env = { DB: d1.db, ASSETS: createMockAssets(), FEEDBACK_DAILY_CEILING: String(ceiling) };
  const out: SimDay[] = [];
  vi.useFakeTimers({ toFake: ["Date"] });
  try {
    for (let day = 0; day <= opts.lastDay; day++) {
      const visited = opts.visitOn(day);
      if (visited) {
        vi.setSystemTime(at(day, 0.5));
        const res = await handleEvent(post("/e", { name: "page_view" }), env);
        if (res.status !== 202) throw new Error(`day ${day}: /e answered ${res.status}`);
      }
      if (day < burstDays) {
        for (let i = 0; i < ceiling; i++) {
          vi.setSystemTime(at(day, 23) + i * 1000);
          const res = await handleFeedback(post("/feedback", { text: `b${day}-${i}` }), env);
          if (res.status !== 202) throw new Error(`day ${day}: /feedback answered ${res.status}`);
        }
      }
      const end = at(day, 24);
      const oldest = d1.query<{ ts: number }>("SELECT ts FROM feedback ORDER BY ts LIMIT 1")[0];
      out.push({
        day,
        visited,
        rows: d1.query<{ n: number }>("SELECT COUNT(*) AS n FROM feedback")[0].n,
        expired: d1.query<{ n: number }>("SELECT COUNT(*) AS n FROM feedback WHERE ts < ?", end - RETENTION_MS)[0].n,
        oldestAgeDays: oldest ? (end - oldest.ts) / DAY_MS : 0,
      });
    }
  } finally {
    vi.useRealTimers();
  }
  return out;
}

/**
 * What the privacy page claims, and all it claims: when the site goes
 * unvisited, deletion falls behind (nothing runs on a day nobody visits),
 * and it catches up once visits resume. Catch-up is provable: once every
 * burst row has expired, each visited day's purge (2 x the ceiling) deletes
 * at least a ceiling's worth of the backlog, or all of it, so the backlog
 * reaches zero. No bound in days is claimed: repeated or sparse idle
 * stretches break any simple one.
 */
export interface IdleScenario {
  name: string;
  burstDays: number;
  /** Which days before `dailyFrom` get a visit. */
  visitOn: (day: number) => boolean;
  /** From this day on, a visit every day; after every burst row has expired. */
  dailyFrom: number;
}

export async function runIdleScenario(s: IdleScenario, ceiling = 100) {
  const lastDay = s.dailyFrom + 100;
  const days = await simulateRetention({ visitOn: (day) => day >= s.dailyFrom || s.visitOn(day), lastDay, burstDays: s.burstDays, ceiling });
  const backlog = days[s.dailyFrom - 1].expired;
  let clearedWithinVisitedDays = Infinity;
  for (const d of days.slice(s.dailyFrom)) {
    if (d.expired === 0) {
      clearedWithinVisitedDays = d.day - s.dailyFrom + 1;
      break;
    }
  }
  return { days, backlog, clearedWithinVisitedDays };
}

/** Bursts at the ceiling whose rows expire while visits are missing or sparse. */
export const IDLE_SCENARIOS: IdleScenario[] = [
  { name: "5-day burst, 38 days unvisited", burstDays: 5, visitOn: (d) => !(d >= 60 && d <= 97), dailyFrom: 98 },
  { name: "30-day burst, 60 days unvisited", burstDays: 30, visitOn: (d) => !(d >= 60 && d <= 119), dailyFrom: 120 },
  { name: "90-day burst, 90 days unvisited", burstDays: 90, visitOn: (d) => !(d >= 90 && d <= 179), dailyFrom: 180 },
  { name: "30-day burst, two unvisited stretches", burstDays: 30, visitOn: (d) => !((d >= 60 && d <= 89) || (d >= 100 && d <= 129)), dailyFrom: 130 },
  { name: "30-day burst, one visit in three days while it expires", burstDays: 30, visitOn: (d) => d < 60 || d % 3 === 0, dailyFrom: 120 },
];
