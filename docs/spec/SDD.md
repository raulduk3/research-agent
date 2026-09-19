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

## 2. Infrastructure: platform and deployment

### 2.1 Containers and services

**PL-01.** Each software component must run in its own container.
<!-- id: SDD-PL-01 | tdd: none | status: pending:#5 -->

- Trigger: A component is started, as a service or as a batch job.
- Behavior: The component runs in a container that holds that component and its package set and nothing else. No two components share a container or a package set.
- Observable: The platform's list of containers on the host shows every running component in a container of its own.
- On failure: A component that cannot start in its own container does not start, and the failed start is recorded. It is not started inside another component's container or directly on the host.
- Verified by: A check that reads the system definition (PL-03) and the running containers and fails when one container holds two components, when two components share a package set, or when a component runs on the host outside a container.

**PL-02.** Components must interact only through declared service interfaces.
<!-- id: SDD-PL-02 | tdd: none | status: pending:#5 -->

- Trigger: One component needs data or work from another.
- Behavior: Each component that serves others declares its interface. A component reaches another only through a declared interface and reads none of the other's files or memory.
- Observable: A call to a declared interface gets a response. An attempt to reach a component any other way is refused.
- On failure: A request that matches no declared interface is refused, and the refusal is recorded. The calling step stops and takes no other route to the data.
- Verified by: A test that, from inside one container, tries to open another component's files and to call an address the other component does not declare, and checks that both attempts are refused.

**PL-03.** The whole system must start from one declarative definition of its containers, networks and volumes.
<!-- id: SDD-PL-03 | tdd: none | status: pending:#5 -->

