// E1 and E2: the film registry (films.json), the pages it generates, the
// contract it expands, each film's own balance, its caption tracks and its
// imagery rule. Partition's pages must stay exactly what they were before
// they were generated (tests/fixtures/partition-pages/: the hand-written
// pages as main held them at 4fb7669), save that the film and sources pages now
// open their note with the film's content note, as the home page does).
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { parse as yamlParse } from "yaml";
import { expandFilmChecks, loadContract, runContract } from "../scripts/contract.mjs";
import {
  esc,
  fill,
  listedFilms,
  liveFilms,
  loadRegistry,
  marqueeFilm,
  numHtml,
  publishedTracks,
  readTemplates,
  registryProblems,
  reviewNote,
  sitePages,
  viteInputs,
} from "../scripts/lib/films.mjs";
import {
  PARTITION_BALANCE,
  accountsSentence,
  computeBalance,
  imagerySentences,
  parseBalance,
  parseSources,
  sideLabel,
  type Reading,
} from "../web/src/film-data";
import viteConfig from "../web/vite.config";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (f: string) => readFileSync(path.join(root, f), "utf8");
// The pilot-era registry (Partition live, Nought in production), kept as a fixture so the
// in-production rules stay tested now that both films are live in films.json.
const registry = loadRegistry(path.join(root, "tests/fixtures/films-pilot.json"));
/** films.json as shipped. */
const live = loadRegistry(path.join(root, "films.json"));
const templates = readTemplates(path.join(root, "web"));
type Film = (typeof registry.films)[number];
const clone = <T>(x: T): T => JSON.parse(JSON.stringify(x));
/** contract.yaml's films block as written, before expansion. */
const rawFilms = () => yamlParse(read("contract.yaml")).films;
const partition = () => clone(registry.films.find((f: Film) => f.slug === "partition-of-india"));

