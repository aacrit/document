// "Notes on this film" (GRAMMAR A56): what the picture no longer says, from the
// film's sources.json (film-data.ts filmNotes). Every value is set as DOM text
// through el() and numerals(), never as markup: the strings come from a file.
import type { FilmNotes } from "./film-data";
import { dataSourcesNode, el, numerals, withDeeds } from "./site";

export const NO_NOTES = "This film states no notes beyond its sources.";

function block(heading: string, items: Node[]): HTMLElement {
  return el("div", { class: "note-block" }, el("h3", {}, heading), el("ul", {}, ...items.map((n) => el("li", {}, n))));
}

/** "a, b and c" */
function listed(parts: string[]): string {
  return parts.length < 2 ? parts.join("") : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

/** The section's intro, naming only the blocks notesNodes draws, so it is true for every film. */
export function notesIntro(n: FilmNotes): string {
  const parts: string[] = [];
  if (n.voices.length) parts.push("the voices");
  if (n.unnamed.length) parts.push("the speakers the record names only by role");
  if (n.gaps.length || n.statements.length) parts.push("the gaps in the record");
  if (n.mapNotes.length || n.mapData.length) parts.push("the notes on the maps");
  if (n.pictureNotes.length) parts.push("the notes on the pictures");
  if (n.licences.length) parts.push("the licences");
  return parts.length ? `What the picture does not say: ${listed(parts)}.` : "What the picture does not say.";
}

/** The section's body: one block per list sources.json fills, or one muted sentence when it fills none. */
export function notesNodes(n: FilmNotes): HTMLElement[] {
  const out: HTMLElement[] = [];
  if (n.voices.length) out.push(block("Voices", n.voices.map((t) => numerals(t))));
  if (n.unnamed.length) {
    const b = block("Speakers not named on screen", n.unnamed.map((t) => numerals(t)));
    b.insertBefore(el("p", { class: "muted small" }, "The record names these speakers only by role."), b.lastChild);
    out.push(b);
  }
  if (n.gaps.length || n.statements.length) {
    out.push(
      block("Gaps in the record", [
        ...n.gaps.map((g) => {
          const f = document.createDocumentFragment();
          f.append(el("span", {}, g.says));
          if (g.searched) f.append(" ", el("span", { class: "muted" }, numerals(g.searched)));
          return f;
        }),
        ...n.statements.map((t) => numerals(t)),
      ]),
    );
  }
  if (n.mapNotes.length || n.mapData.length) {
    const data = n.mapData.map((m) => {
      const f = document.createDocumentFragment();
      f.append(`${m.map}: Data: `, dataSourcesNode(m.sources));
      return f;
    });
    out.push(block("Notes on the maps", [...n.mapNotes.map((t) => withDeeds(t)), ...data]));
  }
  if (n.pictureNotes.length) out.push(block("Notes on the pictures", n.pictureNotes.map((t) => withDeeds(t))));
  if (n.licences.length) out.push(block("Licences", n.licences.map((t) => withDeeds(t))));
  if (!out.length) out.push(el("p", { class: "muted" }, NO_NOTES));
  return out;
}
