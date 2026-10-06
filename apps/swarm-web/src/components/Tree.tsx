import { useState, type ReactNode } from "react";
import { Link } from "react-router";
import type { IslandPaper, IslandView, Paper, PaperView, Run, RunView } from "../api/types.ts";
import { useGet } from "../api/useGet.ts";
import { BadgeTag, Settled } from "../common.tsx";
import { usd } from "../money.ts";
import { MathText } from "./MathText.tsx";

/** A level's cost when the server reports one; a level without one shows no figure rather than a zero. */
function shown(micros: number | null | undefined): string {
  return typeof micros === "number" ? usd(micros) : "";
}

/** One level of the tree: closed until asked for, and its children are read only once it opens. */
function Branch({ label, sum, open: startOpen = false, children }: { label: ReactNode; sum: ReactNode; open?: boolean; children: () => ReactNode }) {
  const [open, setOpen] = useState(startOpen);
  return (
    <details className="grp" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>
        <span>{label}</span>
        <span className="gsum">{sum}</span>
      </summary>
      {open && <div className="kids">{children()}</div>}
    </details>
  );
}

function RunSteps({ runId }: { runId: string }) {
  const read = useGet<RunView>(`/api/v1/runs/${encodeURIComponent(runId)}`);
  return (
    <Settled read={read} what="The run's steps">
      {(view) =>
        view.events.length === 0 ? (
          <p className="meta">No step is stored for this run.</p>
        ) : (
          <ol className="steps">
            {view.events.map((e, i) => (
              <li key={e.id}>
                <Link to={`/runs/${encodeURIComponent(runId)}?step=${i + 1}`}>
                  <BadgeTag event={e} />
                  <span className="t"><MathText text={e.input || e.body} /></span>
                </Link>
                <span className="c">{usd(e.cost_micros)}</span>
              </li>
            ))}
          </ol>
        )
      }
    </Settled>
  );
}

/** A run and, under it, the steps it recorded: the bottom of the cascade. */
export function RunBranch({ run }: { run: Run }) {
  return (
    <Branch
      label={
        <>
          <Link to={`/runs/${encodeURIComponent(run.id)}`}>agent {run.genome_id}</Link> <span className="meta">· {run.status}</span>
        </>
      }
      sum={shown(run.cost_micros)}
    >
      {() => <RunSteps runId={run.id} />}
    </Branch>
  );
}

function PaperRuns({ paperId }: { paperId: string }) {
  const read = useGet<PaperView>(`/api/v1/papers/${encodeURIComponent(paperId)}`);
  return (
    <Settled read={read} what="The paper's runs">
      {(view) =>
        view.runs.length === 0 ? <p className="meta">No agent has run on this paper yet.</p> : view.runs.map((r) => <RunBranch key={r.id} run={r} />)
      }
    </Settled>
  );
}

export function PaperBranch({ paper, status }: { paper: Paper; status?: string }) {
  return (
    <Branch label={<><Link to={`/papers/${encodeURIComponent(paper.id)}`}><MathText text={paper.title} /></Link>{status && <span className="meta"> · {status}</span>}</>} sum={shown(paper.cost_micros)}>
      {() => <PaperRuns paperId={paper.id} />}
    </Branch>
  );
}

function IslandPapers({ islandId }: { islandId: string }) {
  const read = useGet<IslandView>(`/api/v1/islands/${encodeURIComponent(islandId)}`);
  return (
    <Settled read={read} what="The island's papers">
      {(view) => <PaperBranches papers={view.papers} />}
    </Settled>
  );
}

export function PaperBranches({ papers, selectionStatus = false }: { papers: readonly IslandPaper[]; selectionStatus?: boolean }) {
  if (papers.length === 0) return <p className="meta">No paper has reached this island yet.</p>;
  return (
    <>
      {papers.map((p) => (
        <PaperBranch key={p.id} paper={p} {...(selectionStatus ? { status: p.selected_by?.startsWith("island:") || p.selected_by === "operator" ? "selected by a person" : "selected by agents" } : {})} />
      ))}
    </>
  );
}

/**
 * The tree explorer: island, then its papers, then each paper's runs, then each run's steps, with
 * the cost the server reports at every level. Each level is read when it is opened.
 */
export function Tree({ islandId, islandName }: { islandId: string; islandName?: string }) {
  return (
    <div className="tree">
      <Branch open label={<Link to={`/islands/${encodeURIComponent(islandId)}`}>{islandName ?? `island ${islandId}`}</Link>} sum="island → paper → run → step">
        {() => <IslandPapers islandId={islandId} />}
      </Branch>
    </div>
  );
}
