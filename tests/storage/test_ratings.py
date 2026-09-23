from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_loads
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.digests import DigestRepository
from research_agent.storage.errors import StateConflict
from research_agent.storage.ratings import RatingRepository
from test_digests import seed_single_entry_digest

pytestmark = pytest.mark.integration
PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)


def identity(principal: UUID | None = None) -> CommandIdentity:
    return CommandIdentity(principal or uuid4(), uuid4(), uuid4(), uuid4())


@dataclass
class Storage:
    database: Database
    ratings: RatingRepository
    digests: DigestRepository

    def record(
        self, *, rater_id: UUID, digest_entry_id: UUID, value: str
    ) -> dict[str, Any]:
        response = self.ratings.execute(
            "record",
            identity=identity(),
            payload={
                "rater_id": str(rater_id),
                "paper_hash": "a" * 64,
                "digest_entry_id": str(digest_entry_id),
                "value": value,
            },
        )
        return dict(canonical_loads(response.body)["data"])

    def seed_entry(self) -> UUID:
        return seed_single_entry_digest(self.digests)


@pytest.fixture
def storage(postgres_dsn: str, artifact_root: Path) -> Storage:
    database = Database(postgres_dsn)
    store = ArtifactStore(artifact_root)
    return Storage(
        database,
        RatingRepository(
            database,
            store,
            producer=PRODUCER,
            config_hash="c" * 64,
            retention_policy_hash="d" * 64,
        ),
        DigestRepository(
            database,
            store,
            producer=PRODUCER,
            config_hash="c" * 64,
            retention_policy_hash="d" * 64,
        ),
    )


def test_a_rating_is_stored_against_the_rater_paper_and_digest_entry(
    storage: Storage,
) -> None:
    rater_id, digest_entry_id = uuid4(), storage.seed_entry()
    result = storage.record(
        rater_id=rater_id, digest_entry_id=digest_entry_id, value="like"
    )
    assert UUID(result["rating_id"])
    with storage.database.connect() as connection:
        row = connection.execute(
            "SELECT rater_id, digest_entry_id, value FROM ratings WHERE id=%s",
            (result["rating_id"],),
        ).fetchone()
    assert row == (rater_id, digest_entry_id, "like")


def test_a_rater_cannot_rate_the_same_digest_entry_twice(storage: Storage) -> None:
    rater_id, digest_entry_id = uuid4(), storage.seed_entry()
    storage.record(rater_id=rater_id, digest_entry_id=digest_entry_id, value="like")
    with pytest.raises(StateConflict):
        storage.record(
            rater_id=rater_id, digest_entry_id=digest_entry_id, value="dislike"
        )


def test_rated_entries_lists_one_raters_entries_without_their_values(
    storage: Storage,
) -> None:
    rater_id, other_id = uuid4(), uuid4()
    rated, unrated = storage.seed_entry(), storage.seed_entry()
    storage.record(rater_id=rater_id, digest_entry_id=rated, value="dislike")
    storage.record(rater_id=other_id, digest_entry_id=unrated, value="like")
    entries = storage.ratings.rated_entries(str(rater_id))
    assert entries == ({"entry_id": str(rated), "paper_hash": "a" * 64},)
    assert storage.ratings.rated_entries(str(uuid4())) == ()


def test_different_raters_may_rate_the_same_digest_entry(storage: Storage) -> None:
    digest_entry_id = storage.seed_entry()
    first = storage.record(
        rater_id=uuid4(), digest_entry_id=digest_entry_id, value="like"
    )
    second = storage.record(
        rater_id=uuid4(), digest_entry_id=digest_entry_id, value="skip"
    )
    assert first["rating_id"] != second["rating_id"]
