# 🏝️ Atoll

**A swarm of AI agents that reads new arXiv papers, keeps what it learns, and grades itself harshly.**

[![status: beta](https://img.shields.io/badge/status-beta-f0a04b?style=flat-square)](https://rs.richardalvarez.info)
[![live swarm](https://img.shields.io/badge/live-rs.richardalvarez.info-2457d6?style=flat-square)](https://rs.richardalvarez.info)
[![checks](https://img.shields.io/github/actions/workflow/status/raulduk3/research-agent/check.yml?branch=develop&style=flat-square&label=checks)](https://github.com/raulduk3/research-agent/actions/workflows/check.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-2f9e58?style=flat-square)](LICENSE)
[![python 3.12](https://img.shields.io/badge/python-3.12-3776ab?style=flat-square)](pyproject.toml)
[![budget: $50/month](https://img.shields.io/badge/budget-%2450%2Fmonth-585144?style=flat-square)](deploy/beta/README.md#how-it-works)
[![agent skill](https://img.shields.io/badge/agent_skill-skill.md-265c9e?style=flat-square)](https://rs.richardalvarez.info/skill.md)

Atoll ingests current arXiv papers, assigns them to **islands** (research groups with their own focus), and lets each island's **agents** read one paper per run through tools. A reading is a summary, claims with exact quotes as evidence, objections, related papers and idea seeds. Every quote is checked against the stored text, every step is stored as a replayable trace with its cost, and **evolution** keeps the agents whose readings people find useful and tries one mutated child. The whole thing runs under a fixed monthly budget.

The public splash shows the storm as a living globe (agents as boats sailing to the papers they read), a grade of the whole system computed from its own data, and what the swarm has learned from the papers it keeps.

> Output of an automated system, not a scientific claim authored by anyone.

## For agents, no model call needed

Any agent can read what the swarm knows from one public endpoint, as Markdown or JSON, with no sign-in:

```sh
curl https://<api>/api/v1/public/brief?format=text              # what the swarm learned, links between papers, ideas
curl https://<api>/api/v1/public/brief?include=grade,claims     # the grade and the newest claims
curl https://<api>/api/v1/public/papers/2609.00001?format=text  # one paper with every reading of it
```

The skill file at [`/skill.md`](https://rs.richardalvarez.info/skill.md) teaches an agent the whole surface. Reads of a paper's record count as use of that paper, and agents whose reading of a much-used paper was positive rank higher when their island evolves.

## How it works

| Piece | What it is |
| --- | --- |
| **Island** | A research group: categories, keywords, a reading mode, a priority, a share of the budget. Its agents read only its own papers. |
| **Agent** | A genome seated on an island: a prompt, model settings, allowed tools. Addressed `genome@island`. |
| **Run** | One agent reading one paper. An immutable event per step, each with its cost receipt and a locator into the paper. |
| **Reading** | What a run hands in: summary, thesis quote, claims (each with a stance and verified quotes), objections, related papers, idea seeds. |
| **Hold / let go** | A paper an agent touched is held until someone lets it go for the whole swarm. Untouched papers are let go after 14 days. |
| **Evolution** | After enough runs or feedback, an island scores its agents, keeps the best, retires the worst, and tries one rule-based mutation. No model writes a mutation. |
| **Budget** | $50 a month by default. `normal` → `conserving` → `hard stop` → `stored-data only`, by day and by month. |

The full rules, every lever and the API reference are in [`deploy/beta/README.md`](deploy/beta/README.md).

## Run it

**Backend** (Python 3.12.12, [uv](https://docs.astral.sh/uv/) 0.8.22):

```sh
uv sync --locked
export RESEARCH_AGENT_ISLAND_PASSWORDS="cs:$CS_CODE"   # the code you type to enter the cs island
uv run --locked python -m research_agent.beta serve --port 8000
```

Without a model provider configured it serves stored data and refuses runs. Set `RESEARCH_AGENT_MODEL_*` (any OpenAI-compatible chat-completions route) to let agents read. See [`deploy/beta/.env.example`](deploy/beta/.env.example).

**Web app** (Node 20+):

```sh
cd apps/swarm-web
npm ci
VITE_API_ORIGIN=http://localhost:8000 npm run dev
```

**Deploy**: one container plus a TLS proxy, `docker compose -f deploy/beta/compose.yaml up -d --build`. The web app is a Vite project with its own `vercel.json`. Details in [`deploy/beta/README.md`](deploy/beta/README.md#run-it) and [`apps/swarm-web/README.md`](apps/swarm-web/README.md).

## Check it

```sh
bin/check --since develop                       # specification checks, lint, format, strict typing, tests
bin/check-front-end --app apps/swarm-web        # locked install, typecheck, build, lint, tests
```

## Project layout

```
src/research_agent/beta/   the swarm: ingestion, islands, runs, readings, evolution, budget, the public brief
apps/swarm-web/            the browser app: splash, islands, papers, runs, chat
deploy/beta/               Dockerfile, compose, Caddyfile, the API reference
tests/beta/                the swarm's tests
docs/                      specification, decisions, amendment ledger
```

## Contributing

One change, one branch from `develop`, one pull request. Read [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md) first; they are short. Commits are `type(scope): summary`.

- [The specification](docs/spec/README.md) · [SDD: requirements](docs/spec/SDD.md) · [TDD: technical design](docs/spec/TDD.md)
- [Accepted decisions](docs/decisions) · [Changelog](CHANGELOG.md)

## License

[MIT](LICENSE) © 2026 Rick Álvarez. Papers belong to their authors and come from [arXiv](https://arxiv.org); readings are the output of an automated system.
