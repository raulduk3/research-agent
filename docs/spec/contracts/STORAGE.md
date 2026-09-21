# Storage wire contracts and transactional implementation

This section defines version 1 of `contracts/storage.py`; records are closed (additional properties forbidden), every displayed field is required, `T|null` explicitly permits null, `List<T>[a..b]` bounds length, and unions are discriminated by the literal `kind`. References to domain types below resolve to their canonical domain schema; they are not arbitrary JSON. No wire coercion is allowed. Root identifiers cannot be supplied by untrusted model output.

## Primitive and shared records

| Name | Exact shape |
| --- | --- |
| `Id` | canonical lowercase UUIDv4 string, variant RFC4122 |
| `Hash` | string matching `^[0-9a-f]{64}$` |
| `Utc` | valid UTC RFC3339 timestamp `YYYY-MM-DDTHH:MM:SS.ffffffZ` |
| `Count` | integer 0..9223372036854775807; bool rejected |
| `Positive` | integer 1..9223372036854775807 |
| `Probability` | finite number 0..1 |
| `Money` | Count, USD microdollars |
| `Text` | NFC string with no NUL; individual fields further bounded |
| `Role` | storage, ingest, reader, models, tools, scorer, orchestrator, rating_app, baseline_producer, operator, billing_reconciler, anchor_integration, backup_integration, restore_verifier, health_monitor |
| `Mode` | collection, engineering, study |
| `TargetId` | citation_reach_365d, late_citation_activity_365d, cross_subfield_reach_365d |
| `SourceInterval`, `ExternalIdentifier` | Canonical source-data records owned by LEARNING.md; no alternative interval/identifier encoding |
| `ProducerVersion` | `{image_digest:Hash,source_commit: string matching ^[0-9a-f]{40}$,contract_version:1}` |
| `RecordMeta` | `{schema_version:1,input_hashes:List<Hash>[0..1000000],producer_version:ProducerVersion,config_hash:Hash,created_at:Utc}` |
| `ArtifactRef` | `{schema_version:1,artifact_hash:Hash}` |
| `PageRequest` | `{limit:integer[1..100],after_id:Id\|null}` |
| `CommitReceipt` | `{record_ids:List<Id>[0..1000000],artifact_hashes:List<Hash>[0..1000000],ledger_first:Positive\|null,ledger_last:Positive\|null,committed_at:Utc}`; ledger endpoints either both null or ordered |
| `Error` | `{code:ErrorCode,message:Text[1..512],retryable:boolean,evidence_ids:List<ArtifactId>[0..20]}` |
| `ErrorCode` | malformed_json, unauthenticated, forbidden, not_found, invalid_input, idempotency_conflict, state_conflict, lease_expired, stale_lease, incompatible_manifest, unavailable_input, deadline_exceeded, budget_exceeded, integrity_failure, capacity_exceeded, temporarily_unavailable, incompatible_snapshot, evidence_not_retrieved, incomplete_answers, upstream_rejected, upstream_ambiguous, unavailable_source, funding_disabled |

`Command<P>={schema_version:1,command_id:Id,request_id:Id,payload:P}` with mandatory HTTP `Idempotency-Key: <Id>`. `Reply<T>` is exactly either `{schema_version:1,request_id:Id,status:"ok",data:T,error:null}`, or `{schema_version:1,request_id:Id,status:"unavailable"|"error",data:null,error:Error}`. A successful replay retains the original body including original request_id; response header `X-Replayed: true` identifies replay. Request correlation for the new transport remains in access metadata. Requests have a 1 MiB JSON cap except snapshot/seal manifests, which are uploaded as artifacts rather than embedded. Validation errors disclose field paths and codes in safe message text, never original secrets or hidden values. No endpoint returns 202 unless its response type explicitly represents a durable queued job; every route below returns a committed result.

**Self-hash rule:** a manifest's stored canonical body contains RecordMeta and its typed domain fields, but no `artifact_hash`. Its hash is SHA256 of those complete bytes. `ArtifactRef`/API envelopes carry that hash externally. Existing shorthand saying a manifest “includes artifact_hash” means this envelope, not a circular field inside its own preimage. `input_hashes` is ordered and may not include the manifest's own hash. Binary payload metadata lives in a separate typed manifest referencing the raw payload hash.

## Every storage route

`ManifestRef = ArtifactRef` and `ManifestHeader = RecordMeta` are compatibility aliases only. `M<T>` below means a ArtifactRef whose bytes must decode as exactly T; storage validates its kind, version and dependencies before state change. The domain owners supply `SnapshotManifest`, `PaperCard`, `GraphData`, `PassageRecord`, `Question`, `Submission`, `RunSpec`, `ModelBundle`, `HeadQualificationReport`, `ScoringInput`, `BaselineInput`, `StudyRegistration` and `DigestManifest`; these are finite named schemas, not arbitrary mappings.

