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

/** The newest steps, polled from the public feed. A server without the feed leaves it empty and says so. */
function useActivity(): { steps: ActivityStep[]; papers: Record<string, ActivityPaper>; state: "loading" | "live" | "absent" } {
  const api = useApi();
  const [steps, setSteps] = useState<ActivityStep[]>([]);
  const [papers, setPapers] = useState<Record<string, ActivityPaper>>({});
  const [state, setState] = useState<"loading" | "live" | "absent">("loading");
  useEffect(() => {
    let live = true;
    let after = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const read = () => {
      api.get<Activity>(`/api/v1/public/activity?after=${after}&limit=60`).then(
        (feed) => {
          if (!live) return;
          after = Math.max(after, feed.last_id);
          setState("live");
          if (feed.steps.length > 0) setSteps((had) => [...had, ...feed.steps].slice(-KEEP_STEPS));
          if (Object.keys(feed.papers).length > 0) setPapers((had) => ({ ...had, ...feed.papers }));
          timer = setTimeout(read, POLL_MS);
        },
        () => {
          if (!live) return;
          // An older server has no feed: the globe still turns, without boats. A feed that answered
          // before is asked again, more slowly.
          if (after === 0) setState("absent");
          else timer = setTimeout(read, POLL_MS * 3);
        },
      );
    };
    read();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [api]);
  return { steps, papers, state };
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
  const brief = useGet<Brief>("/api/v1/public/brief?limit=60");
  const activity = useActivity();
  const data = storm.state === "ready" ? storm.data : null;
  const b = brief.state === "ready" ? brief.data : null;

  const known = useMemo<GlobePaper[]>(() => {
    const held = (b?.papers?.held_papers ?? []).map((p) => ({ id: p.id, title: p.title, islands: p.islands, held: true, readings: p.readings }));
    const waiting = (b?.papers?.waiting_papers ?? []).map((p) => ({ id: p.id, title: p.title, islands: p.islands, held: false, daysLeft: p.days_left ?? null, readings: p.readings }));
    return [...held, ...waiting];
  }, [b]);
  const readers = useMemo(() => {
    const by: Record<string, string[]> = {};
    for (const c of b?.claims ?? []) by[c.paper_id] = [...new Set([...(by[c.paper_id] ?? []), c.agent])];
    return by;
  }, [b]);
  const working = (b?.agents ?? []).filter((a) => a.reading_now);
  const lastMinute = activity.steps.filter((s) => s.created_at * 1000 > Date.now() - 60_000).length;

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
        <span className="key held" /> held <span className="key waiting" /> undecided ⛵ agent · click anything ·{" "}
        {activity.state === "live"
          ? lastMinute > 0
            ? `live, ${lastMinute} steps/min`
            : activity.steps.length > 0
              ? "replaying recent steps"
              : "no steps yet"
          : activity.state === "absent"
            ? "no live feed"
            : "…"}
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

      {brief.state === "failed" && (
        <div className="box" role="alert">
          <b>The swarm's brief is not reachable right now.</b> {refusal(brief.error)}
        </div>
      )}
      {b !== null && <BriefBody brief={b} />}

      <Lab />
    </div>
  );
}

function BriefBody({ brief }: { brief: Brief }) {
  const g = brief.grade;
  const papers = brief.papers;
  return (
    <>
      {g && (
        <section className="sheet grade" data-tone={gradeTone(g.letter)}>
          <div className="verdict">
            <span className="letter">{g.letter}</span>
            <span>
              <b>{g.score}</b>/100
              {g.caps.length > 0 && (
                <ul className="caps">
                  {g.caps.map((c) => (
                    <li key={c.reason}>
                      ≤{c.ceiling}: {c.reason}
                    </li>
                  ))}
                </ul>
              )}
            </span>
          </div>
          <table className="crit">
            <tbody>
              {g.criteria.map((c) => (
                <tr key={c.criterion} title={c.evidence}>
                  <th>{c.criterion.replace(/_/g, " ")}</th>
                  <td className="bar">
                    <i style={{ width: `${c.score}%` }} data-low={c.score < 50 ? "" : undefined} />
                  </td>
                  <td className="num">{c.measured ? c.score : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {brief.claims && brief.claims.length > 0 && (
        <section className="sheet">
          <h2>Claims</h2>
          <ul className="claims">
            {brief.claims.slice(0, 8).map((c, k) => (
              <li key={`${c.reading_id}-${k}`}>
                <span className={c.verified ? "tag ok" : "tag refused"}>{c.verified ? "verified" : "unverified"}</span> {c.text}{" "}
                <a className="meta" href={`https://arxiv.org/abs/${encodeURIComponent(c.paper_id)}`} target="_blank" rel="noreferrer">
                  {c.paper_id}
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}

      {papers && (
        <section className="sheet two">
          <div>
            <h2>Held · {papers.held}</h2>
            <ul>
              {papers.held_papers.slice(0, 6).map((p) => (
                <li key={p.id} title={p.thesis ?? undefined}>
                  {p.title}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h2>Undecided · {papers.waiting}</h2>
            <ul>
              {papers.waiting_papers.slice(0, 6).map((p) => (
                <li key={p.id}>
                  {p.title} <span className="meta">{p.days_left ?? "?"}d</span>
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}
    </>
  );
}
