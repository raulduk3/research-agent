import { describe, expect, test } from "vitest";
import { budgetLine, budgetState, usd } from "./money.ts";

const MID_MONTH = new Date(Date.UTC(2026, 9, 11, 0, 0, 0));

describe("the budget line", () => {
  test("states the server's month, projection and mode as sent", () => {
    const state = budgetState({ month_to_date_micros: 12_400_000, projected_month_micros: 38_000_000, mode: "normal" }, MID_MONTH);
    expect(budgetLine(state)).toBe("$12.40 / $50 month · projected $38 · normal");
    expect(state.estimated).toBe(false);
  });

  test("reads the server's own spelling of a mode", () => {
    expect(budgetState({ month_to_date_micros: 1, projected_month_micros: 1, mode: "hard_stop" }, MID_MONTH).mode).toBe("hard stop");
    expect(budgetState({ month_to_date_micros: 1, projected_month_micros: 1, mode: "stored_data_only" }, MID_MONTH).mode).toBe("stored-data only");
  });

  test("with only the month so far, carries the daily rate forward and is conserving once that passes the target", () => {
    // 10 days gone of 31: 41.20 so far projects to 127.72.
    const state = budgetState({ month_to_date_micros: 41_200_000 }, MID_MONTH);
    expect(budgetLine(state)).toBe("$41.20 / $50 month · projected $128 · conserving");
    expect(state.estimated).toBe(true);
  });

  test("is a hard stop once the month has reached its target, and normal while the projection stays under it", () => {
    expect(budgetState({ month_to_date_micros: 50_000_000 }, MID_MONTH).mode).toBe("hard stop");
    expect(budgetState({ month_to_date_micros: 10_000_000 }, MID_MONTH).mode).toBe("normal");
  });

  test("estimates nothing when the server reports no month figure", () => {
    const state = budgetState(undefined, MID_MONTH);
    expect(state).toMatchObject({ monthToDate: null, projected: null, mode: null, estimated: false });
    expect(budgetLine(state)).toBe("$50 month target · projection not reported · mode not reported");
  });
});

describe("a cost in dollars", () => {
  test("keeps a small run from reading as zero", () => {
    expect(usd(2000)).toBe("$0.002");
    expect(usd(41_000)).toBe("$0.041");
    expect(usd(100_000)).toBe("$0.10");
    expect(usd(12_400_000)).toBe("$12.40");
    expect(usd(0)).toBe("$0.00");
  });
});
