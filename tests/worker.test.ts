import { describe, expect, it } from "vitest";
import { handleEvent, handleFeedback, handleHealthz, isAllowedEvent, purgeOldFeedback, type Env } from "../worker/src/index";
import { CLIENT_EVENTS, SERVER_ONLY_EVENTS } from "../worker/src/config";
import { createMockD1, createMockAssets } from "./helpers/mock-d1";

function makeEnv(overrides: Partial<Env> = {}): Env {
  const { db } = createMockD1();
  return { DB: db, ASSETS: createMockAssets(), BUILD_TAG: "test-build", ...overrides };
}

function postJson(path: string, body: unknown): Request {
  return new Request(`http://internal${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

// The product's success event, whatever it is named (the template ships a
// placeholder; the product renames it at Spark).
const SUCCESS = CLIENT_EVENTS.find((n) => n !== "page_view")!;

describe("isAllowedEvent", () => {
  it("accepts events from contract.yaml's allowed list", () => {
    expect(isAllowedEvent("page_view")).toBe(true);
    expect(isAllowedEvent(SUCCESS)).toBe(true);
  });

  it("rejects anything else", () => {
    expect(isAllowedEvent("literally_anything")).toBe(false);
    expect(isAllowedEvent(123)).toBe(false);
    expect(isAllowedEvent(undefined)).toBe(false);
  });
});

describe("/e via handleEvent", () => {
  it("accepts an allowed event and increments today's count", async () => {
    const db = createMockD1();
    const res = await handleEvent(postJson("/e", { name: "page_view" }), makeEnv({ DB: db.db }));
    expect(res.status).toBe(202);
    expect(db.eventCounts).toHaveLength(1);
    expect(db.eventCounts[0]).toMatchObject({ name: "page_view", count: 1 });
  });

  it("rejects an event not in the allowed list", async () => {
    const res = await handleEvent(postJson("/e", { name: "delete_everything" }), makeEnv());
    expect(res.status).toBe(400);
    expect(((await res.json()) as { error: string }).error).toBe("event_not_allowed");
  });

  it("rejects server-only events, so a client cannot inflate them or spend their ceilings", async () => {
    for (const name of SERVER_ONLY_EVENTS) {
      const res = await handleEvent(postJson("/e", { name }), makeEnv());
      expect(res.status, name).toBe(400);
    }
  });

  it("rejects extra fields, so nobody can smuggle an identifier in", async () => {
    const res = await handleEvent(postJson("/e", { name: "page_view", anon_id: "nope" }), makeEnv());
    expect(res.status).toBe(400);
    expect(((await res.json()) as { error: string }).error).toBe("unexpected_fields");
  });

  it("rejects props alongside a valid name", async () => {
    const res = await handleEvent(postJson("/e", { name: SUCCESS, props: { a: 1 } }), makeEnv());
    expect(res.status).toBe(400);
  });

  it("gives a count of 2 for two posts of the same event on the same day, separate per name", async () => {
    const db = createMockD1();
    const env = makeEnv({ DB: db.db });
    await handleEvent(postJson("/e", { name: "page_view" }), env);
    await handleEvent(postJson("/e", { name: "page_view" }), env);
    await handleEvent(postJson("/e", { name: SUCCESS }), env);
    expect(db.eventCounts.find((r) => r.name === "page_view")?.count).toBe(2);
    expect(db.eventCounts).toHaveLength(2);
  });

  it("stops incrementing past the daily ceiling and returns 204 with no body", async () => {
    const db = createMockD1();
    const env = makeEnv({ DB: db.db, EVENT_DAILY_CEILING: "1" });
    expect((await handleEvent(postJson("/e", { name: "page_view" }), env)).status).toBe(202);
    const second = await handleEvent(postJson("/e", { name: "page_view" }), env);
    expect(second.status).toBe(204);
    expect(await second.text()).toBe("");
    expect(db.eventCounts[0].count).toBe(1);
  });

  it("rejects invalid JSON and oversized bodies", async () => {
    const bad = new Request("http://internal/e", { method: "POST", body: "not json" });
    expect((await handleEvent(bad, makeEnv())).status).toBe(400);
    expect((await handleEvent(postJson("/e", { name: "x".repeat(400) }), makeEnv())).status).toBe(413);
  });
});

describe("/feedback via handleFeedback", () => {
  it("accepts feedback and stores it", async () => {
    const db = createMockD1();
    const res = await handleFeedback(postJson("/feedback", { text: "Nice product.", page: "/" }), makeEnv({ DB: db.db }));
    expect(res.status).toBe(202);
    expect(db.feedback).toHaveLength(1);
  });

  it("caps feedback in UTF-8 bytes, not JavaScript characters", async () => {
    expect((await handleFeedback(postJson("/feedback", { text: "x".repeat(4001) }), makeEnv())).status).toBe(400);
    // 1,500 emoji are 3,000 .length units but 6,000 bytes.
    expect((await handleFeedback(postJson("/feedback", { text: "\u{1F600}".repeat(1500) }), makeEnv())).status).toBe(400);
    expect((await handleFeedback(postJson("/feedback", { text: "x".repeat(4000) }), makeEnv())).status).toBe(202);
  });

  it("rejects empty feedback", async () => {
    expect((await handleFeedback(postJson("/feedback", { text: "   " }), makeEnv())).status).toBe(400);
  });
});

describe("purgeOldFeedback", () => {
  it("deletes only feedback older than 90 days, at most `limit` rows, and never touches event_counts", async () => {
    const db = createMockD1();
    const now = Date.parse("2026-09-24T00:00:00Z");
    const old = now - 91 * 24 * 60 * 60 * 1000;
    db.feedback.push({ text: "old 1", page: "/", ts: old });
    db.feedback.push({ text: "old 2", page: "/", ts: old + 1 });
    db.feedback.push({ text: "recent", page: "/", ts: now - 10 * 24 * 60 * 60 * 1000 });
    db.eventCounts.push({ day: "2026-01-01", name: "page_view", count: 42 });

    expect(await purgeOldFeedback(db.db, now, 1)).toBe(1);
    expect(db.feedback.map((f) => f.text)).toEqual(["old 2", "recent"]);
    await purgeOldFeedback(db.db, now, 10);
    expect(db.feedback.map((f) => f.text)).toEqual(["recent"]);
    expect(db.eventCounts[0].count).toBe(42);
  });
});

describe("/healthz via handleHealthz", () => {
  it("reports ok and falls back to the BUILD_TAG var when no asset exists", async () => {
    const res = await handleHealthz(makeEnv({ ASSETS: createMockAssets({}), BUILD_TAG: "fallback-tag" }));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true, build: "fallback-tag" });
  });

  it("prefers the build-tag.txt static asset when present", async () => {
    const res = await handleHealthz(makeEnv({ ASSETS: createMockAssets({ "build-tag.txt": "release/2026.09.24-1\n" }) }));
    expect(((await res.json()) as { build: string }).build).toBe("release/2026.09.24-1");
  });
});
