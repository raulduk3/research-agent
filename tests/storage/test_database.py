from __future__ import annotations

import psycopg
import pytest

from research_agent.storage.database import Database
from research_agent.storage.errors import TransactionUnavailable

pytestmark = pytest.mark.integration

_RAISE_SERIALIZATION_FAILURE = """
DO $$ BEGIN
    RAISE EXCEPTION 'pivot' USING ERRCODE = 'serialization_failure';
END $$
"""


def _recording_database(dsn: str) -> tuple[Database, list[float]]:
    waits: list[float] = []
    return Database(dsn, sleep=waits.append), waits


def test_transient_serialization_failure_is_retried_until_success(
    unmigrated_postgres_dsn: str,
) -> None:
    database, waits = _recording_database(unmigrated_postgres_dsn)
    calls = 0

    def operation(connection: psycopg.Connection[tuple[object, ...]]) -> int:
        nonlocal calls
        calls += 1
        # Four losses would have exhausted the former three-attempt budget.
        if calls <= 4:
            connection.execute(_RAISE_SERIALIZATION_FAILURE)
        isolation = connection.execute("SHOW transaction_isolation").fetchone()
        assert isolation == ("serializable",)
        return calls

    assert database.serializable(operation) == 5
    assert len(waits) == 4


def test_conflict_that_never_clears_exhausts_with_typed_error(
    unmigrated_postgres_dsn: str,
) -> None:
    database, waits = _recording_database(unmigrated_postgres_dsn)
    calls = 0

    def operation(connection: psycopg.Connection[tuple[object, ...]]) -> None:
        nonlocal calls
        calls += 1
        connection.execute(_RAISE_SERIALIZATION_FAILURE)

    with pytest.raises(TransactionUnavailable) as raised:
        database.serializable(operation)
    assert isinstance(raised.value.__cause__, psycopg.errors.SerializationFailure)
    assert calls == 6
    assert len(waits) == 5


def test_backoff_is_full_jitter_under_an_exponential_capped_ceiling(
    unmigrated_postgres_dsn: str,
) -> None:
    assert [Database.backoff_ceiling(retry) for retry in range(7)] == [
        0.010,
        0.020,
        0.040,
        0.080,
        0.160,
        0.320,
        0.500,
    ]
    waits: list[float] = []
    for _ in range(10):
        database, run_waits = _recording_database(unmigrated_postgres_dsn)
        with pytest.raises(TransactionUnavailable):
            database.serializable(
                lambda connection: connection.execute(_RAISE_SERIALIZATION_FAILURE)
            )
        assert all(
            0.0 <= wait <= Database.backoff_ceiling(retry)
            for retry, wait in enumerate(run_waits)
        )
        waits.extend(run_waits)
    # Jittered, not a fixed schedule: the waits for one retry differ run to run.
    assert len({round(wait, 9) for wait in waits[::5]}) > 1
