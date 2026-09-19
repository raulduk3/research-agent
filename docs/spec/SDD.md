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

## 1. Architecture and standing rules

### 1.1 Layers

**SR-01.** The system must be layered, from outermost to innermost: infrastructure with measuring, output and observation, then environment, then agents, then reader, then models.
<!-- id: SDD-SR-01 | tdd: none | status: pending:#5 -->

- Trigger: A component is added to the system or its place in the system changes.
- Behavior: Each component is assigned to exactly one of the five layers, and the assignment is recorded. A batch job of fitting and training is recorded instead with the layers it connects.
- Observable: A stored list names every component with its layer, in the order given, and it matches the components that run.
- On failure: A component with no assignment, or with two, is not added, and the gap is recorded.
- Verified by: A check that compares the running components with the stored list and fails when a component is absent from the list or sits under two layers.

### 1.2 Trust in agent output

**SR-02.** The system must verify what an agent did and never what the agent reported.
<!-- id: SDD-SR-02 | tdd: none | status: pending:#5 -->

- Trigger: An agent run makes a tool call, submits or ends.
- Behavior: Every tool call of a run and its result are written to a run trace that is captured outside the agent's control. Each check on a run's conduct, such as its tool use (AG-14) and its budgets (AG-12), reads the trace and never the agent's own account.
- Observable: A stored trace exists for every run, and it lists the calls the run made whatever the agent's text says about them.
- On failure: A check that finds no complete trace for a run fails and records the failure. It does not fall back to the agent's report.
- Verified by: A test in which an agent states that it read a paper it never requested, and that checks that the trace shows no such read and that a check of the run's conduct reports none. It would catch a check that takes the agent's word.

**SR-03.** Every score must be computed without a language model.
<!-- id: SDD-SR-03 | tdd: none | status: pending:#5 -->

- Trigger: The scorer computes a score for a claim, a genome or a baseline.
- Behavior: The scorer computes each score from ledger records by a deterministic function (IN-01) and calls no language model at any step.
- Observable: The network reach declared for the scorer (PL-19) includes no language model, and the scorer produces every score with all language models unreachable.
- On failure: A score that cannot be computed from ledger records alone is not recorded, and the failure is recorded.
- Verified by: A test that runs the scorer with every language model unreachable and checks that all scores appear and equal those of a normal run. It would catch a scorer that asks a model to judge a claim.

**SR-04.** A language model must be limited to proposing or pre-filtering.
<!-- id: SDD-SR-04 | tdd: none | status: pending:#5 -->

- Trigger: A component receives output from a language model.
- Behavior: The output is taken only as a proposal, such as a claim or a mutation (AG-20), or as a pre-filter that narrows what a deterministic step or a person then decides. No language model output settles a claim, computes a score (SR-03), selects a genome or applies a sanction.
- Observable: The components that settle, score, select and sanction have no language model within their declared reach (PL-19).
- On failure: A step that settles, scores, selects or sanctions and cannot complete without a language model stops, and the failure is recorded. No language model output is taken in place of its result.
- Verified by: A test that runs resolution, scoring, selection and sanctions with every language model unreachable and checks that the results are unchanged. It would catch a resolver or a selection step that asks a model to decide.

**SR-05.** Every interface to the agent must treat the agent as an untrusted proposer.
<!-- id: SDD-SR-05 | tdd: none | status: pending:#5 -->

- Trigger: An agent run sends a tool call or a submission to another component.
- Behavior: The receiving component validates the message against its schema (AG-11) and the run contract (AG-17) before acting on it. The agent holds no authority: it writes no ledger record itself and changes no prompt, run contract (IN-24) or snapshot content (AG-10).
- Observable: A message that fails validation gets a refusal, and the refusal appears in the run trace (SR-02).
- On failure: The message is refused whole, nothing from it is accepted, and the refusal is recorded.
- Verified by: A test that sends a malformed tool call and a call to a tool outside the run contract, and checks that each is refused and recorded. It would catch an interface that accepts agent input as given.

**SR-06.** An agent's output must be acted on only by the scorer and a human reader.
<!-- id: SDD-SR-06 | tdd: none | status: pending:#5 -->

