"""Mode-specific complete-profile gate (SDD-SR-28).

`LaunchProfile` parses Appendix A's values into the nine closed groups SR-28
names: runtime, storage, model, source, budget, evaluation, privacy,
recovery and disabled-capabilities, plus the `run` section of per-run
budgets and tools every run record carries (#285). Each group separates a chosen design
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

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from research_agent.contracts.canonical import (
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
    code without it still carries the decided per-run budgets; a parsed
    profile must name it.
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
            )
        ):
            raise ContractValidationError("every profile group must be a JSON object")
        if set(run) != _RUN_FIELDS:
            raise ContractValidationError("run has unknown or missing fields")
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
            )
        except ContractValidationError:
            raise
        except (AttributeError, KeyError, TypeError) as error:
            raise ContractValidationError("profile group fields are invalid") from error
