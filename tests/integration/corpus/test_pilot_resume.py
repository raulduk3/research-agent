"""The pilot worker resumes through real storage without repeating or skipping work.

Real PostgreSQL, the real storage service over mTLS and real HTTPS requests to a
loopback server standing in for arXiv and OpenAlex. Nothing about storage,
checkpoints or HTTP framing is mocked; only the remote content is synthetic.
"""

from __future__ import annotations

import json
import ssl
import subprocess
import threading
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from research_agent.contracts import RecordMeta
from research_agent.contracts.primitives import ProducerVersion
from research_agent.ingest.arxiv import fetch_document, fetch_listing_page
from research_agent.ingest.fetch import (
    FetchedOpenAlexPage,
    _fetch_page,
    _match_request,
    _request,
)
from research_agent.ingest.pilot import (
    Identity,
    PilotWorker,
    RateGate,
    Sources,
    derived_uuid,
)
from research_agent.ingest.pilot_local import local_storage, worker_principal

pytestmark = pytest.mark.integration

IDENTITY = Identity(
    ProducerVersion("a" * 64, "b" * 40, 1), "c" * 64, "d" * 64, "e" * 64
)
FROZEN_AT = "2025-12-01T00:00:00.000000Z"


def _record(family: str, submitted: str, categories: str) -> str:
    return f"""<record><header><identifier>oai:arXiv.org:{family}</identifier>
<datestamp>2024-01-01</datestamp></header><metadata>
<arXivRaw xmlns="http://arxiv.org/OAI/arXivRaw/"><id>{family}</id>
<version version="v1"><date>{submitted}</date></version>
<title>Paper {family}</title><authors>A. Author</authors>
<categories>{categories}</categories>
<license>http://creativecommons.org/licenses/by/4.0/</license>
<abstract>Abstract {family}</abstract></arXivRaw></metadata></record>"""


def _oai(records: list[str], token: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><ListRecords>'
        + "".join(records)
        + f'<resumptionToken completeListSize="6">{token}</resumptionToken>'
        "</ListRecords></OAI-PMH>"
    ).encode()


JUNE = "Thu, 15 Jun 2023 10:00:00 GMT"
PAGES = {
    None: _oai(
        [
            _record("2306.00001", JUNE, "cs.AI"),
            _record("2306.00002", JUNE, "cs.CV cs.LG"),
        ],
        "t1",
    ),
    "t1": _oai(
        [
            _record("2306.00003", JUNE, "cs.AI"),
            _record("2306.00004", JUNE, "cs.CV"),
        ],
        "t2",
    ),
    "t2": _oai([_record("2306.00005", JUNE, "cs.LG")], ""),
}


def _works(results: list[dict[str, object]], next_cursor: str | None) -> bytes:
    return json.dumps(
        {
            "meta": {"count": len(results), "next_cursor": next_cursor},
            "results": results,
        }
    ).encode()


def _work(number: int) -> dict[str, object]:
    # Every field the closed cites query selects, so a gated job can parse the
    # page; each work cites W1, the match every test family resolves to.
    return {
        "id": f"https://openalex.org/W{number}",
        "ids": {"openalex": f"https://openalex.org/W{number}"},
        "doi": None,
        "publication_date": "2023-09-01",
        "primary_topic": None,
        "referenced_works": ["https://openalex.org/W1"],
    }


class Remote:
    """Loopback HTTPS source with a request log and scripted refusals."""

    def __init__(self) -> None:
        self.log: Counter[str] = Counter()
        self.refuse_once: set[str] = set()

    def respond(self, path: str) -> tuple[int, bytes, str]:
        self.log[path] += 1
        url = urlsplit(path)
        query = {key: values[0] for key, values in parse_qs(url.query).items()}
        if path in self.refuse_once:
            self.refuse_once.discard(path)
            return 429, b"{}", "application/json"
        if url.path == "/oai":
            return 200, PAGES[query.get("resumptionToken")], "text/xml"
        if url.path.startswith("/src/"):
            if "00001" in url.path:
                return 404, b"", "text/plain"
            if "00003" in url.path:
                # A PDF-only submission: arXiv serves the same PDF as its source.
                return 200, b"%PDF-1.5 original", "application/pdf"
            return 200, b"\x1f\x8b source", "application/gzip"
        if url.path.startswith("/pdf/"):
            return 200, b"%PDF-1.5 original", "application/pdf"
        if query.get("filter", "").startswith("doi:"):
            return 200, _works([_work(1)], None), "application/json"
        if query.get("filter") == "cites:W1":
            if query["cursor"] == "*":
                return 200, _works([_work(10), _work(11)], "c1"), "application/json"
            return 200, _works([_work(12)], None), "application/json"
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


