import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it } from "vitest";
import { createClient } from "../api/client.ts";
import { ApiContext } from "../api/context.tsx";
import type { Health, RunView } from "../api/schema.gen.ts";
import { mockContent, skeleton } from "../test/skeleton.ts";
import { Run } from "./Run.tsx";

const RUN = "33333333-3333-4333-8333-333333333331";

const view: RunView = {
  run: {
    run_id: RUN,
    batch_id: "2026-10-01",
    paper_id: "8 of 18",
    configuration_id: "11111111-1111-4111-8111-111111111111",
    attempt: 1,
    genome_hash: "a".repeat(64),
    seed: 7,
    snapshot_hash: "b".repeat(64),
    budgets: { spend_micros: 18_000 },
    allowed_tools: ["query_cards", "read_part"],
    model_identity: { model: "m" },
    checkpoint_dates: ["2026-10-01"],
    created_at: "2026-10-01T03:29:44.000000Z",
    events: [1, 2].map((ordinal) => ({
      attempt: 1,
      ordinal,
      kind: "model_turn",
      payload_hash: "c".repeat(64),
      recorded_at: "2026-10-01T03:30:00.000000Z",
    })),
  },
  submissions: {
    items: [
      {
        submission_id: "44444444-4444-4444-8444-444444444444",
        sheet_hash: "d".repeat(64),
        question_id: "55555555-5555-4555-8555-555555555555",
        status: "sealed",
        confidence: 0.19,
        horizon: "2027-10-01T00:00:00.000000Z",
        reason: "Adapters matter here.",
        sealed_at: "2026-10-01T03:41:07.000000Z",
        evidence_hashes: ["e".repeat(64)],
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

/** Mock sections with no /api/v1 route; docs/implementation/front-end.md lists them. */
const UNSERVED = [
  "body > :nth-child(5)", // explore links
  "body > :nth-child(n+7):nth-child(-n+9)", // the replay
  "body > :nth-child(n+16):nth-child(-n+17)", // the digest nominations
];

const ok = (data: unknown) => new Response(JSON.stringify({ contract: "1", data }), { status: 200 });

afterEach(cleanup);

describe("run page", () => {
  it("matches the mock page's served sections tag for tag and class for class", async () => {
    const fetch = ((input: RequestInfo | URL) =>
      Promise.resolve(ok(String(input).startsWith("/api/v1/health") ? health : view))) as typeof globalThis.fetch;
    const { container } = render(
      <ApiContext.Provider value={createClient({ origin: "", fetch })}>
        <MemoryRouter initialEntries={[`/runs/${RUN}`]}>
          <Routes>
            <Route path="/runs/:runId" element={<Run />} />
          </Routes>
        </MemoryRouter>
      </ApiContext.Provider>,
    );
    await waitFor(() => expect(container.querySelector("p.lead")?.textContent).not.toBe("loading…"));
    await screen.findByText("Adapters matter here.");
    expect(skeleton(container)).toBe(mockContent("run.html", UNSERVED));
  });
});
