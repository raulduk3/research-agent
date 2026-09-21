# Operations and activation contract shapes

Normative implementation detail for SDD SR-13/SR-16/SR-28, PL-03 to PL-19, IN-21/IN-22/IN-25 to IN-27 and TDD section 2.1. Names refer to closed records: every field is required unless explicitly marked optional; null is a value, not omission. Unknown keys, implicit conversions and unknown enum values are rejected. These are planned application contracts, not credentials or populated deployment evidence. Common aliases are defined in INDEX.md.

## Deployment bindings and permissions

```text
ExecutionMode = "collection" | "engineering" | "study"
GateStatus = "verified" | "unset" | "blocked"
SecretRef = string[1..240] matching ^secret://[a-z0-9_/-]+$
Endpoint = { url: HttpsUrl, tls_server_name: NonEmptyString,
             ca_certificate_hash: Sha256, credential_ref: SecretRef | null }
HostObservation = { observed_at: UtcInstant, os: "linux", architecture: "x86_64",
  logical_cpu_count: PositiveInt, memory_bytes: PositiveInt,
  persistent_storage_bytes: PositiveInt, free_storage_bytes: NonNegativeInt,
  gpu_devices: list<GpuDevice>, evidence_hash: ArtifactId }
GpuDevice = { device_id: NonEmptyString, model: NonEmptyString,
              memory_bytes: PositiveInt }
Binding<T> = { status: GateStatus, value: T | null,
               evidence_hashes: list<ArtifactId>, reason: NonEmptyString | null }
SourcePermission = { permission_id: RecordId,
  source_id: "arxiv" | "openalex" | "jev" | "hf_daily_papers" | "embedding_weights" | "agent_weights",
  reviewed_at: UtcInstant, terms_hash: ArtifactId,
  decision: "allowed" | "denied" | "unknown",
  permits_capture: bool, permits_derived_artifacts: bool,
  permits_retained_responses: bool, permits_hosted_processing: bool,
  retention_deadline: UtcInstant | null, evidence_hashes: list<ArtifactId> }
DeploymentBindings = { schema_version: 1, bindings_id: RecordId,
  profile_hash: ArtifactId, created_at: UtcInstant,
  application_host: Binding<HostObservation>,
  inference_endpoint: Binding<Endpoint>,
  anchor_receiver: Binding<Endpoint>, backup_destination: Binding<Endpoint>,
  private_app_origin: Binding<HttpsUrl>,
  rater_ids: list<RecordId>[2], operator_id: RecordId,
  source_permissions: list<SourcePermission>,
  deployment_manifest_hash: ArtifactId | null,
  funding_authorization_id: RecordId | null,
  secret_inventory_ref: SecretRef, signing_key_ref: SecretRef }
```

Binding invariants: verified means non-null value, at least one independently readable evidence artifact, and null reason. Unset/blocked means null value and non-null reason; failed observations can be retained in evidence, not exposed as an active value. No service can toggle verified without the corresponding typed validation. Every source id occurs at most once per manifest. A permission with unknown/denied cannot enable that source. Disabled optional sources may have no row; study-required sources/models may not. Equality to configured allowlists is checked after normalized URL parsing: HTTPS only, no userinfo, fragments or embedded credentials. Internal service names and the private origin resolve only on the declared networks. The deployment verifier checks actual routes/certificates; string validation alone proves no network isolation.

`secret://` references resolve only from the runtime secret mount by the owning component. Values never enter manifests, HTTP bodies, logs or examples. The operator signs the canonical binding payload; the signature wrapper is separate from payload bytes. Two rater identities are distinct and non-operator by default role; operator access is a separate explicit role, never inherited by an agent. Source review does not grant unrestricted data access to a rater.

Qualification owners #59/#55 supply provider/endpoint evidence; #76 assembles these bindings; #74 consumes them. These are not additional approval decisions to finish the TDD.

Signed<T> is `{payload:T, signature:SignatureEvidence}` using STORAGE.md's exact signature record. Verify the signature over canonical payload bytes; the immutable stored signed-envelope artifact hashes the complete envelope, including the signature. Thus neither a signature nor a self-hash is included in its own signed/hash preimage. Deployment submission accepts Signed<DeploymentBindings>, not an unsigned manifest.

