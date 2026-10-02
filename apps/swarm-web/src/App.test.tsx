import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { App, PAGES } from "./App.tsx";
import { PAPER, ROUTES, RUN, fakeServer, signIn } from "./test/server.ts";

afterEach(() => {
  cleanup();
  localStorage.clear();
});

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

test("the splash needs no session and reads only the public storm", async () => {
  const server = open("/");
  expect(await screen.findByText("enter CS island")).toBeTruthy();
  expect(screen.getByRole("status").textContent).toContain("$50 month");
  expect(server.calls.map((c) => c.path)).toEqual(["/api/v1/public/storm"]);
  expect(server.calls[0]?.headers["Authorization"]).toBeUndefined();
});

test("a page behind the island sends a visitor without a session to sign in and reads nothing of it", async () => {
  const server = open("/runs/R-1");
  expect(await screen.findByText("Enter an island")).toBeTruthy();
  expect(window.location.pathname).toBe("/login");
  expect(new URLSearchParams(window.location.search).get("next")).toBe("/runs/R-1");
  expect(server.calls.some((c) => c.path.includes("/runs/"))).toBe(false);
});

test("a session for one island does not open another island's page", async () => {
  signIn("bio");
  const server = open("/islands/cs");
  expect(await screen.findByText("Enter an island")).toBeTruthy();
  expect(new URLSearchParams(window.location.search).get("island")).toBe("cs");
  expect(server.calls.some((c) => c.path.includes("/islands/"))).toBe(false);
});

test("signing in with the island's code opens the page that was asked for", async () => {
  const server = open("/login?next=%2Fislands%2Fcs&island=cs");
  fireEvent.change(await screen.findByLabelText("Access code"), { target: { value: "open sesame" } });
  fireEvent.click(screen.getByDisplayValue("enter"));
  expect(await screen.findByRole("heading", { level: 1, name: "CS island" })).toBeTruthy();
  expect(window.location.pathname).toBe("/islands/cs");
  expect(server.calls.find((c) => c.method === "POST")?.body).toEqual({ island: "cs", password: "open sesame" });
});

test("the island page shows its cost and budget share, and says when the day's runs are not reported", async () => {
  signIn();
  open("/islands/cs");
  await screen.findByRole("heading", { level: 1, name: "CS island" });
  expect(screen.getByText("island cost").parentElement?.textContent).toContain("$0.005");
  expect(screen.getByText("budget share").parentElement?.textContent).toContain("0%");
  expect(screen.getByText("runs left today").parentElement?.textContent).toContain("not reported");
  await waitFor(() => expect(screen.getAllByRole("status")[0]?.textContent).toContain("$0.002 recorded in all"));
});

test("editing an agent saves a new version descended from it and leaves the stored one unsent", async () => {
  signIn();
  const server = open("/islands/cs", { ...ROUTES, "POST /api/v1/genomes": { genome_id: "cs-g1" } });
  fireEvent.click(await screen.findByRole("button", { name: "edit this agent" }));
  const save = screen.getByRole("button", { name: "save as a new version" }) as HTMLButtonElement;
  expect(save.disabled).toBe(true);
  fireEvent.change(screen.getByLabelText("Prompt"), { target: { value: "Read one paper. Name the weakest claim." } });
  fireEvent.click(screen.getByLabelText("submit_reading"));
  fireEvent.click(save);
  await waitFor(() => expect(server.calls.some((c) => c.method === "POST")).toBe(true));
  expect(server.calls.find((c) => c.method === "POST")).toMatchObject({
    path: "/api/v1/genomes",
    body: { island_id: "cs", parent_id: "cs-g0", prompt: "Read one paper. Name the weakest claim.", tools: "paper_text" },
  });
  // The island is read again, so the new version shows as the server stored it.
  await waitFor(() => expect(server.calls.filter((c) => c.path === "/api/v1/islands/cs")).toHaveLength(2));
});

test("when the server does not take agent edits, the page says nothing was saved and keeps the text", async () => {
  signIn();
  open("/islands/cs");
  fireEvent.click(await screen.findByRole("button", { name: "edit this agent" }));
  fireEvent.change(screen.getByLabelText("Prompt"), { target: { value: "Read one paper twice." } });
  fireEvent.click(screen.getByRole("button", { name: "save as a new version" }));
  expect((await screen.findByRole("alert")).textContent).toBe("This server does not take agent edits yet. Nothing was saved.");
  expect((screen.getByLabelText("Prompt") as HTMLTextAreaElement).value).toBe("Read one paper twice.");
});

test("a link to one agent lands on that agent once the island is read", async () => {
  signIn();
  const landed: string[] = [];
  Element.prototype.scrollIntoView = function (this: Element) {
    landed.push(this.id);
  };
  open("/islands/cs#agent-cs-g0");
  await screen.findByRole("button", { name: "edit this agent" });
  expect(landed).toEqual(["agent-cs-g0"]);
});

test("the island guard holds whatever the case of the address", async () => {
  signIn("bio");
  const server = open("/Islands/cs");
  expect(await screen.findByText("Enter an island")).toBeTruthy();
  expect(server.calls.some((c) => c.path.includes("/islands/"))).toBe(false);
});

test("a run of another island is shown without reading that island's agents", async () => {
  signIn("bio");
  const server = open("/runs/R-1");
  expect(await screen.findByText("Agent cs-g0 belongs to island cs. Enter that island to see what it was told.")).toBeTruthy();
  expect(server.calls.some((c) => c.path.includes("/islands/"))).toBe(false);
});

