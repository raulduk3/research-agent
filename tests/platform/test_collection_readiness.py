from pathlib import Path

from research_agent.platform.collection import check_collection_readiness


def test_collection_readiness_refuses_without_isolation_evidence(
    tmp_path: Path,
) -> None:
    compose = tmp_path / "compose.yaml"
    config = tmp_path / "storage.json"
    compose.write_text("services: {}\n")
    config.write_text("{}\n")
    result = check_collection_readiness(
        compose_file=compose, storage_config=config, isolation_evidence=None
    )
    assert not result.ready
    assert "host_enforced_isolation_evidence" in result.missing


def test_collection_readiness_does_not_trust_unverified_evidence(
    tmp_path: Path,
) -> None:
    compose = tmp_path / "compose.yaml"
    config = tmp_path / "storage.json"
    evidence = tmp_path / "isolation.txt"
    compose.write_text("services: {}\n")
    config.write_text("{}\n")
    evidence.write_text("claimed\n")
    result = check_collection_readiness(
        compose_file=compose, storage_config=config, isolation_evidence=evidence
    )
    assert not result.ready
    assert "host_enforced_isolation_unverified" in result.missing
