// The screening room: the current film on the marquee. The page is static
// and complete without script; this adds the runtime to Watch (from the
// film's own sources.json) and plays the trailer in a dialog.
import { formatTime } from "./film-data";
import { byId, loadSources, mediaUrl } from "./site";
import { sendEvent } from "./telemetry";

const SLUG = "partition-of-india";

function setupRuntime(): void {
  const runtime = byId("runtime");
  loadSources(SLUG)
    .then((data) => {
      runtime.textContent = formatTime(data.duration_s);
      runtime.hidden = false;
    })
    .catch(() => {
      // The runtime is a courtesy; Watch works without it.
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
setupRuntime();
setupTrailer();
