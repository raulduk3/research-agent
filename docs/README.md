# Documentation

The root [SDD](../SDD.md) defines the capped swarm requirements. The root [TDD](../TDD.md) maps each requirement to its technical owner and remaining design work. [Specification amendments](../SPEC-AMENDMENTS.md) record contract changes. These are the authoritative product documents.

## Supporting documents

| Purpose | Location |
| --- | --- |
| Run the active swarm and inspect its API | [Beta operations and API reference](../deploy/beta/README.md) |
| Run the active browser | [Swarm browser](../apps/swarm-web/README.md) and [browser API](../apps/swarm-web/API.md) |
| Read accepted decisions | [Decision records](decisions/README.md) |
| Inspect implementation and verification gaps | [Stabilization audit](implementation/swarm-stabilization-audit.md) |
| Inspect dated source, permission and deployment evidence | `evidence/`, organized by subject and date |
| Trace the earlier platform | [Historical documentation](archive/README.md) |

Project status and unfinished work live in GitHub issues. The current stabilization record is #423. A passing document check establishes pairing and structure, not runtime correctness. The audit separates observed behavior from incomplete contract items.
