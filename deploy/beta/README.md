# Swarm beta backend

One small FastAPI process over one SQLite file. It ingests current arXiv papers, assigns them to islands, lets each island's agents read one paper per run, keeps every run as a replayable event trace with cost receipts, holds the month to a budget, and answers chat from the stored data.

The idea the surface is built around: **you edit the agents and you watch the runs.** Nobody starts work by sending a prompt. An idle agent takes the next unread paper from its island's queue; the budget decides how much happens. Evolution, when switched on, edits the agents too: it keeps the best and tries one mutated child.

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
| `RESEARCH_AGENT_INGEST_SECONDS`, `RESEARCH_AGENT_TICK_SECONDS` | How often the process ingests and advances by itself. Zero is off. |

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

With `RESEARCH_AGENT_INGEST_SECONDS` and `RESEARCH_AGENT_TICK_SECONDS` set, the serving process does the first two on its own and no cron is needed.

### Backup

Everything durable is the one SQLite file (WAL mode). Take a consistent copy while the server runs:

```sh
sqlite3 /var/lib/swarm/swarm.sqlite3 ".backup '/backups/swarm-$(date +%F).sqlite3'"
```

## How it works

**Islands, agents, genomes.** An island is a research group with categories, keywords, a reading mode, a priority and a share of the budget. An agent is a genome seated on an island, addressed `genome@island` (`cs-reader@cs`). A genome is the agent's configuration: prompt, model settings, allowed tools, reading strategy, scoring preferences, plus a managed `version` and `lineage`.

**The swarm spec.** Islands, genomes, the budget levers and the evolution settings are one JSON document. Every edit validates the whole document and appends a revision; nothing is updated in place or deleted. A run stores the revision and genome version it ran under and a copy of that genome, so editing an agent never changes a past run. Any revision, and any agent version, can be restored, which appends a new revision with the old content. Islands and agents are switched off (`archived`, `active: false`), never removed.

**Runs.** A run is one agent reading one paper. It records an immutable event per step: `run_started`, `prompt`, `model_call`, `tool_call`, `paper_read`, `note`, `reading_submitted`, `run_completed` or `run_failed`. Each event is committed as it happens, carries a link to its cost receipt when it was paid work, and may carry a paper locator (`paper_id`, `source_kind`, `section`, `passage_id`, `page`, `char_start`, `char_end`, `quote`). The run page replays the events in `seq` order; `?after=<seq>` returns only newer events, which is how a page watches a live run. There is no separate timeline.

The harness controls a run through structure: which tools are offered, a cap on model calls, tool calls and output tokens, and a per-run cost cap. On the last model call only `submit_reading` is offered, and that call is given at least 3,000 output tokens, because a reading is long and a model that reasons first spends part of its output on the reasoning. A run that ends without a reading says why: `output_truncated`, `no_reading_submitted` or `model_call_limit`. What the harness tells the model between calls is recorded on the next `model_call` event as `harness_notice`.

Tools: `paper_text`, `related_papers`, `capture_note`, `feedback_context`, `cost_state`, `submit_reading`. A call to a tool the genome does not allow is recorded as refused and does nothing. A submitted reading must carry `summary`, `claims`, `objections`, `related_papers` and `idea_seeds`; a claim that depends on the paper text needs a quote, and each quote is checked against the stored text and marked verified or not.

**Stored text.** The stored text of a paper is its arXiv abstract, kept as one passage with character offsets. Text this short is placed in the run's prompt and recorded as read there, so the agent does not spend a model call fetching it; `paper_text` answers a request for a passage that is not stored with the list of those that are. Full text is not fetched or stored in this beta, so locators are of kind `abstract` or `metadata` and `page` is always null. The schema has `section`, `page` and `passage` kinds ready for a later text import.

**Costs.** Every paid or scarce action writes one receipt: `ingest` (an arXiv request, amount zero), `model_call`, `chat_retrieval` (amount zero), `chat_answer`. Receipts are append-only leaf charges in whole micro-dollars; every total on every page is a sum of receipts. A model call that fails after the request left gets an `unsettled` receipt at its estimate: excluded from settled totals, held against the budget.

**Budget.** The levers are part of the spec and editable by the operator:

| Lever | Default | Meaning |
| --- | --- | --- |
| `monthly_budget_micros` | 50,000,000 | The month's ceiling: 50 USD. |
| `daily_soft_micros` | derived | Monthly budget over the days of the month. |
| `daily_hard_micros` | derived | Twice the daily soft budget. |
| `per_run_max_micros` | 50,000 | Most a single run may be estimated to cost. |
| `per_chat_max_micros` | 5,000 | Most a model-written chat answer may be estimated to cost. |
| `papers_per_pass` | 10 | Papers one ingestion pass may hold. |
| `agents_per_paper` | 1 | Agents of one island that read a paper. |
| `islands_per_paper` | 2 | Islands a paper is assigned to. |
| `max_tool_calls` | 6 | Tool calls per run. |
| `max_model_calls` | 4 | Model calls per run. |
| `max_output_tokens` | 900 | Output tokens per model call, when the provider accepts the limit. |
| `pause_new_runs` | false | Stop new runs; browsing and chat retrieval stay up. |
| `auto_run_on_ingest` | true | Advance the swarm after each ingestion pass. |

