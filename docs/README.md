# Documentation

Read the root [SDD](../SDD.md) for current requirements and the detailed [TDD](../TDD.md) for implementation contracts, owners, tests and exact gaps. Update these documents with affected code. Pending behavior remains pending until its complete contract is verified.

| Purpose | Document |
| --- | --- |
| Run the active server and inspect configuration | [Beta operations](../deploy/beta/README.md) |
| Build and host the browser | [Swarm browser](../apps/swarm-web/README.md) |
| Look up browser requests and response behavior | [Browser API](../apps/swarm-web/API.md) |
| Maintain historical schema consumers | [API schemas](contracts/api-v1/README.md) |

Git history and closed work records preserve past decisions and development evidence. Documentation states the current system without issue references or duplicate history ledgers. Runtime source-policy inputs live in `config/source-policy/`; runnable configuration examples live in `config/examples/`; test fixtures and deployment templates retain their own owners.

Passing documentation checks establishes current links, owners and traceability. It does not prove pending behavior or provider qualification.
