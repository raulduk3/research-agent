# Technical Design Description

How the software is built to meet each requirement.

## Document control

| Field | Value |
| --- | --- |
| Product | research-agent. |
| Target version | First capped swarm release. |
| Scope | The design of what [SDD.md](SDD.md) requires, and nothing it does not. |
| Authority | This document decides how the software is built. Where code and this document disagree, one is wrong. |
| Companion documents | [SDD.md](SDD.md) states what the software must do. [SPEC-AMENDMENTS.md](SPEC-AMENDMENTS.md) records each change to either. |

## Normative language

- "must" states a requirement.
- "must not" states a prohibition.
- No other word makes a requirement.

## Conventions

- Each item is a `#### TDD-<section>.<n> Title` heading.
- A trace comment follows it: `<!-- id: TDD-x.y.z | implements: XX-nn | code: path#Symbol | tests: path or none | status: ... -->`.
- Status is one of `implemented`, `pending:#issue` or `deviation:#issue`.

## Shared design

The first release has one server and one browser app. The active backend is `src/research_agent/beta/` with SQLite persistence. Its existing owners are `ingest`, `papers`, `islands`, `spec`, `runs`, `projections`, `budget`, `costs`, `likes`, `evolution`, `auth`, `chat`, `service` and `app`. The active browser is `apps/swarm-web/`. Browser routes render a public storm entry plus login, island, paper, run and chat pages. Persistence owns paper records, island state, genome versions, run events, readings, feedback and cost receipts. Browser chat state is disposable.

Implementation references below name existing owners or the gate that must acquire the check. A referenced test establishes only its asserted behavior. Pending items remain incomplete until their full requirement and negative cases are proven. [The stabilization audit](docs/implementation/swarm-stabilization-audit.md) records evidence and remaining discrepancies.

## 1. Product cap

### 1.1 Release boundary

#### TDD-1.1.1 Release manifest gate
<!-- id: TDD-1.1.1 | implements: CP-01 | code: deploy/beta/Dockerfile | tests: tests/beta/test_deploy.py | status: pending:#430 -->

The beta image copies only the beta package and its pinned dependency closure. Packaging must validate admitted purposes, including the existing public storm entry. The current deployment tests check copy and import boundaries but do not plant an unrelated declared component; the manifest gate remains unbuilt.

#### TDD-1.1.2 Source line budget
<!-- id: TDD-1.1.2 | implements: CP-02 | code: bin/check | tests: none | status: pending:#430 -->

The existing repository gate is the owner of the source-budget check. It must count nonblank, noncomment application lines and reject a total at or above 30,000. That count and its negative-case test are not yet implemented.

#### TDD-1.1.3 Current-store admission
<!-- id: TDD-1.1.3 | implements: CP-03 | code: src/research_agent/beta/service.py#Swarm.prepare | tests: tests/beta/test_service.py | status: pending:#430 -->

Startup migrates the configured SQLite database and seeds its swarm specification. It does not scan historical data directories. Visible records must retain current ingestion or explicit import provenance; receipt admission has no dedicated negative-case test yet.

#### TDD-1.1.4 Prohibited component registry
<!-- id: TDD-1.1.4 | implements: CP-04 | code: deploy/beta/Dockerfile | tests: tests/beta/test_deploy.py | status: pending:#430 -->

The image copy boundary and beta import test exclude the historical platform from the deployed backend. A startup registry that refuses prohibited workflow registration remains unbuilt. The historical front end is not the swarm browser.

## 2. Ingestion and paper records

### 2.1 Current storm intake

#### TDD-2.1.1 Current ingestion pass
<!-- id: TDD-2.1.1 | implements: IG-01 | code: src/research_agent/beta/ingest.py#run_ingestion_pass | tests: tests/beta/test_ingest.py | status: pending:#430 -->

The ingestion pass normalizes current arXiv metadata, upserts paper identities, assigns islands and records failures and ingestion receipts. The service supplies the optional HTML text fetcher. Text failures preserve metadata and source links.

#### TDD-2.1.2 Resumable ingestion cursor
<!-- id: TDD-2.1.2 | implements: IG-02 | code: src/research_agent/beta/ingest.py#run_ingestion_pass | tests: tests/beta/test_ingest.py | status: pending:#425 -->

