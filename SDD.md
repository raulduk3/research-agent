# Current product specification

This document is the authority for current behavior, constraints and remaining gaps. Start here, then follow the feature's code and tests. [TDD.md](TDD.md) identifies the architecture and executable contracts. Historical decisions and evidence are optional reference, not prerequisites.

The first release is one cloud-hosted paper-reading swarm: current ingestion, island pages, paper drill-down, agent-run traces, rapid genome evolution, feedback and casual chat. The public storm entry opens into login, island, paper, run and chat page families. Chat history is disposable. Papers, assignments, genomes and lineage, completed readings, retained runs, feedback and cost receipts are durable. Failed attempts without readings expire after the retention window specified below.

The application source ceiling is below 30,000 nonblank, noncomment lines. Generated files, lockfiles, tests, specifications and vendored dependencies are excluded. Historical platform components, two separate front ends, rating-only workflows, historical citation forecasting, prediction-head qualification, Jev assessment, OCR, public publishing, model training and distributed clusters are outside the first release. Stale local data requires an explicit operator import.

Each feature has a stable requirement ID and its intended behavior, implementation owners, behavior tests and exact gap. `must` and `must not` are normative. A cited file establishes ownership, not complete implementation. `Gap: None.` means the entire feature has verification; every other gap stays open. Tests must exercise the owner and reject a concrete prohibited alternative. Field names and feature headings are checked by `bin/spec-check`.

A genome is a versioned agent configuration. An island owns its queue, genomes and reading activity. A run reads one paper under one genome. A reading contains summary, claims, evidence, objections, related papers and idea seeds. A cost receipt records paid or scarce work and its attribution. The storm is the current ingested paper stream.

## CP-01 Release manifest gate

The first release must ship one cloud-hosted swarm application with current ingestion, islands, genomes, agent runs, feedback evolution, cost receipts and the five visible pages.

- Behavior: When a release build is assembled, the build manifest admits only components serving ingestion, islands, genomes, runs, evolution, cost or one of the five visible pages. The manifest lists each component with exactly one admitted purpose. If a component has an unrelated purpose, packaging fails before assembly.

- Constraints: The image must copy `deploy/beta/requirements.txt`, `src/research_agent/__init__.py` and `src/research_agent/beta`. Dependency installation uses pinned requirements with `--require-hashes`.

- Code: [deploy/beta/Dockerfile](deploy/beta/Dockerfile).

- Tests: [tests/beta/test_deploy.py](tests/beta/test_deploy.py).

- Gap: The image-copy and pinned-dependency checks exist. Packaging has no component-purpose manifest or test planting an unrelated declared component and observing refusal. The current image recipe does not prove the live deployment uses it.

## CP-02 Source line budget

The first-release application source must stay below 30,000 nonblank, noncomment lines.

- Behavior: When the repository check runs, the check counts application source files and excludes tests, generated files, lockfiles, specifications and vendored dependencies. The check prints the counted total and the configured ceiling. If the counted total reaches the ceiling, the check fails and names the paths contributing to the excess.

- Code: [bin/check](bin/check).

- Tests: None.

- Gap: Application-only counting, the active-versus-historical counting boundary, ceiling enforcement and negative cases for counted excess and excluded material are absent.

## CP-03 Current-store admission

The runtime must ignore stale local data unless an operator imports it into the current store.

- Behavior: When the server starts or an ingestion pass runs, the runtime reads current store records and operator-imported records with receipts, not arbitrary files on disk. Each visible paper has a current ingestion receipt or import receipt. A record without current ingestion or import provenance is hidden from pages, chat, assignment and evolution.

- Constraints: `ensure_seed(db, now)` must initialize an empty configured SQLite store with the default swarm revision. The seed reads stored specification revisions and creates the baseline only when required.

- Code: [src/research_agent/beta/service.py](src/research_agent/beta/service.py) (`Swarm.prepare`), [src/research_agent/beta/spec.py](src/research_agent/beta/spec.py) (`ensure_seed`).

- Tests: [tests/beta/test_service.py](tests/beta/test_service.py), [tests/beta/test_spec.py](tests/beta/test_spec.py).

- Gap: Startup uses the configured store and does not scan historical directories. General import-provenance admission and the test planting stale files without import receipts are absent.

## CP-04 Prohibited component registry

The first release must not ship rating-only workflows, historical citation forecasting, prediction-head qualification, Jev assessment, OCR, model training, public publishing or distributed clusters.

- Behavior: When a route, job, worker or dependency is registered, registration is refused when the component exists only for a prohibited workflow. The route and job registries contain no prohibited component names. If a prohibited component is registered, startup fails and names that registration.

- Constraints: The active beta package must retain the checked import separation from the earlier Python platform. The image must continue copying only the source entries admitted by its current recipe.

- Code: [deploy/beta/Dockerfile](deploy/beta/Dockerfile).

- Tests: [tests/beta/test_deploy.py](tests/beta/test_deploy.py).

- Gap: The beta image and textual import checks exclude the historical package. A purpose-aware startup registry and prohibited-registration negative case are absent; source-directory exclusion cannot reject a prohibited workflow added inside beta.

## IG-01 Current ingestion pass

Ingestion must collect current paper metadata and available text into one server-side store.

- Behavior: When an ingestion pass starts, the pass fetches configured current sources, normalizes metadata, stores source links, stores text when available and records text failures. Each paper record has source, fetch time, metadata, text status and immutable source links. If a source fails, its failure is recorded while successful source records remain committed.

- Constraints: `parse_arxiv_feed(xml_text)` must return normalized `PaperEntry` records and quarantined-entry descriptions. `upsert_paper(db, entry, receipt_id, now)` must return `stored`, `updated` or `unchanged`.

- Code: [src/research_agent/beta/ingest.py](src/research_agent/beta/ingest.py) (`run_ingestion_pass`), [src/research_agent/beta/ingest.py](src/research_agent/beta/ingest.py) (`parse_arxiv_feed`), [src/research_agent/beta/papers.py](src/research_agent/beta/papers.py) (`upsert_paper`).

- Tests: [tests/beta/test_ingest.py](tests/beta/test_ingest.py).

