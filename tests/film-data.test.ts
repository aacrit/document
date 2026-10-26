// The site's reading of the engine's sources.json (web/src/film-data.ts),
// against a trimmed copy of the Partition trailer's own file.
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  aiSentence,
  archivesOnScreen,
  creditsLine,
  durationsAgree,
  frameAt,
  playedShare,
  posterCredit,
  readingPublications,
  seekTime,
  voiceSentence,
  chapterAt,
  chapters,
  computeBalance,
  formatTime,
  itemLinkLabel,
  lowerThirdAt,
  markAt,
  onDipBlack,
  markWords,
  BLACK_FLOOR_COPY,
  parseLevels,
  stillCamera,
  parseSources,
  parseTimecode,
  pct,
  readingFlag,
  readingSource,
  safeUrl,
  secondsByMark,
  shotAt,
  shotTreatment,
  shotWhat,
  silentRecord,
  sourceGaps,
  filmNotes,
  statementText,
  stepChapter,
  transcript,
  trailerNote,
  type Reading,
} from "../web/src/film-data";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const raw = () => JSON.parse(readFileSync(path.join(root, "tests/fixtures/sources-trailer.json"), "utf8"));
const film = parseSources(raw());

describe("parseSources", () => {
  it("reads the trailer's sources.json: 24 shots in time order, the mark track, lower thirds and readings", () => {
    expect(film.title).toBe("The Partition of India · Trailer");
    expect(film.duration_s).toBe(297.625);
    expect(film.shots).toHaveLength(24);
    expect(film.shots.every((s, i) => i === 0 || s.start_s >= film.shots[i - 1].start_s)).toBe(true);
    expect(film.marks[0]).toEqual({ from_s: 0, to_s: 18, from_frame: 0, class: "ARCHIVE", detail: "Wikimedia Commons 1947" });
    expect(film.lowerThirds).toHaveLength(8);
    expect(film.readings.map((r) => r.id)).toEqual(["R1", "R5", "R6", "R2", "R9", "R7", "R8"]);
    expect(film.readings[0]).toMatchObject({ name: "Arthur Henderson", side: "britain", year: 1947, start_s: 62, dur_s: null, gender: null });
    expect(film.narration).toEqual([]);
  });

  it("keeps a card's text and nulls a card's missing source fields", () => {
    const s03 = film.shots.find((s) => s.id === "S03")!;
    expect(s03.mark).toEqual({ class: "CARD", detail: "" });
    expect(s03.text).toEqual(["The Partition of India · Trailer", "void document"]);
    expect(s03.item_url).toBeNull();
    expect(s03.title).toBeNull();
  });

  it("refuses a file that is not format v2, has no shots, or carries an unknown mark class", () => {
    expect(() => parseSources({ ...raw(), v: 1 })).toThrow(/not v2/);
    expect(() => parseSources({ ...raw(), shots: [] })).toThrow(/no shots/);
    const bad = raw();
    bad.shots[0].mark.class = "MAYBE";
    expect(() => parseSources(bad)).toThrow(/unknown mark class/);
    const backwards = raw();
    backwards.shots[0].end_s = -1;
    expect(() => parseSources(backwards)).toThrow(/ends before it starts/);
    expect(() => parseSources(null)).toThrow();
  });

  it("builds the mark track from the shots when the file has none", () => {
    const noTrack = raw();
    delete noTrack.marks;
    const f = parseSources(noTrack);
    expect(f.marks).toHaveLength(24);
    expect(markAt(f.marks, 20, 24)?.class).toBe("CARD");
  });

  it("renders only https item links; anything else is dropped", () => {
    expect(safeUrl("https://commons.wikimedia.org/wiki/File:X.jpg")).toBe("https://commons.wikimedia.org/wiki/File:X.jpg");
    expect(safeUrl("javascript:alert(1)")).toBeNull();
    expect(safeUrl("http://example.org/")).toBeNull();
    expect(safeUrl(42)).toBeNull();
  });

  it("reads reading durations and genders when the engine writes them", () => {
    const withDur = raw();
    withDur.readings[0].end_s = 72.4;
    withDur.readings[0].gender = "m";
    withDur.readings[1].dur_s = 16;
    const f = parseSources(withDur);
    expect(f.readings[0].dur_s).toBeCloseTo(10.4);
    expect(f.readings[0].gender).toBe("m");
    expect(f.readings[1].dur_s).toBe(16);
  });
});

