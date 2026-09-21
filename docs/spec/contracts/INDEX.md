# Detailed contract catalog

These files are normative implementation detail for TDD.md, under technical-design work #71 and decisions 0008/0009. They specify planned contracts, not implemented services. SDD and its launch/learning/retrieval profiles own product behavior; the catalog owns exact version-1 field shapes and implementation constraints. A conflict is a defect to fix before code, not permission to choose whichever text is convenient.

## Reading the schemas

`Name = {field: Type}` defines a closed record. All displayed fields are required; `T | null` allows an explicit null and does not permit omission. Only fields expressly marked optional may be omitted, with their specified defaults applied at one documented boundary. `A | B` is a union selected by a literal discriminator where present. `list<T>[m..n]` and `List<T>[m..n]` bound array length; `list<T>` has no independent schema cap beyond the applicable message/artifact bound. Array items and keys are always typed. `Map<K,V>` is allowed only when both types and key restrictions are stated. No `Any`, opaque unvalidated object or arbitrary JSON is an application payload.

Code blocks use language-neutral type notation; the implementation translates these records into strict shared Python validators, JSON Schema for model declarations and versioned storage migrations. The notation is not executable Python. Implementers may not infer extra fields from examples or add `additionalProperties` permissiveness. The exact wire representation is ordinary UTF-8 JSON except for the explicitly binary artifact/vector/image endpoints. Server-generated fields stay server-controlled even when a command supplies them for an idempotency comparison.

### Common aliases

| Type | Wire definition |
| --- | --- |
| `RecordId`, `RunId`, `PaperFamilyId`, `PaperVersionId` | Lowercase canonical UUIDv4 string with RFC4122 variant; IDs identify persisted records, not filenames |
| `Sha256`, `ArtifactId`, `SnapshotId` | Exactly 64 lowercase hex characters; domain aliases retain distinct validation and authorization |
| `UtcInstant` | Valid `YYYY-MM-DDTHH:MM:SS.ffffffZ` UTC timestamp; reject offsets/local time and impossible dates |
| `UtcDate` | Valid `YYYY-MM-DD` calendar date in UTC |
| `YearMonth` | Valid `YYYY-MM` UTC billing month |
| `NonNegativeInt` | JSON integer from zero through signed int64 maximum; booleans are not integers |
| `PositiveInt` | NonNegativeInt greater than zero |
| `Finite` | Finite JSON number; no NaN or infinity and no numeric strings |
| `FiniteNonNegative` | Finite number >=0 |
| `Probability` | Finite number in [0,1] |
| `PositiveDecimal` | Decimal ASCII string matching `^[0-9]+(\.[0-9]+)?$`, strictly >0; parse to exact decimal, never binary money arithmetic |
| `NonEmptyString` | Nonempty UTF-8 NFC text without NUL; individual field bounds and endpoint caps still apply |
| `HttpsUrl` | Absolute HTTPS URI with hostname and optional port/path/query, no userinfo or fragment; permitted endpoint allowlist checked separately |
| `Money` | NonNegativeInt in USD microdollars; one USD = 1,000,000 |
| `ArtifactRef`, `RecordMeta` | Storage-owned exact records in STORAGE.md; never embed a manifest's self-hash into its own preimage |

`Id`, `Hash`, `Utc`, `Count`, `Positive`, `Text`, `Mode` in STORAGE.md are short aliases for RecordId, Sha256, UtcInstant, NonNegativeInt, PositiveInt, NFC text and ExecutionMode respectively. They are not alternative encodings. Hash-valued references and UUID-valued IDs are not interchangeable even though both serialize as strings.

A type alias does not establish existence: every reference is checked for committed presence, expected payload type/version, caller visibility and time eligibility. JSON shape validation alone does not establish those facts. Dates with uncertainty use the interval type owned by the source-data contract, not a fake precise timestamp.

`AGENTS.X` references the type X in AGENT-CONTRACTS.md. `SignatureEvidence` and `ArtifactPublicationReceipt` are storage-owned types.

