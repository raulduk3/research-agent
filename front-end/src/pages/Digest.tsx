import { Link, useParams } from "react-router";
import type { OwnerDigest } from "../api/schema.gen.ts";
import { useGet } from "../api/useGet.ts";
import { Id, Ids, Show, when } from "./common.tsx";

/**
 * One stored digest with its provenance (SR-25). The owner is also a rater: an entry the owner
 * has not rated arrives with its origin withheld, and the page shows nothing more than the API sent.
 */
export function Digest() {
  const { digestHash = "" } = useParams();
  const view = useGet<OwnerDigest>(`/api/v1/digests/${encodeURIComponent(digestHash)}`);

  return (
    <Show loaded={view}>
      {(d) => (
        <>
          <h1>
            Digest {d.island} <span className="meta">· built {when(d.built_at)}</span>
          </h1>
          <div className="tw">
            <table>
              <tbody>
                <tr>
                  <th>#</th>
                  <th>Paper</th>
                  <th>Origin</th>
                  <th>Nominated by</th>
                </tr>
                {[...d.entries]
                  .sort((a, b) => a.display_position - b.display_position)
                  .map((e) => (
                    <tr key={e.entry_id}>
                      <td>{e.display_position}</td>
                      <td>
                        <Id value={e.paper_hash} />
                      </td>
                      {e.rated ? (
                        <>
                          <td>
                            {e.origin.replaceAll("_", " ")}
                            {e.service_source && <span className="meta"> · {e.service_source}</span>}
                            {e.inclusion_probability !== null && (
                              <span className="meta"> · p {e.inclusion_probability.toFixed(3)}</span>
                            )}
                          </td>
                          <td>
                            {e.nominations.map((n) => (
                              <div key={n.submission_id}>
                                <Link to={`/agents/${n.configuration_id}`}>
                                  <Id value={n.configuration_id} />
                                </Link>{" "}
                                <span className="meta">preference {n.preference}</span>
                              </div>
                            ))}
                          </td>
                        </>
                      ) : (
                        <td colSpan={2} className="meta">
                          blinded until you rate it
                        </td>
                      )}
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          <Ids
            rows={[
              ["digest", d.digest_hash],
              ["batch", d.batch_id],
              ["shuffle seed", d.shuffle_seed],
              ["source watermark", String(d.source_watermark)],
            ]}
          />
        </>
      )}
    </Show>
  );
}
