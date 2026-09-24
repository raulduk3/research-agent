import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { App } from "../App.tsx";
import type { Health, OwnerIslands } from "../api/schema.gen.ts";
import { mockBody, pageSkeleton } from "../test/skeleton.ts";

const health: Health = {
  state: "healthy",
  checked_at: "2026-10-02T02:30:00.000000Z",
  checks: [{ name: "workers", state: "healthy", detail: "2 of 2 busy" }],
};

const islands: OwnerIslands = {
  islands: {
    items: [
      {
        island: "cs",
        genomes: 4,
        founders: 1,
        lineages: 3,
        runs: 120,
        last_run_at: "2026-10-02T01:00:00.000000Z",
      },
      {
        island: "q-bio",
        genomes: 2,
        founders: 1,
        lineages: 2,
        runs: 0,
        last_run_at: null,
      },
    ],
    next_cursor: null,
  },
};

function mount() {
  const fetch = ((input: RequestInfo | URL) => {
    const url = String(input);
    const data = url.startsWith("/api/v1/health") ? health : url === "/api/v1/islands" ? islands : null;
    return Promise.resolve(
      data === null ? new Response("", { status: 404 }) : new Response(JSON.stringify({ contract: "1", data })),
    );
  }) as typeof globalThis.fetch;
  window.history.pushState({}, "", "/islands");
  return render(<App fetch={fetch} />);
}

function row(island: string): (string | null)[] {
  const link = screen.getByRole("link", { name: island });
  return [...(link.closest("tr")?.querySelectorAll("td") ?? [])].map((td) => td.textContent);
}

afterEach(cleanup);

describe("islands", () => {
  it("gives each island's stored agents, runs and latest run, and names an island with none", async () => {
    mount();
    await screen.findByText("120 runs");
    const na = "not served yet";
    expect(row("cs")).toEqual([
      "cs",
      na,
      na,
      "4 agents · 1 founders · 3 lineages",
      "120 runs",
      na,
      na,
      "2026-10-02 01:00 UTC",
    ]);
    expect(row("quant-ph")).toEqual(["quant-ph", na, na, "no agent stored", "0 runs", na, na, "none"]);
    expect(row("q-bio")[7]).toBe("none");
    expect(screen.getByRole("link", { name: "cs" }).getAttribute("href")).toBe("/islands/cs");
  });

  it("matches the mock page section for section, menu, health line and lab line included", async () => {
    const { container } = mount();
    await screen.findByText("120 runs");
    expect(pageSkeleton(container)).toBe(pageSkeleton(mockBody("islands.html")));
  });
});
