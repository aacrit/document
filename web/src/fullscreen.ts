// Full screen for the player, by capability, never by user agent.
//
// 1. The Fullscreen API on the player's own container (Android Chrome, the
//    primary path, and desktop browsers): requestFullscreen, then, once the
//    page is full screen (Chrome on Android locks orientation only then),
//    screen.orientation.lock("landscape"). A refused lock is ignored: the
//    film still plays full screen in whatever way the phone is held.
// 2. No Fullscreen API on elements, but a native video player (iPhone
//    Safari): the video plays in the system's own full screen player, which
//    turns to landscape with the phone. It needs the gesture, so the call is
//    made in the same tap; before its metadata is in, the video simply plays
//    without playsinline, which iPhone Safari opens full screen itself.
// 3. Neither: the film plays in the page.
//
// Every call that needs the tap (play, requestFullscreen, the native player)
// is made synchronously inside the click handler, before any await.

export type FullscreenPath = "element" | "native" | "none";

export interface FsDocument {
  fullscreenEnabled?: boolean;
  fullscreenElement?: Element | null;
  exitFullscreen?: () => Promise<void>;
}

export interface FsContainer {
  requestFullscreen?: (options?: FullscreenOptions) => Promise<void>;
}

export interface FsVideo {
  webkitEnterFullscreen?: () => void;
  webkitSupportsFullscreen?: boolean;
  setAttribute(name: string, value: string): void;
  removeAttribute(name: string): void;
}

export interface FsOrientation {
  lock?: (orientation: string) => Promise<void>;
  unlock?: () => void;
}

/** Which way full screen works here, from what the browser offers. */
export function fullscreenPath(doc: FsDocument, container: FsContainer, video: FsVideo): FullscreenPath {
  if (doc.fullscreenEnabled && typeof container.requestFullscreen === "function") return "element";
  if (typeof video.webkitEnterFullscreen === "function") return "native";
  return "none";
}

/** Phones and tablets play full screen on the first tap: a coarse pointer, or a small viewport. */
export function playsFullscreen(matches: (query: string) => boolean): boolean {
  return matches("(pointer: coarse)") || matches("(max-width: 760px)");
}

/** Turns to landscape where the browser allows it; a refusal (desktop, an unlocked rotation, no API) is ignored. */
export async function lockLandscape(orientation: FsOrientation | null | undefined): Promise<boolean> {
  if (!orientation || typeof orientation.lock !== "function") return false;
  try {
    await orientation.lock("landscape");
    return true;
  } catch {
    return false;
  }
}

export function unlockOrientation(orientation: FsOrientation | null | undefined): void {
  try {
    orientation?.unlock?.();
  } catch {
    // Nothing was locked.
  }
}

/**
 * Enters full screen by the path the browser offers. The request itself is
 * made before this returns (so it stays inside the tap that asked); the
 * promise settles once full screen and the orientation lock have been tried.
 */
export function enterFullscreen(
  doc: FsDocument,
  container: FsContainer,
  video: FsVideo,
  orientation: FsOrientation | null | undefined,
): { path: FullscreenPath; done: Promise<boolean> } {
  const path = fullscreenPath(doc, container, video);
  if (path === "element") {
    let req: Promise<void>;
    try {
      req = container.requestFullscreen!({ navigationUI: "hide" });
    } catch (err) {
      req = Promise.reject(err);
    }
    return {
      path,
      done: Promise.resolve(req).then(
        () => lockLandscape(orientation).then(() => true),
        () => false,
      ),
    };
  }
  if (path === "native") {
    // Without playsinline, iPhone Safari opens a playing video in its own player.
    video.removeAttribute("playsinline");
    if (video.webkitSupportsFullscreen) {
      try {
        video.webkitEnterFullscreen!();
      } catch {
        // Not ready yet: the playsinline-free play() opens it instead.
      }
    }
    return { path, done: Promise.resolve(true) };
  }
  return { path, done: Promise.resolve(false) };
}

/** Leaves full screen: the orientation lock first, then the page's full screen if it is in one. */
export function exitFullscreen(doc: FsDocument, orientation: FsOrientation | null | undefined): Promise<void> {
  unlockOrientation(orientation);
  if (doc.fullscreenElement && typeof doc.exitFullscreen === "function") return doc.exitFullscreen().catch(() => undefined);
  return Promise.resolve();
}

/** The native player was left: the video plays in the page again from here on. */
export function restoreInline(video: FsVideo): void {
  video.setAttribute("playsinline", "");
}

/**
 * The one-tap start: play unmuted, then (on a phone) full screen and
 * landscape, all called synchronously in the gesture. Desktop plays in the
 * page; its full screen button stays the viewer's choice.
 */
export function playFromTap(opts: {
  play: () => Promise<void> | void;
  fullscreen: boolean;
  path: FullscreenPath;
  enter: () => { path: FullscreenPath; done: Promise<boolean> };
}): { path: FullscreenPath | "inline"; done: Promise<boolean> } {
  const start = () => {
    const played = opts.play();
    if (played && typeof (played as Promise<void>).catch === "function") {
      (played as Promise<void>).catch(() => {
        // Refused or not loaded: the Play control stays available.
      });
    }
  };
  if (!opts.fullscreen || opts.path === "none") {
    start();
    return { path: opts.fullscreen ? "none" : "inline", done: Promise.resolve(false) };
  }
  // The native player is asked for before play(), so a video without its metadata opens in it too.
  if (opts.path === "native") {
    const entered = opts.enter();
    start();
    return entered;
  }
  // play() before requestFullscreen: play needs the activation but does not use it up; requestFullscreen does.
  start();
  return opts.enter();
}

/**
 * A CSS time in milliseconds. Browsers hand a custom property back as they
 * normalise it ("3000ms" can come back as "3s"), so the unit must be read:
 * parseFloat alone turned the house lights' 3 s into 3 ms.
 */
export function cssTimeMs(value: string): number | null {
  const m = /^\s*(\d+(?:\.\d+)?)\s*(ms|s)\s*$/i.exec(value);
  if (!m) return null;
  return Number(m[1]) * (m[2].toLowerCase() === "s" ? 1000 : 1);
}
