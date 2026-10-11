// The film registry (films.json) and the pages it generates. Every film's
// pages (web/f/<slug>/{index,sources/index,correct/index}.html) and the home
// page are written from one template per page type in web/templates/, so no
// film's pages are hand-maintained. Pure functions, plus writeSite() for the
// build and the dev server. The generated pages are gitignored (R-08).
//
// films.json, v1:
//   films[]: slug, title, dates, status ("live" | "in_production"; a paused
//   film is removed), balance_fallback (the Partition pilot only), order (the home
//   marquee shows the live film with the lowest order), synopsis (required
//   when live; a film in production has none, nor logline, content_note or shows),
//   logline (optional), content_note (optional), shows (what the film does
//   and does not show; required when live), poster (the media file the
//   contract checks, or null), legend { reconstructed, drawn } (the marks
//   legend's sample details; required when live), languages { spoken,
//   captions[]: { lang, name, kind ("captions" | "subtitles"), review
//   ("reviewed" | "in_review" | "planned") } }, related[]: { href, name,
//   line, where } (the void family's work on the same subject),
//   screenplay_path (optional: the film's working screenplay.json on the render
//   machine, ~ for the home folder; the engine's bed-reuse lint reads it).

import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";

export const STATUSES = ["live", "in_production"];
/** The one film whose live sources.json predates the balance block (web/src/film-data.ts PARTITION_BALANCE). */
export const BALANCE_FALLBACK_SLUG = "partition-of-india";
export const REVIEWS = ["reviewed", "in_review", "planned"];
export const PAGE_TYPES = ["home", "film", "sources", "correct", "player"];
const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const LANG = /^[a-z]{2,3}$/;

const isObj = (x) => typeof x === "object" && x !== null && !Array.isArray(x);
const text = (x) => typeof x === "string" && x.trim() !== "";

