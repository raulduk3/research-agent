import { useEffect, useMemo, useState } from "react";
import { EMPTY_STATE, IslandCanvas, type Scene, type SceneState } from "../IslandCanvas.tsx";
import { useRunStream } from "./useRunStream.ts";

/** One step of the replay: a recorded event of the run, or one that arrived on the live stream. */
export type Step = { kind: string; at: string | null };

/** A sealed claim as the replay needs it: when it was sealed and its chance, if any. */
export type Sealed = { sealed_at: string; confidence: number | null };

/** The run's agent and paper as the scene draws them; the one paper sits in its island's middle. */
export type SwarmRun = { agent: string; island: string | null };

/**
 * What the run has settled once the first `cursor` steps have played: every step is a read of the
 * run's paper, the run is in flight until its last step (or its ending on the stream), and each
 * claim sealed by the time of the cursor's step points its chance from the paper.
 */
export function sceneAt(steps: readonly Step[], sealed: readonly Sealed[], cursor: number, ended: boolean): SceneState {
  if (cursor <= 0) return EMPTY_STATE;
  const n = Math.min(cursor, steps.length);
  const until = n === steps.length ? null : steps[n - 1]?.at;
  const arrows = sealed
    .filter((s) => s.confidence !== null && (until == null || s.sealed_at <= until))
    .map((s) => [0, s.confidence as number] as const);
  const done = n === steps.length && ended;
  return {
    arrows: new Map(arrows.length > 0 ? [[0, arrows]] : []),
    ticks: new Map([[0, n]]),
    inflight: done ? [] : [{ genome: 0, target: 0 }],
    selected: arrows.length > 0 ? 0 : null,
  };
}

/**
 * The mock's swarm replay (design-mock/swarm.html) over one run: the canvas, the play button, the
 * scrubber and the speed, driven by the run's recorded events and followed live while the stream
 * (#327) is open. Before any step it draws the run's island, paper and nest; with no run, the frame.
 */
export function Swarm({
  run,
  recorded,
  sealed,
  runId,
  width,
}: {
  run: SwarmRun | null;
  recorded: readonly Step[];
  sealed: readonly Sealed[];
  runId: string | null;
  width?: number;
}) {
  const live = useRunStream(runId);
  const steps = useMemo<Step[]>(
    () => [...recorded, ...live.events.map((e) => ({ kind: e.kind, at: null }))],
    [recorded, live.events],
  );
  const ended = !live.open || live.events.some((e) => e.kind === "ending");
  const [cursor, setCursor] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(600);
  // Once the stream opens the replay follows its head until the owner scrubs or plays.
  const [following, setFollowing] = useState(false);
  useEffect(() => {
    if (live.open) setFollowing(true);
  }, [live.open]);
  const at = following ? steps.length : Math.min(cursor, steps.length);

  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => {
      setCursor((c) => {
        if (c + 1 >= steps.length) setPlaying(false);
        return Math.min(c + 1, steps.length);
      });
    }, 360000 / speed);
    return () => clearInterval(timer);
  }, [playing, speed, steps.length]);

  const island = run?.island ?? live.events.find((e) => e.island)?.island ?? null;
  const scene = useMemo<Scene>(
    () =>
      run === null
        ? { islands: [], papers: [], genomes: [], state: EMPTY_STATE }
        : {
            islands: [island ?? "island not read"],
            papers: [{ island: 0, x: 0.5, y: 0.5 }],
            genomes: [{ island: 0, label: run.agent.slice(0, 8), hue: 24 }],
            state: sceneAt(steps, sealed, at, ended),
          },
    [run, island, steps, sealed, at, ended],
  );
  const step = at > 0 ? steps[at - 1] : undefined;

  return (
    <div className="rplay">
      <div className="bar">
        <button
          className="play"
          type="button"
          aria-label={playing ? "pause" : "play"}
          disabled={steps.length === 0}
          onClick={() => {
            if (!playing && at >= steps.length) setCursor(0);
            else setCursor(at);
            setFollowing(false);
            setPlaying(!playing);
          }}
        >
          {playing ? "pause" : "play"}
        </button>
        <input
          className="cur"
          type="range"
          min="0"
          max={steps.length}
          value={at}
          step="1"
          aria-label="timeline"
          disabled={steps.length === 0}
          onChange={(e) => {
            setFollowing(false);
            setPlaying(false);
            setCursor(Number(e.target.value));
          }}
        />
        <span className="readout">
          {steps.length === 0 ? "" : `step ${at} of ${steps.length}${step ? ` · ${step.kind}` : ""}`}
        </span>
        <select
          className="speed"
          aria-label="speed"
          value={String(speed)}
          disabled={steps.length === 0}
          onChange={(e) => setSpeed(Number(e.target.value))}
        >
          <option value="60">×60</option>
          <option value="600">×600</option>
          <option value="3600">×3600</option>
        </select>
      </div>
      <div className="cue">
        {steps.length === 0 ? "No step recorded to replay." : live.open ? "following the run live" : "replay from the record"}
      </div>
      <div className="stage">
        <IslandCanvas scene={scene} width={width} label="the run replayed on its island" />
      </div>
    </div>
  );
}
