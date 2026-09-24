import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";
import type { ManifestView, OwnerModels } from "../api/schema.gen.ts";
import { type Loaded, useGet } from "../api/useGet.ts";
import { EmptyCard, Id, Ids, Lead, ready, UNSERVED, when } from "./common.tsx";

/**
 * The models menu entry (design-mock/models.html): every agent model manifest a stored run
 * pins, from /api/v1/models, each opening its manifest; a hash can still be opened directly.
 */
export function Models() {
  const models = useGet<OwnerModels>("/api/v1/models");
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
      <ModelList models={models} />
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

/** The mock's model sections after the manifest's (design-mock/models.html); no /api/v1 route serves them. */
const MODEL_SECTIONS = ["Training corpus", "Agent model", "Summarizer"] as const;

/** The mock's spending cards on the models page; the costs page serves spend. */
const SPENDING_CARDS = ["Today's batch", "Tonight so far", "This month", "Summarizer today", "Scholarly API · Jev"] as const;

/**
 * One manifest, laid out as design-mock/models.html with every section in order. The manifest
 * takes the embedding section's place, its kind as the heading and its fields as the table; the
 * model list, the prediction heads, the corpus, agent model and summarizer, spending and the
 * content assessments have no /api/v1 route and render empty (docs/implementation/front-end.md).
 */
export function Model() {
  const { manifestHash = "" } = useParams();
  const view = useGet<ManifestView>(`/api/v1/models/${encodeURIComponent(manifestHash)}`);
  const m = ready(view)?.manifest ?? null;
  const models = useGet<OwnerModels>("/api/v1/models");

  return (
    <>
      <h1>Models</h1>
      <Lead reads={[view]}>
        {() => m && `A ${m.manifest_kind} manifest, published ${when(m.created_at)}: ${m.media_type}, ${m.byte_length} bytes.`}
      </Lead>
      <ModelList models={models} />
      <h2>Prediction heads</h2>
      <div className="meta">One logistic head per target, calibrated per category, promoted only after qualification.</div>
      <div className="tw">
        <table className="wide">
          <tbody>
            <tr>
              <th>Target</th>
              <th>Status</th>
              <th>Held-out Brier loss, head vs base rate (0 is perfect)</th>
              <th>Interval of the difference</th>
              <th>Regularization strength</th>
              <th>Promoted</th>
            </tr>
            <tr>
              <td colSpan={6}>{UNSERVED}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div className="meta">The heads&apos; fit and weekly refit: {UNSERVED}.</div>
      <details>
        <summary>calibration per category (a, b and calibration Brier)</summary>
        <div className="tw">
          <table>
            <tbody>
              <tr>
                <th>Target</th>
                <th>cs.AI</th>
                <th>cs.LG</th>
                <th>quant-ph</th>
                <th>q-bio</th>
              </tr>
              <tr>
                <td colSpan={5}>{UNSERVED}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </details>
      <h2>{m ? m.manifest_kind : "Manifest"}</h2>
      <FieldTable rows={m ? Object.entries(m.fields) : null} />
      {MODEL_SECTIONS.map((section) => [
        <h2 key={`${section}-h`}>{section}</h2>,
        <FieldTable key={section} rows={null} />,
      ])}
      <h2>Spending</h2>
      <div className="cards">
        {SPENDING_CARDS.map((card) => (
          <EmptyCard key={card} title={card}>
            spend is on the costs page
          </EmptyCard>
        ))}
      </div>
      <h2>Paper-content assessments (Jev)</h2>
      <div className="box">
        <span className="na">Held out</span> until provider access exists: {UNSERVED}.
      </div>
      <Ids
        rows={[
          ["manifest", m?.manifest_hash ?? manifestHash],
          ["artifact", m?.artifact_hash],
        ]}
      />
    </>
  );
}

/**
 * The model list: each agent model manifest a stored run pins, with its run count and first
 * and latest run instants. Only agent models are listed; the heads, embedding and summarizer
 * are not, and a failed read leaves the row "not served yet".
 */
function ModelList({ models }: { models: Loaded<OwnerModels> }) {
  const items = ready(models)?.models.items ?? null;
  return (
    <div className="tw">
      <table>
        <tbody>
          <tr>
            <th>Model</th>
            <th>Role</th>
            <th>State</th>
            <th />
          </tr>
          {items === null || items.length === 0 ? (
            <tr>
              <td colSpan={4}>{items === null ? UNSERVED : "no stored run pins a model"}</td>
            </tr>
          ) : (
            items.map((row) => (
              <tr key={row.manifest_hash}>
                <td>
                  <Id value={row.manifest_hash} />
                </td>
                <td>agent model</td>
                <td>
                  {row.runs} {row.runs === 1 ? "run" : "runs"}, {when(row.first_run_at)} to {when(row.last_run_at)}
                </td>
                <td>
                  <Link to={`/models/${encodeURIComponent(row.manifest_hash)}`}>open</Link>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

/** A model section's fields, or its empty row when nothing serves it. */
function FieldTable({ rows }: { rows: readonly (readonly [string, unknown])[] | null }) {
  return (
    <div className="tw">
      <table className="kv">
        <tbody>
          <tr>
            <th>Field</th>
            <th>Value</th>
          </tr>
          {rows === null ? (
            <tr>
              <td colSpan={2}>{UNSERVED}</td>
            </tr>
          ) : (
            rows.map(([name, value]) => (
              <tr key={name}>
                <td>{name.replaceAll("_", " ")}</td>
                <td>{typeof value === "string" ? value : JSON.stringify(value)}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
