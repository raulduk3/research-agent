# 0014. Rank pilot families by arXiv id

- Status: accepted
- Date: 2026-09-21
- Issue: #82
- Spec: SDD FT-18; Appendix B, bounded acquisition and qualification; TDD-1.1.13
- Pull requests: #104
- Supersedes: nothing; clarifies "canonical family id" in the pilot and modeling selection rule

## Context

The acquisition pilot takes the four families per mature month with the lowest SHA-256 of the seed and the "canonical family id". The TDD defines `PaperFamilyId` as a storage-issued random UUID. Ranking on those UUIDs would require registering every eligible paper in the 25 months, about 150,000, before selecting 100. It would also make the selection reproducible only from the stored id mapping, not from arXiv's public data. The existing selection code also admitted only papers whose primary category was cs.AI or cs.LG, although EN-01 and TDD-3.1.1 admit any family whose categories intersect them.

## Decision

The selection hash uses the family's canonical unversioned arXiv id (for example `2305.01234`), encoded as canonical JSON `{"paper_family_id": <arXiv id>, "seed": 20260920}`. A family is eligible when any of its arXiv categories is cs.AI or cs.LG, including cross-lists. The same rule applies to the later 2,000-candidate modeling selection. Storage UUIDs are issued only for selected families.

## Consequences

Anyone can reproduce the pilot and modeling selections from arXiv's public listing and the seed. `learning/corpus.py#select_pilot` ranks `PilotCandidate` records built from the retained listing, and reports eligible counts per month next to the shortfalls. The population now includes cross-listed papers that the primary-only filter dropped.
