# Non-storage service APIs

These routes complete the planned internal and private-web interfaces. Shared primitive names come from INDEX.md; `Reply`, `Command`, `Error` and `LeaseFence` are STORAGE types. `AGENTS.X` and `LEARNING.X` name the single defining owner. All JSON records are closed and strictly typed; every field is required unless its defining schema specifies a default. Success bodies below are wrapped in `STORAGE.Reply<T>` except HTML pages and native remote model transport. Errors use STORAGE.Error and its HTTP mapping. Every service enforces the same 1 MiB JSON request limit; artifact bodies travel through storage's bounded streaming protocol. Response content also obeys the tighter tool/context limits. No worker, reader or model service obtains SQL or durable-volume privileges. Actual artifact visibility derives from STORAGE.ArtifactPublicationReceipt, never producer-supplied available_at; no receipt/self-hash is inserted into the body it publishes.

## Tool service

All five paths are literal routes, not an arbitrary tool dispatcher. Method is POST; authenticated caller is an admitted run harness with a scoped capability. The model sees only the domain arguments described in AGENT-CONTRACTS.md. The harness binds run_id, snapshot_id and native tool_call_id. Tool service verifies those fields against the admitted run, then resolves only its permitted snapshot artifacts through storage. HTTP 200 returns an accepted tool envelope; a domain-level unavailable/error is represented in ToolResult.result. Malformed transport/authentication uses HTTP 400/401/403 and Reply error. Shape/domain/state/budget failures use 422/409/429 respectively when no tool envelope could be admitted; once admitted they are retained typed tool receipts and consume the attempt.

| Literal path | JSON request | HTTP 200 data |
| --- | --- | --- |
| `/v1/tools/query_cards` | `AGENTS.ToolRequest<AGENTS.QueryCardsArgs>` | `AGENTS.ToolResult<AGENTS.QueryCardsData>` |
| `/v1/tools/neighbors` | `AGENTS.ToolRequest<AGENTS.NeighborsArgs>` | `AGENTS.ToolResult<AGENTS.NeighborsData>` |
| `/v1/tools/graph` | `AGENTS.ToolRequest<AGENTS.GraphArgs>` | `AGENTS.ToolResult<AGENTS.GraphData>` |
| `/v1/tools/deep_read` | `AGENTS.ToolRequest<AGENTS.DeepReadArgs>` | `AGENTS.ToolResult<AGENTS.DeepReadData>` |
| `/v1/tools/submit` | `AGENTS.ToolRequest<AGENTS.SubmitArgs>` | `AGENTS.ToolResult<AGENTS.SubmitData>` |

ToolResult is already a complete envelope and is not wrapped a second time in Reply. Its nested result.request_id is assigned at the harness boundary. The model-facing tool response is the same sanitized domain payload, source identities and counters; credentials and internal service receipts are never included. Cached immutable reads still recheck visibility and record fresh retrieval receipts. Exact native tool-call retries replay their prior receipt; no second domain action or counter debit occurs.

## Harness-only proxy routes

These are not model-visible functions. A capability covers one run and cannot invoke arbitrary storage commands. The tool service validates each request and forwards a fixed storage command under its service certificate. Storage is the only budget and event owner. The worker cannot assert a successful submit through these routes.

```text
HarnessEnvelope<P> = {schema_version: 1, run_id: RunId,
  snapshot_id: SnapshotId, command: STORAGE.Command<P>}
HarnessEventInput = {expected_next_sequence: PositiveInt, event: HarnessEvent}
HarnessEvent =
  {kind: "model_request", turn_index: Int[0..15], request_hash: Sha256,
   reservation_id: RecordId, request_seed: UInt32}
  | {kind: "model_response", turn_index: Int[0..15], request_hash: Sha256,
     response_hash: Sha256, elapsed_microseconds: NonNegativeInt}
  | {kind: "terminal", state: "void", reason: STORAGE.ErrorCode,
     evidence_hashes: List<Sha256>[0..20]}
RunBudgetReserveInput = {request_id: RecordId, kind: model | tool,
  request_artifact_id: Sha256, reserved_generated_tokens: NonNegativeInt,
  reserved_images: NonNegativeInt, spend_reservation_id: RecordId | null}
RunBudgetReconcileInput = {reservation_id: RecordId,
  observed_response_hash: Sha256 | null,
  consumed_generated_tokens: NonNegativeInt | null,
  returned_images: NonNegativeInt | null,
  disposition: completed | explicit_rejection | ambiguous}
HarnessArtifactInput = {kind: model_request | model_response,
  byte_length: PositiveInt, media_type: "application/json", expected_hash: Sha256}
HarnessArtifactResult = {artifact_id: Sha256, receipt: STORAGE.CommitReceipt}
```

