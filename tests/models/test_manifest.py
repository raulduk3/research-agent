"""The pinned representation manifest rejects drift (MD-06, Appendix A)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from research_agent.contracts.learning import EMBEDDING_DIMENSION
from research_agent.contracts.primitives import ContractValidationError
from research_agent.models.manifest import (
    DOCUMENT_PREFIX,
    MAX_MODEL_TOKENS,
    MODEL_ID,
    QUERY_PREFIX,
    REVISION,
    RepresentationManifest,
)


def test_pinned_manifest_constructs(manifest: RepresentationManifest) -> None:
    assert manifest.model_id == MODEL_ID
    assert manifest.revision == REVISION
    assert manifest.dimension == EMBEDDING_DIMENSION
    assert manifest.document_prefix == DOCUMENT_PREFIX
    assert manifest.query_prefix == QUERY_PREFIX
    assert manifest.max_model_tokens == MAX_MODEL_TOKENS
    assert manifest.device in {"cuda", "mps", "cpu"}
    assert manifest.deterministic_algorithms is True
    assert manifest.qualified is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"dimension": EMBEDDING_DIMENSION + 1},
        {"revision": "0" * 40},
        {"model_id": "some-other/model"},
        {"dtype": "float16"},
        {"pooling": "last_token"},
        {"document_prefix": "passage: "},
        {"query_prefix": "query: "},
        {"max_model_tokens": 4096},
        {"tokenizer_hash": "not-a-hash"},
        {"weight_hash": "not-a-hash"},
        {"device": "tpu"},
        {"deterministic_algorithms": False},
    ],
)
def test_manifest_rejects_drift_from_the_pinned_identity(
    manifest_factory: Callable[..., RepresentationManifest],
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ContractValidationError):
        manifest_factory(**overrides)


def test_representation_hash_changes_with_device(
    manifest_factory: Callable[..., RepresentationManifest],
) -> None:
    cuda = manifest_factory(device="cuda")
    mps = manifest_factory(device="mps")
    assert cuda.representation_hash != mps.representation_hash


def test_representation_hash_is_stable_content_identity(
    manifest_factory: Callable[..., RepresentationManifest],
) -> None:
    first = manifest_factory()
    second = manifest_factory()
    assert first.representation_hash == second.representation_hash
    assert len(first.representation_hash) == 64


def test_representation_hash_excludes_qualification_state(
    manifest_factory: Callable[..., RepresentationManifest],
) -> None:
    unqualified = manifest_factory(qualified=False)
    qualified = manifest_factory(qualified=True)
    assert unqualified.representation_hash == qualified.representation_hash


def test_representation_hash_changes_with_file_hashes(
    manifest_factory: Callable[..., RepresentationManifest],
) -> None:
    first = manifest_factory(tokenizer_hash="a" * 64)
    second = manifest_factory(tokenizer_hash="c" * 64)
    assert first.representation_hash != second.representation_hash
