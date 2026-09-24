"""Acquiring the papers agents requested, end to end (decision 0025, TDD-3.1.78).

Real PostgreSQL, the real storage service over mTLS for both the request
routes and the capture worker, the real documents job, extractor, batch
embedding loop, index publication, card assembly and snapshot seal. Only
the remote arXiv host (a loopback HTTPS server) and the model's forward
pass (a deterministic backend) stand in for the outside world.
"""

from __future__ import annotations

import gzip
import hashlib
import ssl
import subprocess
import sys
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import canonical_loads
from research_agent.contracts.learning import EMBEDDING_DIMENSION
from research_agent.contracts.passages import CHUNK_POLICY
from research_agent.contracts.primitives import ProducerVersion
from research_agent.ingest.arxiv import ArxivListing, ArxivVersion, fetch_document
from research_agent.ingest.fetch import BoundedResponse
from research_agent.ingest.pilot import (
    Identity,
    PilotWorker,
    RateGate,
    Sources,
    derived_uuid,
)
from research_agent.ingest.pilot_local import (
    LocalStorage,
    local_storage,
    worker_principal,
)
from research_agent.ingest.requests import (
    RequestReader,
    acquire_requests,
    listing_identities,
)
from research_agent.models.batch import PlatformIdentity
from research_agent.models.embedding import FrozenEmbedder, TokenEncoding
from research_agent.models.manifest import (
    ADOPTED_CHECKPOINT_DATE,
    DOCUMENT_PREFIX,
    DTYPE,
    MAX_MODEL_TOKENS,
    MODEL_ID,
    POOLING,
    QUERY_PREFIX,
    REVISION,
    RepresentationManifest,
)
from research_agent.retrieval.passages import IndexEntry
from research_agent.snapshots.compose import seal_next_snapshot
from research_agent.storage.artifacts import ArtifactManifest
from research_agent.storage.client import StorageClient
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.snapshots import SnapshotRepository

# The storage test helpers are flat modules in tests/storage.
sys.path.insert(0, str(Path(__file__).parents[1] / "storage"))
from test_exclusions import PRODUCER, World, world  # noqa: E402
from test_requests import record, repository, served  # noqa: E402

pytestmark = pytest.mark.integration

__all__ = ["served", "world"]

IDENTITY = Identity(
    ProducerVersion("a" * 64, "b" * 40, 1), "c" * 64, "d" * 64, "e" * 64
)
READABLE = ("2305.01937", "2305.01938")
MISSING = "2305.01939"
LATEX = (
    r"\documentclass{article}\begin{document}\section{Introduction}"
    r"We study how requested papers reach the corpus. "
    r"\section{Method}Each request is fetched, read and embedded once."
    r"\end{document}"
)


def _listing(family_id: str) -> ArxivListing:
    return ArxivListing(
        family_id,
        "2023-05-03",
        ("cs.AI",),
        (ArxivVersion(1, "2023-05-03T10:00:00.000000Z"),),
        f"Requested paper {family_id}",
        "An abstract about acquisition.",
        "http://creativecommons.org/licenses/by/4.0/",
        None,
        "Author One and Author Two",
    )


def _family(arxiv_id: str) -> UUID:
    return derived_uuid("gate-paper-family", arxiv_id)


class _Backend:
    """One token per word, a fixed vector per token: a deterministic stand-in
    for the model's forward pass; pooling and chunking stay the real ones."""

    def __init__(self) -> None:
        self.calls = 0

    def encode(self, texts: Sequence[str]) -> Sequence[TokenEncoding]:
        self.calls += 1
        encodings = []
        for text in texts:
            tokens = text.split()
            hidden = tuple(
                tuple(
                    float(byte) - 128.0
                    for byte in (hashlib.sha256(token.encode()).digest() * 24)[
                        :EMBEDDING_DIMENSION
                    ]
                )
                for token in tokens
            )
            encodings.append(TokenEncoding(hidden, (1,) * len(tokens), len(tokens)))
        return encodings


class _Words:
    def encode_offsets(self, text: str) -> Sequence[tuple[int, int]]:
        offsets, index = [], 0
        while index < len(text):
            while index < len(text) and text[index].isspace():
                index += 1
            start = index
            while index < len(text) and not text[index].isspace():
                index += 1
            if index > start:
                offsets.append((start, index))
        return offsets


