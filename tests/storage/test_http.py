from __future__ import annotations

import io
import json
import hashlib
import ssl
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.client import HTTPResponse, HTTPSConnection
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import canonical_json
from research_agent.contracts import ProducerVersion
from research_agent.snapshots.documents import DocumentPins
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.errors import (
    IntegrityFailure,
    StateConflict,
    StorageError,
    UnavailableInput,
)
from research_agent.storage.http import (
    JobCommands,
    OwnerCommands,
    PopulationReads,
    RaterCommands,
    RecordCommands,
    RunCommands,
    ServiceCapability,
    SubmissionCommands,
    TraceCommands,
    create_storage_server,
)
from research_agent.storage.idempotency import StoredResponse
from research_agent.storage.jobs import JobRepository
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.authorization import StorageAuthorization


PRINCIPAL = UUID("123e4567-e89b-42d3-a456-426614174000")
OTHER = "123e4567-e89b-42d3-a456-426614174001"
COMMAND = "123e4567-e89b-42d3-a456-426614174002"
REQUEST = "123e4567-e89b-42d3-a456-426614174003"
KEY = "123e4567-e89b-42d3-a456-426614174004"
HASH = "a" * 64
SOURCE = b"%PDF-1.4 pinned source"
PIN = DocumentPins(
    paper_family_id="123e4567-e89b-42d3-a456-426614174020",
    paper_version_id="123e4567-e89b-42d3-a456-426614174021",
    card_hash="b" * 64,
    overview_hash=HASH,
    passage_index_hash="c" * 64,
    graph_hash=None,
)


class Jobs:
    def __init__(self) -> None:
        self.calls: list[tuple[str, CommandIdentity, object, UUID | None]] = []
        self.response = StoredResponse(
            200,
            canonical_json(
                {
                    "schema_version": 1,
                    "request_id": REQUEST,
                    "status": "ok",
                    "data": {"lease": None},
                    "error": None,
                }
            ),
            False,
        )

    def execute(
        self,
        operation: str,
        *,
        identity: CommandIdentity,
        payload: object,
        job_id: UUID | None = None,
    ) -> StoredResponse:
        self.calls.append((operation, identity, payload, job_id))
        return self.response


class Records:
    def __init__(self) -> None:
        self.calls: list[tuple[str, CommandIdentity, object]] = []
        self.reads: list[str] = []
        self.response = StoredResponse(
            200,
            canonical_json(
                {
                    "schema_version": 1,
                    "request_id": REQUEST,
                    "status": "ok",
                    "data": {},
                    "error": None,
                }
            ),
            False,
        )

    def execute(
        self, operation: str, *, identity: CommandIdentity, payload: object
    ) -> StoredResponse:
        self.calls.append((operation, identity, payload))
        return self.response

    def finish_without_submit(
        self, *, identity: CommandIdentity, payload: object
    ) -> StoredResponse:
        return self.execute("finish_without_submit", identity=identity, payload=payload)

    def accept_submission(
        self, *, identity: CommandIdentity, payload: object
    ) -> StoredResponse:
        return self.execute("accept_submission", identity=identity, payload=payload)

    def read(self, run_id: str) -> dict[str, object] | None:
        """A run's trace: OTHER's has no calls, PRINCIPAL's is unreadable."""

        self.reads.append(run_id)
        if run_id == str(PRINCIPAL):
            raise IntegrityFailure("a stored trace payload is unreadable")
        return {"run_id": run_id, "calls": []} if run_id == OTHER else None

    def since(self, cursor: int, limit: int = 100) -> dict[str, object]:
        """No events after any cursor; records what was asked."""

        self.reads.append(f"since:{cursor}:{limit}")
        return {"events": [], "cursor": cursor}


class Asks(Records):
    """A run's asks: OTHER has one kept answer under HASH."""

    def recorded(self, run_id: str, work_key: str) -> bytes | None:
        self.reads.append(run_id)
        return b'{"kind":"ask"}' if (run_id, work_key) == (OTHER, HASH) else None

    def answered(self, run_id: str) -> int:
        self.reads.append(run_id)
        return 1 if run_id == OTHER else 0


class Artifacts:
    def read(self, artifact_hash: str) -> tuple[tuple[int, str], io.BytesIO]:
        assert artifact_hash == HASH
        return (7, "text/plain"), io.BytesIO(b"payload")

    def publish_command(self, *args: object, **kwargs: object) -> StoredResponse:
        raise AssertionError("malformed upload must not publish")


class Queries:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def run(self, run_id: str) -> dict[str, object] | None:
        self.calls.append(("run", (run_id,)))
        if run_id != OTHER:
            return None
        return {"run_id": run_id, "events": []}

    def run_specification(self, run_id: str) -> dict[str, object] | None:
        self.calls.append(("run_specification", (run_id,)))
        if run_id != OTHER:
            return None
        return {"run_id": run_id, "snapshot_hash": HASH, "active": True}

    def run_worker(self, run_id: str) -> dict[str, object] | None:
        self.calls.append(("run_worker", (run_id,)))
        if run_id == str(PRINCIPAL):
            raise UnavailableInput("run configuration has no stored prompt")
        if run_id != OTHER:
            return None
        return {"run_id": run_id, "prompt": "evidence first"}

    def snapshot(self, snapshot_hash: str) -> dict[str, object] | None:
        self.calls.append(("snapshot", (snapshot_hash,)))
        if snapshot_hash != HASH:
            return None
        return {"snapshot_hash": HASH, "pinned_family_count": 1}

    def runs_by_configuration(
        self, configuration_id: str, *, cursor: tuple[str, str] | None
    ) -> tuple[tuple[dict[str, object], ...], tuple[str, str] | None]:
        self.calls.append(("runs_by_configuration", (configuration_id, cursor)))
        return ({"run_id": OTHER},), None

    def runs_by_batch(
        self, batch_id: str, *, cursor: tuple[str, str] | None
    ) -> tuple[tuple[dict[str, object], ...], tuple[str, str] | None]:
        self.calls.append(("runs_by_batch", (batch_id, cursor)))
        return (), None

    def runs_by_paper(
        self, paper_id: str, *, cursor: tuple[str, str] | None
    ) -> tuple[tuple[dict[str, object], ...], tuple[str, str] | None]:
        self.calls.append(("runs_by_paper", (paper_id, cursor)))
        return ({"run_id": OTHER, "paper_id": paper_id},), None

    def sheet(self, sheet_hash: str) -> dict[str, object] | None:
        self.calls.append(("sheet", (sheet_hash,)))
        if sheet_hash != HASH:
            return None
        return {"sheet_hash": HASH, "questions": [{"question_id": OTHER}]}

    def submissions_by_submitter(
        self, submitter_id: str
    ) -> tuple[dict[str, object], ...]:
        self.calls.append(("submissions_by_submitter", (submitter_id,)))
        return ({"submission_id": OTHER},)

    def manifest(self, artifact_hash: str) -> dict[str, object] | None:
        self.calls.append(("manifest", (artifact_hash,)))
        if artifact_hash != HASH:
            return None
        return {"artifact_hash": HASH, "manifest_kind": "unknown", "fields": {}}

    def configurations(
        self, *, cursor: tuple[str, str] | None
    ) -> tuple[tuple[dict[str, object], ...], tuple[str, str] | None]:
        self.calls.append(("configurations", (cursor,)))
        return (
            ({"configuration_id": OTHER},),
            ("2026-09-22T00:00:00.000000Z", OTHER),
        )

    def configuration(self, configuration_id: str) -> dict[str, object] | None:
        self.calls.append(("configuration", (configuration_id,)))
        if configuration_id != OTHER:
            return None
        return {"configuration_id": OTHER, "parts": []}

    def forecasts_by_configuration(
        self, configuration_id: str, *, cursor: tuple[str, str] | None
    ) -> tuple[tuple[dict[str, object], ...], tuple[str, str] | None]:
        self.calls.append(("forecasts_by_configuration", (configuration_id, cursor)))
        return ({"submission_id": OTHER, "resolution": None},), None

    def owner_paper(
        self, paper_id: str, *, cursor: tuple[str, str] | None
    ) -> dict[str, object] | None:
        """OTHER's paper has one run; PRINCIPAL's pinned card is unreadable."""

        self.calls.append(("owner_paper", (paper_id, cursor)))
        if paper_id == str(PRINCIPAL):
            raise UnavailableInput("a pinned card record is unavailable")
        if paper_id != OTHER:
            return None
        return {"paper_id": paper_id, "runs": [{"run_id": OTHER}], "next_cursor": None}

    def owner_run(self, run_id: str) -> dict[str, object] | None:
        self.calls.append(("owner_run", (run_id,)))
        return {"run_id": run_id, "ending": None} if run_id == OTHER else None

    def owner_runs(
        self,
        *,
        day: str | None,
        island: str | None,
        since: str | None,
        cursor: tuple[str, str] | None,
    ) -> tuple[tuple[dict[str, object], ...], tuple[str, str] | None]:
        self.calls.append(("owner_runs", (day, island, since, cursor)))
        return (
            ({"run_id": OTHER, "lineage_id": "lineage-1", "island": "cs"},),
            ("2026-09-22T00:00:00.000000Z", OTHER),
        )

    def owner_islands(self) -> tuple[dict[str, object], ...]:
        self.calls.append(("owner_islands", ()))
        return ({"island": "cs", "genomes": 2},)

    def owner_island(self, island: str) -> tuple[dict[str, object], ...]:
        self.calls.append(("owner_island", (island,)))
        return ({"lineage_id": "lineage-1", "runs": 3},)

    def owner_reports(self) -> tuple[dict[str, object], ...]:
        self.calls.append(("owner_reports", ()))
        return ({"island": "cs", "iso_week": "2026-W39", "digests": 1},)

    def owner_report_selection(
        self, island: str, iso_week: str
    ) -> dict[str, object] | None:
        self.calls.append(("owner_report_selection", (island, iso_week)))
        if island != "cs" or iso_week != "2026-W39":
            return None
        return {"island": island, "iso_week": iso_week, "archived": []}

    def owner_impact(self) -> tuple[dict[str, object], ...]:
        self.calls.append(("owner_impact", ()))
        return ({"island": "cs", "iso_week": "2026-W39", "ratings": 1},)

    def owner_models(self) -> tuple[dict[str, object], ...]:
        self.calls.append(("owner_models", ()))
        return ({"manifest_hash": "a" * 64, "runs": 2},)

    def owner_cost_days(self, day: str) -> tuple[dict[str, object], ...]:
        self.calls.append(("owner_cost_days", (day,)))
        return ({"day": day, "island": "cs", "priced_micros": 5},)

    def owner_day(self, day: str) -> dict[str, object]:
        self.calls.append(("owner_day", (day,)))
        return {"day": day, "runs": [], "digests": []}

    def owner_agents(self) -> tuple[dict[str, object], ...]:
        self.calls.append(("owner_agents", ()))
        return ({"configuration_id": KEY, "island": "cs", "runs": 3},)

    def owner_agent_runs(
        self, configuration_id: str, *, cursor: tuple[str, str] | None
    ) -> tuple[dict[str, object], tuple[str, str] | None] | None:
        self.calls.append(("owner_agent_runs", (configuration_id, cursor)))
        if configuration_id != KEY:
            return None
        return {"days": [], "runs": []}, ("2026-01-01T00:00:00.000000Z", OTHER)

    def owner_questions(self) -> tuple[dict[str, object], ...]:
        self.calls.append(("owner_questions", ()))
        return ({"question_id": KEY, "runs": 1},)

    def owner_question(self, question_id: str) -> dict[str, object] | None:
        self.calls.append(("owner_question", (question_id,)))
        return {"question_id": KEY, "runs": []} if question_id == KEY else None

    def owner_run_record(self, run_id: str) -> dict[str, object] | None:
        self.calls.append(("owner_run_record", (run_id,)))
        return {"island": "cs", "calls": []} if run_id == KEY else None

    def owner_paper_documents(self, paper_id: str) -> tuple[dict[str, object], ...]:
        self.calls.append(("owner_paper_documents", (paper_id,)))
        return ({"artifact_hash": HASH, "byte_length": 7},)

    def owner_document(self, artifact_hash: str) -> bool:
        self.calls.append(("owner_document", (artifact_hash,)))
        return artifact_hash == HASH

    def run_settlement(self, run_id: str) -> dict[str, object] | None:
        self.calls.append(("run_settlement", (run_id,)))
        return {"run_id": run_id, "input_tokens": 3} if run_id == OTHER else None


