# research-agent

A research-discovery experiment for arXiv cs.AI and cs.LG: source-linked paper cards, full-paper retrieval, three automatically labeled citation forecasts, Jev content assessments, and a private reading digest. Citation forecasts and reader usefulness are evaluated separately.

The design is complete and implementation has started with the storage foundation in #72: strict shared values, immutable artifacts, transactional ledger writes, idempotency and fenced job leases. This is a development library, not a running collection service. Authenticated service routes, container isolation, paper acquisition and model training are not yet implemented or qualified.

Artifact publication commits metadata, a typed `ArtifactRef` ledger payload and publication receipts under one ledger watermark after the blobs are durable. Job lease methods are lower-level primitives: command idempotency, ledger events for job transitions, active-duration accounting and complete dependency verification still need integration. SQL role separation, source-time evidence, backup/restore and snapshot sealing also remain open under #72; passing the foundation tests does not qualify a deployment.

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

Local storage administration uses `RESEARCH_AGENT_STORAGE_DSN`: `uv run --locked python -m research_agent migrate` installs the schema with a migrator connection, and `check-schema` verifies it. These commands do not start workers, download papers or call paid services. Runtime credentials and deployment isolation remain part of #72.

Implementation order: verify durable writes and job recovery locally; complete collection service boundaries; exercise a small acquisition pilot; then move resumable bulk downloads and embedding to the VPS. Fit and evaluate prediction heads after the corpus, automatic target labels and time-safe splits are verified. More automatically labeled papers reduce labeling effort, but downloading, extracting and embedding them still require measured time and disk capacity.

- [SDD: requirements and behavioral protocols](docs/spec/SDD.md).
- [Implementation readiness](docs/spec/TDD.md#implementation-readiness) and [TDD](docs/spec/TDD.md).
- [Accepted decisions](docs/decisions) and [amendment ledger](docs/spec/SPEC-AMENDMENTS.md).
- [Working policy](CONTRIBUTING.md) and [contributor instructions](AGENTS.md).