describe("the mark at a time", () => {
  it("is the span holding the time, changing exactly at the cut", () => {
    expect(markAt(film.marks, 0, 24)).toMatchObject({ class: "ARCHIVE", detail: "Wikimedia Commons 1947" });
    expect(markAt(film.marks, 17.999, 24)?.class).toBe("ARCHIVE");
    expect(markAt(film.marks, 18, 24)?.class).toBe("CARD");
    expect(markAt(film.marks, 27, 24)).toMatchObject({ class: "ARCHIVE", detail: "NARA / Internet Archive 1946" });
    expect(markAt(film.marks, 52.49, 24)?.detail).toBe("NARA / Internet Archive 1946");
    expect(markAt(film.marks, 52.5, 24)?.class).toBe("CARD");
    expect(markAt(film.marks, 80, 24)?.detail).toBe("Wikimedia Commons 1950");
  });

  it("holds the first mark before 0 and the last past the end", () => {
    expect(markAt(film.marks, -3, 24)?.from_s).toBe(0);
    expect(markAt(film.marks, 400, 24)?.class).toBe("CARD");
    expect(markAt([], 10, 24)).toBeNull();
  });

  it("agrees with the shot on screen at every second of the film", () => {
    for (let t = 0; t < film.duration_s; t += 0.5) {
      expect(markAt(film.marks, t, 24)?.class, `t=${t}`).toBe(shotAt(film.shots, t, 24)?.mark.class);
    }
  });

  it("says VOID DOCUMENT on a card, the class and detail elsewhere", () => {
    expect(markWords({ class: "CARD", detail: "" })).toEqual({ cls: "VOID DOCUMENT", detail: "" });
    expect(markWords({ class: "ARCHIVE", detail: "Wikimedia Commons 1947" })).toEqual({ cls: "ARCHIVE", detail: "Wikimedia Commons 1947" });
  });

  it("finds the lower third on screen, so a caption can move above it", () => {
    expect(lowerThirdAt(film.lowerThirds, 63)?.lines[0]).toBe("Arthur Henderson");
    expect(lowerThirdAt(film.lowerThirds, 67)).toBeNull();
    expect(lowerThirdAt(film.lowerThirds, 10)).toBeNull();
  });
});

describe("chapters", () => {
  it("title an unnumbered part from its own card (the close's 'Those who stayed'), never from a record-is-silent card", () => {
    const data = raw();
    type S = { part: string; start_s: number };
    const close = (data.shots as S[]).filter((x) => x.part === "close").sort((a, b) => a.start_s - b.start_s)[0];
    Object.assign(close, { kind: "card", mark: { class: "CARD", detail: "" }, text: ["Those who stayed", "1947 to today"] });
    const list = chapters(parseSources(data));
    const ch = list.find((c) => c.id === "close");
    expect([ch?.title, ch?.dates, ch?.n]).toEqual(["Those who stayed", "1947 to today", null]);
    expect(list.filter((c) => c.n !== null)).toHaveLength(3);
    // The credits keep their fixed name; the unmodified fixture's close opens on a record-is-silent card and stays "Close".
    expect(list.find((c) => c.id === "credits")?.title).toBe("Credits");
    expect(chapters(film).find((c) => c.id === "close")?.title).toBe("Close");
  });

  const list = chapters(film);

  it("are the parts in order: the cold open from 0, each numbered chapter from its card, then the close", () => {
    expect(list.map((c) => [c.id, c.n, c.title, c.start_s])).toEqual([
      ["cold-open", null, "Cold open", 0],
      ["ch-1", 1, "The count", 23],
      ["ch-2", 2, "The line", 101.5],
      ["ch-3", 3, "The roads", 166],
      ["close", null, "Close", 199.625],
      ["credits", null, "Credits", 279.125],
    ]);
    expect(list[1].dates).toBe("1946 to 3 June 1947");
  });

  it("tile the film with no gap", () => {
    expect(list[list.length - 1].end_s).toBe(film.duration_s);
    for (let i = 1; i < list.length; i++) expect(list[i].start_s).toBe(list[i - 1].end_s);
  });

  it("know which chapter a time is in, and step with [ and ]", () => {
    expect(chapterAt(list, 0)?.id).toBe("cold-open");
    expect(chapterAt(list, 22.9)?.id).toBe("cold-open");
    expect(chapterAt(list, 23)?.id).toBe("ch-1");
    expect(chapterAt(list, 150)?.id).toBe("ch-2");
    expect(stepChapter(list, 30, 1)?.id).toBe("ch-2");
    expect(stepChapter(list, 30, -1)?.id).toBe("ch-1");
    expect(stepChapter(list, 24, -1)?.id).toBe("cold-open");
    expect(stepChapter(list, 290, 1)).toBeNull();
  });
});

