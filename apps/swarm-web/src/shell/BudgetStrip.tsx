import { refusal } from "../api/client.ts";
import type { Storm } from "../api/types.ts";
import type { Loaded } from "../api/useGet.ts";
import { budgetLine, budgetState, usd } from "../money.ts";

/**
 * The month's cost against its target on one line, on every page. It states what the server
 * reported; a figure the server did not send is named as not reported rather than shown as zero.
 */
export function BudgetStrip({ storm, now = new Date() }: { storm: Loaded<Storm>; now?: Date }) {
  if (storm.state === "loading") return <div className="budget">month budget · reading…</div>;
  if (storm.state === "failed") {
    return (
      <div className="budget" role="status">
        month budget not available · {refusal(storm.error)}
      </div>
    );
  }
  const state = budgetState(storm.data.budget, now);
  const filled = state.monthToDate === null ? 0 : Math.min(1, state.monthToDate / state.target);
  return (
    <div className="budget" role="status" data-mode={state.mode ?? "unknown"}>
      <span className="gauge" aria-hidden="true">
        <i style={{ width: `${filled * 100}%` }} />
      </span>
      {state.monthToDate === null && <b>{usd(storm.data.cost_micros)} recorded in all</b>}
      {state.monthToDate === null ? <span>{budgetLine(state)}</span> : <b>{budgetLine(state)}</b>}
      {state.estimated && <span>estimated from the month so far</span>}
      {storm.data.budget?.runs_allowed === false && (
        <span>no new runs{storm.data.budget.runs_refusal ? `: ${storm.data.budget.runs_refusal.replace(/_/g, " ")}` : ""}</span>
      )}
    </div>
  );
}
