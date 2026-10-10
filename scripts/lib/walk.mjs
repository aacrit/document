import { readdirSync, statSync } from "node:fs";
import path from "node:path";

/**
 * Recursively yields file paths under `dir`, skipping any directory whose
 * basename is in `skipDirNames`.
 */
export function* walk(dir, skipDirNames = new Set()) {
  for (const entry of readdirSync(dir)) {
    if (skipDirNames.has(entry)) continue;
    const full = path.join(dir, entry);
    const stats = statSync(full);
    if (stats.isDirectory()) {
      yield* walk(full, skipDirNames);
    } else {
      yield full;
    }
  }
}
