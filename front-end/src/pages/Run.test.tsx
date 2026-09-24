import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it } from "vitest";
import { createClient } from "../api/client.ts";
import { ApiContext } from "../api/context.tsx";
import type { Health, OwnerRunRecord, RunView } from "../api/schema.gen.ts";
import { mockShape, pageSkeleton } from "../test/skeleton.ts";
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

const record: OwnerRunRecord = {
  run_id: RUN,
  island: "cs",
  ending: "void",
  void_reason: "budget_exhausted",
  ended_at: "2026-10-01T03:41:07.000000Z",
  cost_micros: 19_600,
  settled_at: "2026-10-01T04:00:00.000000Z",
  calls: {
    items: [
      { tool: "query_cards", calls: 12, refused: 0 },
      { tool: "read_part", calls: 10, refused: 2 },
    ],
    next_cursor: null,
  },
  nominations: {
    items: [
      {
        entry_id: "66666666-6666-4666-8666-666666666666",
        digest_hash: "f".repeat(64),
        island: "cs",
        built_at: "2026-10-01T05:00:00.000000Z",
        preference: 3,
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

const ok = (data: unknown) => new Response(JSON.stringify({ contract: "1", data }), { status: 200 });

afterEach(cleanup);

describe("run page", () => {
  it("matches the mock page section for section", async () => {
    const fetch = ((input: RequestInfo | URL) =>
      Promise.resolve(
        ok(String(input).startsWith("/api/v1/health") ? health : String(input).includes("/record") ? record : view),
      )) as typeof globalThis.fetch;
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
    expect(pageSkeleton(container)).toBe(mockShape("run.html"));
    // The owner record: its island, ending, tool calls, cost and the digest entries it was nominated to.
    await screen.findByText("the cs island →");
    const cards = [...container.querySelectorAll(".card")].map((c) => c.textContent);
    expect(cards).toContain("Endedvoid2026-10-01 03:41 UTC: budget_exhausted");
    expect(cards).toContain("Tool calls22 calls2 refused");
    expect(cards).toContain("CostUSD 0.02settled 2026-10-01 04:00 UTC");
    expect(screen.getByText("preference 3")).toBeTruthy();
  });
});
