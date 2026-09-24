import { Link } from "react-router";
import type { OwnerQuestions } from "../api/schema.gen.ts";
import { useGet } from "../api/useGet.ts";
import { Ids, Lead, ready, when } from "./common.tsx";

type Question = OwnerQuestions["questions"]["items"][number];

function resolved(q: Question): number {
  return q.resolved_true + q.resolved_false + q.unresolvable;
}

function name(q: Question): string {
  return `${q.resolver_id} v${q.resolver_version}`;
}

function Card({ q, open }: { q: Question; open: boolean }) {
  return (
    <div className={open ? "feed ask" : "feed done"}>
      <div className="ttl">
        <Link to={`/questions/${q.question_id}`}>{name(q)}</Link>
      </div>
      <div className={open ? "abs" : "meta"}>
        {`judged ${when(q.horizon)} · ${q.sheets} sheets · ${q.runs} runs · ${q.submissions} submissions`}
      </div>
      <div className="state small">
        {open
          ? "open · nothing resolved yet"
          : `${q.resolved_true} true · ${q.resolved_false} false · ${q.unresolvable} unresolvable · resolved ${when(q.last_resolved_at)}`}
      </div>
    </div>
  );
}

/**
 * The questions index (design-mock/questions.html) from /api/v1/questions: each question a sealed
 * sheet holds, open ones first, then the resolved ones in the fold. The mock is a rater's own
 * calls; an owner session carries no rater id and the question's paper is inside its card
 * artifact, so a question is named by its resolver and the calls are not served
 * (docs/implementation/front-end.md).
 */
export function Questions() {
  const questions = useGet<OwnerQuestions>("/api/v1/questions");
  const items = ready(questions)?.questions.items ?? [];
  const open = items.filter((q) => resolved(q) === 0);
  const done = items.filter((q) => resolved(q) > 0);

  return (
    <>
      <div className="meta">
        <Link to="/">← owner home</Link>
      </div>
      <h1>Questions</h1>
      <Lead reads={[questions]}>
        {() => "Each question a sealed sheet holds, with its runs, submissions and current resolutions."}
      </Lead>
      <div className="sec">
        <h2>All questions</h2>
        <span>{`${items.length} asked · ${done.length} resolved · ${open.length} open`}</span>
      </div>
      <div className="cue">↓ open questions first · resolved ones in the fold · judged at their horizon</div>
      {open.map((q) => (
        <Card key={q.question_id} q={q} open />
      ))}
      <details className="adv">
        <summary>{`resolved · ${done.length}`}</summary>
        {done.map((q) => (
          <Card key={q.question_id} q={q} open={false} />
        ))}
      </details>
      <Ids
        rows={items.flatMap((q) => [
          [`question: ${name(q)} · ${q.question_id.slice(0, 8)}`, q.question_id] as const,
          [`target definition: ${q.question_id.slice(0, 8)}`, q.target_definition_hash] as const,
        ])}
      />
    </>
  );
}
