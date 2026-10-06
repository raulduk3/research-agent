# Documentation

Start with [SDD.md](../SDD.md) for current requirements, implementation owners, behavior tests and exact gaps. [TDD.md](../TDD.md) identifies the architecture and executable contracts. Neither requires historical decisions or evidence as background reading.

| Purpose | Document |
| --- | --- |
| Run and operate the active swarm; inspect server API and configuration | [Beta operations](../deploy/beta/README.md) |
| Build and host the browser | [Swarm browser](../apps/swarm-web/README.md) |
| Look up browser requests and display behavior | [Browser API reference](../apps/swarm-web/API.md) |
| Inspect active executable payload shapes | [Zod contracts](../apps/swarm-web/src/api/contracts.ts) |
| Maintain historical schema consumers | [Historical API schemas](contracts/api-v1/README.md) |

`decisions/`, `evidence/` and the root `SPEC-AMENDMENTS.md` remain optional historical reference. New work updates current requirements, executable contracts and behavior tests together; the pull request records rationale and verification. Runtime fixtures retain their existing paths because commands and tests consume them.
