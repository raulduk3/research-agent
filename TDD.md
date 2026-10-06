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
- Several TDD items can implement one SDD requirement. Every item links to exactly one requirement, which lists that item in its own trace.
- Status is `implemented`, `pending` or `deviation`. Status belongs to the specific implementation contract. A working part can be implemented while another contract for the same requirement remains pending.
- Every contract states data or interface shape, state or transaction boundaries, failure behavior and verification. A pending contract states the exact missing behavior without an external work-tracking reference.

## Shared design

The first release has one server and one browser app. The active backend is `src/research_agent/beta/` with SQLite persistence. Its existing owners are `ingest`, `papers`, `islands`, `spec`, `runs`, `projections`, `budget`, `costs`, `likes`, `evolution`, `auth`, `chat`, `service` and `app`. The active browser is `apps/swarm-web/`. Browser routes render a public storm entry plus login, island, paper, run and chat pages. Persistence owns paper records, island state, genome versions, run events, readings, feedback and cost receipts. Browser chat state is disposable.

Implementation references below name existing owners or the gate that must acquire the check. A referenced test establishes only its asserted behavior. Pending items remain incomplete until their full requirement and negative cases are proven. [The implementation review](docs/DEVELOPMENT.md#current-implementation-review) records requirement evidence and remaining discrepancies in both directions.

## Contract coverage

| SDD requirement | Supporting TDD contracts |
| --- | --- |
| CP-01 | TDD-1.1.1, TDD-1.2.1, TDD-1.2.2 |
| CP-02 | TDD-1.1.2, TDD-1.2.3, TDD-1.2.4 |
| CP-03 | TDD-1.1.3, TDD-1.2.5, TDD-1.2.6 |
| CP-04 | TDD-1.1.4, TDD-1.2.7, TDD-1.2.8 |
| IG-01 | TDD-2.1.1, TDD-2.2.1, TDD-2.2.2, TDD-2.2.3 |
| IG-02 | TDD-2.1.2, TDD-2.2.4, TDD-2.2.5, TDD-2.2.6 |
| IG-03 | TDD-2.1.3, TDD-2.2.7, TDD-2.2.8 |
| IG-04 | TDD-2.1.4, TDD-2.2.9, TDD-2.2.10 |
| IS-01 | TDD-3.1.1, TDD-3.2.1, TDD-3.2.2, TDD-3.2.12, TDD-3.2.13, TDD-3.2.14 |
| IS-02 | TDD-3.1.2, TDD-3.2.3, TDD-3.2.4 |
| IS-03 | TDD-3.1.3, TDD-3.2.5, TDD-3.2.6, TDD-3.2.7, TDD-3.2.15 |
| IS-04 | TDD-3.1.4, TDD-3.2.8, TDD-3.2.9 |
| IS-05 | TDD-3.1.5, TDD-3.2.10, TDD-3.2.11 |
| RN-01 | TDD-4.1.1, TDD-4.2.1, TDD-4.2.2, TDD-4.2.3 |
| RN-02 | TDD-4.1.2, TDD-4.2.4, TDD-4.2.5, TDD-4.2.6 |
| RN-03 | TDD-4.1.3, TDD-4.2.7, TDD-4.2.8, TDD-4.2.9, TDD-4.2.10, TDD-4.2.22 |
| RN-04 | TDD-4.1.4, TDD-4.2.11, TDD-4.2.12, TDD-4.2.13 |
| RN-05 | TDD-4.1.5, TDD-4.2.14, TDD-4.2.15, TDD-4.2.16, TDD-4.2.19, TDD-4.2.20, TDD-4.2.21 |
| RN-06 | TDD-4.1.6, TDD-4.2.17, TDD-4.2.18 |
| CT-01 | TDD-5.1.1, TDD-5.2.1, TDD-5.2.2, TDD-5.2.3, TDD-5.2.4 |
| CT-02 | TDD-5.1.2, TDD-5.2.5, TDD-5.2.6, TDD-5.2.7 |
| CT-03 | TDD-5.1.3, TDD-5.2.8, TDD-5.2.9, TDD-5.2.10 |
| CT-04 | TDD-5.1.4, TDD-5.2.11, TDD-5.2.12, TDD-5.2.13 |
| EV-01 | TDD-6.1.1, TDD-6.2.1, TDD-6.2.2, TDD-6.2.3, TDD-6.2.4 |
| EV-02 | TDD-6.1.2, TDD-6.2.5, TDD-6.2.6, TDD-6.2.7, TDD-6.2.8 |
| EV-03 | TDD-6.1.3, TDD-6.2.9, TDD-6.2.10, TDD-6.2.11, TDD-6.2.12 |
| EV-04 | TDD-6.1.4, TDD-6.2.13, TDD-6.2.14, TDD-6.2.15, TDD-6.2.16, TDD-6.2.17 |
| UI-01 | TDD-7.1.1, TDD-7.2.1, TDD-7.2.2, TDD-7.2.3 |
| UI-02 | TDD-7.1.2, TDD-7.2.4, TDD-7.2.5, TDD-7.2.6 |
| UI-03 | TDD-7.1.3, TDD-7.2.7, TDD-7.2.8, TDD-7.2.9 |
| UI-04 | TDD-7.1.4, TDD-7.2.10, TDD-7.2.11, TDD-7.2.12 |
| UI-05 | TDD-7.1.5, TDD-7.2.13, TDD-7.2.14, TDD-7.2.15 |

## 1. Product cap

### 1.1 Release boundary

#### TDD-1.1.1 Release manifest gate
<!-- id: TDD-1.1.1 | implements: CP-01 | code: deploy/beta/Dockerfile | tests: tests/beta/test_deploy.py | status: pending -->

The beta image copies only the beta package and its pinned dependency closure. Packaging must validate admitted purposes, including the existing public storm entry. The current deployment tests check copy and import boundaries but do not plant an unrelated declared component; the manifest gate remains unbuilt.

#### TDD-1.1.2 Source line budget
<!-- id: TDD-1.1.2 | implements: CP-02 | code: bin/check | tests: none | status: pending -->

The existing repository gate is the owner of the source-budget check. It must count nonblank, noncomment application lines and reject a total at or above 30,000. That count and its negative-case test are not yet implemented.

#### TDD-1.1.3 Current-store admission
<!-- id: TDD-1.1.3 | implements: CP-03 | code: src/research_agent/beta/service.py#Swarm.prepare | tests: tests/beta/test_service.py | status: pending -->

Startup migrates the configured SQLite database and seeds its swarm specification. It does not scan historical data directories. Visible records must retain current ingestion or explicit import provenance; receipt admission has no dedicated negative-case test yet.

#### TDD-1.1.4 Prohibited component registry
<!-- id: TDD-1.1.4 | implements: CP-04 | code: deploy/beta/Dockerfile | tests: tests/beta/test_deploy.py | status: pending -->

The image copy boundary and beta import test exclude the historical platform from the deployed backend. A startup registry that refuses prohibited workflow registration remains unbuilt. The historical front end is not the swarm browser.

### 1.2 Detailed implementation contracts

#### TDD-1.2.1 Beta image source and dependency closure
<!-- id: TDD-1.2.1 | implements: CP-01 | code: deploy/beta/Dockerfile | tests: tests/beta/test_deploy.py | status: implemented -->

The image must copy `deploy/beta/requirements.txt`, `src/research_agent/__init__.py` and `src/research_agent/beta`. Its dependency installation uses the pinned requirements with `--require-hashes`.

`test_the_image_copies_the_beta_package_and_nothing_else_of_the_source` compares the complete COPY source list. It fails if the historical application package is added to that list.

`test_the_beta_requirements_are_the_lockfile_versions` checks declared dependency versions against `uv.lock` and rejects the listed numerical and training dependencies.

This implemented boundary describes the current image recipe. It does not supply the admitted-purpose manifest required by the encompassing requirement or prove the running deployment uses this image.

#### TDD-1.2.2 Admitted-purpose packaging gate
<!-- id: TDD-1.2.2 | implements: CP-01 | code: deploy/beta/Dockerfile | tests: tests/beta/test_deploy.py | status: pending -->

Packaging must reject a declared component whose purpose is outside the capped release. The current COPY allowlist is a source-directory boundary, not a component-purpose manifest.

No runtime or build manifest currently classifies routes, jobs and dependencies by their admitted purpose. The existing public storm entry belongs to the same browser application.

The missing negative case must plant an unrelated declared component and observe packaging refusal. Current deployment tests do not perform that experiment.

Pending work covers this gap. The image-copy tests remain evidence for their narrower item and must not be described as proof of the unbuilt manifest gate.

#### TDD-1.2.3 Application source counting boundary
<!-- id: TDD-1.2.3 | implements: CP-02 | code: bin/check | tests: none | status: pending -->

The repository check must count nonblank, noncomment application lines and reject a total at or above 30,000. Tests, generated files, lockfiles, specifications and vendored dependencies are excluded by the requirement.

`bin/check` is the existing aggregate gate. It currently orchestrates specification, Python and browser checks; it does not calculate this application-only total.

The active backend and browser must be distinguished from retained historical maintenance code when the counting boundary is implemented. No count or passing budget result is asserted here.

Pending work covers the missing check and its counting policy. This item names an existing gate owner rather than a nonexistent source-budget implementation.

#### TDD-1.2.4 Source ceiling rejection evidence
<!-- id: TDD-1.2.4 | implements: CP-02 | code: bin/check | tests: none | status: pending -->

The source ceiling needs a negative case that introduces counted application lines beyond the limit and observes a failing repository gate.

The test must also prove that excluded material does not inflate the count. A count printed by an ad hoc command would not establish enforcement.

There is no existing source-budget negative-case test to cite. Specification checker self-tests validate document structure and cannot substitute for this test.

This item keeps this verification work pending until the real gate counts the agreed files and catches the planted over-limit application.

#### TDD-1.2.5 Configured-store migration and idempotent seed
<!-- id: TDD-1.2.5 | implements: CP-03 | code: src/research_agent/beta/spec.py#ensure_seed | tests: tests/beta/test_spec.py | status: implemented -->

`ensure_seed(db, now)` must initialize an empty configured SQLite store with the default swarm revision. `Swarm.prepare()` migrates that database before invoking the seed owner.

The seed reads stored specification revisions and creates the baseline only when required. Specification history remains in `spec_revisions`, with monotonically numbered revisions.

`test_a_fresh_store_is_seeded_as_revision_one` checks the initial revision. `test_an_edit_that_changes_nothing_writes_no_revision` rejects spurious history for unchanged specification content.

These tests establish configured-store initialization and revision behavior. They do not prove the separate prohibition on importing arbitrary stale external data without provenance.

#### TDD-1.2.6 Historical-data admission and receipt proof
<!-- id: TDD-1.2.6 | implements: CP-03 | code: src/research_agent/beta/service.py#Swarm.prepare | tests: tests/beta/test_service.py | status: pending -->

Visible imported records must have current ingestion or explicit import provenance. Startup must not admit arbitrary stale local data into the active store.

`Swarm.prepare()` calls migration, seeding and recovery on the configured database. It contains no directory scan that imports historical datasets.

An explicit negative case that plants stale files and checks that they remain absent without import receipts is missing. Source inspection alone does not demonstrate the complete admission requirement.

Pending work covers this evidence gap. Current ingestion receipts and a configured database path must not be represented as a complete general import authorization mechanism.

#### TDD-1.2.7 Historical Python import exclusion
<!-- id: TDD-1.2.7 | implements: CP-04 | code: deploy/beta/Dockerfile | tests: tests/beta/test_deploy.py | status: implemented -->

The active beta package must retain the checked import separation from the earlier Python platform. The image must continue copying only the source entries admitted by its current recipe.

`test_the_beta_imports_nothing_from_the_earlier_platform` scans top-level import lines in beta Python modules and rejects imports naming another `research_agent` package.

The deployment dependency test also rejects its explicit set of training, numerical and PostgreSQL packages. Together these checks protect the current packaging boundary.

The import check is textual. It is not an exhaustive dynamic dependency analysis or the runtime component registry described by the encompassing requirement.

#### TDD-1.2.8 Prohibited workflow registration refusal
<!-- id: TDD-1.2.8 | implements: CP-04 | code: deploy/beta/Dockerfile | tests: tests/beta/test_deploy.py | status: pending -->

Registration of routes, jobs, workers or dependencies that exist only for prohibited workflows must be refused. A file retained for historical maintenance does not become active release scope.

The current application has no purpose-aware startup registry performing this refusal. A beta-only COPY list cannot detect a prohibited workflow newly added inside beta.

No existing test registers such a workflow and asserts startup refusal. The deployment tests cover package boundaries and declared dependencies only.

Pending work covers the missing registration contract. Retained historical tests cannot be used to claim that prohibited functionality is admitted or that this gate is implemented.

## 2. Ingestion and paper records

### 2.1 Current storm intake

#### TDD-2.1.1 Current ingestion pass
<!-- id: TDD-2.1.1 | implements: IG-01 | code: src/research_agent/beta/ingest.py#run_ingestion_pass | tests: tests/beta/test_ingest.py | status: pending -->

The ingestion pass normalizes current arXiv metadata, upserts canonical paper identities, assigns islands and records source failures and ingestion receipts. The service supplies the HTML text fetcher; failed extraction preserves metadata and source links. A newer version replaces stored source URLs and passages rather than retaining immutable per-version source links, so that observable remains unresolved.

#### TDD-2.1.2 Resumable ingestion cursor
<!-- id: TDD-2.1.2 | implements: IG-02 | code: src/research_agent/beta/ingest.py#run_ingestion_pass | tests: tests/beta/test_ingest.py | status: implemented -->

Canonical identity upserts prevent duplicate paper records. Migration 10 stores next_start and head_due per source category. Ingestion alternates continuation windows with head scans, counts quarantined source positions, and commits cursor advancement with stored papers. Interruption and reconnect tests reach every paper in a twenty-five-record feed without duplicates; source failure does not advance continuation.

#### TDD-2.1.3 Paper projection rollup
<!-- id: TDD-2.1.3 | implements: IG-03 | code: src/research_agent/beta/projections.py#build_paper_projection | tests: tests/beta/test_api.py | status: pending -->

The paper projection assembles assignments, readings, runs, likes and costs through grouped reads. Failed groups appear in unavailable. The browser must preserve that distinction instead of treating failed groups as empty. This display contract remains incomplete.

#### TDD-2.1.4 Text failure visibility
<!-- id: TDD-2.1.4 | implements: IG-04 | code: src/research_agent/beta/text.py | tests: tests/beta/test_text.py | status: pending -->

HTML fetch and ingestion retain the abstract, source metadata and text_failure reason when full text is unavailable. The current text_status remains abstract_only after failed HTML extraction, and PaperPage displays that status without the extraction reason. This differs from the specified failed status and visible failure detail. This observable remains incomplete.

### 2.2 Detailed implementation contracts

#### TDD-2.2.1 Normalized arXiv paper boundary
<!-- id: TDD-2.2.1 | implements: IG-01 | code: src/research_agent/beta/ingest.py#parse_arxiv_feed | tests: tests/beta/test_ingest.py | status: implemented -->

`parse_arxiv_feed(xml_text)` must return normalized `PaperEntry` records and quarantined-entry descriptions. `PaperEntry` carries canonical id, version, title, abstract, authors, primary and cross-list categories, publication/update times, abstract/PDF links and source.

The parser accepts the expected Atom structure and normalizes source identity before storage. A bad member can be quarantined without manufacturing an identity.

`test_parsing_reads_identity_metadata_and_links` asserts concrete normalized fields. `test_an_entry_without_a_readable_identity_is_set_aside` and `test_a_feed_that_is_not_plain_atom_is_refused` catch fabricated identities and unsupported feed shapes.

This boundary establishes the input record shape. Network acquisition, persistence and immutable source-link history are separate concerns.

#### TDD-2.2.2 Canonical paper upsert and abstract indexing
<!-- id: TDD-2.2.2 | implements: IG-01 | code: src/research_agent/beta/papers.py#upsert_paper | tests: tests/beta/test_ingest.py | status: implemented -->

`upsert_paper(db, entry, receipt_id, now)` must return `stored`, `updated` or `unchanged`. `papers.id` is the canonical key, so a later source version updates the same paper rather than adding another identity.

New records store `ingest_receipt_id` and `first_seen_at`. Known equal or older versions refresh `fetched_at`; newer versions replace metadata, reset text checking, replace passages and refresh the search index.

`test_rerunning_a_pass_and_a_newer_version_never_duplicate_a_paper` rejects duplicate identities across repeats and versions. `test_a_paper_without_an_abstract_stays_visible_with_no_invented_text` protects missing-text behavior.

This is implemented update behavior, not immutable metadata history. In particular, newer entries currently replace `abs_url` and `pdf_url`.

#### TDD-2.2.3 Immutable source-link history discrepancy
<!-- id: TDD-2.2.3 | implements: IG-01 | code: src/research_agent/beta/papers.py#upsert_paper | tests: tests/beta/test_ingest.py | status: pending -->

The source-link immutability clause remains binding. Updating a paper to a newer version must not be claimed to preserve immutable provenance merely because the canonical paper id stays unchanged.

The existing update statement replaces `source`, publication metadata, `abs_url` and `pdf_url`. Only the original ingestion receipt field remains on the existing paper row.

The duplicate-prevention test validates identity and version replacement; it does not prove historical source links are retained. No source-link history negative case is established here.

Pending work covers this implementation-contract discrepancy. Resolution must preserve or explicitly amend the normative requirement through the decision process; this item does not silently weaken it.

#### TDD-2.2.4 Durable source offset and atomic category commit
<!-- id: TDD-2.2.4 | implements: IG-02 | code: src/research_agent/beta/ingest.py#run_ingestion_pass | tests: tests/beta/test_ingest.py | status: implemented -->

`run_ingestion_pass(db, spec, plan, *, fetch, clock, ...)` must persist progress per source/category. `source_cursors` stores `next_start` and `head_due`, with nonnegative-offset and Boolean checks.

The adapter receives `(category, max_results, start)`. A successful category stores papers, assignments and its processed offset in the same commit; a source failure records its failure without advancing that offset.

`test_continuation_reaches_every_paper_after_an_interruption_and_reconnect` injects an insertion failure, rolls back, reconnects and eventually stores all 25 unique papers. `test_a_source_failure_does_not_advance_its_continuation` catches skipped windows after failure.

The cursor advances over processed source positions, including quarantined members, rather than only admitted papers. `test_quarantined_records_keep_their_source_positions` proves that distinction.

#### TDD-2.2.5 Head scans alongside backlog pagination
<!-- id: TDD-2.2.5 | implements: IG-02 | code: src/research_agent/beta/ingest.py#run_ingestion_pass | tests: tests/beta/test_ingest.py | status: implemented -->

Continuation must alternate backlog progress with a scan starting at zero when `head_due` is set. A short exhausted source page resets the continuation offset to the head.

The category loop computes `processed` from source positions and preserves `next_start` across head scans. Canonical upserts prevent repeated head entries from becoming duplicate papers.

`test_head_scans_admit_arrivals_and_revisions_while_the_backlog_continues` catches starvation of either current arrivals or backlog. `test_an_exhausted_cursor_returns_to_the_head` checks admission of a later new arrival.

Pagination guarantees operate within the configured admission and storage caps. Reaching the plan cap is a deliberate stop, not evidence that the source is exhausted.

#### TDD-2.2.6 Network request continuation parameters
<!-- id: TDD-2.2.6 | implements: IG-02 | code: src/research_agent/beta/ingest.py#arxiv_fetcher | tests: tests/beta/test_ingest.py | status: implemented -->

`arxiv_fetcher(api, attempts=2)` must return a fetcher accepting category, result limit and start offset. The HTTP query passes the supplied continuation start to arXiv.

The query restricts the category and requests submission-date descending order with the supplied maximum result count. Network failure becomes the ingestion boundary’s `SourceFailed` outcome.

`test_the_network_adapter_requests_the_continuation_window` inspects the real adapter request and catches an adapter that always sends `start=0` despite a nonzero caller offset.

The test uses HTTP transport substitution, not a live source request. It proves request construction without asserting availability or completeness of the live upstream feed.

#### TDD-2.2.7 Paper cascade response groups
<!-- id: TDD-2.2.7 | implements: IG-03 | code: src/research_agent/beta/projections.py#build_paper_projection | tests: tests/beta/test_api.py | status: implemented -->

`build_paper_projection(db, paper_id)` must return the stored paper with assignments, readings, runs, likes, cost summary and per-island costs. Unknown paper identity is rejected by the paper owner.

Readings and run lists are bounded grouped queries, currently limited to 50 and 100 records respectively. Each reading retains its run and genome identity, allowing navigation even when its run lies outside the displayed run window.

`test_the_island_paper_and_agent_views_carry_the_cascade_and_the_cost` asserts actual API response fields and nested activity. `test_a_run_started_through_the_api_can_be_watched_and_replayed` checks navigation data and trace contents.

This implemented assembly does not establish every missing-group presentation or settlement distinction. Those remain separate pending items.

#### TDD-2.2.8 Failed-group visibility through the paper browser
<!-- id: TDD-2.2.8 | implements: IG-03 | code: src/research_agent/beta/projections.py#Groups.rows | tests: tests/beta/test_api.py | status: pending -->

`Groups.rows(name, build)` catches SQLite query errors, records the group name in `unavailable`, and returns an empty list as the structural fallback. Consumers must consult the marker before interpreting that list as no records.

The paper response carries `unavailable` beside assignments, readings and runs. The reading section now distinguishes unavailable from genuinely empty readings.

Assignment and run sections can still display empty-state messages for unavailable groups. Complete negative-case coverage for each failed group is not established by the successful-cascade API test.

Pending work covers the remaining distinction. A structurally valid empty fallback must not soften the requirement to show failed sections as unavailable.

#### TDD-2.2.9 Full-text failure preserves source record
<!-- id: TDD-2.2.9 | implements: IG-04 | code: src/research_agent/beta/text.py#fetch_full_texts | tests: tests/beta/test_text.py | status: implemented -->

`fetch_full_texts(db, *, fetch, clock, owner_id, limit, ...)` must preserve the paper and abstract when HTML is missing, has no usable sections or raises a fetch failure.

The stored `text_failure` distinguishes `no_html_version`, `html_without_sections` and a fetch error. Each attempted HTML request creates its zero-cost ingestion receipt.

`test_a_paper_without_an_html_version_keeps_its_abstract_and_says_why` checks all three outcomes and verifies three request receipts. It also proves a newer version can be tried again.

The current records retain `text_status=abstract_only` for these failures. That fallback is proven behavior, not proof of the SDD requirement for a displayed failed status.

#### TDD-2.2.10 Failed status and reason presentation gap
<!-- id: TDD-2.2.10 | implements: IG-04 | code: src/research_agent/beta/text.py#fetch_full_texts | tests: tests/beta/test_text.py | status: pending -->

The encompassing requirement explicitly asks for failure visibility while preserving inspectable metadata and source links. A valid abstract must not erase the fact that extraction failed.

Current extraction-failure tests assert `abstract_only` status and a separate `text_failure` reason. The paper page displays `text_status` but does not expose that stored failure reason.

The existing passing failure test therefore demonstrates a mismatch with the required observable, rather than full conformity. There is no verified browser failure-state acceptance case for this clause.

Pending work covers the status-and-reason discrepancy. Preserve the current data while resolving the contract; do not rename the requirement to match the incomplete presentation.

## 3. Islands and genomes

### 3.1 Island ownership

#### TDD-3.1.1 Island projection
<!-- id: TDD-3.1.1 | implements: IS-01 | code: src/research_agent/beta/projections.py#build_island_projection | tests: apps/swarm-web/src/App.test.tsx | status: pending -->

The island projection provides queue, paper and run activity, agents, evolution and costs. Its bounded paper response puts selected references before recent arrivals. IslandPage renders selected papers, other papers and current runs before collapsed lineage and management controls. PaperPage derives its single selection override from its own assignment state, including outside the island window. Direct island reading content, feedback totals and complete unavailable-section handling remain incomplete; ordering alone does not satisfy the whole requirement.

#### TDD-3.1.2 Island login session
<!-- id: TDD-3.1.2 | implements: IS-02 | code: src/research_agent/beta/auth.py#open_island_session | tests: tests/beta/test_api.py | status: implemented -->

Login validates the named island credential and issues a signed island-scoped token. API authorization derives island scope from the token and refuses cross-island edits. Login tests verify that durable record tables remain unchanged; tampered and expired tokens are rejected. Chat transcript state remains in the browser.

#### TDD-3.1.3 Genome validation
<!-- id: TDD-3.1.3 | implements: IS-03 | code: src/research_agent/beta/spec.py#validate_genome | tests: tests/beta/test_spec.py | status: pending -->

Genome validation requires prompt, model settings, tools, strategy and numeric scoring_preferences. apply_spec records immutable revisions and version history, with lineage managed separately from incoming content validation. Full non-founder lineage validation remains incomplete. Versioned research_methods and source metadata are validated by spec.py and covered in tests/beta/test_methods.py under decision 0038; GenomeCard displays effective methods separately from their provenance. Scoring preferences exist but do not yet determine the evolution scores required by EV-02.

#### TDD-3.1.4 Paper assignment
<!-- id: TDD-3.1.4 | implements: IS-04 | code: src/research_agent/beta/islands.py#assign_paper | tests: tests/beta/test_ingest.py | status: pending -->

Assignment scores category and keyword matches, stores reasons and falls back to General. Feedback and active-genome demand are not inputs to the current scorer. Those specified inputs remain unresolved; category tests do not prove them.

#### TDD-3.1.5 Cross-island genome transfer
<!-- id: TDD-3.1.5 | implements: IS-05 | code: src/research_agent/beta/evolution.py#mate_genomes | tests: tests/beta/test_evolution.py | status: pending -->

Cross-island mating creates a child with parent references and mutation metadata in a new spec revision. Source genomes stay unchanged. The lineage record must expose the copied field set and source version rather than rely on mutable prompts.

### 3.2 Detailed implementation contracts

#### TDD-3.2.1 Island activity projection and bounded lists
<!-- id: TDD-3.2.1 | implements: IS-01 | code: src/research_agent/beta/projections.py#build_island_projection | tests: tests/beta/test_api.py | status: implemented -->

`build_island_projection(db, spec, island_id, budget)` must return island identity and state, budget figures, evolution switches, categories, keywords, agents, queue, papers, runs, readings, evolution and edits.

The response derives paper and queue membership from assignments and excludes released papers. Queue candidates exclude papers with a nonfailed run on that island; returned paper rows retain selection actor, run count and source metadata. Nonqueue papers sort by kept status before assignment creation time and paper ID, before the bounded window is applied. Normal run briefs exclude failed attempts. `test_old_selected_papers_precede_new_arrivals_in_the_bounded_island_view` and `test_recent_failures_do_not_fill_normal_run_lists` prove those boundaries.

`test_the_island_paper_and_agent_views_carry_the_cascade_and_the_cost` rejects a response that loses the nested paper/run/agent relationship. `test_a_tightened_budget_stops_work_and_shows_on_every_page` checks blocked-budget visibility.

This item covers the assembled activity response. Complete per-generation feedback/cost summaries and every unavailable-section presentation are not implied by those assertions.

#### TDD-3.2.2 Island output ordering and missing activity distinctions
<!-- id: TDD-3.2.2 | implements: IS-01 | code: apps/swarm-web/src/pages/Island.tsx#IslandPage | tests: apps/swarm-web/src/App.test.tsx | status: implemented -->

IslandPage must render selected papers, other papers and current runs before the collapsed agent and evolution controls. Existing links continue to identify paper and run detail routes.

For papers and runs, an `unavailable` group marker selects an unavailable message; a successfully empty result selects the empty-state message. These states must not be conflated.

The tests `the island shows papers and current runs before agent and evolution configuration` and `empty island output distinguishes unavailable groups $unavailable before configuration` assert DOM order, live run identity and distinct messages.

This implemented browser ordering does not create missing feedback/evolution totals. It keeps the available output visible while the broader island contract remains independently assessed.

#### TDD-3.2.3 Stateless island credential exchange
<!-- id: TDD-3.2.3 | implements: IS-02 | code: src/research_agent/beta/auth.py#open_island_session | tests: tests/beta/test_api.py | status: implemented -->

`open_island_session(config, credential, now, island_id=None, known_islands=frozenset())` must return `Session(role, island_id, expires_at, token)` or a typed authorization failure.

An explicit island requires its own configured credential. Unknown islands raise `NotFound`; wrong credentials raise `Forbidden`; an unrecognized unscoped credential raises `Unauthenticated`. The operator credential yields operator scope.

`test_login_binds_an_island_to_its_own_credential_and_stores_nothing` submits wrong-island, unknown-island and unconfigured-island credentials, then checks a valid binding and unchanged durable record counts.

Tokens carry role, island and expiry in a signed payload. Credential exchange writes no session or chat transcript row; durable swarm state continues to belong to the underlying services.

#### TDD-3.2.4 Signed bearer validation and mutation scope
<!-- id: TDD-3.2.4 | implements: IS-02 | code: src/research_agent/beta/auth.py#read_session | tests: tests/beta/test_api.py | status: implemented -->

`read_session(config, token, now)` must verify the versioned bearer structure, HMAC signature and expiry before returning the island scope. Invalid or expired tokens raise `Unauthenticated`.

The payload contains `role`, `island` and `exp`. API mutation authorization derives island identity from the session rather than trusting a request body to select an arbitrary island.

`test_a_session_expires_and_a_tampered_token_is_refused` rejects altered and expired credentials. `test_an_island_session_edits_its_own_agents_and_nothing_beyond` exercises a forbidden cross-island write.

The configured operator bearer remains an explicit existing exception for operator commands. It is not a durable island chat session or a way for an island request to widen its scope.

#### TDD-3.2.5 Genome field and tool-policy validation
<!-- id: TDD-3.2.5 | implements: IS-03 | code: src/research_agent/beta/spec.py#validate_genome | tests: tests/beta/test_spec.py | status: implemented -->

`validate_genome(genome, where)` must validate the declared genome content and return its normalized mapping. Required content includes prompt, model settings, allowed tools, reading strategy and scoring preferences; legacy research-method input is handled separately.

Model settings contain temperature and output-token limits. Allowed tools are a list without duplicates, contain only known tool names and include `submit_reading`. Scoring preferences map string keys to numeric, non-Boolean values.

`test_an_invalid_agent_is_refused_with_the_field_named` catches invalid settings and tools. `test_a_new_agent_must_declare_every_field` rejects incomplete creation and accepts a complete new genome.

Presence and numeric validation of scoring preferences are implemented. Applying those values to evolutionary fitness is not established by this validator.

`unique_instructions` normalizes repeated instruction units in prompts, method instructions and reading strategies. Comparison folds prose whitespace but preserves case, negation, numbers, URLs and the exact bytes inside quoted literals, code and mathematical expressions. It recognizes generated reading-emphasis and strategy labels without stripping arbitrary user labels. Run assembly applies the same normalization across fields; execution normalizes legacy queued system prompts and records the actual transmitted prompt and its hash. Paper text and evidence messages are not rewritten.

`upgrade_methods` applies this validator to all current agents, including inactive agents and archived islands, preserving custom methods and activation flags. Changes create new versions; repeated upgrades are no-ops. Historical revisions, captured run genomes and completed traces remain unchanged. Existing size limits apply to complete combined content; overflow rejects the proposal rather than dropping a parent’s contribution.

#### TDD-3.2.6 Immutable revision and run genome snapshots
<!-- id: TDD-3.2.6 | implements: IS-03 | code: src/research_agent/beta/spec.py#apply_spec | tests: tests/beta/test_spec.py | status: implemented -->

`apply_spec(db, proposed, *, actor, now, ..., lineage=None)` must validate before recording a changed specification. A no-op must not create a revision; a dry run must report changes without persisting them.

Changes append `spec_revisions` and increment the version of altered genome content. Revision rows have database update/delete guards. Runs separately store their genome JSON, genome version and specification revision.

`test_an_edit_that_changes_nothing_writes_no_revision` and `test_a_dry_run_reports_the_changes_and_writes_nothing` catch unwanted writes. `test_editing_an_agent_makes_a_new_version_and_leaves_the_others_alone` checks scoped version changes.

The run test `test_an_edit_after_a_run_does_not_change_what_the_run_was` provides additional evidence for snapshot preservation. Current edits cannot rewrite the genome presented for an earlier run.

#### TDD-3.2.7 Scoring effect and lineage completeness boundary
<!-- id: TDD-3.2.7 | implements: IS-03 | code: src/research_agent/beta/spec.py#validate_genome | tests: tests/beta/test_spec.py | status: pending -->

Every declared genome field must retain its required semantics, and non-founder genomes must have the required lineage. Validating a numeric scoring-preference mapping does not prove those preferences influence selection.

The validator returns lineage for the revision owner to manage; version and ancestry are populated by `apply_spec`. The current validation tests do not exhaust missing-parent or malformed-ancestry cases.

Current evolution does not implement the specified preference-based fitness computation. This is a behavior gap, not a missing `scoring_preferences` field.

The remaining contract requires direct ancestry rejection cases and an explicit reconciliation of scoring semantics. Until then this item remains pending independently of implemented field validation and immutable revisions.

#### TDD-3.2.8 Category assignment with durable reasons
<!-- id: TDD-3.2.8 | implements: IS-04 | code: src/research_agent/beta/islands.py#assign_paper | tests: tests/beta/test_ingest.py | status: implemented -->

`assign_paper(db, spec, entry, islands_per_paper, now)` must score open islands, choose the capped leading candidates or General, and return newly inserted island ids.

Primary-category matches contribute two points; up to two cross-listed categories and two focus keywords contribute additional weight. A keyword alone claims a paper only for an island watching no category. Assignment rows retain reason codes.

`test_assignment_routes_known_cross_topic_and_sparse_papers` checks known, cross-topic and fallback outcomes. `test_a_keyword_alone_does_not_pull_a_paper_onto_a_category_island` catches an overbroad keyword match.

Insertion uses the paper/island identity to avoid duplicate assignment records. Existing human selection is carried into newly inserted assignments rather than discarded.

#### TDD-3.2.9 Feedback and genome-demand assignment inputs
<!-- id: TDD-3.2.9 | implements: IS-04 | code: src/research_agent/beta/islands.py#score_islands | tests: tests/beta/test_ingest.py | status: pending -->

The encompassing assignment requirement includes feedback and active-genome demand alongside metadata and current focus. Those inputs must not disappear from the contract because category routing already works.

`score_islands(spec, entry)` currently reads island category patterns, keywords and archived state. It does not query persisted feedback or derive demand from the active genomes.

Category-routing tests therefore prove only the narrower scorer above. They cannot detect a scorer that ignores all feedback and genome-demand changes.

The missing contract is to reconcile and verify these declared inputs within the existing assignment owner. No alternate routing service or speculative scoring formula is introduced here.

#### TDD-3.2.10 Repeatable cross-island child construction
<!-- id: TDD-3.2.10 | implements: IS-05 | code: src/research_agent/beta/evolution.py#mate_genomes | tests: tests/beta/test_evolution.py | status: implemented -->

`mate_genomes(parent, mate, existing, seed)` must return a novel child content mapping with mutation description, or `None` when no offered child is novel.

The rule combines parent prompt content with the mate’s focus text, reading strategy, mean temperature and tool union, then applies a seeded single-field mutation. It builds new mappings rather than mutating source genomes.

Research methods are combined from both actual parents, including model-proposed children’s declared parents. `mix_methods` retains unique instruction units and source URLs in parent order, uses the maximum profile version and marks different domains as `mixed` without claiming specialist qualification. Mutation retains its parent’s methods. Final persistence cannot reset inherited methods to island defaults. Effective instructions participate in novelty comparison; source metadata alone does not make a new behavior.

`test_mating_keeps_both_method_contributions_once` checks both parents’ instructions and sources. `test_persisted_evolution_keeps_actual_parent_methods` catches a persistence-time island-default reset. `test_instruction_normalization_preserves_scientific_text`, `test_normalization_keeps_distinct_literal_whitespace`, `test_distinct_literal_whitespace_is_a_real_prompt_difference` and `test_run_prompt_removes_duplicates_across_instruction_fields` check literal normalized output and the stored provider prompt.

`test_mating_is_repeatable_and_never_repeats_an_existing_agent` catches nondeterministic or duplicate children. `test_the_run_threshold_breeds_a_child_from_the_island_and_another` checks cross-island parent identity in recorded decisions.

This implemented construction does not prove complete field-by-field provenance in the persisted lineage record. That remaining traceability contract is separate.

#### TDD-3.2.11 Copied-field and source-version lineage gap
<!-- id: TDD-3.2.11 | implements: IS-05 | code: src/research_agent/beta/evolution.py#maybe_run_evolution | tests: tests/beta/test_evolution.py | status: pending -->

Cross-island transfer must retain the source island, source genome and copied-field set so a later reader can reconstruct what behavior was transferred.

The generation owner records parent genome ids, a primary parent version, generation number, mutation metadata and a mating decision naming the other island. It does not record a complete copied-field set and explicit source version for every parent.

Current mating tests assert repeatability and parent links. They do not distinguish exact reconstruction from a lineage record containing only parent ids and one mutation description.

The missing contract is complete persisted transfer provenance. Immutable specification revisions are useful supporting evidence but do not themselves fill the omitted lineage fields.

#### TDD-3.2.12 Island projection displays paper output and current runs before configuration
<!-- id: TDD-3.2.12 | implements: IS-01 | code: apps/swarm-web/src/pages/Island.tsx#IslandPage | tests: apps/swarm-web/src/App.test.tsx | status: implemented -->

Opening `/islands/{island}` reads `GET /api/v1/islands/{encodedIsland}`. `build_island_projection` returns the island, agents, queue, papers, runs, readings, evolution decisions, edit records, budget/cost fields, switch fields and group names in `unavailable`. `IslandPage` renders title/focus, selected papers, other papers and current runs, followed by collapsed agents/evolution controls and cost summaries. An agent hash opens the controls disclosure.

Papers have a visible count and `PaperBranches` links to paper pages and their run/step cascade. Run rows link the genome label to `/runs/{encodedRunId}`, link the paper to `/papers/{encodedPaperId}`, and display stored status, creation time and reported cost. Papers and current runs occur in document order before `EvolutionSwitches` and `EvolutionTree`. A named failed papers/runs group shows local unavailable text rather than the ordinary empty state. The page also lists failed group names in an alert.

Summary cards display `cost_micros`, `budget_share`, `runs_remaining_today` and queue length. Missing numeric values or an absent queue are unreported. `App.test.tsx` checks output-before-configuration order, empty/unavailable paper/run cases and missing summaries. `test_the_island_paper_and_agent_views_carry_the_cascade_and_the_cost` in the HTTP suite checks returned queue, readings, run and agent data and the cost fields.

#### TDD-3.2.13 Own-island controls reload stored settings and paper selection
<!-- id: TDD-3.2.13 | implements: IS-01 | code: apps/swarm-web/src/components/EvolutionSwitches.tsx#EvolutionSwitches | tests: apps/swarm-web/src/App.test.tsx | status: implemented -->

`IslandPage` permits mutations only when `api.session.island` equals the returned island id. Other island pages remain readable with disabled evolution switches and no genome-edit, archive or selected-paper controls. The page does not use chat state as the owner of these settings.

`EvolutionSwitches` posts `/api/v1/islands/{encodedIsland}/settings` with exactly one changed field, either `{evolution_enabled: boolean}` or `{mutation_enabled: boolean}`. Success reloads the island projection and uses the server's returned state; refusal leaves the previous projection visible and reports that nothing changed. Mutation is disabled when island evolution is off, and a false `swarm_evolution_enabled` is explained as the operator's setting. Missing switch values display "not reported".

`LetGo` posts `/api/v1/papers/{encodedPaperId}/select` or `/deselect` with `{}` according to stored selection/release state. It disables selection actions during its request, reloads the owning page on success and reports a refusal without a local selection change. PaperPage finds its own island assignment, including `kept`, `released` and selection actor, and offers one override even when the paper is absent from the island window. `test_paper_selection_state_survives_deselection_outside_the_island_list` verifies stored selection across deselection and reselection. The displayed distinction between person and reader selection comes from stored paper fields.

Browser tests verify one-field switch payloads, refused flips, operator-off and absent values, selected-paper deselection/reselection, and another island's read-only page. HTTP tests cover the same switch ownership and public selection routes.

#### TDD-3.2.14 Complete all island sections and their failure projections
<!-- id: TDD-3.2.14 | implements: IS-01 | code: apps/swarm-web/src/pages/Island.tsx#IslandPage | tests: apps/swarm-web/src/App.test.tsx | status: pending -->

The island page must expose queue, papers, genomes, runs, readings, feedback totals and cost totals with section counts and drill-down links, while retaining paper output and current runs before configuration. A failed section must remain visibly unavailable.

The server already returns a separate `readings` group, but the browser `IslandView` and `IslandPage` do not consume it as a visible reading section. Queue is currently a summary count rather than a queue list. There is no island feedback-total section. Selected genome points are individual values, not the required island total. The page names failed groups globally and handles papers, runs and agents locally, but failed evolution/queue/readings groups do not all have a complete section-specific display. Routine generation-history panels are intentionally omitted; the remaining unavailable cases concern the sections still required by the island contract.

Existing projection tests seed and assert several server groups, and browser tests prove output ordering and local paper/run/agent failure handling. Completion requires the declared projection-plus-browser test with every required section seeded, including readings and feedback totals, and a failure case for each section. That full integration test and the missing visible sections are pending.

#### TDD-3.2.15 Genome detail separates effective methods from source provenance
<!-- id: TDD-3.2.15 | implements: IS-03 | code: apps/swarm-web/src/components/GenomeCard.tsx#GenomeCard | tests: apps/swarm-web/src/components/GenomeCard.test.tsx | status: implemented -->

Agent projections can carry `research_methods` with `version`, `domain`, `specialist`, effective `instructions` and source entries containing `title` and `url`. `GenomeCard` keeps the stored `genome.prompt` visible as its own content. When methods instructions are present, a separate Research methods disclosure shows those instructions. General methods explain their application to the island focus. A nested Method sources disclosure names the methods version and opens the source titles as external links. Source provenance is not inserted into the displayed prompt or effective instruction text.

`shows effective research methods separately from human source provenance` opens both disclosures and asserts literal method instructions, versioned source title and URL. `test_agent_api_exposes_methods_and_separate_source_metadata` in `tests/beta/test_api.py` checks `GET /api/v1/agents/cs-reader`, version/domain, an effective method instruction, the separate source URL and absence of source URLs from the prompt/instructions.

This item records the implemented browser/API display boundary. It does not establish the broader genome-creation requirement that every declared model setting, reading strategy and scoring preference is mandatory, or qualify the method sources. Run pages continue to display the genome version stored with that run.

## 4. Agent harness and runs

### 4.1 Atomic run model

#### TDD-4.1.1 One-paper run scheduler
<!-- id: TDD-4.1.1 | implements: RN-01 | code: src/research_agent/beta/runs.py#create_run | tests: tests/beta/test_runs.py | status: pending -->

Run creation binds one paper, island, genome version and seed, with budget admission before execution. Tests reject unknown papers, wrong-island genomes and absent providers; explicit zero-paper and multi-paper request cases remain unproven. Selected-paper context, frozen reading cohorts, bounded retries and pacing follow decisions 0033 and 0034 through the same scheduler, not a second work system.

#### TDD-4.1.2 Harness tool policy
<!-- id: TDD-4.1.2 | implements: RN-02 | code: src/research_agent/beta/runs.py#dispatch_tool_call | tests: tests/beta/test_runs.py | status: pending -->

Dispatch checks the genome tool policy, records refused attempts and supplies bounded paper retrieval, related-paper lookup, notes, cost state and final submission. feedback_context exists but returns selected papers and recent readings rather than feedback signals. The declared feedback input remains incomplete.

#### TDD-4.1.3 Run event trace
<!-- id: TDD-4.1.3 | implements: RN-03 | code: src/research_agent/beta/runs.py#append_run_event | tests: tests/beta/test_runs.py | status: pending -->

Immutable events retain prompt, model attempts, tool calls, notes, final reading and failures. The model boundary converts malformed responses to typed failures, and paid receipts commit before later trace or generation failures can roll them back. Run, chat and evolution regression tests prove receipt durability.

Normal paper, island and agent run lists exclude failed attempts immediately. Direct diagnostic links remain readable until cleanup. `prune_failed_runs(db, now)` removes failed runs with `finished_at` strictly older than 24 hours and no submitted reading, including events, notes and dependent likes/search records. Startup and heartbeat invoke maintenance. Queued, running and completed runs, and failed runs with readings, remain. Immutable receipts retain run and genome attribution after deletion; agent and island spend remain unchanged.

`test_failed_attempt_cleanup_preserves_receipts_and_current_attempts`, `test_cleanup_preserves_submitted_readings_and_immutable_event_boundaries`, `test_background_maintenance_removes_expired_failed_attempts` and `test_expired_failed_run_cleanup_preserves_agent_and_island_cost` in `tests/beta/test_evolution.py` cover these retention boundaries. General scarce tool and reading receipt coverage remains incomplete. Startup recovery and exclusive executor ownership are defined in TDD-4.2.9.

#### TDD-4.1.4 Reading submission contract
<!-- id: TDD-4.1.4 | implements: RN-04 | code: src/research_agent/beta/runs.py#validate_reading_submission | tests: tests/beta/test_runs.py | status: implemented -->

Submission validates bounded summary, claims, source references, objections, related papers and idea seeds. Quotes are checked against stored passages; unmatched quotes remain unverified and uncited. Missing required fields or evidence reject the submission without an accepted reading, and the run can accept a later corrected submission. ReadingView renders the submitted fields under the owning run.

#### TDD-4.1.5 Run page projection
<!-- id: TDD-4.1.5 | implements: RN-05 | code: src/research_agent/beta/projections.py#build_run_projection | tests: apps/swarm-web/src/pages/Run.test.tsx | status: pending -->

The run projection exposes the immutable genome snapshot, submitted reading, ordered events and evidence locators. RunPage leads with the reading or current status before replay, genome and costs; browser tests cover completed, live and failed ordering. ReadingView displays quotes but lacks per-claim evidence navigation. Missing artifacts and grouped read failures do not have complete explicit handling. These cascade contracts remain incomplete.

#### TDD-4.1.6 Trace authority
<!-- id: TDD-4.1.6 | implements: RN-06 | code: src/research_agent/beta/projections.py#trace_authority_view | tests: tests/beta/test_runs.py | status: pending -->

Conduct, tool activity and timing derive from harness events, while costs derive from receipts. A regression inserts reading prose claiming nonexistent tool calls and verifies that the projection reports only actual activity. Missing trace data currently produces empty lists or null timing rather than the specified trace_missing marker. This failure contract remains incomplete.

### 4.2 Detailed implementation contracts

#### TDD-4.2.1 Single-paper queued run identity
<!-- id: TDD-4.2.1 | implements: RN-01 | code: src/research_agent/beta/runs.py#create_run | tests: tests/beta/test_runs.py | status: implemented -->

`create_run(db, *, spec, revision, provider, clock, paper_id, island_id, genome_id=None, seed=None)` must return one queued run id bound to one existing paper and one genome belonging to the island.

The row records paper/island/genome identity, genome version, specification revision, frozen genome JSON, seed, mode, prompt system/user text, SHA-256 prompt hash, provider model, limits and estimate.

`test_a_run_is_one_paper_under_one_agent_and_refuses_anything_else` rejects unknown papers/genomes, a genome from another island and an absent provider before asserting the stored identity tuple.

This proves the single-paper row shape and those refusal paths. The explicit zero-paper and multi-paper input acceptance cases named by the SDD are not all exercised by that test.

#### TDD-4.2.2 Run reservation and immutable prompt context
<!-- id: TDD-4.2.2 | implements: RN-01 | code: src/research_agent/beta/runs.py#create_run | tests: tests/beta/test_runs.py | status: implemented -->

Creation must calculate admission and bounded request estimates before provider execution. The queued run’s estimate participates in subsequent budget admission.

The owner derives limits from genome settings, reading mode, available passages and the budget plan, builds the prompt and fits calls to the cap and band. Selected context contains only the admitted selected papers for the same island.

`test_a_queued_run_reserves_its_estimate_against_the_daily_budget` catches overbooking after queueing. `test_selected_papers_guide_new_prompt_and_exclude_deselected_or_other_islands` checks context scope and deselection.

`test_an_edit_after_a_run_does_not_change_what_the_run_was` checks the frozen genome snapshot. Cross-process execution ownership is defined separately in TDD-4.2.9.

#### TDD-4.2.3 Explicit malformed paper-cardinality acceptance cases
<!-- id: TDD-4.2.3 | implements: RN-01 | code: src/research_agent/beta/runs.py#create_run | tests: tests/beta/test_runs.py | status: pending -->

The SDD asks for a scheduler test rejecting zero-paper and multi-paper requests. The current API and function signatures represent one paper identity, and successful rows have one `paper_id`.

The existing identity test rejects a nonexistent string identity and a wrong-island genome. Those cases are not an explicit demonstration of missing or multiple paper inputs at the public request boundary.

The remaining verification must exercise those malformed request shapes and assert refusal before any provider call or queued row appears.

No multi-paper scheduler is proposed. This item records the precise evidence gap while retaining the implemented single-paper binding and admission owner.

#### TDD-4.2.4 Tool admission and bounded refusal result
<!-- id: TDD-4.2.4 | implements: RN-02 | code: src/research_agent/beta/runs.py#dispatch_tool_call | tests: tests/beta/test_runs.py | status: implemented -->

`dispatch_tool_call(ctx, call, offered)` must return a result mapping and a finished flag. It checks offered-tool membership, the bounded tool-call allowance and parsed arguments before executing the tool.

Refused results identify `tool_not_allowed`, `tool_call_limit` or `arguments_not_json`. Refused ordinary tools append a tool event and produce no tool side effect; submission remains available after the ordinary tool allowance.

`test_a_tool_the_agent_was_not_given_is_refused_and_does_nothing` detects unauthorized effects. `test_tool_calls_past_the_limit_are_refused_but_submission_still_ends_the_run` checks the terminal submission exception.

Malformed JSON arguments for `submit_reading` have a distinct existing path: the model receives retry guidance without an invalid tool-call event. This exception must not be described as universally logged attempts.

#### TDD-4.2.5 Bounded text access and final submission offering
<!-- id: TDD-4.2.5 | implements: RN-02 | code: src/research_agent/beta/runs.py#dispatch_tool_call | tests: tests/beta/test_runs.py | status: implemented -->

The harness must expose only the tool schemas offered for the current call. At the final submission stage it offers `submit_reading` alone and records the harness notice.

Paper retrieval returns bounded passage content and produces `paper_read` events for the passages actually returned. Large stored full text can be listed and read by tool rather than included wholesale in the initial prompt.

`test_the_last_model_call_offers_only_submission_and_the_notice_is_recorded` catches an unrestricted final call. `test_stored_text_too_long_for_the_prompt_is_listed_and_read_by_tool` checks the long-text path.

The successful tool result is bounded before returning to the model. These tests establish concrete tool limits, not a claim that every scarce tool action already has a dedicated cost receipt.

#### TDD-4.2.6 Feedback-context result and missing signals
<!-- id: TDD-4.2.6 | implements: RN-02 | code: src/research_agent/beta/runs.py#_run_tool | tests: tests/beta/test_runs.py | status: pending -->

The `feedback_context` tool currently returns `selected_papers`, `recent_readings` and an explanatory note. Recent readings are restricted to the current island, exclude the current run, and contain bounded agent, title and summary fields.

This is stored contextual material. The query does not return persisted likes, feedback signals or notes despite the tool’s feedback-oriented name.

The declared feedback-context requirement therefore needs reconciliation and a test that changes stored feedback and observes the intended tool result. Existing tool-policy tests cannot prove that semantic behavior.

The missing contract remains in the existing tool owner. This entry does not invent a second feedback store or an unimplemented integration.

#### TDD-4.2.7 Append-only event fields and paid-event guard
<!-- id: TDD-4.2.7 | implements: RN-03 | code: src/research_agent/beta/runs.py#append_run_event | tests: tests/beta/test_runs.py | status: implemented -->

`append_run_event(db, run_id, kind, payload, *, now, receipt_id=None, cost_state="none", locator=None)` must allocate the next run-local sequence and persist the event with its timestamp and optional evidence locator.

Unknown event kinds are refused. A model-call event requires a receipt id and a non-`none` cost state. `run_events` has run/sequence identity and an unconditional update guard; database checks restrict cost-state and locator-source values. Its delete guard permits only events belonging to a failed run without a reading. The maintenance owner separately enforces the 24-hour age cutoff; the database trigger itself does not enforce age. Completed and reading-bearing traces remain protected.

`test_a_model_call_event_cannot_be_written_without_its_receipt` catches missing payment linkage and unknown event names. `test_a_run_records_every_step_in_order_with_receipts_and_locators` checks concrete order and evidence fields.

`_Context.event` commits each appended event. This establishes incremental trace durability, not atomicity of an entire multi-call run.

#### TDD-4.2.8 Malformed provider responses preserve request receipts
<!-- id: TDD-4.2.8 | implements: RN-03 | code: src/research_agent/beta/models.py#ChatCompletionsClient.complete | tests: tests/beta/test_runs.py | status: implemented -->

The HTTP completion boundary must parse provider response shape inside the typed failure boundary. Invalid choices/messages/tool-call shapes or invalid token counts become `ModelCallFailed`, not uncaught parser exceptions.

After a paid attempt, the run owner records and commits either a settled receipt for reported usage or an unsettled estimate for a typed failure before appending the model-call event.

`test_a_malformed_paid_reply_keeps_its_receipt_after_run_failure` exercises invalid messages and usage, then forces model-event insertion failure. It proves receipts survive and the run records either `model_call_failed` or `harness_error`.

The successful-response case in the same test preserves a settled charge through later event failure. This repair does not imply that all free-but-scarce tool actions have receipts.

#### TDD-4.2.9 Startup recovery and execution ownership
<!-- id: TDD-4.2.9 | implements: RN-03 | code: src/research_agent/beta/runs.py#sweep_interrupted_runs | tests: tests/beta/test_runs.py | status: implemented -->

Each executor acquires a nonblocking exclusive OS advisory lock before reading the run state. The lock remains held through all provider calls, committed events, receipts and terminal status. A competing executor returns without a provider request. All executors must use the same OS user or compatible file permissions. In-memory databases are rejected. The lock directory is the resolved SQLite filename plus `.run-locks`; each persistent filename is the SHA-256 digest of the run id. Lock files are never unlinked while the store exists, so contenders use one inode.

`Swarm.prepare()` preserves queued work. Its sweep considers only running rows and obtains the same lock before conditionally marking an abandoned row failed with `interrupted_by_restart` and committing one terminal event. A live owner prevents recovery even during a long provider response. Kernel process exit releases ownership without a heartbeat timeout. The next heartbeat drives preserved queued runs before scheduling new work. Failed abandoned runs retain all committed trace and receipts and remain eligible for the existing paper retry policy.

`test_contested_queued_execution_pays_for_one_request`, `test_queued_owner_is_safe_before_running_transition`, `test_startup_preserves_queued_work`, `test_live_execution_survives_startup_and_duplicate_executor` and `test_crashed_executor_releases_ownership_for_recovery` in `tests/beta/test_runs.py` verify queue preservation, live startup safety, one paid receipt under contention and actual process-death recovery. `test_heartbeat_executes_queue_preserved_across_preparation` in `tests/beta/test_service.py` proves the preserved queue resumes.

This contract requires all executors to share one host kernel, the same resolved SQLite file and its adjacent lock directory. It does not support independent hosts, network filesystems or older executors that bypass ownership. Upgrade by stopping older executors before starting the new runtime. An interrupted in-flight provider request may have an unknown external charge; recovery preserves committed receipts and does not retry that request under the same run id.

#### TDD-4.2.10 Complete scarce-action trace and receipt coverage
<!-- id: TDD-4.2.10 | implements: RN-03 | code: src/research_agent/beta/runs.py#dispatch_tool_call | tests: tests/beta/test_runs.py | status: pending -->

Every paid or scarce run action must retain the trace and receipt linkage required by the encompassing requirement. Provider-attempt durability is one implemented subset of this rule.

The cost ledger currently admits ingestion, model calls, chat retrieval/answers and evolution. Ordinary bounded tools and reading submission do not all create their own receipt action.

The event-sequence tests prove stored tool activity and provider costs; they do not assert a receipt for every tool and reading action. There is also a documented omission of malformed submission argument events.

The remaining work must reconcile those specific action and trace cases without replacing the normative coverage clause with the narrower set that happens to be stored today.

#### TDD-4.2.11 Bounded reading fields and abstract thesis
<!-- id: TDD-4.2.11 | implements: RN-04 | code: src/research_agent/beta/runs.py#validate_reading_submission | tests: tests/beta/test_runs.py | status: implemented -->

`validate_reading_submission(arguments, paper_id, passages)` must require summary, thesis quote, claims, objections, related papers and idea seeds, plus a Boolean keep decision.

The current bounds include a nonempty summary of at most 2,000 characters, thesis text of at most 1,000 characters, one to eight claims, claim text up to 600 characters and at most four evidence entries per claim. Thesis text must be found exactly in the stored abstract.

`test_reading_validation_requires_every_field_and_evidence_for_text_claims` rejects missing fields, missing textual support and invalid stance. It also asserts bounded objection and idea-seed output.

The normalized reading includes thesis character offsets and strips surrounding text whitespace. Source inspection supplies the full field bounds; the named test covers its explicit missing-field/evidence cases, not every numeric boundary.

#### TDD-4.2.12 Quote matching and uncited claim representation
<!-- id: TDD-4.2.12 | implements: RN-04 | code: src/research_agent/beta/runs.py#locate_quote | tests: tests/beta/test_runs.py | status: implemented -->

Quote validation must compare evidence against stored passages and return a locator only when matching text is found. A claim depending on paper text cannot omit evidence entirely.

Each returned evidence object contains quote text, a verified Boolean and a locator or null. Claim `cited` is true only if at least one evidence entry verified; an unmatched supplied quote remains visible as unverified rather than becoming support.

`test_reading_validation_requires_every_field_and_evidence_for_text_claims` injects an invented quote and asserts `verified=False`, `cited=False`, and an explicitly non-paper-dependent uncited claim.

This proves honest citation status for supplied evidence. It does not claim semantic entailment between a matching quote and the agent’s interpretation of that quote.

#### TDD-4.2.13 Rejected submission and corrected retry persistence
<!-- id: TDD-4.2.13 | implements: RN-04 | code: src/research_agent/beta/runs.py#dispatch_tool_call | tests: tests/beta/test_runs.py | status: implemented -->

A structurally invalid submission must leave no accepted reading. The dispatch result identifies `accepted=False`, the validation error and the offending field, allowing a bounded later retry.

Accepted submission stores the normalized reading, appends the accepted tool result and a `reading_submitted` event, and returns the reading id with the finished flag.

`test_a_rejected_submission_leaves_the_run_open_for_a_corrected_one` sends an incomplete reading followed by a complete one. It asserts the rejected field, subsequent acceptance and exactly one persisted reading.

This contract covers parsed submission objects. Malformed JSON submission arguments follow the separate retry path described in the tool-dispatch item and must not be conflated with stored rejected-object events.

#### TDD-4.2.14 Run replay projection and cursor semantics
<!-- id: TDD-4.2.14 | implements: RN-05 | code: src/research_agent/beta/projections.py#build_run_projection | tests: tests/beta/test_runs.py | status: implemented -->

`build_run_projection(db, run_id, after_seq=0)` must return the stored run, its event-ordered replay, reading, frozen genome, paper, receipt details, cost summary and conduct. An unknown or expired run raises `NotFound`. Failed runs remain directly readable during retention even though normal run lists exclude them; maintenance removes only failed attempts without readings older than 24 hours.

The `after_seq` cursor limits returned event rows to later sequence numbers. Conduct is still calculated from the complete trace, so incremental polling does not rewrite the apparent history.

`test_replay_can_be_read_from_a_sequence_onward` checks the cursor. `test_an_edit_after_a_run_does_not_change_what_the_run_was` verifies that current genome edits do not alter the projected run snapshot.

The projection’s summary and receipt list support inspection. Its older aggregate display value can include unsettled amounts; settlement-aware presentation remains a separate pending cost item.

#### TDD-4.2.15 Reading-first run presentation with preserved replay
<!-- id: TDD-4.2.15 | implements: RN-05 | code: apps/swarm-web/src/pages/Run.tsx#RunBody | tests: apps/swarm-web/src/pages/Run.test.tsx | status: implemented -->

RunBody must place an available reading before the replay, genome and detailed cost sections. A run without a reading must lead with a clear queued, running, failed or completed-without-reading message.

The reading remains visible without opening a details element. The paper back-link, reading like action and replay step query remain available.

Tests `a completed run shows visible reading content before replay, genome and cost details` and `a $status run without a reading leads with its status before diagnostics` assert DOM order and status text.

The existing `a link to a step opens the replay there` test protects explicit step navigation. The display move does not change the run event ordering or provider execution.

#### TDD-4.2.16 Missing run artifacts remain an explicit gap
<!-- id: TDD-4.2.16 | implements: RN-05 | code: src/research_agent/beta/projections.py#build_run_projection | tests: tests/beta/test_runs.py | status: pending -->

The run page must report missing artifacts rather than substituting agent prose. Successful projection of an intact fixture does not prove every absent-paper, absent-genome or missing-trace state.

The implementation returns nullable stored artifacts in several cases, and the browser has specific empty states. Complete negative-case coverage of the required artifact failures is not established here.

The remaining tests must deliberately remove or make unavailable the relevant artifact and assert the resulting explicit response and presentation, including preservation of honest evidence navigation.

This item remains pending independently of implemented replay order, snapshots and reading-first layout. It does not authorize inventing replacement artifacts.

#### TDD-4.2.17 Conduct derived from harness events
<!-- id: TDD-4.2.17 | implements: RN-06 | code: src/research_agent/beta/projections.py#trace_authority_view | tests: tests/beta/test_runs.py | status: implemented -->

`trace_authority_view(events)` must derive tool calls, refused calls, passages read and timing from the harness event sequence. Reading summaries are rendered content and cannot add activity to that conduct record.

Tool and paper-read event payloads supply the observed action identities. Timing comes from stored event timestamps rather than an agent’s narrative of elapsed work.

`test_what_the_agent_says_it_did_is_not_what_the_run_page_reports` stores a summary claiming five nonexistent related-paper calls and complete paper reading. Conduct still contains only actual submission and the recorded abstract passage.

This is direct evidence against trusting self-report for activity. It does not establish the required explicit marker when the authoritative trace itself is missing.

#### TDD-4.2.18 Explicit missing-trace authority marker
<!-- id: TDD-4.2.18 | implements: RN-06 | code: src/research_agent/beta/projections.py#trace_authority_view | tests: tests/beta/test_runs.py | status: pending -->

The encompassing trace-authority requirement includes honest handling of unavailable trace data. Empty or absent authoritative evidence must not look like a verified account of no activity.

For an empty event sequence the current function returns empty activity collections and null timing. It does not produce a `trace_missing` marker.

The self-report rejection test exercises a present, valid trace. It cannot distinguish missing authoritative data from an intact trace containing no actions.

The remaining contract must define and assert the missing-trace observable while continuing to reject prose as evidence. Keep the whole requirement pending until that clause is proven.

#### TDD-4.2.19 Run page leads with stored reading or explicit current status
<!-- id: TDD-4.2.19 | implements: RN-05 | code: apps/swarm-web/src/pages/Run.tsx#RunBody | tests: apps/swarm-web/src/pages/Run.test.tsx | status: implemented -->

`RunPage` reads `GET /api/v1/runs/{encodedRunId}` and passes the stored run, paper, events, genome, reading, cost and likes to `RunBody`. The page renders the run identity and status, then a returned reading through `ReadingView`, before its cost cards, paper/replay diagnostics, recorded genome and detailed cost groups.

Without a reading, queued/running runs say that the reading has not been submitted yet, failed runs say that they failed without a reading, and completed runs say that no reading is stored. Failure reason text remains visible. The page never constructs a final reading from event prose. The recorded genome is the version attached to the run. Its own-island edit action is a link to `/islands/{encodedIsland}#agent-{genomeId}`; the run does not edit that recorded genome in place. A run 404 forgets its remembered id and returns to the storm.

Tests include "a completed run shows visible reading content before replay, genome and cost details", the parameterized "a $status run without a reading leads with its status before diagnostics", "the submitted reading shows its claims with the words they quote" and "a run is watched, not steered: its genome is shown as the run used it, and editing is a link to the agent". These verify visible text, document order and the stored-genome boundary.

#### TDD-4.2.20 Replay navigates stored event order and follows live records
<!-- id: TDD-4.2.20 | implements: RN-05 | code: apps/swarm-web/src/pages/Run.tsx#RunPage | tests: apps/swarm-web/src/pages/Run.test.tsx | status: implemented -->

Queued and running runs refresh their projection every three seconds; terminal runs stop that polling. The run body's replay state starts at zero for a terminal run without a query. A live run without a step query follows the newest stored event. A numeric integer `?step=` selects a clamped event position; tree event links are one-based. Selecting a step pauses live following, and the live control can resume it.

`Replay` displays the recorded opening prompt before the first event, then the event badge, input/tool data and event cost in stored response order. Play advances one step every 1,600 milliseconds, stops at the final event, and supports pause and restart. A run with no events cannot replay fabricated steps. `PaperViewer` uses the current event's locator to select a stored section and mark its quotation, opens a PDF at a page-only locator, or keeps available metadata/abstract and a quotation when neither stored full text nor PDF exists.

Run tests check opening prompt, played-only event lists, `?step=3`, live follow/pause/refollow, timed play/pause/restart, no-event controls, section/quote highlighting and PDF/fallback behavior. `test_a_run_started_through_the_api_can_be_watched_and_replayed` covers the HTTP run/event projection. These event locator tests do not establish links from each final-reading claim to atomic evidence.

#### TDD-4.2.21 Link every final claim to atomic evidence or mark it uncited
<!-- id: TDD-4.2.21 | implements: RN-05 | code: apps/swarm-web/src/components/ReadingView.tsx#ReadingView | tests: apps/swarm-web/src/pages/Run.test.tsx | status: pending -->

A final-reading claim must link to its cited atomic evidence in the run/tool-call cascade, or show the required uncited state when no citation exists. Missing artifacts must be reported rather than replaced with agent prose. The reading-first order and existing replay navigation must remain.

`ReadingView` currently renders evidence quotation text with "quoted from the paper", "not found in stored text" or "quote" labels. A claim without quotation evidence says "no quote given". Its browser claim-evidence type has quotation and verification data but no evidence locator/link, and the renderer has no per-claim evidence navigation anchor. Direct links from paper readings to runs and `?step=` links from run branches do not connect a particular final claim to the atomic evidence it cites.

Existing run tests prove visible quotation text, event locator behavior and reading-first order. Completion requires the declared run-page test to follow a final claim into its cited evidence and to observe an explicit uncited/missing-artifact state for a claim without it. Those claim-to-evidence interactions remain unimplemented and untested.

#### TDD-4.2.22 Finite provider wait and single-attempt failure
<!-- id: TDD-4.2.22 | implements: RN-03 | code: src/research_agent/beta/config.py#_provider_timeout | tests: tests/beta/test_service.py | status: implemented -->

Provider configuration must parse `RESEARCH_AGENT_MODEL_TIMEOUT_SECONDS` as finite positive seconds, defaulting to 300. Fractional values are accepted; zero, negative, nonnumeric and nonfinite values raise `ConfigError` during configuration loading.

`ChatCompletionsClient.complete` applies the configured value to HTTP connect, read, write and connection-pool waits. The timeout does not change request prompts, output allowances or run budgets. A transport timeout becomes `ModelCallFailed` after one request; automatic paid-request retries are not added because a timed-out request may already have completed remotely.

`test_provider_timeout_requires_finite_positive_seconds` checks invalid settings. `test_configured_provider_timeout_reaches_the_http_request` checks both the default and a fractional override in the actual request extensions, preserving its output limit. `test_provider_read_timeout_is_reported_without_retrying_the_request` checks typed failure and exactly one request.

These tests establish configuration propagation and failure behavior. They do not demonstrate a live completion beyond the previous deadline or settle an unknown provider charge.

## 5. Cost receipts

### 5.1 Cost attached to everything

#### TDD-5.1.1 Cost receipt writer
<!-- id: TDD-5.1.1 | implements: CT-01 | code: src/research_agent/beta/costs.py#record_cost_receipt | tests: tests/beta/test_costs.py | status: pending -->

The leaf-charge ledger stores owner, parent object, units, amount, provider and settlement state. Paid requests with malformed responses retain an unsettled estimate, and successful paid receipts survive later trace or generation rollback. Ingestion, run, chat and evolution callers use the same writer. General tool and reading actions are absent from the admitted action set, so every-scarce-action coverage remains incomplete.

#### TDD-5.1.2 Cost-aware projections
<!-- id: TDD-5.1.2 | implements: CT-02 | code: src/research_agent/beta/costs.py#attach_cost_summary | tests: tests/beta/test_costs.py | status: pending -->

Cost summaries return settled totals and unsettled counts or unavailable. Paper, run and island views use those summaries beside output and activity. fixes the run total that currently mixes settlement states. Genome, evolution and cost-per-useful-feedback coverage remain incomplete.

#### TDD-5.1.3 Evolution cost policy
<!-- id: TDD-5.1.3 | implements: CT-03 | code: src/research_agent/beta/evolution.py#maybe_run_evolution | tests: tests/beta/test_evolution.py | status: pending -->

The current implementation ranks parents by like points, run count and id, then applies breeding and budget admission. It does not implement usefulness bands, a cost tie-break or per-genome budget exclusion. owns the discrepancy; do not add another fitness system without an accepted decision.

#### TDD-5.1.4 Cost rollup ledger
<!-- id: TDD-5.1.4 | implements: CT-04 | code: src/research_agent/beta/costs.py#sum_cost_scope | tests: tests/beta/test_costs.py | status: pending -->

Each receipt is a leaf charge attached to object scope columns, not an aggregate charge. Scope totals sum leaf receipts once by run, paper or island. Nested receipt graphs are not the storage model. Receipts now retain a genome ID derived from their run, so agent totals survive failed-run expiry. The generic scope helper still admits only run, paper and island; graph consistency and complete genome/version scope contracts remain open.

### 5.2 Detailed implementation contracts

#### TDD-5.2.1 Immutable receipt storage and action admission
<!-- id: TDD-5.2.1 | implements: CT-01 | code: src/research_agent/beta/costs.py#record_cost_receipt | tests: tests/beta/test_costs.py | status: implemented -->

`record_cost_receipt` must accept exactly `ingest`, `model_call`, `chat_retrieval`, `chat_answer` and `evolution`. Unknown actions raise `ValueError` before insertion.

Each receipt stores `id`, `action`, `owner_kind`, `owner_id`, `parent_kind`, `parent_id`, `unit_type`, `quantity`, `amount_micros`, `currency`, `provider`, `estimated`, `settlement`, `island_id`, `paper_id`, `run_id`, `genome_id` and `created_at`. IDs have a `C` prefix, dates are UTC, and currency defaults to `USD`. Provider and object scopes may be null. The schema constrains nonnegative amount, estimation to zero or one, and settlement to `settled` or `unsettled`. Triggers reject receipt updates and deletes.

The writer derives `genome_id` from the named run; it can be null when no run is attached. Migration 11 backfills existing receipts from runs and restores the immutable update trigger before normal use. `test_receipt_attribution_migration_backfills_and_restores_immutability` verifies attribution, unchanged charge, restored update/delete refusal and migration repeatability. The receipt-value and unknown-action tests verify the writer. `test_run_events_and_receipts_cannot_be_rewritten` in `tests/beta/test_db.py` verifies immutability.

#### TDD-5.2.2 Token prices and worst-case run estimates
<!-- id: TDD-5.2.2 | implements: CT-01 | code: src/research_agent/beta/budget.py#estimate_run_micros | tests: tests/beta/test_budget.py | status: implemented -->

`price_micros` must return the ceiling of input tokens multiplied by the configured input USD-per-million-token rate plus output tokens multiplied by the output rate. The million-token and micro-dollar factors cancel. The test provider prices 1,000 input and 200 output tokens at 500 micro-dollars. `estimate_tokens` uses the ceiling of character count divided by three.

Run estimates add 500 schema tokens to the prompt. Zero-based call index `i` adds `i * (max_output_tokens + 1000)` carried input tokens, then prices the full output allowance. Explicit closing allowances add `final_calls - 1` calls and use the final output limit from the submission index onward. `fit_run_to_cap` reduces normal calls until the estimate fits, retaining one call even if that minimum exceeds the cap.

The worst-case estimate, submission-retry and per-run call-reduction tests verify these bounds.

#### TDD-5.2.3 Paid settlement and independent receipt commits
<!-- id: TDD-5.2.3 | implements: CT-01 | code: src/research_agent/beta/runs.py#_drive | tests: tests/beta/test_runs.py | status: implemented -->

A usable response must record input plus output tokens at `price_micros`. Missing provider usage sets `estimated=True` while the usable response remains settled. Invalid completion containers or invalid token counts become `ModelCallFailed` at the provider boundary.

A failed run records estimated sent input tokens and their input-only price. Failed chat records its prompt estimate as quantity and its admitted full input/output estimate as amount. Failed evolution records the user-text estimate as quantity and its admitted system/user input plus 1,200 output tokens as amount. All three failures record estimated, unsettled receipts.

These owners must commit paid receipts before later trace, answer or generation work. The malformed-response test forces a failed run-event insert and retains the charge. The rollback tests in `tests/beta/test_chat.py` and `tests/beta/test_evolution.py` prove the same boundary for settled and unsettled receipts.

#### TDD-5.2.4 Complete scarce-action accounting
<!-- id: TDD-5.2.4 | implements: CT-01 | code: src/research_agent/beta/runs.py#dispatch_tool_call | tests: none | status: pending -->

Every performed scarce action must retain a linked receipt, including failed external retrieval, HTML text retrieval, stored-data tools and reading submission when those actions consume a scarce resource.

Ingestion currently records a zero-amount `ingest` receipt with unit `arxiv_request` and quantity one before each source-category request, including recorded source failure. Chat records zero-amount `chat_retrieval` with unit `stored_lookup` and quantity one. Successful cited-paper import records ingestion cost after fetching metadata. Failed cited-paper fetches, HTML extraction, ordinary tool dispatch and final submission do not each receive separate receipts. No test proves one linked receipt for every scarce action. Parent-wide `cost_unsettled` behavior on accounting failure also lacks a uniform representation.

#### TDD-5.2.5 Settlement-aware summaries and unavailable cost
<!-- id: TDD-5.2.5 | implements: CT-02 | code: src/research_agent/beta/costs.py#attach_cost_summary | tests: tests/beta/test_costs.py | status: implemented -->

`attach_cost_summary` must return `state=available` with `settled_micros`, `unsettled_micros`, `unsettled_count`, `receipt_count` and `estimated_count`. Estimated settled charges remain in settled totals; unsettled estimates stay separate. A SQLite query error must yield only `state=unavailable`, rather than an available zero.

`test_scope_totals_count_each_receipt_once_and_keep_unsettled_apart` checks literal totals of 5,000 settled micro-dollars, 700 unsettled micro-dollars, one unsettled receipt, three receipts and one estimate. `test_a_cost_that_cannot_be_read_is_unavailable_not_zero` drops the receipt table and checks unavailable cost.

#### TDD-5.2.6 Settlement consistency across activity projections
<!-- id: TDD-5.2.6 | implements: CT-02 | code: src/research_agent/beta/projections.py#build_run_projection | tests: tests/beta/test_api.py | status: pending -->

Activity views must distinguish settled cost, unsettled charges and unavailable cost. An unsettled estimate must not appear as settled spend.

The run response has a settlement-aware `cost` block and individual receipts, but top-level and nested `cost_micros` sum all receipt amounts. Run briefs, island paper rows, per-island paper breakdowns and agent statistics also combine settlement states. Paper top-level cost uses only settled amount; agent detail separately provides settled cost and unsettled count. The positive API cascade test uses settled receipts, so it does not prove mixed-settlement or unavailable display across these views.

#### TDD-5.2.7 Complete genome, generation and feedback cost measures
<!-- id: TDD-5.2.7 | implements: CT-02 | code: src/research_agent/beta/projections.py#build_agent_projection | tests: none | status: pending -->

Genome and evolution views must show settlement-aware costs beside activity and provide cost per useful feedback when useful feedback exists. Failed cost queries must remain unavailable.

Agent detail reads receipts directly by their durable `genome_id` and returns settled cost, unsettled count and receipt count. Failed-run deletion no longer removes the receipt from genome totals. `test_expired_failed_run_cleanup_preserves_agent_and_island_cost` proves retained attribution and spend. Agent lists use a combined amount, and the detail cost query has no unavailable-result guard. There is no shared useful-feedback denominator or cost-per-useful-feedback calculation. Generation activity has no persisted settlement-aware cost projection. Chat returns an answer amount and receipt IDs without an answer-scoped settlement summary. Complete projections and mixed-settlement negative tests remain absent.

#### TDD-5.2.8 Current parent and retirement ordering
<!-- id: TDD-5.2.8 | implements: CT-03 | code: src/research_agent/beta/evolution.py#maybe_run_evolution | tests: tests/beta/test_evolution.py | status: implemented -->

The current rule path selects the island parent by the maximum tuple of like points, completed-run count and genome ID. Cost is not an input. A seeded choice selects a mate from active genomes on nonarchived other islands.

Population-cap retirement selects the minimum completed-run count and genome ID among eligible nonparents; a valid model-requested retirement records its reason. These are current selection rules, not usefulness bands or cost tie-breaks. `test_the_breeder_may_fail_out_a_lemon_and_likes_pick_the_parent` shows one like outweighing six completed runs. `test_over_its_cap_the_island_archives_its_least_run_agent` verifies retirement ordering.

#### TDD-5.2.9 Paid proposal budget admission
<!-- id: TDD-5.2.9 | implements: CT-03 | code: src/research_agent/beta/budget.py#admit_paid | tests: tests/beta/test_evolution.py | status: implemented -->

Paid proposals must be admitted against provider availability, budget mode, request estimate and `per_evolution_max_micros`, whose default is 20,000. The estimate prices system/user token estimates plus the 1,200-token proposal allowance.

`admit_paid` refuses estimates strictly above the request cap, or an estimate plus existing run reservations that would exceed monthly committed budget or today's hard budget. Monthly committed cost includes settled and unsettled receipts. Equality with the cap is permitted; stopped budget modes refuse paid proposals. Refusal leaves the rule path available.

`test_the_budget_decides_whether_the_model_is_asked` sets a one-micro-dollar cap, observes zero provider requests and rule fallback. Paid-chat cap tests in `tests/beta/test_budget.py` exercise the same shared admission boundary.

#### TDD-5.2.10 Usefulness bands and candidate budget enforcement
<!-- id: TDD-5.2.10 | implements: CT-03 | code: src/research_agent/beta/evolution.py#maybe_run_evolution | tests: none | status: pending -->

Selection must compare genome usefulness before cost, use cost only within equal usefulness bands, and refuse a genome above its configured budget. Records must expose usefulness, cost and budget decisions separately, and a failed comparison must preserve survivors.

Current selection uses likes, completed runs and IDs. Digest cost per run is information shown to a proposal request, not a deterministic tie-break. The request cap controls whether to ask for a proposal, not candidate genome spending. No test proves that a useful expensive genome defeats a cheap bad genome or that an over-budget candidate is excluded. Scoring bands and candidate-budget admission remain unimplemented.

#### TDD-5.2.11 Flat scope rollup and settlement partitions
<!-- id: TDD-5.2.11 | implements: CT-04 | code: src/research_agent/beta/costs.py#sum_cost_scope | tests: tests/beta/test_costs.py | status: implemented -->

`sum_cost_scope` must sum each matching receipt row once. Its allowed scope columns are exactly `run_id`, `paper_id` and `island_id`. An unknown scope raises `ValueError` before SQL construction. It does not add stored run totals to paper totals or paper totals to island totals.

Settled and unsettled amounts are summed separately; receipt and estimation counts include both settlement states. The two-run paper fixture proves a 10,000-micro-dollar settled paper total and the same island total. Both seeded island totals sum to 19,000, equal to the settled receipt ledger. This verifies flat scope columns rather than nested parent traversal. Failed-run cleanup leaves receipt rows intact, including `run_id`, `paper_id`, `island_id` and durable `genome_id`; deleting the diagnostic run therefore does not remove its spend from scope totals.

#### TDD-5.2.12 Budget commitment and remaining reservations
<!-- id: TDD-5.2.12 | implements: CT-04 | code: src/research_agent/beta/budget.py#budget_state | tests: tests/beta/test_budget.py | status: implemented -->

Budget commitment must include settled and unsettled receipt amounts. UTC receipt dates define month-to-date, today's total and island totals. Each queued or running run reserves `max(0, estimate_micros - sum(all run receipt amounts))`; completed and failed runs reserve nothing. A receipt and its already-spent estimate are therefore not reserved twice.

Derived daily soft budget uses integer division of monthly budget by days in the month; default hard budget doubles that amount. Mode uses actual committed spend. New-run admission also considers reservations and refuses when existing commitment reaches a line, instead of requiring the next full estimate to fit beforehand.

The unsettled-spend test verifies hard stop while settled display remains zero. The queued-reservation test in `tests/beta/test_runs.py` verifies that a stored estimate blocks subsequent admission.

#### TDD-5.2.13 Parent consistency and complete scope reconciliation
<!-- id: TDD-5.2.13 | implements: CT-04 | code: src/research_agent/beta/costs.py#sum_cost_scope | tests: none | status: pending -->

Rollup must reconcile declared object-parent links, count represented charges once and mark inconsistent totals rather than display them as settled. Nested parent receipts require a negative case that exposes double counting.

Current rollup filters denormalized scope columns without traversing `parent_kind` and `parent_id`. The writer does not validate parent existence or prevent another receipt being named as parent. No consistency state is computed. Genome totals use separate joins through runs, not an admitted generic receipt scope. Evolution can retain a paid receipt without a generation row after rollback. Parent-link reconciliation for these cases is absent, and the flat-scope test does not establish nested rollup.

## 6. Feedback and rapid evolution

### 6.1 Live genome movement

#### TDD-6.1.1 Feedback service
<!-- id: TDD-6.1.1 | implements: EV-01 | code: src/research_agent/beta/likes.py#toggle_like | tests: tests/beta/test_api.py | status: pending -->

A persisted island-scoped toggle validates paper, run, reading, claim, idea and agent targets. The specified signal, optional note and chat-answer targets are not implemented. Those missing fields and targets remain required by the feedback contract.

#### TDD-6.1.2 Evolution threshold runner
<!-- id: TDD-6.1.2 | implements: EV-02 | code: src/research_agent/beta/evolution.py#maybe_run_evolution | tests: tests/beta/test_evolution.py | status: pending -->

Evolution triggers on configured run count or an explicit force request. Feedback-count thresholds and scoring from completion, trace health and preferences are absent. The declared feedback threshold and usefulness scoring remain unimplemented.

#### TDD-6.1.3 Atomic generation record
<!-- id: TDD-6.1.3 | implements: EV-03 | code: src/research_agent/beta/evolution.py#maybe_run_evolution | tests: tests/beta/test_evolution.py | status: implemented -->

Evolution stores created, retained and archived genome decisions with parent links and reason codes in the generation transaction. Tests force failure after spec revision creation and verify no new spec or partial generation remains. Separate paid-proposal tests prove that the receipt survives while partial lineage rolls back. Source versions and copied fields remain the distinct IS-05 discrepancy.

#### TDD-6.1.4 Evolution activity projection
<!-- id: TDD-6.1.4 | implements: EV-04 | code: src/research_agent/beta/evolution.py#build_generation_activity | tests: tests/beta/test_evolution.py | status: pending -->

`build_generation_activity` supplies stored generation decisions. IslandPage places selected papers and current runs before a collapsed lineage and management section. EvolutionTree provides search, active/archived filters, expandable ancestry, one selected GenomeCard, bounded rows and cycle handling. Routine cycle and decision-history panels are omitted. App, EvolutionTree and GenomeCard tests cover these browser behaviors.

Only committed generations reset completed-run progress. Idle heartbeats can evolve existing completed work, including without a model provider; skipped cycles retry after a 15-minute cooldown. The combined seeded-generation browser acceptance case for island-to-genome-to-run navigation and unavailable lineage remains incomplete. Settlement-aware cost and feedback measures remain separate cost contracts.

### 6.2 Detailed implementation contracts

#### TDD-6.2.1 Stored feedback targets and authenticated scope
<!-- id: TDD-6.2.1 | implements: EV-01 | code: src/research_agent/beta/likes.py#_resolve | tests: tests/beta/test_api.py | status: implemented -->

The like endpoint must admit only `paper`, `run`, `reading`, `claim`, `idea` and `agent`. Papers and runs resolve against storage. A reading resolves to its stored paper, run and genome. Claims and ideas use `<reading-id>#<index>` with a zero-based index into the stored array. The endpoint validates agents against the current specification before invoking the toggle.

The giving island derives from authenticated session scope; an operator may name a permitted island. Targets can belong to another island. The API test permits a Quant like on a CS run and rejects missing runs, out-of-range claims, unknown agents, tool-call targets, mismatched island scope and unauthenticated requests.

#### TDD-6.2.2 Reversible one-per-island like storage
<!-- id: TDD-6.2.2 | implements: EV-01 | code: src/research_agent/beta/likes.py#toggle_like | tests: tests/beta/test_api.py | status: implemented -->

Storage must admit at most one like for `(island_id, target_kind, target_id)`. A first toggle inserts an `L`-prefixed row with resolved paper, run and genome scopes and a UTC timestamp. A repeated toggle deletes the existing row. The response includes target, giving island, resulting `liked` boolean and the count across islands.

This is a reversible toggle, not idempotent submission. Repeating the request changes the outcome. The endpoint commits the toggle before constructing the budget response. `test_a_like_on_any_layer_is_one_per_island_and_becomes_the_agents_points` verifies insertion, removal and the literal zero count after removal.

#### TDD-6.2.3 Feedback projection keys and selector points
<!-- id: TDD-6.2.3 | implements: EV-01 | code: src/research_agent/beta/likes.py#points_of | tests: tests/beta/test_api.py | status: implemented -->

`likes_where` must project stored rows under `<kind>:<target-id>` keys, with count and giving islands in creation order. Paper views filter resolved paper ID; run views include likes resolved to the run and directly named run targets.

`points_of` counts likes resolved to the genome, then adds each paper like for which at least one reading by that genome voted to keep the paper. The existential query counts that paper like once even if multiple matching readings exist. Points enter the proposal digest and rule parent selector. The API test checks run and claim keys and the literal six-point example spanning run, reading, claim, idea, agent and kept-paper likes.

#### TDD-6.2.4 Signal notes, history and chat-answer feedback
<!-- id: TDD-6.2.4 | implements: EV-01 | code: src/research_agent/beta/likes.py#toggle_like | tests: none | status: pending -->

Feedback must retain the specified signal, optional note, island and time for paper, reading, run, idea and chat-answer targets. Target history, island totals and evolution input must expose those records. Removing a current like deletes it, so toggle rows alone do not provide durable history.

The likes schema has no signal or note, the old feedback table was dropped, and `chat_answer` is not admitted. No test records chat-answer feedback or durable target history. Bulk agent points also join every keep-reading, while selector points use an existential paper query. Repeated keep-readings can multiply a paper like in bulk projections; consistent totals for that case remain unproven.

#### TDD-6.2.5 Evolution defaults and setting validation
<!-- id: TDD-6.2.5 | implements: EV-02 | code: src/research_agent/beta/spec.py#evolution_settings_from | tests: tests/beta/test_evolution.py | status: implemented -->

Evolution defaults are `enabled=True`, `runs_threshold=6` and `max_agents_per_island=6`. Enable must be a boolean. Threshold and population cap must be whole numbers of at least one, excluding booleans. Unknown names are refused.

Retired settings `feedback_threshold`, `verdict_threshold` and `min_runs_to_judge` are accepted and discarded before validation; they do not activate those behaviors. The settings test checks that an old feedback threshold is dropped while the run threshold remains, and rejects an unknown fitness setting and a zero population cap.

#### TDD-6.2.6 Completed-run threshold and force behavior
<!-- id: TDD-6.2.6 | implements: EV-02 | code: src/research_agent/beta/evolution.py#_since_last | tests: tests/beta/test_evolution.py | status: implemented -->

Threshold counts include only completed runs whose `finished_at` is later than the latest committed generation timestamp for the island. Failed runs do not advance the threshold. Skipped generations do not consume completed-run progress. New generation number counts all stored generations plus one.

The runner returns no generation below threshold unless forced. A latest skipped cycle imposes a 15-minute retry cooldown unless forced. Force bypasses count and cooldown, while global disable, island `evolve=False` and archived-island guards still apply. An island with mutation disabled can record a cycle that keeps all genomes.

`test_skipped_cycles_retry_without_consuming_completed_runs` rejects consuming completed work on a skipped cycle and immediate retry, then proves a later committed cycle. `test_idle_heartbeat_evolves_from_existing_completed_runs` and `test_idle_heartbeat_evolves_without_a_model_provider` prove evolution without newly scheduled work or a model provider. Existing threshold and disable tests verify six-run admission and force respecting switches.

#### TDD-6.2.7 Optional proposals and seeded fallback
<!-- id: TDD-6.2.7 | implements: EV-02 | code: src/research_agent/beta/evolution.py#_proposal_from_model | tests: tests/beta/test_evolution.py | status: implemented -->

An admitted proposal request exposes only `propose_child`, uses temperature 0.9 and allows 1,200 output tokens. The digest places the target island first and includes active settings, recent readings, points and aggregate cost per run.

A proposal needs known parent IDs with at least one from the target island. Unknown tools are filtered and `submit_reading` retained. Temperature is clamped to 0.1 through 1.2, output allowance to 256 through 2,000, prompt to 1,800 characters and strategy to 600. The genome is validated and must not repeat existing content. Missing tools, unparsable argument text, wrong-island parents and rejected genomes return proposal outcomes; no accepted child invokes seeded rule breeding.

The configured-proposal test verifies model lineage and cost. The failed-or-useless-proposal test verifies typed provider failure and wrong-island fallback.

#### TDD-6.2.8 Feedback thresholds and recent-genome scoring
<!-- id: TDD-6.2.8 | implements: EV-02 | code: src/research_agent/beta/evolution.py#maybe_run_evolution | tests: none | status: pending -->

Evolution must trigger from feedback-count or completed-run thresholds and score recent genomes using feedback, reading completion, trace health, cost and island preferences. A skipped comparison must record a reason without changing active genomes.

Only completed-run counting and force are implemented. Feedback thresholds are discarded; scoring preferences are validated genome data rather than selection inputs. The current parent tuple has no trace-health or composite usefulness score. No test crosses a feedback count to create a generation or distinguishes useful expensive behavior from cheap poor behavior. These trigger and scoring paths remain absent.

#### TDD-6.2.9 Seeded breeding, novelty and ancestry
<!-- id: TDD-6.2.9 | implements: EV-03 | code: src/research_agent/beta/evolution.py#mate_genomes | tests: tests/beta/test_evolution.py | status: implemented -->

Rule mating preserves the parent's main prompt, adds the mate's reading emphasis, takes the mate's strategy, averages temperatures and combines tools before offering one seeded field mutation. Plain mutation applies when no cross-island mate exists. Offered mutations cover prompt emphasis, strategy, temperature, output allowance and optional tools.

The same seed must repeat the chosen child. Existing content is excluded, and managed research-method metadata alone does not establish novelty. Each child's methods are set to the target island's methods and the genome is validated before specification changes.

The repeatability test validates deterministic mating and exhausts mutation offers to obtain no child. Tests in `tests/beta/test_methods.py` verify target-domain retention, novelty independent of managed guidance, and refusal of oversized crossed content.

#### TDD-6.2.10 Population limits and unfinished-cohort protection
<!-- id: TDD-6.2.10 | implements: EV-03 | code: src/research_agent/beta/evolution.py#_unfinished_readers | tests: tests/beta/test_evolution.py | status: implemented -->

Retirement candidates must exclude new-child parents and readers whose frozen cohort lacks a completed keep vote. Cohort size uses the first run's stored limits with current planned size as fallback. Selected, released or decided papers do not retain protection.

A proposed retirement applies only to an eligible active nonparent. Adding a child above the population cap archives the least-completed-run eligible genome. If every retiree is protected, the cycle records `pending_reading_cohort` and leaves population unchanged. Archived genomes remain stored with `active=False`.

Tests keep failed readers until cohorts finish, defer children when all retirees have missing votes, and retire completed readers instead of readers that still owe a vote.

#### TDD-6.2.11 Generation records and atomic lineage changes
<!-- id: TDD-6.2.11 | implements: EV-03 | code: src/research_agent/beta/evolution.py#maybe_run_evolution | tests: tests/beta/test_evolution.py | status: implemented -->

Each generation stores `id`, `island_id`, `number`, `status`, `reason`, `revision`, serialized `decisions` and `created_at`, with a unique number per island. Status is `committed` or `skipped`. Decisions contain genome ID, decision and reason plus applicable parent, mutation, island and explanation fields.

Decision outcomes include parent, mate, created, kept and archived. Reasons include `mated`, `from_another_island`, `rule_mating`, `model_mating`, `no_ranking`, `population_cap` and `breeder_lemon`. Cycle skips include `no_active_agent`, `no_novel_child`, `invalid_child` and `pending_reading_cohort`.

New genome IDs avoid collisions. Lineage records origin, primary-parent ID/version, parent IDs, generation, mutation, proposer and explanation; `apply_spec` adds revision. Genome changes and generation insertion share the post-proposal transaction. The forced-write-failure test rolls it back and finds neither new revision nor child.

#### TDD-6.2.12 Paid proposal receipts survive lineage rollback
<!-- id: TDD-6.2.12 | implements: EV-03 | code: src/research_agent/beta/evolution.py#_proposal_from_model | tests: tests/beta/test_evolution.py | status: implemented -->

Paid proposal receipts must commit before normalization, genome changes or generation insertion. Action is `evolution`, owner is the new generation ID and parent is its island. Island scope and provider remain attached. A usable response is settled; typed provider failure retains an unsettled estimate and falls back to rule breeding.

Later generation failure must roll back revised lineage and generation storage without erasing the incurred charge. A receipt may therefore name a generation ID with no committed generation row. `test_a_paid_proposal_receipt_survives_generation_rollback` uses the real completion client and a SQLite insert trigger. Invalid-message, invalid-usage and valid-response cases each retain one receipt, zero generations and the original specification.

#### TDD-6.2.13 Stored backend generation activity
<!-- id: TDD-6.2.13 | implements: EV-04 | code: src/research_agent/beta/evolution.py#build_generation_activity | tests: tests/beta/test_evolution.py | status: implemented -->

Generation activity must read one island's stored rows in descending generation-number order, defaulting to twenty records, and decode decision arrays. Returned ID, island, number, status, reason, revision, decisions and timestamp derive from storage rather than current genome reconstruction.

`_evolution_steps` flattens generations into decision rows with generation number, status, revision and timestamp. Skipped generations add an explicit skipped row with the stored reason. The island projection collects that evolution group. Its backend test verifies the stored parent and created-child decisions and generation number. Browser presentation is a separate contract.

#### TDD-6.2.14 Complete lineage availability boundary
<!-- id: TDD-6.2.14 | implements: EV-04 | code: src/research_agent/beta/projections.py#_evolution_steps | tests: none | status: pending -->

A failed lineage projection must remain distinguishable from an empty population. IslandPage names failed groups in its alert, and an unavailable agents group substitutes explicit unavailable text for EvolutionTree. The backend still exposes stored generation decisions, but routine decision-history panels are not part of the current browser contract.

A complete seeded-generation integration test must connect backend lineage availability to the collapsed browser section and prove that missing data cannot appear as an ordinary empty population. Existing fixture-based unavailable-agent tests and separate generation-projection tests do not prove that combined boundary. Generation and genome settlement/feedback measures remain cost requirements; they are not prerequisites for the revised lineage layout.

#### TDD-6.2.15 Lineage browser keeps selection and ancestry bounded
<!-- id: TDD-6.2.15 | implements: EV-04 | code: apps/swarm-web/src/components/EvolutionTree.tsx#EvolutionTree | tests: apps/swarm-web/src/components/EvolutionTree.test.tsx | status: implemented -->

`IslandPage` passes projected agents to `EvolutionTree`. The tree owns expanded branches, selected id, case-insensitive id/prompt search, active/archived filter and visible-row limit. It displays one selected `GenomeCard`. Removing that selection from the response falls back to an available active agent or the first remaining agent. Outline rows initially show at most 30, with explicit increments of 30.

`lineageForest` builds the primary-parent tree and records secondary parents. `parentOf` preserves evolutionary ancestry when an edited version names itself as version parent. Missing parents stay reachable as roots with an unavailable-parent label. Cycle detection breaks a cyclic primary edge, and iterative traversal handles deep ancestry. Search results retain parent/depth context; population filters include ancestors. Search/filter force visible matching ancestry rather than using the collapsed outline state.

Routine decision-history and skipped-cycle panels are omitted. Backend generation records remain available to their readers; absence of those browser panels is intentional.

The eight `EvolutionTree.test.tsx` cases check branch collapse, single-card selection, filters, bounded population without cycle diagnostics, missing/secondary parents, self-version ancestry, deep/cyclic traversal, removed selection, an outside descendant leading into a cycle, and shallow-search parent/depth display.

#### TDD-6.2.16 Selected genome management uses version and active-state services
<!-- id: TDD-6.2.16 | implements: EV-04 | code: apps/swarm-web/src/components/GenomeCard.tsx#GenomeCard | tests: apps/swarm-web/src/App.test.tsx | status: implemented -->

Own-island lineage detail receives `onSaved`, which enables editing an active genome and archiving or bringing back the selected genome. `GenomeEdit` owns edited prompt, selected tools and request/refusal state. It posts `/api/v1/genomes` with `{island_id, parent_id: genome.id, prompt, tools}` where tools is a comma-separated list. Success reloads the island and closes the form. A refusal keeps the edited text and tool selection and says that nothing was saved. The API creates a new version; prior run records retain their stored version.

Archive/restore posts `/api/v1/agents/{encodedGenomeId}` with `{fields: {active: boolean}}`, disables the control while waiting and reloads on success. Refusal preserves the server projection and reports that nothing changed. Other island details receive no mutation callback. A hash link `/islands/{island}#agent-{id}` selects the referenced detail after data arrives, including same-island hash navigation. A failed agents group displays unavailable text without an empty searchable population.

App tests cover prompt/tool payload, refused edits, reload without blanking the island, archive/restore payload, refused archival, hash selection and unavailable agents. `test_the_web_apps_agent_form_saves_a_new_version_and_keeps_past_runs` in the HTTP suite proves version preservation. These behaviors implement management and current-run links. The combined seeded-generation island-to-detail-to-run acceptance case remains separate; routine decision histories and aggregate activity metrics are not obligations of the revised lineage browser requirement.

#### TDD-6.2.17 Close lineage navigation and unavailable-state integration
<!-- id: TDD-6.2.17 | implements: EV-04 | code: apps/swarm-web/src/components/EvolutionTree.tsx#EvolutionTree | tests: tests/beta/test_evolution.py | status: pending -->

A visitor must open collapsed island lineage, inspect a genome and follow links to that genome's runs. Unavailable lineage must be visibly unavailable. Routine skipped-cycle and decision-history panels are intentionally omitted.

`test_the_island_page_shows_generations_and_the_settings_are_validated` seeds a generation and verifies stored decisions, generation numbers and child ancestry. `test_finished_runs_evolve_an_island_and_the_page_lists_each_decision` checks the HTTP projection. The browser renders ancestry and selected detail; a current-run watch link is available when reported. App tests exercise hash selection and unavailable agents. These separate tests do not establish the complete seeded-generation navigation path through the live projection.

Completion requires that combined browser acceptance case to open lineage, follow genome detail and the associated run, and distinguish unavailable lineage from empty data. The remaining gap is integration proof of navigation and failure presentation, not a requirement to restore removed history panels or introduce feedback/cost metrics into this section.

## 7. Pages and chat

### 7.1 Visible surfaces

#### TDD-7.1.1 Visible route families
<!-- id: TDD-7.1.1 | implements: UI-01 | code: apps/swarm-web/src/App.tsx#PAGES | tests: apps/swarm-web/src/App.test.tsx | status: pending -->

PAGES registers the public splash, login, island, paper, run and chat in apps/swarm-web. The exact-family browser test excludes unrelated page families, but no startup registry refuses an unexpected family. The public brief and grade belong to the same entry page; the grade formula is descriptive output, not scientific qualification. The registration guard remains missing.

#### TDD-7.1.2 Paper cascade projection
<!-- id: TDD-7.1.2 | implements: UI-02 | code: apps/swarm-web/src/pages/Paper.tsx#PaperPage | tests: apps/swarm-web/src/App.test.tsx | status: pending -->

PaperPage consumes build_paper_projection and renders title and visible ReadingView content before metadata, assignments, run traces and cost breakdown. Empty and unavailable readings have separate messages, and each reading retains likes and a run link even when its run lies outside the response window. Assignment and run group failures still appear empty, and settlement display remains incomplete.

#### TDD-7.1.3 Chat answer service
<!-- id: TDD-7.1.3 | implements: UI-03 | code: src/research_agent/beta/chat.py#answer_question | tests: tests/beta/test_chat.py | status: pending -->

Chat retrieves island-scoped stored references and either renders deterministic retrieval text or requests optional synthesis. Retrieved links alone do not prove generated claims are supported. Unlinked or invented model claims must remain unsupported; HTTP and browser interaction coverage for that boundary is still missing.

#### TDD-7.1.4 Chat non-authority
<!-- id: TDD-7.1.4 | implements: UI-04 | code: src/research_agent/beta/chat.py#answer_question | tests: tests/beta/test_chat.py | status: pending -->

Chat stores retrieval and paid-answer receipts but no transcript as authority. Durable object changes belong to their existing services. Clearing browser conversation state must leave swarm records intact.

#### TDD-7.1.5 Shared UI feedback action
<!-- id: TDD-7.1.5 | implements: UI-05 | code: apps/swarm-web/src/components/Like.tsx#Like | tests: apps/swarm-web/src/App.test.tsx | status: pending -->

Like is the shared persisted browser toggle for admitted stored targets. Paper and run pages expose it, and GenomeCard provides island agent likes. Chat-answer feedback, signal notes, target history and island feedback totals remain incomplete. Browser-only votes cannot satisfy the durable feedback requirement.

### 7.2 Detailed implementation contracts

#### TDD-7.2.1 Six browser page families share one island session client
<!-- id: TDD-7.2.1 | implements: UI-01 | code: apps/swarm-web/src/App.tsx#PAGES | tests: apps/swarm-web/src/App.test.tsx | status: implemented -->

`PAGES` registers `splash` at `/`, `login` at `/login`, `island` at `/islands/:island`, `paper` at `/papers/:paperId`, `run` at `/runs/:runId` and `chat` at `/chat`. Splash and login are open. The remaining routes render through `Layout`. There is one app shell and no rating or inspector page family.

`Routed` retains one `createClient` instance across navigation and updates its navigation callback through a ref. The client uses `VITE_API_ORIGIN`, or the current origin when unset, sends credentials and carries the stored bearer token after login. `Layout` refuses to render a private child without a session. It redirects to login with the original local pathname, search and fragment as `next`, including an island hint for an island URL. `Login` posts `/api/v1/login` with `{island, password}`, accepts only an island in the public storm response and returns only to a local URL. A later authenticated 401 clears the session and returns to login. Logout clears the session and remembered paper/run navigation before opening `/`.

`App.test.tsx` verifies the exact family list, that an unauthenticated private route reads none of its data, the case-insensitive island hint, restoration of the requested fragment and retention of one client across page changes. `src/api/client.test.ts` verifies login payload, token carriage, session removal on 401 and a wrong code as a login refusal.

#### TDD-7.2.2 Public entry refreshes stored storm and activity projections
<!-- id: TDD-7.2.2 | implements: UI-01 | code: apps/swarm-web/src/pages/Splash.tsx#Splash | tests: apps/swarm-web/src/App.test.tsx | status: implemented -->

The public entry reads `GET /api/v1/public/storm` and `GET /api/v1/public/brief?include=grade,numbers,papers,agents&limit=100` without a session. It reads current readers from `agents.reading_now`, displays the stored grade and counts, and limits the globe's recent-paper input to 100. It does not render the brief's individual claim list.

Storm and brief refresh every 15 seconds. `useActivity` requests `GET /api/v1/public/activity?after={cursor}&limit=60`, advances the cursor to the maximum reported `last_id`, keeps the newest 400 steps and merges reported paper records. The next activity request occurs four seconds after a successful answer and 12 seconds after a failure. Cleanup clears the timer and ignores a pending answer after disposal. A missing brief or activity feed leaves the entry visible without a feed-error panel.

Shared `useGet` keeps a previous ready response during network, 408, 429, server or unreadable-success refresh failures. Initial failure reports a failed state; 403 or 404 clears an old response. A changed path begins loading rather than showing the previous object's data, and obsolete responses cannot replace the current path.

Existing browser tests include "the splash needs no session and reads only the public routes", "the splash counts a current reading from the requested agents section", "the globe feed retries an initial outage and stops polling when the page closes", the live-refresh and failed-refresh tests, and the parameterized `useGet` refusal and temporary-failure tests.

#### TDD-7.2.3 Reject an unexpected route family when the route table is built
<!-- id: TDD-7.2.3 | implements: UI-01 | code: apps/swarm-web/src/App.tsx#PAGES | tests: apps/swarm-web/src/App.test.tsx | status: pending -->

Route construction must reject a family outside `splash`, `login`, `island`, `paper`, `run` and `chat`, and the startup error must name that unexpected family. This is the route-table failure contract, distinct from handling an unknown URL.

The current `Page.family` is a string, and `Routed` registers the supplied `PAGES` entries without a family validator. Its wildcard URL route renders `Splash`. The existing exact-list test detects an edited family list but does not exercise a production startup rejection with an unrelated family.

Completion requires a test that supplies the six accepted families to the actual route construction owner, then supplies an unrelated family and observes startup rejection with its name. That negative behavior is not implemented or covered by the current route test.

#### TDD-7.2.4 Paper title leads into independent visible submitted readings
<!-- id: TDD-7.2.4 | implements: UI-02 | code: apps/swarm-web/src/pages/Paper.tsx#PaperPage | tests: apps/swarm-web/src/App.test.tsx | status: implemented -->

Opening `/papers/{paperId}` reads `GET /api/v1/papers/{encodedPaperId}`. The page renders `paper.title`, then the readings heading and every returned `readings` item as visible content through `ReadingView`. Reading content does not require expanding a run branch. Each reading links to `/runs/{encodedRunId}` using its own `run_id` and names its `genome_id` and creation time. A reading remains visible when its run is outside the returned run window.

`ReadingView` renders the keep vote, thesis quotation, summary, claims with evidence quotations and verification labels, objections, related-paper strings and idea seeds. The page places this content before source category, fetch/text status, source/PDF links, feedback, cost cards, assignment rows and run diagnostics. A present empty array displays "No reading has been submitted for this paper yet." Missing or null `readings`, or an `unavailable` entry of `readings`, displays "The paper's readings are unavailable." A 404 forgets the remembered paper and returns to the storm.

`App.test.tsx` checks visible reading text and document order in "the paper title leads into visible reading content before metadata and run diagnostics", independently retained readings in "a submitted reading remains visible when its run is outside the paper's run window", and explicit empty or unavailable states in "the paper leads with an explicit reading state for $message".

#### TDD-7.2.5 Paper projection links assignments and lazy run steps with reported costs
<!-- id: TDD-7.2.5 | implements: UI-02 | code: src/research_agent/beta/projections.py#build_paper_projection | tests: tests/beta/test_api.py | status: implemented -->

`GET /api/v1/papers/{paperId}` obtains `build_paper_projection`, which returns `paper`, `assignments`, `readings`, `runs`, `cost_micros`, `likes`, `cost_by_island`, receipt-summary fields and `unavailable`. Assignments include the island id, stored reason codes, combined reason text, `kept`, `released` and normalized `selected_by`. PaperPage uses its own-island assignment for one manual selection override, independent of the bounded island paper list. Readings have their own limit of 50; run briefs have a separate limit of 100. A reading's visibility does not depend on joining it to that run window.

`PaperPage` links assignment ids to island pages and uses `RunBranch` for the returned runs. Opening a run branch triggers `GET /api/v1/runs/{encodedRunId}`. `RunSteps` lists stored events in response order and links event index `i` to `/runs/{encodedRunId}?step={i+1}`, preserving the replay step query. Closed branches do not fetch their steps.

`costByIsland` prefers a nonempty server `cost_by_island` map. It sums returned run costs only when at least one run exists and every run reports a numeric cost. Otherwise the breakdown is unknown. An assigned island absent from the breakdown displays an unreported cost rather than an invented zero.

`test_the_island_paper_and_agent_views_carry_the_cascade_and_the_cost` asserts the HTTP projection, readings/run relationship, tool-call count and cost map. Browser tests cover the lazy step link and "the paper page shows each island's cost, and an island the breakdown leaves out is not shown as zero".

#### TDD-7.2.6 Distinguish every failed paper section from a successfully empty section
<!-- id: TDD-7.2.6 | implements: UI-02 | code: apps/swarm-web/src/pages/Paper.tsx#PaperPage | tests: apps/swarm-web/src/App.test.tsx | status: pending -->

A paper projection's `unavailable` group names must control each corresponding visible section. A failed assignment or run query must display an unavailable state and offer no drill-down links for that failed group. Successfully returned empty arrays must retain their ordinary empty-state copy.

The server's grouped projection can return empty arrays together with `unavailable` names. `PaperPage` currently applies this distinction to readings, but its assignment and run sections branch only on array length. A failed assignment group can therefore appear as "No island has taken this paper yet", and a failed run group can appear as no runs. Nested paper/run tree readers also do not complete this group-level distinction.

Existing paper tests prove reading-state handling and successful cascade links. They do not seed failed assignments, failed runs and nested failed groups and assert unavailable text with absent drill-downs. Completion requires those cases against the existing paper and tree owners while preserving visible readings, feedback and replay query links.

#### TDD-7.2.7 Chat retrieves stored records within the authenticated island
<!-- id: TDD-7.2.7 | implements: UI-03 | code: src/research_agent/beta/chat.py#answer_question | tests: tests/beta/test_chat.py | status: implemented -->

`POST /api/v1/chat` accepts `{message, synthesize?, island_id?}`. `synthesize` defaults to true. The HTTP owner derives the island from an island session, refuses operator/no-island sessions, and refuses a supplied `island_id` that differs from the session. `answer_question` trims the message and rejects empty input or more than 2,000 characters.

`_retrieve` starts with stored island context, resolves named island-scoped run and paper references, adds stored settled-cost and activity summaries for matching question words, and searches up to eight stored paper/reading hits. Reading references link to the stored run. Public link fields are `kind`, `id`, `title`, `snippet` and `href`; the internal `record` field stays on the server. Retrieval-only answers assemble sentences from those records. Synthesis, when admitted, receives the question and stored records with no tools and a 2,500-token output bound.

Responses contain `answer_id`, `answer`, `supported`, `mode`, `links`, `paid`, `cost_micros` and `receipt_ids`, plus the HTTP budget wrapper. `test_a_known_topic_is_answered_with_links_to_the_paper_and_the_run`, `test_deictic_island_questions_get_the_island_record`, `test_named_objects_and_costs_are_answered_from_their_records` and the empty/oversized test cover retrieval behavior. `tests/beta/test_api.py` covers default synthesis and `test_chat_is_scoped_to_the_session_island`.

#### TDD-7.2.8 Chat panel owns request state and renders linked answers with answer cost
<!-- id: TDD-7.2.8 | implements: UI-03 | code: apps/swarm-web/src/components/ChatPanel.tsx#ChatPanel | tests: apps/swarm-web/src/components/ChatPanel.test.ts | status: implemented -->

`ChatPanel` keeps `turns`, `message` and `sending` in React state. It trims input and refuses to send blank input or input without an island session. Submit appends a user turn, clears the composer and posts `/api/v1/chat` with exactly `{message: text}`. It appends the server answer on success or a refusal turn on error, then releases the sending state. While waiting, the composer and send button are disabled and a status explains that the swarm is still answering. A sending-state effect installs an unload warning and a link-navigation confirmation, and removes those handlers when sending ends or the component leaves.

Answers display `answer` and optional `links`. The panel constructs encoded local run, island or paper paths from each link's `kind` and `id`, and displays its title and optional snippet. `answerCost` shows "answer cost not reported" when absent, "from stored records" for zero and the positive answer amount with "this answer". Refused turns invite a retry. The panel currently does not render `supported`, `mode`, `paid` or `receipt_ids`.

`ChatPanel.test.ts` proves the literal answer-cost labels for zero, positive and missing costs. Backend chat/API tests prove linked response fields. Browser interaction tests for submitting, waiting, navigating during a request and displaying refusals remain absent; this implemented item records the actual owner rather than claiming that integration coverage.

#### TDD-7.2.9 Validate answer support and expose absent support in the browser
<!-- id: TDD-7.2.9 | implements: UI-03 | code: src/research_agent/beta/chat.py#answer_question | tests: tests/beta/test_chat.py | status: pending -->

A known paper topic must produce claims supported by stored paper or run references. A topic with no supporting records must state that lack of support. Failure must return a retriable error without displaying an unsupported paper claim. The server and browser must distinguish those cases from an ordinary successful answer.

The current server sets `supported` to `bool(links)`. Island context can make that true even when no record supports the requested topic. `test_a_topic_the_store_lacks_still_gets_swarm_context` explicitly observes a supported answer with island and paper context for an absent topic. A nonempty synthesized model answer replaces the retrieval answer without checking each paper-dependent claim against the retrieved records. `ChatPanel` renders the returned answer but does not inspect or show `supported`.

Completion requires known/absent-topic tests through the actual chat service and browser, a synthesized answer with an unsupported paper claim that is refused before display, and a visible no-support or retriable failure state. Existing tests establish retrieval links and fallback receipts; they do not establish answer-to-evidence support or the required browser failure behavior.

#### TDD-7.2.10 Browser conversation state is disposable and links to stored object pages
<!-- id: TDD-7.2.10 | implements: UI-04 | code: apps/swarm-web/src/components/ChatPanel.tsx#ChatPanel | tests: apps/swarm-web/src/components/ChatPanel.test.ts | status: implemented -->

The browser's conversation consists only of the `turns` React state in `ChatPanel`. User, swarm and refusal turns form a discriminated union. The composer and in-flight flag are also component state. The panel contains no transcript-storage write, transcript-fetch endpoint or restoration of conversation turns from local storage.

Chat answers refer visitors to ordinary stored-object pages through encoded paper, run and island links. `ChatPage` adds the session island's existing tree next to the panel; it does not construct a separate chat-owned paper or run record. Leaving and remounting the panel begins with the empty conversation state. The only network mutation initiated by its submit handler is `/api/v1/chat` with the message.

`ChatPanel.test.ts` covers the answer-cost renderer, and backend tests cover stored reference responses. These tests do not currently mount a conversation, clear its browser state and compare durable records. The source implements disposable turns; the full persistence verification remains a separate pending contract.

#### TDD-7.2.11 Chat persists cost receipts without persisting a question transcript
<!-- id: TDD-7.2.11 | implements: UI-04 | code: src/research_agent/beta/chat.py#answer_question | tests: tests/beta/test_chat.py | status: implemented -->

`answer_question` reads existing swarm records and writes cost receipts through `record_cost_receipt`. Every accepted lookup records a `chat_retrieval` receipt with unit `stored_lookup`, quantity one, amount zero and island ownership. That receipt id is `answer_id`. When synthesis is admitted and a model is configured, a separate `chat_answer` tokens receipt records the model call. The response reports its receipt ids and whether paid synthesis was requested, used or refused.

A budget refusal retains a retrieval answer. A model-call failure also falls back to retrieval and records an estimated unsettled receipt for the attempted answer. A successful synthesis records its token usage and returns its amount as this answer's `cost_micros`. These receipts are durable accounting records; the service does not store user or assistant turns as an authoritative transcript.

`test_chat_keeps_no_transcript` asks a question containing a unique marker and scans every non-search-index table to prove the marker was not stored. The paid-within-budget, over-budget and failed/malformed paid-answer tests check receipts, retrieval fallback and receipt survival after rollback. They do not prove that clearing a live browser conversation leaves every durable object family unchanged.

#### TDD-7.2.12 Close the browser-to-storage chat persistence test
<!-- id: TDD-7.2.12 | implements: UI-04 | code: apps/swarm-web/src/components/ChatPanel.tsx#ChatPanel | tests: tests/beta/test_chat.py | status: pending -->

The required integration test must take a snapshot of durable paper, run, feedback, cost and evolution records, use the browser chat, delete or remount its conversation state, and show that the durable records still exist with their original object data. Legitimate chat cost receipts must remain independently available after the conversation disappears.

Current evidence is split. React source owns transient turns, and `test_chat_keeps_no_transcript` proves that a distinctive question is absent from durable table values. Neither test clears browser state after an actual HTTP conversation and verifies the listed durable record families. The browser tests also do not exercise a refusal of a mutation that would exist only in chat state.

Completion requires an integration test across the actual chat and object-service boundaries, including feedback and evolution fixtures and an explicit refusal of chat-only authority. The existing no-transcript test must remain, but it does not substitute for the observable required by the persistence contract.

#### TDD-7.2.13 Shared like controls submit target identities and use server results
<!-- id: TDD-7.2.13 | implements: UI-05 | code: apps/swarm-web/src/components/Like.tsx#Like | tests: apps/swarm-web/src/App.test.tsx | status: implemented -->

`Like` is the shared control used for a paper, run, submitted reading, claim, idea seed and selected agent. Reading claim and idea targets use `{readingId}#{zeroBasedIndex}`. The control reads the stored `likes` map at `{kind}:{id}`, displays the aggregate count and marks the current island's membership. Without a session its button is disabled.

Pressing the control posts `/api/v1/likes` with `{target_kind: kind, target_id: id}`. Island scope comes from the session client rather than an editable browser field. Only a successful response's `like.count` and `like.liked` replace the displayed state. A refusal retains the prior count and liked state and displays the server error in an alert. There is no optimistic local vote before the server answer.

Paper and run pages pass their returned `likes` to these controls. `ReadingView` uses the same owner for the reading, every claim and every idea seed. `GenomeCard` also renders an agent control, though it does not receive a stored likes map. `App.test.tsx` verifies the exact paper payload, server count and second-press reversal in "a like on a paper is one press, counted for every island, and a second press takes it back", and the run/reading/claim/idea controls in the run feedback test.

#### TDD-7.2.14 Shared feedback service stores one toggle per island and target
<!-- id: TDD-7.2.14 | implements: UI-05 | code: src/research_agent/beta/likes.py#toggle_like | tests: tests/beta/test_api.py | status: implemented -->

`POST /api/v1/likes` resolves the authenticated island, validates the target, calls `toggle_like` and commits the transaction. It responds with status 201 and `like` fields `target_kind`, `target_id`, `island_id`, `liked` and aggregate `count`, together with the budget wrapper. Accepted target kinds are `paper`, `run`, `reading`, `claim`, `idea` and `agent`.

One island has at most one active like per target. A second post from that island removes its like; another island's like remains independent and contributes to the total. Indexed claim/idea targets must resolve to an existing reading element. Missing objects return 404, an unsupported target kind returns 422, a forged different island scope returns 403 and an unauthenticated caller returns 401. Agent likes are accepted only after the HTTP owner resolves the genome in the current specification.

`test_a_like_on_any_layer_is_one_per_island_and_becomes_the_agents_points` exercises all six target kinds, exact response fields, reversal, another island's count, stored run/paper projection maps and agent points, then all listed refusal cases. These assertions establish the shared storage shape. They do not establish feedback controls from the chat page or target-history and island-total rendering.

#### TDD-7.2.15 Complete four-page feedback history, totals and unavailable states
<!-- id: TDD-7.2.15 | implements: UI-05 | code: apps/swarm-web/src/components/ChatPanel.tsx#ChatPanel | tests: apps/swarm-web/src/App.test.tsx | status: pending -->

Island, paper, run and chat pages must all submit feedback through the same island-scoped service. The result must appear in target history and island totals. A failed feedback projection or submission must show the required `feedback_unavailable` state without replacing stored values with a fabricated vote.

The browser currently exposes paper, run, reading, claim, idea and agent likes. The selected agent's like is present on the island page, so island feedback is not wholly absent. `ChatPanel` has no feedback control for the returned `answer_id`; the current likes service also has no chat-answer target kind. Counts and agent points do not constitute the required target-history or island-feedback-total display. A failed `Like` post displays the server reason, but there is no complete page-level `feedback_unavailable` contract or four-page persistence test.

Completion requires exercising a feedback action from each of the four page families against one stored feedback shape, then checking target history, island totals and failure behavior. Existing like/API tests remain evidence for their implemented target kinds and do not close this broader UI contract.
