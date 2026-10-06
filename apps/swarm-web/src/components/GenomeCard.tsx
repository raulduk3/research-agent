import { genomeRequestSchema, agentEditRequestSchema, revisionAnswerSchema } from "../api/contracts.ts";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { refusal } from "../api/client.ts";
import { useApi } from "../api/context.tsx";
import type { Agent } from "../api/types.ts";
import { TOOLS } from "../common.tsx";
import { cost } from "../money.ts";
import { Like } from "./Like.tsx";
import { MathText } from "./MathText.tsx";

/**
 * The agent this one descends from, wherever the answer put it. An agent edited by hand names
 * itself as version parent; stored evolutionary parents still describe its ancestry.
 */
export function parentOf(agent: Agent): string | null {
  const parent = agent.parent_id ?? agent.lineage?.parent?.genome_id ?? null;
  return parent === agent.id ? agent.lineage?.parents?.find((id) => id !== agent.id) ?? null : parent;
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
      }, genomeRequestSchema, revisionAnswerSchema);
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
  const api = useApi();
  const [editing, setEditing] = useState(false);
  const [sending, setSending] = useState(false);
  const [refused, setRefused] = useState<string | null>(null);
  const parent = parentOf(genome);

  async function setActive(active: boolean) {
    if (sending) return;
    setSending(true);
    setRefused(null);
    try {
      await api.post(`/api/v1/agents/${encodeURIComponent(genome.id)}`, { fields: { active } }, agentEditRequestSchema, revisionAnswerSchema);
      onSaved?.();
    } catch (err) {
      setRefused(`Nothing changed. ${refusal(err)}`);
    } finally {
      setSending(false);
    }
  }
  return (
    <div className="box genome" id={`agent-${genome.id}`}>
      <div className="meta">
        agent <span className="code">{genome.id}</span>
        {typeof genome.version === "number" && ` · version ${genome.version}`} · generation {generationOf(genome)} ·{" "}
        {parent !== null ? `from ${parent}` : (genome.version ?? 1) > 1 ? "edited" : "founder"} · {genome.active ? (genome.state ?? "active") : "archived"}
        {genome.state === "blocked" && genome.blocked_reason ? ` (${genome.blocked_reason.replace(/_/g, " ")})` : ""}
        {typeof genome.cost_micros === "number" && ` · ${cost(genome.cost_micros)}`}
        {typeof genome.points === "number" && ` · ${genome.points} point${genome.points === 1 ? "" : "s"}`} <Like kind="agent" id={genome.id} />
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
          {genome.research_methods?.instructions && (
            <details>
              <summary>Research methods</summary>
              <div className="said"><MathText text={genome.research_methods.instructions} /></div>
              {!genome.research_methods.specialist && <p className="meta">General methods applied to this island's focus.</p>}
              <details>
                <summary>Method sources · version {genome.research_methods.version}</summary>
                <ul>
                  {genome.research_methods.sources.map((source) => (
                    <li key={source.url}><a href={source.url} target="_blank" rel="noreferrer">{source.title}</a></li>
                  ))}
                </ul>
                <p className="meta">Research methods adapted to the available tools. Sources and lineage stay in agent data.</p>
              </details>
            </details>
          )}
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
            <>
              {genome.active && (
                <button type="button" className="quiet ctl" onClick={() => setEditing(true)}>
                  edit this agent
                </button>
              )}
              <button type="button" className="quiet ctl" disabled={sending} onClick={() => void setActive(!genome.active)}>
                {genome.active ? "archive" : "bring back"}
              </button>
              {refused !== null && (
                <span className="meta" role="alert" style={{ color: "var(--red)" }}>
                  {refused}
                </span>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
