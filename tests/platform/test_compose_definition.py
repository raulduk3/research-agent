import hashlib
import json
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
    SERVICE_ROLES,
    IngressRefused,
    IngressRoute,
    published_upstreams,
    render_caddyfile,
    verify_published,
    verify_tunnel_terminates_tls,
)
from research_agent.platform.resources import ROLE_LIMITS
from research_agent.platform.secrets import SecretBindings, SecretReference
from research_agent.platform.stack_config import (
    INGEST_STATE_DIR,
    MODEL_CLIENTS,
    MODELS_PROFILE,
)
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
    "RESEARCH_AGENT_MODELS_HOST_ALIAS": "host.docker.internal",
}
_VARIABLE = re.compile(r"(?<!\$)\$\{([A-Z_]+)(?::\?[^}]*)?\}")

# The registry's OCI image index for postgres:17.11, byte for byte as served;
# its SHA-256 is the digest both Compose files pin.
_POSTGRES_INDEX = (
    r'{"manifests":[{"annotations":{"com.docker.official-images.bashbrew.arch":"amd64"'
    r',"org.opencontainers.image.base.digest":"sha256:7792b1f7702a86946cd518db72b6a407'
    r'302c3e9bc1635634368b878189e8221c","org.opencontainers.image.base.name":"debian:t'
    r'rixie-slim","org.opencontainers.image.created":"2026-09-19T00:35:55Z","org.openc'
    r'ontainers.image.revision":"2603e26e245e558218728ee14e0a42dcb020dc7f","org.openco'
    r'ntainers.image.source":"https:\/\/github.com\/docker-library\/postgres.git#2603e'
    r'26e245e558218728ee14e0a42dcb020dc7f:17\/trixie","org.opencontainers.image.url":"'
    r'https:\/\/hub.docker.com\/_\/postgres","org.opencontainers.image.version":"17.11'
    r'"},"digest":"sha256:e31e3d5327d1806f6177827c9710643e4f35f7ab3f14d26d05332753d3e9'
    r'5ee0","mediaType":"application\/vnd.oci.image.manifest.v1+json","platform":{"arc'
    r'hitecture":"amd64","os":"linux"},"size":3628},{"annotations":{"com.docker.offici'
    r'al-images.bashbrew.arch":"amd64","vnd.docker.reference.digest":"sha256:e31e3d532'
    r'7d1806f6177827c9710643e4f35f7ab3f14d26d05332753d3e95ee0","vnd.docker.reference.t'
    r'ype":"attestation-manifest"},"digest":"sha256:2ca48abe6ef9fb9fda600a9198bddb1478'
    r'4a87cd653a364631916831168b938f","mediaType":"application\/vnd.oci.image.manifest'
    r'.v1+json","platform":{"architecture":"unknown","os":"unknown"},"size":841},{"ann'
    r'otations":{"com.docker.official-images.bashbrew.arch":"arm32v5","org.opencontain'
    r'ers.image.base.digest":"sha256:3405f5ef07b562ef1977c29a729f4b800f5565c96c7c75937'
    r'80ac3729029f9f8","org.opencontainers.image.base.name":"debian:trixie-slim","org.'
    r'opencontainers.image.created":"2026-09-19T00:41:08Z","org.opencontainers.image.r'
    r'evision":"2603e26e245e558218728ee14e0a42dcb020dc7f","org.opencontainers.image.so'
    r'urce":"https:\/\/github.com\/docker-library\/postgres.git#2603e26e245e558218728e'
    r'e14e0a42dcb020dc7f:17\/trixie","org.opencontainers.image.url":"https:\/\/hub.doc'
    r'ker.com\/_\/postgres","org.opencontainers.image.version":"17.11"},"digest":"sha2'
    r'56:9b6d2e9b55335c9909a929c463a906a82a5cc9cf4302f87c44269c1aa4173d47","mediaType"'
    r':"application\/vnd.oci.image.manifest.v1+json","platform":{"architecture":"arm",'
    r'"os":"linux","variant":"v5"},"size":3629},{"annotations":{"com.docker.official-i'
    r'mages.bashbrew.arch":"arm32v5","vnd.docker.reference.digest":"sha256:9b6d2e9b553'
    r'35c9909a929c463a906a82a5cc9cf4302f87c44269c1aa4173d47","vnd.docker.reference.typ'
    r'e":"attestation-manifest"},"digest":"sha256:9ed0d522a7775bef984ee7620b5a3da8a0fa'
    r'40f8e472a400b3969d41bd8644a0","mediaType":"application\/vnd.oci.image.manifest.v'
    r'1+json","platform":{"architecture":"unknown","os":"unknown"},"size":841},{"annot'
    r'ations":{"com.docker.official-images.bashbrew.arch":"arm32v7","org.opencontainer'
    r's.image.base.digest":"sha256:36fb0164b892c70d3f7e84d2650f0550276f6099381cce5f2d1'
    r'5de87271709f4","org.opencontainers.image.base.name":"debian:trixie-slim","org.op'
    r'encontainers.image.created":"2026-09-19T01:12:59Z","org.opencontainers.image.rev'
    r'ision":"2603e26e245e558218728ee14e0a42dcb020dc7f","org.opencontainers.image.sour'
    r'ce":"https:\/\/github.com\/docker-library\/postgres.git#2603e26e245e558218728ee1'
    r'4e0a42dcb020dc7f:17\/trixie","org.opencontainers.image.url":"https:\/\/hub.docke'
    r'r.com\/_\/postgres","org.opencontainers.image.version":"17.11"},"digest":"sha256'
    r':b635c790d35ec6ca6b2ad7ce115c6e2500610168b236b7ced090b53cae837a3c","mediaType":"'
    r'application\/vnd.oci.image.manifest.v1+json","platform":{"architecture":"arm","o'
    r's":"linux","variant":"v7"},"size":3629},{"annotations":{"com.docker.official-ima'
    r'ges.bashbrew.arch":"arm32v7","vnd.docker.reference.digest":"sha256:b635c790d35ec'
    r'6ca6b2ad7ce115c6e2500610168b236b7ced090b53cae837a3c","vnd.docker.reference.type"'
    r':"attestation-manifest"},"digest":"sha256:e84821b83861dcdc2c1abb7d4be0c2e21cd59e'
    r'd33eba6da965492ff2285ba603","mediaType":"application\/vnd.oci.image.manifest.v1+'
    r'json","platform":{"architecture":"unknown","os":"unknown"},"size":841},{"annotat'
    r'ions":{"com.docker.official-images.bashbrew.arch":"arm64v8","org.opencontainers.'
    r'image.base.digest":"sha256:da496358bd6934d2bd6a563a33176a2e50eff5490c54b4ac6fb05'
    r'1b69fef4071","org.opencontainers.image.base.name":"debian:trixie-slim","org.open'
    r'containers.image.created":"2026-09-19T00:38:22Z","org.opencontainers.image.revis'
    r'ion":"2603e26e245e558218728ee14e0a42dcb020dc7f","org.opencontainers.image.source'
    r'":"https:\/\/github.com\/docker-library\/postgres.git#2603e26e245e558218728ee14e'
    r'0a42dcb020dc7f:17\/trixie","org.opencontainers.image.url":"https:\/\/hub.docker.'
    r'com\/_\/postgres","org.opencontainers.image.version":"17.11"},"digest":"sha256:8'
    r'6fa57b44a1d38f09970f64ac71eb492f7a9cf94d08b85e1c8f07bb0fc0a1761","mediaType":"ap'
    r'plication\/vnd.oci.image.manifest.v1+json","platform":{"architecture":"arm64","o'
    r's":"linux","variant":"v8"},"size":3630},{"annotations":{"com.docker.official-ima'
    r'ges.bashbrew.arch":"arm64v8","vnd.docker.reference.digest":"sha256:86fa57b44a1d3'
    r'8f09970f64ac71eb492f7a9cf94d08b85e1c8f07bb0fc0a1761","vnd.docker.reference.type"'
    r':"attestation-manifest"},"digest":"sha256:32350a9fb589b9fd6648d8dd9ed3a8871f0f8c'
    r'8734f1db3e72e94e458c4c2c11","mediaType":"application\/vnd.oci.image.manifest.v1+'
    r'json","platform":{"architecture":"unknown","os":"unknown"},"size":841},{"annotat'
    r'ions":{"com.docker.official-images.bashbrew.arch":"i386","org.opencontainers.ima'
    r'ge.base.digest":"sha256:925b2e26c366e1666a32f47809d3428de3db478ea5ef6bcd73c3d54a'
    r'415c9285","org.opencontainers.image.base.name":"debian:trixie-slim","org.opencon'
    r'tainers.image.created":"2026-09-19T00:38:52Z","org.opencontainers.image.revision'
    r'":"2603e26e245e558218728ee14e0a42dcb020dc7f","org.opencontainers.image.source":"'
    r"https:\/\/github.com\/docker-library\/postgres.git#2603e26e245e558218728ee14e0a4"
    r'2dcb020dc7f:17\/trixie","org.opencontainers.image.url":"https:\/\/hub.docker.com'
    r'\/_\/postgres","org.opencontainers.image.version":"17.11"},"digest":"sha256:8e61'
    r'732943bd1812876cedbc1219744e1f741d41bc3929ed1dd9f0fd9b334a50","mediaType":"appli'
    r'cation\/vnd.oci.image.manifest.v1+json","platform":{"architecture":"386","os":"l'
    r'inux"},"size":3626},{"annotations":{"com.docker.official-images.bashbrew.arch":"'
    r'i386","vnd.docker.reference.digest":"sha256:8e61732943bd1812876cedbc1219744e1f74'
    r'1d41bc3929ed1dd9f0fd9b334a50","vnd.docker.reference.type":"attestation-manifest"'
    r'},"digest":"sha256:17c1d3a29c6dfec97603c0b0d5d3925307a947c491fbcb015aba7291b0513'
    r'da3","mediaType":"application\/vnd.oci.image.manifest.v1+json","platform":{"arch'
    r'itecture":"unknown","os":"unknown"},"size":841},{"annotations":{"com.docker.offi'
    r'cial-images.bashbrew.arch":"ppc64le","org.opencontainers.image.base.digest":"sha'
    r'256:d7dc605ae51866ab640be68806bb01896966ef6089ddf1861a1b758774903c7c","org.openc'
    r'ontainers.image.base.name":"debian:trixie-slim","org.opencontainers.image.create'
    r'd":"2026-09-19T02:52:18Z","org.opencontainers.image.revision":"2603e26e245e55821'
    r'8728ee14e0a42dcb020dc7f","org.opencontainers.image.source":"https:\/\/github.com'
    r"\/docker-library\/postgres.git#2603e26e245e558218728ee14e0a42dcb020dc7f:17\/trix"
    r'ie","org.opencontainers.image.url":"https:\/\/hub.docker.com\/_\/postgres","org.'
    r'opencontainers.image.version":"17.11"},"digest":"sha256:5902b512844acd01fad56673'
    r'98e6e24e730406c7bcf0b748bb38d0182f71003c","mediaType":"application\/vnd.oci.imag'
    r'e.manifest.v1+json","platform":{"architecture":"ppc64le","os":"linux"},"size":36'
    r'30},{"annotations":{"com.docker.official-images.bashbrew.arch":"ppc64le","vnd.do'
    r'cker.reference.digest":"sha256:5902b512844acd01fad5667398e6e24e730406c7bcf0b748b'
    r'b38d0182f71003c","vnd.docker.reference.type":"attestation-manifest"},"digest":"s'
    r'ha256:1703de522c0456d074966a27ac1d189cbb90777eec371d3d9f0c508290a1d729","mediaTy'
    r'pe":"application\/vnd.oci.image.manifest.v1+json","platform":{"architecture":"un'
    r'known","os":"unknown"},"size":841},{"annotations":{"com.docker.official-images.b'
    r'ashbrew.arch":"riscv64","org.opencontainers.image.base.digest":"sha256:fea8b6ee7'
    r'f2ce6ac14cc629f0c4af17df0d33a6796798a0c73a9e44eb4ddbb9a","org.opencontainers.ima'
    r'ge.base.name":"debian:trixie-slim","org.opencontainers.image.created":"2026-08-2'
    r'6T16:20:07Z","org.opencontainers.image.revision":"2603e26e245e558218728ee14e0a42'
    r'dcb020dc7f","org.opencontainers.image.source":"https:\/\/github.com\/docker-libr'
    r'ary\/postgres.git#2603e26e245e558218728ee14e0a42dcb020dc7f:17\/trixie","org.open'
    r'containers.image.url":"https:\/\/hub.docker.com\/_\/postgres","org.opencontainer'
    r's.image.version":"17.11"},"digest":"sha256:cbc6b27fc0a255576fd004f1334ea16f7b5b0'
    r'65c368e721d6fb9c8417e404570","mediaType":"application\/vnd.oci.image.manifest.v1'
    r'+json","platform":{"architecture":"riscv64","os":"linux"},"size":3629},{"annotat'
    r'ions":{"com.docker.official-images.bashbrew.arch":"riscv64","vnd.docker.referenc'
    r'e.digest":"sha256:cbc6b27fc0a255576fd004f1334ea16f7b5b065c368e721d6fb9c8417e4045'
    r'70","vnd.docker.reference.type":"attestation-manifest"},"digest":"sha256:bf88233'
    r'4b82a7bf155029b198b584dced38421a7e48fc561494a0020900dfdd8","mediaType":"applicat'
    r'ion\/vnd.oci.image.manifest.v1+json","platform":{"architecture":"unknown","os":"'
    r'unknown"},"size":841},{"annotations":{"com.docker.official-images.bashbrew.arch"'
    r':"s390x","org.opencontainers.image.base.digest":"sha256:c0519c2c1a61f37ec112cd0a'
    r'4ee700071b1067b59c3b4409726975aeb5b9ebc9","org.opencontainers.image.base.name":"'
    r'debian:trixie-slim","org.opencontainers.image.created":"2026-09-19T00:40:03Z","o'
    r'rg.opencontainers.image.revision":"2603e26e245e558218728ee14e0a42dcb020dc7f","or'
    r'g.opencontainers.image.source":"https:\/\/github.com\/docker-library\/postgres.g'
    r'it#2603e26e245e558218728ee14e0a42dcb020dc7f:17\/trixie","org.opencontainers.imag'
    r'e.url":"https:\/\/hub.docker.com\/_\/postgres","org.opencontainers.image.version'
    r'":"17.11"},"digest":"sha256:33b944ae19be3c19293d7592789c56a6c7808b552a38e78e4409'
    r'04a57d19d570","mediaType":"application\/vnd.oci.image.manifest.v1+json","platfor'
    r'm":{"architecture":"s390x","os":"linux"},"size":3628},{"annotations":{"com.docke'
    r'r.official-images.bashbrew.arch":"s390x","vnd.docker.reference.digest":"sha256:3'
    r'3b944ae19be3c19293d7592789c56a6c7808b552a38e78e440904a57d19d570","vnd.docker.ref'
    r'erence.type":"attestation-manifest"},"digest":"sha256:e2b19c8069f8e33f1042c22d5b'
    r'5b9c8aeb0f49d4e0333e3037f79919f30aba7c","mediaType":"application\/vnd.oci.image.'
    r'manifest.v1+json","platform":{"architecture":"unknown","os":"unknown"},"size":84'
    r'1}],"mediaType":"application\/vnd.oci.image.index.v1+json","schemaVersion":2}'
)


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


