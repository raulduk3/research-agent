"""A sealed snapshot, runs and the shared tool service over real storage (#287).

Every tool test that crosses storage uses this: real PostgreSQL behind the
real storage HTTP server, reached by a ``tools``-role ``StorageClient`` over
mutually authenticated TLS. Papers are real LaTeX extracted by the reader,
chunked by the retrieval policy and pinned with their card, passage index,
extraction and source exactly as the snapshot pins them. Only the query
embedding (the model service, tested in ``tests/models``) and the page
rasterizer (a subprocess) are stand-ins.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_json, canonical_loads
from research_agent.contracts.canonical import sha256_hex
from research_agent.ingest.bulk import decode_latex_source
from research_agent.models.service import EmbeddingResult
from research_agent.reader.extract import extract_latex, normalize_text
from research_agent.retrieval.passages import build_passages
from research_agent.snapshots.documents import SnapshotDocuments
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.authorization import StorageAuthorization
from research_agent.storage.client import StorageClient
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.http import ServiceCapability, create_storage_server
from research_agent.storage.queries import InspectorQueries
from research_agent.storage.requests import PaperRequestRepository
from research_agent.storage.runs import RunRepository
from research_agent.storage.sheets import SheetRepository
from research_agent.storage.snapshots import SnapshotRepository
from research_agent.storage.submissions import SubmissionRepository
from research_agent.storage.trace import TraceRepository
from research_agent.tools.ask import AskHandler
from research_agent.tools.deep_read import DeepReadHandler
from research_agent.tools.graph import GraphHandler
from research_agent.tools.lookup import StorageSnapshotMembership
from research_agent.tools.neighbors import NeighborsHandler
from research_agent.tools.query_cards import QueryCardsHandler
from research_agent.tools.service import ToolService
from research_agent.tools.snapshots import SnapshotIndex
from research_agent.tools.submit import SubmitHandler
from research_agent.tools.text import PinnedTexts
from research_agent.tools.trace import TraceWriter

from tests.storage.test_http import Jobs, _tls_material  # noqa: E402

PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)
SETTINGS: dict[str, Any] = {
    "producer": PRODUCER,
    "config_hash": "c" * 64,
    "retention_policy_hash": "d" * 64,
}
REPRESENTATION = "9" * 64
QUESTION_A = "123e4567-e89b-42d3-a456-426614174100"
QUESTION_B = "123e4567-e89b-42d3-a456-426614174101"
BUDGETS = {
    "context_tokens": 8000,
    "generation_tokens": 2000,
    "tool_calls": 12,
    "deep_reads": 3,
    "images": 3,
    "timeout_seconds": 30,
    "retries": 1,
    "wall_time_seconds": 300,
    "spend_micros": 500_000,
}
MODEL_IDENTITY = {
    "agent_model_manifest": "a" * 64,
    "service_image_versions": {"reader": "b" * 64},
    "paper_card_manifest": "c" * 64,
    "prediction_head_bundles": {},
}
ALL_TOOLS = ("query_cards", "neighbors", "graph", "deep_read", "submit")
TOOL_SCOPES = frozenset(
    {
        "snapshots:read",
        "runs:specification",
        "runs:submit",
        "trace:request",
        "trace:terminal",
        "paper_requests:record",
    }
)
# The query every test searches with, and the one direction it points.
ATTENTION = (1.0, 0.0, 0.0, 0.0)


class WhitespaceTokenizer:
    """One token per whitespace-delimited word."""

    def encode_offsets(self, text: str) -> Sequence[tuple[int, int]]:
        return [(match.start(), match.end()) for match in re.finditer(r"\S+", text)]


def passage_vector(text: str) -> tuple[float, ...]:
    """A passage about attention points at the query; any other does not."""

    return ATTENTION if "attention" in text else (0.0, 1.0, 0.0, 0.0)


@dataclass(frozen=True)
class Paper:
    """One paper as a snapshot pins it; ``latex`` or ``pdf`` is its source."""

    family: str
    version: str
    title: str
    overview: tuple[float, ...]
    latex: str | None = None
    pdf: bytes | None = None
    graph: dict[str, Any] | None = None
    abstract: str | None = None


def latex_paper(
    title: str,
    overview: tuple[float, ...],
    sections: dict[str, str],
    *,
    graph: dict[str, Any] | None = None,
) -> Paper:
    body = "".join(
        f"\\section{{{heading}}}\n{text}\n" for heading, text in sections.items()
    )
    return Paper(
        family=str(uuid4()),
        version=str(uuid4()),
        title=title,
        overview=overview,
        latex=f"\\documentclass{{article}}\n\\begin{{document}}\n{body}\\end{{document}}\n",
        graph=graph,
    )


class FixedEmbedder:
    """The model service's query embedding, answered from a fixed table."""

    def __init__(self, vectors: dict[str, tuple[float, ...]]) -> None:
        self.vectors = vectors
        self.calls: list[tuple[str, str]] = []

    def embed_query(self, text: str, *, representation_hash: str) -> EmbeddingResult:
        self.calls.append((text, representation_hash))
        return EmbeddingResult(
            self.vectors[text], representation_hash, "model", "rev", "2026-01-01"
        )


