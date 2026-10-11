// The public pages keep the G2 design's standing rules (design/spec.md,
// "Shared rules (public)"): the void family footer everywhere, the theatre
// dark, no studio language, amber only on sourced things, English captions
// only until Hindi and Urdu are reviewed, and the sober content note.
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (f: string) => readFileSync(path.join(root, f), "utf8");
const pages = readdirSync(path.join(root, "web"), { recursive: true, encoding: "utf8" })
  .map((f) => `web/${f.split(path.sep).join("/")}`)
  // web/templates/ holds the page templates the build fills from films.json; the pages are what it writes.
  .filter((f) => f.endsWith(".html") && !f.startsWith("web/templates/"));
const PUBLIC = ["web/index.html", "web/f/partition-of-india/index.html", "web/f/partition-of-india/sources/index.html", "web/f/partition-of-india/correct/index.html"];
const visible = (html: string) =>
  html
    .replace(/<script[\s\S]*?<\/script>/g, " ")
    .replace(/<(?:svg|head)[\s\S]*?<\/(?:svg|head)>/g, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .replace(/ ([.,;:])/g, "$1");
const clientScripts = readdirSync(path.join(root, "web/src")).filter((f) => f.endsWith(".ts"));
const stringLiterals = (src: string) => [...src.matchAll(/"([^"\n]*)"|`([^`]*)`/g)].map((m) => m[1] ?? m[2]).join("\n");

describe("the public pages", () => {
  it("are the four charter surfaces plus privacy", () => {
    expect([...pages].sort()).toEqual([...PUBLIC, "web/privacy.html"].sort());
  });

  it("every page names the void family, linked, and the licence; every public page links Privacy", () => {
    for (const page of pages) {
      const html = read(page);
      expect(visible(html), page).toContain("void document is part of void, with void news and void history.");
      expect(html, page).toContain('<a href="https://news.voidvision.org/" rel="noopener">void news</a>');
      expect(html, page).toContain('<a href="https://news.voidvision.org/history/" rel="noopener">void history</a>');
      expect(visible(html), page).toContain("Films are free to watch and licensed CC BY 4.0.");
      if (PUBLIC.includes(page)) expect(html, page).toContain('<a href="/privacy">Privacy</a>');
    }
  });

  it("the four surfaces are the dark theatre; only privacy follows the viewer's preference", () => {
    for (const page of PUBLIC) expect(read(page), page).toMatch(/<html lang="en" data-theme="dark">/);
    expect(read("web/privacy.html")).not.toContain("data-theme");
  });

  it("carry no studio language, on the page or in what the scripts write", () => {
    const banned = /\b(render(?:ed|ing|s)?|pipeline|studio|Director's Lens|ledger|pending|slot|cleared|read-by|refrain|end frame|screenplay|engine)\b/i;
    for (const page of pages) expect(visible(read(page)), page).not.toMatch(banned);
    for (const page of pages) expect(read(page), page).not.toMatch(/href="\/studio/);
    for (const f of clientScripts) expect(stringLiterals(read(`web/src/${f}`)), f).not.toMatch(banned);
  });

  it("amber only on sourced things: safelight classes sit only on credits and source links", () => {
    for (const page of pages) {
      for (const m of read(page).matchAll(/<(\w+)\b[^>]*class="([^"]*\b(?:safe|source)\b[^"]*)"[^>]*>/g)) {
        const [, tag, cls] = m;
        const ok = (tag === "a" && /\bsource\b/.test(cls)) || (tag === "p" && /\b(credits|w)\b/.test(cls));
        expect(ok, `${page}: <${tag} class="${cls}">`).toBe(true);
      }
    }
  });

  it("the home page says what the film shows and does not show; how it is voiced and whether any of it is AI-generated come from sources.json", () => {
    const html = read("web/index.html");
    // The theatre is the film page's own player (its marks legend names AI-GENERATED as a class): the claims are judged outside it.
    const home = visible(html.replace(/<dialog class="theatre"[\s\S]*?<\/dialog>/, " "));
    expect(home).toContain("This film shows no bodies or killing.");
    // A dip's black hold carries no mark (A11) and the label fades to a glyph (A16): every shot carries one, not every second.
    expect(home).toContain("Every shot carries a mark that says what it is.");
    expect(home).not.toMatch(/Every second/);
    // Filled by home.ts from voiceSentence and aiSentence (film-data.ts), never typed.
    expect(html).toMatch(/id="home-voice"><\/span>/);
    expect(html).toMatch(/id="home-ai"><\/span>/);
    expect(home).not.toMatch(/read by a computer|AI-generated|no recording is imitated/i);
    expect(read("web/src/home.ts")).toMatch(/byId\("home-voice"\)\.textContent = voiceSentence\(data\.readings, data\.narrator\)/);
    expect(read("web/src/home.ts")).toMatch(/byId\("home-ai"\)\.textContent = aiSentence\(data\.shots\)/);
    expect(read("web/index.html")).toContain('href="/f/partition-of-india/"');
    expect(home).toMatch(/\bWatch\b/);
    // The Trailer button exists but is hidden until sources.json declares a trailer; its note is never typed.
    expect(html).toMatch(/<button[^>]*id="trailer-open"[^>]*\bhidden\b[^>]*>Trailer<\/button>/);
    expect(html).toMatch(/<p class="note" id="trailer-note"><\/p>/);
    expect(html).not.toMatch(/five minutes/);
    const homeTs = read("web/src/home.ts");
    expect(homeTs).toMatch(/if \(data\.trailer\) \{[^}]*byId\("trailer-open"\)\.hidden = false;/);
    expect(homeTs.match(/trailer-open"\)\.hidden = false/g)).toHaveLength(1);
    expect(home).toMatch(/\bSources\b/);
  });

  it("the film page offers English captions only, and says Hindi and Urdu are being reviewed", () => {
    const film = read("web/f/partition-of-india/index.html");
    const tracks = [...film.matchAll(/<track\b[^>]*>/g)].map((m) => m[0]);
    expect(tracks).toHaveLength(1);
    expect(tracks[0]).toContain('srclang="en"');
    expect(film).not.toMatch(/lang="(hi|ur)"|captions-(hi|ur)/);
    expect(visible(film)).toContain("Hindi and Urdu subtitles are being reviewed.");
    expect(film).toContain('href="https://news.voidvision.org/history/partition-of-india/"');
    expect(visible(film)).toContain("Listen to void history's audio documentary on the Partition of India");
  });

  it("prints no claim about the film that is not derived from its sources.json", () => {
    const film = read("web/f/partition-of-india/index.html");
    const home = read("web/index.html");
    // The AI and voice sentences, the accounts and the credits are filled by script from sources.json (film-data.ts).
    for (const id of ["ai-sentence", "ai-sentence-legend", "voice-sentence", "voice-sentence-legend", "voice-note", "accounts"]) {
      expect(film, id).toMatch(new RegExp(`id="${id}"></`));
    }
    expect(visible(film)).not.toMatch(/AI-generated images|Accounts from/);
    expect(home).toMatch(/<p class="credits safe" id="credits-line"><\/p>/);
    expect(home).toMatch(/<p class="frame-credit" id="poster-credit"><\/p>/);
    for (const page of [film, home]) {
      expect(page).not.toMatch(/Wikimedia Commons|National Archives|Internet Archive|Hansard|Boundary Commission/);
      // The poster appears only once sources.json records which still it is (its hash is checked in contract.yaml).
      expect(page).not.toContain("poster.jpg");
    }
  });

  it("every player control is a real, labelled button or link", () => {
    const film = read("web/f/partition-of-india/index.html");
    for (const label of ["Play", "Subtitles", "Marks", "Chapters", "Sound", "Full screen"]) {
      expect(film, label).toMatch(new RegExp(`<(button|a)\\b[^>]*aria-label="${label}"[^>]*data-label="${label}"`));
    }
    expect(film).toMatch(/role="slider"[^>]*tabindex="0"[^>]*aria-label="Position in the film"/);
  });

  it("the corrections form posts no name or email, and confirms in place", () => {
    const form = read("web/f/partition-of-india/correct/index.html");
    expect(form).not.toMatch(/type="email"|name="(name|email)"/);
    expect(visible(form)).toContain("Sent.");
  });
});
