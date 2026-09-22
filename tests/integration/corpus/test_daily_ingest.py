"""The daily ingest job resumes through real storage without repeating or
skipping listing work, and seals one sorted batch record per day.

Real PostgreSQL, the real storage service over mTLS and real HTTPS requests to
a loopback server standing in for arXiv. Nothing about storage, checkpoints
or HTTP framing is mocked; only the remote content is synthetic.
"""

from __future__ import annotations

import ssl
import subprocess
import threading
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from research_agent.contracts.primitives import ProducerVersion
from research_agent.ingest.arxiv import fetch_document, fetch_listing_page
from research_agent.ingest.daily import DailyWindow, advance, run_once
from research_agent.ingest.fetch import FetchedOpenAlexPage
from research_agent.ingest.pilot import Identity, PilotWorker, RateGate, Sources
from research_agent.ingest.pilot_local import local_storage, worker_principal

pytestmark = pytest.mark.integration

IDENTITY = Identity(
    ProducerVersion("a" * 64, "b" * 40, 1), "c" * 64, "d" * 64, "e" * 64
)
WINDOW = DailyWindow("2026-01-01", "2026-01-02")


def _record(family: str, submitted: str, categories: str) -> str:
    return f"""<record><header><identifier>oai:arXiv.org:{family}</identifier>
<datestamp>2026-01-02</datestamp></header><metadata>
<arXivRaw xmlns="http://arxiv.org/OAI/arXivRaw/"><id>{family}</id>
<version version="v1"><date>{submitted}</date></version>
<title>Paper {family}</title><categories>{categories}</categories>
<license>http://creativecommons.org/licenses/by/4.0/</license>
<abstract>Abstract {family}</abstract></arXivRaw></metadata></record>"""


def _oai(records: list[str], token: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><ListRecords>'
        + "".join(records)
        + f'<resumptionToken completeListSize="3">{token}</resumptionToken>'
        "</ListRecords></OAI-PMH>"
    ).encode()


JAN2 = "Fri, 02 Jan 2026 09:00:00 GMT"
AI_PAGES = {
    None: _oai([_record("2601.00001", JAN2, "cs.AI")], "ai-t1"),
    "ai-t1": _oai([_record("2601.00002", JAN2, "cs.AI cs.LG")], ""),
}
LG_PAGES = {
    None: _oai(
        [
            _record("2601.00002", JAN2, "cs.AI cs.LG"),
            _record("2601.00003", JAN2, "cs.LG"),
        ],
        "",
    ),
}


class Remote:
    """Loopback HTTPS source with a request log."""

    def __init__(self) -> None:
        self.log: Counter[str] = Counter()

    def respond(self, path: str) -> tuple[int, bytes, str]:
        self.log[path] += 1
        url = urlsplit(path)
        query = {key: values[0] for key, values in parse_qs(url.query).items()}
        if url.path == "/oai":
            token = query.get("resumptionToken")
            # A resumption-token request carries no `set`, matching the real
            # OAI-PMH continuation contract: the token alone must resolve it.
            if token is not None:
                pages = AI_PAGES if token in AI_PAGES else LG_PAGES
            else:
                pages = AI_PAGES if query.get("set") == "cs:cs:AI" else LG_PAGES
            return 200, pages[token], "text/xml"
        if url.path.startswith(("/src/", "/pdf/")):
            return 200, b"%PDF-1.5 original", "application/pdf"
        return 404, b"", "text/plain"