- Trigger: The owner starts the system on a host that has passed the floor check (PL-10).
- Behavior: One definition names every container, network and volume of the system, and one start action applied to it brings the whole system up. Nothing is created or configured by hand outside the definition.
- Observable: After the start, every service, network and volume the definition names is present on the host, and nothing is present that it does not name.
- On failure: If any part of the definition cannot be brought up, the start stops and the failure is recorded. The daily cycle does not begin on a partly started system.
- Verified by: A test that starts the system from the definition on a clean host and fails when a container, network or volume exists that the definition does not name, or when a named service, network or volume is absent.
- Limits: Where the system is built and run is open (#8). The requirement holds under each option, and the values in the definition that depend on the host are not settled.

**PL-04.** Every container must run under declared processor, memory and accelerator limits.
<!-- id: SDD-PL-04 | tdd: none | status: pending:#5 -->

- Trigger: A container is started.
- Behavior: The definition (PL-03) states a processor limit, a memory limit and an accelerator limit for every container, and the platform applies them at start. A container that uses no accelerator is declared with none.
- Observable: For each running container, the limits the platform reports equal the limits in the definition.
- On failure: A container whose definition lacks any of the three limits is not started, and the refusal is recorded.
- Verified by: A test that runs a batch job that tries to take more processor and memory than its limits, and checks that the platform holds it to them while a service beside it keeps answering. A second check fails when any container in the definition lacks a limit.
- Limits: The limits for each container are not yet set (#6). Whether weekly training runs on the target hardware is unverified (#18), so the accelerator limit is stated without naming hardware.

**PL-05.** Every service must expose a health check.
<!-- id: SDD-PL-05 | tdd: none | status: pending:#5 -->

- Trigger: The platform asks a service for its health, at start and while the service runs.
- Behavior: Every service answers a health check that says whether it is ready to answer requests. The platform uses the answer to tell a service that is still starting from one that has failed.
- Observable: The platform's recorded state for each service: waiting, healthy or failed.
- On failure: A service whose health check gives a failing answer, or no answer after it was healthy, is recorded as failed. It is not recorded as waiting.
- Verified by: A test that stops the work inside a service without stopping its container and checks that the platform records the service as failed. A second test holds a service in startup and checks that it is recorded as waiting and not as failed.

**PL-06.** Every service image must be built from pinned inputs and carry a version that is recorded with each run.
<!-- id: SDD-PL-06 | tdd: none | status: pending:#5 -->

- Trigger: A service image is built. Later, an agent run starts.
- Behavior: The build names every input by an exact version or a content hash, and the built image carries a version. The stamp of each run (SR-15) also records the version of every service image running when the run starts.
- Observable: The version each running service image carries, and the same versions in the stamp of each run.
- On failure: A build with an input that is not pinned stops and produces no image. A run whose service image versions cannot be read does not start, and the refusal is recorded.
- Verified by: A check that reads the build inputs of every service image and fails on one named without an exact version or hash. A test that starts a run and fails when its stamp lacks the version of a running service image or names a version other than the one running.

**PL-07.** Credentials must reach a container only at run time and never be built into an image.
<!-- id: SDD-PL-07 | tdd: none | status: pending:#5 -->

- Trigger: An image is built, or a container that uses a credential is started.
- Behavior: The platform hands a credential to the container that uses it when that container starts. Images, build inputs and the definition (PL-03) hold no credential value, and the definition names a credential by reference only.
- Observable: An inspection of any image, its build inputs and the definition finds no credential value.
- On failure: A container whose credential is absent at start does not start, and the failure is recorded without the credential value. An image found to hold a credential value is not run.
- Verified by: A check that searches every built image, its build inputs and the definition for the values of the credentials in use and fails on any match.

### 2.2 Shared model service and compute

**PL-08.** The small models must be served by one shared service used by every agent run.
<!-- id: SDD-PL-08 | tdd: none | status: pending:#5 -->

- Trigger: The reader, or a tool that answers an agent run, needs an output of the encoder, the embedder or the heads.
- Behavior: One shared model service on the host holds the only copy of the small models loaded for serving and answers every such request. Every model output an agent run receives, on a card or in a tool's answer, came from that one service, and no run calls the service itself (SR-12).
- Observable: The platform's list of containers shows exactly one shared model service. Every number on a card that a small model produced carries the model id and checkpoint date (RD-02, RD-03) the service had loaded when it produced the number.
- On failure: When the shared model service is not healthy (PL-05), a request to it fails and the failure is recorded. No other component loads the small models in its place.
- Verified by: A test that starts several agent runs at once and fails when a second copy of the small models is loaded for serving on the host, when a model output a run received on a card or from a tool did not come from the shared model service, or when a call to the service from inside a run gets an answer.

**PL-09.** An agent run must not load model weights of its own.
<!-- id: SDD-PL-09 | tdd: none | status: pending:#5 -->

- Trigger: An agent run starts.
- Behavior: Every output of the small models that the run receives comes from the shared model service through cards and tools (PL-08), and the run reaches the agent model over its API (SR-12). Its container holds no model weights: none in its image and none on a volume attached to it.
- Observable: An inspection of the agent run image and of the volumes the definition (PL-03) attaches to it finds no model weights.
- On failure: An agent run image found to hold model weights is not run. An attempt from inside a run to read the volumes that hold checkpoints or heads, or to fetch weights over the network (PL-19), is refused by the platform and recorded.
- Verified by: A test that, from inside an agent run container, tries to open the volumes that hold checkpoints and heads and to fetch weights from an internet address, and checks that each attempt is refused. A check fails when the agent run image holds model weights.

**PL-10.** The host must meet a stated minimum of compute, memory, accelerator and storage before the system starts.
<!-- id: SDD-PL-10 | tdd: none | status: pending:#5 -->

- Trigger: The owner starts the system (PL-03).
- Behavior: Before any service or batch job starts, a floor check measures the host's processor, memory, accelerator and free storage and compares each with the stated minimum. The system starts only when all four meet it.
- Observable: A stored floor check record, written before any service starts, that lists the four measured values, the four minimums and pass or fail.
- On failure: When a value is below its minimum or cannot be measured, no service or batch job starts. The failed check is recorded with the value that fell short.
- Verified by: A test that sets a minimum above what the host has, starts the system, and checks that no service starts and that the record names the shortfall.
- Limits: The host floor numbers are not yet set (#6). They are sized by the shared model service under the full population and depend on where the system runs (#8), on the compute for weekly training (#9), on the count of parallel agent runs (#10) and on whether training runs on the target hardware, which is unverified (#18).

### 2.3 Batch jobs

**PL-11.** Training and data preparation must run as batch jobs apart from the services that answer requests.
<!-- id: SDD-PL-11 | tdd: none | status: pending:#5 -->

- Trigger: A training or data preparation step comes due: weekly encoder training, re-encoding or head fitting (FT-16), or any one-time build of a historical outcome set for the heads.
- Behavior: Each such step runs as a batch job in a container of its own (PL-01) that starts for the job and ends with it. No service that answers requests does training or data preparation inside its own container.
- Observable: While a batch job runs, the platform's list of containers shows it apart from every service, and the job has a batch job record (PL-16).
- On failure: A batch job that fails ends with the failure in its record (PL-16), and its output is not promoted (PL-14). The services keep answering requests.
- Verified by: A test that starts each kind of batch job and fails when the work runs inside a service's container and not in a job container of its own.
- Limits: Whether the heads start pre-fit, and so whether a historical outcome set is built at all, is open (#7). The compute for weekly training is open (#9), and the requirement holds under each option.

**PL-12.** The daily cycle must continue while a batch job runs.
<!-- id: SDD-PL-12 | tdd: none | status: pending:#5 -->

- Trigger: A step of the daily cycle comes due while a batch job is running: ingest, issuing the sheet, agent runs or resolution.
- Behavior: The step starts when it is due and completes without waiting for the batch job. Daily steps use the last accepted checkpoint and heads (PL-13), so none of them depends on the running job (PL-17).
- Observable: The day's sheet, run and resolution records in the ledger carry timestamps that fall between the recorded start and end of the batch job (PL-16).
- On failure: A daily step that cannot complete while a batch job runs is recorded as failed for that day. It is not held back until the batch job ends.
- Verified by: A test that starts a long batch job, runs a full daily cycle beside it, and fails when any daily step waits for the job to end or does not complete.
- Limits: The compute for weekly training is open (#9). The requirement holds whether training shares the accelerator of the shared model service or uses another.

**PL-13.** The shared model service must keep serving the last accepted checkpoint and heads until new ones are promoted.
<!-- id: SDD-PL-13 | tdd: none | status: pending:#5 -->

- Trigger: A batch job that produces a new checkpoint or new heads is running, has failed, or has finished and is not yet promoted.
- Behavior: The shared model service keeps answering from the last accepted checkpoint and the heads fit to it. Nothing a batch job writes changes what the service serves before promotion (PL-14).
- Observable: The model id and checkpoint date the service reports, and the stamps on the numbers it produces for cards in that period (RD-02, RD-03), stay those of the last accepted checkpoint and heads.
- On failure: If the service cannot serve the last accepted checkpoint and heads, its health check fails (PL-05) and requests to it fail. It does not fall back to a checkpoint or heads that were not promoted.
- Verified by: A test that requests model outputs throughout a training job and after a failed one, and fails when a response before promotion carries a checkpoint date other than the last accepted one.

**PL-14.** A new checkpoint or set of heads must be promoted in one step, only after its job has finished and passed its checks.
<!-- id: SDD-PL-14 | tdd: none | status: pending:#5 -->

- Trigger: A batch job that produced a new checkpoint or a new set of heads has finished (PL-16) and its output has passed its checks. For a checkpoint, the checks are that it carries its date and data end date (FT-03, FT-04) and that heads were refit on it (FT-10) and calibrated (FT-11). For heads promoted alone, the checks are that they are fit to the checkpoint being served and calibrated (FT-11).
- Behavior: Promotion switches the shared model service from the last accepted checkpoint and heads to the new ones in one step, and no request is answered from a mix of old and new. A checkpoint and its heads are promoted together or not at all (FT-10).
- Observable: From one request to the next, the service reports the new checkpoint date and heads. The promotion is recorded.
- On failure: Output of a job that did not finish or did not pass a check is not promoted, and the refusal is recorded. A promotion that fails part way leaves the service on the last accepted checkpoint and heads (PL-13).
- Verified by: A test that offers for promotion the output of an unfinished job, a checkpoint whose heads are not calibrated and a checkpoint paired with heads fit to another checkpoint, and checks that each is refused. A second test sends requests across a promotion and fails when a response mixes old and new.

**PL-15.** A batch job must resume from its last saved state after an interruption.
<!-- id: SDD-PL-15 | tdd: none | status: pending:#5 -->

- Trigger: A batch job that was interrupted is started again.
- Behavior: While it runs, a batch job saves its state to a volume (PL-18). Started again, it continues from the last saved state and does not begin again from the start.
- Observable: The job's record (PL-16) shows the interruption and the resume, and the work done before the last saved state is not repeated.
- On failure: If the last saved state cannot be read, the job is recorded as failed and nothing from it is promoted (PL-14). It does not continue from a damaged or partial state.
- Verified by: A test that stops a batch job part way, starts it again, and fails when the job begins again from the start or repeats work done before its last saved state.

**PL-16.** Every batch job must record its state, its start and end times and its duration.
<!-- id: SDD-PL-16 | tdd: none | status: pending:#5 -->

- Trigger: A batch job starts, changes state or ends.
- Behavior: Each batch job has a record that holds its state (running, interrupted, finished or failed), its start time, its end time and its duration. The record is written at the start and updated at each change of state and at the end, whether the job finished or failed.
- Observable: The stored record of each batch job, kept on a volume (PL-18) and readable by the owner while the job runs and after it ends.
- On failure: A job that cannot write its record does not start. A job whose record does not show finished is not treated as finished (PL-14, PL-17).
- Verified by: A test that runs one batch job to the end and stops another part way, and checks that the first record shows finished with a start time, an end time and a duration, and that the second never shows finished.

**PL-17.** A step that depends on a batch job must wait for that job to finish and never read its partial output.
<!-- id: SDD-PL-17 | tdd: none | status: pending:#5 -->

- Trigger: A step whose input is the output of a batch job comes due, in the weekly cycle (FT-16) or after any one-time data build.
- Behavior: The step starts only after the job's record (PL-16) shows finished, and reads the job's output only then.
- Observable: The step's start time is later than the end time in the job's record. A dependent step started earlier is refused.
- On failure: If the job fails or is interrupted, the dependent step does not start, and that is recorded. It starts after the job has been resumed (PL-15) and has finished.
- Verified by: A test that starts a dependent step while its job is still running, and again after the job has failed, and checks that the step is refused both times and reads nothing the job wrote.
- Limits: Whether the heads start pre-fit on historical outcomes is open (#7). If they do, the first fit of the heads is a step that depends on the build of the historical outcome set.

### 2.4 Storage and network

**PL-18.** Data that needs to outlive a container must be kept on volumes outside every container's own file system.
<!-- id: SDD-PL-18 | tdd: none | status: pending:#5 -->

- Trigger: A component writes data that is still needed after its container is replaced: the ledger, the corpus, raw responses, checkpoints, heads, snapshots, and the records and saved states of batch jobs (PL-15, PL-16).
- Behavior: Such data is written to volumes that the definition (PL-03) names. A container's own file system holds nothing that is needed after the container is removed.
- Observable: After a container is removed and created again from its image, the data on its volumes is present and unchanged.
- On failure: A component whose volume is absent or cannot be written does not start, and the failure is recorded. It does not fall back to writing inside its container.
- Verified by: A test that removes and recreates every container and checks that the ledger's hash chain still verifies (EN-05) and that the corpus, raw responses, checkpoints, heads and snapshots are unchanged.
- Limits: Where the system is built and run is open (#8), so where the volumes are stored is not settled. The requirement holds under each option.

**PL-19.** Network reach must be enforced for each container by the platform and not by the component inside it.
<!-- id: SDD-PL-19 | tdd: none | status: pending:#5 -->

- Trigger: A container is started, or a process inside a container opens a connection.
- Behavior: The definition (PL-03) states for each container which other containers and which outside addresses it reaches, and the platform blocks everything else. The isolation rules for agent runs and for ingest (SR-12, SR-13) are applied this way.
- Observable: A connection attempt outside a container's declared reach is refused by the platform, whatever the code inside the container does.
- On failure: A container whose reach rules cannot be applied does not start, and the failure is recorded. It does not start with open network reach.
- Verified by: A test that runs code inside an agent run container and inside a service container other than ingest, tries to reach an internet address and an undeclared container from each, and checks that the platform refuses every attempt.
- Limits: Where the system is built and run is open (#8), and the means of enforcement depends on the host. The requirement holds under each option.

## 3. Infrastructure: measuring, output and observation

### 3.1 Scoring

**IN-01.** Scoring must be deterministic, so that the same ledger records always give the same score.
<!-- id: SDD-IN-01 | tdd: none | status: pending:#5 -->

- Trigger: The scorer computes a score.
- Behavior: The scorer computes the score as a function of ledger records and of nothing else. It reads sealed claims, the baselines' among them (IN-07 to IN-09), and the results that stand for them (EN-04, IN-12), makes no random draw and calls no language model (SR-03).
- Observable: Running the scorer again over the same ledger records gives a recorded score identical to the first.
- On failure: When a record the scorer reads is missing or unreadable, the scorer stops, records the failure and writes no score.
- Verified by: A test that runs the scorer twice over one fixed set of ledger records, the second time at a later time and with no stored data but those records in its reach, and checks that every score is identical. It catches a score that depends on when the scorer runs, on a random draw or on anything outside the ledger.

**IN-02.** Scoring must not require understanding the paper: the scorer reads claims and outcomes and never paper content.
<!-- id: SDD-IN-02 | tdd: none | status: pending:#5 -->

- Trigger: The scorer reads its inputs.
- Behavior: The scorer reads sealed claims, the baselines' among them, and the results that stand for them, in which a paper appears only as an id. It has no interface (PL-02) to paper text, figures, tables or cards.
- Observable: The scorer's declared interfaces name no source of paper content, and a request from the scorer for paper content is refused.
- On failure: When a score cannot be computed from the permitted inputs, the scorer records the failure and writes no score. It does not turn to paper content.
- Verified by: A test that scores one fixed set of ledger records twice, the second time with all paper content removed, and checks that the scores are identical. It catches a scorer that reads paper content.

**IN-03.** Scoring must not punish sleepers, important papers that sit unknown, early: an unresolved claim does not count against a genome before its horizon.
<!-- id: SDD-IN-03 | tdd: none | status: pending:#5 -->

- Trigger: The scorer scores a genome that has sealed claims with no resolver result.
- Behavior: Before a claim's horizon the scorer counts the claim as neither true nor false (EN-04), so the claim adds no penalty. A claim's result, and so any penalty for a claim that settles false, comes no earlier than its horizon (EN-02).
- Observable: Apart from the novelty term (IN-04), a genome's score computed before a claim's horizon is the same with that claim in the ledger and without it.
- On failure: When the scorer cannot establish whether a claim's horizon has passed, it stops, records the failure and writes no score.
- Verified by: A test that adds a sealed claim whose horizon has not passed to a genome's records and checks that the genome's score, apart from the novelty term (IN-04), does not change. It catches a scorer that counts an unresolved claim as false.
- Limits: How early is too early to count an unresolved claim against a genome is not yet set (#6). This requirement fixes only that it is never before the claim's horizon.

**IN-04.** Scoring must include a novelty term equal to one minus the overlap with the obvious baseline's picks.
<!-- id: SDD-IN-04 | tdd: none | status: pending:#5 -->

- Trigger: The scorer scores a genome's claims on a question sheet.
- Behavior: The scorer computes the overlap between the papers the genome picked on the sheet and the papers the obvious baseline picked on the same sheet. It records one minus that overlap as the genome's novelty term.
- Observable: A novelty term recorded with each genome's score.
- On failure: When the obvious baseline's picks for the sheet are missing, the scorer records the term as not computed and writes no value for it.
- Verified by: A test that scores a genome whose picks equal the obvious baseline's and checks that the term is 0, and a genome that shares no pick with it and checks that the term is 1. It catches a term that rewards agreement with the baseline.
- Limits: Which baseline is the obvious one is not yet set (#6). Whether the novelty term enters fitness (FT-12) is not yet set (#6). What a pick is, for a genome and for a baseline, is not yet set (#6).

**IN-05.** The scorer must flag a genome whose confidences cluster at one value.
<!-- id: SDD-IN-05 | tdd: none | status: pending:#5 -->

- Trigger: The scorer scores a genome.
- Behavior: The scorer applies the clustering test to the confidences of the genome's sealed claims. When the test is met, it records a flag against the genome hash.
- Observable: A recorded flag that names the genome hash.
- On failure: When the test cannot be computed, the scorer records that it was not computed and records no flag.
- Verified by: A test that scores one genome whose claims all carry the same confidence and one whose confidences are spread from 0 to 1, and checks that only the first is flagged. It catches a scorer that never flags or that flags every genome.
- Limits: The test for confidences clustering at one value is not yet set (#6).

**IN-06.** Measuring must produce a reliability diagram per genome.
<!-- id: SDD-IN-06 | tdd: none | status: pending:#5 -->

- Trigger: The report step of the weekly cycle runs (FT-16).
- Behavior: For each genome, measuring groups the claims settled true or false by their stated confidence and sets each group's confidence against the share of its claims that settled true. The result is stored as that genome's reliability diagram.
- Observable: One stored reliability diagram for each genome that has resolved claims, named by genome hash.
- On failure: A genome with no claims settled true or false gets no diagram, and the report states that. No diagram is drawn from unresolved claims.
- Verified by: A test that supplies resolved claims with known confidences and outcomes and checks the diagram's points against shares computed by hand. It catches a diagram that includes unresolved claims or another genome's claims.

### 3.2 Baselines

**IN-07.** A popularity baseline that agents have to beat must answer every question sheet and be scored by the same scorer.
<!-- id: SDD-IN-07 | tdd: none | status: pending:#5 -->

- Trigger: A question sheet is sealed (EN-10).
- Behavior: The popularity baseline gives a confidence for each question on the sheet from a popularity signal available when the sheet is issued, and its answers are sealed in the ledger as claims (EN-03). The scorer scores them with the function it applies to genomes (FT-12).
- Observable: The baseline's sealed claims for each sheet in the ledger, and a recorded score for the baseline beside the genomes' scores.
- On failure: When no popularity signal is available at sheet time, the baseline records no answers for that sheet and the gap is recorded. No answer is added once the sheet's outcomes begin to exist.
- Verified by: A test that offers the baseline a popularity signal dated after the sheet was issued and checks that it is refused, and that checks the baseline's answers are sealed before the sheet's outcomes. It catches a baseline that sees outcomes or later data.
- Limits: The popularity signal is not named. Whether any source gives live arXiv download counts is open (#22), and this requirement holds whichever signal is chosen.

**IN-08.** A base-rate baseline that agents have to beat must answer every question sheet and be scored by the same scorer.
<!-- id: SDD-IN-08 | tdd: none | status: pending:#5 -->

- Trigger: A question sheet is sealed (EN-10).
- Behavior: The base-rate baseline gives, for each question, the rate at which earlier questions resolved true, computed only from outcomes resolved before the sheet is issued. Its answers are sealed in the ledger as claims (EN-03) and scored by the function the scorer applies to genomes (FT-12).
- Observable: The baseline's sealed claims for each sheet in the ledger, and a recorded score for the baseline beside the genomes' scores.
- On failure: When no outcome has resolved yet, the baseline records no answers for that sheet and the gap is recorded.
- Verified by: A test that builds a ledger with a known share of true outcomes and checks that the baseline's confidence equals that share, and that an outcome resolved after the sheet was issued does not change it. It catches a base rate that draws on outcomes later than the sheet.
- Limits: The reference class of the base rate, all earlier questions or each kind of question and horizon, is not yet set (#6).

**IN-09.** A plain regression over card features that agents have to beat must answer every question sheet and be scored by the same scorer.
<!-- id: SDD-IN-09 | tdd: none | status: pending:#5 -->

- Trigger: A question sheet is sealed (EN-10).
- Behavior: A plain regression, fitted on the fixed card fields of papers whose outcomes resolved before the sheet is issued, gives a confidence for each question from the cards in the sheet's snapshot. Its answers are sealed in the ledger as claims (EN-03) and scored by the function the scorer applies to genomes (FT-12).
- Observable: The baseline's sealed claims for each sheet in the ledger, and a recorded score for the baseline beside the genomes' scores.
- On failure: When the regression cannot be fitted, or a card lacks one of the fixed fields, the baseline records no answer for the affected questions and the gap is recorded.
- Verified by: A test that checks the regression's inputs against the fixed card fields and the sheet's snapshot, and that an outcome resolved after the sheet was issued does not change its answers. It catches a baseline that reads beyond the card or fits on later outcomes.
- Limits: The card fields the plain regression uses are not yet set (#6).

### 3.3 Human rating and review

**IN-10.** Human raters must rate the papers the system surfaces.
<!-- id: SDD-IN-10 | tdd: none | status: pending:#5 -->

- Trigger: A digest is delivered to the raters (EN-32).
- Behavior: Each rater rates each paper in the digest in a rating view that hides the genome and the random controls (SR-21, SR-22). The system stores each rating against the paper and the rater.
- Observable: A stored rating for each paper a rater has rated, and every other pairing of a paper in a digest and a rater shows as unrated.
- On failure: A rating that cannot be stored is shown to the rater as not saved and the paper stays unrated. No rating is filled in on a rater's behalf.
- Verified by: A test that delivers a digest, submits ratings for some of its papers and checks that each is stored against the right paper and rater and that the others show as unrated. It catches ratings that are lost, attached to the wrong paper or filled in by default.

**IN-11.** A human must spot-check a random sample of claims for whether the cited evidence supports the claim.
<!-- id: SDD-IN-11 | tdd: none | status: pending:#5 -->

- Trigger: The sampling step draws a spot-check sample from the sealed claims.
- Behavior: The system draws the sample at random, shows each sampled claim with its cited evidence in a review view, and stores the human's verdict on whether the evidence supports the claim. The human does not choose which claims are sampled.
- Observable: A record of the claims drawn, and a stored verdict against each one that has been checked.
- On failure: A sampled claim with no verdict stays recorded as unchecked. It is not swapped for another claim.
- Verified by: A test that draws a sample from a fixed set of claims and checks that the recorded draw matches the claims shown, and that a sampled claim left without a verdict still appears as unchecked. It catches hand-picked samples and claims dropped without a trace.
- Limits: The size of the spot-check sample is not yet set (#6).

**IN-12.** When a human rater and a resolver disagree, the human's judgment must stand.
<!-- id: SDD-IN-12 | tdd: none | status: pending:#5 -->

- Trigger: A rater records a judgment of a claim's outcome that differs from the resolver's result for that claim.
- Behavior: The rater's judgment is appended to the ledger as the claim's standing result and marks the resolver's result as superseded, and the resolver's record stays in the ledger unchanged (SR-14, SR-19). The scorer uses the standing result.
- Observable: A ledger record of the rater's judgment that refers to the resolver's result, and scores computed afterwards that follow the rater's judgment.
- On failure: When the rater's judgment cannot be appended, the resolver's result remains the standing result and the failure is recorded. No existing record is edited.
- Verified by: A test that records a rater's judgment opposite to a resolver's result and checks that the scorer uses the rater's judgment and that the resolver's record is still present and unchanged. It catches a resolver result that is overwritten and a human judgment that is ignored.
- Limits: Where a rater records a judgment of a claim's outcome is not yet set (#6). What stands when the two raters disagree with each other is not yet set (#6), and the behavior above does not cover that case.

**IN-13.** A resolver that disagreed with a human rater must be reviewed.
<!-- id: SDD-IN-13 | tdd: none | status: pending:#5 -->

- Trigger: A disagreement is recorded under IN-12.
- Behavior: The system opens a resolver review record that names the resolver, its version (EN-08) and the claim. The review is human work, and its conclusion is recorded against that record when it is done.
- Observable: One open resolver review record for each recorded disagreement, and the conclusion on each review that has been closed.
- On failure: When the resolver review record cannot be written, the failure is recorded. The system closes no review by itself.
- Verified by: A test that records a disagreement and checks that a resolver review record naming the resolver and its version exists and stays open until a human conclusion is recorded. It catches a disagreement that leaves no trace against the resolver.

### 3.4 Statistics and reporting

**IN-14.** The claim must be the unit of statistical analysis.
<!-- id: SDD-IN-14 | tdd: none | status: pending:#5 -->

- Trigger: A comparison between genomes, or between a genome and one of the baselines, is computed.
- Behavior: Every statistic in the comparison is computed over individual resolved claims. Claims are not first averaged by run, day, paper or genome and then counted as one observation each.
- Observable: Each reported comparison gives the count of claims on each side.
- On failure: A comparison with no resolved claims on one side is not computed, and that is recorded.
- Verified by: A test that computes a comparison over claims spread unevenly across runs and checks that the result equals the value computed by hand over claims and differs from the average over runs. It catches analysis that treats the run or the day as the unit.

**IN-15.** Comparisons must report bootstrap intervals.
<!-- id: SDD-IN-15 | tdd: none | status: pending:#5 -->

- Trigger: A comparison is computed.
- Behavior: One resampling routine, shared by all comparisons, resamples claims (IN-14) and gives an interval for the difference in the comparison's primary measure (IN-17).
- Observable: Each reported comparison gives the difference together with its interval.
- On failure: When the routine cannot produce an interval, the comparison is reported as having none and gets no verdict. The difference is not reported as a win or a loss.
- Verified by: A test that runs the routine over synthetic claims with a known difference and checks that the interval covers it, and a check that no reported comparison lacks an interval. It catches a comparison reported as a bare difference.
- Limits: Whether an interval can be reproduced from a recorded seed, its level and the count of resamples are not yet set (#6).

**IN-16.** A difference whose interval includes zero must be reported as a tie.
<!-- id: SDD-IN-16 | tdd: none | status: pending:#5 -->

- Trigger: A comparison's interval is computed (IN-15).
- Behavior: When the interval includes zero, the report calls the comparison a tie and names neither side as better. When it excludes zero, the report names the side the difference favors.
- Observable: A verdict recorded with each comparison: a tie, or the side favored.
- On failure: A comparison with no interval gets no verdict (IN-15).
- Verified by: A test that gives the reporting step a large difference whose interval spans zero and checks that the verdict is a tie. It catches a report that ranks two genomes on the difference alone.

**IN-17.** Each comparison must have one primary measure chosen in advance.
<!-- id: SDD-IN-17 | tdd: none | status: pending:#5 -->

- Trigger: A comparison is about to run.
- Behavior: The dated record that SR-18 requires names the comparison's one primary measure before the comparison runs, and the comparison's verdict (IN-16) rests on that measure alone. A comparison with no such record, or with a record that names more than one primary measure, is refused.
- Observable: One dated record per comparison that names its primary measure and is earlier than the comparison's run, and a recorded refusal for any comparison started without one.
- On failure: The comparison does not run, the refusal is recorded and no result is reported.
- Verified by: A test that starts one comparison with no record and one with a record naming two primary measures and checks that both are refused, and a check that every record is dated before its comparison ran. It catches a measure chosen after the results are seen.

**IN-18.** All runs must be reported.
<!-- id: SDD-IN-18 | tdd: none | status: pending:#5 -->

- Trigger: A report is produced.
- Behavior: The report accounts for every run that was issued a run contract in the span it covers, with each run's state. Void runs (AG-15), failed runs and quarantined runs (AG-22) are included.
- Observable: The count of runs in the report equals the count of run contracts issued in the same span, and each run appears with its state.
- On failure: When the report cannot account for every run contract, it is not issued and the failure is recorded.
- Verified by: A test that plants a void run and a failed run and checks that the report lists both and that its count of runs matches the run contracts issued. It catches a report that shows only completed or favorable runs.

### 3.5 Operations

**IN-19.** A kill switch outside the system's own processes must halt all runs.
<!-- id: SDD-IN-19 | tdd: none | status: pending:#5 -->

- Trigger: The owner operates the kill switch.
- Behavior: The kill switch stops every run in progress and blocks new runs from starting. It acts from outside the system's own processes and is able to stop any of them, so it works when they do not respond.
- Observable: After the kill switch is operated, no run is in progress, no new run contract is issued, and a record of the halt and its time exists.
- On failure: When a process does not stop, the kill switch reports the halt as incomplete and names the process. It does not report a complete halt.
- Verified by: A test that starts runs, makes the system's own processes unresponsive, operates the kill switch and checks that every run stops and none starts. It catches a kill switch that depends on the processes it is meant to stop.

**IN-20.** The kill switch must restore the last accepted state.
<!-- id: SDD-IN-20 | tdd: none | status: pending:#5 -->

- Trigger: The kill switch has halted all runs (IN-19).
- Behavior: The kill switch puts back the population, the checkpoint and the heads from the saved copy of the last accepted state, which the system keeps each time a new state is accepted. The ledger is not rolled back (SR-14).
- Observable: After the restore, the population, the checkpoint and the heads in service are identical to the saved copy of the last accepted state, and the restore is recorded.
- On failure: When the saved copy is missing or incomplete, the restore stops, the system stays halted and the failure is recorded. No partly restored state goes into service.
- Verified by: A test that accepts a state, changes the population and the heads, operates the kill switch and checks that what is restored is identical to the saved copy and that no ledger record is lost. It catches a restore that was never exercised, a partial restore and a restore that rewrites the ledger.

**IN-21.** Anomaly flags must reach the owner the same day.
<!-- id: SDD-IN-21 | tdd: none | status: pending:#5 -->

- Trigger: A component raises an anomaly flag.
- Behavior: The system sends the flag to the owner over the notification channel on the day it is raised. It records when the flag was raised and when it was sent.
- Observable: For each anomaly flag, a record of the time raised and the time sent, both on the same day.
- On failure: When the flag cannot be sent, it is recorded as not delivered. It is not recorded as sent and it is not dropped.
- Verified by: A test that raises a flag and checks for a send record dated the same day, and that raises one with the channel unavailable and checks that it is recorded as not delivered. It catches a flag that is written to a log and sent to nobody.
- Limits: The channel that carries anomaly flags is not yet set (#6). SR-13 applies to it when it is set. What raises an anomaly flag, and whether the flag of IN-05 is one, is not yet set (#6).

**IN-22.** An anomaly flag left unread must itself be recorded.
<!-- id: SDD-IN-22 | tdd: none | status: pending:#5 -->

- Trigger: An anomaly flag that was sent (IN-21) has not been read.
- Behavior: The system writes an unread record that names the flag. The record is separate from the flag and stays when the flag is read later.
- Observable: One unread record for each sent flag that has not been read.
- On failure: When the notification channel cannot say whether a flag was read, the flag is recorded as unread. It is not taken as read.
- Verified by: A test that sends two flags, marks one as read and checks that an unread record exists for the other alone. It catches a system that treats a sent flag as a read flag.
- Limits: What counts as a flag having been read is not yet set (#6). The channel is that of IN-21, and SR-13 applies to it when it is set.

**IN-23.** Text retrieved from papers must be treated as untrusted input.
<!-- id: SDD-IN-23 | tdd: none | status: pending:#5 -->

- Trigger: The reader puts paper text on a card, or a deep read returns paper text to the agent model.
- Behavior: Paper text reaches the agent model only as data inside a card or a deep-read result, apart from the prompt. Nothing in paper text changes a run's tools, budgets, prompt or run contract, and no component carries out an instruction found in it.
- Observable: A run fed a paper that contains instructions ends with the same tools, budgets and run contract it started with, and every tool call it made fits the strict schemas (AG-11).
- On failure: When paper text cannot be kept apart from the prompt, it is withheld from the agent model and the failure is recorded.
- Verified by: A test that plants a paper whose text tells the agent to call a tool outside its run contract and to exceed its budgets, and checks that neither happens and that the run's claims are scored as any others are. It catches paper text that takes effect as an instruction.

**IN-24.** Prompts and run contracts must be read-only to agents.
<!-- id: SDD-IN-24 | tdd: none | status: pending:#5 -->

- Trigger: A run starts.
- Behavior: The run is able to read its prompt and its run contract and has no means of writing to either, or to those of any other run. A prompt changes only through mutation (AG-20), outside any run.
- Observable: A write to a prompt or a run contract attempted from inside a run is refused and the refusal is recorded. The genome hash and the run contract are the same at the end of the run as at its start.
- On failure: When the read-only permission cannot be applied, the run does not start and the failure is recorded.
- Verified by: A test in which a run attempts to write to its prompt and to its run contract through every tool it holds, and which checks that each attempt is refused and both are unchanged. It catches a run that edits its own instructions or budgets.

### 3.6 Data use and presentation

**IN-25.** Data and model weights must be used only under their licenses.
<!-- id: SDD-IN-25 | tdd: none | status: pending:#5 -->

- Trigger: A data source or a set of model weights is proposed for use.
- Behavior: Before first use, a dated license review record names the license of the source or model, the use the system makes of it and whether the license allows that use (SR-20). A source or model with no record, or with a record that does not allow the use, is not used.
- Observable: One dated license review record for each data source and each model in use, and a recorded refusal for any source or model configured without one.
- On failure: When the license cannot be established or does not allow the use, the source or model stays unused and the finding is recorded.
- Verified by: A test that configures a data source with no license review record and a set of weights with none, and checks that both are refused. It catches data or weights adopted with no license read.
- Limits: Whether the ModernBERT license allows continued fine-tuning and kept checkpoints is not verified (#23).

**IN-26.** Ingest must not scrape paywalled content.
<!-- id: SDD-IN-26 | tdd: none | status: pending:#5 -->

- Trigger: Ingest fetches from a source.
- Behavior: Ingest fetches only from sources whose license review record (IN-25) allows the use, and a source that offers its content only behind a paywall gets no such record. Ingest does not work around a paywall.
- Observable: Every fetch in ingest's records goes to a reviewed source, and a fetch to any other address is refused and recorded.
- On failure: When a source answers with a paywall, ingest stores nothing from the response and records the event.
- Verified by: A test that points ingest at an address outside the reviewed sources and at a stub that answers with a paywall, and checks that the first is refused and nothing from the second is stored. It catches an ingest that follows links to publisher pages.

**IN-27.** The system must not hold personal data.
<!-- id: SDD-IN-27 | tdd: none | status: pending:#5 -->

- Trigger: Ingest stores a response, or a component writes to the ledger or stores a rating.
- Behavior: What ingest stores from a response holds no personal data. The ledger and the stored ratings name a rater by a role label and carry no name or contact detail of a rater.
- Observable: Personal data that arrived in a response appears in nothing stored and in no ledger record, and records about raters carry a role label alone.
- On failure: Personal data that arrives in a response is dropped before anything is stored. When it cannot be separated, the response is not stored and the event is recorded.
- Verified by: A test that feeds ingest a stub response holding an email address and checks that it appears in nothing stored and in no ledger record, and a check that no record about a rater carries a name or contact detail.
- Limits: Whether published author names, and account names inside a provider's response, count as personal data is not yet set (#6). EN-07 keeps each response as received, so that answer decides how the two rules meet.

**IN-28.** Outputs must not be presented as authored scientific claims.
<!-- id: SDD-IN-28 | tdd: none | status: pending:#5 -->

- Trigger: The system produces a digest or a report.
- Behavior: Every digest and every report carries a label that says its content is the output of an automated system and is not a scientific claim authored by anyone. Claims are worded as dated predictions with a confidence and not as findings.
- Observable: The label on every delivered digest and every stored report.
- On failure: A digest or a report that lacks the label is not delivered or stored, and the failure is recorded.
- Verified by: A test that builds a digest and a report without the label and checks that delivery and storing are refused, and that checks the label on ones built normally. It catches output that reads as a person's finding.

### 3.7 Known weaknesses to avoid

**IN-29.** The system must measure and report its accuracy on timing against chance, to avoid near-chance accuracy on timing, a weakness reported of published systems.
<!-- id: SDD-IN-29 | tdd: none | status: pending:#5 -->

- Trigger: The report step of the weekly cycle runs (FT-16).
- Behavior: Measuring computes the timing measure over resolved claims for each genome. It reports each value beside the value that chance gives on the same claims.
- Observable: Each report gives the timing measure for each genome beside the chance value.
- On failure: When the measure cannot be computed, the report states that and gives no value.
- Verified by: A test that supplies resolved claims whose timing is right at the chance rate and checks that the report shows the measure equal to the chance value beside it. It catches a report that leaves timing out or shows timing with no chance value to read it against.
- Limits: The timing measure is not yet set (#6). The cited weakness carries no verification date yet (SR-20).

**IN-30.** The system must measure and report the calibration of each genome's confidences, to avoid overconfidence, a weakness reported of published systems.
<!-- id: SDD-IN-30 | tdd: none | status: pending:#5 -->

- Trigger: The report step of the weekly cycle runs (FT-16).
- Behavior: Measuring reports each genome's reliability diagram (IN-06), in which overconfidence shows as a share of claims settled true that lies below the stated confidence. The heads are calibrated separately (FT-11).
- Observable: Each report gives the reliability diagram of each genome that has resolved claims.
- On failure: A genome with no claims settled true or false gets no diagram, and the report states that.
- Verified by: A test that supplies claims stated at a high confidence, of which a known smaller share settled true, and checks that the genome's diagram in the report shows that share below the stated confidence. It catches a report that gives accuracy alone.
- Limits: The cited weakness carries no verification date yet (SR-20).

**IN-31.** The system must measure and report the spread of topics among the papers it surfaces, to avoid bias toward mainstream topics, a weakness reported of published systems.
<!-- id: SDD-IN-31 | tdd: none | status: pending:#5 -->

- Trigger: The report step of the weekly cycle runs (FT-16).
- Behavior: Measuring computes the measure of topic spread over the papers surfaced in the span the report covers and reports its value.
- Observable: Each report gives the value of the measure of topic spread for the surfaced papers.
- On failure: When no paper was surfaced in the span, or the measure cannot be computed, the report states that and gives no value.
- Verified by: A test that supplies one set of surfaced papers drawn from a single topic and one spread evenly across topics, and checks that the reported value is lower for the first. It catches a report that leaves topic spread out and a measure that does not move with it.
- Limits: The measure of topic spread is not yet set (#6). The cited weakness carries no verification date yet (SR-20).

**IN-32.** The system must report the share of spot-checked claims whose cited evidence does not support the claim, to avoid cited evidence that does not drive the prediction, a weakness reported of published systems.
<!-- id: SDD-IN-32 | tdd: none | status: pending:#5 -->

- Trigger: The report step of the weekly cycle runs (FT-16).
- Behavior: Measuring reports the share of spot-checked claims whose stored verdict (IN-11) is that the cited evidence does not support the claim, with the count of claims checked.
- Observable: Each report gives that share and that count.
- On failure: When no verdict exists for the span, the report states that and gives no share. Sampled claims still unchecked are counted as unchecked and not as supported.
- Verified by: A test that stores a known set of verdicts, leaves some sampled claims unchecked and checks that the reported share and count match the verdicts alone. It catches a report that counts unchecked claims as supported.
- Limits: The spot check is the only probe specified, and it shows whether evidence supports a claim, not whether the evidence drove it. The cited weakness carries no verification date yet (SR-20).
