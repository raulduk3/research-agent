# Technical Design Description

How the software is built to meet each requirement, item by item, with the code and tests that carry it.

## Document control

| Field               | Value                                                                                                                                |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Product             | research-agent.                                                                                                                |
| Target version      | Planned first application release; full SDD coverage, with planned implementation owners.                                                                                                 |
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

The shared implementation boundary is [TDD-CONTRACTS.md](TDD-CONTRACTS.md): identity, storage ownership, typed APIs, permissions, transaction order and lifecycle. The [detailed contract catalog](contracts/INDEX.md) supplies exact schemas, service request/response shapes, storage constraints, algorithms and failure cases. The items below specialize those contracts; named source and test files are planned, not implemented.

## 1. Historical learning and evidence

### 1.1 Corpus, labels and qualified prediction heads

These items define the learning subsystem. Code and test paths name planned owners, not existing implementations. Python module names establish a concrete package boundary; runtime, storage ownership and check commands are fixed in LAUNCH-PROFILE.md; implementation builds lock and test the dependency/image manifests. Decision #77 reconciles the final launch contracts; this document maps the complete SDD and #71 tracks integration review.

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

Commit verified bundle bytes before one transactional compare-and-swap of the active bundle id. Inference acquires one manifest at request start and holds it until completion. Old manifests remain addressable for sealed snapshots. Test concurrent inference across promotion and crashes before and after pointer commit; each response resolves to one fully verified manifest. Use the storage-owned PostgreSQL transaction and immutable artifact commit protocol in LAUNCH-PROFILE.md.

#### TDD-1.1.22 Three named head outputs

<!-- id: TDD-1.1.22 | implements: RD-08 | code: src/research_agent/models/predict.py#predict_targets | tests: tests/models/test_predictions.py | status: pending:#64 -->

Accept original paper/version id and pinned bundle id. Construct the matching [2d] vector and evaluate each qualified head/calibrator in registry order. Return the three records specified in LEARNING-PROTOCOL.md, with probability or null, status/reason, exact question/target version and shared bundle provenance. Distinguish retrospective estimates from prospective-eligible forecasts. Reject dimension mismatches before multiplication. No raw vector or aggregate quality score enters the card; unavailable heads never suppress readable text.

Persist PredictionArtifact with each raw pre-calibration linear logit, calibrated probability, target/bundle/representation ids, input hash and computed_at/available_at. A card references the artifact but displays only the public probability/provenance contract. The baseline service receives only a typed time-safe scalar projection; no historical recomputation or scorer access to vectors. Test raw-logit and probability lineage and denial of raw values in agent/rater projections.

#### TDD-1.1.23 Prospective head evaluation

<!-- id: TDD-1.1.23 | implements: IN-38 | code: src/research_agent/measurement/heads.py#evaluate_predictions | tests: tests/measurement/test_head_evaluation.py | status: pending:#64 -->

Join persisted predictions and their bundle memberships to automatically resolved label versions. Exclude recomputed predictions, fitting/tuning/calibration families and preexisting or ambiguous pre-seal events. Report each target separately: Brier loss, paired baseline skill, average precision, reliability bins and missingness. Group intervals by publication week with families inseparable. Retrospective graph reconstruction and public-model contamination limitations remain distinct from valid prospective records.

#### TDD-1.1.24 Weekly stage state machine

<!-- id: TDD-1.1.24 | implements: FT-16 | code: src/research_agent/orchestration/weekly.py#run_week | tests: tests/orchestration/test_weekly.py | status: pending:#64 -->

Use a persisted weekly id and freeze watermark to make each stage idempotent. Complete freeze, fitting, calibration, scoring, the selection-disabled record and report in order. FT-14 prevents launch parent draws and performance replacements. Treat model candidate rejection and insufficient data as terminal stage outcomes that allow reporting with the incumbent; treat corrupt source or ledger integrity as dependency failure. Resume from the last committed stage, not by rerunning submitted forecasts. Test a fit crash and a broken chain as different paths.

#### TDD-1.1.25 preserve source-linked passage embeddings alongside paper overview embeddings

<!-- id: TDD-1.1.25 | implements: RD-25 | code: src/research_agent/retrieval/passages.py#build_passages | tests: tests/retrieval/test_passages.py | status: pending:#68 -->

Apply the representations, coverage and chunking rules in RETRIEVAL-PROTOCOL.md. Keep versioned source spans, section paths, extraction coverage and compatible model identities; do not silently truncate or replace the passage index with only a pooled vector. Preserve passage vectors alongside the separate FT-09 pool. A real extracted document is chunked across a long section and a short appendix; every included token is covered, overlap is bounded, and source spans reconstruct the passages. Planned owner only; no implementation exists. Storage ownership and immutable manifests follow LAUNCH-PROFILE.md.

#### TDD-1.1.26 Passage search must obey the run snapshot and bounded deterministic ranking

<!-- id: TDD-1.1.26 | implements: RD-26 | code: src/research_agent/retrieval/passages.py#search_passages | tests: tests/retrieval/test_passages.py | status: pending:#68 -->

Apply the query, cosine ranking, family/version selection, tie order, non-overlap and result limits in RETRIEVAL-PROTOCOL.md through the existing tool. An exact cosine reference comparison catches ranking drift, duplicated overlapping hits and a revised paper inserted after the snapshot. Planned owner only; no implementation exists. Storage ownership and immutable manifests follow LAUNCH-PROFILE.md.

#### TDD-1.1.27 Paper-card responses must expose full-paper evidence as source-linked query attachments

<!-- id: TDD-1.1.27 | implements: RD-27 | code: src/research_agent/retrieval/passages.py#attach_evidence | tests: tests/retrieval/test_passages.py | status: pending:#68 -->

Keep the base card immutable and attach exact matching text, score, source location, query identity and coverage using RETRIEVAL-PROTOCOL.md. Deep reading resolves the surrounding source; no raw vectors or quality probabilities are inferred. Two queries produce distinct evidence attachments while preserving the same base-card hash; each attachment reproduces its cited source bytes. Planned owner only; no implementation exists. Storage ownership and immutable manifests follow LAUNCH-PROFILE.md.

#### TDD-1.1.28 Passage-index publication must preserve cache identity and historical snapshots

<!-- id: TDD-1.1.28 | implements: RD-28 | code: src/research_agent/retrieval/passages.py#publish_index | tests: tests/retrieval/test_passages.py | status: pending:#56 -->

Apply the cache and atomic publication rules in RETRIEVAL-PROTOCOL.md. Reuse unchanged passage artifacts and keep prior snapshot memberships accessible. Qualify study use through the recorded comparison under SR-17 and SR-18. Interrupt an index build, resume it, and verify unchanged vectors are reused and an older run still reads only its original index. Planned owner only; no implementation exists. Storage ownership and immutable manifests follow LAUNCH-PROFILE.md.

## 2. Platform and durable state

### 2.1 Contracts

The following planned Python owners use storage-owned durable state and versioned HTTP contracts. TDD-CONTRACTS.md owns the shared identifiers, HTTP errors and storage boundaries. Deployment acceptance tests exercise disposable real containers and PostgreSQL; default unit checks do not claim that deployed boundaries have passed.

#### TDD-2.1.1 Executable component inventory

<!-- id: TDD-2.1.1 | implements: SR-01 | code: src/research_agent/platform/inventory.py#ComponentInventory | tests: tests/platform/test_inventory.py | status: pending:#5 -->

Load a strict, versioned inventory whose rows contain component_id, role, layer, image_digest, interface_ids and mode membership. Batch rows instead carry input/output layer ids. Assign runtime/observation, environment, agent workers, reader and shared models to the ordered five layers. At readiness, compare Compose project labels and container inspection results with the inventory, ignoring unrelated host projects. Missing, duplicate or extra project components block that mode. Persist the inventory hash through storage. A real Compose acceptance test introduces an undeclared project service and verifies refusal; a schema test rejects both zero and two service-layer assignments.

#### TDD-2.1.2 Externally captured conduct trace

<!-- id: TDD-2.1.2 | implements: SR-02 | code: src/research_agent/tools/trace.py#TraceWriter | tests: tests/tools/test_trace_capture.py | status: pending:#5 -->

The shared tool service allocates a monotonic per-run call sequence through storage before executing each request. Trace entries contain run_id, call_id, request_hash, schema decision, start/end timestamps, response_hash, retrieved artifact ids and budget deltas; refused calls are entries too. Append a terminal response or error event rather than editing the request event. Sealing requires successful complete receipts for cited retrievals and no unresolved earlier tool call. The current submit request is exempt from that prior-receipt test: its terminal receipt commits atomically with forecasts, nominations and terminal run state. A pending earlier call still blocks sealing. Agent-written summaries have no authority over trace fields. Exercise the actual HTTP tool path with an invented read in agent text and confirm conduct inspection reports only the separately captured retrieval events.

#### TDD-2.1.3 Model-free production scoring boundary

<!-- id: TDD-2.1.3 | implements: SR-03 | code: src/research_agent/scoring/service.py#ScoringService | tests: tests/scoring/test_model_free.py | status: pending:#56 -->

Give the scorer storage read access to sealed forecasts, resolver records and preregistration, plus narrowly authorized append access for computed score records. Its dependency graph contains pure numeric functions, not model clients; its container egress lists storage only. Evaluation outputs include function version and ordered ledger input hashes. Unresolved and void records produce exclusion reasons rather than guessed labels. ForeSci artifacts occupy a development namespace denied to the production score input schema. Run an integration fixture with model endpoints unreachable, verify exact numeric parity, then attempt a model connection from the real scorer network namespace and verify denial.

#### TDD-2.1.4 Separate proposal and authority types

<!-- id: TDD-2.1.4 | implements: SR-04 | code: src/research_agent/contracts/authority.py#AuthorityPolicy | tests: tests/contracts/test_authority.py | status: pending:#56 -->

Define distinct versioned Proposal, SourceObservation, Resolution, Score and ExclusionRecord schemas. Storage accepts each authoritative record only from its named resolver/scorer/operator role and checks source lineage, never an agent-supplied role field. Model outputs can populate proposal or assessment artifacts but cannot satisfy authoritative resolution inputs. OpenAlex taxonomy is preserved as a source observation with proxy provenance, not as a model adjudication. Selection/mutation routes are disabled. Tests submit a valid-looking resolution with an agent token, and route a Jev answer into a resolver: both fail before append. Deterministic resolution and sanction tests run with all model networks disabled.

#### TDD-2.1.5 Strict untrusted request admission

<!-- id: TDD-2.1.5 | implements: SR-05 | code: src/research_agent/tools/admission.py#admit_request | tests: tests/tools/test_admission.py | status: pending:#56 -->

Resolve the run from the authenticated short-lived capability rather than trusting request run_id. Require the strict tool envelope and exact allowed schema version; compare run_id, snapshot_id, tool name, active state and remaining budget against the stored run specification. Reject unknown keys, coercions and protected-field writes as one request, recording refusal externally. Any invalid submit attempt is refused atomically: append a rejection audit with the request hash and field errors, seal no forecasts, and allow correction within the remaining run budget and deadline. Exercise a cross-run token, a disallowed tool and a payload with an extra configuration field; verify no ledger proposal or configuration mutation occurs.

#### TDD-2.1.6 Restrict consumers of agent records

<!-- id: TDD-2.1.6 | implements: SR-06 | code: src/research_agent/storage/authorization.py#AgentOutputPolicy | tests: tests/storage/test_agent_output_policy.py | status: pending:#56 -->

Assign agent output artifacts a restricted record kind. Storage permits the sealing/resolution/scoring path and authorized human presentation projections to read them; reader, ingest, model fitting and other workers cannot retrieve their hashes or payloads through generic artifact endpoints. Orchestration reads lifecycle status and budget metadata, not agent prose. A digest projection is produced within the human-output path and preserves provenance. Enforce authorization both on manifest lookup and byte streaming so knowledge of a hash grants no access. Integration tests request the same artifact as each service identity and verify the denied callers receive no body or cross-run metadata.

#### TDD-2.1.7 Render recorded fields without rewriting

<!-- id: TDD-2.1.7 | implements: SR-26 | code: src/research_agent/web/rendering.py#RecordedFieldRenderer | tests: tests/web/test_recorded_rendering.py | status: pending:#56 -->

Construct presentation DTOs from allowed ledger fields and fixed UI labels, then use Jinja autoescaping without Markdown execution or generated prose. Store field source pointers in the internal projection so displayed text can be checked against its ledger source after HTML escaping is reversed. The app has no model client or model-network route. Rationale text, title and unavailable states remain verbatim recorded values, subject to the rater-specific disclosure projection. Tests use hostile HTML and Unicode text to verify safe rendering without semantic rewriting, and reject a projection field whose value is not the referenced record value.

#### TDD-2.1.8 Bind forecast evidence to retrieved artifacts

<!-- id: TDD-2.1.8 | implements: SR-07 | code: src/research_agent/environment/sealing.py#validate_evidence | tests: tests/environment/test_sealing_evidence.py | status: pending:#77 -->

Build a retrieved-id set from completed successful tool trace responses for the authenticated run and pinned snapshot; an id being present in the snapshot is insufficient. Require one to five evidence ids per forecast, reject duplicates under the submission schema, and resolve each to its exact snapshot artifact locator. A failed trace read aborts acceptance rather than trusting incomplete data. Any absent or unrequested evidence id rejects the complete submit attempt, recording safe field errors and its request hash without sealing siblings. Test an actually retrieved span, an unrequested snapshot span and another run's span; a corrected attempt can succeed only within the original budget and deadline.

#### TDD-2.1.9 Bind statements to immutable question definitions

<!-- id: TDD-2.1.9 | implements: SR-08 | code: src/research_agent/environment/sealing.py#bind_question | tests: tests/environment/test_question_binding.py | status: pending:#77 -->

A forecast names question_id; the sealer resolves its target definition and resolver through the run's immutable batch manifest rather than interpreting agent free text or accepting agent-supplied authority fields. Accepted ledger records store the derived question hash, target definition hash and resolver identity. Launch questions are exactly the three admitted citation predicates; nominations remain separate and cannot create questions. An unissued, duplicate or missing required answer rejects the complete attempt and records field errors. Tests submit another shard's question and an extra resolver override, verify zero sealed siblings, and then submit a valid correction within the remaining run allowance.

#### TDD-2.1.10 Derive immutable question horizons

<!-- id: TDD-2.1.10 | implements: SR-09 | code: src/research_agent/environment/sealing.py#validate_horizon | tests: tests/environment/test_horizon_binding.py | status: pending:#77 -->

Resolve horizon metadata from each issued question's immutable definition: verified first-public origin, the 365-day event end and separate 90-day maturity allowance. The agent does not supply or choose a horizon; strict submit parsing rejects a horizon override as an extra field. Accepted ledger forecasts persist the derived interval and definition hash alongside their question id. An unresolved or inconsistent question manifest prevents acceptance of the entire attempt rather than inventing timing. Tests reject a 455-day question event window and an agent horizon override, and verify a valid accepted forecast stores the exact question-derived 365-day interval.

#### TDD-2.1.11 Preserve finite submitted probabilities

<!-- id: TDD-2.1.11 | implements: SR-10 | code: src/research_agent/environment/sealing.py#validate_probability | tests: tests/environment/test_probability_binding.py | status: pending:#77 -->

Require a JSON numeric probability that is finite and within the closed interval [0,1], retaining its canonical numeric value in accepted ledger records. Booleans, numeric strings, omission, nonfinite extensions and out-of-range values reject the complete submit attempt before any forecast is sealed. Record its request hash and safe field errors; never clip, fill a head estimate or create a partial accepted submission. Tests cover both endpoints, a round-trip-precision interior value and invalid sibling values, proving zero forecast writes on rejection and no budget reset or deadline extension when correction is attempted.

#### TDD-2.1.12 Atomic complete submission acceptance

<!-- id: TDD-2.1.12 | implements: SR-11 | code: src/research_agent/storage/submissions.py#commit_submission | tests: tests/storage/test_submission_atomicity.py | status: pending:#77 -->

Validate the complete submission before acceptance. On any schema or semantic error, append a submission_rejected audit containing run_id, attempt request hash and bounded field errors, and create no forecast or nomination rows. Rejection consumes the tool call and returns remaining budgets; a correction uses a fresh attempt identity within the same run and deadline. A valid complete attempt atomically commits receipt, all forecasts and nominations under one transaction; identical accepted retries return the receipt without duplicate effects. If the run ends or expires without acceptance, record terminal run void rather than partial forecasts. Test invalid-sibling rollback, successful correction, expiry refusal and crash-safe idempotent acceptance.

#### TDD-2.1.13 Bound rationale and gate its disclosure

<!-- id: TDD-2.1.13 | implements: SR-24 | code: src/research_agent/contracts/submission.py#ForecastRationale | tests: tests/contracts/test_rationale.py | status: pending:#56 -->

Make rationale a required Unicode string with length at most 2000 code points in the strict submission schema; apply canonical NFC serialization and never silently truncate the recorded field. Evidence ids are separately bounded to five. Schema failure rejects the entire call before any forecast append. The canonical stored rationale is outside the resolver statement and score DTO. The rating projection includes it only when storage proves that this authenticated rater has rated this digest entry. Tests cover missing/overlong rationale, concurrent rating by the other rater, and equal numeric scores for records differing only in rationale.

#### TDD-2.1.14 Worker capabilities and two-destination isolation

<!-- id: TDD-2.1.14 | implements: SR-12 | code: src/research_agent/platform/isolation.py#WorkerIsolation | tests: tests/platform/test_worker_isolation.py | status: pending:#57 -->

