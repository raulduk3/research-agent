"""The immutable representation manifest for the pinned launch embedder.

Appendix A: Launch profile, pinned model choices and representation; SDD MD-06.
The manifest fixes the frozen `nomic-ai/modernbert-embed-base` identity every
overview and passage vector is computed under, so a wrong dimension or a
revision drift is rejected before it can enter a vector space.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from research_agent.contracts.canonical import canonical_json, sha256_hex
from research_agent.contracts.learning import EMBEDDING_DIMENSION
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_sha256,
    validate_utc_date,
)

__all__ = [
    "MODEL_ID",
    "REVISION",
    "ADOPTED_CHECKPOINT_DATE",
    "DTYPE",
    "POOLING",
    "DOCUMENT_PREFIX",
    "QUERY_PREFIX",
    "MAX_MODEL_TOKENS",
    "RepresentationManifest",
]

# Decision 0011: the frozen launch representation. Facts are read from the
# model's public metadata, not from local execution (Appendix A).
MODEL_ID = "nomic-ai/modernbert-embed-base"
REVISION = "d556a88e332558790b210f7bdbe87da2fa94a8d8"
ADOPTED_CHECKPOINT_DATE = "2026-09-21"
DTYPE = "float32"
POOLING = "attention_masked_mean"
DOCUMENT_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "
MAX_MODEL_TOKENS = 8192

_REVISION_PATTERN = re.compile(r"[0-9a-f]{40}\Z")


def _validate_revision(value: object) -> str:
    if not isinstance(value, str) or _REVISION_PATTERN.fullmatch(value) is None:
        raise ContractValidationError(
            "revision must be 40 lowercase hexadecimal characters",
        )
    return value


@dataclass(frozen=True, slots=True)
class RepresentationManifest:
    """The pinned identity a served vector was computed under.

    Field values other than the file hashes and qualification state are fixed
    to the launch profile; construction rejects any drift from them rather
    than silently accepting an alternate model, revision or format.
    """

    model_id: str
    revision: str
    checkpoint_date: str
    dtype: str
    dimension: int
    pooling: str
    document_prefix: str
    query_prefix: str
    max_model_tokens: int
    tokenizer_hash: str
    weight_hash: str
    qualified: bool

    def __post_init__(self) -> None:
        if validate_non_empty_string(self.model_id) != MODEL_ID:
            raise ContractValidationError("model_id must be the pinned launch model")
        if _validate_revision(self.revision) != REVISION:
            raise ContractValidationError(
                "revision must be the pinned launch revision",
            )
        validate_utc_date(self.checkpoint_date)
        if self.dtype != DTYPE:
            raise ContractValidationError("dtype must be float32")
        if self.dimension != EMBEDDING_DIMENSION:
            raise ContractValidationError(
                "dimension must match the pinned representation width",
            )
        if self.pooling != POOLING:
            raise ContractValidationError(
                "pooling must be attention-masked mean pooling",
            )
        if self.document_prefix != DOCUMENT_PREFIX:
            raise ContractValidationError("document_prefix must be the pinned prefix")
        if self.query_prefix != QUERY_PREFIX:
            raise ContractValidationError("query_prefix must be the pinned prefix")
        if self.max_model_tokens != MAX_MODEL_TOKENS:
            raise ContractValidationError(
                "max_model_tokens must be the pinned model limit",
            )
        validate_sha256(self.tokenizer_hash)
        validate_sha256(self.weight_hash)
        if not isinstance(self.qualified, bool):
            raise ContractValidationError("qualified must be a boolean")

    def to_dict(self) -> dict[str, object]:
        return {
            "model_id": self.model_id,
            "revision": self.revision,
            "checkpoint_date": self.checkpoint_date,
            "dtype": self.dtype,
            "dimension": self.dimension,
            "pooling": self.pooling,
            "document_prefix": self.document_prefix,
            "query_prefix": self.query_prefix,
            "max_model_tokens": self.max_model_tokens,
            "tokenizer_hash": self.tokenizer_hash,
            "weight_hash": self.weight_hash,
            "qualified": self.qualified,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @property
    def representation_hash(self) -> str:
        """The content-addressed identity every vector under this manifest carries.

        Qualification state is evidence about the manifest, not part of the
        representation it computes, so it is excluded from the identity hash;
        promoting a manifest from unqualified to qualified must not change the
        identity vectors already computed under it carry.
        """

        payload = self.to_dict()
        del payload["qualified"]
        return sha256_hex(canonical_json(payload))
