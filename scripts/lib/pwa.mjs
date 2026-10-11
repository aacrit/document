// The installable app: the web app manifest, its icons and the head tags
// that point to them. Written into dist/ by scripts/build.mjs, never by hand
// and never committed (PNG files are build outputs, R-08):
//
// - dist/manifest.webmanifest (served as application/manifest+json through
//   dist/_headers, so the type never depends on an extension table);
// - dist/icons/*.png, rasterised here from design/brand-kit/logomark.svg's
//   own geometry with no dependency (a small PNG encoder on node:zlib);
// - the manifest link, theme-color and apple-touch-icon in every page's
//   <head> (injectAppHead), because a colour literal may live only in
//   design/tokens.css: the build reads it from there.
//
// The service worker is its own module (scripts/lib/sw.mjs).

import { deflateSync } from "node:zlib";

export const MANIFEST_PATH = "/manifest.webmanifest";
export const MANIFEST_TYPE = "application/manifest+json";

// From the site's own copy (the home page's description and the marquee's note).
export const APP_DESCRIPTION = "History told with the public record. Every shot carries a mark that says what it is.";

/** The primaries design/tokens.css defines as literals (--doc-black and the rest), as lowercase hex. */
export function readTokens(css) {
  const out = {};
  for (const m of css.matchAll(/--(doc-[a-z]+):\s*(#[0-9a-fA-F]{6})\s*;/g)) {
    if (!(m[1] in out)) out[m[1]] = m[2].toLowerCase();
  }
  for (const need of ["doc-black", "doc-bone", "doc-safelight"]) {
    if (!out[need]) throw new Error(`pwa: design/tokens.css defines no --${need}`);
  }
  return out;
}

// Every icon the manifest names, and the touch icon. "any" icons are a
// rounded tile; maskable ones are full bleed (the launcher draws the shape).
export const ICONS = [
  { file: "icon-192.png", size: 192, purpose: "any" },
  { file: "icon-512.png", size: 512, purpose: "any" },
  { file: "maskable-192.png", size: 192, purpose: "maskable" },
  { file: "maskable-512.png", size: 512, purpose: "maskable" },
];
export const TOUCH_ICON = { file: "apple-touch-icon-180.png", size: 180, purpose: "touch" };

/**
 * The manifest. display is fullscreen with standalone as the fallback, and
 * there is no orientation: the page turns to landscape only inside the
 * player (web/src/fullscreen.ts), never for the whole app.
 */
export function manifest(tokens) {
  return {
    id: "/",
    name: "void document",
    short_name: "document",
    description: APP_DESCRIPTION,
    lang: "en",
    dir: "ltr",
    start_url: "/",
    scope: "/",
    display: "fullscreen",
    display_override: ["fullscreen", "standalone"],
    background_color: tokens["doc-black"],
    theme_color: tokens["doc-black"],
    prefer_related_applications: false,
    icons: ICONS.map((i) => ({ src: `/icons/${i.file}`, sizes: `${i.size}x${i.size}`, type: "image/png", purpose: i.purpose })),
  };
}

/** The head tags every page carries; placed just before </head>. Idempotent. */
export function injectAppHead(html, tokens) {
  if (html.includes('rel="manifest"')) return html;
  const tags = [
    `<link rel="manifest" href="${MANIFEST_PATH}" />`,
    `<meta name="theme-color" content="${tokens["doc-black"]}" />`,
    `<link rel="apple-touch-icon" href="/icons/${TOUCH_ICON.file}" />`,
  ];
  const at = html.search(/<\/head>/i);
  if (at < 0) throw new Error("pwa: no </head> to inject into");
  return `${html.slice(0, at)}  ${tags.join("\n    ")}\n  ${html.slice(at)}`;
}

// ---- the logomark, from its SVG ----

/** Segments (polylines from <path d>) and circles from logomark.svg: stroked inside the <g>, filled after it. */
export function parseLogomark(svg) {
  const g = /<g\b([^>]*)>([\s\S]*?)<\/g>/.exec(svg);
  if (!g) throw new Error("pwa: logomark.svg has no stroked <g>");
  const width = Number(/stroke-width="([\d.]+)"/.exec(g[1])?.[1]);
  if (!(width > 0)) throw new Error("pwa: logomark.svg's <g> has no stroke-width");
  const viewBox = /viewBox="([\d.\s-]+)"/.exec(svg)?.[1].trim().split(/\s+/).map(Number);
  const polylines = [];
  for (const m of g[2].matchAll(/<path\b[^>]*\sd="([^"]+)"/g)) polylines.push(parsePath(m[1]));
  const rings = [...g[2].matchAll(/<circle\b([^>]*)\/?>/g)].map((m) => circleOf(m[1]));
  const rest = svg.slice(g.index + g[0].length);
  const dots = [...rest.matchAll(/<circle\b([^>]*)\/?>/g)].map((m) => circleOf(m[1]));
  return { viewBox, strokeWidth: width, polylines, rings, dots };
}

function circleOf(attrs) {
  const n = (k) => Number(new RegExp(`\\b${k}="([\\d.-]+)"`).exec(attrs)?.[1]);
  return { cx: n("cx"), cy: n("cy"), r: n("r") };
}

/** M, L, H, V (and lower-case relatives): the only commands the mark uses. */
export function parsePath(d) {
  const pts = [];
  let x = 0;
  let y = 0;
  for (const m of d.matchAll(/([MLHVmlhv])\s*([^MLHVmlhv]*)/g)) {
    const nums = m[2].trim() ? m[2].trim().split(/[\s,]+/).map(Number) : [];
    const c = m[1];
    if (c === "M" || c === "L") [x, y] = nums;
    else if (c === "m" || c === "l") [x, y] = [x + nums[0], y + nums[1]];
    else if (c === "H") x = nums[0];
    else if (c === "h") x += nums[0];
    else if (c === "V") y = nums[0];
    else if (c === "v") y += nums[0];
    pts.push([x, y]);
  }
  return pts;
}

function segDist(px, py, ax, ay, bx, by) {
  const dx = bx - ax;
  const dy = by - ay;
  const len = dx * dx + dy * dy;
  const t = len ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len)) : 0;
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));

