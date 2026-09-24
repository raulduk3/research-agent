import { Link } from "react-router";
import type { Health, OwnerCosts } from "../api/schema.gen.ts";
import { useGet } from "../api/useGet.ts";
import { Diag } from "../shell/Diag.tsx";
import { Show, usd } from "./common.tsx";

const state = (s: Health["state"]) => s.replace("_", " ");

/**
 * Owner home (design-mock/overview.html). The mock's top papers, run board, agent tiles, run,
 * digest and weekly cards and identifier fold have no /api/v1 route and are left out
 * (docs/implementation/front-end.md); the rest reads the health monitor and the costs.
 */
export function Overview() {
  const health = useGet<Health>("/api/v1/health");
  const costs = useGet<OwnerCosts>("/api/v1/costs");

  return (
    <>
      <h1>What the agents are thinking</h1>
      <Show loaded={health}>
        {(h) => <p className="lead">{h.checked_at.slice(0, 10)}, as of the last health check.</p>}
      </Show>
      <Show loaded={costs}>
        {(c) => (
          <div className="cards">
            <div className="card">
              <b>Spend</b>
              <div className="v">{usd(c.today.priced_micros)}</div>
              <span className="meta">
                {c.day} · {c.today.priced_runs} priced runs, {c.today.unpriced_runs} unpriced ·{" "}
                {usd(c.month_to_date.priced_micros).slice(4)} of {usd(c.caps.monthly_cap_micros).slice(4)} this month
              </span>
            </div>
          </div>
        )}
      </Show>
      <h2>Needs attention</h2>
      <div className="tw">
        <table>
          <tbody>
            <tr>
              <th>What</th>
              <th>State</th>
            </tr>
            <tr>
              <td>Alerts</td>
              <td>
                <Show loaded={health}>
                  {(h) => {
                    const open = h.checks.filter((c) => c.state !== "healthy");
                    return open.length === 0 ? "none" : open.map((c) => `${c.name}: ${state(c.state)}`).join(" · ");
                  }}
                </Show>
              </td>
            </tr>
            <tr>
              <td>Spend</td>
              <td>
                <Show loaded={costs}>
                  {(c) => `${usd(c.today.priced_micros)} of ${usd(c.caps.daily_cap_micros)} today · `}
                </Show>
                <Link to="/costs">costs</Link>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div className="meta">
        The kill switch lives outside the app. Every lever is on <Link to="/costs">costs</Link>.
      </div>
      <Diag />
    </>
  );
}
