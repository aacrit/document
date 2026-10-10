import {
  ALLOWED_EVENTS,
  DEFAULT_EVENT_DAILY_CEILING,
  DEFAULT_FEEDBACK_DAILY_CEILING,
  FEEDBACK_PURGE_DAILY_MULTIPLE,
  FEEDBACK_PURGE_ON_INSERT,
  MAX_EVENT_BODY_BYTES,
  MAX_FEEDBACK_BODY_BYTES,
  MAX_FEEDBACK_PAGE_CHARS,
  MAX_FEEDBACK_TEXT_BYTES,
  RATE_LIMITER_ERROR_DAILY_CEILING,
  RETENTION_DAYS,
  SERVER_ONLY_EVENTS,
  type AllowedEvent,
} from "./config";
import { incrementUnderCeiling, utcDay } from "./events";
import { readJsonWithCap } from "./http";
import { isCrossSite, isJsonContentType, LIMITER_PERIOD_SECONDS, limiterFor, withinRateLimit, type GuardEnv } from "./guard";
import { API_CSP, withSecurityHeaders } from "./headers";
import { handleMedia } from "./media";
import { PAGE_CSP_HEADER } from "../../scripts/lib/csp.mjs";

export interface Env extends GuardEnv {
  DB: D1Database;
  ASSETS: Fetcher;
  MEDIA: R2Bucket;
  BUILD_TAG?: string;
  EVENT_DAILY_CEILING?: string;
  FEEDBACK_DAILY_CEILING?: string;
}

export { utcDay, incrementUnderCeiling };

export function isAllowedEvent(name: unknown): name is AllowedEvent {
  return typeof name === "string" && (ALLOWED_EVENTS as readonly string[]).includes(name);
}

export function isServerOnlyEvent(name: unknown): boolean {
  return typeof name === "string" && (SERVER_ONLY_EVENTS as readonly string[]).includes(name);
}

