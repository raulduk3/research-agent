"""Export a corpus release's extracted paper text for batch embedding.

``bin/export-text`` walks a pilot's committed ``documents`` jobs and writes
one ``models.batch.PaperText`` JSON per paper version, the directory
``bin/embed-batch --text`` reads. Title and abstract come from the committed
selection record; the source is the payload the documents job retained,
found through the job's own request records; the extraction is
``reader.extract``'s own, so no second extractor exists here. The paper
version id is the one ``ingest.pilot`` publishes, so the vectors join back
to the corpus records.

Resumable: a version whose file already exists is not extracted again. A
version with no usable text, or whose extraction failed, is recorded in the
export manifest with its reason and does not stop the walk. Reads local
storage only; makes no network request.

The text directory names paper versions only. ``release_identities`` reads
the same committed selection to say which family, title and first public
time each version has, so ``bin/import-embeddings --state --dsn`` can name
the embedding view it builds for every version it publishes (#302).
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import subprocess
import tempfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from research_agent.contracts.canonical import canonical_json, sha256_hex
from research_agent.contracts.papers import SourceAccess
from research_agent.contracts.passages import ExtractionRecord
from research_agent.ingest.arxiv import bucket_pdf_path, document_path
from research_agent.ingest.bulk import EXTRACTOR_MANIFEST_HASH, decode_latex_source
from research_agent.ingest.pilot import derived_uuid
from research_agent.ingest.pilot_local import LocalStorage, local_storage
from research_agent.ingest.pilot_run import RECORD_CAP, _by_stage, _identity
from research_agent.learning.corpus import DEFAULT_CATEGORIES
from research_agent.models.batch import PaperText, paper_text_path
from research_agent.models.embedding_view import PaperIdentity
from research_agent.reader.extract import (
    PdfPage,
    extract_latex,
    extract_pdf,
    extract_unsupported,
    normalize_text,
)

__all__ = [
    "MANIFEST_NAME",
    "PDF_EXTRACTOR_MANIFEST_HASH",
    "PdfReader",
    "export_text",
    "main",
    "pilot_storage",
    "read_pdf_pages",
    "release_identities",
]

# Not `*.json`: `bin/embed-batch` reads every `*.json` in the directory as a
# paper version.
MANIFEST_NAME = "export-manifest.canonical"
# The PDF path's extractor is `extract_pdf` over poppler's text layer; the
# LaTeX and unsupported paths share the bulk extractor's identity. v2 splits
# pages at numbered top-level headings (#295).
PDF_EXTRACTOR_MANIFEST_HASH = sha256(b"reader.extract-pdf-v2 pdftotext").hexdigest()
_PDFTOTEXT_TIMEOUT_SECONDS = 120.0

PdfReader = Callable[[bytes], Sequence[PdfPage]]


def read_pdf_pages(pdf_bytes: bytes) -> tuple[PdfPage, ...]:
    """A PDF's text layer, one page per form feed, through ``pdftotext``.

    Non-executing and never OCR (SDD-MD-10). ``pdftotext`` cannot say
    whether an empty page holds an image, so every page without text is
    passed on as unreadable rather than silently dropped.
    """
    with tempfile.TemporaryDirectory() as raw_directory:
        source = Path(raw_directory) / "source.pdf"
        source.write_bytes(pdf_bytes)
        completed = subprocess.run(
            ["pdftotext", "-enc", "UTF-8", str(source), "-"],
            capture_output=True,
            timeout=_PDFTOTEXT_TIMEOUT_SECONDS,
            check=False,
        )
    if completed.returncode != 0:
        raise RuntimeError(
            f"pdftotext exited {completed.returncode}: "
            + completed.stderr.decode("utf-8", "replace").strip()[:200]
        )
    pages = completed.stdout.decode("utf-8", "replace").split("\f")
    if pages and pages[-1] == "":
        pages.pop()
    return tuple(
        PdfPage(number, text, not text.strip())
        for number, text in enumerate(pages, start=1)
    )


@contextmanager
def pilot_storage(state: Path, dsn: str) -> Iterator[LocalStorage]:
    """A pilot's local storage, under the identity its state directory records.

    Never migrates the schema it opens. A build owns its schema, and applying
    a migration under a running build deadlocks against its transactions; a
    reader on a newer checkout than the build reads the same tables all the
    same.
    """
    stored = json.loads((state / "state.json").read_text())
    identity = _identity(
        stored["frozen_at"],
        tuple(stored.get("categories", DEFAULT_CATEGORIES)),
        stored.get("record_cap", RECORD_CAP),
    )
    with local_storage(
        dsn=dsn,
        artifact_root=state / "artifacts",
        tls_directory=state / "tls",
        identity=identity,
    ) as storage:
        yield storage


def release_identities(storage: LocalStorage) -> dict[str, PaperIdentity]:
    """Paper version id -> what an embedding view names it by, per selected family.

    Keyed by the version id ``export_text`` writes (``ingest.pilot``'s), and
    naming the family id the corpus records publish, with the committed
    selection's title and first public time.
    """
    selection = next(
        (j for j in _by_stage(storage).get("select", []) if j["state"] == "committed"),
        None,
    )
    if selection is None:
        raise RuntimeError("this pilot has no committed selection")
    return {
        str(derived_uuid("gate-paper-version", family["family_id"])): PaperIdentity(
            str(derived_uuid("gate-paper-family", family["family_id"])),
            str(family["title"]),
            family["first_public_at"],
        )
        for family in selection["report"]["selected"]
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _retained(storage: LocalStorage, job_id: str, family_id: str) -> dict[str, str]:
    """The retained payload hash of each document kind one job captured.

    Read from the job's own request records, so a bucket PDF and an arXiv
    PDF both count as the family's PDF, and a failed request counts as
    nothing retained.
    """
    rows = storage.database.transaction(
        lambda connection: connection.execute(
            """SELECT DISTINCT encode(a.hash,'hex') FROM artifacts a
               JOIN artifact_productions p ON p.artifact_hash=a.hash
               JOIN job_productions jp ON jp.manifest_hash=p.manifest_hash
               WHERE jp.job_id=%s AND a.kind='source_response'
                 AND a.media_type='application/json'
               ORDER BY 1""",
            (job_id,),
        ).fetchall()
    )
    paths = {
        document_path(family_id, "src"): "src",
        document_path(family_id, "pdf"): "pdf",
        bucket_pdf_path(family_id): "pdf",
    }
    retained: dict[str, str] = {}
    for (value,) in rows:
        access = SourceAccess.from_json(_read(storage, str(value)))
        kind = paths.get(urlsplit(access.requested_url).path)
        if kind is None or access.failure is not None:
            continue
        if access.retained_payload_hash is not None:
            retained.setdefault(kind, access.retained_payload_hash)
    return retained


def _read(storage: LocalStorage, artifact_hash: str) -> bytes:
    (_, _), stream = storage.artifacts.read(artifact_hash)
    with stream:
        return stream.read()


def _as_pdf(raw: bytes) -> bytes | None:
    """The PDF bytes of a payload that is a PDF, gzipped or not."""
    try:
        payload = gzip.decompress(raw)
    except (OSError, EOFError):
        payload = raw
    return payload if payload.startswith(b"%PDF") else None


def _extract(
    storage: LocalStorage,
    paper_version_id: str,
    retained: dict[str, str],
    pdf_reader: PdfReader,
) -> tuple[ExtractionRecord, str]:
    """The reader's extraction of one version and its canonical text.

    LaTeX source first; otherwise the PDF, from its own capture or from a
    source that is itself a PDF; otherwise unsupported.
    """
    created_at = _utc_now()
    source_bytes = None
    if "src" in retained:
        source_bytes = _read(storage, retained["src"])
        latex = decode_latex_source(source_bytes)
        if latex is not None:
            record = extract_latex(
                paper_version_id,
                retained["src"],
                EXTRACTOR_MANIFEST_HASH,
                latex,
                created_at,
            )
            return record, normalize_text(latex)
    pdf: tuple[str, bytes] | None = None
    if "pdf" in retained:
        pdf = retained["pdf"], _read(storage, retained["pdf"])
    elif source_bytes is not None:
        as_pdf = _as_pdf(source_bytes)
        if as_pdf is not None:
            pdf = retained["src"], as_pdf
    if pdf is not None:
        pages = pdf_reader(pdf[1])
        record = extract_pdf(
            paper_version_id, pdf[0], PDF_EXTRACTOR_MANIFEST_HASH, pages, created_at
        )
        # `extract_pdf` joins each readable page's normalized text with one
        # newline; the text hash below proves this is that same text.
        readable = (normalize_text(p.text) for p in pages)
        return record, "\n".join(text for text in readable if text.strip())
    # Nothing retained names the empty payload as its source.
    source_hash = retained.get("src", sha256_hex(b""))
    record = extract_unsupported(
        paper_version_id, source_hash, EXTRACTOR_MANIFEST_HASH, created_at
    )
    return record, ""


def _write_atomic(path: Path, body: bytes) -> None:
    partial = path.with_name(f".{path.name}.partial")
    partial.write_bytes(body)
    os.replace(partial, path)


def export_text(
    storage: LocalStorage,
    out: Path,
    *,
    pilot_state: Path,
    config_hash: str,
    pdf_reader: PdfReader = read_pdf_pages,
) -> dict[str, Any]:
    """Write one ``PaperText`` per committed family and return the manifest.

    The manifest is also written to ``out/MANIFEST_NAME``. It names the
    pilot state and its ``config_hash``, counts the versions in ``out``, and
    lists every version not written with the reader's coverage or the
    failure that stopped it.
    """
    out.mkdir(parents=True, exist_ok=True)
    by_stage = _by_stage(storage)
    selection = next(
        (j for j in by_stage.get("select", []) if j["state"] == "committed"), None
    )
    if selection is None:
        raise RuntimeError("this pilot has no committed selection")
    families = {f["family_id"]: f for f in selection["report"]["selected"]}
    committed: dict[str, str] = {}
    for job in by_stage.get("documents", []):
        if job["state"] == "committed":
            committed[job["spec"]["family"]["family_id"]] = job["id"]
    written = skipped = 0
    coverage: dict[str, int] = {}
    unavailable: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for family_id in sorted(committed):
        paper_version_id = str(derived_uuid("gate-paper-version", family_id))
        path = paper_text_path(out, paper_version_id)
        if path.exists():
            skipped += 1
            existing = PaperText.from_json(path.read_bytes()).extraction.coverage
            coverage[existing] = coverage.get(existing, 0) + 1
            continue
        entry = {"family_id": family_id, "paper_version_id": paper_version_id}
        try:
            family = families[family_id]
            title, abstract = str(family["title"]), str(family["abstract"])
            retained = _retained(storage, committed[family_id], family_id)
            record, text = _extract(storage, paper_version_id, retained, pdf_reader)
            if sha256_hex(text.encode("utf-8")) != record.text_hash:
                raise RuntimeError("canonical text does not match the extraction")
        except Exception as error:  # one family's failure never stops the walk
            failed.append({**entry, "reason": f"{type(error).__name__}: {error}"})
            continue
        coverage[record.coverage] = coverage.get(record.coverage, 0) + 1
        if record.coverage == "unavailable":
            unavailable.append(
                {
                    **entry,
                    "coverage": record.coverage,
                    "coverage_reasons": list(record.coverage_reasons),
                }
            )
            continue
        paper_text = PaperText(
            paper_version_id=paper_version_id,
            title=title,
            abstract=abstract,
            extraction_hash=sha256_hex(record.to_canonical_json()),
            canonical_text=text,
            extraction=record,
        )
        _write_atomic(path, paper_text.to_canonical_json())
        written += 1
    manifest = {
        "pilot_state": str(pilot_state.resolve()),
        "config_hash": config_hash,
        "count": written + skipped,
        "written": written,
        "skipped": skipped,
        "coverage": dict(sorted(coverage.items())),
        "unavailable": unavailable,
        "failed": failed,
    }
    _write_atomic(out / MANIFEST_NAME, canonical_json(manifest))
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="export-text", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--dsn", required=True, help="DSN selecting a pilot schema")
    parser.add_argument(
        "--out", type=Path, required=True, help="paper text output directory"
    )
    args = parser.parse_args(argv)
    state: Path = args.state
    state_file = state / "state.json"
    if not state_file.exists():
        parser.error("no pilot state exists at --state")
    # Read-only by construction: this walks a build's committed jobs and the
    # artifacts they produced, tables every schema since the pilot's first has
    # carried.
    with pilot_storage(state, args.dsn) as storage:
        manifest = export_text(
            storage,
            args.out,
            pilot_state=state,
            config_hash=storage.identity.config_hash,
        )
    print(
        json.dumps(
            {k: manifest[k] for k in ("count", "written", "skipped", "coverage")}
            | {"unavailable": len(manifest["unavailable"])}
            | {"failed": len(manifest["failed"])},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
