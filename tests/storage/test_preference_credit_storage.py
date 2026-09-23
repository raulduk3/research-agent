"""SDD-IN-43: stored preference credit, its refusals and the weekly report reads."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_loads
from research_agent.measurement.preference import RatingEvent, credit_ratings
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.digests import DigestRepository
from research_agent.storage.errors import StateConflict
from research_agent.storage.preference import PreferenceRepository, week_bounds
from research_agent.storage.ratings import RatingRepository
from test_digests import entry, store_payload

pytestmark = pytest.mark.integration
PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)
TARGET = "citation_reach_365d"


def _hash(label: str) -> str:
    return sha256(label.encode()).hexdigest()


def identity() -> CommandIdentity:
    return CommandIdentity(uuid4(), uuid4(), uuid4(), uuid4())


@dataclass
class World:
    database: Database
    digests: DigestRepository
    ratings: RatingRepository
    preference: PreferenceRepository

    def genome(
        self,
        label: str,
        island: str = "cs",
        *,
        parent: str | None = None,
        founder: bool = False,
        admitted: str = "now()",
    ) -> tuple[UUID, str]:
        configuration_id, configuration_hash = uuid4(), _hash(f"genome-{label}")
        with self.database.connect() as connection:
            connection.execute(
                f"""INSERT INTO genomes(
                        configuration_id, configuration_hash, lineage_id, island,
                        founder, infra_hash, parent_hash, admission, profile_hash,
                        admitted_at
                    ) VALUES(%s, decode(%s,'hex'), %s, %s, %s, decode(%s,'hex'),
                             decode(%s,'hex'),
                             CASE WHEN %s::text IS NULL THEN 'seeded' ELSE 'accepted' END,
                             decode(%s,'hex'), {admitted})""",
                (
                    configuration_id,
                    configuration_hash,
                    label,
                    island,
                    founder,
                    _hash("infra"),
                    parent,
                    parent,
                    _hash("profile"),
                ),
            )
        return configuration_id, configuration_hash

    def submission(self, probability: float, resolver: str = TARGET) -> UUID:
        sheet_hash, submission_id, question_id = (
            _hash(f"sheet-{uuid4()}"),
            uuid4(),
            uuid4(),
        )
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO sheets(hash, sealed_at) VALUES(decode(%s,'hex'), now())",
                (sheet_hash,),
            )
            connection.execute(
                """INSERT INTO sheet_questions(
                       sheet_hash, ordinal, question_id, target_definition_hash,
                       resolver_id, resolver_version, horizon
                   ) VALUES(decode(%s,'hex'), 0, %s, decode(%s,'hex'), %s, 1, now())""",
                (sheet_hash, question_id, _hash("target"), resolver),
            )
            connection.execute(
                """INSERT INTO submissions(
                       id, sheet_hash, submitter_id, question_id, status,
                       confidence, horizon, sealed_at
                   ) VALUES(%s, decode(%s,'hex'), %s, %s, 'sealed', %s, now(), now())""",
                (submission_id, sheet_hash, uuid4(), question_id, probability),
            )
        return submission_id

    def digest(
        self,
        island: str,
        entries: tuple[dict[str, Any], ...],
        nominations: tuple[dict[str, Any], ...] = (),
    ) -> None:
        self.digests.execute(
            "store",
            identity=identity(),
            payload=store_payload(
                island=island, entries=entries, nominations=nominations
            ),
        )

    def rate(self, entry_id: UUID, value: str) -> UUID:
        response = self.ratings.execute(
            "record",
            identity=identity(),
            payload={
                "rater_id": str(uuid4()),
                "paper_hash": "a" * 64,
                "digest_entry_id": str(entry_id),
                "value": value,
            },
        )
        return UUID(canonical_loads(response.body)["data"]["rating_id"])

    def week_of(self, rating_id: UUID) -> str:
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT to_char(rated_at AT TIME ZONE 'UTC', 'IYYY-"W"IW')
                   FROM ratings WHERE id = %s""",
                (rating_id,),
            ).fetchone()
        assert row is not None
        return str(row[0])

    def dump(self, *tables: str) -> str:
        parts = []
        with self.database.connect() as connection:
            for table in tables:
                rows = connection.execute(
                    f"SELECT * FROM {table} ORDER BY 1, 2"
                ).fetchall()
                parts.append(f"{table}:{rows!r}")
        return sha256("\n".join(parts).encode()).hexdigest()


@pytest.fixture
def world(postgres_dsn: str, artifact_root: Path) -> World:
    database = Database(postgres_dsn)
    store = ArtifactStore(artifact_root)
    common: dict[str, Any] = {
        "producer": PRODUCER,
        "config_hash": "c" * 64,
        "retention_policy_hash": "d" * 64,
    }
    return World(
        database,
        DigestRepository(database, store, **common),
        RatingRepository(database, store, **common),
        PreferenceRepository(database, store, **common),
    )