Provision each worker with a run-scoped tool capability and model-proxy credential only. Attach it to dedicated tool and inference-proxy network paths; do not attach the application service network, data volumes, Docker socket or host network. Host firewall rules allow the shared tool service and the pinned proxy endpoints and deny other destinations, including direct model-service addresses and link-local host metadata. Apply and verify rules before launching the worker process. Container acceptance tests attempt storage HTTP, PostgreSQL, model-service HTTP, arbitrary internet and host gateway access, while permitted tools and inference calls remain reachable.

#### TDD-2.1.15 Explicit external egress roles

<!-- id: TDD-2.1.15 | implements: SR-13 | code: src/research_agent/platform/network.py#EgressManifest | tests: tests/platform/test_external_egress.py | status: pending:#56 -->

Represent deployment-bound endpoints as scheme, hostname, port, resolved addresses and TLS identity in an immutable egress manifest. Route ingest external requests through its source allowlist, workers through the inference proxy, and storage through the backup/anchor receiver. Resolve allowed names outside untrusted workers; block DNS rebinding to private or metadata destinations except explicitly bound private receiver routes. Rating HTTP listens only on its configured private interface. Start is refused when rules cannot be installed. Test with controlled allowed and denied servers from each actual container, including that storage cannot reach an ingest source and the rating app cannot call the internet.

#### TDD-2.1.16 Append-only transactional ledger

<!-- id: TDD-2.1.16 | implements: SR-14 | code: src/research_agent/storage/ledger.py#LedgerRepository | tests: tests/storage/test_ledger_append_only.py | status: pending:#5 -->

Use ledger_records(sequence bigint primary key, record_id uuid unique, kind, schema_version, canonical_payload bytea, previous_hash, record_hash, created_at). Storage appends under a serializable transaction with a locked chain-head row; serialization conflicts retry the same idempotent operation. Its application database role has SELECT/INSERT but no UPDATE/DELETE on ledger_records, with migrations using a separate operator role. No public mutation endpoint exists. Hash checks use canonical stored bytes. Tests use real PostgreSQL to attempt UPDATE/DELETE through both API and application role, and concurrent appends to verify one gap-free predecessor chain and no partial writes.

#### TDD-2.1.17 Snapshot-derived immutable run stamp

<!-- id: TDD-2.1.17 | implements: SR-15 | code: src/research_agent/orchestration/stamps.py#build_run_stamp | tests: tests/orchestration/test_run_stamp.py | status: pending:#64 -->

Before issuing worker credentials, resolve the run specification and card manifest through storage, collect all producing bundle ids, and freeze image digests, configuration hash, seed, agent deployment manifest, snapshot hash and execution mode. Read producing-model identities from the snapshot's artifact DAG, never the active model pointer. Represent absent deferred encoder and unavailable heads explicitly. Store the stamp before the first provider call and include its hash in trace entries. An unresolved required artifact blocks start. Test queued snapshot A after active bundle B promotion and verify every producing-model reference remains A.

#### TDD-2.1.18 Externally immutable chain-head receipts

<!-- id: TDD-2.1.18 | implements: SR-16 | code: src/research_agent/storage/anchors.py#AnchorClient | tests: tests/storage/test_anchor_receipts.py | status: pending:#56 -->

Storage tracks last_receipted_sequence and last_receipted_at and schedules anchoring after 100 new records or 15 minutes. Send sequence, record hash, profile id and an idempotency key to the separate receiver; retain its authenticated receipt as an immutable artifact. Receiver authority permits append/read only and rejects replacement or decreasing sequence. A timeout does not advance the acknowledged watermark. Sealing checks whether unanchored prospective records exceed the 30-minute backlog bound and refuses new seals while preserving capture. Test receiver outage/recovery and a recomputed altered ledger copy against an independently retained receipt.

#### TDD-2.1.19 Content-addressed dependency provenance

<!-- id: TDD-2.1.19 | implements: SR-23 | code: src/research_agent/storage/artifacts.py#ArtifactManifest | tests: tests/storage/test_artifact_provenance.py | status: pending:#56 -->

Every derived artifact commit carries schema_version, SHA-256 artifact_hash, ordered input_hashes, producer_version, config_hash, created_at and actual available_at, plus separate source clocks where applicable. Storage verifies byte hashes and existence/authorization of input manifests before publishing the manifest; caller-provided paths are never accepted. Blob bytes are streamed into a temporary file, fsynced and renamed before the transaction publishes references. Repeated identical content reuses its address, with distinct producing manifests when provenance differs. Tests mutate an input copy and detect the mismatch, omit one dependency and reject commit, and crash before the reference transaction without exposing a usable artifact.

#### TDD-2.1.20 Evidence-gated layer activation

<!-- id: TDD-2.1.20 | implements: SR-17 | code: src/research_agent/platform/readiness.py#LayerAdmission | tests: tests/platform/test_layer_admission.py | status: pending:#77 -->

Maintain an immutable admission record naming layer id, baseline configuration hash, candidate hash, registered primary metric, comparison report ids and activation scope. The gate verifies baseline/candidate comparability and temporal precedence from stored registration and execution provenance; it does not treat a green unit test as a measured baseline. Jev follows its explicit qualification plus preregistration exception, without waiting for future citation maturity. Future heads and disabled evolution remain denied irrespective of a caller flag. Tests reject a missing baseline, wrong-metric report, post-hoc registration and unqualified Jev rubric, while accepting the named Jev exception with immature citation outcomes.

#### TDD-2.1.21 Immutable comparison registration

<!-- id: TDD-2.1.21 | implements: SR-18 | code: src/research_agent/evaluation/registrations.py#ComparisonRegistration | tests: tests/evaluation/test_registration_gate.py | status: pending:#77 -->

Define a strict registration with hypothesis, population and split hashes, primary metric, direction, pass/kill criteria, minimum effect, exclusions, sample size, failure handling and stop rule. Canonicalize and hash it before accepting the first comparison job. Storage enforces that each job references the immutable registration and records its start after registration availability. Changed analysis receives a new exploratory identity, never overwrites the original. Pre-runtime signed registration imports preserve original date, signature evidence and later import time separately. Tests reject registrations created after first execution, mismatched metric hashes and modification under an existing registration id.

#### TDD-2.1.22 Retained supersession lineage

<!-- id: TDD-2.1.22 | implements: SR-19 | code: src/research_agent/storage/versions.py#SupersessionRecord | tests: tests/storage/test_supersession.py | status: pending:#5 -->

Versioned configurations and decisions are immutable records; replacement appends a supersession edge old_hash -> new_hash with reason, decision id and effective_at. Resolve current choices through that edge while keeping old artifacts addressable for replay. For repository contracts, review tooling compares the changed choice registry with its base and requires either an unchanged entry or a retained old entry with a superseding decision link; ordinary prose edits are not guessed to be machine-detectable choices. Reject cycles and dangling replacements. Tests demonstrate that activating a new configuration preserves the old configuration's bytes and that deletion or unmarked id reuse fails.

#### TDD-2.1.23 Dated external verification registry

<!-- id: TDD-2.1.23 | implements: SR-20 | code: src/research_agent/contracts/verification.py#VerificationRecord | tests: tests/contracts/test_verification_registry.py | status: pending:#5 -->

Store one verification entry per borrowed component or relied-on result, keyed by artifact/source identity, with source URL, checked_at UTC, verifier reference, content hash when permitted and status verified/unverified. Model selection and citation manifests reference these entries; a publication date is not used as checked_at. Missing evidence makes the entry explicitly unverified and prevents a readiness claim that depends on it. Document validation resolves registered named components/results against this registry. Tests distinguish unknown verification from a dated check and reject a reference whose immutable component revision differs from the verified one.

#### TDD-2.1.24 Accuracy obligations as scheduled records

<!-- id: TDD-2.1.24 | implements: SR-27 | code: src/research_agent/evaluation/accuracy.py#AccuracyRegistry | tests: tests/evaluation/test_accuracy_registry.py | status: pending:#56 -->

For each active output-producing component register component_version, metric_definition_hash, reference_manifest, denominator policy, cadence, last_report and next_due_at. Populate acquisition, extraction, resolver, retrieval, heads, Jev, agent calibration and integrity entries from the launch profile. Jobs freeze source and reference watermarks; unresolved outcomes produce explicit insufficient-reference reports rather than fabricated scores. Activation checks registry coverage against the component inventory. Tests add a component without a reference schedule and refuse activation; a resolved/unresolved fixture verifies only eligible known outcomes enter the metric while exclusions retain their original denominator.

#### TDD-2.1.25 Mode-specific complete-profile gate

<!-- id: TDD-2.1.25 | implements: SR-28 | code: src/research_agent/platform/profile.py#LaunchProfile | tests: tests/platform/test_profile_readiness.py | status: pending:#56 -->

Parse one closed, immutable launch profile into runtime, storage, model, source, budget, evaluation, privacy, recovery and disabled-capability groups. Separate deployment bindings and operator funding authorizations from chosen design ceilings. Readiness returns a typed list of unmet gates for collection, engineering or study; collection needs licensed source/storage bindings, engineering adds local model/replay integrity, and study additionally needs all qualification, backup and funded inference prerequisites. Every job/artifact records profile_hash and mode. Unknown override keys are rejected. Parameterized deletion tests remove each required group; integration tests prove collection can operate while study is refused for an unfunded endpoint.

#### TDD-2.1.26 Per-paper blinded human projections

<!-- id: TDD-2.1.26 | implements: SR-21 | code: src/research_agent/web/projections.py#BlindedPaperView | tests: tests/web/test_genome_blinding.py | status: pending:#45 -->

Build a positive-list rater DTO that contains no genome, run, slot or lineage fields. Keep provenance joins inside storage and use paper-specific opaque detail labels generated once for that view from secure randomness, rejecting any reused label across papers in the presented digest. The private mapping supports later analysis but is inaccessible through rater endpoints. Selection ordering is shuffled from the persisted seed before projection. Render two papers from one known configuration and inspect HTML, JSON, links and attributes for forbidden identifiers; verify labels differ and the analyst-side provenance join remains correct.

#### TDD-2.1.27 Uniform origin-blinded digest entry

<!-- id: TDD-2.1.27 | implements: SR-22 | code: src/research_agent/web/projections.py#OriginBlindEntry | tests: tests/web/test_origin_blinding.py | status: pending:#45 -->

Use the same bibliographic pre-rating DTO for nominations, random controls and service picks; origin and selection reason remain storage-only analysis fields. Serialize absent optional content consistently so different array shapes or hidden attributes cannot encode origin. Shuffle after the full merged selection using the recorded digest seed; do not reserve position ranges for controls. Post-rating details still exclude permanent provenance fields. Tests build identical-paper fixtures under each origin and compare their rater-visible pre-rating serialization, then inspect several recorded-seed orders for fixed origin blocks rather than demanding statistically impossible perfect anonymity.

#### TDD-2.1.28 Server-side per-rater disclosure

<!-- id: TDD-2.1.28 | implements: SR-25 | code: src/research_agent/web/projections.py#RatingDisclosure | tests: tests/web/test_rating_disclosure.py | status: pending:#54 -->

Within one storage-backed projection request, read the authenticated rater's accepted rating for (digest_id,paper_id,rater_id). Before it exists, omit probabilities, rationales, popularity counts, Jev fields and origin from the server response entirely; CSS hiding is insufficient. After rating, allow the first four groups while continuing permanent genome/control/service-origin blinding. Use private no-store responses, rater-scoped cache keys or no projection cache, and CSRF-protected writes. Tests rate as A and read as B, inspect raw HTML/network payloads before rating, and verify that A's post-rating response exposes assessments without origin or genome ids.

#### TDD-2.1.29 One role per container

<!-- id: TDD-2.1.29 | implements: PL-01 | code: src/research_agent/platform/compose.py#ComposeInventory | tests: tests/platform/test_component_containers.py | status: pending:#56 -->

Compose assigns a service role and image entrypoint per storage, ingest, reader, models, tools, scorer, orchestrator, app and PostgreSQL container, plus isolated run/batch instances. Share only verified image layers; give each process a private writable temporary filesystem and role-scoped runtime secrets. No shared virtualenv is writable, no container runs multiple application role entrypoints, and ordinary service containers cannot start peers. Reconcile project inventory against actual container labels/process metadata. A disposable-host acceptance check introduces a second role in one container or a shared writable environment and verifies readiness refusal.

#### TDD-2.1.30 Versioned authenticated service contracts

<!-- id: TDD-2.1.30 | implements: PL-02 | code: src/research_agent/contracts/http.py#ServiceContract | tests: tests/contracts/test_service_contracts.py | status: pending:#5 -->

Expose versioned /v1 HTTP/JSON endpoints with strict request/response schemas and role-scoped service authentication. The interface registry lists caller, callee, method, route, schema and authorization scope. Storage is the only PostgreSQL client and artifact volume writer; other services stream authorized bytes by hash rather than filesystem path. Require schema_version and physical units on numeric boundary fields, propagate request ids, and return stable error codes without credentials. Tests use real service HTTP against declared routes and verify wrong-role and unknown-route refusal; container tests verify another role's file paths and database port are unreachable.

#### TDD-2.1.31 Declarative mode startup

<!-- id: TDD-2.1.31 | implements: PL-03 | code: src/research_agent/platform/startup.py#start_mode | tests: tests/platform/test_startup_modes.py | status: pending:#56 -->

The operator entrypoint validates the selected profile and deployment bindings, runs floor/network checks, then starts the selected Compose profile and waits for required health states. Inventory matching is scoped to this Compose project, including declared support database/proxy containers; unrelated host containers are not deleted. The operator-owned host launcher accepts only predeclared immutable worker specifications from authenticated orchestration; workers and ordinary services receive no Docker socket. Record external endpoint identities without provisioning them. A readiness failure leaves cycle scheduling disabled and reports the failed gate, while successful collection mode never implies study readiness. Disposable-host tests start each mode from the declaration, omit a required service, and verify that no ingest/daily cycle is released for the incomplete selected mode.

#### TDD-2.1.32 Applied cgroup resource ceilings

<!-- id: TDD-2.1.32 | implements: PL-04 | code: src/research_agent/platform/resources.py#ResourcePolicy | tests: tests/platform/test_resource_limits.py | status: pending:#56 -->

Generate CPU quota and memory.max settings from the launch role table, declare zero accelerator device mounts for local roles, and inspect applied cgroup values after container creation. Limit two workers and one heavy batch through transactional storage leases. Orchestration measures foreground resident memory outside the batch container, requests checkpoint-and-pause above 48 GiB and resumes below 40 GiB; hard memory limits remain the fallback if a job ignores the request. Tests compare declared versus actual limits and run a memory/CPU stress batch beside a health-probed service to verify containment rather than merely checking Compose text.

#### TDD-2.1.33 Health state machine

<!-- id: TDD-2.1.33 | implements: PL-05 | code: src/research_agent/platform/health.py#HealthMonitor | tests: tests/platform/test_health_monitor.py | status: pending:#5 -->

Each service exposes /health/live and /health/ready; readiness checks its critical event loop and required local dependencies rather than only process existence. The supervisor polls every 30 seconds, distinguishes initial waiting from a previously healthy service, and marks failed after three consecutive failed polls. Initial model load has a 15-minute bound. Recovery attempts follow 10/30/90-second delays and then latch an operator-repair state. Store transitions through storage when available and retain host supervisor diagnostics during storage failure. Test a running process with a stalled worker loop and a deliberately slow initial load to distinguish failed from waiting.

#### TDD-2.1.34 Reproducible build and run identities

<!-- id: TDD-2.1.34 | implements: PL-06 | code: src/research_agent/platform/builds.py#BuildManifest | tests: tests/platform/test_build_manifest.py | status: pending:#5 -->

The build manifest includes source tree hash, Python/tool versions, uv lock hash, base-image digest, package hashes and selected model/runtime identities. Fail unresolved tags, unconstrained dependencies or missing lock artifacts before producing a releasable image. Embed product version and manifest hash as OCI labels; record the running image digest separately because a human tag is mutable. Run stamps inspect actual selected containers rather than trusting build configuration. Tests reject a floating base image and altered lock hash, then start containers and verify their observed image digests and labels appear in the run stamp.

#### TDD-2.1.35 Runtime-only scoped secret files

<!-- id: TDD-2.1.35 | implements: PL-07 | code: src/research_agent/platform/secrets.py#SecretBindings | tests: tests/platform/test_secret_injection.py | status: pending:#5 -->

Deployment bindings name secret references, not values. Mount each needed credential read-only into its single consumer at startup using runtime secret files; never pass it in build arguments, image environment layers or logged command lines. Validate presence and permissions before readiness, and configure error serialization to report only the reference id. Scan image layers, history, build context and rendered Compose using synthetic test credentials that exercise the exact injection path. The scanner fails on any occurrence while logs are inspected for redaction. Actual production secret values are never copied into test fixtures or committed build inputs.

#### TDD-2.1.36 Stateless shared tools with external authority

<!-- id: TDD-2.1.36 | implements: PL-20 | code: src/research_agent/tools/service.py#ToolService | tests: tests/tools/test_cross_run_isolation.py | status: pending:#57 -->

One shared tools service resolves each authenticated run specification and snapshot from storage. It keeps no mutable conversation state; durable call budgets, retrieved ids and trace events belong to storage with atomic reservation before work. Cache only immutable content keyed by snapshot_hash, representation_hash, tool version and normalized arguments, and reapply authorization before returning cached bytes. Submission uses the same service but is forwarded to the storage-owned commit boundary through the sealer. Concurrent integration tests seed distinguishable run-specific arguments and verify no response, error or budget count leaks into the other run.

#### TDD-2.1.37 Snapshot-keyed indexes without latest fallback

<!-- id: TDD-2.1.37 | implements: PL-21 | code: src/research_agent/tools/snapshots.py#SnapshotIndex | tests: tests/tools/test_snapshot_pinning.py | status: pending:#57 -->

