# 0002. Adopt the post-baseline candidates of 2026-09-19 as a set

- Status: accepted
- Date: 2026-09-19
- Issue: #45
- Spec: SDD Scope and scale, Terms, and sections 1 to 8. 44 requirements added (SDD-SR-23 to SR-27, PL-20 to PL-22, IN-33 to IN-42, EN-35 to EN-42, AG-25 to AG-35, RD-11 to RD-14, MD-12, FT-17 and FT-18), 33 amended, 6 reserved (SDD-FT-01 to FT-05, SDD-RD-09). The TDD is unchanged.
- Pull requests: pending

## Context

The baseline SDD (0001) was written from the candidates of the owner's first design session. Later sessions the same day raised 62 more, C-2026-09-19-189 to C-2026-09-19-250, merged into `docs/incoming.html` in #42 and regrouped in #44 into eleven groups. A leakage check across the set found four paths by which information from after a sheet's issue could reach a head, a baseline or an agent, and the candidates that close them contradict SDD-FT-10 and SDD-FT-16 as written.

## Decision

The 48 candidates in the first eight groups of the regrouped inbox are accepted as a set, with C-2026-09-19-195 accepted: in the first build the heads are fit on the frozen embedder's vector alone, and weekly training of the encoder is held out until the configuration without it has been measured on the same score (SR-17). SDD-FT-01 to SDD-FT-05 and SDD-RD-09 are reserved; SDD-FT-09, SDD-FT-10, SDD-FT-16 and SDD-MD-04 are rewritten; the Scope paragraph and the Terms change with them. The embedder-alone premise is superseded in part by decision [0021](0021-add-card-metadata-to-prediction-heads.md): the head input widens with a declared metadata block beside the embedding, while the embedding-only head remains the comparison arm of the #25 run.

Five statements were reworded before acceptance so the set agrees with itself and with the merged SDD (C-192, C-247, C-213, C-200 with C-202, C-245); the inbox notes say why. Five candidates are held back and produce no text: C-196, C-199, C-208, C-209 and C-210. C-240 is a later measured layer. C-207 and C-212 are findings. C-222 is decided on #46.

Every requirement added or changed carries `status: pending:#45` and `tdd: none`.

## Consequences

The first build has no training job, no encoder checkpoint series and no masked-word surprise on the card. The weekly cycle is: freeze the week, refit the heads, calibrate, score, select, report. #9, #18, #34, #37 and #39 are moot for the first build and closed with a pointer here; they reopen if weekly training enters.

The digest reaches the raters through a private app on a private network (PL-22), the first inbound path in the specification, which also carries the anomaly flags. Three values on #6 are settled by it: the delivery path of the digest, the channel for anomaly flags, and the meaning of a pick (EN-41). Ratings enter neither fitness nor head fitting in the first build (#40 answered for now; #46 holds the later question).

A fourth baseline, the nearest-neighbor forecast, answers every sheet (IN-33). The picks of discovery services are captured daily (EN-38), are the obvious baseline of the novelty term, and are carried unmarked in the digest so the raters compare blind (EN-42); the popularity baseline answers from counts captured at the snapshot (RD-12). Both depend on the finding C-207 for which services allow capture.

Every derived stored value carries the hashes of its inputs and the version of its component (SR-23), and every step that can be wrong has a named accuracy measure (SR-27), applied to ingest, heads, neighbor retrieval, resolvers and outcome sources.

Left open: the values this batch names as `not yet set (#6)`; the resolver for the trend-to-paper type (#17); the language and toolchain (#43), on which the TDD waits.
