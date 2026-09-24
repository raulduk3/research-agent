import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { App } from "../App.tsx";
import type { Health, OwnerReports } from "../api/schema.gen.ts";
import { mockBody, pageSkeleton } from "../test/skeleton.ts";
import { weekSpan } from "./Reports.tsx";

const health: Health = {
  state: "healthy",
  checked_at: "2026-10-02T02:30:00.000000Z",
  checks: [{ name: "workers", state: "healthy", detail: "2 of 2 busy" }],
};

const reports: OwnerReports = {
  reports: {
    items: [
      { island: "q-bio", iso_week: "2026-W40", digests: 1, entries: 10, ratings: 2, credits: 1 },
      { island: "cs", iso_week: "2026-W39", digests: 9, entries: 90, ratings: 40, credits: 30 },
      { island: "cs", iso_week: "2026-W40", digests: 2, entries: 20, ratings: 5, credits: 4 },
    ],
    next_cursor: null,
  },
};

function mount() {
  const fetch = ((input: RequestInfo | URL) => {
    const url = String(input);
    const data = url.startsWith("/api/v1/health") ? health : url === "/api/v1/reports" ? reports : null;
    return Promise.resolve(
      data === null ? new Response("", { status: 404 }) : new Response(JSON.stringify({ contract: "1", data })),
    );
  }) as typeof globalThis.fetch;
  window.history.pushState({}, "", "/reports");
  return render(<App fetch={fetch} />);
}

function rows(): (string | null)[][] {
  return screen
    .getAllByRole("link", { name: /^W\d{2} · / })
    .map((link) => [...(link.closest("tr")?.querySelectorAll("td") ?? [])].map((td) => td.textContent));
}

afterEach(cleanup);

describe("reports", () => {
  it("writes an ISO week as its Monday to Sunday, across a year end", () => {
    expect(weekSpan("2026-W40")).toBe("W40 · 2026-09-28 to 10-04");
    expect(weekSpan("2026-W01")).toBe("W01 · 2025-12-29 to 01-04");
  });

  it("lists each stored island week newest first, opening its report", async () => {
    mount();
    await screen.findByText(/3 island weeks/);
    const na = "not served yet";
    expect(rows()).toEqual([
      ["W40 · 2026-09-28 to 10-04", "cs", "2 digests · 20 entries · 5 ratings · 4 credits", na, na],
      ["W40 · 2026-09-28 to 10-04", "q-bio", "1 digests · 10 entries · 2 ratings · 1 credits", na, na],
      ["W39 · 2026-09-21 to 09-27", "cs", "9 digests · 90 entries · 40 ratings · 30 credits", na, na],
    ]);
    expect(screen.getAllByRole("link", { name: /^W40/ })[1]?.getAttribute("href")).toBe("/reports/q-bio/2026-W40");
  });

  it("matches the mock page section for section, menu, health line and lab line included", async () => {
    const { container } = mount();
    await screen.findByText(/3 island weeks/);
    expect(pageSkeleton(container)).toBe(pageSkeleton(mockBody("reports.html")));
  });
});
