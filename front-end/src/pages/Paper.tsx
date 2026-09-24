import { useState } from "react";
import { Link, useParams } from "react-router";
import { ApiError } from "../api/client.ts";
import type { EmbeddingView, OwnerPaper } from "../api/schema.gen.ts";
import { useGet } from "../api/useGet.ts";
import { Id, Ids, More, Refusal, Show, usd, when } from "./common.tsx";

/** Everything the agents saw of one paper family (design-mock/paper.html, #301). */
export function Paper() {
  const { paperId = "" } = useParams();
  const [cursor, setCursor] = useState<string | null>(null);
  const paper = useGet<OwnerPaper>(`/api/v1/owner/papers/${encodeURIComponent(paperId)}`, { cursor });

  return (
    <Show loaded={paper}>
      {(p) => (
        <>
          <h1>
            Paper <Id value={p.paper_id} />
          </h1>
          <div className="meta">
            {p.acquired_on_request
              ? "Acquired because a run asked for it."
              : "Came in by the population rule."}
          </div>
          <h2>Runs that read it</h2>
          <div className="tw">
            <table className="wide">
              <tbody>
                <tr>
                  <th>Started</th>
                  <th>Agent</th>
                  <th>Budget</th>
                  <th>Ending</th>
                  <th>Claims</th>
                  <th />
                </tr>
                {p.runs.items.map((r) => (
                  <tr key={r.run_id}>
                    <td>{when(r.created_at)}</td>
                    <td>
                      <Link to={`/agents/${r.configuration_id}`}>
                        <Id value={r.configuration_id} />
                      </Link>
                    </td>
                    <td className="num">{usd(r.budgets.spend_micros)}</td>
                    <td>
                      {r.ending
                        ? r.ending.state === "void"
                          ? `void: ${r.ending.reason ?? "no reason"}`
                          : `submitted, ${r.ending.submission?.forecasts.length ?? 0} forecasts`
                        : "active"}
                    </td>
                    <td className="num">{r.outcomes.length}</td>
                    <td>
                      <Link to={`/runs/${r.run_id}`}>run</Link> · <Link to={`/runs/${r.run_id}/trace`}>tool calls</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {p.runs.items.length === 0 && <div className="meta">No run has read it.</div>}
          <More cursor={p.runs.next_cursor} onMore={setCursor} />
          <h2>Requests</h2>
          {p.requests.items.length === 0 ? (
            <div className="meta">No run asked for it.</div>
          ) : (
            <div className="tw">
              <table>
                <tbody>
                  <tr>
                    <th>Requested</th>
                    <th>Status</th>
                    <th>By run</th>
                  </tr>
                  {p.requests.items.map((q) => (
                    <tr key={q.request_id}>
                      <td>{when(q.requested_at)}</td>
                      <td>
                        {q.status}
                        {q.reason ? `: ${q.reason}` : ""}
                      </td>
                      <td>
                        <Link to={`/runs/${q.run_id}`}>
                          <Id value={q.run_id} />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <h2>Cards the runs received</h2>
          {p.cards.items.map((c) => (
            <details key={c.snapshot_hash + c.card_hash}>
              <summary>
                snapshot <Id value={c.snapshot_hash} /> · card <Id value={c.card_hash} />
              </summary>
              <pre className="code">{JSON.stringify(c.card, null, 2)}</pre>
            </details>
          ))}
          {p.cards.items.length === 0 && <div className="meta">No card pinned.</div>}
          <Embedding path={p.embedding_view} />
          <Ids rows={[["paper family", p.paper_id]]} />
        </>
      )}
    </Show>
  );
}

function Embedding({ path }: { path: string }) {
  const view = useGet<EmbeddingView>(path);
  if (view.state === "failed") {
    const unpublished = view.error instanceof ApiError && view.error.code === "not_found";
    return (
      <>
        <h2>Embedding</h2>
        {unpublished ? <div className="meta">No embedding published yet.</div> : <Refusal error={view.error} />}
      </>
    );
  }
  return (
    <>
      <h2>Embedding</h2>
      <Show loaded={view}>
        {(e) => {
          const peak = Math.max(1, ...e.overview.histogram.counts);
          return (
            <>
              <div className="meta">
                {e.dims} dimensions · {e.passages.items.length} passages · coverage {e.coverage} · {e.chunk_policy}
              </div>
              <h3>Overview coordinates</h3>
              <div className="hist" aria-label="overview coordinate histogram">
                {e.overview.histogram.counts.map((n, i) => (
                  <i key={i} style={{ height: `${(100 * n) / peak}%` }} title={String(n)} />
                ))}
              </div>
              <div className="meta">
                {e.overview.histogram.min} to {e.overview.histogram.max} in {e.overview.histogram.bins} bins
              </div>
              <h3>Nearest papers</h3>
              <div className="tw">
                <table>
                  <tbody>
                    <tr>
                      <th>Paper</th>
                      <th>Cosine</th>
                      <th>Earlier</th>
                    </tr>
                    {e.neighbors.items.map((n) => (
                      <tr key={n.paper_id}>
                        <td>
                          <Link to={`/papers/${n.paper_id}`}>{n.title}</Link>
                        </td>
                        <td className="num">{n.cos.toFixed(3)}</td>
                        <td>{n.earlier ? "yes" : "no"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <h3>Passages</h3>
              <div className="tw">
                <table className="wide">
                  <tbody>
                    <tr>
                      <th>#</th>
                      <th>Section</th>
                      <th>Excerpt</th>
                      <th>Tokens</th>
                      <th>Cosine to overview</th>
                    </tr>
                    {e.passages.items.map((s) => (
                      <tr key={s.order}>
                        <td className="num">{s.order}</td>
                        <td>{s.section_path.join(" › ")}</td>
                        <td>{s.excerpt}</td>
                        <td className="num">{s.tokens}</td>
                        <td className="num">{s.cos_overview.toFixed(3)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Ids
                rows={[
                  ["paper version", e.paper_version_id],
                  ["representation", e.representation_hash],
                  ["extraction", e.extraction_hash],
                  ["overview artifact", e.derived_from.overview_hash],
                  ["passage index", e.derived_from.passage_index_hash],
                  ["neighbor index", e.derived_from.neighbor_index_hash],
                ]}
              />
            </>
          );
        }}
      </Show>
    </>
  );
}
