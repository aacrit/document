// What each still is, as the Sources page prints it in an entry's "What" row and its item link: a map, a printed page,
// a frame held from a film the archive holds, or a photograph. A printed label has to be true: Market Street's map
// sheet, magazine and newspaper pages, proclamation and held frames of its 1906 ride all used to print "Photograph".
// The shots are copied verbatim from Market Street's release sources.json and from the live sources.json of Partition
// and The Next Village (tests/fixtures/sources-{market-street,partition,smallpox}-stills.json).
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import {
  entryWhat,
  filmFootage,
  itemLinkLabel,
  parseSources,
  secondsByMark,
  shotWhat,
  stillKind,
  witnessSentence,
  type FilmSources,
  type Shot,
} from "../web/src/film-data";
import { asFake, installFakeDocument } from "./helpers/fake-dom";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const fixture = (name: string) => JSON.parse(readFileSync(path.join(root, `tests/fixtures/${name}`), "utf8"));
const raw = () => fixture("sources-market-street-stills.json");
const EVIL = '"><img src=x onerror=alert(1)>';
const NONE = new Map<string, string | null>();

const film = (): FilmSources => parseSources(raw());
const partition = (): FilmSources => parseSources(fixture("sources-partition-stills.json"));
const smallpox = (): FilmSources => parseSources(fixture("sources-smallpox-stills.json"));
const shot = (d: FilmSources, id: string): Shot => d.shots.find((s) => s.id === id)!;
/** What a film's own Sources page prints for one of its shots. */
const what = (d: FilmSources, id: string): string => shotWhat(shot(d, id), filmFootage(d.shots));
const kind = (d: FilmSources, id: string) => stillKind(shot(d, id), filmFootage(d.shots));
/** Market Street's photograph (2.3, Sacramento Street), re-titled or re-filed. */
function still(over: Record<string, unknown>): Shot {
  const j = raw();
  Object.assign(j.shots.find((s: { id: string }) => s.id === "2.3"), over);
  return shot(parseSources(j), "2.3");
}

let restore: () => void;
beforeAll(() => {
  restore = installFakeDocument();
});
afterAll(() => restore());

describe("a map", () => {
  it("prints Map for the 1899 Sanborn sheet, an archive still with no data, by its title naming a map", () => {
    const d = film();
    expect(shot(d, "2.4").data_sources).toEqual([]);
    expect(what(d, "2.4")).toBe("Map, 1899, held 14 s");
  });

  it("prints Map for a drawn map's data or mark (isMapShot), a map-sheet ledger item, and a mark that names a map", () => {
    expect(shotWhat(still({ data_sources: [{ id: "Natural Earth", url: "https://www.naturalearthdata.com/", licence: "public domain" }] }), NONE)).toBe("Map, 1906-04-18, held 8 s");
    // The Next Village's CIA sheets sit in the house's map-sheet ledger, "sheets"
    expect(what(smallpox(), "1.11")).toMatch(/^Map, /);
    // Partition's Survey of India sheet 43 P is filed with the stills, but its mark says "1943 map"
    expect(what(partition(), "2.2")).toMatch(/^Map, /);
    // a drawn map keeps saying it was drawn
    expect(shotWhat(still({ kind: "drawn", mark: { class: "DRAWN", detail: "from map data", label: "Drawn · from map data" } }), NONE)).toBe("Drawn map, 8 s");
    expect(shotWhat(still({ kind: "drawn", mark: { class: "DRAWN", detail: "from Hansard", label: "Drawn · from Hansard" } }), NONE)).toBe("Drawn, 8 s");
  });

  it("prints Map for every WHO map slide: '(map, Source: WHO)' at a title's end, or 'a map slide' anywhere in it", () => {
    const d = smallpox();
    expect(shot(d, "2.1a").title).toBe("Worldwide smallpox endemic areas, 1966: a map slide (Source: WHO) from Michael Schwartz's set");
    expect(what(d, "2.1a")).toMatch(/^Map, /);
    expect(what(d, "5.3b")).toMatch(/^Map, /);
    expect(what(d, "5.9a")).toMatch(/^Map, /);
  });

  it("reads a map from the mark's label only, never from its detail (the archive's name)", () => {
    expect(stillKind(still({ mark: { class: "ARCHIVE", detail: "Geography and Map Division 1906", label: "Archive · 1906" } }), NONE)).toBe("photograph");
  });

  it("keeps Photograph where the map is in the picture, not the item: a scene, a display, a pin map photographed", () => {
    const d = smallpox();
    expect(shot(d, "4.2a").title).toBe("A map of Sylhet with flags on the villages where smallpox had been found, 1975");
    expect(what(d, "4.2a")).toMatch(/^Photograph, /);
    expect(what(d, "O2")).toMatch(/^Photograph, /); // J. Donald Millar beside a Shapona display: map of West Africa, ...
    expect(what(d, "1.5a")).toMatch(/^Photograph, /); // A Shapona display: map of West Africa, ...
    expect(what(d, "O1")).toMatch(/^Photograph, /); // Sheetaladevi, a Kalighat painting
    expect(stillKind(still({ title: "The map showing the burnt district, pinned to a wall, 1906" }), NONE)).toBe("photograph");
    expect(stillKind(still({ title: "Soldiers studying a map on Van Ness Avenue, 1906" }), NONE)).toBe("photograph");
  });
});

