# Software Design Description

What the software must do, stated as requirements a reader can verify.

## Document control

| Field | Value |
| --- | --- |
| Product | research-agent: a cloud-hosted paper swarm with islands, genomes, agent runs, cost receipts and explorable readings. |
| Target version | First capped swarm release. |
| Scope | One cloud server, current paper ingestion, island pages, paper drill-down, agent-run traces, rapid genome evolution, feedback and casual chat. |
| Authority | This document decides what the software does. Where code and this document disagree, one is wrong. |
| Companion documents | [TDD.md](TDD.md) states how each requirement is met. [SPEC-AMENDMENTS.md](SPEC-AMENDMENTS.md) records each change to either. |

## Scope and scale

The product is a living paper-reading swarm. It ingests current papers on one cloud server, assigns each paper to research islands, runs agents whose behavior comes from explicit genomes, stores every agent run, evolves island genomes quickly from feedback and run results, and lets people inspect the cascade from island to paper to run to tool call.

The first release includes a public storm entry page and five island-session page families: login, island, paper, run and chat. An island login opens an endless casual session for that island. Chat history is not a first-release durable record. Agent-run data, cost receipts, feedback, paper records, island state and genome lineage are durable records.

The first release excludes the earlier large platform shape: two separate front ends, rating-only workflows, historical citation forecasting as the spine, prediction-head qualification, Jev assessment, OCR, public publishing, model training, distributed clusters and work on stale local data unless an operator imports it into the current store.

The implementation must stay below 30,000 nonblank, noncomment application source lines for the first release. Generated files, lockfiles, tests, specifications and vendored dependencies are outside that count.

## Normative language

- "must" states a requirement.
- "must not" states a prohibition.
- No other word makes a requirement.

## Conventions

- Each requirement is one sentence on a `**XX-nn.**` line.
- A trace comment follows it: `<!-- id: SDD-XX-nn | tdd: TDD-x.y.z | status: ... -->`.
- Bullets follow the trace comment: `Trigger`, `Behavior`, `Observable`, `On failure`, and `Verified by`.
- Status is one of `implemented`, `pending:#issue` or `deviation:#issue`.

## Terms

| Term | Meaning |
| --- | --- |
| agent run | One agent reading one paper under one genome with a stored prompt, tool trace, cost receipts and final reading. |
| chat | A casual island-scoped conversation surface that can inspect stored swarm data and does not persist transcript history in the first release. |
| cost receipt | A stored resource record for paid or scarce work, with owner, amount, units, provider when known and parent object. |
| feedback | A user signal on a paper, reading, run, idea or chat answer that becomes evolution input. |
| genome | A versioned agent configuration: prompt, island, model settings, tool policy, reading strategy, scoring preferences and mutation metadata. |
| island | A research group with its own page, queue, genomes, runs, readings, feedback totals, cost totals and lineage. |
| paper record | The metadata, source links, available text, assigned islands, readings, runs, feedback and cost totals for one paper. |
| reading | A bounded agent output for one paper with summary, claims, evidence references, objections, related papers and idea seeds. |
| storm | The current stream of ingested papers and their island activity. |
| swarm | The running population of island genomes and their agent runs. |
| tool call | A recorded harness action available to an agent run, such as paper text retrieval, related-paper lookup, note capture or final submission. |

## 1. Product cap

### 1.1 Release boundary

**CP-01.** The first release must ship one cloud-hosted swarm application with current ingestion, islands, genomes, agent runs, feedback evolution, cost receipts and the five visible pages.
<!-- id: SDD-CP-01 | tdd: TDD-1.1.1 | status: pending:#430 -->

- Trigger: A release build is assembled.
- Behavior: The build manifest admits only components serving ingestion, islands, genomes, runs, evolution, cost or one of the five visible pages.
- Observable: The manifest lists each component with exactly one admitted purpose.
- On failure: The build fails before packaging.
- Verified by: A manifest test that plants an unrelated component and checks that packaging is refused.

**CP-02.** The first-release application source must stay below 30,000 nonblank, noncomment lines.
<!-- id: SDD-CP-02 | tdd: TDD-1.1.2 | status: pending:#430 -->

- Trigger: The repository check runs.
- Behavior: The check counts application source files and excludes tests, generated files, lockfiles, specifications and vendored dependencies.
- Observable: The check prints the counted total and the configured ceiling.
- On failure: The check fails with the paths contributing to the excess.
- Verified by: A line-count test that adds counted source over the ceiling and confirms failure.

