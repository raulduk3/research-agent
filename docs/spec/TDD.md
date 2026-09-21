# Technical Design Description

How the software is built to meet each requirement, item by item, with the code and tests that carry it.

## Document control

| Field               | Value                                                                                                                                |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Product             | research-agent.                                                                                                                |
| Target version      | First release; learning and passage-retrieval coverage only.                                                                                                 |
| Scope               | The design of what [SDD.md](SDD.md) requires, and nothing it does not.                                                               |
| Authority           | This document decides how the software is built. Where code and this document disagree, one is wrong; say which, with evidence.      |
| Companion documents | [SDD.md](SDD.md) states what the software must do. [SPEC-AMENDMENTS.md](SPEC-AMENDMENTS.md) records each change to either.           |
| Change control      | A pull request cites an accepted decision under `docs/decisions/`, edits the exact lines, and appends a row to the amendment ledger. |

## Normative language

- "must" states a requirement.
- "must not" states a prohibition.
- No other word makes a requirement. A proposal that is not decided is a GitHub issue and does not appear here.

## Conventions

- Each item is a `#### TDD-<section>.<n> Title` heading.
- A trace comment follows it: `<!-- id: TDD-x.y.z | implements: XX-nn | code: path#Symbol | tests: path or none | status: ... -->`.
- Items are numbered in reading order. A cited item is never renumbered; new items are appended.
- Status is one of `implemented`, `pending:#issue` (decided, not yet implemented) or `deviation:#issue` (the code does not yet meet it).

Example, not part of the specification:

```text
#### TDD-1.1.1 Reject a request without a credential

<!-- id: TDD-1.1.1 | implements: XX-01 | code: src/http/auth.ts#requireCredential | tests: tests/http/auth.test.ts | status: pending:#12 -->

The request handler calls `requireCredential` before routing. It returns the rejection response and logs the request id once.
```

## 1. Historical learning and evidence

### 1.1 Corpus, labels and qualified prediction heads

These items define the learning subsystem. Code and test paths name planned owners, not existing implementations. Python module names establish a concrete package boundary; runtime pins, packaging, storage bindings and CI remain the separate toolchain work in #43. Full-system coverage remains tracked in #56.

#### TDD-1.1.1 Versioned target registry

<!-- id: TDD-1.1.1 | implements: EN-12 | code: src/research_agent/outcomes/targets.py#TargetDefinition | tests: tests/outcomes/test_targets.py | status: pending:#64 -->

Represent each target as an immutable record with id, semantic version, relationship predicate, origin rule, horizon seconds, grace seconds and observation-protocol hash. Store the two launch records in a versioned registry. Questions persist the complete definition hash, not a lookup of the latest definition. Reject unregistered targets and reuse of an id/version with different bytes. Resolver input contains reviewed edges, not platform counters.

#### TDD-1.1.2 Event and collection clocks

<!-- id: TDD-1.1.2 | implements: EN-13 | code: src/research_agent/outcomes/windows.py#OutcomeWindow | tests: tests/outcomes/test_windows.py | status: pending:#64 -->

Represent timestamps as timezone-aware UTC instants and uncertain dates as half-open intervals. Compute the event end by adding 31,536,000 seconds and the collection deadline by adding 7,776,000 seconds. A dated passage is eligible only when its entire possible event interval is inside the event window. Record a separate 86,400-second seal deadline. Test exact boundary instants, date-only intervals and delayed arrival without using the machine clock inside the resolver.

#### TDD-1.1.3 Independent relationship outcomes

<!-- id: TDD-1.1.3 | implements: EN-15 | code: src/research_agent/outcomes/targets.py#RelationshipLabels | tests: tests/outcomes/test_relationships.py | status: pending:#64 -->

Use two independent named label fields rather than a mutually exclusive class. Each field stores value true/false/unknown, evidence-edge ids and reason. Store contribution object and evaluation direction on evidence edges; they are not additional trained targets. Deduplicate downstream versions by family before aggregation. A use-and-evaluation case produces two true fields, while a mention-only case satisfies neither.

#### TDD-1.1.4 Coverage denominators

