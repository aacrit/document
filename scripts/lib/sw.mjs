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
// Caches are named by build tag; activating a new build deletes every
// older one.

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

/** Wires the worker's install, activate and fetch handlers onto `scope` (self, or a test's stand-in). */
export function installHandlers(scope, cache, prefix) {
  const put = (request, res) => {
    if (!storable(res)) return Promise.resolve();
    const copy = res.clone();
    return scope.caches.open(cache).then((c) => c.put(request, copy)).catch(() => undefined);
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
        wait(put(request, res));
        return res;
      });
      wait(fresh.catch(() => undefined));
      return scope.caches.match(request, { cacheName: cache }).then((hit) => hit || fresh);
    },
    revalidate: (request) => scope.fetch(request, { cache: "no-cache" }),
  };

  scope.addEventListener("install", (event) => {
    event.waitUntil(scope.skipWaiting());
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

/** The text of dist/sw.js for a build. */
export function swSource(tag) {
  return [
    `// void document's service worker, build ${tag}. Written by scripts/build.mjs from scripts/lib/sw.mjs.`,
    `"use strict";`,
    routeFor.toString(),
    storable.toString(),
    installHandlers.toString(),
    `installHandlers(self, ${JSON.stringify(cacheName(tag))}, ${JSON.stringify(CACHE_PREFIX)});`,
    "",
  ].join("\n");
}