**CP-03.** The runtime must ignore stale local data unless an operator imports it into the current store.
<!-- id: SDD-CP-03 | tdd: TDD-1.1.3 | status: pending:#430 -->

- Trigger: The server starts or an ingestion pass runs.
- Behavior: The runtime reads current store records and operator-imported records with receipts, not arbitrary files on disk.
- Observable: Each visible paper has a current ingestion receipt or import receipt.
- On failure: The record is hidden from pages, chat, assignment and evolution.
- Verified by: A startup test with old files on disk that confirms none appear without import receipts.

**CP-04.** The first release must not ship rating-only workflows, historical citation forecasting, prediction-head qualification, Jev assessment, OCR, model training, public publishing or distributed clusters.
<!-- id: SDD-CP-04 | tdd: TDD-1.1.4 | status: pending:#430 -->

- Trigger: A route, job, worker or dependency is registered.
- Behavior: Registration is refused when the component exists only for a prohibited workflow.
- Observable: The route and job registries contain no prohibited component names.
- On failure: The server refuses startup and names the prohibited registration.
- Verified by: A registry test that tries to register one prohibited workflow and checks startup refusal.

## 2. Ingestion and paper records

### 2.1 Current storm intake

**IG-01.** Ingestion must collect current paper metadata and available text into one server-side store.
<!-- id: SDD-IG-01 | tdd: TDD-2.1.1 | status: pending:#430 -->

- Trigger: An ingestion pass starts.
- Behavior: The pass fetches configured current sources, normalizes metadata, stores source links, stores text when available and records text failures.
- Observable: Each paper record has source, fetch time, metadata, text status and immutable source links.
- On failure: The failed source is recorded and successful source records remain committed.
- Verified by: An ingestion test with one unavailable source that preserves successful paper records and records the failure.

**IG-02.** Ingestion must be resumable without duplicating paper records.
<!-- id: SDD-IG-02 | tdd: TDD-2.1.2 | status: pending:#425 -->

- Trigger: An ingestion pass stops and later restarts.
- Behavior: The restarted pass resumes from stored source cursors and upserts by canonical paper identity.
- Observable: Re-running a completed pass leaves one paper record per canonical paper identity.
- On failure: Ambiguous identity records are quarantined and excluded from island assignment.
- Verified by: A restart test that interrupts after partial storage, reruns and confirms no duplicate paper records.

**IG-03.** Every paper record must roll up its island assignments, readings, agent runs, feedback and cost receipts.
<!-- id: SDD-IG-03 | tdd: TDD-2.1.3 | status: pending:#430 -->

- Trigger: The paper page or chat requests a paper.
- Behavior: The server assembles the paper record from stored paper, assignment, run, reading, feedback and cost tables.
- Observable: The paper page shows counts and links for each rollup group.
- On failure: The page marks the failed group unavailable rather than showing a partial group as complete.
- Verified by: A paper projection test that seeds each group and checks the paper response links all of them.

**IG-04.** A paper must remain inspectable when text extraction fails.
<!-- id: SDD-IG-04 | tdd: TDD-2.1.4 | status: pending:#430 -->

- Trigger: Text extraction fails for an ingested paper.
- Behavior: The paper record keeps metadata, source links, text failure category and assignment eligibility.
- Observable: The paper page shows the paper with text status failed and no fabricated text.
- On failure: Agents receive only metadata and available source links for that paper.
- Verified by: An extraction-failure test that confirms the paper remains visible and no text field is invented.

## 3. Islands and genomes

### 3.1 Island ownership

**IS-01.** Each island must have its own page with queue, papers, genomes, runs, readings, feedback totals and cost totals.
<!-- id: SDD-IS-01 | tdd: TDD-3.1.1 | status: pending:#424 -->

- Trigger: A logged-in visitor opens an island page.
- Behavior: The server returns the island projection with paper output and current reading activity before genome settings and evolution controls, with links to paper and run pages.
- Observable: Paper output and current runs precede configuration, with section counts and drill-down links.
- On failure: The page marks a failed section unavailable rather than hiding it.
- Verified by: Projection and browser tests that seed every section and check output appears before configuration.

**IS-02.** Login must bind a visitor to one island without creating durable chat-session records.
<!-- id: SDD-IS-02 | tdd: TDD-3.1.2 | status: pending:#430 -->

