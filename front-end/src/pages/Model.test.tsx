import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it } from "vitest";
import { createClient } from "../api/client.ts";
import { ApiContext } from "../api/context.tsx";
import type { Health, ManifestView, OwnerModels } from "../api/schema.gen.ts";
import { mockShape, pageSkeleton } from "../test/skeleton.ts";
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

const models: OwnerModels = {
  models: {
    items: [
      {
        manifest_hash: "c".repeat(64),
        runs: 3,
        first_run_at: "2026-09-20T01:00:00.000000Z",
        last_run_at: "2026-09-22T01:00:00.000000Z",
      },
    ],
    next_cursor: null,
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
const ok = (data: unknown) => new Response(JSON.stringify({ contract: "1", data }), { status: 200 });

afterEach(cleanup);

describe("model page", () => {
  it("matches the mock page section for section", async () => {
    const fetch = ((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith("/api/v1/health")) return Promise.resolve(ok(health));
      if (url.split("?")[0] === "/api/v1/models") return Promise.resolve(ok(models));
      return Promise.resolve(ok(view));
    }) as typeof globalThis.fetch;
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
    await screen.findByText("agent model");
    expect(screen.getByText(/^3 runs, /)).toBeTruthy();
    expect(screen.getByRole("link", { name: "open" }).getAttribute("href")).toBe(`/models/${"c".repeat(64)}`);
    expect(pageSkeleton(container)).toBe(mockShape("models.html"));
  });
});
