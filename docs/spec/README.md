# The specification

Two documents state the capped swarm release.

- [SDD.md](SDD.md) states what the software must do: cloud ingestion, islands, genomes, one-paper agent runs, durable run traces, cost receipts, rapid evolution, feedback and the five visible pages.
- [TDD.md](TDD.md) states how each requirement is met.
- [SPEC-AMENDMENTS.md](SPEC-AMENDMENTS.md) records each change to either document.

The first release excludes the earlier broad forecasting and qualification system. Historical citation forecasting, prediction heads, Jev assessment, OCR, public publishing, model training and distributed clusters are not part of the active contract. Chat is an exploratory surface, not the durable record; stored paper, island, genome, run, feedback, evolution and cost records are the durable record.

A change enters by updating the exact SDD and TDD lines it affects, adding or updating a decision record under [`../decisions/`](../decisions/), and appending a row to the amendment ledger.

Run the document checks with:

```bash
bin/spec-check --strict
```

Run the full repository gate with:

```bash
bin/check --since develop
```
