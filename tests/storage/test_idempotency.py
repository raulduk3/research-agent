from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from psycopg import Connection
from psycopg.errors import CheckViolation

from research_agent.storage.database import Database
from research_agent.storage.errors import IdempotencyConflict
from research_agent.storage.idempotency import (
    IdempotencyRepository,
    StoredResponse,
    command_content_hash,
)

pytestmark = pytest.mark.integration


def test_concurrent_identical_commands_commit_one_effect_and_replay(
    postgres_dsn: str,
) -> None:
    database = Database(postgres_dsn)
    repository = IdempotencyRepository()
    principal_id, key, command_id = uuid4(), uuid4(), uuid4()
    content_hash = command_content_hash("/v1/example", {}, {"value": 1})
    barrier = Barrier(2)
    with database.connect() as connection:
        connection.execute("CREATE TABLE test_effects(id uuid PRIMARY KEY)")

    def execute() -> StoredResponse:
        barrier.wait()

        def transaction(
            connection: Connection[tuple[object, ...]],
        ) -> StoredResponse:
            replay = repository.begin(
                connection,
                principal_id=principal_id,
                key=key,
                command_id=command_id,
                content_hash=content_hash,
            )
            if replay is not None:
                return replay
            connection.execute("INSERT INTO test_effects(id) VALUES (%s)", (uuid4(),))
            return repository.finish(
                connection,
                principal_id=principal_id,
                key=key,
                command_id=command_id,
                content_hash=content_hash,
                status_code=201,
                response_body=b'{"created":true}',
            )

        return database.serializable(transaction)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: execute(), range(2)))

    assert {result.body for result in results} == {b'{"created":true}'}
    assert sorted(result.replayed for result in results) == [False, True]
    with database.connect() as connection:
        row = connection.execute("SELECT count(*) FROM test_effects").fetchone()
        assert row is not None and row[0] == 1


def test_key_or_command_reuse_with_changed_content_conflicts(postgres_dsn: str) -> None:
    database = Database(postgres_dsn)
    repository = IdempotencyRepository()
    principal_id, key, command_id = uuid4(), uuid4(), uuid4()
    first = command_content_hash("/v1/example", {}, {"value": 1})
    changed = command_content_hash("/v1/example", {}, {"value": 2})

    def commit(connection: Connection[tuple[object, ...]]) -> StoredResponse:
        assert (
            repository.begin(
                connection,
                principal_id=principal_id,
                key=key,
                command_id=command_id,
                content_hash=first,
            )
            is None
        )
        return repository.finish(
            connection,
            principal_id=principal_id,
            key=key,
            command_id=command_id,
            content_hash=first,
            status_code=200,
            response_body=b"{}",
        )

    database.serializable(commit)
    with pytest.raises(IdempotencyConflict):
        database.serializable(
            lambda connection: repository.begin(
                connection,
                principal_id=principal_id,
                key=key,
                command_id=command_id,
                content_hash=changed,
            )
        )


def test_unfinished_claim_cannot_commit_and_real_500_response_replays(
    postgres_dsn: str,
) -> None:
    database = Database(postgres_dsn)
    repository = IdempotencyRepository()
    principal_id, key, command_id = uuid4(), uuid4(), uuid4()
    content_hash = command_content_hash("/v1/example", {}, {"value": 1})

    with pytest.raises(CheckViolation):
        database.serializable(
            lambda connection: repository.begin(
                connection,
                principal_id=principal_id,
                key=key,
                command_id=command_id,
                content_hash=content_hash,
            )
        )

    def commit(connection: Connection[tuple[object, ...]]) -> StoredResponse:
        assert (
            repository.begin(
                connection,
                principal_id=principal_id,
                key=key,
                command_id=command_id,
                content_hash=content_hash,
            )
            is None
        )
        return repository.finish(
            connection,
            principal_id=principal_id,
            key=key,
            command_id=command_id,
            content_hash=content_hash,
            status_code=500,
            response_body=b'{"error":"committed"}',
        )

    database.serializable(commit)
    replay = database.serializable(
        lambda connection: repository.begin(
            connection,
            principal_id=principal_id,
            key=key,
            command_id=command_id,
            content_hash=content_hash,
        )
    )
    assert replay == StoredResponse(500, b'{"error":"committed"}', True)
    changed = command_content_hash("/v1/example", {}, {"value": 2})
    with pytest.raises(IdempotencyConflict):
        database.serializable(
            lambda connection: repository.begin(
                connection,
                principal_id=principal_id,
                key=uuid4(),
                command_id=command_id,
                content_hash=changed,
            )
        )