def test_the_database_network_holds_exactly_the_database_secret_holders() -> None:
    document = _deploy()
    services = document["services"]
    networks = set(services["postgres"]["networks"])
    assert networks == {"storage"}
    assert document["networks"]["storage"] == {"internal": True}
    holders = {
        name
        for name, service in services.items()
        if any(secret.endswith("dsn") for secret in service.get("secrets", []))
    }
    assert holders == {"storage", "ingest", "owner"}
    members = {
        name
        for name, service in services.items()
        if name != "postgres" and networks & set(service["networks"])
    }
    assert members == holders


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


def test_the_ingest_state_dir_lies_on_a_volume_mounted_into_ingest_alone() -> None:
    # Under the container's /tmp tmpfs the watermark died with the container.
    definition = _deploy()
    assert "ingest-state" in definition["volumes"]
    for name, service in definition["services"].items():
        targets = [
            str(volume).removeprefix("ingest-state:")
            for volume in service.get("volumes", [])
            if str(volume).startswith("ingest-state:")
        ]
        if name != "ingest":
            assert not targets, name
            continue
        assert len(targets) == 1
        assert Path(INGEST_STATE_DIR).is_relative_to(targets[0])


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


def test_postgres_is_pinned_to_its_multi_platform_index() -> None:
    image = _deploy()["services"]["postgres"]["image"]
    name, _, digest = image.partition("@sha256:")
    assert name == "postgres:17.11"
    assert hashlib.sha256(_POSTGRES_INDEX.encode()).hexdigest() == digest
    index = json.loads(_POSTGRES_INDEX)
    assert index["mediaType"] == "application/vnd.oci.image.index.v1+json"
    platforms = {
        (entry["platform"]["os"], entry["platform"]["architecture"])
        for entry in index["manifests"]
    }
    assert {("linux", "amd64"), ("linux", "arm64")} <= platforms


