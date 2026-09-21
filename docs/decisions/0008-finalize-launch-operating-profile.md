# 0008. Finalize the launch operating profile

- Status: accepted
- Date: 2026-09-20
- Issue: #56
- Spec: SDD SR-28 and all launch-profile references; LAUNCH-PROFILE.md; LEARNING-PROTOCOL.md; RETRIEVAL-PROTOCOL.md; existing paired TDD items
- Pull requests: #63
- Supersedes: remaining unset launch limits and conditional launch activation in earlier decisions; preserves decisions 0004, 0006 and 0007 except as explicitly resolved here

## Context

The learning and paper-card contracts were settled, but runtime, deployment, agent budgets, evaluation and operational defaults remained scattered across decision issues. These gaps prevented a full technical design. The source decision delegates selecting coherent launch defaults and completing the SDD without expanding its features.

## Decision

Adopt launch-v1 in LAUNCH-PROFILE.md as the normative operating profile through SR-28. Use Python, PostgreSQL and immutable local artifacts, with containerized application services on one local Linux host, a separately managed rented multimodal inference endpoint, and a separate backup/anchor receiver. Add one local/CI check entrypoint now; application and provider checks activate with the corresponding implementation.

Select immutable Qwen3 embedding and GLM-4.6V-FP8 artifacts. The frozen embedding baseline has 1024 dimensions and combined overview/full-paper head input has 2048. Selection is not successful qualification. Four fixed agent configurations receive identical 20-paper shards, at most two concurrently, with explicit context, call, image, time and spending bounds. Prompts differ only in reading emphasis. Exactly three automatic citation targets and eight Jev original-paper assessments remain the launch model outputs.

Fix source fallbacks, exact-identifier graph matching, bounded cards/tools, submission idempotency, ledger ownership, provenance, replay, comparisons, human-reference evaluation samples, alerting and retention. Human review evaluates Jev and retrieval, not historical citation labels. Explicit temporal covariates and model membership checks also apply to baselines. Pre-runtime studies preserve genuine dated registrations and results before import; imported history never becomes a prospective forecast.

Disable automatic evolution, parent selection, schema mutation, extra claim types, persistent agent memory and preference fitness. ForeSci is isolated optional development evaluation, not a production judge or launch prerequisite. Reserved extension ids remain reserved; activating an extension requires a new accepted amendment. Optional social/download diagnostics and discovery-service outages cannot create an additional launch dependency.

Collection and engineering modes precede fully qualified study mode. Paid execution defaults off with zero authorized spend. Resource envelopes and numerical acceptance floors are initial policies, not demonstrated capacity, optimal parameters or provider rights. Procurement, binding actual hosts, acquiring licenses, solving tested dependency/image manifests and passing qualification are execution gates, not unsettled product decisions.

## Consequences

The SDD supplies a closed launch behavior contract for full TDD authoring. Full TDD coverage is still required before broad implementation dispatch. Existing learning/retrieval work can reuse preserved artifacts and resume jobs instead of repeating downloads and embedding preparation.

Initial thresholds, budgets and model choices can fail qualification. A failure becomes a specific finding; it cannot silently widen spend, change the labels, switch models or turn a partial system into a full-feature readiness claim. Any resulting behavior change receives a versioned profile and affected requalification. No application, dataset, trained head, provider approval or deployed endpoint is claimed by this decision.
