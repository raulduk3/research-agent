import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { App } from "../App.tsx";
import type { Health, OwnerImpact } from "../api/schema.gen.ts";
import { mockBody, pageSkeleton } from "../test/skeleton.ts";

const health: Health = {
  state: "healthy",
  checked_at: "2026-10-02T02:30:00.000000Z",
  checks: [{ name: "workers", state: "healthy", detail: "2 of 2 busy" }],
};

function row(island: "cs" | "econ", week: string, likes: number) {
  return {
    island,
    iso_week: week,
    ratings: likes + 2,
    likes,
    dislikes: 1,
    skips: 1,
    credits: likes,
    genomes_credited: 1,
    credit_gaps: 1,
  };
}

const impact: OwnerImpact = {
  impact: {
    items: [row("cs", "2026-W39", 9), row("cs", "2026-W40", 3), row("q-bio", "2026-W40", 1)],
    next_cursor: null,
  },
};

function mount() {
  const fetch = ((input: RequestInfo | URL) => {
    const url = String(input);
    const data = url.startsWith("/api/v1/health") ? health : url === "/api/v1/impact" ? impact : null;
    return Promise.resolve(
      data === null ? new Response("", { status: 404 }) : new Response(JSON.stringify({ contract: "1", data })),
    );
  }) as typeof globalThis.fetch;
  window.history.pushState({}, "", "/impact");
  return render(<App fetch={fetch} />);
}

afterEach(cleanup);

describe("impact", () => {
  it("sums the latest rating week over its islands, leaving earlier weeks out", async () => {
    const { container } = mount();
    await screen.findByText("In 2026-W40 raters made 8 calls: 4 liked, 2 disliked, 2 skipped.");
    const facts = container.querySelectorAll("ul.facts > li");
    expect(facts[1]?.textContent).toContain("They wrote 4 credit rows to 2 genomes, with 2 credit gaps.");
    expect(facts[1]?.querySelector(".num")?.textContent).toBe("0.50");
    expect(container.querySelector("p.lead")?.textContent).toContain("summed over cs, econ");
  });

  it("matches the mock page section for section, menu, health line and lab line included", async () => {
    const { container } = mount();
    await screen.findByText("In 2026-W40 raters made 8 calls: 4 liked, 2 disliked, 2 skipped.");
    expect(pageSkeleton(container)).toBe(pageSkeleton(mockBody("impact.html")));
  });
});
