import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it } from "vitest";
import { createClient } from "../api/client.ts";
import { ApiContext } from "../api/context.tsx";
import type { Health, OwnerReportSelection, ReportView, ReportViewComparison } from "../api/schema.gen.ts";
import { mockShape, pageSkeleton } from "../test/skeleton.ts";
import { Report } from "./Report.tsx";

const comparison = (comparator: ReportViewComparison["comparator"]): ReportViewComparison => ({
  comparator,
  population_likes: 11,
  population_decided: 18,
  comparator_likes: 2,
  comparator_decided: 7,
  population_rate: 0.61,
  comparator_rate: 0.29,
  weeks: 1,
  interval: {
    method: "bootstrap",
    method_version: 1,
    resamples: 10_000,
    seed: 7,
    lower_tail: 0.025,
    upper_tail: 0.975,
    support_count: 25,
    support_hash: "a".repeat(64),
    estimate: 0.32,
    low: -0.04,
    high: 0.58,
    disposition: "estimated",
  },
  verdict: {
    verdict: "inconclusive",
    low: -0.04,
    high: 0.58,
    favorable_direction: "greater",
    minimum_effect: null,
    minimum_effect_pass: null,
  },
});

const view: ReportView = {
  notice: "Automated output. Not a scientific claim authored by any person.",
  comparator_names: { random_control: "random controls", service: "service picks" },
  report: {
    island: "cs",
    iso_week: "2026-W40",
    rows: ["d", "1"].map((c, n) => ({
      genome_hash: c.repeat(64),
      founder: n === 0,
      skills: ["reach", "late_activity"].map((target_id) => ({
        target_id,
        skill: null,
        support_count: 0,
        disposition: "not_yet_resolved",
      })),
      preference_credit: 3.1,
      credited_entries: 9,
    })),
    preference_reason: null,
    comparisons: [comparison("random_control"), comparison("service")],
    migrations: [],
  },
};

const health: Health = {
  state: "healthy",
  checked_at: "2026-10-02T02:30:00.000000Z",
  checks: [{ name: "workers", state: "healthy", detail: "2 of 2 busy" }],
};

const selection: OwnerReportSelection = {
  island: "cs",
  iso_week: "2026-W40",
  archived: {
    items: [
      {
        configuration_hash: "e".repeat(64),
        lineage_id: "C.2",
        cycle_id: "2026-W40",
        skill: 0.412,
        resolved_claim_count: 18,
        archived_at: "2026-10-04T03:00:00.000000Z",
      },
    ],
    next_cursor: null,
  },
  admitted: {
    items: [
      {
        configuration_hash: "f".repeat(64),
        lineage_id: "C.5",
        founder: false,
        admission: "accepted",
        admitted_at: "2026-10-04T03:05:00.000000Z",
      },
    ],
    next_cursor: null,
  },
};

const ok = (data: unknown) => new Response(JSON.stringify({ contract: "1", data }), { status: 200 });

afterEach(cleanup);

describe("report page", () => {
  it("matches the mock page section for section", async () => {
    const fetch = ((input: RequestInfo | URL) =>
      Promise.resolve(
        ok(
          String(input).startsWith("/api/v1/health")
            ? health
            : String(input).endsWith("/selection")
              ? selection
              : view,
        ),
      )) as typeof globalThis.fetch;
    const { container } = render(
      <ApiContext.Provider value={createClient({ origin: "", fetch })}>
        <MemoryRouter initialEntries={["/reports/cs/2026-W40"]}>
          <Routes>
            <Route path="/reports/:island/:isoWeek" element={<Report />} />
          </Routes>
        </MemoryRouter>
      </ApiContext.Provider>,
    );
    await waitFor(() => expect(container.querySelector("p.lead")?.textContent).not.toBe("loading…"));
    await screen.findByText("Each agent this week so far");
    expect(pageSkeleton(container)).toBe(mockShape("report.html"));
    await waitFor(() =>
      expect(screen.getByText("Selection this week").nextElementSibling?.textContent).toBe(
        "Archived: eeeeeeeeeeee at skill 0.412 (18 resolved). Admitted: ffffffffffff (accepted).",
      ),
    );
  });
});
