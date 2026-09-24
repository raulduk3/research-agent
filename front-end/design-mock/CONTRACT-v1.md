# Front-end contract, version 1

Fixed 2026-09-23. `CONTRACTS.md` says what exists; this fixes how the front end and the backend
talk so each side can be built without waiting on the other. It is versioned, and version 1 is
frozen once its schemas land in the repository: a payload field is never renamed or removed in v1,
only added, and a breaking change is `/api/v2`.

## Transport

- Every application serves its JSON under `/api/v1/` beside its HTML routes, same handlers, same
  view models. The HTML is a rendering of the same object the JSON returns; a field the HTML shows
  that the JSON lacks is a bug.
- Auth is the session cookie the app already sets (`rater_session`, owner session), `SameSite=Lax`,
  `HttpOnly`. JSON `POST`s carry the session's CSRF token in `X-CSRF-Token`. There is no bearer
  token and no API key in the browser; there is nothing to leak.
- Requests that need a session and lack one get `401 {"error":{"code":"unauthenticated"}}`; a
  session on the wrong island or role gets `403 {"error":{"code":"forbidden"}}`.
- Responses are `{"contract":"1", "data": ...}` on success and
  `{"contract":"1", "error":{"code":<closed string>, "message":<text>, "field":<name>|null}}` on
  refusal. Codes are the storage service's own (`not_found`, `state_conflict`,
  `idempotency_conflict`, `refused`, `invalid`), never HTTP reasons re-worded.
- Lists are `{"items":[...], "next_cursor": <opaque>|null}`; the client sends `?cursor=` back
  verbatim. Order is the storage order, never re-sorted by the app.