Per island: `budget_share` (its part of the daily hard and monthly budgets), `reading_mode` (`abstract`, or `metadata` for a single-call reading with the abstract in the prompt), `paused`, `priority` (`low` islands are the first paused under pressure).

Modes, by UTC day and month:

| Mode | When | Effect |
| --- | --- | --- |
| `normal` | today below the daily soft budget | The levers as written. |
| `conserving` | today at or above soft | One agent and one island per paper, half the tool and model calls, half the papers per pass, low-priority islands paused. |
| `hard_stop` | today at or above hard | No new runs, no paid chat. Ingestion still stores and assigns metadata. |
| `stored_data_only` | month at or above the monthly budget | No paid work. The pages and retrieval-only chat stay up. |

A run is admitted only if its worst-case estimate fits the per-run cap (model calls are cut to make it fit), today's and the month's remaining budget, and the island's share. Queued and running runs hold their estimates. A refusal is a `409` whose `detail` starts with a reason code such as `daily_hard_budget_exhausted`, `island_over_share` or `runs_paused`. Each island's `runs_remaining_today` is how many more runs it could start today if each cost the per-run cap: a floor, not a forecast.

The projected month end is the month to date plus the mean daily spend of the last seven days for each day left.

**Evolution.** One switch for the swarm (`evolution.enabled`, on by default) and two flags per island: `evolve` (the island takes part; the swarm switch must be on too) and `mutate` (a cycle may create a child). With `mutate` off a cycle only scores, keeps and retires. A flip takes effect from the next cycle and rewrites nothing stored. Settings, all editable:

| Setting | Default | Meaning |
| --- | --- | --- |
| `enabled` | true | The switch. |
| `runs_threshold` | 6 | Completed runs on an island since its last generation that start a cycle. |
| `feedback_threshold` | 3 | Feedback signals since its last generation that start one. |
| `max_agents_per_island` | 3 | Active agents an island may hold. |
| `min_runs_to_judge` | 2 | Finished runs an agent needs before it is scored. |

A cycle runs after an island's runs finish, once a threshold is crossed. Each active agent with enough runs of its current version is scored: accepted minus pushed-away feedback per completed run, plus half its completion rate. Agents are ranked by usefulness in bands of 0.2; cost per run decides only between agents in the same band; an agent whose runs average above the per-run cap cannot parent. The best is retained and one child is made from it by exactly one field-level mutation: an emphasis line in the prompt, the reading strategy, the temperature, the output tokens, or one optional tool. A mutation that would repeat an agent already on the island is passed over. When the child puts the island over its cap, the worst judged agent is retired, which switches it off. An agent too new to judge is never retired.

Mutation is rule-based and seeded by island and generation number, so it calls no model, costs nothing and is repeatable. A generation is one spec revision written together with its record, so it appears whole or not at all, shows on the island page with every decision and its reason, and can be restored like any hand edit. A cycle that cannot act is recorded as skipped with the reason (`no_judged_agent`, `population_full_awaiting_evidence`, `no_novel_mutation`).

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

**Scope.** Any session reads everything. An island session writes within its own island: its feedback, chat and runs, its island's descriptive fields and `evolve` flag, and its agents. The operator may do everything, and alone may ingest, advance, edit the budget and the evolution settings, change `budget_share` or `archived`, create islands, apply a whole spec and restore a spec revision.