- Gap: A newer paper version replaces source metadata, abstract/PDF URLs and passages on the same identity. Immutable per-version source-link history and its negative case are absent. Identity deduplication does not establish provenance history.

## IG-02 Resumable ingestion cursor

Ingestion must be resumable without duplicating paper records.

- Behavior: When an ingestion pass stops and later restarts, the restarted pass resumes from stored source cursors and upserts by canonical paper identity. Re-running a completed pass leaves one paper record per canonical paper identity. An ambiguous identity is quarantined and excluded from island assignment.

- Constraints: `run_ingestion_pass(db, spec, plan, *, fetch, clock, ...)` must persist progress per source/category. Continuation must alternate backlog progress with a scan starting at zero when `head_due` is set. `arxiv_fetcher(api, attempts=2)` must return a fetcher accepting category, result limit and start offset.

- Code: [src/research_agent/beta/ingest.py](src/research_agent/beta/ingest.py) (`run_ingestion_pass`), [src/research_agent/beta/ingest.py](src/research_agent/beta/ingest.py) (`arxiv_fetcher`).

- Tests: [tests/beta/test_ingest.py](tests/beta/test_ingest.py).

- Gap: None.

## IG-03 Paper projection rollup

Every paper record must roll up its island assignments, readings, agent runs, feedback and cost receipts.

- Behavior: When the paper page or chat requests a paper, the server assembles the paper record from stored paper, assignment, run, reading, feedback and cost tables. The paper page shows counts and links for each rollup group. If a projection group fails, the page marks it unavailable instead of presenting a partial group as complete.

- Constraints: `build_paper_projection(db, paper_id)` must return the stored paper with assignments, readings, runs, likes, cost summary and per-island costs. Unknown paper identity is rejected by the paper owner. Readings and run lists are bounded grouped queries, currently limited to 50 and 100 records respectively.

- Code: [src/research_agent/beta/projections.py](src/research_agent/beta/projections.py) (`build_paper_projection`), [src/research_agent/beta/projections.py](src/research_agent/beta/projections.py) (`Groups.rows`).

- Tests: [tests/beta/test_api.py](tests/beta/test_api.py).

- Gap: The grouped response reports failures in `unavailable`, and readings distinguish unavailable from empty. Assignment and run sections can still present failed groups as empty. Complete per-group browser refusal coverage is absent.

## IG-04 Text failure visibility

A paper must remain inspectable when text extraction fails.

- Behavior: When text extraction fails for an ingested paper, the paper record keeps metadata, source links, text failure category and assignment eligibility. The paper page shows the paper with text status failed and no fabricated text. When extraction fails, agents receive only metadata and available source links.

- Constraints: `fetch_full_texts(db, *, fetch, clock, owner_id, limit, ...)` must preserve the paper and abstract when HTML is missing, has no usable sections or raises a fetch failure.

- Code: [src/research_agent/beta/text.py](src/research_agent/beta/text.py), [src/research_agent/beta/text.py](src/research_agent/beta/text.py) (`fetch_full_texts`).

- Tests: [tests/beta/test_text.py](tests/beta/test_text.py).

- Gap: HTML failures preserve the abstract and `text_failure`, but retain `text_status=abstract_only`; PaperPage displays that status without the extraction reason. The specified failed status, visible reason and browser failure-state acceptance case are absent.

## IS-01 Island projection

Each island must have its own page with queue, papers, genomes, runs, readings, feedback totals and cost totals.

- Behavior: When a logged-in visitor opens an island page, the server returns the island projection with selected papers for future reference first, other papers and current runs next, and collapsed genome settings and evolution controls after the output. Manual paper selection belongs on the individual paper page. Paper output and current runs precede configuration, with section counts and drill-down links. If a section fails, the page keeps it visible as unavailable.

- Constraints: `build_island_projection(db, spec, island_id, budget)` must return island identity and state, budget figures, evolution switches, categories, keywords, agents, queue, papers, runs, readings, evolution and edits. IslandPage must render selected papers, other papers and current runs before the collapsed agent and evolution controls. These states must not be conflated. Nonqueue papers sort by kept status before assignment creation time and paper ID, before the bounded window is applied. Normal run briefs exclude failed attempts. A named failed papers/runs group shows local unavailable text rather than the ordinary empty state. The page also lists failed group names in an alert. `IslandPage` permits mutations only when `api.session.island` equals the returned island id. `EvolutionSwitches` posts `/api/v1/islands/{encodedIsland}/settings` with exactly one changed field, either `{evolution_enabled: boolean}` or `{mutation_enabled: boolean}`.

- Code: [src/research_agent/beta/projections.py](src/research_agent/beta/projections.py) (`build_island_projection`), [apps/swarm-web/src/pages/Island.tsx](apps/swarm-web/src/pages/Island.tsx) (`IslandPage`), [apps/swarm-web/src/components/EvolutionSwitches.tsx](apps/swarm-web/src/components/EvolutionSwitches.tsx) (`EvolutionSwitches`).

- Tests: [apps/swarm-web/src/App.test.tsx](apps/swarm-web/src/App.test.tsx), [tests/beta/test_api.py](tests/beta/test_api.py).

- Gap: The response contains readings, but the browser has no separate reading section. Queue is a count, not a list. Island feedback totals are absent. Failed evolution, queue and readings groups lack complete local unavailable displays. No projection-plus-browser test seeds all required sections and fails each section independently.

## IS-02 Island login session

Login must bind a visitor to one island without creating durable chat-session records.

- Behavior: When a visitor selects or enters an island login, the server issues an island-scoped browser session and stores no chat transcript for that login. Requests carry island scope, and durable storage has no chat transcript row for the login. If login is invalid, it is refused before any island data is shown.

- Constraints: `open_island_session(config, credential, now, island_id=None, known_islands=frozenset())` must return `Session(role, island_id, expires_at, token)` or a typed authorization failure. `read_session(config, token, now)` must verify the versioned bearer structure, HMAC signature and expiry before returning the island scope. Unknown islands raise `NotFound`; wrong credentials raise `Forbidden`; an unrecognized unscoped credential raises `Unauthenticated`. The operator credential yields operator scope. Invalid or expired tokens raise `Unauthenticated`.