Resolve the snapshot by exact content hash before any index lookup. Cache index entries under (snapshot_hash, representation_id, index_schema_version), verifying the stored membership manifest and artifact hashes. A missing/corrupt old index is rebuilt only from that same snapshot or returns unavailable; it never redirects to the latest snapshot. Acquire an immutable index handle for the request lifetime so cache eviction cannot change its membership midway. Test snapshots A and B with one added highly similar paper and query A after B loads; both direct cards and neighbor/passage paths must exclude B-only content.

#### TDD-2.1.38 Single shared model-serving owner

<!-- id: TDD-2.1.38 | implements: PL-08 | code: src/research_agent/models/service.py#ModelService | tests: tests/models/test_single_serving_owner.py | status: pending:#64 -->

The shared model service owns the single serving instance of the frozen embedder and qualified numeric head bundles. Reader and tools call typed embedding/prediction endpoints; workers have no route or token. Requests name representation/bundle identity and return producing identity with output. Batch jobs may fit numeric heads but request encoding from the same service rather than loading another serving embedder. A missing model process or incompatible manifest yields unavailable, not local fallback. Compose inspection plus request tracing in a multi-worker acceptance test verifies one serving process and that all returned model artifacts originated from it.

#### TDD-2.1.39 Weight-free worker images and mounts

<!-- id: TDD-2.1.39 | implements: PL-09 | code: src/research_agent/platform/workers.py#WorkerImagePolicy | tests: tests/platform/test_weight_free_workers.py | status: pending:#57 -->

Build a small worker image containing the model HTTP client, strict tool loop and contract code only. Exclude training/inference packages, model cache paths and artifact/model volumes from its image/mount allowlist. Set no writable Hugging Face cache mount and prohibit internet model-download destinations through host isolation. Admission verifies image manifest and attached volumes, not only a filename pattern. Tests inspect the built image and attempt actual opens on model paths and network fetches inside a worker; permitted model endpoint calls still succeed and return no application storage authority.

#### TDD-2.1.40 Operator preflight floor attestation

<!-- id: TDD-2.1.40 | implements: PL-10 | code: src/research_agent/platform/preflight.py#HostFloorReport | tests: tests/platform/test_host_floor.py | status: pending:#77 -->

Before Compose starts application services, the operator CLI measures logical CPUs, physical RAM, persistent filesystem capacity/free bytes and accelerator inventory through OS interfaces. Compare with 16 threads, 64 GiB, 1 TiB SSD and 500 GiB initial free space, with zero required local GPUs. Generate a dated, hashed preflight report outside application state, retain it as operator startup evidence, then import through storage after successful start; this exception creates no alternate application writer. Unknown storage medium/capacity is not a pass. A disposable-host test raises one floor above the measured value and verifies no application container is started.

#### TDD-2.1.41 Independent foreground and batch scheduling

<!-- id: TDD-2.1.41 | implements: PL-12 | code: src/research_agent/orchestration/scheduler.py#WorkScheduler | tests: tests/orchestration/test_foreground_progress.py | status: pending:#57 -->

Storage job records distinguish foreground capture/batch issuance/run/resolution work from checkpointable heavy jobs. The orchestrator reserves their separate concurrency lanes and never places a daily dependency edge on an in-progress fitting release. Foreground requests pin the accepted bundle and committed snapshots at admission. Resource pause signals and hard ceilings preserve the daily lane without promising unmeasured throughput. Run a long real numeric batch task while exercising ingest, snapshot, sealed submission and resolution on a disposable deployment; assert each starts before batch completion and records its actual completion or explicit deadline failure.

#### TDD-2.1.42 Stable serving handle until promotion

<!-- id: TDD-2.1.42 | implements: PL-13 | code: src/research_agent/models/registry.py#ServingHandle | tests: tests/models/test_stable_serving.py | status: pending:#57 -->

Represent the accepted bundle as a storage-owned immutable release id and generation. Model service obtains a validated handle at startup and holds it for every admitted request; fitting writes candidate manifests under distinct ids and cannot mutate the handle. Promotion first validates and loads candidate numeric parameters without changing the serving handle, then performs the storage compare-and-swap of accepted generation and an atomic handle swap. Requests admitted during handoff either retain their complete old manifest or acquire the complete new one. Existing snapshot artifacts retain their old producing ids. If the currently accepted bundle cannot be loaded, readiness fails rather than adopting a candidate. Tests interleave requests, successful candidate creation and failed fitting and verify outputs retain the accepted identity until explicit promotion.

#### TDD-2.1.43 Checkpointed leased batch recovery

<!-- id: TDD-2.1.43 | implements: PL-15 | code: src/research_agent/storage/jobs.py#JobCheckpoint | tests: tests/storage/test_checkpoint_resume.py | status: pending:#5 -->

A checkpoint manifest contains job identity, stage, ordered input hashes, configuration hash, completed work keys, continuation cursor and output artifact hashes. Workers persist it only through storage's artifact/lease endpoints. Resume claims a new lease generation and verifies the complete checkpoint DAG before continuing; stale owners cannot commit after lease expiry. Reuse completed acquisition/encoding units by content key and charge reservations only for genuinely new external attempts. Tests kill a real batch process after committed progress, restart it and inspect call counters for non-repetition; a corrupted checkpoint fails instead of restarting silently.

#### TDD-2.1.44 Durable job lifecycle and clocks

<!-- id: TDD-2.1.44 | implements: PL-16 | code: src/research_agent/storage/jobs.py#JobRepository | tests: tests/storage/test_job_lifecycle.py | status: pending:#5 -->

Store jobs with queue state, active lease generation, first_started_at, terminal_at, accumulated active_duration_ns, latest checkpoint and transition events. Public batch state maps queued before execution, running during a live lease, interrupted on expired/lost execution, finished only after committed manifest, and failed on terminal error; skipped is explicitly a non-run result. Attempts have separate start/end clocks. Use monotonic deltas for active duration and UTC instants for audit; never subtract clocks across processes. No worker starts before a durable running transition. Tests terminate a lease owner, recover it, and verify no finished state exists until outputs commit.

#### TDD-2.1.45 Storage-owned persistence and verified restore

<!-- id: TDD-2.1.45 | implements: PL-18 | code: src/research_agent/storage/persistence.py#PersistentStores | tests: tests/storage/test_container_replacement.py | status: pending:#56 -->

Mount PostgreSQL data and content-addressed artifact volumes only into their owning database/storage containers; all application root filesystems are read-only except disposable scratch. Storage verifies volume identity, permissions and free space before readiness. Publish artifact references only after durable file commit and reject missing hashes on reads. Nightly backup captures a consistent database snapshot plus all referenced blobs, recording the snapshot watermark and anchor receipts; isolated restore verifies both references and chain before declaring success. Acceptance tests recreate all application containers against preserved volumes and compare ledger, manifests, checkpoints and artifacts byte-for-byte.

#### TDD-2.1.46 Host-enforced service reach graph

<!-- id: TDD-2.1.46 | implements: PL-19 | code: src/research_agent/platform/network.py#ReachabilityPolicy | tests: tests/platform/test_reachability_matrix.py | status: pending:#56 -->

Compile the interface and egress registries into isolated Compose networks plus host firewall rules, with ingress/egress default deny. Separate worker, storage/database, service and private-app paths; same-network membership alone is not authorization. Deny host-gateway, metadata, unapproved IPv6 and direct DNS bypasses. Install rules before workload processes and compare observed rules with the manifest on readiness. Execute a container-level matrix test for every allowed and representative denied role pair using real listeners; verify a compromised process cannot grant itself reach by editing its own environment or HTTP client.

#### TDD-2.1.47 Private authenticated two-rater application

<!-- id: TDD-2.1.47 | implements: PL-22 | code: src/research_agent/web/auth.py#RaterSession | tests: tests/web/test_private_rater_access.py | status: pending:#56 -->

Bind server-rendered FastAPI/Jinja HTTPS behind the declared private listener with no public port binding. Provision exactly two pseudonymous rater principals through the operator path; store salted credential hashes through storage. Issue opaque 24-hour sessions with Secure, HttpOnly, SameSite=Strict cookies and require CSRF tokens on ratings/acknowledgments. Storage checks session principal and rater-specific projection scope; browser-supplied ids never select another identity. Tests exercise unauthenticated requests, expired sessions, forged CSRF and wrong-rater access; a separate real-network acceptance probe verifies private access works while public-interface access fails.


## 3. Forecast batches and agent execution

### 3.1 Contracts

Planned Python owners below use the shared schemas, service roles and HTTP conventions in TDD-CONTRACTS.md. Storage alone performs database and artifact writes. Domain services submit authorized versioned commands. Workers send harness-only transcript/accounting events through the tool service using their scoped run capability; its restricted storage writer forwards those events. These internal HTTP routes are not extra model-visible tools, and workers receive no storage certificate, database connection or writable artifact mount. Replays use recorded model replies and never imply deterministic fresh generation.

#### TDD-3.1.1 Atomic daily corpus admission

<!-- id: TDD-3.1.1 | implements: EN-01 | code: src/research_agent/ingest/arxiv.py#admit_daily_fetch | tests: tests/ingest/test_arxiv.py | status: pending:#5 -->

Parse arXiv records into family_id, version_id, categories, first_public_at, captured_at and source_hash; strip version suffix only through the canonical identity adapter. A fetch manifest lists every page and completion token. Stage records through storage, then commit corpus membership only after complete pagination and validation. Include a family when its category set intersects {cs.AI, cs.LG}; cross-listing does not duplicate it. Keep older referenced works in graph-reference identity records, not corpus membership. Verify a real storage transaction with an interrupted second page leaves membership unchanged, an irrelevant category is excluded and duplicate category hits create one family.

#### TDD-3.1.2 Prospective eligibility at seal and resolution

<!-- id: TDD-3.1.2 | implements: EN-02 | code: src/research_agent/forecasts/eligibility.py#check_prospective | tests: tests/forecasts/test_eligibility.py | status: pending:#64 -->

Evaluate the frozen target definition and preserved observation intervals against the actual storage seal timestamp. Output eligible, preexisting_event, timing_ambiguous or missed_deadline with witness hashes; do not equate capture time with event date. Resolution rechecks preexisting-event eligibility from later-captured dated evidence, appending an exclusion disposition without modifying the original forecast. Historical_reconstructed observations cannot enter prospective resolution. Test an after-seal capture whose definite witnesses predate sealing, an interval straddling seal time and three targets with different eligibility on the same paper.

#### TDD-3.1.3 Separate prediction and reading version pins

<!-- id: TDD-3.1.3 | implements: EN-35 | code: src/research_agent/snapshots/documents.py#DocumentPins | tests: tests/snapshots/test_document_pins.py | status: pending:#64 -->

Snapshot paper entries hold family_id, original_version_id, original_feature_hash or unavailable reason, readable_version_id, extraction_hash and card_hash. Resolve each artifact's available_at through storage before sealing; original feature lineage must terminate at the first public version. Read tools use readable_version_id while head inference uses original_feature_hash. Test original text unavailable with a readable revision, and a post-seal revision carrying new results: the first retains reading access with absent heads, the second cannot alter any historical bytes.

#### TDD-3.1.4 Provider signal capture boundary

<!-- id: TDD-3.1.4 | implements: EN-36 | code: src/research_agent/snapshots/signals.py#select_provider_signal | tests: tests/snapshots/test_signals.py | status: pending:#57 -->

Select only committed source captures whose capture completion and ledger sequence precede the snapshot seal and whose artifact is in its manifest. A signal record carries provider_id, capture_id, payload_hash, value or unavailable reason and observation time; provider event dates never substitute for capture eligibility. Storage rejects a manifest referencing an uncommitted or future capture. Tests provide an old-dated response first captured after sealing and verify no value, then replay a later snapshot and verify the new value appears there alone.

#### TDD-3.1.5 Extraction coverage with independent audit state

<!-- id: TDD-3.1.5 | implements: EN-37 | code: src/research_agent/ingest/coverage.py#build_daily_coverage | tests: tests/ingest/test_coverage.py | status: pending:#77 -->

Use the complete daily admitted-family manifest as denominator and left join source, text, figure and bibliography extraction statuses. Compute four integer numerators and denominators before division, retaining missing/error distinctions. Attach the immutable fixed source-audit report and its sampled family ids, verdicts and actual audit date; do not describe an unaudited day's rows as hand verified. A missing audit produces not_yet_audited alongside valid automatic daily counts; missing automatic measurement records a gap. Test all combinations of missing artifacts against known counts, zero-paper days and a withheld audit report that does not suppress daily counts.

#### TDD-3.1.6 Same-day discovery capture

<!-- id: TDD-3.1.6 | implements: EN-38 | code: src/research_agent/ingest/discovery.py#capture_daily_picks | tests: tests/ingest/test_discovery.py | status: pending:#56 -->

The sole launch adapter is licensed Hugging Face Daily Papers. Preserve service day, actual capture timestamp, provider order, canonical family ids, source response hash, verification record and at most 50 picks. Commit successful same-day captures through storage; a response arriving on a later UTC day records uncovered for the requested day and cannot populate its pick list. Disabled/unlicensed service returns unavailable and performs no request. Test day rollover at UTC midnight, duplicate family ids, fifty-entry cap and disabled adapter with a network-deny test.

#### TDD-3.1.7 Transactional forecast sealing

<!-- id: TDD-3.1.7 | implements: EN-03 | code: src/research_agent/storage/forecasts.py#seal_forecasts | tests: tests/storage/test_forecasts.py | status: pending:#57 -->

Storage accepts a typed sealing command from authorized submission or rater/baseline owners, never an agent database connection. It validates question identity, finite probability in [0,1], submitter identity, snapshot evidence and deadlines, allocates the actual seal timestamp and appends one forecast ledger event per answer in the submission transaction. Seal receipt contains forecast ids, sequences and hashes. Idempotent request identity returns the same receipt. Concurrent identical requests create one set; an injected append failure rolls back every forecast and leaves no scorable partial submission.

#### TDD-3.1.8 Append-only settlement state

<!-- id: TDD-3.1.8 | implements: EN-04 | code: src/research_agent/storage/resolutions.py#append_resolution | tests: tests/storage/test_resolutions.py | status: pending:#57 -->

Accept forecast_id, frozen resolver identity, target identity, observation hash, tri-state result, evidence and resolution_version. Validate the referenced forecast is sealed and the outcome capture is eligible before appending a resolution event. Corrections append superseding resolution lineage rather than update original events; an as-of projection selects the declared active version. Retry the same request by canonical hash. Test true, false and unresolvable settlements, failed append leaving unsettled state, and byte-identical original forecast after correction.

#### TDD-3.1.9 Serializable hash-chain append

<!-- id: TDD-3.1.9 | implements: EN-05 | code: src/research_agent/storage/ledger.py#append_event | tests: tests/storage/test_ledger.py | status: pending:#5 -->

Storage alone locks the ledger head inside a PostgreSQL serializable transaction. Allocate sequence=head+1 and previous_hash=head.hash; compute SHA-256 over the canonical event envelope excluding its own hash, including schema_version, sequence, previous_hash, kind, payload and timestamp. Genesis uses an explicit all-zero SHA-256 predecessor. Insert event and advance the head atomically; stale expected-head requests conflict and internal transaction retry cannot duplicate an idempotency key. Verify the actual PostgreSQL path under concurrent append, rollback and tampering; audit identifies the first corrupted sequence.

#### TDD-3.1.10 Typed ledger envelopes

<!-- id: TDD-3.1.10 | implements: EN-06 | code: src/research_agent/storage/ledger.py#LedgerEvent | tests: tests/storage/test_ledger_schema.py | status: pending:#5 -->

Define a versioned strict envelope with sequence positive integer, previous_hash and hash lowercase SHA-256 hex, kind registered discriminant, payload a matching strict schema and UTC timestamp. Fields added by storage remain required on persisted/readback records; clients supply only the permitted append-command subset. Unknown event kind, omitted stored field, nonfinite number or naive timestamp is invalid before insertion. Validation of an exported ledger checks hashes and schema independently so a self-consistent but malformed record is still refused.

#### TDD-3.1.11 Sanitized source capture provenance

<!-- id: TDD-3.1.11 | implements: EN-07 | code: src/research_agent/ingest/capture.py#preserve_response | tests: tests/ingest/test_capture.py | status: pending:#56 -->

Before requesting storage persistence, calculate transport SHA-256, apply the license/privacy field allowlist, strip authorization and credential material, then calculate stored-payload SHA-256. A capture event names both hashes when different, sanitizer version, source request parameters excluding secrets, HTTP status, actual capture interval and artifact retention class. Commit artifact and capture event before any consumer sees it. Failure leaves the response unusable; no consumer receives an in-memory bypass. Test secret-bearing response headers/body, permitted byte-preserving input, artifact tampering and failure between artifact upload and manifest commit.

#### TDD-3.1.12 Resolver build identity in settlement

<!-- id: TDD-3.1.12 | implements: EN-08 | code: src/research_agent/storage/resolutions.py#validate_resolver_identity | tests: tests/storage/test_resolver_identity.py | status: pending:#57 -->

Resolution commands carry resolver_id, source/build digest, definition hash and observation-protocol version. Storage compares the complete tuple against the sealed question before append; a semantic version string without its immutable digest is insufficient. Persist those fields in the resolution payload so replay never resolves a mutable latest alias. Test omitted identity, changed build under the same name and a complete valid tuple; rejection leaves the forecast unsettled.

#### TDD-3.1.13 Daily batch and canonical shard creation

<!-- id: TDD-3.1.13 | implements: EN-09 | code: src/research_agent/orchestration/batches.py#build_daily_batch | tests: tests/orchestration/test_batches.py | status: pending:#56 -->

