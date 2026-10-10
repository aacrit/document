// The site's reading of the engine's sources.json (web/src/film-data.ts),
// against a trimmed copy of the Partition trailer's own file.
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  PLAN_BALANCE,
  balanceFor,
  chapterAt,
  chapters,
  computeBalance,
  formatTime,
  itemLinkLabel,
  lowerThirdAt,
  markAt,
  markWords,
  parseSources,
  parseTimecode,
  pct,
  readingFlag,
  readingSource,
  safeUrl,
  secondsByMark,
  shotAt,
  shotTreatment,
  silentRecord,
  stepChapter,
  transcript,
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
    expect(film.marks[0]).toEqual({ from_s: 0, to_s: 18, class: "ARCHIVE", detail: "Wikimedia Commons 1947" });
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
    expect(markAt(f.marks, 20)?.class).toBe("CARD");
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
    expect(markAt(film.marks, 0)).toMatchObject({ class: "ARCHIVE", detail: "Wikimedia Commons 1947" });
    expect(markAt(film.marks, 17.999)?.class).toBe("ARCHIVE");
    expect(markAt(film.marks, 18)?.class).toBe("CARD");
    expect(markAt(film.marks, 27)).toMatchObject({ class: "ARCHIVE", detail: "NARA / Internet Archive 1946" });
    expect(markAt(film.marks, 52.49)?.detail).toBe("NARA / Internet Archive 1946");
    expect(markAt(film.marks, 52.5)?.class).toBe("CARD");
    expect(markAt(film.marks, 80)?.detail).toBe("Wikimedia Commons 1950");
  });

  it("holds the first mark before 0 and the last past the end", () => {
    expect(markAt(film.marks, -3)?.from_s).toBe(0);
    expect(markAt(film.marks, 400)?.class).toBe("CARD");
    expect(markAt([], 10)).toBeNull();
  });

  it("agrees with the shot on screen at every second of the film", () => {
    for (let t = 0; t < film.duration_s; t += 0.5) {
      expect(markAt(film.marks, t)?.class, `t=${t}`).toBe(shotAt(film.shots, t)?.mark.class);
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

  it("finds the last record-is-silent card", () => {
    expect(silentRecord(film.shots)?.says).toBe("The record holds no first-person account under an open licence by a Bengali or Bangladeshi witness.");
    expect(silentRecord(film.shots)?.searched).toMatch(/^Searched: FRUS/);
  });

  it("labels item links in plain words and says what was done", () => {
    const still = film.shots.find((s) => s.id === "S02")!;
    const clip = film.shots.find((s) => s.id === "S05")!;
    expect(itemLinkLabel(still)).toBe("The photograph at Wikimedia Commons");
    expect(itemLinkLabel(clip)).toBe("The film at the Internet Archive");
    expect(shotTreatment(still)).toMatch(/^Shown whole, then the camera moves/);
    expect(shotTreatment({ ...clip, mark: { class: "RECONSTRUCTED", detail: "" }, alterations: ["colour cast removed"] })).toBe("Changed: colour cast removed.");
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

  it("falls back to the treatment's figures when sources.json lacks durations or genders (the trailer's file does)", () => {
    expect(computeBalance(film.readings)).toBeNull();
    const b = balanceFor("partition-of-india", film.readings)!;
    expect(b).toBe(PLAN_BALANCE["partition-of-india"]);
    expect(b.from).toBe("plan");
    // TREATMENT.md section 5: cleared testimony 396 s; Britain 34.3%, Pakistan 16.7%, Sikh 14.6%, women 11.6%.
    expect(b.sides.reduce((s, x) => s + x.seconds, 0)).toBe(b.total_s);
    expect(b.sides.map((s) => pct(s.share))).toEqual(["34.3%", "34.3%", "16.7%", "14.6%", "0.0%"]);
    expect(pct(b.women.share)).toBe("11.6%");
    expect(b.women.names.reduce((s, w) => s + w.seconds, 0)).toBe(b.women.seconds);
    expect(balanceFor("another-film", film.readings)).toBeNull();
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
