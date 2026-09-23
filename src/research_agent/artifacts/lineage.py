"""Correction dependency graph: invalidate without rewriting history (SDD FT-25).

A correction never edits or deletes a superseded artifact; it is appended
as its own immutable record, and everything that was built from the
superseded content is found by walking the existing content-addressed
dependency graph (:mod:`research_agent.storage.artifacts`) forward from it.
Nothing here rewrites a dependent manifest either: a critical correction
that reaches the currently active prediction-head bundle withdraws only the
affected target, through the same atomic pointer swap every other
promotion uses (:func:`research_agent.models.registry.activate_bundle`),
leaving every already-sealed prediction and every prior byte untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from psycopg import Connection

from research_agent.contracts import (
    ProducerVersion,
    canonical_json,
    sha256_hex,
    validate_non_empty_string,
    validate_sha256,
    validate_utc_instant,
)
from research_agent.models.registry import (
    RETENTION_POLICY_HASH,
    BundleManifest,
    BundleTargetEntry,
    ServingHandle,
    activate_bundle,
)
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.database import Database

CORRECTION_KINDS = frozenset({"source", "label", "representation"})
_MAXIMUM_CORRECTION_BYTES = 64 * 1024


class LineageError(ValueError):
    """A correction record or its application is not admissible."""


@dataclass(frozen=True, slots=True)
class Correction:
    """One accepted correction: what it supersedes, and why (SDD FT-25)."""

    correction_kind: str
    superseded_hash: str
    reason: str
    accepted_at: str

    def __post_init__(self) -> None:
        if self.correction_kind not in CORRECTION_KINDS:
            raise LineageError("correction kind is not admitted")
        validate_sha256(self.superseded_hash)
        validate_non_empty_string(self.reason)
        validate_utc_instant(self.accepted_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "correction_kind": self.correction_kind,
            "superseded_hash": self.superseded_hash,
            "reason": self.reason,
            "accepted_at": self.accepted_at,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class LineageImpact:
    """What one correction reaches, and what it withdrew."""

    correction_hash: str
    dependent_hashes: tuple[str, ...]
    withdrawn_bundle_hash: str | None


def dependents_of(database: Database, superseded_hash: str) -> tuple[str, ...]:
    """Every artifact transitively produced from ``superseded_hash``.

    Walks both dependency edges the storage layer already records --
    ``artifact_edges`` (one committed artifact wrapping another) and
    ``artifact_production_edges`` (a manifest's declared production
    inputs) -- to a fixed point. Read-only: enumeration never mutates or
    deletes a dependent (SDD FT-25: "without rewriting history").
    """

    validate_sha256(superseded_hash)

    def query(connection: Connection[tuple[object, ...]]) -> list[str]:
        rows = connection.execute(
            """
            WITH RECURSIVE edges(output_hash, input_hash) AS (
                SELECT output_hash, input_hash FROM artifact_edges
                UNION ALL
                SELECT manifest_hash, input_hash FROM artifact_production_edges
            ),
            reached(hash) AS (
                SELECT decode(%s, 'hex')
                UNION
                SELECT e.output_hash FROM edges e
                JOIN reached r ON e.input_hash = r.hash
            )
            SELECT DISTINCT encode(hash, 'hex') FROM reached
            WHERE encode(hash, 'hex') != %s
            """,
            (superseded_hash, superseded_hash),
        ).fetchall()
        return [str(row[0]) for row in rows]

    return tuple(sorted(database.transaction(query)))


def apply_correction(
    database: Database,
    artifacts: ArtifactRepository,
    correction: Correction,
    *,
    critical: bool,
    current_handle: ServingHandle | None,
    producer_version: ProducerVersion,
    command_id: UUID | None = None,
) -> LineageImpact:
    """Append one correction and, if critical, withdraw the bundle it reaches.

    ``critical`` corrections that reach a target currently qualified in
    ``current_handle`` withdraw exactly that target -- marking it
    unavailable with reason ``"corrected_dependency"`` -- while every other
    target's recorded membership carries over unchanged (SDD PL-14: "its
    recorded membership is authoritative"). A non-critical correction, or
    one that reaches nothing currently active, is recorded without
    touching serving at all.
    """

    command_id = command_id or uuid4()
    payload = correction.to_canonical_json()
    digest = sha256_hex(payload)
    artifacts.publish(
        [payload],
        expected_hash=digest,
        byte_length=len(payload),
        maximum_length=_MAXIMUM_CORRECTION_BYTES,
        media_type="application/json",
        kind="manifest",
        input_hashes=(correction.superseded_hash,),
        producer_version=producer_version,
        config_hash=correction.superseded_hash,
        retention_policy_hash=RETENTION_POLICY_HASH,
        command_id=command_id,
    )
    dependents = dependents_of(database, correction.superseded_hash)

    withdrawn_bundle_hash: str | None = None
    if critical and current_handle is not None:
        reached = set(dependents) | {correction.superseded_hash}
        affected_targets = {
            entry.target_id
            for entry in current_handle.manifest.entries
            if entry.status == "qualified" and entry.artifact_hash in reached
        }
        if affected_targets:
            new_entries = tuple(
                BundleTargetEntry(
                    entry.target_id,
                    entry.target_definition_hash,
                    "unavailable",
                    None,
                    "corrected_dependency",
                )
                if entry.target_id in affected_targets
                else entry
                for entry in current_handle.manifest.entries
            )
            withdrawal = BundleManifest(
                current_handle.manifest.target_registry_hash,
                current_handle.manifest.representation_hash,
                new_entries,
                producer_version,
                correction.accepted_at,
            )
            result = activate_bundle(
                database, artifacts, withdrawal, command_id=command_id
            )
            withdrawn_bundle_hash = result.bundle_hash

    return LineageImpact(digest, dependents, withdrawn_bundle_hash)
