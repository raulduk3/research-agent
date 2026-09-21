"""Exact non-executable tensor bytes for immutable artifact publication."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from research_agent.contracts import sha256_hex
from research_agent.contracts.learning import TensorRef
from research_agent.storage.errors import IntegrityFailure

_DTYPES: dict[str, np.dtype[np.generic]] = {
    "float32_le": np.dtype("<f4"),
    "float64_le": np.dtype("<f8"),
    "uint8": np.dtype("u1"),
}


def encode_tensor(array: NDArray[np.generic]) -> tuple[TensorRef, bytes]:
    if array.ndim not in {1, 2} or any(size <= 0 for size in array.shape):
        raise ValueError("tensor shape must have one or two nonempty dimensions")
    if array.dtype.kind == "f" and array.dtype.itemsize in {4, 8}:
        dtype = "float32_le" if array.dtype.itemsize == 4 else "float64_le"
        if not np.isfinite(array).all():
            raise ValueError("tensor contains nonfinite coordinates")
    elif array.dtype == np.dtype("u1"):
        dtype = "uint8"
        if not np.isin(array, (0, 1)).all():
            raise ValueError("label and mask tensor bytes must be binary")
    else:
        raise ValueError("tensor dtype is not admitted")
    payload = array.astype(_DTYPES[dtype], copy=False).tobytes(order="C")
    reference = TensorRef(
        sha256_hex(payload), dtype, tuple(array.shape), "C", len(payload)
    )
    return reference, payload


def decode_tensor(
    reference: TensorRef, payload: bytes, *, maximum_bytes: int = 256 * 1024 * 1024
) -> NDArray[np.generic]:
    if type(maximum_bytes) is not int or maximum_bytes <= 0:
        raise ValueError("tensor decode budget must be a positive integer")
    if not isinstance(payload, bytes):
        raise ValueError("tensor decoding requires immutable bytes")
    if reference.byte_length > maximum_bytes:
        raise ValueError("tensor exceeds admitted decode budget")
    if (
        len(payload) != reference.byte_length
        or sha256_hex(payload) != reference.payload_hash
    ):
        raise IntegrityFailure("tensor bytes do not match reference")
    array = np.frombuffer(payload, dtype=_DTYPES[reference.dtype]).reshape(
        reference.shape
    )
    if not np.isfinite(array).all():
        raise IntegrityFailure("tensor has nonfinite coordinates")
    if reference.dtype == "uint8" and not np.isin(array, (0, 1)).all():
        raise IntegrityFailure("label or mask tensor is not binary")
    # The base is immutable bytes, so callers cannot re-enable writeability.
    return array
