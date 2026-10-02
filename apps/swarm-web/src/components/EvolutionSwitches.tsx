import { useState } from "react";
import { ApiError, refusal } from "../api/client.ts";
import { useApi } from "../api/context.tsx";
import type { IslandView } from "../api/types.ts";

type Setting = "evolution_enabled" | "mutation_enabled";

function Switch({ label, what, on, disabled, onFlip }: { label: string; what: string; on: boolean | null; disabled: boolean; onFlip: () => void }) {
  return (
    <div className="switch">
      <button type="button" role="switch" aria-checked={on === true} aria-label={label} disabled={disabled} onClick={onFlip}>
        <i />
      </button>
      <span>
        <b>
          {label} {on === null ? "· not reported" : on ? "on" : "off"}
        </b>
        <span className="meta">{what}</span>
      </span>
    </div>
  );
}

/**
 * The island's two switches. Evolution lets the island keep and retire its agents by how their
 * runs did. Mutation lets evolution also make changed copies of the agents it keeps; it has no
 * effect while evolution is off. Each flip is sent to the server and the island is read again, so
 * the switch shows what the server stored. Nothing is switched in the browser alone.
 */
export function EvolutionSwitches({ view, onChanged }: { view: IslandView; onChanged: () => void }) {
  const api = useApi();
  const [state, setState] = useState<{ sending: boolean; refused: string | null }>({ sending: false, refused: null });
  const evolution = typeof view.evolution_enabled === "boolean" ? view.evolution_enabled : null;
  const mutation = typeof view.mutation_enabled === "boolean" ? view.mutation_enabled : null;

  async function flip(setting: Setting, to: boolean) {
    setState({ sending: true, refused: null });
    try {
      await api.post(`/api/v1/islands/${encodeURIComponent(view.island.id)}/settings`, { [setting]: to });
      setState({ sending: false, refused: null });
      onChanged();
    } catch (err) {
      const unserved = err instanceof ApiError && (err.status === 404 || err.status === 405);
      setState({ sending: false, refused: unserved ? "This server does not take evolution settings yet. Nothing changed." : `Nothing changed. ${refusal(err)}` });
    }
  }

  return (
    <div className="switches">
      <Switch
        label="evolution"
        what="keep and retire agents by how their runs did"
        on={evolution}
        disabled={state.sending}
        onFlip={() => void flip("evolution_enabled", evolution !== true)}
      />
      <Switch
        label="mutation"
        what={evolution === false ? "no effect while evolution is off" : "let evolution make changed copies of the agents it keeps"}
        on={mutation}
        disabled={state.sending || evolution === false}
        onFlip={() => void flip("mutation_enabled", mutation !== true)}
      />
      <div className="meta" role="alert" hidden={state.refused === null} style={{ color: "var(--red)" }}>
        {state.refused}
      </div>
    </div>
  );
}
