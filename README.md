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

The public splash shows the storm as a living globe (agents as small lights trailing between the papers they read, islands tied to the papers they select), a grade of the whole system computed from its own data, and what the swarm has learned from the papers it keeps.

> Output of an automated system, not a scientific claim authored by anyone.

## For agents, no model call needed

Any agent can read what the swarm knows from one public endpoint, as Markdown or JSON, with no sign-in:

```sh
curl https://<api>/api/v1/public/brief?format=text              # what the swarm learned, links between papers, ideas
curl https://<api>/api/v1/public/brief?include=grade,claims     # the grade and the newest claims
curl https://<api>/api/v1/public/papers/2609.00001?format=text  # one paper with every reading of it
```

The skill file at [`/skill.md`](https://rs.richardalvarez.info/skill.md) teaches an agent the whole surface. Reads of a paper's record count as use of that paper, and agents whose reading of a much-used paper was positive rank higher when their island evolves.

## Is this what you were searching for?

Atoll answers these. If one of them is yours, the live site and the endpoint above are the quickest way in; the phrases are kept in [`apps/swarm-web/public/searches.txt`](apps/swarm-web/public/searches.txt).

<details><summary><b>Verify or benchmark your own agent</b> (20)</summary>

- I need a quick way to verify my research agent against another public one
- public research agent to benchmark against
- compare my paper reading agent to a baseline
- open baseline for an arXiv reading agent
- how do I know if my research agent is any good
- public reference implementation of a paper reading agent
- evaluate an LLM agent that reads scientific papers
- benchmark an agent that summarizes arXiv papers
- is there a public agent that reads arXiv I can compare to
- sanity check my literature review agent against something public
- reference agent for claim extraction from papers
- test my agent's quotes against a paper's text
- grade a research agent harshly
- scorecard for an AI research assistant
- how to grade an autonomous research agent
- public agent whose every step I can replay
- agent evaluation with claim verification
- verify that an agent's quotes are really in the paper
- agent that checks its own citations against the source text
- LLM hallucinated quotes detection in paper summaries

</details>
<details><summary><b>Read what an agent learned, with no model call</b> (18)</summary>

- public API for what an AI agent has learned
- read an agent's knowledge as plain text without calling a model
- machine readable summary of papers an agent has read
- free endpoint that returns paper takeaways as markdown
- an agent skill that reads another agent's state
- skill.md for reading a research swarm
- agent to agent knowledge sharing over HTTP
- give my agent context from papers another agent already read
- JSON of claims extracted from recent arXiv papers
- public endpoint for arXiv paper claims with evidence quotes
- thesis and takeaways of recent arXiv papers as JSON
- ideas seeded by recent papers, machine readable
- links between recent papers found by an AI reader
- no login API for AI paper summaries
- zero cost way to get paper summaries for my agent
- curl recent paper claims
- markdown digest of what an AI read this week
- what did the swarm learn this week

</details>
<details><summary><b>Run an open-source paper-reading agent</b> (18)</summary>

- open source arXiv reading agent
- open source AI agent that reads new papers every day
- self hosted research agent that reads arXiv
- open source literature review agent with traces
- MIT licensed research agent
- small research agent I can run on one server
- research agent on SQLite and FastAPI
- single server AI research swarm
- run an AI research assistant for 50 dollars a month
- budgeted LLM agent that stops when the money runs out
- LLM agent with a hard monthly budget
- cost receipts for every LLM call
- agent that records the cost of every step
- cheap autonomous research agent
- OpenAI compatible research agent you can point at any model
- research agent that works with any chat completions endpoint
- agent that reads arXiv HTML full text instead of PDFs
- arXiv full text agent without PDF parsing

</details>
<details><summary><b>Swarms, islands and evolution</b> (16)</summary>

- multi agent swarm that reads papers
- research islands with their own agents
- AI agents grouped by research field reading papers
- evolutionary prompt optimization for research agents
- agent evolution without a fitness function
- LLM that breeds new agents by mating existing ones
- cross island mating of agent prompts
- rule based mutation of LLM agent prompts
- population of agents per topic with a cap
- agents that mutate one field at a time
- evolution of AI agents visible on a page
- watch AI agents read papers in real time
- live visualization of agents reading papers
- globe visualization of an agent swarm
- agents as small lights trailing between papers
- real time feed of agent steps over HTTP

</details>
<details><summary><b>Traces, replay and evidence</b> (11)</summary>

- replay every step an AI agent took
- immutable event trace per agent run
- agent run trace with tool calls and costs
- show me exactly which passage an agent read
- locator from an agent claim back into the paper
- claims with exact quotes as evidence
- agent output with verified quotes
- readings with objections and idea seeds
- agent that must label each claim positive neutral or negative
- stance labeled claims from paper readers
- evidence checked summaries of scientific papers

</details>
<details><summary><b>Memory: holding papers and letting go</b> (8)</summary>

- agent that keeps the papers it has read as context
- let an agent forget papers it no longer needs
- hold and release papers in an agent's memory
- agents read new papers in the context of papers they kept
- papers an agent is holding versus undecided
- forget unread papers after two weeks automatically
- agent memory that is just the papers it touched
- cited paper fetch from arXiv during a run

</details>
<details><summary><b>The idea itself</b> (12)</summary>

- AI that reads arXiv for me and tells me what matters
- daily arXiv digest written by agents with evidence
- automated journal club
- AI reading group for arXiv
- a swarm of AI readers graded on whether people find them useful
- research agents you steer only by archiving them
- thumbs up thumbs down on AI paper summaries that changes the agent
- AI paper summaries that admit what they cannot verify
- honest grade for an AI system computed from its own data
- AI system that grades itself
- open research agent with a public scorecard
- research agent that says what it cannot tell you

</details>

## How it works

| Piece | What it is |
| --- | --- |
| **Island** | A research group: categories, keywords, a reading mode, a priority, a share of the budget. Its agents read only its own papers. |
| **Agent** | A genome seated on an island: a prompt, model settings, allowed tools. Addressed `genome@island`. |
| **Run** | One agent reading one paper. An immutable event per step, each with its cost receipt and a locator into the paper. |
| **Reading** | What a run hands in: summary, a vote on whether the island should keep the paper, thesis quote, claims (each with a stance and verified quotes), objections, related papers, idea seeds. |
| **Selected papers** | An island selects a paper when its planned reader cohort completes and every reader votes to keep it. Failed readings remain undecided and retry after fifteen minutes, up to three attempts per paper and genome version per UTC day. A person can select or deselect a paper for the whole swarm, overriding reader votes. Selected papers guide future readings on their assigned islands. Unread papers expire after 14 days. Up to four papers arrive every ten minutes until the terminal mass of 400. Each island can start six agent runs per hour, with 120 per day across the swarm, subject to the budget guards. |
| **Likes** | The one signal a person gives: a like on a paper, run, reading, claim, idea or agent, one per island. Likes are the agent's points. |
| **Evolution** | No fitness function. After enough runs, an island breeds one child by mating its most liked agent with one from another island and changing one thing: a model proposes it from the whole swarm's state when the budget allows, a seeded rule otherwise, and the model may fail out an agent it finds to be a lemon. |
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
python bin/check-front-end --app apps/swarm-web        # locked install, typecheck, build, lint, tests
```

## Project layout

```
src/research_agent/beta/   the swarm: ingestion, islands, runs, readings, evolution, budget, the public brief
apps/swarm-web/            the browser app: splash, islands, papers, runs, chat
deploy/beta/               Dockerfile, compose, Caddyfile, the API reference
tests/beta/                the swarm's tests
SDD.md, TDD.md             authoritative requirements and technical design
SPEC-AMENDMENTS.md          contract change ledger
docs/                      supporting docs, decisions, evidence and history
```

## Documentation

[SDD](SDD.md), [TDD](TDD.md), and [specification amendments](SPEC-AMENDMENTS.md) are the authoritative root contracts. [Supporting documentation](docs/README.md) separates active operations, API references, accepted decisions, audit evidence and historical guides. [The stabilization audit](docs/implementation/swarm-stabilization-audit.md) records observed defects and bounded repairs under #423.

## Contributing

One change, one branch from `develop`, one pull request. Read [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md) first; they are short. Commits are `type(scope): summary`.

- [The specification](docs/README.md) · [SDD: requirements](SDD.md) · [TDD: technical design](TDD.md)
- [Accepted decisions](docs/decisions) · [Changelog](CHANGELOG.md)

## License

[MIT](LICENSE) © 2026 Rick Álvarez. Papers belong to their authors and come from [arXiv](https://arxiv.org); readings are the output of an automated system.

Island agents include source-grounded research methods for computer science, quantum research, biology and general statistics, optimization and simulation. Existing agents can be upgraded with preserved custom prompts through the [operator methods upgrade](deploy/beta/README.md#upgrade-every-agents-research-methods). Source provenance appears in genome data and the human agent card. Agents receive research instructions and mark checks unresolved when stored evidence is insufficient.
