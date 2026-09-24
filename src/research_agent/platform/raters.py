"""Operator command that provisions one rater principal through storage (PL-22).

The command generates the rater's credential, writes it to a new owner-only
file whose path it prints, and sends storage only the salted hash. The salt
and the command's identifiers are derived from the credential and the rater
id, so a rerun that names the same file and rater replays the stored command
instead of provisioning a second principal. An existing file is read, never
overwritten.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4, uuid5

from research_agent.storage.client import StorageClient, StorageClientError
from research_agent.web.auth import _hash_credential

PROVISION_SCOPES = frozenset({"raters:provision"})
# Accepted spellings of the two rater islands the specification fixes, mapped
# to the stored value. A q-bio rater waits on the owner's decision in #371.
ISLANDS = {"cs": "cs", "quant-ph": "quant_ph", "quant_ph": "quant_ph"}
_DEFERRED = {"q-bio": "a q-bio rater is not specified yet (#371)"}
_NAMESPACE = UUID("5d7c1f3e-2b8a-4c61-9f0e-7a4b3c2d1e0f")


class RaterStorage(Protocol):
    def provision_rater(
        self,
        *,
        rater_id: UUID,
        island: str,
        salt: str,
        credential_hash: str,
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> object: ...


class RefusedProvision(Exception):
    """The command's inputs cannot provision a rater."""


def stored_island(island: str) -> str:
    if island in _DEFERRED:
        raise RefusedProvision(_DEFERRED[island])
    if island not in ISLANDS:
        raise RefusedProvision(f"island {island!r} has no rater principal")
    return ISLANDS[island]


def salt_for(credential: str) -> str:
    return hashlib.sha256(b"rater-salt\0" + credential.encode()).hexdigest()[:32]


def _credential(path: Path, *, replay: bool) -> str:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if not replay:
            raise RefusedProvision(
                f"{path} exists; pass --rater-id to replay its provisioning"
            ) from None
        credential = path.read_text(encoding="ascii").strip()
        if not credential:
            raise RefusedProvision(f"{path} holds no credential") from None
        return credential
    credential = secrets.token_urlsafe(32)
    with os.fdopen(descriptor, "w", encoding="ascii") as handle:
        handle.write(credential + "\n")
    return credential


def provision(
    storage: RaterStorage, *, island: str, credential_file: Path, rater_id: UUID | None
) -> UUID:
    stored = stored_island(island)
    replay = rater_id is not None
    rater = rater_id if rater_id is not None else uuid4()
    credential = _credential(credential_file, replay=replay)
    salt = salt_for(credential)
    storage.provision_rater(
        rater_id=rater,
        island=stored,
        salt=salt,
        credential_hash=_hash_credential(credential, salt),
        command_id=uuid5(_NAMESPACE, f"command:{rater}"),
        request_id=uuid5(_NAMESPACE, f"request:{rater}"),
        idempotency_key=uuid5(_NAMESPACE, f"idempotency:{rater}"),
    )
    return rater


def main(
    argv: Sequence[str] | None = None,
    *,
    storage: RaterStorage | None = None,
    out: Any = None,
) -> int:
    parser = argparse.ArgumentParser(description="Provision one rater principal.")
    parser.add_argument("--island", required=True)
    parser.add_argument("--credential-file", required=True, type=Path)
    parser.add_argument("--rater-id", type=UUID)
    parser.add_argument("--storage-host")
    parser.add_argument("--storage-port", type=int)
    parser.add_argument("--storage-server-name")
    parser.add_argument("--ca-file")
    parser.add_argument("--owner-cert")
    parser.add_argument("--owner-key")
    args = parser.parse_args(argv)
    out = out if out is not None else sys.stdout
    try:
        stored_island(args.island)
    except RefusedProvision as refused:
        print(f"refused: {refused}", file=sys.stderr)
        return 2
    if storage is None:
        missing = [
            name
            for name in (
                "storage_host",
                "storage_port",
                "storage_server_name",
                "ca_file",
                "owner_cert",
                "owner_key",
            )
            if getattr(args, name) is None
        ]
        if missing:
            parser.error(
                "required: " + ", ".join("--" + n.replace("_", "-") for n in missing)
            )
        storage = StorageClient(
            connect_host=args.storage_host,
            port=args.storage_port,
            server_hostname=args.storage_server_name,
            ca_file=Path(args.ca_file),
            client_cert_file=Path(args.owner_cert),
            client_key_file=Path(args.owner_key),
            scopes=PROVISION_SCOPES,
        )
    try:
        rater = provision(
            storage,
            island=args.island,
            credential_file=args.credential_file,
            rater_id=args.rater_id,
        )
    except RefusedProvision as refused:
        print(f"refused: {refused}", file=sys.stderr)
        return 2
    except StorageClientError as error:
        print(f"storage: {error.code}: {error}", file=sys.stderr)
        return 1
    print(f"rater {rater} credential {args.credential_file}", file=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
