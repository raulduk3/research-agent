import { useSearchParams } from "react-router";
import type { OwnerCosts } from "../api/schema.gen.ts";
import { useGet } from "../api/useGet.ts";
import { SpendChart } from "../graphics/SpendChart.tsx";
import { Ids, Lead, ready, UNSERVED, usd } from "./common.tsx";

/** The alert tick on each cap bar: spending at 80% of either cap raises an alert (SDD). */
const ALERT = 0.8;

const percent = (part: number, whole: number) => (whole > 0 ? Math.min(100, (100 * part) / whole) : 0);

const ISLANDS = ["cs", "quant-ph", "q-bio"] as const;

/** The launch profile fold's sections (design-mock/costs.html); no /api/v1 route serves the profile. */
const PROFILE_SECTIONS = ["Selection", "Each run", "Agent model", "Papers", "Raters", "Safety and alerts"] as const;

/** The islands table's columns (design-mock/costs.html); no /api/v1 route serves them. */
const ISLAND_COLUMNS = [
  "Island",
  "Papers from",
  "Rated by",
  "Agents",
  "Budget share",
  "Founder",
  "Selection proxy until outcomes exist",
  "Accepts agents from other islands",
] as const;

/**
 * Settled spend (design-mock/costs.html): one UTC day and its month against the caps (#251), every
 * mock section in order; the spend chart draws the day read. `?day=YYYY-MM-DD` picks the day;
 * without it the server picks today (UTC) rather than the browser's clock. Spend on the other days,
 * each island's share, pausing paid execution, the islands table, skill per dollar and the launch
 * profile have no /api/v1 route and render empty (docs/implementation/front-end.md).
 */