describe("films.json", () => {
  it("as shipped: Partition, The Next Village and Real World all live, Partition on the marquee", () => {
    expect(registryProblems(live)).toEqual([]);
    expect(listedFilms(live).map((f: Film) => [f.slug, f.status, f.order])).toEqual([
      ["partition-of-india", "live", 1],
      ["smallpox-eradication", "live", 2],
      ["real-world", "live", 3],
    ]);
    expect(marqueeFilm(live).slug).toBe("partition-of-india");
    const nv = live.films.find((f: Film) => f.slug === "smallpox-eradication");
    expect(nv.title).toBe("The Next Village");
    expect(nv.poster).toBe("poster.jpg");
    const p = sitePages(live, templates);
    expect(p["f/smallpox-eradication/index.html"]).toContain("<title>The Next Village · void document</title>");
    expect(p["index.html"]).toContain('<li><a href="/f/smallpox-eradication/">');
  });

  it("as shipped: Real World carries the founder-approved copy (2026-10-26) word for word, and no caption track it has not reviewed", () => {
    const rw = live.films.find((f: Film) => f.slug === "real-world");
    expect(rw).toMatchObject({
      title: "Real World",
      dates: "11 September 2001",
      logline: "one morning, as it was heard by the people working the sky",
      synopsis:
        "On the morning of 11 September 2001, controllers at Boston and New York, the air defence sector at Rome, New York, and the White House tried to understand what was happening in the air above them. The film keeps to what they knew, minute by minute, in their own recorded words: the tapes of the control rooms and the defence sector, and what was said in public that day. A narrator gives the time and the place; the record carries the rest.",
      content_note:
        "It concerns the attacks of 11 September 2001. It plays air traffic and air defence recordings made that morning, and shows the towers burning and falling, in wide views.",
      shows:
        "This film shows the day as it was broadcast and photographed: the burning towers, the impact and the collapses, the dust and the debris, in wide views. It never shows an identifiable person in their final moments; a wide view is never zoomed in, slowed or held on a person; no final call is played; the dead are shown by what the day left empty.",
      poster: "poster.jpg",
      screenplay_path: "~/document-work/sept11/screenplay.json",
    });
    // Its own sources.json declares its balance: no fallback.
    expect(rw.balance_fallback).toBeUndefined();
    // The English captions are written at release from the render; nobody has reviewed them yet, so none is offered.
    expect(rw.languages.captions).toEqual([{ lang: "en", name: "English", kind: "captions", review: "in_review" }]);
    expect(publishedTracks(rw)).toEqual([]);
    const p = sitePages(live, templates);
    const page = p["f/real-world/index.html"];
    expect(page).toContain("<title>Real World · void document</title>");
    expect(page).not.toContain("/media/real-world/captions-en.vtt");
    expect(page).toContain("English captions are being reviewed.");
    expect(p["f/real-world/sources/index.html"]).toBeDefined();
    expect(p["f/real-world/correct/index.html"]).toBeDefined();
    expect(p["index.html"]).toContain('<li><a href="/f/real-world/"><span class="t">Real World</span>');
    // Partition keeps the marquee.
    expect(marqueeFilm(live).slug).toBe("partition-of-india");
  });

  it("escapes every registry value it writes into a page, attributes included", () => {
    const evil = '"><img src=x onerror=alert(1)>';
    const r = clone(live);
    const f = r.films.find((x: Film) => x.slug === "real-world");
    Object.assign(f, { title: evil, dates: `${evil} 2001`, logline: evil, synopsis: evil, content_note: evil, shows: evil, legend: { reconstructed: evil, drawn: evil } });
    f.languages.captions = [{ lang: "en", name: evil, kind: "captions", review: "reviewed" }];
    f.related = [{ href: `https://example.test/${evil}`, name: evil, line: evil, where: evil }];
    // On the marquee too, so the home page's own fields are fed the same value.
    f.order = 0;
    const pages = sitePages(r, templates);
    for (const page of ["index.html", "f/real-world/index.html", "f/real-world/sources/index.html", "f/real-world/correct/index.html"]) {
      expect(pages[page], page).not.toContain("<img src=x");
      expect(pages[page], page).not.toContain('"><img src=x');
      expect(pages[page], page).not.toContain("onerror=alert(1)>");
      expect(pages[page], page).toContain("&quot;&gt;&lt;img src=x onerror=alert(1)&gt;");
    }
  });

  it("the pilot-era fixture is a sound registry: Partition live on the marquee, Nought in production, in order", () => {
    expect(registryProblems(registry)).toEqual([]);
    expect(listedFilms(registry).map((f: Film) => [f.slug, f.status])).toEqual([
      ["partition-of-india", "live"],
      ["smallpox-eradication", "in_production"],
    ]);
    expect(marqueeFilm(registry).slug).toBe("partition-of-india");
    const nought = registry.films.find((f: Film) => f.slug === "smallpox-eradication");
    expect(nought.title).toBe("Nought");
    expect(nought.poster).toBeNull();
    // A film in production says nothing it cannot yet source: title, dates and status only (CoS, 2026-10-11).
    for (const k of ["synopsis", "logline", "content_note", "shows"]) expect(nought[k], k).toBeUndefined();
  });

  it("refuses a registry that would publish something wrong", () => {
    const bad = (mut: (r: { v: number; films: Film[] }) => void) => {
      const r = clone(registry);
      mut(r);
      return registryProblems(r).join("\n");
    };
    expect(bad((r) => r.films.push(clone(r.films[0])))).toMatch(/slug is listed twice/);
    expect(bad((r) => (r.films[1].status = "soon"))).toMatch(/status must be one of live, in_production/);
    expect(bad((r) => (r.films[1].status = "paused"))).toMatch(/a paused film is taken off films\.json, not listed: remove the entry/);
    expect(bad((r) => ((r.films[1] as Film).synopsis = "Unsourced words."))).toMatch(/in production shows title, dates and status only: remove synopsis/);
    expect(bad((r) => ((r.films[1] as Film).logline = "x"))).toMatch(/remove logline/);
    expect(bad((r) => ((r.films[1] as Film).balance_fallback = true))).toMatch(/only partition-of-india may fall back/);
    expect(bad((r) => delete r.films[0].shows)).toMatch(/must say what it shows/);
    expect(bad((r) => delete r.films[0].synopsis)).toMatch(/needs a synopsis/);
    expect(bad((r) => delete r.films[0].legend)).toMatch(/legend/);
    expect(bad((r) => (r.films[0].languages.captions[1].review = "ok"))).toMatch(/review \(reviewed, in_review, planned\)/);
    expect(bad((r) => (r.films[0].slug = "Partition Of India"))).toMatch(/lowercase words/);
    expect(bad((r) => (r.films[0].status = "in_production"))).toMatch(/no live film for the marquee/);
    expect(bad((r) => (r.films[0].related[0].href = "http://x"))).toMatch(/https href/);
    // A film in production needs no poster, shows or legend.
    expect(bad((r) => delete r.films[1].poster)).toBe("");
    // screenplay_path (the engine's bed-reuse lint reads it) is optional, and a screenplay.json when given.
    expect(bad((r) => delete (r.films[1] as Film).screenplay_path)).toBe("");
    expect(bad((r) => ((r.films[1] as Film).screenplay_path = "~/document-work/smallpox/"))).toMatch(/screenplay_path must be/);
    expect(bad((r) => ((r.films[1] as Film).screenplay_path = 3))).toMatch(/screenplay_path must be/);
  });
});