- Code: [src/research_agent/beta/auth.py](src/research_agent/beta/auth.py) (`open_island_session`), [src/research_agent/beta/auth.py](src/research_agent/beta/auth.py) (`read_session`).

- Tests: [tests/beta/test_api.py](tests/beta/test_api.py).

- Gap: None.

## IS-03 Genome validation

Each genome must declare its prompt, island, model settings, allowed tools, reading strategy, scoring preferences and lineage metadata.

- Behavior: When a genome is created, imported or mutated, the genome validator requires every declared field and records parent references for non-founder genomes. The genome page and run records can display the exact genome version used. An invalid genome is rejected and cannot start runs.

- Constraints: `validate_genome(genome, where)` must validate the declared genome content and return its normalized mapping. `apply_spec(db, proposed, *, actor, now, ..., lineage=None)` must validate before recording a changed specification. A no-op must not create a revision; a dry run must report changes without persisting them. Model settings contain temperature and output-token limits. Allowed tools are a list without duplicates, contain only known tool names and include `submit_reading`.

- Code: [src/research_agent/beta/spec.py](src/research_agent/beta/spec.py) (`validate_genome`), [src/research_agent/beta/spec.py](src/research_agent/beta/spec.py) (`apply_spec`), [apps/swarm-web/src/components/GenomeCard.tsx](apps/swarm-web/src/components/GenomeCard.tsx) (`GenomeCard`).

- Tests: [tests/beta/test_spec.py](tests/beta/test_spec.py), [apps/swarm-web/src/components/GenomeCard.test.tsx](apps/swarm-web/src/components/GenomeCard.test.tsx).

- Gap: Scoring preferences are validated but do not affect evolutionary fitness. Missing-parent and malformed-ancestry rejection cases are incomplete. Field validation and immutable revisions do not establish those semantics.

## IS-04 Paper assignment

A paper assignment must choose one or more islands from metadata, current focus, feedback and genome demand.

- Behavior: When a paper becomes assignment-eligible, the assignment step stores island ids and reason codes, using a general island when evidence is sparse. The paper and island pages show assignment reason codes. If assignment evidence is insufficient, the paper goes to General with `assignment_uncertain`.

- Constraints: `assign_paper(db, spec, entry, islands_per_paper, now)` must score open islands, choose the capped leading candidates or General, and return newly inserted island ids. A keyword alone claims a paper only for an island watching no category.

- Code: [src/research_agent/beta/islands.py](src/research_agent/beta/islands.py) (`assign_paper`), [src/research_agent/beta/islands.py](src/research_agent/beta/islands.py) (`score_islands`).

- Tests: [tests/beta/test_ingest.py](tests/beta/test_ingest.py).

- Gap: Assignment reads categories, focus keywords and archive state. It does not read persisted feedback or active-genome demand. Tests changing those inputs and observing assignment are absent.

## IS-05 Cross-island genome transfer

Cross-island transfer must copy behavior through genome lineage rather than shared mutable prompts.

- Behavior: When evolution borrows behavior from another island, the system creates a child genome that cites the source island, source genome and copied field set. The child genome lineage shows the cross-island transfer. A failed transfer leaves all existing mutable prompts unchanged.

- Constraints: `mate_genomes(parent, mate, existing, seed)` must return a novel child content mapping with mutation description, or `None` when no offered child is novel.

- Code: [src/research_agent/beta/evolution.py](src/research_agent/beta/evolution.py) (`mate_genomes`), [src/research_agent/beta/evolution.py](src/research_agent/beta/evolution.py) (`maybe_run_evolution`).

- Tests: [tests/beta/test_evolution.py](tests/beta/test_evolution.py).

- Gap: Lineage records parent IDs, primary-parent version and a mating decision naming the other island. Complete copied-field sets and explicit source versions for every parent are absent, as is reconstruction coverage.

## RN-01 One-paper run scheduler

The atomic work unit must be one agent run reading one paper under one genome.

- Behavior: When the scheduler creates reading work, the scheduler creates a run with one paper id, one island id, one genome version and one run seed. Every run page names exactly one paper and one genome. Requests with missing or multiple papers are refused before model calls.

- Constraints: `create_run(db, *, spec, revision, provider, clock, paper_id, island_id, genome_id=None, seed=None)` must return one queued run id bound to one existing paper and one genome belonging to the island. Creation must calculate admission and bounded request estimates before provider execution. The row records paper/island/genome identity, genome version, specification revision, frozen genome JSON, seed, mode, prompt system/user text, SHA-256 prompt hash, provider model, limits and estimate. The owner derives limits from genome settings, reading mode, available passages and the budget plan, builds the prompt and fits calls to the cap and band. Selected context contains only the admitted selected papers for the same island.

- Code: [src/research_agent/beta/runs.py](src/research_agent/beta/runs.py) (`create_run`).

- Tests: [tests/beta/test_runs.py](tests/beta/test_runs.py).

- Gap: The single-paper row and unknown-paper, wrong-island and absent-provider refusals are verified. Missing-paper and multi-paper public request cases with no provider calls or queued rows are unproven.

## RN-02 Harness tool policy

The harness must expose a bounded tool set for paper text, related papers, note capture, feedback context, cost state and final submission.

- Behavior: When an agent run starts, the harness builds allowed tool schemas from the genome and refuses calls outside that set. The run page lists allowed tools and each attempted tool call. An undeclared tool call is refused and recorded without a side effect.

- Constraints: `dispatch_tool_call(ctx, call, offered)` must return a result mapping and a finished flag. The harness must expose only the tool schemas offered for the current call. It checks offered-tool membership, the bounded tool-call allowance and parsed arguments before executing the tool. Refused ordinary tools append a tool event and produce no tool side effect; submission remains available after the ordinary tool allowance. Paper retrieval returns bounded passage content and produces `paper_read` events for the passages actually returned.

- Code: [src/research_agent/beta/runs.py](src/research_agent/beta/runs.py) (`dispatch_tool_call`), [src/research_agent/beta/runs.py](src/research_agent/beta/runs.py) (`_run_tool`).

