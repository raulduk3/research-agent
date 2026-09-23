"""The single shared model-serving owner (SDD PL-08).

One shared model service on the host holds the only loaded copy of the
frozen embedding model and the qualified numeric prediction-head bundle,
and answers every embedding and prediction request the reader and tools
make. Every vector it returns carries the producing model's identity and
checkpoint date (RD-02, RD-03); every prediction it returns carries the
producing bundle's identity (PL-13), so a downstream paper card can stamp
both.
"""

from __future__ import annotations

import threading
import time
import tracemalloc
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass

from research_agent.contracts.learning import TargetDefinition
from research_agent.contracts.passages import ResourceDemand

from .embedding import FrozenEmbedder, overview_text
from .predict import PredictionArtifact, predict_targets
from .registry import PublishedHead, ServingHandle

__all__ = [
    "ModelServiceAlreadyRunningError",
    "PredictionBundleUnavailableError",
    "EmbeddingResult",
    "BatchDemand",
    "BatchDemandRecorder",
    "ModelService",
]


class ModelServiceAlreadyRunningError(RuntimeError):
    """Raised when a second instance would hold a serving copy of the weights.

    PL-08: one shared model service holds the only copy of the small models
    loaded for serving; nothing else loads them in its place.
    """


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
    def manifest_representation_hash(self) -> str:
        return self._embedder.manifest.representation_hash

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
