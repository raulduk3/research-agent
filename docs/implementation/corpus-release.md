# Corpus release assembly

This implements the release-assembly slice of #66 under #114: given a
frozen population already selected elsewhere, it resolves automatic labels,
assigns each family's split, writes a coverage report and publishes one
immutable `CorpusRelease` artifact with content hashes. It does not select
the pilot or modeling population (`learning/corpus.py#select_pilot`, #65),
acquire original papers or citation records (#65/#110), or compute features
(#70). It consumes those pipelines' already published, content-addressed
outputs by reference.

## Label-first gating (#144)

The acquisition harness (`docs/implementation/source-pilot.md`) orders a
selected family's own stages so that no time is spent downloading or
embedding text a label can never train a head from: it observes citations
first (`openalex`), resolves the three automatic-citations-v1 target labels
from that observation alone (`ingest/pilot.py#resolve_citation_gate`, the
same pure resolver this job uses), then requests `documents` only for a
family whose every target resolved to a known `true`/`false` state. A
family with any `unknown` label is recorded in the pilot's own report (its
`gate` counts, below) and skipped for acquisition; it still counts toward
the intended population as excluded, and — once it reaches this job — as an
`excluded`/unlabeled-partition row whose per-target reason lives on its
published `AutomaticLabel`, per the release contract's existing coverage
reporting (`build_row`, `coverage_report_bytes`).

Gating is a configured switch, `--gate-on-labels` on `bin/corpus-pilot`,
fixed on a pilot's first run like every other selection parameter. It
defaults off so the already-committed 100-family pilot reproduces exactly
byte for byte; a corpus release population draw should pass it explicitly.
With it on, the `openalex` stage's report gains a `gate` object (`labels`
per target, `decision`: `acquire` or `skip`), and `bin/corpus-pilot report`
gains a `gate` summary: `selected`, `labeled`, `gated_out`, `acquired`,
`embedded` (always `0`; no embedding pipeline exists yet, #70). With it
off, `gate.labeled` and `gate.gated_out` stay `0` and `documents` is
enqueued unconditionally, exactly as before this change.

The corpus population rule — the owner's still-open decision on #66 — is a
required, non-blank configured value. The job refuses to run without one,
both at the CLI (`--population-rule` is required and rejected if blank) and
inside `assemble_release` itself, so a caller that bypasses the CLI gets the
same refusal.

## Owners

| Concern | Owner | Tests |
| --- | --- | --- |
| Row assembly, coverage report and release assembly (pure) | `learning/release.py#build_row`, `#coverage_report_bytes`, `#assemble_release` | `tests/learning/test_release.py` |
| Resumable `label` job worker | `learning/release.py#ReleaseWorker` | same |
| Local operator and CLI | `learning/release.py#main`, `bin/build-corpus` | same |
| Candidate list from a pilot's committed stages (#321) | `learning/candidates.py#build_candidates`, `#main`, `bin/release-candidates` | `tests/learning/test_candidates.py` |
| Binding a verified embed batch and the exported text to the pinned tokenizer | `learning/release.py#local_embedding_inputs` | same |
| Head fitting over two committed releases (#278) | `learning/pipeline.py#FitWorker`, `#main`, `bin/fit-heads` | `tests/learning/test_pipeline.py` |

## Design

The release job claims a `label` job (one of the fixed kinds in
`contracts/jobs.py`) whose input manifest is a specification: the purpose,
the population rule, the selection seed/freeze/cutoff, the intended
population count, the enumerated-population hash, an optional prior release
hash, and the ordered list of selected candidates. Each candidate names its
family and version id, its known first-public time, and — when an earlier
pipeline has already published them — the manifest hashes of its
`PaperVersionRecord` and `CitationObservation`. Missing values are expected:
a family the acquisition pipeline has not yet captured still gets an
admitted or excluded row, never a job failure.

For each candidate the worker:

1. Reads the paper and observation (when their hashes are present) by
   publication manifest, the same addressing every other job output uses.
2. Resolves the three automatic-citations-v1 target labels through the
   existing pure resolver (`outcomes/resolve.py#Resolver`), against one
   fixed registry identity (`release.py#_TARGET_META`) shared by every
   release regardless of its own fitting cutoff — FT-19 requires labels to
   trace to one resolver version, not one tied to this job's own manifest.
   Citation families the observation cites are read by their own content
   hash, the identity `Resolver` verifies them against, not by publication
   manifest.
3. Assigns the row's partition: `pilot` for an acquisition-pilot release,
   otherwise the frozen chronological split week its first-public time
   falls in. A family whose maturity date (t0 + 455 days) is later than the
   release's fitting cutoff is refused rather than silently admitted into a
   labeled split — an unmatured outcome cannot honestly enter training data.
4. Publishes the row and checkpoints it before moving to the next
   candidate.

Once every candidate has a row, the worker rebuilds the full row set from
its checkpointed outputs, assembles and publishes the `CorpusRelease` and
its coverage report, and completes the job with a summary naming both
hashes.

## Resumption

Each candidate is one checkpointed unit, matching the pattern in
`docs/implementation/source-pilot.md`: the worker records completed work
keys and output hashes after every row, and a resumed claim restores them
before continuing with the next candidate. Nothing before the last saved
state is repeated. No `CorpusRelease` is ever published until every
candidate has a row; a killed job exposes no partial release.

## Operating it

```
bin/corpus-pilot run --state DIR --dsn DSN            # capture (#65)
bin/release-candidates --state DIR --dsn DSN \
  --corpus-state DIR2 --corpus-dsn DSN2 \
  --purpose acquisition_pilot --out candidates.json
bin/build-corpus run --state DIR2 --dsn DSN2 \
  --population-rule "<the owner's answer on #66>" \
  --representation-hash <sha256 of the pinned embedding manifest> \
  --purpose acquisition_pilot --release-id pilot --candidates candidates.json
bin/build-corpus report --state DIR2 --dsn DSN2 \
  --population-rule "..." --representation-hash <sha256> --release-id pilot
```

`--release-id` names a release so several share one schema: the job id is
derived from it, `run` enqueues that release only if its job is absent, and
`report` lists only that job. Without it the schema holds one release, the
first job enqueued there, as before. A pilot schema can hold a release job
too: the pilot's own commands read only its `capture` jobs
(`ingest/pilot_run.py#_jobs`). Keeping the release in its own schema is
still the rule, because the release job reads its inputs from the store it
runs in.

`bin/corpus-pilot run`'s eligibility categories are a configured value of
the run too: omitted, `--categories` defaults to the owner's four (cs.AI,
cs.LG, quant-ph, q-bio), each deriving its own OAI-PMH listing set so a
paper cross-listed in from another archive is still enumerated; the
selection report records the categories, the derived sets and the eligible
count per category. `--categories cs.AI,cs.LG` reproduces the original
two-category 100-family pilot's population exactly (#136).

The same capture harness draws the release population by passing the
owner's cap, seed and rule text to `bin/corpus-pilot` instead of accepting
the 100-family pilot's defaults; `--per-month 0` disables the pilot's
per-month stratification so the draw is one uniform, seeded rank over
every eligible family in the mature window (#133). A release run also
passes `--gate-on-labels` so a family whose labels cannot resolve is never
downloaded or embedded (#144):

```
bin/corpus-pilot run --state DIR --dsn DSN \
  --population-rule "<the owner's population rule from #66>" \
  --cap 10000 --seed <the owner's recorded seed> --per-month 0 \
  --gate-on-labels
```

At the pilot's measured ~8.5 MB of retained source and PDF bytes per
family, 10,000 families is roughly 85 GB of originals before citation
records and listings. Document capture makes two arXiv requests per
family (source and PDF) at arXiv's minimum 3-second request spacing, so
10,000 families take at least 20,000 requests, about 16.7 hours of request
time alone; the listing stage is unaffected by the cap, since it always
enumerates the whole mature window.

The candidates file is a JSON object with `selection_seed`,
`selection_frozen_at`, `fitting_cutoff`, `intended_population_count`,
`enumerated_population_hash` and `candidates` (and, for a purpose other than
`acquisition_pilot`, `fit_weeks`/`development_weeks`/`calibration_weeks`/
`locked_evaluation_weeks`). `bin/release-candidates` builds it from a pilot
schema (#321):

- The candidates are the committed selection's `selected` families in rank
  order; the seed, freeze instant, intended count and population hash are
  the selection's own. `--fitting-cutoff` defaults to the freeze instant,
  which admits only families from mature months.
- Each family gets a `PaperVersionRecord` built from its selection entry
  (title, abstract, categories, author and version counts), under the ids
  `ingest/pilot.py#gate_identity` derives, the same the pilot's observations
  and `bin/export-text`'s paper versions carry.
- Each family's observation is the one its committed
  `openalex_snapshot_labels` pass published; the citation family records it
  names come with it. A family with no such observation stays a candidate
  with none, so its row's labels are unknown; the printed counts say how
  many (`observed`, `unobserved`).
- The paper records, observations and citation family records are
  published into the corpus schema (`--corpus-state`/`--corpus-dsn`, the
  `--state`/`--dsn` given to `bin/build-corpus`), never the pilot's. A
  record already there is reused, so a rebuild writes the same file.
- A purpose other than `acquisition_pilot` splits the candidates' own
  publication weeks chronologically (`learning/corpus.py#split_weeks`).
- The file records its `purpose` and a `candidates_hash` over every other
  field. `bin/build-corpus` refuses a file built for another purpose.

## Embedding options (#278)

`bin/build-corpus run` takes three optional flags for a release the heads
can be fitted from:

- `--embeddings DIR` is a `bin/embed-batch --out` directory: its
  `manifest.json` and one vector file per paper version. The release job
  verifies every file against the manifest's hashes before using it.
- `--text DIR` is the `bin/export-text` directory that batch embedded. The
  two are given together; either alone is refused. Each row's passage spans
  are rebuilt from the exported text with the batch's chunker and must match
  the embedded passages' text hashes, and the text and vectors must name the
  same extraction.
- `--model-cache-dir DIR` is the local model cache holding the pinned
  tokenizer, the same `--cache-dir` `bin/embed-batch` and
  `bin/import-embeddings` used. It is read with no download, so the pinned
  model must already be cached there; omitted, the default cache is used.

With them, every row with a paper record records `abstract_tokens`,
`title_tokens`, `first_available_weekday` and `code_link`, the token counts
taken with the pinned tokenizer, and a row whose version is in the batch
with a complete extraction and poolable vectors gets one published
`CombinedFeatureRecord`, which its `feature_hash` names
(`release.py#ReleaseWorker._publish_feature`). Any other row keeps a `null`
`feature_hash`. Without the flags the release is built as before, with no
card fields and no features, and `bin/fit-heads` refuses its rows
(`features.py#row_card_metadata`).

## From a population to fitted heads (#278)

The one-pass order, each step on the application host unless it says
otherwise:

1. Export the pilot's committed documents as extracted text:
   `bin/export-text --state PILOT --dsn "$PILOT_DSN" --out ./text`.
2. Embed it, on a rented GPU host or locally:
   `bin/embed-batch --text ./text --out ./vectors [--device cuda]`. Syncing
   `./text` out and `./vectors` back is described in
   `docs/implementation/remote-embedding.md#Sync`.
3. Gate the batch on platform agreement:
   `bin/import-embeddings --in ./vectors --namespace ./index --text ./text --check 25 --state PILOT --dsn "$PILOT_DSN"`.
   A batch it refuses is not used in the next step. With `--state` and
   `--dsn`, every imported version also gets its embedding view (#302).
4. Build the release from the same batch and text:

   ```
   bin/release-candidates --state PILOT --dsn "$PILOT_DSN" \
     --corpus-state DIR2 --corpus-dsn DSN2 \
     --purpose initial_fit --out fit-candidates.json
   bin/build-corpus run --state DIR2 --dsn DSN2 \
     --population-rule "<the owner's answer on #66>" \
     --representation-hash <sha256 of the pinned embedding manifest> \
     --purpose initial_fit --release-id initial-fit \
     --candidates fit-candidates.json \
     --embeddings ./vectors --text ./text [--model-cache-dir DIR]
   ```

   The job's committed summary, the output `bin/build-corpus report` lists,
   names the release by `release_artifact_hash`. The acquisition-pilot
   release is built the same way into the same `DIR2`/`DSN2`, with
   `--purpose acquisition_pilot` on both commands and its own
   `--release-id`.
5. Fit, calibrate, qualify and bundle the three heads:
   `bin/fit-heads --state DIR2 --dsn DSN2 --release <initial-fit release_artifact_hash> --pilot-release <pilot release_artifact_hash>`.
   Both releases are read by content hash from this `--state` and `--dsn`,
   the one schema step 4 built them into.
   It prints the qualification report path, the bundle id and file, the
   promotion decision path and the promoted targets. It activates nothing,
   makes no paid call and downloads nothing; a rerun on the same inputs
   resumes or replays the same job. `bin/activate-bundle --bundle <bundle
   file> --decision <promotion decision> --dsn DSN2 --artifacts
   DIR2/artifacts` activates the bundle it wrote.

Step 4 reads the `bin/embed-batch` output directly, not the step 3
namespace; step 3 is the agreement check that makes the batch safe to use.

## Restart (#151)

`openalex` is always scheduled ahead of `documents`: each family's citation
observation, and the labels it resolves, are claimed before the
`documents` backlog behind it, one family at a time, independent of
`--gate-on-labels`. A build already running when this ordering shipped
still queued its `documents` jobs ahead of any `openalex` job under the
old order; the operator expedites the one still queued back to the front
of the claim order on its next `_advance`, so a restart alone is enough to
pick up the new order without discarding queued work.

A build run as a restarting service (a `launchd` agent or equivalent) does
not need an operator to fail a job by hand after a storage request whose
response was lost: the acquisition worker resends that one request under
its identical idempotency key before giving up on it, so storage either
replays what it already committed or applies the request fresh
(`docs/implementation/source-pilot.md#Resumption`, #178). A killed build
otherwise resumes exactly as documented there — restart the same command
and the next claim continues from the last committed checkpoint.

The global citation-record cap is a configured run value, `--record-cap`,
defaulting to 100,000 like the committed 100-family pilot. A release run
that expects to exceed it restarts with the same command plus the larger
cap; resume is checkpointed, so already-committed jobs are untouched and
the queued jobs already in storage are unaffected by the flag:

```
bin/corpus-pilot run --state DIR --dsn DSN \
  --population-rule "<the owner's population rule from #66>" \
  --cap 10000 --seed <the owner's recorded seed> --per-month 0 \
  --gate-on-labels --record-cap 2000000
```

## Known limits

- The gate-out rate label-first gating measures in practice is not yet
  recorded here: no `--gate-on-labels` release population draw has run
  against the live arXiv/OpenAlex sources. This section gets that measured
  rate from the first release run that uses it.
- Only the `acquisition_pilot` purpose has an exercised, tested path end to
  end. The `initial_fit`/`initial_expansion`/`weekly_refresh` purposes are
  implemented against the same `CorpusRelease` contract and covered by pure
  tests, but the 2000/5000-candidate modeling selection they depend on is
  #65's future work, not built here.
- A release built without `--embeddings` and `--text` has no features:
  every row's `feature_hash` is `null` and `features_complete` is always
  false in the coverage report. This is the expected, disclosed state FT-18
  anticipates for an unqualified corpus: it supports acquisition and
  engineering, not serving.
- `bin/release-candidates` reads observations only from committed snapshot
  labels passes. The per-family API path (`openalex` jobs) publishes no
  observation (#332), so a family labeled that way is a candidate with no
  observation and unknown labels.
- The `CorpusRelease` contract fixes the selection seed at 20260920 and the
  intended population per purpose (acquisition pilot 100, initial fit 2000,
  expansion 5000). The candidate list carries the selection's own values,
  so a selection drawn with another seed or cap is refused when the release
  is assembled, after every row is built.
- The release worker claims any queued `label` job in its schema, so a
  `run` for one named release also finishes another left unfinished there,
  under the configuration of the command that claimed it.
- Like the source pilot's local operator, this one runs in a single local
  process with no container image and talks to storage directly through
  `JobRepository`/`ArtifactRepository` rather than over the deployed mTLS
  boundary: the storage HTTP layer's role-to-job-kind map
  (`storage/http.py#JOB_ROLE_KINDS`) does not yet admit the `label` kind to
  any role, and extending it is outside this slice's scope.