describe("words: sources, flags, the transcript, the record's silences", () => {
  it("names a reading's source from its speaker's lower third, without the voice suffix", () => {
    expect(readingSource(film.readings[0], film.lowerThirds)).toBe("Hansard, House of Commons, 17 March 1947");
    expect(readingFlag(film.readings[0], film.lowerThirds)).toBeNull();
  });

  it("lists the readings in order with their speakers", () => {
    const t = transcript(film);
    expect(t).toHaveLength(7);
    expect(t[0]).toMatchObject({ start_s: 62, who: "Arthur Henderson" });
    expect(t.map((e) => e.start_s)).toEqual([...t.map((e) => e.start_s)].sort((a, b) => a - b));
  });

  it("finds the last record-is-silent card of a film rendered before A56, and says it was on screen", () => {
    expect(silentRecord(film)?.says).toBe("The record holds no first-person account under an open licence by a Bengali or Bangladeshi witness.");
    expect(silentRecord(film)?.searched).toMatch(/^Searched: FRUS/);
    expect(silentRecord(film)?.on_screen).toBe(true);
  });

  it("reads the gaps from the sources data (A56), not from card text, once the film states them", () => {
    const j = raw();
    j.gaps = [{ says: "The record holds no photograph of the tower.", searched: "Searched: NARA." }, { searched: "no says" }, "x"];
    const d = parseSources(j);
    expect(d.gaps).toEqual([{ says: "The record holds no photograph of the tower.", searched: "Searched: NARA." }]);
    expect(sourceGaps(d)).toEqual([{ says: "The record holds no photograph of the tower.", searched: "Searched: NARA.", on_screen: false }]);
    expect(silentRecord(d)?.on_screen).toBe(false);
  });

  it("names a reading's source from the reading itself when its lower third is name and role only (A56)", () => {
    const j = raw();
    for (const t of j.lower_thirds) t.lines = t.lines.slice(0, 2);
    j.readings[0].source = "Hansard, 17 March 1947";
    const d = parseSources(j);
    const r = d.readings.find((x) => x.id === j.readings[0].id)!;
    expect(readingSource(r, d.lowerThirds)).toBe("Hansard, 17 March 1947");
  });

  it("labels item links in plain words and says what was done", () => {
    const still = film.shots.find((s) => s.id === "S02")!;
    const clip = film.shots.find((s) => s.id === "S05")!;
    expect(itemLinkLabel(still)).toBe("The photograph at Wikimedia Commons");
    expect(itemLinkLabel(clip)).toBe("The film at the Internet Archive");
    expect(shotTreatment(still)).toMatch(/^Shown whole, then the camera moves/);
    expect(shotTreatment({ ...clip, mark: { class: "RECONSTRUCTED", detail: "" }, alterations: ["colour cast removed"] })).toBe("Changed: colour cast removed.");
  });

  it("states a black floor (A46) and never says the picture is unchanged then", () => {
    const still = film.shots.find((s) => s.id === "S02")!;
    expect(parseLevels({ applied: true, black_in: 35, black_out: 10 })).toEqual({ black_in: 35, black_out: 10 });
    expect(parseLevels({ applied: false, opt_out: true, reason: "the fade is the print" })).toBeNull();
    expect(parseLevels(null)).toBeNull();
    const floored = { ...still, levels: { black_in: 35, black_out: 10 } };
    expect(shotTreatment(floored)).toContain(BLACK_FLOOR_COPY);
    expect(BLACK_FLOOR_COPY).toMatch(/one straight-line level, the same on every colour/);
    // the copy claims nothing the map does not do: it multiplies chroma, so no "hue" or "colour untouched" or "flat"
    expect(BLACK_FLOOR_COPY).not.toMatch(/hue|untouched|flat|unchanged/i);
    expect(shotTreatment(floored)).toMatch(/Nothing else in the picture is changed\.$/);
    expect(shotTreatment(floored)).not.toMatch(/Nothing in the picture is changed/);
    expect(shotTreatment({ ...floored, mark: { class: "RECONSTRUCTED", detail: "" }, alterations: ["upscaled"] })).toMatch(/^Changed: upscaled\. Black level set/);
    expect(shotTreatment({ ...still, levels: null })).toMatch(/Nothing in the picture is changed\.$/);
  });

  it("says how the camera showed a still, true per shot (A41)", () => {
    const still = film.shots.find((s) => s.id === "S02")!;
    const whole = { ...still, fill_ok: false, fill_exception: "a small scan: the fill would pass 3x" };
    expect(stillCamera(whole)).toBe("Shown whole at its own shape, then the camera creeps slowly inside it.");
    const tour = { ...still, fill_ok: true, fill_exception: null };
    expect(stillCamera(tour)).toBe("Filled to the screen, the camera moves across it, never past the picture's own edges.");
    expect(shotTreatment(tour)).not.toMatch(/Shown whole/);
    expect(shotTreatment(whole)).toMatch(/^Shown whole at its own shape/);
    // a sources.json made before A41 has no fill_exception key and keeps what its presets did
    const legacy = { ...still, fill_ok: null };
    delete (legacy as { fill_exception?: string | null }).fill_exception;
    expect(stillCamera({ ...legacy, preset: "PUSH" })).toBe("Shown whole, then the camera moves slowly across it.");
    expect(parseSources({ v: 2, shots: [{ id: "a", kind: "archive_still", start_s: 0, end_s: 1, mark: { class: "ARCHIVE" }, fill_ok: true, fill_exception: null }] }).shots[0])
      .toMatchObject({ fill_ok: true, fill_exception: null });
    expect("fill_exception" in parseSources({ v: 2, shots: [{ id: "a", kind: "archive_still", start_s: 0, end_s: 1, mark: { class: "ARCHIVE" } }] }).shots[0]).toBe(false);
    // A50: the words follow the measured share: a detail only at 40% of the picture or less, else closer on one part
    expect(stillCamera({ ...whole, fill_detail: "detail" as const })).toBe("Shown whole at its own shape; the camera moves in to one detail, then back out to the whole.");
    expect(stillCamera({ ...whole, fill_detail: "field" as const })).toBe("Shown whole at its own shape; the camera moves in closer on one part of it, then back out to the whole.");
    expect(stillCamera({ ...whole, fill_detail: "field" as const })).not.toMatch(/detail/);
    expect(parseSources({ v: 2, shots: [{ id: "a", kind: "archive_still", start_s: 0, end_s: 1, mark: { class: "ARCHIVE" }, fill_ok: false, fill_exception: "a small scan, two words", fill_detail: "field" }] }).shots[0])
      .toMatchObject({ fill_detail: "field" });
    expect("fill_detail" in parseSources({ v: 2, shots: [{ id: "a", kind: "archive_still", start_s: 0, end_s: 1, mark: { class: "ARCHIVE" }, fill_detail: false }] }).shots[0]).toBe(false);
    expect("fill_detail" in parseSources({ v: 2, shots: [{ id: "a", kind: "archive_still", start_s: 0, end_s: 1, mark: { class: "ARCHIVE" }, fill_detail: true }] }).shots[0]).toBe(false);
    expect(stillCamera(whole)).toBe("Shown whole at its own shape, then the camera creeps slowly inside it.");
  });

  it("names the series titles (GRAMMAR A40) in plain words", () => {
    const clip = film.shots.find((s) => s.id === "S05")!;
    const titles = { ...clip, kind: "title_sequence", start_s: 20, end_s: 77, mark: { class: "DRAWN", detail: "from period records" }, alterations: [] };
    expect(shotWhat(titles)).toBe("The series titles, drawn from period records, 57 s");
    expect(shotTreatment(titles)).toMatch(/^A model built from scans of period records/);
  });
});

