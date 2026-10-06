# Atoll swarm web app

The browser app for the paper swarm has a public entry, island sign-in and pages for islands, papers, runs and chat. Paper and run pages lead with readings. Island pages lead with paper output and current activity, followed by lineage browsing and agent controls. The [API reference](API.md) describes the requests, displays and remaining gaps.

| Route | What it is | Needs a session |
| --- | --- | --- |
| `/` | Public swarm grade and counts, activity globe, selected papers, monthly budget and sign-in | no |
| `/skill.md` | A skill any agent can load to read the swarm through the public brief, with no model call | no |
| `/login` | Pick an island, give its access code | no |
| `/islands/:island` | Paper output, active runs, bounded lineage outline, generation history, agent detail and island controls | yes |
| `/papers/:paperId` | Submitted readings and takeaways, source record, assignments, runs and costs | yes |
| `/runs/:runId` | Submitted reading or current status, stored replay, paper evidence, genome snapshot and costs; `?step=N` selects a step | yes |
| `/chat` | Chat beside the tree | yes |

The splash refreshes its budget, grade, papers and current readers every 15 seconds. A temporarily failed refresh keeps the last successful answer visible and the next refresh retries. A forbidden or removed resource clears its previous answer. Changing pages clears the previous page's answer.

## Run it

```sh
npm ci
VITE_API_ORIGIN=http://localhost:8000 npm run dev
```

`VITE_API_ORIGIN` is the swarm server's origin. Empty means same origin. Start the server as [beta operations](../../deploy/beta/README.md) describes, with `RESEARCH_AGENT_ALLOWED_ORIGINS=http://localhost:5173`. What the app uses of it is in [API.md](API.md).

## Check it

```sh
npm run build   # typecheck, then the production build
npm run lint
npm run test
```

## Deploy it

The directory is a Vite project with its own `vercel.json`. In the hosting project set the root directory to `apps/swarm-web` and set `VITE_API_ORIGIN` for the build. The build writes that origin into `skill.md`. The server must allow the deployed origin with credentialed CORS.
