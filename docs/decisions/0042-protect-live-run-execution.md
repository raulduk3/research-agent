# 0042. Protect live run execution

- Status: accepted
- Date: 2026-10-06
- Spec: SDD-RN-03; SDD-CT-01; TDD-4.2.9

## Context

Startup treated every queued or running row as abandoned. Execution read queued state before establishing ownership. Another process could fail a live run or issue duplicate paid requests.

## Decision

Hold one per-run nonblocking OS advisory lock across execution. Recovery uses the same lock and changes only abandoned running rows. Preserve queued rows and execute them on the next heartbeat. Keep persistent lock files beside the resolved SQLite database. Process exit releases the lock. Do not infer abandonment from a wall-clock expiry while a provider call remains live.

## Consequences

This contract applies to the single-host SQLite deployment and shared local volume. Stop older executors before upgrading because they do not participate in ownership. No database migration is needed. Preserve committed trace and receipts after a crash. Unknown provider charges from an interrupted request remain unknown; recovery does not repeat a request for that run. Independent-host execution and network filesystems remain outside the deployment contract.