describe("the balance: whose words, and how long", () => {
  const r = (over: Partial<Reading>): Reading => ({ id: "R", name: "X", side: "india", year: 1947, start_s: 0, dur_s: 10, gender: "m", text: "", credit: "", ...over });

  it("computes seconds and shares by side, and women's share, from the readings", () => {
    const b = computeBalance([
      r({ name: "A", side: "britain", dur_s: 30 }),
      r({ name: "B", side: "india", dur_s: 20, gender: "f" }),
      r({ name: "B", side: "india", dur_s: 10, gender: "f" }),
      r({ name: "C", side: "pakistan", dur_s: 25 }),
      r({ name: "D", side: "sikh", dur_s: 15 }),
    ])!;
    expect(b.from).toBe("film");
    expect(b.total_s).toBe(100);
    expect(b.sides.map((s) => [s.side, s.seconds, s.share])).toEqual([
      ["britain", 30, 0.3],
      ["india", 30, 0.3],
      ["pakistan", 25, 0.25],
      ["bangladesh", 0, 0],
      ["sikh", 15, 0.15],
    ]);
    expect(b.sides.find((s) => s.side === "india")?.speakers).toEqual(["B"]);
    expect(b.women).toEqual({ seconds: 30, share: 0.3, names: [{ name: "B", seconds: 30 }] });
  });

  it("gives no figures when sources.json lacks a length, a gender or a known side (the trailer's file lacks lengths)", () => {
    expect(computeBalance(film.readings)).toBeNull();
    expect(computeBalance([r({ dur_s: null })])).toBeNull();
    expect(computeBalance([r({ gender: null })])).toBeNull();
    expect(computeBalance([r({ side: "elsewhere" })])).toBeNull();
    expect(computeBalance([])).toBeNull();
  });

  it("splits the film's seconds by mark, ARCHIVE film apart from photographs", () => {
    const rows = secondsByMark(film.shots);
    const total = rows.reduce((s, x) => s + x.seconds, 0);
    expect(total).toBeCloseTo(film.duration_s, 6);
    const card = rows.find((x) => x.key === "card")!;
    expect(card.share).toBeCloseTo(0.2251, 3);
    expect(rows.find((x) => x.key === "generated")?.seconds).toBe(0);
  });
});

