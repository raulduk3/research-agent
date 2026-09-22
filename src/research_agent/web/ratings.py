"""Recording one rater's like, dislike or skip through the storage API (IN-10)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from research_agent.storage.client import (
    StorageClient,
    StorageClientError,
    StorageTransportError,
)


@dataclass(frozen=True, slots=True)
class RatingOutcome:
    """What the rater sees after a rating attempt; never filled in speculatively."""

    accepted: bool
    rating_id: str | None
    rated_at: str | None
    reason: str | None


def submit_rating(
    storage: StorageClient,
    *,
    rater_id: UUID,
    paper_hash: str,
    digest_entry_id: UUID,
    value: str,
    command_id: UUID,
    request_id: UUID,
    idempotency_key: UUID,
) -> RatingOutcome:
    """Record one rater's rating of one digest entry through the storage API.

    ``rater_id`` must come from the caller's authenticated session, never
    from a request body field, so a forged identity in the form can never
    select another rater (PL-22). Storage supplies the event time. A second
    rating attempt for an already-rated entry comes back as unaccepted rather
    than silently overwriting or duplicating the first; a rating that cannot
    be stored is reported as not saved and the entry stays unrated, never
    filled in by default (IN-10).
    """
    try:
        result = storage.record_rating(
            rater_id=rater_id,
            paper_hash=paper_hash,
            digest_entry_id=digest_entry_id,
            value=value,
            command_id=command_id,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )
    except StorageClientError as error:
        reason = "already rated" if error.code == "state_conflict" else "not saved"
        return RatingOutcome(
            accepted=False, rating_id=None, rated_at=None, reason=reason
        )
    except StorageTransportError:
        return RatingOutcome(
            accepted=False, rating_id=None, rated_at=None, reason="not saved"
        )
    data = result.data
    return RatingOutcome(
        accepted=True,
        rating_id=str(data["rating_id"]),
        rated_at=str(data["rated_at"]),
        reason=None,
    )
