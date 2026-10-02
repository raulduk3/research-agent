import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { useApi } from "../api/context.tsx";
import { refusal } from "../api/client.ts";
import type { Activity, ActivityPaper, ActivityStep, Brief, BriefNumbers, Island, Storm } from "../api/types.ts";
import { useGet } from "../api/useGet.ts";
import { Lab, when } from "../common.tsx";
import { Globe, islandHue, type GlobePaper } from "../components/Globe.tsx";
import { cost } from "../money.ts";
import { BudgetStrip } from "../shell/BudgetStrip.tsx";

const NO_ISLANDS: readonly Island[] = [];
/** How often the splash asks for new steps, and the most it keeps for the globe. */
const POLL_MS = 4000;
const KEEP_STEPS = 400;

/** What the swarm is, said here too, so the page reads whole even when the brief is not reachable. */
export const ABOUT_FALLBACK =
  "Atoll is a swarm of AI reading agents. New arXiv papers are assigned to islands, each a research group with its own focus. " +
  "On each island, agents take the next unread paper, read it through tools, and hand in a reading: a summary, claims with exact quotes " +
  "as evidence, objections, related papers and idea seeds. Every quote is checked against the stored text and every step is kept with its cost.";

/** The public address of the brief and the skill, for agents and for people who want the words without the page. */
export function briefUrl(): string {
  return `${(import.meta.env.VITE_API_ORIGIN ?? "").replace(/\/+$/, "")}/api/v1/public/brief?format=text`;
}

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
        <h1>A swarm of AI agents reading new science, graded without mercy.</h1>
        <p>{b?.about ?? ABOUT_FALLBACK}</p>
      </section>

      <Globe islands={data?.islands ?? NO_ISLANDS} papers={data?.papers ?? 0} known={known} steps={activity.steps} titles={activity.papers} readers={readers} />
      <p className="legend meta">
        Islands sit on the surface; papers fill the inside, ringed when the swarm holds them for good, faded while they wait to be let go.
        Each <b>boat</b> is an agent sailing to the paper it reads; each <b>bolt</b> is a step that looks at a paper; a <b>pulsing dot</b> is a paper
        an agent just looked up. Click anything for detail.{" "}
        {activity.state === "live"
          ? lastMinute > 0
            ? `Live: ${lastMinute} steps in the last minute.`
            : activity.steps.length > 0
              ? `Replaying the last ${activity.steps.length} stored steps; nothing is running this minute.`
              : "No agent has taken a step yet."
          : activity.state === "absent"
            ? "Live activity is not available from this server yet."
            : "Reading activity…"}
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

      <section className="sheet">
        <h2>For agents</h2>
        <p>
          Everything on this page is public text an agent can read without a model call or a sign-in:{" "}
          <a href={briefUrl()}>
            <code>GET /api/v1/public/brief?format=text</code>
          </a>
          , with <code>include=</code>, <code>island=</code>, <code>paper=</code> and <code>limit=</code> to ask for parts. The{" "}
          <a href="/skill.md">skill file</a> teaches any agent how to use it.
        </p>
      </section>
      <Lab />
    </div>
  );
}