describe("time", () => {
  it("formats and parses timecodes", () => {
    expect(formatTime(0)).toBe("0:00");
    expect(formatTime(667.9)).toBe("11:07");
    expect(formatTime(3723)).toBe("1:02:03");
    expect(parseTimecode("17:12")).toBe(1032);
    expect(parseTimecode(" 1:02:03 ")).toBe(3723);
    expect(parseTimecode("7:61")).toBeNull();
    expect(parseTimecode("Refugees")).toBeNull();
  });
});

describe("frames: the mark changes on the cut frame, not a frame early or late", () => {
  // S05 starts at frame 648 (27 s at 24 fps); before it, S04 is a CARD.
  const s05 = film.shots.find((s) => s.id === "S05")!;
  const f0 = s05.start_frame;
  const mid = (f: number) => (f + 0.5) / film.fps;

  it("reads the engine's frame numbers", () => {
    expect(f0).toBe(648);
    expect(film.fps).toBe(24);
    expect(frameAt(27, 24)).toBe(648);
    expect(frameAt(27 - 1e-9, 24)).toBe(648);
    expect(frameAt(26.99, 24)).toBe(647);
    expect(frameAt(26.95, 24)).toBe(646);
  });

  it("at f0-1, f0 and f0+1", () => {
    expect(markAt(film.marks, mid(f0 - 1), 24)?.class).toBe("CARD");
    expect(markAt(film.marks, mid(f0), 24)).toMatchObject({ class: "ARCHIVE", detail: "NARA / Internet Archive 1946" });
    expect(markAt(film.marks, mid(f0 + 1), 24)?.class).toBe("ARCHIVE");
    expect(shotAt(film.shots, mid(f0 - 1), 24)?.id).toBe("S04");
    expect(shotAt(film.shots, mid(f0), 24)?.id).toBe("S05");
    expect(shotAt(film.shots, mid(f0 + 1), 24)?.id).toBe("S05");
  });

  it("survives the 4-decimal rounding of start_s (a 186.6387 s boundary is frame 4479)", () => {
    const raw2 = raw();
    raw2.marks = [{ from_s: 0, to_s: 186.6387, class: "CARD", detail: "" }, { from_s: 186.6387, to_s: 297.625, class: "ARCHIVE", detail: "X 1947" }];
    const f = parseSources(raw2);
    expect(f.marks[1].from_frame).toBe(4479);
    expect(markAt(f.marks, mid(4478), 24)?.class).toBe("CARD");
    expect(markAt(f.marks, mid(4479), 24)?.class).toBe("ARCHIVE");
  });

  it("seeks into the middle of a shot's first frame", () => {
    expect(frameAt(seekTime(s05.start_s, 24), 24)).toBe(f0);
    expect(seekTime(27, 24)).toBeCloseTo(27 + 1 / 48);
  });
});

