import { createRequire } from "node:module";
import path from "node:path";
import { spawnSync } from "node:child_process";

const require = createRequire(import.meta.url);

/**
 * Resolves an installed package's bin script to an absolute path, so callers
 * can run it with `node <script> ...args`. Avoids spawning platform shims
 * (tsc.cmd, vitest.cmd) directly, which fails on Windows under spawnSync /
 * spawn with shell:false.
 */
export function resolveBinPath(pkg, binName) {
  const pkgJsonPath = require.resolve(`${pkg}/package.json`);
  const pkgDir = path.dirname(pkgJsonPath);
  const pkgJson = require(pkgJsonPath);
  const binField = typeof pkgJson.bin === "string" ? pkgJson.bin : pkgJson.bin?.[binName];
  if (!binField) {
    throw new Error(`could not resolve bin "${binName}" for package "${pkg}"`);
  }
  return path.join(pkgDir, binField);
}

export function runBin(pkg, binName, args, options = {}) {
  const binPath = resolveBinPath(pkg, binName);
  return spawnSync(process.execPath, [binPath, ...args], { stdio: "inherit", shell: false, ...options });
}
