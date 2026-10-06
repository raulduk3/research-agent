import { execFileSync } from "node:child_process";
import { fileURLToPath, URL as NodeURL } from "node:url";
import { describe, expect, test } from "vitest";
import { z } from "zod";
import { agentEditRequestSchema, chatRequestSchema, genomeRequestSchema, likeRequestSchema, loginRequestSchema, selectionRequestSchema, activitySchema, briefSchema, chatAnswerSchema, errorSchema, islandViewSchema, likeAnswerSchema, loginAnswerSchema, paperViewSchema, publicPaperSchema, revisionAnswerSchema, runViewSchema, selectionAnswerSchema, settingsRequestSchema, stormSchema } from "./contracts.ts";

const schemas = {
  storm: stormSchema, brief: briefSchema, activity: activitySchema, login: loginAnswerSchema,
  island: islandViewSchema, paper: paperViewSchema, run: runViewSchema, chat: chatAnswerSchema,
  settings: revisionAnswerSchema, genome: revisionAnswerSchema, agentEdit: revisionAnswerSchema,
  selection: selectionAnswerSchema, deselection: selectionAnswerSchema, like: likeAnswerSchema, error: errorSchema, publicPaper: publicPaperSchema,
};
const root = process.env.RESEARCH_AGENT_CONTRACT_ROOT ?? fileURLToPath(new NodeURL("../../../..", import.meta.url));
const samples = z.record(z.string(), z.unknown()).parse(JSON.parse(execFileSync("uv", ["run", "--locked", "python", "-m", "tests.beta.browser_contract_samples"], { cwd: root, encoding: "utf8", timeout: 30000 })));

describe("the real Python API answers satisfy browser contracts", () => {
  for (const [name, schema] of Object.entries(schemas)) {
    test(name, () => {
      const result = schema.safeParse(samples[name]);
      expect(result.success, result.success ? "" : JSON.stringify(result.error.issues)).toBe(true);
    });
  }
});

const requestSchemas = {
  login: loginRequestSchema, chat: chatRequestSchema, settings: settingsRequestSchema,
  genome: genomeRequestSchema, selection: selectionRequestSchema, deselection: selectionRequestSchema,
  like: likeRequestSchema, agentEdit: agentEditRequestSchema,
};
const requests = z.record(z.string(), z.unknown()).parse(samples.requests);

describe("browser write contracts describe requests accepted by the real Python API", () => {
  for (const [name, schema] of Object.entries(requestSchemas)) {
    test(name, () => {
      const result = schema.safeParse(requests[name]);
      expect(result.success, result.success ? "" : JSON.stringify(result.error.issues)).toBe(true);
    });
  }
});

test("the shared contract rejects a changed money field from a real API response", () => {
  const sample = z.record(z.string(), z.unknown()).parse(samples.storm);
  expect(stormSchema.safeParse({ ...sample, cost_micros: "100" }).success).toBe(false);
  expect(stormSchema.safeParse({ ...sample, cost_micros: -1 }).success).toBe(false);
  expect(stormSchema.safeParse({ ...sample, cost_micros: 0.5 }).success).toBe(false);
});

test("an island settings edit must name a switch", () => {
  expect(settingsRequestSchema.safeParse({}).success).toBe(false);
  expect(settingsRequestSchema.parse({ evolution_enabled: false })).toEqual({ evolution_enabled: false });
});
