"""Externally immutable chain-head receipts (SDD-SR-16).

Storage schedules anchoring after 100 new ledger records or 15 minutes,
whichever comes first, and sends the current sequence, record hash, profile
id and an idempotency key to a separate append-only receiver. The receiver's
authority is append/read only: it never accepts a replacement or a
decreasing sequence, and a request timeout never advances the acknowledged
watermark. Sealing refuses new seals once the unanchored backlog exceeds 30
minutes, while capture already recorded stays available.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_non_negative_int,
    validate_sha256,
    validate_utc_instant,
)

RECORD_INTERVAL = 100
TIME_INTERVAL = timedelta(minutes=15)
BACKLOG_BOUND = timedelta(minutes=30)


class AnchorTimeout(RuntimeError):
    """Raised by a transport when the receiver did not answer in time."""


@dataclass(frozen=True, slots=True)
class AnchorRequest:
    sequence: int
    record_hash: str
    profile_id: str
    idempotency_key: str

    def __post_init__(self) -> None:
        validate_non_negative_int(self.sequence)
        validate_sha256(self.record_hash)
        validate_non_empty_string(self.profile_id)
        validate_non_empty_string(self.idempotency_key)


@dataclass(frozen=True, slots=True)
class AnchorReceipt:
    """An immutable, receiver-authenticated proof that a sequence was anchored."""

    sequence: int
    record_hash: str
    receiver_signature: str
    accepted_at: str

    def __post_init__(self) -> None:
        validate_non_negative_int(self.sequence)
        validate_sha256(self.record_hash)
        validate_non_empty_string(self.receiver_signature)
        validate_utc_instant(self.accepted_at)


@dataclass(frozen=True, slots=True)
class AnchorWatermark:
    """The last sequence storage has an accepted receipt for."""

    last_receipted_sequence: int
    last_receipted_at: str

    def __post_init__(self) -> None:
        validate_non_negative_int(self.last_receipted_sequence)
        validate_utc_instant(self.last_receipted_at)


def record_receipt(previous: AnchorReceipt | None, new: AnchorReceipt) -> AnchorReceipt:
    """Accept a receipt only if it strictly advances the sequence; never replace."""

    if previous is not None and new.sequence <= previous.sequence:
        raise ContractValidationError(
            "receiver rejects a replacement or a decreasing sequence"
        )
    return new


def is_anchoring_due(
    watermark: AnchorWatermark, *, current_sequence: int, now: datetime
) -> bool:
    """Anchor after 100 new records or 15 minutes, whichever comes first."""

    if current_sequence - watermark.last_receipted_sequence >= RECORD_INTERVAL:
        return True
    last = datetime.strptime(
        watermark.last_receipted_at, "%Y-%m-%dT%H:%M:%S.%fZ"
    ).replace(tzinfo=timezone.utc)
    return now - last >= TIME_INTERVAL


def exceeds_backlog(watermark: AnchorWatermark, *, now: datetime) -> bool:
    """Refuse new seals once the unanchored backlog exceeds the 30-minute bound."""

    last = datetime.strptime(
        watermark.last_receipted_at, "%Y-%m-%dT%H:%M:%S.%fZ"
    ).replace(tzinfo=timezone.utc)
    return now - last > BACKLOG_BOUND


class AnchorClient:
    """Sends anchor requests through an injectable transport; never mutates on timeout."""

    def __init__(self, transport: Callable[[AnchorRequest], AnchorReceipt]) -> None:
        self._transport = transport

    def submit(self, request: AnchorRequest) -> AnchorReceipt | None:
        """Return the receiver's receipt, or None if the attempt timed out."""

        try:
            return self._transport(request)
        except AnchorTimeout:
            return None
