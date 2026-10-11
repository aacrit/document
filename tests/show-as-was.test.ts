// GRAMMAR A0, the founding principle, on the site: show as was, not as is,
// and never tell. films.json copy, the page templates and every generated
// page (its visible words and its meta description) are held to the same
// lists the engine holds the film to (studio/show-as-was.json), matched the
// same way: the text cases in tests/fixtures/a0-cases.json run here and in
// studio/tests/test_a0_show_as_was.py.
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { loadRegistry, readTemplates, registryProblems, sitePages } from "../scripts/lib/films.mjs";
import {
  LEXICON,
  copyFindings,
  horizonFromDates,
  modernNameHits,
  parseDate,
  phraseHits,
  yearsIn,
} from "../scripts/lib/show-as-was.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (f: string) => readFileSync(path.join(root, f), "utf8");
const CASES = JSON.parse(read("tests/fixtures/a0-cases.json"));
type Case = { text: string; expect: unknown; as_of?: string | null };
const clone = <T>(x: T): T => JSON.parse(JSON.stringify(x));

describe("the A0 lists match as the engine's do (tests/fixtures/a0-cases.json)", () => {
  it.each(CASES.hindsight as Case[])("hindsight: $text", (c) => {
    expect(phraseHits(c.text, LEXICON.hindsight).map((h: { phrase: string }) => h.phrase)).toEqual(c.expect);
  });
  it.each(CASES.never_tell as Case[])("never tell: $text", (c) => {
    expect(phraseHits(c.text, LEXICON.never_tell).map((h: { phrase: string }) => h.phrase)).toEqual(c.expect);
  });
  it.each(CASES.modern_names as Case[])("modern names: $text", (c) => {
    expect(modernNameHits(c.text, parseDate(c.as_of)).map((h: { modern: string }) => h.modern)).toEqual(c.expect);
  });
  it.each(CASES.years as Case[])("years: $text", (c) => {
    expect(yearsIn(c.text)).toEqual(c.expect);
  });
  it.each(CASES.dates as { value: string | number; expect: unknown }[])("dates: $value", (c) => {
    expect(parseDate(c.value)).toEqual(c.expect);
  });
});

/** The words a page shows: no script, style or tags, entities for quotes and ampersands decoded. */
function visible(html: string): string {
  return html
    .replace(/<(script|style)[\s\S]*?<\/\1>/g, " ")
    .replace(/<!--[\s\S]*?-->/g, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/\{\{[^}]+\}\}/g, " ")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ");
}
const metaDescription = (html: string) => /<meta name="description" content="([^"]*)"/.exec(html)?.[1] ?? "";

describe("the site's copy shows as was and never tells", () => {
  const registry = loadRegistry(path.join(root, "films.json"));
  const templates = readTemplates(path.join(root, "web"));
  const pages = sitePages(registry, templates);

  it("films.json: every film's title, dates, logline, synopsis, content note and shows", () => {
    for (const f of registry.films) {
      const horizon = horizonFromDates(f.dates);
      expect(horizon, `${f.slug}: its dates name the end of its window`).not.toBeNull();
      for (const k of ["title", "dates", "logline", "synopsis", "content_note", "shows"]) {
        if (typeof f[k] === "string") expect(copyFindings(`${f.slug} ${k}`, f[k], { horizon }), `${f.slug} ${k}`).toEqual([]);
      }
    }
  });

  it("the templates' own words", () => {
    for (const [name, html] of Object.entries(templates as Record<string, string>)) {
      expect(copyFindings(`web/templates/${name}.html`, visible(html)), name).toEqual([]);
    }
  });

  it("every generated page's words and meta description, against the film it shows", () => {
    type F = { slug: string; status: string; dates: string };
    const films = registry.films as F[];
    const marquee = films.find((f) => f.status === "live") as F;
    // the home page lists every film with its own dates, so its words are read against the latest horizon among them
    const latest = films.map((f) => horizonFromDates(f.dates)).sort((a, b) => (a![1] < b![1] ? 1 : -1))[0];
    for (const [page, html] of Object.entries(pages as Record<string, string>)) {
      const own = films.find((f) => page.startsWith(`f/${f.slug}/`));
      const horizon = horizonFromDates((own ?? marquee).dates);
      expect(copyFindings(`${page} (description)`, metaDescription(html), { horizon }), page).toEqual([]);
      expect(copyFindings(page, visible(html), { horizon: own ? horizon : latest }), page).toEqual([]);
    }
  });

  it("refuses an entry that tells, looks back or uses a later name", () => {
    const bad = (mut: (f: Record<string, unknown>) => void) => {
      const r = clone(registry);
      mut(r.films[0]);
      return registryProblems(r).join("\n");
    };
    expect(bad((f) => (f.dates = "1946 to today"))).toMatch(/dates: hindsight \(present-day\): "today"/);
    expect(bad((f) => (f.synopsis = "The line would later be called a scar."))).toMatch(/synopsis: hindsight \(future-in-past\): "would later"/);
    expect(bad((f) => (f.synopsis = "In 1971 the east became a country."))).toMatch(/synopsis: hindsight \(year-after-horizon\): "1971"/);
    expect(bad((f) => (f.logline = "the roads to Dhaka"))).toMatch(/logline: modern name "Dhaka": the period wrote Dacca/);
    expect(bad((f) => (f.synopsis = "A tragic summer, told with the record."))).toMatch(/synopsis: tells \(editorial-adjectives\): "tragic"/);
    expect(bad((f) => (f.shows = "We believe this film shows no bodies."))).toMatch(/shows: tells \(first-person-opinion\): "we believe"/);
    // and lets the period speak: a quote may say what the narrator may not
    expect(bad((f) => (f.synopsis = 'Nehru told the Assembly, "today we are free".'))).toBe("");
    expect(bad((f) => (f.logline = "the roads to Dacca"))).toBe("");
  });
});
