// The Sources page's provenance rows for one shot (web/src/shot-rows.ts): CC BY's title, author, source and licence
// are all shown, every value from sources.json lands as text or as an https link, never as markup.
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { parseSources, type Shot } from "../web/src/film-data";
import { asFake, installFakeDocument, type FakeNode } from "./helpers/fake-dom";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const raw = () => JSON.parse(readFileSync(path.join(root, "tests/fixtures/sources-trailer.json"), "utf8"));
const EVIL = '"><img src=x onerror=alert(1)>';

let restore: () => void;
beforeAll(() => {
  restore = installFakeDocument();
});
afterAll(() => restore());

function shotWith(over: Record<string, unknown>): Shot {
  const j = raw();
  Object.assign(j.shots[1], over);
  return parseSources(j).shots[1];
}

async function rows(shot: Shot): Promise<Map<string, FakeNode>> {
  const { sourceRows } = await import("../web/src/shot-rows");
  return new Map(sourceRows(shot).filter(([, v]) => v !== null && v !== "").map(([k, v]) => [k, asFake(v)]));
}

describe("a shot's provenance rows", () => {
  it("shows the author of a CC BY photograph whose file has no credit", async () => {
    const r = await rows(shotWith({ creator: "Kim Carpenter (Flickr)", archive: "Wikimedia Commons", credit: null, licence: "CC BY 2.0" }));
    expect(r.get("By")?.textContent).toBe("Kim Carpenter (Flickr)");
    const lic = r.get("Licence")!.all().find((n) => n.tag === "a")!;
    expect([lic.textContent, lic.attrs.href]).toEqual(["CC BY 2.0", "https://creativecommons.org/licenses/by/2.0/"]);
    expect([...r.keys()].indexOf("By")).toBeLessThan([...r.keys()].indexOf("Licence"));
  });

  it("shows no author row when the archive or the credit already names them", async () => {
    expect((await rows(shotWith({ creator: "void document studio", archive: "void document studio", credit: null }))).has("By")).toBe(false);
    const r = await rows(shotWith({ creator: "Luigi Novi", archive: "Wikimedia Commons", credit: "Photograph by Luigi Novi, CC BY 3.0" }));
    expect(r.has("By")).toBe(false);
    const credit = r.get("Credit")!;
    expect(credit.textContent).toBe("Photograph by Luigi Novi, CC BY 3.0");
    expect(credit.all().find((n) => n.tag === "a")?.attrs.href).toBe("https://creativecommons.org/licenses/by/3.0/");
  });

  it("shows a credit that is a url: an https one as a link, any other as text, never hidden", async () => {
    const https = (await rows(shotWith({ credit: "https://www.flickr.com/photos/x/1" }))).get("Credit")!;
    const a = https.all().find((n) => n.tag === "a")!;
    expect(a.attrs.href).toBe("https://www.flickr.com/photos/x/1");
    expect(a.attrs.rel.split(" ")).toContain("noopener");
    const http = (await rows(shotWith({ credit: "http://example.org/x" }))).get("Credit")!;
    expect(http.textContent).toBe("http://example.org/x");
    expect(http.all().some((n) => n.tag === "a")).toBe(false);
    const js = (await rows(shotWith({ credit: "javascript:alert(1)" }))).get("Credit")!;
    expect(js.all().some((n) => n.tag === "a")).toBe(false);
    expect(js.textContent).toBe("javascript:alert(1)");
  });

  it("reads a credit with a colon in its prose as prose, its licence linked to the deed", async () => {
    const r = await rows(shotWith({ credit: "Photo: Jane Doe, CC BY 4.0" }));
    const credit = r.get("Credit")!;
    expect(credit.textContent).toBe("Photo: Jane Doe, CC BY 4.0");
    const links = credit.all().filter((n) => n.tag === "a");
    expect(links.map((a) => [a.textContent, a.attrs.href])).toEqual([["CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/"]]);
  });

  it("sets a hostile creator, credit, archive and licence as text", async () => {
    const r = await rows(shotWith({ creator: EVIL, credit: `${EVIL} CC BY 4.0`, archive: `${EVIL}x`, licence: EVIL }));
    const all = [...r.values()].flatMap((n) => n.all());
    expect(all.some((n) => n.tag === "img")).toBe(false);
    expect(all.every((n) => !("onerror" in n.attrs) && !("src" in n.attrs))).toBe(true);
    expect(all.filter((n) => n.tag === "a").every((n) => n.attrs.href.startsWith("https://"))).toBe(true);
    expect(r.get("Licence")?.textContent).toBe(EVIL);
  });
});
