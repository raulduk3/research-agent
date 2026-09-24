import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it } from "vitest";
import { createClient } from "../api/client.ts";
import { ApiContext } from "../api/context.tsx";
import type { OwnerAgentView } from "../api/schema.gen.ts";
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

const ok = (status: number, data: unknown) => new Response(JSON.stringify({ contract: "1", data }), { status });

function mount(...posts: Response[]) {
  const seen: { url: string; init: RequestInit }[] = [];
  const fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    seen.push({ url: String(input), init: init ?? {} });
    if (init?.method === "GET") return Promise.resolve(ok(200, view));
    const next = posts.shift();
    if (!next) throw new Error("unexpected POST");
    return Promise.resolve(next);
  }) as typeof globalThis.fetch;
  render(
    <ApiContext.Provider value={createClient({ origin: "", fetch })}>
      <MemoryRouter initialEntries={[`/agents/${ID}`]}>
        <Routes>
          <Route path="/agents/:configurationId" element={<Agent />} />
        </Routes>
      </MemoryRouter>
    </ApiContext.Provider>,
  );
  const posted = () => seen.filter((s) => s.init.method === "POST");
  return { posted };
}

const header = (init: RequestInit | undefined, name: string) => new Headers(init?.headers).get(name);

afterEach(cleanup);

describe("agent page", () => {
  it("admits an edit with only the changed parts and the view's token, reusing the key on retry", async () => {
    const { posted } = mount(
      new Response("", { status: 503 }),
      ok(201, { configuration_id: "22222222-2222-4222-8222-222222222222" }),
    );
    fireEvent.change(await screen.findByLabelText("How it reads"), { target: { value: "r1" } });
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
    const reads = await screen.findByLabelText("How it reads");
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
});