After a completed daily ingest, use its immutable membership manifest to select first-public eligible families without sorting on predicted success. Sort by first_public_at then family_id, take the profile's immediate-processing ceiling and partition into consecutive groups of at most 20. Record excluded late arrivals and overflow explicitly. Build question ids from family and qualified target-definition hashes; each shard and the four configuration slots reference one parent snapshot. Storage enforces unique UTC processing day and idempotent build identity. Test 0, 1, 20, 21 and 1001 papers, duplicate scheduler calls and exact four-way shard coverage.

#### TDD-3.1.14 Atomic batch seal and dispatch barrier

<!-- id: TDD-3.1.14 | implements: EN-10 | code: src/research_agent/storage/batches.py#seal_batch | tests: tests/storage/test_batches.py | status: pending:#57 -->

A batch manifest contains UTC day, ordered family/shard/question ids, target/resolver identities, snapshot hash, mode and configuration hashes. Storage verifies all referenced artifacts and future event horizons, writes the canonical batch hash and seal event in one transaction and returns a receipt. Only a committed receipt authorizes slot creation. A mutation creates a different manifest rejected against the existing day; no in-place question editing. Test crash before seal commit, question-byte alteration and dispatch racing seal completion.

#### TDD-3.1.15 Pinned resolver routing

<!-- id: TDD-3.1.15 | implements: EN-11 | code: src/research_agent/outcomes/dispatch.py#resolve_pinned_question | tests: tests/outcomes/test_dispatch.py | status: pending:#57 -->

Dispatch loads the immutable resolver artifact named by the question rather than the currently active target registry. Verify artifact hash and supported protocol, then invoke the pure resolver on the preserved observation. An absent build returns resolver_unavailable, schedules an operational finding and leaves settlement pending; it never redirects to a newer build. Test a newer registry alongside an old sealed question and a missing historical resolver image.

#### TDD-3.1.16 Evidence-bearing tri-state results

<!-- id: TDD-3.1.16 | implements: EN-14 | code: src/research_agent/outcomes/results.py#ResolutionResult | tests: tests/outcomes/test_results.py | status: pending:#57 -->

The resolver return type is status true/false/unresolvable, definition_hash, observation_hash, witness_ids, completion_proof_hash when needed, lower/upper bounds and reason. Map automatic label unknown to unresolvable without inventing a false event. At least one evidence artifact or explicit missing-evidence diagnostic must identify the input condition. Validate referenced ids in the observation manifest. Test each target's positive witnesses, negative complete upper bound and missing/ambiguous source; a bare boolean or unknown enum fails persistence.

#### TDD-3.1.17 No selection authority from metrics

<!-- id: TDD-3.1.17 | implements: EN-16 | code: src/research_agent/evolution/disabled.py#selection_disposition | tests: tests/evolution/test_disabled.py | status: pending:#56 -->

The launch policy object returns selection_disabled with the fixed configuration-manifest hash; it has no weighted aggregate fitness field. Reports can reference independent target loss records but no report endpoint can request replacement or a parent draw. Missing profile is fail-closed. Exercise drastically changed citation/Jev/preference inputs and verify identical population identity, zero launch requests and one audit disposition per weekly policy invocation.

#### TDD-3.1.18 Typed citation diagnostics

<!-- id: TDD-3.1.18 | implements: EN-17 | code: src/research_agent/papers/diagnostics.py#CitationDiagnostic | tests: tests/papers/test_diagnostics.py | status: pending:#64 -->

Graph diagnostics hold canonical family ids, graph manifest, capture time and count with explicit availability. Their artifact role is card_diagnostic, distinct from label_observation; storage manifest validators and resolver entrypoints reject the former where the latter is required. Resolve duplicate citation ids before computing descriptive totals. Test changing a current graph count after snapshot capture changes neither preserved labels nor fitting-release bytes.

#### TDD-3.1.19 Disabled citation intent diagnostic

<!-- id: TDD-3.1.19 | implements: EN-18 | code: src/research_agent/papers/diagnostics.py#disabled_diagnostic | tests: tests/papers/test_disabled_diagnostics.py | status: pending:#64 -->

The launch adapter registry has no enabled citation intent acquisition job. Its typed diagnostic view returns status unavailable and reason disabled_by_profile; it never substitutes zero. The reserved provenance shape names provider method, annotation availability and source evidence, but no network client or historical backfill is required. Diagnostic artifacts cannot be passed to automatic-label, fitting-target or selection APIs. Test this named field's disabled response and inject arbitrary diagnostic values into an otherwise identical card fixture: label outputs, head feature bytes and population identity remain unchanged.

#### TDD-3.1.20 Disabled repository forks diagnostic

<!-- id: TDD-3.1.20 | implements: EN-19 | code: src/research_agent/papers/diagnostics.py#disabled_diagnostic | tests: tests/papers/test_disabled_diagnostics.py | status: pending:#64 -->

The launch adapter registry has no enabled repository forks acquisition job. Its typed diagnostic view returns status unavailable and reason disabled_by_profile; it never substitutes zero. The reserved provenance shape names repository attribution, observed fork count and capture time, but no network client or historical backfill is required. Diagnostic artifacts cannot be passed to automatic-label, fitting-target or selection APIs. Test this named field's disabled response and inject arbitrary diagnostic values into an otherwise identical card fixture: label outputs, head feature bytes and population identity remain unchanged.

#### TDD-3.1.21 Disabled linked artifact diagnostic

<!-- id: TDD-3.1.21 | implements: EN-20 | code: src/research_agent/papers/diagnostics.py#disabled_diagnostic | tests: tests/papers/test_disabled_diagnostics.py | status: pending:#64 -->

The launch adapter registry has no enabled linked artifact acquisition job. Its typed diagnostic view returns status unavailable and reason disabled_by_profile; it never substitutes zero. The reserved provenance shape names paper-declared link, artifact identity and source text locator, but no network client or historical backfill is required. Diagnostic artifacts cannot be passed to automatic-label, fitting-target or selection APIs. Test this named field's disabled response and inject arbitrary diagnostic values into an otherwise identical card fixture: label outputs, head feature bytes and population identity remain unchanged.

#### TDD-3.1.22 Disabled artifact upvotes diagnostic

<!-- id: TDD-3.1.22 | implements: EN-21 | code: src/research_agent/papers/diagnostics.py#disabled_diagnostic | tests: tests/papers/test_disabled_diagnostics.py | status: pending:#64 -->

The launch adapter registry has no enabled artifact upvotes acquisition job. Its typed diagnostic view returns status unavailable and reason disabled_by_profile; it never substitutes zero. The reserved provenance shape names source page identity, observed count and capture time, but no network client or historical backfill is required. Diagnostic artifacts cannot be passed to automatic-label, fitting-target or selection APIs. Test this named field's disabled response and inject arbitrary diagnostic values into an otherwise identical card fixture: label outputs, head feature bytes and population identity remain unchanged.

#### TDD-3.1.23 Disabled repository stars diagnostic

<!-- id: TDD-3.1.23 | implements: EN-22 | code: src/research_agent/papers/diagnostics.py#disabled_diagnostic | tests: tests/papers/test_disabled_diagnostics.py | status: pending:#64 -->

The launch adapter registry has no enabled repository stars acquisition job. Its typed diagnostic view returns status unavailable and reason disabled_by_profile; it never substitutes zero. The reserved provenance shape names repository attribution, count or event series and capture time, but no network client or historical backfill is required. Diagnostic artifacts cannot be passed to automatic-label, fitting-target or selection APIs. Test this named field's disabled response and inject arbitrary diagnostic values into an otherwise identical card fixture: label outputs, head feature bytes and population identity remain unchanged.

#### TDD-3.1.24 Disabled discussion mentions diagnostic

<!-- id: TDD-3.1.24 | implements: EN-23 | code: src/research_agent/papers/diagnostics.py#disabled_diagnostic | tests: tests/papers/test_disabled_diagnostics.py | status: pending:#64 -->

The launch adapter registry has no enabled discussion mentions acquisition job. Its typed diagnostic view returns status unavailable and reason disabled_by_profile; it never substitutes zero. The reserved provenance shape names matched item ids, dates and paper-link attribution, but no network client or historical backfill is required. Diagnostic artifacts cannot be passed to automatic-label, fitting-target or selection APIs. Test this named field's disabled response and inject arbitrary diagnostic values into an otherwise identical card fixture: label outputs, head feature bytes and population identity remain unchanged.

#### TDD-3.1.25 Reject trend-to-paper forecasts

<!-- id: TDD-3.1.25 | implements: EN-24 | code: src/research_agent/forecasts/admission.py#validate_target | tests: tests/forecasts/test_admission.py | status: pending:#56 -->

The launch allowlist consists only of the three immutable automatic-citations-v1 target hashes. A trend-to-paper claim returns unadmitted_type through the typed refusal path before any outcome acquisition or sealing; free-text mention in rationale remains unscored text. Record the attempted type and request hash without creating a forecast. Test otherwise well-formed input naming this type, including an attempted alias of an admitted resolver, and verify no resolution job or ledger forecast is created.

#### TDD-3.1.26 Reject co-citation forecasts

<!-- id: TDD-3.1.26 | implements: EN-25 | code: src/research_agent/forecasts/admission.py#validate_target | tests: tests/forecasts/test_admission.py | status: pending:#56 -->

The launch allowlist consists only of the three immutable automatic-citations-v1 target hashes. A co-citation claim returns unadmitted_type through the typed refusal path before any outcome acquisition or sealing; free-text mention in rationale remains unscored text. Record the attempted type and request hash without creating a forecast. Test otherwise well-formed input naming this type, including an attempted alias of an admitted resolver, and verify no resolution job or ledger forecast is created.

#### TDD-3.1.27 Reject query-growth forecasts

<!-- id: TDD-3.1.27 | implements: EN-26 | code: src/research_agent/forecasts/admission.py#validate_target | tests: tests/forecasts/test_admission.py | status: pending:#56 -->

The launch allowlist consists only of the three immutable automatic-citations-v1 target hashes. A query-growth claim returns unadmitted_type through the typed refusal path before any outcome acquisition or sealing; free-text mention in rationale remains unscored text. Record the attempted type and request hash without creating a forecast. Test otherwise well-formed input naming this type, including an attempted alias of an admitted resolver, and verify no resolution job or ledger forecast is created.

#### TDD-3.1.28 Reject citation-rate-growth forecasts

<!-- id: TDD-3.1.28 | implements: EN-27 | code: src/research_agent/forecasts/admission.py#validate_target | tests: tests/forecasts/test_admission.py | status: pending:#56 -->

The launch allowlist consists only of the three immutable automatic-citations-v1 target hashes. A citation-rate-growth claim returns unadmitted_type through the typed refusal path before any outcome acquisition or sealing; free-text mention in rationale remains unscored text. Record the attempted type and request hash without creating a forecast. Test otherwise well-formed input naming this type, including an attempted alias of an admitted resolver, and verify no resolution job or ledger forecast is created.

#### TDD-3.1.29 Launch volunteered-claim boundary

<!-- id: TDD-3.1.29 | implements: EN-30 | code: src/research_agent/forecasts/admission.py#validate_issued_question | tests: tests/forecasts/test_issued_questions.py | status: pending:#77 -->

The atomic launch submit schema binds each forecast to an issued shard question. A forecast without that identity, an extra question id or a new paper/target combination returns unissued_question and cannot create a volunteered claim. Preserve refusal diagnostics within the normal tool budget. The admitted three targets remain usable through issued questions; expanding the volunteer surface requires an accepted amendment and schema version. Test a familiar target paired with an unissued paper and verify no additional forecast row or resolver job.

#### TDD-3.1.30 Immutable launch target admission

<!-- id: TDD-3.1.30 | implements: EN-31 | code: src/research_agent/forecasts/admission.py#admit_registry | tests: tests/forecasts/test_registry_admission.py | status: pending:#77 -->

An operator-owned activation command verifies the exact three target-definition and resolver-build hashes, conformance report and deterministic repeat-test artifact before recording target admission. Agent tool credentials cannot call this endpoint. Test each resolver twice over the same preserved fixtures and compare canonical results, including unknown cases; the repeat check complements pure dependency and no-clock/no-network design rather than proving arbitrary code deterministic. Unknown target definitions remain unadmitted until a future amendment; a random-number resolver fixture is refused.

#### TDD-3.1.31 Atomic private digest publication

<!-- id: TDD-3.1.31 | implements: EN-32 | code: src/research_agent/digest/publish.py#publish_digest | tests: tests/digest/test_publish.py | status: pending:#56 -->

Storage persists a complete immutable digest manifest and its blinded view before atomically making it available to the two provisioned rater identities. The app reads by authenticated rater and digest id; public, agent and other-rater credential roles cannot access internal source maps. Rendering includes the automated-output label and version-pinned cards. Test no authentication, unauthorized identity, partial manifest commit and a successful two-rater read; no partially populated digest becomes visible.

#### TDD-3.1.32 Seeded controls from the residual pool

<!-- id: TDD-3.1.32 | implements: EN-33 | code: src/research_agent/digest/controls.py#sample_controls | tests: tests/digest/test_controls.py | status: pending:#64 -->

Form a canonical ordered pool of daily eligible families minus selected population entries, then sample min(3,N) without replacement using hash ranking over batch_hash, control_rubric_version and family_id. Treat SHA-256-derived ranks as the recorded pseudorandom draw, tie-breaking by family id; inclusion probability is min(3,N)/N for each eligible residual family, with no probability for N=0. Persist candidate-pool hash, selected ids, seed and shortfall. Test replay, empty pools, no duplication, score changes and explicit conditional inclusion probabilities.

#### TDD-3.1.33 Optional human question offer

<!-- id: TDD-3.1.33 | implements: EN-34 | code: src/research_agent/ratings/forecasts.py#offer_human_questions | tests: tests/ratings/test_human_forecasts.py | status: pending:#77 -->

At batch issue, hash-rank its qualified citation_reach_365d questions using batch_hash and question_id, offering the first min(3,N) identically to both raters. Persist offer ids/deadlines independently of digest publication. Before deadline, an authenticated answer uses the common forecast sealing validator with rater submitter type; after deadline it is refused without locking ratings or requiring completion. Preserve participation as offered/answered/expired, never a synthetic zero. Test late/no participation, fewer questions, identical offers and unauthenticated submissions.

#### TDD-3.1.34 Watermarked deterministic digest build

<!-- id: TDD-3.1.34 | implements: EN-40 | code: src/research_agent/digest/build.py#build_digest | tests: tests/digest/test_build.py | status: pending:#77 -->

Build only after daily slots are terminal or their deadlines have expired; storage freezes a digest input ledger watermark exactly once for that batch. From events at or below that watermark read accepted nomination lists, linked sealed forecasts, the eligible control pool and captured service picks. Apply the profile allocation, then hash-rank the union with the recorded shuffle seed for blind display order. Persist input hashes, watermark, seed, selected/omitted ids and digest hash in one publication transaction. Test identical watermark replay after new ratings, late service captures and late submission attempts; none alters the published digest.

#### TDD-3.1.35 Two-stage nomination allocation

<!-- id: TDD-3.1.35 | implements: EN-41 | code: src/research_agent/digest/nominations.py#allocate_population_entries | tests: tests/digest/test_nominations.py | status: pending:#64 -->

For each configuration, visit its shards in canonical order repeatedly, consuming the next not-yet-seen nomination from each list until exhausted; skip void/quarantined submissions. Sort the four configuration ids and rotate by UTC day ordinal modulo four, then round-robin next unseen families until seven entries or exhaustion. Record winning nomination provenance and all supporting rationales without sorting on any probability. Test overlapping lists, empty shards, rotations across four days, 20-paper shard boundaries and wholesale probability changes with fixed nomination bytes.

#### TDD-3.1.36 Bounded service entry allocation

<!-- id: TDD-3.1.36 | implements: EN-42 | code: src/research_agent/digest/services.py#allocate_service_entries | tests: tests/digest/test_service_entries.py | status: pending:#64 -->

Start after population and controls are fixed. Sort qualified captured service ids lexically, preserve each source order, skip any family already selected and round-robin until two new entries or exhaustion. A pick must have a corpus family and permitted same-day capture; unmatched references are recorded omitted, not added as a second corpus. Persist internal origin mapping while returning the same blinded card schema to the app. Test 100 offered picks, control overlap, source outage and a final digest size never exceeding twelve.

#### TDD-3.1.37 Pinned inference client identity

<!-- id: TDD-3.1.37 | implements: AG-01 | code: src/research_agent/agents/client.py#PinnedModelClient | tests: tests/agents/test_model_client.py | status: pending:#56 -->

Load the qualified deployment manifest with weights revision, tokenizer/template/parser hashes, FP8 format, image processor and endpoint identity. Before a run, compare endpoint readback against that manifest and refuse drift or missing qualification. Use the profile's chat-completions path and sampling settings with request_seed derived exactly from run_id, turn_index and sampling-v1 under TDD-CONTRACTS.md, recording actual server metadata. The client has no fallback URL/model. Test a replay server reporting a changed tokenizer or model alias fails before generation; separately run the budgeted real-tool/image/context qualification suite required by the profile.

#### TDD-3.1.38 Snapshot-bound multimodal deep reads

<!-- id: TDD-3.1.38 | implements: AG-02 | code: src/research_agent/tools/deep_read.py#deep_read | tests: tests/tools/test_deep_read.py | status: pending:#56 -->

Accept a snapshot-visible family id and mutually exclusive section id or one/two page numbers, with an optional next_span continuation locator. Validate the locator against the same immutable snapshot, version and requested section/pages; it cannot select another paper or skip into hidden bytes. Resolve the readable version and exact text/figure locators from the snapshot, obtain immutable artifact streams through storage and return at most 6000 model text tokens and two images. Tables remain extracted text when available; PDF fallback renders the pinned page at 150 dpi with longest edge at most 1600 pixels, without OCR. Response names partial coverage, offsets and next_span. Tests verify two figures and textual tables reach canonical model content blocks, newer revisions stay inaccessible, and unavailable images carry reasons rather than invented pixels.

