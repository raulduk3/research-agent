import { useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router";
import type { ManifestView } from "../api/schema.gen.ts";
import { useGet } from "../api/useGet.ts";
import { Diag } from "../shell/Diag.tsx";
import { Ids, Show, when } from "./common.tsx";

/**
 * The models menu entry (design-mock/models.html). No route lists the models, so the
 * page opens one manifest by its hash, as a run's model identity names it.
 */
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
      <p className="lead">A published manifest: bundle, refresh or release, read by its hash.</p>
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

/** One manifest, laid out as a model section of design-mock/models.html: its typed fields. */
export function Model() {
  const { manifestHash = "" } = useParams();
  const view = useGet<ManifestView>(`/api/v1/models/${encodeURIComponent(manifestHash)}`);

  return (
    <Show loaded={view}>
      {({ manifest: m }) => (
        <>
          <h1>Models</h1>
          <p className="lead">
            A {m.manifest_kind} manifest, published {when(m.created_at)}: {m.media_type}, {m.byte_length} bytes.
          </p>
          <h2>{m.manifest_kind}</h2>
          <div className="tw">
            <table className="kv">
              <tbody>
                <tr>
                  <th>Field</th>
                  <th>Value</th>
                </tr>
                {Object.entries(m.fields).map(([name, value]) => (
                  <tr key={name}>
                    <td>{name.replaceAll("_", " ")}</td>
                    <td>{typeof value === "string" ? value : JSON.stringify(value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Ids
            rows={[
              ["manifest", m.manifest_hash],
              ["artifact", m.artifact_hash],
            ]}
          />
          <Diag />
        </>
      )}
    </Show>
  );
}
