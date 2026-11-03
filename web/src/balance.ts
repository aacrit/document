// "Whose words, and how long" on the Sources page: only figures computed from the film's own readings, or plain
// sentences. A film with no readings says so, says where its witnesses are quoted as far as its shots show it, and
// names its sides. Every value from sources.json is set as DOM text through el() and numerals(), never as markup.
import { PARTITION_BALANCE, filmNotes, pct, secondsByMark, witnessSentence, type Balance, type BalanceConfig, type FilmSources } from "./film-data";
import { el, numerals } from "./site";

export const NO_READINGS = "This film has no readings.";
export const NOT_AVAILABLE = "Balance figures are not available for this cut.";

function bar(share: number, kind: "band" | "floor" | "none", c: BalanceConfig): HTMLElement {
  const fill = el("i");
  fill.style.width = `${Math.min(100, share * 100)}%`;
  if (kind === "none") return el("span", { class: "bar", "aria-hidden": "true" }, fill);
  const marker = el("b", { class: kind });
  if (kind === "band") {
    marker.style.left = `${c.band.min * 100}%`;
    marker.style.width = `${(c.band.max - c.band.min) * 100}%`;
  } else marker.style.left = `${c.women_floor * 100}%`;
  return el("span", { class: "bar", "aria-hidden": "true" }, fill, marker);
}

const small = (text: string) => el("p", { class: "muted small" }, numerals(text));

/** A56: what the record lacks is stated in the sources data, under Notes on this film. */
function gapsNode(d: FilmSources): HTMLElement | null {
  const gaps = filmNotes(d).gaps;
  if (!gaps.length) return null;
  return el("div", { class: "short" }, ...gaps.map((g) => el("p", {}, g.says)), el("p", { class: "muted small" }, el("a", { href: "#notes" }, "Gaps in the record")));
}

function marksNode(d: FilmSources): HTMLElement {
  const marks = secondsByMark(d.shots)
    .filter((m) => m.seconds > 0 || m.key === "generated")
    .map((m) => `${m.label} ${Math.round(m.seconds)} s (${pct(m.share)})`)
    .join(", ");
  return small(`Seconds by mark, whole film: ${marks}.`);
}

/** The panel's body, after its heading. */
export function balanceNodes(d: FilmSources, b: Balance | null): HTMLElement[] {
  const out: HTMLElement[] = [];
  if (d.readings.length === 0) {
    const witnesses = witnessSentence(d.shots);
    out.push(small(witnesses ? `${NO_READINGS} ${witnesses}` : NO_READINGS));
    if (d.balance?.sides.length) out.push(small(`This film's sides: ${d.balance.sides.map((s) => s.label).join("; ")}.`));
    const gaps = gapsNode(d);
    if (gaps) out.push(gaps);
    out.push(marksNode(d));
    return out;
  }
  if (!b) return [el("p", { class: "muted small" }, NOT_AVAILABLE)];
  const c = d.balance ?? PARTITION_BALANCE;
  const s = (n: number) => `${Math.round(n)} s`;
  out.push(
    small(
      `Seconds of readings by side: words read by a computer voice, and any archival recording; the narrator is not counted. All ${s(b.total_s)} are listed under Readings. Each side should hold ${pct(c.band.min).replace(".0", "")} to ${pct(c.band.max).replace(".0", "")}.`,
    ),
  );
  const table = el("div", { class: "btable" });
  for (const side of b.sides) {
    table.append(el("span", {}, side.label), bar(side.share, "band", c), el("span", { class: "num small" }, `${s(side.seconds)} · ${pct(side.share)}`));
  }
  out.push(table);
  if (c.named_speakers_min !== null) {
    const short = b.speakersShort.map((x) => `${x.label} ${x.count}`).join(", ");
    out.push(small(`Each side heard should have at least ${c.named_speakers_min} named speakers.${short ? ` Fewer here: ${short}.` : ""}`));
  }
  if (b.roles) {
    const roles = el("div", { class: "btable" });
    for (const role of b.roles) {
      roles.append(el("span", {}, role.label), bar(role.share, "none", c), el("span", { class: "num small" }, `${s(role.seconds)} · ${pct(role.share)}`));
    }
    out.push(el("p", { class: "muted small" }, "Seconds of readings by role."), roles);
  }
  out.push(
    el(
      "div",
      { class: "btable" },
      el("span", {}, "Women"),
      bar(b.women.share, "floor", c),
      el("span", { class: "num small" }, `${s(b.women.seconds)} · ${pct(b.women.share)}`),
    ),
  );
  const names = b.women.names.map((w) => `${w.name} ${s(w.seconds)}`).join(", ");
  out.push(small(`Floor ${pct(c.women_floor).replace(".0", "")}.${names ? ` ${names}.` : ""}${b.women.share < c.women_floor ? " Short of the floor." : ""}`));
  const gaps = gapsNode(d);
  if (gaps) out.push(gaps);
  out.push(marksNode(d));
  return out;
}
