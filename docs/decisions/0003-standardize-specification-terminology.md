# 0003. Standardize specification terminology

- Status: accepted
- Date: 2026-09-20
- Issue: #57
- Spec: SDD document control, scope, Terms and terminology throughout sections 1 to 8; the amendment ledger lists each changed requirement
- Pull requests: pending

## Context

Several names described different concepts as if they were the same: a forecast probability and assessment confidence, scientific novelty and disagreement with service picks, or neural checkpoints and fitted classifier artifacts. Other names were project-specific but were not identified as such. The owner accepted a terminology-only standardization in #57.

## Decision

Use forecast, forecast probability, forecast batch, paper card, embedding model, prediction head, run specification and structured output schema consistently. Keep genome, population, mutation and fitness with their evolutionary-search meanings. Define a genome as an agent configuration's search representation.

Name RD-07's measure embedding distance and IN-04's measure pick-set non-overlap score. Name the deferred RD-09 signal masked-LM surprise score without choosing its scoring formula. Distinguish operational alerts from paper novelty. Describe the two existing outcome groups as research uptake and online attention tracks, explicitly as proxies rather than proof of quality or independent adoption.

Use checkpoint for neural weights, fitted artifact for fitted predictors, and fit date for a prediction head's refit date. Model-state date is explicitly a project-specific umbrella for the dates already required by SR-15 and RD-03; it adds no new stamping obligation. Exclusion action replaces sanction without changing quarantine or permanent-exclusion behavior.

The glossary identifies project-specific names and preserves historical aliases. It cites dated primary sources, distinguishing recent research terminology from technical standards. The product description matches the existing deferred encoder fine-tuning decision, and the ingest definition acknowledges the existing agent-model API exception.

## Consequences

Requirement ids, requirement count, outcome membership, algorithms, thresholds, timing rules, validation behavior and open decisions remain unchanged. The change does not select a novelty metric, change calibration or bootstrap rules, add features, or accept #56's implementation proposals. Jev's schema and integration remain owned by #54; naming assessment confidence does not implement them.

Historical decision records and incoming candidates retain their original wording, interpreted through the alias table. The TDD has no requirement items to rename. Changed SDD requirements cite #57 while their original behavioral decisions remain in the retained records and amendment history. No runtime implementation or schema migration is introduced.
