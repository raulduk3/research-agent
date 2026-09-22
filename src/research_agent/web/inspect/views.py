"""Page-ready projections of storage's inspector reads, exactly as returned.

Nothing here recomputes a stored field or invents one storage does not yet
hold: a configuration's genome and a forecast's resolution are not storage
records yet (#162, #177), so no view here promises them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from research_agent.storage.client import StorageClient, StorageClientError


@dataclass(frozen=True, slots=True)
class RunView:
    run: dict[str, Any]
    submissions: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class AgentView:
    configuration_id: str
    runs: tuple[dict[str, Any], ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class ManifestView:
    manifest: dict[str, Any]


def read_run_view(storage: StorageClient, run_id: UUID) -> RunView | None:
    """A run as stored, with the claims it submitted as itself (submitter_id=run_id)."""

    try:
        run = storage.read_run(run_id)
    except StorageClientError as error:
        if error.code == "not_found":
            return None
        raise
    submissions = storage.list_submissions_by_submitter(submitter_id=run_id)
    return RunView(dict(run.data), tuple(submissions.data["submissions"]))


def read_agent_view(
    storage: StorageClient, configuration_id: UUID, *, cursor: tuple[str, str] | None
) -> AgentView:
    """One configuration's runs, newest first; its genome is not a view here (#177)."""

    listing = storage.list_runs_by_configuration(
        configuration_id=configuration_id, cursor=cursor
    )
    next_cursor = listing.data["next_cursor"]
    return AgentView(str(configuration_id), tuple(listing.data["runs"]), next_cursor)


def read_manifest_view(
    storage: StorageClient, manifest_hash: str
) -> ManifestView | None:
    try:
        manifest = storage.read_manifest(manifest_hash)
    except StorageClientError as error:
        if error.code == "not_found":
            return None
        raise
    return ManifestView(dict(manifest.data))
