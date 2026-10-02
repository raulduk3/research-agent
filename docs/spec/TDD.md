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

The first release has one server and one browser app. Server modules are `ingest`, `papers`, `islands`, `genomes`, `runs`, `costs`, `evolution`, `feedback` and `chat`. Browser routes render login, island, paper, run and chat pages. Persistence owns paper records, island state, genome versions, run events, readings, feedback and cost receipts. Browser chat state is disposable.

## 1. Product cap

### 1.1 Release boundary

#### TDD-1.1.1 Release manifest gate
<!-- id: TDD-1.1.1 | implements: CP-01 | code: src/research_agent/release/manifest.py#validate_release_manifest | tests: tests/release/test_manifest.py | status: pending:#378 -->

`validate_release_manifest` reads declared components and requires each component to name one admitted purpose: ingestion, island, genome, run, evolution, cost, login_page, island_page, paper_page, run_page or chat_page. Packaging calls the validator. The test plants an unrelated component and proves packaging fails.

#### TDD-1.1.2 Source line budget
<!-- id: TDD-1.1.2 | implements: CP-02 | code: tools/source_budget.py#count_application_source | tests: tests/release/test_source_budget.py | status: pending:#378 -->

`count_application_source` walks configured application paths, ignores blank and comment-only lines, excludes tests, generated paths, lockfiles, specifications and vendored directories, and returns per-path counts plus total. `bin/check` fails when the total exceeds 30,000. The test adds temporary counted files over the ceiling and checks the failure report.

#### TDD-1.1.3 Current-store admission
<!-- id: TDD-1.1.3 | implements: CP-03 | code: src/research_agent/storage/admission.py#admit_visible_record | tests: tests/storage/test_admission.py | status: pending:#378 -->

`admit_visible_record` accepts only records that carry a current ingestion receipt or an explicit import receipt. Startup never scans arbitrary data directories for visible records. The test creates old files beside the runtime and confirms no paper appears until an import receipt is inserted.

#### TDD-1.1.4 Prohibited component registry
<!-- id: TDD-1.1.4 | implements: CP-04 | code: src/research_agent/release/registry.py#register_component | tests: tests/release/test_registry.py | status: pending:#378 -->

`register_component` rejects route, worker and dependency registrations tagged rating_only, historical_citation_forecast, prediction_head_qualification, jev_assessment, ocr, model_training, public_publishing or distributed_cluster. Startup uses the same registry. The test attempts one prohibited tag and checks startup refusal.

## 2. Ingestion and paper records

### 2.1 Current storm intake

#### TDD-2.1.1 Current ingestion pass
<!-- id: TDD-2.1.1 | implements: IG-01 | code: src/research_agent/ingest/current.py#run_ingestion_pass | tests: tests/ingest/test_current.py | status: pending:#378 -->

`run_ingestion_pass` fetches each configured source through a source adapter, normalizes metadata into `PaperRecord`, stores immutable source links, and attempts text extraction into `PaperTextStatus`. Source failures write `SourceFailure` rows and do not roll back successful papers. The test simulates one failed source and confirms successful papers remain committed.

#### TDD-2.1.2 Resumable ingestion cursor
<!-- id: TDD-2.1.2 | implements: IG-02 | code: src/research_agent/ingest/current.py#resume_ingestion_pass | tests: tests/ingest/test_resume.py | status: pending:#378 -->

`resume_ingestion_pass` reads source cursor rows, restarts from the last committed cursor boundary and upserts by canonical paper identity. Ambiguous identities write `QuarantinedPaper` and are not assignment inputs. The test interrupts after partial storage, reruns and checks one paper row per identity.

#### TDD-2.1.3 Paper projection rollup
<!-- id: TDD-2.1.3 | implements: IG-03 | code: src/research_agent/papers/projections.py#build_paper_projection | tests: tests/papers/test_projection.py | status: pending:#378 -->

`build_paper_projection` loads the paper row and rollups for assignments, readings, runs, feedback and cost receipts. Each group carries `available`, `unavailable` or `empty` state, so projection failure cannot masquerade as no data. The test seeds every group and checks links and counts.

