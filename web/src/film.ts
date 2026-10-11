// The film page: our own player on <video>, with labelled controls, the
// current shot's mark drawn crisply over the burned-in one (GRAMMAR A4),
// captions placed above a lower third, chapters, the transcript and the end
// card. Everything about the film comes from its sources.json.
import {
  aiSentence,
  chapterAt,
  durationsAgree,
  playedShare,
  seekTime,
  voiceSentence,
  chapters as chaptersOf,
  formatTime,
  lowerThirdAt,
  markAt,
  onDipBlack,
  markHook,
  markWords,
  shotAt,
  silentRecord,
  stepChapter,
  transcript,
  type Chapter,
  type FilmSources,
  type MarkClass,
} from "./film-data";
import { byId, el, filmPath, loadSources, mediaUrl, numerals } from "./site";
import { countCompletionOnce, reportCoreSuccess, sendEvent } from "./telemetry";

const screen = byId("screen");
const SLUG = screen.dataset.slug ?? "partition-of-india";
const FILM = filmPath(SLUG);

const video = byId<HTMLVideoElement>("film");
const frame = byId("frame");
const markEl = byId("mark");
const cueEl = byId("cue");
const bigplay = byId<HTMLButtonElement>("bigplay");
const playBtn = byId<HTMLButtonElement>("play");
const playIcon = byId("play-icon");
const timeEl = byId("time");
const scrub = byId("scrub");
const scrubFill = byId("scrub-fill");
const scrubHead = byId("scrub-head");
const subsBtn = byId<HTMLButtonElement>("subs");
const subsMenu = byId("subs-menu");
const marksBtn = byId<HTMLButtonElement>("marks");
const legend = byId("legend");
const volBtn = byId<HTMLButtonElement>("vol");
const fullBtn = byId<HTMLButtonElement>("full");
const credit = byId("credit");
const endcard = byId("endcard");
const correctTop = byId<HTMLAnchorElement>("correct-top");

const PLAY_PATH = "M8 5.5v13l10.5-6.5z";
const PAUSE_PATH = "M8 5.5v13M16 5.5v13";

// `loaded` is the sources.json as fetched; `data` is set from it only once the
// served film is known to be the cut it describes (durations within a frame).
// Until then, and if they differ, nothing on the page is drawn from it.
let loaded: FilmSources | null = null;
let data: FilmSources | null = null;
let chapterList: Chapter[] = [];
let started = false;

const duration = () => (Number.isFinite(video.duration) && video.duration > 0 ? video.duration : (data?.duration_s ?? 0));

// ---- Marks, cues, the paused credit -------------------------------------------

let shownMark = "";
function drawMark(t: number): void {
  if (!data || !started || !endcard.hidden) {
    markEl.hidden = true;
    shownMark = "";
    return;
  }
  const m = markAt(data.marks, t, data.fps);
  // On a dip's black hold the burned frame carries no mark; neither does the overlay.
  if (!m || onDipBlack(data.shots, t, data.fps)) {
    markEl.hidden = true;
    shownMark = "";
    return;
  }
  const key = `${m.class}|${m.detail}`;
  markEl.hidden = false;
  if (key === shownMark) return;
  shownMark = key;
  const w = markWords(m);
  markEl.dataset.class = markHook(m.class);
  markEl.setAttribute("role", "img");
  markEl.setAttribute("aria-label", w.detail ? `${w.cls} ${w.detail}` : w.cls);
  markEl.replaceChildren(el("span", { class: "cls" }, w.cls), w.detail ? el("span", { class: "det" }, numerals(w.detail)) : "");
}

let track: TextTrack | null = null;
function drawCue(t: number): void {
  const cues = track && track.mode !== "disabled" && captionsOn ? track.activeCues : null;
  const text = cues && cues.length ? Array.from(cues, (c) => ((c as VTTCue).text ?? "").replace(/<[^>]*>/g, "")).join("\n") : "";
  // Captions belong to one cut: shown only once the film is known to be the cut sources.json describes.
  if (!text || !data || !endcard.hidden) {
    cueEl.hidden = true;
    return;
  }
  const lt = data ? lowerThirdAt(data.lowerThirds, t) : null;
  cueEl.classList.toggle("raised", Boolean(lt));
  cueEl.classList.toggle("flagged", Boolean(lt?.flag));
  const span = cueEl.firstElementChild as HTMLElement;
  if (span.textContent !== text) span.textContent = text;
  cueEl.hidden = false;
}

