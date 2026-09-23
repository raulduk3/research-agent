"""Local storage service for the source pilot: loopback mTLS, one ingest identity.

The pilot worker still reaches storage only through its authenticated HTTP
client. This module plays the operator: it provisions local certificates,
starts the storage service on loopback, publishes stage specifications and
enqueues `capture` jobs.
"""

from __future__ import annotations

import hashlib
import ssl
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from psycopg import Connection

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import canonical_json, canonical_loads
from research_agent.ingest.pilot import Identity, derived_uuid
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.authorization import StorageAuthorization
from research_agent.storage.client import StorageClient
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.http import ServiceCapability, create_storage_server
from research_agent.storage.jobs import JobRepository

WORKER_SCOPES = frozenset(
    {
        "jobs:claim",
        "jobs:renew",
        "jobs:checkpoint",
        "jobs:complete",
        "artifacts:read",
        "artifacts:publish",
    }
)
_SPEC_LIMIT = 16 * 1024 * 1024


def _openssl(*arguments: str) -> None:
    subprocess.run(("openssl", *arguments), check=True, capture_output=True)


def provision_tls(directory: Path) -> str:
    """Create a local CA, a `localhost` server certificate and one worker
    certificate once; return the worker certificate fingerprint."""
    directory.mkdir(parents=True, exist_ok=True)
    ca_key, ca = directory / "ca.key", directory / "ca.pem"
    if not ca.exists():
        _openssl(
            "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "3650",
            "-subj", "/CN=research-agent-pilot-ca",
            "-keyout", str(ca_key), "-out", str(ca),
        )  # fmt: skip
        for name, extension in (
            ("server", ("-addext", "subjectAltName=DNS:localhost")),
            ("worker", ()),
        ):
            key, csr = directory / f"{name}.key", directory / f"{name}.csr"
            _openssl(
                "req", "-newkey", "rsa:2048", "-nodes", "-subj", f"/CN={name}",
                *extension, "-keyout", str(key), "-out", str(csr),
            )  # fmt: skip
            _openssl(
                "x509", "-req", "-days", "3650", "-in", str(csr), "-CA", str(ca),
                "-CAkey", str(ca_key), "-CAcreateserial", "-copy_extensions",
                "copy", "-out", str(directory / f"{name}.pem"),
            )  # fmt: skip
        for key in directory.glob("*.key"):
            key.chmod(0o600)
    der = ssl.PEM_cert_to_DER_cert((directory / "worker.pem").read_text())
    return hashlib.sha256(der).hexdigest()