#### TDD-3.1.39 Fixed configuration boundary

<!-- id: TDD-3.1.39 | implements: AG-03 | code: src/research_agent/agents/configuration.py#validate_fixed_population | tests: tests/agents/test_configuration.py | status: pending:#77 -->

The population manifest contains exactly four immutable reading configurations. Its common infrastructure hash covers model, tools, budgets, rubric, registry, scorer and snapshot policy; only the admitted prompt/policy emphasis varies. No evolution job mutates any object at launch. Validate a proposed activation manifest against common identities and reject per-member model, resolver or tool-behavior overrides. Test a valid four-emphasis population and each forbidden shared-component change.

#### TDD-3.1.40 Matched tasks across configurations

<!-- id: TDD-3.1.40 | implements: AG-04 | code: src/research_agent/orchestration/slots.py#create_slots | tests: tests/orchestration/test_slots.py | status: pending:#56 -->

For each shard, construct four population slot records referencing identical shard hash, snapshot hash, model deployment, loop image, budgets and tool-schema manifest. Configuration hash and seed are the deliberate differing fields. Persist the complete population slot set atomically through storage before scheduling, so partial creation cannot masquerade as a smaller population. Eligible preregistered Jev comparisons receive two separate arm-specific slots under TDD-CONTRACTS.md; their nominations never enter population selection, and both consume the same global limits. Test shuffled configuration input yields canonical identities and all pairwise shared fields remain equal; reject one member using a newer snapshot.

#### TDD-3.1.41 Two-worker slot scheduler

<!-- id: TDD-3.1.41 | implements: AG-05 | code: src/research_agent/orchestration/scheduler.py#schedule_slots | tests: tests/orchestration/test_scheduler.py | status: pending:#56 -->

Read queued slots from storage in earliest paper seal-deadline then slot-id order. Acquire durable fenced leases and ask the operator-owned launcher for the predefined unprivileged worker specification, with at most two active workers. Never expose a Docker socket to workers. Each slot ends completed, void or missed_deadline; a restarted scheduler reconciles live workers against leases before launching anything. No retry slot is created after ambiguous model execution. Test two competing schedulers and a crash after launch acknowledgment using actual storage: no duplicate slot execution, third worker or silently dropped deadline.

#### TDD-3.1.42 Reject performance mutation

<!-- id: TDD-3.1.42 | implements: AG-06 | code: src/research_agent/evolution/disabled.py#reject_performance_mutation | tests: tests/evolution/test_disabled.py | status: pending:#56 -->

The launch mutation command returns disabled_by_profile with profile hash and records an audit disposition through storage. It does not allocate a model request, child configuration, candidate score or selection job. A missing profile is an error, never implicit permission. Test a syntactically valid high-performing configuration and mature loss records still leave population bytes and provider request count unchanged.

#### TDD-3.1.43 Scoring input separation

<!-- id: TDD-3.1.43 | implements: AG-07 | code: src/research_agent/scoring/inputs.py#ForecastScoringInput | tests: tests/scoring/test_input_boundary.py | status: pending:#57 -->

The scorer requests typed sealed forecast and resolution projections from storage; each row contains forecast identity, target version, numeric probability, result and exclusion/lineage identities. Agent notes, nominated rank, claimed score and all Jev answers are absent from that projection. Scorer credentials cannot alter population manifests. Test adding self-praise or a claimed perfect score to model output changes neither the scoring input hash nor per-target losses; unsealed prose produces no input row.

#### TDD-3.1.44 Configuration identifier admission scan

<!-- id: TDD-3.1.44 | implements: AG-31 | code: src/research_agent/agents/admission.py#reject_paper_identifiers | tests: tests/agents/test_identifier_admission.py | status: pending:#57 -->

Recursively scan every configuration string and object key after canonical Unicode normalization, including prompt, policies, schema descriptions and enum values. Match normalized known corpus identifiers and their recognized DOI/arXiv URL forms from a storage-supplied identity manifest; reject with field path and identifier class, not a hidden prompt rewrite. Repeat validation against the current identity manifest when activating a configuration. This is identifier exclusion, not a claim to detect every encoded scientific fact. Test nested schema labels, versioned arXiv URLs, DOI casing and a benign non-identifier substring.

#### TDD-3.1.45 Strict assistant-turn schema

<!-- id: TDD-3.1.45 | implements: AG-32 | code: src/research_agent/agents/turns.py#AssistantTurn | tests: tests/agents/test_turns.py | status: pending:#56 -->

The protected assistant content is a strict JSON object {note:string, intent:enum, extension:{}}. Native tool_calls remain the API's separate ordered field; forecast answers remain submit arguments. Pass the fixed response schema on every request, preserving the same core hash for all configurations. Validate content before executing any tool call; malformed content records invalid_model_turn and ends the run void without executing attached calls. The qualification suite must prove the selected parser can combine this content contract with native tools; unsupported simultaneous formatting blocks qualification rather than silently dropping the note schema.

#### TDD-3.1.46 Bounded action notes and intents

<!-- id: TDD-3.1.46 | implements: AG-33 | code: src/research_agent/agents/turns.py#validate_protected_core | tests: tests/agents/test_protected_core.py | status: pending:#56 -->

Require note length at most 1000 Unicode characters encoded as valid UTF-8 and intent in scan/compare/inspect/forecast/nominate/submit/stop; normalize only at admitted configuration/artifact boundaries, never rewrite recorded model bytes. The note is an observable action/evidence summary rather than requested private reasoning. Store it with the turn but exclude it from scorer projections and pre-rating views. Test over-limit multibyte notes, unknown intents, missing note, core-schema mutation and identical scores after changing valid notes.

#### TDD-3.1.47 Empty extension at launch

<!-- id: TDD-3.1.47 | implements: AG-34 | code: src/research_agent/agents/turns.py#validate_empty_extension | tests: tests/agents/test_empty_extension.py | status: pending:#77 -->

Admission and turn validation require extension to be an object with zero properties. Even a well-labeled, well-typed future extension returns disabled_by_profile; there is no mutation builder or generated UI caption service. The reserved future type limits remain documentation rather than executable authority to admit fields. The app renders stored protected note/intent with ordinary escaping and no model request. Test valid-looking extra fields, missing labels, an unsupported nested type and rendering with every model endpoint unavailable.

#### TDD-3.1.48 Canonical single-conversation worker

<!-- id: TDD-3.1.48 | implements: AG-08 | code: src/research_agent/agents/loop.py#run_conversation | tests: tests/agents/test_loop.py | status: pending:#56 -->

Worker states are created -> running -> submitted or void, with quarantine as an exclusion disposition. Load the immutable run specification, append the system and initial task messages, then repeat budget reservation, persist request, call the pinned client, persist response, validate turn, dispatch native tool calls in received order and append exact tool responses. Execute the first accepted submit then stop, ignoring no later call as an alternative submission. A plain model stop without accepted submit is void. No framework rewrite, secondary planner, memory call or context compression exists. Replay preserved model bytes through the real dispatcher to verify ordering and terminal transitions.

#### TDD-3.1.49 Five-tool dispatcher

<!-- id: TDD-3.1.49 | implements: AG-09 | code: src/research_agent/tools/dispatch.py#dispatch_tool | tests: tests/tools/test_dispatch.py | status: pending:#57 -->

The dispatcher table contains query_cards, neighbors, graph, deep_read and submit only. The worker presents the run's admitted subset; the shared tool service independently checks that subset from run_id, never trusts supplied names. Read handlers resolve only snapshot-bound artifacts. submit invokes the transactional storage command through the authorized service adapter. Unknown tool names return tool_not_allowed before execution and consume one call. Test shell/browser/HTTP/protected-write requests, tool aliases and a hidden sixth registration are all refused.

#### TDD-3.1.50 Run-bound snapshot authorization

<!-- id: TDD-3.1.50 | implements: AG-10 | code: src/research_agent/tools/snapshot.py#authorize_snapshot | tests: tests/tools/test_snapshot_authorization.py | status: pending:#57 -->

Every call carries schema_version, run_id, tool_call_id and snapshot_id. Tools resolve the immutable run capability and compare its snapshot hash to the request before lookup; clients cannot select a newer snapshot by changing the field. Snapshot membership controls cards, paper versions, vectors, edges, images and allowed outcome observations. Read endpoints have no write operation, and direct storage artifact fetches require equivalent role/snapshot authorization. Test concurrent old/new snapshots, guessed artifact hashes, a later source response and an attempted manifest write from a real worker container.

#### TDD-3.1.51 Strict tool argument unions

<!-- id: TDD-3.1.51 | implements: AG-11 | code: src/research_agent/contracts/tools.py#ToolRequest | tests: tests/tools/test_schemas.py | status: pending:#57 -->

The model supplies only tool domain arguments. The trusted harness adds schema_version, run_id, snapshot_id and endpoint-native tool_call_id from its immutable context to the internal HTTP envelope. Reject attempted authority overrides; validate envelope separately. Parse domain JSON without coercion into tagged strict schemas with unknown properties forbidden recursively. query_cards is either paper_ids[1..5 distinct] or text query with overview/passages mode, optional single-paper filter and limit 1..5; neighbors takes one paper and limit 1..5; graph takes direction references/citations and limit 1..20; deep_read selects section or 1..2 pages with an optional matching next_span continuation; submit uses the complete answer/nomination schema. Defaults are only those documented in the profile. Reject booleans where integers are expected, nonfinite probabilities, duplicate ids, both query variants and malformed UTF-8. Execute no handler on validation failure.

#### TDD-3.1.52 Monotone resource accounting

<!-- id: TDD-3.1.52 | implements: AG-12 | code: src/research_agent/agents/budgets.py#RunBudget | tests: tests/agents/test_budgets.py | status: pending:#56 -->

Persist initial limits and append monotonically increasing usage events through storage: model attempts, tool attempts including refusals, deep reads, images, generated tokens, measured/reserved spend and wall deadline. Before a model request reserve min(8192, remaining generation allowance) within 65536 total context tokens using the pinned text/image processor, and reject a zero allowance or nonfitting conversation. Enforce 16 model attempts, 40 tool attempts, 8 deep reads, 12 images, 16384 generated tokens and 20 minutes. A retry consumes another attempt and fits the same deadline; only explicit nonexecuted 429/503 may retry once after five seconds. Unknown completion voids. Test exact boundary, concurrent tool attempts, failed reservations and timeout without hidden retries.

#### TDD-3.1.53 Independent scorer deployment

<!-- id: TDD-3.1.53 | implements: AG-13 | code: src/research_agent/scoring/service.py#ScoringService | tests: tests/scoring/test_isolation.py | status: pending:#5 -->

Run scorer as its declared container with a storage read projection and authorized score-append route. It exposes no listener to the worker network and imports no worker conversation state. A scoring batch is identified by ledger watermark, target registry and scoring build hash; it executes with workers absent. Integration tests use Compose network policies to refuse worker access and compute identical score artifacts before/after all workers stop, using actual preserved forecast/resolution records.

#### TDD-3.1.54 Tool allowlist intersection at admission

<!-- id: TDD-3.1.54 | implements: AG-14 | code: src/research_agent/agents/configuration.py#validate_tools | tests: tests/agents/test_tool_allowlist.py | status: pending:#57 -->

Validate the configuration's unique ordered tool names against the fixed five, then persist the exact allowed list into the run specification. Reject the entire configuration on an unknown name instead of silently intersecting away an error. Launch's four configured members all use the same full set, while the admission validator supports a strictly smaller set for conformance. Test four known tools produce only four advertised/authorized handlers and a sixth tool prevents slot creation.

#### TDD-3.1.55 Void terminal state without submission

<!-- id: TDD-3.1.55 | implements: AG-15 | code: src/research_agent/storage/runs.py#finish_without_submit | tests: tests/storage/test_run_terminal.py | status: pending:#57 -->

Storage performs a compare-and-set from running to void only if no accepted submission exists, recording reason, last usage event and complete run stamp. Successful submission and void transition serialize on the same run row so a timeout race cannot create both outcomes. Scoring projections exclude void runs but coverage denominators retain their slots. Test model stop with prose probabilities, failed submits, budget expiry and a racing accepted submit; exactly one terminal state survives and no plain text becomes a forecast.

#### TDD-3.1.56 Minimal initial task payload

<!-- id: TDD-3.1.56 | implements: AG-25 | code: src/research_agent/agents/messages.py#build_initial_message | tests: tests/agents/test_initial_message.py | status: pending:#57 -->

Serialize only shard paper/question ids and immutable question definitions, budget limits and snapshot description into the initial user/task message. System configuration remains the separate immutable instruction message. Do not include abstracts, cards, precomputed head/Jev values, neighbor lists or outcomes. Every later card message references a successful run-bound tool_call_id. Test message shape and content against a fixture whose abstract contains a unique marker; the marker appears only after an explicit query_cards lookup.

#### TDD-3.1.57 Atomic complete submit transaction

<!-- id: TDD-3.1.57 | implements: AG-26 | code: src/research_agent/storage/submissions.py#accept_submission | tests: tests/storage/test_submissions.py | status: pending:#64 -->

Submit body contains submission_id, answers[{question_id,probability,rationale,evidence_ids}], nominations[{paper_id,rationale}] plus strict tool envelope. Require answer ids equal the issued question set exactly, probabilities finite in [0,1], rationales at most 2000 characters, one to five evidence ids each and every evidence id previously delivered to this run from its snapshot. Require 0..7 unique nomination ids from this shard. Any structural or semantic error rejects the whole attempt and records submission_rejected with the request hash and per-question error codes; no partial forecast set is sealed, and a corrected attempt remains allowed within budget. In one storage transaction lock run state, validate all deadlines, append every forecast and nomination event, store canonical request hash/receipt and mark submitted. Same (run_id,submission_id) and bytes return the original receipt even after deadline; changed bytes conflict. Test one invalid answer rolls back all, empty-question engineering nominations work, duplicate nominations and simultaneous different submissions yield only one accepted result.

#### TDD-3.1.58 Post-call budget envelope

<!-- id: TDD-3.1.58 | implements: AG-27 | code: src/research_agent/agents/budgets.py#attach_remaining | tests: tests/agents/test_budget_envelope.py | status: pending:#57 -->

Every ok/unavailable/error tool result carries remaining values for each initial budget, computed after charging that attempt, plus current context size and wall milliseconds remaining. Read usage from the committed usage event, not caller-supplied counters. Remaining consumable allowances use declared units and never increase within a run; context usage is reported separately and can grow; idempotent transport replay returns the original call receipt and does not charge twice. If accounting cannot be committed, withhold the response and terminate void. Test rejected calls and unavailable images include complete budgets, and a storage outage cannot produce an unaccounted response.

#### TDD-3.1.59 No context compaction

<!-- id: TDD-3.1.59 | implements: AG-28 | code: src/research_agent/agents/messages.py#prepare_request | tests: tests/agents/test_context_integrity.py | status: pending:#45 -->

Store canonical conversation messages as append-only ordered artifacts, including native tool-call ids and image identities. prepare_request materializes the entire prior sequence byte-equivalently under the pinned transport serializer; only a new message is appended. Count all tokens including reserved output and image processing before sending. If the next request exceeds context, append budget_exhausted and stop without another provider call. Test a boundary fixture whose oldest evidence would disappear under truncation and compare each successive request prefix exactly.

#### TDD-3.1.60 Hashed eight-part configuration

<!-- id: TDD-3.1.60 | implements: AG-16 | code: src/research_agent/agents/configuration.py#AgentConfiguration | tests: tests/agents/test_configuration_schema.py | status: pending:#77 -->

The strict configuration record contains prompt, scan_policy, read_policy, probability_assignment_rule, tools, budgets, sampling and output_schema. Enforce policy text at most 4000 characters each, assembled system prompt at most 16000 and sampling count exactly one at launch. Hash canonical bytes of all eight parts and their schema version; no mutable description sits outside the identity used by runs. The one submitted probability is the one validated sample, not an average invented from prose. Test every missing part, a one-byte policy change and sampling count three rejection.

#### TDD-3.1.61 Immutable run specification and seed

<!-- id: TDD-3.1.61 | implements: AG-17 | code: src/research_agent/orchestration/specifications.py#build_run_specification | tests: tests/orchestration/test_specification.py | status: pending:#56 -->

Construct the slot tuple (daily_batch_id,shard_id,configuration_id,arm,attempt=0), configuration_hash, snapshot_hash, budgets, tool allowlist and seed before dispatch. Store run_id as the shared UUIDv4 identity; derive specification_seed as the first unsigned 64 bits of SHA-256 over canonical slot identity plus profile hash; derive request_seed as the first unsigned 32 bits over run_id, turn_index and sampling-v1 exactly as TDD-CONTRACTS.md defines. Include mode, model/service manifests and earliest question seal deadline in the immutable specification hash. A questionless engineering slot uses batch seal plus 24 hours as its scheduling deadline and still obeys the 20-minute run cap; it produces no prospective forecasts. Storage rejects reuse of a slot with changed specification. Test missing seed, modified budgets and restart reuse of the same persisted specification.

#### TDD-3.1.62 Durable ordered model transcript

<!-- id: TDD-3.1.62 | implements: AG-29 | code: src/research_agent/agents/transcript.py#record_exchange | tests: tests/agents/test_transcript.py | status: pending:#45 -->

Before network send, stream sanitized canonical request bytes to storage and append a request event with run_id and strictly increasing exchange ordinal. After receipt, persist permitted response bytes and a response event linked to that request before any tool execution. Record explicit failed/ambiguous completion when no response exists; do not invent a paired response. Native call arguments remain exact strings for replay, with parsed validation kept separately. Test storage failure before send prevents network access; failure after response prevents dispatch; altered transcript bytes fail the recorded hash.

