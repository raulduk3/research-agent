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
