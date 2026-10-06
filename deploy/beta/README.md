# Swarm beta backend

One small FastAPI process over one SQLite file. It ingests current arXiv papers, assigns them to islands, lets each island's agents read one paper per run, keeps every run as a replayable event trace with cost receipts, holds the month to a budget, and answers chat from the stored data.

The idea the surface is built around: **you edit the agents and you watch the runs.** Nobody starts work by sending a prompt. An idle agent takes the next unread paper from its island's queue; agents and islands with fewer runs take their turns first; the budget decides how much happens. Evolution, when switched on, edits the agents too: it keeps the best and tries one mutated child.

Source: `src/research_agent/beta/`. It imports nothing from the earlier platform packages.

## Run it

Local, from the repository root, with the locked environment (`uv sync --locked`):

```sh
export RESEARCH_AGENT_ISLAND_PASSWORDS="cs:$CS_CODE"   # the code you will type to enter the cs island
uv run --locked python -m research_agent.beta serve --port 8000
```

On a VPS, as a container:

```sh
docker build -f deploy/beta/Dockerfile -t swarm-beta .
cp deploy/beta/.env.example /etc/swarm-beta.env    # then fill it in
docker run -d --name swarm-beta --restart unless-stopped \
  --env-file /etc/swarm-beta.env -p 127.0.0.1:8000:8000 \
  -v swarm-data:/var/lib/swarm swarm-beta
```

Put a TLS-terminating reverse proxy (Caddy, nginx) in front of `127.0.0.1:8000`.

Or bring up the API and a TLS proxy together. Point the API's DNS name at the server first, set `API_HOST` and the rest in `deploy/beta/.env`, then:

```sh
docker compose -f deploy/beta/compose.yaml up -d --build
docker compose -f deploy/beta/compose.yaml logs -f api      # watch it start
curl https://$API_HOST/health
```

The proxy obtains and renews the certificate for `API_HOST` on its own. The database lives in the `swarm-data` volume. The image holds the beta package and its fifteen pinned dependencies; it has no PostgreSQL, numerical or model stack.

Without a container: create a Python 3.12.12 virtual environment, `pip install --require-hashes -r deploy/beta/requirements.txt`, set `PYTHONPATH=src`, load the environment file and run `python -m research_agent.beta serve --host 127.0.0.1 --port 8000` under systemd.

`deploy/beta/requirements.txt` is the beta's dependency closure at the versions `uv.lock` pins. Regenerate it after a lock change:

```sh
uv export --locked --no-dev --no-emit-project --no-hashes | grep -v pytorch > /tmp/constraints.txt
printf 'fastapi\nuvicorn\nhttpx\n' > /tmp/beta.in
uv pip compile /tmp/beta.in -c /tmp/constraints.txt --python-version 3.12 --universal \
  --generate-hashes --no-header --no-annotate -o deploy/beta/requirements.txt
```

### Environment

Every variable is listed with its meaning in [`.env.example`](.env.example). The ones that matter first:

| Variable | Purpose |
| --- | --- |
| `RESEARCH_AGENT_BETA_DB` | Path of the SQLite file. |
| `RESEARCH_AGENT_SESSION_SECRET` | Signs session tokens. Set it, or every restart signs everyone out. |
| `RESEARCH_AGENT_ISLAND_PASSWORDS` | `island:credential` pairs, one distinct credential per island. |
| `RESEARCH_AGENT_OPERATOR_TOKEN` | The operator's credential and bearer token. |
| `RESEARCH_AGENT_ALLOWED_ORIGINS` | Exact front-end origins for CORS. No wildcard. |
| `RESEARCH_AGENT_MODEL_*` | Endpoint, key, model id and both prices. All five or none. |
| `RESEARCH_AGENT_INGEST_SECONDS`, `RESEARCH_AGENT_TICK_SECONDS` | How often the process ingests and advances by itself. Unset, it ingests every 600 seconds and advances every 60; zero is off. |

The model provider is one OpenAI-compatible chat-completions route. Nothing about it is assumed: with no provider variables the app serves stored data and refuses runs with `503 unavailable`; with only some of them it refuses to start. Prices have no defaults because receipts and the budget are computed from them.

