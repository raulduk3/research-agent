import { useState, type FormEvent } from "react";
import { ApiError, refusal } from "../api/client.ts";
import { useApi } from "../api/context.tsx";
import type { Genome } from "../api/types.ts";
import { TOOLS, toolNames } from "../common.tsx";
import { cost } from "../money.ts";

/**
 * Editing an agent: its prompt and the tools it may call. Saving never changes the stored genome;
 * it asks the server for a new version descended from this one, so the earlier version and every
 * run it made stay as they are. If the server does not take the edit, the text stays in the form.
 */
function GenomeEdit({ genome, onSaved, onClose }: { genome: Genome; onSaved: () => void; onClose: () => void }) {
  const api = useApi();
  const [prompt, setPrompt] = useState(genome.prompt);
  const [tools, setTools] = useState(() => new Set(toolNames(genome.tools)));
  const [state, setState] = useState<{ sending: boolean; refused: string | null }>({ sending: false, refused: null });
  const offered = [...new Set([...TOOLS, ...toolNames(genome.tools)])];
  const changed = prompt !== genome.prompt || [...tools].sort().join() !== toolNames(genome.tools).sort().join();

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
      const unserved = err instanceof ApiError && (err.status === 404 || err.status === 405);
      setState({ sending: false, refused: unserved ? "This server does not take agent edits yet. Nothing was saved." : `Nothing was saved. ${refusal(err)}` });
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
 * An agent's genome: the prompt it is given and the tools it may call. With `onSaved` the agent
 * can be edited here, which is offered on its island's page; elsewhere it is shown as stored.
 */
export function GenomeCard({ genome, onSaved }: { genome: Genome; onSaved?: () => void }) {
  const [editing, setEditing] = useState(false);
  const tools = toolNames(genome.tools);
  return (
    <div className="box genome" id={`agent-${genome.id}`}>
      <div className="meta">
        agent <span className="code">{genome.id}</span> · generation {genome.generation} ·{" "}
        {genome.parent_id === null ? "founder" : `from ${genome.parent_id}`} · {genome.active ? "active" : "retired"}
        {typeof genome.cost_micros === "number" && ` · ${cost(genome.cost_micros)}`}
      </div>
      {editing && onSaved ? (
        <GenomeEdit genome={genome} onSaved={onSaved} onClose={() => setEditing(false)} />
      ) : (
        <>
          <div className="said">{genome.prompt}</div>
          {tools.length > 0 && (
            <div className="tags">
              may call{" "}
              {tools.map((t) => (
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
