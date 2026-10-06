# Development record

The root [SDD](../SDD.md), [TDD](../TDD.md) and [amendment ledger](../SPEC-AMENDMENTS.md) define the active capped swarm. This file consolidates development reviews and historical notes. Accepted [decisions](decisions/README.md), dated evidence, runtime fixtures and active operating instructions retain their own owners.

## Current implementation review

Reviewed source baseline: `5d886bd`. This review covers the beta backend, swarm browser and their tests. It does not establish deployed behavior or provider qualification.

The implementation is substantial, but complete SDD conformity is not established. Each requirement links several detailed TDD contracts. Implemented parts name their actual owner, data and interface contract, transaction or state boundary, failure behavior and regression evidence. Pending parts state the missing contract inline. A whole requirement is implemented only when all of its linked contracts are implemented.

The current backend suite passed 274 tests, including provider timeout configuration, failed-attempt retention and automatic evolution retry cases. The merged browser passed its production build, lint and all 127 tests. An earlier independent focused backend review passed 159 tests. The original attempt at the broader suite was inconclusive because the temporary filesystem was full; the successful rerun used an isolated directory on the main filesystem. Structural verification uses `python bin/doc-check`, `python bin/doc-check --self-test`, `bin/spec-check --strict --since origin/develop` and `bin/spec-check --self-test`. The exact-head full repository gate is required before merge.

### Requirements to implementation

The root TDD is the detailed mapping. Its trace comments link each technical contract back to exactly one SDD requirement. The SDD lists every supporting TDD contract, so an unlinked implementation item or a missing backlink fails verification. Completion is conjunctive rather than inferred from file existence or test counts.

The most consequential remaining boundaries are release manifest and line-budget gates, receipt-controlled admission, immutable paper-version links, failed extraction presentation, child lineage completeness, assignment feedback inputs, safe executor ownership, scarce-action receipts, evidence navigation, explicit missing traces, settlement-aware displays, cost selection policy, parent-graph rollups, chat-answer feedback and evidence support. These are exact unfulfilled contracts, not requests to expand into forecasting, qualification or a second application.

### Implementation to requirements

| Implemented behavior | Contract authority | Exact remaining boundary |
| --- | --- | --- |
| Current paper metadata, HTML sections and source continuation | IG-01 to IG-04 | Source-version link immutability and visible extraction failure. |
| Human selection and selected-paper context | IG-03, RN-01; [paper selection decision](decisions/0034-select-papers-and-activate-island-reading.md) | Human choices remain authoritative. Root retention and deletion guarantees need explicit reconciliation. |
| Frozen reader cohorts, retries and pacing | RN-01 and RN-03; [cohort recovery decision](decisions/0033-recover-stalled-reading-cohorts.md) | Startup sweeping does not distinguish live work from abandoned work. |
| Validated genome versions, scoped edits, preview and restoration | IS-02, IS-03 and IS-05 | Complete child lineage and copied-source versions. |
| Domain research methods and provenance | IS-03; [research methods decision](decisions/0038-ground-island-prompts-in-research-methods.md) | Existing custom behavior and historical run snapshots remain preserved. |
| Collapsed lineage outline and retained generation records | EV-03 and EV-04; [paper-first and retention decision](decisions/0040-put-kept-papers-first-and-expire-failed-attempts.md) | Changes still need clear per-genome presentation; settled-cost and unavailable-group distinctions remain incomplete. |
| Bounded reading submission, tool policy, events and replay | RN-01 to RN-06, UI-02 | Scarce-action receipt coverage, evidence links and explicit missing traces. |
| Leaf receipts and budget guarded calls | CT-01 to CT-04 | Parent-graph semantics and cost-aware selection differ from the specified contract. |
| Likes, run-count evolution and disposable chat | EV-01, EV-02, UI-03 to UI-05 | Feedback thresholds, preference scoring, chat feedback and synthesized support. |
| Public brief, grade, globe and activity | UI-01; [scope decision](decisions/0035-solidify-capped-swarm-documentation.md) | The grade is descriptive output, not scientific qualification; formula authority remains insufficiently explicit. |
| Historical forecasting, rating and distributed services | Explicit exclusions in CP-04 | Retained maintenance tests do not establish capped-release conformity. |

## Historical development notes

These summaries replace the scattered development Markdown and empty intake scaffold. They retain the earlier system's ownership and limits without restoring its retired requirements. Detailed dated measurements remain under `evidence/`, and original document contents remain in version history. Runtime fixtures keep their original paths because commands and tests consume them. There are no active incoming requirement candidates.

<a id="record-swarm-stabilization-audit"></a>

### Earlier stabilization audit

The earlier audit reproduced ingestion starvation, malformed provider parsing, unsafe startup recovery, unsupported synthesized chat, and diagnostics preceding readings. Continuation, receipt preservation and reading-first order now have direct regression coverage. Safe executor recovery, support distinctions and complete unavailable or unsettled presentation remain unfulfilled contracts. The detailed TDD states those boundaries independently of external work tracking.