| Route and success HTTP | Exact payload/request | Exact data |
| --- | --- | --- |
| POST /v1/artifacts (201 new/200 existing) | binary protocol below | `ArtifactReceipt` |
| GET /v1/artifacts/{hash} (200) | no body, hash path | raw exact bytes; binary protocol below |
| POST /v1/paper-observations (201) | `Command<PaperObservation>` | `{family_id:Id,version_id:Id,observation_id:Id,receipt:CommitReceipt}` |
| POST /v1/jobs/claim (200) | `Command<{worker_id:Id,kinds:List<JobKind>[1..12]}>` | `{lease:JobLease\|null}`; null means no eligible work, not failure |
| POST /v1/jobs/{id}/renew (200) | `Command<LeaseFence>` | `{expires_at:Utc,receipt:CommitReceipt}` |
| POST /v1/jobs/{id}/checkpoint (200) | `Command<{fence:LeaseFence,checkpoint:Hash}>` | `{checkpoint_id:Id,receipt:CommitReceipt}` |
| POST /v1/jobs/{id}/complete (200) | `Command<{fence:LeaseFence,result:JobResult}>` | `{job_id:Id,state:"committed"\|"failed"\|"skipped",receipt:CommitReceipt}` |
| POST /v1/snapshots/seal (201) | `Command<{manifest:M<SnapshotManifest>}>` | `{snapshot_id:Hash,receipt:CommitReceipt}` |
| GET /v1/snapshots/{id}/cards (200) | query `paper_id` repeated 1..5 times; no other arguments | `{snapshot_id:Hash,cards:List<PaperCard>[1..5]}`; exact requested order |
| GET /v1/snapshots/{id}/graph (200) | query `paper_id:Id`; `direction:"references"\|"citations"`; `limit:1..20` | `GraphData` |
| GET /v1/snapshots/{id}/passages (200) | query `paper_id:Id`; `passage_id:ArtifactId` repeated 1..20 | `{snapshot_id:Hash,passages:List<PassageRecord>[1..20]}` |
| GET /v1/snapshots/{id}/questions (200) | query `paper_id:Id` repeated 1..20 | `{snapshot_id:Hash,questions:List<Question>[0..60]}` |
| POST /v1/runs (201) | `Command<{spec:M<RunSpec>}>` | `{run_id:Id,slot_id:Sha256,state:"queued",receipt:CommitReceipt}` |
| POST /v1/runs/{id}/events (201) | `Command<{expected_next_sequence:Positive,event:RunEvent}>` | `{event_id:Id,sequence:Positive,receipt:CommitReceipt}` |
| POST /v1/runs/{id}/budget/reserve (201) | `Command<RunBudgetReserveInput>` | `RunBudgetReservation` |
| POST /v1/runs/{id}/budget/reconcile (200) | `Command<RunBudgetReconcileInput>` | `RunBudgetReservation` |
| POST /v1/runs/{id}/submit (201) | `Command<{submission:Submission}>` | `{submission_id:Id,run_id:Id,state:"submitted",receipt:CommitReceipt}` |
| POST /v1/bundles/activate (200) | `Command<{namespace:Hash,expected_old:Hash\|null,new_bundle:M<ModelBundle>,qualification:M<HeadQualificationReport>}>` | `{namespace:Hash,active_bundle:Hash,receipt:CommitReceipt}` |
| POST /v1/digests (201) | `Command<{batch_id:Sha256,terminal_watermark:Hash}>` | `{digest_id:Sha256,digest: M<DigestManifest>,receipt:CommitReceipt}` |
| POST /v1/ratings (201) | `Command<RatingInput>` | `{rating_event_id:Id,receipt:CommitReceipt}` |
| POST /v1/human-forecasts (201) | `Command<HumanForecastInput>` | `{forecast_ids:List<Id>[1..60],receipt:CommitReceipt}` |
| POST /v1/alerts/{id}/ack (201) | `Command<AlertAcknowledgment>` | `AlertAcknowledgment` |
| POST /v1/spend/reserve (201) | `Command<SpendReservationRequest>` | `SpendReservation` |
| POST /v1/spend/{id}/reconcile (200) | `Command<SpendReconciliation>` | `SpendReservation` |
| POST /v1/studies/import (201) | `Command<{registration:M<StudyRegistration>,signature:SignatureEvidence,chronology_evidence:List<Hash>[1..20]}>` | `{registration_id:Id,imported_at:Utc,receipt:CommitReceipt}` |
| POST /v1/anchors/receipts (201) | `Command<LedgerAnchorReceipt>` | `ArtifactRef` |
| GET /v1/scoring-inputs/{manifest_id} (200) | no body | `ScoringInput` |
| POST /v1/scores (201) | `Command<{score:M<ScoreRecord>}>` | `{score_id:ArtifactId,receipt:CommitReceipt}` |
| GET /v1/baseline-inputs/{snapshot_id} (200) | no body | `BaselineInput` |

The former `/snapshots/{id}/...` is only the four enumerated routes above. Search, neighbors and deep-read pagination are tool/reader computations over authorized snapshot artifacts, not an extra unscoped storage API. Snapshot route callers authenticate scope with `X-Run-Id: Id` when serving a run; storage independently binds it to the stored run/snapshot. A reader batch principal instead presents its fenced job id/epoch and is restricted to that job's declared inputs.

### Binary artifact protocol

