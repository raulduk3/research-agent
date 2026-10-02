import { useEffect } from "react";
import { Link, useLocation, useParams } from "react-router";
import type { EvolutionStep, Genome, IslandView } from "../api/types.ts";
import { useGet } from "../api/useGet.ts";
import { Settled, decoded, when } from "../common.tsx";
import { EvolutionSwitches } from "../components/EvolutionSwitches.tsx";
import { Feedback } from "../components/Feedback.tsx";
import { GenomeCard } from "../components/GenomeCard.tsx";
import { PaperBranches } from "../components/Tree.tsx";
import { MONTH_TARGET_MICROS, cost, share, usd, usdRound } from "../money.ts";

/** The island's cost as a share of the month's target: the server's figure, else its cost over the target. */
function budgetShare(view: IslandView): { text: string; basis: string } {
  if (typeof view.budget_share === "number") return { text: share(view.budget_share), basis: `of the ${usdRound(MONTH_TARGET_MICROS)} month` };
  if (typeof view.month_cost_micros === "number") {
    return { text: share(view.month_cost_micros / MONTH_TARGET_MICROS), basis: `this month's cost over the ${usdRound(MONTH_TARGET_MICROS)} month` };
  }
  return { text: share(view.cost_micros / MONTH_TARGET_MICROS), basis: `all recorded cost over the ${usdRound(MONTH_TARGET_MICROS)} month` };
}

/** Evolution as the server records it, or, without that, the lineage the stored genomes spell out. */
function Evolution({ steps, genomes }: { steps: readonly EvolutionStep[] | null; genomes: readonly Genome[] }) {
  if (steps !== null && steps.length > 0) {
    return (
      <ol className="chain">
        {steps.map((s, i) => (
          <li key={i} className={s.decision === "created" ? "now" : s.decision === "retired" ? "later" : "you"}>
            <b>
              generation {s.generation} · {s.genome_id} {s.decision}
            </b>
            {s.reason ?? <span className="na">no reason recorded</span>}
          </li>
        ))}
      </ol>
    );
  }
  const children = genomes.filter((g) => g.parent_id !== null);
  if (children.length === 0) return <p className="meta">No evolution yet: the island still runs its founding agents.</p>;
  return (
    <ol className="chain">
      {children.map((g) => (
        <li key={g.id} className={g.active ? "now" : "later"}>
          <b>
            generation {g.generation} · {g.id} {g.active ? "created" : "retired"}
          </b>
          from {g.parent_id} · {when(g.created_at)}
        </li>
      ))}
    </ol>
  );
}

export function IslandPage() {
  const { island = "" } = useParams();
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
        const papers = new Map(view.papers.map((p) => [p.id, p.title]));
        const budget = budgetShare(view);
        return (
          <>
            <div className="meta">
              <Link to="/">← storm</Link>
            </div>
            <h1>{view.island.name}</h1>
            <p className="lead">{view.island.focus}</p>
            <div className="cards">
              <div className="card">
                <b>island cost</b>
                <div className="v">{usd(view.cost_micros)}</div>
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
                <span className="meta">{typeof view.runs_remaining_today === "number" ? "before the day's budget is spent" : "not reported"}</span>
              </div>
              <div className="card">
                <b>runs</b>
                <div className="v">{view.runs.length}</div>
                <span className="meta">most recent, one paper each</span>
              </div>
            </div>

            <div className="sec">
              <h2>agents</h2>
              <span>{view.genomes.length} · what each is told and may call</span>
            </div>
            {view.genomes.length === 0 ? <p className="meta">This island has no agent yet.</p> : view.genomes.map((g) => <GenomeCard key={g.id} genome={g} onSaved={read.reload} />)}

            <div className="sec">
              <h2>evolution</h2>
              <span>what changed, newest generation first</span>
            </div>
            <EvolutionSwitches view={view} onChanged={read.reload} />
            <Evolution steps={view.evolution ?? null} genomes={view.genomes} />

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
                          <Link to={`/papers/${encodeURIComponent(r.paper_id)}`}>{papers.get(r.paper_id) ?? r.paper_id}</Link>
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

            <Feedback targetType="island" targetId={view.island.id} />
          </>
        );
      }}
    </Settled>
  );
}