class Documents:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def paper_manifest_hash(self, snapshot_hash: str) -> str:
        self.calls.append(("paper_manifest", ()))
        return "b" * 64

    def cards(
        self, snapshot_hash: str, paper_version_ids: tuple[str, ...]
    ) -> tuple[dict[str, object], ...]:
        self.calls.append(("cards", paper_version_ids))
        return tuple({"paper_version_id": item} for item in paper_version_ids)

    def graph(self, snapshot_hash: str, paper_version_id: str) -> dict[str, object]:
        self.calls.append(("graph", (paper_version_id,)))
        return {"incoming": []}

    def passage_index(
        self, snapshot_hash: str, paper_version_id: str
    ) -> dict[str, object]:
        self.calls.append(("passage_index", (paper_version_id,)))
        return {"passages": [{"text_hash": HASH, "text": "matched text"}]}

    def questions(self, snapshot_hash: str) -> tuple[dict[str, object], ...]:
        self.calls.append(("questions", ()))
        return ({"question_id": OTHER},)

    def members(
        self,
        snapshot_hash: str,
        *,
        after: tuple[str, str] | None = None,
        limit: int | None = None,
    ) -> tuple[DocumentPins, ...]:
        self.calls.append(("members", () if after is None else after))
        return (PIN,)

    def family_pin(self, snapshot_hash: str, paper_family_id: str) -> DocumentPins:
        self.calls.append(("family_pin", (paper_family_id,)))
        if paper_family_id != PIN.paper_family_id:
            raise UnavailableInput("paper family is not pinned in this snapshot")
        return PIN

    def overviews(
        self, snapshot_hash: str, overview_hashes: tuple[str, ...]
    ) -> tuple[dict[str, object], ...]:
        self.calls.append(("overviews", overview_hashes))
        return tuple({"vector": [1.0, 0.0]} for _ in overview_hashes)

    def passage_index_by_hash(
        self, snapshot_hash: str, passage_index_hash: str
    ) -> dict[str, object]:
        self.calls.append(("passage_index_by_hash", (passage_index_hash,)))
        return {"passages": []}

    def extraction(self, snapshot_hash: str, paper_family_id: str) -> dict[str, object]:
        self.calls.append(("extraction", (paper_family_id,)))
        if paper_family_id != PIN.paper_family_id:
            raise UnavailableInput("paper family is not pinned in this snapshot")
        return {
            "paper_version_id": PIN.paper_version_id,
            "extraction_hash": HASH,
            "extraction": {"blocks": []},
        }

    def source(
        self, snapshot_hash: str, paper_family_id: str
    ) -> tuple[str, tuple[int, str], io.BytesIO]:
        self.calls.append(("source", (paper_family_id,)))
        if paper_family_id != PIN.paper_family_id:
            raise UnavailableInput("paper family is not pinned in this snapshot")
        return (
            hashlib.sha256(SOURCE).hexdigest(),
            (len(SOURCE), "application/pdf"),
            io.BytesIO(SOURCE),
        )


class EmbeddingViews:
    """A family's stored views: PIN's family has one, OTHER's is unreadable."""

    def __init__(self, view: dict[str, object] | None = None) -> None:
        self.view = view or {"paper_id": PIN.paper_family_id, "dims": 2}
        self.calls: list[str] = []

    def current(self, paper_family_id: str) -> dict[str, object] | None:
        self.calls.append(paper_family_id)
        if paper_family_id == OTHER:
            raise UnavailableInput("stored view is not valid JSON")
        return self.view if paper_family_id == PIN.paper_family_id else None

    def record(self, view_hash: str) -> None:
        self.calls.append(view_hash)


class Authorization(StorageAuthorization):
    def __init__(self) -> None:
        pass

    def job_fence_allowed(self, **kwargs: object) -> bool:
        return True

    def command_completed(self, **kwargs: object) -> bool:
        return False

    def job_scope_active(self, **kwargs: object) -> bool:
        return True

    def artifact_in_job_scope(self, *, artifact_hash: str, **kwargs: object) -> bool:
        return artifact_hash == HASH


def _tls_material(
    root: Path,
) -> tuple[ssl.SSLContext, ssl.SSLContext, str, ssl.SSLContext, str, ssl.SSLContext]:
    ca_key, ca_cert = root / "ca.key", root / "ca.pem"
    server_key, server_csr, server_cert = (
        root / "server.key",
        root / "server.csr",
        root / "server.pem",
    )
    client_key, client_csr, client_cert = (
        root / "client.key",
        root / "client.csr",
        root / "client.pem",
    )
    wrong_key, wrong_csr, wrong_cert = (
        root / "wrong.key",
        root / "wrong.csr",
        root / "wrong.pem",
    )
    commands = (
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=test-ca",
            "-keyout",
            str(ca_key),
            "-out",
            str(ca_cert),
        ],
        [
            "openssl",
            "req",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-subj",
            "/CN=storage",
            "-addext",
            "subjectAltName=DNS:localhost,IP:127.0.0.1",
            "-keyout",
            str(server_key),
            "-out",
            str(server_csr),
        ],
        [
            "openssl",
            "x509",
            "-req",
            "-days",
            "1",
            "-in",
            str(server_csr),
            "-CA",
            str(ca_cert),
            "-CAkey",
            str(ca_key),
            "-CAcreateserial",
            "-copy_extensions",
            "copy",
            "-out",
            str(server_cert),
        ],
        [
            "openssl",
            "req",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-subj",
            "/CN=reader",
            "-keyout",
            str(client_key),
            "-out",
            str(client_csr),
        ],
        [
            "openssl",
            "x509",
            "-req",
            "-days",
            "1",
            "-in",
            str(client_csr),
            "-CA",
            str(ca_cert),
            "-CAkey",
            str(ca_key),
            "-CAcreateserial",
            "-out",
            str(client_cert),
        ],
        [
            "openssl",
            "req",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-subj",
            "/CN=tools",
            "-keyout",
            str(wrong_key),
            "-out",
            str(wrong_csr),
        ],
        [
            "openssl",
            "x509",
            "-req",
            "-days",
            "1",
            "-in",
            str(wrong_csr),
            "-CA",
            str(ca_cert),
            "-CAkey",
            str(ca_key),
            "-CAcreateserial",
            "-out",
            str(wrong_cert),
        ],
    )
    for command_line in commands:
        subprocess.run(command_line, check=True, capture_output=True)
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(server_cert, server_key)
    server_context.load_verify_locations(ca_cert)
    server_context.verify_mode = ssl.CERT_REQUIRED
    client_context = ssl.create_default_context(cafile=str(ca_cert))
    client_context.load_cert_chain(client_cert, client_key)
    der = ssl.PEM_cert_to_DER_cert(client_cert.read_text())
    wrong_context = ssl.create_default_context(cafile=str(ca_cert))
    wrong_context.load_cert_chain(wrong_cert, wrong_key)
    wrong_der = ssl.PEM_cert_to_DER_cert(wrong_cert.read_text())
    no_certificate_context = ssl.create_default_context(cafile=str(ca_cert))
    return (
        server_context,
        client_context,
        hashlib.sha256(der).hexdigest(),
        wrong_context,
        hashlib.sha256(wrong_der).hexdigest(),
        no_certificate_context,
    )


@contextmanager
def server(
    jobs: JobCommands,
    tls: tuple[
        ssl.SSLContext, ssl.SSLContext, str, ssl.SSLContext, str, ssl.SSLContext
    ],
    *,
    artifact: bool = False,
    artifact_repository: ArtifactRepository | None = None,
    documents: Documents | None = None,
    queries: Queries | None = None,
    authorization: StorageAuthorization | None = None,
    role: str = "reader",
    extra_scopes: frozenset[str] = frozenset(),
    runs: RunCommands | None = None,
    snapshots: RecordCommands | None = None,
    sheets: RecordCommands | None = None,
    submissions: SubmissionCommands | None = None,
    ratings: RecordCommands | None = None,
    owners: OwnerCommands | None = None,
    trace: TraceCommands | None = None,
    embedding_views: EmbeddingViews | None = None,
    asks: Asks | None = None,
    raters: RaterCommands | None = None,
    population: PopulationReads | None = None,
) -> Iterator[tuple[tuple[str, int], ssl.SSLContext, ssl.SSLContext, ssl.SSLContext]]:
    (
        server_context,
        client_context,
        fingerprint,
        wrong_context,
        wrong_fingerprint,
        no_certificate_context,
    ) = tls
    capability = ServiceCapability(
        PRINCIPAL,
        role,
        frozenset({"jobs:claim", "jobs:renew", "artifacts:read", "artifacts:publish"})
        | extra_scopes,
        job_kinds=frozenset({"extract"}),
        producer_version=ProducerVersion("a" * 64, "b" * 40, 1),
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )
    httpd = create_storage_server(
        ("127.0.0.1", 0),
        jobs,
        {
            fingerprint: capability,
            wrong_fingerprint: ServiceCapability(
                PRINCIPAL,
                "scorer",
                frozenset({"jobs:claim", "artifacts:read"}),
                job_kinds=frozenset({"extract"}),
                producer_version=ProducerVersion("a" * 64, "b" * 40, 1),
                config_hash="c" * 64,
                retention_policy_hash="d" * 64,
            ),
        },
        tls_context=server_context,
        authorization=authorization or Authorization(),
        artifacts=artifact_repository or (Artifacts() if artifact else None),
        documents=documents,
        queries=queries,
        runs=runs,
        snapshots=snapshots,
        sheets=sheets,
        submissions=submissions,
        ratings=ratings,
        owners=owners,
        trace=trace,
        embedding_views=embedding_views,
        asks=asks,
        raters=raters,
        population=population,
    )
    thread = threading.Thread(target=httpd.serve_forever)
    thread.start()
    try:
        host, port = httpd.server_address[:2]
        yield (
            (str(host), int(port)),
            client_context,
            wrong_context,
            no_certificate_context,
        )
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def request(
    address: tuple[str, int],
    context: ssl.SSLContext,
    method: str,
    path: str,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[HTTPResponse, bytes]:
    connection = HTTPSConnection(*address, timeout=2, context=context)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    data = response.read()
    connection.close()
    return response, data


def command(payload: object) -> bytes:
    return canonical_json(
        {
            "schema_version": 1,
            "command_id": COMMAND,
            "request_id": REQUEST,
            "payload": payload,
        }
    )


def headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Idempotency-Key": KEY,
        "X-Job-Id": OTHER,
        "X-Lease-Epoch": "1",
    }


def multipart(metadata: dict[str, object], payload: bytes) -> tuple[bytes, str]:
    boundary = "research-agent-boundary"
    body = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="metadata"\r\n'
            "Content-Type: application/json\r\n\r\n"
        ).encode()
        + canonical_json(metadata)
        + (
            f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="payload"; filename="payload"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        + payload
        + f"\r\n--{boundary}--\r\n".encode()
    )
    return body, f"multipart/form-data; boundary={boundary}"


