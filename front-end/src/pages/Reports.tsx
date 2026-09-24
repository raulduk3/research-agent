import { Link } from "react-router";
import type { OwnerReports } from "../api/schema.gen.ts";
import { useGet } from "../api/useGet.ts";
import { ISLANDS } from "./Agents.tsx";
import { Ids, Lead, ready, UNSERVED } from "./common.tsx";

type Week = OwnerReports["reports"]["items"][number];

/** An ISO week (`2026-W40`) as the mock writes it: `W40 · 2026-09-28 to 10-04`, Monday to Sunday. */
export function weekSpan(isoWeek: string): string {
  const m = /^(\d{4})-W(\d{2})$/.exec(isoWeek);
  if (!m) return isoWeek;
  const jan4 = Date.UTC(Number(m[1]), 0, 4);
  const monday = jan4 - ((new Date(jan4).getUTCDay() + 6) % 7) * 86_400_000 + (Number(m[2]) - 1) * 7 * 86_400_000;
  const day = (t: number) => new Date(t).toISOString().slice(0, 10);
  return `W${m[2]} · ${day(monday)} to ${day(monday + 6 * 86_400_000).slice(5)}`;
}

function order(a: Week, b: Week): number {
  const rank = (i: string) => {
    const n = (ISLANDS as readonly string[]).indexOf(i);
    return n < 0 ? ISLANDS.length : n;
  };
  return b.iso_week.localeCompare(a.iso_week) || rank(a.island) - rank(b.island) || a.island.localeCompare(b.island);
}

/**
 * The reports index (design-mock/reports.html), one row per island and ISO week from
 * /api/v1/reports, newest first, each opening its report. A report is built on request, so its
 * state, headline and selection are not stored and the State column gives the week's stored
 * records instead; the headline and selection render "not served yet" (docs/implementation/front-end.md).
 */
export function Reports() {
  const reports = useGet<OwnerReports>("/api/v1/reports");
  const items = ready(reports)?.reports.items;
  const weeks = [...(items ?? [])].sort(order);

  return (
    <>
      <h1>Reports</h1>
      <Lead reads={[reports]}>
        {() =>
          `One report per island per week, built from the record when it is opened. ${weeks.length} island weeks hold a stored digest or rating. Newest first.`
        }
      </Lead>
      <div className="tw">
        <table className="wide">
          <tbody>
            <tr>
              <th>Week</th>
              <th>Island</th>
              <th>State</th>
              <th>Headline</th>
              <th>Selection</th>
            </tr>
            {weeks.map((w) => (
              <tr key={`${w.iso_week}/${w.island}`}>
                <td>
                  <Link to={`/reports/${w.island}/${w.iso_week}`}>{weekSpan(w.iso_week)}</Link>
                </td>
                <td>{w.island}</td>
                <td>{`${w.digests} digests · ${w.entries} entries · ${w.ratings} ratings · ${w.credits} credits`}</td>
                <td>
                  <span className="na">{UNSERVED}</span>
                </td>
                <td>
                  <span className="na">{UNSERVED}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Ids rows={[]} />
    </>
  );
}
