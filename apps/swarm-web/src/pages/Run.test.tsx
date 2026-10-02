import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { App } from "../App.tsx";
import type { RunView } from "../api/types.ts";
import { Replay } from "../components/Replay.tsx";
import { PAPER, ROUTES, RUN, fakeServer, signIn } from "../test/server.ts";
import { costGroups } from "./Run.tsx";

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.useRealTimers();
});

async function openRun(routes: Record<string, unknown> = ROUTES, path = "/runs/R-1") {
  signIn();
  window.history.pushState({}, "", path);
  const server = fakeServer(routes);
  render(<App fetch={server.fetch} />);
  await screen.findByText("watch it");
  return server;
}

/** A step state that also records every value it took. */
function useStateSpy(seen: number[]): [number, (step: number) => void] {
  const [step, setStep] = useState(0);
  if (seen.at(-1) !== step) seen.push(step);
  return [step, setStep];
}

const log = () => screen.queryByRole("group", { name: "steps played so far" });

test("the replay starts before the first step, showing the prompt and none of the run's steps", async () => {
  await openRun();
  expect(await screen.findAllByText("Read one paper. Ask what would change your mind.")).toHaveLength(2);
  expect(log()).toBeNull();
  expect(screen.queryByText("What did routing change?")).toBeNull();
  // With no located step yet, the viewer shows the stored record and abstract.
  expect(screen.getByTestId("paper-about").textContent).toContain("We route papers to islands.");
});

test("each step shows what the agent asked, its badge and its cost, and only played steps are listed", async () => {
  await openRun();
  const next = screen.getByRole("button", { name: "next step" });
  fireEvent.click(next);
  fireEvent.click(next);
  expect(screen.getByText("the agent asked").parentElement?.textContent).toContain("What did routing change?");
  expect(screen.getByText("this step $0.001 · so far $0.001")).toBeTruthy();
  const played = within(log() as HTMLElement).getAllByRole("button");
  expect(played).toHaveLength(2);
  expect(played[1]?.getAttribute("aria-current")).toBe("step");
  expect(screen.queryByText("weighed the claim")).toBeNull();
  fireEvent.click(next);
  expect(document.querySelector(".now .tag")?.textContent).toBe("model · reader-small");
  expect(screen.getByText("this step $0.003 · so far $0.004")).toBeTruthy();
});

test("a step that read a place in the paper moves the viewer to that section and marks the quoted passage", async () => {
  await openRun();
  const next = screen.getByRole("button", { name: "next step" });
  fireEvent.click(next);
  fireEvent.click(next);
  const text = await screen.findByTestId("paper-text");
  const section = within(text).getByText("Results").closest("section");
  expect(section?.getAttribute("aria-current")).toBe("location");
  // The stored text breaks the line inside the passage; the quote still matches.
  expect(section?.querySelector("mark")?.textContent).toBe("cut cost by half\nwhile keeping coverage");
  expect(screen.getByText("page 4")).toBeTruthy();
});

test("a step located only by a page opens the PDF at that page", async () => {
  await openRun();
  const next = screen.getByRole("button", { name: "next step" });
  fireEvent.click(next);
  fireEvent.click(next);
  fireEvent.click(next);
  const frame = await screen.findByTitle("the paper's PDF");
  expect(frame.getAttribute("src")).toBe("https://arxiv.org/pdf/2610.00001#page=7");
});

test("a paper with no stored text and no PDF keeps the record and abstract, with the quote beside it", async () => {
  const bare = { ...RUN, paper: { ...PAPER.paper, url: "https://example.org/p/1", sections: null } };
  await openRun({ ...ROUTES, "GET /api/v1/runs/R-1": bare });
  const next = screen.getByRole("button", { name: "next step" });
  fireEvent.click(next);
  fireEvent.click(next);
  expect(screen.getByTestId("paper-about")).toBeTruthy();
  expect(screen.queryByTitle("the paper's PDF")).toBeNull();
  expect(screen.getByText("cut cost by half while keeping coverage").tagName).toBe("MARK");
});