<!-- id: TDD-1.1.4 | implements: EN-39 | code: src/research_agent/learning/coverage.py#CoverageReport | tests: tests/learning/test_coverage.py | status: pending:#64 -->

Build reports from the initial selection manifest with left joins to acquisition and annotation results. Never start from successfully downloaded or labeled rows. Count every stage and unknown reason by target, month, contribution type and domain, preserving multi-label stratum denominators. Include source pagination completion and unmatched families. Serialize both numerators and denominators; a source total without passages does not count as annotation coverage.

#### TDD-1.1.5 Independent adjudication

<!-- id: TDD-1.1.5 | implements: IN-12 | code: src/research_agent/review/adjudication.py#AdjudicationService | tests: tests/review/test_adjudication.py | status: pending:#64 -->

Review assignments expose preserved passages and the frozen rubric, excluding model proposals and forecast fields. Persist each reviewer verdict separately. Two agreeing verdicts create a reviewed edge; disagreement creates an unresolved adjudication task. Joint adjudication appends a result referencing both initial records. Preference ratings live in a different event type and cannot call the outcome-correction operation. Corrections create new label versions and do not overwrite old review events.

#### TDD-1.1.6 Resumable corpus stages

<!-- id: TDD-1.1.6 | implements: PL-11 | code: src/research_agent/learning/jobs.py#CorpusPipeline | tests: tests/learning/test_resume.py | status: pending:#64 -->

Execute acquisition, extraction, identity matching, annotation export, label assembly, encoding and release assembly as separate checkpointed stages. The cache key is the stage version plus ordered input artifact hashes and configuration hash. Write temporary output, verify hashes, then commit the stage manifest; publish a dataset release only after all required stages pass. Resume reads verified committed stages and retries missing work. A failed annotation stage never re-downloads unchanged papers.

#### TDD-1.1.7 Manifest dependency barrier

<!-- id: TDD-1.1.7 | implements: PL-17 | code: src/research_agent/artifacts/manifests.py#ManifestResolver | tests: tests/artifacts/test_manifests.py | status: pending:#64 -->

A dependent job accepts a release id, resolves its immutable manifest, verifies terminal success and all referenced artifact hashes, then records that exact dependency. Raw directory contents are not an accepted input interface. Inference holds the previously activated manifest independently of running jobs. Exercise interruption after individual file writes but before manifest commit to prove partial output stays invisible.

#### TDD-1.1.8 Masked binary head fitting

<!-- id: TDD-1.1.8 | implements: FT-08 | code: src/research_agent/learning/fit.py#fit_head | tests: tests/learning/test_fit.py | status: pending:#68 -->

Accept a float32 feature matrix, one target label vector and an availability mask from a validated manifest. Select only known rows, optimize the exact mean-loss/L2 objective in LEARNING-PROTOCOL.md and record convergence, selected lambda and fitting hashes. Use float64 optimization and unpenalized intercept. Persist plain numeric coefficients plus metadata; never load untrusted serialized executable objects. Reject nonfinite inputs and single-class fitting. Test the real objective gradient against numerical differentiation and verify masked rows have no effect.

#### TDD-1.1.9 Representation-only feature assembly

<!-- id: TDD-1.1.9 | implements: FT-09 | code: src/research_agent/learning/features.py#assemble_features | tests: tests/learning/test_features.py | status: pending:#68 -->

Resolve stored vectors through the representation manifest and require equal dimension, preprocessing id and weights/tokenizer hashes. Construct X with 2d columns by concatenating the overview and overlap-weighted unit-normalized passage pool divided by sqrt(2), as fixed in RETRIEVAL-PROTOCOL.md. Join labels separately by canonical paper id; do not concatenate metadata into X. Reject partial original full-text coverage and keep retrieval availability separate. Return X, named Y and M arrays with explicit row ids. Feature assembly has no API for Jev probabilities, later evidence text or platform counts. Use a preserved vector fixture and mutate every forbidden metadata field to verify the fitted input bytes remain identical.

#### TDD-1.1.10 Weekly training manifest

