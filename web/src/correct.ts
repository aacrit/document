// Corrections: one form, posted to /feedback as same-origin JSON. It asks
// where in the film, what is wrong and how they know; never a name or an
// email. A send is confirmed in place ("Sent."), with no page jump.
import { correctionText, whereIsValid } from "./correction";
import { formatTime, shotAt, type FilmSources } from "./film-data";
import { byId, el, loadSources, numerals } from "./site";
import { sendEvent } from "./telemetry";

const root = byId("correct");
const SLUG = root.dataset.slug ?? "partition-of-india";

const form = byId<HTMLFormElement>("form");
const sent = byId("sent");
const when = byId<HTMLInputElement>("when");
const what = byId<HTMLTextAreaElement>("what");
const how = byId<HTMLInputElement>("how");
const send = byId<HTMLButtonElement>("send");
const status = byId("status");
const count = byId("what-count");

// The Worker caps feedback text at 4,000 UTF-8 bytes (worker/src/config.ts).
const MAX_BYTES = 4000;
let film: FilmSources | null = null;
let shotId: string | null = null;

const utf8 = (s: string) => new TextEncoder().encode(s).byteLength;

function setInvalid(fieldId: string, msgId: string, bad: boolean, input: HTMLElement): void {
  byId(fieldId).classList.toggle("invalid", bad);
  byId(msgId).hidden = !bad;
  if (bad) input.setAttribute("aria-invalid", "true");
  else input.removeAttribute("aria-invalid");
}

function updateCount(): void {
  count.textContent = `${what.value.length.toLocaleString("en-GB")} of 2,000`;
}

function showMoment(d: FilmSources, params: URLSearchParams): void {
  const t = params.get("t");
  const secs = t !== null && /^\d+(\.\d+)?$/.test(t) ? Number(t) : null;
  const sid = params.get("s");
  const shot = sid ? (d.shots.find((s) => s.id === sid) ?? null) : secs !== null ? shotAt(d.shots, secs) : null;
  if (!shot && secs === null) return;
  const at = secs ?? shot?.start_s ?? 0;
  if (!when.value) when.value = formatTime(at);
  shotId = shot?.id ?? null;
  byId("moment-when").replaceChildren("At ", el("span", { class: "tc" }, formatTime(at)), sid ? ", from Sources" : ", from the film");
  byId("moment-title").textContent = shot && shot.mark.class !== "CARD" ? (shot.title ?? "") : (shot?.text?.join(" ") ?? "");
  const credit = byId("moment-credit");
  if (shot && shot.mark.class !== "CARD") {
    const bits = [shot.archive, shot.date].filter(Boolean).join(", ");
    credit.replaceChildren(numerals(bits), bits ? " · " : "", el("a", { class: "source", href: `/f/${SLUG}/sources/#${shot.id}` }, "Source"));
  } else credit.replaceChildren();
  byId("moment").hidden = false;
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const whatBad = !what.value.trim();
  const whenBad = !whereIsValid(when.value, film?.duration_s ?? null);
  setInvalid("what-field", "what-msg", whatBad, what);
  setInvalid("when-field", "when-msg", whenBad, when);
  if (whatBad || whenBad) {
    (whatBad ? what : when).focus();
    return;
  }
  const text = correctionText({ what: what.value, when: when.value, how: how.value, shot: shotId });
  if (utf8(text) > MAX_BYTES) {
    status.textContent = "That is too long to send. Shorten it a little; your text is still here.";
    status.className = "status err";
    return;
  }
  send.disabled = true;
  send.textContent = "Sending";
  status.textContent = "";
  status.className = "status";
  fetch("/feedback", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ text, page: location.pathname }),
  })
    .then((res) => {
      if (res.status === 429) throw new Error("full");
      if (!res.ok) throw new Error(`status ${res.status}`);
      form.hidden = true;
      sent.hidden = false;
      byId<HTMLButtonElement>("again").focus({ preventScroll: true });
    })
    .catch((err: unknown) => {
      status.textContent =
        err instanceof Error && err.message === "full"
          ? "Corrections are full for today. Send this tomorrow; your text is still here."
          : "Could not send. Check your connection and send again; your text is still here.";
      status.className = "status err";
    })
    .finally(() => {
      send.disabled = false;
      send.textContent = "Send correction";
    });
});

byId("again").addEventListener("click", () => {
  form.reset();
  shotId = null;
  updateCount();
  sent.hidden = true;
  form.hidden = false;
  what.focus();
});
what.addEventListener("input", () => {
  updateCount();
  if (what.value.trim()) setInvalid("what-field", "what-msg", false, what);
});
when.addEventListener("input", () => setInvalid("when-field", "when-msg", false, when));

sendEvent("page_view");
updateCount();
const params = new URLSearchParams(location.search);
loadSources(SLUG)
  .then((d) => {
    film = d;
    showMoment(d, params);
  })
  .catch(() => {
    // Without the sources file the form still works; only the moment is missing.
    const t = params.get("t");
    if (t && /^\d+$/.test(t) && !when.value) when.value = formatTime(Number(t));
  });