function drawCredit(): void {
  const t = video.currentTime;
  const show = Boolean(data) && started && video.paused && !video.ended && endcard.hidden;
  const sec = Math.floor(t);
  correctTop.href = started ? `${FILM}correct/?t=${sec}` : `${FILM}correct/`;
  if (!show || !data) {
    credit.hidden = true;
    return;
  }
  const shot = shotAt(data.shots, t, data.fps);
  if (!shot || shot.mark.class === "CARD" || !shot.title) {
    credit.hidden = true;
    return;
  }
  byId("credit-title").textContent = shot.title;
  const where = byId("credit-where");
  const bits = [shot.archive, shot.date].filter(Boolean).join(", ");
  where.replaceChildren(numerals(`${bits}${bits ? ". " : ""}${shot.licence ? `Licence: ${shot.licence}.` : ""}`));
  byId<HTMLAnchorElement>("credit-source").href = `${FILM}sources/#${shot.id}`;
  byId<HTMLAnchorElement>("credit-correct").href = `${FILM}correct/?t=${sec}&s=${encodeURIComponent(shot.id)}`;
  credit.hidden = false;
}

// ---- Time, scrubber, chapters ------------------------------------------------------

function drawTime(t: number): void {
  const d = duration();
  timeEl.replaceChildren(formatTime(t), " ", el("span", { class: "of" }, `/ ${formatTime(d)}`));
  const pct = d ? Math.min(100, (t / d) * 100) : 0;
  scrubFill.style.width = `${pct}%`;
  scrubHead.style.left = `${pct}%`;
  scrub.setAttribute("aria-valuemax", String(Math.floor(d)));
  scrub.setAttribute("aria-valuenow", String(Math.floor(t)));
  const ch = chapterAt(chapterList, t);
  scrub.setAttribute("aria-valuetext", `${formatTime(t)} of ${formatTime(d)}${ch ? `, ${ch.n !== null ? `chapter ${ch.n}, ` : ""}${ch.title}` : ""}`);
  for (const li of document.querySelectorAll<HTMLElement>("#chapter-list li")) li.classList.toggle("now", li.dataset.id === ch?.id);
}

function draw(): void {
  const t = video.currentTime;
  drawMark(t);
  drawCue(t);
  drawTime(t);
}

let raf = 0;
function loop(): void {
  draw();
  raf = video.paused ? 0 : requestAnimationFrame(loop);
}

function seek(t: number, andPlay = false): void {
  const d = duration();
  video.currentTime = Math.max(0, d ? Math.min(t, d - 0.05) : t);
  if (andPlay) play();
  draw();
  drawCredit();
}

function play(): void {
  hideEnd();
  started = true;
  bigplay.hidden = true;
  void video.play().catch(() => {
    // Refused (no gesture yet) or not loaded: the Play control stays available.
  });
}

function toggle(): void {
  if (video.paused || video.ended) play();
  else video.pause();
}

function setupScrubber(): void {
  const timeAt = (clientX: number) => {
    const r = scrub.getBoundingClientRect();
    return Math.max(0, Math.min(1, (clientX - r.left) / r.width)) * duration();
  };
  let dragging = false;
  scrub.addEventListener("pointerdown", (e) => {
    dragging = true;
    scrub.setPointerCapture(e.pointerId);
    started = true;
    bigplay.hidden = true;
    seek(timeAt(e.clientX));
  });
  scrub.addEventListener("pointermove", (e) => {
    if (dragging) seek(timeAt(e.clientX));
  });
  const end = () => (dragging = false);
  scrub.addEventListener("pointerup", end);
  scrub.addEventListener("pointercancel", end);
  scrub.addEventListener("keydown", (e) => {
    const steps: Record<string, number> = { ArrowLeft: -5, ArrowDown: -5, ArrowRight: 5, ArrowUp: 5, PageDown: -60, PageUp: 60 };
    let to: number | null = null;
    if (e.key in steps) to = video.currentTime + steps[e.key];
    else if (e.key === "Home") to = 0;
    else if (e.key === "End") to = duration();
    if (to === null) return;
    e.preventDefault();
    e.stopPropagation();
    started = true;
    bigplay.hidden = true;
    seek(to);
  });
}

/** A seek target inside the first frame at `start_s`, never on its boundary. */
const at = (start_s: number) => seekTime(start_s, data?.fps ?? 24).toFixed(3);

