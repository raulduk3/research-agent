# research-agent

A capped research-discovery assistant for watching a live swarm read a storm of papers.

The first release does seven things:

1. ingest current paper metadata and available text on one cloud server,
2. maintain research islands with their own queues and pages,
3. run one-agent-one-paper readings from explicit genomes,
4. preserve every run trace, tool call, reading and cost receipt,
5. evolve genomes quickly from feedback and run results,
6. show paper cascades from metadata down to atomic agent evidence, and
7. provide casual island-scoped chat over the stored swarm data.

The visible app is intentionally small: login, island, paper, run and chat pages. Chat sessions are for exploration and do not become the durable system of record. The durable records are paper records, island state, genomes, agent runs, readings, feedback, evolution lineage and costs.

The active specification deliberately excludes the earlier large system: two separate front ends, rating-only workflows, historical citation forecasting as the spine, prediction-head qualification, Jev assessment, OCR, public publishing, model training and distributed clusters. Existing code is reusable only when it directly serves the capped swarm contract. Old data can stay on disk, but the application ignores it unless it is explicitly imported into the current store.

Install uv 0.8.22 and Python 3.12.12, then install the locked environment:

```sh
uv sync --locked
```

Run the repository checks with:

```sh
bin/check --since develop
```

The first implementation target is the single-server path: current ingestion, paper records, islands, genomes, one-paper runs, cost receipts, rapid evolution, feedback and the five-page UI.

## The swarm beta backend

`src/research_agent/beta/` is that single-server path as one FastAPI process over one SQLite file: arXiv ingestion, islands, editable agents, one-paper runs with a replayable event trace, feedback, cost receipts, a 50 USD monthly budget with degradation modes, simple evolution and chat over the stored data. Run it locally with:

```sh
RESEARCH_AGENT_ISLAND_PASSWORDS=cs:local-cs \
  uv run --locked python -m research_agent.beta serve --port 8000
```

[`deploy/beta/README.md`](deploy/beta/README.md) holds the VPS deploy steps, the environment variables, the budget and evolution rules and the API reference. Its tests are `tests/beta/`.

- [The specification](docs/spec/README.md)
- [SDD: requirements](docs/spec/SDD.md)
- [TDD: technical design](docs/spec/TDD.md)
- [Accepted decisions](docs/decisions)
- [Working policy](CONTRIBUTING.md) and [contributor instructions](AGENTS.md)
