# 0036. Track unfinished capped-release contracts

- Status: accepted
- Date: 2026-10-06
- Issue: #430
- Spec: SDD-CP-01 to SDD-UI-05; TDD-1.1.1 to TDD-7.1.5; unchanged behavior
- Pull requests: pending

## Context

PR #429 completed the documentation acceptance of #423. Its audit also identified incomplete contract behavior distinct from the concrete repairs in #424 through #428. Closing the documentation issue must not hide those discrepancies.

## Decision

Close #423 after its documentation change merges. Move remaining generic pending markers to #430. Preserve the narrower runtime repair markers. Do not mark behavior implemented because the documentation or a related issue is complete.

## Consequences

Every unfinished capped-release item keeps an open issue owner. Feedback, assignment, evolution, release gates and remaining cost coverage stay visible under #430. Repair workers use independent branches and one pull request each. Deployment issue #420 remains separate.
