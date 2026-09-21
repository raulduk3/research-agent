## Exact agent, tool and presentation contracts

These types are closed records: every listed field is required unless marked `= default`; unknown keys fail validation. `T?` means required and nullable, not omitted. `List<T>[a..b]` bounds element count; `String[a..b]` bounds Unicode scalar values after NFC normalization, never bytes. Strings must be valid UTF-8; token limits are additional tokenizer checks. `UInt` is an integer >=0 excluding booleans; `PositiveInt` is >=1. `Probability` is a finite JSON number in [0,1]. UUID/hash/time aliases use the shared identity contract. All unions are discriminated by their named literal field. No contract permits arbitrary JSON maps. Aliases are `UUID = RecordId`, `ArtifactHash = Sha256`, `Instant = UtcInstant`, `Date = UtcDate`, `UInt = NonNegativeInt`, `SourceLocation = LEARNING.SourceLocator`; `UInt32` and `UInt64` are JSON integers in [0,2^32-1] and [0,2^64-1], respectively, excluding booleans. `Int[a..b]` and `Float[a..b]` are bounded integer and finite-number types. `PaperCard` and model/source manifests use their single defining owner in LEARNING.md. `STORAGE.X` below references the exact X definition in STORAGE.md, not another schema.

### HTTP envelope and tool authority

```text
ErrorCode = STORAGE.ErrorCode
Error = STORAGE.Error
Response<T> = STORAGE.Reply<T>
Command<T> = STORAGE.Command<T>
CommitReceipt = STORAGE.CommitReceipt
ToolRequest<A> = {schema_version: 1, run_id: UUID, snapshot_id: ArtifactHash,
  tool_call_id: String[1..128], arguments: A}
ToolResult<T> = {schema_version: 1, run_id: UUID, snapshot_id: ArtifactHash,
  tool_call_id: String[1..128], result: Response<T>,
  source_artifact_ids: List<ArtifactHash>[0..], remaining: BudgetRemaining}
```

Internal commands carry `Idempotency-Key: <UUID>` and mutually authenticated service identity. Tool requests carry a run capability in the Authorization header, never a JSON field. Do not hash or retain that header. `request_id` traces a transport attempt; the idempotency hash covers the route plus canonical domain payload and authenticated scope, excluding transport request id. A repeated key with a different domain payload returns 409 before effects. Tool uniqueness is `(run_id, tool_call_id)`: identical domain arguments replay its receipt without consuming another tool call; different arguments return 409. This does not let the model create free retries: fresh native tool-call ids consume calls, including validation failures.

Model-visible JSON contains only `arguments`. The harness inserts the pinned run/snapshot and actual native tool-call id. The schema exposed to the model does not include `ToolRequest`. Authentication and scope precede record existence lookup; hidden or nonexistent objects both return not_found. Valid authentication with a well-formed tool call consumes its call allowance before domain validation, even if invalid. Rejected unauthenticated network traffic never consumes a victim run's budgets. Error evidence ids must themselves be visible to the caller. Read failures have no domain mutation, but retain receipt, consumed counters and audit event.

### Configuration, slots, snapshots and questions

