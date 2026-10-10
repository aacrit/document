// Response headers every Worker response carries. Static assets that never
// reach the Worker get the same set from dist/_headers, written at build
// time by scripts/build.mjs from scripts/lib/csp.mjs's SECURITY_HEADERS, so
// the two lists cannot drift apart.

import { SECURITY_HEADERS } from "../../scripts/lib/csp.mjs";

/**
 * The Worker's own JSON and error responses load nothing, so their policy
 * is the narrowest one: no sources at all, and no framing.
 */
export const API_CSP = "default-src 'none'; frame-ancestors 'none'";

/**
 * Returns `res` with the security headers and `csp` as its
 * Content-Security-Policy. The body is passed through untouched (null for
 * a 304 or a HEAD), with the same status.
 */
export function withSecurityHeaders(res: Response, csp: string): Response {
  const headers = new Headers(res.headers);
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) headers.set(name, value);
  headers.set("Content-Security-Policy", csp);
  return new Response(res.body, { status: res.status, statusText: res.statusText, headers });
}
