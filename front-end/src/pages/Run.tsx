import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";
import type { Run as RunRecord, RunView } from "../api/schema.gen.ts";
import { useGet } from "../api/useGet.ts";
import { Id, Ids, More, Show, usd, when } from "./common.tsx";

/** The runs menu entry: the API reads runs by id, reached from an agent or a paper. */
export function Runs() {
  const navigate = useNavigate();
  const [runId, setRunId] = useState("");
  function open(e: FormEvent) {
    e.preventDefault();
    void navigate(`/runs/${encodeURIComponent(runId.trim())}`);
  }
  return (
    <>
      <h1>Runs</h1>
      <div className="meta">
        Runs are reached from their <Link to="/agents">agent</Link> or the paper they read, or by id.
      </div>
      <form onSubmit={open}>
        <label>
          Run id <input value={runId} onChange={(e) => setRunId(e.target.value)} />
        </label>
        <button type="submit" disabled={runId.trim() === ""}>
          open
        </button>
      </form>
    </>
  );
}

/** One run (design-mock/run.html): its record, its model turns and the claims it sealed. */
export function Run() {
  const { runId = "" } = useParams();
  const [cursor, setCursor] = useState<string | null>(null);
  const view = useGet<RunView>(`/api/v1/runs/${encodeURIComponent(runId)}`, { cursor });

  return (
    <Show loaded={view}>
      {(v) => (
        <>
          <RunHeader run={v.run} />
          <h2>Claims it sealed</h2>
          <div className="tw">
            <table className="wide">
              <tbody>
                <tr>
                  <th>Sealed</th>
                  <th>Status</th>
                  <th>Chance</th>
                  <th>Horizon</th>
                  <th>Reason</th>
                  <th>Evidence</th>
                </tr>
                {v.submissions.items.map((s) => (
                  <tr key={s.submission_id}>
                    <td>{when(s.sealed_at)}</td>
                    <td>{s.status}</td>
                    <td className="num">{s.confidence?.toFixed(2) ?? <span className="na">none</span>}</td>
                    <td>{when(s.horizon)}</td>
                    <td>{s.reason ?? <span className="na">none</span>}</td>
                    <td className="num">{s.evidence_hashes.length}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {v.submissions.items.length === 0 && <div className="meta">No claim sealed.</div>}
          <More cursor={v.submissions.next_cursor} onMore={setCursor} />
          <Events run={v.run} />
          <Ids
            rows={[
              ["run", v.run.run_id],
              ["batch", v.run.batch_id],
              ["genome hash", v.run.genome_hash],
              ["snapshot", v.run.snapshot_hash],
            ]}
          />
        </>
      )}
    </Show>
  );
}

/** What every run page leads with: who ran, on what, with which budget. */
export function RunHeader({ run }: { run: RunRecord }) {
  return (
    <>
      <div className="meta">
        <Link to={`/agents/${run.configuration_id}`}>← its agent</Link> ·{" "}
        <Link to={`/papers/${encodeURIComponent(run.paper_id)}`}>its paper</Link> ·{" "}
        <Link to={`/runs/${run.run_id}/trace`}>its tool calls</Link>
      </div>
      <h1>
        Run <Id value={run.run_id} /> <span className="meta">attempt {run.attempt}</span>
      </h1>
      <div className="tiles">
        <div className="card">
          <b>Started</b>
          <div className="v">{when(run.created_at)}</div>
        </div>
        <div className="card">
          <b>Budget</b>
          <div className="v">{usd(run.budgets.spend_micros)}</div>
          <span className="meta">seed {run.seed}</span>
        </div>
        <div className="card">
          <b>Tools allowed</b>
          <div className="v">{run.allowed_tools.length}</div>
          <span className="meta">{run.allowed_tools.join(", ") || "none"}</span>
        </div>
      </div>
    </>
  );
}

export function Events({ run }: { run: RunRecord }) {
  if (!run.events) return null;
  return (
    <>
      <h2>Model turns</h2>
      <div className="tw">
        <table>
          <tbody>
            <tr>
              <th>#</th>
              <th>Kind</th>
              <th>Recorded</th>
              <th>Payload</th>
            </tr>
            {run.events.map((e) => (
              <tr key={`${e.attempt}-${e.ordinal}`}>
                <td className="num">{e.ordinal}</td>
                <td>{e.kind}</td>
                <td>{when(e.recorded_at)}</td>
                <td>
                  <Id value={e.payload_hash} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
