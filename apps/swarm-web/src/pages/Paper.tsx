import { useEffect } from "react";
import { Link, useParams } from "react-router";
import type { Micros, PaperView } from "../api/types.ts";
import { useGet } from "../api/useGet.ts";
import { Settled, pdfUrl, remember, webUrl, when } from "../common.tsx";
import { Feedback } from "../components/Feedback.tsx";
import { RunBranch } from "../components/Tree.tsx";
import { cost, usd } from "../money.ts";

/**
 * Cost by island: the server's breakdown, or, when every run carries its own cost, the runs added
 * up by island. With neither, the breakdown is not known and is not shown as zero.
 */
export function costByIsland(view: PaperView): Map<string, Micros> | null {
  if (view.cost_by_island) return new Map(Object.entries(view.cost_by_island));
  if (view.runs.length === 0 || !view.runs.every((r) => typeof r.cost_micros === "number")) return null;
  const sums = new Map<string, Micros>();
  for (const r of view.runs) sums.set(r.island_id, (sums.get(r.island_id) ?? 0) + (r.cost_micros ?? 0));
  return sums;
}

/** The paper cascade: the paper's record, the islands it went to, each run on it, and under each run its steps. */
export function PaperPage() {
  const { paperId = "" } = useParams();
  const read = useGet<PaperView>(`/api/v1/papers/${encodeURIComponent(paperId)}`);
  useEffect(() => remember("paper", paperId), [paperId]);
  return (
    <Settled read={read} what="The paper">
      {(view) => {
        const { paper } = view;
        const byIsland = costByIsland(view);
        const source = webUrl(paper.url);
        const pdf = pdfUrl(paper);
        return (
          <>
            <div className="meta">
              {view.assignments[0] ? <Link to={`/islands/${encodeURIComponent(view.assignments[0].island_id)}`}>← island</Link> : <Link to="/">← storm</Link>}
            </div>
            <h1>{paper.title}</h1>
            <p className="lead">
              {paper.primary_category} · fetched {when(paper.fetched_at)} · stored text: {paper.text_status}
            </p>
            <div className="explore">
              {source !== null && (
                <a href={source} target="_blank" rel="noreferrer">
                  source
                </a>
              )}
              {pdf !== null && (
                <a href={pdf} target="_blank" rel="noreferrer">
                  PDF
                </a>
              )}
            </div>
            <div className="cards">
              <div className="card">
                <b>paper cost</b>
                <div className="v">{usd(view.cost_micros)}</div>
                <span className="meta">every receipt under this paper</span>
              </div>
              <div className="card">
                <b>islands</b>
                <div className="v">{view.assignments.length}</div>
                <span className="meta">it was assigned to</span>
              </div>
              <div className="card">
                <b>runs</b>
                <div className="v">{view.runs.length}</div>
                <span className="meta">one agent each</span>
              </div>
            </div>
            <p>{paper.summary === "" ? <span className="na">No abstract is stored for this paper.</span> : paper.summary}</p>

            <div className="sec">
              <h2>islands</h2>
              <span>where it went, why, and what it cost there</span>
            </div>
            {view.assignments.length === 0 ? (
              <p className="meta">No island has taken this paper yet.</p>
            ) : (
              <div className="tw">
                <table>
                  <thead>
                    <tr>
                      <th>island</th>
                      <th>why</th>
                      <th>runs</th>
                      <th>cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {view.assignments.map((a) => (
                      <tr key={a.island_id}>
                        <td>
                          <Link to={`/islands/${encodeURIComponent(a.island_id)}`}>{a.island_id}</Link>
                        </td>
                        <td>{a.reason}</td>
                        <td className="num">{view.runs.filter((r) => r.island_id === a.island_id).length}</td>
                        <td className="num">{byIsland === null ? "not reported" : usd(byIsland.get(a.island_id) ?? 0)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <div className="sec">
              <h2>runs</h2>
              <span>cost beside each · open one for its steps</span>
            </div>
            {view.runs.length === 0 ? (
              <p className="meta">No agent has run on this paper yet.</p>
            ) : (
              <div className="tree">
                {view.runs.map((r) => (
                  <div key={r.id}>
                    <RunBranch run={r} />
                    {r.reading !== "" && (
                      <details className="after">
                        <summary>
                          reading by {r.genome_id} · {when(r.created_at)} · {cost(r.cost_micros)}
                        </summary>
                        <div className="reading said">{r.reading}</div>
                      </details>
                    )}
                  </div>
                ))}
              </div>
            )}

            <Feedback targetType="paper" targetId={paper.id} />
            <details className="ids">
              <summary>Identifiers</summary>
              <div className="id">paper {paper.id}</div>
            </details>
          </>
        );
      }}
    </Settled>
  );
}