function renderChapters(list: Chapter[]): void {
  const ol = byId("chapter-list");
  byId("chapters-count").textContent = `${list.filter((c) => c.n !== null).length} chapters`;
  ol.replaceChildren(
    ...list.map((c) =>
      el(
        "li",
        { "data-id": c.id },
        el("a", { class: "tc", href: `#t=${at(c.start_s)}`, "data-seek": at(c.start_s), "aria-label": `Play from ${formatTime(c.start_s)}, ${c.title}` }, formatTime(c.start_s)),
        el("span", {}, c.n !== null ? numerals(`${c.n}  `) : "", c.title, c.dates ? " " : "", c.dates ? el("span", { class: "muted" }, numerals(c.dates)) : ""),
      ),
    ),
  );
  // Chapter ticks on the scrubber.
  for (const c of list) {
    if (c.start_s <= 0) continue;
    const tick = el("span", { class: "tick", "aria-hidden": "true" });
    tick.style.left = `${(c.start_s / (data?.duration_s || 1)) * 100}%`;
    scrub.prepend(tick);
  }
}

function renderTranscript(d: FilmSources): void {
  const entries = transcript(d);
  byId("transcript").replaceChildren(
    ...entries.map((e) =>
      el(
        "li",
        {},
        el("a", { class: "tc", href: `#t=${at(e.start_s)}`, "data-seek": at(e.start_s), "aria-label": `Play from ${formatTime(e.start_s)}` }, formatTime(e.start_s)),
        el("span", { class: "who" }, e.who),
        el("span", { class: "said" }, numerals(e.text)),
      ),
    ),
  );
}

const SIDE_PHRASE: Record<string, string> = { britain: "Britain", india: "India", pakistan: "Pakistan", bangladesh: "Bangladesh", sikh: "the Sikh community" };

