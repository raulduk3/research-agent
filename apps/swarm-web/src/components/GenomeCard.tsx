import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { refusal } from "../api/client.ts";
import { useApi } from "../api/context.tsx";
import type { Agent } from "../api/types.ts";
import { TOOLS } from "../common.tsx";
import { cost } from "../money.ts";
import { MathText } from "./MathText.tsx";

/**
 * The agent this one descends from, wherever the answer put it. An agent edited by hand names
 * itself as parent (its earlier version); that is a new version, not a descendant.
 */
export function parentOf(agent: Agent): string | null {
  const parent = agent.parent_id ?? agent.lineage?.parent?.genome_id ?? null;
  return parent === agent.id ? null : parent;
}

export function generationOf(agent: Agent): number {
  return agent.generation ?? agent.lineage?.generation ?? 0;
}

/**
 * Editing an agent: its prompt and the tools it may call. Saving never changes what is stored; it
 * asks the server for a new version of the agent, so the earlier version and every run it made
 * stay as they are and can be brought back. If the server refuses, the text stays in the form.
 */
function GenomeEdit({ genome, onSaved, onClose }: { genome: Agent; onSaved: () => void; onClose: () => void }) {
  const api = useApi();
  const [prompt, setPrompt] = useState(genome.prompt);
  const [tools, setTools] = useState(() => new Set(genome.allowed_tools));
  const [state, setState] = useState<{ sending: boolean; refused: string | null }>({ sending: false, refused: null });
  const offered = [...new Set([...TOOLS, ...genome.allowed_tools])];
  const changed = prompt !== genome.prompt || [...tools].sort().join() !== [...genome.allowed_tools].sort().join();

  async function save(e: FormEvent) {
    e.preventDefault();
    setState({ sending: true, refused: null });
    try {
      await api.post("/api/v1/genomes", {
        island_id: genome.island_id,
        parent_id: genome.id,
        prompt,
        tools: offered.filter((t) => tools.has(t)).join(","),
      });
      onSaved();
      onClose();
    } catch (err) {
      setState({ sending: false, refused: `Nothing was saved. ${refusal(err)}` });
    }
  }

  return (
    <form onSubmit={(e) => void save(e)}>
      <label htmlFor={`prompt-${genome.id}`}>Prompt</label>
      <textarea id={`prompt-${genome.id}`} rows={6} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
      <fieldset className="toolset">
        <legend>May call</legend>
        {offered.map((t) => (
          <label key={t}>
            <input
              type="checkbox"
              checked={tools.has(t)}
              onChange={(e) => {
                const next = new Set(tools);
                if (e.target.checked) next.add(t);
                else next.delete(t);
                setTools(next);
              }}
            />{" "}
            {t}
          </label>
        ))}
      </fieldset>
      <div className="meta">Saving makes a new version of this agent. This version and every run it made stay as they are.</div>
      <div className="meta" role="alert" hidden={state.refused === null} style={{ color: "var(--red)" }}>
        {state.refused}
      </div>
      <button type="submit" className="ctl" disabled={state.sending || !changed || prompt.trim() === ""}>
        {state.sending ? "saving…" : "save as a new version"}
      </button>
      <button type="button" className="quiet ctl" onClick={onClose}>
        cancel
      </button>
    </form>
  );
}

/**
 * An agent: the prompt it is given, the tools it may call and what it is doing now. With `onSaved`
 * the agent can be edited here, which is offered on its own island's page; elsewhere it is shown
 * as stored.
 */
export function GenomeCard({ genome, onSaved }: { genome: Agent; onSaved?: () => void }) {
  const [editing, setEditing] = useState(false);
  const parent = parentOf(genome);
  return (
    <div className="box genome" id={`agent-${genome.id}`}>
      <div className="meta">
        agent <span className="code">{genome.id}</span>
        {typeof genome.version === "number" && ` · version ${genome.version}`} · generation {generationOf(genome)} ·{" "}
        {parent !== null ? `from ${parent}` : (genome.version ?? 1) > 1 ? "edited" : "founder"} · {genome.active ? (genome.state ?? "active") : "retired"}
        {genome.state === "blocked" && genome.blocked_reason ? ` (${genome.blocked_reason.replace(/_/g, " ")})` : ""}
        {typeof genome.cost_micros === "number" && ` · ${cost(genome.cost_micros)}`}
      </div>
      {genome.current && (
        <div className="explore">
          reading now: <Link to={`/runs/${encodeURIComponent(genome.current.run_id)}`}><MathText text={genome.current.paper_title} /> · watch</Link>
        </div>
      )}
      {editing && onSaved ? (
        <GenomeEdit genome={genome} onSaved={onSaved} onClose={() => setEditing(false)} />
      ) : (
        <>
          <div className="said"><MathText text={genome.prompt} /></div>
          {genome.allowed_tools.length > 0 && (
            <div className="tags">
              may call{" "}
              {genome.allowed_tools.map((t) => (
                <span key={t} className="tag see">
                  {t}
                </span>
              ))}
            </div>
          )}
          {onSaved && (
            <button type="button" className="quiet ctl" onClick={() => setEditing(true)}>
              edit this agent
            </button>
          )}
        </>
      )}
    </div>
  );
}
