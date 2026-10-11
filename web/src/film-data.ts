// The film's own record, read from the engine's sources.json (studio/engine/
// render.py's sources_doc): every shot with its mark and source, the mark
// track, the lower thirds and the readings. Everything the public pages show
// about a film is derived here, never typed, so the pages cannot drift from
// the film. Pure functions only: no DOM, no fetch (tests/film-data.test.ts).

export const MARK_CLASSES = ["ARCHIVE", "RECONSTRUCTED", "AI-GENERATED", "DRAWN", "CARD"] as const;
export type MarkClass = (typeof MARK_CLASSES)[number];

export interface Mark {
  class: MarkClass;
  detail: string;
}

export interface Shot {
  id: string;
  part: string;
  kind: string;
  start_s: number;
  end_s: number;
  /** The shot's first frame and the frame after its last, as the engine counted them. */
  start_frame: number;
  end_frame: number;
  mark: Mark;
  title: string | null;
  archive: string | null;
  item_url: string | null;
  date: string | null;
  creator: string | null;
  credit: string | null;
  licence: string | null;
  alterations: string[];
  /** How the shot enters: a cut, a dissolve, or a dip to black of `s` seconds centred on the cut. */
  transition: { type: string; s: number };
  preset: string | null;
  in_s: number | null;
  out_s: number | null;
  text: string[] | null;
}

export interface MarkSpan {
  from_s: number;
  to_s: number;
  from_frame: number;
  class: MarkClass;
  detail: string;
}

export interface LowerThird {
  id: string;
  start_s: number;
  end_s: number;
  lines: string[];
  flag: string | null;
}

export interface Reading {
  id: string;
  name: string;
  side: string;
  year: number | null;
  start_s: number;
  /** Seconds the reading lasts, when the engine wrote it (dur_s, or end_s - start_s). */
  dur_s: number | null;
  gender: string | null;
  /** The speaker's role (counters, counted, officials), when the film declares roles in its balance block. */
  role?: string | null;
  text: string;
  credit: string;
}

export interface Narration {
  id: string;
  start_s: number;
  text: string;
}

/** The poster still, as the release step recorded it beside the bytes it uploaded (studio/engine/publish.py). */
export interface Poster {
  ledger_id: string;
  title: string;
  creator: string | null;
  date: string | null;
  archive: string | null;
  licence: string;
  item_url: string | null;
  description: string | null;
  sha256: string;
}

export interface FilmSources {
  title: string;
  slug: string;
  fps: number;
  duration_s: number;
  /** The web encode the release uploaded, when recorded: its sha256 and measured duration. */
  web: { film_sha256: string; film_duration_s: number } | null;
  poster: Poster | null;
  shots: Shot[];
  marks: MarkSpan[];
  lowerThirds: LowerThird[];
  readings: Reading[];
  narration: Narration[];
  /** The trailer the release declared (publish.py --trailer), or null: then the site offers no trailer. */
  trailer: { sha256: string; duration_s: number | null } | null;
  /** The narrator's voice credit ("Narrated by a computer voice"), when the film has narration and records it. */
  narrator: string | null;
  /**
   * Whose words the film weighs, and by what measure: the film's declared
   * balance block, or the Partition film's own figures when its sources.json
   * predates the block. null when a declared block is malformed: then the
   * page shows no figures rather than the wrong ones.
   */
  balance: BalanceConfig | null;
  /** The film's stated imagery rule, in plain sentences, when sources.json carries one. */
  imagery: string[];
}

// ---- Parsing -------------------------------------------------------------

type Json = Record<string, unknown>;

const isObj = (x: unknown): x is Json => typeof x === "object" && x !== null && !Array.isArray(x);
const str = (x: unknown): string | null => (typeof x === "string" && x.trim() !== "" ? x : null);
const num = (x: unknown): number | null => (typeof x === "number" && Number.isFinite(x) ? x : null);

function need<T>(value: T | null, what: string): T {
  if (value === null) throw new Error(`sources.json: ${what} is missing or malformed`);
  return value;
}

function markClass(x: unknown, where: string): MarkClass {
  if (typeof x === "string" && (MARK_CLASSES as readonly string[]).includes(x)) return x as MarkClass;
  throw new Error(`sources.json: ${where} has an unknown mark class ${JSON.stringify(x)}`);
}

/** "f", "female", "F", "woman" are a woman's words; "m", "male", "man" a man's; anything else is refused. */
export function normaliseGender(x: unknown, where: string): "f" | "m" | null {
  if (x === null || x === undefined || x === "") return null;
  const g = typeof x === "string" ? x.trim().toLowerCase() : "";
  if (["f", "female", "woman"].includes(g)) return "f";
  if (["m", "male", "man"].includes(g)) return "m";
  throw new Error(`sources.json: ${where} has an unknown gender ${JSON.stringify(x)}`);
}