describe("a printed page", () => {
  it("prints Printed page for a magazine page and a newspaper's front page, titled by 'page N'", () => {
    const d = film();
    expect(what(d, "2.2")).toBe("Printed page, 1906-07, held 20 s");
    expect(shot(d, "2.10").title).toBe("The Call-Chronicle-Examiner, 19 April 1906, page 1");
    expect(what(d, "2.10")).toBe("Printed page, 1906-04-19, held 36 s");
  });

  it("prints Printed page for Partition's Gazette pages titled 'p. 91', 'p. 92', and the issue of 30 July 1949 named by its date", () => {
    const d = partition();
    expect(shot(d, "5.1").title).toMatch(/^The Gazette of India Extraordinary, 31 January 1949, p\. 91: /);
    expect(what(d, "5.1")).toMatch(/^Printed page, /);
    expect(what(d, "5.3")).toMatch(/^Printed page, /);
    expect(shot(d, "5.8").title).toBe("The Gazette of India Extraordinary, Saturday 30 July 1949: Ordinance No. XVIII of 1949 (the Ordinance made again)");
    expect(what(d, "5.8")).toMatch(/^Printed page, /);
    expect(what(d, "2.4")).toMatch(/^Printed page, /);
    // the Assembly's printed debates, "p. 574"
    expect(what(d, "4.1")).toMatch(/^Printed page, /);
  });

  it("keeps Photograph for a portrait whose source, in brackets, is a magazine page, and for a scene in a gazette's office", () => {
    const d = partition();
    expect(shot(d, "4.5b").title).toBe("Begum Aizaz Rasul, 1938 (The Indian Listener, 9 April 1938, p. 465)");
    expect(what(d, "4.5b")).toMatch(/^Photograph, /);
    expect(stillKind(still({ title: "Compositors at the Gazette press, Simla, 1947" }), NONE)).toBe("photograph");
    expect(stillKind(still({ title: "The Gazette office, Bombay" }), NONE)).toBe("photograph");
  });

  it("prints Printed page for the Mayor's proclamation of 18 April 1906, a broadside", () => {
    const d = film();
    expect(shot(d, "2.5").title).toBe("Proclamation by the Mayor, 18 April 1906");
    expect(what(d, "2.5")).toBe("Printed page, 1906-04-18, held 19 s");
    expect(stillKind(still({ title: "Broadside of the Citizens' Committee, 20 April 1906" }), NONE)).toBe("page");
  });

  it("keeps Photograph for a picture with a proclamation or a broadside in it", () => {
    for (const title of [
      "A proclamation being read aloud on Market Street, 1906",
      "Crowd reading a proclamation on Market Street, 1906",
      "Men beside a broadside, 1906",
      "Proclamations posted on a wall: the corner of Market and Kearny, 1906",
      "Proclamation being read to the crowd at City Hall, 1906",
    ])
      expect(stillKind(still({ title }), NONE), title).toBe("photograph");
  });

  it("leaves #86's witness sentence true: printed pages are named only where a film shows one", () => {
    expect(witnessSentence(film().shots)).toBeNull(); // no quote card in this fixture
    const cards = raw();
    cards.shots.push({ id: "Q1", kind: "card", start_s: 2000, end_s: 2010, mark: { class: "CARD" }, text: ["\"The city is burning.\"", "Jack London, Collier's, 5 May 1906"] });
    expect(witnessSentence(parseSources(cards).shots)).toBe("Its witnesses are quoted on cards and printed pages.");
    cards.shots = cards.shots.filter((s: { id: string }) => !["2.2", "2.5", "2.10"].includes(s.id));
    expect(witnessSentence(parseSources(cards).shots)).toBe("Its witnesses are quoted on cards.");
  });
});

