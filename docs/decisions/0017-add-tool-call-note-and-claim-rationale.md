# 0017. Add a tool-call note, intent and per-claim submit rationale

- Status: accepted
- Date: 2026-09-22
- Issue: #141
- Spec: SDD-AG-36, SDD-AG-37 added; TDD-3.1.72, TDD-3.1.73 added
- Pull requests: pending

## Context

AG-11 already makes every tool call's domain arguments strict, and AG-33 already gives the agent's own structured turn a protected note and intent, but that turn schema (AG-32, AG-33) is still pending and lives apart from the tool call itself. #141 asks for a shorter, already-reachable record of what the model thought at each step and why it backed a paper: a note and an intent on the tool call itself, and an optional rationale per claim at submit, both recorded for a person to read and never scored.

## Decision

Extend the tool-call envelope, not the AG-32/AG-33 turn schema. Every tool call now carries a plain-language note bounded to a configured word count starting at 60 words, and an intent label from a fixed set (scan, read, compare, decide), validated before the tool's own domain arguments and refused whole when either is missing or out of bound. The note and intent are recorded, in call order, outside the call's own effect.

submit additionally accepts one optional rationale per claim, in claim order, bounded to a configured word count starting at 120 words, carried beside the claim rather than inside it, so the shared claim schema stays the one schema AG-11 already defines. This rationale is distinct from the sealed forecast rationale of SR-24 and AG-26, which the sealing step records once a claim is actually sealed; the new one exists earlier, at the tool call, and is never sealed by this decision.

## Consequences

`contracts/tools.py` gains a `ToolCall` envelope wrapping the existing `ToolRequest`; `tools/submit.py` gains the per-claim rationale extraction; `tools/trace.py` gains a minimal append-only record of a run's tool-call notes and intents. The dispatcher does not yet call any of this, so no live tool call is refused or traced by it until a later change wires the dispatcher to the new envelope; that wiring, and any storage of a rationale beside a sealed claim, are left open.
