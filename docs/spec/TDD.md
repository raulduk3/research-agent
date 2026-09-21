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

<!-- id: TDD-1.1.1 | implements: XX-01 | code: src/http/auth.ts#requireCredential | tests: tests/http/auth.test.ts | status: pending:#64 -->

The request handler calls `requireCredential` before routing. It returns the rejection response and logs the request id once.
```

## 1. Historical learning and evidence

### 1.1 Corpus, labels and qualified prediction heads

These items define the learning subsystem. Code and test paths name planned owners, not existing implementations. Python module names establish a concrete package boundary; runtime pins, packaging, storage bindings and CI remain the separate toolchain work in #43. Full-system coverage remains tracked in #56.

#### TDD-1.1.1 Versioned automatic target registry

<!-- id: TDD-1.1.1 | implements: EN-12 | code: src/research_agent/outcomes/targets.py#TargetDefinition | tests: tests/outcomes/test_targets.py | status: pending:#64 -->

Store the three automatic-citations-v1 records in fixed order with source, predicates, thresholds, elapsed-day windows, grace, capture allowance, identity/taxonomy rules and definition hash. Questions embed that immutable identity. Resolver inputs are preserved citation observations, never current counters, human semantic verdicts or Jev answers. Reject id/version reuse with changed bytes. Test the exact 5-family, two-window and 2-subfield predicates.

#### TDD-1.1.2 Event and collection clocks

<!-- id: TDD-1.1.2 | implements: EN-13 | code: src/research_agent/outcomes/windows.py#OutcomeWindow | tests: tests/outcomes/test_windows.py | status: pending:#64 -->

Represent instants in UTC and provider dates as full half-open day intervals. Compute the 365-day event end and 90-day maturity allowance; enforce a capture starting at or after maturity and completing by maturity plus 24 hours. Record the 24-hour forecast seal deadline independently. Determine definite/possible inclusion at t0, day 180, 270 and 365, and preexisting-predicate exclusion per target. Pass time explicitly into the resolver. A late historical acquisition is marked reconstructed, never backdated.

#### TDD-1.1.3 Three independent bibliometric outcomes

<!-- id: TDD-1.1.3 | implements: EN-15 | code: src/research_agent/outcomes/targets.py#CitationLabels | tests: tests/outcomes/test_citation_labels.py | status: pending:#64 -->

Return three true/false/unknown records with witnesses or completion proof, bounds and reason. Count canonical citing families once; self-author citations remain included. Reach ignores taxonomy, late activity requires distinct dated families in both windows, breadth counts distinct non-target primary subfields. Test zero/all/overlapping positives, duplicate versions and missing target subfield masking breadth alone. Report correlation without assuming independent outcomes.

#### TDD-1.1.4 Coverage denominators

<!-- id: TDD-1.1.4 | implements: EN-39 | code: src/research_agent/learning/coverage.py#CoverageReport | tests: tests/learning/test_coverage.py | status: pending:#64 -->

Left join source observations, original-text features and automatic labels to the original selection manifest. Preserve failed requests and monthly/weekly shortfalls. Report source matching, capture completion, date/taxonomy availability, feature coverage and per-target unknown reasons by publication period and source-subfield, with missing-subfield as its own group. A release cannot start its denominator from successful rows or hide target-text exclusions.

#### TDD-1.1.5 Deterministic source corrections

<!-- id: TDD-1.1.5 | implements: IN-12 | code: src/research_agent/outcomes/corrections.py#CorrectionService | tests: tests/outcomes/test_corrections.py | status: pending:#64 -->

Accept replacement preserved source evidence or an identified resolver defect. Recompute under the specified protocol, append label versions and dependency lineage, and retain sealed forecasts. No reviewer assignment or adjudication service exists for launch head labels. Rating and Jev schemas have no label-write authority. Test source correction propagation and refusal of a preference-only correction.

#### TDD-1.1.6 Resumable corpus stages

<!-- id: TDD-1.1.6 | implements: PL-11 | code: src/research_agent/learning/jobs.py#CorpusPipeline | tests: tests/learning/test_resume.py | status: pending:#64 -->

Checkpoint acquisition, extraction, identity reconciliation, automatic resolution, encoding and release assembly independently. Keys combine stage version, ordered input hashes and configuration hash. Verify temporary artifacts before committing the manifest. Interrupted label work reuses original papers, raw citation responses and embeddings. A failed target cannot expose a partial release or trigger unchanged paid acquisition.

#### TDD-1.1.7 Manifest dependency barrier

<!-- id: TDD-1.1.7 | implements: PL-17 | code: src/research_agent/artifacts/manifests.py#ManifestResolver | tests: tests/artifacts/test_manifests.py | status: pending:#64 -->

A dependent job accepts a release id, resolves its immutable manifest, verifies terminal success and all referenced artifact hashes, then records that exact dependency. Raw directory contents are not an accepted input interface. Inference holds the previously activated manifest independently of running jobs. Exercise interruption after individual file writes but before manifest commit to prove partial output stays invisible.

#### TDD-1.1.8 Masked three-head fitting

<!-- id: TDD-1.1.8 | implements: FT-08 | code: src/research_agent/learning/fit.py#fit_head | tests: tests/learning/test_fit.py | status: pending:#64 -->

Accept X float32 [N,2d], Y boolean [N,3], M boolean [N,3], row ids and ordered manifests. Fit each logistic model on its own known rows with the exact objective and numeric settings in LEARNING-PROTOCOL.md. Use float64 optimization, unpenalized intercept and plain numeric artifacts. Reject nonfinite inputs, mismatched target order, single-class support and incompatible representation ids. Numerical-gradient and mask-invariance tests exercise the real optimizer; no encoder weights change.

#### TDD-1.1.9 Representation-only feature assembly

<!-- id: TDD-1.1.9 | implements: FT-09 | code: src/research_agent/learning/features.py#assemble_features | tests: tests/learning/test_features.py | status: pending:#64 -->

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

Freeze the 100-paper pilot separately from the 2000-candidate modeling selection using the protocol month/week hash rules. Preserve all selected ids and shortfalls. If allowed, expand to 5000 before inspecting locked evaluation, retaining partition memberships. Join original features and automatic labels without conditioning inclusion on success. Group families and publication weeks, freeze temporal partitions and record reconstructed acquisition. Verify hashes and gates before publishing.

#### TDD-1.1.14 Shared automatic observation protocol

<!-- id: TDD-1.1.14 | implements: FT-19 | code: src/research_agent/outcomes/protocol.py#ObservationProtocol | tests: tests/outcomes/test_protocol.py | status: pending:#64 -->

Use one immutable protocol object for historical and prospective resolution: source adapter, family aliases, provider-date intervals, target predicates, taxonomy snapshot rules and capture deadline. Preserve raw response hashes, capture start/end and maturity separately. Provider publication date is not citation-passage event time. The same stored observation gives the same labels in both execution paths; acquisition kind changes reporting eligibility, not predicate semantics.

#### TDD-1.1.15 Qualified target extension boundary

<!-- id: TDD-1.1.15 | implements: FT-20 | code: src/research_agent/outcomes/targets.py#validate_extension | tests: tests/outcomes/test_extensions.py | status: pending:#64 -->

Permit exactly the three launch target definitions. An extension requires an accepted definition and qualification manifest, new registry/bundle identity and compatible card schema. No semantic-review queue or Jev annotation job is needed. Verify old snapshots retain prior target order, unknown targets are rejected and failed extensions leave existing outputs usable. A changed multiple-comparison plan precedes evaluating added heads.

#### TDD-1.1.16 Bounded automatic resolver

<!-- id: TDD-1.1.16 | implements: FT-21 | code: src/research_agent/outcomes/resolve.py#resolve_target | tests: tests/outcomes/test_resolution.py | status: pending:#64 -->

Run a pure function over mature preserved observations. Build lower/upper counts for dates, family uncertainty and primary-subfield availability under LEARNING-PROTOCOL.md. Positive definite witnesses suffice; false requires complete capture and an upper bound below the predicate; otherwise return unknown. Incomplete pagination gives unbounded upper counts. Test ambiguous boundary dates, repeated records, conflicting family metadata, unknown target subfield and initial request failure. No downstream full text is read.

#### TDD-1.1.17 Source and model qualification gates

<!-- id: TDD-1.1.17 | implements: FT-22 | code: src/research_agent/learning/qualification.py#qualify_corpus | tests: tests/learning/test_qualification.py | status: pending:#64 -->

Evaluate 100-paper acquisition feasibility and modeling coverage/class-count gates separately, using intended selection denominators and original-feature eligibility. Then evaluate per-head calibration and locked Brier improvement with the specified three-comparison correction. Preserve exclusions, costs, sparse slice failures and correlated outcomes. Missing semantic annotations are not a failure because they are not required. A failed target cannot gain a qualified status from the success of another.

#### TDD-1.1.18 Bundle compatibility gate

<!-- id: TDD-1.1.18 | implements: FT-23 | code: src/research_agent/learning/bundles.py#validate_bundle | tests: tests/learning/test_bundles.py | status: pending:#64 -->

A bundle is a content-addressed manifest containing target definitions, representation identity, numeric head/calibrator artifacts and evaluation reports. Validate hashes, expected dimensions, finite coefficients, calibration status and target version before publishing it. Each target entry is qualified with an artifact or unavailable with a reason. Retained older artifacts are accepted only when their representation and target identity match the new manifest; they are explicit members, not mutable pointers.

#### TDD-1.1.19 Per-head and three-head readiness

<!-- id: TDD-1.1.19 | implements: FT-24 | code: src/research_agent/learning/readiness.py#forecast_readiness | tests: tests/learning/test_readiness.py | status: pending:#64 -->

Expose engineering-ready, per-target-qualified, all-three-qualified and mature-prospective-evaluation separately. Empty registry permits source collection and cards. Two qualified heads expose two probabilities plus an unavailable third, but cannot satisfy all-three readiness. Keep original-paper Jev and platform gates independent. Artifact existence or successful process exit cannot stand in for model qualification.

#### TDD-1.1.20 Correction dependency graph

<!-- id: TDD-1.1.20 | implements: FT-25 | code: src/research_agent/artifacts/lineage.py#apply_correction | tests: tests/artifacts/test_corrections.py | status: pending:#64 -->

Append corrections referencing superseded source, label or representation ids and enumerate dependent corpus, bundle and report manifests. Mark affected evaluation stale and enqueue replacement qualification. Preserve prior bytes and sealed predictions. Critical invalidation withdraws the affected target atomically until requalified. New representations create a separate namespace; no human review artifact is required.

#### TDD-1.1.21 Atomic serving pointer

<!-- id: TDD-1.1.21 | implements: PL-14 | code: src/research_agent/models/registry.py#activate_bundle | tests: tests/models/test_activation.py | status: pending:#64 -->

Commit verified bundle bytes before one transactional compare-and-swap of the active bundle id. Inference acquires one manifest at request start and holds it until completion. Old manifests remain addressable for sealed snapshots. Test concurrent inference across promotion and crashes before and after pointer commit; each response resolves to one fully verified manifest. Storage locking and transaction implementation are pinned with the platform toolchain under #43.

#### TDD-1.1.22 Three named head outputs

<!-- id: TDD-1.1.22 | implements: RD-08 | code: src/research_agent/models/predict.py#predict_targets | tests: tests/models/test_predictions.py | status: pending:#64 -->

Accept original paper/version id and pinned bundle id. Construct the matching [2d] vector and evaluate each qualified head/calibrator in registry order. Return the three records specified in LEARNING-PROTOCOL.md, with probability or null, status/reason, exact question/target version and shared bundle provenance. Distinguish retrospective estimates from prospective-eligible forecasts. Reject dimension mismatches before multiplication. No raw vector or aggregate quality score enters the card; unavailable heads never suppress readable text.

#### TDD-1.1.23 Prospective head evaluation

<!-- id: TDD-1.1.23 | implements: IN-38 | code: src/research_agent/measurement/heads.py#evaluate_predictions | tests: tests/measurement/test_head_evaluation.py | status: pending:#64 -->

Join persisted predictions and their bundle memberships to automatically resolved label versions. Exclude recomputed predictions, fitting/tuning/calibration families and preexisting or ambiguous pre-seal events. Report each target separately: Brier loss, paired baseline skill, average precision, reliability bins and missingness. Group intervals by publication week with families inseparable. Retrospective graph reconstruction and public-model contamination limitations remain distinct from valid prospective records.

#### TDD-1.1.24 Weekly stage state machine

<!-- id: TDD-1.1.24 | implements: FT-16 | code: src/research_agent/orchestration/weekly.py#run_week | tests: tests/orchestration/test_weekly.py | status: pending:#64 -->

Use a persisted weekly id and freeze watermark to make each stage idempotent. Complete freeze, fitting, calibration, scoring, the selection-disabled record and report in order. FT-14 prevents launch parent draws and performance replacements. Treat model candidate rejection and insufficient data as terminal stage outcomes that allow reporting with the incumbent; treat corrupt source or ledger integrity as dependency failure. Resume from the last committed stage, not by rerunning submitted forecasts. Test a fit crash and a broken chain as different paths.

#### TDD-1.1.25 preserve source-linked passage embeddings alongside paper overview embeddings

<!-- id: TDD-1.1.25 | implements: RD-25 | code: src/research_agent/retrieval/passages.py#build_passages | tests: tests/retrieval/test_passages.py | status: pending:#68 -->

Apply the representations, coverage and chunking rules in RETRIEVAL-PROTOCOL.md. Keep versioned source spans, section paths, extraction coverage and compatible model identities; do not silently truncate or replace the passage index with only a pooled vector. Preserve passage vectors alongside the separate FT-09 pool. A real extracted document is chunked across a long section and a short appendix; every included token is covered, overlap is bounded, and source spans reconstruct the passages. Planned owner only; no implementation exists. Storage bindings remain under #43.

#### TDD-1.1.26 Passage search must obey the run snapshot and bounded deterministic ranking

<!-- id: TDD-1.1.26 | implements: RD-26 | code: src/research_agent/retrieval/passages.py#search_passages | tests: tests/retrieval/test_passages.py | status: pending:#68 -->

Apply the query, cosine ranking, family/version selection, tie order, non-overlap and result limits in RETRIEVAL-PROTOCOL.md through the existing tool. An exact cosine reference comparison catches ranking drift, duplicated overlapping hits and a revised paper inserted after the snapshot. Planned owner only; no implementation exists. Storage bindings remain under #43.

#### TDD-1.1.27 Paper-card responses must expose full-paper evidence as source-linked query attachments

<!-- id: TDD-1.1.27 | implements: RD-27 | code: src/research_agent/retrieval/passages.py#attach_evidence | tests: tests/retrieval/test_passages.py | status: pending:#68 -->

Keep the base card immutable and attach exact matching text, score, source location, query identity and coverage using RETRIEVAL-PROTOCOL.md. Deep reading resolves the surrounding source; no raw vectors or quality probabilities are inferred. Two queries produce distinct evidence attachments while preserving the same base-card hash; each attachment reproduces its cited source bytes. Planned owner only; no implementation exists. Storage bindings remain under #43.

#### TDD-1.1.28 Passage-index publication must preserve cache identity and historical snapshots

<!-- id: TDD-1.1.28 | implements: RD-28 | code: src/research_agent/retrieval/passages.py#publish_index | tests: tests/retrieval/test_passages.py | status: pending:#68 -->

Apply the cache and atomic publication rules in RETRIEVAL-PROTOCOL.md. Reuse unchanged passage artifacts and keep prior snapshot memberships accessible. Qualify study use through the recorded comparison under SR-17 and SR-18. Interrupt an index build, resume it, and verify unchanged vectors are reused and an older run still reads only its original index. Planned owner only; no implementation exists. Storage bindings remain under #43.
