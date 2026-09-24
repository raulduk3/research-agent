import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it } from "vitest";
import { createClient } from "../api/client.ts";
import { ApiContext } from "../api/context.tsx";
import type { Health, OwnerPaper, OwnerPaperRun } from "../api/schema.gen.ts";
import { mockContent, skeleton } from "../test/skeleton.ts";
import { Paper } from "./Paper.tsx";

const FAMILY = "00000000-0000-4000-8000-0000000000aa";
const questions = ["00000000-0000-4000-8000-0000000000b1", "00000000-0000-4000-8000-0000000000b2"];

function run(n: number): OwnerPaperRun {
  const id = `00000000-0000-4000-8000-00000000000${n}`;
  return {
    run_id: id,
    batch_id: "2026-10-01",
    paper_id: FAMILY,
    configuration_id: `00000000-0000-4000-8000-00000000010${n}`,
    attempt: 1,
    genome_hash: String(n).repeat(64),
    seed: n,
    snapshot_hash: "c".repeat(64),
    budgets: { spend_micros: 400_000 },
    allowed_tools: ["query_cards"],
    model_identity: {},
    checkpoint_dates: [],
    created_at: "2026-10-01T02:00:00.000000Z",
    events: [],
    ending: {
      state: "submitted",
      reason: null,
      ended_at: "2026-10-01T02:20:00.000000Z",
      submission: {
        submission_id: id,
        accepted_at: "2026-10-01T02:20:00.000000Z",
        forecasts: questions.map((question_id, i) => ({
          question_id,
          probability: 0.2 * (n + i),
          rationale: "Table 3 shows the cut at equal recall.",
          evidence_ids: ["e".repeat(64)],
        })),
        nomination: null,
      },
    },
    outcomes: [],
    trace: `/api/v1/owner/runs/${id}/trace`,
  };
}

const paper: OwnerPaper = {
  paper_id: FAMILY,
  embedding_view: `/api/v1/papers/${FAMILY}/embedding`,
  acquired_on_request: false,
  requests: { items: [], next_cursor: null },
  cards: { items: [], next_cursor: null },
  runs: { items: [run(1), run(2)], next_cursor: null },
};

const health: Health = {
  state: "healthy",
  checked_at: "2026-10-02T02:30:00.000000Z",
  checks: [{ name: "workers", state: "healthy", detail: "2 of 2 busy" }],
};

/** Mock sections with no /api/v1 route; docs/implementation/front-end.md lists them. */
const UNSERVED = [
  "body > :nth-child(n+5):nth-child(-n+15)", // abstract, the rater's call, the parts and PDF, the replay (#208), the summary
  "body > p.lead > a", // the arXiv link
  "body > div.ans form.flag", // rater flags
  "body > :nth-child(24)", // the flag note
  "body > :nth-child(28) td:first-child > *", // evidence text and its PDF page
  "body > :nth-child(n+29):nth-child(-n+31)", // baselines
  "body > details.adv > :not(summary)", // authors, the content assessment
];

/** The page's own record the mock lacks: evidence ids, and requests, cards and embedding under "More". */
const EXTRA = ["details.adv > :not(summary)", "td:first-child > span.id"];

const ok = (data: unknown) => new Response(JSON.stringify({ contract: "1", data }), { status: 200 });

afterEach(cleanup);

describe("paper page", () => {
  it("matches the mock page's served sections tag for tag and class for class", async () => {
    const fetch = ((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith("/api/v1/health")) return Promise.resolve(ok(health));
      if (url.startsWith("/api/v1/owner/papers/")) return Promise.resolve(ok(paper));
      return Promise.resolve(new Response("", { status: 404 }));
    }) as typeof globalThis.fetch;
    const { container } = render(
      <ApiContext.Provider value={createClient({ origin: "", fetch })}>
        <MemoryRouter initialEntries={[`/papers/${FAMILY}`]}>
          <Routes>
            <Route path="/papers/:paperId" element={<Paper />} />
          </Routes>
        </MemoryRouter>
      </ApiContext.Provider>,
    );
    await waitFor(() => expect(container.querySelector("p.lead")?.textContent).not.toBe("loading…"));
    await screen.findByText("No embedding published yet.");
    expect(skeleton(container, { drop: EXTRA })).toBe(mockContent("paper.html", UNSERVED));
  });

  it("names every run's void reason where its chance would be", async () => {
    const voided: OwnerPaperRun = {
      ...run(3),
      ending: { state: "void", reason: "budget", ended_at: "2026-10-01T02:20:00.000000Z", submission: null },
    };
    const fetch = ((input: RequestInfo | URL) =>
      Promise.resolve(
        String(input).startsWith("/api/v1/owner/papers/")
          ? ok({ ...paper, runs: { items: [run(1), voided], next_cursor: null } })
          : ok(health),
      )) as typeof globalThis.fetch;
    render(
      <ApiContext.Provider value={createClient({ origin: "", fetch })}>
        <MemoryRouter initialEntries={[`/papers/${FAMILY}`]}>
          <Routes>
            <Route path="/papers/:paperId" element={<Paper />} />
          </Routes>
        </MemoryRouter>
      </ApiContext.Provider>,
    );
    expect(await screen.findAllByText("void: budget")).toHaveLength(2);
  });
});
