import { z } from "zod";
const valueSchema = z.object({ value: z.string() });
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { App, PAGES } from "./App.tsx";
import { BRIEF, ISLAND, PAPER, ROUTES, RUN, STORM, REVISION, SELECTED, DESELECTED, fakeServer, signIn } from "./test/server.ts";

import { ApiContext } from "./api/context.tsx";
import { createClient } from "./api/client.ts";
import { useGet } from "./api/useGet.ts";
import type { ReactNode } from "react";

const AGENT_PROMPT = "Read one paper. Ask what would change your mind.";

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.useRealTimers();
});

async function openAgentControls() {
  const summary = await screen.findByText("Agents and evolution", { selector: "summary" });
  if (!summary.closest("details")?.open) fireEvent.click(summary);
}

function open(path: string, routes: Record<string, unknown> = ROUTES) {
  window.history.pushState({}, "", path);
  const server = fakeServer(routes);
  render(<App fetch={server.fetch} />);
  return server;
}

test("the app serves the public splash, the sign-in and the four pages behind it, and nothing else", () => {
  expect(PAGES.map((p) => p.family).sort()).toEqual(["chat", "island", "login", "paper", "run", "splash"]);
  expect(PAGES.filter((p) => p.open).map((p) => p.path).sort()).toEqual(["/", "/login"]);
});

test("the splash needs no session and reads only the public routes", async () => {
  const server = open("/");
  expect(await screen.findByText("enter CS island")).toBeTruthy();
  expect(screen.getByRole("status").textContent).toContain("$50 month");
  await waitFor(() => expect(server.calls.length).toBe(3));
  expect(server.calls.map((c) => c.path).sort()).toEqual(["/api/v1/public/activity?after=0&limit=60", "/api/v1/public/brief?include=grade,numbers,papers,agents&limit=100", "/api/v1/public/storm"]);
  expect(server.calls.every((c) => c.headers["Authorization"] === undefined)).toBe(true);
});

test("the splash counts a current reading from the requested agents section", async () => {
  const routes = {
    ...ROUTES,
    "GET /api/v1/public/brief?include=grade,numbers,papers,agents&limit=100": {
      ...BRIEF,
      agents: (BRIEF.agents ?? []).map((agent) => ({
        ...agent,
        reading_now: { run_id: "R-live", paper_id: "2610.00001", paper_title: "Sparse routing for reading swarms" },
      })),
    },
  };
  open("/", routes);
  await waitFor(() => expect(screen.getByText(/reading now/).textContent).toBe("1 reading now"));
});

test("the splash gives the grade and says what would raise it, and no more", async () => {
  open("/");
  await waitFor(() => expect(document.querySelector(".grade .letter")?.textContent).toBe("D"));
  expect(screen.getByText(/1 reading so far/)).toBeTruthy();
  expect(screen.getByText(/people need to like what they/)).toBeTruthy();
  expect(screen.getByText("skill for agents").getAttribute("href")).toBe("/skill.md");
  // The claims and paper lists stay in the public brief, not on the splash.
  expect(screen.queryByText("Routing halves cost.")).toBeNull();
  expect(screen.queryByText("An unread paper")).toBeNull();
});

test("a server without the brief or the feed still shows the splash, with no error and no feed status", async () => {
  const routes = { ...ROUTES };
  delete routes["GET /api/v1/public/brief?include=grade,numbers,papers,agents&limit=100"];
  delete routes["GET /api/v1/public/activity?after=0&limit=60"];
  open("/", routes);
  expect(await screen.findByText("enter CS island")).toBeTruthy();
  // No error box for a server that has no brief yet: the page simply stops at the counts.
  expect(screen.queryByRole("alert")).toBeNull();
  // The legend says what the marks are; it does not narrate the feed.
  expect(document.querySelector(".legend")?.textContent).not.toMatch(/live|feed|steps/);
});

test("the budget strip states the month, projection and mode the server sends", async () => {
  const budget = { mode: "conserving", target_micros: 50_000_000, month_to_date_micros: 41_200_000, projected_month_micros: 63_000_000 };
  open("/", { ...ROUTES, "GET /api/v1/public/storm": { ...STORM, budget } });
  await screen.findByText("enter CS island");
  expect(screen.getByRole("status").textContent).toContain("$41.20 / $50 month · projected $63 · conserving");
});

test("a page behind the sign-in sends a visitor without a session to sign in and reads nothing of it", async () => {
  const server = open("/runs/R-1");
  expect(await screen.findByText("Enter an island")).toBeTruthy();
  expect(window.location.pathname).toBe("/login");
  expect(new URLSearchParams(window.location.search).get("next")).toBe("/runs/R-1");
  expect(server.calls.some((c) => c.path.includes("/runs/"))).toBe(false);
});

test("an island page asked for without a session offers that island at sign-in, whatever the case of the address", async () => {
  const server = open("/Islands/cs");
  expect(await screen.findByText("Enter an island")).toBeTruthy();
  expect(new URLSearchParams(window.location.search).get("island")).toBe("cs");
  expect(server.calls.some((c) => c.path.includes("/islands/"))).toBe(false);
});