`UInt32` and `Int[a..b]` follow AGENTS aliases. Request/response artifact JSON is permitted sanitized provider payload, not an executable arbitrary command. The proxy validates model requests against AGENTS.ModelRequest and its qualified transmitted schema; responses are bounded preserved provider bytes followed by strict domain parsing. The artifact route uses multipart/form-data with exactly metadata (HarnessEnvelope<HarnessArtifactInput>, application/json, at most 128 KiB) and payload (application/octet-stream) parts. Stream payload bytes without wrapping or escaping them into another JSON string. A model_request payload is at most 256 MiB, accommodating the admitted 12 images at 1600-pixel bounds even when the qualified provider transport uses base64; a model_response payload is at most 1 MiB. Reject declared or streamed overage before forwarding. Hash the exact sanitized UTF-8 provider JSON bytes without NFC rewriting; embedded image content must resolve to the admitted image hashes and processor limits. The ordinary 1 MiB JSON limit applies to other routes. This endpoint does not accept standalone page-image uploads. The model response artifact is retained even when domain parsing fails, subject to the admitted retention policy; secret fields are removed with distinct stored hash/policy bridge. Request artifact identity pins the full actual qualified provider request, not merely an inferred summary.

| Method and path | Request | Success data |
| --- | --- | --- |
| POST `/v1/harness/artifacts` | Multipart metadata and streamed payload as defined above | HTTP 201 `HarnessArtifactResult`; identical retry 200 |
| POST `/v1/harness/events` | `HarnessEnvelope<HarnessEventInput>` | HTTP 201 `{event_id:RecordId,sequence:PositiveInt,receipt:STORAGE.CommitReceipt}` |
| POST `/v1/harness/budget/reserve` | `HarnessEnvelope<RunBudgetReserveInput>` | HTTP 201 `AGENTS.RunBudgetReservation` |
| POST `/v1/harness/budget/reconcile` | `HarnessEnvelope<RunBudgetReconcileInput>` | HTTP 200 `AGENTS.RunBudgetReservation` |

The artifact route is the bounded implementation of already-required request logging, not generic worker storage access. Tool receipt events are written by the tool service after execution, not accepted from model/harness assertions. Started events originate in orchestrator/launcher admission. Missed-deadline events originate in scheduler expiry. Submitted originates only from atomic submit. For event writes check next sequence, matching request/reservation and response hash; conflicting sequence returns409 without a second event.

Reserve checks recorded request size, remaining run limits, deadline and admitted monetary reservation together before permitting the call. Input-request allowance is measured by the pinned processor, not trusted from a worker count. A tool reservation has zero generated-token allowance; a model reservation has zero images to return. Response reconciliation validates provider usage/processor counts against retained bytes. completed requires response hash and nonnull counts; explicit_rejection requires response hash proving nonexecution and zero returned/consumed counts; ambiguous permits missing response and null counts, keeps worst-case reservations and voids the run. Consumption cannot exceed reserved values; overage is an integrity/invalid-output result, never negative remaining counters. Financial settlement is OPERATIONS.SpendReconciliation by its authorized owner; these routes cannot manufacture or reconcile charges.

## Local model service

Caller authenticates as reader/models batch worker using a fenced job scope, or tools with an admitted run/snapshot scope. The model service validates scope through storage before loading inputs; agents cannot call it directly. It owns the one frozen embedder process, not a new copy per request. No route accepts custom weights, executable model paths or an arbitrary model repository.

