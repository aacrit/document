// GRAMMAR A0, the founding principle: show as was, not as is, and never tell.
// The site's side of the lints: films.json copy, the page templates and the
// generated meta descriptions are held to the same lists as the film
// (studio/show-as-was.json). The text functions match exactly as
// studio/engine/aswas.py's do; tests/fixtures/a0-cases.json holds the cases
// both suites run.
import { readFileSync } from "node:fs";

export const LEXICON = JSON.parse(readFileSync(new URL("../../studio/show-as-was.json", import.meta.url), "utf8"));

const QUOTE_SPANS = [/“[^”]*”/g, /"[^"]*"/g];

/** Text with every double-quoted span blanked: quoted period speech is exempt. */
export function stripQuotes(text) {
  let t = String(text ?? "");
  for (const rx of QUOTE_SPANS) t = t.replace(rx, " ");
  return t;
}

const norm = (text) => stripQuotes(text).replace(/[‘’]/g, "'");
const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const cache = new Map();
function rx(phrase, ignoreCase) {
  const key = `${ignoreCase ? "i" : "c"}:${phrase}`;
  if (!cache.has(key)) {
    const words = phrase.trim().split(/[\s-]+/).filter(Boolean).map(escape);
    const edge = ignoreCase ? "a-z0-9" : "A-Za-z0-9";
    cache.set(key, new RegExp(`(?<![${edge}])${words.join("[\\s-]+")}(?![${edge}])`, ignoreCase ? "gi" : "g"));
  }
  const r = cache.get(key);
  r.lastIndex = 0;
  return r;
}

/** Every phrase of every group found in the unquoted text, in list order; a group's except phrases are blanked first. */
export function phraseHits(text, groups) {
  const base = norm(text);
  const out = [];
  for (const g of groups) {
    let t = base;
    for (const x of g.except ?? []) t = t.replace(rx(x, true), " ");
    for (const p of g.phrases) if (rx(p, true).test(t)) out.push({ group: g.id, phrase: p });
  }
  return out;
}

// --- dates: an interval [lo, hi] as ISO strings (they compare as dates) ---
const MONTH_NAMES = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"];
const MONTHS = Object.fromEntries([...MONTH_NAMES.map((m, i) => [m, i + 1]), ...MONTH_NAMES.map((m, i) => [m.slice(0, 3), i + 1]), ["sept", 9]]);
const pad = (n, w = 2) => String(n).padStart(w, "0");
const lastDay = (y, m) => new Date(Date.UTC(y, m, 0)).getUTCDate();
const yearSpan = (y) => [`${pad(y, 4)}-01-01`, `${pad(y, 4)}-12-31`];
const monthSpan = (y, m) => [`${pad(y, 4)}-${pad(m)}-01`, `${pad(y, 4)}-${pad(m)}-${pad(lastDay(y, m))}`];
const day = (y, m, d) => (m >= 1 && m <= 12 && d >= 1 && d <= lastDay(y, m) ? `${pad(y, 4)}-${pad(m)}-${pad(d)}` : null);

/** A date as the interval it can mean (studio/engine/aswas.py parse_date); null when it names no year. */
export function parseDate(value) {
  if (value === null || value === undefined || typeof value === "boolean") return null;
  if (typeof value === "number") return Number.isInteger(value) && value >= 1 && value <= 9999 ? yearSpan(value) : null;
  let low = String(value).trim().toLowerCase();
  const before = /^before\s+(.*)$/.exec(low);
  if (before) {
    const inner = parseDate(before[1]);
    if (!inner) return null;
    const d = new Date(`${inner[0]}T00:00:00Z`);
    d.setUTCDate(d.getUTCDate() - 1);
    return ["0001-01-01", d.toISOString().slice(0, 10)];
  }
  low = low.replace(/^(circa|ca\.|c\.|about|around)\s*/, "");
  let m;
  if ((m = /^(?:the\s+)?(\d{3})0s\b/.exec(low))) {
    const d = Number(m[1]) * 10;
    return [`${pad(d, 4)}-01-01`, `${pad(d + 9, 4)}-12-31`];
  }
  if ((m = /^(\d{4})-(\d{2})-(\d{2})/.exec(low))) {
    const d = day(+m[1], +m[2], +m[3]);
    return d ? [d, d] : null;
  }
  if ((m = /^(\d{4})-(\d{2})(?!\d)/.exec(low))) return +m[2] >= 1 && +m[2] <= 12 ? monthSpan(+m[1], +m[2]) : null;
  if ((m = /^(\d{1,2})\s+([a-z]+)\.?,?\s+(\d{4})/.exec(low)) && MONTHS[m[2]]) {
    const d = day(+m[3], MONTHS[m[2]], +m[1]);
    return d ? [d, d] : null;
  }
  if ((m = /^([a-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})/.exec(low)) && MONTHS[m[1]]) {
    const d = day(+m[3], MONTHS[m[1]], +m[2]);
    return d ? [d, d] : null;
  }
  if ((m = /^([a-z]+)\.?,?\s+(\d{4})/.exec(low)) && MONTHS[m[1]]) return monthSpan(+m[2], MONTHS[m[1]]);
  if ((m = /^(\d{4})(?!\d)/.exec(low))) return yearSpan(+m[1]);
  if ((m = /(?<!\d)(\d{4})(?!\d)/.exec(low))) return yearSpan(+m[1]);
  return null;
}

