import { useParams } from "react-router";
import type { OwnerRunTrace, OwnerRunTracePayload } from "../api/schema.gen.ts";
import { useGet } from "../api/useGet.ts";
import { Id, Show, when } from "./common.tsx";
import { Events, RunHeader } from "./Run.tsx";

/** Every tool call of one run in call order, owner only (#301). */
export function Trace() {
  const { runId = "" } = useParams();
  const trace = useGet<OwnerRunTrace>(`/api/v1/owner/runs/${encodeURIComponent(runId)}/trace`);

  return (
    <Show loaded={trace}>
      {(t) => (
        <>
          <RunHeader run={t.run} />
          <div className="meta">
            {t.run.ending
              ? t.run.ending.state === "void"
                ? `Void ${when(t.run.ending.ended_at)}: ${t.run.ending.reason ?? "no reason recorded"}.`
                : `Submitted ${when(t.run.ending.ended_at)}.`
              : "Still active."}
          </div>
          <h2>Tool calls</h2>
          {t.calls.items.length === 0 && <div className="meta">No tool call recorded.</div>}
          {t.calls.items.map((c) => (
            <details key={c.call_id} className={c.decision === "refused" ? "refused" : undefined}>
              <summary>
                <span className="tm">#{c.call_sequence}</span> <span className="tool">{c.tool}</span> ·{" "}
                {when(c.started_at)}
                {c.decision === "refused" && (
                  <>
                    {" "}
                    · <b>refused</b>: {c.reason}
                  </>
                )}
                {c.terminal?.outcome === "error" && ` · error ${c.terminal.error_code ?? ""}`}
                <span className="meta">
                  {" "}
                  · left: {Object.entries(c.remaining_budgets).map(([k, n]) => `${k} ${n}`).join(", ") || "none"}
                </span>
              </summary>
              <h3>Request</h3>
              <Payload payload={c.request} />
              <h3>Response</h3>
              {c.terminal ? <Payload payload={c.terminal.response} /> : <div className="meta">No answer.</div>}
            </details>
          ))}
          <Events run={t.run} />
        </>
      )}
    </Show>
  );
}

function Payload({ payload }: { payload: OwnerRunTracePayload }) {
  if (payload === null) return <div className="meta">Recorded before payloads were stored.</div>;
  return (
    <>
      <pre className="code">{payload.text}</pre>
      <div className="meta">
        artifact <Id value={payload.artifact_hash} />
        {payload.truncated && " · cut at 256 KiB; the hash is of the whole"}
      </div>
    </>
  );
}