def _labelled_roles() -> dict[str, str]:
    return {
        name: service["labels"]["research-agent.role"]
        for name, service in _deploy()["services"].items()
    }


def test_every_service_is_named_for_the_role_its_label_declares() -> None:
    assert _labelled_roles() == dict(SERVICE_ROLES)


def test_the_committed_caddyfile_is_the_rendered_one() -> None:
    assert CADDYFILE.read_text() == render_caddyfile()


def test_the_ingress_publishes_the_owner_app_alone() -> None:
    caddyfile = CADDYFILE.read_text()
    assert published_upstreams(caddyfile) == {"owner"}
    assert verify_published(caddyfile, _labelled_roles()) == {"owner"}


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
        verify_published(caddyfile, _labelled_roles())


def test_a_route_to_an_undeclared_service_is_refused() -> None:
    caddyfile = render_caddyfile(
        (IngressRoute(path="/*", service="elsewhere", port=8443),)
    )
    with pytest.raises(IngressRefused):
        verify_published(caddyfile, _labelled_roles())


def test_an_unreadable_upstream_is_refused_rather_than_skipped() -> None:
    caddyfile = CADDYFILE.read_text().replace(
        "reverse_proxy https://owner:8443", "reverse_proxy {$UPSTREAM}", 1
    )
    with pytest.raises(IngressRefused):
        published_upstreams(caddyfile)


