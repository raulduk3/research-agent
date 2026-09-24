# Owner front end

This implements #340: the owner's pages as a React single-page app in
`front-end/`, reading and writing only `/api/v1` (`docs/contracts/api-v1/`),
built from the design mock and deployable to Vercel. It adds no server route and
changes no contract. The design mock it follows is kept, with its generator, at
`front-end/design-mock/` (`ALIGNMENT.md` traces each field to the contract).

## Owners

| Concern | Owner | Tests |
| --- | --- | --- |
| Envelope, refusal codes, credentialed fetch, CSRF and `Idempotency-Key` on POST, sign-in, 401 to `/login` | `src/api/client.ts` | `src/api/client.test.ts` |
| One GET per view, stale answers dropped; one POST per command, key reused for the same body | `src/api/useGet.ts`, `src/api/useCommand.ts` | `src/pages/Agent.test.tsx` |
| Response types generated from `docs/contracts/api-v1/*.json` | `scripts/gen-types.mjs` writes `src/api/schema.gen.ts` | `src/api/schema.gen.test.ts` |
| Owner shell, navigation, sign-in | `src/shell/Layout.tsx`, `src/shell/Login.tsx` | `src/shell/Login.test.tsx` |
| Overview, agents, agent (admit, retire), runs, run, trace, paper and embedding | `src/pages/*.tsx` | `src/pages/render.test.tsx`, `src/pages/Agent.test.tsx` |
| Reports, models, costs, digests (unrated entries blinded), seed | `src/pages/*.tsx` | `src/pages/render.test.tsx`, `src/pages/pages.test.tsx` |
| Styles | `src/styles/atoll.css`, copied from the mock's `dist/atoll.css` | none |

`render.test.tsx` mounts every route through the real app and client with every
GET refused, and asserts each page reads its own `/api/v1` path and shows the
refusal rather than failing or inventing data.

## Matching the mock

Each ported page has a skeleton test (`src/test/skeleton.ts`): the page's
content inside the shell's `<main>` must equal the mock page's body, minus its
menu and lab line, tag for tag and class for class. Text, attributes and list
lengths do not count. A mock section with no `/api/v1` route is removed from
both sides and listed here; the page leaves it out rather than showing mock data.

| Page | Mock | Not served |
| --- | --- | --- |
| Sign-in | `owner-login.html` | nothing |
| Owner home | `overview.html` | the papers the agents back most, the swarm link, the run board and agent tiles, the runs, digests and this-week cards, the identifier fold; the date line gives the health check's day, not the study day |
| Agents | `agents.html` | the runs, forecasts, rater credit, agreement and cost-per-run columns and the note on them; the lead counts the agents on the page rather than stating the study calendar |
| Agent | `agent.html` | the explore links, the day cards, the replay (#208), the runs table's duration and outcome columns; the forecasts table the port had is gone because the mock has none. The mock opens one run and the page opens every run, so the link column is compared out on both sides. The mock's island and reading-style lists are not in the edit or seed bodies; the page asks for the lineage those bodies require, compared out on its side |
| Run | `run.html` | the explore links, the replay (#208), the digest nominations; the run record carries no agent name, island, finish time or call counts, so the header names the agent by id and its cards give the start, budget, recorded steps and allowed tools. Steps are the recorded events by kind and payload hash, not the agent's notes and tool calls; submissions are one row per sealed claim with its chance, not a row per paper with three chances |
| Costs | `costs.html` | spend per day, each island's share of the month, pausing paid execution, the islands table, skill per dollar, the launch profile fold. Reservations, the summarizer and scholarly-API sublimits and the paid-execution start time are not in the costs body, so the cap bars show settled spend against the daily and monthly caps only. Cost per run is settled spend over priced runs for the month; the per-agent table's third column gives unpriced runs and their tokens, and the identifier fold lists each agent's id. The page's day picker sits in the section line, compared out on its side |
| Report | `report.html` | the replay (#208), the explore links, agreement with the prediction heads, the owner's forecasts beside the agents', the selection box, the health checks. The report body names genomes by hash only, so an agent is its founder mark and short hash; its skill columns are the report's targets. Migrations and the preference-credit reason join the note under the agents table. The owner reads a report by island and week, so the page is the same for every island and the other islands line names them without links |

The health line (`footer.diag`) that ends each owner page is `src/shell/Diag.tsx`, bound to `/api/v1/health`.

## Commands

```sh
cd front-end
npm ci
npm run gen:types          # regenerate src/api/schema.gen.ts from the contract schemas
node scripts/gen-types.mjs --check   # fail if the generated types are stale
npm run check              # typecheck, lint, tests
npm run dev                # local server; set VITE_API_ORIGIN in .env.local
npm run build              # static build in dist/
```

## Deploying

`vercel.json` builds with `npm ci && npm run build`, publishes `dist/`, and
rewrites every path to `index.html` so client routes load directly. Set the
project root to `front-end/` and `VITE_API_ORIGIN` to the owner API's origin.
That origin must answer with credentialed CORS for the published origin (the
launch profile's `front_end_origin`), because the session cookie is sent with
`credentials: "include"`. Nothing here deploys; publishing is the owner's step.

## Known gaps

- The weekly report route is served by `src/research_agent/web/report/app.py`,
  a separate app from the owner app in `src/research_agent/web/app.py`. The
  client has one `VITE_API_ORIGIN`, so it assumes one origin fronts both (a
  proxy or rewrite). Until then the report pages need that front.
- Swarm replay, impact and islands have no `/api/v1` route; their links render
  a page saying so (`src/pages/NotServed.tsx`).
- The CSRF token is held in memory from sign-in or any form view. After a page
  reload, a POST from a page with no form view (sign-out) is refused client-side
  until a form view or sign-in supplies the token again.
