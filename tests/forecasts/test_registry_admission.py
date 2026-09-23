import pytest

from research_agent.contracts.forecasts import RegistryAdmission
from research_agent.contracts.learning import TARGET_IDS
from research_agent.contracts.primitives import ContractValidationError
from research_agent.forecasts.admission import admit_registry

_DEFINITION_HASHES = {target_id: "a" * 64 for target_id in TARGET_IDS}
_BUILD_HASHES = {target_id: "b" * 64 for target_id in TARGET_IDS}
_CONFORMANCE_HASH = "c" * 64


def _repeat_results(
    *, unknown_target: str | None = None
) -> dict[str, tuple[bytes, bytes]]:
    results: dict[str, tuple[bytes, bytes]] = {}
    for target_id in TARGET_IDS:
        canonical = (
            b'{"status":"unknown"}'
            if target_id == unknown_target
            else b'{"status":"true"}'
        )
        results[target_id] = (canonical, canonical)
    return results


def _admit(**overrides: object) -> RegistryAdmission:
    kwargs: dict[str, object] = {
        "caller_role": "operator",
        "target_definition_hashes": _DEFINITION_HASHES,
        "resolver_build_hashes": _BUILD_HASHES,
        "conformance_report_hash": _CONFORMANCE_HASH,
        "repeat_results": _repeat_results(),
    }
    kwargs.update(overrides)
    return admit_registry(**kwargs)  # type: ignore[arg-type]


def test_the_three_fixed_registry_definitions_are_admitted() -> None:
    admission = _admit()
    assert admission.admitted_target_ids == TARGET_IDS
    assert admission.target_definition_hashes == tuple(
        _DEFINITION_HASHES[target_id] for target_id in TARGET_IDS
    )


def test_repeat_check_accepts_identical_unknown_case_results() -> None:
    admission = _admit(repeat_results=_repeat_results(unknown_target=TARGET_IDS[1]))
    assert admission.admitted_target_ids == TARGET_IDS


def test_agent_tool_credentials_cannot_admit_the_registry() -> None:
    with pytest.raises(ContractValidationError):
        _admit(caller_role="agent")


def test_an_unknown_target_definition_remains_unadmitted() -> None:
    hashes = dict(_DEFINITION_HASHES)
    del hashes["citation_reach_365d"]
    hashes["a_random_number_target"] = "a" * 64
    with pytest.raises(ContractValidationError):
        _admit(target_definition_hashes=hashes)


def test_a_random_number_resolver_fixture_is_refused() -> None:
    """A resolver whose two independent runs over the same fixtures
    disagree -- the random-number-resolver case -- refuses the whole
    admission rather than admitting the targets that did check out."""

    results = _repeat_results()
    results[TARGET_IDS[0]] = (b'{"status":"true"}', b'{"status":"false"}')
    with pytest.raises(ContractValidationError):
        _admit(repeat_results=results)


def test_incomplete_registry_is_refused() -> None:
    incomplete = dict(_repeat_results())
    del incomplete[TARGET_IDS[0]]
    with pytest.raises(ContractValidationError):
        _admit(repeat_results=incomplete)
