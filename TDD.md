# Architecture and executable contracts

[SDD.md](SDD.md) is the current behavior specification. Its feature IDs connect intended behavior, implementation owners, tests and exact gaps. This document identifies the shared architecture. It does not duplicate requirements or require historical decision records.

## Runtime and ownership

The active application has one Python beta server, a SQLite store and one swarm browser. The retained Python platform and `front-end/` are historical maintenance code, outside the active release.

| Boundary | Owner | Responsibility |
| --- | --- | --- |
| HTTP and authorization | [app.py](src/research_agent/beta/app.py), [auth.py](src/research_agent/beta/auth.py) | Parse external input, authenticate signed sessions and enforce island mutation scope. |
| Lifecycle | [service.py](src/research_agent/beta/service.py) | Prepare the configured store, schedule work, run maintenance and advance evolution. |
| Paper intake | [ingest.py](src/research_agent/beta/ingest.py), [papers.py](src/research_agent/beta/papers.py), [text.py](src/research_agent/beta/text.py), [islands.py](src/research_agent/beta/islands.py) | Normalize papers, persist source cursors, fetch available text and assign islands. |
| Genomes and evolution | [spec.py](src/research_agent/beta/spec.py), [evolution.py](src/research_agent/beta/evolution.py) | Validate genomes, retain revisions and snapshots, and commit generation decisions. |
| Agent execution | [runs.py](src/research_agent/beta/runs.py), [models.py](src/research_agent/beta/models.py) | Admit single-paper runs, enforce tool limits, validate submissions and retain event traces. |
| Accounting | [budget.py](src/research_agent/beta/budget.py), [costs.py](src/research_agent/beta/costs.py) | Admit paid work, reserve estimates and retain immutable settled or unsettled receipts. |
| Feedback and chat | [likes.py](src/research_agent/beta/likes.py), [chat.py](src/research_agent/beta/chat.py) | Persist validated island-scoped feedback and answer from stored records without durable chat transcripts. |
| Read projections | [projections.py](src/research_agent/beta/projections.py) | Assemble bounded object views with costs and unavailable-group markers. |
| Browser | [App.tsx](apps/swarm-web/src/App.tsx), [browser API reference](apps/swarm-web/API.md) | Render the public storm, login, island, paper, run and chat page families. |

SQLite owns papers, assignments, genome revisions, lineage, run events, readings, likes and receipts. The browser owns disposable chat turns. A run stores its genome and prompt snapshot, so later genome edits cannot rewrite its record. Failed attempts without readings expire after 24 hours; completed readings and cost receipts remain.

Paid receipts commit before later trace, answer or generation work. A later failure can remove partial work without erasing incurred charges. Run events and receipts have database immutability guards. Missing projection data must remain distinguishable from empty data and from zero cost. SDD.md records where those guarantees remain incomplete.

## Contract ownership

The active browser's [Zod contracts](apps/swarm-web/src/api/contracts.ts) own HTTP payload shapes and runtime validation. [types.ts](apps/swarm-web/src/api/types.ts) derives TypeScript types with `z.infer`; interfaces do not independently redefine wire shapes. [client.ts](apps/swarm-web/src/api/client.ts) parses requests and responses at the transport boundary before a page consumes them. A malformed successful response is a transport failure, not page data.

Python keeps its existing HTTP and domain validators. Zod does not enforce server mutations, storage invariants, accounting or authorization. Python tests exercise those owners. [Contract tests](apps/swarm-web/src/api/contracts.test.ts) validate actual API responses produced by [the Python response samples](tests/beta/browser_contract_samples.py) against the same browser schemas. A schema proves shape. Behavior assertions prove effects and refusals, including that rejected work changes no stored state.

The JSON schemas under `docs/contracts/api-v1/` belong to the historical front end. They remain maintained for that consumer. New active-browser contracts belong in Zod. If another consumer needs JSON Schema, derive it from the executable contract instead of maintaining another active schema definition.

## Change and verification

For a behavior change, update the feature in SDD.md and add or change a behavior test that fails for the prohibited alternative. Implement the change through the existing owner, then verify the outcome and update the exact gap. Contract-shape changes update Zod and its inferred consumers in the same change. A passing schema test alone does not close a behavior gap.

Run `bin/check --since develop`. The aggregate check runs current-spec validation, Python lint, formatting, strict typing and tests, plus the browser gates. Run `python bin/check-front-end --app apps/swarm-web` for the browser's locked install, typecheck, production build, lint and tests. The checker's negative cases verify that planted specification, type and test errors are caught.

Start with SDD.md and the feature's linked tests. Consult [beta operations](deploy/beta/README.md) for runtime configuration and [the browser API reference](apps/swarm-web/API.md) for calls and display behavior. Git history and retained decision/evidence files are optional investigation material. Neither a new decision record nor an amendment-ledger entry is required for a behavior change; the pull request records the change and its verification.
