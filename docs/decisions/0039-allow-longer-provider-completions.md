# 0039. Allow longer provider completions

- Status: accepted
- Date: 2026-10-06
- Spec: SDD-RN-01; SDD-CT-01

## Context

Nonstreaming provider requests stop waiting after 90 seconds. Completed readings already take 78 to 89 seconds with smaller output allowances, and failed readings report transport read timeouts. The provider timeout is an internal default with no deployment setting. Replaying a previously failed first call with a longer timeout returned in 75.43 seconds at its 4,000-token limit; this does not demonstrate a call completing after the old deadline. The larger wait is a bounded remedy to verify against a complete reading.

## Decision

Default the provider transport timeout to 300 seconds and expose `RESEARCH_AGENT_MODEL_TIMEOUT_SECONDS`. Accept finite positive seconds, including fractional values. Apply the configured timeout through the existing HTTP client to connect, read, write and connection-pool waits. Keep the timeout finite and reject zero, negative, nonnumeric and nonfinite values at configuration loading.

## Consequences

A longer completion can finish within the configured wait without changing its prompts, output allowances or budget. Calls that exceed the wait still fail once; no automatic retry is added because a timed-out paid request may already have completed at the provider. Changing the setting requires the deployed process to load its environment again.
