import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it } from "vitest";
import { createClient } from "../api/client.ts";
import { ApiContext } from "../api/context.tsx";
import type { Health, OwnerAgentView, Run } from "../api/schema.gen.ts";
import { mockShape, pageSkeleton } from "../test/skeleton.ts";
import { Agent } from "./Agent.tsx";

const ID = "11111111-1111-4111-8111-111111111111";

const view: OwnerAgentView = {
  genome: {
    configuration_id: ID,
    configuration_hash: "a".repeat(64),
    island: "cs",
    founder: false,
    lineage_id: "evidence-first",
    emphasis: { prompt: "p0", scan_policy: "s0", read_policy: "r0", probability_assignment_rule: "q0" },
  },
  emphasis_fields: { items: ["prompt", "scan_policy", "read_policy", "probability_assignment_rule"], next_cursor: null },
  admission: null,
  retirement: null,
  csrf_token: "form-token",
};

const health: Health = {
  state: "healthy",
  checked_at: "2026-10-02T02:30:00.000000Z",
  checks: [{ name: "workers", state: "healthy", detail: "2 of 2 busy" }],
};

function run(n: number): Run {
  return {
    run_id: `33333333-3333-4333-8333-33333333333${n}`,
    batch_id: "2026-10-01",
    paper_id: `group ${n} of 18`,
    configuration_id: ID,
    attempt: 1,
    genome_hash: "a".repeat(64),
    seed: n,
    snapshot_hash: "b".repeat(64),
    budgets: { spend_micros: 18_000 },
    allowed_tools: [],
    model_identity: {},
    checkpoint_dates: [],
    created_at: `2026-10-01T0${n}:03:00.000000Z`,
  };
}

const inspected: OwnerAgentView = {
  ...view,
  genome: { ...view.genome, founder: true },
  admission: { configuration_id: ID, owner_id: ID, kind: "seed", source_configuration_id: null, requested_at: "2026-09-24T00:00:00.000000Z" },
  inspected: {
    configuration_id: ID,
    genome: null,
    runs: { items: [run(1), run(2)], next_cursor: null },
    forecasts: { items: [], next_cursor: null },
  },
};

const ok = (status: number, data: unknown) => new Response(JSON.stringify({ contract: "1", data }), { status });

function mount(...posts: Response[]) {
  return mountWith(view, posts);
}

function mountWith(get: OwnerAgentView, posts: Response[]) {
  const seen: { url: string; init: RequestInit }[] = [];
  const fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    seen.push({ url: String(input), init: init ?? {} });
    if (init?.method === "GET") return Promise.resolve(ok(200, String(input).startsWith("/api/v1/health") ? health : get));
    const next = posts.shift();
    if (!next) throw new Error("unexpected POST");
    return Promise.resolve(next);
  }) as typeof globalThis.fetch;
  const { container } = render(
    <ApiContext.Provider value={createClient({ origin: "", fetch })}>
      <MemoryRouter initialEntries={[`/agents/${ID}`]}>
        <Routes>
          <Route path="/agents/:configurationId" element={<Agent />} />
        </Routes>
      </MemoryRouter>
    </ApiContext.Provider>,
  );
  const posted = () => seen.filter((s) => s.init.method === "POST");
  return { posted, container };
}

const header = (init: RequestInit | undefined, name: string) => new Headers(init?.headers).get(name);

afterEach(cleanup);

/** A field of the owner actions once the agent is read: until then the fold's fields are disabled. */
async function loaded(label: string) {
  await waitFor(() => expect((screen.getByLabelText(label) as HTMLTextAreaElement).disabled).toBe(false));
  return screen.getByLabelText(label);
}

describe("agent page", () => {
  it("admits an edit with only the changed parts and the view's token, reusing the key on retry", async () => {
    const { posted } = mount(
      new Response("", { status: 503 }),
      ok(201, { configuration_id: "22222222-2222-4222-8222-222222222222" }),
    );
    fireEvent.change(await loaded("How it reads"), { target: { value: "r1" } });
    const admit = screen.getByRole("button", { name: "admit as new agent" });
    fireEvent.click(admit);
    expect(await screen.findByRole("alert")).toBeTruthy();
    fireEvent.click(admit);
    expect((await screen.findByRole("status")).textContent).toContain("22222222-222");

    const [first, second] = posted();
    expect(first?.url).toBe(`/api/v1/agents/${ID}/admit`);
    expect(JSON.parse(String(first?.init.body))).toEqual({ lineage_id: "evidence-first", read_policy: "r1" });
    expect(header(first?.init, "X-CSRF-Token")).toBe("form-token");
    expect(header(first?.init, "Idempotency-Key")).toBeTruthy();
    expect(header(second?.init, "Idempotency-Key")).toBe(header(first?.init, "Idempotency-Key"));
  });

  it("gives a changed body a new key", async () => {
    const { posted } = mount(new Response("", { status: 503 }), new Response("", { status: 503 }));
    const reads = await loaded("How it reads");
    const admit = screen.getByRole("button", { name: "admit as new agent" });
    fireEvent.change(reads, { target: { value: "r1" } });
    fireEvent.click(admit);
    await screen.findByRole("alert");
    fireEvent.change(reads, { target: { value: "r2" } });
    fireEvent.click(admit);
    await waitFor(() => expect(posted()).toHaveLength(2));
    const [a, b] = posted();
    expect(JSON.parse(String(b?.init.body))).toMatchObject({ read_policy: "r2" });
    expect(header(b?.init, "Idempotency-Key")).not.toBe(header(a?.init, "Idempotency-Key"));
  });

  it("matches the mock page section for section", async () => {
    const { container } = mountWith(inspected, []);
    await waitFor(() => expect(container.querySelector("p.lead")?.textContent).not.toBe("loading…"));
    await screen.findAllByRole("link", { name: "open" });
    expect(pageSkeleton(container)).toBe(mockShape("agent.html"));
  });
});
