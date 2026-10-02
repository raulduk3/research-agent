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

type Vec = { x: number; y: number; z: number };
type Projector = (p: Vec) => Vec;

/** Paints the globe and returns how it projected, so the marks drawn over it line up. */
function draw(ctx: CanvasRenderingContext2D, scene: GlobeScene, W: number, H: number, angle: number, selected = -1): { proj: Projector; S: number; R: number } {
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
    // An island sits on a radial point of the shell; the dot is the island. When it is the one
    // selected, two of the sphere's own lines are drawn through it, its parallel and its
    // meridian, all the way round, each pressed harder near the point so the crossing stands
    // out. On the far side it is a mark on the inner wall, seen through the open front.
    const hue = islandHue(n.island);
    const back = p.z < 0;
    const seen = back ? Math.max(0, Math.min(1, -p.z / 0.14)) * 0.6 : facing(p.z);
    if (seen <= 0) continue;
    const rr = 5.5 * (0.7 + 0.5 * depth) * S;
    ctx.globalAlpha = seen;
    for (const line of n.island === selected ? islandLines(n) : []) {
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
const dot = (a: Vec, b: Vec): number => a.x * b.x + a.y * b.y + a.z * b.z;
const cross = (a: Vec, b: Vec): Vec => ({ x: a.y * b.z - a.z * b.y, y: a.z * b.x - a.x * b.z, z: a.x * b.y - a.y * b.x });
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

type Local = [forward: number, up: number, side: number];
// Deck corners from the bow round, then the keel's fore and aft points.
const BOW: Local = [1, 0, 0];
const FORE_S: Local = [0.35, 0, 0.34];
const AFT_S: Local = [-0.85, 0, 0.3];
const AFT_P: Local = [-0.85, 0, -0.3];
const FORE_P: Local = [0.35, 0, -0.34];
const KEEL_F: Local = [0.7, -0.34, 0];
const KEEL_A: Local = [-0.75, -0.3, 0];
/** The boat: a hull of five faces, a deck, a mainsail and a jib, in its own frame. */
const BOAT: { part: "hull" | "deck" | "sail"; at: Local[] }[] = [
  { part: "hull", at: [BOW, FORE_S, KEEL_F] },
  { part: "hull", at: [FORE_S, AFT_S, KEEL_A, KEEL_F] },
  { part: "hull", at: [BOW, KEEL_F, FORE_P] },
  { part: "hull", at: [FORE_P, KEEL_F, KEEL_A, AFT_P] },
  { part: "hull", at: [AFT_S, AFT_P, KEEL_A] },
  { part: "deck", at: [BOW, FORE_S, AFT_S, AFT_P, FORE_P] },
  { part: "sail", at: [[0.1, 0.06, 0], [0.1, 1.45, 0], [-0.78, 0.1, 0]] },
  { part: "sail", at: [[0.18, 1.3, 0], [0.95, 0.05, 0], [0.18, 0.08, 0]] },
];

/**
 * The boat's faces in globe space: at `pos`, standing on `up`, bow toward `heading`, `size` long.
 * Each face keeps its part so it can be colored.
 */
export function boatFaces(pos: Vec, up: Vec, heading: Vec, size: number): { part: "hull" | "deck" | "sail"; at: Vec[] }[] {
  const u = unit(up);
  let f = add(heading, mul(u, -dot(heading, u)));
  if (Math.hypot(f.x, f.y, f.z) < 1e-6) f = cross(u, { x: 0, y: 0, z: 1 });
  f = unit(f);
  const side = cross(u, f);
  const place = ([a, b, c]: Local) => add(pos, add(mul(f, a * size), add(mul(u, b * size), mul(side, c * size))));
  return BOAT.map((face) => ({ part: face.part, at: face.at.map(place) }));
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
 * What one stored step does on the globe. `sail` moves the agent's boat: to a paper, or home to
 * its island when null; undefined leaves it. `bolts` are the papers it strikes, `born` the papers
 * it found that the globe may not show yet, `ring` a reading handed in.
 */
export function stepEffect(step: ActivityStep): { sail?: string | null; bolts: string[]; born: string[]; ring?: string } {
  switch (step.kind) {
    case "run_started":
      return { sail: step.paper_id, bolts: [], born: [step.paper_id] };
    case "run_completed":
    case "run_failed":
      return { sail: null, bolts: [], born: [] };
    case "reading_submitted":
      return { sail: step.paper_id, bolts: [step.paper_id], born: [], ring: step.paper_id };
    case "tool_call":
      return { sail: step.paper_id, bolts: [step.paper_id, ...step.looked_at], born: step.looked_at };
    default:
      return { sail: step.paper_id, bolts: [step.paper_id], born: [] };
  }
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
  if (step.kind === "run_started") return "set sail for a paper";
  if (step.kind === "run_completed") return "finished the run";
  if (step.kind === "run_failed") return "the run failed";
  return step.kind.replace(/_/g, " ");
}

type Boat = { agent: string; island: number; hue: number; pos: Vec; heading: Vec; target: string | null; last: ActivityStep | null };
/** `seen` holds every island whose agents looked at the paper, beside the islands it is assigned to. */
type Mark = { paper: GlobePaper; at: Vec; hue: number | null; born: number; touched: number; seen: Set<number>; shove: { x: number; y: number } };
type Flash = { agent: string; to: string; hue: number; born: number };

export type Picked =
  | { kind: "paper"; paper: GlobePaper; readers: string[]; aboard: string[] }
  | { kind: "agent"; agent: string; island: string; paper: GlobePaper | null; last: ActivityStep | null }
  | { kind: "island"; island: Island };

const READ_MS = 1100;
const PULSE_MS = 5000;
/** How long an island's holding line to a paper stays after an agent touched it. */
const HOLD_LINE_MS = 9000;
const RING_MS = 1400;

/**
 * The cover: a slowly turning glass globe of the storm, islands on the surface and papers inside,
 * sharp on the side facing the viewer and soft behind. A held paper is a solid dot tied by a line to
 * each island that has it or whose agents looked at it; a paper still waiting is a hollow ring. Each
 * agent is a small boat that sails from its island to the paper it reads, and each step draws a line
 * from the boat to the papers it looks at. A paper found that the globe did not show yet appears and
 * pulses. A click names the paper, boat or island under the pointer. It stands still for a visitor
 * who asks for reduced motion.
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
  // The island whose lines are drawn: the one clicked, read by the animation through a ref.
  const selectedRef = useRef(-1);
  selectedRef.current = picked?.kind === "island" ? islands.findIndex((i) => i.id === picked.island.id) : -1;
  const scene = useMemo(() => {
    const drawn = globeScene(islands, Math.max(0, papers - known.length));
    // With the brief's papers known, their own holding lines replace the lines drawn from counts.
    return known.length > 0 ? { ...drawn, edges: [] } : drawn;
  }, [islands, papers, known.length]);
  const islandIndex = useMemo(() => new Map(islands.map((island, i) => [island.id, i])), [islands]);

  // Everything the animation moves lives here, outside React, and survives new props.
  const live = useRef({
    marks: new Map<string, Mark>(),
    boats: new Map<string, Boat>(),
    flashes: [] as Flash[],
    rings: [] as Flash[],
    queue: [] as { step: ActivityStep; at: number }[],
    seen: new Set<number>(),
    readers: new Map<string, Set<string>>(),
    hits: [] as { x: number; y: number; key: string }[],
    // The pointer as wind: where it is, how fast it moves, and when it last moved.
    wind: { x: 0, y: 0, vx: 0, vy: 0, at: 0 },
  });
  const api = useApi();

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
  const place = (paper: GlobePaper, hue: number | null, born: number) => {
    const marks = live.current.marks;
    const had = marks.get(paper.id);
    if (had) {
      if (paper.held !== null || had.paper.held === null) had.paper = { ...had.paper, ...paper, held: paper.held ?? had.paper.held };
      return;
    }
    const island = islandIndex.get(paper.islands[0] ?? "") ?? -1;
    marks.set(paper.id, { paper, at: paperPoint(paper.id, island, islands.length), hue, born, touched: 0, seen: new Set(), shove: { x: 0, y: 0 } });
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
    let boat = L.boats.get(step.agent);
    if (!boat) {
      boat = { agent: step.agent, island, hue, pos: home(island), heading: { x: 1, y: 0, z: 0 }, target: null, last: null };
      L.boats.set(step.agent, boat);
    }
    boat.last = step;
    const effect = stepEffect(step);
    for (const id of effect.born) place(paperOf(id), hue, L.marks.has(id) ? 0 : now);
    if (effect.sail !== undefined) boat.target = effect.sail;
    for (const id of [step.paper_id, ...step.looked_at]) {
      const who = L.readers.get(id) ?? new Set<string>();
      who.add(step.agent);
      L.readers.set(id, who);
    }
    for (const id of effect.bolts) {
      if (!L.marks.has(id)) place(paperOf(id), hue, now);
      // The paper is now in this island's view too, whichever island brought it in.
      const mark = L.marks.get(id);
      if (mark) {
        mark.seen.add(island);
        mark.touched = now;
      }
      L.flashes.push({ agent: step.agent, to: id, hue, born: now });
    }
    if (effect.ring) L.rings.push({ agent: step.agent, to: effect.ring, hue, born: now });
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

    const overlay = (proj: Projector, S: number, R: number, now: number) => {
      const hits: { x: number; y: number; key: string }[] = [];
      const surface = islands.map((_, i) => {
        const [x, y, z] = direction(i, Math.max(islands.length, 1), 1.1);
        return proj({ x, y, z });
      });
      // Every paper sits where it is, moved by the weather and by any gust the pointer made.
      const gusting = now - L.wind.at < 160;
      const marks = [...L.marks.entries()].map(([id, mark]) => {
        const p = proj(mark.at);
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
      // Holding lines, only while a paper is in play: from each island whose agents touched it
      // in the last moments, fading out, so a full globe is a constellation and not a web.
      for (const { mark, p } of marks) {
        const age = now - mark.touched;
        if (mark.touched === 0 || age > HOLD_LINE_MS || mark.seen.size === 0) continue;
        const fade = 1 - age / HOLD_LINE_MS;
        for (const i of mark.seen) {
          const A = surface[i];
          if (!A) continue;
          const f = focus((A.z + p.z) / 2);
          ctx.strokeStyle = `hsla(${islandHue(i)},70%,40%,${(0.35 * fade * f.alpha * Math.max(0.2, facing(A.z))).toFixed(3)})`;
          ctx.lineWidth = 0.8 * S;
          ctx.beginPath();
          ctx.moveTo(A.x, A.y);
          ctx.lineTo(p.x, p.y);
          ctx.stroke();
        }
      }
      // A step: a plain line from the boat to each paper it looks at, fading out.
      L.flashes = L.flashes.filter((f) => now - f.born < READ_MS);
      for (const f of L.flashes) {
        const boat = L.boats.get(f.agent);
        const mark = L.marks.get(f.to);
        if (!boat || !mark) continue;
        const A = proj(boat.pos);
        const B = placed.get(f.to) ?? proj(mark.at);
        const fade = 1 - (now - f.born) / READ_MS;
        ctx.strokeStyle = `hsla(${f.hue},80%,42%,${(0.85 * fade).toFixed(3)})`;
        ctx.lineWidth = 1.3 * S;
        ctx.beginPath();
        ctx.moveTo(A.x, A.y);
        ctx.lineTo(B.x, B.y);
        ctx.stroke();
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
          softDot(ctx, p.x, p.y, r, f.blur * S, `hsla(${hue},70%,${pulsing ? 50 : light}%,`, f.alpha);
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
      // A boat under way sails along its line, home island to the paper, drawn while it goes.
      for (const b of L.boats.values()) {
        if (b.target === null) continue;
        const mark = L.marks.get(b.target);
        if (!mark) continue;
        const A = proj(home(b.island));
        const B = placed.get(b.target) ?? proj(mark.at);
        const f = focus((A.z + B.z) / 2);
        ctx.strokeStyle = `hsla(${b.hue},60%,40%,${(0.3 * f.alpha).toFixed(3)})`;
        ctx.lineWidth = 0.8 * S;
        ctx.setLineDash([2 * S, 3 * S]);
        ctx.beginPath();
        ctx.moveTo(A.x, A.y);
        ctx.lineTo(B.x, B.y);
        ctx.stroke();
        ctx.setLineDash([]);
      }
      // Boats last, nearest on top: a little 3D model in black and white, faces painted back
      // to front and shaded.
      const boats = [...L.boats.values()].map((b) => ({ b, p: proj(b.pos) })).sort((u, v) => u.p.z - v.p.z);
      for (const { b, p } of boats) {
        const seen = b.target === null ? Math.max(0.3, facing(p.z)) : 1;
        const bob = still ? 0 : Math.sin(now / 320 + hash01(b.agent) * 6) * 0.004;
        const radial = unit(b.pos);
        const up = unit(add({ x: 0, y: 0.8, z: 0 }, mul(radial, 0.35)));
        const at = add(b.pos, mul(up, 0.03 + bob));
        const faces = boatFaces(at, up, b.heading, (11 * S) / R).map((face) => {
          const q = face.at.map(proj);
          const [q0, q1, q2] = q as [Vec, Vec, Vec];
          const n = cross(
            { x: q1.x - q0.x, y: q0.y - q1.y, z: (q1.z - q0.z) * R },
            { x: q2.x - q0.x, y: q0.y - q2.y, z: (q2.z - q0.z) * R },
          );
          const light = Math.abs(n.z) / (Math.hypot(n.x, n.y, n.z) || 1);
          return { part: face.part, q, z: q.reduce((sum, v) => sum + v.z, 0) / q.length, light };
        });
        faces.sort((u, v) => u.z - v.z);
        ctx.globalAlpha = seen;
        for (const face of faces) {
          const l = face.light;
          ctx.fillStyle = face.part === "hull" ? `hsl(0,0%,${8 + 22 * l}%)` : face.part === "deck" ? `hsl(0,0%,${40 + 25 * l}%)` : `hsl(0,0%,${84 + 14 * l}%)`;
          ctx.beginPath();
          face.q.forEach((v, k) => (k === 0 ? ctx.moveTo(v.x, v.y) : ctx.lineTo(v.x, v.y)));
          ctx.closePath();
          ctx.fill();
          if (face.part === "sail") {
            ctx.strokeStyle = "rgba(0,0,0,0.7)";
            ctx.lineWidth = 0.6;
            ctx.stroke();
          }
        }
        ctx.globalAlpha = 1;
        hits.push({ x: p.x, y: p.y - 6 * S, key: `a:${b.agent}` });
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
      for (const b of L.boats.values()) {
        const goal = b.target !== null ? (L.marks.get(b.target)?.at ?? home(b.island)) : home(b.island);
        const k = still ? 1 : 0.045;
        const way = add(goal, mul(b.pos, -1));
        // The bow turns toward where the boat is going; at rest it swings slowly at anchor.
        const turn = Math.hypot(way.x, way.y, way.z) > 0.02 ? unit(way) : unit(add(b.heading, mul(cross({ x: 0, y: 1, z: 0 }, b.heading), still ? 0 : 0.01)));
        b.heading = unit(add(mul(b.heading, 0.9), mul(turn, 0.1)));
        b.pos = { x: b.pos.x + (goal.x - b.pos.x) * k, y: b.pos.y + (goal.y - b.pos.y) * k, z: b.pos.z + (goal.z - b.pos.z) * k };
      }
      const { proj, S, R } = draw(ctx, scene, W, H, angle, selectedRef.current);
      const hits = overlay(proj, S, R, now);
      const surface = scene.nodes.flatMap((n, k) => {
        if (n.kind !== "island") return [];
        const p = proj(n);
        return facing(p.z) > 0.3 ? [{ x: p.x, y: p.y, key: `i:${k}` }] : [];
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
    // Boats are small and move: they win a near tie, then papers, then islands.
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
      const boat = L.boats.get(id);
      setPicked({ kind: "agent", agent: id, island: islands[boat?.island ?? 0]?.id ?? "", paper: boat?.target ? paperOf(boat.target) : null, last: boat?.last ?? null });
    } else if (key.startsWith("p:")) {
      const who = new Set([...(readers[id] ?? []), ...(L.readers.get(id) ?? [])]);
      const aboard = [...L.boats.values()].filter((b) => b.target === id).map((b) => b.agent);
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
        aria-label="the storm as a turning globe: islands on the surface, papers inside, agents as boats sailing to the papers they read"
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
        <div>{picked.paper ? <>Sailing to {picked.paper.title} ({picked.paper.id}).</> : "At home on its island."}</div>
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
