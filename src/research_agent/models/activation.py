"""Activate the prediction-head bundle a fit job wrote (SDD PL-14, FT-23).

``bin/fit-heads`` commits a qualification report, a bundle and a promotion
decision and activates nothing. This command is the operator's one step
from those files to the serving pointer: it reads the bundle and decision
back from the artifact store they were committed to, verifies the bundle's
vectors and id (:func:`research_agent.learning.bundles.bundle_from_json`)
and that every target it would serve was promoted, publishes one
:class:`~research_agent.models.registry.PublishedHead` per qualified target
and commits the derived manifest through
:func:`~research_agent.models.registry.activate_bundle`.

A qualified but unpromoted target is refused unless the operator names a
reason, which the published activation record keeps. Activating the bundle
that is already active reports the active pointer and writes nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import (
    ProducerVersion,
    canonical_json,
    canonical_loads,
    sha256_hex,
)
from research_agent.contracts.learning import TARGET_IDS
from research_agent.learning.bundles import ModelBundle, bundle_from_json
from research_agent.learning.release import _TARGET_META, _commit
from research_agent.models.registry import (
    RETENTION_POLICY_HASH,
    BundleManifest,
    BundleTargetEntry,
    PublishedHead,
    ServingHandle,
    activate_bundle,
    active_bundle,
    publish_head,
)
from research_agent.outcomes.targets import registry as target_registry
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.database import Database
from research_agent.storage.errors import IntegrityFailure, UnavailableInput
from research_agent.storage.migrate import migrate

_MAXIMUM_RECORD_BYTES = 1024 * 1024
_MAXIMUM_INPUT_BYTES = 64 * 1024 * 1024


class ActivationError(ValueError):
    """A fit bundle or its promotion decision cannot be activated."""


@dataclass(frozen=True, slots=True)
class ActivationRecord:
    """What one activation committed, or found already committed."""

    fit_bundle_id: str
    bundle_file_hash: str
    decision_hash: str
    manifest_hash: str
    generation: int
    already_active: bool
    served_targets: tuple[str, ...]
    unpromoted_targets: tuple[str, ...]
    unpromoted_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "fit_bundle_id": self.fit_bundle_id,
            "bundle_file_hash": self.bundle_file_hash,
            "decision_hash": self.decision_hash,
            "manifest_hash": self.manifest_hash,
            "generation": self.generation,
            "already_active": self.already_active,
            "served_targets": list(self.served_targets),
            "unpromoted_targets": list(self.unpromoted_targets),
            "unpromoted_reason": self.unpromoted_reason,
        }


def _committed(artifacts: ArtifactRepository, raw: bytes, what: str) -> str:
    """The artifact hash of ``raw``, refused unless the store holds these bytes."""

    digest = sha256_hex(raw)
    try:
        (_length, _media), stream = artifacts.read(digest)
    except (UnavailableInput, IntegrityFailure) as error:
        raise ActivationError(f"the {what} is not a committed artifact") from error
    with stream:
        if stream.read() != raw:
            raise ActivationError(f"the {what} differs from its committed bytes")
    return digest


def _promotions(raw: bytes, bundle: ModelBundle) -> tuple[bool, ...]:
    """Each registry target's promotion, from the fit job's decision document."""

    value = canonical_loads(raw)
    if not isinstance(value, dict) or set(value) != {
        "bundle_id",
        "activated",
        "decisions",
    }:
        raise ActivationError("promotion decision fields do not match schema")
    if value["bundle_id"] != bundle.bundle_id:
        raise ActivationError("promotion decision names a different bundle")
    decisions = value["decisions"]
    if not isinstance(decisions, list) or any(
        not isinstance(item, dict) or not isinstance(item.get("promoted"), bool)
        for item in decisions
    ):
        raise ActivationError("promotion decisions are invalid")
    items = cast(list[dict[str, Any]], decisions)
    if tuple(item.get("target_id") for item in items) != TARGET_IDS:
        raise ActivationError("promotion decisions must cover the registry in order")
    return tuple(bool(item["promoted"]) for item in items)


def derive_manifest(
    bundle: ModelBundle,
    promoted: tuple[bool, ...],
    *,
    unpromoted_reason: str | None,
    producer_version: ProducerVersion,
) -> tuple[BundleManifest, tuple[PublishedHead, ...], tuple[str, ...]]:
    """The serving manifest, its heads and the unpromoted targets it serves.

    Every entry the fit bundle carries as qualified becomes a published
    head; every other one stays unavailable with the bundle's reason. The
    manifest is dated by the bundle's label freeze, so the same bundle
    always derives the same membership.
    """

    registry = target_registry(_TARGET_META)
    if sha256(registry.to_canonical_json()).hexdigest() != bundle.target_registry_hash:
        raise ActivationError("bundle was fit under a different target registry")
    if bundle.retained:
        raise ActivationError("a fit bundle with retained artifacts is not activated")
    heads: list[PublishedHead] = []
    entries: list[BundleTargetEntry] = []
    unpromoted: list[str] = []
    for definition, entry, is_promoted in zip(
        registry.definitions, bundle.entries, promoted, strict=True
    ):
        definition_hash = sha256(definition.to_canonical_json()).hexdigest()
        if entry.status != "qualified":
            if is_promoted:
                raise ActivationError(
                    f"{entry.target_id} is promoted but the bundle has no head for it"
                )
            entries.append(
                BundleTargetEntry(
                    entry.target_id,
                    definition_hash,
                    "unavailable",
                    None,
                    entry.reason or "unavailable",
                )
            )
            continue
        if entry.target_definition_hash != definition_hash:
            raise ActivationError(f"{entry.target_id} was fit to another definition")
        if not is_promoted:
            unpromoted.append(entry.target_id)
        head = PublishedHead.from_bundle_entry(bundle, entry)
        heads.append(head)
        entries.append(
            BundleTargetEntry(
                entry.target_id,
                definition_hash,
                "qualified",
                sha256_hex(head.to_canonical_json()),
                None,
            )
        )
    if unpromoted and not unpromoted_reason:
        raise ActivationError(
            "targets were not promoted: "
            + ", ".join(unpromoted)
            + " (name a reason with --allow-unpromoted to serve them anyway)"
        )
    manifest = BundleManifest(
        bundle.target_registry_hash,
        bundle.representation_hash,
        tuple(entries),
        producer_version,
        bundle.label_window.freeze_at,
    )
    return manifest, tuple(heads), tuple(unpromoted)


def _same_membership(active: BundleManifest, candidate: BundleManifest) -> bool:
    return (
        active.target_registry_hash == candidate.target_registry_hash
        and active.representation_hash == candidate.representation_hash
        and active.entries == candidate.entries
        and active.created_at == candidate.created_at
    )


def activate_fit_bundle(
    database: Database,
    artifacts: ArtifactRepository,
    bundle_bytes: bytes,
    decision_bytes: bytes,
    *,
    unpromoted_reason: str | None,
    producer_version: ProducerVersion,
) -> ActivationRecord:
    """Verify a fit job's bundle and decision, then activate the derived manifest."""

    bundle_file_hash = _committed(artifacts, bundle_bytes, "bundle")
    decision_hash = _committed(artifacts, decision_bytes, "promotion decision")
    bundle = bundle_from_json(bundle_bytes)
    promoted = _promotions(decision_bytes, bundle)
    manifest, heads, unpromoted = derive_manifest(
        bundle,
        promoted,
        unpromoted_reason=unpromoted_reason,
        producer_version=producer_version,
    )
    served = tuple(
        entry.target_id for entry in manifest.entries if entry.status == "qualified"
    )

    def record(
        manifest_hash: str, generation: int, already_active: bool
    ) -> ActivationRecord:
        return ActivationRecord(
            bundle.bundle_id,
            bundle_file_hash,
            decision_hash,
            manifest_hash,
            generation,
            already_active,
            served,
            unpromoted,
            unpromoted_reason if unpromoted else None,
        )

    if active_bundle(database) is not None:
        handle = ServingHandle.load(database, artifacts)
        if _same_membership(handle.manifest, manifest):
            return record(handle.bundle_hash, handle.generation, True)

    command_id = uuid4()
    for head in heads:
        publish_head(artifacts, head, producer_version=producer_version)
    result = activate_bundle(database, artifacts, manifest, command_id=command_id)
    activation = record(result.bundle_hash, result.generation, result.already_active)
    if not result.already_active:
        payload = canonical_json(activation.to_dict())
        artifacts.publish(
            [payload],
            expected_hash=sha256_hex(payload),
            byte_length=len(payload),
            maximum_length=_MAXIMUM_RECORD_BYTES,
            media_type="application/json",
            kind="manifest",
            input_hashes=tuple(
                sorted({result.bundle_hash, bundle_file_hash, decision_hash})
            ),
            producer_version=producer_version,
            config_hash=manifest.target_registry_hash,
            retention_policy_hash=RETENTION_POLICY_HASH,
            command_id=command_id,
        )
    return activation


