# Data contracts: what the backend serves each page, and how

Written 2026-09-23 against `loop/2026-09-23` (develop `43d4c1e` plus the day's folds: #139 owner
actions, #140 weekly report and preference credit, #234 owner routes). This is the page-by-page
account of what a real front end gets from the running system. The mock's design, styles and
presentation rules (`ALIGNMENT.md`) are unchanged by it; this says what feeds them.

The rule that shapes everything below: **a browser never talks to storage.** The storage service
(`storage/http.py`) authenticates its callers by mTLS certificate and role (`inspector`, `owner`,
rater app, agent worker), and a browser holds no such certificate. The four web applications are the
backend for the front end; each holds one client certificate and a session store, and each page's
payload is a view model those apps already build. The React front end is those four apps' routes
answered as JSON instead of HTML.

## The backend

| Application | Module | Session | Routes |
| --- | --- | --- | --- |
| Rater | `web/app.py` | `rater_session` cookie, 24 h, one island (PL-22) | `GET/POST /login`, `GET /`, `POST /ratings` |
| Inspector | `web/inspect/app.py` | none: mTLS `inspector` role | `GET /agents`, `GET /agents/{configuration_id}`, `GET /runs/{run_id}`, `GET /models/{manifest_hash}` |
| Owner | `web/actions/app.py` | owner session cookie, CSRF | `GET/POST /login`, `POST /logout`, `GET /`, `GET /agents/{id}`, `POST /agents/{id}/admit`, `POST /agents/{id}/retire`, `GET/POST /seed` |
| Report | `web/report/app.py` | none yet | `GET /reports/{island}/{iso_week}` |

Every page they render is composed from these `StorageClient` reads, which are the whole read surface
a front end can ever see:

| Read | Returns | Storage route, role scope |
| --- | --- | --- |
| `read_digest_for_rater(island, batch_id)` | the sealed digest for one island and batch: entries with `paper_hash`, `digest_entry_id`, `title`, `abstract`, `genome_hash`, `origin` | `GET /v1/digests`, `digests:read` |
| `read_digest_with_provenance(digest_hash)` | the same with nominations and origins, for the owner | `GET /v1/digests/{hash}` |
| `read_run(run_id)` | the run record plus its ordered events | `GET /v1/runs/{id}`, `runs:read` |
| `list_runs_by_configuration(configuration_id, cursor)` | runs, newest first, with `next_cursor` | `GET /v1/runs?configuration_id`, `runs:read` |
| `list_submissions_by_submitter(submitter_id)` | a run's sealed submissions (answers and nomination) | `GET /v1/submissions?submitter_id`, `submissions:read` |
| `list_configurations(cursor)` | the population, with `next_cursor` | `GET /v1/configurations`, `configurations:read` |
| `read_configuration(configuration_id)` | one genome record | `GET /v1/configurations/{id}` |
| `list_forecasts_by_configuration(configuration_id, cursor)` | sealed claims paired with their resolution where one exists | `GET /v1/configurations/{id}/forecasts`, `forecasts:read` |
| `read_manifest(manifest_hash)` | a published manifest (bundle, refresh, release) | `GET /v1/manifests/{hash}`, `manifests:read` |
| `read_artifact(hash)` | immutable bytes by content hash | `GET /v1/artifacts/{hash}`, `artifacts:read` |
| `read_genome_view`, `admission_history`, `retirement_status`, `retrospective` | the owner's view of one genome and what was done to it | owner routes (#234), `owner` role |
| `list_raters()` | provisioned rater principals, for the operator | `GET /v1/raters`, `raters:read` |

Writes a front end may cause: `record_rating` (`POST /v1/ratings`, value `like`, `dislike` or `skip`)
through the rater app; `admit_edited_genome`, `seed_variant`, `retire_genome` through the owner app.
Nothing else. Agents, resolvers, the scorer and the digest builder write everything else, and no
page gives a human a way to write into their records (AG-06, EN-16, AuthorityPolicy).

## Records

The shapes below are what the reads return today (`storage/queries.py`). Field names are the contract;
a front end renders human names over them and keeps the ids (the presentation rule in `ALIGNMENT.md`).

**Configuration** (`_genome_fields`): `configuration_id`, `configuration_hash`, `lineage_id`,
`island`, `founder`, `infra_hash`, `parent_hash`, `parts[{part, value, value_hash}]` (the four
AG-20 emphasis parts), `admission{disposition, profile_hash}`, `admitted_at`,
`archive{cycle_id, skill, resolved_claim_count, profile_hash, archived_at} | null`.

**Run** (`_run_fields`): `run_id`, `batch_id`, `paper_id` (one run reads one paper, decision 0022),
`configuration_id`, `attempt`, `genome_hash`, `seed`, `snapshot_hash`, `budgets`, `allowed_tools`,
`model_identity`, `checkpoint_dates`, `created_at`, and `events[{attempt, ordinal, kind,
payload_hash, recorded_at}]`. An event's payload is an artifact: `read_artifact(payload_hash)`.

**Submission** (`contracts/submissions.py`): `submission_id`, `run_id`, `sheet_hash`, `submitter_id`,
`answers[{question_id, probability, rationale, evidence_ids}]` (five registry questions per run,
#210), `nomination{paper_id, recommend, preference, rationale}` (the run's own paper).

**Forecast** (`_forecast_fields`): `submission_id`, `run_id`, `question_id`, `confidence`,
`horizon`, `sealed_at`, `resolver_id`, `resolver_version`, `resolution{resolution_id, status,
resolver_id, resolver_build_digest, resolution_version, resolved_at} | null`. A claim with no
resolution is pending until its horizon; nothing computes a verdict on the page. No Brier
contribution is stored yet, and the page says so rather than compute one (#177 ruling).

**Blinded digest entry** (`web/projections.py#BlindedPaperView`): `paper_hash`, `digest_entry_id`,
`title`, `abstract`. Nothing else, ever, before a rating: origin (agent or control) is blinded
permanently (SR-21, SR-22).

**Rating disclosure** (`RatingDisclosure`): after the rater's accepted rating on that entry, and only
then, all five together: `probability`, `rationale`, `popularity_count`, `jev`, `reading`. Omitted
from the payload before rating, not nulled (SR-25). `jev` is the RD-16 assessment, admitted under
decision 0024 and excluded from every pre-rating view (RD-21).

**Rating** (`record_rating`): `rater_id` (from the session), `paper_hash`, `digest_entry_id`,
`value ∈ {like, skip}` (accept or pass; `dislike` exists in storage and no page sends it), plus command and idempotency ids the app mints. Result
(`RatingOutcome`): `accepted`, `rating_id`, `rated_at`, `reason`.

**Island report** (`measurement/weekly.py#IslandReport`): `island`, `iso_week`,
`rows[{genome_hash, founder, skills[{target_id, skill, support_count, disposition}],
preference_credit, credited_entries}]`, `preference_reason`, `comparisons[{comparator,
population_likes, population_decided, comparator_likes, comparator_decided, population_rate,
comparator_rate, weeks, interval, verdict}]`. Targets are the registry's: `citation_reach_365d`,
`citation_count_180d`, `late_citation_activity_365d`, `rater_like_7d`, `early_citation_rank_60d`,
`venue_180d` (decision 0023).

**Owner action result** (`OwnerActionResult`): `disposition`, `configuration_id`, `reason`; the
admit form carries `lineage_id`, `prompt`, `scan_policy`, `read_policy`,
`probability_assignment_rule`; seed adds `island` and `template_configuration_id`; retire is the
`csrf_token` alone. Edit-and-admit returns `cycle_disabled` until a completed weekly cycle count is
supplied (AG-06 guard).

## Sessions

- **Rater login** is one field, `credential`; the principal is whichever provisioned rater that
  credential hashes to (PBKDF2, 200,000 rounds, per-principal salt). No username, no email. The
  session cookie `rater_session` lives 24 hours and binds the rater to one island; every POST carries
  the session's `csrf_token`. The mock has no login page; it needs one, and it is this form.
- **Owner login** is the same shape against `owner_principals`, with `POST /logout`.
- **Inspector** has no login: the app is reached under an `inspector` certificate. A browser cannot
  present that, so the front end's owner-side pages (population, agent, run, model) go through the
  owner app's session, which reads the same views. That is one decision to record before the React
  build starts (see Gaps).

## JSON

The proposal, one small change per app: every `GET` above answers `Accept: application/json` with the
view model it already builds, serialized as-is; every `POST` answers the outcome record. No new
payloads are designed for the front end -- the view models are the contract, and a page that needs a
field the view model lacks is a change to the view model, cited to a requirement, not a second API.
Pagination stays what it is: an opaque `next_cursor` echoed back as `?cursor=`.

## Pages

Status: **built** (route and view exist on the day branch), **decision** (the page draws something
an open decision has not admitted), **gap** (no read exists for it yet).

### Rater-facing (the Atoll app: `web/app.py`)

| Page | Route | What it draws from | Status |
| --- | --- | --- | --- |
| `login` (`login.html`; owner: `owner-login.html`) | `GET/POST /login` | the credential form above | built |
| `index` today's picks: the paper feed, accept / pass | `GET /` → blinded digest; `POST /ratings` value `like` / `skip` | `BlindedPaperView` per entry; `RatingOutcome` | built |
| `index` "a question for you": the rater's own forecast, slider and note | none | ratings carry `like` / `dislike` / `skip` only; no record holds a rater probability or a note | decision: #196 (reading guide), #197 (dismissed state), #198 (rater note); a rater-forecast record is a new decision |
| `index` "9 of 12 left", progress | `GET /` entries minus the rater's ratings on them | needs the rater's own ratings for the batch, which no read returns | gap: a rater-scoped ratings read |
| `index` hero globe: 594 papers, 12 agents, what each read | runs of the batch and their events | `list_runs_by_configuration` for each of 12 configurations, `read_run` for events | built, expensive; a batch-scoped runs read would make it one call |
| `liked` accepted list | the rater's `like` ratings and their entries | same rater-scoped ratings read | gap; #199 for the shared view across islands |
| `paper-P*` a paper as five screens: paper and call, conversation, reads, analyst, life | `GET /` entry plus `RatingDisclosure` once rated; runs by paper for the reads; `papers/{hash}/life` | `probability`, `rationale`, `popularity_count`, `jev`, `reading`; runs and events; the life days | built except the life read, a gap (#253) |
| `reading-P*-*` one agent's reading of a paper | `read_run(run_id)` events, `read_artifact` per payload | tool calls, reads, the sealed answer | built (events) |
| `question-Q*`, `questions` the human forecast questions | the sealed sheet's questions | sheets are sealed by `POST /v1/sheets`; no read returns a sheet's questions | gap: a questions read; the answer side is the decision above |
| `impact` what your ratings did | `PreferenceCredit` rows for this rater | persisted by #140 (`storage/preference.py`); no rater-scoped read | gap |
| `about` | static | -- | built (static) |
| `costs` (was `settings`) | `GET /api/v1/costs` (owner) | spend against the caps, per island and per genome; a rater has no settings under PL-22 | decision recorded in CONTRACT-v1.md; read is a gap |
| footer "all systems normal" | none | `platform/health.py#HealthMonitor` exists; nothing serves it | gap: a health read, owner-side |

### Owner-facing (`web/actions/app.py`, `web/inspect/app.py`, `web/report/app.py`)

| Page | Route | What it draws from | Status |
| --- | --- | --- | --- |
| `overview` owner home | `GET /` (owner) | composed: population, latest batch, reports | built as a page; the numbers on the mock are several reads |
| `agents` the population | `GET /agents` | `PopulationView`: configurations, `next_cursor` | built |
| `agent` one genome: parts, admission, archive, runs, forecasts and verdicts, owner actions | `GET /agents/{id}` (inspector view + owner view); `POST admit` / `retire`; `GET/POST /seed` | `AgentView`, genome view, admission history, retirement status | built |
| `runs` index | none | only `list_runs_by_configuration` | gap: a batch-scoped or global runs read |
| `run` one run: events, submissions | `GET /runs/{run_id}` | `RunView`: run + events, submissions | built |
| `islands`, `island` | `GET /agents` grouped by `island`; `GET /reports/{island}/{week}` | configurations, `IslandReport` | built (derived) |
| `reports`, `report` weekly island report | `GET /reports/{island}/{iso_week}` | `IslandReport` | built; an index of available weeks is a gap |
| `models`, `head` one prediction head | `GET /models/{manifest_hash}` | `ManifestView` | built; an index of manifests is a gap |
| `swarm` replay of a batch | runs and events of the batch | as the hero globe | built (events); the replay level itself is decision #208 |

## Gaps, as the issues they become

1. (#252) Rater-scoped reads: the rater's own ratings for a batch (progress, accepted list, impact),
   `PreferenceCredit` by rater. One storage read each, `raters:read` scope, rater app routes.
2. (#253) A batch-scoped runs read (`/v1/runs?batch_id`) so the globe, the runs index and the swarm replay
   are one call, not twelve; and a paper-scoped one (`/v1/runs?paper_id`, plus mentions from events) for a
   paper's life.
3. (#253; the answer is decision #250) A questions read for a sealed sheet, so question pages exist; the rater's own answer is a
   decision (a new record, or `skip` with a note under #198), not a read.
4. (#253) Indexes: manifests, report weeks.
5. (#254) A health read for the footer, from `HealthMonitor`, owner-side.
6. (#249) JSON on the existing routes, one change per app.
7. (#255) Inspector views behind the owner session, so a browser can reach them.
8. Login pages: done in the mock (`login.html`, `owner-login.html`).

The owner cost dashboard is #251. None of these changes what a page shows; they make what the mock already shows reachable.
