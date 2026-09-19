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
