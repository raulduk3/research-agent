import { useState } from "react";
import type { OwnerCosts } from "../api/schema.gen.ts";
import { useGet } from "../api/useGet.ts";
import { Diag } from "../shell/Diag.tsx";
import { Ids, Show, usd } from "./common.tsx";

/** The alert tick on each cap bar: spending at 80% of either cap raises an alert (SDD). */
const ALERT = 0.8;

const percent = (part: number, whole: number) => (whole > 0 ? Math.min(100, (100 * part) / whole) : 0);

/** Settled spend (design-mock/costs.html): one UTC day and its month against the caps (#251). */
export function Costs() {
  const [day, setDay] = useState("");
  // An empty day lets the server choose today (UTC) rather than the browser's clock.
  const costs = useGet<OwnerCosts>("/api/v1/costs", day ? { day } : {});

  return (
    <>
      <h1>Costs</h1>
      <p className="lead">
        What the swarm spends against the caps the launch profile fixes. Owner only: a rater has nothing to
        configure, so there is no settings page. Numbers are settled spend; a run without a price is counted by
        its tokens and never given one.
      </p>
      <Show loaded={costs}>
        {(c) => {
          const agents = c.by_configuration.items;
          const perRun = agents.map((a) => (a.priced_runs > 0 ? a.priced_micros / a.priced_runs : 0));
          const widest = Math.max(0, ...perRun);
          return (
            <>
              <div className="sec">
                <h2>Today and this month</h2>
                <span>
                  caps from the launch profile · UTC days ·{" "}
                  <input type="date" aria-label="Day (UTC)" value={day} onChange={(e) => setDay(e.target.value)} />
                </span>
              </div>
              <div className="cards">
                <div className="card">
                  <b>{c.day}</b>
                  {usd(c.today.priced_micros)}{" "}
                  <span className="meta">
                    of {usd(c.caps.daily_cap_micros)} · {Math.round(percent(c.today.priced_micros, c.caps.daily_cap_micros))}%
                  </span>
                </div>
                <div className="card">
                  <b>{c.month}</b>
                  {usd(c.month_to_date.priced_micros)}{" "}
                  <span className="meta">
                    of {usd(c.caps.monthly_cap_micros)} · shared by the islands, per agent below
                  </span>
                </div>
                <div className="card">
                  <b>assessment sublimit</b>
                  {usd(c.caps.jev_daily_sublimit_micros)} <span className="meta">a day · profile constant</span>
                </div>
                <div className="card">
                  <b>paid execution</b>
                  {c.caps.paid_execution_enabled ? "enabled" : "disabled"}{" "}
                  <span className="meta">{c.caps.funded ? "funded" : "not funded"}</span>
                </div>
              </div>
              <p className="meta">
                source: <b>settlements</b> · micro-dollars, shown to the cent
                {c.today.unpriced_runs > 0 && ` · ${c.today.unpriced_runs} unpriced runs today`}
              </p>
              <h2>Spending</h2>
              <h3>Against each cap</h3>
              <div className="graph">
                <div className="hbars" role="img" aria-label="spend against each cap">
                  <Bar
                    label={`${c.day}, everything`}
                    spent={c.today.priced_micros}
                    cap={c.caps.daily_cap_micros}
                  />
                  <Bar label={`${c.month}, everything`} spent={c.month_to_date.priced_micros} cap={c.caps.monthly_cap_micros} />
                </div>
                <div className="cap">
                  A call is refused when settled charges plus outstanding reservations would pass any cap; the tick on
                  each bar is the alert at 80%. Caps change only with a new profile version.
                </div>
              </div>
              <h3>Cost per run, by agent</h3>
              <div className="graph">
                <div className="hbars" role="img" aria-label="measured model cost per run by agent">
                  {agents.map((a, i) => (
                    <div className="hrow" key={a.configuration_id}>
                      <span className="hl">{agentLabel(a.island, a.configuration_id)}</span>
                      <span className="hb">
                        <i style={{ width: `${percent(perRun[i] ?? 0, widest).toFixed(1)}%` }} />
                      </span>
                      <span className="hv">
                        {a.priced_runs > 0 ? `USD ${((perRun[i] ?? 0) / 1_000_000).toFixed(4)} a run` : "no priced run"} ·{" "}
                        {a.priced_runs} priced runs in {c.month}
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
                  </tbody>
                </table>
              </div>
              <div className="meta">
                Spend is reserved at worst case before every call and settled from the provider’s token counts. Nothing
                at run time can raise a cap.
              </div>
              <h2>Per agent, this month</h2>
              <p className="meta">Settled spend by agent up to the end of {c.day}. Cost never enters selection.</p>
              {agents.length === 0 ? (
                <div className="meta">No settled run.</div>
              ) : (
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
              )}
              <Ids rows={agents.map((a) => [`agent ${agentLabel(a.island, a.configuration_id)}`, a.configuration_id])} />
            </>
          );
        }}
      </Show>
      <Diag />
    </>
  );
}

function agentLabel(island: string | null, id: string): string {
  return `${island ?? "no island"} · ${id.slice(0, 8)}`;
}

function Bar({ label, spent, cap }: { label: string; spent: number; cap: number }) {
  return (
    <div className="hrow">
      <span className="hl">{label}</span>
      <span className="hb">
        <i style={{ width: `${percent(spent, cap).toFixed(1)}%` }} />
        <u style={{ left: `${100 * ALERT}%` }} />
      </span>
      <span className="hv">
        {usd(spent)} settled of {usd(cap)}
      </span>
    </div>
  );
}
