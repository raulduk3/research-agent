"""Dated external verification registry (SDD-SR-20).

Every borrowed component and every cited result carries one verification
entry keyed by its artifact/source identity: a source URL, the UTC instant
it was last checked against that source, a verifier reference, an optional
content hash and a status of verified or unverified. A publication date is
never used as `checked_at`. Missing evidence makes an entry explicitly
unverified rather than silently absent, and a reference whose immutable
component revision differs from the verified one is refused.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_https_url,
    validate_non_empty_string,
    validate_sha256,
    validate_utc_instant,
)

Status = Literal["verified", "unverified"]


@dataclass(frozen=True, slots=True)
class VerificationRecord:
    """One dated check of a borrowed component or a cited result."""

    artifact_identity: str
    component_revision: str
    source_url: str
    status: Status
    checked_at: str | None = None
    verifier_reference: str | None = None
    content_hash: str | None = None

    def __post_init__(self) -> None:
        validate_non_empty_string(self.artifact_identity)
        validate_non_empty_string(self.component_revision)
        validate_https_url(self.source_url)
        if self.status not in ("verified", "unverified"):
            raise ContractValidationError("status must be verified or unverified")
        if self.status == "verified":
            if self.checked_at is None or self.verifier_reference is None:
                raise ContractValidationError(
                    "a verified entry requires checked_at and verifier_reference"
                )
            validate_utc_instant(self.checked_at)
            validate_non_empty_string(self.verifier_reference)
        else:
            if self.checked_at is not None or self.verifier_reference is not None:
                raise ContractValidationError(
                    "an unverified entry carries no check evidence"
                )
        if self.content_hash is not None:
            validate_sha256(self.content_hash)


class VerificationUnavailable(RuntimeError):
    """Raised when a readiness claim depends on a missing or unverified entry."""


@dataclass(slots=True)
class VerificationRegistry:
    """One verification entry per artifact identity; missing means unavailable."""

    _entries: dict[str, VerificationRecord] = field(default_factory=dict)

    def register(self, record: VerificationRecord) -> None:
        self._entries[record.artifact_identity] = record

    def lookup(self, artifact_identity: str) -> VerificationRecord | None:
        return self._entries.get(artifact_identity)

    def require_verified(
        self, artifact_identity: str, *, component_revision: str
    ) -> VerificationRecord:
        """Resolve a readiness-relied-on entry; refuse anything but a live match."""

        record = self._entries.get(artifact_identity)
        if record is None:
            raise VerificationUnavailable(
                f"'{artifact_identity}' has no verification entry"
            )
        if record.status != "verified":
            raise VerificationUnavailable(f"'{artifact_identity}' is unverified")
        if record.component_revision != component_revision:
            raise VerificationUnavailable(
                f"'{artifact_identity}' verified revision differs from the one referenced"
            )
        return record
