from __future__ import annotations

import math
import unittest

from research_agent.contracts.canonical import (
    CanonicalJsonError,
    canonical_json,
    canonical_loads,
)


class CanonicalJsonTests(unittest.TestCase):
    def test_sorts_keys_normalizes_strings_and_preserves_arrays(self) -> None:
        value = {"z": ["e\u0301", -0.0, 1e-06], "a": "\u03bc"}

        self.assertEqual(
            canonical_json(value),
            b'{"a":"\xce\xbc","z":["\xc3\xa9",-0.0,1e-06]}',
        )

    def test_rejects_duplicate_keys_before_and_after_normalization(self) -> None:
        with self.assertRaises(CanonicalJsonError):
            canonical_loads(b'{"a":1,"a":2}')
        with self.assertRaises(CanonicalJsonError):
            canonical_loads(b'{"e\xcc\x81":1,"\xc3\xa9":2}')
        with self.assertRaises(CanonicalJsonError):
            canonical_json({"e\u0301": 1, "\u00e9": 2})

    def test_rejects_nonfinite_values_and_invalid_utf8(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            with self.assertRaises(CanonicalJsonError):
                canonical_json(value)
        with self.assertRaises(CanonicalJsonError):
            canonical_loads(b'"\xff"')
        with self.assertRaises(CanonicalJsonError):
            canonical_loads(b"[1e9999]")
        with self.assertRaises(CanonicalJsonError):
            canonical_loads(b"[" + b"1" * 5_000 + b"]")
        with self.assertRaises(CanonicalJsonError):
            canonical_loads(b'"\\ud800"')