def test_real_http_dispatches_strict_authenticated_command(tmp_path: Path) -> None:
    jobs = Jobs()
    with server(jobs, _tls_material(tmp_path)) as (address, context, _, no_certificate):
        with pytest.raises((ssl.SSLError, BrokenPipeError)):
            request(address, no_certificate, "GET", f"/v1/artifacts/{HASH}")
        response, body = request(
            address,
            context,
            "POST",
            "/v1/jobs/claim",
            command({"worker_id": str(PRINCIPAL), "kinds": ["extract"]}),
            headers(),
        )
    assert response.status == 200
    assert json.loads(body)["status"] == "ok"
    assert jobs.calls[0][0] == "claim"
    assert jobs.calls[0][1] == CommandIdentity(
        PRINCIPAL, UUID(KEY), UUID(COMMAND), UUID(REQUEST)
    )


def test_scope_and_worker_binding_fail_before_repository(tmp_path: Path) -> None:
    jobs = Jobs()
    with server(jobs, _tls_material(tmp_path)) as (
        address,
        context,
        wrong_context,
        _,
    ):
        wrong_role, _ = request(
            address,
            wrong_context,
            "POST",
            "/v1/jobs/claim",
            command({"worker_id": str(PRINCIPAL), "kinds": ["extract"]}),
            headers(),
        )
        forbidden_scope, _ = request(
            address,
            context,
            "POST",
            f"/v1/jobs/{OTHER}/complete",
            command(
                {"fence": {"worker_id": str(PRINCIPAL), "lease_epoch": 1}, "result": {}}
            ),
            headers(),
        )
        forged_worker, forged_body = request(
            address,
            context,
            "POST",
            "/v1/jobs/claim",
            command({"worker_id": OTHER, "kinds": ["extract"]}),
            headers(),
        )
        forbidden_kind, _ = request(
            address,
            context,
            "POST",
            "/v1/jobs/claim",
            command({"worker_id": str(PRINCIPAL), "kinds": ["fit"]}),
            headers(),
        )
    assert wrong_role.status == 403
    assert forbidden_scope.status == 403
    assert forbidden_scope.getheader("Connection") == "close"
    assert wrong_role.getheader("Connection") == "close"
    assert forged_worker.status == 403
    assert forbidden_kind.status == 403
    assert json.loads(forged_body)["error"]["code"] == "forbidden"
    assert jobs.calls == []


def test_closed_command_content_type_size_and_unknown_routes_fail_closed(
    tmp_path: Path,
) -> None:
    jobs = Jobs()
    valid = json.loads(command({"worker_id": str(PRINCIPAL), "kinds": ["extract"]}))
    valid["extra"] = True
    with server(jobs, _tls_material(tmp_path)) as (address, context, _, _):
        wrong_type, _ = request(
            address,
            context,
            "POST",
            "/v1/jobs/claim",
            b"{}",
            {**headers(), "Content-Type": "text/plain"},
        )
        unknown_field, _ = request(
            address, context, "POST", "/v1/jobs/claim", canonical_json(valid), headers()
        )
        unknown_route, _ = request(
            address, context, "POST", "/v1/jobs/enqueue", command({}), headers()
        )
        upload, upload_body = request(
            address, context, "POST", "/v1/artifacts", b"", headers()
        )
    assert wrong_type.status == 422
    assert unknown_field.status == 422
    assert unknown_route.status == 404
    assert upload.status == 403
    assert json.loads(upload_body)["error"]["code"] == "forbidden"
    assert jobs.calls == []


def test_unsupported_method_returns_typed_reply(tmp_path: Path) -> None:
    jobs = Jobs()
    with server(jobs, _tls_material(tmp_path)) as (address, context, _, _):
        response, body = request(address, context, "PUT", "/v1/jobs/claim", b"{}")
    assert response.status == 404
    assert response.getheader("Content-Type") == "application/json"
    assert json.loads(body)["error"]["code"] == "not_found"


def test_successful_replay_header_is_emitted(tmp_path: Path) -> None:
    jobs = Jobs()
    jobs.response = StoredResponse(200, jobs.response.body, True)
    with server(jobs, _tls_material(tmp_path)) as (address, context, _, _):
        response, _ = request(
            address,
            context,
            "POST",
            "/v1/jobs/claim",
            command({"worker_id": str(PRINCIPAL), "kinds": ["extract"]}),
            headers(),
        )
    assert response.getheader("X-Replayed") == "true"


def test_artifact_read_requires_hash_specific_visibility(tmp_path: Path) -> None:
    jobs = Jobs()
    with server(jobs, _tls_material(tmp_path), artifact=True) as (
        address,
        context,
        wrong_context,
        _,
    ):
        visible, body = request(
            address,
            context,
            "GET",
            f"/v1/artifacts/{HASH}",
            headers={"X-Job-Id": OTHER, "X-Lease-Epoch": "1"},
        )
        hidden, hidden_body = request(
            address,
            context,
            "GET",
            f"/v1/artifacts/{'b' * 64}",
            headers={"X-Job-Id": OTHER, "X-Lease-Epoch": "1"},
        )
        wrong_role, wrong_role_body = request(
            address,
            wrong_context,
            "GET",
            f"/v1/artifacts/{HASH}",
            headers={"X-Job-Id": OTHER, "X-Lease-Epoch": "1"},
        )
    assert visible.status == 200
    assert visible.getheader("ETag") == f'"{HASH}"'
    assert body == b"payload"
    assert hidden.status == 404
    assert json.loads(hidden_body)["error"]["code"] == "not_found"
    assert wrong_role.status == 404
    assert json.loads(wrong_role_body)["error"]["code"] == "not_found"


@pytest.mark.integration
def test_real_http_reaches_postgres_job_transaction(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    jobs = JobRepository(
        Database(postgres_dsn),
        ArtifactStore(artifact_root),
        producer=ProducerVersion("a" * 64, "b" * 40, 1),
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )
    with server(jobs, _tls_material(tmp_path)) as (address, context, _, _):
        response, body = request(
            address,
            context,
            "POST",
            "/v1/jobs/claim",
            command({"worker_id": str(PRINCIPAL), "kinds": ["extract"]}),
            headers(),
        )
        replay, replay_body = request(
            address,
            context,
            "POST",
            "/v1/jobs/claim",
            command({"worker_id": str(PRINCIPAL), "kinds": ["extract"]}),
            headers(),
        )
    assert response.status == 200
    assert json.loads(body)["data"] == {"lease": None}
    assert replay.status == 200
    assert replay.getheader("X-Replayed") == "true"
    assert replay_body == body


@pytest.mark.integration
def test_real_http_artifact_upload_is_idempotent(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    database = Database(postgres_dsn)
    store = ArtifactStore(artifact_root)
    jobs = JobRepository(
        database,
        store,
        producer=ProducerVersion("a" * 64, "b" * 40, 1),
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )
    artifacts = ArtifactRepository(database, store)
    seed = b'{"seed":1}'
    seed_publication = artifacts.publish(
        [seed],
        expected_hash=hashlib.sha256(seed).hexdigest(),
        byte_length=len(seed),
        maximum_length=1024,
        media_type="application/json",
        kind="manifest",
        input_hashes=(),
        producer_version=ProducerVersion("a" * 64, "b" * 40, 1),
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
        command_id=uuid4(),
    )
    jobs.execute(
        "enqueue",
        identity=CommandIdentity(uuid4(), uuid4(), uuid4(), uuid4()),
        payload={
            "job_id": OTHER,
            "kind": "extract",
            "input_manifest": seed_publication.manifest_hash,
            "scheduled_at": (
                datetime.now(timezone.utc) - timedelta(seconds=1)
            ).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        },
    )
    jobs.execute(
        "claim",
        identity=CommandIdentity(PRINCIPAL, uuid4(), uuid4(), uuid4()),
        payload={"worker_id": str(PRINCIPAL), "kinds": ["extract"]},
    )
    payload = b'{"http-upload":1}'
    metadata: dict[str, object] = {
        "schema_version": 1,
        "command_id": COMMAND,
        "request_id": REQUEST,
        "expected_hash": hashlib.sha256(payload).hexdigest(),
        "byte_length": len(payload),
        "media_type": "application/json",
        "kind": "manifest",
        "input_hashes": [],
        "producer_version": {
            "image_digest": "a" * 64,
            "source_commit": "b" * 40,
            "contract_version": 1,
        },
        "config_hash": "c" * 64,
        "source_available_at": None,
        "retention_policy_hash": "d" * 64,
    }
    body, content_type = multipart(metadata, payload)
    upload_headers = {
        "Content-Type": content_type,
        "Idempotency-Key": KEY,
        "X-Job-Id": OTHER,
        "X-Lease-Epoch": "1",
    }
    with server(
        jobs,
        _tls_material(tmp_path),
        artifact_repository=artifacts,
        authorization=StorageAuthorization(database),
    ) as (
        address,
        context,
        _,
        _,
    ):
        first, first_body = request(
            address, context, "POST", "/v1/artifacts", body, upload_headers
        )
        replay, replay_body = request(
            address, context, "POST", "/v1/artifacts", body, upload_headers
        )
    assert first.status == 201
    assert replay.status == 201
    assert replay.getheader("X-Replayed") == "true"
    assert replay_body == first_body
    assert json.loads(first_body)["data"]["artifact_hash"] == metadata["expected_hash"]


def test_record_routes_dispatch_to_their_owner_with_required_scope(
    tmp_path: Path,
) -> None:
    jobs = Jobs()
    runs, snapshots, sheets, submissions, ratings = (
        Records(),
        Records(),
        Records(),
        Records(),
        Records(),
    )
    with server(
        jobs,
        _tls_material(tmp_path),
        role="orchestrator",
        extra_scopes=frozenset(
            {"runs:create", "runs:append_event", "snapshots:seal", "sheets:seal"}
        ),
        runs=runs,
        snapshots=snapshots,
        sheets=sheets,
        submissions=submissions,
        ratings=ratings,
    ) as (address, context, _, _):
        run_response, _ = request(
            address, context, "POST", "/v1/runs", command({}), headers()
        )
        event_response, _ = request(
            address,
            context,
            "POST",
            f"/v1/runs/{OTHER}/events",
            command({}),
            headers(),
        )
        snapshot_response, _ = request(
            address, context, "POST", "/v1/snapshots", command({}), headers()
        )
        sheet_response, _ = request(
            address, context, "POST", "/v1/sheets", command({}), headers()
        )
        forbidden_submission, _ = request(
            address, context, "POST", "/v1/submissions", command({}), headers()
        )
        forbidden_rating, _ = request(
            address, context, "POST", "/v1/ratings", command({}), headers()
        )
        malformed_run_id, _ = request(
            address,
            context,
            "POST",
            "/v1/runs/not-a-uuid/events",
            command({}),
            headers(),
        )
    assert run_response.status == 200
    assert event_response.status == 200
    assert snapshot_response.status == 200
    assert sheet_response.status == 200
    assert forbidden_submission.status == 403
    assert forbidden_rating.status == 403
    assert malformed_run_id.status == 404
    assert runs.calls[0][0] == "create"
    assert runs.calls[1][0] == "append_event"
    assert snapshots.calls[0][0] == "seal"
    assert sheets.calls[0][0] == "seal"
    assert submissions.calls == []
    assert ratings.calls == []


class Refusing(Records):
    """A record owner whose every command fails with one storage error."""

    def __init__(self, error: StorageError) -> None:
        super().__init__()
        self.error = error

    def execute(
        self, operation: str, *, identity: CommandIdentity, payload: object
    ) -> StoredResponse:
        self.calls.append((operation, identity, payload))
        raise self.error


def test_run_endings_dispatch_submit_and_void_to_their_owners(
    tmp_path: Path,
) -> None:
    runs, submissions = Records(), Records()
    ending = {"run_id": OTHER, "reason": "model_stopped"}
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="orchestrator",
        extra_scopes=frozenset({"runs:submit", "runs:void"}),
        runs=runs,
        submissions=submissions,
    ) as (address, context, _, _):
        submit_response, _ = request(
            address,
            context,
            "POST",
            f"/v1/runs/{OTHER}/submit",
            command({"run_id": OTHER}),
            headers(),
        )
        void_response, _ = request(
            address,
            context,
            "POST",
            f"/v1/runs/{OTHER}/void",
            command(ending),
            headers(),
        )
        mismatched, mismatched_body = request(
            address,
            context,
            "POST",
            f"/v1/runs/{PRINCIPAL}/void",
            command(ending),
            headers(),
        )
    assert submit_response.status == 200
    assert void_response.status == 200
    assert submissions.calls[0][0] == "accept_submission"
    assert runs.calls[0][0] == "finish_without_submit"
    assert runs.calls[0][2] == ending
    assert mismatched.status == 422
    assert json.loads(mismatched_body)["error"]["code"] == "invalid_input"
    assert len(runs.calls) == 1


def test_run_endings_need_their_role_and_their_scope(
    tmp_path: Path,
) -> None:
    runs, submissions = Records(), Records()
    scopes = frozenset({"runs:submit", "runs:void"})
    # The tool service forwards a run's submit (#287) but never voids a run.
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="tools",
        extra_scopes=scopes,
        runs=runs,
        submissions=submissions,
    ) as (address, context, _, _):
        tools = [
            request(
                address,
                context,
                "POST",
                f"/v1/runs/{OTHER}/{ending}",
                command({"run_id": OTHER}),
                headers(),
            )[0].status
            for ending in ("submit", "void")
        ]
    assert tools == [200, 403]
    assert [call[0] for call in submissions.calls] == ["accept_submission"]
    assert runs.calls == []
    submissions.calls.clear()
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="reader",
        extra_scopes=scopes,
        runs=runs,
        submissions=submissions,
    ) as (address, context, _, _):
        wrong_role = [
            request(
                address,
                context,
                "POST",
                f"/v1/runs/{OTHER}/{ending}",
                command({"run_id": OTHER}),
                headers(),
            )[0].status
            for ending in ("submit", "void")
        ]
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="orchestrator",
        extra_scopes=frozenset({"runs:create"}),
        runs=runs,
        submissions=submissions,
    ) as (address, context, _, _):
        missing_scope = [
            request(
                address,
                context,
                "POST",
                f"/v1/runs/{OTHER}/{ending}",
                command({"run_id": OTHER}),
                headers(),
            )[0].status
            for ending in ("submit", "void")
        ]
    assert wrong_role == [403, 403]
    assert missing_scope == [403, 403]
    assert runs.calls == [] and submissions.calls == []


