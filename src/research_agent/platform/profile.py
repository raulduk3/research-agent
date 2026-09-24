"""Mode-specific complete-profile gate (SDD-SR-28).

`LaunchProfile` parses Appendix A's values into the nine closed groups SR-28
names: runtime, storage, model, source, budget, evaluation, privacy,
recovery and disabled-capabilities, plus the `run` section of per-run
budgets and tools every run record carries (#285) and the `host` section of
the guest's size and public reach (#336). Each group separates a chosen design
ceiling (the fixed decimal caps in `BudgetGroup`) from the operator's actual
funding authorization or deployment binding (`BudgetGroup.funded`,
`StorageGroup.backup_endpoint_bound`), so a caller never mistakes a ceiling
for permission to spend against it.

`readiness` is the typed gate SR-28's Behavior bullet requires: collection
needs licensed source access; engineering adds verified local replay
integrity; study additionally needs agent qualification, a verified backup
and funded inference. A mode's readiness never implies a stronger mode's,
because each call re-checks its own gate list from the same immutable
profile rather than caching a weaker mode's pass.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from research_agent.contracts.canonical import (
    CanonicalJsonError,
    canonical_json,
    canonical_loads,
    sha256_hex,
)
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_positive_int,
)
from research_agent.contracts.runs import (
    ALLOWED_TOOLS,
    BUDGET_FIELDS,
    validate_allowed_tools,
    validate_run_budgets,
)
from research_agent.platform.inventory import MODES

_GROUP_FIELDS: frozenset[str] = frozenset(
    {
        "runtime",
        "storage",
        "model",
        "source",
        "budget",
        "evaluation",
        "privacy",
        "recovery",
        "disabled_capabilities",
        "run",
        "host",
    }
)


def _closed(raw: bytes, fields: frozenset[str], name: str) -> dict[str, Any]:
    value = canonical_loads(raw)
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractValidationError(f"{name} has unknown or missing fields")
    return value


@dataclass(frozen=True, slots=True)
class RuntimeGroup:
    python_version: str
    uv_version: str

    def __post_init__(self) -> None:
        validate_non_empty_string(self.python_version)
        validate_non_empty_string(self.uv_version)

    def to_dict(self) -> dict[str, object]:
        return {"python_version": self.python_version, "uv_version": self.uv_version}


@dataclass(frozen=True, slots=True)
class StorageGroup:
    postgres_version: str
    backup_endpoint_bound: bool
    anchor_endpoint_bound: bool

    def __post_init__(self) -> None:
        validate_non_empty_string(self.postgres_version)

    def to_dict(self) -> dict[str, object]:
        return {
            "postgres_version": self.postgres_version,
            "backup_endpoint_bound": self.backup_endpoint_bound,
            "anchor_endpoint_bound": self.anchor_endpoint_bound,
        }


@dataclass(frozen=True, slots=True)
class ModelGroup:
    agent_model_id: str
    agent_provider: str
    embedding_model_revision: str
    agent_qualification_passed: bool

    def __post_init__(self) -> None:
        validate_non_empty_string(self.agent_model_id)
        validate_non_empty_string(self.agent_provider)
        validate_non_empty_string(self.embedding_model_revision)

    def to_dict(self) -> dict[str, object]:
        return {
            "agent_model_id": self.agent_model_id,
            "agent_provider": self.agent_provider,
            "embedding_model_revision": self.embedding_model_revision,
            "agent_qualification_passed": self.agent_qualification_passed,
        }


@dataclass(frozen=True, slots=True)
class SourceGroup:
    licensed_source_ids: frozenset[str]

    def to_dict(self) -> dict[str, object]:
        return {"licensed_source_ids": sorted(self.licensed_source_ids)}


def _usd_micros(value: str) -> int:
    """A profile cap written in USD, as whole microdollars."""

    try:
        micros = Decimal(value) * 1_000_000
    except InvalidOperation as error:
        raise ContractValidationError("a budget cap must be a USD amount") from error
    if not micros.is_finite() or micros < 0 or micros != micros.to_integral_value():
        raise ContractValidationError("a budget cap must be whole microdollars")
    return int(micros)


@dataclass(frozen=True, slots=True)
class BudgetGroup:
    paid_execution_enabled: bool
    daily_cap_usd: str
    monthly_cap_usd: str
    funded: bool

    def __post_init__(self) -> None:
        validate_non_empty_string(self.daily_cap_usd)
        validate_non_empty_string(self.monthly_cap_usd)

    @property
    def daily_cap_micros(self) -> int:
        return _usd_micros(self.daily_cap_usd)

    @property
    def monthly_cap_micros(self) -> int:
        return _usd_micros(self.monthly_cap_usd)

    def to_dict(self) -> dict[str, object]:
        return {
            "paid_execution_enabled": self.paid_execution_enabled,
            "daily_cap_usd": self.daily_cap_usd,
            "monthly_cap_usd": self.monthly_cap_usd,
            "funded": self.funded,
        }


@dataclass(frozen=True, slots=True)
class EvaluationGroup:
    replay_integrity_verified: bool

    def to_dict(self) -> dict[str, object]:
        return {"replay_integrity_verified": self.replay_integrity_verified}


@dataclass(frozen=True, slots=True)
class PrivacyGroup:
    retention_years: int

    def __post_init__(self) -> None:
        if not isinstance(self.retention_years, int) or self.retention_years <= 0:
            raise ContractValidationError("retention_years must be a positive integer")

    def to_dict(self) -> dict[str, object]:
        return {"retention_years": self.retention_years}


@dataclass(frozen=True, slots=True)
class RecoveryGroup:
    backup_verified: bool

    def to_dict(self) -> dict[str, object]:
        return {"backup_verified": self.backup_verified}


@dataclass(frozen=True, slots=True)
class DisabledCapabilities:
    capability_ids: frozenset[str]

    def to_dict(self) -> dict[str, object]:
        return {"capability_ids": sorted(self.capability_ids)}


@dataclass(frozen=True, slots=True)
class RunGroup:
    """Per-run budgets and tools, owner-changeable profile values (#285).

    The launch values are Appendix A's per-run paragraph (decision 0022):
    6 model calls, 12 tool calls, 3 deep reads, 6 images, a 32768-token
    context, 4096 generated tokens, 64000 cumulative tokens, 300 seconds of
    wall time, 1 retry and the 120-second provider request timeout.
    ``spend_micros`` is the per-run reservation ceiling, USD 0.01. The nine
    fields of `contracts/runs.py#BUDGET_FIELDS` are what a run record
    carries; ``model_calls`` and ``max_tokens_per_run`` complete the loop's
    own ceilings.
    """

    model_calls: int = 6
    tool_calls: int = 12
    deep_reads: int = 3
    images: int = 6
    context_tokens: int = 32768
    generation_tokens: int = 4096
    max_tokens_per_run: int = 64000
    wall_time_seconds: int = 300
    retries: int = 1
    timeout_seconds: int = 120
    spend_micros: int = 10000
    allowed_tools: frozenset[str] = ALLOWED_TOOLS

    def __post_init__(self) -> None:
        validate_positive_int(self.model_calls)
        validate_positive_int(self.max_tokens_per_run)
        validate_run_budgets(self.budgets())
        if not isinstance(self.allowed_tools, frozenset):
            raise ContractValidationError("allowed_tools must be a frozenset")
        validate_allowed_tools(sorted(self.allowed_tools, key=str))

    def budgets(self) -> dict[str, int]:
        """The run record's budget object, exactly `BUDGET_FIELDS`."""

        return {name: getattr(self, name) for name in sorted(BUDGET_FIELDS)}

    def to_dict(self) -> dict[str, object]:
        return {
            **self.budgets(),
            "model_calls": self.model_calls,
            "max_tokens_per_run": self.max_tokens_per_run,
            "allowed_tools": sorted(self.allowed_tools),
        }


_RUN_FIELDS: frozenset[str] = BUDGET_FIELDS | {
    "model_calls",
    "max_tokens_per_run",
    "allowed_tools",
}

_HOSTNAME = re.compile(
    r"(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+"
)


def _validate_origin(value: str) -> None:
    """Refuse anything but ``https://host`` or ``https://host:port``."""

    parts = urlsplit(value)
    try:
        port = parts.port
    except ValueError as error:
        raise ContractValidationError("front_end_origin has an invalid port") from error
    if (
        parts.scheme != "https"
        or parts.hostname is None
        or not _HOSTNAME.fullmatch(parts.hostname)
        or parts.username is not None
        or parts.path
        or parts.query
        or parts.fragment
        or value != f"https://{parts.hostname}" + (f":{port}" if port else "")
    ):
        raise ContractValidationError(
            "front_end_origin must be one https origin with no path or wildcard"
        )


@dataclass(frozen=True, slots=True)
class HostGroup:
    """The one application host's guest size and public reach (#336).

    ``guest_vcpus`` and ``guest_memory_gib`` size the Linux guest the
    services run in; the batch memory thresholds are fractions of the
    guest's memory (`platform/resources.py#ResourcePolicy.for_guest`).
    ``public_hostname`` is the tunnel's reserved domain the owner surfaces
    are published under, empty when nothing is published (decision 0030).
    ``front_end_origin`` is the one browser origin the owner API admits
    cross-origin, empty to admit none. The defaults are the committed
    guest's size and no public reach.
    """

    guest_vcpus: int = 4
    guest_memory_gib: int = 8
    public_hostname: str = ""
    front_end_origin: str = ""

    def __post_init__(self) -> None:
        validate_positive_int(self.guest_vcpus)
        validate_positive_int(self.guest_memory_gib)
        if not isinstance(self.public_hostname, str) or (
            self.public_hostname and not _HOSTNAME.fullmatch(self.public_hostname)
        ):
            raise ContractValidationError(
                "public_hostname must be empty or one lowercase hostname"
            )
        if not isinstance(self.front_end_origin, str):
            raise ContractValidationError("front_end_origin must be a string")
        if self.front_end_origin:
            _validate_origin(self.front_end_origin)

    def to_dict(self) -> dict[str, object]:
        return {
            "guest_vcpus": self.guest_vcpus,
            "guest_memory_gib": self.guest_memory_gib,
            "public_hostname": self.public_hostname,
            "front_end_origin": self.front_end_origin,
        }

    def guest_arguments(self) -> tuple[str, ...]:
        """The ``limactl start`` options that size the guest from this group."""

        return (
            "--cpus",
            str(self.guest_vcpus),
            "--memory",
            str(self.guest_memory_gib),
        )


_HOST_FIELDS: frozenset[str] = frozenset(HostGroup().to_dict())


# The gates each mode adds beyond the weaker mode before it, per SR-28's
# Behavior bullet: collection needs licensed source access; engineering adds
# verified local replay integrity; study additionally needs qualification,
# a verified backup and funded inference.
_COLLECTION_GATES: tuple[str, ...] = ("licensed_source_access",)
_ENGINEERING_GATES: tuple[str, ...] = (*_COLLECTION_GATES, "replay_integrity")
_STUDY_GATES: tuple[str, ...] = (
    *_ENGINEERING_GATES,
    "agent_qualification",
    "backup_verified",
    "funded_inference",
)


@dataclass(frozen=True, slots=True)
class LaunchProfile:
    """One closed, immutable launch profile: Appendix A parsed into nine groups.

    ``run`` defaults to Appendix A's launch values so a profile built in
    code without it still carries the decided per-run budgets, and ``host``
    to the committed guest with no public reach; a parsed profile must name
    both.
    """

    profile_version: str
    runtime: RuntimeGroup
    storage: StorageGroup
    model: ModelGroup
    source: SourceGroup
    budget: BudgetGroup
    evaluation: EvaluationGroup
    privacy: PrivacyGroup
    recovery: RecoveryGroup
    disabled_capabilities: DisabledCapabilities
    run: RunGroup = field(default_factory=RunGroup)
    host: HostGroup = field(default_factory=HostGroup)

    def __post_init__(self) -> None:
        validate_non_empty_string(self.profile_version)

    def to_dict(self) -> dict[str, object]:
        return {
            "profile_version": self.profile_version,
            "runtime": self.runtime.to_dict(),
            "storage": self.storage.to_dict(),
            "model": self.model.to_dict(),
            "source": self.source.to_dict(),
            "budget": self.budget.to_dict(),
            "evaluation": self.evaluation.to_dict(),
            "privacy": self.privacy.to_dict(),
            "recovery": self.recovery.to_dict(),
            "disabled_capabilities": self.disabled_capabilities.to_dict(),
            "run": self.run.to_dict(),
            "host": self.host.to_dict(),
        }

    def compute_hash(self) -> str:
        return sha256_hex(canonical_json(self.to_dict()))

    def readiness(self, mode: str) -> tuple[str, ...]:
        """Return the unmet gates for *mode*; an empty tuple means it is ready.

        A mode's result never leans on a stronger or weaker mode's outcome:
        each call re-evaluates its full gate list against this same profile.
        """

        if mode not in MODES:
            raise ContractValidationError("mode must be one of MODES")
        if mode == "collection":
            gates = _COLLECTION_GATES
        elif mode == "engineering":
            gates = _ENGINEERING_GATES
        else:
            gates = _STUDY_GATES

        unmet: list[str] = []
        checks = {
            "licensed_source_access": bool(self.source.licensed_source_ids),
            "replay_integrity": self.evaluation.replay_integrity_verified,
            "agent_qualification": self.model.agent_qualification_passed,
            "backup_verified": self.recovery.backup_verified,
            "funded_inference": self.budget.funded
            and self.budget.paid_execution_enabled,
        }
        for gate in gates:
            if not checks[gate]:
                unmet.append(gate)
        return tuple(unmet)

    @classmethod
    def from_json(cls, raw: bytes) -> "LaunchProfile":
        value = _closed(raw, _GROUP_FIELDS | {"profile_version"}, "LaunchProfile")
        runtime = value["runtime"]
        storage = value["storage"]
        model = value["model"]
        source = value["source"]
        budget = value["budget"]
        evaluation = value["evaluation"]
        privacy = value["privacy"]
        recovery = value["recovery"]
        disabled = value["disabled_capabilities"]
        run = value["run"]
        host = value["host"]
        if not all(
            isinstance(group, dict)
            for group in (
                runtime,
                storage,
                model,
                source,
                budget,
                evaluation,
                privacy,
                recovery,
                disabled,
                run,
                host,
            )
        ):
            raise ContractValidationError("every profile group must be a JSON object")
        if set(run) != _RUN_FIELDS:
            raise ContractValidationError("run has unknown or missing fields")
        if set(host) != _HOST_FIELDS:
            raise ContractValidationError("host has unknown or missing fields")
        try:
            return cls(
                profile_version=value["profile_version"],
                runtime=RuntimeGroup(**runtime),
                storage=StorageGroup(**storage),
                model=ModelGroup(**model),
                source=SourceGroup(
                    licensed_source_ids=frozenset(source["licensed_source_ids"])
                ),
                budget=BudgetGroup(**budget),
                evaluation=EvaluationGroup(**evaluation),
                privacy=PrivacyGroup(**privacy),
                recovery=RecoveryGroup(**recovery),
                disabled_capabilities=DisabledCapabilities(
                    capability_ids=frozenset(disabled["capability_ids"])
                ),
                run=RunGroup(
                    **{
                        **run,
                        "allowed_tools": frozenset(
                            validate_allowed_tools(run["allowed_tools"])
                        ),
                    }
                ),
                host=HostGroup(**host),
            )
        except ContractValidationError:
            raise
        except (AttributeError, KeyError, TypeError) as error:
            raise ContractValidationError("profile group fields are invalid") from error


# Appendix A's launch values as one profile: the reference `bin/check-profile`
# compares against and `docs/implementation/launch-profile.example.json`
# reproduces. Every evidence and funding flag is false, so the reference can
# neither spend nor claim a gate it has not passed; a flag turns true only in
# an operator's profile, after the runbook step that evidences it. Retention
# is the study duration plus two years; the licensed sources are the two
# launch sources whose permission is allowed
# (docs/evidence/permissions/source-permissions.md); the disabled
# capabilities are Appendix A's disabled-for-launch list.
LAUNCH_PROFILE = LaunchProfile(
    profile_version="launch-v2",
    runtime=RuntimeGroup(python_version="3.12.12", uv_version="0.8.22"),
    storage=StorageGroup(
        postgres_version="17.11",
        backup_endpoint_bound=False,
        anchor_endpoint_bound=False,
    ),
    model=ModelGroup(
        agent_model_id="glm-5.3-flash",
        agent_provider="zai",
        embedding_model_revision="d556a88e332558790b210f7bdbe87da2fa94a8d8",
        agent_qualification_passed=False,
    ),
    source=SourceGroup(licensed_source_ids=frozenset({"arxiv", "openalex"})),
    budget=BudgetGroup(
        paid_execution_enabled=False,
        daily_cap_usd="8.00",
        monthly_cap_usd="200.00",
        funded=False,
    ),
    evaluation=EvaluationGroup(replay_integrity_verified=False),
    privacy=PrivacyGroup(retention_years=2),
    recovery=RecoveryGroup(backup_verified=False),
    disabled_capabilities=DisabledCapabilities(
        capability_ids=frozenset(
            {
                "evolved_schema_fields",
                "agent_past_ledger_access",
                "agent_persistent_memory",
                "preference_selection_objective",
                "additional_prediction_heads",
                "encoder_fine_tuning",
                "masked_lm_surprise",
                "trend_to_paper_forecasts",
                "co_citation_forecasts",
                "query_growth_forecasts",
                "rate_growth_forecasts",
            }
        )
    ),
    run=RunGroup(),
    host=HostGroup(),
)


def _leaves(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        return {path: value}
    leaves: dict[str, object] = {}
    for key, item in value.items():
        leaves.update(_leaves(item, f"{path}.{key}" if path else key))
    return leaves


def differences(
    profile: LaunchProfile, reference: LaunchProfile = LAUNCH_PROFILE
) -> tuple[tuple[str, object, object], ...]:
    """Every field of *profile* whose value differs from *reference*.

    Each entry is the dotted field path, the reference value and the
    profile's value, in path order.
    """

    expected = _leaves(reference.to_dict(), "")
    actual = _leaves(profile.to_dict(), "")
    return tuple(
        (path, expected[path], actual[path])
        for path in sorted(expected)
        if expected[path] != actual[path]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a launch profile, print its hash and every field "
        "that differs from Appendix A's launch values."
    )
    parser.add_argument("file", type=Path)
    parser.add_argument(
        "--guest",
        action="store_true",
        help="print only the limactl start options that size the guest",
    )
    args = parser.parse_args(argv)
    try:
        profile = LaunchProfile.from_json(args.file.read_bytes())
    except (OSError, CanonicalJsonError, ContractValidationError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    if args.guest:
        print(" ".join(profile.host.guest_arguments()))
        return 0
    print(f"profile_hash {profile.compute_hash()}")
    for path, launch, actual in differences(profile):
        print(
            f"differs {path}: launch {json.dumps(launch)}, profile {json.dumps(actual)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
