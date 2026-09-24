import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";
import { createClient } from "../api/client.ts";
import { ApiContext } from "../api/context.tsx";
import type { Health, OwnerCosts } from "../api/schema.gen.ts";
import { mockContent, skeleton } from "../test/skeleton.ts";
import { Costs } from "./Costs.tsx";

const totals = (priced_micros: number, priced_runs: number) => ({
  priced_micros,
  priced_runs,
  unpriced_runs: 0,
  unpriced_input_tokens: 0,
  unpriced_output_tokens: 0,
});

const costs: OwnerCosts = {
  day: "2026-10-02",
  month: "2026-10",
  source: "settlements",
  caps: {
    daily_cap_micros: 8_000_000,
    monthly_cap_micros: 200_000_000,
    jev_daily_sublimit_micros: 2_000_000,
    jev_daily_sublimit_source: "profile_constant",
    funded: true,
    paid_execution_enabled: true,
  },
  today: totals(260_000, 14),
  month_to_date: totals(2_540_000, 140),
  by_island: { items: [{ island: "cs", ...totals(2_540_000, 140) }], next_cursor: null },
  by_configuration: {
    items: ["1", "2"].map((n) => ({
      configuration_id: `${n.repeat(8)}-1111-4111-8111-111111111111`,
      island: "cs",
      ...totals(1_270_000, 70),
    })),
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
  "body > :nth-child(n+8):nth-child(-n+9)", // spend per day
  "body > :nth-child(11) > :nth-child(n+3)", // each island's share of the month
  "body > :nth-child(15) form", // pausing paid execution
  "body > :nth-child(n+17):nth-child(-n+19)", // the islands table
  "body > :nth-child(22) span.na", // skill per dollar
  "body > :nth-child(23)", // the launch profile
];

/** The page's own day picker, which the mock lacks. */
const EXTRA = ["div.sec input"];

const ok = (data: unknown) => new Response(JSON.stringify({ contract: "1", data }), { status: 200 });

afterEach(cleanup);

describe("costs page", () => {
  it("matches the mock page's served sections tag for tag and class for class", async () => {
    const fetch = ((input: RequestInfo | URL) =>
      Promise.resolve(ok(String(input).startsWith("/api/v1/health") ? health : costs))) as typeof globalThis.fetch;
    const { container } = render(
      <ApiContext.Provider value={createClient({ origin: "", fetch })}>
        <MemoryRouter>
          <Costs />
        </MemoryRouter>
      </ApiContext.Provider>,
    );
    await screen.findByText("All systems normal");
    await screen.findByText("Per agent, this month");
    expect(skeleton(container, { drop: EXTRA })).toBe(mockContent("costs.html", UNSERVED));
  });
});
