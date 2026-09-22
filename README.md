# research-agent

A research-discovery experiment for arXiv cs.AI and cs.LG: source-linked paper cards, full-paper retrieval, three automatically labeled citation forecasts, Jev content assessments, and a private reading digest. Citation forecasts and reader usefulness are evaluated separately.

What has been built so far, and what it was verified against, is recorded in [implementation records](docs/implementation/README.md). The implementation order and evidence gates are tracked in [#100](https://github.com/raulduk3/research-agent/issues/100).

Install uv 0.8.22 and Python 3.12.12, then install the locked environment:

```sh
uv sync --locked
```

Build distributable artifacts with `uv build --no-build-isolation` after syncing; the build backend and its dependencies are included in the lock. `uv run --locked python -m research_agent --version` reads the product version from a tagged Git checkout. Python package metadata uses the Git-derived PEP 440 representation required by Python packaging; it is not the product's display version.

Run the full checks against a disposable PostgreSQL 17 database. The test role must be able to create schemas; tests create and remove only their own uniquely named schemas. Do not use a production database. Set `RESEARCH_AGENT_TEST_DSN` through your environment, then run:

```sh
bin/check --since develop
```

Database checks fail if the DSN is missing. `uv run --locked pytest -m 'not integration'` runs the unit tests alone; this does not qualify storage. Document-only checks remain available with `bin/spec-check --strict --since develop` and `bin/spec-check --self-test`. `bin/progress` prints a progress map derived from the specification tree: each TDD item is scored by whether its named code path, symbol and tests exist and whether its status is `implemented`, rolled up by SDD section; `bin/progress --issues` adds the milestone's issue tree from GitHub.

Local storage administration uses `RESEARCH_AGENT_STORAGE_DSN`: `uv run --locked python -m research_agent migrate` installs the schema with a migrator connection, and `check-schema` verifies it. These commands do not start workers, download papers or call paid services. `serve-storage --storage-config /absolute/path/storage.json` is the low-level mTLS storage launcher; it requires external DSN and TLS files and never provisions credentials or starts paid workers. `collection-readiness --storage-config /absolute/path/storage.json` refuses admission while host isolation is unverified. The pinned Compose file is a deployment scaffold, not proof of its container boundaries. `bin/check-collection-linux --worker-boundary` starts that stack on a disposable Linux engine and observes what a worker container reaches; the gate without that flag still reports unavailable, because host-network enforcement is unproven. [`docs/implementation/lima-collection-boundary.yaml`](docs/implementation/lima-collection-boundary.yaml) defines the Linux VM used for it and [`docs/implementation/linux-boundary-evidence.md`](docs/implementation/linux-boundary-evidence.md) records what was observed. Do not use the migrator identity for the storage service.

- [SDD: requirements and behavioral protocols](docs/spec/SDD.md).
- [TDD: technical design and contracts](docs/spec/TDD.md).
- [Implementation records](docs/implementation/README.md) and [evidence](docs/evidence).
- [Accepted decisions](docs/decisions) and [amendment ledger](docs/spec/SPEC-AMENDMENTS.md).
- [Working policy](CONTRIBUTING.md) and [contributor instructions](AGENTS.md).