```text
Mode = collection | engineering | study
Intent = scan | compare | inspect | forecast | nominate | submit | stop
ToolName = query_cards | neighbors | graph | deep_read | submit
TargetId = LEARNING.TargetId
AgentConfigBody = {schema_version: 1,
  emphasis: evidence_first | methods_assumptions | earlier_work | limitations,
  model_manifest_id: ArtifactHash, system_prompt: String[1..16000],
  scan_policy: String[1..4000], read_policy: String[1..4000],
  probability_policy: String[1..4000],
  tools: List<ToolName>[1..5], samples_per_question: 1,
  extension: {}, profile_id: ArtifactHash}
AgentConfig = {config_id: ArtifactHash, body: AgentConfigBody}
SlotIdentity = {batch_id: ArtifactHash, shard_index: UInt,
  config_id: ArtifactHash,
  arm: population | jev_present | jev_absent, attempt: 0}
RunSlot = {slot_id: ArtifactHash, identity: SlotIdentity,
  state: queued | running | completed | void | missed_deadline,
  run_id: UUID?, deadline: Instant, terminal_event_id: UUID?}
SnapshotMember = {paper_id: PaperFamilyId, version_id: PaperVersionId,
  card_id: ArtifactHash, overview_manifest_id: ArtifactHash?,
  passages_manifest_id: ArtifactHash?, graph_manifest_id: ArtifactHash?,
  assessment_id: ArtifactHash?}
SnapshotManifest = {schema_version: 1,
  sealed_at: Instant, cutoff: Instant, source_watermark: UInt,
  representation_id: ArtifactHash, target_registry_id: ArtifactHash,
  bundle_id: ArtifactHash?, members: List<SnapshotMember>[0..],
  input_hashes: List<ArtifactHash>[0..]}
Snapshot = {snapshot_id: ArtifactHash, body: SnapshotManifest}
QuestionBody = {schema_version: 1,
  paper_id: PaperFamilyId, version_id: PaperVersionId,
  target_id: TargetId, target_version: ArtifactHash,
  snapshot_id: ArtifactHash, issued_at: Instant, seal_deadline: Instant,
  outcome_window_end: Instant, maturity_at: Instant,
  resolver_version: ArtifactHash}
Question = {question_id: ArtifactHash, body: QuestionBody}
RunSpec = {schema_version: 1, run_id: UUID, slot_id: ArtifactHash,
  mode: engineering | study, config_id: ArtifactHash,
  snapshot_id: ArtifactHash, profile_id: ArtifactHash,
  paper_ids: List<PaperFamilyId>[1..20], questions: List<Question>[0..60],
  specification_seed: UInt64, limits: BudgetLimits, deadline: Instant}
Run = {spec: RunSpec, state: queued | running | submitted | void | missed_deadline,
  started_at: Instant?, terminated_at: Instant?,
  submission_id: UUID?, termination_reason: ErrorCode?}
```

All lists representing sets require uniqueness; the fixed target order is reach, late activity, cross-subfield reach. Snapshot members sort by canonical family id. AgentConfigBody, SnapshotManifest, QuestionBody and DigestManifest are the stored hash preimages and carry no self-id; AgentConfig, Snapshot, Question and DigestDescriptor are API descriptors only. Each descriptor id equals SHA256 of its canonical body; never store the descriptor as its own body. References in semantic rules to question fields mean Question.body fields. Other immutable artifacts compose the shared ManifestHeader once where required; body schema_version is that same header field, never a duplicate key. Shards sort families by first-public time then family id and chunk into 20. Four population slots and the two separately registered comparison slots are created before dispatch; comparison slots use the evidence-first config and cannot nominate. All share concurrency two. Config admission rejects any known corpus identifier in all text fields, nonempty extension, repeated tool names or a non-pinned model. RunSpec question order is paper order followed by target order; absence of a qualified target is represented by no issued question, never an answer fabricated at zero. Starting pins all fields; no later mutable active pointer is consulted. Questions in the run all bind its snapshot. The run deadline is no later than its earliest question seal deadline; engineering runs without questions use batch seal plus 24 hours.

### Budget reservation and accounting

```text
BudgetLimits = {model_calls: 16, tool_calls: 40, deep_reads: 8,
  images: 12, context_tokens: 65536, generated_tokens: 16384,
  response_tokens: 8192, wall_ms: 1200000}
BudgetUsage = {model_calls: UInt, tool_calls: UInt, deep_reads: UInt,
  images: UInt, generated_tokens: UInt, elapsed_ms: UInt,
  measured_input_tokens: UInt, measured_output_tokens: UInt}
BudgetRemaining = {model_calls: UInt, tool_calls: UInt, deep_reads: UInt,
  images: UInt, generated_tokens: UInt, wall_ms: UInt}
RunBudgetReservation = {reservation_id: UUID, run_id: UUID,
  request_id: UUID, kind: model | tool, state: reserved | reconciled | ambiguous,
  reserved_generated_tokens: UInt, reserved_images: UInt,
  spend_reservation_id: UUID?, created_at: Instant,
  expires_at: Instant, consumed_generated_tokens: UInt?}
```

Storage locks the run budget row before admitting a reservation. Check terminal state, wall and forecast deadlines, global concurrency/spend, remaining counters, then full serialized context tokens with pinned processor and reserved output. Model output reservation is `min(8192, remaining_generated_tokens)` and input plus reservation must fit 65536; no hidden context eviction. Decrement model attempts before dispatch. Charge known generated tokens on every response, including invalid JSON; reconcile unused reserved output only when actual usage is known. An ambiguous completion retains its worst-case money reservation and terminates the run; it cannot free budget for another sample. Explicit non-executed 429/503 can retry once after five seconds, with a new recorded attempt and allowance. The 120-second timeout is inside the wall limit.

