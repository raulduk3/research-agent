"""``serve-models``: the shared model service's mTLS listener (SDD PL-08, #315).

``platform/model_service.py#serve_models`` loads the pinned checkpoint into
the single ModelService; this launcher puts ``models/service.py`` in front of
it on the configured address, admitting only the declared client
certificate fingerprints.
"""

from __future__ import annotations

from http.server import ThreadingHTTPServer
from pathlib import Path

from research_agent.models.manifest import REVISION
from research_agent.models.service import ModelService, create_model_server
from research_agent.platform import model_service
from research_agent.platform.services.config import (
    LaunchConfig,
    LaunchRefused,
    load_launch_config,
)


def build_model_server(
    config: LaunchConfig, service: ModelService
) -> ThreadingHTTPServer:
    """Serve *service* on the configured listener, if it holds the pinned embedder."""

    if service.manifest.revision != config.profile.model.embedding_model_revision:
        raise LaunchRefused("the held embedder is not the profile's pinned revision")
    fingerprints = config.values.get("client_fingerprints")
    if not isinstance(fingerprints, list) or not all(
        isinstance(item, str) for item in fingerprints
    ):
        raise LaunchRefused("client_fingerprints must be a string list")
    return create_model_server(
        (config.text("host"), config.integer("port")),
        service,
        tls_context=config.server_tls(client_certificates=True),
        client_fingerprints=frozenset(fingerprints),
    )


def serve_models(config_path: Path) -> None:
    """Check the configuration, load the pinned checkpoint once and serve it."""

    config = load_launch_config(config_path, "models")
    # Refuse before the weights load, not after.
    if config.profile.model.embedding_model_revision != REVISION:
        raise LaunchRefused("the profile does not pin this build's embedder revision")
    service = model_service.serve_models(config_path)
    try:
        server = build_model_server(config, service)
        try:
            server.serve_forever()
        finally:
            server.server_close()
    finally:
        service.close()