def test_run_ending_conflict_and_unknown_run_come_through_unchanged(
    tmp_path: Path,
) -> None:
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="orchestrator",
        extra_scopes=frozenset({"runs:submit", "runs:void"}),
        runs=Refusing(UnavailableInput("void names an unknown run")),
        submissions=Refusing(StateConflict("run is void and accepts no submission")),
    ) as (address, context, _, _):
        submit_response, submit_body = request(
            address,
            context,
            "POST",
            f"/v1/runs/{OTHER}/submit",
            command({"run_id": OTHER}),
            headers(),
        )
        void_response, void_body = request(
            address,
            context,
            "POST",
            f"/v1/runs/{OTHER}/void",
            command({"run_id": OTHER, "reason": "model_stopped"}),
            headers(),
        )
    assert submit_response.status == 409
    assert json.loads(submit_body)["error"]["code"] == "state_conflict"
    assert void_response.status == 422
    assert json.loads(void_body)["error"]["code"] == "unavailable_input"


def test_rating_route_requires_rating_app_role_and_scope(tmp_path: Path) -> None:
    jobs = Jobs()
    ratings = Records()
    with server(
        jobs,
        _tls_material(tmp_path),
        role="rating_app",
        extra_scopes=frozenset({"ratings:record"}),
        ratings=ratings,
    ) as (address, context, _, _):
        response, _ = request(
            address, context, "POST", "/v1/ratings", command({}), headers()
        )
    assert response.status == 200
    assert ratings.calls[0][0] == "record"


def test_rating_app_may_seal_a_human_forecast_but_gains_no_other_authority(
    tmp_path: Path,
) -> None:
    jobs = Jobs()
    runs, snapshots, sheets, submissions = (
        Records(),
        Records(),
        Records(),
        Records(),
    )
    with server(
        jobs,
        _tls_material(tmp_path),
        role="rating_app",
        # Every scope a sealing route could check is granted here too, so a
        # 403 on runs/snapshots below can only come from the role gate, not
        # a missing scope.
        extra_scopes=frozenset(
            {
                "ratings:record",
                "sheets:seal",
                "submissions:submit",
                "runs:create",
                "snapshots:seal",
            }
        ),
        runs=runs,
        snapshots=snapshots,
        sheets=sheets,
        submissions=submissions,
    ) as (address, context, _, _):
        sheet_response, _ = request(
            address, context, "POST", "/v1/sheets", command({}), headers()
        )
        submission_response, _ = request(
            address, context, "POST", "/v1/submissions", command({}), headers()
        )
        forbidden_run, _ = request(
            address, context, "POST", "/v1/runs", command({}), headers()
        )
        forbidden_snapshot, _ = request(
            address, context, "POST", "/v1/snapshots", command({}), headers()
        )
    assert sheet_response.status == 200
    assert submission_response.status == 200
    assert forbidden_run.status == 403
    assert forbidden_snapshot.status == 403
    assert sheets.calls[0][0] == "seal"
    assert submissions.calls[0][0] == "submit"
    assert runs.calls == []
    assert snapshots.calls == []


def test_snapshot_read_routes_dispatch_to_documents_with_required_scope(
    tmp_path: Path,
) -> None:
    jobs = Jobs()
    documents = Documents()
    paper_a = "123e4567-e89b-42d3-a456-426614174010"
    paper_b = "123e4567-e89b-42d3-a456-426614174011"
    with server(
        jobs,
        _tls_material(tmp_path),
        role="tools",
        extra_scopes=frozenset({"snapshots:read"}),
        documents=documents,
    ) as (address, context, wrong_context, _):
        cards_response, cards_body = request(
            address,
            context,
            "GET",
            f"/v1/snapshots/{HASH}/cards?paper_id={paper_a}&paper_id={paper_b}",
        )
        graph_response, graph_body = request(
            address,
            context,
            "GET",
            f"/v1/snapshots/{HASH}/graph?paper_id={paper_a}&direction=citations&limit=5",
        )
        passages_response, passages_body = request(
            address,
            context,
            "GET",
            f"/v1/snapshots/{HASH}/passages?paper_id={paper_a}&passage_id={HASH}",
        )
        questions_response, questions_body = request(
            address,
            context,
            "GET",
            f"/v1/snapshots/{HASH}/questions?paper_id={paper_a}",
        )
        wrong_role_response, wrong_role_body = request(
            address,
            wrong_context,
            "GET",
            f"/v1/snapshots/{HASH}/cards?paper_id={paper_a}",
        )
        bad_query_response, bad_query_body = request(
            address, context, "GET", f"/v1/snapshots/{HASH}/graph?paper_id=not-a-uuid"
        )
    assert cards_response.status == 200
    cards_data = json.loads(cards_body)["data"]
    assert cards_data["snapshot_id"] == HASH
    assert [card["paper_version_id"] for card in cards_data["cards"]] == [
        paper_a,
        paper_b,
    ]
    assert documents.calls[0] == ("cards", (paper_a, paper_b))

    assert graph_response.status == 200
    graph_data = json.loads(graph_body)["data"]
    assert graph_data["direction"] == "citations"
    assert graph_data["graph"] == {"incoming": []}
    assert documents.calls[1] == ("graph", (paper_a,))

    assert passages_response.status == 200
    passages_data = json.loads(passages_body)["data"]
    assert passages_data["passages"] == [{"text_hash": HASH, "text": "matched text"}]

    assert questions_response.status == 200
    questions_data = json.loads(questions_body)["data"]
    assert questions_data["questions"] == [{"question_id": OTHER}]

    assert wrong_role_response.status == 404
    assert json.loads(wrong_role_body)["error"]["code"] == "not_found"

    assert bad_query_response.status == 422
    assert json.loads(bad_query_body)["error"]["code"] == "invalid_input"


def test_snapshot_read_routes_reject_a_route_outside_the_four_enumerated(
    tmp_path: Path,
) -> None:
    jobs = Jobs()
    documents = Documents()
    with server(
        jobs,
        _tls_material(tmp_path),
        role="tools",
        extra_scopes=frozenset({"snapshots:read"}),
        documents=documents,
    ) as (address, context, _, _):
        response, body = request(
            address, context, "GET", f"/v1/snapshots/{HASH}/passages/extra"
        )
    assert response.status == 404
    assert json.loads(body)["error"]["code"] == "not_found"


def test_snapshot_member_reads_serve_the_tools_role_only(tmp_path: Path) -> None:
    documents = Documents()
    family = PIN.paper_family_id
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="tools",
        extra_scopes=frozenset({"snapshots:read"}),
        documents=documents,
    ) as (address, context, wrong_context, _):
        base = f"/v1/snapshots/{HASH}"
        members = request(address, context, "GET", f"{base}/members")
        paged = request(
            address, context, "GET", f"{base}/members?cursor={family},{OTHER}"
        )
        bad_cursor = request(address, context, "GET", f"{base}/members?cursor={OTHER}")
        member = request(address, context, "GET", f"{base}/family?family_id={family}")
        absent = request(address, context, "GET", f"{base}/family?family_id={OTHER}")
        overviews = request(
            address,
            context,
            "GET",
            f"{base}/overviews?overview_hash={HASH}&overview_hash={'b' * 64}",
        )
        index = request(
            address, context, "GET", f"{base}/passage_index?passage_index_hash={HASH}"
        )
        repeated = request(
            address,
            context,
            "GET",
            f"{base}/overviews?overview_hash={HASH}&overview_hash={HASH}",
        )
        extra = request(address, context, "GET", f"{base}/members?paper_id={OTHER}")
        wrong_role = request(address, wrong_context, "GET", f"{base}/members")
    member_row = {
        "paper_family_id": family,
        "paper_version_id": PIN.paper_version_id,
        "card_hash": "b" * 64,
        "overview_hash": HASH,
        "passage_index_hash": "c" * 64,
        "graph_hash": None,
    }
    assert members[0].status == 200
    assert json.loads(members[1])["data"] == {
        "snapshot_id": HASH,
        "members": [member_row],
        "next_cursor": None,
    }
    assert json.loads(paged[1])["data"]["members"] == [member_row]
    assert bad_cursor[0].status == 422
    assert json.loads(member[1])["data"]["member"] == member_row
    assert absent[0].status == 422
    assert json.loads(absent[1])["error"]["code"] == "unavailable_input"
    assert [
        item["overview_hash"] for item in json.loads(overviews[1])["data"]["overviews"]
    ] == [HASH, "b" * 64]
    assert json.loads(index[1])["data"]["passage_index"] == {"passages": []}
    assert repeated[0].status == 422 and extra[0].status == 422
    assert wrong_role[0].status == 404
    assert json.loads(wrong_role[1])["error"]["code"] == "not_found"
    assert documents.calls[1] == ("members", (family, OTHER))
    assert [call[0] for call in documents.calls] == [
        "members",
        "members",
        "family_pin",
        "family_pin",
        "overviews",
        "passage_index_by_hash",
    ]


