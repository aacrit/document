// "Notes on this film" (web/src/notes.ts, GRAMMAR A56): every value from
// sources.json is set as DOM text, never parsed as markup. There is no DOM
// library in the gate, so a minimal document records what the renderer builds:
// elements by tag, and text nodes, with no HTML parser at all, so a value that
// turned into an element would have to go through createElement.
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import type { FilmNotes } from "../web/src/film-data";

class FakeNode {
  children: FakeNode[] = [];
  parent: FakeNode | null = null;
  constructor(
    public tag: string,
    public text = "",
  ) {}
  attrs: Record<string, string> = {};
  setAttribute(k: string, v: string): void {
    this.attrs[k] = v;
  }
  append(...xs: (FakeNode | string)[]): void {
    for (const x of xs) {
      const n = typeof x === "string" ? new FakeNode("#text", x) : x;
      if (n.tag === "#fragment") {
        for (const c of n.children) this.append(c);
        continue;
      }
      n.parent = this;
      this.children.push(n);
    }
  }
  get lastChild(): FakeNode | null {
    return this.children[this.children.length - 1] ?? null;
  }
  insertBefore(n: FakeNode, ref: FakeNode | null): void {
    const i = ref ? this.children.indexOf(ref) : this.children.length;
    n.parent = this;
    this.children.splice(i < 0 ? this.children.length : i, 0, n);
  }
  get textContent(): string {
    return this.tag === "#text" ? this.text : this.children.map((c) => c.textContent).join("");
  }
  all(): FakeNode[] {
    return [this, ...this.children.flatMap((c) => c.all())];
  }
}

const g = globalThis as unknown as { document?: unknown };
let saved: unknown;
beforeAll(() => {
  saved = g.document;
  g.document = {
    createElement: (t: string) => new FakeNode(t),
    createDocumentFragment: () => new FakeNode("#fragment"),
    createTextNode: (t: string) => new FakeNode("#text", t),
  };
});
afterAll(() => {
  g.document = saved;
});

const EVIL = '"><img src=x onerror=alert(1)>';
const notes = (over: Partial<FilmNotes> = {}): FilmNotes => ({
  voices: [],
  unnamed: [],
  gaps: [],
  statements: [],
  mapNotes: [],
  mapData: [],
  licences: [],
  ...over,
});

describe("notes on this film", () => {
  it("renders a hostile value from every list as text, never as an element", async () => {
    const { notesNodes } = await import("../web/src/notes");
    const nodes = notesNodes(
      notes({
        voices: [EVIL],
        unnamed: [EVIL],
        gaps: [{ says: EVIL, searched: EVIL }],
        statements: [EVIL],
        mapNotes: [EVIL],
        licences: [EVIL],
      }) as never,
    ) as unknown as FakeNode[];
    const all = nodes.flatMap((n) => n.all());
    expect(all.some((n) => n.tag === "img")).toBe(false);
    expect(all.every((n) => !("onerror" in n.attrs) && !("src" in n.attrs))).toBe(true);
    const text = nodes.map((n) => n.textContent).join("\n");
    expect(text.split(EVIL).length - 1).toBe(7);          // every value lands verbatim, as text (the gap holds two)
    expect(all.filter((n) => n.tag === "li")).toHaveLength(6);
  });

  it("links a licence id to its deed and a data source to its https url, and nothing hostile to anything", async () => {
    const { notesNodes } = await import("../web/src/notes");
    const nodes = notesNodes(
      notes({
        mapData: [
          {
            map: EVIL,
            sources: [
              { name: "GeoNames", url: "https://www.geonames.org/", licence: "CC BY 4.0" },
              { name: EVIL, url: `https://example.org/${EVIL}`, licence: EVIL },
              { name: "Plain http", url: "http://example.org/", licence: null },
              { name: "Script", url: "javascript:alert(1)", licence: null },
            ],
          },
        ],
        licences: ["CC-BY-4.0 (contains GeoNames data (CC BY 4.0)): 1 shot", "CC0: 3 shots", "public domain: 38 shots", EVIL],
      }) as never,
    ) as unknown as FakeNode[];
    const all = nodes.flatMap((n) => n.all());
    expect(all.some((n) => n.tag === "img")).toBe(false);
    expect(all.every((n) => !("onerror" in n.attrs) && !("src" in n.attrs))).toBe(true);
    const links = all.filter((n) => n.tag === "a");
    expect(links.map((a) => [a.textContent, a.attrs.href])).toEqual([
      ["GeoNames", "https://www.geonames.org/"],
      ["CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/"],
      [EVIL, "https://example.org/%22%3E%3Cimg%20src=x%20onerror=alert(1)%3E"],
      ["CC-BY-4.0", "https://creativecommons.org/licenses/by/4.0/"],
      ["CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/"],
      ["CC0", "https://creativecommons.org/publicdomain/zero/1.0/"],
    ]);
    expect(links.every((a) => a.attrs.href.startsWith("https://") && a.attrs.rel.split(" ").includes("noopener"))).toBe(true);
    const text = nodes.map((n) => n.textContent).join("\n");
    expect(text).toContain("Plain http");                         // a refused url leaves the name, unlinked
    expect(text).toContain("public domain: 38 shots");
    expect(text.split(EVIL).length - 1).toBe(4);                  // map, name, licence, and the licence line: as text
  });

  it("omits an empty list and says so in one sentence when every list is empty", async () => {
    const { notesNodes, NO_NOTES } = await import("../web/src/notes");
    const empty = notesNodes(notes()) as unknown as FakeNode[];
    expect(empty).toHaveLength(1);
    expect(empty[0].textContent).toBe(NO_NOTES);
    const one = notesNodes(notes({ statements: ["Women speak 4% of the readings."] })) as unknown as FakeNode[];
    expect(one).toHaveLength(1);
    expect(one[0].textContent).toContain("Gaps in the record");
    expect(one[0].textContent).toContain("Women speak 4% of the readings.");
  });
});
