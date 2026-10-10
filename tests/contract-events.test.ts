import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parse as parseYaml } from "yaml";
import { describe, expect, it } from "vitest";
import { ALLOWED_EVENTS, SERVER_ONLY_EVENTS } from "../worker/src/config";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const contract = parseYaml(readFileSync(path.join(repoRoot, "contract.yaml"), "utf8"));

describe("contract.yaml <-> worker/src/config.ts", () => {
  it("keeps the allowed-event list in sync", () => {
    expect([...ALLOWED_EVENTS].sort()).toEqual([...contract.events.allowed].sort());
  });

  it("keeps the server-only list in sync, and every server-only name is allowed", () => {
    expect([...SERVER_ONLY_EVENTS].sort()).toEqual([...contract.events.server_only].sort());
    for (const n of SERVER_ONLY_EVENTS) expect(ALLOWED_EVENTS as readonly string[]).toContain(n);
  });

  it("the success event is a client event the Worker accepts (scripts/lint-events.mjs checks its name)", () => {
    expect(ALLOWED_EVENTS as readonly string[]).toContain(contract.success_event);
    expect(SERVER_ONLY_EVENTS as readonly string[]).not.toContain(contract.success_event);
  });
});
