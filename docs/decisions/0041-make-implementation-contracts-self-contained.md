# 0041. Make implementation contracts self-contained

- Status: accepted
- Date: 2026-10-06
- Spec: SDD-CP-01 to SDD-UI-05; TDD chapters 1 to 7

## Context

The technical design mostly named owners and broad gaps. It did not expose the implemented data, interfaces, transaction boundaries, failure states and verification for each requirement. One-to-one traces also hid working parts when a whole requirement remained incomplete. Scattered development notes and external work references made the documents difficult to interpret on their own.

## Decision

Retain root SDD.md, TDD.md and SPEC-AMENDMENTS.md as the authoritative contracts. Preserve all existing requirement and primary technical IDs. Decompose each SDD requirement into several supporting TDD contracts, each with exactly one requirement backlink. List every supporting contract in its SDD trace.

Use implemented, pending or deviation statuses without external work references. Status belongs to the specific contract. A whole requirement is implemented only when every linked technical contract is implemented. Each pending contract states its exact missing behavior and required acceptance evidence in full. A passing owner-existence check or unrelated test count cannot complete it.

Define current DTOs, routes, schemas, state transitions, commit boundaries, budgets, UI behavior and negative cases using actual implementation owners. Retain the original behavioral requirements; do not weaken them to match a defect or invent a separate subsystem to hide a gap.

Consolidate development notes and retired scaffolding Markdown into docs/DEVELOPMENT.md. Keep active operating instructions, accepted decisions, dated evidence, schemas and consumed fixtures with their owners. Remove the empty intake page. Documentation states rationale and gaps without issue references; external work tracking is separate from document authority.

## Consequences

The specification checker verifies one-to-many coverage, backlinks and completion aggregation locally. The documentation gate rejects missing local links, missing owner symbols, tracker references and scattered development Markdown. Both gates include negative cases. Numbering reservations cite local decision records, and amendments record their change and rationale without an external pull request prerequisite.

Implemented parts become visible without concealing incomplete parent requirements. The source and browser reviews support the current contracts but do not establish full release conformity, live deployment health or provider qualification. Retired forecasting, qualification and rating scope remains excluded.
