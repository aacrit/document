// The installable app's decisions, pure so the tests run them without a
// browser (web/src/app.ts wires them to the page).

/** Chrome's beforeinstallprompt event (not in lib.dom). */
export interface InstallPromptEvent extends Event {
  prompt(): Promise<void>;
  readonly userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

export interface InstallState {
  /** The browser has offered the install (a kept beforeinstallprompt). */
  available: boolean;
  /** The visitor has watched on this page (a play, or the film's end). */
  watched: boolean;
  /** Running as the installed app already (standalone or fullscreen). */
  installed: boolean;
}

/** Which install controls show: the footer link whenever the install is offered, the watched offer only after a watch. */
export function installControls(s: InstallState): { footer: boolean; offer: boolean } {
  const can = s.available && !s.installed;
  return { footer: can, offer: can && s.watched };
}

/** Running as the installed app: the manifest's display modes. */
export function runningInstalled(matches: (query: string) => boolean): boolean {
  return matches("(display-mode: fullscreen)") || matches("(display-mode: standalone)");
}

/** The service worker is registered only on a built page (its build tag is stamped) in a secure context. */
export function shouldRegister(win: { isSecureContext: boolean; navigator: { serviceWorker?: unknown } }, buildTag: string | null | undefined): boolean {
  return win.isSecureContext && Boolean(win.navigator.serviceWorker) && Boolean(buildTag) && buildTag !== "__BUILD__";
}
