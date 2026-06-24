// vitest.config.ts — minimal node-environment config for the DATA-07 unit tests.
//
// The coords.ts join reads server-assets/coords/ via node:fs, so tests run in the
// node environment (not jsdom). The `@/*` alias mirrors tsconfig.json so imports
// like `@/lib/coords` resolve to the web/ root, matching the app's resolution.

import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import { defineConfig } from "vitest/config";

const root = dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  resolve: {
    alias: {
      "@": resolve(root, "."),
    },
  },
  test: {
    environment: "node",
    include: ["lib/**/*.test.ts", "components/**/*.test.tsx"],
  },
});
