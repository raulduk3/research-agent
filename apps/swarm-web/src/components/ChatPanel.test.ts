import { expect, test } from "vitest";
import { answerCost } from "./ChatPanel.tsx";

test("an answer's cost is only what the server reported about that answer", () => {
  expect(answerCost({ answer: "a", answer_cost_micros: 4000 })).toBe("$0.004 this answer");
  expect(answerCost({ answer: "a", stored_data_only: true })).toBe("stored-data only");
  expect(answerCost({ answer: "a", answer_cost_micros: 0 })).toBe("$0.00 this answer");
});

test("a running total sent in another field is not read as the answer's cost, nor its absence as free", () => {
  const sentToday = { answer: "a", links: [], cost_micros: 12_000 };
  expect(answerCost(sentToday)).toBe("answer cost not reported");
});
