"""Storage-owned publication authority outside an artifact's hashed body."""

from dataclasses import dataclass

from .canonical import canonical_json, canonical_loads
from .primitives import (
    ContractValidationError,
    validate_positive_int,
    validate_sha256,
    validate_utc_instant,
)


@dataclass(frozen=True, slots=True)
class ArtifactPublicationReceipt:
    schema_version: int
    artifact_id: str
    committed_ledger_sequence: int
    published_at: str

    def __post_init__(self) -> None:
        if validate_positive_int(self.schema_version) != 1:
            raise ContractValidationError("unsupported publication receipt version")
        validate_sha256(self.artifact_id)
        validate_positive_int(self.committed_ledger_sequence)
        validate_utc_instant(self.published_at)

    def to_canonical_json(self) -> bytes:
        return canonical_json(
            {
                "schema_version": self.schema_version,
                "artifact_id": self.artifact_id,
                "committed_ledger_sequence": self.committed_ledger_sequence,
                "published_at": self.published_at,
            }
        )

    @classmethod
    def from_json(cls, raw: bytes) -> "ArtifactPublicationReceipt":
        value = canonical_loads(raw)
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "artifact_id",
            "committed_ledger_sequence",
            "published_at",
        }:
            raise ContractValidationError(
                "publication receipt fields do not match schema"
            )
        return cls(
            validate_positive_int(value["schema_version"]),
            validate_sha256(value["artifact_id"]),
            validate_positive_int(value["committed_ledger_sequence"]),
            validate_utc_instant(value["published_at"]),
        )
