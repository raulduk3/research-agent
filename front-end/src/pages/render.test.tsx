import { cleanup, render, screen, waitFor } from "@testing-library/react";
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
    ["/islands", "/api/v1/islands"],
    ["/islands/cs", "/api/v1/islands/cs"],
    [`/agents/${ID}`, `/api/v1/`],
    [`/runs/${ID}`, `/api/v1/`],
    [`/runs/${ID}/trace`, `/api/v1/`],
    [`/papers/${ID}`, `/api/v1/`],
    ["/reports", "/api/v1/reports"],
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

  it.each(["/runs"])("%s is a lookup form that reads nothing but the health line until asked", (path) => {
    const seen = mount(path);
    expect(screen.getAllByRole("textbox").length).toBeGreaterThan(0);
    expect(seen).toEqual(["/api/v1/health"]);
  });

  it("/models lists the pinned models and keeps the lookup form", async () => {
    const seen = mount("/models");
    expect(screen.getAllByRole("textbox").length).toBeGreaterThan(0);
    await waitFor(() => expect(seen).toContain("/api/v1/models"));
    expect(await screen.findByText("not served yet")).toBeTruthy();
  });

  it("a page with no /api/v1 route says so instead of inventing data", () => {
    const seen = mount("/swarm");
    expect(screen.getByText(/no \/api\/v1 route/i)).toBeTruthy();
    expect(seen).toEqual(["/api/v1/health"]);
  });
});