POST uses `Content-Type: multipart/form-data` with exactly two parts: `metadata` (`application/json`, at most 128 KiB, `ArtifactUpload`) and `payload` (`application/octet-stream`, bytes). Never embed base64 PDFs/weights/vectors in JSON. `ArtifactUpload={schema_version:1,command_id:Id,request_id:Id,expected_hash:Hash,byte_length:Count,media_type:"application/json"|"application/pdf"|"application/octet-stream"|"image/png"|"text/plain",kind:ArtifactKind,input_hashes:List<Hash>[0..1000],producer_version:ProducerVersion,config_hash:Hash,source_available_at:Utc|null,retention_policy_hash:Hash}`. `ArtifactKind` = source_response, source_document, extraction, vector_payload, model_weights, tokenizer, manifest, tool_request, tool_response, provider_response, study_evidence, signature_evidence. A model_weights binary can be up to 128 GiB, other binaries up to 1 GiB; actual admitted job/source cap may be lower. Reject declared or streamed overage; stream without buffering whole body. Storage assigns `created_at` after fsync; validates any source_available_at against authenticated capture evidence; actual runtime publication comes from ArtifactPublicationReceipt. Input hashes must all be committed/visible. ArtifactReceipt is `{artifact_hash:Hash,byte_length:Count,created_at:Utc,receipt:CommitReceipt}`. GET sets exact Content-Length, Content-Type and `ETag: "<hash>"`; no content transformations. Error replies are the JSON Reply error union. Missing, tombstoned and unauthorized hashes return indistinguishable 404 not_found to callers without tombstone-audit privilege.

### Command payload records

`PaperObservation={source:ExternalIdentifier,external_version:Text[1..64],identifiers:List<ExternalIdentifier>[1..20],source_artifact:Hash,source_event_at:Utc|null,source_event_interval:SourceInterval|null,captured_at:Utc,available_at:Utc,transport_hash:Hash,stored_payload_hash:Hash,sanitization_policy_hash:Hash|null}`. Exactly one of source_event_at/source_event_interval is nonnull. ExternalIdentifier uses the canonical scheme/value fields, not provider/value. stored_payload_hash equals source_artifact; differing transport/stored hashes require sanitization policy. available_at>=captured_at and both<=command receipt time; uncertain historical event dates are allowed without backdating actual availability. Resolve known exact identifiers transactionally; contradictory existing family mappings produce a conflict finding and no merge. Original source version is immutable; revised bytes with same external version become a separate observation and conflict, not replacement.

`JobKind` = capture, extract, embed, label, fit, calibrate, predict, assess, qualify, baseline, score, audit. `LeaseFence={worker_id:Id,lease_epoch:Positive}`. `JobLease={job_id:Id,kind:JobKind,lease_epoch:Positive,expires_at:Utc,input_manifest:Hash,checkpoint:Hash|null}`. `JobResult` is `{kind:"committed",output_hashes:List<Hash>[1..1000]}` or `{kind:"failed",error:Error}` or `{kind:"skipped",reason:"unavailable_input"|"ineligible"|"disabled",evidence_hashes:List<Hash>[0..20]}`. Job insertion is a storage-internal consequence of a validated source/profile operation, not arbitrary enqueue exposed to agents.

`RunEvent` is one of `{kind:"started",worker_id:Id,launcher_receipt:Hash}`, `{kind:"model_request",turn_index:integer[0..15],request_hash:Hash,reservation_id:Id,request_seed:integer[0..4294967295]}`, `{kind:"model_response",turn_index:integer[0..15],request_hash:Hash,response_hash:Hash,elapsed_microseconds:Count}`, `{kind:"tool_receipt",tool_call_id:Text[1..128],tool_name:"query_cards"|"neighbors"|"graph"|"deep_read"|"submit",request_hash:Hash,response_hash:Hash,evidence_ids:List<ArtifactId>[0..1000],elapsed_microseconds:Count}`, `{kind:"submission_rejected",submission_hash:Hash,error:Error}`, `{kind:"terminal",state:"void"|"missed_deadline",reason:ErrorCode,evidence_hashes:List<Hash>[0..20]}`. Provider ambiguity becomes terminal void, not a second request sample. `submitted` can be generated only by successful submit transaction.

`RatingInput={rater_id:Id,digest_entry_id:Sha256,view_receipt_id:Id,rating:RatingValue,supersedes_event_id:Id|null}`. `RatingValue="like"|"dislike"|"skip"`; absence of a rating event is unrated and is not a fourth submitted value. Same-rater corrections append and reference the immediately prior event; no edits to old rows. `HumanForecastInput={rater_id:Id,snapshot_id:Hash,view_receipt_ids:List<Id>[1..100],answers:List<HumanAnswer>[1..60]}`; `HumanAnswer={question_id:Sha256,probability:Probability,rationale:Text[0..2000],evidence_ids:List<ArtifactId>[0..5]}`. Storage resolves target/horizon/deadline from question and checks each evidence view existed before submission; no human-provided resolution, target id or timestamp accepted.

`SpendReservationRequest`, `SpendReservation`, `SpendReconciliation`, `LedgerAnchorReceipt` and `AlertAcknowledgment` are defined only in OPERATIONS.md. Their exact route payload/result types above match that owner. Billing reconciliation is restricted to operator/billing reconciler, not ingest; ingest only requests reservations and supplies billing evidence through its admitted operation record. UTC accounting fields are checked against storage-derived exposure periods; callers cannot move charges to an arbitrary less-used period.

`SignatureEvidence={key_id:Id,algorithm:"ed25519",signed_payload_hash:Hash,signature_base64:Text[88..88]}`; decode exactly 64 bytes and verify against admitted key registry. `LedgerAnchorReceipt` uses this signature wrapper under OPERATIONS.md; signatures cover the canonical unsigned receipt body (request, received_at and receiver_id), excluding the signature field. Receipt verification checks the local sequence/hash and admitted receiver signing key; decreasing/conflicting receiver claims are rejected and alerted, identical replay is harmless.

## Ledger, idempotency and transaction algorithms

