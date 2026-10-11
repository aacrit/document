import { defineConfig } from "vite";
import registry from "../films.json";

// Run with cwd set to web/ (scripts/build.mjs and scripts/dev.mjs both do
// this), so `root` defaults to this directory and `outDir` below lands at
// the repo root's dist/, matching wrangler.jsonc's assets.directory.
// The inputs are the home page, privacy, and every live film's three pages,
// which scripts/lib/films.mjs writes from films.json before Vite runs (its
// viteInputs() is the same list; tests/films.test.ts holds the two equal).
const live = registry.films.filter((f) => f.status === "live");
const filmInputs = Object.fromEntries(
  live.flatMap((f) => [
    [`film-${f.slug}`, `f/${f.slug}/index.html`],
    [`sources-${f.slug}`, `f/${f.slug}/sources/index.html`],
    [`correct-${f.slug}`, `f/${f.slug}/correct/index.html`],
  ]),
);

export default defineConfig({
  publicDir: "public",
  build: {
    outDir: "../dist",
    emptyOutDir: true,
    // Fonts are always separate files, never inlined as data: URLs: the CSP
    // (scripts/lib/csp.mjs) allows fonts from this origin only.
    assetsInlineLimit: (file) => (file.endsWith(".woff2") ? false : undefined),
    rollupOptions: {
      input: {
        main: "index.html",
        privacy: "privacy.html",
        ...filmInputs,
      },
    },
  },
});
