// Telemetry here is aggregate counts only: no anonymous id, no localStorage,
// no cookies, nothing that could identify a visitor. `/e` accepts exactly
// `{ "name": "<allowed event>" }` and bumps a same-day, same-name counter.
// Because it collects and stores nothing personal, no consent banner is
// needed (see web/privacy.html). Every POST is same-origin JSON: the Worker
// refuses anything else (worker/src/guard.ts), so never use sendBeacon,
// which sends text/plain.
function sendEvent(name: string): void {
  fetch("/e", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name }),
    keepalive: true,
  }).catch(() => {
    // Best-effort telemetry: a failed send is not the user's problem.
  });
}

/**
 * Call this exactly where the product's core action completes (the export
 * is written, the order is placed, the task is finished). Its event is
 * contract.yaml's success_event, the one count the kill criteria in
 * CHARTER.md are written against. Never call it for page views or feedback.
 * The placeholder name is renamed at Spark (scripts/lint-events.mjs).
 */
export function reportCoreSuccess(): void {
  sendEvent("film_completed");
}

function setupFeedback(): void {
  const form = document.getElementById("feedback-form");
  const status = document.getElementById("feedback-status");
  if (!(form instanceof HTMLFormElement) || !status) return;

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const textarea = form.elements.namedItem("text");
    const text = textarea instanceof HTMLTextAreaElement ? textarea.value.trim() : "";
    if (!text) return;

    status.textContent = "Sending.";
    status.removeAttribute("data-state");

    fetch("/feedback", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ text, page: location.pathname }),
    })
      .then((response) => {
        if (response.status === 429) throw new Error("ceiling");
        if (!response.ok) throw new Error(`status ${response.status}`);
        status.textContent = "Thank you, that was sent.";
        form.reset();
      })
      .catch((err: unknown) => {
        status.textContent =
          err instanceof Error && err.message === "ceiling"
            ? "We have had a lot of feedback today. Please try again tomorrow."
            : "Could not send that. Please try again.";
        status.dataset.state = "error";
      });
  });
}

interface Shot {
  id: string;
  start_s: number;
  title: string;
  date: string | null;
  creator: string | null;
  credit: string;
  licence: string;
  item_url: string;
  treatment: string;
}

function timecode(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

// The film's sources ledger, written by studio/sketch.py beside the film.
function setupSources(film: HTMLVideoElement): void {
  const list = document.getElementById("sources");
  if (!list) return;
  fetch("/media/maxwell-street/sources.json")
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`status ${r.status}`))))
    .then((data: { shots: Shot[] }) => {
      for (const shot of data.shots) {
        const li = document.createElement("li");
        const jump = document.createElement("button");
        jump.type = "button";
        jump.className = "tc";
        jump.textContent = timecode(shot.start_s);
        jump.setAttribute("aria-label", `Play from ${timecode(shot.start_s)}`);
        jump.addEventListener("click", () => {
          film.currentTime = shot.start_s;
          void film.play();
        });
        const body = document.createElement("div");
        const title = document.createElement("a");
        title.href = shot.item_url;
        title.rel = "noreferrer";
        title.textContent = shot.title;
        const meta = document.createElement("p");
        meta.className = "muted";
        meta.textContent = [shot.creator, shot.date, shot.licence].filter(Boolean).join(" · ");
        const credit = document.createElement("p");
        credit.className = "credit";
        credit.textContent = `${shot.credit}. ${shot.treatment}.`;
        body.append(title, meta, credit);
        li.append(jump, body);
        list.append(li);
      }
    })
    .catch(() => {
      list.insertAdjacentHTML("beforeend", "<li class=\"muted\">The sources list could not load. Reload to try again.</li>");
    });
}

function setupFilm(): void {
  const film = document.getElementById("film");
  if (!(film instanceof HTMLVideoElement)) return;
  // The unit of value is a film watched to its last frame.
  let reported = false;
  film.addEventListener("ended", () => {
    if (reported) return;
    reported = true;
    reportCoreSuccess();
  });
  setupSources(film);
}

sendEvent("page_view");
setupFilm();
setupFeedback();
