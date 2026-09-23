from pathlib import Path

import pytest

from research_agent.platform.secrets import (
    SecretBindingError,
    SecretBindings,
    SecretReference,
    SecretUnavailable,
    describe_error,
    scan_for_secret_values,
    verify_mounted_secrets,
)


def test_secret_reference_rejects_a_mount_outside_the_runtime_secret_root() -> None:
    with pytest.raises(SecretBindingError):
        SecretReference(name="storage_dsn", mount_path="/etc/storage_dsn")


def test_secret_bindings_rejects_a_name_bound_to_two_roles() -> None:
    reference = SecretReference(
        name="storage_dsn", mount_path="/run/secrets/storage_dsn"
    )
    other = SecretReference(name="storage_dsn", mount_path="/run/secrets/storage_dsn_2")
    with pytest.raises(SecretBindingError):
        SecretBindings({"storage": (reference,), "ingest": (other,)})


def test_secret_bindings_rejects_a_reused_mount_path() -> None:
    reference = SecretReference(name="a", mount_path="/run/secrets/shared")
    other = SecretReference(name="b", mount_path="/run/secrets/shared")
    with pytest.raises(SecretBindingError):
        SecretBindings({"storage": (reference, other)})


def test_verify_mounted_secrets_refuses_a_missing_file(tmp_path: Path) -> None:
    reference = SecretReference(
        name="storage_dsn", mount_path="/run/secrets/storage_dsn"
    )
    with pytest.raises(SecretUnavailable) as excinfo:
        verify_mounted_secrets((reference,), root=tmp_path)
    assert excinfo.value.reference_name == "storage_dsn"


def test_verify_mounted_secrets_refuses_a_world_readable_file(tmp_path: Path) -> None:
    reference = SecretReference(
        name="storage_dsn", mount_path="/run/secrets/storage_dsn"
    )
    path = tmp_path / "run" / "secrets" / "storage_dsn"
    path.parent.mkdir(parents=True)
    path.write_text("super-secret-value")
    path.chmod(0o644)
    with pytest.raises(SecretUnavailable):
        verify_mounted_secrets((reference,), root=tmp_path)


def test_verify_mounted_secrets_accepts_an_owner_scoped_file(tmp_path: Path) -> None:
    reference = SecretReference(
        name="storage_dsn", mount_path="/run/secrets/storage_dsn"
    )
    path = tmp_path / "run" / "secrets" / "storage_dsn"
    path.parent.mkdir(parents=True)
    path.write_text("super-secret-value")
    path.chmod(0o600)
    verify_mounted_secrets((reference,), root=tmp_path)


def test_describe_error_never_carries_the_secret_value(tmp_path: Path) -> None:
    reference = SecretReference(
        name="storage_dsn", mount_path="/run/secrets/storage_dsn"
    )
    try:
        verify_mounted_secrets((reference,), root=tmp_path)
    except SecretUnavailable as error:
        message = describe_error(error)
    assert message == "secret_reference=storage_dsn"


def test_scan_for_secret_values_flags_a_leaked_synthetic_credential() -> None:
    synthetic = "synthetic-test-credential-91a2"
    blobs = {
        "compose_render": b"services: {}\n",
        "image_history": f"ENV STORAGE_DSN={synthetic}".encode(),
    }
    hits = scan_for_secret_values(blobs, (synthetic,))
    assert hits == ("image_history",)


def test_scan_for_secret_values_is_clean_when_no_value_is_present() -> None:
    blobs = {"compose_render": b"services: {}\n"}
    hits = scan_for_secret_values(blobs, ("synthetic-test-credential-91a2",))
    assert hits == ()
