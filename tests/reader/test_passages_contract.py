from dataclasses import replace
from uuid import uuid4

import pytest

from research_agent.contracts import ContractValidationError
from research_agent.contracts.passages import (
    CHUNK_POLICY,
    ExtractedBlock,
    ExtractionRecord,
    PassageRecord,
    ResourceDemand,
    SourceLocator,
)


def _locator(**overrides: object) -> SourceLocator:
    values: dict[str, object] = {
        "source_hash": "a" * 64,
        "kind": "latex",
        "page_number": None,
        "source_member": None,
        "source_line_start": None,
        "source_line_end_inclusive": None,
    }
    values.update(overrides)
    return SourceLocator(**values)  # type: ignore[arg-type]


def _block(**overrides: object) -> ExtractedBlock:
    values: dict[str, object] = {
        "block_id": "b0",
        "section_path": ("Introduction",),
        "section_order": 0,
        "block_order": 0,
        "kind": "body",
        "char_start": 0,
        "char_end_exclusive": 10,
        "included_in_passages": True,
        "omission_reason": None,
        "locator": _locator(),
    }
    values.update(overrides)
    return ExtractedBlock(**values)  # type: ignore[arg-type]


def test_source_locator_round_trips_and_requires_a_full_line_range() -> None:
    locator = _locator(page_number=3, source_line_start=4, source_line_end_inclusive=6)
    assert SourceLocator.from_json(locator.to_canonical_json()) == locator
    with pytest.raises(ContractValidationError):
        _locator(source_line_start=4)
    with pytest.raises(ContractValidationError):
        _locator(source_line_start=6, source_line_end_inclusive=4)
    with pytest.raises(ContractValidationError):
        _locator(kind="ocr")


def test_extracted_block_separates_included_content_from_omitted_regions() -> None:
    block = _block()
    assert ExtractedBlock.from_json(block.to_canonical_json()) == block
    with pytest.raises(ContractValidationError):
        replace(block, omission_reason="parse_failure")
    with pytest.raises(ContractValidationError):
        replace(block, char_end_exclusive=block.char_start)
    excluded = _block(
        kind="bibliography",
        included_in_passages=False,
        omission_reason="bibliography",
        char_end_exclusive=20,
    )
    assert ExtractedBlock.from_json(excluded.to_canonical_json()) == excluded
    with pytest.raises(ContractValidationError):
        replace(excluded, omission_reason=None)
    with pytest.raises(ContractValidationError):
        replace(excluded, omission_reason="unreadable")
    unreadable = _block(
        block_id="b1",
        kind="unreadable",
        included_in_passages=False,
        omission_reason="unreadable",
        char_start=5,
        char_end_exclusive=5,
    )
    assert ExtractedBlock.from_json(unreadable.to_canonical_json()) == unreadable


def test_extraction_record_counts_and_orders_its_own_blocks() -> None:
    version_id = str(uuid4())
    body = _block()
    excluded = _block(
        block_id="b1",
        block_order=1,
        kind="bibliography",
        included_in_passages=False,
        omission_reason="bibliography",
        char_start=10,
        char_end_exclusive=30,
    )
    record = ExtractionRecord(
        paper_version_id=version_id,
        source_hash="a" * 64,
        extractor_manifest_hash="b" * 64,
        text_hash="c" * 64,
        text_codepoints=30,
        blocks=(body, excluded),
        coverage="complete",
        coverage_reasons=(),
        included_block_count=1,
        omitted_block_count=1,
        created_at="2026-01-01T00:00:00.000000Z",
    )
    assert ExtractionRecord.from_json(record.to_canonical_json()) == record

    with pytest.raises(ContractValidationError):
        replace(record, included_block_count=2)
    with pytest.raises(ContractValidationError):
        replace(record, coverage_reasons=("empty_text",))
    with pytest.raises(ContractValidationError):
        replace(record, coverage="partial")
    with pytest.raises(ContractValidationError):
        replace(record, text_codepoints=5)
    reordered = (
        replace(excluded, block_order=0),
        replace(body, block_order=1),
    )
    with pytest.raises(ContractValidationError):
        replace(record, blocks=reordered)
    overlapping = replace(body, char_end_exclusive=25)
    with pytest.raises(ContractValidationError):
        replace(record, blocks=(overlapping, excluded))


def test_passage_record_round_trips_and_bounds_its_token_span() -> None:
    version_id = str(uuid4())
    passage = PassageRecord(
        paper_version_id=version_id,
        extraction_hash="d" * 64,
        chunk_policy=CHUNK_POLICY,
        section_order=0,
        section_path=("Introduction",),
        passage_order=0,
        section_token_start=0,
        section_token_end_exclusive=384,
        char_start=0,
        char_end_exclusive=1200,
        block_ids=("b0",),
        text_hash="e" * 64,
        source_locators=(_locator(),),
        overlap_adjusted_weight=384.0,
    )
    assert PassageRecord.from_json(passage.to_canonical_json()) == passage

    with pytest.raises(ContractValidationError):
        replace(passage, chunk_policy="passages-512-0-v1")
    with pytest.raises(ContractValidationError):
        replace(passage, section_token_end_exclusive=385)
    with pytest.raises(ContractValidationError):
        replace(passage, section_token_start=10, section_token_end_exclusive=10)
    with pytest.raises(ContractValidationError):
        replace(passage, overlap_adjusted_weight=0)
    with pytest.raises(ContractValidationError):
        replace(passage, block_ids=())


def test_resource_demand_rejects_a_negative_duration() -> None:
    demand = ResourceDemand(0.125, 4096)
    assert ResourceDemand.from_json(demand.to_canonical_json()) == demand
    with pytest.raises(ContractValidationError):
        ResourceDemand(-0.001, 0)
