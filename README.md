# research-agent

A research-discovery experiment for arXiv cs.AI and cs.LG: source-linked paper cards, full-paper retrieval, three automatically labeled citation forecasts, Jev content assessments, and a private reading digest. Citation forecasts and reader usefulness are evaluated separately.

This repository currently contains the design and its validation tools. The application is not implemented. Launch behavior is fixed in the SDD and its protocols; full-system technical design and empirical qualification follow.

Run document checks with Python 3:

```sh
bin/check --since develop
```

Application runtime is Python 3.12.12; its dependency lock and service images will be tested during implementation. No models or paid services are needed for document checks.

- [SDD](docs/spec/SDD.md), [launch profile](docs/spec/LAUNCH-PROFILE.md), [learning protocol](docs/spec/LEARNING-PROTOCOL.md), [retrieval protocol](docs/spec/RETRIEVAL-PROTOCOL.md).
- [Implementation readiness](docs/IMPLEMENTATION-READINESS.md) and [TDD](docs/spec/TDD.md).
- [Accepted decisions](docs/decisions/) and [amendment ledger](docs/spec/SPEC-AMENDMENTS.md).
- [Working policy](CONTRIBUTING.md) and [contributor instructions](AGENTS.md).
