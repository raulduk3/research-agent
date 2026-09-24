import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it } from "vitest";
import { createClient } from "../api/client.ts";
import { ApiContext } from "../api/context.tsx";
import type { Health, ManifestView } from "../api/schema.gen.ts";
import { mockContent, skeleton } from "../test/skeleton.ts";
import { Model } from "./Model.tsx";

const view: ManifestView = {
  manifest: {
    manifest_hash: "a".repeat(64),
    artifact_hash: "b".repeat(64),
    manifest_kind: "bundle",
    media_type: "application/json",
    byte_length: 812,
    created_at: "2026-09-22T00:00:00.000000Z",
    fields: { embedding_revision: "d556a88e", dimensions: 768 },
  },
};

const health: Health = {
  state: "healthy",
  checked_at: "2026-10-02T02:30:00.000000Z",
  checks: [{ name: "workers", state: "healthy", detail: "2 of 2 busy" }],
};

/**
 * Mock sections with no /api/v1 route; docs/implementation/front-end.md lists them. One
 * manifest takes the place of the embedding section (a kv table of fields).
 */
const UNSERVED = [
  "body > :nth-child(n+4):nth-child(-n+9)", // the model list and the prediction heads
  "body > :nth-child(n+12):nth-child(-n+21)", // corpus, agent model, summarizer, spending, Jev
];

const ok = (data: unknown) => new Response(JSON.stringify({ contract: "1", data }), { status: 200 });

afterEach(cleanup);

describe("model page", () => {
  it("matches the mock page's served sections tag for tag and class for class", async () => {
    const fetch = ((input: RequestInfo | URL) =>
      Promise.resolve(ok(String(input).startsWith("/api/v1/health") ? health : view))) as typeof globalThis.fetch;
    const { container } = render(
      <ApiContext.Provider value={createClient({ origin: "", fetch })}>
        <MemoryRouter initialEntries={[`/models/${"a".repeat(64)}`]}>
          <Routes>
            <Route path="/models/:manifestHash" element={<Model />} />
          </Routes>
        </MemoryRouter>
      </ApiContext.Provider>,
    );
    await waitFor(() => expect(container.querySelector("p.lead")?.textContent).not.toBe("loading…"));
    await screen.findByText("embedding revision");
    expect(skeleton(container)).toBe(mockContent("models.html", UNSERVED));
  });
});
