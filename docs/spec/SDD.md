# Software Design Description

What the software must do, stated as requirements a reader can verify.

## Document control

| Field               | Value                                                                                                                                |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Product             | research-agent: a forward-only research agent for arXiv cs.AI and cs.LG, with weekly prediction-head refitting; encoder fine-tuning is deferred.        |
| Target version      | The first release. No release tag exists yet.                                                                                        |
| Scope               | One deployment on one host. What it covers, at what scale, and what it leaves out are stated under Scope and scale.                  |
| Authority           | This document decides what the software does. Where code and this document disagree, one is wrong; say which, with evidence.         |
| Companion documents | [TDD.md](TDD.md) states how each requirement is met. [SPEC-AMENDMENTS.md](SPEC-AMENDMENTS.md) records each change to either.         |
| Change control      | A pull request cites an accepted decision under `docs/decisions/`, edits the exact lines, and appends a row to the amendment ledger. |

## Scope and scale

The software reads every new paper in two arXiv categories with small models, gives a population of the same agent a paper card per paper, and takes from each agent dated forecasts about which papers will matter. Forecasts are sealed in a ledger before their outcomes exist and settled later by deterministic resolvers. Each agent's configuration, its genome, is scored only by that record, and the population is selected and mutated toward its best performers. The prediction heads are fit on the frozen embedding model's vectors and refit and calibrated each week; weekly fine-tuning of an encoder is held out until the system without it has been measured (SR-17, #51). Jev adds fixed content assessments to paper cards at launch (RD-15 to RD-24). Two raters rate what the system surfaces, through a private app, without seeing where it came from.

- Covers: ingest of the corpus, of outcomes and of discovery-service picks, the small models and their fitting, the reader, the agent runs, the ledger and its resolvers, scoring against the baselines, selection and mutation, the digest and human rating, and the platform all of it runs on.
- Scale: one host that meets a stated floor, run by its owner. One corpus, arXiv cs.AI and cs.LG. One population of one agent design. Two raters. Output that is private to the raters.
- Does not cover: more than one host, a corpus beyond the two categories, output to the public, a model trained from scratch, or reading papers with an optical character recognition model.

A requirement states the smallest behavior that serves the study. A capability that would be a second way of doing something the system already does once stays out until the system without it has been measured, except for the named Jev launch exception (SR-17).

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

Established technical terms keep their usual meaning, qualified by the definitions below. Descriptive groupings and interface labels specific to this project are identified explicitly; they are not claims of an academic or industry standard. A name does not establish a measured property: a novelty proxy does not prove scientific novelty, and a reported probability does not establish calibration.

| Term | Meaning |
| --- | --- |
| agent model | The language model called by an agent run. Its weights are not trained by this system (FT-07). |
| assessment confidence | A model's stated certainty about a content assessment, or a class probability with a named target. Distinct from a forecast probability about a future event. Jev assessment confidence summarizes its returned class distribution (RD-18); measured accuracy is separate (RD-22). |
| Jev assessment | A fixed, model-derived classification of what a paper reports, under the rubric in RD-16. It is not a forecast or an overall scientific-quality score. |
| baselines | Popularity, base rate, regression over paper-card features, and nearest-neighbor forecasting (IN-07 to IN-09, IN-33). |
| batch job | Training or data preparation executed separately from request-serving services. Distinct from a forecast batch. |
| calibration | Agreement between predicted probabilities and observed event frequencies across evaluated predictions. FT-11 calibrates prediction heads; IN-06 measures agent forecasts. |
| checkpoint | A saved state of neural model weights. The embedding model retains its adopted checkpoint; an encoder checkpoint series exists only if fine-tuning enters (#51). A checkpoint date is not an immutable artifact identifier. |
| cohort | Papers from the same week used for relative outcome thresholds (EN-12). The precise boundary remains a configured decision. |
| delayed recognition | Later recognition after an initial period of little recognition. Bibliometrics also calls such papers Sleeping Beauties; low attention at arrival alone does not establish this longitudinal pattern. |
| digest | The private collection of selected papers delivered to raters through the rating app. |
| embedding model | The frozen document embedding model (MD-06). It is an encoder by function; the separate term encoder below identifies a different project role. |
| embedding distance | Project-specific name for RD-07's distance-based statistic relative to the corpus, using the embedding model's vectors. It is a proxy for semantic novelty; its distance and aggregation remain open in #6. |
| encoder | The BERT encoder adopted under MD-04 for possible fine-tuning. Its training and contribution to prediction-head features are held out of the first build (#51). |
| exclusion action | Project-specific name for a run or lineage's exclusion from scoring or execution: quarantine, followed by permanent exclusion where AG-22 specifies it. This is not a synonym for an ordinary provider failure. |
| fitness | The numerical objective used for evolutionary selection, derived from forecast performance under FT-12. It is not a measure of a paper's scientific quality. |
| fitted artifact | Saved fitted parameters of a prediction head or calibrator. A prediction head's fit date is the date assigned by its refit (FT-10). |
| forecast | A dated prediction with evidence ids, a resolvable event statement, a horizon and a forecast probability (SR-07 to SR-10). A paper's own scientific assertion is a paper claim, not a forecast. |
| forecast batch | Project-specific name for the daily collection of forecasting questions under EN-09. Short form: batch. It does not mean a training batch. |
| forecast probability | The submitted probability from 0 to 1 that a forecast's specified event will resolve true by its horizon. Distinct from assessment confidence and from the confidence level of a statistical interval. |
| genome | The evolutionary-search representation of an agent configuration: prompt, scan policy, read policy, probability assignment rule, structured output schema, tools, budgets and sampling settings (AG-16). |
| horizon | The time interval used to determine when a forecast is resolved. The origin for batch questions remains open under EN-13; this term does not settle that choice. |
| ingest | The component that retrieves external data. SR-13 also permits an agent run's call to its agent-model API; ingest is not the only permitted internet path. |
| ledger | The append-only, hash-chained record used for scoring. Each record has a kind (EN-06). Its chain head is unrelated to a prediction head. |
| masked-LM surprise score | Project-specific umbrella for the deferred masked-language-model signal (RD-09, #49). Pseudo-log-likelihood and pseudo-perplexity are established candidate scoring quantities; the name does not choose their formula or equate them with scientific novelty. |
| model-state date | Project-specific umbrella for the checkpoint date of neural weights or the fit date of a prediction head, used in existing model stamps (SR-15, RD-03). Identity and provenance are recorded separately. |
| online attention track | Project-specific grouping of visibility and expressed-interest indicators: Hugging Face upvotes, GitHub stars and Hacker News mentions (EN-21 to EN-23). These do not establish quality or adoption. Altmetrics is a broader established category, not an exact synonym. |
| operational alert | A diagnostic flag delivered through the rating app (IN-21). Distinct from a paper's statistical outlier score or novelty assessment; alert triggers remain open in #6. |
| paper card | Project-specific text record produced by the reader for one paper. The display label is distinct from a model card documenting a model. |
| pick-set non-overlap score | Project-specific name for one minus the overlap between an agent's selected papers and discovery-service selections (IN-04). It measures selection disagreement, not scientific novelty; the overlap convention remains open in #6. |
| population | The set of active agent configurations participating in evolutionary selection. Genome, population, mutation and fitness retain their evolutionary-search meanings. |
| prediction head | A probabilistic outcome model over frozen features, with model family and calibration method configured under FT-08 and FT-11. It can be a separately fitted classifier; the term does not imply joint BERT fine-tuning. |
| rating app | The private app serving the digest, ratings, detail view and operational alerts (PL-22). |
| reader | The project component that assembles paper cards from model outputs and recorded signals. |
| research uptake track | Project-specific grouping of citation and artifact indicators (EN-17 to EN-20). These are proxies for uptake, not proof of independent adoption, scientific correctness or reader usefulness. |
| resolver | An outcome-resolution function that deterministically returns true, false or unresolvable with evidence. |
| run | One execution of an agent under an immutable run specification. |
| run specification | Project-specific record of a slot, genome hash, seed, snapshot hash, budgets and allowed tools (AG-17). |
| scorer | The deterministic component that scores forecasts and agent configurations. |
| semantic novelty | Difference in meaning or contribution relative to prior work. It is not established by textual rarity or embedding distance alone. No new novelty assessment is required by this definition. |
| service pick | A paper selected by a discovery service and captured by ingest on the selection day (EN-38). |
| shared model service | The service providing small-model outputs for agent runs (PL-08). |
| shared tool service | The service enforcing the run specification on each tool call and answering from its snapshot (PL-20, PL-21). |
| small models | Project shorthand for the embedding model, prediction heads and the encoder when its training enters (#51). It is a role grouping, not a parameter-count standard. |
| snapshot | The read-only collection of paper versions, paper cards and citation-graph data frozen when a forecast batch is issued. |
| structured output schema | The schema for the agent model's turns: a fixed protected core and an evolvable extension (AG-32 to AG-35). |
| weekly refitting | Fitting prediction heads again on eligible known outcomes each week. This does not train the embedding model and does not by itself imply online or continual learning of encoder weights. |

Historical aliases below preserve the meaning of earlier decision records, issues and incoming candidates. They are not additional data types or new behaviors.

| Historical wording | Current wording |
| --- | --- |
| claim, for a submitted prediction | forecast |
| confidence, for a future event | forecast probability |
| confidence rule | probability assignment rule |
| question sheet, sheet | forecast batch, batch |
| card | paper card |
| embedder | embedding model |
| head, heads, for outcome models | prediction head, prediction heads |
| checkpoint date, for a fitted head | fit date |
| checkpoint dates, when combining weights and fitted heads | model-state dates |
| use track | research uptake track |
| attention track | online attention track |
| novelty distance | embedding distance |
| novelty term, for service-pick overlap | pick-set non-overlap score |
| masked-word surprise | masked-LM surprise score |
| anomaly flag | operational alert |
| sleeper | paper with delayed recognition |
| run contract | run specification |
| working format | structured output schema |
| sanction | exclusion action |

Terminology references, checked against their primary sources on 2026-09-20:

- [Literature-Grounded Novelty Assessment of Scientific Ideas, 2025](https://aclanthology.org/2025.sdp-1.9/): scientific novelty assessment against prior literature.
- [A Toolbox for Improving Evolutionary Prompt Search, 2025](https://aclanthology.org/2025.luhme-1.6/): evolutionary prompt optimization terminology.
- [Verifiable Rewards for Calibrated Probabilistic Forecasting, 2026 preprint](https://arxiv.org/abs/2607.00164): probabilistic forecasting distinguished from confidence in an answer. A preprint is terminology evidence, not an adopted technical standard.
- [Masked Language Model Scoring, 2020](https://aclanthology.org/2020.acl-main.240/): pseudo-log-likelihood and pseudo-perplexity for masked language models.
- [Defining and identifying Sleeping Beauties in science, 2015](https://arxiv.org/abs/1505.06454): delayed recognition as a longitudinal bibliometric phenomenon.
- [NISO Altmetrics Initiative](https://www.niso.org/standards-committees/altmetrics): the broader alternative-metrics context for research assessment.

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
<!-- id: SDD-SR-03 | tdd: none | status: pending:#57 -->

- Trigger: The scorer computes a score for a forecast, a genome or a baseline.
- Behavior: The scorer computes each score from ledger records by a deterministic function (IN-01) and calls no language model at any step.
- Observable: The network reach declared for the scorer (PL-19) includes no language model, and the scorer produces every score with all language models unreachable.
- On failure: A score that cannot be computed from ledger records alone is not recorded, and the failure is recorded.
- Verified by: A test that runs the scorer with every language model unreachable and checks that all scores appear and equal those of a normal run. It would catch a scorer that asks a model to judge a forecast.

**SR-04.** A language model must be limited to proposing or pre-filtering.
<!-- id: SDD-SR-04 | tdd: none | status: pending:#57 -->

- Trigger: A component receives output from a language model.
- Behavior: The output is taken only as a proposal, such as a forecast or a mutation (AG-20), or as a pre-filter that narrows what a deterministic step or a person then decides. No language model output settles a forecast, computes a score (SR-03), selects a genome or applies an exclusion action.
- Observable: The components that settle, score, select and apply exclusion actions have no language model within their declared reach (PL-19).
- On failure: A step that settles, scores, selects or applies exclusion actions and cannot complete without a language model stops, and the failure is recorded. No language model output is taken in place of its result.
- Verified by: A test that runs resolution, scoring, selection and exclusion actions with every language model unreachable and checks that the results are unchanged. It would catch a resolver or a selection step that asks a model to decide.

**SR-05.** Every interface to the agent must treat the agent as an untrusted proposer.
<!-- id: SDD-SR-05 | tdd: none | status: pending:#57 -->

- Trigger: An agent run sends a tool call or a submission to another component.
- Behavior: The receiving component validates the message against its schema (AG-11) and the run specification (AG-17) before acting on it. The agent holds no authority: it writes no ledger record itself and changes no prompt, run specification (IN-24) or snapshot content (AG-10).
- Observable: A message that fails validation gets a refusal, and the refusal appears in the run trace (SR-02).
- On failure: The message is refused whole, nothing from it is accepted, and the refusal is recorded.
- Verified by: A test that sends a malformed tool call and a call to a tool outside the run specification, and checks that each is refused and recorded. It would catch an interface that accepts agent input as given.

**SR-06.** An agent's output must be acted on only by the scorer and a human reader.
<!-- id: SDD-SR-06 | tdd: none | status: pending:#5 -->

- Trigger: An agent run submits its output.
- Behavior: Agent output goes to the ledger, and from the ledger to the scoring path (the resolvers and the scorer) and to human readers through the digest (EN-32) and the spot check (IN-11). No other component takes agent output as input.
- Observable: The declared service interfaces (PL-02) show no consumer of agent output other than those.
- On failure: A request for agent output from any other component is refused, and the refusal is recorded.
- Verified by: A check of the declared interfaces that fails when any other component reads agent output, and a test that such a read is refused.
- Limits: Whether the step that proposes mutations is shown agent output is open (#13). Under this rule it is shown none.

**SR-26.** Agent output must reach a rater only as recorded fields rendered by the app, and never as text that a model wrote for the rater.
<!-- id: SDD-SR-26 | tdd: none | status: pending:#45 -->

- Trigger: Agent output reaches a rater through the digest (EN-32) or the spot-check review view (IN-11).
- Behavior: The app renders each field a run recorded to the ledger exactly as recorded. No component calls a language model to rewrite, summarize or draft prose from that output for a rater to read: the same limit to proposing or pre-filtering that SR-04 sets, and the same rule against an added layer that AG-08 sets inside a run.
- Observable: What a rater receives in a digest or a review view matches, field for field, what a run's record holds, with no passage of text absent from a record, and the digest still carries the label IN-28 requires.
- On failure: A digest or a review view that requires a rewriting step to be produced is not delivered, and the failure is recorded.
- Verified by: A test that builds a digest through an added step that rewrites a run's recorded fields into new prose, and checks that the digest is refused because its text does not match the record. It would catch a display layer drafting text for a rater instead of rendering the record.

### 1.3 Forecasts

**SR-07.** Every forecast must carry evidence ids that are among the items its run retrieved through its tools.
<!-- id: SDD-SR-07 | tdd: none | status: pending:#57 -->

- Trigger: A forecast is submitted for sealing.
- Behavior: The sealing step looks up each evidence id of the forecast in the run trace of the forecast's run (SR-02), which records every item the run's tools retrieved from the snapshot named in its run specification (AG-10). The forecast is sealed as valid only when it carries at least one evidence id and the run trace shows every id was retrieved by that run.
- Observable: The ledger record of a sealed forecast holds its evidence ids, and a forecast with an id the run trace shows was never retrieved appears in the ledger as void.
- On failure: A forecast with no evidence id, or with an id its run did not retrieve, is recorded as void (SR-11). If the trace lookup itself cannot run, nothing is sealed and the failure is recorded.
- Verified by: A test that submits a forecast citing an evidence id present in the snapshot but never retrieved by the forecast's run, and one with no evidence id, and checks that each is recorded as void.
- Limits: Open issue #12, whether every surfaced paper is itself a dated forecast, is not decided. This rule applies to whatever is sealed as a forecast under either option.

**SR-08.** Every forecast must carry a statement that a resolver can settle.
<!-- id: SDD-SR-08 | tdd: none | status: pending:#57 -->

- Trigger: A forecast is submitted for sealing.
- Behavior: The statement either answers a question on the sealed batch, whose resolver is fixed (EN-11), or is a volunteered forecast of an admitted forecast type (EN-30). The sealing step binds the forecast to that resolver at submission.
- Observable: The ledger record of a sealed forecast shows which resolver it is bound to, at the version fixed under EN-11.
- On failure: A forecast whose statement matches no batch question and no admitted forecast type is recorded as void (SR-11).
- Verified by: A test that submits a forecast with free text in place of a statement of an admitted type and checks that it is recorded as void. It would catch a forecast sealed with a statement no resolver can read.
- Limits: Open issue #12, whether every surfaced paper is itself a dated forecast, is not decided. This rule applies to whatever is sealed as a forecast under either option.

**SR-09.** Every forecast must carry a horizon.
<!-- id: SDD-SR-09 | tdd: none | status: pending:#57 -->

- Trigger: A forecast is submitted for sealing.
- Behavior: The sealing step checks that the forecast carries one horizon. The horizon fixes the time after sealing at which the resolver settles the forecast.
- Observable: The ledger record of a sealed forecast holds its horizon.
- On failure: A forecast with no horizon is recorded as void (SR-11), and no horizon is assumed for it.
- Verified by: A test that submits a forecast with no horizon and checks that it is recorded as void and that no default horizon is filled in.
- Limits: The horizon values for batch questions are those of EN-13, and no accepted statement limits the horizon of a volunteered forecast (EN-30). Open issue #12, whether every surfaced paper is itself a dated forecast, is not decided, and this rule applies to whatever is sealed as a forecast under either option.

**SR-10.** Every forecast must carry a forecast probability from 0 to 1.
<!-- id: SDD-SR-10 | tdd: none | status: pending:#57 -->

- Trigger: A forecast is submitted for sealing.
- Behavior: The sealing step checks that the forecast carries one forecast probability and that the value lies in the range. The value is sealed as submitted.
- Observable: The ledger record of a sealed forecast holds the forecast probability exactly as submitted.
- On failure: A forecast with no forecast probability, or with a value outside the range, is recorded as void (SR-11). The value is not clipped into the range and no default is filled in.
- Verified by: A test that submits a forecast with a forecast probability above 1, one below 0 and one with none, and checks that each is recorded as void and that none is sealed with an altered value.
- Limits: The range is 0 to 1, end values included. Open issue #12, whether every surfaced paper is itself a dated forecast, is not decided, and this rule applies to whatever is sealed as a forecast under either option.

**SR-11.** A forecast that a resolver cannot bind must be recorded as void.
<!-- id: SDD-SR-11 | tdd: none | status: pending:#57 -->

- Trigger: The sealing step finishes its checks on a submitted forecast (SR-07 to SR-10).
- Behavior: A forecast is bound when it passes every check of SR-07 to SR-10, so that a resolver can read its evidence, statement and horizon at settlement. Any other forecast is recorded in the ledger as void and is neither settled nor scored.
- Observable: Every such forecast appears in the ledger as void, and no resolver result and no score exists for it.
- On failure: If the forecast cannot be recorded as void, the submission is not accepted and the failure is recorded.
- Verified by: A test that submits one forecast failing each check of SR-07 to SR-10 and checks that each is recorded as void, that none reaches a resolver, and that the other forecasts of the run are sealed as usual.

**SR-24.** A submitted forecast must carry a rationale of bounded length that is recorded, never scored, and shown to a rater only after that rater has rated the entry.
<!-- id: SDD-SR-24 | tdd: none | status: pending:#57 -->

- Trigger: A forecast is submitted for sealing.
- Behavior: The rationale is a field of the submit schema, so a call that omits it or exceeds its bound is refused whole (AG-11). The sealing step records it on the forecast apart from the statement bound under SR-08, the scorer never reads it (IN-02), and a rating view withholds it until that rater has rated the entry.
- Observable: The ledger record of a sealed forecast holds its rationale, and a rating view served to a rater before that rater has rated the entry carries no rationale field for it.
- On failure: A submit whose rationale is missing or over its bound is refused and nothing of that call is sealed (AG-11). A rationale that cannot be written to the record of an accepted call leaves the forecast unsealed, and the failure is recorded.
- Verified by: A test that submits a forecast with no rationale and one over the bound and checks that both calls are refused with nothing sealed. A test that checks the score is identical whether the field is present or removed, and that the rating view carries it only after that rater has rated the entry.
- Limits: The bounded length of a rationale is not yet set (#6).

### 1.4 Isolation

**SR-12.** An agent run must reach only the frozen snapshot and the API of the agent model.
<!-- id: SDD-SR-12 | tdd: none | status: pending:#57 -->

- Trigger: An agent run starts.
- Behavior: The run reaches the snapshot named in its run specification (AG-10) through its tools, which also take its submission (AG-09), and calls the API of the agent model. The platform closes every other destination to it, the shared model service (PL-08) included, and all other stored data (PL-19).
- Observable: The reach declared for the run under PL-19 lists those two destinations only, and an attempt from inside the run to reach anything else fails.
- On failure: A run whose isolation cannot be put in place does not start, and the failure is recorded.
- Verified by: A test that, from inside a run, tries to reach an internet address other than the API of the agent model, to call the shared model service and to read stored data outside the snapshot, and checks that every attempt fails.

**SR-13.** A component other than ingest must not reach the internet, except for an agent run's call to the API of the agent model.
<!-- id: SDD-SR-13 | tdd: none | status: pending:#54 -->

- Trigger: Any container starts.
- Behavior: The platform gives internet reach to ingest, and gives each agent run one route to the API of the agent model (SR-12). Ingest also mediates Jev assessment requests (RD-20); the reader consumes stored responses. Every other container has no route to the internet, and the platform enforces this from outside the component (PL-19). The rating app is reached over a private network alone, with no internet route either way.
- Observable: The reach declared under PL-19 shows internet access for ingest and the one route for agent runs, and an outbound attempt from any other container fails. The rating app's declared reach shows the private network alone, with no internet route in either direction.
- On failure: A container whose reach cannot be set as declared does not start, and the failure is recorded.
- Verified by: A test that attempts an outbound connection from every container other than ingest and checks that each attempt fails, apart from an agent run's call to the API of the agent model. A further test attempts to reach the rating app from the internet and checks that the attempt fails.
- Limits: Where the hash chain head is anchored (SR-16) is not yet set (#6), and this rule applies to it once set. The digest (EN-32) and the operational alerts (IN-21) now run through the rating app on its private network, not the internet. What proposes mutations is open (#13), and a call from that step to a language model is another outbound path.

### 1.5 Ledger and run records

**SR-14.** The ledger must be append-only.
<!-- id: SDD-SR-14 | tdd: none | status: pending:#5 -->

- Trigger: Any component writes to the ledger.
- Behavior: The ledger accepts a new record at its end and refuses every request to change or remove a record already written.
- Observable: A request to rewrite or delete a record gets a refusal, and the records already written and the hash chain over them (EN-05, EN-06) are unchanged.
- On failure: An append that cannot complete leaves no partial record, and the step that asked for it stops and records the failure.
- Verified by: A test that attempts to overwrite and to delete an existing record through the ledger's interface and checks that both are refused and that the chain still verifies (EN-05).

**SR-15.** Every run must be stamped with its genome hash, its seed, the id of the agent model and the model-state dates of the small models.
<!-- id: SDD-SR-15 | tdd: none | status: pending:#57 -->

- Trigger: An agent run starts.
- Behavior: One stamp is written to the ledger for the run, once, before the run's first call to the agent model. It holds the genome hash and the seed from the run specification (AG-17), the id of the agent model the run calls, and the model-state dates of the encoder, the embedding model and the prediction heads being served when the run starts (PL-13). PL-06 adds the versions of the service images to the stamp.
- Observable: The ledger holds exactly one stamp for every run, written as a ledger record (EN-06), and it sits earlier in the ledger than any forecast of that run.
- On failure: A run whose stamp cannot be written, or whose stamp lacks a value, does not start, and the failure is recorded.
- Verified by: A test that starts a run, promotes a new checkpoint while it runs, and checks that the stamp shows the dates served at the start. A second test withholds one value and checks that the run does not start.
- Limits: Open issue #14, the name of the agent's language model, is not decided, and the stamp records the id of whichever agent model the run calls under either option. The embedding model is never trained (FT-06) and keeps the checkpoint date it was adopted with.

**SR-16.** The head of the ledger's hash chain must be anchored in a place outside the system.
<!-- id: SDD-SR-16 | tdd: none | status: pending:#5 -->

- Trigger: Anchoring comes due on its schedule.
- Behavior: The current head hash of the ledger's chain (EN-05), with its sequence number (EN-06), is written to a place that no process of the system can alter.
- Observable: The anchored value can be read from outside the system and compared with the ledger record at the same sequence number.
- On failure: A failed anchoring is recorded, and the previous anchor stays in place.
- Verified by: A test that alters a record in a copy of the ledger, recomputes the chain, and checks that comparing the copy with the anchored head shows the change. It would catch an anchor the system could rewrite along with the chain.
- Limits: Where the head of the hash chain is anchored, and how often, is not yet set (#6). SR-13 applies to the path of the anchoring write when it is set.

**SR-23.** A stored value that a component derives must carry the hashes of the inputs it was derived from and the version of the component that derived it.
<!-- id: SDD-SR-23 | tdd: none | status: pending:#57 -->

- Trigger: A component derives and stores a value from other stored values.
- Behavior: The component writes, beside the stored value, the hashes of every input it read and the version of the component that ran. The same stamp already applies to raw responses, paper card numbers, a run and a resolver (EN-07, RD-02, RD-03, SR-15, EN-08). This rule extends it to every other derived value a component stores.
- Observable: A stored value carries beside it the hashes of its inputs and the version of the component that derived it, and a named input hash can be recomputed from what is stored to check that it matches.
- On failure: A value that cannot be stamped with its input hashes and deriving version is not stored, and the failure is recorded.
- Verified by: A test that alters one stored input after a value was derived from it and checks that the input's hash recorded beside the derived value no longer matches the altered input. It would catch a stamp that does not reveal a later change to an input the value was derived from.
- Limits: The exact fields and placement of the stamp for a value beyond the ones already named are open (#32), and this rule holds under whatever shape that issue settles.

### 1.6 Procedure for change

**SR-17.** A layer other than the named Jev launch assessment must be added only after the configuration without it has been measured on the same score.
<!-- id: SDD-SR-17 | tdd: none | status: pending:#54 -->

- Trigger: A layer, meaning any part added to the running configuration to improve a score, is proposed for addition.
- Behavior: Jev assessments enter at launch after the qualification and preregistration gates of RD-22 to RD-24, without waiting for mature forecast outcomes; the comparison in RD-23 measures their downstream benefit. For every other layer, the configuration without the layer is first measured on the primary measure of the comparison (IN-17), and the result is written to the ledger as a dated record. The layer is switched on only after that record exists, and it is then measured on the same score.
- Observable: A Jev launch has the RD-24 readiness record; for every other layer, the measurement without the layer sits earlier in the ledger than the stamp (SR-15) of the first run that includes the layer.
- On failure: A Jev launch without the RD-24 readiness record is refused. For every other layer, without the earlier measurement the addition is refused, the configuration stays as it was, and the refusal is recorded.
- Verified by: A test that tries to switch on a layer with no earlier measurement, and again with a measurement on a different score, and checks that both attempts are refused for other layers. A Jev launch test checks that missing qualification or preregistration refuses launch while immature forecast outcomes alone do not.
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

**SR-27.** A step that can be wrong must have a named accuracy measure, a reference it is measured against, and a schedule on which it is computed and reported.
<!-- id: SDD-SR-27 | tdd: none | status: pending:#54 -->

- Trigger: A step of the system that can produce a wrong output is added or changed.
- Behavior: The step is given one named accuracy measure, a reference and a schedule, as IN-06 and IN-29 to IN-32 already give the agent-level measures. Jev fields use the reference, metrics and schedule of RD-22. A comparison of the step against an alternative follows SR-17 and SR-18. A hand-checked sample the measure uses is drawn with a recorded seed.
- Observable: A stored measure definition names the step, its accuracy measure, its reference and its schedule, and a report exists for the step on that schedule.
- On failure: A step with no named measure, reference or schedule is not put into use, and the gap is recorded.
- Verified by: A check that lists every step in the running configuration and fails on one with no recorded measure, reference or schedule. A test that gives a measure an outcome not yet resolved and checks that the measure refuses to compute.
- Limits: Which steps of the pipeline count as a step that can be wrong is not yet set (#6).

### 1.7 Blind rating

**SR-21.** Human rating must hide from a rater which genome surfaced a paper.
<!-- id: SDD-SR-21 | tdd: none | status: pending:#45 -->

- Trigger: A digest (EN-32), its rating view or its detail view (IN-36) is prepared for a rater.
- Behavior: What a rater receives carries no genome hash, lineage, slot or run for any paper, and papers are not grouped or ordered by genome. Where the detail view shows a paper's runs (IN-36), each run's label is drawn fresh for that paper and carries no identity across papers. The link from paper to genome stays recorded, out of the rater's view.
- Observable: A delivered digest and its rating view contain no genome identifier, and ratings are joined to genomes afterwards from the recorded link. In a detail view, the run label for a given genome differs from one paper to the next, so no label persists across papers.
- On failure: A rating view or a detail view that cannot be produced without the genome, or without labels drawn fresh for that paper, is not delivered, and the failure is recorded.
- Verified by: A test that builds a digest from papers surfaced by known genomes and checks that nothing the rater receives, in a field or in the order of papers, identifies the genome of any paper. A further test builds detail views for two papers surfaced by the same genome and checks that the label given to its run differs between the two papers.

**SR-22.** Human rating must hide from a rater which papers are random controls or service picks.
<!-- id: SDD-SR-22 | tdd: none | status: pending:#45 -->

- Trigger: A digest that includes random papers (EN-33) or service picks (EN-38), and its rating view, are prepared for a rater.
- Behavior: A random control or a service pick appears in the same form as a surfaced paper, with no field, label or fixed position that sets it apart from the others. The record of which papers are controls or service picks is kept out of the rater's view.
- Observable: In a delivered digest, a control, a service pick and a surfaced paper show the same fields, and the record of which papers were controls or service picks exists outside the digest.
- On failure: A digest in which controls or service picks cannot be shown in the same form is not delivered, and the failure is recorded.
- Verified by: A test that builds a digest with known controls and known service picks and checks that no field and no fixed position in what the rater receives sets any one of the three kinds of paper apart from the others.

**SR-25.** The rating view must hide agent forecast probabilities, agent rationales, popularity counts, Jev assessments and the origin of each entry until the rater has rated that entry.
<!-- id: SDD-SR-25 | tdd: none | status: pending:#54 -->

- Trigger: A digest and its rating view are prepared for a rater.
- Behavior: What a rater sees before rating an entry carries no agent forecast probability, no agent rationale (SR-24), no popularity count, no Jev assessment or assessment confidence, and no marker of origin, as SR-21 hides the genome and SR-22 hides random controls. Each stays recorded and is shown to the rater once rated, except for whatever SR-21 or SR-22 keeps hidden past that point.
- Observable: A rating view served before a rating is recorded for an entry shows none of the five groups of values, and the same view served after shows each one SR-21 and SR-22 do not also keep hidden.
- On failure: A rating view that cannot be produced with the five groups of values hidden is not delivered, and the failure is recorded.
- Verified by: A test with a known forecast probability, rationale, popularity count and Jev assessment checks that none appears before the rating is recorded and that each appears once it is. A second test gives the entry an origin that SR-21 or SR-22 also hides and checks that the view never reveals it, rated or not.

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
<!-- id: SDD-PL-04 | tdd: none | status: pending:#57 -->

- Trigger: A container is started.
- Behavior: The definition (PL-03) states a processor limit, a memory limit and an accelerator limit for every container, and the platform applies them at start. A container that uses no accelerator is declared with none.
- Observable: For each running container, the limits the platform reports equal the limits in the definition.
- On failure: A container whose definition lacks any of the three limits is not started, and the refusal is recorded.
- Verified by: A test that runs a batch job that tries to take more processor and memory than its limits, and checks that the platform holds it to them while a service beside it keeps answering. A second check fails when any container in the definition lacks a limit.
- Limits: The limits for each container are not yet set (#6). Weekly fine-tuning of the encoder is held out of the first build (SR-17, #51), so the accelerator limit is stated without naming hardware, and whether training runs on the target hardware (#18) is settled with that layer.

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

**PL-20.** The tools of an agent run must be served by one shared tool service that applies the run specification to every call and keeps no state that one run can read of another.
<!-- id: SDD-PL-20 | tdd: none | status: pending:#57 -->

- Trigger: A run's loop sends a tool call to be answered (AG-09).
- Behavior: One shared tool service, running in its own container (PL-01), receives the call, checks it against the tool's schema (AG-11), and answers only within what the call's run specification (AG-17) allows from the snapshot it names (AG-10). It keeps nothing from one call that another run's call can read.
- Observable: The platform's list of containers shows exactly one shared tool service, every tool response a run receives came from it, and a value the service holds after answering one run's call is absent from another run's call to the same tool.
- On failure: A call the shared tool service cannot answer within its run specification is refused, and the refusal is recorded. The service does not answer it from another run's state.
- Verified by: A test that runs two runs at once, has one call a tool with values chosen to appear in a shared cache or index, and checks that the other run's calls to the same tool carry no trace of them.

**PL-21.** The shared tool service must answer every call from the snapshot named in the run specification, including a run that starts after a newer snapshot exists.
<!-- id: SDD-PL-21 | tdd: none | status: pending:#57 -->

- Trigger: The shared tool service (PL-20) receives a call, including one from a run that starts after a newer snapshot has been frozen.
- Behavior: The service reads the snapshot hash from the call's run specification (AG-17) and answers only from that snapshot (AG-10), including from any index it keeps over that snapshot, such as the one behind the neighbors of RD-06. It keeps every index keyed by snapshot hash and never serves one snapshot's index to a call naming another.
- Observable: A call naming an older snapshot hash returns a result drawn only from that snapshot's papers, even while a newer snapshot exists.
- On failure: A call whose named snapshot hash matches no snapshot the service holds is refused, and the refusal is recorded. It is not answered from a newer snapshot or from an index built over another.
- Verified by: A test that freezes a second snapshot with an added paper, then sends a call naming the first snapshot's hash, and checks that the added paper is absent from the result and from any neighbor index used to produce it.

### 2.2 Shared model service and compute

**PL-08.** The small models must be served by one shared service used by every agent run.
<!-- id: SDD-PL-08 | tdd: none | status: pending:#57 -->

- Trigger: The reader, or a tool that answers an agent run, needs an output of the encoder, the embedding model or the prediction heads.
- Behavior: One shared model service on the host holds the only copy of the small models loaded for serving and answers every such request. Every model output an agent run receives, on a paper card or in a tool's answer, came from that one service, and no run calls the service itself (SR-12).
- Observable: The platform's list of containers shows exactly one shared model service. Every number on a paper card that a small model produced carries the model id and model-state date (RD-02, RD-03) the service had loaded when it produced the number.
- On failure: When the shared model service is not healthy (PL-05), a request to it fails and the failure is recorded. No other component loads the small models in its place.
- Verified by: A test that starts several agent runs at once and fails when a second copy of the small models is loaded for serving on the host, when a model output a run received on a paper card or from a tool did not come from the shared model service, or when a call to the service from inside a run gets an answer.

**PL-09.** An agent run must not load model weights of its own.
<!-- id: SDD-PL-09 | tdd: none | status: pending:#57 -->

- Trigger: An agent run starts.
- Behavior: Every output of the small models that the run receives comes from the shared model service through paper cards and tools (PL-08), and the run reaches the agent model over its API (SR-12). Its container holds no model weights: none in its image and none on a volume attached to it.
- Observable: An inspection of the agent run image and of the volumes the definition (PL-03) attaches to it finds no model weights.
- On failure: An agent run image found to hold model weights is not run. An attempt from inside a run to read the volumes that hold checkpoints or prediction heads, or to fetch weights over the network (PL-19), is refused by the platform and recorded.
- Verified by: A test that, from inside an agent run container, tries to open the volumes that hold checkpoints and prediction heads and to fetch weights from an internet address, and checks that each attempt is refused. A check fails when the agent run image holds model weights.

**PL-10.** The host must meet a stated minimum of compute, memory, accelerator and storage before the system starts.
<!-- id: SDD-PL-10 | tdd: none | status: pending:#5 -->

- Trigger: The owner starts the system (PL-03).
- Behavior: Before any service or batch job starts, a floor check measures the host's processor, memory, accelerator and free storage and compares each with the stated minimum. The system starts only when all four meet it.
- Observable: A stored floor check record, written before any service starts, that lists the four measured values, the four minimums and pass or fail.
- On failure: When a value is below its minimum or cannot be measured, no service or batch job starts. The failed check is recorded with the value that fell short.
- Verified by: A test that sets a minimum above what the host has, starts the system, and checks that no service starts and that the record names the shortfall.
- Limits: The host floor numbers are not yet set (#6). They are sized by the shared model service under the full population and depend on where the system runs (#8) and on the count of parallel agent runs (#10). The compute for weekly training (#9) and whether training runs on the target hardware (#18) are held out with the encoder layer (SR-17, #51) and raise the floor when it enters.

### 2.3 Batch jobs

**PL-11.** Training and data preparation must run as batch jobs apart from the services that answer requests.
<!-- id: SDD-PL-11 | tdd: none | status: pending:#57 -->

- Trigger: A training or data preparation step comes due: prediction head fitting (FT-16), or any one-time build of a historical outcome set for a pre-fit prediction head.
- Behavior: Each such step runs as a batch job in a container of its own (PL-01) that starts for the job and ends with it. No service that answers requests does training or data preparation inside its own container.
- Observable: While a batch job runs, the platform's list of containers shows it apart from every service, and the job has a batch job record (PL-16).
- On failure: A batch job that fails ends with the failure in its record (PL-16), and its output is not promoted (PL-14). The services keep answering requests.
- Verified by: A test that starts each kind of batch job and fails when the work runs inside a service's container and not in a job container of its own.
- Limits: Whether the prediction heads start pre-fit, and so whether a historical outcome set is built at all, is open (#7).

**PL-12.** The daily cycle must continue while a batch job runs.
<!-- id: SDD-PL-12 | tdd: none | status: pending:#57 -->

- Trigger: A step of the daily cycle comes due while a batch job is running: ingest, issuing the batch, agent runs or resolution.
- Behavior: The step starts when it is due and completes without waiting for the batch job. Daily steps use the last accepted checkpoint and prediction heads (PL-13), so none of them depends on the running job (PL-17).
- Observable: The day's batch, run and resolution records in the ledger carry timestamps that fall between the recorded start and end of the batch job (PL-16).
- On failure: A daily step that cannot complete while a batch job runs is recorded as failed for that day. It is not held back until the batch job ends.
- Verified by: A test that starts a long batch job, runs a full daily cycle beside it, and fails when any daily step waits for the job to end or does not complete.
- Limits: Weekly fine-tuning of the encoder is held out of the first build (SR-17, #51), and the compute it runs on (#9) is settled with it. The requirement holds for every batch job the first build runs, and for weekly training when it enters, whether it shares the accelerator of the shared model service or uses another.

**PL-13.** The shared model service must keep serving the last accepted checkpoint and prediction heads until new ones are promoted.
<!-- id: SDD-PL-13 | tdd: none | status: pending:#57 -->

- Trigger: A batch job that produces new prediction heads is running, has failed, or has finished and is not yet promoted.
- Behavior: The shared model service keeps answering from the embedding model at its adopted checkpoint and the last accepted prediction heads. Nothing a batch job writes changes what the service serves before promotion (PL-14).
- Observable: The checkpoint date the service reports stays the one the embedding model was adopted with, and the stamps on the numbers it produces for paper cards (RD-02, RD-03) stay those of the last accepted prediction heads until new ones are promoted.
- On failure: If the service cannot serve the embedding model at its adopted checkpoint or the last accepted prediction heads, its health check fails (PL-05) and requests to it fail. It does not fall back to prediction heads that were not promoted.
- Verified by: A test that requests model outputs throughout a prediction-head fitting job and after a failed one, and fails when a response before promotion serves prediction heads other than the last accepted ones, or a checkpoint date other than the one the embedding model was adopted with.

**PL-14.** A new checkpoint or set of prediction heads must be promoted in one step, only after its job has finished and passed its checks.
<!-- id: SDD-PL-14 | tdd: none | status: pending:#57 -->

- Trigger: A batch job that produced a new set of prediction heads has finished (PL-16) and its output has passed its checks: the prediction heads were refit (FT-10) and calibrated (FT-11). While weekly encoder training is held out (SR-17), no batch job produces a new checkpoint to promote.
- Behavior: Promotion switches the shared model service from what it last accepted, whether a checkpoint, a set of prediction heads or both, to what is offered, in one step, and no request is answered from a mix of old and new.
- Observable: From one request to the next, the service reports the new prediction heads, while the checkpoint date it reports stays the one the embedding model was adopted with. The promotion is recorded.
- On failure: Output of a job that did not finish or did not pass a check is not promoted, and the refusal is recorded. A promotion that fails part way leaves the service on what it last accepted (PL-13).
- Verified by: A test that offers for promotion the output of an unfinished job and a set of prediction heads that is not calibrated, and checks that each is refused. A second test sends requests across a promotion and fails when a response mixes old and new.

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
<!-- id: SDD-PL-17 | tdd: none | status: pending:#57 -->

- Trigger: A step whose input is the output of a batch job comes due, in the weekly cycle (FT-16) or after any one-time data build.
- Behavior: The step starts only after the job's record (PL-16) shows finished, and reads the job's output only then.
- Observable: The step's start time is later than the end time in the job's record. A dependent step started earlier is refused.
- On failure: If the job fails or is interrupted, the dependent step does not start, and that is recorded. It starts after the job has been resumed (PL-15) and has finished.
- Verified by: A test that starts a dependent step while its job is still running, and again after the job has failed, and checks that the step is refused both times and reads nothing the job wrote.
- Limits: Whether the prediction heads start pre-fit on historical outcomes is open (#7). If they do, the first fit of the prediction heads is a step that depends on the build of the historical outcome set.

### 2.4 Storage and network

**PL-18.** Data that needs to outlive a container must be kept on volumes outside every container's own file system.
<!-- id: SDD-PL-18 | tdd: none | status: pending:#57 -->

- Trigger: A component writes data that is still needed after its container is replaced: the ledger, the corpus, raw responses, checkpoints, prediction heads, snapshots, and the records and saved states of batch jobs (PL-15, PL-16).
- Behavior: Such data is written to volumes that the definition (PL-03) names. A container's own file system holds nothing that is needed after the container is removed.
- Observable: After a container is removed and created again from its image, the data on its volumes is present and unchanged.
- On failure: A component whose volume is absent or cannot be written does not start, and the failure is recorded. It does not fall back to writing inside its container.
- Verified by: A test that removes and recreates every container and checks that the ledger's hash chain still verifies (EN-05) and that the corpus, raw responses, checkpoints, prediction heads and snapshots are unchanged.
- Limits: Where the system is built and run is open (#8), so where the volumes are stored is not settled. The requirement holds under each option.

**PL-19.** Network reach must be enforced for each container by the platform and not by the component inside it.
<!-- id: SDD-PL-19 | tdd: none | status: pending:#45 -->

- Trigger: A container is started, or a process inside a container opens a connection.
- Behavior: The definition (PL-03) states each container's reach: which containers and outside addresses it reaches, and, for the rating app, the network allowed to reach it (PL-22). The platform blocks everything else, applying the isolation rules of SR-12, SR-13 and PL-22 this way.
- Observable: A connection attempt outside a container's declared reach is refused by the platform, whatever the code inside the container does.
- On failure: A container whose reach rules cannot be applied does not start, and the failure is recorded. It does not start with open network reach.
- Verified by: A test that runs code inside an agent run container and inside a service container other than ingest, tries to reach an internet address and an undeclared container from each, and checks that the platform refuses every attempt.
- Limits: Where the system is built and run is open (#8), and the means of enforcement depends on the host. The requirement holds under each option.

**PL-22.** Raters must read the digest and record ratings through a private app on their phones, served from the host over a private network with no route from the internet.
<!-- id: SDD-PL-22 | tdd: none | status: pending:#45 -->

- Trigger: A rater opens the rating app on a phone to read the digest (EN-32) or record a rating.
- Behavior: The host serves the rating app only over a private network with no route from the internet, admitting a call only after it checks a credential naming the rater. The platform enforces that reach from outside the app, as it enforces every container's reach (PL-19), and the app's outbound side falls under SR-13.
- Observable: A call to the rating app from an address outside the private network gets no response, and what the app presents to a rater carries the label of IN-28.
- On failure: A call that carries no credential, or one the app does not recognize, is refused, and the refusal is recorded. The app does not serve the digest or accept a rating without it.
- Verified by: A test that calls the rating app from an address outside the private network, from the internet, and with no credential, and checks that each is refused, while a call from a rater's credential on the private network succeeds.
- Limits: The rating app sets the delivery path of the digest, which #6 lists as not yet set. How the app is built is decided with #43 and does not enter this requirement.

## 3. Infrastructure: measuring, output and observation

### 3.1 Scoring

**IN-01.** Scoring must be deterministic, so that the same ledger records always give the same score.
<!-- id: SDD-IN-01 | tdd: none | status: pending:#57 -->

- Trigger: The scorer computes a score.
- Behavior: The scorer computes the score as a function of ledger records and of nothing else. It reads sealed forecasts, the baselines' among them (IN-07 to IN-09), and the results that stand for them (EN-04, IN-12), makes no random draw and calls no language model (SR-03).
- Observable: Running the scorer again over the same ledger records gives a recorded score identical to the first.
- On failure: When a record the scorer reads is missing or unreadable, the scorer stops, records the failure and writes no score.
- Verified by: A test that runs the scorer twice over one fixed set of ledger records, the second time at a later time and with no stored data but those records in its reach, and checks that every score is identical. It catches a score that depends on when the scorer runs, on a random draw or on anything outside the ledger.

**IN-02.** Scoring must not require understanding the paper: the scorer reads forecasts and outcomes and never paper content.
<!-- id: SDD-IN-02 | tdd: none | status: pending:#57 -->

- Trigger: The scorer reads its inputs.
- Behavior: The scorer reads sealed forecasts, the baselines' among them, and the results that stand for them, in which a paper appears only as an id. It has no interface (PL-02) to paper text, figures, tables or paper cards.
- Observable: The scorer's declared interfaces name no source of paper content, and a request from the scorer for paper content is refused.
- On failure: When a score cannot be computed from the permitted inputs, the scorer records the failure and writes no score. It does not turn to paper content.
- Verified by: A test that scores one fixed set of ledger records twice, the second time with all paper content removed, and checks that the scores are identical. It catches a scorer that reads paper content.

**IN-03.** Scoring must not count an unresolved forecast against a genome before its horizon, including forecasts about papers with delayed recognition.
<!-- id: SDD-IN-03 | tdd: none | status: pending:#57 -->

- Trigger: The scorer scores a genome that has sealed forecasts with no resolver result.
- Behavior: Before a forecast's horizon the scorer counts the forecast as neither true nor false (EN-04), so the forecast adds no penalty. A forecast's result, and so any penalty for a forecast that settles false, comes no earlier than its horizon (EN-02).
- Observable: Apart from the pick-set non-overlap score (IN-04), a genome's score computed before a forecast's horizon is the same with that forecast in the ledger and without it.
- On failure: When the scorer cannot establish whether a forecast's horizon has passed, it stops, records the failure and writes no score.
- Verified by: A test that adds a sealed forecast whose horizon has not passed to a genome's records and checks that the genome's score, apart from the pick-set non-overlap score (IN-04), does not change. It catches a scorer that counts an unresolved forecast as false.
- Limits: How early is too early to count an unresolved forecast against a genome is not yet set (#6). This requirement fixes only that it is never before the forecast's horizon.

**IN-04.** Scoring must include a pick-set non-overlap score equal to one minus the overlap with the obvious baseline's picks.
<!-- id: SDD-IN-04 | tdd: none | status: pending:#57 -->

- Trigger: The scorer scores a genome's forecasts on a forecast batch.
- Behavior: The obvious baseline is the picks of the paper-discovery services captured by ingest (EN-38). The scorer computes the overlap between the papers the genome picked on the batch and the papers that baseline picked on the same batch, and records one minus that overlap as the genome's pick-set non-overlap score.
- Observable: A pick-set non-overlap score recorded with each genome's score.
- On failure: When the obvious baseline's picks for the batch are missing, the scorer records the term as not computed and writes no value for it.
- Verified by: A test that scores a genome whose picks equal the obvious baseline's and checks that the term is 0, and a genome that shares no pick with it and checks that the term is 1. It catches a term that rewards agreement with the baseline.
- Limits: Whether the pick-set non-overlap score enters fitness (FT-12) is not yet set (#6). What a pick is, for a genome and for a baseline, is not yet set (#6).

**IN-05.** The scorer must flag a genome whose forecast probabilities cluster at one value.
<!-- id: SDD-IN-05 | tdd: none | status: pending:#57 -->

- Trigger: The scorer scores a genome.
- Behavior: The scorer applies the clustering test to the forecast probabilities of the genome's sealed forecasts. When the test is met, it records a flag against the genome hash.
- Observable: A recorded flag that names the genome hash.
- On failure: When the test cannot be computed, the scorer records that it was not computed and records no flag.
- Verified by: A test that scores one genome whose forecasts all carry the same forecast probability and one whose forecast probabilities are spread from 0 to 1, and checks that only the first is flagged. It catches a scorer that never flags or that flags every genome.
- Limits: The test for forecast probabilities clustering at one value is not yet set (#6).

**IN-06.** Measuring must produce a reliability diagram per genome.
<!-- id: SDD-IN-06 | tdd: none | status: pending:#57 -->

- Trigger: The report step of the weekly cycle runs (FT-16).
- Behavior: For each genome, measuring groups the forecasts settled true or false by their stated forecast probability and sets each group's forecast probability against the share of its forecasts that settled true. The result is stored as that genome's reliability diagram.
- Observable: One stored reliability diagram for each genome that has resolved forecasts, named by genome hash.
- On failure: A genome with no forecasts settled true or false gets no diagram, and the report states that. No diagram is drawn from unresolved forecasts.
- Verified by: A test that supplies resolved forecasts with known forecast probabilities and outcomes and checks the diagram's points against shares computed by hand. It catches a diagram that includes unresolved forecasts or another genome's forecasts.

### 3.2 Baselines

**IN-07.** A popularity baseline that agents have to beat must answer every forecast batch and be scored by the same scorer.
<!-- id: SDD-IN-07 | tdd: none | status: pending:#57 -->

- Trigger: A forecast batch is sealed (EN-10).
- Behavior: The popularity baseline gives a forecast probability for each question from the counts taken at the batch's snapshot, the authors' prior citation counts and the paper's early repository and Hugging Face counts (RD-12). Its answers are sealed in the ledger as forecasts (EN-03) and scored by the function the scorer applies to genomes (FT-12).
- Observable: The baseline's sealed forecasts for each batch in the ledger, and a recorded score for the baseline beside the genomes' scores.
- On failure: When none of those counts was taken at the snapshot, the baseline records no answers for that batch and the gap is recorded. No answer is added once the batch's outcomes begin to exist.
- Verified by: A test that offers the baseline a count captured after the batch was issued and checks that it is refused, and that checks the baseline's answers are sealed before the batch's outcomes. It catches a baseline that sees outcomes or later data.
- Limits: Whether any source gives live arXiv download counts is open (#22), and this requirement holds whichever of the snapshot counts a source supports.

**IN-08.** A base-rate baseline that agents have to beat must answer every forecast batch and be scored by the same scorer.
<!-- id: SDD-IN-08 | tdd: none | status: pending:#57 -->

- Trigger: A forecast batch is sealed (EN-10).
- Behavior: The base-rate baseline gives, for each question, the rate at which earlier questions resolved true, computed only from outcomes whose resolution was recorded before the batch was sealed (IN-35). Its answers are sealed in the ledger as forecasts (EN-03) and scored by the function the scorer applies to genomes (FT-12).
- Observable: The baseline's sealed forecasts for each batch in the ledger, and a recorded score for the baseline beside the genomes' scores.
- On failure: When no outcome resolved before the batch was sealed, the baseline records no answers for that batch and the gap is recorded.
- Verified by: A test that builds a ledger with a known share of true outcomes and checks that the baseline's forecast probability equals that share, and that an outcome resolved after the batch was sealed does not change it. It catches a base rate that draws on outcomes later than the batch.
- Limits: The reference class of the base rate, all earlier questions or each kind of question and horizon, is not yet set (#6).

**IN-09.** A plain regression over paper card features that agents have to beat must answer every forecast batch and be scored by the same scorer.
<!-- id: SDD-IN-09 | tdd: none | status: pending:#54 -->

- Trigger: A forecast batch is sealed (EN-10).
- Behavior: A plain regression, fitted on the fixed paper card fields of papers whose outcomes were recorded as resolved before the batch was sealed (IN-35), gives a forecast probability for each question from the paper cards in the batch's snapshot. Jev assessments and their confidence or availability fields are excluded from these inputs. Its answers are sealed in the ledger as forecasts (EN-03) and scored by the function the scorer applies to genomes (FT-12).
- Observable: The baseline's sealed forecasts for each batch in the ledger, and a recorded score for the baseline beside the genomes' scores.
- On failure: When the regression cannot be fitted, or a paper card lacks one of the fixed fields, the baseline records no answer for the affected questions and the gap is recorded.
- Verified by: A test that checks the regression's inputs against the fixed paper card fields and the batch's snapshot, and that an outcome resolved after the batch was sealed does not change its answers. A second test changes only Jev fields and checks that baseline inputs and answers stay unchanged. It catches a baseline that reads beyond the paper card or fits on later outcomes.
- Limits: The paper card fields the plain regression uses are not yet set (#6).

**IN-33.** A nearest-neighbor baseline that agents have to beat must answer every forecast batch and be scored by the same scorer.
<!-- id: SDD-IN-33 | tdd: none | status: pending:#57 -->

- Trigger: A forecast batch is sealed (EN-10).
- Behavior: The nearest-neighbor baseline gives a forecast probability for each question from the neighbor outcomes the paper card holds (RD-11), which cover only earlier neighbors and only outcomes resolved before the snapshot. Its answers are sealed in the ledger as forecasts (EN-03) and scored by the function the scorer applies to genomes (FT-12).
- Observable: The baseline's sealed forecasts for each batch in the ledger, and a recorded score for the baseline beside the genomes' scores.
- On failure: When a paper card holds no earlier neighbor with an outcome resolved before the snapshot, the baseline records no answer for the affected questions and the gap is recorded.
- Verified by: A test that gives a paper one neighbor whose outcome resolved after the snapshot and one that arrived later than the paper, and checks that neither changes the baseline's forecast probability. It catches a forecast drawn from later neighbors or later outcomes.
- Limits: The count of neighbors and the measure of nearness are those of RD-06 and are not yet set (#6). How the neighbors' outcomes become one forecast probability is not yet set (#6).

**IN-34.** The mean of the genomes' forecast probabilities must answer every forecast batch as a forecaster of its own and be scored by the same scorer.
<!-- id: SDD-IN-34 | tdd: none | status: pending:#57 -->

- Trigger: The genomes' forecasts on a forecast batch are sealed (EN-03).
- Behavior: For each question on the batch the mean of the forecast probabilities the genomes sealed for it is computed and sealed in the ledger as a forecast (EN-03) under its own submitter. The scorer scores it with the function it applies to genomes (FT-12), and it takes no part in selection.
- Observable: The mean forecaster's sealed forecasts for each batch in the ledger, and a recorded score for it beside the genomes' and the baselines' scores.
- On failure: When no genome sealed a forecast probability for a question, the mean records no answer for that question and the gap is recorded.
- Verified by: A test that seals known genome forecast probabilities and checks that the mean's sealed forecast probability equals their arithmetic mean, that it is sealed before the batch's outcomes, and that the fitness values selection reads are the same with it and without it. It catches a mean computed after the outcomes or fed into selection.

**IN-35.** A baseline must answer a forecast batch only from information captured before that batch was sealed.
<!-- id: SDD-IN-35 | tdd: none | status: pending:#57 -->

- Trigger: A baseline (IN-07 to IN-09, IN-33) prepares its answers for a forecast batch.
- Behavior: Every input a baseline reads carries the date it was captured, and the baseline uses only inputs captured before the batch's seal record (EN-10). A service pick captured after that moment (EN-38) counts for no question on that batch.
- Observable: The recorded inputs behind a baseline's sealed answers each carry a capture date earlier than the batch's seal record.
- On failure: When an input carries no capture date, or one later than the seal, the baseline leaves it out, records no answer for the questions that depend on it alone, and records the left-out input with the capture date it carries, if any.
- Verified by: A test that captures a service pick after a batch was sealed and checks that the baseline's answers for that batch are unchanged and that the late pick is recorded as left out. It catches a baseline filled in from information captured after the seal.

### 3.3 Human rating and review

**IN-10.** Human raters must rate the papers the system surfaces.
<!-- id: SDD-IN-10 | tdd: none | status: pending:#45 -->

- Trigger: A digest is delivered to the raters (EN-32).
- Behavior: Each rater rates each paper in the digest as like, dislike or skip, in a rating view that hides the genome and the random controls (SR-21, SR-22). The system stores each rating against the rater, the paper, the digest entry and the time it was given.
- Observable: A stored rating of like, dislike or skip for each paper a rater has rated, carrying the rater, the paper, the digest entry and the time, and every other pairing of a paper in a digest and a rater shows as unrated.
- On failure: A rating that cannot be stored is shown to the rater as not saved and the paper stays unrated. No rating is filled in on a rater's behalf.
- Verified by: A test that delivers a digest, submits a like, a dislike and a skip for some papers and checks each is stored as given, against the right rater, paper, digest entry and time, with others unrated. It catches ratings that are lost, misattached, given the wrong value or filled in by default.

**IN-11.** A human must spot-check a random sample of forecasts for whether the cited evidence supports the forecast.
<!-- id: SDD-IN-11 | tdd: none | status: pending:#57 -->

- Trigger: The sampling step draws a spot-check sample from the sealed forecasts.
- Behavior: The system draws the sample at random, shows each sampled forecast with its cited evidence in a review view, and stores the human's verdict on whether the evidence supports the forecast. The human does not choose which forecasts are sampled.
- Observable: A record of the forecasts drawn, and a stored verdict against each one that has been checked.
- On failure: A sampled forecast with no verdict stays recorded as unchecked. It is not swapped for another forecast.
- Verified by: A test that draws a sample from a fixed set of forecasts and checks that the recorded draw matches the forecasts shown, and that a sampled forecast left without a verdict still appears as unchecked. It catches hand-picked samples and forecasts dropped without a trace.
- Limits: The size of the spot-check sample is not yet set (#6).

**IN-12.** When a human rater and a resolver disagree, the human's judgment must stand.
<!-- id: SDD-IN-12 | tdd: none | status: pending:#57 -->

- Trigger: A rater records a judgment of a forecast's outcome that differs from the resolver's result for that forecast.
- Behavior: The rater's judgment is appended to the ledger as the forecast's standing result and marks the resolver's result as superseded, and the resolver's record stays in the ledger unchanged (SR-14, SR-19). The scorer uses the standing result.
- Observable: A ledger record of the rater's judgment that refers to the resolver's result, and scores computed afterwards that follow the rater's judgment.
- On failure: When the rater's judgment cannot be appended, the resolver's result remains the standing result and the failure is recorded. No existing record is edited.
- Verified by: A test that records a rater's judgment opposite to a resolver's result and checks that the scorer uses the rater's judgment and that the resolver's record is still present and unchanged. It catches a resolver result that is overwritten and a human judgment that is ignored.
- Limits: Where a rater records a judgment of a forecast's outcome is not yet set (#6). What stands when the two raters disagree with each other is not yet set (#6), and the behavior above does not cover that case.

**IN-13.** A resolver that disagreed with a human rater must be reviewed.
<!-- id: SDD-IN-13 | tdd: none | status: pending:#57 -->

- Trigger: A disagreement is recorded under IN-12.
- Behavior: The system opens a resolver review record that names the resolver, its version (EN-08) and the forecast. The review is human work, and its conclusion is recorded against that record when it is done.
- Observable: One open resolver review record for each recorded disagreement, and the conclusion on each review that has been closed.
- On failure: When the resolver review record cannot be written, the failure is recorded. The system closes no review by itself.
- Verified by: A test that records a disagreement and checks that a resolver review record naming the resolver and its version exists and stays open until a human conclusion is recorded. It catches a disagreement that leaves no trace against the resolver.

**IN-36.** The rating app must show, for an entry a rater has already rated, what each run recorded about that paper: its forecast probability, its cited evidence and its structured output schema fields, rendered without a language model.
<!-- id: SDD-IN-36 | tdd: none | status: pending:#57 -->

- Trigger: A rater opens, in the rating app, an entry the rater has already rated.
- Behavior: The rating app renders each run's forecast probability, cited evidence and structured output schema fields (AG-32, AG-33) directly from its ledger record, with no language model summarizing them, in the same view IN-11 reads for spot-check. The view hides what SR-21 and SR-22 hide from a rater.
- Observable: The entry's detail view lists the forecast probability, the cited evidence and the structured output schema fields the ledger holds for every run that surfaced the paper, matching the stored record.
- On failure: When a run's record cannot be rendered, the detail view shows that the run's detail is unavailable, and no field is filled in from elsewhere.
- Verified by: A test that rates an entry, opens its detail view and checks that each run's forecast probability, evidence and structured output schema fields match its ledger record, with no language model producing them, and that the view hides what SR-21 and SR-22 hide. It catches a view that invents or summarizes a run's record, or leaks the genome or the controls.
- Limits: What a run recorded is not always what drove its forecast probability (IN-32).

**IN-37.** The detail view must show each forecast's verdict once it resolves, beside the baselines' answers to the same question.
<!-- id: SDD-IN-37 | tdd: none | status: pending:#57 -->

- Trigger: A rater opens, in the rating app, an entry already rated under IN-10, once one of the paper's forecasts has resolved (EN-04).
- Behavior: The detail view shows each forecast's verdict (EN-04) beside the baselines' answers to the same question (IN-07, IN-08, IN-09, IN-33), once the forecast has resolved. A forecast or a baseline answer that has not resolved shows as unresolved rather than take a value from elsewhere.
- Observable: The detail view of a rated entry lists, for each of the paper's resolved forecasts, its verdict next to each baseline's answer to that question, and shows an unresolved forecast or baseline answer as unresolved.
- On failure: When a forecast's verdict or a baseline's answer cannot be read, the detail view shows that value as unavailable and still shows the rest.
- Verified by: A test that resolves some of a rated entry's forecasts and baseline answers, leaves others unresolved, opens the detail view and checks that each resolved verdict appears beside the matching baseline answers and each unresolved one shows as unresolved. It catches a view that fills in an unresolved verdict or omits a baseline's answer.

### 3.4 Statistics and reporting

**IN-14.** The forecast must be the unit of statistical analysis.
<!-- id: SDD-IN-14 | tdd: none | status: pending:#57 -->

- Trigger: A comparison between genomes, or between a genome and one of the baselines, is computed.
- Behavior: Every statistic in the comparison is computed over individual resolved forecasts. Forecasts are not first averaged by run, day, paper or genome and then counted as one observation each.
- Observable: Each reported comparison gives the count of forecasts on each side.
- On failure: A comparison with no resolved forecasts on one side is not computed, and that is recorded.
- Verified by: A test that computes a comparison over forecasts spread unevenly across runs and checks that the result equals the value computed by hand over forecasts and differs from the average over runs. It catches analysis that treats the run or the day as the unit.

**IN-15.** Comparisons must report bootstrap intervals.
<!-- id: SDD-IN-15 | tdd: none | status: pending:#57 -->

- Trigger: A comparison is computed.
- Behavior: One resampling routine, shared by all comparisons, resamples forecasts (IN-14) and gives an interval for the difference in the comparison's primary measure (IN-17).
- Observable: Each reported comparison gives the difference together with its interval.
- On failure: When the routine cannot produce an interval, the comparison is reported as having none and gets no verdict. The difference is not reported as a win or a loss.
- Verified by: A test that runs the routine over synthetic forecasts with a known difference and checks that the interval covers it, and a check that no reported comparison lacks an interval. It catches a comparison reported as a bare difference.
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
<!-- id: SDD-IN-18 | tdd: none | status: pending:#57 -->

- Trigger: A report is produced.
- Behavior: The report accounts for every run that was issued a run specification in the span it covers, with each run's state. Void runs (AG-15), failed runs and quarantined runs (AG-22) are included.
- Observable: The count of runs in the report equals the count of run specifications issued in the same span, and each run appears with its state.
- On failure: When the report cannot account for every run specification, it is not issued and the failure is recorded.
- Verified by: A test that plants a void run and a failed run and checks that the report lists both and that its count of runs matches the run specifications issued. It catches a report that shows only completed or favorable runs.

**IN-38.** Each prediction head's calibration and discrimination must be measured on outcomes that resolved after its fit and reported for each prediction head version.
<!-- id: SDD-IN-38 | tdd: none | status: pending:#57 -->

- Trigger: The report step of the weekly cycle runs (FT-16), for a prediction head that has outcomes resolved after its fit date.
- Behavior: Measuring compares each prediction head's probability for a paper (RD-08) against the paper's resolved outcome, over outcomes that resolved after the prediction head's fit date (RD-03), and computes the prediction head's calibration and discrimination from that set. It reports the result for each prediction head version, named by that fit date.
- Observable: Each report gives a calibration and discrimination result for each prediction head that has an outcome resolved after its fit date, named by that date.
- On failure: A prediction head with no outcome resolved after its fit date gets no result for that cycle, and the report states that.
- Verified by: A test that supplies a prediction head's probabilities with outcomes that resolved both before and after its fit date, and checks that only the outcomes that resolved after enter the computed result. It catches a result computed from outcomes known before the prediction head was fit.
- Limits: The discrimination measure is not yet set (#6). This measure differs from the held-out set the prediction head is calibrated on at refit (FT-11), which uses outcomes already known at fit time.

**IN-39.** Each resolver's error rate must be measured from the spot checks and the raters' judgments and reported for each resolver version.
<!-- id: SDD-IN-39 | tdd: none | status: pending:#57 -->

- Trigger: The report step of the weekly cycle runs (FT-16), for a resolver version with a spot-checked forecast or a reviewed disagreement in the span.
- Behavior: Measuring reports, for each resolver version recorded in the ledger (EN-08), the share of the spot-checked forecasts (IN-11) and reviewed disagreements (IN-12, IN-13) settled by that version in which the human verdict goes against the resolver's result, together with the count of instances it draws on.
- Observable: Each report gives that share and that count for each resolver version with an instance in the span.
- On failure: A resolver version with no spot-checked forecast and no reviewed disagreement in the span gets no share, and the report states that.
- Verified by: A test that stores a known set of spot-check verdicts and disagreement reviews naming two resolver versions and checks that each version's reported share and count match its own instances alone. It catches a rate that mixes instances across resolver versions.
- Limits: What counts as the human verdict going against the resolver's result, for a spot-checked forecast whose verdict addresses evidence support rather than the resolver's true or false result, is not yet set (#6).

**IN-40.** Every report that compares agents with a service-derived baseline on an online attention outcome must name the overlap between the service that made the picks and the service the outcome is read from.
<!-- id: SDD-IN-40 | tdd: none | status: pending:#57 -->

- Trigger: The report step of the weekly cycle runs (FT-16), for a comparison of agents' skill (FT-12) against a baseline whose picks come from a discovery service, on a question whose outcome is an online attention track count (EN-21 to EN-23).
- Behavior: Measuring names, beside that comparison, the discovery service that supplied the baseline's picks and the service the online attention outcome is read from, whether the two are the same service or different ones.
- Observable: Each such reported comparison shows both service names beside its result.
- On failure: When the service that supplied the baseline's picks cannot be identified, the report states that and the comparison is not shown.
- Verified by: A test that builds one comparison whose baseline picks and whose online attention outcome come from the same service, and one where they come from different services, and checks that both reports name the two services. It catches a report that shows the comparison with no service named.
- Limits: Which baseline counts as service-derived, and how the two tracks count toward fitness, is not yet set (#11).

**IN-41.** The system must report, for each paper of the arXiv stream that a discovery service later picks, whether a genome had already given it a forecast probability above a threshold written down beforehand, and how many days earlier.
<!-- id: SDD-IN-41 | tdd: none | status: pending:#57 -->

- Trigger: Ingest captures a service pick for a paper of the arXiv stream (EN-38).
- Behavior: Measuring finds, among the forecast probabilities a genome gave the paper before the pick's capture date, the earliest one that crossed the threshold written down beforehand for this comparison (SR-18), and reports how many days before the capture date it was given.
- Observable: For each paper a discovery service picks, the report gives the count of days a genome's forecast probability led the pick, or states that no genome crossed the threshold before it.
- On failure: When the paper's history of forecast probabilities cannot be read, the report states that and gives no value for that paper.
- Verified by: A test that gives one genome a forecast probability above the threshold before the capture date and one only after, and checks that the report counts days for the first and states none for the second. It catches a report that counts a forecast probability given after the pick.
- Limits: Which discovery services count for this comparison is not yet set (#6).

### 3.5 Operations

**IN-19.** A kill switch outside the system's own processes must halt all runs.
<!-- id: SDD-IN-19 | tdd: none | status: pending:#57 -->

- Trigger: The owner operates the kill switch.
- Behavior: The kill switch stops every run in progress and blocks new runs from starting. It acts from outside the system's own processes and is able to stop any of them, so it works when they do not respond.
- Observable: After the kill switch is operated, no run is in progress, no new run specification is issued, and a record of the halt and its time exists.
- On failure: When a process does not stop, the kill switch reports the halt as incomplete and names the process. It does not report a complete halt.
- Verified by: A test that starts runs, makes the system's own processes unresponsive, operates the kill switch and checks that every run stops and none starts. It catches a kill switch that depends on the processes it is meant to stop.

**IN-20.** The kill switch must restore the last accepted state.
<!-- id: SDD-IN-20 | tdd: none | status: pending:#57 -->

- Trigger: The kill switch has halted all runs (IN-19).
- Behavior: The kill switch puts back the population, the checkpoint and the prediction heads from the saved copy of the last accepted state, which the system keeps each time a new state is accepted. The ledger is not rolled back (SR-14).
- Observable: After the restore, the population, the checkpoint and the prediction heads in service are identical to the saved copy of the last accepted state, and the restore is recorded.
- On failure: When the saved copy is missing or incomplete, the restore stops, the system stays halted and the failure is recorded. No partly restored state goes into service.
- Verified by: A test that accepts a state, changes the population and the prediction heads, operates the kill switch and checks that what is restored is identical to the saved copy and that no ledger record is lost. It catches a restore that was never exercised, a partial restore and a restore that rewrites the ledger.

**IN-21.** Operational alerts must reach the owner the same day.
<!-- id: SDD-IN-21 | tdd: none | status: pending:#57 -->

- Trigger: A component raises an operational alert.
- Behavior: The system delivers the flag to the owner in the rating app on the day it is raised. It records when the flag was raised and when it was delivered.
- Observable: For each operational alert, a record of the time raised and the time delivered, both on the same day.
- On failure: When the flag cannot be delivered, it is recorded as not delivered. It is not recorded as delivered and it is not dropped.
- Verified by: A test that raises a flag and checks for a delivery record dated the same day, and that raises one with the rating app unavailable and checks that it is recorded as not delivered. It catches a flag that is written to a log and delivered to nobody.
- Limits: The channel that carries operational alerts is the rating app, and SR-13 applies to it. What raises an operational alert, and whether the flag of IN-05 is one, is not yet set (#6).

**IN-22.** An operational alert left unread must itself be recorded.
<!-- id: SDD-IN-22 | tdd: none | status: pending:#57 -->

- Trigger: An operational alert delivered to the owner (IN-21) has not been acknowledged by a rater in the rating app.
- Behavior: The system writes an unread record that names the flag. The record is separate from the flag and stays until a rater acknowledges the flag in the rating app, which counts as the flag having been read.
- Observable: One unread record for each delivered flag that has not been acknowledged in the rating app.
- On failure: When the rating app cannot say whether a flag was acknowledged, the flag is recorded as unread. It is not taken as read.
- Verified by: A test that delivers two flags, acknowledges one in the rating app and checks that an unread record exists for the other alone. It catches a system that treats a delivered flag as a read flag.
- Limits: The channel is that of IN-21, and SR-13 applies to it.

**IN-23.** Text retrieved from papers must be treated as untrusted input.
<!-- id: SDD-IN-23 | tdd: none | status: pending:#57 -->

- Trigger: The reader puts paper text on a paper card, or a deep read returns paper text to the agent model.
- Behavior: Paper text reaches the agent model only as data inside a paper card or a deep-read result, apart from the prompt. Nothing in paper text changes a run's tools, budgets, prompt or run specification, and no component carries out an instruction found in it.
- Observable: A run fed a paper that contains instructions ends with the same tools, budgets and run specification it started with, and every tool call it made fits the strict schemas (AG-11).
- On failure: When paper text cannot be kept apart from the prompt, it is withheld from the agent model and the failure is recorded.
- Verified by: A test that plants a paper whose text tells the agent to call a tool outside its run specification and to exceed its budgets, and checks that neither happens and that the run's forecasts are scored as any others are. It catches paper text that takes effect as an instruction.

**IN-24.** Prompts and run specifications must be read-only to agents.
<!-- id: SDD-IN-24 | tdd: none | status: pending:#57 -->

- Trigger: A run starts.
- Behavior: The run is able to read its prompt and its run specification and has no means of writing to either, or to those of any other run. A prompt changes only through mutation (AG-20), outside any run.
- Observable: A write to a prompt or a run specification attempted from inside a run is refused and the refusal is recorded. The genome hash and the run specification are the same at the end of the run as at its start.
- On failure: When the read-only permission cannot be applied, the run does not start and the failure is recorded.
- Verified by: A test in which a run attempts to write to its prompt and to its run specification through every tool it holds, and which checks that each attempt is refused and both are unchanged. It catches a run that edits its own instructions or budgets.

**IN-42.** A periodic check must walk a random sample of scores back to their raw inputs through the recorded provenance and report every break.
<!-- id: SDD-IN-42 | tdd: none | status: pending:#45 -->

- Trigger: The periodic check comes due on its schedule.
- Behavior: The check draws a random sample of recorded scores (IN-01) and, for each, follows its recorded provenance stamps (SR-23) through the ledger's hash chain (EN-05), anchored outside the system (SR-16), back from the score to the raw inputs it was computed from. It runs apart from the services that answer requests.
- Observable: A stored report that names the sample drawn, and for each score in it, either that the walk reached its raw inputs intact or the point at which it broke.
- On failure: When a score's walk cannot be completed, the break is recorded in the report and the score stays as recorded. The check corrects nothing it finds.
- Verified by: A test that alters a raw input behind one recorded score in a copy of the records, runs the check, and checks that the report names that score as broken and no other score as broken. It catches a check that samples scores but never compares them against their raw inputs.
- Limits: The schedule of the periodic check and the size of its random sample are not yet set (#6). This requirement rests on open issue #32 and holds under how that issue is decided.

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
<!-- id: SDD-IN-28 | tdd: none | status: pending:#57 -->

- Trigger: The system produces a digest or a report.
- Behavior: Every digest and every report carries a label that says its content is the output of an automated system and is not a scientific claim authored by anyone. Forecasts are worded as dated predictions with a forecast probability and not as findings.
- Observable: The label on every delivered digest and every stored report.
- On failure: A digest or a report that lacks the label is not delivered or stored, and the failure is recorded.
- Verified by: A test that builds a digest and a report without the label and checks that delivery and storing are refused, and that checks the label on ones built normally. It catches output that reads as a person's finding.

### 3.7 Known weaknesses to avoid

**IN-29.** The system must measure and report its accuracy on timing against chance, to avoid near-chance accuracy on timing, a weakness reported of published systems.
<!-- id: SDD-IN-29 | tdd: none | status: pending:#57 -->

- Trigger: The report step of the weekly cycle runs (FT-16).
- Behavior: Measuring computes the timing measure over resolved forecasts for each genome. It reports each value beside the value that chance gives on the same forecasts, and beside the lead-time report of IN-41 for the span the report covers.
- Observable: Each report gives the timing measure for each genome beside the chance value, and the lead-time report of IN-41 for the span it covers.
- On failure: When the measure cannot be computed, the report states that and gives no value.
- Verified by: A test that supplies resolved forecasts whose timing is right at the chance rate and checks that the report shows the measure equal to the chance value beside it. It catches a report that leaves timing out or shows timing with no chance value to read it against.
- Limits: The timing measure is not yet set (#6). The cited weakness carries no verification date yet (SR-20).

**IN-30.** The system must measure and report the calibration of each genome's forecast probabilities, to avoid overconfidence, a weakness reported of published systems.
<!-- id: SDD-IN-30 | tdd: none | status: pending:#57 -->

- Trigger: The report step of the weekly cycle runs (FT-16).
- Behavior: Measuring reports each genome's reliability diagram (IN-06), in which overconfidence shows as a share of forecasts settled true that lies below the stated forecast probability. The prediction heads are calibrated separately (FT-11).
- Observable: Each report gives the reliability diagram of each genome that has resolved forecasts.
- On failure: A genome with no forecasts settled true or false gets no diagram, and the report states that.
- Verified by: A test that supplies forecasts stated at a high forecast probability, of which a known smaller share settled true, and checks that the genome's diagram in the report shows that share below the stated forecast probability. It catches a report that gives accuracy alone.
- Limits: The cited weakness carries no verification date yet (SR-20).

**IN-31.** The system must measure and report the spread of topics among the papers it surfaces, to avoid bias toward mainstream topics, a weakness reported of published systems.
<!-- id: SDD-IN-31 | tdd: none | status: pending:#5 -->

- Trigger: The report step of the weekly cycle runs (FT-16).
- Behavior: Measuring computes the measure of topic spread over the papers surfaced in the span the report covers and reports its value.
- Observable: Each report gives the value of the measure of topic spread for the surfaced papers.
- On failure: When no paper was surfaced in the span, or the measure cannot be computed, the report states that and gives no value.
- Verified by: A test that supplies one set of surfaced papers drawn from a single topic and one spread evenly across topics, and checks that the reported value is lower for the first. It catches a report that leaves topic spread out and a measure that does not move with it.
- Limits: The measure of topic spread is not yet set (#6). The cited weakness carries no verification date yet (SR-20).

**IN-32.** The system must report the share of spot-checked forecasts whose cited evidence does not support the forecast, to avoid cited evidence that does not drive the prediction, a weakness reported of published systems.
<!-- id: SDD-IN-32 | tdd: none | status: pending:#57 -->

- Trigger: The report step of the weekly cycle runs (FT-16).
- Behavior: Measuring reports the share of spot-checked forecasts whose stored verdict (IN-11) is that the cited evidence does not support the forecast, with the count of forecasts checked.
- Observable: Each report gives that share and that count.
- On failure: When no verdict exists for the span, the report states that and gives no share. Sampled forecasts still unchecked are counted as unchecked and not as supported.
- Verified by: A test that stores a known set of verdicts, leaves some sampled forecasts unchecked and checks that the reported share and count match the verdicts alone. It catches a report that counts unchecked forecasts as supported.
- Limits: The spot check is the only probe specified, and it shows whether evidence supports a forecast, not whether the evidence drove it. The cited weakness carries no verification date yet (SR-20).

## 4. Environment

### 4.1 Corpus and time

**EN-01.** The corpus must consist of the papers in the arXiv categories cs.AI and cs.LG.
<!-- id: SDD-EN-01 | tdd: none | status: pending:#5 -->

- Trigger: Ingest runs its daily fetch of new papers from arXiv.
- Behavior: Ingest adds to the corpus the new papers in cs.AI and cs.LG, and adds no paper that is in neither category. The corpus has no other source of papers.
- Observable: Every paper in the corpus has a stored arXiv record that lists cs.AI or cs.LG among its categories.
- On failure: When the fetch does not complete, no paper from it enters the corpus, the corpus stays as it was and the failure is recorded.
- Verified by: A test that offers ingest a paper listed in neither category and checks that the paper is absent from the corpus afterwards.
- Limits: The daily volume of new papers in the two categories has not been measured (#19).

**EN-02.** The system must run live and forward-only, with every forecast sealed before its outcome exists and settled only by outcome data ingested after it was sealed.
<!-- id: SDD-EN-02 | tdd: none | status: pending:#57 -->

- Trigger: A forecast is sealed, and later its horizon passes.
- Behavior: Ingest, sealing, resolution and scoring run on the calendar, and a horizon is real time elapsed from sealing. A resolver settles a forecast only from outcome data that ingest brought in after the forecast's sealing timestamp.
- Observable: No resolution record in the ledger is earlier than the end of its forecast's horizon. The outcome data it cites as evidence was ingested after the forecast record was written.
- On failure: A forecast whose resolver finds no outcome data ingested after sealing is not settled true or false. The result is unresolvable under EN-14.
- Verified by: A test that tries to resolve a forecast before its horizon and checks that no resolution record is written. A test that offers a resolver only data ingested before the forecast was sealed and checks that the result is unresolvable.

**EN-35.** The reader and the tools must read only the version of a paper that was current when its batch's snapshot was frozen, never a later revision.
<!-- id: SDD-EN-35 | tdd: none | status: pending:#57 -->

- Trigger: A batch's snapshot is frozen (AG-10), or the reader produces a paper card (RD-01) or a tool reads a paper's source (MD-11) from that snapshot.
- Behavior: When the snapshot is frozen, ingest pins the version id current for each paper in the corpus (EN-01), and the reader and every tool that reads a paper read only that pinned version for the life of the batch.
- Observable: The snapshot record for a batch names the pinned version id for each paper, and every paper card and every tool read for that batch cites that same id.
- On failure: When the version current at freeze time cannot be read, the paper is not read for that batch and the failure is recorded.
- Verified by: A test that publishes a later revision of a paper after its batch's snapshot is frozen and checks that the reader and a run's tools on that batch both read the version pinned at freeze time, not the later one.

**EN-36.** A paper card signal taken from an outside provider must come only from a response captured before the batch's snapshot was frozen, never from a later response read back to that date.
<!-- id: SDD-EN-36 | tdd: none | status: pending:#57 -->

- Trigger: The reader builds a paper card signal that draws on a response from an outside provider.
- Behavior: The reader uses, for that signal, only a stored provider response that ingest hashed into the ledger (EN-07) before the batch's snapshot was frozen (AG-10), consistent with the forward-only rule (EN-02), and never substitutes a response captured later by reading it back to an earlier date.
- Observable: The paper card's signal cites the hash of a stored response whose ingest timestamp precedes the snapshot's freeze timestamp.
- On failure: When no response captured before the freeze exists, the paper card carries no value for that signal and the gap is recorded.
- Verified by: A test that offers the reader a provider response captured after the snapshot was frozen and checks that the paper card shows no value for that signal, never the value from the later response backdated to the batch.

**EN-37.** Ingest must measure and report each day the share of that day's papers for which it obtained the source, the text, the figures and a parsed bibliography, checked against a hand-verified sample.
<!-- id: SDD-EN-37 | tdd: none | status: pending:#45 -->

- Trigger: Ingest completes its daily fetch of new papers (EN-01).
- Behavior: For that day's papers, ingest measures the share for which it obtained the source, the text, the figures (MD-11) and a parsed bibliography (MD-07), checks the measurement against a hand-verified sample, and reports the four shares with the result of that check.
- Observable: A stored daily report gives, for that day's papers, the four measured shares and the result of the check against the hand-verified sample.
- On failure: When the measurement or the check cannot complete for a day, no report is stored for that day and the gap is recorded.
- Verified by: A test that gives ingest a day's papers with a known number missing the source, the text, the figures or the bibliography, and checks that the report's shares match the known counts.
- Limits: The match rate of parsed bibliography entries against known papers rests on open issue #26. The size and makeup of the hand-verified sample rest on open issue #31.

**EN-38.** Ingest must capture the picks of each named paper-discovery service on the day the service makes them.
<!-- id: SDD-EN-38 | tdd: none | status: pending:#57 -->

- Trigger: A named paper-discovery service publishes its picks for the day.
- Behavior: Ingest fetches that day's picks from each named service under that service's license review (IN-25), stores them and appends a ledger record under EN-07, and each service carries a verification date under SR-20.
- Observable: A stored record of each day's picks exists for each named service, dated to the day the service made them, and each service's entry shows a verification date.
- On failure: When a service's picks cannot be captured on the day they are made, no record is written for that service for that day, and the day is recorded as uncovered for that service.
- Verified by: A test that withholds a service's picks for a day and offers them a day later, and checks that no record is written crediting that later capture to the earlier day. This catches a pick list rebuilt after its day.
- Limits: Capture starts before the corpus's first batch is issued, or the days before it starts have no baseline drawn from that service. Which services are named, and whether any of them can be captured at all, is open (#22). The measure that checks a captured pick list against the service's own history is open (#33).

### 4.2 Ledger

**EN-03.** The ledger must record every forecast with the date on which it was sealed.
<!-- id: SDD-EN-03 | tdd: none | status: pending:#57 -->

- Trigger: A run, a rater or a baseline (IN-07 to IN-09) submits a forecast.
- Behavior: The ledger appends one record per forecast under SR-14, holding the forecast and its submitter, which for a run is the run stamped under SR-15. The record's timestamp is the moment of sealing and serves as the forecast's date.
- Observable: For each submitted forecast the ledger shows one record with the forecast, its submitter and its sealing timestamp.
- On failure: When the append does not complete, the forecast is not sealed, the submitter receives a refusal and the forecast is never scored.
- Verified by: A test that submits a forecast and checks that exactly one ledger record holds it with a sealing timestamp. A test that the scorer ignores a forecast that has no ledger record.

**EN-04.** The ledger must record whether each forecast was later confirmed or denied.
<!-- id: SDD-EN-04 | tdd: none | status: pending:#57 -->

- Trigger: A sealed forecast reaches its horizon and its resolver returns a result.
- Behavior: The ledger appends a resolution record that refers to the forecast's record and holds the resolver result of EN-14, where true means confirmed and false means denied. The forecast's own record stays unchanged, as SR-14 states.
- Observable: A forecast past its horizon has a resolution record in the ledger that refers to it and reads true, false or unresolvable.
- On failure: When the resolver does not run or the append does not complete, no resolution record is written, the forecast stays unsettled and the failure is recorded. An unsettled forecast counts as neither confirmed nor denied.
- Verified by: A test that seals a forecast, resolves it at its horizon with data that makes it true, and checks for a resolution record reading true that refers to the forecast. The same test checks that the forecast's original record and hash are unchanged, which catches a write over the original.

**EN-05.** The ledger must be hash-chained.
<!-- id: SDD-EN-05 | tdd: none | status: pending:#5 -->

- Trigger: A record is appended to the ledger.
- Behavior: Each record carries the hash of the record before it, and its own hash is computed over its content including that previous hash. The head of the chain is anchored as SR-16 states.
- Observable: Recomputing the hashes from the first record to the head reproduces every stored hash.
- On failure: An append whose previous hash does not equal the hash of the current head is refused and nothing is written. A recomputation that finds a mismatch reports the first record at which the chain breaks.
- Verified by: A test that changes one stored record in a copy of the ledger and checks that recomputation reports a break at that record. This catches a ledger whose past records can be edited unnoticed.

**EN-06.** A ledger record must hold a sequence number, the previous hash, its own hash, a kind, a payload and a timestamp.
<!-- id: SDD-EN-06 | tdd: none | status: pending:#5 -->

- Trigger: A record is appended to the ledger.
- Behavior: Every record, whatever its kind, is written with all six fields. The sequence number gives the record's place in the order of appending, and the kind says how the payload is read.
- Observable: Any record read from the ledger shows the six fields.
- On failure: An append that lacks any of the six fields is refused and nothing is written.
- Verified by: A test that attempts an append with each field missing in turn and checks that every attempt is refused.

**EN-07.** Every raw API response from an outside provider must be hashed into the ledger.
<!-- id: SDD-EN-07 | tdd: none | status: pending:#5 -->

- Trigger: Ingest receives a response from an outside provider.
- Behavior: Ingest stores the response exactly as received and appends a ledger record that holds the hash of the stored response.
- Observable: Hashing a stored response again gives the hash in its ledger record.
- On failure: A response that cannot be stored or hashed is not used by any later step, and the failure is recorded.
- Verified by: A test that alters a stored response and checks that its hash no longer equals the hash in the ledger. This catches outcome data changed after it was received.

**EN-08.** The version of every resolver that settles a forecast must be recorded in the ledger.
<!-- id: SDD-EN-08 | tdd: none | status: pending:#57 -->

- Trigger: A resolver returns a result for a forecast.
- Behavior: The resolution record names the resolver and the version that produced the result.
- Observable: Each resolution record in the ledger shows a resolver and a version.
- On failure: A result that comes without a resolver version is not appended. The forecast stays unsettled and the failure is recorded.
- Verified by: A test that resolves a forecast and checks that the resolution record carries the version of the resolver that ran. A test that an append of a resolution record with no version is refused.

### 4.3 Forecast batches and resolution

**EN-09.** A forecast batch must be issued daily.
<!-- id: SDD-EN-09 | tdd: none | status: pending:#57 -->

- Trigger: Once each day, after that day's ingest of new papers completes.
- Behavior: The environment builds one batch of questions about the papers ingested that day, seals it under EN-10 and issues it to the population's runs.
- Observable: The ledger holds one batch record for each calendar day.
- On failure: When the batch cannot be built or sealed, no batch is issued that day, no run starts against it and the failure is recorded.
- Verified by: A test that runs the daily cycle over several days and checks for exactly one sealed batch per day, with questions about that day's papers only. This catches a skipped day, a second batch in one day and a batch that reaches back to older papers.
- Limits: How long a batch accepts forecasts is not yet set (#6). The number of questions on a batch follows the daily volume of new papers, which has not been measured (#19).

**EN-10.** Each forecast batch must be sealed before its outcomes exist.
<!-- id: SDD-EN-10 | tdd: none | status: pending:#57 -->

- Trigger: A batch has been built and has not yet been issued.
- Behavior: The environment hashes the whole batch and appends a batch record with that hash and a timestamp to the ledger. Every question on the batch asks about a moment later than that timestamp, and the batch is issued only after the record exists.
- Observable: The batch record precedes, in the ledger, every forecast against the batch and all outcome data that settles its questions. Hashing the batch again gives the recorded hash.
- On failure: A batch that cannot be sealed is not issued, and no forecast against it is accepted. The failure is recorded.
- Verified by: A test that changes a question after sealing and checks that the batch's hash no longer equals its record and that forecasts against the changed batch are refused. This catches a question rewritten once outcomes are known.

**EN-11.** The resolver of each question must be fixed at the time the question is asked.
<!-- id: SDD-EN-11 | tdd: none | status: pending:#57 -->

- Trigger: A question is sealed, on a batch or as part of a volunteered forecast.
- Behavior: The sealed question names its resolver and that resolver's version. At the horizon the question is settled by that resolver at that version and by no other.
- Observable: The resolver and version in each resolution record equal those in the sealed question it settles.
- On failure: When the named resolver version cannot run at the horizon, no other resolver or version settles the question. No resolution record is written, and the failure is recorded.
- Verified by: A test that seals a question, offers a newer resolver version at the horizon, and checks that the sealed version settles the question. This catches a resolver changed after the question was asked.

**EN-12.** Outcome thresholds must be set relative to the cohort of papers from the same week.
<!-- id: SDD-EN-12 | tdd: none | status: pending:#57 -->

- Trigger: A question that compares a paper's outcome with a threshold is sealed, and later reaches its horizon.
- Behavior: The sealed question states its threshold as a rule over the outcomes of the paper's cohort, not as a fixed count. At the horizon the resolver computes the threshold from the outcomes of the cohort's papers at that same horizon and compares the paper with it.
- Observable: The resolution record's evidence shows the cohort outcomes the threshold was computed from and the paper's own outcome.
- On failure: When the cohort's outcomes are not available at the horizon, the threshold is not computed and the result is unresolvable under EN-14.
- Verified by: A test that resolves the same paper outcome against two cohorts with different outcome levels and checks that the result follows the cohort. This catches a threshold fixed as an absolute count.
- Limits: The rule that places a threshold within the cohort is not yet set (#6). Which thresholds carry prediction head probabilities is open (#16).

**EN-13.** Questions must use horizons of 1 week, 1 month, 3 months and 1 year.
<!-- id: SDD-EN-13 | tdd: none | status: pending:#57 -->

- Trigger: A question is built for a batch.
- Behavior: Every question on a batch carries exactly one of the four horizons, and every batch asks at each of the four. No other horizon appears on a batch.
- Observable: Each question in a sealed batch shows one of the four values as its horizon, and each of the four values appears in every sealed batch.
- On failure: A batch that holds a question with any other horizon is not sealed, and the failure is recorded.
- Verified by: A test that builds a batch containing a question whose horizon is none of the four values, and a batch that asks nothing at 1 year, and checks that sealing refuses both. It catches a system that never asks at the horizon a paper with delayed recognition needs.
- Limits: The four values are 1 week, 1 month, 3 months and 1 year, and whether a horizon runs from the seal of the batch or of the forecast is not yet set (#6). Which horizons carry prediction head probabilities is open (#16).

**EN-14.** A resolver result must be true, false or unresolvable, with evidence.
<!-- id: SDD-EN-14 | tdd: none | status: pending:#57 -->

- Trigger: A resolver runs on a forecast at its horizon.
- Behavior: The resolver returns exactly one of true, false and unresolvable, together with evidence that identifies the stored data it read. It returns unresolvable when that data is missing or permits neither true nor false, and the evidence then says what was missing.
- Observable: The resolution record in the ledger shows one of the three values and the evidence.
- On failure: A result with any other value, or with no evidence, is not appended to the ledger. The forecast stays unsettled and the failure is recorded.
- Verified by: A test that runs a resolver on data that settles the forecast each way and on data that settles nothing, and checks the three results and their evidence. A test that an append of a result without evidence is refused.

### 4.4 Outcome tracks

**EN-15.** Outcomes must be tracked as two tracks, the research uptake track and the online attention track.
<!-- id: SDD-EN-15 | tdd: none | status: pending:#57 -->

- Trigger: A question about an outcome is built for a batch.
- Behavior: Every outcome count belongs to exactly one track, as EN-17 to EN-23 assign it, and every question about an outcome carries the track of the counts it reads. Each track has its own resolvers and its own results.
- Observable: Each sealed question about an outcome, and each resolution record that settles one, shows research uptake or online attention as its track.
- On failure: A batch that holds an outcome question with no track, or one that reads counts from both tracks, is not sealed, and the failure is recorded.
- Verified by: A test that builds a question reading GitHub forks and GitHub stars together and checks that sealing refuses the batch. This catches outcomes of the two tracks merged into one result.
- Limits: How the tracks count toward fitness is open (#11). Which outcomes carry prediction head probabilities is open (#16).

**EN-16.** The research uptake track and the online attention track must be scored separately.
<!-- id: SDD-EN-16 | tdd: none | status: pending:#57 -->

- Trigger: The scorer scores a genome.
- Behavior: The scorer computes the genome's research uptake track score from its research uptake track forecasts only, and its online attention track score from its online attention track forecasts only. The two scores are recorded as two values.
- Observable: The scorer's output for a genome shows two scores, one per track.
- On failure: When a track's score cannot be computed, no value is recorded for that track and the other track's score does not stand in for it. The failure is recorded.
- Verified by: A test that changes only a genome's online attention track results and checks that its research uptake track score is unchanged. This catches one track's results entering the other track's score.
- Limits: How the two scores count toward fitness is open (#11).

**EN-17.** The research uptake track must count the citing papers in the system's own citation graph.
<!-- id: SDD-EN-17 | tdd: none | status: pending:#57 -->

- Trigger: A research uptake track question that reads this count reaches its horizon.
- Behavior: The resolver counts the papers in the system's citation graph (MD-07, MD-08) that cite the paper as of the horizon. The count is a research uptake track outcome.
- Observable: The resolution record's evidence gives the count taken from the citation graph at the horizon and identifies the citing papers counted.
- On failure: When the citation graph cannot be read at the horizon, no count is taken and the result is unresolvable under EN-14.
- Verified by: A test over a small citation graph with a known number of citing papers that checks the count. The graph includes a paper that cites a different work, and the test checks that it is not counted.
- Limits: The count depends on how many parsed bibliography entries match known papers, and that match rate has not been measured (#26).

**EN-18.** The research uptake track must count, as one count, the citations that Semantic Scholar marks as method citations or as influential citations.
<!-- id: SDD-EN-18 | tdd: none | status: pending:#57 -->

- Trigger: A research uptake track question that reads this count reaches its horizon.
- Behavior: Ingest fetches the paper's citations from Semantic Scholar and stores the response under EN-07. The resolver takes one count, as a research uptake track outcome, of the citations that carry either mark, and a citation that carries both marks is counted once.
- Observable: The resolution record's evidence gives the count and cites the hash of the stored response it was read from.
- On failure: When the fetch does not complete or the response lacks the marks, no count is taken and the result is unresolvable under EN-14.
- Verified by: A test that gives the resolver a stored response holding citations with the method mark, the influential mark, both marks and neither, and checks the one count. This catches a citation with both marks counted twice, a count of all citations and two separate counts.

**EN-19.** The research uptake track must count GitHub forks.
<!-- id: SDD-EN-19 | tdd: none | status: pending:#57 -->

- Trigger: A research uptake track question that reads this count reaches its horizon.
- Behavior: Ingest fetches from GitHub the fork count of the repository linked to the paper and stores the response under EN-07. The resolver reads the fork count from the stored response as a research uptake track outcome.
- Observable: The resolution record's evidence gives the count and cites the hash of the stored response it was read from.
- On failure: When the fetch does not complete, no count is taken and the result is unresolvable under EN-14.
- Verified by: A test that gives the resolver a stored response with known fork and star counts and checks that it reads the fork count. This catches stars counted as research uptake.

**EN-20.** The research uptake track must count the Hugging Face models and datasets linked to the paper.
<!-- id: SDD-EN-20 | tdd: none | status: pending:#57 -->

- Trigger: A research uptake track question that reads this count reaches its horizon.
- Behavior: The number of models and datasets on Hugging Face linked to the paper, as of the horizon, is a research uptake track outcome. Ingest obtains it and stores the raw response under EN-07, and the resolver reads the count from the stored response.
- Observable: The resolution record's evidence gives the count and cites the hash of the stored response it was read from.
- On failure: When the count cannot be obtained, no count is taken and the result is unresolvable under EN-14.
- Verified by: A test that gives the resolver a stored response with a known number of linked models and datasets and checks the count. The test checks that upvotes in the same response are not added to it.
- Limits: The Hugging Face endpoint for linked models and datasets is unconfirmed (#20).

**EN-21.** The online attention track must count Hugging Face upvotes.
<!-- id: SDD-EN-21 | tdd: none | status: pending:#57 -->

- Trigger: An online attention track question that reads this count reaches its horizon.
- Behavior: The number of upvotes the paper has on Hugging Face, as of the horizon, is an online attention track outcome. Ingest obtains it and stores the raw response under EN-07, and the resolver reads the count from the stored response.
- Observable: The resolution record's evidence gives the count and cites the hash of the stored response it was read from.
- On failure: When the count cannot be obtained, no count is taken and the result is unresolvable under EN-14.
- Verified by: A test that gives the resolver a stored response with a known number of upvotes and checks the count. The test checks that the count enters the online attention track and not the research uptake track.
- Limits: The Hugging Face endpoint for upvotes is unconfirmed (#20).

**EN-22.** The online attention track must count GitHub stars.
<!-- id: SDD-EN-22 | tdd: none | status: pending:#57 -->

- Trigger: An online attention track question that reads this count reaches its horizon.
- Behavior: Ingest fetches from GitHub the star count of the repository linked to the paper and stores the response under EN-07. The resolver reads the star count from the stored response as an online attention track outcome.
- Observable: The resolution record's evidence gives the count and cites the hash of the stored response it was read from.
- On failure: When the fetch does not complete, no count is taken and the result is unresolvable under EN-14.
- Verified by: A test that gives the resolver a stored response with known fork and star counts and checks that it reads the star count. This catches forks counted as online attention.

**EN-23.** The online attention track must count Hacker News mentions.
<!-- id: SDD-EN-23 | tdd: none | status: pending:#57 -->

- Trigger: An online attention track question that reads this count reaches its horizon.
- Behavior: The number of Hacker News mentions of the paper, as of the horizon, is an online attention track outcome. Ingest obtains it and stores the raw response under EN-07, and the resolver reads the count from the stored response.
- Observable: The resolution record's evidence gives the count and cites the hash of the stored response it was read from.
- On failure: When the count cannot be obtained, no count is taken and the result is unresolvable under EN-14.
- Verified by: A test that gives the resolver a stored response with a known number of mentions and checks the count. The test checks that the count enters the online attention track and not the research uptake track.
- Limits: The Hacker News endpoint for mentions is unconfirmed, and with it what is found as a mention (#21).

**EN-39.** Every outcome source must be measured each day for its coverage of the cohort and, where a second source exists for the same outcome, for its agreement with that source.
<!-- id: SDD-EN-39 | tdd: none | status: pending:#57 -->

- Trigger: Once each day, over the current cohort's outcome data.
- Behavior: For every outcome source that feeds the research uptake track or the online attention track (EN-17 to EN-23), ingest measures the share of the cohort's papers for which that source returned a value that day, and, where a second independent source exists for the same outcome, measures the agreement between the two sources' values.
- Observable: A stored daily report gives, for each outcome source, its coverage share of the cohort, and, where a second source exists, the agreement measure between them.
- On failure: When a source's coverage or an agreement measure cannot be computed for a day, no value is stored for that source for that day, and the gap is recorded.
- Verified by: A test that gives one source a known share of the cohort with no returned value and checks that the reported coverage matches, and a test that gives two sources for one outcome disagreeing values and checks that the reported agreement reflects the disagreement.
- Limits: Which outcome has a second independent source to check agreement against is open (#33).

### 4.5 Forecast types

**EN-24.** The environment must admit a forecast type that connects a field-level trend to a single paper-level result.
<!-- id: SDD-EN-24 | tdd: none | status: pending:#57 -->

- Trigger: The trend-to-paper forecast type receives its admission record under EN-31.
- Behavior: From that record on, the environment accepts forecasts of this type, each naming one field-level trend and one paper-level result and stating the connection between them. Such forecasts are sealed, settled and scored like forecasts of any other admitted type.
- Observable: The ledger holds the admission record for the type, and forecasts of the type submitted after it are sealed.
- On failure: While the type has no admission record, a forecast of the type is recorded as void under SR-11 and is not scored.
- Verified by: A test that submits a trend-to-paper forecast before the admission record exists and checks that it is recorded as void. The test repeats the forecast after admission and checks that it is sealed.
- Limits: The resolver for this type is not yet defined (#17). Until it is, EN-31 keeps the type unadmitted and this requirement stays unmet.

**EN-25.** The environment must admit the forecast that two works are cited together by at least N later papers within the horizon.
<!-- id: SDD-EN-25 | tdd: none | status: pending:#57 -->

- Trigger: A forecast of this type is submitted, and later reaches its horizon.
- Behavior: The forecast fixes the two works, N and the horizon when it is sealed. At the horizon the resolver counts the papers that entered the citation graph after sealing and cite both works, and returns true when the count is at least N.
- Observable: The resolution record gives the result, and its evidence gives the count and identifies the citing papers counted.
- On failure: A forecast that names a work absent from the citation graph at sealing cannot be bound and is void under SR-11.
- Verified by: A test over a small citation graph in which N later papers cite both works, checking true, and in which one fewer does, checking false. The graph includes a paper from before sealing that cites both works, and the test checks that it is not counted.

**EN-26.** The environment must admit the forecast that papers matching a fixed query grow by at least X percent.
<!-- id: SDD-EN-26 | tdd: none | status: pending:#57 -->

- Trigger: A forecast of this type is submitted, and later reaches its horizon.
- Behavior: The forecast fixes the query, X and the horizon when it is sealed, and the query is stored with the forecast. At the horizon the resolver runs the stored query over the corpus and returns true when the count of matching papers has grown by at least X percent since sealing.
- Observable: The resolution record gives the result, and its evidence gives the stored query and the two counts.
- On failure: A forecast whose query matches no paper at sealing has no base for a percentage, cannot be bound and is void under SR-11.
- Verified by: A test over a small corpus that checks true when the matching papers grow by exactly X percent and false just below. A second test changes the query after sealing and checks that the resolver still runs the stored one.
- Limits: The form of a fixed query is not yet set (#6).

**EN-27.** The environment must admit the forecast that a paper's citation rate rises by a factor k.
<!-- id: SDD-EN-27 | tdd: none | status: pending:#57 -->

- Trigger: A forecast of this type is submitted, and later reaches its horizon.
- Behavior: The forecast fixes the paper, k and the horizon when it is sealed. At the horizon the resolver computes the paper's citation rate from dated citation counts, compares the rate after sealing with the rate at sealing, and returns true when the ratio is at least k.
- Observable: The resolution record gives the result, and its evidence gives the dated counts and the two rates.
- On failure: A forecast on a paper whose citation rate at sealing is zero has no base for a factor, cannot be bound and is void under SR-11.
- Verified by: A test with dated citation counts in which the rate rises by exactly k, checking true, and by less than k, checking false.
- Limits: The window a citation rate is taken over is not yet set (#6).

The ids EN-28 and EN-29 are reserved by #27: a subtopic publication-rate forecast and a benchmark-adoption forecast are held out of the first build.

**EN-30.** Agents must be able to volunteer forecasts of the admitted forecast types.
<!-- id: SDD-EN-30 | tdd: none | status: pending:#57 -->

- Trigger: A run submits a forecast that answers no question on the batch.
- Behavior: The environment accepts the forecast when its type has an admission record (EN-31), binds it to that type's resolver and version (EN-11) and applies the sealing checks of SR-07 to SR-10. A forecast that passes is sealed under EN-03 and settled at its horizon like any other.
- Observable: The ledger holds a forecast record that names an admitted forecast type and no batch question.
- On failure: A volunteered forecast of a type with no admission record, or one that fails a sealing check, is recorded as void under SR-11 and is not scored.
- Verified by: A test in which a run volunteers a forecast of the EN-25 type with its parameters and checks that it is sealed. A second test volunteers a forecast of an unknown type and checks that it is recorded as void.

**EN-31.** A new forecast type must be admitted only when it has a deterministic resolver.
<!-- id: SDD-EN-31 | tdd: none | status: pending:#57 -->

- Trigger: A forecast type is put forward for admission.
- Behavior: A forecast type is admitted by a ledger record that names the type, its resolver and the resolver's version. The record is written only for a resolver that gives the same result every time it runs on the same stored inputs.
- Observable: The ledger holds one admission record for each admitted forecast type, and forecasts are sealed only for types that have one.
- On failure: For a type with no resolver, or a resolver whose results differ between runs on the same inputs, no admission record is written. Forecasts of that type are recorded as void under SR-11.
- Verified by: A test that runs each admitted resolver twice on the same stored inputs and checks that the results are identical. A test that puts forward a type whose resolver draws a random number and checks that no admission record is written.
- Limits: The trend-to-paper type of EN-24 stays unadmitted under this rule until its resolver is defined (#17).

### 4.6 Digest and human answers

**EN-32.** Surfaced papers must be delivered to the raters as a private digest.
<!-- id: SDD-EN-32 | tdd: none | status: pending:#57 -->

- Trigger: Papers surfaced by the population's runs are ready to go to the raters.
- Behavior: The environment assembles the digest under EN-40 and delivers it to the two raters only, through the private app of PL-22. What the digest hides from the raters is stated in SR-21 and SR-22.
- Observable: Each rater receives the digest. An attempt to read it without a rater's access is refused.
- On failure: When delivery does not complete, no partial digest reaches a rater and the failure is recorded.
- Verified by: A test that tries to read a digest without a rater's access and checks refusal, then reads it with a rater's access and checks that the surfaced papers are there. This catches a digest that anyone can read.
- Limits: The digest reaches the raters through the app of PL-22 and no other path, and SR-13 applies to that path. Whether every surfaced paper is itself a dated forecast is open (#12), and delivery is the same under either answer.

**EN-33.** Each digest must include a few papers chosen at random, to correct rating bias.
<!-- id: SDD-EN-33 | tdd: none | status: pending:#45 -->

- Trigger: A digest is assembled.
- Behavior: The environment draws the set count of papers at random, by no genome's choice, and places them among the surfaced papers. It records which papers were drawn, and SR-22 keeps that record from the raters. The service picks a digest also carries are EN-42's.
- Observable: The record of each digest marks its random papers, and the digest the raters see carries no such mark.
- On failure: When the draw does not complete, the digest is not delivered without its random papers, and the failure is recorded.
- Verified by: A test that assembles a digest and checks that it holds the set count of random papers, marked in the record and unmarked in the raters' view. This catches a digest made only of surfaced papers.
- Limits: The count of random papers in a digest is not yet set (#6).

**EN-34.** The raters must answer a subset of the same daily batch that the agents answer, so that the ledger scores them too.
<!-- id: SDD-EN-34 | tdd: none | status: pending:#57 -->

- Trigger: A batch is issued.
- Behavior: The environment gives the raters a subset of the questions on that batch, answered while the batch accepts forecasts (EN-09), and that day's digest (EN-32) opens to a rater only after that rater's answers are sealed. Each answer is a forecast, sealed under EN-03 after the same checks, and settled and scored by the same path as an agent's forecast.
- Observable: For each sealed batch the ledger holds forecast records submitted by the raters against it, and the scorer's output shows scores for the raters. That day's digest is open to a rater only after that rater's answers against the batch are in the ledger.
- On failure: A rater's answer that fails a sealing check is recorded as void under SR-11 and is not scored. A question a rater leaves unanswered yields no forecast, no answer is filled in for it, and the day's digest stays closed to that rater, with each refusal recorded.
- Verified by: A test that submits a rater's answer and an agent's answer to the same question and checks that both are sealed, settled by the same resolver result and scored by the same function. A check that fails when a batch that no longer accepts forecasts holds no forecast record from a rater, and a test that the day's digest is refused to a rater who has not answered that batch and opens once those answers are sealed.
- Limits: The size of the subset of the batch that the raters answer is not yet set (#6).

**EN-40.** The digest must be built after the day's batch seals, by a fixed rule and a recorded seed, from the ledger alone, as one entry per paper, so that the same ledger always gives the same digest.
<!-- id: SDD-EN-40 | tdd: none | status: pending:#57 -->

- Trigger: The day's batch has been sealed (EN-10) and the day's digest is built.
- Behavior: The environment builds the digest by one fixed rule from ledger records alone: the day's sealed forecasts, the random papers of EN-33 and any service picks the ledger carries (EN-38), one entry per paper and no entry from any other source. It records the seed the rule used and a hash of the digest.
- Observable: The ledger holds, for each digest, the seed and the hash, and building the digest again from the same records, which SR-14 keeps as they were written, gives that hash.
- On failure: When a record the build reads is missing, or the seed or the hash cannot be recorded, no digest is built or delivered that day and the failure is recorded.
- Verified by: A test that builds the digest twice from one fixed set of ledger records and checks that both give the recorded hash. A test that stores a rating and a paper held outside the ledger, rebuilds the digest and checks that it is unchanged, which catches a digest assembled from a second list beside the ledger.
- Limits: Whether every surfaced paper is itself a dated forecast is open (#12), and the build reads the same ledger records under either answer.

**EN-41.** The digest's entries from the population must be chosen by pooling the genomes' forecast probabilities for each paper, with each genome's highest-probability paper kept when pooling would drop it.
<!-- id: SDD-EN-41 | tdd: none | status: pending:#57 -->

- Trigger: The day's digest is built (EN-40) and its entries from the population are chosen.
- Behavior: For each paper the environment pools the forecast probabilities of the forecasts the genomes sealed about it on the day's batch, ranks the papers by the pooled value and fills the entries in that order. The highest-probability paper of each genome takes a place among those entries when the ranking left that paper out.
- Observable: The record of each digest gives, for every entry from the population, the pooled value that placed it or the genome whose highest forecast probability kept it, out of the raters' view (SR-21).
- On failure: When the day's sealed forecasts cannot be read, the entries from the population are not chosen, no digest is delivered and the failure is recorded.
- Verified by: A test with several genomes, one of them alone in its forecast probability about a paper the others did not name, that checks that the paper is among the entries. This catches a choice that takes only the highest pooled papers and buries the paper one genome found.
- Limits: The size of the digest and the rule that pools forecast probabilities are not yet set (#6), as is what counts as a genome's pick (IN-04). The size of the digest does not grow with the population, which is bounded by the count of parallel runs (#10).

**EN-42.** The digest must carry a discovery service's picks unmarked, so that a rater rates each one without knowing it came from a service.
<!-- id: SDD-EN-42 | tdd: none | status: pending:#57 -->

- Trigger: The day's digest is built (EN-40) from ledger records that include that day's service picks (EN-38).
- Behavior: The environment carries each service pick the ledger holds for that day among the digest's other entries, one entry per pick, with nothing in the entry naming it a pick. What keeps a rater from telling a pick from another entry is stated in SR-22.
- Observable: For a day whose ledger holds service picks, the delivered digest has an entry for each of them, and a rater's rating under IN-10 is stored against those entries as against any other.
- On failure: When a service pick cannot be carried among the digest's entries as one of them, no digest is delivered that day and the failure is recorded.
- Verified by: A test that builds a digest for a day whose ledger holds known service picks and checks that each pick has an entry in what the rater receives. This catches a digest assembled from surfaced papers and random controls alone.
- Limits: An arXiv id older than the other entries' can still reveal a pick. Recording that residue leaves it in view, and running the digest a fixed number of days behind the batch removes it. Which applies, and any day count, is not yet set (#6). Whether a surfaced paper is a dated forecast is open (#12), and this rule holds either way.

## 5. Agents

### 5.1 Population

**AG-01.** The agent model must be a top-tier reasoning model that reasons over the small models' probabilistic outputs.
<!-- id: SDD-AG-01 | tdd: none | status: pending:#57 -->

- Trigger: A run starts under its run specification.
- Behavior: The run calls the agent model, and the agent model receives the small models' probabilistic outputs as the text of paper cards (RD-04, RD-08) returned by the run's tools. The forecasts a run submits are those the agent model passes to submit, and nothing else writes forecasts for a run.
- Observable: The tool responses delivered to the agent model contain the prediction head probabilities from the paper cards, and the run's stamp names the agent model id (SR-15).
- On failure: When the agent model cannot be called, the run stops without a submit and is void (AG-15). The failure is recorded.
- Verified by: A test that runs one agent on a snapshot whose paper cards carry known prediction head probabilities and checks that those values appear in the tool responses sent to the agent model and that the stamp names the agent model id. It catches a run that submits forecasts without the agent model having received the small models' outputs.
- Limits: The agent model is not named (#14). What counts as top-tier is settled by that decision, and this requirement holds whether one model is named or the model is a configured value.

**AG-02.** The agent model must also receive the figures and tables of a paper, in addition to its paper card.
<!-- id: SDD-AG-02 | tdd: none | status: pending:#57 -->

- Trigger: A run calls deep_read on a paper (AG-09).
- Behavior: The deep_read response carries the paper's figures and tables, taken from the paper's source in the snapshot, in a form the agent model accepts (MD-11).
- Observable: For a paper whose source holds figures and tables, the deep_read response sent to the agent model contains them.
- On failure: When a figure or table cannot be served, the deep_read response names what is missing and carries nothing in its place. The failure is recorded with the run.
- Verified by: A test that calls deep_read on a paper with a known figure and a known table and checks that both are in the response the agent model receives. It catches a deep read that delivers text alone.
- Limits: The agent model is not named (#14). The requirement holds for any choice that accepts figures and tables as input, and it rules out a choice that does not.

**AG-03.** What evolves must be the agent's own process for choosing which papers to read and put into context.
<!-- id: SDD-AG-03 | tdd: none | status: pending:#57 -->

- Trigger: Selection is evaluated (AG-18), or a mutation is proposed against a parent genome (AG-20).
- Behavior: Selection and mutation act on genomes (AG-16) and on nothing else. The agent model's weights (FT-07), the small models, the behavior of the tools, the batch, the resolvers and the scorer are the same for every genome and are never changed by selection or mutation.
- Observable: The stored diff of every child genome (AG-20) changes parts of the genome (AG-16) and nothing else, and a diff that reaches outside the genome is recorded as rejected.
- On failure: A diff that reaches outside the genome is rejected. No child is made from it, the population is unchanged, and the rejection is recorded.
- Verified by: A test that proposes a diff reaching outside the genome, for example one that changes the agent model id or a tool's behavior, and checks that it is rejected and that no child enters the population. It catches selection or mutation acting on anything other than genomes.
- Limits: Which parts of a genome are open to mutation is not yet set (#6).

**AG-04.** The agent layer must be a population of the same agent doing the same task.
<!-- id: SDD-AG-04 | tdd: none | status: pending:#57 -->

- Trigger: A forecast batch is issued (EN-09).
- Behavior: Every run on the batch uses the same loop (AG-08), the same agent model, the same batch and the same snapshot. One member of the population differs from another by its genome alone.
- Observable: The run specifications written for one batch carry the same snapshot hash and differing genome hashes (AG-17), and the run stamps carry the same agent model id (SR-15).
- On failure: A genome whose run cannot start on a batch has no forecasts on that batch, and the missing run is recorded. No other agent design or task is put in its place.
- Verified by: A test that issues one batch to a population of differing genomes and checks that every run specification names the same snapshot hash and every run stamp names the same agent model id. It catches a member that runs a different agent, task or snapshot.
- Limits: The size of the population is not stated. It is bounded by the count of agent runs that execute in parallel, which is an open decision (#10).

**AG-05.** The population must be tested continuously, with every genome in it run on each forecast batch as the batch is issued.
<!-- id: SDD-AG-05 | tdd: none | status: pending:#57 -->

- Trigger: A forecast batch is issued (EN-09).
- Behavior: A run is started on that batch for every genome in the population, and the forecasts it submits are sealed in the ledger to be settled at their horizons. A genome's record on live batches is the only test it is given.
- Observable: For each batch, every genome that was in the population at issue has either sealed forecasts in the ledger or a run recorded as void (AG-15) or as missing (AG-04).
- On failure: A run that ends without a submit is void (AG-15), and a run that cannot start is recorded as missing (AG-04). The gap stays in the genome's record.
- Verified by: A test that issues batches on consecutive days to a population and checks that every genome has a run recorded on every batch. It catches a genome that stays in the population without being tested.
- Limits: The load of testing grows with the size of the population, which is bounded by the count of parallel runs, an open decision (#10).

**AG-06.** The population must be mutated toward its best performers.
<!-- id: SDD-AG-06 | tdd: none | status: pending:#5 -->

- Trigger: Selection is evaluated in a weekly cycle and proceeds (AG-18).
- Behavior: Parents are sampled by fitness (AG-19, FT-12), children are made from them by mutation (AG-20, AG-21), and the children replace genomes in the population (FT-13).
- Observable: After a selection that replaces genomes, every new genome in the population traces through its stored diff to a parent drawn by fitness.
- On failure: When sampling, mutation or replacement cannot complete, the population stays as it was before the cycle. No partial replacement is applied and the failure is recorded.
- Verified by: A test that runs selection many times over a population with known, well separated fitness values and checks that the fittest genomes have more children than the least fit. It catches replacement that ignores fitness, such as replacement at random or in a fixed order.

**AG-07.** The agent must not judge itself: no score, fitness value or selection decision comes from an agent or from the agent model.
<!-- id: SDD-AG-07 | tdd: none | status: pending:#57 -->

- Trigger: The scorer scores a genome, or selection is evaluated.
- Behavior: The scorer computes a genome's score from ledger records alone, which for the genome are its sealed forecasts and their resolver results (IN-01, SR-03). Nothing an agent says about its own performance or about another genome is read by the scorer or by selection.
- Observable: A genome's score recomputed from the ledger alone, with no call to the agent model, equals the recorded score.
- On failure: When a score cannot be computed from ledger records alone, the scorer stops and writes no score (IN-01), and the failure is recorded. No agent output stands in for it.
- Verified by: A test that adds to a run's final message a statement rating its own forecasts as correct and checks that the genome's score is the same with and without it. It catches any path by which an agent's view of itself reaches a score.

**AG-31.** A genome must not contain the identifier of a paper in any of its parts.
<!-- id: SDD-AG-31 | tdd: none | status: pending:#57 -->

- Trigger: A genome is offered to the population, as a first genome or as a child of mutation (AG-20).
- Behavior: Admission reads every part of the genome (AG-16) and looks for the identifier of a paper in the corpus. A genome that carries one in any part is not admitted, so no lineage carries a named paper, and with it a settled outcome, into a later run.
- Observable: No genome in the population holds a paper's identifier in any part, and a genome that carried one has a recorded refusal and appears in no run specification.
- On failure: The genome is refused whole. It does not enter the population, gets no run specification, and the refusal is recorded with the part that carried the identifier.
- Verified by: A test that offers a child genome whose prompt names a paper by its identifier, and one whose structured output schema names a paper in a field description, and checks that both are refused. It catches a genome that carries knowledge of a settled paper forward in its own text.

**AG-32.** A genome must hold a structured output schema, a schema for the agent model's own turns that the loop enforces, bounded by a fixed meta-schema, whose evolved extension is empty in the first population.
<!-- id: SDD-AG-32 | tdd: none | status: pending:#57 -->

- Trigger: A genome is offered to the population (AG-16), or a run's loop assembles a request to the agent model (AG-08).
- Behavior: The structured output schema gives the schema of the agent model's own turns, it is checked at admission against a fixed meta-schema, and the loop passes it with each request. A genome of the first population carries its protected core (AG-33) and no evolved field beside it, and the tool schemas (AG-11) and the fields of a forecast stay outside it.
- Observable: Every genome in the population, read back, shows a structured output schema that holds against the meta-schema, and the fields it names are the fields filled in that genome's run records (AG-29).
- On failure: A genome whose structured output schema does not hold against the meta-schema is not admitted, gets no run specification, and the refusal is recorded. When the loop cannot pass the format to the agent model, the run ends without a submit and is void (AG-15).
- Verified by: A test that offers a genome whose structured output schema breaks the meta-schema and checks that it is refused, and a test that changes a filled field in a run record and checks that the genome's score is unchanged (SR-03). It catches a format outside the meta-schema and a filled field that reaches the scorer.
- Limits: The bounds the meta-schema sets on the evolved extension are not yet set (#6). What the step that proposes a mutation is shown is an open decision (#13), and this requirement holds under each of its options.

**AG-33.** The structured output schema must have a protected core, the same for every genome and never mutated, that holds for each turn a plain-language note of bounded length and an intent label from a fixed list, with evolution acting only on the extension beside it.
<!-- id: SDD-AG-33 | tdd: none | status: pending:#57 -->

- Trigger: A genome is offered to the population (AG-16), or a mutation of a structured output schema is proposed (AG-35).
- Behavior: Every structured output schema carries the same core, which for each turn holds a note in plain language of bounded length and an intent label from a fixed list. Mutation acts only on the extension (AG-03), the core is not read by the scorer (SR-03), and a rater sees the note only after rating the entry (IN-36).
- Observable: The run records of any two genomes hold the same core fields under the same names (AG-29), and a diff that changes the core or the list of intent labels is recorded as rejected.
- On failure: A genome whose structured output schema lacks the core, or whose core differs from the fixed one, is not admitted, gets no run specification, and the refusal is recorded.
- Verified by: A test that proposes a diff removing the note from the core and one that uses an intent label outside the fixed list, and checks that both are rejected. It catches evolution that drops the fields a reader compares across genomes.
- Limits: The length of the note is not yet set (#6). It is set within the run's output budget (AG-12), against which the note counts for every turn of a run.

**AG-34.** Every evolved field of a structured output schema must carry a label and a description in human-readable words and one of a small fixed set of types, so that the rating app renders it by rule and without a language model.
<!-- id: SDD-AG-34 | tdd: none | status: pending:#57 -->

- Trigger: A mutation that adds, renames or retypes a field of the structured output schema is proposed (AG-35).
- Behavior: The proposed diff carries the field's label, its description and its type, and admission checks that all three are present and that the type is one of the fixed set (AG-20). The rating app reads those values to render the field (IN-36), and nothing is generated when the field is displayed.
- Observable: Every evolved field of every genome in the population has a label, a description and a type from the set, and the rendered field's caption is the stored label.
- On failure: A diff whose field lacks a label or a description, or whose type is outside the set, is rejected. No child is made from it, and the rejection is recorded.
- Verified by: A test that proposes a field with no description and one with a type outside the set and checks that both are rejected, and a test that renders a run record with every language model unreachable (IN-36). It catches a caption or a type worked out at display time.
- Limits: The set of types is not yet set (#6).

### 5.2 Runs

**AG-08.** An agent run must be a plain Messages API loop: one conversation between the agent model and the run's tools, with no layer between them.
<!-- id: SDD-AG-08 | tdd: none | status: pending:#57 -->

- Trigger: A run starts under its run specification.
- Behavior: The loop sends the conversation to the agent model through a Messages API and answers each tool call with that tool's response, ending the run at the first accepted submit (AG-26), an exhausted budget (AG-12), the model stopping, or a conversation that no longer fits its context. Nothing else adds, removes, reorders or rewrites messages.
- Observable: Every request a run sends to the agent model holds only the system prompt from the genome, a first message that holds the batch, the run's budgets and a description of the snapshot, the model's earlier turns and the tool responses, in the order they were produced.
- On failure: When a call to the agent model fails, the loop stops, and the run ends without a submit and is void (AG-15). The failure is recorded.
- Verified by: A test that runs the loop against a stand-in agent model with a fixed script of tool calls, and checks each request for any message beyond the system prompt, the first message, an earlier turn or a tool response, or any change in their order. It catches a layer that injects, drops, reorders or rewrites messages.
- Limits: The agent model is not named (#14). The loop assumes an agent model offered through a Messages API, and that assumption is settled with the model.

**AG-09.** An agent's tools must be exactly query_cards, neighbors, graph, deep_read and submit.
<!-- id: SDD-AG-09 | tdd: none | status: pending:#57 -->

- Trigger: A run is offered its tools, and the agent model returns a tool call.
- Behavior: The loop offers the agent model these five tools and no other, less any the genome has narrowed away (AG-14). The first four read from the snapshot (AG-10), and what they return of the small models is paper card text (RD-04, RD-05). Submit hands in the run's forecasts.
- Observable: The tool list in every request to the agent model names only tools among the five, and a call to any other name gets a refusal.
- On failure: A call to a tool outside the run's allowed set is refused with an error response. Nothing is executed and the refusal is recorded with the run.
- Verified by: A test in which a stand-in for the agent model calls a sixth tool name and checks that the call is refused and nothing runs, and a check of the tool list offered to the model against the five names. It catches a tool added outside the specification.

**AG-10.** An agent must have read-only access to a snapshot frozen when the batch is issued.
<!-- id: SDD-AG-10 | tdd: none | status: pending:#57 -->

- Trigger: A forecast batch is issued (EN-09), and a run on that batch starts.
- Behavior: When the batch is issued, the papers, the paper cards and the citation graph are frozen as a snapshot and its hash is recorded. The shared tool service (PL-21) answers every call a run makes from the snapshot named in that run's contract (AG-17), even when the run starts after a newer snapshot exists, and the run has no means to write to it.
- Observable: The snapshot hash in each run specification for the batch (AG-17) equals the hash recorded at issue and the hash recomputed after the runs, and a run that starts after a later batch is issued still reads only the snapshot named in its own contract. A write attempted from a run is refused.
- On failure: When the snapshot cannot be frozen, or its hash does not match the run specification, no run on that batch starts and the failure is recorded.
- Verified by: A test adds a paper after a batch is issued and checks a run on that batch cannot retrieve it, and a test starts a run on an old contract after a later snapshot exists and checks it is still answered from its own snapshot. A further test attempts a write from a run and checks it is refused and the snapshot hash is unchanged.

**AG-11.** Tool schemas must be strict, so that a tool call with a missing, extra or wrongly typed argument is refused.
<!-- id: SDD-AG-11 | tdd: none | status: pending:#57 -->

- Trigger: The agent model returns a tool call.
- Behavior: The call's arguments are checked against the tool's schema before the tool runs. A call that does not match exactly is refused with an error response, and its arguments are not coerced or partly used.
- Observable: The refused call gets an error response and has no effect. For submit, no forecast from the refused call reaches the ledger.
- On failure: When the check itself cannot run, the call is refused, the tool does not run and the failure is recorded.
- Verified by: A test that sends each tool a call with an extra argument, one with a missing argument and one with a wrongly typed argument, and checks that all are refused. It catches a tool that coerces or ignores bad input.

**AG-12.** Every run must have hard budgets, enforced by the loop and outside the agent's control.
<!-- id: SDD-AG-12 | tdd: none | status: pending:#57 -->

- Trigger: A run starts under a run specification that carries its budgets (AG-17).
- Behavior: The loop counts the run's use against each budget in the run specification, states the remaining amount against each budget in every tool response (AG-27), and stops the run when one is exhausted. Nothing the agent model does raises or resets a budget.
- Observable: A run stopped by a budget is recorded with the budget that was exhausted, no call to the agent model or to a tool follows that point, and every tool response of the run carries the remaining amount for each budget.
- On failure: A run whose contract carries no budgets does not start. A run stopped by a budget before submit is void (AG-15). A tool response that cannot state the remaining budgets is not sent, and the failure is recorded.
- Verified by: A test gives a run a small budget and a stand-in agent model that never stops calling tools, and checks the run stops at the budget with no further call, and that each tool response up to then carried the remaining amount per budget. It catches a budget that is advisory, extendable by the agent, or unreported.
- Limits: The run budgets, in kind and in size, are not yet set (#6). They depend on the count of parallel runs (#10) and on the daily volume of new papers, which has not been measured (#19).

**AG-13.** The scorer must run in a process separate from the agent.
<!-- id: SDD-AG-13 | tdd: none | status: pending:#5 -->

- Trigger: The scorer starts, or an agent run starts.
- Behavior: The scorer runs as its own process in its own container (PL-01) and takes its input from the ledger. No agent run executes inside that process, and a run has no interface to it (SR-12).
- Observable: The scorer and the agent runs are listed as separate processes, and the scorer produces the same scores from the ledger when no agent run exists.
- On failure: When the scorer's process is not running, no score is produced and the failure is recorded. An agent run never computes a score in its place.
- Verified by: A test that tries to reach the scorer from inside an agent run and checks that the attempt is refused, and a test that stops all agent runs and checks that the scorer still computes the same scores from the ledger. It catches scoring that shares a process or state with an agent.

**AG-14.** A genome must be able to narrow the tool set of AG-09 and never widen it.
<!-- id: SDD-AG-14 | tdd: none | status: pending:#57 -->

- Trigger: A run specification is built for a genome.
- Behavior: The tools allowed in the run specification are the genome's tools when every one of them is among the five of AG-09. A genome that lists any other tool gets no run specification.
- Observable: The tools allowed in every run specification are among the five, and a genome that lists any other tool has a recorded refusal and no run.
- On failure: The run specification is not built, the genome has no run on that batch, and the refusal is recorded.
- Verified by: A test that builds a run specification for a genome listing four of the five tools and checks that the run is offered only those four, and a test with a genome listing a sixth tool that checks the contract is refused. It catches a genome that gains a tool by naming it.

**AG-15.** A run that ends without a submit must be void.
<!-- id: SDD-AG-15 | tdd: none | status: pending:#57 -->

- Trigger: A run ends without an accepted call to submit, whether the model stopped, a budget was exhausted, a failure stopped the loop, or every call to submit it made was refused.
- Behavior: The run is recorded as void with its stamp (SR-15). No forecast from it is sealed or scored, text the agent model produced outside submit is never read as a forecast, and a run's ending follows the same first-accepted-submit rule as any other run (AG-26).
- Observable: The run's record shows the void state, and the ledger holds no forecast from that run.
- On failure: There is no partial outcome. A run either has an accepted submit or is void.
- Verified by: A test that ends one run by exhausting its budget before submit and another in which the model stops after listing its picks as plain text, and checks that both are void and that no forecast from either reaches the ledger.

**AG-25.** The first message of a run must hold only the batch, the run's budgets and a description of the snapshot, so that every paper card in the conversation is one the agent asked for.
<!-- id: SDD-AG-25 | tdd: none | status: pending:#57 -->

- Trigger: A run starts under its run specification (AG-17).
- Behavior: The loop (AG-08) composes the first message from the batch issued for the run (EN-09), the run's budgets and a description of the snapshot, and places no paper card in it. Every paper card that reaches the conversation after that point is one the agent retrieved through its own tool call (AG-03).
- Observable: The first message stored for a run holds only these three parts, and no paper card text appears in it before the run's first tool call.
- On failure: A first message that carries a paper card or content beyond these three parts means the run does not start, and the failure is recorded.
- Verified by: A test that inspects the first message of a run and checks it for content besides the batch, the budgets and the snapshot description. It catches a loop that places a paper card or other context into the first message on the agent's behalf.

**AG-26.** A run must end at its first accepted submit, which carries all of the run's forecasts and is accepted or refused as a whole, after which each forecast it carries is sealed or recorded as void (SR-11).
<!-- id: SDD-AG-26 | tdd: none | status: pending:#57 -->

- Trigger: The agent model calls submit (AG-09) during a run.
- Behavior: The loop (AG-08) accepts or refuses the call as a whole, and once a call is accepted the run ends and no later call is read. Each forecast the accepted call carries is then sealed in the ledger or recorded as void (SR-11).
- Observable: A finished run's record shows exactly one accepted submit, and the ledger holds, for every forecast that call carried, a sealed forecast with its seal date (EN-03) or a void record.
- On failure: A submit call that is refused leaves the run running under its remaining budget (AG-12), and a run with no accepted submit is void (AG-15).
- Verified by: A test that has the agent model call submit twice in one run and checks that only the first accepted call's forecasts reach the ledger and the second call has no effect. It catches a loop that reads forecasts from more than one submit.

**AG-27.** Every tool response must state the run's remaining budgets.
<!-- id: SDD-AG-27 | tdd: none | status: pending:#57 -->

- Trigger: The loop returns a response to a tool call the agent model made (AG-09).
- Behavior: The loop attaches to every tool response the remaining amount against each budget in the run's contract (AG-12, AG-17), computed after the call that produced the response.
- Observable: Every tool response received by the agent model carries a remaining value for each budget named in the run specification.
- On failure: A response that cannot carry the remaining budgets is not sent, the tool call is treated as failed, and the failure is recorded.
- Verified by: A test that reads every tool response of a run and checks each one for a remaining value per budget in the contract. It catches a response that omits the budgets or states them only in the run's final message.

**AG-28.** The loop must not drop, summarize or reorder earlier messages to fit the agent model's context, and a run that no longer fits ends as its budget exhaustion does.
<!-- id: SDD-AG-28 | tdd: none | status: pending:#45 -->

- Trigger: The conversation of a run grows too large for the agent model's context.
- Behavior: The loop (AG-08) sends the full, unmodified sequence of earlier turns and tool responses on every call to the agent model. When the conversation no longer fits, the run ends there, the same way a run ends when a budget is exhausted (AG-12, AG-15).
- Observable: Every request sent to the agent model contains the same earlier turns and tool responses in the same order as they were produced, with no message missing, shortened or moved, up to the point where the run ends.
- On failure: A run that cannot send its full conversation to the agent model ends without a submit and is void (AG-15). No message is dropped, summarized or reordered to keep the run going.
- Verified by: A test that grows a run's conversation past a fixed context size for a stand-in agent model and checks that the loop ends the run rather than dropping, summarizing or reordering any earlier message. It catches a harness that compacts the conversation to keep the run alive.

### 5.3 Records

**AG-16.** A genome must hold a prompt, a scan policy, a read policy, a probability assignment rule, tools, budgets, sampling settings and a structured output schema.
<!-- id: SDD-AG-16 | tdd: none | status: pending:#57 -->

- Trigger: A genome is offered to the population, as a first genome or as a child of mutation (AG-20).
- Behavior: A genome is one record with these eight parts, its genome hash is computed over all of them, and a record that lacks a part is not admitted. The sampling settings give the count of samples the run takes of the agent model for one question, and the forecast probability submitted for that question is their mean (AG-26).
- Observable: Every genome in the population, read back, shows the eight parts, and the hash recomputed over them equals the genome hash stamped on its runs (SR-15). For a question sampled more than once, the sealed forecast probability equals the mean of the samples recorded for it (AG-29).
- On failure: A record that lacks a part is refused. It does not enter the population, gets no run specification, and the refusal is recorded.
- Verified by: A test that offers a genome with no probability assignment rule and checks that it is refused, a test that changes one part and checks that the genome hash changes, and a test with three samples of known forecast probability that checks the sealed value is their mean. It catches a part outside the hash and a last sample passed off as a mean.
- Limits: The form of the scan policy and the read policy is not yet set (#6). The count of samples a genome asks for is bounded by the run's budgets (AG-12).

**AG-17.** A run specification must hold a slot, a genome hash, a seed, a snapshot hash, budgets and the tools allowed.
<!-- id: SDD-AG-17 | tdd: none | status: pending:#57 -->

- Trigger: A run is about to start for a genome on a batch.
- Behavior: The run specification is written with these six parts before the run starts. The run reads it and cannot change it (IN-24).
- Observable: A stored run specification exists for every run, written before the run's first call to the agent model, and its genome hash and seed equal those in the run's stamp (SR-15).
- On failure: When a run specification cannot be written with all six parts, the run does not start and the failure is recorded.
- Verified by: A test that starts a run on a contract with no seed and checks that the run does not start, and a test that compares each finished run's stamp with its run specification. It catches a run that starts on an incomplete contract or on one edited later.
- Limits: What a slot is: not yet set (#6).

**AG-29.** The loop must record every request to the agent model and every response, by hash and in order, with the run.
<!-- id: SDD-AG-29 | tdd: none | status: pending:#45 -->

- Trigger: The loop sends a request to the agent model or receives its response, inside the conversation AG-08 defines.
- Behavior: The loop writes one record for the request and one for the response, each holding its hash and its place in the run's order, and ties both to the run identified by its stamp (SR-15).
- Observable: The ledger holds, for each run counted in a report (IN-18), one record per request and one per response, in send order, each identified by its hash.
- On failure: A request or response that cannot be recorded stops the loop. The run ends without a submit and is void (AG-15), and the failure is recorded.
- Verified by: A test that runs the loop against a stand-in for the agent model and checks that every request and response the stand-in exchanges has a matching record in the ledger, in order and by hash. It catches a run whose reported turns the ledger does not confirm.

**AG-30.** The run record must name every image a deep read gave the agent model.
<!-- id: SDD-AG-30 | tdd: none | status: pending:#45 -->

- Trigger: A deep_read call delivers an image to the agent model (AG-02, MD-11).
- Behavior: The run's record names the paper and the image for each one the response carried, in the order they were sent, alongside the same run's stamp (SR-15).
- Observable: For a run that called deep_read on a paper with a figure, the run's record names that figure for the spot check (IN-11) to read, and the images named match those the tool response carried.
- On failure: An image that cannot be named in the run's record does not reach the agent model, and the omission is recorded with the run.
- Verified by: A test that calls deep_read on a paper with two figures and checks that both are named in the run's record in the order sent, and a test that blocks the naming step and checks that the image is withheld from the response. It catches an image the agent model received that the run's record does not account for.
- Limits: A LaTeX table served as MD-11 describes is text, not an image, and sits outside this requirement.

### 5.4 Selection and mutation

**AG-18.** Selection must run on no generation clock, being evaluated once in each weekly cycle and replacing nothing in a cycle in which no genome has the minimum count of resolved forecasts (FT-14).
<!-- id: SDD-AG-18 | tdd: none | status: pending:#57 -->

- Trigger: The select step of a weekly cycle is reached (FT-16).
- Behavior: Selection is evaluated once and acts only on genomes that have the minimum count of resolved forecasts (FT-14), so a genome below it is neither drawn as a parent nor replaced. A cycle in which no genome has the minimum carries the population over unchanged, and no count of batches, runs or cycles forces a replacement.
- Observable: Each weekly cycle leaves one recorded selection result (FT-13), with each genome's count of resolved forecasts and either the replacements made or the statement that nothing was replaced.
- On failure: When the counts of resolved forecasts cannot be read from the ledger, the cycle replaces nothing and the failure is recorded.
- Verified by: A test that runs a weekly cycle in which every genome is below the minimum count and checks that the population is unchanged, then resolves enough forecasts for one genome and checks that the next cycle's selection proceeds. It catches replacement forced by the calendar alone.
- Limits: The count of resolved forecasts that is enough is the minimum of FT-14, which is not yet set (#6).

**AG-19.** Parents must be sampled by fitness, weighted against those with many children.
<!-- id: SDD-AG-19 | tdd: none | status: pending:#57 -->

- Trigger: Selection proceeds in a weekly cycle (AG-18) and a parent is drawn for a child.
- Behavior: Each parent is drawn at random from the genomes taking part in selection, which are those at or above the minimum count of resolved forecasts (FT-14). The probability of a draw rises with the genome's fitness (FT-12) and falls with its count of children, which are the genomes whose stored diff names it as parent (AG-20).
- Observable: Each draw is recorded with the genome drawn, its fitness and its count of children at the time.
- On failure: When fitness or the counts of children cannot be computed, no parent is drawn, the cycle replaces nothing and the failure is recorded.
- Verified by: A test that draws parents many times from a fixed set and checks that, of two genomes with equal fitness, the one with fewer children is drawn more often, and that, of two with equal children, the fitter is drawn more often. It catches sampling that ignores either term.
- Limits: The weighting against parents with many children is not yet set (#6). Fitness is the measure of FT-12.

**AG-20.** Mutations must be proposed as diffs to a parent genome.
<!-- id: SDD-AG-20 | tdd: none | status: pending:#5 -->

- Trigger: A parent has been drawn (AG-19) and a mutation of it is proposed.
- Behavior: A mutation arrives as a diff against the parent genome and in no other form. The diff is applied to the parent, and the result becomes a child only when it is a complete genome (AG-16) and changes only what AG-03 allows.
- Observable: Every child genome is stored with the diff that made it and the genome hash of its parent, and applying the stored diff to the parent gives the child's genome hash.
- On failure: A diff that does not apply to its parent, or whose result fails these checks, is rejected. No child is made from it and the rejection is recorded.
- Verified by: A test that offers a whole replacement genome in place of a diff and checks that it is rejected, and a test that reapplies each stored diff to its parent and checks that the child's genome hash is reproduced. It catches a child whose change from its parent is not on record.
- Limits: What the mutation prompt carries is an open decision (#13). This requirement says nothing about what the proposer of a diff is shown, and it holds under every option.

**AG-21.** Near-duplicate mutations must be rejected.
<!-- id: SDD-AG-21 | tdd: none | status: pending:#57 -->

- Trigger: A diff has been applied and its result has passed the checks of AG-20.
- Behavior: The child is compared with every genome in the population, using the measure of difference between genomes that FT-15 uses. A child whose similarity to any of them is above the limit is rejected before it enters the population.
- Observable: A rejected child is recorded with the genome it came too close to and the similarity found, and it appears in no run specification.
- On failure: When the similarity cannot be computed, the child is not admitted and the failure is recorded.
- Verified by: A test that proposes a diff whose child equals a genome already in the population and checks that the child is rejected, and a test with a child below the limit that checks it is admitted. It catches a population that fills with copies of one genome.
- Limits: The similarity above which a mutation is a near-duplicate is not yet set (#6). The measure of similarity is the measure of difference between genomes of FT-15, which is also not yet set (#6).

**AG-35.** A mutation of the structured output schema must make one field-level change, adding, removing, renaming, reordering or retyping one field of the extension.
<!-- id: SDD-AG-35 | tdd: none | status: pending:#57 -->

- Trigger: A mutation is proposed as a diff against a parent genome (AG-20) and the diff touches the structured output schema.
- Behavior: The diff changes one field of the extension by one of those five changes and alters nothing else in the structured output schema, so that a parent and its child differ there for one reason. A diff that changes two fields, that replaces the schema, or that reaches the protected core (AG-33) is rejected.
- Observable: The stored diff of every child whose structured output schema differs from its parent's names one field and one of the five changes (AG-20), and the diff at which a field entered a lineage can be read from the stored diffs.
- On failure: The diff is rejected, no child is made from it, the population is unchanged, and the rejection is recorded.
- Verified by: A test that proposes a diff adding two fields at once, and one that renames a field and retypes another, and checks that both are rejected. It catches a child whose structured output schema differs from its parent's for more than one reason.
- Limits: What the step that proposes a mutation is shown is an open decision (#13), and this requirement holds under each of its options.

### 5.5 Exclusion actions

**AG-22.** Exclusion actions must be graduated, applied in this order: quarantine of the run, then quarantine of the lineage, then purge.
<!-- id: SDD-AG-22 | tdd: none | status: pending:#57 -->

- Trigger: A condition that triggers an exclusion action is met for a run or for a lineage.
- Behavior: Quarantine of a run sets its forecasts aside from scoring (FT-12, FT-14). Quarantine of a lineage takes the genome and its descendants out of the population, so they get no runs and take no part in selection, and purge makes that permanent. The steps apply in that order with none skipped, and no ledger record is removed at any step (SR-14).
- Observable: Each run and lineage subject to exclusion has a recorded exclusion action state, and the ledger holds one exclusion action record for each step applied (AG-23), in order.
- On failure: When a step cannot be applied, the state stays at the step before it and the failure is recorded.
- Verified by: A test that attempts to purge a lineage that has not been quarantined and checks that the attempt is refused, and a test that takes one lineage through the three steps and checks the order of its exclusion action records. It catches a step applied out of order.
- Limits: What triggers each exclusion action is not yet set (#6).

**AG-23.** Exclusion actions must be recorded in the ledger.
<!-- id: SDD-AG-23 | tdd: none | status: pending:#57 -->

- Trigger: An exclusion action step is applied (AG-22).
- Behavior: One ledger record is appended for each exclusion action step, with a kind that marks it as an exclusion action (EN-06) and a payload that names the step and the run or lineage it applies to.
- Observable: The ledger holds one exclusion action record for each step applied, inside the hash chain with every other record (EN-05).
- On failure: When the record cannot be appended, the step does not take effect and the failure is recorded.
- Verified by: A test that applies each of the three steps and checks that the ledger gains one exclusion action record per step and that the hash chain still verifies. It catches an exclusion action held only in working state, where it could be changed or lost without trace.

**AG-24.** Exclusion actions must not be mentioned in any prompt.
<!-- id: SDD-AG-24 | tdd: none | status: pending:#57 -->

- Trigger: A prompt is assembled, for an agent run or for any other call to a language model.
- Behavior: Prompt assembly takes no input from exclusion action records or exclusion action state. The text it produces names no exclusion action, quarantine or purge.
- Observable: For the same genome and batch, the prompt sent to the agent model is identical whether or not any exclusion action has been applied.
- On failure: A prompt found to mention an exclusion action is not sent, and the failure is recorded.
- Verified by: A test that quarantines a run and then a lineage, assembles the prompts for the next batch, and checks that they are byte for byte what they are with no exclusion action applied. It catches exclusion action state reaching the agent model, which could then shape its behavior around it.

## 6. Reader

### 6.1 Paper cards

**RD-01.** The reader must maintain exactly one current paper card for each paper in the corpus.
<!-- id: SDD-RD-01 | tdd: none | status: pending:#54 -->

- Trigger: A paper enters the corpus.
- Behavior: The reader asks the shared model service (PL-08) for the paper's model outputs and gathers the active signals of RD-06 to RD-13 and the Jev assessment result or unavailable status of RD-15 to RD-21 into one text record, the paper card, stored under the paper's id. A paper card produced again for the same paper replaces the current view; earlier versions referenced by a snapshot remain immutable (RD-21).
- Observable: Each paper in the corpus has one current paper card found by its id, or a recorded failure; immutable historical versions remain accessible only through their version references.
- On failure: A missing or failed Jev assessment alone leaves the base paper card available with an unavailable status and reason (RD-18). When another failure prevents completion of a paper card, it stores nothing for that paper, leaves any earlier paper card in place and records the failure with the paper's id.
- Verified by: A check that counts paper cards against papers in a snapshot and fails when a paper has more than one paper card, or has no paper card and no recorded failure. A provider-failure test checks that the base card survives with an unavailable assessment, and a rebuild test checks that earlier snapshots retain their card versions.
- Limits: When a paper card is produced again, after a promotion (PL-14) or once a signal that was absent exists, is not yet set (#6).

**RD-02.** Every model-produced number on a paper card must carry its producing model identity.
<!-- id: SDD-RD-02 | tdd: none | status: pending:#54 -->

- Trigger: The reader writes a small-model number or a Jev assessment onto a paper card.
- Behavior: Jev numbers use the provider/model identity and pinning status of RD-19, including for a mutable provider alias. For small-model numbers, the reader writes beside the number the id of the model that produced it: the embedding model or one prediction head, as the shared model service (PL-08) served it when the number was produced. The id sits beside the number itself and not once for the whole paper card.
- Observable: On any stored paper card, each number from a small model has a model id beside it in the paper card's text.
- On failure: A Jev result without the required identity provenance becomes unavailable (RD-19). For a small-model number with no producing identity, neither the number nor a stand-in is written, and the paper card is not completed (RD-01).
- Verified by: A check that reads every paper card in a snapshot and fails on a model-produced number with no id beside it. A test that changes the served model and fails when a paper card produced afterwards still carries the earlier id.
- Limits: The encoder's vector joins the paper card's numbers only once that layer is measured back in (SR-17, #51).

**RD-03.** Every small-model number on a paper card must be stamped with its model-state date and measured accuracy, while Jev assessments carry the provenance and qualification references of RD-19 and RD-22.
<!-- id: SDD-RD-03 | tdd: none | status: pending:#54 -->

- Trigger: The reader writes a small-model number or a Jev assessment onto a paper card.
- Behavior: A hosted Jev assessment carries its computation time, returned or configured model identity, pinning status and per-field qualification reference; it has no invented checkpoint date. For small-model numbers, the reader writes beside the number the producing model's model-state date, and the model's measured accuracy as of the snapshot, taken from the accuracy measure SR-27 names for it. For a prediction head this is its fit date (FT-10); for the embedding model it is its adopted checkpoint date.
- Observable: On any stored paper card, each number from a small model has a model-state date and a measured accuracy beside it, next to the model id of RD-02.
- On failure: A Jev result with missing required provenance becomes unavailable (RD-19). For a small-model number, when its model-state date or measured accuracy is not known, the reader writes neither the number nor a stand-in for either, and the paper card is not completed (RD-01).
- Verified by: A test that promotes a new checkpoint (PL-14), produces a paper card and fails when a number carries any date other than that checkpoint's or an accuracy value other than the one SR-27's measure recorded for it as of the snapshot. It catches a stale date and an accuracy value carried over from an earlier checkpoint.

**RD-04.** An agent run must receive paper cards as text.
<!-- id: SDD-RD-04 | tdd: none | status: pending:#57 -->

- Trigger: An agent run calls a tool that returns paper cards (AG-09).
- Behavior: The reader renders each paper card as text that a person can read as it stands: each signal under a label, with its value and its stamps (RD-02, RD-03) beside it. The tool returns that text unchanged.
- Observable: The response a run receives for a paper card is readable text and matches the paper card held in the snapshot the run reads.
- On failure: A paper card that cannot be rendered as text is not stored (RD-01), so no run receives it.
- Verified by: A test that calls each tool that returns paper cards against a snapshot and fails when a response carries a paper card in any other form, such as an encoded binary block or a pointer to stored model output.

**RD-05.** The reader must keep raw vectors from an agent run.
<!-- id: SDD-RD-05 | tdd: none | status: pending:#57 -->

- Trigger: An agent run calls any of its tools (AG-09).
- Behavior: What the small models produce reaches a run only as the text of paper cards (RD-04): derived values such as a neighbor list, a distance or a probability. A raw vector, the list of numbers the encoder or the embedding model outputs for a text, appears on no paper card and in no tool response.
- Observable: No paper card in a snapshot and no response to a run holds a raw vector. A tool call that asks for one gets a refusal.
- On failure: A tool call that asks for a vector fits no tool schema (AG-11) and is refused. The run receives the refusal and nothing else.
- Verified by: A test that calls every tool a run is allowed for a paper whose vectors are known and fails when any stretch of those vector values appears in a paper card or a response.

**RD-14.** A discovery service's ranking or recommendation of a paper must not appear on a paper card or in a tool response.
<!-- id: SDD-RD-14 | tdd: none | status: pending:#57 -->

- Trigger: The reader produces a paper card for a paper (RD-01), or a tool call returns a response about a paper (AG-09).
- Behavior: Nothing a discovery service ranked or recommended about a paper is written onto its paper card or returned in a response from any tool (RD-04). A count taken at the snapshot under RD-12 that happens to reflect a service's own feature stays on the paper card, and only the service's ranking or recommendation itself is withheld.
- Observable: No stored paper card and no tool response names a discovery service's rank or its recommendation of a paper.
- On failure: A value that would carry a discovery service's ranking or recommendation is left off the paper card and off every tool response. The paper card is completed without it (RD-01).
- Verified by: A test that supplies ingest with a discovery service's ranking for a known paper, produces its paper card and a tool response, and fails if either shows the ranking or a recommendation derived from it.

### 6.2 Signals

**RD-06.** A paper card must list the paper's nearest neighbors in the corpus.
<!-- id: SDD-RD-06 | tdd: none | status: pending:#57 -->

- Trigger: The reader produces a paper card for a paper (RD-01).
- Behavior: The reader lists on the paper card the papers in the corpus whose vectors lie nearest to this paper's vector, nearest first, each by its paper id. All vectors compared come from the same model at the same checkpoint.
- Observable: A stored paper card shows an ordered list of paper ids, none of them the paper itself.
- On failure: When the neighbors cannot be found, or the vectors at hand come from more than one checkpoint, the paper card is not completed (RD-01).
- Verified by: A test over a small corpus with known vectors that fails when the listed neighbors are not the nearest papers in order, when the list holds the paper itself, or when it holds an id absent from the corpus.
- Limits: The count of neighbors on a paper card and the measure of nearness are not yet set (#6). The test cannot be written until they are.

**RD-07.** A paper card must give the paper's embedding distance.
<!-- id: SDD-RD-07 | tdd: none | status: pending:#57 -->

- Trigger: The reader produces a paper card for a paper (RD-01).
- Behavior: The reader writes on the paper card one number, the embedding distance: how far the paper lies from the papers already in the corpus, by the measure in Limits, over the same vectors that give its neighbors (RD-06). The number carries the stamps of RD-02 and RD-03.
- Observable: A stored paper card shows one embedding distance with its stamps.
- On failure: When the distance cannot be computed, no stand-in number is written and the paper card is not completed (RD-01).
- Verified by: A test over a small corpus with known vectors that computes the embedding distance by the set measure and fails when the paper card's number differs, or when the paper card shows no embedding distance or more than one.
- Limits: The embedding distance measure is not yet set (#6). The test cannot be written until it is.

**RD-08.** A paper card must give the probability that each prediction head outputs for the paper.
<!-- id: SDD-RD-08 | tdd: none | status: pending:#57 -->

- Trigger: The reader produces a paper card for a paper (RD-01).
- Behavior: For each prediction head the shared model service serves, the reader asks for the paper's probability and writes it on the paper card, labelled with the outcome that prediction head predicts and stamped under RD-02 and RD-03. While no prediction head is served, the paper card says in words that no prediction head probability exists and gives no number.
- Observable: A stored paper card shows one labelled probability from 0 to 1 for each prediction head in service when the paper card was produced, or the statement that there is none.
- On failure: When a prediction head is served and the reader cannot get its probability, the paper card is not completed (RD-01). A missing probability is never written as 0 or as any stand-in number.
- Verified by: A test that serves a known set of prediction heads, produces a paper card and fails when the paper card lacks a served prediction head, shows a prediction head not served or shows a value that differs from the prediction head's output. A second pass with no prediction head served fails when any probability appears.
- Limits: Which probabilities the prediction heads output is open (#16), so the paper card gives whichever prediction heads exist. Whether the prediction heads start pre-fit is open (#7), and if they start empty a paper card carries no prediction head probability until prediction heads are fit.

The id RD-09 is reserved by #49: masked-LM surprise score leaves the paper card while weekly fine-tuning of the encoder is held out (SR-17, #51).

**RD-10.** A paper card must give the paper's graph features.
<!-- id: SDD-RD-10 | tdd: none | status: pending:#57 -->

- Trigger: The reader produces a paper card for a paper (RD-01).
- Behavior: The reader writes on the paper card the paper's graph features, each a labelled value computed from the citation graph (MD-07, MD-08) as it stands when the paper card is produced. No small model produces a graph feature, so RD-02 and RD-03 place no stamp on it.
- Observable: A stored paper card shows each graph feature by name with its value.
- On failure: When the citation graph cannot be read, the paper card is not completed (RD-01). A feature is never written as 0 because the graph could not be read.
- Verified by: A test that builds a small citation graph of known structure, produces a paper card for a paper in it and fails when a listed feature is missing or its value differs from the value worked out by hand.
- Limits: Which graph features a paper card gives is not yet set (#6).

**RD-11.** A paper card must give, for the paper's nearest earlier neighbors, the outcomes that resolved before the snapshot.
<!-- id: SDD-RD-11 | tdd: none | status: pending:#57 -->

- Trigger: The reader produces a paper card for a paper (RD-01).
- Behavior: Among the papers nearest to this paper's vector (RD-06), the reader keeps those that entered the corpus earlier than this paper, and for each earlier neighbor writes on the paper card the outcomes recorded for it whose resolution record predates the snapshot. An earlier neighbor with no such outcome is listed with none.
- Observable: A stored paper card shows, beside each earlier neighbor, the outcomes resolved for it before the snapshot, or a statement that it has none.
- On failure: When an earlier neighbor's resolved outcomes cannot be read, the paper card is not completed (RD-01).
- Verified by: A test over a small corpus with known arrival dates and known resolution dates that fails when a later-arriving paper appears among the earlier neighbors, when a listed outcome resolved after the snapshot, or when an outcome resolved before the snapshot is missing from the paper card.
- Limits: The count of earlier neighbors a paper card gives is not yet set (#6).

**RD-12.** A paper card must give, taken at the snapshot, the authors' prior citation counts and the paper's early repository and Hugging Face counts.
<!-- id: SDD-RD-12 | tdd: none | status: pending:#57 -->

- Trigger: The reader produces a paper card for a paper (RD-01).
- Behavior: The reader writes on the paper card, each taken at the snapshot: the prior citation count of each author, and the paper's own repository count and Hugging Face count. No small model produces these counts, so RD-02 and RD-03 place no stamp on them.
- Observable: A stored paper card shows an author citation count for each author, and a repository count and a Hugging Face count for the paper, all as they stood at the snapshot.
- On failure: When a count cannot be read as of the snapshot, the paper card gives no number for it and says in words that the count is absent.
- Verified by: A test that freezes a snapshot with known counts, produces a paper card and fails when a listed count differs from the snapshot's value, or when a count taken after the snapshot appears on the paper card.
- Limits: Whether any source gives these counts live is open (#22).

**RD-13.** A paper card must give the distance between the paper's vector and the mean vector of the papers it cites.
<!-- id: SDD-RD-13 | tdd: none | status: pending:#57 -->

- Trigger: The reader produces a paper card for a paper (RD-01).
- Behavior: The reader takes the vectors of the papers this paper cites in the citation graph (MD-07, MD-08), computes their mean, and writes on the paper card the distance between the paper's own vector and that mean, by the same measure of nearness that RD-06 and RD-07 use. The number carries the stamps of RD-02 and RD-03.
- Observable: A stored paper card shows one such distance, labelled apart from the embedding distance of RD-07.
- On failure: When the paper cites no paper with a known vector, or the distance cannot be computed, no stand-in number is written and the paper card is not completed (RD-01).
- Verified by: A test over a small citation graph with known vectors that computes the distance by hand and fails when the paper card's number differs, or when the paper card shows more than one such distance.
- Limits: The measure of nearness this number uses is the one RD-07's Limits leaves not yet set (#6). The test cannot be written until it is.

### 6.3 Jev launch assessments

The rubric is project-specific. It describes supplied paper content and does not certify scientific correctness, novelty, reproducibility or future impact. The provider's Choice and confidence interfaces were verified on 2026-09-20 against [Primitives](https://docs.typesafe.ai/primitives) and [Confidence](https://docs.typesafe.ai/confidence); provider access, limits and operating values remain the readiness gates in RD-24.

The fixed rubric used by RD-16 is:

| Field | Categories and meaning |
| --- | --- |
| Primary contribution | Method/system; dataset/resource; benchmark/evaluation method; theoretical result; empirical analysis/replication; synthesis/survey; mixed/other; insufficient information. Mixed applies when no primary contribution dominates. |
| Comparative evaluation | Reports a comparison to an alternative or baseline addressing a contribution; explicitly no such comparison; not reported; not applicable; insufficient information. Presence does not establish fairness or superiority. |
| Ablation/component analysis | Reports isolating a component or design choice's effect; explicitly absent; not reported; not applicable; insufficient information. Presence does not establish causal identification. |
| Uncertainty reporting | Reports variation across repeated measurements, an interval or a statistical test for an empirical result; explicitly absent; not reported; not applicable; insufficient information. Presence does not establish statistical validity. |
| Theoretical support | Supplies a proof or derivation supporting a contribution; states that support is elsewhere; not reported; not applicable; insufficient information. This does not verify a proof. |
| Evaluation beyond the main setting | Reports testing a contribution in another dataset, domain, environment or operating condition; explicitly limited to the main setting; not reported; not applicable; insufficient information. This does not establish generalization. |
| Artifact availability statement | Claims an implementation, data or model artifact is available; promises future availability only; explicitly unavailable; not reported; not applicable; insufficient information. Available means at least one artifact is claimed available; future-only means none is claimed available and at least one is promised. No external availability is verified by this field. |
| Limitations disclosure | States a concrete assumption, failure case or scope restriction relevant to the contribution; only generic caveats; not reported; insufficient information. A limitations heading alone is not a concrete disclosure. This does not measure completeness or severity. |

**RD-15.** The reader must expose fixed Jev paper-content assessments on paper cards at launch.
<!-- id: SDD-RD-15 | tdd: none | status: pending:#54 -->

- Trigger: A paper card is assembled.
- Behavior: The card includes the eight assessment fields of RD-16 or the unavailable state of RD-18. Agents interpret these as content assessments. No composite quality score, automatic paper exclusion or ranking is derived from them. They do not enter prediction-head inputs (FT-09), deterministic outcome resolution, baseline regression inputs (IN-09) or fitness directly; an agent forecast informed by the assessments is scored normally.
- Observable: Each card labels the assessment source and rubric version separately from forecasts and measured counts.
- On failure: An unavailable assessment is rendered with its reason; a permanent inability to provide the qualified launch feature fails RD-24.
- Verified by: A test checks that each card carries a result or unavailable state, and that changing only assessment fields leaves head inputs, baseline inputs and resolver inputs unchanged.

**RD-16.** Every Jev assessment must use the eight-field rubric in this subsection as a fixed, versioned set of categorical questions.
<!-- id: SDD-RD-16 | tdd: none | status: pending:#54 -->

- Trigger: An assessment request is assembled.
- Behavior: Each table row becomes a separate Choice question with its full category criteria. All questions inspect the same supplied text; contribution type does not gate another question. The rubric carries a version and hash, includes annotated category-boundary examples, and is outside the mutable genome. No question asks for an overall quality, novelty or future-impact score.
- Observable: The stored request contains exactly the eight fields, their category definitions and the rubric hash.
- On failure: A missing field, altered unversioned rubric or attempted agent mutation is rejected and recorded.
- Verified by: A test compares the request against the versioned rubric and rejects an extra quality question, a missing field or a genome-supplied rubric change.

**RD-17.** Jev input must be limited to the immutable paper version's extracted text and recorded extraction coverage.
<!-- id: SDD-RD-17 | tdd: none | status: pending:#54 -->

- Trigger: Ingest prepares an assessment request.
- Behavior: The input contains available paper text, appendices, captions and table text in document order, with extraction coverage. It contains no separately supplied popularity, reputation, discovery rankings, forecasts, other-paper context or generated summary. No external retrieval is performed for the assessment. Embedded author cues and provider pretraining knowledge are not represented as removed. Input is checked against the verified provider limit before sending; no truncation or chunk aggregation is performed.
- Observable: The stored input bytes and coverage identify exactly what text the request supplied.
- On failure: No usable text or input beyond the verified limit produces an unavailable result with a reason, rather than a partial silent request.
- Verified by: A test includes prohibited metadata alongside an allowed extraction and verifies the outbound input excludes it; over-limit and empty inputs produce no provider call.
- Limits: Actual provider input constraints and corpus coverage are verified under RD-24; text-extraction fallback remains open in #29.

**RD-18.** Assessment results must distinguish categorical uncertainty from processing unavailability.
<!-- id: SDD-RD-18 | tdd: none | status: pending:#54 -->

- Trigger: A response is validated or an assessment cannot be obtained.
- Behavior: Each valid field retains its selected category, full probability distribution and provider confidence as a distribution summary, not measured accuracy. Not reported means no qualifying statement in the supplied content; not applicable means no meaningful target for that question; insufficient information means missing content or ambiguity prevents classification. Low confidence is retained without becoming a negative or unavailable result. A processing failure has an unavailable status and reason, without fabricated categories or numbers.
- Observable: The stored and rendered results preserve the category distributions and separate processing status.
- On failure: An invalid response produces unavailable with its validation reason; the base card remains usable under RD-01.
- Verified by: A test supplies low confidence, not reported, insufficient information, malformed probabilities and a timeout, and checks that only invalid or failed processing becomes unavailable.
- Limits: Exact response validation and category-boundary examples belong to the versioned rubric and TDD; no confidence cutoff is introduced.

**RD-19.** Every assessment must preserve its input, rubric, provider and computation provenance.
<!-- id: SDD-RD-19 | tdd: none | status: pending:#54 -->

- Trigger: An assessment attempt completes.
- Behavior: The stored record contains the paper revision, extraction version, exact supplied text and hash, rubric version and hash, configured or returned provider/model identity, sanitized request and response, computation time, coverage, status and error reason. Identity distinguishes an immutable revision from a mutable alias; inability to pin a revision is explicit. No credential headers, invented weight hashes or checkpoint dates are stored.
- Observable: Every assessment field resolves to its exact request, response and qualification reference, with unavailable identity metadata stated explicitly. Provider identity changes are recorded and handled by RD-22.
- On failure: A result whose required provenance cannot be persisted is not exposed as a valid assessment; the failure is recorded.
- Verified by: A test rejects a result missing input provenance and verifies that an alias-only provider produces an explicit unpinned status instead of a fabricated checkpoint stamp.

**RD-20.** Ingest must own bounded Jev requests and the reader must consume only stored results.
<!-- id: SDD-RD-20 | tdd: none | status: pending:#54 -->

- Trigger: Assessment work becomes eligible for processing.
- Behavior: Ingest sends requests through its declared interface and network reach (SR-13). A local work key covers input, rubric and provider configuration; a completed saved result is reused. Configuration supplies validated request timeouts, retry limits and daily cost ceilings. Exhausted limits stop requests and record unavailable results. The reader gains no outbound path, and no fallback provider is introduced. An ambiguous timeout records billing uncertainty rather than claiming exactly-once provider execution.
- Observable: The work record identifies attempts, saved-result reuse and budget consumption; reader output references persisted results.
- On failure: A timeout, provider failure or exhausted budget leaves the base card available with an unavailable assessment. Missing operating limits refuse activation under RD-24.
- Verified by: A test reuses a completed work key without a second request, forces timeout and budget exhaustion, and verifies the base card remains available and the reader cannot reach the provider.
- Limits: Operating limits and budget allocation remain open in #6 and #55 and are required by RD-24.

**RD-21.** An assessment recomputation must leave all earlier snapshot-visible artifacts unchanged.
<!-- id: SDD-RD-21 | tdd: none | status: pending:#54 -->

- Trigger: An assessment or card is rebuilt.
- Behavior: A new result is stored as a new artifact. A card snapshot pins its assessment artifact and rubric and provider provenance. Only artifacts available at the snapshot enter it; a result computed later is eligible only for future snapshots. Updating the current card view does not overwrite a version referenced by a snapshot.
- Observable: An earlier snapshot returns the same card and assessment bytes after recomputation.
- On failure: An attempt to overwrite a referenced artifact or attach a later assessment to an earlier snapshot is rejected and recorded.
- Verified by: A test recomputes an assessment after snapshot creation and verifies that earlier runs still read the original bytes and cannot retrieve the new result.
- Limits: General replay and temporal verification contracts remain open in #32.

**RD-22.** Every rubric field must qualify separately against an independently annotated reference before launch use.
<!-- id: SDD-RD-22 | tdd: none | status: pending:#54 -->

- Trigger: The initial rubric is qualified, the rubric or declared provider/model version changes, or a scheduled recheck runs.
- Behavior: A seeded target-corpus pilot has 200 papers: 50 for rubric development and 150 untouched for qualification. Two annotators label independently without Jev answers, retaining disagreements and adjudicated labels. Per-field multiclass Brier score is compared against class frequencies from development. Before qualification, the rubric, label guide, split and pass/kill criteria are frozen (SR-18). Every field beats its fixed baseline and meets the profile's label-coverage minimum to qualify; repairs use a fresh held-out set.
- Observable: A qualification report names each field, reference, baseline, result and pass/kill disposition. It reports category and contribution-type coverage, confusion matrices, macro-F1, annotator agreement, input coverage, unavailable rates, latency, cost and uncertainty intervals. Separate rare-label challenge sets are reported separately. Aggregate performance cannot conceal a failing field, and provider confidence is not reported as measured calibration.
- On failure: An unqualified field blocks launch of the eight-field feature under RD-24; a failed recheck marks assessments unavailable until requalification rather than silently deleting a field.
- Verified by: A test with seven passing fields and one failing field refuses qualification, and a split-integrity check rejects reuse of development examples for qualification.
- Limits: The 200-paper pilot is an initial workload, not a power guarantee. Exact pass/kill margins, label-coverage minima, uncertainty method and periodic recheck schedule remain open in #6 and #32; activation requires their recorded measurement profile. Provider change monitoring covers mutable aliases without asserting undetectable weight changes are observable.

**RD-23.** The system must preregister and preserve a prospective comparison of agent forecasts with and without Jev assessments.
<!-- id: SDD-RD-23 | tdd: none | status: pending:#54 -->

- Trigger: The launch assessment feature is prepared for activation.
- Behavior: The comparison uses the same prospective questions, paper snapshots, agent model, frozen agent configurations and budgets, differing in exposure to Jev fields. Comparison runs remain separate from the evolving population and contribute neither parents nor selection fitness. Assigned-treatment analysis includes failed or missing delivery. Primary measure and pass/kill thresholds are recorded before runs under SR-18. Analysis accounts for forecasts sharing papers and cohorts. Improved forecasting is not reported before the planned outcome measurement.
- Observable: A preregistration record precedes comparison runs, and each paired input record documents treatment assignment, actual exposure and unavailable results.
- On failure: Missing preregistration blocks launch readiness; immature outcomes leave effectiveness pending and do not become a zero or a success.
- Verified by: A test rejects an unregistered comparison, verifies comparison runs cannot affect selection, and checks that a failed Jev delivery remains in its assigned-treatment analysis.
- Limits: Targets and horizons remain open in #16; comparison sample, forecast metric, dependence-aware analysis and thresholds remain open in #6 and #32. These values are required before launch; mature outcome results are not.

**RD-24.** Launch readiness must require a verified Jev integration and recorded qualification and operating profiles.
<!-- id: SDD-RD-24 | tdd: none | status: pending:#54 -->

- Trigger: The deployment is checked for launch readiness.
- Behavior: The readiness record verifies provider access, permitted input and response retention, provider identity semantics, input constraints, real target-corpus input coverage, configured timeouts/retries/cost ceilings, field qualification (RD-22), and preregistered forecast comparison (RD-23). Missing access or a permanently unavailable or unqualified feature blocks the promised launch. Transient failures after qualification use RD-18 and do not stop the daily pipeline. The SR-17 exception applies only to waiting for downstream forecast outcomes, not to these checks or SR-18.
- Observable: The readiness record links dated evidence and the exact active profiles, rubric and provider configuration.
- On failure: A missing readiness item blocks launch and names the unmet item without supplying a guessed default.
- Verified by: A check removes each required item in turn and verifies launch refusal; another supplies all items with immature forecast outcomes and verifies readiness.
- Limits: Provider findings are tracked by #59, integration by #60, qualification by #61 and comparison by #62; #6, #16, #29, #32 and #55 retain their existing decisions.

## 7. Models

### 7.1 Encoder and embedding model

**MD-01.** The system must be built on a BERT encoder, meaning a bidirectional encoder pretrained by masked-word prediction.
<!-- id: SDD-MD-01 | tdd: none | status: pending:#57 -->

- Trigger: An encoder is adopted for the system.
- Behavior: The encoder that the shared model service serves (PL-08) is a BERT encoder. Weekly fine-tuning of it and its part of the prediction head features (FT-09) are held out of the first build under SR-17 and #51, until the prediction heads fit on the frozen embedding model's vector alone have been measured.
- Observable: The record of a borrowed component (SR-20) names the encoder with its verification date, and the model id the shared model service reports for the encoder (PL-08) names the same model.
- On failure: A model that is not a BERT encoder is not adopted as the encoder, and the refusal is recorded. Nothing is served or trained from it.
- Verified by: A check that reads the adopted model's published configuration and fails when the model is not a bidirectional encoder that predicts masked words. It catches a decoder-only language model or an embedding-only model put in the encoder's place.

**MD-02.** The system must not train a model from scratch, that is, from weights that do not descend from published weights.
<!-- id: SDD-MD-02 | tdd: none | status: pending:#57 -->

- Trigger: A batch job that trains a model starts.
- Behavior: Every model the system trains starts from published weights or from a checkpoint that descends from them, never from weights the system initialized itself. The prediction heads are fit under FT-08, have no published weights to start from, and fall outside this rule.
- Observable: The record of a borrowed component (SR-20) names the published weights that each trained model starts from. A training job given no starting weights refuses to run, and the refusal is recorded with the job (PL-16).
- On failure: If the starting weights cannot be loaded, the job stops and records the failure (PL-16). No checkpoint is produced and no newly initialized weights take their place.
- Verified by: A test that starts a training job with its starting weights withheld and checks that the job refuses and produces no checkpoint. It catches a job that falls back to newly initialized weights.

**MD-03.** The system must start from the BERT encoder that is the latest available on the date its adoption is checked.
<!-- id: SDD-MD-03 | tdd: none | status: pending:#5 -->

- Trigger: An encoder is adopted for the system.
- Behavior: Before adoption, the BERT encoders with published weights that IN-25 allows the system to use are compared by release date, and the most recently released one is chosen. The rule applies at the moment of adoption and does not reopen the choice when a later encoder is released.
- Observable: The record of a borrowed component (SR-20) names the chosen encoder and carries the date on which it was checked to be the latest available.
- On failure: An encoder whose record carries no dated check is not adopted, and neither serving nor training starts from it.
- Verified by: A review of that record against the release dates of BERT encoders published by the check date. It catches a record with no check date and an encoder chosen out of habit when a later one was already available.
- Limits: Which encoder counts as the latest at adoption is the open model pick (#15).

**MD-04.** The trainable encoder must be ModernBERT-base.
<!-- id: SDD-MD-04 | tdd: none | status: pending:#57 -->

- Trigger: The encoder is adopted for the system.
- Behavior: ModernBERT-base is adopted from its published weights as the encoder, and the shared model service serves it (PL-08). Weekly fine-tuning of it is held out of the first build under SR-17 and #51.
- Observable: The model id the shared model service reports for the encoder (PL-08) names ModernBERT-base.
- On failure: If the published weights cannot be obtained or loaded, adoption stops and the failure is recorded. No other encoder is put in its place.
- Verified by: A test that reads the encoder's model id as the shared model service reports it and fails when it names any encoder other than ModernBERT-base or a checkpoint descended from it.
- Limits: The pick awaits the owner's confirmation (#15). Weekly fine-tuning of it is held out of the first build under SR-17 and #51. Two facts stay open for when training resumes: whether its license allows continued fine-tuning and kept checkpoints (#23), and the end date of its training data (#24).

The id MD-05 is reserved by #27: a second trainable encoder kept as a swap is held out of the first build.

**MD-06.** The frozen embedding model must be SciEmbed sciembed-ctx.
<!-- id: SDD-MD-06 | tdd: none | status: pending:#57 -->

- Trigger: The embedding model is adopted for the system.
- Behavior: SciEmbed sciembed-ctx is adopted from its published weights as the embedding model. The shared model service serves it (PL-08) and its weights stay as published (FT-06).
- Observable: The model id the shared model service reports for the embedding model (PL-08) and the id stamped on any embedding model number on a paper card (RD-02) name SciEmbed sciembed-ctx.
- On failure: If the published weights cannot be obtained or loaded, adoption stops and the failure is recorded. No other embedding model is put in its place.
- Verified by: A test that reads the embedding model id as the shared model service reports it and as stamped on a newly produced paper card, and fails when either names any other embedding model.
- Limits: The pick awaits the owner's confirmation (#15). Whether SciEmbed serves this corpus better than general-purpose embedding models has not been compared (#25).

**MD-12.** Neighbor retrieval must be measured on a fixed task, whether a paper's own references rank above random earlier papers, and reported for each embedding model version.
<!-- id: SDD-MD-12 | tdd: none | status: pending:#57 -->

- Trigger: An embedding model version is adopted for the system (MD-06).
- Behavior: For a fixed sample of papers, the task ranks each paper's neighbors (RD-06) and checks whether its own references (MD-07, MD-08) rank above a matched set of random earlier papers. Every reference and every random paper compared existed in the corpus on the paper's own arrival day. This gives SR-27 its measure, reference and schedule.
- Observable: A stored result names the embedding model version it ran against, the count of papers in the sample, and how references ranked against random earlier papers.
- On failure: When a paper's arrival day cannot be established, or a reference or a random paper drawn for it cannot be confirmed to have existed in the corpus by that day, the paper is left out of the sample and the omission is recorded.
- Verified by: A test with a fixture corpus of known arrival days and citation links that fails when the recorded result counts a reference or a random paper that had not yet arrived by the paper's arrival day, or omits a paper whose full comparison set had arrived.
- Limits: The same vectors and measure of nearness also give the embedding distance (RD-07). The size of the fixed sample and the draw of random earlier papers are not yet set (#6). The comparisons that use this measure rest on open issues #25 and #36, undecided here.

### 7.2 Citation graph

**MD-07.** The citation graph must be built from the system's own parse of arXiv LaTeX bibliographies.
<!-- id: SDD-MD-07 | tdd: none | status: pending:#5 -->

- Trigger: The LaTeX source of a new paper arrives through ingest (SR-13).
- Behavior: The system parses the bibliography in the paper's source, matches each entry to a paper identifier where it can, and adds one edge from the citing paper to each matched paper. An entry that matches nothing adds no edge.
- Observable: After a paper is parsed, the citation graph holds an edge from that paper to each reference that was matched, and no edge for an entry that was not.
- On failure: If a paper has no LaTeX source or its bibliography cannot be parsed, the parse adds no edges for that paper and the failure is recorded against the paper. Other papers are parsed as usual.
- Verified by: A test that parses a paper source whose bibliography is known, with every outside provider withheld, and checks that the graph gains exactly the expected edges. It catches a graph filled only from an outside provider and edges made up for entries that match nothing.
- Limits: The source awaits the owner's confirmation (#15). The share of parsed entries that match a paper has not been measured (#26).

**MD-08.** The citation graph must also draw on the Semantic Scholar Graph API.
<!-- id: SDD-MD-08 | tdd: none | status: pending:#5 -->

- Trigger: Ingest stores a response from the Semantic Scholar Graph API about a paper in the corpus.
- Behavior: Citation links in the response add edges to the same citation graph that MD-07 builds. They add edges and remove none, and ingest is the only component that calls the provider (SR-13).
- Observable: The ledger holds the hash of the raw response (EN-07), and the citation graph holds the edges that the response gives.
- On failure: When the provider cannot be reached, refuses a request under its rate limits, or returns a response that cannot be read, no edge is added from that request and the failure is recorded. The graph keeps the edges it already has.
- Verified by: A test that supplies a stored provider response with a citation link absent from the parsed bibliographies and checks that the edge appears, then supplies an unreadable response and checks that the graph is unchanged. It catches a graph that ignores the provider and edges taken from a broken response.
- Limits: The provider awaits the owner's confirmation (#15).

### 7.3 Figures and tables

The id MD-09 is reserved by #27: a third citation source is held out of the first build.

**MD-10.** The system must not run an optical character recognition model.
<!-- id: SDD-MD-10 | tdd: none | status: pending:#57 -->

- Trigger: A container image is built, or a component handles a figure or a table from a paper.
- Behavior: No component loads or calls an optical character recognition model. The system does not turn figures or tables into recognized text, and they reach the agent model as MD-11 describes.
- Observable: The pinned inputs of every container image (PL-06) include no optical character recognition model, and no paper card or deep_read response carries text recognized from a figure.
- On failure: Content that cannot be read without such a model is left out and named as missing, and no recognized text is put in its place. A container image found to include such a model is not run, and the finding is recorded.
- Verified by: A check of the pinned inputs of every container image that fails when an optical character recognition model is among them. It catches a component that turns a figure into recognized text before the agent model sees it.

**MD-11.** A paper's figures and LaTeX tables must go to the agent model on a deep read of that paper.
<!-- id: SDD-MD-11 | tdd: none | status: pending:#5 -->

- Trigger: A run calls the deep_read tool (AG-09) on a paper in its snapshot.
- Behavior: The deep_read response attaches the paper's figures and its tables as LaTeX source, taken from the paper's source in the run's snapshot, and the run passes them to the agent model. The attached content is paper content and is handled as IN-23 describes.
- Observable: The deep_read response for a paper that has figures and LaTeX tables contains each of them, and the next request the run sends to the agent model carries them.
- On failure: If the paper has no source, or a figure or table cannot be extracted, the response carries what was extracted and names each missing item, and the failure is recorded with the run (AG-02). Nothing is recognized or redrawn in its place (MD-10).
- Verified by: A test that calls deep_read on a paper with one known figure and one known LaTeX table and checks that both reach the agent model. It catches a deep read that sends text alone and one that sends a table as text recognized from a picture of it.

## 8. Fitting and training

### 8.1 Encoder fine-tuning

This subsection is empty in the first build. Weekly fine-tuning of the encoder is held out until the configuration without it has been measured on the same score (SR-17). The requirement ids it would use, FT-01 to FT-05, are reserved by #51, which decides when the layer enters.

### 8.2 Embedding model and agent model

**FT-06.** The embedding model must never be trained.
<!-- id: SDD-FT-06 | tdd: none | status: pending:#57 -->

- Trigger: Any step of the daily cycle or the weekly cycle that uses the embedding model.
- Behavior: The embedding model's weights are loaded and only read. No training job, prediction head fit or calibration updates them, and no step writes a changed copy of them.
- Observable: The embedding model's stored weights are identical before and after every weekly cycle, and the embedding model id and checkpoint date stamped on paper cards (RD-02, RD-03) stay the same from cycle to cycle.
- On failure: A step that would write to the embedding model's weights stops, nothing from it is accepted, and the failure is recorded. The last accepted state stays in service (PL-13).
- Verified by: A test that runs a full weekly cycle on a fixture corpus and fails if the embedding model's weights afterwards differ from the weights before it, which catches a training job that updates both models together.

**FT-07.** The agent model's weights must never be trained.
<!-- id: SDD-FT-07 | tdd: none | status: pending:#5 -->

- Trigger: Any batch job that is defined or started, and any call a component makes to the agent model.
- Behavior: No batch job or service trains, fine-tunes or otherwise updates the agent model's weights, and no component calls a training interface for it. The agents change only through selection and mutation of genomes (FT-12, AG-06).
- Observable: The batch job records (PL-16) hold no job that trains the agent model, and the declared service interfaces (PL-02) include no training interface for it.
- On failure: A batch job or call found to train the agent model is stopped, its output is discarded, and the finding is recorded.
- Verified by: A check that reads every batch job definition and every declared interface of the deployment (PL-02, PL-03) and fails if any of them trains or fine-tunes the agent model, for example a job that tunes it on run traces (SR-02).

### 8.3 Prediction heads

**FT-08.** The prediction heads must be models of one configured family over frozen features, chosen by a comparison written down before it ran.
<!-- id: SDD-FT-08 | tdd: none | status: pending:#57 -->

- Trigger: A prediction head is fit, for the first time or as a refit (FT-10).
- Behavior: Each prediction head is one model of the family the configuration names, fitted on the features of FT-09 for papers whose outcome is known. The family is set only from a recorded comparison whose criteria were written down before it ran (SR-18), and fitting changes only that prediction head's fitted values, not the encoder body and not the embedding model.
- Observable: Each promoted prediction head takes the FT-09 feature vector as its only input and returns a probability between 0 and 1 through the shared model service. The configured family, and the comparison record behind it, are stored and name the same family the fitted prediction heads belong to.
- On failure: A prediction head that cannot be fit, including for lack of known outcomes, is not promoted (PL-14). A fit with no configured family, or with a family no recorded comparison chose, does not run. Each failure is recorded and the last accepted prediction heads, if there are any, stay in service (PL-13).
- Verified by: A test that fits the prediction heads on a fixture set and fails if the encoder body or embedding model weights change during the fit, if a fitted prediction head belongs to a family other than the configured one, or if a family with no recorded prior comparison is accepted.
- Limits: The model family of the prediction heads and the comparison that chooses it: not yet set (#6). Whether the prediction heads start pre-fit on historical outcomes is open (#7), and this requirement holds either way. Which probabilities the prediction heads output on day one is open (#16), so the count of prediction heads and what each predicts are not stated here.

**FT-09.** The prediction head features must be the frozen embedding model's vector for the paper and nothing else.
<!-- id: SDD-FT-09 | tdd: none | status: pending:#57 -->

- Trigger: Features are built for a paper, when the prediction heads are fit (FT-10) and when prediction head probabilities are produced for a paper card (RD-08).
- Behavior: The feature vector for a paper is the embedding model's vector for that paper. Nothing else enters the features, fitting and paper card production build them the same way, and the vector is stored with the date it was computed so that a fit can select by date (FT-17).
- Observable: The length of a prediction head's input equals the length of the embedding model's vector, and the stored vector for a paper carries a computation date and does not change once it is stored.
- On failure: If the vector is missing for a paper, no feature vector is built for it, no value is substituted, and the failure is recorded.
- Verified by: A test that builds features for fixture papers and fails if a feature vector is anything other than the embedding model's vector for that paper, for example a substitute for a missing vector. A second case rebuilds a paper's features after later papers arrived and fails if the vector differs from the one stored at its batch.
- Limits: A vector from the encoder joins the features only once that layer has been measured (SR-17). Whether the prediction heads start pre-fit on historical outcomes is open (#7), and features are built the same way either way. The comparison of SciEmbed with general-purpose embedding models is not done (#25), and this holds for whichever embedding model MD-06 names.

**FT-10.** The prediction heads must be refit once in each weekly cycle.
<!-- id: SDD-FT-10 | tdd: none | status: pending:#57 -->

- Trigger: The refit step of the weekly cycle (FT-16).
- Behavior: Every prediction head is fit again (FT-08) on the features of FT-09 for the papers whose outcome is known at the freeze of that week, and no rating (IN-10) enters the fit. The refit gives the prediction heads their fit date (RD-03), and the prediction heads it produces are calibrated (FT-11) and promoted in one step or not at all (PL-14).
- Observable: The records of each completed weekly cycle hold one refit with its date, and the shared model service serves the prediction heads of one refit and never a mix of two.
- On failure: If the refit cannot complete, no new prediction heads are promoted (PL-14). The shared model service keeps the last accepted prediction heads (PL-13), and the failure is recorded (PL-16).
- Verified by: A test that runs two weekly cycles on a fixture corpus and fails if a cycle that reaches its refit step holds no refit or more than one, if a rating reaches the fit, or if the fit reads a feature value computed after a paper's batch was issued (FT-17).
- Limits: Whether the prediction heads start pre-fit on historical outcomes is open (#7). The refit is the same under either option, and only the set of known outcomes it fits on differs. Whether ratings enter prediction head fitting in a later configuration is open (#46).

**FT-11.** The prediction heads must be calibrated after each refit.
<!-- id: SDD-FT-11 | tdd: none | status: pending:#57 -->

- Trigger: A refit of the prediction heads (FT-10) finishes.
- Behavior: Each refit prediction head's probabilities are calibrated by the method the configuration names, on a held-out set of outcomes that the refit did not use. The method is set only from a recorded comparison whose criteria were written down before it ran (SR-18), and the calibrated prediction heads are the ones offered for promotion (PL-14).
- Observable: The probabilities the shared model service returns after a promotion are the calibrated ones, and the records show a calibration step after each refit and before the promotion, with the method it used.
- On failure: If calibration cannot complete, including when the held-out set is empty or no method is configured, the prediction heads are not promoted (PL-14). The last accepted prediction heads stay in service (PL-13) and the failure is recorded (PL-16).
- Verified by: A test that refits prediction heads on a fixture set whose raw probabilities are known to be off, and fails if the served probabilities are the uncalibrated ones, if the method used is not the configured one, or if any held-out outcome was also used in the refit.
- Limits: The calibration method, the comparison that chooses it and the held-out set the prediction heads are calibrated on: not yet set (#6, #38). Whether the prediction heads start pre-fit on historical outcomes is open (#7), which decides what outcomes exist to hold out at the start.

**FT-17.** A prediction head must be fit only on feature values that were computed and stored no later than the issue of the paper's batch.
<!-- id: SDD-FT-17 | tdd: none | status: pending:#57 -->

- Trigger: A prediction head is fit, for the first time or as a refit (FT-10).
- Behavior: Every stored feature value carries the date it was computed, and the fit reads for each paper only the values dated no later than the issue of that paper's batch, or no later than the paper's arrival day where it never had one. A value computed after that date is not read for that paper, whether it was recomputed or newly added.
- Observable: The record of a fit gives, for each paper it used, the computation date of the feature values it read, and every one of those dates is no later than that paper's cutoff date.
- On failure: A paper with no feature value dated at or before its cutoff date is left out of the fit, no value is substituted, and the omission is recorded. A prediction head that cannot be fit on the papers that remain is not promoted (PL-14) and the failure is recorded.
- Verified by: A test that recomputes a paper's feature values after its batch was issued and fails if the fit reads the recomputed values for that paper, or if a paper whose only values postdate its batch still enters the fit.
- Limits: A paper that never had a batch, because it arrived before the system ran, is dated by its arrival day instead (FT-18). The held-out set the prediction heads are calibrated on is open (#38), and the values that set is built from are dated the same way (FT-11).

**FT-18.** A prediction head that starts pre-fit on historical outcomes must use only features that can be rebuilt as of each paper's arrival day and that no language model produced.
<!-- id: SDD-FT-18 | tdd: none | status: pending:#57 -->

- Trigger: The prediction heads are fit for the first time, on the outcomes of papers that arrived before the system started running.
- Behavior: The fit uses only features whose value can be rebuilt from what was recorded on a paper's arrival day, so a citation count taken today and a link added in a later version stay out. No feature a language model produced enters it, and an embedding whose data end date falls after a paper's arrival day is not used for that paper.
- Observable: The record of the first fit lists the features it used, each with the day its value is dated to and the model that produced it, and no listed feature is dated after its paper's arrival day or produced by a language model.
- On failure: A feature that cannot be shown to meet both tests is left out of the fit and the omission is recorded. A prediction head left with no usable feature or no usable paper is not promoted (PL-14), and the failure is recorded.
- Verified by: A test that offers the first fit a citation count taken today, a repository link added after the paper's arrival and a value produced by a language model, and fails if any of the three enters the fit or reaches a prediction head's input (RD-08).
- Limits: Whether the prediction heads start pre-fit on historical outcomes is open (#7), and this requirement governs the first fit if that option is chosen. How the frozen embedding model is replaced is open (#36), and which papers a pre-fit prediction head can use rests on the embedding model's data end date.

### 8.4 Genome selection

**FT-12.** Genomes must be selected by Brier skill over the baselines.
<!-- id: SDD-FT-12 | tdd: none | status: pending:#57 -->

- Trigger: The score step of the weekly cycle (FT-16), whose result the select step uses.
- Behavior: For each genome the scorer computes the Brier score of its own forecasts that resolved true or false, and the Brier score of each baseline's sealed answers (IN-07 to IN-09, IN-33) to the same questions. Fitness, the value selection uses (AG-19), is computed from the genome's skill over the four baselines, and no rating (IN-10) enters it.
- Observable: The scorer's recorded result for the cycle gives, for each genome, its count of resolved forecasts, its Brier score, each baseline's Brier score, its skill over each baseline and its fitness, beside the score of the mean of the genomes' forecast probabilities (IN-34). Recomputing from the same ledger gives the same values (IN-01).
- On failure: If the scorer cannot compute skill for the cycle, the select step does not run, the population stays as it was, and the failure is recorded.
- Verified by: A test that scores a fixture ledger with known outcomes and fails if a genome's skill over any baseline differs from the value worked out by hand, if another genome's forecasts change it, or if the fitness selection reads differs from the fitness the scorer recorded. A second case adds a rating and the mean forecaster's score and fails if either changes a fitness value.
- Limits: How skill over the four baselines becomes one fitness value, and whether the pick-set non-overlap score (IN-04) enters it, is not yet set (#6). Forecasts of a quarantined run are set aside (AG-22). Whether volunteered forecasts (EN-30), which answer no batch question, enter fitness is not yet set (#6). How the two outcome tracks count toward fitness is open (#11), and skill is computed from the forecasts that count under that decision. Whether ratings enter fitness later is open (#46).

**FT-13.** Genome replacement must happen weekly, as one selection evaluated in each weekly cycle.
<!-- id: SDD-FT-13 | tdd: none | status: pending:#57 -->

- Trigger: The select step of each weekly cycle (FT-16).
- Behavior: Selection is evaluated once in the cycle, over the genomes that meet the minimum count of resolved forecasts (FT-14), and replacement follows AG-18 to AG-21. A cycle in which no genome meets the minimum replaces nothing, and no genome is replaced by selection outside this step.
- Observable: Each weekly cycle leaves one recorded selection result, which gives either the genomes replaced and what replaced them, or a statement that nothing was replaced because no genome met the minimum.
- On failure: If the select step cannot complete, no partial replacement is applied, the population stays as it was, and the failure is recorded.
- Verified by: A test that runs weekly cycles over a fixture ledger and fails if a cycle that reaches its select step evaluates selection more than once or not at all, if selection changes the population between cycles, or if a cycle in which no genome meets the FT-14 minimum replaces a genome.
- Limits: One selection in each weekly cycle. How many genomes a cycle replaces and which leave is not yet set (#6). The minimum count that gates selection is that of FT-14.

**FT-14.** Selection must require a minimum count of resolved forecasts.
<!-- id: SDD-FT-14 | tdd: none | status: pending:#57 -->

- Trigger: The select step evaluates the genomes of the population (FT-13).
- Behavior: The scorer counts, for each genome, its own resolved forecasts that enter its Brier skill (FT-12). A genome below the minimum takes no part in that cycle's selection, so it is not replaced and it is not a parent.
- Observable: The recorded selection result (FT-13) gives each genome's count of resolved forecasts beside the minimum in force, and no genome below the minimum is among those replaced or those chosen as parents.
- On failure: If no minimum is recorded, or the counts cannot be computed from the ledger, the select step replaces nothing and records why.
- Verified by: A test that runs the select step on a fixture ledger where one genome is one resolved forecast short of the minimum and fails if that genome is replaced or chosen as a parent. A second case puts every genome short and fails if anything is replaced.
- Limits: The minimum count of resolved forecasts: not yet set (#6). What removes a genome that never reaches it is not yet set (#6) either.

**FT-15.** Selection must keep a diversity archive.
<!-- id: SDD-FT-15 | tdd: none | status: pending:#5 -->

- Trigger: The select step of a weekly cycle replaces at least one genome (FT-13).
- Behavior: Selection keeps an archive of genomes beside the population. Genomes are held in it for how much they differ from one another under one measure of difference between genomes, so that replacement in the population does not lose them.
- Observable: The archive is a stored set of whole genomes (AG-16) that can be listed after every select step, and the recorded selection result (FT-13) names the genomes added to it.
- On failure: If the archive cannot be updated, the select step applies no replacement, the population and the archive stay as they were, and the failure is recorded.
- Verified by: A test that runs selection on a fixture population with a stand-in measure, where a replaced genome differs from every other genome, and fails if that genome is absent from the archive afterwards or if the archive holds only genomes the measure rates as the same.
- Limits: The measure of difference between genomes: not yet set (#6). It is the same measure that near-duplicate rejection uses (AG-21). What the archive is used for, its size and what admits a genome to it are not yet set (#6) either.

### 8.5 Weekly cycle

**FT-16.** The weekly cycle must run in this order: freeze the week, refit the prediction heads, calibrate, score genomes, select, report.
<!-- id: SDD-FT-16 | tdd: none | status: pending:#57 -->

- Trigger: The end of each week, when that week's cohort of papers is complete.
- Behavior: The six steps run one after another in the stated order, and each starts only when the step before it has finished (PL-17). The refit step reads only feature values stored no later than each paper's batch (FT-17), and the steps that are batch jobs follow PL-11 to PL-17.
- Observable: The records of the cycle show each of the six steps with its start and end, in the stated order, and no step starting before the one before it ended.
- On failure: The cycle does not advance past a step that has not finished, and the failure is recorded. The last accepted prediction heads and population stay in place (PL-13) while the daily cycle continues (PL-12).
- Verified by: A test that runs the cycle on a fixture week and fails if the recorded order differs from the stated order, for example calibration before the refit or selection before scoring. A second run forces one step to fail and fails if any later step runs.
- Limits: Weekly fine-tuning of the encoder, and the re-encoding of the corpus that follows it, are held out of the cycle until the configuration without them has been measured on the same score (SR-17).
