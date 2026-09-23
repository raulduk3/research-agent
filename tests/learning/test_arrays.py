from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from typing import cast
from uuid import UUID

import numpy as np
import pytest

from research_agent.contracts import (
    ProducerVersion,
    RecordMeta,
    canonical_json,
    canonical_loads,
)
from research_agent.contracts.learning import (
    AutomaticLabel,
    CountBounds,
    CombinedFeatureRecord,
    EMBEDDING_FEATURE_DIMENSION,
    LabelCounts,
    TargetRegistry,
    TrainingArrays,
)
from research_agent.contracts.primitives import ContractValidationError
from research_agent.learning.arrays import materialize_training_arrays
from research_agent.learning.features import CardMetadata, assemble_metadata_block
from research_agent.learning.fit import FitError
from research_agent.learning.tensors import encode_tensor
from research_agent.outcomes.targets import definitions
from research_agent.storage.errors import IntegrityFailure

META = RecordMeta(
    1,
    (),
    ProducerVersion("a" * 64, "b" * 40, 1),
    "c" * 64,
    "2026-09-21T00:00:00.000000Z",
)


def _uuid(index: int) -> str:
    return str(UUID(bytes=sha256(str(index).encode()).digest()[:16], version=4))


def _metadata_records() -> dict[str, CardMetadata]:
    return {
        _uuid(1): CardMetadata(
            author_count=2,
            categories=("cs.AI",),
            abstract_tokens=10,
            title_tokens=3,
            first_available_weekday=0,
            code_link=False,
            version_count=1,
        ),
        _uuid(2): CardMetadata(
            author_count=1,
            categories=("cs.LG",),
            abstract_tokens=20,
            title_tokens=4,
            first_available_weekday=3,
            code_link=True,
            version_count=2,
        ),
    }


def _fixture() -> tuple[
    TrainingArrays,
    TargetRegistry,
    dict[str, bytes],
    dict[str, AutomaticLabel],
    dict[str, CombinedFeatureRecord],
    dict[str, CardMetadata],
]:
    targets = definitions(META)
    registry = TargetRegistry(
        1,
        (),
        META.producer_version,
        META.config_hash,
        META.created_at,
        "automatic-citations-v1",
        targets,
        ("cs.AI", "cs.LG"),
    )
    registry_hash = sha256(registry.to_canonical_json()).hexdigest()
    family_ids = (_uuid(1), _uuid(2))
    metadata_records = _metadata_records()
    embedding = np.zeros((2, EMBEDDING_FEATURE_DIMENSION), dtype=np.float32)
    embedding[0, 0] = 1
    embedding[1, 1] = 1
    metadata_blocks = np.array(
        [
            assemble_metadata_block(metadata_records[family_id])
            for family_id in family_ids
        ],
        dtype=np.float32,
    )
    x = np.concatenate((embedding, metadata_blocks), axis=1)
    y = np.array(((1, 0, 1), (0, 1, 0)), dtype=np.uint8)
    mask = np.ones((2, 3), dtype=np.uint8)
    x_ref, x_bytes = encode_tensor(x)
    y_ref, y_bytes = encode_tensor(y)
    m_ref, m_bytes = encode_tensor(mask)
    tensors = {
        x_ref.payload_hash: x_bytes,
        y_ref.payload_hash: y_bytes,
        m_ref.payload_hash: m_bytes,
    }
    empty = CountBounds(0, 0)
    counts = LabelCounts(empty, empty, empty, empty)
    labels: dict[str, AutomaticLabel] = {}
    rows: list[tuple[str | None, str | None, str | None]] = []
    for row, family_id in enumerate(family_ids):
        hashes = []
        for column, target in enumerate(targets):
            state = "true" if y[row, column] else "false"
            label = AutomaticLabel(
                1,
                (),
                META.producer_version,
                META.config_hash,
                META.created_at,
                family_id,
                target.target_id,
                sha256(target.to_canonical_json()).hexdigest(),
                state,
                "sufficient_positive_witnesses"
                if state == "true"
                else "complete_negative_evidence",
                "d" * 64,
                counts,
                (),
                (),
                (),
                "2026-01-01T00:00:00.000000Z",
                META.created_at,
                None,
                None,
            )
            digest = sha256(label.to_canonical_json()).hexdigest()
            labels[digest] = label
            hashes.append(digest)
        rows.append(cast(tuple[str | None, str | None, str | None], tuple(hashes)))
    feature_records = {}
    feature_hashes = []
    for row, family_id in enumerate(family_ids):
        vector_ref, vector_bytes = encode_tensor(embedding[row])
        pool_ref, pool_bytes = encode_tensor(embedding[row, :768])
        tensors[vector_ref.payload_hash] = vector_bytes
        tensors[pool_ref.payload_hash] = pool_bytes
        feature = CombinedFeatureRecord(
            1,
            (),
            META.producer_version,
            META.config_hash,
            META.created_at,
            family_id,
            _uuid(100 + row),
            "5" * 64,
            "6" * 64,
            "3" * 64,
            "7" * 64,
            ("8" * 64,),
            (1.0,),
            pool_ref,
            vector_ref,
            "overview_passage_sqrt2_v1",
            META.created_at,
        )
        digest = sha256(feature.to_canonical_json()).hexdigest()
        feature_records[digest] = feature
        feature_hashes.append(digest)
    record = TrainingArrays(
        1,
        (x_ref.payload_hash, y_ref.payload_hash, m_ref.payload_hash),
        META.producer_version,
        META.config_hash,
        META.created_at,
        family_ids,
        x_ref,
        y_ref,
        m_ref,
        tuple(feature_hashes),
        tuple(rows),
        "1" * 64,
        "2" * 64,
        registry_hash,
        "3" * 64,
        "fit",
    )
    return record, registry, tensors, labels, feature_records, metadata_records


