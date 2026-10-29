// A minimal document for the renderers' tests: elements by tag, and text nodes, with no HTML parser at all, so a
// value from a file that turned into an element would have had to go through createElement (tests/notes.test.ts
// keeps its own copy of the same idea).
export class FakeNode {
  children: FakeNode[] = [];
  parent: FakeNode | null = null;
  attrs: Record<string, string> = {};
  constructor(
    public tag: string,
    public text = "",
  ) {}
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
  get textContent(): string {
    return this.tag === "#text" ? this.text : this.children.map((c) => c.textContent).join("");
  }
  all(): FakeNode[] {
    return [this, ...this.children.flatMap((c) => c.all())];
  }
}

/** Installs the fake document; returns the function that puts the real one back. */
export function installFakeDocument(): () => void {
  const g = globalThis as unknown as { document?: unknown };
  const saved = g.document;
  g.document = {
    createElement: (t: string) => new FakeNode(t),
    createDocumentFragment: () => new FakeNode("#fragment"),
    createTextNode: (t: string) => new FakeNode("#text", t),
  };
  return () => {
    g.document = saved;
  };
}

/** A node or string from a renderer, as a FakeNode (a string becomes a text node). */
export const asFake = (x: unknown): FakeNode => (typeof x === "string" ? new FakeNode("#text", x) : (x as FakeNode));
