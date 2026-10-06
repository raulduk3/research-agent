# Capped swarm stabilization audit

Audit baseline is `origin/develop` at `fc9b866`, recorded on 2026-10-06. The existing `fix/flexible-run-band` checkout contains unmerged #422 and was excluded from this baseline. No live deployment was inspected or changed. This record supports #423 and decision 0035.

## Active feature inventory

| Feature | Owner | Existing evidence | Remaining boundary |
| --- | --- | --- | --- |
| Current arXiv intake and HTML text | `beta/ingest.py`, `papers.py`, `text.py` | Ingestion and text tests | Continuation stalls beyond the newest source window, #425. |
| Island assignment and selection | `beta/islands.py`, `papers.py` | Ingestion, run and API tests | Category and keyword scoring omits specified feedback and genome demand. Human selection remains authoritative under decision 0034. |
| Signed island login | `beta/auth.py`, `app.py` | API tests | One island-scoped session, no durable chat transcript. |
| Genome revisions and lineage | `beta/spec.py`, `evolution.py` | Spec and evolution tests | Declared scoring preferences and copied field/version detail need reconciliation. |
| One-paper run and bounded tools | `beta/runs.py`, `service.py` | Run and service tests | Recovery and executor ownership, #427. Unmerged limit-band behavior remains #421/#422. |
| Evidence-bearing readings and replay | `beta/runs.py`, `projections.py`; `ReadingView`, `Replay`, `PaperViewer` | Run and browser tests | Readings-first page order, #424. |
| Budget guards and receipt ledger | `beta/budget.py`, `costs.py`, `models.py` | Budget and cost tests | Malformed provider accounting, #426; unsettled display, #428; incomplete tool/genome cost coverage. |
| Persisted likes | `beta/likes.py`; browser `Like` | API and browser tests | Contract requests signal/note/chat targets that the toggle does not implement. |
| Rapid evolution | `beta/evolution.py` | Evolution tests | Run-count breeding exists; feedback threshold, health/usefulness scoring and cost tie-break do not. |
| Disposable chat | `beta/chat.py`; `ChatPanel` | Chat and API tests | Synthesized support and browser interaction, #428. |
| Public storm, activity and brief | `beta/brief.py`, `app.py`; `Splash`, `Globe` | Brief and browser tests | Existing public entry belongs to the same app. Live service health remains unverified, #420. |
| Beta packaging | `deploy/beta/Dockerfile`, pinned requirements | Deployment tests | Copies only beta; declared manifest and source line-budget gates remain absent. |

Backend paths in this table are relative to `src/research_agent/`. Browser paths are under `apps/swarm-web/src/`. The historical `front-end/`, forecasting, qualification, Jev, OCR, model training and distributed-service code are outside the active release. Their retained tests are maintenance coverage, not proof of capped swarm behavior. The beta image already excludes that Python code.

## Ranked findings

1. Ingestion starvation is reproduced. `beta/ingest.py:133` requests `start=0`; line 214 scans the newest twenty entries; line 282 writes a cursor without reading it. A stable twenty-five-record feed admits twenty papers, then subsequent passes admit zero. #425 requires continuation without duplicates.
2. Malformed provider output escapes the accounting failure type. Parsing outside the protected boundary at `beta/models.py:130` raises `AttributeError` for an invalid message shape and `ValueError` for invalid usage. `beta/runs.py:1548` records unsettled costs only for `ModelCallFailed`; generic failure becomes `harness_error`. Lost receipt accounting is inferred from these exception paths, not reproduced through all callers. #426 covers run, chat and evolution accounting, including transaction rollback.
3. Startup recovery can fail another live process's work. `beta/service.py:46` calls the sweep at `beta/runs.py:934`, which fails every queued/running row without ownership or stale-time checks. A second preparation over the same temporary database fails the first process's queued run. #427 also covers inferred duplicate-executor risk. That race has not yet been reproduced.
4. Chat support is overstated. `beta/chat.py:376` accepts arbitrary synthesized prose and line 382 marks it supported when retrieval has links. A scripted invented, unlinked experiment reports `supported=True`. #428 requires supported-answer behavior to follow evidence rather than link existence.
5. The pages put operational detail before useful output. Paper readings are in closed details at `pages/Paper.tsx:179`. Run reading follows replay, genome and cost tables at `pages/Run.tsx:165`. Island agents precede paper output at `pages/Island.tsx:114`. #424 moves existing output forward and preserves diagnostics and evidence links.
6. Failed projection groups appear empty in the paper UI. The backend returns `unavailable` at `beta/projections.py:343`; `pages/Paper.tsx:137` and line 170 show no island or run messages instead. Run projection sums all settlement states at `beta/projections.py:242`, while `pages/Run.tsx:77` labels that value settled. #428 covers both distinctions.
7. Contract drift remains explicit. All thirty-two prior traces pointed to #378, a closed account-model issue unrelated to most capped requirements. Most TDD owners were planned paths rather than beta paths. The updated TDD names real owners and records absent gates. Feedback, assignment and evolution discrepancies remain under #423 rather than being silently marked implemented or expanded into new systems.

## Page hierarchy

Paper pages lead with title and visible readings, then source metadata, assignments, runs and cost detail. Completed-run pages lead with the submitted reading, then replay, genome and detailed costs. Runs with no reading lead with live or failed status. Island pages lead with paper output and current reading activity before genome and evolution controls. Empty readings and unavailable readings have different states. These changes reuse the current data and components.

## Verification

- `bin/check --since origin/develop` passed the original strict specification checks and negative-case self-tests, Ruff lint and formatting, and strict mypy over 321 source files. It stopped at pytest because `RESEARCH_AGENT_TEST_DSN` is not configured. The complete repository gate is not verified.
- `uv run --locked pytest tests/beta -q` passed 194 tests.
- `python bin/check-front-end --app apps/swarm-web` passed the locked install, production build, lint and 94 tests.
- `python bin/check-front-end --app front-end` passed generated schema comparison, production build, lint and 112 historical browser tests.
- `PYTHONPATH=. uv run --locked python docs/evidence/stabilization/reproduce.py` confirmed ingestion starvation, startup sweeping, unsupported chat labeling and malformed parser exceptions using temporary SQLite stores and scripted clients or HTTP MockTransport. It made no paid or network calls. The [reproduction script](../evidence/stabilization/reproduce.py) asserts the defective baseline behavior; successful repairs will intentionally invalidate those assertions.
- Both front-end negative-case self-tests caught a planted type error and a failing test. Final `bin/spec-check --strict --issues --since origin/develop` passed all 32 paired items. The checker self-test confirms root relocation still rejects an unrecorded requirement change.

Passing existing tests did not detect the reproduced defects. Deployment state, provider qualification and actual monthly spending are unverified. A merge is not deployment authorization.

## Bounded stabilization order

1. Land the root contract consolidation and owner mapping under #423.
2. Repair provider receipts under #426 and active-run ownership under #427 before more paid execution.
3. Repair source continuation under #425 and readings-first page order under #424 as independent changes.
4. Repair supported chat, unavailable groups and settlement-aware display under #428.
5. Resolve feedback, assignment, evolution and release-gate discrepancies against the capped contract under #423. Complete only the agreed release behavior.
6. Run the full repository gate with its required PostgreSQL prerequisite. Live verification and deployment remain a separate explicitly authorized operation under #420.

No forecasting, training, qualification platform, second browser application or new paid capability enters this sequence.