def _started(services: dict[str, Any], active: set[str]) -> set[str]:
    """The services `docker compose up` starts with *active* profiles on."""

    return {
        name
        for name, service in services.items()
        if not service.get("profiles") or active & set(service["profiles"])
    }


def test_the_model_container_starts_only_under_its_profile() -> None:
    services = _deploy()["services"]
    assert services["models"]["profiles"] == [MODELS_PROFILE]
    assert "models" not in _started(services, set())
    assert "models" in _started(services, {MODELS_PROFILE})
    assert _started(services, {MODELS_PROFILE}) - _started(services, set()) == {
        "models"
    }
    # The container keeps its graphics reservation where the profile runs it.
    devices = services["models"]["deploy"]["resources"]["reservations"]["devices"]
    assert devices == [{"capabilities": ["gpu"], "count": 1}]


def test_native_model_clients_resolve_models_to_the_host_gateway() -> None:
    native = _load(
        ROOT / "deploy" / "compose.yaml",
        {**VARIABLES, "RESEARCH_AGENT_MODELS_HOST_ALIAS": "models"},
    )["services"]
    assert "models" not in _started(native, set())
    for name, service in native.items():
        expected = ["models:host-gateway"] if name in MODEL_CLIENTS else None
        assert service.get("extra_hosts") == expected, name
    # In container mode the mapping names another host, so the clients'
    # lookup of `models` reaches the container rather than /etc/hosts.
    for name in MODEL_CLIENTS:
        assert _deploy()["services"][name]["extra_hosts"] == [
            "host.docker.internal:host-gateway"
        ]


def test_the_ingress_never_terminates_tls_itself() -> None:
    caddyfile = CADDYFILE.read_text()
    verify_tunnel_terminates_tls(caddyfile)
    for edited in (
        caddyfile.replace("\tauto_https off\n", ""),
        caddyfile.replace("http://{$", "https://{$", 1),
        caddyfile.replace("\tlog {", "\ttls internal\n\tlog {", 1),
    ):
        with pytest.raises(IngressRefused):
            verify_tunnel_terminates_tls(edited)
