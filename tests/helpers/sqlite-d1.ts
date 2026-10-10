// A D1Database stand-in backed by real SQLite (node:sqlite) with the repo's
// real migrations applied. Unlike mock-d1.ts (string matching, no SQL
// engine), this runs the Worker's actual SQL, so a test can prove what a
// statement does on SQLite itself: an upsert's WHERE clause, RETURNING with
// no row, a CHECK constraint. Only the surface the Worker uses is here:
// prepare().bind().first()/run()/all(), and batch().

import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

export interface SqliteD1 {
  db: D1Database;
  /** Runs a raw query for assertions. */
  query<T = Record<string, unknown>>(sql: string, ...args: unknown[]): T[];
}

export async function createSqliteD1(): Promise<SqliteD1> {
  const { DatabaseSync } = await import("node:sqlite");
  const sqlite = new DatabaseSync(":memory:");
  const dir = path.join(root, "migrations");
  for (const f of readdirSync(dir).sort()) sqlite.exec(readFileSync(path.join(dir, f), "utf8"));

  type Arg = string | number | null | bigint | Uint8Array;

  function statement(sql: string, args: Arg[]) {
    const returnsRows = /^\s*select\b/i.test(sql) || /\breturning\b/i.test(sql);
    const self = {
      bind(...bound: unknown[]) {
        return statement(sql, bound as Arg[]);
      },
      async first<T = unknown>(): Promise<T | null> {
        const row = sqlite.prepare(sql).get(...args);
        return (row ?? null) as T | null;
      },
      async all<T = unknown>() {
        const rows = sqlite.prepare(sql).all(...args);
        return { results: rows as T[], success: true, meta: {} } as unknown as D1Result<T>;
      },
      async run() {
        if (returnsRows) {
          const rows = sqlite.prepare(sql).all(...args);
          return { results: rows, success: true, meta: { changes: rows.length } } as unknown as D1Result;
        }
        const info = sqlite.prepare(sql).run(...args);
        return { success: true, meta: { changes: Number(info.changes) } } as unknown as D1Result;
      },
    };
    return self;
  }

  async function batch(statements: { run: () => Promise<D1Result> }[]) {
    const out: D1Result[] = [];
    sqlite.exec("BEGIN");
    try {
      for (const s of statements) out.push(await s.run());
      sqlite.exec("COMMIT");
    } catch (err) {
      sqlite.exec("ROLLBACK");
      throw err;
    }
    return out;
  }

  const db = { prepare: (sql: string) => statement(sql, []), batch } as unknown as D1Database;
  return {
    db,
    query: <T,>(sql: string, ...args: unknown[]) => sqlite.prepare(sql).all(...(args as Arg[])) as T[],
  };
}
