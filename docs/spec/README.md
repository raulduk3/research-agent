# The specification

Two documents state what the software is and how it is built. Nothing else in the repository overrides them; where code and a document disagree, one of them is wrong and the fix says which.

- [SDD.md](SDD.md), the Software Design Description: what the software must do, as requirements a reader can verify, with the operating values the requirements rest on in three appendices.
- [TDD.md](TDD.md), the Technical Design Description: how each requirement is met, one item per requirement naming the code path, the symbol and the tests that carry it, followed by the exact record, route, storage and operations contracts.
- [SPEC-AMENDMENTS.md](SPEC-AMENDMENTS.md), the amendment ledger: one row per merged change to either document, newest last, naming the items that changed, the decision behind them and the pull request.

## How to read them

Every SDD requirement is one sentence on a line that begins with its id, such as `**EN-01.**`, holding one obligation with `must` or `must not`. The trace comment on the next line names its TDD item and its status: `implemented`, `pending:#issue` for a decided requirement whose work issue is still open, or `deviation:#issue` for a requirement the code does not yet meet, citing the work issue that repairs it. The five bullets under it fix the trigger, the behavior, what is observable, what happens on failure and the test that would catch the wrong implementation; a sixth, `Limits`, carries the numbers and names any value that is still open, by issue number.

The appendices are part of the contract. Appendix A, the launch profile, fixes the operating values the requirements cite: hosts, budgets, models, schemas, samples, thresholds and gates. Appendix B, the learning protocol, owns the three citation targets and how the prediction heads are fitted. Appendix C, the retrieval protocol, owns passages and search. A requirement that says "under Appendix A" makes those values part of itself.

Each TDD item is a heading such as `#### TDD-3.1.13`, with a trace comment naming the requirement it implements, `code: path#Symbol`, `tests: path` and the same status as its requirement. Its paragraph states the algorithm, the failure handling and the test that detects the prohibited alternative. The catalog sections after the items are normative too: closed records, every field required, unions by literal discriminator, exact routes and transaction order.

The Terms table near the top of the SDD fixes the meaning of project-specific words in both documents. Ids are never renumbered; a gap in the numbering is an id reserved by a note that cites the issue holding it.

## How a change enters

1. A decision issue on GitHub, labeled `decision`, with Context, Options, Consequences, Recommendation and Question. The owner accepts an option in a comment. No requirement changes before that comment exists.
2. One branch from `develop`, one pull request, that edits the exact lines of the SDD and TDD, adds a decision record under [`../decisions/`](../decisions/) from its template, appends one row to the amendment ledger, and updates the root README where it describes what changed. The pull request description follows the repository template.
3. The author merges once the check passes. The ledger row and the record are what make the change findable and revertible later.

Project status, plans, ordering and evidence never enter the documents. They live in the GitHub issues, in [`../implementation/`](../implementation/) and in [`../evidence/`](../evidence/); the trace status is the only implementation state the documents record. New requirement candidates are filed as issues labeled `incoming`; [`../incoming.html`](../incoming.html) is locked until the first release.

## The one command

```bash
bin/check --since develop
```

It runs the strict specification checks (trace comments, one-to-one pairing, cross references, reserved ids, requirement shape, and that every requirement changed since `develop` has a ledger row), the checker's own self-test, and then the locked lint, format, type and test suites of the application. `bin/spec-check --strict --issues` also asks GitHub that every cited issue exists and that no deviation cites a closed one. `bin/progress --issues` prints how much of the TDD exists on disk, by chapter, with the milestone's issue tree.
