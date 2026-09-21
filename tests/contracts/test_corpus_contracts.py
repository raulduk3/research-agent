from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, cast
from uuid import uuid4

import pytest

from research_agent.contracts import (
    ContractValidationError,
    ProducerVersion,
    canonical_json,
)
from research_agent.contracts.corpus import CorpusRelease, CorpusRow, TemporalSplit

STAMP = "2026-09-21T00:00:00.000000Z"
META = (1, (), ProducerVersion("a" * 64, "b" * 40, 1), "c" * 64, STAMP)


def row() -> CorpusRow:
    return CorpusRow(
        str(uuid4()),
        str(uuid4()),
        STAMP,
        "2026-W39",
        "cs.AI",
        0,
        "d" * 64,
        (None, None, None),
        (False, False, False),
        "pilot",
        (),
    )


def split() -> TemporalSplit:
    monday = datetime(2025, 1, 6, tzinfo=timezone.utc)
    weeks = tuple(
        (monday + timedelta(weeks=index)).strftime("%G-W%V") for index in range(40)
    )
    return TemporalSplit(
        *META, weeks, weeks[:24], weeks[24:30], weeks[30:34], weeks[34:], "e" * 64, True
    )


def test_corpus_row_closed_roundtrip_and_utc_week() -> None:
    record = row()
    assert CorpusRow.from_json(record.to_canonical_json()) == record
    with pytest.raises(ContractValidationError, match="week differs"):
        replace(record, publication_week="2026-W38")
    with pytest.raises(ContractValidationError, match="known mask"):
        replace(record, known_mask=(True, False, False))
    with pytest.raises(ContractValidationError, match="three entries"):
        replace(record, label_hashes=cast(Any, [None, None, None]))
    with pytest.raises(ContractValidationError, match="requires a reason"):
        replace(record, partition="excluded")
    with pytest.raises(ContractValidationError, match="shortfall cannot"):
        replace(record, partition="fit", exclusion_reasons=("shortfall",))
    assert replace(record, partition="fit", exclusion_reasons=("missing_label",))
    body = {**__import__("json").loads(record.to_canonical_json()), "extra": 1}
    with pytest.raises(ContractValidationError, match="fields"):
        CorpusRow.from_json(canonical_json(body))


def test_temporal_split_exact_boundaries_and_chronological_weeks() -> None:
    record = split()
    assert TemporalSplit.from_json(record.to_canonical_json()) == record
    with pytest.raises(ContractValidationError, match="boundaries"):
        replace(record, fit_weeks=record.fit_weeks[1:])
    broken = (
        *record.ordered_weeks[:20],
        record.ordered_weeks[21],
        record.ordered_weeks[20],
        *record.ordered_weeks[22:],
    )
    with pytest.raises(ContractValidationError, match="chronological"):
        replace(record, ordered_weeks=broken)
    gapped = (*record.ordered_weeks[:20], *record.ordered_weeks[21:], "2025-W42")
    assert TemporalSplit(
        *META,
        gapped,
        gapped[:24],
        gapped[24:30],
        gapped[30:34],
        gapped[34:],
        "e" * 64,
        True,
    )
    with pytest.raises(ContractValidationError, match="precede"):
        replace(record, created_before_outcome_inspection=False)


def test_corpus_release_fixed_population_and_shortfall() -> None:
    selected = row()
    record = CorpusRelease(
        *META,
        "acquisition_pilot",
        "d" * 64,
        "e" * 64,
        20260920,
        STAMP,
        STAMP,
        100,
        "f" * 64,
        (selected,),
        99,
        "1" * 64,
        "2" * 64,
        (),
        None,
    )
    assert CorpusRelease.from_json(record.to_canonical_json()) == record
    with pytest.raises(ContractValidationError, match="fixed protocol"):
        replace(record, intended_population_count=101, shortfall_count=100)
    with pytest.raises(ContractValidationError, match="shortfall"):
        replace(record, shortfall_count=98)
    with pytest.raises(ContractValidationError, match="unique families"):
        replace(record, rows=(selected, selected), shortfall_count=98)
    # A refresh can retain earlier rows while its intended count describes a
    # newly frozen acquisition denominator; admission checks that enumeration.
    refresh = replace(
        record,
        purpose="weekly_refresh",
        intended_population_count=2,
        shortfall_count=0,
    )
    assert CorpusRelease.from_json(refresh.to_canonical_json()) == refresh
