// Types for csp.mjs, so the Worker (worker/src/headers.ts, index.ts) and the
// tests can import the one policy without a type escape hatch.
export declare const CSP: string;
export declare const PAGE_CSP_HEADER: string;
export declare const SECURITY_HEADERS: Record<string, string>;
export declare function headersFile(): string;
export declare function injectCsp(html: string): string;
export declare function cspViolations(html: string): string[];
