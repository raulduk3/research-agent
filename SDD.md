# Current product specification

This document is the authority for current behavior, constraints and remaining gaps. Start here, then follow the feature's code and tests. [TDD.md](TDD.md) states the detailed fulfillment contracts: data and interfaces, state and transaction boundaries, failure handling, verification and honest per-contract status. Historical decisions and evidence are optional reference, not prerequisites.

The first release is one cloud-hosted paper-reading swarm: current ingestion, island pages, paper drill-down, agent-run traces, rapid genome evolution, feedback and casual chat. The public storm entry opens into login, island, paper, run and chat page families. Chat history is disposable. Papers, assignments, genomes and lineage, completed readings, retained runs, feedback and cost receipts are durable. Failed attempts without readings expire after the retention window specified below.

The application source ceiling is below 30,000 nonblank, noncomment lines. Generated files, lockfiles, tests, specifications and vendored dependencies are excluded. Historical platform components, two separate front ends, rating-only workflows, historical citation forecasting, prediction-head qualification, Jev assessment, OCR, public publishing, model training and distributed clusters are outside the first release. Stale local data requires an explicit operator import.

Each feature has a stable requirement ID and its intended behavior, implementation owners, behavior tests and exact gap. `must` and `must not` are normative. A cited file establishes ownership, not complete implementation. `Gap: None.` means the entire feature has verification; every other gap stays open. Tests must exercise the owner and reject a concrete prohibited alternative. Feature IDs, fulfillment links, implementation/test references and statuses are checked by `bin/spec-check`. A feature remains pending when any linked fulfillment contract is pending.

A genome is a versioned agent configuration. An island owns its queue, genomes and reading activity. A run reads one paper under one genome. A reading contains summary, claims, evidence, objections, related papers and idea seeds. A cost receipt records paid or scarce work and its attribution. The storm is the current ingested paper stream.

## CP-01 Release manifest gate

The first release must ship one cloud-hosted swarm application with current ingestion, islands, genomes, agent runs, feedback evolution, cost receipts and the five visible pages.
<!-- id: SDD-CP-01 | tdd: TDD-1.1.1, TDD-1.2.1, TDD-1.2.2 | status: pending -->

- Behavior: When a release build is assembled, the build manifest admits only components serving ingestion, islands, genomes, runs, evolution, cost or one of the five visible pages. The manifest lists each component with exactly one admitted purpose. If a component has an unrelated purpose, packaging fails before assembly.

