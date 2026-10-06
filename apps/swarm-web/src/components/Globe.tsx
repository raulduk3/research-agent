import { type MouseEvent, useEffect, useMemo, useRef, useState } from "react";
import type { ActivityPaper, ActivityStep, Island } from "../api/types.ts";
import { useApi } from "../api/context.tsx";

/** A point of the globe: an island on the surface or a paper inside. `island` is -1 for a paper no island is known for. */
export type GlobeNode = { x: number; y: number; z: number; kind: "island" | "paper"; island: number };

export type GlobeScene = { nodes: GlobeNode[]; edges: [island: number, paper: number][] };

/** The most papers and reads drawn; past it the globe shows scale, not each one. */
const MAX_PAPERS = 160;
const MAX_EDGES = 160;

const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
const HUES = [214, 140, 24, 265, 48, 355];

export function islandHue(index: number): number {
  return HUES[index % HUES.length] ?? 214;
}

/** The k-th of n evenly spread directions on a sphere. */
function direction(k: number, n: number, turn: number): [number, number, number] {
  const y = 1 - (2 * (k + 0.5)) / n;
  const r = Math.sqrt(Math.max(0, 1 - y * y));
  const lon = k * GOLDEN_ANGLE + turn;
  return [r * Math.cos(lon), y, r * Math.sin(lon)];
}

/**
 * Where everything sits: islands evenly on the surface, one dot per paper filling the inside.
 * When the server counts papers and runs per island, each island's papers lean toward it and one
 * line is drawn per run; otherwise the dots fill the ball evenly and no line is drawn. Positions
 * depend only on the counts, so the same storm always draws the same globe, and a dot keeps its
 * place when the count changes.
 */
export function globeScene(islands: readonly Island[], papers: number): GlobeScene {
  const nodes: GlobeNode[] = islands.map((_, i) => {
    const [x, y, z] = direction(i, Math.max(islands.length, 1), 1.1);
    return { x, y, z, kind: "island", island: i };
  });
  const drawn = Math.min(Math.max(0, Math.floor(papers)), MAX_PAPERS);
  const counted = islands.length > 0 && islands.every((i) => typeof i.paper_count === "number");
  const total = islands.reduce((sum, i) => sum + (i.paper_count ?? 0), 0);
  // Each dot's island, in proportion to the islands' paper counts. A dot's share is fixed by its own
  // order alone, spread by a low-discrepancy sequence, so a change in the count never hands an
  // existing dot to another island.
  const owner: number[] = [];
  if (counted && total > 0) {
    for (let k = 0; k < drawn; k++) {
      const share = (((k + 0.5) * 0.7548776662) % 1) * total;
      let sum = 0;
      const i = islands.findIndex((isl) => (sum += isl.paper_count ?? 0) > share);
      owner.push(i >= 0 ? i : islands.length - 1);
    }
  }
  const firstPaper = nodes.length;
  for (let k = 0; k < drawn; k++) {
    // Each dot owns a fixed slot of the full set, strided so any count still fills the ball, so a
    // change in the count adds or removes dots without moving the ones already there.
    let [x, y, z] = direction((k * 61) % MAX_PAPERS, MAX_PAPERS, 0.4);
    const of = owner[k] ?? -1;
    const home = of >= 0 ? nodes[of] : undefined;
    if (home) {
      x = x * 0.45 + home.x * 0.55;
      y = y * 0.45 + home.y * 0.55;
      z = z * 0.45 + home.z * 0.55;
      const len = Math.hypot(x, y, z) || 1;
      x /= len;
      y /= len;
      z /= len;
    }
    // Depth by a low-discrepancy sequence, eased outward so the projected ball reads evenly filled.
    const depth = 0.9 * Math.pow(((k + 0.5) * 0.6180339887) % 1, 1 / 2.8);
    nodes.push({ x: x * depth, y: y * depth, z: z * depth, kind: "paper", island: of });
  }
  const edges: [number, number][] = [];
  const runs = islands.reduce((sum, i) => sum + (i.run_count ?? 0), 0);
  if (counted && runs > 0 && islands.every((i) => typeof i.run_count === "number")) {
    islands.forEach((isl, i) => {
      const own = owner.flatMap((o, k) => (o === i ? [firstPaper + k] : []));
      const lines = Math.min(own.length, Math.round(((isl.run_count ?? 0) / runs) * Math.min(runs, MAX_EDGES)));
      for (let k = 0; k < lines; k++) edges.push([i, own[k] as number]);
    });
  }
  return { nodes, edges };
}

const TILT = 0.38;

/**
 * The meridians, in degrees of longitude. Each is drawn pole to pole on one side, so a full set
 * goes all the way round; stopping at 180 left half the globe without vertical lines.
 */
export const MERIDIANS: readonly number[] = Array.from({ length: 12 }, (_, i) => i * 30);

/**
 * How much of a surface mark the camera sees, from its depth toward the viewer: nothing on the
 * far side of the globe, all of it once it is clear of the rim, easing in between so an island
 * comes round the edge instead of popping.
 */
export function facing(z: number): number {
  return Math.max(0, Math.min(1, z / 0.14));
}

/**
 * How much of an island the camera sees: all of it on the near side once clear of the rim, and
 * on the far side a fainter mark on the inner wall, seen through the open front. Either can be
 * clicked; an island at the rim is too faint to see and cannot.
 */
export function islandSeen(z: number): number {
  return z < 0 ? Math.max(0, Math.min(1, -z / 0.14)) * 0.6 : facing(z);
}

type Vec = { x: number; y: number; z: number };
type Projector = (p: Vec) => Vec;

/**
 * How much of each part of the scene is shown, eased by the caller so nothing pops: each count
 * dot by its order among the papers, the islands, the count lines, and the selected island's lines.
 */
type Shown = { dot: (k: number) => number; islands: number; edges: number; selected: number; retiring: readonly { node: GlobeNode; alpha: number }[] };