class FakeRenderer:
    """A page rasterizer that returns distinct PNG-signed bytes per page."""

    def render(self, pdf_bytes: bytes, page_number: int) -> bytes:
        return b"\x89PNG\r\n\x1a\n" + f"page {page_number}".encode()


def identity() -> CommandIdentity:
    return CommandIdentity(uuid4(), uuid4(), uuid4(), uuid4())


@dataclass
class World:
    """Real storage owners over one disposable PostgreSQL schema."""

    database: Database
    store: ArtifactStore
    tmp_path: Path
    published: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.artifacts = ArtifactRepository(self.database, self.store)
        self.snapshots = SnapshotRepository(self.database, self.store, **SETTINGS)
        self.sheets = SheetRepository(self.database, self.store, **SETTINGS)
        self.runs = RunRepository(self.database, self.store, **SETTINGS)
        self.submissions = SubmissionRepository(self.database, self.store, **SETTINGS)
        self.trace = TraceRepository(self.database, self.store, **SETTINGS)
        self.paper_requests = PaperRequestRepository(
            self.database, self.store, **SETTINGS
        )
        self.documents = SnapshotDocuments(self.database, self.artifacts)
        self.queries = InspectorQueries(self.database, self.store)
        self.sheet_hash = self._seal_sheet()

    # --- artifacts and snapshots ---------------------------------------------

    def publish(
        self,
        payload: bytes,
        *,
        kind: str = "manifest",
        media_type: str = "application/json",
    ) -> str:
        """Publish *payload* once and return its manifest hash."""

        digest = sha256_hex(payload)
        if digest not in self.published:
            self.published[digest] = self.artifacts.publish(
                [payload],
                expected_hash=digest,
                byte_length=len(payload),
                maximum_length=1024 * 1024,
                media_type=media_type,
                kind=kind,
                input_hashes=(),
                producer_version=PRODUCER,
                config_hash="c" * 64,
                retention_policy_hash="d" * 64,
                command_id=uuid4(),
            ).manifest_hash
        return self.published[digest]

    def _data(self, body: bytes) -> dict[str, Any]:
        return dict(canonical_loads(body)["data"])  # type: ignore[index, arg-type]

    def _seal_sheet(self) -> str:
        response = self.sheets.execute(
            "seal",
            identity=identity(),
            payload={
                "questions": [
                    {
                        "question_id": question_id,
                        "target_definition_hash": "a" * 64,
                        "resolver_id": "citation-reach-v1",
                        "resolver_version": 1,
                        "horizon": "2099-09-01T00:00:00.000000Z",
                    }
                    for question_id in (QUESTION_A, QUESTION_B)
                ]
            },
        )
        return str(self._data(response.body)["sheet_hash"])

    def _pin(self, paper: Paper) -> dict[str, Any]:
        extraction_hash: str | None = None
        if paper.latex is not None:
            source = paper.latex.encode("utf-8")
            text = decode_latex_source(source)
            assert text is not None
            extraction = extract_latex(
                paper.version,
                sha256_hex(source),
                "e" * 64,
                text,
                "2026-01-01T00:00:00.000000Z",
            )
            extraction_bytes = extraction.to_canonical_json()
            extraction_hash = sha256_hex(extraction_bytes)
            self.publish(extraction_bytes, kind="extraction")
            canonical = normalize_text(text)
            passages = [
                {
                    "passage_order": record.passage_order,
                    "text_hash": record.text_hash,
                    "vector": list(
                        passage_vector(
                            canonical[record.char_start : record.char_end_exclusive]
                        )
                    ),
                }
                for record in build_passages(
                    extraction, canonical, extraction_hash, WhitespaceTokenizer()
                )
            ]
        else:
            assert paper.pdf is not None
            source = paper.pdf
            passages = []
        source_hash = sha256_hex(source)
        self.publish(
            source, kind="source_document", media_type="application/octet-stream"
        )
        card = {
            "paper_family_id": paper.family,
            "paper_version_id": paper.version,
            "representation_hash": REPRESENTATION,
            "overview": {"kind": "complete", "title": paper.title}
            if paper.abstract is None
            else {
                "kind": "complete",
                "title": paper.title,
                "abstract": paper.abstract,
                "spans": [],
            },
            "extraction_hash": extraction_hash,
            "original_source": {
                "source_hash": source_hash,
                "kind": "latex" if paper.latex is not None else "pdf",
            },
        }
        index = {
            "paper_version_id": paper.version,
            "extraction_hash": extraction_hash,
            "overview_vector": list(paper.overview),
            "passages": passages,
        }
        return {
            "paper_family_id": paper.family,
            "paper_version_id": paper.version,
            "card_hash": self.publish(canonical_json(card)),
            "overview_hash": None,
            "passage_index_hash": self.publish(canonical_json(index)),
            "graph_hash": None
            if paper.graph is None
            else self.publish(canonical_json(paper.graph)),
        }

    def seal_snapshot(self, papers: Sequence[Paper]) -> str:
        manifest = self.publish(
            canonical_json({"papers": sorted(paper.family for paper in papers)})
        )
        response = self.snapshots.execute(
            "seal",
            identity=identity(),
            payload={
                "paper_manifest_hash": manifest,
                "index_identity_hashes": [REPRESENTATION],
            },
        )
        snapshot_hash = str(self._data(response.body)["snapshot_hash"])
        self.snapshots.execute(
            "pin_items",
            identity=identity(),
            payload={
                "snapshot_hash": snapshot_hash,
                "sheet_hash": self.sheet_hash,
                "items": [self._pin(paper) for paper in papers],
            },
        )
        return snapshot_hash

    # --- runs ------------------------------------------------------------------

    def create_run(
        self,
        snapshot_hash: str,
        *,
        paper_id: str,
        allowed_tools: Sequence[str] = ALL_TOOLS,
    ) -> str:
        response = self.runs.execute(
            "create",
            identity=identity(),
            payload={
                "run_id": str(uuid4()),
                "slot": {
                    "batch_id": self.sheet_hash,
                    "paper_id": paper_id,
                    "configuration_id": str(uuid4()),
                    "attempt": 0,
                },
                "genome_hash": "f" * 64,
                "seed": 7,
                "snapshot_hash": snapshot_hash,
                "budgets": BUDGETS,
                "allowed_tools": list(allowed_tools),
                "model_identity": MODEL_IDENTITY,
                "checkpoint_dates": [],
                "issued_question_ids": [QUESTION_A, QUESTION_B],
            },
        )
        return str(self._data(response.body)["run_id"])

    def void(self, run_id: str) -> None:
        self.runs.finish_without_submit(
            identity=identity(), payload={"run_id": run_id, "reason": "model_stopped"}
        )

    def trace_rows(self, run_id: str) -> list[dict[str, Any]]:
        """The run's external trace, as a conduct check reads it."""

        rows = self.database.transaction(
            lambda connection: connection.execute(
                """SELECT c.call_sequence, c.tool, c.decision, c.reason,
                          t.outcome, t.error_code, t.retrieved_ids, t.budget_deltas
                   FROM run_trace_calls c
                   LEFT JOIN run_trace_terminals t
                     ON t.run_id = c.run_id AND t.call_sequence = c.call_sequence
                   WHERE c.run_id = %s ORDER BY c.call_sequence""",
                (run_id,),
            ).fetchall()
        )
        return [
            {
                "sequence": row[0],
                "tool": row[1],
                "decision": row[2],
                "reason": row[3],
                "outcome": row[4],
                "error_code": row[5],
                "retrieved_ids": [bytes(item).hex() for item in row[6] or []],
                "budget_deltas": None
                if row[7] is None
                else canonical_loads(bytes(row[7])),
            }
            for row in rows
        ]

    def count(self, table: str, run_id: str) -> int:
        assert table in {"run_submissions", "run_forecasts", "paper_requests"}
        row = self.database.transaction(
            lambda connection: connection.execute(
                f"SELECT count(*) FROM {table} WHERE run_id = %s", (run_id,)
            ).fetchone()
        )
        assert row is not None
        return int(row[0])

    # --- the storage boundary ------------------------------------------------

    @contextmanager
    def serve(self) -> Iterator[StorageClient]:
        """Storage over mutually authenticated HTTPS and a tools-role client."""

        (
            server_context,
            _client_context,
            tools_fingerprint,
            _wrong_context,
            _wrong_fingerprint,
            _no_certificate_context,
        ) = _tls_material(self.tmp_path)
        httpd = create_storage_server(
            ("127.0.0.1", 0),
            Jobs(),
            {tools_fingerprint: ServiceCapability(uuid4(), "tools", TOOL_SCOPES)},
            tls_context=server_context,
            authorization=StorageAuthorization(self.database),
            artifacts=self.artifacts,
            documents=self.documents,
            queries=self.queries,
            runs=self.runs,
            submissions=self.submissions,
            paper_requests=self.paper_requests,
            trace=self.trace,
        )
        thread = threading.Thread(target=httpd.serve_forever)
        thread.start()
        host, port = httpd.server_address[:2]
        try:
            yield StorageClient(
                connect_host=str(host),
                port=int(port),
                server_hostname="localhost",
                ca_file=self.tmp_path / "ca.pem",
                client_cert_file=self.tmp_path / "client.pem",
                client_key_file=self.tmp_path / "client.key",
                scopes=TOOL_SCOPES,
                timeout_seconds=10,
            )
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join()


