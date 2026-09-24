"""Build, publish and store one island's rating digest for an issued day (#370).

``main`` reads the runs ``bin/daily`` issued for the day (``issued_runs``),
keeps the island's committed ones (an accepted submission and its
nomination), builds the digest through ``build.build_digest``, passes it
through ``publish.publish_digest`` and stores it through the digest storage
owner, so ``web/digest.py#load_digest`` reads it back for the rating app.
It prints the island and batch id the rating app's configuration names,
with the ``--values`` fragment ``bin/stack-config`` takes.

Every build input is fixed by the day's stored records: the batch id is the
day's snapshot, the watermark the ledger position of the island's last
accepted submission, the cutoff that submission's acceptance time. A rerun
over the same committed runs rebuilds the same digest and storage replays
it. A day with no committed run on the island refuses as
``no_committed_runs`` and stores nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from psycopg import Connection

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_json, sha256_hex
from research_agent.contracts.digests import DIGEST_ISLANDS
from research_agent.ingest.pilot import derived_uuid
from research_agent.orchestration.daily import issued_runs
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.digests import DigestRepository
from research_agent.storage.errors import StateConflict, UnavailableInput

from .build import DigestManifest, build_digest
from .nominations import Nomination
from .publish import publish_digest

#: The principal every digest store is recorded under.
OPERATOR = derived_uuid("digest-operator")
CONTROL_RUBRIC_VERSION = "control-rubric-v1"
_RETENTION = (
    b"Digests are retained privately for this research as the record of what "
    b"each island's raters were shown."
)
_INSTANT = "%Y-%m-%dT%H:%M:%S.%fZ"


class DigestRefused(Exception):
    """A day that yields no digest; the message is the named reason."""


@dataclass(frozen=True, slots=True)
class CommittedRun:
    """One island run of the day that ended in an accepted submission."""

    configuration_id: str
    paper_id: str
    recommend: bool
    preference: float


@dataclass(frozen=True, slots=True)
class DayInputs:
    """What the island's digest is built from, read once at the day's close."""

    snapshot_hash: str
    source_watermark: int
    cutoff: str
    profile_id: str
    paper_ids: tuple[str, ...]
    committed: tuple[CommittedRun, ...]


def read_day(database: Database, island: str, run_ids: Sequence[str]) -> DayInputs:
    """The island's issued papers and committed runs among *run_ids*."""

    def read(connection: Connection[tuple[object, ...]]) -> DayInputs:
        issued = connection.execute(
            """SELECT r.id, r.paper_id, r.configuration_id::text,
                      encode(r.snapshot_hash,'hex'), encode(g.profile_hash,'hex'),
                      s.accepted_at, n.recommend, n.preference
               FROM runs r
               JOIN genomes g ON g.configuration_id = r.configuration_id
               LEFT JOIN run_submissions s ON s.run_id = r.id
               LEFT JOIN run_nominations n ON n.run_id = r.id
               WHERE r.id = ANY(%s::uuid[]) AND g.island = %s
               ORDER BY r.id""",
            ([UUID(run_id) for run_id in run_ids], island),
        ).fetchall()
        committed = [row for row in issued if row[5] is not None]
        if not committed:
            raise DigestRefused("no_committed_runs")
        snapshots = {str(row[3]) for row in issued}
        profiles = {str(row[4]) for row in committed}
        if len(snapshots) != 1 or len(profiles) != 1:
            raise DigestRefused("mixed_day_inputs")
        accepted = max(cast(datetime, row[5]) for row in committed)
        # The ledger position the island's last accepted submission closed:
        # later records, of any kind, never move it.
        watermark = connection.execute(
            "SELECT coalesce(max(sequence), 0) FROM ledger_records WHERE created_at <= %s",
            (accepted,),
        ).fetchone()
        assert watermark is not None
        return DayInputs(
            snapshot_hash=snapshots.pop(),
            source_watermark=int(cast(int, watermark[0])),
            cutoff=accepted.astimezone(timezone.utc).strftime(_INSTANT),
            profile_id=profiles.pop(),
            paper_ids=tuple(sorted({str(row[1]) for row in issued})),
            committed=tuple(
                CommittedRun(
                    str(row[2]), str(row[1]), bool(row[6]), float(cast(float, row[7]))
                )
                for row in committed
                if row[6] is not None
            ),
        )

    return database.transaction(read)


