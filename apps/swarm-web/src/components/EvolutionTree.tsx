import { useEffect, useState } from "react";
import type { Agent } from "../api/types.ts";
import { GenomeCard, generationOf, parentOf } from "./GenomeCard.tsx";

const PAGE = 30;
type Node = { agent: Agent; parent: string | null; children: string[]; otherParents: string[] };
type Row = { node: Node; depth: number };

export function lineageForest(agents: readonly Agent[]): Map<string, Node> {
  const nodes = new Map<string, Node>(agents.map((agent) => [agent.id, { agent, parent: parentOf(agent), children: [], otherParents: (agent.lineage?.parents ?? []).filter((id) => id !== agent.id && id !== parentOf(agent)) }]));
  const checked = new Set<string>();
  for (const node of nodes.values()) {
    if (checked.has(node.agent.id)) continue;
    const seen = new Set([node.agent.id]);
    let parent = node.parent;
    while (parent !== null && nodes.has(parent) && !checked.has(parent)) {
      if (seen.has(parent)) {
        const cycle = nodes.get(parent);
        if (cycle) cycle.parent = null;
        break;
      }
      seen.add(parent);
      parent = nodes.get(parent)?.parent ?? null;
    }
    for (const id of seen) checked.add(id);
  }
  for (const node of nodes.values()) if (node.parent !== null) nodes.get(node.parent)?.children.push(node.agent.id);
  return nodes;
}

export function EvolutionTree({ agents, onSaved, initialId }: { agents: readonly Agent[]; onSaved?: () => void; initialId?: string }) {
  const [expanded, setExpanded] = useState(new Set<string>());
  const [selected, setSelected] = useState(initialId || agents.find((a) => a.active)?.id || agents[0]?.id || "");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [limit, setLimit] = useState(PAGE);
  useEffect(() => { if (initialId) setSelected(initialId); }, [initialId]);
  const nodes = lineageForest(agents);
  const included = new Set<string>();
  for (const node of nodes.values()) {
    if ((filter === "active" && !node.agent.active) || (filter === "archived" && node.agent.active)) continue;
    if (!`${node.agent.id} ${node.agent.prompt}`.toLowerCase().includes(query.toLowerCase())) continue;
    let next: Node | undefined = node;
    while (next && !included.has(next.agent.id)) {
      included.add(next.agent.id);
      next = next.parent === null ? undefined : nodes.get(next.parent);
    }
  }
  const rows: Row[] = [];
  const stack = [...nodes.values()].filter((n) => n.parent === null || !nodes.has(n.parent)).reverse().map((node) => ({ node, depth: 0 }));
  while (stack.length > 0) {
    const row = stack.pop();
    if (!row || !included.has(row.node.agent.id)) continue;
    if (query === "" || `${row.node.agent.id} ${row.node.agent.prompt}`.toLowerCase().includes(query.toLowerCase())) rows.push(row);
    if (expanded.has(row.node.agent.id) || query !== "" || filter !== "all") {
      for (const id of [...row.node.children].reverse()) {
        const node = nodes.get(id);
        if (node) stack.push({ node, depth: row.depth + 1 });
      }
    }
  }
  const chosen = nodes.get(selected)?.agent ?? agents.find((agent) => agent.active) ?? agents[0];
  const selectedId = chosen?.id ?? "";
  function toggle(id: string) {
    setExpanded((current) => { const next = new Set(current); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  }
  return <>
    {agents.length === 0 ? <p className="meta">This island has no agent yet.</p> : <>
      <div className="evolution-controls">
        <label>Find an agent <input value={query} onChange={(e) => { setQuery(e.target.value); setLimit(PAGE); }} type="search" /></label>
        <label>Show <select value={filter} onChange={(e) => { setFilter(e.target.value); setLimit(PAGE); }}><option value="all">all agents</option><option value="active">active agents and ancestors</option><option value="archived">archived agents and ancestors</option></select></label>
        <button className="quiet ctl" disabled={query !== "" || filter !== "all"} onClick={() => setExpanded(new Set(nodes.keys()))}>expand all</button>
        <button className="quiet ctl" disabled={query !== "" || filter !== "all"} onClick={() => setExpanded(new Set())}>collapse all</button>
      </div>
      <p className="meta">{agents.filter((a) => a.active).length} active · {agents.filter((a) => !a.active).length} archived. Archive removes an agent from the active population and keeps its history. Bring back restores it.</p>
      <div className="evolution-outline" aria-label="Agent lineage">
        {rows.slice(0, limit).map(({ node, depth }) => <div className="evolution-row" key={node.agent.id} style={{ paddingLeft: `${Math.min(depth, 8) * 1.25}rem` }}>
          {node.children.length > 0 ? <button className="quiet ctl" aria-expanded={expanded.has(node.agent.id) || query !== "" || filter !== "all"} aria-label={`Expand descendants of ${node.agent.id}`} disabled={query !== "" || filter !== "all"} onClick={() => toggle(node.agent.id)}>{expanded.has(node.agent.id) || query !== "" || filter !== "all" ? "▾" : "▸"}</button> : <span className="evolution-leaf">{depth > 0 ? "└" : "·"}</span>}
          <button className="quiet ctl" aria-pressed={selectedId === node.agent.id} onClick={() => { setSelected(node.agent.id); }}>{node.agent.id}</button>
          <span className="meta">generation {generationOf(node.agent)} · {node.agent.active ? "active" : "archived"}{query !== "" && node.parent !== null && nodes.has(node.parent) ? ` · from ${node.parent}` : ""}{query !== "" || depth > 8 ? ` · depth ${depth}` : ""}{node.parent !== null && !nodes.has(node.parent) ? ` · parent ${node.parent} unavailable` : ""}{node.otherParents.length > 0 ? ` · also from ${node.otherParents.join(", ")}` : ""}</span>
        </div>)}
      </div>
      {rows.length === 0 && <p className="meta">No agents match.</p>}
      <p className="meta">Showing {Math.min(limit, rows.length)} of {rows.length} expanded agents · {included.size} agents in matching branches.</p>
      {rows.length > limit && <button className="quiet ctl" onClick={() => setLimit(limit + PAGE)}>show more agents</button>}
      {chosen && <GenomeCard key={`${chosen.id}-${chosen.version}`} genome={chosen} {...(onSaved ? { onSaved } : {})} />}
    </>}
  </>;
}
