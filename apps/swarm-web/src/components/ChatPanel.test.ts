import { expect, test } from "vitest";
import { answerCost } from "./ChatPanel.tsx";

test("an answer's cost is the figure the server sent for that answer", () => {
  expect(answerCost({ answer: "a", cost_micros: 4000 })).toBe("$0.004 this answer");
  expect(answerCost({ answer: "a", cost_micros: 0 })).toBe("from stored records");
});

test("an answer without a cost figure is not called free", () => {
  expect(answerCost({ answer: "a" })).toBe("answer cost not reported");
});
