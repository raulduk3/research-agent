# 0036. Keep unfinished capped-release contracts explicit

- Status: accepted, documentation format superseded by 0041
- Date: 2026-10-06
- Spec: SDD-CP-01 to SDD-UI-05; TDD-1.1.1 to TDD-7.1.5

## Context

Completing a documentation audit did not complete the contract behaviors it identified. Feedback, assignment, evolution, release gates and cost coverage still had concrete discrepancies. Requirement status had conflated acceptance of a decision with implementation evidence.

## Decision

Keep unfinished contract behavior explicit after documentation consolidation. Preserve narrow runtime repair boundaries. Do not mark behavior implemented because its description or related work record is complete. The current self-contained status and trace format is defined by decision 0041.

## Consequences

Feedback targets, assignment inputs, evolution scoring, release gates and complete cost coverage retain exact pending contracts in the TDD. Runtime repairs remain independent complete changes. Deployment remains a separately authorized operation.
