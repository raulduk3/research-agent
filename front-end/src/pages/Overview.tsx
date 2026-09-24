import { Link } from "react-router";
import type {
  Configuration,
  Health,
  OwnerCosts,
  OwnerDay,
  OwnerGenomes,
  OwnerImpact,
  OwnerReports,
  Population,
} from "../api/schema.gen.ts";
import { useGet } from "../api/useGet.ts";
import { Board, type BoardLane } from "../graphics/Board.tsx";
import { Card, Cards } from "../graphics/Cards.tsx";
import { type TileRow, Tiles } from "../graphics/Tiles.tsx";
import { ISLANDS } from "./Agents.tsx";
import { Ids, Lead, ready, UNSERVED, usd } from "./common.tsx";

const state = (s: Health["state"]) => s.replace("_", " ");

type DayRun = OwnerDay["runs"]["items"][number];

/** An instant as minutes after midnight UTC. */
const minute = (instant: string) => Math.floor((Date.parse(instant) % 86_400_000) / 60_000);

/** The agents in the tiles' order: islands in order, founders first. */
function ordered(agents: readonly Configuration[]): Configuration[] {
  return ISLANDS.flatMap((island) =>
    agents.filter((c) => c.island === island).sort((a, b) => Number(b.founder) - Number(a.founder)),
  );
}

/** Each agent's hue, stepping by 30 degrees over the tiles' order. */
function hues(agents: readonly Configuration[]): Map<string, number> {
  return new Map(ordered(agents).map((c, i) => [c.configuration_id, (i * 30) % 360]));
}

/**
 * The agents as the mock's tiles: one row per island, founder first, each noting its runs on the
 * day read and the void ones, or "not served yet" without that read.
 */
function tileRows(agents: readonly Configuration[], runs: readonly DayRun[] | null): TileRow[] {
  const hue = hues(agents);
  const note = (c: Configuration) => {
    const own = runs?.filter((r) => r.configuration_id === c.configuration_id) ?? [];
    const voided = own.filter((r) => r.ending === "void").length;
    const count = runs === null ? `runs ${UNSERVED}` : `${own.length} runs${voided ? ` · ${voided} void` : ""}`;
    return c.founder ? `founder · ${count}` : count;
  };
  return ISLANDS.map((island) => ({ island, members: ordered(agents).filter((c) => c.island === island) }))
    .filter((row) => row.members.length > 0)
    .map(({ island, members }) => ({
      island,
      tiles: members.map((c) => ({
        key: c.configuration_id,
        name: <Link to={`/agents/${c.configuration_id}`}>{c.lineage_id}</Link>,
        hue: hue.get(c.configuration_id) ?? 0,
        note: note(c),
      })),
    }));
}

/**
 * The day's runs as board lanes. No worker container is stored, so each lane is an island in the
 * islands' order, with runs whose agent has no population record last. A run spans its creation
 * to its end instant (nothing while it has none) in its agent's hue; a void run takes the mock's
 * no-answer colour.
 */
function lanes(runs: readonly DayRun[], agents: readonly Configuration[]): BoardLane[] {
  const hue = hues(agents);
  return [...ISLANDS, null]
    .map((island) => ({
      name: island ?? "no population record",
      runs: runs
        .filter((r) => r.island === island)
        .map((r) => ({
          start: minute(r.created_at),
          end: minute(r.ended_at ?? r.created_at),
          hue: r.ending === "void" ? null : (hue.get(r.configuration_id) ?? 0),
          title: `${r.lineage_id ?? r.configuration_id} · ${r.paper_id} · ${r.ending ?? "open"} · ${r.run_id}`,
        })),
    }))
    .filter((lane) => lane.runs.length > 0);
}