def tool_service(
    storage: StorageClient,
    *,
    embedder: FixedEmbedder | None = None,
    index: SnapshotIndex | None = None,
    ask: AskHandler | None = None,
) -> ToolService:
    """The shared tool service with the five handlers over *storage*.

    ``ask`` adds the sixth (decision 0031), which needs a Jev stand-in.
    """

    index = index or SnapshotIndex(storage)
    texts = PinnedTexts(storage)
    tokenizer = WhitespaceTokenizer()
    extra: dict[str, AskHandler] = {} if ask is None else {"ask": ask}
    return ToolService(
        specifications=storage,
        handlers={
            **extra,
            "query_cards": QueryCardsHandler(
                storage=storage,
                index=index,
                embedder=embedder or FixedEmbedder({"attention": ATTENTION}),
                texts=texts,
                tokenizer=tokenizer,
            ),
            "neighbors": NeighborsHandler(storage=storage, index=index),
            "graph": GraphHandler(storage=storage),
            "deep_read": DeepReadHandler(
                texts=texts, tokenizer=tokenizer, renderer=FakeRenderer()
            ),
            "submit": SubmitHandler(storage=storage),
        },
        membership=StorageSnapshotMembership(storage),
        paper_requests=storage,
        trace=TraceWriter(storage),
    )