A deep_read attempt consumes both tool and deep-read counts before domain validation. Reserve up to two requested images against remaining image allowance before rendering; return bounded text-only content only if the requested source can truthfully be represented without omitted required images, otherwise refuse. Reconcile image allowance to actual returned images. Read responses include counters after consumption. Wall expiry is enforced by a durable deadline plus a monotonic process timer; restart cannot reset elapsed time. Expiry after running but before accepted submission is void; a queued slot that never starts by deadline is missed_deadline. Domain errors permit correction within remaining allowances. Integrity violations quarantine independently of ordinary schema errors.

### Exact five tool schemas

```text
QueryCardsArgs =
  {kind: "lookup", paper_ids: List<PaperFamilyId>[1..5]}
  | {kind: "search", query: String[1..], mode: overview | passages = overview,
     limit: Int[1..5] = 5, paper_id: PaperFamilyId? = null}
QueryCardsData = {items: List<CardHit>[0..5], query_hash: ArtifactHash?,
  mode: lookup | overview | passages}
CardHit = {card: PaperCard, evidence: QueryEvidence?}
QueryEvidence = {query_hash: ArtifactHash, snapshot_id: ArtifactHash,
  mode: overview | passages, retrieval_manifest_id: ArtifactHash,
  paper_id: PaperFamilyId, version_id: PaperVersionId,
  similarity: Float[-1..1], passages: List<PassageHit>[0..5]}
PassageHit = {evidence_id: ArtifactHash, passage: LEARNING.PassageEvidence}
NeighborsArgs = {paper_id: PaperFamilyId, limit: Int[1..5] = 5}
NeighborsData = {paper_id: PaperFamilyId, items: List<Neighbor>[0..5]}
Neighbor = {paper_id: PaperFamilyId, version_id: PaperVersionId,
  source_artifact_id: ArtifactHash, similarity: Float[-1..1],
  outcomes: List<NeighborOutcome>[3..3]}
NeighborOutcome = {target_id: TargetId, target_version: ArtifactHash,
  value: bool?, unavailable_reason: unavailable | immature | incompatible | null,
  label_artifact_id: ArtifactHash?, known_at: Instant?}
GraphArgs = {paper_id: PaperFamilyId,
  direction: references | citations = references, limit: Int[1..20] = 20}
GraphData = {paper_id: PaperFamilyId, direction: references | citations,
  edges: List<GraphEdge>[0..20], total_visible_edges: UInt,
  missingness: complete | partial | unavailable}
GraphEdge = {from_paper_id: PaperFamilyId, to_paper_id: PaperFamilyId,
  source_artifact_ids: List<ArtifactHash>[1..], captured_at: Instant}
DeepReadArgs =
  {kind: "section", paper_id: PaperFamilyId, section_id: ArtifactHash}
  | {kind: "pages", paper_id: PaperFamilyId, page_numbers: List<PositiveInt>[1..2]}
  | {kind: "continuation", paper_id: PaperFamilyId, next_span: ArtifactHash}
DeepReadData = {paper_id: PaperFamilyId, version_id: PaperVersionId,
  evidence_id: ArtifactHash, span_id: ArtifactHash, text: String[0..],
  locations: List<SourceLocation>[1..], images: List<PageImage>[0..2],
  coverage: complete | partial, next_span: ArtifactHash?}
PageImage = {evidence_id: ArtifactHash, artifact_id: ArtifactHash,
  page_number: PositiveInt, mime_type: "image/png",
  width_px: Int[1..1600], height_px: Int[1..1600], render_dpi: 150}
SubmitArgs = {submission_id: UUID, answers: List<Answer>[0..60],
  nominations: List<Nomination>[0..7]}
Answer = {question_id: ArtifactHash, probability: Probability,
  rationale: String[0..2000], evidence_ids: List<ArtifactHash>[0..5]}
Nomination = {paper_id: PaperFamilyId, rationale: String[0..2000]}
SubmitData = {submission_id: UUID, submission_hash: ArtifactHash,
  forecast_ids: List<UUID>[0..60], accepted_at: Instant,
  ledger_sequence: PositiveInt, run_state: "submitted"}
```