/** The latest ISO week holding a stored report or rating, with its report and impact rows summed over islands. */
function thisWeek(reports: OwnerReports | null, impact: OwnerImpact | null) {
  const weeks = [...(reports?.reports.items ?? []), ...(impact?.impact.items ?? [])].map((row) => row.iso_week);
  const week = weeks.sort().at(-1);
  if (week === undefined) return null;
  const sum = <T,>(rows: readonly T[], field: (row: T) => number) => rows.reduce((total, row) => total + field(row), 0);
  const r = reports?.reports.items.filter((row) => row.iso_week === week) ?? [];
  const i = impact?.impact.items.filter((row) => row.iso_week === week) ?? [];
  return {
    week,
    digests: sum(r, (row) => row.digests),
    entries: sum(r, (row) => row.entries),
    ratings: sum(r, (row) => row.ratings),
    credits: sum(r, (row) => row.credits),
    likes: sum(i, (row) => row.likes),
    dislikes: sum(i, (row) => row.dislikes),
    skips: sum(i, (row) => row.skips),
  };
}

/**
 * Owner home (design-mock/overview.html), every section in the mock's order. The health monitor
 * and the costs fill what they can, the agent tiles draw the population with each agent's runs on
 * the day from `/api/v1/day`, which also fills the run board and the runs and digests cards. The
 * this-week card holds the latest week's stored counts from `/api/v1/reports` and
 * `/api/v1/impact`; the identifier fold lists each genome from `/api/v1/genomes`. The top papers
 * and the week's verdict are derived and render empty.
 */
export function Overview() {
  const health = useGet<Health>("/api/v1/health");
  const costs = useGet<OwnerCosts>("/api/v1/costs");
  const population = useGet<Population>("/api/v1/agents");
  const dayRead = useGet<OwnerDay>("/api/v1/day");
  const reportsRead = useGet<OwnerReports>("/api/v1/reports");
  const impactRead = useGet<OwnerImpact>("/api/v1/impact");
  const genomesRead = useGet<OwnerGenomes>("/api/v1/genomes");
  const h = ready(health);
  const c = ready(costs);
  const day = ready(dayRead);
  const agents = ready(population)?.configurations.items ?? [];
  const open = h?.checks.filter((check) => check.state !== "healthy") ?? [];
  const runs = day?.runs.items ?? [];
  const voided = runs.filter((r) => r.ending === "void").length;
  const submitted = runs.filter((r) => r.ending === "submitted").length;
  const digests = day?.digests.items ?? [];
  const week = thisWeek(ready(reportsRead), ready(impactRead));

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
      <Board
        lanes={day ? lanes(runs, agents) : []}
        label={day ? `${day.day}: ${runs.length} runs by island` : `today's runs: ${UNSERVED}`}
      />
      <Tiles
        rows={tileRows(agents, day ? runs : null)}
        empty={ready(population) ? "No agent admitted yet." : "Agent tiles: none read."}
      />
      <div className="meta">The worker containers across today, one block per run in its agent's color.</div>
      <Cards>
        <Card
          title="Runs"
          value={day ? `${submitted} of ${runs.length}` : "none"}
          meta={
            day
              ? `${day.day} · ${voided} void, ${runs.length - submitted - voided} not ended`
              : `today's batch · ${UNSERVED}`
          }
        />
        <Card
          title="Digests"
          value={day ? `${digests.length} built` : "none"}
          meta={
            day
              ? digests.map((d) => `${d.island}: ${d.rated_entries} of ${d.entries} rated`).join(" · ") || "none built"
              : UNSERVED
          }
        />
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
          value={week ? `${week.ratings} ratings` : "none"}
          meta={
            <>
              {week
                ? `${week.week} · ${week.digests} digests, ${week.entries} entries · ` +
                  `${week.likes} liked, ${week.dislikes} disliked, ${week.skips} skipped · ${week.credits} credits · ` +
                  `verdict ${UNSERVED}`
                : UNSERVED}{" "}
              · <Link to="/reports">report</Link>
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
      <Ids
        rows={[
          ["costs day", c?.day],
          ["runs day", day?.day],
          ...(ready(genomesRead)?.genomes.items.map((g) => [`${g.island} ${g.lineage_id}`, g.configuration_hash] as const) ??
            []),
        ]}
      />
    </>
  );
}
