import { useState } from "react";
import { refusal } from "../api/client.ts";
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

export function EvolutionSwitches({ view, mine, onChanged }: { view: IslandView; mine: boolean; onChanged: () => void }) {
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
      setState({ sending: false, refused: `Nothing changed. ${refusal(err)}` });
    }
  }

  return (
    <div className="switches">
      <Switch
        label="evolution"
        what={
          !mine
            ? "only this island's own session can switch it"
            : view.swarm_evolution_enabled === false
              ? "off for the whole swarm by the operator; this switch takes effect once that is on"
              : "automatic cycles mate agents and vary their research methods"
        }
        on={evolution}
        disabled={state.sending || !mine}
        onFlip={() => void flip("evolution_enabled", evolution !== true)}
      />
      <Switch
        label="mutation"
        what={evolution === false ? "no effect while evolution is off" : "automatic cycles also vary inherited research methods"}
        on={mutation}
        disabled={state.sending || !mine || evolution === false}
        onFlip={() => void flip("mutation_enabled", mutation !== true)}
      />
      <div className="meta" role="alert" hidden={state.refused === null} style={{ color: "var(--red)" }}>
        {state.refused}
      </div>
    </div>
  );
}
