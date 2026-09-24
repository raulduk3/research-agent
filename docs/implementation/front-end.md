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
| The mock's graphics: chance bar, dots, cards, run board, agent tiles, reader lane, spend chart, island canvas, swarm replay and its live stream | `src/graphics/*.tsx`, `src/graphics/swarm/` | `src/graphics/graphics.test.tsx`, `src/graphics/swarm/swarm.test.tsx` |
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
| Owner home | `overview.html` | the papers the agents back most, the run board's lanes, the runs, digests and this-week cards; the date line gives the health check's day, not the study day. `/api/v1/day` now serves each run created on a UTC day with its genome's island and lineage, its stored ending and end instant, and each digest built on it with its entries and the rated ones, which the run board, the agent tiles and the runs and digests cards count. The this-week card sums the latest ISO week's rows in `/api/v1/reports` (digests, entries, ratings, credits) and `/api/v1/impact` (likes, dislikes, skips) over the islands, and the identifier fold lists each genome's hash from `/api/v1/genomes`. No worker container is stored, so the board draws one lane per island rather than per container, each run from its creation to its end instant in its agent's hue, a void run in the no-answer colour. Without the day read the board has no lanes and the tiles and cards read "not served yet". The papers the agents back most are a mean chance and an agreement over the day's claims, derived scores, and are not served; the study day and control period are the profile's calendar, not a stored record; the report's verdict on the this-week card is built on request and is not served here |
| Agents | `agents.html` | the agreement column, which is not stored; the lead counts the agents on the page rather than stating the study calendar. The runs, forecasts, rater credit and cost-per-run columns come from `/api/v1/genomes`: every stored run with the void ones named, the forecasts, the preference credits with their share, and settled cost over priced runs. Those counts are all-time, not the mock's seven days or this week, so the headings drop the window; an agent the read does not name, or a refused read, leaves them "not served yet" |
| Agent | `agent.html` | the forecasts and rater-credit cards, agreement with the heads, the replay (#208). The explore links lead to the runs, islands and reports pages and the agent's latest run. The owner actions keep their forms, disabled until the agent is read. The reading-style list is the four launch emphases (TDD genome emphasis) plus the agent's own lineage, and is the lineage the edit and seed bodies send; an edit's island is shown and fixed, since the edit body names none. The runs today and in the seven days ending today (UTC), with the void ones, and cost per run (all-time settled cost over priced runs) come from `/api/v1/genomes/{configuration_id}/runs`, which also fills the runs table with each run's stored ending, void reason and settled cost; without it the table is the inspector's runs and those cards and columns read "not served yet". No duration is stored, so a duration is the page's reading of the creation and end instants. Forecasts made and rater credit this week are not in that read. The mock opens one run and the page opens every run, so the link column is compared out on both sides. The mock's island and reading-style lists are not in the edit or seed bodies; the page asks for the lineage those bodies require, compared out on its side |
| Run | `run.html` | the last explore link, the nominated papers and their reasons; the run record carries no agent name, so the header names the agent by id. Its cards give the start, budget, recorded steps and allowed tools from the run read, then the stored ending (with the void reason), the trace's tool calls with the refused ones counted and the settled cost from `/api/v1/runs/{run_id}/record`, which also names the island in the lead and the explore link. The mock's model calls, deep reads and images, time and context cards are not in that read. The nominations table lists the digest entries the run's claims were nominated to, each with its digest, island, build instant and preference; the entry names no paper and no reason, so those are not served. Without the record those cards and the table read "not served yet". Steps are the recorded events by kind and payload hash, not the agent's notes and tool calls; submissions are one row per sealed claim with its chance, not a row per paper with three chances. The agent name and the replay stay not served |
| Costs | `costs.html` | spend by source, each island's share of the month, pausing paid execution, the islands table, skill per dollar, the launch profile's six sections. Reservations, the summarizer and scholarly-API sublimits and the paid-execution start time are not in the costs body, so the cap bars show settled spend against the daily and monthly caps only. Cost per run is settled spend over priced runs for the month; the per-agent table's third column gives unpriced runs and their tokens, and the identifier fold lists each agent's id. The mock has no day picker, so the day is `?day=YYYY-MM-DD` and the server picks today (UTC) without it. The spend chart draws each UTC day of the month from `/api/v1/costs/days`, its islands summed; island shares, the islands table and the paid-execution flag are already in the costs body. Skill per dollar is a derived score and stays not served |
| Report | `report.html` | the replay (#208), agreement with the prediction heads, the owner's forecasts beside the agents', the health checks. The report body names genomes by hash only, so an agent is its founder mark and short hash; its skill columns are the report's targets. Migrations and the preference-credit reason join the note under the agents table. The owner reads a report by island and week, so the page is the same for every island and the other islands line names them without links. The selection box reads `/api/v1/reports/{island}/{iso_week}/selection`: the genomes archived in the week with the skill and support they were archived on, then the genomes admitted in it. Agreement with the heads is a derived score and is not served. The health checks are answered live and not stored by island or week, so they are not served. A human forecast is sealed with its rater as submitter and an owner session carries no rater id, so the owner's forecasts are not served. |
| Paper | `paper-P1.html` | the title, abstract and arXiv link, the parts map and PDF, the rater's call, the summarizer's reading, the baselines, the authors, the content assessment, the paper's days and their replay (#208). The five panels show one at a time, chosen by the tabs and step links. The conversation is one turn per run with its chance on each question, by agent id, since the owner sees who read it; the read tiles are each forecast's reason, linked to the run's tool calls. The paper's requests, pinned cards and embedding are its record page (`/papers/:paperId/record`), linked from the "More" fold. The mock's `reading-*.html` pages are each run's own page (`run.html`). `/api/v1/owner/papers/{paper_id}/documents` now lists the retained PDFs the family's pinned cards came from, each with the path of its exact bytes at `/api/v1/owner/documents/{artifact_hash}` (`application/pdf`, 404 for any other artifact), but the page does not yet read them. The owner paper read's cards carry the snapshot, version and card hashes only; the title, abstract and arXiv id are inside the card artifact and are not served as fields. Each pinned card now carries the content assessment section its snapshot pins for the version (`assessment_section_hash`, null when none), but the page does not yet read it. The rater's call is stored (`ratings`, keyed by the digest entry's paper hash, with no stored link to a paper family) and is not served: the rating guard withholds other raters' figures from an owner session, so serving it needs the owner's decision. The summarizer's reading, rater flags, the baselines and the authors have no stored table and are not served |
| Model | `models.html` | the model list, the prediction heads and their calibration, the training corpus, the agent model, the summarizer, spending and the content assessments. The heads' own page (`head.html`) has no route either. `/api/v1/models` now lists each agent model manifest a stored run pins, with its run count and first and latest run instants, but the page does not yet read it, so the menu entry still opens one manifest by its hash; the heads, their calibration, the training corpus, the summarizer, spending and the content assessments are not listed; the manifest takes the embedding section's place, its kind as the heading and its fields as the table. |

Mock pages served but not yet ported: `islands.html` (`/api/v1/islands`), `island.html` (`/api/v1/islands/{island}`), `reports.html` (`/api/v1/reports`; the page is still a lookup form for one island and week, and the mock's State and Headline columns are not served because a report is built on request), `questions.html` and `question-*.html` (`/api/v1/questions`, `/api/v1/questions/{question_id}`), `impact.html` (`/api/v1/impact`: each island and rating week's ratings by value, credit rows, genomes credited and credit gaps; the uncalled count, the per-call list and the table of calls to change are not served, because no record holds an uncalled paper and a call cannot yet be changed). Mock pages with no `/api/v1` route at all (`docs/contracts/api-v1/endpoints.json`) are not ported: `swarm.html`. Paths without a ported page render `src/pages/NotServed.tsx`.

## Graphics

Each drawn element of the mock is one component in `src/graphics/` (#353), drawn
only from `/api/v1` values and drawn empty (axes, frames and labels, no marks)
without them. Each has a render test over a fixture and an empty-state test.

- `ChanceBar`, `Dot`, `Cards`: the tables' chance bars (`span.pb`), the state dots and the card grid, on every page that shows them.
- `Board`, `Tiles`: the owner home's run board and agent tiles. The tiles are the agents by island, from `/api/v1/agents`; no route serves the day's runs, so the board keeps its axis and no lanes.
- `ReaderLane`: the paper's replay stage, one lane per question with its forecasts on the chance axis and its runs' events on the timeline. There is no question page to carry it.
- `SpendChart`: the costs page's settled spend. The costs body serves one day and no split by source, so the chart draws that day's bar in one colour against the caps.
- `IslandCanvas`: the island and swarm drawing on a `canvas`, tested through `vitest-canvas-mock` (`src/test/setup.ts`).
- `swarm/Swarm.tsx`: the swarm replay (canvas, play and pause, scrubber, speed) over one run, on the run page. Its steps are the run's recorded events from `/api/v1/runs/{id}`; its sealed chances are the run's submissions. The run record carries no island, so the island is the one the live stream names, or "island not read".
- `swarm/useRunStream.ts`: follows the run on `GET /api/v1/owner/runs/live?run_id=` (#327) with an `EventSource`, drops repeated ids, and closes on the run's ending or a refused stream. While it is open the replay follows its head. `src/api/schema.gen.ts` does not carry `owner-run-event.json`, so the hook types the fields it reads locally; #345 should generate the type and the hook should import it.

The island and swarm pages themselves stay `NotServed`: their routes live in `src/App.tsx`, and no route serves papers' positions or a population's runs.

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
- The swarm page has no `/api/v1` route; its path renders a page saying so
  (`src/pages/NotServed.tsx`). The swarm replay is drawn for one run on its run
  page. Islands, one island, the reports index, questions, impact and the
  models list are served but their pages are not yet ported.
- The ported owner home, agents, agent, run, costs, report, model and paper
  pages do not yet read the routes added for them (#344); their rows above
  name each route and what it serves.
- The CSRF token is held in memory from sign-in or any form view. After a page
  reload, a POST from a page with no form view (sign-out) is refused client-side
  until a form view or sign-in supplies the token again.
