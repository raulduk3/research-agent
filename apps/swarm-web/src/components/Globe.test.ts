import { describe, expect, it } from "vitest";
import { facing, globeScene } from "./Globe.tsx";

describe("the globe", () => {
  it("shows a surface mark only on the side the camera sees", () => {
    // z runs from -1 (the far side) to 1 (nearest the viewer).
    expect(facing(-1)).toBe(0);
    expect(facing(-0.01)).toBe(0);
    expect(facing(0)).toBe(0);
    expect(facing(1)).toBe(1);
    expect(facing(0.2)).toBe(1);
  });

  it("eases a mark in as it comes round the rim instead of popping", () => {
    const near = facing(0.07);
    expect(near).toBeGreaterThan(0);
    expect(near).toBeLessThan(1);
    expect(facing(0.03)).toBeLessThan(near);
  });

  it("puts every island on the surface, where the far side can hide it", () => {
    const islands = ["cs", "quant", "bio", "general"].map((id) => ({ id, name: id, focus: "" }));
    const scene = globeScene(islands as never, 10);
    const surface = scene.nodes.filter((n) => n.kind === "island");
    expect(surface).toHaveLength(4);
    for (const n of surface) expect(Math.hypot(n.x, n.y, n.z)).toBeCloseTo(1, 6);
  });
});
