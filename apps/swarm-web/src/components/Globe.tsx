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
 * depend only on the counts, so the same storm always draws the same globe.
 */
export function globeScene(islands: readonly Island[], papers: number): GlobeScene {
  const nodes: GlobeNode[] = islands.map((_, i) => {
    const [x, y, z] = direction(i, Math.max(islands.length, 1), 1.1);
    return { x, y, z, kind: "island", island: i };
  });
  const drawn = Math.min(Math.max(0, Math.floor(papers)), MAX_PAPERS);
  const counted = islands.length > 0 && islands.every((i) => typeof i.paper_count === "number");
  const total = islands.reduce((sum, i) => sum + (i.paper_count ?? 0), 0);
  // Each dot's island, in proportion to the islands' paper counts.
  const owner: number[] = [];
  if (counted && total > 0) {
    islands.forEach((isl, i) => {
      const dots = Math.round(((isl.paper_count ?? 0) / total) * drawn);
      for (let k = 0; k < dots && owner.length < drawn; k++) owner.push(i);
    });
  }
  const firstPaper = nodes.length;
  for (let k = 0; k < drawn; k++) {
    let [x, y, z] = direction(k, drawn, 0.4);
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

/** Paints the globe and returns how it projected, so the marks drawn over it line up. */
function draw(ctx: CanvasRenderingContext2D, scene: GlobeScene, W: number, H: number, angle: number, selected: number): { proj: Projector; S: number; R: number } {
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
    const vis = Math.max(0, Math.min(1, ((A.z + B.z) / 2 + 0.8) / 1.2)) * facing(A.z);
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
  const order = P.map((_, k) => k).sort((u, v) => (P[u]?.z ?? 0) - (P[v]?.z ?? 0));
  for (const k of order) {
    const p = P[k];
    const n = scene.nodes[k];
    if (!p || !n) continue;
    const depth = (p.z + 1) / 2;
    if (n.kind === "paper") {
      // A paper the brief does not list: a faint speck, softer the farther back it sits.
      const f = focus(p.z);
      softDot(ctx, p.x, p.y, (0.5 + 1.0 * f.near) * S, f.blur * S, n.island >= 0 ? `hsla(${islandHue(n.island)},30%,${Math.round(58 - 18 * f.near)}%,` : "rgba(60,60,60,", 0.22 * f.alpha);
      continue;
    }
    // An island sits on a radial point of the shell; the dot is the island. On the far side it is
    // a mark on the inner wall, seen through the open front. The selected island also gets two of
    // the sphere's own lines through it, its parallel and its meridian, all the way round, each
    // pressed harder near the point so the crossing stands out.
    const hue = islandHue(n.island);
    const back = p.z < 0;
    const seen = islandSeen(p.z);
    if (seen <= 0) continue;
    const rr = 5.5 * (0.7 + 0.5 * depth) * S;
    ctx.globalAlpha = seen;
    for (const line of k === selected ? islandLines(n) : []) {
      // The whole line, thin, on both halves; the near half darker.
      for (const [side, alpha] of [[false, 0.14], [true, 0.4]] as const) {
        ctx.strokeStyle = `hsla(${hue},70%,40%,${alpha})`;
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
      ctx.strokeStyle = `hsla(${hue},75%,38%,${back ? 0.45 : 0.85})`;
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
 * One frame of a light's flight: it moves a share `k` of the way to its first stop, and says
 * whether it got there, so the caller can take that stop off the route.
 */
export function flyLight(pos: Vec, route: readonly Vec[], k: number): { pos: Vec; reached: boolean } {
  const goal = route[0];
  if (!goal) return { pos, reached: false };
  const next = add(pos, mul(add(goal, mul(pos, -1)), k));
  const left = add(goal, mul(next, -1));
  return { pos: next, reached: Math.hypot(left.x, left.y, left.z) < ARRIVED };
}

/** A paper the globe knows by id: held for good, waiting to be let go, or just looked up. */
export type GlobePaper = {
  id: string;
  title: string;
  islands: string[];
  /** True when held for good, false while waiting, null when the globe only saw it looked up. */
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
      return { visit: null, born: [], flare: false };
    case "reading_submitted":
      return { visit: [step.paper_id], born: [], flare: false, ring: step.paper_id };
    case "tool_call":
      return { visit: [...step.looked_at, step.paper_id], born: step.looked_at, flare: true };
    default:
      return { visit: [step.paper_id], born: [], flare: false };
  }
}

/** The islands, by index, that decided to hold a paper: none until it is held for good. */
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
 * An agent's light: where it is, the stops still ahead (a paper id, or null for home), the paper
 * it is working on, its recent path for the trail, and when it last stepped and last flared.
 */
type Light = {
  agent: string;
  island: number;
  hue: number;
  pos: Vec;
  route: (string | null)[];
  target: string | null;
  trail: Vec[];
  active: number;
  flare: number;
  last: ActivityStep | null;
};
/** `seen` holds every island whose agents looked at the paper, beside the islands it is assigned to. */
/** `from` is where a paper spawned, a light's place, and `lit` when a light last reached it. */
type Mark = { paper: GlobePaper; at: Vec; from: Vec | null; hue: number | null; born: number; touched: number; lit: number; seen: Set<number>; shove: { x: number; y: number } };
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
/** Frames of path a light trails behind it, and the most stops it keeps ahead. */
const TRAIL = 16;
const ROUTE_MAX = 8;
/** How long an island's holding line to a paper stays after an agent touched it. */
const HOLD_LINE_MS = 9000;
/** How strong the steady line is from an island to a paper it decided to hold. */
const HELD_LINE = 0.16;
const RING_MS = 1400;

/**
 * The cover: a slowly turning glass globe of the storm, islands on the surface and papers inside,
 * sharp on the side facing the viewer and soft behind. A held paper is a solid dot tied by a line to
 * each island that has it or whose agents looked at it; a paper still waiting is a hollow ring. Each
 * agent is a small light, smaller than its island, that trails from paper to paper as it works and
 * lights up each paper it reaches. A tool call flares it and sends it round the papers the tool
 * looked at; a paper the globe did not show yet spawns out of the light, flies to its place and
 * pulses. An agent that stops stepping fades out. A click names the paper, agent or island under the
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
  const scene = useMemo(() => {
    const drawn = globeScene(islands, Math.max(0, papers - known.length));
    // With the brief's papers known, their own holding lines replace the lines drawn from counts.
    return known.length > 0 ? { ...drawn, edges: [] } : drawn;
  }, [islands, papers, known.length]);
  const islandIndex = useMemo(() => new Map(islands.map((island, i) => [island.id, i])), [islands]);

  // Everything the animation moves lives here, outside React, and survives new props.
  const live = useRef({
    marks: new Map<string, Mark>(),
    lights: new Map<string, Light>(),
    rings: [] as Ring[],
    queue: [] as { step: ActivityStep; at: number }[],
    seen: new Set<number>(),
    readers: new Map<string, Set<string>>(),
    hits: [] as { x: number; y: number; key: string }[],
    // The node of the island picked by a click, whose lines are drawn; -1 for none.
    selected: -1,
    // The pointer as wind: where it is, how fast it moves, and when it last moved.
    wind: { x: 0, y: 0, vx: 0, vy: 0, at: 0 },
  });
  const api = useApi();
  useEffect(() => {
    live.current.selected = picked?.kind === "island" ? scene.nodes.findIndex((n) => n.kind === "island" && islands[n.island]?.id === picked.island.id) : -1;
  }, [picked, scene, islands]);

  const home = (island: number): Vec => {
    const [x, y, z] = direction(Math.max(0, island), Math.max(islands.length, 1), 1.1);
    return { x: x * 1.08, y: y * 1.08, z: z * 1.08 };
  };
  // The animation outlives a render, so it reads titles through a ref that is always current.
  const titlesNow = useRef(titles);
  useEffect(() => {
    titlesNow.current = titles;
  }, [titles]);
  const paperOf = (id: string): GlobePaper => {
    const seen = live.current.marks.get(id)?.paper;
    if (seen && seen.title !== id) return seen;
    const t = titlesNow.current[id];
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
    const island = islandIndex.get(paper.islands[0] ?? "") ?? -1;
    marks.set(paper.id, { paper, at: paperPoint(paper.id, island, islands.length), from, hue, born, touched: 0, lit: 0, seen: new Set(), shove: { x: 0, y: 0 } });
  };

  // Known papers take their places at once, without a pulse.
  useEffect(() => {
    for (const paper of known) place(paper, null, 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [known, islandIndex]);

  // New steps are queued and played a beat apart, so a burst reads as work rather than a flash.
  useEffect(() => {
    const L = live.current;
    const now = performance.now();
    let at = Math.max(now, L.queue.at(-1)?.at ?? now);
    const fresh = steps.filter((s) => !L.seen.has(s.id));
    const gap = fresh.length > 40 ? 120 : 420;
    for (const step of fresh) {
      L.seen.add(step.id);
      at += gap;
      L.queue.push({ step, at });
    }
  }, [steps]);

  const play = (step: ActivityStep, now: number) => {
    const L = live.current;
    const island = islandIndex.get(step.island_id) ?? 0;
    const hue = (islandHue(island) + Math.round(hash01(step.agent) * 50 - 25) + 360) % 360;
    let light = L.lights.get(step.agent);
    if (!light) {
      light = { agent: step.agent, island, hue, pos: home(island), route: [], target: null, trail: [], active: 0, flare: 0, last: null };
      L.lights.set(step.agent, light);
    }
    // A light that had gone out comes back where it rested, without a trail across the globe.
    if (lightAlpha(now - light.active) === 0) light.trail = [];
    light.last = step;
    light.active = now;
    const effect = stepEffect(step);
    if (effect.flare) light.flare = now;
    // Papers it found spawn out of the light and fly to their places.
    for (const id of effect.born) place(paperOf(id), hue, L.marks.has(id) ? 0 : now, light.pos);
    if (effect.visit === null) {
      light.target = null;
      light.route = [null];
    } else if (effect.visit.length > 0) {
      for (const id of effect.visit) if (!L.marks.has(id)) place(paperOf(id), hue, now, light.pos);
      light.target = effect.visit.at(-1) ?? null;
      // A burst of steps queues stops; past the most kept, the oldest are dropped.
      light.route = [...light.route, ...effect.visit].slice(-ROUTE_MAX);
    }
    for (const id of [step.paper_id, ...step.looked_at]) {
      const who = L.readers.get(id) ?? new Set<string>();
      who.add(step.agent);
      L.readers.set(id, who);
    }
    if (effect.ring) L.rings.push({ to: effect.ring, hue, born: now });
  };

  /** A light reached a paper: it glows, and it is now in the light's island's view too. */
  const reach = (light: Light, id: string, now: number) => {
    const mark = live.current.marks.get(id);
    if (!mark) return;
    mark.lit = now;
    mark.touched = now;
    mark.seen.add(light.island);
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
    let angle = 0;

    const overlay = (proj: Projector, S: number, now: number) => {
      const hits: { x: number; y: number; key: string }[] = [];
      const surface = islands.map((_, i) => {
        const [x, y, z] = direction(i, Math.max(islands.length, 1), 1.1);
        return proj({ x, y, z });
      });
      // Every paper sits where it is, moved by the weather and by any gust the pointer made.
      const gusting = now - L.wind.at < 160;
      const marks = [...L.marks.entries()].map(([id, mark]) => {
        // A paper just spawned flies out from the light that found it, easing into its place.
        const flight = mark.from && mark.born > 0 ? Math.min(1, (now - mark.born) / SPAWN_MS) : 1;
        const ease = 1 - (1 - flight) * (1 - flight) * (1 - flight);
        const p = proj(flight < 1 && mark.from ? add(mark.from, mul(add(mark.at, mul(mark.from, -1)), ease)) : mark.at);
        const w = still ? { x: 0, y: 0 } : weather(hash01(id, 3), now, S);
        if (gusting && !still) {
          const g = gust(p.x, p.y, L.wind.x, L.wind.y, L.wind.vx, L.wind.vy, 80 * S);
          mark.shove.x += g.x;
          mark.shove.y += g.y;
        }
        mark.shove.x *= 0.92;
        mark.shove.y *= 0.92;
        return { id, mark, p: { x: p.x + w.x + mark.shove.x, y: p.y + w.y + mark.shove.y, z: p.z } };
      });
      const placed = new Map(marks.map((m) => [m.id, m.p]));
      // Holding lines. A paper an island decided to hold keeps a steady line to that island; a
      // paper in play also gets a brighter line from each island whose agents touched it in the
      // last moments, fading back to the steady one, or to nothing for a paper not held.
      for (const { mark, p } of marks) {
        const holders = holdingIslands(mark.paper, islandIndex);
        const age = now - mark.touched;
        const fade = mark.touched === 0 || age > HOLD_LINE_MS ? 0 : 1 - age / HOLD_LINE_MS;
        for (const i of new Set([...holders, ...(fade > 0 ? mark.seen : [])])) {
          const A = surface[i];
          if (!A) continue;
          const strength = Math.max(holders.includes(i) ? HELD_LINE : 0, 0.35 * fade);
          const f = focus((A.z + p.z) / 2);
          ctx.strokeStyle = `hsla(${islandHue(i)},70%,40%,${(strength * f.alpha * Math.max(0.2, facing(A.z))).toFixed(3)})`;
          ctx.lineWidth = 0.8 * S;
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
        const age = now - mark.born;
        const pulsing = mark.born > 0 && age < PULSE_MS;
        const hue = mark.hue ?? islandHue(islandIndex.get(mark.paper.islands[0] ?? "") ?? 0);
        // Depth shows in the dot itself: near ones large and dark, far ones small and pale.
        const r = (1.1 + 2.8 * f.near) * S;
        const light = Math.round(62 - 28 * f.near);
        // A paper a light just reached glows in the light's color, dimming as it lets go.
        const lit = mark.lit > 0 ? Math.max(0, 1 - (now - mark.lit) / LIT_MS) : 0;
        if (lit > 0) {
          const g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, r * 4);
          g.addColorStop(0, `hsla(${hue},100%,62%,${(0.75 * lit).toFixed(3)})`);
          g.addColorStop(1, `hsla(${hue},100%,62%,0)`);
          ctx.fillStyle = g;
          ctx.beginPath();
          ctx.arc(p.x, p.y, r * 4, 0, 6.283);
          ctx.fill();
        }
        if (pulsing) {
          const beat = (Math.sin(age / 160) + 1) / 2;
          ctx.fillStyle = `hsla(${hue},95%,55%,${((0.22 * (1 - age / PULSE_MS) + 0.1 * beat) * f.alpha).toFixed(3)})`;
          ctx.beginPath();
          ctx.arc(p.x, p.y, r * (1.7 + 0.9 * beat), 0, 6.283);
          ctx.fill();
        }
        if (mark.paper.held === false) {
          ctx.strokeStyle = `rgba(30,30,30,${(0.75 * f.alpha).toFixed(3)})`;
          ctx.lineWidth = Math.max(0.7, 1.1 * S - f.blur * 0.2);
          ctx.beginPath();
          ctx.arc(p.x, p.y, r + f.blur * 0.4, 0, 6.283);
          ctx.stroke();
        } else {
          softDot(ctx, p.x, p.y, r, f.blur * S, `hsla(${hue},${lit > 0 ? 90 : 70}%,${pulsing || lit > 0 ? 50 : light}%,`, f.alpha);
        }
        hits.push({ x: p.x, y: p.y, key: `p:${id}` });
      }
      L.rings = L.rings.filter((f) => now - f.born < RING_MS);
      for (const f of L.rings) {
        const mark = L.marks.get(f.to);
        if (!mark) continue;
        const p = placed.get(f.to) ?? proj(mark.at);
        const t = (now - f.born) / RING_MS;
        ctx.strokeStyle = `hsla(${f.hue},90%,45%,${(1 - t).toFixed(3)})`;
        ctx.lineWidth = 1.5 * S;
        ctx.beginPath();
        ctx.arc(p.x, p.y, (4 + 22 * t) * S, 0, 6.283);
        ctx.stroke();
      }
      // Lights last, nearest on top: a bright point smaller than an island, a fading trail of where
      // it has been, and a flash when a tool call goes out. An idle light fades away.
      const lights = [...L.lights.values()].map((l) => ({ l, p: proj(l.pos) })).sort((u, v) => u.p.z - v.p.z);
      for (const { l, p } of lights) {
        const alpha = lightAlpha(now - l.active);
        if (alpha <= 0) continue;
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
        const f = focus(p.z);
        const trail = l.trail.map(proj);
        ctx.lineCap = "round";
        for (let k = 1; k < trail.length; k++) {
          const A = trail[k - 1];
          const B = trail[k];
          if (!A || !B) continue;
          const t = k / trail.length;
          ctx.strokeStyle = `hsla(${l.hue},100%,55%,${(0.55 * t * alpha * f.alpha).toFixed(3)})`;
          ctx.lineWidth = (0.4 + 1.4 * t) * S;
          ctx.beginPath();
          ctx.moveTo(A.x + dx * t, A.y + dy * t);
          ctx.lineTo(B.x + dx * t, B.y + dy * t);
          ctx.stroke();
        }
        ctx.lineCap = "butt";
        const x = p.x + dx;
        const y = p.y + dy;
        const flare = l.flare > 0 ? Math.max(0, 1 - (now - l.flare) / FLARE_MS) : 0;
        if (flare > 0) {
          ctx.strokeStyle = `hsla(${l.hue},100%,55%,${(0.8 * flare * alpha).toFixed(3)})`;
          ctx.lineWidth = 1 * S;
          ctx.beginPath();
          ctx.arc(x, y, (2 + 9 * (1 - flare)) * S, 0, 6.283);
          ctx.stroke();
        }
        const twinkle = still ? 1 : 0.85 + 0.15 * Math.sin(now / 140 + hash01(l.agent) * 6.283);
        const halo = (3.2 + 1.5 * flare) * S;
        const g = ctx.createRadialGradient(x, y, 0, x, y, halo);
        g.addColorStop(0, `hsla(${l.hue},100%,60%,${(0.8 * alpha * twinkle).toFixed(3)})`);
        g.addColorStop(1, `hsla(${l.hue},100%,60%,0)`);
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(x, y, halo, 0, 6.283);
        ctx.fill();
        ctx.fillStyle = `hsla(${l.hue},100%,92%,${alpha.toFixed(3)})`;
        ctx.beginPath();
        ctx.arc(x, y, 1.3 * S, 0, 6.283);
        ctx.fill();
        if (alpha > 0.3) hits.push({ x, y, key: `a:${l.agent}` });
      }
      return hits;
    };

    let frame = 0;
    let last = 0;
    const paint = (now: number) => {
      if (!(W > 40 && H > 40)) size();
      if (!(W > 40 && H > 40)) return;
      while (L.queue.length > 0 && (L.queue[0]?.at ?? Infinity) <= now) {
        const next = L.queue.shift();
        if (next) play(next.step, now);
      }
      for (const l of L.lights.values()) {
        // Each stop is a paper, or null for the island; a paper not on the globe is skipped.
        while (l.route.length > 0 && l.route[0] !== null && !L.marks.has(l.route[0] ?? "")) l.route.shift();
        const stop = l.route[0];
        const at = stop === undefined ? null : stop === null ? home(l.island) : (L.marks.get(stop)?.at ?? null);
        // More stops queued, a quicker flight, so a burst of tool calls is still followed.
        const flown = flyLight(l.pos, at ? [at] : [], still ? 1 : Math.min(0.3, 0.09 + 0.03 * l.route.length));
        l.pos = flown.pos;
        if (flown.reached) {
          if (stop) reach(l, stop, now);
          l.route.shift();
        }
        // Without motion there is no trail: the light only stands where it is.
        l.trail = still ? [] : [...l.trail, l.pos].slice(-TRAIL);
      }
      const { proj, S } = draw(ctx, scene, W, H, angle, L.selected);
      const hits = overlay(proj, S, now);
      const surface = scene.nodes.flatMap((n, k) => {
        if (n.kind !== "island") return [];
        const p = proj(n);
        return islandSeen(p.z) > 0.2 ? [{ x: p.x, y: p.y, key: `i:${k}` }] : [];
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
      if (t - last > 33) {
        if (!still) angle += 0.0025;
        last = t;
        paint(t);
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", onResize);
    };
    // play and home read the latest islands through islandIndex.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scene, islandIndex]);

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
      setPicked({ kind: "agent", agent: id, island: islands[light?.island ?? 0]?.id ?? "", paper: light?.target ? paperOf(light.target) : null, last: light?.last ?? null });
    } else if (key.startsWith("p:")) {
      const who = new Set([...(readers[id] ?? []), ...(L.readers.get(id) ?? [])]);
      const aboard = [...L.lights.values()].filter((l) => l.target === id && lightAlpha(performance.now() - l.active) > 0).map((l) => l.agent);
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
            ? "Held for good: an agent has touched it."
            : p.held === false
              ? `Waiting: let go in ${p.daysLeft ?? "?"} days unless an agent reads it.`
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
