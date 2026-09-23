# Source acquisition pilot harness

This implements the acquisition part of #82 under #65. It captures sources. It
does not extract text, resolve labels, embed papers or qualify any source.

## Owners

| Concern | Owner | Tests |
| --- | --- | --- |
| arXiv listing query, parser and v1 document paths | `ingest/arxiv.py` | `tests/ingest/test_arxiv.py` |
| Bounded HTTPS GET, OpenAlex citation and arXiv-DOI match queries | `ingest/fetch.py` | `tests/ingest/test_fetch.py` |
| Outcome-independent selection by arXiv id, cross-lists included | `learning/corpus.py#select_pilot` | `tests/learning/test_corpus.py` |
| Resumable capture worker | `ingest/pilot.py#PilotWorker` | `tests/integration/corpus/test_pilot_resume.py` |
| Local storage service and operator | `ingest/pilot_local.py`, `ingest/pilot_run.py`, `bin/corpus-pilot` | same |
| Checked access rules | `docs/evidence/source-pilot/access-rules.md` | hashed into every request record |

## Stages

Each stage is a `capture` job whose input manifest is a stage specification.
The operator enqueues a stage once its prerequisites have committed.

1. **Listing**, one job per OAI set (`cs:cs:AI`, `cs:cs:LG`). It requests
   every page of arXivRaw records modified from the first mature month through
   the freeze date. Datestamps are last-modified dates, so this covers every
   paper first submitted in the window. Each page is retained with its request
   record, and the continuation token is the checkpoint cursor. A failed page
   or expired token fails the job. The operator starts a fresh listing for
   that set, at most three times.
2. **Select** reads every retained page back through storage, keeps families
   whose categories include cs.AI or cs.LG, and applies `select_pilot` with
   the frozen instant. Its report lists the selected families with v1 time,
   categories, license URL, DOI, title and abstract. It also records eligible
   counts and shortfalls per month and a hash of the whole eligible
   population.
3. **Documents**, one job per selected family. It requests `/src/<id>v1` and
   `/pdf/<id>v1` and nothing later. Each retained document carries the paper's
   own license URL. A missing source archive is recorded as `not_found`.
4. **OpenAlex**, one family at a time. It looks up the Work with the exact
   arXiv DOI `10.48550/arXiv.<id>`, then pages its incoming citations. The job
   ends `unmatched`, `ambiguous`, `complete`, `incomplete` (a failed page),
   or `capped` (the global 100,000-record cap). A 429 stops the run; the job
   resumes at the same cursor later.
5. **OpenAlex snapshot**, instead of stage 4 once `--snapshot-release` and
   `--snapshot-parts` name a release of the works table (#223). It reads the
   table once for the whole corpus, not once per family, in jobs of 64
   contiguous parts that checkpoint after every part. A job's parts are read
   through a bounded parallel gate, at most `SNAPSHOT_PARALLELISM` (sixteen,
   the pacing rule fixed in `docs/evidence/source-pilot/openalex-snapshot.md`)
   in flight at once, but each part still publishes and checkpoints in key
   order regardless of which finishes reading first (#225).
   `openalex_snapshot_match` reads `id` and `doi` to find each family's Work
   by the same exact arXiv DOI. `openalex_snapshot` then reads the reference
   columns and keeps every edge landing on any matched Work. Last,
   `openalex_snapshot_labels` commits one observation per family, dated by
   the release. A matched family nothing cites gets an observed zero over a
   complete pass. A family already sent to stage 4 keeps it, so the two never
   both run for one family. A failed range read fails its job and holds the
   pass until `requeue --stage <stage>` runs that range again.

## Resumption

The worker checkpoints after every unit (page, document, citation page),
naming the unit's retained artifacts as outputs. After a kill, the next claim
returns the committed checkpoint. The worker restores its completed keys,
cursor and outputs and continues with the next request. Command ids derive
from the job and payload hash, so a retried publish replays its original
response. An uncheckpointed request can be repeated once after a kill; its
earlier response is retained under the job but is not an output.

A single storage request whose outcome a transport failure leaves unknown —
the response was lost, not necessarily the command — is resent once with its
identical idempotency key and content before the worker gives up on it
(#178): storage either replays the response it already committed or applies
the request fresh, so it never refuses the resend as a changed-content
conflict. A worker run as a restarting service no longer has to crash and
reclaim the job over a single lost response; it resumes in place.

Storage records which job lease produced each artifact (migration 0004), so a
job can name its own outputs in a checkpoint or report. No other job's scope
reaches them.

## Known limits

- t0 is the v1 submission time from arXivRaw. Announcement can follow by a few
  days, so a paper submitted on a month's last day can belong to the next
  month by announcement date.
- Matching uses only the arXiv DOI. A journal version is usually a separate
  OpenAlex Work, so citations to it are not counted. The report shows match
  outcomes; it does not correct for this.
- The local run has no container image. Its producer identity names a local
  process, and the storage service runs in-process on loopback with the
  administrative database connection, not the separated production roles.
- Name resolution is outside the fetch deadline (#91).
- arXiv continuation tokens expire at the next midnight UTC. A listing still
  running then fails and restarts from its first page. The pilot listing
  runs at about 5 seconds per 1,300-record page, well inside a day. The
  2,000-candidate stage should split the listing into date windows so an
  expiry repeats only one window.
