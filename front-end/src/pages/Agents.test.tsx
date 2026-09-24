import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { App } from "../App.tsx";
import type { Configuration, Health, Population } from "../api/schema.gen.ts";
import { mockContent, skeleton } from "../test/skeleton.ts";

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
    items: [
      agent("cs", "earlier-work", false, 1),
      agent("cs", "evidence-first", true, 2),
      agent("quant-ph", "evidence-first", true, 3),
      agent("q-bio", "evidence-first", true, 4),
      agent("q-bio", "limitations", false, 5),
    ],
    next_cursor: null,
  },
};
const health: Health = {
  state: "healthy",
  checked_at: "2026-10-02T02:30:00.000000Z",
  checks: [{ name: "workers", state: "healthy", detail: "2 of 2 busy" }],
};

function mount() {
  const fetch = ((input: RequestInfo | URL) => {
    const url = String(input);
    const data = url.startsWith("/api/v1/health") ? health : url.startsWith("/api/v1/agents") ? population : null;
    return Promise.resolve(
      data === null ? new Response("", { status: 404 }) : new Response(JSON.stringify({ contract: "1", data })),
    );
  }) as typeof globalThis.fetch;
  window.history.pushState({}, "", "/agents");
  return render(<App fetch={fetch} />);
}

afterEach(cleanup);

/** Mock sections with no /api/v1 route; docs/implementation/front-end.md lists them. */
const UNSERVED = [
  ".wide tr > :nth-child(n+2)", // runs, forecasts, rater credit, agreement, cost per run
  "body > :nth-child(10)", // the note on those columns
];

describe("agents", () => {
  it("lists each island's agents founder first", async () => {
    mount();
    const links = await screen.findAllByRole("link", { name: /cs · / });
    expect(links.map((a) => a.textContent)).toEqual([
      `cs · evidence-first founder ${"2".repeat(12)}`,
      `cs · earlier-work ${"1".repeat(12)}`,
    ]);
  });

  it("matches the mock page's served sections tag for tag and class for class", async () => {
    const { container } = mount();
    await screen.findByText("All systems normal");
    await screen.findAllByRole("link", { name: /q-bio · / });
    const main = container.querySelector("main");
    expect(main).not.toBeNull();
    expect(skeleton(main as Element)).toBe(mockContent("agents.html", UNSERVED));
  });
});
