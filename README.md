# research-agent

A research-discovery experiment for arXiv cs.AI and cs.LG: source-linked paper cards, full-paper retrieval, three automatically labeled citation forecasts, Jev content assessments, and a private reading digest. Citation forecasts and reader usefulness are evaluated separately.

Implementation is in progress under #72. The storage foundation includes strict shared records, PostgreSQL command idempotency, typed ledger events, immutable producing manifests, fenced jobs, verified checkpoint recovery, mTLS service routes and separate SQL roles. [Storage evidence and remaining criteria](docs/implementation/storage-foundation.md) distinguish tested behavior from the open collection and operating gates.

Jobs pin a producing-manifest hash so identical raw bytes can retain distinct producer/configuration/input histories. Mutations, ledger events and exact replay responses commit in one transaction. Monotonic active-duration evidence survives retries; an interval lost across a storage-process restart is explicitly incomplete. Real PostgreSQL tests include concurrency, COMMIT-time rollback and recovery after terminating a checkpoint-writing subprocess.

Install uv 0.8.22 and Python 3.12.12, then install the locked environment:

```sh
uv sync --locked
```

Build distributable artifacts with `uv build --no-build-isolation` after syncing; the build backend and its dependencies are included in the lock. `uv run --locked python -m research_agent --version` reads the product version from a tagged Git checkout. Python package metadata uses the Git-derived PEP 440 representation required by Python packaging; it is not the product's display version.

Run the full checks against a disposable PostgreSQL 17 database. The test role must be able to create schemas; tests create and remove only their own uniquely named schemas. Do not use a production database. Set `RESEARCH_AGENT_TEST_DSN` through your environment, then run:

```sh
bin/check --since develop
```

Database checks fail if the DSN is missing. `uv run --locked pytest -m 'not integration'` runs the unit tests alone; this does not qualify storage. Document-only checks remain available with `bin/spec-check --strict --since develop` and `bin/spec-check --self-test`.

Local storage administration uses `RESEARCH_AGENT_STORAGE_DSN`: `uv run --locked python -m research_agent migrate` installs the schema with a migrator connection, and `check-schema` verifies it. These commands do not start workers, download papers or call paid services. Runtime credentials and deployment isolation remain part of #72. `serve-storage --storage-config /absolute/path/storage.json` is the low-level mTLS storage launcher; it requires external DSN and TLS files and never provisions credentials or starts paid workers. `collection-readiness --storage-config /absolute/path/storage.json` refuses admission while host isolation is unverified. The pinned Compose file is a deployment scaffold, not proof of its container boundaries; `bin/check-collection-linux` reports unavailable until real Linux acceptance probes exist. Do not use the migrator identity for the storage service.

Implementation order: verify durable writes and job recovery locally; complete collection service boundaries; exercise a small acquisition pilot; then move resumable bulk downloads and embedding to the VPS. Fit and evaluate prediction heads after the corpus, automatic target labels and time-safe splits are verified. More automatically labeled papers reduce labeling effort, but downloading, extracting and embedding them still require measured time and disk capacity.

- [SDD: requirements and behavioral protocols](docs/spec/SDD.md).
- [Implementation readiness](docs/spec/TDD.md#implementation-readiness) and [TDD](docs/spec/TDD.md).
- [Accepted decisions](docs/decisions) and [amendment ledger](docs/spec/SPEC-AMENDMENTS.md).
- [Working policy](CONTRIBUTING.md) and [contributor instructions](AGENTS.md).
