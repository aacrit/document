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
