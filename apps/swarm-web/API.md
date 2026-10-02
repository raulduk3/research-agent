# What this app uses of the swarm server

The server's contract is `deploy/beta/README.md` (the API section) and its code is `src/research_agent/beta/`. This file lists only what the app calls and how it reads the answers. `src/api/types.ts` is the same list as types. If this file and the server's contract disagree, the server's contract is right and this file is wrong.

## Conventions the app relies on

- Base address: `VITE_API_ORIGIN` at build time. Empty means the same origin as the app.
- Plain JSON both ways. A refusal is a non-2xx status with `detail`, which the app shows as written.
- Money is whole micro-dollars. Times are whole seconds since 1970 (UTC).
- After sign-in every request carries `Authorization: Bearer <token>`. Requests are sent with `credentials: "include"`, so the server's CORS must name the app's exact origin (`RESEARCH_AGENT_ALLOWED_ORIGINS`).
- Every answer carries a `budget` block. The strip on every page reads the one on `GET /public/storm`.
- A field the server leaves out or sends as null is shown as "not reported", never as zero. A group named in an answer's `unavailable` list is reported as unavailable, not as empty.

## Calls

| Call | Used by |
| --- | --- |
| `GET /api/v1/public/storm` | splash, sign-in island list, budget strip on every page |
| `GET /api/v1/public/brief?include=grade,claims,papers&limit=100` | splash: the grade, claims, papers held and undecided, and the newest hundred papers for the globe |
| `GET /api/v1/public/activity?after=N&limit=60` | splash globe: read every four seconds from the last `last_id`; each step moves a boat, strikes papers with bolts and adds the papers it looked up |
| `POST /api/v1/login` with `{island, password}` | sign-in |
| `GET /api/v1/islands/{island}` | island page, tree |
| `POST /api/v1/islands/{island}/settings` with `{evolution_enabled}` or `{mutation_enabled}` | the island's two switches, one setting per call |
| `POST /api/v1/genomes` with `{island_id, parent_id, prompt, tools}` | editing an agent |
| `GET /api/v1/papers/{paperId}` | paper page, tree |
| `GET /api/v1/runs/{runId}` | run page, tree; read again every three seconds while the run is queued or running |
| `POST /api/v1/chat` with `{message}` | chat |
| `POST /api/v1/papers/{paperId}/release`, `.../hold` with `{}` | the island's own page: let a paper go or hold it again; the island is read again after each |
| `POST /api/v1/likes` with `{target_kind, target_id}` | the like button on a paper, run, reading, claim, idea or agent; the answer's `liked` and `count` replace the button's |
| `POST /api/v1/agents/{agent}` with `{fields: {active}}` | the island's own page: archive an agent or bring it back; the island is read again after each |

The app never calls ingestion, `POST /runs`, `POST /swarm/advance` or any operator route. It starts no work. Agents take their own next papers.

## How the answers are read

**Budget strip.** `month_to_date_micros / target_micros month · projected projected_month_micros · mode`, with `hard_stop` and `stored_data_only` shown as "hard stop" and "stored-data only". When `runs_allowed` is false the strip adds "no new runs" and the reason. If a server sent a month figure without a projection or mode, the app would carry the daily rate forward and derive the mode, and say it was estimated; this server always sends both.

**Splash.** The storm, the brief and the activity feed are read without a session. A server that answers the brief or the feed with a refusal leaves the globe and counts in place and says which part is missing. The globe draws the brief's `recent_papers`, the newest hundred not let go (held solid, waiting hollow), places each by its id so it keeps its place, and plays the feed's steps a beat apart: `run_started` sails the agent's boat from its island to the paper, every later step strikes the run's paper (and, for a tool call, each of `looked_at`) with a bolt, a paper not yet drawn appears and pulses in the agent's color, `reading_submitted` rings the paper, and `run_completed` or `run_failed` sails the boat home. A click names the paper, boat or island under the pointer.

**Sign-in.** The session `{island, token}` is kept in the browser's local storage until the visitor leaves. A 401 on any later call drops it and returns to sign-in.

**Scope.** The server lets any session read everything and lets an island session write only within its own island. The app follows that: every page opens for any session, and the edit form, the archive control and the evolution switch appear only on the session's own island. A page behind sign-in is neither shown nor requested without a session.

**Island.** `agents[]` (each with `points`), `queue[]`, `papers[]` (each with `kept` and `released`), `runs[]`, `evolution[]`, `cost_micros`, `budget_share`, `runs_remaining_today`, and the switch fields below. An agent whose `current` is set links to that run to be watched. An evolution row with no `genome_id` is a skipped cycle.

**Editing an agent.** The form sends the prompt and the ticked tools; `parent_id` is the agent's id. The server stores a new version of that agent. An agent whose parent is itself is shown as edited, not as a descendant.

**Evolution and mutation switches.** Two switches per island, read from `evolution_enabled` and `mutation_enabled` on the island answer. A flip sends that one setting, then the island is read again and the switch shows what the server stored. With evolution off the mutation switch is disabled, because it would change nothing. The operator's switch for every island arrives as `swarm_evolution_enabled` and is reported, not changed here. A server that sends neither field shows both switches as "not reported".

**Paper.** `paper` with `sections[]` and `pdf_url`, `assignments[]`, `runs[]`, `readings[]` (matched to runs by `run_id`), `cost_micros`, `cost_by_island`. With an empty `cost_by_island` the page adds up the runs' own costs by island. An island missing from a non-empty breakdown reads "not reported".

**Run.** `run`, `genome` (the copy the run used), `paper`, `events[]`, `reading`, `cost_micros`. The events are the replay: the app plays the stored list in order and adds nothing. Per event it shows `body`, the badge from `model` or `tool` (else from `kind`), `input` as what the agent asked, `output` folded beneath, `cost_micros`, and follows `locator`: the section whose id is `locator.section` with `locator.quote` marked, else the PDF at `locator.page`, else the abstract with the quote beside it. Model, tool and step costs are the events' costs added up by badge.

**Chat.** `answer`, `links[]` by `kind` and `id`, `answer_id`. `cost_micros` is that answer's cost: above zero it is shown as the answer's cost, zero as "stored-data only". Chat turns live in the page only.


## Limits that show on screen today

- The server stores a paper's abstract as its only text, so locators point at the abstract and `page` is always null. The PDF view opens for arXiv papers but no step moves it to a page.
- The PDF view is the browser's own viewer in a frame. It reloads to change page and cannot mark text inside the PDF.
- Without a model provider configured on the server no run starts, and the strip says so.
