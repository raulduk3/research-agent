# 0004. Adopt Jev paper assessments at launch

- Status: accepted
- Date: 2026-09-20
- Issue: #54
- Spec: SDD scope and Terms; SR-13, SR-17, SR-25, SR-27, IN-09, RD-01 to RD-03, RD-15 to RD-24
- Pull requests: pending

## Context

The launch includes Jev-derived paper-card assessments. The earlier later-layer recommendation in #54 is superseded by the accepted launch role and complete rubric package. Existing reader failure and provenance rules did not distinguish hosted assessments from local fitted models, and SR-17 would have required mature baseline outcomes before activation.

## Decision

Use eight fixed categorical assessments of supplied paper content: contribution type, comparative evaluation, ablation/component analysis, uncertainty reporting, theoretical support, evaluation beyond the main setting, artifact availability statements and limitations disclosure. Keep full probability distributions and provider confidence separate from measured accuracy. The rubric is project-specific and does not produce an overall scientific-quality or novelty score.

Ingest owns bounded external requests; the reader consumes stored results. Supply immutable extracted paper text and coverage without added reputation, popularity, rankings or forecasts. Preserve provenance and historical snapshot bytes. A transient assessment failure leaves the base card available with an explicit unavailable state. Keep assessments out of prediction-head and regression-baseline inputs, deterministic resolution and direct fitness computation, and hide them from raters until rating.

Qualify each field on a seeded 200-paper pilot with 50 development and 150 held-out papers, independently annotated by two people. Compare per-field multiclass Brier score with development-set class frequencies. Freeze the measurement profile before qualification; retain coverage, error, uncertainty, cost and latency reports. The sample is an initial workload rather than a power guarantee.

Amend SR-17 only for this launch feature: qualification and preregistration precede launch, but downstream outcome maturity does not. A prospective comparison with and without assessment fields uses matched inputs and frozen agent configurations; comparison runs do not participate in selection. Later features still obey SR-17.

## Consequences

Ten reader requirements are added; existing ids remain stable. Provider access, retention permissions, identity semantics, input coverage, operating ceilings and measurement-profile values remain explicit readiness gates. #6, #16, #29, #32 and #55 retain their related unresolved choices. #59 carries provider evidence, #60 integration, #61 qualification and #62 the prospective comparison; no provider qualification or forecast benefit is asserted by accepting this design.

The TDD remains unwritten pending the implementation stack and cross-system decisions. No code, API purchase, rental, deployment or head-feature expansion is introduced. Historical decision records remain unchanged; this record supersedes the earlier Jev deferral only for the accepted paper-card feature.
