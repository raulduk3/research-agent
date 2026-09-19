# Software Design Description

What the software must do, stated as requirements a reader can verify.

## Document control

| Field               | Value                                                                                                                                |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Product             | research-agent: a forward-only research agent for arXiv cs.AI and cs.LG, built on a BERT encoder that keeps being fine-tuned.        |
| Target version      | The first release. No release tag exists yet.                                                                                        |
| Scope               | One deployment on one host. What it covers, at what scale, and what it leaves out are stated under Scope and scale.                  |
| Authority           | This document decides what the software does. Where code and this document disagree, one is wrong; say which, with evidence.         |
| Companion documents | [TDD.md](TDD.md) states how each requirement is met. [SPEC-AMENDMENTS.md](SPEC-AMENDMENTS.md) records each change to either.         |
| Change control      | A pull request cites an accepted decision under `docs/decisions/`, edits the exact lines, and appends a row to the amendment ledger. |

## Scope and scale

The software reads every new paper in two arXiv categories with small models, gives a population of the same agent a text card per paper, and takes from each agent dated claims about which papers will matter. Claims are sealed in a ledger before their outcomes exist and settled later by deterministic resolvers. Each agent's configuration, its genome, is scored only by that record, and the population is selected and mutated toward its best performers. The encoder keeps training on each week's papers, and the heads are refit and calibrated after it. Two raters rate what the system surfaces without seeing where it came from.

- Covers: ingest of the corpus and of outcomes, the small models and their training, the reader, the agent runs, the ledger and its resolvers, scoring against the baselines, selection and mutation, the digest and human rating, and the platform all of it runs on.
- Scale: one host that meets a stated floor, run by its owner. One corpus, arXiv cs.AI and cs.LG. One population of one agent design. Two raters. Output that is private to the raters.
- Does not cover: more than one host, a corpus beyond the two categories, output to the public, a model trained from scratch, or reading papers with an optical character recognition model.

A requirement states the smallest behavior that serves the study. A capability that would be a second way of doing something the system already does once stays out until the system without it has been measured (SR-17).

## Normative language

- "must" states a requirement.
- "must not" states a prohibition.
- No other word makes a requirement. A proposal that is not decided is a GitHub issue and does not appear here.

## Conventions

- Each requirement is one sentence on a `**XX-nn.**` line: a two-letter area code and a two-digit number.
- A trace comment follows it: `<!-- id: SDD-XX-nn | tdd: TDD-x.y.z | status: ... -->`. The `tdd` field is `none` until the TDD item exists.
- Bullets follow the trace comment: `Trigger`, `Behavior`, `Observable`, `On failure`, `Verified by`, and `Limits` where numbers apply. `Limits` also names a value that is not yet set and an open issue the requirement rests on, each by issue number.
- Status is one of `implemented`, `pending:#issue` (decided, not yet implemented) or `deviation:#issue` (the code does not yet meet it).
- A cited requirement is never renumbered. A gap in the numbering is an id reserved by an open issue.

Example, not part of the specification:

```text
**XX-01.** The service must reject a request that carries no credential.
<!-- id: SDD-XX-01 | tdd: TDD-1.1.1 | status: pending:#12 -->

- Trigger: a request arrives without a credential.
- Behavior: the service rejects it before any work is done.
- Observable: the response status is 401 and the body names the missing credential.
- On failure: the rejection is logged once with the request id.
- Verified by: a test that sends a request with no credential and checks the response.
- Limits: the rejection is returned within 100 ms.
```

## Terms

| Term                 | Meaning                                                                                                                                                             |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| agent model          | The language model an agent run calls.                                                                                                                              |
| baselines            | Popularity, base rate, and plain regression over card features.                                                                                                     |
| batch job            | Training or data preparation that runs apart from the services that answer requests.                                                                                |
| card                 | The text record the reader produces for one paper.                                                                                                                  |
| checkpoint           | A dated saved state of a small model. The encoder gets one at each weekly training and the heads one at each refit. The embedder keeps the one it was adopted with. |
| claim                | A dated statement with evidence ids, a statement a resolver can settle, a horizon and a confidence from 0 to 1.                                                     |
| cohort               | The papers from the same week.                                                                                                                                      |
| digest               | The private delivery of surfaced papers to the raters.                                                                                                              |
| embedder             | The frozen embedding model.                                                                                                                                         |
| encoder              | The trainable BERT model. The encoder body is its weights apart from the heads.                                                                                     |
| genome               | The configuration of one agent: prompt, scan policy, read policy, confidence rule, tools, budgets and sampling.                                                     |
| heads                | Logistic regressions over frozen features that output probabilities.                                                                                                |
| horizon              | The time after sealing at which a claim is settled.                                                                                                                 |
| ingest               | The only component that reaches the internet.                                                                                                                       |
| ledger               | The append-only, hash-chained record that scoring reads. Each record has a kind (EN-06).                                                                            |
| population           | The set of live genomes.                                                                                                                                            |
| question sheet       | The daily set of questions, sealed before its outcomes exist. Also "sheet".                                                                                         |
| reader               | The layer that produces cards from the small models.                                                                                                                |
| resolver             | A deterministic procedure that settles a claim as true, false or unresolvable, with evidence.                                                                       |
| run                  | One execution of an agent under one run contract.                                                                                                                   |
| run contract         | Slot, genome hash, seed, snapshot hash, budgets and the tools allowed.                                                                                              |
| sanction             | Quarantine of a run, then of a lineage, then purge.                                                                                                                 |
| scorer               | The deterministic process that scores claims and genomes.                                                                                                           |
| shared model service | The one service that serves the small models to every run.                                                                                                          |
| small models         | The encoder, the embedder and the heads.                                                                                                                            |
| snapshot             | The read-only copy of the papers, the cards and the citation graph, frozen when a sheet is issued.                                                                  |
| use track            | Outcomes that show a paper was built on. The attention track holds outcomes that show it was noticed.                                                               |
