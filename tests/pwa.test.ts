// The installable app (T9a): the manifest Chrome on Android installs from,
// the icons it draws on the home screen, and the tags every page carries.

import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { inflateSync } from "node:zlib";
import { describe, expect, it } from "vitest";
import { APP_DESCRIPTION, ICONS, TOUCH_ICON, appIcons, iconLayout, injectAppHead, manifest, parseLogomark, parsePath, readTokens } from "../scripts/lib/pwa.mjs";
import { manifestProblems } from "../scripts/contract.mjs";
import { installControls, runningInstalled, shouldRegister } from "../web/src/install";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (f: string) => readFileSync(path.join(root, f), "utf8");
const tokens = readTokens(read("design/tokens.css"));
const svg = read("design/brand-kit/logomark.svg");

/** Decodes the build's own PNGs (8-bit RGBA, filter 0 on every row). */
function decodePng(buf: Buffer): { size: number; px: Buffer } {
  expect(buf.subarray(0, 8)).toEqual(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]));
  let off = 8;
  let size = 0;
  const idat: Buffer[] = [];
  while (off < buf.length) {
    const len = buf.readUInt32BE(off);
    const type = buf.toString("ascii", off + 4, off + 8);
    const data = buf.subarray(off + 8, off + 8 + len);
    if (type === "IHDR") {
      size = data.readUInt32BE(0);
      expect(data.readUInt32BE(4)).toBe(size);
      expect([data[8], data[9]]).toEqual([8, 6]);
    }
    if (type === "IDAT") idat.push(data);
    off += 12 + len;
  }
  const raw = inflateSync(Buffer.concat(idat));
  const px = Buffer.alloc(size * size * 4);
  for (let y = 0; y < size; y++) {
    expect(raw[y * (size * 4 + 1)]).toBe(0);
    raw.copy(px, y * size * 4, y * (size * 4 + 1) + 1, (y + 1) * (size * 4 + 1));
  }
  return { size, px };
}

