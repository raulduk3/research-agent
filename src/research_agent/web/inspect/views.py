"""Page-ready projections of storage's inspector reads, exactly as returned.

Nothing here recomputes a stored field or invents one storage does not yet
hold: a genome and its admission come from the population store, a verdict
from the latest stored resolution, and no view here carries a Brier
contribution because no scorer output is stored yet.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote
from uuid import UUID

from research_agent.storage.client import StorageClient, StorageClientError
from research_agent.web.api import listing


@dataclass(frozen=True, slots=True)
class RunView:
    run: dict[str, Any]
    submissions: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class AgentView:
    configuration_id: str
    genome: dict[str, Any] | None
    runs: tuple[dict[str, Any], ...]
    next_cursor: str | None
    forecasts: tuple[dict[str, Any], ...]
    forecasts_next_cursor: str | None


@dataclass(frozen=True, slots=True)
class PopulationView:
    configurations: tuple[dict[str, Any], ...]
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


def read_population_view(
    storage: StorageClient, *, cursor: tuple[str, str] | None
) -> PopulationView:
    """Every admitted genome, run or not, newest admission first."""

    listing = storage.list_configurations(cursor=cursor)
    return PopulationView(
        tuple(listing.data["configurations"]), listing.data["next_cursor"]
    )


def read_agent_view(
    storage: StorageClient,
    configuration_id: UUID,
    *,
    cursor: tuple[str, str] | None,
    forecasts_cursor: tuple[str, str] | None = None,
) -> AgentView:
    """One configuration's genome, runs newest first, and sealed claims with verdicts.

    ``genome`` is ``None`` when the population store holds no record for
    this configuration; its runs and claims are still shown as stored.
    """

    try:
        genome: dict[str, Any] | None = dict(
            storage.read_configuration(configuration_id).data
        )
    except StorageClientError as error:
        if error.code != "not_found":
            raise
        genome = None
    listing = storage.list_runs_by_configuration(
        configuration_id=configuration_id, cursor=cursor
    )
    forecasts = storage.list_forecasts_by_configuration(
        configuration_id=configuration_id, cursor=forecasts_cursor
    )
    return AgentView(
        str(configuration_id),
        genome,
        tuple(listing.data["runs"]),
        listing.data["next_cursor"],
        tuple(forecasts.data["forecasts"]),
        forecasts.data["next_cursor"],
    )


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


def run_data(view: RunView) -> dict[str, Any]:
    """A run view as its ``/api/v1`` twin serves it: lists as ``{items, next_cursor}``."""
    return {"run": view.run, "submissions": listing(view.submissions)}


def population_data(view: PopulationView) -> dict[str, Any]:
    return {"configurations": listing(view.configurations, view.next_cursor)}


def agent_data(view: AgentView) -> dict[str, Any]:
    return {
        "configuration_id": view.configuration_id,
        "genome": view.genome,
        "runs": listing(view.runs, view.next_cursor),
        "forecasts": listing(view.forecasts, view.forecasts_next_cursor),
    }


def manifest_data(view: ManifestView) -> dict[str, Any]:
    return {"manifest": view.manifest}


def cursor_query(value: str | None) -> str | None:
    return quote(value, safe="") if value is not None else None


def parse_cursor(value: str | None) -> tuple[str, str] | None:
    if value is None:
        return None
    created_at, separator, run_id = value.partition(",")
    if not separator:
        raise ValueError("cursor is not an admitted value")
    return created_at, run_id


def read_rated_entry_ids(storage: StorageClient, rater_id: UUID) -> frozenset[str]:
    """The digest entry ids one rater has rated; the rating values stay private."""

    rated = storage.list_rated_entries(rater_id)
    return frozenset(entry["entry_id"] for entry in rated.data["entries"])


def guard_digest_for_rater(
    digest: Mapping[str, Any], rated: frozenset[str]
) -> dict[str, Any]:
    """A stored digest as its rater may see it: provenance only past a rating.

    An entry the rater has not rated keeps its id, paper and position and
    nothing an agent or the digest builder recorded about it: origin,
    service source, control provenance, nominations (SR-21, SR-22, SR-25).
    A rated entry is shown in full. Which per-agent figures a rated entry
    would additionally carry is not yet defined (#255), so none is added.
    """

    entries = [
        {**entry, "rated": True}
        if entry["entry_id"] in rated
        else {
            "entry_id": entry["entry_id"],
            "paper_hash": entry["paper_hash"],
            "display_position": entry["display_position"],
            "rated": False,
        }
        for entry in digest["entries"]
    ]
    return {**digest, "entries": entries}
