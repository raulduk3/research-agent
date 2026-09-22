# Funding and spend-authorization evidence, 2026-09-22

Maps evidence to the Spending and rental authorization contracts (TDD.md:
`SpendAuthorization`, `CostQuote`, `RentalPermit`) and to Appendix A: Hosts,
isolation, recovery and spend. This is evidence toward those records, not a
submitted `SpendAuthorization`: no storage service exists to hold one, and no
funding decision has been made for this issue to record instead.

## Authorized spend

Current authorized spend is zero. Appendix A fixes the default:
`paid_execution_enabled=false`, active monetary authorization zero. No
`SpendAuthorization` record exists. No funding owner, approved cap or
start-stop authority has been recorded. This issue is operations preparation
only; it authorizes no paid action, provisioning or credential change, and
`CONTRIBUTING.md` reserves deploys, spend and credential decisions to the
owner's explicit instruction in the session that requests them.

## Dated quotes gathered so far

| Date | Provider | Item | Price | Status |
| --- | --- | --- | --- | --- |
| 2026-09-20 | Hetzner (auction) | Dedicated server at the SDD's stated floor (16 threads / 64 GiB / 1 TiB) | about EUR 140/month | Rejected option (#105 Option 2); not applicable to the adopted host-sizing approach |
| 2026-09-21 | DigitalOcean | Cloud VM, 16 vCPU / 64 GiB, plus block storage | about USD 504/month | Rejected option (#105 Option 3); not applicable |
| 2026-09-21 | OpenAlex | Filtered Works list request | USD 0.0001/request; about USD 0.10/day keyless free budget | Free tier; zero actual USD charge while under budget ([access-rules.md](../source-pilot/access-rules.md)) |

No quote exists yet for the adopted approach (#105 Option 1: the smallest
rented VM that measured demand supports). That quote depends on job-record
figures #55, #70 and #83 have not yet all published, and on #105 itself
resolving; until then, naming a host price would be inventing a bindings
value the issue explicitly prohibits.

No GPU rental quote has been gathered. Appendix A's four-GPU / 32-vCPU /
256-GiB envelope is stated as "a bounded capacity-test candidate, not a
verified need or price"; #55 owns measuring and pricing the actual rented
inference endpoint.

## Recurring and idle charges

None incurred. The only real spend-adjacent event to date is the OpenAlex
pilot's roughly USD 0.019 of keyless daily budget consumption, recorded in
[pilot-2026-09-21.md](../source-pilot/pilot-2026-09-21.md) — a free-tier
allowance, not a charge; the pilot ran with no key, account or payment
method.

Idle and stop behavior (10-minute idle stop, an authorized deadline stop, the
rental controller running outside agent containers under operator authority,
no worker receiving cloud credentials — Appendix A; `RentalPermit`, TDD.md)
is a design commitment. No rental controller exists yet to exercise it.

## Funding link

`funding_authorization_id` in the deployment bindings evidence
([bindings-2026-09-22.md](../deployment/bindings-2026-09-22.md)) is unset for
the same reason recorded here: no funding decision, quote or approved cap
exists yet for the adopted host-sizing approach.
