"""The tool service embeds queries through the one shared model service (PL-08).

#287: ``POST /v1/embeddings/query`` serves the frozen embedder's query
vector over mutually authenticated TLS, under the ``search_query: ``
prefix, stamped with the producing identity; a request naming another
representation and a caller whose certificate is not admitted are refused.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.models.client import (
    ModelServiceClient,
    ModelServiceError,
    ModelTransportError,
)
from research_agent.models.embedding import FrozenEmbedder
from research_agent.models.manifest import QUERY_PREFIX, RepresentationManifest
from research_agent.models.service import ModelService, create_model_server

sys.path.insert(0, str(Path(__file__).parents[1] / "storage"))
from test_http import _tls_material  # noqa: E402


@contextmanager
def _served(service: ModelService, tmp_path: Path) -> Iterator[tuple[str, int]]:
    server_context, _, fingerprint, _, _, _ = _tls_material(tmp_path)
    httpd = create_model_server(
        ("127.0.0.1", 0),
        service,
        tls_context=server_context,
        client_fingerprints=frozenset({fingerprint}),
    )
    thread = threading.Thread(target=httpd.serve_forever)
    thread.start()
    try:
        host, port = httpd.server_address[:2]
        yield str(host), int(port)
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def _client(tmp_path: Path, address: tuple[str, int], cert: str) -> ModelServiceClient:
    return ModelServiceClient(
        connect_host=address[0],
        port=address[1],
        server_hostname="localhost",
        ca_file=tmp_path / "ca.pem",
        client_cert_file=tmp_path / f"{cert}.pem",
        client_key_file=tmp_path / f"{cert}.key",
        timeout_seconds=5,
    )


def test_a_query_is_embedded_by_the_shared_service_with_its_identity(
    model_service_factory: Callable[..., ModelService],
    fake_backend_factory: Callable[..., object],
    manifest: RepresentationManifest,
    tmp_path: Path,
) -> None:
    backend = fake_backend_factory()
    service = model_service_factory(backend=backend)
    local = FrozenEmbedder(manifest, fake_backend_factory()).embed_queries(
        ["sparse probes"]
    )[0]
    with _served(service, tmp_path) as address:
        result = _client(tmp_path, address, "client").embed_query(
            "sparse probes", representation_hash=manifest.representation_hash
        )
    assert result.vector == pytest.approx(local)
    assert result.representation_hash == manifest.representation_hash
    assert (result.model_id, result.revision, result.checkpoint_date) == (
        manifest.model_id,
        manifest.revision,
        manifest.checkpoint_date,
    )
    assert backend.received_texts == [f"{QUERY_PREFIX}sparse probes"]  # type: ignore[attr-defined]


def test_another_representation_and_an_unadmitted_caller_are_refused(
    model_service_factory: Callable[..., ModelService],
    fake_backend_factory: Callable[..., object],
    tmp_path: Path,
) -> None:
    backend = fake_backend_factory()
    service = model_service_factory(backend=backend)
    with _served(service, tmp_path) as address:
        with pytest.raises(ModelServiceError) as mismatch:
            _client(tmp_path, address, "client").embed_query(
                "sparse probes", representation_hash="0" * 64
            )
        with pytest.raises(ModelServiceError) as unadmitted:
            _client(tmp_path, address, "wrong").embed_query(
                "sparse probes",
                representation_hash=service.manifest_representation_hash,
            )
        with pytest.raises(ContractValidationError):
            _client(tmp_path, address, "client").embed_query(
                "x" * 2049, representation_hash=service.manifest_representation_hash
            )
    assert (mismatch.value.status_code, mismatch.value.code) == (
        409,
        "representation_mismatch",
    )
    assert (unadmitted.value.status_code, unadmitted.value.code) == (
        401,
        "unauthenticated",
    )
    # Nothing was embedded for a refused request.
    assert backend.received_texts == []  # type: ignore[attr-defined]


def test_the_client_refuses_a_model_service_it_cannot_reach(
    manifest: RepresentationManifest, tmp_path: Path
) -> None:
    _tls_material(tmp_path)
    with pytest.raises(ModelTransportError, match="not retried"):
        _client(tmp_path, ("127.0.0.1", 1), "client").embed_query(
            "sparse probes", representation_hash=manifest.representation_hash
        )
