import { useEffect, useRef, useState } from "react";
import type { RunEvent } from "../api/types.ts";
import { BadgeTag, badge } from "../common.tsx";
import { usd } from "../money.ts";

/** How long each step stays on screen while playing. */
const STEP_MS = 1600;

/** The cost of the first `step` events. */
export function costThrough(events: readonly RunEvent[], step: number): number {
  return events.slice(0, step).reduce((sum, e) => sum + e.cost_micros, 0);
}

/**
 * A run replayed from its stored events, one at a time. `step` is how many events have played;
 * the event at `step` is the current one and the list below shows only what has played so far.
 * Nothing is made up: a run with no stored events has nothing to play.
 */
export function Replay({
  events,
  step,
  onStep,
  opening,
}: {
  events: readonly RunEvent[];
  step: number;
  onStep: (step: number) => void;
  /** What the agent was given before its first step. */
  opening: string | null;
}) {
  const [playing, setPlaying] = useState(false);
  const total = events.length;
  const current = step > 0 ? events[step - 1] : undefined;
  const here = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!playing) return;
    if (step >= total) {
      setPlaying(false);
      return;
    }
    const timer = setTimeout(() => onStep(step + 1), STEP_MS);
    return () => clearTimeout(timer);
  }, [playing, step, total, onStep]);

  useEffect(() => {
    here.current?.scrollIntoView?.({ block: "nearest" });
  }, [step]);

  const go = (to: number) => {
    setPlaying(false);
    onStep(Math.max(0, Math.min(total, to)));
  };

  return (
    <>
      <div className="bar">
        <button
          className="play"
          type="button"
          disabled={total === 0}
          onClick={() => {
            if (!playing && step >= total) onStep(0);
            setPlaying(!playing);
          }}
        >
          {playing ? "pause" : "play"}
        </button>
        <button className="quiet ctl" type="button" disabled={total === 0 || step === 0} onClick={() => go(0)}>
          restart
        </button>
        <button className="quiet ctl" type="button" aria-label="previous step" disabled={step === 0} onClick={() => go(step - 1)}>
          ‹
        </button>
        <button className="quiet ctl" type="button" aria-label="next step" disabled={step >= total} onClick={() => go(step + 1)}>
          ›
        </button>
        <input
          type="range"
          min="0"
          max={total}
          step="1"
          value={step}
          aria-label="step"
          disabled={total === 0}
          onChange={(e) => go(Number(e.target.value))}
        />
        <span className="readout">{total === 0 ? "" : `step ${step} of ${total}`}</span>
      </div>
      <div className="rp-side now" aria-live="polite">
        {total === 0 ? (
          <div className="meta">No step is stored for this run, so there is nothing to replay.</div>
        ) : current === undefined ? (
          <>
            <div className="meta">Before the first step. Press play to follow the agent through the paper.</div>
            {opening !== null && (
              <div className="ask">
                <span className="meta">the agent was told</span>
                {opening}
              </div>
            )}
          </>
        ) : (
          <>
            <div className="rp-cap">
              <BadgeTag event={current} />
              <span className="open">
                this step {usd(current.cost_micros)} · so far {usd(costThrough(events, step))}
              </span>
            </div>
            {current.input ? (
              <div className="ask">
                <span className="meta">the agent asked</span>
                {current.input}
              </div>
            ) : null}
            <div className="said">{current.body}</div>
            {current.output ? (
              <details>
                <summary>what came back</summary>
                <div className="said">{current.output}</div>
              </details>
            ) : null}
          </>
        )}
      </div>
      {step > 0 && (
        <div className="rlog" role="group" aria-label="steps played so far">
          {events.slice(0, step).map((e, i) => (
            <button
              key={e.id}
              type="button"
              className={i === step - 1 ? "ev-row on" : "ev-row"}
              aria-current={i === step - 1 ? "step" : undefined}
              ref={i === step - 1 ? here : null}
              onClick={() => go(i + 1)}
            >
              <span className="n">{i + 1}</span>
              <span className="k">{badge(e).label}</span>
              <span className="t">{e.input || e.body}</span>
              <span className="c">{usd(e.cost_micros)}</span>
            </button>
          ))}
        </div>
      )}
    </>
  );
}
