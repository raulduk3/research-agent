import { type MouseEvent, useEffect, useMemo, useRef, useState } from "react";
import type { ActivityPaper, ActivityStep, Island } from "../api/types.ts";

/** A point of the globe: an island on the surface or a paper inside. `island` is -1 for a paper no island is known for. */
export type GlobeNode = { x: number; y: number; z: number; kind: "island" | "paper"; island: number };

export type GlobeScene = { nodes: GlobeNode[]; edges: [island: number, paper: number][] };

/** The most papers and reads drawn; past it the globe shows scale, not each one. */
const MAX_PAPERS = 600;
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
const INK = "43,40,34";

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
function draw(ctx: CanvasRenderingContext2D, scene: GlobeScene, W: number, H: number, angle: number): { proj: Projector; S: number } {
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

  // The body: a soft shade and a rim.
  const body = ctx.createRadialGradient(cx - R * 0.35, cy - R * 0.4, R * 0.1, cx, cy, R);
  body.addColorStop(0, "rgba(255,255,255,0.55)");
  body.addColorStop(0.7, "rgba(255,255,255,0.10)");
  body.addColorStop(1, `rgba(${INK},0.06)`);
  ctx.fillStyle = body;
  ctx.beginPath();
  ctx.arc(cx, cy, R, 0, 6.283);
  ctx.fill();
  ctx.strokeStyle = `rgba(${INK},0.35)`;
  ctx.lineWidth = 1.2;
  ctx.stroke();

  // The graticule: latitude rings and meridians, front half only.
  ctx.strokeStyle = `rgba(${INK},0.12)`;
  const arc = (point: (i: number) => { x: number; y: number; z: number }) => {
    ctx.beginPath();
    let pen = false;
    for (let i = 0; i <= 90; i++) {
      const p = proj(point(i));
      if (p.z < 0) {
        pen = false;
        continue;
      }
      if (pen) ctx.lineTo(p.x, p.y);
      else ctx.moveTo(p.x, p.y);
      pen = true;
    }
    ctx.stroke();
  };
  for (let lat = -60; lat <= 60; lat += 30) {
    const la = (lat * Math.PI) / 180;
    arc((i) => ({ x: Math.cos(la) * Math.cos((i / 90) * 6.283), y: Math.sin(la), z: Math.cos(la) * Math.sin((i / 90) * 6.283) }));
  }
  for (const lon of MERIDIANS) {
    const lo = (lon * Math.PI) / 180;
    arc((i) => {
      const la = -Math.PI / 2 + (i / 90) * Math.PI;
      return { x: Math.cos(la) * Math.cos(lo), y: Math.sin(la), z: Math.cos(la) * Math.sin(lo) };
    });
  }

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
      ctx.fillStyle = n.island >= 0 ? `hsla(${islandHue(n.island)},45%,32%,${(0.25 + 0.55 * depth).toFixed(2)})` : `rgba(${INK},${(0.2 + 0.6 * depth).toFixed(2)})`;
      ctx.beginPath();
      ctx.arc(p.x, p.y, (1.1 + 1.2 * depth) * S, 0, 6.283);
      ctx.fill();
      continue;
    }
    // An island sits on the surface: on the far side the globe is in front of it.
    const seen = facing(p.z);
    if (seen <= 0) continue;
    const hue = islandHue(n.island);
    const rr = 5.5 * (0.7 + 0.5 * depth) * S;
    ctx.globalAlpha = seen;
    ctx.fillStyle = `hsla(${hue},90%,50%,${(0.14 + 0.16 * depth).toFixed(2)})`;
    ctx.beginPath();
    ctx.arc(p.x, p.y, rr * 2.6, 0, 6.283);
    ctx.fill();
    ctx.fillStyle = `hsla(${hue},90%,42%,${(0.55 + 0.45 * depth).toFixed(2)})`;
    ctx.beginPath();
    ctx.arc(p.x, p.y, rr, 0, 6.283);
    ctx.fill();
    ctx.fillStyle = `rgba(255,255,255,${(0.5 * depth).toFixed(2)})`;
    ctx.beginPath();
    ctx.arc(p.x - rr * 0.3, p.y - rr * 0.3, rr * 0.35, 0, 6.283);
    ctx.fill();
    ctx.globalAlpha = 1;
  }
  return { proj, S };
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
};

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

