import { useEffect, useRef, useState } from "react";

/** A paper: its island's index and its position in that island's region, each 0 to 1. */
export type ScenePaper = { island: number; x: number; y: number };

/** An agent's nest: its island's index, the label under its square and its identity hue. */
export type SceneGenome = { island: number; label: string; hue: number };

/** What a run's recorded events have settled up to the replay's cursor. */
export type SceneState = {
  /** Per paper, each submitted chance with the genome that sealed it. */
  arrows: ReadonlyMap<number, readonly (readonly [genome: number, p: number])[]>;
  /** Per paper, how many deep reads have touched it. */
  ticks: ReadonlyMap<number, number>;
  /** Runs in flight: the reading genome and the paper it is on, if any. */
  inflight: readonly { genome: number; target: number | null }[];
  selected: number | null;
};

export type Scene = {
  islands: readonly string[];
  papers: readonly ScenePaper[];
  genomes: readonly SceneGenome[];
  state: SceneState;
};

export const EMPTY_STATE: SceneState = { arrows: new Map(), ticks: new Map(), inflight: [], selected: null };

type Region = { x: number; y: number; w: number; h: number };

const FONT = "Monaco, Geneva, ui-monospace, Menlo, monospace";
const INK3 = "#6b6559";

/** The canvas height and island regions for a width, as design-mock/island.html lays them out. */
export function layout(width: number, islands: number): { height: number; regions: Region[] } {
  const stack = width < 640;
  const k = Math.max(islands, 1);
  const height = stack ? k * Math.round(width * 0.7) : Math.round(width * (k === 1 ? 0.6 : 0.5));
  const regions = Array.from({ length: islands }, (_, i) =>
    stack ? { x: 0, y: (i * height) / k, w: width, h: height / k } : { x: (i * width) / k, y: 0, w: width / k, h: height },
  );
  return { height, regions };
}