def _embedder(backend: _Backend) -> FrozenEmbedder:
    manifest = RepresentationManifest(
        model_id=MODEL_ID,
        revision=REVISION,
        checkpoint_date=ADOPTED_CHECKPOINT_DATE,
        dtype=DTYPE,
        device="mps",
        deterministic_algorithms=True,
        dimension=EMBEDDING_DIMENSION,
        pooling=POOLING,
        document_prefix=DOCUMENT_PREFIX,
        query_prefix=QUERY_PREFIX,
        max_model_tokens=MAX_MODEL_TOKENS,
        tokenizer_hash="a" * 64,
        weight_hash="b" * 64,
        qualified=False,
    )
    return FrozenEmbedder(manifest, backend)  # type: ignore[arg-type]


@contextmanager
def _arxiv(
    tmp_path: Path, readable: tuple[str, ...] = READABLE, latex: str = LATEX
) -> Iterator[tuple[int, ssl.SSLContext, list[str]]]:
    """Loopback HTTPS standing in for export.arxiv.org: the readable families
    have gzipped LaTeX source, any other has nothing at all."""

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
    log: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            log.append(self.path)
            found = any(self.path == f"/src/{f}v1" for f in readable)
            body = gzip.compress(latex.encode()) if found else b""
            self.send_response(200 if found else 404)
            self.send_header("Content-Type", "application/gzip")
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
        yield server.server_port, ssl.create_default_context(cafile=str(cert)), log
    finally:
        server.shutdown()
        server.server_close()


def _sources(port: int, context: ssl.SSLContext) -> Sources:
    def document(path: str) -> BoundedResponse:
        return fetch_document(path, host="localhost", port=port, context=context)

    def unreachable(*_: object, **__: object) -> Any:
        raise AssertionError("acquisition never lists or reaches OpenAlex")

    return Sources(
        listing=unreachable,
        document=document,
        openalex_match=unreachable,
        openalex_cites=unreachable,
        arxiv_gate=RateGate(0.001),
        openalex_gate=RateGate(0.001),
    )


def _json(storage: LocalStorage, manifest_hash: str) -> dict[str, Any]:
    return storage.report(manifest_hash)


def _inputs(storage: LocalStorage, manifest_hash: str) -> tuple[str, ...]:
    (_, _), stream = storage.artifacts.read(manifest_hash)
    with stream:
        return ArtifactManifest.from_json(stream.read()).input_hashes


def _requests(dsn: str) -> dict[UUID, tuple[str, str | None, UUID | None]]:
    with psycopg.connect(dsn) as connection:
        rows = connection.execute(
            "SELECT id, status, reason, paper_version_id FROM paper_requests"
        ).fetchall()
    return {
        cast(UUID, row[0]): (str(row[1]), row[2], cast(UUID | None, row[3]))
        for row in rows
    }


