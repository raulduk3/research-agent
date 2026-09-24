import { useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router";
import type { ReportView, ReportViewComparison } from "../api/schema.gen.ts";
import { useGet } from "../api/useGet.ts";
import { Id, Show } from "./common.tsx";

const ISLANDS = ["cs", "quant-ph", "q-bio"] as const;

/** The reports menu entry: a report is stored per island and ISO week. */
export function Reports() {
  const navigate = useNavigate();
  const [island, setIsland] = useState<string>(ISLANDS[0]);
  const [week, setWeek] = useState("");
  const valid = /^\d{4}-W\d{2}$/.test(week.trim());
  function open(e: FormEvent) {
    e.preventDefault();
    void navigate(`/reports/${island}/${week.trim()}`);
  }
  return (
    <>
      <h1>Reports</h1>
      <div className="meta">One report per island and ISO week, published after the weekly cycle.</div>
      <form onSubmit={open}>
        <label>
          Island{" "}
          <select value={island} onChange={(e) => setIsland(e.target.value)}>
            {ISLANDS.map((i) => (
              <option key={i}>{i}</option>
            ))}
          </select>
        </label>
        <label>
          Week <input placeholder="2026-W39" value={week} onChange={(e) => setWeek(e.target.value)} />
        </label>
        <button type="submit" disabled={!valid}>
          open
        </button>
      </form>
    </>
  );
}

/** One weekly island report (design-mock/report.html, FT-26). */
export function Report() {
  const { island = "", isoWeek = "" } = useParams();
  const view = useGet<ReportView>(`/api/v1/reports/${encodeURIComponent(island)}/${encodeURIComponent(isoWeek)}`);

  return (
    <Show loaded={view}>
      {(v) => (
        <>
          <h1>
            {v.report.island} <span className="meta">· week {v.report.iso_week}</span>
          </h1>
          <p className="meta">{v.notice}</p>
          <h2>Against the comparators</h2>
          {v.report.comparisons.length === 0 ? (
            <div className="meta">No comparison this week.</div>
          ) : (
            v.report.comparisons.map((c) => (
              <Comparison key={c.comparator} c={c} name={v.comparator_names[c.comparator]} />
            ))
          )}
          <h2>Genomes</h2>
          {v.report.preference_reason && <div className="meta">{v.report.preference_reason}</div>}
          <div className="tw">
            <table>
              <tbody>
                <tr>
                  <th>Genome</th>
                  <th>Skill by target</th>
                  <th>Preference credit</th>
                  <th>Credited entries</th>
                </tr>
                {v.report.rows.map((r) => (
                  <tr key={r.genome_hash}>
                    <td>
                      <Id value={r.genome_hash} />
                      {r.founder && <span className="meta"> · founder</span>}
                    </td>
                    <td>
                      {r.skills.map((s) => (
                        <div key={s.target_id}>
                          {s.target_id}: {s.skill === null ? s.disposition.replaceAll("_", " ") : s.skill.toFixed(3)}{" "}
                          <span className="meta">· {s.support_count} resolved</span>
                        </div>
                      ))}
                    </td>
                    <td>{r.preference_credit.toFixed(3)}</td>
                    <td>{r.credited_entries}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {v.report.migrations.length > 0 && (
            <>
              <h2>Migrations in</h2>
              <ul>
                {v.report.migrations.map((m) => (
                  <li key={m.child_hash}>
                    <Id value={m.child_hash} /> from {m.source_island} (<Id value={m.source_hash} />)
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </Show>
  );
}

function rate(value: number | null): string {
  return value === null ? "none" : `${(value * 100).toFixed(1)}%`;
}

function Comparison({ c, name }: { c: ReportViewComparison; name: string }) {
  const i = c.interval;
  return (
    <div className="card">
      <b>Population against {name}</b>
      <div className="v">{c.verdict.verdict.replaceAll("_", " ")}</div>
      <span className="meta">
        liked {rate(c.population_rate)} ({c.population_likes} of {c.population_decided}) against{" "}
        {rate(c.comparator_rate)} ({c.comparator_likes} of {c.comparator_decided}) over {c.weeks} weeks · difference{" "}
        {i.estimate === null ? "none" : i.estimate.toFixed(3)}
        {i.low !== null && i.high !== null && ` [${i.low.toFixed(3)}, ${i.high.toFixed(3)}]`} · {i.method} v
        {i.method_version}, {i.resamples} resamples · {i.disposition.replaceAll("_", " ")}
      </span>
    </div>
  );
}
