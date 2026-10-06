# Documentation

The root [SDD](../SDD.md) states requirements. The root [TDD](../TDD.md) identifies implementation owners, verified behavior and remaining gaps. The root [specification amendments](../SPEC-AMENDMENTS.md) records changes to those contracts.

| Purpose | Document |
| --- | --- |
| Run and operate the active swarm; inspect server API and configuration | [Beta operations](../deploy/beta/README.md) |
| Build and host the browser | [Swarm browser](../apps/swarm-web/README.md) |
| Look up browser requests and display behavior | [Browser API reference](../apps/swarm-web/API.md) |
| Read accepted contract decisions | [Decision records](decisions/README.md) |
| Review implementation conformity and earlier development notes | [Development record](DEVELOPMENT.md) |
| Inspect dated observations and source permissions | `evidence/`, organized by subject |
| Maintain historical schema consumers | [Historical API schemas](contracts/api-v1/README.md) |

All development notes and retired scaffolding documentation are consolidated in DEVELOPMENT.md. Accepted decisions, dated evidence, schemas, runtime fixtures and active operating instructions retain their own owners. Fixtures in `docs/implementation/` and `docs/launch/` keep their paths because commands and tests consume them.

The development record states the implementation evidence and remaining gaps in full. Work tracking lives outside these documents. Passing documentation checks establishes links and traceability, not complete runtime conformity.
