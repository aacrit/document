// What each still is, as the Sources page prints it in an entry's "What" row: a map, a printed page, a frame held from
// a film the archive holds, or a photograph. A printed label has to be true: Market Street's map sheet, magazine and
// newspaper pages and held frames of its 1906 ride all used to print "Photograph". The shots are copied verbatim from
// Market Street's release sources.json (tests/fixtures/sources-market-street-stills.json).
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { entryWhat, filmFootage, parseSources, shotWhat, stillKind, type FilmSources, type Shot } from "../web/src/film-data";
import { asFake, installFakeDocument } from "./helpers/fake-dom";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const raw = () => JSON.parse(readFileSync(path.join(root, "tests/fixtures/sources-market-street-stills.json"), "utf8"));
const EVIL = '"><img src=x onerror=alert(1)>';

const film = (): FilmSources => parseSources(raw());
const shot = (d: FilmSources, id: string): Shot => d.shots.find((s) => s.id === id)!;
/** Market Street's photograph (2.3, Sacramento Street), re-titled and re-filed as another film's still would be. */
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

describe("what a still is", () => {
  it("prints Map for the 1899 Sanborn sheet, an archive still with no data, by the word map in its title's head", () => {
    const d = film();
    const sanborn = shot(d, "2.4");
    expect(sanborn.data_sources).toEqual([]);
    expect(stillKind(sanborn, filmFootage(d.shots))).toBe("map");
    expect(shotWhat(sanborn, filmFootage(d.shots))).toBe("Map, 1899, held 14 s");
  });

  it("prints Map for a drawn map's data or mark (isMapShot), a map-sheet ledger item, and a mark that names a map", () => {
    expect(shotWhat(still({ data_sources: [{ id: "Natural Earth", url: "https://www.naturalearthdata.com/", licence: "public domain" }] }))).toBe("Map, 1906-04-18, held 8 s");
    // Smallpox's CIA sheets ("West Africa (countries, roads ...)") sit in the house's map-sheet ledger, "sheets"
    expect(shotWhat(still({ ledger: "sheets", title: "West Africa (countries, roads and caravan routes, railways), US Central Intelligence Agency, 1963" }))).toMatch(/^Map, /);
    // Partition's Survey of India sheet 43 P is filed with the stills, but its mark says "1943 map"
    expect(shotWhat(still({ mark: { class: "ARCHIVE", detail: "", label: "Archive · 1943 map · marks drawn" }, title: "Survey of India quarter-inch sheet 43 P Gurdaspur" }))).toMatch(/^Map, /);
    // a WHO map slide titled "(map, Source: WHO)" at its end
    expect(shotWhat(still({ title: "World-wide smallpox endemic areas, June 1971 (map, Source: WHO)" }))).toMatch(/^Map, /);
    // a drawn map keeps saying it was drawn
    const drawn = still({ kind: "drawn", mark: { class: "DRAWN", detail: "from map data", label: "Drawn · from map data" } });
    expect(shotWhat(drawn)).toBe("Drawn map, 8 s");
    expect(shotWhat(still({ kind: "drawn", mark: { class: "DRAWN", detail: "from Hansard", label: "Drawn · from Hansard" } }))).toBe("Drawn, 8 s");
  });

  it("keeps Photograph for a photograph of people beside a map: the map is in the picture, not the item", () => {
    expect(shotWhat(still({ title: "J. Donald Millar beside a Shapona display: map of West Africa, a description of Yoruba beliefs, and a votive sculpture, 1968" }))).toMatch(/^Photograph, /);
    expect(shotWhat(still({ title: "A Shapona display: map of West Africa, a description of Yoruba beliefs, and a votive sculpture, 1968" }))).toMatch(/^Photograph, /);
    expect(shotWhat(still({ title: "Sheetaladevi: The Smallpox Goddess, Kalighat painting, Kolkata, c. 1890" }))).toMatch(/^Photograph, /);
  });

  it("prints Printed page for a magazine page (isPrintedPage)", () => {
    const d = film();
    expect(shotWhat(shot(d, "2.2"), filmFootage(d.shots))).toBe("Printed page, 1906-07, held 20 s");
  });

  it("prints Printed page for a newspaper's front page, The Call-Chronicle-Examiner of 19 April 1906, page 1", () => {
    const d = film();
    const front = shot(d, "2.10");
    expect(front.title).toBe("The Call-Chronicle-Examiner, 19 April 1906, page 1");
    expect(stillKind(front, filmFootage(d.shots))).toBe("page");
    expect(shotWhat(front, filmFootage(d.shots))).toBe("Printed page, 1906-04-19, held 36 s");
  });

  it("prints Frame of archive film for a still held from a footage item the film shows (MS-F01-*)", () => {
    const d = film();
    const footage = filmFootage(d.shots);
    expect([...footage]).toEqual(["MS-F01"]);
    expect(shotWhat(shot(d, "2.1a"), footage)).toBe("Frame of archive film, 1906-04, held 52 s");
    expect(shotWhat(shot(d, "2.1b"), footage)).toBe("Frame of archive film, 1906-04, held 39 s");
    // without the film's footage to read it from, the still says only what is certain of it
    expect(shotWhat(shot(d, "2.1a"))).toBe("Photograph, 1906-04, held 52 s");
    // an id that merely starts with the same letters is no frame of it
    expect(stillKind(still({ ledger_id: "MS-F012" }), footage)).toBe("photograph");
  });

  it("keeps Photograph for everything else", () => {
    const d = film();
    expect(shotWhat(shot(d, "2.3"), filmFootage(d.shots))).toBe("Photograph, 1906-04-18, held 8 s");
    // a filmstrip frame (Partition's Gandhi on the way to Noakhali) is a still photograph, not a frame of footage
    expect(shotWhat(still({ title: "Gandhi on the way to Noakhali, 1946 (filmstrip frame no. 19)" }), filmFootage(d.shots))).toMatch(/^Photograph, /);
    // the archive film itself is unchanged
    expect(entryWhat(shot(d, "1.1"), filmFootage(d.shots))).toBe("Film, 1906-04, 295 s, from 4:10 to 9:05 of the archive's copy");
  });

  it("lands every value as text: a hostile title is classified, never parsed, and no element comes of it", async () => {
    const { whatNode } = await import("../web/src/shot-rows");
    const d = film();
    const footage = filmFootage(d.shots);
    for (const over of [
      { title: `Map of ${EVIL}` },
      { title: `${EVIL}, page 1` },
      { title: EVIL, ledger_id: "MS-F01-PALACE-9" },
      { title: EVIL, date: EVIL },
    ]) {
      const node = asFake(whatNode(still(over), footage));
      expect(node.all().filter((n) => n.tag !== "#text" && n.tag !== "#fragment" && n.tag !== "span")).toEqual([]);
      expect(node.all().some((n) => n.tag === "img")).toBe(false);
      expect(node.textContent).not.toMatch(/[!—]/);
    }
    expect(asFake(whatNode(still({ title: EVIL, date: EVIL }), footage)).textContent).toBe(`Photograph, ${EVIL}, held 8 s`);
  });
});
