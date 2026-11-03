// A film with no readings (Market Street is the first): its witnesses are quoted on cards and printed pages, never
// read aloud. The Sources page says so in place of "not available", lists the film's sides by their labels, keeps the
// seconds by mark, shows the readings' lede, link, heading and list only when there are readings, and files a note on
// a picture that is not a map under "Notes on the pictures". Every value from the file lands as text, never markup.
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { liveFilms, loadRegistry, readTemplates, sitePages } from "../scripts/lib/films.mjs";
import { computeBalance, filmNotes, isMapShot, parseSources, transcriptLede } from "../web/src/film-data";
import { installFakeDocument, type FakeNode } from "./helpers/fake-dom";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (p: string) => readFileSync(path.join(root, p), "utf8");
const zero = () => JSON.parse(read("tests/fixtures/sources-zero-readings.json"));
const trailer = () => JSON.parse(read("tests/fixtures/sources-trailer.json"));
const EVIL = '"><img src=x onerror=alert(1)>';

let restore: () => void;
beforeAll(() => {
  restore = installFakeDocument();
});
afterAll(() => restore());

const text = (nodes: unknown[]) => (nodes as FakeNode[]).map((n) => n.textContent).join("\n");
const all = (nodes: unknown[]) => (nodes as FakeNode[]).flatMap((n) => n.all());

describe("the balance panel of a film with no readings", () => {
  it("says the film has no readings and where its witnesses are quoted, lists its sides, and keeps the seconds by mark", async () => {
    const { balanceNodes, NO_READINGS } = await import("../web/src/balance");
    const d = parseSources(zero());
    expect(d.readings).toEqual([]);
    const nodes = balanceNodes(d, computeBalance(d.readings, d.balance));
    const t = text(nodes);
    expect(NO_READINGS).toBe("This film has no readings.");
    expect(t).toContain("This film has no readings. Its witnesses are quoted on cards and printed pages.");
    expect(t).not.toContain("not available");
    expect(t).toContain("This film's sides: The army's account; Civilians' and reporters' accounts.");
    expect(t).toContain("Seconds by mark, whole film: ARCHIVE film 12 s (27.3%), ARCHIVE stills 12 s (27.3%), DRAWN 10 s (22.7%), CARD 10 s (22.7%), AI-GENERATED 0 s (0.0%).");
    for (const line of t.split("\n")) expect(line).not.toMatch(/[!—]/);
    // every numeral sits in the data face
    const nums = all(nodes).filter((n) => n.tag === "span" && n.attrs.class === "num");
    expect(nums.map((n) => n.textContent)).toEqual(expect.arrayContaining(["12", "27.3", "10", "22.7"]));
  });

  it("says where its witnesses are quoted only as far as the file shows it: quote cards, then printed pages", async () => {
    const { balanceNodes, NO_READINGS } = await import("../web/src/balance");
    const { witnessSentence } = await import("../web/src/film-data");
    const said = (j: ReturnType<typeof zero>) => text(balanceNodes(parseSources(j), null)).split("\n")[0];
    // a quote card and a printed page
    expect(said(zero())).toBe("This film has no readings. Its witnesses are quoted on cards and printed pages.");
    // a quote card, no printed page
    const cardsOnly = zero();
    cardsOnly.shots[1].title = "The Call building, 19 April 1906";
    expect(said(cardsOnly)).toBe("This film has no readings. Its witnesses are quoted on cards.");
    // no quote card: a printed page alone says nothing of witnesses, and a chapter card or a title card is no quote
    const noCards = zero();
    noCards.shots.pop();
    expect(said(noCards)).toBe(NO_READINGS);
    const titleOnly = zero();
    titleOnly.shots[4].text = ["Market Street · San Francisco, spring 1906", "void document"];
    expect(said(titleOnly)).toBe(NO_READINGS);
    const unsourced = zero();
    unsourced.shots[4].text = ["The dead were counted at 478 by the city in 1907."];
    expect(said(unsourced)).toBe(NO_READINGS);
    expect(witnessSentence(parseSources(noCards).shots)).toBeNull();
  });

  it("prints no sides line when the film declares no balance", async () => {
    const { balanceNodes, NO_READINGS } = await import("../web/src/balance");
    const j = zero();
    delete j.balance;
    const d = parseSources(j);
    expect(d.balance).toBeNull();
    const t = text(balanceNodes(d, null));
    expect(t).toContain(NO_READINGS);
    expect(t).not.toContain("sides");
    expect(t).toContain("Seconds by mark, whole film:");
  });

  it("sets a hostile side label as text, never as an element", async () => {
    const { balanceNodes, NO_READINGS } = await import("../web/src/balance");
    const j = zero();
    j.balance.sides[0].label = EVIL;
    j.balance.sides[1].label = `${EVIL} 2`;
    const d = parseSources(j);
    const nodes = balanceNodes(d, null);
    const every = all(nodes);
    expect(every.some((n) => n.tag === "img")).toBe(false);
    expect(every.every((n) => !("onerror" in n.attrs) && !("src" in n.attrs))).toBe(true);
    const t = text(nodes);
    expect(t).toContain(NO_READINGS);
    expect(t).toContain(`This film's sides: ${EVIL}; ${EVIL} 2.`);
  });

  it("keeps a film with readings as it was: figures when they compute, the plain sentence when they do not", async () => {
    const { balanceNodes, NO_READINGS } = await import("../web/src/balance");
    const uncomputable = parseSources(trailer());          // the trailer's readings carry no lengths
    expect(uncomputable.readings.length).toBeGreaterThan(0);
    const u = text(balanceNodes(uncomputable, computeBalance(uncomputable.readings, uncomputable.balance)));
    expect(u).toBe("Balance figures are not available for this cut.");
    const j = trailer();
    j.readings.forEach((r: Record<string, unknown>) => Object.assign(r, { dur_s: 10, gender: "m" }));
    j.balance = { sides: ["britain", "india", "pakistan", "bangladesh", "sikh"] };
    const d = parseSources(j);
    const b = computeBalance(d.readings, d.balance);
    expect(b).not.toBeNull();
    const t = text(balanceNodes(d, b));
    expect(t).toMatch(/^Seconds of readings by side:/);
    expect(t).not.toContain(NO_READINGS);
    expect(t).toContain("Seconds by mark, whole film:");
  });
});

