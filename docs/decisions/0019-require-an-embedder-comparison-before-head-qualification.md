# 0016. Require an embedder comparison before head qualification

- Status: accepted
- Date: 2026-09-22
- Issue: #150
- Spec: SDD Appendix A: Launch profile, Pinned model choices and representation; Evaluation, leakage and provider qualification
- Pull requests: pending
- Supersedes: the optional SciEmbed-comparison wording in decision 0011

## Context

Decision 0011 pinned `nomic-ai/modernbert-embed-base` as the frozen launch representation and left a SciEmbed comparison optional before any later replacement. #25 asks that SciEmbed be compared with general-purpose embedders before adoption, and that finding does not exist yet. For release 1, the owner decided the comparison is a precondition for qualifying the prediction heads, not an optional check before a later swap.

## Decision

Before the release-1 prediction heads are qualified, a preregistered comparison of at least these candidates runs on corpus release 1: the incumbent `nomic-ai/modernbert-embed-base`, a citation-supervised scientific embedder (`allenai/specter2` with the proximity adapter), `Qwen/Qwen3-Embedding-0.6B`, and a TF-IDF floor. Primary metric is mean held-out log-loss over the three targets on publication-month blocked splits; secondary metric is top-five family recall on the locked retrieval questions. Each candidate's published training-data cutoff is recorded, and label windows overlapping a citation-supervised candidate's training data are reported separately.

The heads are fitted on the winner. The overview slot and the passage slot of the head input may come from different representation namespaces when the comparison favors it; each namespace keeps the full-rebuild and never-mix rules of #36.

A failed or missing comparison leaves the heads unqualified; the incumbent remains the engineering default.

## Consequences

Head qualification for release 1 cannot proceed on the incumbent alone; the comparison in Appendix A: Launch profile is a gate, not a courtesy check before a later swap. #25's finding, once written, settles whether the pinned incumbent stands. No application code exists yet, so nothing is rebuilt by this decision alone.
