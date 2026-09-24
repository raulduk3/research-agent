import { useState } from "react";
import { Link } from "react-router";
import type { Configuration, Population } from "../api/schema.gen.ts";
import { useGet } from "../api/useGet.ts";
import { Ids, Lead, More, ready } from "./common.tsx";

const ISLANDS = ["cs", "quant-ph", "q-bio"] as const;

/** The mock's columns after the agent; no /api/v1 route serves them yet. */
const UNSERVED_COLUMNS = [
  "Runs (7 days)",
  "Forecasts made",
  "Rater credit this week",
  "Agreement with the prediction heads (0 to 1)",
  "Cost per run",
] as const;

/**
 * The population (design-mock/agents.html): every admitted agent by island, founder first. Each
 * island keeps its section when it has no agent or the read is refused, and the runs, forecasts,
 * rater credit, agreement and cost columns render empty (docs/implementation/front-end.md).
 */
export function Agents() {
  const [cursor, setCursor] = useState<string | null>(null);
  const population = useGet<Population>("/api/v1/agents", { cursor });
  const p = ready(population);
  const agents = p?.configurations.items ?? [];

  return (
    <>
      <h1>Agents</h1>
      <Lead reads={[population]}>
        {() =>
          agents.length === 0 ? "No agent admitted yet." : `${agents.length} agents on this page. Tap one for everything about it.`
        }
      </Lead>
      {ISLANDS.map((island) => {
        const members = agents.filter((c) => c.island === island).sort((a, b) => Number(b.founder) - Number(a.founder));
        return [
          <h2 key={`${island}-h`}>
            {island} <span className="meta">· {members.length} agents · founder first</span>
          </h2>,
          <AgentTable key={island} agents={members} />,
        ];
      })}
      <More cursor={p?.configurations.next_cursor ?? null} onMore={setCursor} />
      <div className="meta">
        Forecast skill is not shown until forecasts mature. Runs, forecasts, rater credit, agreement and cost per run
        are not served yet.
      </div>
      <Ids rows={agents.map((c) => [`${c.island} · ${c.lineage_id}`, c.configuration_hash] as const)} />
    </>
  );
}

function AgentTable({ agents }: { agents: Configuration[] }) {
  return (
    <div className="tw">
      <table className="wide">
        <tbody>
          <tr>
            <th>Agent</th>
            {UNSERVED_COLUMNS.map((column) => (
              <th key={column}>{column}</th>
            ))}
          </tr>
          {agents.length === 0 && (
            <tr>
              <td colSpan={1 + UNSERVED_COLUMNS.length}>none</td>
            </tr>
          )}
          {agents.map((c) => (
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
              {UNSERVED_COLUMNS.map((column) => (
                <td key={column}>
                  <span className="na">not served yet</span>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
