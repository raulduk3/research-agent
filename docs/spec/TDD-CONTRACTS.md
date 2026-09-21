# Shared implementation contracts

This companion to TDD.md fixes common interfaces used by its requirement-specific items. Decision #77 and implementation design #71; planned owners, not existing code. SDD and its launch/learning/retrieval profiles define behavior. A disagreement is a defect to reconcile, not permission to choose a second implementation. All services use the same versioned Python contract package in `src/research_agent/contracts/`.

## Identity, time and serialization

`ArtifactHash` is a lowercase 64-hex SHA-256 over actual bytes; JSON artifacts use one canonical serializer (`contracts/canonical.py`). Normalize Unicode strings to NFC, reject duplicate keys before and after normalization, sort object keys, preserve array order, emit UTF-8 without whitespace, and reject nonfinite floats. Python's round-trip numeric rendering is pinned by the runtime; fixture bytes include negative zero, Unicode and exponents. Never normalize raw provider/PDF/model bytes before hashing them. A stored payload sanitized for retention has a different identity from transport bytes, with a policy-id bridge.

`RecordId` and `RunId` are UUIDv4 identifiers from the standard library; randomness is not study sampling. `PaperFamilyId` is a storage-issued stable UUID with an immutable external-id mapping history; never merge uncertain bibliography titles. `PaperVersionId` identifies a family plus original external version and source hash. Immutable manifest ids are content hashes. A human-readable model/rubric alias is never an immutable identity. Target ids and their order are exactly those in LEARNING-PROTOCOL.md.

Instants are UTC RFC3339 strings with microsecond precision and a Z suffix, stored as timestamptz. Source dates are intervals, not fabricated exact instants. Separate `source_event_interval`, `captured_at`, `available_at`, `created_at` and `imported_at`. Runtime durations use monotonic elapsed values; wall-time reports use recorded UTC pairs with explicit clock-domain checks. Nonnegative integer budget counters with positive configured limits and money in integer USD microdollars avoid float accounting. No schema coerces strings to numbers, booleans to counts or NaN to unavailable.

Each immutable manifest includes `schema_version`, `artifact_hash`, ordered `input_hashes`, `producer_version`, `config_hash`, `created_at`; additional typed provenance belongs to the specific manifest. `schema_version` is an explicit integer, initially 1. Unknown versions fail closed, never silently deserialize as the current version. Binary float32 vectors carry little-endian dtype, shape, representation id, feature/source hash and payload checksum; similarity accumulation is float64. Vector coordinates are not agent-visible.

## Ownership and durable state

Only storage connects to PostgreSQL and mounts the persistent artifact tree writable. Storage's public application API is `/v1`; model/reader/ingest/scorer workers compute and submit typed commands. Shared Python contracts are not a second storage client with SQL privileges. Worker's temporary scratch data is bounded and disposable; no recovery depends on it. The local model service streams verified weight/tokenizer artifacts through storage into a disposable private cache; the separately managed inference host uses its own operator-provisioned immutable model cache. Neither mounts another application component's writable volume. Agent workers mount no weights.

Storage table families and invariants:

| Owner tables | Key and constraint |
| --- | --- |
| `artifacts`, `artifact_edges`, `artifact_tombstones` | Hash primary key; finalized bytes immutable; edges reference committed inputs; tombstone disables retrieval without rewriting permitted ledger metadata |
| `paper_families`, `paper_versions`, `external_id_observations` | Stable family id; provider/version identities retained; uncertain merges produce findings, never title-based guesses |
| `jobs`, `job_attempts`, `job_checkpoints` | Job id plus monotonically increasing lease epoch; checkpoint references committed artifact hashes |
| `ledger_records`, `ledger_head`, `anchor_receipts` | Unique sequence and record id, previous-record hash, typed payload hash; append-only application privileges |
| `snapshots`, `snapshot_members` | Content-hashed manifest with exact versions/cards/graph/target/bundle ids; sealed membership never changes |
| `run_slots`, `runs`, `run_events`, `tool_receipts` | Unique batch/shard/configuration/arm/attempt slot; ordered run event sequence; immutable request/response hashes |
| `submissions`, `forecasts`, `nominations` | Unique run submission plus content hash; one accepted submit per run; one answer per issued question |
| `model_bundles`, `active_bundles`, `qualification_records` | Immutable bundle manifests; one compare-and-swap pointer per compatible registry/representation namespace |
| `digests`, `digest_entries`, `ratings`, `human_forecasts` | Unique batch digest watermark; unique paper per digest; rater events append rather than rewrite audit history |
| `spend_authorizations`, `spend_reservations`, `spend_charges` | Immutable authorization identity; transactional daily/monthly capacity checks; no negative or duplicate reconciliation |
| `alerts`, `audit_events`, `study_registrations` | Immutable event ids; authenticated acknowledgment separate from display; actual external/import times kept |