`LedgerPreimage={schema_version:1,sequence:Positive,record_id:Id,previous_record_hash:Hash,event_kind:LedgerEventKind,payload_hash:Hash,created_at:Utc,command_id:Id}`. Genesis previous hash is 64 zeros. `record_hash=SHA256(canonical(LedgerPreimage))`; record_hash is stored alongside preimage, excluded from preimage. Event payload is independently content-addressed, with its own specific typed schema. `LedgerEventKind` = artifact_committed, paper_observed, job_transition, snapshot_sealed, run_created, run_event, submission_accepted, bundle_activated, digest_created, rating_recorded, human_forecast_sealed, alert_acknowledged, spend_reserved, spend_reconciled, study_imported, anchor_received, score_published, run_budget_reserved, run_budget_reconciled. Event references identify the command's domain record and committed artifacts, never an arbitrary object supplied by caller.

1. Authenticate role, parse/normalize exact schema, validate size, compute command content hash over canonical `{route_template,path_ids,payload}` (exclude request_id and command_id so a transport retry is semantically identical); begin SERIALIZABLE transaction.
2. Claim `(principal_id,idempotency_key)` unique row. Existing same content hash returns stored status/body; different content returns409. A unique `(principal_id,command_id)` also prevents one command identifier from changing payload under another key. Concurrent in-flight conflicts wait for the first transaction rather than running twice.
3. Lock relevant domain rows in order: spend authorization, UTC monthly bucket, UTC daily bucket, job/run/slot, ledger head. Validate fences, active state, deadline and scope using database time after lock. Check all artifact metadata/hash rows are committed and not tombstoned. Domain rules run before ledger insertion.
4. Perform domain change, append ledger payload artifacts already fsynced (or canonical small payload fsynced before acquiring head), lock single head and append consecutive records; persist exact successful response with idempotency row; commit. Rollback leaves no domain/ledger/idempotency success. Verified orphan bytes are harmless and reusable.
5. Serialization/deadlock retry at most three attempts with 10/30/90 ms backoff, preserving command content and no external call inside transaction. Exhaustion503 retryable. Lost connection after COMMIT is resolved by replay, never guessing failure.

Lease claim uses `FOR UPDATE SKIP LOCKED`, earliest scheduled_at then job_id, permitted kinds only. Claim increments lease_epoch, creates job_attempt, expires_at=DBnow+120s. Expired running attempts become expired audit rows before reassignment. Renewal every30s requires state running, matchingworker/epoch, DBnow<expires_at; returns DBnow+120s. Checkpoint/complete repeat fence predicate in same write transaction; an uploaded artifact from an old worker may remain an orphan but cannot become job output. A process restart discovers durable lease/slot state, never resets counters or sample number.

Submit locks run then slot, rejects terminal/expired/budget-exceeded state, exact question-id set mismatch, duplicate targets/questions, foreign snapshot or unseen evidence. Store submission and every forecast/nomination, append sealed event, mark run submitted and slot completed atomically. Immutable question content supplies deadlines/resolver/target. Request or retry arriving after deadline may return an already committed response, but cannot create a new submission. Rejection is a separately committed typed run event; retryable correction does not replace the rejected event. CAS activation locks namespace pointer, requires current==expected_old and qualification with matching exact bundle/representation/target registry and passes; initial null CAS races produce one winner.

Digest transaction validates every slot in the supplied watermark is terminal and membership exactly matches batch population slots. Its manifest hashes sorted `(slot_id,state,submission_hash|null)`; comparison slots excluded. It projects round-robin nominations and controls from frozen inputs, checks family uniqueness and cap, inserts unique batch digest plus entries, and appends ledger event. Replays return the existing result; a different watermark cannot rewrite it.

Spend reservation locks authorization/month/day in fixed order and checks combined/subcategory monetary caps and rental seconds using settled charges plus outstanding reservations. UTC bucket comes from storage time; operations spanning midnight preserve original allocation and reserve future covered buckets before incurring cost. Reconcile charges once by unique reservation id, releases only proven unused remainder, appends outcome atomically. An unresolved reservation retains full capacity consumption. Authorization cannot be manufactured by reserve; operator-signed funding/binding admission is required.

## Relational layout and constraints

All ids use PostgreSQL uuid, hashes bytea with octet_length=32, counters bigint CHECK>=0, timestamps timestamptz NOT NULL, money bigint CHECK>=0. Enumerations are text CHECK IN fixed schema values. Columns nullable only when explicitly marked `?`. Every hash FK references artifacts unless specified as an external transport/checksum identity. Manifest JSON bytes remain authoritative; indexed relational projections are built in the same transaction and verified against manifest hash on replay. No table stores unconstrained mutable JSON as the sole domain owner.

