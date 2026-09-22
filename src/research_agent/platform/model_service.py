"""Configuration-backed launcher for the shared model-serving owner (SDD PL-08).

Loads the pinned embedding checkpoint and starts the single ModelService this
host runs; a second launch in the same process is refused rather than
loading a second copy of the small models (SDD PL-08, PL-09).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research_agent.models.backend import load_frozen_embedder
from research_agent.models.service import ModelService


def serve_models(config_path: Path) -> ModelService:
    """Start the shared model service from a reference to its runtime config.

    Downloads and loads the pinned checkpoint through the configured cache
    directory. This is local engineering-mode inference, not a paid or
    provisioned call; the returned service's manifest stays unqualified until
    the retrieval qualification protocol records evidence (Appendix A).
    """

    config = _read_config(config_path)
    cache_dir = config.get("model_cache_dir")
    if cache_dir is not None and not isinstance(cache_dir, str):
        raise ValueError("model_cache_dir must be a string path")
    embedder = load_frozen_embedder(Path(cache_dir) if cache_dir else None)
    return ModelService(embedder)


def _read_config(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("model service configuration is unreadable") from error
    if not isinstance(value, dict):
        raise ValueError("model service configuration must be an object")
    return value