Migration owner `storage/migrations/` creates constraints and schema version. Startup refuses unsupported schema; no auto-destructive downgrade. A transaction that serializes ledger append locks the head row, allocates sequence, validates previous hash, appends typed record and updates head atomically. Retry serialization conflicts only on the same idempotent command. Artifact write order is temp/write/checksum/fsync/atomic rename/fsync directory, then DB references. If a crash leaves a verified unreferenced blob, retry can reuse it by hash; no partial bytes are served. Garbage collection consults references, leases and retention, preserving required tombstones. The DB superuser is not an application principal; independent anchors expose later privileged rewrites.

## HTTP and command contracts

Service-to-service TLS with operator-provisioned certificates authenticates a service role; endpoint permissions are server-side, independent of request fields. Agent access is only through tools using an opaque run-scoped capability, never a storage certificate. Storage checks the caller's role and artifact/snapshot scope on every route. Credentials are mounted at runtime and omitted from logs/artifacts.

Commands use `schema_version`, `command_id`, `request_id`, `payload` and an idempotency key. Store the canonical payload hash with the key. Identical retries return the original committed response; a changed payload receives 409 `idempotency_conflict`. Domain-specific unique constraints prevent two different command ids from duplicating an accepted submission or ledger event. A 202 response means queued, never committed. Committed responses identify affected records/artifact hashes and a ledger sequence when that command appends ledger records.

Responses use `{schema_version, request_id, status, data, error}`; status is ok/unavailable/error: ok carries data and null error; unavailable/error carries null data and a typed error object. Per-field unavailable states can occur inside otherwise successful card data. Unavailable never silently means zero. Errors have stable `code`, safe `message`, `retryable` and evidence ids when allowed. HTTP mappings: 400 malformed JSON/duplicate keys, 401 unauthenticated, 403 forbidden, 404 absent-or-not-visible artifact, 409 state/idempotency conflict, 422 invalid typed input, 429 bounded capacity rejection, 503 temporarily unavailable. Do not expose hidden artifact existence through distinct responses. Internal finite bounded retries do not override provider-specific no-ambiguous-retry policy.

Storage-owned routes (typed request/response models in `contracts/storage.py`):

| Route | Contract and caller |
| --- | --- |
| `POST /v1/artifacts` | Stream bytes with expected hash/type/provenance; stage/check/commit; authorized producer role only |
| `GET /v1/artifacts/{hash}` | Exact permitted bytes or tombstone/unavailable; scoped internal role; no agent direct access |
| `POST /v1/paper-observations` | Ingest adds preserved provider identity/version/source observations and effective availability |
| `POST /v1/jobs/claim`, `/v1/jobs/{id}/renew`, `/checkpoint`, `/complete` | Claim returns lease epoch; every update compares owner/epoch/expiry. A stale worker cannot commit |
| `POST /v1/snapshots/seal` | Orchestrator supplies committed membership and cutoff; storage checks provenance/time/compatibility and hashes exact membership |
| `GET /v1/snapshots/{id}/...` | Tools/reader receive scoped immutable cards, graph, passages and question definitions; no unscoped search for an agent |
| `POST /v1/runs`, `/v1/runs/{id}/events` | Orchestrator creates declared slot; authenticated run/event writer appends ordered status and request/response records |
| `POST /v1/runs/{id}/submit` | Tool service passes validated payload; storage rechecks slot, deadline, snapshot, retrieved evidence, uniqueness and budgets in one transaction |
| `POST /v1/bundles/activate` | Models/orchestrator submits expected-old/new ids plus qualification identity; CAS rejects mismatch without partial pointer changes |
| `POST /v1/digests` | Orchestrator supplies batch id and terminal-slot watermark only; the storage-owned digest projector reads nominations and commits deterministic entries, avoiding orchestration access to agent prose |
| `POST /v1/ratings`, `/v1/human-forecasts`, `/v1/alerts/{id}/ack` | Rating backend supplies authenticated pseudonymous rater; server enforces visibility, consent/action, deadlines and blinding |
| `POST /v1/spend/reserve`, `/v1/spend/{id}/reconcile` | Authorized orchestrator/ingest; atomic caps and prior authorization; unresolved charge stays reserved |
| `POST /v1/studies/import`, `/v1/anchors/receipts` | Restricted operator/storage integrations import evidenced records with actual times and verified signatures |

