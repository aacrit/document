// The public pages are generated from films.json and web/templates/ (scripts/lib/films.mjs)
// and are not in git: write them before any test reads web/index.html or web/f/.
import path from "node:path";
import { fileURLToPath } from "node:url";
import { writeSite } from "../scripts/lib/films.mjs";

export default function setup(): void {
  writeSite(path.resolve(path.dirname(fileURLToPath(import.meta.url)), ".."));
}
