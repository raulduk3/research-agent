"""Pinned embedding inference: prefixes, pooling and the 1536-feature output.

TDD-4.1.67 (MD-06): default CI validates manifest/text contracts without
downloading weights. Padding invariance, dimension, finite norm and the
combined 1536-feature output are all pure math, so they are verified here
with a deterministic fake backend; a small real-model qualification fixture,
gated on locally cached weights, verifies the actual pinned checkpoint.
"""

from __future__ import annotations

import math
import os
from collections.abc import Callable

import pytest

from research_agent.contracts.learning import (
    EMBEDDING_DIMENSION,
    EMBEDDING_FEATURE_DIMENSION,
)
from research_agent.contracts.primitives import ContractValidationError
from research_agent.learning.features import PassageEmbedding, assemble_features
from research_agent.models.embedding import (
    FrozenEmbedder,
    ModelBackend,
    TokenBudgetExceededError,
    TokenEncoding,
    document_text,
    mean_pool_unit_l2,
    overview_text,
    query_text,
)
from research_agent.models.manifest import (
    DOCUMENT_PREFIX,
    MAX_MODEL_TOKENS,
    QUERY_PREFIX,
    RepresentationManifest,
)


def test_overview_text_joins_title_and_abstract_with_one_newline() -> None:
    assert overview_text("A Title", "An abstract.") == "A Title\nAn abstract."


def test_overview_text_normalizes_nfc_and_line_breaks() -> None:
    text = overview_text("Café title\r\nsecond line", "abstract\rbody")
    assert text == "Café title\nsecond line\nabstract\nbody"


@pytest.mark.parametrize(
    "title,abstract", [("", "abstract"), ("title", ""), ("  ", "x")]
)
def test_overview_text_rejects_an_empty_title_or_abstract(
    title: str, abstract: str
) -> None:
    with pytest.raises(ContractValidationError):
        overview_text(title, abstract)


def test_document_text_uses_the_exact_pinned_prefix() -> None:
    assert document_text("some passage text") == f"{DOCUMENT_PREFIX}some passage text"


def test_query_text_uses_the_exact_pinned_prefix() -> None:
    assert query_text("a search query") == f"{QUERY_PREFIX}a search query"


def test_query_text_rejects_an_empty_query() -> None:
    with pytest.raises(ContractValidationError):
        query_text("   ")


def test_mean_pool_is_attention_masked_and_unit_l2() -> None:
    encoding = TokenEncoding(
        hidden_states=((1.0, 0.0), (0.0, 1.0), (100.0, 100.0)),
        attention_mask=(1, 1, 0),
        token_count=3,
    )
    pooled = mean_pool_unit_l2(encoding, 2)
    norm = math.sqrt(sum(value * value for value in pooled))
    assert math.isclose(norm, 1.0, rel_tol=1e-6)
    assert pooled == pytest.approx((1 / math.sqrt(2), 1 / math.sqrt(2)))


def test_mean_pool_is_padding_invariant() -> None:
    unpadded = TokenEncoding(
        hidden_states=((1.0, 0.0), (0.0, 1.0)),
        attention_mask=(1, 1),
        token_count=2,
    )
    padded = TokenEncoding(
        hidden_states=((1.0, 0.0), (0.0, 1.0), (999.0, -999.0), (-5.0, 5.0)),
        attention_mask=(1, 1, 0, 0),
        token_count=2,
    )
    assert mean_pool_unit_l2(unpadded, 2) == mean_pool_unit_l2(padded, 2)


def test_mean_pool_rejects_all_padding() -> None:
    encoding = TokenEncoding(
        hidden_states=((1.0, 0.0),),
        attention_mask=(0,),
        token_count=1,
    )
    with pytest.raises(ContractValidationError):
        mean_pool_unit_l2(encoding, 2)


def test_frozen_embedder_returns_pinned_dimension_finite_unit_vectors(
    manifest: RepresentationManifest,
    fake_backend_factory: Callable[..., ModelBackend],
) -> None:
    backend = fake_backend_factory()
    embedder = FrozenEmbedder(manifest, backend)
    (vector,) = embedder.embed_documents(["hello world this is text"])
    assert len(vector) == EMBEDDING_DIMENSION
    assert all(math.isfinite(value) for value in vector)
    norm = math.sqrt(sum(value * value for value in vector))
    assert math.isclose(norm, 1.0, rel_tol=1e-5)


def test_frozen_embedder_rejects_text_over_the_pinned_token_budget(
    manifest: RepresentationManifest,
    fake_backend_factory: Callable[..., ModelBackend],
) -> None:
    backend = fake_backend_factory()
    long_text = " ".join(f"tok{i}" for i in range(MAX_MODEL_TOKENS + 1))
    embedder = FrozenEmbedder(manifest, backend)
    with pytest.raises(TokenBudgetExceededError):
        embedder.embed_documents([long_text])


def test_overview_and_passage_vectors_assemble_to_the_1536_feature_output(
    manifest: RepresentationManifest,
    fake_backend_factory: Callable[..., ModelBackend],
) -> None:
    embedder = FrozenEmbedder(manifest, fake_backend_factory())
    (overview_vector,) = embedder.embed_documents(
        [overview_text("Title", "Abstract text")]
    )
    passage_vectors = embedder.embed_documents(
        ["first passage body", "second passage body"]
    )

    passages = tuple(
        PassageEmbedding(
            0, index * 320, index * 320 + 384, manifest.representation_hash, vector
        )
        for index, vector in enumerate(passage_vectors)
    )
    assembled = assemble_features(
        overview_vector,
        passages,
        representation_hash=manifest.representation_hash,
        representation_dimension=EMBEDDING_DIMENSION,
        overview_representation_hash=manifest.representation_hash,
        source_version_id="123e4567-e89b-42d3-a456-426614174000",
        original_version_id="123e4567-e89b-42d3-a456-426614174000",
        extraction_coverage="complete",
    )
    assert len(assembled.combined) == EMBEDDING_FEATURE_DIMENSION


@pytest.fixture
def real_frozen_embedder() -> FrozenEmbedder:
    cache_dir = os.environ.get("RESEARCH_AGENT_MODEL_CACHE")
    if not cache_dir:
        pytest.skip(
            "Set RESEARCH_AGENT_MODEL_CACHE to a local Hugging Face cache to run"
            " the pinned embedding-model qualification fixture",
        )
    from pathlib import Path

    from research_agent.models.backend import load_frozen_embedder

    return load_frozen_embedder(Path(cache_dir))


def test_pinned_checkpoint_qualification_fixture(
    real_frozen_embedder: FrozenEmbedder,
) -> None:
    """Verify the actual pinned checkpoint: real file hashes, dimension, norm.

    Skipped by default; CI makes no model call (Appendix A). Requires the
    pinned checkpoint already downloaded to RESEARCH_AGENT_MODEL_CACHE.
    """

    manifest = real_frozen_embedder.manifest
    assert manifest.dimension == EMBEDDING_DIMENSION
    padded, unpadded = real_frozen_embedder.embed_documents(
        ["a short passage", "a short passage with more trailing words after it"]
    )
    for vector in (padded, unpadded):
        assert len(vector) == EMBEDDING_DIMENSION
        norm = math.sqrt(sum(value * value for value in vector))
        assert math.isclose(norm, 1.0, rel_tol=1e-4)
        assert all(math.isfinite(value) for value in vector)
