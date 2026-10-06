import { runViewSchema } from "../api/contracts.ts";
import { useEffect, useState } from "react";
import { Link, Navigate, useParams, useSearchParams } from "react-router";
import { ApiError } from "../api/client.ts";
import { useApi } from "../api/context.tsx";
import type { Micros, RunEvent, RunView } from "../api/types.ts";
import { useGet } from "../api/useGet.ts";
import { Settled, badge, forget, remember, when, type Badge } from "../common.tsx";
import { GenomeCard } from "../components/GenomeCard.tsx";
import { Like } from "../components/Like.tsx";
import { MathText } from "../components/MathText.tsx";
import { PaperViewer } from "../components/PaperViewer.tsx";
import { ReadingView } from "../components/ReadingView.tsx";
import { Replay } from "../components/Replay.tsx";
import { cost, usd } from "../money.ts";

export type CostGroup = Badge & { steps: number; micros: Micros };

/** The run's stored step costs added up by what each step was: each model, each tool, each other step. */
export function costGroups(events: readonly RunEvent[]): CostGroup[] {
  const groups = new Map<string, CostGroup>();
  for (const e of events) {
    const b = badge(e);
    const key = `${b.type}:${b.label}`;
    const g = groups.get(key) ?? { ...b, steps: 0, micros: 0 };
    g.steps += 1;
    g.micros += e.cost_micros;
    groups.set(key, g);
  }
  return [...groups.values()].sort((a, b) => b.micros - a.micros);
}

/** A run that is still being worked on, so more steps may yet be stored. */
export function isLive(status: string): boolean {
  return status === "queued" || status === "running";
}

/** How often a live run is read again. */
const WATCH_MS = 3000;