def test_snapshot_extraction_and_source_reads_serve_the_tools_role_only(
    tmp_path: Path,
) -> None:
    documents = Documents()
    family = PIN.paper_family_id
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="tools",
        extra_scopes=frozenset({"snapshots:read"}),
        documents=documents,
    ) as (address, context, wrong_context, _):
        base = f"/v1/snapshots/{HASH}"
        extraction = request(
            address, context, "GET", f"{base}/extraction?family_id={family}"
        )
        source = request(address, context, "GET", f"{base}/source?family_id={family}")
        absent = request(address, context, "GET", f"{base}/source?family_id={OTHER}")
        extra = request(
            address,
            context,
            "GET",
            f"{base}/source?family_id={family}&paper_id={OTHER}",
        )
        missing = request(address, context, "GET", f"{base}/extraction")
        wrong_role = request(
            address, wrong_context, "GET", f"{base}/source?family_id={family}"
        )
    assert json.loads(extraction[1])["data"] == {
        "snapshot_id": HASH,
        "paper_version_id": PIN.paper_version_id,
        "extraction_hash": HASH,
        "extraction": {"blocks": []},
    }
    assert source[0].status == 200
    assert source[1] == SOURCE
    assert source[0].getheader("Content-Type") == "application/pdf"
    assert source[0].getheader("ETag") == f'"{hashlib.sha256(SOURCE).hexdigest()}"'
    assert absent[0].status == 422
    assert json.loads(absent[1])["error"]["code"] == "unavailable_input"
    assert extra[0].status == 422 and missing[0].status == 422
    assert wrong_role[0].status == 404
    assert [call[0] for call in documents.calls] == ["extraction", "source", "source"]


def test_run_specification_serves_the_tools_role_with_its_own_scope(
    tmp_path: Path,
) -> None:
    queries = Queries()
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="tools",
        extra_scopes=frozenset({"runs:specification"}),
        queries=queries,
    ) as (address, context, wrong_context, _):
        found = request(address, context, "GET", f"/v1/runs/{OTHER}/specification")
        unknown = request(
            address, context, "GET", f"/v1/runs/{PRINCIPAL}/specification"
        )
        queried = request(
            address, context, "GET", f"/v1/runs/{OTHER}/specification?x=1"
        )
        # runs:specification does not widen runs:read: the inspector route
        # stays closed to the tool service.
        inspector_route = request(address, context, "GET", f"/v1/runs/{OTHER}")
        wrong_role = request(
            address, wrong_context, "GET", f"/v1/runs/{OTHER}/specification"
        )
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="tools",
        extra_scopes=frozenset({"runs:read"}),
        queries=queries,
    ) as (address, context, _, _):
        without_scope = request(
            address, context, "GET", f"/v1/runs/{OTHER}/specification"
        )
    assert json.loads(found[1])["data"] == {
        "run_id": OTHER,
        "snapshot_hash": HASH,
        "active": True,
    }
    assert unknown[0].status == 404
    assert queried[0].status == 404
    assert inspector_route[0].status == 404
    assert wrong_role[0].status == 404
    assert without_scope[0].status == 404
    assert queries.calls == [
        ("run_specification", (OTHER,)),
        ("run_specification", (str(PRINCIPAL),)),
    ]


def test_run_worker_read_serves_the_orchestrator_role_with_its_own_scope(
    tmp_path: Path,
) -> None:
    queries = Queries()
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="orchestrator",
        extra_scopes=frozenset({"runs:worker", "runs:specification"}),
        queries=queries,
    ) as (address, context, wrong_context, _):
        found = request(address, context, "GET", f"/v1/runs/{OTHER}/worker")
        unknown = request(address, context, "GET", f"/v1/runs/{uuid4()}/worker")
        promptless = request(address, context, "GET", f"/v1/runs/{PRINCIPAL}/worker")
        queried = request(address, context, "GET", f"/v1/runs/{OTHER}/worker?x=1")
        # runs:worker does not widen the inspector's run read, and the tool
        # service's specification read stays the tools role's.
        inspector_route = request(address, context, "GET", f"/v1/runs/{OTHER}")
        specification = request(
            address, context, "GET", f"/v1/runs/{OTHER}/specification"
        )
        scorer = request(address, wrong_context, "GET", f"/v1/runs/{OTHER}/worker")
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="tools",
        extra_scopes=frozenset({"runs:worker"}),
        queries=queries,
    ) as (address, context, _, _):
        tools = request(address, context, "GET", f"/v1/runs/{OTHER}/worker")
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="orchestrator",
        extra_scopes=frozenset({"runs:read", "runs:specification"}),
        queries=queries,
    ) as (address, context, _, _):
        without_scope = request(address, context, "GET", f"/v1/runs/{OTHER}/worker")
    assert json.loads(found[1])["data"] == {"run_id": OTHER, "prompt": "evidence first"}
    assert unknown[0].status == 404
    assert promptless[0].status == 422
    assert json.loads(promptless[1])["error"]["code"] == "unavailable_input"
    assert [
        response[0].status
        for response in (
            queried,
            inspector_route,
            specification,
            scorer,
            tools,
            without_scope,
        )
    ] == [404] * 6
    assert [call[0] for call in queries.calls] == ["run_worker"] * 3


def test_snapshot_description_serves_the_orchestrator_and_tools_roles(
    tmp_path: Path,
) -> None:
    queries = Queries()
    served = []
    for role in ("orchestrator", "tools"):
        with server(
            Jobs(),
            _tls_material(tmp_path),
            role=role,
            extra_scopes=frozenset({"snapshots:read"}),
            queries=queries,
        ) as (address, context, wrong_context, _):
            served.append(request(address, context, "GET", f"/v1/snapshots/{HASH}"))
            unknown = request(address, context, "GET", f"/v1/snapshots/{'b' * 64}")
            queried = request(address, context, "GET", f"/v1/snapshots/{HASH}?x=1")
            malformed = request(address, context, "GET", "/v1/snapshots/ABC")
            scorer = request(address, wrong_context, "GET", f"/v1/snapshots/{HASH}")
        assert [
            response[0].status for response in (unknown, queried, malformed, scorer)
        ] == [404] * 4
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="reader",
        extra_scopes=frozenset({"snapshots:read"}),
        queries=queries,
    ) as (address, context, _, _):
        reader = request(address, context, "GET", f"/v1/snapshots/{HASH}")
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="tools",
        extra_scopes=frozenset({"runs:specification"}),
        queries=queries,
    ) as (address, context, _, _):
        without_scope = request(address, context, "GET", f"/v1/snapshots/{HASH}")
    assert [json.loads(response[1])["data"] for response in served] == [
        {"snapshot_hash": HASH, "pinned_family_count": 1}
    ] * 2
    assert (reader[0].status, without_scope[0].status) == (404, 404)
    assert queries.calls == [
        ("snapshot", (HASH,)),
        ("snapshot", ("b" * 64,)),
        ("snapshot", (HASH,)),
        ("snapshot", ("b" * 64,)),
    ]


def test_embedding_view_read_serves_the_owner_role_only(tmp_path: Path) -> None:
    views = EmbeddingViews()
    base = "/v1/owner/papers"
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="owner",
        extra_scopes=frozenset({"owner:read"}),
        embedding_views=views,
    ) as (address, context, wrong_context, _):
        found = request(
            address, context, "GET", f"{base}/{PIN.paper_family_id}/embedding"
        )
        absent = request(address, context, "GET", f"{base}/{KEY}/embedding")
        unreadable = request(address, context, "GET", f"{base}/{OTHER}/embedding")
        queried = request(
            address, context, "GET", f"{base}/{PIN.paper_family_id}/embedding?x=1"
        )
        malformed = request(address, context, "GET", f"{base}/not-a-uuid/embedding")
        wrong_role = request(
            address, wrong_context, "GET", f"{base}/{PIN.paper_family_id}/embedding"
        )
    assert found[0].status == 200
    assert json.loads(found[1])["data"] == views.view
    assert absent[0].status == 404
    assert json.loads(absent[1])["error"]["code"] == "not_found"
    assert unreadable[0].status == 422
    assert json.loads(unreadable[1])["error"]["code"] == "unavailable_input"
    assert queried[0].status == 404 and malformed[0].status == 404
    assert wrong_role[0].status == 403
    assert json.loads(wrong_role[1])["error"]["code"] == "forbidden"
    # Neither the refused role nor a malformed route reached the repository.
    assert views.calls == [PIN.paper_family_id, KEY, OTHER]


def test_embedding_view_read_needs_the_owner_read_scope(tmp_path: Path) -> None:
    views = EmbeddingViews()
    with server(
        Jobs(), _tls_material(tmp_path), role="owner", embedding_views=views
    ) as (address, context, _, _):
        response = request(
            address,
            context,
            "GET",
            f"/v1/owner/papers/{PIN.paper_family_id}/embedding",
        )
    assert response[0].status == 403
    assert views.calls == []


def test_trace_routes_admit_only_the_tools_role_on_the_run_path(
    tmp_path: Path,
) -> None:
    trace = Records()
    scopes = frozenset({"trace:request", "trace:terminal"})
    requested = {"run_id": OTHER, "call_id": COMMAND}
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="tools",
        extra_scopes=scopes,
        trace=trace,
    ) as (address, context, _, _):
        request_response, _ = request(
            address,
            context,
            "POST",
            f"/v1/runs/{OTHER}/trace/requests",
            command(requested),
            headers(),
        )
        terminal_response, _ = request(
            address,
            context,
            "POST",
            f"/v1/runs/{OTHER}/trace/terminals",
            command(requested),
            headers(),
        )
        other_run, other_body = request(
            address,
            context,
            "POST",
            f"/v1/runs/{PRINCIPAL}/trace/requests",
            command(requested),
            headers(),
        )
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="orchestrator",
        extra_scopes=scopes,
        trace=trace,
    ) as (address, context, _, _):
        forbidden, forbidden_body = request(
            address,
            context,
            "POST",
            f"/v1/runs/{OTHER}/trace/requests",
            command(requested),
            headers(),
        )
    assert request_response.status == 200 and terminal_response.status == 200
    assert other_run.status == 422
    assert json.loads(other_body)["error"]["message"] == (
        "payload run_id differs from route"
    )
    assert forbidden.status == 403
    assert json.loads(forbidden_body)["error"]["code"] == "forbidden"
    assert [call[0] for call in trace.calls] == ["request", "terminal"]


def test_ask_routes_admit_only_the_tools_role_with_its_scope(tmp_path: Path) -> None:
    asks = Asks()
    scope = frozenset({"jev_asks:write"})
    reserved = {"run_id": OTHER}
    with server(
        Jobs(), _tls_material(tmp_path), role="tools", extra_scopes=scope, asks=asks
    ) as (address, context, _, _):
        writes = [
            request(
                address,
                context,
                "POST",
                f"/v1/runs/{OTHER}/asks/{route}",
                command(reserved),
                headers(),
            )[0].status
            for route in ("reservations", "settlements", "answers")
        ]
        other_run = request(
            address,
            context,
            "POST",
            f"/v1/runs/{PRINCIPAL}/asks/reservations",
            command(reserved),
            headers(),
        )[0]
        count, count_body = request(address, context, "GET", f"/v1/runs/{OTHER}/asks")
        kept, kept_body = request(
            address, context, "GET", f"/v1/runs/{OTHER}/asks/{HASH}"
        )
        absent = request(address, context, "GET", f"/v1/runs/{KEY}/asks/{HASH}")[0]
    refused = []
    for role, scopes in (("tools", frozenset({"trace:request"})), ("reader", scope)):
        with server(
            Jobs(), _tls_material(tmp_path), role=role, extra_scopes=scopes, asks=asks
        ) as (address, context, _, _):
            refused += [
                request(
                    address,
                    context,
                    "POST",
                    f"/v1/runs/{OTHER}/asks/reservations",
                    command(reserved),
                    headers(),
                )[0].status,
                request(address, context, "GET", f"/v1/runs/{OTHER}/asks")[0].status,
            ]

    assert writes == [200, 200, 200]
    assert [call[0] for call in asks.calls] == ["reserve", "settle", "record"]
    assert other_run.status == 422
    assert count.status == 200
    assert json.loads(count_body)["data"] == {"run_id": OTHER, "answered": 1}
    assert kept.status == 200
    assert json.loads(kept_body)["data"]["answer"] == "eyJraW5kIjoiYXNrIn0="
    assert absent.status == 404
    assert refused == [403, 403, 403, 403]