test("signing in with the island's code opens the page that was asked for, fragment and all", async () => {
  const server = open("/login?next=%2Fislands%2Fcs%23agent-cs-reader&island=cs");
  fireEvent.change(await screen.findByLabelText("Access code"), { target: { value: "open sesame" } });
  fireEvent.click(screen.getByDisplayValue("enter"));
  expect(await screen.findByRole("heading", { level: 1, name: "CS island" })).toBeTruthy();
  expect(window.location.pathname + window.location.hash).toBe("/islands/cs#agent-cs-reader");
  expect(server.calls.find((c) => c.method === "POST")?.body).toEqual({ island: "cs", password: "open sesame" });
});

test("sign-in posts only an island that exists and returns only to a page of this app", async () => {
  const server = open("/login?island=Cs&next=%2F%5Cevil.example");
  fireEvent.click(await screen.findByDisplayValue("enter"));
  expect(await screen.findByRole("heading", { level: 1, name: "CS island" })).toBeTruthy();
  // "Cs" names no island, so the first listed one is offered and sent.
  expect(server.calls.find((c) => c.method === "POST")?.body).toMatchObject({ island: "cs" });
  expect(window.location.pathname).toBe("/islands/cs");
});

test("the island page shows its cost, its budget share and its runs left today", async () => {
  signIn();
  open("/islands/cs", { ...ROUTES, "GET /api/v1/islands/cs": { ...ISLAND, budget_share: 0.4, runs_remaining_today: 12 } });
  await screen.findByRole("heading", { level: 1, name: "CS island" });
  expect(screen.getByText("island cost").parentElement?.textContent).toContain("$0.005");
  expect(screen.getByText("budget share").parentElement?.textContent).toContain("40%");
  expect(screen.getByText("runs left today").parentElement?.textContent).toContain("12");
});