describe("the served film against its sources.json", () => {
  it("agree within one frame and no more", () => {
    expect(durationsAgree(297.625, film)).toBe(true);
    expect(durationsAgree(297.625 + 1 / 24, film)).toBe(true);
    expect(durationsAgree(297.625 + 2 / 24, film)).toBe(false);
    expect(durationsAgree(120, film)).toBe(false);
    expect(durationsAgree(Number.NaN, film)).toBe(false);
  });

  it("measure what was actually played", () => {
    const ranges = (pairs: [number, number][]) => ({ length: pairs.length, start: (i: number) => pairs[i][0], end: (i: number) => pairs[i][1] });
    expect(playedShare(ranges([[0, 90]]), 100)).toBe(0.9);
    expect(playedShare(ranges([[0, 10], [95, 100]]), 100)).toBe(0.15);
    expect(playedShare(ranges([]), 0)).toBe(0);
  });
});

describe("parsing guards", () => {
  it("normalises gender and refuses unknown values", () => {
    const g = (gender: unknown) => {
      const x = raw();
      x.readings[0].gender = gender;
      return parseSources(x).readings[0].gender;
    };
    expect(g("f")).toBe("f");
    expect(g("F")).toBe("f");
    expect(g("female")).toBe("f");
    expect(g("Male")).toBe("m");
    expect(g(undefined)).toBeNull();
    expect(() => g("x")).toThrow(/unknown gender/);
    expect(() => g(3)).toThrow(/unknown gender/);
  });

  it("reads the poster and the web encode only when complete, with a real sha256", () => {
    const sha = "a".repeat(64);
    const x = raw();
    x.poster = { ledger_id: "S-020", title: "Indian Independence Day at the Red Fort", creator: "Unknown author", date: "1947", archive: "Wikimedia Commons", licence: "Public domain", sha256: sha, item_url: "https://commons.wikimedia.org/wiki/File:X.jpg" };
    x.web = { film_sha256: sha, film_duration_s: 297.6 };
    const f = parseSources(x);
    expect(f.poster?.ledger_id).toBe("S-020");
    expect(posterCredit(f.poster!)).toBe("Indian Independence Day at the Red Fort. Unknown author, 1947. Wikimedia Commons, public domain.");
    expect(f.web).toEqual({ film_sha256: sha, film_duration_s: 297.6 });
    expect(film.poster).toBeNull();
    expect(film.web).toBeNull();
    const y = raw();
    y.poster = { ledger_id: "S-020", title: "T", licence: "Public domain", sha256: "nothex" };
    expect(parseSources(y).poster).toBeNull();
  });
});

