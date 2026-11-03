// A film with no readings (Market Street is the first): its witnesses are quoted on cards and printed pages, never
// read aloud. The Sources page says so in place of "not available", lists the film's sides by their labels, keeps the
// seconds by mark, shows the readings' lede, link, heading and list only when there are readings, and files a note on
// a picture that is not a map under "Notes on the pictures". Every value from the file lands as text, never markup.
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { computeBalance, filmNotes, isMapShot, parseSources } from "../web/src/film-data";
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
    expect(NO_READINGS).toBe("This film has no readings. Its witnesses are quoted on cards and printed pages, never read aloud.");
    expect(t).toContain(NO_READINGS);
    expect(t).not.toContain("not available");
    expect(t).toContain("This film's sides: The army's account; Civilians' and reporters' accounts.");
    expect(t).toContain("Seconds by mark, whole film: ARCHIVE film 12 s (30.0%), ARCHIVE photographs 12 s (30.0%), DRAWN 10 s (25.0%), CARD 6 s (15.0%), AI-GENERATED 0 s (0.0%).");
    for (const line of t.split("\n")) expect(line).not.toMatch(/[!—]/);
    // every numeral sits in the data face
    const nums = all(nodes).filter((n) => n.tag === "span" && n.attrs.class === "num");
    expect(nums.map((n) => n.textContent)).toEqual(expect.arrayContaining(["12", "30.0", "6", "15.0"]));
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
    const { showReadings } = await import("../web/src/balance");
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

describe("the notes of a film whose pictures are not all maps", () => {
  it("files a map's notes under the maps and any other picture's under the pictures, each after its shot's title", async () => {
    const d = parseSources(zero());
    expect(d.shots.map(isMapShot)).toEqual([false, false, true, false]);
    const n = filmNotes(d);
    expect(n.mapNotes).toEqual(["The burned district: The fire line is approximate, from the army's report."]);
    expect(n.pictureNotes).toEqual(["The Call, 19 April 1906, front page: The paper printed a correction to this page on 21 April 1906."]);
    const { notesNodes } = await import("../web/src/notes");
    const blocks = notesNodes(n) as unknown as FakeNode[];
    const byHeading = new Map(blocks.map((b) => [b.children[0].textContent, b.textContent]));
    expect(byHeading.get("Notes on the maps")).toContain("The fire line is approximate");
    expect(byHeading.get("Notes on the maps")).not.toContain("correction");
    expect(byHeading.get("Notes on the pictures")).toContain("The Call, 19 April 1906, front page: The paper printed a correction");
    expect([...byHeading.keys()].indexOf("Notes on the pictures")).toBe([...byHeading.keys()].indexOf("Notes on the maps") + 1);
  });

  it("introduces the notes by what they hold, true in every state", async () => {
    const { notesIntro } = await import("../web/src/notes");
    expect(notesIntro(filmNotes(parseSources(zero())))).toBe("What the picture does not say: the notes on the maps, the notes on the pictures and the licences.");
    const empty = { voices: [], unnamed: [], gaps: [], statements: [], mapNotes: [], mapData: [], pictureNotes: [], licences: [] };
    expect(notesIntro(empty)).toBe("What the picture does not say.");
    expect(notesIntro({ ...empty, voices: ["v"], unnamed: ["u"], gaps: [{ says: "g", searched: "" }], mapNotes: ["m"], licences: ["l"] })).toBe(
      "What the picture does not say: the voices, the speakers the record names only by role, the gaps in the record, the notes on the maps and the licences.",
    );
    expect(notesIntro({ ...empty, pictureNotes: ["p"] })).toBe("What the picture does not say: the notes on the pictures.");
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
