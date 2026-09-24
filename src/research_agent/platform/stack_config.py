"""Write the compose stack's configuration, secrets and certificates (#342).

`generate` turns a checked launch profile and the built image's record into
the three directories `deploy/compose.yaml` mounts and its environment file:

    OUT/certs    bin/issue-certs output, issued once
    OUT/secrets  PostgreSQL credentials and one DSN file per consumer,
                 generated once and reused
    OUT/config   profile.json and one <service>.json per application role,
                 rewritten on every run
    OUT/compose.env

Secret values are written to owner-only files and never returned or printed.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from research_agent.contracts.canonical import canonical_json, sha256_hex
from research_agent.platform.builds import ImageRecord
from research_agent.platform.profile import LaunchProfile
from research_agent.platform.services.config import ROLE_SECRETS

ROOT = Path(__file__).resolve().parents[3]
STORAGE_PORT = 8443
LISTENER_PORT = 8443
CONTRACT_VERSION = 1
ARTIFACT_ROOT = "/var/lib/research-agent/artifacts"
PROFILE_MOUNT = "/run/config/profile.json"
DATABASE = "research_agent"
PROVIDER_KEYS = ("ZAI_API_KEY", "JEV_API_KEY")

_JOBS = ("jobs:claim", "jobs:renew", "jobs:checkpoint", "jobs:complete")
_ARTIFACTS = ("artifacts:publish", "artifacts:read")


@dataclass(frozen=True, slots=True)
class Service:
    """One application service: its launcher role, storage identity and mounts."""

    launcher_role: str
    capability_role: str
    scopes: tuple[str, ...]
    job_kinds: tuple[str, ...] = ()
    database: bool = False
    listener: bool = False


#: Each compose application service, keyed by its service name. Scopes are
#: the storage routes the role's code calls, as `storage/http.py` admits them.
SERVICES: dict[str, Service] = {
    "ingest": Service(
        "ingest",
        "ingest",
        (*_JOBS, *_ARTIFACTS, "paper_requests:read", "paper_requests:transition"),
        ("capture", "assess"),
        database=True,
    ),
    "reader": Service(
        "reader", "reader", (*_JOBS, *_ARTIFACTS, "assessments:read"), ("extract",)
    ),
    "models": Service(
        "models",
        "models",
        (*_JOBS, *_ARTIFACTS),
        ("embed", "fit", "calibrate", "predict"),
        listener=True,
    ),
    "tools": Service(
        "tools",
        "tools",
        (
            *_ARTIFACTS,
            "snapshots:read",
            "runs:specification",
            "runs:submit",
            "paper_requests:record",
            "trace:request",
            "trace:terminal",
        ),
        listener=True,
    ),
    "scorer": Service("scorer", "scorer", (*_JOBS, "artifacts:publish"), ("score",)),
    "orchestrator": Service(
        "orchestrator",
        "orchestrator",
        (
            *_ARTIFACTS,
            "runs:create",
            "runs:append_event",
            "runs:submit",
            "runs:void",
            "runs:worker",
            "snapshots:seal",
            "snapshots:read",
            "sheets:seal",
            "submissions:submit",
            "digests:store",
            "settlements:record",
            "resources:record",
        ),
    ),
    "app": Service(
        "rating",
        "rating_app",
        (
            "digests:read",
            "sheets:seal",
            "submissions:submit",
            "ratings:record",
            "raters:read",
        ),
        listener=True,
    ),
    "owner": Service(
        "owner",
        "owner",
        ("owner:admit", "owner:seed", "owner:retire", "owner:read"),
        database=True,
        listener=True,
    ),
}

#: The services that call the model service; its listener admits these alone.
MODEL_CLIENTS = ("ingest", "reader", "tools", "scorer", "orchestrator")


class StackConfigRefused(ValueError):
    """An input does not admit writing the stack's configuration."""


@dataclass
class Report:
    """What one run wrote; names only, never a secret value."""

    changed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def secret_mounts(service: str) -> dict[str, str]:
    """The secret names *service*'s launcher reads, mapped to their mount paths."""

    spec = SERVICES[service]
    names: dict[str, str] = {}
    if spec.database:
        names["database_dsn"] = f"{service}_database_dsn"
    if spec.listener:
        names["tls_certificate"] = f"{service}_tls_certificate"
        names["tls_private_key"] = f"{service}_tls_private_key"
        if service in ("models", "tools"):
            names["tls_client_ca"] = f"{service}_tls_client_ca"
    names["storage_ca"] = f"{service}_ca"
    names["storage_client_certificate"] = f"{service}_client_certificate"
    names["storage_client_private_key"] = f"{service}_client_private_key"
    return {name: f"/run/secrets/{mount}" for name, mount in names.items()}


def principal_id(capability_role: str) -> str:
    """A stable version-4 UUID per storage role, so reissued certificates keep it."""

    digest = sha256_hex(f"research-agent-principal:{capability_role}".encode())
    return str(uuid.UUID(bytes=bytes.fromhex(digest)[:16], version=4))