@contextmanager
def _remote(tmp_path: Path) -> Iterator[tuple[Remote, int, ssl.SSLContext]]:
    key, cert = tmp_path / "remote.key", tmp_path / "remote.pem"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days",
            "1", "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
            "-keyout", str(key), "-out", str(cert),
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    remote = Remote()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            status, body, media = remote.respond(self.path)
            self.send_response(status)
            self.send_header("Content-Type", media)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("localhost", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield remote, server.server_port, ssl.create_default_context(cafile=str(cert))
    finally:
        server.shutdown()
        server.server_close()


class Killed(Exception):
    """Stands in for the worker process dying between two requests."""


def _no_citations(*_args: object, **_kwargs: object) -> FetchedOpenAlexPage:
    raise AssertionError("the daily ingest job does not capture citations")


def _sources(
    port: int, context: ssl.SSLContext, *, die_before_listing_call: int | None = None
) -> Sources:
    calls = Counter[str]()

    def listing(path: str):  # type: ignore[no-untyped-def]
        calls["listing"] += 1
        if calls["listing"] == die_before_listing_call:
            raise Killed()
        return fetch_listing_page(path, host="localhost", port=port, context=context)

    def document(path: str):  # type: ignore[no-untyped-def]
        return fetch_document(path, host="localhost", port=port, context=context)

    return Sources(
        listing=listing,
        document=document,
        openalex_match=_no_citations,
        openalex_cites=_no_citations,
        arxiv_gate=RateGate(0.001),
        openalex_gate=RateGate(0.001),
    )


def _expire_running_leases(storage) -> None:  # type: ignore[no-untyped-def]
    storage.database.transaction(
        lambda connection: connection.execute(
            "UPDATE jobs SET expires_at = clock_timestamp() - interval '1 second'"
            " WHERE state = 'running'"
        )
    )


def test_killed_listing_resumes_and_the_batch_covers_both_sets_once(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    tls = tmp_path / "tls"
    with (
        _remote(tmp_path) as (remote, port, context),
        local_storage(
            dsn=postgres_dsn,
            artifact_root=artifact_root,
            tls_directory=tls,
            identity=IDENTITY,
        ) as storage,
    ):
        worker_id = worker_principal(tls)
        dying = PilotWorker(
            storage.client,
            worker_id=worker_id,
            identity=IDENTITY,
            sources=_sources(port, context, die_before_listing_call=2),
        )
        with pytest.raises(Killed):
            advance(storage, WINDOW)
            dying.run()
        _expire_running_leases(storage)

        resumed = PilotWorker(
            storage.client,
            worker_id=worker_id,
            identity=IDENTITY,
            sources=_sources(port, context),
        )
        run = run_once(storage, window=WINDOW, worker=resumed)

        # Each listing page was requested exactly once across the kill and resume.
        oai = {
            path: count for path, count in remote.log.items() if path.startswith("/oai")
        }
        assert sorted(oai.values()) == [1, 1, 1]

    families = [item["family_id"] for item in run.batch["eligible_families"]]
    assert families == ["2601.00001", "2601.00002", "2601.00003"]
    # The cross-listed family merged both sets' categories.
    merged = next(
        item
        for item in run.batch["eligible_families"]
        if item["family_id"] == "2601.00002"
    )
    assert merged["categories"] == ["cs.AI", "cs.LG"]
    assert run.batch["day"] == "2026-01-02"
    assert run.batch["categories"] == ["cs.AI", "cs.LG"]
    assert len(run.batch["lateness"]) == 3
    assert all(item["lateness_seconds"] >= 0 for item in run.batch["lateness"])
    assert run.papers_listed == 4  # 1 + 1 (cs.AI) + 2 (cs.LG), before merging
    assert run.bytes_fetched > 0


def test_a_second_run_of_the_same_day_reseals_the_identical_batch(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    tls = tmp_path / "tls"
    with (
        _remote(tmp_path) as (_, port, context),
        local_storage(
            dsn=postgres_dsn,
            artifact_root=artifact_root,
            tls_directory=tls,
            identity=IDENTITY,
        ) as storage,
    ):
        worker = PilotWorker(
            storage.client,
            worker_id=worker_principal(tls),
            identity=IDENTITY,
            sources=_sources(port, context),
        )
        first = run_once(storage, window=WINDOW, worker=worker)
        second = run_once(storage, window=WINDOW, worker=worker)
    assert first.batch == second.batch
    assert first.batch_manifest == second.batch_manifest


def test_document_acquisition_is_enqueued_for_every_eligible_family(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    tls = tmp_path / "tls"
    with (
        _remote(tmp_path) as (_, port, context),
        local_storage(
            dsn=postgres_dsn,
            artifact_root=artifact_root,
            tls_directory=tls,
            identity=IDENTITY,
        ) as storage,
    ):
        worker = PilotWorker(
            storage.client,
            worker_id=worker_principal(tls),
            identity=IDENTITY,
            sources=_sources(port, context),
        )
        run_once(storage, window=WINDOW, worker=worker)
        counts = storage.database.transaction(
            lambda connection: connection.execute(
                "SELECT state, count(*) FROM jobs GROUP BY state"
            ).fetchall()
        )
    # 2 listing jobs (cs.AI, cs.LG) plus 3 document jobs, all committed.
    assert dict(counts) == {"committed": 5}