#### TDD-3.1.63 Image-delivery manifest

<!-- id: TDD-3.1.63 | implements: AG-30 | code: src/research_agent/agents/transcript.py#record_images | tests: tests/agents/test_image_manifest.py | status: pending:#45 -->

Before attaching image blocks, commit their ordered delivery manifest: run_id, tool_call_id, snapshot_id, family/version ids, figure/page locator, rendered artifact hash, source hash, pixel dimensions and processor identity. Returned content includes exactly that committed sequence. Withhold any image whose manifest commit fails and record unavailable; text tables do not increment image counters. Test two figures retain order, failed recording withholds pixels and replay identifies the exact rendered source version.

#### TDD-3.1.64 Weekly unchanged population checkpoint

<!-- id: TDD-3.1.64 | implements: AG-18 | code: src/research_agent/orchestration/selection.py#record_selection_stage | tests: tests/evolution/test_weekly_noop.py | status: pending:#64 -->

The weekly pipeline writes an idempotent selection_disabled event keyed by (cycle_id, select, profile_hash) through the same owner as TDD-4.1.76, then carries that same population into its checkpoint. Do not create candidate rankings, parent probabilities or fitness artifacts. Missing input ledger/profile yields failed-no-replacement with the previous population still active. Test successive weeks with changing mature forecast scores and interrupted checkpoint append; the active configuration hashes never change.

#### TDD-3.1.65 Disabled parent selection

<!-- id: TDD-3.1.65 | implements: AG-19 | code: src/research_agent/evolution/disabled.py#reject_parent_selection | tests: tests/evolution/test_disabled.py | status: pending:#56 -->

A launch request for parent selection is handled by the common disabled-capability guard before any search, model inference, similarity computation, schema generation or durable candidate creation. Return disabled_by_profile with the active profile hash and append the request disposition through storage. There is no dormant implementation to provision. Test otherwise valid input with a missing profile and an active launch profile: neither authorizes the operation, creates a child nor changes an existing configuration.

#### TDD-3.1.66 Disabled mutation proposals

<!-- id: TDD-3.1.66 | implements: AG-20 | code: src/research_agent/evolution/disabled.py#reject_mutation | tests: tests/evolution/test_disabled.py | status: pending:#56 -->

A launch request for mutation proposals is handled by the common disabled-capability guard before any search, model inference, similarity computation, schema generation or durable candidate creation. Return disabled_by_profile with the active profile hash and append the request disposition through storage. There is no dormant implementation to provision. Test otherwise valid input with a missing profile and an active launch profile: neither authorizes the operation, creates a child nor changes an existing configuration.

#### TDD-3.1.67 Disabled mutation similarity admission

<!-- id: TDD-3.1.67 | implements: AG-21 | code: src/research_agent/evolution/disabled.py#reject_similarity_admission | tests: tests/evolution/test_disabled.py | status: pending:#56 -->

A launch request for mutation similarity admission is handled by the common disabled-capability guard before any search, model inference, similarity computation, schema generation or durable candidate creation. Return disabled_by_profile with the active profile hash and append the request disposition through storage. There is no dormant implementation to provision. Test otherwise valid input with a missing profile and an active launch profile: neither authorizes the operation, creates a child nor changes an existing configuration.

#### TDD-3.1.68 Disabled schema evolution

<!-- id: TDD-3.1.68 | implements: AG-35 | code: src/research_agent/evolution/disabled.py#reject_schema_evolution | tests: tests/evolution/test_disabled.py | status: pending:#56 -->

A launch request for schema evolution is handled by the common disabled-capability guard before any search, model inference, similarity computation, schema generation or durable candidate creation. Return disabled_by_profile with the active profile hash and append the request disposition through storage. There is no dormant implementation to provision. Test otherwise valid input with a missing profile and an active launch profile: neither authorizes the operation, creates a child nor changes an existing configuration.

#### TDD-3.1.69 Graduated integrity exclusions

<!-- id: TDD-3.1.69 | implements: AG-22 | code: src/research_agent/storage/exclusions.py#apply_exclusion | tests: tests/storage/test_exclusions.py | status: pending:#56 -->

Storage enforces transitions active -> run_quarantined -> configuration_quarantined -> authority_revoked, with scope-specific events retaining references to the triggering runs. A verified boundary/protected-write violation quarantines its run; three integrity run quarantines for the same immutable configuration in rolling seven days quarantine that configuration. Ordinary argument errors do not count. Authority revocation requires confirmed repeated protected write after quarantine and an operator disposition; no audit deletion occurs. A new tested configuration plus recorded disposition is required for release. Test skip-step refusal, concurrent third violations, seven-day boundary and unchanged historical forecast bytes.

#### TDD-3.1.70 Exclusion and ledger atomicity

<!-- id: TDD-3.1.70 | implements: AG-23 | code: src/research_agent/storage/exclusions.py#append_exclusion_transition | tests: tests/storage/test_exclusion_ledger.py | status: pending:#57 -->

In the same serializable storage transaction compare the expected exclusion state, append an event naming action, scope id, prior/new state, evidence hashes and operator/system authority, then update the materialized authorization projection. If append fails no effective transition occurs. An idempotency key prevents repeated delivery duplicating the step. Test failure after provisional projection update rolls back both state and event, and reconstruct all authorization state from the ledger in order.

#### TDD-3.1.71 Prompt independence from exclusions

<!-- id: TDD-3.1.71 | implements: AG-24 | code: src/research_agent/agents/messages.py#assemble_system_prompt | tests: tests/agents/test_prompt_independence.py | status: pending:#57 -->

The prompt builder accepts only the immutable configuration and common prompt-schema manifest; scheduling checks exclusion state outside that API. It never reads exclusion events, score reports or future outcome projections. Validate admitted prompt text contains no exclusion-action terminology required forbidden by the SDD, rejecting rather than editing it. Test byte-identical assembly for the same configuration before and after run/configuration quarantine, while scheduler authority independently blocks the latter.


## 4. Reader models and measurement

### 4.1 Contracts

All persistence uses the versioned storage HTTP API and error/identity contracts in TDD-CONTRACTS.md. These modules own computations and projections, not additional durable stores. Existing learning, correction, calibration and passage-retrieval owners remain authoritative.

#### TDD-4.1.1 Pure ledger scoring

<!-- id: TDD-4.1.1 | implements: IN-01 | code: src/research_agent/scoring/scores.py#score_ledger | tests: tests/scoring/test_scores.py | status: pending:#57 -->

Read a complete versioned ScoreInput through the storage API: ordered forecast ids, probabilities, target versions and selected resolution versions. Compute binary Brier losses in float64 in canonical id order; persist result with input hash and scorer version. Missing or invalid records fail the job without a score. Run the real function twice under different clocks and with networking denied and compare canonical output bytes.

#### TDD-4.1.2 Content-free scoring interface

<!-- id: TDD-4.1.2 | implements: IN-02 | code: src/research_agent/scoring/schemas.py#ScoreInput | tests: tests/scoring/test_schemas.py | status: pending:#57 -->

ScoreInput forbids extra keys and admits paper family identifiers but no text, cards, images or model outputs. The scorer role can read ledger scoring projections only; storage rejects its artifact-content requests. Exercise the deployed authorization rules against paper endpoints and score the same permitted projection with paper artifacts absent; losses must remain identical.

#### TDD-4.1.3 Unresolved outcome masking

<!-- id: TDD-4.1.3 | implements: IN-03 | code: src/research_agent/scoring/support.py#resolved_support | tests: tests/scoring/test_support.py | status: pending:#64 -->

Select only explicit true/false resolution versions linked to the exact question target; unknown and absent resolutions increment coverage counters and never enter loss. Validate maturity and question clocks before selection, failing malformed temporal records. Append both immature and overdue unknown forecasts to a fixture and prove the resolved losses stay unchanged while the coverage denominator grows.

#### TDD-4.1.4 Selection disagreement diagnostic

<!-- id: TDD-4.1.4 | implements: IN-04 | code: src/research_agent/scoring/attention.py#pick_nonoverlap | tests: tests/scoring/test_attention.py | status: pending:#64 -->

Deduplicate submitted nomination family ids per configuration/batch and match permitted service-capture ids on that batch. Return 1-len(intersection)/len(nominations), source id and both set hashes. Empty nomination sets or missing source captures return null with reason, never one. Test identical, disjoint, partially intersecting and duplicated sets; verify this diagnostic has no fitness output field.

#### TDD-4.1.5 Probability concentration monitor

<!-- id: TDD-4.1.5 | implements: IN-05 | code: src/research_agent/scoring/calibration.py#concentration_flag | tests: tests/scoring/test_calibration.py | status: pending:#56 -->

Partition by configuration and target definition; sort sealed forecasts by seal sequence and take the latest 200. Require 200 observations, otherwise report insufficient-support. Bin floor(10*p), mapping p=1 to bin9, and flag if one count is at least180. Persist counts, support hash and profile id. Test179/180 boundary, p=1 and multiple configurations; unresolved probabilities participate without being called miscalibration.

#### TDD-4.1.6 Reliability table and diagram

<!-- id: TDD-4.1.6 | implements: IN-06 | code: src/research_agent/scoring/calibration.py#reliability_table | tests: tests/scoring/test_calibration.py | status: pending:#57 -->

For each configuration/target use resolved probabilities in ten fixed bins [0,.1), ending [.9,1]. Store count, mean predicted probability, observed positive fraction and question ids; empty bins carry null means. Render the table with an ordinary plotting function, not a model. Hand-calculated unequal-size bins catch replacing bin means with centers or including unknown outcomes.

#### TDD-4.1.7 Logged author-count baseline

<!-- id: TDD-4.1.7 | implements: IN-07 | code: src/research_agent/scoring/baselines.py#PopularityBaseline | tests: tests/scoring/test_baselines.py | status: pending:#77 -->

Build one fixed scalar covariate log1p(sum of prior citation counts over unique author ids)) only when all author counts have valid pre-seal captures. Train through the shared learning.logistic.fit_binary_logistic and calibrator owners on temporally partitioned logged covariates; do not reconstruct old author totals. Seal available probabilities through the common forecast endpoint with baseline identity and covariate hashes. Test missing author counts, repeated authors and a post-seal replacement; no unavailable row gets a fabricated answer.

#### TDD-4.1.8 Bundle base-rate forecast

<!-- id: TDD-4.1.8 | implements: IN-08 | code: src/research_agent/scoring/baselines.py#BaseRateBaseline | tests: tests/scoring/test_baselines.py | status: pending:#64 -->

Read each qualified target bundle's immutable fitting positive and known counts; compute numerator/denominator and seal that value under a dedicated baseline submitter. Reject zero denominator, unqualified target and changed target definition. Add a later label and a different target's label to storage and prove an existing batch forecast and its denominator remain byte-identical.

#### TDD-4.1.9 Fixed card regression baseline

<!-- id: TDD-4.1.9 | implements: IN-09 | code: src/research_agent/scoring/baselines.py#CardRegressionBaseline | tests: tests/scoring/test_baselines.py | status: pending:#77 -->

Use vector [target raw logit, original overview neighbor distance, head_available, distance_available]; missing numeric values use zero only internally with their masks, and no row with all signal masks false is answered. The fit wrapper validates its four-feature schema and delegates to the common numeric logistic/calibration owners in TDD-CONTRACTS.md and uses only earlier persisted out-of-family head predictions, not in-sample fitted logits. Save covariate schema hash and training availability cutoff. Test changed Jev/metadata fields cannot change inputs; reject a training row whose producing bundle included its family.

#### TDD-4.1.10 Earlier-neighbor forecasts

<!-- id: TDD-4.1.10 | implements: IN-33 | code: src/research_agent/scoring/baselines.py#NeighborBaseline | tests: tests/scoring/test_baselines.py | status: pending:#56 -->

Consume the card's pinned earlier-neighbor ids and known labels for the identical target version with resolution availability strictly before seal. Return (positive_count+1)/(known_count+2), or unavailable for zero known. Store witness label versions in the sealed input manifest. Test two neighbors with future labels and later arrivals leave the result unchanged, and one positive produces2/3.

#### TDD-4.1.11 Sealed population mean

<!-- id: TDD-4.1.11 | implements: IN-34 | code: src/research_agent/scoring/baselines.py#MeanForecaster | tests: tests/scoring/test_baselines.py | status: pending:#57 -->

After valid configuration submissions close but before the question deadline, take at most one accepted probability per configuration/question and compute its arithmetic mean in sorted configuration-id order. Persist contributing forecast ids and seal under a non-population submitter. Late or absent means remain unavailable; do not average baselines or retries. Test a duplicate submit, missing configuration and deadline expiry; selection state cannot consume this submitter.

#### TDD-4.1.12 Baseline availability barrier

<!-- id: TDD-4.1.12 | implements: IN-35 | code: src/research_agent/scoring/baselines.py#validate_baseline_inputs | tests: tests/scoring/test_baselines.py | status: pending:#57 -->

Require each baseline input's captured_at and available_at strictly earlier than batch.sealed_at and validate snapshot membership, target version and training cutoff. Record excluded ids and reasons as a baseline attempt even when all inputs fail. Exercise exact-equality and later timestamps, missing dates and incompatible versions; the baseline cannot read a newer current-card pointer.

#### TDD-4.1.13 Authenticated rating events

<!-- id: TDD-4.1.13 | implements: IN-10 | code: src/research_agent/web/ratings.py#submit_rating | tests: tests/web/test_ratings.py | status: pending:#45 -->

POST the authenticated rater, digest entry id, enum like/dislike/skip and idempotency key through the storage API; server supplies event time. The current rating is the latest append-only rating event for that rater/entry, with prior events retained. Unrated is absence, not skip. Browser tests submit each enum, reject forged rater identity and simulate persistence failure; the UI cannot display saved until storage acknowledges.

#### TDD-4.1.14 Frozen evidence review sample

<!-- id: TDD-4.1.14 | implements: IN-11 | code: src/research_agent/measurement/reviews.py#sample_forecasts | tests: tests/measurement/test_reviews.py | status: pending:#56 -->

At each ISO-week close hash-rank sealed forecast ids with SHA256(profile_id, ISO_week, forecast_id), choose first five or all if fewer, and persist the selection before opening review. Verdicts use supported/unsupported/unassessable with reviewer id and evidence references; absent verdict remains unchecked. Tests verify seeded membership independent of input order and no replacement after an unanswered or unassessable review.

#### TDD-4.1.15 Resolver defect case lifecycle

<!-- id: TDD-4.1.15 | implements: IN-13 | code: src/research_agent/measurement/defects.py#DefectCase | tests: tests/measurement/test_defects.py | status: pending:#64 -->

Create immutable defect events through storage with case id, reporter, source hashes, target definition, resolver version and state open/investigating/confirmed/rejected. A confirmed disposition references reproducible evidence and delegates correction to outcomes.corrections.CorrectionService; it never edits a label directly. Test a preserved malformed-date case reaches correction and a preference-only complaint cannot obtain label-write authority.

#### TDD-4.1.16 Post-rating recorded detail view

<!-- id: TDD-4.1.16 | implements: IN-36 | code: src/research_agent/web/details.py#render_recorded_detail | tests: tests/web/test_details.py | status: pending:#57 -->

Check the requesting rater has a rating for the entry before fetching the redacted ledger projection. Render escaped stored rationale, named probabilities and evidence locators directly in Jinja; map configuration identities to per-entry opaque labels. Missing records yield explicit unavailable panels. Browser tests compare visible values with stored fixtures, deny unrated access and verify injected HTML and hidden configuration/control origins never reach the rendered page.

#### TDD-4.1.17 Question-aligned outcome detail

<!-- id: TDD-4.1.17 | implements: IN-37 | code: src/research_agent/web/details.py#join_outcome_details | tests: tests/web/test_details.py | status: pending:#57 -->

Join forecast, resolution and baseline answers by immutable question id and target definition, never paper id alone. Render true/false only for known resolution; null outcome means unresolved and read failure means unavailable. Keep missing baselines visible. A three-target fixture with one resolved and two unresolved questions catches cross-target joins and copied verdicts.

#### TDD-4.1.18 Forecast-level estimands

<!-- id: TDD-4.1.18 | implements: IN-14 | code: src/research_agent/measurement/comparisons.py#paired_forecast_rows | tests: tests/measurement/test_comparisons.py | status: pending:#57 -->

Construct one row per matched question/configuration pair and target with individual losses; preserve run, family and publication-week ids as clustering metadata. Estimate mean difference over forecast rows before any resampling, never equal-weight run means. Test an uneven run-size fixture where the pooled forecast difference disagrees with the average run difference; report all counts and omitted support.

#### TDD-4.1.19 Shared clustered bootstrap

<!-- id: TDD-4.1.19 | implements: IN-15 | code: src/research_agent/measurement/bootstrap.py#bootstrap_difference | tests: tests/measurement/test_bootstrap.py | status: pending:#56 -->

Accept paired value rows, immutable family/week cluster mapping, requested interval tails and seed. Draw 10000 publication-week samples with replacement using a versioned NumPy generator seeded20260920, carry every family and forecast in each selected week, recompute the forecast-level statistic and take percentile bounds. Preserve method/version and support hashes. Empty or nonfinite samples produce unavailable/no verdict. Test paired row permutation invariance, inseparable families and analytic constant-difference data; callers supply head/Jev multiplicity tails instead of reimplementing bootstrap.

#### TDD-4.1.20 Uncertainty disposition

<!-- id: TDD-4.1.20 | implements: IN-16 | code: src/research_agent/measurement/comparisons.py#interval_verdict | tests: tests/measurement/test_comparisons.py | status: pending:#64 -->