def _sources(
    port: int,
    context: ssl.SSLContext,
    *,
    die_before_listing_call: int | None = None,
    die_before_document_call: int | None = None,
) -> Sources:
    calls = Counter[str]()

    def listing(path: str):  # type: ignore[no-untyped-def]
        calls["listing"] += 1
        if calls["listing"] == die_before_listing_call:
            raise Killed()
        return fetch_listing_page(path, host="localhost", port=port, context=context)

    def openalex(query: tuple[str, bytes], meta: RecordMeta) -> FetchedOpenAlexPage:
        return _fetch_page(
            query=query,
            provenance=meta,
            permission_evidence_hash=IDENTITY.permission_evidence_hash,
            retention_policy_hash=IDENTITY.retention_policy_hash,
            host="localhost",
            port=port,
            context=context,
        )

    def document(path: str):  # type: ignore[no-untyped-def]
        calls["document"] += 1
        if calls["document"] == die_before_document_call:
            raise Killed()
        return fetch_document(path, host="localhost", port=port, context=context)

    return Sources(
        listing=listing,
        document=document,
        openalex_match=lambda family, meta: openalex(_match_request(family), meta),
        openalex_cites=lambda work, cursor, meta: openalex(
            _request((work,), cursor, 100), meta
        ),
        arxiv_gate=RateGate(0.001),
        openalex_gate=RateGate(0.001),
    )


def _expire_running_leases(storage: Any) -> None:
    """Expire every running lease now, instead of waiting a wall-clock interval.

    A sleep races the resumed run: on a slow host its own publication could
    straddle a second expiry of a short lease. Moving ``expires_at`` into the
    past makes the stopped job reclaimable at once while the resumed claim
    keeps the full lease length.
    """
    storage.database.transaction(
        lambda connection: connection.execute(
            "UPDATE jobs SET expires_at = clock_timestamp() - interval '1 second'"
            " WHERE state = 'running'"
        )
    )