<!-- id: TDD-1.1.10 | implements: FT-10 | code: src/research_agent/learning/refresh.py#build_refresh | tests: tests/learning/test_refresh.py | status: pending:#64 -->

Freeze a committed evidence watermark and label-version map at the job start. Select only mature labels whose available_at is at or before the freeze. Resolve immutable historical and live examples into the existing partition policy. Hash the resulting dataset and fitting configuration; unchanged identity yields unchanged-data without fitting. Corrections after the watermark wait for a later run. Emit explicit per-target completion, insufficiency and failure records.

#### TDD-1.1.11 Separate sigmoid calibration

<!-- id: TDD-1.1.11 | implements: FT-11 | code: src/research_agent/learning/calibration.py#fit_calibrator | tests: tests/learning/test_calibration.py | status: pending:#64 -->

Fit nonnegative slope a and intercept b on calibration logits using the exact penalized objective in the learning protocol, independently of the head optimizer. Verify family/week partition disjointness before accessing labels. Store a,b and the calibration manifest in the bundle. Evaluate raw and calibrated outputs on the locked partition without updating either. A calibration set containing a fitting-family id fails before optimization; nonconvergence is a failed candidate, not an identity calibrator.

#### TDD-1.1.12 Original input provenance

<!-- id: TDD-1.1.12 | implements: FT-17 | code: src/research_agent/learning/representation.py#EmbeddingManifest | tests: tests/learning/test_representation.py | status: pending:#68 -->

Persist original paper version, normalized title/abstract input bytes, full-text extraction identity, ordered passage spans and weights, combined-feature hash, source availability and computed_at separately. Apply RETRIEVAL-PROTOCOL.md for passage pooling and complete-original-text eligibility. Normalize UTF-8 text to NFC and LF, tokenize with the pinned tokenizer and refuse empty or oversized inputs rather than truncating. Normalize dense output to unit L2 length and reject zero/nonfinite vectors. A current computation date is valid for historical deployment training; live snapshots additionally require the vector artifact to have been committed before sealing.

#### TDD-1.1.13 Historical release assembly

<!-- id: TDD-1.1.13 | implements: FT-18 | code: src/research_agent/learning/corpus.py#build_release | tests: tests/learning/test_corpus.py | status: pending:#64 -->

Create the selection manifest before evidence retrieval, following the deterministic month/hash sampling rule. Retain each selected id even after a failed download. Join original versions, reviewed labels and representation artifacts without filtering on positive outcomes. Group paper families and complete publication weeks before creating four temporal partitions. Store acquisition kind historical_reconstructed where old index snapshots are absent. Publication of a release requires verified hashes, partition checks and a qualification report.

#### TDD-1.1.14 Shared label protocol

<!-- id: TDD-1.1.14 | implements: FT-19 | code: src/research_agent/outcomes/protocol.py#ObservationProtocol | tests: tests/outcomes/test_protocol.py | status: pending:#64 -->

Use one frozen protocol object in both the historical label job and live resolver. It contains discovery adapter versions, work-identity rules, evidence-window rules, rubric hash and author relation rule. An edge includes event interval, captured_at and reviewed_at. Store historical acquisition limitations separately, without changing the semantic relationship predicate. Both execution paths pass the same preserved-case conformance suite; protocol changes require new question and label identities.

#### TDD-1.1.15 Jev annotation proposals

<!-- id: TDD-1.1.15 | implements: FT-20 | code: src/research_agent/review/proposals.py#propose_relationships | tests: tests/review/test_proposals.py | status: pending:#64 -->

Ingest builds a bounded request from numbered source passages, contribution context and a fixed rubric. Store sanitized request/response bytes and provider identity under a proposal record. Proposals have no authority to write reviewed edges or labels. The review assignment query omits proposal fields from independent reviewers. A provider outage leaves the manual queue intact. Replaying stored responses tests schema handling without pretending provider generation is deterministic.

#### TDD-1.1.16 Evidence completion resolver

<!-- id: TDD-1.1.16 | implements: FT-21 | code: src/research_agent/outcomes/resolve.py#resolve_target | tests: tests/outcomes/test_resolution.py | status: pending:#64 -->

