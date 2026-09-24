# 0027. Issue a day's sheets per island and key the draw on the day

- Status: accepted
- Date: 2026-09-23
- Issue: #283
- Spec: SDD Appendix A (agent batches); TDD-3.1.13, TDD-3.1.14, TDD-3.1.41
- Pull requests: pending

## Context

A sheet holds 1 to 20 questions (`contracts/questions.py`), a slot's
`batch_id` is the hash of a sealed sheet, and a run carries up to three
issued question ids. One sheet per day would cover about six papers across
the three islands, whatever the spend covered. The coverage draw was keyed
on `{batch_id, island, family_id}` (TDD-3.1.41), but the sheet holds the
papers' questions, so each needed the other first. The owner accepted the
recommendation on #283.

## Decision

- A day issues one sheet per island per chunk of up to 20 questions. A
  chunk holds whole papers: a paper's three questions are never split
  across sheets, so a chunk holds at most six papers. The sheets are
  sealed after the day's papers are carded, and their questions cover
  every carded paper of the day, sampled or not, so the prediction heads
  forecast every one (`ingest/daily.py#issue_questions`).
- The coverage draw is keyed on `{utc_day, island, family_id, seed}`. It
  needs nothing a sheet fixes, so it is the same whether computed before or
  after the sheets are sealed.
- A slot's `batch_id` stays the hash of the sealed sheet that holds its
  paper's questions (EN-10).
- The day's snapshot is sealed after the day's sheets and pinned to every
  one of them (EN-09's common snapshot).
- Each island's draw spends its share of the day's remaining authorized
  spend, in proportion to its carded papers that day, and a sampled paper
  costs one per-run reservation for each active configuration of the
  island. The seed is fixed by the launch profile hash. The draw, its seed,
  spend and coverage are published as a record.

No code contract widens: the 20-question sheet bound and the three-question
run bound stay as they are.

## Consequences

`orchestration/scheduler.py#draw_coverage_sample` takes the UTC day and
the island's configuration count instead of a batch id.
`orchestration/daily.py#issue_day` drives the day end to end and writes
one run record per sampled paper and active genome. A second call on the
same day replays every command and creates nothing.

A run's `seed` column is a bigint, so the run record stores the first 63
bits of the 64-bit specification seed. The run's `question_seal_deadline`
is the paper's first public time plus 24 hours (EN-13). Starting the runs
is #279. The durable leases and launcher of TDD-3.1.41 are still open, so
EN-09 and AG-05 stay pending.