test("moving between pages keeps one client: a page's data is read once", async () => {
  signIn();
  const server = open("/islands/cs");
  fireEvent.click(await screen.findByRole("link", { name: "chat" }));
  await screen.findByText("chat with the swarm");
  // The island page read it once and the chat page's tree reads it once more; no repeats.
  await waitFor(() => expect(server.calls.filter((c) => c.path === "/api/v1/islands/cs")).toHaveLength(2));
});

test("an edit the server accepts without a body counts as saved", async () => {
  signIn();
  const server = open("/islands/cs", { ...ROUTES, "POST /api/v1/genomes": new Response(null, { status: 204 }) });
  fireEvent.click(await screen.findByRole("button", { name: "edit this agent" }));
  fireEvent.change(screen.getByLabelText("Prompt"), { target: { value: "Read one paper slowly." } });
  fireEvent.click(screen.getByRole("button", { name: "save as a new version" }));
  await waitFor(() => expect(server.calls.filter((c) => c.path === "/api/v1/islands/cs")).toHaveLength(2));
  expect(screen.queryByRole("alert")).toBeNull();
});

test("an island the cost breakdown leaves out reads as not reported, not as zero", async () => {
  signIn();
  open("/papers/2610.00001", { ...ROUTES, "GET /api/v1/papers/2610.00001": { ...PAPER, runs: [RUN.run], cost_by_island: {} } });
  const row = (await screen.findByText("category:cs.AI")).closest("tr");
  expect(row?.textContent).toContain("not reported");
  expect(row?.textContent).not.toContain("$0.00");
});

test("sign-in posts only an island that exists and returns only to a page of this app", async () => {
  const server = open("/login?island=Cs&next=%2F%5Cevil.example");
  fireEvent.click(await screen.findByDisplayValue("enter"));
  expect(await screen.findByRole("heading", { level: 1, name: "CS island" })).toBeTruthy();
  // "Cs" names no island, so the first listed one is offered and sent.
  expect(server.calls.find((c) => c.method === "POST")?.body).toMatchObject({ island: "cs" });
  expect(window.location.pathname).toBe("/islands/cs");
});

test("an address with a malformed escape is turned away, not a blank page", async () => {
  signIn();
  open("/islands/%ZZ");
  expect(await screen.findByText("Enter an island")).toBeTruthy();
});

test("re-reading the island after a save keeps the page, and an edit open on it, on screen", async () => {
  signIn();
  let release: (value: Response) => void = () => {};
  const held = new Promise<Response>((resolve) => (release = resolve));
  const server = fakeServer({ ...ROUTES, "POST /api/v1/genomes": { genome_id: "cs-g1" } });
  let islandReads = 0;
  const slowSecondRead = ((input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input) === "/api/v1/islands/cs" && ++islandReads === 2) return held;
    return server.fetch(input, init);
  }) as typeof fetch;
  window.history.pushState({}, "", "/islands/cs");
  render(<App fetch={slowSecondRead} />);
  fireEvent.click(await screen.findByRole("button", { name: "edit this agent" }));
  fireEvent.change(screen.getByLabelText("Prompt"), { target: { value: "Read one paper slowly." } });
  fireEvent.click(screen.getByRole("button", { name: "save as a new version" }));
  await waitFor(() => expect(islandReads).toBe(2));
  // The second read has not answered yet: the island is still shown, not a wait message.
  expect(screen.getByRole("heading", { level: 1, name: "CS island" })).toBeTruthy();
  expect(screen.queryByText("Reading The island…")).toBeNull();
  release(new Response(JSON.stringify(ROUTES["GET /api/v1/islands/cs"]), { status: 200 }));
  expect(await screen.findByRole("button", { name: "edit this agent" })).toBeTruthy();
});

test("the evolution switch sends the flip to the server and shows what the server then stores", async () => {
  signIn();
  const island = ROUTES["GET /api/v1/islands/cs"] as Record<string, unknown>;
  const server = fakeServer({ ...ROUTES, "POST /api/v1/islands/cs/settings": {} });
  let on = false;
  const doFetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input) === "/api/v1/islands/cs/settings") on = true;
    if (String(input) === "/api/v1/islands/cs" && !init?.body) {
      void server.fetch(input, init);
      return Promise.resolve(new Response(JSON.stringify({ ...island, evolution_enabled: on, mutation_enabled: false }), { status: 200 }));
    }
    return server.fetch(input, init);
  }) as typeof fetch;
  window.history.pushState({}, "", "/islands/cs");
  render(<App fetch={doFetch} />);
  const evolution = await screen.findByRole("switch", { name: "evolution" });
  expect(evolution.getAttribute("aria-checked")).toBe("false");
  // Mutation changes nothing while evolution is off, so it cannot be flipped.
  expect((screen.getByRole("switch", { name: "mutation" }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(evolution);
  await waitFor(() => expect(screen.getByRole("switch", { name: "evolution" }).getAttribute("aria-checked")).toBe("true"));
  expect(server.calls.find((c) => c.method === "POST")).toMatchObject({ path: "/api/v1/islands/cs/settings", body: { evolution_enabled: true } });
  expect((screen.getByRole("switch", { name: "mutation" }) as HTMLButtonElement).disabled).toBe(false);
});

test("a switch the server does not take stays as it was and says nothing changed", async () => {
  signIn();
  open("/islands/cs");
  const evolution = await screen.findByRole("switch", { name: "evolution" });
  expect(screen.getByText("evolution · not reported")).toBeTruthy();
  fireEvent.click(evolution);
  expect((await screen.findByRole("alert")).textContent).toBe("This server does not take evolution settings yet. Nothing changed.");
  expect(screen.getByRole("switch", { name: "evolution" }).getAttribute("aria-checked")).toBe("false");
});
