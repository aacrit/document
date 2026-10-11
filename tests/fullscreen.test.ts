// One tap to the film playing, full screen and landscape on a phone
// (web/src/fullscreen.ts, used by web/src/player.ts). Browsers allow sound
// and full screen only inside the tap, so every call that needs it must be
// made before the click handler returns: these tests record what was called
// synchronously, before any promise settled.
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  enterFullscreen,
  exitFullscreen,
  fullscreenPath,
  lockLandscape,
  playFromTap,
  playsFullscreen,
  restoreInline,
  type FsOrientation,
} from "../web/src/fullscreen";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (f: string) => readFileSync(path.join(root, f), "utf8");

function fakes(opts: { element?: boolean; native?: boolean; nativeReady?: boolean; lock?: "ok" | "reject" | "none"; fsReject?: boolean } = {}) {
  const calls: string[] = [];
  const attrs = new Set(["playsinline"]);
  const doc = {
    fullscreenEnabled: opts.element ?? false,
    fullscreenElement: null as Element | null,
    exitFullscreen: async () => {
      calls.push("exitFullscreen");
    },
  };
  const container = opts.element
    ? {
        requestFullscreen: (o?: FullscreenOptions) => {
          calls.push(`requestFullscreen:${o?.navigationUI ?? ""}`);
          return opts.fsReject ? Promise.reject(new Error("denied")) : Promise.resolve();
        },
      }
    : {};
  const video = {
    webkitSupportsFullscreen: opts.nativeReady ?? false,
    ...(opts.native
      ? {
          webkitEnterFullscreen: () => {
            calls.push(`webkitEnterFullscreen:${attrs.has("playsinline") ? "inline" : "no-inline"}`);
            if (!opts.nativeReady) throw new Error("InvalidStateError");
          },
        }
      : {}),
    setAttribute: (n: string) => attrs.add(n),
    removeAttribute: (n: string) => {
      calls.push(`remove:${n}`);
      attrs.delete(n);
    },
  };
  const orientation: FsOrientation | null =
    opts.lock === "none"
      ? null
      : {
          lock: (o: string) => {
            calls.push(`lock:${o}`);
            return opts.lock === "reject" ? Promise.reject(new DOMException("not allowed", "NotSupportedError")) : Promise.resolve();
          },
          unlock: () => calls.push("unlock"),
        };
  const play = () => {
    calls.push(`play:${attrs.has("playsinline") ? "inline" : "no-inline"}`);
    return Promise.resolve();
  };
  return { calls, attrs, doc, container, video, orientation, play };
}

describe("which way full screen works, by capability", () => {
  it("uses the Fullscreen API on the player when the page may go full screen (Android Chrome, desktop)", () => {
    const f = fakes({ element: true, native: true });
    expect(fullscreenPath(f.doc, f.container, f.video)).toBe("element");
  });

  it("falls back to the native video player when elements cannot go full screen (iPhone Safari)", () => {
    const f = fakes({ element: false, native: true });
    expect(fullscreenPath(f.doc, f.container, f.video)).toBe("native");
    // requestFullscreen present but not enabled (an iframe, a policy) is not the element path either.
    expect(fullscreenPath({ fullscreenEnabled: false }, { requestFullscreen: async () => undefined }, f.video)).toBe("native");
  });

  it("plays in the page when neither exists", () => {
    const f = fakes();
    expect(fullscreenPath(f.doc, f.container, f.video)).toBe("none");
  });

  it("goes full screen on play for a coarse pointer or a small viewport, never by user agent", () => {
    expect(playsFullscreen((q) => q === "(pointer: coarse)")).toBe(true);
    expect(playsFullscreen((q) => q === "(max-width: 760px)")).toBe(true);
    expect(playsFullscreen(() => false)).toBe(false);
    expect(read("web/src/fullscreen.ts")).not.toMatch(/userAgent|navigator\.platform|iPhone\b.*test/);
    expect(read("web/src/player.ts")).not.toMatch(/userAgent/);
  });
});

