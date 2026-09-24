"""`bin/export-text` turns a pilot's committed documents into `--text` (#237).

Real PostgreSQL, the real storage service over mTLS, and the real pilot
worker capturing each family's documents over HTTPS from a loopback server;
only the remote content is synthetic. The selection stage's listing parse is
replaced by a fixed report, and the PDF text layer by fixed pages except in
the one test that runs poppler itself.
"""

from __future__ import annotations

import gzip
import io
import shutil
import ssl
import subprocess
import tarfile
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from research_agent.contracts.canonical import canonical_loads
from research_agent.contracts.primitives import ProducerVersion
from research_agent.ingest.arxiv import (
    bucket_pdf_path,
    fetch_bucket_pdf,
    fetch_document,
)
from research_agent.ingest.pilot import (
    Identity,
    ParallelGate,
    PilotWorker,
    RateGate,
    Sources,
    derived_uuid,
    gate_identity,
)
from research_agent.ingest.pilot_local import (
    LocalStorage,
    local_storage,
    worker_principal,
)
from research_agent.ingest.bulk import EXTRACTOR_MANIFEST_HASH
from research_agent.learning.text_export import (
    MANIFEST_NAME,
    PDF_EXTRACTOR_MANIFEST_HASH,
    export_text,
    read_pdf_pages,
)
from research_agent.models.batch import read_paper_text
from research_agent.reader.extract import PdfPage
from research_agent.retrieval.passages import build_passages

pytestmark = pytest.mark.integration

IDENTITY = Identity(
    ProducerVersion("a" * 64, "b" * 40, 1), "c" * 64, "d" * 64, "e" * 64
)
LATEX_FAMILY = "2305.01937"
PDF_FAMILY = "2305.01938"
BARE_FAMILY = "2305.01939"
LATEX = (
    "\\begin{abstract}An abstract in the source.\\end{abstract}\n"
    "\\section{Introduction}\nThe body of the paper, in its own words.\n"
)
PDF_BYTES = b"%PDF-1.4 a PDF-only submission"
PDF_PAGES = (
    PdfPage(1, "First page of the text layer.", False),
    PdfPage(2, "Second page of the text layer.", False),
)


def _family(family_id: str) -> dict[str, Any]:
    # Titles and abstracts carry what a naive re-encoding would change.
    return {
        "family_id": family_id,
        "first_public_at": "2023-05-03T00:00:00.000000Z",
        "categories": ["cs.LG"],
        "license_url": None,
        "doi": None,
        "title": f"Caf\u00e9  {family_id}: a  \u201cquoted\u201d title",
        "abstract": f"Line one of {family_id}.\n  Line two, \u00e9t\u00e9 $x^2$.",
        "author_count": 1,
        "version_count": 1,
    }


FAMILIES = [_family(f) for f in (LATEX_FAMILY, PDF_FAMILY, BARE_FAMILY)]


def _latex_archive() -> bytes:
    body = LATEX.encode("utf-8")
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        member = tarfile.TarInfo("main.tex")
        member.size = len(body)
        archive.addfile(member, io.BytesIO(body))
    return gzip.compress(buffer.getvalue())


def _respond(path: str) -> tuple[int, bytes]:
    """What arXiv and the bucket hold for each family.

    The LaTeX family also has a PDF, which the export must pass over; the
    PDF-only family's source is its PDF, as arXiv serves it; the bare
    family has nothing retained anywhere.
    """
    if path == f"/src/{LATEX_FAMILY}v1":
        return 200, _latex_archive()
    if path in (bucket_pdf_path(LATEX_FAMILY), bucket_pdf_path(PDF_FAMILY)):
        return 200, PDF_BYTES
    if path == f"/src/{PDF_FAMILY}v1":
        return 200, PDF_BYTES
    return 404, b""


@contextmanager
def _remote(tmp_path: Path) -> Iterator[tuple[int, ssl.SSLContext]]:
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

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            status, body = _respond(self.path)
            self.send_response(status)
            self.send_header("Content-Type", "application/octet-stream")
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
        yield server.server_port, ssl.create_default_context(cafile=str(cert))
    finally:
        server.shutdown()
        server.server_close()


