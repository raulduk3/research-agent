import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sceneAt, Swarm, type Sealed, type Step } from "./Swarm.tsx";
import { LIVE_RUNS } from "./useRunStream.ts";

/** A stand-in for the browser's EventSource that the test drives by hand. */
class FakeSource {
  static CLOSED = 2;
  static last: FakeSource | null = null;
  readyState = 0;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  listeners = new Map<string, (m: { data: string }) => void>();
  constructor(readonly url: string) {
    FakeSource.last = this;
  }
  addEventListener(kind: string, f: (m: { data: string }) => void) {
    this.listeners.set(kind, f);
  }
  close() {
    this.readyState = FakeSource.CLOSED;
  }
  emit(kind: string, id: string, run_id = RUN) {
    this.listeners.get(kind)?.({ data: JSON.stringify({ id, kind, run_id, paper_id: null, island: "north" }) });
  }
}

const RUN = "33333333-3333-4333-8333-333333333331";
const AGENT = "11111111-1111-4111-8111-111111111111";
const steps: Step[] = [
  { kind: "model_turn", at: "2026-10-01T03:30:00Z" },
  { kind: "model_turn", at: "2026-10-01T03:45:00Z" },
];
const sealed: Sealed[] = [
  { sealed_at: "2026-10-01T03:41:07Z", confidence: 0.19 },
  { sealed_at: "2026-10-01T03:42:00Z", confidence: null },
];

beforeEach(() => {
  FakeSource.last = null;
  vi.stubGlobal("EventSource", FakeSource);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const timeline = () => screen.getByLabelText<HTMLInputElement>("timeline");

describe("sceneAt", () => {
  it("settles reads, flight and sealed chances up to the cursor", () => {
    expect(sceneAt(steps, sealed, 0, true).ticks.size).toBe(0);
    const first = sceneAt(steps, sealed, 1, true);
    expect(first.ticks.get(0)).toBe(1);
    expect(first.arrows.size).toBe(0);
    expect(first.inflight).toEqual([{ genome: 0, target: 0 }]);
    const last = sceneAt(steps, sealed, 2, true);
    expect(last.arrows.get(0)).toEqual([[0, 0.19]]);
    expect(last.selected).toBe(0);
    expect(last.inflight).toEqual([]);
    expect(sceneAt(steps, sealed, 2, false).inflight).toHaveLength(1);
  });
});

describe("Swarm", () => {
  it("scrubs and plays the run's recorded steps", () => {
    vi.useFakeTimers();
    render(<Swarm run={{ agent: AGENT, island: "north" }} recorded={steps} sealed={sealed} runId={null} width={400} />);
    expect(timeline().max).toBe("2");
    expect(timeline().value).toBe("0");
    fireEvent.change(timeline(), { target: { value: "1" } });
    expect(screen.getByText("step 1 of 2 · model_turn")).toBeTruthy();
    fireEvent.click(screen.getByLabelText("play"));
    act(() => vi.advanceTimersByTime(600));
    expect(timeline().value).toBe("2");
    expect(screen.getByLabelText("play")).toBeTruthy();
    const ctx = document.querySelector("canvas")?.getContext("2d") as unknown as {
      __getEvents(): { type: string; props: { text?: string } }[];
    };
    const texts = ctx.__getEvents().flatMap((e) => (e.type === "fillText" ? [e.props.text] : []));
    expect(texts).toContain("north");
    expect(texts).toContain(AGENT.slice(0, 8));
  });

  it("draws the frame and disables its controls with no run", () => {
    render(<Swarm run={null} recorded={[]} sealed={[]} runId={null} width={400} />);
    expect(timeline().disabled).toBe(true);
    expect(screen.getByLabelText<HTMLButtonElement>("play").disabled).toBe(true);
    expect(screen.getByText("No step recorded to replay.")).toBeTruthy();
    expect(document.querySelector(".rplay > .stage > canvas")).toBeTruthy();
  });

  it("follows the live stream until the run ends", () => {
    render(<Swarm run={{ agent: AGENT, island: null }} recorded={steps} sealed={sealed} runId={RUN} width={400} />);
    const source = FakeSource.last;
    if (!source) throw new Error("no stream opened");
    expect(source.url).toBe(`${LIVE_RUNS}?run_id=${RUN}`);
    act(() => source.onopen?.());
    act(() => {
      source.emit("call", "7");
      source.emit("call", "7");
      source.emit("call", "8", "other");
    });
    expect(screen.getByText("following the run live")).toBeTruthy();
    expect(timeline().value).toBe("3");
    expect(screen.getByText("step 3 of 3 · call")).toBeTruthy();
    act(() => source.emit("ending", "9"));
    expect(source.readyState).toBe(FakeSource.CLOSED);
    expect(screen.getByText("replay from the record")).toBeTruthy();
    expect(timeline().max).toBe("4");
  });
});