Search query's formatted token length is <=256. No empty/whitespace-only query and no truncation. In unfiltered passage search the result limit counts families, with at most two non-overlapping passages per family. With a paper filter it counts non-overlapping passages, so a single CardHit can hold up to five. Greedily skip overlapping spans in rank order; ties use paper-family id, version id, section order, then passage start offset. Search results sort exact cosine descending, ties canonical family id. Lookup preserves requested order; any absent/not-visible id refuses the call rather than silently returning an incomplete lookup. A search paper filter must be visible. Base cards fit 3000 embedding tokens using the existing explicit overview-reference fallback. QueryEvidence never modifies the immutable base card. Neighbor known outcomes require identical target version and known_at <= snapshot cutoff; null outcomes require a reason, known values require null reason and provenance. Graph returns one hop in canonical peer-id order and never invokes a remote source. DeepRead page numbers are one-based distinct source pages; continuation must be a previously returned locator for the same run snapshot and family. Text is <=6000 agent-model tokens, image count <=2; next_span nonnull implies partial. The immutable span preserves exact source boundaries and cannot be a user-supplied filesystem offset/path.

### Model request/response and execution

```text
ProtectedTurn = {note: String[0..1000], intent: Intent, extension: {}}
ToolCall = {id: String[1..128], type: "function",
  function: {name: ToolName, arguments: String[2..]}}
AssistantContent = {core: ProtectedTurn}
ModelTurn = {content: AssistantContent, tool_calls: List<ToolCall>[0..40]}
TextPart = {type: "text", text: String[0..]}
ImagePart = {type: "image_url", image_url: {url: String[1..]}}
ChatMessage =
  {role: "system", content: String[1..16000]}
  | {role: "user", content: List<TextPart | ImagePart>[1..]}
  | {role: "assistant", content: String[2..], tool_calls: List<ToolCall>[0..40]}
  | {role: "tool", tool_call_id: String[1..128], content: String[2..]}
ModelRequest = {model: String[1..128], messages: List<ChatMessage>[1..],
  temperature: 0.7, top_p: 0.9, repetition_penalty: 1.0,
  max_tokens: Int[1..8192], seed: UInt32, stream: false,
  tools_schema_id: ArtifactHash, response_schema_id: ArtifactHash}
ModelReceipt = {request_id: UUID, run_id: UUID, turn_index: UInt,
  request_artifact_id: ArtifactHash, response_artifact_id: ArtifactHash?,
  requested_at: Instant, finished_at: Instant?,
  input_tokens: UInt?, output_tokens: UInt?,
  disposition: accepted | invalid_output | explicit_rejection | ambiguous,
  provider_request_id: String[1..256]?}
```

`ModelRequest` is the typed adapter input, not a fictitious provider wire API: resolve the two schema ids to the exact qualified native `tools` and structured-output parameter fields and record those transmitted bytes. `AssistantContent` is parsed from native assistant content JSON; function.arguments is independently strict-parsed as its named tool's domain record. Native arbitrary provider response fields are retained as permitted raw payload but are never executable domain fields. Image URLs are generated by the harness from verified rendered bytes using qualified inline data encoding or authenticated scoped transport; model-supplied URLs are never fetched. All schemas set additionalProperties false. JSON duplicate keys, duplicate call ids, missing core, content outside the envelope, nonempty extension and unknown function names reject the complete turn before executing its first call. The provider may have separate reasoning fields; never require, display or use private reasoning as protected notes.

Execute validated calls serially and repeat budget/deadline checks for each. Invalid tool domain arguments generate that call's typed error, consuming its call, then subsequent permitted calls may run. An accepted submit stops execution immediately, ignoring any later calls in that response with recorded not-executed disposition. An empty call list with stop ends void unless a submit has already been accepted. Native response finish_reason length or unknown completion cannot be treated as a valid truncated JSON submission. Provider tool/schema qualification must demonstrate this transport combination; an incompatible endpoint is an activation failure, not permission to change the interface.

### Submission transaction and forecast record

```text
Submission = {submission_id: UUID, run_id: UUID, snapshot_id: ArtifactHash,
  request_hash: ArtifactHash, payload: SubmitArgs, accepted_at: Instant,
  ledger_sequence: PositiveInt}
ForecastProducer =
  {kind: "agent", run_id: UUID, config_id: ArtifactHash}
  | {kind: "human", rater_id: UUID, view_receipt_id: UUID}
  | {kind: "baseline", baseline_id: ArtifactHash, input_receipt_id: UUID}
  | {kind: "population_mean", component_forecast_ids: List<UUID>[1..4]}
Forecast = {schema_version: 1, forecast_id: UUID, question_id: ArtifactHash,
  snapshot_id: ArtifactHash, producer: ForecastProducer,
  probability: Probability, sealed_at: Instant, ledger_sequence: PositiveInt,
  rationale: String[0..2000], evidence_ids: List<ArtifactHash>[0..5],
  submission_id: UUID?}
ToolReceipt = {run_id: UUID, tool_call_id: String[1..128],
  tool_name: ToolName, request_hash: ArtifactHash, response_hash: ArtifactHash,
  visible_evidence_ids: List<ArtifactHash>[0..], created_at: Instant,
  usage_after: BudgetUsage}
```