def test_trace_read_serves_the_owner_role_only(tmp_path: Path) -> None:
    trace = Records()
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="owner",
        extra_scopes=frozenset({"owner:read"}),
        trace=trace,
    ) as (address, context, wrong_context, _):
        found = request(address, context, "GET", f"/v1/runs/{OTHER}/trace")
        absent = request(address, context, "GET", f"/v1/runs/{KEY}/trace")
        unreadable = request(address, context, "GET", f"/v1/runs/{PRINCIPAL}/trace")
        queried = request(address, context, "GET", f"/v1/runs/{OTHER}/trace?x=1")
        wrong_role = request(address, wrong_context, "GET", f"/v1/runs/{OTHER}/trace")
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="tools",
        extra_scopes=frozenset({"owner:read", "trace:request"}),
        trace=trace,
    ) as (address, context, _, _):
        tools = request(address, context, "GET", f"/v1/runs/{OTHER}/trace")
    with server(Jobs(), _tls_material(tmp_path), role="owner", trace=trace) as (
        address,
        context,
        _,
        _,
    ):
        without_scope = request(address, context, "GET", f"/v1/runs/{OTHER}/trace")
    assert found[0].status == 200
    assert json.loads(found[1])["data"] == {
        "run_id": OTHER,
        "calls": [],
        "resources": None,
    }
    assert absent[0].status == 404
    assert json.loads(absent[1])["error"]["code"] == "not_found"
    assert unreadable[0].status == 422
    assert json.loads(unreadable[1])["error"]["code"] == "integrity_failure"
    assert queried[0].status == 404
    # The tool service that writes the trace cannot read it back.
    for refused in (wrong_role, tools, without_scope):
        assert refused[0].status == 403
        assert json.loads(refused[1])["error"]["code"] == "forbidden"
    assert trace.reads == [OTHER, KEY, str(PRINCIPAL)]


def test_trace_since_read_serves_the_owner_role_only(tmp_path: Path) -> None:
    trace = Records()
    path = "/v1/owner/trace/since"
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="owner",
        extra_scopes=frozenset({"owner:read"}),
        trace=trace,
    ) as (address, context, wrong_context, _):
        found = request(address, context, "GET", f"{path}?cursor=7&limit=20")
        default = request(address, context, "GET", f"{path}?cursor=0")
        malformed = [
            request(address, context, "GET", f"{path}{query}")
            for query in ("", "?cursor=-1", "?cursor=1&cursor=2", "?cursor=1&x=1")
        ]
        wrong_role = request(address, wrong_context, "GET", f"{path}?cursor=0")
    assert found[0].status == 200
    assert json.loads(found[1])["data"] == {"events": [], "cursor": 7}
    assert default[0].status == 200
    for refused in malformed:
        assert refused[0].status == 422
        assert json.loads(refused[1])["error"]["code"] == "invalid_input"
    assert wrong_role[0].status == 403
    assert trace.reads == ["since:7:20", "since:0:100"]


def test_owner_paper_and_run_reads_serve_the_owner_role_only(tmp_path: Path) -> None:
    queries = Queries()
    papers, runs = "/v1/owner/papers", "/v1/owner/runs"
    cursor = f"2026-09-22T00:00:00.000000Z,{KEY}"
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="owner",
        extra_scopes=frozenset({"owner:read"}),
        queries=queries,
    ) as (address, context, wrong_context, _):
        paper = request(address, context, "GET", f"{papers}/{OTHER}")
        paged = request(address, context, "GET", f"{papers}/{OTHER}?cursor={cursor}")
        run = request(address, context, "GET", f"{runs}/{OTHER}")
        absent_paper = request(address, context, "GET", f"{papers}/{KEY}")
        absent_run = request(address, context, "GET", f"{runs}/{KEY}")
        unreadable = request(address, context, "GET", f"{papers}/{PRINCIPAL}")
        bad_query = request(address, context, "GET", f"{papers}/{OTHER}?x=1")
        bad_cursor = request(address, context, "GET", f"{papers}/{OTHER}?cursor=x")
        run_query = request(address, context, "GET", f"{runs}/{OTHER}?cursor={cursor}")
        malformed = request(address, context, "GET", f"{papers}/not-a-uuid")
        wrong_role = request(address, wrong_context, "GET", f"{papers}/{OTHER}")
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=frozenset({"owner:read", "runs:read"}),
        queries=queries,
    ) as (address, context, _, _):
        inspector = request(address, context, "GET", f"{runs}/{OTHER}")
    with server(Jobs(), _tls_material(tmp_path), role="owner", queries=queries) as (
        address,
        context,
        _,
        _,
    ):
        without_scope = request(address, context, "GET", f"{papers}/{OTHER}")
    assert paper[0].status == 200 and paged[0].status == 200
    assert json.loads(paper[1])["data"]["runs"] == [{"run_id": OTHER}]
    assert json.loads(run[1])["data"] == {"run_id": OTHER, "ending": None}
    for absent in (absent_paper, absent_run, malformed):
        assert absent[0].status == 404
        assert json.loads(absent[1])["error"]["code"] == "not_found"
    assert unreadable[0].status == 422
    assert json.loads(unreadable[1])["error"]["code"] == "unavailable_input"
    for refused in (bad_query, bad_cursor, run_query):
        assert refused[0].status == 422
        assert json.loads(refused[1])["error"]["code"] == "invalid_input"
    for refused in (wrong_role, inspector, without_scope):
        assert refused[0].status == 403
        assert json.loads(refused[1])["error"]["code"] == "forbidden"
    # Only the owner's well-formed reads reached the queries, cursor parsed.
    assert queries.calls == [
        ("owner_paper", (OTHER, None)),
        ("owner_paper", (OTHER, ("2026-09-22T00:00:00.000000Z", KEY))),
        ("owner_run", (OTHER,)),
        ("owner_paper", (KEY, None)),
        ("owner_run", (KEY,)),
        ("owner_paper", (str(PRINCIPAL), None)),
    ]


def test_owner_run_listing_and_settlement_serve_the_owner_role_only(
    tmp_path: Path,
) -> None:
    queries = Queries()
    runs = "/v1/owner/runs"
    instant = "2026-09-22T00:00:00.000000Z"
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="owner",
        extra_scopes=frozenset({"owner:read"}),
        queries=queries,
    ) as (address, context, wrong_context, _):
        by_day = request(address, context, "GET", f"{runs}?day=2026-09-22")
        by_island = request(
            address,
            context,
            "GET",
            f"{runs}?island=quant-ph&since={instant}&cursor={instant},{KEY}",
        )
        settled = request(address, context, "GET", f"{runs}/{OTHER}/settlement")
        unsettled = request(address, context, "GET", f"{runs}/{KEY}/settlement")
        refused_queries = [
            request(address, context, "GET", f"{runs}{query}")
            for query in (
                "",
                "?day=2026-09-22&island=cs",
                "?day=22-09-2026",
                "?island=physics",
                "?day=2026-09-22&since=yesterday",
                "?day=2026-09-22&paper_id=x",
                "?day=2026-09-22&day=2026-09-23",
                f"?island=cs&cursor={instant}",
            )
        ]
        settlement_query = request(
            address, context, "GET", f"{runs}/{OTHER}/settlement?x=1"
        )
        wrong_list = request(address, wrong_context, "GET", f"{runs}?day=2026-09-22")
        wrong_settlement = request(
            address, wrong_context, "GET", f"{runs}/{OTHER}/settlement"
        )
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=frozenset({"owner:read", "runs:read"}),
        queries=queries,
    ) as (address, context, _, _):
        inspector = request(address, context, "GET", f"{runs}?day=2026-09-22")
    assert by_day[0].status == 200 and by_island[0].status == 200
    assert json.loads(by_day[1])["data"] == {
        "runs": [{"run_id": OTHER, "lineage_id": "lineage-1", "island": "cs"}],
        "next_cursor": f"{instant},{OTHER}",
    }
    assert json.loads(settled[1])["data"] == {"run_id": OTHER, "input_tokens": 3}
    assert unsettled[0].status == 404
    assert json.loads(unsettled[1])["error"]["code"] == "not_found"
    for refused in refused_queries:
        assert refused[0].status == 422
        assert json.loads(refused[1])["error"]["code"] == "invalid_input"
    assert settlement_query[0].status == 404
    for refused in (wrong_list, wrong_settlement, inspector):
        assert refused[0].status == 403
        assert json.loads(refused[1])["error"]["code"] == "forbidden"
    # Only the owner's well-formed reads reached the queries, each parsed.
    assert queries.calls == [
        ("owner_runs", ("2026-09-22", None, None, None)),
        ("owner_runs", (None, "quant-ph", instant, (instant, KEY))),
        ("run_settlement", (OTHER,)),
        ("run_settlement", (KEY,)),
    ]


def test_owner_islands_serve_the_owner_role_only(tmp_path: Path) -> None:
    queries = Queries()
    islands = "/v1/owner/islands"
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="owner",
        extra_scopes=frozenset({"owner:read"}),
        queries=queries,
    ) as (address, context, wrong_context, _):
        listed = request(address, context, "GET", islands)
        argued = request(address, context, "GET", f"{islands}?island=cs")
        wrong = request(address, wrong_context, "GET", islands)
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=frozenset({"owner:read", "runs:read"}),
        queries=queries,
    ) as (address, context, _, _):
        inspector = request(address, context, "GET", islands)
    assert listed[0].status == 200
    assert json.loads(listed[1])["data"] == {
        "islands": [{"island": "cs", "genomes": 2}]
    }
    assert argued[0].status == 422
    for refused in (wrong, inspector):
        assert refused[0].status == 403
    assert queries.calls == [("owner_islands", ())]


def test_owner_reports_serve_the_owner_role_only(tmp_path: Path) -> None:
    queries = Queries()
    reports = "/v1/owner/reports"
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="owner",
        extra_scopes=frozenset({"owner:read"}),
        queries=queries,
    ) as (address, context, wrong_context, _):
        listed = request(address, context, "GET", reports)
        argued = request(address, context, "GET", f"{reports}?island=cs")
        wrong = request(address, wrong_context, "GET", reports)
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=frozenset({"owner:read", "runs:read"}),
        queries=queries,
    ) as (address, context, _, _):
        inspector = request(address, context, "GET", reports)
    assert listed[0].status == 200
    assert json.loads(listed[1])["data"] == {
        "reports": [{"island": "cs", "iso_week": "2026-W39", "digests": 1}]
    }
    assert argued[0].status == 422
    for refused in (wrong, inspector):
        assert refused[0].status == 403
    assert queries.calls == [("owner_reports", ())]


def test_owner_impact_serves_the_owner_role_only(tmp_path: Path) -> None:
    queries = Queries()
    impact = "/v1/owner/impact"
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="owner",
        extra_scopes=frozenset({"owner:read"}),
        queries=queries,
    ) as (address, context, wrong_context, _):
        listed = request(address, context, "GET", impact)
        argued = request(address, context, "GET", f"{impact}?island=cs")
        wrong = request(address, wrong_context, "GET", impact)
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=frozenset({"owner:read", "runs:read"}),
        queries=queries,
    ) as (address, context, _, _):
        inspector = request(address, context, "GET", impact)
    assert listed[0].status == 200
    assert json.loads(listed[1])["data"] == {
        "impact": [{"island": "cs", "iso_week": "2026-W39", "ratings": 1}]
    }
    assert argued[0].status == 422
    for refused in (wrong, inspector):
        assert refused[0].status == 403
    assert queries.calls == [("owner_impact", ())]


def test_owner_models_serves_the_owner_role_only(tmp_path: Path) -> None:
    queries = Queries()
    models = "/v1/owner/models"
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="owner",
        extra_scopes=frozenset({"owner:read"}),
        queries=queries,
    ) as (address, context, wrong_context, _):
        listed = request(address, context, "GET", models)
        argued = request(address, context, "GET", f"{models}?island=cs")
        wrong = request(address, wrong_context, "GET", models)
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=frozenset({"owner:read", "runs:read"}),
        queries=queries,
    ) as (address, context, _, _):
        inspector = request(address, context, "GET", models)
    assert listed[0].status == 200
    assert json.loads(listed[1])["data"] == {
        "models": [{"manifest_hash": "a" * 64, "runs": 2}]
    }
    assert argued[0].status == 422
    for refused in (wrong, inspector):
        assert refused[0].status == 403
    assert queries.calls == [("owner_models", ())]