function renderNotes(d: FilmSources): void {
  const sides = Object.keys(SIDE_PHRASE).filter((s) => d.readings.some((r) => r.side === s));
  if (sides.length) {
    const names = sides.map((s) => SIDE_PHRASE[s]);
    const list = names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}` : names[0];
    byId("accounts").textContent = `Accounts from ${list}.`;
  }
  const ai = aiSentence(d.shots);
  const voice = voiceSentence(d.readings);
  for (const id of ["ai-sentence", "ai-sentence-legend"]) byId(id).textContent = ai;
  for (const id of ["voice-sentence", "voice-sentence-legend", "voice-note"]) byId(id).textContent = voice ?? "";
  const silent = silentRecord(d.shots);
  if (silent) {
    byId("silent-note").textContent = `${silent.says} The film says so on screen.`;
    const says = byId("end-silent");
    says.textContent = silent.says;
    says.hidden = false;
    if (silent.searched) {
      const searched = byId("end-searched");
      searched.replaceChildren(numerals(silent.searched));
      searched.hidden = false;
    }
  }
  const counts = new Map<MarkClass, number>();
  for (const s of d.shots) counts.set(s.mark.class, (counts.get(s.mark.class) ?? 0) + 1);
  for (const p of document.querySelectorAll<HTMLElement>("[data-none-for]")) {
    if (!counts.get(p.dataset.noneFor as MarkClass)) p.append(" This film has none.");
  }
  byId("bigplay-time").textContent = formatTime(d.duration_s);
}

// ---- Menus: subtitles and the marks legend -------------------------------------------

let captionsOn = false;
function setCaptions(on: boolean): void {
  captionsOn = on && Boolean(track);
  if (track) track.mode = captionsOn ? "hidden" : "disabled";
  for (const b of subsMenu.querySelectorAll<HTMLButtonElement>("[data-track]")) {
    b.setAttribute("aria-checked", String((b.dataset.track === "en") === captionsOn));
  }
  draw();
}

function closeMenus(except?: HTMLElement): void {
  for (const [menu, btn] of [[subsMenu, subsBtn], [legend, marksBtn]] as const) {
    if (menu === except) continue;
    menu.hidden = true;
    btn.setAttribute("aria-expanded", "false");
  }
}

function openMenu(menu: HTMLElement, btn: HTMLButtonElement, focus: boolean): void {
  closeMenus(menu);
  menu.hidden = false;
  btn.setAttribute("aria-expanded", "true");
  if (focus) {
    const first = menu.querySelector<HTMLElement>('[aria-checked="true"], button, a');
    first?.focus();
  }
}

function toggleMenu(menu: HTMLElement, btn: HTMLButtonElement, focus: boolean): void {
  if (menu.hidden) openMenu(menu, btn, focus);
  else {
    closeMenus();
    btn.focus();
  }
}

function setupMenus(): void {
  const tracks = video.textTracks;
  track = tracks.length ? tracks[0] : null;
  if (track) track.mode = "disabled";
  const trackEl = video.querySelector("track");
  trackEl?.addEventListener("error", () => {
    byId("captions-error").hidden = false;
    subsMenu.querySelector<HTMLButtonElement>('[data-track="en"]')?.setAttribute("disabled", "");
    setCaptions(false);
  });
  track?.addEventListener("cuechange", () => drawCue(video.currentTime));

  subsBtn.addEventListener("click", (e) => toggleMenu(subsMenu, subsBtn, e.detail === 0));
  marksBtn.addEventListener("click", (e) => toggleMenu(legend, marksBtn, e.detail === 0));
  byId("legend-link").addEventListener("click", (e) => {
    e.preventDefault();
    openMenu(legend, marksBtn, true);
    marksBtn.scrollIntoView({ block: "nearest" });
  });
  for (const b of subsMenu.querySelectorAll<HTMLButtonElement>("[data-track]")) {
    b.addEventListener("click", () => {
      setCaptions(b.dataset.track === "en");
      closeMenus();
      subsBtn.focus();
    });
  }
  // Arrow keys move within the subtitles menu; Escape closes either menu.
  subsMenu.addEventListener("keydown", (e) => {
    const items = [...subsMenu.querySelectorAll<HTMLButtonElement>("[data-track]:not([disabled])")];
    const i = items.indexOf(document.activeElement as HTMLButtonElement);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      items[(i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length]?.focus();
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (!subsMenu.hidden) {
      closeMenus();
      subsBtn.focus();
    } else if (!legend.hidden) {
      closeMenus();
      marksBtn.focus();
    }
  });
  document.addEventListener("click", (e) => {
    const t = e.target as Node;
    if (!subsMenu.hidden && !subsMenu.contains(t) && !subsBtn.contains(t)) closeMenus();
    if (!legend.hidden && !legend.contains(t) && !marksBtn.contains(t) && !byId("legend-link").contains(t)) closeMenus();
  });
}

// ---- Sound, full screen, end, errors ------------------------------------------------------

function setupButtons(): void {
  bigplay.addEventListener("click", play);
  playBtn.addEventListener("click", toggle);
  video.addEventListener("click", toggle);
  volBtn.setAttribute("aria-pressed", "true");
  volBtn.addEventListener("click", () => {
    video.muted = !video.muted;
  });
  video.addEventListener("volumechange", () => {
    volBtn.setAttribute("aria-pressed", String(!video.muted));
    volBtn.dataset.label = video.muted ? "Sound off" : "Sound";
  });
  fullBtn.addEventListener("click", () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else if (screen.requestFullscreen) void screen.requestFullscreen().catch(() => undefined);
    else (video as HTMLVideoElement & { webkitEnterFullscreen?: () => void }).webkitEnterFullscreen?.();
  });
  document.addEventListener("fullscreenchange", () => {
    const on = Boolean(document.fullscreenElement);
    fullBtn.setAttribute("aria-label", on ? "Leave full screen" : "Full screen");
    fullBtn.dataset.label = on ? "Leave full screen" : "Full screen";
  });
  byId("again").addEventListener("click", () => seek(0, true));
}

function showEnd(): void {
  endcard.hidden = false;
  credit.hidden = true;
  draw();
  byId<HTMLButtonElement>("again").focus({ preventScroll: true });
}

function hideEnd(): void {
  if (endcard.hidden) return;
  endcard.hidden = true;
}

function setupVideoEvents(): void {
  const setPlaying = (playing: boolean) => {
    playIcon.setAttribute("d", playing ? PAUSE_PATH : PLAY_PATH);
    playBtn.setAttribute("aria-label", playing ? "Pause" : "Play");
    playBtn.dataset.label = playing ? "Pause" : "Play";
  };
  video.addEventListener("play", () => {
    started = true;
    bigplay.hidden = true;
    hideEnd();
    setPlaying(true);
    drawCredit();
    if (!raf) raf = requestAnimationFrame(loop);
    lightsSoon();
  });
  video.addEventListener("pause", () => {
    setPlaying(false);
    lightsUp();
    draw();
    drawCredit();
  });
  video.addEventListener("seeked", () => {
    draw();
    drawCredit();
  });
  video.addEventListener("timeupdate", () => {
    if (video.paused) draw();
  });
  video.addEventListener("loadedmetadata", () => {
    trust();
    applyHash();
    draw();
  });
  video.addEventListener("waiting", () => frame.setAttribute("aria-busy", "true"));
  video.addEventListener("playing", () => frame.removeAttribute("aria-busy"));
  video.addEventListener("ended", showEnd);
  // The unit of value is a film watched to its last frame, counted once.
  // Only when at least 90% of it was actually played, so a seek to the end does not count.
  countCompletionOnce(video, reportCoreSuccess, () => playedShare(video.played, duration()) >= 0.9);
  // iOS plays full screen in its own player, which draws only "showing" tracks.
  video.addEventListener("webkitbeginfullscreen", () => {
    if (track && captionsOn) track.mode = "showing";
  });
  video.addEventListener("webkitendfullscreen", () => {
    if (track && captionsOn) track.mode = "hidden";
  });
  const fail = () => {
    byId("film-error").hidden = false;
    bigplay.hidden = true;
  };
  video.addEventListener("error", fail);
  video.querySelector("source")?.addEventListener("error", fail);
}

// ---- #t=, keyboard, house lights ------------------------------------------------------------

function applyHash(): void {
  const m = /^#t=(\d+(?:\.\d+)?)$/.exec(location.hash);
  if (!m) return;
  started = true;
  bigplay.hidden = true;
  seek(Number(m[1]));
}

function setupSeekLinks(): void {
  document.addEventListener("click", (e) => {
    const a = (e.target as Element).closest<HTMLAnchorElement>("a[data-seek]");
    if (!a) return;
    e.preventDefault();
    history.replaceState(null, "", `#t=${a.dataset.seek}`);
    seek(Number(a.dataset.seek), true);
    screen.scrollIntoView({ block: "start" });
    playBtn.focus({ preventScroll: true });
  });
  window.addEventListener("hashchange", applyHash);
}

