"""PostgreSQL connection and bounded transaction retry ownership."""

from __future__ import annotations

import random
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

    _ATTEMPTS = 6
    _BACKOFF_BASE_SECONDS = 0.010
    _BACKOFF_CAP_SECONDS = 0.500

    def __init__(
        self, dsn: str, *, sleep: Callable[[float], None] = time.sleep
    ) -> None:
        self._dsn = dsn
        self._sleep = sleep

    @classmethod
    def backoff_ceiling(cls, retry: int) -> float:
        """Upper bound of the wait before retry `retry` (0-based): exponential
        from the base, capped."""
        return min(cls._BACKOFF_CAP_SECONDS, cls._BACKOFF_BASE_SECONDS * 2.0**retry)

    def connect(self) -> Connection[tuple[object, ...]]:
        return psycopg.connect(self._dsn)

    def serializable(
        self, operation: Callable[[Connection[tuple[object, ...]]], T]
    ) -> T:
        last_error: BaseException | None = None
        for attempt in range(self._ATTEMPTS):
            try:
                with self.connect() as connection:
                    connection.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                    return operation(connection)
            except (SerializationFailure, DeadlockDetected) as error:
                last_error = error
                if attempt == self._ATTEMPTS - 1:
                    break
                # Full jitter: concurrent losers of one pivot do not retry in step.
                self._sleep(random.uniform(0.0, self.backoff_ceiling(attempt)))
        raise TransactionUnavailable(
            "serializable transaction retry exhausted"
        ) from last_error

    def transaction(
        self, operation: Callable[[Connection[tuple[object, ...]]], T]
    ) -> T:
        with self.connect() as connection:
            return operation(connection)