function parseShot(x: unknown, i: number, fps: number): Shot {
  if (!isObj(x)) throw new Error(`sources.json: shot ${i} is not an object`);
  const id = need(str(x.id), `shot ${i} id`);
  const mark = isObj(x.mark) ? x.mark : {};
  const start_s = need(num(x.start_s), `shot ${id} start_s`);
  const end_s = need(num(x.end_s), `shot ${id} end_s`);
  if (end_s <= start_s) throw new Error(`sources.json: shot ${id} ends before it starts`);
  return {
    id,
    part: str(x.part) ?? "",
    kind: str(x.kind) ?? "",
    start_s,
    end_s,
    start_frame: num(x.start_frame) ?? Math.round(start_s * fps),
    end_frame: num(x.end_frame) ?? Math.round(end_s * fps),
    mark: { class: markClass(mark.class, `shot ${id}`), detail: typeof mark.detail === "string" ? mark.detail : "" },
    title: str(x.title),
    archive: str(x.archive),
    item_url: safeUrl(x.item_url),
    date: str(x.date),
    creator: str(x.creator),
    credit: str(x.credit),
    licence: str(x.licence),
    alterations: Array.isArray(x.alterations) ? x.alterations.filter((a): a is string => typeof a === "string") : [],
    transition: isObj(x.transition_in) ? { type: str(x.transition_in.type) ?? "cut", s: num(x.transition_in.s) ?? 0 } : { type: "cut", s: 0 },
    preset: str(x.preset),
    in_s: num(x.in_s),
    out_s: num(x.out_s),
    text: Array.isArray(x.text) ? x.text.filter((t): t is string => typeof t === "string") : null,
  };
}

/** Only an https link to another site is ever rendered as a source link. */
export function safeUrl(x: unknown): string | null {
  if (typeof x !== "string") return null;
  try {
    const u = new URL(x);
    return u.protocol === "https:" ? u.href : null;
  } catch {
    return null;
  }
}

/** Reads and checks an engine sources.json (format v2). Throws with a reason on anything malformed. */
export function parseSources(json: unknown): FilmSources {
  if (!isObj(json)) throw new Error("sources.json: not an object");
  if (json.v !== 2) throw new Error(`sources.json: format ${JSON.stringify(json.v)} is not v2`);
  if (!Array.isArray(json.shots) || json.shots.length === 0) throw new Error("sources.json: no shots");
  const fps = num(json.fps) ?? 24;
  if (fps <= 0) throw new Error("sources.json: fps must be positive");
  const shots = json.shots.map((x, i) => parseShot(x, i, fps)).sort((a, b) => a.start_frame - b.start_frame);
  const duration_s = num(json.duration_s) ?? shots[shots.length - 1].end_s;

  const marks: MarkSpan[] = Array.isArray(json.marks)
    ? json.marks.filter(isObj).map((m, i) => {
        const from_s = need(num(m.from_s), `mark ${i} from_s`);
        // The track's times are the engine's frame boundaries rounded to 4 decimals: rounding recovers the frame.
        return {
          from_s,
          to_s: need(num(m.to_s), `mark ${i} to_s`),
          from_frame: Math.round(from_s * fps),
          class: markClass(m.class, `mark ${i}`),
          detail: typeof m.detail === "string" ? m.detail : "",
        };
      })
    : shots.map((s) => ({ from_s: s.start_s, to_s: s.end_s, from_frame: s.start_frame, class: s.mark.class, detail: s.mark.detail }));
  marks.sort((a, b) => a.from_frame - b.from_frame);

  const lowerThirds: LowerThird[] = (Array.isArray(json.lower_thirds) ? json.lower_thirds : []).filter(isObj).map((t, i) => ({
    id: str(t.id) ?? `T${i + 1}`,
    start_s: need(num(t.start_s), `lower third ${i} start_s`),
    end_s: need(num(t.end_s), `lower third ${i} end_s`),
    lines: Array.isArray(t.lines) ? t.lines.filter((l): l is string => typeof l === "string") : [],
    flag: str(t.flag),
  }));

  const readings: Reading[] = (Array.isArray(json.readings) ? json.readings : []).filter(isObj).map((r, i) => {
    const start_s = need(num(r.start_s), `reading ${i} start_s`);
    const end = num(r.end_s);
    const dur = num(r.dur_s) ?? (end !== null ? end - start_s : null);
    return {
      id: str(r.id) ?? `R${i + 1}`,
      name: str(r.name) ?? str(r.speaker) ?? "",
      side: (str(r.side) ?? "").toLowerCase(),
      year: num(r.year),
      start_s,
      dur_s: dur !== null && dur > 0 ? dur : null,
      gender: normaliseGender(r.gender, `reading ${str(r.id) ?? i}`),
      role: str(r.role)?.toLowerCase() ?? null,
      text: str(r.text) ?? "",
      credit: str(r.credit) ?? "",
    };
  });
  readings.sort((a, b) => a.start_s - b.start_s);

  const narration: Narration[] = (Array.isArray(json.narration) ? json.narration : [])
    .filter(isObj)
    .map((n, i) => ({ id: str(n.id) ?? `N${i + 1}`, start_s: need(num(n.start_s), `narration ${i} start_s`), text: str(n.text) ?? "" }))
    .filter((n) => n.text)
    .sort((a, b) => a.start_s - b.start_s);

  const web =
    isObj(json.web) && num(json.web.film_duration_s) !== null && str(json.web.film_sha256)
      ? { film_sha256: str(json.web.film_sha256) as string, film_duration_s: num(json.web.film_duration_s) as number }
      : null;

  return {
    title: str(json.title) ?? "",
    slug: str(json.slug) ?? "",
    fps,
    duration_s,
    web,
    poster: parsePoster(json.poster),
    shots,
    marks,
    lowerThirds,
    readings,
    narration,
    narrator: narration.length && isObj(json.narrator) ? str(json.narrator.credit) : null,
    trailer: parseTrailer(json.trailer),
    balance: balanceOf(json),
    imagery: imagerySentences(json.imagery_rule),
  };
}