All routes have explicit typed payloads in their owning TDD item; they cannot accept arbitrary SQL, paths, tool names or Python execution. HTTP path segments are opaque ids, never filesystem paths. Protect file lookup with hash validation and directory confinement. Default body caps derive from the called artifact/tool contract; transport cannot bypass a smaller domain cap.

## Run lifecycle and inter-service boundaries

Scheduler creates all four population slots per shard before dispatch, and two separate with/without-Jev evidence-first comparison slots per eligible study shard. Slot identity includes arm so comparison runs cannot overwrite population runs. All six consume the same global concurrency/spend limits. Comparison runs do not nominate into the population digest and are not reused as population runs. A pair's assigned arm is fixed before requests; preserve missing/failed arm outcomes. Capacity qualification includes these additional calls, not just four population slots.

A run progresses queued -> running -> submitted, void or missed_deadline. Starting a run pins the run spec and immutable snapshot; a run finishing after its question seal deadline cannot obtain forecast credit. Reservations/deadline checks precede calls; consumed resources are committed even on provider errors. Tool receipts record requested ids, actual visible evidence ids, result bytes and counters. Storage validates submit against receipts, preventing invented evidence ids. Every validation failure rejects the complete attempt and records submission_rejected; no partial forecast subset is sealed. Horizon and resolver derive from the issued question, not agent fields. Human/baseline producers use authenticated view/input receipts with equivalent snapshot scope. A terminal run permits only exact receipt replay, not additional reading, changed submissions or budget reset.

The operator-owned host launcher starts only the declared worker image, fixed mounts, network policy and resource limits from an admitted run spec. It accepts an authenticated orchestrator request, not arbitrary container arguments. It is a constrained deployment adapter, not agent-accessible tooling; workers and web app have no Docker socket. A launcher failure produces a slot failure. Reconciliation after process restart reads durable slots before attempting any work; no automatic second sample is created for an ambiguous model completion.

Tools are `query_cards`, `neighbors`, `graph`, `deep_read`, `submit` only. Their exact argument schema lives in `contracts/tools.py`, generated from one shared schema owner for server validation and model declarations. No hidden extra tool fields are inferred from prose. Model transport turns include protected action summary/intent as structured fields and zero or more declared tool calls; summaries describe actions/evidence rather than private reasoning. The adapter validates the complete response envelope before executing calls sequentially in declared order. The first accepted submit ends execution; later calls in that response are not executed. A rejected submit returns structured errors and remaining budgets and permits correction on a later turn within the unchanged run limits. Budget/deadline validation repeats before each call, preventing a parallel-call array from overspending.

## Bootstrap, qualification and operations separation

Collection mode runs storage/ingest only; engineering adds the local reader/models/tools plus deterministic recorded-response execution with explicit unqualified outputs; study mode requires the full activation manifest. Common readiness code evaluates evidence records, not `all=true` operator assertions. Actual host addresses, certificate references, permission evidence, backup receiver, quotes and funding are DeploymentBindings under #76; secrets are external references. An incomplete binding cannot become an invented default.