- Tests: [tests/beta/test_runs.py](tests/beta/test_runs.py).

- Gap: `feedback_context` returns selected papers and recent same-island readings, not persisted feedback signals or notes. No test changes feedback and checks the tool result. Malformed `submit_reading` JSON produces retry guidance without a tool-call event; universally logged refused attempts are not established.

## RN-03 Run event trace

Every agent run must store its prompt, model settings, tool trace, notes, final reading, status and cost receipts.

- Behavior: When a run starts, calls a tool, calls a model, submits or fails, the harness appends immutable run events and links each paid or scarce action to a cost receipt. Startup and heartbeats remove failed attempts without submitted readings after 24 hours, including their events and notes, while preserving cost receipts and completed readings. The run page can reconstruct retained runs from stored events. Expired failed attempts disappear without reducing recorded spending. If a run fails, its failed status, last committed event and cost total remain available during its 24-hour retention window.

- Constraints: `append_run_event(db, run_id, kind, payload, *, now, receipt_id=None, cost_state="none", locator=None)` must allocate the next run-local sequence and persist the event with its timestamp and optional evidence locator. The HTTP completion boundary must parse provider response shape inside the typed failure boundary. Provider configuration must parse `RESEARCH_AGENT_MODEL_TIMEOUT_SECONDS` as finite positive seconds, defaulting to 300. Unknown event kinds are refused. Its delete guard permits only events belonging to a failed run without a reading. Completed and reading-bearing traces remain protected. After a paid attempt, the run owner records and commits either a settled receipt for reported usage or an unsettled estimate for a typed failure before appending the model-call event. A transport timeout becomes `ModelCallFailed` after one request; automatic paid-request retries are not added because a timed-out request may already have completed remotely.

- Code: [src/research_agent/beta/runs.py](src/research_agent/beta/runs.py) (`append_run_event`), [src/research_agent/beta/models.py](src/research_agent/beta/models.py) (`ChatCompletionsClient.complete`), [src/research_agent/beta/runs.py](src/research_agent/beta/runs.py) (`sweep_interrupted_runs`), [src/research_agent/beta/runs.py](src/research_agent/beta/runs.py) (`dispatch_tool_call`), [src/research_agent/beta/config.py](src/research_agent/beta/config.py) (`_provider_timeout`).

- Tests: [tests/beta/test_runs.py](tests/beta/test_runs.py), [tests/beta/test_service.py](tests/beta/test_service.py).

- Gap: Startup marks all queued/running runs failed without checking another live owner or stale heartbeat. Duplicate executor exclusion and concurrent recovery tests are absent. Ordinary tools and reading submission do not all create linked receipts. Malformed submission arguments omit a tool-call event. Provider receipts and 24-hour failed-run retention are verified, not complete scarce-action coverage.

## RN-04 Reading submission contract

A reading must contain summary, claims, evidence references, objections, related papers and idea seeds.

- Behavior: When an agent submits a final reading, the submission validator requires the bounded reading fields and source references where claims depend on paper text. The paper page renders each field under the submitting run. An invalid reading is rejected and the run remains incomplete.

- Constraints: `validate_reading_submission(arguments, paper_id, passages)` must require summary, thesis quote, claims, objections, related papers and idea seeds, plus a Boolean keep decision. Thesis text must be found exactly in the stored abstract. Quote validation must compare evidence against stored passages and return a locator only when matching text is found. A structurally invalid submission must leave no accepted reading. The current bounds include a nonempty summary of at most 2,000 characters, thesis text of at most 1,000 characters, one to eight claims, claim text up to 600 characters and at most four evidence entries per claim. A claim depending on paper text cannot omit evidence entirely. Claim `cited` is true only if at least one evidence entry verified; an unmatched supplied quote remains visible as unverified rather than becoming support. The dispatch result identifies `accepted=False`, the validation error and the offending field, allowing a bounded later retry.

- Code: [src/research_agent/beta/runs.py](src/research_agent/beta/runs.py) (`validate_reading_submission`), [src/research_agent/beta/runs.py](src/research_agent/beta/runs.py) (`locate_quote`), [src/research_agent/beta/runs.py](src/research_agent/beta/runs.py) (`dispatch_tool_call`).

- Tests: [tests/beta/test_runs.py](tests/beta/test_runs.py).

- Gap: None.

## RN-05 Run page projection

The run page must show the cascade from run to tool calls to atomic evidence.

- Behavior: When a visitor opens a run page, the page leads with the submitted reading for a completed run or current status when no reading exists, followed by replay, genome, costs and notes in event order. The reading appears before diagnostics, and each final claim links to its cited evidence or is marked uncited. If an artifact is missing, the page reports its absence rather than substituting agent prose.

- Constraints: `build_run_projection(db, run_id, after_seq=0)` must return the stored run, its event-ordered replay, reading, frozen genome, paper, receipt details, cost summary and conduct. RunBody must place an available reading before the replay, genome and detailed cost sections. A run without a reading must lead with a clear queued, running, failed or completed-without-reading message. An unknown or expired run raises `NotFound`. Failed runs remain directly readable during retention even though normal run lists exclude them; maintenance removes only failed attempts without readings older than 24 hours. The `after_seq` cursor limits returned event rows to later sequence numbers. Without a reading, queued/running runs say that the reading has not been submitted yet, failed runs say that they failed without a reading, and completed runs say that no reading is stored. A run 404 forgets its remembered id and returns to the storm. Play advances one step every 1,600 milliseconds, stops at the final event, and supports pause and restart. A run with no events cannot replay fabricated steps. `PaperViewer` uses the current event's locator to select a stored section and mark its quotation, opens a PDF at a page-only locator, or keeps available metadata/abstract and a quotation when neither stored full text nor PDF exists.

- Code: [src/research_agent/beta/projections.py](src/research_agent/beta/projections.py) (`build_run_projection`), [apps/swarm-web/src/pages/Run.tsx](apps/swarm-web/src/pages/Run.tsx) (`RunBody`), [apps/swarm-web/src/pages/Run.tsx](apps/swarm-web/src/pages/Run.tsx) (`RunPage`), [apps/swarm-web/src/components/ReadingView.tsx](apps/swarm-web/src/components/ReadingView.tsx) (`ReadingView`).