/** The trailer record, only when it names its hash (publish.py records it only with --trailer). */
function parseTrailer(x: unknown): FilmSources["trailer"] {
  if (!isObj(x)) return null;
  const sha256 = str(x.sha256);
  if (!sha256 || !/^[0-9a-f]{64}$/.test(sha256)) return null;
  const d = num(x.duration_s);
  return { sha256, duration_s: d !== null && d > 0 ? d : null };
}

/** The trailer dialog's note: its length when recorded, rounded to whole minutes. */
export function trailerNote(t: NonNullable<FilmSources["trailer"]>): string {
  if (t.duration_s === null) return "Made under the same rules as the film.";
  const m = Math.max(1, Math.round(t.duration_s / 60));
  const words = NUMBER_WORDS[m] ? NUMBER_WORDS[m].toLowerCase() : String(m);
  return `About ${words} ${m === 1 ? "minute" : "minutes"}, made under the same rules as the film.`;
}

/** The poster record, only when it names its still, licence and hash; otherwise null and no credit is printed. */
function parsePoster(x: unknown): Poster | null {
  if (!isObj(x)) return null;
  const ledger_id = str(x.ledger_id);
  const title = str(x.title);
  const licence = str(x.licence);
  const sha256 = str(x.sha256);
  if (!ledger_id || !title || !licence || !sha256 || !/^[0-9a-f]{64}$/.test(sha256)) return null;
  return {
    ledger_id,
    title,
    creator: str(x.creator),
    date: str(x.date),
    archive: str(x.archive),
    licence,
    item_url: safeUrl(x.item_url),
    description: str(x.description),
    sha256,
  };
}

// ---- Time lookups ----------------------------------------------------------

/** The frame on screen at time t: the engine's frames are [f/fps, (f+1)/fps). */
export function frameAt(t: number, fps: number): number {
  return Math.floor(t * fps + 1e-6);
}

/** Where to seek to land inside a shot's first frame, not on its boundary. */
export function seekTime(start_s: number, fps: number): number {
  return start_s + 0.5 / fps;
}

/** True when the served film and its sources.json describe the same cut: durations within one frame. */
export function durationsAgree(videoDuration: number, data: Pick<FilmSources, "duration_s" | "fps">): boolean {
  return Number.isFinite(videoDuration) && Math.abs(videoDuration - data.duration_s) <= 1 / data.fps + 1e-6;
}

/** Seconds of the film actually played (a TimeRanges-like list), as a share of its duration. */
export function playedShare(ranges: { length: number; start(i: number): number; end(i: number): number }, duration: number): number {
  if (!(duration > 0)) return 0;
  let sum = 0;
  for (let i = 0; i < ranges.length; i++) sum += Math.max(0, ranges.end(i) - ranges.start(i));
  return Math.min(1, sum / duration);
}