| Table | Columns beyond common typed identity | Keys/indexes/checks |
| --- | --- | --- |
| artifacts | hash PK, byte_length, media_type, kind, created_at, available_at, retention_policy_hash, producer_manifest_hash | hash unique; bytes path derived only from hash; ready rows only after fsync |
| artifact_edges | output_hash,input_hash,ordinal | PK(output_hash,ordinal); both FK; CHECK output!=input; index input_hash |
| artifact_tombstones | id PK,artifact_hash,reason,policy_hash,created_at | UNIQUE artifact_hash; original metadata retained |
| paper_families | id PK,created_at | no title unique constraint |
| paper_versions | id PK,family_id,provider,external_version,source_hash,observed_at | UNIQUE(family_id,provider,external_version,source_hash); index(family_id,observed_at) |
| external_id_observations | id PK,family_id,provider,value,version_id,observation_hash,captured_at,available_at | immutable observations; lookup(provider,value); authoritative binding separate unique(provider,value) mapping inserted only after exact-ID validation |
| jobs | id PK,kind,state,input_manifest_hash,scheduled_at,lease_epoch,worker_id?,expires_at?,checkpoint_hash? | index(state,scheduled_at,id); running iff worker/expires nonnull |
| job_attempts | id PK,job_id,lease_epoch,worker_id,started_at,ended_at?,status | UNIQUE(job_id,lease_epoch) |
| job_checkpoints | id PK,job_id,lease_epoch,artifact_hash,created_at | index(job_id,lease_epoch,created_at) |
| ledger_records | sequence PK,record_id UNIQUE,previous_record_hash,record_hash UNIQUE,event_kind,payload_hash,created_at,command_id | append-only; predecessor validated under head lock |
| ledger_head | singleton boolean PK CHECK true,sequence,record_hash | exactly one row bootstrap sequence0/zero hash |
| anchor_receipts | id PK,receiver_id,sequence,record_hash,received_at,signature_hash | UNIQUE(receiver_id,sequence); sequence references ledger_records |
| snapshots | hash PK,cutoff_at,mode,manifest_hash UNIQUE,sealed_at | no UPDATE/DELETE for application |
| snapshot_members | snapshot_hash,paper_id,version_id,card_hash,ordinal | PK(snapshot_hash,paper_id); UNIQUE(snapshot_hash,ordinal) |
| run_slots | id hash PK,batch_id hash,shard_id hash,config_hash,arm,attempt,state,run_id? | UNIQUE(batch_id,shard_id,config_hash,arm,attempt); launch attempt CHECK=0 |
| runs | id PK,slot_id hash UNIQUE,snapshot_hash,spec_hash,state,deadline_at,next_event_sequence,model_calls,tool_calls,deep_reads,images,generated_tokens | nonnegative counters; configured bounds validated transactionally |
| run_events | id PK,run_id,sequence,event_hash,created_at | UNIQUE(run_id,sequence) |
| tool_receipts | id PK,run_id,tool_call_id,request_hash,response_hash,event_id | UNIQUE(run_id,tool_call_id); normalized receipt_evidence(receipt_id,evidence_id) PK |
| run_budget_reservations | id UUID PK,run_id,request_id,kind,request_artifact_hash,reserved_generated_tokens,reserved_images,spend_reservation_id?,state,response_hash?,consumed_generated_tokens?,returned_images? | UNIQUE(run_id,request_id); nonnegative counters; settled fields consistent with disposition; all updates lock owning run |
| submissions | id PK,run_id UNIQUE,payload_hash,accepted_at | same id changed payload conflicts |
| forecasts | id PK,submission_id?,human_batch_id?,question_id hash,probability,producer_id,sealed_at | probability finite[0,1]; exactly one producer linkage; UNIQUE(producer_id,question_id) within sealed run/batch producer identity |
| nominations | submission_id,paper_id,rank,rationale_hash | PK(submission_id,paper_id); UNIQUE(submission_id,rank); rank1..7 |
| model_bundles | hash PK,namespace,manifest_hash,created_at | immutable |
| active_bundles | namespace PK,bundle_hash,qualification_hash,activated_at | CAS only |
| qualification_records | hash PK,subject_hash,protocol_hash,result,measured_at,evidence_hash | immutable result, exact subject matching |
| digests | id hash PK,batch_id hash UNIQUE,watermark_hash,manifest_hash,created_at | immutable |
| digest_entries | id hash PK,digest_id hash,paper_id,display_order,blind_label,origin_manifest_hash | UNIQUE(digest_id,paper_id); UNIQUE(digest_id,display_order); origin excluded from rating projections |
| ratings | id PK,rater_id,entry_id hash,value,view_receipt_id,supersedes_id?,created_at | index(rater_id,entry_id,created_at); unique nonnull supersedes_id prevents forked corrections |
| human_forecasts | batch_id PK,rater_id,snapshot_hash,input_hash,created_at | answers in forecasts; view receipt junction table |
| spend_authorizations | id PK,manifest_hash,valid_from,valid_until,enabled | signed immutable; validity start<end |
| spend_reservations | id PK,authorization_id,operation_id UNIQUE,purpose,quote_hash,reserved_money,reserved_seconds,state,created_at | lock bucket projections; nonnegative |
| spend_charges | reservation_id PK,actual_money,actual_seconds,receipt_hash,reconciled_at | at most one proven settlement |
| alerts | id PK,condition,component,version_hash,opened_at,resolved_at? | partial UNIQUE(condition,component,version_hash) WHERE resolved_at IS NULL |
| alert_acknowledgments | id PK,alert_id,rater_id,created_at | UNIQUE(alert_id,rater_id) |
| audit_events | id PK,principal_id,action,event_hash,created_at | append-only index(principal_id,created_at) |
| study_registrations | id PK,manifest_hash UNIQUE,registered_at,imported_at,signature_hash,chronology_hash | registered_at retained; chronology validated, never inferred from import |
| idempotency_records | principal_id,key,command_id,content_hash,status_code,response_hash,committed_at | PK(principal_id,key); UNIQUE(principal_id,command_id) |

