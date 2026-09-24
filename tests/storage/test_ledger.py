from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.errors import ObjectNotInPrerequisiteState

from research_agent.storage.database import Database
from research_agent.storage.errors import (
    IntegrityFailure,
    StateConflict,
    TransactionUnavailable,
)
from research_agent.storage.ledger import GENESIS_HASH, LedgerRepository

pytestmark = pytest.mark.integration


def _insert_payload_artifact(database: Database, artifact_hash: str) -> None:
    def insert(connection: psycopg.Connection[tuple[object, ...]]) -> None:
        connection.execute(
            """
            INSERT INTO artifacts(
                hash, byte_length, media_type, kind, retention_policy_hash,
                producer_image_digest, producer_source_commit,
                producer_contract_version, config_hash
            ) VALUES (
                decode(%s, 'hex'), 0, 'application/json', 'manifest',
                decode(%s, 'hex'), decode(%s, 'hex'), decode(%s, 'hex'), 1,
                decode(%s, 'hex')
            )
            """,
            (artifact_hash, "9" * 64, "8" * 64, "7" * 40, "6" * 64),
        )

    database.transaction(insert)


def test_concurrent_appends_form_one_gap_free_chain(postgres_dsn: str) -> None:
    database = Database(postgres_dsn)
    repository = LedgerRepository()
    payload_hash = hashlib.sha256(b"shared event payload").hexdigest()
    _insert_payload_artifact(database, payload_hash)

    commands = [(uuid4(), uuid4()) for _ in range(24)]

    def append(command: tuple[UUID, UUID]) -> int | tuple[UUID, UUID]:
        record_id, command_id = command
        try:
            event = database.serializable(
                lambda connection: repository.append(
                    connection,
                    record_id=record_id,
                    event_kind="run_event",
                    payload_hash=payload_hash,
                    command_id=command_id,
                )
            )
            return event.sequence
        except TransactionUnavailable:
            return command

    with ThreadPoolExecutor(max_workers=8) as executor:
        first_results = list(executor.map(append, commands))
    sequences = [result for result in first_results if isinstance(result, int)]
    rejected = [result for result in first_results if isinstance(result, tuple)]
    for command in rejected:
        result = append(command)
        assert isinstance(result, int)
        sequences.append(result)

    assert sorted(sequences) == list(range(1, 25))
    assert database.transaction(repository.verify) == 24
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT sequence, encode(previous_record_hash, 'hex'),
                   encode(record_hash, 'hex')
            FROM ledger_records ORDER BY sequence
            """
        ).fetchall()
    assert rows[0][1] == GENESIS_HASH
    assert all(rows[index][1] == rows[index - 1][2] for index in range(1, len(rows)))


def test_ledger_record_cannot_be_updated_or_deleted(postgres_dsn: str) -> None:
    database = Database(postgres_dsn)
    repository = LedgerRepository()
    _insert_payload_artifact(database, "1" * 64)
    event = database.serializable(
        lambda connection: repository.append(
            connection,
            record_id=uuid4(),
            event_kind="run_event",
            payload_hash="1" * 64,
            command_id=uuid4(),
        )
    )

    with pytest.raises(ObjectNotInPrerequisiteState):
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(
                "UPDATE ledger_records SET event_kind = 'score_published' WHERE sequence = %s",
                (event.sequence,),
            )
    with pytest.raises(ObjectNotInPrerequisiteState):
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(
                "DELETE FROM ledger_records WHERE sequence = %s", (event.sequence,)
            )


def test_append_rollback_leaves_head_and_records_unchanged(postgres_dsn: str) -> None:
    database = Database(postgres_dsn)
    repository = LedgerRepository()
    _insert_payload_artifact(database, "2" * 64)

    class Abort(Exception):
        pass

    def operation(connection: psycopg.Connection[tuple[object, ...]]) -> None:
        repository.append(
            connection,
            record_id=uuid4(),
            event_kind="run_event",
            payload_hash="2" * 64,
            command_id=uuid4(),
        )
        raise Abort

    with pytest.raises(Abort):
        database.serializable(operation)
    assert database.transaction(repository.verify) == 0


def test_append_refuses_a_stale_expected_head(postgres_dsn: str) -> None:
    database = Database(postgres_dsn)
    repository = LedgerRepository()
    _insert_payload_artifact(database, "3" * 64)

    database.serializable(
        lambda connection: repository.append(
            connection,
            record_id=uuid4(),
            event_kind="run_event",
            payload_hash="3" * 64,
            command_id=uuid4(),
        )
    )

    with pytest.raises(StateConflict):
        database.serializable(
            lambda connection: repository.append(
                connection,
                record_id=uuid4(),
                event_kind="run_event",
                payload_hash="3" * 64,
                command_id=uuid4(),
                expected_head=GENESIS_HASH,
            )
        )
    assert database.transaction(repository.verify) == 1


def _append_records(database: Database, count: int, payload: str) -> None:
    repository = LedgerRepository()
    _insert_payload_artifact(database, payload)
    for _ in range(count):
        database.serializable(
            lambda connection: repository.append(
                connection,
                record_id=uuid4(),
                event_kind="run_event",
                payload_hash=payload,
                command_id=uuid4(),
            )
        )


def _tamper(postgres_dsn: str, statement: str, parameters: tuple[object, ...]) -> None:
    # The immutability trigger refuses the edit, so lift it for the edit alone:
    # the test needs a ledger whose past was changed outside the repository.
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        connection.execute("ALTER TABLE ledger_records DISABLE TRIGGER USER")
        connection.execute(statement, parameters)  # type: ignore[arg-type]
        connection.execute("ALTER TABLE ledger_records ENABLE TRIGGER USER")


def test_verify_reports_the_first_record_whose_content_was_changed(
    postgres_dsn: str,
) -> None:
    database = Database(postgres_dsn)
    repository = LedgerRepository()
    _append_records(database, 4, "4" * 64)
    assert database.transaction(repository.verify) == 4
    _insert_payload_artifact(database, "5" * 64)

    _tamper(
        postgres_dsn,
        "UPDATE ledger_records SET payload_hash = decode(%s, 'hex') WHERE sequence IN (2, 4)",
        ("5" * 64,),
    )

    with pytest.raises(IntegrityFailure, match="hash fails at sequence 2$"):
        database.transaction(repository.verify)


def test_verify_reports_the_record_whose_previous_hash_was_changed(
    postgres_dsn: str,
) -> None:
    database = Database(postgres_dsn)
    repository = LedgerRepository()
    _append_records(database, 3, "6" * 64)

    _tamper(
        postgres_dsn,
        "UPDATE ledger_records SET previous_record_hash = decode(%s, 'hex') WHERE sequence = 3",
        ("f" * 64,),
    )

    with pytest.raises(IntegrityFailure, match="chain breaks at sequence 3$"):
        database.transaction(repository.verify)


def test_verify_reports_a_removed_record_at_the_gap(postgres_dsn: str) -> None:
    database = Database(postgres_dsn)
    repository = LedgerRepository()
    _append_records(database, 3, "7" * 64)

    _tamper(postgres_dsn, "DELETE FROM ledger_records WHERE sequence = 2", ())

    with pytest.raises(IntegrityFailure, match="chain breaks at sequence 3$"):
        database.transaction(repository.verify)


def test_verify_refuses_a_head_that_does_not_match_the_chain(
    postgres_dsn: str,
) -> None:
    database = Database(postgres_dsn)
    repository = LedgerRepository()
    _append_records(database, 2, "8" * 64)

    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        connection.execute(
            "UPDATE ledger_head SET record_hash = decode(%s, 'hex') WHERE singleton",
            ("e" * 64,),
        )

    with pytest.raises(IntegrityFailure, match="head does not match"):
        database.transaction(repository.verify)