`PreflightReport = {schema_version:1, preflight_id:RecordId, profile_hash:ArtifactId, mode:ExecutionMode, host:HostObservation, captured_at:UtcInstant, minimums:{logical_cpu_count:16,memory_bytes:68719476736,persistent_storage_bytes:1099511627776,initial_free_storage_bytes:536870912000,gpu_device_count:0}, passed:bool, failures:list<NonEmptyString>}`. It is a signed operator artifact written before application services start. Storage later imports Signed<PreflightReport> and stamps its actual import time; this preflight has no fictitious database watermark.

## Spending and rental authorization

```text
Money = int64[0..9223372036854775807]  // USD microdollars
CostClass = "inference_rental" | "inference_storage" | "jev" | "scholarly_api"
CostQuote = { quote_id: RecordId, provider_id: NonEmptyString, class: CostClass,
  observed_at: UtcInstant, valid_until: UtcInstant,
  source_hash: ArtifactId, currency: "USD", unit: "request" | "hour" | "byte_day",
  price_per_unit_microdollars: Money, billing_quantum_units: PositiveDecimal,
  minimum_charge_microdollars: Money, fixed_charge_microdollars: Money,
  taxes_and_fees_included: bool, maximum_total_is_bounded: bool }
SpendAuthorization = { authorization_id: RecordId, operator_id: RecordId,
  profile_hash: ArtifactId, created_at: UtcInstant, valid_from: UtcInstant,
  expires_at: UtcInstant, paid_execution_enabled: bool,
  daily_limit_microdollars: Money, monthly_limit_microdollars: Money,
  jev_daily_limit_microdollars: Money, scholarly_daily_limit_microdollars: Money,
  rental_seconds_per_day: NonNegativeInt,
  quote_ids: list<RecordId>, allowed_classes: list<CostClass>,
  action_evidence_hash: ArtifactId }
SpendReservationRequest = { reservation_id: RecordId, authorization_id: RecordId,
  quote_id: RecordId, class: CostClass, operation_id: RecordId,
  worst_case_microdollars: Money, rental_seconds: NonNegativeInt,
  allocations: list<SpendAllocation>[1..2] }
SpendAllocation = { accounting_day:UtcDate, accounting_month:YearMonth,
  worst_case_microdollars:Money, rental_seconds:NonNegativeInt }
SpendReservation = { request: SpendReservationRequest, created_at: UtcInstant,
  state: "reserved" | "settled" | "released" | "disputed",
  charged_microdollars: Money | null, billing_evidence_hash: ArtifactId | null }
SpendReconciliation = { reservation_id: RecordId,
  disposition: "settled" | "released" | "disputed",
  charged_microdollars: Money | null, actual_rental_seconds: NonNegativeInt | null,
  actual_allocations: list<ActualSpendAllocation>[0..2], billing_evidence_hash: ArtifactId }
ActualSpendAllocation = { accounting_day:UtcDate, accounting_month:YearMonth,
  charged_microdollars:Money, actual_rental_seconds:NonNegativeInt }
RentalPermit = { permit_id: RecordId, reservation_id: RecordId,
  deployment_manifest_hash: ArtifactId, issued_at: UtcInstant,
  stop_no_later_than: UtcInstant, idle_stop_seconds: 600,
  operator_action_evidence_hash: ArtifactId }
```

Authorization starts disabled with zero caps. Enabled limits cannot exceed profile ceilings: 25,000,000 daily and 300,000,000 monthly microdollars, 2,000,000 Jev and 2,000,000 scholarly daily sublimits, 14,400 rental seconds/day. A lower explicit funding cap wins. Validity requires `valid_from <= now < expires_at` and a current quote (`now < valid_until`); quote units, provider identity and operation class must agree. Costs round upward to microdollars and provider billing quanta; unknown fees/unbounded charges prohibit a reservation. External taxes are included in a preserved worst-case bound, never assumed zero. No runtime operation can enlarge authorization.

