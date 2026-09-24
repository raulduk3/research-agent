"""The single shared model-serving owner (SDD PL-08).

One shared model service on the host holds the only loaded copy of the
frozen embedding model and the qualified numeric prediction-head bundle,
and answers every embedding and prediction request the reader and tools
make. Every vector it returns carries the producing model's identity and
checkpoint date (RD-02, RD-03); every prediction it returns carries the
producing bundle's identity (PL-13), so a downstream paper card can stamp
both.

The tool service reaches the same instance over one mutually
authenticated route, ``POST /v1/embeddings/query`` (#287): a search query
is embedded here under the pinned model's query prefix, never by a second
copy of the model in the tools container. ``GET /health`` on the same
listener reports the held embedder and bundle to an admitted caller (#315).
"""

from __future__ import annotations

import hashlib
import hmac
import ssl
import threading
import time
import tracemalloc
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from research_agent.contracts.canonical import (
    CanonicalJsonError,
    canonical_json,
    canonical_loads,
)
from research_agent.contracts.learning import TargetDefinition
from research_agent.contracts.passages import ResourceDemand
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_sha256,
)

from .embedding import FrozenEmbedder, overview_text
from .manifest import RepresentationManifest
from .predict import PredictionArtifact, predict_targets
from .registry import PublishedHead, ServingHandle

__all__ = [
    "ModelServiceAlreadyRunningError",
    "PredictionBundleUnavailableError",
    "RepresentationMismatchError",
    "EmbeddingResult",
    "BatchDemand",
    "BatchDemandRecorder",
    "ModelService",
    "MAXIMUM_QUERY_CHARS",
    "create_model_server",
]

# The longest query ``query_cards`` admits (``contracts.tools``).
MAXIMUM_QUERY_CHARS = 2048
_MAXIMUM_REQUEST_BYTES = 64 * 1024


class ModelServiceAlreadyRunningError(RuntimeError):
    """Raised when a second instance would hold a serving copy of the weights.

    PL-08: one shared model service holds the only copy of the small models
    loaded for serving; nothing else loads them in its place.
    """


class RepresentationMismatchError(RuntimeError):
    """Raised when a request names a representation this service does not hold."""


class PredictionBundleUnavailableError(RuntimeError):
    """Raised when a prediction is requested and no bundle has ever activated.

    PL-13: readiness fails rather than adopting an unpromoted candidate.
    """


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    """One served vector, stamped with the identity that produced it."""

    vector: tuple[float, ...]
    representation_hash: str
    model_id: str
    revision: str
    checkpoint_date: str


@dataclass(frozen=True, slots=True)
class BatchDemand:
    """Wall time, peak memory, CPU time and volume a served batch actually used."""

    paper_count: int
    passage_count: int
    resource: ResourceDemand
    cpu_seconds: float

    def __post_init__(self) -> None:
        if self.paper_count < 0 or self.passage_count < 0:
            raise ValueError("paper_count and passage_count must not be negative")
        if self.cpu_seconds < 0:
            raise ValueError("cpu_seconds must not be negative")


class BatchDemandRecorder:
    """Accumulates paper/passage counts for one in-flight batch measurement."""

    def __init__(self) -> None:
        self.paper_count = 0
        self.passage_count = 0
        self.demand: BatchDemand | None = None

    def record_paper(self) -> None:
        self.paper_count += 1

    def record_passages(self, count: int) -> None:
        if count < 0:
            raise ValueError("count must not be negative")
        self.passage_count += count


