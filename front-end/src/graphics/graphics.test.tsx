import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Board, NO_ANSWER } from "./Board.tsx";
import { Card, Cards } from "./Cards.tsx";
import { ChanceBar, chanceColour } from "./ChanceBar.tsx";
import { Dot } from "./Dot.tsx";
import { ReaderLane } from "./ReaderLane.tsx";
import { Tiles } from "./Tiles.tsx";

afterEach(cleanup);

/** A colour as the DOM stores it once painted, so the mock's hsl compares after normalising. */
function painted(colour: string): string {
  const probe = document.createElement("span");
  probe.style.background = colour;
  return probe.style.background;
}

describe("ChanceBar", () => {
  it("draws the bar at the chance's width in the mock's colour", () => {
    const { container } = render(<ChanceBar p={0.74} />);
    const bar = container.querySelector<HTMLElement>("span.pb > i > b");
    expect(chanceColour(0.74)).toBe("hsl(24, 81%, 55%)");
    expect(bar?.style.width).toBe("74%");
    expect(bar?.style.background).toBe(painted("hsl(24, 81%, 55%)"));
    expect(container.querySelector("span.num")?.textContent).toBe("0.74");
  });

  it("keeps the frame and draws no bar without a chance", () => {
    const { container } = render(<ChanceBar p={null} none="none rated" />);
    expect(container.querySelector("span.pb > i")).not.toBeNull();
    expect(container.querySelector("span.pb b")).toBeNull();
    expect(container.querySelector("span.num")?.textContent).toBe("none rated");
  });
});

describe("Dot", () => {
  it("colours an identity mark by hue", () => {
    const { container } = render(<Dot hue={30} />);
    const dot = container.querySelector<HTMLElement>("span.dot");
    expect(dot?.className).toBe("dot");
    expect(dot?.style.background).toBe(painted("hsl(30, 70%, 50%)"));
  });

  it("carries the lane states as the mock's classes", () => {
    const { container } = render(<Dot kind="base" hidden />);
    const dot = container.querySelector("span.dot");
    expect(dot?.className).toBe("dot base hid");
    expect(dot?.getAttribute("style")).toBeNull();
  });
});

describe("Cards", () => {
  it("renders the grid with each card's title, value and note", () => {
    const { container } = render(
      <Cards>
        <Card title="Runs" value="121 of 124" meta="today" />
        <Card title="Spend" value="none" />
      </Cards>,
    );
    const cards = container.querySelectorAll("div.cards > div.card");
    expect(cards).toHaveLength(2);
    expect(cards[0]?.querySelector("b")?.textContent).toBe("Runs");
    expect(cards[0]?.querySelector("div.v")?.textContent).toBe("121 of 124");
    expect(cards[0]?.querySelector("span.meta")?.textContent).toBe("today");
    expect(cards[1]?.querySelector("span.meta")).toBeNull();
  });
});

describe("Board", () => {
  it("draws one lane per container and one block per run over the day's minutes", () => {
    const lanes = [
      {
        name: "container 1",
        runs: [
          { start: 63, end: 76, hue: 0, title: "cs · evidence-first · 01:03 to 01:16 UTC" },
          { start: 197, end: 209, hue: null, title: "q-bio · limitations · no answer" },
        ],
      },
      { name: "container 2", runs: [] },
    ];
    const { container } = render(<Board lanes={lanes} label="today's runs" />);
    const drawn = container.querySelectorAll("div.board > div.lane");
    expect(drawn).toHaveLength(2);
    expect(drawn[0]?.querySelector("span.ln")?.textContent).toBe("container 1");
    const rects = drawn[0]?.querySelectorAll("svg[viewBox='0 0 1440 24'] > rect") ?? [];
    expect(rects).toHaveLength(2);
    expect(rects[0]?.getAttribute("x")).toBe("63");
    expect(rects[0]?.getAttribute("width")).toBe("13");
    expect(rects[0]?.getAttribute("fill")).toBe("hsl(0, 70%, 55%)");
    expect(rects[0]?.querySelector("title")?.textContent).toBe("cs · evidence-first · 01:03 to 01:16 UTC");
    expect(rects[1]?.getAttribute("fill")).toBe(NO_ANSWER);
  });

  it("keeps the hour axis and draws no lane without runs", () => {
    const { container } = render(<Board lanes={[]} label="today's runs: none" />);
    expect(container.querySelectorAll("div.board > div.axis > div > span")).toHaveLength(5);
    expect(container.querySelector("div.lane")).toBeNull();
    expect(container.querySelector("rect")).toBeNull();
  });
});

describe("Tiles", () => {
  it("draws one row per island and one tile per agent with its dot", () => {
    const rows = [
      {
        island: "cs",
        tiles: [
          { key: "a", name: "evidence", hue: 0, note: "18 runs" },
          { key: "b", name: "methods", hue: 30, note: "18 runs" },
        ],
      },
      { island: "q-bio", tiles: [{ key: "c", name: "limits", hue: 60, note: "7 runs" }] },
    ];
    const { container } = render(<Tiles rows={rows} empty="none" />);
    const trows = container.querySelectorAll("div.tiles > div.trow");
    expect(trows).toHaveLength(2);
    expect(trows[0]?.querySelector("span.isl")?.textContent).toBe("cs");
    const tiles = trows[0]?.querySelectorAll("div.tgrid > div.tile") ?? [];
    expect(tiles).toHaveLength(2);
    expect(tiles[1]?.textContent).toBe("methods18 runs");
    expect(tiles[1]?.querySelector<HTMLElement>("span.dot")?.style.background).toBe(painted("hsl(30, 70%, 50%)"));
  });

  it("keeps the frame and says why without rows", () => {
    const { container } = render(<Tiles rows={[]} empty="No agent admitted yet." />);
    expect(container.querySelector("div.tiles")?.textContent).toBe("No agent admitted yet.");
    expect(container.querySelector("div.trow")).toBeNull();
  });
});

describe("ReaderLane", () => {
  const events = [
    { at: "2026-10-01T02:00:00Z", kind: "read", title: "a read" },
    { at: "2026-10-01T14:00:00Z", kind: "forecast", title: "a forecast" },
  ];

  it("places events over the recorded span and readers on the chance axis", () => {
    const { container } = render(
      <ReaderLane label="lane" events={events} marks={[{ p: 0.3, title: "reader · 0.30" }]} />,
    );
    const evs = container.querySelectorAll<HTMLElement>("div.tl > div.ev");
    expect([...evs].map((e) => [e.className, e.style.left])).toEqual([
      ["ev c-read", "0%"],
      ["ev c-forecast", "100%"],
    ]);
    const ticks = container.querySelectorAll<HTMLElement>("div.tl > div.tk");
    expect([...ticks].map((t) => [t.textContent, t.style.left])).toEqual([
      ["06:00", "33.33%"],
      ["12:00", "83.33%"],
    ]);
    const dot = container.querySelector<HTMLElement>("div.axis1 > span.dot");
    expect(dot?.style.left).toBe("30%");
    expect(dot?.title).toBe("reader · 0.30");
  });

  it("keeps both frames and the axis labels and draws no marks when nothing is served", () => {
    const { container } = render(<ReaderLane label="lane" events={[]} marks={[]} />);
    expect(container.querySelector("div.tl")?.children).toHaveLength(0);
    expect(container.querySelectorAll("div.axis1 > span.lbl")).toHaveLength(3);
    expect(container.querySelector("div.axis1 .dot")).toBeNull();
  });
});