def test_owner_cost_days_serves_one_day_to_the_owner_only(tmp_path: Path) -> None:
    queries = Queries()
    days = "/v1/owner/costs/days"
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="owner",
        extra_scopes=frozenset({"owner:read"}),
        queries=queries,
    ) as (address, context, wrong_context, _):
        listed = request(address, context, "GET", f"{days}?day=2026-09-24")
        bare = request(address, context, "GET", days)
        twice = request(
            address, context, "GET", f"{days}?day=2026-09-24&day=2026-09-23"
        )
        argued = request(address, context, "GET", f"{days}?day=2026-09-24&island=cs")
        wrong = request(address, wrong_context, "GET", f"{days}?day=2026-09-24")
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=frozenset({"owner:read", "runs:read"}),
        queries=queries,
    ) as (address, context, _, _):
        inspector = request(address, context, "GET", f"{days}?day=2026-09-24")
    assert listed[0].status == 200
    assert json.loads(listed[1])["data"] == {
        "days": [{"day": "2026-09-24", "island": "cs", "priced_micros": 5}]
    }
    for invalid in (bare, twice, argued):
        assert invalid[0].status == 422
    for refused in (wrong, inspector):
        assert refused[0].status == 403
    assert queries.calls == [("owner_cost_days", ("2026-09-24",))]


def test_owner_day_serves_one_day_to_the_owner_only(tmp_path: Path) -> None:
    queries = Queries()
    day = "/v1/owner/day"
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="owner",
        extra_scopes=frozenset({"owner:read"}),
        queries=queries,
    ) as (address, context, wrong_context, _):
        read = request(address, context, "GET", f"{day}?day=2026-09-24")
        bare = request(address, context, "GET", day)
        argued = request(address, context, "GET", f"{day}?day=2026-09-24&island=cs")
        wrong = request(address, wrong_context, "GET", f"{day}?day=2026-09-24")
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=frozenset({"owner:read", "runs:read"}),
        queries=queries,
    ) as (address, context, _, _):
        inspector = request(address, context, "GET", f"{day}?day=2026-09-24")
    assert read[0].status == 200
    assert json.loads(read[1])["data"] == {
        "day": "2026-09-24",
        "runs": [],
        "digests": [],
    }
    for invalid in (bare, argued):
        assert invalid[0].status == 422
    for refused in (wrong, inspector):
        assert refused[0].status == 403
    assert queries.calls == [("owner_day", ("2026-09-24",))]


def test_owner_agents_serves_the_owner_role_only(tmp_path: Path) -> None:
    queries = Queries()
    agents = "/v1/owner/agents"
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="owner",
        extra_scopes=frozenset({"owner:read"}),
        queries=queries,
    ) as (address, context, wrong_context, _):
        listed = request(address, context, "GET", agents)
        argued = request(address, context, "GET", f"{agents}?island=cs")
        wrong = request(address, wrong_context, "GET", agents)
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=frozenset({"owner:read", "runs:read"}),
        queries=queries,
    ) as (address, context, _, _):
        inspector = request(address, context, "GET", agents)
    assert listed[0].status == 200
    assert json.loads(listed[1])["data"] == {
        "agents": [{"configuration_id": KEY, "island": "cs", "runs": 3}]
    }
    assert argued[0].status == 422
    for refused in (wrong, inspector):
        assert refused[0].status == 403
    assert queries.calls == [("owner_agents", ())]


def test_owner_agent_runs_page_one_genome_for_the_owner_only(
    tmp_path: Path,
) -> None:
    queries = Queries()
    runs = f"/v1/owner/agents/{KEY}/runs"
    cursor = "2026-01-01T00:00:00.000000Z," + OTHER
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="owner",
        extra_scopes=frozenset({"owner:read"}),
        queries=queries,
    ) as (address, context, wrong_context, _):
        read = request(address, context, "GET", runs)
        paged = request(address, context, "GET", f"{runs}?cursor={cursor}")
        unknown = request(address, context, "GET", f"/v1/owner/agents/{OTHER}/runs")
        malformed = request(address, context, "GET", "/v1/owner/agents/x/runs")
        argued = request(address, context, "GET", f"{runs}?island=cs")
        wrong = request(address, wrong_context, "GET", runs)
    assert read[0].status == 200
    assert json.loads(read[1])["data"] == {
        "days": [],
        "runs": [],
        "next_cursor": cursor,
    }
    assert paged[0].status == 200
    for missing in (unknown, malformed):
        assert missing[0].status == 404
    assert argued[0].status == 422
    assert wrong[0].status == 403
    assert queries.calls == [
        ("owner_agent_runs", (KEY, None)),
        ("owner_agent_runs", (KEY, ("2026-01-01T00:00:00.000000Z", OTHER))),
        ("owner_agent_runs", (OTHER, None)),
    ]


def test_owner_run_record_serves_one_run_to_the_owner_only(
    tmp_path: Path,
) -> None:
    queries = Queries()
    record = f"/v1/owner/runs/{KEY}/record"
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="owner",
        extra_scopes=frozenset({"owner:read"}),
        queries=queries,
    ) as (address, context, wrong_context, _):
        read = request(address, context, "GET", record)
        unknown = request(address, context, "GET", f"/v1/owner/runs/{OTHER}/record")
        malformed = request(address, context, "GET", "/v1/owner/runs/x/record")
        argued = request(address, context, "GET", f"{record}?island=cs")
        wrong = request(address, wrong_context, "GET", record)
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=frozenset({"owner:read", "runs:read"}),
        queries=queries,
    ) as (address, context, _, _):
        inspector = request(address, context, "GET", record)
    assert read[0].status == 200
    assert json.loads(read[1])["data"] == {"island": "cs", "calls": []}
    for missing in (unknown, malformed):
        assert missing[0].status == 404
    assert argued[0].status == 422
    for refused in (wrong, inspector):
        assert refused[0].status == 403
    assert queries.calls == [
        ("owner_run_record", (KEY,)),
        ("owner_run_record", (OTHER,)),
    ]


def test_owner_paper_documents_serve_the_pdf_list_and_bytes_to_the_owner_only(
    tmp_path: Path,
) -> None:
    queries = Queries()
    listed = f"/v1/owner/papers/{KEY}/documents"
    document = f"/v1/owner/documents/{HASH}"
    with server(
        Jobs(),
        _tls_material(tmp_path),
        artifact=True,
        role="owner",
        extra_scopes=frozenset({"owner:read"}),
        queries=queries,
    ) as (address, context, wrong_context, _):
        read = request(address, context, "GET", listed)
        malformed = request(address, context, "GET", "/v1/owner/papers/x/documents")
        argued = request(address, context, "GET", f"{listed}?cursor=1")
        wrong = request(address, wrong_context, "GET", listed)
        pdf = request(address, context, "GET", document)
        other = request(address, context, "GET", f"/v1/owner/documents/{'b' * 64}")
        bad_hash = request(address, context, "GET", "/v1/owner/documents/x")
        wrong_pdf = request(address, wrong_context, "GET", document)
    with server(
        Jobs(),
        _tls_material(tmp_path),
        artifact=True,
        role="inspector",
        extra_scopes=frozenset({"owner:read", "runs:read"}),
        queries=queries,
    ) as (address, context, _, _):
        inspector = request(address, context, "GET", document)
    assert read[0].status == 200
    assert json.loads(read[1])["data"] == {
        "paper_id": KEY,
        "documents": [{"artifact_hash": HASH, "byte_length": 7}],
    }
    assert pdf[0].status == 200
    assert pdf[1] == b"payload"
    assert pdf[0].getheader("ETag") == f'"{HASH}"'
    for missing in (malformed, other, bad_hash):
        assert missing[0].status == 404
    assert argued[0].status == 422
    for refused in (wrong, wrong_pdf, inspector):
        assert refused[0].status == 403
    assert queries.calls == [
        ("owner_paper_documents", (KEY,)),
        ("owner_document", (HASH,)),
        ("owner_document", ("b" * 64,)),
    ]


def test_owner_island_serves_one_named_island_to_the_owner_only(
    tmp_path: Path,
) -> None:
    queries = Queries()
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="owner",
        extra_scopes=frozenset({"owner:read"}),
        queries=queries,
    ) as (address, context, wrong_context, _):
        read = request(address, context, "GET", "/v1/owner/islands/quant-ph")
        unknown = request(address, context, "GET", "/v1/owner/islands/atoll")
        argued = request(address, context, "GET", "/v1/owner/islands/cs?week=1")
        wrong = request(address, wrong_context, "GET", "/v1/owner/islands/cs")
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=frozenset({"owner:read", "runs:read"}),
        queries=queries,
    ) as (address, context, _, _):
        inspector = request(address, context, "GET", "/v1/owner/islands/cs")
    assert read[0].status == 200
    assert json.loads(read[1])["data"] == {
        "island": "quant-ph",
        "genomes": [{"lineage_id": "lineage-1", "runs": 3}],
    }
    assert unknown[0].status == 404
    assert argued[0].status == 422
    for refused in (wrong, inspector):
        assert refused[0].status == 403
    assert queries.calls == [("owner_island", ("quant-ph",))]


def test_owner_report_selection_serves_one_island_week_to_the_owner_only(
    tmp_path: Path,
) -> None:
    queries = Queries()
    selection = "/v1/owner/reports/cs/2026-W39/selection"
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="owner",
        extra_scopes=frozenset({"owner:read"}),
        queries=queries,
    ) as (address, context, wrong_context, _):
        read = request(address, context, "GET", selection)
        unknown = request(
            address, context, "GET", "/v1/owner/reports/atoll/2026-W39/selection"
        )
        unparted = request(address, context, "GET", "/v1/owner/reports/cs/selection")
        nested = request(
            address, context, "GET", "/v1/owner/reports/cs/2026-W39/x/selection"
        )
        argued = request(address, context, "GET", f"{selection}?week=1")
        wrong = request(address, wrong_context, "GET", selection)
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=frozenset({"owner:read", "runs:read"}),
        queries=queries,
    ) as (address, context, _, _):
        inspector = request(address, context, "GET", selection)
    assert read[0].status == 200
    assert json.loads(read[1])["data"] == {
        "island": "cs",
        "iso_week": "2026-W39",
        "archived": [],
    }
    for missing in (unknown, unparted, nested):
        assert missing[0].status == 404
    assert argued[0].status == 422
    for refused in (wrong, inspector):
        assert refused[0].status == 403
    assert queries.calls == [
        ("owner_report_selection", ("cs", "2026-W39")),
        ("owner_report_selection", ("atoll", "2026-W39")),
    ]


