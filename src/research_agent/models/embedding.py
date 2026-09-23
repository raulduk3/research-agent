"""Frozen embedding inference under the pinned representation (MD-06).

Prefixing, attention-masked mean pooling and unit-L2 normalization are pure
functions shared by the real CPU Transformers backend and any test fixture,
so the pooling math itself is verified without downloading model weights.
Overview and passage feature assembly stay with the existing
``learning.features`` owner; this module only produces the per-text vectors
it consumes.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Iterable, Sequence
from typing import NamedTuple, Protocol

from research_agent.contracts.primitives import ContractValidationError
from research_agent.reader.extract import normalize_text

from .manifest import (
    DOCUMENT_PREFIX,
    MAX_MODEL_TOKENS,
    QUERY_PREFIX,
    RepresentationManifest,
)

__all__ = [
    "TokenBudgetExceededError",
    "TokenEncoding",
    "ModelBackend",
    "FrozenEmbedder",
    "overview_text",
    "document_text",
    "query_text",
    "mean_pool_unit_l2",
]


class TokenBudgetExceededError(ContractValidationError):
    """A text's token count, including specials and the prefix, exceeds MAX_MODEL_TOKENS.

    Appendix A: no silent truncation; the caller marks the field unavailable.
    """


class TokenEncoding(NamedTuple):
    """One prefixed text's per-token hidden states and attention mask.

    ``hidden_states[i]`` is the backend's final-layer vector for token i in
    the pinned representation dimension; ``attention_mask`` marks real tokens
    (1) against padding (0). ``token_count`` is the unpadded, untruncated
    token count including specials and the prefix.
    """

    hidden_states: tuple[tuple[float, ...], ...]
    attention_mask: tuple[int, ...]
    token_count: int


class ModelBackend(Protocol):
    """The loaded pinned model: prefixed text in, per-token states out.

    A backend owns tokenization and the forward pass only; FrozenEmbedder
    owns prefixing, the token budget and pooling, so a real Transformers
    backend and a deterministic test fixture share exactly the pooling math
    under test.
    """

    def encode(self, texts: Sequence[str]) -> Sequence[TokenEncoding]:
        """Return one TokenEncoding per text, in the same order."""


def overview_text(title: str, abstract: str) -> str:
    """Build the original-version overview input (Appendix B: Learning protocol).

    Title, one newline, then abstract, UTF-8 NFC with line breaks normalized
    to LF. An empty title or abstract has no valid overview text; the caller
    marks the field unavailable rather than embedding a partial input.
    """

    if not isinstance(title, str) or not title.strip():
        raise ContractValidationError("overview text requires a nonempty title")
    if not isinstance(abstract, str) or not abstract.strip():
        raise ContractValidationError("overview text requires a nonempty abstract")
    return normalize_text(f"{title}\n{abstract}")


def document_text(text: str) -> str:
    """Prefix already-normalized overview or passage text for indexing."""

    if not isinstance(text, str) or not text:
        raise ContractValidationError("document text must be nonempty")
    return f"{DOCUMENT_PREFIX}{text}"


def query_text(text: str) -> str:
    """Prefix query text for search (Appendix A, Appendix C)."""

    if not isinstance(text, str) or not text.strip():
        raise ContractValidationError("query text must be nonempty")
    return f"{QUERY_PREFIX}{text}"


def mean_pool_unit_l2(encoding: TokenEncoding, dimension: int) -> tuple[float, ...]:
    """Attention-masked mean pooling over all tokens, then unit-L2 normalization.

    Padding tokens (attention_mask == 0) never enter the pool, so padding a
    batch to its longest member cannot change a shorter member's vector.
    Accumulates in float64 and casts the normalized result to float32,
    matching the codebase's other pooled-vector arithmetic.
    """

    if len(encoding.hidden_states) != len(encoding.attention_mask):
        raise ContractValidationError(
            "hidden states and attention mask must be the same length",
        )
    included = [
        vector
        for vector, mask in zip(
            encoding.hidden_states, encoding.attention_mask, strict=True
        )
        if mask
    ]
    if not included:
        raise ContractValidationError("pooling requires at least one unmasked token")
    for vector in included:
        if len(vector) != dimension:
            raise ContractValidationError(
                "hidden state dimension differs from the representation",
            )
    pooled64 = tuple(
        math.fsum(vector[coordinate] for vector in included) / len(included)
        for coordinate in range(dimension)
    )
    norm = math.sqrt(math.fsum(value * value for value in pooled64))
    if not math.isfinite(norm) or norm == 0.0:
        raise ContractValidationError("pooled vector must be finite and nonzero")
    return _float32(value / norm for value in pooled64)


def _float32(values: Iterable[float]) -> tuple[float, ...]:
    return tuple(struct.unpack("<f", struct.pack("<f", value))[0] for value in values)


class FrozenEmbedder:
    """The frozen pinned embedder: one manifest identity plus a loaded backend.

    ModelService holds the single instance (PL-08); this class only computes
    vectors from prefixed text under a backend it does not itself load.
    """

    def __init__(self, manifest: RepresentationManifest, backend: ModelBackend) -> None:
        self._manifest = manifest
        self._backend = backend

    @property
    def manifest(self) -> RepresentationManifest:
        return self._manifest

    def embed_documents(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """Embed already-normalized document texts (overview or passage)."""

        return self._embed([document_text(text) for text in texts])

    def embed_queries(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """Embed search queries under the query prefix."""

        return self._embed([query_text(text) for text in texts])

    def _embed(self, prefixed_texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        if not prefixed_texts:
            return ()
        pool = getattr(self._backend, "pool", None)
        if pool is not None:
            # A backend that pools on its own tensors returns the same
            # vectors as encode() followed by mean_pool_unit_l2 without
            # materializing every hidden state as a Python float.
            pooled = pool(prefixed_texts)
            if len(pooled) != len(prefixed_texts):
                raise ContractValidationError(
                    "backend returned a different number of vectors than requested",
                )
            for vector in pooled:
                if len(vector) != self._manifest.dimension:
                    raise ContractValidationError(
                        "pooled vector dimension differs from the representation",
                    )
            return tuple(tuple(float(value) for value in vector) for vector in pooled)
        encodings = self._backend.encode(prefixed_texts)
        if len(encodings) != len(prefixed_texts):
            raise ContractValidationError(
                "backend returned a different number of encodings than requested",
            )
        vectors: list[tuple[float, ...]] = []
        for encoding in encodings:
            if encoding.token_count > MAX_MODEL_TOKENS:
                raise TokenBudgetExceededError(
                    "text exceeds the pinned model token limit",
                )
            vectors.append(mean_pool_unit_l2(encoding, self._manifest.dimension))
        return tuple(vectors)