function setupKeys(): void {
  document.addEventListener("keydown", (e) => {
    if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey) return;
    const target = e.target as HTMLElement;
    if (target.closest("input, textarea, select, [role=menu], [role=dialog]")) return;
    const onControl = target.closest("button, a, summary, [role=slider]");
    let handled = true;
    switch (e.key) {
      case " ":
      case "k":
      case "K":
        if (e.key === " " && onControl) return;
        toggle();
        break;
      case "ArrowLeft":
      case "j":
      case "J":
        if (onControl && e.key === "ArrowLeft") return;
        started = true;
        seek(video.currentTime - (e.key === "ArrowLeft" ? 5 : 10));
        break;
      case "ArrowRight":
      case "l":
      case "L":
        if (onControl && e.key === "ArrowRight") return;
        started = true;
        seek(video.currentTime + (e.key === "ArrowRight" ? 5 : 10));
        break;
      case "m":
      case "M":
        toggleMenu(legend, marksBtn, true);
        break;
      case "c":
      case "C":
        setCaptions(!captionsOn);
        break;
      case "f":
      case "F":
        fullBtn.click();
        break;
      case "[":
      case "]": {
        const to = stepChapter(chapterList, video.currentTime, e.key === "]" ? 1 : -1);
        if (to) {
          started = true;
          seek(seekTime(to.start_s, data?.fps ?? 24));
        }
        break;
      }
      default:
        handled = false;
    }
    if (handled) e.preventDefault();
  });
}

let idle = 0;
function lightsUp(): void {
  window.clearTimeout(idle);
  screen.classList.remove("lights-down");
}
function lightsSoon(): void {
  lightsUp();
  if (video.paused) return;
  const ms = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--house-lights-idle")) || 2500;
  idle = window.setTimeout(() => {
    if (!video.paused && subsMenu.hidden && legend.hidden && !screen.querySelector(".controls")?.contains(document.activeElement)) {
      screen.classList.add("lights-down");
    }
  }, ms);
}

// ---- Start ----------------------------------------------------------------------------------

sendEvent("page_view");
setupButtons();
setupVideoEvents();
setupMenus();
setupScrubber();
setupSeekLinks();
setupKeys();
for (const ev of ["pointermove", "pointerdown", "keydown", "focusin"]) screen.addEventListener(ev, lightsSoon);
draw();

/**
 * Uses the sources file only once the film's metadata is in and the two
 * agree. A film and a sources.json from different cuts would put marks,
 * credits and chapters on the wrong frames, so then nothing is drawn: the
 * burned-in marks still say what each frame is.
 */
function trust(): void {
  if (!loaded || data || video.readyState < 1) return;
  if (!durationsAgree(video.duration, loaded)) return;
  data = loaded;
  chapterList = chaptersOf(data);
  renderChapters(chapterList);
  renderTranscript(data);
  renderNotes(data);
  for (const id of ["chapters", "transcript-drill", "chapters-link", "derived-notes"]) byId(id).hidden = false;
  draw();
  drawCredit();
}

loadSources(SLUG)
  .then((d) => {
    loaded = d;
    // The poster is shown only when the release recorded which still it is (its credit lives in Sources).
    if (d.poster && !video.getAttribute("poster")) video.poster = mediaUrl(SLUG, "poster.jpg");
    trust();
  })
  .catch(() => {
    // The film still plays without its sources file; the marks stay burned into the picture.
  });
