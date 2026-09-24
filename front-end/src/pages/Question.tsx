import { useState, type MouseEvent } from "react";
import { Link, useParams } from "react-router";
import type { OwnerQuestion } from "../api/schema.gen.ts";
import { useGet } from "../api/useGet.ts";
import { ChanceBar } from "../graphics/ChanceBar.tsx";
import { Ids, Lead, ready, Replay, UNSERVED, when } from "./common.tsx";

/** The mock's tabs (design-mock/question-Q1.html), one panel each, in order. */
const TABS = [
  ["question", "Question"],
  ["conversation", "Conversation"],
  ["reads", "Reads"],
  ["analyst", "Analyst"],
  ["life", "Life"],
] as const;

type Tab = (typeof TABS)[number][0];

/** The tabs a rater's call opens in the mock. An owner session has no call and reads them all. */
const LOCKED: ReadonlySet<Tab> = new Set(["conversation", "reads", "analyst"]);

/**
 * One question (design-mock/question-Q1.html) from /api/v1/questions/{question_id}: the runs that
 * submitted a chance on it and its current resolutions, in the mock's five panels. The mock is a
 * rater's page; the rater's call form, the paper (its guide, parts map, PDF and page), the evidence,
 * the analyst, the baselines, the authors and the replay have no /api/v1 route for a question and
 * render empty (docs/implementation/front-end.md).
 */
