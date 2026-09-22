# 0017. Divide the population into three islands with one unrated control

- Status: accepted
- Date: 2026-09-22
- Issue: #134
- Spec: SDD Scope and scale, Terms; SDD-EN-09, EN-32, EN-33, EN-40, EN-41, IN-10, IN-11, AG-04, AG-05, AG-16, AG-18 to AG-21, FT-13, FT-14 amended; SDD-AG-36 to AG-38, IN-43 and FT-26 added; Appendix A agent batches, seeded evolution and rater access; Appendix B agent scoring boundary; TDD-3.1.13, 3.1.31, 3.1.32, 3.1.35, 3.1.39 to 3.1.41, 3.1.60, 3.1.65 to 3.1.67, 4.1.13, 4.1.14, 4.1.77 amended; TDD-3.1.72 to 3.1.74, 4.1.79 and 4.1.80 added; the AgentConfigBody, SlotIdentity, DigestManifest, digests table and DeploymentBindings records
- Pull requests: #157
- Supersedes: the single-population reading of decision 0015's seeded evolution; preserves its two fixed cycles, skill-only fitness, cost as a size constraint and the archive

## Context

The system serves two researchers in different fields, each wanting agents that read their field and weekly ratings that shape them, while the population shares evolution so that what one island learns can reach the other. Whether ratings improve forecasting or only bend agents toward one reader's taste cannot be told from two rated islands alone. The owner accepted option 1 of #134 on 2026-09-22 and locked the mixed daily stream and the credit rule in two comments the same day.

## Decision

The population is three islands by primary category: cs (cs.AI and cs.LG), quant-ph and q-bio. A genome belongs to one island and runs only on that island's shards; the tools still answer from the whole snapshot. Each island has one founder genome that selection never replaces, a floor of four genomes, and its own share of the monthly spend. Selection, mutation and the archive act within an island; a mutation may take its parent or its changed field from another island as a recorded migration, never into q-bio. Each island has its own daily digest: the cs and quant-ph digests go to their bound rater, the q-bio digest is built and scored and delivered to no one. A rater's like or dislike is credited to every genome of the island whose sealed submission nominated the paper, in proportion to the citation-reach probability each sealed, and to no genome for a control or a service pick; that preference credit is the island's weekly selection proxy while resolved outcomes are too few, and enters no citation-skill score, prediction head or outcome record. The control island's proxy is agreement with the calibrated heads, which a rated island also uses in a week its rater recorded nothing. The weekly report gives every genome's citation skill, preference credit and credited-entry count as separate values, and preregisters three questions: rated against control skill trajectories, migrated traits against local mutations, and drift from the seeds.

## Consequences

The seed becomes twelve configurations, the four launch emphases in each island, with the evidence-first configuration of each island as its founder; owner-written variants enter a named island. `AgentConfigBody` gains `island` and `founder`, `SlotIdentity` and `DigestManifest` gain `island`, the digests table is unique per batch and island, and `DeploymentBindings` binds each rater to one island. The daily bill is the sum of the islands' runs; at four genomes per island it is roughly 125 runs a day. One person's ratings shape a rated island's weekly proxy; the floor, the founder and the random controls limit what a bad week can do, and resolved outcomes replace the proxy as they mature. The per-island spend share is in proportion to each island's paper count in the month so far, a chosen bound. The digest stays daily under EN-40; #134's option text spoke of a weekly digest, and the weekly unit here is the report and the selection stage, not the digest. Left open: the minimum resolved-claim count (#130) and the run shape if one run maps to one paper (#155).
