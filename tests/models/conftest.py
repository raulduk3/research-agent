"""Shared fixtures for the shared model-serving owner tests (MD-06, PL-08)."""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Callable, Sequence

import pytest

from collections.abc import Iterator

from research_agent.contracts.learning import EMBEDDING_DIMENSION
from research_agent.models.embedding import FrozenEmbedder, ModelBackend, TokenEncoding
from research_agent.models.manifest import (
    ADOPTED_CHECKPOINT_DATE,
    DOCUMENT_PREFIX,
    DTYPE,
    MAX_MODEL_TOKENS,
    MODEL_ID,
    POOLING,
    QUERY_PREFIX,
    REVISION,
    RepresentationManifest,
)
from research_agent.models.service import ModelService

TOKENIZER_HASH = "a" * 64
WEIGHT_HASH = "b" * 64


def _build_manifest(*, qualified: bool = False) -> RepresentationManifest:
    return RepresentationManifest(
        model_id=MODEL_ID,
        revision=REVISION,
        checkpoint_date=ADOPTED_CHECKPOINT_DATE,
        dtype=DTYPE,
        dimension=EMBEDDING_DIMENSION,
        pooling=POOLING,
        document_prefix=DOCUMENT_PREFIX,
        query_prefix=QUERY_PREFIX,
        max_model_tokens=MAX_MODEL_TOKENS,
        tokenizer_hash=TOKENIZER_HASH,
        weight_hash=WEIGHT_HASH,
        qualified=qualified,
    )


def _token_vector(token: str) -> tuple[float, ...]:
    """A deterministic, token-distinctive vector for pooling-math fixtures."""

    digest = hashlib.sha256(token.encode("utf-8")).digest()
    return tuple(
        float(digest[index % len(digest)]) - 128.0
        for index in range(EMBEDDING_DIMENSION)
    )


class FakeBackend:
    """A deterministic backend: one token per whitespace-delimited word.

    Records every prefixed text it receives so tests can assert prefix
    formatting, and reports the real unpadded token count so budget tests do
    not depend on padding. Optionally pads every encoding out to a fixed
    width with masked-out tokens, to test padding invariance.
    """

    def __init__(self, *, pad_to: int | None = None) -> None:
        self.received_texts: list[str] = []
        self._pad_to = pad_to

    def encode(self, texts: Sequence[str]) -> Sequence[TokenEncoding]:
        self.received_texts.extend(texts)
        tokenized = [text.split() for text in texts]
        width = self._pad_to or max((len(tokens) for tokens in tokenized), default=0)
        encodings: list[TokenEncoding] = []
        for tokens in tokenized:
            if self._pad_to is not None and len(tokens) > self._pad_to:
                raise ValueError("fixture text has more tokens than pad_to")
            hidden = [_token_vector(token) for token in tokens]
            mask = [1] * len(tokens)
            while len(hidden) < width:
                hidden.append(_token_vector("<pad>"))
                mask.append(0)
            encodings.append(TokenEncoding(tuple(hidden), tuple(mask), len(tokens)))
        return encodings


@pytest.fixture
def manifest() -> RepresentationManifest:
    return _build_manifest()


@pytest.fixture
def manifest_factory() -> Callable[..., RepresentationManifest]:
    def factory(**overrides: object) -> RepresentationManifest:
        return dataclasses.replace(_build_manifest(), **overrides)  # type: ignore[arg-type]

    return factory


@pytest.fixture
def fake_backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def fake_backend_factory() -> Callable[..., FakeBackend]:
    return FakeBackend


@pytest.fixture
def model_service_factory(
    manifest: RepresentationManifest,
    fake_backend_factory: Callable[..., FakeBackend],
) -> Iterator[Callable[..., ModelService]]:
    """Build ModelService instances backed by a fake embedder, closed on teardown."""

    services: list[ModelService] = []

    def factory(*, backend: ModelBackend | None = None) -> ModelService:
        embedder = FrozenEmbedder(manifest, backend or fake_backend_factory())
        service = ModelService(embedder)
        services.append(service)
        return service

    yield factory
    for service in services:
        service.close()