function RunBody({ view, startAt }: { view: RunView; startAt: number | null }) {
  const { run, events } = view;
  const paper = view.paper ?? null;
  const genome = view.genome ?? null;
  const live = isLive(run.status);
  const mine = useApi().session?.island === run.island_id;

  const [step, setStep] = useState(() => (startAt !== null && Number.isInteger(startAt) ? Math.max(0, Math.min(events.length, startAt)) : 0));
  // A live run opened without a step is followed: the replay stays on the newest stored step
  // until the visitor takes the controls.
  const [following, setFollowing] = useState(live && startAt === null);
  const shown = following ? events.length : Math.min(step, events.length);
  const current = shown > 0 ? events[shown - 1] : undefined;
  const take = (to: number) => {
    setFollowing(false);
    setStep(to);
  };
  const groups = costGroups(events);
  const sumOf = (type: Badge["type"]) => groups.filter((g) => g.type === type).reduce((s, g) => s + g.micros, 0);

  return (
    <main className="reading-page">
      <div className="meta">
        <Link to={`/papers/${encodeURIComponent(run.paper_id)}`}>← paper</Link>
      </div>
      <h1>
        agent {run.genome_id} reading <MathText text={paper?.title ?? "its paper"} />
      </h1>
      <p className="lead">
        {run.status}
        {run.failure ? ` (${run.failure.replace(/_/g, " ")})` : ""} · {when(run.created_at)} ·{" "}
        <Link to={`/islands/${encodeURIComponent(run.island_id)}`}>island {run.island_id}</Link>
      </p>
      {view.reading ? (
        <>
          <div className="sec">
            <h2>the reading it submitted</h2>
            <span>takeaways from this run</span>
          </div>
          <ReadingView reading={view.reading} likes={view.likes} />
        </>
      ) : (
        <p className="meta">
          {live ? `No reading has been submitted yet. This run is ${run.status}.` : run.status === "failed" ? "This run failed without a submitted reading." : `No reading is stored for this ${run.status} run.`}
        </p>
      )}
      <div className="cards">
        <div className="card">
          <b>run cost</b>
          <div className="v">{cost(view.cost_micros)}</div>
          <span className="meta">settled receipts</span>
        </div>
        <div className="card">
          <b>model</b>
          <div className="v">{usd(sumOf("model"))}</div>
          <span className="meta">across model steps</span>
        </div>
        <div className="card">
          <b>tools</b>
          <div className="v">{usd(sumOf("tool"))}</div>
          <span className="meta">across tool steps</span>
        </div>
        <div className="card">
          <b>steps</b>
          <div className="v">{events.length}</div>
          <span className="meta">{live ? "stored so far" : "stored for this run"}</span>
        </div>
      </div>

      <div className="sec">
        <h2>watch it</h2>
        <span>{live ? (following ? "live: following the agent" : "live: more steps are arriving") : "the paper above, the agent's steps below"}</span>
      </div>
      <div className="rplay">
        {paper !== null ? (
          <PaperViewer paper={paper} locator={current?.locator ?? null} step={shown} />
        ) : (
          <div className="rp-pdf meta">The paper's record was not sent with this run.</div>
        )}
        <Replay events={events} step={shown} onStep={take} opening={genome?.prompt ?? null} />
        {live && !following && (
          <div className="rp-side">
            <button type="button" className="quiet ctl" onClick={() => setFollowing(true)}>
              follow the agent live
            </button>
          </div>
        )}
      </div>

      <div className="sec">
        <h2>what the agent was told</h2>
        <span>its genome as this run used it</span>
      </div>
      {genome !== null ? (
        <>
          <GenomeCard genome={{ ...genome, island_id: genome.island_id ?? run.island_id }} />
          {mine && (
            <div className="explore">
              <Link to={`/islands/${encodeURIComponent(run.island_id)}#agent-${encodeURIComponent(genome.id)}`}>edit this agent on its island</Link>
            </div>
          )}
        </>
      ) : (
        <p className="meta">The genome {run.genome_id} was not sent with this run.</p>
      )}

      <div className="sec">
        <h2>where the cost went</h2>
        <span>by model, tool and step</span>
      </div>
      {groups.length === 0 ? (
        <p className="meta">No step is stored, so no step cost is known.</p>
      ) : (
        <div className="tw">
          <table>
            <thead>
              <tr>
                <th>what</th>
                <th>steps</th>
                <th>cost</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((g) => (
                <tr key={`${g.type}:${g.label}`}>
                  <td>{g.type === "step" ? g.label : `${g.type} · ${g.label}`}</td>
                  <td className="num">{g.steps}</td>
                  <td className="num">{usd(g.micros)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="meta">
        this run <Like kind="run" id={run.id} likes={view.likes} />
      </div>
      <details className="ids">
        <summary>Identifiers</summary>
        <div className="id">run {run.id}</div>
        <div className="id">paper {run.paper_id}</div>
        <div className="id">
          genome {run.genome_id}
          {typeof run.genome_version === "number" ? ` version ${run.genome_version}` : ""}
        </div>
      </details>
    </main>
  );
}

/**
 * One run: the paper it read, its stored steps replayed beneath, the genome that drove it and what
 * it cost. A run still in progress is read again every few seconds, so its new steps appear as the
 * agent stores them.
 */
export function RunPage() {
  const { runId = "" } = useParams();
  const [params] = useSearchParams();
  const read = useGet(`/api/v1/runs/${encodeURIComponent(runId)}`, runViewSchema);
  useEffect(() => remember("run", runId), [runId]);
  const live = read.state === "ready" && isLive(read.data.run.status);
  const reload = read.reload;
  useEffect(() => {
    if (!live) return;
    const timer = setInterval(reload, WATCH_MS);
    return () => clearInterval(timer);
  }, [live, reload]);
  const step = params.get("step");
  if (read.state === "failed" && read.error instanceof ApiError && read.error.status === 404) {
    forget("run");
    return <Navigate to="/" replace />;
  }
  return (
    <Settled read={read} what="The run">
      {(view) => <RunBody key={`${view.run.id}:${step ?? ""}`} view={view} startAt={step === null ? null : Number(step)} />}
    </Settled>
  );
}
