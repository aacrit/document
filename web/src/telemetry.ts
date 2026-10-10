// Telemetry here is aggregate counts only: no anonymous id, no localStorage,
// no cookies, nothing that could identify a visitor. `/e` accepts exactly
// `{ "name": "<allowed event>" }` and bumps a same-day, same-name counter.
// Because it collects and stores nothing personal, no consent banner is
// needed (see web/privacy.html). Every POST is same-origin JSON: the Worker
// refuses anything else (worker/src/guard.ts), so never use sendBeacon,
// which sends text/plain.
export type ClientEvent = "page_view" | "film_completed" | "source_opened";

export function sendEvent(name: ClientEvent): void {
  fetch("/e", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name }),
    keepalive: true,
  }).catch(() => {
    // Best-effort telemetry: a failed send is not the viewer's problem.
  });
}

/**
 * Call this exactly where the product's core action completes: a film
 * watched to its last frame. Its event is contract.yaml's success_event,
 * the one count the kill criteria in CHARTER.md are written against. Never
 * call it for page views or feedback.
 */
export function reportCoreSuccess(): void {
  sendEvent("film_completed");
}

/**
 * Counts a film as completed the first time it reaches its last frame
 * (`ended`), and never again for this page load: watching it again, or
 * seeking back to the end, does not count twice. Returns a detach function.
 */
export function countCompletionOnce(film: EventTarget, report: () => void): () => void {
  let reported = false;
  const onEnded = () => {
    if (reported) return;
    reported = true;
    report();
  };
  film.addEventListener("ended", onEnded);
  return () => film.removeEventListener("ended", onEnded);
}

/**
 * Counts `source_opened` when a viewer opens an archive's item link (a
 * click, or a middle-click into a new tab) anywhere under `root`.
 */
export function countSourceOpens(root: EventTarget, send: (name: ClientEvent) => void = sendEvent): void {
  const handler = (event: Event) => {
    if (event.type === "auxclick" && (event as MouseEvent).button !== 1) return;
    const target = event.target as { closest?: (sel: string) => unknown } | null;
    if (target && typeof target.closest === "function" && target.closest("a.source[data-item]")) send("source_opened");
  };
  root.addEventListener("click", handler);
  root.addEventListener("auxclick", handler);
}
