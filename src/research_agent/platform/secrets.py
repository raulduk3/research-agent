"""Runtime-only scoped secret files (SDD-PL-07).

A deployment binding names a credential by reference, never by value; the
platform hands the referenced file to the one container that consumes it at
container start. Nothing here ever holds or logs a secret's plaintext value:
`SecretReference` carries a name and a mount path only, and `describe_error`
reports the reference id alone. `scan_for_secret_values` is the reusable
detector the host-acceptance probe runs against built image layers, image
history, build context and rendered Compose output, exercised with synthetic
credentials that are never a real production value.
"""

from __future__ import annotations

import stat
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

_ALLOWED_MODE_BITS = stat.S_IRUSR | stat.S_IWUSR


class SecretBindingError(ValueError):
    """Raised for a malformed binding; never carries a secret value."""


class SecretUnavailable(RuntimeError):
    """Raised when a bound secret file is missing or insufficiently scoped."""

    def __init__(self, reference_name: str, reason: str) -> None:
        super().__init__(f"secret '{reference_name}' is unavailable: {reason}")
        self.reference_name = reference_name


@dataclass(frozen=True, slots=True)
class SecretReference:
    """Names a credential by reference; it never carries the credential value."""

    name: str
    mount_path: str

    def __post_init__(self) -> None:
        if not self.name or "\x00" in self.name:
            raise SecretBindingError("secret reference name must be nonempty text")
        if not self.mount_path.startswith("/run/secrets/"):
            raise SecretBindingError("secret reference must mount under /run/secrets/")


@dataclass(frozen=True, slots=True)
class SecretBindings:
    """The secret references one deployment declares, one consumer role each.

    A reference name may be bound to only one consumer role, matching the
    single-consumer runtime-secret-file mount the requirement fixes; two
    roles that both need a credential get two distinct references.
    """

    by_role: Mapping[str, tuple[SecretReference, ...]]

    def __post_init__(self) -> None:
        seen_names: dict[str, str] = {}
        seen_paths: dict[str, str] = {}
        for role, references in self.by_role.items():
            if not role:
                raise SecretBindingError("consumer role must be nonempty text")
            for reference in references:
                if reference.name in seen_names:
                    raise SecretBindingError(
                        f"secret '{reference.name}' is bound to more than one role"
                    )
                seen_names[reference.name] = role
                if reference.mount_path in seen_paths:
                    raise SecretBindingError(
                        f"mount path '{reference.mount_path}' is reused"
                    )
                seen_paths[reference.mount_path] = role

    def for_role(self, role: str) -> tuple[SecretReference, ...]:
        return self.by_role.get(role, ())


def verify_mounted_secrets(
    references: Iterable[SecretReference], *, root: Path | None = None
) -> None:
    """Refuse readiness unless every referenced secret file is present and scoped.

    Raises `SecretUnavailable` naming only the reference id, never the
    file's contents, on a missing file, an empty file or a mode that grants
    access beyond the owner.
    """

    for reference in references:
        path = (
            Path(reference.mount_path)
            if root is None
            else root / reference.mount_path.lstrip("/")
        )
        try:
            info = path.stat()
        except OSError as error:
            raise SecretUnavailable(reference.name, "file is absent") from error
        if info.st_size == 0:
            raise SecretUnavailable(reference.name, "file is empty")
        mode = stat.S_IMODE(info.st_mode)
        if mode & ~_ALLOWED_MODE_BITS:
            raise SecretUnavailable(reference.name, "file permissions are too broad")


def describe_error(error: SecretUnavailable) -> str:
    """Serialize a secret failure as its reference id alone."""

    return f"secret_reference={error.reference_name}"


def scan_for_secret_values(
    blobs: Mapping[str, bytes], secret_values: Iterable[str]
) -> tuple[str, ...]:
    """Return the labels of any blob that contains a synthetic secret's bytes.

    The host-acceptance probe calls this against real image layers, image
    history, build context and rendered Compose text, injecting synthetic
    test credentials that exercise the exact injection path so the scan
    proves something; a production secret value is never passed in.
    """

    encoded = [value.encode("utf-8") for value in secret_values if value]
    hits: list[str] = []
    for label, blob in blobs.items():
        if any(needle in blob for needle in encoded):
            hits.append(label)
    return tuple(hits)
