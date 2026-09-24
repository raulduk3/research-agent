import { Fragment, useState } from "react";
import { Link, useParams } from "react-router";
import { ApiError } from "../api/client.ts";
import type { EmbeddingView, OwnerPaper, OwnerPaperRun } from "../api/schema.gen.ts";
import { useGet } from "../api/useGet.ts";
import { Diag } from "../shell/Diag.tsx";
import { Id, Ids, More, Refusal, Show, when } from "./common.tsx";

/**
 * Everything the agents saw of one paper family (design-mock/paper.html, #301), in the
 * mock's order: the readings, their reasons, the evidence they cited, then the stored
 * record under "More". The mock's reading pages are the run page for each run.
 */
export function Paper() {
  const { paperId = "" } = useParams();
  const [cursor, setCursor] = useState<string | null>(null);
  const paper = useGet<OwnerPaper>(`/api/v1/owner/papers/${encodeURIComponent(paperId)}`, { cursor });

  return (
    <Show loaded={paper}>
      {(p) => {
        const runs = p.runs.items;
        const forecasts = runs.flatMap((r) => (r.ending?.submission?.forecasts ?? []).map((f) => ({ run: r, f })));
        const questions = [...new Set(forecasts.map(({ f }) => f.question_id))];
        const chance = (r: OwnerPaperRun, q: string) =>
          r.ending?.submission?.forecasts.find((f) => f.question_id === q)?.probability;
        const cited = new Map<string, Set<string>>();
        for (const { run, f } of forecasts)
          for (const e of f.evidence_ids) cited.set(e, (cited.get(e) ?? new Set()).add(run.run_id));
        return (
          <>
            <div className="meta">
              <Link to="/">← owner home</Link>
            </div>
            <h1>Paper {p.paper_id.slice(0, 8)}</h1>
            <p className="lead">
              {p.acquired_on_request ? "Acquired because a run asked for it" : "Came in by the population rule"} ·{" "}
              {runs.length} runs read it on this page
            </p>
            <h2>The readings</h2>
            <div className="meta">
              Each bar is the chance a run gave, from 0 to 1, one column per question. Open a run to watch it step by
              step.
            </div>
            <div className="tw">
              <table>
                <tbody>
                  <tr>
                    <th>Agent</th>
                    {questions.map((q) => (
                      <th key={q}>Question {q.slice(0, 8)} (chance, 0 to 1)</th>
                    ))}
                    <th />
                  </tr>
                  {runs.map((r) => (
                    <tr key={r.run_id}>
                      <td>
                        <Link to={`/agents/${r.configuration_id}`}>{r.configuration_id.slice(0, 8)}</Link>
                      </td>
                      {questions.map((q) => (
                        <td key={q}>
                          <Chance p={chance(r, q)} ending={r.ending} />
                        </td>
                      ))}
                      <td>
                        <Link to={`/runs/${r.run_id}`}>watch its run →</Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <More cursor={p.runs.next_cursor} onMore={setCursor} />
            <h3>Their reasons</h3>
            {forecasts.map(({ run, f }) => (
              <div className="ans" key={run.run_id + f.question_id}>
                <b>{run.configuration_id.slice(0, 8)}</b> on question {f.question_id.slice(0, 8)}: {f.rationale}{" "}
                <Link className="small" to={`/runs/${run.run_id}/trace`}>
                  how it got there →
                </Link>
              </div>
            ))}
            {forecasts.length === 0 && <div className="meta">No run has submitted a forecast for it.</div>}
            {questions.length > 0 && (
              <div className="box">
                {questions.map((q) => {
                  const ps = runs.flatMap((r) => chance(r, q) ?? []);
                  return (
                    <Fragment key={q}>
                      On question {q.slice(0, 8)} the chances run from <Chance p={Math.min(...ps)} ending={null} /> to{" "}
                      <Chance p={Math.max(...ps)} ending={null} />.{" "}
                    </Fragment>
                  );
                })}
              </div>
            )}
            <h2>What they pointed at</h2>
            <div className="meta">The evidence ids the submitted forecasts cited, with how many runs cited each.</div>
            <div className="tw">
              <table>
                <tbody>
                  <tr>
                    <th>Evidence</th>
                    <th>Cited by</th>
                  </tr>
                  {[...cited].map(([e, by]) => (
                    <tr key={e}>
                      <td>
                        <Id value={e} />
                      </td>
                      <td>
                        {by.size} of {runs.length}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <details className="adv">
              <summary>More: the requests, the cards the runs received, the embedding</summary>
              <Record p={p} />
            </details>
            <Ids rows={[["paper family", p.paper_id]]} />
            <Diag />
          </>
        );
      }}
    </Show>
  );
}

/** A chance as the mock's bar, or why a run has none. */
function Chance({ p, ending }: { p: number | undefined; ending: OwnerPaperRun["ending"] }) {
  if (p === undefined) {
    const why = ending === null ? "active" : ending.state === "void" ? `void: ${ending.reason ?? "no reason"}` : "none";
    return <span className="na">{why}</span>;
  }
  return (
    <span className="pb">
      <i>
        <b style={{ width: `${Math.round(p * 100)}%` }} />
      </i>
      <span className="num">{p.toFixed(2)}</span>
    </span>
  );
}

/** The paper's stored requests, the card each run's snapshot pinned, and its embedding view. */
function Record({ p }: { p: OwnerPaper }) {
  return (
    <>
          <h3>Requests</h3>
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
          <h3>Cards the runs received</h3>
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
    </>
  );
}

function Embedding({ path }: { path: string }) {
  const view = useGet<EmbeddingView>(path);
  if (view.state === "failed") {
    const unpublished = view.error instanceof ApiError && view.error.code === "not_found";
    return (
      <>
        <h3>Embedding</h3>
        {unpublished ? <div className="meta">No embedding published yet.</div> : <Refusal error={view.error} />}
      </>
    );
  }
  return (
    <>
      <h3>Embedding</h3>
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
