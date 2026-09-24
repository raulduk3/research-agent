"""A pinned paper's canonical text, rebuilt from its pinned sources (#287).

No stored artifact holds a paper's canonical text: the reader keeps its
extraction -- located blocks and the text's hash -- and the source document
the text came from. ``deep_read`` and passage search need the text itself,
so :class:`PinnedTexts` rebuilds it from exactly the extraction and source
the pinned card names (``SnapshotDocuments.extraction`` and ``.source``)
and serves it only when its SHA-256 equals the extraction's ``text_hash``.
A paper whose extraction was never stored, or whose text cannot be rebuilt
to that hash, is ``text_unavailable``: never approximated, never read from
another version.

LaTeX source is decoded exactly as the reader decodes it. A PDF's text
layer needs the reader's page-text function; without one a PDF paper's text
is unavailable here while its pages can still be rendered.
"""

from __future__ import annotations

import gzip
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from ..contracts.canonical import canonical_json, sha256_hex
from ..contracts.passages import ExtractionRecord
from ..contracts.primitives import ContractValidationError
from ..ingest.bulk import decode_latex_source
from ..reader.extract import normalize_text
from ..storage.client import ArtifactBytes, QueryResult, StorageClientError
from .answers import ToolError

__all__ = ["PageTexts", "PinnedText", "PinnedTexts", "SourceReads", "pdf_bytes"]

# One PDF's text layer, one string per page, as the reader's PDF path reads it.
PageTexts = Callable[[bytes], Sequence[str]]


class SourceReads(Protocol):
    def snapshot_extraction(
        self, snapshot_hash: str, *, family_id: UUID
    ) -> QueryResult: ...

    def snapshot_source(
        self, snapshot_hash: str, *, family_id: UUID
    ) -> ArtifactBytes: ...


@dataclass(frozen=True, slots=True)
class PinnedText:
    """One pinned paper version's extraction and its verified canonical text."""

    paper_version_id: str
    extraction_hash: str
    extraction: ExtractionRecord
    text: str


def pdf_bytes(raw: bytes) -> bytes | None:
    """The PDF a source payload holds, gzipped or not, or ``None``."""

    try:
        payload = gzip.decompress(raw)
    except (OSError, EOFError):
        payload = raw
    return payload if payload.startswith(b"%PDF") else None


class PinnedTexts:
    """Rebuild pinned papers' canonical text from their pinned sources."""

    def __init__(
        self, storage: SourceReads, *, page_texts: PageTexts | None = None
    ) -> None:
        self._storage = storage
        self._page_texts = page_texts

    def source(self, snapshot_hash: str, family_id: str) -> ArtifactBytes:
        """The source document the pinned card of *family_id* names."""

        try:
            return self._storage.snapshot_source(
                snapshot_hash, family_id=UUID(family_id)
            )
        except StorageClientError as error:
            if error.status_code == 422:
                raise ToolError("source_unavailable", str(error)) from error
            raise

    def text(self, snapshot_hash: str, family_id: str) -> PinnedText:
        """The verified canonical text of the pinned version of *family_id*."""

        try:
            data = self._storage.snapshot_extraction(
                snapshot_hash, family_id=UUID(family_id)
            ).data
        except StorageClientError as error:
            if error.status_code == 422:
                raise ToolError("text_unavailable", str(error)) from error
            raise
        try:
            extraction = ExtractionRecord.from_json(canonical_json(data["extraction"]))
        except (ContractValidationError, KeyError) as error:
            raise ToolError("text_unavailable", "extraction is invalid") from error
        extraction_hash = str(data["extraction_hash"])
        if sha256_hex(extraction.to_canonical_json()) != extraction_hash:
            raise ToolError("text_unavailable", "extraction differs from its hash")
        source = self.source(snapshot_hash, family_id)
        if source.artifact_hash != extraction.source_hash:
            raise ToolError(
                "text_unavailable", "extraction names another source document"
            )
        for text in self._candidates(source.payload):
            if sha256_hex(text.encode("utf-8")) == extraction.text_hash:
                return PinnedText(
                    extraction.paper_version_id, extraction_hash, extraction, text
                )
        raise ToolError(
            "text_unavailable", "the source does not rebuild the extracted text"
        )

    def _candidates(self, source: bytes) -> list[str]:
        latex = decode_latex_source(source)
        if latex is not None:
            return [normalize_text(latex)]
        pdf = pdf_bytes(source)
        if pdf is None or self._page_texts is None:
            return []
        pages = (normalize_text(page) for page in self._page_texts(pdf))
        return ["\n".join(page for page in pages if page.strip())]
