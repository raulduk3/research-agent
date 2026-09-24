"""Measured platform equivalence gate for imported batch vectors (Appendix A).

``bin/import-embeddings`` runs this module's ``main`` to verify a remote
batch's manifest, measure how closely N of its paper versions agree with the
same paper versions embedded on the host device, and only then publish the
batch's vectors into the host's representation namespace through
``retrieval.passages.publish_index``. A batch whose measured minimum cosine
agreement falls below its manifest's configured threshold is refused rather
than imported (#105).

Given a pilot's ``--state`` and ``--dsn``, it also builds the embedding view
of every version it publishes (#298), naming each by the family the pilot's
committed selection records for it (#302).

Every import records the namespace's manifest and prints its index identity
last; ``--print-identity --namespace DIR`` prints only that identity for an
already published namespace, the one ``bin/bindings --namespace`` binds
(#355).
"""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from research_agent.contracts.canonical import canonical_json
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_finite,
    validate_non_negative_int,
)
from research_agent.reader.chunk import SectionTokenizer
from research_agent.retrieval.passages import (
    IndexEntry,
    IndexPublicationResult,
    PublishedPassage,
    namespace_identity,
    publish_index,
    publish_namespace_manifest,
)

from . import batch as batch_module
from .backend import load_frozen_embedder_and_backend
from .embedding import FrozenEmbedder
from .embedding_view import EmbeddingViewSink, build_embedding_view, load_candidates

# Rounding a float cosine of two equal unit vectors can exceed one by a few
# ulps; this is the largest excess treated as rounding rather than a defect.
_COSINE_ROUNDING = 1e-6

__all__ = [
    "EquivalenceReport",
    "EquivalenceRefusedError",
    "ImportResult",
    "cosine_similarity",
    "compute_equivalence",
    "check_equivalence",
    "import_batch",
    "main",
]


class EquivalenceRefusedError(ContractValidationError):
    """The measured agreement between platforms is below the configured minimum."""


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Exact float64 cosine accumulation over stored vectors (Appendix A)."""

    if len(a) != len(b):
        raise ContractValidationError("compared vectors must be the same dimension")
    dot = math.fsum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(math.fsum(x * x for x in a))
    norm_b = math.sqrt(math.fsum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        raise ContractValidationError("compared vectors must be nonzero")
    return _bounded_cosine(dot / (norm_a * norm_b))


def _bounded_cosine(value: float) -> float:
    """Return ``value`` within [-1, 1], absorbing float rounding only.

    Two identical unit vectors can divide to 1.0000001 in float arithmetic;
    that is rounding, not a cosine above one, and the report's own bound
    would otherwise refuse the batch that agreed best. Anything past the
    rounding tolerance is a defect and stays refused downstream.
    """
    if 1.0 < value <= 1.0 + _COSINE_ROUNDING:
        return 1.0
    if -1.0 - _COSINE_ROUNDING <= value < -1.0:
        return -1.0
    return value


@dataclass(frozen=True, slots=True)
class EquivalenceReport:
    """Measured agreement between a host device and a remote batch's vectors."""

    sample_count: int
    min_cosine: float
    mean_cosine: float
    max_absolute_difference: float

    def __post_init__(self) -> None:
        validate_non_negative_int(self.sample_count)
        if self.sample_count == 0:
            raise ContractValidationError(
                "an equivalence report requires at least one sample",
            )
        for value in (self.min_cosine, self.mean_cosine, self.max_absolute_difference):
            validate_finite(value)
        if not -1.0 <= self.min_cosine <= 1.0 or not -1.0 <= self.mean_cosine <= 1.0:
            raise ContractValidationError("cosine similarity must be in [-1, 1]")
        if self.max_absolute_difference < 0:
            raise ContractValidationError(
                "max_absolute_difference must not be negative"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "sample_count": self.sample_count,
            "min_cosine": self.min_cosine,
            "mean_cosine": self.mean_cosine,
            "max_absolute_difference": self.max_absolute_difference,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())


def compute_equivalence(
    host_vectors: Sequence[Sequence[float]],
    batch_vectors: Sequence[Sequence[float]],
) -> EquivalenceReport:
    """Compare paired host/batch vectors for the same paper versions, same order."""

    if not host_vectors:
        raise ContractValidationError(
            "equivalence comparison requires at least one pair"
        )
    if len(host_vectors) != len(batch_vectors):
        raise ContractValidationError("host and batch vector counts must match")
    cosines: list[float] = []
    max_abs_diff = 0.0
    for host_vector, batch_vector in zip(host_vectors, batch_vectors, strict=True):
        if len(host_vector) != len(batch_vector):
            raise ContractValidationError("compared vectors must be the same dimension")
        cosines.append(cosine_similarity(host_vector, batch_vector))
        max_abs_diff = max(
            max_abs_diff,
            max(abs(h - b) for h, b in zip(host_vector, batch_vector, strict=True)),
        )
    return EquivalenceReport(
        sample_count=len(cosines),
        min_cosine=min(cosines),
        mean_cosine=math.fsum(cosines) / len(cosines),
        max_absolute_difference=max_abs_diff,
    )


