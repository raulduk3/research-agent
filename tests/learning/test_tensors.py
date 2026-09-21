from dataclasses import replace
import struct

import numpy as np
import pytest

from research_agent.contracts import sha256_hex
from research_agent.contracts.learning import TensorRef
from research_agent.learning.tensors import decode_tensor, encode_tensor
from research_agent.storage.errors import IntegrityFailure


def test_exact_little_endian_bytes_roundtrip_and_immutable_decode() -> None:
    source = np.array([[1.0, -2.0], [0.5, 0.0]], dtype=">f4")
    reference, payload = encode_tensor(source)
    assert payload == struct.pack("<ffff", 1.0, -2.0, 0.5, 0.0)
    assert reference == TensorRef.from_json(reference.to_canonical_json())
    decoded = decode_tensor(reference, payload)
    assert decoded.dtype == np.dtype("<f4")
    assert np.array_equal(decoded, source)
    with pytest.raises(ValueError):
        decoded.setflags(write=True)
    source[0, 0] = 99
    assert decoded[0, 0] == 1.0


def test_checksum_length_and_admitted_budget_are_verified_before_decode() -> None:
    reference, payload = encode_tensor(np.zeros((2, 3), dtype=np.uint8))
    for invalid in (payload[:-1], b"\x01" + payload[1:]):
        with pytest.raises(IntegrityFailure):
            decode_tensor(reference, invalid)
    with pytest.raises(ValueError):
        decode_tensor(reference, payload, maximum_bytes=5)
    with pytest.raises(ValueError):
        replace(reference, shape=(3, 3))
    with pytest.raises(ValueError):
        replace(reference, shape=(True, 6))


def test_nonfinite_object_and_nonbinary_payloads_are_refused() -> None:
    for array in (
        np.array([float("nan")]),
        np.array([object()], dtype=object),
        np.array([2], dtype=np.uint8),
        np.zeros((0, 2), dtype=np.float32),
    ):
        with pytest.raises(ValueError):
            encode_tensor(array)
    payload = struct.pack("<d", float("inf"))
    reference = TensorRef(sha256_hex(payload), "float64_le", (1,), "C", 8)
    with pytest.raises(IntegrityFailure):
        decode_tensor(reference, payload)


def test_existing_artifact_owner_reloads_and_reuses_exact_tensor_bytes(
    tmp_path,
) -> None:
    from research_agent.artifacts import ArtifactStore

    reference, payload = encode_tensor(np.array([1.0, 0.0], dtype=np.float64))
    store = ArtifactStore(tmp_path / "artifacts")
    options = dict(
        expected_hash=reference.payload_hash,
        expected_length=reference.byte_length,
        maximum_length=reference.byte_length,
    )
    assert store.commit([payload], **options).created
    assert not store.commit([payload], **options).created
    with store.open_verified(reference.payload_hash) as stream:
        restored = decode_tensor(reference, stream.read())
    assert np.array_equal(restored, np.array([1.0, 0.0]))
    store.path_for(reference.payload_hash).write_bytes(b"x" * reference.byte_length)
    with pytest.raises(IntegrityFailure):
        store.open_verified(reference.payload_hash)