describe("the readings' lede, link, heading and list", () => {
  const template = read("web/templates/sources.html");
  const gated = [...template.matchAll(/<(\w+)[^>]*\bdata-readings\b[^>]*>/g)].map((m) => m[0]);

  it("are marked in the page and hidden until the film's readings are counted, so no page claims readings it lacks", () => {
    expect(gated).toHaveLength(4);
    for (const tag of gated) expect(tag).toMatch(/\bhidden\b/);
    const lede = /<span data-readings hidden>([^<]*(?:<span class="num">\.\.\.<\/span>[^<]*)?)<\/span>/.exec(template)?.[1] ?? "";
    expect(lede).toBe("Every reading with its speaker, their side, the year and the source. Every reading is word for word from its source, sometimes in part (marked <span class=\"num\">...</span>). ");
    expect(template).toContain('<span data-readings hidden> · <a href="#readings" id="readings-link">All readings</a></span>');
    expect(gated.some((t) => /^<h2 class="sec" id="readings"/.test(t))).toBe(true);
    expect(gated.some((t) => /^<ol class="readings" id="reading-list"/.test(t))).toBe(true);
    // the shot sentence is not gated: every film has shots
    expect(template).toMatch(/\{\{content_note\}\}Every shot with the mark it carries on screen, where it came from and its licence\. <span data-readings hidden>/);
  });

  it("are shown when the film has readings and stay hidden when it has none", async () => {
    const { showReadings } = await import("../web/src/site");
    const nodes = () => [{ hidden: true }, { hidden: true }];
    const none = nodes();
    showReadings(none, parseSources(zero()));
    expect(none.every((n) => n.hidden)).toBe(true);
    const some = nodes();
    showReadings(some, parseSources(trailer()));
    expect(some.every((n) => n.hidden === false)).toBe(true);
    const src = read("web/src/sources.ts");
    expect(src).toMatch(/showReadings\(root\.querySelectorAll<HTMLElement>\("\[data-readings\]"\), d\)/);
  });
});

