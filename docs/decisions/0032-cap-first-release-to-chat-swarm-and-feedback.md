# 0032. Cap the first release to a visible paper-reading swarm

- Status: accepted
- Date: 2026-09-24
- Spec: SDD-CP-01 to SDD-UI-05; TDD-1.1.1 to TDD-7.1.5

## Context

The project expanded into multiple applications and a large forecasting and qualification system. The useful product is smaller and more alive: ingest current papers, have islanded agents read them, expose every run, let feedback shape fast genome evolution, show costs everywhere and let people explore the cascade from island to paper to agent evidence.

Historical data on disk is not a launch dependency. It can remain available for a later explicit import, but the first release should not spend time qualifying it before current ingestion works.

## Decision

The active first-release specification is replaced with a capped swarm contract:

1. one cloud server and one current paper store,
2. research islands with their own pages,
3. explicit genomes for prompts, tools, reading strategy and lineage,
4. one-agent-one-paper runs as the atomic work unit,
5. durable traces for prompts, tool calls, notes, readings and costs,
6. rapid evolution from feedback, trace health, cost and run results,
7. cost receipts attached to every paid or scarce action, and
8. five visible pages: login, island, paper, run and chat.

The first release excludes the second front end, rating-only workflows, citation forecasting as the spine, prediction heads, Jev assessment, historical corpus qualification, OCR, public publishing, model training and distributed deployment.

The application source must stay below 30,000 nonblank, noncomment lines for the first release, excluding tests, generated files, lockfiles, specifications and vendored dependencies.

## Consequences

- Existing implementation may be reused only when it serves the capped swarm contract directly.
- The browser surface becomes small but inspectable rather than chat-only: island, paper and run pages expose the swarm cascade.
- Chat is casual and island-scoped; it is not the durable record for swarm data.
- Stored local data is ignored unless an operator imports it into the current store with receipts.
- Cost is first-class telemetry and appears beside activity instead of being an afterthought.
- Forecasting can return later as a swarm behavior or product feature, but the first-release spine is agent reading and feedback evolution over current papers.
