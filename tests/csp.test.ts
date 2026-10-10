// Every built page carries a CSP with default-src 'self' and no other
// origin (fonts are self-hosted), and nothing in the source pages or
// stylesheets loads from another origin (doctrine L-26: a Google Fonts
// @import sent every visit to a third party, against V3).

import { existsSync, readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { CSP, cspViolations, injectCsp } from "../scripts/lib/csp.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const pages = () => readdirSync(path.join(root, "web")).filter((f) => f.endsWith(".html"));

describe("CSP policy", () => {
  it("defaults to self, loads styles and fonts from this origin only, and allows no inline script or eval", () => {
    expect(CSP).toContain("default-src 'self'");
    expect(CSP).toContain("script-src 'self'");
    expect(CSP).toContain("style-src 'self';");
    expect(CSP).toContain("font-src 'self';");
    expect(CSP).not.toMatch(/https?:|unsafe-inline|unsafe-eval|\*/);
  });

  it("injectCsp puts the meta first in <head>, once", () => {
    const html = `<!doctype html><html><head><meta charset="UTF-8" /><title>x</title></head><body></body></html>`;
    const once = injectCsp(html);
    expect(once.indexOf("Content-Security-Policy")).toBeLessThan(once.indexOf('charset="UTF-8"'));
    expect(injectCsp(once)).toBe(once);
  });

  it("cspViolations finds inline scripts, styles and handlers, and passes external module scripts", () => {
    expect(cspViolations(`<script type="module" src="/a.js"></script>`)).toEqual([]);
    expect(cspViolations(`<script>alert(1)</script>`)).toEqual(["inline <script>"]);
    expect(cspViolations(`<div style="color:red"></div>`)).toEqual(["style= attribute"]);
    expect(cspViolations(`<style>a{}</style>`)).toEqual(["inline <style>"]);
    expect(cspViolations(`<img src="x" onerror="y">`)).toEqual(["inline event handler"]);
  });

  it("every source page has no inline script, style or handler", () => {
    for (const page of pages()) expect(cspViolations(readFileSync(path.join(root, "web", page), "utf8")), page).toEqual([]);
  });
});

describe("nothing loads from another origin", () => {
  const EXTERNAL = /^(https?:)?\/\//i;

  function cssFiles(): string[] {
    const out: string[] = [];
    const walk = (dir: string) => {
      for (const e of readdirSync(path.join(root, dir), { withFileTypes: true })) {
        const rel = `${dir}/${e.name}`;
        if (e.isDirectory()) walk(rel);
        else if (e.name.endsWith(".css")) out.push(rel);
      }
    };
    walk("design");
    walk("web/src");
    return out;
  }

  it("no stylesheet imports or url()s another origin, and every font url() exists", () => {
    const files = cssFiles();
    expect(files).toContain("design/fonts.css");
    for (const file of files) {
      const css = readFileSync(path.join(root, file), "utf8");
      for (const m of css.matchAll(/url\(\s*["']?([^"')]+)["']?\s*\)/g)) {
        expect(EXTERNAL.test(m[1]), `${file}: ${m[1]}`).toBe(false);
        if (m[1].endsWith(".woff2")) expect(existsSync(path.resolve(path.dirname(path.join(root, file)), m[1])), `${file}: ${m[1]}`).toBe(true);
      }
      for (const m of css.matchAll(/@import\s+(?:url\()?\s*["']?([^"');]+)/g)) {
        expect(EXTERNAL.test(m[1]), `${file}: @import ${m[1]}`).toBe(false);
      }
    }
  });

  it("no page links a stylesheet, script, image, frame or preconnect on another origin", () => {
    for (const page of pages()) {
      const html = readFileSync(path.join(root, "web", page), "utf8");
      for (const m of html.matchAll(/<(link|script|img|iframe|source|video|audio)\b[^>]*\s(?:href|src)="([^"]+)"/gi)) {
        expect(EXTERNAL.test(m[2]), `web/${page}: <${m[1]} ${m[2]}>`).toBe(false);
      }
    }
  });

  it("no client or Worker code fetches another origin (the LLM add-on's worker/src/llm.ts excepted, server side)", () => {
    for (const dir of ["web/src", "worker/src"]) {
      for (const f of readdirSync(path.join(root, dir)).filter((x) => x.endsWith(".ts") && `${dir}/${x}` !== "worker/src/llm.ts")) {
        const src = readFileSync(path.join(root, dir, f), "utf8");
        expect(src, `${dir}/${f}`).not.toMatch(/fetch\(\s*["'`]https?:\/\//);
      }
    }
  });

  it("tokens.css takes its faces from design/fonts.css, which covers every family and weight the tokens name", () => {
    const tokens = readFileSync(path.join(root, "design/tokens.css"), "utf8");
    expect(tokens).toContain('@import "./fonts.css";');
    const fonts = readFileSync(path.join(root, "design/fonts.css"), "utf8");
    for (const family of ["Inter", "JetBrains Mono", "Fraunces"]) {
      for (const weight of family === "JetBrains Mono" ? [400, 600] : [400, 500, 600]) {
        expect(fonts, `${family} ${weight}`).toMatch(new RegExp(`font-family: "${family}";\\s*font-style: normal;\\s*font-weight: ${weight};`));
      }
    }
  });
});