/** The page's words with every [data-readings] element (and what it holds) removed, as a film with no readings shows it. */
function shownWithoutReadings(html: string): string {
  let s = html.replace(/<script[\s\S]*?<\/script>/g, "").replace(/<meta name="(?!description)[^>]*>/g, "");
  for (;;) {
    const m = /<(\w+)\b[^>]*\bdata-readings\b[^>]*>/.exec(s);
    if (!m) break;
    const tag = m[1];
    const open = new RegExp(`<${tag}\\b[^>]*>|</${tag}>`, "g");
    open.lastIndex = m.index + m[0].length;
    let depth = 1;
    let end = -1;
    for (let t = open.exec(s); t; t = open.exec(s)) {
      depth += t[0].startsWith("</") ? -1 : 1;
      if (depth === 0) {
        end = t.index + t[0].length;
        break;
      }
    }
    if (end < 0) throw new Error(`unclosed <${tag} data-readings>`);
    s = s.slice(0, m.index) + s.slice(end);
  }
  // the words a reader sees, and the meta description a search result shows
  const meta = [...s.matchAll(/<meta name="description" content="([^"]*)"/g)].map((x) => x[1]);
  return [...meta, s.replace(/<[^>]+>/g, " ")].join("\n");
}

describe("every page of a film with no readings claims none", () => {
  const live = loadRegistry(path.join(root, "films.json"));
  // the films' own words (content note, synopsis, logline, what it shows) are each film's; the pages' are tested here
  const neutral = { ...live, films: live.films.map((f: Record<string, unknown>) => ({ ...f, content_note: "It concerns a fire.", synopsis: "A city burns.", logline: "a city burns", shows: "It shows no bodies." })) };
  const pages = sitePages(neutral, readTemplates(path.join(root, "web")));
  const slugs = liveFilms(neutral).map((f: { slug: string }) => f.slug);

  it("says nothing of readings on the home, film and sources pages until the film's readings are counted", () => {
    expect(slugs.length).toBeGreaterThan(0);
    const all = ["index.html", ...slugs.flatMap((s: string) => [`f/${s}/index.html`, `f/${s}/sources/index.html`])];
    for (const p of all) expect(shownWithoutReadings(pages[p]), p).not.toMatch(/\breadings?\b/i);
    // and with them counted, each page still says what it said
    expect(pages[`f/${slugs[0]}/index.html`]).toContain('<span data-readings hidden>Every reading is word for word from its source, sometimes in part (marked <span class="num">...</span>). </span>');
    expect(pages[`f/${slugs[0]}/index.html`]).toContain('<span class="m">Every shot with its mark, archive and licence<span data-readings hidden>; every reading with its speaker and source</span></span>');
    expect(pages["index.html"]).toContain('<span data-readings hidden>Every reading is word for word from its source, sometimes in part (marked <span class="num">...</span>). </span>');
  });

  it("describes the sources page by what every film has", () => {
    for (const s of slugs) {
      const meta = /<meta name="description" content="([^"]*)"/.exec(pages[`f/${s}/sources/index.html`])![1];
      expect(meta).toMatch(/^Every shot of .+ with its mark, archive and licence, and what the picture does not say\.$/);
    }
  });

  it("shows the gated words from the film's own sources.json, on the film page and the home page", () => {
    expect(read("web/src/player.ts")).toMatch(/showReadings\(document\.querySelectorAll<HTMLElement>\("\[data-readings\]"\), d\)/);
    expect(read("web/src/home.ts")).toMatch(/showReadings\(document\.querySelectorAll<HTMLElement>\("\[data-readings\]"\), data\)/);
  });

  it("introduces the transcript by what is spoken in it", () => {
    const d = parseSources(zero());
    expect(transcriptLede({ readings: d.readings, narration: [{ id: "N1", start_s: 1, text: "The fire." }] })).toBe("Everything spoken, word for word: the narration.");
    const t = parseSources(trailer());
    expect(transcriptLede({ readings: t.readings, narration: [] })).toBe("The readings, word for word, each with its speaker.");
    expect(transcriptLede({ readings: t.readings, narration: [{ id: "N1", start_s: 1, text: "x" }] })).toBe(
      "Everything spoken, word for word: the narration and the readings, each with its speaker.",
    );
    expect(transcriptLede({ readings: [], narration: [] })).toBeNull();
    expect(read("web/templates/film.html")).toContain('<span id="transcript-lede">Everything spoken, word for word.</span>');
  });
});