describe("the generated pages", () => {
  const pages = sitePages(registry, templates);

  it("are the home page and each live film's three pages; a film in production has none", () => {
    expect(Object.keys(pages).sort()).toEqual(["f/partition-of-india/correct/index.html", "f/partition-of-india/index.html", "f/partition-of-india/sources/index.html", "index.html"]);
    // Vite builds exactly those pages (web/vite.config.ts reads films.json the same way).
    const input = (viteConfig as { build: { rollupOptions: { input: Record<string, string> } } }).build.rollupOptions.input;
    expect(input).toEqual(viteInputs(live));
  });

  it("render Partition's film, sources and correct pages byte for byte as they were hand-written", () => {
    expect(pages["f/partition-of-india/index.html"]).toBe(read("tests/fixtures/partition-pages/film.html"));
    expect(pages["f/partition-of-india/sources/index.html"]).toBe(read("tests/fixtures/partition-pages/sources.html"));
    expect(pages["f/partition-of-india/correct/index.html"]).toBe(read("tests/fixtures/partition-pages/correct.html"));
  });

  it("the home theatre is the film page's own player, filled from the same template", () => {
    const section = (html: string) => /<section class="screen" id="screen"[\s\S]*?<\/section>/.exec(html)?.[0].replace(/\s+/g, " ") ?? "";
    expect(section(pages["index.html"])).toBe(section(pages["f/partition-of-india/index.html"]).replace('preload="metadata"', 'preload="none"'));
  });

  it("the home page lists every film: the marquee film linked as now showing, Nought as in production, by title, dates and status only", () => {
    const home = pages["index.html"];
    expect(home).toContain('<main class="marquee" id="marquee" data-slug="partition-of-india">');
    expect(home).toContain('<li><a href="/f/partition-of-india/"><span class="t">The Partition of India</span>');
    expect(home).toContain('<li class="in-production"><div><span class="t">Nought</span><span class="m"><span class="num">1967</span> to <span class="num">1980</span></span><span class="s">In production</span></div></li>');
    expect(home).not.toContain("/f/smallpox-eradication/");
    expect(home).not.toContain("/media/smallpox-eradication/");
  });

  it("a second live film gets its own pages from the same templates, with its own words and media paths", () => {
    const r = clone(registry);
    const n = r.films[1];
    Object.assign(n, { status: "live", synopsis: "A test synopsis of 1974.", shows: "This film shows smallpox.", legend: { reconstructed: "archive 1967 upscaled", drawn: "from WHO 1988" } });
    n.languages.captions[0].review = "reviewed";
    const p = sitePages(r, templates);
    const film = p["f/smallpox-eradication/index.html"];
    expect(film).toContain('data-slug="smallpox-eradication"');
    expect(film).toContain('<source src="/media/smallpox-eradication/film.mp4" type="video/mp4" />');
    expect(film).toContain("<title>Nought · void document</title>");
    expect(film).toContain("This film shows smallpox.");
    expect(film).not.toMatch(/partition/i);
    expect(p["f/smallpox-eradication/sources/index.html"]).toContain("<h1>Nought</h1>");
    expect(p["f/smallpox-eradication/correct/index.html"]).toContain("Correct something in <em>Nought</em>");
    // The marquee stays with the lowest order.
    expect(p["index.html"]).toContain('data-slug="partition-of-india"');
  });

  it("each live film's content note leads the note on its film page and its sources page, as on the home page", () => {
    const p = sitePages(live, templates);
    const films = liveFilms(live);
    expect(films.length).toBeGreaterThan(1);
    for (const f of films) {
      expect(f.content_note, f.slug).toBeTruthy();
      // Escaped, numerals in the data face (as the synopsis).
      const note = numHtml(f.content_note);
      expect(p[`f/${f.slug}/index.html`], f.slug).toContain(`<p class="note">${note} <span id="derived-notes" hidden>`);
      expect(p[`f/${f.slug}/sources/index.html`], f.slug).toContain(`<p>${note} Every shot with the mark it carries on screen`);
    }
    // The home page says the marquee film's note once, as before.
    const m = marqueeFilm(live);
    expect(p["index.html"]).toContain(`<p class="note">${numHtml(m.content_note)} Every reading is word for word`);
    expect(numHtml("It concerns 11 September 2001.")).toBe('It concerns <span class="num">11</span> September <span class="num">2001</span>.');
    // A film with no content note says nothing in its place, and its note starts as it did.
    const r = clone(live);
    delete r.films[1].content_note;
    const q = sitePages(r, templates);
    expect(q[`f/${r.films[1].slug}/index.html`]).toContain('<p class="note"><span id="derived-notes" hidden>');
    expect(q[`f/${r.films[1].slug}/sources/index.html`]).toContain("<p>Every shot with the mark it carries on screen");
    // Escaped, as every registry value.
    const evil = '"><img src=x onerror=alert(1)>';
    r.films[1].content_note = evil;
    const e = sitePages(r, templates)[`f/${r.films[1].slug}/index.html`];
    expect(e).not.toContain("<img src=x");
    expect(e).not.toContain('"><img');
    expect(e).toContain('&quot;&gt;&lt;img src=x onerror=alert(<span class="num">1</span>)&gt; <span id="derived-notes"');
    expect(esc("<")).toBe("&lt;");
  });

  it("escape registry text and set every numeral in the data face", () => {
    expect(numHtml('Born 14 August 1947 <b> & "so"')).toBe('Born <span class="num">14</span> August <span class="num">1947</span> &lt;b&gt; &amp; &quot;so&quot;');
    expect(() => fill("{{nope}}", {})).toThrow(/no value for \{\{nope\}\}/);
    expect(fill("a\n  {{x}}\nb", { x: "" })).toBe("a\nb");
  });
});

