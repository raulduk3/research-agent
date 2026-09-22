"""The real pinned model, standard Transformers inference on CPU (Appendix A).

Loading this backend downloads and runs the pinned checkpoint, so no default
test imports this module's ``load_frozen_embedder``; qualification against
the real weights is an explicitly invoked, budgeted job outside default CI
(Appendix A: Launch profile).
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from research_agent.contracts.learning import EMBEDDING_DIMENSION

from .embedding import FrozenEmbedder, TokenBudgetExceededError, TokenEncoding
from .manifest import (
    ADOPTED_CHECKPOINT_DATE,
    DTYPE,
    MAX_MODEL_TOKENS,
    MODEL_ID,
    POOLING,
    DOCUMENT_PREFIX,
    QUERY_PREFIX,
    REVISION,
    RepresentationManifest,
)

__all__ = ["TransformersCPUBackend", "load_frozen_embedder", "resolved_file_hashes"]

_WEIGHT_SUFFIXES = (".safetensors", ".bin")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _combined_hash(hashes: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for value in sorted(hashes):
        digest.update(value.encode("ascii"))
    return digest.hexdigest()


def resolved_file_hashes(snapshot_dir: Path) -> tuple[str, str]:
    """Combine the pinned checkpoint's actual tokenizer and weight file hashes."""

    weight_hashes: list[str] = []
    tokenizer_hashes: list[str] = []
    for path in sorted(snapshot_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix in _WEIGHT_SUFFIXES:
            weight_hashes.append(_file_sha256(path))
        elif path.suffix == ".json":
            tokenizer_hashes.append(_file_sha256(path))
    if not weight_hashes:
        raise ValueError("no pinned weight files found in the resolved snapshot")
    if not tokenizer_hashes:
        raise ValueError(
            "no pinned tokenizer/config files found in the resolved snapshot"
        )
    return _combined_hash(tokenizer_hashes), _combined_hash(weight_hashes)


class TransformersCPUBackend:
    """Standard Transformers CPU float32 inference for the pinned revision.

    Owns tokenization and the forward pass only; FrozenEmbedder applies the
    prefix, token budget and pooling so the same pooling math runs whether
    the caller is this backend or a deterministic test fixture.
    """

    def __init__(self, tokenizer: Any, model: Any) -> None:
        self._tokenizer = tokenizer
        self._model = model

    @classmethod
    def load(cls, snapshot_dir: Path) -> "TransformersCPUBackend":
        import torch
        from transformers import AutoModel, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(str(snapshot_dir))
        model = AutoModel.from_pretrained(str(snapshot_dir), torch_dtype=torch.float32)
        model.eval()
        return cls(tokenizer, model)

    def encode(self, texts: Sequence[str]) -> Sequence[TokenEncoding]:
        import torch

        if not texts:
            return ()
        token_counts = [
            len(self._tokenizer(text, truncation=False)["input_ids"]) for text in texts
        ]
        for count in token_counts:
            if count > MAX_MODEL_TOKENS:
                raise TokenBudgetExceededError(
                    "text exceeds the pinned model token limit",
                )
        batch = self._tokenizer(
            list(texts), padding=True, truncation=False, return_tensors="pt"
        )
        with torch.inference_mode():
            output = self._model(**batch)
        hidden_states = output.last_hidden_state
        attention_mask = batch["attention_mask"]
        encodings: list[TokenEncoding] = []
        for index, count in enumerate(token_counts):
            hidden = tuple(
                tuple(float(value) for value in row)
                for row in hidden_states[index].tolist()
            )
            mask = tuple(int(value) for value in attention_mask[index].tolist())
            encodings.append(TokenEncoding(hidden, mask, count))
        return encodings


def load_frozen_embedder(cache_dir: Path | None = None) -> FrozenEmbedder:
    """Resolve, hash and load the pinned checkpoint into a serving FrozenEmbedder.

    Downloads the checkpoint on first use through the given cache directory,
    or the standard Hugging Face cache when none is given. The returned
    manifest is unqualified: this repository revision is selected, not
    demonstrated qualified (Appendix A), until the retrieval qualification
    protocol records evidence.
    """

    from huggingface_hub import snapshot_download

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
        dimension=EMBEDDING_DIMENSION,
        pooling=POOLING,
        document_prefix=DOCUMENT_PREFIX,
        query_prefix=QUERY_PREFIX,
        max_model_tokens=MAX_MODEL_TOKENS,
        tokenizer_hash=tokenizer_hash,
        weight_hash=weight_hash,
        qualified=False,
    )
    backend = TransformersCPUBackend.load(snapshot_dir)
    return FrozenEmbedder(manifest, backend)
