# Inference qualification battery, 2026-09-22T19:39:59.910444Z

Deployment: `zai/glm-5.3-flash` at `https://api.z.ai/api/paas/v4/chat/completions`, revision `unpinned`. Pricing dated 2026-09-22: input USD 0.15/M, cached USD 0.03/M, output USD 0.5/M.

**DRY RUN** -- no live provider calls were made; this is a mechanism check, not a qualification result. Cost and token figures come from a synthetic in-process transport.

Reservation ceiling for this invocation: USD 8.00/day, USD 200.00/month (Appendix A); outstanding reserved amount at completion: USD 0.0008.

## five_tool_conversations

- Required population: 100; measured: 3 (0 not run)
- Successes: 3/3 (100.0%), threshold 99.0%
- Forbidden tool attempts: 0
- Tokens: input 768, cached 192, output 144
- Cost: USD 0.0002
- Mean latency: 0.000s

Verdict: **insufficient_population**

## figure_table_questions

- Required population: 50; measured: 2 (0 not run)
- Successes: 0/2 (0.0%), threshold 80.0%
- Forbidden tool attempts: 0
- Tokens: input 512, cached 128, output 96
- Cost: USD 0.0001
- Mean latency: 0.000s

Verdict: **insufficient_population**

## evidence_location_questions

- Required population: 100; measured: 9 (0 not run)
- Successes: 3/9 (33.3%), threshold 90.0%
- Forbidden tool attempts: 0
- Tokens: input 2304, cached 576, output 432
- Cost: USD 0.0005
- Mean latency: 0.000s

| Context bucket | Successes | Denominator |
| --- | --- | --- |
| 16k | 1 | 3 |
| 32k | 1 | 3 |
| 64k | 1 | 3 |

Verdict: **insufficient_population**

No purchase, deployment, credential change or study activation is authorized by this report.
