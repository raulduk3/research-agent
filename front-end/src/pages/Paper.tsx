import { Fragment, useState, type MouseEvent } from "react";
import { Link, useParams } from "react-router";
import { ApiError } from "../api/client.ts";
import type { EmbeddingView, OwnerPaper, OwnerPaperRun } from "../api/schema.gen.ts";
import { useGet } from "../api/useGet.ts";
import { ChanceBar } from "../graphics/ChanceBar.tsx";
import { Id, Ids, Lead, More, ready, Refusal, Replay, Show, UNSERVED, when } from "./common.tsx";

/** The mock's tabs (design-mock/paper-P1.html), one panel each, in order. */
const TABS = [
  ["paper", "Paper"],
  ["conversation", "Conversation"],
  ["reads", "Reads"],
  ["analyst", "Analyst"],
  ["life", "Life"],
] as const;

type Tab = (typeof TABS)[number][0];

/**
 * Everything the agents saw of one paper family (design-mock/paper-P1.html, #301), the mock's five
 * panels in order: the paper, the conversation of its readers, their reads and the evidence they
 * cited, the analyst, and its life. The title, abstract, parts map and PDF, the rater's call, the
 * summarizer's reading, the baselines, the authors, the content assessment and the paper's days
 * have no /api/v1 route and render empty (docs/implementation/front-end.md). The stored requests,
 * cards and embedding are the paper's record page, linked under "More".
 */