Canonical identity upserts prevent duplicates. Source cursors must drive continuation across source pages and interruption. The current adapter always requests the first page and stores a cursor without consuming it; #425 owns continuation beyond that window.

#### TDD-2.1.3 Paper projection rollup
<!-- id: TDD-2.1.3 | implements: IG-03 | code: src/research_agent/beta/projections.py#build_paper_projection | tests: tests/beta/test_api.py | status: pending:#430 -->

The paper projection assembles assignments, readings, runs, likes and costs through grouped reads. Failed groups appear in unavailable. The browser must preserve that distinction instead of treating failed groups as empty; #428 owns this repair.

#### TDD-2.1.4 Text failure visibility
<!-- id: TDD-2.1.4 | implements: IG-04 | code: src/research_agent/beta/text.py | tests: tests/beta/test_text.py | status: pending:#430 -->

The HTML fetch and ingestion paths retain text status and source metadata when full text is unavailable. Run inputs then use available passages or abstract text, without inventing full text.

## 3. Islands and genomes

### 3.1 Island ownership

#### TDD-3.1.1 Island projection
<!-- id: TDD-3.1.1 | implements: IS-01 | code: src/research_agent/beta/projections.py#build_island_projection | tests: apps/swarm-web/src/App.test.tsx | status: pending:#424 -->

The island projection provides paper and run activity, queue, agents, evolution, feedback and costs. Its bounded paper response prioritizes selected references before recent arrivals. IslandPage shows selected papers for future reference before other papers and current runs. Agent settings and lineage remain in a collapsed section. PaperPage uses its own assignment selection state to offer one manual override, including after deselection or when the paper is outside the island window. #424 owns browser ordering and explicit empty or unavailable states.

#### TDD-3.1.2 Island login session
<!-- id: TDD-3.1.2 | implements: IS-02 | code: src/research_agent/beta/auth.py#open_island_session | tests: tests/beta/test_api.py | status: pending:#430 -->

Login validates island credentials and issues a signed session token. API authorization derives island scope from the token. Chat transcript state stays in the browser and is not written as a login record.

#### TDD-3.1.3 Genome validation
<!-- id: TDD-3.1.3 | implements: IS-03 | code: src/research_agent/beta/spec.py#validate_genome | tests: tests/beta/test_spec.py | status: pending:#430 -->

Genome validation checks prompt, model parameters, tools, strategy and mutation metadata. apply_spec records immutable revisions and version history. Required scoring-preference fields and their effect must be reconciled with the existing genome contract before this item is complete.

#### TDD-3.1.4 Paper assignment
<!-- id: TDD-3.1.4 | implements: IS-04 | code: src/research_agent/beta/islands.py#assign_paper | tests: tests/beta/test_ingest.py | status: pending:#430 -->

Assignment scores category and keyword matches, stores reasons and falls back to General. Feedback and active-genome demand are not inputs to the current scorer. Those specified inputs remain unresolved under #430; category tests do not prove them.

#### TDD-3.1.5 Cross-island genome transfer
<!-- id: TDD-3.1.5 | implements: IS-05 | code: src/research_agent/beta/evolution.py#mate_genomes | tests: tests/beta/test_evolution.py | status: pending:#430 -->

Cross-island mating creates a child with parent references and mutation metadata in a new spec revision. Source genomes stay unchanged. The lineage record must expose the copied field set and source version rather than rely on mutable prompts.

## 4. Agent harness and runs

### 4.1 Atomic run model

#### TDD-4.1.1 One-paper run scheduler
<!-- id: TDD-4.1.1 | implements: RN-01 | code: src/research_agent/beta/runs.py#create_run | tests: tests/beta/test_runs.py | status: pending:#430 -->

Run creation binds exactly one paper, island, genome version and seed. Budget admission reserves the bounded request before provider execution. Selection context contains up to five other selected island papers under decision 0034.

#### TDD-4.1.2 Harness tool policy
<!-- id: TDD-4.1.2 | implements: RN-02 | code: src/research_agent/beta/runs.py#dispatch_tool_call | tests: tests/beta/test_runs.py | status: pending:#430 -->

Dispatch checks the genome tool policy, records refused attempts, and supplies bounded paper retrieval, related-paper lookup, notes, cost state and final submission. The actual schemas in runs.py define tool names; feedback-context behavior remains to be reconciled with this contract.

