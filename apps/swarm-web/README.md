# Atoll swarm web app

The browser app for the paper swarm: a public splash, an island sign-in, and four pages behind it. You edit agents and watch runs. It is chat plus a tree explorer down the cascade island → paper → run → step, with cost shown at every level.

| Route | What it is | Needs a session |
| --- | --- | --- |
| `/` | Public splash: the storm as a globe, counts, the month's budget, the way in | no |
| `/login` | Pick an island, give its access code | no |
| `/islands/:island` | Agents (editable), evolution, runs, papers, island cost and budget share | that island |
| `/papers/:paperId` | The paper cascade: record, islands, runs, steps, cost by island and by run | yes |
| `/runs/:runId` | The paper viewer with the run's stored steps replayed beneath it; `?step=N` opens at a step | yes |
| `/chat` | Chat beside the tree | yes |

## Run it

```sh
npm ci
VITE_API_ORIGIN=http://localhost:8000 npm run dev
```

`VITE_API_ORIGIN` is the swarm server's origin. Empty means same origin. What the app expects from that server is in [API.md](API.md).

## Check it

```sh
npm run build   # typecheck, then the production build
npm run lint
npm run test
```

## Deploy it

The directory is a Vite project with its own `vercel.json`. In the hosting project set the root directory to `apps/swarm-web` and set `VITE_API_ORIGIN` for the build. The server must allow the deployed origin with credentialed CORS.