Reservation transaction: authenticate role, validate quote/authorization, lock authorization and relevant UTC day/month counter rows in lexical order, check `settled charges + unresolved reserved worst cases + requested worst case <= cap`, check class/rental sublimits, insert unique `(authorization_id, operation_id)` reservation and update counters. Commit before the external request. Concurrent callers cannot each observe the same remaining budget. An identical retry returns the stored reservation; changed cost/operation bytes under the key fail 409. All overflow arithmetic fails closed.

Ambiguous provider completion leaves the full reservation outstanding. Explicit unexecuted rejection plus preserved billing evidence may release it; absence of a receipt is not evidence of zero cost. Settlement cannot double-count a reservation. If actual charge exceeds its reserved bound, record the actual bill, flag a bound violation and block new paid calls pending operator disposition; do not clip financial evidence to make a cap look respected. No reconciliation automatically raises the cap. Do not start an operation crossing a billing boundary without reservations for its maximum exposure in both affected periods; unknown spillover blocks execution. Persistent rental storage is independently reserved even when compute is stopped.

The rental controller runs outside agent containers under operator authority. A permit is evidence of previously authorized action, not self-authorization to provision. It stops at the earlier authorized deadline or 600 seconds idle. Lifecycle states are `not_started -> starting -> running -> stopping -> stopped`, with `failed` possible from each active state. Start failure preserves charges and produces evidence. Lost stop acknowledgment triggers an alert and continued billing reconciliation, not an assumption that the rental is free/stopped. Controller state/evidence persists through storage; no worker receives cloud credentials.

## Qualification and readiness

```text
GateKind = "host_floor" | "source_permission" | "source_feasibility" |
  "representation" | "retrieval" | "heads" | "jev_provider" | "jev_content" |
  "jev_registration" | "agent_capability" | "funding" | "private_access" |
  "backup_restore" | "anchor" | "daily_capacity" | "mode_services" |
  "local_model_compatibility" | "replay_assets"
GateResult = { kind: GateKind, state: "pass" | "fail" | "unavailable",
  subject_hash: ArtifactId, evidence_hashes: list<ArtifactId>,
  checked_at: UtcInstant, reasons: list<NonEmptyString> }
ReadinessReport = { schema_version: 1, report_id: RecordId,
  mode: ExecutionMode, profile_hash: ArtifactId, bindings_id: RecordId,
  checked_at: UtcInstant, storage_watermark: PositiveInt,
  gates: list<GateResult>, ready: bool }
ActivationRequest = { mode: ExecutionMode, profile_hash: ArtifactId,
  bindings_id: RecordId, expected_active_manifest_hash: ArtifactId | null,
  readiness_report_hash: ArtifactId }
ActivationReceipt = { activation_id: RecordId, mode: ExecutionMode,
  active_manifest_hash: ArtifactId, previous_manifest_hash: ArtifactId | null,
  ledger_sequence: PositiveInt, activated_at: UtcInstant }
```

Gate identity includes exact representation, target registry, rubric/provider identity, model deployment, comparison registration and actual source manifests as relevant. A pass for a different identity is not a pass. The readiness owner recomputes `ready`; clients cannot assert it. Gate sets per mode are explicit: collection requires host_floor, source_permission for active sources, private_access and mode_services (storage/ingest); engineering additionally requires local_model_compatibility and replay_assets and extends mode_services to the local required components, while recording model/retrieval outcomes as unqualified; study requires all GateKind cases, all three qualified heads, required rubric fields and mode_services covering all study components. Missing head outcome maturity does not block the preregistered Jev launch exception, while missing Jev content qualification does.

Check creation time, subject identity, applicable suspension/correction records and replayable evidence at activation. Current suspensions affect new study activation or future card publication, not bytes in historical snapshots. Activation uses CAS on the active deployment manifest after validating evidence in one storage transaction; an intervening changed pointer/permission/suspension makes it conflict, not silently activate stale evidence. Readiness jobs are read-only until the explicit activation command. A mode downgrade stops new prohibited work first; it does not delete historical outputs.

## Backup, anchors and health

