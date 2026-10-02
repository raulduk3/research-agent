import type { Activity, Agent, Brief, IslandView, PaperView, RunView, Storm } from "../api/types.ts";

// The shapes below are the server's own (deploy/beta/README.md), cut down to what the pages read.

export const STORM: Storm = {
  islands: [
    { id: "cs", name: "CS island", focus: "agents, memory, evaluation", evolve: true, paper_count: 1, run_count: 1 },
    { id: "bio", name: "Bio island", focus: "mechanisms, methods", evolve: false, paper_count: 0, run_count: 0 },
  ],
  papers: 2,
  runs: 1,
  cost_micros: 2000,
};

export const AGENT: Agent = {
  id: "cs-reader",
  island_id: "cs",
  prompt: "Read one paper. Ask what would change your mind.",
  allowed_tools: ["paper_text", "submit_reading"],
  active: true,
  version: 1,
  parent_id: null,
  generation: 0,
  state: "idle",
  cost_micros: 5000,
};

export const PAPER: PaperView = {
  paper: {
    id: "2610.00001",
    title: "Sparse routing for reading swarms",
    summary: "We route papers to islands. Visible traces change what agents learn.",
    url: "https://arxiv.org/abs/2610.00001",
    primary_category: "cs.AI",
    text_status: "abstract",
    fetched_at: 1790000100,
    sections: [
      { id: "p-intro", title: "Introduction", page: 1, text: "Reading swarms need routing." },
      { id: "p-results", title: "Results", page: 4, text: "Routing by island cut cost by half\nwhile keeping coverage." },
    ],
  },
  assignments: [{ paper_id: "2610.00001", island_id: "cs", reason: "category:cs.AI" }],
  runs: [],
  readings: [],
  cost_micros: 5000,
  cost_by_island: { cs: 5000 },
  likes: { "paper:2610.00001": { count: 2, islands: ["bio", "quant"] } },
};

export const RUN: RunView = {
  run: { id: "R-1", paper_id: "2610.00001", paper_title: PAPER.paper.title, island_id: "cs", genome_id: "cs-reader", genome_version: 1, status: "completed", created_at: 1790000200, cost_micros: 5000 },
  // The run's own copy of the genome keeps its lineage nested, as the server stores it.
  genome: { id: "cs-reader", island_id: "cs", prompt: AGENT.prompt, allowed_tools: AGENT.allowed_tools, active: true, version: 1, lineage: { generation: 0, parent: null } },
  paper: PAPER.paper,
  events: [
    { id: 1, run_id: "R-1", kind: "run_started", body: "run started", cost_micros: 0, created_at: 1790000200 },
    { id: 2, run_id: "R-1", kind: "tool_call", tool: "paper_text", body: "Tool paper_text", cost_micros: 1000, created_at: 1790000201, input: "What did routing change?", locator: { page: 4, section: "p-results", quote: "cut cost by half while keeping coverage" } },
    { id: 3, run_id: "R-1", kind: "model_call", model: "reader-small", body: "weighed the claim", cost_micros: 3000, created_at: 1790000202, locator: { page: 7 } },
    { id: 4, run_id: "R-1", kind: "tool_call", tool: "submit_reading", body: "submitted the reading", cost_micros: 1000, created_at: 1790000203 },
  ],
  reading: {
    id: "D-1",
    run_id: "R-1",
    genome_id: "cs-reader",
    summary: "Routing by island helps.",
    thesis_quote: "Visible traces change what agents learn.",
    thesis_char_start: 28,
    thesis_char_end: 68,
    claims: [{ text: "Routing halves cost.", evidence: [{ quote: "cut cost by half", verified: true }] }],
    objections: ["One benchmark only."],
    related_papers: [],
    idea_seeds: ["Try it on a second island."],
    created_at: 1790000203,
  },
  cost_micros: 5000,
};

export const ISLAND: IslandView = {
  island: STORM.islands[0] as IslandView["island"],
  agents: [AGENT],
  queue: [],
  papers: [PAPER.paper],
  runs: [RUN.run],
  cost_micros: 5000,
  evolution: [],
  evolution_enabled: true,
  mutation_enabled: true,
  swarm_evolution_enabled: true,
  unavailable: [],
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

export const BRIEF: Brief = {
  generated_at: 1790000300,
  about: "Atoll is a swarm of AI reading agents.",
  grade: {
    letter: "D",
    score: 41.5,
    rule: "The score weighs each criterion by its weight.",
    criteria: [
      { criterion: "evidence", weight: 20, score: 100, measured: true, evidence: "1 of 1 paper claims carry a quote found in the stored text" },
      { criterion: "scrutiny", weight: 15, score: 0, measured: true, evidence: "0 of 1 readings drew any human feedback" },
    ],
    caps: [{ ceiling: "C-", reason: "no person has judged a reading; usefulness is unmeasured" }],
  },
  findings: ["Coverage is middling at 50/100: 1 of 2 stored papers have a reading."],
  numbers: { readings: 1, claims: 1, verified_claims: 1, cost_micros: 5000 },
  claims: [
    { text: "Routing halves cost.", paper_id: "2610.00001", paper_title: "Sparse routing for reading swarms", agent: "cs-reader@cs", island_id: "cs", reading_id: "D-1", depends_on_paper: true, stance: "positive", verified: true, quote: "cut cost by half", created_at: 1790000203 },
  ],
  papers: {
    held: 1,
    waiting: 1,
    let_go_after_days: 14,
    rule: "A paper is held once any run or reading names it, until someone lets it go.",
    held_papers: [{ id: "2610.00001", title: "Sparse routing for reading swarms", primary_category: "cs.AI", text_status: "abstract_only", first_seen_at: 1790000000, islands: ["cs"], readings: 1, runs: 1 }],
    waiting_papers: [{ id: "2610.00002", title: "An unread paper", primary_category: "cs.AI", text_status: "abstract_only", first_seen_at: 1790000000, islands: ["cs"], readings: 0, runs: 0, days_left: 3.5 }],
    recent_papers: [],
  },
  agents: [{ address: "cs-reader@cs", island_id: "cs", version: 1, generation: 0, runs: 1, completed: 1, failed: 0, reading_now: null }],
  limits: ["A claim is checked once, when it is submitted."],
};

export const ACTIVITY: Activity = {
  steps: [
    { id: 1, run_id: "R-1", agent: "cs-reader@cs", island_id: "cs", paper_id: "2610.00001", kind: "run_started", looked_at: [], created_at: 1790000200 },
    { id: 2, run_id: "R-1", agent: "cs-reader@cs", island_id: "cs", paper_id: "2610.00001", kind: "tool_call", tool: "related_papers", looked_at: ["2610.00009"], created_at: 1790000201 },
  ],
  papers: { "2610.00001": { id: "2610.00001", title: "Sparse routing for reading swarms", primary_category: "cs.AI", islands: ["cs"] } },
  last_id: 2,
};

export const ROUTES: Record<string, unknown> = {
  "GET /api/v1/public/storm": STORM,
  "GET /api/v1/public/brief?include=grade,numbers,papers&limit=100": BRIEF,
  "GET /api/v1/public/activity?after=0&limit=60": ACTIVITY,
  "GET /api/v1/islands/cs": ISLAND,
  "GET /api/v1/papers/2610.00001": PAPER,
  "GET /api/v1/runs/R-1": RUN,
  "POST /api/v1/login": { island: "cs", token: "t-cs", role: "island" },
};

export function signIn(island = "cs"): void {
  localStorage.setItem("atoll.session", JSON.stringify({ island, token: `t-${island}` }));
}
