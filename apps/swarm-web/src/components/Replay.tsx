import { useEffect, useRef, useState, type ReactNode } from "react";
import type { RunEvent } from "../api/types.ts";
import { BadgeTag, badge } from "../common.tsx";
import { usd } from "../money.ts";
import { MathText } from "./MathText.tsx";

/** How long each step stays on screen while playing. */
const STEP_MS = 1600;

type Json = null | boolean | number | string | Json[] | { [key: string]: Json };

function object(value: unknown): Record<string, Json> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, Json>) : null;
}

function array(value: Json | undefined): Json[] {
  return Array.isArray(value) ? value : [];
}

function string(value: Json | undefined): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

function parseObject(text: string | null | undefined): Record<string, Json> | null {
  if (!text) return null;
  try {
    return object(JSON.parse(text));
  } catch {
    return null;
  }
}

function short(value: string, limit = 420): string {
  return value.length > limit ? `${value.slice(0, limit).trim()}…` : value;
}

function ToolInput({ event }: { event: RunEvent }) {
  const args = object(object(event.payload)?.arguments) ?? parseObject(event.input);
  if (args === null) return event.input ? <MathText text={event.input} /> : null;
  const tool = event.tool;
  if (tool === "paper_text") {
    return <MathText text={string(args.passage_id) ? `read passage ${string(args.passage_id)}` : "read the stored paper text"} />;
  }
  if (tool === "related_papers") return <MathText text={`search related papers for “${string(args.query) ?? ""}”`} />;
  if (tool === "cited_paper_text") {
    const passage = string(args.passage_id);
    return <MathText text={`${passage ? `read passage ${passage} from` : "inspect"} cited paper “${string(args.reference) ?? ""}”`} />;
  }
  if (tool === "capture_note") return <MathText text={string(args.text) ?? "capture a note"} />;
  if (tool === "submit_reading") return <MathText text="submit the final reading" />;
  return event.input ? <MathText text={event.input} /> : null;
}

function ResultItems({ label, items, pick }: { label: string; items: Json[]; pick: (item: Record<string, Json>, index: number) => ReactNode }) {
  if (items.length === 0) return null;
  return (
    <>
      <div className="meta">{label}</div>
      <ul className="facts compact">
        {items.slice(0, 8).map((item, i) => {
          const row = object(item);
          return row === null ? null : <li key={i}>{pick(row, i)}</li>;
        })}
      </ul>
      {items.length > 8 && <div className="meta">and {items.length - 8} more</div>}
    </>
  );
}

function ToolResult({ event }: { event: RunEvent }) {
  const payload = object(event.payload);
  const result = object(payload?.result) ?? parseObject(event.output);
  if (result === null) return event.output ? <MathText text={event.output} /> : null;
  if (string(result.error)) return <div className="result-card refused">{string(result.error)?.replace(/_/g, " ")}</div>;
  if (event.tool === "paper_text") {
    const passages = array(result.passages);
    return (
      <div className="result-card">
        <ResultItems
          label="passages returned"
          items={passages}
          pick={(row) => (
            <>
              <b>{string(row.title) ?? string(row.passage_id) ?? "passage"}</b>
              {string(row.text) && <p><MathText text={short(string(row.text) ?? "")} /></p>}
            </>
          )}
        />
        {string(result.note) && <p className="meta"><MathText text={string(result.note) ?? ""} /></p>}
      </div>
    );
  }
  if (event.tool === "related_papers") {
    return (
      <div className="result-card">
        <ResultItems
          label="related papers found"
          items={array(result.results)}
          pick={(row) => (
            <>
              <b><MathText text={string(row.title) ?? string(row.paper_id) ?? "paper"} /></b>
              {string(row.snippet) && <p><MathText text={string(row.snippet) ?? ""} /></p>}
            </>
          )}
        />
      </div>
    );
  }
  if (event.tool === "cited_paper_text") {
    const paper = object(result.paper);
    const passage = object(result.passage);
    return (
      <div className="result-card">
        {paper && <p><b><MathText text={string(paper.title) ?? string(paper.id) ?? "cited paper"} /></b></p>}
        {array(result.outline).length > 0 && (
          <>
            <div className="meta">available passages</div>
            <ul className="facts compact">
              {array(result.outline).slice(0, 12).map((line, i) => (
                <li key={i}><MathText text={typeof line === "string" ? line : JSON.stringify(line)} /></li>
              ))}
            </ul>
          </>
        )}
        {passage && string(passage.text) && <p><MathText text={short(string(passage.text) ?? "")} /></p>}
        {string(result.note) && <p className="meta"><MathText text={string(result.note) ?? ""} /></p>}
      </div>
    );
  }
  if (event.tool === "capture_note") {
    return <div className="result-card">note saved{result.quote_verified === true ? " with a verified quote" : ""}</div>;
  }
  if (event.tool === "feedback_context") {
    return <div className="result-card">feedback context loaded</div>;
  }
  if (event.tool === "cost_state") {
    return <div className="result-card">spent {String(result.spent_micros ?? 0)} micros in this run</div>;
  }
  if (event.tool === "submit_reading") {
    if (result.accepted === true) return <div className="result-card accepted">reading accepted</div>;
    return <div className="result-card refused">submission needs {string(result.field) ?? "a correction"}: {string(result.error) ?? "not accepted"}</div>;
  }
  return event.output ? <MathText text={event.output} /> : null;
}

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
                <ToolInput event={current} />
              </div>
            ) : null}
            <div className="said"><MathText text={current.body} /></div>
            {current.output ? (
              <>
                <ToolResult event={current} />
                <details>
                  <summary>raw record</summary>
                  <pre>{current.output}</pre>
                </details>
              </>
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
              <span className="t"><MathText text={e.input || e.body} /></span>
              <span className="c">{usd(e.cost_micros)}</span>
            </button>
          ))}
        </div>
      )}
    </>
  );
}
