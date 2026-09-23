# Jev provider capabilities and operating limits

Checked 2026-09-22 against the live service, on #59. This records what the
provider serves, how a request is shaped and what identity comes back. It does
not establish retention permission or provider qualification: RD-22's smoke
test, RD-23's preregistration and RD-24's readiness record are separate gates,
and none of them is met by this document.

## Access

Jev is reached through the ngrok AI gateway rather than Typesafe AI's own
endpoint. The gateway serves `https://gateway.ngrok.ai`, authenticates with a
bearer access key, and lists Jev among 140 models under the provider id
`typesafeai`, whose `status` is `active` and whose `website_url` is
`https://typesafe.ai`.

Three model ids are published:

| id | kind | resolves to |
| --- | --- | --- |
| `typesafeai/jev-1.13.0` | immutable revision | itself |
| `typesafeai/jev-latest` | mutable alias, current build | `jev-1.13.0` |
| `typesafeai/jev-preview` | mutable alias, next build | `jev-1.13.0` |

## Interface

Jev does not serve the chat-completions surface. A chat-completions request
returns `ERR_NGROK_27226`, `Provider "typesafeai" does not support API surface
"chat-completions"`. The model's published `supported_api_formats` names one
format, `systemone`, at `POST /v1/systemone`, taking `state`, `model` and
`questions`.

`questions` is an object keyed by field name. Each value carries a `type` and
`instructions`; a `choice` question adds `criteria`, an object mapping each
option to its description. The three primitives are `choice` (one option from a
defined set), `score` (an ordered scale) and `noul` (the probability that a
yes/no answer is yes).

A `choice` answer returns the selected option, a probability for every option
and a confidence in [0, 1]. This is the shape RD-18 requires: selected
category, full probability distribution and provider confidence as a
distribution summary. The eight fixed rubric fields of RD-16 are eight `choice`
questions in one request.

## Identity semantics

The response body carries a `model` field naming the resolved revision. A
request sent to the mutable alias `typesafeai/jev-latest` returned
`"model": "jev-1.13.0"`. The returned identity is therefore always an immutable
revision, and RD-19's requirement that provenance distinguish an immutable
revision from a mutable alias is satisfied by recording the returned value
rather than the configured one. RD-22's refusal when the active provider
identity differs from the smoke report's has a concrete field to compare.

## Input coverage and operating values

| value | observed |
| --- | --- |
| context length | 65,536 tokens |
| maximum input | 32,768 tokens |
| maximum completion | not published |
| input modality | text |
| prompt price | USD 0.000000042 per token, USD 0.042 per million |
| completion price | USD 0 |
| implicit caching | not supported |

A three-question rubric-shaped request over a short abstract consumed 460 input
and 87 output tokens. At the published prompt rate, one thousand full-text
assessments fall near one United States dollar, which is consistent with the
figure already carried in the intake record.

The provider documents `429 Too Many Requests` and `529 Overloaded` as
retryable with exponential backoff, `401` for an invalid credential and `422`
for a validation failure. No numeric rate limit, quota or concurrency ceiling
is published, so RD-20's concurrency of two, its 30-second timeout and its
1000-attempt cap remain our own limits rather than the provider's.

## What this does not establish

- **Retention permission.** No published policy states whether inputs are
  stored or used for training. The `jev` row in the permission registry stays
  `unknown` and its `permits_*` columns stay false until terms are reviewed.
  RD-19 requires storing the sanitized request and response, so this gate is
  load-bearing, not a formality.
- **Failover.** RD-20 forbids a fallback provider. The gateway's stated purpose
  includes automatic failover across providers and keys. Jev has exactly one
  provider behind it, so a single-model request cannot silently land elsewhere,
  but a routing rule listing alternates would breach RD-20. The configured rule
  must be confirmed to name one model and one key.
- **Qualification.** No accuracy is claimed or measured here. The provider
  describes its probabilities as calibrated across groups of predictions, which
  is not a per-answer correctness guarantee and is not a substitute for RD-22.

## Sources

- ngrok AI gateway overview, <https://ngrok.com/docs/ai-gateway/overview>, checked 2026-09-22.
- Typesafe AI HTTP API reference, <https://docs.typesafe.ai/api.md>, checked 2026-09-22.
- Typesafe AI System One concepts, <https://docs.typesafe.ai/concepts/system-one>, checked 2026-09-22.
- The gateway's own model listing and two live responses, read on 2026-09-22.

## Answer wire shape

Checked 2026-09-23 against the live service with one `choice` question. The
response body is `{"model": "jev-1.13.0", "answers": {...}, "usage":
{"input_tokens": int, "output_tokens": int}}`, and each entry of `answers`,
keyed by the question's field name, is `{"type": "choice", "choice":
"<option>", "confidence": float, "probabilities": {"<option>": float, ...}}`
with one probability per option. `type` names the primitive that answered.
The request named the alias `typesafeai/jev-latest`; the answer's `model`
resolved it to `jev-1.13.0`, as the identity section above records.

The other two primitives, checked the same day on `jev-1.13.0`:

- `score`: the question carries `criteria` as an ordered list, one entry per
  scale point (an object is refused with `Input should be a valid list`);
  the answer is `{"type": "score", "score": <int>, "confidence": float,
  "legend": {"0": "<criterion>", ...}, "probabilities": {"0": float, ...}}`
  with one probability per scale point.
- `noul`: the question carries `instructions` only; the answer is
  `{"type": "noul", "noul": float}`, the probability that the yes/no answer
  is yes.
