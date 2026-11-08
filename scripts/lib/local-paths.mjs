// A Windows drive path is studio language: it names the machine a film was
// made on, never anything a viewer can open. Partition's sources.json printed
// "Lok Sabha Secretariat (eparlib), PDF on D:" as the archive and credit of
// four shots (2026-11). One pattern, used by the site-pages sweep (pages and
// client scripts) and by release-film's refusal to upload a packet sources.json.
//
// Two forms, both anchored so the letter is not the end of a word or number
// (the lookbehind keeps "https://" and "12:30" out: "s" and "2" follow a letter or digit):
//   1. a path: a letter, a colon and a slash or backslash ("D:/document-media/x.pdf", "C:\Users\x").
//   2. the bare drive: an upper-case letter and a colon that close the text or a clause ("PDF on D:",
//      "D:)", "D:,", "D:."), never one followed by more words. Music cue text writes key names that way
//      ("phrase c in C: C5 D5 A5", "the ground moves to E: E minor", "C# to D: the first D major"), so a
//      letter and colon followed by a space and more text is a key, not a drive.
// What it never flags: ids like "A:5.4" (a digit follows), times "12:30", words "Note: x", URLs.

/** The shared pattern (no g flag, so .test() keeps no state). */
export const LOCAL_PATH = /(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|[A-Z]:(?=\s*$|[,;)"'\]]|\.(?!\d)))/;

/** Whether a string names a local drive. */
export const hasLocalPath = (s) => typeof s === "string" && LOCAL_PATH.test(s);

/**
 * Every string value in a parsed JSON document (a film's sources.json) that names a local drive, as
 * { path, value } with the path written as it is read: ".shots[96].archive". Object keys are walked as well, since a
 * key is printed text too. Pure: no I/O.
 */
export function localPathFindings(doc) {
  const out = [];
  const walk = (v, at) => {
    if (typeof v === "string") {
      if (hasLocalPath(v)) out.push({ path: at || ".", value: v });
    } else if (Array.isArray(v)) {
      v.forEach((x, i) => walk(x, `${at}[${i}]`));
    } else if (v && typeof v === "object") {
      for (const [k, x] of Object.entries(v)) {
        const key = /^[A-Za-z_$][\w$]*$/.test(k) ? `.${k}` : `[${JSON.stringify(k)}]`;
        if (hasLocalPath(k)) out.push({ path: `${at}${key} (key)`, value: k });
        walk(x, `${at}${key}`);
      }
    }
  };
  walk(doc, "");
  return out;
}
