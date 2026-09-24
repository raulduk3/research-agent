import { useState, type ReactNode } from "react";
import { Link } from "react-router";
import type { OwnerCosts, OwnerCostsTotals } from "../api/schema.gen.ts";
import { useGet } from "../api/useGet.ts";
import { Id, Show, usd } from "./common.tsx";

/** Settled spend (design-mock/costs.html): one UTC day and its month against the caps (#251). */
export function Costs() {
  const [day, setDay] = useState("");
  // An empty day lets the server choose today (UTC) rather than the browser's clock.
  const costs = useGet<OwnerCosts>("/api/v1/costs", day ? { day } : {});

  return (
    <>
      <h1>Costs</h1>
      <label>
        Day (UTC) <input type="date" value={day} onChange={(e) => setDay(e.target.value)} />
      </label>
      <Show loaded={costs}>
        {(c) => (
          <>
            <div className="meta">
              {c.day} · month {c.month} · from settlements · {c.caps.funded ? "funded" : "not funded"} · paid
              execution {c.caps.paid_execution_enabled ? "enabled" : "disabled"}
            </div>
            <div className="cards">
              <Spend title="Today" totals={c.today} cap={c.caps.daily_cap_micros} />
              <Spend title="Month to date" totals={c.month_to_date} cap={c.caps.monthly_cap_micros} />
              <div className="card">
                <b>Assessment sublimit</b>
                <div className="v">{usd(c.caps.jev_daily_sublimit_micros)}</div>
                <span className="meta">per day · profile constant</span>
              </div>
            </div>
            <h2>By island</h2>
            <TotalsTable
              head="Island"
              rows={c.by_island.items.map((r) => [r.island ?? "none", r.island ?? "none", r])}
            />
            <h2>By agent</h2>
            <TotalsTable
              head="Agent"
              rows={c.by_configuration.items.map((r) => [
                r.configuration_id,
                <Link key={r.configuration_id} to={`/agents/${r.configuration_id}`}>
                  <Id value={r.configuration_id} />
                </Link>,
                r,
              ])}
            />
          </>
        )}
      </Show>
    </>
  );
}

function Spend({ title, totals, cap }: { title: string; totals: OwnerCostsTotals; cap: number }) {
  return (
    <div className="card">
      <b>{title}</b>
      <div className="v">{usd(totals.priced_micros)}</div>
      <span className="meta">
        of {usd(cap)} cap · {totals.priced_runs} priced runs
        {totals.unpriced_runs > 0 && ` · ${totals.unpriced_runs} unpriced runs`}
      </span>
    </div>
  );
}

function TotalsTable({
  head,
  rows,
}: {
  head: string;
  rows: readonly (readonly [key: string, label: ReactNode, totals: OwnerCostsTotals])[];
}) {
  if (rows.length === 0) return <div className="meta">No settled run.</div>;
  return (
    <div className="tw">
      <table>
        <tbody>
          <tr>
            <th>{head}</th>
            <th>Priced</th>
            <th>Priced runs</th>
            <th>Unpriced runs</th>
            <th>Unpriced tokens in / out</th>
          </tr>
          {rows.map(([key, label, t]) => (
            <tr key={key}>
              <td>{label}</td>
              <td>{usd(t.priced_micros)}</td>
              <td>{t.priced_runs}</td>
              <td>{t.unpriced_runs}</td>
              <td>
                {t.unpriced_input_tokens} / {t.unpriced_output_tokens}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
