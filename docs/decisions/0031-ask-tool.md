# 0031. Let a run ask Jev small questions through an ask tool

- Status: accepted
- Date: 2026-09-23
- Issue: #274 (decision), #300 (implementation)
- Spec: SDD-AG-09, SDD-AG-11, SDD-AG-12, SDD-AG-14, SDD-AG-16, SDD-AG-27 and Appendix A (run budgets, Jev sublimit); TDD-3.1.49, TDD-3.1.51, TDD-3.1.52, TDD-3.1.54, TDD-3.1.58
- Pull requests: pending

## Context

Every run gets the same eight Jev fields on the paper card. A run that could
write its own question would get a second reading where it matters to the
three tasks: whether an excerpt supports a claim, whether a loose end is
already closed, how novel a mechanism is. AG-09 fixed the tool set at five,
SR-12 and AG-10 give a run no reach beyond its snapshot and the agent model,
and the Jev sublimit is USD 2 per UTC day. The owner accepted the proposed
shape on #274 on 2026-09-23 with the values below.

## Decision

`ask` is a sixth tool, between `deep_read` and `submit` in AG-09's order. A
genome may narrow it away under AG-14; a genome without it is the control of
the Jev benefit comparison.

- Kinds. `yes_no`, `choose` and `rate` are sent as the Jev primitives
  `noul`, `choice` and `score`, which the agent never sees by name. `choose`
  carries 2 to 6 named options with a criterion each, `rate` an ordered
  scale of 3 to 7 points, lowest first. `yes_no` answers `{answer, p_yes}`,
  `choose` `{answer, confidence, probabilities}`, `rate` `{answer, label,
  confidence, probabilities}` with the scale point nearest Jev's score. Each
  answer also renders as one sentence.
- State by reference. `about` is exactly one of a passage id with its paper
  id, a paper id with section `abstract` or `overview`, or `self`, the
  run's own words. The tool service resolves the first two from the run's
  own snapshot and refuses anything else `not_in_snapshot`; Jev always reads
  the pinned text, never text the agent copied in.
- Strict schema (AG-11). Every field present, unused fields null. `question`
  at most 300 characters, `self` at most 1,500 and the optional `claim` at
  most 500. There is no free-text instruction field.
- Run budget. `ask_calls` is 4 a run, a launch constant beside
  `model_calls`, charged by `RunBudget.charge_ask` when an answer reports it
  and shown in `remaining` on every tool response (AG-27). The tool service
  refuses a fifth ask `ask_budget_exhausted` before Jev is reached.
- Daily budget. Asks draw from a USD 0.50 daily pool inside the USD 2 Jev
  sublimit. Each ask reserves its worst case, no more input tokens than
  request bytes at the Jev prompt price, on the day's Jev usage record in
  the same atomic update that counts card attempts, against the pool and the
  whole sublimit together, so an ask never spends what the sublimit leaves
  the cards. Past the pool the tool refuses `daily_ask_budget_exhausted`.
- Provenance and replay. Request and response are stored artifacts whose
  hashes, returned model and configuration hash the answer carries (SR-23);
  the tool trace records the call and its `ask_calls` charge. The answer is
  kept once per run and request, so a replayed call is served the kept
  answer and never asks Jev again.
- The Jev credential lives only in the tool service's transport. The run
  sends `ask` to the tool service like any other call and never reaches Jev.
- `agents/configuration.py#ASK_GUIDANCE` is when to ask, and one worked
  example of each kind. The harness adds it to the system message of every
  run whose allowed tools include `ask`; no genome's own text carries it.

## Consequences

- One ask is about 1,000 input tokens, about USD 0.00005. 1,400 runs a day
  at 4 asks each is 5,600 asks, about USD 0.28, so the pool is a hard stop
  rather than the expected spend.
- The launch profile's `run` section carries `ask_calls: 4` and admits
  `ask`, so the profile hash changes.
- Migration 0025 admits `ask` in a run's `allowed_tools`, adds the ask
  pool's reserved spend to `jev_daily_usage`, marks ask reservations, and
  keeps each run's answered asks in `jev_ask_answers`.
- `ask` answers are agent-side and never shown to a rater (SR-25, SR-26).
- `self` asks Jev to grade the agent's own prose, which is outside what Jev
  was built for. It ships behind the cap and the benefit comparison decides.
- Open under #300: the tool service a run worker starts has no `ask`
  handler yet, because the ask store is not reachable over the storage
  service's routes, so AG-09 stays pending until it is.
