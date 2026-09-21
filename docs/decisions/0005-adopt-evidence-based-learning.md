# 0005. Adopt evidence-based research outcome learning

- Status: superseded in part by [0007](0007-adopt-three-automatic-citation-heads.md); retained as the historical decision record
- Date: 2026-09-20
- Issue: #64
- Spec: SDD target, corpus, fitting, inference, scoring and digest contracts; LEARNING-PROTOCOL.md
- Pull requests: #63

## Context

Platform-specific popularity counts did not operationalize substantive research use across contribution types. The target count and meaning remained unspecified, historical labels were assumed available, and the reconstruction rules prohibited computing historical embeddings after publication. The design therefore did not define a buildable supervised-learning experiment.

## Decision

Adopt two evidence-defined first-year outcomes: documented external substantive use and documented external substantive evaluation. Contributions include findings, theories, arguments, syntheses, methods, data and tools. Extension is included in use; evaluation direction is retained separately. These are project-specific operational definitions, not universal research-quality scores. Only substantive use enters fitness and pooled digest ranking. Keep launch ingestion in cs.AI/cs.LG and require separate qualification before broader deployment claims.

Build a versioned historical corpus as a required subsystem. Discover candidate downstream works through scholarly indexes, preserve dated full-text evidence, and establish labels through independent human annotation and adjudication. Jev proposes evidence classifications but never settles labels. Preserve unknowns, collection gaps, paper families, source licenses, correction lineage and observation-protocol limitations. Original-paper Jev assessments remain separate.

Use frozen original-title-and-abstract embeddings and one regularized logistic head per qualified target. Apply temporal partitions, separate calibration, locked release evaluation, explicit promotion gates and immutable serving bundles. Retrain from mature eligible labels; do not train the embedding or agent model. Historical reconstruction supports deployment preparation, not a claim of historical foresight. All clocks and numerical corpus/training policies are fixed in LEARNING-PROTOCOL.md.

The delegated design selection closes the outcome direction without claiming empirical qualification. The initial pilot and corpus growth caps bound the work before further costs. Failed qualification preserves an unavailable signal; it does not silently change labels or relax gates.

## Consequences

This supersedes count-based head recommendations in #16 and makes historical initialization under #7 required. It settles target-specific missingness in #33, chronological calibration in #38 and primary-target fitness under #11. Model artifact capability, source access and coverage, annotation availability and actual forecast skill remain empirical gates. Other platform and agent settings under #6, #43, #55 and #56 are not closed by this decision.

The annotation workload becomes explicit and can dominate corpus preparation. There is no guarantee that the two targets yield enough reliable labels or predictable signal. Cross-disciplinary rubric applicability and cross-disciplinary predictive validity are distinct. A first-year negative is not evidence of permanent worthlessness.

Counter adapters are optional diagnostics. Digest quotas and common primary forecasting support replace incompatible all-service/all-genome inclusion and mixed-target pooling. Human forecasting no longer permanently blocks digest access. Optional signal failures no longer discard papers. The separately deferred encoder is removed from initial startup dependencies.

No paid source access, rented hardware, deployment or successful qualification is implied. The existing draft launch PR is expanded as one coherent launch-design change; no dependent branch or stacked PR is introduced. Full-system implementation readiness is recorded separately and is not inferred from document lint passing.
