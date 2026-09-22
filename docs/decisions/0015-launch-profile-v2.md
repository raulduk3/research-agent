# 0015. Amend the launch profile to version 2

- Status: accepted
- Date: 2026-09-22
- Issue: #131, carrying #105, #123, #129 and #130
- Spec: SDD Scope and scale, Terms, 6.3 heading note; SDD-SR-13, SR-15, SR-16, SR-17, SR-28, PL-03, PL-04, PL-10, PL-11, EN-09, EN-16, AG-01 to AG-06, AG-18 to AG-21, AG-35, RD-02, RD-03, RD-15 to RD-24, MD-06, FT-12 to FT-16; SDD Appendix A (all sections, plus Seeded evolution and population size), Appendix B source basis, Appendix C chunking; TDD-2.1.20, TDD-3.1.17, TDD-3.1.37, TDD-3.1.39 to TDD-3.1.42, TDD-3.1.64 to TDD-3.1.67, TDD-4.1.67, TDD-4.1.75 to TDD-4.1.78 and the shared storage, agent, operations and spending contracts
- Pull requests: pending

## Context

Launch profile version 1 fixed four values that measurement and access have since overtaken. It pinned `GLM-4.6V-FP8` on a rented four-GPU window inside caps of USD 25 per day and 300 per month, which the 2026-09-22 cost survey on #55 showed the rental posture cannot meet at any agent count. It fixed a host floor of 16 threads, 64 GiB and 1 TiB against no measured workload, while the measurement on #105 recorded the pinned embedder needing about 2 GiB and a few hours a day, and running at 8 seconds per paper on the development machine's graphics processor against 22 on its processor. It put eight Jev assessments on every paper card and made a verified Jev integration a launch gate, while the provider access that #59 needs does not exist. And it disabled selection and mutation outright, at a time when a run's cost was an unknown rental share rather than a measured per-run number.

The owner accepted four decisions on 2026-09-22, one per issue. This record carries all four into one profile version, because they share the same paragraphs: the spend ceiling that the hosted model makes affordable is the same ceiling that bounds how many genomes selection may admit.

## Decision

The launch profile is version 2.

**Agent model (#129).** `glm-5.3-flash`, served per-token by Z.ai's first-party API as the one named provider. The system hosts no agent weights. Each run records the provider identity and the revision the provider returned; a mutable alias is recorded as unpinned rather than given a fabricated hash. There is no relay, no second provider and no automatic fallback: a provider outage is an unavailable endpoint and a void run. Ceilings become USD 8 per UTC day and USD 200 per UTC month. The qualification battery, its tool, figure and evidence-location floors unchanged, is the activation gate, and authorized spend stays zero until it passes.

**Host and representation (#105).** The application host is the owner's development Mac, kept awake, running the services in a Linux virtual machine, with container images pinned to that host's architecture. The floor in PL-10 is no longer four fixed numbers; it is the measured demand recorded under #82, #112 and #114 plus a stated margin, fixed in a profile amendment before #74, and the per-role container limits and batch memory thresholds are resized in that same amendment. The representation platform is this host's graphics processor in float32 with deterministic algorithms, recorded in the representation manifest; a vector computed on another platform belongs to another namespace. Backups go to object storage and the anchor receiver is the smallest separate virtual private server.

**Jev held out (#123).** The eight assessments are held out of the launch under SR-17 until provider access exists, by the mechanism the encoder hold-out used under #51: a sentence in Scope and scale, a note under the 6.3 heading, a Limits line on each of RD-15 to RD-24, a Terms entry, and a paragraph in Appendix A's scope. No new status value is introduced and the trace status of RD-15 to RD-24 is unchanged. RD-24's readiness condition and RD-23's with-Jev arm are suspended by a sentence each; the without-Jev arm is the launch; #59 to #62 are deferred. Every Jev requirement keeps its id and text for the day access exists.

**Seeded evolution (#130).** The population is eight seeded configurations: the four launch emphases and four owner-written variants. It is fixed for its first two weekly cycles so the first selection comparison has a control, and from the third cycle FT-14 selects on the forecast skill FT-12 reports. FT-12 now reports measured skill per dollar beside skill; that term breaks ties and sets how many genomes the month's remaining budget admits, and is never the objective. The floor is four genomes. Mutation is one field-level change to one parent, similarity admission refuses a repeat, and the diversity archive keeps the best-scoring genome of each retired lineage. One preregistration under SR-18 precedes the first selecting stage and names the proxies that stand in while one-year outcomes do not exist: rater preference, lead time over discovery services, and agreement with the calibrated heads.

## Consequences

Two requirements whose code was written against version 1 now state something the code does not do, and carry a deviation marker that says so.

- MD-06 and TDD-4.1.67 are `deviation:#105`. `models/backend.py#TransformersCPUBackend` loads the pinned embedder on the processor, and `models/manifest.py#RepresentationManifest` has no compute-platform field. Moving the embedder to the host's graphics device and adding that field to the manifest changes the representation hash, so every vector under the current manifest belongs to the old namespace and is rebuilt, not reused.
- FT-12 and TDD-4.1.75 are `deviation:#130`. `scoring/scores.py#target_skill` reports per-target skill and has no cost term; skill per dollar needs the settled `agent_inference` reservation of each run in the support, which no run yet produces.

The rental contracts are gone from the TDD: `RentalPermit`, the rental controller, `rental_seconds` and the `inference_rental`/`inference_storage` cost classes, replaced by one `agent_inference` class and per-token quote units. `docs/evidence/funding/authorization-status.md` is a dated record that cites `RentalPermit` and the four-GPU envelope; it stands as the evidence it was on 2026-09-22 and is not rewritten here.

What becomes impossible: renting inference capacity, reaching a second agent-model host, mixing vectors from two compute platforms in one namespace, showing a Jev assessment on a paper card, and selecting on anything but forecast skill.

What is deliberately left open: the measured host floor and the resized container limits, which the amendment before #74 fixes from #82, #112 and #114; the minimum resolved-claim count below which a genome is neither parent nor replaced, which rests on #130; and the day Jev provider access exists, which #123 leaves to a later decision.
