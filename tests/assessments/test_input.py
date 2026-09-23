from uuid import uuid4

import pytest

from research_agent.assessments.input import (
    AssessmentInput,
    ProviderInputLimit,
    build_assessment_input,
)
from research_agent.assessments.rubric import Rubric
from research_agent.contracts.assessments import JevProviderIdentity
from research_agent.contracts.canonical import canonical_json, sha256_hex
from research_agent.contracts.papers import ExternalIdentifier, PaperVersionRecord
from research_agent.contracts.passages import (
    ExtractedBlock,
    ExtractionRecord,
    SourceLocator,
)
from research_agent.contracts.primitives import ContractValidationError, ProducerVersion

_METADATA_MARKER = "METADATA-ONLY-7731"
_BIBLIOGRAPHY_MARKER = "BIBLIOGRAPHY-ONLY-4410"


class _WordCounter:
    def count(self, text: str) -> int:
        return len(text.split())


def _paper(version_id: str) -> PaperVersionRecord:
    return PaperVersionRecord(
        1,
        ("e" * 64,),
        ProducerVersion("f" * 64, "1" * 40, 1),
        "2" * 64,
        "2026-01-02T00:00:00.000000Z",
        str(uuid4()),
        version_id,
        (ExternalIdentifier("arxiv", "2401.01234v1"),),
        True,
        "2026-01-01T00:00:00.000000Z",
        None,
        ("a" * 64,),
        ("b" * 64,),
        f"Title {_METADATA_MARKER}",
        f"Abstract {_METADATA_MARKER} cited 900 times, trending first",
        ("author",),
        "cs.AI",
        "c" * 64,
        "latex",
        "v1",
        3,
        ("cs.AI",),
        1,
    )


def _extraction(
    version_id: str, blocks: list[tuple[str, str]]
) -> tuple[ExtractionRecord, str]:
    parts: list[str] = []
    records: list[ExtractedBlock] = []
    offset = 0
    for index, (kind, text) in enumerate(blocks):
        excluded = kind in {"bibliography", "page_furniture"}
        records.append(
            ExtractedBlock(
                block_id=f"b{index}",
                section_path=(kind,),
                section_order=index,
                block_order=index,
                kind=kind,
                char_start=offset,
                char_end_exclusive=offset + len(text),
                included_in_passages=not excluded,
                omission_reason=kind if excluded else None,
                locator=SourceLocator("a" * 64, "latex", None, None, None, None),
            )
        )
        parts.append(text)
        offset += len(text)
    text = "".join(parts)
    included = sum(1 for block in records if block.included_in_passages)
    record = ExtractionRecord(
        paper_version_id=version_id,
        source_hash="a" * 64,
        extractor_manifest_hash="b" * 64,
        text_hash=sha256_hex(text.encode("utf-8")),
        text_codepoints=len(text),
        blocks=tuple(records),
        coverage="complete",
        coverage_reasons=(),
        included_block_count=included,
        omitted_block_count=len(records) - included,
        created_at="2026-01-01T00:00:00.000000Z",
    )
    return record, text


def _provider() -> JevProviderIdentity:
    return JevProviderIdentity(
        "typesafe",
        "typesafeai/jev-latest",
        None,
        None,
        "mutable_alias",
        "c" * 64,
        "d" * 64,
    )


def _build(
    blocks: list[tuple[str, str]],
    *,
    max_input_tokens: int = 1_000_000,
) -> AssessmentInput:
    version_id = str(uuid4())
    extraction, text = _extraction(version_id, blocks)
    return build_assessment_input(
        _paper(version_id),
        extraction,
        text,
        Rubric.launch(),
        _provider(),
        limit=ProviderInputLimit(max_input_tokens),
        counter=_WordCounter(),
        smoke_report_hash=None,
    )


def test_input_is_the_extracted_content_in_document_order_without_metadata() -> None:
    built = _build(
        [
            ("body", "Intro text. "),
            ("caption", "Figure 1 caption. "),
            ("bibliography", f"{_BIBLIOGRAPHY_MARKER} [1] Ref. "),
            ("table", "Table 1 row. "),
            ("appendix", "Appendix proof."),
        ]
    )
    assert built.sendable
    assert built.state_text == (
        "Intro text. \n\nFigure 1 caption. \n\nTable 1 row. \n\nAppendix proof."
    )
    assert _METADATA_MARKER not in built.state_text
    assert _BIBLIOGRAPHY_MARKER not in built.state_text
    assert "cited" not in built.state_text
    assert built.record.supplied_text_hash == sha256_hex(
        built.state_text.encode("utf-8")
    )
    assert built.record.coverage == "complete"


def test_multibyte_text_at_the_byte_boundary_is_admitted_and_one_past_is_not() -> None:
    at_limit = _build([("body", "é" * 65536)])
    assert at_limit.record.supplied_text_bytes == 131072
    assert at_limit.sendable
    over = _build([("body", "é" * 65536 + "a")])
    assert over.record.supplied_text_bytes == 131073
    assert over.unavailable_reason == "input_too_large"


def test_rubric_overhead_counts_against_the_provider_token_limit() -> None:
    text = "word " * 100
    overhead = _WordCounter().count(
        canonical_json(Rubric.launch().choice_questions()).decode("utf-8")
    )
    fits = _build([("body", text)], max_input_tokens=100 + overhead)
    assert fits.sendable
    too_many = _build([("body", text)], max_input_tokens=100 + overhead - 1)
    assert too_many.unavailable_reason == "input_too_large"
    assert too_many.state_text == text


def test_empty_usable_text_is_missing_input_and_never_truncated() -> None:
    built = _build([("bibliography", "[1] Only references.")])
    assert built.unavailable_reason == "missing_input"
    assert built.state_text == ""
    assert built.record.coverage == "unavailable"
    assert "empty_text" in built.record.coverage_reasons


def test_text_that_is_not_the_extractions_own_is_refused() -> None:
    version_id = str(uuid4())
    extraction, text = _extraction(version_id, [("body", "Real text.")])
    with pytest.raises(ContractValidationError):
        build_assessment_input(
            _paper(version_id),
            extraction,
            "Real text!",
            Rubric.launch(),
            _provider(),
            limit=ProviderInputLimit(1000),
            counter=_WordCounter(),
            smoke_report_hash=None,
        )
    with pytest.raises(ContractValidationError):
        build_assessment_input(
            _paper(str(uuid4())),
            extraction,
            text,
            Rubric.launch(),
            _provider(),
            limit=ProviderInputLimit(1000),
            counter=_WordCounter(),
            smoke_report_hash=None,
        )
