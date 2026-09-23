# 0023. Register short-horizon targets and year-one selection fitness

- Status: accepted
- Date: 2026-09-22
- Issue: #195, carrying #153 and #130
- Spec: SDD-SR-07, SR-08, SR-09, AG-19, AG-26, FT-14 amended; SDD-FT-27 added; SDD Appendix B target registry (short-horizon target registry added) and agent scoring boundary; SDD Appendix A seeded evolution and population size; TDD-2.1.10, TDD-3.1.57, TDD-3.1.65, TDD-4.1.77 amended; TDD-4.1.81 added
- Pull requests: pending

## Context

Decision 0015 fixed weekly selection fitness to forecast skill but left the minimum resolved-claim count open, because the only targets that resolve within a genome's first year are the three citation targets, which mature at 365 days plus a 90-day indexing allowance: selection would have had no resolved signal for over a year. Issue #153 proposed short-horizon signals that resolve on a weekly-to-six-month scale, are domain-general, deterministic and replayable from stored responses, and outside the agent's influence; issue #130 held open the minimum resolved-claim count pending that supply of faster signal. Issue #155 already unified the nomination's preference score with the sealed `rater_like_7d` forecast (decision 0022). The owner decided both on 2026-09-22, adopting the minimum that gives year-one selection a resolved signal, nothing more.

## Decision

**Short-horizon target registry (Appendix B).** Three definitions join the three citation targets as registered targets, disjoint from the prediction-head registry: `rater_like_7d` (resolves at the digest week's close from the island rater's like on the nominated entry; unavailable for the unrated q-bio island), `early_citation_rank_60d` (top decile of the publication-week primary-category cohort by citing families observed at 60 days; base rate fixed at 10% by the rank definition itself), and `venue_180d` (a journal-ref, DOI, OpenAlex journal/proceedings location or a fixed versioned acceptance-note match on the arXiv record, by t0 + 180 days; per-category base rate from the historical corpus). `early_citation_rank_60d` and `venue_180d` reuse the existing daily listing and weekly OpenAlex observation; no new source or acquisition pipeline is added, and historical labels for them come from the same listing and observations. `rater_like_7d` has no historical-corpus label, since no rating precedes launch, and is scored against the population-mean baseline instead.

**Year-one fitness (FT-12, FT-14, AG-19).** Fitness for weekly selection is skill over a genome's resolved registered targets — the three citation targets and the three short-horizon targets above, six in all — reported per target and combined by FT-14 into one internal ranking statistic, the mean skill over the genome's own resolved set; this ranking statistic is never presented as the scientific value FT-12's per-target reports carry. The minimum resolved-claim count is 30 resolved registered-target forecasts (#130's open point); with `rater_like_7d` and `early_citation_rank_60d` resolving weekly and at 60 days, a genome reaches it in two to five weeks instead of never in year one. Below the count, the island's already-specified registered proxy (preference credit for the rated islands, calibrated-head agreement for q-bio) continues to rank it.

**Grounding gate (new FT-27).** Every sealed claim's cited evidence must resolve to a span of the immutable extracted text containing the quoted words; the seal records the claim grounded or not. A genome's grounding is the grounded share of its last 30 sealed claims. Below a floor of 0.95, the genome is neither drawn as a parent (AG-19) nor kept as a survivor of a select stage (FT-14), alongside the existing resolved-claim-count exclusion. Grounding is a mechanical check, never a citation-skill input or a paper-card field.

**Question issuance (SR-09, AG-26).** Every sheet issues five questions — the three citation questions plus `early_citation_rank_60d` and `venue_180d` — instead of three; `rater_like_7d` is not issued as a separate question, but is sealed once as the nomination's `preference` field and resolved from the island's rating of that entry, exactly as decision 0022 already defined it. SR-09 and AG-26 describe this five-question contract now; their code (`environment/sealing.py#validate_horizon`, fixed to a 365-day event window, and `contracts/submissions.py#parse_answers`, bounded to three answers) still serves the three-target contract, so both move from `implemented` to a recorded deviation citing #153 until a code slice raises the horizon check and the submit bound to five.

Not adopted for release 1, per #153's decision comment: `stability`, `revision_60d` and `early_citation_30d` as fitness (reported only if free); web mentions (#143, closed on feasibility); a venue registry or venue shown on cards (#156, deferred).

## Consequences

FT-14 and AG-19 were already `pending:#162`; their text now describes the six-target fitness pool, the count of 30, and the grounding gate, with no status change. FT-27 is new and carries `pending:#162` for the same reason: its eligibility gate lives beside AG-19's parent draw and FT-14's retirement in `orchestration/selection.py` and `evolution/parents.py`, the files #162 already owns.

SR-09 and AG-26 were `implemented`; they now carry `deviation:#153` until a code slice widens `validate_horizon` to the three horizons this decision adds and raises `_MAX_ANSWERS` from 3 to 5. No such code slice is filed yet; #73, which owns the submission/sealing path, explicitly excludes new targets from its scope, and #162 owns selection, not sealing or submission. The owner must file that code slice before SR-09 and AG-26 can move back to `implemented`.

What is deliberately left open: the mechanical per-claim grounding computation itself (which module writes the grounded verdict at seal) is not assigned a code owner here; FT-27 states the contract and the gate it feeds, and names its owner only where the gate is applied. Repointing SR-09, AG-26 and FT-27 at their eventual code slice, instead of at #153/#162, is a separate change, following the same pattern issue #100 already documents for older items.

Decision 0023 supersedes nothing. It cites #130's decision comment of 2026-09-22 for the count of 30.
