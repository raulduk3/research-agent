# What this app expects from the swarm server

This file records what the app asks the server and what it does with the answer. It is an assumption, not a contract the repository holds. It was read off the beta server draft (`src/research_agent/beta/app.py`, not yet committed anywhere) on 2026-10-01. `src/api/types.ts` is the same list as types. When the server's real contract lands, this file and those types change together.

## Conventions

- Base address: `VITE_API_ORIGIN` at build time. Empty means the same origin as the app.
- Requests and answers are plain JSON. There is no envelope.
- A refusal is a non-2xx status with `{"detail": "..."}`. The app shows `detail` to the visitor.
- Money is an integer count of micros: one millionth of a US dollar. `cost_micros: 2000` is $0.002.
- Times are whole seconds since 1970 (UTC).
- Every request is sent with `credentials: "include"`. After sign-in every request also carries `Authorization: Bearer <token>`. The server must answer with credentialed CORS for the app's origin: the exact origin, not `*`.

## Endpoints the app calls

| Call | Used by | Session |
| --- | --- | --- |
| `GET /api/v1/public/storm` | splash, sign-in island list, budget strip on every page | none |
| `POST /api/v1/login` | sign-in | none |
| `GET /api/v1/islands/{island_id}` | island page, tree, run page (to find the run's genome) | island |
| `GET /api/v1/papers/{paper_id}` | paper page, tree, run page (the paper beside the replay) | island |
| `GET /api/v1/runs/{run_id}` | run page, tree | island |
| `POST /api/v1/chat` | chat | island |
| `POST /api/v1/feedback` | island, paper, run pages and chat answers | island |
| `POST /api/v1/genomes` | editing an agent on the island page (assumed, see below) | island |
| `POST /api/v1/islands/{island_id}/settings` | the evolution and mutation switches (assumed, see below) | island |

The app never calls `POST /api/v1/ingest/arxiv` or `POST /api/v1/runs`. It starts no work and spends nothing.

## Answers

Fields in the first list are what the draft server sends today. Fields under "read when sent" are not sent today. The app uses each one when it arrives and otherwise says "not reported" in its place. It does not show a zero or a made-up value.

### `GET /api/v1/public/storm`

Sent today: `islands[] {id, name, focus, created_at}`, `papers` (count), `runs` (count), `cost_micros` (all recorded cost, not scoped to a month).

Read when sent:

- `budget {target_micros, month_to_date_micros, projected_month_micros, mode}`. `mode` is one of `normal`, `conserving`, `hard stop`, `stored-data only` (underscores are accepted). This is what fills the strip: `$12.40 / $50 month · projected $38 · normal`.
- `islands[].paper_count`, `islands[].run_count`. With both on every island the globe leans each island's papers toward it and draws one line per run. Without them the papers fill the globe evenly and no line is drawn.

What the app works out itself, and only then:

- No `target_micros`: the target is $50.
- `month_to_date_micros` sent but no projection: the month so far divided by days elapsed (UTC, at least one day), times the days in the month.
- `month_to_date_micros` sent but no mode: `hard stop` once the month reaches the target, `conserving` when the projection is over it, else `normal`. The strip then adds "estimated from the month so far".
- No `month_to_date_micros`: nothing is estimated. The strip shows the all-time `cost_micros` as "recorded in all" and says the projection and mode are not reported. This is what the draft server produces today.

### `POST /api/v1/login`

Body `{island, password}`. Answer `{island, token}`. A wrong code is 403, an unknown island 404.

The app keeps `{island, token}` in the browser's local storage until the visitor leaves the island. A 401 on any later call drops it and returns the visitor to sign-in.

Not enforced by the draft server: no other endpoint checks the token, and an island with no configured password accepts any code. Today the island gate is the app's own routing: a page behind the gate is not rendered and its data is not requested without a session for that island. That is not access control. The server must check the token and the island scope on every non-public call before real data sits behind it.

### `GET /api/v1/islands/{island_id}`

Sent today: `island`, `papers[]` (newest 100), `genomes[] {id, island_id, prompt, tools, parent_id, generation, active, created_at}` with `tools` a comma-separated string, `runs[]` (newest 100), `cost_micros`.

Read when sent:

- `month_cost_micros`, `budget_share` (0 to 1). Budget share shown is `budget_share`, else `month_cost_micros` over the target, else `cost_micros` over the target, and the card says which.
- `runs_remaining_today`. Otherwise the card says "not reported".
- `evolution[] {generation, genome_id, decision, reason}` with `decision` one of `created`, `retained`, `retired`. Without it the page lists the lineage the genome rows spell out (generation, parent, active or retired) and no reasons.
- `papers[].cost_micros`, `runs[].cost_micros`, `genomes[].cost_micros`.

### `GET /api/v1/papers/{paper_id}`

Sent today: `paper {id, title, summary, url, primary_category, text_status, fetched_at}`, `assignments[] {paper_id, island_id, reason}`, `runs[]`, `cost_micros`.

Read when sent:

- `cost_by_island {island_id: micros}`. Without it, cost by island is the runs' own costs added up, and only if every run carries `cost_micros`. Otherwise "not reported".
- `runs[].cost_micros` for cost by run.
- `paper.pdf_url`. Without it, an `arxiv.org/abs/...` address in `url` is turned into `https://arxiv.org/pdf/...`. A paper with neither has no PDF view.
- `paper.sections[] {id, title, page, text}`: the stored text, in reading order. This is what lets the viewer jump to a section and mark a quoted passage.

### `GET /api/v1/runs/{run_id}`

Sent today: `run {id, paper_id, island_id, genome_id, status, reading, created_at}`, `events[] {id, run_id, kind, body, cost_micros, created_at}` in order, `cost_micros`.

The events are the replay. The app plays exactly the stored list in the stored order and adds nothing.

Read when sent, per event:

- `tool`, `model`: names for the badge. Without them the badge comes from `kind`: `model_call` is a model step, `tool_call` or a known tool name (`paper_text`, `related_papers`, `capture_note`, `feedback_context`, `cost_state`, `submit_reading`) is a tool step, anything else is shown by its kind.
- `input`: what the reader asked the tool or the model at this step. Shown as "the reader asked".
- `output`: what came back. Shown folded under the step.
- `locator {page, section, quote}`: where in the paper the step read. Any subset may be present. With stored text, the viewer opens the named section (else the one containing the quote, else the one on that page) and marks the quote. Without stored text it opens the PDF at `page`. With neither it stays on the record and abstract and shows the quote beside it.

Read when sent, on the answer: `genome` and `paper` (the full rows). Without them the app makes two more calls: the paper, and the run's island to find the genome by id.

Model, tool and step costs on the run page are the events' own `cost_micros` added up by badge. The run total is the answer's `cost_micros`.

### `POST /api/v1/chat`

Body `{island_id, message}`. Answer `{answer, links[] {id, title}, cost_micros}`.

Assumed: `cost_micros` is the cost of this answer. Above zero the app shows it as the answer's cost. Zero or absent shows "stored-data only". The draft server sends the island's running total in this field instead. That needs to change on the server or the label will be wrong once islands have cost.

Read when sent: `links[].kind` (`paper`, `run` or `island`, default `paper`) to choose where a link leads, and `answer_id` to offer feedback on the answer.

Chat turns live in the page only. Nothing is stored in the browser or sent anywhere but this call.

### `POST /api/v1/feedback`

Body `{island_id, target_type, target_id, signal, note}`. `target_type` is `island`, `paper`, `run` or `chat`. `signal` is `useful` or `not_useful`. Any 2xx counts as recorded. A refusal is shown as "feedback unavailable, nothing was recorded".

## Editing agents

The big idea is two halves: agents are edited, runs are watched. The island page lets a visitor edit an agent's prompt and the tools it may call. The run page shows the genome as that run used it and links to the agent; it steers nothing. The app starts no run and no ingestion.

### `POST /api/v1/genomes` (assumed, not in the draft server)

Body `{island_id, parent_id, prompt, tools}` with `tools` a comma-separated string. Any 2xx counts as saved, after which the app reads the island again and shows what the server stored.

Assumed meaning: the server creates a new genome version whose parent is `parent_id`. It does not change the parent in place, so the earlier version and every run it made stay as they are. That is what makes an edit safe to try. Whether the new version becomes active at once, and whether the parent retires, is the server's decision and shows up in the island answer.

Until the server has this call it answers 404 or 405. The app then says "This server does not take agent edits yet. Nothing was saved." and keeps the text in the form.

## Evolution and mutation switches

The island page carries two switches. The app only shows and flips them; evolution itself is the server's work.

Read when sent, on `GET /api/v1/islands/{island_id}`: `evolution_enabled`, `mutation_enabled` (booleans). Without them a switch reads "not reported".

### `POST /api/v1/islands/{island_id}/settings` (assumed, not in the draft server)

Body `{"evolution_enabled": true}` or `{"mutation_enabled": false}`: one setting per call, as a JSON boolean. Any 2xx counts as stored, after which the app reads the island again and shows what the server stored. Until the server has this call it answers 404 or 405 and the app says "This server does not take evolution settings yet. Nothing changed."

Assumed meaning, kept simple:

- Evolution on: when the island crosses its feedback or run-count threshold, the server scores its agents from feedback, run health and cost, then keeps or retires them and records why.
- Mutation on: a cycle may also create changed copies of the agents it keeps, as new versions with the kept agent as parent.
- Evolution off: nothing changes on its own. Agents still change when someone edits one. Mutation has no effect, and the app disables that switch.
- Flipping a switch changes what happens from the next cycle on. It rewrites no stored agent, run or record.

## Known gaps against the draft server

- No month figures, projection or mode, so the budget strip cannot state a budget mode yet.
- No runs remaining today.
- No per-run, per-paper or per-island cost on list rows, so most list rows read "not reported".
- No step locators and no stored paper text, so the replay's viewer opens on the abstract. The PDF view still works for arXiv papers.
- No evolution records.
- No call to save an edited agent, so the edit form reports that nothing was saved.
- No evolution or mutation settings, so both switches read "not reported" and a flip reports that nothing changed.
- Paper ids that contain a slash (old arXiv ids) will not resolve as one path segment.