// --- years: numerals and years said in words ---
const UNITS = Object.fromEntries("one two three four five six seven eight nine".split(" ").map((w, i) => [w, i + 1]));
const TEENS = Object.fromEntries("ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(" ").map((w, i) => [w, 10 + i]));
const TENS = Object.fromEntries("twenty thirty forty fifty sixty seventy eighty ninety".split(" ").map((w, i) => [w, 10 * (i + 2)]));
const CENTURIES = { eighteen: 18, nineteen: 19 };
const YEAR_CONTEXT = new Set([
  ..."in of by since until till from to between year years summer winter spring autumn monsoon early late mid".split(" "),
  ...Object.keys(MONTHS).filter((m) => m.length > 3),
]);
const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);

function under100(tok, i) {
  if (i >= tok.length) return null;
  const w = tok[i];
  if ((w === "oh" || w === "o") && i + 1 < tok.length && has(UNITS, tok[i + 1])) return [UNITS[tok[i + 1]], i + 2];
  if (has(TEENS, w)) return [TEENS[w], i + 1];
  if (has(TENS, w)) return i + 1 < tok.length && has(UNITS, tok[i + 1]) ? [TENS[w] + UNITS[tok[i + 1]], i + 2] : [TENS[w], i + 1];
  if (has(UNITS, w)) return [UNITS[w], i + 1];
  return null;
}

/** Years written out as narration says them (aswas.spoken_years). */
export function spokenYears(text) {
  const tok = norm(text).toLowerCase().match(/[a-z]+/g) ?? [];
  const out = [];
  let i = 0;
  while (i < tok.length) {
    const w = tok[i];
    const ctx = i > 0 && YEAR_CONTEXT.has(tok[i - 1]);
    if (has(CENTURIES, w) && i + 1 < tok.length) {
      if (tok[i + 1] === "hundred") {
        if (ctx) {
          const j = i + 2 + (i + 2 < tok.length && tok[i + 2] === "and" ? 1 : 0);
          const rest = j > i + 2 ? under100(tok, j) : null;
          out.push(CENTURIES[w] * 100 + (rest ? rest[0] : 0));
          i = rest ? rest[1] : i + 2;
          continue;
        }
      } else {
        const rest = under100(tok, i + 1);
        if (rest && rest[0] >= 1 && !has(UNITS, tok[i + 1])) {
          out.push(CENTURIES[w] * 100 + rest[0]);
          i = rest[1];
          continue;
        }
      }
    }
    if (w === "two" && tok[i + 1] === "thousand" && ctx) {
      const j = i + 2 + (i + 2 < tok.length && tok[i + 2] === "and" ? 1 : 0);
      const rest = under100(tok, j);
      out.push(2000 + (rest ? rest[0] : 0));
      i = rest ? rest[1] : i + 2;
      continue;
    }
    i += 1;
  }
  return out;
}

const NUMERAL_YEAR = /(?<![\d,.])(1\d{3}|20\d{2})(?![\d,])/g;

/** Every year in the unquoted text (aswas.years_in). */
export function yearsIn(text) {
  const t = norm(text);
  return [...t.matchAll(NUMERAL_YEAR)].map((m) => Number(m[1])).concat(spokenYears(t));
}

/** Modern names the horizon predates; every one when there is no horizon (aswas.modern_name_hits). */
export function modernNameHits(text, horizon, entries = LEXICON.period_names) {
  const base = norm(text);
  const out = [];
  for (const e of entries) {
    const until = parseDate(e.until);
    if (horizon && until && horizon[1] >= until[0]) continue;
    let t = base;
    for (const x of e.except ?? []) t = t.replace(rx(x, false), " ");
    if (rx(e.modern, false).test(t)) out.push({ modern: e.modern, period: e.period, until: e.until ?? null });
  }
  return out;
}

/** Every A0 problem in one piece of copy: hindsight phrases and years after the horizon, modern names, telling. */
export function copyProblems(text, { horizon = null } = {}) {
  const hindsight = phraseHits(text, LEXICON.hindsight);
  if (horizon) for (const y of yearsIn(text)) if (y > Number(horizon[1].slice(0, 4))) hindsight.push({ group: "year-after-horizon", phrase: String(y) });
  return { hindsight, modern: modernNameHits(text, horizon), tell: phraseHits(text, LEXICON.never_tell) };
}

/** Problems as sentences, empty when the copy holds. */
export function copyFindings(where, text, opts) {
  const p = copyProblems(text, opts);
  return [
    ...p.hindsight.map((h) => `${where}: hindsight (${h.group}): "${h.phrase}" (GRAMMAR A0: show as was, not as is)`),
    ...p.modern.map((h) => `${where}: modern name "${h.modern}": the period wrote ${h.period} (GRAMMAR A0)`),
    ...p.tell.map((h) => `${where}: tells (${h.group}): "${h.phrase}" (GRAMMAR A0: never tell)`),
  ];
}

/** A film's horizon read from its registry dates: the last year they name ("1946 to 1951" is 1951). */
export function horizonFromDates(dates) {
  const ys = [...String(dates ?? "").matchAll(/(?<!\d)(\d{4})(?!\d)/g)].map((m) => Number(m[1]));
  return ys.length ? parseDate(Math.max(...ys)) : null;
}
