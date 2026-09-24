import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { App } from "../App.tsx";
import type { Health, OwnerIsland } from "../api/schema.gen.ts";
import { mockBody, pageSkeleton } from "../test/skeleton.ts";

const health: Health = {
  state: "healthy",
  checked_at: "2026-10-02T02:30:00.000000Z",
  checks: [{ name: "workers", state: "healthy", detail: "2 of 2 busy" }],
};

const FOUNDER = "11111111-1111-4111-8111-111111111111";
const CHILD = "22222222-2222-4222-8222-222222222222";

const island: OwnerIsland = {
  island: "cs",
  genomes: {
    items: [
      {
        configuration_id: FOUNDER,
        configuration_hash: "a".repeat(64),
        lineage_id: "evidence-first",
        founder: true,
        admission: "seeded",
        admitted_at: "2026-09-20T00:00:00.000000Z",
        runs: 40,
        void_runs: 2,
        priced_runs: 38,
        cost_micros: 3_800_000,
        last_run_at: "2026-10-02T01:00:00.000000Z",
      },
      {
        configuration_id: CHILD,
        configuration_hash: "b".repeat(64),
        lineage_id: "skeptic",
        founder: false,
        admission: "accepted",
        admitted_at: "2026-09-27T00:00:00.000000Z",
        runs: 0,
        void_runs: 0,
        priced_runs: 0,
        cost_micros: 0,
        last_run_at: null,
      },
    ],
    next_cursor: null,
  },
};

function mount() {
  const seen: string[] = [];
  const fetch = ((input: RequestInfo | URL) => {
    const url = String(input);
    seen.push(url);
    const data = url.startsWith("/api/v1/health") ? health : url === "/api/v1/islands/cs" ? island : null;
    return Promise.resolve(
      data === null ? new Response("", { status: 404 }) : new Response(JSON.stringify({ contract: "1", data })),
    );
  }) as typeof globalThis.fetch;
  window.history.pushState({}, "", "/islands/cs");
  return { ...render(<App fetch={fetch} />), seen };
}

function row(name: string): (string | null)[] {
  const link = screen.getByRole("link", { name: new RegExp(name) });
  return [...(link.closest("tr")?.querySelectorAll("td") ?? [])].map((td) => td.textContent);
}

afterEach(cleanup);

describe("island", () => {
  it("lists the island's stored agents, founder first, with their runs and cost, and sums them", async () => {
    mount();
    await screen.findByText("40 · 2 void");
    const na = "not served yet";
    expect(row("evidence-first")).toEqual([
      "cs · evidence-first founder",
      "40 · 2 void",
      na,
      na,
      na,
      "USD 0.10",
      "2026-10-02 01:00 UTC",
    ]);
    expect(row("skeptic")).toEqual(["cs · skeptic", "0", na, na, na, "no priced run", "none"]);
    expect(screen.getByRole("link", { name: /skeptic/ }).getAttribute("href")).toBe(`/agents/${CHILD}`);
    expect(screen.getByText("40 runs")).toBeTruthy();
    expect(screen.getByText("all-time · 2 void")).toBeTruthy();
    expect(screen.getByText("USD 3.80")).toBeTruthy();
    expect(screen.getByText(/2 agents stored, 1 of them founders/)).toBeTruthy();
  });

  it("matches the mock page section for section, menu, health line and lab line included", async () => {
    const { container } = mount();
    await screen.findByText("40 · 2 void");
    expect(pageSkeleton(container)).toBe(pageSkeleton(mockBody("island.html")));
  });
});