/** Index of the last span whose start is at or before t (binary search); -1 before the first. */
function lastStartingBy<T>(items: T[], t: number, start: (x: T) => number): number {
  let lo = 0;
  let hi = items.length - 1;
  let found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (start(items[mid]) <= t + 1e-9) {
      found = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return found;
}

/** The mark on the frame shown at time t, looked up by frame. Past the end, the last mark; before 0, the first. */
export function markAt(marks: MarkSpan[], t: number, fps: number): MarkSpan | null {
  if (marks.length === 0) return null;
  const i = lastStartingBy(marks, frameAt(t, fps), (m) => m.from_frame);
  return marks[Math.max(0, i)];
}

/** A dip's picture level at `t` seconds into a dip of `dur` (motion.py dip_level): 0 only on its black hold. */
function dipBlack(t: number, dur: number, hold = 0.1): boolean {
  if (dur <= 0) return false;
  const u = t / dur;
  const a = 0.5 * (1 - hold);
  return u >= a && u <= 1 - a;
}

/**
 * True on a dip's black hold, where the burned frame is all black and carries
 * no mark (render.py picture_level and compose, founder ruling 2026-10-10), so
 * the player draws no mark either. Same arithmetic as the engine, by frame.
 */
export function onDipBlack(shots: Shot[], t: number, fps: number): boolean {
  const f = frameAt(t, fps);
  const i = Math.max(0, lastStartingBy(shots, f, (s) => s.start_frame));
  const shot = shots[i];
  if (!shot) return false;
  const tf = f / fps;
  const tl = tf - shot.start_frame / fps;
  if (shot.transition.type === "dip" && tl < shot.transition.s / 2 && dipBlack(tl + shot.transition.s / 2, shot.transition.s)) return true;
  const next = shots[i + 1];
  if (next && next.transition.type === "dip") {
    const ds = next.transition.s;
    const dt = next.start_frame / fps - tf;
    if (dt > 0 && dt <= ds / 2 && dipBlack(ds / 2 - dt, ds)) return true;
  }
  return false;
}

/** The shot on the frame shown at time t (same rule as markAt). */
export function shotAt(shots: Shot[], t: number, fps: number): Shot | null {
  if (shots.length === 0) return null;
  const i = lastStartingBy(shots, frameAt(t, fps), (s) => s.start_frame);
  return shots[Math.max(0, i)];
}

/** The lower third burned into the picture at time t, if any. */
export function lowerThirdAt(lts: LowerThird[], t: number): LowerThird | null {
  return lts.find((lt) => lt.start_s <= t && t < lt.end_s) ?? null;
}

/** The words a mark plate shows: "ARCHIVE" + detail, or "VOID DOCUMENT" on a card. */
export function markWords(m: Pick<Mark, "class" | "detail">): { cls: string; detail: string } {
  if (m.class === "CARD") return { cls: "VOID DOCUMENT", detail: "" };
  return { cls: m.class, detail: m.detail };
}

/** The CSS hook for a mark's hue rule (house.css .mark[data-class]). */
export function markHook(c: MarkClass): string {
  return { ARCHIVE: "archive", RECONSTRUCTED: "reconstructed", "AI-GENERATED": "generated", DRAWN: "drawn", CARD: "card" }[c];
}

// ---- Chapters ----------------------------------------------------------------

export interface Chapter {
  id: string;
  n: number | null;
  title: string;
  dates: string;
  start_s: number;
  end_s: number;
}

const CHAPTER_CARD = /^(\d+)\s+(.+)$/;
/** An unnumbered part's own title card: a short title, then its dates (the close's "Those who stayed" / "1947 to today"). */
const PART_CARD_DATES = /\b(1[89]|20)\d\d\b/;
const FIXED_PARTS: Record<string, string> = { "cold-open": "Cold open", close: "Close", credits: "Credits" };

function chapterCard(shot: Shot): { n: number; title: string; dates: string } | null {
  if (shot.kind !== "card" || !shot.text || shot.text.length === 0) return null;
  const m = CHAPTER_CARD.exec(shot.text[0].trim());
  return m ? { n: Number(m[1]), title: m[2].trim(), dates: (shot.text[1] ?? "").trim() } : null;
}

/**
 * The title an unnumbered part gives itself on its first shot: a card of two
 * lines, a short title that is not a sentence, then dates. A record-is-silent
 * card or the credits' statement is never read as a title.
 */
function partCard(first: Shot): { title: string; dates: string } | null {
  const t = first.text;
  if (first.kind !== "card" || !t || t.length !== 2) return null;
  const title = t[0].trim();
  const dates = t[1].trim();
  if (!title || title.length > 40 || /[.;:]$/.test(title) || !PART_CARD_DATES.test(dates)) return null;
  return { title, dates };
}

/**
 * The film's chapters, from its parts: a numbered chapter starts at its
 * chapter card (which can sit at the end of the part before it), the cold
 * open at 0, and the close and credits where their parts begin, under the
 * title their own card gives them when they have one. The title part folds
 * into the cold open.
 */
export function chapters(data: Pick<FilmSources, "shots" | "duration_s">): Chapter[] {
  const cards = new Map<number, { shot: Shot; n: number; title: string; dates: string }>();
  for (const s of data.shots) {
    const c = chapterCard(s);
    if (c && !cards.has(c.n)) cards.set(c.n, { shot: s, ...c });
  }
  const out: Chapter[] = [];
  const seen = new Set<string>();
  for (const s of data.shots) {
    if (seen.has(s.part) || s.part === "title") continue;
    seen.add(s.part);
    const ch = /^ch-(\d+)$/.exec(s.part);
    if (ch) {
      const n = Number(ch[1]);
      const card = cards.get(n);
      out.push({
        id: s.part,
        n,
        title: card?.title ?? `Chapter ${n}`,
        dates: card?.dates ?? "",
        start_s: Math.min(s.start_s, card?.shot.start_s ?? Infinity),
        end_s: 0,
      });
    } else {
      const own = partCard(s);
      const title = own?.title ?? FIXED_PARTS[s.part] ?? s.part.replace(/-/g, " ").replace(/^./, (c) => c.toUpperCase());
      out.push({ id: s.part, n: null, title, dates: own?.dates ?? "", start_s: s.part === "cold-open" ? 0 : s.start_s, end_s: 0 });
    }
  }
  out.sort((a, b) => a.start_s - b.start_s);
  out.forEach((c, i) => (c.end_s = i + 1 < out.length ? out[i + 1].start_s : data.duration_s));
  return out;
}

export function chapterAt(list: Chapter[], t: number): Chapter | null {
  if (list.length === 0) return null;
  return list[Math.max(0, lastStartingBy(list, t, (c) => c.start_s))];
}

/** The chapter to jump to with ] (dir 1) or [ (dir -1). [ within 3 s of a chapter's start goes to the one before. */
export function stepChapter(list: Chapter[], t: number, dir: 1 | -1): Chapter | null {
  if (list.length === 0) return null;
  const i = Math.max(0, lastStartingBy(list, t, (c) => c.start_s));
  if (dir === 1) return list[i + 1] ?? null;
  return t - list[i].start_s > 3 ? list[i] : list[Math.max(0, i - 1)];
}

// ---- Words: readings, transcript, the record's silences ------------------------

const LT_SUFFIX = /\s+·\s+(read by a computer voice|original recording)\s*$/;

/** A reading's source, as its speaker's lower third names it (line 3 without its voice suffix). */
export function readingSource(r: Reading, lts: LowerThird[]): string | null {
  const lt = lts.find((x) => x.lines.length === 3 && x.lines[0] === r.name && x.start_s <= r.start_s + 1e-6 && r.start_s < x.end_s)
    ?? lts.find((x) => x.lines.length === 3 && x.lines[0] === r.name);
  return lt ? lt.lines[2].replace(LT_SUFFIX, "").trim() : null;
}

/** The partisan flag shown above a reading's lower third ("Account of ..."), if any. */
export function readingFlag(r: Reading, lts: LowerThird[]): string | null {
  return lts.find((x) => x.lines[0] === r.name && x.flag)?.flag ?? null;
}

export interface TranscriptEntry {
  id: string;
  start_s: number;
  who: string;
  text: string;
}

/** Everything spoken, in order: the readings with their speakers, and the narration when sources.json carries it. */
export function transcript(data: Pick<FilmSources, "readings" | "narration">): TranscriptEntry[] {
  return [
    ...data.readings.map((r) => ({ id: r.id, start_s: r.start_s, who: r.name, text: r.text })),
    ...data.narration.map((n) => ({ id: n.id, start_s: n.start_s, who: "Narrator", text: n.text })),
  ].sort((a, b) => a.start_s - b.start_s);
}

/** The last record-is-silent card (GRAMMAR 9): what the record lacks, and what was searched. */
export function silentRecord(shots: Shot[]): { says: string; searched: string } | null {
  for (let i = shots.length - 1; i >= 0; i--) {
    const t = shots[i].text;
    if (shots[i].kind === "card" && t && /^The record holds no .+\.$/.test(t[0])) return { says: t[0], searched: t[1] ?? "" };
  }
  return null;
}

// ---- The balance: whose words, and how long ------------------------------------

export interface SideBalance {
  side: string;
  label: string;
  seconds: number;
  share: number;
  speakers: string[];
}

export interface Balance {
  /** Always computed from the film's own readings in sources.json: there is no planned fallback. */
  from: "film";
  total_s: number;
  sides: SideBalance[];
  /** Seconds by declared role, or null when the film declares no roles (or a reading's role is not one of them). */
  roles: Shares[] | null;
  /** Sides heard with fewer named speakers than the film's stated minimum (none when it states no minimum). */
  speakersShort: { side: string; label: string; count: number }[];
  women: { seconds: number; share: number; names: { name: string; seconds: number }[] };
}

/**
 * A film's balance block (sources.json `balance`, written by the engine from
 * the screenplay): the sides and roles its readings are weighed by, with the
 * label each prints under, the share band each side should hold, the floor
 * for women's words, and the fewest named speakers a side heard should have
 * (GRAMMAR 6.4 and 6.5, as the film declares them).
 */
export interface BalanceConfig {
  sides: { id: string; label: string; phrase: string }[];
  roles: { id: string; label: string }[];
  band: { min: number; max: number };
  women_floor: number;
  /** null: the film states no minimum, and the page prints none. */
  named_speakers_min: number | null;
}

/**
 * The Partition film's figures, as the site held them before films declared
 * their own: its live sources.json has no balance block, and must keep
 * rendering exactly as it did with no re-upload.
 */
/** The pilot, the one film whose live sources.json predates the balance block (films.json balance_fallback). */
export const PARTITION_SLUG = "partition-of-india";

export const PARTITION_BALANCE: BalanceConfig = {
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
};

const BALANCE_ID = /^[a-z][a-z0-9_-]*$/;
const shareOf = (x: unknown): number | null => {
  const n = num(x);
  return n !== null && n >= 0 && n <= 1 ? n : null;
};

/** A side with no label of its own: Partition's name for it, else its id as a word ("uk" as UK, "india" as India). */
function defaultLabel(id: string): { label: string; phrase: string } {
  const known = PARTITION_BALANCE.sides.find((s) => s.id === id);
  if (known) return { label: known.label, phrase: known.phrase };
  const word = id.length <= 3 ? id.toUpperCase() : id.replace(/[-_]/g, " ").replace(/^./, (c) => c.toUpperCase());
  return { label: word, phrase: word };
}

/** Sides or roles as the engine writes them: bare ids, or objects with an id and optionally a label and phrase. */
function parseLabelled(list: unknown): { id: string; label: string; phrase: string }[] | null {
  if (!Array.isArray(list)) return null;
  const out: { id: string; label: string; phrase: string }[] = [];
  for (const s of list) {
    const id = (typeof s === "string" ? s : isObj(s) ? str(s.id) : null)?.toLowerCase();
    if (!id || !BALANCE_ID.test(id) || out.some((o) => o.id === id)) return null;
    const fallback = defaultLabel(id);
    const label = isObj(s) ? (str(s.label) ?? fallback.label) : fallback.label;
    const phrase = isObj(s) ? (str(s.phrase) ?? (str(s.label) ? label : fallback.phrase)) : fallback.phrase;
    out.push({ id, label, phrase });
  }
  return out;
}

/**
 * Reads a balance block as the engine writes it (sources.json `balance`, the
 * screenplay's own: GRAMMAR 6.4 and A22). Only `sides` is required, as ids or
 * as {id, label, phrase}; `roles` likewise; `band`, `women_floor` (else the
 * film's `settings.women_floor`, else 0.30) and `named_speakers_min` are
 * optional. null when anything present is malformed: the page then prints no
 * figures rather than guessed ones.
 */
export function parseBalance(x: unknown, settings?: unknown): BalanceConfig | null {
  if (!isObj(x)) return null;
  const sides = parseLabelled(x.sides);
  if (!sides || sides.length === 0) return null;
  const roles = x.roles === undefined || x.roles === null ? [] : parseLabelled(x.roles);
  if (!roles) return null;
  let band = PARTITION_BALANCE.band;
  if (x.band !== undefined && x.band !== null) {
    const min = isObj(x.band) ? shareOf(x.band.min) : null;
    const max = isObj(x.band) ? shareOf(x.band.max) : null;
    if (min === null || max === null || min > max) return null;
    band = { min, max };
  }
  const stated = x.women_floor ?? (isObj(settings) ? settings.women_floor : undefined);
  const floor = stated === undefined || stated === null ? PARTITION_BALANCE.women_floor : shareOf(stated);
  if (floor === null) return null;
  let speakers: number | null = null;
  if (x.named_speakers_min !== undefined && x.named_speakers_min !== null) {
    speakers = num(x.named_speakers_min);
    if (speakers === null || speakers < 0 || !Number.isInteger(speakers)) return null;
  }
  return { sides, roles: roles.map(({ id, label }) => ({ id, label })), band, women_floor: floor, named_speakers_min: speakers };
}

/**
 * Which balance a sources.json gives: its declared `balance`; else its
 * `sides` (the cast's sides, which the engine always writes) with Partition's
 * band and floor; else, only for the Partition pilot (its live file predates
 * both), Partition's own figures; any other film, none.
 */
export function balanceOf(json: Record<string, unknown>): BalanceConfig | null {
  if (json.balance !== undefined && json.balance !== null) return parseBalance(json.balance, json.settings);
  if (Array.isArray(json.sides) && json.sides.length) return parseBalance({ sides: json.sides }, json.settings);
  // Only the pilot's live file predates the block; any other film without one shows no figures (contract.yaml requires it declared).
  return json.slug === PARTITION_SLUG ? PARTITION_BALANCE : null;
}

/** The label a side prints under (the declared one), or the side's own id when the film declares none. */
export function sideLabel(config: BalanceConfig | null, side: string): string {
  return (config ?? PARTITION_BALANCE).sides.find((s) => s.id === side)?.label ?? side;
}

/** "Accounts from Britain, India, Pakistan and the Sikh community.": the declared sides that have readings, in declared order. */
export function accountsSentence(config: BalanceConfig | null, readings: Reading[]): string | null {
  const names = (config ?? PARTITION_BALANCE).sides.filter((s) => readings.some((r) => r.side === s.id)).map((s) => s.phrase);
  return names.length ? `Accounts from ${listWords(names)}.` : null;
}

export interface Shares {
  id: string;
  label: string;
  seconds: number;
  share: number;
  speakers: string[];
}

/**
 * The balance computed from the film's readings, or null when sources.json
 * does not say how long each reading lasts, whose side it is, or whether it
 * is a woman's words: then the page says the figures are not available. The
 * roles axis is measured only when the film declares roles, and is null when
 * a reading has a role it does not declare.
 */
export function computeBalance(readings: Reading[], config: BalanceConfig | null = PARTITION_BALANCE): Balance | null {
  if (!config || readings.length === 0) return null;
  const ids = config.sides.map((s) => s.id);
  if (readings.some((r) => r.dur_s === null || r.gender === null || !ids.includes(r.side))) return null;
  const total = readings.reduce((sum, r) => sum + (r.dur_s ?? 0), 0);
  if (total <= 0) return null;
  const measure = (id: string, label: string, rs: Reading[]): Shares => {
    const seconds = rs.reduce((sum, r) => sum + (r.dur_s ?? 0), 0);
    return { id, label, seconds, share: seconds / total, speakers: [...new Set(rs.map((r) => r.name))] };
  };
  const sides = config.sides.map((s) => {
    const m = measure(s.id, s.label, readings.filter((r) => r.side === s.id));
    return { side: m.id, label: m.label, seconds: m.seconds, share: m.share, speakers: m.speakers };
  });
  const roleIds = config.roles.map((r) => r.id);
  const roles =
    config.roles.length && readings.every((r) => r.role && roleIds.includes(r.role))
      ? config.roles.map((role) => measure(role.id, role.label, readings.filter((r) => r.role === role.id)))
      : null;
  const min = config.named_speakers_min;
  const named = (s: SideBalance) => s.speakers.filter(Boolean).length;
  const speakersShort = min === null ? [] : sides.filter((s) => s.seconds > 0 && named(s) < min).map((s) => ({ side: s.side, label: s.label, count: named(s) }));
  const byWoman = new Map<string, number>();
  for (const r of readings) if (r.gender === "f") byWoman.set(r.name, (byWoman.get(r.name) ?? 0) + (r.dur_s ?? 0));
  const womenS = [...byWoman.values()].reduce((a, b) => a + b, 0);
  return {
    from: "film",
    total_s: total,
    sides,
    roles,
    speakersShort,
    women: { seconds: womenS, share: womenS / total, names: [...byWoman].map(([name, seconds]) => ({ name, seconds })) },
  };
}

/** Seconds of picture by mark, whole film, with ARCHIVE split into film and photographs. */
export function secondsByMark(shots: Shot[]): { key: string; label: string; seconds: number; share: number }[] {
  const total = shots.reduce((s, x) => s + (x.end_s - x.start_s), 0) || 1;
  const sum = (f: (s: Shot) => boolean) => shots.filter(f).reduce((a, s) => a + (s.end_s - s.start_s), 0);
  const rows = [
    { key: "archive-film", label: "ARCHIVE film", seconds: sum((s) => s.mark.class === "ARCHIVE" && s.kind === "archive_video") },
    { key: "archive-still", label: "ARCHIVE photographs", seconds: sum((s) => s.mark.class === "ARCHIVE" && s.kind !== "archive_video") },
    { key: "reconstructed", label: "RECONSTRUCTED", seconds: sum((s) => s.mark.class === "RECONSTRUCTED") },
    { key: "drawn", label: "DRAWN", seconds: sum((s) => s.mark.class === "DRAWN") },
    { key: "card", label: "CARD", seconds: sum((s) => s.mark.class === "CARD") },
    { key: "generated", label: "AI-GENERATED", seconds: sum((s) => s.mark.class === "AI-GENERATED") },
  ];
  return rows.map((r) => ({ ...r, share: r.seconds / total }));
}

// ---- Words for one shot (Sources) -------------------------------------------------

/** "The photograph at Wikimedia Commons", "The film at the Internet Archive". */
export function itemLinkLabel(shot: Shot): string {
  const what = shot.kind === "archive_video" ? "The film" : shot.kind === "archive_still" ? "The photograph" : "The item";
  let where = shot.archive ?? "the archive";
  if (shot.item_url) {
    const host = new URL(shot.item_url).hostname;
    if (host.endsWith("wikimedia.org")) where = "Wikimedia Commons";
    else if (host.endsWith("archive.org")) where = "the Internet Archive";
    else if (host.endsWith("archives.gov")) where = "the National Archives";
    else if (host.endsWith("loc.gov")) where = "the Library of Congress";
  }
  return `${what} at ${where}`;
}

/** What a shot is, in plain words, with its length on screen. */
export function shotWhat(shot: Shot): string {
  const secs = Math.round(shot.end_s - shot.start_s);
  if (shot.kind === "archive_video") return `Film, ${secs} s`;
  if (shot.kind === "archive_still") return `Photograph${shot.date ? `, ${shot.date}` : ""}, held ${secs} s`;
  if (shot.kind === "black") return `Black, under a voice or in silence, ${secs} s`;
  if (shot.kind === "card") return `Text on black, ${secs} s`;
  if (shot.kind === "drawn") return `Drawn, ${secs} s`;
  return `${secs} s`;
}

/** What was done to the item, in plain words (GRAMMAR 4.2's closed list, or what is allowed without a mark change). */
export function shotTreatment(shot: Shot): string | null {
  if (shot.mark.class === "CARD") return null;
  if (shot.alterations.length) return `Changed: ${shot.alterations.join(", ")}.`;
  if (shot.kind === "archive_still") return shot.preset ? "Shown whole, then the camera moves slowly across it. Nothing in the picture is changed." : "Shown whole. Nothing in the picture is changed.";
  if (shot.kind === "archive_video") return "Trimmed, shown at its own speed. Nothing in the picture is changed.";
  return null;
}

/** A card's own words, or a plain name for a black hold or the credits. */
export function cardTitle(shot: Shot): string {
  if (shot.text && shot.text.length) return shot.text.join(" ");
  if (shot.part === "credits") return "The credits";
  if (shot.kind === "black") return "Black";
  return "A card";
}

// ---- Time formatting ---------------------------------------------------------------

/** 0:00, 11:07, 1:02:03. */
export function formatTime(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds + 1e-6));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