/** Draws the scene: island labels and dividers, papers, the selected paper's arrows, nests, runs in flight. */
export function drawScene(ctx: CanvasRenderingContext2D, scene: Scene, width: number): void {
  const { height, regions } = layout(width, scene.islands.length);
  const { arrows, ticks, inflight, selected } = scene.state;
  const hue = (g: number) => `hsl(${scene.genomes[g]?.hue ?? 0},80%,45%)`;
  // A paper or genome whose island is not in the scene has no place and is not drawn.
  const ppos = (pi: number): [number, number] | null => {
    const p = scene.papers[pi];
    const r = p && regions[p.island];
    return p && r ? [r.x + 8 + p.x * (r.w - 16), r.y + 24 + p.y * (r.h - 70)] : null;
  };
  const nest = (gi: number): [number, number] | null => {
    const g = scene.genomes[gi];
    const r = g && regions[g.island];
    if (!g || !r) return null;
    const k = scene.genomes.filter((x) => x.island === g.island).indexOf(g);
    return [r.x + (r.w * (k + 1)) / 5, r.y + r.h - 22];
  };

  ctx.clearRect(0, 0, width, height);
  ctx.font = `bold 12px ${FONT}`;
  ctx.textBaseline = "top";
  regions.forEach((r, i) => {
    if (i > 0) {
      ctx.strokeStyle = "#ebe6d9";
      ctx.lineWidth = 1;
      ctx.beginPath();
      if (r.x > 0) {
        ctx.moveTo(r.x + 0.5, r.y);
        ctx.lineTo(r.x + 0.5, r.y + r.h);
      } else {
        ctx.moveTo(r.x, r.y + 0.5);
        ctx.lineTo(r.x + r.w, r.y + 0.5);
      }
      ctx.stroke();
    }
    ctx.fillStyle = INK3;
    ctx.fillText(scene.islands[i] ?? "", r.x + 10, r.y + 8);
  });
  // Grey until a run has submitted; then the dot darkens and grows with the mean chance.
  scene.papers.forEach((_, pi) => {
    const at = ppos(pi);
    if (!at) return;
    const [x, y] = at;
    const arr = arrows.get(pi);
    if (!arr || arr.length === 0) {
      ctx.fillStyle = ticks.get(pi) ? "#777" : "#c8c8c8";
      ctx.beginPath();
      ctx.arc(x, y, 2, 0, 6.283);
      ctx.fill();
      return;
    }
    let sx = 0;
    let sy = 0;
    let mp = 0;
    for (const [, p] of arr) {
      const th = Math.PI * (1 - p);
      sx += Math.cos(th);
      sy += -Math.sin(th);
      mp += p;
    }
    mp /= arr.length;
    const agree = Math.hypot(sx, sy) / arr.length;
    const ang = Math.atan2(sy, sx);
    const shade = Math.round(200 - 190 * mp);
    ctx.fillStyle = `rgb(${shade},${shade},${shade})`;
    ctx.beginPath();
    ctx.arc(x, y, 2 + 4 * mp, 0, 6.283);
    ctx.fill();
    const len = 5 + 13 * agree;
    ctx.strokeStyle = `rgba(0,0,0,${(0.3 + 0.7 * agree).toFixed(2)})`;
    ctx.lineWidth = 1 + 1.5 * agree;
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x + len * Math.cos(ang), y + len * Math.sin(ang));
    ctx.stroke();
  });
  // The selected paper shows each genome's own arrow in its hue.
  const chosen = selected === null ? null : ppos(selected);
  const own = selected === null ? undefined : arrows.get(selected);
  if (chosen && own) {
    const [x, y] = chosen;
    for (const [g, p] of own) {
      const th = Math.PI * (1 - p);
      ctx.strokeStyle = hue(g);
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x, y);
      ctx.lineTo(x + 16 * Math.cos(th), y - 16 * Math.sin(th));
      ctx.stroke();
    }
  }
  scene.genomes.forEach((g, gi) => {
    const at = nest(gi);
    if (!at) return;
    const [x, y] = at;
    ctx.fillStyle = hue(gi);
    ctx.beginPath();
    if (typeof ctx.roundRect === "function") {
      ctx.roundRect(x - 5, y - 5, 10, 10, 2);
      ctx.fill();
    } else {
      ctx.fillRect(x - 5, y - 5, 10, 10);
    }
    ctx.fillStyle = INK3;
    ctx.textAlign = "center";
    ctx.font = `11px ${FONT}`;
    ctx.fillText(g.label, x, y + 7);
    ctx.font = `bold 12px ${FONT}`;
    ctx.textAlign = "left";
  });
  for (const run of inflight) {
    const from = nest(run.genome);
    const to = run.target === null ? null : ppos(run.target);
    if (!from || !to) continue;
    const [nx, ny] = from;
    const [px, py] = to;
    ctx.strokeStyle = hue(run.genome);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(nx, ny - 5);
    ctx.lineTo(px, py);
    ctx.stroke();
  }
  if (chosen) {
    const [x, y] = chosen;
    ctx.strokeStyle = "#111";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(x, y, 7, 0, 6.283);
    ctx.stroke();
  }
}

/**
 * The mock's population canvas (design-mock/island.html, the same drawing swarm.html spans across
 * every island): papers as dots, agents as squares in their island's region, runs in flight as
 * lines, sealed chances as arrows. With no papers or agents it draws the regions and their labels.
 * `width` is measured from the element when not given; a missing 2d context leaves the frame blank.
 */
export function IslandCanvas({ scene, width, label }: { scene: Scene; width?: number | undefined; label: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const [measured, setMeasured] = useState(0);
  const w = width ?? measured;

  useEffect(() => {
    if (width !== undefined) return;
    const measure = () => setMeasured(ref.current?.clientWidth ?? 0);
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [width]);

  useEffect(() => {
    const cv = ref.current;
    const ctx = cv?.getContext("2d");
    if (!cv || !ctx || w <= 0) return;
    const dpr = window.devicePixelRatio || 1;
    const { height } = layout(w, scene.islands.length);
    cv.width = w * dpr;
    cv.height = height * dpr;
    cv.style.height = `${height}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    drawScene(ctx, scene, w);
  }, [scene, w]);

  return <canvas ref={ref} aria-label={label} style={{ width: "100%", display: "block", border: 0 }} />;
}