- Tests: [apps/swarm-web/src/pages/Run.test.tsx](apps/swarm-web/src/pages/Run.test.tsx), [tests/beta/test_runs.py](tests/beta/test_runs.py).

- Gap: ReadingView displays quotations and verification labels but no per-claim locator or evidence navigation anchor. Claims without quotes say "no quote given", not the complete uncited/artifact state. Absent paper, genome, trace and grouped-query failures lack complete projection/browser negative cases. Existing replay locators and links to a run do not connect a final claim to its atomic evidence.

## RN-06 Trace authority

The harness must record run data independently of the agent's self-report.

- Behavior: When an agent describes its own behavior, the system displays conduct, tools, timing and costs from harness events only. A mismatch between agent prose and trace favors the trace on the run page. If authoritative trace data is missing, the disputed field is marked `trace_missing` rather than trusting the agent.

- Constraints: `trace_authority_view(events)` must derive tool calls, refused calls, passages read and timing from the harness event sequence. Reading summaries are rendered content and cannot add activity to that conduct record.

- Code: [src/research_agent/beta/projections.py](src/research_agent/beta/projections.py) (`trace_authority_view`).

- Tests: [tests/beta/test_runs.py](tests/beta/test_runs.py).

- Gap: Missing trace returns empty lists or null timing rather than `trace_missing`. The regression against invented tool activity does not prove the missing-authority state.

## CT-01 Cost receipt writer

Every paid or scarce action must create a cost receipt.

- Behavior: When the system performs ingestion, model inference, tool work, reading, evolution or chat retrieval, the actor records owner id, parent id, unit type, quantity, cost amount when known and estimation flag when estimated. Each page can show cost totals from receipts rather than recomputing hidden counters. If accounting fails, the parent action is marked `cost_unsettled` and excluded from settled totals.

- Constraints: Paid run, chat and evolution receipts must commit before later trace, answer or generation work. `record_cost_receipt` must accept exactly `ingest`, `model_call`, `chat_retrieval`, `chat_answer` and `evolution`. `price_micros` must return the ceiling of input tokens multiplied by the configured input USD-per-million-token rate plus output tokens multiplied by the output rate. A usable response must record input plus output tokens at `price_micros`. Unknown actions raise `ValueError` before insertion. The schema constrains nonnegative amount, estimation to zero or one, and settlement to `settled` or `unsettled`. The test provider prices 1,000 input and 200 output tokens at 500 micro-dollars. `estimate_tokens` uses the ceiling of character count divided by three. Run estimates add 500 schema tokens to the prompt. Zero-based call index `i` adds `i * (max_output_tokens + 1000)` carried input tokens, then prices the full output allowance. `fit_run_to_cap` reduces normal calls until the estimate fits, retaining one call even if that minimum exceeds the cap. Explicit closing allowances add `final_calls - 1` calls and use the final output limit from the submission index onward. Missing provider usage sets `estimated=True` while the usable response remains settled. A failed run records estimated sent input tokens and their input-only price. Failed chat records its prompt estimate as quantity and its admitted full input/output estimate as amount. Failed evolution records the user-text estimate as quantity and its admitted system/user input plus 1,200 output tokens as amount. All three failures record estimated, unsettled receipts.

- Code: [src/research_agent/beta/costs.py](src/research_agent/beta/costs.py) (`record_cost_receipt`), [src/research_agent/beta/budget.py](src/research_agent/beta/budget.py) (`estimate_run_micros`), [src/research_agent/beta/runs.py](src/research_agent/beta/runs.py) (`_drive`), [src/research_agent/beta/runs.py](src/research_agent/beta/runs.py) (`dispatch_tool_call`).

- Tests: [tests/beta/test_costs.py](tests/beta/test_costs.py), [tests/beta/test_budget.py](tests/beta/test_budget.py), [tests/beta/test_runs.py](tests/beta/test_runs.py).

- Gap: The admitted ledger actions are ingest, model_call, chat_retrieval, chat_answer and evolution. General tool and reading receipt actions are absent. Failed cited-paper fetch, HTML extraction and final submission do not each have complete dedicated receipt coverage. Parent-wide `cost_unsettled` on accounting failure has no uniform representation. Provider-attempt rollback tests do not prove every scarce action. HTML request receipts are covered by text tests, but complete caller accounting is not established.

## CT-02 Cost-aware projections

Paper, island, genome, run, evolution and chat views must show cost beside activity.

- Behavior: When a view renders an activity count or generated answer, the view includes settled cost, unsettled cost count and cost-per-useful-feedback where feedback exists. Cost appears beside papers read, runs, readings, genome lineage and chat answers. If cost cannot be read, the view marks it unavailable instead of showing zero.

- Constraints: `attach_cost_summary` must return `state=available` with `settled_micros`, `unsettled_micros`, `unsettled_count`, `receipt_count` and `estimated_count`. A SQLite query error must yield only `state=unavailable`, rather than an available zero. Estimated settled charges remain in settled totals; unsettled estimates stay separate.

- Code: [src/research_agent/beta/costs.py](src/research_agent/beta/costs.py) (`attach_cost_summary`), [src/research_agent/beta/projections.py](src/research_agent/beta/projections.py) (`build_run_projection`), [src/research_agent/beta/projections.py](src/research_agent/beta/projections.py) (`build_agent_projection`).

- Tests: [tests/beta/test_costs.py](tests/beta/test_costs.py), [tests/beta/test_api.py](tests/beta/test_api.py).

- Gap: Run top-level/nested costs, run briefs, island paper rows, per-island breakdowns and agent lists can combine settlement states. Agent detail has settled totals but no unavailable-query guard. Cost per useful feedback and generation settlement projections are absent. Chat exposes an answer amount and receipt IDs without an answer settlement summary. Mixed-settlement and unavailable browser cases are incomplete.

## CT-03 Evolution cost policy

Evolution must use cost only as a tie-breaker unless a genome exceeds a configured budget.