- Types: ids are strings (UUIDv4 or hex hash); instants are UTC `YYYY-MM-DDTHH:MM:SS.ffffffZ`
  (the repository's one format) and the client renders local time; probabilities are floats in
  `[0,1]`; money is integer micro-dollars (`_micros`), never a float; enums are closed and listed
  here. Absent means absent: a gated field is omitted from the object, not `null`.
- Idempotency: every JSON `POST` carries a client-minted `Idempotency-Key` (UUIDv4); a replay with
  the same key returns the first outcome. This is how a flaky phone submits once.

## Endpoints

Rater app (session: rater, one island):

| Method, path | Data | Notes |
| --- | --- | --- |
| `POST /api/v1/login` `{credential}` | `{rater_id, island, csrf_token, expires_at}` | sets the cookie; one field, no username |
| `POST /api/v1/logout` | `{}` | clears the cookie |
| `GET /api/v1/digest` | `{batch_id, island, published_at, closes_at, entries[BlindedEntry], rated[Rating]}` | today's digest for the session's island; `closes_at` is the rating window's end |
| `GET /api/v1/digest/{batch_id}` | same | an earlier day |
| `POST /api/v1/ratings` `{digest_entry_id, paper_hash, value}` | `Rating` | `value ∈ {like, skip}` -- accept or pass, the only two calls any page offers; storage's `dislike` is reserved and never sent; one per entry per rater; `409 state_conflict` on a second |
| `GET /api/v1/entries/{digest_entry_id}` | `BlindedEntry & Disclosure?` | disclosure present only after the session's accepted rating |
| `GET /api/v1/ratings?batch_id=` | `{items[Rating]}` | the session rater's own ratings (progress, accepted list) |
| `GET /api/v1/credit?week=` | `{iso_week, items[{rating_id, genome_hash, share}], total}` | what your calls did; no running score |
| `GET /api/v1/runs/{run_id}` | `Run & {events[Event]}` | an agent's reading, after the rater's rating on that paper |
| `GET /api/v1/papers/{paper_hash}/life` | `{days[{day, in_digest, reads[{run_id, configuration_id, started_at}], mentions[{run_id, kind, at}]}]}` | every day the paper was sent, read or mentioned, for the paper page's Life screen; gated like the conversation |
| `POST /api/v1/forecasts` `{question_id, probability, note?}` | `HumanForecast` | see Decisions; sealed at send, immutable |

Owner app (session: owner):

| Method, path | Data |
| --- | --- |
| `POST /api/v1/login`, `POST /api/v1/logout` | as above, owner principal |
| `GET /api/v1/configurations?cursor=` | `{items[Configuration], next_cursor}` |
| `GET /api/v1/configurations/{id}` | `Configuration & {runs[Run], runs_cursor, forecasts[Forecast], forecasts_cursor, admission, retirement}` |
| `POST /api/v1/configurations/{id}/admit` `{lineage_id, prompt, scan_policy, read_policy, probability_assignment_rule}` | `OwnerActionResult` |
| `POST /api/v1/configurations/{id}/retire` | `OwnerActionResult` |
| `POST /api/v1/configurations/seed` `{island, lineage_id, template_configuration_id, prompt, scan_policy, read_policy, probability_assignment_rule}` | `OwnerActionResult` |
| `GET /api/v1/runs?batch_id=&cursor=` | `{items[Run]}` (the globe, the swarm replay, the runs index in one call) |
| `GET /api/v1/runs/{id}` | `Run & {events[Event], submissions[Submission]}` |
| `GET /api/v1/reports?island=` | `{items[{island, iso_week, frozen_at}]}` |
| `GET /api/v1/reports/{island}/{iso_week}` | `IslandReport` |
| `GET /api/v1/manifests` | `{items[{manifest_hash, kind, created_at}]}` |
| `GET /api/v1/manifests/{hash}` | `Manifest` |
| `GET /api/v1/costs?day=` | `Costs` (see Decisions) |
| `GET /api/v1/health` | `{state, checked_at, checks[{name, state, detail}]}` from `HealthMonitor` |
| `GET /api/v1/digests/{hash}` | the digest with provenance, but a row for a paper the owner has not rated omits the agents' chance (the owner is also a rater) |

Schemas: one JSON Schema per object in `docs/contracts/api-v1/` in the repository, and a test per
endpoint that validates a real response against it. The schemas are the freeze.

## Screens

A paper page is five screens, one on screen at a time, chosen by the hash: `#paper` (the paper and
your call), `#conversation` (one turn per reader), `#reads` (each recorded run, played back),
`#analyst` (the fixed summarizer's reading and the baselines), `#life` (the days it was read or
mentioned). A question page is the same five with `#question` first. Everything but the first is
served only after the session's call on that paper (SR-25); the JSON for a locked screen is `403`.
A reading page is one run's replay with previous/next links inside its paper's reads.

## Objects

`BlindedEntry {paper_hash, digest_entry_id, title, abstract, published_on}`;
`Disclosure {probability, rationale, popularity_count, jev, reading}` (all five or none);
`Rating {rating_id, digest_entry_id, paper_hash, value, rated_at}`;
`HumanForecast {forecast_id, question_id, probability, note, sealed_at, horizon, resolution?}`;
`Configuration`, `Run`, `Event`, `Submission`, `Forecast`, `IslandReport`, `Manifest`,
`OwnerActionResult`: the records in `CONTRACTS.md`, field for field;
`Costs {day, month, spent_today_micros, spent_month_micros, daily_cap_micros, monthly_cap_micros,
jev_today_micros, jev_daily_cap_micros, funded, paid_execution_enabled,
by_island[{island, micros, runs}], by_genome[{genome_hash, micros, runs, skill_per_dollar}],
source}` where `source ∈ {settlements, model_call_events}` says what the numbers are computed from.

## Decisions, and why

Each of these is the owner's call delegated on 2026-09-23; each is recorded as an issue so it can be
reversed by number. The test applied to every one is the mock's own review
(`REVIEW-evil-by-design.md`): a pattern is fair when the outcome is the reader's and they would
agree with the means if they saw them.

1. **Two calls, accept or pass, and a rating is one immutable record whose commit is the POST.**
   Every page offers the same two buttons and nothing else; storage's third value (`dislike`) is
   reserved and no page sends it. A rating cannot be changed once sent: storage refuses a second
   (`state_conflict`), and no page offers one. The way out is before the record: a button starts a
   visible three-second send with cancel inside the card; a swipe takes the card away and leaves the
   word and a cancel in its slot; on commit the card leaves the list for "Rated earlier today".
   Changing a rating afterwards is the intended next step, not v1: #260 holds it, as append-only
   supersession with the latest counting, so that when it lands nothing here is renamed.
2. **The reader's own forecast is a first-class, sealed record, not a rating with a number.** The
   question card is the one thing on Today that asks the reader to think rather than react, and it
   is worth keeping. It is stored as `HumanForecast`, sealed at send like the agents' claims, judged
   by the same resolver at the same horizon, and never an input to any head, baseline or selection
   (the RD-21 shape, applied to people). Optional, skippable with nothing recorded, no default value
   on the slider, the number shown, submit disabled until the slider is touched, no gesture on the
   card. `note` is free text the reader keeps and nobody scores. The reading guide (#196) shows the
   paper's own sections, never the agents' evidence, before the answer. Closes #196, #197 and #198
   with one record.
3. **Settings is an owner cost dashboard, and raters have no settings.** PL-22 gives a rater an
   island and a credential and nothing to configure; a settings page for them is an empty room, and
   an empty room invites features. The owner has real state to watch: spend against the USD 8 per
   day and 200 per month caps, the Jev sublimit, whether paid execution is enabled and funded, and
   spend per island and per genome beside skill per dollar (#159). That is `costs`, owner-only, and
   it is where the budget line the review took off the rater's Today goes. Until a settlement
   record exists, the numbers derive from `model_call` run events and the page says so (`source`).
4. **Nothing on a rater page compares the rater to a hidden set while they work.** The agents-vs-
   random accept rate stays on the report and the owner home. Credit shows on `impact` as plain
   sentences, no numerals in green, no day-by-day, no streak, and the API serves no per-rater
   running score (`/credit` returns shares, not a total the client is told to celebrate).
5. **Loss language is out; arithmetic is in.** State lines are `accepted · +1`, `pushed away · −1`,
   `passed · 0`, identical for controls, with the rule explained once on `impact`.
6. **Times are the reader's.** The API sends UTC instants only; the client renders local time and
   "in 2 h" beside a closing time. The one deadline, the question's, is shown as information, with
   no countdown animation.
7. **Accepted stays per island** (#199 answered no): a rater is bound to one island; a shared view
   would need cross-island reads that the blinding does not permit and that nobody asked for.
8. **The owner's leak is closed server-side.** `GET /api/v1/digests/{hash}` omits the agents'
   chance and agreement for any paper the owner has not rated, since the owner is also the cs
   rater. Server-side, so no front end can undo it.
9. **Inspector reads ride the owner session.** A browser cannot hold the inspector certificate, so
   the population, agent, run and manifest reads are owner-app routes; the inspector app stays for
   certificate-holding tools.

## Guards the server keeps, whatever the client does

- Disclosure fields absent before rating; `jev` never in a pre-rating object (SR-25, RD-21).
- No `origin`, no `genome_hash` on a blinded entry, ever (SR-21, SR-22).
- One rating per entry per rater; `409` on a second; nothing is ever deleted.
- A `HumanForecast` seals at send; no update route exists.
- The owner's unrated papers carry no agents' chance.
- Rate limits per session on `POST`s, so a script cannot rate a batch in a second.
