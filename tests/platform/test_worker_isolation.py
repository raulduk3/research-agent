import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.platform.isolation import NetworkDestination, WorkerIsolation

RUN_ID = "8b6a5f2e-5c1a-4b4b-9b3d-8e2f6a7c1d90"
SNAPSHOT_HASH = "a" * 64


def _isolation() -> WorkerIsolation:
    return WorkerIsolation(
        run_id=RUN_ID,
        snapshot_hash=SNAPSHOT_HASH,
        tool_service=NetworkDestination("tools.internal", 8443),
        model_proxy=NetworkDestination("proxy.internal", 8444),
    )


def test_worker_isolation_permits_only_its_two_destinations() -> None:
    isolation = _isolation()
    assert isolation.is_permitted(NetworkDestination("tools.internal", 8443))
    assert isolation.is_permitted(NetworkDestination("proxy.internal", 8444))


def test_worker_isolation_denies_the_shared_model_service_and_storage() -> None:
    isolation = _isolation()
    assert not isolation.is_permitted(NetworkDestination("models.internal", 9000))
    assert not isolation.is_permitted(NetworkDestination("storage.internal", 8443))


def test_worker_isolation_denies_metadata_and_internet_addresses() -> None:
    isolation = _isolation()
    assert not isolation.is_permitted(NetworkDestination("1.1.1.1", 443))
    with pytest.raises(ContractValidationError):
        NetworkDestination("169.254.169.254", 80)


def test_worker_isolation_rejects_identical_tool_and_proxy_destinations() -> None:
    with pytest.raises(ContractValidationError):
        WorkerIsolation(
            run_id=RUN_ID,
            snapshot_hash=SNAPSHOT_HASH,
            tool_service=NetworkDestination("shared.internal", 8443),
            model_proxy=NetworkDestination("shared.internal", 8443),
        )
