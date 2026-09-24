import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { App } from "../App.tsx";
import type { Configuration, Health, OwnerCosts, OwnerDay, OwnerImpact, OwnerReports, Population } from "../api/schema.gen.ts";
import { NO_ANSWER } from "../graphics/Board.tsx";
import { mockBody, pageSkeleton } from "../test/skeleton.ts";

const totals = { priced_micros: 2_280_000, priced_runs: 121, unpriced_runs: 0, unpriced_input_tokens: 0, unpriced_output_tokens: 0 };
const costs: OwnerCosts = {
  day: "2026-10-01",
  month: "2026-10",
  source: "settlements",
  caps: {
    daily_cap_micros: 8_000_000,
    monthly_cap_micros: 200_000_000,
    jev_daily_sublimit_micros: 1_000_000,
    jev_daily_sublimit_source: "profile_constant",
    funded: true,
    paid_execution_enabled: true,
  },
  today: totals,
  month_to_date: totals,
  by_island: { items: [], next_cursor: null },
  by_configuration: { items: [], next_cursor: null },
};
const health: Health = {
  state: "waiting",
  checked_at: "2026-10-02T02:30:00.000000Z",
  checks: [
    { name: "workers", state: "healthy", detail: "2 of 2 busy" },
    { name: "anchor", state: "waiting", detail: "one check waiting" },
  ],
};

function agent(island: Configuration["island"], lineage: string, founder: boolean, n: number): Configuration {
  const hash = String(n).repeat(64);
  return {
    configuration_id: `00000000-0000-4000-8000-00000000000${n}`,
    configuration_hash: hash,
    lineage_id: lineage,
    island,
    founder,
    infra_hash: hash,
    parent_hash: null,
    parts: [],
    admission: { disposition: "admitted", profile_hash: null },
    admitted_at: "2026-10-01T02:00:00.000000Z",
    archive: null,
  };
}
const population: Population = {
  configurations: {
    items: [agent("q-bio", "limitations", true, 3), agent("cs", "earlier-work", false, 1), agent("cs", "evidence-first", true, 2)],
    next_cursor: null,
  },
};

const cs1 = "00000000-0000-4000-8000-000000000001";
const cs2 = "00000000-0000-4000-8000-000000000002";
const run = (n: number, configuration_id: string, ending: "submitted" | "void" | null, created: string, ended: string | null) => ({
  run_id: `10000000-0000-4000-8000-00000000000${n}`,
  configuration_id,
  island: "cs" as const,
  lineage_id: configuration_id === cs1 ? "earlier-work" : "evidence-first",
  paper_id: `2610.0000${n}`,
  created_at: `2026-10-01T${created}:00.000000Z`,
  ending,
  ended_at: ended === null ? null : `2026-10-01T${ended}:00.000000Z`,
});
const day: OwnerDay = {
  day: "2026-10-01",
  runs: {
    items: [
      run(1, cs2, "submitted", "01:00", "01:20"),
      run(2, cs2, "void", "02:00", "02:05"),
      run(3, cs1, "submitted", "03:00", "03:30"),
      run(4, cs1, null, "04:00", null),
    ],
    next_cursor: null,
  },
  digests: {
    items: [{ digest_hash: "d".repeat(64), island: "cs", built_at: "2026-10-01T05:00:00.000000Z", entries: 12, rated_entries: 3 }],
    next_cursor: null,
  },
};
const reports: OwnerReports = {
  reports: {
    items: [
      { island: "cs", iso_week: "2026-W39", digests: 9, entries: 90, ratings: 40, credits: 30 },
      { island: "cs", iso_week: "2026-W40", digests: 2, entries: 20, ratings: 5, credits: 4 },
      { island: "q-bio", iso_week: "2026-W40", digests: 1, entries: 10, ratings: 2, credits: 1 },
    ],
    next_cursor: null,
  },
};
const impact: OwnerImpact = {
  impact: {
    items: [
      { island: "cs", iso_week: "2026-W40", ratings: 5, likes: 3, dislikes: 1, skips: 1, credits: 4, genomes_credited: 2, credit_gaps: 0 },
      { island: "q-bio", iso_week: "2026-W40", ratings: 2, likes: 1, dislikes: 1, skips: 0, credits: 1, genomes_credited: 1, credit_gaps: 0 },
    ],
    next_cursor: null,
  },
};

