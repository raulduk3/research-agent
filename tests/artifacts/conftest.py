"""Shared bundle fixtures for correction/lineage tests (SDD FT-25)."""

from __future__ import annotations

from hashlib import sha256

import pytest

from research_agent.contracts import ProducerVersion, RecordMeta
from research_agent.contracts.learning import HEAD_INPUT_DIMENSION, TargetDefinition
from research_agent.learning.features import (
    CardMetadata,
    Standardization,
    assemble_metadata_block,
    fit_standardization,
)
from research_agent.outcomes.targets import definitions as target_definitions

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
def head_weights() -> tuple[float, ...]:
    return tuple(0.0005 * ((index % 5) - 2) for index in range(HEAD_INPUT_DIMENSION))