function positiveVar(value: string | undefined, fallback: number): number {
  const parsed = Number(value ?? "");
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function feedbackDailyCeiling(env: Env): number {
  return positiveVar(env.FEEDBACK_DAILY_CEILING, DEFAULT_FEEDBACK_DAILY_CEILING);
}

/** Rows one daily purge may delete: enough to keep up with expiry and clear a backlog (config.ts). */
// Assumes FEEDBACK_DAILY_CEILING was never lowered after rows were stored under a higher one.
export function dailyPurgeLimit(env: Env): number {
  return FEEDBACK_PURGE_DAILY_MULTIPLE * feedbackDailyCeiling(env);
}

/** UTF-8 byte length: what D1 stores, unlike String.length (UTF-16 code units). */
export function utf8Bytes(text: string): number {
  return new TextEncoder().encode(text).byteLength;
}

// Deletes feedback older than RETENTION_DAYS, oldest first, at most `limit`
// rows: a bounded batch, so one purge never writes more than its share of
// the account's daily D1 writes (config.ts's worstCaseDailyWrites).
export async function purgeOldFeedback(db: D1Database, now: number, limit: number): Promise<number> {
  const cutoff = now - RETENTION_DAYS * 24 * 60 * 60 * 1000;
  const res = await db
    .prepare("DELETE FROM feedback WHERE id IN (SELECT id FROM feedback WHERE ts < ? ORDER BY ts LIMIT ?)")
    .bind(cutoff, limit)
    .run();
  return res.meta?.changes ?? 0;
}

function jsonResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function tooLargeResponse(): Response {
  return jsonResponse({ error: "payload_too_large" }, 413);
}

// Aggregate-only telemetry (V3: collect nothing that identifies a person).
// A request carries exactly one field, `name`, and nothing else: no anon
// id, no props, no free-form payload that could smuggle an identifier past
// review. The handler never reads the IP address, user agent or any cookie,
// and never stores anything per visit: it only increments a same-day,
// same-name count, and only while that count is under its ceiling.
export async function handleEvent(request: Request, env: Env): Promise<Response> {
  const read = await readJsonWithCap(request, MAX_EVENT_BODY_BYTES);
  if (!read.ok) return tooLargeResponse();
  const body = read.body;
  if (!body) return jsonResponse({ error: "invalid_json" }, 400);

  const keys = Object.keys(body);
  if (keys.length !== 1 || keys[0] !== "name") {
    return jsonResponse({ error: "unexpected_fields" }, 400);
  }

  const { name } = body;
  if (!isAllowedEvent(name) || isServerOnlyEvent(name)) {
    return jsonResponse({ error: "event_not_allowed" }, 400);
  }

  const now = Date.now();
  const count = await incrementUnderCeiling(env.DB, utcDay(now), name, positiveVar(env.EVENT_DAILY_CEILING, DEFAULT_EVENT_DAILY_CEILING));
  if (count === null) {
    // Past the day's ceiling for this name: nothing was written, and no
    // error either, so abuse learns nothing from the response.
    return new Response(null, { status: 204 });
  }

  // Feedback retention also runs on a day with no feedback: the first
  // count of each client event on a day purges up to twice a day's worth
  // of feedback, so the purge keeps up with expiry (config.ts).
  if (count === 1) {
    await purgeOldFeedback(env.DB, now, dailyPurgeLimit(env));
  }

  return jsonResponse({ ok: true }, 202);
}

export async function handleFeedback(request: Request, env: Env): Promise<Response> {
  const read = await readJsonWithCap(request, MAX_FEEDBACK_BODY_BYTES);
  if (!read.ok) return tooLargeResponse();
  const body = read.body;
  if (!body) return jsonResponse({ error: "invalid_json" }, 400);

  const text = typeof body.text === "string" ? body.text.trim() : "";
  if (!text) return jsonResponse({ error: "invalid_feedback" }, 400);
  if (utf8Bytes(text) > MAX_FEEDBACK_TEXT_BYTES) return jsonResponse({ error: "feedback_too_long" }, 400);
  const page = typeof body.page === "string" ? body.page.slice(0, MAX_FEEDBACK_PAGE_CHARS) : null;

  const now = Date.now();
  // A day ceiling on stored feedback, the same conditional upsert as /e.
  // Past it nothing is stored, and the form says so (429).
  const count = await incrementUnderCeiling(env.DB, utcDay(now), "feedback_received", feedbackDailyCeiling(env));
  if (count === null) return jsonResponse({ error: "daily_ceiling_reached" }, 429);

  // Retention runs before every insert (an indexed delete, usually of no
  // rows), so the table never holds more than RETENTION_DAYS of at most
  // FEEDBACK_DAILY_CEILING rows a day.
  await purgeOldFeedback(env.DB, now, FEEDBACK_PURGE_ON_INSERT);
  await env.DB.prepare("INSERT INTO feedback (text, page, ts) VALUES (?, ?, ?)").bind(text, page, now).run();

  return jsonResponse({ ok: true }, 202);
}

async function readBuildTag(env: Env): Promise<string> {
  // The build tag is a static asset (see scripts/build.mjs), not a Worker
  // var, so a deploy never needs to touch wrangler.jsonc. Falls back to the
  // "dev" var default in local dev, or before the first build has run.
  try {
    const res = await env.ASSETS.fetch(new Request("http://internal/build-tag.txt"));
    if (res.ok) {
      const text = (await res.text()).trim();
      if (text) return text;
    }
  } catch {
    // Fall through to the static default below.
  }
  return env.BUILD_TAG ?? "dev";
}

export async function handleHealthz(env: Env): Promise<Response> {
  const build = await readBuildTag(env);
  const res = jsonResponse({ ok: true, build }, 200);
  res.headers.set("cache-control", "no-store");
  return res;
}

/** The Worker's whole request path: guards, then the route, then headers. */
export async function handle(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);

  // Per-client rate limit first (worker/src/guard.ts), so refused requests
  // count against it too.
  const limiter = limiterFor(request.method, url.pathname);
  const countLimiterError = () =>
    incrementUnderCeiling(env.DB, utcDay(Date.now()), "rate_limiter_error", RATE_LIMITER_ERROR_DAILY_CEILING);
  if (!(await withinRateLimit(env, limiter, request, countLimiterError))) {
    const res = jsonResponse({ error: "rate_limited" }, 429);
    res.headers.set("retry-after", String(LIMITER_PERIOD_SECONDS[limiter]));
    return withSecurityHeaders(res, API_CSP);
  }

  if (request.method === "POST") {
    // Another site's page must not be able to post here through a
    // visitor's browser: refuse cross-site requests, and any body that is
    // not JSON (the "simple" requests a browser sends cross-site without a
    // CORS preflight).
    if (isCrossSite(request)) return withSecurityHeaders(jsonResponse({ error: "cross_site" }, 403), API_CSP);
    if (!isJsonContentType(request)) return withSecurityHeaders(jsonResponse({ error: "unsupported_media_type" }, 415), API_CSP);
  }

  const res = await route(request, env, url);
  // The static fallthrough carries a page policy; every other response is
  // the Worker's JSON, which loads nothing.
  return withSecurityHeaders(res, res.headers.get("Content-Security-Policy") ?? API_CSP);
}

async function route(request: Request, env: Env, url: URL): Promise<Response> {
  if (request.method === "POST" && url.pathname === "/e") return handleEvent(request, env);
  if (request.method === "POST" && url.pathname === "/feedback") return handleFeedback(request, env);
  if (request.method === "GET" && url.pathname === "/healthz") return handleHealthz(env);
  if ((request.method === "GET" || request.method === "HEAD") && url.pathname.startsWith("/media/")) {
    return handleMedia(request, env.MEDIA, url.pathname.slice("/media/".length));
  }

  // Not a Worker route: whatever Workers Static Assets has at this path.
  // With run_worker_first limited to the Worker's own routes, this is
  // mostly a 404 for a path no asset matches. A page policy it carries
  // (dist/_headers) is kept; anything without one gets the page policy.
  const asset = await env.ASSETS.fetch(request);
  return withSecurityHeaders(asset, asset.headers.get("Content-Security-Policy") ?? PAGE_CSP_HEADER);
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    return handle(request, env);
  },

  // Cloudflare caps cron triggers at 5 per account and this account shares
  // one scheduler Worker across every product (wrangler.jsonc explains why
  // this product has no trigger of its own). This handler exists so that
  // shared scheduler, or a future dedicated trigger, can run feedback
  // retention deterministically; day-to-day retention runs in bounded
  // batches inside handleEvent and handleFeedback. `event_counts` rows are
  // never purged: they identify no one, so they are kept indefinitely.
  async scheduled(_event: ScheduledController, env: Env): Promise<void> {
    await purgeOldFeedback(env.DB, Date.now(), dailyPurgeLimit(env));
  },
};