- Behavior: When evolution compares genome candidates, the selector ranks usefulness first, applies cost between candidates with equal usefulness band and rejects candidates over budget. The evolution record shows usefulness, cost and budget decisions separately. If a comparison fails, the cycle makes no survivor change for that comparison.

- Constraints: Paid proposals must be admitted against provider availability, budget mode, request estimate and `per_evolution_max_micros`, whose default is 20,000. The estimate prices system/user token estimates plus the 1,200-token proposal allowance. Monthly committed cost includes settled and unsettled receipts.

- Code: [src/research_agent/beta/evolution.py](src/research_agent/beta/evolution.py) (`maybe_run_evolution`), [src/research_agent/beta/budget.py](src/research_agent/beta/budget.py) (`admit_paid`).

- Tests: [tests/beta/test_evolution.py](tests/beta/test_evolution.py).

- Gap: Selection uses likes, completed-run counts and IDs. It has no usefulness bands, cost tie-break, per-genome budget exclusion or separately recorded comparison measures. Paid-proposal caps control requesting a proposal, not candidate spending. Useful-expensive versus cheap-poor and over-budget-candidate tests are absent.

## CT-04 Cost rollup ledger

Cost receipts must roll up through parent links without double counting.

- Behavior: When a cost total is requested, the cost service sums each receipt once through stored parent links and excludes child totals already represented by parent receipts. Paper, island and genome totals equal the receipt ledger for their scope. If reconciliation fails, the total is marked inconsistent and is not displayed as settled.

- Constraints: `sum_cost_scope` must sum each matching receipt row once. Budget commitment must include settled and unsettled receipt amounts. Its allowed scope columns are exactly `run_id`, `paper_id` and `island_id`. An unknown scope raises `ValueError` before SQL construction. Settled and unsettled amounts are summed separately; receipt and estimation counts include both settlement states. The two-run paper fixture proves a 10,000-micro-dollar settled paper total and the same island total. Both seeded island totals sum to 19,000, equal to the settled receipt ledger. This verifies flat scope columns rather than nested parent traversal. Failed-run cleanup leaves receipt rows intact, including `run_id`, `paper_id`, `island_id` and durable `genome_id`; deleting the diagnostic run therefore does not remove its spend from scope totals. Each queued or running run reserves `max(0, estimate_micros - sum(all run receipt amounts))`; completed and failed runs reserve nothing.

- Code: [src/research_agent/beta/costs.py](src/research_agent/beta/costs.py) (`sum_cost_scope`), [src/research_agent/beta/budget.py](src/research_agent/beta/budget.py) (`budget_state`).

- Tests: [tests/beta/test_costs.py](tests/beta/test_costs.py), [tests/beta/test_budget.py](tests/beta/test_budget.py).

- Gap: Totals filter flat run/paper/island scope columns instead of traversing parent links. The writer does not validate parent existence or prevent receipt parents. No consistency state or nested-parent double-counting negative case exists. Generic genome/version scopes remain absent, though durable genome attribution preserves failed-run spend. An evolution receipt can survive without its generation row; parent reconciliation must handle that case.

## EV-01 Feedback service

Feedback must be accepted on papers, readings, runs, ideas and chat answers.

- Behavior: When a visitor submits feedback, the server validates the target, records the signal, note, island scope and time, and exposes it to evolution. The target history and island feedback totals include the signal. Invalid feedback is rejected before evolution can read it.

- Constraints: The like endpoint must admit only `paper`, `run`, `reading`, `claim`, `idea` and `agent`. Storage must admit at most one like for `(island_id, target_kind, target_id)`. `likes_where` must project stored rows under `<kind>:<target-id>` keys, with count and giving islands in creation order. The giving island derives from authenticated session scope; an operator may name a permitted island. The API test permits a Quant like on a CS run and rejects missing runs, out-of-range claims, unknown agents, tool-call targets, mismatched island scope and unauthenticated requests.

- Code: [src/research_agent/beta/likes.py](src/research_agent/beta/likes.py) (`toggle_like`), [src/research_agent/beta/likes.py](src/research_agent/beta/likes.py) (`_resolve`), [src/research_agent/beta/likes.py](src/research_agent/beta/likes.py) (`points_of`).

- Tests: [tests/beta/test_api.py](tests/beta/test_api.py).

- Gap: Like rows have no signal or note; chat-answer targets, durable target history and island feedback totals are absent. Removing a like deletes its row. Bulk agent-point projections can multiply a paper like across repeated keep-readings, while selector points use an existential query. Consistent totals for that case are unproven.

## EV-02 Evolution threshold runner

Evolution must run after configured feedback or run-count thresholds without waiting for citation outcomes.

- Behavior: When an island reaches an evolution threshold, the cycle scores recent genomes from feedback, reading completion, trace health, cost and configured island preferences. The island page shows generation number, changed genomes and reason codes soon after threshold crossing. If a cycle cannot complete, it records a skipped reason and leaves active genomes unchanged. A skip does not consume completed-run progress. Due cycles retry on the heartbeat without manual input after a fifteen-minute cooldown.

- Constraints: Enable must be a boolean. Threshold and population cap must be whole numbers of at least one, excluding booleans. The genome is validated and must not repeat existing content. Evolution defaults are `enabled=True`, `runs_threshold=6` and `max_agents_per_island=6`. Unknown names are refused. The settings test checks that an old feedback threshold is dropped while the run threshold remains, and rejects an unknown fitness setting and a zero population cap. Threshold counts include only completed runs whose `finished_at` is later than the latest committed generation timestamp for the island. Failed runs do not advance the threshold. A latest skipped cycle imposes a 15-minute retry cooldown unless forced. An admitted proposal request exposes only `propose_child`, uses temperature 0.9 and allows 1,200 output tokens. Unknown tools are filtered and `submit_reading` retained. Temperature is clamped to 0.1 through 1.2, output allowance to 256 through 2,000, prompt to 1,800 characters and strategy to 600.

