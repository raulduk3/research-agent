import { useState } from "react";
import { Link } from "react-router";
import type { Configuration, Population } from "../api/schema.gen.ts";
import { useGet } from "../api/useGet.ts";
import { Diag } from "../shell/Diag.tsx";
import { Ids, More, Show } from "./common.tsx";

const ISLANDS = ["cs", "quant-ph", "q-bio"] as const;

/**
 * The population (design-mock/agents.html): every admitted agent by island, founder first.
 * The mock's runs, forecasts, rater credit, agreement and cost columns and its note on them
 * have no /api/v1 route and are left out (docs/implementation/front-end.md).
 */
export function Agents() {
  const [cursor, setCursor] = useState<string | null>(null);
  const population = useGet<Population>("/api/v1/agents", { cursor });

  return (
    <>
      <h1>Agents</h1>
      <Show loaded={population}>
        {(p) => {
          const agents = p.configurations.items;
          return (
            <>
              <p className="lead">
                {agents.length === 0
                  ? "No agent admitted yet."
                  : `${agents.length} agents on this page. Tap one for everything about it.`}
              </p>
              {ISLANDS.map((island) => {
                const members = agents
                  .filter((c) => c.island === island)
                  .sort((a, b) => Number(b.founder) - Number(a.founder));
                if (members.length === 0) return null;
                return [
                  <h2 key={`${island}-h`}>
                    {island} <span className="meta">· {members.length} agents · founder first</span>
                  </h2>,
                  <AgentTable key={island} agents={members} />,
                ];
              })}
              <More cursor={p.configurations.next_cursor} onMore={setCursor} />
              <Ids rows={agents.map((c) => [`${c.island} · ${c.lineage_id}`, c.configuration_hash] as const)} />
            </>
          );
        }}
      </Show>
      <Diag />
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
          </tr>
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
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
