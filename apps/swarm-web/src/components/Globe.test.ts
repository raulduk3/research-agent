import { describe, expect, it } from "vitest";
import { MERIDIANS, ease, pace, facing, flyLight, focus, globeScene, gust, hash01, holdingIslands, islandLines, islandSeen, lightAlpha, nearest, paperPoint, stepEffect, weather } from "./Globe.tsx";

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

  it("sends a light to its paper and round what a tool call looked at", () => {
    const step = { id: 1, run_id: "R-1", agent: "a@cs", island_id: "cs", paper_id: "P", kind: "run_started", looked_at: [], created_at: 0 };
    expect(stepEffect(step).visit).toEqual(["P"]);
    expect(stepEffect(step).flare).toBe(false);
    const search = stepEffect({ ...step, kind: "tool_call", tool: "related_papers", looked_at: ["Q", "R"] });
    // It visits each paper the tool found, spawning them, and comes back to its own.
    expect(search.visit).toEqual(["Q", "R", "P"]);
    expect(search.born).toEqual(["Q", "R"]);
    expect(search.flare).toBe(true);
    expect(stepEffect({ ...step, kind: "reading_submitted" }).ring).toBe("P");
    expect(stepEffect({ ...step, kind: "run_completed" }).visit).toEqual([]);
  });

  it("keeps a light bright while its agent works and puts it out once idle", () => {
    expect(lightAlpha(0)).toBe(1);
    expect(lightAlpha(7000)).toBe(1);
    const fading = lightAlpha(8500);
    expect(fading).toBeGreaterThan(0);
    expect(fading).toBeLessThan(1);
    expect(lightAlpha(10_000)).toBe(0);
    expect(lightAlpha(60_000)).toBe(0);
  });

  it("flies a light toward its next stop and says when it gets there", () => {
    const from = { x: 0, y: 0, z: 0 };
    const to = { x: 0.5, y: 0, z: 0 };
    const step = flyLight(from, from, to, 1 / 60);
    expect(step.pos.x).toBeGreaterThan(0);
    expect(step.pos.x).toBeLessThan(0.5);
    expect(step.reached).toBe(false);
    // Frame by frame it gets there.
    let at = { pos: from, vel: from, reached: false };
    for (let k = 0; k < 120 && !at.reached; k++) at = flyLight(at.pos, at.vel, to, 1 / 60);
    expect(at.reached).toBe(true);
    // With nowhere to go a resting light stays put.
    expect(flyLight(from, from, null, 1 / 60).pos).toEqual(from);
  });

  it("turns a light through a curve, not a corner, when its next stop changes", () => {
    // Flying up along y, it is sent off along x: it keeps some of its upward speed for a moment
    // instead of snapping onto the new heading.
    const turned = flyLight({ x: 0, y: 0, z: 0 }, { x: 0, y: 1, z: 0 }, { x: 0.5, y: 0, z: 0 }, 1 / 60);
    expect(turned.pos.y).toBeGreaterThan(0);
    expect(turned.pos.x).toBeGreaterThan(0);
  });

  it("does not overshoot or stall on a long frame", () => {
    const to = { x: 0.5, y: 0, z: 0 };
    const long = flyLight({ x: 0, y: 0, z: 0 }, { x: 0, y: 0, z: 0 }, to, 0.5);
    expect(long.pos.x).toBeGreaterThan(0.4);
    expect(long.pos.x).toBeLessThanOrEqual(0.5);
  });

  it("eases a line or glow toward its new strength instead of jumping there", () => {
    const one = ease(0, 1, 16, 260);
    expect(one).toBeGreaterThan(0);
    expect(one).toBeLessThan(0.2);
    let v = 0;
    for (let k = 0; k < 120; k++) v = ease(v, 1, 16, 260);
    expect(v).toBeGreaterThan(0.99);
    // It ebbs more slowly than it swells.
    expect(1 - ease(1, 0, 16, 260, 900)).toBeLessThan(ease(0, 1, 16, 260, 900));
    expect(ease(0.3, 0.3, 16, 260)).toBe(0.3);
  });

  it("keeps every drawn paper in place when the paper count changes", () => {
    const islands = ["cs", "bio"].map((id) => ({ id, name: id, focus: "" }));
    const fewer = globeScene(islands as never, 30).nodes.filter((n) => n.kind === "paper");
    const more = globeScene(islands as never, 40).nodes.filter((n) => n.kind === "paper");
    expect(more).toHaveLength(40);
    expect(more.slice(0, 30)).toEqual(fewer);
    // A small count still fills the ball rather than one cap of it.
    expect(Math.min(...fewer.map((n) => n.y))).toBeLessThan(0);
    expect(Math.max(...fewer.map((n) => n.y))).toBeGreaterThan(0);
  });

  it("ties a held paper to every island holding it, and a paper not held to none", () => {
    const index = new Map([
      ["cs", 0],
      ["bio", 2],
    ]);
    const paper = { id: "P", title: "P", islands: ["cs", "bio", "gone"], held: true };
    expect(holdingIslands(paper, index)).toEqual([0, 2]);
    expect(holdingIslands({ ...paper, held: false }, index)).toEqual([]);
    expect(holdingIslands({ ...paper, held: null }, index)).toEqual([]);
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

  it("lets an island on the far wall be clicked through the open front, but not one at the rim", () => {
    expect(islandSeen(-0.5)).toBeGreaterThan(0.2);
    expect(islandSeen(0.5)).toBe(1);
    expect(islandSeen(-0.01)).toBeLessThan(0.2);
    expect(islandSeen(0.01)).toBeLessThan(0.2);
  });

  it("draws two full lines through an island, with the island at their middle", () => {
    const at = { x: 0, y: 0.5, z: Math.sqrt(0.75) };
    const [parallel, meridian] = islandLines(at);
    expect(parallel).toHaveLength(145);
    expect(meridian).toHaveLength(145);
    for (const line of [parallel, meridian]) {
      const mid = line[72];
      expect(mid?.x).toBeCloseTo(at.x, 6);
      expect(mid?.y).toBeCloseTo(at.y, 6);
      expect(mid?.z).toBeCloseTo(at.z, 6);
      for (const v of line) expect(Math.hypot(v.x, v.y, v.z)).toBeCloseTo(1, 6);
    }
    // The parallel keeps its latitude; the meridian comes back round to where it started.
    for (const v of parallel) expect(v.y).toBeCloseTo(0.5, 6);
    expect(meridian[0]?.y).toBeCloseTo(meridian[144]?.y ?? NaN, 6);
  });

  it("has weather that moves every mark a little and a gust that fades with distance", () => {
    const a = weather(0.1, 1000, 1);
    const b = weather(0.1, 2500, 1);
    expect(a).not.toEqual(b);
    expect(Math.hypot(a.x, a.y)).toBeLessThan(6);
    expect(gust(0, 0, 0, 0, 10, 0, 80).x).toBeGreaterThan(gust(40, 0, 0, 0, 10, 0, 80).x);
    expect(gust(100, 0, 0, 0, 10, 0, 80)).toEqual({ x: 0, y: 0 });
  });

  it("plays new steps with their real spacing, after what is queued, and keeps up with the feed", () => {
    // Two steps a second apart, nothing queued: the first now, the next a second later.
    expect(pace([], [100, 101], 0).at).toEqual([0, 1000]);
    // A burst at one instant is spread out rather than played in one frame.
    const burst = pace([], [100, 100, 100], 0).at;
    expect((burst[1] ?? 0) - (burst[0] ?? 0)).toBeGreaterThan(100);
    // A long quiet stretch between steps is squeezed so the globe is not left behind.
    expect(pace([], [100, 160], 0).at[1]).toBeLessThanOrEqual(3600);
    // New steps never play before steps already queued.
    const after = pace([500, 900], [100], 0);
    expect(after.at[0]).toBeGreaterThanOrEqual(900);
  });

  it("squeezes a backlog that has fallen behind instead of letting it grow", () => {
    const backlog = [0, 4000, 8000];
    const timed = pace(backlog, [100], 0);
    expect(timed.backlog.at(-1)).toBeLessThanOrEqual(1500);
    expect(timed.backlog).toEqual([...timed.backlog].sort((a, b) => a - b));
    expect(timed.at[0]).toBeGreaterThanOrEqual(timed.backlog.at(-1) ?? Infinity);
    expect(timed.at[0]).toBeLessThanOrEqual(1500);
  });
});