describe("the notes of a film whose pictures are not all maps", () => {
  it("files a map's notes under the maps and any other picture's under the pictures, each after its shot's title", async () => {
    const d = parseSources(zero());
    expect(d.shots.map(isMapShot)).toEqual([false, false, true, false, false]);
    const n = filmNotes(d);
    expect(n.mapNotes).toEqual(["The burned district: The fire line is approximate, from the army's report."]);
    expect(n.pictureNotes).toEqual(["The Call, 19 April 1906, page 1: The paper printed a correction to this page on 21 April 1906."]);
    const { notesNodes } = await import("../web/src/notes");
    const blocks = notesNodes(n) as unknown as FakeNode[];
    const byHeading = new Map(blocks.map((b) => [b.children[0].textContent, b.textContent]));
    expect(byHeading.get("Notes on the maps")).toContain("The fire line is approximate");
    expect(byHeading.get("Notes on the maps")).not.toContain("correction");
    expect(byHeading.get("Notes on the pictures")).toContain("The Call, 19 April 1906, page 1: The paper printed a correction");
    expect([...byHeading.keys()].indexOf("Notes on the pictures")).toBe([...byHeading.keys()].indexOf("Notes on the maps") + 1);
  });

  it("knows a map by its mark's label too, as the engine's is_map does", () => {
    const j = zero();
    Object.assign(j.shots[2], { mark: { class: "DRAWN", detail: "", label: "DRAWN from map data" }, source_line: null, data_sources: [] });
    const d = parseSources(j);
    expect(d.shots[2].mark.label).toBe("DRAWN from map data");
    expect(isMapShot(d.shots[2])).toBe(true);
    expect(filmNotes(d).mapNotes).toEqual(["The burned district: The fire line is approximate, from the army's report."]);
    j.shots[2].mark.label = "DRAWN";
    const plain = parseSources(j);
    expect(isMapShot(plain.shots[2])).toBe(false);
    expect(filmNotes(plain).pictureNotes).toContain("The burned district: The fire line is approximate, from the army's report.");
    // a mark without a label (an older sources.json) parses to an empty one
    expect(parseSources(zero()).shots[0].mark.label).toBe("");
  });

  it("introduces the notes by what they hold, true in every state", async () => {
    const { notesIntro } = await import("../web/src/notes");
    expect(notesIntro(filmNotes(parseSources(zero())))).toBe("What the picture does not say: the notes on the maps, the notes on the pictures and the licences.");
    const empty = { dated: [], voices: [], recordings: [], unnamed: [], gaps: [], statements: [], mapNotes: [], mapData: [], pictureNotes: [], licences: [] };
    expect(notesIntro(empty)).toBe("What the picture does not say.");
    expect(notesIntro({ ...empty, voices: ["v"], unnamed: ["u"], gaps: [{ says: "g", searched: "" }], mapNotes: ["m"], licences: ["l"] })).toBe(
      "What the picture does not say: the voices, the speakers the record names only by role, the gaps in the record, the notes on the maps and the licences.",
    );
    expect(notesIntro({ ...empty, pictureNotes: ["p"] })).toBe("What the picture does not say: the notes on the pictures.");
    // the house's dated notes (film_notes) and the period recordings (palette cues), only when there are some
    const note = { text: "t", noted: "2026-11-02", source: null };
    const rec = { id: "N1", performer: "p", what: null, source: null, licence: null };
    expect(notesIntro({ ...empty, dated: [note], licences: ["l"] })).toBe("What the picture does not say: our dated notes on the film and the licences.");
    expect(notesIntro({ ...empty, recordings: [rec] })).toBe("What the picture does not say. It also lists the period recordings the film plays.");
    expect(notesIntro({ ...empty, dated: [note], recordings: [rec] })).toBe(
      "What the picture does not say: our dated notes on the film. It also lists the period recordings the film plays.",
    );
    expect(read("web/templates/sources.html")).toContain('<p class="muted" id="notes-intro">What the picture does not say.</p>');
    expect(read("web/src/sources.ts")).toMatch(/byId\("notes-intro"\)\.textContent = notesIntro\(notes\)/);
  });

  it("sets a hostile picture note and shot title as text, never as an element", async () => {
    const j = zero();
    j.shots[1].title = EVIL;
    j.shots[1].notes = [EVIL];
    const n = filmNotes(parseSources(j));
    expect(n.pictureNotes).toEqual([`${EVIL}: ${EVIL}`]);
    const { notesNodes } = await import("../web/src/notes");
    const nodes = notesNodes(n);
    const every = all(nodes);
    expect(every.some((x) => x.tag === "img")).toBe(false);
    expect(every.every((x) => !("onerror" in x.attrs) && !("src" in x.attrs))).toBe(true);
    expect(text(nodes).split(EVIL).length - 1).toBe(2);
  });
});
