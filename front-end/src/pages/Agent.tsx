import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";
import type { AgentView, CommandResult, OwnerAgentView, OwnerGenome } from "../api/schema.gen.ts";
import { useCommand } from "../api/useCommand.ts";
import { useGet } from "../api/useGet.ts";
import { Id, Ids, More, Refusal, Show, usd, when } from "./common.tsx";

type Part = keyof OwnerGenome["emphasis"];

/** The mock's names for the four policy parts (design-mock/agent.html). */
export const PART_LABELS: Record<Part, string> = {
  prompt: "Instructions",
  scan_policy: "How it scans",
  read_policy: "How it reads",
  probability_assignment_rule: "How it sets probabilities",
};

/** One agent (design-mock/agent.html): its genome, owner history, runs and verdicts, and the owner's actions. */
export function Agent() {
  const { configurationId = "" } = useParams();
  const [cursor, setCursor] = useState<string | null>(null);
  const [forecastCursor, setForecastCursor] = useState<string | null>(null);
  const view = useGet<OwnerAgentView>(`/api/v1/agents/${encodeURIComponent(configurationId)}`, {
    cursor,
    forecast_cursor: forecastCursor,
  });

  return (
    <>
      <div className="meta">
        <Link to="/agents">← agents</Link>
      </div>
      <Show loaded={view}>
        {(v) => (
          <>
            <h1>
              <b>
                {v.genome.island} · {v.genome.lineage_id}
              </b>{" "}
              {v.genome.founder && <span className="code">founder</span>}{" "}
              <span className="code" title={v.genome.configuration_hash}>
                {v.genome.configuration_hash.slice(0, 12)}
              </span>
            </h1>
            <History view={v} />
            <h2>How it reads</h2>
            <div className="tw">
              <table className="kv">
                <tbody>
                  <tr>
                    <th>Part</th>
                    <th>Value</th>
                  </tr>
                  {(Object.keys(PART_LABELS) as Part[]).map((part) => (
                    <tr key={part}>
                      <td>{PART_LABELS[part]}</td>
                      <td className="code">{v.genome.emphasis[part]}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {v.inspected ? (
              <Inspected view={v.inspected} onRuns={setCursor} onForecasts={setForecastCursor} />
            ) : (
              <div className="meta">Runs and verdicts need the inspector, which this deployment does not reach.</div>
            )}
            <Actions view={v} onChanged={view.reload} />
            <Ids
              rows={[
                ["agent config", v.genome.configuration_id],
                ["config hash", v.genome.configuration_hash],
                ["lineage", v.genome.lineage_id],
              ]}
            />
          </>
        )}
      </Show>
    </>
  );
}

function History({ view }: { view: OwnerAgentView }) {
  const a = view.admission;
  return (
    <div className="meta">
      {a
        ? a.kind === "seed"
          ? `Seeded by the owner ${when(a.requested_at)}.`
          : `Admitted by the owner ${when(a.requested_at)} as an edit of `
        : "No owner action admitted it."}
      {a?.source_configuration_id && (
        <Link to={`/agents/${a.source_configuration_id}`}>
          <Id value={a.source_configuration_id} />
        </Link>
      )}
      {view.retirement && ` Retired ${when(view.retirement.requested_at)}; it leaves at the next weekly cycle.`}
    </div>
  );
}

function Inspected({
  view,
  onRuns,
  onForecasts,
}: {
  view: AgentView;
  onRuns: (cursor: string) => void;
  onForecasts: (cursor: string) => void;
}) {
  return (
    <>
      <h2>Runs</h2>
      <div className="tw">
        <table className="wide">
          <tbody>
            <tr>
              <th>Started</th>
              <th>Paper</th>
              <th>Attempt</th>
              <th>Budget</th>
              <th />
            </tr>
            {view.runs.items.map((r) => (
              <tr key={r.run_id}>
                <td>{when(r.created_at)}</td>
                <td>
                  <Link to={`/papers/${encodeURIComponent(r.paper_id)}`}>{r.paper_id}</Link>
                </td>
                <td className="num">{r.attempt}</td>
                <td className="num">{usd(r.budgets.spend_micros)}</td>
                <td>
                  <Link to={`/runs/${r.run_id}`}>run</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {view.runs.items.length === 0 && <div className="meta">No run yet.</div>}
      <More cursor={view.runs.next_cursor} onMore={onRuns} />
      <h2>Forecasts and verdicts</h2>
      <div className="tw">
        <table className="wide">
          <tbody>
            <tr>
              <th>Sealed</th>
              <th>Chance</th>
              <th>Horizon</th>
              <th>Verdict</th>
            </tr>
            {view.forecasts.items.map((f) => (
              <tr key={f.submission_id + f.question_id}>
                <td>{when(f.sealed_at)}</td>
                <td className="num">{f.confidence.toFixed(2)}</td>
                <td>{when(f.horizon)}</td>
                <td>{f.resolution ? f.resolution.status : <span className="na">pending</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <More cursor={view.forecasts.next_cursor} onMore={onForecasts} />
    </>
  );
}

function Actions({ view, onChanged }: { view: OwnerAgentView; onChanged: () => void }) {
  const id = encodeURIComponent(view.genome.configuration_id);
  const editable = view.emphasis_fields.items;
  const [lineage, setLineage] = useState(view.genome.lineage_id);
  const [parts, setParts] = useState<Record<string, string>>(() =>
    Object.fromEntries(editable.map((p) => [p, view.genome.emphasis[p]])),
  );
  const admit = useCommand<CommandResult>(`/api/v1/agents/${id}/admit`);
  const retire = useCommand<CommandResult>(`/api/v1/agents/${id}/retire`);

  function onAdmit(e: FormEvent) {
    e.preventDefault();
    // Only the parts that differ travel; the rest are the source's.
    const changed = Object.fromEntries(
      Object.entries(parts).filter(([p, value]) => view.genome.emphasis[p as Part] !== value),
    );
    void admit.send({ lineage_id: lineage, ...changed });
  }

  function onRetire(e: FormEvent) {
    e.preventDefault();
    void retire.send({}).then(onChanged);
  }

  return (
    <details className="adv">
      <summary>Advanced: owner actions on this agent</summary>
      <div className="meta">
        Every action writes a record. The stored agent, its runs and its forecasts never change.
      </div>
      <h3>Edit and admit as a new agent</h3>
      <form onSubmit={onAdmit}>
        <div className="meta">
          Prefilled from this agent. Creates a new agent with a lineage link to this one; this one is untouched.
        </div>
        <label>
          Lineage
          <input value={lineage} onChange={(e) => setLineage(e.target.value)} />
        </label>
        {editable.map((p) => (
          <label key={p}>
            {PART_LABELS[p]}
            <textarea value={parts[p] ?? ""} onChange={(e) => setParts({ ...parts, [p]: e.target.value })} />
          </label>
        ))}
        <button type="submit" disabled={admit.result.state === "sending"}>
          admit as new agent
        </button>
      </form>
      {admit.result.state === "failed" && <Refusal error={admit.result.error} />}
      {admit.result.state === "done" && (
        <div className="meta" role="status">
          Admitted:{" "}
          <Link to={`/agents/${admit.result.data.configuration_id}`}>
            <Id value={admit.result.data.configuration_id} />
          </Link>
        </div>
      )}
      <h3>Retire</h3>
      <form onSubmit={onRetire}>
        <div className="meta">
          Leaves the population at the next weekly cycle; its record stays. A founder cannot be retired.
        </div>
        <button type="submit" disabled={view.retirement !== null || retire.result.state === "sending"}>
          retire at next cycle
        </button>
      </form>
      {retire.result.state === "failed" && <Refusal error={retire.result.error} />}
      <div className="meta">
        <Link to={`/seed?template=${id}`}>Seed a variant into an island</Link>
      </div>
    </details>
  );
}
