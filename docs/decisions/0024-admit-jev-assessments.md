# 0024: Admit the Jev assessments; provider access exists

Accepted 2026-09-23 on #238. Supersedes the Jev hold-out of decision 0015
(#123); leaves the rest of 0015 in force.

## Context

Decision 0015 held the eight Jev paper-card assessments out of the launch
under SR-17 "until provider access exists", by a sentence in Scope and
scale, a note under the 6.3 heading, a Limits line on each of RD-15 to
RD-24, a Terms entry and a paragraph in Appendix A's scope, and had them
"enter by a later accepted decision". On 2026-09-22 (#59,
`docs/evidence/models/jev-provider.md`, #212) access was verified against
the live service through the ngrok AI gateway: the `systemone` interface,
the `choice`, `score` and `noul` primitives, the immutable revision
`jev-1.13.0` resolved behind both aliases, the context and input limits and
the price. On 2026-09-23 the owner directed that the launch uses Jev.

## Decision

The Jev assessments are admitted to the launch under RD-15 to RD-24.

- The hold-out sentences that 0015 placed (Scope and scale; the Terms
  entry; the 6.3 note; the Limits line on each of RD-15 to RD-24; Appendix
  A's scope paragraph and its three held-out value paragraphs; the
  with-Jev arm's suspension under RD-23; RD-24's suspended readiness
  condition) are replaced by a citation of this decision. RD-15 to RD-24
  keep their ids and text; their trace status changes only as #60 to #62
  implement them.
- The readiness gate `platform/readiness.py#LayerAdmission` admits the Jev
  layer only on the evidence RD-22 to RD-24 name: a passing smoke test with
  owner review, a preregistered prospective comparison and the readiness
  record. This decision establishes none of that evidence, and neither
  does #59's document; `jev_admitted` is set by the launch profile from
  that evidence (#62), not by this decision.
- #60, #61 and #62 resume. #60 builds against recorded fixtures; the
  controlled live qualification call is the owner's, with the credential
  that stays with the owner.

## What stays as it was

- Retention: the provider publishes no retention policy, so no retention
  permission is established. RD-21's exclusion of Jev data from head,
  baseline, resolver and pre-rating inputs stands.
- No fallback provider (RD-20). The gateway is the one path, and a gateway
  refusal is an assessment failure, never a substitute answer.
- Selection fitness is forecast skill (decision 0023). An assessment on a
  paper card is not a selection signal, and AG-35's prohibition on schema
  evolution reaching the rubric stands.
- The Jev sublimit in Appendix A (USD 2 per day) is unchanged and remains
  unused until funded execution is authorized.

## What becomes impossible

Launching with a paper card that shows no assessment field: the card
carries the assessment or a recorded assessment failure, never silence.

## What is deliberately left open

The values of RD-22's smoke-test pass criteria and RD-23's preregistration
are as the SDD already fixes them; their measurement is #61 and #62.
