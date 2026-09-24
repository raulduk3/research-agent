// @vitest-environment node
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { OUTPUT, generate } from "../../scripts/gen-types.mjs";

describe("generated API types", () => {
  it("are current with docs/contracts/api-v1", () => {
    // A schema change without `npm run gen:types` fails here.
    expect(readFileSync(OUTPUT, "utf8")).toBe(generate());
  });

  it("inline a $ref into another file's properties", () => {
    const dir = mkdtempSync(join(tmpdir(), "gen-types-"));
    const run = { type: "object", properties: { run_id: { type: "string" } } };
    const paper = {
      type: "object",
      required: ["run_id"],
      properties: { run_id: { $ref: "run.json#/properties/run_id" } },
    };
    writeFileSync(join(dir, "run.json"), JSON.stringify(run));
    writeFileSync(join(dir, "paper.json"), JSON.stringify(paper));
    writeFileSync(join(dir, "endpoints.json"), JSON.stringify({ endpoints: [] }));
    expect(generate(dir)).toContain("export type Paper = {\n  run_id: string;\n};");
  });
});
