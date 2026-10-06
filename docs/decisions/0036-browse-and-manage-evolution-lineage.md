# 0036. Browse and manage evolution lineage

- Status: accepted
- Date: 2026-10-06
- Issue: #436
- Spec: SDD-IS-03; SDD-EV-01; SDD-UI-01
- Pull requests: pending

## Context

The island page rendered every agent's prompt alongside a flat list of every evolution decision. Population and decision growth made ancestry difficult to inspect and management difficult to reach.

## Decision

Show a collapsible lineage outline with a single selected agent detail. Start with collapsed descendants and at most 30 visible rows. Population filters retain matching agents' ancestors. Search shows direct matches with their parent and depth so deeply nested agents are reachable without paging through ancestors. Expand or collapse branches and request more rows explicitly. Limit indentation for deep ancestry and show its depth. Display secondary parents as references, missing parents as unavailable, and manual self-parent versions as roots.

Keep decisions beside their selected agent and skipped cycles or unavailable agents in a separate history disclosure. Show at most 30 decisions until more are requested. Preserve all stored history.

Use the existing owner-authorized edit, archive and bring-back routes. Archive removes an agent from the active population and preserves its versions and runs. Another island's page remains read-only. No destructive deletion is added.

## Consequences

A bounded flattened outline avoids recursive rendering and repeated cards while preserving ancestry. A nested DOM tree would make deep ancestry harder to bound and could overflow. Secondary parents do not duplicate the child into multiple branches. The browser retains the complete received population and histories; this change bounds rendering rather than storage or response size.