/** Paints the globe and returns how it projected, so the marks drawn over it line up. */
function draw(ctx: CanvasRenderingContext2D, scene: GlobeScene, W: number, H: number, angle: number, selected: number, shown: Shown): { proj: Projector; S: number; R: number } {
  ctx.clearRect(0, 0, W, H);
  const R = Math.max(1, Math.min(W, H) / 2 - Math.min(16, Math.min(W, H) * 0.06));
  const cx = W / 2;
  const cy = H / 2;
  const S = Math.max(0.55, Math.min(1, R / 140));
  const ca = Math.cos(angle);
  const sa = Math.sin(angle);
  const ct = Math.cos(TILT);
  const st = Math.sin(TILT);
  const proj = (p: { x: number; y: number; z: number }) => {
    const x = p.x * ca - p.z * sa;
    const z0 = p.x * sa + p.z * ca;
    return { x: cx + x * R, y: cy - (p.y * ct - z0 * st) * R, z: p.y * st + z0 * ct };
  };

  // The far side is the inside of a hollow shell: a solid, grey surface lit from the upper
  // left, bright where it faces us and darkening to the rim where it curves away. The near side
  // is left open, wireframe only, so the papers read as hanging inside the bowl.
  const shell = ctx.createRadialGradient(cx - R * 0.28, cy - R * 0.3, R * 0.05, cx, cy, R);
  shell.addColorStop(0, "#f6f6f6");
  shell.addColorStop(0.45, "#e2e2e2");
  shell.addColorStop(0.8, "#bdbdbd");
  shell.addColorStop(1, "#8d8d8d");
  ctx.fillStyle = shell;
  ctx.beginPath();
  ctx.arc(cx, cy, R, 0, 6.283);
  ctx.fill();
  const lip = ctx.createRadialGradient(cx, cy, R * 0.84, cx, cy, R);
  lip.addColorStop(0, "rgba(0,0,0,0)");
  lip.addColorStop(1, "rgba(0,0,0,0.3)");
  ctx.fillStyle = lip;
  ctx.beginPath();
  ctx.arc(cx, cy, R, 0, 6.283);
  ctx.fill();
  ctx.strokeStyle = "rgba(0,0,0,0.5)";
  ctx.lineWidth = 1;
  ctx.stroke();

  // The graticule, both halves: on the far wall as lighter lines caught by the light, on the
  // near side as the wire of the open front.
  const arc = (point: (i: number) => Vec, back: boolean) => {
    ctx.beginPath();
    let pen = false;
    for (let i = 0; i <= 90; i++) {
      const p = proj(point(i));
      if (back ? p.z > 0 : p.z < 0) {
        pen = false;
        continue;
      }
      if (pen) ctx.lineTo(p.x, p.y);
      else ctx.moveTo(p.x, p.y);
      pen = true;
    }
    ctx.stroke();
  };
  const rings: ((i: number) => Vec)[] = [];
  for (let lat = -60; lat <= 60; lat += 30) {
    const la = (lat * Math.PI) / 180;
    rings.push((i) => ({ x: Math.cos(la) * Math.cos((i / 90) * 6.283), y: Math.sin(la), z: Math.cos(la) * Math.sin((i / 90) * 6.283) }));
  }
  for (const lon of MERIDIANS) {
    const lo = (lon * Math.PI) / 180;
    rings.push((i) => {
      const la = -Math.PI / 2 + (i / 90) * Math.PI;
      return { x: Math.cos(la) * Math.cos(lo), y: Math.sin(la), z: Math.cos(la) * Math.sin(lo) };
    });
  }
  ctx.strokeStyle = "rgba(255,255,255,0.5)";
  ctx.lineWidth = 0.8;
  for (const ring of rings) arc(ring, true);
  ctx.strokeStyle = "rgba(0,0,0,0.3)";
  ctx.lineWidth = 0.8;
  for (const ring of rings) arc(ring, false);

  const P = scene.nodes.map(proj);
  // One arc per read, bowed outward in the island's color, fading toward the back.
  for (const [i, j] of scene.edges) {
    const A = P[i];
    const B = P[j];
    if (!A || !B) continue;
    // A read is drawn from its island, so it goes out of sight with the island.
    const vis = Math.max(0, Math.min(1, ((A.z + B.z) / 2 + 0.8) / 1.2)) * facing(A.z) * shown.edges;
    if (vis <= 0) continue;
    const mx = (A.x + B.x) / 2;
    const my = (A.y + B.y) / 2;
    const L = Math.hypot(mx - cx, my - cy) || 1;
    ctx.strokeStyle = `hsla(${islandHue(i)},85%,38%,${(0.32 * vis * vis).toFixed(3)})`;
    ctx.lineWidth = 0.8 * S;
    ctx.beginPath();
    ctx.moveTo(A.x, A.y);
    ctx.quadraticCurveTo(mx + ((mx - cx) / L) * 0.22 * R, my + ((my - cy) / L) * 0.22 * R, B.x, B.y);
    ctx.stroke();
  }
  // Back to front, so nearer marks cover farther ones.
  // Dots the count no longer has fade out where they were, rather than vanishing.
  for (const { node, alpha } of shown.retiring) {
    const p = proj(node);
    const f = focus(p.z);
    softDot(ctx, p.x, p.y, (0.5 + 1.0 * f.near) * S, f.blur * S, node.island >= 0 ? `hsla(${islandHue(node.island)},30%,${Math.round(58 - 18 * f.near)}%,` : "rgba(60,60,60,", 0.22 * f.alpha * alpha);
  }
  const order = P.map((_, k) => k).sort((u, v) => (P[u]?.z ?? 0) - (P[v]?.z ?? 0));
  const firstPaper = scene.nodes.findIndex((n) => n.kind === "paper");
  for (const k of order) {
    const p = P[k];
    const n = scene.nodes[k];
    if (!p || !n) continue;
    const depth = (p.z + 1) / 2;
    if (n.kind === "paper") {
      // A paper the brief does not list: a faint speck, softer the farther back it sits.
      const f = focus(p.z);
      const a = 0.22 * f.alpha * shown.dot(k - firstPaper);
      if (a > 0.002) softDot(ctx, p.x, p.y, (0.5 + 1.0 * f.near) * S, f.blur * S, n.island >= 0 ? `hsla(${islandHue(n.island)},30%,${Math.round(58 - 18 * f.near)}%,` : "rgba(60,60,60,", a);
      continue;
    }
    // An island sits on a radial point of the shell; the dot is the island. On the far side it is
    // a mark on the inner wall, seen through the open front. The selected island also gets two of
    // the sphere's own lines through it, its parallel and its meridian, all the way round, each
    // pressed harder near the point so the crossing stands out.
    const hue = islandHue(n.island);
    const back = p.z < 0;
    const seen = islandSeen(p.z) * shown.islands;
    if (seen <= 0) continue;
    const rr = 5.5 * (0.7 + 0.5 * depth) * S;
    ctx.globalAlpha = seen;
    for (const line of k === selected && shown.selected > 0.002 ? islandLines(n) : []) {
      // The whole line, thin, on both halves; the near half darker.
      for (const [side, alpha] of [[false, 0.14], [true, 0.4]] as const) {
        ctx.strokeStyle = `hsla(${hue},70%,40%,${(alpha * shown.selected).toFixed(3)})`;
        ctx.lineWidth = 0.7 * S;
        ctx.beginPath();
        let pen = false;
        for (const q of line) {
          const v = proj(q);
          if (side ? v.z < 0 : v.z >= 0) {
            pen = false;
            continue;
          }
          if (pen) ctx.lineTo(v.x, v.y);
          else ctx.moveTo(v.x, v.y);
          pen = true;
        }
        ctx.stroke();
      }
      // The stretch near the point, doubled: a heavier stroke over the thin one.
      ctx.strokeStyle = `hsla(${hue},75%,38%,${((back ? 0.45 : 0.85) * shown.selected).toFixed(3)})`;
      ctx.lineWidth = 1.8 * S;
      ctx.beginPath();
      const near = line.slice(line.length / 2 - EMPHASIS_STEPS, line.length / 2 + EMPHASIS_STEPS + 1);
      near.forEach((q, k) => {
        const v = proj(q);
        if (k === 0) ctx.moveTo(v.x, v.y);
        else ctx.lineTo(v.x, v.y);
      });
      ctx.stroke();
    }
    ctx.fillStyle = `hsla(${hue},90%,42%,${(back ? 0.6 : 0.55 + 0.45 * depth).toFixed(2)})`;
    ctx.beginPath();
    ctx.arc(p.x, p.y, rr, 0, 6.283);
    ctx.fill();
    if (!back) {
      ctx.fillStyle = `rgba(255,255,255,${(0.5 * depth).toFixed(2)})`;
      ctx.beginPath();
      ctx.arc(p.x - rr * 0.3, p.y - rr * 0.3, rr * 0.35, 0, 6.283);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  }
  return { proj, S, R };
}

/**
 * How sharply a mark inside the globe is drawn, from its depth: z is -1 at the far side and 1
 * nearest the viewer. Near marks are opaque and crisp; far ones fade and blur, so the side facing
 * the viewer is the one in focus.
 */
export function focus(z: number): { near: number; alpha: number; blur: number } {
  const near = Math.max(0, Math.min(1, (z + 1) / 2));
  return { near, alpha: 0.3 + 0.7 * near * near, blur: 3.5 * (1 - near) * (1 - near) };
}

/** A dot, crisp when `blur` is small and a soft falloff otherwise. `color` ends before the alpha. */
function softDot(ctx: CanvasRenderingContext2D, x: number, y: number, r: number, blur: number, color: string, alpha: number): void {
  ctx.beginPath();
  if (blur < 0.6) {
    ctx.fillStyle = `${color}${alpha.toFixed(3)})`;
    ctx.arc(x, y, r, 0, 6.283);
  } else {
    const g = ctx.createRadialGradient(x, y, 0, x, y, r + blur);
    g.addColorStop(0, `${color}${alpha.toFixed(3)})`);
    g.addColorStop(r / (r + blur), `${color}${(alpha * 0.6).toFixed(3)})`);
    g.addColorStop(1, `${color}0)`);
    ctx.fillStyle = g;
    ctx.arc(x, y, r + blur, 0, 6.283);
  }
  ctx.fill();
}

const add = (a: Vec, b: Vec): Vec => ({ x: a.x + b.x, y: a.y + b.y, z: a.z + b.z });
const mul = (a: Vec, k: number): Vec => ({ x: a.x * k, y: a.y * k, z: a.z * k });
const unit = (a: Vec): Vec => mul(a, 1 / (Math.hypot(a.x, a.y, a.z) || 1));

/** A point on the unit sphere at latitude and longitude, in radians. */
const onSphere = (lat: number, lon: number): Vec => ({ x: Math.cos(lat) * Math.cos(lon), y: Math.sin(lat), z: Math.cos(lat) * Math.sin(lon) });

/** Points per full line, and how many each side of the island's point are pressed harder. */
const LINE_STEPS = 144;
const EMPHASIS_STEPS = 7;

/**
 * The two lines through a surface point: its parallel and its meridian, each the full way
 * round as `LINE_STEPS + 1` points on the sphere with the island's point at the middle, so the
 * middle stretch can be drawn heavier.
 */
export function islandLines(at: Vec): [parallel: Vec[], meridian: Vec[]] {
  const r = unit(at);
  const lat = Math.asin(Math.max(-1, Math.min(1, r.y)));
  const lon = Math.atan2(r.z, r.x);
  const parallel: Vec[] = [];
  const meridian: Vec[] = [];
  for (let k = 0; k <= LINE_STEPS; k++) {
    const t = -Math.PI + (2 * Math.PI * k) / LINE_STEPS;
    parallel.push(onSphere(lat, lon + t));
    meridian.push(onSphere(lat + t, lon));
  }
  return [parallel, meridian];
}

/** How long a light stays bright after its agent's last step, then how long it takes to go out. */
const AWAKE_MS = 7000;
const FADE_MS = 3000;

/**
 * How bright an agent's light is, from the time since its last step: full while it works, then
 * fading to nothing, so an idle agent leaves no mark on the globe.
 */
export function lightAlpha(sinceStep: number): number {
  if (sinceStep <= AWAKE_MS) return 1;
  return Math.max(0, 1 - (sinceStep - AWAKE_MS) / FADE_MS);
}

/** How far from a paper a light counts as there, in globe units. */
const ARRIVED = 0.03;

/**
 * `dt` seconds of a light's flight. A critically damped spring at rate `pull` per second draws it
 * toward `goal` and carries its speed into the next stop, so a change of course is a curve rather
 * than a corner; with no goal it coasts to rest. The spring is solved exactly, so a long frame
 * neither overshoots nor stalls. It says whether the light got there.
 */
export function flyLight(pos: Vec, vel: Vec, goal: Vec | null, dt: number, pull = 10): { pos: Vec; vel: Vec; reached: boolean } {
  const e = Math.exp(-pull * dt);
  if (!goal) {
    return { pos: add(pos, mul(vel, (1 - e) / pull)), vel: mul(vel, e), reached: false };
  }
  const off = add(pos, mul(goal, -1));
  const c = add(vel, mul(off, pull));
  const left = mul(add(off, mul(c, dt)), e);
  return { pos: add(goal, left), vel: mul(add(vel, mul(c, -pull * dt)), e), reached: Math.hypot(left.x, left.y, left.z) < ARRIVED };
}

/**
 * `from` moved toward `to` over `dt` milliseconds, closing about two thirds of the gap every
 * `rise` ms on the way up and every `fall` ms on the way down. Every line, glow and fade on the
 * globe goes through it, so a change in the swarm shows as a swell or an ebb, never a jump.
 */
export function ease(from: number, to: number, dt: number, rise: number, fall = rise): number {
  const tau = to > from ? rise : fall;
  if (tau <= 0) return to;
  return to + (from - to) * Math.exp(-dt / tau);
}

/** A paper the globe knows by id: selected, waiting for a decision, or just looked up. */
export type GlobePaper = {
  id: string;
  title: string;
  islands: string[];
  /** True when selected, false while waiting, null when the globe only saw it looked up. */
  held: boolean | null;
  daysLeft?: number | null;
  readings?: number | null;
  /** Filled in when the paper's public record is read on a click. */
  thesis?: string | null;
  takeaways?: string[] | null;
  used?: number | null;
};

/**
 * The weather: a slow swell that moves every mark a little, by its own phase, so the globe is
 * never quite still. In screen pixels, scaled by `S`. A viewer who asks for reduced motion
 * gets none.
 */
export function weather(seed: number, now: number, S: number): { x: number; y: number } {
  const t = now / 1000;
  return {
    x: (Math.sin(t * 0.37 + seed * 6.283) * 2.2 + Math.sin(t * 0.11 + seed * 2.1) * 1.4) * S,
    y: (Math.cos(t * 0.29 + seed * 4.2) * 1.8 + Math.sin(t * 0.07 + seed * 5.3) * 1.2) * S,
  };
}

/** How much a gust at (gx, gy) moving (vx, vy) shoves a mark at (x, y): nearer marks more, up to `reach` px. */
export function gust(x: number, y: number, gx: number, gy: number, vx: number, vy: number, reach: number): { x: number; y: number } {
  const d = Math.hypot(x - gx, y - gy);
  if (d > reach) return { x: 0, y: 0 };
  const k = (1 - d / reach) * 0.18;
  return { x: vx * k, y: vy * k };
}

/** A stable number in [0, 1) from text, so the same paper always sits in the same place. */
export function hash01(text: string, salt = 0): number {
  let h = 2166136261 ^ salt;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return ((h >>> 0) % 100000) / 100000;
}

/** Where a known paper sits: inside the ball, leaning toward its island when it has one. */
export function paperPoint(id: string, island: number, islandCount: number): Vec {
  const k = Math.floor(hash01(id) * 997);
  let [x, y, z] = direction(k, 997, 0.4);
  if (island >= 0 && islandCount > 0) {
    const [hx, hy, hz] = direction(island, islandCount, 1.1);
    x = x * 0.5 + hx * 0.5;
    y = y * 0.5 + hy * 0.5;
    z = z * 0.5 + hz * 0.5;
    const len = Math.hypot(x, y, z) || 1;
    x /= len;
    y /= len;
    z /= len;
  }
  const depth = 0.35 + 0.55 * hash01(id, 7);
  return { x: x * depth, y: y * depth, z: z * depth };
}

/**
 * What one stored step does on the globe. `visit` is where the agent's light goes, in order: the
 * papers a tool call looked at and then back to the run's own paper; null sends it home to its
 * island. Each paper it reaches lights up. `born` are the papers it found that the globe may not
 * show yet, spawned from the light; `flare` marks a tool call, which the light answers with a
 * flash; `ring` is a reading handed in.
 */
export function stepEffect(step: ActivityStep): { visit: string[] | null; born: string[]; flare: boolean; ring?: string } {
  switch (step.kind) {
    case "run_started":
      return { visit: [step.paper_id], born: [step.paper_id], flare: false };
    case "run_completed":
    case "run_failed":
      return { visit: [], born: [], flare: false };
    case "reading_submitted":
      return { visit: [step.paper_id], born: [], flare: false, ring: step.paper_id };
    case "tool_call":
      return { visit: [...step.looked_at, step.paper_id], born: step.looked_at, flare: true };
    default:
      return { visit: [step.paper_id], born: [], flare: false };
  }
}

/** The islands, by index, that selected a paper: none until it is selected. */
export function holdingIslands(paper: GlobePaper, islandIndex: ReadonlyMap<string, number>): number[] {
  if (paper.held !== true) return [];
  return paper.islands.flatMap((id) => {
    const i = islandIndex.get(id);
    return i === undefined ? [] : [i];
  });
}

/** The key of the nearest point within `within` pixels of (x, y), if any. */
export function nearest(points: readonly { x: number; y: number; key: string }[], x: number, y: number, within: number): string | null {
  let best: string | null = null;
  let gap = within;
  for (const p of points) {
    const d = Math.hypot(p.x - x, p.y - y);
    if (d <= gap) {
      gap = d;
      best = p.key;
    }
  }
  return best;
}

/** What a step is, in a few words, for the detail card. */
export function stepWords(step: ActivityStep): string {
  if (step.kind === "tool_call") {
    if (step.looked_at.length > 0) return `${step.tool ?? "a tool"}, looking at ${step.looked_at.length} other paper${step.looked_at.length === 1 ? "" : "s"}`;
    return `using ${step.tool ?? "a tool"}`;
  }
  if (step.kind === "paper_read") return step.passage_id ? `reading passage ${step.passage_id.split(":").pop()}` : "reading";
  if (step.kind === "model_call") return "thinking (a model call)";
  if (step.kind === "reading_submitted") return "handed in a reading";
  if (step.kind === "run_started") return "set out for a paper";
  if (step.kind === "run_completed") return "finished the run";
  if (step.kind === "run_failed") return "the run failed";
  return step.kind.replace(/_/g, " ");
}

/**
 * An agent's light: its island, where it is and how fast it moves, the stops still ahead (a paper
 * id, or null for home), the paper it is working on, its recent path for the trail, when it last
 * stepped and flared, how bright it is shown, and how far it is nudged on screen to sit on the
 * swaying dot it is at.
 */
type Light = {
  agent: string;
  islandId: string;
  pos: Vec;
  vel: Vec;
  route: (string | null)[];
  target: string | null;
  trail: { at: Vec; t: number }[];
  active: number;
  flare: number;
  last: ActivityStep | null;
  shown: number;
  nudge: { x: number; y: number };
};
/** A line from an island to a paper, as shown: its strength, and how much of it is live work. */
type Tie = { strength: number; live: number };
/**
 * A paper on the globe. `at` is where it sits, drifting to `goal`, its place by its island, so a
 * paper whose island becomes known moves there instead of jumping. `from` is where it spawned, a
 * light's place, and `lit` when a light last reached it. `seen` holds every island whose agents
 * looked at it. `shown`, `glow` and `solid` are its eased presence, light and holding; `ties` are
 * its lines.
 */
type Mark = {
  paper: GlobePaper;
  at: Vec;
  goal: Vec;
  goalKey: string;
  from: Vec | null;
  hue: number | null;
  born: number;
  touched: number;
  lit: number;
  seen: Set<number>;
  shove: { x: number; y: number };
  shown: number;
  glow: number;
  solid: number;
  ties: Map<number, Tie>;
};
type Ring = { to: string; hue: number; born: number };

export type Picked =
  | { kind: "paper"; paper: GlobePaper; readers: string[]; aboard: string[] }
  | { kind: "agent"; agent: string; island: string; paper: GlobePaper | null; last: ActivityStep | null }
  | { kind: "island"; island: Island };

const PULSE_MS = 5000;
/** How long a paper glows after a light reached it, and how long a spawned paper flies to its place. */
const LIT_MS = 2200;
const SPAWN_MS = 900;
const FLARE_MS = 700;
/** How long a light's trail lasts, and the most stops it keeps ahead. */
const TRAIL_MS = 520;
const ROUTE_MAX = 8;
/** How long an island's line to a paper stays after an agent touched it. */
const HOLD_LINE_MS = 30000;
/** How strong the steady line is from an island to a paper it selected. */
const HELD_LINE = 0.34;
const RING_MS = 1400;
/** Radians the globe turns per millisecond: once round in about a minute and a half. */
const SPIN = 0.000075;
/**
 * The feed is polled every few seconds. Steps that happened longer ago than `REPLAY_S` when the
 * page opens settle in place as they stand now; newer ones play out, keeping their real spacing
 * but squeezed into `PLAY_MS` so the globe keeps up with the next poll, and never more than
 * `LAG_MS` behind.
 */
const REPLAY_S = 12;
const PLAY_MS = 3600;
const MIN_GAP_MS = 240;
const LAG_MS = 1500;

const ZERO: Vec = { x: 0, y: 0, z: 0 };

/**
 * When a step happened, in Unix seconds. The feed sends an ISO-8601 time; a number is taken as
 * seconds already. A time that cannot be read counts as now, so it plays live rather than never.
 */
export function stepSeconds(createdAt: string | number): number {
  const seconds = typeof createdAt === "number" ? createdAt : Date.parse(createdAt) / 1000;
  return Number.isFinite(seconds) ? seconds : Date.now() / 1000;
}

/**
 * When to play new steps, in ms on the page clock `t`, given the play times still queued and the
 * steps' own times in seconds. A backlog running more than `LAG_MS` behind is squeezed to end by
 * then, keeping its order. The new steps follow it with their real spacing, squeezed to fit in
 * `PLAY_MS` and at least a short gap apart, so the globe keeps up with the feed and never plays a
 * newer step before an older one.
 */
export function pace(backlog: readonly number[], times: readonly number[], t: number): { backlog: number[]; at: number[] } {
  const head = backlog[0] ?? t;
  const tail = backlog.at(-1) ?? t;
  const squeezed = tail > t + LAG_MS ? backlog.map((at) => Math.max(t, head) + ((at - head) * (t + LAG_MS - Math.max(t, head))) / Math.max(1, tail - head)) : [...backlog];
  const start = Math.max(t, squeezed.at(-1) ?? t);
  const first = times[0] ?? 0;
  const span = ((times.at(-1) ?? first) - first) * 1000;
  const squeeze = span > PLAY_MS ? PLAY_MS / span : 1;
  const gap = Math.min(MIN_GAP_MS, PLAY_MS / Math.max(1, times.length));
  const at: number[] = [];
  let last = start - gap;
  for (const time of times) {
    last = Math.max(last + gap, start + Math.max(0, time - first) * 1000 * squeeze);
    at.push(last);
  }
  return { backlog: squeezed, at };
}

/**
 * The cover: a slowly turning glass globe of the storm, islands on the surface and papers inside,
 * sharp on the side facing the viewer and soft behind. A selected paper is a solid dot tied by a line to
 * each island that has it; a paper still waiting is a hollow ring. Each agent is a small light,
 * smaller than its island, that flies from paper to paper as it works; while it heads for or works
 * on a paper, a bright line ties that paper to the agent's island, and the line ebbs once it moves
 * on. A tool call flares it and sends it round the papers the tool looked at; a paper the globe did
 * not show yet spawns out of the light, flies to its place and pulses. An agent that stops stepping
 * fades out. Steps play in time with when they happened, and every line, glow and colour eases to
 * its new state, so nothing on the globe jumps. A click names the paper, agent or island under the
 * pointer. It stands still for a visitor who asks for reduced motion.
 */
export function Globe({
  islands,
  papers,
  known = [],
  steps = [],
  titles = {},
  readers = {},
}: {
  islands: readonly Island[];
  papers: number;
  known?: readonly GlobePaper[];
  steps?: readonly ActivityStep[];
  titles?: Readonly<Record<string, ActivityPaper>>;
  readers?: Readonly<Record<string, readonly string[]>>;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [picked, setPicked] = useState<Picked | null>(null);
  const scene = useMemo(() => globeScene(islands, Math.max(0, papers - known.length)), [islands, papers, known.length]);
  const islandIndex = useMemo(() => new Map(islands.map((island, i) => [island.id, i])), [islands]);

  // The animation runs once for the life of the globe; it reads the latest props through this.
  const now = useRef({ scene, islands, islandIndex, known: known.length, titles });
  useEffect(() => {
    now.current = { scene, islands, islandIndex, known: known.length, titles };
  }, [scene, islands, islandIndex, known.length, titles]);

  // Everything the animation moves lives here, outside React, and survives new props.
  const listed = useRef(new Set<string>());
  const live = useRef({
    marks: new Map<string, Mark>(),
    lights: new Map<string, Light>(),
    rings: [] as Ring[],
    queue: [] as { step: ActivityStep; at: number; age: number }[],
    seen: new Set<number>(),
    started: false,
    readers: new Map<string, Set<string>>(),
    hits: [] as { x: number; y: number; key: string }[],
    angle: 0,
    // The node of the island picked by a click, whose lines are drawn; -1 for none. The last one
    // picked keeps being drawn while its lines fade.
    selected: -1,
    drawnSelected: -1,
    shown: { islands: 0, edges: 0, selected: 0, dots: [] as number[], retiring: [] as { node: GlobeNode; alpha: number }[] },
    // The scene last drawn, so dots it had and the new one lacks can fade out.
    drawnScene: null as GlobeScene | null,
    // The pointer as wind: where it is, how fast it moves, and when it last moved.
    wind: { x: 0, y: 0, vx: 0, vy: 0, at: 0 },
  });
  const api = useApi();
  useEffect(() => {
    live.current.selected = picked?.kind === "island" ? scene.nodes.findIndex((n) => n.kind === "island" && islands[n.island]?.id === picked.island.id) : -1;
  }, [picked, scene, islands]);

  const islandOf = (id: string | undefined): number => now.current.islandIndex.get(id ?? "") ?? -1;
  const home = (island: number): Vec => {
    const [x, y, z] = direction(Math.max(0, island), Math.max(now.current.islands.length, 1), 1.1);
    return { x: x * 1.08, y: y * 1.08, z: z * 1.08 };
  };
  const lightHue = (light: Light): number => (islandHue(Math.max(0, islandOf(light.islandId))) + Math.round(hash01(light.agent) * 50 - 25) + 360) % 360;
  const paperOf = (id: string): GlobePaper => {
    const seen = live.current.marks.get(id)?.paper;
    if (seen && seen.title !== id) return seen;
    const t = now.current.titles[id];
    if (seen) return t ? { ...seen, title: t.title, islands: seen.islands.length > 0 ? seen.islands : t.islands } : seen;
    return { id, title: t?.title ?? id, islands: t?.islands ?? [], held: null };
  };
  const place = (paper: GlobePaper, hue: number | null, born: number, from: Vec | null = null) => {
    const marks = live.current.marks;
    const had = marks.get(paper.id);
    if (had) {
      if (paper.held !== null || had.paper.held === null) had.paper = { ...had.paper, ...paper, held: paper.held ?? had.paper.held };
      return;
    }
    const island = islandOf(paper.islands[0]);
    const n = now.current.islands.length;
    const at = paperPoint(paper.id, island, n);
    marks.set(paper.id, {
      paper,
      at,
      goal: at,
      goalKey: `${island}/${n}`,
      from,
      hue,
      born,
      touched: 0,
      lit: 0,
      seen: new Set(),
      shove: { x: 0, y: 0 },
      // A spawned paper is shown at once, flying out of its light; a listed one fades in.
      shown: born > 0 ? 1 : 0,
      glow: 0,
      solid: paper.held === false ? 0 : 1,
      ties: new Map(),
    });
  };

  // Known papers take their places, fading in without a pulse.
  useEffect(() => {
    const incoming = new Set(known.map((paper) => paper.id));
    const removed = new Set([...listed.current].filter((id) => !incoming.has(id)));
    for (const id of removed) live.current.marks.delete(id);
    setPicked((current) => current?.kind === "paper" && removed.has(current.paper.id) ? null : current);
    for (const paper of known) place(paper, null, 0);
    listed.current = incoming;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [known, islandIndex]);

  // New steps are queued to play in time with when they happened.
  useEffect(() => {
    const L = live.current;
    const t = performance.now();
    let fresh = steps.filter((s) => !L.seen.has(s.id));
    if (fresh.length === 0) return;
    for (const step of fresh) L.seen.add(step.id);
    const wall = Date.now() / 1000;
    if (!L.started) {
      // The first answer is history: what is already over settles where it stands now.
      L.started = true;
      for (const step of fresh) if (wall - stepSeconds(step.created_at) > REPLAY_S) L.queue.push({ step, at: t, age: (wall - stepSeconds(step.created_at)) * 1000 });
      fresh = fresh.filter((step) => wall - stepSeconds(step.created_at) <= REPLAY_S);
    }
    const timed = pace(
      L.queue.map((q) => q.at),
      fresh.map((step) => stepSeconds(step.created_at)),
      t,
    );
    L.queue.forEach((q, k) => (q.at = timed.backlog[k] ?? q.at));
    fresh.forEach((step, k) => L.queue.push({ step, at: timed.at[k] ?? t, age: 0 }));
  }, [steps]);

  /** A light reached a paper, or reached it `age` ms ago: it glows, and it is now in the light's island's view too. */
  const reach = (light: Light, id: string, t: number, age = 0) => {
    const mark = live.current.marks.get(id);
    if (!mark) return;
    if (age === 0) mark.lit = t;
    mark.touched = Math.max(mark.touched, t - age);
    const island = islandOf(light.islandId);
    if (island >= 0) mark.seen.add(island);
  };

  /** One step: the light moves, flares and spawns. A step `age` ms old only settles the light where the step left it. */
  const play = (step: ActivityStep, t: number, age: number) => {
    const L = live.current;
    let light = L.lights.get(step.agent);
    if (!light) {
      light = {
        agent: step.agent,
        islandId: step.island_id,
        pos: home(islandOf(step.island_id)),
        vel: ZERO,
        route: [],
        target: null,
        trail: [],
        active: -Infinity,
        flare: 0,
        last: null,
        shown: 0,
        nudge: { x: 0, y: 0 },
      };
      L.lights.set(step.agent, light);
    }
    light.islandId = step.island_id;
    // A light that had gone out comes back where it rested, without a trail across the globe.
    if (light.shown < 0.02) light.trail = [];
    light.last = step;
    light.active = t - age;
    const quiet = age > 0;
    const effect = stepEffect(step);
    const hue = lightHue(light);
    if (effect.flare && !quiet) light.flare = t;
    // Papers it found spawn out of the light and fly to their places.
    for (const id of effect.born) place(paperOf(id), hue, L.marks.has(id) || quiet ? 0 : t, light.pos);
    if (effect.visit === null) {
      light.target = null;
      light.route = [null];
    } else if (effect.visit.length > 0) {
      for (const id of effect.visit) if (!L.marks.has(id)) place(paperOf(id), hue, quiet ? 0 : t, light.pos);
      light.target = effect.visit.at(-1) ?? null;
      if (quiet) {
        for (const id of effect.visit) reach(light, id, t, age);
        light.route = [];
        light.pos = L.marks.get(light.target ?? "")?.at ?? light.pos;
        light.vel = ZERO;
      } else {
        // A burst of steps queues stops; past the most kept, the oldest are dropped.
        light.route = [...light.route, ...effect.visit].slice(-ROUTE_MAX);
      }
    }
    for (const id of [step.paper_id, ...step.looked_at]) {
      const who = L.readers.get(id) ?? new Set<string>();
      who.add(step.agent);
      L.readers.set(id, who);
    }
    if (effect.ring && !quiet) L.rings.push({ to: effect.ring, hue, born: t });
  };

  useEffect(() => {
    const cv = canvas.current;
    const ctx = cv?.getContext("2d") ?? null;
    if (!cv || !ctx) return;
    const L = live.current;
    let W = 0;
    let H = 0;
    const size = () => {
      const dpr = window.devicePixelRatio || 1;
      W = cv.clientWidth;
      H = cv.clientHeight;
      cv.width = W * dpr;
      cv.height = H * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    const still = typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    /** Moves everything `dt` ms on: the queue, the turn, the eased shows, the papers and the lights. */
    const advance = (t: number, dt: number) => {
      const C = now.current;
      while (L.queue.length > 0 && (L.queue[0]?.at ?? Infinity) <= t) {
        const next = L.queue.shift();
        if (next) play(next.step, t, next.age);
      }
      if (!still) L.angle += dt * SPIN;
      const shown = L.shown;
      shown.islands = ease(shown.islands, C.islands.length > 0 ? 1 : 0, dt, 450);
      // With the brief's papers known, their own holding lines replace the lines drawn from counts.
      shown.edges = ease(shown.edges, C.known > 0 ? 0 : 1, dt, 600);
      const dots = C.scene.nodes.length - C.islands.length;
      if (L.drawnScene !== C.scene) {
        const before = L.drawnScene?.nodes.filter((node) => node.kind === "paper") ?? [];
        for (let k = dots; k < before.length; k++) {
          const node = before[k];
          const alpha = shown.dots[k] ?? 0;
          if (node && alpha > 0.01) shown.retiring.push({ node, alpha });
        }
        L.drawnScene = C.scene;
      }
      for (const r of shown.retiring) r.alpha = ease(r.alpha, 0, dt, 600);
      shown.retiring = shown.retiring.filter((r) => r.alpha > 0.005);
      shown.dots.length = Math.min(shown.dots.length, dots);
      for (let k = 0; k < dots; k++) shown.dots[k] = ease(shown.dots[k] ?? 0, 1, dt, 700);
      if (L.selected >= 0) L.drawnSelected = L.selected;
      shown.selected = ease(shown.selected, L.selected >= 0 ? 1 : 0, dt, 160, 320);
      if (shown.selected < 0.002) L.drawnSelected = -1;

      const n = C.islands.length;
      for (const [id, mark] of L.marks) {
        const island = islandOf(mark.paper.islands[0]);
        const key = `${island}/${n}`;
        if (key !== mark.goalKey) {
          mark.goalKey = key;
          mark.goal = paperPoint(id, island, n);
        }
        const k = still ? 1 : 1 - Math.exp(-dt / 700);
        mark.at = add(mark.at, mul(add(mark.goal, mul(mark.at, -1)), k));
        mark.shown = ease(mark.shown, 1, dt, 500);
        mark.solid = ease(mark.solid, mark.paper.held === false ? 0 : 1, dt, 400);
      }
      for (const l of L.lights.values()) {
        // Each stop is a paper, or null for the island; a paper not on the globe is skipped.
        while (l.route.length > 0 && l.route[0] !== null && !L.marks.has(l.route[0] ?? "")) l.route.shift();
        const stop = l.route[0];
        const goal = stop === undefined ? null : stop === null ? home(islandOf(l.islandId)) : (L.marks.get(stop)?.at ?? null);
        if (still) {
          if (goal) l.pos = goal;
          l.vel = ZERO;
          if (stop !== undefined) {
            if (stop) reach(l, stop, t);
            l.route.shift();
          }
        } else {
          // More stops queued, a stronger pull, so a burst of tool calls is still followed.
          const flown = flyLight(l.pos, l.vel, goal, dt / 1000, 7 + 1.5 * Math.min(l.route.length, ROUTE_MAX));
          l.pos = flown.pos;
          l.vel = flown.vel;
          if (flown.reached) {
            if (stop) reach(l, stop, t);
            l.route.shift();
          }
          l.trail.push({ at: l.pos, t });
          while ((l.trail[0]?.t ?? t) < t - TRAIL_MS) l.trail.shift();
        }
        l.shown = ease(l.shown, lightAlpha(t - l.active), dt, 220, 300);
      }
    };

    const overlay = (proj: Projector, S: number, t: number, dt: number) => {
      const C = now.current;
      const hits: { x: number; y: number; key: string }[] = [];
      const surface = C.islands.map((_, i) => {
        const [x, y, z] = direction(i, Math.max(C.islands.length, 1), 1.1);
        return proj({ x, y, z });
      });
      // Every paper sits where it is, moved by the weather and by any gust the pointer made.
      const gusting = t - L.wind.at < 160;
      const settle = Math.exp(-dt / 200);
      const marks = [...L.marks.entries()].map(([id, mark]) => {
        // A paper just spawned flies out from the light that found it, easing into its place.
        const flight = mark.from && mark.born > 0 ? Math.min(1, (t - mark.born) / SPAWN_MS) : 1;
        const eased = 1 - (1 - flight) * (1 - flight) * (1 - flight);
        const p = proj(flight < 1 && mark.from ? add(mark.from, mul(add(mark.at, mul(mark.from, -1)), eased)) : mark.at);
        const w = still ? { x: 0, y: 0 } : weather(hash01(id, 3), t, S);
        if (gusting && !still) {
          const g = gust(p.x, p.y, L.wind.x, L.wind.y, L.wind.vx, L.wind.vy, 80 * S);
          mark.shove.x += (g.x * dt) / 16;
          mark.shove.y += (g.y * dt) / 16;
        }
        mark.shove.x *= settle;
        mark.shove.y *= settle;
        return { id, mark, p: { x: p.x + w.x + mark.shove.x, y: p.y + w.y + mark.shove.y, z: p.z } };
      });
      const placed = new Map(marks.map((m) => [m.id, m.p]));
      // How hard each island works on each paper right now: the brightest of its lights flying to
      // the paper, or working on it once its route is done. The rest of a route waits its turn,
      // and a light flying home ties to nothing.
      const working = new Map<string, Map<number, number>>();
      for (const light of L.lights.values()) {
        const island = islandOf(light.islandId);
        if (light.shown <= 0.01 || island < 0) continue;
        const id = light.route.length > 0 ? light.route[0] : light.target;
        if (!id) continue;
        const by = working.get(id) ?? new Map<number, number>();
        by.set(island, Math.max(by.get(island) ?? 0, light.shown));
        working.set(id, by);
      }
      // Lines. A selected paper keeps a steady line to every island that kept it; a paper an agent is
      // on gets a bright live line from that agent's island, which ebbs to a faint one for a while
      // after it leaves. Each line eases to its strength, so work swells in and ebbs out.
      for (const { id, mark, p } of marks) {
        const holders = holdingIslands(mark.paper, C.islandIndex);
        const active = working.get(id);
        const age = t - mark.touched;
        const fade = mark.touched === 0 || age > HOLD_LINE_MS ? 0 : 1 - age / HOLD_LINE_MS;
        const islandsHere = new Set([...holders, ...(active?.keys() ?? []), ...(fade > 0 ? mark.seen : []), ...mark.ties.keys()]);
        for (const i of islandsHere) {
          const liveNow = active?.get(i) ?? 0;
          const goal = Math.max(holders.includes(i) ? HELD_LINE : 0, liveNow, mark.seen.has(i) ? 0.42 * fade : 0);
          const tie = mark.ties.get(i) ?? { strength: 0, live: 0 };
          tie.strength = ease(tie.strength, goal, dt, 260, 900);
          tie.live = ease(tie.live, liveNow, dt, 200, 700);
          if (goal === 0 && tie.strength < 0.004) {
            mark.ties.delete(i);
            continue;
          }
          mark.ties.set(i, tie);
          const A = surface[i];
          if (!A) continue;
          const f = focus((A.z + p.z) / 2);
          const visibility = Math.max(0.38 + 0.22 * tie.live, facing(A.z));
          const alpha = tie.strength * f.alpha * visibility * mark.shown * L.shown.islands;
          if (alpha < 0.003) continue;
          ctx.strokeStyle = `hsla(${islandHue(i)},85%,${(40 - 4 * tie.live).toFixed(1)}%,${alpha.toFixed(3)})`;
          ctx.lineWidth = (0.95 + 0.85 * tie.live) * S;
          ctx.beginPath();
          ctx.moveTo(A.x, A.y);
          ctx.lineTo(p.x, p.y);
          ctx.stroke();
        }
      }
      // Papers back to front: held solid, waiting hollow, both in focus only near the viewer.
      marks.sort((u, v) => u.p.z - v.p.z);
      for (const { id, mark, p } of marks) {
        const f = focus(p.z);
        const age = t - mark.born;
        const pulse = mark.born > 0 ? Math.max(0, 1 - age / PULSE_MS) : 0;
        const hue = mark.hue ?? islandHue(Math.max(0, islandOf(mark.paper.islands[0])));
        // Depth shows in the dot itself: near ones large and dark, far ones small and pale.
        const r = (1.1 + 2.8 * f.near) * S;
        const base = 62 - 28 * f.near;
        // A paper a light is on stays bright; after the light moves on, the glow dims.
        let on = 0;
        for (const v of working.get(id)?.values() ?? []) on = Math.max(on, v);
        const lit = mark.lit > 0 ? Math.max(0, 1 - (t - mark.lit) / LIT_MS) : 0;
        mark.glow = ease(mark.glow, Math.max(on, lit), dt, 120, 450);
        const glow = mark.glow;
        const a = mark.shown;
        if (glow > 0.01) {
          const g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, r * 6);
          g.addColorStop(0, `hsla(${hue},100%,58%,${(0.95 * glow * a).toFixed(3)})`);
          g.addColorStop(0.35, `hsla(${hue},100%,62%,${(0.45 * glow * a).toFixed(3)})`);
          g.addColorStop(1, `hsla(${hue},100%,62%,0)`);
          ctx.fillStyle = g;
          ctx.beginPath();
          ctx.arc(p.x, p.y, r * 6, 0, 6.283);
          ctx.fill();
        }
        if (pulse > 0) {
          const beat = (Math.sin(age / 160) + 1) / 2;
          ctx.fillStyle = `hsla(${hue},95%,55%,${(pulse * (0.22 + 0.1 * beat) * f.alpha).toFixed(3)})`;
          ctx.beginPath();
          ctx.arc(p.x, p.y, r * (1.7 + 0.9 * beat), 0, 6.283);
          ctx.fill();
        }
        // Waiting and held cross-fade, so a paper being kept fills in rather than flipping.
        if (mark.solid < 0.99) {
          ctx.strokeStyle = `rgba(30,30,30,${(0.75 * f.alpha * a * (1 - mark.solid)).toFixed(3)})`;
          ctx.lineWidth = Math.max(0.7, 1.1 * S - f.blur * 0.2);
          ctx.beginPath();
          ctx.arc(p.x, p.y, r + f.blur * 0.4, 0, 6.283);
          ctx.stroke();
        }
        if (mark.solid > 0.01) {
          const hot = Math.max(glow, pulse);
          softDot(ctx, p.x, p.y, r, f.blur * S, `hsla(${hue},${(70 + 20 * glow).toFixed(1)}%,${(base + (50 - base) * hot).toFixed(1)}%,`, f.alpha * a * mark.solid);
        }
        if (a > 0.3) hits.push({ x: p.x, y: p.y, key: `p:${id}` });
      }
      L.rings = L.rings.filter((f) => t - f.born < RING_MS);
      for (const f of L.rings) {
        const mark = L.marks.get(f.to);
        if (!mark) continue;
        const p = placed.get(f.to) ?? proj(mark.at);
        const k = (t - f.born) / RING_MS;
        ctx.strokeStyle = `hsla(${f.hue},90%,45%,${(1 - k).toFixed(3)})`;
        ctx.lineWidth = 1.5 * S;
        ctx.beginPath();
        ctx.arc(p.x, p.y, (4 + 22 * k) * S, 0, 6.283);
        ctx.stroke();
      }
      // Lights last, nearest on top: a bright point smaller than an island, a fading trail of where
      // it has been, and a flash when a tool call goes out. An idle light fades away.
      const lights = [...L.lights.values()].map((l) => ({ l, p: proj(l.pos) })).sort((u, v) => u.p.z - v.p.z);
      for (const { l, p } of lights) {
        // Near a paper the light takes on the paper's sway, so it sits on the dot it lit.
        const stop = l.route[0] ?? l.target;
        const mark = stop ? L.marks.get(stop) : undefined;
        const spot = stop ? placed.get(stop) : undefined;
        let dx = 0;
        let dy = 0;
        if (mark && spot) {
          const q = proj(mark.at);
          const close = Math.max(0, 1 - Math.hypot(l.pos.x - mark.at.x, l.pos.y - mark.at.y, l.pos.z - mark.at.z) / 0.15);
          dx = (spot.x - q.x) * close;
          dy = (spot.y - q.y) * close;
        }
        const k = 1 - Math.exp(-dt / 120);
        l.nudge.x += (dx - l.nudge.x) * k;
        l.nudge.y += (dy - l.nudge.y) * k;
        const alpha = l.shown;
        if (alpha <= 0.004) continue;
        const hue = lightHue(l);
        const f = focus(p.z);
        ctx.lineCap = "round";
        for (let j = 1; j < l.trail.length; j++) {
          const from = l.trail[j - 1];
          const to = l.trail[j];
          if (!from || !to) continue;
          const A = proj(from.at);
          const B = proj(to.at);
          const fresh = Math.max(0, 1 - (t - to.t) / TRAIL_MS);
          ctx.strokeStyle = `hsla(${hue},100%,55%,${(0.55 * fresh * alpha * f.alpha).toFixed(3)})`;
          ctx.lineWidth = (0.4 + 1.4 * fresh) * S;
          ctx.beginPath();
          ctx.moveTo(A.x + l.nudge.x * fresh, A.y + l.nudge.y * fresh);
          ctx.lineTo(B.x + l.nudge.x * fresh, B.y + l.nudge.y * fresh);
          ctx.stroke();
        }
        ctx.lineCap = "butt";
        const x = p.x + l.nudge.x;
        const y = p.y + l.nudge.y;
        const flare = l.flare > 0 ? Math.max(0, 1 - (t - l.flare) / FLARE_MS) : 0;
        if (flare > 0) {
          ctx.strokeStyle = `hsla(${hue},100%,55%,${(0.8 * flare * alpha).toFixed(3)})`;
          ctx.lineWidth = 1 * S;
          ctx.beginPath();
          ctx.arc(x, y, (2 + 9 * (1 - flare)) * S, 0, 6.283);
          ctx.stroke();
        }
        const twinkle = still ? 1 : 0.85 + 0.15 * Math.sin(t / 140 + hash01(l.agent) * 6.283);
        const halo = (3.2 + 1.5 * flare) * S;
        const g = ctx.createRadialGradient(x, y, 0, x, y, halo);
        g.addColorStop(0, `hsla(${hue},100%,60%,${(0.8 * alpha * twinkle).toFixed(3)})`);
        g.addColorStop(1, `hsla(${hue},100%,60%,0)`);
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(x, y, halo, 0, 6.283);
        ctx.fill();
        ctx.fillStyle = `hsla(${hue},100%,92%,${alpha.toFixed(3)})`;
        ctx.beginPath();
        ctx.arc(x, y, 1.3 * S, 0, 6.283);
        ctx.fill();
        if (alpha > 0.3) hits.push({ x, y, key: `a:${l.agent}` });
      }
      return hits;
    };

    let frame = 0;
    let last = performance.now();
    const paint = (t: number) => {
      if (!(W > 40 && H > 40)) size();
      if (!(W > 40 && H > 40)) return;
      // A frame's time, capped so a tab coming back from the background resumes rather than leaps.
      const dt = Math.min(64, Math.max(0, t - last));
      last = t;
      advance(t, dt);
      const C = now.current;
      const shown = L.shown;
      const { proj, S } = draw(ctx, C.scene, W, H, L.angle, L.drawnSelected, { dot: (k) => shown.dots[k] ?? 0, islands: shown.islands, edges: shown.edges, selected: shown.selected, retiring: shown.retiring });
      const hits = overlay(proj, S, t, dt);
      const surface = C.scene.nodes.flatMap((n, k) => {
        if (n.kind !== "island") return [];
        const p = proj(n);
        return islandSeen(p.z) * shown.islands > 0.2 ? [{ x: p.x, y: p.y, key: `i:${k}` }] : [];
      });
      L.hits = [...surface, ...hits];
    };
    const onResize = () => {
      size();
      paint(performance.now());
    };
    size();
    paint(performance.now());
    window.addEventListener("resize", onResize);
    const tick = (t: number) => {
      paint(t);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", onResize);
    };
    // The loop runs once and reads the latest props through `now`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onClick = (event: MouseEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const L = live.current;
    // Lights are small and move: they win a near tie, then papers, then islands.
    const key =
      nearest(L.hits.filter((h) => h.key.startsWith("a:")), x, y, 16) ??
      nearest(L.hits.filter((h) => h.key.startsWith("p:")), x, y, 12) ??
      nearest(L.hits.filter((h) => h.key.startsWith("i:")), x, y, 18);
    if (key === null) {
      setPicked(null);
      return;
    }
    const id = key.slice(2);
    if (key.startsWith("a:")) {
      const light = L.lights.get(id);
      setPicked({ kind: "agent", agent: id, island: light?.islandId ?? "", paper: light?.target ? paperOf(light.target) : null, last: light?.last ?? null });
    } else if (key.startsWith("p:")) {
      const who = new Set([...(readers[id] ?? []), ...(L.readers.get(id) ?? [])]);
      const aboard = [...L.lights.values()].filter((l) => l.target === id && l.shown > 0.05).map((l) => l.agent);
      setPicked({ kind: "paper", paper: paperOf(id), readers: [...who].sort(), aboard });
      // Reading the paper's record counts as use of it, which the swarm's breeder is shown:
      // a click here is a small hand on what comes next.
      api
        .get<{ thesis?: string | null; takeaways?: { text: string }[] | null; used?: number | null }>(`/api/v1/public/papers/${encodeURIComponent(id)}`)
        .then((record) => {
          const mark = L.marks.get(id);
          if (!mark) return;
          mark.paper = { ...mark.paper, thesis: record.thesis ?? null, takeaways: (record.takeaways ?? []).map((t) => t.text), used: record.used ?? null };
          setPicked((was) => (was?.kind === "paper" && was.paper.id === id ? { ...was, paper: mark.paper } : was));
        })
        .catch(() => undefined);
    } else {
      const island = islands[scene.nodes[Number(id)]?.island ?? -1];
      if (island) setPicked({ kind: "island", island });
    }
  };

  return (
    <div className="hero globe">
      <canvas
        ref={canvas}
        role="img"
        onClick={onClick}
        onMouseMove={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          const x = event.clientX - rect.left;
          const y = event.clientY - rect.top;
          const w = live.current.wind;
          const dt = Math.max(16, performance.now() - w.at);
          w.vx = w.at === 0 ? 0 : ((x - w.x) / dt) * 16;
          w.vy = w.at === 0 ? 0 : ((y - w.y) / dt) * 16;
          w.x = x;
          w.y = y;
          w.at = performance.now();
        }}
        aria-label="the storm as a turning globe: islands on the surface, papers inside, agents as small lights trailing between the papers they read"
      />
      {picked !== null && <PickedCard picked={picked} onClose={() => setPicked(null)} />}
    </div>
  );
}

function PickedCard({ picked, onClose }: { picked: Picked; onClose: () => void }) {
  let body;
  if (picked.kind === "paper") {
    const p = picked.paper;
    body = (
      <>
        <b>{p.title}</b>
        <div className="meta">
          <a href={`https://arxiv.org/abs/${encodeURIComponent(p.id)}`} target="_blank" rel="noreferrer">
            arXiv {p.id}
          </a>
          {p.islands.length > 0 && <> · islands {p.islands.join(", ")}</>}
          {typeof p.readings === "number" && <> · {p.readings} reading{p.readings === 1 ? "" : "s"}</>}
        </div>
        <div>
          {p.held === true
            ? "Selected by readers or a person. Guides future island readings."
            : p.held === false
              ? `Waiting for a selection decision. Expires in ${p.daysLeft ?? "?"} days if unread.`
              : "Looked up by an agent; not yet in the brief's lists."}
        </div>
        <div>
          {picked.aboard.length > 0 ? <>Reading it now: {picked.aboard.join(", ")}. </> : null}
          {picked.readers.length > 0 ? <>Touched by: {picked.readers.join(", ")}.</> : "No agent seen on it yet."}
        </div>
        {p.thesis && <div className="meta">“{p.thesis}”</div>}
        {p.takeaways && p.takeaways.length > 0 && (
          <ul className="takeaways">
            {p.takeaways.slice(0, 3).map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        )}
        {typeof p.used === "number" && <div className="meta">asked for {p.used} time{p.used === 1 ? "" : "s"}; the swarm's breeder sees that</div>}
      </>
    );
  } else if (picked.kind === "agent") {
    body = (
      <>
        <b>{picked.agent}</b>
        <div className="meta">an agent of island {picked.island}</div>
        <div>{picked.paper ? <>Working on {picked.paper.title} ({picked.paper.id}).</> : "At home on its island."}</div>
        {picked.last && <div className="meta">last step: {stepWords(picked.last)}</div>}
      </>
    );
  } else {
    const i = picked.island;
    body = (
      <>
        <b>{i.name}</b>
        <div className="meta">{i.focus}</div>
        <div>
          {i.paper_count ?? "?"} papers · {i.run_count ?? "?"} runs · {i.agent_count ?? "?"} agents
        </div>
      </>
    );
  }
  return (
    <div className="picked" role="dialog" aria-label="what you clicked">
      <button type="button" className="quiet close" onClick={onClose} aria-label="close">
        ×
      </button>
      {body}
    </div>
  );
}