describe("caption tracks: only reviewed ones are offered", () => {
  const filmPage = (film: Film) => {
    const r = clone(registry);
    r.films[0] = film;
    return sitePages(r, templates)["f/partition-of-india/index.html"];
  };

  it("Partition offers English only; the Hindi and Urdu note is derived from their review status", () => {
    expect(publishedTracks(partition()).map((c: { lang: string }) => c.lang)).toEqual(["en"]);
    expect(reviewNote(partition())).toBe("Hindi and Urdu subtitles are being reviewed.");
    expect(read("web/templates/film.html") + read("web/templates/player.html")).not.toContain("Hindi and Urdu");
  });

  it("a track becomes a <track> and a menu item only once reviewed; planned tracks are named, never offered", () => {
    const f = partition();
    f.languages.captions = [
      { lang: "en", name: "English", kind: "captions", review: "reviewed" },
      { lang: "hi", name: "Hindi", kind: "subtitles", review: "reviewed" },
      { lang: "bn", name: "Bengali", kind: "subtitles", review: "planned" },
    ];
    const html = filmPage(f);
    const tracks = [...html.matchAll(/<track\b[^>]*>/g)].map((m) => m[0]);
    expect(tracks).toEqual([
      '<track kind="captions" srclang="en" label="English captions" src="/media/partition-of-india/captions-en.vtt" />',
      '<track kind="subtitles" srclang="hi" label="Hindi subtitles" src="/media/partition-of-india/captions-hi.vtt" />',
    ]);
    expect(html).toContain('data-track="hi">Hindi subtitles</button>');
    expect(html).not.toMatch(/srclang="bn"|data-track="bn"|captions-bn/);
    expect(html).toContain('<p class="quiet">Bengali subtitles are planned.</p>');
    expect(reviewNote(f)).toBe("Bengali subtitles are planned.");
  });

  it("names each track by its own kind: captions and subtitles are said apart", () => {
    const f = partition();
    f.languages.captions = [
      { lang: "en", name: "English", kind: "captions", review: "in_review" },
      { lang: "hi", name: "Hindi", kind: "subtitles", review: "in_review" },
      { lang: "ur", name: "Urdu", kind: "subtitles", review: "in_review" },
      { lang: "bn", name: "Bengali", kind: "subtitles", review: "planned" },
      { lang: "fr", name: "French", kind: "captions", review: "planned" },
    ];
    expect(reviewNote(f)).toBe("English captions are being reviewed. Hindi and Urdu subtitles are being reviewed. French captions are planned. Bengali subtitles are planned.");
  });

  it("with every track reviewed, nothing is said about review", () => {
    const f = partition();
    for (const c of f.languages.captions) c.review = "reviewed";
    const html = filmPage(f);
    expect(html).not.toMatch(/being reviewed|planned/);
    expect([...html.matchAll(/<track\b/g)]).toHaveLength(3);
  });

  it("the player reads its tracks from the page and picks them by language, never a hard-coded en", () => {
    const player = read("web/src/player.ts");
    expect(player).toMatch(/Array\.from\(video\.textTracks\)\.find\(\(t\) => t\.language === lang\)/);
    expect(player).not.toMatch(/data-track="en"|=== "en"/);
  });
});

