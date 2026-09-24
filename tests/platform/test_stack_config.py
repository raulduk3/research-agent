import hashlib
import json
import re
import shutil
import ssl
from pathlib import Path
from typing import Any

import pytest
import yaml

from research_agent.platform.builds import BuildManifest, ImageRecord
from research_agent.platform.compose import inventory_from_definition
from research_agent.platform.services.config import load_launch_config
from research_agent.platform.stack_config import (
    SERVICES,
    StackConfigRefused,
    config_hash,
    generate,
)
from research_agent.platform.storage_service import _capabilities

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy" / "compose.yaml"
INGRESS = "c" * 64
LAUNCHERS = {"ingest": "ingest", "models": "models", "app": "rating", "owner": "owner"}
_VARIABLE = re.compile(r"(?<!\$)\$\{([A-Z_]+)(?::\?[^}]*)?\}")


def _manifest() -> BuildManifest:
    return BuildManifest(
        source_tree_hash="a" * 64,
        python_version="3.12.12",
        tool_versions={"uv": "0.8.22", "docker": "29.8.1"},
        uv_lock_hash="b" * 64,
        base_image_digest="c" * 64,
        base_image_tag="3.12.12-slim-bookworm",
        package_hashes=("d" * 64, "e" * 64),
        model_runtime_identities={"torch": "2.14.0", "transformers": "5.17.0"},
        product_version="0.1.1-main.3+0123abcd",
    )


def _inputs(directory: Path) -> tuple[Path, Path]:
    profile = json.loads(
        (ROOT / "docs/implementation/launch-profile.example.json").read_text()
    )
    profile["host"]["public_hostname"] = "owner.example.test"
    profile_path = directory / "profile.json"
    profile_path.write_text(json.dumps(profile))
    images = directory / "images.json"
    images.write_text(
        ImageRecord(
            image_digest="f" * 64, source_commit="1" * 40, manifest=_manifest()
        ).to_json()
    )
    return profile_path, images


@pytest.fixture(scope="module")
def stack(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, Path]:
    inputs = tmp_path_factory.mktemp("inputs")
    profile, images = _inputs(inputs)
    output = tmp_path_factory.mktemp("stack") / "out"
    generate(
        profile,
        output,
        images_path=images,
        ingress_digest=INGRESS,
        profile_mount=str(output / "config" / "profile.json"),
    )
    return output, profile, images


def _environment(output: Path) -> dict[str, str]:
    lines = (output / "compose.env").read_text().splitlines()
    return dict(line.split("=", 1) for line in lines)


def _compose(output: Path) -> dict[str, Any]:
    environment = _environment(output)
    text = _VARIABLE.sub(lambda match: environment[match.group(1)], COMPOSE.read_text())
    document = yaml.safe_load(text)
    assert isinstance(document, dict)
    return document


def _mounts(output: Path, root: Path) -> Path:
    """Copy every compose secret to where Docker mounts it, under *root*."""

    for name, secret in _compose(output)["secrets"].items():
        target = root / "run" / "secrets" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(secret["file"], target)
        target.chmod(0o600)
    return root


