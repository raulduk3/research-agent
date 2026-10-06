# 0040. Put kept papers first and expire failed attempts

- Status: accepted
- Date: 2026-10-06
- Issue: #443
- Spec: SDD-IS-01; SDD-RN-03; SDD-EV-02; SDD-EV-04; TDD-3.1.1; TDD-4.1.3; TDD-6.1.4
- Pull requests: #445

## Context

The island page repeated its paper collection as a long manual selection list and gave routine evolution diagnostics too much space. Skipped cycles consumed completed-run progress, idle heartbeats never retried due evolution, and failed attempts kept papers in storage indefinitely. The owner requested a simpler paper and run workflow with automatic evolution and a clean database, without added features.

## Decision

Show selected papers for future reference first, then other papers and runs. Prioritize kept references in the bounded island paper response so recent arrivals cannot displace them. Move the existing manual selection override to the individual paper page, using its assignment state so deselection and the island window cannot hide the control. Keep agent lineage and existing settings inside a collapsed section. Remove decision-history and skipped-cycle panels from the browser, while preserving generation records. Give page sections and paper entries room to read.

Only committed generations reset the completed-run threshold. Heartbeats evaluate due evolution even when no new reading starts. Retry skipped cycles after fifteen minutes to avoid repeated no-progress records.

Remove failed run attempts without submitted readings after 24 hours during startup and heartbeats. Remove dependent events, notes, search entries and feedback. Keep immutable spending receipts with their historical run and agent attribution, plus completed readings and live runs. Backfill agent attribution before cleanup so historical agent cost totals survive. Preserve failed attempts for at least a full day so cleanup cannot reset current-day retry or admission limits. Apply the existing unread-paper retention policy after cleanup.

This decision supersedes indefinite failed-run history preservation in 0033 and the browser decision-history disclosures in 0037. It does not change completed reading retention, human selection authority or the existing route families.

## Consequences

The visible workflow centers on papers, references kept by the agents and runs. Selection, lineage management and evolution settings reuse existing services. Database migration 11 permits event deletion for failed runs without submitted readings while continuing to prohibit event updates and receipt mutations. Failed traces remain available for one day. A paper with only expired failed attempts becomes available to the current reader cohort again. A merge does not deploy the application or clean a running database.
