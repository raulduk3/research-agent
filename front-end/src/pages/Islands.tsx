import { Link } from "react-router";
import type { OwnerIslands } from "../api/schema.gen.ts";
import { useGet } from "../api/useGet.ts";
import { ISLANDS } from "./Agents.tsx";
import { Ids, Lead, ready, UNSERVED, when } from "./common.tsx";

type Counts = OwnerIslands["islands"]["items"][number];

/**
 * The islands index (design-mock/islands.html), one row per island from /api/v1/islands: its
 * stored agents, founders and lineages, its runs and its latest run. The papers an island reads,
 * its rater, budget share and selection proxy are the launch profile's, not a stored record, and
 * render "not served yet" (docs/implementation/front-end.md).
 */
export function Islands() {
  const islands = useGet<OwnerIslands>("/api/v1/islands");
  const items = ready(islands)?.islands.items;
  const counts = new Map((items ?? []).map((i) => [i.island, i] as const));
  const names = [...ISLANDS, ...(items ?? []).map((i) => i.island).filter((i) => !ISLANDS.includes(i))];

  return (
    <>
      <h1>Islands</h1>
      <Lead reads={[islands]}>
        {() =>
          `${names.length} islands, one per field. Each has its own agents and its own digest. Tap one for its agents and runs.`
        }
      </Lead>
      <div className="tw">
        <table className="wide">
          <tbody>
            <tr>
              <th>Island</th>
              <th>Papers from</th>
              <th>Rated by</th>
              <th>Agents</th>
              <th>Runs</th>
              <th>Budget</th>
              <th>Selection proxy</th>
              <th>Latest run</th>
            </tr>
            {items && names.map((island) => <IslandRow key={island} island={island} counts={counts.get(island)} />)}
          </tbody>
        </table>
      </div>
      <Ids rows={[]} />
    </>
  );
}

function IslandRow({ island, counts }: { island: string; counts: Counts | undefined }) {
  const na = <span className="na">{UNSERVED}</span>;
  return (
    <tr>
      <td>
        <Link to={`/islands/${island}`}>
          <b>{island}</b>
        </Link>
      </td>
      <td>{na}</td>
      <td>{na}</td>
      <td>
        {counts
          ? `${counts.genomes} agents · ${counts.founders} founders · ${counts.lineages} lineages`
          : "no agent stored"}
      </td>
      <td>{counts ? `${counts.runs} runs` : "0 runs"}</td>
      <td>{na}</td>
      <td>{na}</td>
      <td>{counts ? when(counts.last_run_at) : "none"}</td>
    </tr>
  );
}