/** "17:12" or "1:02:03" to seconds; null for anything else. */
export function parseTimecode(text: string): number | null {
  const m = /^\s*(?:(\d+):)?(\d{1,3}):([0-5]\d)\s*$/.exec(text);
  if (!m) return null;
  return Number(m[1] ?? 0) * 3600 + Number(m[2]) * 60 + Number(m[3]);
}

/** A percentage with one decimal, as the treatment writes them ("34.3%"). */
export function pct(share: number): string {
  return `${(Math.round(share * 1000) / 10).toFixed(1)}%`;
}

// ---- Printed claims, derived (never typed) ------------------------------------------

const NUMBER_WORDS = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"];

/** "No AI-generated images in this film.", or how many shots are, from the shots' own marks. */
export function aiSentence(shots: Shot[]): string {
  const n = shots.filter((s) => s.mark.class === "AI-GENERATED").length;
  if (n === 0) return "No AI-generated images in this film.";
  const count = n < NUMBER_WORDS.length ? NUMBER_WORDS[n] : String(n);
  return `${count} ${n === 1 ? "shot" : "shots"} in this film ${n === 1 ? "is" : "are"} AI-generated, each marked AI-GENERATED.`;
}

/** How the narration and the readings are voiced, from their credits in sources.json. */
export function voiceSentence(readings: Reading[], narrator: string | null = null): string | null {
  const computerNarrator = narrator !== null && narrator.startsWith("Narrated by a computer voice");
  if (readings.length === 0) return computerNarrator ? "The narrator is a computer voice." : null;
  const computer = readings.filter((r) => r.credit.startsWith("Read by a computer voice")).length;
  const own = readings.length - computer;
  const except = own ? `, except ${own === 1 ? "one original recording" : `${own} original recordings`}` : "";
  if (computerNarrator) return `The narrator and the readings are computer voices${except}; no recording is imitated.`;
  if (own === 0) return "Voices are read by a computer; no recording is imitated.";
  return `Voices are read by a computer${except}; no recording is imitated.`;
}

