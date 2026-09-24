import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { App } from "../App.tsx";
import type { Health, OwnerQuestions } from "../api/schema.gen.ts";
import { mockBody, pageSkeleton } from "../test/skeleton.ts";

const health: Health = {
  state: "healthy",
  checked_at: "2026-10-02T02:30:00.000000Z",
  checks: [{ name: "workers", state: "healthy", detail: "2 of 2 busy" }],
};

const OPEN = "11111111-1111-4111-8111-111111111111";
const DONE = "22222222-2222-4222-8222-222222222222";

function question(id: string, resolvedTrue: number, lastResolved: string | null) {
  return {
    question_id: id,
    target_definition_hash: "a".repeat(64),
    resolver_id: "citations-5-in-1y",
    resolver_version: 1,
    horizon: "2027-10-01T02:47:00.000000Z",
    sheets: 2,
    runs: 4,
    submissions: 3,
    resolved_true: resolvedTrue,
    resolved_false: 0,
    unresolvable: 0,
    last_resolved_at: lastResolved,
  };
}

const questions: OwnerQuestions = {
  questions: {
    items: [question(DONE, 2, "2026-10-01T05:00:00.000000Z"), question(OPEN, 0, null)],
    next_cursor: null,
  },
};

function mount() {
  const fetch = ((input: RequestInfo | URL) => {
    const url = String(input);
    const data = url.startsWith("/api/v1/health") ? health : url === "/api/v1/questions" ? questions : null;
    return Promise.resolve(
      data === null ? new Response("", { status: 404 }) : new Response(JSON.stringify({ contract: "1", data })),
    );
  }) as typeof globalThis.fetch;
  window.history.pushState({}, "", "/questions");
  return render(<App fetch={fetch} />);
}

afterEach(cleanup);

describe("questions", () => {
  it("puts open questions first and resolved ones in the fold, each opening its question", async () => {
    const { container } = mount();
    await screen.findByText("2 asked · 1 resolved · 1 open");
    const ask = container.querySelectorAll(".feed.ask");
    const done = container.querySelectorAll("details.adv > .feed.done");
    expect(ask).toHaveLength(1);
    expect(done).toHaveLength(1);
    expect(ask[0]?.querySelector("a")?.getAttribute("href")).toBe(`/questions/${OPEN}`);
    expect(ask[0]?.querySelector(".state")?.textContent).toBe("open · nothing resolved yet");
    expect(done[0]?.querySelector(".state")?.textContent).toBe(
      "2 true · 0 false · 0 unresolvable · resolved 2026-10-01 05:00 UTC",
    );
    expect(ask[0]?.textContent).toContain("judged 2027-10-01 02:47 UTC · 2 sheets · 4 runs · 3 submissions");
  });

  it("matches the mock page section for section, menu, health line and lab line included", async () => {
    const { container } = mount();
    await screen.findByText("2 asked · 1 resolved · 1 open");
    expect(pageSkeleton(container)).toBe(pageSkeleton(mockBody("questions.html")));
  });
});
