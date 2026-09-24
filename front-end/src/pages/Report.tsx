import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";
import type { ReportView, ReportViewComparison } from "../api/schema.gen.ts";
import { useGet } from "../api/useGet.ts";
import { Card } from "../graphics/Cards.tsx";
import { ChanceBar } from "../graphics/ChanceBar.tsx";
import { Ids, Lead, ready, Replay, UNSERVED } from "./common.tsx";

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

/** The mock's health checks (design-mock/report.html) after the service-agreement table; none is served. */
const HEALTH_CHECKS = [
  "Were the agents early on the service's picks?",
  "How spread out are the topics?",
  "Are the agents overconfident?",
  "Does the cited evidence support the forecasts?",
] as const;

/**
 * One weekly island report (design-mock/report.html, FT-26), every mock section in order. The
 * replay, the explore links, agreement with the prediction heads, the owner's forecasts beside the
 * agents', the selection box and the health checks have no /api/v1 route and render empty
 * (docs/implementation/front-end.md).
 */
export function Report() {
  const { island = "", isoWeek = "" } = useParams();
  const view = useGet<ReportView>(`/api/v1/reports/${encodeURIComponent(island)}/${encodeURIComponent(isoWeek)}`);
  const v = ready(view);
  const r = v?.report ?? null;
  const first = r?.comparisons[0];
  const others = ISLANDS.filter((i) => i !== (r?.island ?? island));

  return (
    <>
      <div className="meta">
        <Link to="/reports">← reports</Link>
      </div>
      <h1>
        Weekly report · {r?.island ?? island} island · week {r?.iso_week ?? isoWeek}
      </h1>
      <Lead reads={[view]}>{() => v?.notice}</Lead>
      <h2>The week so far, replayed</h2>
      <div className="meta">Each day: the batch, the digest and your calls as they landed.</div>
      <Replay />
      <div className="explore">
        <Link to="/islands">the {r?.island ?? island} island →</Link>
        <Link to="/agents">the agents →</Link>
        <Link to="/impact">your impact →</Link>
        <a>today →</a>
      </div>
      <h2>Did you accept the agents&apos; picks more than chance?</h2>
      <div className="cards">
        <RateCard
          label="Agents' picks"
          rate={first?.population_rate ?? null}
          likes={first?.population_likes ?? 0}
          decided={first?.population_decided ?? 0}
        />
        {r?.comparisons.map((c) => (
          <RateCard
            key={c.comparator}
            label={v?.comparator_names[c.comparator] ?? c.comparator}
            rate={c.comparator_rate}
            likes={c.comparator_likes}
            decided={c.comparator_decided}
          />
        ))}
      </div>
      <div className="tw">
        <table>
          <tbody>
            <tr>
              <th>Comparison</th>
              <th>Difference in accept rate (0 to 1)</th>
              <th>95% interval</th>
              <th>Verdict</th>
            </tr>
            {!r || r.comparisons.length === 0 ? (
              <tr>
                <td colSpan={4}>none</td>
              </tr>
            ) : (
              r.comparisons.map((c) => (
                <ComparisonRow key={c.comparator} c={c} name={v?.comparator_names[c.comparator] ?? c.comparator} />
              ))
            )}
          </tbody>
        </table>
      </div>
      <div className="meta">
        A pass counts as not accepted.
        {first &&
          ` Intervals from ${first.interval.resamples.toLocaleString("en-US")} resamples (${first.interval.method} v${first.interval.method_version}) over ${first.weeks} publication weeks.`}{" "}
        Inconclusive is not &quot;the same&quot;.
      </div>
      <h2>Each agent this week so far</h2>
      <div className="tw">
        <table className="wide">
          <tbody>
            <tr>
              <th>Agent</th>
              {r?.rows[0]?.skills.map((s) => <th key={s.target_id}>Skill: {s.target_id}</th>)}
              <th>Rater credit</th>
              <th>Rated entries it came from</th>
              <th>Agreement with the prediction heads (0 to 1)</th>
            </tr>
            {!r || r.rows.length === 0 ? (
              <tr>
                <td colSpan={4}>none</td>
              </tr>
            ) : (
              r.rows.map((row) => (
                <tr key={row.genome_hash}>
                  <td>
                    {row.founder && <span className="code">founder</span>}{" "}
                    <span className="code" title={`genome ${row.genome_hash}`}>
                      {row.genome_hash.slice(0, 12)}
                    </span>
                  </td>
                  {row.skills.map((s) => (
                    <td key={s.target_id}>
                      {s.skill === null ? (
                        <span className="na">{s.disposition.replaceAll("_", " ")}</span>
                      ) : (
                        `${s.skill.toFixed(3)} (${s.support_count} resolved)`
                      )}
                    </td>
                  ))}
                  <td>
                    {row.preference_credit >= 0 ? "+" : ""}
                    {row.preference_credit.toFixed(2)} credit
                  </td>
                  <td>{row.credited_entries} entries</td>
                  <td>
                    <span className="na">{UNSERVED}</span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <div className="meta">
        Credit and its count are separate on purpose and are never combined.
        {r?.preference_reason && ` ${r.preference_reason}.`}{" "}
        {r &&
          (r.migrations.length === 0
            ? "No agents migrated this week."
            : `Migrated in: ${r.migrations.map((m) => `${m.child_hash.slice(0, 12)} from ${m.source_island}`).join(", ")}.`)}
      </div>
      <h2>You and the agents</h2>
      <div className="meta">The questions you answered this week, beside what the agents put on the same papers.</div>
      <div className="tw">
        <table>
          <tbody>
            <tr>
              <th>Paper</th>
              <th>Your chance (0 to 1)</th>
              <th>The agents’ average chance (0 to 1)</th>
            </tr>
            <tr>
              <td colSpan={3}>{UNSERVED}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div className="meta">Your answers this week: {UNSERVED}.</div>
      <h2>Selection this week</h2>
      <div className="box">Selection: {UNSERVED}.</div>
      <h2>
        Health checks <span className="meta">(none of these enters selection)</span>
      </h2>
      <h3>Are the agents picking what the discovery service picks?</h3>
      <div className="tw">
        <table>
          <tbody>
            <tr>
              <th>Agent</th>
              <th>Share of nominations not on the service&apos;s list (0 to 1)</th>
              <th>Nominations</th>
              <th>Shared with the service picks</th>
            </tr>
            <tr>
              <td colSpan={4}>{UNSERVED}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div className="meta">The discovery service&apos;s daily capture: {UNSERVED}.</div>
      {HEALTH_CHECKS.map((check) => [
        <h3 key={`${check}-h`}>{check}</h3>,
        <div className="box" key={check}>
          {check === "Are the agents overconfident?" ? <span className="na">{UNSERVED}</span> : UNSERVED}
        </div>,
      ])}
      <h2>Other islands</h2>
      <div className="meta">{others.join(" and ")} have the same report for this week.</div>
      <Ids
        rows={[
          ...(r?.rows ?? []).map((row) => [`genome ${row.genome_hash.slice(0, 12)}`, row.genome_hash] as const),
          ...(r?.migrations ?? []).map(
            (m) => [`${m.child_hash.slice(0, 12)} parent in ${m.source_island}`, m.source_hash] as const,
          ),
          ...(first ? [["interval support", first.interval.support_hash] as const] : []),
        ]}
      />
    </>
  );
}

function RateCard(p: { label: string; rate: number | null; likes: number; decided: number }) {
  return (
    <Card
      title={p.label}
      value={<ChanceBar p={p.rate} none="none rated" />}
      meta={
        <>
          {p.likes} of {p.decided} rated
        </>
      }
    />
  );
}

function signed(value: number): string {
  return `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(2)}`;
}

function ComparisonRow({ c, name }: { c: ReportViewComparison; name: string }) {
  const i = c.interval;
  return (
    <tr>
      <td>agents&apos; picks vs {name}</td>
      <td>{i.estimate === null ? "none" : signed(i.estimate)}</td>
      <td>
        {i.low !== null && i.high !== null
          ? `${signed(i.low)} to ${signed(i.high)}`
          : i.disposition.replaceAll("_", " ")}
      </td>
      <td>
        <b>{c.verdict.verdict.replaceAll("_", " ")}</b>
      </td>
    </tr>
  );
}