Run a pure function over a mature observation manifest. First return true if any reviewed eligible external edge meets the target. Otherwise return unknown if any source discovery is incomplete or any potentially eligible edge has unresolved text, identity, date or review. Return false only when the completion certificate proves every such edge handled. Persist the exact evidence set and unknown codes. Test inaccessible text, duplicate revisions, author overlap and evidence inserted after the collection watermark.

#### TDD-1.1.17 Qualification gates

<!-- id: TDD-1.1.17 | implements: FT-22 | code: src/research_agent/learning/qualification.py#qualify_corpus | tests: tests/learning/test_qualification.py | status: pending:#64 -->

Consume the preserved selection denominator, independent initial reviews and final labels. Compute target coverage, stratum counts, kappa and separate positive/negative agreement before adjudication. Evaluate each fixed gate independently and emit a machine-readable pass/fail reason with raw counts. Development and challenge-set ids cannot enter representative qualification. A report cannot mark a sparse or absent stratum passed. Keep workload cap exhaustion and reviewer time visible even when a target has enough positives.

#### TDD-1.1.18 Bundle compatibility gate

<!-- id: TDD-1.1.18 | implements: FT-23 | code: src/research_agent/learning/bundles.py#validate_bundle | tests: tests/learning/test_bundles.py | status: pending:#64 -->

A bundle is a content-addressed manifest containing target definitions, representation identity, numeric head/calibrator artifacts and evaluation reports. Validate hashes, expected dimensions, finite coefficients, calibration status and target version before publishing it. Each target entry is qualified with an artifact or unavailable with a reason. Retained older artifacts are accepted only when their representation and target identity match the new manifest; they are explicit members, not mutable pointers.

#### TDD-1.1.19 Readiness state

<!-- id: TDD-1.1.19 | implements: FT-24 | code: src/research_agent/learning/readiness.py#forecast_readiness | tests: tests/learning/test_readiness.py | status: pending:#64 -->

Derive engineering-ready, qualified-forecasting and mature-evaluation states from separate evidence records. Missing heads permit source capture, review and readable cards. Qualified forecasting requires a currently valid use-head qualification; optional evaluation-head failure remains visible. No readiness path infers model quality from process exit status or from an existing artifact filename. Verify empty-registry startup and later qualification without rewriting prior readiness records.

#### TDD-1.1.20 Correction dependency graph

<!-- id: TDD-1.1.20 | implements: FT-25 | code: src/research_agent/artifacts/lineage.py#apply_correction | tests: tests/artifacts/test_corrections.py | status: pending:#64 -->

Append a correction referencing the superseded source/review/label id, then enumerate dependent corpus, bundle and report manifests through stored input edges. Mark affected evaluations stale and enqueue replacement qualification. Preserve sealed predictions and previous artifacts. If an active qualification is critically invalid, atomically withdraw the affected target to unavailable until requalified. A representation correction requires a new namespace rather than mutation of vector bytes.

#### TDD-1.1.21 Atomic serving pointer

<!-- id: TDD-1.1.21 | implements: PL-14 | code: src/research_agent/models/registry.py#activate_bundle | tests: tests/models/test_activation.py | status: pending:#64 -->

Commit verified bundle bytes before one transactional compare-and-swap of the active bundle id. Inference acquires one manifest at request start and holds it until completion. Old manifests remain addressable for sealed snapshots. Test concurrent inference across promotion and crashes before and after pointer commit; each response resolves to one fully verified manifest. Storage locking and transaction implementation are pinned with the platform toolchain under #43.

#### TDD-1.1.22 Named head inference

<!-- id: TDD-1.1.22 | implements: RD-08 | code: src/research_agent/models/predict.py#predict_targets | tests: tests/models/test_predictions.py | status: pending:#64 -->

Accept paper/version and pinned bundle ids, obtain the matching stored vector and compute calibrated sigmoid outputs in the registry target order. Return named records containing probability or unavailable reason, target version, event window, fit cutoff and provenance ids. Do not output raw vector coordinates to the agent. Reject incompatible vectors before multiplication. Missing one target leaves the other available and cannot suppress the core paper card.

