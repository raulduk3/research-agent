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
| Owner shell, navigation, sign-in | `src/shell/Layout.tsx`, `src/shell/Login.tsx` | `src/shell/Layout.test.tsx`, `src/shell/Login.test.tsx` |
| Overview, agents, agent (admit, retire), runs, run, trace, paper, its record and embedding | `src/pages/*.tsx` | `src/pages/render.test.tsx`, `src/pages/refused.test.tsx`, `src/pages/Agent.test.tsx` |
| Reports, models, costs, digests (unrated entries blinded), seed | `src/pages/*.tsx` | `src/pages/render.test.tsx`, `src/pages/pages.test.tsx` |
| Styles | `src/styles/atoll.css`, copied from the mock's `dist/atoll.css` | none |

`render.test.tsx` mounts every route through the real app and client with every
GET refused, and asserts each page reads its own `/api/v1` path and shows the
refusal rather than failing or inventing data.

## Matching the mock

Every ported page renders every section of its mock page, in the mock's order,
with the mock's classes, whatever the API says. A section no `/api/v1` route
fills keeps its heading, table heads and meta lines and says "not served yet"
where its values would be. A refused read does not replace the sections: the
refusal takes the lead's place (`p.lead`, `src/pages/common.tsx`), and the health
line names a refused health read. The shell (`src/shell/Layout.tsx`) renders the
menu, the health line and the lab line on every page; each page ends its content
with the identifier fold (`details.ids`).

`src/pages/refused.test.tsx` mounts each page below through the real app with
every read refused and compares the whole page, menu, health line and lab line
included, with the mock page's body: tag for tag and class for class, text and
attributes stripped. The page tests compare the same shape with data present.
Only list lengths are free (`LIST_ITEMS` in `src/test/skeleton.ts`): a table's
data rows, a chart's marks and the entries of the mock's boards, tiles, section
chips, page links, reader turns, read tiles and paper days may number zero or
more. There is no list of sections a page may leave out.

| Page | Mock | Rendered empty |
| --- | --- | --- |
| Sign-in | `owner-login.html` | nothing |
| Owner home | `overview.html` | the papers the agents back most, the run board and agent tiles, the runs, digests and this-week cards; the date line gives the health check's day, not the study day |
| Agents | `agents.html` | the runs, forecasts, rater credit, agreement and cost-per-run columns; the lead counts the agents on the page rather than stating the study calendar |
| Agent | `agent.html` | the day cards, the replay (#208), the runs table's duration and outcome columns. The explore links lead to the runs, islands and reports pages and the agent's latest run. The owner actions keep their forms, disabled until the agent is read. The reading-style list is the four launch emphases (TDD genome emphasis) plus the agent's own lineage, and is the lineage the edit and seed bodies send; an edit's island is shown and fixed, since the edit body names none |
| Run | `run.html` | the replay (#208), the digest nominations, the last explore link; the run record carries no agent name, island, finish time or call counts, so the header names the agent by id and its cards give the start, budget, recorded steps and allowed tools. Steps are the recorded events by kind and payload hash, not the agent's notes and tool calls; submissions are one row per sealed claim with its chance, not a row per paper with three chances |
| Costs | `costs.html` | spend per day, each island's share of the month, pausing paid execution, the islands table, skill per dollar, the launch profile's six sections. Reservations, the summarizer and scholarly-API sublimits and the paid-execution start time are not in the costs body, so the cap bars show settled spend against the daily and monthly caps only. Cost per run is settled spend over priced runs for the month; the per-agent table's third column gives unpriced runs and their tokens, and the identifier fold lists each agent's id. The mock has no day picker, so the day is `?day=YYYY-MM-DD` and the server picks today (UTC) without it |
| Report | `report.html` | the replay (#208), agreement with the prediction heads, the owner's forecasts beside the agents', the selection box, the health checks. The report body names genomes by hash only, so an agent is its founder mark and short hash; its skill columns are the report's targets. Migrations and the preference-credit reason join the note under the agents table. The owner reads a report by island and week, so the page is the same for every island and the other islands line names them without links |
| Paper | `paper-P1.html` | the title, abstract and arXiv link, the parts map and PDF, the rater's call, the summarizer's reading, the baselines, the authors, the content assessment, the paper's days and their replay (#208). The five panels show one at a time, chosen by the tabs and step links. The conversation is one turn per run with its chance on each question, by agent id, since the owner sees who read it; the read tiles are each forecast's reason, linked to the run's tool calls. The paper's requests, pinned cards and embedding are its record page (`/papers/:paperId/record`), linked from the "More" fold. The mock's `reading-*.html` pages are each run's own page (`run.html`) |
| Model | `models.html` | the model list, the prediction heads and their calibration, the training corpus, the agent model, the summarizer, spending and the content assessments. No route lists the models, so the menu entry opens one manifest by its hash; the manifest takes the embedding section's place, its kind as the heading and its fields as the table. The heads' own page (`head.html`) has no route either |

Mock pages with no `/api/v1` route at all (`docs/contracts/api-v1/endpoints.json`) are not ported: `questions.html` and `question-*.html`, `reports.html` (the page is a lookup form for one island and week instead), `impact.html`, `islands.html` and `island.html`, `swarm.html`. Their paths render `src/pages/NotServed.tsx`.

The menu is the mock's nav element for element (`src/shell/Layout.test.tsx` compares it with `overview.html`): the brand, the rating app's today, accepted and about links, then the `more` dropdown whose summary names the current page and whose last link logs out. A page under no menu entry, such as a paper, shows the summary as only "more", as `paper-P1.html` does. The rating app is not served from the owner origin, so its three links render without a target.

The health line (`footer.diag`) that ends each owner page is `src/shell/Diag.tsx`, bound to `/api/v1/health` and rendered by the shell. It renders on every page: while the read waits or when it is refused, the footer keeps its summary and grid with empty values and names the refusal.

The mock's stylesheet is committed at `design-mock/dist/atoll.css` so the reference pages render styled when served.

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
- Swarm replay, impact, islands and questions have no `/api/v1` route; their
  paths render a page saying so (`src/pages/NotServed.tsx`).
- The CSRF token is held in memory from sign-in or any form view. After a page
  reload, a POST from a page with no form view (sign-out) is refused client-side
  until a form view or sign-in supplies the token again.
