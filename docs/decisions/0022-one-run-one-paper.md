# 0022. Amend the run shape to one paper per run

- Status: accepted
- Date: 2026-09-23
- Issue: #193, carrying #155
- Spec: SDD-EN-09, AG-04, AG-05, AG-12, AG-17, AG-25, AG-26, AG-27, EN-41, IN-04, IN-43; AG-36, AG-38 reworded for consistency; SDD Appendix A agent batches, schemas and bounded reading; Appendix B agent scoring boundary; TDD-3.1.13, 3.1.35, 3.1.40, 3.1.41, 3.1.52, 3.1.56, 3.1.57, 3.1.58, 3.1.61, 3.1.72; SlotIdentity, RunSpec, BudgetLimits, SubmitArgs and Nomination records
- Pull requests: pending

## Context

The run shape decision 0015 adopted gave each run a shard of up to 20 papers: one first message carrying every shard paper and question id, one atomic submit answering every issued question with up to seven ranked nominations, and per-run budgets sized for that shape. A run therefore searched across papers inside one context window and reasoned past cards it did not need. Issue #155 asked whether a run should instead map to one paper, so that a context window holds one paper's card and the reasoning about it, with the agent still free to read other cards through its tools.

The owner weighed sampling every genome to the same partial daily set of papers, shrinking the population to whatever the daily spend cap covers at full coverage, keeping the 20-paper shard, and splitting forecasting from nomination into two run kinds. The owner decided the first of these, with the budgets and coverage rule below, on 2026-09-23.

## Decision

One agent run maps to one paper.

**Run shape.** A slot is (daily batch, paper, configuration, attempt). The first message holds the run's paper id, its issued questions, its budgets and a description of the snapshot; it holds no paper card (AG-25). The run's five tools are unchanged (#117): it may read any card, neighbor, graph node or passage of the snapshot, and it forecasts and nominates for its own paper only.

**Questions and submit (AG-26).** One probability answer with evidence for each of the three registry targets, and exactly one nomination for the run's own paper: `recommend` (bool), `preference` (the sealed `rater_like_7d` forecast, Appendix B), and a rationale. `preference` is not one of the three registry targets and never enters citation-skill scoring; it is IN-43's preference credit and EN-41's ranking input.

**Budgets (Appendix A, configured values, measured before activation).** 6 model calls, 12 tool calls, 3 deep reads, 6 images, 32,768 context tokens, 4,096 generated tokens, a 64,000 `max_tokens_per_run` ceiling, and 5 minutes wall time, replacing the 20-paper shard's 16/40/8/12/65,536/16,384/1,200,000 values.

**Coverage rule.** Per island per day, the number of papers each genome reads is the largest count the island's remaining authorized spend covers at the measured per-run cost, drawn by hash from the day's stream with a recorded seed, the same sample for every genome of the island. Papers outside the sample keep their cards and prediction-head probabilities and receive no agent forecast that day; coverage is reported daily. At the measured per-run cost and the USD 8 daily cap across twelve genomes, the arithmetic covers the whole stream; the sample rule guards a costlier measured run rather than describing the expected regime.

**Digest (EN-41).** A genome's daily nomination list is its recommended papers for the day, ranked by `preference` descending; the round-robin merge across an island's genomes is unchanged.

**Selection proxy (IN-43).** A rating's credit divides among nominating genomes in proportion to the nomination's `preference` rather than the `citation_reach_365d` probability.

Decision 0015's 20-paper shard, in SDD Appendix A and the AG-04/AG-05 limits it set, is superseded by this record.

## Consequences

Most of the requirements and TDD items listed above were already `pending:#73` or `pending:#117`; they now describe a run bound to one paper rather than a shard and carry `pending:#194`, the code slice that implements this run shape: slots, scheduler, the daily sample, budgets and the single-nomination submit.

EN-41 and TDD-3.1.35 were `implemented`: `digest/nominations.py#allocate_population_entries` merges each configuration's own shard nomination lists round-robin, then round-robins the island's configuration lists, exactly as decision 0015's shape specified. That code does not meet this decision's text, so both carry `deviation:#194` rather than `pending:#194` until the code slice rewrites the merge to rank each genome's day by nomination preference.

AG-36 and AG-38, which cross-reference EN-09's slot mechanism by id, are reworded from "shard" to "paper" for consistency; their own status and code ownership stay under #162.

What becomes impossible: a run reasoning across more than one paper's forecast inside its own context window, and a submit carrying more than one nomination.

What is deliberately left open: the two short-horizon targets (`early_citation_rank_60d`, `venue_180d`) that #153 adds to the same submit shape are a separate amendment, not part of this one; and a handful of illustrative "shard" mentions outside the touched items (TDD-2.1.9, TDD-3.1.14, TDD-3.1.29, and the Jev comparison paragraphs of Appendix A) are left for a later pass, since they describe test examples or a held-out comparison arm rather than assert a structural fact this decision changes.
