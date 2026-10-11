// Sources: every shot with its mark, archive, item, licence, credit and what
// was done to it, filterable by mark; every reading with its speaker, side,
// year and source; and the balance of whose words the film holds. All of it
// is generated from the film's sources.json.
import {
  MARK_CLASSES,
  SIDE_BAND,
  WOMEN_FLOOR,
  computeBalance,
  cardTitle,
  chapterAt,
  chapters as chaptersOf,
  formatTime,
  itemLinkLabel,
  pct,
  readingFlag,
  readingSource,
  secondsByMark,
  seekTime,
  shotTreatment,
  shotWhat,
  silentRecord,
  SIDE_LABELS,
  type Balance,
  type Chapter,
  type FilmSources,
  type MarkClass,
  type Shot,
} from "./film-data";
import { byId, el, filmPath, loadSources, markPlate, numerals } from "./site";
import { countSourceOpens, sendEvent } from "./telemetry";

const root = byId("sources-page");
const SLUG = root.dataset.slug ?? "partition-of-india";
const FILM = filmPath(SLUG);
let fps = 24;

const NONE: Record<MarkClass, string> = {
  ARCHIVE: "No shot in this film is from the archive.",
  RECONSTRUCTED: "No shot in this film is reconstructed.",
  "AI-GENERATED": "No shot in this film is AI-generated.",
  DRAWN: "No shot in this film is drawn.",
  CARD: "No shot in this film is a card.",
};

function dl(rows: [string, Node | string | null][]): HTMLDListElement {
  const list = el("dl");
  for (const [k, v] of rows) if (v !== null && v !== "") list.append(el("dt", {}, k), el("dd", {}, v));
  return list;
}

function chapterHeading(c: Chapter, tag: "h2" | "h3", cls: string): HTMLElement {
  return el(
    tag,
    { class: cls },
    c.n !== null ? numerals(`${c.n}  `) : "",
    c.title,
    c.dates ? " " : "",
    c.dates ? el("span", { class: "muted dates" }, numerals(c.dates)) : "",
  );
}

function shotEntry(shot: Shot): HTMLLIElement {
  const t = Math.floor(shot.start_s);
  const isCard = shot.mark.class === "CARD";
  const title = isCard ? cardTitle(shot) : (shot.title ?? "Untitled item");
  let what = shotWhat(shot);
  if (shot.kind === "archive_video" && shot.date) what = `Film, ${shot.date}, ${Math.round(shot.end_s - shot.start_s)} s`;
  if (shot.kind === "archive_video" && shot.in_s !== null && shot.out_s !== null) {
    what += `, from ${formatTime(shot.in_s)} to ${formatTime(shot.out_s)} of the archive's copy`;
  }
  const item = shot.item_url
    ? el("a", { class: "source", href: shot.item_url, rel: "noreferrer", "data-item": "" }, itemLinkLabel(shot))
    : null;
  const rows: [string, Node | string | null][] = isCard
    ? [["What", numerals(what)]]
    : [
        ["What", numerals(what)],
        ["Archive", shot.archive],
        ["Item", item],
        ["Licence", shot.licence],
        ["Credit", shot.credit && !/^https?:/.test(shot.credit) ? numerals(shot.credit) : null],
        ["Treatment", shotTreatment(shot)],
      ];
  return el(
    "li",
    { id: shot.id, class: "entry", "data-class": shot.mark.class },
    el(
      "div",
      { class: "ehead" },
      markPlate(shot.mark),
      el("a", { class: "tc", href: `${FILM}#t=${seekTime(shot.start_s, fps).toFixed(3)}`, "aria-label": `Watch from ${formatTime(shot.start_s)}` }, formatTime(shot.start_s)),
    ),
    el("h2", {}, numerals(title)),
    dl(rows),
    el("a", { class: "correct-this", href: `${FILM}correct/?s=${encodeURIComponent(shot.id)}&t=${t}` }, "Correct this"),
  );
}

function renderEntries(d: FilmSources, list: Chapter[]): void {
  const box = byId("entries");
  box.replaceChildren();
  for (const c of list) {
    const shots = d.shots.filter((s) => chapterAt(list, s.start_s)?.id === c.id);
    if (!shots.length) continue;
    box.append(
      el("section", { class: "chapter-block", "data-chapter": c.id }, chapterHeading(c, "h2", "sec"), el("ol", { class: "entries" }, ...shots.map(shotEntry))),
    );
  }
}

function renderReadings(d: FilmSources, list: Chapter[]): void {
  const ol = byId("reading-list");
  byId("readings-link").replaceChildren("All ", numerals(String(d.readings.length)), " readings");
  let current = "";
  for (const r of d.readings) {
    const c = chapterAt(list, r.start_s);
    if (c && c.id !== current) {
      current = c.id;
      ol.append(el("li", { class: "rch" }, chapterHeading(c, "h3", "")));
    }
    const flag = readingFlag(r, d.lowerThirds);
    const source = readingSource(r, d.lowerThirds);
    const side = `${SIDE_LABELS[r.side] ?? r.side}${r.gender === "f" ? ", a woman's words" : ""}`;
    ol.append(
      el(
        "li",
        { class: flag ? "flagged" : undefined, id: `reading-${r.id}` },
        flag ? el("p", { class: "rflag" }, numerals(flag)) : null,
        el("q", {}, numerals(r.text)),
        dl([
          ["Speaker", r.name],
          ["Side", side],
          ["Year", r.year !== null ? numerals(String(r.year)) : null],
          ["Length", r.dur_s !== null ? numerals(`${Math.round(r.dur_s)} s`) : null],
          ["Source", source ? numerals(source) : null],
          ["Heard at", el("a", { class: "tc", href: `${FILM}#t=${seekTime(r.start_s, fps).toFixed(3)}` }, formatTime(r.start_s))],
          ["Voice", r.credit],
        ]),
      ),
    );
  }
  if (!d.readings.length) ol.append(el("li", {}, el("p", { class: "muted" }, "This film has no readings.")));
}

