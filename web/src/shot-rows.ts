// A shot's provenance rows on the Sources page: archive, author, item, licence, data, credit and treatment. CC BY
// asks for the title, the author, the source and the licence; every one of them is here. Values from sources.json
// are set as DOM text or as links checked by safeUrl, never as markup (tests/shot-rows.test.ts).
import { itemLinkLabel, safeUrl, shotTreatment, type Shot } from "./film-data";
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

/** The credit: a link when it is an https url, plain text when it is any other url, else text with its licences linked. */
export function creditNode(credit: string | null): Node | null {
  if (!credit) return null;
  if (/^[a-z][a-z0-9+.-]*:/i.test(credit.trim())) {
    const url = safeUrl(credit.trim());
    return url ? el("a", { class: "source", href: url, rel: "noopener noreferrer" }, credit.trim()) : numerals(credit);
  }
  return withDeeds(credit);
}

export function sourceRows(shot: Shot): [string, Node | string | null][] {
  const url = safeUrl(shot.item_url);
  const author = authorOf(shot);
  return [
    ["Archive", shot.archive],
    ["By", author ? numerals(author) : null],
    ["Item", url ? el("a", { class: "source", href: url, rel: "noopener noreferrer", "data-item": "" }, itemLinkLabel(shot)) : null],
    ["Licence", shot.licence ? withDeeds(shot.licence) : null],
    ["Data", shot.data_sources.length ? dataSourcesNode(shot.data_sources) : null],
    ["Credit", creditNode(shot.credit)],
    ["Treatment", shotTreatment(shot)],
  ];
}
