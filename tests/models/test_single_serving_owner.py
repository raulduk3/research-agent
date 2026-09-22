"""One shared model-serving owner; every response carries its identity (PL-08).

TDD-2.1.38: reader and tools call typed embedding endpoints and get back the
producing identity with the output; a second copy of the small models is
never loaded while one is already serving.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from research_agent.contracts.learning import EMBEDDING_DIMENSION
from research_agent.contracts.passages import ResourceDemand
from research_agent.models.embedding import FrozenEmbedder, ModelBackend
from research_agent.models.manifest import RepresentationManifest
from research_agent.models.service import (
    BatchDemand,
    ModelService,
    ModelServiceAlreadyRunningError,
)


def test_second_instance_is_refused_while_one_is_active(
    model_service_factory: Callable[..., ModelService],
    manifest: RepresentationManifest,
    fake_backend_factory: Callable[..., ModelBackend],
) -> None:
    model_service_factory()
    with pytest.raises(ModelServiceAlreadyRunningError):
        ModelService(FrozenEmbedder(manifest, fake_backend_factory()))


def test_closing_frees_the_slot_for_a_new_instance(
    manifest: RepresentationManifest,
    fake_backend_factory: Callable[..., ModelBackend],
) -> None:
    first = ModelService(FrozenEmbedder(manifest, fake_backend_factory()))
    first.close()
    second = ModelService(FrozenEmbedder(manifest, fake_backend_factory()))
    second.close()


def test_a_closed_service_refuses_further_requests(
    model_service_factory: Callable[..., ModelService],
) -> None:
    service = model_service_factory()
    service.close()
    with pytest.raises(ModelServiceAlreadyRunningError):
        service.embed_overview("Title", "Abstract text")


def test_embed_overview_returns_the_producing_identity(
    model_service_factory: Callable[..., ModelService],
    manifest: RepresentationManifest,
) -> None:
    service = model_service_factory()
    result = service.embed_overview("Title", "Abstract text")
    assert result.model_id == manifest.model_id
    assert result.revision == manifest.revision
    assert result.checkpoint_date == manifest.checkpoint_date
    assert result.representation_hash == manifest.representation_hash
    assert len(result.vector) == EMBEDDING_DIMENSION


def test_embed_passages_stamps_every_vector_with_the_same_identity(
    model_service_factory: Callable[..., ModelService],
    manifest: RepresentationManifest,
) -> None:
    service = model_service_factory()
    results = service.embed_passages(["first passage body", "second passage body"])
    assert len(results) == 2
    for result in results:
        assert result.representation_hash == manifest.representation_hash
        assert len(result.vector) == EMBEDDING_DIMENSION


def test_measure_batch_records_counts_and_nonnegative_demand(
    model_service_factory: Callable[..., ModelService],
) -> None:
    service = model_service_factory()
    with service.measure_batch() as recorder:
        service.embed_overview("Title", "Abstract text")
        recorder.record_paper()
        results = service.embed_passages(["p1", "p2"])
        recorder.record_passages(len(results))
    demand = recorder.demand
    assert demand is not None
    assert demand.paper_count == 1
    assert demand.passage_count == 2
    assert demand.cpu_seconds >= 0
    assert demand.resource.wall_seconds >= 0
    assert demand.resource.peak_memory_bytes >= 0


def test_batch_demand_rejects_negative_counts() -> None:
    with pytest.raises(ValueError):
        BatchDemand(-1, 0, ResourceDemand(0.0, 0), 0.0)


def test_batch_demand_rejects_negative_cpu_seconds() -> None:
    with pytest.raises(ValueError):
        BatchDemand(0, 0, ResourceDemand(0.0, 0), -0.5)
