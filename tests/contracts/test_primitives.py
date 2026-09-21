from __future__ import annotations

import unittest

from research_agent.contracts.primitives import (
    ArtifactRef,
    ContractValidationError,
    ProducerVersion,
    RecordMeta,
    validate_https_url,
    validate_non_empty_string,
    validate_non_negative_int,
    validate_positive_decimal,
    validate_probability,
    validate_sha256,
    validate_utc_instant,
    validate_uuid4,
)


HASH = "a" * 64
UUID4 = "123e4567-e89b-42d3-a456-426614174000"
INSTANT = "2026-09-20T12:34:56.123456Z"


class PrimitiveValidationTests(unittest.TestCase):
    def test_identifiers_and_instants_are_exact(self) -> None:
        self.assertEqual(validate_uuid4(UUID4), UUID4)
        self.assertEqual(validate_sha256(HASH), HASH)
        self.assertEqual(validate_utc_instant(INSTANT), INSTANT)
        for invalid in (UUID4.upper(), "123e4567-e89b-12d3-a456-426614174000"):
            with self.assertRaises(ContractValidationError):
                validate_uuid4(invalid)
        for invalid in ("A" * 64, "a" * 63, "2026-09-20T12:34:56Z"):
            with self.assertRaises(ContractValidationError):
                if len(invalid) == 64 or len(invalid) == 63:
                    validate_sha256(invalid)
                else:
                    validate_utc_instant(invalid)

    def test_numbers_and_text_reject_coercion(self) -> None:
        self.assertEqual(validate_probability(0.5), 0.5)
        self.assertEqual(validate_positive_decimal("0.01"), "0.01")
        for invalid in (True, "1", -1):
            with self.assertRaises(ContractValidationError):
                validate_non_negative_int(invalid)
        with self.assertRaises(ContractValidationError):
            validate_probability(float("nan"))
        with self.assertRaises(ContractValidationError):
            validate_non_empty_string("e\u0301")
        with self.assertRaises(ContractValidationError):
            validate_non_empty_string("\ud800")

    def test_https_url_excludes_credentials_and_fragments(self) -> None:
        self.assertEqual(
            validate_https_url("https://example.test/path?q=x"),
            "https://example.test/path?q=x",
        )
        for invalid in (
            "http://example.test",
            "https://u:p@example.test",
            "https://example.test/#x",
            "https://example.test/#",
            "https://example.test:65536",
            "https://[not-an-ipv6-host",
        ):
            with self.assertRaises(ContractValidationError):
                validate_https_url(invalid)


class SharedRecordTests(unittest.TestCase):
    def test_records_are_closed_and_round_trip_canonically(self) -> None:
        producer = ProducerVersion(HASH, "b" * 40, 1)
        meta = RecordMeta(1, (HASH,), producer, "c" * 64, INSTANT)
        raw = meta.to_canonical_json()

        self.assertEqual(RecordMeta.from_json(raw), meta)
        self.assertEqual(
            ArtifactRef.from_json(
                b'{"artifact_hash":"' + HASH.encode() + b'","schema_version":1}'
            ),
            ArtifactRef(1, HASH),
        )
        with self.assertRaises(ContractValidationError):
            RecordMeta.from_json(raw[:-1] + b',"extra":1}')
        with self.assertRaises(ContractValidationError):
            ArtifactRef(1.0, HASH)
