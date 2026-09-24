import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { App } from "../App.tsx";
import type { Health, OwnerQuestion } from "../api/schema.gen.ts";
import { mockBody, pageSkeleton } from "../test/skeleton.ts";

const health: Health = {
  state: "healthy",
  checked_at: "2026-10-02T02:30:00.000000Z",
  checks: [{ name: "workers", state: "healthy", detail: "2 of 2 busy" }],
};

const Q = "11111111-1111-4111-8111-111111111111";
const RUN = "33333333-3333-4333-8333-333333333333";
const GENOME = "44444444-4444-4444-8444-444444444444";

const question: OwnerQuestion = {
  question_id: Q,
  target_definition_hash: "a".repeat(64),
  resolver_id: "citations-5-in-1y",
  resolver_version: 1,
  horizon: "2027-10-01T02:47:00.000000Z",
  sheets: 2,
  runs: {
    items: [{ run_id: RUN, configuration_id: GENOME, probability: 0.58, accepted_at: "2026-10-01T03:00:00.000000Z" }],
    next_cursor: null,
  },
  resolutions: {
    items: [
      {
        forecast_id: "55555555-5555-4555-8555-555555555555",
        status: "true",
        resolution_version: 1,
        resolved_at: "2027-10-01T05:00:00.000000Z",
      },
    ],
    next_cursor: null,
  },
};

function mount() {
  const fetch = ((input: RequestInfo | URL) => {
    const url = String(input);
    const data = url.startsWith("/api/v1/health") ? health : url === `/api/v1/questions/${Q}` ? question : null;
    return Promise.resolve(
      data === null ? new Response("", { status: 404 }) : new Response(JSON.stringify({ contract: "1", data })),
    );
  }) as typeof globalThis.fetch;
  window.history.pushState({}, "", `/questions/${Q}`);
  return render(<App fetch={fetch} />);
}

afterEach(cleanup);

describe("question", () => {
  it("names the question by its resolver and lists each run's chance and the resolutions", async () => {
    const { container } = mount();
    await screen.findByText("citations-5-in-1y v1");
    expect(container.querySelector("p.lead")?.textContent).toContain(
      "judged 2027-10-01 02:47 UTC · 2 sheets · 1 runs submitted a chance",
    );
    const turn = container.querySelector(".thread > .turn");
    expect(turn?.querySelector(".who a")?.getAttribute("href")).toBe(`/agents/${GENOME}`);
    expect(turn?.querySelector(".watch")?.getAttribute("href")).toBe(`/runs/${RUN}/trace`);
    expect(turn?.textContent).toContain("accepted 2026-10-01 03:00 UTC");
    expect(container.querySelector(".reads > .readtile")?.getAttribute("href")).toBe(`/runs/${RUN}`);
    expect(container.querySelector("#life > .meta")?.textContent).toContain(
      "1 true · 0 false · 0 unresolvable · resolved 2027-10-01 05:00 UTC",
    );
  });

  it("matches the mock page section for section, menu, health line and lab line included", async () => {
    const { container } = mount();
    await screen.findByText("citations-5-in-1y v1");
    expect(pageSkeleton(container)).toBe(pageSkeleton(mockBody("question-Q1.html")));
  });
});