def envelope(
    arguments: object, *, note: object = "reading the cards", intent: object = "scan"
) -> dict[str, Any]:
    """*arguments* inside the note and intent envelope the model sends (AG-39)."""

    return {"note": note, "intent": intent, "arguments": arguments}


def lookup_args(*paper_ids: str) -> dict[str, Any]:
    return {
        "paper_ids": list(paper_ids),
        "query": None,
        "mode": None,
        "paper_id": None,
        "limit": None,
    }


def search_args(
    query: str, *, mode: str, paper_id: str | None = None, limit: int | None = None
) -> dict[str, Any]:
    return {
        "paper_ids": None,
        "query": query,
        "mode": mode,
        "paper_id": paper_id,
        "limit": limit,
    }


def deep_read_args(
    paper_id: str,
    *,
    section_id: str | None = None,
    pages: list[int] | None = None,
    next_span: str | None = None,
) -> dict[str, Any]:
    return {
        "paper_id": paper_id,
        "section_id": section_id,
        "pages": pages,
        "next_span": next_span,
    }


def submit_args(paper_id: str, evidence_id: str) -> dict[str, Any]:
    return {
        "submission_id": str(uuid4()),
        "answers": [
            {
                "question_id": question_id,
                "probability": 0.6,
                "rationale": "the method section supports this",
                "evidence_ids": [evidence_id],
            }
            for question_id in (QUESTION_A, QUESTION_B)
        ],
        "nomination": {
            "paper_id": paper_id,
            "recommend": True,
            "preference": 0.7,
            "rationale": "worth reading",
        },
    }
