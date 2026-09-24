# 0029. Let ingest hold the database DSN at launch

- Status: accepted
- Date: 2026-09-23
- Issue: #315
- Spec: SDD Appendix A (storage: "Only the storage service connects to PostgreSQL"); PL-08
- Pull requests: pending

## Context

`python -m research_agent` needed a start command for the daily ingest
loop. The only day pass that exists, `orchestration/daily.py#main` (what
`bin/daily` runs), drives listing, documents, the requested-paper pass,
cards, sheets and the snapshot over `ingest/pilot_local.py#local_storage`.
That adapter opens its own `Database` and runs an in-process storage server
beside it, and the pass migrates its schema on every call. SDD Appendix A
says only the storage service connects to PostgreSQL. No storage-client day
pass exists, and writing one is not a launcher's job.

The same pass reads each paper in-process: `ingest/requests.py#RequestReader`
extracts, chunks and embeds inside the day pass, on the embedder that
`orchestration/daily.py#main` loads.

## Decision

At launch, `serve-ingest` runs `orchestration/daily.py#main` once per UTC
day over the local storage adapters, the same way the pilot runs today. The
ingest role holds the DSN of its own dedicated schema, read from a secret
file named in its launch configuration, and that DSN can run the pass's
migrations. The rule that only storage connects to PostgreSQL is deferred
for ingest until a day pass runs over the storage client. That work is
separate from #315.

The reader has no service and no `serve-reader` command. It runs
in-process inside the day pass for the reason above. A reader container
would have no caller until the day pass reaches it through a storage and
model client.

## Consequences

- `serve-ingest --config FILE` checks the launch profile hash and the DSN
  secret, then runs the day pass for today and again after each UTC
  midnight. A failed pass raises, so the supervisor restarts the launcher.
  The pass resumes from storage and a repeated day issues nothing new.
- The ingest DSN must not be the storage service's runtime role. The pass
  migrates, so that role would fail, and sharing the role would erase the
  line storage's runtime role draws (`storage/roles.py`).
- The owner app's sign-in directory (`web/auth.py#OwnerDirectory`) reads
  owner principals through `storage/owners.py#OwnerRepository`, which also
  holds a `Database`. `serve-owner` therefore declares a DSN secret too,
  under the same deferral.
- The `reader` role in `deploy/compose.yaml` stays an inventory entry with
  no command.
