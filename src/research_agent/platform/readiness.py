"""Evidence-gated layer activation (SDD-SR-17).

`evaluate_admission` is the gate SR-17 fixes: a layer, meaning anything added
to the running configuration to improve a score, activates only behind a
registered baseline on the same primary metric and a comparison report whose
registration precedes its execution. `ComparisonReport` enforces that
temporal precedence structurally, so a post-hoc registration cannot even be
constructed as evidence, matching the requirement that a green unit test is
never mistaken for a measured baseline.

The Jev layer is held out until a later accepted decision admits it
(`jev_admitted`); every future prediction head stays denied unconditionally,
because SR-17 fixes that no caller flag can move it, so this module accepts
no parameter that would let one try.
"""

from __future__ import annotations

from dataclasses import dataclass

from research_agent.contracts.canonical import canonical_json, sha256_hex
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_sha256,
    validate_utc_instant,
    validate_uuid4,
)

JEV_LAYER_ID: str = "jev"

# The disabled-for-launch future prediction heads Appendix A names; SR-17
# denies every one of them irrespective of any caller flag.
FUTURE_PREDICTION_HEAD_LAYER_IDS: frozenset[str] = frozenset(
    {
        "encoder_fine_tuning",
        "masked_lm_surprise",
        "trend_to_paper",
        "co_citation",
        "query_growth",
        "rate_growth",
    }
)


@dataclass(frozen=True, slots=True)
class ComparisonReport:
    """One registered, executed comparison; registration must precede execution."""

    report_id: str
    primary_metric: str
    registered_at: str
    executed_at: str

    def __post_init__(self) -> None:
        validate_uuid4(self.report_id)
        validate_non_empty_string(self.primary_metric)
        validate_utc_instant(self.registered_at)
        validate_utc_instant(self.executed_at)
        if self.registered_at > self.executed_at:
            raise ContractValidationError(
                "a comparison's registration must precede its execution"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "report_id": self.report_id,
            "primary_metric": self.primary_metric,
            "registered_at": self.registered_at,
            "executed_at": self.executed_at,
        }


@dataclass(frozen=True, slots=True)
class LayerAdmission:
    """The immutable admission decision for one layer activation request."""

    layer_id: str
    baseline_config_hash: str | None
    candidate_config_hash: str
    registered_primary_metric: str
    comparison_report_ids: tuple[str, ...]
    activation_scope: str
    denial_reasons: tuple[str, ...]

    @property
    def admitted(self) -> bool:
        return not self.denial_reasons

    def to_dict(self) -> dict[str, object]:
        return {
            "layer_id": self.layer_id,
            "baseline_config_hash": self.baseline_config_hash,
            "candidate_config_hash": self.candidate_config_hash,
            "registered_primary_metric": self.registered_primary_metric,
            "comparison_report_ids": list(self.comparison_report_ids),
            "activation_scope": self.activation_scope,
            "denial_reasons": list(self.denial_reasons),
        }

    def record_hash(self) -> str:
        return sha256_hex(canonical_json(self.to_dict()))


def evaluate_admission(
    *,
    layer_id: str,
    baseline_config_hash: str | None,
    candidate_config_hash: str,
    registered_primary_metric: str,
    reports: tuple[ComparisonReport, ...],
    activation_scope: str,
    jev_admitted: bool,
) -> LayerAdmission:
    """Evaluate one layer activation request against SR-17's fixed gate."""

    validate_non_empty_string(layer_id)
    validate_sha256(candidate_config_hash)
    if baseline_config_hash is not None:
        validate_sha256(baseline_config_hash)
    validate_non_empty_string(registered_primary_metric)
    validate_non_empty_string(activation_scope)

    reasons: list[str] = []
    if layer_id == JEV_LAYER_ID and not jev_admitted:
        reasons.append("jev_layer_held_out")
    elif layer_id in FUTURE_PREDICTION_HEAD_LAYER_IDS:
        reasons.append("future_prediction_head_denied")
    if baseline_config_hash is None:
        reasons.append("missing_baseline")
    if not reports:
        reasons.append("missing_comparison_report")
    elif any(report.primary_metric != registered_primary_metric for report in reports):
        reasons.append("wrong_metric_report")

    return LayerAdmission(
        layer_id=layer_id,
        baseline_config_hash=baseline_config_hash,
        candidate_config_hash=candidate_config_hash,
        registered_primary_metric=registered_primary_metric,
        comparison_report_ids=tuple(report.report_id for report in reports),
        activation_scope=activation_scope,
        denial_reasons=tuple(reasons),
    )
