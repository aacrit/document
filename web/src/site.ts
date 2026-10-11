// Shared by every public page: the film's media URLs, loading its
// sources.json, and a small element builder (text only, never innerHTML,
// so nothing in a sources file can inject markup).
import { parseSources, type FilmSources, type MarkSpan, markHook, markWords } from "./film-data";

export const mediaUrl = (slug: string, file: string): string => `/media/${slug}/${file}`;
export const filmPath = (slug: string): string => `/f/${slug}/`;

const loading = new Map<string, Promise<FilmSources>>();

/** A film's sources.json, fetched once per page however many parts of it ask (the home page's marquee and its theatre). */
export function loadSources(slug: string): Promise<FilmSources> {
  let p = loading.get(slug);
  if (!p) {
    p = fetch(mediaUrl(slug, "sources.json")).then(async (res) => {
      if (!res.ok) throw new Error(`sources.json: status ${res.status}`);
      return parseSources(await res.json());
    });
    // A failed load is not kept: a later ask tries again.
    p.catch(() => loading.delete(slug));
    loading.set(slug, p);
  }
  return p;
}

type Child = Node | string | null | undefined | false;

/** Builds an element: el("p", { class: "t" }, "text", child). Attributes are set as attributes; children as text or nodes. */
export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Record<string, string | undefined> = {},
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== undefined) node.setAttribute(k, v);
  for (const c of children) if (c !== null && c !== undefined && c !== false) node.append(c);
  return node;
}

/** Text with every run of digits set in the data face (Ink & Momentum: numerals are tabular, always). */
export function numerals(text: string): Node {
  const frag = document.createDocumentFragment();
  for (const part of text.split(/(\d[\d,.:]*\d|\d)/)) {
    if (!part) continue;
    frag.append(/^\d/.test(part) ? el("span", { class: "num" }, part) : part);
  }
  return frag;
}

/** A mark plate as on screen (house.css .mark): the class word, then the detail. */
export function markPlate(m: Pick<MarkSpan, "class" | "detail">, extraClass = ""): HTMLSpanElement {
  const w = markWords(m);
  const label = w.detail ? `${w.cls} ${w.detail}` : w.cls;
  return el(
    "span",
    { class: `mark${extraClass ? ` ${extraClass}` : ""}`, "data-class": markHook(m.class), role: "img", "aria-label": label },
    el("span", { class: "cls" }, w.cls),
    w.detail ? el("span", { class: "det" }, numerals(w.detail)) : null,
  );
}

export function byId<T extends HTMLElement = HTMLElement>(id: string): T {
  const node = document.getElementById(id);
  if (!node) throw new Error(`#${id} is missing`);
  return node as T;
}
