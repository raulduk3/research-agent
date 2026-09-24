"""``serve-models``: the shared model service's mTLS listener (SDD PL-08, #315).

``platform/model_service.py#serve_models`` loads the pinned checkpoint into
the single ModelService; this launcher puts ``models/service.py`` in front of
it on the configured address, admitting only the declared client
certificate fingerprints.

A host-native configuration (``models.native.json``, #350) names a
``secrets_root`` under which the host holds the ``/run/secrets/`` mounts a
container would have.
"""

from __future__ import annotations

import json
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


def secrets_root(config_path: Path) -> Path | None:
    """The configuration's host secrets root, or None for container mounts."""

    try:
        value = json.loads(config_path.read_text()).get("secrets_root")
    except (OSError, json.JSONDecodeError, AttributeError) as error:
        raise LaunchRefused("launch configuration is unreadable") from error
    if value is None:
        return None
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise LaunchRefused("secrets_root must be an absolute path")
    return Path(value)


def serve_models(config_path: Path) -> None:
    """Check the configuration, load the pinned checkpoint once and serve it."""

    config = load_launch_config(
        config_path, "models", secrets_root=secrets_root(config_path)
    )
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