def test_every_launcher_accepts_its_generated_configuration(
    stack: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    output, _, _ = stack
    root = _mounts(output, tmp_path)
    for service, role in LAUNCHERS.items():
        config = load_launch_config(
            output / "config" / f"{service}.json", role, secrets_root=root
        )
        assert config.producer().image_digest == "f" * 64
        if "storage_ca" in config.secrets:
            config.storage_client()
        if "tls_certificate" in config.secrets:
            config.server_tls(client_certificates="tls_client_ca" in config.secrets)


def test_compose_accepts_the_generated_environment_and_every_file_exists(
    stack: tuple[Path, Path, Path],
) -> None:
    output, _, _ = stack
    document = _compose(output)
    inventory = inventory_from_definition(document["services"])
    assert inventory.for_role("storage") is not None
    for name, secret in document["secrets"].items():
        assert Path(secret["file"]).is_file(), name
    for service in document["services"].values():
        for volume in service.get("volumes", []):
            if (
                isinstance(volume, dict)
                and volume.get("type") == "bind"
                and "/run/config/" in volume["target"]
            ):
                assert Path(volume["source"]).is_file(), volume["source"]
    assert (
        _environment(output)["RESEARCH_AGENT_PUBLIC_HOSTNAME"] == "owner.example.test"
    )


def test_each_storage_capability_is_keyed_by_the_issued_certificate(
    stack: tuple[Path, Path, Path],
) -> None:
    output, _, _ = stack
    storage = json.loads((output / "config" / "storage.json").read_text())
    capabilities = _capabilities(storage["capabilities"])
    for service, spec in SERVICES.items():
        der = ssl.PEM_cert_to_DER_cert(
            (output / "certs" / f"{service}-client.pem").read_text()
        )
        capability = capabilities[hashlib.sha256(der).hexdigest()]
        role_file = json.loads((output / "config" / f"{service}.json").read_text())
        assert capability.role == spec.capability_role
        assert capability.scopes == frozenset(spec.scopes)
        assert (
            capability.config_hash == role_file["config_hash"] == config_hash(role_file)
        )
        assert capability.retention_policy_hash == role_file["retention_policy_hash"]
    assert len(capabilities) == len(SERVICES)


def test_models_admits_the_model_clients_by_fingerprint(
    stack: tuple[Path, Path, Path],
) -> None:
    output, _, _ = stack
    fingerprints = json.loads((output / "certs" / "fingerprints.json").read_text())
    models = json.loads((output / "config" / "models.json").read_text())
    assert set(models["client_fingerprints"]) <= set(fingerprints.values())
    assert fingerprints["owner"] not in models["client_fingerprints"]


def test_a_rerun_keeps_certificates_and_secrets_and_changes_nothing(
    stack: tuple[Path, Path, Path],
) -> None:
    output, profile, images = stack
    before = {path: path.read_bytes() for path in output.rglob("*") if path.is_file()}
    report = generate(
        profile,
        output,
        images_path=images,
        ingress_digest=INGRESS,
        profile_mount=str(output / "config" / "profile.json"),
    )
    assert report.changed == []
    assert (
        "certs" in report.unchanged and "secrets/postgres_password" in report.unchanged
    )
    assert {
        path: path.read_bytes() for path in output.rglob("*") if path.is_file()
    } == before


def test_secrets_are_owner_only_and_never_reported(
    stack: tuple[Path, Path, Path],
) -> None:
    output, _, _ = stack
    password = (output / "secrets" / "postgres_password").read_text().strip()
    for path in (output / "secrets").iterdir():
        assert path.stat().st_mode & 0o077 == 0, path
    for path in (output / "config").iterdir():
        assert password not in path.read_text(), path
    assert password in (output / "secrets" / "ingest_database_dsn").read_text()


def test_provider_keys_no_launcher_declares_are_left_out(tmp_path: Path) -> None:
    profile, images = _inputs(tmp_path)
    output = tmp_path / "out"
    report = generate(
        profile,
        output,
        images_path=images,
        ingress_digest=INGRESS,
        environment={"ZAI_API_KEY": "not-a-real-key"},
    )
    assert not (output / "secrets" / "zai_api_key").exists()
    assert any(note.startswith("ZAI_API_KEY") for note in report.notes)
    assert all("not-a-real-key" not in note for note in report.notes)


def test_refuses_an_output_inside_the_repository(tmp_path: Path) -> None:
    profile, images = _inputs(tmp_path)
    with pytest.raises(StackConfigRefused, match="inside the repository"):
        generate(
            profile, ROOT / "stack-out", images_path=images, ingress_digest=INGRESS
        )
    assert not (ROOT / "stack-out").exists()


def test_refuses_a_missing_image_record(tmp_path: Path) -> None:
    profile, _ = _inputs(tmp_path)
    with pytest.raises(StackConfigRefused, match="image record"):
        generate(
            profile,
            tmp_path / "out",
            images_path=tmp_path / "none.json",
            ingress_digest=INGRESS,
        )
    assert not (tmp_path / "out").exists()


def test_refuses_a_profile_that_fails_check_profile(tmp_path: Path) -> None:
    profile, images = _inputs(tmp_path)
    value = json.loads(profile.read_text())
    value["unexpected"] = True
    profile.write_text(json.dumps(value))
    with pytest.raises(StackConfigRefused, match="check-profile"):
        generate(profile, tmp_path / "out", images_path=images, ingress_digest=INGRESS)
