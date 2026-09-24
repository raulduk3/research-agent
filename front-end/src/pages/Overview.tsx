import { Link } from "react-router";
import type { Configuration, Health, OwnerCosts, Population } from "../api/schema.gen.ts";
import { useGet } from "../api/useGet.ts";
import { Board } from "../graphics/Board.tsx";
import { Card, Cards } from "../graphics/Cards.tsx";
import { type TileRow, Tiles } from "../graphics/Tiles.tsx";
import { ISLANDS } from "./Agents.tsx";
import { Ids, Lead, ready, UNSERVED, usd } from "./common.tsx";

const state = (s: Health["state"]) => s.replace("_", " ");

/** The agents as the mock's tiles: one row per island, founder first, hues stepping by 30 degrees. */
function tileRows(agents: readonly Configuration[]): TileRow[] {
  let hue = 0;
  return ISLANDS.map((island) => ({
    island,
    members: agents.filter((c) => c.island === island).sort((a, b) => Number(b.founder) - Number(a.founder)),
  }))
    .filter((row) => row.members.length > 0)
    .map(({ island, members }) => ({
      island,
      tiles: members.map((c) => ({
        key: c.configuration_id,
        name: <Link to={`/agents/${c.configuration_id}`}>{c.lineage_id}</Link>,
        hue: (hue++ * 30) % 360,
        note: c.founder ? `founder · runs ${UNSERVED}` : `runs ${UNSERVED}`,
      })),
    }));
}

/**
 * Owner home (design-mock/overview.html), every section in the mock's order. The health monitor
 * and the costs fill what they can and the agent tiles draw the population; the top papers, the
 * run board and the run, digest and weekly cards have no /api/v1 route and render empty.
 */
export function Overview() {
  const health = useGet<Health>("/api/v1/health");
  const costs = useGet<OwnerCosts>("/api/v1/costs");
  const population = useGet<Population>("/api/v1/agents");
  const h = ready(health);
  const c = ready(costs);
  const agents = ready(population)?.configurations.items ?? [];
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
      <Board lanes={[]} label={`today's runs: ${UNSERVED}`} />
      <Tiles rows={tileRows(agents)} empty={ready(population) ? "No agent admitted yet." : "Agent tiles: none read."} />
      <div className="meta">The worker containers across today, one block per run in its agent's color.</div>
      <Cards>
        <Card title="Runs" value="none" meta={`today's batch · ${UNSERVED}`} />
        <Card title="Digests" value="none" meta={UNSERVED} />
        <Card
          title="Spend"
          value={c ? usd(c.today.priced_micros) : "none"}
          meta={
            c
              ? `${c.day} · ${c.today.priced_runs} priced runs, ${c.today.unpriced_runs} unpriced · ` +
                `${usd(c.month_to_date.priced_micros).slice(4)} of ${usd(c.caps.monthly_cap_micros).slice(4)} this month`
              : "no costs read"
          }
        />
        <Card
          title="This week"
          value="none"
          meta={
            <>
              {UNSERVED} · <Link to="/reports">report</Link>
            </>
          }
        />
      </Cards>
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