- Trigger: A visitor selects or enters an island login.
- Behavior: The server issues an island-scoped browser session and stores no chat transcript for that login.
- Observable: Requests carry island scope, and durable storage has no chat transcript row for the login.
- On failure: The login is refused before any island data is shown.
- Verified by: A login test that opens an island session and checks storage for no transcript record.

**IS-03.** Each genome must declare its prompt, island, model settings, allowed tools, reading strategy, scoring preferences and lineage metadata.
<!-- id: SDD-IS-03 | tdd: TDD-3.1.3 | status: pending:#430 -->

- Trigger: A genome is created, imported or mutated.
- Behavior: The genome validator requires every declared field and records parent references for non-founder genomes.
- Observable: The genome page and run records can display the exact genome version used.
- On failure: The genome is rejected and cannot start runs.
- Verified by: A genome validation test that rejects missing fields and accepts a complete founder and child genome.

**IS-04.** A paper assignment must choose one or more islands from metadata, current focus, feedback and genome demand.
<!-- id: SDD-IS-04 | tdd: TDD-3.1.4 | status: pending:#430 -->

- Trigger: A paper becomes assignment-eligible.
- Behavior: The assignment step stores island ids and reason codes, using a general island when evidence is sparse.
- Observable: The paper and island pages show assignment reason codes.
- On failure: The paper is assigned to the general island with assignment_uncertain.
- Verified by: An assignment test that routes known, cross-topic and sparse papers to observable island sets.

**IS-05.** Cross-island transfer must copy behavior through genome lineage rather than shared mutable prompts.
<!-- id: SDD-IS-05 | tdd: TDD-3.1.5 | status: pending:#430 -->

- Trigger: Evolution borrows behavior from another island.
- Behavior: The system creates a child genome that cites the source island, source genome and copied field set.
- Observable: The child genome lineage shows the cross-island transfer.
- On failure: No mutable prompt is changed in place.
- Verified by: A transfer test that mutates one island and confirms the source genome remains unchanged.

## 4. Agent harness and runs

### 4.1 Atomic run model

**RN-01.** The atomic work unit must be one agent run reading one paper under one genome.
<!-- id: SDD-RN-01 | tdd: TDD-4.1.1 | status: pending:#430 -->

- Trigger: The scheduler creates reading work.
- Behavior: The scheduler creates a run with one paper id, one island id, one genome version and one run seed.
- Observable: Every run page names exactly one paper and one genome.
- On failure: Work with missing or multiple papers is refused before model calls.
- Verified by: A scheduler test that rejects zero-paper and multi-paper run requests.

**RN-02.** The harness must expose a bounded tool set for paper text, related papers, note capture, feedback context, cost state and final submission.
<!-- id: SDD-RN-02 | tdd: TDD-4.1.2 | status: pending:#430 -->

- Trigger: An agent run starts.
- Behavior: The harness builds allowed tool schemas from the genome and refuses calls outside that set.
- Observable: The run page lists allowed tools and each attempted tool call.
- On failure: The refused call is recorded and no side effect occurs.
- Verified by: A harness test that allows a declared tool and records refusal for an undeclared tool.

**RN-03.** Every agent run must store its prompt, model settings, tool trace, notes, final reading, status and cost receipts.
<!-- id: SDD-RN-03 | tdd: TDD-4.1.3 | status: pending:#426 -->

- Trigger: A run starts, calls a tool, calls a model, submits or fails.
- Behavior: The harness appends immutable run events and links each paid or scarce action to a cost receipt.
- Observable: The run page can reconstruct the run from stored events.
- On failure: The run is marked failed with the last committed event and cost total.
- Verified by: A trace test that forces a mid-run failure and checks prompt, events and costs remain visible.

**RN-04.** A reading must contain summary, claims, evidence references, objections, related papers and idea seeds.
<!-- id: SDD-RN-04 | tdd: TDD-4.1.4 | status: pending:#430 -->

- Trigger: An agent submits a final reading.
- Behavior: The submission validator requires the bounded reading fields and source references where claims depend on paper text.
- Observable: The paper page renders each field under the submitting run.
- On failure: The reading is rejected and the run remains incomplete.
- Verified by: A submission test that rejects missing fields and accepts a complete reading with evidence references.

