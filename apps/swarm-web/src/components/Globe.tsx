import { useEffect, useMemo, useRef } from "react";
import type { Island } from "../api/types.ts";

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

function draw(ctx: CanvasRenderingContext2D, scene: GlobeScene, W: number, H: number, angle: number): void {
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
}

/**
 * The cover: a slowly turning globe of the storm, islands on the surface in their colors and the
 * papers inside. It carries no text and is not a link; it stands still for a visitor who asks for
 * reduced motion.
 */
export function Globe({ islands, papers }: { islands: readonly Island[]; papers: number }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const scene = useMemo(() => globeScene(islands, papers), [islands, papers]);

  useEffect(() => {
    const cv = canvas.current;
    const ctx = cv?.getContext("2d") ?? null;
    if (!cv || !ctx) return;
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
    let angle = 0;
    const paint = () => {
      if (!(W > 40 && H > 40)) size();
      if (W > 40 && H > 40) draw(ctx, scene, W, H, angle);
    };
    const onResize = () => {
      size();
      paint();
    };
    size();
    paint();
    window.addEventListener("resize", onResize);
    const still = typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let frame = 0;
    let last = 0;
    const tick = (t: number) => {
      if (t - last > 33) {
        angle += 0.0035;
        last = t;
        paint();
      }
      frame = requestAnimationFrame(tick);
    };
    if (!still) frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", onResize);
    };
  }, [scene]);

  return (
    <div className="hero">
      <canvas ref={canvas} role="img" aria-label="the storm as a turning globe: islands on the surface, papers inside" />
    </div>
  );
}