def _sources(port: int, context: ssl.SSLContext) -> Sources:
    def _unreachable(*_: object, **__: object) -> Any:
        raise AssertionError("only the documents stage makes requests here")

    return Sources(
        listing=_unreachable,
        document=lambda path: fetch_document(
            path, host="localhost", port=port, context=context
        ),
        openalex_match=_unreachable,
        openalex_cites=_unreachable,
        arxiv_gate=RateGate(0.001),
        openalex_gate=RateGate(0.001),
        pdf_bucket=lambda path: fetch_bucket_pdf(
            path, host="localhost", port=port, context=context
        ),
        bucket_gate=ParallelGate(8),
    )


def _selection_report(self: PilotWorker, lease: object) -> dict[str, Any]:
    return {"stage": "select", "selected": FAMILIES}


@pytest.fixture
def pilot(
    postgres_dsn: str,
    artifact_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[LocalStorage]:
    """A pilot with a committed selection and one committed documents job
    per family, each captured by the real worker."""
    monkeypatch.setattr(PilotWorker, "_select", _selection_report)
    tls = tmp_path / "tls"
    with (
        _remote(tmp_path) as (port, context),
        local_storage(
            dsn=postgres_dsn, artifact_root=artifact_root, tls_directory=tls,
            identity=IDENTITY,
        ) as storage,
    ):  # fmt: skip
        worker = PilotWorker(
            storage.client,
            worker_id=worker_principal(tls),
            identity=IDENTITY,
            sources=_sources(port, context),
        )
        storage.enqueue({"stage": "select"})
        for family in FAMILIES:
            storage.enqueue({"stage": "documents", "family": family})
        assert worker.run().jobs_completed == 1 + len(FAMILIES)
        assert all(state == "committed" for _, state, _ in storage.job_rows())
        yield storage


def _fixed_pages(pdf_bytes: bytes) -> Sequence[PdfPage]:
    assert pdf_bytes == PDF_BYTES
    return PDF_PAGES


def _version(family_id: str) -> str:
    return str(derived_uuid("gate-paper-version", family_id))


def _manifest(out: Path) -> dict[str, Any]:
    value = canonical_loads((out / MANIFEST_NAME).read_bytes())
    assert isinstance(value, dict)
    return value


def test_pdf_extractor_manifest_names_the_v2_pdf_extractor() -> None:
    # v2 cuts pages at numbered headings; a v1 record of the same PDF differs.
    assert PDF_EXTRACTOR_MANIFEST_HASH == (
        sha256(b"reader.extract-pdf-v2 pdftotext").hexdigest()
    )


def test_export_writes_latex_and_pdf_text_and_records_the_bare_family(
    pilot: LocalStorage, tmp_path: Path
) -> None:
    out = tmp_path / "text"
    manifest = export_text(
        pilot,
        out,
        pilot_state=tmp_path,
        config_hash=IDENTITY.config_hash,
        pdf_reader=_fixed_pages,
    )

    assert sorted(p.name for p in out.glob("*.json")) == sorted(
        f"{_version(f)}.json" for f in (LATEX_FAMILY, PDF_FAMILY)
    )
    latex = read_paper_text(out, _version(LATEX_FAMILY))
    assert {b.locator.kind for b in latex.extraction.blocks} == {"latex"}
    assert latex.extraction.coverage == "complete"
    assert latex.canonical_text == LATEX
    pdf = read_paper_text(out, _version(PDF_FAMILY))
    assert {b.locator.kind for b in pdf.extraction.blocks} == {"pdf"}
    assert pdf.extraction.coverage == "complete"
    assert pdf.canonical_text == (
        "First page of the text layer.\nSecond page of the text layer."
    )
    assert latex.extraction.extractor_manifest_hash == EXTRACTOR_MANIFEST_HASH
    assert pdf.extraction.extractor_manifest_hash == PDF_EXTRACTOR_MANIFEST_HASH
    # The version id is the one the corpus records publish.
    assert gate_identity(PDF_FAMILY)[1] == pdf.paper_version_id
    for family, paper in ((FAMILIES[0], latex), (FAMILIES[1], pdf)):
        assert paper.title.encode() == family["title"].encode()
        assert paper.abstract.encode() == family["abstract"].encode()

    assert manifest == _manifest(out)
    assert manifest["pilot_state"] == str(tmp_path.resolve())
    assert manifest["config_hash"] == IDENTITY.config_hash
    assert manifest["count"] == 2
    assert manifest["written"] == 2
    assert manifest["skipped"] == 0
    assert manifest["coverage"] == {"complete": 2, "unavailable": 1}
    assert manifest["failed"] == []
    assert manifest["unavailable"] == [
        {
            "family_id": BARE_FAMILY,
            "paper_version_id": _version(BARE_FAMILY),
            "coverage": "unavailable",
            "coverage_reasons": ["unsupported_source"],
        }
    ]


def test_a_rerun_writes_nothing_and_reports_the_skips(
    pilot: LocalStorage, tmp_path: Path
) -> None:
    out = tmp_path / "text"
    export_text(
        pilot, out, pilot_state=tmp_path, config_hash="f" * 64, pdf_reader=_fixed_pages
    )
    before = {p.name: p.stat().st_mtime_ns for p in out.glob("*.json")}

    def _never(pdf_bytes: bytes) -> Sequence[PdfPage]:
        raise AssertionError("an exported version is not extracted again")

    manifest = export_text(
        pilot, out, pilot_state=tmp_path, config_hash="f" * 64, pdf_reader=_never
    )

    assert {p.name: p.stat().st_mtime_ns for p in out.glob("*.json")} == before
    assert manifest["written"] == 0
    assert manifest["skipped"] == 2
    assert manifest["count"] == 2
    assert manifest["coverage"] == {"complete": 2, "unavailable": 1}


def test_a_failed_extraction_is_recorded_and_does_not_stop_the_walk(
    pilot: LocalStorage, tmp_path: Path
) -> None:
    out = tmp_path / "text"

    def _broken(pdf_bytes: bytes) -> Sequence[PdfPage]:
        raise RuntimeError("no text layer tool")

    manifest = export_text(
        pilot, out, pilot_state=tmp_path, config_hash="f" * 64, pdf_reader=_broken
    )

    assert [p.name for p in out.glob("*.json")] == [f"{_version(LATEX_FAMILY)}.json"]
    assert manifest["failed"] == [
        {
            "family_id": PDF_FAMILY,
            "paper_version_id": _version(PDF_FAMILY),
            "reason": "RuntimeError: no text layer tool",
        }
    ]
    # The failed version has no file, so the next run tries it again.
    manifest = export_text(
        pilot, out, pilot_state=tmp_path, config_hash="f" * 64, pdf_reader=_fixed_pages
    )
    assert manifest["written"] == 1
    assert manifest["failed"] == []


class _WhitespaceTokenizer:
    def encode_offsets(self, text: str) -> Sequence[tuple[int, int]]:
        offsets, start = [], None
        for index, character in enumerate(text + " "):
            if character.isspace():
                if start is not None:
                    offsets.append((start, index))
                    start = None
            elif start is None:
                start = index
        return offsets


def test_the_batch_embedder_chunks_what_the_export_writes(
    pilot: LocalStorage, tmp_path: Path
) -> None:
    out = tmp_path / "text"
    export_text(
        pilot, out, pilot_state=tmp_path, config_hash="f" * 64, pdf_reader=_fixed_pages
    )
    for family_id in (LATEX_FAMILY, PDF_FAMILY):
        paper = read_paper_text(out, _version(family_id))
        passages = build_passages(
            paper.extraction,
            paper.canonical_text,
            paper.extraction_hash,
            _WhitespaceTokenizer(),
        )
        assert passages


def _one_page_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    body = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, content in enumerate(objects, start=1):
        offsets.append(len(body))
        body += b"%d 0 obj\n" % number + content + b"\nendobj\n"
    xref = len(body)
    body += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    body += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    body += b"trailer\n<< /Size %d /Root 1 0 R >>\n" % (len(objects) + 1)
    body += b"startxref\n%d\n%%%%EOF\n" % xref
    return bytes(body)


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="needs pdftotext")
def test_read_pdf_pages_returns_the_text_layer_page_by_page() -> None:
    pages = read_pdf_pages(_one_page_pdf("Hello text layer"))
    assert [page.page_number for page in pages] == [1]
    assert pages[0].text.strip() == "Hello text layer"
    assert not pages[0].has_image


def test_the_exporter_never_migrates_the_schema_it_reads() -> None:
    """The prohibited alternative is applying a migration on open: a build
    owns its schema, and a migration taken under a running build deadlocks
    against its transactions. The exporter reads tables every schema since
    the pilot's first has carried, and touches the schema version not at all."""
    import inspect

    from research_agent.learning import text_export

    source = inspect.getsource(text_export)
    assert "migrate(" not in source
    assert "require_schema(" not in source
