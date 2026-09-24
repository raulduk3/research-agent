import { useState } from "react";
import { Link } from "react-router";
import type { Configuration, OwnerGenomes, Population } from "../api/schema.gen.ts";
import { useGet } from "../api/useGet.ts";
import { Ids, Lead, More, ready, UNSERVED, usd } from "./common.tsx";

export const ISLANDS = ["cs", "quant-ph", "q-bio"] as const;

type Counts = OwnerGenomes["genomes"]["items"][number];

/**
 * The population (design-mock/agents.html): every admitted agent by island, founder first. Each
 * island keeps its section when it has no agent or the read is refused. The runs, forecasts, rater
 * credit and cost columns come from /api/v1/genomes; agreement is not stored and renders empty
 * (docs/implementation/front-end.md).
 */
export function Agents() {
  const [cursor, setCursor] = useState<string | null>(null);
  const population = useGet<Population>("/api/v1/agents", { cursor });
  const p = ready(population);
  const agents = p?.configurations.items ?? [];
  const genomes = useGet<OwnerGenomes>("/api/v1/genomes");
  const counts = new Map((ready(genomes)?.genomes.items ?? []).map((g) => [g.configuration_id, g] as const));

  return (
    <>
      <h1>Agents</h1>
      <Lead reads={[population]}>
        {() =>
          agents.length === 0
            ? "No agent admitted yet."
            : `${agents.length} agents on this page. Tap one for everything about it.`
        }
      </Lead>
      {ISLANDS.map((island) => {
        const members = agents.filter((c) => c.island === island).sort((a, b) => Number(b.founder) - Number(a.founder));
        return [
          <h2 key={`${island}-h`}>
            {island} <span className="meta">· {members.length} agents · founder first</span>
          </h2>,
          <AgentTable key={island} agents={members} counts={counts} />,
        ];
      })}
      <More cursor={p?.configurations.next_cursor ?? null} onMore={setCursor} />
      <div className="meta">
        Forecast skill is not shown until forecasts mature. Runs and forecasts count every stored run; rater credit is
        the agent's preference credits and its share of them; cost per run is settled cost over priced runs. Agreement
        is not served yet.
      </div>
      <Ids rows={agents.map((c) => [`${c.island} · ${c.lineage_id}`, c.configuration_hash] as const)} />
    </>
  );
}

function AgentTable({ agents, counts }: { agents: Configuration[]; counts: ReadonlyMap<string, Counts> }) {
  return (
    <div className="tw">
      <table className="wide">
        <tbody>
          <tr>
            <th>Agent</th>
            <th>Runs</th>
            <th>Forecasts made</th>
            <th>Rater credit</th>
            <th>Agreement with the prediction heads (0 to 1)</th>
            <th>Cost per run</th>
          </tr>
          {agents.length === 0 && (
            <tr>
              <td colSpan={6}>none</td>
            </tr>
          )}
          {agents.map((c) => {
            const g = counts.get(c.configuration_id);
            return (
              <tr key={c.configuration_id}>
                <td>
                  <Link to={`/agents/${c.configuration_id}`}>
                    <b>
                      {c.island} · {c.lineage_id}
                    </b>{" "}
                    {c.founder && <span className="code">founder</span>}
                    {c.founder && " "}
                    <span className="code" title={`config ${c.configuration_hash}`}>
                      {c.configuration_hash.slice(0, 12)}
                    </span>
                  </Link>
                </td>
                <Count value={g && `${g.runs}${g.void_runs > 0 ? ` · ${g.void_runs} void` : ""}`} />
                <Count value={g && String(g.forecasts)} />
                <Count value={g && `${g.credits} · ${Math.round(g.credit_share * 100)}%`} />
                <Count value={undefined} />
                <Count value={g && (g.priced_runs > 0 ? usd(g.cost_micros / g.priced_runs) : "no priced run")} />
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** One served count, or "not served yet" when the genomes read is missing or refused. */
function Count({ value }: { value: string | undefined }) {
  return <td>{value ?? <span className="na">{UNSERVED}</span>}</td>;
}