Require finite ordered bounds and the preregistered favorable direction. If low<=0<=high return inconclusive; otherwise indicate the favored direction, with separate minimum-effect pass field where registered. Missing bounds yield unavailable. There is no equivalence verdict without a separate registered margin. Test intervals touching zero, wide intervals around a large estimate and reversed bounds.

#### TDD-4.1.21 Preregistration admission

<!-- id: TDD-4.1.21 | implements: IN-17 | code: src/research_agent/evaluation/registrations.py#ComparisonRegistration | tests: tests/measurement/test_registrations.py | status: pending:#56 -->

Validate one primary metric, direction, population, sampling/splits, minimum effect, exclusions, failure handling, stop rule and canonical configuration hash before a comparison job obtains a lease. Resolve the immutable registered record through storage and delegate to the same registration validator as TDD-2.1.21 and verify evidenced registration precedes first comparison execution. Signed pre-runtime findings retain original provenance when imported. Tests reject two primaries, backdated unproven registration and attempts to alter a consumed registration.

#### TDD-4.1.22 Complete run accounting

<!-- id: TDD-4.1.22 | implements: IN-18 | code: src/research_agent/measurement/reports.py#run_accounting | tests: tests/measurement/test_reports.py | status: pending:#57 -->

Freeze issued run specifications and states at a ledger watermark, then left-join results by run id. Include scheduled, running, void, failed, quarantined and completed dispositions with missing-result reasons. Compare distinct run-id count to the frozen specifications before committing report artifacts. An integration fixture with unfinished and void runs catches reporting only successful submissions.

#### TDD-4.1.23 Defect audit denominators

<!-- id: TDD-4.1.23 | implements: IN-39 | code: src/research_agent/measurement/defects.py#defect_report | tests: tests/measurement/test_defects.py | status: pending:#64 -->

Group investigated cases by resolver version and report confirmed defects, investigated cases, open cases and null rate when investigated=0. Label the ratio as selected-audit evidence; uninvestigated cases cannot enter the denominator. Read rationale-support reviews from a different schema only for a separate section. Tests change all support-review verdicts without changing defect statistics.

#### TDD-4.1.24 Attention comparison provenance

<!-- id: TDD-4.1.24 | implements: IN-40 | code: src/research_agent/measurement/attention.py#service_comparison | tests: tests/measurement/test_attention.py | status: pending:#64 -->

Build a descriptive record with service id, capture interval, canonical family overlap and rating coverage. Permit a forecast metric attachment only from the shared scorer on matched sealed question ids. Missing source identity disables that comparison. Tests pass service picks without probabilities and require coverage output with no Brier loss or skill field.

#### TDD-4.1.25 Captured service lead times

<!-- id: TDD-4.1.25 | implements: IN-41 | code: src/research_agent/measurement/attention.py#forecast_lead_time | tests: tests/measurement/test_attention.py | status: pending:#56 -->

For each source-captured pick select the earliest valid sealed citation_reach_365d forecast with p>0.75 and seal time strictly earlier than capture, per configuration. Return (capture_at-sealed_at).total_seconds()/86400, question id, registered threshold and source-capture id; no crossing and unavailable history are distinct states. Tests cover p=.75, equality of timestamps and a later favorable forecast. Do not interpret capture time as the source's unknowable first recommendation time.

#### TDD-4.1.26 External emergency halt

<!-- id: TDD-4.1.26 | implements: IN-19 | code: src/research_agent/ops/control.py#halt_runs | tests: tests/ops/test_control.py | status: pending:#57 -->

An operator-invoked host utility outside Compose writes a durable admission-deny marker in the host control directory, revokes run network access, stops orchestrator admission and all labeled run containers, escalating termination to forced kill. Capture runtime container ids and actual completion; any survivor yields incomplete and nonzero exit. Queue its signed halt event for storage import when storage recovers. An isolated host acceptance test freezes application processes before invoking the utility and verifies no run can restart.

#### TDD-4.1.27 Accepted-state restoration

<!-- id: TDD-4.1.27 | implements: IN-20 | code: src/research_agent/ops/control.py#restore_accepted_state | tests: tests/ops/test_control.py | status: pending:#57 -->

While admission remains denied, verify the last accepted manifest and all population/model/bundle hashes; ask storage to atomically restore only active pointers in one compare-and-swap transaction. Preserve the complete ledger and append restoration lineage. Missing artifacts keep the system halted with no pointer changes. A recovery integration test alters active pointers, restores, and compares ledger prefix and restored hashes; restoring does not itself release the halt.

#### TDD-4.1.28 Private operational delivery

<!-- id: TDD-4.1.28 | implements: IN-21 | code: src/research_agent/ops/alerts.py#deliver_alert | tests: tests/ops/test_alerts.py | status: pending:#56 -->

Evaluate profile conditions into a stable condition/component/version key and persist raised_at plus pending delivery. Delivery means the authenticated private app's alert inbox has durably accepted the item, not that a user read it; app unavailability retains pending. Store delivered_at and same-UTC-day status, retry pending deliveries without duplicate rows. Test unavailable app crossing midnight remains late/not-delivered rather than falsifying timestamps.

#### TDD-4.1.29 Explicit acknowledgment state

<!-- id: TDD-4.1.29 | implements: IN-22 | code: src/research_agent/ops/alerts.py#acknowledge_alert | tests: tests/ops/test_alerts.py | status: pending:#57 -->

Create one outstanding unread projection when delivery commits. Only an authenticated acknowledgment event for the alert id closes it; HTTP GET/page rendering does not. Preserve acknowledgment author and time. Exercise browser refresh, failed acknowledgment and concurrent duplicate acknowledgment; one logical event closes unread, while inability to query acknowledgment fails toward unread.

#### TDD-4.1.30 Untrusted source envelope

<!-- id: TDD-4.1.30 | implements: IN-23 | code: src/research_agent/reader/security.py#SourceEvidence | tests: tests/reader/test_security.py | status: pending:#57 -->

Serialize paper text, locators and image references inside an explicit data-only tool-result envelope, never interpolate them into system/developer instructions or tool definitions. Escape rendered markup; tool authorization validates independent RunSpec identity and budgets after every reply. A hostile source fixture requesting changed tools or protected writes must be refused by actual dispatch validation regardless of model output; no claim that prompt wording alone prevents injection.

#### TDD-4.1.31 Immutable run configuration

<!-- id: TDD-4.1.31 | implements: IN-24 | code: src/research_agent/agents/configuration.py#verify_configuration_digest | tests: tests/agents/test_configuration.py | status: pending:#77 -->

Resolve prompt and RunSpec hashes before worker start, mount only immutable read-only copies, and give the worker no storage configuration-write permission. Recompute hashes on completion and quarantine a mismatch through the normal integrity path. Test attempted writes through both filesystem and every exposed storage/tool route; launch performs no mutation job and operator changes create new configuration versions.

#### TDD-4.1.32 Independent provenance walk

<!-- id: TDD-4.1.32 | implements: IN-42 | code: src/research_agent/measurement/audit.py#audit_provenance | tests: tests/measurement/test_audit.py | status: pending:#77 -->

Run a leased weekly audit outside serving processes. Hash-select up to50 stored score records, follow score-input manifests through resolutions and source/artifact hashes to the independently verified ledger anchor, and report each broken link without repair. Reuse recorded-response replay for latest plus seeded older batch. Test corrupting one leaf artifact and one predecessor hash in a copied store; findings identify affected roots and leave original records untouched.

#### TDD-4.1.33 License admission records

<!-- id: TDD-4.1.33 | implements: IN-25 | code: src/research_agent/compliance/licenses.py#authorize_use | tests: tests/compliance/test_licenses.py | status: pending:#5 -->

Resolve a dated license-review record keyed by source/model identity with permitted purposes, retention constraints, review evidence and expiration when applicable. Before fetch/load/retention, compare requested purpose against this allowlist; absent or incompatible review is a structured refusal. Test granted inference but denied weight redistribution, missing source record and changed model revision; deferred ModernBERT has no launch artifact dependency.

#### TDD-4.1.34 Permitted fetch destinations

<!-- id: TDD-4.1.34 | implements: IN-26 | code: src/research_agent/ingest/access.py#authorize_fetch | tests: tests/ingest/test_access.py | status: pending:#5 -->

Build outbound requests only from configured permitted source adapters and reviewed license records. Validate redirects against the same allowed source policy before following; paywall/auth challenges fail as unavailable without browser fallback, proxying or scraped mirrors. Tests serve a redirect from an allowed source to an unapproved/paywalled route and verify no second request occurs.

#### TDD-4.1.35 Sanitization and retention lineage

<!-- id: TDD-4.1.35 | implements: IN-27 | code: src/research_agent/compliance/retention.py#sanitize_payload | tests: tests/compliance/test_retention.py | status: pending:#56 -->

Apply explicit source payload schemas before persistence, removing auth headers, credentials and unrelated contacts while preserving licensed public scholarly author metadata. Record transport hash, sanitized payload hash and retention class. Deletion creates a tombstone and invalidates dependent replay qualifications through storage lineage, with secrets never in diagnostics. Tests verify sanitized bytes, log redaction and a required-deletion walk that preserves permitted audit ids without retaining prohibited content.

#### TDD-4.1.36 Automated-output framing

<!-- id: TDD-4.1.36 | implements: IN-28 | code: src/research_agent/web/rendering.py#validate_output_label | tests: tests/web/test_rendering.py | status: pending:#57 -->

All digest and report renderers consume one fixed automated-output notice and dated-probability formatter. Validate the notice is present before publication/storage; format predictions with target, seal time and finite probability, not an authored finding. Test missing-notice rejection at the publication boundary and escaped model text that attempts to override the notice.

#### TDD-4.1.37 Operational latency summaries

<!-- id: TDD-4.1.37 | implements: IN-29 | code: src/research_agent/measurement/timing.py#timing_report | tests: tests/measurement/test_timing.py | status: pending:#77 -->

Compute publication-to-ingest hours and ingest-to-card, queue wait, first-model-call-to-submit and batch-to-digest seconds from validated UTC pairs. Store count, missing/invalid count and float64 median/95th percentile using pinned NumPy linear quantiles. Never substitute monotonic clock values for UTC; absent endpoints are unavailable. Test known durations and mixed clock-domain rejection. Link service lead-time diagnostics separately; these latencies are not prediction timing accuracy against chance.

#### TDD-4.1.38 Agent calibration reporting

<!-- id: TDD-4.1.38 | implements: IN-30 | code: src/research_agent/measurement/reports.py#calibration_section | tests: tests/measurement/test_reports.py | status: pending:#57 -->

Attach each configuration/target's reliability_table artifact at the report watermark together with resolved and unresolved counts. No pooled diagram merges target definitions or substitutes head calibration for agent calibration. Empty support renders unavailable. A fixture of .9 forecasts with 50% positives must display mean .9 and observed .5 and remain separate from a well-calibrated head.

#### TDD-4.1.39 Nominated-topic dispersion

<!-- id: TDD-4.1.39 | implements: IN-31 | code: src/research_agent/measurement/topics.py#topic_entropy | tests: tests/measurement/test_topics.py | status: pending:#56 -->

Deduplicate nominated family ids, obtain snapshot-valid primary subfields and compute -sum(p*log(p)) over known labels, using natural logs. Return distinct count, unknown fraction and same-day eligible-pool comparator with matching deduplication. No known labels produces null entropy, not zero. Test one-topic/equal-three-topic distributions and unknown-only data; no entropy enters selection.

#### TDD-4.1.40 Evidence-support review report

<!-- id: TDD-4.1.40 | implements: IN-32 | code: src/research_agent/measurement/reviews.py#support_report | tests: tests/measurement/test_reviews.py | status: pending:#57 -->

Join the frozen sample to adjudicated supported/unsupported/unassessable verdicts. Report unsupported/(supported+unsupported), that assessable count, unassessable and unchecked counts separately; empty assessable support is null. Do not infer whether evidence caused a model response. Test adding unchecked or unassessable reviews changes coverage but not the assessable failure ratio.

#### TDD-4.1.41 Immutable card assembly

<!-- id: TDD-4.1.41 | implements: RD-01 | code: src/research_agent/reader/cards.py#assemble_card | tests: tests/reader/test_cards.py | status: pending:#68 -->

Resolve paper/version, bundle, graph and assessment artifacts through an immutable input-assembly manifest at a declared cutoff. Commit the card before snapshot sealing references it and its exact inputs. Replay resolves the already pinned card directly; a crash before card commit cannot publish a snapshot. Produce a versioned Card with core identity/title/abstract/source locator and typed per-signal available/unavailable values. Persist canonical card JSON and deterministic rendered text as artifacts, then compare-and-swap the current pointer through storage. Snapshot references never follow the current pointer. Test optional-service failure still commits readable core and a later promotion leaves old card bytes unchanged.

#### TDD-4.1.42 Per-field producing identity

<!-- id: TDD-4.1.42 | implements: RD-02 | code: src/research_agent/reader/cards.py#ModelSignal | tests: tests/reader/test_cards.py | status: pending:#68 -->

Represent every model-derived scalar as value, model_id, representation_or_bundle_id and provenance_ref; Jev adds identity_kind immutable_revision/mutable_alias. Validate each field independently before assembly and convert a missing producer into unavailable with reason. Render identity beside each scalar rather than only in a footer. Tests change one head identity and leave another unchanged, detecting stale stamps without suppressing the whole card.

#### TDD-4.1.43 Snapshot-valid accuracy stamps

<!-- id: TDD-4.1.43 | implements: RD-03 | code: src/research_agent/reader/cards.py#SignalQualification | tests: tests/reader/test_cards.py | status: pending:#68 -->

Resolve model-state date and metric/report references at card creation using only qualification evidence available by snapshot seal. Stamp head fit dates separately from embedding checkpoint identity/date; Jev uses computation time and alias semantics with no invented checkpoint date. Unavailable accuracy yields unavailable scalar under this contract. Tests attach a newer accuracy report to an old snapshot and require rejection, while unchanged archived evidence stays readable.

#### TDD-4.1.44 Deterministic bounded card text

<!-- id: TDD-4.1.44 | implements: RD-04 | code: src/research_agent/reader/rendering.py#render_card | tests: tests/reader/test_rendering.py | status: pending:#68 -->

Render a fixed ordered text schema: identity and abstract/source-span locator, coverage, three named head outputs, eight Jev fields, earlier neighbors and graph/count diagnostics. Each value includes required provenance and availability; enforce the3000 embedding-token cap using the pinned tokenizer and explicit source-span fallback for an overlong abstract rather than silent truncation. Store rendered bytes once; tool output returns those bytes plus separate query evidence. Golden content tests compare actual text and ensure no binary/pointer-only card is accepted.

#### TDD-4.1.45 Vector-free tool projection

<!-- id: TDD-4.1.45 | implements: RD-05 | code: src/research_agent/reader/projections.py#AgentCardProjection | tests: tests/reader/test_projections.py | status: pending:#57 -->

Construct public tool/card projections from an allowlist of scalar signals, identities, locators and text. Vector arrays, feature pools and model coefficients are absent from the projection schema; storage also refuses vector artifact reads under a run credential. Test all five tool responses using a distinctive vector fixture and reject an extra embedding field at serialization, rather than relying only on searching output strings.

#### TDD-4.1.46 Discovery provenance exclusion

<!-- id: TDD-4.1.46 | implements: RD-14 | code: src/research_agent/reader/projections.py#strip_discovery_origin | tests: tests/reader/test_projections.py | status: pending:#57 -->

Keep captured service picks in a storage namespace unavailable to reader/tool roles. Typed card construction admits no service rank, nomination flag or source-origin field. Test identical papers with different hidden service ranks produce identical cards and graph/tool projections; discovery ids cannot be retrieved through arbitrary artifact locators.

#### TDD-4.1.47 Exact earlier overview neighbors

<!-- id: TDD-4.1.47 | implements: RD-06 | code: src/research_agent/models/neighbors.py#earlier_neighbors | tests: tests/models/test_neighbors.py | status: pending:#56 -->

Load snapshot-eligible original overview vectors with matching representation id; filter verified first_public_at strictly before target and exclude its family. Normalize/validate finite vectors and accumulate float64 dot products over stored float32 coordinates; sort by descending cosine then canonical family id and take five. Return ids/similarities/model provenance, not vectors. Known-vector tests cover ties, wrong revision, uncertain times and duplicate versions.

#### TDD-4.1.48 Descriptive embedding distance

<!-- id: TDD-4.1.48 | implements: RD-07 | code: src/research_agent/models/neighbors.py#neighbor_distance | tests: tests/models/test_neighbors.py | status: pending:#56 -->

Consume the exact selected neighbor result, not a second candidate search, and compute mean(1-cosine) in deterministic neighbor order with float64 accumulation. Record neighbor count, selected ids and representation id. Empty support or invalid vectors produces unavailable. Test orthogonal and identical unit vectors and verify the displayed label contains no novelty/anomaly probability interpretation.

#### TDD-4.1.49 Snapshot graph counters

<!-- id: TDD-4.1.49 | implements: RD-10 | code: src/research_agent/reader/graph.py#graph_summary | tests: tests/reader/test_graph.py | status: pending:#56 -->

Read captured deduplicated family edges and bibliography match observations from storage. Return incoming unique families, outgoing unique families and matched bibliographic entries/total parsed entries with graph hash, capture times and unknown counts. Empty parsed bibliography makes match fraction null; a missing graph makes counts unavailable, not zero. A fixture with repeated DOI/preprint aliases and partial index coverage catches double counting and false completeness.

#### TDD-4.1.50 Earlier-neighbor outcome projection

<!-- id: TDD-4.1.50 | implements: RD-11 | code: src/research_agent/reader/graph.py#neighbor_outcomes | tests: tests/reader/test_graph.py | status: pending:#56 -->

