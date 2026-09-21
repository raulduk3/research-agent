# Implementation readiness

Checked 2026-09-20. Draft PR #63 closes the launch head design under #64 and full-paper representations under #68. The current contract is decision 0007 and automatic-citations-v1, superseding decision 0005's human-reviewed launch labels. Three heads are configured: citation reach, late-year citation activity and cross-subfield reach. This is a specification, not a claim that data or models passed qualification.

## Settled learning contracts

| Contract | Location |
| --- | --- |
| Three fixed automatic targets and one preserved source pipeline | SDD EN-12 to EN-17; LEARNING-PROTOCOL.md |
| Original title/abstract plus pooled full-paper input [2d]; outputs/labels/masks [N,3] | FT-08, FT-09; RETRIEVAL-PROTOCOL.md |
| Provider-date semantics, 365-day windows, 90-day allowance, unknown handling and reconstructed history | EN-13; FT-17 to FT-21 |
| 100-paper acquisition pilot; 2000 modeling candidates, bounded expansion to 5000 | FT-18, FT-22; learning protocol |
| Chronological partitions, calibration, per-head qualification, atomic promotion and weekly refresh | FT-10, FT-11, FT-23 to FT-25 |
| No human semantic head labels or downstream Jev annotation job | IN-12; FT-20; TDD-1.1.5 and TDD-1.1.15 |
| Three named card fields, separate source-linked passages and original-paper Jev assessments | RD-08, RD-15 to RD-28 |
| Future heads require explicit target versions, label feasibility and incremental-value qualification | FT-20; decision 0007 |
| Per-target agent metrics; no launch automatic performance selection; nomination-based digest | EN-16, EN-41, AG-26, FT-12, FT-14 |

Head counts and outcomes are settled. Do not reopen them merely because no data has been collected. A failed empirical gate creates a concrete finding; it does not silently change the label or claim all three heads are ready.

## Empirical gates

| Gate | Evidence required | Owner |
| --- | --- | --- |
| Source feasibility | Exact identifier matching, complete paginated citation capture, dates/subfields, licensed original text and representative missingness | #65, #66 |
| Frozen embedding capability | Obtainable immutable artifact, license, tokenizer, dimensions and query/document compatibility | #15, #25 |
| Three-head qualification | Per-head coverage, class support, held-out baseline improvement and calibration; all three for full-feature readiness | #67 |
| Original-paper Jev | Verified provider access/retention, input capability, content-assessment qualification and prospective comparison registration | #59 to #62 |
| Agent endpoint and host | Exact artifact/API, tool correctness, resource measurements, spending limits and recovery | #8, #14, #55 |

No acquisition pilot or head training has run. Automatic head labels do not remove the independent human reference work for Jev content-assessment qualification or the reader-rating study.

## Remaining system design before a full TDD

| Decision area | Remaining work | Owner |
| --- | --- | --- |
| Scoring activation | Launch selection is explicitly disabled. Accept a separate policy before activating evolutionary replacement or ForeSci-driven selection | #69, #11 |
| Runtime and persistence | Language/toolchain pins, package boundaries, storage transactions, checks and CI | #43 |
| Operations | Local-state/rented-inference topology, backup/restore, ledger anchor, resource and spending profiles | #6, #8, #55 |
| Agent behavior | Run budgets, population/concurrency, schema bounds, tools/retries; future mutation/replacement parameters remain inactive | #6, #10, #13, #35 |
| Reader measurement | Neighbor/distance/graph fields, extraction fallback and measured passage-retrieval criterion | #6, #25, #29, #32 |
| Evaluation | Whole-system replay, leakage assertions, preregistered Jev comparisons and statistical sample plan | #32, #61, #62 |
| Data handling | Source/correction diagnostics, audit sampling, alert triggers and metadata retention | #6 |

The TDD has 28 concrete learning and passage-retrieval items with planned owners and failure tests. It does not yet cover every SDD requirement. Conditional evolution clauses do not override the explicit launch disablement in FT-14. Runtime, study and provider gates remain separate from specification lint.

## Incremental implementation

1. #65: implement paper/version identity, licensed original-text capture, resumable citation observations and immutable release manifests. Prove interruption resumes without repeated completed downloads.
2. #66: implement the three pure label resolvers and bounded source-feasibility job. Exercise thresholds, date boundaries, duplicate families, missing taxonomy and partial capture. No semantic annotation interface.
3. #70: implement full-paper passage storage/search, source-linked card evidence and shared [2d] features. Prove original-version fidelity and train/inference parity.
4. #67: implement one generic logistic fitting/calibration path for all three definitions, target-specific masks, qualification and atomic bundles. Preserve unavailable fields rather than fabricate forecasts.
5. Integrate one paper-to-card-to-agent-submission-to-digest path with fixed configurations; capture future citation observations and compare with sealed forecasts. Broader population behavior follows its separate contracts.

All four numbered implementation issues remain needs-triage, dependent on the spec amendment and runtime/representation decisions. Acquisition and deterministic resolver work can precede rented agent inference. Original artifacts and embeddings are reused across the three heads and later refits.

## Exit criteria

Learning-design closure means target, source, feature, training, inference, refresh and extension contracts are fixed. Full SDD closure requires remaining launch behavior decisions above to be closed or explicitly deferred. Full TDD readiness requires every active requirement to have an implementation owner, interface and meaningful verification. Study readiness additionally requires empirical qualification and operating capacity. Demonstrated benefit requires actual measured outcomes; none of these states substitutes for another.
