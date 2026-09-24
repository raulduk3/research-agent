"""``GET /health`` on the shared model service (#315).

The route answers only an admitted client certificate, reports the held
embedder's identity and bundle, and is unavailable once the service closes.
"""

from __future__ import annotations

import json
import ssl
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from research_agent.models.manifest import RepresentationManifest
from research_agent.models.service import ModelService, create_model_server

from tests.storage.test_http import _tls_material, request  # noqa: E402


@contextmanager
def _served(
    service: ModelService, tmp_path: Path
) -> Iterator[tuple[tuple[str, int], ssl.SSLContext, ssl.SSLContext]]:
    server_context, client, fingerprint, wrong, _, _ = _tls_material(tmp_path)
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
        yield (str(host), int(port)), client, wrong
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def test_an_admitted_caller_reads_the_held_embedder(
    model_service_factory: Callable[..., ModelService],
    manifest: RepresentationManifest,
    tmp_path: Path,
) -> None:
    service = model_service_factory()
    with _served(service, tmp_path) as (address, client, _wrong):
        response, body = request(address, client, "GET", "/health")

    assert response.status == 200
    assert json.loads(body)["data"] == {
        "state": "ready",
        "representation_hash": manifest.representation_hash,
        "model_id": manifest.model_id,
        "revision": manifest.revision,
        "bundle_hash": None,
    }


def test_an_unadmitted_caller_and_a_closed_service_get_no_ready_answer(
    model_service_factory: Callable[..., ModelService],
    tmp_path: Path,
) -> None:
    service = model_service_factory()
    with _served(service, tmp_path) as (address, client, wrong):
        refused, _ = request(address, wrong, "GET", "/health")
        unknown, _ = request(address, client, "GET", "/v1/health")
        service.close()
        closed, body = request(address, client, "GET", "/health")

    assert refused.status == 401
    assert unknown.status == 404
    assert closed.status == 503
    assert json.loads(body)["error"]["code"] == "unavailable"