describe("printed claims are derived from the film", () => {
  it("says no AI-generated images only when none are, and how many otherwise", () => {
    expect(aiSentence(film.shots)).toBe("No AI-generated images in this film.");
    const one = film.shots.map((s, i) => (i === 3 ? { ...s, mark: { class: "AI-GENERATED" as const, detail: "context" } } : s));
    expect(aiSentence(one)).toBe("One shot in this film is AI-generated, each marked AI-GENERATED.");
    const many = film.shots.map((s) => ({ ...s, mark: { class: "AI-GENERATED" as const, detail: "context" } }));
    expect(aiSentence(many)).toBe("24 shots in this film are AI-generated, each marked AI-GENERATED.");
  });

  it("says how voices are read from the readings' credits", () => {
    expect(voiceSentence(film.readings)).toBe("Voices are read by a computer; no recording is imitated.");
    const own = film.readings.map((r, i) => (i === 0 ? { ...r, credit: "original recording" } : r));
    expect(voiceSentence(own)).toBe("Voices are read by a computer, except one original recording; no recording is imitated.");
    expect(voiceSentence([])).toBeNull();
  });

  it("says the narrator is a computer voice only when sources.json credits one", () => {
    const narrator = "Narrated by a computer voice";
    expect(voiceSentence(film.readings, narrator)).toBe("The narrator and the readings are computer voices; no recording is imitated.");
    const own = film.readings.map((r, i) => (i === 0 ? { ...r, credit: "original recording" } : r));
    expect(voiceSentence(own, narrator)).toBe("The narrator and the readings are computer voices, except one original recording; no recording is imitated.");
    expect(voiceSentence([], narrator)).toBe("The narrator is a computer voice.");
    expect(voiceSentence(film.readings, "Narrated by Tara")).toBe("Voices are read by a computer; no recording is imitated.");
  });

  it("declares a trailer only when sources.json records its hash, and says its length from the record", () => {
    expect(film.trailer).toBeNull();
    const h = "a".repeat(64);
    const t = parseSources({ ...raw(), trailer: { file: "trailer.mp4", sha256: h, duration_s: 297.625 } }).trailer;
    expect(t).toEqual({ sha256: h, duration_s: 297.625 });
    expect(trailerNote(t!)).toBe("About five minutes, made under the same rules as the film.");
    expect(trailerNote({ sha256: h, duration_s: null })).toBe("Made under the same rules as the film.");
    expect(trailerNote({ sha256: h, duration_s: 50 })).toBe("About one minute, made under the same rules as the film.");
    expect(parseSources({ ...raw(), trailer: { file: "trailer.mp4" } }).trailer).toBeNull();
    expect(parseSources({ ...raw(), trailer: { sha256: "not-a-hash" } }).trailer).toBeNull();
  });

  it("reads the narration and the narrator's credit, and credits no narrator without narration", () => {
    const narrated = parseSources({ ...raw(), narration: [{ id: "N1", start_s: 2, text: "In the summer of 1947." }], narrator: { credit: "Narrated by a computer voice" } });
    expect(narrated.narrator).toBe("Narrated by a computer voice");
    expect(transcript(narrated).find((e) => e.id === "N1")).toEqual({ id: "N1", start_s: 2, who: "Narrator", text: "In the summer of 1947." });
    expect(parseSources({ ...raw(), narration: [], narrator: { credit: "Narrated by a computer voice" } }).narrator).toBeNull();
    expect(film.narrator).toBeNull();
  });

  it("builds the credit line from the shots' archives and the readings' sources", () => {
    expect(archivesOnScreen(film.shots)).toEqual(["Wikimedia Commons", "US National Archives, via Internet Archive"]);
    // A DRAWN map's maker is not an archive of film or photographs.
    const drawn = film.shots.map((s, i) => (i === 3 ? { ...s, mark: { class: "DRAWN" as const, detail: "from x" }, archive: "void document studio" } : s));
    expect(archivesOnScreen(drawn)).not.toContain("void document studio");
    expect(readingPublications(film.readings, film.lowerThirds)).toContain("Hansard");
    const line = creditsLine(film);
    expect(line).toMatch(/^Film and photographs from Wikimedia Commons and US National Archives, via Internet Archive\. Words from Hansard, Broadcast on All India Radio, Constituent Assembly of Pakistan Debates and 2 other sources\. /);
    expect(line).toMatch(/Sources lists every one\.$/);
  });
});

