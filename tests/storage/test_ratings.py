from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_loads
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.digests import DigestRepository
from research_agent.storage.errors import StateConflict, UnavailableInput
from research_agent.storage.ratings import RatingRepository
from research_agent.storage.raters import RaterRepository
from tests.storage.test_digests import _hash, entry, store_payload

pytestmark = pytest.mark.integration
PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)


def identity(principal: UUID | None = None) -> CommandIdentity:
    return CommandIdentity(principal or uuid4(), uuid4(), uuid4(), uuid4())


@dataclass
class Storage:
    database: Database
    ratings: RatingRepository
    digests: DigestRepository
    raters: RaterRepository

    def record(
        self,
        *,
        rater_id: UUID,
        paper_hash: str,
        digest_entry_id: UUID,
        value: str,
    ) -> dict[str, Any]:
        response = self.ratings.execute(
            "record",
            identity=identity(),
            payload={
                "rater_id": str(rater_id),
                "paper_hash": paper_hash,
                "digest_entry_id": str(digest_entry_id),
                "value": value,
            },
        )
        envelope = cast(dict[str, Any], canonical_loads(response.body))
        return cast(dict[str, Any], envelope["data"])

    def provision(self, rater_id: UUID, island: str) -> None:
        self.raters.execute(
            "provision",
            identity=identity(),
            payload={
                "rater_id": str(rater_id),
                "island": island,
                "salt": "a" * 32,
                "credential_hash": "b" * 64,
            },
        )

    def seed_entry(
        self, *, island: str = "cs", batch_id: str | None = None
    ) -> tuple[UUID, str, str]:
        entry_id = uuid4()
        paper_hash = _hash(f"paper-{entry_id}")
        payload = store_payload(
            batch_id=batch_id,
            island=island,
            entries=(entry(entry_id, paper_hash=paper_hash),),
        )
        self.digests.execute("store", identity=identity(), payload=payload)
        return entry_id, paper_hash, payload["batch_id"]


