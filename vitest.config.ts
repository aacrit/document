import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["tests/**/*.test.ts"],
    environment: "node",
    // The pages are generated, not committed: write them first (tests/setup-site.ts).
    globalSetup: ["tests/setup-site.ts"],
  },
});
