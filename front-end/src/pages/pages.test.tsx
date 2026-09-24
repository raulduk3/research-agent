import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it } from "vitest";
import { createClient } from "../api/client.ts";
import { ApiContext } from "../api/context.tsx";
import type { OwnerDigest, SeedView } from "../api/schema.gen.ts";
import { Digest } from "./Digest.tsx";
import { Seed } from "./Seed.tsx";

const TEMPLATE = "11111111-1111-4111-8111-111111111111";
const SEEDED = "33333333-3333-4333-8333-333333333333";
const H = (c: string) => c.repeat(64);

const ok = (status: number, data: unknown) => new Response(JSON.stringify({ contract: "1", data }), { status });

function mount(at: string, path: string, element: ReactNode, get: unknown, ...posts: Response[]) {
  const seen: { url: string; init: RequestInit }[] = [];
  const fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    seen.push({ url: String(input), init: init ?? {} });
    if (init?.method === "GET") return Promise.resolve(ok(200, get));
    const next = posts.shift();
    if (!next) throw new Error("unexpected POST");
    return Promise.resolve(next);
  }) as typeof globalThis.fetch;
  render(
    <ApiContext.Provider value={createClient({ origin: "", fetch })}>
      <MemoryRouter initialEntries={[at]}>
        <Routes>
          <Route path={path} element={element} />
        </Routes>
      </MemoryRouter>
    </ApiContext.Provider>,
  );
  return seen;
}

afterEach(cleanup);

describe("seed page", () => {
  it("reads the template and seeds every part into the chosen island", async () => {
    const view: SeedView = {
      emphasis_fields: { items: ["prompt", "scan_policy", "read_policy", "probability_assignment_rule"], next_cursor: null },
      copied: {
        configuration_id: TEMPLATE,
        configuration_hash: H("a"),
        island: "cs",
        founder: true,
        lineage_id: "evidence-first",
        emphasis: { prompt: "p0", scan_policy: "s0", read_policy: "r0", probability_assignment_rule: "q0" },
      },
      csrf_token: "form-token",
    };
    const seen = mount(`/seed?template=${TEMPLATE}`, "/seed", <Seed />, view, ok(201, { configuration_id: SEEDED }));
    fireEvent.change(await screen.findByLabelText("Island"), { target: { value: "q-bio" } });
    fireEvent.click(screen.getByRole("button", { name: "seed as new agent" }));
    await screen.findByRole("status");

    expect(seen[0]?.url).toBe(`/api/v1/seed?template=${TEMPLATE}`);
    const post = seen.find((s) => s.init.method === "POST");
    expect(post?.url).toBe("/api/v1/seed");
    expect(new Headers(post?.init.headers).get("X-CSRF-Token")).toBe("form-token");
    // Seed has no source to fall back on: every part travels, unlike an edit's changed parts.
    expect(JSON.parse(String(post?.init.body))).toEqual({
      island: "q-bio",
      lineage_id: "evidence-first",
      template_configuration_id: TEMPLATE,
      prompt: "p0",
      scan_policy: "s0",
      read_policy: "r0",
      probability_assignment_rule: "q0",
    });
  });
});

describe("digest page", () => {
  it("shows provenance for a rated entry and nothing more than the position for an unrated one", async () => {
    const digest: OwnerDigest = {
      digest_hash: H("d"),
      batch_id: "b1",
      island: "cs",
      source_watermark: 7,
      shuffle_seed: "s",
      built_at: "2026-09-24T01:03:00Z",
      entries: [
        { entry_id: "e2", paper_hash: H("2"), display_position: 2, rated: false },
        {
          entry_id: "e1",
          paper_hash: H("1"),
          origin: "random_control",
          display_position: 1,
          service_source: null,
          candidate_pool_hash: null,
          inclusion_probability: 0.25,
          nominations: [],
          rated: true,
        },
      ],
    };
    mount(`/digests/${H("d")}`, "/digests/:digestHash", <Digest />, digest);
    const entries = (await screen.findAllByRole("table"))[0];
    const rows = within(entries as HTMLElement).getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(rows[1]?.textContent).toContain("random control");
    expect(rows[2]?.textContent).toContain("blinded until you rate it");
    expect(rows[2]?.textContent).not.toMatch(/control|population|service/);
  });
});