For each selected neighbor retain only exact-target resolution versions available strictly before snapshot seal, and retain its entry even when no target has a known outcome. Include label id, state, available_at and source observation ref; enforce earlier corpus arrival in addition to the neighbor representation's first-public ordering. Tests distinguish publication from corpus-arrival times and exclude a label corrected after seal.

#### TDD-4.1.51 Snapshot bibliographic counts

<!-- id: TDD-4.1.51 | implements: RD-12 | code: src/research_agent/reader/counts.py#author_counts | tests: tests/reader/test_counts.py | status: pending:#77 -->

Read only explicitly captured public prior-author citation counts visible at snapshot, keyed by canonical author id with source/capture time. Missing author or ambiguous identity yields unavailable for that author. Render repository/Hugging Face/download counters as disabled-by-profile without fetching them. Test later author-count replacement cannot mutate a frozen card and source errors never become zero.

#### TDD-4.1.52 Reference centroid distance

<!-- id: TDD-4.1.52 | implements: RD-13 | code: src/research_agent/models/neighbors.py#reference_centroid_distance | tests: tests/models/test_neighbors.py | status: pending:#56 -->

Select deduplicated outgoing reference families with snapshot-visible original overview vectors in the same representation. Sum in canonical family order, divide by present count and normalize in float64; return 1-cosine(target,centroid), present/missing counts and provenance. No references or zero centroid gives unavailable. Test cancelling vectors, missing reference vectors and duplicate aliases.

#### TDD-4.1.53 Separated assessment card section

<!-- id: TDD-4.1.53 | implements: RD-15 | code: src/research_agent/reader/assessments.py#assessment_section | tests: tests/reader/test_assessments.py | status: pending:#54 -->

Resolve only a committed assessment artifact compatible with the qualification manifest pinned by that snapshot; current qualification is checked only before publishing into future snapshots, never to rewrite historical replay. Emit eight named fields or per-field unavailable records in a distinct Jev section; do not derive aggregate rank or quality. Reader assemblers pass no assessment object to learning feature assembly, outcome resolution or baseline schemas. A contract test mutates every assessment field and compares forbidden downstream input hashes unchanged.

#### TDD-4.1.54 Versioned eight-question rubric

<!-- id: TDD-4.1.54 | implements: RD-16 | code: src/research_agent/assessments/rubric.py#Rubric | tests: tests/assessments/test_rubric.py | status: pending:#54 -->

Encode the exact SDD eight rows as immutable field ids, ordered categories, full criteria and development-only positive/boundary examples. Compute a canonical rubric hash and create one Choice per row regardless of contribution type. Reject unknown keys, extra questions, missing criteria and an altered body under a reused version. Fixture tests compare the full outbound schema with the approved rubric artifact and deny run-role mutation.

#### TDD-4.1.55 Whole extracted-text assessment input

<!-- id: TDD-4.1.55 | implements: RD-17 | code: src/research_agent/assessments/input.py#build_assessment_input | tests: tests/assessments/test_input.py | status: pending:#56 -->

Build state text from the saved version's body, appendices, captions and table text in document order with extraction coverage, using no popularity or other-paper context. Validate nonempty usable text, UTF8 byte length<=131072 and verified provider total request/token limits including rubric overhead. Over-limit state returns unavailable before any request; no truncation or summary. Test multibyte text at the byte boundary, missing sections and metadata contamination.

#### TDD-4.1.56 Strict categorical result state

<!-- id: TDD-4.1.56 | implements: RD-18 | code: src/research_agent/assessments/schemas.py#AssessmentResult | tests: tests/assessments/test_schemas.py | status: pending:#54 -->

Use a discriminated union: available carries category, ordered probability map and optional provider confidence; unavailable carries reason and no probabilities. Validate exactly eight rubric fields, all expected categories, finite nonnegative probabilities summing within 1e-6 of one, confidence in[0,1] when supplied and selected category membership. Retain low confidence and rubric categories such as insufficient-information as valid answers. Test NaN, missing categories, malformed sums and timeout without renormalization or fabricated answers.

#### TDD-4.1.57 Assessment attempt provenance

<!-- id: TDD-4.1.57 | implements: RD-19 | code: src/research_agent/ingest/jev.py#persist_attempt | tests: tests/ingest/test_jev.py | status: pending:#54 -->

Persist sanitized request/response artifacts, input/extraction hashes, rubric hash, configured and returned identity, identity pinning kind, request/completion times and qualification reference through storage before publishing an available result. Keep actual available_at distinct from provider computation time. Failed persistence leaves no reader-visible valid result. Test alias-only identity with no invented weights hash and a crash between response receipt and manifest commit.

#### TDD-4.1.58 Bounded ingest assessment adapter

<!-- id: TDD-4.1.58 | implements: RD-20 | code: src/research_agent/ingest/jev.py#JevWorker | tests: tests/ingest/test_jev.py | status: pending:#56 -->

Acquire a storage-backed lease on SHA256(input_hash,rubric_hash,provider_config_hash), reuse committed results and reserve worst-case funded cost before sending. Enforce two concurrent attempts,30s timeout,1000 daily attempts and all monetary limits; retry once after 2s only for explicit429/503 rejection. Ambiguous timeout retains billing reservation and unavailable status without automatic retry. Test a real local HTTP fault endpoint, concurrent same-key jobs and budget exhaustion; reader has no provider route.

#### TDD-4.1.59 Assessment version publication

<!-- id: TDD-4.1.59 | implements: RD-21 | code: src/research_agent/reader/assessments.py#publish_assessment_version | tests: tests/reader/test_assessments.py | status: pending:#56 -->

Commit new immutable result/card artifacts with actual availability and conditionally advance current-card pointer; old snapshot memberships stay pinned to prior artifact hashes. Retrieval must supply snapshot id, never choose latest assessment implicitly. Test recomputation against two snapshots and attempted referenced-blob overwrite, plus recorded-response replay that uses original assessment bytes.

#### TDD-4.1.60 Per-field assessment qualification

<!-- id: TDD-4.1.60 | implements: RD-22 | code: src/research_agent/measurement/jev.py#qualify_rubric | tests: tests/measurement/test_jev.py | status: pending:#56 -->

Materialize the fixed200-paper20-week sample and 50/150 split before predictions; annotation access excludes predictions. Store two independent verdicts and explicit adjudication per field, preserving disputed/unknown references. For each field require profile coverage, compare multiclass Brier sum to development frequencies through the shared publication-week bootstrap using one-sided99.375% upper bounds, and record confusion/macro-F1/agreement/latency/cost. All eight must pass; recheck on 50 fresh papers every 30days and suspend affected fields on>.02 Brier degradation or<80% coverage. Tests fail the whole promised rubric when the eighth field fails and reject reused held-out examples as fresh.

#### TDD-4.1.61 Paired prospective assessment trial

<!-- id: TDD-4.1.61 | implements: RD-23 | code: src/research_agent/measurement/jev.py#JevBenefitStudy | tests: tests/measurement/test_jev.py | status: pending:#56 -->

Resolve a preregistered study id before issuing evidence-first paired runs, randomizing with/without exposure order from a recorded seed while holding snapshot/model/questions/budgets fixed. Allocate first 2000 eligible families across>=26 publication weeks; retain assigned treatment, actual exposure and failure states. Wait for 455-day mature resolutions and require>=70% matched support,>=.01 reach Brier gain and 95% lower bound>0 using shared bootstrap. Other targets remain secondary. Tests preserve failed delivery in assignment denominators and refuse a benefit verdict before maturity.

#### TDD-4.1.62 Assessment activation evidence

<!-- id: TDD-4.1.62 | implements: RD-24 | code: src/research_agent/assessments/readiness.py#check_assessment_readiness | tests: tests/assessments/test_readiness.py | status: pending:#56 -->

Validate referenced provider access/retention evidence, identity semantics, actual input limits, funded profile, immutable rubric, successful full qualification and prospective registration at a storage watermark. Return typed failed gates; immature prospective outcomes are not a gate. Transient unavailable attempts after activation do not revoke past qualification automatically. Tests remove each evidence record individually and verify study activation fails while collection mode remains allowed.

#### TDD-4.1.63 No deferred encoder dependency

<!-- id: TDD-4.1.63 | implements: MD-01 | code: src/research_agent/models/policy.py#validate_launch_models | tests: tests/models/test_policy.py | status: pending:#64 -->

Validate active model manifests against launch roles: frozen embedding representation, numeric head bundle and configured agent endpoint only. Separate trainable-encoder artifacts/jobs are rejected disabled-by-profile; missing ModernBERT artifacts do not affect readiness. Test actual deployment configuration validation with no deferred weights and with an injected training dependency.

#### TDD-4.1.64 Training ancestry gate

<!-- id: TDD-4.1.64 | implements: MD-02 | code: src/research_agent/learning/policy.py#validate_training_origin | tests: tests/learning/test_policy.py | status: pending:#57 -->

Apply ancestry validation to any proposed neural-weight training job before job creation, then reject that job as disabled at launch. Require a published-weight artifact and verifiable parent chain if a future admitted type reaches validation; numeric logistic heads use their explicit fitting exemption. Test absent ancestry cannot create a checkpoint and normal head fitting is not incorrectly rejected.

#### TDD-4.1.65 Pinned representation selection

<!-- id: TDD-4.1.65 | implements: MD-03 | code: src/research_agent/models/policy.py#validate_representation_adoption | tests: tests/models/test_policy.py | status: pending:#77 -->

Resolve the profile's exact representation revision and qualification manifest; no registry query for newest release participates in serving. A different revision requires a separately qualified namespace and explicit accepted activation manifest, not a date comparison. Test introducing a later available checkpoint leaves active representation and all snapshot vector ids unchanged.

#### TDD-4.1.66 ModernBERT admission refusal

<!-- id: TDD-4.1.66 | implements: MD-04 | code: src/research_agent/models/policy.py#reject_deferred_encoder | tests: tests/models/test_policy.py | status: pending:#64 -->

Return disabled-by-profile for requests naming the deferred ModernBERT service or training pipeline, with audit disposition and no weight download. This shares the launch-model policy rather than adding a dormant implementation. Test request rejection occurs before filesystem/network/model allocation and leaves the active frozen bundle intact.

#### TDD-4.1.67 Pinned embedding inference

<!-- id: TDD-4.1.67 | implements: MD-06 | code: src/research_agent/models/embedding.py#FrozenEmbedder | tests: tests/models/test_embedding.py | status: pending:#56 -->

Verify Qwen3-Embedding-0.6B revision97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3 and actual file hashes, load CPU float32 in evaluation/inference mode with gradients disabled, and pool the last non-padding token into 1024 dimensions with L2 normalization. Documents have no query prefix; queries use the exact profile instruction/newline format. Delegate overview/passage feature assembly to existing learning.features owner. Tests use a small real-model qualification fixture to verify padding invariance, dimension, finite norm and 2048-feature output; default CI validates manifest/text contracts without downloading weights.

#### TDD-4.1.68 Fixed neighbor quality evaluation

<!-- id: TDD-4.1.68 | implements: MD-12 | code: src/research_agent/measurement/retrieval.py#reference_rank_evaluation | tests: tests/measurement/test_retrieval.py | status: pending:#56 -->

Use the profile's locked100-paper source-anchored sample and five seed-selected earlier random controls per paper, recording all eligible reference/control ids before model results. Require evidence each candidate existed in the relevant corpus by target arrival; missing history excludes it with reason. Compute reference-vs-control ranking and relevance@5 separately from passage recall, preserving representation id. Known-time vector fixtures catch later candidates and a model version accidentally sharing an old report.

#### TDD-4.1.69 Exact bibliography edges

<!-- id: TDD-4.1.69 | implements: MD-07 | code: src/research_agent/ingest/bibliography.py#parse_identified_references | tests: tests/ingest/test_bibliography.py | status: pending:#56 -->

Use a non-executing parser to extract DOI/arXiv identifiers and source character spans from bibliography blocks. Canonicalize identifiers through the shared identity service; exact resolved aliases produce family edges and ambiguous strings remain unmatched entries. Never invoke TeX compilation or fuzzy title matching. Test malicious TeX, duplicate preprint/journal identifiers and an ambiguous near-title match against preserved source fixtures.

#### TDD-4.1.70 Captured graph merge

<!-- id: TDD-4.1.70 | implements: MD-08 | code: src/research_agent/ingest/graph.py#merge_graph_observation | tests: tests/ingest/test_graph.py | status: pending:#56 -->

Merge exact source-parsed edges and captured OpenAlex relationships by ordered source/target family ids, retaining a list of evidence refs and availability timestamps. Publish a new immutable graph manifest through storage, never mutate older snapshot memberships. Keep this graph view separate from outcomes' observation/capture-completion protocol. Tests merge duplicate edges once and preserve missing-remote coverage rather than asserting an empty complete graph.

#### TDD-4.1.71 No OCR execution path

<!-- id: TDD-4.1.71 | implements: MD-10 | code: src/research_agent/reader/extraction.py#validate_extraction_policy | tests: tests/reader/test_extraction.py | status: pending:#57 -->

Allow only non-executing source parsing, PDF text-layer extraction and image rendering. Validate deployment model inventory and extractor configuration against this allowlist; no OCR packages/models or external OCR endpoints are permitted. An image-only PDF yields explicit missing text plus available page images. Test actual extraction on an image-only fixture and fail image/config validation when an OCR dependency is declared.

#### TDD-4.1.72 Bounded page and figure media

<!-- id: TDD-4.1.72 | implements: MD-11 | code: src/research_agent/reader/media.py#render_deep_read_media | tests: tests/reader/test_media.py | status: pending:#56 -->

Resolve immutable source/PDF hashes and requested section or one/two pages, extract source figures/table text when available and otherwise rasterize those pages at 150dpi bounded to1600px. Return locator, coverage, media hash and untrusted-data marker, with at most two images and 6000 agent-model text tokens; oversized text uses explicit immutable spans and next_span pagination under the profile. Run the renderer in a restricted subprocess with input/output/time limits and no network. Tests exercise a PDF-only fixture, invalid pages and malicious source instructions without changing tool authority.

#### TDD-4.1.73 Read-only embedding weights

<!-- id: TDD-4.1.73 | implements: FT-06 | code: src/research_agent/models/policy.py#verify_frozen_weights | tests: tests/models/test_policy.py | status: pending:#57 -->

Stream hash-verified embedding artifacts through storage into the model service private disposable cache, exposing inference without training authority and expose only inference interfaces; the head fitting process receives numeric features, never a writable neural module. Record before/after manifest hashes around weekly execution and fail qualification on mutation. An integration test executes actual head fitting/refresh over saved features while checking model artifact hashes and denied write attempts.

#### TDD-4.1.74 Inference-only agent endpoint

<!-- id: TDD-4.1.74 | implements: FT-07 | code: src/research_agent/agents/model_client.py#InferenceOnlyClient | tests: tests/agents/test_model_client.py | status: pending:#77 -->

Expose only the pinned chat-completions request schema to run workers; deployment egress and credential scope provide no training/fine-tuning route. Batch job admission rejects any agent-weight-update job. Fixed configuration updates produce new immutable prompt identities outside runs and do not modify weights. Test prohibited endpoint/job admission and verify weekly execution produces no training request.

#### TDD-4.1.75 Per-target matched-support skill

<!-- id: TDD-4.1.75 | implements: FT-12 | code: src/research_agent/scoring/scores.py#target_skill | tests: tests/scoring/test_scores.py | status: pending:#64 -->

Intersect resolved question ids for compared configurations and the sealed fitting-base-rate baseline separately for each target. Compute mean(p-y)^2 and 1-agent_loss/base_loss on that support; baseline_loss=0 yields null skill and empty support yields null loss. Store exact support ids and coverage exclusions; never produce a cross-target aggregate or fitness. Tests remove hard questions, add historical labels without sealed forecasts and check neither silently improves common-support scores.

#### TDD-4.1.76 Idempotent selection disposition

<!-- id: TDD-4.1.76 | implements: FT-13 | code: src/research_agent/orchestration/selection.py#record_selection_stage | tests: tests/orchestration/test_selection.py | status: pending:#64 -->

At the weekly select stage invoke the shared disabled-selection policy and submit one disposition keyed by cycle_id/stage/profile_hash through storage. A retry with identical body returns the committed result; changed population output under the same key is rejected. Inject interruption before and after commit and prove exactly one disposition and unchanged active population.

#### TDD-4.1.77 Disabled evolutionary selection

<!-- id: TDD-4.1.77 | implements: FT-14 | code: src/research_agent/orchestration/selection.py#disabled_selection | tests: tests/orchestration/test_selection.py | status: pending:#56 -->

Validate the immutable launch profile, return selection-disabled plus the current population hash, and invoke no parent draw, replacement or archive operation. Missing profile is a failed stage, never implicit enablement. Test arbitrarily large favorable forecast histories and an attempted enable flag both leave the population unchanged.

#### TDD-4.1.78 Disabled diversity archive

<!-- id: TDD-4.1.78 | implements: FT-15 | code: src/research_agent/orchestration/selection.py#reject_archive_operation | tests: tests/orchestration/test_selection.py | status: pending:#56 -->

Reject archive insert/select requests as disabled-by-profile before any model call or population mutation and record the rejected capability plus profile identity. Do not create an archive service or schema solely for dormant search. A contract test with otherwise valid inputs verifies refusal and absence of model/job/storage mutation beyond the audit event.


The disabled weekly selection stage has one implementation owner, orchestration/selection.py#record_selection_stage, and one idempotency key (cycle_id, select, profile_hash) across AG-18 and FT-13. Neither caller appends a second event. The IN-35 pre-batch input barrier applies to IN-07 to IN-09 and IN-33 only; IN-34's population-mean comparison is computed after member submissions and remains separately labeled.
