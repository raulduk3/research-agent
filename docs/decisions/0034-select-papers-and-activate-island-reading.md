# 0034. Select papers and activate island reading

- Status: accepted
- Date: 2026-10-05
- Issue: #405
- Spec: SDD-IG-01; SDD-IS-01; SDD-RN-02; SDD-CT-03; SDD-UI-01
- Pull requests: pending

## Context

Paper selection was called holding, with descriptions incorrectly equating a read attempt with selection. A later reader vote could overwrite a person's selection. General had no watched categories, and low ingestion and run caps left the swarm well below its monthly budget.

## Decision

Use selected and deselected in the product. Readers select a paper only when their assigned cohort completes and all votes agree. A person's explicit selection or deselection remains authoritative across all assigned islands until changed by a person. Preserve external hold and release routes and legacy response fields while adding canonical select and deselect routes.

Provide up to five other selected papers from the current island in each new reading prompt. Each carries its title, selection source and a summary of at most 600 characters. Selection guides research interests and comparisons, but is not evidence for a claim. Include this context in the existing run cost calculation.

Give General explicit statistics, optimization and complex systems sources while preserving unmatched-paper fallback. Default ingestion to four papers per pass, with six agent starts per island per hour and 120 across the swarm per UTC day. Existing explicit configuration remains authoritative. The monthly ceiling remains 50 USD, and measured costs, reservations and daily guards remain unchanged.

## Consequences

Schema version 9 records explicit human selection state and preserves historical human deselections. Older positive selections have no recoverable human provenance. Selected unread papers remain available until deselected. Island views and globe links reflect the islands that actually selected each paper.

Existing deployments need a deliberate configuration revision for General's categories and pacing. A develop merge alone does not establish an atoll deployment. Verify actual ingestion, completed readings and activity after deployment; a scheduled capacity is not a spending commitment.