### Operator commands

The same database can be driven without the API:

```sh
python -m research_agent.beta migrate            # create or update the store
python -m research_agent.beta ingest             # one arXiv pass, then advance
python -m research_agent.beta advance            # idle agents take their next papers
python -m research_agent.beta evolve [--force]   # run evolution where it is due
python -m research_agent.beta budget             # print the budget state
python -m research_agent.beta spec export        # the editable swarm spec as JSON
python -m research_agent.beta spec apply f.json  # apply one as a new revision
```

The serving process does the first two on its own at the cadence `RESEARCH_AGENT_INGEST_SECONDS` and `RESEARCH_AGENT_TICK_SECONDS` set (a paper every ten minutes and a tick a minute unless told otherwise), so no cron is needed.

### Backup

Everything durable is the one SQLite file (WAL mode). Take a consistent copy while the server runs:

```sh
sqlite3 /var/lib/swarm/swarm.sqlite3 ".backup '/backups/swarm-$(date +%F).sqlite3'"
```

## How it works

**Islands, agents, genomes.** An island is a research group with categories, keywords, a reading mode, a priority and a share of the budget. An agent is a genome seated on an island, addressed `genome@island` (`cs-reader@cs`). A genome is the agent's configuration: prompt, model settings, allowed tools, reading strategy, scoring preferences, plus a managed `version` and `lineage`.

**The swarm spec.** Islands, genomes, the budget levers and the evolution settings are one JSON document. Every edit validates the whole document and appends a revision; nothing is updated in place or deleted. A run stores the revision and genome version it ran under and a copy of that genome, so editing an agent never changes a past run. Any revision, and any agent version, can be restored, which appends a new revision with the old content. Islands and agents are switched off (`archived`, `active: false`), never removed.

**Runs.** A run is one agent reading one paper. It records an immutable event per step: `run_started`, `prompt`, `model_call`, `tool_call`, `paper_read`, `note`, `reading_submitted`, `run_completed` or `run_failed`. Each event is committed as it happens, carries a link to its cost receipt when it was paid work, and may carry a paper locator (`paper_id`, `source_kind`, `section`, `passage_id`, `page`, `char_start`, `char_end`, `quote`). The run page replays the events in `seq` order; `?after=<seq>` returns only newer events, which is how a page watches a live run. There is no separate timeline.

The harness controls a run through structure: which tools are offered, a cap on model calls, tool calls and output tokens, and a per-run cost cap. On the last model call only `submit_reading` is offered. A model that reasons before it answers spends that reasoning out of its output allowance, so every call is given at least 2,500 output tokens and a submission at least 4,000, whatever the genome or the `max_output_tokens` lever asks for; the per-run cap still bounds the cost. When the last submission is cut off, malformed or rejected, the run gets one more submission-only call, told what was wrong. A run that still ends without a reading says why: `output_truncated`, `no_reading_submitted`, `submission_rejected` or `model_call_limit`. A refused tool call tells the model why, not just a code. `paper_text` finds a passage by its full id, its kind (`abstract`) or the end of its id, and an empty id means all of them. What the harness tells the model between calls is recorded on the next `model_call` event as `harness_notice`.

An island reads within its own pool: `related_papers`, the related-work shortlist in the prompt and `cited_paper_text` see only papers assigned to the agent's island. A cited paper an agent reads through `cited_paper_text`, stored already or fetched from arXiv, is assigned to that island (`cited_by_run`), which is how an island brings a paper in. Chat is scoped to the session's island the same way.

Tools: `paper_text`, `related_papers`, `cited_paper_text`, `capture_note`, `feedback_context` (selected papers and recent conclusions from this island), `cost_state`, `submit_reading`. A call to a tool the genome does not allow is recorded as refused and does nothing. A submitted reading must carry `summary`, `keep` (whether the island should select the paper), `claims`, `objections`, `related_papers` and `idea_seeds`; each claim carries the agent's `stance` toward the paper (`positive` credits its contribution, `neutral` describes, `negative` doubts or limits it); a claim that depends on the paper text needs a quote, and each quote is checked against the stored text and marked verified or not.

