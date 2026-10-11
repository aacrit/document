// The service worker's rules, run against the very functions dist/sw.js is
// made of (scripts/lib/sw.mjs serialises them), and the generated script
// itself in a stand-in worker scope. Truth first: a film, a caption file or
// a byte range is never touched, and a film's sources.json is never stored
// and always revalidated.

import { runInNewContext } from "node:vm";
import { describe, expect, it } from "vitest";
import { CACHE_PREFIX, cacheName, installHandlers, routeFor, storable, swSource } from "../scripts/lib/sw.mjs";

const ORIGIN = "https://document.voidvision.org";

type Req = { method: string; url: string; mode: string; headers: Headers };
const req = (p: string, init: { method?: string; mode?: string; headers?: Record<string, string> } = {}): Req => ({
  method: init.method ?? "GET",
  url: p.startsWith("http") ? p : `${ORIGIN}${p}`,
  mode: init.mode ?? "cors",
  headers: new Headers(init.headers ?? {}),
});
const route = (p: string, init?: Parameters<typeof req>[1]) => routeFor(req(p, init), ORIGIN);

describe("routeFor: which requests the worker answers, and how", () => {
  it("never touches a film, a trailer or a caption file", () => {
    expect(route("/media/partition-of-india/film.mp4")).toBe("pass");
    expect(route("/media/partition-of-india/trailer.mp4")).toBe("pass");
    expect(route("/media/partition-of-india/captions-en.vtt")).toBe("pass");
    expect(route("/media/partition-of-india/film.mp4", { mode: "navigate" })).toBe("pass");
  });

  it("never touches a Range request, whatever it asks for", () => {
    for (const p of ["/media/partition-of-india/film.mp4", "/assets/app.js", "/", "/media/partition-of-india/poster.jpg"]) {
      expect(route(p, { headers: { range: "bytes=0-1" }, mode: p === "/" ? "navigate" : "cors" }), p).toBe("pass");
    }
  });

  it("revalidates a film's sources.json on every load and never stores it", () => {
    expect(route("/media/partition-of-india/sources.json")).toBe("revalidate");
  });

  it("pages are network first; hashed assets and icons cache first; posters from the cache and refreshed", () => {
    expect(route("/", { mode: "navigate" })).toBe("network-first");
    expect(route("/f/partition-of-india/", { mode: "navigate" })).toBe("network-first");
    expect(route("/privacy", { mode: "navigate" })).toBe("network-first");
    expect(route("/assets/home-AbC123.js")).toBe("cache-first");
    expect(route("/assets/inter-latin-400-normal-XyZ.woff2")).toBe("cache-first");
    expect(route("/icons/icon-192.png")).toBe("cache-first");
    expect(route("/media/partition-of-india/poster.jpg")).toBe("cache-refresh");
  });

  it("leaves alone: anything not GET, another origin, the Worker's routes and the worker script", () => {
    expect(route("/e", { method: "POST" })).toBe("pass");
    expect(route("/feedback", { method: "POST" })).toBe("pass");
    expect(route("/healthz")).toBe("pass");
    expect(route("/api/anything")).toBe("pass");
    expect(route("/sw.js")).toBe("pass");
    expect(route("https://news.voidvision.org/", { mode: "navigate" })).toBe("pass");
    expect(route("/assets/x.js", { method: "HEAD" })).toBe("pass");
    // A path that only looks like a media key is not a poster or a ledger.
    expect(route("/media/../sources.json")).toBe("pass");
    expect(route("/media/a/b/poster.jpg")).toBe("pass");
  });
});

describe("storable", () => {
  const res = (status: number, headers: Record<string, string> = {}, type = "basic", redirected = false) => ({ status, type, redirected, headers: new Headers(headers) });
  it("keeps only a whole, same-origin, unredirected 200", () => {
    expect(storable(res(200))).toBe(true);
    expect(storable(res(206, { "content-range": "bytes 0-1/10" }))).toBe(false);
    expect(storable(res(200, { "content-range": "bytes 0-9/10" }))).toBe(false);
    expect(storable(res(404))).toBe(false);
    expect(storable(res(200, {}, "opaque"))).toBe(false);
    expect(storable(res(200, {}, "basic", true))).toBe(false);
    expect(storable(null)).toBe(false);
  });
});

// ---- a stand-in worker scope -------------------------------------------------

function fakeScope(network: (r: Req, init?: RequestInit) => Promise<Response>) {
  const stores = new Map<string, Map<string, Response>>();
  const listeners: Record<string, (e: unknown) => void> = {};
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const scope = {
    location: { origin: ORIGIN },
    addEventListener: (type: string, fn: (e: unknown) => void) => (listeners[type] = fn),
    skipWaiting: () => Promise.resolve(),
    clients: { claim: () => Promise.resolve() },
    fetch: (r: Req, init?: RequestInit) => {
      calls.push({ url: r.url, init });
      return network(r, init);
    },
    caches: {
      open: async (name: string) => {
        if (!stores.has(name)) stores.set(name, new Map());
        const s = stores.get(name)!;
        return { put: async (r: Req, res: Response) => void s.set(r.url, res) };
      },
      match: async (r: Req, opts?: { cacheName?: string }) => stores.get(opts?.cacheName ?? "")?.get(r.url)?.clone(),
      keys: async () => [...stores.keys()],
      delete: async (name: string) => stores.delete(name),
    },
  };
  /** Dispatches a fetch; returns the response, or "pass" when the worker leaves it to the browser. */
  const dispatch = async (r: Req): Promise<Response | "pass"> => {
    let answer: Promise<Response> | undefined;
    const waits: Promise<unknown>[] = [];
    listeners.fetch({ request: r, respondWith: (p: Promise<Response>) => (answer = p), waitUntil: (p: Promise<unknown>) => waits.push(p) });
    if (!answer) return "pass";
    const res = await answer;
    await Promise.all(waits);
    await Promise.all(waits); // a wait may add another (a refreshed poster's store)
    return res;
  };
  const lifecycle = async (type: "install" | "activate") => {
    const waits: Promise<unknown>[] = [];
    listeners[type]({ waitUntil: (p: Promise<unknown>) => waits.push(p) });
    await Promise.all(waits);
  };
  return { scope, stores, calls, dispatch, lifecycle, listeners };
}

