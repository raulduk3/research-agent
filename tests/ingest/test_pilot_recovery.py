"""A storage command with an unknown outcome resumes instead of refusing the
replay (#178): the worker resends the identical idempotency key and content
before giving up, so storage either adopts what it already committed or
applies the command fresh.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from research_agent.contracts.primitives import ProducerVersion
from research_agent.ingest.pilot import Identity, PilotWorker, RateGate, Sources
from research_agent.ingest.pilot_local import (
    LocalStorage,
    local_storage,
    worker_principal,
)
from research_agent.storage.client import (
    StorageClient,
    StorageClientError,
    StorageTransportError,
)

pytestmark = pytest.mark.integration

IDENTITY = Identity(
    ProducerVersion("a" * 64, "b" * 40, 1), "c" * 64, "d" * 64, "e" * 64
)
FROZEN_AT = "2025-12-01T00:00:00.000000Z"


def _unreachable(*_: object, **__: object) -> Any:
    raise AssertionError("the select stage never touches an upstream source")


def _sources() -> Sources:
    return Sources(
        listing=_unreachable,
        document=_unreachable,
        openalex_match=_unreachable,
        openalex_cites=_unreachable,
        arxiv_gate=RateGate(0.001),
        openalex_gate=RateGate(0.001),
    )


class _ResponseLostOnce:
    """A `StorageClient` whose first matching call commits for real but the
    caller only ever observes a transport failure -- a response lost after
    storage already applied the command."""

    def __init__(self, inner: StorageClient, matches: Callable[[str], bool]) -> None:
        self._inner = inner
        self._matches = matches
        self._armed = True

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._inner, name)
        if not self._armed or not self._matches(name):
            return attribute

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            attribute(*args, **kwargs)
            self._armed = False
            raise StorageTransportError("simulated: response lost after commit")

        return wrapped


class _NeverArrives:
    """A `StorageClient` whose first `attempts` matching calls raise before
    the command ever reaches storage -- a request stuck on a dead
    connection, not a lost response."""

    def __init__(
        self, inner: StorageClient, matches: Callable[[str], bool], attempts: int
    ) -> None:
        self._inner = inner
        self._matches = matches
        self._remaining = attempts

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._inner, name)
        if self._remaining <= 0 or not self._matches(name):
            return attribute

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            self._remaining -= 1
            raise StorageTransportError("simulated: request never reached storage")

        return wrapped


class _RefusedAsChangedContent:
    """A `StorageClient` whose first matching call refuses with the typed
    conflict storage raises for a reused key with different content -- the
    prohibited alternative this change must never trigger, and must never
    swallow when something else does."""

    def __init__(self, inner: StorageClient, matches: Callable[[str], bool]) -> None:
        self._inner = inner
        self._matches = matches
        self._armed = True

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._inner, name)
        if not self._armed or not self._matches(name):
            return attribute
        self._armed = False

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            raise StorageClientError(
                status_code=409,
                request_id="00000000-0000-4000-8000-000000000000",
                code="idempotency_conflict",
                message="key or command identity changed content",
                retryable=False,
                evidence_ids=(),
                headers=(),
                body=b"{}",
            )

        return wrapped


def _expire_running_leases(storage: LocalStorage) -> None:
    storage.database.transaction(
        lambda connection: connection.execute(
            "UPDATE jobs SET expires_at = clock_timestamp() - interval '1 second'"
            " WHERE state = 'running'"
        )
    )


def test_a_lost_response_resumes_by_adopting_the_committed_result(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    tls = tmp_path / "tls"
    with local_storage(
        dsn=postgres_dsn,
        artifact_root=artifact_root,
        tls_directory=tls,
        identity=IDENTITY,
    ) as storage:
        worker = worker_principal(tls)
        storage.enqueue(
            {"stage": "select", "frozen_at": FROZEN_AT, "listing_reports": []}
        )
        client = _ResponseLostOnce(storage.client, lambda name: name == "complete")
        pilot = PilotWorker(
            client, worker_id=worker, identity=IDENTITY, sources=_sources()
        )
        assert pilot.run().jobs_completed == 1
        assert [state for _, state, _ in storage.job_rows()] == ["committed"]


def test_a_request_that_never_arrives_republishes_after_a_fresh_claim(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    tls = tmp_path / "tls"
    with local_storage(
        dsn=postgres_dsn,
        artifact_root=artifact_root,
        tls_directory=tls,
        identity=IDENTITY,
    ) as storage:
        worker = worker_principal(tls)
        storage.enqueue(
            {"stage": "select", "frozen_at": FROZEN_AT, "listing_reports": []}
        )
        dying = PilotWorker(
            _NeverArrives(storage.client, lambda name: name == "complete", 2),
            worker_id=worker,
            identity=IDENTITY,
            sources=_sources(),
        )
        with pytest.raises(StorageTransportError):
            dying.run()
        _expire_running_leases(storage)
        resumed = PilotWorker(
            storage.client, worker_id=worker, identity=IDENTITY, sources=_sources()
        )
        assert resumed.run().jobs_completed == 1
        assert [state for _, state, _ in storage.job_rows()] == ["committed"]


def test_a_changed_content_conflict_is_never_retried_or_swallowed(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    tls = tmp_path / "tls"
    with local_storage(
        dsn=postgres_dsn,
        artifact_root=artifact_root,
        tls_directory=tls,
        identity=IDENTITY,
    ) as storage:
        worker = worker_principal(tls)
        storage.enqueue(
            {"stage": "select", "frozen_at": FROZEN_AT, "listing_reports": []}
        )
        client = _RefusedAsChangedContent(
            storage.client, lambda name: name == "complete"
        )
        pilot = PilotWorker(
            client, worker_id=worker, identity=IDENTITY, sources=_sources()
        )
        with pytest.raises(StorageClientError, match="changed content"):
            pilot.run()
        assert [state for _, state, _ in storage.job_rows()] == ["running"]
