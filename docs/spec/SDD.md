# Software Design Description

What the software must do, stated as requirements a reader can verify.

## Document map

- [Appendix A: Launch profile](#launch-profile)
- [Appendix B: Learning protocol](#learning-protocol)
- [Appendix C: Retrieval protocol](#retrieval-protocol)

## Document control

| Field               | Value                                                                                                                                |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Product             | research-agent: a forward-only research agent for arXiv cs.AI, cs.LG, quant-ph and q-bio, with evidence-defined outcomes and historical prediction-head training; encoder fine-tuning is deferred.        |
| Target version      | First application release.                                                                                                           |
| Scope               | One local deployment with external inference and backup endpoints. What it covers, at what scale, and what it leaves out are stated under Scope and scale.                  |
| Authority           | This document decides what the software does. Where code and this document disagree, one is wrong; say which, with evidence.         |
| Companion documents | [TDD.md](TDD.md) states how each requirement is met. [SPEC-AMENDMENTS.md](SPEC-AMENDMENTS.md) records each change to either.         |
| Change control      | A pull request cites an accepted decision under `docs/decisions/`, edits the exact lines, and appends a row to the amendment ledger. |

## Scope and scale

The software reads every new paper in four arXiv categories with small models, gives a population of the same agent a paper card per paper, and takes from each agent dated forecasts about specified citation events alongside reading recommendations. Forecasts are sealed in a ledger before their outcomes exist and settled later by deterministic resolvers. Each agent configuration, its genome, receives target-specific forecast measurements from that record. The population is divided into three islands by primary category, cs (cs.AI and cs.LG), quant-ph and q-bio; each genome belongs to one island and reads that island's papers (AG-36). Selection and mutation act within an island once the seeded population has completed two fixed weekly cycles, on forecast skill alone (FT-14), with one founder genome per island exempt from replacement (AG-38) and migration between islands recorded in the lineage (AG-37). The three prediction heads estimate indexed first-year citation reach, late-year citation activity and cross-subfield citation reach from frozen embedding vectors; their historical corpus and weekly refitting follow Appendix B: Learning protocol; weekly fine-tuning of an encoder is held out until the system without it has been measured (SR-17, #51). Jev content assessments are held out of the launch until provider access exists (SR-17, #123); their requirements keep their ids and text (RD-15 to RD-24) and downstream semantic labeling is deferred (FT-20). Two raters, one for the cs island and one for the quant-ph island, rate what their island surfaces, through a private app, without seeing where it came from; the q-bio island is scored and never rated, so that the effect of rating on evolution can be told from evolution alone. A rater's ratings reach that island's genomes only as preference credit (IN-43), a weekly selection proxy that never enters the citation-skill score.

- Covers: ingest of the corpus, of outcomes and of discovery-service picks, the small models and their fitting, the reader, the agent runs, the ledger and its resolvers, scoring against the baselines, the seeded agent population and its selection, the digest and human rating, and the platform all of it runs on.
- Scale: one owner-controlled application host, one named provider's hosted agent-model endpoint and an owner-controlled backup/anchor destination under Appendix A: Launch profile. One corpus, arXiv cs.AI, cs.LG, quant-ph and q-bio, each paper compared within its primary category. One population of one agent design in three islands. Two raters, one per rated island. Output that is private to the raters.
- Does not cover: a distributed application cluster, a corpus beyond the four categories, output to the public, a model trained from scratch, or reading papers with an optical character recognition model.

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
- The document states design only. Implementation progress, plans, ordering and evidence live in GitHub issues, `docs/implementation/` and `docs/evidence/`; the trace status is the only implementation state recorded here.
- A cited requirement is never renumbered. A gap in the numbering is an id reserved by an open issue or explicitly reserved by a completed decision. A completed decision preserves an accepted deferral and does not reopen a launch choice.

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

Terms below have the meaning given here throughout the SDD and TDD. Other technical terms keep their usual meaning. A name does not establish a measured property: embedding distance is not scientific novelty, and a submitted probability is not evidence of calibration.

| Term | Meaning |
| --- | --- |
| agent model | The language model an agent run calls. This system does not train its weights (FT-07). |
| assessment confidence | The certainty a model reports for a Jev assessment, summarized from its returned class distribution (RD-18). It is not a forecast probability, and no accuracy is measured for Jev at launch (RD-22). |
| automatic label | A target value computed by a versioned rule over preserved source records. |
| baselines | Popularity, base rate, regression over paper-card features, and nearest-neighbor forecasting (IN-07 to IN-09, IN-33). |
| citation reach | The first-year citation threshold event of EN-12. |
| cohort | Papers of one primary category grouped by ISO publication week in UTC, for reporting and temporal evaluation. |
| cross-subfield citation reach | Citation breadth across provider-assigned subfields; the subfield classification is automatic and fallible. |
| digest | The private collection of selected papers delivered to raters through the rating app. |
| embedding distance | Mean cosine distance from five earlier overview neighbors (RD-07). |
| embedding model | The frozen document embedding model (MD-06). |
| encoder | The BERT encoder adopted under MD-04 for possible fine-tuning, held out of the first build (#51). |
| exclusion action | Quarantine of a run or lineage from scoring or execution, followed by permanent exclusion where AG-22 specifies it. |
| forecast | A dated prediction with evidence ids, a resolvable event statement, a horizon and a forecast probability (SR-07 to SR-10). |
| forecast batch | The daily collection of forecasting questions (EN-09), partitioned into shards per island. |
| founder genome | The one genome per island that FT-14 never replaces (AG-38); it is the no-selection arm of that island. |
| forecast probability | The submitted probability, from 0 to 1, that a forecast's event resolves true by its horizon. |
| genome | An agent configuration as evolutionary search represents it: prompt, scan policy, read policy, probability assignment rule, structured output schema, tools, budgets and sampling settings (AG-16). Selection and mutation by fitness begin after the seeded population's first two weekly cycles (FT-14). |
| horizon | The event window from first public availability: 365 days at launch, followed by a 90-day collection grace period (EN-13). |
| island | The part of the population that reads one domain: cs (primary category cs.AI or cs.LG), quant-ph or q-bio (AG-36). The cs and quant-ph islands each have one rater; the q-bio island is the control and is never rated. |
| ingest | The component that retrieves external data. An agent run's call to its agent model is the other permitted internet path (SR-13). |
| Jev assessment | A fixed, model-derived classification of what a paper reports, under the RD-16 rubric. Held out of the launch until provider access exists (SR-17, #123). |
| late-year citation activity | Citations in both final observation windows (EN-12). |
| ledger | The append-only, hash-chained record used for scoring (EN-06). Its latest record is the chain head. |
| masked-LM surprise score | The deferred masked-language-model signal (RD-09, #49); its formula is not chosen. |
| migration | A mutation whose parent, or whose changed field, comes from another island (AG-37); the lineage records it. |
| model-state date | The checkpoint date of neural weights or the fit date of a prediction head (FT-10), as stamped on model outputs (SR-15, RD-03). |
| operational alert | A diagnostic flag delivered through the rating app (IN-21), with triggers fixed in Appendix A: Launch profile. |
| paper card | The text record the reader produces for one paper. |
| passage embedding | A vector for a source-linked span of extracted paper text, used in retrieval and pooled into the second half of a prediction-head input. |
| pick-set non-overlap score | One minus the overlap between an agent's selected papers and discovery-service selections (IN-04). |
| population | The set of active agent configurations across the three islands. |
| preference credit | The share of a rater's like or dislike on a digest entry credited to each genome whose sealed submission nominated that paper (IN-43); an island's weekly selection proxy and nothing else. |
| primary category | The arXiv primary category of a family's earliest public version: one of cs.AI, cs.LG, quant-ph and q-bio (EN-01). Base rates, calibration, slices and reports are computed within it. |
| prediction head | A calibrated probabilistic outcome model over frozen features (FT-08, FT-11), fitted separately from any encoder. |
| rating app | The private app serving the digest, ratings, detail view and operational alerts (PL-22). |
| reader | The component that assembles paper cards from model outputs and recorded signals. |
| resolver | A function that deterministically settles a forecast as true, false or unresolvable, with evidence. |
| run | One execution of an agent under an immutable run specification. |
| run specification | The record of a run's slot, genome hash, seed, snapshot hash, budgets and allowed tools (AG-17). |
| scorer | The deterministic component that scores forecasts and agent configurations. |
| service pick | A paper selected by a discovery service and captured by ingest on the selection day (EN-38). |
| shared model service | The service producing small-model values for the reader before snapshots; agent runs read stored values through tools (PL-08). |
| shared tool service | The service enforcing the run specification on each tool call and answering from its snapshot (PL-20, PL-21). |
| small models | The embedding model, the prediction heads, and the encoder if its training enters (#51). |
| snapshot | The read-only paper versions, paper cards and citation-graph data frozen when a forecast batch is issued. |
| structured output schema | The schema for the agent model's turns: a fixed protected core and an empty launch extension (AG-32 to AG-35). |

## 1. Architecture and standing rules

### 1.1 Layers

**SR-01.** The system must be layered, from outermost to innermost: infrastructure with measuring, output and observation, then environment, then agents, then reader, then models.
<!-- id: SDD-SR-01 | tdd: TDD-2.1.1 | status: pending:#5 -->

- Trigger: A component is added to the system or its place in the system changes.
- Behavior: Each component is assigned to exactly one of the five layers, and the assignment is recorded. A batch job of fitting and training is recorded instead with the layers it connects.
- Observable: A stored list names every component with its layer, in the order given, and it matches the components that run.
- On failure: A component with no assignment, or with two, is not added, and the gap is recorded.
- Verified by: A check that compares the running components with the stored list and fails when a component is absent from the list or sits under two layers.

### 1.2 Trust in agent output

**SR-02.** The system must verify what an agent did and never what the agent reported.
<!-- id: SDD-SR-02 | tdd: TDD-2.1.2 | status: pending:#5 -->

- Trigger: An agent run makes a tool call, submits or ends.
- Behavior: Every tool call of a run and its result are written to a run trace that is captured outside the agent's control. Each check on a run's conduct, such as its tool use (AG-14) and its budgets (AG-12), reads the trace and never the agent's own account.
- Observable: A stored trace exists for every run, and it lists the calls the run made whatever the agent's text says about them.
- On failure: A check that finds no complete trace for a run fails and records the failure. It does not fall back to the agent's report.
- Verified by: A test in which an agent states that it read a paper it never requested, and that checks that the trace shows no such read and that a check of the run's conduct reports none. It would catch a check that takes the agent's word.

**SR-03.** Every score must be computed without a language model.
<!-- id: SDD-SR-03 | tdd: TDD-2.1.3 | status: pending:#56 -->

- Trigger: The scorer computes a score for a forecast, a genome or a baseline.
- Behavior: The production scorer computes each forecast score from ledger records by a deterministic function (IN-01) and calls no language model. Optional ForeSci judge results are isolated development evaluations under Appendix A: Launch profile and never production scores or fitness.
- Observable: The network reach declared for the scorer (PL-19) includes no language model, and the scorer produces every score with all language models unreachable.
- On failure: A score that cannot be computed from ledger records alone is not recorded, and the failure is recorded.
- Verified by: A test that runs the scorer with every language model unreachable and checks that all scores appear and equal those of a normal run. It would catch a scorer that asks a model to judge a forecast.

**SR-04.** A language model must be limited to proposing or pre-filtering.
<!-- id: SDD-SR-04 | tdd: TDD-2.1.4 | status: pending:#56 -->

- Trigger: A component receives output from a language model.
- Behavior: The output is taken only as a proposal, such as a forecast or a mutation (AG-20), or as a pre-filter that narrows what a deterministic step or a person then decides. Runtime model answers cannot settle, score, select or impose exclusion actions. ForeSci remains isolated development evaluation. Fixed OpenAlex subfield metadata is an explicit machine-assigned proxy for deterministic resolution, not expert ground truth.
- Observable: The components that settle, score, select and apply exclusion actions have no language model within their declared reach (PL-19).
- On failure: A step that settles, scores, selects or applies exclusion actions and cannot complete without a language model stops, and the failure is recorded. No language model output is taken in place of its result.
- Verified by: A test that runs resolution, scoring, selection and exclusion actions with every language model unreachable and checks that the results are unchanged. It would catch a resolver or a selection step that asks a model to decide.

**SR-05.** Every interface to the agent must treat the agent as an untrusted proposer.
<!-- id: SDD-SR-05 | tdd: TDD-2.1.5 | status: pending:#56 -->

- Trigger: An agent run sends a tool call or a submission to another component.
- Behavior: The receiving component validates the message against its schema (AG-11) and the run specification (AG-17) before acting on it. The agent holds no authority: it writes no ledger record itself and changes no prompt, run specification (IN-24) or snapshot content (AG-10).
- Observable: A message that fails validation gets a refusal, and the refusal appears in the run trace (SR-02).
- On failure: The message is refused whole, nothing from it is accepted, and the refusal is recorded.
- Verified by: A test that sends a malformed tool call and a call to a tool outside the run specification, and checks that each is refused and recorded. It would catch an interface that accepts agent input as given.
- Limits: No agent proposes a mutation of its own genome, and agent access to prior records is disabled at launch, under Appendix A: Launch profile.


**SR-06.** An agent's output must be acted on only by the scorer and a human reader.
<!-- id: SDD-SR-06 | tdd: TDD-2.1.6 | status: pending:#56 -->

- Trigger: An agent run submits its output.
- Behavior: Agent output goes to the ledger, and from the ledger to the scoring path (the resolvers and the scorer) and to human readers through the digest (EN-32) and the spot check (IN-11). No other component takes agent output as input.
- Observable: The declared service interfaces (PL-02) show no consumer of agent output other than those.
- On failure: A request for agent output from any other component is refused, and the refusal is recorded.
- Verified by: A check of the declared interfaces that fails when any other component reads agent output, and a test that such a read is refused.
- Limits: No mutation proposer runs and no agent reads another run output at launch; future history access requires an accepted measured extension.
**SR-26.** Agent output must reach a rater only as recorded fields rendered by the app, and never as text that a model wrote for the rater.
<!-- id: SDD-SR-26 | tdd: TDD-2.1.7 | status: pending:#56 -->

- Trigger: Agent output reaches a rater through the digest (EN-32) or the spot-check review view (IN-11).
- Behavior: The app renders each field a run recorded to the ledger exactly as recorded. No component calls a language model to rewrite, summarize or draft prose from that output for a rater to read: the same limit to proposing or pre-filtering that SR-04 sets, and the same rule against an added layer that AG-08 sets inside a run.
- Observable: What a rater receives in a digest or a review view matches, field for field, what a run's record holds, with no passage of text absent from a record, and the digest still carries the label IN-28 requires.
- On failure: A digest or a review view that requires a rewriting step to be produced is not delivered, and the failure is recorded.
- Verified by: A test that builds a digest through an added step that rewrites a run's recorded fields into new prose, and checks that the digest is refused because its text does not match the record. It would catch a display layer drafting text for a rater instead of rendering the record.
- Limits: Every output references source artifact ids, input hash, producer/model/configuration identity, actual computed_at, available_at and snapshot id through the shared manifest envelope in Appendix A: Launch profile.


### 1.3 Forecasts

**SR-07.** Every sealed forecast must cite evidence observed through its authorized input path.
<!-- id: SDD-SR-07 | tdd: TDD-2.1.8 | status: pending:#77 -->

- Trigger: A forecast is submitted for sealing.
- Behavior: For agents, require one to five evidence ids actually retrieved by that run from its snapshot. Baselines cite their preserved snapshot input receipt; human forecasts cite the question/evidence view receipt served to that authenticated rater. A source merely existing in storage is insufficient.
- Observable: Sealed forecasts resolve to their producer-specific observation receipts and immutable snapshot inputs; rejected attempts have errors without sealed forecasts.
- On failure: Missing or unobserved evidence rejects the complete submission atomically under SR-11; lookup outage seals nothing and records operational failure.
- Verified by: A test exercises these cases: Reject a submission citing a snapshot artifact the agent never retrieved and one with no evidence. Accept a baseline/human input receipt only for its authenticated producer and matching snapshot; cross-producer receipts fail.
- Limits: Digest nominations are reading recommendations, separate from the three sealed citation questions; Appendix A: Launch profile fixes the boundary.
**SR-08.** Every forecast must carry a statement that a resolver can settle.
<!-- id: SDD-SR-08 | tdd: TDD-2.1.9 | status: pending:#77 -->

- Trigger: A forecast is submitted for sealing.
- Behavior: Bind every answer to an issued question from the submitting run or authorized human/baseline batch. That immutable question supplies target id/version and resolver version. No volunteered free-text statement creates a launch forecast.
- Observable: The ledger record of a sealed forecast shows which resolver it is bound to, at the version fixed under EN-11.
- On failure: An unknown, unissued or incompatible question rejects the complete submission under SR-11.
- Verified by: A test exercises these cases: Reject free text, an unissued question and a changed target version; a valid question resolves to exactly its pinned resolver.
- Limits: Digest nominations are separate from forecasts; only admitted citation questions are sealed at launch.
**SR-09.** Every forecast must carry a horizon.
<!-- id: SDD-SR-09 | tdd: TDD-2.1.10 | status: pending:#77 -->

- Trigger: A forecast is submitted for sealing.
- Behavior: Resolve the horizon from the immutable issued question identified by the answer. It includes event origin/end and the separate collection deadline under EN-13; the model cannot supply or change horizon values.
- Observable: The ledger record of a sealed forecast holds its horizon.
- On failure: Missing or invalid question/horizon binding rejects the complete submission under SR-11; no generic default or guessed date is filled in.
- Verified by: A test exercises these cases: Reject an unknown question, missing horizon in the registry and an attempted horizon override. A valid question seals its pinned horizon exactly.
- Limits: Only the three 365-day target definitions are admitted at launch; nominations do not create additional forecasts.
**SR-10.** Every forecast must carry a forecast probability from 0 to 1.
<!-- id: SDD-SR-10 | tdd: TDD-2.1.11 | status: pending:#77 -->

- Trigger: A forecast is submitted for sealing.
- Behavior: The sealing step checks that the forecast carries one forecast probability and that the value lies in the range. The value is sealed as submitted.
- Observable: The ledger record of a sealed forecast holds the forecast probability exactly as submitted.
- On failure: A missing, nonfinite or out-of-range probability rejects the entire submission under SR-11; no clipping or defaulting.
- Verified by: A test exercises these cases: Submit a probability above one, below zero, nonfinite or missing beside a valid answer and confirm neither seals; a corrected complete attempt can succeed within the unchanged deadline and budgets.
- Limits: Probabilities range from 0 to 1 inclusive; nomination preference is a separate ordered field.
**SR-11.** An invalid submission must be rejected atomically and preserved as an audit event.
<!-- id: SDD-SR-11 | tdd: TDD-2.1.12 | status: pending:#77 -->

- Trigger: A submission fails shape, coverage, evidence, binding, probability, rationale or deadline validation.
- Behavior: Append submission_rejected with canonical request hash, available run/question ids and safe structured errors; seal no answers or nominations from that attempt. Permit a corrected attempt only within the original budgets/deadlines. Only an accepted complete submission commits forecasts and nominations together; a run ending without one becomes operationally void under AG-15.
- Observable: Rejected attempts have audit events but no forecast/nomination rows; accepted submissions are complete and unique, with no partially sealed subset.
- On failure: If rejection cannot be durably recorded, fail closed and stop the run as an infrastructure failure. Retrying an identical accepted request returns its original receipt; changed bytes under the same idempotency key are refused.
- Verified by: A test exercises these cases: Mix one valid and one invalid answer and confirm no partial writes, then correct before expiry and accept exactly once. Crash before commit, retry the same request and prove one complete result; after expiry correction cannot revive the run.
- Limits: Rationales are limited to 2000 characters and five retrieved evidence ids under Appendix A: Launch profile.


**SR-24.** A submitted forecast must carry a rationale of bounded length that is recorded, never scored, and shown to a rater only after that rater has rated the entry.
<!-- id: SDD-SR-24 | tdd: TDD-2.1.13 | status: pending:#56 -->

- Trigger: A forecast is submitted for sealing.
- Behavior: The rationale is a field of the submit schema, so a call that omits it or exceeds its bound is refused whole (AG-11). The sealing step records it on the forecast apart from the statement bound under SR-08, the scorer never reads it (IN-02), and a rating view withholds it until that rater has rated the entry.
- Observable: The ledger record of a sealed forecast holds its rationale, and a rating view served to a rater before that rater has rated the entry carries no rationale field for it.
- On failure: A submit whose rationale is missing or over its bound is refused and nothing of that call is sealed (AG-11). A rationale that cannot be written to the record of an accepted call leaves the forecast unsealed, and the failure is recorded.
- Verified by: A test that submits a forecast with no rationale and one over the bound and checks that both calls are refused with nothing sealed. A test that checks the score is identical whether the field is present or removed, and that the rating view carries it only after that rater has rated the entry.
- Limits: Rationale text is at most 2000 characters with at most five retrieved source ids, as fixed in Appendix A: Launch profile.
### 1.4 Isolation

**SR-12.** An agent run must reach only the frozen snapshot and the API of the agent model.
<!-- id: SDD-SR-12 | tdd: TDD-2.1.14 | status: pending:#57 -->

- Trigger: An agent run starts.
- Behavior: The run reaches the snapshot named in its run specification (AG-10) through its tools, which also take its submission (AG-09), and calls the API of the agent model. The platform closes every other destination to it, the shared model service (PL-08) included, and all other stored data (PL-19).
- Observable: The reach declared for the run under PL-19 lists those two destinations only, and an attempt from inside the run to reach anything else fails.
- On failure: A run whose isolation cannot be put in place does not start, and the failure is recorded.
- Verified by: A test that, from inside a run, tries to reach an internet address other than the API of the agent model, to call the shared model service and to read stored data outside the snapshot, and checks that every attempt fails.

**SR-13.** External access must be restricted to ingest sources, agent-model calls and the storage backup/anchor receiver.
<!-- id: SDD-SR-13 | tdd: TDD-2.1.15 | status: pending:#56 -->

- Trigger: Any container starts.
- Behavior: The platform gives internet reach to ingest, and gives each agent run one route to the API of the agent model (SR-12). Ingest also mediates Jev paper assessments (RD-20); the reader consumes stored responses. Storage has one authenticated route to the declared backup/anchor receiver. Every other container has no route to the internet, and the platform enforces this from outside the component (PL-19). The rating app is reached over a private network alone, with no internet route either way.
- Observable: The reach declared under PL-19 shows allowlisted source access for ingest, one route for agent runs and one receiver route for storage; all other outbound attempts fail. The rating app's declared reach shows the private network alone, with no internet route in either direction.
- On failure: A container whose reach cannot be set as declared does not start, and the failure is recorded.
- Verified by: A test that attempts an outbound connection from every container other than ingest and checks that each attempt fails, apart from an agent run's model call and storage's declared receiver call. A further test attempts to reach the rating app from the internet and checks that the attempt fails.
- Limits: Apply the exact ingress, egress, backup/anchor and paid-execution policy in Appendix A: Launch profile. An agent run's one route reaches the named provider endpoint fixed there; no relay, second provider, automatic fallback or mutation-model route exists.
### 1.5 Ledger and run records

**SR-14.** The ledger must be append-only.
<!-- id: SDD-SR-14 | tdd: TDD-2.1.16 | status: pending:#72 -->

- Trigger: Any component writes to the ledger.
- Behavior: The ledger accepts a new record at its end and refuses every request to change or remove a record already written.
- Observable: A request to rewrite or delete a record gets a refusal, and the records already written and the hash chain over them (EN-05, EN-06) are unchanged.
- On failure: An append that cannot complete leaves no partial record, and the step that asked for it stops and records the failure.
- Verified by: A test that attempts to overwrite and to delete an existing record through the ledger's interface and checks that both are refused and that the chain still verifies (EN-05).

**SR-15.** Each run must identify the immutable artifacts actually visible in its snapshot.
<!-- id: SDD-SR-15 | tdd: TDD-2.1.17 | status: pending:#64 -->

- Trigger: A run starts.
- Behavior: Record genome hash, seed, agent-model manifest, service-image versions, snapshot hash, paper-card manifest and producing small-model bundle ids before the first call. The agent-model manifest names the provider and the model revision the provider returned for that run. Read small-model provenance from pinned paper cards and bundles, not the active model-service pointer. A deferred encoder is explicitly absent; unavailable prediction heads are recorded as unavailable.
- Observable: The stamp resolves to all producing artifacts even after later promotion.
- On failure: An unresolved required manifest prevents the run; the absence of deferred or unqualified models does not.
- Verified by: A test checks that A queued run using yesterday's paper cards after today's promotion retains yesterday's producing bundle ids and can start without ModernBERT.

**SR-16.** The head of the ledger's hash chain must be anchored in a place outside the system.
<!-- id: SDD-SR-16 | tdd: TDD-2.1.18 | status: pending:#56 -->

- Trigger: Anchoring comes due on its schedule.
- Behavior: The current head hash of the ledger's chain (EN-05), with its sequence number (EN-06), is written to a place that no process of the system can alter.
- Observable: The anchored value can be read from outside the system and compared with the ledger record at the same sequence number.
- On failure: A failed anchoring is recorded, and the previous anchor stays in place.
- Verified by: A test that alters a record in a copy of the ledger, recomputes the chain, and checks that comparing the copy with the anchored head shows the change. It would catch an anchor the system could rewrite along with the chain.
- Limits: Anchor every 15 minutes or 100 records, whichever comes first, using the separate append-only receiver and 30-minute fail-closed rule in Appendix A: Launch profile. The receiver is a separate owner-controlled virtual private server; nightly backups go to object storage.
**SR-23.** A stored value that a component derives must carry the hashes of the inputs it was derived from and the version of the component that derived it.
<!-- id: SDD-SR-23 | tdd: TDD-2.1.19 | status: pending:#72 -->

- Trigger: A component derives and stores a value from other stored values.
- Behavior: The component writes, beside the stored value, the hashes of every input it read and the version of the component that ran. The same stamp already applies to raw responses, paper card numbers, a run and a resolver (EN-07, RD-02, RD-03, SR-15, EN-08). This rule extends it to every other derived value a component stores.
- Observable: A stored value carries beside it the hashes of its inputs and the version of the component that derived it, and a named input hash can be recomputed from what is stored to check that it matches.
- On failure: A value that cannot be stamped with its input hashes and deriving version is not stored, and the failure is recorded.
- Verified by: A test that alters one stored input after a value was derived from it and checks that the input's hash recorded beside the derived value no longer matches the altered input. It would catch a stamp that does not reveal a later change to an input the value was derived from.
- Limits: Each artifact manifest carries schema_version, artifact_hash, ordered input_hashes, producer_version, config_hash and created_at in UTC, under Appendix A: Launch profile; source capture and availability timestamps are separately preserved.

### 1.6 Procedure for change

**SR-17.** A layer must be added only after the configuration without it has been measured on the same score.
<!-- id: SDD-SR-17 | tdd: TDD-2.1.20 | status: pending:#77 -->

- Trigger: A layer, meaning any part added to the running configuration to improve a score, is proposed for addition.
- Behavior: Jev paper-card assessments are held out of the launch until provider access exists (#123); they enter by a later accepted decision, with the RD-22 smoke test, RD-23 preregistration and RD-24 readiness unchanged. Every predictive layer requires a registered baseline on the same primary measure and a comparison with the layer enabled. Pre-runtime measurements use signed, timestamped registration and result artifacts, imported with their original and import times before activation.
- Observable: The activation record resolves to a baseline registration preceding its measurement and to imported comparison evidence committed before the first activated run; the launch record shows the Jev layer held out.
- On failure: A Jev activation without the RD-24 readiness record is refused. For every layer, without the earlier measurement the addition is refused, the configuration stays as it was, and the refusal is recorded.
- Verified by: A test exercises these cases: Try activation without a baseline, with a wrong metric, with a registration after results and with forged backdated import; all fail. A preregistered offline prediction-head/retrieval comparison imported before activation passes its own qualification; a launch configuration exposing Jev fields is refused.
- Limits: Use the preregistered comparison and activation rules in Appendix A: Launch profile; deferred mutations and future prediction heads require their separate versioned admission.
**SR-18.** Pass and kill thresholds must be written down before a comparison runs.
<!-- id: SDD-SR-18 | tdd: TDD-2.1.21 | status: implemented -->

- Trigger: A relied-on comparison inside or outside the system is about to start.
- Behavior: Before the first comparison execution, freeze the primary measure, pass/kill thresholds and comparison plan in the ledger, or in a signed dated pre-runtime registration when the ledger does not yet exist. Import pre-runtime registration and evidence with distinct original and import timestamps before any system reliance; never rewrite either record.
- Observable: Each relied-on result resolves to a registration whose evidenced creation precedes the first comparison execution. Runtime registrations precede run stamps in ledger order; imported artifacts retain their original timing evidence.
- On failure: A comparison with no threshold record is refused and none of its runs start. No result is reported as a pass or a kill without the record.
- Verified by: A test exercises these cases: Reject an unregistered comparison and a registration created after comparison execution starts; accept a verified pre-runtime registration imported later without pretending the ledger existed earlier. Mutation of imported bytes invalidates the evidence.
- Limits: Use the comparison-specific fixed thresholds and preregistration rules in Appendix A: Launch profile and Appendix B: Learning protocol; external comparisons are included.
**SR-19.** Superseded choices must be marked as superseded and kept, not deleted.
<!-- id: SDD-SR-19 | tdd: TDD-2.1.22 | status: pending:#5 -->

- Trigger: A choice recorded in this specification, in a configuration or in a stored record is replaced by a new one.
- Behavior: The earlier choice stays where it was and is marked as superseded. Nothing is removed, and in the ledger the same holds through SR-14.
- Observable: The earlier choice can still be read, with its mark, after the new choice is in place.
- On failure: A change that removes an earlier choice instead of marking it is not accepted, and the earlier choice stays in place.
- Verified by: A check that compares a changed document or configuration with its previous version and fails when a choice present before is absent after, or is changed in place with no superseded mark.

**SR-20.** Every borrowed component and every cited result must carry a verification date.
<!-- id: SDD-SR-20 | tdd: TDD-2.1.23 | status: pending:#5 -->

- Trigger: A borrowed component or a cited result is named in this specification or in a stored record.
- Behavior: The record of a borrowed component, and the entry that names a cited result, each carry a verification date, the date on which the component or the result was last checked against its source.
- Observable: Every borrowed component and cited result that is named shows a verification date beside it.
- On failure: An item with no verification date is recorded as unverified, and no requirement states it as fact until a date is recorded.
- Verified by: A check that lists every borrowed component and cited result named in this specification and fails on any entry that has no verification date and is not recorded as unverified.

**SR-27.** A step that can be wrong must have a named accuracy measure, a reference it is measured against, and a schedule on which it is computed and reported.
<!-- id: SDD-SR-27 | tdd: TDD-2.1.24 | status: implemented -->

- Trigger: A step of the system that can produce a wrong output is added or changed.
- Behavior: The step is given one named accuracy measure, a reference and a schedule, as IN-06 and IN-29 to IN-32 already give the agent-level measures. Jev fields are the named exception: they carry the RD-22 smoke test and are shown as unqualified, with no accuracy measure or reference. A comparison of the step against an alternative follows SR-17 and SR-18. A hand-checked sample the measure uses is drawn with a recorded seed.
- Observable: A stored measure definition names the step, its accuracy measure, its reference and its schedule, and a report exists for the step on that schedule.
- On failure: A step with no named measure, reference or schedule is not put into use, and the gap is recorded.
- Verified by: A check that lists every step in the running configuration and fails on one with no recorded measure, reference or schedule. A test that gives a measure an outcome not yet resolved and checks that the measure refuses to compute.
- Limits: The accuracy registry and schedules are fixed in Appendix A: Launch profile for acquisition, extraction, resolution, retrieval, prediction heads, Jev, agents and integrity.
**SR-28.** Launch behavior must use the complete versioned launch profile.
<!-- id: SDD-SR-28 | tdd: TDD-2.1.25 | status: pending:#56 -->

- Trigger: A component, run, study or deployment is configured.
- Behavior: Apply Appendix A: Launch profile for runtime, storage, budgets, schemas, models, evaluation, retrieval, recovery, data handling and disabled capabilities. Record its hash with affected artifacts. Reject missing required fields and unversioned overrides. Scientific changes require fresh affected qualification; a funding record is distinct from a design limit.
- Observable: Each execution identifies one complete immutable profile and its mode-specific readiness evidence.
- On failure: An incomplete profile or failed prerequisite refuses only the dependent mode and reports the unmet gate; no guessed default or paid fallback is used.
- Verified by: A test removes each required profile group and checks dependent activation refusal, while qualified acquisition can continue without any paid agent-model call.
- Limits: This closes launch choices under #56; measured provider/model/data results remain explicit execution gates, not assumed successes.

### 1.7 Blind rating

**SR-21.** Human rating must hide from a rater which genome surfaced a paper.
<!-- id: SDD-SR-21 | tdd: TDD-2.1.26 | status: implemented -->

- Trigger: A digest (EN-32), its rating view or its detail view (IN-36) is prepared for a rater.
- Behavior: What a rater receives carries no genome hash, lineage, slot or run for any paper, and papers are not grouped or ordered by genome. Where the detail view shows a paper's runs (IN-36), each run's label is drawn fresh for that paper and carries no identity across papers. The link from paper to genome stays recorded, out of the rater's view.
- Observable: A delivered digest and its rating view contain no genome identifier, and ratings are joined to genomes afterwards from the recorded link. In a detail view, the run label for a given genome differs from one paper to the next, so no label persists across papers.
- On failure: A rating view or a detail view that cannot be produced without the genome, or without labels drawn fresh for that paper, is not delivered, and the failure is recorded.
- Verified by: A test that builds a digest from papers surfaced by known genomes and checks that nothing the rater receives, in a field or in the order of papers, identifies the genome of any paper. A further test builds detail views for two papers surfaced by the same genome and checks that the label given to its run differs between the two papers.

**SR-22.** Human rating must hide from a rater which papers are random controls or service picks.
<!-- id: SDD-SR-22 | tdd: TDD-2.1.27 | status: implemented -->

- Trigger: A digest that includes random papers (EN-33) or service picks (EN-38), and its rating view, are prepared for a rater.
- Behavior: A random control or a service pick appears in the same form as a surfaced paper, with no field, label or fixed position that sets it apart from the others. The record of which papers are controls or service picks is kept out of the rater's view.
- Observable: In a delivered digest, a control, a service pick and a surfaced paper show the same fields, and the record of which papers were controls or service picks exists outside the digest.
- On failure: A digest in which controls or service picks cannot be shown in the same form is not delivered, and the failure is recorded.
- Verified by: A test that builds a digest with known controls and known service picks and checks that no field and no fixed position in what the rater receives sets any one of the three kinds of paper apart from the others.

**SR-25.** The rating view must hide agent forecast probabilities, agent rationales, popularity counts, Jev assessments and the origin of each entry until the rater has rated that entry.
<!-- id: SDD-SR-25 | tdd: TDD-2.1.28 | status: pending:#54 -->

- Trigger: A digest and its rating view are prepared for a rater.
- Behavior: What a rater sees before rating an entry carries no agent forecast probability, no agent rationale (SR-24), no popularity count, no Jev assessment or assessment confidence, and no marker of origin, as SR-21 hides the genome and SR-22 hides random controls. Each stays recorded and is shown to the rater once rated, except for whatever SR-21 or SR-22 keeps hidden past that point.
- Observable: A rating view served before a rating is recorded for an entry shows none of the five groups of values, and the same view served after shows each one SR-21 and SR-22 do not also keep hidden.
- On failure: A rating view that cannot be produced with the five groups of values hidden is not delivered, and the failure is recorded.
- Verified by: A test with a known forecast probability, rationale, popularity count and Jev assessment checks that none appears before the rating is recorded and that each appears once it is. A second test gives the entry an origin that SR-21 or SR-22 also hides and checks that the view never reveals it, rated or not.

## 2. Infrastructure: platform and deployment

### 2.1 Containers and services

**PL-01.** Each software component must run in its own container.
<!-- id: SDD-PL-01 | tdd: TDD-2.1.29 | status: pending:#56 -->

- Trigger: A component is started, as a service or as a batch job.
- Behavior: The component runs in a container that holds that component and its package set and nothing else. No two components share a live container or writable environment; verified base images and locked dependency definitions can be reused.
- Observable: The platform's list of containers on the host shows every running component in a container of its own.
- On failure: A component that cannot start in its own container does not start, and the failed start is recorded. It is not started inside another component's container or directly on the host.
- Verified by: A check that reads the system definition (PL-03) and the running containers and fails when one container holds two components, when two components share a writable environment, or when a component runs on the host outside a container.

**PL-02.** Components must interact only through declared service interfaces.
<!-- id: SDD-PL-02 | tdd: TDD-2.1.30 | status: pending:#5 -->

- Trigger: One component needs data or work from another.
- Behavior: Each component that serves others declares its interface. A component reaches another only through a declared interface and reads none of the other's files or memory.
- Observable: A call to a declared interface gets a response. An attempt to reach a component any other way is refused.
- On failure: A request that matches no declared interface is refused, and the refusal is recorded. The calling step stops and takes no other route to the data.
- Verified by: A test that, from inside one container, tries to open another component's files and to call an address the other component does not declare, and checks that both attempts are refused.

**PL-03.** The whole system must start from one declarative definition of its containers, networks and volumes.
<!-- id: SDD-PL-03 | tdd: TDD-2.1.31 | status: pending:#56 -->

- Trigger: The owner starts the system on a host that has passed the floor check (PL-10).
- Behavior: One Compose definition names every local application container, network and volume and declares the external model and backup endpoints. One start action selects collection, engineering or study mode; each mode enforces its recorded readiness prerequisites. External provisioning is separately managed and never performed by an agent.
- Observable: After the start, every service, network and volume the definition names is present on the host, and nothing is present that it does not name.
- On failure: If any part of the definition cannot be brought up, the start stops and the failure is recorded. The daily cycle does not begin on a partly started system.
- Verified by: A test that starts the system from the definition on a clean host and fails when a container, network or volume exists that the definition does not name, or when a named service, network or volume is absent.
- Limits: One owner-controlled Linux application host runs Docker Compose; the hosted agent model and the backup receiver are declared external endpoints in Appendix A: Launch profile.
**PL-04.** Every container must run under declared processor, memory and accelerator limits.
<!-- id: SDD-PL-04 | tdd: TDD-2.1.32 | status: pending:#56 -->

- Trigger: A container is started.
- Behavior: The definition (PL-03) states a processor limit, a memory limit and an accelerator limit for every container, and the platform applies them at start. A container that uses no accelerator is declared with none.
- Observable: For each running container, the limits the platform reports equal the limits in the definition.
- On failure: A container whose definition lacks any of the three limits is not started, and the refusal is recorded.
- Verified by: A test that runs a batch job that tries to take more processor and memory than its limits, and checks that the platform holds it to them while a service beside it keeps answering. A second check fails when any container in the definition lacks a limit.
- Limits: Apply the per-role vCPU, memory and accelerator limits and batch scheduling rules in Appendix A: Launch profile; the shared model service is the one role that declares the host's graphics processor.
**PL-05.** Every service must expose a health check.
<!-- id: SDD-PL-05 | tdd: TDD-2.1.33 | status: pending:#5 -->

- Trigger: The platform asks a service for its health, at start and while the service runs.
- Behavior: Every service answers a health check that says whether it is ready to answer requests. The platform uses the answer to tell a service that is still starting from one that has failed.
- Observable: The platform's recorded state for each service: waiting, healthy or failed.
- On failure: A service whose health check gives a failing answer, or no answer after it was healthy, is recorded as failed. It is not recorded as waiting.
- Verified by: A test that stops the work inside a service without stopping its container and checks that the platform records the service as failed. A second test holds a service in startup and checks that it is recorded as waiting and not as failed.

**PL-06.** Every service image must be built from pinned inputs and carry a version that is recorded with each run.
<!-- id: SDD-PL-06 | tdd: TDD-2.1.34 | status: pending:#5 -->

- Trigger: A service image is built. Later, an agent run starts.
- Behavior: The build names every input by an exact version or a content hash, and the built image carries a version. The stamp of each run (SR-15) also records the version of every service image running when the run starts.
- Observable: The version each running service image carries, and the same versions in the stamp of each run.
- On failure: A build with an input that is not pinned stops and produces no image. A run whose service image versions cannot be read does not start, and the refusal is recorded.
- Verified by: A check that reads the build inputs of every service image and fails on one named without an exact version or hash. A test that starts a run and fails when its stamp lacks the version of a running service image or names a version other than the one running.

**PL-07.** Credentials must reach a container only at run time and never be built into an image.
<!-- id: SDD-PL-07 | tdd: TDD-2.1.35 | status: pending:#5 -->

- Trigger: An image is built, or a container that uses a credential is started.
- Behavior: The platform hands a credential to the container that uses it when that container starts. Images, build inputs and the definition (PL-03) hold no credential value, and the definition names a credential by reference only.
- Observable: An inspection of any image, its build inputs and the definition finds no credential value.
- On failure: A container whose credential is absent at start does not start, and the failure is recorded without the credential value. An image found to hold a credential value is not run.
- Verified by: A check that searches every built image, its build inputs and the definition for the values of the credentials in use and fails on any match.

**PL-20.** The tools of an agent run must be served by one shared tool service that applies the run specification to every call and keeps no state that one run can read of another.
<!-- id: SDD-PL-20 | tdd: TDD-2.1.36 | status: pending:#57 -->

- Trigger: A run's loop sends a tool call to be answered (AG-09).
- Behavior: One shared tool service, running in its own container (PL-01), receives the call, checks it against the tool's schema (AG-11), and answers only within what the call's run specification (AG-17) allows from the snapshot it names (AG-10). It keeps nothing from one call that another run's call can read.
- Observable: The platform's list of containers shows exactly one shared tool service, every tool response a run receives came from it, and a value the service holds after answering one run's call is absent from another run's call to the same tool.
- On failure: A call the shared tool service cannot answer within its run specification is refused, and the refusal is recorded. The service does not answer it from another run's state.
- Verified by: A test that runs two runs at once, has one call a tool with values chosen to appear in a shared cache or index, and checks that the other run's calls to the same tool carry no trace of them.

**PL-21.** The shared tool service must answer every call from the snapshot named in the run specification, including a run that starts after a newer snapshot exists.
<!-- id: SDD-PL-21 | tdd: TDD-2.1.37 | status: pending:#57 -->

- Trigger: The shared tool service (PL-20) receives a call, including one from a run that starts after a newer snapshot has been frozen.
- Behavior: The service reads the snapshot hash from the call's run specification (AG-17) and answers only from that snapshot (AG-10), including from any index it keeps over that snapshot, such as the one behind the neighbors of RD-06. It keeps every index keyed by snapshot hash and never serves one snapshot's index to a call naming another.
- Observable: A call naming an older snapshot hash returns a result drawn only from that snapshot's papers, even while a newer snapshot exists.
- On failure: A call whose named snapshot hash matches no snapshot the service holds is refused, and the refusal is recorded. It is not answered from a newer snapshot or from an index built over another.
- Verified by: A test that freezes a second snapshot with an added paper, then sends a call naming the first snapshot's hash, and checks that the added paper is absent from the result and from any neighbor index used to produce it.

### 2.2 Shared model service and compute

**PL-08.** The small models must be served by one shared service used by every agent run.
<!-- id: SDD-PL-08 | tdd: TDD-2.1.38 | status: pending:#64 -->

- Trigger: The reader, or a tool that answers an agent run, needs an output of the frozen embedding model or qualified prediction heads.
- Behavior: One shared model service on the host holds the only copy of the small models loaded for serving and answers every such request. Every model output an agent run receives, on a paper card or in a tool's answer, came from that one service, and no run calls the service itself (SR-12).
- Observable: The platform's list of containers shows exactly one shared model service. Every number on a paper card that a small model produced carries the model id and model-state date (RD-02, RD-03) the service had loaded when it produced the number.
- On failure: When the shared model service is not healthy (PL-05), a request to it fails and the failure is recorded. No other component loads the small models in its place.
- Verified by: A test that starts several agent runs at once and fails when a second copy of the small models is loaded for serving on the host, when a model output a run received on a paper card or from a tool did not come from the shared model service, or when a call to the service from inside a run gets an answer.

**PL-09.** An agent run must not load model weights of its own.
<!-- id: SDD-PL-09 | tdd: TDD-2.1.39 | status: pending:#57 -->

- Trigger: An agent run starts.
- Behavior: Every output of the small models that the run receives comes from the shared model service through paper cards and tools (PL-08), and the run reaches the agent model over its API (SR-12). Its container holds no model weights: none in its image and none on a volume attached to it.
- Observable: An inspection of the agent run image and of the volumes the definition (PL-03) attaches to it finds no model weights.
- On failure: An agent run image found to hold model weights is not run. An attempt from inside a run to read the volumes that hold checkpoints or prediction heads, or to fetch weights over the network (PL-19), is refused by the platform and recorded.
- Verified by: A test that, from inside an agent run container, tries to open the volumes that hold checkpoints and prediction heads and to fetch weights from an internet address, and checks that each attempt is refused. A check fails when the agent run image holds model weights.

**PL-10.** The host must meet a stated minimum of compute, memory, accelerator and storage before the system starts.
<!-- id: SDD-PL-10 | tdd: TDD-2.1.40 | status: pending:#77 -->

- Trigger: The owner starts the system (PL-03).
- Behavior: Before any service or batch job starts, a floor check measures the host's processor, memory, accelerator and free storage and compares each with the stated minimum. The system starts only when all four meet it.
- Observable: An operator preflight file records measured host values, minima, profile hash, UTC time and pass/fail before service start. Storage imports that exact file on first activation, preserving capture and import times; no application database exists before bootstrap.
- On failure: When a value is below its minimum or cannot be measured, no service or batch job starts. The failed check is recorded with the value that fell short.
- Verified by: A test that sets a minimum above what the host has, starts the system, and checks that no service starts and that the record names the shortfall.
- Limits: The floor is the measured demand recorded under #82, #112 and #114 plus a stated margin, and is fixed in a profile amendment before #74. Apply measured qualification separately under Appendix A: Launch profile.
### 2.3 Batch jobs

**PL-11.** Historical corpus preparation and prediction-head fitting must run as resumable batch jobs outside request services.
<!-- id: SDD-PL-11 | tdd: TDD-1.1.6 | status: pending:#64 -->

- Trigger: An initial corpus build, corpus refresh or weekly fit is requested.
- Behavior: Run acquisition, extraction, automatic label resolution, manifest construction, embedding and fitting as bounded jobs with independent checkpoints. Cache immutable artifacts by content and configuration identity. Services consume only committed manifests; rebuilding a label release does not repeat unchanged document extraction or embedding.
- Observable: Job records identify stage inputs, completed artifacts, reuse counts and resource consumption.
- On failure: Interruption preserves committed stage outputs and exposes no partial dataset release.
- Verified by: A test checks that Resuming after a failed label stage reuses preserved source and embedding artifacts and cannot publish a partial manifest.
- Limits: Historical corpus preparation is required; paid source access and paid inference remain subject to explicit procurement authorization.

**PL-12.** The daily cycle must continue while a batch job runs.
<!-- id: SDD-PL-12 | tdd: TDD-2.1.41 | status: pending:#57 -->

- Trigger: A step of the daily cycle comes due while a batch job is running: ingest, issuing the batch, agent runs or resolution.
- Behavior: The step starts when it is due and completes without waiting for the batch job. Daily steps use the last accepted checkpoint and prediction heads (PL-13), so none of them depends on the running job (PL-17).
- Observable: The day's batch, run and resolution records in the ledger carry timestamps that fall between the recorded start and end of the batch job (PL-16).
- On failure: A daily step that cannot complete while a batch job runs is recorded as failed for that day. It is not held back until the batch job ends.
- Verified by: A test that starts a long batch job, runs a full daily cycle beside it, and fails when any daily step waits for the job to end or does not complete.
- Limits: Weekly fine-tuning of the encoder is held out of the first build (SR-17, #51), and the compute it runs on (#9) is settled with it. The requirement holds for every batch job the first build runs, and for weekly training when it enters, whether it shares the accelerator of the shared model service or uses another.

**PL-13.** The shared model service must keep serving the last accepted checkpoint and prediction heads until new ones are promoted.
<!-- id: SDD-PL-13 | tdd: TDD-2.1.42 | status: pending:#57 -->

- Trigger: A batch job that produces new prediction heads is running, has failed, or has finished and is not yet promoted.
- Behavior: The shared model service keeps answering from the embedding model at its adopted checkpoint and the last accepted prediction heads. Nothing a batch job writes changes what the service serves before promotion (PL-14).
- Observable: The checkpoint date the service reports stays the one the embedding model was adopted with, and the stamps on the numbers it produces for paper cards (RD-02, RD-03) stay those of the last accepted prediction heads until new ones are promoted.
- On failure: If the service cannot serve the embedding model at its adopted checkpoint or the last accepted prediction heads, its health check fails (PL-05) and requests to it fail. It does not fall back to prediction heads that were not promoted.
- Verified by: A test that requests model outputs throughout a prediction-head fitting job and after a failed one, and fails when a response before promotion serves prediction heads other than the last accepted ones, or a checkpoint date other than the one the embedding model was adopted with.

**PL-14.** A qualified model bundle must be promoted by one atomic pointer change.
<!-- id: SDD-PL-14 | tdd: TDD-1.1.21 | status: pending:#64 -->

- Trigger: Candidate artifacts and the bundle manifest pass FT-23.
- Behavior: Publish the verified immutable bundle before switching the active pointer. Each request pins one manifest for its entire execution. A bundle can explicitly retain an earlier compatible target artifact when that target's refit failed; its recorded membership is authoritative. No request assembles membership by reading mutable per-target latest pointers.
- Observable: Every response and paper card names exactly one bundle manifest.
- On failure: An interrupted or failed qualification leaves the prior active pointer unchanged.
- Verified by: A test checks that Concurrent requests during promotion resolve wholly to one committed manifest; a retained compatible prediction head is explicitly listed rather than accidentally mixed.

**PL-15.** A batch job must resume from its last saved state after an interruption.
<!-- id: SDD-PL-15 | tdd: TDD-2.1.43 | status: pending:#72 -->

- Trigger: A batch job that was interrupted is started again.
- Behavior: While it runs, a batch job saves its state to a volume (PL-18). Started again, it continues from the last saved state and does not begin again from the start.
- Observable: The job's record (PL-16) shows the interruption and the resume, and the work done before the last saved state is not repeated.
- On failure: If the last saved state cannot be read, the job is recorded as failed and nothing from it is promoted (PL-14). It does not continue from a damaged or partial state.
- Verified by: A test that stops a batch job part way, starts it again, and fails when the job begins again from the start or repeats work done before its last saved state.

**PL-16.** Every batch job must record its state, its start and end times and its duration.
<!-- id: SDD-PL-16 | tdd: TDD-2.1.44 | status: pending:#72 -->

- Trigger: A batch job starts, changes state or ends.
- Behavior: Each batch job has a record that holds its state (running, interrupted, finished or failed), its start time, its end time and its duration. The record is written at the start and updated at each change of state and at the end, whether the job finished or failed.
- Observable: The stored record of each batch job, kept on a volume (PL-18) and readable by the owner while the job runs and after it ends.
- On failure: A job that cannot write its record does not start. A job whose record does not show finished is not treated as finished (PL-14, PL-17).
- Verified by: A test that runs one batch job to the end and stops another part way, and checks that the first record shows finished with a start time, an end time and a duration, and that the second never shows finished.

**PL-17.** Dependent work must consume only committed batch-job manifests.
<!-- id: SDD-PL-17 | tdd: TDD-1.1.7 | status: pending:#64 -->

- Trigger: A stage requests an upstream job output.
- Behavior: Require a completed immutable manifest, verified artifact hashes and a terminal successful job record. Initial fitting depends on corpus qualification. Services can continue with the last accepted bundle while a replacement job runs or fails. Explicit skip states do not supply new artifacts.
- Observable: Every dependency records the exact upstream manifest hash.
- On failure: Missing, partial or hash-mismatched outputs refuse dependent execution.
- Verified by: A test checks that A job interrupted after writing some files cannot supply a training dataset, while inference continues with the earlier bundle.

### 2.4 Storage and network

**PL-18.** Data that needs to outlive a container must be kept on volumes outside every container's own file system.
<!-- id: SDD-PL-18 | tdd: TDD-2.1.45 | status: pending:#56 -->

- Trigger: A component writes data that is still needed after its container is replaced: the ledger, the corpus, raw responses, checkpoints, prediction heads, snapshots, and the records and saved states of batch jobs (PL-15, PL-16).
- Behavior: Such data is written to volumes that the definition (PL-03) names. A container's own file system holds nothing that is needed after the container is removed.
- Observable: After a container is removed and created again from its image, the data on its volumes is present and unchanged.
- On failure: A component whose volume is absent or cannot be written does not start, and the failure is recorded. It does not fall back to writing inside its container.
- Verified by: A test that removes and recreates every container and checks that the ledger's hash chain still verifies (EN-05) and that the corpus, raw responses, checkpoints, prediction heads and snapshots are unchanged.
- Limits: Use the storage-owned PostgreSQL and content-addressed volumes, commit protocol and backup/restore policy in Appendix A: Launch profile.
**PL-19.** Network reach must be enforced for each container by the platform and not by the component inside it.
<!-- id: SDD-PL-19 | tdd: TDD-2.1.46 | status: pending:#56 -->

- Trigger: A container is started, or a process inside a container opens a connection.
- Behavior: The definition (PL-03) states each container's reach: which containers and outside addresses it reaches, and, for the rating app, the network allowed to reach it (PL-22). The platform blocks everything else, applying the isolation rules of SR-12, SR-13 and PL-22 this way.
- Observable: A connection attempt outside a container's declared reach is refused by the platform, whatever the code inside the container does.
- On failure: A container whose reach rules cannot be applied does not start, and the failure is recorded. It does not start with open network reach.
- Verified by: A test that runs code inside an agent run container and inside a service container other than ingest, tries to reach an internet address and an undeclared container from each, and checks that the platform refuses every attempt.
- Limits: Use host-enforced private networks and allowlisted egress under Appendix A: Launch profile; actual destinations are verified deployment bindings.
**PL-22.** Raters must read the digest and record ratings through a private app on their phones, served from the host over a private network with no route from the internet.
<!-- id: SDD-PL-22 | tdd: TDD-2.1.47 | status: deviation:#121 -->

- Trigger: A rater opens the rating app on a phone to read the digest (EN-32) or record a rating.
- Behavior: The host serves the rating app only over a private network with no route from the internet, admitting a call only after it checks a credential naming the rater. The platform enforces that reach from outside the app, as it enforces every container's reach (PL-19), and the app's outbound side falls under SR-13.
- Observable: A call to the rating app from an address outside the private network gets no response, and what the app presents to a rater carries the label of IN-28.
- On failure: A call that carries no credential, or one the app does not recognize, is refused, and the refusal is recorded. The app does not serve the digest or accept a rating without it.
- Verified by: A test that calls the rating app from an address outside the private network, from the internet, and with no credential, and checks that each is refused, while a call from a rater's credential on the private network succeeds.
- Limits: The application is server-rendered Python HTML over authenticated private HTTPS, with exactly two provisioned rater identities under Appendix A: Launch profile.
## 3. Infrastructure: measuring, output and observation

### 3.1 Scoring

**IN-01.** Scoring must be deterministic, so that the same ledger records always give the same score.
<!-- id: SDD-IN-01 | tdd: TDD-4.1.1 | status: implemented -->

- Trigger: The scorer computes a score.
- Behavior: The scorer computes the score as a function of ledger records and of nothing else. It reads sealed forecasts, the baselines' among them (IN-07 to IN-09), and the results that stand for them (EN-04, IN-12), makes no random draw and calls no language model (SR-03).
- Observable: Running the scorer again over the same ledger records gives a recorded score identical to the first.
- On failure: When a record the scorer reads is missing or unreadable, the scorer stops, records the failure and writes no score.
- Verified by: A test that runs the scorer twice over one fixed set of ledger records, the second time at a later time and with no stored data but those records in its reach, and checks that every score is identical. It catches a score that depends on when the scorer runs, on a random draw or on anything outside the ledger.

**IN-02.** Scoring must not require understanding the paper: the scorer reads forecasts and outcomes and never paper content.
<!-- id: SDD-IN-02 | tdd: TDD-4.1.2 | status: implemented -->

- Trigger: The scorer reads its inputs.
- Behavior: The scorer reads sealed forecasts, the baselines' among them, and the results that stand for them, in which a paper appears only as an id. It has no interface (PL-02) to paper text, figures, tables or paper cards.
- Observable: The scorer's declared interfaces name no source of paper content, and a request from the scorer for paper content is refused.
- On failure: When a score cannot be computed from the permitted inputs, the scorer records the failure and writes no score. It does not turn to paper content.
- Verified by: A test that scores one fixed set of ledger records twice, the second time with all paper content removed, and checks that the scores are identical. It catches a scorer that reads paper content.

**IN-03.** Scoring must not count an unresolved forecast against a genome before its horizon, including forecasts about papers with delayed recognition.
<!-- id: SDD-IN-03 | tdd: TDD-4.1.3 | status: pending:#75 -->

- Trigger: The scorer scores a genome that has sealed forecasts with no resolver result.
- Behavior: Before a forecast's horizon the scorer counts the forecast as neither true nor false (EN-04), so the forecast adds no penalty. A forecast's result, and so any penalty for a forecast that settles false, comes no earlier than its horizon (EN-02).
- Observable: Apart from the pick-set non-overlap score (IN-04), a genome's score computed before a forecast's horizon is the same with that forecast in the ledger and without it.
- On failure: When the scorer cannot establish whether a forecast's horizon has passed, it stops, records the failure and writes no score.
- Verified by: A test that adds a sealed forecast whose horizon has not passed to a genome's records and checks that the genome's score, apart from the pick-set non-overlap score (IN-04), does not change. It catches a scorer that counts an unresolved forecast as false.
- Limits: An unresolved forecast never receives a binary loss, even after its collection deadline; coverage and operational failures are reported separately.

**IN-04.** Scoring must include a pick-set non-overlap score equal to one minus the overlap with the obvious baseline's picks.
<!-- id: SDD-IN-04 | tdd: TDD-4.1.4 | status: pending:#75 -->

- Trigger: The scorer scores a genome's forecasts on a forecast batch.
- Behavior: The obvious baseline is the picks of the paper-discovery services captured by ingest (EN-38). The scorer computes the overlap between the papers the genome picked on the batch and the papers that baseline picked on the same batch, and records one minus that overlap as the genome's pick-set non-overlap score.
- Observable: A pick-set non-overlap score recorded with each genome's score.
- On failure: When the obvious baseline's picks for the batch are missing, the scorer records the term as not computed and writes no value for it.
- Verified by: A test that scores a genome whose picks equal the obvious baseline's and checks that the term is 0, and a genome that shares no pick with it and checks that the term is 1. It catches a term that rewards agreement with the baseline.
- Limits: This diagnostic does not enter fitness. Each genome's picks are its submitted ranked nominations under AG-26; captured service picks define the comparator. Overlap is intersection size divided by genome pick count; an empty pick set is unavailable.

**IN-05.** The scorer must flag a genome whose forecast probabilities cluster at one value.
<!-- id: SDD-IN-05 | tdd: TDD-4.1.5 | status: pending:#75 -->

- Trigger: The scorer scores a genome.
- Behavior: The scorer applies the clustering test to the forecast probabilities of the genome's sealed forecasts. When the test is met, it records a flag against the genome hash.
- Observable: A recorded flag that names the genome hash.
- On failure: When the test cannot be computed, the scorer records that it was not computed and records no flag.
- Verified by: A test that scores one genome whose forecasts all carry the same forecast probability and one whose forecast probabilities are spread from 0 to 1, and checks that only the first is flagged. It catches a scorer that never flags or that flags every genome.
- Limits: Flag when at least 90 percent of the latest 200 probabilities for one configuration/target occupy one fixed 0.1-wide bin; report separately from measured calibration.
**IN-06.** Measuring must produce a reliability diagram per genome.
<!-- id: SDD-IN-06 | tdd: TDD-4.1.6 | status: pending:#75 -->

- Trigger: The report step of the weekly cycle runs (FT-16).
- Behavior: For each genome, measuring groups the forecasts settled true or false by their stated forecast probability and sets each group's forecast probability against the share of its forecasts that settled true. The result is stored as that genome's reliability diagram.
- Observable: One stored reliability diagram for each genome that has resolved forecasts, named by genome hash.
- On failure: A genome with no forecasts settled true or false gets no diagram, and the report states that. No diagram is drawn from unresolved forecasts.
- Verified by: A test that supplies resolved forecasts with known forecast probabilities and outcomes and checks the diagram's points against shares computed by hand. It catches a diagram that includes unresolved forecasts or another genome's forecasts.

### 3.2 Baselines

**IN-07.** A popularity baseline for comparison with agents must answer every forecast batch and be scored by the same scorer.
<!-- id: SDD-IN-07 | tdd: TDD-4.1.7 | status: implemented -->

- Trigger: A forecast batch is sealed (EN-10).
- Behavior: The popularity baseline gives a forecast probability for each question from the authors' prior citation counts captured at the batch snapshot as defined in Appendix A: Launch profile; repository and Hugging Face counts are not launch covariates. Its answers are sealed in the ledger as forecasts (EN-03) and scored by the function the scorer applies to genomes (FT-12).
- Observable: The baseline's sealed forecasts for each batch in the ledger, and a recorded score for the baseline beside the genomes' scores.
- On failure: When any uniquely identified author lacks a valid pre-snapshot count, or no qualified baseline exists, record no answer for that question and report the gap. No answer is added after its forecast deadline.
- Verified by: A test that offers the baseline a count captured after the batch was issued and checks that it is refused, and that checks the baseline's answers are sealed before the batch's outcomes. It catches a baseline that sees outcomes or later data.
- Limits: Launch popularity comparison uses only preserved prior author-citation covariates under Appendix A: Launch profile; missing historical covariates leave the baseline unavailable. Download and repository counters are disabled.
**IN-08.** The base-rate baseline must issue a sealed probability for each qualified target question.
<!-- id: SDD-IN-08 | tdd: TDD-4.1.8 | status: deviation:#75 -->

- Trigger: A forecast batch is sealed.
- Behavior: Use the empirical positive fraction from the active bundle's fitting partition for that exact target and protocol version within the paper's primary category. This admits qualified historical labels without inventing historical agent forecasts. Freeze the baseline with the batch and score it on the same resolved questions as the compared genome.
- Observable: Each baseline forecast records its corpus manifest, primary category, numerator, denominator and target version.
- On failure: No qualified reference partition means unavailable baseline and no evolutionary selection.
- Verified by: A test checks that a label arriving after the bundle cutoff cannot change a sealed base rate, and that neither another target's labels nor another category's labels enter its denominator.

**IN-09.** A plain regression over paper card features for comparison with agents must answer every forecast batch and be scored by the same scorer.
<!-- id: SDD-IN-09 | tdd: TDD-4.1.9 | status: implemented -->

- Trigger: A forecast batch is sealed (EN-10).
- Behavior: A plain regression uses the fixed snapshot-pinned scalar signal projection, fitted only on time-valid logged covariates and resolved outcomes before sealing under IN-35. Jev, raw vectors and paper text are excluded. Seal available answers through the common producer-scoped forecast path and score them with the same deterministic function as agents.
- Observable: The baseline's sealed forecasts for each batch in the ledger, and a recorded score for the baseline beside the genomes' scores.
- On failure: Missing one configured numeric feature is represented by its explicit mask and zero placeholder, never an imputed observation. If both substantive features are absent, the model is unqualified/unfittable or required temporal provenance is absent, record no answer for that question.
- Verified by: A test that checks the regression's inputs against the fixed paper card fields and the batch's snapshot, and that an outcome resolved after the batch was sealed does not change its answers. A second test changes only Jev fields and checks that baseline inputs and answers stay unchanged. It catches a baseline that reads beyond the paper card or fits on later outcomes.
- Limits: Inputs are the target prediction-head logit and original-overview neighbor distance with missingness masks, excluding Jev and later metadata, under Appendix A: Launch profile.
**IN-33.** A nearest-neighbor baseline for comparison with agents must answer every forecast batch and be scored by the same scorer.
<!-- id: SDD-IN-33 | tdd: TDD-4.1.10 | status: pending:#75 -->

- Trigger: A forecast batch is sealed (EN-10).
- Behavior: The nearest-neighbor baseline gives a forecast probability for each question from the neighbor outcomes the paper card holds (RD-11), which cover only earlier neighbors and only outcomes resolved before the snapshot. Its answers are sealed in the ledger as forecasts (EN-03) and scored by the function the scorer applies to genomes (FT-12).
- Observable: The baseline's sealed forecasts for each batch in the ledger, and a recorded score for the baseline beside the genomes' scores.
- On failure: When a paper card holds no earlier neighbor with an outcome resolved before the snapshot, the baseline records no answer for the affected questions and the gap is recorded.
- Verified by: A test that gives a paper one neighbor whose outcome resolved after the snapshot and one that arrived later than the paper, and checks that neither changes the baseline's forecast probability. It catches a forecast drawn from later neighbors or later outcomes.
- Limits: Use five earlier cosine neighbors and (sum known labels + 1)/(known labels + 2), independently per identical target version; no known labels is unavailable.
**IN-34.** The mean of the genomes' forecast probabilities must answer every forecast batch as a forecaster of its own and be scored by the same scorer.
<!-- id: SDD-IN-34 | tdd: TDD-4.1.11 | status: pending:#75 -->

- Trigger: The genomes' forecasts on a forecast batch are sealed (EN-03).
- Behavior: For each question on the batch the mean of the forecast probabilities the genomes sealed for it is computed and sealed in the ledger as a forecast (EN-03) under its own submitter. The scorer scores it with the function it applies to genomes (FT-12), and it takes no part in selection.
- Observable: The mean forecaster's sealed forecasts for each batch in the ledger, and a recorded score for it beside the genomes' and the baselines' scores.
- On failure: When no genome sealed a forecast probability for a question, the mean records no answer for that question and the gap is recorded.
- Verified by: A test that seals known genome forecast probabilities and checks that the mean's sealed forecast probability equals their arithmetic mean, that it is sealed before the batch's outcomes, and that the fitness values selection reads are the same with it and without it. It catches a mean computed after the outcomes or fed into selection.

**IN-35.** A baseline must answer a forecast batch only from information captured before that batch was sealed.
<!-- id: SDD-IN-35 | tdd: TDD-4.1.12 | status: pending:#75 -->

- Trigger: A baseline (IN-07 to IN-09, IN-33) prepares its answers for a forecast batch.
- Behavior: Every input a baseline reads carries the date it was captured, and the baseline uses only inputs captured before the batch's seal record (EN-10). A service pick captured after that moment (EN-38) counts for no question on that batch.
- Observable: The recorded inputs behind a baseline's sealed answers each carry a capture date earlier than the batch's seal record.
- On failure: When an input carries no capture date, or one later than the seal, the baseline leaves it out, records no answer for the questions that depend on it alone, and records the left-out input with the capture date it carries, if any.
- Verified by: A test that captures a service pick after a batch was sealed and checks that the baseline's answers for that batch are unchanged and that the late pick is recorded as left out. It catches a baseline filled in from information captured after the seal.

### 3.3 Human rating and review

**IN-10.** Human raters must rate the papers the system surfaces.
<!-- id: SDD-IN-10 | tdd: TDD-4.1.13 | status: implemented -->

- Trigger: A digest is delivered to the raters (EN-32).
- Behavior: Each rater rates each paper in their island's digest as like, dislike or skip, in a rating view that hides the genome and the random controls (SR-21, SR-22). The system stores each rating against the rater, the paper, the digest entry and the time it was given.
- Observable: A stored rating of like, dislike or skip for each paper a rater has rated, carrying the rater, the paper, the digest entry and the time, and every other pairing of a paper in a digest and a rater shows as unrated.
- On failure: A rating that cannot be stored is shown to the rater as not saved and the paper stays unrated. No rating is filled in on a rater's behalf.
- Verified by: A test that delivers a digest, submits a like, a dislike and a skip for some papers and checks each is stored as given, against the right rater, paper, digest entry and time, with others unrated. It catches ratings that are lost, misattached, given the wrong value or filled in by default.

**IN-11.** A human must spot-check a random sample of forecasts for whether the cited evidence supports the forecast.
<!-- id: SDD-IN-11 | tdd: TDD-4.1.14 | status: pending:#75 -->

- Trigger: The sampling step draws a spot-check sample from the sealed forecasts.
- Behavior: The system draws the sample at random from the sealed forecasts of all three islands, shows each sampled forecast with its cited evidence in a review view, and stores the human's verdict on whether the evidence supports the forecast. The human does not choose which forecasts are sampled.
- Observable: A record of the forecasts drawn, and a stored verdict against each one that has been checked.
- On failure: A sampled forecast with no verdict stays recorded as unchecked. It is not swapped for another forecast.
- Verified by: A test that draws a sample from a fixed set of forecasts and checks that the recorded draw matches the forecasts shown, and that a sampled forecast left without a verdict still appears as unchecked. It catches hand-picked samples and forecasts dropped without a trace.
- Limits: Five hash-seeded forecasts per ISO week, or all if fewer, under Appendix A: Launch profile; unchecked examples remain in the sample.
**IN-12.** Outcome corrections must use preserved source evidence and deterministic resolver versions.
<!-- id: SDD-IN-12 | tdd: TDD-1.1.5 | status: pending:#66 -->

- Trigger: An outcome correction is proposed.
- Behavior: Recompute from corrected source artifacts or an identified resolver defect using the frozen target protocol. Append the superseding label and dependency lineage; preserve prior labels and forecasts. Preference ratings and Jev outputs cannot edit labels. No per-paper human semantic adjudication is required.
- Observable: Correction records identify source hashes, defect or new evidence, resolver version and superseded label.
- On failure: Unverifiable provenance leaves the old record unchanged and the disputed qualification unavailable.
- Verified by: A test that changes rater preferences and Jev answers without changing labels, then verifies that a dated source correction produces an append-only revision.


**IN-13.** A reported source or resolver defect must create a traceable review record.
<!-- id: SDD-IN-13 | tdd: TDD-4.1.15 | status: pending:#66 -->

- Trigger: A source discrepancy or deterministic resolver defect is reported.
- Behavior: Open a record naming source hashes, target and resolver version. Record investigation and disposition; a verified correction uses IN-12. Reader disagreement about usefulness or forecast rationale is not an outcome-label correction.
- Observable: Reported defects have open or dispositioned records linked to affected artifacts.
- On failure: Failure to write the defect record leaves labels unchanged and reports the failure.
- Verified by: A test verifies a reproducible date-parser defect opens a correction path while a dislike rating cannot alter an outcome.
- Limits: This is data-quality investigation, not mandatory semantic annotation for every paper.


**IN-36.** The rating app must show, for an entry a rater has already rated, what each run recorded about that paper: its forecast probability, its cited evidence and its structured output schema fields, rendered without a language model.
<!-- id: SDD-IN-36 | tdd: TDD-4.1.16 | status: pending:#73 -->

- Trigger: A rater opens, in the rating app, an entry the rater has already rated.
- Behavior: The rating app renders each run's forecast probability, cited evidence and structured output schema fields (AG-32, AG-33) directly from its ledger record, with no language model summarizing them, in the same view IN-11 reads for spot-check. The view hides what SR-21 and SR-22 hide from a rater.
- Observable: The entry's detail view lists the forecast probability, the cited evidence and the structured output schema fields the ledger holds for every run that surfaced the paper, matching the stored record.
- On failure: When a run's record cannot be rendered, the detail view shows that the run's detail is unavailable, and no field is filled in from elsewhere.
- Verified by: A test that rates an entry, opens its detail view and checks that each run's forecast probability, evidence and structured output schema fields match its ledger record, with no language model producing them, and that the view hides what SR-21 and SR-22 hide. It catches a view that invents or summarizes a run's record, or leaks the genome or the controls.
- Limits: What a run recorded is not always what drove its forecast probability (IN-32).

**IN-37.** The detail view must show each forecast's verdict once it resolves, beside the baselines' answers to the same question.
<!-- id: SDD-IN-37 | tdd: TDD-4.1.17 | status: pending:#73 -->

- Trigger: A rater opens, in the rating app, an entry already rated under IN-10, once one of the paper's forecasts has resolved (EN-04).
- Behavior: The detail view shows each forecast's verdict (EN-04) beside the baselines' answers to the same question (IN-07, IN-08, IN-09, IN-33), once the forecast has resolved. A forecast or a baseline answer that has not resolved shows as unresolved rather than take a value from elsewhere.
- Observable: The detail view of a rated entry lists, for each of the paper's resolved forecasts, its verdict next to each baseline's answer to that question, and shows an unresolved forecast or baseline answer as unresolved.
- On failure: When a forecast's verdict or a baseline's answer cannot be read, the detail view shows that value as unavailable and still shows the rest.
- Verified by: A test that resolves some of a rated entry's forecasts and baseline answers, leaves others unresolved, opens the detail view and checks that each resolved verdict appears beside the matching baseline answers and each unresolved one shows as unresolved. It catches a view that fills in an unresolved verdict or omits a baseline's answer.

**IN-43.** A rating must be credited to every genome whose sealed submission nominated the rated paper, in proportion to the forecast probability each sealed for it, and to no genome for a random control or a service pick.
<!-- id: SDD-IN-43 | tdd: TDD-4.1.79 | status: pending:#140 -->

- Trigger: A rater records a like or dislike on a digest entry (IN-10), or the weekly cycle computes an island's selection proxy.
- Behavior: Measuring finds every genome of that island whose accepted submission nominated the entry's paper and divides the rating's credit among them in proportion to the citation_reach_365d probability each sealed for that paper, a like counting plus one and a dislike minus one; a skip credits nothing. A control or service entry credits no genome. The credited preference is the island's weekly selection proxy under FT-14 and enters no citation-skill score, prediction head or ledger outcome record.
- Observable: A stored credit record per rating and genome naming the entry, the rater, the sealed probability and the share; the scorer's inputs and the ledger's outcome records are unchanged by any rating.
- On failure: When the nominating submissions cannot be read, no credit is recorded for that rating and the gap is recorded; nothing is imputed.
- Verified by: A test that rates an entry two genomes nominated with different sealed probabilities and checks the shares, that a control entry credits nobody, and that the citation-skill score and the resolver inputs are byte-identical with and without the rating. It catches a rating that reaches fitness or outcomes by any path but the proxy.
- Limits: Credit is per island; a genome of another island never receives credit. Reported under FT-26.

### 3.4 Statistics and reporting

**IN-14.** The forecast must be the unit of statistical analysis.
<!-- id: SDD-IN-14 | tdd: TDD-4.1.18 | status: pending:#75 -->

- Trigger: A comparison between genomes, or between a genome and one of the baselines, is computed.
- Behavior: Every statistic in the comparison is computed over individual resolved forecasts. Forecasts are not first averaged by run, day, paper or genome and then counted as one observation each.
- Observable: Each reported comparison gives the count of forecasts on each side.
- On failure: A comparison with no resolved forecasts on one side is not computed, and that is recorded.
- Verified by: A test that computes a comparison over forecasts spread unevenly across runs and checks that the result equals the value computed by hand over forecasts and differs from the average over runs. It catches analysis that treats the run or the day as the unit.

**IN-15.** Comparisons must report bootstrap intervals.
<!-- id: SDD-IN-15 | tdd: TDD-4.1.19 | status: pending:#75 -->

- Trigger: A comparison is computed.
- Behavior: One resampling routine, shared by all comparisons, resamples forecasts (IN-14) and gives an interval for the difference in the comparison's primary measure (IN-17).
- Observable: Each reported comparison gives the difference together with its interval.
- On failure: When the routine cannot produce an interval, the comparison is reported as having none and gets no verdict. The difference is not reported as a win or a loss.
- Verified by: A test that runs the routine over synthetic forecasts with a known difference and checks that the interval covers it, and a check that no reported comparison lacks an interval. It catches a comparison reported as a bare difference.
- Limits: Use the seeded 10000 publication-week bootstrap and comparison-specific multiplicity rules in Appendix A: Launch profile and Appendix B: Learning protocol.
**IN-16.** An interval containing zero must be reported as inconclusive rather than evidence of equivalence.
<!-- id: SDD-IN-16 | tdd: TDD-4.1.20 | status: pending:#75 -->

- Trigger: A paired comparison interval is produced.
- Behavior: Report inconclusive when the interval includes zero and report the favored direction when it excludes zero. Include the interval, sample support and analysis method. Equivalence requires a separately preregistered equivalence margin and is not inferred from a nonsignificant difference.
- Observable: Comparison records distinguish direction, uncertainty and lack of evidence.
- On failure: A missing interval produces no comparative verdict.
- Verified by: A test checks that a large estimate with an interval crossing zero is reported as inconclusive, never tied in proven performance.

**IN-17.** Each comparison must have one primary measure chosen in advance.
<!-- id: SDD-IN-17 | tdd: TDD-4.1.21 | status: implemented -->

- Trigger: A relied-on comparison inside or outside the system is about to run.
- Behavior: The dated record that SR-18 requires names the comparison's one primary measure before the comparison runs, and the comparison's verdict (IN-16) rests on that measure alone. A comparison with no such record, or with a record that names more than one primary measure, is refused.
- Observable: One dated record per comparison that names its primary measure and is earlier than the comparison's run, and a recorded refusal for any comparison started without one.
- On failure: The comparison does not run, the refusal is recorded and no result is reported.
- Verified by: A test that starts one comparison with no record and one with a record naming two primary measures and checks that both are refused, and a check that every record is dated before its comparison ran. It catches a measure chosen after the results are seen.

**IN-18.** All runs must be reported.
<!-- id: SDD-IN-18 | tdd: TDD-4.1.22 | status: pending:#75 -->

- Trigger: A report is produced.
- Behavior: The report accounts for every run that was issued a run specification in the span it covers, with each run's state. Void runs (AG-15), failed runs and quarantined runs (AG-22) are included.
- Observable: The count of runs in the report equals the count of run specifications issued in the same span, and each run appears with its state.
- On failure: When the report cannot account for every run specification, it is not issued and the failure is recorded.
- Verified by: A test that plants a void run and a failed run and checks that the report lists both and that its count of runs matches the run specifications issued. It catches a report that shows only completed or favorable runs.

**IN-38.** Prediction-head evaluation must distinguish retrospective benchmarks from genuinely prospective predictions.
<!-- id: SDD-IN-38 | tdd: TDD-1.1.23 | status: pending:#67 -->

- Trigger: A prediction-head performance report is produced.
- Behavior: Prospective results require a persisted probability from a qualified bundle, sealed before the event and before its outcome window ends. Exclude examples used to fit, tune or calibrate that bundle. Report per-target Brier score, base-rate skill, average precision, reliability bins and observation coverage. Retrospective results carry model-knowledge limitations and separate denominators.
- Observable: Each result identifies prediction records, label versions, bundle hash and evaluation kind.
- On failure: No eligible predictions yields an unavailable result rather than zero loss.
- Verified by: A test checks that computing a probability after a known event and resolving it later cannot enter the prospective report.
- Limits: Reliability uses ten fixed equal-width bins with counts; statistical comparisons group repeated predictions by paper and publication week.

**IN-39.** Resolver defect reporting must distinguish confirmed errors from evidence-support judgments.
<!-- id: SDD-IN-39 | tdd: TDD-4.1.23 | status: pending:#75 -->

- Trigger: The weekly report is built.
- Behavior: Report investigated source/resolver cases, confirmed defects and open cases per resolver version. Give confirmed-defect counts and their investigated-case denominator, explicitly a selected audit sample rather than a population error estimate. Keep IN-11 rationale-support verdicts separate.
- Observable: Reports retain version-specific audit denominators and unresolved counts.
- On failure: No investigated cases yields unavailable audit rate, not zero error.
- Verified by: A test shows changing a rationale-support verdict cannot change the confirmed resolver-defect rate.


**IN-40.** Reports involving discovery-service picks must identify source overlap and separate descriptive attention from forecast skill.
<!-- id: SDD-IN-40 | tdd: TDD-4.1.24 | status: pending:#75 -->

- Trigger: A report compares service picks with system selections.
- Behavior: Name each discovery source, any overlapping diagnostic source and the capture period. Descriptive service attention is not a launch fitness component. Compare each registered citation target only when sealed probabilities exist on matched questions; otherwise report pick coverage and human ratings separately.
- Observable: Every service comparison identifies its measurement kind and source overlap.
- On failure: Missing source identity suppresses the affected comparison, not unrelated reports.
- Verified by: A test checks that a list of popular papers without sealed probabilities cannot receive a Brier skill score.

**IN-41.** The system must report, for each paper of the arXiv stream that a discovery service later picks, whether a genome had already given it a forecast probability above a threshold written down beforehand, and how many days earlier.
<!-- id: SDD-IN-41 | tdd: TDD-4.1.25 | status: pending:#75 -->

- Trigger: Ingest captures a service pick for a paper of the arXiv stream (EN-38).
- Behavior: Measuring finds, among the forecast probabilities a genome gave the paper before the pick's capture date, the earliest one that crossed the threshold written down beforehand for this comparison (SR-18), and reports how many days before the capture date it was given.
- Observable: For each paper a discovery service picks, the report gives the count of days a genome's forecast probability led the pick, or states that no genome crossed the threshold before it.
- On failure: When the paper's history of forecast probabilities cannot be read, the report states that and gives no value for that paper.
- Verified by: A test that gives one genome a forecast probability above the threshold before the capture date and one only after, and checks that the report counts days for the first and states none for the second. It catches a report that counts a forecast probability given after the pick.
- Limits: Hugging Face Daily Papers is the sole optional discovery comparison; use a preregistered 0.75 citation_reach_365d probability threshold. No preserved service capture means unavailable comparison.
### 3.5 Operations

**IN-19.** A kill switch outside the system's own processes must halt all runs.
<!-- id: SDD-IN-19 | tdd: TDD-4.1.26 | status: pending:#74 -->

- Trigger: The owner operates the kill switch.
- Behavior: The kill switch stops every run in progress and blocks new runs from starting. It acts from outside the system's own processes and is able to stop any of them, so it works when they do not respond.
- Observable: After the kill switch is operated, no run is in progress, no new run specification is issued, and a record of the halt and its time exists.
- On failure: When a process does not stop, the kill switch reports the halt as incomplete and names the process. It does not report a complete halt.
- Verified by: A test that starts runs, makes the system's own processes unresponsive, operates the kill switch and checks that every run stops and none starts. It catches a kill switch that depends on the processes it is meant to stop.

**IN-20.** The kill switch must restore the last accepted state.
<!-- id: SDD-IN-20 | tdd: TDD-4.1.27 | status: pending:#74 -->

- Trigger: The kill switch has halted all runs (IN-19).
- Behavior: The kill switch puts back the population, the checkpoint and the prediction heads from the saved copy of the last accepted state, which the system keeps each time a new state is accepted. The ledger is not rolled back (SR-14).
- Observable: After the restore, the population, the checkpoint and the prediction heads in service are identical to the saved copy of the last accepted state, and the restore is recorded.
- On failure: When the saved copy is missing or incomplete, the restore stops, the system stays halted and the failure is recorded. No partly restored state goes into service.
- Verified by: A test that accepts a state, changes the population and the prediction heads, operates the kill switch and checks that what is restored is identical to the saved copy and that no ledger record is lost. It catches a restore that was never exercised, a partial restore and a restore that rewrites the ledger.

**IN-21.** Operational alerts must reach the owner the same day.
<!-- id: SDD-IN-21 | tdd: TDD-4.1.28 | status: pending:#74 -->

- Trigger: A component raises an operational alert.
- Behavior: The system delivers the flag to the owner in the rating app on the day it is raised. It records when the flag was raised and when it was delivered.
- Observable: For each operational alert, a record of the time raised and the time delivered, both on the same day.
- On failure: When the flag cannot be delivered, it is recorded as not delivered. It is not recorded as delivered and it is not dropped.
- Verified by: A test that raises a flag and checks for a delivery record dated the same day, and that raises one with the rating app unavailable and checks that it is recorded as not delivered. It catches a flag that is written to a log and delivered to nobody.
- Limits: Use the exact integrity, health, storage, budget, qualification and run-failure alert conditions in Appendix A: Launch profile; no external notification channel is enabled.
**IN-22.** An operational alert left unread must itself be recorded.
<!-- id: SDD-IN-22 | tdd: TDD-4.1.29 | status: pending:#74 -->

- Trigger: An operational alert delivered to the owner (IN-21) has not been acknowledged by a rater in the rating app.
- Behavior: The system writes an unread record that names the flag. The record is separate from the flag and stays until a rater acknowledges the flag in the rating app, which counts as the flag having been read.
- Observable: One unread record for each delivered flag that has not been acknowledged in the rating app.
- On failure: When the rating app cannot say whether a flag was acknowledged, the flag is recorded as unread. It is not taken as read.
- Verified by: A test that delivers two flags, acknowledges one in the rating app and checks that an unread record exists for the other alone. It catches a system that treats a delivered flag as a read flag.
- Limits: The channel is that of IN-21, and SR-13 applies to it.

**IN-23.** Text retrieved from papers must be treated as untrusted input.
<!-- id: SDD-IN-23 | tdd: TDD-4.1.30 | status: pending:#117 -->

- Trigger: The reader puts paper text on a paper card, or a deep read returns paper text to the agent model.
- Behavior: Paper text reaches the agent model only as data inside a paper card or a deep-read result, apart from the prompt. Nothing in paper text changes a run's tools, budgets, prompt or run specification, and no component carries out an instruction found in it.
- Observable: A run fed a paper that contains instructions ends with the same tools, budgets and run specification it started with, and every tool call it made fits the strict schemas (AG-11).
- On failure: When paper text cannot be kept apart from the prompt, it is withheld from the agent model and the failure is recorded.
- Verified by: A test that plants a paper whose text tells the agent to call a tool outside its run specification and to exceed its budgets, and checks that neither happens and that the run's forecasts are scored as any others are. It catches paper text that takes effect as an instruction.

**IN-24.** Prompts and run specifications must be read-only to agents.
<!-- id: SDD-IN-24 | tdd: TDD-4.1.31 | status: pending:#73 -->

- Trigger: A run starts.
- Behavior: The run reads its immutable prompt and run specification but cannot write either or another run's configuration. Outside runs an operator can admit a new version only with a new identity and affected qualification; automatic mutation is disabled.
- Observable: A write to a prompt or a run specification attempted from inside a run is refused and the refusal is recorded. The genome hash and the run specification are the same at the end of the run as at its start.
- On failure: When the read-only permission cannot be applied, the run does not start and the failure is recorded.
- Verified by: A test in which a run attempts to write to its prompt and to its run specification through every tool it holds, and which checks that each attempt is refused and both are unchanged. It catches a run that edits its own instructions or budgets.
- Limits: Configuration policy text and overall prompt bounds are fixed in Appendix A: Launch profile; admission changes never mutate a sealed run.


**IN-42.** A periodic check must walk a random sample of scores back to their raw inputs through the recorded provenance and report every break.
<!-- id: SDD-IN-42 | tdd: TDD-4.1.32 | status: pending:#75 -->

- Trigger: The periodic check comes due on its schedule.
- Behavior: The check draws a random sample of recorded scores (IN-01) and, for each, follows its recorded provenance stamps (SR-23) through the ledger's hash chain (EN-05), anchored outside the system (SR-16), back from the score to the raw inputs it was computed from. It runs apart from the services that answer requests.
- Observable: A stored report that names the sample drawn, and for each score in it, either that the walk reached its raw inputs intact or the point at which it broke.
- On failure: When a score's walk cannot be completed, the break is recorded in the report and the score stays as recorded. The check corrects nothing it finds.
- Verified by: A test that alters a raw input behind one recorded score in a copy of the records, runs the check, and checks that the report names that score as broken and no other score as broken. It catches a check that samples scores but never compares them against their raw inputs.
- Limits: Each ISO week hash-sample up to 50 score records for provenance walks. Separately audit up to 50 captured source records and replay the latest completed batch plus one selected older batch under Appendix A: Launch profile. Use all if fewer exist; every snapshot is boundary-checked before sealing.
### 3.6 Data use and presentation

**IN-25.** Data and model weights must be used only under their licenses.
<!-- id: SDD-IN-25 | tdd: TDD-4.1.33 | status: pending:#74 -->

- Trigger: A data source or a set of model weights is proposed for use.
- Behavior: Before first use, a dated license review record names the license of the source or model, the use the system makes of it and whether the license allows that use (SR-20). A source or model with no record, or with a record that does not allow the use, is not used.
- Observable: One dated license review record for each data source and each model in use, and a recorded refusal for any source or model configured without one.
- On failure: When the license cannot be established or does not allow the use, the source or model stays unused and the finding is recorded.
- Verified by: A test that configures a data source with no license review record and a set of weights with none, and checks that both are refused. It catches data or weights adopted with no license read.
- Limits: Whether the ModernBERT license allows continued fine-tuning and kept checkpoints is not verified (#23).

**IN-26.** Ingest must not scrape paywalled content.
<!-- id: SDD-IN-26 | tdd: TDD-4.1.34 | status: pending:#65 -->

- Trigger: Ingest fetches from a source.
- Behavior: Ingest fetches only from sources whose license review record (IN-25) allows the use, and a source that offers its content only behind a paywall gets no such record. Ingest does not work around a paywall.
- Observable: Every fetch in ingest's records goes to a reviewed source, and a fetch to any other address is refused and recorded.
- On failure: When a source answers with a paywall, ingest stores nothing from the response and records the event.
- Verified by: A test that points ingest at an address outside the reviewed sources and at a stub that answers with a paywall, and checks that the first is refused and nothing from the second is stored. It catches an ingest that follows links to publisher pages.

**IN-27.** The system must limit personal data to declared bibliographic and access-control purposes.
<!-- id: SDD-IN-27 | tdd: TDD-4.1.35 | status: pending:#74 -->

- Trigger: A payload is captured or retained.
- Behavior: Apply Appendix A: Launch profile data minimization and retention. Permit public scholarly author names/ids as provenance and pseudonymous rater ids with credential hashes for access control. Exclude unrelated contact/profile data, credentials and authorization headers from research artifacts. Source terms and required deletion override raw-payload retention.
- Observable: Stored research and access-control records have declared fields and retention classes.
- On failure: A prohibited payload is not persisted; a required removal creates a permitted tombstone and invalidates affected replay.
- Verified by: A test removes authentication headers and unrelated contact fields while preserving paper identity and validates deletion lineage.


**IN-28.** Outputs must not be presented as authored scientific claims.
<!-- id: SDD-IN-28 | tdd: TDD-4.1.36 | status: implemented -->

- Trigger: The system produces a digest or a report.
- Behavior: Every digest and every report carries a label that says its content is the output of an automated system and is not a scientific claim authored by anyone. Forecasts are worded as dated predictions with a forecast probability and not as findings.
- Observable: The label on every delivered digest and every stored report.
- On failure: A digest or a report that lacks the label is not delivered or stored, and the failure is recorded.
- Verified by: A test that builds a digest and a report without the label and checks that delivery and storing are refused, and that checks the label on ones built normally. It catches output that reads as a person's finding.

### 3.7 Known weaknesses to avoid

**IN-29.** The system must report operational latency separately from forecast accuracy.
<!-- id: SDD-IN-29 | tdd: TDD-4.1.37 | status: pending:#75 -->

- Trigger: The weekly reporting cycle runs.
- Behavior: Compute publication-to-ingest, ingest-to-card, queue wait, first-model-call-to-submit and batch-to-digest wall durations from their typed timestamps. Report count, missingness, p50 and p95. No launch target predicts an event timestamp, so timing accuracy versus chance is not applicable; late-year activity remains its own binary forecast target.
- Observable: Reports label latency units and populations, missing/invalid clocks and per-stage quantiles; no latency statistic is presented as predictive skill.
- On failure: Exclude invalid clock pairs with reasons and denominators; absent valid durations yield unavailable statistics, never zero latency.
- Verified by: A test exercises these cases: Use known UTC and monotonic durations, missing timestamps and negative pairs; verify stage quantiles and exclusions and refusal to subtract incompatible clock domains.
- Limits: Use linear-interpolated quantiles over sorted valid durations, hours for publication-to-ingest and seconds for the remaining stages; preserve raw timestamps and seconds internally.
**IN-30.** The system must measure and report the calibration of each genome's forecast probabilities, to avoid overconfidence, a weakness reported of published systems.
<!-- id: SDD-IN-30 | tdd: TDD-4.1.38 | status: pending:#75 -->

- Trigger: The report step of the weekly cycle runs (FT-16).
- Behavior: Measuring reports each genome's reliability diagram (IN-06), in which overconfidence shows as a share of forecasts settled true that lies below the stated forecast probability. The prediction heads are calibrated separately (FT-11).
- Observable: Each report gives the reliability diagram of each genome that has resolved forecasts.
- On failure: A genome with no forecasts settled true or false gets no diagram, and the report states that.
- Verified by: A test that supplies forecasts stated at a high forecast probability, of which a known smaller share settled true, and checks that the genome's diagram in the report shows that share below the stated forecast probability. It catches a report that gives accuracy alone.
- Limits: The cited weakness carries no verification date (SR-20).

**IN-31.** The system must measure and report the spread of topics among the papers it surfaces, to avoid bias toward mainstream topics, a weakness reported of published systems.
<!-- id: SDD-IN-31 | tdd: TDD-4.1.39 | status: pending:#75 -->

- Trigger: The report step of the weekly cycle runs (FT-16).
- Behavior: Measuring computes the measure of topic spread over the papers surfaced in the span the report covers and reports its value.
- Observable: Each report gives the value of the measure of topic spread for the surfaced papers.
- On failure: When no paper was surfaced in the span, or the measure cannot be computed, the report states that and gives no value.
- Verified by: A test that supplies one set of surfaced papers drawn from a single topic and one spread evenly across topics, and checks that the reported value is lower for the first. It catches a report that leaves topic spread out and a measure that does not move with it.
- Limits: Use Shannon entropy and distinct primary-subfield counts, with unknown coverage and the same-day pool comparator, under Appendix A: Launch profile.
**IN-32.** The system must report the share of spot-checked forecasts whose cited evidence does not support the forecast, to avoid cited evidence that does not drive the prediction, a weakness reported of published systems.
<!-- id: SDD-IN-32 | tdd: TDD-4.1.40 | status: pending:#75 -->

- Trigger: The report step of the weekly cycle runs (FT-16).
- Behavior: Measuring reports the share of spot-checked forecasts whose stored verdict (IN-11) is that the cited evidence does not support the forecast, with the count of forecasts checked.
- Observable: Each report gives that share and that count.
- On failure: When no verdict exists for the span, the report states that and gives no share. Sampled forecasts still unchecked are counted as unchecked and not as supported.
- Verified by: A test that stores a known set of verdicts, leaves some sampled forecasts unchecked and checks that the reported share and count match the verdicts alone. It catches a report that counts unchecked forecasts as supported.
- Limits: The spot check is the only probe specified, and it shows whether evidence supports a forecast, not whether the evidence drove it. The cited weakness carries no verification date (SR-20).

## 4. Environment

### 4.1 Corpus and time

**EN-01.** The corpus must consist of the papers in the arXiv categories cs.AI, cs.LG, quant-ph and q-bio, each recorded under its primary category.
<!-- id: SDD-EN-01 | tdd: TDD-3.1.1 | status: pending:#5 -->

- Trigger: Ingest runs its daily fetch of new papers from arXiv.
- Behavior: Ingest adds to the corpus each new family whose categories include any of the four, once, and records the primary category of its earliest public version. A paper in none of the four is not added. The category list is a configured value recorded with each batch and each corpus release. The corpus has no other source of papers.
- Observable: Every paper in the corpus has a stored arXiv record that lists one of the four categories, and a recorded primary category among them.
- On failure: When the fetch does not complete, no paper from it enters the corpus, the corpus stays as it was and the failure is recorded.
- Verified by: A test that offers ingest a paper listed in none of the four categories and checks that it is absent afterwards, and one that offers a paper cross-listed in two of them and checks that it is stored once under its primary category.
- Limits: The daily volume of new papers in the four categories has not been measured (#19).

**EN-02.** Prospective forecasts must precede the qualifying event and use later captured outcome evidence.
<!-- id: SDD-EN-02 | tdd: TDD-3.1.2 | status: pending:#64 -->

- Trigger: A forecast is sealed or resolved.
- Behavior: Apply EN-13 publication-based event and collection windows. Live snapshots contain only artifacts captured before sealing; settlement uses later captured evidence. If preserved source records establish that the target predicate was already satisfied before sealing, exclude that question from prospective skill and mark it preexisting-event. Historical labels remain outside the prospective forecast ledger.
- Observable: Reports distinguish valid prospective questions, late evidence and preexisting events.
- On failure: Unverifiable event timing is unresolvable, never silently counted as a correct prediction.
- Verified by: A test checks that A qualifying citing-work record first captured after sealing but dated before it cannot earn prospective forecast credit.

**EN-35.** Snapshots must pin both original prediction inputs and the document versions available for reading.
<!-- id: SDD-EN-35 | tdd: TDD-3.1.3 | status: pending:#64 -->

- Trigger: A snapshot is sealed.
- Behavior: Pin each paper's original version for prediction-head features and the selected readable version captured by the snapshot for tools and content assessments. Record those roles separately when versions differ. Later revisions never alter either pinned artifact or rebuild a historical paper card in place.
- Observable: Tool responses and prediction-head inputs identify their respective immutable source versions.
- On failure: A missing original input leaves prediction-head probabilities unavailable; available readable text remains accessible.
- Verified by: A test checks that A revision containing later results can be read only in a later snapshot and cannot replace the original head-training input.

**EN-36.** A paper card signal taken from an outside provider must come only from a response captured before the batch's snapshot was frozen, never from a later response read back to that date.
<!-- id: SDD-EN-36 | tdd: TDD-3.1.4 | status: pending:#57 -->

- Trigger: The reader builds a paper card signal that draws on a response from an outside provider.
- Behavior: The reader uses, for that signal, only a stored provider response that ingest hashed into the ledger (EN-07) before the batch's snapshot was frozen (AG-10), consistent with the forward-only rule (EN-02), and never substitutes a response captured later by reading it back to an earlier date.
- Observable: The paper card's signal cites the hash of a stored response whose ingest timestamp precedes the snapshot's freeze timestamp.
- On failure: When no response captured before the freeze exists, the paper card carries no value for that signal and the gap is recorded.
- Verified by: A test that offers the reader a provider response captured after the snapshot was frozen and checks that the paper card shows no value for that signal, never the value from the later response backdated to the batch.

**EN-37.** Ingest must report daily acquisition coverage and link the latest applicable independent audit.
<!-- id: SDD-EN-37 | tdd: TDD-3.1.5 | status: pending:#77 -->

- Trigger: Ingest completes its daily fetch of new papers (EN-01).
- Behavior: For each daily cohort compute source, readable text, figure and parsed-bibliography shares over all acquired families. Attach the most recent applicable dated audit and its sample/version, or explicit not-yet-audited. Run the bounded qualification and monitoring audits in Appendix A: Launch profile separately; no new daily human-labeling job is required.
- Observable: Every daily report includes four denominators/shares, missing reasons and audit identity/date or an explicit unavailable audit state.
- On failure: A missing audit does not suppress automatic daily counts. Failed automatic measurement creates a coverage-report failure without substituting the last day or fabricating review.
- Verified by: A test that gives ingest a day's papers with a known number missing the source, the text, the figures or the bibliography, and checks that the report's shares match the known counts.
- Limits: Measure source and bibliography coverage on the fixed 100-paper source audit in Appendix A: Launch profile; #26 and #31 record findings rather than select the sampling policy.

**EN-38.** Ingest must capture the picks of each named paper-discovery service on the day the service makes them.
<!-- id: SDD-EN-38 | tdd: TDD-3.1.6 | status: pending:#56 -->

- Trigger: A named paper-discovery service publishes its picks for the day.
- Behavior: Ingest fetches that day's picks from each named service under that service's license review (IN-25), stores them and appends a ledger record under EN-07, and each service carries a verification date under SR-20.
- Observable: A stored record of each day's picks exists for each named service, dated to the day the service made them, and each service's entry shows a verification date.
- On failure: When a service's picks cannot be captured on the day they are made, no record is written for that service for that day, and the day is recorded as uncovered for that service.
- Verified by: A test that withholds a service's picks for a day and offers them a day later, and checks that no record is written crediting that later capture to the earlier day. This catches a pick list rebuilt after its day.
- Limits: Use the permitted Hugging Face Daily Papers API, at most 50 picks per day; preserve actual capture time and source ids. No current fetch substitutes for missing historical captures.
### 4.2 Ledger

**EN-03.** The ledger must record every forecast with the date on which it was sealed.
<!-- id: SDD-EN-03 | tdd: TDD-3.1.7 | status: pending:#57 -->

- Trigger: A run, a rater or a baseline (IN-07 to IN-09) submits a forecast.
- Behavior: The ledger appends one record per forecast under SR-14, holding the forecast and its submitter, which for a run is the run stamped under SR-15. The record's timestamp is the moment of sealing and serves as the forecast's date.
- Observable: For each submitted forecast the ledger shows one record with the forecast, its submitter and its sealing timestamp.
- On failure: When the append does not complete, the forecast is not sealed, the submitter receives a refusal and the forecast is never scored.
- Verified by: A test that submits a forecast and checks that exactly one ledger record holds it with a sealing timestamp. A test that the scorer ignores a forecast that has no ledger record.

**EN-04.** The ledger must record whether each forecast was later confirmed or denied.
<!-- id: SDD-EN-04 | tdd: TDD-3.1.8 | status: pending:#57 -->

- Trigger: A sealed forecast reaches its horizon and its resolver returns a result.
- Behavior: The ledger appends a resolution record that refers to the forecast's record and holds the resolver result of EN-14, where true means confirmed and false means denied. The forecast's own record stays unchanged, as SR-14 states.
- Observable: A forecast past its horizon has a resolution record in the ledger that refers to it and reads true, false or unresolvable.
- On failure: When the resolver does not run or the append does not complete, no resolution record is written, the forecast stays unsettled and the failure is recorded. An unsettled forecast counts as neither confirmed nor denied.
- Verified by: A test that seals a forecast, resolves it at its horizon with data that makes it true, and checks for a resolution record reading true that refers to the forecast. The same test checks that the forecast's original record and hash are unchanged, which catches a write over the original.

**EN-05.** The ledger must be hash-chained.
<!-- id: SDD-EN-05 | tdd: TDD-3.1.9 | status: pending:#72 -->

- Trigger: A record is appended to the ledger.
- Behavior: Each record carries the hash of the record before it, and its own hash is computed over its content including that previous hash. The head of the chain is anchored as SR-16 states.
- Observable: Recomputing the hashes from the first record to the head reproduces every stored hash.
- On failure: An append whose previous hash does not equal the hash of the current head is refused and nothing is written. A recomputation that finds a mismatch reports the first record at which the chain breaks.
- Verified by: A test that changes one stored record in a copy of the ledger and checks that recomputation reports a break at that record. This catches a ledger whose past records can be edited unnoticed.

**EN-06.** A ledger record must hold a sequence number, the previous hash, its own hash, a kind, a payload and a timestamp.
<!-- id: SDD-EN-06 | tdd: TDD-3.1.10 | status: pending:#72 -->

- Trigger: A record is appended to the ledger.
- Behavior: Every record, whatever its kind, is written with all six fields. The sequence number gives the record's place in the order of appending, and the kind says how the payload is read.
- Observable: Any record read from the ledger shows the six fields.
- On failure: An append that lacks any of the six fields is refused and nothing is written.
- Verified by: A test that attempts an append with each field missing in turn and checks that every attempt is refused.

**EN-07.** Every raw API response from an outside provider must be hashed into the ledger.
<!-- id: SDD-EN-07 | tdd: TDD-3.1.11 | status: pending:#56 -->

- Trigger: Ingest receives a response from an outside provider.
- Behavior: Ingest preserves permitted research response bytes, removing credentials and forbidden fields before persistence under IN-27. Append the stored payload hash, a separate transport hash when bytes differ, and the sanitization policy/version. An unsanitized transport hash is not a promise of replayable transport bytes.
- Observable: Hashing a stored response again gives the hash in its ledger record.
- On failure: A response that cannot be stored or hashed is not used by any later step, and the failure is recorded.
- Verified by: A test that alters a stored response and checks that its hash no longer equals the hash in the ledger. This catches outcome data changed after it was received.

**EN-08.** The version of every resolver that settles a forecast must be recorded in the ledger.
<!-- id: SDD-EN-08 | tdd: TDD-3.1.12 | status: pending:#57 -->

- Trigger: A resolver returns a result for a forecast.
- Behavior: The resolution record names the resolver and the version that produced the result.
- Observable: Each resolution record in the ledger shows a resolver and a version.
- On failure: A result that comes without a resolver version is not appended. The forecast stays unsettled and the failure is recorded.
- Verified by: A test that resolves a forecast and checks that the resolution record carries the version of the resolver that ran. A test that an append of a resolution record with no version is refused.

### 4.3 Forecast batches and resolution

**EN-09.** A forecast batch must be issued daily.
<!-- id: SDD-EN-09 | tdd: TDD-3.1.13 | status: pending:#56 -->

- Trigger: Once each day, after that day's ingest of new papers completes.
- Behavior: The environment builds one daily parent batch, routes each eligible paper to the island of its primary category, partitions each island's papers into canonical disjoint shards of at most 20, seals the common snapshot under EN-10 and issues every shard to every configuration of its island under Appendix A: Launch profile.
- Observable: The ledger holds one batch record for each calendar day.
- On failure: When the batch cannot be built or sealed, no batch is issued that day, no run starts against it and the failure is recorded.
- Verified by: A test that runs the daily cycle over several days and checks for exactly one sealed batch per day, with questions about that day's papers only, every shard holding papers of one island, and exact once-per-configuration coverage of each island's shards by that island's genomes. This catches a skipped day, a second batch in one day, a batch that reaches back to older papers and a shard that mixes islands.
- Limits: Each question closes 24 hours after its paper's first public availability under EN-13. Late arrivals remain readable but are excluded from forecasting; report that coverage under #19.

**EN-10.** Each forecast batch must be sealed before its outcomes exist.
<!-- id: SDD-EN-10 | tdd: TDD-3.1.14 | status: pending:#57 -->

- Trigger: A batch has been built and has not yet been issued.
- Behavior: The environment hashes the whole batch and appends a batch record with that hash and a timestamp to the ledger. Every question on the batch asks about a moment later than that timestamp, and the batch is issued only after the record exists.
- Observable: The batch record precedes, in the ledger, every forecast against the batch and all outcome data that settles its questions. Hashing the batch again gives the recorded hash.
- On failure: A batch that cannot be sealed is not issued, and no forecast against it is accepted. The failure is recorded.
- Verified by: A test that changes a question after sealing and checks that the batch's hash no longer equals its record and that forecasts against the changed batch are refused. This catches a question rewritten once outcomes are known.

**EN-11.** The resolver of each question must be fixed at the time the question is asked.
<!-- id: SDD-EN-11 | tdd: TDD-3.1.15 | status: pending:#57 -->

- Trigger: A question is sealed, on a batch or as part of a volunteered forecast.
- Behavior: The sealed question names its resolver and that resolver's version. At the horizon the question is settled by that resolver at that version and by no other.
- Observable: The resolver and version in each resolution record equal those in the sealed question it settles.
- On failure: When the named resolver version cannot run at the horizon, no other resolver or version settles the question. No resolution record is written, and the failure is recorded.
- Verified by: A test that seals a question, offers a newer resolver version at the horizon, and checks that the sealed version settles the question. This catches a resolver changed after the question was asked.

**EN-12.** Each launch outcome must use one immutable automatic citation target definition.
<!-- id: SDD-EN-12 | tdd: TDD-1.1.1 | status: pending:#66 -->

- Trigger: A question or label is created.
- Behavior: Use automatic-citations-v1 in Appendix B: Learning protocol: citation_reach_365d (5 citing families), late_citation_activity_365d (at least one family in each of days 181-270 and 271-365), and cross_subfield_reach_365d (2 other primary subfields). Preserve the exact source, thresholds, date and family rules in every question. No human semantic label is required.
- Observable: Each question and label identifies a target definition hash.
- On failure: An unregistered target or changed definition under an existing version is refused.
- Verified by: A test checks all threshold boundaries and proves lifetime counts and calendar-year bins cannot replace dated evidence.
- Limits: These are indexed bibliometric proxies; future prediction heads follow FT-20.


**EN-13.** Each launch question must use fixed publication-relative observation and collection windows.
<!-- id: SDD-EN-13 | tdd: TDD-1.1.2 | status: pending:#66 -->

- Trigger: A question or observation is built.
- Behavior: Apply the 365-day event horizon, final two late-activity windows, 90-day indexing allowance and bounded maturity capture in Appendix B: Learning protocol. Seal forecasts within 24 hours of first public availability and before the target predicate is satisfied. Late arrivals remain readable without launch forecast credit.
- Observable: Records contain origin, window endpoints, seal deadline, maturity, capture interval and per-target eligibility.
- On failure: Ambiguous origin, missed seal deadline or unprovable pre-event sealing prevents prospective credit.
- Verified by: A test checks day 180, 270 and 365 boundaries, provider date intervals and capture after the allowed collection interval.
- Limits: Citing-work publication dates are provider metadata, not verified first appearance of citation passages.


**EN-14.** A resolver result must be true, false or unresolvable, with evidence.
<!-- id: SDD-EN-14 | tdd: TDD-3.1.16 | status: pending:#57 -->

- Trigger: A resolver runs on a forecast at its horizon.
- Behavior: The resolver returns exactly one of true, false and unresolvable, together with evidence that identifies the stored data it read. It returns unresolvable when that data is missing or permits neither true nor false, and the evidence then says what was missing.
- Observable: The resolution record in the ledger shows one of the three values and the evidence.
- On failure: A result with any other value, or with no evidence, is not appended to the ledger. The forecast stays unsettled and the failure is recorded.
- Verified by: A test that runs a resolver on data that settles the forecast each way and on data that settles nothing, and checks the three results and their evidence. A test that an append of a result without evidence is refused.

### 4.4 Outcome targets and descriptive diagnostics

**EN-15.** The three launch outcome targets must remain separate.
<!-- id: SDD-EN-15 | tdd: TDD-1.1.3 | status: pending:#66 -->

- Trigger: A label, paper card or report is built.
- Behavior: Preserve independent true/false/unknown labels and calibrated probabilities for reach, late activity and cross-subfield reach. Report correlations and availability per target. Never average them into quality, substantive use or a delayed-recognition verdict. Repository and social counts remain optional diagnostics.
- Observable: Records contain three named fields in registry order.
- On failure: An unknown target version or conflated output is rejected.
- Verified by: A test constructs cases satisfying different subsets and verifies no softmax or sum-to-one constraint.


**EN-16.** Forecast measurements must remain separate from evolutionary selection authority.
<!-- id: SDD-EN-16 | tdd: TDD-3.1.17 | status: pending:#56 -->

- Trigger: The scorer evaluates a population.
- Behavior: Report the three automatic citation outcomes separately under FT-12. The scorer reports and never selects. Selection authority belongs to the accepted policy in FT-14 alone, and only a measure a preregistration names may reach it: no citation probability, Jev answer, rating or cost figure becomes fitness implicitly, and measured cost constrains population size rather than ranking genomes.
- Observable: Reports expose target-specific losses and the governing selection policy rather than an invented fitness.
- On failure: Absent selection authority retains the population unchanged.
- Verified by: A test changes citation scores and confirms that no parent draw or replacement becomes authorized outside the FT-14 policy.
- Limits: This removes the semantic-label dependency without adopting ForeSci fitness or silently optimizing popularity.


**EN-17.** Current citation diagnostics must remain separate from time-windowed outcome evidence.
<!-- id: SDD-EN-17 | tdd: TDD-3.1.18 | status: pending:#64 -->

- Trigger: A diagnostic adapter returns citation records.
- Behavior: Preserve unique work ids, graph identity and observation time for descriptive fields. Only the separately frozen observation protocol in Appendix B: Learning protocol can construct target labels from dated records; a current total cannot settle them.
- Observable: Diagnostics and label observations have distinct artifact roles.
- On failure: Missing diagnostics remain unavailable without inventing a label.
- Verified by: A test changes a paper-card citation total without changing a preserved outcome label.


**EN-18.** The provider citation-intent diagnostic must remain separate from forecast labels.
<!-- id: SDD-EN-18 | tdd: TDD-3.1.19 | status: pending:#64 -->

- Trigger: An enabled, licensed diagnostic adapter returns evidence.
- Behavior: Preserve provider method and influential annotations separately, including missing annotations; neither annotation establishes substantive use or evaluation. The value is descriptive only and cannot settle EN-12 targets, train their labels or determine fitness.
- Observable: Stored diagnostics identify source, coverage, evidence hash and capture time.
- On failure: A disabled, unavailable or unverified adapter produces an unavailable field and does not block the corpus, paper card or forecast.
- Verified by: A test checks that Removing this diagnostic or changing its count leaves the three target labels and their scored outcomes unchanged.
- Limits: This adapter is not a launch dependency; enabling it requires its source capability and retention review under IN-25.

**EN-19.** The repository-fork diagnostic must remain separate from forecast labels.
<!-- id: SDD-EN-19 | tdd: TDD-3.1.20 | status: pending:#64 -->

- Trigger: An enabled, licensed diagnostic adapter returns evidence.
- Behavior: Preserve the attributed repository, observation time and returned fork count; a fork does not establish substantive use. The value is descriptive only and cannot settle EN-12 targets, train their labels or determine fitness.
- Observable: Stored diagnostics identify source, coverage, evidence hash and capture time.
- On failure: A disabled, unavailable or unverified adapter produces an unavailable field and does not block the corpus, paper card or forecast.
- Verified by: A test checks that Removing this diagnostic or changing its count leaves the three target labels and their scored outcomes unchanged.
- Limits: This adapter is not a launch dependency; enabling it requires its source capability and retention review under IN-25.

**EN-20.** The linked-artifact diagnostic must remain separate from forecast labels.
<!-- id: SDD-EN-20 | tdd: TDD-3.1.21 | status: pending:#64 -->

- Trigger: An enabled, licensed diagnostic adapter returns evidence.
- Behavior: Preserve declared paper links and artifact identities; a link does not establish substantive use. The value is descriptive only and cannot settle EN-12 targets, train their labels or determine fitness.
- Observable: Stored diagnostics identify source, coverage, evidence hash and capture time.
- On failure: A disabled, unavailable or unverified adapter produces an unavailable field and does not block the corpus, paper card or forecast.
- Verified by: A test checks that Removing this diagnostic or changing its count leaves the three target labels and their scored outcomes unchanged.
- Limits: This adapter is not a launch dependency; enabling it requires its source capability and retention review under IN-25.

**EN-21.** The artifact-upvote diagnostic must remain separate from forecast labels.
<!-- id: SDD-EN-21 | tdd: TDD-3.1.22 | status: pending:#64 -->

- Trigger: An enabled, licensed diagnostic adapter returns evidence.
- Behavior: Preserve the observed source count and timestamp; a missing paper page is unavailable, not zero. The value is descriptive only and cannot settle EN-12 targets, train their labels or determine fitness.
- Observable: Stored diagnostics identify source, coverage, evidence hash and capture time.
- On failure: A disabled, unavailable or unverified adapter produces an unavailable field and does not block the corpus, paper card or forecast.
- Verified by: A test checks that Removing this diagnostic or changing its count leaves the three target labels and their scored outcomes unchanged.
- Limits: This adapter is not a launch dependency; enabling it requires its source capability and retention review under IN-25.

**EN-22.** The repository-star diagnostic must remain separate from forecast labels.
<!-- id: SDD-EN-22 | tdd: TDD-3.1.23 | status: pending:#64 -->

- Trigger: An enabled, licensed diagnostic adapter returns evidence.
- Behavior: Preserve repository attribution and the observed count or dated event series without substituting lifetime totals for past snapshots. The value is descriptive only and cannot settle EN-12 targets, train their labels or determine fitness.
- Observable: Stored diagnostics identify source, coverage, evidence hash and capture time.
- On failure: A disabled, unavailable or unverified adapter produces an unavailable field and does not block the corpus, paper card or forecast.
- Verified by: A test checks that Removing this diagnostic or changing its count leaves the three target labels and their scored outcomes unchanged.
- Limits: This adapter is not a launch dependency; enabling it requires its source capability and retention review under IN-25.

**EN-23.** The discussion-mention diagnostic must remain separate from forecast labels.
<!-- id: SDD-EN-23 | tdd: TDD-3.1.24 | status: pending:#64 -->

- Trigger: An enabled, licensed diagnostic adapter returns evidence.
- Behavior: Preserve matched item ids, dates and paper-link attribution; a mention does not establish substantive evaluation. The value is descriptive only and cannot settle EN-12 targets, train their labels or determine fitness.
- Observable: Stored diagnostics identify source, coverage, evidence hash and capture time.
- On failure: A disabled, unavailable or unverified adapter produces an unavailable field and does not block the corpus, paper card or forecast.
- Verified by: A test checks that Removing this diagnostic or changing its count leaves the three target labels and their scored outcomes unchanged.
- Limits: This adapter is not a launch dependency; enabling it requires its source capability and retention review under IN-25.

**EN-39.** Outcome collection must report acquisition, label and feature coverage separately.
<!-- id: SDD-EN-39 | tdd: TDD-1.1.4 | status: pending:#65 -->

- Trigger: A corpus release or outcome report is produced.
- Behavior: Use the original selected denominator. Report family matching, completed citation captures, date and subfield availability, original-text completeness, per-target true/false/unknown and exclusions by publication period and source subfield. Preserve failed acquisitions; no mandatory contribution-type annotation is introduced.
- Observable: Each coverage statistic carries its numerator and denominator.
- On failure: Missing measurements block qualification rather than becoming zero outcomes.
- Verified by: A test verifies a high count with missing dates cannot satisfy dated-label coverage and inaccessible original text cannot satisfy feature coverage.
- Limits: Fixed workload and coverage gates are in Appendix B: Learning protocol.


### 4.5 Forecast types

**EN-24.** The trend-to-paper forecast type must remain disabled at launch.
<!-- id: SDD-EN-24 | tdd: TDD-3.1.25 | status: pending:#56 -->

- Trigger: A run proposes this forecast type.
- Behavior: Refuse the trend-to-paper type with an unadmitted-type reason. Only EN-12 citation targets enter launch settlement; free-text hypotheses remain unscored rationale, not hidden forecasts.
- Observable: The submission records refusal without a scored forecast.
- On failure: No substitute resolver or fabricated outcome is used.
- Verified by: A test submits the disabled type and verifies no settlement job or binary score is created.
- Limits: Future admission requires a separate accepted definition, deterministic resolver and qualification under EN-31.


**EN-25.** The co-citation forecast type must remain disabled at launch.
<!-- id: SDD-EN-25 | tdd: TDD-3.1.26 | status: pending:#56 -->

- Trigger: A run proposes this forecast type.
- Behavior: Refuse the co-citation type with an unadmitted-type reason. Only EN-12 citation targets enter launch settlement; free-text hypotheses remain unscored rationale, not hidden forecasts.
- Observable: The submission records refusal without a scored forecast.
- On failure: No substitute resolver or fabricated outcome is used.
- Verified by: A test submits the disabled type and verifies no settlement job or binary score is created.
- Limits: Future admission requires a separate accepted definition, deterministic resolver and qualification under EN-31.


**EN-26.** The query-growth forecast type must remain disabled at launch.
<!-- id: SDD-EN-26 | tdd: TDD-3.1.27 | status: pending:#56 -->

- Trigger: A run proposes this forecast type.
- Behavior: Refuse the query-growth type with an unadmitted-type reason. Only EN-12 citation targets enter launch settlement; free-text hypotheses remain unscored rationale, not hidden forecasts.
- Observable: The submission records refusal without a scored forecast.
- On failure: No substitute resolver or fabricated outcome is used.
- Verified by: A test submits the disabled type and verifies no settlement job or binary score is created.
- Limits: Future admission requires a separate accepted definition, deterministic resolver and qualification under EN-31.


**EN-27.** The citation-rate-growth forecast type must remain disabled at launch.
<!-- id: SDD-EN-27 | tdd: TDD-3.1.28 | status: pending:#56 -->

- Trigger: A run proposes this forecast type.
- Behavior: Refuse the citation-rate-growth type with an unadmitted-type reason. Only EN-12 citation targets enter launch settlement; free-text hypotheses remain unscored rationale, not hidden forecasts.
- Observable: The submission records refusal without a scored forecast.
- On failure: No substitute resolver or fabricated outcome is used.
- Verified by: A test submits the disabled type and verifies no settlement job or binary score is created.
- Limits: Future admission requires a separate accepted definition, deterministic resolver and qualification under EN-31.


The ids EN-28 and EN-29 are reserved by completed decision #27: subtopic publication-rate and benchmark-adoption forecasts are deferred beyond launch.

**EN-30.** Launch agents must not submit forecasts outside their issued question set.
<!-- id: SDD-EN-30 | tdd: TDD-3.1.29 | status: pending:#77 -->

- Trigger: A run submits an answer without an issued question id.
- Behavior: Refuse the extra forecast under the launch contract. Nominations remain separately accepted recommendations under AG-26, not volunteered forecasts. Admitting volunteered forecasts requires an accepted amendment.
- Observable: Every sealed agent forecast references an issued question from its own run snapshot; unissued forecasts are absent from scoring.
- On failure: Record the invalid submission and permit correction only within the existing run budget/deadline; never seal or score the extra forecast.
- Verified by: A test exercises these cases: Submit an otherwise valid citation target for an unissued paper/question and reject it; confirm an allowed nomination does not create a forecast.

**EN-31.** A new forecast type must be admitted only when it has a deterministic resolver.
<!-- id: SDD-EN-31 | tdd: TDD-3.1.30 | status: pending:#77 -->

- Trigger: A forecast type is put forward for admission.
- Behavior: Launch admission consists exactly of the three versioned automatic-citations-v1 definitions under EN-12 and Appendix B: Learning protocol. Only questions instantiated from that immutable registry may be issued; refuse runtime type additions. Future target admission follows FT-20 and an accepted amendment.
- Observable: The ledger holds one admission record for each admitted forecast type, and forecasts are sealed only for types that have one.
- On failure: For a type with no resolver, or a resolver whose results differ between runs on the same inputs, no admission record is written. Forecasts of that type are recorded as void under SR-11.
- Verified by: A test exercises these cases: Issue questions for all three fixed registry definitions and reject an unknown type, a changed threshold under an existing version, and any runtime type-registration request.
- Limits: The trend-to-paper type of EN-24 stays unadmitted under this rule until its resolver is defined (#17).

### 4.6 Digest and human answers

**EN-32.** Surfaced papers must be delivered to the raters as a private digest.
<!-- id: SDD-EN-32 | tdd: TDD-3.1.31 | status: pending:#56 -->

- Trigger: Papers surfaced by the population's runs are ready to go to the raters.
- Behavior: The environment assembles one digest per island under EN-40. It delivers the cs island's digest to the cs rater and the quant-ph island's digest to the quant-ph rater, each through the private app of PL-22 and to nobody else; the q-bio island's digest is built, scored and stored and delivered to no one. What a digest hides from a rater is stated in SR-21 and SR-22.
- Observable: Each rater receives the digest of their island and no other. An attempt to read a digest without that island's rater access is refused, and the q-bio digest has no reader.
- On failure: When delivery does not complete, no partial digest reaches a rater and the failure is recorded.
- Verified by: A test that tries to read a digest without a rater's access and with the other island's rater access and checks both refusals, then reads it with its own island's rater access and checks that the surfaced papers are there, and checks that the q-bio digest exists with no delivery. This catches a digest that anyone can read and a rater who sees another island.
- Limits: Recommendations are separate from forecasts and delivered only through the private app; available forecast links accompany them without creating extra forecasts.
**EN-33.** Each digest must include up to three uniformly sampled control papers.
<!-- id: SDD-EN-33 | tdd: TDD-3.1.32 | status: pending:#64 -->

- Trigger: Population entries have been chosen.
- Behavior: Sample without replacement from the island's eligible daily papers absent from its population entries, using a seed derived from the batch hash, the island and the control-rubric version. Keep the selection source hidden from raters. Record inclusion probabilities and shortfalls; random controls measure selection effects rather than automatically removing all rating bias.
- Observable: The digest record preserves sampled ids and draw provenance.
- On failure: An unavailable candidate pool is recorded and does not fabricate control entries.
- Verified by: A test checks that Replaying a fixed batch reproduces the draw; changing prediction-head scores cannot change the random ordering before exclusion.
- Limits: Three control places; fewer eligible papers produce fewer entries.

**EN-34.** Human forecasts must remain optional and separate from access to the digest.
<!-- id: SDD-EN-34 | tdd: TDD-3.1.33 | status: deviation:#121 -->

- Trigger: A daily batch is issued and the private human-forecast view is made available.
- Behavior: Expose the three seeded primary-target questions independently of digest publication while their per-paper deadlines remain open. Seal valid answers through the normal ledger path. After expiry, disable answers while leaving digest/rating access independent. Do not impute omitted answers or score them as false.
- Observable: Reports distinguish participation from prediction loss; both raters can read the digest after close.
- On failure: Invalid submissions record their refusal without permanently locking the digest.
- Verified by: A test checks that A rater who misses the entire forecast window can still rate the digest and receives no invented forecasts.
- Limits: Use citation_reach_365d as the primary question offered to raters and the batch hash as the sampling seed; fewer than three questions produce a smaller offer.

**EN-40.** Each island's digest must be built after the day's batch seals, by a fixed rule and a recorded seed, from the ledger alone, as one entry per paper, so that the same ledger always gives the same digest.
<!-- id: SDD-EN-40 | tdd: TDD-3.1.34 | status: pending:#77 -->

- Trigger: Every scheduled daily slot of an island is terminal or its deadline has expired, and that island's daily digest has no committed build.
- Behavior: Freeze one ledger watermark after marking expired slots missed or void. Build from accepted ranked nominations, sealed forecast links, seeded controls and permitted service captures committed at or before that watermark. Record cutoff, algorithm/profile hash, seed and digest hash; future submissions, ratings and outcomes cannot change this digest.
- Observable: The digest manifest records its source watermark and exact input artifact ids; repeated construction produces identical entries/order/hash.
- On failure: When a record the build reads is missing, or the seed or the hash cannot be recorded, no digest is built or delivered that day and the failure is recorded.
- Verified by: A test that builds the digest twice from one fixed set of ledger records and checks that both give the recorded hash. A test that stores a rating and a paper held outside the ledger, rebuilds the digest and checks that it is unchanged, which catches a digest assembled from a second list beside the ledger.
- Limits: Use the bounded nomination, control and service allocation followed by seeded blind shuffling under Appendix A: Launch profile; nominations are not additional forecasts.
**EN-41.** The digest must allocate population places from ranked agent nominations.
<!-- id: SDD-EN-41 | tdd: TDD-3.1.35 | status: pending:#64 -->

- Trigger: A completed daily batch is assembled into a digest.
- Behavior: Each valid agent submission supplies up to seven distinct eligible paper ids in preference order with its rationale. Within each island sort its genomes by id, rotate that order by UTC day ordinal modulo the island's size, and round-robin their next unseen nominations until seven population places are filled or all lists are exhausted. Skip already selected papers. Do not sort by citation-head probabilities or synthesize a quality score.
- Observable: The digest records ranked nominations, rotation, selected ids and shortfalls.
- On failure: An invalid or absent submission supplies no nominations; fewer unique papers leave fewer entries.
- Verified by: A test changes all prediction-head probabilities while keeping submissions fixed and verifies identical allocation, including duplicate nominations and shortfalls.
- Limits: Existing three random-control and two service slots remain EN-33 and EN-42, per island digest; a genome nominates only papers of its island.


**EN-42.** The digest must carry at most two captured discovery-service picks without revealing their source.
<!-- id: SDD-EN-42 | tdd: TDD-3.1.36 | status: pending:#64 -->

- Trigger: Random control entries have been chosen.
- Behavior: Deduplicate service picks against existing entries, then allocate two remaining places by round-robin over service ids sorted lexically, preserving each captured service order. Record omitted picks and source coverage internally. Apply the same presentation and rating rules as other entries. No service adapter is required to supply forecast labels.
- Observable: A digest manifest records included and omitted service picks and never exceeds twelve entries.
- On failure: Unavailable or unqualified services produce zero service entries and leave other entries readable.
- Verified by: A test checks that A service returning one hundred picks cannot prevent digest delivery or displace its protected random controls.
- Limits: Show publication dates consistently and disclose that residual age/content cues can weaken blinding; do not delay all entries to conceal those cues.

## 5. Agents

### 5.1 Population

**AG-01.** Every launch agent run must use the same pinned qualified multimodal model endpoint.
<!-- id: SDD-AG-01 | tdd: TDD-3.1.37 | status: pending:#56 -->

- Trigger: A run specification is prepared.
- Behavior: Use the pinned hosted model, its one named provider endpoint and the deployment qualification contract in Appendix A: Launch profile. Record the provider identity and the model revision the provider returned for the run. No per-run model change, relay, second provider or automatic fallback is allowed.
- Observable: All compared runs carry the same provider endpoint identity and the same returned model revision.
- On failure: Missing vision/tool qualification or a changed model identity prevents new study runs.
- Verified by: A test rejects an unpinned endpoint or a returned revision other than the pinned one, while accepting an explicitly qualified manifest.


**AG-02.** The agent model must also receive the figures and tables of a paper, in addition to its paper card.
<!-- id: SDD-AG-02 | tdd: TDD-3.1.38 | status: pending:#56 -->

- Trigger: A run calls deep_read on a paper (AG-09).
- Behavior: The deep_read response carries the paper's figures and tables, taken from the paper's source in the snapshot, in a form the agent model accepts (MD-11).
- Observable: For a paper whose source holds figures and tables, the deep_read response sent to the agent model contains them.
- On failure: When a figure or table cannot be served, the deep_read response names what is missing and carries nothing in its place. The failure is recorded with the run.
- Verified by: A test that calls deep_read on a paper with a known figure and a known table and checks that both are in the response the agent model receives. It catches a deep read that delivers text alone.
- Limits: The pinned hosted endpoint must pass the exact image/tool capability tests in Appendix A: Launch profile before study use.
**AG-03.** Launch configurations must differ only in their declared reading emphasis.
<!-- id: SDD-AG-03 | tdd: TDD-3.1.39 | status: pending:#77 -->

- Trigger: An initial configuration is admitted or a run specification is constructed.
- Behavior: Admit only the eight seeded configurations of Appendix A: Launch profile, with common model, tools, budgets, targets and schema, differing in prompt and policy emphasis alone. The population is fixed for its first two weekly cycles; afterwards FT-14 alone changes its membership. Any later version is an operator-admitted artifact with affected qualification, never an in-run edit.
- Observable: Configuration manifests show the seeded emphasis identities and identical protected settings; all runs resolve to one immutable manifest.
- On failure: Reject an unregistered configuration, changed protected setting or unauthorized mutation request, record the reason and leave the active configuration set unchanged.
- Verified by: A test exercises these cases: Admit the eight seeded configurations, then alter model id, budget or tools in one and verify rejection; a mutation outside FT-14 cannot create a child or alter any active manifest.
- Limits: Seeded configurations differ only in named reading emphasis; no part is mutable during a run or a study comparison.
**AG-04.** The agent layer must be a population of the same agent doing the same task.
<!-- id: SDD-AG-04 | tdd: TDD-3.1.40 | status: pending:#56 -->

- Trigger: A forecast batch is issued (EN-09).
- Behavior: Every run on the batch uses the same loop (AG-08), the same agent model, the same batch and the same snapshot, on the shards of its own island. One member of the population differs from another by its genome alone.
- Observable: The run specifications written for one batch carry the same snapshot hash and differing genome hashes (AG-17), and the run stamps carry the same agent model id (SR-15).
- On failure: A genome whose run cannot start on a batch has no forecasts on that batch, and the missing run is recorded. No other agent design or task is put in its place.
- Verified by: A test that issues one batch to a population of differing genomes and checks that every run specification names the same snapshot hash and every run stamp names the same agent model id. It catches a member that runs a different agent, task or snapshot.
- Limits: The seeded population and two concurrent workers process every at-most-20-paper shard under Appendix A: Launch profile.
**AG-05.** The population must be tested continuously, with every genome in it run on each forecast batch as the batch is issued.
<!-- id: SDD-AG-05 | tdd: TDD-3.1.41 | status: pending:#56 -->

- Trigger: A forecast batch is issued (EN-09).
- Behavior: A run is started on each shard of an island for every genome of that island, and the forecasts it submits are sealed in the ledger to be settled at their horizons. Only its live sealed records enter prospective measurement; separately labeled development comparisons cannot supply production fitness.
- Observable: For each batch, every genome that was in the population at issue has either sealed forecasts in the ledger or a run recorded as void (AG-15) or as missing (AG-04).
- On failure: A run that ends without a submit is void (AG-15), and a run that cannot start is recorded as missing (AG-04). The gap stays in the genome's record.
- Verified by: A test that issues batches on consecutive days to a population and checks that every genome has a run recorded on every batch. It catches a genome that stays in the population without being tested.
- Limits: Every configuration in an island receives every shard of that island; concurrency two queues excess work with deadline and missing-run accounting under Appendix A: Launch profile.
**AG-06.** Performance-based mutation must produce no child while the seeded population is fixed.
<!-- id: SDD-AG-06 | tdd: TDD-3.1.42 | status: pending:#56 -->

- Trigger: A job or request attempts performance-based mutation.
- Behavior: Return disabled-by-profile through the seeded population's first two weekly cycles, keeping the population and immutable schemas as they are. Afterwards produce a child only under FT-14, as one field-level change to one parent, with no extra model call. Preserve the request disposition in the audit record.
- Observable: The weekly record shows no child before the third weekly cycle, and every later child names its parent and the one field it changed.
- On failure: A missing profile cannot enable it.
- Verified by: A test invokes the mechanism in each of the first two weekly cycles and verifies no population change, then verifies that a later child differs from its parent in exactly one hashed part.
- Limits: Activation follows FT-14 and its preregistration under SR-18, not a runtime flag alone.


**AG-07.** The agent must not judge itself: no score, fitness value or selection decision comes from an agent or from the agent model.
<!-- id: SDD-AG-07 | tdd: TDD-3.1.43 | status: pending:#57 -->

- Trigger: The scorer scores a genome, or selection is evaluated.
- Behavior: The scorer computes a genome's score from ledger records alone, which for the genome are its sealed forecasts and their resolver results (IN-01, SR-03). Nothing an agent says about its own performance or about another genome is read by the scorer or by selection.
- Observable: A genome's score recomputed from the ledger alone, with no call to the agent model, equals the recorded score.
- On failure: When a score cannot be computed from ledger records alone, the scorer stops and writes no score (IN-01), and the failure is recorded. No agent output stands in for it.
- Verified by: A test that adds to a run's final message a statement rating its own forecasts as correct and checks that the genome's score is the same with and without it. It catches any path by which an agent's view of itself reaches a score.

**AG-31.** A genome must not contain the identifier of a paper in any of its parts.
<!-- id: SDD-AG-31 | tdd: TDD-3.1.44 | status: pending:#57 -->

- Trigger: A genome is offered to the population, as a first genome or as a child of mutation (AG-20).
- Behavior: Admission reads every part of the genome (AG-16) and looks for the identifier of a paper in the corpus. A genome that carries one in any part is not admitted, so no lineage carries a named paper, and with it a settled outcome, into a later run.
- Observable: No genome in the population holds a paper's identifier in any part, and a genome that carried one has a recorded refusal and appears in no run specification.
- On failure: The genome is refused whole. It does not enter the population, gets no run specification, and the refusal is recorded with the part that carried the identifier.
- Verified by: A test that offers a child genome whose prompt names a paper by its identifier, and one whose structured output schema names a paper in a field description, and checks that both are refused. It catches a genome that carries knowledge of a settled paper forward in its own text.

**AG-32.** A genome must hold a structured output schema, a schema for the agent model's own turns that the loop enforces, bounded by a fixed meta-schema, whose evolved extension is empty in the first population.
<!-- id: SDD-AG-32 | tdd: TDD-3.1.45 | status: pending:#56 -->

- Trigger: A genome is offered to the population (AG-16), or a run's loop assembles a request to the agent model (AG-08).
- Behavior: The structured output schema gives the schema of the agent model's own turns, it is checked at admission against a fixed meta-schema, and the loop passes it with each request. A genome of the first population carries its protected core (AG-33) and no evolved field beside it, and the tool schemas (AG-11) and the fields of a forecast stay outside it.
- Observable: Every genome in the population, read back, shows a structured output schema that holds against the meta-schema, and the fields it names are the fields filled in that genome's run records (AG-29).
- On failure: A genome whose structured output schema does not hold against the meta-schema is not admitted, gets no run specification, and the refusal is recorded. When the loop cannot pass the format to the agent model, the run ends without a submit and is void (AG-15).
- Verified by: A test that offers a genome whose structured output schema breaks the meta-schema and checks that it is refused, and a test that changes a filled field in a run record and checks that the genome's score is unchanged (SR-03). It catches a format outside the meta-schema and a filled field that reaches the scorer.
- Limits: The launch extension is empty; protected fields and bounded future types are fixed in Appendix A: Launch profile, with future activation requiring an amendment.
**AG-33.** The structured output schema must have a protected core, the same for every genome and never mutated, that holds for each turn a plain-language note of bounded length and an intent label from a fixed list, with evolution acting only on the extension beside it.
<!-- id: SDD-AG-33 | tdd: TDD-3.1.46 | status: pending:#56 -->

- Trigger: A genome is offered to the population (AG-16), or a mutation of a structured output schema is proposed (AG-35).
- Behavior: Every structured output schema carries the same core, which for each turn holds a note in plain language of bounded length and an intent label from a fixed list. Mutation acts only on the extension (AG-03), the core is not read by the scorer (SR-03), and a rater sees the note only after rating the entry (IN-36).
- Observable: The run records of any two genomes hold the same core fields under the same names (AG-29), and a diff that changes the core or the list of intent labels is recorded as rejected.
- On failure: A genome whose structured output schema lacks the core, or whose core differs from the fixed one, is not admitted, gets no run specification, and the refusal is recorded.
- Verified by: A test that proposes a diff removing the note from the core and one that uses an intent label outside the fixed list, and checks that both are rejected. It catches evolution that drops the fields a reader compares across genomes.
- Limits: The note is at most 1000 UTF-8 characters; intents are scan, compare, inspect, forecast, nominate, submit and stop.
**AG-34.** Launch structured output must reject every nonempty schema extension.
<!-- id: SDD-AG-34 | tdd: TDD-3.1.47 | status: pending:#77 -->

- Trigger: A configuration or turn payload is validated.
- Behavior: The launch extension is empty. Refuse extra fields and any evolved-field admission regardless of label, description or type. Retain future type bounds only as a reserved contract; render existing protected fields by fixed rules under IN-36.
- Observable: No admitted configuration or accepted turn contains an evolved field; rendering needs no model call.
- On failure: Return a schema-extension-disabled reason without creating a configuration or accepting the payload.
- Verified by: A test exercises these cases: Reject both a well-typed described extra field and an unknown extra field; render the valid protected schema with all model endpoints unreachable.
- Limits: Reserved future types and bounds are fixed in Appendix A: Launch profile; no evolved field is admitted at launch.
### 5.2 Runs

**AG-08.** An agent run must be a plain canonical-message loop: one conversation between the agent model and the run's tools, with no layer between them.
<!-- id: SDD-AG-08 | tdd: TDD-3.1.48 | status: pending:#56 -->

- Trigger: A run starts under its run specification.
- Behavior: The loop sends the conversation to the agent model through the pinned chat-completions API and answers each tool call with that tool's response, ending the run at the first accepted submit (AG-26), an exhausted budget (AG-12), the model stopping, or a conversation that no longer fits its context. Nothing else adds, removes, reorders or rewrites messages.
- Observable: Every request a run sends to the agent model holds only the system prompt from the genome, a first message that holds the batch, the run's budgets and a description of the snapshot, the model's earlier turns and the tool responses, in the order they were produced.
- On failure: When a call to the agent model fails, the loop stops, and the run ends without a submit and is void (AG-15). The failure is recorded.
- Verified by: A test that runs the loop against a stand-in agent model with a fixed script of tool calls, and checks each request for any message beyond the system prompt, the first message, an earlier turn or a tool response, or any change in their order. It catches a layer that injects, drops, reorders or rewrites messages.
- Limits: Use the pinned GLM endpoint and OpenAI-compatible chat-completions transport in Appendix A: Launch profile, preserving the canonical conversation.
**AG-09.** An agent's tools must be exactly query_cards, neighbors, graph, deep_read and submit.
<!-- id: SDD-AG-09 | tdd: TDD-3.1.49 | status: pending:#57 -->

- Trigger: A run is offered its tools, and the agent model returns a tool call.
- Behavior: The loop offers the agent model these five tools and no other, less any the genome has narrowed away (AG-14). The first four read from the snapshot (AG-10), and what they return of the small models is paper card text (RD-04, RD-05). Submit hands in the run's forecasts.
- Observable: The tool list in every request to the agent model names only tools among the five, and a call to any other name gets a refusal.
- On failure: A call to a tool outside the run's allowed set is refused with an error response. Nothing is executed and the refusal is recorded with the run.
- Verified by: A test in which a stand-in for the agent model calls a sixth tool name and checks that the call is refused and nothing runs, and a check of the tool list offered to the model against the five names. It catches a tool added outside the specification.

**AG-10.** An agent must have read-only access to a snapshot frozen when the batch is issued.
<!-- id: SDD-AG-10 | tdd: TDD-3.1.50 | status: pending:#57 -->

- Trigger: A forecast batch is issued (EN-09), and a run on that batch starts.
- Behavior: When the batch is issued, the papers, the paper cards and the citation graph are frozen as a snapshot and its hash is recorded. The shared tool service (PL-21) answers every call a run makes from the snapshot named in that run's contract (AG-17), even when the run starts after a newer snapshot exists, and the run has no means to write to it.
- Observable: The snapshot hash in each run specification for the batch (AG-17) equals the hash recorded at issue and the hash recomputed after the runs, and a run that starts after a later batch is issued still reads only the snapshot named in its own contract. A write attempted from a run is refused.
- On failure: When the snapshot cannot be frozen, or its hash does not match the run specification, no run on that batch starts and the failure is recorded.
- Verified by: A test adds a paper after a batch is issued and checks a run on that batch cannot retrieve it, and a test starts a run on an old contract after a later snapshot exists and checks it is still answered from its own snapshot. A further test attempts a write from a run and checks it is refused and the snapshot hash is unchanged.

**AG-11.** Tool schemas must be strict, so that a tool call with a missing, extra or wrongly typed argument is refused.
<!-- id: SDD-AG-11 | tdd: TDD-3.1.51 | status: pending:#57 -->

- Trigger: The agent model returns a tool call.
- Behavior: The call's arguments are checked against the tool's schema before the tool runs. A call that does not match exactly is refused with an error response, and its arguments are not coerced or partly used.
- Observable: The refused call gets an error response and has no effect. For submit, no forecast from the refused call reaches the ledger.
- On failure: When the check itself cannot run, the call is refused, the tool does not run and the failure is recorded.
- Verified by: A test that sends each tool a call with an extra argument, one with a missing argument and one with a wrongly typed argument, and checks that all are refused. It catches a tool that coerces or ignores bad input.

**AG-12.** Every run must have hard budgets, enforced by the loop and outside the agent's control.
<!-- id: SDD-AG-12 | tdd: TDD-3.1.52 | status: pending:#56 -->

- Trigger: A run starts under a run specification that carries its budgets (AG-17).
- Behavior: The loop counts the run's use against each budget in the run specification, states the remaining amount against each budget in every tool response (AG-27), and stops the run when one is exhausted. Nothing the agent model does raises or resets a budget.
- Observable: A run stopped by a budget is recorded with the budget that was exhausted, no call to the agent model or to a tool follows that point, and every tool response of the run carries the remaining amount for each budget.
- On failure: A run whose contract carries no budgets does not start. A run stopped by a budget before submit is void (AG-15). A tool response that cannot state the remaining budgets is not sent, and the failure is recorded.
- Verified by: A test gives a run a small budget and a stand-in agent model that never stops calling tools, and checks the run stops at the budget with no further call, and that each tool response up to then carried the remaining amount per budget. It catches a budget that is advisory, extendable by the agent, or unreported.
- Limits: Apply the exact context, generation, calls, deep reads, images, timeout, retry, wall-time and spend ceilings in Appendix A: Launch profile.
**AG-13.** The scorer must run in a process separate from the agent.
<!-- id: SDD-AG-13 | tdd: TDD-3.1.53 | status: pending:#5 -->

- Trigger: The scorer starts, or an agent run starts.
- Behavior: The scorer runs as its own process in its own container (PL-01) and takes its input from the ledger. No agent run executes inside that process, and a run has no interface to it (SR-12).
- Observable: The scorer and the agent runs are listed as separate processes, and the scorer produces the same scores from the ledger when no agent run exists.
- On failure: When the scorer's process is not running, no score is produced and the failure is recorded. An agent run never computes a score in its place.
- Verified by: A test that tries to reach the scorer from inside an agent run and checks that the attempt is refused, and a test that stops all agent runs and checks that the scorer still computes the same scores from the ledger. It catches scoring that shares a process or state with an agent.

**AG-14.** A genome must be able to narrow the tool set of AG-09 and never widen it.
<!-- id: SDD-AG-14 | tdd: TDD-3.1.54 | status: pending:#57 -->

- Trigger: A run specification is built for a genome.
- Behavior: The tools allowed in the run specification are the genome's tools when every one of them is among the five of AG-09. A genome that lists any other tool gets no run specification.
- Observable: The tools allowed in every run specification are among the five, and a genome that lists any other tool has a recorded refusal and no run.
- On failure: The run specification is not built, the genome has no run on that batch, and the refusal is recorded.
- Verified by: A test that builds a run specification for a genome listing four of the five tools and checks that the run is offered only those four, and a test with a genome listing a sixth tool that checks the contract is refused. It catches a genome that gains a tool by naming it.

**AG-15.** A run that ends without a submit must be void.
<!-- id: SDD-AG-15 | tdd: TDD-3.1.55 | status: pending:#57 -->

- Trigger: A run ends without an accepted call to submit, whether the model stopped, a budget was exhausted, a failure stopped the loop, or every call to submit it made was refused.
- Behavior: The run is recorded as void with its stamp (SR-15). No forecast from it is sealed or scored, text the agent model produced outside submit is never read as a forecast, and a run's ending follows the same first-accepted-submit rule as any other run (AG-26).
- Observable: The run's record shows the void state, and the ledger holds no forecast from that run.
- On failure: There is no partial outcome. A run either has an accepted submit or is void.
- Verified by: A test that ends one run by exhausting its budget before submit and another in which the model stops after listing its picks as plain text, and checks that both are void and that no forecast from either reaches the ledger.

**AG-25.** The first message of a run must hold only the batch, the run's budgets and a description of the snapshot, so that every paper card in the conversation is one the agent asked for.
<!-- id: SDD-AG-25 | tdd: TDD-3.1.56 | status: pending:#57 -->

- Trigger: A run starts under its run specification (AG-17).
- Behavior: The loop (AG-08) composes the first message from the batch issued for the run (EN-09), the run's budgets and a description of the snapshot, and places no paper card in it. Every paper card that reaches the conversation after that point is one the agent retrieved through its own tool call (AG-03).
- Observable: The first message stored for a run holds only these three parts, and no paper card text appears in it before the run's first tool call.
- On failure: A first message that carries a paper card or content beyond these three parts means the run does not start, and the failure is recorded.
- Verified by: A test that inspects the first message of a run and checks it for content besides the batch, the budgets and the snapshot description. It catches a loop that places a paper card or other context into the first message on the agent's behalf.

**AG-26.** A run must finish with one atomic forecast and nomination submission.
<!-- id: SDD-AG-26 | tdd: TDD-3.1.57 | status: pending:#64 -->

- Trigger: The run calls submit.
- Behavior: Require one probability answer with evidence for every issued question for the three qualified registry targets, and an ordered list of zero to seven distinct eligible paper nominations with rationales. Forecast probability and reading preference are separate fields. Validate the whole submission before sealing; retries with the same submission id return the original result. Prediction-head unavailability does not prevent nominations.
- Observable: One submission records complete issued-question support and a bounded preference order.
- On failure: An invalid or incomplete submission is refused within the remaining run budget; expiration is operationally void.
- Verified by: A test rejects omitted questions and duplicate or out-of-batch nominations, and verifies a retry creates no extra records.
- Limits: No questions are issued for an unqualified target definition; a batch without qualified targets can still collect nominations for engineering operation.


**AG-27.** Every tool response must state the run's remaining budgets.
<!-- id: SDD-AG-27 | tdd: TDD-3.1.58 | status: pending:#57 -->

- Trigger: The loop returns a response to a tool call the agent model made (AG-09).
- Behavior: The loop attaches to every tool response the remaining amount against each budget in the run's contract (AG-12, AG-17), computed after the call that produced the response.
- Observable: Every tool response received by the agent model carries a remaining value for each budget named in the run specification.
- On failure: A response that cannot carry the remaining budgets is not sent, the tool call is treated as failed, and the failure is recorded.
- Verified by: A test that reads every tool response of a run and checks each one for a remaining value per budget in the contract. It catches a response that omits the budgets or states them only in the run's final message.

**AG-28.** The loop must not drop, summarize or reorder earlier messages to fit the agent model's context, and a run that no longer fits ends as its budget exhaustion does.
<!-- id: SDD-AG-28 | tdd: TDD-3.1.59 | status: pending:#45 -->

- Trigger: The conversation of a run grows too large for the agent model's context.
- Behavior: The loop (AG-08) sends the full, unmodified sequence of earlier turns and tool responses on every call to the agent model. When the conversation no longer fits, the run ends there, the same way a run ends when a budget is exhausted (AG-12, AG-15).
- Observable: Every request sent to the agent model contains the same earlier turns and tool responses in the same order as they were produced, with no message missing, shortened or moved, up to the point where the run ends.
- On failure: A run that cannot send its full conversation to the agent model ends without a submit and is void (AG-15). No message is dropped, summarized or reordered to keep the run going.
- Verified by: A test that grows a run's conversation past a fixed context size for a stand-in agent model and checks that the loop ends the run rather than dropping, summarizing or reordering any earlier message. It catches a harness that compacts the conversation to keep the run alive.

### 5.3 Records

**AG-16.** A genome must hold an island, a prompt, a scan policy, a read policy, a probability assignment rule, tools, budgets, sampling settings and a structured output schema.
<!-- id: SDD-AG-16 | tdd: TDD-3.1.60 | status: pending:#77 -->

- Trigger: An immutable launch configuration is offered for admission.
- Behavior: Hash all nine required parts in one configuration record; the island is one of cs, quant-ph and q-bio (AG-36). Launch sampling specifies exactly one forecast value per issued question; the submitted value is that recorded value, with no repeated sampling or averaging.
- Observable: Every admitted configuration contains all nine parts and reproduces its stamped hash; each accepted question has exactly one finite forecast value.
- On failure: A record that lacks a part is refused. It does not enter the population, gets no run specification, and the refusal is recorded.
- Verified by: A test exercises these cases: Omit the probability policy and reject admission; mutate any hashed part and detect identity change; offer a sample count of three or multiple answers to one question and reject them. A valid single answer seals unchanged.
- Limits: Use the bounded text policies, one-sample settings, fixed intents and immutable configuration contract in Appendix A: Launch profile.
**AG-17.** A run specification must hold a slot, a genome hash, a seed, a snapshot hash, budgets and the tools allowed.
<!-- id: SDD-AG-17 | tdd: TDD-3.1.61 | status: pending:#56 -->

- Trigger: A run is about to start for a genome on a batch.
- Behavior: The run specification is written with these six parts before the run starts. The run reads it and cannot change it (IN-24).
- Observable: A stored run specification exists for every run, written before the run's first call to the agent model, and its genome hash and seed equal those in the run's stamp (SR-15).
- On failure: When a run specification cannot be written with all six parts, the run does not start and the failure is recorded.
- Verified by: A test that starts a run on a contract with no seed and checks that the run does not start, and a test that compares each finished run's stamp with its run specification. It catches a run that starts on an incomplete contract or on one edited later.
- Limits: A slot is daily batch id, shard id, configuration id and attempt zero. The seed is derived from its canonical hash under Appendix A: Launch profile.
**AG-29.** The loop must record every request to the agent model and every response, by hash and in order, with the run.
<!-- id: SDD-AG-29 | tdd: TDD-3.1.62 | status: pending:#45 -->

- Trigger: The loop sends a request to the agent model or receives its response, inside the conversation AG-08 defines.
- Behavior: The loop writes one record for the request and one for the response, each holding its hash and its place in the run's order, and ties both to the run identified by its stamp (SR-15).
- Observable: The ledger holds, for each run counted in a report (IN-18), one record per request and one per response, in send order, each identified by its hash.
- On failure: A request or response that cannot be recorded stops the loop. The run ends without a submit and is void (AG-15), and the failure is recorded.
- Verified by: A test that runs the loop against a stand-in for the agent model and checks that every request and response the stand-in exchanges has a matching record in the ledger, in order and by hash. It catches a run whose reported turns the ledger does not confirm.

**AG-30.** The run record must name every image a deep read gave the agent model.
<!-- id: SDD-AG-30 | tdd: TDD-3.1.63 | status: pending:#45 -->

- Trigger: A deep_read call delivers an image to the agent model (AG-02, MD-11).
- Behavior: The run's record names the paper and the image for each one the response carried, in the order they were sent, alongside the same run's stamp (SR-15).
- Observable: For a run that called deep_read on a paper with a figure, the run's record names that figure for the spot check (IN-11) to read, and the images named match those the tool response carried.
- On failure: An image that cannot be named in the run's record does not reach the agent model, and the omission is recorded with the run.
- Verified by: A test that calls deep_read on a paper with two figures and checks that both are named in the run's record in the order sent, and a test that blocks the naming step and checks that the image is withheld from the response. It catches an image the agent model received that the run's record does not account for.
- Limits: A LaTeX table served as MD-11 describes is text, not an image, and sits outside this requirement.

### 5.4 Selection and mutation

**AG-18.** Weekly selection evaluation must hold the seeded population unchanged through its first two weekly cycles.
<!-- id: SDD-AG-18 | tdd: TDD-3.1.64 | status: pending:#64 -->

- Trigger: The select stage is reached.
- Behavior: Apply FT-14 before any parent or replacement operation, separately within each island. Record selection-disabled and carry the population forward in the first two weekly cycles, so the first comparison has a control. Afterwards draw parents and replacements within each island under FT-14 alone, never touching a founder (AG-38); neither calendar time nor accumulated citation outcomes enables anything by itself.
- Observable: Each weekly cycle records the resulting population of each island and the governing selection policy.
- On failure: Missing policy or ledger data prevents replacement and records the reason.
- Verified by: A test supplies mature forecasts over several weekly cycles and confirms no parent draw in the first two, and a policy-governed draw in the third.


**AG-19.** Parent selection must draw a parent only from genomes the accepted policy declares eligible.
<!-- id: SDD-AG-19 | tdd: TDD-3.1.65 | status: pending:#56 -->

- Trigger: A job or request attempts parent selection.
- Behavior: Return disabled-by-profile through the seeded population's first two weekly cycles. Afterwards draw parents within the island by the forecast skill FT-12 reports, or by the island's registered proxy while skill is unavailable, ranked under FT-14, skipping a genome below the minimum resolved-claim count. A parent from another island is a migration (AG-37). No agent output or cost figure ranks a parent; a rating enters only as preference credit (IN-43). Preserve the request disposition.
- Observable: Each draw records the ranked support it used, the eligible genomes and the parents drawn.
- On failure: A missing profile cannot enable it, and absent eligibility data leaves the population unchanged.
- Verified by: A test invokes the mechanism during the two fixed cycles and verifies no draw, then offers a genome below the resolved-claim count and verifies it is neither drawn nor replaced.
- Limits: The minimum resolved-claim count is not yet set and rests on #130.


**AG-20.** A mutation proposal must change exactly one field of one parent genome.
<!-- id: SDD-AG-20 | tdd: TDD-3.1.66 | status: pending:#56 -->

- Trigger: A job or request proposes a mutation.
- Behavior: Return disabled-by-profile through the seeded population's first two weekly cycles. Afterwards accept a proposal that changes one hashed part carrying a parent's reading emphasis and leaves the common model, tools, budgets, targets and schema equal (AG-03, AG-34, AG-35). The new value is written by the operator or copied from a genome of another island (AG-37), never generated by a model call; the child takes the island it is offered to. Preserve the request disposition.
- Observable: Every accepted proposal names its parent, the changed part and the resulting configuration hash.
- On failure: A missing profile cannot enable it, and a proposal touching more than one part, or a shared part, is refused whole.
- Verified by: A test invokes the mechanism during the two fixed cycles and verifies no proposal is accepted, then refuses a later proposal that changes two parts, one that changes the budgets and one that adds a schema field.
- Limits: The emphasis-carrying parts are the prompt, the scan policy, the read policy and the probability assignment rule (AG-16); schema evolution stays inactive under AG-35.


**AG-21.** Mutation similarity admission must refuse a child that repeats a genome already in the population.
<!-- id: SDD-AG-21 | tdd: TDD-3.1.67 | status: pending:#56 -->

- Trigger: A child produced under AG-20 is offered to the population.
- Behavior: Return disabled-by-profile through the seeded population's first two weekly cycles. Afterwards refuse a child whose hashed parts equal those of an active genome of its island or of the archived best of a retired lineage of that island (FT-15). Admission remains subject to AG-31 and AG-37. Preserve the request disposition in the audit record.
- Observable: Each admission decision records the child's configuration hash and the hash it was compared against.
- On failure: A missing profile cannot enable it, and an undecidable comparison refuses the child.
- Verified by: A test offers a child identical to an active genome and one identical to an archived genome, and verifies both are refused while a child differing in one part is admitted.
- Limits: Comparison is over the hashed genome parts, not over run output or measured score.


**AG-35.** The schema evolution mechanism must remain inactive at launch.
<!-- id: SDD-AG-35 | tdd: TDD-3.1.68 | status: pending:#56 -->

- Trigger: A launch job or request attempts this mechanism.
- Behavior: Return disabled-by-profile for schema evolution. Keep the immutable schemas as they are; selection under FT-14 changes genome parts, never the structured output schema. No dormant search algorithm, extra model call or archive service is required. Preserve the request disposition in the audit record.
- Observable: No launch state transition activates the deferred mechanism.
- On failure: A missing profile cannot enable it.
- Verified by: A test invokes the mechanism with otherwise valid input and verifies no model request or population mutation occurs.
- Limits: Activation requires an accepted future SDD amendment and preregistered evaluation, not a runtime flag alone.


**AG-36.** A genome must belong to exactly one island and run only on that island's shards.
<!-- id: SDD-AG-36 | tdd: TDD-3.1.72 | status: pending:#139 -->

- Trigger: A genome is offered to the population (AG-16), or a run specification is built for it (AG-17).
- Behavior: Admission requires the island part to name cs, quant-ph or q-bio. Slot creation offers a genome only the shards routed to its island (EN-09); papers of another island reach it through its tools alone and never as a shard.
- Observable: Every admitted genome names one island, and every run specification's shard belongs to that island.
- On failure: A genome with no island or an unknown one is refused and gets no run specification; a slot pairing a genome with another island's shard is not created, and the refusal is recorded.
- Verified by: A test that offers a genome without an island and one naming an unknown island and checks both refusals, and a test that builds a day's slots and checks that no genome holds a shard of another island.
- Limits: The three islands and their primary categories are fixed in Appendix A: Launch profile; a new island is an amendment.

**AG-37.** A mutation that takes its parent or its changed field from another island must be recorded as a migration and must not be admitted into the q-bio island.
<!-- id: SDD-AG-37 | tdd: TDD-3.1.73 | status: pending:#139 -->

- Trigger: A mutation proposal (AG-20) names a parent, or copies a field, from a genome of a different island than the one it is offered to.
- Behavior: The child carries the island it is offered to, and its lineage record names the source island, the source genome hash and whether the parent or one field migrated. A proposal whose destination is the q-bio island is refused; a proposal whose source is the q-bio island is admitted.
- Observable: Each migrated child's lineage names its source island and genome; no genome of the q-bio island has a lineage record naming another island as source.
- On failure: A migration into q-bio is refused whole and recorded; a migration whose source genome cannot be resolved is refused.
- Verified by: A test that proposes a child for the cs island from a quant-ph parent and checks the migration record, one for the q-bio island from a cs parent and checks refusal, and one for the cs island from a q-bio parent and checks admission.
- Limits: Migration is one field or one parent per proposal, as AG-20 bounds every mutation.

**AG-38.** One founder genome per island must be exempt from replacement and must run on every batch of its island.
<!-- id: SDD-AG-38 | tdd: TDD-3.1.74 | status: pending:#139 -->

- Trigger: The select stage (FT-14) ranks an island, or a day's slots are created.
- Behavior: The owner marks one seeded genome per island as its founder at admission. FT-14 never retires a founder and never counts it among the genomes the budget admits or removes; the founder can be a parent. Every batch of its island issues the founder its shards like any other member, so its skill is measured throughout as the island's no-selection arm.
- Observable: Each island has exactly one founder, present in every weekly population record and every day's slot set.
- On failure: An island with no founder or two founders refuses the select stage and records the reason; a retirement that would remove a founder is refused.
- Verified by: A test that runs a third weekly cycle with the founder ranked last and checks that it stays, and one that offers two founders for one island and checks refusal.
- Limits: The founder counts toward the island's floor of four (FT-14).

### 5.5 Exclusion actions

**AG-22.** Exclusion actions must be graduated, applied in this order: quarantine of the run, then quarantine of the lineage, then purge.
<!-- id: SDD-AG-22 | tdd: TDD-3.1.69 | status: pending:#56 -->

- Trigger: A condition that triggers an exclusion action is met for a run or for a lineage.
- Behavior: Quarantine of a run sets its forecasts aside from scoring (FT-12, FT-14). Quarantine of a lineage takes the genome and its descendants out of the population, so they get no runs and take no part in selection, and purge makes that permanent. The steps apply in that order with none skipped, and no ledger record is removed at any step (SR-14).
- Observable: Each run and lineage subject to exclusion has a recorded exclusion action state, and the ledger holds one exclusion action record for each step applied (AG-23), in order.
- On failure: When a step cannot be applied, the state stays at the step before it and the failure is recorded.
- Verified by: A test that attempts to purge a lineage that has not been quarantined and checks that the attempt is refused, and a test that takes one lineage through the three steps and checks the order of its exclusion action records. It catches a step applied out of order.
- Limits: Apply the exact run/configuration quarantine and authority-revocation rules in Appendix A: Launch profile; preserve audit records and distinguish schema mistakes.
**AG-23.** Exclusion actions must be recorded in the ledger.
<!-- id: SDD-AG-23 | tdd: TDD-3.1.70 | status: pending:#57 -->

- Trigger: An exclusion action step is applied (AG-22).
- Behavior: One ledger record is appended for each exclusion action step, with a kind that marks it as an exclusion action (EN-06) and a payload that names the step and the run or lineage it applies to.
- Observable: The ledger holds one exclusion action record for each step applied, inside the hash chain with every other record (EN-05).
- On failure: When the record cannot be appended, the step does not take effect and the failure is recorded.
- Verified by: A test that applies each of the three steps and checks that the ledger gains one exclusion action record per step and that the hash chain still verifies. It catches an exclusion action held only in working state, where it could be changed or lost without trace.

**AG-24.** Exclusion actions must not be mentioned in any prompt.
<!-- id: SDD-AG-24 | tdd: TDD-3.1.71 | status: pending:#57 -->

- Trigger: A prompt is assembled, for an agent run or for any other call to a language model.
- Behavior: Prompt assembly takes no input from exclusion action records or exclusion action state. The text it produces names no exclusion action, quarantine or purge.
- Observable: For the same genome and batch, the prompt sent to the agent model is identical whether or not any exclusion action has been applied.
- On failure: A prompt found to mention an exclusion action is not sent, and the failure is recorded.
- Verified by: A test that quarantines a run and then a lineage, assembles the prompts for the next batch, and checks that they are byte for byte what they are with no exclusion action applied. It catches exclusion action state reaching the agent model, which could then shape its behavior around it.

## 6. Reader

### 6.1 Paper cards

**RD-01.** The reader must preserve one current paper card and immutable historical paper-card versions per paper.
<!-- id: SDD-RD-01 | tdd: TDD-4.1.41 | status: implemented -->

- Trigger: A paper arrives, a compatible bundle is promoted or a previously missing signal becomes available.
- Behavior: Build a new immutable paper card from the original paper and available compatible signals, including overview/passage availability and extraction coverage under RD-25 to RD-28. Atomically update the current-card pointer; existing snapshots retain prior paper-card ids. Missing prediction heads, neighbors, graph metrics, counts or Jev assessments produce explicit unavailable fields. Identity and readable source text remain accessible even when every optional signal is unavailable.
- Observable: Every snapshot resolves its exact paper-card version; the current view carries per-signal availability.
- On failure: Failure to store core identity/text preserves the previous paper card and records the failure; optional-signal failure alone cannot discard the paper.
- Verified by: A test checks that A first paper with no neighbors and no trained prediction heads remains readable; promoting a model cannot mutate a sealed snapshot.

**RD-02.** Every model-produced number on a paper card must carry its producing model identity.
<!-- id: SDD-RD-02 | tdd: TDD-4.1.42 | status: pending:#68 -->

- Trigger: The reader writes a small-model number or a Jev assessment onto a paper card.
- Behavior: Jev numbers use the provider/model identity and pinning status of RD-19, including for a mutable provider alias. For small-model numbers, the reader writes beside the number the id of the model that produced it: the embedding model or one prediction head, as the shared model service (PL-08) served it when the number was produced. The id sits beside the number itself and not once for the whole paper card.
- Observable: On any stored paper card, each number from a small model has a model id beside it in the paper card's text.
- On failure: A Jev result without the required identity provenance becomes unavailable (RD-19). For a small-model number with no producing identity, that field becomes unavailable with its reason; the rest of the paper card remains usable under RD-01.
- Verified by: A check that reads every paper card in a snapshot and fails on a model-produced number with no id beside it. A test that changes the served model and fails when a paper card produced afterwards still carries the earlier id.
- Limits: The encoder's vector joins the paper card's numbers only once that layer is measured back in (SR-17, #51). An embedding-model id resolves to the representation manifest, which records the compute platform the vector came from (MD-06).

**RD-03.** Every small-model number on a paper card must be stamped with its model-state date and measured accuracy, while Jev assessments carry the provenance and smoke-test references of RD-19 and RD-22 and are marked unqualified.
<!-- id: SDD-RD-03 | tdd: TDD-4.1.43 | status: pending:#68 -->

- Trigger: The reader writes a small-model number or a Jev assessment onto a paper card.
- Behavior: A hosted Jev assessment carries its computation time, returned or configured model identity, pinning status, smoke-report reference and an unqualified marker; it has no invented checkpoint date. For small-model numbers, the reader writes beside the number the producing model's model-state date, and the model's measured accuracy as of the snapshot, taken from the accuracy measure SR-27 names for it. For a prediction head this is its fit date (FT-10); for the embedding model it is its adopted checkpoint date.
- Observable: On any stored paper card, each number from a small model has a model-state date and a measured accuracy beside it, next to the model id of RD-02.
- On failure: A Jev result with missing required provenance becomes unavailable (RD-19). For a small-model number, when its model-state date or measured accuracy is not known, the reader marks that field unavailable with its reason; the rest of the paper card remains usable under RD-01.
- Verified by: A test that promotes a new checkpoint (PL-14), produces a paper card and fails when a number carries any date other than that checkpoint's or an accuracy value other than the one SR-27's measure recorded for it as of the snapshot. It catches a stale date and an accuracy value carried over from an earlier checkpoint.
- Limits: The representation manifest behind an embedding-model number records its compute platform (MD-06); no paper card states a platform the manifest does not.

**RD-04.** An agent run must receive paper cards as text.
<!-- id: SDD-RD-04 | tdd: TDD-4.1.44 | status: pending:#68 -->

- Trigger: An agent run calls a tool that returns paper cards (AG-09).
- Behavior: The reader renders each paper card as text that a person can read as it stands: each signal under a label, with its value and its stamps (RD-02, RD-03) beside it. The tool returns that text unchanged; query_cards can attach a separately identified query-evidence envelope under RD-27 without mutating the stored paper card.
- Observable: The response a run receives for a paper card is readable text and matches the paper card held in the snapshot the run reads.
- On failure: A paper card that cannot be rendered as text is not stored (RD-01), so no run receives it.
- Verified by: A test that calls each tool that returns paper cards against a snapshot and fails when a response carries a paper card in any other form, such as an encoded binary block or a pointer to stored model output.

**RD-05.** The reader must keep raw vectors from an agent run.
<!-- id: SDD-RD-05 | tdd: TDD-4.1.45 | status: pending:#57 -->

- Trigger: An agent run calls any of its tools (AG-09).
- Behavior: What the small models produce reaches a run only as the text of paper cards (RD-04): derived values such as a neighbor list, a distance or a probability. A raw vector, the list of numbers the encoder or the embedding model outputs for a text, appears on no paper card and in no tool response.
- Observable: No paper card in a snapshot and no response to a run holds a raw vector. A tool call that asks for one gets a refusal.
- On failure: A tool call that asks for a vector fits no tool schema (AG-11) and is refused. The run receives the refusal and nothing else.
- Verified by: A test that calls every tool a run is allowed for a paper whose vectors are known and fails when any stretch of those vector values appears in a paper card or a response.

**RD-14.** A discovery service's ranking or recommendation of a paper must not appear on a paper card or in a tool response.
<!-- id: SDD-RD-14 | tdd: TDD-4.1.46 | status: pending:#57 -->

- Trigger: The reader produces a paper card for a paper (RD-01), or a tool call returns a response about a paper (AG-09).
- Behavior: Nothing a discovery service ranked or recommended about a paper is written onto its paper card or returned in a response from any tool (RD-04). A count taken at the snapshot under RD-12 that happens to reflect a service's own feature stays on the paper card, and only the service's ranking or recommendation itself is withheld.
- Observable: No stored paper card and no tool response names a discovery service's rank or its recommendation of a paper.
- On failure: A value that would carry a discovery service's ranking or recommendation is left off the paper card and off every tool response. The paper card is completed without it (RD-01).
- Verified by: A test that supplies ingest with a discovery service's ranking for a known paper, produces its paper card and a tool response, and fails if either shows the ranking or a recommendation derived from it.

### 6.2 Signals

**RD-06.** A paper card must list the paper's nearest neighbors in the corpus.
<!-- id: SDD-RD-06 | tdd: TDD-4.1.47 | status: pending:#56 -->

- Trigger: The reader produces a paper card for a paper (RD-01).
- Behavior: The reader lists on the paper card the papers in the corpus whose vectors lie nearest to this paper's vector, nearest first, each by its paper id. All vectors compared come from the same model at the same checkpoint.
- Observable: A stored paper card shows an ordered list of paper ids, none of them the paper itself.
- On failure: A missing input or incompatible representation produces an unavailable field with its reason; the rest of the paper card remains usable under RD-01.
- Verified by: A test over a small corpus with known vectors that fails when the listed neighbors are not the nearest papers in order, when the list holds the paper itself, or when it holds an id absent from the corpus.
- Limits: Five strictly earlier, snapshot-visible original overview neighbors by exact cosine, ties by family id, under Appendix A: Launch profile.
**RD-07.** A paper card must give the paper's embedding distance.
<!-- id: SDD-RD-07 | tdd: TDD-4.1.48 | status: pending:#56 -->

- Trigger: The reader produces a paper card for a paper (RD-01).
- Behavior: The reader writes on the paper card one number, the embedding distance: how far the paper lies from the papers already in the corpus, by the measure in Limits, over the same vectors that give its neighbors (RD-06). The number carries the stamps of RD-02 and RD-03.
- Observable: A stored paper card shows one embedding distance with its stamps.
- On failure: A missing input or incompatible representation produces an unavailable field with its reason; the rest of the paper card remains usable under RD-01.
- Verified by: A test over a small corpus with known vectors that computes the embedding distance by the set measure and fails when the paper card's number differs, or when the paper card shows no embedding distance or more than one.
- Limits: Distance is mean one-minus-cosine over the same earlier neighbors; include count and mark zero neighbors unavailable. This is not a novelty or anomaly probability.
**RD-08.** Paper cards must expose three named forecast fields with their exact meaning and availability.
<!-- id: SDD-RD-08 | tdd: TDD-1.1.22 | status: pending:#64 -->

- Trigger: A paper card is built from a pinned bundle.
- Behavior: Follow the Appendix B: Learning protocol paper-card schema: target id/version, plain-language threshold/window question, calibrated probability or null, qualification and unavailable reason, horizon end, bundle id, training cutoff and evaluation link. Shared provenance can be referenced once. Keep Jev and source-linked passages separate. No prediction head acts as a retrieval filter.
- Observable: Every paper card names reach, late activity and cross-subfield reach, including missing states.
- On failure: Missing input or incompatible model marks the affected fields unavailable without discarding the paper card.
- Verified by: A test verifies one unavailable prediction head leaves the other qualified outputs and paper text intact; a missing value cannot become probability zero.
- Limits: No raw vector coordinates or composite quality score go to the agent. Live and retrospective estimates carry distinct eligibility; calibration is per primary category and covers the four corpus categories only.


The id RD-09 is reserved by #49: masked-LM surprise score leaves the paper card while weekly fine-tuning of the encoder is held out (SR-17, #51).

**RD-10.** A paper card must give the paper's graph features.
<!-- id: SDD-RD-10 | tdd: TDD-4.1.49 | status: implemented -->

- Trigger: The reader produces a paper card for a paper (RD-01).
- Behavior: The reader writes on the paper card the paper's graph features, each a labelled value computed from the citation graph (MD-07, MD-08) as it stands when the paper card is produced. No small model produces a graph feature, so RD-02 and RD-03 place no stamp on it.
- Observable: A stored paper card shows each graph feature by name with its value.
- On failure: When the citation graph cannot be read, graph fields become unavailable with reasons and the rest of the paper card remains usable under RD-01. A feature is never written as 0 because the graph could not be read.
- Verified by: A test that builds a small citation graph of known structure, produces a paper card for a paper in it and fails when a listed feature is missing or its value differs from the value worked out by hand.
- Limits: Expose incoming/outgoing unique family counts and matched-reference fraction with source, timestamp and missingness under Appendix A: Launch profile.
**RD-11.** A paper card must give, for the paper's nearest earlier neighbors, the outcomes that resolved before the snapshot.
<!-- id: SDD-RD-11 | tdd: TDD-4.1.50 | status: implemented -->

- Trigger: The reader produces a paper card for a paper (RD-01).
- Behavior: Among the papers nearest to this paper's vector (RD-06), the reader keeps those that entered the corpus earlier than this paper, and for each earlier neighbor writes on the paper card the outcomes recorded for it whose resolution record predates the snapshot. An earlier neighbor with no such outcome is listed with none.
- Observable: A stored paper card shows, beside each earlier neighbor, the outcomes resolved for it before the snapshot, or a statement that it has none.
- On failure: A missing input or incompatible representation produces an unavailable field with its reason; the rest of the paper card remains usable under RD-01.
- Verified by: A test over a small corpus with known arrival dates and known resolution dates that fails when a later-arriving paper appears among the earlier neighbors, when a listed outcome resolved after the snapshot, or when an outcome resolved before the snapshot is missing from the paper card.
- Limits: At most five earlier neighbors with pre-snapshot outcomes of the exact target version, as fixed in Appendix A: Launch profile.
**RD-12.** A paper card must preserve available snapshot-time author citation counts and explicitly disable optional social counters.
<!-- id: SDD-RD-12 | tdd: TDD-4.1.51 | status: implemented -->

- Trigger: The reader produces a paper card for a paper (RD-01).
- Behavior: Include each author's prior citation count only from a permitted preserved response available by the snapshot. Attach source, capture time and unavailable reason. Repository, Hugging Face, download and discussion counters are disabled at launch and cannot be silently fetched or inferred.
- Observable: Author counts trace to eligible source bytes; absent author data and disabled counters are distinct unavailable states.
- On failure: When a count cannot be read as of the snapshot, the paper card gives no number for it and says in words that the count is absent.
- Verified by: A test exercises these cases: Pin author counts at snapshot, add a later response and verify unchanged output; missing authors remain unavailable and disabled counter adapters are never invoked.
- Limits: Optional social, repository and download counters are disabled at launch; unavailable fields do not block paper cards or training.
**RD-13.** A paper card must give the distance between the paper's vector and the mean vector of the papers it cites.
<!-- id: SDD-RD-13 | tdd: TDD-4.1.52 | status: pending:#56 -->

- Trigger: The reader produces a paper card for a paper (RD-01).
- Behavior: The reader takes the vectors of the papers this paper cites in the citation graph (MD-07, MD-08), computes their mean, and writes on the paper card the distance between the paper's own vector and that mean, by the same measure of nearness that RD-06 and RD-07 use. The number carries the stamps of RD-02 and RD-03.
- Observable: A stored paper card shows one such distance, labelled apart from the embedding distance of RD-07.
- On failure: A missing input or incompatible representation produces an unavailable field with its reason; the rest of the paper card remains usable under RD-01.
- Verified by: A test over a small citation graph with known vectors that computes the distance by hand and fails when the paper card's number differs, or when the paper card shows more than one such distance.
- Limits: Use normalized reference-centroid cosine distance, with missing-vector count and zero-centroid unavailability under Appendix A: Launch profile.
### 6.3 Jev launch assessments

These assessments are held out of the launch until provider access exists (SR-17, #123). The requirements below keep their ids, text and trace status; they take effect when a later accepted decision admits the assessments, with the smoke test, preregistration and readiness record unchanged. The execution gates #59 to #62 are deferred with them, and the without-Jev arm of RD-23 is the launch.

The rubric is project-specific. It describes supplied paper content and does not certify scientific correctness, novelty, reproducibility or future impact. Provider access, limits and operating values are the readiness gates in RD-24; the interface sources are listed in [pinned model and provider sources](../evidence/models/pinned-sources.md).

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
<!-- id: SDD-RD-15 | tdd: TDD-4.1.53 | status: pending:#54 -->

- Trigger: A paper card is assembled.
- Behavior: The paper card includes the eight assessment fields of RD-16 or the unavailable state of RD-18. Agents interpret these as content assessments. No composite quality score, automatic paper exclusion or ranking is derived from them. They do not enter prediction-head inputs (FT-09), deterministic outcome resolution, baseline regression inputs (IN-09) or fitness directly; an agent forecast informed by the assessments is scored normally.
- Observable: Each paper card labels the assessment source and rubric version separately from forecasts and measured counts, and states that the assessments are not measured against human labels.
- On failure: An unavailable assessment is rendered with its reason; a permanent inability to provide the launch feature fails RD-24.
- Verified by: A test checks that each paper card carries a result or unavailable state, and that changing only assessment fields leaves prediction-head inputs, baseline inputs and resolver inputs unchanged.
- Limits: The assessments are held out of the launch until provider access exists (SR-17, #123); this requirement takes effect when a later accepted decision admits them.

**RD-16.** Every Jev assessment must use the eight-field rubric in this subsection as a fixed, versioned set of categorical questions.
<!-- id: SDD-RD-16 | tdd: TDD-4.1.54 | status: pending:#54 -->

- Trigger: An assessment request is assembled.
- Behavior: Each table row becomes a separate Choice question with its full category criteria. All questions inspect the same supplied text; contribution type does not gate another question. The rubric carries a version and hash, includes annotated category-boundary examples, and is outside the mutable genome. No question asks for an overall quality, novelty or future-impact score.
- Observable: The stored request contains exactly the eight fields, their category definitions and the rubric hash.
- On failure: A missing field, altered unversioned rubric or attempted agent mutation is rejected and recorded.
- Verified by: A test compares the request against the versioned rubric and rejects an extra quality question, a missing field or a genome-supplied rubric change.
- Limits: The assessments are held out of the launch until provider access exists (SR-17, #123); the rubric takes effect when a later accepted decision admits them.

**RD-17.** Jev input must be limited to the immutable paper version's extracted text and recorded extraction coverage.
<!-- id: SDD-RD-17 | tdd: TDD-4.1.55 | status: pending:#56 -->

- Trigger: Ingest prepares an assessment request.
- Behavior: The input contains available paper text, appendices, captions and table text in document order, with extraction coverage. It contains no separately supplied popularity, reputation, discovery rankings, forecasts, other-paper context or generated summary. No external retrieval is performed for the assessment. Embedded author cues and provider pretraining knowledge are not represented as removed. Input is checked against the verified provider limit before sending; no truncation or chunk aggregation is performed.
- Observable: The stored input bytes and coverage identify exactly what text the request supplied.
- On failure: No usable text or input beyond the verified limit produces an unavailable result with a reason, rather than a partial silent request.
- Verified by: A test includes prohibited metadata alongside an allowed extraction and verifies the outbound input excludes it; over-limit and empty inputs produce no provider call.
- Limits: Apply non-executing LaTeX then PDF text extraction, explicit coverage, and the lower of the verified provider limit and the launch input cap in Appendix A: Launch profile. The assessments are held out of the launch until provider access exists (SR-17, #123).
**RD-18.** Assessment results must distinguish categorical uncertainty from processing unavailability.
<!-- id: SDD-RD-18 | tdd: TDD-4.1.56 | status: pending:#54 -->

- Trigger: A response is validated or an assessment cannot be obtained.
- Behavior: Each valid field retains its selected category, full probability distribution and provider confidence as a distribution summary, not measured accuracy. Not reported means no qualifying statement in the supplied content; not applicable means no meaningful target for that question; insufficient information means missing content or ambiguity prevents classification. Low confidence is retained without becoming a negative or unavailable result. A processing failure has an unavailable status and reason, without fabricated categories or numbers.
- Observable: The stored and rendered results preserve the category distributions and separate processing status.
- On failure: An invalid response produces unavailable with its validation reason; the base paper card remains usable under RD-01.
- Verified by: A test supplies low confidence, not reported, insufficient information, malformed probabilities and a timeout, and checks that only invalid or failed processing becomes unavailable.
- Limits: Exact response validation and category-boundary examples belong to the versioned rubric and TDD; no confidence cutoff is introduced. The assessments are held out of the launch until provider access exists (SR-17, #123).

**RD-19.** Every assessment must preserve its input, rubric, provider and computation provenance.
<!-- id: SDD-RD-19 | tdd: TDD-4.1.57 | status: pending:#54 -->

- Trigger: An assessment attempt completes.
- Behavior: The stored record contains the paper revision, extraction version, exact supplied text and hash, rubric version and hash, configured or returned provider/model identity, sanitized request and response, computation time, coverage, status and error reason. Identity distinguishes an immutable revision from a mutable alias; inability to pin a revision is explicit. No credential headers, invented weight hashes or checkpoint dates are stored.
- Observable: Every assessment field resolves to its exact request, response and smoke-report reference, with unavailable identity metadata stated explicitly. Provider identity changes are recorded and handled by RD-22.
- On failure: A result whose required provenance cannot be persisted is not exposed as a valid assessment; the failure is recorded.
- Verified by: A test rejects a result missing input provenance and verifies that an alias-only provider produces an explicit unpinned status instead of a fabricated checkpoint stamp.
- Limits: The assessments are held out of the launch until provider access exists (SR-17, #123); this provenance record takes effect when a later accepted decision admits them.

**RD-20.** Ingest must own bounded Jev requests and the reader must consume only stored results.
<!-- id: SDD-RD-20 | tdd: TDD-4.1.58 | status: pending:#56 -->

- Trigger: Assessment work becomes eligible for processing.
- Behavior: Ingest sends requests through its declared interface and network reach (SR-13). A local work key covers input, rubric and provider configuration; a completed saved result is reused. Configuration supplies validated request timeouts, retry limits and daily cost ceilings. Exhausted limits stop requests and record unavailable results. The reader gains no outbound path, and no fallback provider is introduced. An ambiguous timeout records billing uncertainty rather than claiming exactly-once provider execution.
- Observable: The work record identifies attempts, saved-result reuse and budget consumption; reader output references persisted results.
- On failure: A timeout, provider failure or exhausted budget leaves the base paper card available with an unavailable assessment. Missing operating limits refuse activation under RD-24.
- Verified by: A test reuses a completed work key without a second request, forces timeout and budget exhaustion, and verifies the base paper card remains available and the reader cannot reach the provider.
- Limits: Apply the 30-second timeout, explicit-rejection retry, concurrency two, 1000-attempt cap and funded sublimit in Appendix A: Launch profile. The assessments are held out of the launch until provider access exists (SR-17, #123), and the sublimit stays unused.
**RD-21.** An assessment recomputation must leave all earlier snapshot-visible artifacts unchanged.
<!-- id: SDD-RD-21 | tdd: TDD-4.1.59 | status: pending:#56 -->

- Trigger: An assessment or paper card is rebuilt.
- Behavior: A new result is stored as a new artifact. A paper-card snapshot pins its assessment artifact and rubric and provider provenance. Only artifacts available at the snapshot enter it; a result computed later is eligible only for future snapshots. Updating the current paper-card view does not overwrite a version referenced by a snapshot.
- Observable: An earlier snapshot returns the same paper card and assessment bytes after recomputation.
- On failure: An attempt to overwrite a referenced artifact or attach a later assessment to an earlier snapshot is rejected and recorded.
- Verified by: A test recomputes an assessment after snapshot creation and verifies that earlier runs still read the original bytes and cannot retrieve the new result.
- Limits: Recorded-response replay and temporal boundary contracts are fixed in Appendix A: Launch profile; actual rerun generation is not presumed deterministic. The assessments are held out of the launch until provider access exists (SR-17, #123).
**RD-22.** Every Jev rubric field must pass an engineering smoke test before launch use and be shown as unqualified.
<!-- id: SDD-RD-22 | tdd: TDD-4.1.60 | status: pending:#97 -->

- Trigger: The rubric or the declared provider/model identity is first activated or changes.
- Behavior: Run the complete eight-field request on the smoke sample in Appendix A: Launch profile. Record for each field the valid-result count, category distribution and unavailable reasons, with input coverage, latency and cost, and keep every request and response. The owner reads the stored answers and records the review before activation. No human reference labels, annotator agreement or accuracy measurement is required, and none is claimed. Paper cards mark every Jev field as not measured against human labels.
- Observable: A smoke report names the rubric, provider identity, sample papers and shortfall, per-field valid counts and unavailable reasons, latency, cost and the recorded owner review.
- On failure: A field below the valid-result floor or a missing owner review blocks activation of the assessment feature under RD-24. A provider or rubric identity change makes new results unavailable until a fresh smoke test passes; existing snapshots keep their results.
- Verified by: A test refuses activation when one field falls below the floor, when the owner review is missing and when the active provider identity differs from the smoke report's; a paper-card test checks that every available assessment carries the unqualified marker.
- Limits: Use the smoke sample and valid-result floor in Appendix A: Launch profile. A passing smoke test shows that the integration works on real papers, not that the answers are right. The assessments are held out of the launch until provider access exists (SR-17, #123), so no smoke test is run before then.
**RD-23.** The system must preregister and preserve a prospective comparison of agent forecasts with and without Jev assessments.
<!-- id: SDD-RD-23 | tdd: TDD-4.1.61 | status: pending:#56 -->

- Trigger: The launch assessment feature is prepared for activation.
- Behavior: The comparison uses the same prospective questions, paper snapshots, agent model, frozen agent configurations and budgets, differing in exposure to Jev fields. Comparison runs remain separate from the population and contribute neither parents nor selection fitness. Assigned-treatment analysis includes failed or missing delivery. Primary measure and pass/kill thresholds are recorded before runs under SR-18. Analysis accounts for forecasts sharing papers and cohorts. Improved forecasting is not reported before the planned outcome measurement.
- Observable: A preregistration record precedes comparison runs, and each paired input record documents treatment assignment, actual exposure and unavailable results.
- On failure: Missing preregistration blocks launch readiness; immature outcomes leave effectiveness pending and do not become a zero or a success.
- Verified by: A test rejects an unregistered comparison, verifies comparison runs cannot affect selection, and checks that a failed Jev delivery remains in its assigned-treatment analysis.
- Limits: Use the fixed paired 2000-paper, at-least-26-week comparison and citation-reach primary endpoint in Appendix A: Launch profile; registration permits launch before maturity. The with-Jev arm is suspended while the assessments are held out (SR-17, #123), and the without-Jev arm is the launch.
**RD-24.** Launch readiness must require a verified Jev integration, a passing smoke test and recorded operating profiles.
<!-- id: SDD-RD-24 | tdd: TDD-4.1.62 | status: pending:#56 -->

- Trigger: The deployment is checked for launch readiness.
- Behavior: The readiness record verifies provider access, permitted input and response retention, provider identity semantics, input constraints, real target-corpus input coverage, configured timeouts/retries/cost ceilings, a passing smoke test for the active identity (RD-22) and preregistered forecast comparison (RD-23). Missing access, a permanently unavailable feature or no smoke test blocks launch. Transient failures after activation use RD-18 and do not stop the daily pipeline. These checks apply when a later accepted decision admits the assessments.
- Observable: The readiness record links dated evidence and the exact active profiles, rubric and provider configuration.
- On failure: A missing readiness item blocks launch and names the unmet item without supplying a guessed default.
- Verified by: A check removes each required item in turn and verifies launch refusal; another supplies all items with immature forecast outcomes and verifies readiness.
- Limits: The exact profiles and thresholds are fixed in Appendix A: Launch profile. Launch readiness does not require this record while the assessments are held out (SR-17, #123); source access, provider permissions, the smoke test and authorized funding are deferred execution gates under #59 to #62.
### 6.4 Full-paper passage retrieval

**RD-25.** The reader must preserve source-linked passage embeddings alongside paper overview embeddings.
<!-- id: SDD-RD-25 | tdd: TDD-1.1.25 | status: implemented -->

- Trigger: A paper version is extracted and indexed.
- Behavior: Apply the representations, coverage and chunking rules in Appendix C: Retrieval protocol. Keep versioned source spans, section paths, extraction coverage and compatible model identities; do not silently truncate or pool a whole paper into one vector.
- Observable: Every indexed passage resolves to exact immutable extracted text and its paper version.
- On failure: Missing or partial extraction preserves overview access with explicit coverage; incompatible model limits block passage indexing.
- Verified by: A test checks that A real extracted document is chunked across a long section and a short appendix; every included token is covered, overlap is bounded, and source spans reconstruct the passages.

**RD-26.** Passage search must obey the run snapshot and bounded deterministic ranking.
<!-- id: SDD-RD-26 | tdd: TDD-1.1.26 | status: pending:#70 -->

- Trigger: query_cards receives a passage-mode request.
- Behavior: Apply the query, cosine ranking, family/version selection, tie order, non-overlap and result limits in Appendix C: Retrieval protocol through the existing tool.
- Observable: Responses record the query, snapshot, representation and returned evidence identities.
- On failure: Invalid or oversized queries are rejected; absent passage support is unavailable without an implicit overview fallback.
- Verified by: A test exercises these cases: An exact cosine reference comparison catches ranking drift, duplicated overlapping hits and a revised paper inserted after the snapshot.

**RD-27.** Paper-card responses must expose full-paper evidence as source-linked query attachments.
<!-- id: SDD-RD-27 | tdd: TDD-1.1.27 | status: pending:#116 -->

- Trigger: Passage search returns matches for a paper.
- Behavior: Keep the base paper card immutable and attach exact matching text, score, source location, query identity and coverage using Appendix C: Retrieval protocol. Deep reading resolves the surrounding source; no raw vectors or quality probabilities are inferred.
- Observable: A paper card shows its full-text availability and each search attachment traces to a snapshot-visible source span.
- On failure: An unresolvable span is withheld as failed evidence while core paper identity and overview text remain accessible.
- Verified by: A test checks that Two queries produce distinct evidence attachments while preserving the same base-card hash; each attachment reproduces its cited source bytes.

**RD-28.** Passage publication must preserve immutable snapshots and pass the fixed retrieval qualification.
<!-- id: SDD-RD-28 | tdd: TDD-1.1.28 | status: implemented -->

- Trigger: A passage index is published or enabled for a study.
- Behavior: Apply cache/atomic publication rules in Appendix C: Retrieval protocol and the source-anchored qualification in Appendix A: Launch profile. Reuse unchanged vectors and preserve prior membership. Engineering indexes remain distinguishable from study-qualified indexes.
- Observable: Index publication records artifacts, snapshot membership and qualification disposition.
- On failure: An interrupted build exposes no partial complete index; failed qualification prevents study activation.
- Verified by: A test interrupts publication, reuses unchanged artifacts and rejects study activation with a failed comparison.


## 7. Models

### 7.1 Encoder and embedding model

**MD-01.** A separate trainable encoder must remain outside the initial deployment.
<!-- id: SDD-MD-01 | tdd: TDD-4.1.63 | status: pending:#64 -->

- Trigger: Initial services are assembled or an encoder change is proposed.
- Behavior: The first deployment serves the frozen embedding model and qualified prediction heads only. No separate masked-language-model service, checkpoint or training job is required. Any later encoder adoption requires the decision and comparative evidence of #51, including compatible feature contracts and license review.
- Observable: The initial runtime has no dependency on a separate trainable encoder.
- On failure: Missing deferred encoder weights cannot prevent initial services from starting.
- Verified by: A test checks that A deployment with no ModernBERT artifact can serve the qualified frozen-embedding bundle; adding a training job without the #51 decision is rejected.

**MD-02.** The system must not train a model from scratch, that is, from weights that do not descend from published weights.
<!-- id: SDD-MD-02 | tdd: TDD-4.1.64 | status: pending:#57 -->

- Trigger: A batch job that trains a model starts.
- Behavior: Every model the system trains starts from published weights or from a checkpoint that descends from them, never from weights the system initialized itself. The prediction heads are fit under FT-08, have no published weights to start from, and fall outside this rule.
- Observable: The record of a borrowed component (SR-20) names the published weights that each trained model starts from. A training job given no starting weights refuses to run, and the refusal is recorded with the job (PL-16).
- On failure: If the starting weights cannot be loaded, the job stops and records the failure (PL-16). No checkpoint is produced and no newly initialized weights take their place.
- Verified by: A test that starts a training job with its starting weights withheld and checks that the job refuses and produces no checkpoint. It catches a job that falls back to newly initialized weights.

**MD-03.** Release recency must not automatically select or replace a representation.
<!-- id: SDD-MD-03 | tdd: TDD-4.1.65 | status: pending:#77 -->

- Trigger: A representation candidate or replacement is offered for admission.
- Behavior: Use the pinned representation from Appendix A: Launch profile. A newer publication/revision timestamp alone cannot replace it. Replacement requires a new immutable namespace, compatible feature construction, license evidence and the fixed retrieval/head comparisons before future-snapshot activation.
- Observable: Serving manifests resolve to the admitted artifact, and a newer unqualified candidate leaves the active identity unchanged.
- On failure: Reject automatic latest-version resolution or an unqualified replacement and retain the compatible active bundle.
- Verified by: A test exercises these cases: Present a newer artifact lacking qualification and confirm no pointer or snapshot change; incompatible dimensions or tokenizer identity also prevent admission.

**MD-04.** ModernBERT adoption must remain deferred with encoder fine-tuning.
<!-- id: SDD-MD-04 | tdd: TDD-4.1.66 | status: pending:#64 -->

- Trigger: Initial services are assembled or an encoder change is proposed.
- Behavior: The first deployment serves the frozen embedding model and qualified prediction heads only. No separate masked-language-model service, checkpoint or training job is required. Any later encoder adoption requires the decision and comparative evidence of #51, including compatible feature contracts and license review.
- Observable: The initial runtime has no dependency on a separate trainable encoder.
- On failure: Missing deferred encoder weights cannot prevent initial services from starting.
- Verified by: A test checks that A deployment with no ModernBERT artifact can serve the qualified frozen-embedding bundle; adding a training job without the #51 decision is rejected.

The id MD-05 is reserved by completed decision #27: a second trainable encoder kept as a swap is held out of the first build.

**MD-06.** The frozen embedding model must use the selected immutable launch representation.
<!-- id: SDD-MD-06 | tdd: TDD-4.1.67 | status: deviation:#105 -->

- Trigger: Encoding or prediction-head inference is prepared.
- Behavior: Use the pinned modernbert-embed-base revision, tokenizer, 768-dimensional attention-masked mean pooling, task prefixes and normalization in Appendix A: Launch profile. Compute in float32 on the host's graphics processor with deterministic algorithms; every vector in one representation namespace comes from that platform. Apply Appendix C: Retrieval protocol for passage pooling and Appendix B: Learning protocol for original-text features. Require artifact and retrieval qualification before study serving.
- Observable: Manifest records actual file hashes, immutable revision, dtype, dimension, compute platform and qualification evidence.
- On failure: Missing or incompatible artifacts leave the representation unqualified; no model alias, automatic substitute or second compute platform is accepted.
- Verified by: A test rejects a wrong dimension, revision or compute platform and verifies the exact document/query prefixes and [1536] prediction-head input.
- Limits: Model replacement uses the full namespace rebuild and qualification protocol in Appendix A: Launch profile.


**MD-12.** Neighbor retrieval must be measured on a fixed task, whether a paper's own references rank above random earlier papers, and reported for each embedding model version.
<!-- id: SDD-MD-12 | tdd: TDD-4.1.68 | status: pending:#56 -->

- Trigger: An embedding model version is adopted for the system (MD-06).
- Behavior: For a fixed sample of papers, the task ranks each paper's neighbors (RD-06) and checks whether its own references (MD-07, MD-08) rank above a matched set of random earlier papers. Every reference and every random paper compared existed in the corpus on the paper's own arrival day. This gives SR-27 its measure, reference and schedule.
- Observable: A stored result names the embedding model version it ran against, the count of papers in the sample, and how references ranked against random earlier papers.
- On failure: When a paper's arrival day cannot be established, or a reference or a random paper drawn for it cannot be confirmed to have existed in the corpus by that day, the paper is left out of the sample and the omission is recorded.
- Verified by: A test with a fixture corpus of known arrival days and citation links that fails when the recorded result counts a reference or a random paper that had not yet arrived by the paper's arrival day, or omits a paper whose full comparison set had arrived.
- Limits: Use the locked source-anchored retrieval test and five random earlier controls per sampled paper in Appendix A: Launch profile. Qualification is measured before study use, not inferred from a model name.
### 7.2 Citation graph

**MD-07.** The citation graph must preserve exact parsed source references with explicit unmatched entries.
<!-- id: SDD-MD-07 | tdd: TDD-4.1.69 | status: pending:#56 -->

- Trigger: A licensed source bibliography is parsed.
- Behavior: Parse without executing TeX. Match exact identifiers and explicit version relations to canonical families, retain source spans and mark unmatched strings; no fuzzy title guess creates an edge. Merge with the snapshot records in MD-08.
- Observable: Every parsed edge identifies its original source and matching evidence; unmatched counts remain visible.
- On failure: Missing LaTeX leaves parser coverage unavailable while other qualified graph evidence remains usable.
- Verified by: A test checks that ambiguous names do not create an edge and repeated versions collapse to one family.


**MD-08.** The citation graph must use captured OpenAlex relationships alongside parsed references.
<!-- id: SDD-MD-08 | tdd: TDD-4.1.70 | status: pending:#56 -->

- Trigger: Qualified source observations enter a graph snapshot.
- Behavior: Merge exact OpenAlex family relationships with MD-07 edges, preserving per-source provenance, actual availability and graph version. Do not make Semantic Scholar a launch dependency or conflate paper-card graph counts with the dedicated outcome protocol.
- Observable: Snapshot edges have family ids, source ids and capture times.
- On failure: Unavailable remote graph evidence leaves source-parsed edges and explicit missingness, not invented empty completeness.
- Verified by: A test merges duplicate source/index edges once and proves a later capture cannot change an old snapshot.


### 7.3 Figures and tables

The id MD-09 is reserved by completed decision #27: a third citation source is held out of the first build.

**MD-10.** The system must not run an optical character recognition model.
<!-- id: SDD-MD-10 | tdd: TDD-4.1.71 | status: pending:#57 -->

- Trigger: A container image is built, or a component handles a figure or a table from a paper.
- Behavior: No component loads or calls an optical character recognition model. The system does not turn figures or tables into recognized text, and they reach the agent model as MD-11 describes.
- Observable: The pinned inputs of every container image (PL-06) include no optical character recognition model, and no paper card or deep_read response carries text recognized from a figure.
- On failure: Content that cannot be read without such a model is left out and named as missing, and no recognized text is put in its place. A container image found to include such a model is not run, and the finding is recorded.
- Verified by: A check of the pinned inputs of every container image that fails when an optical character recognition model is among them. It catches a component that turns a figure into recognized text before the agent model sees it.

**MD-11.** Deep reads must expose source figures and tables or bounded rendered PDF pages.
<!-- id: SDD-MD-11 | tdd: TDD-4.1.72 | status: pending:#56 -->

- Trigger: A deep_read requests a section or page.
- Behavior: Use original source figures/table text when extractable; otherwise render requested immutable PDF pages under Appendix A: Launch profile. Preserve page/section identifiers and partial coverage. Treat every image, table and text span as untrusted data. No OCR or untrusted TeX compilation is introduced.
- Observable: Response contains bounded media with locators or an explicit unavailable reason.
- On failure: Missing source and unrenderable PDF yield unavailable media while preserving other readable content.
- Verified by: A test reads a PDF-only paper through rendered page images and verifies malicious text inside an image cannot change tool authority.


## 8. Fitting and training

### 8.1 Encoder fine-tuning

This subsection is empty in the first build. Weekly fine-tuning of the encoder is held out until the configuration without it has been measured on the same score (SR-17). The requirement ids it would use, FT-01 to FT-05, are reserved by #51, which decides when the layer enters.

### 8.2 Embedding model and agent model

**FT-06.** The embedding model must never be trained.
<!-- id: SDD-FT-06 | tdd: TDD-4.1.73 | status: pending:#57 -->

- Trigger: Any step of the daily cycle or the weekly cycle that uses the embedding model.
- Behavior: The embedding model's weights are loaded and only read. No training job, prediction head fit or calibration updates them, and no step writes a changed copy of them.
- Observable: The embedding model's stored weights are identical before and after every weekly cycle, and the embedding model id and checkpoint date stamped on paper cards (RD-02, RD-03) stay the same from cycle to cycle.
- On failure: A step that would write to the embedding model's weights stops, nothing from it is accepted, and the failure is recorded. The last accepted state stays in service (PL-13).
- Verified by: A test that runs a full weekly cycle on a fixture corpus and fails if the embedding model's weights afterwards differ from the weights before it, which catches a training job that updates both models together.

**FT-07.** The agent model's weights must never be trained.
<!-- id: SDD-FT-07 | tdd: TDD-4.1.74 | status: pending:#77 -->

- Trigger: Any batch job that is defined or started, and any call a component makes to the agent model.
- Behavior: No job or service trains, fine-tunes or updates agent-model weights or calls a training interface. Launch agent configurations remain fixed; operator admission of a new immutable configuration follows AG-03 without changing model weights.
- Observable: The batch job records (PL-16) hold no job that trains the agent model, and the declared service interfaces (PL-02) include no training interface for it.
- On failure: A batch job or call found to train the agent model is stopped, its output is discarded, and the finding is recorded.
- Verified by: A check that reads every batch job definition and every declared interface of the deployment (PL-02, PL-03) and fails if any of them trains or fine-tunes the agent model, for example a job that tunes it on run traces (SR-02).

### 8.3 Prediction heads

**FT-08.** The model service must fit three independent regularized logistic prediction heads.
<!-- id: SDD-FT-08 | tdd: TDD-1.1.8 | status: implemented -->

- Trigger: A qualified historical release or eligible refresh is available.
- Behavior: Fit one binary logistic model for each of the three target definitions using Appendix B: Learning protocol, with the frozen shared feature matrix, per-target masks, chronological partitions and separate calibration. No human-semantic target or encoder update enters launch fitting.
- Observable: The bundle preserves registry order, coefficients, selected penalty, data hashes and per-target qualification.
- On failure: A failed target remains unavailable or retains its compatible qualified incumbent.
- Verified by: A test verifies masked labels contribute no gradient, prediction heads can co-occur, and embedding weights never change.
- Limits: X has shape [N,2d]; probabilities, labels and masks have shape [N,3]. Independent models do not imply independent outcomes.


**FT-09.** The prediction head features must combine the original overview embedding and pooled full-paper passage embedding.
<!-- id: SDD-FT-09 | tdd: TDD-1.1.9 | status: pending:#70 -->

- Trigger: Features are built for a paper, when the prediction heads are fit (FT-10) and when prediction head probabilities are produced for a paper card (RD-08).
- Behavior: Build x = [overview, pooled passages] / sqrt(2) under Appendix C: Retrieval protocol from the first public version. The two normalized d-dimensional vectors produce one 2d-dimensional input. Pooling compensates for overlapping tokens. Fitting and inference share the exact source, extraction, chunk and representation contract; no Jev, citation counts or later evidence joins the features.
- Observable: Each prediction-head input has length 2d and records the overview, ordered passages, overlap weights, pooled vector and complete feature identity with computation and source dates.
- On failure: Missing overview or complete original full-text representation makes the prediction head unavailable; no zero fill, revised text or overview-only fallback is substituted. Partial retrieval remains available under RD-01.
- Verified by: A test reconstructs overlap weights and the 2d feature from stored original spans, changes later metadata without changing feature bytes, and rejects partial extraction or a revised-source substitution.
- Limits: Historical initialization remains FT-18. Representation capability stays under #25; encoder fine-tuning remains deferred under #51. The three automatic targets in #64 share this feature contract.

**FT-10.** The weekly cycle must attempt a versioned refit using only labels available at its freeze.
<!-- id: SDD-FT-10 | tdd: TDD-1.1.10 | status: pending:#64 -->

- Trigger: The weekly dataset freeze completes.
- Behavior: Build a manifest from eligible original-paper embeddings and mature labels available at the freeze. Use the same target and automatic observation protocol as initial fitting. Refit from the accumulated eligible fitting partition, then calibrate and validate. Corrections append label versions and identify affected artifacts; prior bundles and sealed predictions remain unchanged.
- Observable: Each target has a completed, skipped-insufficient-data, unchanged-data or failed refit record.
- On failure: A failed or skipped refit retains the prior accepted bundle, or explicit unavailability when none exists.
- Verified by: A test checks that A correction after the freeze and a newly observed immature positive cannot enter the current fit; an unchanged manifest cannot create a new claimed model.
- Limits: Historical initialization is required under FT-18; historical labels never count as an agent's prospective forecasts.

**FT-11.** Each candidate prediction head must be calibrated on a separate chronological partition before promotion.
<!-- id: SDD-FT-11 | tdd: TDD-1.1.11 | status: pending:#67 -->

- Trigger: A prediction-head fit completes.
- Behavior: Use the sigmoid calibration procedure and chronological partitions in Appendix B: Learning protocol. Fit, development, calibration and locked evaluation examples remain disjoint by paper family. The calibrator uses only calibration labels known by the freeze. Promotion requires the target-specific qualification report; serving uses the calibrated probability.
- Observable: The bundle records calibrator parameters, partition hashes, Brier scores and qualification disposition.
- On failure: An empty, single-class or disqualified calibration partition prevents promotion of that target.
- Verified by: A test checks that Moving a duplicate version into calibration is rejected; changing locked evaluation labels cannot alter fitted prediction head or calibrator parameters.
- Limits: Weekly validation is identified as development monitoring, not a fresh untouched test; a locked release benchmark is consumed once.

**FT-17.** Feature eligibility must distinguish source availability from representation computation time.
<!-- id: SDD-FT-17 | tdd: TDD-1.1.12 | status: pending:#68 -->

- Trigger: An embedding enters a historical fit or a live forecast snapshot.
- Behavior: Use original-version text with recorded source availability, extraction hash, ordered passage spans and pooling weights, combined-feature hash, model revision, preprocessing version and actual computation time. Historical fitting can compute embeddings now without backdating them. Live forecasts use only artifacts committed before snapshot sealing. Later revisions, downstream text, counts and Jev assessments never enter the prediction-head vector.
- Observable: Every vector has separate source and computation timestamps and an immutable representation identity.
- On failure: Unverifiable source versions or representation mismatches exclude the example; no later text is substituted.
- Verified by: A test checks that An embedding computed today from verified original text is eligible for deployment training, while revised text and vectors committed after a live snapshot are rejected.

**FT-18.** The system must build a versioned historical training corpus before serving qualified prediction heads.
<!-- id: SDD-FT-18 | tdd: TDD-1.1.13 | status: pending:#65 -->

- Trigger: Initial prediction head preparation begins.
- Behavior: Follow Appendix B: Learning protocol to select papers independently of outcomes, capture original versions, capture dated citation records, resolve automatic labels, partition families chronologically and freeze a release manifest. A current embedding model is permitted for deployment training. Reports call such evaluation retrospective and disclose unknown or later pretraining coverage; it is not evidence of historical foresight.
- Observable: A corpus release includes acquisition provenance, labels, unknown reasons, splits, licenses, hashes and a qualification report.
- On failure: An incomplete or unqualified corpus supports acquisition and engineering only; paper cards expose unavailable prediction heads.
- Verified by: A test checks that A famous-paper-only sample, missing-as-negative conversion and a retrospective report labelled prospective are rejected.
- Limits: Corpus stages and gates are in Appendix B: Learning protocol. No historical label enters evolutionary fitness without an actual pre-outcome sealed forecast.

### 8.4 Genome selection

**FT-12.** The scorer must report target-specific forecast skill beside the measured skill per dollar of the runs it scored.
<!-- id: SDD-FT-12 | tdd: TDD-4.1.75 | status: deviation:#130 -->

- Trigger: A weekly or comparison report evaluates sealed forecasts.
- Behavior: For each target separately, use matched resolved questions shared by compared genomes and the sealed fitting-base-rate baseline. Report Brier loss, 1 minus agent loss divided by baseline loss, and that skill divided by the measured model cost of the runs in its support. Use no average across targets. Historical training labels without pre-event sealed predictions never supply agent performance.
- Observable: Reports contain support ids, losses, unknown coverage, per-target skill and per-target skill per dollar, each with the cost records it was computed from.
- On failure: Zero baseline loss gives unavailable skill; empty support or unrecorded cost gives unavailable skill per dollar. Neither authorizes selection.
- Verified by: A test verifies omitted hard questions cannot silently improve common-support scores, historical labels cannot become agent forecasts, and a run with no recorded cost leaves skill per dollar unavailable rather than zero.
- Limits: Skill is the fitness FT-14 selects on. Skill per dollar breaks ties and constrains population size under FT-14, and never becomes the objective (EN-16).


**FT-13.** The weekly cycle must record exactly one selection disposition.
<!-- id: SDD-FT-13 | tdd: TDD-4.1.76 | status: pending:#64 -->

- Trigger: The select stage is reached under FT-16.
- Behavior: Apply FT-14 once. The seeded population's first two weekly cycles record selection-disabled with unchanged population; a later cycle records the replacement FT-14 decides, as one atomic population and archive update. No background selection step runs outside this stage.
- Observable: Each completed select stage records its policy and the resulting population identity of every island.
- On failure: An interrupted stage exposes no partial replacement and resumes idempotently.
- Verified by: A test retries the stage after interruption and verifies one disposition, no replacement in the first two weekly cycles and one atomic replacement in a later one.


**FT-14.** Automatic evolutionary selection must act on forecast skill alone, after the seeded population has completed two fixed weekly cycles.
<!-- id: SDD-FT-14 | tdd: TDD-4.1.77 | status: pending:#56 -->

- Trigger: The weekly select stage is reached.
- Behavior: Record selection-disabled and retain the population for its first two weekly cycles. Afterwards rank each island's genomes by the forecast skill FT-12 reports, or by the island's registered proxy while resolved outcomes are too few, break ties by skill per dollar, and admit as many genomes as the island's spend share covers. A genome below the minimum resolved-claim count is neither parent nor replaced; a founder is never replaced (AG-38). Never fall below four genomes in an island.
- Observable: Every select stage records its policy reason, the ranked support it used, the tie-breaks applied and the resulting population size.
- On failure: Missing policy information, unavailable skill or unavailable cost fails closed without changing the population.
- Verified by: A test supplies resolved forecasts through two weekly cycles and verifies no selection, then verifies that a third cycle ranks each island on its own skill, breaks a tie on skill per dollar, keeps the founder and refuses to drop an island below four genomes.
- Limits: The floor is four genomes per island; the ceiling is what the island's share of the authorized monthly cap covers. The minimum resolved-claim count is not yet set and rests on #130. Selection runs only under a preregistration that names its measures and each island's proxy (SR-18).


**FT-15.** The evolutionary diversity archive must retain the best-scoring genome of every retired lineage.
<!-- id: SDD-FT-15 | tdd: TDD-4.1.78 | status: pending:#56 -->

- Trigger: A select stage retires a lineage under FT-14.
- Behavior: Return disabled-by-profile through the seeded population's first two weekly cycles. Afterwards store, in the same atomic update that retires the lineage, the immutable genome of its highest-skill member with the support that scored it. Archived genomes run no further and bound AG-21 admission. Preserve the request disposition in the audit record.
- Observable: Each retirement records one archived genome hash, its skill and the support ids behind it.
- On failure: A missing profile cannot enable it, and an archive write that fails leaves the population unchanged.
- Verified by: A test retires a lineage of three genomes and verifies that exactly the highest-skill one is archived, that it starts no run, and that an identical child is refused under AG-21.
- Limits: The archive holds genomes and their scoring support alone, and never becomes a second population.

**FT-26.** The weekly report must give, for every genome, its citation skill, its preference credit and the count of rated entries it was credited on, as separate values.
<!-- id: SDD-FT-26 | tdd: TDD-4.1.80 | status: pending:#140 -->

- Trigger: The report step of the weekly cycle runs (FT-16).
- Behavior: For each island and each of its genomes the report gives the per-target skill of FT-12, the summed preference credit of IN-43 over the week, and the count of rated entries that credit came from, in separate columns that are never combined into one number. It also gives, per island, the founder's values beside the rest, the rater's like rate on system picks against controls and service picks with intervals (IN-15), and the migrations admitted that week.
- Observable: One weekly report per island with those columns for every genome that was in the island at the freeze.
- On failure: A genome with no rated entries shows zero credit and a zero count, not an absent row; a missing skill shows unavailable.
- Verified by: A test that builds a report from known credits and skills and checks that each column matches the stored records and that no column is derived from another.
- Limits: The q-bio island's preference columns are always zero, and its report says why.


### 8.5 Weekly cycle

**FT-16.** The weekly cycle must freeze data, attempt fitting and calibration, score, conditionally select, and report in that order.
<!-- id: SDD-FT-16 | tdd: TDD-1.1.24 | status: pending:#64 -->

- Trigger: Monday at 00:00 UTC.
- Behavior: Freeze committed inputs and process the stages in order. Insufficient labels, unchanged data or a failed candidate retain the prior bundle and allow scoring and reporting. The select stage records its disposition under FT-14; FT-12 supplies measurements, not selection authority. Each stage records its input manifest and terminal status; partial job outputs never become inputs.
- Observable: One weekly record identifies the freeze and stage dispositions.
- On failure: Corrupt source artifacts or ledger-integrity failure stop dependent work; a model qualification failure alone does not suppress the report.
- Verified by: A test checks that A failed prediction-head fit still permits scoring with the old bundle, while a broken ledger hash stops scoring and selection.
- Limits: Encoder fine-tuning remains deferred under #51.


### 8.6 Historical evidence and qualification

**FT-19.** Historical and prospective labels must share one versioned automatic observation protocol.
<!-- id: SDD-FT-19 | tdd: TDD-1.1.14 | status: pending:#64 -->

- Trigger: Labels or settlements are assembled.
- Behavior: Use identical target predicates, family reconciliation, provider-date intervals, taxonomy policy and uncertainty bounds from Appendix B: Learning protocol. Preserve source capture and maturity separately. Historical reconstruction and prospective capture have distinct acquisition-kind fields, never fabricated historical availability.
- Observable: Every label traces to preserved source artifacts and one resolver version.
- On failure: An unsupported protocol or corrupt artifact yields unknown.
- Verified by: A test feeds identical preserved observations through both resolver entry points and obtains identical labels while retaining different acquisition provenance.


**FT-20.** Additional prediction heads must require an explicit versioned extension and independent qualification.
<!-- id: SDD-FT-20 | tdd: TDD-1.1.15 | status: pending:#64 -->

- Trigger: A target beyond the three launch prediction heads is proposed.
- Behavior: Require an accepted definition, feasible label source, time and missingness rules, acquisition costs, representative qualification, calibration, held-out skill and incremental-value comparison. Preserve earlier definitions and bundle/card compatibility. Semantic-use and evaluation prediction heads and Jev-assisted downstream annotation are deferred; no launch job produces those labels.
- Observable: The registry contains exactly three launch targets and only explicitly accepted later versions.
- On failure: An unregistered target cannot enter a fit, bundle or paper card.
- Verified by: A test rejects an extra target and verifies a failed extension cannot disable existing qualified prediction heads.
- Limits: The extension exists because citation indicators omit substantive use, correctness and long-term value. It does not promise that future labels are obtainable.


**FT-21.** Automatic labels must preserve uncertainty and require evidence for both positive and negative verdicts.
<!-- id: SDD-FT-21 | tdd: TDD-1.1.16 | status: pending:#66 -->

- Trigger: A mature observation is resolved.
- Behavior: Apply the lower/upper-bound predicates in Appendix B: Learning protocol. Definite witnesses can establish true; false requires completed capture and an upper bound below the target predicate. Missing dates, uncertain identity, incomplete capture or unknown subfields remain unknown whenever they can change the result.
- Observable: Labels retain witnesses or completion proofs, count bounds and reasons.
- On failure: Invalid source, unmatched target or immature observation returns unknown, never zero.
- Verified by: A test covers boundary dates, duplicated families, missing subfields and pagination failure without requiring downstream text.
- Limits: An unknown breadth label does not automatically mask the other two targets. Self-author citations are included and never described as independent use.


**FT-22.** Source and label qualification must precede serving trained prediction heads.
<!-- id: SDD-FT-22 | tdd: TDD-1.1.17 | status: pending:#64 -->

- Trigger: An acquisition pilot or modeling release completes.
- Behavior: Apply the 100-paper source pilot, 2000-to-5000 modeling cap, coverage, class-count and chronological evaluation gates in Appendix B: Learning protocol. Preserve selected denominators and report correlated targets separately. Human semantic annotation and its agreement study are not required.
- Observable: Each gate records counts, pass/fail, source costs and exclusions.
- On failure: Failure keeps the affected target unqualified and cannot silently relax thresholds or expand workload.
- Verified by: A test rejects positive-enriched sampling and verifies a missing feature or label cannot disappear from coverage denominators.


**FT-23.** Model promotion must be atomic and tied to immutable representation and target identities.
<!-- id: SDD-FT-23 | tdd: TDD-1.1.18 | status: pending:#64 -->

- Trigger: A qualified fitted bundle is proposed for serving.
- Behavior: Verify hashes, dimensions, preprocessing, target versions, prediction head and calibrator compatibility, corpus manifest and evaluation gates before changing the active pointer. Future snapshots use the new bundle; earlier snapshots retain their bundle. A target failing qualification stays unavailable initially or retains its prior compatible artifact.
- Observable: Every bundle lists each target as qualified or unavailable and records the promotion decision.
- On failure: Any incompatible mixture is rejected and the current pointer is unchanged.
- Verified by: A test checks that An interrupted promotion and a prediction head from another embedding revision cannot change active serving or historical snapshots.


**FT-24.** Readiness must distinguish engineering operation, individual prediction heads and the complete three-head feature.
<!-- id: SDD-FT-24 | tdd: TDD-1.1.19 | status: pending:#64 -->

- Trigger: Collection or serving readiness is checked.
- Behavior: Permit source capture, readable paper cards, smoke-tested original-paper Jev assessments and engineering runs before prediction heads qualify. Serve each qualified target independently with explicit unavailable fields for others. Declare the complete three-head feature ready only when all three pass; prospective benefit additionally requires mature sealed predictions.
- Observable: Readiness identifies each prediction head, the all-three gate and separate Jev/platform gates.
- On failure: A failed prediction head prevents an all-three readiness claim while leaving independent engineering work available.
- Verified by: A test starts with an empty registry, qualifies two prediction heads and verifies readable paper cards but refusal of complete three-head readiness.


**FT-25.** Label and representation corrections must invalidate affected candidates without rewriting history.
<!-- id: SDD-FT-25 | tdd: TDD-1.1.20 | status: pending:#64 -->

- Trigger: A label correction, source correction or embedding revision is accepted.
- Behavior: Append the new version, enumerate dependent manifests and reports, and mark affected evaluations stale. Build a replacement release and requalify before promotion. Preserve prior bytes and sealed predictions. A new embedding revision requires new embeddings and fitted prediction heads; no vector or weight is relabelled as compatible.
- Observable: Dependency records connect corrections to superseded releases and replacement evaluations.
- On failure: Unresolved provenance prevents new promotion; critical qualification invalidation withdraws affected serving with an explicit unavailable state.
- Verified by: A test checks that Correcting a test label triggers reevaluation and cannot silently retain an invalid qualification badge.

<a id="launch-profile"></a>
## Appendix A: Launch profile

<a id="launch-profile-launch-behavior-and-operating-profile"></a>

Version: launch-v2. Decisions #56, #105, #123, #129 and #130; records 0008 and 0015. The SDD clauses that cite this profile make these values part of their contract. These are chosen bounds and acceptance rules, not reported benchmark results. Appendix B: Learning protocol owns target semantics and training; Appendix C: Retrieval protocol owns passages. A change to a scientific comparison or behavior creates a new profile, comparison registration and compatible artifacts. Execution requires deployment bindings and successful qualification.

<a id="launch-profile-scope-and-deferred-behavior"></a>
### Scope and deferred behavior

Launch includes original-paper acquisition, full-text retrieval and pooled features, three automatic citation prediction heads, a seeded population of eight agent configurations, sealed citation forecasts, a private digest and ratings. Recommendation is a separate ranked nomination, not an assertion of scientific quality and not automatically a forecast. Where qualified target questions are issued, runs answer them separately. Missing forecasts do not become dislike labels.

The eight Jev content assessments are held out of the launch under SR-17 until provider access exists (#123). RD-15 to RD-24 keep their ids, text and trace status and specify no launch behavior until a later accepted decision admits the assessments, with the RD-22 smoke test, RD-23 preregistration and RD-24 readiness record unchanged. The without-Jev arm of RD-23 is the launch, its with-Jev arm is suspended, and #59 to #62 are deferred. Paper cards carry the RD-18 unavailable state for every assessment field, and the funded Jev sublimit stays unused.

Evolved schema fields, agent access to past ledgers, agent-written persistent memory, preference as the selection objective, additional trained prediction heads, encoder fine-tuning, masked-LM surprise, trend-to-paper, co-citation, query-growth and rate-growth forecast types are disabled for launch. Their preserved SDD ids specify refusal or no-op behavior; a future accepted amendment is required to activate them. No dormant algorithm or service is required to implement a disabled capability. Future-head admission remains FT-20. Selection and mutation are not in this list: they are seeded and enabled under Seeded evolution below.

ForeSci is optional isolated development evaluation only. It is not a production resolver, evolutionary objective, prediction-head label source or launch prerequisite. Pin its dataset/repository/LLM-judge identities, verify reuse terms, freeze development/evaluation splits and matched reading budgets before a run, and keep reference answers outside retrieval. Report judge agreement and contamination limitations rather than live forecasting skill. Paid benchmark runs require their own funding authorization. No benchmark result automatically changes an agent configuration. Human reader preference remains an outcome to report and, where a preregistration names it, one of the weekly proxies below; it is never the selection objective or training supervision.

<a id="launch-profile-runtime-and-ownership"></a>
### Runtime and ownership

Application runtime: CPython 3.12.12, uv 0.8.22, Ruff 0.13.0 (lint and format), mypy 1.18.1 (strict application typing), pytest 8.4.2. Use Python service interfaces and a FastAPI/Jinja2 server-rendered app with ordinary HTML forms; no SPA, Node toolchain, task broker or agent framework. Use NumPy/SciPy for exact vectors, logistic fitting and calibration. Use standard Transformers inference for the embedding model. Libraries and container bases enter a hash-pinned uv lock/image manifest during the first TDD implementation slice; dependency solving and compatibility are executable acceptance work, not permission for floating production versions. No model-specific remote code executes without a pinned reviewed source artifact.

`bin/check` is the local/CI entrypoint. In this specification-only tree it runs the strict specification checks and checker self-test. Once application source or a project manifest exists, it additionally requires the lockfile and runs locked Ruff check, Ruff format --check, mypy and pytest; missing tools/configuration fail rather than skip application checks. Network issue-reference checks are a separate explicit flag. CI makes no model call and provisions no GPU. Real model/provider qualification is an explicitly invoked, budgeted acceptance job outside default CI.

Use PostgreSQL 17 for transactional records and job state, plus a content-addressed artifact directory on the local application host. Exact patch, container digest and library lock are captured and exercised in the first implementation build. Only the storage service connects to PostgreSQL or mounts artifact data read/write. Other components use declared versioned HTTP/JSON APIs and stream artifacts by hash; no cross-component filesystem access. Separate application containers can share a verified base image but each has its own runtime environment and filesystem. The database is its own container.

Storage owns paper identities, immutable source/artifact manifests, snapshots, ledger, job checkpoints, active-bundle compare-and-swap, submissions, ratings and audit state. Blob commit is write temporary bytes, verify SHA-256, fsync, atomic rename, then commit references in one database transaction. Orphan unreferenced temporary data can be collected after seven days; referenced artifacts cannot be overwritten. Submit uses unique (run_id, submission_id) plus request hash: identical retries return the original response, changed payload under the same key is refused. Ledger sequence allocation and predecessor hash append occur in a serializable transaction. Canonical JSON is UTF-8, NFC strings, sorted keys, no insignificant whitespace, no NaN/infinities; hash the canonical bytes, never implementation repr. Schema version and units are mandatory at every boundary. Model floats are serialized with round-trip precision; ordered arrays retain order.

Derived artifact manifests carry schema_version, artifact_hash, ordered input_hashes, producer_version, config_hash and created_at (UTC). Source capture and availability timestamps are separate fields; sanitization records transport_hash and stored_payload_hash when bytes differ.

Declare service roles: storage, ingest, reader, shared models, shared tools, scorer, orchestrator and rating app; each run is an isolated worker container. Stateless services do not create competing durable stores. All artifacts use explicit actual available_at in addition to source/event time. Jobs move queued -> running -> committed, failed or skipped, with a lease renewed every 30 seconds and expired after 120; only a successful conditional lease owner commits. Retries never duplicate ledger effects. Artifact dependency hashes permit independent acquisition, extraction, encoding and fitting without repeating unchanged work.

<a id="launch-profile-hosts-isolation-recovery-and-spend"></a>
### Hosts, isolation, recovery and spend

The application is one owner-controlled host: the owner's development Mac, kept awake, running the application services in a Linux virtual machine. Container images are pinned to that host's architecture. The floor is the measured demand recorded under #82, #112 and #114 plus a stated margin, and is fixed in a profile amendment before #74; the per-role limits and the batch memory thresholds below are resized in that same amendment. The representation platform is this host's graphics processor in float32 with deterministic algorithms, recorded in the representation manifest; every vector in one representation namespace comes from that platform. The hosted agent inference endpoint owns no corpus, ledger or application authority. The one-application-host scope permits that endpoint and separate owner-controlled backup and anchor destinations. No Kubernetes or distributed database is introduced.

Docker Compose declares local components, private networks, volumes, health checks, seccomp defaults, read-only root filesystems and per-service runtime secrets. Agent workers have no Docker socket or privileged mode. Host-enforced egress permits ingest to the recorded arXiv/OpenAlex/source allowlist and each worker to the one named provider's API host in Pinned model choices below, through an authenticated proxy; no second agent-model host, relay or fallback host is reachable. The Jev entry in the ingest allowlist stays closed while the assessments are held out. Private application calls follow explicit service allowlists. Storage alone reaches the backup/anchor endpoint. Provisioning tools run outside agent containers under the operator's authority. Neither the rating app nor workers can reach arbitrary internet hosts. Local HTTPS binds only to a LAN/private-VPN address; there is no public listener. Two operator-provisioned rater identities, each bound to one rated island, use hashed credentials and secure HttpOnly SameSite=Strict sessions with CSRF checks, 24-hour expiration and no open registration.

Container hard limits, expressed as vCPU / GiB RAM / host graphics devices. Shared models is the one role that declares a graphics device, because the representation platform is the host's; every other role declares none. These values and the memory thresholds below are chosen ceilings inherited from launch-v1 and are resized from measured demand in the same amendment that fixes the floor:

| Role | Limit |
| --- | --- |
| PostgreSQL | 2 / 8 / 0 |
| Storage | 1 / 2 / 0 |
| Ingest | 2 / 4 / 0 |
| Reader/extraction | 2 / 4 / 0 |
| Shared models | 4 / 12 / 1 |
| Shared tools | 1 / 2 / 0 |
| Scorer | 1 / 2 / 0 |
| Orchestrator | 0.5 / 1 / 0 |
| Rating app | 0.5 / 1 / 0 |
| Each of at most two run workers | 1 / 1 / 0 |
| One batch job | 4 / 16 / 0 |

The scheduler runs at most one memory-heavy batch job, pauses it while foreground services exceed 48 GiB resident memory, and resumes from checkpoints below 40 GiB. CPU limits are ceilings, not promised simultaneous reservations. Readiness measures latency, peak memory and full daily completion on the actual host; the floor alone is not a performance guarantee. Health polling is every 30 seconds, with three failed polls marking a service failed; initial model load gets 15 minutes. Service failures retry at most three starts, 10/30/90 seconds apart, then require operator repair. A failed optional provider does not prevent capture or core paper-card reading.

Prospective ledger heads are anchored every 15 minutes or 100 records, whichever comes first, through storage to an append-only receiver on a separate owner-controlled host: the smallest virtual private server that runs the receiver. Receiver validates monotonically increasing sequence and retains prior receipts; the application key cannot delete or replace anchors. An anchor backlog beyond 30 minutes blocks new prospective seals and reports degraded integrity; already captured source data remains available. Nightly encrypted backups go to object storage and hold a PostgreSQL-consistent snapshot plus all referenced artifacts and anchor receipts. Keep seven daily and four weekly versions. Target RPO 24 hours, RTO four hours; a monthly isolated restore proves hash-chain, snapshot and artifact integrity. Actual destination address/key and storage capacity are deployment bindings required at activation, not embedded credentials or an invented available machine.

Default `paid_execution_enabled=false`, active monetary authorization is zero. Maximum ceilings after explicit funding authorization: combined paid spend USD 8 per UTC day and USD 200 per UTC month, Jev sublimit USD 2/day retained but unused while the assessments are held out, scholarly API sublimit USD 2/day. Reserve worst-case request charges before execution against both counters; provider pricing/quote must be dated and available. If the quote, cost bound or authorization is missing, do not call. Ambiguous billed attempts consume their reserved amount until reconciled. Nothing in this design provisions, restarts or purchases a resource.

Agent inference posture is hosted per-token from one named provider, billed by measured input, cached-input and output tokens. There is no rented capacity, no relay or second provider, and no automatic fallback to another endpoint or model. A provider outage is an unavailable endpoint and a void run, never a substitution. The monthly ceiling bounds the population size FT-14 may admit, and the measured per-run cost is the term FT-12 reports as skill per dollar. A deployment must demonstrate daily workload completion within both deadlines and the authorized price cap; failure blocks study activation and produces an evidence-based sizing finding rather than silently spending more.

<a id="launch-profile-pinned-model-choices-and-representation"></a>
### Pinned model choices and representation

Embedding baseline: `nomic-ai/modernbert-embed-base`, revision `d556a88e332558790b210f7bdbe87da2fa94a8d8`, Apache-2.0 as declared by its publisher. It is a ModernBERT-base encoder trained for embeddings and used frozen; prediction-head mathematics is unchanged. Use d=768 without Matryoshka truncation, attention-masked mean pooling over all input tokens including the task prefix, evaluation mode, float32 inference on the host's graphics processor with deterministic algorithms, and unit-L2 output. The representation manifest records the compute platform beside the revision, dtype, pooling and prefixes; a vector computed on another platform belongs to another namespace and is never mixed with these. Thus combined prediction-head input is [1536], fitting X [N,1536], and labels/masks/probabilities [N,3]. The 8192-token model limit includes specials and the prefix. Overview is `search_document: ` + original title + newline + abstract; passage documents use the same `search_document: ` prefix. Queries use exactly `search_query: {query}`. Token budgets include the prefix. No silent truncation. Tokenizer/weight file hashes and package/image manifests are verified before serving; this repository revision is selected, not demonstrated qualified.

Agent: `glm-5.3-flash`, served per-token by Z.ai's first-party API as the one named provider, publisher-declared MIT weights, natively multimodal with tool calling and structured output. The system hosts no agent weights. The provider's returned model identity and revision are recorded on every run (RD-19, SR-15); a mutable alias is recorded as such and never given a fabricated immutable hash. A failed load, tool contract or image contract is a failed qualification, not an automatic version, model or provider swap. Use the provider's OpenAI-compatible chat-completions transport with canonical ordered messages, native tool calls, image blocks and validated JSON arguments; its actual wire route and authentication are verified before activation, not assumed here. Temperature 0.7, top_p 0.9, one sample per question, repetition penalty 1.0, request seed derived from the run id; preserve actual returned sampling metadata, including the input, cached-input and output token counts the run's cost is computed from. Server constrained decoding is used when qualified, while tool validation remains authoritative. No claim of bitwise deterministic model generation is made.

Before activation, execute 100 real five-tool/schema conversations with at least 99 valid complete submissions and no successful forbidden tool; 50 preserved scientific figure/table questions with at least 80% independently agreed correct answers; and 100 evidence-location questions balanced over early/middle/late positions in 16k/32k/64k contexts with at least 90% correct cited source ids at each tested length. These are operating acceptance floors. Use separate held-out cases after fixes. Measure load time, peak memory, concurrent requests, full daily duration and loss/retry behavior. No provider benchmark substitutes for these tests.

The selected embedding model is a baseline candidate, not a claim that modernbert-embed-base beats SciEmbed. Require artifact/license/input tests and the retrieval evaluation below before study use. Replacement under #36 uses a new representation namespace, rebuilds every affected historical vector and prediction head, requalifies retrieval and prediction heads, and atomically switches only future snapshots. Never mix vector spaces. Contemporary embeddings can fit reconstructed historical labels with disclosed pretraining limitations; no unsupported exclusion based on a guessed training cutoff, and no retrospective foresight claim. Known cutoff metadata is recorded; unknown stays unknown.

<a id="launch-profile-agent-batches-schemas-and-bounded-reading"></a>
### Agent batches, schemas and bounded reading

Ingest refreshes arXiv at 00:00 UTC daily, creates one daily parent batch after completion and records per-paper publication/arrival lateness. Route each eligible family to the island of its primary category, cs for cs.AI and cs.LG, quant-ph and q-bio. Within each island sort families by first_public_at then canonical id and partition into disjoint shards of at most 20 papers. Every configuration of an island receives every shard of that island with the same questions and snapshot; no shard mixes islands. A slot is (daily_batch_id, shard_id, configuration_id, attempt=0). The population runs at most two configurations concurrently; queue by earliest paper seal deadline then slot id. Every scheduled slot has a completion, void or missed-deadline record. Sharding changes engineering task size, not paper inclusion, sampling weights or the 24-hour first-public forecast deadline. Prediction-head/assessment acquisition must complete before the snapshot; later enrichment produces future paper-card versions only.

The first request contains the shard's paper/question ids, budgets and snapshot description, not preloaded paper cards. The agent chooses its reads through the existing five tools. The seeded population is three islands of four configurations each, twelve in all: in every island the four launch emphases, which are evidence-first reading, methods/assumptions scrutiny, comparison to earlier related work and limitations/alternative-explanation scrutiny, with the evidence-first configuration marked as the island's founder (AG-38); owner-written variants are admitted under AG-03 before the first cycle into a named island. All use identical tools, budgets, model, rubric and target definitions. Each prompt begins with the same instruction to treat source content as evidence rather than instructions, assess what the paper supports, separate reading preference from citation forecasts, and acknowledge missing evidence. Configuration differences are only the named reading emphasis. Prompts are versioned immutable artifacts frozen before evaluation; wording changes invalidate the configuration identity. No claim that any emphasis is optimal is assumed.

Per run: 16 model calls, 40 total tool calls including rejected calls, 8 deep reads, 12 images, 65536 model tokens maximum context, 16384 total generated tokens and 20 minutes wall time. Per request reserve up to 8192 output tokens inside the context limit; maximum 8192 generated tokens for one response. Resent input counts toward measured usage and the spend reservation; model-token counts include images using the pinned processor. No implicit compression, hidden summarization or dropped conversation turns. A response exceeding remaining allowance is not executed; expiration before an accepted submit is void. Provider request timeout 120 seconds. Retry only explicitly rejected, non-executed 429/503 requests once after 5 seconds within budgets; unknown completion/eviction stops the run as void, without selecting a favorable retry. Idempotent submit retries are allowed from the recorded identical request. A stopped run cannot resume after its seal deadline.

Each turn's protected note is a concise action/evidence summary, at most 1000 UTF-8 characters, not a demand for private chain-of-thought. Intent enum: scan, compare, inspect, forecast, nominate, submit, stop. Forecast rationale maximum 2000 characters, with at most five source ids. The launch schema extension is empty; reject any extra field. Reserved future extension types are string<=1000 chars, finite number, boolean, enum<=16 choices and array<=8 primitive values, maximum eight fields and depth two, labels<=80 chars and descriptions<=240 chars; none can activate without the deferred schema-evolution decision. Scan/read/probability policies are UTF-8 text <=4000 characters each, overall system prompt <=16000 characters, tools a subset of the fixed five, one sample per question. The external loop validates one sample rather than fabricating independent samples from prose.

Strict tool envelopes use schema_version, run_id, tool_call_id and snapshot_id. All fields are required unless a default is specified; unknown fields, invalid UTF-8, nonfinite numbers and schema coercions are rejected. Read responses identify status ok/unavailable/error, data, source artifact ids and remaining budgets. Tool errors consume a call but have no side effects. The TDD binds these contracts to concrete schemas; it does not choose new behavior.

- `query_cards`: existing overview/passages query contract in Appendix C: Retrieval protocol plus mutually exclusive `paper_ids` lookup (1–5 distinct snapshot ids). Lookup returns paper cards by requested order; search uses exact cosine and at most five results. No query is needed for id lookup. A serialized base paper card is bounded to 3000 embedding tokens, retaining identity, full title/abstract, signal availability and provenance first; omit optional neighbor details before core text. If core text itself exceeds the cap, return an explicit overview reference and extract span rather than silently truncate.
- `neighbors`: one paper id, limit 1–5 default 5; return the RD-06 earlier overview neighbors with source/similarity and pre-snapshot outcomes only.
- `graph`: one paper id, direction references/citations default references, limit 1–20 default 20; one hop, canonical id order, no recursive traversal. Return snapshot edges, source and missingness, not fresh remote data.
- `deep_read`: paper id and either a section id, 1–2 page numbers or an immutable next_span continuation returned for that same snapshot/paper; response at most 6000 model text tokens and two images. Text is paginated by immutable span with next_span locator, explicitly marked partial; no chunk is represented as the whole paper. Images are rendered at 150 dpi, downscaled to longest edge <=1600 pixels, with page identity; rendering is not OCR. Requested over-budget content is refused or returned as explicit bounded spans, never silently included beyond the limit.
- `submit`: exactly one answer for each issued shard question, each with question_id, finite probability [0,1], bounded rationale and evidence ids; plus 0–7 ordered unique nominations from the shard, each paper_id and bounded rationale, and submission_id. Evidence ids must exist in that run's snapshot and have been retrieved. No target/version can be substituted by the agent.

Each configuration's daily nomination list is the deterministic round-robin merge of its shard nomination lists in shard order, skipping repeats. EN-41 then merges the configuration lists of each island and takes seven unique population papers per island. Add up to three random controls and up to two service picks from that island's papers. One digest per island per day: the cs digest goes to the cs rater, the quant-ph digest to the quant-ph rater, and the q-bio digest to no one. Shuffle all digest entries with a hash-derived recorded seed after selection so origin is not revealed by position; detail-view labels are fresh per paper. A recommendation carries its available forecast links but is not an extra forecast. Owner retrospectives filter by date, paper, configuration and resolved outcome, read-only, with no cross-run agent access.

Quarantine a run immediately on a verified snapshot/credential/write-boundary violation or an attempted protected-state write; schema mistakes alone are recorded errors within normal budgets. Three integrity quarantines from one immutable configuration within seven days quarantine that configuration. Release requires an operator-recorded disposition and a new tested configuration version. Purge means revoke active execution authority, never delete audit history; use it only on a confirmed repeated prohibited write after a prior quarantine. Performance-based retirement is FT-14's alone and never purges audit history.

<a id="launch-profile-seeded-evolution-and-population-size"></a>
### Seeded evolution and population size

The seeded population runs unchanged for its first two weekly cycles, so the first selection comparison has a control (FT-13, FT-14, AG-18). From the third weekly cycle the select stage ranks the genomes of each island separately by the forecast skill FT-12 reports over matched resolved questions, or, while an island has fewer resolved questions than the minimum resolved-claim count, by that island's registered proxy: preference credit (IN-43) for the cs and quant-ph islands, and agreement with the calibrated prediction heads for the q-bio island and for a rated island in a week its rater recorded nothing. Measured skill per dollar, the same skill divided by the measured model cost of the runs in its support, breaks ties and sets how many genomes the month's remaining authorized spend admits. Cost constrains population size; it is never the objective, and a genome that reads nothing cannot win on it (EN-16).

The floor is four genomes per island and each island's ceiling is what its share of the USD 200 monthly cap covers at the measured per-run cost, shares in proportion to each island's paper count in the month so far. One founder per island is never replaced (AG-38). A genome below the minimum resolved-claim count is neither drawn as a parent nor replaced; that count is not yet set and rests on #130. A mutation may take its parent or its changed field from another island as a migration (AG-37), never into the q-bio island. A mutation proposal is one field-level change to one parent (AG-20); a child equal to an active or archived genome is refused (AG-21); the diversity archive keeps the best-scoring genome of each retired lineage and runs none of them (FT-15). Schema extensions stay empty throughout (AG-34, AG-35).

One canonical preregistration under SR-18 precedes the first select stage that changes the population. It names the primary measure, the pass and kill thresholds, and the proxy each island uses while one-year outcomes do not yet exist: preference credit for the rated islands and agreement with the calibrated prediction heads for the control island, with lead time over discovery services reported beside them. It also registers the three island questions: rated against control skill trajectories, migrated traits against local mutations in the receiving island, and drift from the seeds per island. Each proxy is reported with its own support and its own accuracy; a named proxy is a way of measuring skill before outcomes mature, not a second objective, and forecast skill on resolved outcomes replaces the proxies as they mature. The registration also records the null control under #32. Selection without that registration does not run, and a proxy added after results is exploratory and needs fresh confirmation.

<a id="launch-profile-retrieval-extraction-and-graph-values"></a>
### Retrieval, extraction and graph values

Use original overview vectors for paper-to-paper neighbors and distances; use query/document vectors for passage search. Exact float64 cosine accumulation over float32 stored vectors, descending similarity, ties by canonical family id. Earlier means strictly earlier verified first-public time and snapshot-visible representation; exclude the target family and uncertain ordering. Five neighbors, fewer when unavailable. Embedding distance is mean(1-cosine) to those neighbors, with neighbor count; zero neighbors is unavailable. It is a descriptive distance, not a learned anomaly probability or novelty verdict. Earlier-neighbor baseline is (sum known binary outcomes + 1)/(known neighbors + 2), per identical target version; zero known neighbors is unavailable.

Paper-card graph values are unique incoming and outgoing family counts plus known-reference match fraction, each with graph source and capture time. Reference-centroid distance uses available same-representation original overview vectors for outgoing references, normalizes their mean then uses 1-cosine; a zero/missing centroid is unavailable. Count missing reference vectors separately. Do not add centrality or graph neural networks.

Text extraction order: licensed original arXiv LaTeX source using a non-executing parser, then original PDF text layer. Never compile untrusted TeX or execute attachments. PDF pages supply images when source figures/tables are unavailable. If neither is readable, retain title/abstract and explicit full-text unavailable; prediction-head features remain unavailable under the existing full-original-text rule. Original-only feature provenance is separate from latest snapshot-readable version. Coverage states identify latex, pdf_text, partial or unavailable and omitted blocks. Jev input uses the same saved text but includes the coverage state and its own input limit; no generated summary fills missing text. No OCR or web search fallback.

Citation graph merges exact parsed source identifiers with snapshot-captured OpenAlex relationships. Deduplicate family ids and preserve per-edge sources; unresolved bibliography strings are retained as unmatched diagnostics, never guessed title matches. Semantic Scholar is not required for launch graph or labels. The explicit label observation protocol still owns outcome counts, not the live paper-card graph. Page/figure/text/tool content all count as untrusted data; content in images cannot authorize tools or change system instructions.

Discovery-service baseline: one source, Hugging Face Daily Papers, captured by ingest from its permitted published API with actual capture time and canonical arXiv ids, maximum 50 picks/day. Access/retention validation precedes enabling it. No authentication bypass or HTML scraping fallback. Missing service history is unavailable and supplies no retrospective baseline; it does not block the research digest. Service provenance stays hidden from raters. Optional stars, forks, downloads and discussion counters are disabled at launch. The popularity baseline uses snapshot-valid prior author citation counts only when available for every author; otherwise unavailable. Fit one logistic baseline per target on those logged historical covariates, never reconstruct them from current counts. Baseline logistic fitting and calibration use the same fixed family, regularization search and temporal rules as Appendix B: Learning protocol. The plain paper-card baseline uses only qualified prediction-head logits for that target and original overview nearest-neighbor distance, with separate availability masks and the same temporal partitions; exclude Jev and post-snapshot counts. A baseline training row requires a previously persisted prediction-head prediction from a bundle fitted without that family and with outcomes available before that prediction; in-sample logits cannot become baseline training features. No historical covariate snapshots means no fitted comparison, not invented values.

<a id="launch-profile-evaluation-leakage-and-provider-qualification"></a>
### Evaluation, leakage and provider qualification

Every relied-on comparison, including offline model selection and external ForeSci work, receives a canonical hashed preregistration before its first execution: hypothesis, population/splits, sources, primary metric, direction, minimum effect, sample size, exclusions, failure handling and stop rule. Runtime records go to the ledger; pre-runtime studies use a dated signed/hashed finding subsequently imported with its original timestamp. A changed analysis after results is labeled exploratory and needs fresh confirmation. Default paired comparisons use 10000 bootstrap resamples of publication weeks, families inseparable, seed 20260920, 95% percentile intervals; the learning protocol's three-target correction overrides this default. An interval containing zero is inconclusive, not equivalence. Repeated configuration inspection never produces a new untouched test.

Each snapshot seal asserts that every artifact available_at <= seal, all reference ids resolve within the snapshot, sources/models/target versions are compatible, and no held-out answer/label artifact is exposed through tools. Future publication dates alone are not availability evidence. Once a week replay the most recent completed batch and one uniformly hash-selected older batch using preserved request/response bytes, frozen clocks and manifests. Compare exact tool data, ledger effects and deterministic scores, excluding actual rerun timestamps/transport ids. Replay consumes recorded model replies and does not call the stochastic model; live model re-generation is a separate nondeterminism measurement.

Before each release study, run 100 independent within-publication-month label permutations through each prediction-head pipeline separately, with RNG streams separated across fit/development/calibration/evaluation and real labels inaccessible. Report null-loss distributions and require the per-head number of apparent significant improvements to be compatible with a Binomial(100,0.05) exact upper-tail test at 0.01/3 across the three heads. Failure blocks the study pending leakage investigation; no demand that every chance result equal zero. These runs use a separate artifact/ledger namespace. Seed, sampled families and output hashes make controls reproducible.

Shared retrieval qualification: 100 original papers selected by hash from the latest 20 complete publication weeks, five per week with shortages explicit, allocated across the four categories in proportion to each category's family count in those weeks with at least one per category; five source-anchored retrieval questions per paper, authored without candidate results. Use 20 papers for development and lock 80 (400 questions) for evaluation. Preserve licensed source spans and two independently verified evidence judgments; this is a bounded retrieval test, not head-label creation. Overview retrieval success is whether top-five families include the cited relevant family; passage success additionally requires a returned source span supporting the question. Require >=0.80 top-five family recall, >=0.60 supported-passage recall, 100% exact span reconstruction and at least 0.05 absolute supported-evidence gain over overview-only under equal reading budget, with paired 95% lower bound above zero. Failure leaves passage study activation unqualified; engineering can still exercise the index. SciEmbed comparison is optional before replacing the selected modernbert-embed-base baseline, not a second mandatory model implementation. Neighbor-quality monitoring uses the same question set plus five seeded random earlier controls per paper and reports relevance at five.

The three paragraphs that follow are held out of the launch with the assessments themselves (#123). They are the values that take effect when a later accepted decision admits Jev, and nothing in them is executed before it.

Jev operating limits: 30-second request timeout, one retry after 2 seconds only on explicit 429/503 rejection, concurrency two, at most 1000 request attempts/day, at most 128 KiB UTF-8 state text and the lower verified provider token/byte limit. Verify request/schema overhead fits too. An ambiguous timeout is unavailable and is not automatically retried. One request includes all eight Choice questions; reuse an immutable input/rubric/provider-config cache key. Never truncate to fit. Actual API endpoint, credentials, provider identity and retention permission must be verified before activation. A mutable provider alias is recorded explicitly and smoke-tested again on declared changes; it is not assigned a fictitious immutable hash.

Jev smoke test: 20 target-corpus papers, the first hash-ranked paper from each of the latest 20 complete publication weeks, with shortages visible and no replacement, allocated across the four categories in proportion to their family counts with at least one per category. Run each through the full eight-field request under the operating limits above. Every field must return a schema-valid result for at least 18 of the 20 papers. Record category distributions, unavailable reasons, latency and cost. The owner reads the stored answers and records the review before activation. No reference labels, annotator agreement, Brier comparison or recurring human recheck is required. Rerun the smoke test on any provider identity or rubric change. Paper cards state that Jev assessments are unqualified: not measured against human labels.

Prospective Jev benefit comparison: fixed evidence-first configuration, one run with and one without Jev for the same shard/questions, randomized execution order and identical snapshot/model/budgets. Include failed delivery in assigned-treatment analysis; report paired-completion metrics separately. Register before launch, collect the first 2000 eligible paper families across at least 26 publication weeks, then wait for the 455-day maturity and resolve under the same source protocol. Primary endpoint is citation_reach_365d Brier improvement; require at least 0.01 absolute point improvement and paired 95% lower bound above zero on >=70% of registered families with paired forecasts/resolved labels. Otherwise report inconclusive or failed criterion as appropriate. Treat missingness and paired-completion conditioning as limitations, never causal proof on excluded cases. The other two outcomes and reader preference are secondary; do not pick the best after the fact. Registration and content qualification permit launch while future outcomes are immature. No prospective result is required tonight or manufactured from historical labels.

Accuracy registry: acquisition identity and date parsing (preserved known-identity fixtures plus 50 monthly source audits), extraction/figure locator fidelity (50 monthly papers), resolver boundary/unknown logic (every build), retrieval (above plus quarterly refresh), each prediction head (every promotion and weekly monitoring), each Jev field (above), agent forecast calibration (weekly when outcomes exist), and ledger/tool isolation (every build and weekly replay). Each report preserves denominator, unknowns, version and actual execution time. No output-producing component escapes by calling itself plumbing.

<a id="launch-profile-diagnostics-alerts-and-data-handling"></a>
### Diagnostics, alerts and data handling

Forecast clustering: per configuration/target over the latest 200 resolved or unresolved sealed probabilities, flag when >=90% lie in one fixed-width 0.1 bin; do not call this miscalibration without outcomes. Report ten-bin reliability on resolved outcomes weekly. Evidence spot check: five uniformly hash-sampled submitted forecasts per week, all if fewer, using seed derived from the ISO week and profile; unreviewed examples remain unreviewed. Source integrity audit: 50 captured records weekly or all if fewer, verify response/artifact hashes and snapshot eligibility. Resolver-defect audits stay separate from human liking and rationale support.

Timing: report first-public-to-ingest, ingest-to-card, queue wait, first-model-call-to-submit, and batch-to-digest wall durations with UTC timestamps and count/p50/p95; never subtract a source date from a monotonic process clock. Topic spread: Shannon entropy over known primary subfield ids of nominated papers, plus number of subfields, unknown fraction and same-day eligible-pool entropy. This is diversity description, not novelty or fitness. No source subfield labels are sent as future target answers.

Operational alerts appear only in the private app: any integrity/hash/forbidden-access failure immediately; service failure after three health misses; disk free <20%; backup >26 hours old; anchor >30 minutes; spending >=80% of either cap; >10% void/missed slots over the latest 20 scheduled slots; and any field failing qualification or clustering rule. Deduplicate by condition/component/version until resolved. An alert is read only after an authenticated acknowledgment event, never merely because a page loaded. No email/chat messages are sent automatically. Warnings do not change forecasts or secretly remove unfavorable runs.

Store public scholarly author names and identifiers only as source bibliographic metadata. Do not collect contact information, personal profiles or unrelated social account details. Raters use pseudonymous local ids; credential hashes and audit attribution are access-control data, not model inputs. Retain immutable licensed research artifacts, model/configuration identities, sealed forecasts and ratings for the study duration plus two years; ordinary operational logs 30 days, rejected-payload diagnostics seven days with secrets stripped. Provider response preservation is limited to permitted sanitized research payloads; credentials/auth headers are removed before persistence. No assertion of full raw-byte preservation overrides licensing or privacy. Required deletion under source terms replaces content with a tombstone/hash and marks dependent replay unqualified, preserving permitted audit metadata instead of silently changing history. Restrict access to the two raters and operator roles; encrypted disk/backups and private network access are activation requirements.

<a id="launch-profile-activation-gates"></a>
### Activation gates

Activation requires deployed immutable manifests and compatible runtime, the actual host/backup bindings, funded caps, source licenses/access, successful source/representation/three-head/agent qualification, and a restored replayable ledger. The agent qualification battery above is the gate on the hosted endpoint, and authorized spend stays zero until it passes. The Jev smoke test is not a launch gate while the assessments are held out (#123); it becomes one again when a later accepted decision admits them. A failed gate blocks only its declared mode: acquisition engineering can begin before trained study readiness, but a full promised feature cannot be relabeled ready with missing components. Numerical limits can change only through a versioned profile with disclosed consequences and fresh affected qualification. No model test, source coverage result, listed provider price or provider right is presumed verified; public metadata and documentation establish candidates and interface descriptions, not successful local execution. Optional disabled-source findings cannot block launch. The sources behind the pinned choices are listed in [pinned model and provider sources](../evidence/models/pinned-sources.md).

<a id="launch-profile-source-qualification-and-protocol-validation-details"></a>
### Source qualification and protocol validation details

The shared 100-paper source audit is five hash-selected papers from each of the latest 20 complete publication weeks, seed 20260920, allocated across the four categories in proportion to their family counts with at least one per category. Preserve all failures and record exact-id bibliography precision over up to the first five references per paper, source extraction buckets and unmatched fraction; require zero false exact-identifier merges before activation, with no claimed universal match-recall floor. Daily volume is measured per category over the latest 60 UTC days with cross-list family deduplication; throughput qualification replays the busiest observed day. These samples are source integrity tests, not semantic prediction-head labels.

Ingest uses request timeout 30 seconds, at most three attempts with waits 1 and 4 seconds on explicit transient failure, respecting Retry-After up to the remaining job deadline. arXiv requests are serialized with at least three seconds between starts; OpenAlex starts at most one request/second and at most 5000/day, or lower verified provider limits. An unavailable or unlicensed source stays unavailable; no alternate scraping route appears. Raw response storage follows the privacy/retention exception, recording transport hash separately from sanitized stored payload hash when different.

Jev response validation checks exactly the eight rubric keys, known category values, one finite nonnegative probability per category, total probability within 0.000001 of one, and confidence finite in [0,1] when returned by the verified interface. Invalid distributions remain unavailable, not renormalized guesses. Before qualification freeze at least one positive and one boundary example per category drawn only from the development set; ambiguity stays visible to both reviewers. Confidence never overrides the evidence categories.

The daily pipeline accepts at most 1000 newly ingested paper families per processing day for immediate model scheduling, in publication/id order; any excess is preserved as queued acquisition and explicitly missed prospective deadlines where applicable. No filtering by predicted success is permitted. Production capacity qualification must show the measured busiest day fits the cap and budget, otherwise launch fails with a sizing finding. This is a protective workload ceiling, not a claim of measured demand.

Execution modes: collection starts storage and ingest with source permission checks and no paid model calls; engineering adds local reader/model/tool services and deterministic replay with explicitly unqualified outputs; study adds qualified live agents, Jev, digest and ratings only after every full-feature activation gate. A mode is recorded in every run and cannot claim the readiness of a stronger mode. Components required by the selected mode must all be healthy before its cycle starts.

<a id="launch-profile-final-launch-consistency-rules"></a>
### Final launch consistency rules

Only issued questions can receive agent forecasts; volunteered extra forecasts and runtime type admission are disabled. Nominations remain independent recommendations. Every question receives one value from one sample. Schema extensions remain empty, including otherwise well-typed described fields. Operator replacement of a configuration produces a new immutable identity and affected qualification, never a mutation of existing runs.

Digest construction freezes one ledger watermark when all scheduled daily slots are terminal or expired; it uses accepted nominations, forecast links and the control/service captures at that watermark. Human forecast questions have a separate private view from batch issue until their deadlines, so a late digest does not invent an answering window. Daily automatic source coverage links the latest dated audit or not-yet-audited state; human auditing follows the existing bounded schedules, not a new daily annotation task.

IN-29 measures operational latencies, with linear-interpolated p50/p95, hours for publication-to-ingest and seconds for other stages. It does not assert accuracy at predicting event timestamps. Pre-runtime comparison registration and results retain their evidenced original times and later ledger-import time; activation verifies registration-before-execution and import-before-reliance. Initial host preflight is an operator file captured before startup and imported by storage afterward.

Submission acceptance is atomic: any invalid shape, answer, evidence, registry binding or nomination rejects the whole attempt, preserving an audit event but no partial forecasts. Corrected attempts remain bounded by the original budget/deadline. Question identity supplies the fixed horizon; no agent-authored horizon override exists. Baselines and humans bind evidence through their authenticated input/view receipts rather than a nonexistent agent tool trace.

Engineering shards with no issued forecast questions expire 24 hours after batch sealing. Population and independent with/without-Jev comparison slots share global concurrency and spending limits; the comparison adds two slots per eligible shard beside the population slots and cannot contribute digest nominations. No comparison slot is created while the assessments are held out (#123). Deep-read continuation can only resume a returned immutable span within the same snapshot and paper.

Baseline numeric features are fixed: popularity uses log1p of the sum of known prior citation counts over unique author ids and is unavailable if any author count is missing. The plain paper-card baseline uses [target raw logit, overview neighbor distance, head-present mask, distance-present mask]; missing numeric values use zero placeholders with false masks, and both substantive features missing means no forecast. The stored raw logit is the target prediction head's linear score before calibration and sigmoid, avoiding infinite logit(0/1) inversion; its prediction manifest preserves it internally. It never goes to the paper card an agent reads. Baseline rows obey the existing prior-prediction/no-in-sample and temporal-fitting rules.

Score-provenance and captured-source audit samples are separate. At ISO-week close select the first 50 eligible ids ordered by SHA-256 of profile id, week, sample kind and record id, or all if fewer. Store the eligible watermark, selected ids and every failure before checking; never replace a broken sample. Empty score support does not block source audits. Probability concentration requires 200 observations; fewer reports insufficient support. Rationale-support audits record supported/unsupported/unassessable, use assessable cases as the rate denominator and report unassessable and unchecked counts separately.

<a id="learning-protocol"></a>
## Appendix B: Learning protocol

<a id="learning-protocol-historical-learning-protocol"></a>

Version: automatic-citations-v1. Decision: #64; decision record 0007 supersedes the semantic-label launch contract in 0005. Required by SDD EN-12, EN-13 and FT-18 to FT-25. This protocol defines three automatically labeled prediction targets. No prediction head requires human semantic annotation or downstream full text. Original target-paper full text is still required for the accepted features under #68. Numerical thresholds and gates are fixed launch operating policy, not empirically optimal values or guarantees of sufficient data.

<a id="learning-protocol-target-registry"></a>
### Target registry

Registry order is fixed as below. Labels are independent booleans with per-target unknown states. These are project-specific operational bibliometric indicators, not standard measures of scientific quality, usefulness, novelty, correctness or substantive research use.

| Target id | Display question | Exact true predicate |
| --- | --- | --- |
| citation_reach_365d | Will at least five indexed works cite this paper in its first year? | At least 5 distinct eligible citing paper families in (t0, t0 + 365 days] |
| late_citation_activity_365d | Will indexed citations continue in both final parts of the first year? | At least 1 eligible citing family in (t0 + 180 days, t0 + 270 days] AND at least 1 in (t0 + 270 days, t0 + 365 days] |
| cross_subfield_reach_365d | Will it receive indexed citations from at least two other research subfields in its first year? | At least 2 distinct known primary subfield ids, different from the target's primary subfield, among eligible citing families in (t0, t0 + 365 days] |

A family counts once in each target's evidence, never twice through preprint/journal copies. Its single provider-record date determines its window; it cannot satisfy both late windows. Self-citations are included; these targets do not assert author or institutional independence. Bibliometric reach, temporal persistence and breadth are different but correlated: report pairwise label association and predicted-probability correlation. Late activity is not growth or evidence of delayed recognition. Cross-subfield reach is classified citation breadth, not proof that another discipline used the result. All three can be true or false together. Do not sum or average their probabilities into a paper-quality score.

Thresholds 5, 1-per-window and 2-subfields are fixed before acquisition; no quantile estimation or test-set threshold tuning occurs. Changing a threshold, window, source or taxonomy policy creates a new target definition and separate qualification. The predicates are the same for every category; calibration is per primary category and covers the four corpus categories only, and calibrated generalization beyond them requires representative domain evaluation. No GitHub, repository or social signal is a label.

<a id="learning-protocol-time-and-observation-semantics"></a>
### Time and observation semantics

The target's earliest verified public version supplies t0, independent of its eventual journal date. Use UTC instants and elapsed days of 86400 seconds. Citing-work time is the preserved OpenAlex publication_date represented as the full UTC day interval [00:00, next 00:00). It is a provider date for a work linked in the captured graph, not a verified date on which the citation was first written. Do not claim passage-level historical citation timing from this metadata. A date interval wholly within a target window is definitely in; wholly outside is out; a boundary-straddling, missing or conflicting interval is uncertain. Resolver examples cover t0, day 180, day 270 and day 365.

All three outcomes mature at t0 + 365 days + 90 days of indexing allowance. Do not admit early positives before maturity. Prospective ingest captures raw citation records at maturity: schedule at maturity; actual capture starts no earlier than maturity and completes no later than maturity plus 24 hours. Capture outside this interval is unavailable for that prospective protocol; do not backdate a later fetch. Freeze the actual capture start/end and completion watermark. Labels describe the index observed then, including its omissions and metadata errors. Corrections preserve the original capture result and append a new label version with lineage.

Historical collection today is marked historical_reconstructed with its actual capture times and acquisition lag. Filtering current records by old publication dates does not recreate the graph or topic classifications available at an old deadline. Such labels can train deployment prediction heads and a disclosed retrospective benchmark; they cannot count as historical agent foresight or prospective fitness. Original paper inputs never include this later metadata. Current lifetime totals, calendar-year count bins, current FWCI and provider percentiles are not replacements for the defined windows.

For prospective forecast credit, seal within 24 hours of t0 and before any target predicate was already satisfied. Determine preexisting-event eligibility using definite and possible event intervals: a predicate definitely satisfied before sealing excludes the question; ambiguity preventing proof of pre-event sealing excludes it from prospective skill. This check is per target. Historical papers remain readable and can receive explicitly retrospective estimates, but cannot receive new launch-time forecast credit.

<a id="learning-protocol-one-acquisition-pipeline-and-immutable-records"></a>
### One acquisition pipeline and immutable records

1. Enumerate eligible arXiv paper families without using citation outcomes, freeze selection, and retrieve licensed original title, abstract and full text. Preserve failed acquisitions in denominators. No OCR or new domain rollout is added.
2. Match target families to OpenAlex through exact persistent identifiers and explicit version relations. Query incoming citations for every matched family record, fully paginate and preserve raw responses, query parameters, adapter version, response timestamps and errors. Disable fuzzy title-only merges. Unresolved target matching makes all labels unknown.
3. Reconcile citing records through identical provider ids, DOI/arXiv identifiers and explicit version relations; ambiguous merges stay unresolved. Choose the representative record by published version when explicitly linked, otherwise lowest provider id; record the rule and all aliases. Preserve its publication_date and primary_topic.subfield.id. Conflicting dates/subfields within a linked family are uncertain for affected predicates rather than silently picking favorable values. Known target-family self-links are excluded. Self-author citations from other families remain eligible.
4. Freeze the provider taxonomy response/id mapping and per-work classification metadata with each capture. Unknown target primary subfield makes only the breadth label unknown. The other two targets do not depend on taxonomy. No Jev classification or human substitution fills missing fields. Provider topic assignments are automated proxy metadata and can change; they are not expert reference labels.
5. Persist immutable source, extraction, citation-family, observation, label, vector and bundle artifacts with schema version, content hash, configuration identity and actual creation time. Licenses and retention rules are metadata; credential headers are never retained. Source access and complete query semantics must be verified by the acquisition pilot before scale-up.

Only OpenAlex defines these launch labels. Other scholarly indexes can remain diagnostic or aid original-document identity, but are not silently unioned into outcome counts. No downstream full-text acquisition, reviewer assignment, adjudication interface or Jev evidence-labeling job is a launch dependency.

| Record | Required fields |
| --- | --- |
| Paper version | paper/family/version ids, original source hash, first-public time and uncertainty, source/capture time, license and extraction coverage |
| Citing family | canonical id, aliases and reconciliation evidence, target linkage, provider date interval, primary subfield or uncertainty, raw response hashes |
| Observation | target family, source/protocol/taxonomy identities, capture start/end, pagination completion, candidate family ids, uncertainty flags, historical/prospective kind |
| Label | target id/version, true/false/unknown, reason, sufficient witness ids or completion proof, lower/upper counts, observation hash, maturity and available_at |
| Embedding | original version, model/tokenizer/package revisions, extraction/chunk/feature hashes, d, dtype, normalization, computed_at and vector hashes |
| Corpus release | full selected population and exclusions, seed, family grouping, labels/masks, split ids, source watermarks, coverage report, artifact hashes |
| Model bundle | ordered target definitions, representation id, numeric coefficients and calibrators, fitting cutoff, corpus/split hashes, per-target qualification/availability |

<a id="learning-protocol-automatic-resolution-and-corrections"></a>
### Automatic resolution and corrections

A pure resolver reads only mature preserved observations and the frozen target definition. It uses conservative lower and upper bounds over uncertain dates, classification and family identity. Definite eligible families contribute to lower counts. Possibly eligible records contribute only to upper counts, allowing each unresolved record at most one family and one new subfield. For unresolved identity, lower bounds collapse every possibly identical cluster, upper bounds keep distinct possibilities. Incomplete pagination gives an unbounded upper count. A missing target subfield makes breadth unknown regardless of citing coverage.

Resolve reach true when its lower count is at least 5; false only when a completed capture has upper count below 5; otherwise unknown. Resolve late activity true when both window lower counts are at least 1; false only when a completed capture has upper count zero in either window; otherwise unknown. Resolve breadth true when at least two definitely eligible distinct non-target subfields are witnessed; false only when a completed capture has at most one possible non-target subfield; otherwise unknown. Ambiguous missing records cannot create a false label. A missing/unmatched target, failed initial request, invalid source artifact or immature observation produces unknown, not zero. Positive witnesses may suffice despite later pagination failure, but this is recorded as incomplete capture in coverage reports.

Count evidence is index-defined rather than a statement of complete real-world observation. Human source audits may identify parser defects but never supply per-paper semantic labels. Corrections require replacement preserved source records or an identified deterministic resolver defect, append a new label version and invalidate dependent reports. Preference ratings, Jev answers and agent predictions cannot write labels.

Resolver conformance examples below assume mature completed captures, known target subfield A, unique families and unambiguous dates unless noted. They are verification cases, not observed study results.

| Preserved observation | Reach | Late activity | Cross-subfield |
| --- | --- | --- | --- |
| No citing records, target indexed and capture complete | false | false | false |
| Five families, all in first 180 days, all subfield A | true | false | false |
| Four families, including one in each late window, spanning B and C | false | true | true |
| Five families including both late windows, target subfield missing | true | true | unknown |
| No witnesses and incomplete pagination | unknown | unknown | unknown |
| Only one family potentially in each late window because its date conflicts across aliases | false if the complete upper total is below five | unknown | depends on preserved subfields |

<a id="learning-protocol-bounded-acquisition-and-qualification"></a>
### Bounded acquisition and qualification

First run a 100-paper acquisition pilot, independent of label prevalence: use the latest 25 fully mature UTC publication months, four uniformly selected paper families per month by ascending SHA-256 of the canonical JSON object {paper_family_id, seed} with seed 20260920 and the family's canonical unversioned arXiv id (for example 2305.01234), so anyone can reproduce the selection from arXiv's public listing. A family is eligible when any of its arXiv categories is among the configured corpus categories, cs.AI, cs.LG, quant-ph and q-bio by default, including cross-lists; it is recorded once under its primary category. A month is eligible only when its last possible first-public instant plus 455 days precedes the acquisition freeze. Preserve shortages and failures without outcome-based replacement. Stop at 100 target papers or 100000 returned citation records, whichever is reached; unfinished observations remain unknown. Report requests, bytes, runtime, original-text completeness, citation-family matching, date and topic missingness, indexing lag and projected costs. The pilot diagnoses acquisition; its ids remain development-only.

A pilot passes source feasibility only if at least 70 of the 100 intended papers have complete original-text features and known labels for each target, and all deterministic conformance checks pass. Shortfalls remain in the denominator. Failure produces a finding and no automatic workload escalation. These are operating floors, not data availability claims. Do not change target definitions to force a passing class distribution.

Then freeze a modeling population over the latest 100 fully mature UTC publication weeks, excluding pilot families, and select 2000 candidates by allocating 20 per week with the same hash rule. Preserve shortfalls. Use the temporal split below before reading outcomes. If source coverage passes but class counts are insufficient, a single expansion to 5000 selects the first 50 per same week, preserving original rows, membership and unknowns. Expansion occurs before locked evaluation is inspected. A failed locked evaluation does not authorize mining more examples from the same holdout. Beyond these caps requires a new decision. Data collection runs on demand, not automatically on each weekly tick.

The first-release historical corpus is drawn by one configured population rule recorded in its release: every eligible family whose earliest public version falls in the twelve months ending thirteen months before the build date, so that every family is mature at the build, drawn uniformly at random with a recorded seed and capped at 10,000 families across the four categories. The release records the categories, the per-category counts and the rule. Growth beyond the cap and any deletion of originals require a new decision.

Per-target release eligibility requires known labels AND complete original features for at least 70% of the intended sample, and at least 50% in every adequately sampled primary-category/month slice and every adequately sampled source-subfield/month slice (30 selected families); smaller slices are unqualified. Report separate source, label and feature coverage and exclusions, each per primary category. Missing subfield has its own stratum. Required class counts follow below; no raw paper count guarantees qualification. No human contribution-type annotation or semantic challenge set is required. Paid source calls require a separately authorized spending profile.

<a id="learning-protocol-representation-and-fitting"></a>
### Representation and fitting

The frozen embedding model is selected and pinned under MD-06 and #25; no unverified model alias is an executable artifact identity. Its manifest fixes the vector dimension, tokenizer, dense pooling, weights hash, supported length and numerical precision. A missing qualified manifest blocks embedding production, not data collection. Prediction-head implementation accepts the declared dimension and fails on a mismatch.

The overview input is original-version title, one newline, and original abstract, UTF-8 NFC, with line breaks normalized to LF. An empty abstract or input exceeding the selected model's token limit is unavailable; do not silently truncate. Encode the overview and original full-text passages using Appendix C: Retrieval protocol. Concatenate the normalized overview and overlap-weighted normalized passage pool, divided by sqrt(2), to obtain one float32 vector of shape [2d]. Reject missing complete original-text coverage, zero/nonfinite vectors or incompatible representations. Exclude separately supplied author metadata, citation counts, downstream evidence and Jev fields. Author or result cues embedded in the original text are not claimed to be removed. Fitting and inference share exactly this construction. Record retrieval availability separately: partial text can be retrieved even when prediction-head features are unavailable.

Freeze the eligible population and group related versions before splitting. Order complete ISO publication weeks by first_public_at. Assign oldest 60% of weeks to fitting, next 15% to development, next 10% to calibration and final 15% to locked evaluation, rounding the first three counts down. Require at least 40 distinct weeks overall, at least four in each partition, and retain whole weeks. Families crossing boundaries go to their earliest partition; later copies supply no new rows. Record the exact week boundaries and family resolution before examining labels.

For every target require fitting >=100 positives and >=100 negatives; development >=25 of each; calibration >=25 of each within each primary category; locked evaluation >=50 of each. A category whose calibration partition is below its floor leaves that target unavailable for that category while the others are served. These are operating floors, not statistical sufficiency claims. All labels used by a fit exist by its recorded cutoff. A true historical backtest additionally refits at each simulated cutoff with only labels actually available then; absent old availability records prevent that claim. The initial retrospective benchmark does not pretend a contemporary embedding model existed before its release.

Fit one binary logistic regression per target using mean binary cross-entropy plus lambda/2 times squared L2 weight norm; intercept is unpenalized. Search lambda in {0.0001, 0.001, 0.01, 0.1, 1}, choose lowest development Brier score, breaking ties toward larger lambda. Use deterministic L-BFGS, zero initialization, gradient infinity-norm stopping tolerance 0.000001 and maximum 2,000 iterations. Nonconvergence fails that candidate. Record solver/library revision and actual objective convention rather than confusing inverse regularization C with lambda. No class rebalancing, oversampling or synthetic negatives; unknown labels are masked per target. Freeze the chosen prediction head without refitting on development or calibration.

Fit sigmoid calibration on raw logits using calibration data only, one calibrator per target and primary category: p = sigmoid(a*z+b), with a constrained nonnegative and objective mean binary cross-entropy + (0.000001/2)*(a*a+b*b); initialize a=1,b=0 and use float64 bound-constrained L-BFGS-B with the same tolerance and iteration limit. Record the exact implementation and parameters. Final output is three named scalar probabilities with independent availability, not a softmax; the three events can co-occur. One input has shape [2d], a batch [N,2d], known labels and masks [N,3].

<a id="learning-protocol-validation-promotion-and-retraining"></a>
### Validation, promotion and retraining

The baseline probability is the fitting-partition positive fraction for that target within each primary category, fixed before evaluating later partitions. Each prediction head requires calibration and locked-evaluation Brier scores below its fitting base-rate baseline, overall and within each adequately sampled primary category. On locked evaluation require the upper bound of a paired 98.333333% bootstrap interval for head-minus-baseline Brier loss below zero, a Bonferroni allocation of the 5% family error budget across the three launch prediction heads. This is an operating comparison rule, not proof of independence or statistical power. Use 10,000 resamples of whole publication weeks, seed 20260920, with paper families inseparable. Report average precision, fixed ten-bin reliability with counts, coverage and primary-category, publication-month and source-subfield slices. Sparse slices are unqualified; do not hide them in a global metric. Qualification can fail even with many papers.

Consume a locked release evaluation set once. Model changes after inspecting it require a fresh chronological holdout; previous evaluation data is thereafter labeled development history. Preserve all attempts and comparisons. Repeated weekly checks on an already-seen monitoring set are development monitoring, not new independent evidence. Weekly promotion uses frozen target definitions, model family and lambda choice. Preserve original release split memberships. Put newly mature weeks into the refresh fitting pool except the newest four eligible weeks, which form a chronological refresh-calibration partition. Original development, calibration and consumed release-evaluation families never enter refresh fitting. Compare candidate and incumbent on the same original development monitoring support, requiring baseline improvement and no higher Brier loss. Apply the same fitting/calibration class-count gates; insufficient support retains the incumbent. Reports label this reused support development monitoring. Corpus/label-protocol version changes and changed model selection require fresh release qualification. If the manifest has not changed, skip refitting. If class-count gates fail, retain the prior compatible model.

Before each live batch, pin the entire bundle and compute probabilities only from snapshot-eligible vectors. Store prediction time, target, horizon and bundle identity before later evidence is observed. Prospective evaluation uses those persisted predictions, never probabilities recomputed after the event. Report coverage-conditioned performance and unknown-outcome rates; complete-case metrics do not remove missingness bias. No prediction-head probability acts as an admission filter for agent retrieval.

Weekly refitting uses mature labels available at the freeze and retained eligible historical data. Prediction-head updates do not train the embedding model, Jev or agent model. Label corrections create new immutable releases and invalidate affected reports. Changing embedding models rebuilds embeddings and prediction heads in a separate namespace before atomic promotion. Old snapshots retain old vectors and probabilities. Missing or invalid qualified models are explicit unavailable states.

<a id="learning-protocol-inference-contract-and-card-shape"></a>
### Inference contract and paper-card shape

Training arrays: X float32 [N,2d], Y boolean [N,3], M boolean [N,3], ordered paper ids and the immutable target/representation manifests. Y entries with M=false have no semantic value and never enter a loss. Each prediction-head fits only rows with its own M=true. Inference accepts original paper/version id and pinned bundle id, constructs x [2d], and returns three named records. Internal probabilities have shape [N,3] with an availability mask; external unavailable values are null, not zero or NaN.

Each paper-card record contains target_id, target_version, plain-language question with its fixed threshold/windows, probability (finite [0,1] or null), availability (qualified/unavailable), unavailable_reason, horizon_end, model_bundle_id, training_cutoff and evaluation_report_id. Shared provenance can be stored once in the paper-card envelope. Render all three names even if one fails. Raw coordinates, raw training examples and a composite quality score do not go to the agent. Historical estimates and live forecasts have distinct as_of/forecast-eligibility fields; retrospective estimates cannot enter prospective scoring.

The three outputs are supporting evidence. They do not filter retrieval or automatically rank digest entries. Full-paper evidence and Jev content assessments remain separate fields. Qualification of an individual prediction head permits its serving; the promised three-head feature is ready only when all three pass. An unqualified target stays explicitly unavailable rather than quietly shrinking launch scope.

<a id="learning-protocol-agent-scoring-boundary"></a>
### Agent scoring boundary

Report agent forecast accuracy separately for each of the same three target definitions on matched sealed questions. Do not manufacture one fitness number by averaging correlated targets or use citation probability as scientific value. Automatic evolutionary replacement follows Seeded evolution and population size in Appendix A: Launch profile: none in the seeded population's first two weekly cycles, and afterwards on forecast skill under a preregistration. Weekly cycles still collect, refit eligible prediction heads, evaluate forecasts and report whether or not the population changes. ForeSci is isolated development evaluation under Appendix A: Launch profile and never fitness. Digest inclusion uses agent-ranked nominations and deterministic rotation under EN-41, per island, with existing random controls and service slots preserved.

Reuse original extraction and embeddings across targets and refreshes. The Jev smoke test (RD-24) is a separate gate, held out with the assessments themselves (#123); automatic head labels do not replace it.

<a id="learning-protocol-future-targets"></a>
### Future targets

A new prediction head is an explicit registry extension, not a hidden extra output or a new encoder by default. Require an accepted decision defining the question, observation window, deterministic or independently qualified labeling source, missingness, prospective settlement and license/access costs; representative acquisition feasibility; temporally separated calibration and held-out skill; and a comparison showing useful added information beyond the existing prediction heads. Preserve old target versions, bundle order and paper-card compatibility. Revise the multiple-comparison plan before testing more targets. Serving failure of a new prediction head cannot disable qualified existing prediction heads.

Substantive use, evaluation, longer-term delayed recognition and other future outcomes remain possible because citation signals omit these questions. They are not launch tasks, reserved trained models or promised future functionality. Reconsider them only when credible labels and measurable agent benefit justify their acquisition/annotation cost. Adding prediction heads does not by itself authorize new domains, encoder fine-tuning or changed agent fitness.

<a id="learning-protocol-source-basis-and-limits"></a>
### Source basis and limits

- [OpenAlex citation recipes](https://help.openalex.org/how-to/api-recipes/) document incoming citation queries and pagination.
- [Work attributes](https://help.openalex.org/data/works/attributes/) define provider publication dates, primary topics and annual/lifetime counts. The provider date is not verified citation-passage event time.
- [Topic assignment](https://help.openalex.org/data/topics/) describes automated classifications; breadth labels inherit classification error and missingness.
- [Citation construction](https://help.openalex.org/data/works/citations/) describes matched references and coverage limitations.

These capabilities support the proposed acquisition method; they do not establish representative historical completeness, predictive accuracy or that these three targets are empirically optimal. Frozen artifacts can have later knowledge from model pretraining; disclose this separately from preventing metadata leakage into features. The qualification pipeline exists to measure these limits.

<a id="retrieval-protocol"></a>
## Appendix C: Retrieval protocol

<a id="retrieval-protocol-paper-and-passage-retrieval"></a>

Decision #68. This contract covers full-paper text retrieval alongside the original-title-and-abstract overview representation and their combined prediction-head features under FT-09. The independent Jev input remains RD-17. Retrieval scores are similarities, not probabilities or scientific-value judgments.

<a id="retrieval-protocol-representations-and-source-coverage"></a>
### Representations and source coverage

Each paper version has an overview embedding and zero or more passage embeddings in separately named indexes. The overview retains the Appendix B: Learning protocol text contract. Passage input covers successfully extracted body text, appendices, textual captions and textual tables in document order. Exclude the bibliography and repeated page furniture from passage search; retain those in the original artifact and citation-extraction pipeline. Inline mathematical text is retained as extracted, without claiming that text embeddings understand its notation or that image content has been embedded. Figures and unreadable material remain deep-read resources or explicit missing coverage. No OCR is added.

Store extraction identity, source hash, section path, block id and character offsets into the immutable extracted text for every passage. Store page/LaTeX source locations when the extractor provides them; never invent locations. Report extraction coverage as complete, partial or unavailable with reasons and included/omitted block counts. Complete refers to extractable text under this policy, not verified semantic coverage of the PDF. A pipeline failure cannot mark an incomplete passage index complete.

<a id="retrieval-protocol-chunking"></a>
### Chunking

Use the pinned embedding tokenizer. Split within section boundaries into at most 384 content tokens with 64-token overlap; use a 320-token stride and emit the final nonempty remainder only when it contains previously uncovered tokens. Do not overlap across sections. Sections shorter than 384 tokens form one passage. Token offsets map back to stored character spans, and repeated overlap is identifiable from those spans. Section titles are metadata, not silently added input. The representation manifest validates that 384 content tokens plus all model-required prefixes and special tokens fit its supported length. Incompatible models fail qualification rather than truncate.

Preserve one embedding per passage for retrieval. Document and query formatting, pooling, normalization, dimension, precision and compute platform are fixed in the immutable representation manifest. A model without supported, tested query/document compatibility cannot serve question-to-passage retrieval. Both indexes use compatible vectors from the same adopted model; indexes for different model revisions never mix.

<a id="retrieval-protocol-combined-head-representation"></a>
### Combined prediction-head representation

For prediction-head fitting and inference, use only the first public paper version and its complete extracted-text coverage under this policy. Overview and passage embeddings are unit-L2 float32 vectors of the same dimension d. For each content token t in an included section, let c(t) be the number of passage spans containing that token. Passage weight w(j) is the sum of 1/c(t) over tokens in passage j. This assigns one total unit of weight per token despite overlap. Pool p = sum(w(j) * embedding(j)) / sum(w(j)), using float64 accumulation in section/span order, then normalize p to unit L2 and cast to float32. Concatenate x = [overview, p] / sqrt(2), shape [2d], as the sole prediction-head feature vector. No later citation data, metadata counts or Jev fields enter x. The pool is an approximation to full-text representation, not a claim of reasoning over every detail.

Require at least one passage, valid original overview, complete original extraction under the documented policy, and finite nonzero pool. Missing or partial full text makes prediction-head inference unavailable; do not substitute zeros, a revised paper or an overview-only model. Retrieval still serves the available overview and passages with their coverage states. The paper card records prediction-head eligibility separately from passage availability. Report the exclusion rate and resulting coverage bias in training/evaluation reports. A future fallback prediction head is a separate model decision.

The pooled vector and feature hash include ordered passage identities, source/extraction identity, chunk policy, weights, overview and representation identity. Changing any of these rebuilds and requalifies affected prediction heads; ordinary outcome-label refresh reuses the same features. Historical training and live inference use this identical construction. New paper revisions can have new retrieval paper cards but cannot replace original-version prediction-head features.

<a id="retrieval-protocol-search-and-card-evidence"></a>
### Search and paper-card evidence

Keep the existing five agent tools. query_cards accepts either the bounded paper_ids lookup defined in Appendix A: Launch profile or the following text search, never both. Text search has a retrieval mode: overview or passages, query text and a result limit from 1 to 5; omitted mode is overview and omitted limit is 5. A paper filter is optional and names one snapshot-visible paper family. Reject extra fields and an empty or over-limit query without truncation. Query text is at most 256 embedding tokens including model-required formatting. Tool outputs still count against AG-12 run budgets.

Passage mode ranks eligible vectors by cosine similarity, ties by paper-family id, paper-version id, section order and passage start offset. Consider only the version selected by the run snapshot; never mix versions or fetch newer artifacts. With no paper filter, the result limit counts distinct paper families; return at most that many families and two non-overlapping matching passages per paper. With a filter, the result limit counts non-overlapping passages from that paper. Both cases therefore return at most five results of their specified unit. Select greedily in rank order, skipping passages overlapping an already selected span in the same version. If fewer eligible results exist, return fewer; no fabricated matches or minimum-similarity claim. An index implementation must reproduce the specified ranking or obtain a separate measured approximation decision.

Return each base paper card unchanged and attach a separately identified query-evidence envelope: query hash, snapshot id, retrieval-mode and manifest ids, paper/version ids, exact passage text, section/source locations, similarity score and coverage state. This envelope is query-specific, not a mutation of the stored paper card. A base paper card lists overview/passage availability, coverage, passage count and the source locator for deep_read. This makes full-paper evidence available with paper cards without dumping a paper into every default paper card.

The agent can deep_read the cited surrounding section through existing tools. It receives text and evidence identities, never vector coordinates. Jev assessments remain separately identified; neither retrieval scores nor extracted passages are automatically Jev judgments, quality scores, forecast labels or evolutionary fitness.

<a id="retrieval-protocol-failure-caching-and-snapshots"></a>
### Failure, caching and snapshots

Cache passage embeddings by source/extraction hash, section/span identity, chunk-policy version and representation identity. Index publication is atomic per paper version: unfinished work is pending, not partially complete. Extraction-proven partial text can publish a partial index with its omissions recorded. Reuse unchanged artifacts across runs and prediction-head refits. Replacing extraction, chunking or model revision creates new immutable artifacts; old snapshots retain their own index membership and paper-card versions.

Missing full text leaves overview search and source deep reading available with explicit reasons. A passage-mode request without eligible indexed passages returns unavailable for that mode; it does not silently return overview results. Corrupt or incompatible vectors cannot enter a response. A retrieval outage cannot fabricate evidence or remove the original paper identity and abstract.

<a id="retrieval-protocol-qualification"></a>
### Qualification

Before a study uses passage retrieval, preserve an overview-only baseline under SR-17 and preregister a matched comparison under SR-18. Use the same questions, snapshots and reading budgets. Report passage-source fidelity, extraction coverage, relevant-evidence retrieval and agent evidence-support results separately from forecast accuracy and reader usefulness. The benefit criterion, sample and held-out comparison are fixed in Appendix A: Launch profile; available infrastructure alone does not establish benefit. No paid inference or hardware purchase is authorized by this protocol.