#### TDD-2.1.4 Text failure visibility
<!-- id: TDD-2.1.4 | implements: IG-04 | code: src/research_agent/papers/text.py#record_text_failure | tests: tests/papers/test_text_status.py | status: pending:#378 -->

`record_text_failure` stores a typed failure category on the paper text status and leaves metadata, source links and assignment eligibility intact. Agent input builders read available text only and never synthesize missing text. The test fails extraction and confirms the paper remains visible with no fabricated text field.

## 3. Islands and genomes

### 3.1 Island ownership

#### TDD-3.1.1 Island projection
<!-- id: TDD-3.1.1 | implements: IS-01 | code: src/research_agent/islands/projections.py#build_island_projection | tests: tests/islands/test_projection.py | status: pending:#378 -->

`build_island_projection` reads queue rows, paper summaries, active and retired genomes, runs, readings, feedback totals and cost totals for one island. Section results have explicit availability state. The test seeds each section and checks the response carries counts and drill-down ids.

#### TDD-3.1.2 Island login session
<!-- id: TDD-3.1.2 | implements: IS-02 | code: src/research_agent/auth/islands.py#open_island_session | tests: tests/auth/test_island_login.py | status: pending:#378 -->

`open_island_session` validates the selected island or island access code, issues a signed browser session with island scope and writes no chat transcript row. Request middleware derives island scope from that session. The test opens a session and queries storage to confirm no chat transcript exists.

#### TDD-3.1.3 Genome validation
<!-- id: TDD-3.1.3 | implements: IS-03 | code: src/research_agent/genomes/model.py#validate_genome | tests: tests/genomes/test_model.py | status: pending:#378 -->

`validate_genome` requires prompt, island id, model settings, allowed tools, reading strategy, scoring preferences and lineage metadata. Founder genomes carry a founder marker; child genomes carry parent references and mutation metadata. The test rejects missing fields and accepts one founder and one child genome.

#### TDD-3.1.4 Paper assignment
<!-- id: TDD-3.1.4 | implements: IS-04 | code: src/research_agent/islands/assignment.py#assign_paper | tests: tests/islands/test_assignment.py | status: pending:#378 -->

`assign_paper` scores candidate islands from paper metadata, island focus, feedback aggregates and active genome demand, then writes assignment rows with reason codes. Sparse metadata falls back to the general island and reason `assignment_uncertain`. The test covers known, cross-topic and sparse papers.

#### TDD-3.1.5 Cross-island genome transfer
<!-- id: TDD-3.1.5 | implements: IS-05 | code: src/research_agent/genomes/lineage.py#copy_behavior | tests: tests/genomes/test_lineage.py | status: pending:#378 -->

`copy_behavior` creates a new child genome with copied field names, source island id, source genome id and parent genome id. It never mutates the source genome row. The test copies a strategy field and confirms source bytes stay unchanged while child lineage names the transfer.

## 4. Agent harness and runs

### 4.1 Atomic run model

#### TDD-4.1.1 One-paper run scheduler
<!-- id: TDD-4.1.1 | implements: RN-01 | code: src/research_agent/runs/scheduler.py#create_run | tests: tests/runs/test_scheduler.py | status: pending:#378 -->

`create_run` requires one paper id, one island id, one genome version and one run seed. It rejects missing or multi-paper inputs before any provider call. The test submits zero, one and two papers and verifies only the one-paper request creates a run.

#### TDD-4.1.2 Harness tool policy
<!-- id: TDD-4.1.2 | implements: RN-02 | code: src/research_agent/runs/harness.py#dispatch_tool_call | tests: tests/runs/test_harness_tools.py | status: pending:#378 -->

`dispatch_tool_call` builds allowed schemas from the genome and supports paper_text, related_papers, capture_note, feedback_context, cost_state and submit_reading. Calls outside the allowed set append a refused tool event and perform no side effect. The test permits one declared tool and refuses an undeclared tool.

