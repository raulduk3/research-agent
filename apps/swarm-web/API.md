# Swarm browser API reference

The browser calls the beta FastAPI server at `VITE_API_ORIGIN`. Paths below include `/api/v1`. The server implementation and operator routes are documented in [beta operations](../../deploy/beta/README.md).

## Transport and scope

Requests send `credentials: "include"`; credentialed CORS requires the browser origin in `RESEARCH_AGENT_ALLOWED_ORIGINS`. After login, protected requests carry `Authorization: Bearer <token>`. The browser stores the session in local storage until sign-out or authentication refusal. A 401 clears it.

Sessions can read other islands, but island sessions can change only their own island. Agent edits and archive actions are available on the session's island. Other islands show disabled evolution controls. Protected pages do not request their data before sign-in.

Amounts are integer micro-dollars. Instants are UTC strings or Unix seconds where the response declares them. Missing reported values remain “not reported.” Failed refreshes preserve the last successful answer; permanent refusals clear it. Unavailable-group handling is incomplete on paper and run pages. Current cost displays do not consistently distinguish unsettled receipts from settled totals.

## Browser calls

| Request | Consumer |
| --- | --- |
| `GET /api/v1/public/storm` | Public splash, island login list and shared budget strip |
| `GET /api/v1/public/brief?include=grade,numbers,papers,agents&limit=100` | Splash grade, counts and globe records |
| `GET /api/v1/public/activity?after=N&limit=60` | Globe activity, refreshed every four seconds from `last_id` |
| `POST /api/v1/login` with `{island, password}` | Island sign-in |
| `GET /api/v1/islands/{island}` | Island page and explorer |
| `POST /api/v1/islands/{island}/settings` with `{evolution_enabled}` or `{mutation_enabled}` | Island evolution controls |
| `POST /api/v1/genomes` with `{island_id, parent_id, prompt, tools}` | Versioned agent edits |
| `GET /api/v1/papers/{paperId}` | Paper page and explorer |
| `GET /api/v1/runs/{runId}` | Run page and explorer; refreshed every three seconds while queued or running |
| `POST /api/v1/chat` with `{message}` | Disposable island chat |
| `POST /api/v1/papers/{paperId}/select` or `/deselect` with `{}` | Human paper selection |
| `POST /api/v1/likes` with `{target_kind, target_id}` | Shared persisted feedback toggle |
| `POST /api/v1/agents/{agent}` with `{fields: {active}}` | Archive or reactivate an island agent |

The browser does not call ingestion, run creation, swarm advancement or operator routes. Paper selection and agent changes use their existing server owners.

## Display behavior

The budget strip reads the public storm budget. It displays monthly spend, target, projected spend and mode, with “no new runs” when `runs_allowed` is false. A missing projection or mode can produce a labeled estimate.

The public splash reads storm, brief and activity without a session. Its grade and counts describe stored swarm activity. They are not evidence of scientific correctness. A failed brief or activity refresh retains the existing globe without identifying that failure on screen. Activity moves an agent's light between its island and paper; tool lookups can add papers, and reading completion returns the light home. Selected papers retain island connections.

The island page leads with paper output and current reading activity. The lineage outline supports search, active and archived filters, expandable ancestry, pages of thirty agents, one selected detail card and generation history. Agent detail shows effective research methods separately from versioned source provenance. Evolution and mutation controls use their reported server fields, not inferred settings. With evolution disabled, mutation controls are disabled.

The paper page displays every projected reading independently of the returned run window. Title and readings precede source metadata, assignments, runs and costs. Empty readings and unavailable readings have separate states. Assignment and run failures can still appear empty, and cost fallback can obscure unavailable data.

The run page leads with its reading or current status, then presents the stored event replay, genome snapshot and costs. `?step=N` selects a replay step. Replay uses event order and the event's input, output, tool or model badge, and locator. Available HTML sections can be highlighted by section and quote. A PDF page locator opens the browser PDF viewer at that page. Per-claim evidence quotes are displayed, but they do not yet have individual navigation links.

Chat displays `answer`, object links, `answer_id` and cost. Zero cost is labeled “from stored records.” Turns exist only in component state. Navigation is blocked while an answer is pending. The response's `supported` flag is not displayed, and linked retrieval alone can overstate synthesized support. Chat answers cannot yet receive the persisted feedback required by the specification.

## Text and provider limits

The server stores abstracts and available parsed arXiv HTML sections. When HTML is unavailable, it keeps the abstract and extraction reason. The paper page currently displays the available text status without the extraction reason. It does not synthesize missing full text.

The browser PDF viewer cannot highlight text inside a PDF. Without a configured model provider, the server serves stored data and refuses new model runs. The budget strip reports that refusal.
