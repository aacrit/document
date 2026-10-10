// A minimal in-memory stand-in for the D1Database surface the Worker code
// uses (prepare().bind().run()/.first()). Good enough for routing and
// validation tests; not a SQL engine. tests/helpers/sqlite-d1.ts runs the
// Worker's real SQL on real SQLite where the SQL itself is what is tested.

export interface MockEventCountRow {
  day: string;
  name: string;
  count: number;
}

export interface MockFeedbackRow {
  text: string;
  page: string | null;
  ts: number;
}

export interface MockD1 {
  db: D1Database;
  eventCounts: MockEventCountRow[];
  feedback: MockFeedbackRow[];
}

export function createMockD1(): MockD1 {
  const eventCounts: MockEventCountRow[] = [];
  const feedback: MockFeedbackRow[] = [];

  // Mirrors `INSERT ... ON CONFLICT DO UPDATE SET count = count + 1 WHERE
  // event_counts.count < ? RETURNING count` (events.ts): past the ceiling
  // nothing is written and no row comes back (null).
  function upsertEventCount(args: unknown[]): number | null {
    const [day, name, ceiling] = args as [string, string, number];
    const existing = eventCounts.find((e) => e.day === day && e.name === name);
    if (existing) {
      if (existing.count >= ceiling) return null;
      existing.count += 1;
      return existing.count;
    }
    eventCounts.push({ day, name, count: 1 });
    return 1;
  }

  function prepare(sql: string) {
    return {
      bind(...args: unknown[]) {
        return {
          async run() {
            if (sql.startsWith("INSERT INTO event_counts")) {
              upsertEventCount(args);
            } else if (sql.startsWith("INSERT INTO feedback")) {
              feedback.push({ text: args[0] as string, page: (args[1] as string | null) ?? null, ts: args[2] as number });
            } else if (sql.startsWith("DELETE FROM feedback")) {
              // "DELETE ... WHERE id IN (SELECT id ... WHERE ts < ? ORDER BY ts LIMIT ?)": oldest first, at most `limit`.
              const cutoff = args[0] as number;
              const limit = typeof args[1] === "number" ? args[1] : Infinity;
              const doomed = feedback.filter((f) => f.ts < cutoff).sort((a, b) => a.ts - b.ts).slice(0, limit);
              for (const f of doomed) feedback.splice(feedback.indexOf(f), 1);
              return { success: true, meta: { changes: doomed.length } } as unknown as D1Result;
            }
            return { success: true, meta: { changes: 1 } } as unknown as D1Result;
          },
          async first<T = unknown>(): Promise<T | null> {
            if (sql.startsWith("INSERT INTO event_counts")) {
              const count = upsertEventCount(args);
              return (count === null ? null : { count }) as unknown as T;
            }
            if (sql.includes("FROM event_counts")) {
              const [day, name] = args as [string, string];
              const row = eventCounts.find((e) => e.day === day && e.name === name);
              return { count: row?.count ?? 0 } as unknown as T;
            }
            return null;
          },
          async all<T = unknown>() {
            return { results: [] as T[], success: true, meta: {} } as unknown as D1Result<T>;
          },
        };
      },
    };
  }

  const db = { prepare } as unknown as D1Database;
  return { db, eventCounts, feedback };
}

export function createMockAssets(files: Record<string, string> = {}): Fetcher {
  return {
    async fetch(input: RequestInfo | URL): Promise<Response> {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      const pathname = new URL(url).pathname.replace(/^\//, "");
      const content = files[pathname];
      if (content === undefined) return new Response("not found", { status: 404 });
      return new Response(content, { status: 200, headers: { "content-type": "text/html" } });
    },
  } as unknown as Fetcher;
}
