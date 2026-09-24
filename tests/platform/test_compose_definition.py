import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from research_agent.contracts.primitives import ContractValidationError
from research_agent.platform.compose import (
    STATIC_ROLE_IDS,
    inventory_from_definition,
)
from research_agent.platform.health import FAILURE_THRESHOLD, POLL_INTERVAL_SECONDS
from research_agent.platform.resources import ROLE_LIMITS
from research_agent.platform.secrets import SecretBindings, SecretReference

ROOT = Path(__file__).resolve().parents[2]
IMAGE_DIGEST = "d" * 64
VARIABLES = {
    "RESEARCH_AGENT_IMAGE_DIGEST": IMAGE_DIGEST,
    "RESEARCH_AGENT_SECRETS": "/guest/secrets",
    "RESEARCH_AGENT_CERTS": "/guest/certs",
    "RESEARCH_AGENT_CONFIG": "/guest/config",
}
_VARIABLE = re.compile(r"(?<!\$)\$\{([A-Z_]+)(?::\?[^}]*)?\}")


def _load(path: Path, variables: dict[str, str]) -> dict[str, Any]:
    text = _VARIABLE.sub(lambda match: variables[match.group(1)], path.read_text())
    document = yaml.safe_load(text)
    assert isinstance(document, dict)
    return document


def _deploy() -> dict[str, Any]:
    return _load(ROOT / "deploy" / "compose.yaml", VARIABLES)


def _memory_gib(value: str) -> float:
    assert value.endswith("g")
    return float(value[:-1])


def test_every_static_role_is_named_once_by_its_label() -> None:
    services = _deploy()["services"]
    inventory = inventory_from_definition(services)
    assert inventory.role_ids == STATIC_ROLE_IDS
    assert len(services) == len(STATIC_ROLE_IDS)


def test_every_application_role_runs_the_one_recorded_image() -> None:
    inventory = inventory_from_definition(_deploy()["services"])
    for role in STATIC_ROLE_IDS - {"postgres"}:
        service = inventory.for_role(role)
        assert service is not None
        assert service.image_digest == IMAGE_DIGEST


def test_inventory_refuses_a_service_without_a_role_label() -> None:
    services = _deploy()["services"]
    del services["reader"]["labels"]
    with pytest.raises(ContractValidationError):
        inventory_from_definition(services)


def test_inventory_refuses_an_image_selected_by_tag() -> None:
    services = _deploy()["services"]
    services["reader"]["image"] = "research-agent:latest"
    with pytest.raises(ContractValidationError):
        inventory_from_definition(services)


def test_inventory_refuses_a_second_container_for_one_role() -> None:
    services = _deploy()["services"]
    services["reader-2"] = dict(services["reader"])
    with pytest.raises(ContractValidationError):
        inventory_from_definition(services)


def test_every_service_has_a_read_only_root_and_a_health_check() -> None:
    for name, service in _deploy()["services"].items():
        assert service["read_only"] is True, name
        assert service["healthcheck"]["test"], name
        assert "/var/run/docker.sock" not in str(service.get("volumes", [])), name


def test_application_health_checks_poll_on_the_supervisor_cadence() -> None:
    for name, service in _deploy()["services"].items():
        if name == "postgres":
            continue
        check = service["healthcheck"]
        assert check["interval"] == f"{POLL_INTERVAL_SECONDS}s", name
        assert check["retries"] == FAILURE_THRESHOLD, name


def test_ceilings_match_the_launch_role_table() -> None:
    for name, service in _deploy()["services"].items():
        role = service["labels"]["research-agent.role"]
        resources = service["deploy"]["resources"]
        limit = ROLE_LIMITS[role]
        assert float(resources["limits"]["cpus"]) == limit.vcpu, name
        assert _memory_gib(resources["limits"]["memory"]) == limit.memory_gib, name
        devices = resources.get("reservations", {}).get("devices", [])
        assert sum(device["count"] for device in devices) == limit.accelerator_count


def test_every_credential_is_a_file_secret_bound_to_one_consumer() -> None:
    document = _deploy()
    declared = document["secrets"]
    by_role: dict[str, tuple[SecretReference, ...]] = {}
    consumed: list[str] = []
    for service in document["services"].values():
        names = service.get("secrets", [])
        consumed.extend(names)
        by_role[service["labels"]["research-agent.role"]] = tuple(
            SecretReference(name, f"/run/secrets/{name}") for name in names
        )
    SecretBindings(by_role)
    assert sorted(consumed) == sorted(declared)
    for name, secret in declared.items():
        assert set(secret) == {"file"}, name
        assert secret["file"].startswith(("/guest/secrets/", "/guest/certs/")), name
        assert not secret["file"].endswith("ca.key"), name


def test_only_postgres_and_storage_share_the_storage_network() -> None:
    document = _deploy()
    assert document["networks"]["storage"] == {"internal": True}
    members = {
        name
        for name, service in document["services"].items()
        if "storage" in service["networks"]
    }
    assert members == {"postgres", "storage"}


def test_only_ingest_and_storage_have_an_internet_route() -> None:
    document = _deploy()
    external = {
        name
        for name, network in document["networks"].items()
        if not network.get("internal")
    }
    assert external == {"egress"}
    members = {
        name
        for name, service in document["services"].items()
        if external & set(service["networks"])
    }
    assert members == {"ingest", "storage"}


def test_the_artifact_volume_is_mounted_into_storage_alone() -> None:
    for name, service in _deploy()["services"].items():
        mounts = [str(volume) for volume in service.get("volumes", [])]
        holds = any(mount.startswith("artifact-data:") for mount in mounts)
        assert holds == (name == "storage"), name


def test_the_boundary_harness_matches_its_deployable_services() -> None:
    harness = _load(
        ROOT / "compose.yaml",
        {
            "RESEARCH_AGENT_STORAGE_CONFIG": "/guest/config/storage.json",
            **{
                f"RESEARCH_AGENT_{name}_FILE": f"/guest/{name.lower()}"
                for name in (
                    "POSTGRES_DATABASE",
                    "POSTGRES_USER",
                    "POSTGRES_PASSWORD",
                    "STORAGE_DSN",
                    "STORAGE_TLS_CERTIFICATE",
                    "STORAGE_TLS_PRIVATE_KEY",
                    "STORAGE_TLS_CLIENT_CA",
                )
            },
        },
    )["services"]
    deployed = _deploy()["services"]
    assert set(harness) == {"postgres", "storage"}
    for name in ("image", "environment", "secrets", "tmpfs", "read_only"):
        assert harness["postgres"][name] == deployed["postgres"][name], name
    for name in ("command", "secrets", "tmpfs", "read_only", "labels"):
        assert harness["storage"][name] == deployed["storage"][name], name