def test_open_requests_become_cards_in_the_next_snapshot_and_a_fetch_failure_does_not(
    world: World,
    artifact_root: Path,
    tmp_path: Path,
    served: tuple[StorageClient, StorageClient],
) -> None:
    _tools, ingest = served
    requests = repository(world, artifact_root)
    snapshots = SnapshotRepository(
        Database(world.dsn),
        ArtifactStore(artifact_root),
        producer=PRODUCER,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )
    before = world.snapshot_hash

    with (
        _arxiv(tmp_path) as (port, context, log),
        local_storage(
            dsn=world.dsn,
            artifact_root=artifact_root,
            tls_directory=tmp_path / "worker-tls",
            identity=IDENTITY,
        ) as storage,
    ):
        publish = storage.publish_spec
        # The snapshot the run reads holds one drawn paper.
        drawn = [
            {
                "paper_family_id": str(uuid4()),
                "paper_version_id": str(uuid4()),
                "card_hash": publish({"drawn": True}),
                "overview_hash": None,
                "passage_index_hash": None,
                "graph_hash": None,
            }
        ]
        snapshots.execute(
            "pin_items",
            identity=CommandIdentity(uuid4(), uuid4(), uuid4(), uuid4()),
            payload={
                "snapshot_hash": before,
                "sheet_hash": world.sheet_hash,
                "items": drawn,
            },
        )
        run_id = world.run(uuid4(), "p1")
        asked = {
            arxiv_id: UUID(
                record(requests, run_id, _family(arxiv_id), before)["request_id"]
            )
            for arxiv_id in (*READABLE, MISSING)
        }

        backend = _Backend()
        reader = RequestReader(
            storage,
            PilotWorker(
                storage.client,
                worker_id=worker_principal(tmp_path / "worker-tls"),
                identity=IDENTITY,
                sources=_sources(port, context),
            ),
            identities=listing_identities(
                _listing(arxiv_id) for arxiv_id in (*READABLE, MISSING)
            ),
            work_dir=tmp_path / "work",
            namespace_dir=tmp_path / "index",
            embedder=_embedder(backend),
            tokenizer=_Words(),
            platform=PlatformIdentity("cpu", "test", "0", {"torch": "0"}),
        )
        report = acquire_requests(ingest, reader)

        # Each family's source was requested from arXiv once, under the gate.
        assert sorted(p for p in log if p.startswith("/src/")) == sorted(
            f"/src/{f}v1" for f in (*READABLE, MISSING)
        )
        stored = _requests(world.dsn)
        missing = stored[asked[MISSING]]
        assert missing[0] == "failed"
        assert missing[1] is not None and missing[1].startswith("fetch failed")
        assert missing[2] is None
        assert report.failed == ((str(asked[MISSING]), missing[1]),)
        assert report.refused == ()

        assert len(report.acquired) == len(READABLE)
        for arxiv_id in READABLE:
            status, reason, version = stored[asked[arxiv_id]]
            assert (status, reason) == ("acquired", None)
            item = next(
                i for i in report.acquired if i["paper_version_id"] == str(version)
            )
            assert item["paper_family_id"] == str(_family(arxiv_id))
            card = _json(storage, item["card_hash"])
            assert card["paper_version_id"] == str(version)
            assert card["passage_count"] > 0
            assert card["passage_coverage"] == "complete"
            assert {h["unavailable_reason"] for h in card["head_predictions"]} == {
                "disabled_by_profile"
            }
            assert {h["forecast_eligibility"] for h in card["head_predictions"]} == {
                "late_arrival"
            }
            assert card["head_feature_unavailable_reason"] == "disabled_by_profile"
            # The section map is built from the paper's passages (#270).
            titles = [s["title"] for s in card["sections"]]
            assert titles[-2:] == ["Introduction", "Method"]
            # The card descends from the paper record, which names its request.
            (paper_hash,) = _inputs(storage, item["card_hash"])
            paper = _json(storage, paper_hash)
            assert paper["requested_by"] == str(asked[arxiv_id])
            assert paper["family_id"] == str(_family(arxiv_id))
            assert (tmp_path / "index" / f"{version}.json").exists()

        # One embedding batch for every paper read in the pass.
        assert len(list((tmp_path / "work" / "vectors").iterdir())) == 1
        # No card, record or index entry for the failed request.
        missing_version = derived_uuid("gate-paper-version", MISSING)
        assert not (tmp_path / "index" / f"{missing_version}.json").exists()
        with psycopg.connect(world.dsn) as connection:
            hashes = [
                str(row[0])
                for row in connection.execute(
                    """SELECT encode(manifest_hash,'hex') FROM artifact_productions
                       JOIN artifacts ON artifacts.hash = artifact_hash
                       WHERE artifacts.media_type='application/json'"""
                ).fetchall()
            ]
        for manifest_hash in hashes:
            try:
                body = _json(storage, manifest_hash)
            except Exception:  # not a JSON object: not a record or a card
                continue
            assert body.get("requested_by") != str(asked[MISSING])
            assert body.get("paper_family_id") != str(_family(MISSING))

        after = seal_next_snapshot(
            snapshots,
            publish,
            principal_id=uuid4(),
            prior_items=drawn,
            acquired=report.acquired,
            index_identity_hashes=("e" * 64,),
            sheet_hashes=(world.sheet_hash,),
        )

    assert after != before
    with psycopg.connect(world.dsn) as connection:
        pinned = {
            (str(row[0]), str(row[1]))
            for row in connection.execute(
                """SELECT encode(snapshot_hash,'hex'), paper_version_id
                   FROM snapshot_items"""
            ).fetchall()
        }
        sealed = connection.execute(
            "SELECT count(*) FROM snapshots WHERE hash=decode(%s,'hex')", (before,)
        ).fetchone()
    assert sealed == (1,)
    # The snapshot the requests came from still holds only its drawn paper.
    assert {v for s, v in pinned if s == before} == {drawn[0]["paper_version_id"]}
    assert {v for s, v in pinned if s == after} == {
        drawn[0]["paper_version_id"],
        *(i["paper_version_id"] for i in report.acquired),
    }
    assert backend.calls >= 1

    # A second pass finds nothing open and changes nothing.
    assert acquire_requests(ingest, reader).acquired == ()
    assert _requests(world.dsn) == stored