describe("a frame held from archive film", () => {
  it("prints Frame of archive film for a still whose id extends a footage item the film shows, from the same archive item", () => {
    const d = film();
    const footage = filmFootage(d.shots);
    expect([...footage]).toEqual([["MS-F01", "https://archive.org/details/MarketStreet19064KScan20181016"]]);
    expect(what(d, "2.1a")).toBe("Frame of archive film, 1906-04, held 52 s");
    expect(what(d, "2.1b")).toBe("Frame of archive film, 1906-04, held 39 s");
    // without the film's footage, the still says only what is certain of it
    expect(shotWhat(shot(d, "2.1a"), NONE)).toBe("Photograph, 1906-04, held 52 s");
    // an id that merely starts with the same letters is no frame of it
    expect(stillKind(still({ ledger_id: "MS-F012", item_url: "https://archive.org/details/MarketStreet19064KScan20181016" }), footage)).toBe("photograph");
    // the id extends the footage's, but the item is another one: not a frame of that film
    expect(stillKind(still({ ledger_id: "MS-F01-PALACE-9" }), footage)).toBe("photograph");
  });

  it("keeps Photograph for a filmstrip frame, a still photograph, and leaves the archive film's own row alone", () => {
    expect(what(partition(), "1.4")).toMatch(/^Photograph, /);
    const d = film();
    expect(what(d, "2.3")).toBe("Photograph, 1906-04-18, held 8 s");
    expect(entryWhat(shot(d, "1.1"), filmFootage(d.shots))).toBe("Film, 1906-04, 295 s, from 4:10 to 9:05 of the archive's copy");
  });
});

describe("the item link names what the item is", () => {
  it("says map, page, film or photograph from the same kind as the What row", () => {
    const d = film();
    const footage = filmFootage(d.shots);
    expect(itemLinkLabel(shot(d, "2.4"), footage)).toBe("The map at the Library of Congress");
    expect(itemLinkLabel(shot(d, "2.5"), footage)).toBe("The page at the Library of Congress");
    expect(itemLinkLabel(shot(d, "2.10"), footage)).toBe("The page at the Library of Congress");
    expect(itemLinkLabel(shot(d, "2.2"), footage)).toBe("The page at the Internet Archive");
    expect(itemLinkLabel(shot(d, "2.1a"), footage)).toBe("The film at the Internet Archive");
    expect(itemLinkLabel(shot(d, "2.3"), footage)).toBe("The photograph at the Library of Congress");
    expect(itemLinkLabel(shot(d, "1.1"), footage)).toBe("The film at the Internet Archive");
    expect(itemLinkLabel(shot(smallpox(), "4.2a"), NONE)).toMatch(/^The photograph at /);
  });
});

describe("hostile values", () => {
  it("land as text in the What row, whatever kind the title reads as", async () => {
    const { whatNode } = await import("../web/src/shot-rows");
    const footage = filmFootage(film().shots);
    for (const over of [
      { title: `Map of ${EVIL}` },
      { title: `${EVIL}, page 1` },
      { title: `Proclamation by ${EVIL}` },
      { title: EVIL, ledger_id: "MS-F01-PALACE-9", item_url: "https://archive.org/details/MarketStreet19064KScan20181016" },
      { title: EVIL, date: EVIL },
    ]) {
      const node = asFake(whatNode(still(over), footage));
      expect(node.all().filter((n) => n.tag !== "#text" && n.tag !== "#fragment" && n.tag !== "span")).toEqual([]);
      expect(node.textContent).not.toMatch(/[!—]/);
    }
    expect(asFake(whatNode(still({ title: EVIL, date: EVIL }), footage)).textContent).toBe(`Photograph, ${EVIL}, held 8 s`);
  });

  it("land as text in the item link", async () => {
    const { sourceRows } = await import("../web/src/shot-rows");
    const footage = filmFootage(film().shots);
    const cases: [Record<string, unknown>, string][] = [
      [{ title: `Map of ${EVIL}` }, "The map at the Library of Congress"],
      [{ title: `Proclamation by ${EVIL}` }, "The page at the Library of Congress"],
      [{ title: EVIL, ledger_id: "MS-F01-X", item_url: "https://archive.org/details/MarketStreet19064KScan20181016" }, "The film at the Internet Archive"],
      [{ title: EVIL, archive: EVIL, item_url: "https://example.org/x" }, `The photograph at ${EVIL}`],
    ];
    for (const [over, label] of cases) {
      const item = asFake(sourceRows(still(over), footage).find(([k]) => k === "Item")![1]);
      expect(item.all().filter((n) => n.tag !== "#text").map((n) => n.tag)).toEqual(["a"]);
      expect(item.textContent).toBe(label);
    }
  });
});

describe("the seconds by mark", () => {
  it("counts maps, pages, held frames and photographs together as ARCHIVE stills, never as photographs", () => {
    const rows = secondsByMark(film().shots);
    expect(rows.map((r) => r.label)).toContain("ARCHIVE stills");
    expect(rows.map((r) => r.label).join(" ")).not.toMatch(/photograph/i);
  });
});