| Method and path | Who | What |
| --- | --- | --- |
| `GET /health` | anyone | Liveness, schema version, whether a provider is configured. |
| `GET /public/storm` | anyone | `islands[]` (state, counts, cost, share), `papers`, `runs`, `readings`, `cost_micros`, `agents[]` with what each is reading, `recent_papers[]`, `recent_runs[]`. No prompt is shown. |
| `POST /login`, `GET /session` | anyone / session | Open and inspect a session. |
| `POST /ingest/arxiv` | operator | One pass. Body: `category` or `categories`, `limit`, `advance`. Returns what was stored, updated, unchanged, failed, set aside and assigned, and which agents started. |
| `POST /swarm/advance` | operator | Idle agents take their next papers. Returns `started` and `waiting` with a reason per agent. |
| `GET /islands` | session | Every island: state, counts, cost, share, runs remaining today. |
| `GET /islands/{island}` | session | `island`, `cost_micros`, `month_cost_micros`, `budget_share`, `runs_remaining_today`, `agents[]`, `queue[]`, `papers[]`, `runs[]`, `readings[]`, `feedback[]`, `feedback_totals`, `evolution[]`, `edits[]`. |
| `POST /islands/{island}` | island or operator | Edit island fields. |
| `POST /islands/{island}/settings` | island or operator | Flip the island's switches: `{"evolution_enabled": bool}` or `{"mutation_enabled": bool}`. The island view reports both, and `swarm_evolution_enabled`. |
| `GET /agents?island=` | session | Every agent: genome fields, `address`, `state` (`working`, `idle`, `blocked` with `blocked_reason`, `retired`), `version`, `parent_id`, `generation`, `current` run and step, `stats`, `cost_micros`. |
| `GET /agents/{agent}` | session | The agent, its `versions[]`, `runs[]`, `readings[]`, `feedback[]` and cost. |
| `POST /agents/{agent}` | island or operator | Edit the agent's genome (a new version), or create an agent. |
| `POST /genomes` | island or operator | The same edit in the flat shape the web app's form sends: `{island_id, parent_id, prompt, tools}`, `tools` a comma-separated string or a list. The agent named by `parent_id` gets a new version. |
| `POST /agents/{agent}/versions/{n}/restore` | island or operator | Bring back an earlier version as a new one. |
| `GET /papers/{paperId}` | session | `paper` (`id`, `title`, `summary`, `url`, `pdf_url`, `text_status`, `sections[]`, ...), then `assignments[]`, `readings[]`, `runs[]`, `feedback[]`, `cost_micros`, `cost_by_island`. |
| `POST /runs` | session | Have an agent read a paper now. Body: `paper_id`, optional `agent_id` or `genome_id`. Answers `202` with `run_id`; the work happens after the answer. Honors `Idempotency-Key`. Nothing needs to call this: agents start their own work. |
| `GET /runs/{runId}?after=` | session | `run`, the `genome` exactly as the run used it, the `paper`, replay-ordered `events[]`, `conduct` counted from the trace, `reading`, `feedback[]`, `cost_micros`, `receipts[]`. |
| `POST /feedback` | session | `target_kind` (or `target_type`): `island`, `paper`, `reading`, `run`, `idea`, `chat`. `target_id`, `signal`, `note`. An idea is `<reading id>#<index>`; a chat answer is its `answer_id`. Honors `Idempotency-Key`. |
| `POST /chat` | session | `message`, optional `synthesize`. Returns `answer`, `links[]` (`id`, `title`, `kind`, `href`, `snippet`), `cost_micros` (this answer's cost), `answer_id`, `supported`. |
| `GET /costs/budget` | session | The full budget state: figures, levers, the plan in force, each island's share. |
| `POST /costs/budget` | operator | Edit levers. |
| `POST /swarm/evolution` | operator | Edit the evolution settings, including the switch. |
| `POST /swarm/evolve` | operator | Run evolution where it is due. Body: `island_id`, `force` (ignore the thresholds, never the switches). |
| `GET /swarm/spec`, `POST /swarm/spec` | session / operator | Read or replace the whole spec. |
| `GET /swarm/revisions`, `GET /swarm/revisions/{n}` | session | The revision log and one revision's content. |
| `POST /swarm/revisions/{n}/restore` | operator | Restore a revision as a new one. |

**Replay events.** Each event has `id` and `seq` (the same number), `run_id`, `kind`, `created_at`, and what a page shows without interpreting anything: `body` (one line), `tool`, `model`, `input`, `output`, `cost_micros` (the amount of its receipt), `receipt_id`, `cost_state` and `locator`. `payload` is the stored record those were rendered from.

**Feedback signals** are `accept`, `pass` and `push_away`. `useful` is taken as `accept` and `not_useful` as `pass`.

**Chat.** An answer comes from stored data, with links back to the objects it used; `supported: false` when nothing stored supports one. A model-written answer is attempted only when `synthesize` is true and the budget admits it; otherwise the retrieval answer is returned and `paid.refused` says why.

**Edits.** Edit bodies are `{"fields": {...}, "note": "", "dry_run": false, "base_revision": null}`. `dry_run` validates and returns the changes without writing. `base_revision` refuses the edit with `409` when the spec has moved since the caller read it. A validation failure is `422` with the offending field.

## Not in this beta

- Model-written mutation and cross-island transfer. Evolution changes one field by rule within an island.
- Full paper text, PDF parsing and OCR.
- Accounts and login rate limiting. An island has one shared credential; limit `POST /api/v1/login` at the reverse proxy.
- More than one process. Runs execute inside the serving process; a restart closes any run left open as `interrupted_by_restart` with its trace kept.
