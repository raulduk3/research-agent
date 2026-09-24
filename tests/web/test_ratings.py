from __future__ import annotations

from uuid import UUID, uuid4

import psycopg
import pytest

from research_agent.storage.client import StorageClient
from research_agent.web.ratings import RatingOutcome, submit_rating

pytestmark = pytest.mark.integration

PAPER_HASH = "a" * 64
RATER_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def record(
    storage: StorageClient,
    *,
    rater_id: UUID = RATER_ID,
    paper_hash: str,
    digest_entry_id: UUID,
    value: str,
) -> tuple[RatingOutcome, UUID, UUID]:
    outcome = submit_rating(
        storage,
        rater_id=rater_id,
        paper_hash=paper_hash,
        digest_entry_id=digest_entry_id,
        value=value,
        command_id=uuid4(),
        request_id=uuid4(),
        idempotency_key=uuid4(),
    )
    return outcome, rater_id, digest_entry_id


@pytest.mark.parametrize("value", ["like", "dislike", "skip"])
def test_each_rating_value_is_stored_exactly_as_given(
    storage_client: StorageClient,
    postgres_dsn: str,
    stored_digest_entry: tuple[UUID, str, str],
    value: str,
) -> None:
    stored_digest_entry_id, paper_hash, _ = stored_digest_entry
    outcome, rater_id, digest_entry_id = record(
        storage_client,
        paper_hash=paper_hash,
        digest_entry_id=stored_digest_entry_id,
        value=value,
    )

    assert outcome.accepted
    assert outcome.rating_id is not None
    assert outcome.rated_at is not None
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        row = connection.execute(
            "SELECT rater_id, paper_hash, digest_entry_id, value FROM ratings WHERE id=%s",
            (outcome.rating_id,),
        ).fetchone()
    assert row == (rater_id, bytes.fromhex(PAPER_HASH), digest_entry_id, value)


def test_a_second_rating_of_the_same_entry_is_reported_as_not_accepted(
    storage_client: StorageClient, stored_digest_entry: tuple[UUID, str, str]
) -> None:
    digest_entry_id, paper_hash, _ = stored_digest_entry
    rater_id = RATER_ID

    def attempt(value: str) -> RatingOutcome:
        return submit_rating(
            storage_client,
            rater_id=rater_id,
            paper_hash=paper_hash,
            digest_entry_id=digest_entry_id,
            value=value,
            command_id=uuid4(),
            request_id=uuid4(),
            idempotency_key=uuid4(),
        )

    first = attempt("like")
    second = attempt("dislike")

    assert first.accepted
    assert not second.accepted
    assert second.reason == "already rated"


def test_a_rater_reads_their_persisted_rating_for_the_batch(
    storage_client: StorageClient, stored_digest_entry: tuple[UUID, str, str]
) -> None:
    digest_entry_id, paper_hash, batch_id = stored_digest_entry
    outcome, _, _ = record(
        storage_client,
        paper_hash=paper_hash,
        digest_entry_id=digest_entry_id,
        value="dislike",
    )

    result = storage_client.list_own_ratings(RATER_ID, batch_id=batch_id)

    assert result.data["ratings"] == [
        {
            "rating_id": outcome.rating_id,
            "digest_entry_id": str(digest_entry_id),
            "paper_hash": paper_hash,
            "value": "dislike",
            "rated_at": outcome.rated_at,
        }
    ]


def test_a_rating_that_cannot_be_stored_is_reported_as_not_saved_never_filled_in(
    forbidden_storage_client: StorageClient,
) -> None:
    outcome, _, _ = record(
        forbidden_storage_client,
        paper_hash=PAPER_HASH,
        digest_entry_id=uuid4(),
        value="like",
    )

    assert not outcome.accepted
    assert outcome.rating_id is None
    assert outcome.rated_at is None
    assert outcome.reason == "not saved"
