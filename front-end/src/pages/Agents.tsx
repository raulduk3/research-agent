import { useState } from "react";
import { Link } from "react-router";
import type { Configuration, Population } from "../api/schema.gen.ts";
import { useGet } from "../api/useGet.ts";
import { Id, More, Show, when } from "./common.tsx";

const ISLANDS = ["cs", "quant-ph", "q-bio"] as const;

/** The population (design-mock/agents.html): every admitted genome by island, founders first. */
export function Agents() {
  const [cursor, setCursor] = useState<string | null>(null);
  const population = useGet<Population>("/api/v1/agents", { cursor });

  return (
    <>
      <h1>Agents</h1>
      <Show loaded={population}>
        {(p) => (
          <>
            {ISLANDS.map((island) => {
              const agents = p.configurations.items
                .filter((c) => c.island === island)
                .sort((a, b) => Number(b.founder) - Number(a.founder));
              if (agents.length === 0) return null;
              return (
                <section key={island}>
                  <h2>
                    {island} <span className="meta">· {agents.length} agents · founder first</span>
                  </h2>
                  <AgentTable agents={agents} />
                </section>
              );
            })}
            {p.configurations.items.length === 0 && <div className="meta">No agent admitted yet.</div>}
            <More cursor={p.configurations.next_cursor} onMore={setCursor} />
          </>
        )}
      </Show>
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
            <th>Admitted</th>
            <th>Disposition</th>
            <th>Archived skill</th>
            <th>Resolved claims</th>
          </tr>
          {agents.map((c) => (
            <tr key={c.configuration_id}>
              <td>
                <Link to={`/agents/${c.configuration_id}`}>{c.lineage_id}</Link>{" "}
                {c.founder && <span className="code">founder</span>} <Id value={c.configuration_hash} />
              </td>
              <td>{when(c.admitted_at)}</td>
              <td>{c.admission.disposition}</td>
              <td className="num">{c.archive?.skill ?? <span className="na">not yet</span>}</td>
              <td className="num">{c.archive?.resolved_claim_count ?? <span className="na">not yet</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
