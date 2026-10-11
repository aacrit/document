// The screening room: the current film on the marquee. The page is static
// and complete without script; this adds the runtime to Watch (from the
// film's own sources.json) and plays the trailer in a dialog.
import { aiSentence, creditsLine, formatTime, posterCredit, voiceSentence } from "./film-data";
import { byId, loadSources, mediaUrl, numerals } from "./site";
import { sendEvent } from "./telemetry";

const SLUG = "partition-of-india";

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
      byId("home-voice").textContent = voiceSentence(data.readings) ?? "";
      byId("home-ai").textContent = aiSentence(data.shots);
      if (data.poster) {
        const img = byId<HTMLImageElement>("poster");
        img.alt = data.poster.description ?? data.poster.title;
        img.src = mediaUrl(SLUG, "poster.jpg");
        img.hidden = false;
        byId("poster-credit").replaceChildren(numerals(posterCredit(data.poster)));
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

sendEvent("page_view");
setupFromSources();
setupTrailer();
