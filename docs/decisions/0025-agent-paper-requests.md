# 0025: Agents may request papers beyond the snapshot

Accepted 2026-09-23 on #263.

## Context

The five tools answer only from the snapshot frozen when a batch is issued
(AG-10), and a run reaches nothing else (SR-12). The citation snapshot
holds edges into 704,034 arXiv works against the 10,000 the population
rule drew, so `graph` returns edges into papers the corpus never
acquired, and `deep_read` of one has nothing to read. The owner directed
that any paper an agent wants is fetched, read, embedded and given a card.

## Decision

- A `deep_read` or `graph` call naming a family the run's snapshot does
  not hold answers `not_in_snapshot` and records a paper request --
  family id, requesting run, snapshot hash, requested at -- deduplicated by
  family, with a receipt in the same answer. The request is a row; the run
  still reaches nothing but its snapshot and the agent model.
- The acquisition worker fulfils requests with the owners that exist: the
  documents stage fetches source and PDF, the reader extracts, passages are
  built and embedded on the host model service, the index publishes, the
  reader builds the card, and the citation graph gains the family's edges
  from the snapshot channel.
- The acquired paper is available from the next snapshot. The snapshot the
  request came from does not change.
- Requests are bounded by a per-run cap and a per-day acquisition budget
  under the arXiv pacing rule; a request past either is refused as
  `request_budget_exhausted` and recorded.
- A requested paper's provenance names the request, so a population-drawn
  paper and an agent-requested one are distinguishable.

## What stays

SR-12, AG-10 and exact replay; RD-01; the population rule (#66). Requested
papers are outside the drawn population and enter neither head training
nor the qualification sets by that route.

## What becomes impossible

Answering a `deep_read` of an absent paper with silence, and acquiring a
paper with no record of who asked for it.

## What is deliberately left open

The values of the per-run cap and the per-day budget, revisited from
measured request volume. #266 fixed them in the TDD (TDD-3.1.78) at 3
requests per run and 200 acquisitions started per UTC day, and added
EN-44.
