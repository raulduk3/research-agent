"""Atomic prediction-head bundle activation and the stable serving handle.

SDD PL-14: a qualified bundle is promoted by one atomic pointer change, so
every response resolves to exactly one fully verified manifest. SDD PL-13:
the shared model service keeps serving the last accepted bundle until a new
one is promoted; nothing a fitting job writes changes what is served before
that one committed swap.

The active bundle is not a mutable row: it is the most recent
``bundle_activated`` ledger record. Publication is content-addressed and
therefore idempotent (:mod:`research_agent.storage.artifacts`); the swap
itself is the single serialized append onto the ledger's hash chain
(:mod:`research_agent.storage.ledger`), which already holds one lock across
concurrent writers. A crash between publishing the bundle bytes and
appending that record leaves an addressable but never-activated manifest,
and the prior active pointer unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID, uuid4

from psycopg import Connection

from research_agent.contracts import (
    ProducerVersion,
    canonical_json,
    canonical_loads,
    sha256_hex,
    validate_finite,
    validate_sha256,
    validate_utc_instant,
)
from research_agent.contracts.learning import HEAD_INPUT_DIMENSION, TARGET_IDS
from research_agent.learning.features import Standardization
from research_agent.learning.heads import CalibratedHead
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.database import Database
from research_agent.storage.ledger import LedgerRepository

BUNDLE_EVENT_KIND = "bundle_activated"
_MAXIMUM_MANIFEST_BYTES = 8 * 1024 * 1024
_RETENTION_POLICY = (
    b"Prediction-head bundle manifests are retained privately for this "
    b"research and are not redistributed."
)
RETENTION_POLICY_HASH = sha256_hex(_RETENTION_POLICY)


class RegistryError(ValueError):
    """A bundle manifest, published head or activation request is invalid."""


@dataclass(frozen=True, slots=True)
class PublishedHead:
    """The exact serving-relevant coefficients of one calibrated head.

    A scoped-down projection of ``FitResult``/``CalibrationResult`` (SDD
    Appendix B): enough to reproduce the calibrated probability
    ``predict.py`` serves, plus the identity fields a caller must verify
    before trusting it, not the full fitting diagnostics kept on the
    numerical fit/calibration objects themselves.
    """

    target_id: str
    target_definition_hash: str
    weights: tuple[float, ...]
    intercept: float
    standardization: Standardization
    calibrator_a: float
    calibrator_b: float
    representation_hash: str
    target_registry_hash: str
    development_brier: float

    def __post_init__(self) -> None:
        if self.target_id not in TARGET_IDS:
            raise RegistryError("published head names an unregistered target")
        validate_sha256(self.target_definition_hash)
        if (
            not isinstance(self.weights, tuple)
            or len(self.weights) != HEAD_INPUT_DIMENSION
        ):
            raise RegistryError("published head weights must match the head width")
        for value in self.weights:
            validate_finite(value)
        validate_finite(self.intercept)
        if not isinstance(self.standardization, Standardization):
            raise RegistryError("published head requires a stored standardization")
        if validate_finite(self.calibrator_a) <= 0:
            raise RegistryError("published head calibrator scale must be positive")
        validate_finite(self.calibrator_b)
        validate_sha256(self.representation_hash)
        validate_sha256(self.target_registry_hash)
        validate_finite(self.development_brier)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "target_definition_hash": self.target_definition_hash,
            "weights": list(self.weights),
            "intercept": self.intercept,
            "standardization": self.standardization.to_dict(),
            "calibrator_a": self.calibrator_a,
            "calibrator_b": self.calibrator_b,
            "representation_hash": self.representation_hash,
            "target_registry_hash": self.target_registry_hash,
            "development_brier": self.development_brier,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "PublishedHead":
        value = canonical_loads(raw)
        fields = {
            "target_id",
            "target_definition_hash",
            "weights",
            "intercept",
            "standardization",
            "calibrator_a",
            "calibrator_b",
            "representation_hash",
            "target_registry_hash",
            "development_brier",
        }
        if not isinstance(value, dict) or set(value) != fields:
            raise RegistryError("published head fields do not match schema")
        weights = value["weights"]
        if not isinstance(weights, list):
            raise RegistryError("published head weights must be an array")
        standardization = value["standardization"]
        if not isinstance(standardization, dict):
            raise RegistryError("published head standardization must be an object")
        return cls(
            target_id=cast(str, value["target_id"]),
            target_definition_hash=cast(str, value["target_definition_hash"]),
            weights=tuple(float(cast(Any, item)) for item in weights),
            intercept=cast(float, value["intercept"]),
            standardization=Standardization.from_json(canonical_json(standardization)),
            calibrator_a=cast(float, value["calibrator_a"]),
            calibrator_b=cast(float, value["calibrator_b"]),
            representation_hash=cast(str, value["representation_hash"]),
            target_registry_hash=cast(str, value["target_registry_hash"]),
            development_brier=cast(float, value["development_brier"]),
        )

    @classmethod
    def from_calibrated(cls, item: CalibratedHead) -> "PublishedHead":
        head, calibrator = item.head, item.calibrator
        return cls(
            target_id=head.target_id,
            target_definition_hash=head.target_definition_hash,
            weights=tuple(float(value) for value in head.weights.tolist()),
            intercept=float(head.intercept),
            standardization=head.standardization,
            calibrator_a=calibrator.a,
            calibrator_b=calibrator.b,
            representation_hash=head.representation_hash,
            target_registry_hash=head.target_registry_hash,
            development_brier=head.development_brier,
        )


def publish_head(
    artifacts: ArtifactRepository,
    head: PublishedHead,
    *,
    producer_version: ProducerVersion,
) -> str:
    """Commit one calibrated head as an immutable artifact; returns its hash."""

    payload = head.to_canonical_json()
    digest = sha256_hex(payload)
    publication = artifacts.publish(
        [payload],
        expected_hash=digest,
        byte_length=len(payload),
        maximum_length=_MAXIMUM_MANIFEST_BYTES,
        media_type="application/json",
        kind="manifest",
        input_hashes=(),
        producer_version=producer_version,
        config_hash=head.target_definition_hash,
        retention_policy_hash=RETENTION_POLICY_HASH,
        command_id=uuid4(),
    )
    return publication.artifact_hash


@dataclass(frozen=True, slots=True)
class BundleTargetEntry:
    """One registry target's membership in a bundle: a qualified head or why not.

    SDD PL-14: "a bundle can explicitly retain an earlier compatible target
    artifact when that target's refit failed; its recorded membership is
    authoritative" -- a qualified entry's ``artifact_hash`` may therefore
    reference a head published by an earlier bundle.
    """

    target_id: str
    target_definition_hash: str
    status: str
    artifact_hash: str | None
    reason: str | None

    def __post_init__(self) -> None:
        if self.target_id not in TARGET_IDS:
            raise RegistryError("bundle target entry names an unregistered target")
        validate_sha256(self.target_definition_hash)
        if self.status not in {"qualified", "unavailable"}:
            raise RegistryError("bundle target entry status is invalid")
        if self.status == "qualified":
            if self.artifact_hash is None or self.reason is not None:
                raise RegistryError(
                    "a qualified target entry carries an artifact and no reason"
                )
            validate_sha256(self.artifact_hash)
        else:
            if self.artifact_hash is not None or not self.reason:
                raise RegistryError(
                    "an unavailable target entry carries a reason and no artifact"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "target_definition_hash": self.target_definition_hash,
            "status": self.status,
            "artifact_hash": self.artifact_hash,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, value: object) -> "BundleTargetEntry":
        fields = {
            "target_id",
            "target_definition_hash",
            "status",
            "artifact_hash",
            "reason",
        }
        if not isinstance(value, dict) or set(value) != fields:
            raise RegistryError("bundle target entry fields do not match schema")
        return cls(
            target_id=cast(str, value["target_id"]),
            target_definition_hash=cast(str, value["target_definition_hash"]),
            status=cast(str, value["status"]),
            artifact_hash=cast("str | None", value["artifact_hash"]),
            reason=cast("str | None", value["reason"]),
        )


@dataclass(frozen=True, slots=True)
class BundleManifest:
    """A content-addressed, immutable prediction-head bundle (SDD PL-14, FT-23).

    Membership is explicit and closed: exactly the three registry targets,
    each qualified with a published head artifact or unavailable with a
    reason. Nothing resolves a target by reading a mutable per-target
    pointer; the bundle is the sole source of membership.
    """

    target_registry_hash: str
    representation_hash: str
    entries: tuple[BundleTargetEntry, ...]
    producer_version: ProducerVersion
    created_at: str

    def __post_init__(self) -> None:
        validate_sha256(self.target_registry_hash)
        validate_sha256(self.representation_hash)
        validate_utc_instant(self.created_at)
        if tuple(entry.target_id for entry in self.entries) != TARGET_IDS:
            raise RegistryError(
                "bundle manifest must cover the registry targets in order"
            )
        for entry in self.entries:
            if (
                entry.status == "qualified"
                and entry.artifact_hash == self.target_registry_hash
            ):
                raise RegistryError("bundle target entry collides with the registry id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_registry_hash": self.target_registry_hash,
            "representation_hash": self.representation_hash,
            "entries": [entry.to_dict() for entry in self.entries],
            "producer_version": self.producer_version.to_dict(),
            "created_at": self.created_at,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "BundleManifest":
        value = canonical_loads(raw)
        fields = {
            "target_registry_hash",
            "representation_hash",
            "entries",
            "producer_version",
            "created_at",
        }
        if not isinstance(value, dict) or set(value) != fields:
            raise RegistryError("bundle manifest fields do not match schema")
        entries = value["entries"]
        producer = value["producer_version"]
        if not isinstance(entries, list) or not isinstance(producer, dict):
            raise RegistryError("bundle manifest nested fields are invalid")
        return cls(
            target_registry_hash=cast(str, value["target_registry_hash"]),
            representation_hash=cast(str, value["representation_hash"]),
            entries=tuple(BundleTargetEntry.from_dict(item) for item in entries),
            producer_version=ProducerVersion.from_json(canonical_json(producer)),
            created_at=cast(str, value["created_at"]),
        )

    def entry_for(self, target_id: str) -> BundleTargetEntry:
        for entry in self.entries:
            if entry.target_id == target_id:
                return entry
        raise RegistryError(f"'{target_id}' is not a registry target")


@dataclass(frozen=True, slots=True)
class ActivationResult:
    bundle_hash: str
    generation: int
    already_active: bool


def activate_bundle(
    database: Database,
    artifacts: ArtifactRepository,
    manifest: BundleManifest,
    *,
    command_id: UUID | None = None,
) -> ActivationResult:
    """Commit the verified bundle bytes, then atomically swap the active pointer.

    Two ordered steps, not one combined transaction: publication is itself
    transactional and content-addressed (so a retried or duplicate call
    reuses the same bytes rather than rewriting them), and only the ledger
    append that follows is the actual pointer change. A failure between the
    two leaves an addressable, never-activated manifest and the prior
    active pointer unchanged (SDD PL-14).
    """

    for entry in manifest.entries:
        if entry.status != "qualified" or entry.artifact_hash is None:
            continue
        (_length, _media), stream = artifacts.read(entry.artifact_hash)
        with stream:
            head = PublishedHead.from_json(stream.read())
        if (
            head.target_id != entry.target_id
            or head.target_definition_hash != entry.target_definition_hash
            or head.representation_hash != manifest.representation_hash
            or head.target_registry_hash != manifest.target_registry_hash
        ):
            raise RegistryError(
                "bundle target entry identity disagrees with its published head"
            )

    command_id = command_id or uuid4()
    payload = manifest.to_canonical_json()
    digest = sha256_hex(payload)
    input_hashes = tuple(
        sorted(
            {
                entry.artifact_hash
                for entry in manifest.entries
                if entry.artifact_hash is not None
            }
        )
    )
    publication = artifacts.publish(
        [payload],
        expected_hash=digest,
        byte_length=len(payload),
        maximum_length=_MAXIMUM_MANIFEST_BYTES,
        media_type="application/json",
        kind="manifest",
        input_hashes=input_hashes,
        producer_version=manifest.producer_version,
        config_hash=manifest.target_registry_hash,
        retention_policy_hash=RETENTION_POLICY_HASH,
        command_id=command_id,
    )
    ledger = LedgerRepository()

    def append(connection: Connection[tuple[object, ...]]) -> Any:
        return ledger.append(
            connection,
            record_id=uuid4(),
            event_kind=BUNDLE_EVENT_KIND,
            payload_hash=publication.artifact_hash,
            command_id=command_id,
        )

    event = database.serializable(append)
    return ActivationResult(publication.artifact_hash, event.sequence, False)


@dataclass(frozen=True, slots=True)
class ServingHandle:
    """The one bundle a request holds for its entire execution (SDD PL-13, PL-14).

    Resolved once, at request start; every prediction the caller serves
    within its lifetime reads only this manifest, never a fresher pointer
    that may have since been activated. ``generation`` is the ledger
    sequence of the activating record, a monotonically increasing witness
    of "which promotion produced this handle" with no meaning beyond order.
    """

    generation: int
    bundle_hash: str
    manifest: BundleManifest

    @classmethod
    def load(cls, database: Database, artifacts: ArtifactRepository) -> "ServingHandle":
        """Resolve the currently accepted bundle.

        Fails rather than adopting an unpromoted candidate when none has
        ever been activated (SDD PL-13: "readiness fails rather than
        adopting a candidate").
        """

        def read_head(
            connection: Connection[tuple[object, ...]],
        ) -> tuple[object, ...] | None:
            return connection.execute(
                "SELECT sequence, encode(payload_hash, 'hex') FROM ledger_records "
                "WHERE event_kind = %s ORDER BY sequence DESC LIMIT 1",
                (BUNDLE_EVENT_KIND,),
            ).fetchone()

        row = database.transaction(read_head)
        if row is None:
            raise RegistryError("no prediction-head bundle has ever been activated")
        generation, bundle_hash = cast(int, row[0]), cast(str, row[1])
        (_length, _media), stream = artifacts.read(bundle_hash)
        with stream:
            payload = stream.read()
        manifest = BundleManifest.from_json(payload)
        return cls(generation, bundle_hash, manifest)

    def qualified_head(
        self, artifacts: ArtifactRepository, target_id: str
    ) -> PublishedHead | None:
        """The published head for one target, or ``None`` when unavailable."""

        entry = self.manifest.entry_for(target_id)
        if entry.status != "qualified" or entry.artifact_hash is None:
            return None
        (_length, _media), stream = artifacts.read(entry.artifact_hash)
        with stream:
            payload = stream.read()
        return PublishedHead.from_json(payload)
