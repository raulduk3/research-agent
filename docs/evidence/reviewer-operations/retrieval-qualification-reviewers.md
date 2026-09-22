# Reviewers for the shared retrieval qualification

Prepared 2026-09-22, ahead of #70's implementation. This schedules the human
side of MD-12 and RD-28's shared retrieval qualification so it is ready when
the passage index and neighbor-retrieval task exist. No question has been
authored and no reviewer has been contacted; this is the operating plan, not
a completed qualification.

## What this plan does not cover

Issue #78's RD-22 acceptance criterion describes a 200-paper, two-annotator
Jev reference-label program (50 development, 150 held out). That protocol is
decision [0004](../../decisions/0004-adopt-jev-launch-assessments.md)'s
per-field qualification. Decision
[0012](../../decisions/0012-show-jev-after-a-smoke-test.md) (2026-09-21,
#97, merged in #99) supersedes it: "The launch no longer waits on Jev
annotators, and #78 no longer includes Jev labeling." SDD-RD-22 and SDD-SR-27
now require only the engineering smoke test for Jev, with every field shown
as unqualified and no accuracy measure or reference. Jev annotator reviewers
are out of scope for this plan; the acceptance criterion is stale against the
accepted decision record.

## Task: the fixed 100-paper/500-question retrieval evaluation

Source: SDD-MD-12, SDD-RD-28 and Appendix A's "Shared retrieval
qualification" (`docs/spec/SDD.md`, evaluation-leakage section).

- Population: 100 original papers, five per week from the latest 20 complete
  publication weeks, selected uniformly by hash. Five source-anchored
  retrieval questions per paper, authored from the licensed source without
  seeing candidate results: 500 questions total.
- Split: 20 papers (100 questions) are the development set; the remaining 80
  papers (400 questions) are locked for evaluation. The two sets carry
  separate identities in the evidence record; a development question is
  never scored as an evaluation question and the locked 80 are never opened
  to author or tune later questions.
- Judgment: each of the 500 questions gets two independent reviewer
  judgments of whether a candidate source span supports the question
  (`docs/spec/SDD.md` calls this "two independently verified evidence
  judgments"). A reviewer works from the licensed source span alone, without
  seeing the other reviewer's judgment or the system's returned ranking.
- Disagreement: where the two judgments differ, the case is recorded as
  disputed, not resolved by a single reviewer's preference. Adjudication is
  a third, independent read against the same source span; its outcome is
  recorded alongside both original judgments. An unresolved dispute stays
  unresolved in the record rather than being forced to a label.
- Recurring load: the accuracy registry schedules retrieval "above plus
  quarterly refresh" (Appendix A). The quarterly refresh reuses the same
  500-question set and reviewer judgments already on record; it does not
  reopen the locked 80-question evaluation set to new authoring, and any new
  question written for monitoring is drawn only from the development set.

## Reviewer roles and assignment

Two reviewer roles cover this task:

- **Question author.** Writes the five source-anchored questions for an
  assigned paper from the licensed source text, before any candidate result
  exists. One author per paper is sufficient; a second author is not
  required by the spec text.
- **Evidence judge.** Reads a candidate source span against a question and
  records whether it supports the question. Two judges per question, drawn
  so that a judge does not adjudicate a case they already judged.

Actual staffing (named reviewers, their availability and scheduling) is not
authorized by this issue and has not been arranged; #78 says explicitly not
to contact reviewers or promise availability without separate authorization.
This document records the roles and the workload each role carries so that
assignment is ready once the owner authorizes contacting people. Reviewer
identity, when assigned, is recorded as a pseudonymous local id, never a
name or contact detail, matching the retention rule in Appendix A
("Diagnostics, alerts and data handling").

Missing reviewer coverage blocks RD-28's own gate: "Failure leaves passage
study activation unqualified; engineering can still exercise the index."
It does not block #70's implementation or the TDD drafting that names this
task; the index and its engineering use can proceed while reviewer
assignment remains open.

## Keeping evaluator identity separate from rater blinding

Retrieval-qualification reviewers are an operations role distinct from the
blind digest raters that SDD-SR-21 and SDD-SR-22 protect. A retrieval
reviewer sees the licensed source and a candidate span, never a genome
identity, a digest entry or a rater's own view; a digest rater never sees a
retrieval-qualification question or judgment. TDD-4.1.16 ties a rater's
detail-view unlock to that rater's own stored rating; nothing in this plan
grants a retrieval reviewer that unlock, and nothing in this plan exposes a
rater's hidden source, configuration or control-source provenance to a
retrieval reviewer or vice versa. The two reviewer/rater pools do not
overlap access, and access for one is not sufficient authorization for the
other.

## Evidence location

Once real reviewer judgments exist, they are stored with the retrieval
qualification artifacts the storage owner persists under RD-28, referenced
from a future evidence note in this directory naming the run date, sample
and denominator. This document records the plan only.
