# Implementation readiness

Checked 2026-09-20. The launch behavior decisions are finalized under #56, decision 0008 and draft PR #63. Decision 0009 (#77) reconciles the final cross-system contradictions. All 224 SDD requirements now have paired TDD implementation/test owners, with shared interfaces in TDD-CONTRACTS.md. This is a complete design draft for review, not a deployed or qualified system. #71 records the full technical-design work.

## Closed launch contracts

| Contract | Decision and owner |
| --- | --- |
| Three automatic citation targets; one preserved OpenAlex label pipeline | Decision 0007; LEARNING-PROTOCOL.md; EN-12 to EN-17 |
| Frozen Qwen embedding d=1024; title/abstract plus pooled original full-paper input [2048]; output/labels/masks [N,3] | Decisions 0006/0008; MD-06; FT-08/FT-09 |
| Exact historical windows, unknown labels, chronological fitting, calibration, promotion and weekly refresh | LEARNING-PROTOCOL.md; FT-17 to FT-25 |
| Eight Jev original-paper assessments, separate human qualification, no human semantic head labels | Decision 0004; RD-15 to RD-24; launch profile |
| Python/PostgreSQL/local immutable artifacts, isolated services, external GLM endpoint and backup receiver | Decision 0008; SR-28; launch profile |
| Four fixed configurations, two concurrent runs, 20-paper shards, bounded tools/cards and complete slot accounting | AG-01 to AG-35; launch profile |
| Nomination-based private digest with blinded ratings; separate forecasts and preferences | EN-30 to EN-42; IN-10/IN-14/IN-15 |
| Source fallback, graph matching, distances, replay, baselines, preregistration and qualification gates | Retrieval and launch profiles; SDD sections 1, 3 and 6 |
| Resource/spending ceilings, backup/anchor, privacy, alerts and collection/engineering/study modes | Launch profile; SDD sections 1 and 2 |
| Future-head extension path; evolution, extra claim types, encoder training and agent memory disabled | FT-20; decision 0008 |

There are no remaining undecided launch behavior choices after the final reconciliation in #77. #27, #49 and #51 stay open only for deferred extensions and reserved ids. ForeSci is optional development evaluation, not a production judge, selection objective or launch prerequisite. Initial numeric policies are explicit testable defaults, not claims of optimality.

## Evidence and implementation gates

| Gate | Evidence required | Work |
| --- | --- | --- |
| Complete technical contracts | 224 paired technical items and shared contracts are written; PR #63 review/acceptance remains the implementation gate | #71 |
| Durable foundation | Locked application build, real transactional storage, immutable artifacts, idempotency, leases and recovery | #72 |
| Source feasibility | Licensed original versions, citation pagination/dates/subfields, exact identity matching, measured missingness and volume | #19, #26, #31, #65, #66 |
| Frozen representation | Actual artifact/runtime compatibility, licensed access and fixed retrieval acceptance | #25, #70 |
| Three-head qualification | Each head's coverage, class support, held-out baseline improvement and calibration | #67 |
| Jev launch readiness | Verified provider/input/retention rights, independent rubric qualification and preregistered prospective comparison | #59 to #62 |
| Agent-to-digest integration | Snapshot tools, bounded runs, submission/replay, nomination pooling and blinded private ratings | #73 |
| Evaluation correctness | Time-safe baselines, preregistration, leakage controls, replay and denominator-preserving reports | #75 |
| Operations preparation | Actual host/network/backup bindings, access/retention evidence, dated quotes and explicit funding | #76 |
| Human reference operations | Independent Jev/retrieval qualification, reviewer availability and recurring bounded audits | #78 |
| Operating acceptance | Actual busiest-day completion, real endpoint qualification, restore and anchor checks | #55, #74 |

No application build, acquisition pilot, head training, provider qualification or deployment has been completed. Source findings for disabled counters or deferred encoders (#20 to #24) are not launch dependencies. Automatic head labels do not eliminate the bounded independent reference work for Jev/retrieval evaluation or reader ratings. A failing empirical gate produces a specific finding; it does not silently change the target or spend more.

## Incremental implementation

1. Review/accept PR #63 containing the closed SDD and full TDD (#71). Existing implementation issues reference their TDD owners and shared interfaces; no issue becomes sprint-ready solely from document lint. Prepare #76/#78 in parallel without paid execution.
2. Build #72 and the first durable collection/replay path in #65. Preserve originals, provider bytes, identities and checkpoints. Exercise crash recovery before adding live agent calls.
3. Implement pure automatic labels (#66) and full-paper retrieval/shared features (#70). Reuse preserved artifacts; incomplete coverage remains explicit. Run the bounded feasibility pilot before preparing more data.
4. Fit and qualify heads (#67), and implement/qualify Jev (#59 to #62). These share artifacts but keep their supervision and measurements separate.
5. Join the fixed agent/digest path (#73) and deterministic evaluation (#75). Recorded-response engineering precedes paid live endpoint acceptance.
6. Pass #74 capacity, privacy, restore and funded study gates. Only then activate the complete study; future forecasts mature on their real schedule.

The check entrypoint is `bin/check --since develop`, shared with CI. It runs strict document validation and negative-case checker tests now, then locked application checks once source exists. Network issue validation is explicit with `--issues`. Models, provider calls and hardware tests are outside default CI and need their actual authorization and evidence.

## Readiness boundary

SDD-ready means launch choices and failure behavior are fixed and traceable. TDD-ready means every requirement has concrete ownership, interfaces, states and meaningful verification. Implementation-ready issues depend on those accepted contracts. Study-ready additionally means the deployed system passed data/model/provider/operations qualification. Demonstrated benefit requires actual measured outcomes. These states are not interchangeable.

## Implementation ownership and prerequisites

| Work | Primary TDD ownership |
| --- | --- |
| #72 storage/collection foundation | Section 2.1 and TDD-CONTRACTS.md storage, jobs, permissions and bootstrap |
| #65 original papers/citation observations | 1.1.6–7, 1.1.13 and section 3.1 acquisition/ledger items |
| #66 automatic labels/source pilot | 1.1.1–5, 1.1.14–17; section 4.1 source/coverage audits |
| #70 retrieval/features | 1.1.8–9, 1.1.12, 1.1.25–28; section 4.1 reader/model owners |
| #67 heads and refresh | 1.1.8–12, 1.1.17–24; section 4.1 shared numerical/forecast measurement |
| #59–#62 Jev | Section 4.1 rubric/provider/qualification/comparison items; section 3.1 paired run slots |
| #73 fixed agents/digest/rating | Section 3.1 plus section 4.1 private UI projections and shared submission/authorization |
| #75 baselines/replay/evaluation | Sections 2.1 and 4.1; one shared registration and numeric fitting owner |
| #74 final operational acceptance | Section 2.1 deployment/mode/backup/anchor and section 4.1 readiness; evidence from #55/#76/#78 |

All paths in the TDD are planned owners. No test file or service is claimed to exist because its path is named. Implementation issues remain needs-triage until the reviewed contracts and prerequisite slice are accepted. The first code work is #72 plus #65's narrow capture/replay path; later lanes integrate against the same storage/API contracts rather than inventing separate stores.