class ModelService:
    """Owns the single loaded FrozenEmbedder and answers every embedding request.

    Construction refuses to run beside an already-running instance in this
    process, standing in for the deployment-level guarantee that exactly one
    shared model service is ever started on the host.
    """

    _lock = threading.Lock()
    _active: "ModelService | None" = None

    def __init__(
        self,
        embedder: FrozenEmbedder,
        *,
        serving_handle: ServingHandle | None = None,
        heads: Mapping[str, PublishedHead] | None = None,
    ) -> None:
        with ModelService._lock:
            if ModelService._active is not None:
                raise ModelServiceAlreadyRunningError(
                    "a shared model service already holds the frozen embedder",
                )
            ModelService._active = self
        self._embedder = embedder
        self._closed = False
        self._serving_handle = serving_handle
        self._heads = dict(heads) if heads else {}

    @property
    def manifest(self) -> RepresentationManifest:
        """The pinned embedder this service holds, for readiness and launch checks."""

        return self._embedder.manifest

    @property
    def manifest_representation_hash(self) -> str:
        return self._embedder.manifest.representation_hash

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def serving_handle(self) -> ServingHandle | None:
        """The bundle this service holds for every admitted request (PL-13).

        ``None`` before any bundle has ever been activated: readiness fails
        rather than adopting an unpromoted candidate (SDD PL-13).
        """

        return self._serving_handle

    def close(self) -> None:
        """Release this process's hold on the single serving slot."""

        with ModelService._lock:
            if ModelService._active is self:
                ModelService._active = None
        self._closed = True

    def __enter__(self) -> "ModelService":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def embed_overview(self, title: str, abstract: str) -> EmbeddingResult:
        """Embed a paper's original title and abstract (Appendix A, Appendix B)."""

        self._require_open()
        (vector,) = self._embedder.embed_documents([overview_text(title, abstract)])
        return self._stamp(vector)

    def embed_passages(self, texts: Sequence[str]) -> tuple[EmbeddingResult, ...]:
        """Embed already-extracted passage texts in the caller's given order."""

        self._require_open()
        vectors = self._embedder.embed_documents(texts)
        return tuple(self._stamp(vector) for vector in vectors)

    def embed_query(self, text: str, *, representation_hash: str) -> EmbeddingResult:
        """Embed one search query under the ``search_query: `` prefix (RD-26).

        The caller names the representation it ranks against; a request for
        any other is refused rather than answered from this one (PL-14).
        """

        self._require_open()
        if representation_hash != self.manifest_representation_hash:
            raise RepresentationMismatchError(
                "query names a representation this service does not serve"
            )
        (vector,) = self._embedder.embed_queries([text])
        return self._stamp(vector)

    def predict_targets(
        self,
        definitions: tuple[TargetDefinition, TargetDefinition, TargetDefinition],
        *,
        original_version_id: str,
        requested_bundle_hash: str,
        representation_hash: str,
        embedding_block: tuple[float, ...],
        metadata_block: tuple[float, ...],
        computed_at: str,
        available_at: str,
    ) -> tuple[PredictionArtifact, PredictionArtifact, PredictionArtifact]:
        """The one route to a prediction: no caller reaches a head directly (PL-08).

        Uses the bundle this service already holds; a caller naming a
        different bundle id or representation namespace is refused rather
        than served from a pointer it never admitted (PL-13, PL-14).
        """

        self._require_open()
        if self._serving_handle is None:
            raise PredictionBundleUnavailableError(
                "no prediction-head bundle has ever been activated"
            )
        return predict_targets(
            self._serving_handle,
            self._heads,
            definitions,
            original_version_id=original_version_id,
            requested_bundle_hash=requested_bundle_hash,
            representation_hash=representation_hash,
            embedding_block=embedding_block,
            metadata_block=metadata_block,
            computed_at=computed_at,
            available_at=available_at,
        )

    def _stamp(self, vector: tuple[float, ...]) -> EmbeddingResult:
        manifest = self._embedder.manifest
        return EmbeddingResult(
            vector=vector,
            representation_hash=manifest.representation_hash,
            model_id=manifest.model_id,
            revision=manifest.revision,
            checkpoint_date=manifest.checkpoint_date,
        )

    def _require_open(self) -> None:
        if self._closed:
            raise ModelServiceAlreadyRunningError(
                "this model service instance has been closed",
            )

    @contextmanager
    def measure_batch(self) -> Iterator[BatchDemandRecorder]:
        """Record one batch's wall time, peak memory, CPU seconds and volume."""

        recorder = BatchDemandRecorder()
        tracemalloc.start()
        wall_started = time.perf_counter()
        cpu_started = time.process_time()
        try:
            yield recorder
        finally:
            wall_seconds = time.perf_counter() - wall_started
            cpu_seconds = time.process_time() - cpu_started
            _current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            recorder.demand = BatchDemand(
                paper_count=recorder.paper_count,
                passage_count=recorder.passage_count,
                resource=ResourceDemand(wall_seconds, peak),
                cpu_seconds=cpu_seconds,
            )


