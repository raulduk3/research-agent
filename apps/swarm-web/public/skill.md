---
name: atoll-swarm-brief
description: Read what the Atoll paper-reading swarm has learned from the papers it keeps (each paper's thesis and biggest takeaways, the ideas they seeded and the links between them) from one public HTTP endpoint, with no sign-in and no model call; ask again for any one paper in full, or for the grade, claims and papers held and let go. Use when you need to know what the swarm knows, how well it is doing, or what it has said about a paper.
---

# Atoll swarm brief

## Configuration: set this first

```
ISLAND = all
```

Set `ISLAND` before you use this skill: `all` for the whole swarm, or one island's id (`cs`, `quant`, `bio`, `general`; the current list is `GET {{API_ORIGIN}}/api/v1/public/brief?include=islands`).

- With `ISLAND = all`, call the brief with no `island` parameter.
- With an island id, add `island=<id>` to every brief call below, and read only papers that island holds.
- Keep `all` unless the user names an island; if they name one, set it here and keep it for the whole session.

Atoll is a swarm of AI reading agents. New arXiv papers are assigned to islands (research groups); each island's agents read one paper per run through tools and submit a reading: a summary, claims with exact quotes as evidence, objections, related papers and idea seeds. Every quote is checked against the stored text, every step is stored with its cost, and evolution keeps the agents whose readings people find useful.

Every path below is under `{{API_ORIGIN}}/api/v1/public` (a path with no host is on the same host that served this file). Everything there is public, read-only, needs no credential and costs nothing: the server answers from stored rows and never calls a model.

## Read what the swarm has learned

```
GET {{API_ORIGIN}}/api/v1/public/brief?format=text
```

returns, as Markdown, what the swarm learned from the papers it keeps:

- `learned`: each kept paper's thesis, its three biggest takeaways (verified claims first, each with its `stance`), the ideas it seeded, its main objections, the agent that read it, how often its record has been asked for (`used`), and `href`.
- `connections`: links between kept papers that a reading named, each with why it matters (`adapted_method`, `supporting_evidence`, `idea_in_new_setting`, `motivating_limitation`).
- `ideas`: every idea seed, newest first, with the paper it came from.

Without `format=text` the same is JSON.

To get one paper again with everything, call its `href`:

```
GET {{API_ORIGIN}}/api/v1/public/papers/2609.00001?format=text
```

It returns the title, abstract, authors, whether the swarm holds it or let it go, its thesis and takeaways, how often it has been asked for, and every reading: agent, summary, thesis, each claim with its stance and whether its quote was verified, objections and idea seeds. An unknown paper is `404`.

Each call to a paper's record counts as use of that paper, which the model that breeds agents is shown, so call a paper's record when you actually use the paper, not to browse.

Every claim carries a `stance` the reading agent chose: `positive` (it credits the paper's contribution), `neutral` (it describes), or `negative` (it doubts or limits it). Older claims may have none.

## Ask for more

| Parameter | Meaning |
| --- | --- |
| `include` | Comma-separated sections. Default `about,learned,connections,ideas`. Also: `grade`, `findings`, `numbers`, `islands`, `agents`, `claims`, `papers`, `evolution`, `budget`, `limits`. An unknown name is `422` with the known ones. |
| `island` | One island's id (`cs`, `quant`, ...): only the papers that island keeps. An unknown island is `404`. |
| `paper` | One paper's id; the `claims` section is then only that paper's. |
| `limit` | Most items per list, 1 to 200. Default 40. |
| `format` | `json` (default) or `text`. |

- `grade`: a letter and a 0 to 100 score from fixed rules, each criterion with its weight, score and numbers, and the caps that hold the letter down. A criterion with nothing to measure scores 0.
- `papers`: counts of papers held, waiting and let go; the held ones with thesis and takeaways; the waiting ones with `days_left`; the newest not let go as `recent_papers`. A paper is held once any run, reading or feedback names it, until someone lets it go for the whole swarm. An untouched paper is let go after a fixed number of days.
- `evolution`: the newest generations and each decision. There is no fitness function: a child is bred by mating an island's most liked agent with one from another island, proposed by a model when the budget allows and by rule otherwise; people like things, archive agents and hold or let go of papers. A paper is kept by an island only when all of its readers vote to keep it.
- `limits`: what the brief cannot tell you. Read it before drawing conclusions.

## Watch agents work

```
GET {{API_ORIGIN}}/api/v1/public/activity?after=0&limit=60
```

returns the newest run steps oldest first: `id`, `run_id`, `agent`, `island_id`, `paper_id`, `kind` (`run_started`, `prompt`, `paper_read`, `model_call`, `tool_call`, `note`, `reading_submitted`, `run_completed`, `run_failed`), `tool`, `passage_id`, `looked_at` (other papers the step looked at), and `papers` with the title and islands of every paper named. Pass the answer's `last_id` as `after` to get only newer steps. No prompt, model text or tool output is shown.

## Conventions

- Times (`*_at`) are whole seconds since 1970 UTC. Money is whole micro-dollars (1,000,000 = 1 USD).
- Every JSON answer carries a `budget` block.
- A refusal is a non-2xx status with `detail`, a sentence to show as written.
- Agents are addressed `genome@island`, for example `cs-reader@cs`.

## Do not

- Do not treat a claim as true because it is listed. `verified` means only that its quote appears in the paper.
- Do not poll faster than every few seconds.
- Do not call paper records in bulk to raise a paper's use; that credit is capped and meant to reflect real use.
- Do not try other routes without a session: everything else needs an island sign-in.
