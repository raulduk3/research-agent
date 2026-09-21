# 0011. Show Jev assessments after a smoke test

- Status: accepted
- Date: 2026-09-21
- Issue: #97
- Spec: SDD SR-17, SR-27, RD-03, RD-15, RD-19, RD-22, RD-24, FT-24; launch profile, Jev smoke test; TDD-4.1.57, TDD-4.1.60, TDD-4.1.62 and the Jev request, response and smoke-test records
- Pull requests: #98
- Supersedes: the per-field human qualification of RD-22 in decision 0004 and its launch-profile values in decision 0008; preserves the rubric, input, provenance, budget, snapshot and prospective-comparison contracts

## Context

RD-22 required qualifying each of the eight Jev rubric fields before launch. That meant 200 target-corpus papers labeled by two independent annotators and adjudicated, a Brier bootstrap gate per field, and 50 freshly labeled papers every 30 days. That is about 3,200 human labels before launch and a standing labeling commitment afterward. The owner decided the launch does not need that evidence.

## Decision

Jev assessments go on paper cards after an engineering smoke test and are shown as unqualified.

- The smoke test runs the full eight-field request on 20 target-corpus papers: the first hash-ranked paper from each of the latest 20 complete publication weeks, with any shortfall visible.
- Every field must return a schema-valid result for at least 18 of the 20 papers. Category distributions, unavailable reasons, latency and cost are recorded.
- The owner reads the stored answers and records the review before activation.
- A provider identity or rubric change requires a fresh smoke test before new results are admitted.
- Every Jev field on a card is labeled as not measured against human labels. No accuracy is claimed. SR-27 names Jev as its exception.

No reference labels, annotator agreement, Brier comparison or recurring human recheck exist. `JevSmokeReport` and `JevFieldSmoke` replace `JevQualificationReport`, `JevFieldMetrics` and `JevReferenceLabel`.

## Consequences

The launch no longer waits on Jev annotators, and #78 no longer includes Jev labeling. The rubric (RD-16), input limits (RD-17), uncertainty handling (RD-18), provenance (RD-19), budgets (RD-20), snapshot immutability (RD-21) and the preregistered with/without comparison (RD-23) are unchanged. RD-23 still measures whether Jev improves forecasts, without human labels, once outcomes mature.

What is given up: nothing measures whether a Jev answer is correct, so agents read answers of unknown accuracy, and a provider change that worsens answers without breaking the schema will not be detected. The card label exists so that agents and anyone reading a card know this. Per-field qualification can return through a later amendment; the qualification part of #61 is superseded.
