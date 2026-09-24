# research-agent

A research-discovery experiment for arXiv cs.AI, cs.LG, quant-ph and q-bio, each paper compared within its primary category: source-linked paper cards, full-paper retrieval, three automatically labeled citation forecasts, and a private reading digest. A seeded population of agent configurations in three islands, cs, quant-ph and q-bio, reads the papers through one named provider's hosted model, fixed for two weekly cycles and then shaped within each island by forecast skill, with measured cost as a budget constraint rather than an objective; the cs and quant-ph islands each have a rater whose ratings act only as a selection proxy, and q-bio is the unrated control. After a rater rates a digest entry, a pinned summarizer's reading of the agents' claims appears beside the recorded fields, labeled and stored with its inputs' hashes. Jev content assessments are held out of the launch until provider access exists. Citation forecasts and reader usefulness are evaluated separately.

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

Each other role has one start command that takes `--config /absolute/path/role.json`: `serve-models` (the shared model service over mTLS, answering `GET /health`), `serve-owner` and `serve-rating` (the two web apps over HTTPS, each answering `GET /health`), `serve-ingest` (the daily day pass once per UTC day; `--once` runs a single pass) and `provision-launch-roles` (the runtime and migrator roles on the launch database's freshly migrated schema). A configuration names its role, the launch profile file and that profile's expected hash, and its secrets as files under `/run/secrets/`. A command refuses to start if the configuration was written for another role, if the profile's hash differs from the declared one, or if a declared secret is missing, empty or readable beyond its owner. The reader has no start command because it runs inside the day pass ([decision 0029](docs/decisions/0029-ingest-in-process-storage.md)).

The owner's pages are a React app in `front-end/` that talks only to `/api/v1`. It needs Node 20.19 or later. From `front-end/`: `npm ci`, then `npm run check` (typecheck, lint, tests), `npm run dev` for a local server with `VITE_API_ORIGIN` pointing at `serve-owner`, and `npm run build` for the static bundle Vercel publishes. `npm run gen:types` regenerates the API types from `docs/contracts/api-v1/`. [`docs/implementation/front-end.md`](docs/implementation/front-end.md) records its owners, deployment and known gaps.

- [The specification](docs/spec/README.md): what the SDD and TDD are, how to read them, how a change enters, and the one command that checks them.
- [SDD: requirements and behavioral protocols](docs/spec/SDD.md).
- [TDD: technical design and contracts](docs/spec/TDD.md).
- [Implementation records](docs/implementation/README.md) and [evidence](docs/evidence).
- [Accepted decisions](docs/decisions) and [amendment ledger](docs/spec/SPEC-AMENDMENTS.md).
- [Working policy](CONTRIBUTING.md) and [contributor instructions](AGENTS.md).