`spend_bucket_allocations(reservation_id,period_start,period_kind,purpose,money,seconds)` PK(reservation_id,period_start,period_kind); period_kind day/month, used for exact boundary accounting. Required authenticated private UI projection tables `view_receipts` and question domain tables follow their canonical agent/evaluation schema. Their absence from this storage table summary does not grant an untyped foreign key. Ledger/event privileges revoke UPDATE/DELETE from runtime role; migrator uses separate credentials and records schema changes. FK deletion policy is RESTRICT, never cascading audit deletion. Tombstone deletion removes eligible payload bytes only after policy and dependent replay status are committed.

## Authorization matrix

| Principal | Allowed storage operations |
| --- | --- |
| ingest | upload source/assessment artifacts; paper-observations; capture/assess claim/fence updates; reserve Jev/scholarly calls with admitted authorization |
| reader | upload extraction artifacts; extract claim/fence updates; read only assigned input hashes and snapshot document/passages |
| models | upload vectors/bundles/fit evidence; embed/fit/calibrate/predict claim/fence updates; activate qualified compatible bundles; assigned input read |
| tools | run-scoped snapshot projections, run event/budget/submit proxy; upload run request/response artifacts; no unrelated run scope |
| scorer | score claims and exact scoring-input route; output scoring artifacts and POST /v1/scores; no general GET artifact or cards |
| baseline_producer | baseline-input route and baseline claim/output; no paper text/Jev/general artifacts |
| orchestrator | snapshot seal, run creation, digest creation, admitted spend reserve, permitted run metadata; no arbitrary agent prose retrieval |
| rating_app | ratings/human forecasts/ack for authenticated bound rater; blinded projection only, no general snapshots/artifacts |
| operator | billing reconciliation; signed study import, admitted deployment/funding/qualification artifacts, private audit/retrospective projections; no authority through user-supplied role string |
| storage anchor integration | receipt import from admitted receiver and backup/anchor outbound transport only |
| isolated worker/external agent-model endpoint | no storage routes; run capability permits tool service only |

Authorization uses mTLS identity mapped to role and independently stored job/run/rater scope. Passing another rater_id/run_id in a valid payload does not extend scope. All denied existence checks collapse to404 where necessary. Operator inspection requires authenticated operator role and is never exposed through agent tools.

## Examples and prohibited alternatives

Valid claim body (with a UUID Idempotency-Key header):
```json
{"schema_version":1,"command_id":"f5a07bc8-c464-4db3-bb9d-1964b82186d3","request_id":"30fe9b10-dd24-46bf-a72e-3b88d394dc38","payload":{"worker_id":"792f0b8c-313f-47a5-87d3-39b56c973eca","kinds":["extract"]}}
```
Valid no-work response:
```json
{"schema_version":1,"request_id":"30fe9b10-dd24-46bf-a72e-3b88d394dc38","status":"ok","data":{"lease":null},"error":null}
```
Invalid claim payload `{"worker_id":"792f0b8c-313f-47a5-87d3-39b56c973eca","kinds":["extract"],"sql":"SELECT 1"}` rejects422 for unknown sql, not ignored. `lease_epoch:true` rejects422; `probability:"0.5"` rejects422; duplicate JSON payload keys reject400 before model validation. A valid complete command with stale lease rejects409 stale_lease with no job output/checkpoint change. Same idempotency key plus different checkpoint rejects409; identical retry after server restart returns exact original committed response. Corrupted upload with correct-looking declared hash rejects422 integrity_failure and exposes no artifact row. First ledger fixture hashes a preimage with zero predecessor; verifier recomputes payload and record hashes from canonical bytes and detects any field change, reorder of sequence, missing link or mismatching independent anchor.

## Schema-owner references

SourceInterval, ExternalIdentifier, PaperCard, PassageRecord, ModelBundle and HeadQualificationReport resolve to LEARNING.md. SnapshotManifest, Question, RunSpec, Submission, GraphData and DigestManifest resolve to AGENT-CONTRACTS.md. ScoringInput, BaselineInput and StudyRegistration resolve to their canonical catalog definitions. Operations-only routes and payloads have one owner in OPERATIONS.md and inherit these transport/transaction rules; they are not omitted from the full storage API merely because repeated route rows are avoided here. IDs marked hash in the relational table use the 32-byte hash SQL representation; UUIDv4 applies only to RecordId aliases.

## Registration and scoring projections

The scorer's restricted projection contains no paper prose, rationale, Jev assessments, embeddings, identity-revealing configuration text or mutable lookup pointers. Scores are readouts, never new agent outcomes. Stored score artifacts merge RecordMeta with ScoreRecordBody; `ScoreRecord = RecordMeta + ScoreRecordBody`.

