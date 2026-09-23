"""Shared fixtures for the shared model-serving owner tests (MD-06, PL-08)."""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Callable, Sequence
from hashlib import sha256

import pytest

from collections.abc import Iterator

from research_agent.contracts.learning import (
    EMBEDDING_DIMENSION,
    EMBEDDING_FEATURE_DIMENSION,
    HEAD_INPUT_DIMENSION,
    METADATA_DIMENSION,
    TargetDefinition,
)
from research_agent.contracts import ProducerVersion, RecordMeta
from research_agent.learning.features import (
    CardMetadata,
    Standardization,
    assemble_metadata_block,
    fit_standardization,
)
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
from research_agent.outcomes.targets import definitions as target_definitions

TOKENIZER_HASH = "a" * 64
WEIGHT_HASH = "b" * 64
BUNDLE_META = RecordMeta(
    1,
    (),
    ProducerVersion(sha256(b"test-producer").hexdigest(), "a" * 40, 1),
    sha256(b"test-config").hexdigest(),
    "2026-01-01T00:00:00.000000Z",
)


@pytest.fixture
def producer_version() -> ProducerVersion:
    return BUNDLE_META.producer_version


@pytest.fixture
def bundle_target_definitions() -> tuple[
    TargetDefinition, TargetDefinition, TargetDefinition
]:
    found = target_definitions(BUNDLE_META)
    return (found[0], found[1], found[2])


def _metadata_row() -> tuple[float, ...]:
    return assemble_metadata_block(
        CardMetadata(
            author_count=3,
            categories=("cs.AI", "cs.LG"),
            abstract_tokens=120,
            title_tokens=10,
            first_available_weekday=2,
            code_link=True,
            version_count=1,
        )
    )


@pytest.fixture
def standardization() -> Standardization:
    return fit_standardization([_metadata_row(), _metadata_row()])


@pytest.fixture
def embedding_block() -> tuple[float, ...]:
    return tuple(0.001 * (index % 7) for index in range(EMBEDDING_FEATURE_DIMENSION))


@pytest.fixture
def metadata_block() -> tuple[float, ...]:
    row = _metadata_row()
    assert len(row) == METADATA_DIMENSION
    return row


@pytest.fixture
def head_weights() -> tuple[float, ...]:
    return tuple(0.0005 * ((index % 5) - 2) for index in range(HEAD_INPUT_DIMENSION))


def _build_manifest(*, qualified: bool = False) -> RepresentationManifest:
    return RepresentationManifest(
        model_id=MODEL_ID,
        revision=REVISION,
        checkpoint_date=ADOPTED_CHECKPOINT_DATE,
        dtype=DTYPE,
        device="mps",
        deterministic_algorithms=True,
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
