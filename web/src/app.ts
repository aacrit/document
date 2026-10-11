// The installable app, on every page: registers the service worker
// (scripts/lib/sw.mjs, built to /sw.js) and offers the install.
//
// The install offer is never made on arrival. Chrome's own install banner is
// held back (beforeinstallprompt's default is prevented) and the event kept.
// A quiet "Install the app" in the footer works whenever the browser offers
// the install; the "Install void document" button beside the film appears
// only after the visitor has watched (the film played, or ran to its end).
// Nothing is stored and nothing is counted: a fresh page load starts over.

import { installControls, runningInstalled, shouldRegister, type InstallPromptEvent, type InstallState } from "./install";

function registerServiceWorker(): void {
  const tag = document.querySelector<HTMLMetaElement>('meta[name="build"]')?.content;
  if (!shouldRegister(window, tag)) return;
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {
      // The site works the same without it; only install and offline launch need it.
    });
  });
}

function setupInstall(): void {
  const footer = document.getElementById("install-app") as HTMLButtonElement | null;
  const offer = document.getElementById("install-offer");
  const offerBtn = offer?.querySelector("button") ?? null;
  const film = document.getElementById("film") as HTMLVideoElement | null;
  const media = (q: string) => window.matchMedia(q).matches;
  let deferred: InstallPromptEvent | null = null;
  const state: InstallState = { available: false, watched: false, installed: runningInstalled(media) };

  const render = () => {
    const show = installControls(state);
    if (footer) footer.hidden = !show.footer;
    if (offer) offer.hidden = !show.offer;
  };

  window.addEventListener("beforeinstallprompt", (event) => {
    // Never Chrome's own banner on arrival: the offer is ours, and it waits.
    event.preventDefault();
    deferred = event as InstallPromptEvent;
    state.available = true;
    render();
  });
  window.addEventListener("appinstalled", () => {
    deferred = null;
    state.available = false;
    state.installed = true;
    render();
  });

  const watched = () => {
    state.watched = true;
    render();
  };
  if (film) {
    film.addEventListener("play", watched, { once: true });
    film.addEventListener("ended", watched, { once: true });
  }

  const install = async () => {
    const event = deferred;
    if (!event) return;
    // The event can prompt once: whatever the answer, the controls go until the browser offers again.
    deferred = null;
    state.available = false;
    render();
    try {
      await event.prompt();
      await event.userChoice;
    } catch {
      // The browser declined to show it; nothing to do.
    }
  };
  footer?.addEventListener("click", () => void install());
  offerBtn?.addEventListener("click", () => void install());
  render();
}

registerServiceWorker();
setupInstall();