def create_model_server(
    address: tuple[str, int],
    service: ModelService,
    *,
    tls_context: ssl.SSLContext,
    client_fingerprints: frozenset[str],
) -> ThreadingHTTPServer:
    """Serve *service*'s query embedding to the admitted client certificates.

    ``POST /v1/embeddings/query`` and the readiness route ``GET /health``
    (#315), over mutually authenticated TLS: a caller whose certificate
    fingerprint is not admitted is refused before its request is read.
    """

    if tls_context.verify_mode != ssl.CERT_REQUIRED:
        raise ValueError("the model service requires verified client certificates")
    if not client_fingerprints:
        raise ValueError("at least one client certificate is required")
    for fingerprint in client_fingerprints:
        validate_sha256(fingerprint)

    class Handler(_ModelRequestHandler):
        model = service
        fingerprints = client_fingerprints

    server = ThreadingHTTPServer(address, Handler)
    server.socket = tls_context.wrap_socket(server.socket, server_side=True)
    return server


class _ModelRequestHandler(BaseHTTPRequestHandler):
    model: ModelService
    fingerprints: frozenset[str]
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802
        if not self._authenticated():
            self._reply(401, error="unauthenticated")
            return
        if self.path != "/v1/embeddings/query":
            self._reply(404, error="not_found")
            return
        try:
            text, representation_hash = self._query_request()
        except ContractValidationError as error:
            self._reply(422, error="invalid_input", message=str(error))
            return
        try:
            result = self.model.embed_query(
                text, representation_hash=representation_hash
            )
        except RepresentationMismatchError as error:
            self._reply(409, error="representation_mismatch", message=str(error))
            return
        except ModelServiceAlreadyRunningError as error:
            self._reply(503, error="unavailable", message=str(error))
            return
        self._reply(
            200,
            data={
                "vector": list(result.vector),
                "representation_hash": result.representation_hash,
                "model_id": result.model_id,
                "revision": result.revision,
                "checkpoint_date": result.checkpoint_date,
            },
        )

    def _authenticated(self) -> bool:
        connection = self.connection
        if not isinstance(connection, ssl.SSLSocket):
            return False
        certificate = connection.getpeercert(binary_form=True)
        if certificate is None:
            return False
        supplied = hashlib.sha256(certificate).hexdigest()
        return any(
            hmac.compare_digest(supplied, fingerprint)
            for fingerprint in self.fingerprints
        )

    def _query_request(self) -> tuple[str, str]:
        if self.headers.get("Content-Type") != "application/json":
            raise ContractValidationError("Content-Type must be application/json")
        raw_length = self.headers.get("Content-Length", "")
        if not raw_length.isascii() or not raw_length.isdigit():
            raise ContractValidationError("a valid Content-Length is required")
        length = int(raw_length)
        if length > _MAXIMUM_REQUEST_BYTES:
            self.close_connection = True
            raise ContractValidationError("query request is too large")
        try:
            value = canonical_loads(self.rfile.read(length))
        except CanonicalJsonError as error:
            raise ContractValidationError(
                "query request is not canonical JSON"
            ) from error
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "text",
            "representation_hash",
        }:
            raise ContractValidationError("query request has unknown or missing fields")
        if isinstance(value["schema_version"], bool) or value["schema_version"] != 1:
            raise ContractValidationError("schema_version must be 1")
        text = validate_non_empty_string(value["text"])
        if len(text) > MAXIMUM_QUERY_CHARS:
            raise ContractValidationError("query text is too long")
        return text, validate_sha256(value["representation_hash"])

    def _reply(
        self,
        status: int,
        *,
        data: dict[str, Any] | None = None,
        error: str | None = None,
        message: str = "",
    ) -> None:
        body = canonical_json(
            {
                "schema_version": 1,
                "status": "ok" if error is None else "error",
                "data": data,
                "error": None
                if error is None
                else {"code": error, "message": message[:512]},
            }
        )
        if error is not None:
            # An unread or refused body must not be parsed as a next request.
            self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        # A query is agent-written text; the service logger owns safe metadata.
        return

    def do_GET(self) -> None:  # noqa: N802
        if not self._authenticated():
            self._reply(401, error="unauthenticated")
            return
        if self.path != "/health":
            self._reply(404, error="not_found")
            return
        if self.model.closed:
            self._reply(503, error="unavailable", message="the model service is closed")
            return
        handle = self.model.serving_handle
        manifest = self.model.manifest
        self._reply(
            200,
            data={
                "state": "ready",
                "representation_hash": manifest.representation_hash,
                "model_id": manifest.model_id,
                "revision": manifest.revision,
                "bundle_hash": None if handle is None else handle.bundle_hash,
            },
        )

    def _unsupported_method(self) -> None:
        self._reply(404, error="not_found")

    do_PUT = _unsupported_method
    do_PATCH = _unsupported_method
    do_DELETE = _unsupported_method