def test_materialize_verifies_tensors_labels_and_preserves_row_order() -> None:
    record, registry, tensors, labels, features, metadata = _fixture()
    partition = materialize_training_arrays(
        record,
        read_tensor=tensors.__getitem__,
        registry=registry,
        solver_runtime_hash="4" * 64,
        read_label=labels.__getitem__,
        read_feature=features.__getitem__,
        read_metadata=metadata.__getitem__,
        requested_family_ids=frozenset(),
    )
    assert partition.family_ids == record.ordered_family_ids
    assert np.array_equal(
        partition.labels, np.array(((1, 0, 1), (0, 1, 0)), dtype=np.uint8)
    )
    with pytest.raises(ValueError):
        partition.features.setflags(write=True)
    assert TrainingArrays.from_json(record.to_canonical_json()) == record


def test_training_arrays_json_is_closed_and_shapes_are_exact() -> None:
    record, _, _, _, _, _ = _fixture()
    value = canonical_loads(record.to_canonical_json())
    assert isinstance(value, dict)
    value["unexpected"] = True
    with pytest.raises(ContractValidationError, match="fields"):
        TrainingArrays.from_json(canonical_json(value))
    with pytest.raises(ContractValidationError, match="references"):
        replace(
            record, features=replace(record.features, shape=(2, 768), byte_length=6144)
        )


def test_materialize_fails_closed_without_label_reader_and_on_label_mismatch() -> None:
    record, registry, tensors, labels, features, metadata = _fixture()
    with pytest.raises(FitError, match="reader is required"):
        materialize_training_arrays(
            record,
            read_tensor=tensors.__getitem__,
            registry=registry,
            solver_runtime_hash="4" * 64,
            read_label=None,
            read_feature=features.__getitem__,
            read_metadata=metadata.__getitem__,
            requested_family_ids=frozenset(),
        )
    first_hash = record.label_hashes[0][0]
    assert first_hash is not None
    labels[first_hash] = replace(labels[first_hash], paper_family_id=_uuid(99))
    with pytest.raises(IntegrityFailure, match="identity"):
        materialize_training_arrays(
            record,
            read_tensor=tensors.__getitem__,
            registry=registry,
            solver_runtime_hash="4" * 64,
            read_label=labels.__getitem__,
            read_feature=features.__getitem__,
            read_metadata=metadata.__getitem__,
            requested_family_ids=frozenset(),
        )


def test_materialize_rejects_registry_tensor_and_label_state_mismatches() -> None:
    record, registry, tensors, labels, features, metadata = _fixture()
    with pytest.raises(FitError, match="registry differs"):
        materialize_training_arrays(
            replace(record, target_registry_hash="9" * 64),
            read_tensor=tensors.__getitem__,
            registry=registry,
            solver_runtime_hash="4" * 64,
            read_label=labels.__getitem__,
            read_feature=features.__getitem__,
            read_metadata=metadata.__getitem__,
            requested_family_ids=frozenset(),
        )
    damaged = dict(tensors)
    damaged[record.features.payload_hash] = b"x" * record.features.byte_length
    with pytest.raises(IntegrityFailure, match="tensor bytes"):
        materialize_training_arrays(
            record,
            read_tensor=damaged.__getitem__,
            registry=registry,
            solver_runtime_hash="4" * 64,
            read_label=labels.__getitem__,
            read_feature=features.__getitem__,
            read_metadata=metadata.__getitem__,
            requested_family_ids=frozenset(),
        )
    payload = bytearray(tensors[record.labels.payload_hash])
    payload[0] = 0
    changed_ref, changed_bytes = encode_tensor(
        np.frombuffer(bytes(payload), dtype=np.uint8).reshape(2, 3)
    )
    changed = replace(record, labels=changed_ref)
    changed_tensors = {**tensors, changed_ref.payload_hash: changed_bytes}
    with pytest.raises(FitError, match="state differs"):
        materialize_training_arrays(
            changed,
            read_tensor=changed_tensors.__getitem__,
            registry=registry,
            solver_runtime_hash="4" * 64,
            read_label=labels.__getitem__,
            read_feature=features.__getitem__,
            read_metadata=metadata.__getitem__,
            requested_family_ids=frozenset(),
        )