**RN-05.** The run page must show the cascade from run to tool calls to atomic evidence.
<!-- id: SDD-RN-05 | tdd: TDD-4.1.5 | status: pending:#424 -->

- Trigger: A visitor opens a run page.
- Behavior: The page leads with the submitted reading for a completed run or current status when no reading exists, followed by replay, genome, costs and notes in event order.
- Observable: The reading appears before diagnostics, and each final claim links to its cited evidence or is marked uncited.
- On failure: The page reports missing artifacts instead of substituting agent prose.
- Verified by: A run page test that checks reading-first document order, live and failed states, replay order and evidence links.

**RN-06.** The harness must record run data independently of the agent's self-report.
<!-- id: SDD-RN-06 | tdd: TDD-4.1.6 | status: pending:#430 -->

- Trigger: An agent describes its own behavior.
- Behavior: The system displays conduct, tools, timing and costs from harness events only.
- Observable: A mismatch between agent prose and trace favors the trace on the run page.
- On failure: The disputed field is marked trace_missing rather than trusting the agent.
- Verified by: A test where an agent claims an unmade tool call and the page shows no such call.

## 5. Cost receipts

### 5.1 Cost attached to everything

**CT-01.** Every paid or scarce action must create a cost receipt.
<!-- id: SDD-CT-01 | tdd: TDD-5.1.1 | status: pending:#426 -->

- Trigger: The system performs ingestion, model inference, tool work, reading, evolution or chat retrieval.
- Behavior: The actor records owner id, parent id, unit type, quantity, cost amount when known and estimation flag when estimated.
- Observable: Each page can show cost totals from receipts rather than recomputing hidden counters.
- On failure: The parent action is marked cost_unsettled and excluded from settled totals.
- Verified by: A cost test that runs each action type and checks a linked receipt exists.

**CT-02.** Paper, island, genome, run, evolution and chat views must show cost beside activity.
<!-- id: SDD-CT-02 | tdd: TDD-5.1.2 | status: pending:#430 -->

- Trigger: A view renders an activity count or generated answer.
- Behavior: The view includes settled cost, unsettled cost count and cost-per-useful-feedback where feedback exists.
- Observable: Cost appears beside papers read, runs, readings, genome lineage and chat answers.
- On failure: The view marks cost unavailable rather than showing zero.
- Verified by: Projection tests that seed settled and unsettled receipts and check the displayed totals.

**CT-03.** Evolution must use cost only as a tie-breaker unless a genome exceeds a configured budget.
<!-- id: SDD-CT-03 | tdd: TDD-5.1.3 | status: pending:#430 -->

- Trigger: Evolution compares genome candidates.
- Behavior: The selector ranks usefulness first, applies cost between candidates with equal usefulness band and rejects candidates over budget.
- Observable: The evolution record shows usefulness, cost and budget decisions separately.
- On failure: The cycle records no survivor change for that comparison.
- Verified by: An evolution-cost test that confirms a useful expensive genome beats a cheap bad genome and an over-budget genome is refused.

**CT-04.** Cost receipts must roll up through parent links without double counting.
<!-- id: SDD-CT-04 | tdd: TDD-5.1.4 | status: pending:#430 -->

- Trigger: A cost total is requested.
- Behavior: The cost service sums each receipt once through stored parent links and excludes child totals already represented by parent receipts.
- Observable: Paper, island and genome totals equal the receipt ledger for their scope.
- On failure: The total is marked inconsistent and not displayed as settled.
- Verified by: A rollup test with nested receipts that proves each charge is counted once.

## 6. Feedback and rapid evolution

### 6.1 Live genome movement

**EV-01.** Feedback must be accepted on papers, readings, runs, ideas and chat answers.
<!-- id: SDD-EV-01 | tdd: TDD-6.1.1 | status: pending:#430 -->

- Trigger: A visitor submits feedback.
- Behavior: The server validates the target, records the signal, note, island scope and time, and exposes it to evolution.
- Observable: The target history and island feedback totals include the signal.
- On failure: Invalid feedback is rejected before evolution can read it.
- Verified by: A feedback test that records valid targets, rejects invalid ones and checks evolution input.

**EV-02.** Evolution must run after configured feedback or run-count thresholds without waiting for citation outcomes.
<!-- id: SDD-EV-02 | tdd: TDD-6.1.2 | status: pending:#430 -->