function bar(share: number, kind: "band" | "floor"): HTMLElement {
  const fill = el("i");
  fill.style.width = `${Math.min(100, share * 100)}%`;
  const marker = el("b", { class: kind });
  if (kind === "band") {
    marker.style.left = `${SIDE_BAND.min * 100}%`;
    marker.style.width = `${(SIDE_BAND.max - SIDE_BAND.min) * 100}%`;
  } else marker.style.left = `${WOMEN_FLOOR * 100}%`;
  return el("span", { class: "bar", "aria-hidden": "true" }, fill, marker);
}

/** "Whose words, and how long": only figures computed from this film's readings, or one plain sentence. */
function renderBalance(d: FilmSources, b: Balance | null): void {
  const box = byId("balance");
  if (!b) {
    box.append(el("p", { class: "muted small" }, "Balance figures are not available for this cut."));
    return;
  }
  const s = (n: number) => `${Math.round(n)} s`;
  box.append(
    el(
      "p",
      { class: "muted small" },
      numerals(
        `Seconds of readings by side: words read by a computer voice, and any archival recording; the narrator is not counted. All ${s(b.total_s)} are listed under Readings. Each side should hold ${pct(SIDE_BAND.min).replace(".0", "")} to ${pct(SIDE_BAND.max).replace(".0", "")}.`,
      ),
    ),
  );
  const table = el("div", { class: "btable" });
  for (const side of b.sides) {
    table.append(el("span", {}, side.label), bar(side.share, "band"), el("span", { class: "num small" }, `${s(side.seconds)} · ${pct(side.share)}`));
  }
  box.append(table);
  box.append(
    el(
      "div",
      { class: "btable" },
      el("span", {}, "Women"),
      bar(b.women.share, "floor"),
      el("span", { class: "num small" }, `${s(b.women.seconds)} · ${pct(b.women.share)}`),
    ),
  );
  const names = b.women.names.map((w) => `${w.name} ${s(w.seconds)}`).join(", ");
  box.append(
    el(
      "p",
      { class: "muted small" },
      numerals(`Floor ${pct(WOMEN_FLOOR).replace(".0", "")}.${names ? ` ${names}.` : ""}${b.women.share < WOMEN_FLOOR ? " Short of the floor." : ""}`),
    ),
  );
  const silent = silentRecord(d.shots);
  if (silent) {
    box.append(el("div", { class: "short" }, el("p", {}, silent.says), silent.searched ? el("p", { class: "muted small" }, numerals(silent.searched)) : null));
  }
  const marks = secondsByMark(d.shots)
    .filter((m) => m.seconds > 0 || m.key === "generated")
    .map((m) => `${m.label} ${Math.round(m.seconds)} s (${pct(m.share)})`)
    .join(", ");
  box.append(el("p", { class: "muted small" }, numerals(`Seconds by mark, whole film: ${marks}.`)));
}

function setupFilters(d: FilmSources): void {
  const counts = new Map<string, number>([["all", d.shots.length]]);
  for (const c of MARK_CLASSES) counts.set(c, d.shots.filter((s) => s.mark.class === c).length);
  for (const span of root.querySelectorAll<HTMLElement>("[data-count]")) span.textContent = String(counts.get(span.dataset.count ?? "") ?? 0);
  const buttons = [...root.querySelectorAll<HTMLButtonElement>("[data-filter]")];
  const empty = byId("empty");
  for (const b of buttons) {
    b.addEventListener("click", () => {
      const f = b.dataset.filter ?? "all";
      for (const x of buttons) x.setAttribute("aria-pressed", String(x === b));
      for (const li of root.querySelectorAll<HTMLElement>(".entry")) li.hidden = f !== "all" && li.dataset.class !== f;
      for (const sec of root.querySelectorAll<HTMLElement>(".chapter-block")) sec.hidden = !sec.querySelector(".entry:not([hidden])");
      const none = f !== "all" && !counts.get(f);
      empty.textContent = none ? NONE[f as MarkClass] : "";
      empty.hidden = !none;
    });
  }
}

sendEvent("page_view");
countSourceOpens(root);

loadSources(SLUG)
  .then((d) => {
    fps = d.fps;
    const list = chaptersOf(d);
    renderEntries(d, list);
    renderReadings(d, list);
    renderBalance(d, computeBalance(d.readings));
    setupFilters(d);
    let target: HTMLElement | null = null;
    try {
      target = location.hash ? document.getElementById(decodeURIComponent(location.hash.slice(1))) : null;
    } catch {
      // A malformed #fragment: stay at the top.
    }
    target?.scrollIntoView();
  })
  .catch(() => {
    byId("entries").replaceChildren(el("p", { class: "status err", role: "alert" }, "The sources could not load. Check your connection, then reload the page."));
  });