def nomination(
    entry_id: UUID, configuration_id: UUID, submission_id: UUID
) -> dict[str, Any]:
    return {
        "entry_id": str(entry_id),
        "configuration_id": str(configuration_id),
        "submission_id": str(submission_id),
        "preference": 4,
    }


def record(world: World, credits: list[dict[str, Any]]) -> None:
    world.preference.execute(
        "record", identity=identity(), payload={"credits": credits}
    )


def test_two_nominators_are_credited_from_their_stored_sealed_probabilities(
    world: World,
) -> None:
    id_a, hash_a = world.genome("a")
    id_b, hash_b = world.genome("b")
    _, hash_q = world.genome("elsewhere", "quant-ph")
    entry_id = uuid4()
    world.digest(
        "cs",
        (entry(entry_id, origin="population"),),
        (
            nomination(entry_id, id_a, world.submission(0.6)),
            nomination(entry_id, id_b, world.submission(0.2)),
        ),
    )
    rating_id = world.rate(entry_id, "like")
    iso_week = world.week_of(rating_id)

    rows = world.preference.read_rating_events(island="cs", iso_week=iso_week)
    outcome = credit_ratings([RatingEvent.from_record(row) for row in rows])
    assert {credit.genome_hash: credit.share for credit in outcome.credits} == {
        hash_a: pytest.approx(0.75),
        hash_b: pytest.approx(0.25),
    }
    record(world, [credit.to_dict() for credit in outcome.credits])

    stored = world.preference.read_credits(island="cs", iso_week=iso_week)
    assert {row["genome_hash"]: row["share"] for row in stored} == {
        hash_a: pytest.approx(0.75),
        hash_b: pytest.approx(0.25),
    }
    assert {row["genome_hash"]: row["sealed_probability"] for row in stored} == {
        hash_a: 0.6,
        hash_b: 0.2,
    }
    assert hash_q not in {row["genome_hash"] for row in stored}
    assert world.preference.read_credits(island="quant-ph", iso_week=iso_week) == []


def test_a_control_or_service_entry_credits_nobody_and_refuses_a_credit(
    world: World,
) -> None:
    control, service = uuid4(), uuid4()
    world.digest(
        "cs",
        (
            entry(control, origin="random_control", position=0),
            entry(service, origin="service", position=1),
        ),
    )
    ratings = [world.rate(control, "like"), world.rate(service, "like")]
    iso_week = world.week_of(ratings[0])
    rows = world.preference.read_rating_events(island="cs", iso_week=iso_week)
    assert {row["origin"] for row in rows} == {"random_control", "service"}
    outcome = credit_ratings([RatingEvent.from_record(row) for row in rows])
    assert outcome.credits == () and outcome.gaps == ()

    _, hash_a = world.genome("a")
    with pytest.raises(StateConflict):
        record(
            world,
            [
                {
                    "rating_id": str(ratings[0]),
                    "genome_hash": hash_a,
                    "island": "cs",
                    "entry_id": str(control),
                    "sealed_probability": 0.5,
                    "share": 1.0,
                    "iso_week": iso_week,
                }
            ],
        )
    assert world.preference.read_credits(island="cs", iso_week=iso_week) == []


def test_a_credit_to_a_genome_of_another_island_is_refused(world: World) -> None:
    id_a, _ = world.genome("a")
    _, hash_q = world.genome("elsewhere", "quant-ph")
    entry_id = uuid4()
    world.digest(
        "cs",
        (entry(entry_id, origin="population"),),
        (nomination(entry_id, id_a, world.submission(0.5)),),
    )
    rating_id = world.rate(entry_id, "like")
    with pytest.raises(StateConflict):
        record(
            world,
            [
                {
                    "rating_id": str(rating_id),
                    "genome_hash": hash_q,
                    "island": "cs",
                    "entry_id": str(entry_id),
                    "sealed_probability": 0.5,
                    "share": 1.0,
                    "iso_week": world.week_of(rating_id),
                }
            ],
        )


def test_an_unreadable_nomination_is_a_recorded_gap_never_a_partial_credit(
    world: World,
) -> None:
    id_a, _ = world.genome("a")
    id_b, _ = world.genome("b")
    entry_id = uuid4()
    world.digest(
        "cs",
        (entry(entry_id, origin="population"),),
        (
            nomination(entry_id, id_a, world.submission(0.6)),
            # sealed for a different target: not the citation probability
            nomination(entry_id, id_b, world.submission(0.2, resolver="other")),
        ),
    )
    rating_id = world.rate(entry_id, "like")
    iso_week = world.week_of(rating_id)
    rows = world.preference.read_rating_events(island="cs", iso_week=iso_week)
    assert rows[0]["nominations"] is None
    outcome = credit_ratings([RatingEvent.from_record(row) for row in rows])
    assert outcome.credits == ()
    (gap,) = outcome.gaps
    world.preference.execute(
        "record_gap",
        identity=identity(),
        payload={
            "rating_id": gap.rating_id,
            "iso_week": iso_week,
            "reason": gap.reason,
        },
    )
    assert world.preference.read_credits(island="cs", iso_week=iso_week) == []
    with pytest.raises(StateConflict):
        world.preference.execute(
            "record_gap",
            identity=identity(),
            payload={
                "rating_id": gap.rating_id,
                "iso_week": iso_week,
                "reason": "again",
            },
        )


