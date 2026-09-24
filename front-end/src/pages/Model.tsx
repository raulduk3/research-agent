import { useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router";
import type { ManifestView } from "../api/schema.gen.ts";
import { useGet } from "../api/useGet.ts";
import { Ids, Show, when } from "./common.tsx";

/** The models menu entry: a manifest is read by its hash, as a run's model identity names it. */
export function Models() {
  const navigate = useNavigate();
  const [hash, setHash] = useState("");
  function open(e: FormEvent) {
    e.preventDefault();
    void navigate(`/models/${encodeURIComponent(hash.trim())}`);
  }
  return (
    <>
      <h1>Models</h1>
      <div className="meta">A published manifest: bundle, refresh or release, read by its hash.</div>
      <form onSubmit={open}>
        <label>
          Manifest hash <input value={hash} onChange={(e) => setHash(e.target.value)} />
        </label>
        <button type="submit" disabled={hash.trim() === ""}>
          open
        </button>
      </form>
    </>
  );
}

/** One manifest (design-mock/models.html): its kind and typed fields. */
export function Model() {
  const { manifestHash = "" } = useParams();
  const view = useGet<ManifestView>(`/api/v1/models/${encodeURIComponent(manifestHash)}`);

  return (
    <Show loaded={view}>
      {({ manifest: m }) => (
        <>
          <h1>
            {m.manifest_kind} <span className="meta">manifest · {when(m.created_at)}</span>
          </h1>
          <div className="tw">
            <table className="kv">
              <tbody>
                {Object.entries(m.fields).map(([name, value]) => (
                  <tr key={name}>
                    <th>{name.replaceAll("_", " ")}</th>
                    <td className="code">{typeof value === "string" ? value : JSON.stringify(value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="meta">
            {m.media_type} · {m.byte_length} bytes
          </div>
          <Ids
            rows={[
              ["manifest", m.manifest_hash],
              ["artifact", m.artifact_hash],
            ]}
          />
        </>
      )}
    </Show>
  );
}