test("the island shows papers and current runs before agent and evolution configuration", async () => {
  signIn();
  open("/islands/cs", { ...ROUTES, "GET /api/v1/islands/cs": { ...ISLAND, runs: [{ ...RUN.run, status: "running" }] } });
  const papers = await screen.findByRole("heading", { level: 2, name: "papers" });
  const runs = screen.getByRole("heading", { level: 2, name: "runs" });
  const evolution = screen.getByText("Agents and evolution", { selector: "summary" });
  expect(papers.compareDocumentPosition(runs) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(runs.compareDocumentPosition(evolution) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.getByText("running").closest("tr")?.textContent).toContain("cs-reader");
  expect(screen.getAllByRole("link", { name: PAPER.paper.title }).map((link) => link.getAttribute("href"))).toEqual(["/papers/2610.00001", "/papers/2610.00001"]);
  expect(screen.getByRole("link", { name: "cs-reader" }).getAttribute("href")).toBe("/runs/R-1");
});

test.each([
  { unavailable: [], paperMessage: "No paper has reached this island yet.", runMessage: "No agent has run on this island yet." },
  { unavailable: ["papers", "runs"], paperMessage: "The island's papers are unavailable.", runMessage: "The island's runs are unavailable." },
])("empty island output distinguishes unavailable groups $unavailable before configuration", async ({ unavailable, paperMessage, runMessage }) => {
  signIn();
  open("/islands/cs", { ...ROUTES, "GET /api/v1/islands/cs": { ...ISLAND, papers: [], runs: [], unavailable } });
  const papers = await screen.findByText(paperMessage);
  const runs = screen.getByText(runMessage);
  const evolution = screen.getByText("Agents and evolution", { selector: "summary" });
  expect(papers.compareDocumentPosition(evolution) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(runs.compareDocumentPosition(evolution) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  if (unavailable.length > 0) {
    expect(screen.queryByText("No paper has reached this island yet.")).toBeNull();
    expect(screen.queryByText("No agent has run on this island yet.")).toBeNull();
  }
});

test("what the server leaves out reads as not reported, and what it could not read is named", async () => {
  signIn();
  open("/islands/cs", { ...ROUTES, "GET /api/v1/islands/cs": { ...ISLAND, cost_micros: null, queue: null, unavailable: ["runs"] } });
  await screen.findByRole("heading", { level: 1, name: "CS island" });
  expect(screen.getByText("island cost").parentElement?.textContent).toContain("not reported");
  expect(screen.getByText("runs left today").parentElement?.textContent).toContain("not reported");
  expect(screen.getByText("papers waiting").parentElement?.textContent).toContain("not reported");
  expect(screen.getByRole("alert").textContent).toContain("Some island data is unavailable: runs.");
});

test("a session for another island reads the island but is offered no way to change it", async () => {
  signIn("bio");
  open("/islands/cs");
  await openAgentControls();
  await screen.findByRole("heading", { level: 1, name: "CS island" });
  expect(screen.getByText(AGENT_PROMPT)).toBeTruthy();
  expect(screen.queryByRole("button", { name: "edit this agent" })).toBeNull();
  expect((screen.getByRole("switch", { name: "evolution" }) as HTMLButtonElement).disabled).toBe(true);
});
test("editing an agent sends its prompt and tools as a new version and reads the island again", async () => {
  signIn();
  const server = open("/islands/cs", { ...ROUTES, "POST /api/v1/genomes": REVISION });
  await openAgentControls();
  fireEvent.click(await screen.findByRole("button", { name: "edit this agent" }));
  const save = screen.getByRole("button", { name: "save as a new version" }) as HTMLButtonElement;
  expect(save.disabled).toBe(true);
  fireEvent.change(screen.getByLabelText("Prompt"), { target: { value: "Read one paper. Name the weakest claim." } });
  fireEvent.click(screen.getByLabelText("submit_reading"));
  fireEvent.click(save);
  await waitFor(() => expect(server.calls.some((c) => c.method === "POST")).toBe(true));
  expect(server.calls.find((c) => c.method === "POST")).toMatchObject({
    path: "/api/v1/genomes",
    body: { island_id: "cs", parent_id: "cs-reader", prompt: "Read one paper. Name the weakest claim.", tools: "paper_text" },
  });
  await waitFor(() => expect(server.calls.filter((c) => c.path === "/api/v1/islands/cs")).toHaveLength(2));
});
test("an edit the server refuses says nothing was saved, gives the reason and keeps the text", async () => {
  signIn();
  const refused = new Response(JSON.stringify({ detail: "prompt is text of at most 4000 characters", code: "invalid_request" }), { status: 422 });
  open("/islands/cs", { ...ROUTES, "POST /api/v1/genomes": refused });
  await openAgentControls();
  fireEvent.click(await screen.findByRole("button", { name: "edit this agent" }));
  fireEvent.change(screen.getByLabelText("Prompt"), { target: { value: "Read one paper twice." } });
  fireEvent.click(screen.getByRole("button", { name: "save as a new version" }));
  expect((await screen.findByRole("alert")).textContent).toBe("Nothing was saved. prompt is text of at most 4000 characters");
  expect((screen.getByLabelText("Prompt") as HTMLTextAreaElement).value).toBe("Read one paper twice.");
});
test("an accepted edit without its revision reports a contract error and retains the form", async () => {
  signIn();
  const server = open("/islands/cs", { ...ROUTES, "POST /api/v1/genomes": new Response(null, { status: 204 }) });
  await openAgentControls();
  fireEvent.click(await screen.findByRole("button", { name: "edit this agent" }));
  fireEvent.change(screen.getByLabelText("Prompt"), { target: { value: "Read one paper slowly." } });
  fireEvent.click(screen.getByRole("button", { name: "save as a new version" }));
  expect((await screen.findByRole("alert")).textContent).toContain("the server's answer did not match its contract");
  expect((screen.getByLabelText("Prompt") as HTMLTextAreaElement).value).toBe("Read one paper slowly.");
  expect(server.calls.filter((c) => c.path === "/api/v1/islands/cs")).toHaveLength(1);
});
test("re-reading the island after a save keeps the page on screen", async () => {
  signIn();
  let release: (value: Response) => void = () => {};
  const held = new Promise<Response>((resolve) => (release = resolve));
  const server = fakeServer({ ...ROUTES, "POST /api/v1/genomes": REVISION });
  let islandReads = 0;
  const slowSecondRead = ((input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input) === "/api/v1/islands/cs" && !init?.body && ++islandReads === 2) return held;
    return server.fetch(input, init);
  }) as typeof fetch;
  window.history.pushState({}, "", "/islands/cs");
  render(<App fetch={slowSecondRead} />);
  await openAgentControls();
  fireEvent.click(await screen.findByRole("button", { name: "edit this agent" }));
  fireEvent.change(screen.getByLabelText("Prompt"), { target: { value: "Read one paper slowly." } });
  fireEvent.click(screen.getByRole("button", { name: "save as a new version" }));
  await waitFor(() => expect(islandReads).toBe(2));
  // The second read has not answered yet: the island is still shown, not a wait message.
  expect(screen.getByRole("heading", { level: 1, name: "CS island" })).toBeTruthy();
  expect(screen.queryByText("Reading The island…")).toBeNull();
  release(new Response(JSON.stringify(ISLAND), { status: 200 }));
  expect(await screen.findByRole("button", { name: "edit this agent" })).toBeTruthy();
});
test("a link to one agent lands on that agent once the island is read", async () => {
  signIn();
  const landed: string[] = [];
  Element.prototype.scrollIntoView = function (this: Element) {
    landed.push(this.id);
  };
  open("/islands/cs#agent-cs-reader");
  await openAgentControls();
  await screen.findByRole("button", { name: "edit this agent" });
  await waitFor(() => expect(landed).toEqual(["agent-cs-reader"]));
});
test("an agent at work links to the run it is on, to be watched", async () => {
  signIn();
  const working = { ...ISLAND.agents[0], state: "working", current: { run_id: "R-9", paper_id: "2610.00001", paper_title: "Sparse routing for reading swarms", status: "running" } };
  open("/islands/cs", { ...ROUTES, "GET /api/v1/islands/cs": { ...ISLAND, agents: [working] } });
  await openAgentControls();
  const watch = await screen.findByRole("link", { name: "Sparse routing for reading swarms · watch" });
  expect(watch.getAttribute("href")).toBe("/runs/R-9");
});
test("each switch sends its own flip to the server and shows what the server then stores", async () => {
  signIn();
  const server = fakeServer({ ...ROUTES, "POST /api/v1/islands/cs/settings": REVISION });
  const stored = { evolution_enabled: true, mutation_enabled: true };
  const doFetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input) === "/api/v1/islands/cs/settings") Object.assign(stored, JSON.parse(String(init?.body)));
    if (String(input) === "/api/v1/islands/cs") return Promise.resolve(new Response(JSON.stringify({ ...ISLAND, ...stored }), { status: 200 }));
    return server.fetch(input, init);
  }) as typeof fetch;
  window.history.pushState({}, "", "/islands/cs");
  render(<App fetch={doFetch} />);
  await openAgentControls();
  fireEvent.click(await screen.findByRole("switch", { name: "mutation" }));
  await waitFor(() => expect(screen.getByRole("switch", { name: "mutation" }).getAttribute("aria-checked")).toBe("false"));
  // Mutation went off alone; evolution was not touched.
  expect(server.calls.filter((c) => c.method === "POST").map((c) => c.body)).toEqual([{ mutation_enabled: false }]);
  expect(screen.getByRole("switch", { name: "evolution" }).getAttribute("aria-checked")).toBe("true");
  fireEvent.click(screen.getByRole("switch", { name: "evolution" }));
  await waitFor(() => expect(screen.getByRole("switch", { name: "evolution" }).getAttribute("aria-checked")).toBe("false"));
  expect(server.calls.filter((c) => c.method === "POST").map((c) => c.body)).toEqual([{ mutation_enabled: false }, { evolution_enabled: false }]);
  // With evolution off, mutation would change nothing, so it cannot be flipped.
  expect((screen.getByRole("switch", { name: "mutation" }) as HTMLButtonElement).disabled).toBe(true);
});
test("a switch flip the server refuses leaves the switch as it was and says nothing changed", async () => {
  signIn();
  const refused = new Response(JSON.stringify({ detail: "a session writes to its own island" }), { status: 403 });
  open("/islands/cs", { ...ROUTES, "POST /api/v1/islands/cs/settings": refused });
  await openAgentControls();
  fireEvent.click(await screen.findByRole("switch", { name: "evolution" }));
  expect((await screen.findByRole("alert")).textContent).toBe("Nothing changed. a session writes to its own island");
  expect(screen.getByRole("switch", { name: "evolution" }).getAttribute("aria-checked")).toBe("true");
});
test("the island's switch says when the operator has evolution off for the whole swarm", async () => {
  signIn();
  open("/islands/cs", { ...ROUTES, "GET /api/v1/islands/cs": { ...ISLAND, swarm_evolution_enabled: false } });
  await openAgentControls();
  expect(await screen.findByText("off for the whole swarm by the operator; this switch takes effect once that is on")).toBeTruthy();
});
test("a server that does not report the switches shows them as not reported", async () => {
  signIn();
  open("/islands/cs", { ...ROUTES, "GET /api/v1/islands/cs": { ...ISLAND, evolution_enabled: null, mutation_enabled: null } });
  await openAgentControls();
  expect(await screen.findByText("evolution · not reported")).toBeTruthy();
  expect(screen.getByText("mutation · not reported")).toBeTruthy();
});
test("moving between pages keeps one client: a page's data is read once", async () => {
  signIn();
  const server = open("/islands/cs");
  fireEvent.click(await screen.findByRole("link", { name: "chat" }));
  await screen.findByText("chat with the swarm");
  // The island page read it once and the chat page's tree reads it once more; no repeats.
  await waitFor(() => expect(server.calls.filter((c) => c.path === "/api/v1/islands/cs")).toHaveLength(2));
});

