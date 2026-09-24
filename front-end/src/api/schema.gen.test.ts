// @vitest-environment node
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { OUTPUT, generate } from "../../scripts/gen-types.mjs";

describe("generated API types", () => {
  it("are current with docs/contracts/api-v1", () => {
    // A schema change without `npm run gen:types` fails here.
    expect(readFileSync(OUTPUT, "utf8")).toBe(generate());
  });
});
