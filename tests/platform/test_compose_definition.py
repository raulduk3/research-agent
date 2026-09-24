import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from research_agent.contracts.primitives import ContractValidationError
from research_agent.platform.compose import (
    STATIC_ROLE_IDS,
    UNLAUNCHED_PROFILE,
    inventory_from_definition,
)
from research_agent.platform.health import FAILURE_THRESHOLD, POLL_INTERVAL_SECONDS
from research_agent.platform.ingress import (
    INGRESS_PORT,
    PUBLISHABLE_ROLES,
    IngressRefused,
    IngressRoute,
    published_upstreams,
    render_caddyfile,
    verify_published,
)
from research_agent.platform.resources import ROLE_LIMITS
from research_agent.platform.secrets import SecretBindings, SecretReference
from research_agent.platform.startup import ROLE_COMMANDS

ROOT = Path(__file__).resolve().parents[2]
CADDYFILE = ROOT / "deploy" / "ingress" / "Caddyfile"
IMAGE_DIGEST = "d" * 64
VARIABLES = {
    "RESEARCH_AGENT_IMAGE_DIGEST": IMAGE_DIGEST,
    "RESEARCH_AGENT_SECRETS": "/guest/secrets",
    "RESEARCH_AGENT_CERTS": "/guest/certs",
    "RESEARCH_AGENT_CONFIG": "/guest/config",
    "RESEARCH_AGENT_INGRESS_DIGEST": "c" * 64,
    "RESEARCH_AGENT_PUBLIC_HOSTNAME": "owner.example.test",
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
    for role in STATIC_ROLE_IDS - {"postgres", "ingress"}:
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
    assert external == {"egress", "public"}
    members = {
        name
        for name, service in document["services"].items()
        if "egress" in service["networks"]
    }
    assert members == {"ingest", "storage"}


def test_the_ingress_alone_publishes_a_port_and_only_to_loopback() -> None:
    services = _deploy()["services"]
    published = {
        name: service["ports"]
        for name, service in services.items()
        if "ports" in service
    }
    assert published == {"ingress": [f"127.0.0.1:{INGRESS_PORT}:{INGRESS_PORT}"]}
    members = {
        name for name, service in services.items() if "public" in service["networks"]
    }
    assert members == {"ingress"}


def test_every_started_service_runs_a_launcher_that_exists() -> None:
    commands = {*ROLE_COMMANDS, "serve-storage"}
    for name, service in _deploy()["services"].items():
        if name in {"postgres", "ingress"}:
            continue
        if UNLAUNCHED_PROFILE in service.get("profiles", []):
            assert "command" not in service, name
            continue
        assert service["command"][0] in commands, name


def test_inventory_refuses_an_unlaunched_service_that_names_a_command() -> None:
    services = _deploy()["services"]
    services["reader"]["command"] = ["serve-reader"]
    with pytest.raises(ContractValidationError):
        inventory_from_definition(services)


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


def test_the_committed_caddyfile_is_the_rendered_one() -> None:
    assert CADDYFILE.read_text() == render_caddyfile()


def test_the_ingress_publishes_the_owner_app_alone() -> None:
    caddyfile = CADDYFILE.read_text()
    assert published_upstreams(caddyfile) == {"owner"}
    assert verify_published(caddyfile, _deploy()["services"]) == {"owner"}


def test_the_rating_app_is_absent_from_the_published_set() -> None:
    services = _deploy()["services"]
    assert services["app"]["labels"]["research-agent.role"] == "app"
    assert "app" not in PUBLISHABLE_ROLES
    assert "app" not in published_upstreams(CADDYFILE.read_text())


@pytest.mark.parametrize("service", ["app", "storage", "models", "tools", "postgres"])
def test_a_route_to_a_service_without_owner_sessions_is_refused(service: str) -> None:
    caddyfile = render_caddyfile(
        (
            IngressRoute(path="/rate/*", service=service, port=8443),
            IngressRoute(path="/*", service="owner", port=8443),
        )
    )
    with pytest.raises(IngressRefused):
        verify_published(caddyfile, _deploy()["services"])


def test_a_route_to_an_undeclared_service_is_refused() -> None:
    caddyfile = render_caddyfile(
        (IngressRoute(path="/*", service="elsewhere", port=8443),)
    )
    with pytest.raises(IngressRefused):
        verify_published(caddyfile, _deploy()["services"])


def test_an_unreadable_upstream_is_refused_rather_than_skipped() -> None:
    caddyfile = CADDYFILE.read_text().replace(
        "reverse_proxy https://owner:8443", "reverse_proxy {$UPSTREAM}", 1
    )
    with pytest.raises(IngressRefused):
        published_upstreams(caddyfile)


def test_the_ingress_never_terminates_tls_itself() -> None:
    caddyfile = CADDYFILE.read_text()
    assert "auto_https off" in caddyfile
    assert "tls " not in caddyfile.replace("tls_", "")