test("a run is watched, not steered: its genome is shown as the run used it, and editing is a link to the agent", async () => {
  const server = await openRun();
  await screen.findAllByText("Read one paper. Ask what would change your mind.");
  expect(document.querySelectorAll("textarea")).toHaveLength(0);
  expect(screen.queryByRole("button", { name: /^(start|run)\b|edit|save/i })).toBeNull();
  expect(screen.getByRole("link", { name: "edit this agent on its island" }).getAttribute("href")).toBe("/islands/cs#agent-cs-reader");
  expect(server.calls.every((c) => c.method === "GET")).toBe(true);
});

test("a run still in progress is followed live: the replay sits on its newest stored step", async () => {
  const running: RunView = { ...RUN, run: { ...RUN.run, status: "running" }, reading: null };
  await openRun({ ...ROUTES, "GET /api/v1/runs/R-1": running });
  expect(screen.getByText("live: following the agent")).toBeTruthy();
  expect(screen.getByText("step 4 of 4")).toBeTruthy();
  // Taking the controls stops the following; one press brings it back.
  fireEvent.click(screen.getByRole("button", { name: "previous step" }));
  expect(screen.getByText("step 3 of 4")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "follow the agent live" }));
  expect(screen.getByText("step 4 of 4")).toBeTruthy();
});

test("the submitted reading shows its claims with the words they quote", async () => {
  await openRun();
  expect(screen.getByText("Routing halves cost.").textContent).toContain("Routing halves cost.");
  expect(screen.getByText("cut cost by half").tagName).toBe("BLOCKQUOTE");
  expect(screen.getByText("quoted from the paper")).toBeTruthy();
  expect(screen.getByText("One benchmark only.")).toBeTruthy();
});

test("a run with no stored step replays nothing", async () => {
  const empty: RunView = { ...RUN, events: [] };
  await openRun({ ...ROUTES, "GET /api/v1/runs/R-1": empty });
  expect(screen.getByText("No step is stored for this run, so there is nothing to replay.")).toBeTruthy();
  expect((screen.getByRole("button", { name: "play" }) as HTMLButtonElement).disabled).toBe(true);
});

test("a link to a step opens the replay there", async () => {
  await openRun(ROUTES, "/runs/R-1?step=3");
  expect(screen.getByText("step 3 of 4")).toBeTruthy();
});

test("play walks the stored steps one at a time and stops at the last; restart goes back to the start", () => {
  vi.useFakeTimers();
  const steps: number[] = [];
  function Harness() {
    const [step, setStep] = useStateSpy(steps);
    return <Replay events={RUN.events} step={step} onStep={setStep} opening={null} />;
  }
  render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "play" }));
  for (let i = 0; i < 6; i++) act(() => void vi.advanceTimersByTime(1600));
  expect(steps).toEqual([0, 1, 2, 3, 4]);
  expect(screen.getByRole("button", { name: "play" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "restart" }));
  expect(steps.at(-1)).toBe(0);
});

test("pause holds the replay on its step", () => {
  vi.useFakeTimers();
  const steps: number[] = [];
  function Harness() {
    const [step, setStep] = useStateSpy(steps);
    return <Replay events={RUN.events} step={step} onStep={setStep} opening={null} />;
  }
  render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "play" }));
  act(() => void vi.advanceTimersByTime(1600));
  fireEvent.click(screen.getByRole("button", { name: "pause" }));
  act(() => void vi.advanceTimersByTime(8000));
  expect(steps.at(-1)).toBe(1);
});

test("step costs add up by model and by tool", () => {
  expect(costGroups(RUN.events).map((g) => [g.type, g.label, g.steps, g.micros])).toEqual([
    ["model", "reader-small", 1, 3000],
    ["tool", "paper_text", 1, 1000],
    ["tool", "submit_reading", 1, 1000],
    ["step", "run started", 1, 0],
  ]);
});