describe("the tap: play and full screen inside the gesture", () => {
  it("Android path: play() then requestFullscreen are both called before the handler returns; landscape is locked after full screen resolves", async () => {
    const f = fakes({ element: true, lock: "ok" });
    const r = playFromTap({ play: f.play, fullscreen: true, path: "element", enter: () => enterFullscreen(f.doc, f.container, f.video, f.orientation) });
    // Synchronously, in the tap: play first (it does not use up the activation), then full screen; no lock yet.
    expect(f.calls).toEqual(["play:inline", "requestFullscreen:hide"]);
    expect(await r.done).toBe(true);
    expect(f.calls).toEqual(["play:inline", "requestFullscreen:hide", "lock:landscape"]);
    expect(r.path).toBe("element");
  });

  it("a refused orientation lock is ignored: still full screen, still playing", async () => {
    const f = fakes({ element: true, lock: "reject" });
    const r = playFromTap({ play: f.play, fullscreen: true, path: "element", enter: () => enterFullscreen(f.doc, f.container, f.video, f.orientation) });
    await expect(r.done).resolves.toBe(true);
    expect(f.calls).toEqual(["play:inline", "requestFullscreen:hide", "lock:landscape"]);
    expect(await lockLandscape({ lock: () => Promise.reject(new Error("x")) })).toBe(false);
    expect(await lockLandscape(null)).toBe(false);
    expect(await lockLandscape({})).toBe(false);
  });

  it("a refused full screen request never locks and never throws; the film still plays", async () => {
    const f = fakes({ element: true, fsReject: true });
    const r = playFromTap({ play: f.play, fullscreen: true, path: "element", enter: () => enterFullscreen(f.doc, f.container, f.video, f.orientation) });
    await expect(r.done).resolves.toBe(false);
    expect(f.calls).toEqual(["play:inline", "requestFullscreen:hide"]);
  });

  it("iPhone path: playsinline is dropped and the native player asked for before play(), all in the tap", async () => {
    const ready = fakes({ native: true, nativeReady: true });
    playFromTap({ play: ready.play, fullscreen: true, path: "native", enter: () => enterFullscreen(ready.doc, ready.container, ready.video, ready.orientation) });
    expect(ready.calls).toEqual(["remove:playsinline", "webkitEnterFullscreen:no-inline", "play:no-inline"]);
    // Before its metadata is in, webkitEnterFullscreen is not called (it would throw); play() without playsinline opens the native player.
    const cold = fakes({ native: true, nativeReady: false });
    playFromTap({ play: cold.play, fullscreen: true, path: "native", enter: () => enterFullscreen(cold.doc, cold.container, cold.video, cold.orientation) });
    expect(cold.calls).toEqual(["remove:playsinline", "play:no-inline"]);
    // Leaving the native player restores inline play.
    restoreInline(cold.video);
    expect(cold.attrs.has("playsinline")).toBe(true);
  });

  it("desktop: one click plays in the page; nothing goes full screen unasked", () => {
    const f = fakes({ element: true });
    let entered = false;
    const r = playFromTap({ play: f.play, fullscreen: false, path: "element", enter: () => ((entered = true), enterFullscreen(f.doc, f.container, f.video, f.orientation)) });
    expect(r.path).toBe("inline");
    expect(entered).toBe(false);
    expect(f.calls).toEqual(["play:inline"]);
  });

  it("a refused play() (autoplay policy) is swallowed, not an unhandled rejection", async () => {
    const f = fakes({ element: true });
    const r = playFromTap({ play: () => Promise.reject(new DOMException("no", "NotAllowedError")), fullscreen: true, path: "element", enter: () => enterFullscreen(f.doc, f.container, f.video, f.orientation) });
    await expect(r.done).resolves.toBe(true);
  });
});

