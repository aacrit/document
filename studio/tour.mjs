// GRAMMAR A41 (TOUR): the `tour` helper for the film builders (build_screenplay_*.mjs). The builders share the
// engine checkout (DOC_ENGINE), so they import it from there:
//
//   import { pathToFileURL } from "node:url";
//   const { tour } = await import(pathToFileURL(`${ENGINE}/studio/tour.mjs`).href);
//   shot.camera = tour(ledgerItem, { narration: line.text }) ?? undefined;   // undefined: the default tour
//
// It reads the ledger item's regions of interest, `roi: [{name, x, y, w, h, cue?}]` (picture fractions, x and y the
// top left corner; `cue` is what the narration says when it names the region, the name when absent), and returns a
// path the engine draws: an opening stop at the fill, then one stop on each region the narration names, in the order
// spoken. With no timings each stop is anchored to its cue (`at`), and the engine places it on the word from the
// narration's own timing at plan time (studio/engine/tour.py parse_path and anchor_time, the captions' timing); with measured `words`
// ([{w, t}], t in film seconds) and `start_s` it is timed here (`t`, shot seconds). The engine frames each region from
// its box (`roi`), so the helper needs no image size. Pure: no file is read.

const NON_WORD = /[^\p{L}\p{N}_']+/gu;

export function normWord(w) {
  return String(w).toLowerCase().replace(NON_WORD, "").replace(/^'+|'+$/g, "");
}

function located(r) {
  return r && ["x", "y", "w", "h"].every(k => typeof r[k] === "number" && Number.isFinite(r[k]));
}

function cuesOf(r) {
  const c = r.cue ?? r.name;
  return (Array.isArray(c) ? c : [c]).filter(x => typeof x === "string" && x.trim());
}

// The first token index at which a cue (one word or a phrase) is spoken in a list of normalised tokens, or -1.
function findCue(tokens, cue) {
  const want = cue.split(/\s+/).map(normWord).filter(Boolean);
  if (!want.length) return -1;
  for (let i = 0; i + want.length <= tokens.length; i++) {
    if (want.every((w, j) => tokens[i + j] === w)) return i;
  }
  return -1;
}

/**
 * The path for a still from its ledger item's regions and the narration over it (A41).
 * @param {object} item the ledger item, with `roi`
 * @param {object} [opts]
 * @param {string} [opts.narration] the words heard over the shot, in order (one or more lines joined)
 * @param {{w: string, t: number}[]} [opts.words] measured word times (film seconds); with `start_s`, stops get `t`
 * @param {number} [opts.start_s] the shot's start (film seconds), for `words`
 * @param {string[]} [opts.only] visit only these regions
 * @param {number} [opts.dur_s] the shot's length: with `words`, a region named too late to reach is left out
 * @returns {object[] | "tour" | null} a `camera` path; "tour" when no narration is given (the engine resolves it
 *   from the narration it places); null when the narration names no region (leave `camera` out: the default tour)
 */
export function tour(item, { narration = null, words = null, start_s = 0, only = null, dur_s = null } = {}) {
  const roi = (item?.roi ?? []).filter(r => located(r) && (!only || only.includes(r.name)));
  if (narration == null && !words) return "tour";
  const tokens = words ? words.map(w => normWord(w.w)) : String(narration).split(/\s+/).map(normWord).filter(Boolean);
  const picks = [];
  for (const r of roi) {
    for (const cue of cuesOf(r)) {
      const i = findCue(tokens, cue);
      if (i >= 0) {
        picks.push({ i, cue, r });
        break;
      }
    }
  }
  if (!picks.length) return null;
  picks.sort((a, b) => a.i - b.i);
  const stops = [{ t: 0, z: 1, x: 0.5, y: 0.5 }];
  for (const p of picks) {
    if (words) {
      let t = Math.max(0, Math.round((words[p.i].t - start_s) * 1000) / 1000);
      if (t <= stops[stops.length - 1].t) t = stops[stops.length - 1].t + 0.5;   // never two stops at one moment
      if (dur_s != null && t > dur_s) continue;   // named too late to reach in this shot (as tour.py's tour_stops)
      stops.push({ t, roi: p.r.name });
    } else {
      stops.push({ at: p.cue, roi: p.r.name });
    }
  }
  return stops;
}