describe("a dip's black hold carries no mark", () => {
  // S03 enters by a dip of 1 s at frame 432 (18 s): the hold is the middle 10%: frames 431 to 433, as render.py picture_level gives them.
  it("matches the engine's picture level frame by frame", () => {
    const mid = (f: number) => (f + 0.5) / 24;
    const black = [428, 429, 430, 431, 432, 433, 434, 435, 436].filter((f) => onDipBlack(film.shots, mid(f), 24));
    // tl + 0.5 in [0.45, 0.55] s around the cut at 18 s: frames whose time is 17.95 to 18.05 s.
    expect(black).toEqual([431, 432, 433]);
    expect(onDipBlack(film.shots, mid(100), 24)).toBe(false);
    // S02 enters by a dissolve: never black.
    expect(onDipBlack(film.shots, mid(96), 24)).toBe(false);
  });
});

describe("notes on this film (A56)", () => {
  const withNotes = () => {
    const j = raw();
    j.narration = [{ id: "N1", start_s: 1, text: "Words." }];
    j.narrator = { credit: "Narrated by a computer voice", engine: "orpheus", voice: "tara", pitch_shift_st: 0.76 };
    j.readings[0].reader = "kokoro:am_onyx";
    j.readings[1].mark = "ARCHIVE";
    j.readings[1].reader = null;
    j.readings[1].source = "FAA tapes, Boston Center";
    j.unnamed_speakers = [{ speaker: "sp-x", name: "A voice on the NEADS floor", lines: [{ id: "A3", start_s: 75 }] }];
    j.gaps = [{ says: "The record holds no photograph of the tower.", searched: "Searched: NARA, LOC." }];
    j.shortfalls = [
      { what: "women", statement: "Women speak {women_share:pct} of the readings.", filled: "Women speak 4% of the readings." },
      { what: "readings", statement: "Unfilled {readings_share:pct}." },
      { what: "voiceless", statement: "A plain statement." },
    ];
    j.shots[1].notes = ["Line approximate, from the award's description."];
    j.shots[1].source_line = "Data: Natural Earth; GeoNames";
    j.shots[1].licence_note = "contains GeoNames data (CC BY 4.0)";
    return j;
  };

  it("states each disclosure the picture no longer shows, from the sources data", () => {
    const d = parseSources(withNotes());
    const n = filmNotes(d);
    const name0 = d.readings.find((r) => r.reader)!.name;
    expect(n.voices[0]).toBe("Narration: a computer voice, Orpheus 'tara', pitched +0.76 semitones.");
    expect(n.voices[1]).toBe(`Read by computer voices: ${name0} (Kokoro 'am_onyx').`);
    expect(n.voices[2]).toMatch(/^Original recordings: .+, FAA tapes, Boston Center\.$/);
    expect(n.unnamed).toEqual(["A voice on the NEADS floor: A3 (1:15)"]);
    expect(n.gaps).toEqual([{ says: "The record holds no photograph of the tower.", searched: "Searched: NARA, LOC." }]);
    expect(n.statements).toEqual(["Women speak 4% of the readings.", "A plain statement."]);   // an unfilled statement is never printed
    const t = d.shots[1].title ?? d.shots[1].id;
    expect(n.mapNotes).toEqual([`${t}: Line approximate, from the award's description.`, `${t}: Data: Natural Earth; GeoNames`]);
    expect(n.licences.some((l) => l.includes("(contains GeoNames data (CC BY 4.0))"))).toBe(true);
    expect(n.licences.every((l) => /: \d+ shots?$/.test(l))).toBe(true);
  });

  it("states nothing a file does not hold", () => {
    const n = filmNotes(parseSources(raw()));
    expect(n.voices).toEqual([]);
    expect(n.unnamed).toEqual([]);
    expect(n.statements).toEqual([]);
    expect(n.mapNotes).toEqual([]);
  });

  it("prints a shortfall statement only when its numbers are filled", () => {
    expect(statementText({ statement: "{women_share:pct} of it." })).toBeNull();
    expect(statementText({ statement: "{women_share:pct}.", filled: "4%." })).toBe("4%.");
  });
});
