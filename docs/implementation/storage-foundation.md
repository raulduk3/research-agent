# Durable storage foundation evidence

Work under #72, through execution slices #80 and #81, merged in #84 and #95; extended under #73 by #132 with run, snapshot, sheet, submission and rating records. The SDD and TDD remain normative. Requirement markers remain pending: working storage primitives do not implement every source, resolver, run, recovery or operating contract that uses them.

## Transaction and provenance owners

`storage/commands.py` owns serializable command execution. It claims both authenticated principal/key and principal/command identity, applies domain changes and typed ledger records, stores the exact successful response, and commits once. Replays retain the original request ID and response bytes. Serialization/deadlock retry is bounded to three attempts. Filesystem bytes are fsynced before reference insertion; a rolled-back transaction can leave reusable orphan bytes, never a successful reference or command response.

`storage/jobs.py` uses that owner for internal enqueue and claim/renew/checkpoint/complete. Claims and fences bind to the authenticated principal. A command that already committed can replay after expiry; a fresh command cannot acquire the expired owner's authority. Row locks precede database-clock fence checks, and expiry is checked again after verification and ledger insertion. Committed outputs declare the admitted input lineage. Failed/skipped results preserve their typed reason and evidence.

`storage/artifacts.py` separates byte identity from immutable producing-manifest identity. Identical bytes share their content address; producer, configuration, retention and ordered input lineage belong to a separate canonical manifest. Original raw-byte publication receipts are retained; each producing manifest has its own ledger receipt and availability watermark. `storage/verification.py` resolves that exact manifest, checks the manifest against stored metadata and edges, verifies every referenced blob, and recursively checks the selected production DAG. Jobs pin producing-manifest hashes, not an ambiguous raw-byte producer.

Every artifact published under a job lease is recorded in `job_productions` with its job and lease epoch (migration 0004). A job's read and input scope is its admitted input, its committed checkpoint and its own productions, so a checkpoint or result can name outputs the job published earlier over HTTP; another job's scope does not reach them. Checkpoint bodies use `contracts/jobs.py#JobCheckpoint`: version, job ID, stage, exact admitted input, configuration hash, completed content keys, continuation cursor and output references. The production must declare the checkpoint's referenced inputs and outputs. Resume rejects corrupt, absent, unpublished, tombstoned, incompatible or wrong-job/configuration checkpoints. Completed keys and cursors survive process termination; storage does not execute acquisition or model work itself.

Active duration contains acknowledged monotonic intervals from the observing storage process. UTC clocks record audit instants and lease deadlines. No elapsed work is invented by subtracting UTC clocks across process restarts. An attempt whose clock owner is lost retains its measured duration and sets `duration_complete=false`; consumers must preserve that uncertainty. A replay cannot add active time or duplicate attempts, outputs or checkpoints.

## Verification owners

| Evidence | Tests |
| --- | --- |
| Strict job payloads, unions, identifiers and checkpoint bodies | `tests/contracts/test_job_contracts.py` |
| Concurrent duplicate commands, identity conflicts, exact replay | `tests/storage/test_idempotency.py`, `tests/storage/test_jobs.py` |
| Domain/event/idempotency rollback including failure at COMMIT | `tests/storage/test_jobs.py` |
| Epoch fencing, expiry after lock wait, checkpoint corruption and selected lineage | `tests/storage/test_jobs.py` |
| Actual process termination after checkpoint COMMIT, expired lease recovery, preserved keys/cursor, single checkpoint effect | `tests/storage/test_job_process_recovery.py` |
| Distinct producing manifests and preserved byte identity/receipts | `tests/storage/test_artifact_publication.py`, `tests/storage/test_jobs.py` |
| Actual mTLS handshake, certificate role/resource scope and PostgreSQL-backed HTTP commands | `tests/storage/test_http.py` |
| Actual PostgreSQL runtime and migrator privileges, including denied TRUNCATE/schema mutation | `tests/storage/test_roles.py` |
| Content-addressed snapshot/sheet sealing, pinned-manifest immutability under a later addition | `tests/storage/test_snapshots.py`, `tests/storage/test_sheets.py` |
| Immutable run slots, ordered request/response events, sheet/snapshot admission | `tests/storage/test_runs.py` |
| Whole-or-nothing claim submission, durable rejection audit, concurrent submit | `tests/storage/test_submissions.py` |
| One immutable rating per rater and digest entry | `tests/storage/test_ratings.py` |

The integration suite uses disposable schemas on PostgreSQL 17; it fails closed without a configured test DSN. It does not mock the transaction, artifact or lease owners. The process recovery test terminates only its own subprocess. It proves storage recovery and non-duplication of committed storage effects; external request counters and actual acquisition-unit reuse require #65's worker implementation.

`storage/client.py` exposes only the implemented job claim/renew/checkpoint/complete, artifact publish/read, and run/snapshot/sheet/submission/rating routes through verified mutual TLS. It binds the server name, CA and client certificate, validates typed response envelopes and requested job/artifact identity, and preserves the original response on command replay even when the transport request ID changes. Each call makes one HTTP attempt; an ambiguous transport failure is returned as unknown outcome for the caller to resolve with the same command identity, rather than silently resending. `tests/storage/test_client.py` exercises this client against the TLS service and PostgreSQL-backed storage, including exact replay and response byte limits.

## Run, snapshot, sheet, submission and rating records

