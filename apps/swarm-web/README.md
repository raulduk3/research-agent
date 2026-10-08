# Atoll swarm web app

The browser app for the paper swarm has a public entry, island sign-in and pages for islands, papers, runs and chat. Paper and run pages lead with readings. Island pages show kept papers first, then other papers and runs. Agent lineage and settings are in collapsed details, with cost and budget summaries below the paper output. The [API reference](API.md) describes the requests, displays and remaining gaps.

| Route | What it is | Needs a session |
| --- | --- | --- |
| `/` | Public swarm grade and counts, activity globe, selected papers, monthly budget and sign-in | no |
| `/skill.md` | A skill any agent can load to read the swarm through the public brief, with no model call | no |
| `/login` | Pick an island, give its access code | no |
| `/islands/:island` | Kept papers for future reference, other papers, runs, and collapsed agent lineage and settings | yes |
| `/papers/:paperId` | Submitted readings and takeaways, source record, assignments, runs and costs | yes |
| `/runs/:runId` | Submitted reading or current status, stored replay, paper evidence, genome snapshot and costs; `?step=N` selects a step | yes |
| `/chat` | Chat beside the tree | yes |

The splash refreshes its budget, grade, papers and current readers every 15 seconds. A temporarily failed refresh keeps the last successful answer visible and the next refresh retries. A forbidden or removed resource clears its previous answer. Changing pages clears the previous page's answer.

Evolution controls are disabled for another island's session. Turning island evolution off also disables mutation. An operator pause stops automatic cycles across the swarm while preserving island settings. Normal paper, island and agent run lists omit failed attempts; a failed run's direct replay remains available during its 24-hour retention window. Cleanup removes failed attempts without submitted readings, while retaining their cost receipts. Paper-detail selection uses the signed-in island's assignment and refreshes that paper after a change.

## Run it

```sh
npm ci
VITE_API_ORIGIN=http://localhost:8000 npm run dev
```

`VITE_API_ORIGIN` is the swarm server's origin. Empty means same origin. Start the server as [beta operations](../../deploy/beta/README.md) describes, with `RESEARCH_AGENT_ALLOWED_ORIGINS=http://localhost:5173`. What the app uses of it is in [API.md](API.md).

## Check it

The tests call the real Python API on a temporary SQLite store and validate its requests and responses against [the Zod contracts](src/api/contracts.ts). Install Python 3.12.12 and uv 0.8.22, then run `uv sync --locked` from the repository root before the browser tests. No live provider or external database is needed for these contract tests.

```sh
npm run build   # typecheck, then the production build
npm run lint
npm run test
```

## Deploy it

The directory is a Vite project with its own `vercel.json`. In the hosting project set the root directory to `apps/swarm-web` and set `VITE_API_ORIGIN` for the build. The build writes that origin into `skill.md`. The server must allow the deployed origin with credentialed CORS.
