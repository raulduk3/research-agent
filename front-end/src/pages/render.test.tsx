import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { App } from "../App.tsx";

const ID = "11111111-1111-4111-8111-111111111111";
const H = "a".repeat(64);

/** Every GET is refused as not found, so each page must render its refusal, not crash. */
function mount(path: string) {
  const seen: string[] = [];
  const fetch = ((input: RequestInfo | URL) => {
    seen.push(String(input));
    return Promise.resolve(new Response("", { status: 404 }));
  }) as typeof globalThis.fetch;
  window.history.pushState({}, "", path);
  render(<App fetch={fetch} />);
  return seen;
}

afterEach(cleanup);

describe("every served page renders through the owner shell", () => {
  it.each([
    ["/", "/api/v1/"],
    ["/agents", "/api/v1/"],
    [`/agents/${ID}`, `/api/v1/`],
    [`/runs/${ID}`, `/api/v1/`],
    [`/runs/${ID}/trace`, `/api/v1/`],
    [`/papers/${ID}`, `/api/v1/`],
    ["/reports/cs/2026-W38", "/api/v1/reports/cs/2026-W38"],
    [`/models/${H}`, `/api/v1/models/${H}`],
    ["/costs", "/api/v1/costs"],
    [`/digests/${H}`, `/api/v1/digests/${H}`],
    ["/seed", "/api/v1/seed"],
  ])("%s reads /api/v1 and shows the refusal", async (path, prefix) => {
    const seen = mount(path);
    expect((await screen.findAllByRole("alert")).length).toBeGreaterThan(0);
    expect(seen.length).toBeGreaterThan(0);
    expect(seen.every((url) => url.startsWith("/api/v1/"))).toBe(true);
    expect(seen.some((url) => url.startsWith(prefix))).toBe(true);
    if (path !== "/") expect(screen.getByRole("navigation")).toBeTruthy();
  });

  it.each(["/runs", "/reports", "/models"])("%s is a lookup form that reads nothing until asked", (path) => {
    const seen = mount(path);
    expect(screen.getAllByRole("textbox").length).toBeGreaterThan(0);
    expect(seen).toEqual([]);
  });

  it("a page with no /api/v1 route says so instead of inventing data", () => {
    const seen = mount("/islands");
    expect(screen.getByText(/no \/api\/v1 route/i)).toBeTruthy();
    expect(seen).toEqual([]);
  });
});