```text
LedgerAnchorRequest = { schema_version: 1, ledger_id: RecordId,
  sequence: PositiveInt, record_hash: Sha256, previous_receipt_hash: ArtifactId | null,
  sent_at: UtcInstant }
LedgerAnchorReceipt = { request: LedgerAnchorRequest, received_at: UtcInstant,
  receiver_id: RecordId, signature: SignatureEvidence }
BackupManifest = { schema_version: 1, backup_id: RecordId, captured_at: UtcInstant,
  database_schema_version: PositiveInt, database_dump_hash: ArtifactId,
  ledger_sequence: PositiveInt, ledger_record_hash: Sha256,
  referenced_artifact_manifest_hash: ArtifactId,
  anchor_receipt_hash: ArtifactId, encryption_key_ref: SecretRef,
  encrypted_archive_hash: Sha256, encrypted_archive_bytes: NonNegativeInt }
RestoreReport = { schema_version: 1, restore_id: RecordId, backup_hash: ArtifactId,
  started_at: UtcInstant, completed_at: UtcInstant | null,
  isolated_destination_id: RecordId, worker_execution_disabled: true,
  verified_artifact_count: NonNegativeInt, missing_artifact_ids: list<ArtifactId>,
  corrupt_artifact_ids: list<ArtifactId>, ledger_verified: bool,
  independent_anchor_verified: bool, snapshot_replay_verified: bool,
  measured_rpo_seconds: FiniteNonNegative | null,
  measured_rto_seconds: FiniteNonNegative | null,
  verdict: "pass" | "fail" | "incomplete" }
HealthReport = { schema_version: 1, component_id: NonEmptyString,
  deployment_manifest_hash: ArtifactId, observed_at: UtcInstant,
  state: "starting" | "healthy" | "degraded" | "failed",
  consecutive_failures: NonNegativeInt, last_success_at: UtcInstant | null,
  reasons: list<NonEmptyString> }
OperationalAlert = { schema_version: 1, alert_id: RecordId,
  condition: "integrity" | "service_failed" | "disk_low" | "backup_stale" |
   "anchor_stale" | "spend_threshold" | "void_rate" | "qualification" | "forecast_clustering",
  component_id: NonEmptyString, version_hash: ArtifactId,
  first_seen_at: UtcInstant, last_seen_at: UtcInstant,
  state: "open" | "resolved", evidence_hashes: list<ArtifactId> }
AlertAcknowledgment = { alert_id: RecordId, actor_id: RecordId, acknowledged_at: UtcInstant }
```

The anchor receiver treats an identical sequence/hash retry idempotently; same sequence/different hash or a decreasing sequence is rejected. Receiver-signed receipts prove its observation time, not historical source truth. Application credentials can append only, never rewrite/delete past receipts. Every 15 minutes or 100 records (whichever first), storage sends the latest committed head. More than 30 minutes of backlog blocks new prospective seals. Independent verification fetches receipts with a separately controlled read identity; comparing two copies both writable by application is not independence.

Backup procedure: establish a consistent PostgreSQL snapshot, record its committed ledger watermark, enumerate artifact references visible in that snapshot, stream those exact hash-addressed immutable blobs, verify each hash, then encrypt and finalize one archive/manifest. Artifacts added later are not required by this backup. Abort on a missing required artifact; never label an incomplete archive successful. Restore PostgreSQL into an isolated destination, verify every referenced blob/ledger link/independent anchor and one preserved snapshot replay before reporting success. Do not enable paid workers or mutate the production pointer during restore tests. Monthly drill evidence proves the 24-hour RPO/four-hour RTO targets; it is not inferred from backup creation success. Retention is seven daily and four weekly successful versions, subject to documented source deletion requirements and audit tombstones.

Health probes run every 30 seconds; three misses fail a service, with initial model-load allowance 15 minutes. Restart delays are exactly 10/30/90 seconds, at most three starts, then operator repair. A failed optional source does not terminate collection/core reading. Alert dedupe key is `(condition, component_id, version_hash)` while open. A page view never acknowledges an alert. All private alert output uses authenticated projection and safe text, no automated email/chat delivery.

## Exact operations endpoints

Each uses the shared strict response/command envelope, service authentication and idempotency rules in STORAGE.md. Operator routes are not agent tools and never become callable through model arguments.

