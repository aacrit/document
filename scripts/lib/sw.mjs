// The service worker, written to dist/sw.js by scripts/build.mjs. Its rules
// are plain functions here so the tests run the very code that ships:
// swSource() serialises them (Function.prototype.toString) after the
// build tag, so each function must use nothing outside itself and its
// arguments.
//
// The rules (routeFor):
// - Pages (navigations): network first; a copy is kept for offline launch.
// - Hashed build assets (/assets/*: scripts, styles, fonts) and the app
//   icons: cache first. Their names change when their bytes do.
// - Posters (/media/<slug>/*.jpg): from the cache at once, refreshed from
//   the network behind it, so a re-released still replaces the old one.
// - A film's sources.json: never stored. Every load revalidates with the
//   server (cache: "no-cache"): the film's record is always the current one.
// - Films, trailers and caption files (/media/* otherwise), any request
//   with a Range header, anything not GET, another origin, the Worker's
//   own routes and sw.js itself: not touched at all. The browser fetches
//   them as if there were no service worker.
//
// Install stores the start page and its build assets (offline launch).
// Caches are named by build tag; activating a new build deletes every
// older one, and only the newest build's cache is ever written. A poster
// the server no longer has (404 or 410) leaves the cache.

export const CACHE_PREFIX = "document-";

export const cacheName = (tag) => `${CACHE_PREFIX}${tag}`;

/**
 * How a request is answered: "network-first", "cache-first",
 * "cache-refresh", "revalidate", or "pass" (no respondWith: the browser
 * fetches it untouched). `req` needs method, url, mode and headers.has().
 */
export function routeFor(req, origin) {
  if (req.method !== "GET") return "pass";
  if (req.headers.has("range")) return "pass";
  const url = new URL(req.url);
  if (url.origin !== origin) return "pass";
  const p = url.pathname;
  if (p.startsWith("/media/")) {
    if (/^\/media\/[a-z0-9-]+\/sources\.json$/.test(p)) return "revalidate";
    if (/^\/media\/[a-z0-9-]+\/[a-z0-9-]+\.jpg$/.test(p)) return "cache-refresh";
    return "pass";
  }
  if (p === "/e" || p === "/feedback" || p === "/healthz" || p.startsWith("/api/") || p === "/sw.js") return "pass";
  if (p.startsWith("/assets/") || p.startsWith("/icons/")) return "cache-first";
  if (req.mode === "navigate") return "network-first";
  return "pass";
}

/** Only a whole, same-origin 200 is ever stored: never a partial (206), an opaque or a redirected response. */
export function storable(res) {
  return Boolean(res) && res.status === 200 && res.type === "basic" && !res.redirected && !res.headers.has("content-range");
}

/**
 * Wires the worker's install, activate and fetch handlers onto `scope` (self,
 * or a test's stand-in). `precache` is the start page and its build assets,
 * stored at install so the installed app's start page opens offline.
 */
export function installHandlers(scope, cache, prefix, precache) {
  // Only the newest build's cache is ever written: a worker still running an
  // older build (a page open across a deploy) cannot bring its cache back.
  const newest = () =>
    scope.caches.keys().then((keys) => {
      const ours = keys.filter((k) => k.startsWith(prefix));
      return ours.length === 0 || ours[ours.length - 1] === cache;
    });
  const put = (request, res) => {
    if (!storable(res)) return Promise.resolve();
    const copy = res.clone();
    return newest()
      .then((ok) => (ok ? scope.caches.open(cache).then((c) => c.put(request, copy)) : undefined))
      .catch(() => undefined);
  };
  const strategies = {
    "network-first": (request, wait) =>
      scope.fetch(request).then(
        (res) => {
          wait(put(request, res));
          return res;
        },
        (err) => scope.caches.match(request, { cacheName: cache }).then((hit) => hit || Promise.reject(err)),
      ),
    "cache-first": (request, wait) =>
      scope.caches.match(request, { cacheName: cache }).then(
        (hit) =>
          hit ||
          scope.fetch(request).then((res) => {
            wait(put(request, res));
            return res;
          }),
      ),
    "cache-refresh": (request, wait) => {
      const fresh = scope.fetch(request).then((res) => {
        // A poster taken down (404 or 410) leaves the cache too.
        if (res.status === 404 || res.status === 410) {
          wait(scope.caches.open(cache).then((c) => c.delete(request)).catch(() => undefined));
        } else {
          wait(put(request, res));
        }
        return res;
      });
      wait(fresh.catch(() => undefined));
      return scope.caches.match(request, { cacheName: cache }).then((hit) => hit || fresh);
    },
    revalidate: (request) => scope.fetch(request, { cache: "no-cache" }),
  };

  scope.addEventListener("install", (event) => {
    event.waitUntil(
      scope.caches
        .open(cache)
        .then((c) => c.addAll(precache))
        // A failed precache never blocks the worker: pages still work online, only offline launch waits.
        .catch(() => undefined)
        .then(() => scope.skipWaiting()),
    );
  });
  scope.addEventListener("activate", (event) => {
    event.waitUntil(
      scope.caches
        .keys()
        .then((keys) => Promise.all(keys.filter((k) => k.startsWith(prefix) && k !== cache).map((k) => scope.caches.delete(k))))
        .then(() => scope.clients.claim()),
    );
  });
  scope.addEventListener("fetch", (event) => {
    const route = routeFor(event.request, scope.location.origin);
    if (route === "pass") return;
    event.respondWith(strategies[route](event.request, (p) => event.waitUntil(p)));
  });
}

/**
 * What install stores: the start page and every build asset it names
 * (scripts, module preloads, stylesheets) plus the Latin fonts those
 * stylesheets load. `html` is dist/index.html; `readAsset` returns a dist file's text.
 */
export function precacheList(html, readAsset) {
  const list = ["/"];
  const add = (p) => {
    if (p.startsWith("/assets/") && !list.includes(p)) list.push(p);
  };
  for (const m of html.matchAll(/<(?:script|link)\b[^>]*\s(?:src|href)="(\/assets\/[^"]+)"/g)) add(m[1]);
  for (const css of list.filter((p) => p.endsWith(".css"))) {
    for (const m of readAsset(css).matchAll(/url\(\s*["']?(\/assets\/[^"')]+\.woff2)["']?\s*\)/g)) {
      // The Latin subset only: the start page is English. Other subsets still cache on first use.
      if (/-latin-\d{3}-/.test(m[1])) add(m[1]);
    }
  }
  return list;
}

/** The text of dist/sw.js for a build. */
export function swSource(tag, precache = ["/"]) {
  return [
    `// void document's service worker, build ${tag}. Written by scripts/build.mjs from scripts/lib/sw.mjs.`,
    `"use strict";`,
    routeFor.toString(),
    storable.toString(),
    installHandlers.toString(),
    `installHandlers(self, ${JSON.stringify(cacheName(tag))}, ${JSON.stringify(CACHE_PREFIX)}, ${JSON.stringify(precache)});`,
    "",
  ].join("\n");
}
