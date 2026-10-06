import { useEffect } from "react";
import { Link, useLocation, useParams } from "react-router";
import { useApi } from "../api/context.tsx";
import type { IslandView } from "../api/types.ts";
import { useGet } from "../api/useGet.ts";
import { Settled, decoded, when } from "../common.tsx";
import { EvolutionSwitches } from "../components/EvolutionSwitches.tsx";
import { LetGo } from "../components/LetGo.tsx";
import { EvolutionTree } from "../components/EvolutionTree.tsx";
import { MathText } from "../components/MathText.tsx";
import { PaperBranches } from "../components/Tree.tsx";
import { MONTH_TARGET_MICROS, cost, share, usdRound } from "../money.ts";

/** The island's part of the budget: the share the server sets, else its cost over the month's target. */
function budgetShare(view: IslandView): { text: string; basis: string } {
  if (typeof view.budget_share === "number") return { text: share(view.budget_share), basis: "of the month's budget is this island's" };
  const spent = view.month_cost_micros ?? view.cost_micros;
  if (typeof spent !== "number") return { text: "—", basis: "not reported" };
  return { text: share(spent / MONTH_TARGET_MICROS), basis: `its cost over the ${usdRound(MONTH_TARGET_MICROS)} month` };
}

export function IslandPage() {
  const { island = "" } = useParams();
  const api = useApi();
  const read = useGet<IslandView>(`/api/v1/islands/${encodeURIComponent(island)}`);
  const { hash } = useLocation();
  const ready = read.state === "ready";
  // A link to one agent lands on it once the island has been read.
  useEffect(() => {
    if (ready && hash !== "") document.getElementById(decoded(hash.slice(1)))?.scrollIntoView?.();
  }, [ready, hash]);
  return (
    <Settled read={read} what="The island">
      {(view) => {
        // A session reads every island and edits only its own.
        const mine = api.session?.island === view.island.id;
        const budget = budgetShare(view);
        const missing = view.unavailable ?? [];
        return (
          <>
            <div className="meta">
              <Link to="/">← storm</Link>
            </div>
            <h1>{view.island.name}</h1>
            <p className="lead">
              {view.island.focus}
              {!mine && " · you are signed in to another island, so this page is read-only"}
            </p>
            <p className="meta">
              <a href={`/api/v1/public/islands/${encodeURIComponent(view.island.id)}/papers.html`} target="_blank" rel="noreferrer">
                web 1.0 paper chunks for RAG indexing
              </a>
            </p>
            {missing.length > 0 && (
              <div className="box" role="alert">
                The server could not read: {missing.join(", ")}. Those sections are not empty, they are unavailable.
              </div>
            )}
            <div className="cards">
              <div className="card">
                <b>island cost</b>
                <div className="v">{cost(view.cost_micros)}</div>
                <span className="meta">settled receipts</span>
              </div>
              <div className="card">
                <b>budget share</b>
                <div className="v">{budget.text}</div>
                <span className="meta">{budget.basis}</span>
              </div>
              <div className="card">
                <b>runs left today</b>
                <div className="v">{typeof view.runs_remaining_today === "number" ? view.runs_remaining_today : "—"}</div>
                <span className="meta">{typeof view.runs_remaining_today === "number" ? "at most, before today's budget is spent" : "not reported"}</span>
              </div>
              <div className="card">
                <b>papers waiting</b>
                <div className="v">{view.queue ? view.queue.length : "—"}</div>
                <span className="meta">{view.queue ? "for an agent to take next" : "not reported"}</span>
              </div>
            </div>

            <div className="sec">
              <h2>evolution</h2>
              <span>browse lineage and manage agents</span>
            </div>
            <EvolutionSwitches view={view} mine={mine} onChanged={read.reload} />
            <EvolutionTree agents={view.agents} steps={view.evolution ?? []} initialId={decoded(hash.slice(1)).replace(/^agent-/, "")} {...(mine ? { onSaved: read.reload } : {})} />

            <div className="sec">
              <h2>runs</h2>
              <span>{view.runs.length} · cost beside each</span>
            </div>
            {view.runs.length === 0 ? (
              <p className="meta">No agent has run on this island yet.</p>
            ) : (
              <div className="tw">
                <table>
                  <thead>
                    <tr>
                      <th>agent</th>
                      <th>paper</th>
                      <th>state</th>
                      <th>when</th>
                      <th>cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {view.runs.map((r) => (
                      <tr key={r.id}>
                        <td>
                          <Link to={`/runs/${encodeURIComponent(r.id)}`}>{r.genome_id}</Link>
                        </td>
                        <td>
                          <Link to={`/papers/${encodeURIComponent(r.paper_id)}`}><MathText text={r.paper_title ?? r.paper_id} /></Link>
                        </td>
                        <td>{r.status}</td>
                        <td>{when(r.created_at)}</td>
                        <td className="num">{cost(r.cost_micros)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <div className="sec">
              <h2>papers</h2>
              <span>{view.papers.length} · open one to reach its runs and steps</span>
            </div>
            <div className="tree">
              <PaperBranches papers={view.papers} />
            </div>

            {mine && view.papers.length > 0 && (
              <>
                <div className="sec">
                  <h2>selected papers</h2>
                  <span>Readers select a paper when all completed votes agree. Your choice overrides their votes across the swarm. Selected papers guide future readings on this island.</span>
                </div>
                <LetGo papers={view.papers} onChanged={read.reload} />
              </>
            )}

          </>
        );
      }}
    </Settled>
  );
}