def config_hash(values: Mapping[str, Any]) -> str:
    """The hash of a role file over everything but its own ``config_hash``."""

    return sha256_hex(
        canonical_json(
            {key: value for key, value in values.items() if key != "config_hash"}
        )
    )


def retention_policy_hash(profile: LaunchProfile) -> str:
    return sha256_hex(canonical_json(profile.privacy.to_dict()))


def generate(
    profile_path: Path,
    output: Path,
    *,
    images_path: Path,
    ingress_digest: str,
    values: Mapping[str, Mapping[str, Any]] | None = None,
    environment: Mapping[str, str] | None = None,
    profile_mount: str = PROFILE_MOUNT,
) -> Report:
    """Write the whole stack set into *output*; a rerun keeps certs and secrets.

    *values* adds operator-held launcher values per service (the rating
    digest, the ingest day pass's manifest and index identities).
    *profile_mount* is where the launchers read the profile; tests point it
    at the written copy.
    """

    output = output.resolve()
    if output == ROOT or ROOT in output.parents:
        raise StackConfigRefused("the output directory is inside the repository")
    try:
        profile_bytes = profile_path.read_bytes()
        profile = LaunchProfile.from_json(profile_bytes)
    except (OSError, ValueError) as error:
        raise StackConfigRefused(
            f"the launch profile fails check-profile: {error}"
        ) from error
    if not profile.host.public_hostname:
        raise StackConfigRefused("the launch profile has no host.public_hostname")
    try:
        image = ImageRecord.from_json(images_path.read_text())
    except (OSError, ValueError) as error:
        raise StackConfigRefused(f"no usable image record at {images_path}") from error
    if len(ingress_digest) != 64 or any(
        c not in "0123456789abcdef" for c in ingress_digest
    ):
        raise StackConfigRefused("the ingress digest must be a sha256 hex digest")

    report = Report()
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    certs = output / "certs"
    _issue_certs(certs, report)
    fingerprints: dict[str, str] = json.loads((certs / "fingerprints.json").read_text())
    missing = sorted(set(SERVICES) - set(fingerprints))
    if missing:
        raise StackConfigRefused(
            "the issued certificates lack clients: " + ", ".join(missing)
        )
    _write_secrets(output / "secrets", report)
    _provider_keys(output / "secrets", environment or {}, report)

    producer = {
        "image_digest": image.image_digest,
        "source_commit": image.source_commit,
        "contract_version": CONTRACT_VERSION,
    }
    retention = retention_policy_hash(profile)
    config = output / "config"
    config.mkdir(mode=0o700, exist_ok=True)
    _write(config / "profile.json", profile_bytes, report, output)
    profile_hash = profile.compute_hash()
    extra = values or {}
    hashes: dict[str, str] = {}
    for service, spec in SERVICES.items():
        document = _role_values(service, spec, profile, fingerprints)
        document.update(
            role=spec.launcher_role,
            profile_file=profile_mount,
            profile_hash=profile_hash,
            producer=producer,
            retention_policy_hash=retention,
            secrets=secret_mounts(service),
            storage={
                "host": "storage",
                "port": STORAGE_PORT,
                "server_name": "storage",
                "scopes": list(spec.scopes),
            },
        )
        document.update(extra.get(service, {}))
        document["config_hash"] = hashes[service] = config_hash(document)
        _write(config / f"{service}.json", _json(document), report, output)
        for key in _missing_launcher_values(service, document):
            report.notes.append(
                f"{service}.json has no {key}; its launcher refuses until one is set"
            )

    storage: dict[str, Any] = {
        "database_dsn_file": "/run/secrets/storage_dsn",
        "artifact_root": ARTIFACT_ROOT,
        "schema": DATABASE,
        "host": "0.0.0.0",
        "port": STORAGE_PORT,
        "tls": {
            "certificate_file": "/run/secrets/storage_tls_certificate",
            "private_key_file": "/run/secrets/storage_tls_private_key",
            "client_ca_file": "/run/secrets/storage_tls_client_ca",
        },
        "producer": producer,
        "retention_policy_hash": retention,
        "capabilities": {
            fingerprints[service]: {
                "principal_id": principal_id(spec.capability_role),
                "role": spec.capability_role,
                "scopes": sorted(spec.scopes),
                "job_kinds": sorted(spec.job_kinds),
                "producer_version": producer,
                "config_hash": hashes[service],
                "retention_policy_hash": retention,
            }
            for service, spec in SERVICES.items()
        },
    }
    storage.update(extra.get("storage", {}))
    storage["config_hash"] = config_hash(storage)
    _write(config / "storage.json", _json(storage), report, output)

    env = {
        "RESEARCH_AGENT_IMAGE_DIGEST": image.image_digest,
        "RESEARCH_AGENT_INGRESS_DIGEST": ingress_digest,
        "RESEARCH_AGENT_PUBLIC_HOSTNAME": profile.host.public_hostname,
        "RESEARCH_AGENT_CONFIG": str(config),
        "RESEARCH_AGENT_SECRETS": str(output / "secrets"),
        "RESEARCH_AGENT_CERTS": str(certs),
    }
    text = "".join(f"{key}={value}\n" for key, value in env.items())
    _write(output / "compose.env", text.encode(), report, output)
    return report


