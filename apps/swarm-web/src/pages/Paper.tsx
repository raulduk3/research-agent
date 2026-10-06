import { paperViewSchema } from "../api/contracts.ts";
import { useEffect, type CSSProperties } from "react";
import { Link, Navigate, useParams } from "react-router";
import { ApiError } from "../api/client.ts";
import { useApi } from "../api/context.tsx";
import type { Micros, PaperView } from "../api/types.ts";
import { useGet } from "../api/useGet.ts";
import { Settled, forget, pdfUrl, remember, webUrl, when } from "../common.tsx";
import { MathText } from "../components/MathText.tsx";
import { LetGo } from "../components/LetGo.tsx";
import { Like } from "../components/Like.tsx";
import { ReadingView } from "../components/ReadingView.tsx";
import { RunBranch } from "../components/Tree.tsx";
import { cost } from "../money.ts";

/**
 * Cost by island: the server's breakdown, or, when every run carries its own cost, the runs added
 * up by island. With neither, the breakdown is not known and is not shown as zero.
 */
type HeatSegment = { text: string; count: number };

function thesisHeat(summary: string, readings: readonly NonNullable<PaperView["readings"]>[number][]): HeatSegment[] {
  if (summary === "") return [];
  const points = new Set<number>([0, summary.length]);
  const ranges: { start: number; end: number }[] = [];
  for (const reading of readings) {
    const start = reading.thesis_char_start;
    const end = reading.thesis_char_end;
    if (typeof start !== "number" || typeof end !== "number" || start < 0 || end <= start || end > summary.length) continue;
    ranges.push({ start, end });
    points.add(start);
    points.add(end);
  }
  const sorted = [...points].sort((a, b) => a - b);
  return sorted.slice(0, -1).map((start, i) => {
    const end = sorted[i + 1] ?? start;
    return {
      text: summary.slice(start, end),
      count: ranges.filter((range) => range.start <= start && range.end >= end).length,
    };
  }).filter((segment) => segment.text !== "");
}

function ThesisHeat({ summary, readings }: { summary: string; readings: readonly NonNullable<PaperView["readings"]>[number][] }) {
  const segments = thesisHeat(summary, readings);
  if (segments.length === 0) return <span className="na">No abstract is stored for this paper.</span>;
  const max = Math.max(1, ...segments.map((segment) => segment.count));
  return (
    <span className="thesis-heat">
      {segments.map((segment, i) => (
        <span key={i} className={segment.count > 0 ? "hot" : undefined} style={segment.count > 0 ? ({ "--heat": String(segment.count / max) } as CSSProperties) : undefined}>
          <MathText text={segment.text} />
        </span>
      ))}
    </span>
  );
}

export function costByIsland(view: PaperView): Map<string, Micros> | null {
  if (view.cost_by_island && Object.keys(view.cost_by_island).length > 0) return new Map(Object.entries(view.cost_by_island));
  if (view.runs.length === 0 || !view.runs.every((r) => typeof r.cost_micros === "number")) return null;
  const sums = new Map<string, Micros>();
  for (const r of view.runs) sums.set(r.island_id, (sums.get(r.island_id) ?? 0) + (r.cost_micros ?? 0));
  return sums;
}

/** The paper cascade: the paper's record, the islands it went to, each run on it, and under each run its steps. */
export function PaperPage() {
  const { paperId = "" } = useParams();
  const read = useGet(`/api/v1/papers/${encodeURIComponent(paperId)}`, paperViewSchema);
  const session = useApi().session?.island ?? null;
  useEffect(() => remember("paper", paperId), [paperId]);
  if (read.state === "failed" && read.error instanceof ApiError && read.error.status === 404) {
    forget("paper");
    return <Navigate to="/" replace />;
  }
  return (
    <Settled read={read} what="The paper">
      {(view) => {
        const { paper } = view;
        const byIsland = costByIsland(view);
        const readings = view.readings ?? [];
        const readingsUnavailable = view.unavailable?.includes("readings") || view.readings == null;
        // The way back is the visitor's own island when the paper went there.
        const assignment = view.assignments.find((a) => a.island_id === session && a.paper_id === paper.id);
        const home = assignment?.island_id ?? null;
        const selection = assignment && assignment.kept !== undefined && !view.unavailable?.includes("assignments") ? { ...paper, kept: assignment.kept, released: assignment.released ?? null, selected_by: assignment.selected_by ?? null } : undefined;
        const source = webUrl(paper.url);
        const pdf = pdfUrl(paper);
        return (
          <main className="reading-page">
            <div className="meta">
              {home ? <Link to={`/islands/${encodeURIComponent(home)}`}>← island</Link> : <Link to="/">← storm</Link>}
            </div>
            <h1><MathText text={paper.title} /></h1>
            {selection && <div className="paper-selection"><LetGo papers={[selection]} onChanged={read.reload} /></div>}
            <div className="sec">
              <h2>readings</h2>
              <span>submitted takeaways · open the run for its evidence and steps</span>
            </div>
            {readingsUnavailable ? (
              <p className="meta">The paper's readings are unavailable.</p>
            ) : readings.length === 0 ? (
              <p className="meta">No reading has been submitted for this paper yet.</p>
            ) : (
              readings.map((reading) => (
                <section key={reading.id}>
                  <div className="meta">
                    <Link to={`/runs/${encodeURIComponent(reading.run_id)}`}>reading by {reading.genome_id}</Link> · {when(reading.created_at)}
                  </div>
                  <ReadingView reading={reading} likes={view.likes} />
                </section>
              ))
            )}
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
            <div className="meta">
              this paper <Like kind="paper" id={paper.id} likes={view.likes} />
            </div>
            <div className="cards">
              <div className="card">
                <b>paper cost</b>
                <div className="v">{cost(view.cost_micros)}</div>
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
                <span className="meta">agent-paper reads</span>
              </div>
            </div>
            <div className="abstract-heat">
              <p><ThesisHeat summary={paper.summary} readings={view.readings ?? []} /></p>
              {(view.readings ?? []).some((reading) => typeof reading.thesis_char_start === "number") && (
                <div className="meta">Highlighted text is the thesis sentence selected by submitted readings; darker means more agents chose overlapping words.</div>
              )}
            </div>

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
                        <td><MathText text={a.reason} /></td>
                        <td className="num">{view.runs.filter((r) => r.island_id === a.island_id).length}</td>
                        <td className="num">{cost(byIsland?.get(a.island_id))}</td>
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
                {view.runs.map((r) => <RunBranch key={r.id} run={r} />)}
              </div>
            )}

            <details className="ids">
              <summary>Identifiers</summary>
              <div className="id">paper {paper.id}</div>
            </details>
          </main>
        );
      }}
    </Settled>
  );
}