- Code: [src/research_agent/beta/evolution.py](src/research_agent/beta/evolution.py) (`maybe_run_evolution`), [src/research_agent/beta/spec.py](src/research_agent/beta/spec.py) (`evolution_settings_from`), [src/research_agent/beta/evolution.py](src/research_agent/beta/evolution.py) (`_since_last`), [src/research_agent/beta/evolution.py](src/research_agent/beta/evolution.py) (`_proposal_from_model`).

- Tests: [tests/beta/test_evolution.py](tests/beta/test_evolution.py).

- Gap: Only completed-run thresholds and force trigger evolution. Feedback thresholds are accepted then discarded. Trace-health, completion, cost and preference-based usefulness scoring and feedback-trigger acceptance cases are absent. Run-count progress and heartbeat retries after skipped cycles are verified.

## EV-03 Atomic generation record

Each evolution cycle must create, retain or retire genomes with recorded reasons.

- Behavior: When evolution completes candidate scoring, the cycle stores survivor, child and retired genome decisions with parent links and reason codes. The genome lineage page can show what changed in that generation. If the transaction fails, the cycle is discarded atomically and no partial lineage appears.

- Constraints: The same seed must repeat the chosen child. Retirement candidates must exclude new-child parents and readers whose frozen cohort lacks a completed keep vote. Paid proposal receipts must commit before normalization, genome changes or generation insertion. Later generation failure must roll back revised lineage and generation storage without erasing the incurred charge. Cohort size uses the first run's stored limits with current planned size as fallback. A proposed retirement applies only to an eligible active nonparent. If every retiree is protected, the cycle records `pending_reading_cohort` and leaves population unchanged. Island scope and provider remain attached. A usable response is settled; typed provider failure retains an unsettled estimate and falls back to rule breeding.

- Code: [src/research_agent/beta/evolution.py](src/research_agent/beta/evolution.py) (`maybe_run_evolution`), [src/research_agent/beta/evolution.py](src/research_agent/beta/evolution.py) (`mate_genomes`), [src/research_agent/beta/evolution.py](src/research_agent/beta/evolution.py) (`_unfinished_readers`), [src/research_agent/beta/evolution.py](src/research_agent/beta/evolution.py) (`_proposal_from_model`).

- Tests: [tests/beta/test_evolution.py](tests/beta/test_evolution.py).

- Gap: None.

## EV-04 Evolution activity projection

The UI must make evolution visible as recent island activity.

- Behavior: When a visitor opens an island page after an evolution cycle, the page keeps agent lineage and management inspectable below paper output and runs in a collapsed section. It omits routine skipped-cycle and decision-history panels. A visitor can follow a genome from island page to genome detail to runs. If the evolution projection is unavailable, the page marks that state before hiding evolution data.

- Constraints: Generation activity must read one island's stored rows in descending generation-number order, defaulting to twenty records, and decode decision arrays. A failed agents group displays unavailable text without an empty searchable population.

- Code: [src/research_agent/beta/evolution.py](src/research_agent/beta/evolution.py) (`build_generation_activity`), [src/research_agent/beta/projections.py](src/research_agent/beta/projections.py) (`_evolution_steps`), [apps/swarm-web/src/components/EvolutionTree.tsx](apps/swarm-web/src/components/EvolutionTree.tsx) (`EvolutionTree`), [apps/swarm-web/src/components/GenomeCard.tsx](apps/swarm-web/src/components/GenomeCard.tsx) (`GenomeCard`).

- Tests: [tests/beta/test_evolution.py](tests/beta/test_evolution.py), [apps/swarm-web/src/components/EvolutionTree.test.tsx](apps/swarm-web/src/components/EvolutionTree.test.tsx), [apps/swarm-web/src/App.test.tsx](apps/swarm-web/src/App.test.tsx).

- Gap: Stored generation projection, collapsed lineage browser and unavailable-agent fixtures have separate tests. A seeded-generation integration case following island to genome to run and propagating unavailable lineage into the browser is absent. Cost/feedback completeness stays under CT-02.

## UI-01 Visible route families

The app must expose a public storm entry page and login, island, paper, run and chat page families for the first release.

- Behavior: When the route table is built, the app registers the public storm entry and the five session page families without a separate rating or inspector app shell. Navigation from an island links to paper, run and chat pages. If an unexpected route family is registered, startup fails and names it.

- Constraints: The client uses `VITE_API_ORIGIN`, or the current origin when unset, sends credentials and carries the stored bearer token after login. `Login` posts `/api/v1/login` with `{island, password}`, accepts only an island in the public storm response and returns only to a local URL. A later authenticated 401 clears the session and returns to login. It reads current readers from `agents.reading_now`, displays the stored grade and counts, and limits the globe's recent-paper input to 100. `useActivity` requests `GET /api/v1/public/activity?after={cursor}&limit=60`, advances the cursor to the maximum reported `last_id`, keeps the newest 400 steps and merges reported paper records. Storm and brief refresh every 15 seconds. Activity polls four seconds after success and twelve seconds after failure. Cleanup clears timers and ignores disposed replies. `useGet` retains ready data on network, 408, 429, server and malformed-success refresh failures. An initial failure reports failure; 403 or 404 clears previous data. A changed path loads without displaying the previous object, and obsolete replies cannot replace the current path.

- Code: [apps/swarm-web/src/App.tsx](apps/swarm-web/src/App.tsx) (`PAGES`), [apps/swarm-web/src/pages/Splash.tsx](apps/swarm-web/src/pages/Splash.tsx) (`Splash`).

- Tests: [apps/swarm-web/src/App.test.tsx](apps/swarm-web/src/App.test.tsx), [apps/swarm-web/src/api/client.test.ts](apps/swarm-web/src/api/client.test.ts), [apps/swarm-web/src/api/contracts.test.ts](apps/swarm-web/src/api/contracts.test.ts).

- Gap: The exact route list is tested, but production route construction has no family validator: `Page.family` is a string and unknown URL handling falls back to Splash. Supplying an unrelated family must cause startup rejection naming it; that behavior and negative case are absent.

## UI-02 Paper cascade projection

The paper page must lead with submitted readings and takeaways, followed by source metadata, islands, runs, tool calls, feedback and cost.

