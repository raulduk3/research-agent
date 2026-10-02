import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MathText, splitMath } from "./MathText.tsx";

describe("MathText", () => {
  it("renders inline and display LaTeX while leaving plain text alone", () => {
    expect(splitMath("plain $H=\\sum_i Z_i$ and \\[x^2\\]")).toEqual([
      { kind: "text", text: "plain " },
      { kind: "math", text: "H=\\sum_i Z_i", display: false },
      { kind: "text", text: " and " },
      { kind: "math", text: "x^2", display: true },
    ]);

    const view = render(<p><MathText text="claim $H=\\sum_i Z_i$" /></p>);

    expect(screen.getByText("claim", { exact: false })).toBeTruthy();
    expect(view.container.querySelector(".katex")).not.toBeNull();
  });

  it("does not treat ordinary dollar amounts as math", () => {
    const view = render(<p><MathText text="Cost is $5 today and $6 tomorrow." /></p>);

    expect(screen.getByText("Cost is $5 today and $6 tomorrow.")).toBeTruthy();
    expect(view.container.querySelector(".katex")).toBeNull();
  });
});
