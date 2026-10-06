# 0035. Solidify the capped swarm documentation

- Status: accepted
- Date: 2026-10-06
- Spec: SDD-CP-01 to SDD-UI-05; TDD-1.1.1 to TDD-7.1.5

## Context

The capped requirements and current beta implementation had diverged. The TDD named mostly planned owners, requirement traces did not establish actual implementation, and historical launch guides appeared alongside active guidance. Paper and run pages placed readings below operational detail.

## Decision

Keep the existing capped swarm scope and requirement IDs. Place SDD.md, TDD.md and SPEC-AMENDMENTS.md at the repository root. Use docs/README.md to index supporting operations, API references, accepted decisions, audit evidence and historical records. Merge the old specification index into that index and remove its duplicate scaffold. Archive historical implementation guides without moving runtime fixtures or reviving their requirements.

Map technical items to the existing beta backend and swarm browser. Identify unbuilt gates and partial behavior explicitly. State the exact incomplete contracts and their verification boundaries. Do not infer completion from test counts or replace requirements with descriptions of bugs.

Lead paper and completed-run pages with visible readings and takeaways. Lead island pages with paper output and current runs before configuration. Preserve evidence, replay links and detailed costs. Admit the existing public storm entry as part of the same swarm application.

## Consequences

The specification checker and progress command read root contracts and preserve amendment comparisons against the former location. Supplemental historical records cannot decide active product scope. Page ordering, ingestion continuation, provider receipts, run ownership and support and projection distinctions have separate implementation boundaries. Feedback, assignment, evolution and release-gate discrepancies remain explicit. The current self-contained trace format and single development record are defined by decision 0041. Deployment and service restart require separate authorization.
