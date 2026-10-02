import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { refusal } from "../api/client.ts";
import { useApi } from "../api/context.tsx";
import type { IslandView, Micros, PaperView, RunEvent, RunView } from "../api/types.ts";
import { useGet } from "../api/useGet.ts";
import { Settled, badge, remember, when, type Badge } from "../common.tsx";
import { Feedback } from "../components/Feedback.tsx";
import { GenomeCard } from "../components/GenomeCard.tsx";
import { PaperViewer } from "../components/PaperViewer.tsx";
import { Replay } from "../components/Replay.tsx";
import { usd } from "../money.ts";

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

function RunBody({ view, startAt }: { view: RunView; startAt: number }) {
  const { run, events } = view;
  // The run answer names the paper and the genome by id; their records come from their own reads
  // unless the server already sent them along.
  const paperRead = useGet<PaperView>(view.paper ? null : `/api/v1/papers/${encodeURIComponent(run.paper_id)}`);
  // The island's agents are the session's to read only on its own island.
  const ownIsland = useApi().session?.island === run.island_id;
  const islandRead = useGet<IslandView>(view.genome || !ownIsland ? null : `/api/v1/islands/${encodeURIComponent(run.island_id)}`);
  const paper = view.paper ?? (paperRead.state === "ready" ? paperRead.data.paper : null);
  const genome = view.genome ?? (islandRead.state === "ready" ? (islandRead.data.genomes.find((g) => g.id === run.genome_id) ?? null) : null);

  const [step, setStep] = useState(() => (Number.isInteger(startAt) ? Math.max(0, Math.min(events.length, startAt)) : 0));
  const current = step > 0 ? events[step - 1] : undefined;
  const groups = costGroups(events);
  const sumOf = (type: Badge["type"]) => groups.filter((g) => g.type === type).reduce((s, g) => s + g.micros, 0);

  return (
    <>
      <div className="meta">
        <Link to={`/papers/${encodeURIComponent(run.paper_id)}`}>← paper</Link>
      </div>
      <h1>
        agent {run.genome_id} reading {paper?.title ?? "its paper"}
      </h1>
      <p className="lead">
        {run.status} · {when(run.created_at)} · <Link to={`/islands/${encodeURIComponent(run.island_id)}`}>island {run.island_id}</Link>
      </p>
      <div className="cards">
        <div className="card">
          <b>run cost</b>
          <div className="v">{usd(view.cost_micros)}</div>
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
          <span className="meta">stored for this run</span>
        </div>
      </div>

      <div className="sec">
        <h2>watch it</h2>
        <span>the paper above, the agent's steps below</span>
      </div>
      <div className="rplay">
        {paper !== null ? (
          <PaperViewer paper={paper} locator={current?.locator ?? null} step={step} />
        ) : (
          <div className="rp-pdf meta" role={paperRead.state === "failed" ? "alert" : undefined}>
            {paperRead.state === "failed" ? `The paper's record is not available. ${refusal(paperRead.error)}` : "Reading the paper…"}
          </div>
        )}
        <Replay events={events} step={step} onStep={setStep} opening={genome?.prompt ?? null} />
      </div>

      <div className="sec">
        <h2>what the agent was told</h2>
        <span>its genome as this run used it</span>
      </div>
      {genome !== null ? (
        <>
          <GenomeCard genome={genome} />
          {ownIsland && (
            <div className="explore">
              <Link to={`/islands/${encodeURIComponent(run.island_id)}#agent-${encodeURIComponent(genome.id)}`}>edit this agent on its island</Link>
            </div>
          )}
        </>
      ) : (
        <p className="meta" role={islandRead.state === "failed" ? "alert" : undefined}>
          {!ownIsland
            ? `Agent ${run.genome_id} belongs to island ${run.island_id}. Enter that island to see what it was told.`
            : islandRead.state === "loading"
              ? "Reading the genome…"
              : `The genome ${run.genome_id} is not available.`}
        </p>
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

      {run.reading !== "" && (
        <details className="after">
          <summary>the reading it submitted</summary>
          <div className="reading said">{run.reading}</div>
        </details>
      )}
      <Feedback targetType="run" targetId={run.id} />
      <details className="ids">
        <summary>Identifiers</summary>
        <div className="id">run {run.id}</div>
        <div className="id">paper {run.paper_id}</div>
        <div className="id">genome {run.genome_id}</div>
      </details>
    </>
  );
}

/** One run: the paper it read, its stored steps replayed beneath, the genome that drove it and what it cost. */
export function RunPage() {
  const { runId = "" } = useParams();
  const [params] = useSearchParams();
  const read = useGet<RunView>(`/api/v1/runs/${encodeURIComponent(runId)}`);
  useEffect(() => remember("run", runId), [runId]);
  const step = params.get("step");
  return (
    <Settled read={read} what="The run">
      {(view) => <RunBody key={`${view.run.id}:${step ?? ""}`} view={view} startAt={step === null ? 0 : Number(step)} />}
    </Settled>
  );
}
