# Swarm browser API reference

The browser calls the beta FastAPI server at `VITE_API_ORIGIN`. Paths below include `/api/v1`. The server implementation and operator routes are documented in [beta operations](../../deploy/beta/README.md).


The executable definitions for the fields the browser consumes are [the Zod contracts](src/api/contracts.ts). [TypeScript types](src/api/types.ts) are inferred from them. The transport validates outgoing write bodies and incoming successful responses before a page consumes them. Response schemas allow additional server fields. A malformed or empty successful response produces a contract error; the browser cannot infer whether a write committed from that error. [Contract tests](src/api/contracts.test.ts) check real Python API requests and responses, alongside the server's behavior tests.

## Transport and scope

Requests send `credentials: "include"`; credentialed CORS requires the browser origin in `RESEARCH_AGENT_ALLOWED_ORIGINS`. After login, protected requests carry `Authorization: Bearer <token>`. The browser stores the session in local storage until sign-out or authentication refusal. A 401 clears it.

Sessions can read other islands. Agent edits, archive actions and island settings are restricted to the session's island. Other islands show disabled evolution controls. A session may select or deselect a paper assigned to its island; that override applies across the swarm. Protected pages do not request their data before sign-in.

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
| `POST /api/v1/papers/{paperId}/select` or `/deselect` with `{}` | Paper-detail selection override; refreshes the paper after each change |
| `POST /api/v1/likes` with `{target_kind, target_id}` | Shared persisted feedback toggle |
| `POST /api/v1/agents/{agent}` with `{fields: {active}}` | Archive or reactivate an island agent |

The browser does not call ingestion, run creation, swarm advancement or operator routes. Paper selection and agent changes use their existing server owners.

## Display behavior

The budget strip reads the public storm budget. It displays monthly spend, target, projected spend and mode, with “no new runs” when `runs_allowed` is false. A missing projection or mode can produce a labeled estimate.

The public splash reads storm, brief and activity without a session. Its grade and counts describe stored swarm activity. They are not evidence of scientific correctness. A failed brief or activity refresh retains the existing globe without identifying that failure on screen. Activity moves an agent's light between its island and paper; tool lookups can add papers, and reading completion returns the light home. Selected papers retain island connections.

The island page shows kept, unreleased papers first, once each, with agent or person attribution. Other papers and current runs follow. Agents, lineage and settings are inside the collapsed "Agents and evolution" details, which opens for an agent link. The lineage outline supports search, active and archived filters, expandable ancestry, pages of thirty agents and one selected detail card. Cycle decision diagnostics are omitted. Agent detail shows effective research methods separately from versioned source provenance. Island cost and budget summaries follow the paper output and controls.

Evolution and mutation controls use their reported server fields. Both are disabled for another island's session and while a settings request is pending. With island evolution off, mutation has no effect and its switch is disabled. When the operator pauses evolution for the whole swarm, the browser reports that pause; the island's evolution setting remains editable and takes effect when the operator resumes it. A successful change refreshes the island and displays the stored setting.

The paper page displays every projected reading independently of the returned run window. Its title and readings precede source metadata and the paper cost summary, followed by assignments and runs. Empty readings and unavailable readings have separate states. Selection uses the signed-in island's assignment directly, including papers omitted from its catalog after deselection. The override appears only when assignments are available and that assignment reports `kept`, including null while agents read. Assignment and run query failures can still appear empty, and cost fallback can obscure unavailable data.

Normal paper, island and agent run lists omit failed attempts. Failed runs can be opened directly at `/runs/{runId}` for their failure status, event replay and costs during the 24-hour retention window. Startup and heartbeats remove failed attempts without submitted readings after that window, including their events and notes. Their cost receipts and attribution remain in accounting; hiding an attempt from a list does not erase its charge.

The run page leads with its reading or current status, then presents the stored event replay, genome snapshot and costs. `?step=N` selects a replay step. Replay uses event order and the event's input, output, tool or model badge, and locator. Available HTML sections can be highlighted by section and quote. A PDF page locator opens the browser PDF viewer at that page. Per-claim evidence quotes are displayed, but they do not yet have individual navigation links.

Chat displays `answer`, object links, `answer_id` and cost. Zero cost is labeled “from stored records.” Turns exist only in component state. Navigation is blocked while an answer is pending. The response's `supported` flag is not displayed, and linked retrieval alone can overstate synthesized support. Chat answers cannot yet receive the persisted feedback required by the specification.

## Text and provider limits

The server stores abstracts and available parsed arXiv HTML sections. When HTML is unavailable, it keeps the abstract and extraction reason. The paper page currently displays the available text status without the extraction reason. It does not synthesize missing full text.

The browser PDF viewer cannot highlight text inside a PDF. Without a configured model provider, the server serves stored data and refuses new model runs. The budget strip reports that refusal.