@pytest.fixture
def storage(postgres_dsn: str, artifact_root: Path) -> Storage:
    database = Database(postgres_dsn)
    store = ArtifactStore(artifact_root)
    return Storage(
        database=database,
        ratings=RatingRepository(
            database,
            store,
            producer=PRODUCER,
            config_hash="c" * 64,
            retention_policy_hash="d" * 64,
        ),
        digests=DigestRepository(
            database,
            store,
            producer=PRODUCER,
            config_hash="c" * 64,
            retention_policy_hash="d" * 64,
        ),
        raters=RaterRepository(
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
    rater_id = uuid4()
    storage.provision(rater_id, "cs")
    digest_entry_id, paper_hash, _ = storage.seed_entry()
    result = storage.record(
        rater_id=rater_id,
        paper_hash=paper_hash,
        digest_entry_id=digest_entry_id,
        value="like",
    )
    assert UUID(result["rating_id"])
    with storage.database.connect() as connection:
        row = connection.execute(
            "SELECT rater_id, digest_entry_id, value FROM ratings WHERE id=%s",
            (result["rating_id"],),
        ).fetchone()
    assert row == (rater_id, digest_entry_id, "like")


def test_a_rater_cannot_rate_the_same_digest_entry_twice(storage: Storage) -> None:
    rater_id = uuid4()
    storage.provision(rater_id, "cs")
    digest_entry_id, paper_hash, _ = storage.seed_entry()
    storage.record(
        rater_id=rater_id,
        paper_hash=paper_hash,
        digest_entry_id=digest_entry_id,
        value="like",
    )
    with pytest.raises(StateConflict):
        storage.record(
            rater_id=rater_id,
            paper_hash=paper_hash,
            digest_entry_id=digest_entry_id,
            value="dislike",
        )


def test_a_quant_ph_rater_may_rate_a_quant_hyphen_ph_digest(storage: Storage) -> None:
    rater_id = uuid4()
    storage.provision(rater_id, "quant_ph")
    digest_entry_id, paper_hash, _ = storage.seed_entry(island="quant-ph")

    result = storage.record(
        rater_id=rater_id,
        paper_hash=paper_hash,
        digest_entry_id=digest_entry_id,
        value="skip",
    )

    assert UUID(result["rating_id"])


def test_rated_entries_lists_one_raters_entries_without_their_values(
    storage: Storage,
) -> None:
    rater_id, other_id = uuid4(), uuid4()
    storage.provision(rater_id, "cs")
    storage.provision(other_id, "quant_ph")
    rated, rated_hash, _ = storage.seed_entry()
    unrated, unrated_hash, _ = storage.seed_entry(island="quant-ph")
    storage.record(
        rater_id=rater_id, paper_hash=rated_hash, digest_entry_id=rated, value="dislike"
    )
    storage.record(
        rater_id=other_id,
        paper_hash=unrated_hash,
        digest_entry_id=unrated,
        value="like",
    )
    entries = storage.ratings.rated_entries(str(rater_id))
    assert entries == ({"entry_id": str(rated), "paper_hash": rated_hash},)
    assert storage.ratings.rated_entries(str(uuid4())) == ()


def test_ratings_in_batch_lists_one_raters_own_ratings_of_that_batch_only(
    storage: Storage,
) -> None:
    rater_id, other_id = uuid4(), uuid4()
    storage.provision(rater_id, "cs")
    storage.provision(other_id, "quant_ph")
    batch, other_batch = "1" * 64, "2" * 64
    in_batch, second_in_batch, elsewhere = uuid4(), uuid4(), uuid4()
    other_island = uuid4()
    paper, second_paper = "a" * 64, "e" * 64
    storage.digests.execute(
        "store",
        identity=identity(),
        payload=store_payload(
            batch_id=batch,
            entries=(
                entry(in_batch, paper_hash=paper),
                entry(second_in_batch, position=1, paper_hash=second_paper),
            ),
        ),
    )
    storage.digests.execute(
        "store",
        identity=identity(),
        payload=store_payload(
            batch_id=other_batch, entries=(entry(elsewhere, paper_hash=paper),)
        ),
    )
    storage.digests.execute(
        "store",
        identity=identity(),
        payload=store_payload(
            batch_id=batch,
            island="quant-ph",
            entries=(entry(other_island, paper_hash=paper),),
        ),
    )
    first = storage.record(
        rater_id=rater_id, paper_hash=paper, digest_entry_id=in_batch, value="like"
    )
    second = storage.record(
        rater_id=rater_id,
        paper_hash=second_paper,
        digest_entry_id=second_in_batch,
        value="skip",
    )
    storage.record(
        rater_id=rater_id, paper_hash=paper, digest_entry_id=elsewhere, value="like"
    )
    storage.record(
        rater_id=other_id,
        paper_hash=paper,
        digest_entry_id=other_island,
        value="dislike",
    )

    ratings = storage.ratings.ratings_in_batch(str(rater_id), batch)

    assert ratings == (
        {
            "rating_id": first["rating_id"],
            "digest_entry_id": str(in_batch),
            "paper_hash": paper,
            "value": "like",
            "rated_at": first["rated_at"],
        },
        {
            "rating_id": second["rating_id"],
            "digest_entry_id": str(second_in_batch),
            "paper_hash": second_paper,
            "value": "skip",
            "rated_at": second["rated_at"],
        },
    )
    assert storage.ratings.ratings_in_batch(str(uuid4()), batch) == ()


def test_a_rating_refuses_an_unregistered_rater_without_writes(
    storage: Storage,
) -> None:
    digest_entry_id, paper_hash, _ = storage.seed_entry()

    with pytest.raises(UnavailableInput, match="unavailable"):
        storage.record(
            rater_id=uuid4(),
            paper_hash=paper_hash,
            digest_entry_id=digest_entry_id,
            value="like",
        )

    assert _rating_write_counts(storage.database) == (0, 0)


def test_a_rating_refuses_another_islands_entry_without_writes(
    storage: Storage,
) -> None:
    rater_id = uuid4()
    storage.provision(rater_id, "quant_ph")
    digest_entry_id, paper_hash, _ = storage.seed_entry(island="cs")

    with pytest.raises(UnavailableInput, match="unavailable"):
        storage.record(
            rater_id=rater_id,
            paper_hash=paper_hash,
            digest_entry_id=digest_entry_id,
            value="dislike",
        )

    assert _rating_write_counts(storage.database) == (0, 0)


def test_a_rating_refuses_a_mismatched_paper_without_writes(storage: Storage) -> None:
    rater_id = uuid4()
    storage.provision(rater_id, "cs")
    digest_entry_id, _, _ = storage.seed_entry()

    with pytest.raises(UnavailableInput, match="unavailable"):
        storage.record(
            rater_id=rater_id,
            paper_hash="f" * 64,
            digest_entry_id=digest_entry_id,
            value="like",
        )

    assert _rating_write_counts(storage.database) == (0, 0)


def test_ratings_in_batch_lists_only_the_raters_matching_batch(
    storage: Storage,
) -> None:
    rater_id = uuid4()
    storage.provision(rater_id, "cs")
    selected_batch = "1" * 64
    selected_id, selected_hash, _ = storage.seed_entry(batch_id=selected_batch)
    other_id, other_hash, other_batch = storage.seed_entry()
    selected = storage.record(
        rater_id=rater_id,
        paper_hash=selected_hash,
        digest_entry_id=selected_id,
        value="like",
    )
    storage.record(
        rater_id=rater_id,
        paper_hash=other_hash,
        digest_entry_id=other_id,
        value="skip",
    )

    assert storage.ratings.ratings_in_batch(str(rater_id), selected_batch) == (
        {
            "rating_id": selected["rating_id"],
            "digest_entry_id": str(selected_id),
            "paper_hash": selected_hash,
            "value": "like",
            "rated_at": selected["rated_at"],
        },
    )
    assert storage.ratings.ratings_in_batch(str(uuid4()), selected_batch) == ()
    assert storage.ratings.ratings_in_batch(str(rater_id), other_batch)[0][
        "digest_entry_id"
    ] == str(other_id)


def _rating_write_counts(database: Database) -> tuple[int, int]:
    with database.connect() as connection:
        ratings = connection.execute("SELECT count(*) FROM ratings").fetchone()
        events = connection.execute(
            "SELECT count(*) FROM ledger_records WHERE event_kind='rating_recorded'"
        ).fetchone()
    assert ratings is not None and events is not None
    return cast(int, ratings[0]), cast(int, events[0])