#### TDD-4.1.3 Run event trace
<!-- id: TDD-4.1.3 | implements: RN-03 | code: src/research_agent/beta/runs.py#append_run_event | tests: tests/beta/test_runs.py | status: pending:#426 -->

Immutable events retain prompt, model attempts, tool calls, notes, final reading and failures. Failed runs without a submitted reading expire after 24 hours on startup and heartbeat. Cleanup removes their events, notes and dependent discovery records while retaining immutable receipts. Completed readings and current-day retry and admission counters survive. #426 requires malformed provider responses to become typed failures with unsettled receipts. #427 requires startup recovery and execution ownership to distinguish live work from abandoned work.

#### TDD-4.1.4 Reading submission contract
<!-- id: TDD-4.1.4 | implements: RN-04 | code: src/research_agent/beta/runs.py#validate_reading_submission | tests: tests/beta/test_runs.py | status: pending:#430 -->

Submission validates bounded summary, claims, quotations, objections, related papers and idea seeds. Quote locators are checked against stored passages. Rejection leaves no accepted reading and records the failed attempt in the run trace.

#### TDD-4.1.5 Run page projection
<!-- id: TDD-4.1.5 | implements: RN-05 | code: src/research_agent/beta/projections.py#build_run_projection | tests: apps/swarm-web/src/pages/Run.test.tsx | status: pending:#424 -->

The projection supplies the immutable run, recorded genome version, ordered events, paper, reading and cost summary. RunPage leads with an available reading, otherwise live or failed status, before replay, genome and cost details. Preserve step query links and evidence navigation. #424 owns ordering.

#### TDD-4.1.6 Trace authority
<!-- id: TDD-4.1.6 | implements: RN-06 | code: src/research_agent/beta/projections.py#trace_authority_view | tests: tests/beta/test_runs.py | status: pending:#430 -->

Conduct, tool activity, timing and costs derive from harness events and receipts. Reading prose is content and cannot establish that a tool was called. Missing trace data must remain explicit.

## 5. Cost receipts

### 5.1 Cost attached to everything

#### TDD-5.1.1 Cost receipt writer
<!-- id: TDD-5.1.1 | implements: CT-01 | code: src/research_agent/beta/costs.py#record_cost_receipt | tests: tests/beta/test_costs.py | status: pending:#426 -->

The leaf-charge ledger stores owner, parent object, units, amount, provider and settlement state. Paid requests that fail after dispatch retain an unsettled estimate. #426 covers malformed response accounting; coverage for every scarce tool and reading action remains incomplete.

#### TDD-5.1.2 Cost-aware projections
<!-- id: TDD-5.1.2 | implements: CT-02 | code: src/research_agent/beta/costs.py#attach_cost_summary | tests: tests/beta/test_costs.py | status: pending:#430 -->

Cost summaries return settled totals and unsettled counts or unavailable. Paper, run and island views use those summaries beside output and activity. #428 fixes the run total that currently mixes settlement states. Genome, evolution and cost-per-useful-feedback coverage remain incomplete.

#### TDD-5.1.3 Evolution cost policy
<!-- id: TDD-5.1.3 | implements: CT-03 | code: src/research_agent/beta/evolution.py#maybe_run_evolution | tests: tests/beta/test_evolution.py | status: pending:#430 -->

The current implementation ranks parents by like points, run count and id, then applies breeding and budget admission. It does not implement usefulness bands, a cost tie-break or per-genome budget exclusion. #430 owns the discrepancy; do not add another fitness system without an accepted decision.

#### TDD-5.1.4 Cost rollup ledger
<!-- id: TDD-5.1.4 | implements: CT-04 | code: src/research_agent/beta/costs.py#sum_cost_scope | tests: tests/beta/test_costs.py | status: pending:#430 -->

Each receipt is a leaf charge attached to object scope columns, not an aggregate charge. Scope totals sum leaf receipts once by run, paper or island. Nested receipt graphs are not the storage model. Graph consistency and genome-scope requirements remain open under #430.

## 6. Feedback and rapid evolution

### 6.1 Live genome movement

