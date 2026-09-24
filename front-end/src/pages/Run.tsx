import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";
import type { Run as RunRecord, RunView } from "../api/schema.gen.ts";
import { useGet } from "../api/useGet.ts";
import { Diag } from "../shell/Diag.tsx";
import { Ids, More, Show, usd, when } from "./common.tsx";

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

/** One run (design-mock/run.html): its record, its recorded steps and the claims it sealed. */
export function Run() {
  const { runId = "" } = useParams();
  const [cursor, setCursor] = useState<string | null>(null);
  const view = useGet<RunView>(`/api/v1/runs/${encodeURIComponent(runId)}`, { cursor });

  return (
    <>
      <Show loaded={view}>
        {(v) => (
          <>
            <RunHeader run={v.run} />
            <Events run={v.run} />
            <h2>What it submitted</h2>
            <div className="meta">One chance per question, with a reason, sealed with its evidence.</div>
            <div className="tw">
              <table className="wide">
                <tbody>
                  <tr>
                    <th>Claim</th>
                    <th>Chance (0 to 1)</th>
                    <th>Reason</th>
                  </tr>
                  {v.submissions.items.map((s) => (
                    <tr key={s.submission_id}>
                      <td>
                        {s.status}{" "}
                        <span className="meta">
                          sealed {when(s.sealed_at)} · horizon {when(s.horizon)} · {s.evidence_hashes.length} evidence
                        </span>
                      </td>
                      <td>
                        {s.confidence === null ? (
                          <span className="na">none</span>
                        ) : (
                          <span className="pb">
                            <i>
                              <b style={{ width: `${Math.round(s.confidence * 100)}%` }} />
                            </i>
                            <span className="num">{s.confidence.toFixed(2)}</span>
                          </span>
                        )}
                      </td>
                      <td className="small">{s.reason ?? <span className="na">none</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {v.submissions.items.length === 0 && <div className="meta">No claim sealed.</div>}
            <More cursor={v.submissions.next_cursor} onMore={setCursor} />
            <details className="adv">
              <summary>Advanced: run record and budgets</summary>
              <div className="tw">
                <table className="kv">
                  <tbody>
                    <tr>
                      <th>Field</th>
                      <th>Value</th>
                    </tr>
                    <tr>
                      <td>Batch</td>
                      <td>{v.run.batch_id}</td>
                    </tr>
                    <tr>
                      <td>Paper group</td>
                      <td>{v.run.paper_id}</td>
                    </tr>
                    <tr>
                      <td>Checkpoints</td>
                      <td>{v.run.checkpoint_dates.join(", ") || "none"}</td>
                    </tr>
                    <tr>
                      <td>Model</td>
                      <td>
                        <pre>{JSON.stringify(v.run.model_identity, null, 2)}</pre>
                        <span className="meta">the model identity the run recorded</span>
                      </td>
                    </tr>
                    <tr>
                      <td>Attempt</td>
                      <td>{v.run.attempt}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </details>
            <Ids
              rows={[
                ["run", v.run.run_id],
                ["agent", v.run.configuration_id],
                ["batch", v.run.batch_id],
                ["genome hash", v.run.genome_hash],
                ["snapshot", v.run.snapshot_hash],
              ]}
            />
          </>
        )}
      </Show>
      <Diag />
    </>
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
        A run ·{" "}
        <Link to={`/agents/${run.configuration_id}`}>
          <span className="code">{run.configuration_id.slice(0, 8)}</span>
        </Link>
      </h1>
      <p className="lead">
        Paper group {run.paper_id}, batch {run.batch_id}. Started {when(run.created_at)}, attempt {run.attempt}.
      </p>
      <div className="cards">
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
          <b>Recorded steps</b>
          <div className="v">{run.events?.length ?? "not recorded"}</div>
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

/** The run's recorded events, one step each, with the hash of its payload record. */
export function Events({ run }: { run: RunRecord }) {
  if (!run.events) return null;
  return (
    <>
      <h2>What it did, step by step</h2>
      <div className="meta">Each step is one recorded event; its payload is kept by hash.</div>
      <div className="tw">
        <table className="wide">
          <tbody>
            <tr>
              <th>Step</th>
              <th>Kind</th>
              <th>Record</th>
            </tr>
            {run.events.map((e) => (
              <tr key={`${e.attempt}-${e.ordinal}`}>
                <td>{e.ordinal}</td>
                <td>{e.kind}</td>
                <td>
                  <div className="small">
                    <span className="meta">{when(e.recorded_at)}</span>
                    <details>
                      <summary>payload</summary>
                      <span className="id">{e.payload_hash}</span>
                      <div className="meta">attempt {e.attempt}</div>
                    </details>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
