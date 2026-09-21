# 0009. Reconcile launch contracts and complete technical design

- Status: accepted
- Date: 2026-09-20
- Issue: #77; technical design #71
- Spec: SDD SR-07 to SR-11, SR-17/SR-18, PL-10, IN-07/IN-09/IN-24/IN-29/IN-42, EN-30/EN-31/EN-34/EN-37/EN-40, AG-03/AG-16/AG-34, RD-12, MD-03, FT-07; launch profile; full TDD and shared contracts
- Pull requests: #63, #79
- Supersedes: contradictory residual behavior in those clauses; preserves launch-v1 feature scope and decisions 0004, 0006, 0007 and 0008

## Context

Cross-system technical design exposed residual contradictions after launch choices were fixed. Older clauses still admitted mutation, repeated samples, extra volunteered forecasts and social counters. Others required partial forecast sealing despite atomic complete submissions, an existing ledger before offline qualification, a sealed snapshot before card construction, or timing-forecast accuracy without an event-time target. These would force incompatible implementations.

## Decision

Make the bounded launch behavior explicit throughout: four fixed configurations, one sample per issued question, no schema extension or extra volunteered forecast path, the three immutable citation target definitions, author counters only when captured and optional social counters disabled. New operator configuration versions are immutable and requalified; no automatic evolution exists.

Validate submissions atomically. An invalid attempt produces an audit event and no forecasts or nominations. Correction is permitted within the same original deadline and budget; final failure makes the run void. Issued question identity binds target, resolver and horizon, preventing redundant agent-supplied horizon fields. Agent evidence must have been retrieved; human and baseline producers use equivalent scoped evidence-view/input receipts.

Freeze digest input at one ledger watermark after scheduled slots finish or expire; use accepted nominations, control and service records. Optional human questions have a separate pre-deadline view. Daily coverage is automatic and links the latest applicable bounded independent audit. IN-29 is operational latency, not an undefined event-time forecasting task. Keep score-provenance and source audits distinct, with missingness visible.

Permit evidenced pre-runtime registrations before execution, followed by immutable results imported before activation. Preserve original and import times without fabricated earlier ledger events. Bootstrap host preflight is an operator report imported at first storage activation. Correct document-control text to acknowledge the existing repository tag v0.1.0 without implying an implemented application release.

TDD-CONTRACTS.md owns the shared identity/serialization, storage APIs, authorization, command idempotency, transactions, run lifecycle and qualification boundaries. The full TDD maps all 224 SDD requirements to planned code/test owners, retaining the original 28 stable item ids. One numerical logistic implementation serves separately validated head and baseline feature contracts; one registration owner and one weekly disabled-selection disposition prevent competing implementations. Public cards contain calibrated probabilities, not internal raw logits. Scorer, baseline producer and rater projections have distinct permissions.

## Consequences

This is complete technical-design coverage, not application code or measured model success. Existing draft PR #63 remains the review boundary; implementation work still depends on accepted contracts. #76 tracks actual deployment/access/funding bindings, #78 reviewer and recurring audit operations, #55 endpoint capacity, and #74 final operational acceptance. Missing real hosts, permissions, funds or reference judgments cannot be replaced by invented defaults and do not block writing the design.

No new model, citation target, dataset, platform or autonomous purchasing capability is introduced. Engineering can begin with durable source capture and recorded-response replay, reusing immutable preparation artifacts before paid inference. Qualification failures remain concrete findings that require an explicit affected amendment where behavior changes.

## Technical precision under #71

The detailed catalog under docs/spec/contracts fixes closed field shapes and service routes without adding launch behavior. It separates hashed payloads from publication receipts and qualification reports to prevent circular hashes, uses committed ledger watermarks for visibility, specifies bounded streaming of image-bearing model requests, and defines cost allocations across billing periods. The calibration objective explicitly fixes the one-half L2 convention and optimizer initialization. These are implementation contracts for the existing decisions, not evidence of implementation or qualification.

## Consolidated document ownership

SDD.md now contains the launch, learning and retrieval protocols as named appendices. TDD.md contains all shared rules and exact contract schemas, plus the interface/member map and class diagram. The former companion files are removed; requirement identities and contract payloads remain stable. Named adapter members expose existing routes rather than creating new endpoints. Prior filename references in historical decision and amendment records identify the original location; current navigation points to SDD/TDD sections.

## Implementation dispatch

The fixed launch scope is accepted for sprint-ready implementation. Normalize existing issue path scopes and work dependencies; no feature or numerical policy changes. Start the foundation before source capture, reuse one evaluation owner before Jev comparison, and prepare deployment/reviewer evidence independently. The consolidated contracts must be merged into the develop base before coding; empirical qualification and explicit operational authorizations remain distinct from design acceptance.

Completed deferral #27 preserves EN-28, EN-29, MD-05 and MD-09 as unused ids without requiring an open launch-choice issue. An explicit completed-decision reservation is valid; closing an ordinary reservation still fails validation. This records the accepted deferral and does not restore any excluded feature.
