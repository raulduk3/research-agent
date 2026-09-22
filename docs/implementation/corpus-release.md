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
# ... build a candidates.json from the pilot's committed selection ...
bin/build-corpus run --state DIR2 --dsn DSN2 \
  --population-rule "<the owner's answer on #66>" \
  --representation-hash <sha256 of the pinned embedding manifest> \
  --candidates candidates.json
bin/build-corpus report --state DIR2 --dsn DSN2 \
  --population-rule "..." --representation-hash <sha256>
```

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
`locked_evaluation_weeks`). Building it from a completed pilot run, and from
the acquisition and observation pipelines once they exist, is future work;
today an operator assembles it directly from what those pipelines have
already published.

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
- No feature pipeline exists yet (#70): every row's `feature_hash` is
  `null` and `features_complete` is always false in the coverage report.
  This is the expected, disclosed state FT-18 anticipates for an
  unqualified corpus: it supports acquisition and engineering, not serving.
- Like the source pilot's local operator, this one runs in a single local
  process with no container image and talks to storage directly through
  `JobRepository`/`ArtifactRepository` rather than over the deployed mTLS
  boundary: the storage HTTP layer's role-to-job-kind map
  (`storage/http.py#JOB_ROLE_KINDS`) does not yet admit the `label` kind to
  any role, and extending it is outside this slice's scope.
