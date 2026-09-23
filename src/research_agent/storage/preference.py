"""Persist a rating's preference credit and read the weekly report's inputs (IN-43, FT-26, #140).

Credit rows are immutable and cite the rating, the entry and the genome
(`0014_preference_credit.sql`). Nothing here writes a forecast, a resolution
or a score, and the scorer's projection reads none of these tables.

The report reads are plain selects over records other owners write:
genomes and their archive (`evolution/population.py`), digests and their
nominations (`storage/digests.py`) and ratings (`storage/ratings.py`). They
recompute nothing.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, cast

from psycopg import Connection

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ProducerVersion
from research_agent.contracts.preference import (
    validate_iso_week,
    validate_preference_payload,
)
from research_agent.storage.commands import (
    CommandIdentity,
    CommandTransaction,
    DomainEvents,
)
from research_agent.storage.database import Database
from research_agent.storage.errors import StateConflict
from research_agent.storage.idempotency import StoredResponse

LIKE_TARGET_ID = "citation_reach_365d"
_WEEK_SQL = "to_char({column} AT TIME ZONE 'UTC', 'IYYY-\"W\"IW')"


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def week_bounds(iso_week: str) -> tuple[datetime, datetime]:
    """The UTC instants a stored ISO week starts at and ends before."""

    validate_iso_week(iso_week)
    year, week = iso_week.split("-W")
    monday = date.fromisocalendar(int(year), int(week), 1)
    start = datetime.combine(monday, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=7)


class PreferenceRepository:
    def __init__(
        self,
        database: Database,
        store: ArtifactStore,
        *,
        producer: ProducerVersion,
        config_hash: str,
        retention_policy_hash: str,
    ) -> None:
        self._database = database
        self._commands = CommandTransaction(database)
        self._events = DomainEvents(store, producer, config_hash, retention_policy_hash)

    def execute(
        self, operation: str, *, identity: CommandIdentity, payload: object
    ) -> StoredResponse:
        value = validate_preference_payload(operation, payload)

        def mutate(connection: Connection[tuple[object, ...]]) -> dict[str, Any]:
            if operation == "record":
                return self._record(connection, identity, value["credits"])
            return self._record_gap(connection, identity, value)

        return self._commands.execute(identity, "/v1/preference", {}, value, mutate)

    def _record(
        self,
        connection: Connection[tuple[object, ...]],
        identity: CommandIdentity,
        credits: list[dict[str, Any]],
    ) -> dict[str, Any]:
        rating_id = credits[0]["rating_id"]
        rating = connection.execute(
            """SELECT r.digest_entry_id, d.island, e.origin,
                      """
            + _WEEK_SQL.format(column="r.rated_at")
            + """
               FROM ratings r
               JOIN digest_entries e ON e.entry_id = r.digest_entry_id
               JOIN digests d ON d.hash = e.digest_hash
               WHERE r.id = %s""",
            (rating_id,),
        ).fetchone()
        if rating is None:
            raise StateConflict("credit names a rating that was never recorded")
        entry_id, island, origin, iso_week = rating
        if str(entry_id) != credits[0]["entry_id"] or island != credits[0]["island"]:
            raise StateConflict("credit does not name the rated entry and island")
        if iso_week != credits[0]["iso_week"]:
            raise StateConflict("credit does not name the week the rating was made")
        if origin != "population":
            raise StateConflict("only a population entry credits a genome")
        for credit in credits:
            genome = connection.execute(
                "SELECT island FROM genomes WHERE configuration_hash = decode(%s,'hex')",
                (credit["genome_hash"],),
            ).fetchone()
            if genome is None or genome[0] != island:
                raise StateConflict("a genome of another island never receives credit")
        stored = connection.execute(
            "SELECT count(*) FROM preference_credits WHERE rating_id = %s",
            (rating_id,),
        ).fetchone()
        assert stored is not None
        if stored[0]:
            raise StateConflict("this rating already has its credit recorded")
        if connection.execute(
            "SELECT 1 FROM preference_credit_gaps WHERE rating_id = %s", (rating_id,)
        ).fetchone():
            raise StateConflict("this rating already has a recorded credit gap")
        receipt = self._events.append(
            connection,
            command_id=identity.command_id,
            event_kind="preference_credit_recorded",
            payload={"schema_version": 1, "credits": credits},
            input_hashes=(),
        )
        for credit in credits:
            connection.execute(
                """INSERT INTO preference_credits(
                       rating_id, genome_hash, island, entry_id,
                       sealed_probability, share, iso_week
                   ) VALUES(%s, decode(%s,'hex'), %s, %s, %s, %s, %s)""",
                (
                    credit["rating_id"],
                    credit["genome_hash"],
                    credit["island"],
                    credit["entry_id"],
                    credit["sealed_probability"],
                    credit["share"],
                    credit["iso_week"],
                ),
            )
        return {"rating_id": rating_id, "credited": len(credits), "receipt": receipt}

    def _record_gap(
        self,
        connection: Connection[tuple[object, ...]],
        identity: CommandIdentity,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        if connection.execute(
            "SELECT 1 FROM preference_credits WHERE rating_id = %s",
            (value["rating_id"],),
        ).fetchone():
            raise StateConflict("this rating already has its credit recorded")
        receipt = self._events.append(
            connection,
            command_id=identity.command_id,
            event_kind="preference_credit_gap_recorded",
            payload={"schema_version": 1, **value},
            input_hashes=(),
        )
        inserted = connection.execute(
            """INSERT INTO preference_credit_gaps(rating_id, iso_week, reason, recorded_at)
               VALUES(%s, %s, %s, clock_timestamp())
               ON CONFLICT (rating_id) DO NOTHING RETURNING recorded_at""",
            (value["rating_id"], value["iso_week"], value["reason"]),
        ).fetchone()
        if inserted is None:
            raise StateConflict("this rating already has a recorded credit gap")
        return {"rating_id": value["rating_id"], "receipt": receipt}

    def read_rating_events(self, *, island: str, iso_week: str) -> list[dict[str, Any]]:
        """An island's ratings made in one week, with each entry's sealed nominators.

        A nomination whose submission or genome cannot be joined makes the
        entry's ``nominations`` ``None``: a partial list would skew the shares.
        """

        validate_iso_week(iso_week)
        week = _WEEK_SQL.format(column="r.rated_at")

        def read(connection: Connection[tuple[object, ...]]) -> list[dict[str, Any]]:
            ratings = connection.execute(
                f"""SELECT r.id, e.entry_id, d.island, {week}, r.value, e.origin
                    FROM ratings r
                    JOIN digest_entries e ON e.entry_id = r.digest_entry_id
                    JOIN digests d ON d.hash = e.digest_hash
                    WHERE d.island = %s AND {week} = %s
                    ORDER BY r.rated_at, r.id""",
                (island, iso_week),
            ).fetchall()
            entry_ids = [row[1] for row in ratings]
            declared: dict[str, int] = {}
            for entry_id, count in connection.execute(
                """SELECT entry_id, count(*) FROM digest_nominations
                   WHERE entry_id = ANY(%s) GROUP BY entry_id""",
                (entry_ids,),
            ).fetchall():
                declared[str(entry_id)] = cast(int, count)
            readable: dict[str, list[dict[str, Any]]] = {}
            for entry_id, genome_hash, genome_island, probability in connection.execute(
                """SELECT n.entry_id, encode(g.configuration_hash,'hex'), g.island,
                          s.confidence
                   FROM digest_nominations n
                   JOIN submissions s ON s.id = n.submission_id AND s.status = 'sealed'
                   JOIN sheet_questions q ON q.sheet_hash = s.sheet_hash
                        AND q.question_id = s.question_id AND q.resolver_id = %s
                   JOIN genomes g ON g.configuration_id = n.configuration_id
                   WHERE n.entry_id = ANY(%s)
                   ORDER BY n.entry_id, g.configuration_hash""",
                (LIKE_TARGET_ID, entry_ids),
            ).fetchall():
                readable.setdefault(str(entry_id), []).append(
                    {
                        "genome_hash": genome_hash,
                        "island": genome_island,
                        "sealed_probability": probability,
                    }
                )
            events: list[dict[str, Any]] = []
            for (
                rating_id,
                entry_id,
                rating_island,
                rating_week,
                value,
                origin,
            ) in ratings:
                key = str(entry_id)
                found = readable.get(key, [])
                nominations = (
                    None
                    if origin == "population" and len(found) != declared.get(key, 0)
                    else found
                )
                events.append(
                    {
                        "rating_id": str(rating_id),
                        "entry_id": key,
                        "island": rating_island,
                        "iso_week": rating_week,
                        "value": value,
                        "origin": origin,
                        "nominations": nominations,
                    }
                )
            return events

        return self._database.transaction(read)

    def read_credits(self, *, island: str, iso_week: str) -> list[dict[str, Any]]:
        """The stored credit rows of one island and week, exactly as recorded."""

        validate_iso_week(iso_week)

        def read(connection: Connection[tuple[object, ...]]) -> list[dict[str, Any]]:
            rows = connection.execute(
                """SELECT rating_id, encode(genome_hash,'hex'), island, entry_id,
                          sealed_probability, share, iso_week
                   FROM preference_credits WHERE island = %s AND iso_week = %s
                   ORDER BY rating_id, genome_hash""",
                (island, iso_week),
            ).fetchall()
            return [
                {
                    "rating_id": str(row[0]),
                    "genome_hash": row[1],
                    "island": row[2],
                    "entry_id": str(row[3]),
                    "sealed_probability": row[4],
                    "share": row[5],
                    "iso_week": row[6],
                }
                for row in rows
            ]

        return self._database.transaction(read)

    def read_rated_entries(
        self, *, island: str, through_iso_week: str
    ) -> list[dict[str, Any]]:
        """Every rating of an island's entries up to the end of a week, by origin.

        ``week`` is the ISO week the entry's digest was built in, the cluster
        the report's interval resamples.
        """

        _, end = week_bounds(through_iso_week)
        week = _WEEK_SQL.format(column="d.built_at")

        def read(connection: Connection[tuple[object, ...]]) -> list[dict[str, Any]]:
            rows = connection.execute(
                f"""SELECT r.id, e.origin, r.value, {week}
                    FROM ratings r
                    JOIN digest_entries e ON e.entry_id = r.digest_entry_id
                    JOIN digests d ON d.hash = e.digest_hash
                    WHERE d.island = %s AND r.rated_at < %s
                    ORDER BY r.rated_at, r.id""",
                (island, end),
            ).fetchall()
            return [
                {
                    "rating_id": str(row[0]),
                    "origin": row[1],
                    "value": row[2],
                    "week": row[3],
                }
                for row in rows
            ]

        return self._database.transaction(read)

    def read_week_population(self, *, island: str, iso_week: str) -> dict[str, Any]:
        """The genomes present at a week's freeze and the migrations admitted in it.

        Present means admitted before the week ended and not archived before
        it. A migration is a genome admitted that week whose parent belongs
        to another island (TDD-3.1.73); a field migration copies one part
        from another island's genome and keeps a local parent, and no stored
        record distinguishes it, so it is not listed.
        """

        start, end = week_bounds(iso_week)

        def read(connection: Connection[tuple[object, ...]]) -> dict[str, Any]:
            genomes = connection.execute(
                """SELECT g.configuration_id, encode(g.configuration_hash,'hex'),
                          g.founder, g.lineage_id
                   FROM genomes g
                   LEFT JOIN genome_archive a ON a.configuration_id = g.configuration_id
                   WHERE g.island = %s AND g.admitted_at < %s
                     AND (a.archived_at IS NULL OR a.archived_at >= %s)
                   ORDER BY g.admitted_at, g.configuration_id""",
                (island, end, end),
            ).fetchall()
            migrations = connection.execute(
                """SELECT encode(c.configuration_hash,'hex'), p.island,
                          encode(p.configuration_hash,'hex'), c.admitted_at
                   FROM genomes c
                   JOIN genomes p ON p.configuration_hash = c.parent_hash
                   WHERE c.island = %s AND p.island <> c.island
                     AND c.admitted_at >= %s AND c.admitted_at < %s
                   ORDER BY c.admitted_at, c.configuration_id""",
                (island, start, end),
            ).fetchall()
            return {
                "genomes": [
                    {
                        "configuration_id": str(row[0]),
                        "genome_hash": row[1],
                        "founder": row[2],
                        "lineage_id": row[3],
                    }
                    for row in genomes
                ],
                "migrations": [
                    {
                        "child_hash": row[0],
                        "source_island": row[1],
                        "source_hash": row[2],
                        "admitted_at": _utc(cast(datetime, row[3])),
                    }
                    for row in migrations
                ],
            }

        return self._database.transaction(read)
