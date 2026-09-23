"""`LocalStorage.enqueue(ahead=...)` and `.expedite()` order claims (#151).

Claim order is `ORDER BY scheduled_at, id` (`storage/jobs.py#_claim`). These
exercise the two primitives `ingest/pilot_run.py#_advance` builds the
schedule-openalex-ahead-of-documents behavior from, directly against real
storage: an `ahead` job jumps a normally scheduled backlog, and `expedite`
moves an already-queued job the same way for a build started before this
change.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest

from research_agent.contracts import canonical_loads
from research_agent.contracts.primitives import ProducerVersion
from research_agent.ingest.pilot import Identity
from research_agent.ingest.pilot_local import LocalStorage, local_storage
from research_agent.storage.commands import CommandIdentity

pytestmark = pytest.mark.integration

IDENTITY = Identity(
    ProducerVersion("a" * 64, "b" * 40, 1), "c" * 64, "d" * 64, "e" * 64
)


def _claim(storage: LocalStorage) -> str | None:
    worker_id = uuid4()
    response = storage.jobs.execute(
        "claim",
        identity=CommandIdentity(worker_id, uuid4(), uuid4(), uuid4()),
        payload={"worker_id": str(worker_id), "kinds": ["capture"]},
    )
    lease = cast(dict[str, Any], canonical_loads(response.body))["data"]["lease"]
    return None if lease is None else str(lease["job_id"])


@pytest.fixture
def storage(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> Iterator[LocalStorage]:
    with local_storage(
        dsn=postgres_dsn,
        artifact_root=artifact_root,
        tls_directory=tmp_path / "tls",
        identity=IDENTITY,
    ) as value:
        yield value


def test_an_ahead_job_enqueued_after_normal_jobs_is_claimed_first(
    storage: LocalStorage,
) -> None:
    storage.enqueue({"stage": "documents", "family": {"family_id": "A"}})
    storage.enqueue({"stage": "documents", "family": {"family_id": "B"}})
    ahead = storage.enqueue(
        {"stage": "openalex", "family": {"family_id": "C"}}, ahead=True
    )
    assert _claim(storage) == str(ahead)


def test_expedite_moves_a_queued_job_ahead_of_an_earlier_one(
    storage: LocalStorage,
) -> None:
    storage.enqueue({"stage": "documents", "family": {"family_id": "A"}})
    late = storage.enqueue({"stage": "openalex", "family": {"family_id": "B"}})
    storage.expedite(late)
    assert _claim(storage) == str(late)


def test_expedite_refuses_a_job_that_is_not_queued(storage: LocalStorage) -> None:
    job_id = storage.enqueue({"stage": "documents", "family": {"family_id": "A"}})
    assert _claim(storage) == str(job_id)
    with pytest.raises(ValueError):
        storage.expedite(job_id)
