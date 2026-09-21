# Implementation readiness

Checked 2026-09-20. Draft PR #63 includes accepted full-paper passage retrieval and combined overview/passage head features under #68. The semantic targets and reviewed corpus from #64 are now under explicit reconsideration; they remain written contracts, not reaffirmed product choices. ForeSci selection authority is separately open in #69. This inventory is not a claim that the entire system is ready or that a model has been trained.

## Decisions required to close the SDD

| Order | Decision | Proposed direction or remaining choice | Owner |
| --- | --- | --- | --- |
| 1 | Target and label acquisition | Decide one or two automatic citation targets versus the written semantic targets; fix threshold, indexing allowance, coverage and original-document eligibility | #64, #16, #7 |
| 2 | Evaluation and evolutionary authority | ForeSci as isolated development evaluation versus explicit benchmark-based selection; reconcile the no-LLM-score rule and preserve live outcome reporting | #69, #11, #32 |
| 3 | Reader and card measurements | Full-paper passage retrieval and pooled head input accepted; choose neighbor/distance policy and measured comparison criterion, exact graph fields and extraction fallback | #68, #6, #25, #29 |
| 4 | Agent procedure and claims | Fix mutation fields, schema bounds, retrieval/run budgets, population/concurrency, replacement and diversity behavior; admit only resolvable claim types | #6, #10, #12, #13, #17, #35 |
| 5 | Jev qualification | Keep eight original-paper assessments; settle operating limits and comparison plan independently of head-label work | #54, #59, #61, #62 |
| 6 | Deployment and runtime | Local state plus model endpoint; fix toolchain, persistence and recovery interfaces, backup/anchor and resource profile without buying hardware | #43, #8, #55 |
| 7 | Measurement and operations | Freeze statistical comparisons, alert conditions, source/correction checks and data handling; reader preference authority stays a separate choice | #6, #32, #46 |

Published methods and accessible code do not close these product decisions. Budget, provider access, exact model capability, source coverage and predictive gain remain measurable external gates. Fixed engineering contracts can be written before those results exist; results cannot be invented to make the SDD look complete.

## Written contracts, with target reconsideration noted above

| Contract | Location |
| --- | --- |
| Two precise, contribution-general outcome definitions; one primary selection objective | SDD EN-12 to EN-16; LEARNING-PROTOCOL.md target registry |
| Original-version input, fixed horizon and delayed collection, unknown versus negative | EN-13; FT-17 to FT-21 |
| Historical corpus is required, with sources, provenance, review and sample gates | FT-18 to FT-22; learning protocol |
| Jev assistance distinct from human label authority and original-paper assessment | FT-20; IN-12; RD-15 to RD-24 |
| Input/output shape, logistic loss, regularization, split, calibration, promotion | FT-08 to FT-11; FT-23; learning protocol |
| Weekly refresh, corrections, cold start, immutable model compatibility | FT-10, FT-16, FT-23 to FT-25 |
| One common target for fitness and digest ordering; bounded digest quotas | FT-12, FT-14; EN-33, EN-34, EN-41, EN-42 |
| Partial cards and no mandatory separate trainable encoder | RD-01, RD-08; MD-01, MD-03, MD-04 |

## Empirical gates, not additional feature decisions

| Gate | Evidence required | Owner | Work possible before it passes |
| --- | --- | --- | --- |
| Source access and historical evidence coverage | Licensed responses, completed pagination, dated versions and representative missingness report | #64, #26, #31, #33 | Identity, artifact and corpus-manifest implementation |
| Annotation feasibility | Independent reviews, agreement, unknown reasons, cost and contribution-type coverage | #64 | Review interface and deterministic evidence resolver |
| Frozen embedding artifact | Obtainable immutable weights, input/tokenizer contract, dimension, license and measured representation comparison | #15, #25 | Representation-manifest interface and CPU head fitting on verified stored vectors |
| Forecast skill | Qualified partitions, held-out Brier improvement, calibration and subgroup reporting | #64 | Training and evaluation pipeline; unavailable-head serving |
| Original-paper Jev provider and rubric | Capability/retention evidence and the separate content-assessment qualification | #59, #61 | Stored-response integration and unavailable handling |
| Agent endpoint | Exact multimodal checkpoint/quantization/template, tool correctness, context limits, latency and interruption test | #14, #55 | Canonical transcript, schema validation, recorded-response replay |
| Host and spend | Available hardware, measured capacity, explicit rental/source-call spending cap | #8, #10, #55 | Local document and contract work; no provisioning |