def build_day_digest(island: str, day: str, inputs: DayInputs) -> DigestManifest:
    """The island's digest from the day's committed runs (EN-40, EN-41)."""

    nominations: dict[str, list[Nomination]] = {}
    for run in inputs.committed:
        listed = nominations.setdefault(run.configuration_id, [])
        if run.recommend:
            listed.append(Nomination(run.paper_id, run.preference))
    return build_digest(
        batch_id=inputs.snapshot_hash,
        island=island,
        source_watermark=inputs.source_watermark,
        cutoff=inputs.cutoff,
        profile_id=inputs.profile_id,
        control_rubric_version=CONTROL_RUBRIC_VERSION,
        day_ordinal=date.fromisoformat(day).toordinal(),
        population_nominations=nominations,
        eligible_family_ids=inputs.paper_ids,
        service_picks={},
    )


def store_payload(manifest: DigestManifest) -> dict[str, Any]:
    """The digest-store payload for *manifest* (``contracts/digests.py``).

    Storage keys an entry by a UUID and a paper by a SHA-256; both derive
    from the manifest's content-hashed ids, so a rebuild stores nothing new.
    The run nominations stay out: ``digest_nominations`` references sheet
    submissions, which an accepted run submission is not.
    """

    entries = []
    for entry in manifest.entries:
        control = entry.origin == "random_control"
        if entry.origin == "service":
            raise ValueError("a service entry has no captured source to store")
        entries.append(
            {
                "entry_id": str(derived_uuid("digest-entry", entry.entry_id)),
                "paper_hash": sha256_hex(entry.paper_id.encode()),
                "origin": entry.origin,
                "display_position": entry.position,
                "service_source": None,
                "candidate_pool_hash": manifest.control_pool_hash if control else None,
                "inclusion_probability": manifest.control_inclusion_probability
                if control
                else None,
            }
        )
    return {
        "digest_hash": manifest.digest_hash,
        "batch_id": manifest.batch_id,
        "island": manifest.island,
        "source_watermark": manifest.source_watermark,
        "shuffle_seed": manifest.shuffle_seed.to_bytes(8, "big").hex(),
        "entries": entries,
        "nominations": [],
    }


def publish_day(
    database: Database,
    store: ArtifactStore,
    *,
    island: str,
    day: str,
    run_ids: Sequence[str],
    producer: ProducerVersion,
) -> DigestManifest:
    """Build, publish and store the island's digest; a rerun replays it."""

    manifest = build_day_digest(island, day, read_day(database, island, run_ids))
    publication = publish_digest(manifest)
    repository = DigestRepository(
        database,
        store,
        producer=producer,
        config_hash=sha256_hex(
            canonical_json({"island": island, "control_rubric": CONTROL_RUBRIC_VERSION})
        ),
        retention_policy_hash=sha256(_RETENTION).hexdigest(),
    )
    command = derived_uuid("digest-store", publication.digest_id)
    repository.execute(
        "store",
        identity=CommandIdentity(OPERATOR, command, command, command),
        payload=store_payload(manifest),
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    from research_agent.platform.producer import source_commit
    from research_agent.storage.migrate import require_schema

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--island", required=True, choices=sorted(DIGEST_ISLANDS))
    parser.add_argument("--day", required=True, help="the issued UTC date")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--dsn", required=True)
    args = parser.parse_args(argv)
    database = Database(args.dsn)
    try:
        require_schema(database)
    except RuntimeError as error:
        print(f"{error}; apply migrations first", file=sys.stderr)
        return 1
    state: Path = args.state
    try:
        manifest = publish_day(
            database,
            ArtifactStore(state / "artifacts"),
            island=args.island,
            day=args.day,
            run_ids=issued_runs(state, args.day),
            producer=ProducerVersion(
                sha256(b"local-process").hexdigest(), source_commit(), 1
            ),
        )
    except (DigestRefused, UnavailableInput) as error:
        print(str(error), file=sys.stderr)
        return 2
    except StateConflict:
        print("digest_conflict", file=sys.stderr)
        return 2
    digest = {"island": manifest.island, "batch_id": manifest.batch_id}
    print(
        json.dumps(
            {
                **digest,
                "digest_hash": manifest.digest_hash,
                "entries": len(manifest.entries),
                "values": {"app": {"digest": digest}},
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