def test_ratings_and_credit_leave_every_scoring_input_byte_identical(
    world: World,
) -> None:
    id_a, hash_a = world.genome("a")
    entry_id = uuid4()
    world.digest(
        "cs",
        (entry(entry_id, origin="population"),),
        (nomination(entry_id, id_a, world.submission(0.6)),),
    )
    inputs = (
        "submissions",
        "sheet_questions",
        "run_forecasts",
        "resolutions",
        "genomes",
    )
    before = world.dump(*inputs)
    rating_id = world.rate(entry_id, "like")
    iso_week = world.week_of(rating_id)
    record(
        world,
        [
            {
                "rating_id": str(rating_id),
                "genome_hash": hash_a,
                "island": "cs",
                "entry_id": str(entry_id),
                "sealed_probability": 0.6,
                "share": 1.0,
                "iso_week": iso_week,
            }
        ],
    )
    assert world.dump(*inputs) == before

    root = Path(__file__).resolve().parents[2] / "src" / "research_agent"
    readers = [*(root / "scoring").rglob("*.py"), root / "storage" / "forecasts.py"]
    assert readers
    for path in readers:
        text = path.read_text()
        assert "preference_credit" not in text and "measurement.preference" not in text


def test_the_credit_rows_are_immutable(world: World) -> None:
    id_a, hash_a = world.genome("a")
    entry_id = uuid4()
    world.digest(
        "cs",
        (entry(entry_id, origin="population"),),
        (nomination(entry_id, id_a, world.submission(0.6)),),
    )
    rating_id = world.rate(entry_id, "dislike")
    record(
        world,
        [
            {
                "rating_id": str(rating_id),
                "genome_hash": hash_a,
                "island": "cs",
                "entry_id": str(entry_id),
                "sealed_probability": 0.6,
                "share": -1.0,
                "iso_week": world.week_of(rating_id),
            }
        ],
    )
    with world.database.connect() as connection, pytest.raises(psycopg.Error):
        connection.execute("UPDATE preference_credits SET share = 1")


def test_the_week_population_reports_present_genomes_and_cross_island_admissions(
    world: World,
) -> None:
    _, founder = world.genome(
        "founder", founder=True, admitted="now() - interval '30 days'"
    )
    _, source = world.genome(
        "source", "quant-ph", admitted="now() - interval '30 days'"
    )
    _, retired = world.genome("retired", admitted="now() - interval '30 days'")
    retired_id = world.genome("retired-b", admitted="now() - interval '30 days'")[0]
    with world.database.connect() as connection:
        connection.execute(
            """INSERT INTO genome_archive(
                   configuration_id, cycle_id, skill, resolved_claim_count,
                   profile_hash, archived_at
               ) VALUES(%s, 'cycle', 0.1, 30, decode(%s,'hex'), now() - interval '20 days')""",
            (retired_id, _hash("profile")),
        )
        row = connection.execute(
            "SELECT to_char(now() AT TIME ZONE 'UTC', 'IYYY-\"W\"IW')"
        ).fetchone()
    assert row is not None
    iso_week = str(row[0])
    _, migrant = world.genome("migrant", parent=source)
    _, local_child = world.genome("local-child", parent=founder)

    start, end = week_bounds(iso_week)
    assert (end - start).days == 7
    population = world.preference.read_week_population(island="cs", iso_week=iso_week)
    present = {item["genome_hash"]: item["founder"] for item in population["genomes"]}
    assert present == {
        founder: True,
        retired: False,
        migrant: False,
        local_child: False,
    }
    assert [
        (item["child_hash"], item["source_island"], item["source_hash"])
        for item in population["migrations"]
    ] == [(migrant, "quant-ph", source)]


def test_rated_entries_are_read_by_origin_through_the_week(world: World) -> None:
    id_a, _ = world.genome("a")
    population, control = uuid4(), uuid4()
    world.digest(
        "cs",
        (
            entry(population, origin="population", position=0),
            entry(control, origin="random_control", position=1),
        ),
        (nomination(population, id_a, world.submission(0.5)),),
    )
    first, second = world.rate(population, "like"), world.rate(control, "skip")
    iso_week = world.week_of(first)
    rows = world.preference.read_rated_entries(island="cs", through_iso_week=iso_week)
    assert {(row["rating_id"], row["origin"], row["value"]) for row in rows} == {
        (str(first), "population", "like"),
        (str(second), "random_control", "skip"),
    }
    assert (
        world.preference.read_rated_entries(
            island="quant-ph", through_iso_week=iso_week
        )
        == []
    )