/**
 * Units of clear space around the mark: BRAND-KIT 2 asks for the ring's
 * diameter on every side, measured from the strokes' outer edge. The
 * resulting layout also keeps every stroke inside a maskable icon's safe
 * zone (a centred circle 80% of the icon wide).
 */
export function iconLayout(mark) {
  const half = mark.strokeWidth / 2;
  const xs = mark.polylines.flat().map((p) => p[0]);
  const ys = mark.polylines.flat().map((p) => p[1]);
  const minX = Math.min(...xs) - half;
  const maxX = Math.max(...xs) + half;
  const minY = Math.min(...ys) - half;
  const maxY = Math.max(...ys) + half;
  const clear = 2 * mark.rings[0].r;
  const span = Math.max(maxX - minX, maxY - minY) + 2 * clear;
  return { centre: [(minX + maxX) / 2, (minY + maxY) / 2], span };
}

/** RGBA pixels of the icon: bone strokes and the safelight ember on the theatre's black. */
export function rasterIcon(mark, tokens, size, purpose) {
  const [bgR, bgG, bgB] = hex(tokens["doc-black"]);
  const ink = hex(tokens["doc-bone"]);
  const ember = hex(tokens["doc-safelight"]);
  const { centre, span } = iconLayout(mark);
  const unit = span / size; // mark units per pixel
  const half = mark.strokeWidth / 2;
  const radius = purpose === "any" ? size * 0.2 : 0; // the "any" tile's corner radius
  const SS = 4; // 4x4 samples per pixel
  const px = new Uint8Array(size * size * 4);
  const segs = mark.polylines.flatMap((pl) => pl.slice(1).map((p, i) => [pl[i][0], pl[i][1], p[0], p[1]]));

  const inTile = (x, y) => {
    if (!radius) return true;
    const cx = Math.min(Math.max(x, radius), size - radius);
    const cy = Math.min(Math.max(y, radius), size - radius);
    return Math.hypot(x - cx, y - cy) <= radius;
  };

  for (let j = 0; j < size; j++) {
    for (let i = 0; i < size; i++) {
      let tile = 0;
      let stroke = 0;
      let dot = 0;
      for (let sy = 0; sy < SS; sy++) {
        for (let sx = 0; sx < SS; sx++) {
          const x = i + (sx + 0.5) / SS;
          const y = j + (sy + 0.5) / SS;
          if (!inTile(x, y)) continue;
          tile++;
          const ux = centre[0] + (x - size / 2) * unit;
          const uy = centre[1] + (y - size / 2) * unit;
          if (mark.dots.some((c) => Math.hypot(ux - c.cx, uy - c.cy) <= c.r)) {
            dot++;
            continue;
          }
          if (
            segs.some((s) => segDist(ux, uy, s[0], s[1], s[2], s[3]) <= half) ||
            mark.rings.some((c) => Math.abs(Math.hypot(ux - c.cx, uy - c.cy) - c.r) <= half)
          )
            stroke++;
        }
      }
      const n = SS * SS;
      const a = tile / n;
      const o = (j * size + i) * 4;
      if (!tile) continue; // transparent outside the tile
      // Colour over the tile's own samples, alpha from the tile's coverage.
      const s = stroke / tile;
      const d = dot / tile;
      const b = 1 - s - d;
      px[o] = Math.round(bgR * b + ink[0] * s + ember[0] * d);
      px[o + 1] = Math.round(bgG * b + ink[1] * s + ember[1] * d);
      px[o + 2] = Math.round(bgB * b + ink[2] * s + ember[2] * d);
      px[o + 3] = Math.round(255 * a);
    }
  }
  return px;
}

// ---- PNG ----

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

export function crc32(buf) {
  let c = 0xffffffff;
  for (const b of buf) c = CRC_TABLE[(c ^ b) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const td = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(td));
  return Buffer.concat([len, td, crc]);
}

/** An 8-bit RGBA PNG of `size` x `size` pixels. */
export function encodePng(rgba, size) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // RGBA
  const raw = Buffer.alloc(size * (size * 4 + 1));
  for (let y = 0; y < size; y++) {
    raw[y * (size * 4 + 1)] = 0; // filter: none
    Buffer.from(rgba.buffer, rgba.byteOffset + y * size * 4, size * 4).copy(raw, y * (size * 4 + 1) + 1);
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(raw, { level: 9 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

/** Every icon file the build writes: { file, png }. */
export function appIcons(logomarkSvg, tokens) {
  const mark = parseLogomark(logomarkSvg);
  return [...ICONS, TOUCH_ICON].map((i) => ({
    file: i.file,
    png: encodePng(rasterIcon(mark, tokens, i.size, i.purpose === "any" ? "any" : "full"), i.size),
  }));
}
