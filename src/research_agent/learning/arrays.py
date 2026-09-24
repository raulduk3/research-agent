"""Materialize verified TrainingArrays for the existing numerical owner."""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from typing import cast

import numpy as np
from numpy.typing import NDArray

from research_agent.contracts.learning import (
    AutomaticLabel,
    CombinedFeatureRecord,
    EMBEDDING_FEATURE_DIMENSION,
    TARGET_IDS,
    TargetRegistry,
    TrainingArrays,
)
from research_agent.contracts.primitives import validate_sha256
from research_agent.learning.features import CardMetadata, assemble_metadata_block
from research_agent.learning.fit import FitError, MaterializedPartition
from research_agent.learning.tensors import decode_tensor
from research_agent.storage.errors import IntegrityFailure


def materialize_training_arrays(
    record: TrainingArrays,
    *,
    read_tensor: Callable[[str], bytes],
    registry: TargetRegistry,
    solver_runtime_hash: str,
    read_label: Callable[[str], AutomaticLabel] | None,
    read_feature: Callable[[str], CombinedFeatureRecord] | None,
    read_metadata: Callable[[str], CardMetadata] | None,
    requested_family_ids: frozenset[str],
) -> MaterializedPartition:
    """Resolve tensor rows against immutable feature, label and card records.

    This internal adapter establishes row consistency, not corpus admission or
    qualification. Release membership, receipt cutoffs and extraction lineage
    remain responsibilities of the authoritative corpus adapter. The row
    identity check covers the embedding prefix against its committed
    ``CombinedFeatureRecord``; the metadata tail is assembled beside it from
    the card record ``read_metadata`` resolves for the row's family (#149).
    A row for a family in ``requested_family_ids`` -- a paper an agent
    requested -- refuses the whole record: requested papers never train a
    prediction head (decision 0025), and dropping the row would misalign
    every tensor after it.
    """

    validate_sha256(solver_runtime_hash)
    if not requested_family_ids.isdisjoint(record.ordered_family_ids):
        raise FitError("training arrays hold an agent-requested paper")
    registry_hash = sha256(registry.to_canonical_json()).hexdigest()
    if record.target_registry_hash != registry_hash:
        raise FitError("training arrays target registry differs")
    definition_hashes = cast(
        tuple[str, str, str],
        tuple(
            sha256(item.to_canonical_json()).hexdigest()
            for item in registry.definitions
        ),
    )
    if tuple(item.target_id for item in registry.definitions) != TARGET_IDS:
        raise FitError("target registry order differs from training contract")
    if read_label is None:
        raise FitError("label record reader is required for training materialization")
    if read_feature is None:
        raise FitError("feature record reader is required for training materialization")
    if read_metadata is None:
        raise FitError("card metadata reader is required for training materialization")

    features = cast(
        NDArray[np.float32],
        decode_tensor(record.features, read_tensor(record.features.payload_hash)),
    )
    labels = cast(
        NDArray[np.uint8],
        decode_tensor(record.labels, read_tensor(record.labels.payload_hash)),
    )
    mask = cast(
        NDArray[np.uint8],
        decode_tensor(record.known_mask, read_tensor(record.known_mask.payload_hash)),
    )
    for row_index, family_id in enumerate(record.ordered_family_ids):
        feature_hash = record.feature_hashes[row_index]
        feature = read_feature(feature_hash)
        if sha256(feature.to_canonical_json()).hexdigest() != feature_hash:
            raise IntegrityFailure("combined feature bytes do not match identity")
        if (
            feature.paper_family_id != family_id
            or feature.representation_hash != record.representation_hash
        ):
            raise FitError("combined feature row or representation binding differs")
        vector = decode_tensor(
            feature.combined_vector, read_tensor(feature.combined_vector.payload_hash)
        )
        embedding_block = features[row_index, :EMBEDDING_FEATURE_DIMENSION]
        if vector.tobytes() != embedding_block.tobytes():
            raise FitError("combined feature tensor differs from training row")
        metadata = read_metadata(family_id)
        metadata_vector = np.asarray(
            assemble_metadata_block(metadata), dtype=np.float32
        )
        metadata_block = features[row_index, EMBEDDING_FEATURE_DIMENSION:]
        if metadata_vector.tobytes() != metadata_block.tobytes():
            raise FitError("assembled metadata block differs from training row")
        for target_index, label_hash in enumerate(record.label_hashes[row_index]):
            if label_hash is None:
                if mask[row_index, target_index] or labels[row_index, target_index]:
                    raise FitError("missing label reference has known tensor value")
                continue
            label = read_label(label_hash)
            if sha256(label.to_canonical_json()).hexdigest() != label_hash:
                raise IntegrityFailure("automatic label bytes do not match identity")
            if (
                label.paper_family_id != family_id
                or label.target_id != TARGET_IDS[target_index]
                or label.target_definition_hash != definition_hashes[target_index]
            ):
                raise FitError("automatic label row or target binding differs")
            expected_known = label.state in {"true", "false"}
            expected_value = 1 if label.state == "true" else 0
            if (
                bool(mask[row_index, target_index]) != expected_known
                or int(labels[row_index, target_index]) != expected_value
            ):
                raise FitError("automatic label state differs from tensor values")
    return MaterializedPartition(
        features,
        labels,
        mask,
        record.ordered_family_ids,
        record.partition,
        record.corpus_release_hash,
        record.split_hash,
        record.target_registry_hash,
        record.representation_hash,
        solver_runtime_hash,
        definition_hashes,
    )
