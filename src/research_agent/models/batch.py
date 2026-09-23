"""Batch embedding manifest and CLI for embedding a corpus batch off-host.

``bin/embed-batch`` runs this module's ``main`` to embed extracted paper text
anywhere, reusing #112's ``FrozenEmbedder``/``RepresentationManifest`` and
``retrieval.passages.build_passages`` so no second implementation of pooling
or chunking exists here (Appendix A, Appendix C). Each paper version's
vectors are written to one file; the batch manifest names the pinned model
identity, the chunk policy, the platform the batch actually ran on and a
SHA-256 hash of every vector file, so ``models.equivalence`` can detect an
altered or substituted file before importing the batch.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research_agent.contracts.canonical import (
    canonical_json,
    canonical_loads,
    sha256_hex,
)
from research_agent.contracts.passages import CHUNK_POLICY, ExtractionRecord
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_finite,
    validate_non_empty_string,
    validate_sha256,
    validate_utc_date,
    validate_utc_instant,
)
from research_agent.reader.chunk import SectionTokenizer
from research_agent.retrieval.passages import build_passages

from .backend import TransformersDeviceBackend
from .embedding import FrozenEmbedder, overview_text
from .manifest import (
    DOCUMENT_PREFIX,
    DTYPE,
    MODEL_ID,
    POOLING,
    QUERY_PREFIX,
    REVISION,
)

__all__ = [
    "ALLOWED_DEVICES",
    "DEFAULT_MIN_COSINE_THRESHOLD",
    "PlatformIdentity",
    "BatchManifest",
    "PassageVector",
    "PaperBatch",
    "PaperText",
    "embed_paper_batch",
    "paper_batch_path",
    "write_paper_batch",
    "read_paper_batch",
    "paper_text_path",
    "read_paper_text",
    "manifest_path",
    "write_batch_manifest",
    "read_batch_manifest",
    "verify_batch_manifest",
    "run_batch",
    "detect_platform",
    "OffsetTokenizer",
    "TransformersDeviceBackend",
    "load_device_embedder",
    "main",
]

ALLOWED_DEVICES = frozenset({"cuda", "mps", "cpu"})

# #105: the launch profile's initial configured minimum platform agreement,
# until a measured amendment revises it.
DEFAULT_MIN_COSINE_THRESHOLD = 0.9999


def _validate_device(value: object) -> str:
    if not isinstance(value, str) or value not in ALLOWED_DEVICES:
        raise ContractValidationError("device must be one of cuda, mps, cpu")
    return value


def _require_dict(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractValidationError(f"{name} must be an object")
    return value


def _require_list(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ContractValidationError(f"{name} must be an array")
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True, slots=True)
class PlatformIdentity:
    """The device, driver and library identity a batch actually ran on."""

    device: str
    device_name: str
    driver_version: str
    library_versions: Mapping[str, str]

    def __post_init__(self) -> None:
        _validate_device(self.device)
        validate_non_empty_string(self.device_name)
        validate_non_empty_string(self.driver_version)
        if not self.library_versions:
            raise ContractValidationError("library_versions must not be empty")
        for name, version in self.library_versions.items():
            validate_non_empty_string(name)
            validate_non_empty_string(version)

    def to_dict(self) -> dict[str, object]:
        return {
            "device": self.device,
            "device_name": self.device_name,
            "driver_version": self.driver_version,
            "library_versions": dict(sorted(self.library_versions.items())),
        }

    @classmethod
    def from_dict(cls, value: object) -> "PlatformIdentity":
        mapping = _require_dict(value, "platform")
        library_versions = _require_dict(
            mapping.get("library_versions"), "library_versions"
        )
        return cls(
            device=str(mapping.get("device")),
            device_name=str(mapping.get("device_name")),
            driver_version=str(mapping.get("driver_version")),
            library_versions={str(k): str(v) for k, v in library_versions.items()},
        )


@dataclass(frozen=True, slots=True)
class BatchManifest:
    """The pinned identity, platform and file inventory of one embed-batch run."""

    model_id: str
    revision: str
    checkpoint_date: str
    dtype: str
    pooling: str
    document_prefix: str
    query_prefix: str
    chunk_policy: str
    platform: PlatformIdentity
    created_at: str
    min_cosine_threshold: float
    file_hashes: Mapping[str, str]

    def __post_init__(self) -> None:
        if self.model_id != MODEL_ID:
            raise ContractValidationError("model_id must be the pinned launch model")
        if self.revision != REVISION:
            raise ContractValidationError("revision must be the pinned launch revision")
        validate_utc_date(self.checkpoint_date)
        if self.dtype != DTYPE:
            raise ContractValidationError("dtype must be float32")
        if self.pooling != POOLING:
            raise ContractValidationError(
                "pooling must be attention-masked mean pooling"
            )
        if self.document_prefix != DOCUMENT_PREFIX:
            raise ContractValidationError("document_prefix must be the pinned prefix")
        if self.query_prefix != QUERY_PREFIX:
            raise ContractValidationError("query_prefix must be the pinned prefix")
        if self.chunk_policy != CHUNK_POLICY:
            raise ContractValidationError("chunk_policy must be the pinned policy")
        if not isinstance(self.platform, PlatformIdentity):
            raise ContractValidationError("platform must be a PlatformIdentity")
        validate_utc_instant(self.created_at)
        threshold = validate_finite(self.min_cosine_threshold)
        if not -1.0 <= threshold <= 1.0:
            raise ContractValidationError("min_cosine_threshold must be in [-1, 1]")
        if not self.file_hashes:
            raise ContractValidationError("a batch manifest requires at least one file")
        for paper_version_id, file_hash in self.file_hashes.items():
            validate_non_empty_string(paper_version_id)
            validate_sha256(file_hash)

    def to_dict(self) -> dict[str, object]:
        return {
            "model_id": self.model_id,
            "revision": self.revision,
            "checkpoint_date": self.checkpoint_date,
            "dtype": self.dtype,
            "pooling": self.pooling,
            "document_prefix": self.document_prefix,
            "query_prefix": self.query_prefix,
            "chunk_policy": self.chunk_policy,
            "platform": self.platform.to_dict(),
            "created_at": self.created_at,
            "min_cosine_threshold": self.min_cosine_threshold,
            "file_hashes": dict(sorted(self.file_hashes.items())),
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @property
    def namespace_id(self) -> str:
        """The representation-and-platform identity every vector in this batch shares.

        Appendix A: a vector computed on another platform belongs to another
        namespace and is never mixed with these; this identity excludes the
        per-run ``created_at``/``file_hashes`` so two batches run on the same
        platform for the same representation share one namespace id.
        """

        payload = self.to_dict()
        del payload["created_at"]
        del payload["file_hashes"]
        del payload["min_cosine_threshold"]
        return sha256_hex(canonical_json(payload))

    @classmethod
    def from_json(cls, raw: bytes) -> "BatchManifest":
        value = _require_dict(canonical_loads(raw), "batch manifest")
        file_hashes = _require_dict(value.get("file_hashes"), "file_hashes")
        return cls(
            model_id=str(value.get("model_id")),
            revision=str(value.get("revision")),
            checkpoint_date=str(value.get("checkpoint_date")),
            dtype=str(value.get("dtype")),
            pooling=str(value.get("pooling")),
            document_prefix=str(value.get("document_prefix")),
            query_prefix=str(value.get("query_prefix")),
            chunk_policy=str(value.get("chunk_policy")),
            platform=PlatformIdentity.from_dict(value.get("platform")),
            created_at=str(value.get("created_at")),
            min_cosine_threshold=float(value.get("min_cosine_threshold")),  # type: ignore[arg-type]
            file_hashes={str(k): str(v) for k, v in file_hashes.items()},
        )


@dataclass(frozen=True, slots=True)
class PassageVector:
    """One passage's identity and embedded vector inside a paper batch file."""

    passage_order: int
    text_hash: str
    vector: tuple[float, ...]

    def __post_init__(self) -> None:
        if self.passage_order < 0:
            raise ContractValidationError("passage_order must not be negative")
        validate_sha256(self.text_hash)
        if not self.vector:
            raise ContractValidationError("a passage vector must not be empty")
        for coordinate in self.vector:
            validate_finite(coordinate)

    def to_dict(self) -> dict[str, object]:
        return {
            "passage_order": self.passage_order,
            "text_hash": self.text_hash,
            "vector": list(self.vector),
        }

    @classmethod
    def from_dict(cls, value: object) -> "PassageVector":
        mapping = _require_dict(value, "passage vector")
        vector = _require_list(mapping.get("vector"), "vector")
        return cls(
            passage_order=int(mapping.get("passage_order")),  # type: ignore[arg-type]
            text_hash=str(mapping.get("text_hash")),
            vector=tuple(float(coordinate) for coordinate in vector),
        )