```text
ComputationScope =
  {kind: "job", job_id: RecordId, fence: STORAGE.LeaseFence}
  | {kind: "run", run_id: RunId, snapshot_id: SnapshotId}
EmbedInput =
  {kind: "overview", paper_version_id: PaperVersionId, source_hash: Sha256}
  | {kind: "passage", passage_hash: Sha256}
  | {kind: "query", query: String[1..]}
EmbedRequest = {schema_version: 1, request_id: RecordId,
  scope: ComputationScope, representation_hash: Sha256, input: EmbedInput}
EmbedResult =
  {kind: "document", embedding: STORAGE.ArtifactRef}
  | {kind: "query", representation_hash: Sha256,
     query_hash: Sha256, vector: List<Finite>[1024..1024]}
PredictRequest = {schema_version: 1, request_id: RecordId,
  scope: ComputationScope, bundle_hash: Sha256,
  feature_hash: Sha256, as_of: UtcInstant,
  mode: retrospective_estimate | live_snapshot}
PredictResult = {prediction: STORAGE.ArtifactRef}
```

| Method and path | Request | Success data |
| --- | --- | --- |
| POST `/v1/models/embed` | `EmbedRequest` | HTTP 200 `EmbedResult` |
| POST `/v1/models/predict` | `PredictRequest` | HTTP 200 `PredictResult` |

Run-scoped EmbedRequest admits query inputs only; document encoding and PredictRequest are fenced admitted-job operations, preventing a model read from scheduling unbounded computation. Document result references committed LEARNING.EmbeddingRecord with tensor payload; prediction references committed LEARNING.PredictionArtifact. Commit computation results via storage under the admitted job or scoped computation, never local persistent state. Query vector is a service-only finite unit-L2 1024-vector; tools use it for exact retrieval and never include it in model-visible replies. Query limit<=256 formatted tokens; documents obey the fixed representation/chunk contract. Representation/bundle must match the pinned run or admitted job. as_of cannot override run snapshot cutoff or job evaluation cutoff. Original features are required for prediction; unqualified/incompatible/missing input returns unavailable rather than padded vectors or guessed predictions. Cache key is canonical operation+ordered input hashes+representation/bundle+mode+cutoff; authentication is rechecked before returning cached results. No training HTTP route exists: fitting is the admitted leased batch-job process with its learning manifest and checkpoint contracts.

The remote GLM endpoint remains the qualified native chat-completions transport specified by AGENTS.ModelRequest/ModelReceipt and deployment binding; its actual provider wire API and authentication are verified, not guessed here. Jev and source capture likewise use their admitted adapter evidence and immutable captured responses rather than fabricated endpoint schemas.

## Reader construction and index publication

Reader owns deterministic assembly, not storage publication authority. Callers are admitted orchestrator/job workers through service certificates. Each input is an already committed typed artifact; job fence limits declared inputs and protects completion. The run tool service invokes read computations over existing snapshots; it cannot trigger fresh source capture or mutate an index.

```text
CardBuildInput = {paper_version_id: PaperVersionId,
  source_record_hash: Sha256, representation_hash: Sha256,
  extraction_hash: Sha256 | null, prediction_hash: Sha256 | null,
  graph_manifest_hash: Sha256 | null, assessment_hash: Sha256 | null,
  neighbor_input_manifest_hash: Sha256, as_of: UtcInstant}
ReaderBuildRequest = {schema_version: 1, request_id: RecordId,
  job_id: RecordId, fence: STORAGE.LeaseFence, input: CardBuildInput}
ReaderBuildResult = {card_artifact: STORAGE.ArtifactRef}
ReaderIndexRequest = {schema_version: 1, request_id: RecordId,
  job_id: RecordId, fence: STORAGE.LeaseFence,
  index_manifest: STORAGE.ArtifactRef}
ReaderIndexResult = {index_artifact: STORAGE.ArtifactRef,
  completion_receipt: STORAGE.CommitReceipt}
```

`neighbor_input_manifest_hash` must decode as the already-defined snapshot-compatible LEARNING.VectorIndexManifest with prior-label inputs already declared by the admitted job and checked against its cutoff; it is not an untyped arbitrary neighbor list. Card builder loads the declared source/feature/graph/assessment owners, checks storage publication receipts against the admitted cutoff ledger sequence and all applicable source timestamps<=as_of, applies exact public-card projection and tokenizer cap, then commits its immutable body via storage. Snapshot association is an API descriptor and cannot be included circularly in the stored card hash. Missing optional inputs produce their typed unavailable states. Never auto-fetch a replacement source to fill a declared missing input.

| Method and path | Request | Success data |
| --- | --- | --- |
| POST `/v1/reader/cards/build` | `ReaderBuildRequest` | HTTP 200 `ReaderBuildResult` |
| POST `/v1/reader/indexes/publish` | `ReaderIndexRequest` | HTTP 200 `ReaderIndexResult` |

