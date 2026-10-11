// The corrections form's pure parts (tests/correction.test.ts): what the
// Worker stores, and which "where in the film" answers are understood.
import { parseTimecode } from "./film-data";

/** The text the Worker stores: what is wrong, then where and how, each only if given. Never a name or an email field. */
export function correctionText(fields: { what: string; when: string; how: string; shot: string | null }): string {
  const parts = [fields.what.trim()];
  const where = [fields.when.trim(), fields.shot ? `(${fields.shot})` : ""].filter(Boolean).join(" ");
  if (where) parts.push(`Where in the film: ${where}`);
  if (fields.how.trim()) parts.push(`How they know: ${fields.how.trim()}`);
  return parts.join("\n\n");
}

/** Empty is fine; a time must fall inside the film; digits that are not a time are refused; anything else is a title. */
export function whereIsValid(text: string, duration_s: number | null): boolean {
  const t = text.trim();
  if (!t) return true;
  const secs = parseTimecode(t);
  if (secs !== null) return duration_s === null || secs <= duration_s;
  return !/^[\d\s:.]+$/.test(t);
}