`storage/snapshots.py` and `storage/sheets.py` seal frozen, content-addressed records: a snapshot's identity is the hash of its pinned paper manifest and index identities (AG-10), a sheet's identity is the hash of its ordered questions (EN-10). Content addressing is the refusal mechanism for an altered sheet or snapshot: a caller can only reach the exact bytes it names, and re-sealing identical content is idempotent rather than a conflict. `storage/runs.py` writes one immutable run row per slot (daily sheet, shard, configuration, attempt) before any conversation turn, refusing an unsealed sheet or snapshot (AG-17); it has no update path, so a run cannot change once created. Request and response turns append to `run_events` in caller-declared, storage-verified order, one row and one `run_event` ledger record per turn (AG-29).

`storage/submissions.py` accepts a sheet-bound batch of claims from one submitter. Claim shape, sheet binding and cited evidence are validated inside the same serializable transaction that would commit the claims, so a shape, coverage or evidence failure still produces a durable `submission_rejected` ledger record with its reason (SR-11) instead of an uncommitted HTTP error; a valid batch seals one `submission_accepted` ledger record per claim and is checked whole-or-nothing. `storage/ratings.py` records one immutable rating per rater and digest entry (IN-10). All five own tables are insert-only under `storage/roles.py`; the application role never receives UPDATE, DELETE or TRUNCATE on them.

These are storage primitives only: they do not build a run specification, issue a daily sheet, evaluate SR-07's "observed by this run" evidence rule, or render a rating view. The orchestration, environment sealing and rating-app owners that call them remain open under their own issues; the parent requirement markers they contribute to (SR-11, EN-03, EN-10, AG-10, AG-17, SR-14/SR-15, IN-10) stay pending until those owners exist.

## Local service configuration

`storage-config.example.json` is a shape example, not an admitted identity. Replace its placeholder image/source/configuration hashes and certificate fingerprint with verified values. Supply the DSN and certificate/key/CA paths as external runtime files; Compose mounts the matching `/run/secrets/` paths. The DSN must select the explicitly configured schema. Install migrations with the separate migrator identity, then provision fresh role ownership and least grants through `storage/roles.py`; the service refuses an administrative or schema-mutating connection. This does not provision login credentials. Each certificate capability binds its own admitted producer version, configuration and retention hashes; these are distinct from the storage process producer. Duplicate principal mappings are refused. Artifact reads use persisted active job scope and its producing dependency graph, not a static list of visible hashes. Artifact upload uses `X-Job-Id` and `X-Lease-Epoch` and rechecks the fence inside its publication transaction; successful command replay retains its original response after expiry.

The Python image is pinned to Linux amd64, matching the launch host. The PostgreSQL image is digest pinned. The artifact directory is prepared for UID 10001 before named-volume initialization. Applied UID/mount/cgroup/network behavior still requires a real container test. Existing raw-input jobs from the partial version-one library are not silently rebound to a guessed production; they fail closed unless their original admitted producing identity can be supplied through an explicit migration decision. No existing operational database was upgraded in this work.

## Remaining parent criteria

| #72 acceptance area | Current evidence and remaining owner |
| --- | --- |
| SR-14 / EN-05 durable ledger, SR-23 producing provenance, job command atomicity | Real PostgreSQL and filesystem tests under #80. Complete source/run/domain event coverage remains with the domain owners; all parent markers stay pending. |
| SR-12/SR-13, PL-18/PL-19 container filesystem/network boundaries | #81 supplies the storage scaffold. Real Linux default-deny firewall, worker destination matrix, host/DNS/metadata denial, mounts and Docker socket refusal remain unverified. Compose membership is not authorization. |
| SR-28 mode-specific startup, PL-01 through PL-06 | #81 supplies authenticated storage service startup. Full collection admission requires actual deployment/permission/volume/isolation evidence and acquisition integration; engineering/study admission is unavailable. |
| SR-15 frozen run provenance, PL-20 tools, PL-21 private rating, PL-22 batch lane | Storage now persists the run/snapshot/sheet/submission/rating records these depend on (see below), but still requires the downstream run-stamping, tool-service, rating-app and batch-lane owners; a storage service or healthy database alone cannot satisfy these requirements. |
| EN-06 complete typed event vocabulary | Job and artifact events are implemented. Source, resolution, run, scoring, billing and operating events remain with their domain slices. |
| EN-07 preserved source/version bytes, EN-08 resolver build identity | #65/#82 source capture and #66/#70 resolver/label integration remain blocked on the completed foundation. No source qualification claimed. |
| SR-16 anchors, backup/restore and recovery interfaces | Anchor/backup/recovery interfaces remain open under #72/#74. Actual independent receiver, isolated restore, RPO/RTO and deployment qualification belong to #74 and require separate operating evidence. |

A disposable Linux VM now provides limited container execution evidence; see `linux-boundary-evidence.md`. The pinned PostgreSQL image runs and rejects the tested forbidden SQL operations. The application image build fails under amd64 emulation, so production application-container evidence remains unavailable. `bin/check-collection-linux` is a separate explicit gate; an unavailable result is not a passing test. No existing service was restarted. No paid jobs, purchases, deployment, merge, or unrelated worktree changes were performed.

The next sequence remains #82 through #65, then #66/#70, then #83 through #67, once prerequisite acceptance permits it. A 100-paper run is only an engineering smoke test; source, representation, forecasting, Jev, reader and operating qualification gates remain unchanged.
