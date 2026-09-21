# 0011. Keep project status out of the specification

- Status: accepted
- Date: 2026-09-21
- Issue: #100
- Spec: SDD and TDD Conventions and Document control; SDD Appendix A activation gates and Appendix B agent scoring boundary; TDD implementation readiness (removed); TDD section introductions
- Pull requests: #101

## Context

The SDD and TDD had accumulated project status alongside the design: a dated TDD "Implementation readiness" section with sprint-ready issue lists, dispatch order, per-issue ownership and a merge prerequisite for a pull request that has since merged; a build order in the learning protocol; an issue-by-issue disposition list in the launch profile; dated source-check notes; and repeated statements that code and test paths were planned rather than implemented. That text goes stale as work lands, and every update to it churned the normative documents.

## Decision

The SDD and TDD state design only. The trace comment's status is the only implementation state they record.

- Implementation order, evidence gates, readiness states and per-issue TDD ownership live in #100 and the work issues it lists.
- What has been built and verified lives in `docs/implementation/`; provider and source facts checked for the work live in `docs/evidence/`.
- Which decision closed which launch contract, and how the decision and evidence issues are disposed, lives in `docs/decisions/README.md`.

Both documents' Conventions state the rule.

## Consequences

No requirement id, status, behavior, threshold or trace changes. The SDD Appendix A heading "Decision disposition and evidence gates" becomes "Activation gates" and keeps its activation rule; Appendix B's "Agent scoring boundary and build order" becomes "Agent scoring boundary" and keeps its design rules. A change that reports progress edits an issue or an implementation record, not the specification.
