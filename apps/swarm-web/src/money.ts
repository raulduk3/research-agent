import type { Budget, BudgetMode, Micros } from "./api/types.ts";

/** The month's budget target when the server names none: 50 US dollars. */
export const MONTH_TARGET_MICROS: Micros = 50_000_000;

const MICROS_PER_DOLLAR = 1_000_000;

/** A cost in dollars: cents from a dollar up, and up to four decimals below it so a small run is not shown as zero. */
export function usd(micros: Micros): string {
  const dollars = micros / MICROS_PER_DOLLAR;
  if (Math.abs(dollars) >= 1 || dollars === 0) return `$${dollars.toFixed(2)}`;
  const fine = dollars.toFixed(4).replace(/0{1,2}$/, "");
  return `$${fine}`;
}

/** A cost in whole dollars, for a target or a projection. */
export function usdRound(micros: Micros): string {
  return `$${Math.round(micros / MICROS_PER_DOLLAR)}`;
}

/** A cost the server may not have sent: the amount, or the words that it was not reported. */
export function cost(micros: Micros | null | undefined): string {
  return typeof micros === "number" ? usd(micros) : "not reported";
}

const MODES: Record<string, BudgetMode> = {
  normal: "normal",
  conserving: "conserving",
  "hard stop": "hard stop",
  "stored-data only": "stored-data only",
};

function readMode(mode: string | null | undefined): BudgetMode | null {
  if (typeof mode !== "string") return null;
  const key = mode.toLowerCase().replace(/_/g, " ").replace("stored data only", "stored-data only");
  return MODES[key] ?? null;
}

export interface BudgetState {
  target: Micros;
  monthToDate: Micros | null;
  projected: Micros | null;
  mode: BudgetMode | null;
  /** True when the projection or the mode was worked out here from the month-to-date figure. */
  estimated: boolean;
}

/** The month's cost so far carried forward at the same daily rate to the month's end (UTC). */
export function projectMonth(monthToDate: Micros, now: Date): Micros {
  const days = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 0)).getUTCDate();
  const elapsed = Math.max(1, now.getUTCDate() - 1 + now.getUTCHours() / 24);
  return Math.round((monthToDate / elapsed) * days);
}

/**
 * The budget as the strip states it. The server's projection and mode are used as sent. With only
 * a month-to-date figure the projection is the daily rate carried forward, and the mode follows
 * it: at or over the target is a hard stop, a projection over the target is conserving. Without a
 * month-to-date figure nothing is estimated.
 */
export function budgetState(budget: Budget | null | undefined, now: Date): BudgetState {
  const target = typeof budget?.target_micros === "number" ? budget.target_micros : MONTH_TARGET_MICROS;
  const monthToDate = typeof budget?.month_to_date_micros === "number" ? budget.month_to_date_micros : null;
  const sentProjection = typeof budget?.projected_month_micros === "number" ? budget.projected_month_micros : null;
  const sentMode = readMode(budget?.mode);
  if (monthToDate === null) return { target, monthToDate, projected: sentProjection, mode: sentMode, estimated: false };
  const projected = sentProjection ?? projectMonth(monthToDate, now);
  const mode = sentMode ?? (monthToDate >= target ? "hard stop" : projected > target ? "conserving" : "normal");
  return { target, monthToDate, projected, mode, estimated: sentProjection === null || sentMode === null };
}

/** "$12.40 / $50 month · projected $38 · normal", naming what the server did not report. */
export function budgetLine(state: BudgetState): string {
  const parts = [state.monthToDate === null ? `${usdRound(state.target)} month target` : `${usd(state.monthToDate)} / ${usdRound(state.target)} month`];
  parts.push(state.projected !== null ? `projected ${usdRound(state.projected)}` : "projection not reported");
  parts.push(state.mode ?? "mode not reported");
  return parts.join(" · ");
}

/** A share of the month's target as a whole percent. */
export function share(fraction: number): string {
  return `${Math.round(fraction * 100)}%`;
}