Index publish validates every member's version/representation/availability, stable ordering, checksum and completeness; uploads canonical manifest then conditionally completes its fenced job in storage. It does not replace old snapshots or mutate active members. A stale fence returns409/lease error and leaves any unreferenced computed blob collectible; no partial index is exposed. index_manifest must resolve to exactly LEARNING.VectorIndexManifest; its potentially large body uses storage artifact upload, not this JSON request. This size policy never permits truncating membership.

## Private rating application

Only the two provisioned raters have sessions; no registration endpoint. Credentials/cookies are not artifact content. Authenticated session determines rater_id; every view id is checked against that identity. Mutating routes require a same-origin CSRF token and Origin check in addition to Secure HttpOnly SameSite=Strict cookie. Session expires24hours after creation, server-side revocation takes effect immediately. TLS/private bind are deployment activation gates. JSON actions and HTML forms share the same strict underlying schemas and authorized handlers.

```text
LoginInput = {username: String[1..128], password: String[1..1024]}
LoginResult = {authenticated: true, expires_at: UtcInstant}
LogoutInput = {}
LogoutResult = {authenticated: false}
RatingActionResult = {state: AGENTS.RatingState}
HumanForecastResult = {question_view_id: RecordId, forecast_id: RecordId,
  sealed_at: UtcInstant, state: "answered"}
HumanQuestionsView = {questions: List<AGENTS.HumanQuestionView>[0..3]}
```

| Method and literal route pattern | Request/parameters | Success |
| --- | --- | --- |
| GET `/login` | No query/body; anonymous | HTTP200 escaped HTML login and CSRF form |
| POST `/v1/session/login` | `LoginInput`; CSRF pre-session token | HTTP200 `LoginResult`; sets fresh session cookie |
| POST `/v1/session/logout` | `LogoutInput`; session/CSRF | HTTP200 `LogoutResult`; revokes server session and clears cookie |
| GET `/digests/{digest_view_id}` | UUIDv4 path only; session | HTTP200 HTML rendering of `AGENTS.DigestView` |
| GET `/v1/digests/{digest_view_id}` | Same authorized path, no query/body | HTTP200 `AGENTS.DigestView` |
| GET `/v1/entries/{entry_view_id}/details` | UUIDv4 path, no query/body | HTTP200 `AGENTS.DetailView`; 403 until this rater rated |
| POST `/v1/ratings` | `AGENTS.RatingArgs`; session/CSRF | HTTP201 `RatingActionResult` |
| GET `/human-forecasts` | No query/body; session | HTTP200 HTML rendering of `HumanQuestionsView` |
| GET `/v1/human-forecasts` | No query/body; session | HTTP200 `HumanQuestionsView` |
| POST `/v1/human-forecasts` | `AGENTS.HumanForecastArgs`; session/CSRF | HTTP201 `HumanForecastResult` |
| GET `/v1/evidence/{evidence_view_id}` | UUIDv4 path, no query/body; session | HTTP200 `AGENTS.VisibleEvidence` |

The `/v1/ratings` and `/v1/human-forecasts` paths belong to the private web service, not the storage origin; routing/service certificates keep those interfaces distinct. Public requests never contain rater identity, trusted receipt identity or arbitrary artifact hashes granting reads. Backend resolves opaque view ids then constructs STORAGE.RatingInput/HumanForecastInput, preserving request idempotency and provenance. Failed writes show unsaved, not success. Human forecast expiry returns409 deadline error; it never blocks digest reading. Initial login failure is a uniform401 without revealing account existence; malformed shape400/422, no CSRF403. Unauthenticated private pages return401 or redirect to login without protected content. Hidden/nonexistent view ids return indistinguishable404. Detail unlock checks the authenticated rater's persisted explicit like/dislike/skip before reading protected detail artifacts.

Only enumerated projection fields enter HTML, JSON, links, DOM data attributes or errors. Evidence-view access is separately authorized for rated detail versus timely human-question reading; a generic evidence URL cannot unlock all artifacts. Source links are sanitized external paper links with safe schemes, not arbitrary HTML from source text. Browser responses use no-store for authenticated projections and restrictive CSP. No service, configuration, run, comparison-arm or control identity is emitted in these views. Model calls never occur while rendering or rating.
