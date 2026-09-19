# 0001. Adopt the 2026-09-19 candidates as the baseline SDD

- Status: accepted
- Date: 2026-09-19
- Issue: #5
- Spec: SDD sections 1 to 8, SDD-SR-01 to SDD-FT-16, 164 requirements. The TDD is unchanged.
- Pull requests: pending

## Context

`docs/spec/SDD.md` held no requirements. `docs/incoming.html` held the candidates distilled from the owner's notes of 2026-09-19: the design by layer, the standing rules, how fitting and training connect the layers, and the platform the system runs on. Candidate C-2026-09-19-22 asked whether the proposed and carried-forward candidates were accepted one by one, as a set, or not at all.

## Decision

The requirement candidates C-2026-09-19-1 to C-2026-09-19-163 and the platform candidates C-2026-09-19-170 to C-2026-09-19-188 are accepted as a set and written into the SDD as its baseline. The questions among them are not requirements and stay out.

The baseline is scoped to the smallest system that still studies what the project studies: one host, one corpus, one population of one agent design, two raters, private output. Each requirement states the smallest behavior that satisfies its candidate. No research component is cut.

Every requirement is written with "must" or "must not", carries `status: pending:#5`, and carries `tdd: none` until the TDD is written.

Weekly genome replacement (C-2026-09-19-34, SDD-FT-13) and selection with no generation clock (C-2026-09-19-134, SDD-AG-18) are reconciled: selection is evaluated once in each weekly cycle, and a cycle in which no genome has the minimum count of resolved claims replaces nothing.

## Consequences

The design has a written baseline that implementation issues can be cut from. Any requirement can still be changed by its own later decision, through the amendment ledger.

Four accepted candidates are held out because each is a second way of doing something the baseline already does once: a larger encoder kept as a swap, a third citation source, and two further claim types. They stay in `docs/incoming.html`, their ids SDD-MD-05, SDD-MD-09, SDD-EN-28 and SDD-EN-29 are reserved, and #27 decides when they enter.

Left open on purpose, each with its issue:

- Values the requirements need and the candidates did not give: #6. A requirement with an unset value says `not yet set (#6)` in its Limits and cannot be implemented or verified until the value exists. Writing the baseline found further values of this kind, and they are listed on the same issue.
- Decisions that are the owner's: #7 to #17. A requirement that rests on one is written to hold under every listed option and cites the issue.
- Facts that are not yet verified: #18 to #26. No requirement states one as fact.

The TDD, the implementation language and its check command are not part of this decision.