def check_equivalence(
    host_vectors: Sequence[Sequence[float]],
    batch_vectors: Sequence[Sequence[float]],
    *,
    min_cosine: float,
) -> EquivalenceReport:
    """Compute the equivalence report and refuse import when it falls short.

    Import into the host's representation namespace is refused when the
    measured minimum cosine agreement is below the configured threshold
    (#105); otherwise the report is the evidence import records beside both
    platforms.
    """

    report = compute_equivalence(host_vectors, batch_vectors)
    if report.min_cosine < min_cosine:
        raise EquivalenceRefusedError(
            f"measured minimum cosine {report.min_cosine!r} is below the "
            f"configured threshold {min_cosine!r}",
        )
    return report


@dataclass(frozen=True, slots=True)
class ImportResult:
    """What one ``import_batch`` call actually measured and published.

    ``views`` are the manifest hashes of the embedding views this call
    stored, one per published paper version its sink could name whose view
    changed; ``views_current`` counts the versions whose stored view was
    already the one this batch builds.
    """

    manifest: batch_module.BatchManifest
    equivalence: EquivalenceReport
    published: tuple[IndexPublicationResult, ...]
    namespace_identity: str
    views: tuple[str, ...] = ()
    views_current: int = 0


def import_batch(
    batch_dir: Path,
    namespace_dir: Path,
    text_dir: Path,
    host_embedder: FrozenEmbedder,
    tokenizer: SectionTokenizer,
    check_count: int,
    *,
    views: EmbeddingViewSink | None = None,
    current_view: Callable[[str], Mapping[str, Any] | None] | None = None,
) -> ImportResult:
    """Verify, equivalence-check and publish one embed-batch run's vectors.

    Refuses a manifest whose model identity or chunk policy differs from the
    service's: ``BatchManifest`` itself rejects any drift from the pinned
    identity on construction, so a manifest that reads at all already
    matches. Refuses a manifest whose files were altered after it was
    written, and refuses import when the measured platform agreement over
    ``check_count`` sampled paper versions falls below the manifest's
    configured threshold.

    With a ``views`` sink, every published paper version the sink names
    then gets its embedding view (#298), its neighbors ranked over the
    namespace as this batch left it. ``current_view`` answers a family's
    current stored view; a version whose view equals it is not stored
    again, so rerunning an import over an unchanged namespace records no
    view (#302). Every input a view is derived from is named in the view
    itself, so equal views have equal provenance.
    """

    if check_count <= 0:
        raise ContractValidationError("check_count must be positive")

    manifest = batch_module.read_batch_manifest(batch_dir)
    batch_module.verify_batch_manifest(batch_dir, manifest)

    paper_version_ids = sorted(manifest.file_hashes)
    checked_ids = paper_version_ids[:check_count]
    host_vectors: list[tuple[float, ...]] = []
    batch_vectors: list[tuple[float, ...]] = []
    for paper_version_id in checked_ids:
        paper_text = batch_module.read_paper_text(text_dir, paper_version_id)
        host_batch = batch_module.embed_paper_batch(
            paper_text, tokenizer, host_embedder
        )
        imported_batch = batch_module.read_paper_batch(
            batch_module.paper_batch_path(batch_dir, paper_version_id)
        )
        host_vectors.append(host_batch.overview_vector)
        batch_vectors.append(imported_batch.overview_vector)
    equivalence = check_equivalence(
        host_vectors, batch_vectors, min_cosine=manifest.min_cosine_threshold
    )

    # The equivalence gate admits the batch's vectors into the host's
    # representation, so the namespace records the host's manifest, before
    # any entry: a namespace built under another is refused untouched.
    representation = host_embedder.manifest.to_dict()
    del representation["qualified"]
    namespace = publish_namespace_manifest(
        namespace_dir, representation, manifest.chunk_policy
    )

    platform = manifest.platform.to_dict()
    equivalence_dict = equivalence.to_dict()
    published: list[IndexPublicationResult] = []
    entries: list[IndexEntry] = []
    for paper_version_id in paper_version_ids:
        paper_batch = batch_module.read_paper_batch(
            batch_module.paper_batch_path(batch_dir, paper_version_id)
        )
        entry = IndexEntry(
            paper_version_id=paper_batch.paper_version_id,
            extraction_hash=paper_batch.extraction_hash,
            chunk_policy=paper_batch.chunk_policy,
            coverage=paper_batch.coverage,
            coverage_reasons=paper_batch.coverage_reasons,
            overview_vector=paper_batch.overview_vector,
            passages=tuple(
                PublishedPassage(
                    passage.passage_order, passage.text_hash, passage.vector
                )
                for passage in paper_batch.passages
            ),
            platform=platform,
            equivalence=equivalence_dict,
        )
        published.append(publish_index(namespace_dir, entry))
        entries.append(entry)

    stored: list[str] = []
    unchanged = 0
    if views is not None:
        identities = views.identities()
        candidates = load_candidates(namespace_dir, identities)
        for entry in entries:
            identity = identities.get(entry.paper_version_id)
            if identity is None:
                continue
            view = build_embedding_view(
                identity=identity,
                text=batch_module.read_paper_text(text_dir, entry.paper_version_id),
                entry=entry,
                tokenizer=tokenizer,
                representation_hash=host_embedder.manifest.representation_hash,
                candidates=candidates,
            )
            current = (
                None if current_view is None else current_view(identity.paper_family_id)
            )
            if current is not None and canonical_json(current) == canonical_json(view):
                unchanged += 1
                continue
            stored.append(views.store(view, ()))

    return ImportResult(
        manifest=manifest,
        equivalence=equivalence,
        published=tuple(published),
        namespace_identity=namespace,
        views=tuple(stored),
        views_current=unchanged,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="import-embeddings",
        description=(
            "Verify a remote embed-batch run, measure its platform agreement "
            "with the host device, and publish it into the host's index."
        ),
    )
    parser.add_argument("--in", dest="batch_dir", type=Path)
    parser.add_argument("--namespace", dest="namespace_dir", required=True, type=Path)
    parser.add_argument(
        "--print-identity",
        action="store_true",
        help="print the index identity of the published --namespace and nothing else",
    )
    parser.add_argument(
        "--text",
        dest="text_dir",
        type=Path,
        help="the same extracted-text input directory bin/embed-batch read",
    )
    parser.add_argument(
        "--check",
        dest="check_count",
        type=int,
        help="how many paper versions to re-embed on the host device for the equivalence gate",
    )
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument(
        "--state",
        type=Path,
        default=None,
        help="the pilot state bin/export-text read; builds each version's embedding view",
    )
    parser.add_argument("--dsn", default=None, help="DSN selecting that pilot's schema")
    args = parser.parse_args(argv)
    import_options = (args.batch_dir, args.text_dir, args.check_count)
    if args.print_identity:
        if any(value is not None for value in (*import_options, args.state, args.dsn)):
            parser.error("--print-identity takes only --namespace")
        try:
            print(namespace_identity(args.namespace_dir))
        except ContractValidationError as error:
            print(f"refused: {error}", file=sys.stderr)
            return 2
        return 0
    if any(value is None for value in import_options):
        parser.error("--in, --text and --check are required to import")
    if (args.state is None) != (args.dsn is None):
        parser.error("--state and --dsn are given together")
    if args.state is not None and not (args.state / "state.json").exists():
        parser.error("no pilot state exists at --state")

    embedder, backend = load_frozen_embedder_and_backend(args.cache_dir)
    tokenizer = batch_module.OffsetTokenizer(backend.tokenizer)
    if args.state is None:
        result = import_batch(
            args.batch_dir,
            args.namespace_dir,
            args.text_dir,
            embedder,
            tokenizer,
            args.check_count,
        )
    else:
        # Imported here: the gate alone needs no storage.
        from research_agent.ingest.requests import LocalEmbeddingViews
        from research_agent.learning.text_export import (
            pilot_storage,
            release_identities,
        )
        from research_agent.storage.embedding_views import EmbeddingViewRepository

        with pilot_storage(args.state, args.dsn) as storage:
            result = import_batch(
                args.batch_dir,
                args.namespace_dir,
                args.text_dir,
                embedder,
                tokenizer,
                args.check_count,
                views=LocalEmbeddingViews(storage, release_identities(storage)),
                current_view=EmbeddingViewRepository(
                    storage.database, storage.artifacts
                ).current,
            )
    reused = sum(1 for item in result.published if item.reused)
    print(
        f"published {len(result.published)} paper versions "
        f"({reused} already current) into {args.namespace_dir}; "
        f"min cosine {result.equivalence.min_cosine:.6f} over "
        f"{result.equivalence.sample_count} sampled paper versions",
    )
    if args.state is not None:
        print(
            f"stored {len(result.views)} embedding views "
            f"({result.views_current} already current)",
        )
    print(f"namespace identity {result.namespace_identity}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