function listWords(items: string[]): string {
  return items.length > 1 ? `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}` : (items[0] ?? "");
}

/** The archives the film's pictures come from, most seconds on screen first. */
export function archivesOnScreen(shots: Shot[]): string[] {
  const secs = new Map<string, number>();
  for (const s of shots) {
    // Only archival pictures: a DRAWN map or a CARD is not film or a photograph from an archive.
    if ((s.mark.class !== "ARCHIVE" && s.mark.class !== "RECONSTRUCTED") || !s.archive) continue;
    for (const a of s.archive.split(/\s*\/\s*|\s*;\s*/)) if (a) secs.set(a, (secs.get(a) ?? 0) + (s.end_s - s.start_s));
  }
  return [...secs].sort((a, b) => b[1] - a[1]).map(([a]) => a);
}

/** The publications the readings come from: each speaker's lower-third source up to its first comma, first heard first. */
export function readingPublications(readings: Reading[], lts: LowerThird[]): string[] {
  const out: string[] = [];
  for (const r of readings) {
    const src = readingSource(r, lts);
    const head = src ? src.split(",")[0].trim() : "";
    if (head && !out.includes(head)) out.push(head);
  }
  return out;
}

/** The screening room's credit line, from the shots' archives and the readings' sources. */
export function creditsLine(data: Pick<FilmSources, "shots" | "readings" | "lowerThirds">, maxEach = 3): string {
  const shorten = (xs: string[]) => (xs.length > maxEach ? [...xs.slice(0, maxEach), `${xs.length - maxEach} other ${xs.length - maxEach === 1 ? "source" : "sources"}`] : xs);
  const archives = archivesOnScreen(data.shots);
  const pubs = readingPublications(data.readings, data.lowerThirds);
  const parts: string[] = [];
  if (archives.length) parts.push(`Film and photographs from ${listWords(shorten(archives))}.`);
  if (pubs.length) parts.push(`Words from ${listWords(shorten(pubs))}.`);
  if (parts.length) parts.push("Sources lists every one.");
  return parts.join(" ");
}