/** Every problem with a registry, in words; an empty list when it is sound. */
export function registryProblems(reg) {
  const out = [];
  if (!isObj(reg) || reg.v !== 1 || !Array.isArray(reg.films)) return ["films.json: not a v1 registry with a films list"];
  const slugs = new Set();
  for (const [i, f] of reg.films.entries()) {
    const at = `films.json: film ${isObj(f) && text(f.slug) ? f.slug : i}`;
    if (!isObj(f)) {
      out.push(`${at}: not an object`);
      continue;
    }
    if (!text(f.slug) || !SLUG.test(f.slug)) out.push(`${at}: slug must be lowercase words joined by hyphens`);
    if (slugs.has(f.slug)) out.push(`${at}: slug is listed twice`);
    slugs.add(f.slug);
    for (const k of ["title", "dates"]) if (!text(f[k])) out.push(`${at}: ${k} is missing`);
    if (f.status === "paused") out.push(`${at}: a paused film is taken off films.json, not listed: remove the entry`);
    else if (!STATUSES.includes(f.status)) out.push(`${at}: status must be one of ${STATUSES.join(", ")}`);
    if (f.status === "in_production") {
      // A film in production shows its title, dates and status only: nothing it says can be checked yet (CoS, 2026-10-11).
      for (const k of ["synopsis", "logline", "content_note", "shows"]) if (f[k] !== undefined) out.push(`${at}: a film in production shows title, dates and status only: remove ${k}`);
    }
    if (f.balance_fallback !== undefined && !(f.balance_fallback === true && f.slug === BALANCE_FALLBACK_SLUG)) {
      out.push(`${at}: only ${BALANCE_FALLBACK_SLUG} may fall back on its own balance figures; every other film declares its balance in sources.json`);
    }
    if (!Number.isInteger(f.order)) out.push(`${at}: order must be a whole number`);
    for (const k of ["synopsis", "logline", "content_note", "shows"]) {
      if (f[k] !== undefined && f[k] !== null && !text(f[k])) out.push(`${at}: ${k} must be text when given`);
    }
    if (f.poster !== null && f.poster !== undefined && !(text(f.poster) && /^[a-z0-9-]+\.jpg$/.test(f.poster))) out.push(`${at}: poster must be a .jpg file name or null`);
    const caps = isObj(f.languages) && Array.isArray(f.languages.captions) ? f.languages.captions : null;
    if (!caps) out.push(`${at}: languages.captions must be a list`);
    const langs = new Set();
    for (const c of caps ?? []) {
      if (!isObj(c) || !LANG.test(c.lang ?? "") || !text(c.name) || !["captions", "subtitles"].includes(c.kind) || !REVIEWS.includes(c.review)) {
        out.push(`${at}: each caption track needs lang, name, kind (captions or subtitles) and review (${REVIEWS.join(", ")})`);
        continue;
      }
      if (langs.has(c.lang)) out.push(`${at}: caption track ${c.lang} is listed twice`);
      langs.add(c.lang);
    }
    if (f.screenplay_path !== undefined && !(text(f.screenplay_path) && f.screenplay_path.endsWith("screenplay.json"))) {
      out.push(`${at}: screenplay_path must be the path of the film's screenplay.json when given`);
    }
    if (!Array.isArray(f.related ?? [])) out.push(`${at}: related must be a list`);
    for (const r of f.related ?? []) {
      if (!isObj(r) || !text(r.name) || !text(r.line) || !text(r.where) || !/^https:\/\//.test(r.href ?? "")) out.push(`${at}: each related link needs an https href, name, line and where`);
    }
    if (f.status === "live") {
      if (!text(f.shows)) out.push(`${at}: a live film must say what it shows (shows)`);
      if (!text(f.synopsis)) out.push(`${at}: a live film needs a synopsis`);
      if (!isObj(f.legend) || !text(f.legend.reconstructed) || !text(f.legend.drawn)) out.push(`${at}: a live film needs legend.reconstructed and legend.drawn`);
    }
  }
  if (!reg.films.some((f) => isObj(f) && f.status === "live")) out.push("films.json: no live film for the marquee");
  return out;
}

export function loadRegistry(file) {
  const reg = JSON.parse(readFileSync(file, "utf8"));
  const problems = registryProblems(reg);
  if (problems.length) throw new Error(problems.join("\n"));
  return reg;
}

const byOrder = (a, b) => a.order - b.order || a.slug.localeCompare(b.slug);
export const liveFilms = (reg) => reg.films.filter((f) => f.status === "live").sort(byOrder);
export const listedFilms = (reg) => [...reg.films].sort(byOrder);
/** The film on the home marquee: the live film with the lowest order. */
export const marqueeFilm = (reg) => liveFilms(reg)[0];

/** The caption tracks a page may offer: only those whose review is done. */
export const publishedTracks = (film) => (film.languages?.captions ?? []).filter((c) => c.review === "reviewed");
export const trackLabel = (c) => `${c.name} ${c.kind}`;

function listWords(items) {
  return items.length > 1 ? `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}` : (items[0] ?? "");
}

/**
 * What the page says about tracks not yet offered, from their review status
 * and their kind: "Hindi and Urdu subtitles are being reviewed.", "English
 * captions are planned." One sentence per status and kind. Empty when every
 * listed track is offered.
 */
export function reviewNote(film) {
  const caps = film.languages?.captions ?? [];
  const out = [];
  for (const [status, verb] of [["in_review", "are being reviewed"], ["planned", "are planned"]]) {
    for (const kind of ["captions", "subtitles"]) {
      const names = caps.filter((c) => c.review === status && c.kind === kind).map((c) => c.name);
      if (names.length) out.push(`${listWords(names)} ${kind} ${verb}.`);
    }
  }
  return out.join(" ");
}

export const esc = (s) => String(s).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");

/** Escaped text with every run of digits set in the data face, as site.ts numerals() does at runtime. */
export function numHtml(s) {
  return String(s)
    .split(/(\d[\d,.:]*\d|\d)/)
    .map((part) => (/^\d/.test(part) ? `<span class="num">${esc(part)}</span>` : esc(part)))
    .join("");
}

/**
 * Fills {{name}} placeholders. A placeholder alone on its line whose value is
 * empty removes the line. An unknown placeholder, or one left unfilled, is a
 * build fault.
 */
export function fill(template, vars) {
  const out = template
    .replace(/^[ \t]*\{\{(\w+)\}\}[ \t]*\r?\n/gm, (line, key) => {
      if (!(key in vars)) throw new Error(`template: no value for {{${key}}}`);
      return vars[key] === "" ? "" : line.replace(`{{${key}}}`, vars[key]);
    })
    .replace(/\{\{(\w+)\}\}/g, (_, key) => {
      if (!(key in vars)) throw new Error(`template: no value for {{${key}}}`);
      return vars[key];
    });
  return out;
}

const ARROW =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 16 16 8M10 8h6v6" /></svg>';

function filmVars(film) {
  const tracks = publishedTracks(film);
  const note = reviewNote(film);
  const first = tracks[0];
  return {
    slug: film.slug,
    title: esc(film.title),
    dates_html: numHtml(film.dates),
    description: esc(`${film.title}, ${film.dates}, told with the public record${film.logline ? `: ${film.logline}` : ""}. A void document film.`),
    sources_description: esc(`Every shot of ${film.title} with its mark, archive and licence, and every reading with its speaker and source.`),
    correct_description: esc(`Tell void document what ${film.title} gets wrong.`),
    synopsis_html: film.synopsis ? numHtml(film.synopsis) : "",
    shows: esc(film.shows ?? ""),
    tracks: tracks
      .map((c) => `              <track kind="${c.kind}" srclang="${c.lang}" label="${esc(trackLabel(c))}" src="/media/${film.slug}/captions-${c.lang}.vtt" />`)
      .join("\n"),
    track_buttons: tracks
      .map((c) => `              <button type="button" role="menuitemradio" aria-checked="false" data-track="${c.lang}">${esc(trackLabel(c))}</button>`)
      .join("\n"),
    review_note_menu: note ? `              <p class="quiet">${esc(note)}</p>` : "",
    review_note_after: note ? ` ${esc(note)}` : "",
    captions_error: first ? esc(`The ${trackLabel(first)} could not load. Reload the page to try again.`) : "",
    legend_reconstructed: numHtml(film.legend?.reconstructed ?? ""),
    legend_drawn: numHtml(film.legend?.drawn ?? ""),
    related_onward: (film.related ?? [])
      .map((r) => `            <a href="${esc(r.href)}" rel="noopener"><span class="t">${esc(r.line)}</span><span class="m">${esc(r.where)}</span>${ARROW}</a>`)
      .join("\n"),
  };
}

function homeVars(reg) {
  const film = marqueeFilm(reg);
  const v = filmVars(film);
  const status = (f) => (f === film ? "Now showing" : f.status === "live" ? "Showing" : "In production");
  const entry = (f) => {
    const inner = `<span class="t">${esc(f.title)}</span><span class="m">${numHtml(f.dates)}</span><span class="s">${status(f)}</span>`;
    return f.status === "live"
      ? `        <li><a href="/f/${f.slug}/">${inner}</a></li>`
      : `        <li class="in-production"><div>${inner}</div></li>`;
  };
  return {
    ...v,
    home_description: esc(`void document: history told with the public record. Now showing: ${film.title}, ${film.dates}${film.logline ? `: ${film.logline}` : ""}.`),
    content_note: film.content_note ? `${esc(film.content_note)} ` : "",
    family_related: (film.related ?? [])
      .map((r) => `        <li><a href="${esc(r.href)}" rel="noopener"><span class="t">${esc(r.name)}</span><span class="m">${esc(r.line)}.</span></a></li>`)
      .join("\n"),
    film_list: listedFilms(reg).map(entry).join("\n"),
  };
}

/**
 * The player (web/templates/player.html), filled for one film: the same
 * markup on the film page and, in the home page's theatre, indented into the
 * dialog and loading nothing until the tap (preload none).
 */
function withPlayer(v, templates) {
  const player = fill(templates.player, v).replace(/\n$/, "");
  const theatre = player
    .split("\n")
    .map((l) => (l.trim() ? `  ${l}` : l))
    .join("\n")
    .replace('preload="metadata"', 'preload="none"');
  return { ...v, player, player_theatre: theatre };
}

/** Every generated page, keyed by its path under web/: the home page and each live film's three pages. */
export function sitePages(reg, templates) {
  const pages = { "index.html": fill(templates.home, withPlayer(homeVars(reg), templates)) };
  for (const film of liveFilms(reg)) {
    const v = withPlayer(filmVars(film), templates);
    pages[`f/${film.slug}/index.html`] = fill(templates.film, v);
    pages[`f/${film.slug}/sources/index.html`] = fill(templates.sources, v);
    pages[`f/${film.slug}/correct/index.html`] = fill(templates.correct, v);
  }
  return pages;
}

export function readTemplates(webDir) {
  return Object.fromEntries(PAGE_TYPES.map((t) => [t, readFileSync(path.join(webDir, "templates", `${t}.html`), "utf8")]));
}

/** Vite's inputs: privacy, the home page, and every live film's pages. */
export function viteInputs(reg) {
  const input = { main: "index.html", privacy: "privacy.html" };
  for (const f of liveFilms(reg)) {
    input[`film-${f.slug}`] = `f/${f.slug}/index.html`;
    input[`sources-${f.slug}`] = `f/${f.slug}/sources/index.html`;
    input[`correct-${f.slug}`] = `f/${f.slug}/correct/index.html`;
  }
  return input;
}

/** Writes the generated pages into web/ (web/f/ is rebuilt whole, so a film taken off the registry leaves no page). */
export function writeSite(repoRoot) {
  const webDir = path.join(repoRoot, "web");
  const reg = loadRegistry(path.join(repoRoot, "films.json"));
  const pages = sitePages(reg, readTemplates(webDir));
  rmSync(path.join(webDir, "f"), { recursive: true, force: true });
  for (const [rel, html] of Object.entries(pages)) {
    const out = path.join(webDir, rel);
    if (!existsSync(path.dirname(out))) mkdirSync(path.dirname(out), { recursive: true });
    writeFileSync(out, html);
  }
  return { reg, pages: Object.keys(pages) };
}
