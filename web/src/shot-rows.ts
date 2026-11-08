// A shot's provenance rows on the Sources page: archive, author, item, licence, data, credit and treatment. CC BY
// asks for the title, the author, the source and the licence; every one of them is here. Values from sources.json
// are set as DOM text or as links checked by safeUrl, never as markup (tests/shot-rows.test.ts).
import { entryWhat, itemLinkLabel, kindLabel, safeUrl, shotTreatment, type Footage, type Shot, type TitleInput } from "./film-data";
import { dataSourcesNode, el, numerals, withDeeds } from "./site";

const same = (a: string, b: string): boolean => a.trim().toLowerCase() === b.trim().toLowerCase();

/** The author, when the file names one that no other row already shows (the archive, or inside the credit). */
export function authorOf(shot: Pick<Shot, "creator" | "archive" | "credit">): string | null {
  const who = shot.creator?.trim();
  if (!who) return null;
  if (shot.archive && same(who, shot.archive)) return null;
  if (shot.credit && shot.credit.toLowerCase().includes(who.toLowerCase())) return null;
  return who;
}

/** The credit: a link when it is an https url, plain text when it is any other url (scheme://), else text with its
 * licences linked to their deeds. */
export function creditNode(credit: string | null): Node | null {
  if (!credit) return null;
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(credit.trim())) { // a url; "Photo: Jane Doe, CC BY 4.0" is prose
    const url = safeUrl(credit.trim());
    return url ? el("a", { class: "source", href: url, rel: "noopener noreferrer" }, credit.trim()) : numerals(credit);
  }
  return withDeeds(credit);
}

/** An entry's "What" row: what the shot is (a map, a printed page, a frame of archive film, a photograph ...), as text. */
export function whatNode(shot: Shot, footage: Footage): Node {
  return numerals(entryWhat(shot, footage));
}

/** The MIT licence's text, linked where a CC licence links its deed (founder ruling 2026-11-07: MIT, for sound only,
 * is credited the same way as CC BY). */
export const MIT_URI = "https://opensource.org/license/mit";

/** A licence as a node: "MIT" linked to its text as "MIT licence", any CC id linked to its deed, else text. */
export function licenceNode(licence: string): Node {
  if (/^mit$/i.test(licence.trim())) return el("a", { href: MIT_URI, rel: "license noopener noreferrer" }, "MIT licence");
  return withDeeds(licence);
}

/** The series titles' inputs, one line each: the title (linked to its https page), whom it is by, its licence. */
export function titleInputsNode(inputs: TitleInput[] | undefined, byKind = false): Node | null {
  if (!inputs?.length) return null;
  // ruling 18: the "Drawn from" row says what each input is (a period record, a museum-object scan, a studio
  // texture); a sources.json made before it states no kind and prints as before
  const labelled = byKind && inputs.every((x) => kindLabel(x.kind));
  return el(
    "ul",
    { class: "title-inputs" },
    ...inputs.map((x) =>
      el(
        "li",
        {},
        labelled ? `${kindLabel(x.kind)}: ` : "",
        x.url ? el("a", { class: "source", href: x.url, rel: "noopener noreferrer" }, numerals(x.title)) : numerals(x.title),
        x.by ? ", by " : "",
        x.by ? numerals(x.by) : "",
        x.archive ? ", " : "",
        x.archive ? numerals(x.archive) : "",
        x.licence ? ", " : "",
        x.licence ? licenceNode(x.licence) : "",
      ),
    ),
  );
}

export function sourceRows(shot: Shot, footage: Footage): [string, Node | string | null][] {
  const url = safeUrl(shot.item_url);
  const author = authorOf(shot);
  return [
    ["Archive", shot.archive],
    ["By", author ? numerals(author) : null],
    ["Item", url ? el("a", { class: "source", href: url, rel: "noopener noreferrer", "data-item": "" }, itemLinkLabel(shot, footage)) : null],
    ["Licence", shot.licence ? withDeeds(shot.licence) : null],
    ["Data", shot.data_sources.length ? dataSourcesNode(shot.data_sources) : null],
    ["Credit", creditNode(shot.credit)],
    ["Drawn from", titleInputsNode(shot.title_records, true)],
    ["Sound", titleInputsNode(shot.title_sound)],
    ["Treatment", shotTreatment(shot)],
  ];
}