def _role_values(
    service: str, spec: Service, profile: LaunchProfile, fingerprints: Mapping[str, str]
) -> dict[str, Any]:
    document: dict[str, Any] = {}
    if spec.listener:
        document.update(host="0.0.0.0", port=LISTENER_PORT)
    if service == "models":
        document["client_fingerprints"] = sorted(
            fingerprints[client] for client in MODEL_CLIENTS
        )
    elif service == "owner":
        document.update(
            artifact_root=ARTIFACT_ROOT,
            public_hostname=profile.host.public_hostname,
            front_end_origin=profile.host.front_end_origin,
        )
    elif service == "ingest":
        document.update(state_dir="/tmp/research-agent/ingest", images={})
    return document


def _missing_launcher_values(service: str, document: Mapping[str, Any]) -> list[str]:
    required = {
        "app": ("digest", "public_origin"),
        "ingest": ("agent_model_manifest", "index_identities"),
    }.get(service, ())
    return [key for key in required if key not in document]


def _issue_certs(certs: Path, report: Report) -> None:
    if (certs / "fingerprints.json").exists():
        report.unchanged.append("certs")
        return
    result = subprocess.run(
        (str(ROOT / "bin" / "issue-certs"), str(certs)),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise StackConfigRefused(f"bin/issue-certs failed: {result.stderr.strip()}")
    report.changed.append("certs")


def _write_secrets(directory: Path, report: Report) -> None:
    directory.mkdir(mode=0o700, exist_ok=True)
    fixed = {"postgres_database": DATABASE, "postgres_user": DATABASE}
    for name, value in fixed.items():
        _secret(directory / name, value, report)
    _secret(directory / "postgres_password", secrets.token_urlsafe(32), report)
    user = (directory / "postgres_user").read_text().strip()
    password = (directory / "postgres_password").read_text().strip()
    database = (directory / "postgres_database").read_text().strip()
    dsn = f"postgresql://{user}:{password}@postgres:5432/{database}"
    for name in ("storage_dsn", "ingest_database_dsn", "owner_database_dsn"):
        _secret(directory / name, dsn, report)


def _provider_keys(
    directory: Path, environment: Mapping[str, str], report: Report
) -> None:
    declared = set().union(*ROLE_SECRETS.values())
    for key in PROVIDER_KEYS:
        name = key.lower()
        if name not in declared:
            report.notes.append(
                f"{key}: no launcher declares a {name} secret; the run command "
                "reads it from its own environment"
            )
        elif environment.get(key):
            _secret(directory / name, environment[key], report)
        else:
            report.notes.append(f"{key} is unset; {name} was not written")


def _secret(path: Path, value: str, report: Report) -> None:
    label = f"secrets/{path.name}"
    if path.exists() and path.read_text().strip():
        report.unchanged.append(label)
        return
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(value + "\n")
    path.chmod(0o600)
    report.changed.append(label)


def _write(path: Path, content: bytes, report: Report, output: Path) -> None:
    label = str(path.relative_to(output))
    if path.exists() and path.read_bytes() == content:
        report.unchanged.append(label)
        return
    path.write_bytes(content)
    path.chmod(0o600)
    report.changed.append(label)


def _json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def commands(output: Path) -> list[str]:
    """The operator lines that start the stack from what `generate` wrote."""

    env = f"{output}/compose.env"
    return [
        f"docker compose --env-file {env} -f deploy/compose.yaml up -d postgres",
        f'RESEARCH_AGENT_STORAGE_DSN="$(cat {output}/secrets/storage_dsn)" '
        "uv run --locked python -m research_agent migrate",
        f'RESEARCH_AGENT_STORAGE_DSN="$(cat {output}/secrets/storage_dsn)" '
        "uv run --locked python -m research_agent check-schema",
        "uv run --locked python -m research_agent provision-launch-roles "
        "--config /absolute/path/roles.json",
        f"docker compose --env-file {env} -f deploy/compose.yaml up -d",
    ]


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("profile", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--images", type=Path, default=ROOT / "deploy" / "images.json")
    parser.add_argument("--ingress-digest", required=True)
    parser.add_argument(
        "--values",
        type=Path,
        help="JSON object of per-service launcher values merged into each role file",
    )
    args = parser.parse_args(argv)
    try:
        extra = json.loads(args.values.read_text()) if args.values else None
        report = generate(
            args.profile,
            args.output,
            images_path=args.images,
            ingress_digest=args.ingress_digest,
            values=extra,
            environment=os.environ,
        )
    except (StackConfigRefused, OSError, json.JSONDecodeError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    for label in report.changed:
        print(f"wrote {label}")
    for label in report.unchanged:
        print(f"kept {label}")
    for note in report.notes:
        print(f"note: {note}")
    for line in commands(args.output.resolve()):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