CITING = "2305.01940"
CITING_LATEX = (
    r"\documentclass{article}\begin{document}\section{Introduction}"
    r"We build on three earlier results about acquisition. "
    r"\section{Method}Each cited result is read beside the new one."
    r"\begin{thebibliography}{9}"
    r"\bibitem{one} A. Author. First result. arXiv:2301.00001v1."
    r"\bibitem{two} B. Author. Second result. arXiv:2302.00002v1."
    r"\bibitem{three} C. Author. Third result, never embedded."
    r"\end{thebibliography}\end{document}"
)


def _pinned(
    storage: LocalStorage,
    representation_hash: str,
    *,
    title: str,
    first_public_at: str,
    vector: tuple[float, ...],
) -> dict[str, Any]:
    """One snapshot item with a published card and index entry."""

    family, version = str(uuid4()), str(uuid4())
    entry = IndexEntry(
        paper_version_id=version,
        extraction_hash="f" * 64,
        chunk_policy=CHUNK_POLICY,
        coverage="complete",
        coverage_reasons=(),
        overview_vector=vector,
        passages=(),
        platform={"device": "cpu"},
        equivalence=None,
    )
    card = {
        "paper_family_id": family,
        "paper_version_id": version,
        "as_of": "2023-06-01T00:00:00.000000Z",
        "overview": {"title": title},
        "first_public_at": first_public_at,
        "representation_hash": representation_hash,
    }
    return {
        "paper_family_id": family,
        "paper_version_id": version,
        "card_hash": storage.publish_spec(card),
        "overview_hash": None,
        "passage_index_hash": storage.publish_spec(
            cast(dict[str, Any], canonical_loads(entry.to_canonical_json()))
        ),
        "graph_hash": None,
    }


def test_a_requested_card_shows_its_earlier_neighbors_and_its_cited_families(
    world: World,
    artifact_root: Path,
    tmp_path: Path,
    served: tuple[StorageClient, StorageClient],
) -> None:
    _tools, ingest = served
    requests = repository(world, artifact_root)
    embedder = _embedder(_Backend())
    representation = embedder.manifest.representation_hash
    ones = (1.0,) * EMBEDDING_DIMENSION
    alternating = tuple(float((-1) ** i) for i in range(EMBEDDING_DIMENSION))
    with (
        _arxiv(tmp_path, (CITING,), CITING_LATEX) as (port, context, _log),
        local_storage(
            dsn=world.dsn,
            artifact_root=artifact_root,
            tls_directory=tmp_path / "worker-tls",
            identity=IDENTITY,
        ) as storage,
    ):
        first, second, later = (
            _pinned(storage, representation, title=title, first_public_at=at, vector=v)
            for title, at, v in (
                ("First result", "2023-01-10T00:00:00.000000Z", ones),
                ("Second result", "2023-02-10T00:00:00.000000Z", alternating),
                # Published after the requested paper: never its neighbor.
                ("Later result", "2023-05-10T00:00:00.000000Z", ones),
            )
        )
        # The third cited family has no vector in the snapshot.
        cited = (first["paper_family_id"], second["paper_family_id"], str(uuid4()))
        run_id = world.run(uuid4(), "p1")
        record(requests, run_id, _family(CITING), world.snapshot_hash)
        reader = RequestReader(
            storage,
            PilotWorker(
                storage.client,
                worker_id=worker_principal(tmp_path / "worker-tls"),
                identity=IDENTITY,
                sources=_sources(port, context),
            ),
            identities=listing_identities([_listing(CITING)]),
            work_dir=tmp_path / "work",
            namespace_dir=tmp_path / "index",
            embedder=embedder,
            tokenizer=_Words(),
            platform=PlatformIdentity("cpu", "test", "0", {"torch": "0"}),
            citation_edges=lambda family: ((), cited) if family == CITING else None,
            snapshot_items=(first, second, later),
        )
        report = acquire_requests(ingest, reader)

        assert report.failed == ()
        (item,) = report.acquired
        card = _json(storage, item["card_hash"])

    assert {n["paper_family_id"]: n["card_id"] for n in card["neighbors"]} == {
        first["paper_family_id"]: first["card_hash"],
        second["paper_family_id"]: second["card_hash"],
    }
    assert {n["title"] for n in card["neighbors"]} == {"First result", "Second result"}
    assert card["neighbor_embedding_distance"]["status"] == "available"
    graph = card["graph"]
    assert graph["outgoing_family_count"] == 3
    # Three \bibitem entries parsed; two of the cited families have a vector.
    assert graph["reference_count"] == 3
    assert graph["reference_vector_count"] == 2
    assert graph["missing_reference_vector_count"] == 1
    assert graph["reference_centroid_distance"]["status"] == "available"
