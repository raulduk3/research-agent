import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { useApi } from "../api/context.tsx";
import { refusal } from "../api/client.ts";
import type { Activity, ActivityPaper, ActivityStep, Brief, BriefNumbers, Island, Storm } from "../api/types.ts";
import { useGet } from "../api/useGet.ts";
import { Lab } from "../common.tsx";
import { Globe, islandHue, type GlobePaper } from "../components/Globe.tsx";
import { BudgetStrip } from "../shell/BudgetStrip.tsx";

const NO_ISLANDS: readonly Island[] = [];
/** How often the splash asks for new steps, and the most it keeps for the globe. */
const POLL_MS = 4000;
const KEEP_STEPS = 400;

/** The newest steps, polled from the public feed. A server without the feed leaves it empty. */
function useActivity(): { steps: ActivityStep[]; papers: Record<string, ActivityPaper> } {
  const api = useApi();
  const [steps, setSteps] = useState<ActivityStep[]>([]);
  const [papers, setPapers] = useState<Record<string, ActivityPaper>>({});
  useEffect(() => {
    let live = true;
    let after = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const read = () => {
      api.get<Activity>(`/api/v1/public/activity?after=${after}&limit=60`).then(
        (feed) => {
          if (!live) return;
          after = Math.max(after, feed.last_id);
          if (feed.steps.length > 0) setSteps((had) => [...had, ...feed.steps].slice(-KEEP_STEPS));
          if (Object.keys(feed.papers).length > 0) setPapers((had) => ({ ...had, ...feed.papers }));
          timer = setTimeout(read, POLL_MS);
        },
        () => {
          if (!live) return;
          // A transient failure must recover even before the first successful answer.
          timer = setTimeout(read, POLL_MS * 3);
        },
      );
    };
    read();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [api]);
  return { steps, papers };
}

function num(numbers: BriefNumbers | undefined, key: string): number {
  const value = numbers?.[key];
  return typeof value === "number" ? value : 0;
}

function gradeTone(letter: string): string {
  if (letter.startsWith("A")) return "good";
  if (letter.startsWith("B")) return "fair";
  if (letter.startsWith("C")) return "poor";
  return "bad";
}

/**
 * The public front door: what the swarm is, the storm as a living globe, a hard grade of the whole
 * system computed from its stored data, the claims it has made, the papers it holds and lets go,
 * and the way in to an island. It needs no sign-in and reads only the public routes.
 */
export function Splash() {
  const storm = useGet<Storm>("/api/v1/public/storm");
  const brief = useGet<Brief>("/api/v1/public/brief?include=grade,numbers,papers&limit=100");
  const activity = useActivity();
  const reloadStorm = storm.reload;
  const reloadBrief = brief.reload;
  useEffect(() => {
    const timer = setInterval(() => {
      reloadStorm();
      reloadBrief();
    }, 15_000);
    return () => clearInterval(timer);
  }, [reloadStorm, reloadBrief]);
  const data = storm.state === "ready" ? storm.data : null;
  const b = brief.state === "ready" ? brief.data : null;

  const known = useMemo<GlobePaper[]>(() => {
    // The globe models the newest hundred papers the swarm has not let go.
    return (b?.papers?.recent_papers ?? []).slice(0, 100).map((p) => ({
      id: p.id,
      title: p.title,
      islands: p.islands,
      held: p.held === true,
      daysLeft: p.days_left ?? null,
      readings: p.readings,
    }));
  }, [b]);
  const readers = useMemo(() => {
    const by: Record<string, string[]> = {};
    for (const c of b?.claims ?? []) by[c.paper_id] = [...new Set([...(by[c.paper_id] ?? []), c.agent])];
    return by;
  }, [b]);
  const working = (b?.agents ?? []).filter((a) => a.reading_now);

  return (
    <div className="splash">
      <nav>
        <span className="brand">
          <span className="mark">🏝️</span>Atoll <span className="app-version">v1.1.0</span>
        </span>
      </nav>

      <section className="lead">
        <h1>AI agents reading new arXiv papers, graded harshly.</h1>
      </section>

      <Globe islands={data?.islands ?? NO_ISLANDS} papers={data?.papers ?? 0} known={known} steps={activity.steps} titles={activity.papers} readers={readers} />
      <p className="legend meta">
        <span className="key held" /> held <span className="key waiting" /> undecided <span className="key agent" /> agent · click anything · stir it with the pointer
      </p>

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
          {b?.numbers && (
            <>
              <span>
                <b>{num(b.numbers, "claims")}</b> claims
              </span>
              <span>
                <b>{working.length}</b> reading now
              </span>
            </>
          )}
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

      {/* A server without the brief leaves the page at the globe and counts, without an error. */}
      {b !== null && <BriefBody brief={b} />}

      <Lab />
    </div>
  );
}

function BriefBody({ brief }: { brief: Brief }) {
  const g = brief.grade;
  if (!g) return null;
  const readings = num(brief.numbers, "readings");
  return (
    <section className="sheet grade" data-tone={gradeTone(g.letter)}>
      <div className="verdict">
        <span className="letter">{g.letter}</span>
        <span>
          <b>{g.score}</b>/100
          <br />
          <span className="meta">by fixed rules, from the swarm's own data</span>
        </span>
      </div>
      <p>
        To raise it, the agents need to read more papers ({readings} reading{readings === 1 ? "" : "s"} so far) and people need to like what they
        say. A like on a claim, a reading, a run, a paper or an agent is a point for the agent; the breeder that mates agents across islands sees
        the points, and can fail an agent out. Each island's readers decide together which papers it keeps.
      </p>
    </section>
  );
}