export function Costs() {
  const [params] = useSearchParams();
  const day = params.get("day") ?? "";
  const costs = useGet<OwnerCosts>("/api/v1/costs", day ? { day } : {});
  const c = ready(costs);
  const agents = c?.by_configuration.items ?? [];
  const perRun = agents.map((a) => (a.priced_runs > 0 ? a.priced_micros / a.priced_runs : 0));
  const widest = Math.max(0, ...perRun);

  return (
    <>
      <h1>Costs</h1>
      <Lead reads={[costs]}>
        {() =>
          "What the swarm spends against the caps the launch profile fixes. Owner only: a rater has nothing to " +
          "configure, so there is no settings page. Numbers are settled spend; a run without a price is counted by " +
          "its tokens and never given one."
        }
      </Lead>
      <div className="sec">
        <h2>Today and this month</h2>
        <span>caps from the launch profile · UTC days</span>
      </div>
      <div className="cards">
        <div className="card">
          <b>{c?.day ?? "today"}</b>
          {c ? usd(c.today.priced_micros) : "none"}{" "}
          <span className="meta">
            {c
              ? `of ${usd(c.caps.daily_cap_micros)} · ${Math.round(percent(c.today.priced_micros, c.caps.daily_cap_micros))}%`
              : "no costs read"}
          </span>
        </div>
        <div className="card">
          <b>{c?.month ?? "this month"}</b>
          {c ? usd(c.month_to_date.priced_micros) : "none"}{" "}
          <span className="meta">
            {c ? `of ${usd(c.caps.monthly_cap_micros)} · shared by the islands, per agent below` : "no costs read"}
          </span>
        </div>
        <div className="card">
          <b>assessment sublimit</b>
          {c ? usd(c.caps.jev_daily_sublimit_micros) : "none"} <span className="meta">a day · profile constant</span>
        </div>
        <div className="card">
          <b>paid execution</b>
          {c ? (c.caps.paid_execution_enabled ? "enabled" : "disabled") : "none"}{" "}
          <span className="meta">{c ? (c.caps.funded ? "funded" : "not funded") : "no costs read"}</span>
        </div>
      </div>
      <p className="meta">
        source: <b>settlements</b> · micro-dollars, shown to the cent
        {c && c.today.unpriced_runs > 0 && ` · ${c.today.unpriced_runs} unpriced runs today`}
      </p>
      <h2>Spending</h2>
      <h3>Settled per day</h3>
      <div className="graph">
        <div className="legend">
          <i />
          agents’ model calls
          <i />
          summarizer
          <i />
          scholarly APIs
        </div>
        <SpendChart
          days={c ? [{ day: c.day, micros: c.today.priced_micros }] : []}
          capMicros={c?.caps.daily_cap_micros ?? null}
          alert={ALERT}
          label={c ? `settled spend on ${c.day} against the ${usd(c.caps.daily_cap_micros)} daily cap` : "no costs read"}
        />
        <div className="cap">
          Settled spend in UTC day buckets. Only {c?.day ?? "the day read"} is drawn, as one undivided total: spend on
          the month's other days and its split by source are {UNSERVED}.
        </div>
      </div>
      <h3>Against each cap</h3>
      <div className="graph">
        <div className="hbars" role="img" aria-label="spend against each cap">
          <Bar
            label={`${c?.day ?? "today"}, everything`}
            spent={c?.today.priced_micros ?? null}
            cap={c?.caps.daily_cap_micros ?? null}
          />
          <Bar
            label={`${c?.month ?? "this month"}, everything`}
            spent={c?.month_to_date.priced_micros ?? null}
            cap={c?.caps.monthly_cap_micros ?? null}
          />
        </div>
        <div className="cap">
          A call is refused when settled charges plus outstanding reservations would pass any cap; the tick on each bar
          is the alert at 80%. Caps change only with a new profile version.
        </div>
        <h3>Each island’s share of the month</h3>
        <div className="hbars" role="img" aria-label="island spend against its share">
          {ISLANDS.map((island) => (
            <Bar key={island} label={`${island}, ${c?.month ?? "this month"}`} spent={null} cap={null} />
          ))}
        </div>
        <div className="cap">An island’s share of the monthly cap bounds how many agents it can afford: {UNSERVED}.</div>
      </div>
      <h3>Cost per run, by agent</h3>
      <div className="graph">
        <div className="hbars" role="img" aria-label="measured model cost per run by agent">
          {agents.length === 0 && (
            <div className="hrow">
              <span className="hl">no agent</span>
              <span className="hb" />
              <span className="hv">no priced run</span>
            </div>
          )}
          {agents.map((a, i) => (
            <div className="hrow" key={a.configuration_id}>
              <span className="hl">{agentLabel(a.island, a.configuration_id)}</span>
              <span className="hb">
                <i style={{ width: `${percent(perRun[i] ?? 0, widest).toFixed(1)}%` }} />
              </span>
              <span className="hv">
                {a.priced_runs > 0 ? `USD ${((perRun[i] ?? 0) / 1_000_000).toFixed(4)} a run` : "no priced run"} ·{" "}
                {a.priced_runs} priced runs in {c?.month}
              </span>
            </div>
          ))}
        </div>
        <div className="cap">Settled spend over priced runs, this month. Spend never ranks an agent.</div>
      </div>
      <h2>Spending caps</h2>
      <div className="tw">
        <table>
          <tbody>
            <tr>
              <th>Lever</th>
              <th>Now</th>
              <th>How it changes</th>
            </tr>
            {c === null ? (
              <tr>
                <td colSpan={3}>none</td>
              </tr>
            ) : (
              <>
                <tr>
                  <td>Paid execution</td>
                  <td>
                    <b>{c.caps.paid_execution_enabled ? "on" : "off"}</b>
                  </td>
                  <td className="meta">enabling needs a funding record and a passed qualification</td>
                </tr>
                <tr>
                  <td>Daily cap, everything</td>
                  <td>{usd(c.caps.daily_cap_micros)}</td>
                  <td className="meta">new profile version</td>
                </tr>
                <tr>
                  <td>Monthly cap, everything</td>
                  <td>{usd(c.caps.monthly_cap_micros)}</td>
                  <td className="meta">new profile version</td>
                </tr>
                <tr>
                  <td>Content-assessment service, per day</td>
                  <td>{usd(c.caps.jev_daily_sublimit_micros)}</td>
                  <td className="meta">profile constant</td>
                </tr>
              </>
            )}
          </tbody>
        </table>
      </div>
      <div className="meta">
        Spend is reserved at worst case before every call and settled from the provider’s token counts. Nothing at run
        time can raise a cap.
      </div>
      <h2>Islands</h2>
      <div className="tw">
        <table className="wide">
          <tbody>
            <tr>
              {ISLAND_COLUMNS.map((column) => (
                <th key={column}>{column}</th>
              ))}
            </tr>
            <tr>
              <td colSpan={ISLAND_COLUMNS.length}>{UNSERVED}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div className="meta">Each island gets its own digest every day; the islands' settings are {UNSERVED}.</div>
      <h2>Per agent, this month</h2>
      <p className="meta">Settled spend by agent up to the end of {c?.day ?? "the day"}. Cost never enters selection.</p>
      <div className="tw">
        <table>
          <thead>
            <tr>
              <th>agent</th>
              <th>spent</th>
              <th>unpriced runs</th>
            </tr>
          </thead>
          <tbody>
            {agents.length === 0 && (
              <tr>
                <td colSpan={3}>No settled run.</td>
              </tr>
            )}
            {agents.map((a) => (
              <tr key={a.configuration_id}>
                <td>
                  {a.island ?? "no island"} <span className="code">{a.configuration_id.slice(0, 8)}</span>
                </td>
                <td className="num">{usd(a.priced_micros)}</td>
                <td className="num">
                  {a.unpriced_runs} ({a.unpriced_input_tokens} / {a.unpriced_output_tokens} tokens)
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <details className="adv">
        <summary>Launch profile: the fixed values these costs run under</summary>
        {PROFILE_SECTIONS.map((section) => [
          <h2 key={`${section}-h`}>{section}</h2>,
          <div className="tw" key={section}>
            <table>
              <tbody>
                <tr>
                  <th>Lever</th>
                  <th>Now</th>
                  <th>How it changes</th>
                </tr>
                <tr>
                  <td colSpan={3}>{UNSERVED}</td>
                </tr>
              </tbody>
            </table>
          </div>,
        ])}
      </details>
      <Ids rows={agents.map((a) => [`agent ${agentLabel(a.island, a.configuration_id)}`, a.configuration_id])} />
    </>
  );
}

function agentLabel(island: string | null, id: string): string {
  return `${island ?? "no island"} · ${id.slice(0, 8)}`;
}

function Bar({ label, spent, cap }: { label: string; spent: number | null; cap: number | null }) {
  const known = spent !== null && cap !== null;
  return (
    <div className="hrow">
      <span className="hl">{label}</span>
      <span className="hb">
        <i style={{ width: `${known ? percent(spent, cap).toFixed(1) : 0}%` }} />
        <u style={{ left: `${100 * ALERT}%` }} />
      </span>
      <span className="hv">{known ? `${usd(spent)} settled of ${usd(cap)}` : "none"}</span>
    </div>
  );
}
