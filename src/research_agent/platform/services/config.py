"""The one configuration reader every role launcher starts from (#315)."""

from __future__ import annotations

import json
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from research_agent.contracts.primitives import ContractValidationError, ProducerVersion
from research_agent.platform.profile import LaunchProfile
from research_agent.platform.secrets import (
    SecretBindingError,
    SecretReference,
    SecretUnavailable,
    describe_error,
    verify_mounted_secrets,
)
from research_agent.storage.client import StorageClient

#: The secrets each role must declare; a launcher refuses to start without them.
ROLE_SECRETS: dict[str, frozenset[str]] = {
    "models": frozenset({"tls_certificate", "tls_private_key", "tls_client_ca"}),
    "owner": frozenset(
        {
            "database_dsn",
            "tls_certificate",
            "tls_private_key",
            "storage_ca",
            "storage_client_certificate",
            "storage_client_private_key",
        }
    ),
    "rating": frozenset(
        {
            "tls_certificate",
            "tls_private_key",
            "storage_ca",
            "storage_client_certificate",
            "storage_client_private_key",
        }
    ),
    "ingest": frozenset({"database_dsn"}),
    "roles": frozenset({"database_dsn"}),
}


class LaunchRefused(ValueError):
    """A launcher's configuration, profile or secrets do not admit a start."""


@dataclass(frozen=True, slots=True)
class LaunchConfig:
    """One role's checked configuration, profile and secret file references.

    ``secrets_root`` relocates ``/run/secrets/`` for a test that cannot
    write there; a deployment leaves it unset.
    """

    role: str
    values: dict[str, Any]
    profile: LaunchProfile
    profile_file: Path
    secrets: dict[str, Path]

    def secret_path(self, name: str) -> Path:
        return self.secrets[name]

    def secret_text(self, name: str) -> str:
        value = self.secrets[name].read_text().strip()
        if not value:
            raise LaunchRefused(f"secret_reference={name}")
        return value

    def text(self, key: str, *, section: str | None = None) -> str:
        return _text(self.values if section is None else self.mapping(section), key)

    def integer(self, key: str) -> int:
        return _integer(self.values, key)

    def mapping(self, key: str) -> dict[str, Any]:
        return _mapping(self.values, key)

    def producer(self) -> ProducerVersion:
        """The producer this role stamps on what it records, as storage's config names it."""

        producer = self.mapping("producer")
        return ProducerVersion(
            _text(producer, "image_digest"),
            _text(producer, "source_commit"),
            _integer(producer, "contract_version"),
        )

    def server_tls(self, *, client_certificates: bool) -> ssl.SSLContext:
        """This role's listener context; mutual TLS when *client_certificates*."""

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(
            self.secret_path("tls_certificate"), self.secret_path("tls_private_key")
        )
        if client_certificates:
            context.load_verify_locations(self.secret_path("tls_client_ca"))
            context.verify_mode = ssl.CERT_REQUIRED
        return context

    def storage_client(self) -> StorageClient:
        """The role's scope-restricted mTLS client to the storage service."""

        storage = self.mapping("storage")
        timeout = storage.get("timeout_seconds", 30.0)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise LaunchRefused("storage.timeout_seconds must be a number")
        return StorageClient(
            connect_host=_text(storage, "host"),
            port=_integer(storage, "port"),
            server_hostname=_text(storage, "server_name"),
            ca_file=self.secret_path("storage_ca"),
            client_cert_file=self.secret_path("storage_client_certificate"),
            client_key_file=self.secret_path("storage_client_private_key"),
            scopes=frozenset(_strings(storage, "scopes")),
            timeout_seconds=float(timeout),
        )


def load_launch_config(
    path: Path, role: str, *, secrets_root: Path | None = None
) -> LaunchConfig:
    """Read *path* for *role*, refusing before anything is started.

    Refuses a configuration declared for another role, a launch profile that
    is unreadable or whose hash is not the declared ``profile_hash``, and a
    missing, empty or too-broadly readable secret. A refusal names the key
    or secret reference, never a secret's value.
    """

    required = ROLE_SECRETS[role]
    values = _read_json(path, "launch configuration")
    if values.get("role") != role:
        raise LaunchRefused(f"configuration is not declared for role {role!r}")
    profile_file = Path(_text(values, "profile_file"))
    try:
        profile = LaunchProfile.from_json(profile_file.read_bytes())
    except (OSError, ContractValidationError, ValueError) as error:
        raise LaunchRefused("launch profile is unreadable") from error
    if profile.compute_hash() != _text(values, "profile_hash"):
        raise LaunchRefused("launch profile does not match profile_hash")
    declared = _mapping(values, "secrets")
    missing = sorted(required - set(declared))
    if missing:
        raise LaunchRefused("undeclared secrets: " + ", ".join(missing))
    try:
        references = tuple(
            SecretReference(name, _text(declared, name)) for name in sorted(required)
        )
        verify_mounted_secrets(references, root=secrets_root)
    except SecretUnavailable as error:
        raise LaunchRefused(describe_error(error)) from error
    except SecretBindingError as error:
        raise LaunchRefused(str(error)) from error
    return LaunchConfig(
        role=role,
        values=values,
        profile=profile,
        profile_file=profile_file,
        secrets={
            reference.name: _resolve(reference.mount_path, secrets_root)
            for reference in references
        },
    )


def _resolve(mount_path: str, root: Path | None) -> Path:
    return Path(mount_path) if root is None else root / mount_path.lstrip("/")


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise LaunchRefused(f"{label} is unreadable") from error
    if not isinstance(value, dict):
        raise LaunchRefused(f"{label} must be an object")
    return value


def _mapping(value: dict[str, Any], key: str) -> dict[str, Any]:
    result = value.get(key)
    if not isinstance(result, dict):
        raise LaunchRefused(f"{key} must be an object")
    return result


def _text(value: dict[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise LaunchRefused(f"{key} must be a nonempty string")
    return result


def _integer(value: dict[str, Any], key: str) -> int:
    result = value.get(key)
    if isinstance(result, bool) or not isinstance(result, int):
        raise LaunchRefused(f"{key} must be an integer")
    return result


def _strings(value: dict[str, Any], key: str) -> list[str]:
    result = value.get(key)
    if not isinstance(result, list) or not all(
        isinstance(item, str) for item in result
    ):
        raise LaunchRefused(f"{key} must be a string list")
    return result
