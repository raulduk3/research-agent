import { Link } from "react-router";
import type { Health, OwnerCosts } from "../api/schema.gen.ts";
import { useGet } from "../api/useGet.ts";
import { Ids, Lead, ready, usd } from "./common.tsx";

const state = (s: Health["state"]) => s.replace("_", " ");

/** What a section says when no /api/v1 route fills it (docs/implementation/front-end.md). */
const UNSERVED = "not served yet";

/**
 * Owner home (design-mock/overview.html), every section in the mock's order. The health monitor
 * and the costs fill what they can; the top papers, the run board, the agent tiles and the run,
 * digest and weekly cards have no /api/v1 route and render empty.
 */
export function Overview() {
  const health = useGet<Health>("/api/v1/health");
  const costs = useGet<OwnerCosts>("/api/v1/costs");
  const h = ready(health);
  const c = ready(costs);
  const open = h?.checks.filter((check) => check.state !== "healthy") ?? [];

  return (
    <>
      <h1>What the agents are thinking</h1>
      <Lead reads={[health, costs]}>{() => `${h?.checked_at.slice(0, 10)}, as of the last health check.`}</Lead>
      <div className="meta">The papers the agents back most, from today's runs, and how closely the agents agree.</div>
      <div className="tw">
        <table>
          <tbody>
            <tr>
              <th>Paper</th>
              <th>Chance of five citations in a year (0 to 1)</th>
              <th>Agreement</th>
            </tr>
            <tr>
              <td colSpan={3}>{UNSERVED}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div className="meta">
        Every paper of the day, animated: <Link to="/swarm">the swarm</Link>.
      </div>
      <h2>What's new</h2>
      <div className="board" role="img" aria-label={`today's runs: ${UNSERVED}`}>
        <div className="axis">
          <span className="ln" />
          <div>
            <span>00</span>
            <span>06</span>
            <span>12</span>
            <span>18</span>
            <span>24</span>
          </div>
        </div>
      </div>
      <div className="tiles">Agent tiles: {UNSERVED}.</div>
      <div className="meta">The worker containers across today, one block per run in its agent's color.</div>
      <div className="cards">
        <div className="card">
          <b>Runs</b>
          <div className="v">none</div>
          <span className="meta">today's batch · {UNSERVED}</span>
        </div>
        <div className="card">
          <b>Digests</b>
          <div className="v">none</div>
          <span className="meta">{UNSERVED}</span>
        </div>
        <div className="card">
          <b>Spend</b>
          <div className="v">{c ? usd(c.today.priced_micros) : "none"}</div>
          <span className="meta">
            {c
              ? `${c.day} · ${c.today.priced_runs} priced runs, ${c.today.unpriced_runs} unpriced · ` +
                `${usd(c.month_to_date.priced_micros).slice(4)} of ${usd(c.caps.monthly_cap_micros).slice(4)} this month`
              : "no costs read"}
          </span>
        </div>
        <div className="card">
          <b>This week</b>
          <div className="v">none</div>
          <span className="meta">
            {UNSERVED} · <Link to="/reports">report</Link>
          </span>
        </div>
      </div>
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
                {h === null
                  ? "none read"
                  : open.length === 0
                    ? "none"
                    : open.map((check) => `${check.name}: ${state(check.state)}`).join(" · ")}
              </td>
            </tr>
            <tr>
              <td>Spend</td>
              <td>
                {c ? `${usd(c.today.priced_micros)} of ${usd(c.caps.daily_cap_micros)} today · ` : "none read · "}
                <Link to="/costs">costs</Link>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div className="meta">
        The kill switch lives outside the app. Every lever is on <Link to="/costs">costs</Link>.
      </div>
      <Ids rows={[["costs day", c?.day]]} />
    </>
  );
}
