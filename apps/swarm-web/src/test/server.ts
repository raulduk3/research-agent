import type { IslandView, PaperView, RunView, Storm } from "../api/types.ts";

export const STORM: Storm = {
  islands: [
    { id: "cs", name: "CS island", focus: "agents, memory, evaluation", created_at: 1790000000 },
    { id: "bio", name: "Bio island", focus: "mechanisms, methods", created_at: 1790000000 },
  ],
  papers: 2,
  runs: 1,
  cost_micros: 2000,
};

export const PAPER: PaperView = {
  paper: {
    id: "2610.00001",
    title: "Sparse routing for reading swarms",
    summary: "We route papers to islands. Visible traces change what agents learn.",
    url: "https://arxiv.org/abs/2610.00001",
    primary_category: "cs.AI",
    text_status: "full",
    fetched_at: 1790000100,
    sections: [
      { title: "Introduction", page: 1, text: "Reading swarms need routing." },
      { title: "Results", page: 4, text: "Routing by island cut cost by half\nwhile keeping coverage." },
    ],
  },
  assignments: [{ paper_id: "2610.00001", island_id: "cs", reason: "category:cs.AI" }],
  runs: [],
  cost_micros: 5000,
};

export const RUN: RunView = {
  run: { id: "R-1", paper_id: "2610.00001", island_id: "cs", genome_id: "cs-g0", status: "submitted", reading: "Summary: routing helps.", created_at: 1790000200 },
  events: [
    { id: 1, run_id: "R-1", kind: "run_started", body: "run started", cost_micros: 0, created_at: 1790000200 },
    { id: 2, run_id: "R-1", kind: "paper_text", body: "read the results", cost_micros: 1000, created_at: 1790000201, input: "What did routing change?", locator: { page: 4, section: "Results", quote: "cut cost by half while keeping coverage" } },
    { id: 3, run_id: "R-1", kind: "model_call", model: "reader-small", body: "weighed the claim", cost_micros: 3000, created_at: 1790000202, locator: { page: 7 } },
    { id: 4, run_id: "R-1", kind: "submit_reading", body: "submitted the reading", cost_micros: 1000, created_at: 1790000203 },
  ],
  cost_micros: 5000,
};

export const ISLAND: IslandView = {
  island: STORM.islands[0] as IslandView["island"],
  papers: [PAPER.paper],
  genomes: [{ id: "cs-g0", island_id: "cs", prompt: "Read one paper. Ask what would change your mind.", tools: "paper_text,submit_reading", parent_id: null, generation: 0, active: 1, created_at: 1790000000 }],
  runs: [RUN.run],
  cost_micros: 5000,
};

export type Call = { method: string; path: string; headers: Record<string, string>; body: unknown };

/** A stand-in for the swarm server: answers the paths it is given, 404 for the rest, and keeps every call. */
export function fakeServer(routes: Record<string, unknown>): { fetch: typeof fetch; calls: Call[] } {
  const calls: Call[] = [];
  const doFetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const path = String(input);
    calls.push({ method, path, headers: (init?.headers ?? {}) as Record<string, string>, body: typeof init?.body === "string" ? JSON.parse(init.body) : null });
    const answer = routes[`${method} ${path}`];
    if (answer === undefined) return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
    if (answer instanceof Response) return answer.clone();
    return new Response(JSON.stringify(answer), { status: 200 });
  }) as typeof fetch;
  return { fetch: doFetch, calls };
}

export const ROUTES: Record<string, unknown> = {
  "GET /api/v1/public/storm": STORM,
  "GET /api/v1/islands/cs": ISLAND,
  "GET /api/v1/papers/2610.00001": PAPER,
  "GET /api/v1/runs/R-1": RUN,
  "POST /api/v1/login": { island: "cs", token: "t-cs" },
};

export function signIn(island = "cs"): void {
  localStorage.setItem("atoll.session", JSON.stringify({ island, token: `t-${island}` }));
}
