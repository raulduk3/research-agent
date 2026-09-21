"""PostgreSQL connection and bounded transaction retry ownership."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

import psycopg
from psycopg import Connection
from psycopg.errors import DeadlockDetected, SerializationFailure

from research_agent.storage.errors import TransactionUnavailable

T = TypeVar("T")


class Database:
    """Own database connections for the storage service.

    A transaction callback may be run more than once. It must contain database
    work only; callers must finish filesystem and external effects first.
    """

    _BACKOFF_SECONDS = (0.010, 0.030)

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def connect(self) -> Connection[tuple[object, ...]]:
        return psycopg.connect(self._dsn)

    def serializable(
        self, operation: Callable[[Connection[tuple[object, ...]]], T]
    ) -> T:
        last_error: BaseException | None = None
        for attempt in range(3):
            try:
                with self.connect() as connection:
                    connection.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                    return operation(connection)
            except (SerializationFailure, DeadlockDetected) as error:
                last_error = error
                if attempt == 2:
                    break
                time.sleep(self._BACKOFF_SECONDS[attempt])
        raise TransactionUnavailable(
            "serializable transaction retry exhausted"
        ) from last_error

    def transaction(
        self, operation: Callable[[Connection[tuple[object, ...]]], T]
    ) -> T:
        with self.connect() as connection:
            return operation(connection)