Ingestion rotates the first category on each pass, recording that order so a restart preserves the next turn. Partly read cohorts are scheduled before untouched arrivals. Each category gets a share of the pass's admission cap. Requests scan at least twenty newest entries; unchanged papers do not consume admission slots, so repeated feed heads do not prevent the rest from entering.

A failed reading is eligible for another automatic attempt after fifteen minutes, up to three attempts per paper and genome version per UTC day. Completed readings are not repeated. Every attempt keeps its trace and receipts, counts toward the hourly and daily run caps, and must fit the remaining budget. The next UTC day permits another bounded set of attempts, so a prolonged provider outage does not permanently stop a reader. Editing a genome also permits another set. On startup, automatic releases caused by missing failed readings are reopened; human releases stay in force.

**Stored text.** Every paper starts with its arXiv abstract, kept as one passage with character offsets. Each ingestion pass then looks for the paper's HTML version on arXiv (converted from its LaTeX source, so no PDF parsing or OCR is involved) and stores its sections and subsections as further passages, split at paragraphs into parts of at most 3,500 characters, with titles. Mathematics is kept as its LaTeX source; the bibliography and footnotes are left out. A paper is looked for once per version; one without an HTML version keeps its abstract and records why (`no_html_version`, `html_without_sections` or `html_fetch_failed`). Text short enough (6,000 characters) is placed whole in a run's prompt; otherwise the prompt carries an outline of the passages, and `paper_text` returns about 5,000 characters a call and names what it left out. Locators are of kind `abstract` or `section`; `page` is null, because the HTML has no pages.

**Costs.** Every paid or scarce action writes one receipt: `ingest` (an arXiv request, amount zero), `model_call`, `chat_retrieval` (amount zero), `chat_answer`. Receipts are append-only leaf charges in whole micro-dollars; every total on every page is a sum of receipts. A model call that fails after the request left gets an `unsettled` receipt at its estimate: excluded from settled totals, held against the budget.

**Budget.** The levers are part of the spec and editable by the operator:

| Lever | Default | Meaning |
| --- | --- | --- |
| `monthly_budget_micros` | 50,000,000 | The month's ceiling: 50 USD. |
| `daily_soft_micros` | derived | Monthly budget over the days of the month. |
| `daily_hard_micros` | derived | Twice the daily soft budget. |
| `per_run_max_micros` | 50,000 | Most a single run may be estimated to cost. |
| `per_chat_max_micros` | 5,000 | Most a model-written chat answer may be estimated to cost. |
| `papers_per_pass` | 4 | Papers one ingestion pass may admit, shared across rotating category feeds. |
| `agents_per_paper` | 3 | Readers in one paper's cohort on an island; all submit before it is decided. |
| `islands_per_paper` | 2 | Islands a paper is assigned to. |
| `max_tool_calls` | 6 | Tool calls per run. |
| `max_model_calls` | 4 | Model calls per run. |
| `max_output_tokens` | 900 | Output tokens per model call, when the provider accepts the limit. The harness raises it to at least 2,500 (4,000 for a submission) so a reasoning model has room to answer. |
| `pause_new_runs` | false | Stop new runs; browsing and chat retrieval stay up. |
| `auto_run_on_ingest` | true | Advance the swarm after each ingestion pass. |
| `unread_paper_days` | 14 | Papers no agent has run on or read are forgotten after this many days, at the start of an ingestion pass. Selected papers remain available until explicitly deselected for the whole swarm (`POST /papers/{id}/deselect`). |
| `max_papers` | 400 | The terminal mass: once this many papers are selected or waiting, a pass stores none. Letting papers go makes room. |
| `max_runs_per_day` | 120 | Runs the whole swarm may start in one UTC day, subject to the monthly and daily cost guards. |
| `runs_per_island_per_hour` | 6 | Agent runs each island may start per hour, while the daily cap and budget allow. |
| `per_evolution_max_micros` | 20,000 | Most one model-proposed child may be estimated to cost. |

Per island: `budget_share` (its part of the daily hard and monthly budgets), `reading_mode` (`abstract`, or `metadata` for a single-call reading with the abstract in the prompt, even when full text is stored), `paused`, `priority` (`low` islands are the first paused under pressure).