def _read(path: Path, what: str) -> bytes:
    if path.stat().st_size > _MAXIMUM_INPUT_BYTES:
        raise ActivationError(f"the {what} file is larger than any fit job writes")
    return path.read_bytes()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bundle", type=Path, required=True, help="bundle file")
    parser.add_argument(
        "--decision", type=Path, required=True, help="promotion decision file"
    )
    parser.add_argument("--dsn", required=True)
    parser.add_argument(
        "--artifacts", type=Path, required=True, help="the fit job's artifact store"
    )
    parser.add_argument(
        "--allow-unpromoted",
        metavar="REASON",
        help="serve qualified targets that were not promoted; the reason is recorded",
    )
    args = parser.parse_args(argv)
    if args.allow_unpromoted is not None and not args.allow_unpromoted.strip():
        parser.error("--allow-unpromoted needs a reason")
    migrate(Database(args.dsn))
    database = Database(args.dsn)
    artifacts = ArtifactRepository(database, ArtifactStore(args.artifacts))
    producer = ProducerVersion(sha256(b"local-process").hexdigest(), _commit(), 1)
    try:
        activation = activate_fit_bundle(
            database,
            artifacts,
            _read(args.bundle, "bundle"),
            _read(args.decision, "promotion decision"),
            unpromoted_reason=args.allow_unpromoted,
            producer_version=producer,
        )
    except ValueError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    print(json.dumps(activation.to_dict(), sort_keys=True))
    print(f"active bundle: {activation.manifest_hash}")
    print(f"generation: {activation.generation}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