export function Question() {
  const { questionId = "" } = useParams();
  const [tab, setTab] = useState<Tab>("question");
  const question = useGet<OwnerQuestion>(`/api/v1/questions/${encodeURIComponent(questionId)}`);
  const q = ready(question);
  const runs = q?.runs.items ?? [];
  const resolutions = q?.resolutions.items ?? [];
  const count = (status: string) => resolutions.filter((r) => r.status === status).length;

  const go = (to: Tab) => (e: MouseEvent) => {
    e.preventDefault();
    setTab(to);
  };
  const step = (to: Tab, label: string, forward: boolean) => (
    <a className={forward ? "go" : undefined} href={`#${to}`} onClick={go(to)}>
      {forward ? `${label} →` : `← ${label}`}
    </a>
  );

  return (
    <>
      <div className="meta">
        <Link to="/questions">← questions</Link>
      </div>
      <h1>{q ? `${q.resolver_id} v${q.resolver_version}` : `Question ${questionId.slice(0, 8)}`}</h1>
      <Lead
        reads={[question]}
        tail={
          <>
            {" "}
            · <a>the paper: {UNSERVED}</a>
          </>
        }
      >
        {() => q && `judged ${when(q.horizon)} · ${q.sheets} sheets · ${runs.length} runs submitted a chance`}
      </Lead>
      <nav className="seg" role="tablist" aria-label="this question">
        {TABS.map(([id, label]) => (
          <a
            key={id}
            className={LOCKED.has(id) ? "locked" : undefined}
            href={`#${id}`}
            role="tab"
            aria-selected={tab === id}
            onClick={go(id)}
          >
            {label}
          </a>
        ))}
      </nav>
      <section className="panel" id="question" role="tabpanel" hidden={tab !== "question"}>
        <h2>The call</h2>
        <div className="cue lockcue">
          A rater&apos;s call opens the conversation, the reads and the analyst; an owner reads them all. The
          rater&apos;s call: {UNSERVED}.
        </div>
        <h3>The paper</h3>
        <div className="pm">
          <div className="secs">Parts map: {UNSERVED}.</div>
          <div className="pgs" />
        </div>
        <div className="rp-pdf">
          <div className="rp-cap">
            <b>The paper</b> · <a>the PDF: {UNSERVED}</a>
          </div>
          <iframe title="the paper" />
        </div>
        <p className="meta">
          <a>The paper&apos;s own page: {UNSERVED}</a>
        </p>
        <div className="stepbar">
          <span />
          {step("life", "its life", true)}
        </div>
      </section>
      <section className="panel" id="conversation" role="tabpanel" hidden={tab !== "conversation"}>
        <h2>The conversation</h2>
        <div className="cue">
          {runs.length === 0
            ? "No run submitted a chance."
            : "Each run that submitted a chance, in the order it was accepted. Open one to watch its read."}
        </div>
        <div className="thread">
          {runs.map((r) => (
            <div className="turn" key={r.run_id}>
              <span className="who">
                <Link to={`/agents/${r.configuration_id}`}>{r.configuration_id.slice(0, 8)}</Link>
              </span>
              <span className="say">
                <ChanceBar p={r.probability} /> · accepted {when(r.accepted_at)}
              </span>
              <Link className="watch" to={`/runs/${r.run_id}/trace`}>
                ▶ watch this read
              </Link>
            </div>
          ))}
        </div>
        <div className="stepbar">
          {step("question", "the call", false)}
          {step("reads", "the reads", true)}
        </div>
      </section>
      <section className="panel" id="reads" role="tabpanel" hidden={tab !== "reads"}>
        <h2>The reads</h2>
        <div className="cue">Each read is a recorded run.</div>
        <div className="reads">
          {runs.map((r, i) => (
            <Link className="readtile" key={r.run_id} to={`/runs/${r.run_id}`}>
              <b>read {i + 1}</b>
              <span>{r.configuration_id.slice(0, 8)}</span>
              <span className="meta">open the run →</span>
            </Link>
          ))}
        </div>
        <h3>What they pointed at</h3>
        <div className="meta">The evidence the reads cited.</div>
        <div className="tw">
          <table>
            <tbody>
              <tr>
                <th>Evidence</th>
                <th>Cited by</th>
              </tr>
              <tr>
                <td colSpan={2}>{UNSERVED}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div className="stepbar">
          {step("conversation", "the conversation", false)}
          {step("analyst", "the analyst", true)}
        </div>
      </section>
      <section className="panel" id="analyst" role="tabpanel" hidden={tab !== "analyst"}>
        <h2>What the analyst said</h2>
        <div className="reading">The summarizer&apos;s reading: {UNSERVED}.</div>
        <div className="meta">A fixed summarizer writes this from the readers&apos; recorded forecasts and notes.</div>
        <h3>Against simple baselines</h3>
        <div className="meta">The same question answered without reading.</div>
        <div className="tw">
          <table>
            <tbody>
              <tr>
                <th>Baseline</th>
                <th>Chance, 0 to 1</th>
              </tr>
              <tr>
                <td colSpan={2}>{UNSERVED}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <details className="adv">
          <summary>More: the authors, the content assessment</summary>
          <h3>Authors&apos; prior citations, at the time</h3>
          <div className="tw">
            <table>
              <tbody>
                <tr>
                  <th>Author</th>
                  <th>Prior citations</th>
                </tr>
                <tr>
                  <td colSpan={2}>{UNSERVED}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <h3>Paper-content assessment</h3>
          <div className="meta">The outside assessment: {UNSERVED}.</div>
        </details>
        <div className="stepbar">
          {step("reads", "the reads", false)}
          {step("life", "its life", true)}
        </div>
      </section>
      <section className="panel" id="life" role="tabpanel" hidden={tab !== "life"}>
        <h2>Its life</h2>
        <div className="meta">
          {q === null
            ? `Resolutions: ${UNSERVED}.`
            : resolutions.length === 0
              ? `Nothing resolved yet; judged at ${when(q.horizon)}.`
              : `${count("true")} true · ${count("false")} false · ${count("unresolvable")} unresolvable · resolved ${when(
                  resolutions
                    .map((r) => r.resolved_at)
                    .sort()
                    .at(-1),
                )}`}{" "}
          Its hour by hour: {UNSERVED}.
        </div>
        <Replay cue={false} />
        <div className="explore">
          <Link to="/questions">all questions →</Link>
          <Link to="/">owner home →</Link>
        </div>
        <p className="meta">
          Every day this paper was read or mentioned: <a>the paper&apos;s life: {UNSERVED}</a>
        </p>
        <div className="stepbar">{step("analyst", "the analyst", false)}</div>
      </section>
      <Ids
        rows={[
          ["question", q?.question_id ?? questionId],
          ["target definition", q?.target_definition_hash],
          ...resolutions.map(
            (r) =>
              [`forecast ${r.forecast_id.slice(0, 8)} · ${r.status} v${r.resolution_version}`, r.forecast_id] as const,
          ),
        ]}
      />
    </>
  );
}