describe("the contract, expanded from films.json", () => {
  const contract = loadContract(path.join(root, "contract.yaml"));
  const forFilm = (slug: string) => contract.checks.filter((c: { film?: string }) => c.film === slug);

  it("gives Partition every check it had, and The Next Village and Real World a live film's checks", () => {
    expect(contract.checks).toHaveLength(87);
    const rw = forFilm("real-world");
    expect(rw).toHaveLength(19);
    expect(rw.find((c: { type: string }) => c.type === "json_has")).toMatchObject({ path: "/media/real-world/sources.json", field: "balance.sides", requires: "deployed" });
    // No English track is reviewed yet, so the contract asks for none.
    expect(rw.some((c: { path?: string }) => /captions-/.test(c.path ?? ""))).toBe(false);
    expect(forFilm("partition-of-india")).toHaveLength(22);
    const nv = forFilm("smallpox-eradication");
    expect(nv).toHaveLength(19);
    expect(nv.some((c: { name: string }) => /has no page until/.test(c.name))).toBe(false);
    expect(nv.find((c: { type: string }) => c.type === "json_has")).toMatchObject({ path: "/media/smallpox-eradication/sources.json", field: "balance.sides" });
  });

  it("a film in production gets only what it can answer (pilot-era fixture)", () => {
    const out = expandFilmChecks({ checks: [{ expand: "films" }], films: rawFilms() }, registry).filter((c: { film?: string }) => c.film === "smallpox-eradication");
    expect(out.map((c: { name: string }) => c.name)).toEqual(["homepage names Nought", "Nought has no page until it is live"]);
    expect(out.find((c: { type: string }) => c.type === "status")).toMatchObject({ path: "/f/smallpox-eradication/", expect: 404 });
    expect(JSON.stringify(out)).not.toContain("/media/");
  });

  it("keeps when_declared and undeclared_status on each film's trailer check", () => {
    const trailer = forFilm("partition-of-india").find((c: { field?: string }) => c.field === "trailer.sha256");
    expect(trailer).toMatchObject({ path: "/media/partition-of-india/trailer.mp4", sources: "/media/partition-of-india/sources.json", when_declared: "trailer", undeclared_status: 404, requires: "deployed" });
  });

  it("requires every live film but the pilot to declare its balance", () => {
    expect(forFilm("partition-of-india").some((c: { type: string }) => c.type === "json_has")).toBe(false);
    const r = clone(registry);
    Object.assign(r.films[1], { status: "live", synopsis: "x", shows: "y", legend: { reconstructed: "a", drawn: "b" } });
    const out = expandFilmChecks({ checks: [{ expand: "films" }], films: rawFilms() }, r);
    expect(out.find((c: { film?: string; type: string }) => c.film === "smallpox-eradication" && c.type === "json_has")).toMatchObject({
      path: "/media/smallpox-eradication/sources.json",
      field: "balance.sides",
      requires: "deployed",
    });
  });

  it("json_has passes on a declared field, and fails on a missing or empty one", async () => {
    const answer = (doc: unknown) => async () => new Response(JSON.stringify(doc), { status: 200, headers: { "content-type": "application/json" } });
    const check = { checks: [{ name: "b", type: "json_has", path: "/media/x/sources.json", field: "balance.sides" }] };
    const opts = (doc: unknown) => ({ fetch: answer(doc), sleep: async () => undefined });
    expect((await runContract(check, "https://example.test", opts({ balance: { sides: ["uk"] } })))[0].pass).toBe(true);
    expect((await runContract(check, "https://example.test", opts({ balance: { sides: [] } })))[0].pass).toBe(false);
    expect((await runContract(check, "https://example.test", opts({ sides: ["uk"] })))[0].pass).toBe(false);
  });

  it("checks a caption track per reviewed track, and a poster only when the film names one", () => {
    const r = clone(registry);
    const n = r.films[1];
    Object.assign(n, { status: "live", synopsis: "x", shows: "y", legend: { reconstructed: "a", drawn: "b" } });
    n.languages.captions[0].review = "reviewed";
    n.languages.captions[1].review = "reviewed";
    const out = expandFilmChecks({ checks: [{ expand: "films" }], films: rawFilms() }, r).filter((c: { film?: string }) => c.film === "smallpox-eradication");
    const paths = out.map((c: { path: string }) => c.path);
    expect(paths).toContain("/media/smallpox-eradication/captions-en.vtt");
    expect(paths).toContain("/media/smallpox-eradication/captions-bn.vtt");
    expect(paths).not.toContain("/media/smallpox-eradication/captions-hi.vtt");
    expect(paths.some((p: string) => p.endsWith("poster.jpg"))).toBe(false);
    expect(out.some((c: { name: string }) => /has no page until/.test(c.name))).toBe(false);
  });

  it("refuses a films block it cannot expand", () => {
    expect(() => expandFilmChecks({ checks: [], films: rawFilms() }, registry)).toThrow(/exactly once/);
    expect(() => expandFilmChecks({ checks: [{ expand: "films" }], films: { checks: [{ name: "x {nope}", type: "status" }] } }, registry)).toThrow(/unknown placeholder \{nope\}/);
    expect(() => expandFilmChecks({ checks: [{ expand: "films" }], films: { checks: [{ name: "x", for: ["soon"] }] } }, registry)).toThrow(/for must list/);
  });
});