- Contracts: [TDD-1.1.1](TDD.md#tdd-1.1.1), [TDD-1.2.1](TDD.md#tdd-1.2.1), [TDD-1.2.2](TDD.md#tdd-1.2.2).

- Code: [deploy/beta/Dockerfile](deploy/beta/Dockerfile).

- Tests: [tests/beta/test_deploy.py](tests/beta/test_deploy.py).

- Gap: The image-copy and pinned-dependency checks exist. Packaging has no component-purpose manifest or test planting an unrelated declared component and observing refusal. The current image recipe does not prove the live deployment uses it.

## CP-02 Source line budget

The first-release application source must stay below 30,000 nonblank, noncomment lines.
<!-- id: SDD-CP-02 | tdd: TDD-1.1.2, TDD-1.2.3, TDD-1.2.4 | status: pending -->

- Behavior: When the repository check runs, the check counts application source files and excludes tests, generated files, lockfiles, specifications and vendored dependencies. The check prints the counted total and the configured ceiling. If the counted total reaches the ceiling, the check fails and names the paths contributing to the excess.

- Contracts: [TDD-1.1.2](TDD.md#tdd-1.1.2), [TDD-1.2.3](TDD.md#tdd-1.2.3), [TDD-1.2.4](TDD.md#tdd-1.2.4).

- Code: [bin/check](bin/check).

- Tests: None.

- Gap: Application-only counting, the active-versus-historical counting boundary, ceiling enforcement and negative cases for counted excess and excluded material are absent.

## CP-03 Current-store admission

The runtime must ignore stale local data unless an operator imports it into the current store.
<!-- id: SDD-CP-03 | tdd: TDD-1.1.3, TDD-1.2.5, TDD-1.2.6 | status: pending -->

- Behavior: When the server starts or an ingestion pass runs, the runtime reads current store records and operator-imported records with receipts, not arbitrary files on disk. Each visible paper has a current ingestion receipt or import receipt. A record without current ingestion or import provenance is hidden from pages, chat, assignment and evolution.

- Contracts: [TDD-1.1.3](TDD.md#tdd-1.1.3), [TDD-1.2.5](TDD.md#tdd-1.2.5), [TDD-1.2.6](TDD.md#tdd-1.2.6).

- Code: [src/research_agent/beta/service.py](src/research_agent/beta/service.py) (`Swarm.prepare`), [src/research_agent/beta/spec.py](src/research_agent/beta/spec.py) (`ensure_seed`).

- Tests: [tests/beta/test_service.py](tests/beta/test_service.py), [tests/beta/test_spec.py](tests/beta/test_spec.py).

- Gap: Startup uses the configured store and does not scan historical directories. General import-provenance admission and the test planting stale files without import receipts are absent.

## CP-04 Prohibited component registry

The first release must not ship rating-only workflows, historical citation forecasting, prediction-head qualification, Jev assessment, OCR, model training, public publishing or distributed clusters.
<!-- id: SDD-CP-04 | tdd: TDD-1.1.4, TDD-1.2.7, TDD-1.2.8 | status: pending -->

- Behavior: When a route, job, worker or dependency is registered, registration is refused when the component exists only for a prohibited workflow. The route and job registries contain no prohibited component names. If a prohibited component is registered, startup fails and names that registration.

- Contracts: [TDD-1.1.4](TDD.md#tdd-1.1.4), [TDD-1.2.7](TDD.md#tdd-1.2.7), [TDD-1.2.8](TDD.md#tdd-1.2.8).

- Code: [deploy/beta/Dockerfile](deploy/beta/Dockerfile).

- Tests: [tests/beta/test_deploy.py](tests/beta/test_deploy.py).

- Gap: The beta image and textual import checks exclude the historical package. A purpose-aware startup registry and prohibited-registration negative case are absent; source-directory exclusion cannot reject a prohibited workflow added inside beta.

## IG-01 Current ingestion pass

Ingestion must collect current paper metadata and available text into one server-side store.
<!-- id: SDD-IG-01 | tdd: TDD-2.1.1, TDD-2.2.1, TDD-2.2.2, TDD-2.2.3 | status: pending -->

- Behavior: When an ingestion pass starts, the pass fetches configured current sources, normalizes metadata, stores source links, stores text when available and records text failures. Each paper record has source, fetch time, metadata, text status and immutable source links. If a source fails, its failure is recorded while successful source records remain committed.

- Contracts: [TDD-2.1.1](TDD.md#tdd-2.1.1), [TDD-2.2.1](TDD.md#tdd-2.2.1), [TDD-2.2.2](TDD.md#tdd-2.2.2), [TDD-2.2.3](TDD.md#tdd-2.2.3).

- Code: [src/research_agent/beta/ingest.py](src/research_agent/beta/ingest.py) (`run_ingestion_pass`), [src/research_agent/beta/ingest.py](src/research_agent/beta/ingest.py) (`parse_arxiv_feed`), [src/research_agent/beta/papers.py](src/research_agent/beta/papers.py) (`upsert_paper`).

- Tests: [tests/beta/test_ingest.py](tests/beta/test_ingest.py).

- Gap: A newer paper version replaces source metadata, abstract/PDF URLs and passages on the same identity. Immutable per-version source-link history and its negative case are absent. Identity deduplication does not establish provenance history.

## IG-02 Resumable ingestion cursor

Ingestion must be resumable without duplicating paper records.
<!-- id: SDD-IG-02 | tdd: TDD-2.1.2, TDD-2.2.4, TDD-2.2.5, TDD-2.2.6 | status: implemented -->

- Behavior: When an ingestion pass stops and later restarts, the restarted pass resumes from stored source cursors and upserts by canonical paper identity. Re-running a completed pass leaves one paper record per canonical paper identity. An ambiguous identity is quarantined and excluded from island assignment.

- Contracts: [TDD-2.1.2](TDD.md#tdd-2.1.2), [TDD-2.2.4](TDD.md#tdd-2.2.4), [TDD-2.2.5](TDD.md#tdd-2.2.5), [TDD-2.2.6](TDD.md#tdd-2.2.6).

- Code: [src/research_agent/beta/ingest.py](src/research_agent/beta/ingest.py) (`run_ingestion_pass`), [src/research_agent/beta/ingest.py](src/research_agent/beta/ingest.py) (`arxiv_fetcher`).

- Tests: [tests/beta/test_ingest.py](tests/beta/test_ingest.py).

- Gap: None.

## IG-03 Paper projection rollup

Every paper record must roll up its island assignments, readings, agent runs, feedback and cost receipts.
<!-- id: SDD-IG-03 | tdd: TDD-2.1.3, TDD-2.2.7, TDD-2.2.8 | status: pending -->

- Behavior: When the paper page or chat requests a paper, the server assembles the paper record from stored paper, assignment, run, reading, feedback and cost tables. The paper page shows counts and links for each rollup group. If a projection group fails, the page marks it unavailable instead of presenting a partial group as complete.

- Contracts: [TDD-2.1.3](TDD.md#tdd-2.1.3), [TDD-2.2.7](TDD.md#tdd-2.2.7), [TDD-2.2.8](TDD.md#tdd-2.2.8).

- Code: [src/research_agent/beta/projections.py](src/research_agent/beta/projections.py) (`build_paper_projection`), [src/research_agent/beta/projections.py](src/research_agent/beta/projections.py) (`Groups.rows`).

- Tests: [tests/beta/test_api.py](tests/beta/test_api.py).

- Gap: The grouped response reports failures in `unavailable`, and readings distinguish unavailable from empty. Assignment and run sections can still present failed groups as empty. Complete per-group browser refusal coverage is absent.

## IG-04 Text failure visibility

A paper must remain inspectable when text extraction fails.
<!-- id: SDD-IG-04 | tdd: TDD-2.1.4, TDD-2.2.9, TDD-2.2.10 | status: pending -->

- Behavior: When text extraction fails for an ingested paper, the paper record keeps metadata, source links, text failure category and assignment eligibility. The paper page shows the paper with text status failed and no fabricated text. When extraction fails, agents receive only metadata and available source links.

- Contracts: [TDD-2.1.4](TDD.md#tdd-2.1.4), [TDD-2.2.9](TDD.md#tdd-2.2.9), [TDD-2.2.10](TDD.md#tdd-2.2.10).

- Code: [src/research_agent/beta/text.py](src/research_agent/beta/text.py), [src/research_agent/beta/text.py](src/research_agent/beta/text.py) (`fetch_full_texts`).

- Tests: [tests/beta/test_text.py](tests/beta/test_text.py).

- Gap: HTML failures preserve the abstract and `text_failure`, but retain `text_status=abstract_only`; PaperPage displays that status without the extraction reason. The specified failed status, visible reason and browser failure-state acceptance case are absent.

## IS-01 Island projection

Each island must have its own page with queue, papers, genomes, runs, readings, feedback totals and cost totals.
<!-- id: SDD-IS-01 | tdd: TDD-3.1.1, TDD-3.2.1, TDD-3.2.2, TDD-3.2.12, TDD-3.2.13, TDD-3.2.14 | status: pending -->

- Behavior: When a logged-in visitor opens an island page, the server returns the island projection with selected papers for future reference first, other papers and current runs next, and collapsed genome settings and evolution controls after the output. Manual paper selection belongs on the individual paper page. Paper output and current runs precede configuration, with section counts and drill-down links. If a section fails, the page keeps it visible as unavailable.

- Contracts: [TDD-3.1.1](TDD.md#tdd-3.1.1), [TDD-3.2.1](TDD.md#tdd-3.2.1), [TDD-3.2.2](TDD.md#tdd-3.2.2), [TDD-3.2.12](TDD.md#tdd-3.2.12), [TDD-3.2.13](TDD.md#tdd-3.2.13), [TDD-3.2.14](TDD.md#tdd-3.2.14).

- Code: [src/research_agent/beta/projections.py](src/research_agent/beta/projections.py) (`build_island_projection`), [apps/swarm-web/src/pages/Island.tsx](apps/swarm-web/src/pages/Island.tsx) (`IslandPage`), [apps/swarm-web/src/components/EvolutionSwitches.tsx](apps/swarm-web/src/components/EvolutionSwitches.tsx) (`EvolutionSwitches`).

- Tests: [apps/swarm-web/src/App.test.tsx](apps/swarm-web/src/App.test.tsx), [tests/beta/test_api.py](tests/beta/test_api.py).

- Gap: The response contains readings, but the browser has no separate reading section. Queue is a count, not a list. Island feedback totals are absent. Failed evolution, queue and readings groups lack complete local unavailable displays. No projection-plus-browser test seeds all required sections and fails each section independently.

## IS-02 Island login session

Login must bind a visitor to one island without creating durable chat-session records.
<!-- id: SDD-IS-02 | tdd: TDD-3.1.2, TDD-3.2.3, TDD-3.2.4 | status: implemented -->

- Behavior: When a visitor selects or enters an island login, the server issues an island-scoped browser session and stores no chat transcript for that login. Requests carry island scope, and durable storage has no chat transcript row for the login. If login is invalid, it is refused before any island data is shown.

- Contracts: [TDD-3.1.2](TDD.md#tdd-3.1.2), [TDD-3.2.3](TDD.md#tdd-3.2.3), [TDD-3.2.4](TDD.md#tdd-3.2.4).

- Code: [src/research_agent/beta/auth.py](src/research_agent/beta/auth.py) (`open_island_session`), [src/research_agent/beta/auth.py](src/research_agent/beta/auth.py) (`read_session`).

- Tests: [tests/beta/test_api.py](tests/beta/test_api.py).

- Gap: None.

## IS-03 Genome validation

Each genome must declare its prompt, island, model settings, allowed tools, reading strategy, scoring preferences and lineage metadata.
<!-- id: SDD-IS-03 | tdd: TDD-3.1.3, TDD-3.2.5, TDD-3.2.6, TDD-3.2.7, TDD-3.2.15 | status: pending -->

- Behavior: When a genome is created, imported or mutated, the genome validator requires every declared field and records parent references for non-founder genomes. Exact repeated instructions are removed before storing agent content and assembling provider prompts. Existing agents, including archived agents, receive the same normalization through a versioned upgrade; historical revisions and completed runs remain immutable. The genome page and run records can display the exact genome version used. An invalid genome is rejected and cannot start runs.

- Contracts: [TDD-3.1.3](TDD.md#tdd-3.1.3), [TDD-3.2.5](TDD.md#tdd-3.2.5), [TDD-3.2.6](TDD.md#tdd-3.2.6), [TDD-3.2.7](TDD.md#tdd-3.2.7), [TDD-3.2.15](TDD.md#tdd-3.2.15).

- Code: [src/research_agent/beta/spec.py](src/research_agent/beta/spec.py) (`validate_genome`), [src/research_agent/beta/spec.py](src/research_agent/beta/spec.py) (`apply_spec`), [apps/swarm-web/src/components/GenomeCard.tsx](apps/swarm-web/src/components/GenomeCard.tsx) (`GenomeCard`).

- Tests: [tests/beta/test_spec.py](tests/beta/test_spec.py), [apps/swarm-web/src/components/GenomeCard.test.tsx](apps/swarm-web/src/components/GenomeCard.test.tsx).

- Gap: Scoring preferences are validated but do not affect evolutionary fitness. Missing-parent and malformed-ancestry rejection cases are incomplete. Field validation and immutable revisions do not establish those semantics.

## IS-04 Paper assignment

A paper assignment must choose one or more islands from metadata, current focus, feedback and genome demand.
<!-- id: SDD-IS-04 | tdd: TDD-3.1.4, TDD-3.2.8, TDD-3.2.9 | status: pending -->

- Behavior: When a paper becomes assignment-eligible, the assignment step stores island ids and reason codes, using a general island when evidence is sparse. The paper and island pages show assignment reason codes. If assignment evidence is insufficient, the paper goes to General with `assignment_uncertain`.

- Contracts: [TDD-3.1.4](TDD.md#tdd-3.1.4), [TDD-3.2.8](TDD.md#tdd-3.2.8), [TDD-3.2.9](TDD.md#tdd-3.2.9).

- Code: [src/research_agent/beta/islands.py](src/research_agent/beta/islands.py) (`assign_paper`), [src/research_agent/beta/islands.py](src/research_agent/beta/islands.py) (`score_islands`).

- Tests: [tests/beta/test_ingest.py](tests/beta/test_ingest.py).

- Gap: Assignment reads categories, focus keywords and archive state. It does not read persisted feedback or active-genome demand. Tests changing those inputs and observing assignment are absent.

## IS-05 Cross-island genome transfer

Cross-island transfer must copy behavior through genome lineage rather than shared mutable prompts.
<!-- id: SDD-IS-05 | tdd: TDD-3.1.5, TDD-3.2.10, TDD-3.2.11 | status: pending -->

- Behavior: When evolution borrows behavior from another island, the system creates a child genome that cites the source island, source genome and copied field set. Breeding combines the actual parents' research-method instructions and source provenance; mutation retains inherited methods. Shared instructions occur once, and island defaults cannot replace inherited methods. The child genome lineage shows the cross-island transfer. A failed transfer leaves all existing mutable prompts unchanged.

- Contracts: [TDD-3.1.5](TDD.md#tdd-3.1.5), [TDD-3.2.10](TDD.md#tdd-3.2.10), [TDD-3.2.11](TDD.md#tdd-3.2.11).

- Code: [src/research_agent/beta/evolution.py](src/research_agent/beta/evolution.py) (`mate_genomes`), [src/research_agent/beta/evolution.py](src/research_agent/beta/evolution.py) (`maybe_run_evolution`).

- Tests: [tests/beta/test_evolution.py](tests/beta/test_evolution.py).

- Gap: Lineage records parent IDs, primary-parent version and a mating decision naming the other island. Complete copied-field sets and explicit source versions for every parent are absent, as is reconstruction coverage.

## RN-01 One-paper run scheduler

The atomic work unit must be one agent run reading one paper under one genome.
<!-- id: SDD-RN-01 | tdd: TDD-4.1.1, TDD-4.2.1, TDD-4.2.2, TDD-4.2.3 | status: pending -->

- Behavior: When the scheduler creates reading work, the scheduler creates a run with one paper id, one island id, one genome version and one run seed. Every run page names exactly one paper and one genome. Requests with missing or multiple papers are refused before model calls.

- Contracts: [TDD-4.1.1](TDD.md#tdd-4.1.1), [TDD-4.2.1](TDD.md#tdd-4.2.1), [TDD-4.2.2](TDD.md#tdd-4.2.2), [TDD-4.2.3](TDD.md#tdd-4.2.3).

- Code: [src/research_agent/beta/runs.py](src/research_agent/beta/runs.py) (`create_run`).

- Tests: [tests/beta/test_runs.py](tests/beta/test_runs.py).

- Gap: The single-paper row and unknown-paper, wrong-island and absent-provider refusals are verified. Missing-paper and multi-paper public request cases with no provider calls or queued rows are unproven.

## RN-02 Harness tool policy

The harness must expose a bounded tool set for paper text, related papers, note capture, feedback context, cost state and final submission.
<!-- id: SDD-RN-02 | tdd: TDD-4.1.2, TDD-4.2.4, TDD-4.2.5, TDD-4.2.6 | status: pending -->

- Behavior: When an agent run starts, the harness builds allowed tool schemas from the genome and refuses calls outside that set. The run page lists allowed tools and each attempted tool call. An undeclared tool call is refused and recorded without a side effect.

- Contracts: [TDD-4.1.2](TDD.md#tdd-4.1.2), [TDD-4.2.4](TDD.md#tdd-4.2.4), [TDD-4.2.5](TDD.md#tdd-4.2.5), [TDD-4.2.6](TDD.md#tdd-4.2.6).

- Code: [src/research_agent/beta/runs.py](src/research_agent/beta/runs.py) (`dispatch_tool_call`), [src/research_agent/beta/runs.py](src/research_agent/beta/runs.py) (`_run_tool`).

- Tests: [tests/beta/test_runs.py](tests/beta/test_runs.py).

- Gap: `feedback_context` returns selected papers and recent same-island readings, not persisted feedback signals or notes. No test changes feedback and checks the tool result. Malformed `submit_reading` JSON produces retry guidance without a tool-call event; universally logged refused attempts are not established.

## RN-03 Run event trace

Every agent run must store its prompt, model settings, tool trace, notes, final reading, status and cost receipts.
<!-- id: SDD-RN-03 | tdd: TDD-4.1.3, TDD-4.2.7, TDD-4.2.8, TDD-4.2.9, TDD-4.2.10, TDD-4.2.22 | status: pending -->

- Behavior: When a run starts, calls a tool, calls a model, submits or fails, the harness appends immutable run events and links each paid or scarce action to a cost receipt. Startup and heartbeats remove failed attempts without submitted readings after 24 hours, including their events and notes, while preserving cost receipts and completed readings. The run page can reconstruct retained runs from stored events. Expired failed attempts disappear without reducing recorded spending. If a run fails, its failed status, last committed event and cost total remain available during its 24-hour retention window.

- Contracts: [TDD-4.1.3](TDD.md#tdd-4.1.3), [TDD-4.2.7](TDD.md#tdd-4.2.7), [TDD-4.2.8](TDD.md#tdd-4.2.8), [TDD-4.2.9](TDD.md#tdd-4.2.9), [TDD-4.2.10](TDD.md#tdd-4.2.10), [TDD-4.2.22](TDD.md#tdd-4.2.22).

- Code: [src/research_agent/beta/runs.py](src/research_agent/beta/runs.py) (`append_run_event`), [src/research_agent/beta/models.py](src/research_agent/beta/models.py) (`ChatCompletionsClient.complete`), [src/research_agent/beta/runs.py](src/research_agent/beta/runs.py) (`sweep_interrupted_runs`), [src/research_agent/beta/runs.py](src/research_agent/beta/runs.py) (`dispatch_tool_call`), [src/research_agent/beta/config.py](src/research_agent/beta/config.py) (`_provider_timeout`).

- Tests: [tests/beta/test_runs.py](tests/beta/test_runs.py), [tests/beta/test_service.py](tests/beta/test_service.py).

- Gap: Startup preserves queued runs and recovers abandoned running work only after acquiring the same persistent OS lock used by executors. Live-owner protection, contested execution and process-death recovery are verified under TDD-4.2.9. Ordinary tools and reading submission do not all create linked receipts. Malformed submission arguments omit a tool-call event. Provider receipts and 24-hour failed-run retention are verified, not complete scarce-action coverage.

## RN-04 Reading submission contract

A reading must contain summary, claims, evidence references, objections, related papers and idea seeds.
<!-- id: SDD-RN-04 | tdd: TDD-4.1.4, TDD-4.2.11, TDD-4.2.12, TDD-4.2.13 | status: implemented -->

- Behavior: When an agent submits a final reading, the submission validator requires the bounded reading fields and source references where claims depend on paper text. The paper page renders each field under the submitting run. An invalid reading is rejected and the run remains incomplete.

- Contracts: [TDD-4.1.4](TDD.md#tdd-4.1.4), [TDD-4.2.11](TDD.md#tdd-4.2.11), [TDD-4.2.12](TDD.md#tdd-4.2.12), [TDD-4.2.13](TDD.md#tdd-4.2.13).

- Code: [src/research_agent/beta/runs.py](src/research_agent/beta/runs.py) (`validate_reading_submission`), [src/research_agent/beta/runs.py](src/research_agent/beta/runs.py) (`locate_quote`), [src/research_agent/beta/runs.py](src/research_agent/beta/runs.py) (`dispatch_tool_call`).

- Tests: [tests/beta/test_runs.py](tests/beta/test_runs.py).

- Gap: None.

## RN-05 Run page projection

The run page must show the cascade from run to tool calls to atomic evidence.
<!-- id: SDD-RN-05 | tdd: TDD-4.1.5, TDD-4.2.14, TDD-4.2.15, TDD-4.2.16, TDD-4.2.19, TDD-4.2.20, TDD-4.2.21 | status: pending -->

- Behavior: When a visitor opens a run page, the page leads with the submitted reading for a completed run or current status when no reading exists, followed by replay, genome, costs and notes in event order. The reading appears before diagnostics, and each final claim links to its cited evidence or is marked uncited. If an artifact is missing, the page reports its absence rather than substituting agent prose.

- Contracts: [TDD-4.1.5](TDD.md#tdd-4.1.5), [TDD-4.2.14](TDD.md#tdd-4.2.14), [TDD-4.2.15](TDD.md#tdd-4.2.15), [TDD-4.2.16](TDD.md#tdd-4.2.16), [TDD-4.2.19](TDD.md#tdd-4.2.19), [TDD-4.2.20](TDD.md#tdd-4.2.20), [TDD-4.2.21](TDD.md#tdd-4.2.21).

- Code: [src/research_agent/beta/projections.py](src/research_agent/beta/projections.py) (`build_run_projection`), [apps/swarm-web/src/pages/Run.tsx](apps/swarm-web/src/pages/Run.tsx) (`RunBody`), [apps/swarm-web/src/pages/Run.tsx](apps/swarm-web/src/pages/Run.tsx) (`RunPage`), [apps/swarm-web/src/components/ReadingView.tsx](apps/swarm-web/src/components/ReadingView.tsx) (`ReadingView`).

- Tests: [apps/swarm-web/src/pages/Run.test.tsx](apps/swarm-web/src/pages/Run.test.tsx), [tests/beta/test_runs.py](tests/beta/test_runs.py).

- Gap: ReadingView displays quotations and verification labels but no per-claim locator or evidence navigation anchor. Claims without quotes say "no quote given", not the complete uncited/artifact state. Absent paper, genome, trace and grouped-query failures lack complete projection/browser negative cases. Existing replay locators and links to a run do not connect a final claim to its atomic evidence.

## RN-06 Trace authority

The harness must record run data independently of the agent's self-report.
<!-- id: SDD-RN-06 | tdd: TDD-4.1.6, TDD-4.2.17, TDD-4.2.18 | status: pending -->

- Behavior: When an agent describes its own behavior, the system displays conduct, tools, timing and costs from harness events only. A mismatch between agent prose and trace favors the trace on the run page. If authoritative trace data is missing, the disputed field is marked `trace_missing` rather than trusting the agent.

- Contracts: [TDD-4.1.6](TDD.md#tdd-4.1.6), [TDD-4.2.17](TDD.md#tdd-4.2.17), [TDD-4.2.18](TDD.md#tdd-4.2.18).

- Code: [src/research_agent/beta/projections.py](src/research_agent/beta/projections.py) (`trace_authority_view`).

- Tests: [tests/beta/test_runs.py](tests/beta/test_runs.py).

- Gap: Missing trace returns empty lists or null timing rather than `trace_missing`. The regression against invented tool activity does not prove the missing-authority state.

## CT-01 Cost receipt writer

Every paid or scarce action must create a cost receipt.
<!-- id: SDD-CT-01 | tdd: TDD-5.1.1, TDD-5.2.1, TDD-5.2.2, TDD-5.2.3, TDD-5.2.4 | status: pending -->

- Behavior: When the system performs ingestion, model inference, tool work, reading, evolution or chat retrieval, the actor records owner id, parent id, unit type, quantity, cost amount when known and estimation flag when estimated. Each page can show cost totals from receipts rather than recomputing hidden counters. If accounting fails, the parent action is marked `cost_unsettled` and excluded from settled totals.

- Contracts: [TDD-5.1.1](TDD.md#tdd-5.1.1), [TDD-5.2.1](TDD.md#tdd-5.2.1), [TDD-5.2.2](TDD.md#tdd-5.2.2), [TDD-5.2.3](TDD.md#tdd-5.2.3), [TDD-5.2.4](TDD.md#tdd-5.2.4).

- Code: [src/research_agent/beta/costs.py](src/research_agent/beta/costs.py) (`record_cost_receipt`), [src/research_agent/beta/budget.py](src/research_agent/beta/budget.py) (`estimate_run_micros`), [src/research_agent/beta/runs.py](src/research_agent/beta/runs.py) (`_drive`), [src/research_agent/beta/runs.py](src/research_agent/beta/runs.py) (`dispatch_tool_call`).

- Tests: [tests/beta/test_costs.py](tests/beta/test_costs.py), [tests/beta/test_budget.py](tests/beta/test_budget.py), [tests/beta/test_runs.py](tests/beta/test_runs.py).

- Gap: The admitted ledger actions are ingest, model_call, chat_retrieval, chat_answer and evolution. General tool and reading receipt actions are absent. Failed cited-paper fetch, ordinary tool dispatch and final submission do not each have complete dedicated receipt coverage. Parent-wide `cost_unsettled` on accounting failure has no uniform representation. Provider-attempt rollback tests do not prove every scarce action. HTML request receipts are covered by text tests, but complete caller accounting is not established.

## CT-02 Cost-aware projections

Paper, island, genome, run, evolution and chat views must show cost beside activity.
<!-- id: SDD-CT-02 | tdd: TDD-5.1.2, TDD-5.2.5, TDD-5.2.6, TDD-5.2.7 | status: pending -->

- Behavior: When a view renders an activity count or generated answer, the view includes settled cost, unsettled cost count and cost-per-useful-feedback where feedback exists. Cost appears beside papers read, runs, readings, genome lineage and chat answers. If cost cannot be read, the view marks it unavailable instead of showing zero.

- Contracts: [TDD-5.1.2](TDD.md#tdd-5.1.2), [TDD-5.2.5](TDD.md#tdd-5.2.5), [TDD-5.2.6](TDD.md#tdd-5.2.6), [TDD-5.2.7](TDD.md#tdd-5.2.7).

- Code: [src/research_agent/beta/costs.py](src/research_agent/beta/costs.py) (`attach_cost_summary`), [src/research_agent/beta/projections.py](src/research_agent/beta/projections.py) (`build_run_projection`), [src/research_agent/beta/projections.py](src/research_agent/beta/projections.py) (`build_agent_projection`).

- Tests: [tests/beta/test_costs.py](tests/beta/test_costs.py), [tests/beta/test_api.py](tests/beta/test_api.py).

- Gap: Run top-level/nested costs, run briefs, island paper rows, per-island breakdowns and agent lists can combine settlement states. Agent detail has settled totals but no unavailable-query guard. Cost per useful feedback and generation settlement projections are absent. Chat exposes an answer amount and receipt IDs without an answer settlement summary. Mixed-settlement and unavailable browser cases are incomplete.

## CT-03 Evolution cost policy

Evolution must use cost only as a tie-breaker unless a genome exceeds a configured budget.
<!-- id: SDD-CT-03 | tdd: TDD-5.1.3, TDD-5.2.8, TDD-5.2.9, TDD-5.2.10 | status: pending -->

- Behavior: When evolution compares genome candidates, the selector ranks usefulness first, applies cost between candidates with equal usefulness band and rejects candidates over budget. The evolution record shows usefulness, cost and budget decisions separately. If a comparison fails, the cycle makes no survivor change for that comparison.

- Contracts: [TDD-5.1.3](TDD.md#tdd-5.1.3), [TDD-5.2.8](TDD.md#tdd-5.2.8), [TDD-5.2.9](TDD.md#tdd-5.2.9), [TDD-5.2.10](TDD.md#tdd-5.2.10).

- Code: [src/research_agent/beta/evolution.py](src/research_agent/beta/evolution.py) (`maybe_run_evolution`), [src/research_agent/beta/budget.py](src/research_agent/beta/budget.py) (`admit_paid`).

- Tests: [tests/beta/test_evolution.py](tests/beta/test_evolution.py).

- Gap: Selection uses likes, completed-run counts and IDs. It has no usefulness bands, cost tie-break, per-genome budget exclusion or separately recorded comparison measures. Paid-proposal caps control requesting a proposal, not candidate spending. Useful-expensive versus cheap-poor and over-budget-candidate tests are absent.

## CT-04 Cost rollup ledger

Cost receipts must roll up through parent links without double counting.
<!-- id: SDD-CT-04 | tdd: TDD-5.1.4, TDD-5.2.11, TDD-5.2.12, TDD-5.2.13 | status: pending -->

- Behavior: When a cost total is requested, the cost service sums each receipt once through stored parent links and excludes child totals already represented by parent receipts. Paper, island and genome totals equal the receipt ledger for their scope. If reconciliation fails, the total is marked inconsistent and is not displayed as settled.

- Contracts: [TDD-5.1.4](TDD.md#tdd-5.1.4), [TDD-5.2.11](TDD.md#tdd-5.2.11), [TDD-5.2.12](TDD.md#tdd-5.2.12), [TDD-5.2.13](TDD.md#tdd-5.2.13).

- Code: [src/research_agent/beta/costs.py](src/research_agent/beta/costs.py) (`sum_cost_scope`), [src/research_agent/beta/budget.py](src/research_agent/beta/budget.py) (`budget_state`).

- Tests: [tests/beta/test_costs.py](tests/beta/test_costs.py), [tests/beta/test_budget.py](tests/beta/test_budget.py).

- Gap: Totals filter flat run/paper/island scope columns instead of traversing parent links. The writer does not validate parent existence or prevent receipt parents. No consistency state or nested-parent double-counting negative case exists. Generic genome/version scopes remain absent, though durable genome attribution preserves failed-run spend. An evolution receipt can survive without its generation row; parent reconciliation must handle that case.

## EV-01 Feedback service

Feedback must be accepted on papers, readings, runs, ideas and chat answers.
<!-- id: SDD-EV-01 | tdd: TDD-6.1.1, TDD-6.2.1, TDD-6.2.2, TDD-6.2.3, TDD-6.2.4 | status: pending -->

- Behavior: When a visitor submits feedback, the server validates the target, records the signal, note, island scope and time, and exposes it to evolution. The target history and island feedback totals include the signal. Invalid feedback is rejected before evolution can read it.

- Contracts: [TDD-6.1.1](TDD.md#tdd-6.1.1), [TDD-6.2.1](TDD.md#tdd-6.2.1), [TDD-6.2.2](TDD.md#tdd-6.2.2), [TDD-6.2.3](TDD.md#tdd-6.2.3), [TDD-6.2.4](TDD.md#tdd-6.2.4).

- Code: [src/research_agent/beta/likes.py](src/research_agent/beta/likes.py) (`toggle_like`), [src/research_agent/beta/likes.py](src/research_agent/beta/likes.py) (`_resolve`), [src/research_agent/beta/likes.py](src/research_agent/beta/likes.py) (`points_of`).

- Tests: [tests/beta/test_api.py](tests/beta/test_api.py).

- Gap: Like rows have no signal or note; chat-answer targets, durable target history and island feedback totals are absent. Removing a like deletes its row. Bulk agent-point projections can multiply a paper like across repeated keep-readings, while selector points use an existential query. Consistent totals for that case are unproven.

## EV-02 Evolution threshold runner

Evolution must run after configured feedback or run-count thresholds without waiting for citation outcomes.
<!-- id: SDD-EV-02 | tdd: TDD-6.1.2, TDD-6.2.5, TDD-6.2.6, TDD-6.2.7, TDD-6.2.8 | status: pending -->

- Behavior: When an island reaches an evolution threshold, the cycle scores recent genomes from feedback, reading completion, trace health, cost and configured island preferences. The island page shows generation number, changed genomes and reason codes soon after threshold crossing. If a cycle cannot complete, it records a skipped reason and leaves active genomes unchanged. A skip does not consume completed-run progress. Due cycles retry on the heartbeat without manual input after a fifteen-minute cooldown.

- Contracts: [TDD-6.1.2](TDD.md#tdd-6.1.2), [TDD-6.2.5](TDD.md#tdd-6.2.5), [TDD-6.2.6](TDD.md#tdd-6.2.6), [TDD-6.2.7](TDD.md#tdd-6.2.7), [TDD-6.2.8](TDD.md#tdd-6.2.8).

- Code: [src/research_agent/beta/evolution.py](src/research_agent/beta/evolution.py) (`maybe_run_evolution`), [src/research_agent/beta/spec.py](src/research_agent/beta/spec.py) (`evolution_settings_from`), [src/research_agent/beta/evolution.py](src/research_agent/beta/evolution.py) (`_since_last`), [src/research_agent/beta/evolution.py](src/research_agent/beta/evolution.py) (`_proposal_from_model`).

- Tests: [tests/beta/test_evolution.py](tests/beta/test_evolution.py).

- Gap: Only completed-run thresholds and force trigger evolution. Feedback thresholds are accepted then discarded. Trace-health, completion, cost and preference-based usefulness scoring and feedback-trigger acceptance cases are absent. Run-count progress and heartbeat retries after skipped cycles are verified.

## EV-03 Atomic generation record

Each evolution cycle must create, retain or retire genomes with recorded reasons.
<!-- id: SDD-EV-03 | tdd: TDD-6.1.3, TDD-6.2.9, TDD-6.2.10, TDD-6.2.11, TDD-6.2.12 | status: implemented -->

- Behavior: When evolution completes candidate scoring, the cycle stores survivor, child and retired genome decisions with parent links and reason codes. The genome lineage page can show what changed in that generation. If the transaction fails, the cycle is discarded atomically and no partial lineage appears.

- Contracts: [TDD-6.1.3](TDD.md#tdd-6.1.3), [TDD-6.2.9](TDD.md#tdd-6.2.9), [TDD-6.2.10](TDD.md#tdd-6.2.10), [TDD-6.2.11](TDD.md#tdd-6.2.11), [TDD-6.2.12](TDD.md#tdd-6.2.12).

- Code: [src/research_agent/beta/evolution.py](src/research_agent/beta/evolution.py) (`maybe_run_evolution`), [src/research_agent/beta/evolution.py](src/research_agent/beta/evolution.py) (`mate_genomes`), [src/research_agent/beta/evolution.py](src/research_agent/beta/evolution.py) (`_unfinished_readers`), [src/research_agent/beta/evolution.py](src/research_agent/beta/evolution.py) (`_proposal_from_model`).

- Tests: [tests/beta/test_evolution.py](tests/beta/test_evolution.py).

- Gap: None.

## EV-04 Evolution activity projection

The UI must make evolution visible as recent island activity.
<!-- id: SDD-EV-04 | tdd: TDD-6.1.4, TDD-6.2.13, TDD-6.2.14, TDD-6.2.15, TDD-6.2.16, TDD-6.2.17 | status: pending -->

- Behavior: When a visitor opens an island page after an evolution cycle, the page keeps agent lineage and management inspectable below paper output and runs in a collapsed section. It omits routine skipped-cycle and decision-history panels. A visitor can follow a genome from island page to genome detail to runs. If the evolution projection is unavailable, the page marks that state before hiding evolution data.

- Contracts: [TDD-6.1.4](TDD.md#tdd-6.1.4), [TDD-6.2.13](TDD.md#tdd-6.2.13), [TDD-6.2.14](TDD.md#tdd-6.2.14), [TDD-6.2.15](TDD.md#tdd-6.2.15), [TDD-6.2.16](TDD.md#tdd-6.2.16), [TDD-6.2.17](TDD.md#tdd-6.2.17).

- Code: [src/research_agent/beta/evolution.py](src/research_agent/beta/evolution.py) (`build_generation_activity`), [src/research_agent/beta/projections.py](src/research_agent/beta/projections.py) (`_evolution_steps`), [apps/swarm-web/src/components/EvolutionTree.tsx](apps/swarm-web/src/components/EvolutionTree.tsx) (`EvolutionTree`), [apps/swarm-web/src/components/GenomeCard.tsx](apps/swarm-web/src/components/GenomeCard.tsx) (`GenomeCard`).

- Tests: [tests/beta/test_evolution.py](tests/beta/test_evolution.py), [apps/swarm-web/src/components/EvolutionTree.test.tsx](apps/swarm-web/src/components/EvolutionTree.test.tsx), [apps/swarm-web/src/App.test.tsx](apps/swarm-web/src/App.test.tsx).

- Gap: Stored generation projection, collapsed lineage browser and unavailable-agent fixtures have separate tests. A seeded-generation integration case following island to genome to run and propagating unavailable lineage into the browser is absent. Cost/feedback completeness stays under CT-02.

## UI-01 Visible route families

The app must expose a public storm entry page and login, island, paper, run and chat page families for the first release.
<!-- id: SDD-UI-01 | tdd: TDD-7.1.1, TDD-7.2.1, TDD-7.2.2, TDD-7.2.3 | status: pending -->

- Behavior: When the route table is built, the app registers the public storm entry and the five session page families without a separate rating or inspector app shell. Navigation from an island links to paper, run and chat pages. If an unexpected route family is registered, startup fails and names it.

- Contracts: [TDD-7.1.1](TDD.md#tdd-7.1.1), [TDD-7.2.1](TDD.md#tdd-7.2.1), [TDD-7.2.2](TDD.md#tdd-7.2.2), [TDD-7.2.3](TDD.md#tdd-7.2.3).

- Code: [apps/swarm-web/src/App.tsx](apps/swarm-web/src/App.tsx) (`PAGES`), [apps/swarm-web/src/pages/Splash.tsx](apps/swarm-web/src/pages/Splash.tsx) (`Splash`).

- Tests: [apps/swarm-web/src/App.test.tsx](apps/swarm-web/src/App.test.tsx), [apps/swarm-web/src/api/client.test.ts](apps/swarm-web/src/api/client.test.ts), [apps/swarm-web/src/api/contracts.test.ts](apps/swarm-web/src/api/contracts.test.ts).

- Gap: The exact route list is tested, but production route construction has no family validator: `Page.family` is a string and unknown URL handling falls back to Splash. Supplying an unrelated family must cause startup rejection naming it; that behavior and negative case are absent.

## UI-02 Paper cascade projection

The paper page must lead with submitted readings and takeaways, followed by source metadata, islands, runs, tool calls, feedback and cost.
<!-- id: SDD-UI-02 | tdd: TDD-7.1.2, TDD-7.2.4, TDD-7.2.5, TDD-7.2.6 | status: pending -->

- Behavior: When a visitor opens a paper page, the server returns the paper projection with nested links down to each agent run and tool-call evidence. The title and visible readings precede metadata and diagnostics, with an explicit empty or unavailable reading state and links to run evidence. If a section is missing or unavailable, the page marks that state and omits its drill-down links.

- Contracts: [TDD-7.1.2](TDD.md#tdd-7.1.2), [TDD-7.2.4](TDD.md#tdd-7.2.4), [TDD-7.2.5](TDD.md#tdd-7.2.5), [TDD-7.2.6](TDD.md#tdd-7.2.6).

- Code: [apps/swarm-web/src/pages/Paper.tsx](apps/swarm-web/src/pages/Paper.tsx) (`PaperPage`), [src/research_agent/beta/projections.py](src/research_agent/beta/projections.py) (`build_paper_projection`).

- Tests: [apps/swarm-web/src/App.test.tsx](apps/swarm-web/src/App.test.tsx), [tests/beta/test_api.py](tests/beta/test_api.py).

- Gap: Readings distinguish unavailable from empty. Assignment/run sections and nested cascade readers can still treat failed groups as empty. Failed assignments, runs and nested groups need unavailable text and absent drill-downs without hiding readings, feedback or replay links.

## UI-03 Chat answer service

Chat must answer from stored paper, island, genome, run, reading, feedback and cost data.
<!-- id: SDD-UI-03 | tdd: TDD-7.1.3, TDD-7.2.7, TDD-7.2.8, TDD-7.2.9 | status: pending -->

- Behavior: When a visitor asks chat about the storm, an island, a paper, a run or an idea, chat retrieves stored swarm data, answers with linked references and states no support when retrieval finds none. Paper-dependent claims carry paper or run links. If chat fails, it returns a retriable error without an unsupported paper claim.

- Contracts: [TDD-7.1.3](TDD.md#tdd-7.1.3), [TDD-7.2.7](TDD.md#tdd-7.2.7), [TDD-7.2.8](TDD.md#tdd-7.2.8), [TDD-7.2.9](TDD.md#tdd-7.2.9).

- Code: [src/research_agent/beta/chat.py](src/research_agent/beta/chat.py) (`answer_question`), [apps/swarm-web/src/components/ChatPanel.tsx](apps/swarm-web/src/components/ChatPanel.tsx) (`ChatPanel`).

- Tests: [tests/beta/test_chat.py](tests/beta/test_chat.py), [apps/swarm-web/src/components/ChatPanel.test.ts](apps/swarm-web/src/components/ChatPanel.test.ts).

- Gap: The server uses `supported=bool(links)`, so unrelated island context can mark an absent topic supported. Synthesized answers replace retrieval prose without checking each paper-dependent claim. ChatPanel does not inspect `supported`. Known/absent-topic, unsupported-synthesis refusal and visible no-support/retriable-state integration cases are absent. Submission and malformed-answer refusal have browser coverage; waiting and navigation during a request remain incompletely covered.

## UI-04 Chat non-authority

Chat must not be the durable source for run, paper, feedback, cost or evolution data.
<!-- id: SDD-UI-04 | tdd: TDD-7.1.4, TDD-7.2.10, TDD-7.2.11, TDD-7.2.12 | status: pending -->

- Behavior: When chat displays or accepts information about stored swarm objects, chat reads and writes through the underlying object services and persists no transcript as authority. Deleting browser chat state leaves paper, run, feedback, cost and evolution records unchanged. An operation that would store authority only in chat state is refused.

- Contracts: [TDD-7.1.4](TDD.md#tdd-7.1.4), [TDD-7.2.10](TDD.md#tdd-7.2.10), [TDD-7.2.11](TDD.md#tdd-7.2.11), [TDD-7.2.12](TDD.md#tdd-7.2.12).

- Code: [src/research_agent/beta/chat.py](src/research_agent/beta/chat.py) (`answer_question`), [apps/swarm-web/src/components/ChatPanel.tsx](apps/swarm-web/src/components/ChatPanel.tsx) (`ChatPanel`).

- Tests: [tests/beta/test_chat.py](tests/beta/test_chat.py), [apps/swarm-web/src/components/ChatPanel.test.ts](apps/swarm-web/src/components/ChatPanel.test.ts).

- Gap: Browser turns are transient, and the backend proves a distinctive question is not stored. No actual browser-to-HTTP persistence test clears conversation state and compares durable paper, run, feedback, cost and evolution records. Legitimate chat receipts must survive. Refusal of chat-only authority also lacks coverage.

## UI-05 Shared UI feedback action

The UI must allow feedback from island, paper, run and chat pages.
<!-- id: SDD-UI-05 | tdd: TDD-7.1.5, TDD-7.2.13, TDD-7.2.14, TDD-7.2.15 | status: pending -->

- Behavior: When a visitor views an object that accepts feedback, the page renders feedback controls that submit to the shared feedback service with island scope. Submitted feedback appears in the target history and island totals. If feedback fails, the page shows `feedback_unavailable` and does not fabricate a local vote.

- Contracts: [TDD-7.1.5](TDD.md#tdd-7.1.5), [TDD-7.2.13](TDD.md#tdd-7.2.13), [TDD-7.2.14](TDD.md#tdd-7.2.14), [TDD-7.2.15](TDD.md#tdd-7.2.15).

- Code: [apps/swarm-web/src/components/Like.tsx](apps/swarm-web/src/components/Like.tsx) (`Like`), [src/research_agent/beta/likes.py](src/research_agent/beta/likes.py) (`toggle_like`), [apps/swarm-web/src/components/ChatPanel.tsx](apps/swarm-web/src/components/ChatPanel.tsx) (`ChatPanel`).

- Tests: [apps/swarm-web/src/App.test.tsx](apps/swarm-web/src/App.test.tsx), [tests/beta/test_api.py](tests/beta/test_api.py).

- Gap: Paper/run/reading/claim/idea likes and selected-agent island likes exist. ChatPanel has no answer feedback control and the service has no chat-answer target. Target history, island totals, page-level `feedback_unavailable` and a four-page persistence/failure test are absent. Submission refusal currently shows a server reason and preserves the stored vote.
