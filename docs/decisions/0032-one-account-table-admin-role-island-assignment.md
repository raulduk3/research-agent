# 0032. One account table, an admin role and island assignment

- Status: accepted
- Date: 2026-09-28
- Spec: SDD-PL-22; TDD "Relational layout and constraints" (`rater_principals`, `owner_principals`, `preference_credits`); TDD Appendix A `DeploymentBindings`.

## Context

Two identity tables exist, provisioned only from the command line and never from the app: `rater_principals(rater_id, island, salt, credential_hash, provisioned_at)`, `UNIQUE(island)`, immutable by trigger (migration 0007); and `owner_principals(owner_id, salt, credential_hash, provisioned_at)`, immutable, one row. PL-22 fixes "exactly two provisioned rater identities"; `DeploymentBindings` carries `rater_ids: list[2]`, `rater_islands: list<"cs"|"quant_ph">[2]` and a singular `operator_id`. Six tables hold a foreign key to one or the other: `ratings.rater_id`, `human_forecasts.rater_id`, `alert_acknowledgments.rater_id`, `audit_events.principal_id`, `genome_owner_admissions.owner_id`, `genome_retirements.owner_id`.

`digest/publish.py#ISLAND_READERS` maps each island to exactly one reader name. `preference_credits` (IN-43) keys on `(rating_id, genome_hash)`, so crediting is already per individual rating; nothing there forces a singleton rater per island. How several raters' credited shares on one island would combine into that island's weekly selection proxy (FT-14) is undefined and is not decided here.

The owner asked for an account system: one admin account with the platform's controls, and accounts assignable to islands. The request was distilled as C-2026-09-28-1, C-2026-09-28-2 and C-2026-09-28-8, and combined with the requested reviewer isolation and exclusion of the owner from rating. The separate requests for one web application and internet-reachable rating are unchanged by this decision.

## Decision

One `accounts` table replaces `rater_principals` and `owner_principals`:

```
accounts(account_id uuid PK, name text, salt, credential_hash,
         role text CHECK (role IN ('admin','reviewer')),
         disabled_at timestamptz NULL, provisioned_at timestamptz)
  -- partial unique index: at most one row WHERE role = 'admin' AND disabled_at IS NULL
account_islands(account_id FK, island text, PRIMARY KEY(account_id, island))
```

- Exactly one enabled `admin` account at a time (the former owner); `reviewer` accounts replace the former raters.
- `account_islands` is a join table: the schema permits an account assigned to more than one island and an island read by more than one reviewer, but the launch configuration stays what PL-22 fixes today, two reviewer accounts, one row each in `account_islands`, on `cs` and `quant-ph`. Widening that is a separate decision.
- A reviewer session is refused on every admin route, and an admin route renders no figure a reviewer view withholds (restates SR-21, SR-22, SR-25 for the merged model).
- The admin account is not admitted to rate as a reviewer.
- The six existing foreign keys move to `accounts.account_id`. The two current reviewer ids and the one admin id carry forward unchanged; no existing rating, forecast, acknowledgment, audit event, admission or retirement record changes identity.
- Provisioning gains an app-facing path (create, disable, reset credential, assign or unassign an island) alongside the existing command-line one; every such change is recorded as a new ledger event kind naming the acting admin, on a schema the implementation task defines.

Flexible schema, fixed launch configuration: SDD line 24 rates `cs` and `quant-ph` with exactly one rater each "so that the effect of rating on evolution can be told from evolution alone," and q-bio is deliberately unrated as the control. A join table costs nothing structurally, but actually assigning more than one reviewer to a rated island changes that experiment and belongs to a separate decision.

## Consequences

- SDD-PL-22 loses "exactly two provisioned rater identities" in favor of the `accounts`/`account_islands` shape at the same launch-fixed count. TDD's relational layout drops `rater_principals` and `owner_principals` for `accounts` and `account_islands`. `DeploymentBindings.rater_ids`/`rater_islands`/`operator_id` collapse into one account and assignment binding.
- A migration touches six foreign-key columns; existing stored ids are preserved, not regenerated.
- Verified by: the migration applied to a copy of the corpus database with all six foreign keys intact and every existing row's id unchanged; a reviewer session refused on every admin route; exactly one enabled admin row enforced by constraint.
- Left open, each its own decision: multi-account-per-island in the launch configuration and how several reviewers' preference credit combines into one weekly selection proxy; the admin-facing UI for create/disable/reset/assign, a follow-on feature once the table exists; the separate choices about one web application, internet-reachable rating, cloud hosting and spending, untouched by this decision. Hosting requires separately approved funding and topology; this account design authorizes neither.