describe("leaving full screen", () => {
  it("unlocks the orientation and leaves the page's full screen", async () => {
    const f = fakes({ element: true, lock: "ok" });
    f.doc.fullscreenElement = {} as Element;
    await exitFullscreen(f.doc, f.orientation);
    expect(f.calls).toEqual(["unlock", "exitFullscreen"]);
    const g = fakes({ element: true });
    await exitFullscreen(g.doc, null);
    expect(g.calls).toEqual([]);
  });
});

describe("the player wires the one tap", () => {
  const player = read("web/src/player.ts");
  const home = read("web/src/home.ts");

  it("the film page's big Play and the first press of Play use the one-tap path", () => {
    expect(player).toMatch(/bigplay\.addEventListener\("click", tapPlay\)/);
    expect(player).toMatch(/function toggle\(\): void \{\s*if \(!started\) tapPlay\(\);/);
    expect(player).toMatch(/export function tapPlay\(\): void \{[\s\S]*?playFromTap\(\{ play: \(\) => video\.play\(\), fullscreen: playsFullscreen\(media\), path: fsPath\(\), enter: goFullscreen \}\);/);
    // Full screen goes on the player's container, never the page.
    expect(player).toMatch(/enterFullscreen\(document, playerRoot, video, orientation\(\)\)/);
  });

  it("Watch on the home page plays in place, in the same click: no navigation, no autoplay on load", () => {
    const handler = /watch\.addEventListener\("click", \(event\) => \{([\s\S]*?)\n  \}\);/.exec(home)?.[1] ?? "";
    expect(handler).toMatch(/event\.preventDefault\(\);\s*theatre\.showModal\(\);[\s\S]*tapPlay\(\);/);
    // Nothing between the click and tapPlay waits: no await, no then, no timer.
    expect(handler).not.toMatch(/await|\.then\(|setTimeout|requestAnimationFrame/);
    // A modified click still opens the film page in a new tab.
    expect(handler).toMatch(/event\.metaKey \|\| event\.ctrlKey/);
    const html = read("web/index.html");
    expect(html).toMatch(/<a class="btn" href="\/f\/partition-of-india\/" id="watch">/);
    for (const page of ["web/index.html", "web/f/partition-of-india/index.html"]) expect(read(page)).not.toMatch(/\bautoplay\b/);
  });

  it("the theatre is the film page's own player markup, loading nothing until the tap", () => {
    const section = (html: string) => (/<section class="screen" id="screen"[\s\S]*?<\/section>/.exec(html)?.[0] ?? "").replace(/\s+/g, " ");
    const film = section(read("web/f/partition-of-india/index.html"));
    const theatre = section(read("web/index.html"));
    expect(film.length).toBeGreaterThan(1000);
    expect(theatre).toBe(film.replace('preload="metadata"', 'preload="none"'));
  });

  it("only the page entries count a page view: the shared player sends none", () => {
    expect(player).not.toMatch(/sendEvent\("page_view"\)/);
    expect(read("web/src/film.ts")).toMatch(/sendEvent\("page_view"\)/);
    expect(home).toMatch(/sendEvent\("page_view"\)/);
    // The success event is still counted once, by the player, wherever the film is watched.
    expect(player).toMatch(/countCompletionOnce\(video, reportCoreSuccess/);
  });

  it("the pages with the player draw under display cutouts and pad by the safe areas", () => {
    for (const page of ["web/index.html", "web/f/partition-of-india/index.html"]) expect(read(page)).toContain("viewport-fit=cover");
    const css = read("web/src/film.css");
    expect(css).toMatch(/\.screen:fullscreen \{[^}]*height: 100dvh/);
    expect(css).toMatch(/env\(safe-area-inset-bottom\)/);
    expect(css).toMatch(/\.screen:fullscreen \.frame-box video \{ background: var\(--color-fullscreen\); \}/);
  });
});

describe("the house lights' delay", () => {
  it("reads a CSS time in either unit the browser hands back", async () => {
    const { cssTimeMs } = await import("../web/src/fullscreen");
    expect(cssTimeMs("3000ms")).toBe(3000);
    expect(cssTimeMs(" 3s")).toBe(3000);
    expect(cssTimeMs("2.5s")).toBe(2500);
    expect(cssTimeMs("soon")).toBeNull();
    expect(read("web/src/player.ts")).toMatch(/cssTimeMs\(getComputedStyle\(document\.documentElement\)\.getPropertyValue\("--house-lights-idle"\)\)/);
  });
});

describe("the phone controls", () => {
  it("fit one row from 360 px: icons only with their labels kept for assistive tech, the total time dropped below 380 px", () => {
    const css = read("web/src/film.css");
    expect(css).toMatch(/@media \(max-width: 520px\) \{[^@]*\.controls > button::after, \.controls > a\.ic::after \{ content: none; \}/);
    expect(css).toMatch(/@media \(max-width: 520px\) \{[^@]*min-width: 44px/);
    expect(css).toMatch(/@media \(max-width: 379\.98px\) \{ \.controls \.time \.of \{ display: none; \} \}/);
    const film = read("web/f/partition-of-india/index.html");
    for (const label of ["Play", "Subtitles", "Marks", "Chapters", "Sound", "Full screen"]) expect(film).toMatch(new RegExp(`aria-label="${label}"`));
  });
});

describe("review fixes", () => {
  const player = read("web/src/player.ts");
  const css = read("web/src/film.css");

  it("with the theatre closed, no key, hash or seek link drives the player (k on the landing page started the film)", () => {
    expect(player).toMatch(/export const playerOffScreen = \(\): boolean => Boolean\(playerRoot\.closest\("dialog:not\(\[open\]\)"\)\);/);
    expect(player).toMatch(/function setupKeys\(\): void \{\s*document\.addEventListener\("keydown", \(e\) => \{\s*\/\/[^\n]*\n\s*if \(playerOffScreen\(\)\) return;/);
    expect(player).toMatch(/function applyHash\(\): void \{\s*if \(playerOffScreen\(\)\) return;/);
    expect(player).toMatch(/if \(!a \|\| playerOffScreen\(\)\) return;/);
  });

  it("the DOM order is the order on screen on phones: frame, controls, paused credit, provenance (WCAG 2.4.3)", () => {
    for (const page of ["web/index.html", "web/f/partition-of-india/index.html"]) {
      const html = read(page);
      const at = (s: string) => html.indexOf(s);
      expect(at('id="frame"'), page).toBeLessThan(at('class="controls"'));
      expect(at('class="controls"'), page).toBeLessThan(at('id="credit"'));
      expect(at('id="credit"'), page).toBeLessThan(at('class="provenance"'));
    }
    expect(css).not.toMatch(/\.paused-credit \{ order:/);
  });

  it("one accessible name: the theatre dialog does not repeat the player's", () => {
    expect(read("web/index.html")).toMatch(/<dialog class="theatre" id="theatre">/);
  });

  it("focus moves to Play once full screen resolves", () => {
    expect(player).toMatch(/r\.done\.then\(\(ok\) => \{\s*if \(ok\) playBtn\.focus\(\{ preventScroll: true \}\);/);
  });

  it("full screen keeps the watermark zone clear, the theatre backdrop is the letterbox, and the controls hug the picture", () => {
    expect(css).toMatch(/top: max\(calc\(env\(safe-area-inset-top\) \+ 56px\), 13dvh\)/);
    expect(css).toMatch(/\.theatre::backdrop \{ background: var\(--color-letterbox\); \}/);
    expect(css).toMatch(/@media \(orientation: portrait\) \{\s*\.screen:fullscreen \{ display: flex; flex-direction: column; justify-content: center; \}/);
    expect(css).toMatch(/grid-template-areas: "play tc scrub subs marks list vol full"/);
  });
});
