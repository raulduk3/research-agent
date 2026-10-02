import { useState } from "react";
import { refusal } from "../api/client.ts";
import { useApi } from "../api/context.tsx";
import type { Island } from "../api/types.ts";

/**
 * The island's evolution switch. With it on, a cycle keeps the island's best agent, tries one
 * mutated child of it and retires the worst once the island is full; with it off the agents
 * change only when someone edits one. A flip is sent to the server as an edit of the island and
 * the island is read again, so the switch shows what the server stored.
 *
 * `swarmOn` is the operator's switch for every island: evolution runs only where both are on.
 * `mine` is whether the session may edit this island.
 */
export function EvolutionSwitch({ island, swarmOn, mine, onChanged }: { island: Island; swarmOn: boolean | null; mine: boolean; onChanged: () => void }) {
  const api = useApi();
  const [state, setState] = useState<{ sending: boolean; refused: string | null }>({ sending: false, refused: null });
  const on = typeof island.evolve === "boolean" ? island.evolve : null;

  async function flip() {
    setState({ sending: true, refused: null });
    try {
      await api.post(`/api/v1/islands/${encodeURIComponent(island.id)}`, { fields: { evolve: on !== true } });
      setState({ sending: false, refused: null });
      onChanged();
    } catch (err) {
      setState({ sending: false, refused: `Nothing changed. ${refusal(err)}` });
    }
  }

  return (
    <div className="switches">
      <div className="switch">
        <button type="button" role="switch" aria-checked={on === true} aria-label="evolution" disabled={state.sending || !mine} onClick={() => void flip()}>
          <i />
        </button>
        <span>
          <b>evolution and mutation {on === null ? "· not reported" : on ? "on" : "off"}</b>
          <span className="meta">
            {!mine
              ? "only this island's own session can switch it"
              : swarmOn === false
                ? "off for the whole swarm by the operator; this switch takes effect once that is on"
                : "each cycle keeps the best agent, tries one mutated child and retires the worst"}
          </span>
        </span>
      </div>
      <div className="meta" role="alert" hidden={state.refused === null} style={{ color: "var(--red)" }}>
        {state.refused}
      </div>
    </div>
  );
}
