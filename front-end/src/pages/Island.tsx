import { Link, useParams } from "react-router";
import type { OwnerIsland } from "../api/schema.gen.ts";
import { useGet } from "../api/useGet.ts";
import { Card, Cards } from "../graphics/Cards.tsx";
import { ChanceBar } from "../graphics/ChanceBar.tsx";
import { EmptyCard, Ids, Lead, ready, UNSERVED, usd, when } from "./common.tsx";

type Genome = OwnerIsland["genomes"]["items"][number];

/**
 * One island (design-mock/island.html) from /api/v1/islands/{island}: its stored agents, founders
 * first, with their runs, void runs and settled cost. The island's paper stream, rater, budget share
 * and selection state are the launch profile's, and today's papers, digest, accept rate and the
 * recent weeks are not in that read; they render "not served yet". The replay has no route until
 * #208 is decided, so its controls are there but disabled (docs/implementation/front-end.md).
 */
export function Island() {
  const { island = "" } = useParams();
  const read = useGet<OwnerIsland>(`/api/v1/islands/${encodeURIComponent(island)}`);
  const genomes = ready(read)?.genomes.items;
  const runs = genomes?.reduce((n, g) => n + g.runs, 0);
  const voids = genomes?.reduce((n, g) => n + g.void_runs, 0);
  const priced = genomes?.reduce((n, g) => n + g.priced_runs, 0);
  const cost = genomes?.reduce((n, g) => n + g.cost_micros, 0);
  const founders = genomes?.filter((g) => g.founder).length;

  return (
    <>
      <div className="meta">
        <Link to="/islands">← islands</Link>
      </div>
      <h1>{island}</h1>
      <Lead reads={[read]}>
        {() =>
          `${genomes?.length ?? 0} agents stored, ${founders ?? 0} of them founders. Papers from, rater and budget share ${UNSERVED}.`
        }
      </Lead>
      <Cards>
        <Card
          title="Runs"
          value={runs === undefined ? "none" : `${runs} runs`}
          meta={voids === undefined ? UNSERVED : `all-time · ${voids} void`}
        />
        <EmptyCard title="Digest today" />
        <Card
          title="Accept rate this week so far"
          value={<ChanceBar p={null} none={UNSERVED} />}
          meta={
            <>
              on agents’ picks · controls <ChanceBar p={null} none={UNSERVED} />
            </>
          }
        />
        <Card
          title="Settled cost"
          value={cost === undefined ? "none" : usd(cost)}
          meta={priced === undefined ? UNSERVED : `all-time · over ${priced} priced runs`}
        />
      </Cards>

      <h2>Today, replayed</h2>
      <div className="meta">The island’s day, step by step: the replay follows the record.</div>
      <div className="ctl">
        <button type="button" disabled>
          play
        </button>{" "}
        <span className="meta">replay {UNSERVED}</span>
        <input type="range" min="0" max="0" defaultValue="0" step="1" aria-label="timeline" disabled />
      </div>
      <canvas aria-label="island replay, not served yet" style={{ width: "100%", display: "block", border: 0 }} />
      <div className="meta">Replay {UNSERVED} (#208).</div>
      <div className="box">
        <span className="meta">Papers and runs appear here once the replay is served.</span>
      </div>
      <details className="adv">
        <summary>Advanced: one event at a time</summary>
        <div className="ctl">
          <button type="button" disabled>
            −1 event
          </button>
          <button type="button" disabled>
            +1 event
          </button>
        </div>
      </details>

      <div className="explore">
        <Link to="/swarm">the whole swarm →</Link>
        <Link to="/reports">its reports →</Link>
        <Link to="/runs">the runs →</Link>
        <Link to="/">owner home →</Link>
      </div>

      <h2>
        Agents <span className="meta">· founder first</span>
      </h2>
      <div className="tw">
        <table className="wide">
          <tbody>
            <tr>
              <th>Agent</th>
              <th>Runs</th>
              <th>Forecasts made</th>
              <th>Rater credit this week</th>
              <th>Agreement with the prediction heads (0 to 1)</th>
              <th>Cost per run</th>
              <th>Latest run</th>
            </tr>
            {genomes?.length === 0 && (
              <tr>
                <td colSpan={7}>no agent stored</td>
              </tr>
            )}
            {genomes?.map((g) => (
              <AgentRow key={g.configuration_id} island={island} genome={g} />
            ))}
          </tbody>
        </table>
      </div>

      <h2>Selection</h2>
      <div className="box">Selection state {UNSERVED}: the control period and ranking are the launch profile’s.</div>

      <h2>Recent weeks</h2>
      <div className="tw">
        <table>
          <tbody>
            <tr>
              <th>Week</th>
              <th>Runs</th>
              <th>Accept rate, agents’ picks vs controls</th>
              <th>Selection</th>
              <th />
            </tr>
            <tr>
              <td colSpan={5}>
                <span className="na">{UNSERVED}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <Ids rows={(genomes ?? []).map((g) => [`${g.lineage_id} configuration`, g.configuration_hash] as const)} />
    </>
  );
}

function AgentRow({ island, genome: g }: { island: string; genome: Genome }) {
  const na = <span className="na">{UNSERVED}</span>;
  return (
    <tr>
      <td>
        <Link to={`/agents/${g.configuration_id}`}>
          <b>
            {island} · {g.lineage_id}
          </b>
          {g.founder && (
            <>
              {" "}
              <span className="code">founder</span>
            </>
          )}
        </Link>
      </td>
      <td>{`${g.runs}${g.void_runs > 0 ? ` · ${g.void_runs} void` : ""}`}</td>
      <td>{na}</td>
      <td>{na}</td>
      <td>{na}</td>
      <td>{g.priced_runs > 0 ? usd(g.cost_micros / g.priced_runs) : "no priced run"}</td>
      <td>{when(g.last_run_at)}</td>
    </tr>
  );
}