| Service and route | Request payload | Success data | Authorized role |
| --- | --- | --- | --- |
| storage `POST /v1/deployment-bindings` | Signed<DeploymentBindings> | ArtifactRef | operator |
| storage `POST /v1/spend/authorizations` | SpendAuthorization | SpendAuthorization | operator |
| storage `POST /v1/spend/reserve` | SpendReservationRequest | SpendReservation | ingest, orchestrator, approved batch producer |
| storage `POST /v1/spend/{id}/reconcile` | SpendReconciliation | SpendReservation | billing reconciler/operator |
| storage `POST /v1/readiness/evaluate` | `{mode:ExecutionMode, profile_hash:ArtifactId, bindings_id:RecordId}` | ReadinessReport | operator, orchestrator |
| storage `POST /v1/activation` | ActivationRequest | ActivationReceipt | operator |
| storage `POST /v1/anchors/receipts` | LedgerAnchorReceipt | ArtifactRef | storage anchor integration |
| anchor receiver `POST /v1/anchors` | LedgerAnchorRequest | LedgerAnchorReceipt | application append identity |
| storage `POST /v1/backups/manifests` | BackupManifest | ArtifactRef | backup_integration |
| storage `POST /v1/restores/reports` | RestoreReport | ArtifactRef | operator restore verifier |
| storage `POST /v1/health` | HealthReport | RecordId | authenticated component for its own id |
| storage `POST /v1/alerts/{id}/ack` | AlertAcknowledgment | AlertAcknowledgment | authenticated private app for current actor |
| each component `GET /health/live` | no body | `{schema_version:1, alive:bool}` | health monitor |
| each component `GET /health/ready` | no body | HealthReport | health monitor |

Path/body ids must agree. Timestamps and actor/component identities requiring server authority are stamped/checked by storage, not accepted merely because supplied. Incoming operator evidence retains its original captured time with a separate server import time. A health failure does not authorize an extra model sample, changed funding cap or current-snapshot rewrite.

## Boundary examples and prohibited alternatives

A reservation with `paid_execution_enabled=false` and all monetary caps zero is a valid stored authorization, but `POST /v1/spend/reserve` for any positive charge returns 403 funding_disabled and produces no external request. A 2,000,001-microdollar Jev daily reservation exceeds its sublimit even if the combined daily cap has room. An ambiguous timeout leaves its reservation present. Two 15,000,000 reservations racing under a 25,000,000 daily cap cannot both commit.

A restore report with `verdict="pass"` and `independent_anchor_verified=false` is invalid; the report stays fail/incomplete. A verified binding with null value is invalid. A quote missing a fee bound is usable as collected evidence but cannot authorize execution. These cases are real boundary tests in planned `tests/operations/` and transaction tests against PostgreSQL; replacing the storage owner with a mock does not demonstrate cap or idempotency safety.

Spending allocation invariants: each accounting_month equals its accounting_day prefix; days are unique and sorted, and top-level worst_case_microdollars/rental_seconds equal the sums of their allocations. The operation deadline restricts one reservation to at most two UTC days; longer ongoing storage billing uses separately authorized daily reservations. The same reservation id contains all crossing-boundary allocations and remains unique per operation. Lock all affected day/month counters in canonical order, applying each day allocation once and each month's sum once; one operation cannot avoid a cap by choosing a different accounting date. Dates must match the preserved bounded exposure interval in the operation evidence, not caller convenience. Conservative over-reservation is permitted; unbounded exposure is not.

Settled reconciliation requires non-null charges/duration, actual allocations summing exactly to those totals, and billing evidence. Non-rental classes have zero rental duration. Released requires zero charge/duration and explicit nonexecution/billing evidence. Disputed has null final charge/duration, no actual allocations and retains every original reserved allocation. Reconciliation records actual charges even outside reserved bounds, blocks new paid execution on a violation, and never rewrites the original funding authorization. Allocation changes need evidence of actual billing periods, not a way to shift charges away from a full counter.

Anchor receipt SignatureEvidence.signed_payload_hash equals SHA256 of canonical `{request, received_at, receiver_id}` excluding signature; verify its ed25519 signature against the separately admitted receiver key. Its full stored artifact includes that signature. Application append identity cannot rotate the receiver key. The signature verifies observed bytes/time; eligibility of historical source events is a separate protocol check.