<a id="record-readme"></a>

### Historical platform boundary

The earlier platform combined citation forecasting, model qualification, rating workflows and distributed services. Its fixtures and schemas remain for maintenance, but it is excluded from the capped swarm image. Dated evidence establishes only the measured activity and period; it does not qualify the current release.

<a id="record-bulk-acquisition"></a>

### Bulk source acquisition

The historical ingestion owners acquire arXiv requester-pays S3 members, parse archive manifests and record resumable member outcomes. Missing source text remains unavailable rather than invented. Original source permissions and acquisition limits remain in the source-pilot evidence. This path is distinct from the beta metadata and HTML adapter.

<a id="record-corpus-release"></a>

### Corpus assembly

Historical corpus assembly freezes paper-family selection, source bytes, labels, passage records and embedding inputs before release publication. It records completed stages for restart and separates acquisition from numerical fitting. The retained corpus fixtures and tests do not create a current ingestion prerequisite.

<a id="record-front-end"></a>

### Historical owner browser

The historical front-end consumes the distributed platform JSON contracts and preserves private owner, inspector, report and rating distinctions. Its generated types remain tied to docs/contracts/api-v1. Its styles and design mock are maintenance assets, not the swarm browser or an admitted second release app.

<a id="record-launch-runbook"></a>

### Historical launch sequence

The earlier launch sequence acquired a corpus, fitted prediction heads, established Linux service boundaries, qualified providers and retrieval, activated the operating profile and inspected the first batch. Those prerequisites belong to the retired platform. Current startup, configuration and deployment are specified in the beta operating instructions.

<a id="record-linux-boundary-evidence"></a>

### Linux boundary experiments

Disposable Linux and emulated guests tested worker reach, service isolation and pinned image behavior. These experiments did not establish all production firewall, mount, certificate or independent restore guarantees. Dated platform and deployment evidence retain the observed values; they do not authorize operations or prove the current deployment.

<a id="record-local-learning-prerequisites"></a>

### Historical learning inputs

Local learning requires retained source evidence, frozen family selection, label coverage and numerical prerequisites. Unknown targets remain unknown. Those acquisition and fitting rules maintain historical learning code and do not turn current paper ingestion into a qualification pipeline.

<a id="record-numerical-smoke"></a>

### Numerical fitting smoke

The historical numerical smoke established that the selected fitting implementation could execute on the measured embedding shape. It did not establish model quality, retrieval qualification or agreement after later embedding-width changes. Dated model evidence remains the source for measured limits.

<a id="record-rating-frontend"></a>

### Private rating browser

The earlier rating browser used blinded entries, session scope, rating submission and private preference credit. It was development integration evidence rather than study readiness. It is not the active island-session browser and is excluded from the capped release.

<a id="record-remote-embedding"></a>

### Remote embedding import

Historical remote batches exported pinned passage inputs, computed embeddings on a remote device and imported vectors only after local agreement checks. Sync, source identity and platform equivalence were explicit boundaries. This workflow is not part of the beta runtime.

<a id="record-source-pilot"></a>

### Source acquisition pilot

The historical pilot selected canonical paper families, acquired source material, recorded deterministic unavailable outcomes and resumed completed stages. Permissions, snapshot coverage and bibliography matching remain dated evidence. The pilot does not establish full current source qualification.

<a id="record-storage-foundation"></a>

### Historical storage foundation

The distributed storage service used immutable artifacts, role-scoped certificates, transaction ledgers, fenced job leases and scoped publication. Administrative connection refusal and idempotent replay were maintenance boundaries. SQLite beta persistence is a separate current owner; historical service interfaces are not implied beta contracts.

<a id="record-launch-population"></a>

### Historical seed population

The retained docs/launch/seeds.json fixture defines earlier study procedures for three research islands. The seed-population command validates the full fixture and admits immutable configuration hashes; rerunning unchanged content does not admit new configurations. Current beta founders and research-method profiles are defined in beta/spec.py.

<a id="record-alignment"></a>

### Historical design alignment

The design mock recorded presentation rules and field provenance for private owner, rating, inspector and report pages. Missing values were absent rather than fabricated, and forecasts remained separate from preferences. Current swarm layout, lineage and reading display are defined by active UI contracts.

<a id="record-contract-v1"></a>

### Historical browser transport contract

The earlier front-end transport used JSON envelopes, cookie sessions, CSRF protection, idempotency keys and opaque list cursors. These rules serve the retained historical schemas and consumers. The active swarm browser instead uses its documented beta requests and signed bearer session.

<a id="record-contracts"></a>

### Historical browser data ownership

The distributed platform web applications assembled browser view models from role-scoped storage clients; the browser never held storage client certificates. Rating, inspector, report and owner views had distinct authorization and withheld fields. This remains historical ownership context, not a second current application.