Submit validation order: parse closed types; authenticate scope; replay exact idempotent request if already committed; lock run/slot/budget rows; confirm running state and deadlines; compare exact set of answer question ids with issued set and reject duplicates; bind question target/version/snapshot from stored definitions; check finite probabilities, rationale/evidence bounds; require each evidence id to be snapshot-visible and returned in prior successful receipts; check unique nominations belong to shard and arm permits nominations; atomically insert submission, all forecasts/nominations, terminal run+completed slot and one ledger append. Any failure inserts only a sanitized rejection audit and consumes the tool attempt, never a partial forecast. Serialization retry reruns this same transaction/key, not a model call. Different submission ids after success conflict. An exact recorded retry after terminal/deadline returns the original result without new effects. Original acceptance must have met the deadline. Population mean uses only population forecasts and seals before outcomes; zero components means unavailable, never 0.5.

### Digest, rating and human-forecast projections

```text
DigestManifest = {schema_version: 1,
  batch_id: ArtifactHash, source_watermark: UInt, cutoff: Instant,
  profile_id: ArtifactHash, shuffle_seed: UInt64,
  entries: List<DigestInternalEntry>[0..12], created_at: Instant}
DigestDescriptor = {digest_id: ArtifactHash, body: DigestManifest}
DigestInternalEntry = {entry_id: ArtifactHash, paper_id: PaperFamilyId,
  version_id: PaperVersionId, position: Int[0..11],
  origin: population | random_control | service,
  nomination_refs: List<UUID>[0..], forecast_ids: List<UUID>[0..],
  source_capture_ids: List<ArtifactHash>[0..]}
Rating = {rating_id: UUID, rater_id: UUID, digest_id: ArtifactHash,
  entry_id: ArtifactHash, paper_id: PaperFamilyId,
  value: like | dislike | skip, created_at: Instant,
  supersedes_event_id: UUID?}
RatingArgs = {request_id: UUID, digest_id: ArtifactHash, entry_id: ArtifactHash,
  value: like | dislike | skip, expected_previous_event_id: UUID?}
RatingState = {state: "unrated"} |
  {state: "rated", value: like | dislike | skip, rating_id: UUID, created_at: Instant}
DigestView = {digest_view_id: UUID, publication_day: Date,
  entries: List<DigestEntryView>[0..12]}
DigestEntryView = {entry_view_id: UUID, paper_id: PaperFamilyId,
  title: String[1..], abstract: String[0..], publication_date: Date,
  source_link: String[1..], rating: RatingState, details_available: bool}
DetailView = {entry_view_id: UUID, runs: List<AnonymousRunView>[0..],
  author_citations: List<HumanAuthorCitation>[0..], assessment: HumanAssessment}
HumanAuthorCitation = {author_id: String[1..512], count: UInt?,
  captured_at: Instant?, unavailable_reason: missing_source | not_available_as_of | null}
HumanAssessment =
  {status: "available", source_label: "Jev paper-content assessment",
   fields: LEARNING.JevFieldMap<LEARNING.JevFieldResult>, assessed_at: Instant}
  | {status: "unavailable", source_label: "Jev paper-content assessment"}
AnonymousRunView = {label: String[1..80],
  answers: List<AnonymousAnswer>[0..3], turns: List<ProtectedTurn>[0..16]}
AnonymousAnswer = {target_id: TargetId, probability: Probability,
  rationale: String[0..2000], evidence: List<VisibleEvidence>[0..5],
  verdict: "unresolved" | "unavailable" | "true" | "false",
  baselines: List<AnonymousBaseline>[0..]}
VisibleEvidence = {evidence_view_id: UUID, text: String[0..],
  paper_id: PaperFamilyId, location: SourceLocation}
AnonymousBaseline = {name: String[1..80], probability: Probability?,
  verdict: "unresolved" | "unavailable" | "true" | "false"}
HumanQuestionView = {question_view_id: UUID, paper_id: PaperFamilyId,
  target_id: "citation_reach_365d", prompt: String[1..],
  deadline: Instant, state: open | answered | expired,
  probability: Probability?}
HumanForecastArgs = {request_id: UUID, question_view_id: UUID,
  probability: Probability, rationale: String[0..2000],
  evidence_view_ids: List<UUID>[0..5]}
HumanViewReceipt = {receipt_id: UUID, rater_id: UUID,
  snapshot_id: ArtifactHash, question_id: ArtifactHash,
  visible_evidence_ids: List<ArtifactHash>[0..], viewed_at: Instant}
```

