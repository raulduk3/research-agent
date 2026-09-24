import { Link } from "react-router";
import type { Health, Retrospective } from "../api/schema.gen.ts";
import { useGet } from "../api/useGet.ts";
import { Id, Show, when } from "./common.tsx";

/** Owner home (design-mock/overview.html): the health monitor, then every owner action. */
export function Overview() {
  const health = useGet<Health>("/api/v1/health");
  const retro = useGet<Retrospective>("/api/v1/retrospective");

  return (
    <>
      <h1>Owner home</h1>
      <h2>Health</h2>
      <Show loaded={health}>
        {(h) => (
          <>
            <div className="card">
              <b>Platform</b>
              <div className="v">{h.state.replace("_", " ")}</div>
              <span className="meta">checked {when(h.checked_at)}</span>
            </div>
            <div className="tw">
              <table>
                <tbody>
                  <tr>
                    <th>Check</th>
                    <th>State</th>
                    <th>Detail</th>
                  </tr>
                  {h.checks.map((c) => (
                    <tr key={c.name}>
                      <td>{c.name}</td>
                      <td>{c.state.replace("_", " ")}</td>
                      <td>{c.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Show>
      <h2>Owner actions</h2>
      <Show loaded={retro}>
        {(r) => (
          <>
            <div className="tw">
              <table>
                <tbody>
                  <tr>
                    <th>When</th>
                    <th>Action</th>
                    <th>Agent</th>
                    <th>From</th>
                  </tr>
                  {r.admissions.items.map((a) => (
                    <tr key={`a-${a.configuration_id}`}>
                      <td>{when(a.requested_at)}</td>
                      <td>{a.kind === "seed" ? "seeded" : "admitted an edit"}</td>
                      <td>
                        <Link to={`/agents/${a.configuration_id}`}>
                          <Id value={a.configuration_id} />
                        </Link>
                      </td>
                      <td>
                        {a.source_configuration_id ? (
                          <Link to={`/agents/${a.source_configuration_id}`}>
                            <Id value={a.source_configuration_id} />
                          </Link>
                        ) : (
                          <span className="meta">none</span>
                        )}
                      </td>
                    </tr>
                  ))}
                  {r.retirements.items.map((t) => (
                    <tr key={`r-${t.configuration_id}`}>
                      <td>{when(t.requested_at)}</td>
                      <td>retired</td>
                      <td>
                        <Link to={`/agents/${t.configuration_id}`}>
                          <Id value={t.configuration_id} />
                        </Link>
                      </td>
                      <td />
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {r.admissions.items.length + r.retirements.items.length === 0 && (
              <div className="meta">No owner action recorded yet.</div>
            )}
            {(r.admissions.next_cursor ?? r.retirements.next_cursor) !== null && (
              <div className="meta">Older actions are stored beyond this page.</div>
            )}
          </>
        )}
      </Show>
    </>
  );
}
