// The one Content-Security-Policy and security-header set for this product.
// Pages get the policy as a <meta> injected into dist/*.html at build time
// (scripts/build.mjs), not written into web/*.html, because Vite's dev
// server injects inline styles this policy rightly blocks. Static responses
// get the headers from dist/_headers (headersFile below, written by the
// build); Worker responses get them from worker/src/headers.ts. One module,
// so the three can never drift apart.
//
// - Scripts: only this origin's files. No inline script, no eval.
// - Styles: only this origin's stylesheets. No inline <style> and no
//   style="" attributes (scripts may still set element.style).
// - Fonts: only this origin. Faces are self-hosted from @fontsource
//   (design/fonts.css); no font CDN, so no third party learns who opened a
//   page (V3, privacy by construction).
// - Images: this origin and data: (the favicon is a data: SVG).
// - Fetches: this origin only (/e, /feedback, /api).
// - The installable app: its service worker (/sw.js) and its manifest
//   (/manifest.webmanifest) from this origin only, said explicitly rather
//   than left to default-src.

export const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self'",
  "font-src 'self'",
  "img-src 'self' data:",
  "connect-src 'self'",
  "worker-src 'self'",
  "manifest-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

// The same policy as a response header, plus frame-ancestors, which
// browsers ignore in a <meta> policy: only a header can stop a page being
// framed (clickjacking).
export const PAGE_CSP_HEADER = `${CSP}; frame-ancestors 'none'`;

// Headers on every response, static or from the Worker. X-Frame-Options
// covers browsers that predate frame-ancestors; none of these can be set
// from a <meta> tag.
export const SECURITY_HEADERS = {
  "X-Frame-Options": "DENY",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
};

/**
 * The Workers Static Assets `_headers` file for dist/: every static
 * response gets the security headers and the page policy. Written by
 * scripts/build.mjs, never by hand, so it always matches this module.
 */
export function headersFile() {
  const lines = [
    "/*",
    ...Object.entries(SECURITY_HEADERS).map(([k, v]) => `  ${k}: ${v}`),
    `  Content-Security-Policy: ${PAGE_CSP_HEADER}`,
    // The app manifest's type never depends on an extension table (scripts/lib/pwa.mjs).
    "/manifest.webmanifest",
    "  Content-Type: application/manifest+json",
  ];
  return lines.join("\n") + "\n";
}

const META = `<meta http-equiv="Content-Security-Policy" content="${CSP}" />`;

/** Adds the CSP meta as the first element in <head> (it only governs what comes after it). Idempotent. */
export function injectCsp(html) {
  if (html.includes('http-equiv="Content-Security-Policy"')) return html;
  const head = /<head[^>]*>/i.exec(html);
  if (!head) throw new Error("csp: no <head> to inject into");
  const at = head.index + head[0].length;
  return `${html.slice(0, at)}\n    ${META}${html.slice(at)}`;
}

/** Everything in built HTML the policy would block: inline scripts, inline <style>, style attributes, inline handlers. */
export function cspViolations(html) {
  const found = [];
  for (const m of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
    if (!/\bsrc=/i.test(m[1]) || m[2].trim()) found.push("inline <script>");
  }
  if (/<style[\s>]/i.test(html)) found.push("inline <style>");
  if (/<[a-z][^>]*\sstyle=/i.test(html)) found.push("style= attribute");
  if (/<[a-z][^>]*\son[a-z]+=/i.test(html)) found.push("inline event handler");
  return found;
}
