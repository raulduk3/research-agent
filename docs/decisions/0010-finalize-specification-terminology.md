# 0010. Finalize specification terminology

- Status: accepted
- Date: 2026-09-21
- Issue: #57
- Spec: SDD Terms; terminology throughout SDD sections 1 to 8 and Appendices A to C; terminology throughout the TDD
- Pull requests: pending
- Amends: 0003, which kept a historical alias table in the SDD Terms

## Context

Decision 0003 standardized the specification's terms but kept a table mapping retired wording to current wording, and the documents still used several retired forms: bare "head" and "card", "embedder", "claim" for a forecast, "sanction" and "sleeper". The Terms table also defined general vocabulary such as calibration, checkpoint and batch job alongside project-specific names.

## Decision

The SDD and TDD use only the current terms. Prose says prediction head, paper card, embedding model, forecast, forecast probability, exclusion action and delayed recognition; the chain head of the ledger keeps that name. Code identifiers, field names and schema values are unchanged.

The SDD Terms table defines only terms specific to this project or to its study design. The historical alias table and the terminology source list are removed. General technical terms keep their usual meaning.

## Consequences

Requirement ids, statuses, behavior, thresholds and traceability are unchanged; only wording changes. Earlier decision records, issues and incoming candidates keep their original wording, and decision 0003 names the current term for each retired one.