- Trigger: An agent run submits its output.
- Behavior: Agent output goes to the ledger, and from the ledger to the scoring path (the resolvers and the scorer) and to human readers through the digest (EN-32) and the spot check (IN-11). No other component takes agent output as input.
- Observable: The declared service interfaces (PL-02) show no consumer of agent output other than those.
- On failure: A request for agent output from any other component is refused, and the refusal is recorded.
- Verified by: A check of the declared interfaces that fails when any other component reads agent output, and a test that such a read is refused.
- Limits: Whether the step that proposes mutations is shown agent output is open (#13). Under this rule it is shown none.

### 1.3 Claims

**SR-07.** Every claim must carry evidence ids that exist in the corpus at the moment the claim is sealed.
<!-- id: SDD-SR-07 | tdd: none | status: pending:#5 -->

- Trigger: A claim is submitted for sealing.
- Behavior: The sealing step looks up each evidence id of the claim in the snapshot frozen for the sheet on which the claim is submitted (AG-10), which for a run is the snapshot named in its run contract. The claim is sealed as valid only when it carries at least one evidence id and every id is found.
- Observable: The ledger record of a sealed claim holds its evidence ids, and a claim with an id that is not found appears in the ledger as void.
- On failure: A claim with no evidence id, or with an id absent from the snapshot, is recorded as void (SR-11). If the lookup itself cannot run, nothing is sealed and the failure is recorded.
- Verified by: A test that submits a claim citing an evidence id absent from the snapshot, and one with no evidence id, and checks that each is recorded as void.
- Limits: Open issue #12, whether every surfaced paper is itself a dated claim, is not decided. This rule applies to whatever is sealed as a claim under either option.

**SR-08.** Every claim must carry a statement that a resolver can settle.
<!-- id: SDD-SR-08 | tdd: none | status: pending:#5 -->

- Trigger: A claim is submitted for sealing.
- Behavior: The statement either answers a question on the sealed sheet, whose resolver is fixed (EN-11), or is a volunteered claim of an admitted claim type (EN-30). The sealing step binds the claim to that resolver at submission.
- Observable: The ledger record of a sealed claim shows which resolver it is bound to, at the version fixed under EN-11.
- On failure: A claim whose statement matches no sheet question and no admitted claim type is recorded as void (SR-11).
- Verified by: A test that submits a claim with free text in place of a statement of an admitted type and checks that it is recorded as void. It would catch a claim sealed with a statement no resolver can read.
- Limits: Open issue #12, whether every surfaced paper is itself a dated claim, is not decided. This rule applies to whatever is sealed as a claim under either option.

**SR-09.** Every claim must carry a horizon.
<!-- id: SDD-SR-09 | tdd: none | status: pending:#5 -->

- Trigger: A claim is submitted for sealing.
- Behavior: The sealing step checks that the claim carries one horizon. The horizon fixes the time after sealing at which the resolver settles the claim.
- Observable: The ledger record of a sealed claim holds its horizon.
- On failure: A claim with no horizon is recorded as void (SR-11), and no horizon is assumed for it.
- Verified by: A test that submits a claim with no horizon and checks that it is recorded as void and that no default horizon is filled in.
- Limits: The horizon values for sheet questions are those of EN-13, and no accepted statement limits the horizon of a volunteered claim (EN-30). Open issue #12, whether every surfaced paper is itself a dated claim, is not decided, and this rule applies to whatever is sealed as a claim under either option.

**SR-10.** Every claim must carry a confidence from 0 to 1.
<!-- id: SDD-SR-10 | tdd: none | status: pending:#5 -->

- Trigger: A claim is submitted for sealing.
- Behavior: The sealing step checks that the claim carries one confidence and that the value lies in the range. The value is sealed as submitted.
- Observable: The ledger record of a sealed claim holds the confidence exactly as submitted.
- On failure: A claim with no confidence, or with a value outside the range, is recorded as void (SR-11). The value is not clipped into the range and no default is filled in.
- Verified by: A test that submits a claim with a confidence above 1, one below 0 and one with none, and checks that each is recorded as void and that none is sealed with an altered value.
- Limits: The range is 0 to 1, end values included. Open issue #12, whether every surfaced paper is itself a dated claim, is not decided, and this rule applies to whatever is sealed as a claim under either option.

**SR-11.** A claim that a resolver cannot bind must be recorded as void.
<!-- id: SDD-SR-11 | tdd: none | status: pending:#5 -->

- Trigger: The sealing step finishes its checks on a submitted claim (SR-07 to SR-10).
- Behavior: A claim is bound when it passes every check of SR-07 to SR-10, so that a resolver can read its evidence, statement and horizon at settlement. Any other claim is recorded in the ledger as void and is neither settled nor scored.
- Observable: Every such claim appears in the ledger as void, and no resolver result and no score exists for it.
- On failure: If the claim cannot be recorded as void, the submission is not accepted and the failure is recorded.
- Verified by: A test that submits one claim failing each check of SR-07 to SR-10 and checks that each is recorded as void, that none reaches a resolver, and that the other claims of the run are sealed as usual.

### 1.4 Isolation

**SR-12.** An agent run must reach only the frozen snapshot and the API of the agent model.
<!-- id: SDD-SR-12 | tdd: none | status: pending:#5 -->

- Trigger: An agent run starts.
- Behavior: The run reaches the snapshot named in its run contract (AG-10) through its tools, which also take its submission (AG-09), and calls the API of the agent model. The platform closes every other destination to it, the shared model service (PL-08) included, and all other stored data (PL-19).
- Observable: The reach declared for the run under PL-19 lists those two destinations only, and an attempt from inside the run to reach anything else fails.
- On failure: A run whose isolation cannot be put in place does not start, and the failure is recorded.
- Verified by: A test that, from inside a run, tries to reach an internet address other than the API of the agent model, to call the shared model service and to read stored data outside the snapshot, and checks that every attempt fails.

**SR-13.** A component other than ingest must not reach the internet, except for an agent run's call to the API of the agent model.
<!-- id: SDD-SR-13 | tdd: none | status: pending:#5 -->

- Trigger: Any container starts.
- Behavior: The platform gives internet reach to ingest, and gives each agent run one route to the API of the agent model (SR-12). Every other container has no route to the internet, and the platform enforces this from outside the component (PL-19).
- Observable: The reach declared under PL-19 shows internet access for ingest and the one route for agent runs, and an outbound attempt from any other container fails.
- On failure: A container whose reach cannot be set as declared does not start, and the failure is recorded.
- Verified by: A test that attempts an outbound connection from every container other than ingest and checks that each attempt fails, apart from an agent run's call to the API of the agent model.
- Limits: Three outbound paths are not yet set (#6): where the head of the hash chain is anchored (SR-16), the delivery path of the digest (EN-32) and the channel that carries anomaly flags (IN-21). This rule applies to each when it is set. What proposes mutations is open (#13), and a call from that step to a language model is a further outbound path under this rule.

### 1.5 Ledger and run records

**SR-14.** The ledger must be append-only.
<!-- id: SDD-SR-14 | tdd: none | status: pending:#5 -->

- Trigger: Any component writes to the ledger.
- Behavior: The ledger accepts a new record at its end and refuses every request to change or remove a record already written.
- Observable: A request to rewrite or delete a record gets a refusal, and the records already written and the hash chain over them (EN-05, EN-06) are unchanged.
- On failure: An append that cannot complete leaves no partial record, and the step that asked for it stops and records the failure.
- Verified by: A test that attempts to overwrite and to delete an existing record through the ledger's interface and checks that both are refused and that the chain still verifies (EN-05).

**SR-15.** Every run must be stamped with its genome hash, its seed, the id of the agent model and the checkpoint dates of the small models.
<!-- id: SDD-SR-15 | tdd: none | status: pending:#5 -->

- Trigger: An agent run starts.
- Behavior: One stamp is written to the ledger for the run, once, before the run's first call to the agent model. It holds the genome hash and the seed from the run contract (AG-17), the id of the agent model the run calls, and the checkpoint dates of the encoder, the embedder and the heads being served when the run starts (PL-13). PL-06 adds the versions of the service images to the stamp.
- Observable: The ledger holds exactly one stamp for every run, written as a ledger record (EN-06), and it sits earlier in the ledger than any claim of that run.
- On failure: A run whose stamp cannot be written, or whose stamp lacks a value, does not start, and the failure is recorded.
- Verified by: A test that starts a run, promotes a new checkpoint while it runs, and checks that the stamp shows the dates served at the start. A second test withholds one value and checks that the run does not start.
- Limits: Open issue #14, the name of the agent's language model, is not decided, and the stamp records the id of whichever agent model the run calls under either option. The embedder is never trained (FT-06) and keeps the checkpoint date it was adopted with.

**SR-16.** The head of the ledger's hash chain must be anchored in a place outside the system.
<!-- id: SDD-SR-16 | tdd: none | status: pending:#5 -->

- Trigger: Anchoring comes due on its schedule.
- Behavior: The current head hash of the ledger's chain (EN-05), with its sequence number (EN-06), is written to a place that no process of the system can alter.
- Observable: The anchored value can be read from outside the system and compared with the ledger record at the same sequence number.
- On failure: A failed anchoring is recorded, and the previous anchor stays in place.
- Verified by: A test that alters a record in a copy of the ledger, recomputes the chain, and checks that comparing the copy with the anchored head shows the change. It would catch an anchor the system could rewrite along with the chain.
- Limits: Where the head of the hash chain is anchored, and how often, is not yet set (#6). SR-13 applies to the path of the anchoring write when it is set.

### 1.6 Procedure for change

**SR-17.** A layer must be added only after the configuration without it has been measured on the same score.
<!-- id: SDD-SR-17 | tdd: none | status: pending:#5 -->

- Trigger: A layer, meaning any part added to the running configuration to improve a score, is proposed for addition.
- Behavior: The configuration without the layer is first measured on the primary measure of the comparison (IN-17), and the result is written to the ledger as a dated record. The layer is switched on only after that record exists, and it is then measured on the same score.
- Observable: The measurement without the layer sits earlier in the ledger than the stamp (SR-15) of the first run that includes the layer.
- On failure: Without the earlier measurement the addition is refused, the configuration stays as it was, and the refusal is recorded.
- Verified by: A test that tries to switch on a layer with no earlier measurement, and again with a measurement on a different score, and checks that both attempts are refused.
- Limits: Open issue #13, what the mutation prompt carries, is a case of this rule and is not decided. The rule holds under each of its options, since each is compared with the configuration without it.

**SR-18.** Pass and kill thresholds must be written down before a comparison runs.
<!-- id: SDD-SR-18 | tdd: none | status: pending:#5 -->

- Trigger: A comparison between configurations is about to start.
- Behavior: The pass threshold and the kill threshold of the comparison, on its primary measure (IN-17), are written to the ledger as one dated record before the first run of the comparison. The record is never changed afterwards (SR-14).
- Observable: The threshold record sits earlier in the ledger than the stamp (SR-15) of the first run of the comparison.
- On failure: A comparison with no threshold record is refused and none of its runs start. No result is reported as a pass or a kill without the record.
- Verified by: A test that starts a comparison with no threshold record and checks that it is refused, and a check that fails when a threshold record sits later in the ledger than any run of its comparison.
- Limits: No threshold value is given here, since each comparison states its own. Open issue #13, what the mutation prompt carries, is settled by such a comparison and is not decided.

**SR-19.** Superseded choices must be marked as superseded and kept, not deleted.
<!-- id: SDD-SR-19 | tdd: none | status: pending:#5 -->

- Trigger: A choice recorded in this specification, in a configuration or in a stored record is replaced by a new one.
- Behavior: The earlier choice stays where it was and is marked as superseded. Nothing is removed, and in the ledger the same holds through SR-14.
- Observable: The earlier choice can still be read, with its mark, after the new choice is in place.
- On failure: A change that removes an earlier choice instead of marking it is not accepted, and the earlier choice stays in place.
- Verified by: A check that compares a changed document or configuration with its previous version and fails when a choice present before is absent after, or is changed in place with no superseded mark.

**SR-20.** Every borrowed component and every cited result must carry a verification date.
<!-- id: SDD-SR-20 | tdd: none | status: pending:#5 -->

- Trigger: A borrowed component or a cited result is named in this specification or in a stored record.
- Behavior: The record of a borrowed component, and the entry that names a cited result, each carry a verification date, the date on which the component or the result was last checked against its source.
- Observable: Every borrowed component and cited result that is named shows a verification date beside it.
- On failure: An item with no verification date is recorded as unverified, and no requirement states it as fact until a date is recorded.
- Verified by: A check that lists every borrowed component and cited result named in this specification and fails on any entry that has no verification date and is not recorded as unverified.

### 1.7 Blind rating

**SR-21.** Human rating must hide from a rater which genome surfaced a paper.
<!-- id: SDD-SR-21 | tdd: none | status: pending:#5 -->

- Trigger: A digest (EN-32) and its rating view are prepared for a rater.
- Behavior: What a rater receives carries no genome hash, lineage, slot or run for any paper, and papers are not grouped or ordered by genome. The link from paper to genome stays recorded, out of the rater's view.
- Observable: A delivered digest and its rating view contain no genome identifier, and ratings are joined to genomes afterwards from the recorded link.
- On failure: A rating view that cannot be produced without the genome is not delivered, and the failure is recorded.
- Verified by: A test that builds a digest from papers surfaced by known genomes and checks that nothing the rater receives, in a field or in the order of papers, identifies the genome of any paper.

**SR-22.** Human rating must hide from a rater which papers are random controls.
<!-- id: SDD-SR-22 | tdd: none | status: pending:#5 -->

- Trigger: A digest that includes random papers (EN-33) and its rating view are prepared for a rater.
- Behavior: A random control appears in the same form as a surfaced paper, with no field, label or fixed position that sets it apart. The record of which papers are controls is kept out of the rater's view.
- Observable: In a delivered digest a control and a surfaced paper show the same fields, and the record of which papers were controls exists outside the digest.
- On failure: A digest in which controls cannot be shown in the same form is not delivered, and the failure is recorded.
- Verified by: A test that builds a digest with known controls and checks that no field and no fixed position in what the rater receives separates controls from surfaced papers.
