import { Link } from "react-router";
import { refusal } from "../api/client.ts";
import type { Island, Storm } from "../api/types.ts";
import { useGet } from "../api/useGet.ts";
import { Lab } from "../common.tsx";
import { Globe, islandHue } from "../components/Globe.tsx";
import { BudgetStrip } from "../shell/BudgetStrip.tsx";

const NO_ISLANDS: readonly Island[] = [];

/**
 * The public front door: the storm as a globe, how much there is, what it has cost against the
 * month's budget, and the way in to an island. It needs no sign-in and reads only the public storm.
 */
export function Splash() {
  const storm = useGet<Storm>("/api/v1/public/storm");
  const data = storm.state === "ready" ? storm.data : null;
  return (
    <div className="splash">
      <nav>
        <span className="brand">
          <span className="mark">🏝️</span>Atoll <span className="app-version">v1.1.0</span>
        </span>
      </nav>
      <Globe islands={data?.islands ?? NO_ISLANDS} papers={data?.papers ?? 0} />
      {storm.state === "failed" ? (
        <div className="box" role="alert">
          <b>The storm is not reachable right now.</b> {refusal(storm.error)}
          <div>
            <button type="button" className="quiet" onClick={storm.reload}>
              try again
            </button>
          </div>
        </div>
      ) : (
        <div className="cnt">
          <span>
            <b>{data ? data.islands.length : "…"}</b> islands
          </span>
          <span>
            <b>{data ? data.papers : "…"}</b> papers
          </span>
          <span>
            <b>{data ? data.runs : "…"}</b> runs, 1 agent : 1 paper
          </span>
        </div>
      )}
      <BudgetStrip storm={storm} />
      {data !== null &&
        (data.islands.length === 0 ? (
          <p className="meta">No island exists yet.</p>
        ) : (
          <div className="enter">
            {data.islands.map((island, i) => (
              <Link key={island.id} className="go" to={`/islands/${encodeURIComponent(island.id)}`}>
                <i style={{ background: `hsl(${islandHue(i)},90%,42%)` }} />
                enter {island.name}
              </Link>
            ))}
          </div>
        ))}
      <Lab />
    </div>
  );
}