#### TDD-6.1.1 Feedback service
<!-- id: TDD-6.1.1 | implements: EV-01 | code: src/research_agent/beta/likes.py#toggle_like | tests: tests/beta/test_api.py | status: pending:#430 -->

A persisted island-scoped toggle validates paper, run, reading, claim, idea and agent targets. The specified signal, optional note and chat-answer targets are not implemented. Resolve the contract under #430 before extending the existing service.

#### TDD-6.1.2 Evolution threshold runner
<!-- id: TDD-6.1.2 | implements: EV-02 | code: src/research_agent/beta/evolution.py#maybe_run_evolution | tests: tests/beta/test_evolution.py | status: pending:#430 -->

Evolution triggers on configured run count or an explicit force request. Feedback-count thresholds and scoring from completion, trace health and preferences are absent. #430 owns reconciliation with the declared threshold and usefulness contract.

#### TDD-6.1.3 Atomic generation record
<!-- id: TDD-6.1.3 | implements: EV-03 | code: src/research_agent/beta/evolution.py#maybe_run_evolution | tests: tests/beta/test_evolution.py | status: pending:#430 -->

Evolution writes generation records and revised genome lineage in the database transaction. Children cite parents and mutation reasons. Verify rollback of a forced mid-generation failure before marking the item complete.

#### TDD-6.1.4 Evolution activity projection
<!-- id: TDD-6.1.4 | implements: EV-04 | code: src/research_agent/beta/evolution.py#build_generation_activity | tests: tests/beta/test_evolution.py | status: pending:#430 -->

Generation activity exposes recorded survivors, children, retired agents and lineage. IslandPage keeps lineage inspectable in a collapsed section below paper output and current runs. Routine cycle and decision histories are omitted from the browser. Only committed generations reset completed-run progress, and an idle heartbeat retries due evolution after a fifteen-minute skipped-cycle cooldown. Feedback and settlement-aware cost totals need complete projection coverage.

## 7. Pages and chat

### 7.1 Visible surfaces

#### TDD-7.1.1 Visible route families
<!-- id: TDD-7.1.1 | implements: UI-01 | code: apps/swarm-web/src/App.tsx#PAGES | tests: apps/swarm-web/src/App.test.tsx | status: pending:#430 -->

The active browser is apps/swarm-web. PAGES registers public splash, login, island, paper, run and chat. The root splash is the entry to the same swarm app, not a separate product shell. The historical front-end route table is outside this release.

#### TDD-7.1.2 Paper cascade projection
<!-- id: TDD-7.1.2 | implements: UI-02 | code: apps/swarm-web/src/pages/Paper.tsx#PaperPage | tests: apps/swarm-web/src/App.test.tsx | status: pending:#424 -->

PaperPage consumes build_paper_projection. The title and visible ReadingView content precede metadata, assignments, run traces and cost breakdown. Empty and unavailable readings have different messages. Each reading retains likes and links to run evidence. #424 owns ordering and #428 owns unavailable groups.

#### TDD-7.1.3 Chat answer service
<!-- id: TDD-7.1.3 | implements: UI-03 | code: src/research_agent/beta/chat.py#answer_question | tests: tests/beta/test_chat.py | status: pending:#428 -->

Chat retrieves island-scoped stored references and either renders deterministic retrieval text or requests optional synthesis. Retrieved links alone do not prove generated claims are supported. #428 requires unlinked or invented model claims to remain unsupported and adds HTTP and browser interaction coverage.

#### TDD-7.1.4 Chat non-authority
<!-- id: TDD-7.1.4 | implements: UI-04 | code: src/research_agent/beta/chat.py#answer_question | tests: tests/beta/test_chat.py | status: pending:#430 -->

Chat stores retrieval and paid-answer receipts but no transcript as authority. Durable object changes belong to their existing services. Clearing browser conversation state must leave swarm records intact.

#### TDD-7.1.5 Shared UI feedback action
<!-- id: TDD-7.1.5 | implements: UI-05 | code: apps/swarm-web/src/components/Like.tsx#Like | tests: apps/swarm-web/src/App.test.tsx | status: pending:#430 -->

Like is the shared persisted browser toggle for admitted stored targets. Paper and run pages expose it. Island and chat feedback affordances remain incomplete under #430; do not fake browser-only votes or create a second feedback owner.