Modes, by UTC day and month:

| Mode | When | Effect |
| --- | --- | --- |
| `normal` | today below the daily soft budget | The levers as written. |
| `conserving` | today at or above soft | One agent and one island per paper, half the tool and model calls, half the papers per pass, low-priority islands paused. |
| `hard_stop` | today at or above hard | No new runs, no paid chat. Ingestion still stores and assigns metadata. |
| `stored_data_only` | month at or above the monthly budget | No paid work. The pages and retrieval-only chat stay up. |

A run is admitted only if its worst-case estimate fits the per-run cap (model calls are cut to make it fit), today's and the month's remaining budget, and the island's share. Queued and running runs hold their estimates. A refusal is a `409` whose `detail` starts with a reason code such as `daily_hard_budget_exhausted`, `island_over_share` or `runs_paused`. Each island's `runs_remaining_today` is how many more runs it could start today if each cost the per-run cap: a floor, not a forecast.

The projected month end is the month to date plus the mean daily spend of the last seven days for each day left.

**Evolution.** One switch for the swarm (`evolution.enabled`, on by default) and two flags per island: `evolve` (the island takes part; the swarm switch must be on too) and `mutate` (a cycle may create a child). With `mutate` off a cycle is recorded and breeds nothing. A flip takes effect from the next cycle and rewrites nothing stored. Settings, all editable:

| Setting | Default | Meaning |
| --- | --- | --- |
| `enabled` | true | The switch. |
| `runs_threshold` | 6 | Completed runs on an island since its last generation that start a cycle. |
| `max_agents_per_island` | 6 | Active agents an island may hold; past it, the agent with the fewest runs that is not a parent of the new child is archived. |

**Selected papers.** The first `agents_per_paper` distinct readers who take a paper form its cohort, or all active agents if fewer. Each reading votes on `keep`; the island selects the paper only when every completed cohort vote agrees. A failed reading has not voted. Until the cohort completes, the paper waits. Once every assigned island decides and none selects it, the readers deselect it for the swarm. New agents join new cohorts without changing existing cohorts. Automatic evolution retains readers whose cohort votes are still missing; if retirement would strand a cohort and no safe replacement fits the population cap, that generation waits. A person's choice overrides these votes. Selections remain available, even unread or not yet assigned, until deselected. A selection follows a paper when it reaches a new island.

Each future reading receives up to five selected papers from its own island, with bounded summaries and the selection source. These guide interests and comparisons; they are not evidence for new claims.

`POST /papers/{paperId}/select` and `/deselect` are the canonical actions. The old `/hold` and `/release` routes remain aliases. Public records include `selected`, `selected_by` and manual `selection` details; legacy `held` fields remain compatible. Island briefs expose `selected` and `selected_papers` aliases. The globe ties selected papers only to their selecting islands.

**Likes.** The one signal a person gives: `POST /likes` with `target_kind` (`paper`, `run`, `reading`, `claim`, `idea`, `agent`) and `target_id` (a claim or idea is `<reading id>#<index>`). One like per island per thing; sending it again takes it back. An agent's points are the likes on its runs, readings, claims and ideas, plus the likes on papers it voted to keep. Points show on the island page, in the breeder's digest and in the brief's grade (`reception`); nothing else is computed from them.