- Trigger: An island reaches an evolution threshold.
- Behavior: The cycle scores recent genomes from feedback, reading completion, trace health, cost and configured island preferences.
- Observable: The island page shows generation number, changed genomes and reason codes soon after threshold crossing.
- On failure: The cycle records skipped with reason and leaves active genomes unchanged.
- Verified by: A threshold test that crosses the feedback count and confirms a generation record appears.

**EV-03.** Each evolution cycle must create, retain or retire genomes with recorded reasons.
<!-- id: SDD-EV-03 | tdd: TDD-6.1.3 | status: pending:#430 -->

- Trigger: Evolution completes candidate scoring.
- Behavior: The cycle stores survivor, child and retired genome decisions with parent links and reason codes.
- Observable: The genome lineage page can show what changed in that generation.
- On failure: The cycle is discarded atomically and no partial lineage appears.
- Verified by: A lineage test that confirms create, retain and retire decisions are recorded together.

**EV-04.** The UI must make evolution visible as recent island activity.
<!-- id: SDD-EV-04 | tdd: TDD-6.1.4 | status: pending:#430 -->

- Trigger: A visitor opens an island page after an evolution cycle.
- Behavior: The page highlights new, retained and retired genomes with run counts, feedback totals and cost totals.
- Observable: A visitor can follow a genome from island page to genome detail to runs.
- On failure: Evolution state is hidden only when the projection is unavailable and marked as such.
- Verified by: An island UI test that seeds a generation and checks visible lineage links.

## 7. Pages and chat

### 7.1 Visible surfaces

**UI-01.** The app must expose a public storm entry page and login, island, paper, run and chat page families for the first release.
<!-- id: SDD-UI-01 | tdd: TDD-7.1.1 | status: pending:#430 -->

- Trigger: The route table is built.
- Behavior: The app registers the public storm entry and the five session page families without a separate rating or inspector app shell.
- Observable: Navigation from an island links to paper, run and chat pages.
- On failure: Startup fails with the unexpected route family name.
- Verified by: A route test that accepts the public entry and five session families and rejects unrelated page families.

**UI-02.** The paper page must lead with submitted readings and takeaways, followed by source metadata, islands, runs, tool calls, feedback and cost.
<!-- id: SDD-UI-02 | tdd: TDD-7.1.2 | status: pending:#424 -->

- Trigger: A visitor opens a paper page.
- Behavior: The server returns the paper projection with nested links down to each agent run and tool-call evidence.
- Observable: The title and visible readings precede metadata and diagnostics, with an explicit empty or unavailable reading state and links to run evidence.
- On failure: Missing sections are marked unavailable and keep their drill-down links absent.
- Verified by: A paper page test that checks visible readings before diagnostics, evidence links and empty or unavailable states.

**UI-03.** Chat must answer from stored paper, island, genome, run, reading, feedback and cost data.
<!-- id: SDD-UI-03 | tdd: TDD-7.1.3 | status: pending:#428 -->

- Trigger: A visitor asks chat about the storm, an island, a paper, a run or an idea.
- Behavior: Chat retrieves stored swarm data, answers with linked references and states no support when retrieval finds none.
- Observable: Paper-dependent claims carry paper or run links.
- On failure: Chat returns a retriable error and no unsupported paper claim.
- Verified by: A chat test that asks known and absent topics and checks linked answers or no-support responses.

**UI-04.** Chat must not be the durable source for run, paper, feedback, cost or evolution data.
<!-- id: SDD-UI-04 | tdd: TDD-7.1.4 | status: pending:#430 -->

- Trigger: Chat displays or accepts information about stored swarm objects.
- Behavior: Chat reads and writes through the underlying object services and persists no transcript as authority.
- Observable: Deleting browser chat state leaves paper, run, feedback, cost and evolution records unchanged.
- On failure: The operation is refused if it would store only in chat state.
- Verified by: A persistence test that clears chat state and confirms durable swarm records remain.

**UI-05.** The UI must allow feedback from island, paper, run and chat pages.
<!-- id: SDD-UI-05 | tdd: TDD-7.1.5 | status: pending:#430 -->

- Trigger: A visitor views an object that accepts feedback.
- Behavior: The page renders feedback controls that submit to the shared feedback service with island scope.
- Observable: Submitted feedback appears in the target history and island totals.
- On failure: The page shows feedback_unavailable and does not fake a local vote.
- Verified by: A UI feedback test that submits from each page and checks one stored feedback shape.