def test_inspector_routes_dispatch_to_queries_with_required_role_and_scope(
    tmp_path: Path,
) -> None:
    jobs = Jobs()
    queries = Queries()
    with server(
        jobs,
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=frozenset({"runs:read", "submissions:read", "manifests:read"}),
        queries=queries,
    ) as (address, context, wrong_context, _):
        run_response, run_body = request(address, context, "GET", f"/v1/runs/{OTHER}")
        runs_response, runs_body = request(
            address, context, "GET", f"/v1/runs?configuration_id={OTHER}"
        )
        submissions_response, submissions_body = request(
            address, context, "GET", f"/v1/submissions?submitter_id={OTHER}"
        )
        manifest_response, manifest_body = request(
            address, context, "GET", f"/v1/manifests/{HASH}"
        )
        missing_run, missing_run_body = request(
            address, context, "GET", f"/v1/runs/{PRINCIPAL}"
        )
        wrong_role_response, wrong_role_body = request(
            address, wrong_context, "GET", f"/v1/runs/{OTHER}"
        )
    assert run_response.status == 200
    assert json.loads(run_body)["data"]["run_id"] == OTHER
    assert runs_response.status == 200
    assert json.loads(runs_body)["data"]["runs"] == [{"run_id": OTHER}]
    assert json.loads(runs_body)["data"]["next_cursor"] is None
    assert submissions_response.status == 200
    assert json.loads(submissions_body)["data"]["submissions"] == [
        {"submission_id": OTHER}
    ]
    assert manifest_response.status == 200
    assert json.loads(manifest_body)["data"]["artifact_hash"] == HASH
    assert missing_run.status == 404
    assert json.loads(missing_run_body)["error"]["code"] == "not_found"
    assert wrong_role_response.status == 404
    assert json.loads(wrong_role_body)["error"]["code"] == "not_found"
    assert queries.calls[0] == ("run", (OTHER,))
    assert queries.calls[1] == ("runs_by_configuration", (OTHER, None))
    assert queries.calls[2] == ("submissions_by_submitter", (OTHER,))
    assert queries.calls[3] == ("manifest", (HASH,))


def test_inspector_run_listing_round_trips_a_cursor(tmp_path: Path) -> None:
    jobs = Jobs()
    queries = Queries()
    with server(
        jobs,
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=frozenset({"runs:read"}),
        queries=queries,
    ) as (address, context, _, _):
        response, body = request(
            address,
            context,
            "GET",
            f"/v1/runs?configuration_id={OTHER}&cursor="
            f"2026-09-22T00%3A00%3A00.000000Z%2C{OTHER}",
        )
    assert response.status == 200
    assert queries.calls[0] == (
        "runs_by_configuration",
        (OTHER, ("2026-09-22T00:00:00.000000Z", OTHER)),
    )


def test_inspector_routes_reject_malformed_query_parameters(tmp_path: Path) -> None:
    jobs = Jobs()
    queries = Queries()
    with server(
        jobs,
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=frozenset({"runs:read", "submissions:read", "manifests:read"}),
        queries=queries,
    ) as (address, context, _, _):
        bad_configuration, bad_configuration_body = request(
            address, context, "GET", "/v1/runs?configuration_id=not-a-uuid"
        )
        bad_cursor, bad_cursor_body = request(
            address,
            context,
            "GET",
            f"/v1/runs?configuration_id={OTHER}&cursor=not-a-cursor",
        )
        bad_submitter, bad_submitter_body = request(
            address, context, "GET", "/v1/submissions?submitter_id=not-a-uuid"
        )
        manifest_with_query, manifest_with_query_body = request(
            address, context, "GET", f"/v1/manifests/{HASH}?extra=1"
        )
    assert bad_configuration.status == 422
    assert json.loads(bad_configuration_body)["error"]["code"] == "invalid_input"
    assert bad_cursor.status == 422
    assert json.loads(bad_cursor_body)["error"]["code"] == "invalid_input"
    assert bad_submitter.status == 422
    assert json.loads(bad_submitter_body)["error"]["code"] == "invalid_input"
    assert manifest_with_query.status == 404
    assert json.loads(manifest_with_query_body)["error"]["code"] == "not_found"
    assert queries.calls == []


def test_run_listing_selects_by_batch_or_paper(tmp_path: Path) -> None:
    queries = Queries()
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=frozenset({"runs:read"}),
        queries=queries,
    ) as (address, context, _, _):
        batch, batch_body = request(
            address, context, "GET", f"/v1/runs?batch_id={HASH}"
        )
        paper, paper_body = request(
            address,
            context,
            "GET",
            "/v1/runs?paper_id=arxiv%3A2409.00001&cursor="
            f"2026-09-22T00%3A00%3A00.000000Z%2C{OTHER}",
        )
    assert batch.status == 200
    assert json.loads(batch_body)["data"] == {"runs": [], "next_cursor": None}
    assert paper.status == 200
    assert json.loads(paper_body)["data"]["runs"] == [
        {"run_id": OTHER, "paper_id": "arxiv:2409.00001"}
    ]
    assert queries.calls == [
        ("runs_by_batch", (HASH, None)),
        (
            "runs_by_paper",
            ("arxiv:2409.00001", ("2026-09-22T00:00:00.000000Z", OTHER)),
        ),
    ]


def test_run_listing_requires_exactly_one_admitted_filter(tmp_path: Path) -> None:
    queries = Queries()
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=frozenset({"runs:read"}),
        queries=queries,
    ) as (address, context, _, _):
        responses = [
            request(address, context, "GET", path)
            for path in (
                "/v1/runs",
                f"/v1/runs?batch_id={HASH}&paper_id=p",
                f"/v1/runs?batch_id={HASH}&batch_id={HASH}",
                f"/v1/runs?configuration_id={OTHER}&extra=1",
                "/v1/runs?batch_id=not-a-hash",
                f"/v1/runs?paper_id={'p' * 129}",
            )
        ]
    for response, body in responses:
        assert response.status == 422
        assert json.loads(body)["error"]["code"] == "invalid_input"
    assert queries.calls == []


def test_sheet_read_needs_the_inspector_role_and_forecasts_scope(
    tmp_path: Path,
) -> None:
    queries = Queries()
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=frozenset({"forecasts:read"}),
        queries=queries,
    ) as (address, context, wrong_context, _):
        found, found_body = request(address, context, "GET", f"/v1/sheets/{HASH}")
        missing, _ = request(address, context, "GET", f"/v1/sheets/{'b' * 64}")
        with_query, _ = request(address, context, "GET", f"/v1/sheets/{HASH}?x=1")
        wrong_role, _ = request(address, wrong_context, "GET", f"/v1/sheets/{HASH}")
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=frozenset({"runs:read"}),
        queries=Queries(),
    ) as (address, context, _, _):
        unscoped, _ = request(address, context, "GET", f"/v1/sheets/{HASH}")
    assert found.status == 200
    assert json.loads(found_body)["data"]["questions"] == [{"question_id": OTHER}]
    assert missing.status == 404
    assert with_query.status == 404
    assert wrong_role.status == 404
    assert unscoped.status == 404
    assert queries.calls == [("sheet", (HASH,)), ("sheet", ("b" * 64,))]


POPULATION_SCOPES = frozenset({"configurations:read", "forecasts:read"})


def test_population_routes_dispatch_to_queries_for_the_inspector_role(
    tmp_path: Path,
) -> None:
    queries = Queries()
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=POPULATION_SCOPES,
        queries=queries,
    ) as (address, context, _, _):
        listing, listing_body = request(address, context, "GET", "/v1/configurations")
        single, single_body = request(
            address, context, "GET", f"/v1/configurations/{OTHER}"
        )
        missing, missing_body = request(
            address, context, "GET", f"/v1/configurations/{PRINCIPAL}"
        )
        forecasts, forecasts_body = request(
            address, context, "GET", f"/v1/configurations/{OTHER}/forecasts"
        )
    assert listing.status == 200
    assert json.loads(listing_body)["data"] == {
        "configurations": [{"configuration_id": OTHER}],
        "next_cursor": f"2026-09-22T00:00:00.000000Z,{OTHER}",
    }
    assert single.status == 200
    assert json.loads(single_body)["data"]["configuration_id"] == OTHER
    assert missing.status == 404
    assert json.loads(missing_body)["error"]["code"] == "not_found"
    assert forecasts.status == 200
    assert json.loads(forecasts_body)["data"] == {
        "forecasts": [{"submission_id": OTHER, "resolution": None}],
        "next_cursor": None,
    }
    assert queries.calls == [
        ("configurations", (None,)),
        ("configuration", (OTHER,)),
        ("configuration", (str(PRINCIPAL),)),
        ("forecasts_by_configuration", (OTHER, None)),
    ]


def test_population_routes_are_refused_without_the_inspector_role(
    tmp_path: Path,
) -> None:
    queries = Queries()
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="scorer",
        extra_scopes=POPULATION_SCOPES,
        queries=queries,
    ) as (address, context, wrong_context, _):
        responses = [
            request(address, selected, "GET", path)
            for selected in (context, wrong_context)
            for path in (
                "/v1/configurations",
                f"/v1/configurations/{OTHER}",
                f"/v1/configurations/{OTHER}/forecasts",
            )
        ]
    for response, body in responses:
        assert response.status == 404
        assert json.loads(body)["error"]["code"] == "not_found"
    assert queries.calls == []


def test_population_routes_are_refused_without_their_scope(tmp_path: Path) -> None:
    queries = Queries()
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=frozenset({"runs:read"}),
        queries=queries,
    ) as (address, context, _, _):
        responses = [
            request(address, context, "GET", path)
            for path in (
                "/v1/configurations",
                f"/v1/configurations/{OTHER}",
                f"/v1/configurations/{OTHER}/forecasts",
            )
        ]
    for response, _body in responses:
        assert response.status == 404
    assert queries.calls == []


def test_population_listings_round_trip_a_cursor_and_reject_malformed_ones(
    tmp_path: Path,
) -> None:
    queries = Queries()
    cursor = f"2026-09-22T00%3A00%3A00.000000Z%2C{OTHER}"
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=POPULATION_SCOPES,
        queries=queries,
    ) as (address, context, _, _):
        listing, _ = request(
            address, context, "GET", f"/v1/configurations?cursor={cursor}"
        )
        forecasts, _ = request(
            address,
            context,
            "GET",
            f"/v1/configurations/{OTHER}/forecasts?cursor={cursor}",
        )
        bad_cursor, bad_cursor_body = request(
            address, context, "GET", "/v1/configurations?cursor=not-a-cursor"
        )
        extra, extra_body = request(
            address, context, "GET", "/v1/configurations?island=cs"
        )
        with_query, _ = request(
            address, context, "GET", f"/v1/configurations/{OTHER}?extra=1"
        )
        bad_id, _ = request(address, context, "GET", "/v1/configurations/not-a-uuid")
    assert listing.status == 200
    assert forecasts.status == 200
    assert bad_cursor.status == 422
    assert json.loads(bad_cursor_body)["error"]["code"] == "invalid_input"
    assert extra.status == 422
    assert json.loads(extra_body)["error"]["code"] == "invalid_input"
    assert with_query.status == 404
    assert bad_id.status == 404
    decoded = ("2026-09-22T00:00:00.000000Z", OTHER)
    assert queries.calls == [
        ("configurations", (decoded,)),
        ("forecasts_by_configuration", (OTHER, decoded)),
    ]


def test_owner_questions_serve_the_owner_role_only(tmp_path: Path) -> None:
    queries = Queries()
    questions = "/v1/owner/questions"
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="owner",
        extra_scopes=frozenset({"owner:read"}),
        queries=queries,
    ) as (address, context, wrong_context, _):
        listed = request(address, context, "GET", questions)
        argued = request(address, context, "GET", f"{questions}?island=cs")
        one = request(address, context, "GET", f"{questions}/{KEY}")
        missing = request(address, context, "GET", f"{questions}/{OTHER}")
        malformed = request(address, context, "GET", f"{questions}/not-a-uuid")
        wrong = request(address, wrong_context, "GET", f"{questions}/{KEY}")
    with server(
        Jobs(),
        _tls_material(tmp_path),
        role="inspector",
        extra_scopes=frozenset({"owner:read", "runs:read"}),
        queries=queries,
    ) as (address, context, _, _):
        inspector = request(address, context, "GET", questions)
    assert listed[0].status == 200
    assert json.loads(listed[1])["data"] == {
        "questions": [{"question_id": KEY, "runs": 1}]
    }
    assert one[0].status == 200
    assert json.loads(one[1])["data"] == {"question_id": KEY, "runs": []}
    assert argued[0].status == 422
    for absent in (missing, malformed):
        assert absent[0].status == 404
    for refused in (wrong, inspector):
        assert refused[0].status == 403
    assert queries.calls == [
        ("owner_questions", ()),
        ("owner_question", (KEY,)),
        ("owner_question", (OTHER,)),
    ]
