// The screening room: the current film on the marquee. The page is static
// and complete without script; this adds the runtime to Watch (from the
// film's own sources.json) and, when sources.json declares a trailer, offers
// it in a dialog. Without one the Trailer button stays hidden.
//
// Watch plays the film right here, in the theatre (the film page's own player,
// player.ts), inside the same tap: a link to the film page would lose the tap,
// and with it the browser's leave to play sound and go full screen. From the
// landing page to the film playing is one tap. A modified click (a new tab)
// and a page without script still open the film page.
import "./app";
import { aiSentence, creditsLine, formatTime, posterCredit, trailerNote, voiceSentence } from "./film-data";
import { tapPlay } from "./player";
import { byId, loadSources, mediaUrl, numerals, slugOf, withDeeds } from "./site";
import { sendEvent } from "./telemetry";

// The marquee film, from the page (the build writes it from films.json).
const SLUG = slugOf(byId("marquee"));

/**
 * Everything the marquee prints about the film comes from its sources.json:
 * the runtime, the archives and publications credited, and the poster with
 * its own credit. The poster is shown only when the release recorded which
 * still it is (studio/engine/publish.py), so its credit is always its own.
 */
function setupFromSources(): void {
  const runtime = byId("runtime");
  loadSources(SLUG)
    .then((data) => {
      runtime.textContent = formatTime(data.duration_s);
      runtime.hidden = false;
      byId("credits-line").replaceChildren(numerals(creditsLine(data)));
      byId("home-voice").textContent = voiceSentence(data.readings, data.narrator) ?? "";
      byId("home-ai").textContent = aiSentence(data.shots);
      if (data.trailer) {
        byId("trailer-note").textContent = trailerNote(data.trailer);
        byId("trailer-open").hidden = false;
      }
      if (data.poster) {
        const img = byId<HTMLImageElement>("poster");
        img.alt = data.poster.description ?? data.poster.title;
        img.src = mediaUrl(SLUG, "poster.jpg");
        img.hidden = false;
        byId("poster-credit").replaceChildren(withDeeds(posterCredit(data.poster)));
        byId<HTMLVideoElement>("trailer-video").poster = mediaUrl(SLUG, "poster.jpg");
      }
    })
    .catch(() => {
      // Without the sources file the marquee prints no credits rather than guess them; Watch still works.
    });
}

function setupTrailer(): void {
  const dialog = byId<HTMLDialogElement>("trailer");
  const video = byId<HTMLVideoElement>("trailer-video");
  const open = byId<HTMLButtonElement>("trailer-open");
  const close = byId<HTMLButtonElement>("trailer-close");
  open.addEventListener("click", () => {
    // The trailer loads only when asked for: no bytes spent on a visit that never plays it.
    if (!video.getAttribute("src")) video.src = mediaUrl(SLUG, "trailer.mp4");
    dialog.showModal();
    void video.play().catch(() => {
      // Autoplay refused: the trailer's own controls are there.
    });
  });
  close.addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => {
    video.pause();
    open.focus();
  });
  // A click on the backdrop closes it, as Escape does.
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
}

function setupTheatre(): void {
  const theatre = byId<HTMLDialogElement>("theatre");
  const watch = byId<HTMLAnchorElement>("watch");
  const video = byId<HTMLVideoElement>("film");
  watch.addEventListener("click", (event) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    theatre.showModal();
    // In the same tap: play with sound, and on a phone full screen and landscape.
    tapPlay();
  });
  byId("theatre-close").addEventListener("click", () => theatre.close());
  theatre.addEventListener("close", () => {
    video.pause();
    if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined);
    watch.focus();
  });
}

sendEvent("page_view");
setupFromSources();
setupTrailer();
setupTheatre();