def test_unknown_label_record_remains_masked_zero() -> None:
    record, registry, tensors, labels, features, metadata = _fixture()
    old_hash = record.label_hashes[0][0]
    assert old_hash is not None
    unknown = replace(
        labels.pop(old_hash), state="unknown", reason="incomplete_capture"
    )
    unknown_hash = sha256(unknown.to_canonical_json()).hexdigest()
    labels[unknown_hash] = unknown
    rows = [list(row) for row in record.label_hashes]
    rows[0][0] = unknown_hash
    y = np.array(((0, 0, 1), (0, 1, 0)), dtype=np.uint8)
    mask = np.array(((0, 1, 1), (1, 1, 1)), dtype=np.uint8)
    y_ref, y_bytes = encode_tensor(y)
    m_ref, m_bytes = encode_tensor(mask)
    changed = replace(
        record,
        labels=y_ref,
        known_mask=m_ref,
        label_hashes=tuple(
            cast(tuple[str | None, str | None, str | None], tuple(row)) for row in rows
        ),
    )
    partition = materialize_training_arrays(
        changed,
        read_tensor={
            **tensors,
            y_ref.payload_hash: y_bytes,
            m_ref.payload_hash: m_bytes,
        }.__getitem__,
        registry=registry,
        solver_runtime_hash="4" * 64,
        read_label=labels.__getitem__,
        read_feature=features.__getitem__,
        read_metadata=metadata.__getitem__,
        requested_family_ids=frozenset(),
    )
    assert partition.labels[0, 0] == partition.known_mask[0, 0] == 0


def test_materialize_requires_feature_records_and_rejects_substituted_rows() -> None:
    record, registry, tensors, labels, features, metadata = _fixture()
    kwargs = dict(
        read_tensor=tensors.__getitem__,
        registry=registry,
        solver_runtime_hash="4" * 64,
        read_label=labels.__getitem__,
        read_metadata=metadata.__getitem__,
        requested_family_ids=frozenset(),
    )
    with pytest.raises(FitError, match="feature record reader"):
        materialize_training_arrays(record, read_feature=None, **kwargs)
    feature = features[record.feature_hashes[0]]
    assert CombinedFeatureRecord.from_json(feature.to_canonical_json()) == feature
    for field, value in (
        ("paper_family_id", _uuid(88)),
        ("representation_hash", "9" * 64),
        ("combined_vector", features[record.feature_hashes[1]].combined_vector),
    ):
        changed = replace(feature, **{field: value})
        digest = sha256(changed.to_canonical_json()).hexdigest()
        changed_record = replace(
            record, feature_hashes=(digest, record.feature_hashes[1])
        )
        reader = {**features, digest: changed}.__getitem__
        with pytest.raises(FitError, match="binding differs|tensor differs"):
            materialize_training_arrays(changed_record, read_feature=reader, **kwargs)
    features[record.feature_hashes[0]] = replace(feature, original_source_hash="9" * 64)
    with pytest.raises(IntegrityFailure, match="feature bytes"):
        materialize_training_arrays(record, read_feature=features.__getitem__, **kwargs)


def test_materialize_requires_metadata_records_and_rejects_a_substituted_block() -> (
    None
):
    record, registry, tensors, labels, features, metadata = _fixture()
    kwargs = dict(
        read_tensor=tensors.__getitem__,
        registry=registry,
        solver_runtime_hash="4" * 64,
        read_label=labels.__getitem__,
        read_feature=features.__getitem__,
        requested_family_ids=frozenset(),
    )
    with pytest.raises(FitError, match="card metadata reader"):
        materialize_training_arrays(record, read_metadata=None, **kwargs)
    family_ids = record.ordered_family_ids
    swapped = {
        family_ids[0]: metadata[family_ids[1]],
        family_ids[1]: metadata[family_ids[0]],
    }
    with pytest.raises(FitError, match="metadata block differs"):
        materialize_training_arrays(record, read_metadata=swapped.__getitem__, **kwargs)


def test_feature_record_refuses_mutable_weights_and_wrong_tensor_shape() -> None:
    record, _, _, _, features, _ = _fixture()
    feature = features[record.feature_hashes[0]]
    with pytest.raises(ContractValidationError, match="weights"):
        replace(feature, ordered_passage_weights=[1.0])
    with pytest.raises(ContractValidationError, match="positive"):
        replace(feature, ordered_passage_weights=(0.0,))
    with pytest.raises(ContractValidationError, match="tensor"):
        replace(feature, combined_vector=feature.pooled_passage_vector)
    with pytest.raises(ContractValidationError, match="immutable"):
        replace(record, feature_hashes=list(record.feature_hashes))


def test_arrays_holding_an_agent_requested_paper_never_materialize() -> None:
    record, registry, tensors, labels, features, metadata = _fixture()
    kwargs = dict(
        read_tensor=tensors.__getitem__,
        registry=registry,
        solver_runtime_hash="4" * 64,
        read_label=labels.__getitem__,
        read_feature=features.__getitem__,
        read_metadata=metadata.__getitem__,
    )
    unrelated = frozenset({_uuid(77)})
    assert materialize_training_arrays(record, requested_family_ids=unrelated, **kwargs)
    requested = frozenset({record.ordered_family_ids[1]})
    with pytest.raises(FitError, match="agent-requested"):
        materialize_training_arrays(record, requested_family_ids=requested, **kwargs)