describe("the balance: per film, from its sources.json", () => {
  const r = (over: Partial<Reading>): Reading => ({ id: "R", name: "X", side: "usa", year: 1979, start_s: 0, dur_s: 10, gender: "m", role: null, text: "", credit: "", ...over });
  const smallpox = {
    sides: [
      { id: "usa", label: "United States", phrase: "the United States" },
      { id: "uk", label: "United Kingdom", phrase: "the United Kingdom" },
    ],
    roles: [
      { id: "official", label: "Officials" },
      { id: "counter", label: "Counters" },
    ],
    band: { min: 0.1, max: 0.6 },
    women_floor: 0.4,
    named_speakers_min: 2,
  };

  it("a sources.json without a balance block (Partition's live file) keeps Partition's figures, so its page is unchanged", () => {
    const base = { v: 2, slug: "partition-of-india", shots: [{ id: "S1", start_s: 0, end_s: 1, mark: { class: "CARD" } }] };
    const d = parseSources(base);
    expect(d.balance).toBe(PARTITION_BALANCE);
    expect(PARTITION_BALANCE).toEqual({
      sides: [
        { id: "britain", label: "Britain", phrase: "Britain" },
        { id: "india", label: "India", phrase: "India" },
        { id: "pakistan", label: "Pakistan", phrase: "Pakistan" },
        { id: "bangladesh", label: "Bangladesh", phrase: "Bangladesh" },
        { id: "sikh", label: "Sikh", phrase: "the Sikh community" },
      ],
      roles: [],
      band: { min: 0.1, max: 0.35 },
      women_floor: 0.3,
      named_speakers_min: null,
    });
    // Partition's values declared as a block parse to the same figures: once the engine writes it, nothing changes.
    expect(parseSources({ ...base, balance: PARTITION_BALANCE }).balance).toEqual(PARTITION_BALANCE);
    // As the engine will write it for Partition's next release (GRAMMAR A22: episode-v2 declares balance.sides as ids,
    // the engine adds settings and sides): the same figures, so the page renders the same.
    const rerender = { ...base, balance: { sides: ["britain", "india", "pakistan", "bangladesh", "sikh"] }, sides: ["britain", "india", "pakistan", "bangladesh", "sikh"], settings: { women_floor: 0.3, readings_floor: 0.2 } };
    expect(parseSources(rerender).balance).toEqual(PARTITION_BALANCE);
    const readings = [r({ name: "Mountbatten", side: "britain" }), r({ name: "Baldev Singh", side: "sikh" })];
    expect(accountsSentence(d.balance, readings)).toBe("Accounts from Britain and the Sikh community.");
    expect(sideLabel(d.balance, "sikh")).toBe("Sikh");
    expect(computeBalance(readings, d.balance)?.speakersShort).toEqual([]);
  });

  it("a declared block names the sides, roles, band, floor and minimum: smallpox's usa and uk print as countries", () => {
    const c = parseBalance(smallpox)!;
    const b = computeBalance(
      [
        r({ name: "David Ennals", side: "uk", dur_s: 40, role: "official" }),
        r({ name: "Jill Knight", side: "uk", dur_s: 22, gender: "f", role: "official" }),
        r({ name: "US Army film, 1967", side: "usa", dur_s: 38, role: "counter" }),
      ],
      c,
    )!;
    expect(b.sides.map((s) => [s.label, s.seconds])).toEqual([
      ["United States", 38],
      ["United Kingdom", 62],
    ]);
    expect(b.roles?.map((x) => [x.label, x.seconds])).toEqual([
      ["Officials", 62],
      ["Counters", 38],
    ]);
    expect(b.speakersShort).toEqual([{ side: "usa", label: "United States", count: 1 }]);
    expect(b.women.share).toBeCloseTo(0.22, 6);
    expect(accountsSentence(c, [r({ side: "uk" }), r({ side: "usa" })])).toBe("Accounts from the United States and the United Kingdom.");
    // A reading with a side the film does not declare: no figures at all (as before), never a wrong table.
    expect(computeBalance([r({ side: "india" })], c)).toBeNull();
    // A reading with an undeclared role: the roles axis is dropped, the sides stand.
    const partial = computeBalance([r({ role: "doubter" })], c)!;
    expect(partial.roles).toBeNull();
    expect(partial.sides[0].seconds).toBe(10);
  });

  it("only the pilot falls back: another film with neither a balance nor sides shows no figures", () => {
    const other = parseSources({ v: 2, slug: "smallpox-eradication", shots: [{ id: "S1", start_s: 0, end_s: 1, mark: { class: "CARD" } }] });
    expect(other.balance).toBeNull();
    expect(computeBalance([r({})], other.balance)).toBeNull();
  });

  it("a malformed declared block shows no figures rather than guessed ones", () => {
    for (const broken of [{}, { ...smallpox, sides: [] }, { ...smallpox, band: { min: 0.5, max: 0.2 } }, { ...smallpox, women_floor: 2 }, { ...smallpox, sides: [{ label: "no id" }] }, { ...smallpox, sides: ["usa", "usa"] }, { ...smallpox, named_speakers_min: 1.5 }, { ...smallpox, roles: "officials" }]) {
      expect(parseBalance(broken), JSON.stringify(broken)).toBeNull();
    }
    const d = parseSources({ v: 2, shots: [{ id: "S1", start_s: 0, end_s: 1, mark: { class: "CARD" } }], balance: { sides: "usa" } });
    expect(d.balance).toBeNull();
    expect(computeBalance([r({})], d.balance)).toBeNull();
  });

  it("reads the engine's other shapes: bare ids, the cast's sides, the film's own women_floor setting", () => {
    // Bare ids with no labels: Partition's names where they are Partition's sides, else the id as a word.
    expect(parseBalance({ sides: ["uk", "usa", "sikh"] })!.sides.map((s) => s.label)).toEqual(["UK", "USA", "Sikh"]);
    // No balance block but the cast's sides (the engine always writes sides): those, with Partition's band.
    const fromCast = parseSources({ v: 2, shots: [{ id: "S1", start_s: 0, end_s: 1, mark: { class: "CARD" } }], sides: ["uk", "usa"], settings: { women_floor: 0.4 } }).balance!;
    expect(fromCast.sides.map((s) => s.id)).toEqual(["uk", "usa"]);
    expect([fromCast.band, fromCast.women_floor]).toEqual([PARTITION_BALANCE.band, 0.4]);
    // A block's own floor wins over the setting.
    expect(parseBalance({ sides: ["uk"], women_floor: 0.5 }, { women_floor: 0.4 })!.women_floor).toBe(0.5);
  });

  it("the pages read the block, not constants", () => {
    const sources = read("web/src/sources.ts");
    expect(sources).toMatch(/computeBalance\(d\.readings, d\.balance\)/);
    expect(sources).not.toMatch(/SIDE_LABELS|SIDE_BAND|WOMEN_FLOOR/);
    expect(read("web/src/player.ts")).not.toMatch(/SIDE_PHRASE|"the Sikh community"/);
  });
});