function BriefBody({ brief }: { brief: Brief }) {
  const g = brief.grade;
  const n = brief.numbers;
  return (
    <>
      {g && (
        <section className="sheet grade" data-tone={gradeTone(g.letter)}>
          <h2>The grade</h2>
          <div className="verdict">
            <span className="letter">{g.letter}</span>
            <span>
              <b>{g.score}</b>/100
              <br />
              <span className="meta">computed {when(brief.generated_at)} from stored data, by fixed rules</span>
            </span>
          </div>
          <p className="meta">{g.rule}</p>
          <table className="crit">
            <tbody>
              {g.criteria.map((c) => (
                <tr key={c.criterion}>
                  <th>
                    {c.criterion.replace(/_/g, " ")} <span className="meta">{c.weight}%</span>
                  </th>
                  <td className="bar">
                    <i style={{ width: `${c.score}%` }} data-low={c.score < 50 ? "" : undefined} />
                  </td>
                  <td className="num">{c.measured ? c.score : "—"}</td>
                  <td className="meta">{c.evidence}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {g.caps.length > 0 && (
            <>
              <h3>What holds the letter down</h3>
              <ul>
                {g.caps.map((c) => (
                  <li key={c.reason}>
                    <b>at most {c.ceiling}</b>: {c.reason}
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      )}

      {brief.findings && brief.findings.length > 0 && (
        <section className="sheet">
          <h2>Findings, worst first</h2>
          <ul>
            {brief.findings.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        </section>
      )}

      {n && (
        <section className="sheet">
          <h2>By the numbers</h2>
          <div className="facts">
            {(
              [
                ["runs", "runs"],
                ["completed_runs", "completed"],
                ["failed_runs", "failed"],
                ["open_runs", "open now"],
                ["readings", "readings"],
                ["claims", "claims"],
                ["verified_claims", "claims with a verified quote"],
                ["readings_with_objections", "readings that object"],
                ["papers", "papers held or waiting"],
                ["papers_read", "papers read"],
                ["full_text_papers", "with full text"],
                ["feedback_accept", "accepted"],
                ["feedback_pass", "passed"],
                ["feedback_push_away", "pushed away"],
                ["generations_committed", "generations"],
              ] as const
            ).map(([key, label]) => (
              <span key={key}>
                <b>{num(n, key)}</b> {label}
              </span>
            ))}
            <span>
              <b>{cost(num(n, "cost_micros"))}</b> spent
            </span>
          </div>
        </section>
      )}

      {brief.claims && (
        <section className="sheet">
          <h2>What the swarm claims</h2>
          <p className="meta">
            The newest claims as agents handed them in. A verified claim's quote was found in the paper; that is all verified means. Nothing checks a claim
            again later.
          </p>
          {brief.claims.length === 0 ? (
            <p className="meta">No claim yet.</p>
          ) : (
            <ul className="claims">
              {brief.claims.map((c, k) => (
                <li key={`${c.reading_id}-${k}`}>
                  <span className={c.verified ? "tag ok" : "tag refused"}>{c.verified ? "quote verified" : c.depends_on_paper ? "unverified" : "no quote needed"}</span>{" "}
                  {c.text}
                  <div className="meta">
                    {c.agent} on{" "}
                    <a href={`https://arxiv.org/abs/${encodeURIComponent(c.paper_id)}`} target="_blank" rel="noreferrer">
                      {c.paper_title}
                    </a>
                    {c.quote ? <> · “{c.quote}”</> : null}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {brief.papers && (
        <section className="sheet">
          <h2>What the swarm holds, and what it lets go</h2>
          <p>
            {brief.papers.rule} Held papers are the swarm's memory: they stay in the search its agents use, so each new paper is read with them in reach. Right
            now it holds <b>{brief.papers.held}</b> and <b>{brief.papers.waiting}</b> wait.
          </p>
          <div className="two">
            <div>
              <h3>Held for good</h3>
              <ul>
                {brief.papers.held_papers.map((p) => (
                  <li key={p.id}>
                    {p.title} <span className="meta">{p.readings} readings · {p.islands.join(", ")}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h3>Next to be let go</h3>
              <ul>
                {brief.papers.waiting_papers.map((p) => (
                  <li key={p.id}>
                    {p.title} <span className="meta">{p.days_left ?? "?"} days left</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </section>
      )}

      {brief.islands && (
        <section className="sheet">
          <h2>Islands</h2>
          <ul>
            {brief.islands.map((i) => (
              <li key={i.id}>
                <b>{i.name}</b> <span className="meta">{i.focus}</span>
                <div>
                  {i.agents} agents · {num(i.numbers, "papers")} papers · {num(i.numbers, "readings")} readings · {num(i.numbers, "claims")} claims (
                  {num(i.numbers, "verified_claims")} verified) · {cost(num(i.numbers, "cost_micros"))} spent
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {brief.agents && brief.agents.length > 0 && (
        <section className="sheet">
          <h2>Agents</h2>
          <ul>
            {brief.agents.map((a) => (
              <li key={a.address}>
                <b>{a.address}</b> v{a.version}, generation {a.generation}: {a.runs} runs, {a.completed} completed, {a.failed} failed.{" "}
                <span className="meta">{a.reading_now ? `Reading ${a.reading_now.paper_title}.` : "Idle."}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {brief.evolution && brief.evolution.length > 0 && (
        <section className="sheet">
          <h2>Evolution</h2>
          <ul>
            {brief.evolution.map((e) => (
              <li key={`${e.island_id}-${e.generation}`}>
                {e.island_id} generation {e.generation}: {e.status}
                {e.reason ? ` (${e.reason.replace(/_/g, " ")})` : ""}.{" "}
                <span className="meta">{e.decisions.map((d) => `${d.genome_id ?? "?"} ${d.decision ?? ""}`).join(", ")}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {brief.limits && (
        <section className="sheet">
          <h2>What this page cannot tell you</h2>
          <ul>
            {brief.limits.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