- Behavior: When a visitor opens a paper page, the server returns the paper projection with nested links down to each agent run and tool-call evidence. The title and visible readings precede metadata and diagnostics, with an explicit empty or unavailable reading state and links to run evidence. If a section is missing or unavailable, the page marks that state and omits its drill-down links.

- Constraints: A present empty array displays "No reading has been submitted for this paper yet." Missing or null `readings`, or an `unavailable` entry of `readings`, displays "The paper's readings are unavailable." A 404 forgets the remembered paper and returns to the storm. PaperPage uses its own-island assignment for one manual selection override, independent of the bounded island paper list. Readings have a separate limit of fifty and run briefs a limit of one hundred. Every returned reading remains visible independently of the run window, without expanding a run branch. `RunSteps` lists stored events in response order and links event index `i` to `/runs/{encodedRunId}?step={i+1}`, preserving the replay step query.

- Code: [apps/swarm-web/src/pages/Paper.tsx](apps/swarm-web/src/pages/Paper.tsx) (`PaperPage`), [src/research_agent/beta/projections.py](src/research_agent/beta/projections.py) (`build_paper_projection`).

- Tests: [apps/swarm-web/src/App.test.tsx](apps/swarm-web/src/App.test.tsx), [tests/beta/test_api.py](tests/beta/test_api.py).

- Gap: Readings distinguish unavailable from empty. Assignment/run sections and nested cascade readers can still treat failed groups as empty. Failed assignments, runs and nested groups need unavailable text and absent drill-downs without hiding readings, feedback or replay links.

## UI-03 Chat answer service

Chat must answer from stored paper, island, genome, run, reading, feedback and cost data.

- Behavior: When a visitor asks chat about the storm, an island, a paper, a run or an idea, chat retrieves stored swarm data, answers with linked references and states no support when retrieval finds none. Paper-dependent claims carry paper or run links. If chat fails, it returns a retriable error without an unsupported paper claim.

- Constraints: `answer_question` trims the message and rejects empty input or more than 2,000 characters. `_retrieve` starts with stored island context, resolves named island-scoped run and paper references, adds stored settled-cost and activity summaries for matching question words, and searches up to eight stored paper/reading hits. Retrieval-only answers assemble sentences from those records. Synthesis, when admitted, receives the question and stored records with no tools and a 2,500-token output bound. Submit appends a user turn, clears the composer and posts `/api/v1/chat` with exactly `{message: text}`. Refused turns invite a retry.

- Code: [src/research_agent/beta/chat.py](src/research_agent/beta/chat.py) (`answer_question`), [apps/swarm-web/src/components/ChatPanel.tsx](apps/swarm-web/src/components/ChatPanel.tsx) (`ChatPanel`).

- Tests: [tests/beta/test_chat.py](tests/beta/test_chat.py), [apps/swarm-web/src/components/ChatPanel.test.ts](apps/swarm-web/src/components/ChatPanel.test.ts).

- Gap: The server uses `supported=bool(links)`, so unrelated island context can mark an absent topic supported. Synthesized answers replace retrieval prose without checking each paper-dependent claim. ChatPanel does not inspect `supported`. Known/absent-topic, unsupported-synthesis refusal and visible no-support/retriable-state integration cases are absent. Submit, wait, navigation during a request and refusal browser interactions also lack coverage.

## UI-04 Chat non-authority

Chat must not be the durable source for run, paper, feedback, cost or evolution data.

- Behavior: When chat displays or accepts information about stored swarm objects, chat reads and writes through the underlying object services and persists no transcript as authority. Deleting browser chat state leaves paper, run, feedback, cost and evolution records unchanged. An operation that would store authority only in chat state is refused.

- Constraints: The browser's conversation consists only of the `turns` React state in `ChatPanel`. The only network mutation initiated by its submit handler is `/api/v1/chat` with the message. A model-call failure also falls back to retrieval and records an estimated unsettled receipt for the attempted answer.

- Code: [src/research_agent/beta/chat.py](src/research_agent/beta/chat.py) (`answer_question`), [apps/swarm-web/src/components/ChatPanel.tsx](apps/swarm-web/src/components/ChatPanel.tsx) (`ChatPanel`).

- Tests: [tests/beta/test_chat.py](tests/beta/test_chat.py), [apps/swarm-web/src/components/ChatPanel.test.ts](apps/swarm-web/src/components/ChatPanel.test.ts).

- Gap: Browser turns are transient, and the backend proves a distinctive question is not stored. No actual browser-to-HTTP persistence test clears conversation state and compares durable paper, run, feedback, cost and evolution records. Legitimate chat receipts must survive. Refusal of chat-only authority also lacks coverage.

## UI-05 Shared UI feedback action

The UI must allow feedback from island, paper, run and chat pages.

- Behavior: When a visitor views an object that accepts feedback, the page renders feedback controls that submit to the shared feedback service with island scope. Submitted feedback appears in the target history and island totals. If feedback fails, the page shows `feedback_unavailable` and does not fabricate a local vote.

- Constraints: Indexed claim/idea targets must resolve to an existing reading element. Island scope comes from the session client rather than an editable browser field. Only a successful response's `like.count` and `like.liked` replace the displayed state. Missing objects return 404, an unsupported target kind returns 422, a forged different island scope returns 403 and an unauthenticated caller returns 401. Agent likes are accepted only after the HTTP owner resolves the genome in the current specification.

- Code: [apps/swarm-web/src/components/Like.tsx](apps/swarm-web/src/components/Like.tsx) (`Like`), [src/research_agent/beta/likes.py](src/research_agent/beta/likes.py) (`toggle_like`), [apps/swarm-web/src/components/ChatPanel.tsx](apps/swarm-web/src/components/ChatPanel.tsx) (`ChatPanel`).

- Tests: [apps/swarm-web/src/App.test.tsx](apps/swarm-web/src/App.test.tsx), [tests/beta/test_api.py](tests/beta/test_api.py).

- Gap: Paper/run/reading/claim/idea likes and selected-agent island likes exist. ChatPanel has no answer feedback control and the service has no chat-answer target. Target history, island totals, page-level `feedback_unavailable` and a four-page persistence/failure test are absent. Submission refusal currently shows a server reason and preserves the stored vote.