#### TDD-4.1.3 Run event trace
<!-- id: TDD-4.1.3 | implements: RN-03 | code: src/research_agent/runs/events.py#append_run_event | tests: tests/runs/test_events.py | status: pending:#378 -->

`append_run_event` writes immutable events for run_started, model_call, tool_call, note, reading_submitted, run_failed and run_completed. Paid and scarce events require a linked cost receipt id or an unsettled marker. The test forces a mid-run failure and checks prompt, events, status and cost total remain queryable.

#### TDD-4.1.4 Reading submission contract
<!-- id: TDD-4.1.4 | implements: RN-04 | code: src/research_agent/runs/readings.py#validate_reading_submission | tests: tests/runs/test_readings.py | status: pending:#378 -->

`validate_reading_submission` requires summary, claims, evidence references, objections, related papers and idea seeds with configured bounds. It rejects paper-text claims without evidence references. The test rejects missing fields and accepts a complete reading with evidence references.

#### TDD-4.1.5 Run page projection
<!-- id: TDD-4.1.5 | implements: RN-05 | code: src/research_agent/runs/projections.py#build_run_projection | tests: tests/runs/test_projection.py | status: pending:#378 -->

`build_run_projection` returns metadata, genome summary, prompt hash, event-ordered tool calls, tool outputs, costs, notes and final reading. Missing artifacts become explicit missing rows. The test seeds tool calls and confirms order and claim-to-evidence links.

#### TDD-4.1.6 Trace authority
<!-- id: TDD-4.1.6 | implements: RN-06 | code: src/research_agent/runs/projections.py#trace_authority_view | tests: tests/runs/test_trace_authority.py | status: pending:#378 -->

`trace_authority_view` derives conduct, tools, timing and costs only from harness events and cost receipts, not from agent prose. Agent prose is rendered as content only. The test stores prose claiming an unmade tool call and confirms no such call appears in conduct.

## 5. Cost receipts

### 5.1 Cost attached to everything

#### TDD-5.1.1 Cost receipt writer
<!-- id: TDD-5.1.1 | implements: CT-01 | code: src/research_agent/costs/receipts.py#record_cost_receipt | tests: tests/costs/test_receipts.py | status: pending:#378 -->

`record_cost_receipt` writes owner id, parent id, action type, unit type, quantity, amount, currency, provider, estimate flag and settlement state. Ingestion, model, tool, reading, evolution and chat services call it for paid or scarce work. The test runs one action of each type and checks a linked receipt exists.

#### TDD-5.1.2 Cost-aware projections
<!-- id: TDD-5.1.2 | implements: CT-02 | code: src/research_agent/costs/projections.py#attach_cost_summary | tests: tests/costs/test_projections.py | status: pending:#378 -->

`attach_cost_summary` adds settled total, unsettled receipt count and cost-per-useful-feedback when feedback exists. Paper, island, genome, run, evolution and chat projections call it. The test seeds settled and unsettled receipts and checks displayed totals and unavailable markers.

#### TDD-5.1.3 Evolution cost policy
<!-- id: TDD-5.1.3 | implements: CT-03 | code: src/research_agent/evolution/selection.py#select_survivors | tests: tests/evolution/test_cost_policy.py | status: pending:#378 -->

`select_survivors` computes usefulness bands first, uses cost only inside the same band and rejects genomes exceeding configured island budget. The evolution record stores usefulness and cost decisions separately. The test proves a useful expensive genome beats a cheap bad genome and an over-budget genome is refused.

#### TDD-5.1.4 Cost rollup ledger
<!-- id: TDD-5.1.4 | implements: CT-04 | code: src/research_agent/costs/rollups.py#sum_cost_scope | tests: tests/costs/test_rollups.py | status: pending:#378 -->

`sum_cost_scope` traverses receipt parent links, counts each receipt id once and treats aggregate receipts as parents whose child receipts are explanatory rather than additional charges. Inconsistent graphs return unavailable. The test builds nested receipts and confirms no double count.

## 6. Feedback and rapid evolution

### 6.1 Live genome movement

#### TDD-6.1.1 Feedback service
<!-- id: TDD-6.1.1 | implements: EV-01 | code: src/research_agent/feedback/service.py#record_feedback | tests: tests/feedback/test_service.py | status: pending:#378 -->