An operator preflight writes a signed local report before the database starts; storage then imports its exact hash and original time. Offline comparisons likewise preserve signed registrations before comparison execution; import records `registered_at`, evidenced result time and `imported_at` separately. Import validates signatures against admitted operator keys and artifact hashes, records verification evidence and refuses registration after comparison execution begins. A signature alone does not prove historical timing: preserve independent timestamp evidence (for example a prior published commit or trusted timestamp receipt); unverifiable chronology cannot qualify activation. Runtime registrations use existing ledger order.

Work queues, permits, active pointers and audit commands are tested against real PostgreSQL and artifact storage; deterministic boundary fixtures test clocks, sources and model response parsing. Default CI never rents a GPU or invokes paid APIs. Real embedding/agent/Jev qualification is a separate explicit command that writes immutable measured evidence and refuses missing permission/funding. Preserved provider responses test adapters without claiming live provider capability. All output schemas expose unavailable reasons, eligible denominator and version so engineering results cannot be labeled prospective study evidence.

Implementation sequence: storage/identities -> source capture and replay -> labels and extraction/retrieval -> fitted heads and Jev -> bounded runs/digest/ratings -> full evaluation and operations qualification. Build one end-to-end path before widening concurrency. Immutable artifact checkpoints are the unit of reuse; changes invalidate only dependent artifacts. No implementation lane starts against an unaccepted competing interface.

Harness-only run-event and budget-reservation endpoints on the tool service accept the same scoped run capability, validate ordered request/response ids and proxy durable writes to storage under the tool-service role. They are not model-visible tools. Thus request logging and reservations precede model execution without giving a worker direct storage access. A single budget owner in storage fences concurrent calls. The tools proxy cannot select arbitrary storage commands from a worker payload.

Sampling seeds: `specification_seed` is the first unsigned 64 bits of SHA-256 over canonical slot identity plus profile hash; `request_seed` is the first unsigned 32 bits of SHA-256 over run_id, turn_index and the literal sampling-v1 domain. Store both with each request and read them unchanged during replay. Study sampling/shuffling uses separate domain-separated seeds defined by each profile algorithm. These seeds do not promise deterministic model generation.

## Restricted projections and common numerical fitting

`GET /v1/scoring-inputs/{manifest_id}` exposes forecast ids/probabilities, target definitions, resolution states, eligible support and hashes only. The production scorer cannot retrieve general artifacts, paper content, cards, assessments or baseline covariates. A separate baseline-producer principal uses `GET /v1/baseline-inputs/{snapshot_id}` for only the permitted counts, raw head logits, scalar distances, masks and earlier known labels with lineage. Sharing a Python package does not share credentials or role permissions. Baseline computations run as admitted batch jobs; they do not introduce another service or neural-model copy. The deterministic scorer only consumes their sealed forecasts.

Private rating routes serve explicit projection models, never generic artifact JSON. Strip hidden producer/configuration/control-source identity recursively, including nested provenance and linked URLs. Per-entry labels do not carry across papers. Rater detail unlock depends on that rater's own stored rating; direct artifact/snapshot routes are forbidden. HTML escapes preserved source and rationale text. These controls hide assigned origin, not a guarantee that writing style cannot suggest it. Human evidence-view receipts have their own authenticated rater/snapshot scope.

PredictionArtifact preserves raw pre-calibration linear head score internally alongside calibrated probability; public cards carry the calibrated value and allowed provenance only. The common numeric owner `learning/logistic.py#fit_binary_logistic` accepts a finite 2-D matrix, binary labels, fixed regularization and convergence settings, and returns weights/intercept/diagnostics. `learning/fit.py#fit_head` first enforces the exact 2048-dimensional representation-only head contract and target mask. Baseline wrappers enforce their own fixed one- or four-feature schema before calling the same numeric owner and calibration routines. Generic numeric fitting never grants a caller permission to supply forbidden head features or change temporal partitions.

Model tool schemas expose domain arguments only. The trusted harness binds schema_version/run_id/snapshot_id and the actual native tool_call_id into the internal HTTP request from its immutable run context; model-supplied authority fields are invalid. Server-side envelope checks authenticate that binding before domain validation.

A run terminal state submitted maps to its scheduler slot state completed; void/missed_deadline remain explicit. The mapping commits with the same submission transaction and cannot be inferred from a worker process exit code alone.