def test_killed_listing_resumes_without_refetching_and_selection_reads_it(
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
        worker = worker_principal(tls)
        spec = {
            "stage": "listing",
            "set_spec": "cs:cs:AI",
            "from_date": "2023-05-01",
            "until_date": "2025-12-01",
        }
        listing_job = storage.enqueue(spec)
        dying = PilotWorker(
            storage.client,
            worker_id=worker,
            identity=IDENTITY,
            sources=_sources(port, context, die_before_listing_call=3),
        )
        with pytest.raises(Killed):
            dying.run()
        _expire_running_leases(storage)
        resumed = PilotWorker(
            storage.client,
            worker_id=worker,
            identity=IDENTITY,
            sources=_sources(port, context),
        )
        assert resumed.run().jobs_completed == 1
        # Each page was requested exactly once across the kill and the resume.
        oai = {
            path: count for path, count in remote.log.items() if path.startswith("/oai")
        }
        assert sorted(oai.values()) == [1, 1, 1]
        rows = {job: (state, output) for job, state, output in storage.job_rows()}
        state, listing_report = rows[str(listing_job)]
        assert state == "committed" and listing_report is not None
        assert storage.report(listing_report)["pages"] == 3

        selection_job = storage.enqueue(
            {
                "stage": "select",
                "frozen_at": FROZEN_AT,
                "listing_reports": [listing_report],
            },
            (listing_report,),
        )
        assert resumed.run().jobs_completed == 1
        rows = {job: (state, output) for job, state, output in storage.job_rows()}
        selection = storage.report(rows[str(selection_job)][1] or "")
    june = dict(selection["eligible_counts"])["2023-06"]
    # 00004 is cs.CV only; the cross-listed 00002 is eligible.
    assert june == 4
    chosen = {item["family_id"] for item in selection["selected"]}
    assert chosen == {"2306.00001", "2306.00002", "2306.00003", "2306.00005"}
    assert selection["intended_count"] == 100
    assert sum(count for _, count in selection["month_shortfalls"]) == 96


class _CountingClient:
    """A `StorageClient` that counts the lease renewals it forwards."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.renewals = 0

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._inner, name)
        if name != "renew":
            return attribute

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            self.renewals += 1
            return attribute(*args, **kwargs)

        return wrapped


def test_selection_renews_its_lease_once_per_listing_page(
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
        worker = worker_principal(tls)
        listing_job = storage.enqueue(
            {
                "stage": "listing",
                "set_spec": "cs:cs:AI",
                "from_date": "2023-05-01",
                "until_date": "2025-12-01",
            }
        )
        assert (
            PilotWorker(
                storage.client,
                worker_id=worker,
                identity=IDENTITY,
                sources=_sources(port, context),
            )
            .run()
            .jobs_completed
            == 1
        )
        rows = {job: (state, output) for job, state, output in storage.job_rows()}
        _, listing_report = rows[str(listing_job)]
        assert listing_report is not None
        pages = storage.report(listing_report)["pages"]
        assert pages == 3

        selection_job = storage.enqueue(
            {
                "stage": "select",
                "frozen_at": FROZEN_AT,
                "listing_reports": [listing_report],
            },
            (listing_report,),
        )
        counting = _CountingClient(storage.client)
        selecting = PilotWorker(
            counting,
            worker_id=worker,
            identity=IDENTITY,
            sources=_sources(port, context),
        )
        assert selecting.run().jobs_completed == 1
        rows = {job: (state, output) for job, state, output in storage.job_rows()}
        assert rows[str(selection_job)][0] == "committed"
    # Selection checkpoints nothing until it reports, so the lease must be kept
    # alive by the page loop itself: at least one renewal per page read.
    assert counting.renewals >= pages


def test_documents_record_missing_source_and_openalex_resumes_after_budget_refusal(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    tls = tmp_path / "tls"
    family = {
        "family_id": "2306.00001",
        "license_url": "http://creativecommons.org/licenses/by/4.0/",
    }
    with (
        _remote(tmp_path) as (remote, port, context),
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
        documents = storage.enqueue({"stage": "documents", "family": family})
        assert worker.run().jobs_completed == 1

        second_page = "/works?" + _request(("W1",), "c1", 100)[0].split("?", 1)[1]
        remote.refuse_once.add(second_page)
        citations = storage.enqueue(
            {"stage": "openalex", "family": family, "record_budget": 100000}
        )
        stopped = worker.run()
        assert stopped.stopped_for_budget and stopped.jobs_completed == 0
        _expire_running_leases(storage)
        assert worker.run().jobs_completed == 1
        rows = {job: (state, output) for job, state, output in storage.job_rows()}
        document_report = storage.report(rows[str(documents)][1] or "")
        citation_report = storage.report(rows[str(citations)][1] or "")
    assert document_report == {
        "stage": "documents",
        "family_id": "2306.00001",
        "src": "not_found",
        "pdf": "retained",
    }
    assert citation_report == {
        "stage": "openalex",
        "family_id": "2306.00001",
        "state": "complete",
        "work": "W1",
        "records_received": 3,
    }
    match = [path for path in remote.log if "doi%3A" in path]
    first_page = [
        path for path in remote.log if "cursor=%2A" in path and "cites" in path
    ]
    # The match and first page were not repeated; only the refused page was.
    assert [remote.log[path] for path in match + first_page] == [1, 1]
    assert remote.log[second_page] == 2


def _canonical_openalex(sources: Sources, port: int) -> Sources:
    """The loopback remote standing in for api.openalex.org: the gate's page
    parser admits only records naming the real host, so each access record
    keeps the request it made but under the canonical origin."""
    origin = f"https://localhost:{port}"

    def canonical(page: FetchedOpenAlexPage) -> FetchedOpenAlexPage:
        access = replace(
            page.access,
            requested_url=page.access.requested_url.replace(
                origin, "https://api.openalex.org", 1
            ),
        )
        return replace(page, access=access)

    return replace(
        sources,
        openalex_match=lambda family, meta: canonical(
            sources.openalex_match(family, meta)
        ),
        openalex_cites=lambda work, cursor, meta: canonical(
            sources.openalex_cites(work, cursor, meta)
        ),
    )


def test_gated_openalex_resolves_a_matched_family_with_citing_works(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    """With label gating on, a family matched to a work that other works cite
    resolves to a gate decision. The prohibited alternative is the resolver
    refusing the job's own citation families as newer than the observation
    they hang from, which no resumed or fresh job could ever get past."""
    tls = tmp_path / "tls"
    family = {
        "family_id": "2306.00001",
        "first_public_at": "2023-06-15T10:00:00.000000Z",
        "license_url": "http://creativecommons.org/licenses/by/4.0/",
        "author_count": 2,
        "categories": ["cs.AI"],
        "version_count": 1,
    }
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
            sources=_canonical_openalex(_sources(port, context), port),
            gate_on_labels=True,
        )
        citations = storage.enqueue(
            {"stage": "openalex", "family": family, "record_budget": 100000}
        )
        assert worker.run().jobs_completed == 1
        rows = {job: (state, output) for job, state, output in storage.job_rows()}
        state, output = rows[str(citations)]
        assert state == "committed" and output is not None
        report = storage.report(output)
    assert report["state"] == "complete" and report["work"] == "W1"
    gate = report["gate"]
    assert gate["family_id"] == "2306.00001"
    assert gate["decision"] in {"acquire", "skip"}
    assert all(
        label["state"] in {"true", "false", "unknown"}
        for label in gate["labels"].values()
    )


def test_document_job_killed_between_kinds_reports_both_after_resume(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    tls = tmp_path / "tls"
    family = {"family_id": "2306.00002", "license_url": None}
    with (
        _remote(tmp_path) as (remote, port, context),
        local_storage(
            dsn=postgres_dsn,
            artifact_root=artifact_root,
            tls_directory=tls,
            identity=IDENTITY,
        ) as storage,
    ):
        principal = worker_principal(tls)
        job = storage.enqueue({"stage": "documents", "family": family})
        with pytest.raises(Killed):
            PilotWorker(
                storage.client,
                worker_id=principal,
                identity=IDENTITY,
                sources=_sources(port, context, die_before_document_call=2),
            ).run()
        _expire_running_leases(storage)
        PilotWorker(
            storage.client,
            worker_id=principal,
            identity=IDENTITY,
            sources=_sources(port, context),
        ).run()
        rows = {job_id: output for job_id, _, output in storage.job_rows()}
        report = storage.report(rows[str(job)] or "")
    assert report == {
        "stage": "documents",
        "family_id": "2306.00002",
        "src": "retained",
        "pdf": "retained",
    }
    assert remote.log["/src/2306.00002v1"] == 1


def test_openalex_failure_is_incomplete_not_empty(
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
        remote.refuse_once.add("unused")
        original = remote.respond

        def failing(path: str) -> tuple[int, bytes, str]:
            if "cites" in path and "c1" in path:
                remote.log[path] += 1
                return 503, b"", "text/plain"
            return original(path)

        remote.respond = failing  # type: ignore[method-assign]
        worker = PilotWorker(
            storage.client,
            worker_id=worker_principal(tls),
            identity=IDENTITY,
            sources=_sources(port, context),
        )
        job = storage.enqueue(
            {
                "stage": "openalex",
                "family": {"family_id": "2306.00001", "license_url": None},
                "record_budget": 100000,
            }
        )
        assert worker.run().jobs_completed == 1
        rows = {job_id: (state, output) for job_id, state, output in storage.job_rows()}
        report = storage.report(rows[str(job)][1] or "")
    assert report["state"] == "incomplete"
    assert report["records_received"] == 2


def test_expired_listing_token_fails_the_job_instead_of_retrying_forever(
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
        original = remote.respond

        def expired(path: str) -> tuple[int, bytes, str]:
            if "resumptionToken=t1" in path:
                remote.log[path] += 1
                return (
                    200,
                    b'<?xml version="1.0"?><OAI-PMH xmlns="http://www.openarchives.org'
                    b'/OAI/2.0/"><error code="badResumptionToken">expired</error>'
                    b"</OAI-PMH>",
                    "text/xml",
                )
            return original(path)

        remote.respond = expired  # type: ignore[method-assign]
        worker = PilotWorker(
            storage.client,
            worker_id=worker_principal(tls),
            identity=IDENTITY,
            sources=_sources(port, context),
        )
        job = storage.enqueue(
            {
                "stage": "listing",
                "set_spec": "cs:cs:AI",
                "from_date": "2023-05-01",
                "until_date": "2025-12-01",
            }
        )
        assert worker.run().jobs_completed == 1
        states = {job_id: state for job_id, state, _ in storage.job_rows()}
    assert states[str(job)] == "failed"
    assert sum(1 for path in remote.log if "resumptionToken=t1" in path) == 1


def test_rate_gate_spaces_requests_and_waits_after_a_restart() -> None:
    now = [100.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    gate = RateGate(3.0, clock=lambda: now[0], sleep=sleep)
    gate.wait()
    now[0] += 1.0
    gate.wait()
    assert slept == [3.0, 2.0]


def test_derived_command_ids_are_stable_uuid4() -> None:
    first = derived_uuid("job", "publish", "a" * 64)
    assert first == derived_uuid("job", "publish", "a" * 64)
    assert first != derived_uuid("job", "publish", "b" * 64)
    assert first.version == 4 and first.variant == "specified in RFC 4122"


def test_operator_runs_stages_in_order_and_holds_the_record_cap(
    postgres_dsn: str,
    artifact_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from research_agent.ingest import pilot_run

    # Two citation records per family exhaust this cap after the first family.
    monkeypatch.setattr(pilot_run, "RECORD_CAP", 2)
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
        worker = PilotWorker(
            storage.client,
            worker_id=worker_principal(tls),
            identity=IDENTITY,
            sources=_sources(port, context),
        )
        while True:
            pilot_run._advance(storage, FROZEN_AT)
            if worker.run().jobs_completed == 0 and not pilot_run._advance(
                storage, FROZEN_AT
            ):
                break
        jobs = pilot_run._jobs(storage)
        (tmp_path / "state.json").write_text('{"frozen_at": "%s"}' % FROZEN_AT)
        (tmp_path / "artifacts").mkdir(exist_ok=True)
        summary = pilot_run.report(storage, tmp_path)
    requests = summary["requests"]["by_adapter"]
    # 3 listing pages per set, 4 sets for the default categories (cs.AI, cs.LG,
    # quant-ph, q-bio), 2 documents per family, then the match and one citation
    # page: its 2 records reach the cap, so no further page is requested.
    assert requests["arxiv-oai-arxivraw-v1"] == {"retained": 12}
    assert requests["arxiv-original-v1-document-v1"] == {
        "retained": 7,
        "not_found": 1,
    }
    assert requests["openalex-anonymous-citations-v1"] == {"retained": 2}
    assert summary["openalex"] == {
        "states": {"capped": 1},
        "records_received": 2,
        "record_cap": 2,
    }
    assert summary["documents"]["src"] == {"not_found": 1, "retained": 3}
    assert summary["selection"]["selected"] == 4
    stages = [(job["spec"]["stage"], job["state"]) for job in jobs]
    assert stages.count(("listing", "committed")) == 4
    assert stages.count(("select", "committed")) == 1
    selected = next(j for j in jobs if j["spec"]["stage"] == "select")["report"]
    assert len(selected["selected"]) == 4
    assert stages.count(("documents", "committed")) == 4
    openalex = [j for j in jobs if j["spec"]["stage"] == "openalex"]
    # The first family reached the cap of 2; no second family was started.
    assert len(openalex) == 1
    # Documents: one missing source archive, all PDFs retained.
    documents = [j["report"] for j in jobs if j["spec"]["stage"] == "documents"]
    assert sorted(d["src"] for d in documents) == ["not_found"] + ["retained"] * 3
    assert all(d["pdf"] == "retained" for d in documents)