type Boat = { agent: string; island: number; hue: number; pos: Vec; target: string | null; last: ActivityStep | null };
type Mark = { paper: GlobePaper; at: Vec; hue: number | null; born: number };
type Flash = { agent: string; to: string; hue: number; born: number };

export type Picked =
  | { kind: "paper"; paper: GlobePaper; readers: string[]; aboard: string[] }
  | { kind: "agent"; agent: string; island: string; paper: GlobePaper | null; last: ActivityStep | null }
  | { kind: "island"; island: Island };

const BOLT_MS = 900;
const PULSE_MS = 7000;
const RING_MS = 1400;

/**
 * The cover: a slowly turning globe of the storm, islands on the surface in their colors and the
 * papers inside. Each agent is a small boat that sails from its island to the paper it is reading;
 * every step it takes strikes the papers it looks at with a bolt in its color, and a paper it finds
 * that the globe did not show yet appears and pulses. A click names the paper, boat or island under
 * the pointer. It stands still for a visitor who asks for reduced motion.
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
  });

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
    marks.set(paper.id, { paper, at: paperPoint(paper.id, island, islands.length), hue, born });
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
      boat = { agent: step.agent, island, hue, pos: home(island), target: null, last: null };
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

    const overlay = (proj: Projector, S: number, now: number) => {
      const hits: { x: number; y: number; key: string }[] = [];
      for (const [id, mark] of L.marks) {
        const p = proj(mark.at);
        const depth = (p.z + 1) / 2;
        const age = now - mark.born;
        const pulsing = mark.born > 0 && age < PULSE_MS;
        const hue = mark.hue ?? islandHue(islandIndex.get(mark.paper.islands[0] ?? "") ?? 0);
        const r = (1.6 + 1.6 * depth) * S;
        if (pulsing) {
          const beat = (Math.sin(age / 160) + 1) / 2;
          ctx.fillStyle = `hsla(${hue},95%,55%,${(0.25 * (1 - age / PULSE_MS) + 0.1 * beat).toFixed(3)})`;
          ctx.beginPath();
          ctx.arc(p.x, p.y, r * (2.4 + 1.6 * beat), 0, 6.283);
          ctx.fill();
        }
        ctx.fillStyle = mark.paper.held === false ? `hsla(${hue},30%,45%,${(0.3 + 0.4 * depth).toFixed(2)})` : `hsla(${hue},70%,${pulsing ? 50 : 34}%,${(0.45 + 0.5 * depth).toFixed(2)})`;
        ctx.beginPath();
        ctx.arc(p.x, p.y, r, 0, 6.283);
        ctx.fill();
        if (mark.paper.held === true) {
          // A held paper wears a ring: the swarm keeps it.
          ctx.strokeStyle = `hsla(${hue},70%,30%,${(0.3 + 0.4 * depth).toFixed(2)})`;
          ctx.lineWidth = 0.8;
          ctx.beginPath();
          ctx.arc(p.x, p.y, r + 1.8 * S, 0, 6.283);
          ctx.stroke();
        }
        hits.push({ x: p.x, y: p.y, key: `p:${id}` });
      }
      // Bolts: a short jagged strike from the boat to each paper it looks at.
      L.flashes = L.flashes.filter((f) => now - f.born < BOLT_MS);
      for (const f of L.flashes) {
        const boat = L.boats.get(f.agent);
        const mark = L.marks.get(f.to);
        if (!boat || !mark) continue;
        const A = proj(boat.pos);
        const B = proj(mark.at);
        const fade = 1 - (now - f.born) / BOLT_MS;
        const len = Math.hypot(B.x - A.x, B.y - A.y) || 1;
        const nx = -(B.y - A.y) / len;
        const ny = (B.x - A.x) / len;
        const path = () => {
          ctx.beginPath();
          ctx.moveTo(A.x, A.y);
          for (let k = 1; k < 6; k++) {
            const t = k / 6;
            const j = (Math.random() - 0.5) * Math.min(14, len * 0.18) * S;
            ctx.lineTo(A.x + (B.x - A.x) * t + nx * j, A.y + (B.y - A.y) * t + ny * j);
          }
          ctx.lineTo(B.x, B.y);
        };
        ctx.strokeStyle = `hsla(${f.hue},100%,60%,${(0.25 * fade).toFixed(3)})`;
        ctx.lineWidth = 4 * S;
        path();
        ctx.stroke();
        ctx.strokeStyle = `hsla(${f.hue},100%,${45 + 30 * fade}%,${(0.9 * fade).toFixed(3)})`;
        ctx.lineWidth = 1.3 * S;
        path();
        ctx.stroke();
      }
      L.rings = L.rings.filter((f) => now - f.born < RING_MS);
      for (const f of L.rings) {
        const mark = L.marks.get(f.to);
        if (!mark) continue;
        const p = proj(mark.at);
        const t = (now - f.born) / RING_MS;
        ctx.strokeStyle = `hsla(${f.hue},90%,45%,${(1 - t).toFixed(3)})`;
        ctx.lineWidth = 2 * S;
        ctx.beginPath();
        ctx.arc(p.x, p.y, (4 + 26 * t) * S, 0, 6.283);
        ctx.stroke();
      }
      // Boats last, nearest on top: a hull and a sail in the agent's color.
      const boats = [...L.boats.values()].map((b) => ({ b, p: proj(b.pos) })).sort((u, v) => u.p.z - v.p.z);
      for (const { b, p } of boats) {
        const atHome = b.target === null;
        const seen = atHome ? Math.max(0.25, facing(p.z)) : 1;
        const s = (0.8 + 0.35 * ((p.z + 1) / 2)) * S;
        const bob = still ? 0 : Math.sin(now / 320 + hash01(b.agent) * 6) * 1.2;
        const x = p.x;
        const y = p.y + bob - 2 * s;
        ctx.globalAlpha = seen;
        ctx.fillStyle = `hsl(${b.hue},70%,28%)`;
        ctx.beginPath();
        ctx.moveTo(x - 7 * s, y);
        ctx.lineTo(x + 7 * s, y);
        ctx.lineTo(x + 4.5 * s, y + 3.5 * s);
        ctx.lineTo(x - 4.5 * s, y + 3.5 * s);
        ctx.closePath();
        ctx.fill();
        ctx.strokeStyle = `hsl(${b.hue},40%,20%)`;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x, y);
        ctx.lineTo(x, y - 11 * s);
        ctx.stroke();
        ctx.fillStyle = `hsl(${b.hue},95%,${atHome ? 70 : 58}%)`;
        ctx.beginPath();
        ctx.moveTo(x + 0.8 * s, y - 11 * s);
        ctx.lineTo(x + 0.8 * s, y - 1.5 * s);
        ctx.lineTo(x + 7 * s, y - 1.5 * s);
        ctx.closePath();
        ctx.fill();
        ctx.globalAlpha = 1;
        hits.push({ x, y: y - 3 * s, key: `a:${b.agent}` });
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
        b.pos = { x: b.pos.x + (goal.x - b.pos.x) * k, y: b.pos.y + (goal.y - b.pos.y) * k, z: b.pos.z + (goal.z - b.pos.z) * k };
      }
      const { proj, S } = draw(ctx, scene, W, H, angle);
      const hits = overlay(proj, S, now);
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
