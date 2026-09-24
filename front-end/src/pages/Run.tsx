import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";
import type { Run as RunRecord, RunView } from "../api/schema.gen.ts";
import { useGet, type Loaded } from "../api/useGet.ts";
import { Ids, Lead, More, ready, Replay, UNSERVED, usd, when } from "./common.tsx";

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

/**
 * One run (design-mock/run.html): its record, its recorded steps and the claims it sealed, in the
 * mock's order. Every section renders when the read is refused; the explore links, the replay and
 * the digest nominations have no /api/v1 route and render empty (docs/implementation/front-end.md).
 */
export function Run() {
  const { runId = "" } = useParams();
  const [cursor, setCursor] = useState<string | null>(null);
  const view = useGet<RunView>(`/api/v1/runs/${encodeURIComponent(runId)}`, { cursor });
  const v = ready(view);
  const r = v?.run ?? null;
  const submissions = v?.submissions.items ?? [];

  return (
    <>
      <RunHeader run={r} runId={runId} loaded={view} />
      <h2>Watch it</h2>
      <div className="meta">The run replayed from its record; nothing here calls a model.</div>
      <Replay />
      <Events run={r} />
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
            {submissions.length === 0 && (
              <tr>
                <td colSpan={3}>No claim sealed.</td>
              </tr>
            )}
            {submissions.map((s) => (
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
      <More cursor={v?.submissions.next_cursor ?? null} onMore={setCursor} />
      <h3>Its nominations for the digest</h3>
      <div className="tw">
        <table>
          <tbody>
            <tr>
              <th>#</th>
              <th>Paper</th>
              <th>Why</th>
            </tr>
            <tr>
              <td colSpan={3}>{UNSERVED}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <details className="adv">
        <summary>Advanced: run record and budgets</summary>
        <div className="tw">
          <table className="kv">
            <tbody>
              <tr>
                <th>Field</th>
                <th>Value</th>
              </tr>
              {r === null ? (
                <tr>
                  <td colSpan={2}>none</td>
                </tr>
              ) : (
                <>
                  <tr>
                    <td>Batch</td>
                    <td>{r.batch_id}</td>
                  </tr>
                  <tr>
                    <td>Paper group</td>
                    <td>{r.paper_id}</td>
                  </tr>
                  <tr>
                    <td>Checkpoints</td>
                    <td>{r.checkpoint_dates.join(", ") || "none"}</td>
                  </tr>
                  <tr>
                    <td>Model</td>
                    <td>
                      <pre>{JSON.stringify(r.model_identity, null, 2)}</pre>
                      <span className="meta">the model identity the run recorded</span>
                    </td>
                  </tr>
                  <tr>
                    <td>Attempt</td>
                    <td>{r.attempt}</td>
                  </tr>
                </>
              )}
            </tbody>
          </table>
        </div>
      </details>
      <Ids
        rows={[
          ["run", r?.run_id ?? runId],
          ["agent", r?.configuration_id],
          ["batch", r?.batch_id],
          ["genome hash", r?.genome_hash],
          ["snapshot", r?.snapshot_hash],
        ]}
      />
    </>
  );
}

/** What every run page leads with: who ran, on what, with which budget; empty until the run is read. */
export function RunHeader({ run, runId, loaded }: { run: RunRecord | null; runId: string; loaded: Loaded<unknown> }) {
  const agent = run ? `/agents/${run.configuration_id}` : "/agents";
  return (
    <>
      <div className="meta">
        <Link to={agent}>← its agent</Link> ·{" "}
        <Link to={run ? `/papers/${encodeURIComponent(run.paper_id)}` : "/runs"}>its paper</Link> ·{" "}
        <Link to={`/runs/${encodeURIComponent(runId)}/trace`}>its tool calls</Link>
      </div>
      <h1>
        A run ·{" "}
        <Link to={agent}>
          <span className="code">{run ? run.configuration_id.slice(0, 8) : "none"}</span>
        </Link>
      </h1>
      <Lead reads={[loaded]}>
        {() =>
          run && `Paper group ${run.paper_id}, batch ${run.batch_id}. Started ${when(run.created_at)}, attempt ${run.attempt}.`
        }
      </Lead>
      <div className="explore">
        <Link to={agent}>this agent →</Link>
        <Link to="/islands">its island →</Link>
        <Link to="/swarm">the swarm today →</Link>
        <Link to="/reports">this week →</Link>
        <a>the paper it nominated first →</a>
      </div>
      <div className="cards">
        <div className="card">
          <b>Started</b>
          <div className="v">{run ? when(run.created_at) : "none"}</div>
        </div>
        <div className="card">
          <b>Budget</b>
          <div className="v">{run ? usd(run.budgets.spend_micros) : "none"}</div>
          <span className="meta">{run ? `seed ${run.seed}` : "no run read"}</span>
        </div>
        <div className="card">
          <b>Recorded steps</b>
          <div className="v">{run ? (run.events?.length ?? "not recorded") : "none"}</div>
        </div>
        <div className="card">
          <b>Tools allowed</b>
          <div className="v">{run ? run.allowed_tools.length : "none"}</div>
          <span className="meta">{run ? run.allowed_tools.join(", ") || "none" : "no run read"}</span>
        </div>
      </div>
    </>
  );
}

/** The run's recorded events, one step each, with the hash of its payload record. */
export function Events({ run }: { run: RunRecord | null }) {
  const events = run?.events ?? [];
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
            {events.length === 0 && (
              <tr>
                <td colSpan={3}>{run?.events ? "No step recorded." : "Steps not recorded."}</td>
              </tr>
            )}
            {events.map((e) => (
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
