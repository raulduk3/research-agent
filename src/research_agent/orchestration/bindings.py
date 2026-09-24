"""What a day's runs are bound to, and what the day may still spend (#285).

`current_bindings` gathers the caller-fixed half of a run record: the
pinned agent model manifest, the service image versions observed at daily
run time, and the launch profile's per-run budgets and tools. Nothing is
stored or read from an active pointer; the snapshot-derived half, the paper
card manifest and prediction head bundles, comes from
`orchestration/stamps.py#build_run_stamp` (SR-15).

`remaining_spend` is the amount an island's coverage draw may still
reserve today: the smaller of the profile's daily and monthly caps less
the settled spend the owner cost read reports (#251), zero unless funded
execution is enabled. A settled run with no price yet is charged its full
per-run reservation, because an ambiguous billed attempt consumes its
reserved amount until reconciled (Appendix A).

`DailyInputs` is what `bin/daily` binds a day to beyond its profile, and
`bin/bindings` prints it (#317): the agent model manifest hash
(`agent_model_manifest_hash`, the canonical hash of the deployment manifest
`bin/run-agent` pins), the observed service image digests, and the index
identities the latest sealed snapshot froze (`current_index_identities`).
The first day has no sealed snapshot, so `--namespace DIR` binds each
published namespace's identity instead (`retrieval/passages.py#namespace_identity`,
#355). With `--runs DAY` it prints instead the run ids `bin/daily` issued for that
day, in slot order, one per line.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from research_agent.agents.model_client import (
    UNPINNED_REVISION,
    AgentDeploymentManifest,
)
from research_agent.contracts.canonical import canonical_json, sha256_hex
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_negative_int,
    validate_sha256,
)
from research_agent.platform.builds import ObservedImage
from research_agent.platform.profile import LaunchProfile
from research_agent.retrieval.passages import namespace_identity
from research_agent.storage.database import Database
from research_agent.storage.errors import UnavailableInput

__all__ = [
    "CostReader",
    "DailyInputs",
    "RunBindings",
    "agent_model_manifest_hash",
    "current_bindings",
    "current_index_identities",
    "parse_image",
    "remaining_spend",
]


class _Costs(Protocol):
    @property
    def data(self) -> Mapping[str, Any]: ...


class CostReader(Protocol):
    """The owner cost read (#251): ``StorageClient`` over the service, or
    the operator's own settlement read in process."""

    def read_costs(self, day: str) -> _Costs: ...


@dataclass(frozen=True, slots=True)
class RunBindings:
    """The caller-fixed fields of every run record a day issues."""

    agent_model_manifest: str
    service_image_versions: dict[str, str]
    budgets: dict[str, int]
    allowed_tools: tuple[str, ...]


def current_bindings(
    profile: LaunchProfile,
    *,
    agent_model_manifest_hash: str,
    observed_images: tuple[ObservedImage, ...],
) -> RunBindings:
    """Bind a day's runs to the pinned model, the observed images and the profile.

    Each service is named by its container role and versioned by the image
    digest it actually runs. No observed image, or two images claiming one
    role, refuses with a named reason rather than recording an identity
    that does not say what served the run. The whole identity is
    validated against the run contract when the stamp adds the snapshot's
    half (`RunStamp.model_identity`).
    """

    validate_sha256(agent_model_manifest_hash)
    if not observed_images:
        raise UnavailableInput("no_observed_service_images")
    versions: dict[str, str] = {}
    for image in observed_images:
        if image.role in versions:
            raise UnavailableInput(f"duplicate_service_role:{image.role}")
        versions[image.role] = image.image_digest
    return RunBindings(
        agent_model_manifest=agent_model_manifest_hash,
        service_image_versions=versions,
        budgets=profile.run.budgets(),
        allowed_tools=tuple(sorted(profile.run.allowed_tools)),
    )


def _spent(totals: Mapping[str, Any], reservation: int) -> int:
    priced = validate_non_negative_int(totals["priced_micros"])
    unpriced = validate_non_negative_int(totals["unpriced_runs"])
    return priced + unpriced * reservation


def remaining_spend(client: CostReader, profile: LaunchProfile, day: str) -> int:
    """Microdollars the day's draw may still reserve under both caps.

    Zero unless the profile is funded with paid execution enabled; never
    negative, however far settled spend has run past a cap.
    """

    budget = profile.budget
    if not (budget.funded and budget.paid_execution_enabled):
        return 0
    costs = client.read_costs(day).data
    reservation = profile.run.spend_micros
    day_left = budget.daily_cap_micros - _spent(costs["day_totals"], reservation)
    month_left = budget.monthly_cap_micros - _spent(costs["month_totals"], reservation)
    return max(0, min(day_left, month_left))


def agent_model_manifest_hash(
    profile: LaunchProfile, *, endpoint: str, revision: str = UNPINNED_REVISION
) -> str:
    """The hash of the agent deployment manifest ``bin/run-agent`` pins.

    The manifest names the profile's provider and model, the endpoint and
    the revision the provider last reported, and whether the profile records
    the agent qualification as passed; it is built exactly as the runner
    builds it, so a manifest the runner would refuse is refused here too.
    """

    manifest = AgentDeploymentManifest(
        provider=profile.model.agent_provider,
        model_id=profile.model.agent_model_id,
        endpoint=endpoint,
        revision=revision,
        qualified=profile.model.agent_qualification_passed,
    )
    return sha256_hex(canonical_json(manifest.to_dict()))


def parse_image(value: str) -> ObservedImage:
    """One ``ROLE=SHA256`` observed service image."""

    role, separator, digest = value.partition("=")
    if not separator:
        raise ContractValidationError(f"image must be ROLE=SHA256, got {value!r}")
    return ObservedImage(role, digest, {})


def current_index_identities(database: Database) -> tuple[str, ...]:
    """The index identities the latest sealed snapshot froze, in its order.

    No sealed snapshot refuses as ``no_sealed_snapshot``: the first day's
    identities are its published namespaces' (``namespace_identity``).
    """

    rows = database.transaction(
        lambda connection: connection.execute(
            """SELECT encode(i.index_hash,'hex') FROM snapshot_indexes i
               WHERE i.snapshot_hash = (
                   SELECT hash FROM snapshots ORDER BY sealed_at DESC, hash LIMIT 1)
               ORDER BY i.ordinal"""
        ).fetchall()
    )
    if not rows:
        raise UnavailableInput("no_sealed_snapshot")
    return tuple(str(row[0]) for row in rows)


@dataclass(frozen=True, slots=True)
class DailyInputs:
    """What ``bin/daily`` binds a day to beyond its launch profile."""

    agent_model_manifest: str
    observed_images: tuple[ObservedImage, ...]
    index_identity_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        validate_sha256(self.agent_model_manifest)
        if not self.observed_images:
            raise UnavailableInput("no_observed_service_images")
        roles = [image.role for image in self.observed_images]
        for role in roles:
            if roles.count(role) > 1:
                raise UnavailableInput(f"duplicate_service_role:{role}")
        if not self.index_identity_hashes:
            raise ContractValidationError("index_identity_hashes must be nonempty")
        for value in self.index_identity_hashes:
            validate_sha256(value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "agent_model_manifest": self.agent_model_manifest,
            "images": {
                image.role: image.image_digest for image in self.observed_images
            },
            "index_identity_hashes": list(self.index_identity_hashes),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> DailyInputs:
        expected = {
            "schema_version",
            "agent_model_manifest",
            "images",
            "index_identity_hashes",
        }
        if set(value) != expected or value["schema_version"] != 1:
            raise ContractValidationError(
                "bindings must be a schema_version 1 object with exactly "
                + ", ".join(sorted(expected))
            )
        images = value["images"]
        if not isinstance(images, Mapping):
            raise ContractValidationError("images must map a role to a digest")
        return cls(
            value["agent_model_manifest"],
            tuple(ObservedImage(role, digest, {}) for role, digest in images.items()),
            tuple(value["index_identity_hashes"]),
        )


def _images(args: argparse.Namespace) -> tuple[ObservedImage, ...]:
    """The ``--images`` file's role-to-digest object, then each ``--image``."""

    observed: list[ObservedImage] = []
    if args.images is not None:
        recorded = json.loads(args.images.read_text())
        if not isinstance(recorded, dict):
            raise ContractValidationError("--images must hold a role-to-digest object")
        observed.extend(
            ObservedImage(role, digest, {}) for role, digest in recorded.items()
        )
    observed.extend(parse_image(value) for value in args.image)
    return tuple(observed)


def main(argv: list[str] | None = None) -> int:
    from research_agent.orchestration.daily import issued_runs

    parser = argparse.ArgumentParser(
        description="Print the inputs bin/daily binds a day to, or a day's run ids."
    )
    parser.add_argument("--runs", metavar="YYYY-MM-DD", help="list this day's run ids")
    parser.add_argument("--state", type=Path, help="bin/daily's state directory")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--endpoint", help="agent chat-completions URL")
    parser.add_argument("--revision", default=UNPINNED_REVISION)
    parser.add_argument(
        "--images", type=Path, help="a JSON object of role to observed image digest"
    )
    parser.add_argument(
        "--image",
        action="append",
        default=[],
        metavar="ROLE=SHA256",
        help="an observed service image digest; repeat once per role",
    )
    parser.add_argument("--dsn", help="read the latest snapshot's index identities")
    parser.add_argument(
        "--index-identity",
        action="append",
        default=[],
        metavar="SHA256",
        help="name the index identities instead of reading them from storage",
    )
    parser.add_argument(
        "--namespace",
        action="append",
        default=[],
        type=Path,
        metavar="DIR",
        help="a published representation namespace whose identity to bind",
    )
    args = parser.parse_args(argv)
    try:
        if args.runs is not None:
            if args.state is None:
                parser.error("--runs needs --state")
            for run_id in issued_runs(args.state, args.runs):
                print(run_id)
            return 0
        if args.profile is None or args.endpoint is None:
            parser.error("--profile and --endpoint are required")
        sources = (bool(args.dsn), bool(args.index_identity), bool(args.namespace))
        if sum(sources) != 1:
            parser.error("give exactly one of --dsn, --index-identity and --namespace")
        profile = LaunchProfile.from_json(args.profile.read_bytes())
        if args.namespace:
            identities = tuple(namespace_identity(path) for path in args.namespace)
        elif args.index_identity:
            identities = tuple(args.index_identity)
        else:
            identities = current_index_identities(Database(args.dsn))
        inputs = DailyInputs(
            agent_model_manifest_hash(
                profile, endpoint=args.endpoint, revision=args.revision
            ),
            _images(args),
            identities,
        )
    except (UnavailableInput, ContractValidationError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    print(json.dumps(inputs.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