```text
MetricId = "brier" | "multiclass_brier" | "average_precision" |
  "family_recall_at_5" | "supported_passage_recall_at_5" |
  "exact_span_reconstruction_rate" | "paired_brier_improvement" |
  "paired_supported_gain" | "coverage" | "exact_agreement" |
  "macro_f1" | "latency_seconds" | "cost_microdollars"
StudyEndpoint = { metric: MetricId, target_id: TargetId | null,
  assessment_field_id: JevFieldId | null, role: "primary" | "secondary" | "diagnostic",
  direction: "lower" | "higher" | "descriptive", required_absolute_effect: Finite | null,
  minimum_coverage: Probability | null }
StudyRegistration = RecordMeta + {
  registration_id: RecordId,
  study_kind: "head_release" | "retrieval_qualification" | "jev_content" |
    "jev_prospective" | "external_comparison" | "agent_capability" | "integrity_null",
  registered_at: UtcInstant, planned_start_at: UtcInstant,
  protocol_hash: ArtifactId, profile_hash: ArtifactId,
  cohort_selection: CohortSelection, split_selection: SplitSelection,
  candidate_manifest_hashes: List<ArtifactId>[1..100],
  baseline_manifest_hashes: List<ArtifactId>[0..100],
  endpoints: List<StudyEndpoint>[1..100],
  sampling_seed: NonNegativeInt, bootstrap_resamples: 10000,
  bootstrap_unit: "publication_week", interval_coverage: Probability,
  interval_sidedness: "one_sided_upper" | "two_sided",
  multiplicity_rule: "none" | "bonferroni_three" | "bonferroni_eight",
  stop_rule_hash: ArtifactId, missingness_policy_hash: ArtifactId,
  permission_evidence_hashes: List<ArtifactId>[1..100],
  maximum_cost_microdollars: Money }
ScoringResolution = { status: "true" | "false" | "unresolvable",
  label: 0 | 1 | null, resolution_hash: ArtifactId,
  resolved_at: UtcInstant, available_at: UtcInstant }
ScoringRow = { forecast_id: RecordId, producer_id: ArtifactId,
  question_id: ArtifactId, family_id: PaperFamilyId,
  publication_week: UtcDate, target_id: TargetId,
  target_definition_hash: ArtifactId, probability: Probability,
  sealed_at: UtcInstant, eligible: bool,
  ineligible_reason: "late" | "invalidated" | "wrong_target_version" | null,
  resolution: ScoringResolution | null }
ScoringInput = RecordMeta + { scoring_watermark: PositiveInt,
  as_of: UtcInstant, protocol_hash: ArtifactId,
  rows: List<ScoringRow>[0..1000000],
  intended_forecast_count: NonNegativeInt }
ForecastLoss = { forecast_id: RecordId, squared_error: Probability }
ScoreRecordBody = { input_manifest_hash: ArtifactId,
  target_id: TargetId, target_definition_hash: ArtifactId,
  producer_id: ArtifactId, scoring_watermark: PositiveInt,
  intended_count: NonNegativeInt, eligible_count: NonNegativeInt,
  resolved_count: NonNegativeInt, unresolved_count: NonNegativeInt,
  excluded_count: NonNegativeInt, losses: List<ForecastLoss>[0..1000000],
  mean_brier: Probability | null,
  disposition: "available" | "no_resolved_support" | "invalidated",
  computed_at: UtcInstant }
```

For StudyRegistration, registered_at<=planned_start_at; actual execution cannot begin before independently evidenced registration. Primary endpoints cannot be chosen after measurement. The protocol hash resolves to the exact admitted profile/protocol record and must agree with every numeric field; it does not permit untyped alternative definitions. A head release uses two-sided 98.333333% coverage/Bonferroni-three; Jev content uses one-sided99.375%/Bonferroni-eight; prospective Jev and retrieval use their fixed95% intervals. Fields irrelevant to a deterministic capability test remain declared diagnostics, with no bootstrap result invented. CohortSelection preserves the frozen existing corpus or fully specified selection rule; prospective realized membership is a separate later artifact and is never a prerequisite hash of unknown future papers. The scorer cannot execute these scientific comparisons solely because it can read the registration; qualification jobs own them.

ScoringResolution true requires label1, false requires label0, unresolvable requires null; resolution null is not yet resolved. ScoringInput rows contain unique forecast ids, available_at<=as_of for every nonnull resolution, immutable target definition hashes and intended_count>=rows length. A row is eligible iff ineligible_reason is null. For each ScoreRecord group, intended_count=eligible_count+excluded_count and eligible_count=resolved_count+unresolved_count; losses length=resolved_count. Every squared_error equals (p-y)^2 from its matched eligible resolved row; mean_brier is the arithmetic mean, null only with no resolved support or invalidation. No probability clipping, rounding or renormalization changes stored forecasts. All values use pinned round-trip float serialization.

POST /v1/scores authenticates scorer, verifies the ScoringInput is an authorized restricted projection, recomputes the deterministic row membership/counts/losses and rejects mismatches. It then inserts immutable `scores(hash PK,input_manifest_hash,producer_id hash,target_definition_hash,scoring_watermark,created_at)` with UNIQUE(input_manifest_hash,producer_id,target_definition_hash), appends score_published and returns its hash. Repeat publication reuses exact artifact bytes; later outcomes create a new input watermark and score instead of overwriting an old result. Scorer upload permissions admit only the ScoreRecord shape, not a general blob upload that could leak paper data.

`BaselineInput` is `RecordMeta + {snapshot_id:SnapshotId,as_of:UtcInstant,items:List<BaselineInputItem>[0..1000000]}`. `BaselineInputItem` is either `{kind:"popularity",target_id:TargetId,input:PopularityBaselineInput,training_rows:List<BaselineTrainingRow>[0..1000000],model_hash:ArtifactId|null}` or `{kind:"plain_card",target_id:TargetId,input:PlainCardBaselineInput,training_rows:List<BaselineTrainingRow>[0..1000000],model_hash:ArtifactId|null}`. Every input snapshot/as_of equals the envelope; target ids equal the requested question and each training row; a nonnull model_hash resolves to BaselineModel of the matching kind/target. Rows supply only already-admitted time-valid lineage. Missing fitted model remains explicit unavailable through the baseline producer, not a permission to train on the current inference snapshot. Large fitting projections are stored artifacts with the same closed shape, fetched by admitted job scope; an ordinary per-snapshot call does not return unrelated corpus rows. Numeric covariates and labels are the complete permitted content—never source text, Jev or vector arrays. These leaf records are defined only in LEARNING.md.

