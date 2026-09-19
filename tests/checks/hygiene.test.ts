import { expect, test } from "bun:test";
import { checkCommitMessage } from "../../scripts/checks/hygiene.ts";

test("a counterexample commit subject is rejected", () => {
  expect(checkCommitMessage("abcdef0", "Add the thing").map((f) => f.code)).toEqual([
    "subject-format",
  ]);
  expect(checkCommitMessage("abcdef0", "feat(x): add the thing")).toEqual([]);
});
