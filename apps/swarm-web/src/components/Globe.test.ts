import { describe, expect, it } from "vitest";
import { MERIDIANS, boatFaces, facing, focus, globeScene, hash01, nearest, paperPoint, stepEffect } from "./Globe.tsx";

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

  it("draws meridians all the way round, not only on one half", () => {
    expect(MERIDIANS).toEqual([0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330]);
  });

  it("keeps a known paper in the same place inside the ball, near its island", () => {
    const a = paperPoint("2610.00001", 0, 4);
    expect(paperPoint("2610.00001", 0, 4)).toEqual(a);
    expect(Math.hypot(a.x, a.y, a.z)).toBeLessThan(1);
    expect(hash01("2610.00001")).not.toBe(hash01("2610.00002"));
  });

  it("sails a boat to its paper, strikes what it looks at and sends it home when the run ends", () => {
    const step = { id: 1, run_id: "R-1", agent: "a@cs", island_id: "cs", paper_id: "P", kind: "run_started", looked_at: [], created_at: 0 };
    expect(stepEffect(step).sail).toBe("P");
    const search = stepEffect({ ...step, kind: "tool_call", tool: "related_papers", looked_at: ["Q", "R"] });
    expect(search.bolts).toEqual(["P", "Q", "R"]);
    expect(search.born).toEqual(["Q", "R"]);
    expect(stepEffect({ ...step, kind: "reading_submitted" }).ring).toBe("P");
    expect(stepEffect({ ...step, kind: "run_completed" }).sail).toBeNull();
  });

  it("picks the nearest mark under the pointer and nothing beyond reach", () => {
    const marks = [
      { x: 10, y: 10, key: "a" },
      { x: 30, y: 10, key: "b" },
    ];
    expect(nearest(marks, 27, 11, 12)).toBe("b");
    expect(nearest(marks, 100, 100, 12)).toBeNull();
  });

  it("keeps the near side in focus and blurs the far side", () => {
    expect(focus(1).alpha).toBeCloseTo(1, 6);
    expect(focus(1).blur).toBe(0);
    expect(focus(-1).alpha).toBeLessThan(0.4);
    expect(focus(-1).blur).toBeGreaterThan(focus(0).blur);
  });

  it("builds the boat as a small solid at its place, bow toward its heading", () => {
    const at = { x: 0.5, y: 0, z: 0 };
    const faces = boatFaces(at, { x: 0, y: 1, z: 0 }, { x: 0, y: 0, z: 1 }, 0.1);
    expect(faces.filter((f) => f.part === "hull")).toHaveLength(5);
    expect(faces.some((f) => f.part === "sail")).toBe(true);
    const bow = faces[0]?.at[0];
    // The bow is a boat-length ahead along the heading, and nothing is farther than that.
    expect(bow?.z).toBeCloseTo(0.1, 6);
    for (const f of faces) for (const v of f.at) expect(Math.hypot(v.x - at.x, v.y - at.y, v.z - at.z)).toBeLessThanOrEqual(0.1 * 1.5);
  });
});
