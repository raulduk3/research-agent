import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";
import type { AgentView, CommandResult, CommonIsland, OwnerAgentView, OwnerGenome } from "../api/schema.gen.ts";
import { useCommand } from "../api/useCommand.ts";
import { useGet } from "../api/useGet.ts";
import { Id, Ids, More, Refusal, Show, when } from "./common.tsx";

const ISLANDS: readonly CommonIsland[] = ["cs", "quant-ph", "q-bio"];

type Part = keyof OwnerGenome["emphasis"];

/** The mock's names for the four policy parts (design-mock/agent.html). */
export const PART_LABELS: Record<Part, string> = {
  prompt: "Instructions",
  scan_policy: "How it scans",
  read_policy: "How it reads",
  probability_assignment_rule: "How it sets probabilities",
};

/**
 * One agent (design-mock/agent.html): its owner history, runs, genome and the owner's actions.
 * The mock's explore links, day cards and replay have no /api/v1 route and are left out, and
 * its runs table loses the duration and outcome columns (docs/implementation/front-end.md).
 */
export function Agent() {
  const { configurationId = "" } = useParams();
  const [cursor, setCursor] = useState<string | null>(null);
  const view = useGet<OwnerAgentView>(`/api/v1/agents/${encodeURIComponent(configurationId)}`, { cursor });

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
              {v.genome.founder && <span className="code">founder</span>}
              {v.genome.founder && " "}
              <span className="code" title={v.genome.configuration_hash}>
                {v.genome.configuration_hash.slice(0, 12)}
              </span>
            </h1>
            <History view={v} />
            {v.inspected ? (
              <Runs view={v.inspected} onMore={setCursor} />
            ) : (
              <div className="meta">Runs need the inspector, which this deployment does not reach.</div>
            )}
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
                      <td>{part === "prompt" ? <pre>{v.genome.emphasis[part]}</pre> : v.genome.emphasis[part]}</td>
                    </tr>
                  ))}
                  <tr>
                    <td>Lineage</td>
                    <td>
                      {v.genome.lineage_id} · the {v.genome.island} island
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <Actions view={v} onChanged={view.reload} />
            <Ids
              rows={[
                ["agent config", v.genome.configuration_id],
                ["config hash", v.genome.configuration_hash],
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
    <p className="lead">
      {view.genome.founder ? `Founder of the ${view.genome.island} island. ` : ""}
      {a
        ? a.kind === "seed"
          ? `Seeded by you on ${when(a.requested_at)}.`
          : `Admitted by you on ${when(a.requested_at)} as an edit of `
        : "No owner action admitted it."}
      {a?.source_configuration_id && (
        <Link to={`/agents/${a.source_configuration_id}`}>
          <Id value={a.source_configuration_id} />
        </Link>
      )}
      {view.retirement && ` Retired ${when(view.retirement.requested_at)}; it leaves at the next weekly cycle.`}
    </p>
  );
}

function Runs({ view, onMore }: { view: AgentView; onMore: (cursor: string) => void }) {
  return (
    <>
      <h2>Its runs</h2>
      <div className="tw">
        <table className="wide">
          <tbody>
            <tr>
              <th>When</th>
              <th>Papers</th>
              <th />
            </tr>
            {view.runs.items.map((r) => (
              <tr key={r.run_id}>
                <td>{when(r.created_at)}</td>
                <td>
                  {r.paper_id}
                  {r.attempt > 1 ? ` · attempt ${r.attempt}` : ""}
                </td>
                <td>
                  <Link to={`/runs/${r.run_id}`}>open</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {view.runs.items.length === 0 && <div className="meta">No run yet.</div>}
      <More cursor={view.runs.next_cursor} onMore={onMore} />
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
  const seed = useCommand<CommandResult>("/api/v1/seed");
  const [island, setIsland] = useState<CommonIsland>(view.genome.island);
  const [seedLineage, setSeedLineage] = useState(view.genome.lineage_id);

  function onAdmit(e: FormEvent) {
    e.preventDefault();
    // Only the parts that differ travel; the rest are the source's.
    const changed = Object.fromEntries(
      Object.entries(parts).filter(([p, value]) => view.genome.emphasis[p as Part] !== value),
    );
    void admit.send({ lineage_id: lineage, ...changed });
  }

  function onSeed(e: FormEvent) {
    e.preventDefault();
    void seed.send({
      island,
      lineage_id: seedLineage,
      template_configuration_id: view.genome.configuration_id,
      ...view.genome.emphasis,
    });
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
        <input type="submit" value="admit as new agent" disabled={admit.result.state === "sending"} />
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
        <input
          type="submit"
          value="retire at next cycle"
          disabled={view.retirement !== null || retire.result.state === "sending"}
        />
      </form>
      {retire.result.state === "failed" && <Refusal error={retire.result.error} />}
      <h3>Seed a variant into an island</h3>
      <form onSubmit={onSeed}>
        <div className="meta">
          Copies this agent's four parts. The island's floor and its budget are enforced; a refusal says why.
        </div>
        <label>
          Island
          <select value={island} onChange={(e) => setIsland(e.target.value as CommonIsland)}>
            {ISLANDS.map((i) => (
              <option key={i}>{i}</option>
            ))}
          </select>
        </label>
        <label>
          Lineage
          <input value={seedLineage} onChange={(e) => setSeedLineage(e.target.value)} />
        </label>
        <input type="submit" value="seed variant" disabled={seed.result.state === "sending"} />
      </form>
      {seed.result.state === "failed" && <Refusal error={seed.result.error} />}
      {seed.result.state === "done" && (
        <div className="meta" role="status">
          Seeded:{" "}
          <Link to={`/agents/${seed.result.data.configuration_id}`}>
            <Id value={seed.result.data.configuration_id} />
          </Link>
        </div>
      )}
    </details>
  );
}