describe("the imagery rule, stated on the Sources page", () => {
  it("prints only a rule the film declared: the default rule (Partition's) prints nothing", () => {
    // As the engine writes the default (studio/engine/policy.py DEFAULT_IMAGERY_RULE, declared false).
    const partitionDefault = { show_disease: false, show_bodies: false, show_violence: false, name_only_where_source_names: true, min_hold_s: 8, no_detail_on_face: true, no_dissolve_into_patient: true, statement: "No footage or photograph of bodies, killing, wounds or corpses.", declared: false };
    expect(imagerySentences(partitionDefault)).toEqual([]);
    expect(imagerySentences(undefined)).toEqual([]);
    expect(parseSources({ v: 2, shots: [{ id: "S1", start_s: 0, end_s: 1, mark: { class: "CARD" } }], imagery_rule: partitionDefault }).imagery).toEqual([]);
  });

  it("states a declared rule in plain words: the film's statement first, then the rules for a patient's photograph", () => {
    const nought = { show_disease: true, show_bodies: false, show_violence: false, name_only_where_source_names: true, min_hold_s: 8, no_detail_on_face: true, no_dissolve_into_patient: true, statement: "This film shows smallpox as the record holds it.", declared: true, unknown_setting: "ignored" };
    const lines = imagerySentences(nought);
    expect(lines).toEqual([
      "This film shows smallpox as the record holds it.",
      "A person is named only where the source names them; anyone else is given the place and date of the picture.",
      "A photograph of a patient is held at least 8 s, never flashed.",
      "The camera never moves in close on a patient's face.",
      "A photograph of a patient never dissolves out of an unrelated picture.",
    ]);
    for (const l of lines) expect(l).not.toMatch(/[!—]/);
    // Without a statement, what it shows and does not show is said from the flags.
    expect(imagerySentences({ ...nought, statement: undefined, subject: "smallpox" }).slice(0, 2)).toEqual([
      "This film shows smallpox as the photographs and films of the time record it.",
      "It shows no bodies or violence.",
    ]);
  });

  it("the Sources page draws it only when the film has one, so Partition's page is unchanged", () => {
    const sources = read("web/src/sources.ts");
    expect(sources).toMatch(/function renderImagery\(d: FilmSources\): void \{\s*if \(!d\.imagery\.length\) return;/);
    expect(read("tests/fixtures/partition-pages/sources.html")).not.toContain("What this film shows");
  });
});

describe("the Worker needs no change for a second film", () => {
  it("serves any film's media keys, captions in any language included", async () => {
    const { isMediaKey } = await import("../worker/src/media");
    for (const k of ["smallpox-eradication/film.mp4", "smallpox-eradication/sources.json", "smallpox-eradication/captions-bn.vtt", "smallpox-eradication/captions-hi.vtt", "smallpox-eradication/poster.jpg"]) expect(isMediaKey(k), k).toBe(true);
    expect(read("wrangler.jsonc")).toContain('"/media/*"');
  });
});
