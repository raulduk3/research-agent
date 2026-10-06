import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { ApiContext } from "../api/context.tsx";
import { createClient } from "../api/client.ts";
import { MemoryRouter } from "react-router";
import { AGENT, fakeServer } from "../test/server.ts";
import type { Agent } from "../api/types.ts";
import { parentOf } from "./GenomeCard.tsx";
import { EvolutionTree, lineageForest } from "./EvolutionTree.tsx";

afterEach(cleanup);
function show(agents: Agent[]) {
  const server = fakeServer({});
  const api = createClient({ origin: "", fetch: server.fetch });
  const content = (population: Agent[]) => <MemoryRouter><ApiContext.Provider value={api}><EvolutionTree agents={population} /></ApiContext.Provider></MemoryRouter>;
  const view = render(content(agents));
  return (population: Agent[]) => view.rerender(content(population));
}

test("branches collapse, selection replaces the single detail card, and filters retain ancestors", () => {
  show([{ ...AGENT, active: false }, { ...AGENT, id: "child", parent_id: AGENT.id, prompt: "Child method" }]);
  expect(screen.queryByRole("button", { name: "child" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: `Expand descendants of ${AGENT.id}` }));
  fireEvent.click(screen.getByRole("button", { name: "child" }));
  expect(document.querySelectorAll(".genome")).toHaveLength(1);
  expect(screen.getByText("Child method")).toBeTruthy();
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "active" } });
  expect(screen.getByRole("button", { name: AGENT.id })).toBeTruthy();
  expect(screen.getByRole("button", { name: "child" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "archive" })).toBeNull();
});

test("growing populations stay bounded without cycle diagnostics", () => {
  const agents = Array.from({ length: 95 }, (_, i) => ({ ...AGENT, id: `agent-${i}` }));
  show(agents);
  expect(document.querySelectorAll(".evolution-row")).toHaveLength(30);
  expect(screen.queryByText(/Skipped cycles|Decision history/)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "show more agents" }));
  expect(document.querySelectorAll(".evolution-row")).toHaveLength(60);
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "agent-94" } });
  expect(document.querySelectorAll(".evolution-row")).toHaveLength(1);
});

test("missing parents and secondary parents are explicit and self versions stay roots", () => {
  const agents = [{ ...AGENT, parent_id: AGENT.id }, { ...AGENT, id: "orphan", parent_id: "missing", lineage: { parents: ["missing", "external"] } }];
  show(agents);
  expect(screen.getByText(/parent missing unavailable · also from external/)).toBeTruthy();
  expect(lineageForest(agents).get(AGENT.id)?.parent).toBeNull();
});

test("cyclic and very deep lineage is traversable without recursion", () => {
  const cyclic = lineageForest([{ ...AGENT, id: "a", parent_id: "b" }, { ...AGENT, id: "b", parent_id: "a" }]);
  expect([...cyclic.values()].filter((n) => n.parent === null)).toHaveLength(1);
  const agents = Array.from({ length: 10000 }, (_, i) => ({ ...AGENT, id: `deep-${i}`, parent_id: i === 0 ? null : `deep-${i - 1}` }));
  show(agents);
  fireEvent.click(screen.getByRole("button", { name: "expand all" }));
  expect(document.querySelectorAll(".evolution-row")).toHaveLength(30);
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "deep-9999" } });
  expect(screen.getByText("Showing 1 of 1 expanded agents · 10000 agents in matching branches.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "deep-9999" }));
  expect(document.querySelector(".genome")?.id).toBe("agent-deep-9999");
});


test("version edits preserve evolutionary parents when the version parent is self", () => {
  const edited = { ...AGENT, id: "child", parent_id: "child", lineage: { parents: ["founder", "second"], generation: 4 } };
  expect(parentOf(edited)).toBe("founder");
  expect(lineageForest([edited]).get("child")?.otherParents).toEqual(["second"]);
});


test("a removed selected agent falls back to an available detail", () => {
  const replacement = { ...AGENT, id: "replacement", prompt: "Replacement method" };
  const reload = show([AGENT, replacement]);
  reload([replacement]);
  expect(screen.getByText("Replacement method")).toBeTruthy();
  expect(screen.getByRole("button", { name: "replacement" }).getAttribute("aria-pressed")).toBe("true");
  expect(document.querySelectorAll(".genome")).toHaveLength(1);
});


test("an outside descendant encountered before a parent cycle keeps every agent reachable", () => {
  show([{ ...AGENT, id: "outside", parent_id: "a" }, { ...AGENT, id: "a", parent_id: "b" }, { ...AGENT, id: "b", parent_id: "a" }]);
  fireEvent.click(screen.getByRole("button", { name: "expand all" }));
  expect([...document.querySelectorAll(".evolution-row button[aria-pressed]")].map((button) => button.textContent).sort()).toEqual(["a", "b", "outside"]);
});

test("shallow search results show their parent and depth", () => {
  show([AGENT, { ...AGENT, id: "child", parent_id: AGENT.id, prompt: "Child method" }]);
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "child" } });
  expect(screen.getByText("generation 0 · active · from cs-reader · depth 1")).toBeTruthy();
  expect(document.querySelectorAll(".evolution-row")).toHaveLength(1);
});
