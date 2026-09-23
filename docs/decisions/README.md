# Decisions

Accepted decisions, one record per file, from [0000-template.md](0000-template.md). A record says why a contract changed; the [amendment ledger](../spec/SPEC-AMENDMENTS.md) says which lines changed. Open decisions are GitHub issues.

## Launch contracts and their decisions

| Contract | Decision and specification owner |
| --- | --- |
| Three automatic citation targets; one preserved OpenAlex label pipeline | [0007](0007-adopt-three-automatic-citation-heads.md); SDD Appendix B; EN-12 to EN-17 |
| Frozen modernbert-embed-base embedding d=768; title/abstract plus pooled original full-paper input [1536]; output, labels and masks [N,3] | [0006](0006-adopt-full-paper-passage-retrieval.md), [0008](0008-finalize-launch-operating-profile.md), [0011](0011-use-modernbert-embed-base-embeddings.md); MD-06; FT-08, FT-09 |
| Historical windows, unknown labels, chronological fitting, calibration, promotion and weekly refresh | SDD Appendix B; FT-17 to FT-25 |
| Pilot and modeling selection ranked by canonical arXiv id; cross-listed cs.AI/cs.LG families eligible | [0014](0014-rank-pilot-families-by-arxiv-id.md); FT-18; SDD Appendix B |
| Corpus of arXiv cs.AI, cs.LG, quant-ph and q-bio, one family once under its primary category; fixed predicates, base rates and calibration per category | [0016](0016-add-quant-ph-and-q-bio-to-the-corpus.md); EN-01, IN-08, RD-08; SDD Appendices A and B |
| Eight Jev original-paper assessments, smoke-tested and shown unqualified, no human reference labels or semantic prediction-head labels; held out of the launch until provider access exists | [0004](0004-adopt-jev-launch-assessments.md), [0012](0012-show-jev-after-a-smoke-test.md), [0015](0015-launch-profile-v2.md); RD-15 to RD-24; SDD Appendix A |
| Python, PostgreSQL, local immutable artifacts, isolated services, one named provider's hosted agent endpoint and backup receiver | [0008](0008-finalize-launch-operating-profile.md), [0015](0015-launch-profile-v2.md); SR-28; SDD Appendix A |
| A seeded population of twelve configurations in three islands, two concurrent runs, bounded tools and paper cards, complete slot accounting | AG-01 to AG-35; [0015](0015-launch-profile-v2.md); SDD Appendix A |
| One run per paper, rescaled budgets, a hash-drawn daily coverage sample per island, and a single recommend/preference/rationale nomination per submit | [0022](0022-one-run-one-paper.md); EN-09, AG-04, AG-05, AG-12, AG-17, AG-25 to AG-27, EN-41, IN-04, IN-43; SDD Appendix A, Appendix B |
| Nomination-based private digest with blinded ratings; separate forecasts and preferences | EN-30 to EN-42; IN-10, IN-14, IN-15 |
| One pinned summarizer reading per digest entry, labeled, hash-provenanced, shown after rating; the only model text a rater sees | [0018](0018-add-a-pinned-summarizer-reading-to-the-digest.md); EN-43, SR-04, SR-26, IN-36 |
| Source fallback, graph matching, distances, replay, baselines, preregistration and qualification gates | SDD Appendices A and C; SDD sections 1, 3 and 6 |
| Resource and spending ceilings, backup and anchor, privacy, alerts, collection/engineering/study modes | SDD Appendix A; SDD sections 1 and 2 |
| Future-head extension path; extra forecast types, encoder training and agent memory disabled | FT-20; [0008](0008-finalize-launch-operating-profile.md) |
| Selection on forecast skill after two fixed weekly cycles, measured skill per dollar as tie-breaker and population-size constraint, population floor four | [0015](0015-launch-profile-v2.md); FT-12 to FT-15; AG-06, AG-18 to AG-21; SDD Appendix A |
| Three islands by primary category, cs and quant-ph rated and q-bio the unrated control; one founder per island; migration; ratings as a selection proxy only | [0017](0017-divide-the-population-into-three-islands.md); AG-36 to AG-38, IN-43, FT-26; SDD Appendix A |
| The development Mac in a Linux VM as the application host, its graphics processor as the representation platform, the floor deferred to measured demand | [0015](0015-launch-profile-v2.md); PL-04, PL-10, MD-06; SDD Appendix A |
| Cross-system contradictions reconciled; every requirement paired with a TDD item | [0009](0009-reconcile-launch-contracts-and-complete-tdd.md) |
| Specification terms | [0003](0003-standardize-specification-terminology.md), [0010](0010-finalize-specification-terminology.md) |
| Specification states design only; project status lives in issues and implementation and evidence records | [0013](0013-keep-project-status-out-of-the-specification.md) |

## Issue disposition

- Launch choices in #6, #7, #8, #10 to #17, #28 to #30, #32, #33, #35, #36, #38, #43, #46, #50, #54, #56, #64, #68 and #69 are resolved by the accepted records and SDD Appendix A.
- #27 is a completed deferral that preserves reserved ids EN-28, EN-29, MD-05 and MD-09. #49 and #51 hold deferred extensions and their reserved ids. None of them is unsettled launch behavior.
- #19 to #26, #31, #55, #59 and #61 are evidence or execution tasks, not decisions. The implementation order and evidence gates are tracked in #100.
- ForeSci is optional development evaluation, not a production judge, selection objective or launch prerequisite. Initial numeric policies are explicit testable defaults, not claims of optimality.
