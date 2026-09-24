import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Card, Cards } from "./Cards.tsx";
import { ChanceBar, chanceColour } from "./ChanceBar.tsx";
import { Dot } from "./Dot.tsx";

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
