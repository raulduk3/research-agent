import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it } from "vitest";
import { createClient } from "../api/client.ts";
import { ApiContext } from "../api/context.tsx";
import type { Health, OwnerPaper, OwnerPaperDocuments, OwnerPaperRun } from "../api/schema.gen.ts";
import { mockShape, pageSkeleton } from "../test/skeleton.ts";
import { Paper, PaperRecord } from "./Paper.tsx";

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

const card = (n: number, assessment: string | null) => ({
  snapshot_hash: String(n).repeat(64),
  paper_version_id: FAMILY,
  card_hash: "d".repeat(64),
  assessment_section_hash: assessment,
  card: {},
});

/** Two cards pin the same section and one pins none: the page names the section once. */
const assessedPaper: OwnerPaper = {
  ...paper,
  cards: { items: [card(3, "a".repeat(64)), card(4, "a".repeat(64)), card(5, null)], next_cursor: null },
};

/** Oldest first: the page shows the newest. */
const documents: OwnerPaperDocuments = {
  paper_id: FAMILY,
  documents: {
    items: [1, 2].map((n) => ({
      artifact_hash: String(n).repeat(64),
      byte_length: 204_800,
      created_at: `2026-09-2${n}T00:00:00.000000Z`,
      path: `/api/v1/owner/documents/${String(n).repeat(64)}`,
    })),
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

describe("paper page", () => {
  it("matches the mock page section for section", async () => {
    const fetch = ((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith("/api/v1/health")) return Promise.resolve(ok(health));
      if (url.startsWith(`/api/v1/owner/papers/${FAMILY}/documents`)) return Promise.resolve(ok(documents));
      if (url.startsWith("/api/v1/owner/papers/")) return Promise.resolve(ok(assessedPaper));
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
    expect(pageSkeleton(container)).toBe(mockShape("paper-P1.html"));
    const newest = `/api/v1/owner/documents/${"2".repeat(64)}`;
    expect(container.querySelector(".rp-cap a")?.getAttribute("href")).toBe(newest);
    expect(container.querySelector(".rp-pdf iframe")?.getAttribute("src")).toBe(newest);
    expect(container.querySelector("details.adv")?.textContent).toContain(
      `section ${"a".repeat(12)}, pinned by the cards' snapshots`,
    );
    const axes = [...container.querySelectorAll("#life .stage div.axis1")];
    expect(axes.map((a) => [...a.querySelectorAll<HTMLElement>(".dot")].map((d) => d.style.left))).toEqual([
      ["20%", "40%"],
      ["40%", "60%"],
    ]);
  });

  it("keeps the requests, cards and embedding on the paper's record page", async () => {
    const fetch = ((input: RequestInfo | URL) =>
      Promise.resolve(
        String(input).startsWith("/api/v1/owner/papers/") ? ok(paper) : new Response("", { status: 404 }),
      )) as typeof globalThis.fetch;
    render(
      <ApiContext.Provider value={createClient({ origin: "", fetch })}>
        <MemoryRouter initialEntries={[`/papers/${FAMILY}/record`]}>
          <Routes>
            <Route path="/papers/:paperId/record" element={<PaperRecord />} />
          </Routes>
        </MemoryRouter>
      </ApiContext.Provider>,
    );
    expect(await screen.findByText("No embedding published yet.")).toBeTruthy();
    expect(screen.getByText("Requests")).toBeTruthy();
  });

  it("names every run's void reason where its chance would be", async () => {
    const voided: OwnerPaperRun = {
      ...run(3),
      ending: { state: "void", reason: "budget", ended_at: "2026-10-01T02:20:00.000000Z", submission: null },
    };
    const fetch = ((input: RequestInfo | URL) =>
      Promise.resolve(
        String(input).includes("/documents")
          ? new Response("", { status: 404 })
          : String(input).startsWith("/api/v1/owner/papers/")
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
