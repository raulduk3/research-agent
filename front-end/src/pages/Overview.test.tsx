import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { App } from "../App.tsx";
import type { Configuration, Health, OwnerCosts, Population } from "../api/schema.gen.ts";
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

function mount() {
  const fetch = ((input: RequestInfo | URL) => {
    const url = String(input);
    const data = url.startsWith("/api/v1/health") ? health : url.startsWith("/api/v1/costs")
          ? costs
          : url.startsWith("/api/v1/agents")
            ? population
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
    expect(container.querySelectorAll("div.board > div.lane")).toHaveLength(0);
  });

  it("matches the mock page section for section, menu, health line and lab line included", async () => {
    const { container } = mount();
    await screen.findByText("Platform waiting");
    await screen.findByText("USD 2.28");
    expect(pageSkeleton(container)).toBe(pageSkeleton(mockBody("overview.html")));
  });
});