`record_feedback` validates target kind and id, stores signal, optional note, island scope and timestamp, and exposes accepted rows through `feedback_for_evolution`. The test records valid paper, reading, run, idea and chat targets, rejects invalid targets and checks evolution input.

#### TDD-6.1.2 Evolution threshold runner
<!-- id: TDD-6.1.2 | implements: EV-02 | code: src/research_agent/evolution/thresholds.py#maybe_run_evolution | tests: tests/evolution/test_thresholds.py | status: pending:#378 -->

`maybe_run_evolution` compares island feedback count and run count with configured thresholds. When crossed, it scores recent genomes from feedback, reading completion, trace health, cost and island preferences. The test crosses the feedback threshold and confirms a generation record appears without citation outcomes.

#### TDD-6.1.3 Atomic generation record
<!-- id: TDD-6.1.3 | implements: EV-03 | code: src/research_agent/evolution/cycle.py#commit_generation | tests: tests/evolution/test_cycle.py | status: pending:#378 -->

`commit_generation` writes survivor, child and retired genome decisions with parent links and reason codes in one transaction. A failure rolls back all lineage rows for the generation. The test injects a mid-commit failure and confirms no partial lineage appears.

#### TDD-6.1.4 Evolution activity projection
<!-- id: TDD-6.1.4 | implements: EV-04 | code: src/research_agent/evolution/projections.py#build_generation_activity | tests: tests/evolution/test_projection.py | status: pending:#378 -->

`build_generation_activity` returns new, retained and retired genomes with run counts, feedback totals, cost totals and links to genome detail and runs. The island page includes this projection. The test seeds a generation and checks lineage links are present.

## 7. Pages and chat

### 7.1 Visible surfaces

#### TDD-7.1.1 Visible route families
<!-- id: TDD-7.1.1 | implements: UI-01 | code: front-end/src/App.tsx#Routed | tests: front-end/src/App.test.tsx | status: pending:#378 -->

`Routed` registers login, island, paper, run and chat route families and no separate rating or inspector shell. Navigation from an island links to papers, runs and chat. The test renders the route table and fails when an unexpected visible family is registered.

#### TDD-7.1.2 Paper cascade projection
<!-- id: TDD-7.1.2 | implements: UI-02 | code: src/research_agent/papers/projections.py#build_paper_cascade | tests: tests/papers/test_cascade.py | status: pending:#378 -->

`build_paper_cascade` orders paper metadata, island assignments, readings, runs, tool-call evidence, feedback and cost for display. Missing sections keep explicit unavailable state. The test seeds nested data and confirms cascade order and drill-down ids.

#### TDD-7.1.3 Chat answer service
<!-- id: TDD-7.1.3 | implements: UI-03 | code: src/research_agent/chat/answers.py#answer_question | tests: tests/chat/test_answers.py | status: pending:#378 -->

`answer_question` retrieves paper, island, genome, run, reading, feedback and cost data through their services, then returns linked references for supported claims or a no-support response. The test asks known and absent topics and checks linked answers or no-support output.

#### TDD-7.1.4 Chat non-authority
<!-- id: TDD-7.1.4 | implements: UI-04 | code: src/research_agent/chat/service.py#apply_chat_action | tests: tests/chat/test_non_authority.py | status: pending:#378 -->

`apply_chat_action` persists object changes only by calling paper, run, feedback, cost or evolution services. Chat transcript state is browser-local for the first release and cannot be an authoritative store. The test clears chat state and confirms durable swarm records remain.

#### TDD-7.1.5 Shared UI feedback action
<!-- id: TDD-7.1.5 | implements: UI-05 | code: front-end/src/feedback.ts#submitFeedback | tests: front-end/src/feedback.test.ts | status: pending:#378 -->

`submitFeedback` is the shared browser action used by island, paper, run and chat pages. It posts target kind, target id, signal, note and island scope to the feedback service and never stores a local-only vote. The test submits from each page fixture and checks the same request shape.
