import { Link } from "react-router";
import type { OwnerImpact } from "../api/schema.gen.ts";
import { useGet } from "../api/useGet.ts";
import { ChanceBar } from "../graphics/ChanceBar.tsx";
import { Ids, Lead, ready, UNSERVED } from "./common.tsx";

type Row = OwnerImpact["impact"]["items"][number];

const COUNTS = ["ratings", "likes", "dislikes", "skips", "credits", "genomes_credited", "credit_gaps"] as const;

/** The latest ISO week with a stored rating, its rows summed over islands. */
function latestWeek(rows: readonly Row[]) {
  const week = rows
    .map((r) => r.iso_week)
    .sort()
    .at(-1);
  if (week === undefined) return null;
  const these = rows.filter((r) => r.iso_week === week);
  const sum = Object.fromEntries(COUNTS.map((k) => [k, these.reduce((n, r) => n + r[k], 0)])) as Record<
    (typeof COUNTS)[number],
    number
  >;
  return { week, islands: these.map((r) => r.island), ...sum };
}

/**
 * What the ratings did (design-mock/impact.html) from /api/v1/impact: the latest rating week's
 * calls by value, the credit rows they wrote, the genomes credited and the credit gaps, summed over
 * islands. The mock is a rater's page; an owner session carries no rater id, so these are every
 * rater's calls. The agents-against-controls comparison, the sealed forecasts and the uncalled
 * papers are not served (docs/implementation/front-end.md).
 */
export function Impact() {
  const impact = useGet<OwnerImpact>("/api/v1/impact");
  const rows = ready(impact)?.impact.items ?? [];
  const w = latestWeek(rows);

  return (
    <>
      <h1>Impact</h1>
      <Lead reads={[impact]}>
        {() =>
          w === null
            ? "No rating stored yet."
            : `What the raters' calls did in ${w.week}, summed over ${w.islands.join(", ")}, and what they set in motion.`
        }
      </Lead>
      <ul className="facts">
        <li>
          {w === null
            ? `Calls: ${impact.state === "ready" ? "none stored" : UNSERVED}.`
            : `In ${w.week} raters made ${w.ratings} calls: ${w.likes} liked, ${w.dislikes} disliked, ${w.skips} skipped.`}
        </li>
        <li>
          {w === null
            ? `Credit: ${impact.state === "ready" ? "none written" : UNSERVED}.`
            : `They wrote ${w.credits} credit rows to ${w.genomes_credited} genomes, with ${w.credit_gaps} credit gaps.`}{" "}
          Accepted at a rate of <ChanceBar p={w && w.ratings > 0 ? w.likes / w.ratings : null} />; against hidden random
          controls: {UNSERVED}.
        </li>
        <li>
          Forecasts a rater sealed: {UNSERVED}. <Link to="/reports">The weekly reports</Link>.
        </li>
      </ul>
      <h2>What one call sets in motion</h2>
      <ol className="chain">
        <li className="you">
          <b>A rater accepts or passes.</b> Only the sign reaches the agents, never the words.
        </li>
        <li className="now">
          <b>The credit is shared among the agents that picked the paper.</b> A hidden random control or a service pick
          credits nobody.
        </li>
        <li className="now">
          <b>The island ranks its agents by credit each week.</b> The ranking and the island&apos;s share of the budget
          decide how many agents stay.
        </li>
        <li className="later">
          <b>Next week&apos;s picks come from the agents that stayed.</b>
        </li>
        <li className="later">
          <b>The truth arrives at each question&apos;s horizon.</b> From then on agents are ranked by how right they
          were.
        </li>
      </ol>
      <div className="meta">Papers left uncalled by the next digest: {UNSERVED}.</div>
      <h2>Where a call cannot reach</h2>
      <div className="box">
        A call never touches a forecast score, cannot see which papers were random controls, and cannot name or move a
        single agent; only the weekly ranking does that.
      </div>
      <h2>Change a call</h2>
      <div className="meta">A call cannot be changed once sent; it is on record.</div>
      <Ids rows={[]} />
    </>
  );
}
