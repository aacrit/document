// Shared secret-shape patterns for .githooks/pre-commit, .githooks/pre-push,
// and `npm run scan-history`. Kept in one place so all three stay in sync.
// These are *shapes*, not real secrets - nothing here is a working key.

export const CREDENTIAL_PATH_PATTERNS = [
  /(^|\/)\.env(\..*)?$/,
  /(^|\/)\.dev\.vars$/,
  /(^|\/)secrets\.json$/,
  /\.pem$/,
  /\.key$/,
  /\.keystore$/,
  /\.jks$/,
];

export const ALLOWED_CREDENTIAL_PATH_EXCEPTIONS = [/(^|\/)\.env\.example$/];

export function isBlockedCredentialPath(filePath) {
  const normalized = filePath.replace(/\\/g, "/");
  if (ALLOWED_CREDENTIAL_PATH_EXCEPTIONS.some((p) => p.test(normalized))) return false;
  return CREDENTIAL_PATH_PATTERNS.some((p) => p.test(normalized));
}

const ANTHROPIC_KEY = /sk-ant-[A-Za-z0-9_-]{20,}/;
const GOOGLE_KEY = /AIza[0-9A-Za-z_-]{35}/;
const GITHUB_TOKEN = /(ghp_|github_pat_)[A-Za-z0-9_]{20,}/;
const AWS_ACCESS_KEY_ID = /AKIA[0-9A-Z]{16}/;
const PRIVATE_KEY_BLOCK = /-----BEGIN [A-Z ]*PRIVATE KEY-----/;
const JWT_LIKE = /eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/;
const DB_URL_WITH_PASSWORD = /(postgres|postgresql|mysql|mongodb(\+srv)?):\/\/[^\s:'"]+:[^\s@'"]+@/;

export const SECRET_LINE_PATTERNS = [
  { name: "anthropic-key", pattern: ANTHROPIC_KEY },
  { name: "google-api-key", pattern: GOOGLE_KEY },
  { name: "github-token", pattern: GITHUB_TOKEN },
  { name: "aws-access-key-id", pattern: AWS_ACCESS_KEY_ID },
  { name: "private-key-block", pattern: PRIVATE_KEY_BLOCK },
  { name: "jwt", pattern: JWT_LIKE },
  { name: "db-url-with-password", pattern: DB_URL_WITH_PASSWORD },
];

export function findSecretMatches(line) {
  const hits = [];
  for (const { name, pattern } of SECRET_LINE_PATTERNS) {
    if (pattern.test(line)) hits.push(name);
  }
  return hits;
}

/**
 * Scans `git log -p`-shaped text (a series of commits and unified diffs) for
 * added lines that look like secrets. Used by scan-history.mjs (full
 * history) and the pre-push hook (just the commits being pushed).
 */
export function scanPatchText(text) {
  const violations = [];
  let commit = "(unknown commit)";
  let file = "(unknown file)";

  for (const line of text.split("\n")) {
    if (line.startsWith("commit ")) {
      commit = line.slice("commit ".length).trim().slice(0, 12);
      continue;
    }
    if (line.startsWith("+++ ")) {
      file = line.slice(4).replace(/^b\//, "");
      continue;
    }
    if (!line.startsWith("+") || line.startsWith("+++")) continue;

    const hits = findSecretMatches(line.slice(1));
    if (hits.length > 0) {
      violations.push(`${commit} ${file}: looks like a secret (${hits.join(", ")})`);
    }
  }

  return violations;
}