@dataclass(frozen=True, slots=True)
class PaperBatch:
    """One paper version's embedded overview and passage vectors."""

    paper_version_id: str
    extraction_hash: str
    chunk_policy: str
    coverage: str
    coverage_reasons: tuple[str, ...]
    overview_vector: tuple[float, ...]
    passages: tuple[PassageVector, ...]

    def __post_init__(self) -> None:
        validate_non_empty_string(self.paper_version_id)
        validate_sha256(self.extraction_hash)
        if self.chunk_policy != CHUNK_POLICY:
            raise ContractValidationError("chunk_policy must be the pinned policy")
        validate_non_empty_string(self.coverage)
        for reason in self.coverage_reasons:
            validate_non_empty_string(reason)
        if not self.overview_vector:
            raise ContractValidationError("a paper batch requires an overview vector")
        for coordinate in self.overview_vector:
            validate_finite(coordinate)
        if not all(isinstance(passage, PassageVector) for passage in self.passages):
            raise ContractValidationError("passages must be PassageVector values")
        orders = [passage.passage_order for passage in self.passages]
        if len(set(orders)) != len(orders):
            raise ContractValidationError("passage_order must not repeat")

    def to_dict(self) -> dict[str, object]:
        return {
            "paper_version_id": self.paper_version_id,
            "extraction_hash": self.extraction_hash,
            "chunk_policy": self.chunk_policy,
            "coverage": self.coverage,
            "coverage_reasons": list(self.coverage_reasons),
            "overview_vector": list(self.overview_vector),
            "passages": [passage.to_dict() for passage in self.passages],
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "PaperBatch":
        value = _require_dict(canonical_loads(raw), "paper batch")
        overview_vector = _require_list(value.get("overview_vector"), "overview_vector")
        passages = _require_list(value.get("passages"), "passages")
        reasons = _require_list(value.get("coverage_reasons"), "coverage_reasons")
        return cls(
            paper_version_id=str(value.get("paper_version_id")),
            extraction_hash=str(value.get("extraction_hash")),
            chunk_policy=str(value.get("chunk_policy")),
            coverage=str(value.get("coverage")),
            coverage_reasons=tuple(str(reason) for reason in reasons),
            overview_vector=tuple(float(coordinate) for coordinate in overview_vector),
            passages=tuple(PassageVector.from_dict(item) for item in passages),
        )


@dataclass(frozen=True, slots=True)
class PaperText:
    """One paper version's extracted text, as ``bin/embed-batch`` reads it."""

    paper_version_id: str
    title: str
    abstract: str
    extraction_hash: str
    canonical_text: str
    extraction: ExtractionRecord

    def to_dict(self) -> dict[str, object]:
        return {
            "paper_version_id": self.paper_version_id,
            "title": self.title,
            "abstract": self.abstract,
            "extraction_hash": self.extraction_hash,
            "canonical_text": self.canonical_text,
            "extraction": self.extraction.to_dict(),
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "PaperText":
        value = _require_dict(canonical_loads(raw), "paper text")
        extraction = _require_dict(value.get("extraction"), "extraction")
        return cls(
            paper_version_id=str(value.get("paper_version_id")),
            title=str(value.get("title")),
            abstract=str(value.get("abstract")),
            extraction_hash=str(value.get("extraction_hash")),
            canonical_text=str(value.get("canonical_text")),
            extraction=ExtractionRecord.from_json(canonical_json(extraction)),
        )


def embed_paper_batch(
    paper_text: PaperText,
    tokenizer: SectionTokenizer,
    embedder: FrozenEmbedder,
) -> PaperBatch:
    """Embed one paper version's overview and passages under the pinned model.

    Chunking is ``retrieval.passages.build_passages`` and pooling is
    ``FrozenEmbedder``; this function performs no second implementation of
    either (Appendix A, Appendix C).
    """

    passages = build_passages(
        paper_text.extraction,
        paper_text.canonical_text,
        paper_text.extraction_hash,
        tokenizer,
    )
    passage_texts = [
        paper_text.canonical_text[passage.char_start : passage.char_end_exclusive]
        for passage in passages
    ]
    # One call for the overview and every passage: the overview is one more
    # row in the same device batch, not a second forward pass of its own.
    vectors = embedder.embed_documents(
        [overview_text(paper_text.title, paper_text.abstract), *passage_texts]
    )
    overview_vector, passage_vectors = vectors[0], vectors[1:]
    return PaperBatch(
        paper_version_id=paper_text.paper_version_id,
        extraction_hash=paper_text.extraction_hash,
        chunk_policy=CHUNK_POLICY,
        coverage=paper_text.extraction.coverage,
        coverage_reasons=paper_text.extraction.coverage_reasons,
        overview_vector=overview_vector,
        passages=tuple(
            PassageVector(order, passage.text_hash, vector)
            for order, (passage, vector) in enumerate(zip(passages, passage_vectors))
        ),
    )


def paper_batch_path(out_dir: Path, paper_version_id: str) -> Path:
    return out_dir / f"{paper_version_id}.json"


def write_paper_batch(out_dir: Path, batch: PaperBatch) -> Path:
    path = paper_batch_path(out_dir, batch.paper_version_id)
    path.write_bytes(batch.to_canonical_json())
    return path


def read_paper_batch(path: Path) -> PaperBatch:
    return PaperBatch.from_json(path.read_bytes())


def paper_text_path(text_dir: Path, paper_version_id: str) -> Path:
    return text_dir / f"{paper_version_id}.json"


def read_paper_text(text_dir: Path, paper_version_id: str) -> PaperText:
    return PaperText.from_json(paper_text_path(text_dir, paper_version_id).read_bytes())


def manifest_path(out_dir: Path) -> Path:
    return out_dir / "manifest.json"


def write_batch_manifest(out_dir: Path, manifest: BatchManifest) -> Path:
    path = manifest_path(out_dir)
    path.write_bytes(manifest.to_canonical_json())
    return path


def read_batch_manifest(out_dir: Path) -> BatchManifest:
    return BatchManifest.from_json(manifest_path(out_dir).read_bytes())


def verify_batch_manifest(out_dir: Path, manifest: BatchManifest) -> None:
    """Recompute every named vector file's hash and refuse a mismatch.

    Catches a modified, truncated or substituted file before its vectors are
    published, independent of the model-identity checks ``BatchManifest``
    already enforces on construction.
    """

    for paper_version_id, expected_hash in manifest.file_hashes.items():
        path = paper_batch_path(out_dir, paper_version_id)
        if not path.exists():
            raise ContractValidationError(
                f"batch is missing its recorded file for {paper_version_id}",
            )
        actual_hash = sha256_hex(path.read_bytes())
        if actual_hash != expected_hash:
            raise ContractValidationError(
                f"batch file for {paper_version_id} does not match its recorded hash",
            )


def run_batch(
    text_dir: Path,
    out_dir: Path,
    embedder: FrozenEmbedder,
    tokenizer: SectionTokenizer,
    platform: PlatformIdentity,
    *,
    min_cosine_threshold: float = DEFAULT_MIN_COSINE_THRESHOLD,
) -> BatchManifest:
    """Embed every paper text file in ``text_dir``, resuming already-written papers.

    A paper version whose output file already exists in ``out_dir`` is not
    re-embedded, so an interrupted batch resumes from where it stopped.
    """

    out_dir.mkdir(parents=True, exist_ok=True)
    file_hashes: dict[str, str] = {}
    for text_path in sorted(text_dir.glob("*.json")):
        paper_text = PaperText.from_json(text_path.read_bytes())
        output_path = paper_batch_path(out_dir, paper_text.paper_version_id)
        if not output_path.exists():
            batch = embed_paper_batch(paper_text, tokenizer, embedder)
            write_paper_batch(out_dir, batch)
        file_hashes[paper_text.paper_version_id] = sha256_hex(output_path.read_bytes())

    manifest = BatchManifest(
        model_id=MODEL_ID,
        revision=REVISION,
        checkpoint_date=embedder.manifest.checkpoint_date,
        dtype=DTYPE,
        pooling=POOLING,
        document_prefix=DOCUMENT_PREFIX,
        query_prefix=QUERY_PREFIX,
        chunk_policy=CHUNK_POLICY,
        platform=platform,
        created_at=_utc_now(),
        min_cosine_threshold=min_cosine_threshold,
        file_hashes=file_hashes,
    )
    write_batch_manifest(out_dir, manifest)
    return manifest


def detect_platform(device: str) -> PlatformIdentity:
    """Read the device, driver and library identity the current process runs under."""

    import platform as platform_module
    from importlib import metadata

    _validate_device(device)
    library_versions = {
        "python": platform_module.python_version(),
        "torch": metadata.version("torch"),
        "transformers": metadata.version("transformers"),
    }
    if device == "cuda":
        import torch

        device_name = torch.cuda.get_device_name(0)
        driver_version = torch.version.cuda or "unknown"
    elif device == "mps":
        device_name = platform_module.processor() or "Apple Silicon GPU"
        driver_version = platform_module.mac_ver()[0] or "unknown"
    else:
        device_name = platform_module.processor() or "cpu"
        driver_version = platform_module.platform()
    return PlatformIdentity(
        device=device,
        device_name=device_name,
        driver_version=driver_version,
        library_versions=library_versions,
    )


class OffsetTokenizer:
    """Adapts a loaded Transformers tokenizer to ``SectionTokenizer``."""

    def __init__(self, tokenizer: Any) -> None:
        self._tokenizer = tokenizer

    def encode_offsets(self, text: str) -> Sequence[tuple[int, int]]:
        encoded = self._tokenizer(
            text, add_special_tokens=False, return_offsets_mapping=True
        )
        return [tuple(span) for span in encoded["offset_mapping"]]


def load_device_embedder(
    device: str, cache_dir: Path | None
) -> tuple[FrozenEmbedder, TransformersDeviceBackend]:
    """Load the pinned checkpoint onto any named device for an off-host batch.

    Unlike ``models.backend.load_frozen_embedder``, this accepts a
    caller-chosen device, including ``cpu``: an off-host batch's platform is
    recorded on its own ``BatchManifest`` and gated by the equivalence check
    in ``models.equivalence``, not fixed to the host's representation
    platform (Appendix A).
    """

    from huggingface_hub import snapshot_download

    from research_agent.contracts.learning import EMBEDDING_DIMENSION

    from .backend import resolved_file_hashes
    from .manifest import (
        ADOPTED_CHECKPOINT_DATE,
        MAX_MODEL_TOKENS,
        RepresentationManifest,
    )

    _validate_device(device)
    snapshot_dir = Path(
        snapshot_download(
            MODEL_ID,
            revision=REVISION,
            cache_dir=None if cache_dir is None else str(cache_dir),
        )
    )
    tokenizer_hash, weight_hash = resolved_file_hashes(snapshot_dir)
    manifest = RepresentationManifest(
        model_id=MODEL_ID,
        revision=REVISION,
        checkpoint_date=ADOPTED_CHECKPOINT_DATE,
        dtype=DTYPE,
        device=device,
        deterministic_algorithms=True,
        dimension=EMBEDDING_DIMENSION,
        pooling=POOLING,
        document_prefix=DOCUMENT_PREFIX,
        query_prefix=QUERY_PREFIX,
        max_model_tokens=MAX_MODEL_TOKENS,
        tokenizer_hash=tokenizer_hash,
        weight_hash=weight_hash,
        qualified=False,
    )
    backend = TransformersDeviceBackend.load(snapshot_dir, device)
    return FrozenEmbedder(manifest, backend), backend


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="embed-batch",
        description="Embed extracted paper text on any device under the pinned model.",
    )
    parser.add_argument(
        "--text", required=True, type=Path, help="extracted-text input directory"
    )
    parser.add_argument(
        "--out", required=True, type=Path, help="vector/manifest output directory"
    )
    parser.add_argument("--device", choices=sorted(ALLOWED_DEVICES), default="cpu")
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument(
        "--min-cosine-threshold",
        type=float,
        default=DEFAULT_MIN_COSINE_THRESHOLD,
        help="the platform equivalence floor this batch must clear to import (#105)",
    )
    args = parser.parse_args(argv)

    embedder, backend = load_device_embedder(args.device, args.cache_dir)
    platform = detect_platform(args.device)
    tokenizer = OffsetTokenizer(backend.tokenizer)
    manifest = run_batch(
        args.text,
        args.out,
        embedder,
        tokenizer,
        platform,
        min_cosine_threshold=args.min_cosine_threshold,
    )
    print(f"embedded {len(manifest.file_hashes)} paper versions into {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