export function Paper() {
  const { paperId = "" } = useParams();
  const [cursor, setCursor] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("paper");
  const paper = useGet<OwnerPaper>(`/api/v1/owner/papers/${encodeURIComponent(paperId)}`, { cursor });
  const p = ready(paper);
  const runs = p?.runs.items ?? [];
  const forecasts = runs.flatMap((r) => (r.ending?.submission?.forecasts ?? []).map((f) => ({ run: r, f })));
  const questions = [...new Set(forecasts.map(({ f }) => f.question_id))];
  const cited = new Map<string, Set<string>>();
  for (const { run, f } of forecasts)
    for (const e of f.evidence_ids) cited.set(e, (cited.get(e) ?? new Set()).add(run.run_id));

  const go = (to: Tab) => (e: MouseEvent) => {
    e.preventDefault();
    setTab(to);
  };
  const step = (to: Tab, label: string, forward: boolean) => (
    <a className={forward ? "go" : undefined} href={`#${to}`} onClick={go(to)}>
      {forward ? `${label} →` : `← ${label}`}
    </a>
  );

  return (
    <>
      <div className="meta">
        <Link to="/">← owner home</Link>
      </div>
      <h1>Paper {(p?.paper_id ?? paperId).slice(0, 8)}</h1>
      <Lead
        reads={[paper]}
        tail={
          <>
            {" "}
            · <a>arXiv: {UNSERVED}</a>
          </>
        }
      >
        {() =>
          p &&
          `${p.acquired_on_request ? "Acquired because a run asked for it" : "Came in by the population rule"} · ${runs.length} runs read it on this page`
        }
      </Lead>
      <div className="abs">Abstract: {UNSERVED}.</div>
      <nav className="seg" role="tablist" aria-label="this paper">
        {TABS.map(([id, label]) => (
          <a key={id} href={`#${id}`} role="tab" aria-selected={tab === id} onClick={go(id)}>
            {label}
          </a>
        ))}
      </nav>
      <section className="panel" id="paper" role="tabpanel" hidden={tab !== "paper"}>
        <h2>The paper</h2>
        <div className="meta">Sections, tables and figures by page.</div>
        <div className="pm">
          <div className="secs">Parts map: {UNSERVED}.</div>
          <div className="pgs" />
        </div>
        <div className="rp-pdf">
          <div className="rp-cap">
            <b>The paper</b> · <a>the PDF: {UNSERVED}</a>
          </div>
          <iframe title="the paper" />
        </div>
        <div className="feed">
          <b>Your call</b>
          <div className="state">none</div>
          <div className="meta">
            The rater&apos;s call: {UNSERVED}. <Link to="/impact">How credit works</Link>.
          </div>
        </div>
        <div className="stepbar">
          <span />
          {step("conversation", "the conversation", true)}
        </div>
      </section>
      <section className="panel" id="conversation" role="tabpanel" hidden={tab !== "conversation"}>
        <h2>The conversation</h2>
        <div className="cue">
          {runs.length === 0 ? "No run has read it." : "Each reader and the chance it gave. Open one to watch its run."}
        </div>
        <div className="thread">
          {runs.map((r) => (
            <div className="turn" key={r.run_id}>
              <span className="who">
                <Link to={`/agents/${r.configuration_id}`}>{r.configuration_id.slice(0, 8)}</Link>
              </span>
              <span className="say">
                {questions.length === 0 ? (
                  <Chance p={undefined} ending={r.ending} />
                ) : (
                  questions.map((q) => (
                    <Fragment key={q}>
                      question {q.slice(0, 8)} <Chance p={chance(r, q)} ending={r.ending} />{" "}
                    </Fragment>
                  ))
                )}
              </span>
              <Link className="watch" to={`/runs/${r.run_id}`}>
                ▶ watch its run
              </Link>
            </div>
          ))}
        </div>
        <More cursor={p?.runs.next_cursor ?? null} onMore={setCursor} />
        <div className="stepbar">
          {step("paper", "the paper", false)}
          {step("reads", "the reads", true)}
        </div>
      </section>
      <section className="panel" id="reads" role="tabpanel" hidden={tab !== "reads"}>
        <h2>The reads</h2>
        <div className="cue">Each read is a recorded run and its reasons.</div>
        <div className="reads">
          {forecasts.map(({ run, f }) => (
            <Link className="readtile" key={run.run_id + f.question_id} to={`/runs/${run.run_id}/trace`}>
              <b>{run.configuration_id.slice(0, 8)}</b>
              <span>
                question {f.question_id.slice(0, 8)}: {f.rationale}
              </span>
              <span className="meta">how it got there →</span>
            </Link>
          ))}
        </div>
        <h3>What they pointed at</h3>
        <div className="meta">The evidence ids the submitted forecasts cited, with how many runs cited each.</div>
        <div className="tw">
          <table>
            <tbody>
              <tr>
                <th>Evidence</th>
                <th>Cited by</th>
              </tr>
              {cited.size === 0 && (
                <tr>
                  <td colSpan={2}>No evidence cited.</td>
                </tr>
              )}
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
        <div className="stepbar">
          {step("conversation", "the conversation", false)}
          {step("analyst", "the analyst", true)}
        </div>
      </section>
      <section className="panel" id="analyst" role="tabpanel" hidden={tab !== "analyst"}>
        <h2>What the analyst said</h2>
        <div className="reading">The summarizer&apos;s reading: {UNSERVED}.</div>
        <div className="meta">A fixed summarizer writes this from the readers&apos; recorded forecasts and notes.</div>
        <h3>Against simple baselines</h3>
        <div className="meta">The same question answered without reading.</div>
        <div className="tw">
          <table>
            <tbody>
              <tr>
                <th>Baseline</th>
                <th>Five citations in a year (chance, 0 to 1)</th>
              </tr>
              <tr>
                <td colSpan={2}>{UNSERVED}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <details className="adv">
          <summary>More: the stored record, the content assessment</summary>
          <h3>The stored record</h3>
          <div className="tw">
            <table>
              <tbody>
                <tr>
                  <th>What</th>
                  <th>Held</th>
                </tr>
                <tr>
                  <td>Requests, cards the runs received, the embedding</td>
                  <td>
                    <Link to={`/papers/${encodeURIComponent(paperId)}/record`}>the paper&apos;s record →</Link>
                  </td>
                </tr>
                <tr>
                  <td>Authors&apos; prior citations</td>
                  <td>
                    <span className="na">{UNSERVED}</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <h3>Paper-content assessment</h3>
          <div className="meta">The outside assessment: {UNSERVED}.</div>
        </details>
        <div className="stepbar">
          {step("reads", "the reads", false)}
          {step("life", "its life", true)}
        </div>
      </section>
      <section className="panel" id="life" role="tabpanel" hidden={tab !== "life"}>
        <h2>Its life</h2>
        <div className="meta">Every day this paper was read, mentioned or sent: {UNSERVED}.</div>
        <div className="life" />
        <div>
          <Replay />
        </div>
        <div className="stepbar">{step("analyst", "the analyst", false)}</div>
      </section>
      <Ids rows={[["paper family", p?.paper_id ?? paperId]]} />
    </>
  );
}

function chance(r: OwnerPaperRun, q: string): number | undefined {
  return r.ending?.submission?.forecasts.find((f) => f.question_id === q)?.probability;
}

/** The paper's stored requests, the card each run's snapshot pinned, and its embedding view (#301). */
export function PaperRecord() {
  const { paperId = "" } = useParams();
  const paper = useGet<OwnerPaper>(`/api/v1/owner/papers/${encodeURIComponent(paperId)}`);
  return (
    <>
      <div className="meta">
        <Link to={`/papers/${encodeURIComponent(paperId)}`}>← the paper</Link>
      </div>
      <h1>Paper {paperId.slice(0, 8)}: the stored record</h1>
      <Show loaded={paper}>{(p) => <Record p={p} />}</Show>
    </>
  );
}

/** A chance as the mock's bar, or why a run has none. */
function Chance({ p, ending }: { p: number | undefined; ending: OwnerPaperRun["ending"] }) {
  if (p === undefined) {
    const why = ending === null ? "active" : ending.state === "void" ? `void: ${ending.reason ?? "no reason"}` : "none";
    return <span className="na">{why}</span>;
  }
  return <ChanceBar p={p} />;
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