describe("the web app manifest", () => {
  const m = manifest(tokens);

  it("names the app, starts and scopes at the root, and installs full screen with standalone as the fallback", () => {
    expect(m.name).toBe("void document");
    expect(m.short_name).toBe("document");
    expect([m.id, m.start_url, m.scope]).toEqual(["/", "/", "/"]);
    expect(m.display).toBe("fullscreen");
    expect(m.display_override).toEqual(["fullscreen", "standalone"]);
  });

  it("locks no orientation: landscape belongs to the player alone", () => {
    expect(m).not.toHaveProperty("orientation");
    expect(read("web/src/fullscreen.ts")).toContain('orientation.lock("landscape")');
  });

  it("takes its colours from design/tokens.css: the theatre's black", () => {
    expect(tokens["doc-black"]).toMatch(/^#[0-9a-f]{6}$/);
    expect(m.background_color).toBe(tokens["doc-black"]);
    expect(m.theme_color).toBe(tokens["doc-black"]);
  });

  it("describes the site in its own words", () => {
    expect(m.description).toBe(APP_DESCRIPTION);
    expect(read("scripts/lib/films.mjs")).toContain("history told with the public record");
    expect(read("web/templates/home.html")).toContain("Every shot carries a mark that says what it is.");
    expect(APP_DESCRIPTION).not.toMatch(/—/);
  });

  it("names 192 and 512 px PNG icons, plain and maskable, and passes the contract's own manifest check", () => {
    expect(m.icons).toEqual(
      ICONS.map((i) => ({ src: `/icons/${i.file}`, sizes: `${i.size}x${i.size}`, type: "image/png", purpose: i.purpose })),
    );
    expect(manifestProblems(m)).toEqual([]);
  });

  it("the contract's manifest check catches what would stop an install", () => {
    expect(manifestProblems(null)).toEqual(["not a JSON object"]);
    const { icons, short_name, ...rest } = m;
    void short_name;
    expect(manifestProblems({ ...rest, icons: icons.filter((i: { purpose: string }) => i.purpose === "any") })).toEqual([
      "no short_name",
      "no 192px maskable PNG icon",
      "no 512px maskable PNG icon",
    ]);
    expect(manifestProblems({ ...m, display: "browser", orientation: "landscape" })).toEqual([
      "display browser cannot install",
      "an orientation lock (landscape belongs to the player only)",
    ]);
  });

  it("the build serves it as application/manifest+json (dist/_headers) and the contract checks it live", () => {
    const contract = read("contract.yaml");
    expect(contract).toContain("type: app_manifest\n    path: /manifest.webmanifest");
    for (const i of ICONS) expect(contract).toContain(`path: /icons/${i.file}\n    header: content-type\n    expect: image/png`);
    expect(contract).toContain("path: /sw.js\n    expect: 200");
    const build = read("scripts/build.mjs");
    expect(build).toContain('writeFileSync(path.join(distDir, "manifest.webmanifest")');
    expect(build).toContain('writeFileSync(path.join(distDir, "sw.js"), swSource(tag))');
  });
});

describe("the app icons, from the logomark", () => {
  const mark = parseLogomark(svg);

  it("reads the mark's geometry: four crop corners, the ring and the ember", () => {
    expect(mark.strokeWidth).toBe(1.6);
    expect(mark.polylines).toEqual([
      [[3.5, 8], [3.5, 4.5], [7, 4.5]],
      [[17, 4.5], [20.5, 4.5], [20.5, 8]],
      [[20.5, 16], [20.5, 19.5], [17, 19.5]],
      [[7, 19.5], [3.5, 19.5], [3.5, 16]],
    ]);
    expect(mark.rings).toEqual([{ cx: 12, cy: 12, r: 4.2 }]);
    expect(mark.dots).toEqual([{ cx: 18.6, cy: 17.6, r: 1.25 }]);
    expect(parsePath("M1 2h3v4l-1 1H0V9")).toEqual([[1, 2], [4, 2], [4, 6], [3, 7], [0, 7], [0, 9]]);
  });

  it("the SVG's colours are the tokens' (bone strokes, the safelight ember)", () => {
    expect(svg.toLowerCase()).toContain(`stroke="${tokens["doc-bone"]}"`);
    expect(svg.toLowerCase()).toContain(`fill="${tokens["doc-safelight"]}"`);
  });

  const icons = appIcons(svg, tokens);
  const decoded = Object.fromEntries(icons.map((i) => [i.file, decodePng(i.png)]));

  it("writes every manifest icon and the touch icon at its size, each well under the size lint", () => {
    expect(icons.map((i) => i.file)).toEqual([...ICONS, TOUCH_ICON].map((i) => i.file));
    for (const i of [...ICONS, TOUCH_ICON]) expect(decoded[i.file].size, i.file).toBe(i.size);
    for (const i of icons) expect(i.png.length, i.file).toBeLessThan(64 * 1024);
  });

  it("keeps the brand kit's clear space: the ring's diameter on every side of the strokes", () => {
    const { span } = iconLayout(mark);
    // Strokes span 3.5 to 20.5 plus half a stroke each side (18.6 units), plus 2 x 8.4 units of clear space.
    expect(span).toBeCloseTo(18.6 + 2 * 8.4, 6);
  });

  it("maskable icons are full bleed, with every stroke inside the safe zone (a centred circle 80% wide)", () => {
    for (const file of ["maskable-192.png", "maskable-512.png"]) {
      const { size, px } = decoded[file];
      const [r, g, b] = [1, 3, 5].map((k) => parseInt(tokens["doc-black"].slice(k, k + 2), 16));
      let marked = 0;
      for (let y = 0; y < size; y++) {
        for (let x = 0; x < size; x++) {
          const o = (y * size + x) * 4;
          expect(px[o + 3]).toBe(255);
          const ground = px[o] === r && px[o + 1] === g && px[o + 2] === b;
          if (ground) continue;
          marked++;
          const d = Math.hypot(x + 0.5 - size / 2, y + 0.5 - size / 2);
          expect(d, `${file} (${x}, ${y})`).toBeLessThanOrEqual(0.4 * size);
        }
      }
      expect(marked).toBeGreaterThan(size); // the mark is drawn
    }
  });

  it("plain icons are a rounded tile: transparent at the corners, opaque at the centre", () => {
    const { size, px } = decoded["icon-512.png"];
    expect(px[3]).toBe(0);
    expect(px[((size / 2) * size + size / 2) * 4 + 3]).toBe(255);
  });
});

describe("every page's head", () => {
  const page = `<!doctype html><html><head><meta charset="UTF-8" /><title>x</title></head><body></body></html>`;

  it("links the manifest, sets the theme colour from the tokens and names the touch icon, once", () => {
    const once = injectAppHead(page, tokens);
    expect(once).toContain('<link rel="manifest" href="/manifest.webmanifest" />');
    expect(once).toContain(`<meta name="theme-color" content="${tokens["doc-black"]}" />`);
    expect(once).toContain(`<link rel="apple-touch-icon" href="/icons/${TOUCH_ICON.file}" />`);
    expect(once.indexOf('rel="manifest"')).toBeLessThan(once.indexOf("</head>"));
    expect(injectAppHead(once, tokens)).toBe(once);
  });

  it("every page fits the display edge to edge (viewport-fit=cover) and carries the footer's install link", () => {
    const pages = ["web/index.html", "web/f/partition-of-india/index.html", "web/f/partition-of-india/sources/index.html", "web/f/partition-of-india/correct/index.html", "web/privacy.html"];
    for (const p of pages) {
      const html = read(p);
      expect(html, p).toContain('content="width=device-width, initial-scale=1.0, viewport-fit=cover"');
      expect(html, p).toContain('<button class="foot-install" type="button" id="install-app" hidden>Install the app</button>');
    }
    for (const p of ["web/index.html", "web/f/partition-of-india/index.html"]) {
      expect(read(p), p).toMatch(/<p class="install-offer" id="install-offer" hidden><button class="btn quiet" type="button">.*<span>Install void document<\/span><\/button>/);
    }
  });

  it("every page's script loads the app module (service worker and install)", () => {
    for (const f of ["home.ts", "film.ts", "sources.ts", "correct.ts", "privacy.ts"]) expect(read(`web/src/${f}`), f).toContain('import "./app";');
    expect(read("web/privacy.html")).toContain('<script type="module" src="./src/privacy.ts"></script>');
  });
});

describe("the install offer", () => {
  it("is never shown before the browser offers the install, and the watched offer only after a watch", () => {
    expect(installControls({ available: false, watched: true, installed: false })).toEqual({ footer: false, offer: false });
    expect(installControls({ available: true, watched: false, installed: false })).toEqual({ footer: true, offer: false });
    expect(installControls({ available: true, watched: true, installed: false })).toEqual({ footer: true, offer: true });
    expect(installControls({ available: true, watched: true, installed: true })).toEqual({ footer: false, offer: false });
  });

  it("knows the installed app by its display mode", () => {
    expect(runningInstalled((q) => q === "(display-mode: fullscreen)")).toBe(true);
    expect(runningInstalled((q) => q === "(display-mode: standalone)")).toBe(true);
    expect(runningInstalled(() => false)).toBe(false);
  });

  it("registers the service worker only on a built page in a secure context", () => {
    const sw = { serviceWorker: {} };
    expect(shouldRegister({ isSecureContext: true, navigator: sw }, "cd99bc4")).toBe(true);
    expect(shouldRegister({ isSecureContext: false, navigator: sw }, "cd99bc4")).toBe(false);
    expect(shouldRegister({ isSecureContext: true, navigator: {} }, "cd99bc4")).toBe(false);
    expect(shouldRegister({ isSecureContext: true, navigator: sw }, "__BUILD__")).toBe(false);
    expect(shouldRegister({ isSecureContext: true, navigator: sw }, null)).toBe(false);
  });

  it("holds back Chrome's own banner, counts nothing and stores nothing", () => {
    const app = read("web/src/app.ts");
    expect(app).toContain("event.preventDefault();");
    expect(app).not.toMatch(/sendEvent|reportCoreSuccess|fetch\(|localStorage|sessionStorage|indexedDB|document\.cookie/);
    expect(app).toMatch(/film\.addEventListener\("play", watched/);
    expect(app).toMatch(/film\.addEventListener\("ended", watched/);
  });
});
