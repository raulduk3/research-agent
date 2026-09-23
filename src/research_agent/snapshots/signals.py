"""Provider-signal selection bounded by the snapshot's frozen publication cutoff (EN-36).

A paper card signal taken from an outside provider must come only from a
response captured before the batch's snapshot was frozen, never from a
later response read back to that date. Eligibility is decided from each
capture's own ledger publication watermark, captured when :class:`ArtifactRepository`
committed it (EN-07), never from a provider-claimed event date.
"""

from __future__ import annotations

from dataclasses import dataclass

from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_positive_int,
    validate_sha256,
    validate_utc_instant,
)
from research_agent.storage.verification import PublicationCutoff

__all__ = ["CapturedResponse", "ProviderSignal", "select_provider_signal"]

_UNAVAILABLE_REASON = "no_capture_before_snapshot_freeze"


@dataclass(frozen=True, slots=True)
class CapturedResponse:
    """One committed source-capture artifact eligible to carry a provider signal.

    ``observed_at`` is the provider's own claimed event date; it is carried
    for display only and never substitutes for ``published_at``/
    ``committed_ledger_sequence``, the ledger's own record of when this
    capture was committed.
    """

    provider_id: str
    capture_id: str
    payload_hash: str
    value: str
    observed_at: str
    published_at: str
    committed_ledger_sequence: int

    def __post_init__(self) -> None:
        validate_non_empty_string(self.provider_id)
        validate_sha256(self.capture_id)
        validate_sha256(self.payload_hash)
        validate_non_empty_string(self.value)
        validate_utc_instant(self.observed_at)
        validate_utc_instant(self.published_at)
        validate_positive_int(self.committed_ledger_sequence)


@dataclass(frozen=True, slots=True)
class ProviderSignal:
    """The provider signal a paper card may cite: a captured value or its absence."""

    provider_id: str
    capture_id: str | None
    payload_hash: str | None
    value: str | None
    unavailable_reason: str | None
    observed_at: str | None

    def __post_init__(self) -> None:
        validate_non_empty_string(self.provider_id)
        if self.value is None:
            if (
                self.capture_id is not None
                or self.payload_hash is not None
                or self.observed_at is not None
                or not self.unavailable_reason
            ):
                raise ContractValidationError(
                    "an unavailable provider signal requires no capture fields "
                    "but a reason"
                )
        else:
            if (
                self.capture_id is None
                or self.payload_hash is None
                or self.observed_at is None
                or self.unavailable_reason is not None
            ):
                raise ContractValidationError(
                    "an available provider signal requires its capture and no reason"
                )
            validate_sha256(self.capture_id)
            validate_sha256(self.payload_hash)
            validate_utc_instant(self.observed_at)


def select_provider_signal(
    candidates: tuple[CapturedResponse, ...],
    *,
    provider_id: str,
    cutoff: PublicationCutoff,
) -> ProviderSignal:
    """Select the eligible committed capture for one provider, or record why none exists.

    Eligibility is decided from each capture's own ledger publication
    watermark -- ``published_at`` and ``committed_ledger_sequence`` -- never
    from ``observed_at``, the date the provider itself reports: a response
    committed after the snapshot's freeze cutoff is ineligible even when its
    provider-claimed event date is earlier. Among eligible captures the most
    recently committed wins, so replaying a later snapshot with a later
    cutoff can surface a newly eligible capture in its place, never the
    other way around.
    """

    eligible = [
        candidate
        for candidate in candidates
        if candidate.provider_id == provider_id
        and candidate.committed_ledger_sequence <= cutoff.committed_ledger_sequence
        and candidate.published_at <= cutoff.published_at
    ]
    if not eligible:
        return ProviderSignal(provider_id, None, None, None, _UNAVAILABLE_REASON, None)
    latest = max(eligible, key=lambda candidate: candidate.committed_ledger_sequence)
    return ProviderSignal(
        provider_id,
        latest.capture_id,
        latest.payload_hash,
        latest.value,
        None,
        latest.observed_at,
    )