RunBudgetReserveInput and RunBudgetReconcileInput are closed records owned by SERVICE-API.md; RunBudgetReservation is defined by AGENT-CONTRACTS.md. Only tools may call the storage budget routes, with authenticated run scope. Reserve locks the run, verifies state/deadline and next request identity, then debits the declared model/tool/image/generated-token counters before acknowledging. A duplicate request returns its existing reservation; changed bytes conflict. Concurrent reservations cannot exceed remaining limits. Reconciliation verifies preserved response/receipt hashes and observed usage; explicit unexecuted rejection releases only proven unused reserved capacity according to the existing run policy, ambiguity retains capacity and voids the run. A terminal run cannot reserve more. Reconcile records actual overage and voids/alerts rather than hiding incurred usage. Financial settlement remains the independent restricted OPERATIONS route; a worker's asserted token count cannot alter financial charges.

## Cohort selection and publication authority

```text
CohortSelection =
  {kind:"historical_corpus", corpus_release_hash:ArtifactId,
   selected_membership_hash:ArtifactId} |
  {kind:"source_qualification", source_snapshot_hash:ArtifactId,
   profile_hash:ArtifactId, purpose:"source_audit"|"retrieval"|"jev_content",
   complete_publication_weeks:20, families_per_week:5|10,
   sampling_seed:20260920} |
  {kind:"prospective_jev", start_at:UtcInstant,
   eligibility_profile_hash:ArtifactId,
   target_registry_hash:ArtifactId, required_families:2000,
   minimum_publication_weeks:26, maturity_days:455,
   ordering:"first_eligible_by_arrival_then_family_id"} |
  {kind:"agent_capability", frozen_test_manifest_hash:ArtifactId,
   profile_hash:ArtifactId}
SplitSelection =
  {kind:"existing_split", split_manifest_hash:ArtifactId} |
  {kind:"qualification_profile", profile_hash:ArtifactId,
   purpose:"source_audit"|"retrieval"|"jev_content"|"agent_capability"} |
  {kind:"paired_prospective", pairing:"same_family_same_question",
   arms:["with_jev","without_jev"],
   order_seed:NonNegativeInt}
RealizedCohort = RecordMeta + {registration_hash:ArtifactId,
  selected_family_ids:List<PaperFamilyId>[0..1000000],
  membership_evidence_hashes:List<ArtifactId>[0..1000000],
  selection_closed_at:UtcInstant|null,
  last_included_arrival_at:UtcInstant|null,
  represented_publication_weeks:NonNegativeInt,
  disposition:"collecting"|"complete"|"shortfall"}
ArtifactPublicationReceipt = {schema_version:1,artifact_id:ArtifactId,
  committed_ledger_sequence:PositiveInt,published_at:UtcInstant}
```

Source qualification selector values are checked against the existing profile: source audit/retrieval use five families per week, Jev content uses ten. Retrieval's first20 development/80 evaluation and Jev's prescribed50/150 split follow the frozen hash/week algorithm in LAUNCH-PROFILE.md, not a new random division. Historical cohort/split hashes must already exist and be immutable before registration. Prospective registration stores no realized-membership hash; RealizedCohort artifacts are append-only observations linked back to its registration. Selection closes only after both the2000-family and26-week conditions under the registered eligibility policy, without replacing failed delivery cases. A shortfall remains visible. Agent-capability test artifacts preserve the100 tool conversations,50 image cases and context-depth evidence queries under the profile. Qualification evidence can be stored ahead of implementation, but its original registration/execution chronology needs independently verifiable evidence before import qualifies it.

**Publication authority:** Produced immutable bodies do not carry a self-authorizing runtime available_at. Preserved source/input/label availability fields describe upstream or earlier-receipt evidence and are cross-checked, never permission to use an artifact in an earlier snapshot. Storage publication is represented by ArtifactPublicationReceipt outside the artifact's hash preimage. Its ledger sequence is allocated and committed in the same transaction that installs the artifact metadata/reference. `published_at` is storage's database clock captured within that transaction; it is not asserted to be the later physical commit instant. Only committed records are readable. Snapshot seal holds the ledger-head serialization lock and records its cutoff ledger sequence, admitting only artifact publication sequences at or before that cutoff plus source-time and profile eligibility. Therefore a producer timestamp or an in-flight transaction timestamp cannot backdate eligibility. The publication receipt has its own hash if exported, and never becomes an input dependency of the artifact it publishes.

For exact wall-clock deadline eligibility, storage validates its database time after acquiring the domain/ledger locks immediately before inserting the sealed event. It rejects a delayed command that reaches that point after its deadline; transaction completion can occur later without rewriting the recorded decision instant. Prospective registration eligibility is similarly determined by committed ledger ordering plus independently evidenced imported chronology, not by arbitrary dates in a manifest. Imported historical artifacts retain original captured/claimed times and receive a new actual publication receipt; they cannot masquerade as previously runtime-visible. Preserved source/input/label availability fields remain provenance checked against their referenced receipts; effective runtime availability requires this publication receipt. This avoids adding a self-hash or rewriting a content-addressed payload at commit.
