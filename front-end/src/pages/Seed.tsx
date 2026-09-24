import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";
import type { CommandResult, SeedView } from "../api/schema.gen.ts";
import { useCommand } from "../api/useCommand.ts";
import { useGet } from "../api/useGet.ts";
import { Id, Refusal, Show } from "./common.tsx";
import { PART_LABELS } from "./Agent.tsx";

const ISLANDS = ["cs", "quant-ph", "q-bio"] as const;

/** Seed a variant into an island, copied from a template genome (`?template=`). */
export function Seed() {
  const [params] = useSearchParams();
  const template = params.get("template");
  const view = useGet<SeedView>("/api/v1/seed", template ? { template } : {});

  return (
    <>
      <h1>Seed a variant</h1>
      <Show loaded={view}>{(v) => <SeedForm key={v.copied?.configuration_id ?? ""} view={v} />}</Show>
    </>
  );
}

function SeedForm({ view }: { view: SeedView }) {
  const copied = view.copied;
  const [island, setIsland] = useState<string>(copied?.island ?? ISLANDS[0]);
  const [lineage, setLineage] = useState(copied?.lineage_id ?? "");
  const [templateId, setTemplateId] = useState(copied?.configuration_id ?? "");
  const [parts, setParts] = useState<Record<string, string>>(() =>
    Object.fromEntries(view.emphasis_fields.items.map((p) => [p, copied?.emphasis[p] ?? ""])),
  );
  const seed = useCommand<CommandResult>("/api/v1/seed");

  function onSeed(e: FormEvent) {
    e.preventDefault();
    void seed.send({ island, lineage_id: lineage, template_configuration_id: templateId, ...parts });
  }

  return (
    <>
      <div className="meta">
        Creates a new agent in the island you choose. The template is untouched and stays its own record.
      </div>
      <form onSubmit={onSeed}>
        <label>
          Island{" "}
          <select value={island} onChange={(e) => setIsland(e.target.value)}>
            {ISLANDS.map((i) => (
              <option key={i}>{i}</option>
            ))}
          </select>
        </label>
        <label>
          Lineage
          <input value={lineage} onChange={(e) => setLineage(e.target.value)} />
        </label>
        <label>
          Template agent
          <input value={templateId} onChange={(e) => setTemplateId(e.target.value)} />
        </label>
        {view.emphasis_fields.items.map((p) => (
          <label key={p}>
            {PART_LABELS[p]}
            <textarea value={parts[p] ?? ""} onChange={(e) => setParts({ ...parts, [p]: e.target.value })} />
          </label>
        ))}
        <button type="submit" disabled={seed.result.state === "sending" || templateId.trim() === ""}>
          seed as new agent
        </button>
      </form>
      {seed.result.state === "failed" && <Refusal error={seed.result.error} />}
      {seed.result.state === "done" && (
        <div className="meta" role="status">
          Seeded:{" "}
          <Link to={`/agents/${seed.result.data.configuration_id}`}>
            <Id value={seed.result.data.configuration_id} />
          </Link>
        </div>
      )}
    </>
  );
}