There is no fitness function. A cycle runs once an island has finished `runs_threshold` runs since its last generation, and makes one child by mating: a parent from the island (its most liked agent, then its most experienced) and a mate from another island, combined and then changed in one thing. When a provider is configured and the budget admits the call (`per_evolution_max_micros`, the daily and monthly budgets), a model proposes the child from a digest of the whole swarm (every island's active agents, their prompts, strategies, settings, run counts, costs, points and newest reading summaries, the archived ids, and the papers people ask for most) by calling `propose_child` with the parents it mated, a prompt, a strategy, a temperature, an output budget, tools and a sentence on the idea. It may also name one of the island's agents to fail out as a lemon, with a reason, which archives it (`breeder_lemon`). The call is paid and receipted (`evolution`). A refused, failed, malformed, off-island or repeated proposal falls back to the rule: the child keeps the parent's prompt and takes the mate's bent as a second paragraph, the mate's reading strategy, the mean temperature and the union of tools, then one field-level change seeded by island and generation, so the rule's child is repeatable. A child that would repeat an agent already on the island is passed over.

People shape the population by liking things, by archiving an agent (`POST /agents/{agent}` with `{"fields": {"active": false}}`, or the island page) and bringing it back the same way, and by selecting or deselecting papers. Every island starts with the same three founders, carried over from the first research agent's launch procedures and said in this version's terms (`reader` for the evidence, `skeptic` for what could be wrong, `builder` for what can be built on), each told its island's focus, so the swarm begins with three postures on every island and kinship across them; a store from before the founders is given them at startup.

A generation is one spec revision written together with its record, so it appears whole or not at all, shows on the island page with every decision (`parent`, `mate`, `created`, `archived` with `population_cap` or `breeder_lemon`, `kept`) and the child's lineage (`parents`, `proposed_by`, `why`), and can be restored like any hand edit. A cycle that cannot act is recorded as skipped with the reason (`no_active_agent`, `no_novel_child`).

## API

Base path `/api/v1`. The conventions:

- Requests and answers are plain JSON. There is no envelope.
- A refusal is a non-2xx status with `{"detail": "...", "code": "...", "field": ...}`. `detail` is the sentence to show. `code` is one of `invalid_request`, `unauthenticated`, `forbidden`, `not_found`, `state_conflict`, `unavailable`.
- Money is an integer count of micro-dollars. Every time field (`*_at`) is whole seconds since 1970 UTC.
- Every answer carries a `budget` block: `mode`, `target_micros`, `month_to_date_micros`, `projected_month_micros`, `daily_soft_micros`, `daily_hard_micros`, `today_micros`, `runs_allowed`, `runs_refusal`, `paid_chat_allowed`, and `island` (share, spend, allowance, `runs_remaining_today`) when one is in scope.
- A group of rows is a plain list. A view names any group it could not read in `unavailable`, so an empty list always means "none", never "failed".
- CORS is credentialed and admits only the configured origins.

Interactive documentation is served at `/docs` and the schema at `/openapi.json`.

**Sessions.** `POST /login` takes `{"island": "cs", "password": "..."}` and returns `island`, `token`, `role` and `expires_at`. A wrong credential is `403`, an unknown island `404`, and an island with no credential configured accepts none. `{"credential": "..."}` alone also works: the credential names its island, and the operator's opens an operator session. Every later request sends `Authorization: Bearer <token>`. Tokens are stateless and signed, valid for thirty days; nothing is stored for a login, there is no cookie, and no chat transcript exists. The operator token is also accepted directly as a bearer token, for scripts.

**Public globe.** The splash retries the activity feed after a failed first request and refreshes its paper, island and budget snapshots every fifteen seconds. Agent motion remains driven by recorded run events.

**Scope.** Any session reads everything. An island session writes within its own island: its chat and runs, its island's descriptive fields and `evolve` flag, and its agents. The operator may do everything, and alone may ingest, advance, edit the budget and the evolution settings, change `budget_share` or `archived`, create islands, apply a whole spec and restore a spec revision.

| Method and path | Who | What |
| --- | --- | --- |
| `GET /health` | anyone | Liveness, schema version, whether a provider is configured. |
| `GET /public/storm` | anyone | `islands[]` (state, counts, cost, share), `papers`, `runs`, `readings`, `cost_micros`, `agents[]` with what each is reading, `recent_papers[]`, `recent_runs[]`. No prompt is shown. |
| `GET /public/brief` | anyone | The swarm told in words and numbers, from stored rows and no model call. By default it is what the swarm learned from the papers it keeps: `about`, `learned` (each kept paper's thesis, three biggest takeaways, ideas, objections, the agent that read it, and `href`), `connections` (links between kept papers that readings named in `related_papers`, each with its reason) and `ideas` (idea seeds with their papers). Any other section is asked for by name in `include`: `grade` (a letter, a 0-100 score, each criterion with its weight, score and evidence, and the caps that hold the letter down), `findings`, `numbers`, `islands`, `agents`, `claims` (newest first, each with its agent and whether its quote was verified), `papers` (selected, waiting with days left, deselected, and the newest available papers as `recent_papers`), `evolution`, `budget_state`, `limits`. Query: `include` (comma-separated sections), `island`, `paper`, `limit` (1-200), `format` (`json` or `text`, which answers Markdown). The web app serves a skill for agents that describes it at `/skill.md`. |
| `GET /public/papers/{paperId}` | anyone | One paper as the public may read it: `paper` (title, abstract, authors, url, islands), `selected`, `selected_by`, `selection`, `kept_by`, legacy `held`, `let_go_after`, `thesis`, `summary`, `takeaways` (the newest reading's three biggest claims, verified first), `read_by`, and every reading with its agent, summary, thesis, claims (each `verified`), objections and idea seeds. `format=text` answers Markdown. Each selected paper in the brief carries `thesis`, `takeaways` and this route as `href`. Every request is counted, by day, as use of the paper (`used`); evolution reads it. |
| `GET /public/activity?after=&limit=` | anyone | The newest run steps, oldest first: `id`, `run_id`, `agent`, `island_id`, `paper_id`, `kind`, `tool`, `passage_id`, `looked_at` (other papers a search or a cited read named), `created_at`, with `papers` naming each paper's title and islands and `last_id` to ask for only newer steps. No prompt, model text or tool output. |
| `POST /login`, `GET /session` | anyone / session | Open and inspect a session. |
| `POST /ingest/arxiv` | operator | One pass. Body: `category` or `categories`, `limit`, `advance`. Returns what was stored, updated, unchanged, failed, set aside and assigned, and which agents started. |
| `POST /swarm/advance` | operator | Idle agents take their next papers, at the configured hourly pace and `max_runs_per_day` for the swarm. Returns `started` and `waiting` with a reason per agent (`working`, `queue_empty`, `hourly_pace`, `daily_run_cap`, or a budget reason). |
| `GET /islands` | session | Every island: state, counts, cost, share, runs remaining today. |
| `GET /islands/{island}` | session | `island`, `cost_micros`, `month_cost_micros`, `budget_share`, `runs_remaining_today`, `agents[]`, `queue[]`, `papers[]`, `runs[]`, `readings[]`, `evolution[]`, `edits[]`. Each of `papers[]` carries `kept` (the selection decision, null while they read) and `released`; each agent carries `points`. |
| `POST /islands/{island}` | island or operator | Edit island fields. |
| `POST /islands/{island}/settings` | island or operator | Flip the island's switches: `{"evolution_enabled": bool}` or `{"mutation_enabled": bool}`. The island view reports both, and `swarm_evolution_enabled`. |
| `GET /agents?island=` | session | Every agent: genome fields, `address`, `state` (`working`, `idle`, `blocked` with `blocked_reason`, `retired` when archived), `version`, `parent_id`, `generation`, `current` run and step, `stats`, `cost_micros`. |
| `GET /agents/{agent}` | session | The agent, its `versions[]`, `runs[]`, `readings[]` and cost. |
| `POST /agents/{agent}` | island or operator | Edit the agent's genome (a new version), create an agent, or archive and bring back one with `{"fields": {"active": false}}` / `true`. |
| `POST /genomes` | island or operator | The same edit in the flat shape the web app's form sends: `{island_id, parent_id, prompt, tools}`, `tools` a comma-separated string or a list. The agent named by `parent_id` gets a new version. |
| `POST /agents/{agent}/versions/{n}/restore` | island or operator | Bring back an earlier version as a new one. |
| `GET /papers/{paperId}` | session | `paper` (`id`, `title`, `summary`, `url`, `pdf_url`, `text_status`, `sections[]`, ...), then `assignments[]` (each with `kept`), `readings[]` (each with `keep`), `runs[]`, `likes` (keyed `kind:id`, with `count` and `islands`), `cost_micros`, `cost_by_island`. |
| `POST /runs` | session | Have an agent read a paper now. Body: `paper_id`, optional `agent_id` or `genome_id`. Answers `202` with `run_id`; the work happens after the answer. Honors `Idempotency-Key`. Nothing needs to call this: agents start their own work. |
| `GET /runs/{runId}?after=` | session | `run`, the `genome` exactly as the run used it, the `paper`, replay-ordered `events[]`, `conduct` counted from the trace, `reading`, `likes` (keyed `kind:id`), `cost_micros`, `receipts[]`. |
| `POST /likes` | session | `target_kind` (`paper`, `run`, `reading`, `claim`, `idea`, `agent`), `target_id`. Gives the island's like or takes it back; answers `liked` and `count`. |
| `POST /papers/{paperId}/deselect` | an island the paper reached, or operator | Deselect a paper for the whole swarm. No island queues it and no agent finds it in search or its related-work shortlist; its runs, readings and receipts stay. An untouched paper let go is forgotten at the next ingestion pass. Body: optional `note`. |
| `POST /papers/{paperId}/select` | an island the paper reached, or operator | Select a paper for all assigned islands, overriding future reader votes. It remains available for future reading context. Body: optional `note`. |
| `POST /chat` | session | `message`, optional `synthesize`. Returns `answer`, `links[]` (`id`, `title`, `kind`, `href`, `snippet`), `cost_micros` (this answer's cost), `answer_id`, `supported`. |
| `GET /costs/budget` | session | The full budget state: figures, levers, the plan in force, each island's share. |
| `POST /costs/budget` | operator | Edit levers. |
| `POST /swarm/evolution` | operator | Edit the evolution settings, including the switch. |
| `POST /swarm/evolve` | operator | Run evolution where it is due. Body: `island_id`, `force` (ignore the thresholds, never the switches). |
| `GET /swarm/spec`, `POST /swarm/spec` | session / operator | Read or replace the whole spec. |
| `GET /swarm/revisions`, `GET /swarm/revisions/{n}` | session | The revision log and one revision's content. |
| `POST /swarm/revisions/{n}/restore` | operator | Restore a revision as a new one. |

**Replay events.** Each event has `id` and `seq` (the same number), `run_id`, `kind`, `created_at`, and what a page shows without interpreting anything: `body` (one line), `tool`, `model`, `input`, `output`, `cost_micros` (the amount of its receipt), `receipt_id`, `cost_state` and `locator`. `payload` is the stored record those were rendered from.

**Chat.** An answer comes from stored data, with links back to the objects it used; `supported: false` when nothing stored supports one. A model-written answer is attempted only when `synthesize` is true and the budget admits it; otherwise the retrieval answer is returned and `paid.refused` says why.

**Edits.** Edit bodies are `{"fields": {...}, "note": "", "dry_run": false, "base_revision": null}`. `dry_run` validates and returns the changes without writing. `base_revision` refuses the edit with `409` when the spec has moved since the caller read it. A validation failure is `422` with the offending field.

## Not in this beta

- Model-written mutation and cross-island transfer. Evolution changes one field by rule within an island.
- PDF parsing and OCR. Full text comes only from arXiv's HTML versions; figures are kept as their captions, not their images.
- Accounts and login rate limiting. An island has one shared credential; limit `POST /api/v1/login` at the reverse proxy.
- More than one process. Runs execute inside the serving process; a restart closes any run left open as `interrupted_by_restart` with its trace kept.

The default General island watches statistics, optimization and complex-systems feeds (`stat.ML`, `math.OC`, `physics.soc-ph`), and also receives papers no other island claims. Bio watches `q-bio.*`. Existing island configurations and explicit pacing limits are preserved; operators can apply these defaults through a spec revision. Higher run counts remain subject to measured spend, reserved costs and the existing $50 monthly budget.

### Activate an existing deployment

For an existing deployment, the operator applies `papers_per_pass=4`, `max_runs_per_day=120` and `runs_per_island_per_hour=6` through the budget endpoint, and General categories `stat.ML`, `math.OC`, `physics.soc-ph` through the island endpoint. Defaults do not overwrite explicit existing configuration. Back up the SQLite store before deploying schema version 9. Confirm completed reads and activity on every island after activation. GitHub develop pushes run checks; this repository does not deploy the atoll backend automatically.
