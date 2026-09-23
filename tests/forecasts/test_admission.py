import pytest

from research_agent.contracts.forecasts import AdmissionRefusal
from research_agent.contracts.learning import TARGET_IDS
from research_agent.contracts.primitives import ContractValidationError
from research_agent.forecasts.admission import validate_target

DISABLED_TYPES = (
    "trend_to_paper",
    "co_citation",
    "query_growth",
    "citation_rate_growth",
)


def _request(
    requested_type: str, *, resolver_id: str = "resolver-1"
) -> dict[str, object]:
    return {
        "requested_type": requested_type,
        "resolver_id": resolver_id,
        "target_definition_hash": "a" * 64,
    }


@pytest.mark.parametrize("disabled_type", DISABLED_TYPES)
def test_disabled_types_are_refused_before_any_resolution(disabled_type: str) -> None:
    result = validate_target(_request(disabled_type))
    assert isinstance(result, AdmissionRefusal)
    assert result.reason == "unadmitted_type"
    assert result.attempted_type == disabled_type


def test_aliasing_an_admitted_resolver_does_not_admit_a_disabled_type() -> None:
    """A disabled type is refused even when it claims an admitted
    resolver's own id or target hash (TDD-3.1.25 to TDD-3.1.28): the
    requested type alone decides admission."""

    request = _request("trend_to_paper", resolver_id="citation_reach_365d_resolver_v1")
    result = validate_target(request)
    assert isinstance(result, AdmissionRefusal)
    assert result.reason == "unadmitted_type"


def test_refusal_is_stable_for_the_same_request() -> None:
    request = _request("co_citation")
    first = validate_target(request)
    second = validate_target(request)
    assert isinstance(first, AdmissionRefusal) and isinstance(second, AdmissionRefusal)
    assert first.request_hash == second.request_hash


@pytest.mark.parametrize("target_id", TARGET_IDS)
def test_admitted_targets_pass_through(target_id: str) -> None:
    result = validate_target(_request(target_id))
    assert not isinstance(result, AdmissionRefusal)
    assert result["requested_type"] == target_id


def test_malformed_request_is_rejected_before_admission() -> None:
    with pytest.raises(ContractValidationError):
        validate_target({"requested_type": "trend_to_paper"})