const ok = (body: string, headers: Record<string, string> = {}) => {
  const r = new Response(body, { status: 200, headers });
  // Node's Response has type "default"; the worker only stores same-origin ("basic") answers.
  Object.defineProperty(r, "type", { value: "basic" });
  return r;
};

describe("the worker's handlers", () => {
  const CACHE = cacheName("t1");

  it("stores no film, no range and no sources.json, and sends sources.json to the server with cache: no-cache", async () => {
    const f = fakeScope(async (r) => ok(`net ${r.url}`));
    installHandlers(f.scope, CACHE, CACHE_PREFIX);
    expect(await f.dispatch(req("/media/p/film.mp4"))).toBe("pass");
    expect(await f.dispatch(req("/media/p/film.mp4", { headers: { range: "bytes=0-" } }))).toBe("pass");
    const s1 = (await f.dispatch(req("/media/p/sources.json"))) as Response;
    const s2 = (await f.dispatch(req("/media/p/sources.json"))) as Response;
    expect(await s1.text()).toBe(`net ${ORIGIN}/media/p/sources.json`);
    expect(await s2.text()).toBe(`net ${ORIGIN}/media/p/sources.json`);
    expect(f.calls.filter((c) => c.url.endsWith("sources.json")).map((c) => c.init)).toEqual([{ cache: "no-cache" }, { cache: "no-cache" }]);
    expect([...(f.stores.get(CACHE)?.keys() ?? [])]).toEqual([]);
  });

  it("pages: from the network when it answers (and kept), from the copy when it does not", async () => {
    let online = true;
    const f = fakeScope(async () => (online ? ok("fresh page") : Promise.reject(new TypeError("offline"))));
    installHandlers(f.scope, CACHE, CACHE_PREFIX);
    const nav = req("/f/p/", { mode: "navigate" });
    expect(await ((await f.dispatch(nav)) as Response).text()).toBe("fresh page");
    online = false;
    expect(await ((await f.dispatch(nav)) as Response).text()).toBe("fresh page");
    await expect(f.dispatch(req("/never-seen/", { mode: "navigate" }))).rejects.toThrow("offline");
  });

  it("hashed assets: the network once, then the cache", async () => {
    const f = fakeScope(async () => ok("js"));
    installHandlers(f.scope, CACHE, CACHE_PREFIX);
    await f.dispatch(req("/assets/a-1.js"));
    await f.dispatch(req("/assets/a-1.js"));
    expect(f.calls.length).toBe(1);
  });

  it("posters: answered from the cache, refreshed behind it; a partial answer is never kept", async () => {
    let n = 0;
    const f = fakeScope(async () => ok(`poster v${++n}`));
    installHandlers(f.scope, CACHE, CACHE_PREFIX);
    const poster = req("/media/p/poster.jpg");
    expect(await ((await f.dispatch(poster)) as Response).text()).toBe("poster v1");
    expect(await ((await f.dispatch(poster)) as Response).text()).toBe("poster v1");
    expect(await ((await f.dispatch(poster)) as Response).text()).toBe("poster v2");

    const g = fakeScope(async () => new Response("part", { status: 206, headers: { "content-range": "bytes 0-3/10" } }));
    installHandlers(g.scope, CACHE, CACHE_PREFIX);
    await g.dispatch(req("/assets/b-2.js"));
    expect(g.stores.get(CACHE)?.size ?? 0).toBe(0);
  });

  it("activating a build deletes every older build's cache and nothing else", async () => {
    const f = fakeScope(async () => ok(""));
    installHandlers(f.scope, CACHE, CACHE_PREFIX);
    for (const name of [cacheName("old1"), cacheName("old2"), CACHE, "someone-else"]) await f.scope.caches.open(name);
    await f.lifecycle("install");
    await f.lifecycle("activate");
    expect([...f.stores.keys()].sort()).toEqual([CACHE, "someone-else"].sort());
  });
});

describe("dist/sw.js", () => {
  it("is the same rules, self-contained, versioned by the build tag, and runs in a worker scope", async () => {
    const src = swSource("release/2026-10-11");
    expect(src).toContain('installHandlers(self, "document-release/2026-10-11", "document-");');
    expect(src).not.toMatch(/\bimport\b|\bexport\b|\beval\(|new Function/);
    const f = fakeScope(async () => ok("x"));
    runInNewContext(src, { self: f.scope, URL, Promise });
    expect(Object.keys(f.listeners).sort()).toEqual(["activate", "fetch", "install"]);
    expect(await f.dispatch(req("/media/p/film.mp4"))).toBe("pass");
    expect(await f.dispatch(req("/media/p/film.mp4", { headers: { range: "bytes=0-" } }))).toBe("pass");
    await f.dispatch(req("/media/p/sources.json"));
    expect(f.calls.at(-1)?.init).toEqual({ cache: "no-cache" });
  });
});
