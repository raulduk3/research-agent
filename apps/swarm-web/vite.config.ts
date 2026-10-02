/// <reference types="vitest/config" />
import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv, type Plugin } from "vite";

/**
 * The public skill names the API it describes. Vite copies `public/` as it is, so the built copy
 * has `{{API_ORIGIN}}` replaced with the origin the app was built against.
 */
function skillOrigin(origin: string): Plugin {
  let outDir = "dist";
  return {
    name: "skill-origin",
    apply: "build",
    configResolved(config) {
      outDir = resolve(config.root, config.build.outDir);
    },
    async closeBundle() {
      const file = resolve(outDir, "skill.md");
      const text = await readFile(file, "utf8");
      await writeFile(file, text.replaceAll("{{API_ORIGIN}}", origin.replace(/\/+$/, "")));
    },
  };
}

export default defineConfig(({ mode }) => ({
  plugins: [react(), skillOrigin(loadEnv(mode, process.cwd(), "VITE_").VITE_API_ORIGIN ?? process.env.VITE_API_ORIGIN ?? "")],
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["src/test/setup.ts"],
  },
}));