function mount(served = true) {
  const fetch = ((input: RequestInfo | URL) => {
    const url = String(input);
    const data = url.startsWith("/api/v1/health") ? health : url.startsWith("/api/v1/costs")
          ? costs
          : url.startsWith("/api/v1/agents")
            ? population
            : !served
              ? null
              : url.startsWith("/api/v1/day")
                ? day
                : url.startsWith("/api/v1/reports")
                  ? reports
                  : url.startsWith("/api/v1/impact")
                    ? impact
                    : null;
    return Promise.resolve(
      data === null ? new Response("", { status: 404 }) : new Response(JSON.stringify({ contract: "1", data })),
    );
  }) as typeof globalThis.fetch;
  window.history.pushState({}, "", "/");
  return render(<App fetch={fetch} />);
}

afterEach(cleanup);

describe("owner home", () => {
  it("binds the health monitor and the costs", async () => {
    mount();
    expect(await screen.findByText("USD 2.28")).toBeTruthy();
    expect(await screen.findByText("Platform waiting")).toBeTruthy();
    expect(screen.getByText("anchor: waiting")).toBeTruthy();
  });

  it("draws the population as tiles, one row per island, founder first, hues stepping by 30", async () => {
    const { container } = mount();
    await screen.findByText("limitations");
    const rows = [...container.querySelectorAll("div.tiles > div.trow")];
    expect(rows.map((row) => row.querySelector("span.isl")?.textContent)).toEqual(["cs", "q-bio"]);
    const names = [...container.querySelectorAll("div.tile > a")].map((a) => a.textContent);
    expect(names).toEqual(["evidence-first", "earlier-work", "limitations"]);
    const hues = [...container.querySelectorAll<HTMLElement>("div.tile > span.dot")].map((dot) => dot.style.background);
    const painted = (hue: number) => {
      const probe = document.createElement("span");
      probe.style.background = `hsl(${hue}, 70%, 50%)`;
      return probe.style.background;
    };
    expect(hues).toEqual([painted(0), painted(30), painted(60)]);
    const notes = [...container.querySelectorAll("div.tile > small")].map((small) => small.textContent);
    expect(notes).toEqual(["founder · 2 runs · 1 void", "2 runs", "founder · 0 runs"]);
  });

  it("draws the day's runs on one lane per island, void runs in the no-answer colour", async () => {
    const { container } = mount();
    await screen.findByText("2 of 4");
    const lanes = [...container.querySelectorAll("div.board > div.lane")];
    expect(lanes.map((lane) => lane.querySelector("span.ln")?.textContent)).toEqual(["cs"]);
    const blocks = [...(lanes[0]?.querySelectorAll("rect") ?? [])].map((r) => [r.getAttribute("x"), r.getAttribute("width"), r.getAttribute("fill")]);
    expect(blocks).toEqual([
      ["60", "20", "hsl(0, 70%, 55%)"],
      ["120", "5", NO_ANSWER],
      ["180", "30", "hsl(30, 70%, 55%)"],
      ["240", "0", "hsl(30, 70%, 55%)"],
    ]);
    expect(screen.getByText("2026-10-01 · 1 void, 1 not ended")).toBeTruthy();
    expect(screen.getByText("1 built")).toBeTruthy();
    expect(screen.getByText("cs: 3 of 12 rated")).toBeTruthy();
  });

  it("fills this week from the latest week's reports and impact, summed over islands", async () => {
    mount();
    expect(await screen.findByText("7 ratings")).toBeTruthy();
    expect(
      screen.getByText(/2026-W40 · 3 digests, 30 entries · 4 liked, 2 disliked, 1 skipped · 5 credits · verdict not served yet/),
    ).toBeTruthy();
  });

  it("says not served for the board, tiles and cards when the day and weekly reads are missing", async () => {
    const { container } = mount(false);
    await screen.findByText("limitations");
    expect(container.querySelectorAll("div.board > div.lane")).toHaveLength(0);
    expect(screen.getAllByText("founder · runs not served yet")).toHaveLength(2);
    expect(screen.getByText("today's batch · not served yet")).toBeTruthy();
  });

  it("matches the mock page section for section, menu, health line and lab line included", async () => {
    const { container } = mount();
    await screen.findByText("Platform waiting");
    await screen.findByText("USD 2.28");
    expect(pageSkeleton(container)).toBe(pageSkeleton(mockBody("overview.html")));
  });
});