@dataclass
class LocalStorage:
    client: StorageClient
    jobs: JobRepository
    artifacts: ArtifactRepository
    database: Database
    identity: Identity
    store: ArtifactStore | None = None

    def publish_spec(self, spec: dict[str, Any], inputs: tuple[str, ...] = ()) -> str:
        body = canonical_json(spec)
        return self.artifacts.publish(
            [body],
            expected_hash=hashlib.sha256(body).hexdigest(),
            byte_length=len(body),
            maximum_length=_SPEC_LIMIT,
            media_type="application/json",
            kind="manifest",
            input_hashes=inputs,
            producer_version=self.identity.producer,
            config_hash=self.identity.config_hash,
            retention_policy_hash=self.identity.retention_policy_hash,
            command_id=uuid4(),
        ).manifest_hash

    def enqueue(
        self,
        spec: dict[str, Any],
        inputs: tuple[str, ...] = (),
        *,
        ahead: bool = False,
    ) -> UUID:
        """Publish `spec` and enqueue it; `ahead` schedules it a day early.

        Claim order is `ORDER BY scheduled_at, id`, so an `ahead` job is
        claimed before every normally scheduled job regardless of enqueue
        order (#151): the `openalex` stage uses it to resolve a family's
        labels without waiting behind its own `documents` backlog.
        """
        manifest = self.publish_spec(spec, inputs)
        job_id = uuid4()
        behind = timedelta(days=1) if ahead else timedelta(seconds=1)
        self.jobs.execute(
            "enqueue",
            identity=CommandIdentity(uuid4(), uuid4(), uuid4(), uuid4()),
            payload={
                "job_id": str(job_id),
                "kind": "capture",
                "input_manifest": manifest,
                "scheduled_at": (datetime.now(timezone.utc) - behind).strftime(
                    "%Y-%m-%dT%H:%M:%S.%fZ"
                ),
            },
        )
        return job_id

    def expedite(self, job_id: UUID) -> None:
        """Move a queued job's `scheduled_at` one day earlier.

        Refuses any job not currently `queued`, so a claimed, committed or
        failed job's ordering cannot be disturbed after other state has
        already formed around it.
        """

        def move(connection: Connection[tuple[object, ...]]) -> None:
            row = connection.execute(
                "SELECT state, scheduled_at FROM jobs WHERE id=%s FOR UPDATE",
                (job_id,),
            ).fetchone()
            if row is None or row[0] != "queued":
                raise ValueError(f"job {job_id} is not queued")
            connection.execute(
                "UPDATE jobs SET scheduled_at=%s WHERE id=%s",
                (cast(datetime, row[1]) - timedelta(days=1), job_id),
            )

        self.database.transaction(move)

    def defer(self, job_id: UUID) -> None:
        """Move a queued job's `scheduled_at` one day later.

        The counterpart of :meth:`expedite`, and refusing the same jobs: a
        stage whose provider has refused further requests today yields its
        queued backlog to the stages that read somewhere else, rather than
        holding the front of the claim order until tomorrow.
        """

        def move(connection: Connection[tuple[object, ...]]) -> None:
            row = connection.execute(
                "SELECT state, scheduled_at FROM jobs WHERE id=%s FOR UPDATE",
                (job_id,),
            ).fetchone()
            if row is None or row[0] != "queued":
                raise ValueError(f"job {job_id} is not queued")
            connection.execute(
                "UPDATE jobs SET scheduled_at=%s WHERE id=%s",
                (cast(datetime, row[1]) + timedelta(days=1), job_id),
            )

        self.database.transaction(move)

    def job_rows(self) -> list[tuple[str, str, str | None]]:
        """(job id, state, committed report manifest) in enqueue order."""
        return self.database.transaction(
            lambda connection: [
                (str(row[0]), str(row[1]), None if row[2] is None else str(row[2]))
                for row in connection.execute(
                    """SELECT j.id, j.state, encode(o.artifact_hash,'hex')
                       FROM jobs j LEFT JOIN job_outputs o ON o.job_id=j.id
                       ORDER BY j.scheduled_at, j.id"""
                ).fetchall()
            ]
        )

    def report(self, manifest: str) -> dict[str, Any]:
        """The committed summary a job published, read on the storage side."""
        (_, _), stream = self.artifacts.read(self._raw(manifest))
        with stream:
            value = canonical_loads(stream.read())
        assert isinstance(value, dict)
        return value

    def _raw(self, manifest: str) -> str:
        row = self.database.transaction(
            lambda connection: connection.execute(
                """SELECT encode(artifact_hash,'hex') FROM artifact_productions
                   WHERE manifest_hash=decode(%s,'hex')""",
                (manifest,),
            ).fetchone()
        )
        assert row is not None
        return str(row[0])


@contextmanager
def local_storage(
    *,
    dsn: str,
    artifact_root: Path,
    tls_directory: Path,
    identity: Identity,
    mirror: Path | None = None,
) -> Iterator[LocalStorage]:
    fingerprint = provision_tls(tls_directory)
    database, store = Database(dsn), ArtifactStore(artifact_root, mirror)
    jobs = JobRepository(
        database,
        store,
        producer=identity.producer,
        config_hash=identity.config_hash,
        retention_policy_hash=identity.retention_policy_hash,
    )
    artifacts = ArtifactRepository(database, store)
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(
        tls_directory / "server.pem", tls_directory / "server.key"
    )
    server_context.load_verify_locations(tls_directory / "ca.pem")
    server_context.verify_mode = ssl.CERT_REQUIRED
    capability = ServiceCapability(
        derived_uuid("pilot-worker", fingerprint),
        "ingest",
        WORKER_SCOPES,
        job_kinds=frozenset({"capture"}),
        producer_version=identity.producer,
        config_hash=identity.config_hash,
        retention_policy_hash=identity.retention_policy_hash,
    )
    httpd = create_storage_server(
        ("127.0.0.1", 0),
        jobs,
        {fingerprint: capability},
        tls_context=server_context,
        authorization=StorageAuthorization(database),
        artifacts=artifacts,
    )
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address[:2]
    client = StorageClient(
        connect_host=str(host),
        port=int(port),
        server_hostname="localhost",
        ca_file=tls_directory / "ca.pem",
        client_cert_file=tls_directory / "worker.pem",
        client_key_file=tls_directory / "worker.key",
        scopes=WORKER_SCOPES,
        timeout_seconds=300,
        maximum_artifact_bytes=1024**3,
    )
    try:
        yield LocalStorage(client, jobs, artifacts, database, identity, store)
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def worker_principal(tls_directory: Path) -> UUID:
    """The principal storage binds to the local worker certificate; claims and
    fences must carry it as the worker id."""
    return derived_uuid("pilot-worker", provision_tls(tls_directory))
