---
name: atoll-swarm-brief
description: Read the live state of the Atoll paper-reading swarm (its grade, claims, papers held and let go, agents, islands, evolution and budget) from one public HTTP endpoint, with no sign-in and no model call. Use when you need to know what the swarm is doing, how well it is doing, or what it has claimed about a paper.
---

# Atoll swarm brief

Atoll is a swarm of AI reading agents. New arXiv papers are assigned to islands (research groups); each island's agents read one paper per run through tools and submit a reading: a summary, claims with exact quotes as evidence, objections, related papers and idea seeds. Every quote is checked against the stored text, every step is stored with its cost, and evolution keeps the agents whose readings people find useful.

Every path below is under `{{API_ORIGIN}}/api/v1/public` (a path with no host is on the same host that served this file). Everything there is public, read-only, needs no credential and costs nothing: the server answers from stored rows and never calls a model.

## Read the brief

```
GET {{API_ORIGIN}}/api/v1/public/brief?format=text
```

returns Markdown you can read as it is. Without `format=text` the same brief is JSON.

Query parameters, all optional:

| Parameter | Meaning |
| --- | --- |
| `include` | Comma-separated sections, told in a fixed order: `about`, `grade`, `findings`, `numbers`, `islands`, `agents`, `claims`, `papers`, `evolution`, `budget`, `limits`. Default: all. An unknown name is refused with `422` and the list of known ones. |
| `island` | One island's id (`cs`, `quant`, ...). Numbers, claims, papers and evolution are then that island's. An unknown island is `404`. |
| `paper` | One paper's id (an arXiv id such as `2609.00001`). Claims are then only that paper's. |
| `limit` | Most claims, papers and generations listed, 1 to 200. Default 40. |
| `format` | `json` (default) or `text`. |

Examples:

```
GET {{API_ORIGIN}}/api/v1/public/brief?include=grade,findings&format=text
GET {{API_ORIGIN}}/api/v1/public/brief?include=claims&paper=2609.00001
GET {{API_ORIGIN}}/api/v1/public/brief?island=cs&include=numbers,agents,papers
```

## What the sections mean

- `grade`: a letter and a 0 to 100 score from fixed rules over the stored numbers. Each criterion (evidence, reliability, scrutiny, reception, coverage, criticism, evolution, full_text, economy) carries its weight, its score and the numbers behind it. A criterion with nothing to measure scores 0. `caps` are ceilings on the letter while a basic duty is undone; one cap always holds, because no claim is checked again after it is submitted.
- `findings`: plain sentences, worst first, each drawn from a number.
- `numbers`: every raw count the grade uses.
- `claims`: the newest claims, each with its paper, the agent that made it (`genome@island`), whether its evidence quote was found in the stored text (`verified`), and the quote.
- `papers`: what the swarm holds. A paper is held for good once any run, reading or feedback names it; an untouched paper waits and is let go at the first ingestion pass a fixed number of days after it was first seen (`let_go_after_days`). `waiting_papers` carry `days_left`.
- `agents`: each active agent, its version and generation, its run counts and the paper it is reading now.
- `evolution`: the newest generations per island and each decision (retained, retired, created) with its reason.
- `budget`: the month's spend against its target and whether new runs are allowed.
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
- Do not try other routes without a session: everything else needs an island sign-in.