## Contract owners

| Catalog | What it fixes | Planned code owner |
| --- | --- | --- |
| [STORAGE.md](STORAGE.md) | Shared records, every storage route, binary protocol, relational keys/indexes/constraints, transaction and recovery order, authorization | `contracts/storage.py`, `storage/`, `storage/migrations/` |
| [AGENT-CONTRACTS.md](AGENT-CONTRACTS.md) | Configuration/run/snapshot/question schemas, model transport, five tools, budgets, submissions, digest/rating projections and lifecycle | `contracts/tools.py`, `contracts/runs.py`, `agents/`, `tools/`, `web/` |
| [LEARNING.md](LEARNING.md) | Papers/sources/extraction/passages/vectors, labels/corpus/splits, fitting/bundles/predictions, card/Jev/report contracts | `contracts/papers.py`, `contracts/learning.py`, `learning/`, `models/`, `reader/`, `assessments/` |
| [SERVICE-API.md](SERVICE-API.md) | Exact non-storage routes, transport limits, harness proxies, model/reader and private-web APIs | Service HTTP adapters |
| [OPERATIONS.md](OPERATIONS.md) | Deployment/access/permission/funding, readiness, quotes/reservations, backup/anchor/health and activation operations | `contracts/operations.py`, `operations/`, storage command adapters |

The same type has one defining owner. Cross-domain routes reference it, not a second lookalike. Internal raw predictions, public agent cards and blinded rater projections are deliberately different types. A generic artifact endpoint never bypasses role restrictions. Operations roles are authenticated principals/capabilities of the existing components, not a demand for additional independently deployed services.

## Required implementation artifacts and integration sequence

Each implementation slice produces the strict domain validators, corresponding migration/indexes where durable, authorized API handlers and meaningful tests for its cited TDD items. Generated model tool schemas come from the same validator definitions used by the tool service. Schemas use explicit versions; additive fields are still rejected until a versioned contract is admitted. Preserve old schema readers needed for immutable snapshots; never reinterpret old bytes with a new target or rubric.

1. Storage slice: canonical bytes/hash fixtures, real PostgreSQL schema, blob commit, command idempotency and lease fencing. Verify crash cases and replay before any model work.
2. Source slice: immutable identities/observations, extraction/span manifests, dated citation captures and pure unknown-aware resolvers. Source exceptions return typed unavailable records.
3. Model slice: one frozen embedder, exact shape/normalization checks, common logistic/calibration numerical owner with separate head/baseline input wrappers, immutable bundle qualification and CAS.
4. Agent slice: snapshot membership, trusted harness envelope, model/domain validation, bounded tools, atomic complete submission and deterministic digest with private projection.
5. Evaluation/operations slice: registration and split locks, signed/imported evidence, score/baseline permission separation, mode activation, budget and restore acceptance.

Do not substitute fake behavior behind mocks for storage atomicity, lease fencing, network isolation, encrypted restore or live provider compatibility. Default checks can validate preserved fixtures and real local storage; paid/live qualification remains separately authorized. No passing document check establishes these implementation tests have run.

## Contract acceptance checklist

For each route, identify method/path, caller role, exact request type, exact success and unavailable/error shapes, idempotency behavior and durable commit boundary. For each artifact, identify byte format, self-hash boundary, producer/version, input lineage, availability and retention. For each state transition, name the actor, guard, transaction, resulting event and recovery after interruption. For each scientific computation, preserve exact units, order, dimensions, windows, masks, split membership and failure criteria from the protocols.

Examples demonstrate the schema; they do not expand it. Positive examples must satisfy both shape and stated cross-field constraints. Negative examples name the rejection, and must not silently coerce, clip, guess, reseal or charge twice. Root catalog and linked type references are checked together during review; storage-to-reader-to-tool and snapshot-to-submission-to-digest boundaries are reviewed end to end, not only per file.