test("the paper page shows each island's cost, and an island the breakdown leaves out is not shown as zero", async () => {
  signIn();
  open("/papers/2610.00001", { ...ROUTES, "GET /api/v1/papers/2610.00001": { ...PAPER, runs: [RUN.run], readings: [RUN.reading], cost_by_island: { bio: 100 } } });
  const row = (await screen.findByText("category:cs.AI")).closest("tr");
  expect(row?.textContent).toContain("not reported");
  expect(row?.textContent).not.toContain("$0.00");
  expect(screen.getByText("Routing halves cost.")).toBeTruthy();
});

test("the paper title leads into visible reading content before metadata and run diagnostics", async () => {
  signIn();
  const server = open("/papers/2610.00001", { ...ROUTES, "GET /api/v1/papers/2610.00001": { ...PAPER, runs: [RUN.run], readings: [RUN.reading] } });
  const claim = await screen.findByText("Routing halves cost.");
  const title = screen.getByRole("heading", { level: 1, name: PAPER.paper.title });
  const summary = screen.getByText("Routing by island helps.");
  expect(summary.closest("details:not([open])")).toBeNull();
  expect(claim.closest("details:not([open])")).toBeNull();
  expect(title.compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  for (const diagnostic of [screen.getByText(/cs.AI · fetched/), screen.getByText("paper cost"), screen.getByRole("heading", { level: 2, name: "islands" }), screen.getByRole("heading", { level: 2, name: "runs" })]) {
    expect(claim.compareDocumentPosition(diagnostic) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  }
  expect(screen.getByRole("button", { name: "like this reading" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "like this claim" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "like this idea" })).toBeTruthy();
  expect(screen.getByRole("link", { name: "reading by cs-reader" }).getAttribute("href")).toBe("/runs/R-1");
  const branch = screen.getByRole("link", { name: "agent cs-reader" }).closest("summary");
  if (branch === null) throw new Error("The run has no expandable step branch.");
  fireEvent.click(branch);
  const step = await screen.findByRole("link", { name: /What did routing change/ });
  expect(step.getAttribute("href")).toBe("/runs/R-1?step=2");
  expect(server.calls.filter((call) => call.path === "/api/v1/runs/R-1")).toHaveLength(1);
});

test("a submitted reading remains visible when its run is outside the paper's run window", async () => {
  signIn();
  open("/papers/2610.00001", { ...ROUTES, "GET /api/v1/papers/2610.00001": { ...PAPER, readings: [RUN.reading] } });
  expect(await screen.findByText("Routing by island helps.")).toBeTruthy();
  expect(screen.getByRole("link", { name: "reading by cs-reader" }).getAttribute("href")).toBe("/runs/R-1");
});

test.each([
  { readings: [], unavailable: [], message: "No reading has been submitted for this paper yet." },
  { readings: [], unavailable: ["readings"], message: "The paper's readings are unavailable." },
  { readings: null, unavailable: [], message: "The paper's readings are unavailable." },
])("the paper leads with an explicit reading state for $message", async ({ readings, unavailable, message }) => {
  signIn();
  open("/papers/2610.00001", { ...ROUTES, "GET /api/v1/papers/2610.00001": { ...PAPER, readings, unavailable } });
  const state = await screen.findByText(message);
  expect(state.compareDocumentPosition(screen.getByText(/cs.AI · fetched/)) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(state.compareDocumentPosition(screen.getByText("paper cost")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  if (message.includes("unavailable")) expect(screen.queryByText("No reading has been submitted for this paper yet.")).toBeNull();
});

test("an address with a malformed escape still leads somewhere, not to a blank page", async () => {
  open("/islands/%ZZ");
  expect(await screen.findByText("Enter an island")).toBeTruthy();
});

test("an agent edited by hand is a new version of itself, not a child in the island's evolution", async () => {
  signIn();
  const edited = { ...ISLAND.agents[0], version: 2, parent_id: "cs-reader" };
  open("/islands/cs", { ...ROUTES, "GET /api/v1/islands/cs": { ...ISLAND, agents: [edited] } });
  await openAgentControls();
  await screen.findByRole("heading", { level: 1, name: "CS island" });
  expect(document.querySelector(".genome .meta")?.textContent).toContain("version 2 · generation 0 · edited");
  expect(screen.queryByText(/No evolution yet|Skipped cycles|Decision history/)).toBeNull();
});
test("paper selection can be reversed after deselection removes it from the island list", async () => {
  signIn();
  const assignment = { ...PAPER.assignments[0], kept: true, released: false, selected_by: "island:cs" };
  const routes = { ...ROUTES, "GET /api/v1/papers/2610.00001": { ...PAPER, assignments: [assignment] }, "GET /api/v1/islands/cs": { ...ISLAND, papers: [] }, "POST /api/v1/papers/2610.00001/deselect": DESELECTED, "POST /api/v1/papers/2610.00001/select": SELECTED };
  const server = fakeServer(routes);
  const doFetch: typeof fetch = (input, init) => {
    if (init?.method === "POST") {
      assignment.released = String(input).endsWith("/deselect");
      assignment.kept = !assignment.released;
    }
    return server.fetch(input, init);
  };
  window.history.pushState({}, "", "/papers/2610.00001");
  render(<App fetch={doFetch} />);
  fireEvent.click(await screen.findByRole("button", { name: "deselect" }));
  fireEvent.click(await screen.findByRole("button", { name: "select" }));
  expect(await screen.findByRole("button", { name: "deselect" })).toBeTruthy();
  expect(server.calls.filter((call) => call.method === "POST").map((call) => call.path)).toEqual(["/api/v1/papers/2610.00001/deselect", "/api/v1/papers/2610.00001/select"]);
  expect(server.calls.some((call) => call.path === "/api/v1/islands/cs")).toBe(false);
});

test("another island's page offers no way to let its papers go", async () => {
  signIn("bio");
  open("/islands/cs");
  await screen.findByRole("heading", { level: 1, name: "CS island" });
  expect(screen.queryByRole("button", { name: "deselect" })).toBeNull();
  expect(screen.queryByRole("button", { name: "select" })).toBeNull();
});

test("a like on a paper is one press, counted for every island, and a second press takes it back", async () => {
  signIn();
  const server = open("/papers/2610.00001", { ...ROUTES, "POST /api/v1/likes": { like: { target_kind: "paper", target_id: "2610.00001", island_id: "cs", liked: true, count: 3 } } });
  const button = await screen.findByRole("button", { name: "like this paper" });
  expect(button.textContent).toContain("2");
  fireEvent.click(button);
  await waitFor(() => expect(screen.getByRole("button", { name: /take back the like on this paper/ }).textContent).toContain("3"));
  expect(server.calls.find((c) => c.method === "POST")?.body).toEqual({ target_kind: "paper", target_id: "2610.00001" });
});

test("the run page offers a like on the run, the reading, each claim and each idea", async () => {
  signIn();
  open("/runs/R-1");
  expect(await screen.findByRole("button", { name: "like this run" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "like this reading" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "like this claim" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "like this idea" })).toBeTruthy();
});


test("the globe feed retries an initial outage and stops polling when the page closes", async () => {
  vi.useFakeTimers();
  window.history.pushState({}, "", "/");
  const server = fakeServer(ROUTES);
  let attempts = 0;
  const fetch: typeof globalThis.fetch = async (input, init) => {
    if (String(input).includes("/public/activity")) {
      attempts += 1;
      if (attempts === 1) throw new Error("temporary outage");
    }
    return server.fetch(input, init);
  };
  let view: ReturnType<typeof render> | undefined;
  await act(async () => { view = render(<App fetch={fetch} />); });
  expect(attempts).toBe(1);
  await act(async () => { await vi.advanceTimersByTimeAsync(12_000); });
  expect(attempts).toBe(2);
  view?.unmount();
  await vi.advanceTimersByTimeAsync(30_000);
  expect(attempts).toBe(2);
});

test("the splash refreshes the live budget and grade without reopening the page", async () => {
  vi.useFakeTimers();
  const routes = { ...ROUTES };
  await act(async () => { open("/", routes); });
  routes["GET /api/v1/public/storm"] = {
    ...STORM,
    budget: { mode: "normal", target_micros: 50_000_000, month_to_date_micros: 2_000_000, projected_month_micros: 30_000_000 },
  };
  routes["GET /api/v1/public/brief?include=grade,numbers,papers,agents&limit=100"] = {
    ...BRIEF, grade: { ...BRIEF.grade, letter: "B" },
  };
  await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
  expect(screen.getByRole("status").textContent).toContain("$2.00 / $50 month");
  expect(document.querySelector(".grade .letter")?.textContent).toBe("B");
});


test("a failed splash refresh preserves its budget, grade and readers until the next successful refresh", async () => {
  vi.useFakeTimers();
  const briefPath = "GET /api/v1/public/brief?include=grade,numbers,papers,agents&limit=100";
  const routes: Record<string, unknown> = {
    ...ROUTES,
    [briefPath]: {
      ...BRIEF,
      agents: (BRIEF.agents ?? []).map((agent) => ({ ...agent, reading_now: { run_id: "R-live", paper_id: "2610.00001", paper_title: PAPER.paper.title } })),
    },
  };
  await act(async () => { open("/", routes); });
  expect(screen.getByText(/reading now/).textContent).toBe("1 reading now");
  expect(document.querySelector(".grade .letter")?.textContent).toBe("D");
  expect(screen.getByRole("status").textContent).toContain("$50 month");
  routes[briefPath] = new Response("unavailable", { status: 503 });
  routes["GET /api/v1/public/storm"] = new Response("unavailable", { status: 503 });
  await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
  expect(screen.getByText(/reading now/).textContent).toBe("1 reading now");
  expect(document.querySelector(".grade .letter")?.textContent).toBe("D");
  expect(screen.getByRole("status").textContent).toContain("$50 month");
  expect(screen.getByText("enter CS island")).toBeTruthy();
  routes[briefPath] = { ...BRIEF, grade: { ...BRIEF.grade, letter: "B" } };
  routes["GET /api/v1/public/storm"] = STORM;
  await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
  expect(screen.getByText(/reading now/).textContent).toBe("0 reading now");
  expect(document.querySelector(".grade .letter")?.textContent).toBe("B");
});

test("a GET with no previous answer reports failure and can retry", async () => {
  const routes: Record<string, unknown> = {};
  const api = createClient({ origin: "", fetch: fakeServer(routes).fetch });
  const wrapper = ({ children }: { children: ReactNode }) => <ApiContext.Provider value={api}>{children}</ApiContext.Provider>;
  const { result } = renderHook(() => useGet("/first", valueSchema), { wrapper });
  await waitFor(() => expect(result.current.state).toBe("failed"));
  routes["GET /first"] = { value: "recovered" };
  act(() => result.current.reload());
  await waitFor(() => expect(result.current).toMatchObject({ state: "ready", data: { value: "recovered" } }));
});

test("a changed GET path does not preserve the previous path's answer on failure", async () => {
  const api = createClient({ origin: "", fetch: fakeServer({ "GET /first": { value: "first" } }).fetch });
  const wrapper = ({ children }: { children: ReactNode }) => <ApiContext.Provider value={api}>{children}</ApiContext.Provider>;
  const { result, rerender } = renderHook(({ path }) => useGet(path, valueSchema), { initialProps: { path: "/first" }, wrapper });
  await waitFor(() => expect(result.current).toMatchObject({ state: "ready", data: { value: "first" } }));
  rerender({ path: "/second" });
  await waitFor(() => expect(result.current.state).toBe("failed"));
  expect("data" in result.current).toBe(false);
});

test("a superseded GET answer cannot replace the current path and disposal ignores pending failures", async () => {
  let finishFirst: (value: Response) => void = () => { throw new Error("first request did not start"); };
  let failLast: (reason: unknown) => void = () => { throw new Error("last request did not start"); };
  const fetch: typeof globalThis.fetch = (input) => {
    if (String(input) === "/first") return new Promise<Response>((resolve) => { finishFirst = resolve; });
    if (String(input) === "/last") return new Promise<Response>((_, reject) => { failLast = reject; });
    return Promise.resolve(new Response(JSON.stringify({ value: "second" })));
  };
  const api = createClient({ origin: "", fetch });
  const wrapper = ({ children }: { children: ReactNode }) => <ApiContext.Provider value={api}>{children}</ApiContext.Provider>;
  const { result, rerender, unmount } = renderHook(({ path }) => useGet(path, valueSchema), { initialProps: { path: "/first" }, wrapper });
  rerender({ path: "/second" });
  await waitFor(() => expect(result.current).toMatchObject({ state: "ready", data: { value: "second" } }));
  await act(async () => { finishFirst(new Response(JSON.stringify({ value: "first" }))); });
  expect(result.current).toMatchObject({ state: "ready", data: { value: "second" } });
  rerender({ path: "/last" });
  expect(result.current.state).toBe("loading");
  unmount();
  await act(async () => { failLast(new Error("disconnected")); });
  expect(result.current.state).toBe("loading");
});


test.each([403, 404])("a GET refresh rejected with %i clears the previous answer", async (status) => {
  const routes: Record<string, unknown> = { "GET /paper": { value: "previous" } };
  const api = createClient({ origin: "", fetch: fakeServer(routes).fetch });
  const wrapper = ({ children }: { children: ReactNode }) => <ApiContext.Provider value={api}>{children}</ApiContext.Provider>;
  const { result } = renderHook(() => useGet("/paper", valueSchema), { wrapper });
  await waitFor(() => expect(result.current.state).toBe("ready"));
  routes["GET /paper"] = new Response("rejected", { status });
  act(() => result.current.reload());
  await waitFor(() => expect(result.current.state).toBe("failed"));
  expect("data" in result.current).toBe(false);
});

test.each([408, 429, 503, 200, "network"])("a temporarily failed GET refresh (%s) retains the previous answer", async (failure) => {
  let refreshing = false;
  const fetch: typeof globalThis.fetch = () => {
    if (!refreshing) return Promise.resolve(new Response(JSON.stringify({ value: "previous" })));
    if (typeof failure === "string") return Promise.reject(new TypeError("Failed to fetch"));
    return Promise.resolve(new Response("unreadable", { status: failure }));
  };
  const api = createClient({ origin: "", fetch });
  const wrapper = ({ children }: { children: ReactNode }) => <ApiContext.Provider value={api}>{children}</ApiContext.Provider>;
  const { result } = renderHook(() => useGet("/paper", valueSchema), { wrapper });
  await waitFor(() => expect(result.current.state).toBe("ready"));
  refreshing = true;
  await act(async () => { result.current.reload(); });
  expect(result.current).toMatchObject({ state: "ready", data: { value: "previous" } });
});

test("the selected evolution agent archives and restores through the authenticated owner route", async () => {
  signIn();
  const server = open("/islands/cs", { ...ROUTES, "POST /api/v1/agents/cs-reader": REVISION });
  await openAgentControls();
  fireEvent.click(await screen.findByRole("button", { name: "archive" }));
  await waitFor(() => expect(server.calls.some((call) => call.method === "POST")).toBe(true));
  expect(server.calls.find((call) => call.method === "POST")?.body).toEqual({ fields: { active: false } });
  expect(server.calls.find((call) => call.method === "POST")?.headers.Authorization).toBe("Bearer t-cs");
  cleanup();
  const archived = open("/islands/cs", { ...ROUTES, "GET /api/v1/islands/cs": { ...ISLAND, agents: ISLAND.agents.map((agent) => ({ ...agent, active: false })) }, "POST /api/v1/agents/cs-reader": REVISION });
  await openAgentControls();
  fireEvent.click(await screen.findByRole("button", { name: "bring back" }));
  await waitFor(() => expect(archived.calls.some((call) => call.method === "POST")).toBe(true));
  expect(archived.calls.find((call) => call.method === "POST")?.body).toEqual({ fields: { active: true } });
});
test("a refused archival leaves the selected agent active and reports the refusal", async () => {
  signIn();
  open("/islands/cs");
  await openAgentControls();
  fireEvent.click(await screen.findByRole("button", { name: "archive" }));
  expect(await screen.findByText(/Nothing changed/)).toBeTruthy();
  expect(screen.getByRole("button", { name: "archive" })).toBeTruthy();
  expect(document.querySelectorAll(".genome")).toHaveLength(1);
});
test("same-island hash navigation selects the referenced agent detail", async () => {
  signIn();
  const child = { ...ISLAND.agents[0], id: "cs-child", parent_id: "cs-reader", prompt: "Child research method" };
  open("/islands/cs", { ...ROUTES, "GET /api/v1/islands/cs": { ...ISLAND, agents: [...ISLAND.agents, child] } });
  await screen.findByRole("heading", { name: "CS island" });
  await act(async () => { window.history.pushState({}, "", "/islands/cs#agent-cs-child"); window.dispatchEvent(new PopStateEvent("popstate")); });
  expect(await screen.findByText("Child research method")).toBeTruthy();
  expect(document.querySelectorAll(".genome")).toHaveLength(1);
});


test("unavailable agent data is not presented as an empty population", async () => {
  signIn();
  open("/islands/cs", { ...ROUTES, "GET /api/v1/islands/cs": { ...ISLAND, agents: [], unavailable: ["agents"] } });
  await openAgentControls();
  expect(await screen.findByText("The island's agents are unavailable.")).toBeTruthy();
  expect(screen.queryByText("This island has no agent yet.")).toBeNull();
  expect(screen.queryByRole("searchbox")).toBeNull();
});

test.each(["cs", "bio"])("selected papers lead the island once for a %s session while controls stay closed", async (session) => {
  signIn(session);
  open("/islands/cs", { ...ROUTES, "GET /api/v1/islands/cs": { ...ISLAND, runs: [], papers: [{ ...PAPER.paper, kept: true, selected_by: "readers" }, { ...PAPER.paper, id: "other", title: "Another paper", kept: false }] } });
  const selected = await screen.findByRole("heading", { name: "selected papers" });
  const papers = screen.getByRole("heading", { name: "papers" });
  const link = screen.getByRole("link", { name: PAPER.paper.title });
  expect(selected.compareDocumentPosition(link) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(link.compareDocumentPosition(papers) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.getByText(/selected by agents/)).toBeTruthy();
  expect(screen.getByText("Agents and evolution", { selector: "summary" }).closest("details")?.open).toBe(false);
  if (session === "cs") expect(screen.getByRole("button", { name: "edit this agent" }).closest("details:not([open])")).not.toBeNull();
  expect(screen.queryByRole("button", { name: "select" })).toBeNull();
  expect(screen.queryByText(/Skipped cycles|Decision history/)).toBeNull();
});

test("paper selection uses the signed-in island assignment rather than another island", async () => {
  signIn();
  const server = open("/papers/2610.00001", { ...ROUTES, "GET /api/v1/papers/2610.00001": { ...PAPER, assignments: [{ ...PAPER.assignments[0], island_id: "bio", kept: true }, { ...PAPER.assignments[0], kept: false }] }, "POST /api/v1/papers/2610.00001/select": SELECTED });
  fireEvent.click(await screen.findByRole("button", { name: "select" }));
  await waitFor(() => expect(server.calls.filter((call) => call.method === "POST").map((call) => call.path)).toEqual(["/api/v1/papers/2610.00001/select"]));
  await waitFor(() => expect(server.calls.filter((call) => call.path === "/api/v1/papers/2610.00001")).toHaveLength(2));
  expect(server.calls.some((call) => call.path === "/api/v1/islands/cs")).toBe(false);
  expect(screen.queryByRole("button", { name: "deselect" })).toBeNull();
});

test.each([
  { assignments: [{ paper_id: PAPER.paper.id, island_id: "cs", reason: "category:cs.AI" }], unavailable: [] },
  { assignments: PAPER.assignments, unavailable: ["assignments"] },
  { assignments: PAPER.assignments.map((assignment) => ({ ...assignment, island_id: "bio" })), unavailable: [] },
])("paper selection does not guess when the own assignment state is unavailable", async ({ assignments, unavailable }) => {
  signIn();
  open("/papers/2610.00001", { ...ROUTES, "GET /api/v1/papers/2610.00001": { ...PAPER, assignments, unavailable } });
  await screen.findByRole("heading", { name: PAPER.paper.title });
  expect(screen.queryByRole("button", { name: "select" })).toBeNull();
  expect(screen.queryByRole("button", { name: "deselect" })).toBeNull();
});

test("an island containing only selected papers does not claim it has received none", async () => {
  signIn();
  open("/islands/cs", { ...ROUTES, "GET /api/v1/islands/cs": { ...ISLAND, papers: [{ ...PAPER.paper, kept: true }] } });
  expect(await screen.findByText("All papers on this island are selected.")).toBeTruthy();
  expect(screen.queryByText("No paper has reached this island yet.")).toBeNull();
});