Storage freezes the digest watermark only after every scheduled slot is terminal/expired. For each population configuration merge shard nomination lists round-robin in ascending shard order, skipping repeats. Sort configs by immutable id and rotate by UTC day ordinal modulo four; round-robin these lists to seven unique papers. Add up to three controls from the predeclared hash draw after excluding selected families, then up to two deduplicated service picks with their captured order. Shuffle final entries using the recorded domain-separated seed. Comparison nominations cannot enter. Entry ids are content hashes of canonical {batch_id, source_watermark, paper_id, profile_id}; positions and digest id are assigned after deterministic selection and shuffling. Thus replay does not generate new UUIDs or change the digest hash. Digest created_at is its frozen cutoff, not the time of rebuilding. Rating never mutates the digest.

RatingArgs and HumanForecastArgs are private web forms, not storage command bodies. The backend authenticates the session, resolves opaque entry/question/evidence view ids, and constructs the canonical STORAGE.RatingInput or STORAGE.HumanForecastInput. Rating backend obtains rater id from authenticated session, not RatingArgs. It maps expected_previous_event_id to STORAGE.RatingInput.supersedes_event_id and records the authenticated view_receipt_id. In one transaction require the entry belongs to the digest, compare expected_previous_event_id to latest rating event, insert append-only Rating event, and return saved state; conflicting concurrent edits return 409. A failed write leaves the previous state. Both like, dislike and explicit skip unlock details for that rater; unread/unrated does not. GET details checks this before loading protected projection. Render strictly allowlisted fields using HTML escaping, with no model summary. HumanAuthorCitation projects only public author identity/count/capture time and typed missingness; omit capture artifact links. HumanAssessment projects the fixed eight-field distributions/confidences and assessment time only, stripping provider/request/configuration/qualification hashes. Both are loaded from the paper snapshot projection consistently across population, control and service entries, never from a run arm, so treatment withholding cannot label an entry. Before rating neither author counts nor Jev fields are exposed. Available counts require captured_at and null unavailable_reason; unavailable counts require null count plus reason. Detail source artifact identity stays internal. Never serialize a general PaperCard or manifest into public detail, as nested config/run/arm/source provenance defeats blinding. Evidence links use opaque view ids scoped to rater/paper; no underlying run ids in URL, DOM, downloadable JSON or error. Generate stable-per-view labels with per-paper domain separation so labels cannot track configuration across papers. Service/control entry summaries have identical fields; a missing run detail is shown without an origin explanation. Counts and prose can weaken practical blinding and are reported as limitations.

The separate human-question view selects up to three primary-target questions with batch-hash sampling and opens at issue time, independent of digest completion. HumanForecastArgs resolves its internal question/snapshot using the authenticated view id and checks all cited evidence against that rater's stored receipts. Seal one answer per rater/question before deadline with the same ledger transaction semantics. Missing participation stays absent. An answered question is immutable except exact retry; expired questions reject writes but never prevent digest or rating access.

### Boundary examples

Valid model-domain lookup (UUID shown as an ordinary string, with no authority fields):

```json
{"kind":"lookup","paper_ids":["9d4fb1f6-ecb1-4d91-a713-3454f25b902f"]}
```

Invalid lookup, rejected for authority injection and mixed alternatives:

```json
{"kind":"lookup","paper_ids":["9d4fb1f6-ecb1-4d91-a713-3454f25b902f"],"query":"causal inference","run_id":"9d4fb1f6-ecb1-4d91-a713-3454f25b902f"}
```

Valid zero-question engineering submit; invalid for any run with issued questions:

```json
{"submission_id":"066884e4-a9cc-4783-b018-892945e55c41","answers":[],"nominations":[]}
```

Invalid probability is never coerced or clamped:

```json
{"question_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","probability":"0.7","rationale":"Reported comparison only.","evidence_ids":[]}
```

Valid rated projection and an explicitly unrated projection are different shapes:

```json
{"state":"rated","value":"skip","rating_id":"066884e4-a9cc-4783-b018-892945e55c41","created_at":"2026-09-20T12:00:00.000000Z"}
```

```json
{"state":"unrated"}
```