/** The poster's credit, as printed under it. */
export function posterCredit(p: Poster): string {
  const who = [p.creator, p.date].filter(Boolean).join(", ");
  return [`${p.title}.`, who ? `${who}.` : "", [p.archive, /^public domain/i.test(p.licence) ? p.licence.toLowerCase() : p.licence].filter(Boolean).join(", ") + "."].filter(Boolean).join(" ");
}

// ---- The imagery rule (sources.json `imagery_rule`) ---------------------------------------

/**
 * The film's imagery rule in plain sentences, for its Sources page (GRAMMAR
 * A21: what a film shows is as its rule states, and the rule is stated on the
 * Sources page). The engine always writes the rule; only a rule the film
 * declared (`declared: true`) is printed, so a film on the default rule (the
 * Partition film, whose page already says it shows no bodies or killing) is
 * unchanged. The film's own `statement` comes first, as written; then what
 * the settings add, in plain words. Unknown settings are ignored, never
 * guessed at.
 */
export function imagerySentences(x: unknown): string[] {
  if (!isObj(x) || x.declared !== true) return [];
  const out: string[] = [];
  const stated = str(x.statement);
  if (stated) out.push(stated.trim());
  else {
    if (x.show_disease === true) out.push(`This film shows ${str(x.subject) ?? "the disease"} as the photographs and films of the time record it.`);
    const not = [x.show_bodies === false ? "bodies" : null, x.show_violence === false ? "violence" : null].filter(Boolean);
    if (not.length) out.push(`It shows no ${not.join(" or ")}.`);
  }
  // The rules for a photograph of a patient apply where the film shows disease.
  if (x.show_disease === true) {
    if (x.name_only_where_source_names === true) out.push("A person is named only where the source names them; anyone else is given the place and date of the picture.");
    const hold = num(x.min_hold_s);
    if (hold !== null && hold > 0) out.push(`A photograph of a patient is held at least ${Math.round(hold)} s, never flashed.`);
    if (x.no_detail_on_face === true) out.push("The camera never moves in close on a patient's face.");
    if (x.no_dissolve_into_patient === true) out.push("A photograph of a patient never dissolves out of an unrelated picture.");
  }
  return out;
}