#### TDD-1.1.23 Prospective head evaluation

<!-- id: TDD-1.1.23 | implements: IN-38 | code: src/research_agent/measurement/heads.py#evaluate_predictions | tests: tests/measurement/test_head_evaluation.py | status: pending:#64 -->

Read persisted prediction records and their producing bundle memberships. Exclude recomputed predictions, examples used in that bundle fitting/tuning/calibration, and events predating seal. Join the appropriate reviewed label versions and report unknown denominators separately. Compute Brier score, paired baseline skill, average precision and ten fixed reliability bins. Group repeated forecasts by paper and publication week in interval calculations. Never infer prospective eligibility solely from resolution happening after fit.

#### TDD-1.1.24 Weekly stage state machine

<!-- id: TDD-1.1.24 | implements: FT-16 | code: src/research_agent/orchestration/weekly.py#run_week | tests: tests/orchestration/test_weekly.py | status: pending:#64 -->

Use a persisted weekly id and freeze watermark to make each stage idempotent. Complete freeze, fitting, calibration, scoring, conditional selection and report in order. Treat model candidate rejection and insufficient data as terminal stage outcomes that allow reporting with the incumbent; treat corrupt source or ledger integrity as dependency failure. Resume from the last committed stage, not by rerunning submitted forecasts. Test a fit crash and a broken chain as different paths.

#### TDD-1.1.25 preserve source-linked passage embeddings alongside paper overview embeddings

<!-- id: TDD-1.1.25 | implements: RD-25 | code: src/research_agent/retrieval/passages.py#build_passages | tests: tests/retrieval/test_passages.py | status: pending:#68 -->

Apply the representations, coverage and chunking rules in RETRIEVAL-PROTOCOL.md. Keep versioned source spans, section paths, extraction coverage and compatible model identities; do not silently truncate or pool a whole paper into one vector. A real extracted document is chunked across a long section and a short appendix; every included token is covered, overlap is bounded, and source spans reconstruct the passages. Planned owner only; no implementation exists. Storage bindings remain under #43.

#### TDD-1.1.26 Passage search must obey the run snapshot and bounded deterministic ranking

<!-- id: TDD-1.1.26 | implements: RD-26 | code: src/research_agent/retrieval/passages.py#search_passages | tests: tests/retrieval/test_passages.py | status: pending:#68 -->

Apply the query, cosine ranking, family/version selection, tie order, non-overlap and result limits in RETRIEVAL-PROTOCOL.md through the existing tool. An exact cosine reference comparison catches ranking drift, duplicated overlapping hits and a revised paper inserted after the snapshot. Planned owner only; no implementation exists. Storage bindings remain under #43.

#### TDD-1.1.27 Paper-card responses must expose full-paper evidence as source-linked query attachments

<!-- id: TDD-1.1.27 | implements: RD-27 | code: src/research_agent/retrieval/passages.py#attach_evidence | tests: tests/retrieval/test_passages.py | status: pending:#68 -->

Keep the base card immutable and attach exact matching text, score, source location, query identity and coverage using RETRIEVAL-PROTOCOL.md. Deep reading resolves the surrounding source; no raw vectors or quality probabilities are inferred. Two queries produce distinct evidence attachments while preserving the same base-card hash; each attachment reproduces its cited source bytes. Planned owner only; no implementation exists. Storage bindings remain under #43.

#### TDD-1.1.28 Passage-index publication must preserve cache identity and historical snapshots

<!-- id: TDD-1.1.28 | implements: RD-28 | code: src/research_agent/retrieval/passages.py#publish_index | tests: tests/retrieval/test_passages.py | status: pending:#68 -->

Apply the cache and atomic publication rules in RETRIEVAL-PROTOCOL.md. Reuse unchanged passage artifacts and keep prior snapshot memberships accessible. Qualify study use through the recorded comparison under SR-17 and SR-18. Interrupt an index build, resume it, and verify unchanged vectors are reused and an older run still reads only its original index. Planned owner only; no implementation exists. Storage bindings remain under #43.