No complete historical corpus or annotation benchmark has been run. Public endpoint samples establish reachability only. They do not satisfy these gates.

## Remaining system design before a full TDD

These are deliberately visible rather than described as finished by the learning amendment.

| Issue | Remaining concrete contract |
| --- | --- |
| #43 | Language/toolchain pins, package ownership, storage transaction design, check command and CI |
| #6, #8, #55 | Local-state versus rented-inference topology, resource limits, external ledger anchor, network exceptions, backup/restore and spending boundary |
| #6, #10, #55 | Population size, concurrency, context/tool/run budgets, timeout, retry and eviction policy |
| #13, #35, #6 | Mutation inputs, mutable schema limits, own-record access, replacement rate, diversity metric and sanctions |
| #6, #29, #31 | Source/text fallback and figure/table behavior; fixed neighbor/distance/graph fields |
| #32, #6 | Whole-system snapshot boundary assertions, recorded-response replay, null controls, preregistration and statistical-report contracts beyond head evaluation |
| #6, #59, #61, #62 | Original-paper Jev provider ceilings and content-assessment thresholds; prospective ablation sample-size plan |
| #6 | Remaining diagnostics, alert triggers, review sampling and public-author metadata/retention policy |

The exact unresolved SDD lines remain marked with their existing issue references. The TDD now has 28 concrete learning and passage-retrieval items with planned Python owners and tests. It does not yet cover all active SDD requirements; the entire repository is not implementation-ready merely because the outcome design is precise. Runtime pins and storage bindings still await #43.

## Ordered implementation packages

Existing implementation owners: #65 corpus acquisition/releases, #66 evidence review and feasibility, #67 head fitting/serving/refresh. All are needs-triage in First release and retain their declared dependencies. Their semantic-review scope and the sequence below remain conditional on #64; do not start human-label acquisition before that reconsideration closes. Full-paper head features require original-text acquisition regardless of target choice. Passage retrieval and combined-feature implementation are tracked by #70, depending on #68 and this spec amendment.

1. Foundation schemas: paper family/version, artifact, evidence edge, annotation, label, corpus release, representation, bundle and snapshot. Publish their versioning and idempotency rules before independent component work.
2. Acquisition and corpus releases: resumable retrieval, original versions, candidate evidence union, coverage, licensing and immutable checkpoints. First acceptance uses real preserved sources and a deliberately missing document.
3. Review and label resolution: numbered spans, independent reviewers, adjudication, unknown reasons, time boundaries and immutable corrections. First acceptance proves that a missing passage cannot become a negative and a model proposal cannot settle an outcome.
4. Historical feasibility study: the specified 300-paper representative pilot and separate 90-case rubric challenge set, before broad labeling or GPU spending.
5. Embedding and training: pinned representations, masked labels, chronological splits, fitting, calibration and qualification. First acceptance detects a duplicated family across splits and later-outcome leakage.
6. Serving and weekly refresh: immutable bundle promotion, unavailable states, cached embeddings, label corrections and failed-job recovery. First acceptance retains the old serving bundle after interrupted promotion.
7. Agent integration and observation: one real card-to-forecast-to-resolution path, followed by population scale only after cross-system contracts are complete. Historical fixtures verify engineering without being called prospective results.

Each package includes interfaces and failure tests; corpus acquisition and review do not wait for rented agent inference. Raw artifacts and embeddings are reused across label experiments. The source/corpus stage is the first substantial new work, not a hidden preprocessing script.

## Exit criteria

SDD design-ready requires the remaining behavior choices above to be closed or explicitly deferred out of launch. TDD-ready requires one implementation item per active requirement with owners, interfaces and meaningful tests. Implementation-ready issues depend on those contracts. Study-ready additionally requires empirical qualification and operating capacity. Demonstrated benefit additionally requires mature prospective outcomes. None substitutes for another.
