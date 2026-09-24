import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { App } from "../App.tsx";
import type { Health, OwnerCosts } from "../api/schema.gen.ts";
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

function mount() {
  const fetch = ((input: RequestInfo | URL) => {
    const url = String(input);
    const data = url.startsWith("/api/v1/health") ? health : url.startsWith("/api/v1/costs") ? costs : null;
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

  it("matches the mock page section for section, menu, health line and lab line included", async () => {
    const { container } = mount();
    await screen.findByText("Platform waiting");
    await screen.findByText("USD 2.28");
    expect(pageSkeleton(container)).toBe(pageSkeleton(mockBody("overview.html")));
  });
});
