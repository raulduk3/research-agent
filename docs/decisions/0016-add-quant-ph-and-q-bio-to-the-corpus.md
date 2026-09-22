# 0016. Add quant-ph and q-bio to the corpus, compared per primary category

- Status: accepted
- Date: 2026-09-22
- Issue: #152, carrying the owner's rule on #66 and the stream locked on #134
- Spec: SDD Document control, Scope and scale, Terms; SDD-EN-01, SDD-IN-08, SDD-RD-08; Appendix A source audit, retrieval qualification, smoke sample and daily-volume measurement; Appendix B target registry, bounded acquisition and qualification, representation and fitting, validation and promotion; TDD-1.1.13, TDD-3.1.1, TDD-4.1.8 and the PaperVersionRecord, CorpusRow, TargetRegistry, SigmoidCalibrator, TargetBundleEntry and SliceMetric records
- Pull requests: #154
- Supersedes: the two-category corpus of decision 0001 and the two-category eligibility rule of decision 0014; preserves the target predicates, thresholds, features and heads

## Context

The corpus was arXiv cs.AI and cs.LG. The owner set the first-release population rule on #66, added quant-ph to it, and then locked one mixed daily stream across cs.AI, cs.LG, quant-ph and q-bio on #134, routed by primary category, with cohorts, base rates and head calibration per category. #136 made the category list a configured value with those four as the default. The three targets count OpenAlex citation metadata alone, so their predicates apply to any category unchanged; what a paper is compared with does not.

## Decision

The corpus consists of every arXiv family whose categories include any of cs.AI, cs.LG, quant-ph or q-bio, stored once under the primary category of its earliest public version. The category list is a configured value recorded with each batch and each corpus release.

- The target predicates and thresholds are the same for every category. No per-category threshold and no quantile estimation.
- Base rates (IN-08), sigmoid calibration (FT-11), release eligibility slices and evaluation reports are computed within the primary category. The heads stay one per target, fitted across all categories on the same features.
- A category whose calibration partition is below the class floor leaves that target unavailable for that category while the others are served.
- The first-release historical corpus is every eligible family whose earliest public version falls in the twelve months ending thirteen months before the build date, drawn uniformly with a recorded seed and capped at 10,000 families across the four categories.
- The source audit, retrieval qualification and Jev smoke samples are allocated across the categories in proportion to their family counts in the sampled weeks, at least one per category. Daily volume is measured per category.

## Consequences

`PaperVersionRecord` and `CorpusRow` gain `primary_category`; `SigmoidCalibrator` carries its category; `TargetBundleEntry` holds one calibrator and one base rate per served category; `SliceMetric` gains the primary-category axis. IN-08 and TDD-4.1.8 compute the base rate over one stratum today and carry `deviation:#75` until the baselines carry the category. Daily volume is unmeasured for all four categories (#19); the daily ceiling of 1000 families in Appendix A stands until it is measured. A later category enters by amendment to EN-01 and the configured list, not by code alone.
